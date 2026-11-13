/*
 * The flip model (OPENDMT3_FLIP_MODEL=on; the Screen page's Advanced, off by default): the game's device made with
 * Direct3D 9Ex and a D3DSWAPEFFECT_FLIPEX swap chain, so each frame's back buffer is handed to Windows' compositor
 * instead of copied into its own surface: a copy of the whole screen less a frame, and the way to Windows' independent
 * flip and to a variable refresh rate for a borderless window, neither of which the copy (blt) model gets. Only for a
 * borderless window over its whole monitor with the chain running (FLIPEX presents its whole back buffer, so the back
 * buffer is the window's size); any other start, or a device that cannot be made so, is the copy as before.
 *
 * A Direct3D 9Ex device has no managed pool (Direct3D refuses it there). Every texture, cube or volume texture, vertex
 * and index buffer asked of the managed pool, by the game, its D3DX loader or openDMT3, is made in the default pool as
 * a dynamic one instead: lockable as a managed one is, and kept through a reset (on 9Ex a reset loses nothing).
 */
#include "ingame.h"
#include "methods.h"

#include <d3d9.h>

/* Direct3DCreate9Ex, from the d3d9.dll the game already loaded. */
typedef HRESULT(WINAPI *CreateExFn)(UINT, IDirect3D9Ex **);
/* The device's methods that make resources, by their place in IDirect3DDevice9's table. */
#define M_CREATE_TEXTURE 23
#define M_CREATE_VOLUME_TEXTURE 24
#define M_CREATE_CUBE_TEXTURE 25
#define M_CREATE_VERTEX_BUFFER 26
#define M_CREATE_INDEX_BUFFER 27
typedef HRESULT(STDMETHODCALLTYPE *CreateTextureFn)(IDirect3DDevice9 *, UINT, UINT, UINT, DWORD, D3DFORMAT, D3DPOOL,
                                                    IDirect3DTexture9 **, HANDLE *);
typedef HRESULT(STDMETHODCALLTYPE *CreateVolumeFn)(IDirect3DDevice9 *, UINT, UINT, UINT, UINT, DWORD, D3DFORMAT,
                                                   D3DPOOL, IDirect3DVolumeTexture9 **, HANDLE *);
typedef HRESULT(STDMETHODCALLTYPE *CreateCubeFn)(IDirect3DDevice9 *, UINT, UINT, DWORD, D3DFORMAT, D3DPOOL,
                                                 IDirect3DCubeTexture9 **, HANDLE *);
typedef HRESULT(STDMETHODCALLTYPE *CreateVertexBufferFn)(IDirect3DDevice9 *, UINT, DWORD, DWORD, D3DPOOL,
                                                         IDirect3DVertexBuffer9 **, HANDLE *);
typedef HRESULT(STDMETHODCALLTYPE *CreateIndexBufferFn)(IDirect3DDevice9 *, UINT, DWORD, D3DFORMAT, D3DPOOL,
                                                        IDirect3DIndexBuffer9 **, HANDLE *);
static CreateTextureFn real_create_texture;
static CreateVolumeFn real_create_volume;
static CreateCubeFn real_create_cube;
static CreateVertexBufferFn real_create_vb;
static CreateIndexBufferFn real_create_ib;

/* The 9Ex object made beside the game's own (NULL: the choice is off, or Windows has no 9Ex), the device made on it
 * (NULL: the copy model, as before), and the resources moved from the managed pool, and those Direct3D refused even so
 * (counted, the first few logged). */
static IDirect3D9Ex *g_ex;
static IDirect3DDevice9 *g_device;
static LONG g_moved_textures, g_moved_buffers, g_refused;

void flip_attach_d3d(void)
{
    if (!g_settings.flip || g_ex)
        return;
    HMODULE d3d9 = GetModuleHandleA("d3d9.dll");
    CreateExFn create = d3d9 ? (CreateExFn)(void *)GetProcAddress(d3d9, "Direct3DCreate9Ex") : NULL;
    HRESULT hr = create ? create(D3D_SDK_VERSION, &g_ex) : E_NOTIMPL;
    if (FAILED(hr))
        g_ex = NULL;
    ingame_log("flip: %s", g_ex ? "Direct3D 9Ex made beside the game's Direct3D 9"
                                : "no Direct3D 9Ex on this Windows: the copy model, as before");
}

int flip_wanted(const D3DPRESENT_PARAMETERS *pp, HWND window)
{
    if (!g_ex || !pp || !pp->Windowed || !window)
        return 0;
    /* Over the whole of its monitor (the borderless full screen): its client the monitor's size. */
    RECT client;
    MONITORINFO mi;
    mi.cbSize = sizeof mi;
    if (!GetClientRect(window, &client) || !GetMonitorInfoA(MonitorFromWindow(window, MONITOR_DEFAULTTONEAREST), &mi))
        return 0;
    int whole = client.right == mi.rcMonitor.right - mi.rcMonitor.left &&
                client.bottom == mi.rcMonitor.bottom - mi.rcMonitor.top;
    if (!whole)
        ingame_log("flip: the game's window (%ldx%ld) is not its whole monitor: the copy model", client.right,
                   client.bottom);
    return whole;
}

/* ---------------------------------------------------------------------------------------- no managed pool */

/* A texture's and a surface's LockRect, by their place in IDirect3DTexture9's and IDirect3DSurface9's tables. */
#define M_TEXTURE_LOCK_RECT 19
#define M_SURFACE_LOCK_RECT 13
typedef HRESULT(STDMETHODCALLTYPE *TextureLockFn)(IDirect3DTexture9 *, UINT, D3DLOCKED_RECT *, const RECT *, DWORD);
typedef HRESULT(STDMETHODCALLTYPE *SurfaceLockFn)(IDirect3DSurface9 *, D3DLOCKED_RECT *, const RECT *, DWORD);
static TextureLockFn real_texture_lock;
static SurfaceLockFn real_surface_lock;
/* Locks on the default pool's dynamic levels that only read, taken as writes (counted for the log): the game locks its
 * video's A8 planes every frame with D3DLOCK_READONLY and writes them (measured under Wine: six 640 x 384 textures, one
 * lock each a frame), which a managed texture's copy in memory keeps; a read lock on the default pool hands nothing
 * back to the card, and the video stayed green. */
static LONG g_reads_as_writes;

/* The flags a lock of a level described by `d` goes with: without D3DLOCK_READONLY on the default pool's dynamic
 * levels (where every managed one is made with the flip model). */
static DWORD lock_flags(const D3DSURFACE_DESC *d, DWORD flags)
{
    if ((flags & D3DLOCK_READONLY) && d->Pool == D3DPOOL_DEFAULT && (d->Usage & D3DUSAGE_DYNAMIC)) {
        g_reads_as_writes++;
        return flags & ~(DWORD)D3DLOCK_READONLY;
    }
    return flags;
}

static HRESULT STDMETHODCALLTYPE our_texture_lock(IDirect3DTexture9 *t, UINT level, D3DLOCKED_RECT *lr,
                                                  const RECT *rect, DWORD flags)
{
    D3DSURFACE_DESC d;
    if (SUCCEEDED(IDirect3DTexture9_GetLevelDesc(t, level, &d)))
        flags = lock_flags(&d, flags);
    return real_texture_lock(t, level, lr, rect, flags);
}

static HRESULT STDMETHODCALLTYPE our_surface_lock(IDirect3DSurface9 *s, D3DLOCKED_RECT *lr, const RECT *rect,
                                                  DWORD flags)
{
    D3DSURFACE_DESC d;
    if (SUCCEEDED(IDirect3DSurface9_GetDesc(s, &d)))
        flags = lock_flags(&d, flags);
    return real_surface_lock(s, lr, rect, flags);
}

/* Put `ours` in entry `index` of an object's method table (one table for every object of its kind), keeping what was
 * there in *real (once). */
static void turn_object(void *object, int index, void *ours, void **real)
{
    /* The object's method table: its first pointer. */
    void **table = *(void ***)object;
    /* Already turned (the table every object of the kind shares): nothing to do. */
    if (table[index] == ours)
        return;
    /* Another table for the same kind whose entry is another function: one real function is kept a slot, so it is
     * left as it is (its objects' read locks stay as Direct3D takes them), said once. */
    if (*real && *real != table[index]) {
        static int said;
        if (!said++)
            ingame_log("flip: a second method table for one kind of object: its locks left as they are");
        return;
    }
    /* The table's page made writable for the one entry, then given its protection back. */
    DWORD old;
    if (!VirtualProtect(&table[index], sizeof(void *), PAGE_READWRITE, &old))
        return;
    /* The real function kept for ours to call, ours in its place. */
    *real = table[index];
    table[index] = ours;
    VirtualProtect(&table[index], sizeof(void *), old, &old);
    /* Watched every frame, put back if Direct3D fills its table in again (methods.c). */
    methods_watch(&table[index], ours, "the flip model's", index);
}

/* The locks of a texture moved from the managed pool, and of its levels' surfaces, taken as a managed texture's. */
static void mend_locks_of(IDirect3DTexture9 *t)
{
    turn_object(t, M_TEXTURE_LOCK_RECT, (void *)our_texture_lock, (void **)&real_texture_lock);
    IDirect3DSurface9 *s = NULL;
    if (SUCCEEDED(IDirect3DTexture9_GetSurfaceLevel(t, 0, &s)) && s) {
        turn_object(s, M_SURFACE_LOCK_RECT, (void *)our_surface_lock, (void **)&real_surface_lock);
        IDirect3DSurface9_Release(s);
    }
}

static void refused(const char *what, D3DFORMAT format, DWORD usage, HRESULT hr)
{
    /* The first few in the log: the format and usage the default pool would not take as dynamic. */
    if (g_refused++ < 8)
        ingame_log("flip: a managed %s (format %d, usage 0x%lx) could not be made dynamic (0x%08lx)", what,
                   (int)format, (unsigned long)usage, (unsigned long)hr);
}

static HRESULT STDMETHODCALLTYPE our_create_texture(IDirect3DDevice9 *dev, UINT w, UINT h, UINT levels, DWORD usage,
                                                    D3DFORMAT format, D3DPOOL pool, IDirect3DTexture9 **out,
                                                    HANDLE *shared)
{
    if (pool != D3DPOOL_MANAGED)
        return real_create_texture(dev, w, h, levels, usage, format, pool, out, shared);
    /* Dynamic in the default pool: lockable at every level, as the loader fills a managed one. */
    HRESULT hr = real_create_texture(dev, w, h, levels, usage | D3DUSAGE_DYNAMIC, format, D3DPOOL_DEFAULT, out, shared);
    if (SUCCEEDED(hr) && out && *out) {
        g_moved_textures++;
        /* Its locks as a managed texture's (a read lock the game writes through reaches the card). */
        mend_locks_of(*out);
    } else {
        refused("texture", format, usage, hr);
    }
    return hr;
}

static HRESULT STDMETHODCALLTYPE our_create_volume(IDirect3DDevice9 *dev, UINT w, UINT h, UINT d, UINT levels,
                                                   DWORD usage, D3DFORMAT format, D3DPOOL pool,
                                                   IDirect3DVolumeTexture9 **out, HANDLE *shared)
{
    if (pool != D3DPOOL_MANAGED)
        return real_create_volume(dev, w, h, d, levels, usage, format, pool, out, shared);
    HRESULT hr = real_create_volume(dev, w, h, d, levels, usage | D3DUSAGE_DYNAMIC, format, D3DPOOL_DEFAULT, out,
                                    shared);
    if (SUCCEEDED(hr))
        g_moved_textures++;
    else
        refused("volume texture", format, usage, hr);
    return hr;
}

static HRESULT STDMETHODCALLTYPE our_create_cube(IDirect3DDevice9 *dev, UINT edge, UINT levels, DWORD usage,
                                                 D3DFORMAT format, D3DPOOL pool, IDirect3DCubeTexture9 **out,
                                                 HANDLE *shared)
{
    if (pool != D3DPOOL_MANAGED)
        return real_create_cube(dev, edge, levels, usage, format, pool, out, shared);
    HRESULT hr = real_create_cube(dev, edge, levels, usage | D3DUSAGE_DYNAMIC, format, D3DPOOL_DEFAULT, out, shared);
    if (SUCCEEDED(hr))
        g_moved_textures++;
    else
        refused("cube texture", format, usage, hr);
    return hr;
}

static HRESULT STDMETHODCALLTYPE our_create_vb(IDirect3DDevice9 *dev, UINT length, DWORD usage, DWORD fvf,
                                               D3DPOOL pool, IDirect3DVertexBuffer9 **out, HANDLE *shared)
{
    if (pool != D3DPOOL_MANAGED)
        return real_create_vb(dev, length, usage, fvf, pool, out, shared);
    /* Dynamic: a lock with no flags (as the game writes a managed buffer) is allowed on it. */
    HRESULT hr = real_create_vb(dev, length, usage | D3DUSAGE_DYNAMIC, fvf, D3DPOOL_DEFAULT, out, shared);
    if (SUCCEEDED(hr))
        g_moved_buffers++;
    else
        refused("vertex buffer", D3DFMT_VERTEXDATA, usage, hr);
    return hr;
}

static HRESULT STDMETHODCALLTYPE our_create_ib(IDirect3DDevice9 *dev, UINT length, DWORD usage, D3DFORMAT format,
                                               D3DPOOL pool, IDirect3DIndexBuffer9 **out, HANDLE *shared)
{
    if (pool != D3DPOOL_MANAGED)
        return real_create_ib(dev, length, usage, format, pool, out, shared);
    HRESULT hr = real_create_ib(dev, length, usage | D3DUSAGE_DYNAMIC, format, D3DPOOL_DEFAULT, out, shared);
    if (SUCCEEDED(hr))
        g_moved_buffers++;
    else
        refused("index buffer", format, usage, hr);
    return hr;
}

/* ------------------------------------------------------------------------------------------- 9Ex kept hidden */

/* QueryInterface, the first entry of every COM table. */
typedef HRESULT(STDMETHODCALLTYPE *QueryFn)(IUnknown *, REFIID, void **);
static QueryFn real_device_query, real_d3d_query;

/* The device and the Direct3D object answer to every interface but 9Ex's: the game's D3DX (d3dx9_40) asks for them and,
 * told it is on 9Ex, refuses to make an empty texture in the managed pool (D3DXCreateTexture: the game's 512 x 512
 * glyph textures were never made, measured under Wine), where on Direct3D 9 it asks for the managed pool, which the
 * stand-in above takes. openDMT3 uses the 9Ex interfaces it made itself, never through QueryInterface. */
static HRESULT STDMETHODCALLTYPE our_device_query(IUnknown *self, REFIID riid, void **out)
{
    if (riid && IsEqualGUID(riid, &IID_IDirect3DDevice9Ex)) {
        if (out)
            *out = NULL;
        return E_NOINTERFACE;
    }
    return real_device_query(self, riid, out);
}

static HRESULT STDMETHODCALLTYPE our_d3d_query(IUnknown *self, REFIID riid, void **out)
{
    if (riid && IsEqualGUID(riid, &IID_IDirect3D9Ex)) {
        if (out)
            *out = NULL;
        return E_NOINTERFACE;
    }
    return real_d3d_query(self, riid, out);
}

/* ------------------------------------------------------------------------------------------------ the device */

long flip_create_device(UINT adapter, int type, HWND focus, DWORD flags, D3DPRESENT_PARAMETERS *pp,
                        IDirect3DDevice9 **out)
{
    if (!g_ex || !out)
        return E_FAIL;
    IDirect3DDevice9Ex *dev = NULL;
    /* Windowed: no full-screen mode given. Its present statistics asked for (what each present was shown at). */
    HRESULT hr = IDirect3D9Ex_CreateDeviceEx(g_ex, adapter, (D3DDEVTYPE)type, focus,
                                             flags | D3DCREATE_ENABLE_PRESENTSTATS, pp, NULL, &dev);
    if (FAILED(hr) || !dev) {
        ingame_log("flip: the Direct3D 9Ex device with a flip swap chain was not made (0x%08lx): the copy model",
                   (unsigned long)hr);
        return FAILED(hr) ? hr : E_FAIL;
    }
    /* At most one frame queued by Direct3D itself, as openDMT3's own event query keeps it. */
    IDirect3DDevice9Ex_SetMaximumFrameLatency(dev, 1);
    IDirect3DDevice9 *d = (IDirect3DDevice9 *)dev;
    /* 9Ex hidden from the game and its D3DX, the device and the Direct3D object it answers with both. */
    turn_object(d, 0, (void *)our_device_query, (void **)&real_device_query);
    turn_object(g_ex, 0, (void *)our_d3d_query, (void **)&real_d3d_query);
    turn_object(d, M_CREATE_TEXTURE, (void *)our_create_texture, (void **)&real_create_texture);
    turn_object(d, M_CREATE_VOLUME_TEXTURE, (void *)our_create_volume, (void **)&real_create_volume);
    turn_object(d, M_CREATE_CUBE_TEXTURE, (void *)our_create_cube, (void **)&real_create_cube);
    turn_object(d, M_CREATE_VERTEX_BUFFER, (void *)our_create_vb, (void **)&real_create_vb);
    turn_object(d, M_CREATE_INDEX_BUFFER, (void *)our_create_ib, (void **)&real_create_ib);
    g_device = d;
    *out = d;
    ingame_log("flip: device made with Direct3D 9Ex, %u back buffers flipped (%ux%u), the managed pool moved to the "
               "default pool", pp->BackBufferCount, pp->BackBufferWidth, pp->BackBufferHeight);
    return hr;
}

int flip_device(IDirect3DDevice9 *dev)
{
    return dev && dev == g_device;
}

long flip_reset(IDirect3DDevice9 *dev, D3DPRESENT_PARAMETERS *pp)
{
    /* 9Ex's own reset: the swap chain's size and kind changed, every other resource and state kept. A window needs no
     * display mode; exclusive full screen (openDMT3 never sets it up, the game might) needs its mode given. */
    if (!pp || pp->Windowed)
        return IDirect3DDevice9Ex_ResetEx((IDirect3DDevice9Ex *)dev, pp, NULL);
    D3DDISPLAYMODEEX mode;
    memset(&mode, 0, sizeof mode);
    mode.Size = sizeof mode;
    mode.Width = pp->BackBufferWidth;
    mode.Height = pp->BackBufferHeight;
    mode.RefreshRate = pp->FullScreen_RefreshRateInHz;
    mode.Format = pp->BackBufferFormat;
    mode.ScanLineOrdering = D3DSCANLINEORDERING_PROGRESSIVE;
    return IDirect3DDevice9Ex_ResetEx((IDirect3DDevice9Ex *)dev, pp, &mode);
}

/* What the presents were shown at (present statistics; Windows' flip model gives them, Wine's are zeros): the last
 * shown present's number and its refresh, read after each of the game's own frames, the presents and the refreshes
 * counted between those readings over the counter's two seconds, and whether the display has been found to follow the
 * frames (a variable refresh rate: one refresh a frame, where a fixed rate gives N). */
static UINT g_last_count, g_last_refresh;
static LONG g_shown, g_refreshes, g_one_steps, g_steps;
static int g_follows;

void flip_after_present(void)
{
    if (!g_device)
        return;
    /* The swap chain asked for each time, never kept: a reference kept would keep the device alive past the game's
     * last release of it. */
    IDirect3DSwapChain9 *sc = NULL;
    IDirect3DSwapChain9Ex *chain = NULL;
    if (SUCCEEDED(IDirect3DDevice9_GetSwapChain(g_device, 0, &sc))) {
        IDirect3DSwapChain9_QueryInterface(sc, &IID_IDirect3DSwapChain9Ex, (void **)&chain);
        IDirect3DSwapChain9_Release(sc);
    }
    if (!chain)
        return;
    D3DPRESENTSTATS st;
    HRESULT hr = IDirect3DSwapChain9Ex_GetPresentStats(chain, &st);
    IDirect3DSwapChain9Ex_Release(chain);
    /* Nothing shown yet, or no statistics given: nothing to count. */
    if (FAILED(hr) || !st.PresentCount)
        return;
    /* A newer present shown since the last reading: how many presents, over how many refreshes. */
    if (g_last_count && st.PresentCount > g_last_count && st.PresentRefreshCount >= g_last_refresh) {
        UINT presents = st.PresentCount - g_last_count, refreshes = st.PresentRefreshCount - g_last_refresh;
        g_shown += (LONG)presents;
        g_refreshes += (LONG)refreshes;
        /* One present since the last frame's reading (a frame with no sub-frames), and whether it took one refresh of
         * a display whose mode says more. */
        if (presents == 1) {
            g_steps++;
            g_one_steps += refreshes == 1;
        }
    }
    g_last_count = st.PresentCount;
    g_last_refresh = st.PresentRefreshCount;
}

int flip_follows_frames(void)
{
    return g_follows;
}

void flip_before_reset(void)
{
    /* The swap chain is made again by a reset: its statistics start again with it. */
    g_last_count = g_last_refresh = 0;
}

void flip_summary(int refreshes_a_frame)
{
    if (!g_device)
        return;
    ingame_log("flip: %ld textures and %ld buffers moved from the managed pool, %ld refused; %ld read locks taken as "
               "writes", (long)g_moved_textures, (long)g_moved_buffers, (long)g_refused, (long)g_reads_as_writes);
    if (!g_shown) {
        ingame_log("flip: no present statistics (none shown yet, or none given here)");
        return;
    }
    ingame_log("flip: %ld presents shown over %ld refreshes (%.2f a present), %ld of %ld single presents in one "
               "refresh", (long)g_shown, (long)g_refreshes, (double)g_refreshes / (double)g_shown, (long)g_one_steps,
               (long)g_steps);
    /* Nine in ten single presents shown a refresh apart on a display whose mode gives each frame two or more: the
     * display waits for the frames (a variable refresh rate), so a frame's tick has no refresh to be kept in. */
    int follows = display_follows(refreshes_a_frame, (long)g_steps, (long)g_one_steps);
    if (follows != g_follows)
        ingame_log("flip: the display %s", follows ? "follows the frames (a variable refresh rate): ticks not kept to "
                                                     "its refresh" : "keeps its own refresh");
    g_follows = follows;
    g_shown = g_refreshes = g_one_steps = g_steps = 0;
}
