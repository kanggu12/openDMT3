/*
 * Motion clarity (OPENDMT3_MOTION_CLARITY=crt or bfi; the Screen page, off by default): on a display whose refresh is a
 * whole multiple of 60 Hz from 120 up, each game frame is presented once a refresh for its N = refresh / 60 refreshes,
 * as a CRT's beam would light it (shaders/crt.hlsl, Blur Busters' CRT beam simulator): a rolling scan from the top
 * down (crt), or every row from the frame's first refresh (bfi, black frame insertion). A 60 a second picture held
 * still for a whole frame smears as the eye follows it; lit for a part of the frame it smears that much less (up to
 * 50 % less at 120 Hz, 75 % at 240 Hz), the picture that much darker.
 *
 * The chain's picture (the game's frame enlarged, the layer over it) is copied into one of two kept textures at each
 * game frame (the newest and the one before: the simulator's glow runs on into the next frame); each sub-frame is then
 * one pass from those two into the real back buffer, presented in its own refresh by hooks.c, the first at the frame's
 * tick and each next one a refresh later. The game's state is saved and put back around every pass (a state block, the
 * game's own render target and depth surface), as the chain's passes do.
 *
 * With OPENDMT3_STROBE_WATCH set (measuring only), the first sub-frames of one game frame in every 120 are read back
 * small (64 x 32) and logged as eight bands' brightness from the top down, with each sub-frame's time from the frame's
 * tick: what each refresh was given.
 */
#include "ingame.h"

#include <d3d9.h>
#include <d3dx9shader.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* The shader's source in this DLL's resources (post.rc). */
#define RES_CRT 105

/* D3DXCompileShader, from the game's d3dx9_40.dll (as post.c compiles its own passes). */
typedef HRESULT(WINAPI *CompileFn)(LPCSTR, UINT, const D3DXMACRO *, LPD3DXINCLUDE, LPCSTR, LPCSTR, DWORD,
                                   LPD3DXBUFFER *, LPD3DXBUFFER *, LPD3DXCONSTANTTABLE *);

/* Release a COM object and forget it. */
#define DROP(p)                                                                                                       \
    do {                                                                                                             \
        if (p) {                                                                                                     \
            ((IUnknown *)(p))->lpVtbl->Release((IUnknown *)(p));                                                     \
            (p) = NULL;                                                                                              \
        }                                                                                                            \
    } while (0)

/* The choice, the refreshes a frame it runs with (0: off), and whether it could not be made (said once). */
static int g_mode, g_n, g_broken;
/* The shaders and the triangle's layout (made once; they live through resets), and the state block (default pool:
 * made again after a reset). */
static IDirect3DVertexShader9 *g_vs;
static IDirect3DPixelShader9 *g_ps;
static IDirect3DVertexDeclaration9 *g_decl;
static IDirect3DStateBlock9 *g_state;
/* The two kept pictures (the back buffer's size), which one is the newest, how many hold a frame. */
static IDirect3DTexture9 *g_kept[2];
static int g_newest, g_have;
static int g_tex_w, g_tex_h;
/* The client's size the kept pictures were taken at (a change of the window starts them again). */
static int g_w, g_h;
/* The one triangle over the whole viewport, in clip space. */
static const float TRI[12] = {-1.0f, 1.0f, 0.0f, 1.0f, 3.0f, 1.0f, 0.0f, 1.0f, -1.0f, -3.0f, 0.0f, 1.0f};
/* Measuring (OPENDMT3_STROBE_WATCH): whether, the frames counted towards the next watched one, the small target and
 * its copy in system memory the sub-frames are read back through, and the watched frame's tick. */
static int g_watch = -1, g_watch_frames, g_watching;
static IDirect3DSurface9 *g_small, *g_small_sys;
static LARGE_INTEGER g_watch_tick;

void strobe_choose(int mode)
{
    g_mode = mode;
}

/* The game's D3DXCompileShader, or NULL. */
static CompileFn compiler(void)
{
    HMODULE m = GetModuleHandleA("d3dx9_40.dll");
    return m ? (CompileFn)(void *)GetProcAddress(m, "D3DXCompileShader") : NULL;
}

/* One entry point of the shader compiled and made; 0 with the compiler's words logged. */
static int make_shader(IDirect3DDevice9 *dev, CompileFn fn, const char *src, DWORD len, const char *entry,
                       const char *profile, void **out)
{
    LPD3DXBUFFER code = NULL, errors = NULL;
    HRESULT hr = fn(src, (UINT)len, NULL, NULL, entry, profile, 0, &code, &errors, NULL);
    if (FAILED(hr) || !code) {
        ingame_log("strobe: %s did not compile (0x%08lx): %.400s", entry, (unsigned long)hr,
                   errors ? (const char *)ID3DXBuffer_GetBufferPointer(errors) : "no message");
        DROP(errors);
        DROP(code);
        return 0;
    }
    const DWORD *bytes = (const DWORD *)ID3DXBuffer_GetBufferPointer(code);
    /* A vertex shader or a pixel shader, by its profile's first letter. */
    hr = profile[0] == 'v' ? IDirect3DDevice9_CreateVertexShader(dev, bytes, (IDirect3DVertexShader9 **)out)
                           : IDirect3DDevice9_CreatePixelShader(dev, bytes, (IDirect3DPixelShader9 **)out);
    DROP(errors);
    DROP(code);
    return SUCCEEDED(hr);
}

/* The shaders and the layout, once; 0 when they cannot be had (the choice then stays off for the run). */
static int make_once(IDirect3DDevice9 *dev)
{
    if (g_ps)
        return 1;
    if (g_broken)
        return 0;
    HRSRC r = FindResourceA(g_module, MAKEINTRESOURCEA(RES_CRT), MAKEINTRESOURCEA(10) /* RT_RCDATA */);
    HGLOBAL h = r ? LoadResource(g_module, r) : NULL;
    const char *src = h ? (const char *)LockResource(h) : NULL;
    DWORD len = r ? SizeofResource(g_module, r) : 0;
    CompileFn fn = compiler();
    /* One float4 a corner, its position. */
    static const D3DVERTEXELEMENT9 layout[] = {
        {0, 0, D3DDECLTYPE_FLOAT4, D3DDECLMETHOD_DEFAULT, D3DDECLUSAGE_POSITION, 0}, D3DDECL_END()};
    if (!src || !fn || !make_shader(dev, fn, src, len, "vs_crt", "vs_3_0", (void **)&g_vs) ||
        !make_shader(dev, fn, src, len, "ps_crt", "ps_3_0", (void **)&g_ps) ||
        FAILED(IDirect3DDevice9_CreateVertexDeclaration(dev, layout, &g_decl))) {
        g_broken = 1;
        DROP(g_vs);
        DROP(g_ps);
        DROP(g_decl);
        ingame_log("strobe: the sub-frames' pass could not be made: every frame shown whole");
        return 0;
    }
    return 1;
}

void strobe_refresh(int hz, int vsync)
{
    /* Whole multiples of 60 from 120 up (within 1 Hz, logic.c), with VSync (a present a refresh is what makes a
     * sub-frame a refresh). */
    int n = g_mode && vsync ? strobe_refreshes(hz) : 0;
    /* Said when it changes; off, with the rate kept to (0: none, as for a display that follows the frames or one whose
     * raster does not move) and VSync as they are, which name the cause. */
    if (g_mode && n != g_n && n)
        ingame_log("strobe: %s", g_mode == MOTION_BFI ? "black frames" : "the CRT beam");
    if (g_mode && n != g_n && !n)
        ingame_log("strobe: off (no fixed refresh at a whole multiple of 60 Hz from 120 up with VSync on: the refresh "
                   "kept to is %d Hz, VSync %s)", hz, vsync ? "on" : "off");
    if (g_mode && n)
        ingame_log("strobe: each frame shown over %d refreshes of %d Hz", n, hz);
    g_n = n;
    /* A new display: the kept pictures start again. */
    g_have = 0;
}

int strobe_subframes(void)
{
    return g_broken ? 0 : g_n;
}

void strobe_release(void)
{
    /* The default pool's objects go before a reset (the shaders and the layout live through it). */
    DROP(g_kept[0]);
    DROP(g_kept[1]);
    DROP(g_state);
    DROP(g_small);
    DROP(g_small_sys);
    g_have = 0;
}

/* The two kept textures at the back buffer's size, the state block, and the small target for watching; 0 when not. */
static int make_default(IDirect3DDevice9 *dev, IDirect3DSurface9 *bb)
{
    D3DSURFACE_DESC d;
    if (FAILED(IDirect3DSurface9_GetDesc(bb, &d)))
        return 0;
    /* A new back buffer's size (a reset): the old ones go. */
    if (g_kept[0] && (g_tex_w != (int)d.Width || g_tex_h != (int)d.Height))
        strobe_release();
    for (int i = 0; i < 2; i++)
        if (!g_kept[i] && FAILED(IDirect3DDevice9_CreateTexture(dev, d.Width, d.Height, 1, D3DUSAGE_RENDERTARGET,
                                                                d.Format, D3DPOOL_DEFAULT, &g_kept[i], NULL))) {
            ingame_log("strobe: the kept pictures (%ux%u) could not be made: every frame shown whole", d.Width,
                       d.Height);
            g_broken = 1;
            strobe_release();
            return 0;
        }
    g_tex_w = (int)d.Width;
    g_tex_h = (int)d.Height;
    if (!g_state && FAILED(IDirect3DDevice9_CreateStateBlock(dev, D3DSBT_ALL, &g_state)))
        return 0;
    /* Watched only on a back buffer of four bytes a pixel, the one layout watch() reads. */
    if (g_watch > 0 && !g_small && (d.Format == D3DFMT_X8R8G8B8 || d.Format == D3DFMT_A8R8G8B8)) {
        IDirect3DDevice9_CreateRenderTarget(dev, 64, 32, d.Format, D3DMULTISAMPLE_NONE, 0, FALSE, &g_small, NULL);
        IDirect3DDevice9_CreateOffscreenPlainSurface(dev, 64, 32, d.Format, D3DPOOL_SYSTEMMEM, &g_small_sys, NULL);
    }
    return 1;
}

int strobe_keep(IDirect3DDevice9 *dev)
{
    if (!strobe_subframes() || !make_once(dev))
        return 0;
    if (g_watch < 0) {
        char v[4];
        g_watch = GetEnvironmentVariableA("OPENDMT3_STROBE_WATCH", v, sizeof v) > 0;
    }
    int w, h;
    IDirect3DSurface9 *bb = post_back_buffer(&w, &h);
    if (!bb || w <= 0 || h <= 0 || !make_default(dev, bb))
        return 0;
    /* Another size of the window: the frame before is of another picture. */
    if (w != g_w || h != g_h) {
        g_have = 0;
        g_w = w;
        g_h = h;
    }
    /* This frame's picture into the older of the two, which becomes the newest. */
    int into = g_have ? 1 - g_newest : 0;
    IDirect3DSurface9 *s = NULL;
    if (FAILED(IDirect3DTexture9_GetSurfaceLevel(g_kept[into], 0, &s)))
        return 0;
    RECT r = {0, 0, w, h};
    HRESULT hr = IDirect3DDevice9_StretchRect(dev, bb, &r, s, &r, D3DTEXF_NONE);
    DROP(s);
    if (FAILED(hr))
        return 0;
    g_newest = into;
    g_have = g_have < 2 ? g_have + 1 : 2;
    /* Watched: one frame in every 120 (two seconds), its tick taken as now. */
    g_watching = g_watch > 0 && g_small && g_small_sys && ++g_watch_frames % 120 == 0;
    if (g_watching)
        QueryPerformanceCounter(&g_watch_tick);
    return 1;
}

/* Measuring: the back buffer as sub-frame k left it, small, in eight bands from the top, and its time. */
static void watch(IDirect3DDevice9 *dev, IDirect3DSurface9 *bb, int k)
{
    RECT r = {0, 0, g_w, g_h};
    D3DLOCKED_RECT lr;
    if (FAILED(IDirect3DDevice9_StretchRect(dev, bb, &r, g_small, NULL, D3DTEXF_POINT)) ||
        FAILED(IDirect3DDevice9_GetRenderTargetData(dev, g_small, g_small_sys)) ||
        FAILED(IDirect3DSurface9_LockRect(g_small_sys, &lr, NULL, D3DLOCK_READONLY)))
        return;
    /* The eight bands' brightness, one number each, into one line. */
    char line[160];
    int at = 0;
    for (int band = 0; band < 8; band++) {
        double sum = 0;
        /* Four of the 32 rows a band, every one of the 64 columns, the three colours' mean (0 to 255). */
        for (int y = band * 4; y < band * 4 + 4; y++) {
            /* The row's first byte, a pitch apart (the surface's rows may be longer than its pixels). */
            const BYTE *p = (const BYTE *)lr.pBits + y * lr.Pitch;
            /* Four bytes a pixel (blue, green, red, unused), as the surface is made (strobe_keep). */
            for (int x = 0; x < 64; x++)
                sum += (p[4 * x] + p[4 * x + 1] + p[4 * x + 2]) / 3.0;
        }
        /* The band's mean over its 256 pixels. */
        at += snprintf(line + at, sizeof line - (size_t)at, " %.0f", sum / 256.0);
    }
    IDirect3DSurface9_UnlockRect(g_small_sys);
    /* Its time from the frame's tick: when the sub-frame was read back, which follows its present. */
    LARGE_INTEGER now, f;
    QueryPerformanceCounter(&now);
    QueryPerformanceFrequency(&f);
    ingame_log("strobe: frame %ld sub-frame %d of %d at %.2f ms from its tick: bands%s", ingame_frame() + 1, k, g_n,
               (double)(now.QuadPart - g_watch_tick.QuadPart) * 1000.0 / (double)f.QuadPart, line);
}

int strobe_watched(void)
{
    return g_watching;
}

void strobe_draw(IDirect3DDevice9 *dev, int k)
{
    int w, h;
    IDirect3DSurface9 *bb = post_back_buffer(&w, &h);
    if (!g_have || !bb || !g_state)
        return;
    IDirect3DStateBlock9_Capture(g_state);
    /* Into the real back buffer (the device's own call: the game's turned one gives its proxy), no depth surface. */
    post_target(dev, 1);
    D3DVIEWPORT9 vp = {0, 0, (DWORD)g_w, (DWORD)g_h, 0.0f, 1.0f};
    IDirect3DDevice9_SetViewport(dev, &vp);
    static const D3DRENDERSTATETYPE off[] = {D3DRS_ZENABLE,          D3DRS_ZWRITEENABLE,   D3DRS_ALPHATESTENABLE,
                                             D3DRS_ALPHABLENDENABLE, D3DRS_STENCILENABLE,  D3DRS_SCISSORTESTENABLE,
                                             D3DRS_FOGENABLE,        D3DRS_SRGBWRITEENABLE, D3DRS_CLIPPLANEENABLE};
    for (size_t i = 0; i < sizeof off / sizeof off[0]; i++)
        IDirect3DDevice9_SetRenderState(dev, off[i], FALSE);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_CULLMODE, D3DCULL_NONE);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_COLORWRITEENABLE, 0xf);
    IDirect3DDevice9_SetVertexShader(dev, g_vs);
    IDirect3DDevice9_SetPixelShader(dev, g_ps);
    IDirect3DDevice9_SetVertexDeclaration(dev, g_decl);
    /* The newest picture and the one before, texel for texel. */
    for (DWORD s = 0; s < 2; s++) {
        IDirect3DTexture9 *t = s == 0 ? g_kept[g_newest] : g_kept[g_have > 1 ? 1 - g_newest : g_newest];
        IDirect3DDevice9_SetTexture(dev, s, (IDirect3DBaseTexture9 *)t);
        IDirect3DDevice9_SetSamplerState(dev, s, D3DSAMP_MINFILTER, D3DTEXF_POINT);
        IDirect3DDevice9_SetSamplerState(dev, s, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
        IDirect3DDevice9_SetSamplerState(dev, s, D3DSAMP_MIPFILTER, D3DTEXF_NONE);
        IDirect3DDevice9_SetSamplerState(dev, s, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
        IDirect3DDevice9_SetSamplerState(dev, s, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
        IDirect3DDevice9_SetSamplerState(dev, s, D3DSAMP_SRGBTEXTURE, FALSE);
    }
    /* The gain the simulator gives each refresh rate: 0.5 at 120 Hz, 0.6 at 180, 0.7 from 240 up. */
    float gain = g_n >= 4 ? 0.7f : g_n == 3 ? 0.6f : 0.5f;
    float c[12] = {(float)k, (float)g_n, (float)g_n * gain, g_mode == MOTION_BFI ? 1.0f : 0.0f,
                   g_have > 1 ? 1.0f : 0.0f, 0, 0, 0,
                   1.0f / (float)g_tex_w, 1.0f / (float)g_tex_h, 1.0f / (float)g_h, 0};
    IDirect3DDevice9_SetPixelShaderConstantF(dev, 0, c, 3);
    IDirect3DDevice9_BeginScene(dev);
    IDirect3DDevice9_DrawPrimitiveUP(dev, D3DPT_TRIANGLELIST, 1, TRI, 4 * sizeof(float));
    IDirect3DDevice9_EndScene(dev);
    if (g_watching)
        watch(dev, bb, k);
    /* The game's own target and depth surface, then its state (its viewport among it). */
    post_target(dev, 0);
    IDirect3DStateBlock9_Apply(g_state);
}
