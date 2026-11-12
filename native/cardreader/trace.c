/*
 * How the game draws, written to the in-game log for study (OPENDMT3_INGAME_TRACE set): the Direct3D 9 device's
 * calls a game makes, counted over each 300 frames, with what they carry: the vertex formats of its draws (pre-
 * transformed XYZRHW or not), whether it sets vertex shaders or declarations, its transforms, viewports, scissor
 * rectangles, render targets, the surfaces and textures it makes, and its copies between surfaces. Nothing here is on
 * unless that variable is set: a player's game never runs it.
 */
#include "ingame.h"

#include <d3d9.h>
#include <stdio.h>
#include <string.h>

/* Counters for one window of frames. */
static struct {
    LONG frames;
    LONG calls[120];               /* by method index in IDirect3DDevice9's table */
    LONG prims_by_fvf[16];         /* primitive draws by the FVF seen: see fvf_slot */
    DWORD fvf_seen[16];
    LONG with_shader, with_decl;   /* draws while a vertex shader or a declaration was set */
    /* Texture sampling at the draws (stage 0): each different set of minification, magnification and mip filters,
     * anisotropy and LOD bias, with whether the draw was pre-transformed (2D) or not (3D), and its count. */
    DWORD samp[12][6];
    LONG samp_draws[12];
    LONG mipped, unmipped, untextured;   /* draws whose texture has mip levels, has one, or none is set */
} T;
static DWORD g_fvf;
static int g_shader, g_decl;
/* The frame whose calls are written one by one, in order (OPENDMT3_INGAME_TRACE=sequence): frames 600 and 2400, one
 * on the title and one later, so the order of the game's passes (which target each draw lands in) can be read. */
static LONG g_frame_no;
static int g_sequence;
/* Whether this frame's calls are being written. */
static int in_sequence(void)
{
    return g_sequence && (g_frame_no == 600 || g_frame_no == 2400);
}
/* The real methods, by index. */
static void *real[120];

/* A slot for each different FVF value (16 at most). */
static int fvf_slot(DWORD fvf)
{
    for (int i = 0; i < 16; i++) {
        if (T.fvf_seen[i] == fvf && T.prims_by_fvf[i])
            return i;
        if (!T.prims_by_fvf[i]) {
            T.fvf_seen[i] = fvf;
            return i;
        }
    }
    return 15;
}

/* The distinct viewports and render-target sizes the draws were made with (the first 12). */
static void draw_state(IDirect3DDevice9 *d)
{
    static long seen[12][6];
    static int count;
    if (count >= 12)
        return;
    D3DVIEWPORT9 v;
    IDirect3DSurface9 *rt = NULL;
    D3DSURFACE_DESC desc;
    memset(&desc, 0, sizeof desc);
    if (FAILED(IDirect3DDevice9_GetViewport(d, &v)))
        return;
    if (SUCCEEDED(IDirect3DDevice9_GetRenderTarget(d, 0, &rt)) && rt) {
        IDirect3DSurface9_GetDesc(rt, &desc);
        IDirect3DSurface9_Release(rt);
    }
    long key[6] = {(long)v.X, (long)v.Y, (long)v.Width, (long)v.Height, (long)desc.Width, (long)desc.Height};
    for (int i = 0; i < count; i++)
        if (!memcmp(seen[i], key, sizeof key))
            return;
    memcpy(seen[count++], key, sizeof key);
    ingame_log("trace: draw with viewport %ld %ld %ldx%ld on a %ldx%ld target, fvf 0x%lx", key[0], key[1], key[2], key[3],
               key[4], key[5], (unsigned long)g_fvf);
}

/* One draw in the written frame: its kind, primitive count, the depth test and blending it is made with. */
static void seq_draw(IDirect3DDevice9 *d, const char *what, UINT count)
{
    if (!in_sequence())
        return;
    DWORD z = 0, zw = 0, blend = 0, src = 0, dst = 0;
    IDirect3DDevice9_GetRenderState(d, D3DRS_ZENABLE, &z);
    IDirect3DDevice9_GetRenderState(d, D3DRS_ZWRITEENABLE, &zw);
    IDirect3DDevice9_GetRenderState(d, D3DRS_ALPHABLENDENABLE, &blend);
    IDirect3DDevice9_GetRenderState(d, D3DRS_SRCBLEND, &src);
    IDirect3DDevice9_GetRenderState(d, D3DRS_DESTBLEND, &dst);
    IDirect3DBaseTexture9 *t = NULL;
    IDirect3DDevice9_GetTexture(d, 0, &t);
    ingame_log("seq %ld: %s %u, z %lu write %lu, blend %lu (%lu %lu), texture %p", (long)g_frame_no, what, count,
               (unsigned long)z, (unsigned long)zw, (unsigned long)blend, (unsigned long)src, (unsigned long)dst,
               (void *)t);
    if (t)
        IDirect3DBaseTexture9_Release(t);
}

/* The sampling of stage 0 at a draw: its filters, anisotropy, LOD bias and the texture's mip levels, counted. */
static void sampling(IDirect3DDevice9 *d)
{
    IDirect3DBaseTexture9 *t = NULL;
    if (FAILED(IDirect3DDevice9_GetTexture(d, 0, &t)) || !t) {
        T.untextured++;
        return;
    }
    if (IDirect3DBaseTexture9_GetLevelCount(t) > 1)
        T.mipped++;
    else
        T.unmipped++;
    IDirect3DBaseTexture9_Release(t);
    DWORD key[6] = {0};
    IDirect3DDevice9_GetSamplerState(d, 0, D3DSAMP_MINFILTER, &key[0]);
    IDirect3DDevice9_GetSamplerState(d, 0, D3DSAMP_MAGFILTER, &key[1]);
    IDirect3DDevice9_GetSamplerState(d, 0, D3DSAMP_MIPFILTER, &key[2]);
    IDirect3DDevice9_GetSamplerState(d, 0, D3DSAMP_MAXANISOTROPY, &key[3]);
    IDirect3DDevice9_GetSamplerState(d, 0, D3DSAMP_MIPMAPLODBIAS, &key[4]);
    /* 2D (pre-transformed) or 3D. */
    key[5] = (g_fvf & D3DFVF_POSITION_MASK) == D3DFVF_XYZRHW ? 2 : 3;
    for (int i = 0; i < 12; i++) {
        if (T.samp_draws[i] && !memcmp(T.samp[i], key, sizeof key)) {
            T.samp_draws[i]++;
            return;
        }
        if (!T.samp_draws[i]) {
            memcpy(T.samp[i], key, sizeof key);
            T.samp_draws[i] = 1;
            return;
        }
    }
}

/* One draw: counted against the format and the shader state in use. */
static void drawn_on(IDirect3DDevice9 *d)
{
    /* Its sampling (traced with the chain off, every draw is the game's). */
    sampling(d);
    T.prims_by_fvf[fvf_slot(g_fvf)]++;
    if (g_shader)
        T.with_shader++;
    if (g_decl)
        T.with_decl++;
}

/* The summary of a window of frames, then the counters cleared. */
static void summary(void)
{
    static const struct {
        int index;
        const char *name;
    } named[] = {{23, "CreateTexture"}, {26, "CreateVertexBuffer"}, {28, "CreateRenderTarget"},
                 {29, "CreateDepthStencilSurface"}, {30, "UpdateSurface"}, {31, "UpdateTexture"},
                 {34, "StretchRect"}, {35, "ColorFill"}, {37, "SetRenderTarget"}, {39, "SetDepthStencilSurface"},
                 {14, "GetSwapChain"}, {18, "GetBackBuffer"}, {38, "GetRenderTarget"}, {40, "GetDepthStencilSurface"},
                 {43, "Clear"}, {44, "SetTransform"}, {47, "SetViewport"}, {75, "SetScissorRect"},
                 {81, "DrawPrimitive"}, {82, "DrawIndexedPrimitive"}, {83, "DrawPrimitiveUP"},
                 {84, "DrawIndexedPrimitiveUP"}, {87, "SetVertexDeclaration"}, {89, "SetFVF"},
                 {92, "SetVertexShader"}, {107, "SetPixelShader"}};
    char line[1024];
    int n = snprintf(line, sizeof line, "trace: %ld frames:", (long)T.frames);
    for (size_t i = 0; i < sizeof named / sizeof named[0] && n < (int)sizeof line - 40; i++)
        if (T.calls[named[i].index])
            n += snprintf(line + n, sizeof line - (size_t)n, " %s %ld", named[i].name, (long)T.calls[named[i].index]);
    ingame_log("%s", line);
    n = snprintf(line, sizeof line, "trace: draws by FVF:");
    for (int i = 0; i < 16 && n < (int)sizeof line - 40; i++)
        if (T.prims_by_fvf[i])
            n += snprintf(line + n, sizeof line - (size_t)n, " 0x%lx%s %ld", (unsigned long)T.fvf_seen[i],
                          (T.fvf_seen[i] & D3DFVF_POSITION_MASK) == D3DFVF_XYZRHW ? "(XYZRHW)" : "",
                          (long)T.prims_by_fvf[i]);
    n += snprintf(line + n, sizeof line - (size_t)n, "; with a vertex shader %ld, with a declaration %ld",
                  (long)T.with_shader, (long)T.with_decl);
    ingame_log("%s", line);
    /* Filters by D3DTEXTUREFILTERTYPE: 0 none, 1 point, 2 linear, 3 anisotropic. */
    for (int i = 0; i < 12; i++) {
        /* The LOD bias is a float kept in the state's DWORD. */
        float bias;
        memcpy(&bias, &T.samp[i][4], sizeof bias);
        if (T.samp_draws[i])
            ingame_log("trace: sampling %s: min %lu mag %lu mip %lu, anisotropy %lu, lod bias %g: %ld draws",
                       T.samp[i][5] == 2 ? "2D" : "3D", (unsigned long)T.samp[i][0], (unsigned long)T.samp[i][1],
                       (unsigned long)T.samp[i][2], (unsigned long)T.samp[i][3], bias, (long)T.samp_draws[i]);
    }
    ingame_log("trace: textures at draws: with mip levels %ld, one level %ld, none %ld", (long)T.mipped,
               (long)T.unmipped, (long)T.untextured);
    memset(&T, 0, sizeof T);
}

/* Each traced method: count it, note what it carries, call the real one. */
#define REAL(i, type) ((type)real[i])

static HRESULT STDMETHODCALLTYPE t_set_fvf(IDirect3DDevice9 *d, DWORD fvf)
{
    T.calls[89]++;
    g_fvf = fvf;
    return REAL(89, HRESULT(STDMETHODCALLTYPE *)(IDirect3DDevice9 *, DWORD))(d, fvf);
}

static HRESULT STDMETHODCALLTYPE t_set_vs(IDirect3DDevice9 *d, IDirect3DVertexShader9 *s)
{
    T.calls[92]++;
    g_shader = s != NULL;
    return REAL(92, HRESULT(STDMETHODCALLTYPE *)(IDirect3DDevice9 *, IDirect3DVertexShader9 *))(d, s);
}

static HRESULT STDMETHODCALLTYPE t_set_decl(IDirect3DDevice9 *d, IDirect3DVertexDeclaration9 *v)
{
    T.calls[87]++;
    g_decl = v != NULL;
    return REAL(87, HRESULT(STDMETHODCALLTYPE *)(IDirect3DDevice9 *, IDirect3DVertexDeclaration9 *))(d, v);
}

static HRESULT STDMETHODCALLTYPE t_set_ps(IDirect3DDevice9 *d, IDirect3DPixelShader9 *s)
{
    T.calls[107]++;
    return REAL(107, HRESULT(STDMETHODCALLTYPE *)(IDirect3DDevice9 *, IDirect3DPixelShader9 *))(d, s);
}

/* What a draw's vertices are: its declaration's position usage, and the stream's buffer (its pool, its usage). */
static void describe_draw(IDirect3DDevice9 *d, const char *what)
{
    static int shown;
    if (shown >= 6)
        return;
    IDirect3DVertexDeclaration9 *decl = NULL;
    D3DVERTEXELEMENT9 el[MAXD3DDECLLENGTH + 1];
    UINT n = 0;
    int usage = -1;
    if (SUCCEEDED(IDirect3DDevice9_GetVertexDeclaration(d, &decl)) && decl) {
        n = MAXD3DDECLLENGTH + 1;
        if (SUCCEEDED(IDirect3DVertexDeclaration9_GetDeclaration(decl, el, &n)))
            for (UINT i = 0; i < n && el[i].Stream != 0xff; i++)
                if (el[i].Usage == D3DDECLUSAGE_POSITION || el[i].Usage == D3DDECLUSAGE_POSITIONT)
                    usage = el[i].Usage;
        IDirect3DVertexDeclaration9_Release(decl);
    }
    IDirect3DVertexBuffer9 *vb = NULL;
    UINT offset = 0, stride = 0;
    D3DVERTEXBUFFER_DESC vd;
    memset(&vd, 0, sizeof vd);
    if (SUCCEEDED(IDirect3DDevice9_GetStreamSource(d, 0, &vb, &offset, &stride)) && vb) {
        IDirect3DVertexBuffer9_GetDesc(vb, &vd);
        IDirect3DVertexBuffer9_Release(vb);
    }
    IDirect3DVertexShader9 *vs = NULL;
    int has_vs = SUCCEEDED(IDirect3DDevice9_GetVertexShader(d, &vs)) && vs;
    if (vs)
        IDirect3DVertexShader9_Release(vs);
    DWORD fvf = 0;
    IDirect3DDevice9_GetFVF(d, &fvf);
    ingame_log("trace: %s: declaration position usage %d (0 POSITION, 9 POSITIONT), fvf 0x%lx, vertex shader %d, buffer "
               "pool %d usage 0x%lx stride %u", what, usage, (unsigned long)fvf, has_vs, vd.Pool,
               (unsigned long)vd.Usage, stride);
    shown++;
}

static HRESULT STDMETHODCALLTYPE t_dp(IDirect3DDevice9 *d, D3DPRIMITIVETYPE t, UINT a, UINT b)
{
    T.calls[81]++;
    seq_draw(d, "DrawPrimitive", b);
    describe_draw(d, "DrawPrimitive");
    drawn_on(d);
    draw_state(d);
    return REAL(81, HRESULT(STDMETHODCALLTYPE *)(IDirect3DDevice9 *, D3DPRIMITIVETYPE, UINT, UINT))(d, t, a, b);
}

static HRESULT STDMETHODCALLTYPE t_dip(IDirect3DDevice9 *d, D3DPRIMITIVETYPE t, INT a, UINT b, UINT c, UINT e, UINT f)
{
    T.calls[82]++;
    seq_draw(d, "DrawIndexedPrimitive", c);
    drawn_on(d);
    return REAL(82, HRESULT(STDMETHODCALLTYPE *)(IDirect3DDevice9 *, D3DPRIMITIVETYPE, INT, UINT, UINT, UINT, UINT))(
        d, t, a, b, c, e, f);
}

static HRESULT STDMETHODCALLTYPE t_dpup(IDirect3DDevice9 *d, D3DPRIMITIVETYPE t, UINT n, const void *v, UINT stride)
{
    T.calls[83]++;
    seq_draw(d, "DrawPrimitiveUP", n);
    drawn_on(d);
    draw_state(d);
    static int shown;
    /* The first few pre-transformed draws: their first vertex and stride, to see their coordinates' range. */
    if ((g_fvf & D3DFVF_POSITION_MASK) == D3DFVF_XYZRHW && shown < 6 && v) {
        const float *f = v;
        ingame_log("trace: DrawPrimitiveUP XYZRHW stride %u first vertex %.1f %.1f %.3f %.3f", stride, f[0], f[1],
                   f[2], f[3]);
        shown++;
    }
    return REAL(83, HRESULT(STDMETHODCALLTYPE *)(IDirect3DDevice9 *, D3DPRIMITIVETYPE, UINT, const void *, UINT))(
        d, t, n, v, stride);
}

static HRESULT STDMETHODCALLTYPE t_dipup(IDirect3DDevice9 *d, D3DPRIMITIVETYPE t, UINT a, UINT b, UINT c,
                                         const void *i, D3DFORMAT f, const void *v, UINT s)
{
    T.calls[84]++;
    drawn_on(d);
    return REAL(84, HRESULT(STDMETHODCALLTYPE *)(IDirect3DDevice9 *, D3DPRIMITIVETYPE, UINT, UINT, UINT, const void *,
                                                 D3DFORMAT, const void *, UINT))(d, t, a, b, c, i, f, v, s);
}

static HRESULT STDMETHODCALLTYPE t_set_transform(IDirect3DDevice9 *d, D3DTRANSFORMSTATETYPE s, const D3DMATRIX *m)
{
    T.calls[44]++;
    static int shown;
    /* The first projections: an orthographic one for 1280x768 would have 2/1280 and 2/768 on its diagonal. */
    if (s == D3DTS_PROJECTION && m && shown < 4) {
        ingame_log("trace: projection %.5f %.5f %.5f %.5f / %.5f %.5f", m->_11, m->_22, m->_33, m->_44, m->_41, m->_42);
        shown++;
    }
    return REAL(44, HRESULT(STDMETHODCALLTYPE *)(IDirect3DDevice9 *, D3DTRANSFORMSTATETYPE, const D3DMATRIX *))(d, s, m);
}

static HRESULT STDMETHODCALLTYPE t_set_viewport(IDirect3DDevice9 *d, const D3DVIEWPORT9 *v)
{
    T.calls[47]++;
    static int shown;
    if (v && shown < 8) {
        ingame_log("trace: viewport %lu %lu %lux%lu", (unsigned long)v->X, (unsigned long)v->Y,
                   (unsigned long)v->Width, (unsigned long)v->Height);
        shown++;
    }
    return REAL(47, HRESULT(STDMETHODCALLTYPE *)(IDirect3DDevice9 *, const D3DVIEWPORT9 *))(d, v);
}

static HRESULT STDMETHODCALLTYPE t_scissor(IDirect3DDevice9 *d, const RECT *r)
{
    T.calls[75]++;
    return REAL(75, HRESULT(STDMETHODCALLTYPE *)(IDirect3DDevice9 *, const RECT *))(d, r);
}

static HRESULT STDMETHODCALLTYPE t_set_rt(IDirect3DDevice9 *d, DWORD i, IDirect3DSurface9 *s)
{
    T.calls[37]++;
    if (in_sequence()) {
        D3DSURFACE_DESC desc;
        memset(&desc, 0, sizeof desc);
        if (s)
            IDirect3DSurface9_GetDesc(s, &desc);
        ingame_log("seq %ld: SetRenderTarget %lu %p %ux%u usage 0x%lx", (long)g_frame_no, (unsigned long)i, (void *)s,
                   desc.Width, desc.Height, (unsigned long)desc.Usage);
    }
    static int shown;
    if (s && shown < 8) {
        D3DSURFACE_DESC desc;
        if (SUCCEEDED(IDirect3DSurface9_GetDesc(s, &desc)))
            ingame_log("trace: SetRenderTarget %lu %ux%u format %d", (unsigned long)i, desc.Width, desc.Height,
                       desc.Format);
        shown++;
    }
    return REAL(37, HRESULT(STDMETHODCALLTYPE *)(IDirect3DDevice9 *, DWORD, IDirect3DSurface9 *))(d, i, s);
}

static HRESULT STDMETHODCALLTYPE t_create_texture(IDirect3DDevice9 *d, UINT w, UINT h, UINT levels, DWORD usage,
                                                  D3DFORMAT f, D3DPOOL p, IDirect3DTexture9 **t, HANDLE *sh)
{
    T.calls[23]++;
    /* Render targets and dynamic textures (a video's frames would come through one) are worth naming. */
    if (usage & (D3DUSAGE_RENDERTARGET | D3DUSAGE_DYNAMIC))
        ingame_log("trace: CreateTexture %ux%u usage 0x%lx format %d pool %d", w, h, (unsigned long)usage, f, p);
    return REAL(23, HRESULT(STDMETHODCALLTYPE *)(IDirect3DDevice9 *, UINT, UINT, UINT, DWORD, D3DFORMAT, D3DPOOL,
                                                 IDirect3DTexture9 **, HANDLE *))(d, w, h, levels, usage, f, p, t, sh);
}

static HRESULT STDMETHODCALLTYPE t_create_rt(IDirect3DDevice9 *d, UINT w, UINT h, D3DFORMAT f, D3DMULTISAMPLE_TYPE m,
                                             DWORD q, BOOL l, IDirect3DSurface9 **s, HANDLE *sh)
{
    T.calls[28]++;
    ingame_log("trace: CreateRenderTarget %ux%u format %d", w, h, f);
    return REAL(28, HRESULT(STDMETHODCALLTYPE *)(IDirect3DDevice9 *, UINT, UINT, D3DFORMAT, D3DMULTISAMPLE_TYPE, DWORD,
                                                 BOOL, IDirect3DSurface9 **, HANDLE *))(d, w, h, f, m, q, l, s, sh);
}

static HRESULT STDMETHODCALLTYPE t_create_ds(IDirect3DDevice9 *d, UINT w, UINT h, D3DFORMAT f, D3DMULTISAMPLE_TYPE m,
                                             DWORD q, BOOL l, IDirect3DSurface9 **s, HANDLE *sh)
{
    T.calls[29]++;
    ingame_log("trace: CreateDepthStencilSurface %ux%u format %d", w, h, f);
    return REAL(29, HRESULT(STDMETHODCALLTYPE *)(IDirect3DDevice9 *, UINT, UINT, D3DFORMAT, D3DMULTISAMPLE_TYPE, DWORD,
                                                 BOOL, IDirect3DSurface9 **, HANDLE *))(d, w, h, f, m, q, l, s, sh);
}

static HRESULT STDMETHODCALLTYPE t_stretch(IDirect3DDevice9 *d, IDirect3DSurface9 *a, const RECT *ra,
                                           IDirect3DSurface9 *b, const RECT *rb, D3DTEXTUREFILTERTYPE f)
{
    T.calls[34]++;
    if (in_sequence())
        ingame_log("seq %ld: StretchRect %p -> %p filter %d", (long)g_frame_no, (void *)a, (void *)b, f);
    static int shown;
    /* The first copies: their rectangles and the surfaces' sizes. */
    if (shown < 6) {
        D3DSURFACE_DESC da, db;
        memset(&da, 0, sizeof da);
        memset(&db, 0, sizeof db);
        if (a)
            IDirect3DSurface9_GetDesc(a, &da);
        if (b)
            IDirect3DSurface9_GetDesc(b, &db);
        ingame_log("trace: StretchRect %ux%u %s -> %ux%u %s, filter %d", da.Width, da.Height, ra ? "with a rectangle" : "whole",
                   db.Width, db.Height, rb ? "with a rectangle" : "whole", f);
        if (ra)
            ingame_log("trace:   source %ld %ld %ld %ld", ra->left, ra->top, ra->right, ra->bottom);
        if (rb)
            ingame_log("trace:   target %ld %ld %ld %ld", rb->left, rb->top, rb->right, rb->bottom);
        shown++;
    }
    return REAL(34, HRESULT(STDMETHODCALLTYPE *)(IDirect3DDevice9 *, IDirect3DSurface9 *, const RECT *,
                                                 IDirect3DSurface9 *, const RECT *, D3DTEXTUREFILTERTYPE))(d, a, ra, b,
                                                                                                         rb, f);
}

static HRESULT STDMETHODCALLTYPE t_clear(IDirect3DDevice9 *d, DWORD n, const D3DRECT *r, DWORD fl, D3DCOLOR c, float z,
                                         DWORD s)
{
    T.calls[43]++;
    if (in_sequence())
        ingame_log("seq %ld: Clear flags 0x%lx colour 0x%08lx rects %lu", (long)g_frame_no, (unsigned long)fl,
                   (unsigned long)c, (unsigned long)n);
    return REAL(43, HRESULT(STDMETHODCALLTYPE *)(IDirect3DDevice9 *, DWORD, const D3DRECT *, DWORD, D3DCOLOR, float,
                                                 DWORD))(d, n, r, fl, c, z, s);
}

static HRESULT STDMETHODCALLTYPE t_update_texture(IDirect3DDevice9 *d, IDirect3DBaseTexture9 *a,
                                                  IDirect3DBaseTexture9 *b)
{
    T.calls[31]++;
    return REAL(31, HRESULT(STDMETHODCALLTYPE *)(IDirect3DDevice9 *, IDirect3DBaseTexture9 *,
                                                 IDirect3DBaseTexture9 *))(d, a, b);
}

static HRESULT STDMETHODCALLTYPE t_set_ds(IDirect3DDevice9 *d, IDirect3DSurface9 *s)
{
    T.calls[39]++;
    if (in_sequence())
        ingame_log("seq %ld: SetDepthStencilSurface %p", (long)g_frame_no, (void *)s);
    return REAL(39, HRESULT(STDMETHODCALLTYPE *)(IDirect3DDevice9 *, IDirect3DSurface9 *))(d, s);
}

/* The getters a game uses to find its back buffer and depth surface: the first calls of each, with what came back. */
static HRESULT STDMETHODCALLTYPE t_get_bb(IDirect3DDevice9 *d, UINT c, UINT i, D3DBACKBUFFER_TYPE t,
                                          IDirect3DSurface9 **s)
{
    T.calls[18]++;
    HRESULT hr = REAL(18, HRESULT(STDMETHODCALLTYPE *)(IDirect3DDevice9 *, UINT, UINT, D3DBACKBUFFER_TYPE,
                                                       IDirect3DSurface9 **))(d, c, i, t, s);
    static int shown;
    if (shown++ < 6 || in_sequence())
        ingame_log("trace: GetBackBuffer %u %u -> %p", c, i, s ? (void *)*s : NULL);
    return hr;
}

static HRESULT STDMETHODCALLTYPE t_get_rt(IDirect3DDevice9 *d, DWORD i, IDirect3DSurface9 **s)
{
    T.calls[38]++;
    HRESULT hr = REAL(38, HRESULT(STDMETHODCALLTYPE *)(IDirect3DDevice9 *, DWORD, IDirect3DSurface9 **))(d, i, s);
    static int shown;
    if (shown++ < 6 || in_sequence())
        ingame_log("trace: GetRenderTarget %lu -> %p", (unsigned long)i, s ? (void *)*s : NULL);
    return hr;
}

static HRESULT STDMETHODCALLTYPE t_get_ds(IDirect3DDevice9 *d, IDirect3DSurface9 **s)
{
    T.calls[40]++;
    HRESULT hr = REAL(40, HRESULT(STDMETHODCALLTYPE *)(IDirect3DDevice9 *, IDirect3DSurface9 **))(d, s);
    static int shown;
    if (shown++ < 6 || in_sequence())
        ingame_log("trace: GetDepthStencilSurface -> %p", s ? (void *)*s : NULL);
    return hr;
}

static HRESULT STDMETHODCALLTYPE t_get_swap(IDirect3DDevice9 *d, UINT i, IDirect3DSwapChain9 **s)
{
    T.calls[14]++;
    static int shown;
    if (shown++ < 6)
        ingame_log("trace: GetSwapChain %u", i);
    return REAL(14, HRESULT(STDMETHODCALLTYPE *)(IDirect3DDevice9 *, UINT, IDirect3DSwapChain9 **))(d, i, s);
}

/* Put one traced method in the device's table, keeping the real one. */
static void put(IDirect3DDevice9 *dev, int index, void *ours)
{
    void **table = *(void ***)dev;
    if (table[index] == ours)
        return;
    real[index] = table[index];
    DWORD old;
    if (VirtualProtect(&table[index], sizeof(void *), PAGE_READWRITE, &old)) {
        table[index] = ours;
        VirtualProtect(&table[index], sizeof(void *), old, &old);
    }
}

void trace_attach(void *device, const void *parameters, DWORD flags)
{
    IDirect3DDevice9 *dev = device;
    const D3DPRESENT_PARAMETERS *pp = parameters;
    char value[16];
    if (!GetEnvironmentVariableA("OPENDMT3_INGAME_TRACE", value, sizeof value))
        return;
    /* "sequence": two frames' calls written one by one as well. */
    g_sequence = !strcmp(value, "sequence");
    if (pp)
        ingame_log("trace: device: back buffer %ux%u format %d count %u, windowed %d, swap effect %d, interval 0x%lx, "
                   "auto depth %d (format %d), flags 0x%lx, refresh %u",
                   pp->BackBufferWidth, pp->BackBufferHeight, pp->BackBufferFormat, pp->BackBufferCount, pp->Windowed,
                   pp->SwapEffect, (unsigned long)pp->PresentationInterval, pp->EnableAutoDepthStencil,
                   pp->AutoDepthStencilFormat, (unsigned long)flags, pp->FullScreen_RefreshRateInHz);
    put(dev, 14, (void *)t_get_swap);
    put(dev, 18, (void *)t_get_bb);
    put(dev, 38, (void *)t_get_rt);
    put(dev, 39, (void *)t_set_ds);
    put(dev, 40, (void *)t_get_ds);
    put(dev, 23, (void *)t_create_texture);
    put(dev, 28, (void *)t_create_rt);
    put(dev, 29, (void *)t_create_ds);
    put(dev, 31, (void *)t_update_texture);
    put(dev, 34, (void *)t_stretch);
    put(dev, 37, (void *)t_set_rt);
    put(dev, 43, (void *)t_clear);
    put(dev, 44, (void *)t_set_transform);
    put(dev, 47, (void *)t_set_viewport);
    put(dev, 75, (void *)t_scissor);
    put(dev, 81, (void *)t_dp);
    put(dev, 82, (void *)t_dip);
    put(dev, 83, (void *)t_dpup);
    put(dev, 84, (void *)t_dipup);
    put(dev, 87, (void *)t_set_decl);
    put(dev, 89, (void *)t_set_fvf);
    put(dev, 92, (void *)t_set_vs);
    put(dev, 107, (void *)t_set_ps);
}

void trace_frame(void)
{
    /* Counted at each present; summed up every 300 frames. */
    if (!real[89])
        return;
    g_frame_no++;
    if (in_sequence())
        ingame_log("seq %ld: Present", (long)g_frame_no - 1);
    if (++T.frames >= 300)
        summary();
}
