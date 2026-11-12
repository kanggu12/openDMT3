/*
 * The post-process chain over the game's picture (ingame.h, post_*): the game keeps drawing its 1280x768 frame, but
 * into a render target of ours (a texture's own surface, or a multisampled target resolved into the texture when the
 * game asks for samples); at each present openDMT3 runs the anti-aliasing chosen on it, enlarges it
 * with the upscale filter chosen into the real back buffer at the window's size, and presents that one to one.
 *
 * The game never sees the difference: its back buffer (GetBackBuffer, GetRenderTarget, SetRenderTarget 0) is our
 * 1280x768 target, so every size it knows stays as it was (its own 1280x768 render-target texture and its glow
 * composite are untouched; the composite's shader constants mix sizes, so a larger picture cannot be had from it).
 * The real back buffer is the window's monitor's size (or the window's, if larger), presented through a source
 * rectangle of the window's client size, so the window can change size with no device reset. The chain runs for every
 * choice (Smooth with no anti-aliasing is its bilinear pass): the in-game layer (layer.c) is drawn in it, after the
 * upscale, at the window's own pixels, over glass made from the game's frame (a quarter-size copy, blurred). Our passes save and
 * put back the device's state with a state block, and the depth surface the game asked for is ours too (at the
 * game's size, multisampled only if the game's own setting asks for samples).
 *
 * The shaders (shaders/post.hlsl, shaders/smaa.hlsl with third_party/smaa/SMAA.hlsl) are compiled when the device is
 * made, with D3DXCompileShader from the game's own d3dx9_40.dll: the game imports that library, so it is always in
 * its process, and no HLSL compiler exists for this DLL's build (MinGW in a container). A shader that does not compile
 * leaves the game's picture as Direct3D's own stretch, as before, with the reason in the log.
 *
 * Measuring (OPENDMT3_POSTFX_DUMP, a folder; never set by the launcher): while the file dump.now is in it, the next
 * frame's game picture and the chain's output are written there as BMP files, and the same frame with the in-game
 * layer over it; with "all" in that file, every upscale filter and every anti-aliasing pass run on that same frame,
 * each written beside it, so they can be compared. A file toast.now there shows its words as the layer's toast.
 */
#include "ingame.h"
#include "passtimes.h"
#include "postmath.h"

#include <d3d9.h>
#include <d3dx9shader.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* The layer's blurred frame: an eighth of the game's (each texel 8x8 of the game's pixels). */
#define BLUR_W (GAME_W / 8)
#define BLUR_H (GAME_H / 8)

/* SMAA's precomputed area and search textures (third_party/smaa, MIT). */
#include "third_party/smaa/AreaTex.h"
#include "third_party/smaa/SearchTex.h"

/* The shader sources, in this DLL's resources (post.rc). */
#define RES_POST 101
#define RES_SMAA_LIB 102
#define RES_SMAA_PASSES 103

/* IDirect3DDevice9's methods replaced while the chain runs, by their place in its table. */
#define M_GET_BACK_BUFFER 18
#define M_SET_RENDER_TARGET 37
#define M_GET_RENDER_TARGET 38
typedef HRESULT(STDMETHODCALLTYPE *GetBackBufferFn)(IDirect3DDevice9 *, UINT, UINT, D3DBACKBUFFER_TYPE,
                                                    IDirect3DSurface9 **);
typedef HRESULT(STDMETHODCALLTYPE *SetRenderTargetFn)(IDirect3DDevice9 *, DWORD, IDirect3DSurface9 *);
typedef HRESULT(STDMETHODCALLTYPE *GetRenderTargetFn)(IDirect3DDevice9 *, DWORD, IDirect3DSurface9 **);
static GetBackBufferFn real_get_back_buffer;
static SetRenderTargetFn real_set_render_target;
static GetRenderTargetFn real_get_render_target;

/* D3DXCompileShader, from the game's d3dx9_40.dll. */
typedef HRESULT(WINAPI *CompileFn)(LPCSTR, UINT, const D3DXMACRO *, LPD3DXINCLUDE, LPCSTR, LPCSTR, DWORD,
                                   LPD3DXBUFFER *, LPD3DXBUFFER *, LPD3DXCONSTANTTABLE *);

/* Whether the chain runs on this device (chosen, compiled and made), and the choice it runs. */
static int g_active;
static int g_upscale, g_aa, g_sharpness;
/* The player's upscale filter (g_upscale is bilinear while the game is drawn at the picture's size). */
static int g_upscale_chosen;
/* Measuring: the dump folder (empty: none), and whether every pass is made so "all" can run them. */
static char g_dump_dir[MAX_PATH];
static int g_every_pass;

/* The game's window and the parameters it asked for (its own, kept to answer as the game expects). */
static HWND g_window;
static D3DPRESENT_PARAMETERS g_game_pp;
/* The real back buffer's size, as asked of Direct3D. */
static int g_bb_w, g_bb_h;
/* The game's frame as it is drawn, the chain's input: its own 1280x768, or the picture's size in the window when the
 * game is drawn at it (OPENDMT3_RENDER=display, render.c), chosen when the device is made or reset. */
static int g_src_w = GAME_W, g_src_h = GAME_H;

/* The shaders: our one vertex shader, and a pixel shader for each pass (and each SMAA preset). */
static DWORD *g_code_vs;
static DWORD *g_code_ps[PASS_KINDS];
static DWORD *g_code_smaa[4][3];
static IDirect3DVertexShader9 *g_vs;
static IDirect3DPixelShader9 *g_ps[PASS_KINDS];
static IDirect3DPixelShader9 *g_smaa_ps[4][3];
static IDirect3DVertexDeclaration9 *g_decl;
/* The one triangle every full-screen pass draws (over the whole viewport, already in clip space), and the card's own
 * copy of it, made once: DrawPrimitiveUP copied its 48 bytes into a buffer of the driver's again for every pass. */
static const float TRI[12] = {-1.0f, 1.0f, 0.0f, 1.0f, 3.0f, 1.0f, 0.0f, 1.0f, -1.0f, -3.0f, 0.0f, 1.0f};
static IDirect3DVertexBuffer9 *g_tri;

/* The surfaces and textures. Default pool ones go before a reset and come back after it; managed ones stay. */
static IDirect3DSurface9 *g_proxy;          /* the game's back buffer, 1280x768, as multisampled as the game asked */
/* The proxy is g_src's own surface (no samples asked): the game draws straight into what the chain reads, and the
 * frame's copy out of it is left out. */
static int g_proxy_is_src;
static IDirect3DSurface9 *g_real_bb;        /* the real back buffer (held while the chain runs) */
static IDirect3DSurface9 *g_depth;          /* the game's depth surface, at its size, as multisampled as the proxy */
static IDirect3DSurface9 *g_depth_plain;    /* with samples: one with none, for the game's other targets */
static IDirect3DTexture9 *g_src;            /* the game's frame: the proxy's own texture, or resolved from it */
static IDirect3DTexture9 *g_aa_out;         /* the anti-aliased frame */
static IDirect3DTexture9 *g_smaa_edges, *g_smaa_weights;
static IDirect3DTexture9 *g_area, *g_search; /* managed */
static IDirect3DTexture9 *g_nis_edges;
/* NIS's sums down the game's columns for each of the window's rows (ps_nis_rows): the game's width by the back
 * buffer's height, one 32-bit float a pixel. */
static IDirect3DTexture9 *g_nis_rows;
static IDirect3DTexture9 *g_nis_coef;       /* managed */
static IDirect3DTexture9 *g_easu;           /* EASU's result at the back buffer's size, RCAS's input */
static IDirect3DTexture9 *g_easu_len;       /* EASU's lengths of each texel, the game's size and a texel around */
/* SMAA's stencil at the game's size: its edge pass marks the pixels with an edge, and its weights pass runs on those
 * alone (the others keep the cleared weights, 0, which is what the pass gives a pixel with no edge). */
static IDirect3DSurface9 *g_smaa_stencil;
/* The layer's glass: the game's frame at an eighth (averaged), blurred across, then down, three small passes, each
 * reading what the one before wrote, the finished one shown while the next is made, under 80 % of tint. While a panel
 * shows they come one every BLUR_EVERY frames (below): the glass is new every 300 ms. g_blur[0] the average, [1]
 * across, [2] and [3] the finished pair (g_blur_shown the one read). */
static IDirect3DTexture9 *g_blur[4];
static int g_blur_stage, g_blur_shown = 2;
/* Counted up each time a new blurred frame is shown: a part composed over an older one is composed again. */
static unsigned g_blur_gen;
/* While a glass panel shows, the blur is refreshed slowly: one of its three passes every BLUR_EVERY frames (the whole
 * picture behind the glass new every 18 frames, 300 ms), a pass in its own small target being what costs a software
 * renderer most (0.3 ms a frame with one, measured, against 0.02 ms of its own work); the frames between draw none.
 * g_blur_wait: the frames left until the next pass; g_panels_before: whether the last frame had a glass panel (a panel
 * that comes has the whole blur made at once, so its glass is of that moment). */
#define BLUR_EVERY 6
static int g_blur_wait, g_panels_before;
/* A finished blurred frame exists for these textures (the chip's still glass reads it), and the held frame has its
 * own (made once when the game is held still: its frame does not change). */
static int g_blur_made, g_blur_held;
/* The blurred frame shown now was made under a panel (live): the chip's still glass is made again before it reads it
 * (reading a live one cost Wine's software renderer about 1 ms a frame for as long as the chip showed, measured with
 * OPENDMT3_LAYER_TIMING=frame; one made whole in one frame, nothing measurable). */
static int g_blur_live;
/* The game's first screen (first_screen_look): seen yet, the frames counted towards the next look, and the surface
 * the averaged frame is read back into. */
static int g_first_seen, g_first_look;
static IDirect3DSurface9 *g_first_probe;
static IDirect3DStateBlock9 *g_state;
/* The GPU's own time for our passes (timestamp queries), when the device has them: a ring of four frames. */
#define QUERIES 4
static IDirect3DQuery9 *g_q_disjoint[QUERIES], *g_q_freq[QUERIES], *g_q_begin[QUERIES], *g_q_end[QUERIES];
static int g_q_issued[QUERIES], g_q_next;
/* The layer's own GPU time, only with the diagnostic switch OPENDMT3_LAYER_TIMING=on (a player's game issues none of
 * these): a timestamp before and after its blur pass, one before its parts and one after each, read four frames late
 * with the chain's, never waited on. */
static IDirect3DQuery9 *g_q_blur0[QUERIES], *g_q_blur1[QUERIES], *g_q_parts[QUERIES][LAYER_PARTS + 1];
static int g_q_blur_issued[QUERIES], g_q_parts_n[QUERIES], g_q_parts_kind[QUERIES][LAYER_PARTS];
static int g_layer_timing = -1;
static int g_gpu_timing;
/* OPENDMT3_LAYER_TIMING=sync (measuring only, the Wine tests: it stalls the frame): each of the layer's passes alone,
 * the device made idle before and after it, timed on the CPU's clock with this event query. On a software renderer,
 * where timestamps inside a frame are not where its work is done, this is the measure that holds. */
static IDirect3DQuery9 *g_q_idle;
/* Frames drawn while measuring alone: every other one draws its parts nine times over. */
static long g_sync_frames;
/* The layer's costs by kind of part since the logger last read them (post_layer_costs). */
static LayerCosts g_costs;
/* The parts' textures let go (below: they may be in the default pool). */
static void drop_part_textures(void);
/* The surface of a texture's only level (below). */
static IDirect3DSurface9 *level0(IDirect3DTexture9 *t);
/* Where the game's picture went in the window this frame (logic.c picture_rect: its own shape kept, or filling it),
 * in the window's client pixels; the rest of the client is the bars. The final passes draw into it, the layer lies
 * in it, and the game's pointer is read against it (post_picture). */
static PicRect g_pic;
/* The client's size this frame (the picture and its bars). */
static int g_client_w, g_client_h;

/* The picture's GPU time by pass (OPENDMT3_PASS_TIMES=on, the launcher's switch; off unless asked): a timestamp after
 * each step of a frame's picture work, read four frames late with the chain's own, each step's time the gap since the
 * timestamp before it (passtimes.h keeps them). The steps: two timestamps back to back (what one costs), an empty pass
 * (one pixel drawn: what any pass costs before its work), the glass's blur, the bars, each anti-aliasing and upscale
 * pass, the layer's parts; and the game's own frame, from just after the last present to the chain's first timestamp.
 * g_stepping is on only while post_present draws the frame shown (never for the measuring dump's extra passes). */
#define STEPS 24
static int g_pass_times;
static int g_stepping;
static IDirect3DQuery9 *g_q_step[QUERIES][STEPS], *g_q_pre[QUERIES];
static const char *g_step_name[QUERIES][STEPS];
static int g_step_n[QUERIES], g_q_pre_issued[QUERIES];
/* The empty pass's target: one pixel. */
static IDirect3DTexture9 *g_empty;
/* Two stretches: the in-game log's two seconds, the launcher's note's ten. */
static PassTimes g_pt_log, g_pt_note;
static int g_pt_lines;

/* A timestamp after a step named `name` of this frame's picture work (nothing when not measuring by pass). */
static void step(IDirect3DDevice9 *dev, const char *name)
{
    int q = g_q_next;
    (void)dev;
    if (!g_pass_times || !g_stepping || g_step_n[q] >= STEPS)
        return;
    IDirect3DQuery9_Issue(g_q_step[q][g_step_n[q]], D3DISSUE_END);
    g_step_name[q][g_step_n[q]++] = name;
}

/* What the passes cost: CPU time in counter ticks this frame, the GPU's in microseconds when known (-1 not). */
static LONGLONG g_cpu_ticks;
static double g_gpu_us = -1;
static int g_pass_count;

/* --------------------------------------------------------------------------------------------- small helpers */

/* Release a COM object and forget it. */
#define DROP(p)                                                                                                         \
    do {                                                                                                               \
        if (p) {                                                                                                       \
            ((IUnknown *)(p))->lpVtbl->Release((IUnknown *)(p));                                                       \
            (p) = NULL;                                                                                                \
        }                                                                                                              \
    } while (0)

/* A resource of this DLL (a shader's text), its bytes and length; NULL when missing. */
static const char *resource(int id, DWORD *size)
{
    HRSRC r = FindResourceA(g_module, MAKEINTRESOURCEA(id), MAKEINTRESOURCEA(10) /* RT_RCDATA */);
    HGLOBAL h = r ? LoadResource(g_module, r) : NULL;
    *size = r ? SizeofResource(g_module, r) : 0;
    return h ? (const char *)LockResource(h) : NULL;
}

/* Put `ours` in entry `index` of the device's method table, keeping the method that was there. */
static void *swap_method(IDirect3DDevice9 *dev, int index, void *ours)
{
    void **table = *(void ***)dev;
    void *was = table[index];
    /* Already ours (a second device shares the table): the real one is the one kept the first time. */
    if (was == ours)
        return NULL;
    DWORD old;
    if (!VirtualProtect(&table[index], sizeof(void *), PAGE_READWRITE, &old))
        return NULL;
    table[index] = ours;
    VirtualProtect(&table[index], sizeof(void *), old, &old);
    return was;
}

/* ------------------------------------------------------------------------------------------------- shaders */

/* The game's D3DXCompileShader (its d3dx9_40.dll is one of its imports, so it is loaded), or NULL. */
static CompileFn compiler(void)
{
    HMODULE m = GetModuleHandleA("d3dx9_40.dll");
    /* Not loaded by name (an unusual setup): the one Windows finds, as the game's own load found it. */
    if (!m)
        m = LoadLibraryA("d3dx9_40.dll");
    if (!m)
        return NULL;
    char path[MAX_PATH] = "";
    GetModuleFileNameA(m, path, sizeof path);
    /* Under Wine the library may be Wine's own (its file says so in its header) or the game's copy: logged, since
     * their compilers differ. */
    const IMAGE_DOS_HEADER *dos = (const IMAGE_DOS_HEADER *)m;
    int builtin = memcmp((const char *)m + 0x40, "Wine builtin DLL", 16) == 0 || dos->e_lfanew < 0x40;
    ingame_log("post: shader compiler from %s%s", path, builtin ? " (Wine's own)" : "");
    return (CompileFn)(void *)GetProcAddress(m, "D3DXCompileShader");
}

/* Compile one entry point of `source` for `profile`; its bytecode (malloc'd), or NULL with the errors logged. */
static DWORD *compile(CompileFn fn, const char *source, size_t length, const D3DXMACRO *macros, const char *entry,
                      const char *profile)
{
    LPD3DXBUFFER code = NULL, errors = NULL;
    LARGE_INTEGER t0, t1, f;
    QueryPerformanceCounter(&t0);
    /* The compiler's default optimisation: its level 3 gives the same instructions for these shaders, but the game's
     * 2008 compiler takes 20 s over NIS's scaler at it (measured under Wine) instead of 0.15 s. */
    HRESULT hr = fn(source, (UINT)length, macros, NULL, entry, profile, 0, &code, &errors, NULL);
    QueryPerformanceCounter(&t1);
    QueryPerformanceFrequency(&f);
    if (FAILED(hr) || !code) {
        /* The compiler's own words (the first part: a log line is not a file). */
        const char *why = errors ? (const char *)ID3DXBuffer_GetBufferPointer(errors) : "no message";
        ingame_log("post: %s (%s) did not compile (0x%08lx): %.600s", entry, profile, (unsigned long)hr, why);
        DROP(errors);
        DROP(code);
        return NULL;
    }
    DWORD size = ID3DXBuffer_GetBufferSize(code);
    DWORD *out = malloc(size);
    if (out)
        memcpy(out, ID3DXBuffer_GetBufferPointer(code), size);
    /* The instruction count is in the bytecode's comment table; its size and the time it took are enough here. */
    ingame_log("post: compiled %s (%s), %lu bytes, %.1f ms", entry, profile, (unsigned long)size,
               (double)(t1.QuadPart - t0.QuadPart) * 1000.0 / (double)f.QuadPart);
    DROP(errors);
    DROP(code);
    return out;
}

/* The entry point of post.hlsl for each pass (SMAA's are in smaa.hlsl). */
static const char *const ENTRY[PASS_KINDS] = {"ps_fxaa", NULL, NULL, NULL, "ps_nearest", "ps_copy",
                                              "ps_easu_len", "ps_easu", "ps_rcas", "ps_nis_edges", "ps_nis_rows",
                                              "ps_nis_scale",
                                              "ps_ui_down", "ps_ui_blur", "ps_ui_glass", "ps_ui_compose"};
static const char *const SMAA_PRESET[4] = {"SMAA_PRESET_LOW", "SMAA_PRESET_MEDIUM", "SMAA_PRESET_HIGH",
                                           "SMAA_PRESET_ULTRA"};
static const char *const SMAA_ENTRY[3] = {"ps_smaa_edges", "ps_smaa_weights", "ps_smaa_blend"};

/* Whether a pass is needed: by the choice's plan, or every one when measuring every pass. */
static int needs(int kind, const int *plan, int count)
{
    if (g_every_pass)
        return 1;
    for (int i = 0; i < count; i++)
        if (plan[i] == kind)
            return 1;
    return 0;
}

/* Compile what the choice needs (or every pass when measuring). 1 when all of it compiled. */
static int compile_all(void)
{
    CompileFn fn = compiler();
    if (!fn) {
        ingame_log("post: no D3DXCompileShader in the game's process: Direct3D's own stretch");
        return 0;
    }
    DWORD post_len = 0, lib_len = 0, passes_len = 0;
    const char *post = resource(RES_POST, &post_len);
    const char *lib = resource(RES_SMAA_LIB, &lib_len);
    const char *passes = resource(RES_SMAA_PASSES, &passes_len);
    if (!post || !lib || !passes) {
        ingame_log("post: the shaders are missing from the DLL");
        return 0;
    }
    /* The plan at the largest output, to know which passes the choice runs (the window's size does not add any). */
    int plan[8];
    int count = post_plan(g_upscale, g_aa, GAME_W, GAME_H, 1 << 14, 1 << 14, plan);
    int ok = 1;
    if (!g_code_vs)
        ok &= (g_code_vs = compile(fn, post, post_len, NULL, "vs_main", "vs_3_0")) != NULL;
    for (int k = 0; k < PASS_KINDS; k++) {
        /* The layer's glass passes are compiled always, apart: one that does not compile leaves the layer drawn without
         * its blur (the fixed-function look), never the picture without the chain. */
        int layer = k == PASS_UI_DOWN || k == PASS_UI_BLUR || k == PASS_UI_GLASS || k == PASS_UI_COMPOSE;
        if (layer) {
            if (!g_code_ps[k])
                g_code_ps[k] = compile(fn, post, post_len, NULL, ENTRY[k], "ps_3_0");
            continue;
        }
        /* SMAA's three passes are compiled per preset below; the window may also need bilinear (it shrinks), and the
         * safety net's lighter choices (bilinear, and FXAA after SMAA) are ready before they are needed, so a step
         * down never waits for the compiler. */
        int lighter = k == PASS_BILINEAR || (k == PASS_FXAA && aa_smaa_preset(g_aa) >= 0);
        if (!ENTRY[k] || g_code_ps[k] || !(needs(k, plan, count) || lighter))
            continue;
        ok &= (g_code_ps[k] = compile(fn, post, post_len, NULL, ENTRY[k], "ps_3_0")) != NULL;
    }
    /* SMAA: its library with our definitions in front, our three passes after it, one build per preset. */
    /* mad() is not an intrinsic of the game's 2008 compiler: written out (SMAA's own GLSL path does the same). */
    static const char head[] = "float4 smaa_rt : register(c0);\n#define SMAA_RT_METRICS smaa_rt\n#define SMAA_HLSL_3 1\n"
                               "#define mad(a, b, c) ((a) * (b) + (c))\n";
    size_t total = sizeof head - 1 + lib_len + 1 + passes_len;
    char *text = malloc(total + 1);
    if (!text)
        return 0;
    memcpy(text, head, sizeof head - 1);
    memcpy(text + sizeof head - 1, lib, lib_len);
    text[sizeof head - 1 + lib_len] = '\n';
    memcpy(text + sizeof head - 1 + lib_len + 1, passes, passes_len);
    text[total] = 0;
    for (int p = 0; p < 4; p++) {
        if (!(g_every_pass || aa_smaa_preset(g_aa) == p))
            continue;
        D3DXMACRO macros[2] = {{SMAA_PRESET[p], "1"}, {NULL, NULL}};
        for (int s = 0; s < 3; s++)
            if (!g_code_smaa[p][s])
                ok &= (g_code_smaa[p][s] = compile(fn, text, total, macros, SMAA_ENTRY[s], "ps_3_0")) != NULL;
    }
    free(text);
    return ok;
}

/* ------------------------------------------------------------------------------------------ the device's side */

/* The window's client size, held to the back buffer (a window larger than its monitor's back buffer is stretched). */
static void output_size(int *w, int *h)
{
    RECT r;
    if (!g_window || !GetClientRect(g_window, &r) || r.right <= 0 || r.bottom <= 0) {
        *w = g_bb_w;
        *h = g_bb_h;
        return;
    }
    *w = r.right < g_bb_w ? r.right : g_bb_w;
    *h = r.bottom < g_bb_h ? r.bottom : g_bb_h;
}

int post_prepare(D3DPRESENT_PARAMETERS *pp, HWND window, int creating)
{
    if (creating) {
        /* The choice, read once: the launcher's settings do not change while the game runs. */
        g_upscale = g_upscale_chosen = g_settings.upscale;
        g_aa = g_settings.antialiasing;
        g_sharpness = g_settings.sharpness;
        DWORD got = GetEnvironmentVariableA("OPENDMT3_POSTFX_DUMP", g_dump_dir, sizeof g_dump_dir);
        if (!got || got >= sizeof g_dump_dir)
            g_dump_dir[0] = 0;
        /* Measuring every pass needs every pass made. */
        g_every_pass = g_dump_dir[0] != 0;
    }
    /* Every choice runs the chain, Smooth with no anti-aliasing as its bilinear pass (what Direct3D's own stretch
     * showed): the in-game layer is drawn in it, at the window's size. */
    if (!pp)
        return 0;
    /* The game in exclusive full screen (openDMT3 never sets it up so): the display's mode does the scaling. */
    if (!pp->Windowed) {
        ingame_log("post: the game asked for exclusive full screen: no chain");
        return 0;
    }
    if (creating && !compile_all())
        return 0;
    g_window = window;
    g_game_pp = *pp;
    /* The window's client size and its monitor's, for a back buffer the window can grow to with no reset. */
    RECT client = {0, 0, GAME_W, GAME_H};
    if (window)
        GetClientRect(window, &client);
    MONITORINFO mi;
    mi.cbSize = sizeof mi;
    int mon_w = client.right, mon_h = client.bottom;
    if (window && GetMonitorInfoA(MonitorFromWindow(window, MONITOR_DEFAULTTONEAREST), &mi)) {
        mon_w = mi.rcMonitor.right - mi.rcMonitor.left;
        mon_h = mi.rcMonitor.bottom - mi.rcMonitor.top;
    }
    back_buffer_size(client.right, client.bottom, mon_w, mon_h, &g_bb_w, &g_bb_h);
    /* What Direct3D makes: that size, copied (a source rectangle can then be presented one to one), no depth surface
     * of its own (ours is at the game's size), no samples (ours are in the proxy). */
    pp->BackBufferWidth = (UINT)g_bb_w;
    pp->BackBufferHeight = (UINT)g_bb_h;
    pp->BackBufferCount = 1;
    pp->SwapEffect = D3DSWAPEFFECT_COPY;
    pp->MultiSampleType = D3DMULTISAMPLE_NONE;
    pp->MultiSampleQuality = 0;
    pp->EnableAutoDepthStencil = FALSE;
    pp->Flags &= ~(DWORD)(D3DPRESENTFLAG_DISCARD_DEPTHSTENCIL | D3DPRESENTFLAG_LOCKABLE_BACKBUFFER);
    ingame_log("post: back buffer %dx%d (window %ldx%ld, monitor %dx%d), upscale %s, sharpness %d, anti-aliasing %s",
               g_bb_w, g_bb_h, client.right, client.bottom, mon_w, mon_h, UPSCALE_NAMES[g_upscale], g_sharpness,
               AA_NAMES[g_aa]);
    return 1;
}

/* Make a render-target texture; 0 on failure (logged). */
static int rt_texture(IDirect3DDevice9 *dev, int w, int h, D3DFORMAT f, IDirect3DTexture9 **out, const char *what)
{
    HRESULT hr = IDirect3DDevice9_CreateTexture(dev, (UINT)w, (UINT)h, 1, D3DUSAGE_RENDERTARGET, f, D3DPOOL_DEFAULT,
                                                out, NULL);
    if (FAILED(hr))
        ingame_log("post: %s (%dx%d, format %d) not made (0x%08lx)", what, w, h, f, (unsigned long)hr);
    return SUCCEEDED(hr);
}

/* The managed textures (they live through resets): SMAA's area and search textures, NIS's filter banks. */
static int make_managed(IDirect3DDevice9 *dev)
{
    D3DLOCKED_RECT lr;
    int smaa = g_every_pass || aa_smaa_preset(g_aa) >= 0;
    if (smaa && !g_area) {
        /* The area texture is R8G8; Direct3D 9 has it as A8L8 (luminance the first byte, alpha the second), which
         * SMAA's Direct3D 9 path reads as .ra. */
        if (FAILED(IDirect3DDevice9_CreateTexture(dev, AREATEX_WIDTH, AREATEX_HEIGHT, 1, 0, D3DFMT_A8L8,
                                                  D3DPOOL_MANAGED, &g_area, NULL)))
            return 0;
        if (FAILED(IDirect3DTexture9_LockRect(g_area, 0, &lr, NULL, 0)))
            return 0;
        for (int y = 0; y < AREATEX_HEIGHT; y++)
            memcpy((BYTE *)lr.pBits + y * lr.Pitch, areaTexBytes + y * AREATEX_PITCH, AREATEX_PITCH);
        IDirect3DTexture9_UnlockRect(g_area, 0);
        /* The search texture is one byte a texel: L8. */
        if (FAILED(IDirect3DDevice9_CreateTexture(dev, SEARCHTEX_WIDTH, SEARCHTEX_HEIGHT, 1, 0, D3DFMT_L8,
                                                  D3DPOOL_MANAGED, &g_search, NULL)))
            return 0;
        if (FAILED(IDirect3DTexture9_LockRect(g_search, 0, &lr, NULL, 0)))
            return 0;
        for (int y = 0; y < SEARCHTEX_HEIGHT; y++)
            memcpy((BYTE *)lr.pBits + y * lr.Pitch, searchTexBytes + y * SEARCHTEX_PITCH, SEARCHTEX_PITCH);
        IDirect3DTexture9_UnlockRect(g_search, 0);
    }
    if ((g_every_pass || g_upscale == UPSCALE_NIS) && !g_nis_coef) {
        /* 4 x 64 floats: coef_scale's six taps of a phase in texels 0 and 1 of its row, coef_usm's in 2 and 3. */
        if (FAILED(IDirect3DDevice9_CreateTexture(dev, 4, NIS_PHASES, 1, 0, D3DFMT_A32B32G32R32F, D3DPOOL_MANAGED,
                                                  &g_nis_coef, NULL)))
            return 0;
        if (FAILED(IDirect3DTexture9_LockRect(g_nis_coef, 0, &lr, NULL, 0)))
            return 0;
        for (int p = 0; p < NIS_PHASES; p++) {
            float *row = (float *)((BYTE *)lr.pBits + p * lr.Pitch);
            /* A32B32G32R32F keeps red first in memory: the shader's .x is the first float. */
            float texels[16] = {NIS_COEF_SCALE[p][0], NIS_COEF_SCALE[p][1], NIS_COEF_SCALE[p][2], NIS_COEF_SCALE[p][3],
                                NIS_COEF_SCALE[p][4], NIS_COEF_SCALE[p][5], 0, 0,
                                NIS_COEF_USM[p][0],   NIS_COEF_USM[p][1],   NIS_COEF_USM[p][2],   NIS_COEF_USM[p][3],
                                NIS_COEF_USM[p][4],   NIS_COEF_USM[p][5],   0, 0};
            memcpy(row, texels, sizeof texels);
        }
        IDirect3DTexture9_UnlockRect(g_nis_coef, 0);
    }
    return 1;
}

/* The timestamp queries, when the device has them. */
static void make_queries(IDirect3DDevice9 *dev)
{
    /* The diagnostic switch, read once: the layer's own timestamps (measuring; a player's game has none). */
    if (g_layer_timing < 0) {
        char v[8];
        DWORD got = GetEnvironmentVariableA("OPENDMT3_LAYER_TIMING", v, sizeof v);
        g_layer_timing = got > 0 && got < sizeof v
                             ? (!lstrcmpiA(v, "on") ? 1 : !lstrcmpiA(v, "sync") ? 2 : !lstrcmpiA(v, "frame") ? 3 : 0)
                             : 0;
        static const char *const how[4] = {"", "on", "sync", "frame"};
        if (g_layer_timing)
            ingame_log("post: the layer's GPU time measured (OPENDMT3_LAYER_TIMING=%s)", how[g_layer_timing]);
    }
    g_costs.timing = g_layer_timing;
    /* The chain's own: the safety net's measure of the picture's passes. */
    g_gpu_timing = 1;
    for (int i = 0; i < QUERIES && g_gpu_timing; i++) {
        g_gpu_timing = SUCCEEDED(IDirect3DDevice9_CreateQuery(dev, D3DQUERYTYPE_TIMESTAMPDISJOINT, &g_q_disjoint[i])) &&
                       SUCCEEDED(IDirect3DDevice9_CreateQuery(dev, D3DQUERYTYPE_TIMESTAMPFREQ, &g_q_freq[i])) &&
                       SUCCEEDED(IDirect3DDevice9_CreateQuery(dev, D3DQUERYTYPE_TIMESTAMP, &g_q_begin[i])) &&
                       SUCCEEDED(IDirect3DDevice9_CreateQuery(dev, D3DQUERYTYPE_TIMESTAMP, &g_q_end[i]));
        g_q_issued[i] = 0;
        g_q_blur_issued[i] = 0;
        g_q_parts_n[i] = 0;
    }
    /* By pass, when the launcher's switch asks (and the chain's own timestamps could be made). */
    g_pass_times = g_settings.pass_times && g_gpu_timing;
    for (int i = 0; i < QUERIES && g_pass_times; i++) {
        g_step_n[i] = 0;
        g_q_pre_issued[i] = 0;
        g_pass_times = SUCCEEDED(IDirect3DDevice9_CreateQuery(dev, D3DQUERYTYPE_TIMESTAMP, &g_q_pre[i]));
        for (int k = 0; k < STEPS && g_pass_times; k++)
            g_pass_times = SUCCEEDED(IDirect3DDevice9_CreateQuery(dev, D3DQUERYTYPE_TIMESTAMP, &g_q_step[i][k]));
    }
    if (g_settings.pass_times)
        ingame_log(g_pass_times ? "post: the picture's GPU time measured by pass (OPENDMT3_PASS_TIMES=on)"
                                : "post: the picture's GPU time by pass was asked for: this device has no timestamps");
    /* Measuring alone or by the frame: the event query the device is made idle by. */
    if (g_layer_timing >= 2 && FAILED(IDirect3DDevice9_CreateQuery(dev, D3DQUERYTYPE_EVENT, &g_q_idle))) {
        ingame_log("post: no event query: the layer's passes not measured alone");
        g_layer_timing = 0;
        g_costs.timing = 0;
    }
    /* The layer's timestamps, with the switch on only (and only where the chain's could be made). */
    for (int i = 0; i < QUERIES && g_gpu_timing && g_layer_timing == 1; i++) {
        int ok = SUCCEEDED(IDirect3DDevice9_CreateQuery(dev, D3DQUERYTYPE_TIMESTAMP, &g_q_blur0[i])) &&
                 SUCCEEDED(IDirect3DDevice9_CreateQuery(dev, D3DQUERYTYPE_TIMESTAMP, &g_q_blur1[i]));
        for (int k = 0; k <= LAYER_PARTS && ok; k++)
            ok = SUCCEEDED(IDirect3DDevice9_CreateQuery(dev, D3DQUERYTYPE_TIMESTAMP, &g_q_parts[i][k]));
        if (!ok) {
            ingame_log("post: the layer's timestamps could not be made: its GPU time not measured");
            g_layer_timing = 0;
            g_costs.timing = 0;
        }
    }
    g_q_next = 0;
}

/* Every default pool object of ours: before a reset, or when the chain gives up. */
static void release_default(void)
{
    DROP(g_proxy);
    DROP(g_real_bb);
    DROP(g_depth);
    DROP(g_depth_plain);
    DROP(g_src);
    /* The first screen's read-back surface: made again when next needed. */
    DROP(g_first_probe);
    DROP(g_aa_out);
    DROP(g_smaa_edges);
    DROP(g_smaa_weights);
    DROP(g_nis_edges);
    DROP(g_nis_rows);
    DROP(g_easu);
    DROP(g_easu_len);
    DROP(g_smaa_stencil);
    for (int i = 0; i < 4; i++)
        DROP(g_blur[i]);
    DROP(g_state);
    for (int i = 0; i < QUERIES; i++) {
        DROP(g_q_disjoint[i]);
        DROP(g_q_freq[i]);
        DROP(g_q_begin[i]);
        DROP(g_q_end[i]);
        DROP(g_q_blur0[i]);
        DROP(g_q_blur1[i]);
        for (int k = 0; k <= LAYER_PARTS; k++)
            DROP(g_q_parts[i][k]);
        DROP(g_q_pre[i]);
        for (int k = 0; k < STEPS; k++)
            DROP(g_q_step[i][k]);
    }
    DROP(g_q_idle);
    DROP(g_empty);
    DROP(g_tri);
    /* New blur textures will have no finished frame in them; the parts' textures are made again too. */
    g_blur_made = g_blur_held = 0;
    drop_part_textures();
}

/* Make the default pool objects for the device as it now is, the game's frame at g_src_w x g_src_h; 1 on success. */
static int make_default_at(IDirect3DDevice9 *dev)
{
    D3DFORMAT fmt = g_game_pp.BackBufferFormat == D3DFMT_UNKNOWN ? D3DFMT_X8R8G8B8 : g_game_pp.BackBufferFormat;
    /* Samples only if the game itself asks for them (setting.ini's multipleSample), and the device has them for the
     * picture and its depth; none otherwise. */
    D3DMULTISAMPLE_TYPE ms = g_game_pp.MultiSampleType;
    IDirect3D9 *d3d = NULL;
    D3DDEVICE_CREATION_PARAMETERS cp;
    if (ms != D3DMULTISAMPLE_NONE && SUCCEEDED(IDirect3DDevice9_GetDirect3D(dev, &d3d)) &&
        SUCCEEDED(IDirect3DDevice9_GetCreationParameters(dev, &cp))) {
        int ok = SUCCEEDED(IDirect3D9_CheckDeviceMultiSampleType(d3d, cp.AdapterOrdinal, cp.DeviceType, fmt, TRUE, ms,
                                                                 NULL));
        if (ok && g_game_pp.EnableAutoDepthStencil)
            ok = SUCCEEDED(IDirect3D9_CheckDeviceMultiSampleType(d3d, cp.AdapterOrdinal, cp.DeviceType,
                                                                 g_game_pp.AutoDepthStencilFormat, TRUE, ms, NULL));
        if (!ok) {
            ingame_log("post: %d samples are not offered by this device: none", (int)ms);
            ms = D3DMULTISAMPLE_NONE;
        }
    }
    DROP(d3d);
    /* The frame's texture, which the chain reads: the size the game draws at, its format. */
    if (!rt_texture(dev, g_src_w, g_src_h, fmt, &g_src, "the frame's texture"))
        return 0;
    /* The game's back buffer: with no samples, the frame's texture's own surface, so the game draws straight into
     * what the chain reads and no copy is made a frame; with samples, a multisampled render target of its size and
     * format, resolved into the texture each frame. */
    g_proxy_is_src = ms == D3DMULTISAMPLE_NONE;
    if (g_proxy_is_src)
        g_proxy = level0(g_src);
    else if (FAILED(IDirect3DDevice9_CreateRenderTarget(dev, (UINT)g_src_w, (UINT)g_src_h, fmt, ms, 0, FALSE, &g_proxy,
                                                        NULL)))
        g_proxy = NULL;
    if (!g_proxy) {
        ingame_log("post: the game's back buffer was not made");
        return 0;
    }
    /* Its depth surface, when it asked for one: the proxy's size, the game's format, as many samples as the proxy. */
    if (g_game_pp.EnableAutoDepthStencil) {
        BOOL discard = (g_game_pp.Flags & D3DPRESENTFLAG_DISCARD_DEPTHSTENCIL) != 0;
        if (FAILED(IDirect3DDevice9_CreateDepthStencilSurface(dev, (UINT)g_src_w, (UINT)g_src_h,
                                                              g_game_pp.AutoDepthStencilFormat, ms, 0, discard,
                                                              &g_depth, NULL)))
            return 0;
        /* With samples, the game's own render-target texture needs a depth surface with none to draw with. */
        if (ms != D3DMULTISAMPLE_NONE &&
            FAILED(IDirect3DDevice9_CreateDepthStencilSurface(dev, (UINT)g_src_w, (UINT)g_src_h,
                                                              g_game_pp.AutoDepthStencilFormat, D3DMULTISAMPLE_NONE, 0,
                                                              discard, &g_depth_plain, NULL)))
            return 0;
    }
    if (FAILED(real_get_back_buffer(dev, 0, 0, D3DBACKBUFFER_TYPE_MONO, &g_real_bb)))
        return 0;
    /* The anti-aliased frame; SMAA's and NIS's intermediates; EASU's result. */
    int plan[8], count = post_plan(g_upscale, g_aa, g_src_w, g_src_h, 1 << 14, 1 << 14, plan);
    if ((g_every_pass || g_aa == AA_FXAA || aa_smaa_preset(g_aa) >= 0) &&
        !rt_texture(dev, g_src_w, g_src_h, fmt, &g_aa_out, "the anti-aliased frame"))
        return 0;
    if (needs(PASS_SMAA_EDGES, plan, count) &&
        (!rt_texture(dev, g_src_w, g_src_h, D3DFMT_A8R8G8B8, &g_smaa_edges, "SMAA's edges") ||
         !rt_texture(dev, g_src_w, g_src_h, D3DFMT_A8R8G8B8, &g_smaa_weights, "SMAA's weights")))
        return 0;
    /* Its stencil (the weights on every pixel, as before, when the device has none to give). */
    if (needs(PASS_SMAA_EDGES, plan, count) && !g_smaa_stencil &&
        FAILED(IDirect3DDevice9_CreateDepthStencilSurface(dev, (UINT)g_src_w, (UINT)g_src_h, D3DFMT_D24S8,
                                                          D3DMULTISAMPLE_NONE, 0, TRUE, &g_smaa_stencil, NULL))) {
        g_smaa_stencil = NULL;
        ingame_log("post: no stencil for SMAA: its weights worked out on every pixel");
    }
    /* NIS's edge map: two signed half floats a pixel (ps_nis_edges), as the reference's half-precision build keeps it;
     * four halves or four 32-bit floats on a device that cannot draw into two (the same two numbers in their first two). */
    if (needs(PASS_NIS_EDGES, plan, count) &&
        !rt_texture(dev, g_src_w, g_src_h, D3DFMT_G16R16F, &g_nis_edges, "NIS's edge map") &&
        !rt_texture(dev, g_src_w, g_src_h, D3DFMT_A16B16G16R16F, &g_nis_edges, "NIS's edge map in four halves") &&
        !rt_texture(dev, g_src_w, g_src_h, D3DFMT_A32B32G32R32F, &g_nis_edges, "NIS's edge map in four floats"))
        return 0;
    /* NIS's column sums: one 32-bit float a pixel (kept exactly: the scaler's own sums go on from them), four on a
     * device that cannot draw into one (the sum in the first). */
    if (needs(PASS_NIS_ROWS, plan, count) &&
        !rt_texture(dev, g_src_w, g_bb_h, D3DFMT_R32F, &g_nis_rows, "NIS's column sums") &&
        !rt_texture(dev, g_src_w, g_bb_h, D3DFMT_A32B32G32R32F, &g_nis_rows, "NIS's column sums in four floats"))
        return 0;
    if (needs(PASS_EASU, plan, count) && !rt_texture(dev, g_bb_w, g_bb_h, fmt, &g_easu, "EASU's result"))
        return 0;
    /* EASU's lengths: two 32-bit floats a texel (the numbers FsrEasuF works out, kept exactly), a texel larger than the
     * game's picture on every side (ps_easu_len); four floats, the directions too, measured slower to write than the
     * passes they saved at 1080 lines. A device that cannot draw into those gets bilinear for FSR 1 (run_upscale), the
     * rest of the chain as chosen. */
    if (needs(PASS_EASU_LEN, plan, count) && !g_easu_len &&
        !rt_texture(dev, g_src_w + 2, g_src_h + 2, D3DFMT_G32R32F, &g_easu_len, "EASU's lengths")) {
        g_easu_len = NULL;
        ingame_log("post: FSR 1 needs 32-bit float targets this device does not draw into: bilinear in its place");
    }
    /* The passes' triangle in a buffer of the card's own; DrawPrimitiveUP as before when it cannot be made. */
    if (!g_tri && SUCCEEDED(IDirect3DDevice9_CreateVertexBuffer(dev, sizeof TRI, D3DUSAGE_WRITEONLY, 0, D3DPOOL_DEFAULT,
                                                                &g_tri, NULL))) {
        void *at = NULL;
        if (SUCCEEDED(IDirect3DVertexBuffer9_Lock(g_tri, 0, 0, &at, 0)) && at) {
            memcpy(at, TRI, sizeof TRI);
            IDirect3DVertexBuffer9_Unlock(g_tri);
        } else {
            DROP(g_tri);
        }
    }
    /* Measuring by pass: the empty pass's one pixel (its timing left out when it cannot be made). */
    if (g_settings.pass_times && !g_empty)
        rt_texture(dev, 1, 1, fmt, &g_empty, "the empty pass's pixel");
    /* The layer's glass: four eighth-size targets (above), black to begin with. Without them the layer draws its
     * fixed-function look; the chain goes on either way. */
    int glass = g_code_ps[PASS_UI_GLASS] != NULL;
    for (int i = 0; i < 4 && glass; i++) {
        glass = rt_texture(dev, BLUR_W, BLUR_H, D3DFMT_X8R8G8B8, &g_blur[i], "the glass");
        IDirect3DSurface9 *b = NULL;
        if (glass && SUCCEEDED(IDirect3DTexture9_GetSurfaceLevel(g_blur[i], 0, &b)))
            IDirect3DDevice9_ColorFill(dev, b, NULL, D3DCOLOR_XRGB(0, 0, 0));
        DROP(b);
    }
    if (!glass)
        for (int i = 0; i < 4; i++)
            DROP(g_blur[i]);
    g_blur_stage = 0;
    g_panels_before = 0;
    g_blur_live = 0;
    if (!make_managed(dev))
        return 0;
    /* The state block our passes put the game's state back from. */
    if (FAILED(IDirect3DDevice9_CreateStateBlock(dev, D3DSBT_ALL, &g_state)))
        return 0;
    make_queries(dev);
    /* The game draws into the proxy from now on, with its depth. */
    real_set_render_target(dev, 0, g_proxy);
    IDirect3DDevice9_SetDepthStencilSurface(dev, g_depth);
    return 1;
}

/* Whether render.c's replacements are in the device's tables (the game can be drawn at the picture's size). */
static int g_render_hooked;

/* The size the game is drawn at: its own, or (OPENDMT3_RENDER=display) the picture's size in the window's client now,
 * the largest its targets may be on this device; never smaller than its own. */
static void render_size(IDirect3DDevice9 *dev, int *w, int *h)
{
    *w = GAME_W;
    *h = GAME_H;
    if (!g_settings.render_display || !g_render_hooked)
        return;
    int cw, ch;
    output_size(&cw, &ch);
    /* The picture's size in the client, held to the device's largest texture (logic.c render_size_for). */
    D3DCAPS9 caps;
    memset(&caps, 0, sizeof caps);
    IDirect3DDevice9_GetDeviceCaps(dev, &caps);
    render_size_for(cw, ch, g_settings.fill, (int)caps.MaxTextureWidth, (int)caps.MaxTextureHeight, w, h);
}

/* Make the default pool objects for the device as it now is: the game drawn at the size chosen, and when anything at a
 * larger size cannot be made, everything again at the game's own size (today's path). 1 on success. */
static int make_default(IDirect3DDevice9 *dev)
{
    render_size(dev, &g_src_w, &g_src_h);
    render_set(g_src_w, g_src_h);
    /* Drawn at the picture's size, the chain only copies it there (bilinear when the window changes size after): the
     * upscale filters' targets are not made. Otherwise the player's filter. */
    g_upscale = render_on() ? UPSCALE_SMOOTH : g_upscale_chosen;
    if (make_default_at(dev))
        return 1;
    if (!render_on())
        return 0;
    ingame_log("post: the game's targets could not be made at %dx%d: drawn at its own size", g_src_w, g_src_h);
    release_default();
    g_src_w = GAME_W;
    g_src_h = GAME_H;
    render_set(GAME_W, GAME_H);
    g_upscale = g_upscale_chosen;
    return make_default_at(dev);
}

/* The shader objects (they live through resets). */
static int make_shaders(IDirect3DDevice9 *dev)
{
    static const D3DVERTEXELEMENT9 el[] = {{0, 0, D3DDECLTYPE_FLOAT4, D3DDECLMETHOD_DEFAULT, D3DDECLUSAGE_POSITION, 0},
                                           D3DDECL_END()};
    if (!g_decl && FAILED(IDirect3DDevice9_CreateVertexDeclaration(dev, el, &g_decl)))
        return 0;
    if (!g_vs && FAILED(IDirect3DDevice9_CreateVertexShader(dev, g_code_vs, &g_vs)))
        return 0;
    for (int k = 0; k < PASS_KINDS; k++)
        if (g_code_ps[k] && !g_ps[k] && FAILED(IDirect3DDevice9_CreatePixelShader(dev, g_code_ps[k], &g_ps[k])))
            return 0;
    for (int p = 0; p < 4; p++)
        for (int s = 0; s < 3; s++)
            if (g_code_smaa[p][s] && !g_smaa_ps[p][s] &&
                FAILED(IDirect3DDevice9_CreatePixelShader(dev, g_code_smaa[p][s], &g_smaa_ps[p][s])))
                return 0;
    return 1;
}

/* The game asks for its back buffer: the proxy. */
static HRESULT STDMETHODCALLTYPE our_get_back_buffer(IDirect3DDevice9 *dev, UINT chain, UINT index,
                                                     D3DBACKBUFFER_TYPE type, IDirect3DSurface9 **out)
{
    if (g_active && chain == 0 && index == 0 && out && g_proxy) {
        IDirect3DSurface9_AddRef(g_proxy);
        *out = g_proxy;
        return D3D_OK;
    }
    return real_get_back_buffer(dev, chain, index, type, out);
}

/* The game sets a render target: the real back buffer means the proxy; with samples, each target gets the depth surface
 * with its number of samples. */
static HRESULT STDMETHODCALLTYPE our_set_render_target(IDirect3DDevice9 *dev, DWORD index, IDirect3DSurface9 *s)
{
    if (!g_active || index != 0)
        return real_set_render_target(dev, index, s);
    if (s && s == g_real_bb)
        s = g_proxy;
    HRESULT hr = real_set_render_target(dev, index, s);
    if (g_depth_plain && SUCCEEDED(hr))
        IDirect3DDevice9_SetDepthStencilSurface(dev, s == g_proxy ? g_depth : g_depth_plain);
    return hr;
}

/* The game asks which target is set: never the real back buffer (only our passes set it, and put the proxy back). */
static HRESULT STDMETHODCALLTYPE our_get_render_target(IDirect3DDevice9 *dev, DWORD index, IDirect3DSurface9 **out)
{
    HRESULT hr = real_get_render_target(dev, index, out);
    if (g_active && SUCCEEDED(hr) && out && *out && *out == g_real_bb && g_proxy) {
        IDirect3DSurface9_Release(*out);
        IDirect3DSurface9_AddRef(g_proxy);
        *out = g_proxy;
    }
    return hr;
}

int post_attach(IDirect3DDevice9 *dev)
{
    /* The getters and the setter turned to ours first: make_default reads the real back buffer through them. */
    void *was = swap_method(dev, M_GET_BACK_BUFFER, (void *)our_get_back_buffer);
    if (was)
        real_get_back_buffer = (GetBackBufferFn)was;
    was = swap_method(dev, M_SET_RENDER_TARGET, (void *)our_set_render_target);
    if (was)
        real_set_render_target = (SetRenderTargetFn)was;
    was = swap_method(dev, M_GET_RENDER_TARGET, (void *)our_get_render_target);
    if (was)
        real_get_render_target = (GetRenderTargetFn)was;
    /* Drawing the game at the picture's size (OPENDMT3_RENDER=display): the methods that make its targets and read
     * their sizes turned first, so its targets made from now on can be larger. */
    if (g_settings.render_display && !g_render_hooked && !(g_render_hooked = render_attach(dev)))
        ingame_log("post: the device's tables could not be changed: the game drawn at its own size");
    if (!make_shaders(dev) || !make_default(dev)) {
        ingame_log("post: the chain could not be set up: Direct3D's own stretch");
        release_default();
        g_active = 0;
        return 0;
    }
    g_active = 1;
    ingame_log("post: on, timing %s, the game drawn at %dx%d", g_gpu_timing ? "CPU and GPU (timestamps)"
                                                                           : "CPU (no GPU timestamps here)", g_src_w,
               g_src_h);
    return 1;
}

void post_before_reset(IDirect3DDevice9 *dev)
{
    if (!g_active)
        return;
    /* The device lets go of the proxy and our depth before they go (it holds what is set); after a reset that failed
     * they are gone already. */
    if (g_real_bb)
        real_set_render_target(dev, 0, g_real_bb);
    IDirect3DDevice9_SetDepthStencilSurface(dev, NULL);
    release_default();
    /* The game's own size until the chain is made again (post_after_reset: make_default picks the size anew): a reset
     * the chain does not follow (post_prepare refused it) leaves the game's targets at their own size. */
    render_set(0, 0);
    ingame_log("post: the game resets its device: the chain's objects released");
}

int post_after_reset(IDirect3DDevice9 *dev, HRESULT reset)
{
    if (!g_active)
        return 0;
    /* A reset that failed leaves the device lost: the game resets again, and the chain's objects come back then (until
     * then the getters answer with the real back buffer, and present shows nothing of ours). */
    if (FAILED(reset)) {
        ingame_log("post: the reset failed (0x%08lx): the chain waits for the next one", (unsigned long)reset);
        return 0;
    }
    if (!make_default(dev)) {
        ingame_log("post: the chain could not be made again after a reset: off");
        release_default();
        g_active = 0;
        return 0;
    }
    ingame_log("post: the chain's objects made again after the reset (%dx%d)", g_bb_w, g_bb_h);
    return 1;
}

/* ------------------------------------------------------------------------------------------------- the passes */

/* The device state every pass draws with (the state block puts the game's back after). */
static void pass_state(IDirect3DDevice9 *dev)
{
    static const D3DRENDERSTATETYPE off[] = {D3DRS_ZENABLE,          D3DRS_ZWRITEENABLE,   D3DRS_ALPHATESTENABLE,
                                             D3DRS_ALPHABLENDENABLE, D3DRS_STENCILENABLE,  D3DRS_SCISSORTESTENABLE,
                                             D3DRS_FOGENABLE,        D3DRS_SRGBWRITEENABLE, D3DRS_CLIPPLANEENABLE,
                                             D3DRS_SEPARATEALPHABLENDENABLE, D3DRS_TWOSIDEDSTENCILMODE};
    for (size_t i = 0; i < sizeof off / sizeof off[0]; i++)
        IDirect3DDevice9_SetRenderState(dev, off[i], FALSE);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_CULLMODE, D3DCULL_NONE);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_FILLMODE, D3DFILL_SOLID);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_COLORWRITEENABLE, 0xf);
    IDirect3DDevice9_SetVertexShader(dev, g_vs);
    IDirect3DDevice9_SetVertexDeclaration(dev, g_decl);
    /* No depth surface: ours is the game's size, smaller than the back buffer, and no pass tests depth. */
    IDirect3DDevice9_SetDepthStencilSurface(dev, NULL);
    /* The five samplers the passes read with (NIS's scaler has five inputs). */
    for (DWORD s = 0; s < 5; s++) {
        IDirect3DDevice9_SetSamplerState(dev, s, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
        IDirect3DDevice9_SetSamplerState(dev, s, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
        IDirect3DDevice9_SetSamplerState(dev, s, D3DSAMP_MIPFILTER, D3DTEXF_NONE);
        IDirect3DDevice9_SetSamplerState(dev, s, D3DSAMP_SRGBTEXTURE, FALSE);
        IDirect3DDevice9_SetSamplerState(dev, s, D3DSAMP_MAXMIPLEVEL, 0);
    }
}

/* Bind texture `t` to sampler `s`, filtered by point (0) or bilinear (1). */
static void bind(IDirect3DDevice9 *dev, DWORD s, IDirect3DTexture9 *t, int linear)
{
    IDirect3DDevice9_SetTexture(dev, s, (IDirect3DBaseTexture9 *)t);
    D3DTEXTUREFILTERTYPE f = linear ? D3DTEXF_LINEAR : D3DTEXF_POINT;
    IDirect3DDevice9_SetSamplerState(dev, s, D3DSAMP_MINFILTER, f);
    IDirect3DDevice9_SetSamplerState(dev, s, D3DSAMP_MAGFILTER, f);
}

/* SMAA's passes want their metrics (one texel, then the size) in c0 instead of the input's size: draw() writes these
 * when set. */
static const float *g_c0_override;

/* The one triangle over the whole viewport: from the card's buffer when there is one (stream 0 set each time: the
 * layer's DrawPrimitiveUP parts unset it), else from ours. */
static void full_triangle(IDirect3DDevice9 *dev)
{
    if (g_tri && SUCCEEDED(IDirect3DDevice9_SetStreamSource(dev, 0, g_tri, 0, 4 * sizeof(float))))
        IDirect3DDevice9_DrawPrimitive(dev, D3DPT_TRIANGLELIST, 0, 1);
    else
        IDirect3DDevice9_DrawPrimitiveUP(dev, D3DPT_TRIANGLELIST, 1, TRI, 4 * sizeof(float));
}

/* Draw one pass with pixel shader `ps` into `target`'s top-left w x h, the input's size in c0 and the output's in c1. */
static void draw(IDirect3DDevice9 *dev, IDirect3DPixelShader9 *ps, IDirect3DSurface9 *target, int w, int h, float in_w,
                 float in_h)
{
    real_set_render_target(dev, 0, target);
    /* The viewport after the target (setting a target resets it to the whole surface); into the window's back buffer,
     * at the picture's place (the passes there take its origin off their pixel's position: c8, set each frame). */
    D3DVIEWPORT9 vp = {0, 0, (DWORD)w, (DWORD)h, 0.0f, 1.0f};
    if (target == g_real_bb) {
        vp.X = (DWORD)g_pic.x;
        vp.Y = (DWORD)g_pic.y;
    }
    IDirect3DDevice9_SetViewport(dev, &vp);
    IDirect3DDevice9_SetPixelShader(dev, ps);
    float c[8] = {in_w, in_h, 1.0f / in_w, 1.0f / in_h, (float)w, (float)h, 1.0f / (float)w, 1.0f / (float)h};
    if (g_c0_override)
        memcpy(c, g_c0_override, 4 * sizeof(float));
    IDirect3DDevice9_SetPixelShaderConstantF(dev, 0, c, 2);
    full_triangle(dev);
    g_pass_count++;
}

/* The surface of a texture's only level (a reference the caller lets go of). */
static IDirect3DSurface9 *level0(IDirect3DTexture9 *t)
{
    IDirect3DSurface9 *s = NULL;
    IDirect3DTexture9_GetSurfaceLevel(t, 0, &s);
    return s;
}

/* Run anti-aliasing `aa` on `in` (the game's size); the texture holding the result. */
static IDirect3DTexture9 *run_aa(IDirect3DDevice9 *dev, int aa, IDirect3DTexture9 *in)
{
    int preset = aa_smaa_preset(aa);
    if (aa == AA_FXAA && g_ps[PASS_FXAA] && g_aa_out) {
        IDirect3DSurface9 *out = level0(g_aa_out);
        bind(dev, 0, in, 1);
        draw(dev, g_ps[PASS_FXAA], out, g_src_w, g_src_h, (float)g_src_w, (float)g_src_h);
        step(dev, "fxaa");
        DROP(out);
        return g_aa_out;
    }
    if (preset >= 0 && g_smaa_ps[preset][0] && g_smaa_edges && g_aa_out) {
        /* SMAA's metrics (one texel, the size) in c0 for its three passes. */
        float rt[4] = {1.0f / (float)g_src_w, 1.0f / (float)g_src_h, (float)g_src_w, (float)g_src_h};
        IDirect3DSurface9 *edges = level0(g_smaa_edges), *weights = level0(g_smaa_weights), *out = level0(g_aa_out);
        g_c0_override = rt;
        /* The edges: cleared first, since pixels with none are discarded; with the stencil, each pixel drawn (an edge)
         * marked 1 in it, the others left at the 0 it is cleared to. */
        real_set_render_target(dev, 0, edges);
        if (g_smaa_stencil) {
            IDirect3DDevice9_SetDepthStencilSurface(dev, g_smaa_stencil);
            IDirect3DDevice9_Clear(dev, 0, NULL, D3DCLEAR_TARGET | D3DCLEAR_STENCIL, 0, 1.0f, 0);
            IDirect3DDevice9_SetRenderState(dev, D3DRS_STENCILENABLE, TRUE);
            IDirect3DDevice9_SetRenderState(dev, D3DRS_STENCILFUNC, D3DCMP_ALWAYS);
            IDirect3DDevice9_SetRenderState(dev, D3DRS_STENCILPASS, D3DSTENCILOP_REPLACE);
            IDirect3DDevice9_SetRenderState(dev, D3DRS_STENCILFAIL, D3DSTENCILOP_KEEP);
            IDirect3DDevice9_SetRenderState(dev, D3DRS_STENCILZFAIL, D3DSTENCILOP_KEEP);
            IDirect3DDevice9_SetRenderState(dev, D3DRS_STENCILREF, 1);
            IDirect3DDevice9_SetRenderState(dev, D3DRS_STENCILMASK, 0xff);
            IDirect3DDevice9_SetRenderState(dev, D3DRS_STENCILWRITEMASK, 0xff);
        } else {
            IDirect3DDevice9_Clear(dev, 0, NULL, D3DCLEAR_TARGET, 0, 1.0f, 0);
        }
        /* The picture read with the point filter: the edge pass reads whole texels only (SMAASamplePoint, the pixel and
         * its neighbours), so the filter changes none of them, and the pass measured 8 to 17 % shorter than with the
         * linear one the blend pass needs. */
        bind(dev, 0, in, 0);
        draw(dev, g_smaa_ps[preset][0], edges, g_src_w, g_src_h, (float)g_src_w, (float)g_src_h);
        step(dev, "smaa edges");
        /* The weights, cleared the same way; with the stencil, worked out only where it says an edge is (the pass gives
         * the others 0, the cleared value, so the result is the same). */
        real_set_render_target(dev, 0, weights);
        IDirect3DDevice9_Clear(dev, 0, NULL, D3DCLEAR_TARGET, 0, 1.0f, 0);
        if (g_smaa_stencil) {
            IDirect3DDevice9_SetRenderState(dev, D3DRS_STENCILFUNC, D3DCMP_EQUAL);
            IDirect3DDevice9_SetRenderState(dev, D3DRS_STENCILPASS, D3DSTENCILOP_KEEP);
        }
        bind(dev, 1, g_smaa_edges, 1);
        bind(dev, 2, g_area, 1);
        bind(dev, 3, g_search, 0);
        draw(dev, g_smaa_ps[preset][1], weights, g_src_w, g_src_h, (float)g_src_w, (float)g_src_h);
        /* The stencil done with: no depth surface again, as for every other pass (pass_state). */
        if (g_smaa_stencil) {
            IDirect3DDevice9_SetRenderState(dev, D3DRS_STENCILENABLE, FALSE);
            IDirect3DDevice9_SetDepthStencilSurface(dev, NULL);
        }
        step(dev, "smaa weights");
        bind(dev, 0, in, 1);
        bind(dev, 1, g_smaa_weights, 1);
        draw(dev, g_smaa_ps[preset][2], out, g_src_w, g_src_h, (float)g_src_w, (float)g_src_h);
        step(dev, "smaa blend");
        g_c0_override = NULL;
        DROP(edges);
        DROP(weights);
        DROP(out);
        return g_aa_out;
    }
    return in;
}

/* Enlarge `in` (the game's frame as drawn, g_src_w x g_src_h) with filter `up` into the back buffer's top-left
 * w x h. */
static void run_upscale(IDirect3DDevice9 *dev, int up, IDirect3DTexture9 *in, int w, int h)
{
    /* The input's size, as floats for the passes' constants. */
    const float sw = (float)g_src_w, sh = (float)g_src_h;
    int plan[8], n = post_plan(up, AA_OFF, g_src_w, g_src_h, w, h, plan);
    int last = plan[n - 1];
    if (last == PASS_RCAS && g_ps[PASS_EASU_LEN] && g_ps[PASS_EASU] && g_ps[PASS_RCAS] && g_easu && g_easu_len) {
        /* EASU's lengths of every texel of the picture, once. */
        IDirect3DSurface9 *lens = level0(g_easu_len);
        bind(dev, 0, in, 0);
        draw(dev, g_ps[PASS_EASU_LEN], lens, g_src_w + 2, g_src_h + 2, sw, sh);
        step(dev, "easu len");
        DROP(lens);
        /* EASU into its texture at the output's size: con0 in c2, the lengths' texel size in c3.zw. */
        float con[16];
        easu_constants(sw, sh, (float)w, (float)h, con);
        float grid[4] = {sw + 2, sh + 2, 1.0f / (sw + 2), 1.0f / (sh + 2)};
        IDirect3DSurface9 *mid = level0(g_easu);
        bind(dev, 0, in, 0);
        bind(dev, 1, g_easu_len, 0);
        IDirect3DDevice9_SetPixelShaderConstantF(dev, 2, con, 1);
        IDirect3DDevice9_SetPixelShaderConstantF(dev, 3, grid, 1);
        draw(dev, g_ps[PASS_EASU], mid, w, h, sw, sh);
        step(dev, "easu");
        /* The lengths unbound: their pass draws into them next frame. */
        IDirect3DDevice9_SetTexture(dev, 1, NULL);
        DROP(mid);
        /* RCAS from it into the back buffer: its texel grid is the EASU texture's (c1 set to its size below). */
        /* RCAS from it into the back buffer: c2.x its constant, c3 the EASU texture's texel grid (the back buffer's
         * size, of which EASU filled the top-left w x h). */
        float k[8] = {rcas_constant(rcas_stops(g_sharpness)), 0, 0, 0,
                      (float)g_bb_w, (float)g_bb_h, 1.0f / (float)g_bb_w, 1.0f / (float)g_bb_h};
        bind(dev, 0, g_easu, 0);
        IDirect3DDevice9_SetPixelShaderConstantF(dev, 2, k, 2);
        draw(dev, g_ps[PASS_RCAS], g_real_bb, w, h, sw, sh);
        step(dev, "rcas");
        return;
    }
    if (last == PASS_NIS_SCALE && g_ps[PASS_NIS_EDGES] && g_ps[PASS_NIS_ROWS] && g_ps[PASS_NIS_SCALE] && g_nis_edges &&
        g_nis_rows && g_nis_coef) {
        NisConfig c;
        nis_config((float)g_sharpness / 100.0f, g_src_w, g_src_h, w, h, &c);
        float k[16] = {c.scale_x,        c.scale_y,           c.src_norm_x,         c.src_norm_y,
                       c.detect_ratio,   c.detect_thres,      c.min_contrast_ratio, c.ratio_norm,
                       c.contrast_boost, c.eps,               c.sharp_start_y,      c.sharp_scale_y,
                       c.sharp_strength_min, c.sharp_strength_scale, c.sharp_limit_min, c.sharp_limit_scale};
        /* The edge map at the game's size. */
        IDirect3DSurface9 *edges = level0(g_nis_edges);
        bind(dev, 0, in, 0);
        IDirect3DDevice9_SetPixelShaderConstantF(dev, 2, k, 4);
        draw(dev, g_ps[PASS_NIS_EDGES], edges, g_src_w, g_src_h, sw, sh);
        step(dev, "nis edges");
        DROP(edges);
        /* The scaler down each of the game's columns, for each of the window's rows. */
        IDirect3DSurface9 *rows = level0(g_nis_rows);
        bind(dev, 0, in, 0);
        bind(dev, 2, g_nis_coef, 0);
        draw(dev, g_ps[PASS_NIS_ROWS], rows, g_src_w, h, sw, sh);
        step(dev, "nis rows");
        DROP(rows);
        /* The scaler across them into the back buffer, with the directions' filters: c6.zw the sums' texel size. */
        float grid[4] = {sw, (float)g_bb_h, 1.0f / sw, 1.0f / (float)g_bb_h};
        bind(dev, 0, in, 0);
        bind(dev, 1, g_nis_edges, 0);
        bind(dev, 2, g_nis_coef, 0);
        bind(dev, 3, in, 1);
        bind(dev, 4, g_nis_rows, 0);
        IDirect3DDevice9_SetPixelShaderConstantF(dev, 6, grid, 1);
        draw(dev, g_ps[PASS_NIS_SCALE], g_real_bb, w, h, sw, sh);
        step(dev, "nis scale");
        /* The sums unbound: their pass draws into them next frame. */
        IDirect3DDevice9_SetTexture(dev, 4, NULL);
        return;
    }
    /* Off (sharp bilinear, its own pass) or bilinear (the copy pass), both reading with a linear filter. */
    int nearest = last == PASS_NEAREST && g_ps[PASS_NEAREST];
    bind(dev, 0, in, 1);
    draw(dev, g_ps[nearest ? PASS_NEAREST : PASS_BILINEAR], g_real_bb, w, h, sw, sh);
    step(dev, nearest ? "sharp bilinear" : "bilinear");
}

/* The whole chain for one choice: the game's frame copied out of the proxy, anti-aliased, enlarged. */
static void run_chain(IDirect3DDevice9 *dev, int up, int aa, int w, int h)
{
    IDirect3DTexture9 *in = g_src;
    if (aa == AA_FXAA || aa_smaa_preset(aa) >= 0)
        in = run_aa(dev, aa, in);
    run_upscale(dev, up, in, w, h);
}

/* -------------------------------------------------------------------------------------------- the in-game layer */

/* Each part's pictures as textures, and which version they hold. All of a part's textures are made when the layer
 * first draws at a size (make_parts), as large as the part gets there, filled and drawn once unseen, so no frame of the
 * game's play pays for making one: on WSL's D3D12 a part's first showing cost 0.3 to 1.2 ms for it (a chip's update
 * after it, 12 us), and up to 90 ms at the game's start. */
typedef struct {
    IDirect3DTexture9 *picture, *mask;
    int w, h;
    const Sprite *sprite;
    unsigned version, mask_version;
    /* The part composed once (its glass over the blurred frame at its place, the tint, its picture): drawn every frame
     * as this one texture, composed again when the blurred frame, the picture or the place changes (composed_ok goes
     * to 0 when part_textures fills the picture or the mask again). */
    IDirect3DTexture9 *composed;
    unsigned composed_gen;
    int composed_x, composed_y, composed_ok;
} PartTextures;
static PartTextures g_part_tex[LAYER_PARTS];
/* The target size every part's textures were made for (0: none made yet, or let go). */
static int g_parts_w, g_parts_h;
/* Whether the device takes only textures whose sides are powers of two (read from its caps once). */
static int g_pow2 = -1;
/* The Gaussian's weights for the glass: sigma 1.5 texels of the eighth-size frame (12 of the game's pixels), the
 * middle first then each distance out to 4, made once; and the fallback's state block (no chain: the parts drawn into
 * the game's own back buffer). */
static float g_blur_w[8];
static IDirect3DStateBlock9 *g_layer_state;
/* What the layer cost this frame on the CPU (counter ticks) and how many parts it drew, for the counter's line. */
static LONGLONG g_layer_ticks;
/* The parts drawn this frame, and how many of them were glass panels (not the chip): the safety net leaves frames
 * with a panel out of its judgement. */
static int g_layer_drawn, g_layer_panels;

/* The textures kept for a part's sprite: each sprite has its own slot for the run (the layer has as many sprites as
 * slots), so a part that comes or goes never makes another one's pictures go up again. */
static PartTextures *slot_for(const Sprite *s)
{
    for (int i = 0; i < LAYER_PARTS; i++)
        if (g_part_tex[i].sprite == s)
            return &g_part_tex[i];
    for (int i = 0; i < LAYER_PARTS; i++)
        if (!g_part_tex[i].sprite)
            return &g_part_tex[i];
    /* More sprites than slots (never, as the layer is): the first slot is taken over. */
    return &g_part_tex[0];
}

/* Every part's textures let go (before a reset: dynamic textures are in the default pool), so the next frame makes
 * and fills them again. */
static void drop_part_textures(void)
{
    for (int i = 0; i < LAYER_PARTS; i++) {
        DROP(g_part_tex[i].picture);
        DROP(g_part_tex[i].mask);
        DROP(g_part_tex[i].composed);
        g_part_tex[i].composed_ok = 0;
        g_part_tex[i].w = g_part_tex[i].h = 0;
        g_part_tex[i].sprite = NULL;
    }
    /* None made for any size now: the next frame the layer draws makes them all again. */
    g_parts_w = g_parts_h = 0;
}

/* The smallest power of two holding n. */
static int pow2_of(int n)
{
    int p = 1;
    while (p < n)
        p <<= 1;
    return p;
}

/* A canvas's pixels into a texture of at least its size (both 0xAARRGGBB, premultiplied: the canvas's layout is the
 * texture's A8R8G8B8 in memory), the rest of the texture cleared. */
/* Whether the parts' textures are dynamic (the device has them): written whole with a DISCARD lock, which hands over
 * fresh memory and never waits for the GPU or reads back what it holds. Measured against it under Wine: a managed
 * texture's lock, 2 ms a chip update on the software renderer; a twin in system memory written only where the picture
 * changed and handed over by UpdateTexture, 2.8 ms there against 8 us (the card's texture is in a frame still being
 * drawn, and the copy waits for it). So a changed picture goes up whole (the chip's is 30 KB at 1080 lines), and only
 * the picture that changed: a part's mask has its own version. -1 not asked yet. */
static int g_dynamic = -1;

static int fill(IDirect3DTexture9 *t, const Canvas *c, int tw, int th)
{
    D3DLOCKED_RECT lr;
    if (FAILED(IDirect3DTexture9_LockRect(t, 0, &lr, NULL, g_dynamic > 0 ? D3DLOCK_DISCARD : 0)))
        return 0;
    for (int y = 0; y < th; y++) {
        BYTE *row = (BYTE *)lr.pBits + (size_t)y * (size_t)lr.Pitch;
        int have = y < c->h ? (c->w < tw ? c->w : tw) : 0;
        if (have)
            memcpy(row, c->px + (size_t)y * (size_t)c->w, (size_t)have * 4);
        memset(row + (size_t)have * 4, 0, (size_t)(tw - have) * 4);
    }
    IDirect3DTexture9_UnlockRect(t, 0);
    return 1;
}

/* A part's textures made, at least w x h: its picture and its mask and, for a part with glass of its own (`glass`),
 * the texture it is composed into (compose_part). 1 when the first two were made. */
static int make_part(IDirect3DDevice9 *dev, PartTextures *t, int w, int h, int glass)
{
    if (g_pow2 < 0 || g_dynamic < 0) {
        /* A device that wants powers of two (and allows no other, even conditionally) gets them; one with dynamic
         * textures gets those. */
        D3DCAPS9 caps;
        int got = SUCCEEDED(IDirect3DDevice9_GetDeviceCaps(dev, &caps));
        g_pow2 = got && (caps.TextureCaps & D3DPTEXTURECAPS_POW2) && !(caps.TextureCaps & D3DPTEXTURECAPS_NONPOW2CONDITIONAL);
        g_dynamic = got && (caps.Caps2 & D3DCAPS2_DYNAMICTEXTURES) ? 1 : 0;
    }
    DROP(t->picture);
    DROP(t->mask);
    /* The composed texture is the pictures' size: made again with them. */
    DROP(t->composed);
    t->composed_ok = 0;
    int tw = g_pow2 ? pow2_of(w) : w, th = g_pow2 ? pow2_of(h) : h;
    const D3DFORMAT f = D3DFMT_A8R8G8B8;
    /* Dynamic ones live in the default pool (let go before a reset, made again after: drop_part_textures). */
    DWORD usage = g_dynamic > 0 ? D3DUSAGE_DYNAMIC : 0;
    D3DPOOL pool = g_dynamic > 0 ? D3DPOOL_DEFAULT : D3DPOOL_MANAGED;
    if (FAILED(IDirect3DDevice9_CreateTexture(dev, (UINT)tw, (UINT)th, 1, usage, f, pool, &t->picture, NULL)) ||
        FAILED(IDirect3DDevice9_CreateTexture(dev, (UINT)tw, (UINT)th, 1, usage, f, pool, &t->mask, NULL))) {
        ingame_log("layer: a part's textures (%dx%d) were not made", tw, th);
        DROP(t->picture);
        DROP(t->mask);
        t->w = t->h = 0;
        return 0;
    }
    /* The composed texture: a target of the same size; without it the glass is read every frame (ps_ui_glass). */
    if (glass && g_ps[PASS_UI_COMPOSE] &&
        FAILED(IDirect3DDevice9_CreateTexture(dev, (UINT)tw, (UINT)th, 1, D3DUSAGE_RENDERTARGET, f, D3DPOOL_DEFAULT,
                                              &t->composed, NULL)))
        t->composed = NULL;
    t->w = tw;
    t->h = th;
    return 1;
}

/* A part's textures for its pictures as they are now: a picture uploaded again when its version changed. The textures
 * are there already, as large as the part gets (make_parts); a part grown past them (words nobody knew when they were
 * made: a measuring toast's) gets larger ones here, and the log says so. */
static int part_textures(IDirect3DDevice9 *dev, PartTextures *t, const LayerPart *part)
{
    const Sprite *s = part->sprite;
    if (!s || !s->content || !s->mask)
        return 0;
    int w = s->content->w, h = s->content->h;
    /* The mask's version: its own when the part has one, else the picture's. */
    unsigned mv = part->mask_version ? part->mask_version : part->version;
    if (t->picture && t->sprite == s && t->version == part->version && t->mask_version == mv && t->w >= w && t->h >= h)
        return 1;
    int fresh = 0;
    if (!t->picture || t->w < w || t->h < h) {
        int kind = part->kind;
        ingame_log("layer: a part's textures made while the game plays (kind %d, %dx%d, had %dx%d)", kind, w, h, t->w,
                   t->h);
        if (!make_part(dev, t, w, h, kind != PART_MARK && kind != PART_BAR_CHIPS))
            return 0;
        fresh = 1;
    }
    /* Each texture filled only when its own picture changed (or the textures or the sprite are new). */
    int same = !fresh && t->sprite == s;
    /* Either filled again: the part composed from them is stale. */
    t->composed_ok = 0;
    if (!(same && t->version == part->version) && !fill(t->picture, s->content, t->w, t->h))
        return 0;
    if (!(same && t->mask_version == mv) && !fill(t->mask, s->mask, t->w, t->h))
        return 0;
    t->sprite = s;
    t->version = part->version;
    t->mask_version = mv;
    return 1;
}

/* Every part's textures made for a target of w x h, each as large as the part gets there, and filled with its picture
 * as it is now (`parts`: layer_warm_parts' list). The layer's first frame at a size does this (at the game's loading,
 * after a change of the window's size or a reset) and draws each part once unseen, so the card has every texture made
 * and filled before a part shows. */
static void make_parts(IDirect3DDevice9 *dev, const LayerPart *parts, int n, int w, int h)
{
    LARGE_INTEGER t0, t1, f;
    QueryPerformanceCounter(&t0);
    /* Those of another size go first. */
    drop_part_textures();
    int made = 0;
    for (int i = 0; i < n; i++) {
        const Sprite *s = parts[i].sprite;
        if (!s || !s->content || !s->mask)
            continue;
        PartTextures *t = slot_for(s);
        /* The slot is this sprite's from now on (slot_for looks for it by its sprite). */
        t->sprite = s;
        int rw = parts[i].room_w > s->content->w ? parts[i].room_w : s->content->w;
        int rh = parts[i].room_h > s->content->h ? parts[i].room_h : s->content->h;
        int kind = parts[i].kind;
        if (!make_part(dev, t, rw, rh, kind != PART_MARK && kind != PART_BAR_CHIPS) ||
            !fill(t->picture, s->content, t->w, t->h) || !fill(t->mask, s->mask, t->w, t->h)) {
            /* Not made: part_textures tries again when the part shows. */
            t->version = ~parts[i].version;
            continue;
        }
        t->version = parts[i].version;
        t->mask_version = parts[i].mask_version ? parts[i].mask_version : parts[i].version;
        made++;
    }
    g_parts_w = w;
    g_parts_h = h;
    QueryPerformanceCounter(&t1);
    QueryPerformanceFrequency(&f);
    ingame_log("layer: %d parts' textures made for %dx%d in %.1f ms", made, w, h,
               (double)(t1.QuadPart - t0.QuadPart) * 1000.0 / (double)f.QuadPart);
}

/* A part's quad in the target's clip space for the glass pass: its sprite's pixels exactly (Direct3D 9 samples a
 * pixel at its integer corner, so the edges go half a pixel up and left of the pixel lines). */
static void draw_part_quad(IDirect3DDevice9 *dev, const LayerPart *part, int w, int h)
{
    float x0 = ((float)part->x - 0.5f) / (float)w * 2.0f - 1.0f;
    float x1 = ((float)(part->x + part->sprite->content->w) - 0.5f) / (float)w * 2.0f - 1.0f;
    float y0 = 1.0f - ((float)part->y - 0.5f) / (float)h * 2.0f;
    float y1 = 1.0f - ((float)(part->y + part->sprite->content->h) - 0.5f) / (float)h * 2.0f;
    float quad[16] = {x0, y0, 0, 1, x1, y0, 0, 1, x0, y1, 0, 1, x1, y1, 0, 1};
    IDirect3DDevice9_DrawPrimitiveUP(dev, D3DPT_TRIANGLESTRIP, 2, quad, 4 * sizeof(float));
}

/* A part drawn with no shader of ours (the glass passes did not compile, or the chain does not run): where the glass
 * would be, the tint opaque (no blur: the game's own panels are opaque too); its picture over it. */
static void draw_part_fixed(IDirect3DDevice9 *dev, const PartTextures *t, const LayerPart *part)
{
    struct {
        float x, y, z, rhw, u, v;
    } q[4];
    /* At the part's place in the picture, which starts at g_pic's origin in the window (pre-transformed positions are
     * the target's own pixels, not the viewport's). */
    float x0 = (float)(part->x + g_pic.x) - 0.5f, y0 = (float)(part->y + g_pic.y) - 0.5f;
    float x1 = x0 + (float)part->sprite->content->w, y1 = y0 + (float)part->sprite->content->h;
    float u1 = (float)part->sprite->content->w / (float)t->w, v1 = (float)part->sprite->content->h / (float)t->h;
    q[0].x = x0, q[0].y = y0, q[0].u = 0, q[0].v = 0;
    q[1].x = x1, q[1].y = y0, q[1].u = u1, q[1].v = 0;
    q[2].x = x0, q[2].y = y1, q[2].u = 0, q[2].v = v1;
    q[3].x = x1, q[3].y = y1, q[3].u = u1, q[3].v = v1;
    for (int i = 0; i < 4; i++)
        q[i].z = 0, q[i].rhw = 1;
    IDirect3DDevice9_SetVertexShader(dev, NULL);
    IDirect3DDevice9_SetPixelShader(dev, NULL);
    IDirect3DDevice9_SetFVF(dev, D3DFVF_XYZRHW | D3DFVF_TEX1);
    IDirect3DDevice9_SetSamplerState(dev, 0, D3DSAMP_MINFILTER, D3DTEXF_POINT);
    IDirect3DDevice9_SetSamplerState(dev, 0, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
    IDirect3DDevice9_SetTextureStageState(dev, 1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_TEXCOORDINDEX, 0);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_TEXTURETRANSFORMFLAGS, D3DTTFF_DISABLE);
    BYTE a = (BYTE)(part->alpha * 255.0f + 0.5f);
    /* The glass's place: the tint's colour, at the mask's opacity times the part's. */
    IDirect3DDevice9_SetTexture(dev, 0, (IDirect3DBaseTexture9 *)t->mask);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_COLORARG1, D3DTA_TFACTOR);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_ALPHAOP, D3DTOP_MODULATE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_ALPHAARG2, D3DTA_TFACTOR);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_TEXTUREFACTOR, D3DCOLOR_ARGB(a, (GLASS_TINT >> 16) & 0xff,
                                                                          (GLASS_TINT >> 8) & 0xff, GLASS_TINT & 0xff));
    IDirect3DDevice9_DrawPrimitiveUP(dev, D3DPT_TRIANGLESTRIP, 2, q, sizeof q[0]);
    /* The picture over it, premultiplied: its colour and opacity both times the part's opacity. */
    IDirect3DDevice9_SetTexture(dev, 0, (IDirect3DBaseTexture9 *)t->picture);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_COLORARG2, D3DTA_TFACTOR);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_SRCBLEND, D3DBLEND_ONE);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_TEXTUREFACTOR, D3DCOLOR_ARGB(a, a, a, a));
    IDirect3DDevice9_DrawPrimitiveUP(dev, D3DPT_TRIANGLESTRIP, 2, q, sizeof q[0]);
}

/* The part composed into its own texture when it is not yet, or the blurred frame, its picture or its place changed
 * since (the blurred frame changes every 300 ms while a panel shows; the picture on a hover, new words, the chip's
 * numbers): its glass over the blurred frame at its place in the output (w x h), the tint, its picture over them. The
 * output's target and viewport are put back after. 1 when the composed texture is ready to draw. */
static int compose_part(IDirect3DDevice9 *dev, PartTextures *t, const LayerPart *part, IDirect3DSurface9 *target,
                        int w, int h)
{
    /* Without its shader or a target to come back to: the glass read every frame instead (ps_ui_glass). */
    if (!g_ps[PASS_UI_COMPOSE] || !target)
        return 0;
    /* Its texture, the size of the part's pictures, was made with them (make_part: a target in the default pool, let
     * go before a reset with them); none made, the glass is read every frame instead. */
    if (!t->composed)
        return 0;
    /* Composed already over this blurred frame, from these pictures, at this place: drawn as it is. */
    if (t->composed_ok && t->composed_gen == g_blur_gen && t->composed_x == part->x && t->composed_y == part->y)
        return 1;
    IDirect3DSurface9 *dst = level0(t->composed);
    if (!dst)
        return 0;
    /* Into the part's texture, the whole of it (the chain's own setter: the game's is turned to the proxy). */
    real_set_render_target(dev, 0, dst);
    D3DVIEWPORT9 vp = {0, 0, (DWORD)t->w, (DWORD)t->h, 0.0f, 1.0f};
    IDirect3DDevice9_SetViewport(dev, &vp);
    /* Written as it is (no blending): the composed picture, premultiplied. */
    IDirect3DDevice9_SetRenderState(dev, D3DRS_ALPHABLENDENABLE, FALSE);
    /* The chain's full-screen triangle and the composing shader. */
    IDirect3DDevice9_SetVertexShader(dev, g_vs);
    IDirect3DDevice9_SetVertexDeclaration(dev, g_decl);
    IDirect3DDevice9_SetPixelShader(dev, g_ps[PASS_UI_COMPOSE]);
    /* The picture and the mask at their texels (point), the finished blurred frame shown now smoothed (bilinear). */
    bind(dev, 0, t->picture, 0);
    bind(dev, 1, t->mask, 0);
    bind(dev, 2, g_blur[g_blur_shown], 1);
    /* c1 the output's size (where the blurred frame is read); c2 the part's place and its textures' texel; c3.y the
     * tint's opacity; c4 the tint. */
    float c[16] = {(float)GAME_W, (float)GAME_H, 1.0f / GAME_W, 1.0f / GAME_H,
                   (float)w, (float)h, 1.0f / (float)w, 1.0f / (float)h,
                   (float)part->x, (float)part->y, 1.0f / (float)t->w, 1.0f / (float)t->h,
                   1.0f, GLASS_TINT_ALPHA, 0, 0};
    float tint[4] = {(float)((GLASS_TINT >> 16) & 0xff) / 255.0f, (float)((GLASS_TINT >> 8) & 0xff) / 255.0f,
                     (float)(GLASS_TINT & 0xff) / 255.0f, 1.0f};
    IDirect3DDevice9_SetPixelShaderConstantF(dev, 0, c, 4);
    IDirect3DDevice9_SetPixelShaderConstantF(dev, 4, tint, 1);
    /* One triangle over the whole texture. */
    full_triangle(dev);
    DROP(dst);
    /* The output back, blending as the parts blend. */
    real_set_render_target(dev, 0, target);
    D3DVIEWPORT9 out = {(DWORD)g_pic.x, (DWORD)g_pic.y, (DWORD)w, (DWORD)h, 0.0f, 1.0f};
    IDirect3DDevice9_SetViewport(dev, &out);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_ALPHABLENDENABLE, TRUE);
    /* What it was composed from, so the frames after draw it as it is until one of them changes. */
    t->composed_ok = 1;
    t->composed_gen = g_blur_gen;
    t->composed_x = part->x;
    t->composed_y = part->y;
    /* Counted for the log's line (layer cost compose). */
    g_costs.composed++;
    return 1;
}

/* A part's texture `tex` alone over the game, premultiplied, at the part's opacity, with the fixed function: the picture
 * of a part with no glass (the mark, the bar's chips), or a glass part composed into its own texture (compose_part).
 * The blurred frame is not read here: on Wine's software renderer a draw that reads it after a live blur cost about
 * 1 ms a frame (measured with OPENDMT3_LAYER_TIMING=frame), the fixed function's picture a tenth of that. */
static void draw_part_texture(IDirect3DDevice9 *dev, IDirect3DTexture9 *tex, const PartTextures *t,
                              const LayerPart *part)
{
    struct {
        float x, y, z, rhw, u, v;
    } q[4];
    /* At the part's place in the picture, which starts at g_pic's origin in the window (pre-transformed positions are
     * the target's own pixels, not the viewport's). */
    float x0 = (float)(part->x + g_pic.x) - 0.5f, y0 = (float)(part->y + g_pic.y) - 0.5f;
    float x1 = x0 + (float)part->sprite->content->w, y1 = y0 + (float)part->sprite->content->h;
    float u1 = (float)part->sprite->content->w / (float)t->w, v1 = (float)part->sprite->content->h / (float)t->h;
    q[0].x = x0, q[0].y = y0, q[0].u = 0, q[0].v = 0;
    q[1].x = x1, q[1].y = y0, q[1].u = u1, q[1].v = 0;
    q[2].x = x0, q[2].y = y1, q[2].u = 0, q[2].v = v1;
    q[3].x = x1, q[3].y = y1, q[3].u = u1, q[3].v = v1;
    for (int i = 0; i < 4; i++)
        q[i].z = 0, q[i].rhw = 1;
    IDirect3DDevice9_SetVertexShader(dev, NULL);
    IDirect3DDevice9_SetPixelShader(dev, NULL);
    IDirect3DDevice9_SetFVF(dev, D3DFVF_XYZRHW | D3DFVF_TEX1);
    IDirect3DDevice9_SetSamplerState(dev, 0, D3DSAMP_MINFILTER, D3DTEXF_POINT);
    IDirect3DDevice9_SetSamplerState(dev, 0, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
    IDirect3DDevice9_SetTextureStageState(dev, 1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_TEXCOORDINDEX, 0);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_TEXTURETRANSFORMFLAGS, D3DTTFF_DISABLE);
    /* The texture, premultiplied: its colour and opacity both times the part's opacity (the blend is ONE, INVSRCALPHA,
     * as for every part). */
    BYTE a = (BYTE)(part->alpha * 255.0f + 0.5f);
    IDirect3DDevice9_SetTexture(dev, 0, (IDirect3DBaseTexture9 *)tex);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_COLORARG2, D3DTA_TFACTOR);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_ALPHAOP, D3DTOP_MODULATE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_ALPHAARG2, D3DTA_TFACTOR);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_SRCBLEND, D3DBLEND_ONE);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_TEXTUREFACTOR, D3DCOLOR_ARGB(a, a, a, a));
    IDirect3DDevice9_DrawPrimitiveUP(dev, D3DPT_TRIANGLESTRIP, 2, q, sizeof q[0]);
}

/* The layer's parts for this frame (its motion worked out, its pictures drawn again where they changed), the CPU
 * time this takes counted as the layer's. The first frame at a size (the game's loading, a change of the window, a
 * reset), every part's textures are made and filled (make_parts) and `ready` gets every picture at an opacity too
 * small to change a pixel (a ten thousandth), for the caller to draw once: the shaders' and textures' first use (a
 * renderer compiles and makes its own then) is that frame's, never the first time a part shows. How many parts show;
 * *nready how many to draw unseen first (0 in every other frame). */
static int layer_prepare(IDirect3DDevice9 *dev, int w, int h, LayerPart *parts, LayerPart *ready, int *nready)
{
    LARGE_INTEGER t0, t1;
    QueryPerformanceCounter(&t0);
    int n = layer_parts(parts, LAYER_PARTS, w, h);
    *nready = 0;
    if (w != g_parts_w || h != g_parts_h) {
        *nready = layer_warm_parts(ready, LAYER_PARTS, w, h);
        /* No pictures yet (the layer has no window to draw for): asked again at the next frame. */
        if (*nready > 0) {
            make_parts(dev, ready, *nready, w, h);
            ingame_log("layer: drawn once unseen (%d parts) to make its passes ready", *nready);
        }
    }
    QueryPerformanceCounter(&t1);
    g_layer_ticks = t1.QuadPart - t0.QuadPart;
    g_layer_drawn = g_layer_panels = 0;
    return n;
}

/* Whether the glass's passes and targets are there. */
static int glass_ready(void)
{
    return g_ps[PASS_UI_DOWN] && g_ps[PASS_UI_BLUR] && g_ps[PASS_UI_GLASS] && g_blur[0] && g_blur[1] && g_blur[2] &&
           g_blur[3];
}

/* Measuring alone (OPENDMT3_LAYER_TIMING=sync): everything sent so far done on the device, then the CPU's clock now
 * (at most a fifth of a second waited). */
static LONGLONG idle_now(IDirect3DDevice9 *dev)
{
    (void)dev;
    LARGE_INTEGER t, f, limit;
    QueryPerformanceFrequency(&f);
    QueryPerformanceCounter(&limit);
    limit.QuadPart += f.QuadPart / 5;
    IDirect3DQuery9_Issue(g_q_idle, D3DISSUE_END);
    do {
        QueryPerformanceCounter(&t);
    } while (IDirect3DQuery9_GetData(g_q_idle, NULL, 0, D3DGETDATA_FLUSH) == S_FALSE && t.QuadPart < limit.QuadPart);
    QueryPerformanceCounter(&t);
    return t.QuadPart;
}

/* Microseconds between two of the CPU clock's readings. */
static double ticks_us(LONGLONG a, LONGLONG b)
{
    LARGE_INTEGER f;
    QueryPerformanceFrequency(&f);
    return (double)(b - a) * 1e6 / (double)f.QuadPart;
}

/* One pass of the glass's blurred frame: 0 the game's frame `src` averaged to an eighth, 1 that blurred across, 2 the
 * across blurred down into the finished texture not shown. */
static void blur_pass(IDirect3DDevice9 *dev, IDirect3DTexture9 *src, int stage)
{
    if (!g_blur_w[0]) {
        /* The Gaussian's weights, summing to one over the 9 reads (the middle once, each distance twice). */
        float sum = 0;
        for (int i = 0; i <= 4; i++)
            sum += (i ? 2.0f : 1.0f) * (g_blur_w[i] = expf(-(float)(i * i) / (2.0f * 1.5f * 1.5f)));
        for (int i = 0; i <= 4; i++)
            g_blur_w[i] /= sum;
    }
    float x[4] = {1, 0, 0, 0}, y[4] = {0, 1, 0, 0};
    if (stage == 0) {
        IDirect3DSurface9 *down = level0(g_blur[0]);
        bind(dev, 0, src, 1);
        draw(dev, g_ps[PASS_UI_DOWN], down, BLUR_W, BLUR_H, GAME_W, GAME_H);
        DROP(down);
    } else {
        /* Across from the average (stage 1), or down from the across into the finished one not shown (stage 2). */
        IDirect3DSurface9 *out = level0(stage == 1 ? g_blur[1] : g_blur[g_blur_shown == 2 ? 3 : 2]);
        IDirect3DDevice9_SetPixelShaderConstantF(dev, 3, g_blur_w, 2);
        IDirect3DDevice9_SetPixelShaderConstantF(dev, 2, stage == 1 ? x : y, 1);
        bind(dev, 0, g_blur[stage == 1 ? 0 : 1], 0);
        draw(dev, g_ps[PASS_UI_BLUR], out, BLUR_W, BLUR_H, BLUR_W, BLUR_H);
        DROP(out);
    }
}

/* The glass's blurred frame (before the chain's upscale, so the parts after it go straight into the same target): the
 * next of its three passes, the finished one shown from its last on (`all`: the three in this one frame: a panel that
 * comes, the chip's first still glass, the frame the game is held still on). The passes timed on the GPU with the
 * diagnostic switch. */
static void layer_blur(IDirect3DDevice9 *dev, IDirect3DTexture9 *src, int all)
{
    int stage = all ? 0 : g_blur_stage;
    if (!all)
        g_blur_stage = (g_blur_stage + 1) % 3;
    LARGE_INTEGER t0, t1;
    QueryPerformanceCounter(&t0);
    if (g_layer_timing == 1 && g_q_blur0[g_q_next])
        IDirect3DQuery9_Issue(g_q_blur0[g_q_next], D3DISSUE_END);
    LONGLONG alone = g_layer_timing == 2 ? idle_now(dev) : 0;
    /* Measuring alone: every other frame the pass made nine times over (each pass writes the same texture from the same
     * one, so the result is the same); what nine cost against one is one pass's own work. */
    int times = alone && (g_sync_frames & 1) ? 9 : 1;
    /* The passes a frame makes (the measuring repeats left out). */
    g_costs.blur_passes += all ? 3 : 1;
    if (all) {
        /* The three in a row, the finished one shown at once; the live cycle starts again from its first pass. */
        for (int k = 0; k < times; k++) {
            blur_pass(dev, src, 0);
            blur_pass(dev, src, 1);
            blur_pass(dev, src, 2);
        }
        g_blur_shown = g_blur_shown == 2 ? 3 : 2;
        g_blur_gen++;
        g_blur_stage = 0;
        g_blur_made = 1;
    } else {
        for (int k = 0; k < times; k++)
            blur_pass(dev, src, stage);
        /* The last of the three: the finished one is shown from this frame's parts on (they come after it). */
        if (stage == 2) {
            g_blur_shown = g_blur_shown == 2 ? 3 : 2;
            g_blur_gen++;
            g_blur_made = 1;
        }
    }
    if (g_layer_timing == 2 && times == 9) {
        g_costs.blur_gpu9_us += ticks_us(alone, idle_now(dev));
        g_costs.blur_gpu9_n++;
    } else if (g_layer_timing == 2) {
        g_costs.blur_gpu_us += ticks_us(alone, idle_now(dev));
        g_costs.blur_gpu_n++;
    }
    if (g_layer_timing == 1 && g_q_blur1[g_q_next]) {
        IDirect3DQuery9_Issue(g_q_blur1[g_q_next], D3DISSUE_END);
        g_q_blur_issued[g_q_next] = 1;
    }
    step(dev, "blur");
    QueryPerformanceCounter(&t1);
    g_layer_ticks += t1.QuadPart - t0.QuadPart;
}

/* The layer's parts over the picture in `target` (w x h): over the blurred frame's glass when `glass`, the
 * fixed-function look otherwise. The caller saved the game's state and puts it back. */
static void layer_draw_parts(IDirect3DDevice9 *dev, const LayerPart *parts, int n, IDirect3DSurface9 *target, int w,
                             int h, int glass, int unseen)
{
    LARGE_INTEGER t0, t1;
    QueryPerformanceCounter(&t0);
    /* With the diagnostic switch: the parts' start timed on the GPU, then each part's end (the chain's frames only;
     * never the unseen draws of the frame the textures are made in, which are no part's cost as it shows). */
    int timed = !unseen && g_active && g_layer_timing == 1 && g_q_parts[g_q_next][0];
    if (!unseen)
        g_sync_frames++;
    if (!unseen && g_active && g_layer_timing == 2 && n > 0) {
        /* Measuring alone: the idle device's own round, with nothing sent between (what each part's measure also pays). */
        LONGLONG i0 = idle_now(dev);
        g_costs.idle_us += ticks_us(i0, idle_now(dev));
        g_costs.idle_n++;
    }
    if (timed)
        IDirect3DQuery9_Issue(g_q_parts[g_q_next][0], D3DISSUE_END);
    if (!unseen)
        g_q_parts_n[g_q_next] = 0;
    /* The target through the chain's own setter while it runs (the game's is turned to the proxy), the device's own
     * otherwise. */
    /* Without the chain: the game's own back buffer as the target, its whole size as the viewport. With it, the chain's
     * last pass has just drawn into the same back buffer at the same size (run_chain ends there in every upscale): set
     * again, they would only be one more change for the device to look at. */
    if (!g_active) {
        IDirect3DDevice9_SetRenderTarget(dev, 0, target);
        D3DVIEWPORT9 vp = {0, 0, (DWORD)w, (DWORD)h, 0.0f, 1.0f};
        IDirect3DDevice9_SetViewport(dev, &vp);
    }
    /* The parts' pictures are premultiplied: blended as such. */
    IDirect3DDevice9_SetRenderState(dev, D3DRS_ALPHABLENDENABLE, TRUE);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_BLENDOP, D3DBLENDOP_ADD);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_SRCBLEND, D3DBLEND_ONE);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    for (int i = 0; i < n; i++) {
        PartTextures *t = slot_for(parts[i].sprite);
        int kind = parts[i].kind >= 0 && parts[i].kind < PART_KINDS ? parts[i].kind : PART_PANEL;
        LARGE_INTEGER p0, p1, p2;
        QueryPerformanceCounter(&p0);
        /* Its pictures uploaded again only when drawn again since the last frame (counted as the kind's uploads). */
        unsigned had = t->sprite == parts[i].sprite ? t->version : ~parts[i].version;
        if (parts[i].alpha <= 0.0f || !part_textures(dev, t, &parts[i]))
            continue;
        QueryPerformanceCounter(&p1);
        if (had != parts[i].version && !unseen) {
            g_costs.uploads[kind]++;
            g_costs.upload_ticks[kind] += p1.QuadPart - p0.QuadPart;
        }
        /* Measuring alone: what came before done first, then this part's draw alone (every other frame nine times over:
         * eight more copies at an opacity too small to change a pixel). */
        LONGLONG alone = !unseen && g_active && g_layer_timing == 2 ? idle_now(dev) : 0;
        /* The mark and the bar's chips have no glass of their own (the chips lie on the bar's): their pictures alone,
         * the blurred frame not read. */
        int bare = kind == PART_MARK || kind == PART_BAR_CHIPS;
        /* A glass part: composed once into its own texture (again only when the blurred frame, its picture or its
         * place changes) and drawn as that texture; reading the blurred frame in every frame cost Wine's software
         * renderer about 1 ms a part. */
        int composed = !bare && glass && compose_part(dev, t, &parts[i], target, w, h);
        int copies = alone && glass && !bare && (g_sync_frames & 1) ? 8 : 0;
        if (bare) {
            draw_part_texture(dev, t->picture, t, &parts[i]);
        } else if (composed) {
            draw_part_texture(dev, t->composed, t, &parts[i]);
            /* The measuring copies: the same texture at a ten thousandth of the opacity (no pixel changes). */
            LayerPart faint = parts[i];
            faint.alpha = 0.0001f;
            for (int k = 0; k < copies; k++)
                draw_part_texture(dev, t->composed, t, &faint);
        } else if (glass) {
            IDirect3DDevice9_SetVertexShader(dev, g_vs);
            IDirect3DDevice9_SetVertexDeclaration(dev, g_decl);
            IDirect3DDevice9_SetPixelShader(dev, g_ps[PASS_UI_GLASS]);
            bind(dev, 0, t->picture, 0);
            bind(dev, 1, t->mask, 0);
            /* The finished blurred frame shown now (never the one a pass of this frame writes). */
            bind(dev, 2, g_blur[g_blur_shown], 1);
            /* c1 the output's size; c2 the part's top left and its textures' texel; c3 its opacity and the tint's;
             * c4 the tint. */
            float c[16] = {(float)GAME_W, (float)GAME_H, 1.0f / GAME_W, 1.0f / GAME_H,
                           (float)w, (float)h, 1.0f / (float)w, 1.0f / (float)h,
                           (float)parts[i].x, (float)parts[i].y, 1.0f / (float)t->w, 1.0f / (float)t->h,
                           parts[i].alpha, GLASS_TINT_ALPHA, 0, 0};
            float tint[4] = {(float)((GLASS_TINT >> 16) & 0xff) / 255.0f, (float)((GLASS_TINT >> 8) & 0xff) / 255.0f,
                             (float)(GLASS_TINT & 0xff) / 255.0f, 1.0f};
            IDirect3DDevice9_SetPixelShaderConstantF(dev, 0, c, 4);
            IDirect3DDevice9_SetPixelShaderConstantF(dev, 4, tint, 1);
            draw_part_quad(dev, &parts[i], w, h);
            if (copies) {
                /* The measuring copies: the same quad and textures, a ten thousandth of the opacity. */
                c[12] = 0.0001f;
                IDirect3DDevice9_SetPixelShaderConstantF(dev, 0, c, 4);
                for (int k = 0; k < copies; k++)
                    draw_part_quad(dev, &parts[i], w, h);
            }
        } else {
            draw_part_fixed(dev, t, &parts[i]);
        }
        if (alone && copies) {
            g_costs.gpu9_us[kind] += ticks_us(alone, idle_now(dev));
            g_costs.gpu9_n[kind]++;
        } else if (alone) {
            g_costs.gpu_us[kind] += ticks_us(alone, idle_now(dev));
            g_costs.gpu_n[kind]++;
        }
        /* Its end on the GPU (the diagnostic switch), and its CPU time: the upload (if any) and the draw's calls. */
        if (timed && g_q_parts_n[g_q_next] < LAYER_PARTS) {
            int k = g_q_parts_n[g_q_next]++;
            IDirect3DQuery9_Issue(g_q_parts[g_q_next][k + 1], D3DISSUE_END);
            g_q_parts_kind[g_q_next][k] = kind;
        }
        /* An unseen draw: composed from whatever the glass held, so composed again when the part shows; not a part
         * drawn, for the costs or the safety net. */
        if (unseen) {
            t->composed_ok = 0;
            continue;
        }
        QueryPerformanceCounter(&p2);
        g_costs.frames[kind]++;
        g_costs.cpu[kind] += p2.QuadPart - p0.QuadPart;
        g_layer_drawn++;
        if (PART_IS_PANEL(kind))
            g_layer_panels++;
        g_pass_count++;
    }
    IDirect3DDevice9_SetRenderState(dev, D3DRS_ALPHABLENDENABLE, FALSE);
    QueryPerformanceCounter(&t1);
    g_layer_ticks += t1.QuadPart - t0.QuadPart;
}

void post_layer_without_chain(IDirect3DDevice9 *dev)
{
    /* Only for a device the chain does not run on, and one that can draw. */
    if (g_active || IDirect3DDevice9_TestCooperativeLevel(dev) != D3D_OK)
        return;
    /* No chain: Direct3D's own stretch fills the client with the game's back buffer, where the parts go at its top
     * left (no origin), and no place of the picture's is known to the pointer (post_picture: 0 x 0). */
    g_pic.x = g_pic.y = g_pic.w = g_pic.h = 0;
    IDirect3DSurface9 *bb = NULL;
    D3DSURFACE_DESC d;
    if (FAILED(IDirect3DDevice9_GetBackBuffer(dev, 0, 0, D3DBACKBUFFER_TYPE_MONO, &bb)) ||
        FAILED(render_real_desc(bb, &d))) {
        DROP(bb);
        return;
    }
    if (!g_layer_state && FAILED(IDirect3DDevice9_CreateStateBlock(dev, D3DSBT_ALL, &g_layer_state))) {
        DROP(bb);
        return;
    }
    /* The game's state kept, ours set, the parts drawn into its own back buffer at its size, its state back. */
    IDirect3DStateBlock9_Capture(g_layer_state);
    IDirect3DDevice9_BeginScene(dev);
    static const D3DRENDERSTATETYPE off[] = {D3DRS_ZENABLE, D3DRS_ZWRITEENABLE, D3DRS_ALPHATESTENABLE,
                                             D3DRS_STENCILENABLE, D3DRS_SCISSORTESTENABLE, D3DRS_FOGENABLE,
                                             D3DRS_SRGBWRITEENABLE, D3DRS_LIGHTING, D3DRS_SEPARATEALPHABLENDENABLE};
    for (size_t i = 0; i < sizeof off / sizeof off[0]; i++)
        IDirect3DDevice9_SetRenderState(dev, off[i], FALSE);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_CULLMODE, D3DCULL_NONE);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_COLORWRITEENABLE, 0xf);
    IDirect3DDevice9_SetSamplerState(dev, 0, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
    IDirect3DDevice9_SetSamplerState(dev, 0, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
    IDirect3DDevice9_SetSamplerState(dev, 0, D3DSAMP_MIPFILTER, D3DTEXF_NONE);
    LayerPart parts[LAYER_PARTS], ready[LAYER_PARTS];
    int nready = 0, n = layer_prepare(dev, (int)d.Width, (int)d.Height, parts, ready, &nready);
    /* The frame the textures are made in: every part once unseen first. */
    if (nready > 0)
        layer_draw_parts(dev, ready, nready, bb, (int)d.Width, (int)d.Height, 0, 1);
    if (n > 0)
        layer_draw_parts(dev, parts, n, bb, (int)d.Width, (int)d.Height, 0, 0);
    IDirect3DDevice9_EndScene(dev);
    IDirect3DStateBlock9_Apply(g_layer_state);
    DROP(bb);
}

void post_layer_before_reset(void)
{
    /* A state block is let go before a reset, as every default pool object (the parts' dynamic textures too); made
     * again at the next frame. */
    DROP(g_layer_state);
    drop_part_textures();
}

/* ---------------------------------------------------------------------------------------------- measuring */

/* Write the top-left w x h of a render target as a 24-bit BMP; 1 on success. */
static int write_bmp(IDirect3DDevice9 *dev, IDirect3DSurface9 *rt, int w, int h, const char *name)
{
    D3DSURFACE_DESC d;
    /* Its real size (the game is answered its own for a target drawn larger: render.c). */
    if (FAILED(render_real_desc(rt, &d)))
        return 0;
    /* The target's pixels come to the CPU through a system-memory copy of the same size and format. */
    IDirect3DSurface9 *sys = NULL;
    if (FAILED(IDirect3DDevice9_CreateOffscreenPlainSurface(dev, d.Width, d.Height, d.Format, D3DPOOL_SYSTEMMEM, &sys,
                                                            NULL)))
        return 0;
    int ok = 0;
    D3DLOCKED_RECT lr;
    char path[MAX_PATH * 2];
    snprintf(path, sizeof path, "%s\\%s", g_dump_dir, name);
    FILE *f = NULL;
    if (SUCCEEDED(IDirect3DDevice9_GetRenderTargetData(dev, rt, sys)) &&
        SUCCEEDED(IDirect3DSurface9_LockRect(sys, &lr, NULL, D3DLOCK_READONLY)) && (f = fopen(path, "wb"))) {
        /* BMP rows are padded to 4 bytes and stored bottom first. */
        int row = (w * 3 + 3) & ~3;
        DWORD size = 54 + (DWORD)row * (DWORD)h;
        BYTE head[54] = {'B', 'M'};
        memcpy(head + 2, &size, 4);
        DWORD off = 54, info = 40, planes_bits = 1 | (24 << 16);
        memcpy(head + 10, &off, 4);
        memcpy(head + 14, &info, 4);
        memcpy(head + 18, &w, 4);
        memcpy(head + 22, &h, 4);
        memcpy(head + 26, &planes_bits, 4);
        fwrite(head, 1, 54, f);
        BYTE *line = calloc(1, (size_t)row);
        for (int y = h - 1; line && y >= 0; y--) {
            const BYTE *src = (const BYTE *)lr.pBits + (size_t)y * (size_t)lr.Pitch;
            /* X8R8G8B8 is blue, green, red, unused in memory: BMP's own order once the fourth byte goes. */
            for (int x = 0; x < w; x++)
                memcpy(line + 3 * x, src + 4 * x, 3);
            fwrite(line, 1, (size_t)row, f);
        }
        free(line);
        fclose(f);
        IDirect3DSurface9_UnlockRect(sys);
        ok = 1;
    }
    DROP(sys);
    return ok;
}

/* The label of the frame dumped this frame (empty: none), for the picture with the layer written after it. */
static char g_dumped[64];

/* Measuring two builds against each other: OPENDMT3_POSTFX_SOURCE names a folder of an earlier run's dumps, and a frame
 * dumped here under a label takes that run's game picture of the same label (LABEL-src.bmp, as write_bmp writes it:
 * 24 bits a pixel, bottom row first) in place of the game's own, before anything reads it; so every filter's and
 * anti-aliasing's picture of both runs is of one game picture, whatever the game's animation did in each. 1 when it
 * took the picture's place. */
static int dump_source(IDirect3DDevice9 *dev, const char *label)
{
    char dir[MAX_PATH], path[MAX_PATH * 2];
    DWORD got = GetEnvironmentVariableA("OPENDMT3_POSTFX_SOURCE", dir, sizeof dir);
    if (!got || got >= sizeof dir)
        return 0;
    snprintf(path, sizeof path, "%s\\%s-src.bmp", dir, label);
    FILE *f = fopen(path, "rb");
    BYTE head[54];
    int w = 0, h = 0, bits = 0;
    if (f && fread(head, 1, sizeof head, f) == sizeof head && head[0] == 'B' && head[1] == 'M') {
        memcpy(&w, head + 18, 4);
        memcpy(&h, head + 22, 4);
        bits = head[28] | head[29] << 8;
    }
    /* Only the game's own size, as the dumps write it. */
    IDirect3DSurface9 *dst = level0(g_src), *sys = NULL;
    D3DSURFACE_DESC d;
    int ok = f && w == GAME_W && h == GAME_H && bits == 24 && dst && SUCCEEDED(render_real_desc(dst, &d)) &&
             (int)d.Width == GAME_W && (int)d.Height == GAME_H &&
             (d.Format == D3DFMT_X8R8G8B8 || d.Format == D3DFMT_A8R8G8B8) &&
             SUCCEEDED(IDirect3DDevice9_CreateOffscreenPlainSurface(dev, GAME_W, GAME_H, d.Format, D3DPOOL_SYSTEMMEM,
                                                                    &sys, NULL));
    D3DLOCKED_RECT lr;
    if (ok && SUCCEEDED(IDirect3DSurface9_LockRect(sys, &lr, NULL, 0))) {
        BYTE line[GAME_W * 3];
        /* Bottom row first; each pixel's blue, green and red, its fourth byte opaque. */
        for (int y = GAME_H - 1; ok && y >= 0; y--) {
            ok = fread(line, 1, sizeof line, f) == sizeof line;
            BYTE *row = (BYTE *)lr.pBits + (size_t)y * (size_t)lr.Pitch;
            for (int x = 0; ok && x < GAME_W; x++) {
                memcpy(row + 4 * x, line + 3 * x, 3);
                row[4 * x + 3] = 0xff;
            }
        }
        IDirect3DSurface9_UnlockRect(sys);
        /* Into the frame's texture, where the chain reads the game's picture. */
        ok = ok && SUCCEEDED(IDirect3DDevice9_UpdateSurface(dev, sys, NULL, dst, NULL));
    } else {
        ok = 0;
    }
    if (f)
        fclose(f);
    DROP(sys);
    DROP(dst);
    ingame_log(ok ? "post: the game's picture for %s from %s (measuring)" : "post: no game picture for %s from %s",
               label, path);
    return ok;
}

/* While dump.now is in the dump folder: this frame's game picture and output written there; with "all" in it, every
 * filter and anti-aliasing pass on this same frame. The file's first word names the files. */
static void dump(IDirect3DDevice9 *dev, int w, int h)
{
    static int frame;
    g_dumped[0] = 0;
    if (!g_dump_dir[0])
        return;
    char path[MAX_PATH * 2], label[64] = "frame", mode[16] = "";
    snprintf(path, sizeof path, "%s\\dump.now", g_dump_dir);
    /* At a frame number named in OPENDMT3_POSTFX_DUMP_AT (the game's timers count frames, so the same number is the
     * same picture in two runs): every pass, named by the number. */
    char at[256];
    DWORD got = GetEnvironmentVariableA("OPENDMT3_POSTFX_DUMP_AT", at, sizeof at);
    long now = ingame_frame();
    int timed = 0;
    for (char *p = got && got < sizeof at ? at : NULL; p && *p; p = strchr(p, ',') ? strchr(p, ',') + 1 : NULL)
        if (strtol(p, NULL, 10) == now)
            timed = 1;
    FILE *f = NULL;
    if (timed) {
        snprintf(label, sizeof label, "f%ld", now);
        strcpy(mode, "all");
    } else {
        /* Looked for every 10th frame: a file check each frame would be cost for nothing. */
        if (++frame % 10)
            return;
        /* A toast asked for (toast.now holds its words): the layer's toast shown as the safety net shows its note. */
        char toast_path[MAX_PATH * 2];
        snprintf(toast_path, sizeof toast_path, "%s\\toast.now", g_dump_dir);
        if ((f = fopen(toast_path, "r"))) {
            char words[192] = "";
            if (fgets(words, sizeof words, f))
                words[strcspn(words, "\r\n")] = 0;
            fclose(f);
            f = NULL;
            DeleteFileA(toast_path);
            layer_toast(words);
        }
        /* Measuring every choice in one run (every pass is made when measuring, so any runs at once): choice.now holds
         * an upscale filter, a sharpness, an anti-aliasing and a shape (keep or fill), as the launcher names them. */
        char choice_path[MAX_PATH * 2];
        snprintf(choice_path, sizeof choice_path, "%s\\choice.now", g_dump_dir);
        if ((f = fopen(choice_path, "r"))) {
            char up[16] = "", aa[16] = "", shape[8] = "";
            int sharp = -1, read_n = fscanf(f, "%15s %d %15s %7s", up, &sharp, aa, shape);
            fclose(f);
            f = NULL;
            DeleteFileA(choice_path);
            int u = upscale_from_name(up), a = aa_from_name(aa);
            if (read_n >= 3 && u >= 0 && a >= 0 && sharp >= 0 && sharp <= 100) {
                /* The filter chosen from now on, kept through a reset; bilinear while the game is drawn at the
                 * picture's size (make_default). */
                g_upscale_chosen = u;
                g_upscale = render_on() ? UPSCALE_SMOOTH : u;
                g_aa = a;
                g_sharpness = sharp;
                if (read_n >= 4)
                    g_settings.fill = !lstrcmpiA(shape, "fill");
                ingame_log("post: choice now upscale %s, sharpness %d, anti-aliasing %s, %s (measuring)",
                           UPSCALE_NAMES[u], sharp, AA_NAMES[a], g_settings.fill ? "fill" : "keep");
            }
        }
        if (!(f = fopen(path, "r")))
            return;
        if (fscanf(f, "%63s %15s", label, mode) < 1)
            strcpy(label, "frame");
        fclose(f);
    }
    char name[160];
    /* "frame": no picture, only the frame's number in dump.done (a script's clock: the game's timers count frames). */
    if (!strcmp(mode, "frame"))
        goto done;
    /* Measuring against another build's run: its game picture of this label first, when one is named. */
    dump_source(dev, label);
    snprintf(name, sizeof name, "%s-src.bmp", label);
    IDirect3DSurface9 *src = level0(g_src);
    write_bmp(dev, src, g_src_w, g_src_h, name);
    DROP(src);
    if (!strcmp(mode, "all")) {
        /* Each upscale filter with no anti-aliasing, then each anti-aliasing pass at the game's size and enlarged with
         * the filter chosen. */
        for (int u = 0; u < 4; u++) {
            run_chain(dev, u, AA_OFF, w, h);
            snprintf(name, sizeof name, "%s-up-%s.bmp", label, UPSCALE_NAMES[u]);
            write_bmp(dev, g_real_bb, g_client_w, g_client_h, name);
        }
        /* NIS once more with its edge map in 32-bit floats (the reference's full-precision build; the same two numbers
         * in the first two of four), so the half floats' own effect on its output is read off the two files. */
        IDirect3DTexture9 *halves = g_nis_edges, *floats = NULL;
        if (halves && SUCCEEDED(IDirect3DDevice9_CreateTexture(dev, (UINT)g_src_w, (UINT)g_src_h, 1,
                                                               D3DUSAGE_RENDERTARGET, D3DFMT_A32B32G32R32F,
                                                               D3DPOOL_DEFAULT, &floats, NULL))) {
            g_nis_edges = floats;
            run_chain(dev, UPSCALE_NIS, AA_OFF, w, h);
            snprintf(name, sizeof name, "%s-up-nis-floats.bmp", label);
            write_bmp(dev, g_real_bb, g_client_w, g_client_h, name);
            g_nis_edges = halves;
            DROP(floats);
        }
        for (int a = AA_FXAA; a <= AA_SMAA_ULTRA; a++) {
            IDirect3DTexture9 *t = run_aa(dev, a, g_src);
            IDirect3DSurface9 *s = level0(t);
            snprintf(name, sizeof name, "%s-aa-%s-game.bmp", label, AA_NAMES[a]);
            write_bmp(dev, s, g_src_w, g_src_h, name);
            DROP(s);
            run_upscale(dev, g_upscale, t, w, h);
            snprintf(name, sizeof name, "%s-aa-%s.bmp", label, AA_NAMES[a]);
            write_bmp(dev, g_real_bb, g_client_w, g_client_h, name);
        }
    }
    /* The chain as chosen, last, so what is presented is what the player sees ("src": the game's picture only). */
    run_chain(dev, g_upscale, g_aa, w, h);
    snprintf(name, sizeof name, "%s-out.bmp", label);
    if (strcmp(mode, "src")) {
        write_bmp(dev, g_real_bb, g_client_w, g_client_h, name);
        /* The same frame with the layer over it follows (post_present): the two differ only where the layer drew. */
        snprintf(g_dumped, sizeof g_dumped, "%s", label);
    }
done:
    if (!timed)
        DeleteFileA(path);
    snprintf(path, sizeof path, "%s\\dump.done", g_dump_dir);
    if ((f = fopen(path, "a"))) {
        fprintf(f, "%s %dx%d upscale %s sharpness %d aa %s frame %ld\n", label, w, h, UPSCALE_NAMES[g_upscale],
                g_sharpness, AA_NAMES[g_aa], ingame_frame());
        fclose(f);
    }
    ingame_log("post: dumped %s (%s) at %dx%d", label, mode[0] ? mode : "one", w, h);
}

/* The slot the next frame uses was read already (just after the present, so its "game" timestamp could go in). */
static int g_slot_read;

/* The GPU's time for an earlier frame's passes, when its queries have answered (never waited for). */
static void read_gpu_time(void)
{
    int i = g_q_next;
    if (!g_gpu_timing || !g_q_issued[i])
        return;
    BOOL disjoint = TRUE;
    UINT64 freq = 0, t0 = 0, t1 = 0;
    /* Four frames old: answered by now on any device; if not, this frame's number is simply not counted. */
    if (IDirect3DQuery9_GetData(g_q_disjoint[i], &disjoint, sizeof disjoint, 0) == S_OK &&
        IDirect3DQuery9_GetData(g_q_freq[i], &freq, sizeof freq, 0) == S_OK &&
        IDirect3DQuery9_GetData(g_q_begin[i], &t0, sizeof t0, 0) == S_OK &&
        IDirect3DQuery9_GetData(g_q_end[i], &t1, sizeof t1, 0) == S_OK && !disjoint && freq && t1 >= t0) {
        /* The chain's own passes: its two timestamps bracket them alone (the layer's blur before, its parts after). */
        g_gpu_us = (double)(t1 - t0) * 1e6 / (double)freq;
        /* With the diagnostic switch: the layer's blur pass(es) and each part, by kind. */
        UINT64 b0 = 0, b1 = 0, p0 = 0, p1 = 0;
        if (g_q_blur_issued[i] && IDirect3DQuery9_GetData(g_q_blur0[i], &b0, sizeof b0, 0) == S_OK &&
            IDirect3DQuery9_GetData(g_q_blur1[i], &b1, sizeof b1, 0) == S_OK && b1 >= b0) {
            g_costs.blur_gpu_us += (double)(b1 - b0) * 1e6 / (double)freq;
            g_costs.blur_gpu_n++;
        }
        if (g_q_parts_n[i] && IDirect3DQuery9_GetData(g_q_parts[i][0], &p0, sizeof p0, 0) == S_OK) {
            for (int k = 0; k < g_q_parts_n[i]; k++) {
                if (IDirect3DQuery9_GetData(g_q_parts[i][k + 1], &p1, sizeof p1, 0) != S_OK || p1 < p0)
                    break;
                int kind = g_q_parts_kind[i][k];
                g_costs.gpu_us[kind] += (double)(p1 - p0) * 1e6 / (double)freq;
                g_costs.gpu_n[kind]++;
                p0 = p1;
            }
        }
    }
    /* By pass: each step's time since the one before, and the game's own frame before the first; a frame whose
     * timestamps have not all answered (or whose clock jumped) is left out whole. */
    if (g_pass_times && g_step_n[i] >= 2) {
        UINT64 t[STEPS], pre = 0;
        int ok = IDirect3DQuery9_GetData(g_q_disjoint[i], &disjoint, sizeof disjoint, 0) == S_OK && !disjoint &&
                 IDirect3DQuery9_GetData(g_q_freq[i], &freq, sizeof freq, 0) == S_OK && freq;
        for (int k = 0; ok && k < g_step_n[i]; k++)
            ok = IDirect3DQuery9_GetData(g_q_step[i][k], &t[k], sizeof t[k], 0) == S_OK && (k == 0 || t[k] >= t[k - 1]);
        if (ok) {
            if (g_q_pre_issued[i] && IDirect3DQuery9_GetData(g_q_pre[i], &pre, sizeof pre, 0) == S_OK && t[0] >= pre) {
                pt_step(&g_pt_log, "game", (float)((double)(t[0] - pre) * 1e6 / (double)freq));
                pt_step(&g_pt_note, "game", (float)((double)(t[0] - pre) * 1e6 / (double)freq));
            }
            for (int k = 1; k < g_step_n[i]; k++) {
                float us = (float)((double)(t[k] - t[k - 1]) * 1e6 / (double)freq);
                pt_step(&g_pt_log, g_step_name[i][k], us);
                pt_step(&g_pt_note, g_step_name[i][k], us);
            }
            /* The picture's work whole: from the last of the measuring's own steps (the second timestamp, the empty
             * pass) to the last step, the blur, the bars, the chain and the layer's parts in it. */
            int from = 0;
            for (int k = 0; k < g_step_n[i]; k++)
                if (!strcmp(g_step_name[i][k], "timestamp") || !strcmp(g_step_name[i][k], "empty pass"))
                    from = k;
            float all = (float)((double)(t[g_step_n[i] - 1] - t[from]) * 1e6 / (double)freq);
            pt_step(&g_pt_log, "all", all);
            pt_step(&g_pt_note, "all", all);
            pt_frame(&g_pt_log);
            pt_frame(&g_pt_note);
        }
    }
    g_step_n[i] = 0;
    g_q_pre_issued[i] = 0;
    g_q_issued[i] = 0;
    g_q_blur_issued[i] = 0;
    g_q_parts_n[i] = 0;
}

/* The game's first screen: until a frame with something on it is seen, every 15th frame's picture is averaged 8 x 8
 * (the glass's first pass, into its first target) and read back, and the first with any of those averages over 24 of
 * 255 in a colour (the frames while the game loads are black) is its first screen: the layer is told. Read back only
 * then, a few times in the game's first seconds, never after. */
static void first_screen_look(IDirect3DDevice9 *dev)
{
    if (g_first_seen || !glass_ready() || ++g_first_look % 15)
        return;
    /* The surface in the system's memory the average is read into, made the first time. */
    if (!g_first_probe && FAILED(IDirect3DDevice9_CreateOffscreenPlainSurface(dev, BLUR_W, BLUR_H, D3DFMT_X8R8G8B8,
                                                                                D3DPOOL_SYSTEMMEM, &g_first_probe, NULL)))
        return;
    IDirect3DDevice9_BeginScene(dev);
    pass_state(dev);
    blur_pass(dev, g_src, 0);
    IDirect3DDevice9_EndScene(dev);
    IDirect3DSurface9 *avg = level0(g_blur[0]);
    HRESULT hr = IDirect3DDevice9_GetRenderTargetData(dev, avg, g_first_probe);
    DROP(avg);
    D3DLOCKED_RECT lr;
    if (FAILED(hr) || FAILED(IDirect3DSurface9_LockRect(g_first_probe, &lr, NULL, D3DLOCK_READONLY)))
        return;
    int on = 0;
    for (int y = 0; y < BLUR_H && !on; y++) {
        const uint32_t *row = (const uint32_t *)((const uint8_t *)lr.pBits + (size_t)y * (size_t)lr.Pitch);
        for (int x = 0; x < BLUR_W && !on; x++)
            on = ((row[x] >> 16) & 0xff) > 24 || ((row[x] >> 8) & 0xff) > 24 || (row[x] & 0xff) > 24;
    }
    IDirect3DSurface9_UnlockRect(g_first_probe);
    if (on) {
        g_first_seen = 1;
        ingame_log("post: the game's first screen at frame %ld", ingame_frame());
        layer_first_screen();
    }
}

/* ------------------------------------------------------------------------------------------------ each frame */

/* The bars beside the picture (logic.c picture_rect), each frame: the back buffer's content is not kept from one
 * present to the next. */
static void fill_bars(IDirect3DDevice9 *dev)
{
    RECT bars[2];
    int n = 0;
    if (g_pic.x > 0) {
        SetRect(&bars[n++], 0, 0, g_pic.x, g_client_h);
        SetRect(&bars[n++], g_pic.x + g_pic.w, 0, g_client_w, g_client_h);
    } else if (g_pic.y > 0) {
        SetRect(&bars[n++], 0, 0, g_client_w, g_pic.y);
        SetRect(&bars[n++], 0, g_pic.y + g_pic.h, g_client_w, g_client_h);
    }
    /* Both in one clear of the back buffer as the target (its viewport the whole of it, set with it): two ColorFills
     * measured as two passes' worth of the card's time each. */
    D3DRECT r[2];
    int k = 0;
    for (int i = 0; i < n; i++)
        if (bars[i].right > bars[i].left && bars[i].bottom > bars[i].top) {
            r[k].x1 = bars[i].left, r[k].y1 = bars[i].top, r[k].x2 = bars[i].right, r[k].y2 = bars[i].bottom;
            k++;
        }
    if (!k)
        return;
    real_set_render_target(dev, 0, g_real_bb);
    IDirect3DDevice9_Clear(dev, (DWORD)k, r, D3DCLEAR_TARGET, BAR_COLOR, 1.0f, 0);
}

void post_picture(int *x, int *y, int *w, int *h)
{
    /* The last frame's (the chain sets it at each present); before the first, nothing known: 0 x 0. */
    *x = g_pic.x;
    *y = g_pic.y;
    *w = g_pic.w;
    *h = g_pic.h;
}

const RECT *post_present(IDirect3DDevice9 *dev)
{
    static RECT shown;
    /* Measuring a lost device: with reset.now in the dump folder, a reset as the game asks for one is made here, through
     * the device's table (so through the hooks, as the game's own reset goes); with its own textures alive it fails
     * and the device is lost, as when another program takes the display, and the game must reset it itself. */
    static int reset_look;
    char reset_path[MAX_PATH * 2];
    if (g_dump_dir[0] && g_active && ++reset_look % 30 == 0) {
        snprintf(reset_path, sizeof reset_path, "%s\\reset.now", g_dump_dir);
        if (GetFileAttributesA(reset_path) != INVALID_FILE_ATTRIBUTES) {
            DeleteFileA(reset_path);
            D3DPRESENT_PARAMETERS pp = g_game_pp;
            HRESULT hr = dev->lpVtbl->Reset(dev, &pp);
            ingame_log("post: measuring reset made: 0x%08lx, the device now 0x%08lx", (unsigned long)hr,
                       (unsigned long)IDirect3DDevice9_TestCooperativeLevel(dev));
            return NULL;
        }
    }
    /* Nothing to run until the chain's objects exist (between a failed reset and the next). */
    if (!g_active || !g_proxy || !g_state)
        return NULL;
    LARGE_INTEGER t0, t1;
    QueryPerformanceCounter(&t0);
    /* A lost device draws nothing until the game resets it. */
    if (IDirect3DDevice9_TestCooperativeLevel(dev) != D3D_OK)
        return NULL;
    /* The client's size, the picture's place in it (the chain and the layer work at the picture's size). */
    int cw, ch;
    output_size(&cw, &ch);
    g_client_w = cw;
    g_client_h = ch;
    g_pic = picture_rect(cw, ch, g_settings.fill);
    int w = g_pic.w, h = g_pic.h;
    /* The oldest frame's timestamps (read already when the game's own frame was timed from the last present). */
    if (!g_slot_read)
        read_gpu_time();
    g_slot_read = 0;
    int q = g_q_next;
    if (g_gpu_timing)
        IDirect3DQuery9_Issue(g_q_disjoint[q], D3DISSUE_BEGIN);
    /* Measuring by the frame: the game's own work done first, so what follows is the chain's and the layer's alone. */
    LONGLONG whole = g_layer_timing == 3 ? idle_now(dev) : 0;
    /* The game's state, to be put back exactly. */
    IDirect3DStateBlock9_Capture(g_state);
    g_pass_count = 0;
    /* The in-game layer's parts for this frame (their pictures drawn again where they changed). */
    LayerPart parts[LAYER_PARTS], ready[LAYER_PARTS];
    int nready = 0, nparts = layer_prepare(dev, w, h, parts, ready, &nready);
    /* The game's frame out of the proxy, its samples resolved on the way, when the game asked for samples; without
     * them the game drew into the frame's texture itself. */
    if (!g_proxy_is_src) {
        IDirect3DSurface9 *src = level0(g_src);
        IDirect3DDevice9_StretchRect(dev, g_proxy, NULL, src, NULL, D3DTEXF_NONE);
        DROP(src);
    }
    IDirect3DDevice9_BeginScene(dev);
    pass_state(dev);
    /* By pass: the first timestamp, a second one at once (what a timestamp costs), and an empty pass, one pixel drawn
     * into a target of one pixel (what any pass costs before its own work). */
    g_stepping = 1;
    step(dev, "start");
    step(dev, "timestamp");
    if (g_pass_times && g_empty && g_ps[PASS_BILINEAR]) {
        IDirect3DSurface9 *one = level0(g_empty);
        bind(dev, 0, g_src, 1);
        draw(dev, g_ps[PASS_BILINEAR], one, 1, 1, GAME_W, GAME_H);
        DROP(one);
        g_pass_count--;
        step(dev, "empty pass");
    }
    /* The glass's blurred frame first, when due, so the parts after the upscale go straight into its target (the passes
     * at the frame's end instead measured no cheaper on Wine's software renderer: the bar +1.0 ms a frame against
     * +0.37 here, the question +1.9 against +0.63). While a glass panel shows and the game moves: the whole blur when
     * the panel comes, then a pass every BLUR_EVERY frames; made once in one frame for the frame the game is held still
     * on, and once for the chip's still glass when none was ever made; never for the chip alone after. */
    int glass = nparts > 0 && glass_ready();
    int panels = 0, still = 0;
    for (int i = 0; i < nparts; i++) {
        panels += PART_IS_PANEL(parts[i].kind);
        /* The chip reads the glass with no live blur under it. */
        still += parts[i].kind == PART_FPS;
    }
    int holding = layer_is_holding();
    if (!holding)
        g_blur_held = 0;
    /* The frame the parts' textures are made in: the glass's three passes run once too (their first use is this
     * frame's, not the one a panel first comes in), over the game's frame as it is; live, so the chip's still glass is
     * made again from the frame it first shows on. */
    if (nready > 0 && glass_ready()) {
        layer_blur(dev, g_src, 1);
        g_blur_live = 1;
    }
    if (glass) {
        if (panels && holding && !g_blur_held) {
            layer_blur(dev, g_src, 1);
            g_blur_held = 1;
            g_blur_live = 1;
        } else if (panels && !holding && (!g_panels_before || !g_blur_made)) {
            /* A panel comes: the whole blur of this frame now, then one pass every BLUR_EVERY frames. */
            layer_blur(dev, g_src, 1);
            g_blur_wait = BLUR_EVERY;
            g_blur_live = 1;
        } else if (panels && !holding && --g_blur_wait <= 0) {
            layer_blur(dev, g_src, 0);
            g_blur_wait = BLUR_EVERY;
            g_blur_live = 1;
        } else if (!panels && still && (!g_blur_made || g_blur_live)) {
            /* The chip's still glass, made whole in this frame: the first time, and again after a live blur. */
            layer_blur(dev, g_src, 1);
            g_blur_live = 0;
        }
    }
    g_panels_before = glass && panels > 0;
    /* The chain's own time on the GPU: its passes alone between these two timestamps (the safety net's measure). */
    if (g_gpu_timing)
        IDirect3DQuery9_Issue(g_q_begin[q], D3DISSUE_END);
    /* The bars (none when the picture fills the client), in the launcher's darkest neutral; the final passes take the
     * picture's origin off their pixel's position (c8). */
    fill_bars(dev);
    if (g_pic.w < cw || g_pic.h < ch)
        step(dev, "bars");
    float origin[4] = {(float)g_pic.x, (float)g_pic.y, 0, 0};
    IDirect3DDevice9_SetPixelShaderConstantF(dev, 8, origin, 1);
    run_chain(dev, g_upscale, g_aa, w, h);
    if (g_gpu_timing)
        IDirect3DQuery9_Issue(g_q_end[q], D3DISSUE_END);
    /* The measuring dump's passes are never steps of the frame shown. */
    g_stepping = 0;
    dump(dev, w, h);
    g_stepping = 1;
    /* A frame dumped: the dump's passes their own step, so the layer's after them is its own. */
    if (g_dumped[0])
        step(dev, "dump");
    /* The in-game layer over the picture, at the window's pixels: in the frame its textures are made, every part once
     * unseen first (the chain's last pass left the back buffer as the target; an unseen glass part's composing puts it
     * back). */
    if (nready > 0)
        layer_draw_parts(dev, ready, nready, g_real_bb, w, h, glass_ready(), 1);
    if (nparts > 0 || nready > 0) {
        if (nparts > 0)
            layer_draw_parts(dev, parts, nparts, g_real_bb, w, h, glass, 0);
        step(dev, "layer");
    }
    g_stepping = 0;
    if (g_dumped[0]) {
        /* Measuring: the frame just dumped, with the layer over it. */
        char name[96];
        snprintf(name, sizeof name, "%s-ui.bmp", g_dumped);
        write_bmp(dev, g_real_bb, cw, ch, name);
    }
    IDirect3DDevice9_EndScene(dev);
    /* Until the game's first screen is seen: a look at this frame now and then. */
    first_screen_look(dev);
    /* Drawn at the picture's size: what the game asked of render.c's replacements, a line every 600 frames. */
    if (render_on() && ingame_frame() % 600 == 0)
        render_summary();
    /* Measuring by the frame: the chain's and the layer's work done, its whole time counted. */
    if (whole) {
        g_costs.frame_us += ticks_us(whole, idle_now(dev));
        g_costs.frame_n++;
    }
    /* The game's target and depth back, then its state (its viewport among it). */
    real_set_render_target(dev, 0, g_proxy);
    IDirect3DDevice9_SetDepthStencilSurface(dev, g_depth);
    IDirect3DStateBlock9_Apply(g_state);
    if (g_gpu_timing) {
        IDirect3DQuery9_Issue(g_q_disjoint[q], D3DISSUE_END);
        IDirect3DQuery9_Issue(g_q_freq[q], D3DISSUE_END);
        g_q_issued[q] = 1;
        g_q_next = (q + 1) % QUERIES;
    }
    QueryPerformanceCounter(&t1);
    g_cpu_ticks = t1.QuadPart - t0.QuadPart;
    /* Presented one to one from the back buffer's top-left: the picture and its bars. */
    SetRect(&shown, 0, 0, cw, ch);
    return &shown;
}

void post_after_present(IDirect3DDevice9 *dev)
{
    (void)dev;
    if (!g_pass_times || !g_active || !g_q_pre[g_q_next])
        return;
    /* The slot the next frame will use, read now (its frame is four old), then the game's own frame begins. */
    read_gpu_time();
    g_slot_read = 1;
    IDirect3DQuery9_Issue(g_q_pre[g_q_next], D3DISSUE_END);
    g_q_pre_issued[g_q_next] = 1;
}

/* The launcher's note of the picture's GPU time (beside this DLL in openDMT3's folder, read when the game ends): one
 * line each ten seconds, an hour's lines at most. */
static void note_times(const char *line)
{
    static int written;
    WCHAR path[MAX_PATH * 4];
    if (written >= 360 || !ingame_beside(L"openDMT3-picture-times.txt", path, MAX_PATH * 4))
        return;
    FILE *f = _wfopen(path, written ? L"a" : L"w");
    if (!f)
        return;
    fprintf(f, "%s\n", line);
    fclose(f);
    written++;
}

void post_pass_times_line(void)
{
    if (!g_pass_times)
        return;
    char times[720], line[900];
    /* The choice and the client it ran in, then each step's median. */
    char what[160];
    snprintf(what, sizeof what, "%dx%d %s, upscale %s, sharpness %d, anti-aliasing %s", g_client_w, g_client_h,
             g_settings.fill ? "fill" : "keep", UPSCALE_NAMES[g_upscale], g_sharpness, AA_NAMES[g_aa]);
    if (g_pt_log.frames) {
        pt_line(&g_pt_log, times, sizeof times);
        ingame_log("post: GPU time by pass at %s: %s", what, times);
    }
    pt_clear(&g_pt_log);
    /* Every fifth call (ten seconds): a line for the launcher. */
    if (++g_pt_lines % 5)
        return;
    if (g_pt_note.frames) {
        pt_line(&g_pt_note, times, sizeof times);
        snprintf(line, sizeof line, "%s: %s", what, times);
        note_times(line);
    }
    pt_clear(&g_pt_note);
}

void post_layer_cost(LONGLONG *cpu_ticks, int *parts, int *panels)
{
    *cpu_ticks = g_layer_ticks;
    *parts = g_layer_drawn;
    *panels = g_layer_panels;
}

void post_layer_costs(LayerCosts *out)
{
    /* Handed over and started again (the switch's state kept). */
    *out = g_costs;
    int timing = g_costs.timing;
    memset(&g_costs, 0, sizeof g_costs);
    g_costs.timing = timing;
}

void post_cost(LONGLONG *cpu_ticks, double *gpu_us, int *passes)
{
    /* The picture's own cost: the layer's CPU time taken out, and on the GPU the chain's passes alone (their timestamps
     * leave the layer's blur and parts outside): the safety net judges the filters by it, never the panels. */
    *cpu_ticks = g_active ? g_cpu_ticks - g_layer_ticks : 0;
    *gpu_us = g_active ? g_gpu_us : -1;
    *passes = g_active ? g_pass_count : 0;
}

int post_running(void)
{
    return g_active;
}

int post_lighten(int *upscale, int *aa, int *aa_changed)
{
    int up = g_upscale, a = g_aa;
    /* Nothing lighter, or the lighter pass not made (it is compiled with the chain; a failed compile leaves it out). */
    if (!g_active || !post_lighter(&up, &a))
        return 0;
    if ((a == AA_FXAA && !g_ps[PASS_FXAA]) || !g_ps[PASS_BILINEAR])
        return 0;
    ingame_log("post: stepped down from %s with %s to %s with %s at frame %ld (the chain made frames late)",
               UPSCALE_NAMES[g_upscale], AA_NAMES[g_aa], UPSCALE_NAMES[up], AA_NAMES[a], ingame_frame());
    /* From the next frame on (the anti-aliased frame's target exists: the chain had anti-aliasing before). */
    *aa_changed = a != g_aa;
    g_upscale = up;
    /* The step is the player's filter's too, so a reset (make_default) brings back the lighter one, never the one
     * stepped down from (drawn at the picture's size, the filter is bilinear already: only the anti-aliasing steps). */
    if (!render_on())
        g_upscale_chosen = up;
    g_aa = a;
    *upscale = up;
    *aa = a;
    return 1;
}
