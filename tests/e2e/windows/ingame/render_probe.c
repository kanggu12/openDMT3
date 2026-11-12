/*
 * The game drawn at the screen's size (native/cardreader/render.c), tried without the game
 * (tests/e2e/windows/render.sh): this program imports Direct3DCreate9 by name as the game does, loads openDMT3's
 * CRT_R1.dll (whose DllMain turns that import to its own), makes a device for a 1280x768 back buffer in a window of
 * the screen's size, as the game does with OPENDMT3_RENDER=display, and asks what the game asks:
 *   - its back buffer's size, a 1280x768 render-target texture's size (its level and its surface), the viewport;
 *   - a viewport in its own pixels set and read back;
 *   - a screenshot of its own: the back buffer read into a 1280x768 surface in memory.
 * Then it draws in its own 1280x768 coordinates as the game draws: red over the top-left quarter and green over the
 * bottom-right one through an orthographic projection, the frame copied whole into its texture and that drawn back over
 * the left half, and a yellow square of screen-space vertices (XYZRHW, as the game's videos are drawn) in the top-right
 * corner, 128 of its pixels wide. The chain's measuring dump (dump.now, frame 20) writes the frame as the game drew it
 * (probe-src.bmp, at the larger size): render_probe.py checks where each colour landed. Then a device reset, as the
 * game makes one when its window turns between full screen and a window, and all of it again (after-src.bmp).
 *
 *   wine render_probe.exe       (OPENDMT3_RENDER, OPENDMT3_INGAME_LOG and OPENDMT3_POSTFX_DUMP in the environment)
 * Prints one line a finding; exits 0 when the game is answered its own sizes everywhere, 1 when it is not.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d9.h>
#include <stdio.h>

/* The window carries the pictures only. */
static LRESULT CALLBACK proc(HWND w, UINT m, WPARAM wp, LPARAM lp)
{
    return DefWindowProcA(w, m, wp, lp);
}

/* A vertex in the game's own pixels (its projection turns it), with a colour and a texture coordinate. */
typedef struct {
    float x, y, z;
    DWORD c;
    float u, v;
} V;
#define FVF (D3DFVF_XYZ | D3DFVF_DIFFUSE | D3DFVF_TEX1)
/* A vertex already in the target's pixels (screen space), with a colour. */
typedef struct {
    float x, y, z, rhw;
    DWORD c;
} S;
#define FVF_SCREEN (D3DFVF_XYZRHW | D3DFVF_DIFFUSE)

/* A quad of colour c from (x0, y0) to (x1, y1) of the game's pixels, as two triangles. */
static void quad(IDirect3DDevice9 *d, float x0, float y0, float x1, float y1, DWORD c)
{
    V v[4] = {{x0, y0, 0, c, 0, 0}, {x1, y0, 0, c, 1, 0}, {x0, y1, 0, c, 0, 1}, {x1, y1, 0, c, 1, 1}};
    IDirect3DDevice9_DrawPrimitiveUP(d, D3DPT_TRIANGLESTRIP, 2, v, sizeof v[0]);
}

/* A finding: its line, and whether it held (counted against the exit code). */
static int g_bad;
static void say(int ok, const char *what, unsigned a, unsigned b, unsigned c, unsigned e)
{
    printf("%s %s %u %u %u %u\n", ok ? "ok  " : "FAIL", what, a, b, c, e);
    g_bad += !ok;
}

/* The game's projection: 0..1280 and 0..768 to clip space, y down (its trace's 2/1280 and -2/768). */
static const D3DMATRIX PROJ = {{{2.0f / 1280, 0, 0, 0, 0, -2.0f / 768, 0, 0, 0, 0, 1, 0, -1, 1, 0, 1}}};
static const D3DMATRIX IDENTITY = {{{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1}}};

/* What the game reads of its targets' sizes: its back buffer's, a 1280x768 render-target texture's (its level and its
 * surface), the viewport, a viewport of its own set and read back. `when` names the moment in each line. */
static void sizes(IDirect3DDevice9 *d, IDirect3DSurface9 *bb, IDirect3DTexture9 *t, IDirect3DSurface9 *ts,
                  const char *when)
{
    char what[160];
    D3DSURFACE_DESC desc;
    IDirect3DSurface9_GetDesc(bb, &desc);
    snprintf(what, sizeof what, "the back buffer's size as the game reads it%s", when);
    say(desc.Width == 1280 && desc.Height == 768, what, desc.Width, desc.Height, 0, 0);
    IDirect3DTexture9_GetLevelDesc(t, 0, &desc);
    snprintf(what, sizeof what, "its 1280x768 render-target texture's level%s", when);
    say(desc.Width == 1280 && desc.Height == 768, what, desc.Width, desc.Height, 0, 0);
    IDirect3DSurface9_GetDesc(ts, &desc);
    snprintf(what, sizeof what, "that texture's surface%s", when);
    say(desc.Width == 1280 && desc.Height == 768, what, desc.Width, desc.Height, 0, 0);
    D3DVIEWPORT9 vp;
    IDirect3DDevice9_SetRenderTarget(d, 0, bb);
    IDirect3DDevice9_GetViewport(d, &vp);
    snprintf(what, sizeof what, "the viewport on its back buffer%s", when);
    say(!vp.X && !vp.Y && vp.Width == 1280 && vp.Height == 768, what, vp.X, vp.Y, vp.Width, vp.Height);
    D3DVIEWPORT9 part = {320, 192, 640, 384, 0, 1};
    IDirect3DDevice9_SetViewport(d, &part);
    IDirect3DDevice9_GetViewport(d, &vp);
    snprintf(what, sizeof what, "a viewport of its own set and read back%s", when);
    say(vp.X == 320 && vp.Y == 192 && vp.Width == 640 && vp.Height == 384, what, vp.X, vp.Y, vp.Width, vp.Height);
}

/* `count` frames drawn in the game's own 1280x768 coordinates as the game draws (see the top), the chain's dump of the
 * frame `dump_at` frames in asked for under `label` (it looks every tenth frame). */
static void frames(IDirect3DDevice9 *d, IDirect3DSurface9 *bb, IDirect3DTexture9 *t, IDirect3DSurface9 *ts, int count,
                   int dump_at, const char *label)
{
    for (int frame = 0; frame < count; frame++) {
        if (frame == dump_at) {
            char dir[MAX_PATH], path[MAX_PATH + 16];
            DWORD got = GetEnvironmentVariableA("OPENDMT3_POSTFX_DUMP", dir, sizeof dir);
            snprintf(path, sizeof path, "%s\\dump.now", got && got < sizeof dir ? dir : ".");
            FILE *f = fopen(path, "w");
            if (f) {
                fprintf(f, "%s one\n", label);
                fclose(f);
            }
        }
        IDirect3DDevice9_SetRenderTarget(d, 0, bb);
        IDirect3DDevice9_BeginScene(d);
        IDirect3DDevice9_Clear(d, 0, NULL, D3DCLEAR_TARGET | D3DCLEAR_ZBUFFER, D3DCOLOR_XRGB(0, 0, 255), 1.0f, 0);
        IDirect3DDevice9_SetRenderState(d, D3DRS_LIGHTING, FALSE);
        IDirect3DDevice9_SetRenderState(d, D3DRS_ZENABLE, FALSE);
        IDirect3DDevice9_SetRenderState(d, D3DRS_CULLMODE, D3DCULL_NONE);
        IDirect3DDevice9_SetTransform(d, D3DTS_PROJECTION, &PROJ);
        IDirect3DDevice9_SetTransform(d, D3DTS_VIEW, &IDENTITY);
        IDirect3DDevice9_SetTransform(d, D3DTS_WORLD, &IDENTITY);
        IDirect3DDevice9_SetFVF(d, FVF);
        IDirect3DDevice9_SetTexture(d, 0, NULL);
        IDirect3DDevice9_SetTextureStageState(d, 0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
        IDirect3DDevice9_SetTextureStageState(d, 0, D3DTSS_COLORARG1, D3DTA_DIFFUSE);
        quad(d, 0, 0, 640, 384, D3DCOLOR_XRGB(255, 0, 0));
        quad(d, 640, 384, 1280, 768, D3DCOLOR_XRGB(0, 255, 0));
        /* The glow's way: the frame copied whole into the texture, the texture's left half drawn back over the left
         * half (clamped, point-sampled), so a texture holding the frame anywhere but whole shows here as another
         * picture. */
        IDirect3DDevice9_StretchRect(d, bb, NULL, ts, NULL, D3DTEXF_NONE);
        IDirect3DDevice9_SetTexture(d, 0, (IDirect3DBaseTexture9 *)t);
        IDirect3DDevice9_SetTextureStageState(d, 0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
        IDirect3DDevice9_SetSamplerState(d, 0, D3DSAMP_MINFILTER, D3DTEXF_POINT);
        IDirect3DDevice9_SetSamplerState(d, 0, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
        IDirect3DDevice9_SetSamplerState(d, 0, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
        IDirect3DDevice9_SetSamplerState(d, 0, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
        V v[4] = {{0, 0, 0, 0, 0, 0}, {640, 0, 0, 0, 0.5f, 0}, {0, 768, 0, 0, 0, 1}, {640, 768, 0, 0, 0.5f, 1}};
        IDirect3DDevice9_DrawPrimitiveUP(d, D3DPT_TRIANGLESTRIP, 2, v, sizeof v[0]);
        IDirect3DDevice9_SetTexture(d, 0, NULL);
        /* A square of screen-space vertices in the top-right corner, as the game's videos are drawn: its own pixels,
         * which no projection turns. */
        IDirect3DDevice9_SetTextureStageState(d, 0, D3DTSS_COLORARG1, D3DTA_DIFFUSE);
        IDirect3DDevice9_SetFVF(d, FVF_SCREEN);
        DWORD yellow = D3DCOLOR_XRGB(255, 255, 0);
        S s[4] = {{1152, 0, 0, 1, yellow}, {1280, 0, 0, 1, yellow}, {1152, 128, 0, 1, yellow},
                  {1280, 128, 0, 1, yellow}};
        IDirect3DDevice9_DrawPrimitiveUP(d, D3DPT_TRIANGLESTRIP, 2, s, sizeof s[0]);
        IDirect3DDevice9_EndScene(d);
        IDirect3DDevice9_Present(d, NULL, NULL, NULL, NULL);
        Sleep(16);
    }
}

/* A screenshot of its own: the back buffer read into a 1280x768 surface in memory (red at 100,100, green at
 * 1200,700). */
static void screenshot(IDirect3DDevice9 *d, IDirect3DSurface9 *bb, const char *when)
{
    char what[160];
    IDirect3DSurface9 *sys = NULL;
    IDirect3DDevice9_CreateOffscreenPlainSurface(d, 1280, 768, D3DFMT_X8R8G8B8, D3DPOOL_SYSTEMMEM, &sys, NULL);
    HRESULT hr = sys ? IDirect3DDevice9_GetRenderTargetData(d, bb, sys) : E_FAIL;
    D3DLOCKED_RECT lr;
    DWORD tl = 0, br = 0;
    if (SUCCEEDED(hr) && SUCCEEDED(IDirect3DSurface9_LockRect(sys, &lr, NULL, D3DLOCK_READONLY))) {
        tl = ((DWORD *)((BYTE *)lr.pBits + 100 * lr.Pitch))[100] & 0xffffff;
        br = ((DWORD *)((BYTE *)lr.pBits + 700 * lr.Pitch))[1200] & 0xffffff;
        IDirect3DSurface9_UnlockRect(sys);
    }
    if (sys)
        IDirect3DSurface9_Release(sys);
    snprintf(what, sizeof what, "its own 1280x768 screenshot (colours at 100,100 and 1200,700)%s", when);
    say(SUCCEEDED(hr) && tl == 0xff0000 && br == 0x00ff00, what, (unsigned)SUCCEEDED(hr), (unsigned)tl,
        (unsigned)br, 0);
}

int main(void)
{
    int sw = GetSystemMetrics(SM_CXSCREEN), sh = GetSystemMetrics(SM_CYSCREEN);
    WNDCLASSA wc = {0};
    wc.lpfnWndProc = proc;
    wc.hInstance = GetModuleHandleA(NULL);
    wc.lpszClassName = "render_probe";
    RegisterClassA(&wc);
    /* A borderless window over the whole screen, as the display fix sizes the game's. */
    HWND win = CreateWindowExA(0, "render_probe", "render_probe", WS_POPUP | WS_VISIBLE, 0, 0, sw, sh, NULL, NULL,
                               wc.hInstance, NULL);
    /* The library loaded as the game loads it, before its own code: its DllMain turns this program's imports. */
    if (!LoadLibraryA("CRT_R1.dll")) {
        printf("FAIL no CRT_R1.dll\n");
        return 1;
    }
    IDirect3D9 *d3d = Direct3DCreate9(D3D_SDK_VERSION);
    D3DPRESENT_PARAMETERS pp = {0};
    pp.BackBufferWidth = 1280;
    pp.BackBufferHeight = 768;
    pp.BackBufferFormat = D3DFMT_X8R8G8B8;
    pp.BackBufferCount = 1;
    pp.SwapEffect = D3DSWAPEFFECT_DISCARD;
    pp.hDeviceWindow = win;
    pp.Windowed = TRUE;
    pp.EnableAutoDepthStencil = TRUE;
    pp.AutoDepthStencilFormat = D3DFMT_D24S8;
    pp.PresentationInterval = D3DPRESENT_INTERVAL_IMMEDIATE;
    IDirect3DDevice9 *d = NULL;
    if (!d3d || FAILED(IDirect3D9_CreateDevice(d3d, 0, D3DDEVTYPE_HAL, win, D3DCREATE_HARDWARE_VERTEXPROCESSING, &pp,
                                               &d))) {
        printf("FAIL no device\n");
        return 1;
    }
    /* Its back buffer and its glow's render-target texture, as the game makes them. */
    IDirect3DSurface9 *bb = NULL, *ts = NULL;
    IDirect3DTexture9 *t = NULL;
    IDirect3DDevice9_GetBackBuffer(d, 0, 0, D3DBACKBUFFER_TYPE_MONO, &bb);
    IDirect3DDevice9_CreateTexture(d, 1280, 768, 1, D3DUSAGE_RENDERTARGET, D3DFMT_X8R8G8B8, D3DPOOL_DEFAULT, &t, NULL);
    IDirect3DTexture9_GetSurfaceLevel(t, 0, &ts);
    sizes(d, bb, t, ts, "");
    frames(d, bb, t, ts, 40, 20, "probe");
    screenshot(d, bb, "");
    /* A device reset, as the game makes one when its window turns between full screen and a window: its default-pool
     * objects let go first, the device reset with the same parameters, the objects made again, all of it again. */
    IDirect3DSurface9_Release(ts);
    IDirect3DTexture9_Release(t);
    IDirect3DSurface9_Release(bb);
    ts = bb = NULL;
    t = NULL;
    HRESULT reset = IDirect3DDevice9_Reset(d, &pp);
    say(SUCCEEDED(reset), "the device reset", (unsigned)reset, 0, 0, 0);
    if (FAILED(reset))
        return 1;
    IDirect3DDevice9_GetBackBuffer(d, 0, 0, D3DBACKBUFFER_TYPE_MONO, &bb);
    IDirect3DDevice9_CreateTexture(d, 1280, 768, 1, D3DUSAGE_RENDERTARGET, D3DFMT_X8R8G8B8, D3DPOOL_DEFAULT, &t, NULL);
    IDirect3DTexture9_GetSurfaceLevel(t, 0, &ts);
    sizes(d, bb, t, ts, " after a reset");
    frames(d, bb, t, ts, 40, 20, "after");
    screenshot(d, bb, " after a reset");
    /* Its exit code is the run's verdict (render.sh writes it after these lines). */
    return g_bad ? 1 : 0;
}
