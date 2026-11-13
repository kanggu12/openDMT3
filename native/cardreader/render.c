/*
 * The game drawn at the picture's size in the window (OPENDMT3_RENDER=display; ingame.h render_*), not at its own
 * 1280x768 enlarged after.
 *
 * Every target the game draws into at its own size (its back buffer, which is the chain's proxy, the depth surface
 * with it, and the render-target textures its glow pass copies the frame into) is made at the render size instead,
 * and every way the game reads a target's size back answers 1280x768: a surface's GetDesc, a texture's GetLevelDesc,
 * the viewport and the scissor rectangle. So every sum the game makes from a size stays the one it makes today, and
 * its draws, made for 1280x768 through its own projection, fill the larger target. Rectangles it hands over in its own
 * pixels (a viewport, a scissor rectangle, a clear's or a copy's rectangles) are turned to the target's.
 *
 * The methods are replaced in the device's, the surfaces' and the textures' tables, which every object of a kind
 * shares, so each replacement asks two things before it changes anything: whether the call came from the game (a call
 * from this DLL's own code, the post-process chain's, passes as it is) and whether the target is one made at the
 * render size (its real size is the render size and it is a render target or a depth surface: nothing of the game's
 * own has that size).
 *
 * Measured on the game (docs/architecture.md): it reads its back buffer's size and the viewport once each when it
 * starts; its sprites and its glow composite are drawn in its own pixels through its projection, which the viewport
 * maps onto the whole larger target; its videos (Bink's frames) are drawn with screen-space vertices from 0,0 to
 * 1280,768, which nothing turns, so those are drawn here from a copy turned as the viewport turns the rest (without
 * it a video covered the target's top-left 1280x768 pixels, and the glow copied that corner over the whole picture).
 *
 * Surfaces of different kinds may have tables of their own (Windows' runtime makes a texture's level, a render target
 * and a depth surface of different classes; Wine shares one table): GetDesc is replaced in each kind's table the game
 * draws into, and the real method is always the one of the object's own table.
 */
#include "ingame.h"
#include "methods.h"

#include <d3d9.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

/* A method's place in its interface's table, from the table's own layout in the headers. */
#define SLOT(iface, method) ((int)(offsetof(iface##Vtbl, method) / sizeof(void *)))

/* Whether the game's targets are made at the render size now (0: the game's own, every call passed as it is). */
static int g_on;
/* The render size: the picture's size in the window when the device was made or reset. */
static int g_rw, g_rh;
/* This DLL's own image in memory: a call returning into it is ours, never the game's. */
static const BYTE *g_us_lo, *g_us_hi;

/* The real methods, kept when ours took their places. */
typedef HRESULT(STDMETHODCALLTYPE *SurfaceDescFn)(IDirect3DSurface9 *, D3DSURFACE_DESC *);
/* A surface's GetDesc by the table it was found in: a texture's level, a render target, a depth surface (one table on
 * Wine, up to three on Windows). */
#define DESC_TABLES 4
static void **g_desc_table[DESC_TABLES];
static SurfaceDescFn g_desc_real[DESC_TABLES];
static int g_desc_tables;
typedef HRESULT(STDMETHODCALLTYPE *LevelDescFn)(IDirect3DTexture9 *, UINT, D3DSURFACE_DESC *);
typedef HRESULT(STDMETHODCALLTYPE *CreateTextureFn)(IDirect3DDevice9 *, UINT, UINT, UINT, DWORD, D3DFORMAT, D3DPOOL,
                                                    IDirect3DTexture9 **, HANDLE *);
typedef HRESULT(STDMETHODCALLTYPE *CreateSurfaceFn)(IDirect3DDevice9 *, UINT, UINT, D3DFORMAT, D3DMULTISAMPLE_TYPE,
                                                    DWORD, BOOL, IDirect3DSurface9 **, HANDLE *);
typedef HRESULT(STDMETHODCALLTYPE *ViewportFn)(IDirect3DDevice9 *, D3DVIEWPORT9 *);
typedef HRESULT(STDMETHODCALLTYPE *ScissorFn)(IDirect3DDevice9 *, RECT *);
typedef HRESULT(STDMETHODCALLTYPE *ClearFn)(IDirect3DDevice9 *, DWORD, const D3DRECT *, DWORD, D3DCOLOR, float, DWORD);
typedef HRESULT(STDMETHODCALLTYPE *StretchFn)(IDirect3DDevice9 *, IDirect3DSurface9 *, const RECT *,
                                              IDirect3DSurface9 *, const RECT *, D3DTEXTUREFILTERTYPE);
typedef HRESULT(STDMETHODCALLTYPE *ColorFillFn)(IDirect3DDevice9 *, IDirect3DSurface9 *, const RECT *, D3DCOLOR);
typedef HRESULT(STDMETHODCALLTYPE *ReadBackFn)(IDirect3DDevice9 *, IDirect3DSurface9 *, IDirect3DSurface9 *);
typedef HRESULT(STDMETHODCALLTYPE *DrawUpFn)(IDirect3DDevice9 *, D3DPRIMITIVETYPE, UINT, const void *, UINT);
typedef HRESULT(STDMETHODCALLTYPE *DrawIndexedUpFn)(IDirect3DDevice9 *, D3DPRIMITIVETYPE, UINT, UINT, UINT,
                                                    const void *, D3DFORMAT, const void *, UINT);
typedef HRESULT(STDMETHODCALLTYPE *DrawFn)(IDirect3DDevice9 *, D3DPRIMITIVETYPE, UINT, UINT);
typedef HRESULT(STDMETHODCALLTYPE *DrawIndexedFn)(IDirect3DDevice9 *, D3DPRIMITIVETYPE, INT, UINT, UINT, UINT, UINT);
static LevelDescFn real_level_desc;
static CreateTextureFn real_create_texture;
static CreateSurfaceFn real_create_rt, real_create_ds;
static ViewportFn real_set_viewport, real_get_viewport;
static ScissorFn real_set_scissor, real_get_scissor;
static ClearFn real_clear;
static StretchFn real_stretch;
static ColorFillFn real_color_fill;
static ReadBackFn real_read_back;
static DrawUpFn real_draw_up;
static DrawIndexedUpFn real_draw_indexed_up;
static DrawFn real_draw;
static DrawIndexedFn real_draw_indexed;

/* What the game asked of the replacements, by kind, for the log: sizes answered, targets made larger, rectangles
 * turned, frames read back through a copy at its own size. The first callers of the size answers are logged one by
 * one. */
enum {
    ASK_SURFACE_DESC, ASK_LEVEL_DESC, ASK_VIEWPORT, ASK_SCISSOR, ASK_MADE, ASK_RECTS, ASK_READ_BACK, ASK_SCREEN,
    ASK_SCREEN_BUFFER, ASK_KINDS
};
static const char *const ASK_NAMES[ASK_KINDS] = {"a surface's size", "a texture's size", "a viewport",
                                                 "a scissor rectangle", "a target made larger", "rectangles turned",
                                                 "a frame read back", "screen-space draws turned",
                                                 "screen-space draws from a buffer (not turned)"};
static LONG g_asked[ASK_KINDS];
/* The callers seen answering a size (their return addresses), so each new one is logged once. */
#define CALLERS 16
static const void *volatile g_callers[CALLERS];
static volatile LONG g_ncallers;

/* The game's own caller handed over by the study trace (trace.c), whose replacements of the same methods call these
 * from inside this DLL; NULL when none is waiting. */
static const void *volatile g_handed;

/* ------------------------------------------------------------------------------------------------ helpers */

/* Whether a call returning to `ret` came from this DLL (the chain's own calls pass as they are). */
static int from_us(const void *ret)
{
    return (const BYTE *)ret >= g_us_lo && (const BYTE *)ret < g_us_hi;
}

/* The caller to judge a call by: the one the trace handed over for it, else the immediate one. */
static const void *caller(const void *immediate)
{
    const void *h = g_handed;
    return h && from_us(immediate) ? h : immediate;
}

static HRESULT STDMETHODCALLTYPE our_surface_desc(IDirect3DSurface9 *s, D3DSURFACE_DESC *d);

/* A surface's real GetDesc: its own table's method, or the one ours took the place of in that table. */
static HRESULT real_desc(IDirect3DSurface9 *s, D3DSURFACE_DESC *d)
{
    void **table = *(void ***)s;
    /* The method in this surface's own table: the real one, unless ours is there. */
    SurfaceDescFn fn = (SurfaceDescFn)table[SLOT(IDirect3DSurface9, GetDesc)];
    /* Ours there: the real one it took the place of, kept for that table. */
    for (int i = 0; i < g_desc_tables; i++)
        if (g_desc_table[i] == table)
            fn = g_desc_real[i];
    /* Ours in a table not kept would call itself (never: ours goes only where a real one was kept first). */
    return fn && fn != our_surface_desc ? fn(s, d) : D3DERR_INVALIDCALL;
}

/* Whether a real size and usage are those of a target made at the render size. */
static int big(UINT w, UINT h, DWORD usage)
{
    return g_on && (int)w == g_rw && (int)h == g_rh && (usage & (D3DUSAGE_RENDERTARGET | D3DUSAGE_DEPTHSTENCIL));
}

/* Whether a surface is one made at the render size (read with the real method: never the answer the game gets). */
static int surface_big(IDirect3DSurface9 *s)
{
    D3DSURFACE_DESC d;
    return s && SUCCEEDED(real_desc(s, &d)) && big(d.Width, d.Height, d.Usage);
}

/* Whether the device's first render target now is one made at the render size. */
static int target_big(IDirect3DDevice9 *dev)
{
    IDirect3DSurface9 *s = NULL;
    /* Through the device's table: the chain's getter answers its proxy for the real back buffer, as the game sees
     * it. */
    if (FAILED(IDirect3DDevice9_GetRenderTarget(dev, 0, &s)) || !s)
        return 0;
    int yes = surface_big(s);
    IDirect3DSurface9_Release(s);
    return yes;
}

/* A first sight of a size answered to this caller: one line in the log, the first CALLERS callers only. */
static void note_caller(int kind, const void *ret)
{
    InterlockedIncrement(&g_asked[kind]);
    /* Seen already: counted only. */
    LONG seen = g_ncallers < CALLERS ? g_ncallers : CALLERS;
    for (LONG i = 0; i < seen; i++)
        if (g_callers[i] == ret)
            return;
    /* A slot of its own, claimed at once (two threads never take the same one); none left: counted only. */
    LONG slot = InterlockedIncrement(&g_ncallers) - 1;
    if (slot >= CALLERS)
        return;
    g_callers[slot] = ret;
    ingame_log("render: %s read back by the code at %p: %dx%d answered for %dx%d", ASK_NAMES[kind], ret, GAME_W, GAME_H,
               g_rw, g_rh);
}

/* One coordinate of the game's own pixels on an axis of `game` pixels to the render target's `real` (rounded to a whole
 * pixel, so a rectangle's two edges land where the game's would on the larger target; logic.c scale_edge). */
static LONG up(LONG v, int game, int real)
{
    return (LONG)scale_edge(v, game, real);
}

/* The other way: one of the render target's coordinates back to the game's pixels. */
static LONG down(LONG v, int game, int real)
{
    return (LONG)scale_edge(v, real, game);
}

/* A rectangle of the game's pixels to the render target's, in place. */
static void rect_up(RECT *r)
{
    r->left = up(r->left, GAME_W, g_rw);
    r->right = up(r->right, GAME_W, g_rw);
    r->top = up(r->top, GAME_H, g_rh);
    r->bottom = up(r->bottom, GAME_H, g_rh);
}

/* Put `ours` in entry `index` of an object's method table, keeping the method that was there in *real (once: every
 * object of the kind shares the table, and a second call finds ours there already). */
static void swap(void *object, int index, void *ours, void **real)
{
    void **table = *(void ***)object;
    if (table[index] == ours)
        return;
    DWORD old;
    if (!VirtualProtect(&table[index], sizeof(void *), PAGE_READWRITE, &old))
        return;
    *real = table[index];
    table[index] = ours;
    VirtualProtect(&table[index], sizeof(void *), old, &old);
    /* Watched every frame, put back if Direct3D fills its table in again (methods.c). */
    methods_watch(&table[index], ours, "the larger picture's", index);
}

/* GetDesc replaced in the table of `object`'s kind, its real one kept for that table first (so no call ever finds ours
 * without it); 1 when the table has ours. */
static int swap_desc(IDirect3DSurface9 *object)
{
    void **table = *(void ***)object;
    /* A kind whose table is shared with one seen already: done. */
    for (int i = 0; i < g_desc_tables; i++)
        if (g_desc_table[i] == table)
            return 1;
    void *real = table[SLOT(IDirect3DSurface9, GetDesc)];
    if (g_desc_tables >= DESC_TABLES || real == (void *)our_surface_desc)
        return 0;
    g_desc_table[g_desc_tables] = table;
    g_desc_real[g_desc_tables] = (SurfaceDescFn)real;
    g_desc_tables++;
    swap(object, SLOT(IDirect3DSurface9, GetDesc), (void *)our_surface_desc, &real);
    return table[SLOT(IDirect3DSurface9, GetDesc)] == (void *)our_surface_desc;
}

/* ------------------------------------------------------------------------------------------- the sizes read */

static HRESULT STDMETHODCALLTYPE our_surface_desc(IDirect3DSurface9 *s, D3DSURFACE_DESC *d)
{
    /* The real answer first, from the method of this surface's own kind. */
    HRESULT hr = real_desc(s, d);
    const void *ret = caller(__builtin_return_address(0));
    /* A target made at the render size, asked by the game (or by D3DX for it): its own size answered. */
    if (SUCCEEDED(hr) && d && !from_us(ret) && big(d->Width, d->Height, d->Usage)) {
        d->Width = GAME_W;
        d->Height = GAME_H;
        note_caller(ASK_SURFACE_DESC, ret);
    }
    return hr;
}

static HRESULT STDMETHODCALLTYPE our_level_desc(IDirect3DTexture9 *t, UINT level, D3DSURFACE_DESC *d)
{
    HRESULT hr = real_level_desc(t, level, d);
    const void *ret = caller(__builtin_return_address(0));
    if (FAILED(hr) || !d || from_us(ret) || !g_on)
        return hr;
    /* Its first level is the one made at the render size; a smaller level of such a texture is answered as the same
     * level of the game's own size (a target the game made with levels below it). */
    D3DSURFACE_DESC top = *d;
    if (level > 0 && FAILED(real_level_desc(t, 0, &top)))
        return hr;
    if (!big(top.Width, top.Height, top.Usage))
        return hr;
    d->Width = (GAME_W >> level) > 0 ? (UINT)(GAME_W >> level) : 1u;
    d->Height = (GAME_H >> level) > 0 ? (UINT)(GAME_H >> level) : 1u;
    note_caller(ASK_LEVEL_DESC, ret);
    return hr;
}

static HRESULT STDMETHODCALLTYPE our_get_viewport(IDirect3DDevice9 *dev, D3DVIEWPORT9 *vp)
{
    HRESULT hr = real_get_viewport(dev, vp);
    const void *ret = caller(__builtin_return_address(0));
    /* On a target made at the render size: the viewport in the game's own pixels (the whole target is its 1280x768). */
    if (SUCCEEDED(hr) && vp && g_on && !from_us(ret) && target_big(dev)) {
        /* Its two corners turned back to the game's pixels (the same sum the game's own viewport was turned by, the
         * other way, so a viewport it set reads back as it set it). */
        LONG x0 = down((LONG)vp->X, GAME_W, g_rw), y0 = down((LONG)vp->Y, GAME_H, g_rh);
        LONG x1 = down((LONG)(vp->X + vp->Width), GAME_W, g_rw), y1 = down((LONG)(vp->Y + vp->Height), GAME_H, g_rh);
        /* The corner and the size between the two (the depth range as it is). */
        vp->X = (DWORD)x0;
        vp->Y = (DWORD)y0;
        vp->Width = (DWORD)(x1 - x0);
        vp->Height = (DWORD)(y1 - y0);
        note_caller(ASK_VIEWPORT, ret);
    }
    return hr;
}

static HRESULT STDMETHODCALLTYPE our_set_viewport(IDirect3DDevice9 *dev, D3DVIEWPORT9 *vp)
{
    const void *ret = caller(__builtin_return_address(0));
    /* The game's viewport in its own pixels, on a target made at the render size: the same part of the larger
     * target. */
    if (vp && g_on && !from_us(ret) && target_big(dev)) {
        /* A copy (the game's own stays as it gave it), its depth range kept. */
        D3DVIEWPORT9 v = *vp;
        /* Its two corners turned, each edge rounded as a clear's or a scissor's is, so they meet the same pixels. */
        LONG x0 = up((LONG)vp->X, GAME_W, g_rw), y0 = up((LONG)vp->Y, GAME_H, g_rh);
        LONG x1 = up((LONG)(vp->X + vp->Width), GAME_W, g_rw), y1 = up((LONG)(vp->Y + vp->Height), GAME_H, g_rh);
        v.X = (DWORD)x0;
        v.Y = (DWORD)y0;
        v.Width = (DWORD)(x1 - x0);
        v.Height = (DWORD)(y1 - y0);
        InterlockedIncrement(&g_asked[ASK_RECTS]);
        return real_set_viewport(dev, &v);
    }
    return real_set_viewport(dev, vp);
}

static HRESULT STDMETHODCALLTYPE our_set_scissor(IDirect3DDevice9 *dev, RECT *r)
{
    const void *ret = caller(__builtin_return_address(0));
    if (r && g_on && !from_us(ret) && target_big(dev)) {
        RECT s = *r;
        rect_up(&s);
        InterlockedIncrement(&g_asked[ASK_RECTS]);
        return real_set_scissor(dev, &s);
    }
    return real_set_scissor(dev, r);
}

static HRESULT STDMETHODCALLTYPE our_get_scissor(IDirect3DDevice9 *dev, RECT *r)
{
    HRESULT hr = real_get_scissor(dev, r);
    const void *ret = caller(__builtin_return_address(0));
    if (SUCCEEDED(hr) && r && g_on && !from_us(ret) && target_big(dev)) {
        r->left = down(r->left, GAME_W, g_rw);
        r->right = down(r->right, GAME_W, g_rw);
        r->top = down(r->top, GAME_H, g_rh);
        r->bottom = down(r->bottom, GAME_H, g_rh);
        note_caller(ASK_SCISSOR, ret);
    }
    return hr;
}

/* ------------------------------------------------------------------------------------------ the targets made */

static HRESULT STDMETHODCALLTYPE our_create_texture(IDirect3DDevice9 *dev, UINT w, UINT h, UINT levels, DWORD usage,
                                                    D3DFORMAT f, D3DPOOL pool, IDirect3DTexture9 **out, HANDLE *share)
{
    const void *ret = caller(__builtin_return_address(0));
    /* A render-target texture of the game's own size (its glow pass copies the frame into one): at the render size. */
    if (g_on && !from_us(ret) && (usage & D3DUSAGE_RENDERTARGET) && w == GAME_W && h == GAME_H) {
        HRESULT hr = real_create_texture(dev, (UINT)g_rw, (UINT)g_rh, levels, usage, f, pool, out, share);
        if (SUCCEEDED(hr)) {
            if (InterlockedIncrement(&g_asked[ASK_MADE]) <= 8)
                ingame_log("render: the game's render-target texture (format %d) made at %dx%d", f, g_rw, g_rh);
            return hr;
        }
        /* Not made that large (the card's memory): at the game's size, which the game's copy and its composite read
         * through normalised coordinates all the same (blurrier, never misplaced). */
        ingame_log("render: the game's render-target texture not made at %dx%d (0x%08lx): at its own size", g_rw, g_rh,
                   (unsigned long)hr);
    }
    return real_create_texture(dev, w, h, levels, usage, f, pool, out, share);
}

static HRESULT STDMETHODCALLTYPE our_create_rt(IDirect3DDevice9 *dev, UINT w, UINT h, D3DFORMAT f,
                                               D3DMULTISAMPLE_TYPE ms, DWORD q, BOOL lockable, IDirect3DSurface9 **out,
                                               HANDLE *share)
{
    const void *ret = caller(__builtin_return_address(0));
    /* A render target of the game's own size: at the render size, as its textures. */
    if (g_on && !from_us(ret) && w == GAME_W && h == GAME_H) {
        HRESULT hr = real_create_rt(dev, (UINT)g_rw, (UINT)g_rh, f, ms, q, lockable, out, share);
        if (SUCCEEDED(hr)) {
            /* Counted; the first eight in the log. */
            if (InterlockedIncrement(&g_asked[ASK_MADE]) <= 8)
                ingame_log("render: the game's render target (format %d) made at %dx%d", f, g_rw, g_rh);
            return hr;
        }
        /* Not made that large: at its own size, said. */
        ingame_log("render: the game's render target not made at %dx%d (0x%08lx): at its own size", g_rw, g_rh,
                   (unsigned long)hr);
    }
    return real_create_rt(dev, w, h, f, ms, q, lockable, out, share);
}

static HRESULT STDMETHODCALLTYPE our_create_ds(IDirect3DDevice9 *dev, UINT w, UINT h, D3DFORMAT f,
                                               D3DMULTISAMPLE_TYPE ms, DWORD q, BOOL discard, IDirect3DSurface9 **out,
                                               HANDLE *share)
{
    const void *ret = caller(__builtin_return_address(0));
    /* A depth surface of the game's own size goes with a target of it: as large as the targets it is used with. */
    if (g_on && !from_us(ret) && w == GAME_W && h == GAME_H) {
        HRESULT hr = real_create_ds(dev, (UINT)g_rw, (UINT)g_rh, f, ms, q, discard, out, share);
        if (SUCCEEDED(hr)) {
            /* Counted; the first eight in the log. */
            if (InterlockedIncrement(&g_asked[ASK_MADE]) <= 8)
                ingame_log("render: the game's depth surface (format %d) made at %dx%d", f, g_rw, g_rh);
            return hr;
        }
        /* Not made that large: at its own size, said (a target made larger needs one as large to be drawn with). */
        ingame_log("render: the game's depth surface not made at %dx%d (0x%08lx): at its own size", g_rw, g_rh,
                   (unsigned long)hr);
    }
    return real_create_ds(dev, w, h, f, ms, q, discard, out, share);
}

/* ------------------------------------------------------------------------------------ rectangles and copies */

static HRESULT STDMETHODCALLTYPE our_clear(IDirect3DDevice9 *dev, DWORD n, const D3DRECT *rects, DWORD flags,
                                           D3DCOLOR colour, float z, DWORD stencil)
{
    const void *ret = caller(__builtin_return_address(0));
    /* Rectangles of the game's pixels on a target made at the render size: the same parts of it (64 at most, as
     * many as a game clears in one call; more pass as they are). */
    if (n && n <= 64 && rects && g_on && !from_us(ret) && target_big(dev)) {
        D3DRECT r[64];
        for (DWORD i = 0; i < n; i++) {
            r[i].x1 = up(rects[i].x1, GAME_W, g_rw);
            r[i].x2 = up(rects[i].x2, GAME_W, g_rw);
            r[i].y1 = up(rects[i].y1, GAME_H, g_rh);
            r[i].y2 = up(rects[i].y2, GAME_H, g_rh);
        }
        InterlockedIncrement(&g_asked[ASK_RECTS]);
        return real_clear(dev, n, r, flags, colour, z, stencil);
    }
    /* More rectangles than that: passed as they are, and said once. */
    static LONG said;
    if (n > 64 && rects && g_on && !from_us(ret) && !InterlockedExchange(&said, 1))
        ingame_log("render: a clear of %lu rectangles passed unturned", (unsigned long)n);
    return real_clear(dev, n, rects, flags, colour, z, stencil);
}

static HRESULT STDMETHODCALLTYPE our_stretch(IDirect3DDevice9 *dev, IDirect3DSurface9 *src, const RECT *sr,
                                             IDirect3DSurface9 *dst, const RECT *dr, D3DTEXTUREFILTERTYPE filter)
{
    const void *ret = caller(__builtin_return_address(0));
    /* A copy's rectangles in the game's pixels: each turned on the side made at the render size (no rectangle: the
     * whole surface, already right). */
    if (g_on && !from_us(ret) && (sr || dr)) {
        RECT s, d;
        const RECT *ps = sr, *pd = dr;
        if (sr && surface_big(src)) {
            s = *sr;
            rect_up(&s);
            ps = &s;
        }
        if (dr && surface_big(dst)) {
            d = *dr;
            rect_up(&d);
            pd = &d;
        }
        if (ps != sr || pd != dr)
            InterlockedIncrement(&g_asked[ASK_RECTS]);
        return real_stretch(dev, src, ps, dst, pd, filter);
    }
    return real_stretch(dev, src, sr, dst, dr, filter);
}

static HRESULT STDMETHODCALLTYPE our_color_fill(IDirect3DDevice9 *dev, IDirect3DSurface9 *s, const RECT *r,
                                                D3DCOLOR colour)
{
    const void *ret = caller(__builtin_return_address(0));
    if (r && g_on && !from_us(ret) && surface_big(s)) {
        RECT f = *r;
        rect_up(&f);
        InterlockedIncrement(&g_asked[ASK_RECTS]);
        return real_color_fill(dev, s, &f, colour);
    }
    return real_color_fill(dev, s, r, colour);
}

static HRESULT STDMETHODCALLTYPE our_read_back(IDirect3DDevice9 *dev, IDirect3DSurface9 *rt, IDirect3DSurface9 *sys)
{
    const void *ret = caller(__builtin_return_address(0));
    D3DSURFACE_DESC dr, ds;
    /* A target made at the render size read back into a surface of the game's own size (a screenshot of its own): the
     * target copied at that size first, then read back from the copy. */
    if (g_on && !from_us(ret) && rt && sys && SUCCEEDED(real_desc(rt, &dr)) && big(dr.Width, dr.Height, dr.Usage) &&
        SUCCEEDED(real_desc(sys, &ds)) && ds.Width == GAME_W && ds.Height == GAME_H) {
        IDirect3DSurface9 *small = NULL;
        HRESULT hr = IDirect3DDevice9_CreateRenderTarget(dev, GAME_W, GAME_H, dr.Format, D3DMULTISAMPLE_NONE, 0, FALSE,
                                                         &small, NULL);
        if (SUCCEEDED(hr))
            hr = real_stretch(dev, rt, NULL, small, NULL, D3DTEXF_LINEAR);
        if (SUCCEEDED(hr))
            hr = real_read_back(dev, small, sys);
        if (small)
            IDirect3DSurface9_Release(small);
        InterlockedIncrement(&g_asked[ASK_READ_BACK]);
        return hr;
    }
    return real_read_back(dev, rt, sys);
}

/* ------------------------------------------------------------------------------------------ screen-space draws */

/* Where the current vertex format puts a pre-transformed position (screen pixels, x y z rhw: an FVF with XYZRHW, or a
 * declaration's POSITIONT in stream 0), as an offset in a vertex; -1 when the device transforms the positions (the
 * game's own projection then fills the larger target by itself). The game's video (Bink's frames) is drawn so. */
static int screen_positions(IDirect3DDevice9 *dev)
{
    DWORD fvf = 0;
    /* An FVF: its position first in the vertex. */
    if (SUCCEEDED(IDirect3DDevice9_GetFVF(dev, &fvf)) && fvf)
        return (fvf & D3DFVF_POSITION_MASK) == D3DFVF_XYZRHW ? 0 : -1;
    /* No FVF: the declaration set, read at each draw (cheap; an answer kept by its address could outlive it, and a
     * declaration made later at the same address can have another layout). */
    IDirect3DVertexDeclaration9 *decl = NULL;
    if (FAILED(IDirect3DDevice9_GetVertexDeclaration(dev, &decl)) || !decl)
        return -1;
    D3DVERTEXELEMENT9 el[MAXD3DDECLLENGTH + 1];
    UINT n = MAXD3DDECLLENGTH + 1;
    int at = -1;
    /* Its elements up to the end mark: a four-float POSITIONT in stream 0 is a screen-space position. */
    if (SUCCEEDED(IDirect3DVertexDeclaration9_GetDeclaration(decl, el, &n)))
        for (UINT i = 0; i < n && el[i].Stream != 0xff; i++)
            if (el[i].Stream == 0 && el[i].Usage == D3DDECLUSAGE_POSITIONT && el[i].Type == D3DDECLTYPE_FLOAT4)
                at = el[i].Offset;
    IDirect3DVertexDeclaration9_Release(decl);
    return at;
}

/* The vertices a draw of `count` primitives of `type` reads. */
static UINT vertex_count(D3DPRIMITIVETYPE type, UINT count)
{
    switch (type) {
    case D3DPT_POINTLIST: return count;
    case D3DPT_LINELIST: return count * 2;
    case D3DPT_LINESTRIP: return count + 1;
    case D3DPT_TRIANGLELIST: return count * 3;
    case D3DPT_TRIANGLESTRIP:
    case D3DPT_TRIANGLEFAN: return count + 2;
    default: return 0;
    }
}

/* A copy of `n` vertices of `stride` bytes with their screen positions (at byte `at`) turned from the game's pixels to
 * the render target's, the same way the viewport turns every projected draw (x times the width's ratio, y the
 * height's); NULL when there is no memory. The copy is the caller's to free unless it is the kept buffer. */
static BYTE g_turned[64 * 1024];
static BYTE *turned_copy(const void *v, UINT n, UINT stride, int at)
{
    size_t bytes = (size_t)n * stride;
    /* A quad's or a video frame's vertices fit the kept buffer; a longer list gets memory of its own. */
    BYTE *copy = bytes <= sizeof g_turned ? g_turned : malloc(bytes);
    if (!copy)
        return NULL;
    memcpy(copy, v, bytes);
    /* The viewport's own sum: the game's 1280 pixels across are the target's width, its 768 down its height. */
    const float sx = (float)g_rw / GAME_W, sy = (float)g_rh / GAME_H;
    for (UINT k = 0; k < n; k++) {
        /* Each vertex's x and y (its z and rhw, its colour and texture coordinates as they are). */
        float *p = (float *)(copy + (size_t)k * stride + at);
        p[0] *= sx;
        p[1] *= sy;
    }
    return copy;
}

static HRESULT STDMETHODCALLTYPE our_draw_up(IDirect3DDevice9 *dev, D3DPRIMITIVETYPE type, UINT count, const void *v,
                                             UINT stride)
{
    const void *ret = caller(__builtin_return_address(0));
    int at;
    /* The game's vertices in its own screen pixels, drawn on a target made at the render size: a turned copy drawn. */
    if (g_on && v && stride >= 16 && !from_us(ret) && (at = screen_positions(dev)) >= 0 && (UINT)at + 8 <= stride &&
        target_big(dev)) {
        BYTE *copy = turned_copy(v, vertex_count(type, count), stride, at);
        if (copy) {
            HRESULT hr = real_draw_up(dev, type, count, copy, stride);
            if (copy != g_turned)
                free(copy);
            InterlockedIncrement(&g_asked[ASK_SCREEN]);
            return hr;
        }
    }
    return real_draw_up(dev, type, count, v, stride);
}

static HRESULT STDMETHODCALLTYPE our_draw_indexed_up(IDirect3DDevice9 *dev, D3DPRIMITIVETYPE type, UINT min_index,
                                                     UINT vertices, UINT count, const void *indices, D3DFORMAT format,
                                                     const void *v, UINT stride)
{
    const void *ret = caller(__builtin_return_address(0));
    int at;
    /* The same for an indexed draw: every vertex up to the last one the indices may name turned. */
    if (g_on && v && stride >= 16 && !from_us(ret) && (at = screen_positions(dev)) >= 0 && (UINT)at + 8 <= stride &&
        target_big(dev)) {
        BYTE *copy = turned_copy(v, min_index + vertices, stride, at);
        if (copy) {
            HRESULT hr = real_draw_indexed_up(dev, type, min_index, vertices, count, indices, format, copy, stride);
            if (copy != g_turned)
                free(copy);
            InterlockedIncrement(&g_asked[ASK_SCREEN]);
            return hr;
        }
    }
    return real_draw_indexed_up(dev, type, min_index, vertices, count, indices, format, v, stride);
}

static HRESULT STDMETHODCALLTYPE our_draw(IDirect3DDevice9 *dev, D3DPRIMITIVETYPE type, UINT start, UINT count)
{
    const void *ret = caller(__builtin_return_address(0));
    /* Screen-space vertices from a buffer are not turned (the buffer is the game's, written once): counted, so the
     * log says if the game ever draws so on a larger target. */
    if (g_on && !from_us(ret) && screen_positions(dev) >= 0 && target_big(dev))
        InterlockedIncrement(&g_asked[ASK_SCREEN_BUFFER]);
    return real_draw(dev, type, start, count);
}

static HRESULT STDMETHODCALLTYPE our_draw_indexed(IDirect3DDevice9 *dev, D3DPRIMITIVETYPE type, INT base,
                                                  UINT min_index, UINT vertices, UINT start, UINT count)
{
    const void *ret = caller(__builtin_return_address(0));
    /* The same for an indexed draw from buffers: counted, not turned. */
    if (g_on && !from_us(ret) && screen_positions(dev) >= 0 && target_big(dev))
        InterlockedIncrement(&g_asked[ASK_SCREEN_BUFFER]);
    return real_draw_indexed(dev, type, base, min_index, vertices, start, count);
}

/* ------------------------------------------------------------------------------------------------- the rest */

int render_attach(IDirect3DDevice9 *dev)
{
    /* This DLL's image (its headers say how large): calls returning into it are the chain's own. */
    const IMAGE_DOS_HEADER *dos = (const IMAGE_DOS_HEADER *)g_module;
    const IMAGE_NT_HEADERS *nt = (const IMAGE_NT_HEADERS *)((const BYTE *)g_module + dos->e_lfanew);
    g_us_lo = (const BYTE *)g_module;
    g_us_hi = g_us_lo + nt->OptionalHeader.SizeOfImage;
    /* One small object of each kind the game draws into, for their kinds' tables: a render-target texture and its
     * level (the proxy and the glow's textures), a render target (the proxy with samples) and a depth surface. */
    IDirect3DSurface9 *s = NULL, *rt = NULL, *ds = NULL;
    IDirect3DTexture9 *t = NULL;
    int ok = SUCCEEDED(IDirect3DDevice9_CreateTexture(dev, 1, 1, 1, D3DUSAGE_RENDERTARGET, D3DFMT_X8R8G8B8,
                                                     D3DPOOL_DEFAULT, &t, NULL)) &&
             SUCCEEDED(IDirect3DTexture9_GetSurfaceLevel(t, 0, &s)) &&
             SUCCEEDED(IDirect3DDevice9_CreateRenderTarget(dev, 1, 1, D3DFMT_X8R8G8B8, D3DMULTISAMPLE_NONE, 0, FALSE,
                                                           &rt, NULL));
    /* The depth surface in the format every card has, or the other one. */
    if (ok && FAILED(IDirect3DDevice9_CreateDepthStencilSurface(dev, 1, 1, D3DFMT_D24S8, D3DMULTISAMPLE_NONE, 0, TRUE,
                                                                &ds, NULL)))
        ok = SUCCEEDED(IDirect3DDevice9_CreateDepthStencilSurface(dev, 1, 1, D3DFMT_D16, D3DMULTISAMPLE_NONE, 0, TRUE,
                                                                  &ds, NULL));
    /* GetDesc in each kind's table (one table or several), GetLevelDesc in the textures'. */
    if (ok)
        ok = swap_desc(s) && swap_desc(rt) && swap_desc(ds);
    if (ok)
        swap(t, SLOT(IDirect3DTexture9, GetLevelDesc), (void *)our_level_desc, (void **)&real_level_desc);
    if (ds)
        IDirect3DSurface9_Release(ds);
    if (rt)
        IDirect3DSurface9_Release(rt);
    if (s)
        IDirect3DSurface9_Release(s);
    if (t)
        IDirect3DTexture9_Release(t);
    if (!ok) {
        ingame_log("render: the surfaces' tables could not be changed: the game drawn at its own size");
        return 0;
    }
    ingame_log("render: a surface's size answered in %d table%s", g_desc_tables, g_desc_tables == 1 ? "" : "s");
    /* The device's methods that make targets, read sizes back or take rectangles in the game's pixels; then those that
     * draw, for screen-space vertices (one table for every device of the runtime). The targets it makes: */
    swap(dev, SLOT(IDirect3DDevice9, CreateTexture), (void *)our_create_texture, (void **)&real_create_texture);
    swap(dev, SLOT(IDirect3DDevice9, CreateRenderTarget), (void *)our_create_rt, (void **)&real_create_rt);
    swap(dev, SLOT(IDirect3DDevice9, CreateDepthStencilSurface), (void *)our_create_ds, (void **)&real_create_ds);
    /* The sizes it reads back and the rectangles it gives: */
    swap(dev, SLOT(IDirect3DDevice9, GetViewport), (void *)our_get_viewport, (void **)&real_get_viewport);
    swap(dev, SLOT(IDirect3DDevice9, SetViewport), (void *)our_set_viewport, (void **)&real_set_viewport);
    swap(dev, SLOT(IDirect3DDevice9, SetScissorRect), (void *)our_set_scissor, (void **)&real_set_scissor);
    swap(dev, SLOT(IDirect3DDevice9, GetScissorRect), (void *)our_get_scissor, (void **)&real_get_scissor);
    swap(dev, SLOT(IDirect3DDevice9, Clear), (void *)our_clear, (void **)&real_clear);
    swap(dev, SLOT(IDirect3DDevice9, StretchRect), (void *)our_stretch, (void **)&real_stretch);
    swap(dev, SLOT(IDirect3DDevice9, ColorFill), (void *)our_color_fill, (void **)&real_color_fill);
    swap(dev, SLOT(IDirect3DDevice9, GetRenderTargetData), (void *)our_read_back, (void **)&real_read_back);
    /* Its draws (from its own memory turned, from buffers counted): */
    swap(dev, SLOT(IDirect3DDevice9, DrawPrimitiveUP), (void *)our_draw_up, (void **)&real_draw_up);
    swap(dev, SLOT(IDirect3DDevice9, DrawIndexedPrimitiveUP), (void *)our_draw_indexed_up,
         (void **)&real_draw_indexed_up);
    swap(dev, SLOT(IDirect3DDevice9, DrawPrimitive), (void *)our_draw, (void **)&real_draw);
    swap(dev, SLOT(IDirect3DDevice9, DrawIndexedPrimitive), (void *)our_draw_indexed, (void **)&real_draw_indexed);
    /* Every replacement in place, or none is used (a table that could not be written leaves the game its own size). */
    return real_level_desc && real_create_texture && real_create_rt && real_create_ds &&
           real_get_viewport && real_set_viewport && real_set_scissor && real_get_scissor && real_clear &&
           real_stretch && real_color_fill && real_read_back && real_draw_up && real_draw_indexed_up && real_draw &&
           real_draw_indexed;
}

void render_set(int w, int h)
{
    /* The game's own size (or none): every call passes as it is. */
    g_on = w > 0 && h > 0 && (w != GAME_W || h != GAME_H);
    g_rw = g_on ? w : GAME_W;
    g_rh = g_on ? h : GAME_H;
    if (g_on)
        ingame_log("render: the game's targets made at %dx%d, its own sizes answered when it asks", g_rw, g_rh);
}

int render_on(void)
{
    return g_on;
}

HRESULT render_real_desc(IDirect3DSurface9 *s, D3DSURFACE_DESC *d)
{
    /* The method of the surface's own table, or the real one ours took the place of there. */
    return real_desc(s, d);
}

void render_from(const void *ret)
{
    /* Set before the trace calls on into a replaced method, cleared after it returns. */
    g_handed = ret;
}

void render_summary(void)
{
    if (!g_on)
        return;
    /* Each kind asked since the last line, and nothing when none was. */
    char line[400];
    int n = snprintf(line, sizeof line, "render: since the last line");
    int any = 0;
    for (int k = 0; k < ASK_KINDS; k++) {
        LONG c = InterlockedExchange(&g_asked[k], 0);
        if (c && n < (int)sizeof line - 48) {
            n += snprintf(line + n, sizeof line - (size_t)n, "%s %s %ld", any ? "," : "", ASK_NAMES[k], (long)c);
            any = 1;
        }
    }
    if (any)
        ingame_log("%s", line);
}
