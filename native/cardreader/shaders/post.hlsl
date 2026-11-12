/*
 * openDMT3's post-process passes (post.c), Direct3D 9 shader model 3.0, compiled when the game starts by the game's
 * own D3DX (D3DXCompileShader), one entry point a pass. Each pass draws one triangle over its whole target and works
 * from the pixel's own position (VPOS), so no texture coordinate is interpolated and Direct3D 9's half-pixel offset
 * never comes into it.
 *
 * The filters are written from their published sources' maths, in floats: shader model 3.0 has no integer or bit
 * operations, so where those sources use a bit trick (FSR 1's fast reciprocals) it is worked out in floats to the
 * same value (bits_of and float_of below).
 *   - easu, rcas: AMD FidelityFX Super Resolution 1 (ffx_fsr1.h, MIT, Copyright (c) 2021 Advanced Micro Devices).
 *   - nis_edges, nis_scale: NVIDIA Image Scaling's NVScaler (NIS_Scaler.h, MIT, Copyright (c) 2022 NVIDIA), as a
 *     pixel shader: its compute shader's shared tiles become an edge map pass and texture reads.
 *   - fxaa: FXAA 3.11 Quality by Timothy Lottes (NVIDIA), its preset 39.
 * Their licence texts are in native/cardreader/third_party/.
 *
 * Constants every pass gets: c0 the input's size (w, h, 1/w, 1/h), c1 the output's; c2 on are each pass's own.
 */

float4 c_in : register(c0);
float4 c_out : register(c1);
float4 c_p2 : register(c2);
float4 c_p3 : register(c3);
float4 c_p4 : register(c4);
float4 c_p5 : register(c5);
float4 c_p6 : register(c6);
float4 c_p7 : register(c7);
/* The picture's top left in the window's back buffer (pixels): the bars' width or height when the game's shape is
 * kept, 0 when it fills the window. Taken off the pixel's position by the passes that draw into the back buffer. */
float4 c_origin : register(c8);

/* The samplers; post.c sets each one's filter for the pass (point or bilinear), always clamped at the edges. */
sampler2D s0 : register(s0);
sampler2D s1 : register(s1);
sampler2D s2 : register(s2);
sampler2D s3 : register(s3);
sampler2D s4 : register(s4);

/* The one vertex shader: the triangle's corners come already in clip space. */
float4 vs_main(float4 pos : POSITION) : POSITION
{
    return pos;
}

/* A texel's colour at a normalised position, no mipmaps. */
float4 fetch(sampler2D s, float2 uv)
{
    return tex2Dlod(s, float4(uv, 0.0, 0.0));
}

/* The centre of this pixel of the target, in its normalised coordinates (VPOS is the pixel's corner on Direct3D 9;
 * floor keeps it so on a driver that gives the centre). */
float2 centre_uv(float2 vpos, float4 size)
{
    return (floor(vpos) + 0.5) * size.zw;
}

/* ------------------------------------------------------------------------------------------------ plain copies */

/* Bilinear: the input read at the output pixel's centre mapped onto it, with the sampler's linear filter. */
float4 ps_copy(float2 vpos : VPOS) : COLOR
{
    return float4(fetch(s0, centre_uv(vpos - c_origin.xy, c_out)).rgb, 1.0);
}

/* "Off", sharp bilinear: each game pixel a box of the same width on the screen (output over input pixels: 1.40625 at
 * 1080 lines), the screen pixel on a box's edge mixing the two by how much of it each covers. Nearest alone gave half
 * the game's columns 1 screen pixel and half 2 at 1920 across. A screen pixel wholly inside a game pixel reads its
 * centre; whole multiples of the size are nearest itself. Same mapping as bilinear: no shift of the picture against
 * it. s0 bilinear; postmath.c sharp_coord is the same sums, checked by the native tests. */
float4 ps_nearest(float2 vpos : VPOS) : COLOR
{
    /* Screen pixels to a game pixel, and this pixel's centre in game pixels. */
    float2 scale = c_out.xy * c_in.zw;
    float2 t = (floor(vpos) - c_origin.xy + 0.5) * c_in.xy * c_out.zw;
    /* Its game pixel, and how far from that pixel's centre; within `range` of it the screen pixel lies wholly inside. */
    float2 base = floor(t), centre = t - base - 0.5;
    float2 range = max(0.5 - 0.5 / scale, 0.0);
    /* Read at the centre there; past it, towards the next game pixel by the share of the screen pixel over the edge. */
    float2 c = base + (centre - clamp(centre, -range, range)) * scale + 0.5;
    return float4(fetch(s0, c * c_in.zw).rgb, 1.0);
}

/* ---------------------------------------------------------------------------------- FSR 1's float bit tricks */

/* A positive float's bits as Windows would read them as an unsigned integer, divided by 2^23: its biased exponent plus
 * its mantissa's fraction. What asuint() gives ffx_a.h's approximations, in floats. */
float bits_of(float a)
{
    float e = floor(log2(a));
    float m = a * exp2(-e);
    /* log2 may land a hair off at exact powers of two: the mantissa says which side it really is. */
    if (m >= 2.0) { m *= 0.5; e += 1.0; }
    if (m < 1.0) { m *= 2.0; e -= 1.0; }
    return e + 127.0 + (m - 1.0);
}

/* The other way: bits (divided by 2^23) back to the float they spell. */
float float_of(float b)
{
    float e = floor(b);
    return (1.0 + (b - e)) * exp2(e - 127.0);
}

/* The smallest normal float: zero's bit pattern spells it closely enough (the tricks give a huge number either way). */
#define TINY 1.17549435e-38

/* ffx_a.h APrxLoRcpF1: 0x7ef07ebb less the bits. */
float rcp_lo(float a)
{
    return float_of(2129690299.0 / 8388608.0 - bits_of(max(a, TINY)));
}

/* ffx_a.h APrxLoRsqF1: 0x5f347d74 less half the bits. */
float rsq_lo(float a)
{
    return float_of(1597275508.0 / 8388608.0 - 0.5 * bits_of(max(a, TINY)));
}

/* ffx_a.h APrxMedRcpF1: 0x7ef19fff less the bits, then one Newton step. */
float rcp_med(float a)
{
    float b = float_of(2129764351.0 / 8388608.0 - bits_of(max(a, TINY)));
    return b * (-b * a + 2.0);
}

/* --------------------------------------------------------------------------------------------- FSR 1: EASU */

/* FsrEasuSetF's lengths for one texel, before its bilinear weight: from its '+' of lumas (lA above, lB left, lC itself,
 * lD right, lE below), the length across and the length down, squared; each takes the magnitude from both sides of the
 * centre, turning a reversal of the gradient to 0. They depend on the texel alone, and each takes one of FSR's
 * bit-trick reciprocals (a log2 and two exp2 in shader model 3.0), so ps_easu_len works them out once a texel of the
 * game's picture, where FsrEasuF did so again for each of the four corners of every output pixel (four times for each
 * texel at 1080 lines, sixteen at 2160). The directions, two differences, stay in FsrEasuF. */
float2 easu_len_of(float lA, float lB, float lC, float lD, float lE)
{
    float dc = lD - lC;
    float cb = lC - lB;
    float lenX = max(abs(dc), abs(cb));
    lenX = rcp_lo(lenX);
    float dirX = lD - lB;
    lenX = saturate(abs(dirX) * lenX);
    lenX *= lenX;
    float ec = lE - lC;
    float ca = lC - lA;
    float lenY = max(abs(ec), abs(ca));
    lenY = rcp_lo(lenY);
    float dirY = lE - lA;
    lenY = saturate(abs(dirY) * lenY);
    lenY *= lenY;
    return float2(lenX, lenY);
}

/* FsrEasuSetF: one of the four bilinear corners' direction, the '+' differences of its lumas (lA above, lB left, lD
 * right, lE below), and its lengths (ps_easu_len's), each by its bilinear weight, in FsrEasuSetF's order. */
void easu_set(inout float2 dir, inout float len, float w, float lA, float lB, float lD, float lE, float2 l)
{
    dir.x += (lD - lB) * w;
    len += l.x * w;
    dir.y += (lE - lA) * w;
    len += l.y * w;
}

/* FsrEasuTapF: one tap's weight from its offset rotated into the edge's direction, an approximation of Lanczos 2. */
void easu_tap(inout float3 aC, inout float aW, float2 off, float2 dir, float2 len, float lob, float clp, float3 c)
{
    float2 v;
    v.x = (off.x * (dir.x)) + (off.y * dir.y);
    v.y = (off.x * (-dir.y)) + (off.y * dir.x);
    /* Anisotropy, then the distance squared, limited to the window. */
    v *= len;
    float d2 = v.x * v.x + v.y * v.y;
    d2 = min(d2, clp);
    /* (25/16 * (2/5 * x^2 - 1)^2 - (25/16 - 1)) * (lob * x^2 - 1)^2 */
    float wB = (2.0 / 5.0) * d2 + -1.0;
    float wA = lob * d2 + -1.0;
    wB *= wB;
    wA *= wA;
    wB = (25.0 / 16.0) * wB + (-(25.0 / 16.0 - 1.0));
    float w = wB * wA;
    aC += c * w;
    aW += w;
}

/* FSR's luma times two: b/2 + (r/2 + g). */
float easu_luma(float3 c)
{
    return c.b * 0.5 + (c.r * 0.5 + c.g);
}

/* EASU's lengths for every texel of the game's picture (s0, point filter), into two 32-bit floats a texel (the numbers
 * kept exactly), a texel larger than the picture on every side: texel (x, y) holds the game's texel (x - 1, y - 1), so
 * the border texels EASU's clamped reads reach have their own, of reads clamped as FsrEasuF's are. */
float4 ps_easu_len(float2 vpos : VPOS) : COLOR
{
    float2 t = c_in.zw;
    float2 c = (floor(vpos) - 1.0 + 0.5) * t;
    float lA = easu_luma(fetch(s0, c + float2(0.0, -1.0) * t).rgb);
    float lB = easu_luma(fetch(s0, c + float2(-1.0, 0.0) * t).rgb);
    float lC = easu_luma(fetch(s0, c).rgb);
    float lD = easu_luma(fetch(s0, c + float2(1.0, 0.0) * t).rgb);
    float lE = easu_luma(fetch(s0, c + float2(0.0, 1.0) * t).rgb);
    return float4(easu_len_of(lA, lB, lC, lD, lE), 0.0, 0.0);
}

/* FsrEasuF. c2 holds con0 (the output pixel to input position scale and offset); the input's texel size is c0.zw; s1
 * ps_easu_len's lengths (point filter), their texel size in c3.zw. */
float4 ps_easu(float2 vpos : VPOS) : COLOR
{
    float2 ip = floor(vpos);
    /* The position of 'f', the tap at or before this pixel's centre, and how far past it the centre is. */
    float2 pp = ip * c_p2.xy + c_p2.zw;
    float2 fp = floor(pp);
    pp -= fp;
    /* The 12 taps around it, by their texel centres (the source reads them as four gathers of four):
     *    b c
     *  e f g h
     *  i j k l
     *    n o      */
    float2 t = c_in.zw;
    float2 f0 = (fp + 0.5) * t;
    float3 b = fetch(s0, f0 + float2(0.0, -1.0) * t).rgb;
    float3 c = fetch(s0, f0 + float2(1.0, -1.0) * t).rgb;
    float3 e = fetch(s0, f0 + float2(-1.0, 0.0) * t).rgb;
    float3 f = fetch(s0, f0).rgb;
    float3 g = fetch(s0, f0 + float2(1.0, 0.0) * t).rgb;
    float3 h = fetch(s0, f0 + float2(2.0, 0.0) * t).rgb;
    float3 i = fetch(s0, f0 + float2(-1.0, 1.0) * t).rgb;
    float3 j = fetch(s0, f0 + float2(0.0, 1.0) * t).rgb;
    float3 k = fetch(s0, f0 + float2(1.0, 1.0) * t).rgb;
    float3 l = fetch(s0, f0 + float2(2.0, 1.0) * t).rgb;
    float3 n = fetch(s0, f0 + float2(0.0, 2.0) * t).rgb;
    float3 o = fetch(s0, f0 + float2(1.0, 2.0) * t).rgb;
    float bL = easu_luma(b), cL = easu_luma(c), eL = easu_luma(e), fL = easu_luma(f);
    float gL = easu_luma(g), hL = easu_luma(h), iL = easu_luma(i), jL = easu_luma(j);
    float kL = easu_luma(k), lL = easu_luma(l), nL = easu_luma(n), oL = easu_luma(o);
    /* The four corners f, g, j, k's lengths (one texel further in their texture, for its border). */
    float2 u = c_p3.zw;
    float2 d0 = (fp + 1.5) * u;
    float2 lf = fetch(s1, d0).rg;
    float2 lg = fetch(s1, d0 + float2(1.0, 0.0) * u).rg;
    float2 lj = fetch(s1, d0 + float2(0.0, 1.0) * u).rg;
    float2 lk = fetch(s1, d0 + float2(1.0, 1.0) * u).rg;
    /* Direction and length, accumulated over the four corners with their bilinear weights. */
    float2 dir = float2(0.0, 0.0);
    float len = 0.0;
    easu_set(dir, len, (1.0 - pp.x) * (1.0 - pp.y), bL, eL, gL, jL, lf);
    easu_set(dir, len, pp.x * (1.0 - pp.y), cL, fL, hL, kL, lg);
    easu_set(dir, len, (1.0 - pp.x) * pp.y, fL, iL, kL, nL, lj);
    easu_set(dir, len, pp.x * pp.y, gL, jL, lL, oL, lk);
    /* Normalise the direction (with its approximation), and clean up close to zero. */
    float2 dir2 = dir * dir;
    float dirR = dir2.x + dir2.y;
    bool zro = dirR < (1.0 / 32768.0);
    dirR = rsq_lo(dirR);
    dirR = zro ? 1.0 : dirR;
    dir.x = zro ? 1.0 : dir.x;
    dir *= dirR;
    /* Length from {0 to 2} to {0 to 1}, shaped with a square. */
    len = len * 0.5;
    len *= len;
    /* Stretch the kernel from 1 on vertical and horizontal edges to sqrt(2) on diagonals. */
    float stretch = (dir.x * dir.x + dir.y * dir.y) * rcp_lo(max(abs(dir.x), abs(dir.y)));
    float2 len2 = float2(1.0 + (stretch - 1.0) * len, 1.0 + -0.5 * len);
    /* The negative lobe and the window's end move with the amount of edge. */
    float lob = 0.5 + ((1.0 / 4.0 - 0.04) - 0.5) * len;
    float clp = rcp_lo(lob);
    /* The four nearest's minimum and maximum, to keep the result from ringing past them. */
    float3 min4 = min(min(min(f, g), j), k);
    float3 max4 = max(max(max(f, g), j), k);
    float3 aC = float3(0.0, 0.0, 0.0);
    float aW = 0.0;
    easu_tap(aC, aW, float2(0.0, -1.0) - pp, dir, len2, lob, clp, b);
    easu_tap(aC, aW, float2(1.0, -1.0) - pp, dir, len2, lob, clp, c);
    easu_tap(aC, aW, float2(-1.0, 1.0) - pp, dir, len2, lob, clp, i);
    easu_tap(aC, aW, float2(0.0, 1.0) - pp, dir, len2, lob, clp, j);
    easu_tap(aC, aW, float2(0.0, 0.0) - pp, dir, len2, lob, clp, f);
    easu_tap(aC, aW, float2(-1.0, 0.0) - pp, dir, len2, lob, clp, e);
    easu_tap(aC, aW, float2(1.0, 1.0) - pp, dir, len2, lob, clp, k);
    easu_tap(aC, aW, float2(2.0, 1.0) - pp, dir, len2, lob, clp, l);
    easu_tap(aC, aW, float2(2.0, 0.0) - pp, dir, len2, lob, clp, h);
    easu_tap(aC, aW, float2(1.0, 0.0) - pp, dir, len2, lob, clp, g);
    easu_tap(aC, aW, float2(1.0, 2.0) - pp, dir, len2, lob, clp, o);
    easu_tap(aC, aW, float2(0.0, 2.0) - pp, dir, len2, lob, clp, n);
    /* Normalise and dering. */
    return float4(min(max4, max(min4, aC * (1.0 / aW))), 1.0);
}

/* --------------------------------------------------------------------------------------------- FSR 1: RCAS */

/* RCAS's limit, at the edge of unnatural sharpening. */
#define FSR_RCAS_LIMIT (0.25 - (1.0 / 16.0))

/* FsrRcasF on EASU's result (s0, point filter); c2.x is FsrRcasCon's constant, c3 the EASU texture's size (EASU filled
 * its top-left at the output's size, so its pixels are this pass's pixels). */
float4 ps_rcas(float2 vpos : VPOS) : COLOR
{
    float2 uv = centre_uv(vpos - c_origin.xy, c_p3);
    float2 t = c_p3.zw;
    /*    b
     *  d e f
     *    h      */
    float3 b = fetch(s0, uv + float2(0.0, -1.0) * t).rgb;
    float3 d = fetch(s0, uv + float2(-1.0, 0.0) * t).rgb;
    float3 e = fetch(s0, uv).rgb;
    float3 f = fetch(s0, uv + float2(1.0, 0.0) * t).rgb;
    float3 h = fetch(s0, uv + float2(0.0, 1.0) * t).rgb;
    /* The ring's minimum and maximum, a channel at a time. */
    float3 mn4 = min(min(min(b, d), f), h);
    float3 mx4 = max(max(max(b, d), f), h);
    /* Where the result would clip at 0 and at 1; the larger negative lobe that clips neither. The source calls for
     * high precision reciprocals here; a zero denominator only happens when its numerator is zero too. */
    float2 peakC = float2(1.0, -1.0 * 4.0);
    float3 hitMin = min(mn4, e) / max(4.0 * mx4, TINY);
    float3 hitMax = (peakC.x - max(mx4, e)) / (4.0 * mn4 + peakC.y);
    float3 lobeRGB = max(-hitMin, hitMax);
    float lobe = max(-FSR_RCAS_LIMIT, min(max(max(lobeRGB.r, lobeRGB.g), lobeRGB.b), 0.0)) * c_p2.x;
    /* Resolve with the medium precision reciprocal, as the source does to avoid tonal shifts. */
    float rcpL = rcp_med(4.0 * lobe + 1.0);
    return float4((lobe * b + lobe * d + lobe * h + lobe * f + e) * rcpL, 1.0);
}

/* ------------------------------------------------------------------------------------- NIS: the edge map pass */

/* NIS's luma for SDR input (getY): BT.709's weights. */
float nis_y(float3 c)
{
    return 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b;
}

/* NIS's constants, from nis_config: c2 = scale x, y and the input's texel size; c3 = detect ratio, detect threshold,
 * minimum contrast ratio, ratio norm; c4 = contrast boost, eps, sharp start y, sharp scale y; c5 = sharp strength min
 * and scale, sharp limit min and scale. */
#define kScale c_p2.xy
#define kSrcNorm c_p2.zw
#define kDetectRatio c_p3.x
#define kDetectThres c_p3.y
#define kMinContrastRatio c_p3.z
#define kRatioNorm c_p3.w
#define kContrastBoost c_p4.x
#define kEps c_p4.y
#define kSharpStartY c_p4.z
#define kSharpScaleY c_p4.w
#define kSharpStrengthMin c_p5.x
#define kSharpStrengthScale c_p5.y
#define kSharpLimitMin c_p5.z
#define kSharpLimitScale c_p5.w

/* GetEdgeMap: the weights of the 0, 90, 45 and 135 degree filters for a source pixel, from its 3x3 lumas
 * (p[row][column]). */
float4 nis_edge(float p[3][3])
{
    float g_0 = abs(p[0][0] + p[0][1] + p[0][2] - p[2][0] - p[2][1] - p[2][2]);
    float g_45 = abs(p[1][0] + p[0][0] + p[0][1] - p[2][1] - p[2][2] - p[1][2]);
    float g_90 = abs(p[0][0] + p[1][0] + p[2][0] - p[0][2] - p[1][2] - p[2][2]);
    float g_135 = abs(p[1][0] + p[2][0] + p[2][1] - p[0][1] - p[0][2] - p[1][2]);
    float g_0_90_max = max(g_0, g_90);
    float g_0_90_min = min(g_0, g_90);
    float g_45_135_max = max(g_45, g_135);
    float g_45_135_min = min(g_45, g_135);
    float total = g_0_90_max + g_45_135_max;
    /* No gradient at all: no direction. (The division below is guarded; its result is not used then.) */
    float e_0_90 = min(g_0_90_max / max(total, TINY), 1.0);
    float e_45_135 = 1.0 - e_0_90;
    bool c_0_90 = (g_0_90_max > (g_0_90_min * kDetectRatio)) && (g_0_90_max > kDetectThres) && (g_0_90_max > g_45_135_min);
    bool c_45_135 = (g_45_135_max > (g_45_135_min * kDetectRatio)) && (g_45_135_max > kDetectThres) && (g_45_135_max > g_0_90_min);
    bool c_g_0_90 = g_0_90_max == g_0;
    bool c_g_45_135 = g_45_135_max == g_45;
    float f_e_0_90 = (c_0_90 && c_45_135) ? e_0_90 : 1.0;
    float f_e_45_135 = (c_0_90 && c_45_135) ? e_45_135 : 1.0;
    float weight_0 = (c_0_90 && c_g_0_90) ? f_e_0_90 : 0.0;
    float weight_90 = (c_0_90 && !c_g_0_90) ? f_e_0_90 : 0.0;
    float weight_45 = (c_45_135 && c_g_45_135) ? f_e_45_135 : 0.0;
    float weight_135 = (c_45_135 && !c_g_45_135) ? f_e_45_135 : 0.0;
    return total == 0.0 ? float4(0.0, 0.0, 0.0, 0.0) : float4(weight_0, weight_90, weight_45, weight_135);
}

/* The edge map at the game's size (the compute shader's shEdgeMap), into a two-channel half-float target: s0 the game's
 * picture, point filter. Of each pair of directions at most one has weight (0 or 90 by c_g_0_90, 45 or 135 by
 * c_g_45_135), so each pair is one signed number: the first's weight, or the second's negated (nis_edge_weights reads
 * them back). Half floats as the reference's own half-precision build keeps its edge map; 4 bytes a pixel, where four
 * 32-bit floats took 16. */
float4 ps_nis_edges(float2 vpos : VPOS) : COLOR
{
    float2 uv = centre_uv(vpos, c_in);
    float p[3][3];
    [unroll] for (int r = 0; r < 3; r++)
        [unroll] for (int k = 0; k < 3; k++)
            p[r][k] = nis_y(fetch(s0, uv + float2(k - 1, r - 1) * c_in.zw).rgb);
    float4 e = nis_edge(p);
    return float4(e.x - e.y, e.z - e.w, 0.0, 0.0);
}

/* The four weights (0, 90, 45, 135 degrees) of one texel of the edge map written by ps_nis_edges. */
float4 nis_edge_weights(float2 v)
{
    return float4(max(v.x, 0.0), max(-v.x, 0.0), max(v.y, 0.0), max(-v.y, 0.0));
}

/* ---------------------------------------------------------------------------------------- NIS: the scaler */

/* The filter banks (s2, 4 x 64 floats, point filter): texels 0 and 1 of a row hold coef_scale's six taps of that
 * phase, texels 2 and 3 coef_usm's. */
float4 nis_coef(float column, float phase)
{
    return fetch(s2, float2((column + 0.5) / 4.0, (phase + 0.5) / 64.0));
}

/* CalcLTI: less sharpening where one side of the pixel has much more contrast than the other (ringing). */
float nis_lti(float p0, float p1, float p2, float p3, float p4, float p5, float phase_index)
{
    bool selector = (phase_index <= 64.0 / 2.0);
    float sel = selector ? p0 : p3;
    float a_min = min(min(p1, p2), sel);
    float a_max = max(max(p1, p2), sel);
    sel = selector ? p2 : p5;
    float b_min = min(min(p3, p4), sel);
    float b_max = max(max(p3, p4), sel);
    float a_cont = a_max - a_min;
    float b_cont = b_max - b_min;
    float cont_ratio = max(a_cont, b_cont) / (min(a_cont, b_cont) + kEps);
    return (1.0 - saturate((cont_ratio - kMinContrastRatio) * kRatioNorm)) * kContrastBoost;
}

/* EvalPoly6: six lumas along a direction through the 6-tap scaler, plus their unsharp mask scaled and limited by the
 * luma, its ringing reduced. */
float nis_poly6(float p0, float p1, float p2, float p3, float p4, float p5, float phase)
{
    float4 s_lo = nis_coef(0.0, phase), s_hi = nis_coef(1.0, phase);
    float4 u_lo = nis_coef(2.0, phase), u_hi = nis_coef(3.0, phase);
    float y = s_lo.x * p0 + s_lo.y * p1 + s_lo.z * p2 + s_lo.w * p3 + s_hi.x * p4 + s_hi.y * p5;
    float y_usm = u_lo.x * p0 + u_lo.y * p1 + u_lo.z * p2 + u_lo.w * p3 + u_hi.x * p4 + u_hi.y * p5;
    /* A piece-wise ramp on luma; sharpen as a function of it; limit the mask as a function of it. */
    float y_scale = 1.0 - saturate((y - kSharpStartY) * kSharpScaleY);
    float y_sharpness = y_scale * kSharpStrengthScale + kSharpStrengthMin;
    y_usm *= y_sharpness;
    float y_sharpness_limit = (y_scale * kSharpLimitScale + kSharpLimitMin) * y;
    y_usm = min(y_sharpness_limit, max(-y_sharpness_limit, y_usm));
    y_usm *= nis_lti(p0, p1, p2, p3, p4, p5, phase);
    return y + y_usm;
}

/* FilterNormal's first half, once for each of the game's columns in each of the window's rows (its target: the game's
 * width by the window's height, one 32-bit float a pixel, the sums kept exactly): the six lumas of the column round the
 * row's place in the game, through the 6-tap scaler at the row's phase. NVScaler works this sum out for each of the six
 * columns round every output pixel, from 36 pixels of the game; a column's sum is the same for every pixel of the row
 * that reads it (8 of them at 1080 lines, 17 at 2160), so it is worked out here once and ps_nis_scale reads six sums.
 * s0 the game's picture (point), s2 the filter banks. */
float4 ps_nis_rows(float2 vpos : VPOS) : COLOR
{
    float2 dst = floor(vpos);
    /* The row's place in the game, its integer part and its phase, by ps_nis_scale's own sums (the column's are not
     * used: this pixel is one of the game's columns). */
    float2 src = (0.5 + dst) * kScale - 0.5;
    float2 f0 = floor(src);
    float2 fr = src - f0;
    float2 phase = floor(fr * 64.0);
    float4 sy_lo = nis_coef(0.0, phase.y), sy_hi = nis_coef(1.0, phase.y);
    float cy[6] = {sy_lo.x, sy_lo.y, sy_lo.z, sy_lo.w, sy_hi.x, sy_hi.y};
    /* The column's six lumas from two rows before to three after, as NVScaler's 6x6 has them. */
    float v_acc = 0.0;
    [unroll] for (int ii = 0; ii < 6; ii++)
        v_acc += nis_y(fetch(s0, float2(dst.x + 0.5, f0.y + (ii - 1.5)) * kSrcNorm).rgb) * cy[ii];
    return float4(v_acc, 0.0, 0.0, 0.0);
}

/* One luma of the 6x6 round the pixel, by its column and row there (0 to 5 each; the pixel's own texel is column 2,
 * row 2). */
float nis_at(float2 f0, float k, float r)
{
    return nis_y(fetch(s0, (f0 + float2(k - 1.5, r - 1.5)) * kSrcNorm).rgb);
}

/* NVScaler for one output pixel: s0 the game's picture (point), s1 the edge map (point), s2 the filter banks,
 * s3 the game's picture again with a bilinear filter (for its chroma tap), s4 the columns' sums of ps_nis_rows (point),
 * their texel size in c6.zw. */
float4 ps_nis_scale(float2 vpos : VPOS) : COLOR
{
    float2 dst = floor(vpos) - c_origin.xy;
    /* The input position of this pixel's centre, its integer part, its fraction and the fraction's phase of 64. */
    float2 src = (0.5 + dst) * kScale - 0.5;
    float2 f0 = floor(src);
    float2 fr = src - f0;
    float2 phase = floor(fr * 64.0);
    /* The edge map's four weights around it, bilinear between them. */
    float4 e00 = nis_edge_weights(fetch(s1, (f0 + float2(0.5, 0.5)) * kSrcNorm).xy);
    float4 e01 = nis_edge_weights(fetch(s1, (f0 + float2(1.5, 0.5)) * kSrcNorm).xy);
    float4 e10 = nis_edge_weights(fetch(s1, (f0 + float2(0.5, 1.5)) * kSrcNorm).xy);
    float4 e11 = nis_edge_weights(fetch(s1, (f0 + float2(1.5, 1.5)) * kSrcNorm).xy);
    float4 w = lerp(lerp(e00, e01, fr.x), lerp(e10, e11, fr.x), fr.y);
    float baseWeight = 1.0 - w.x - w.y - w.z - w.w;
    /* FilterNormal's second half: this row's sums of the six columns from two before to three after (ps_nis_rows),
     * through the 6-tap scaler across. */
    float4 sx_lo = nis_coef(0.0, phase.x), sx_hi = nis_coef(1.0, phase.x);
    float cx[6] = {sx_lo.x, sx_lo.y, sx_lo.z, sx_lo.w, sx_hi.x, sx_hi.y};
    float h_acc = 0.0;
    [unroll] for (int jj = 0; jj < 6; jj++)
        h_acc += fetch(s4, float2(f0.x + (jj - 1.5), dst.y + 0.5) * c_p6.zw).r * cx[jj];
    float opY = h_acc * baseWeight;
    /* AddDirFilters, only where the edge map gives a direction weight (most of a picture has none, and reads no more
     * of the game than the sums above). */
    [branch] if (w.x > 0.0 || w.y > 0.0 || w.z > 0.0 || w.w > 0.0) {
        /* The lumas the four directions' filters use between them: 24 of the 6x6, a diamond (its rows 2, 4, 6, 6, 4
         * and 2 wide), read once for them all, p[row][column]; the corners no direction reads stay 0. Each direction
         * reading its own 12 or 14 measured the same on a graphics card and a third slower on a renderer that runs
         * every branch for every pixel (Mesa's llvmpipe), which reads these 24 where the one pass read 36. */
        float p[6][6];
        [unroll] for (int r = 0; r < 6; r++)
            [unroll] for (int k = 0; k < 6; k++)
                p[r][k] = 0.0;
        static const float2 span[6] = {float2(2.0, 3.0), float2(1.0, 4.0), float2(0.0, 5.0),
                                       float2(0.0, 5.0), float2(1.0, 4.0), float2(2.0, 3.0)};
        [unroll] for (int rr = 0; rr < 6; rr++)
            [unroll] for (int kk = 0; kk < 6; kk++)
                if (kk >= span[rr].x && kk <= span[rr].y)
                    p[rr][kk] = nis_at(f0, kk, rr);
        /* Each direction's filter where it has weight (written out in scalars: the game's compiler takes many seconds
         * over small arrays chosen between at run time). */
        [branch] if (w.x > 0.0) {
            /* 0 degrees: down each row's pair of columns 2 and 3, the six rows through the 6-tap filter. */
            opY += nis_poly6(lerp(p[0][2], p[0][3], fr.x), lerp(p[1][2], p[1][3], fr.x), lerp(p[2][2], p[2][3], fr.x),
                             lerp(p[3][2], p[3][3], fr.x), lerp(p[4][2], p[4][3], fr.x), lerp(p[5][2], p[5][3], fr.x),
                             phase.y) * w.x;
        }
        [branch] if (w.y > 0.0) {
            /* 90 degrees: across each column's pair of rows 2 and 3. */
            opY += nis_poly6(lerp(p[2][0], p[3][0], fr.y), lerp(p[2][1], p[3][1], fr.y), lerp(p[2][2], p[3][2], fr.y),
                             lerp(p[2][3], p[3][3], fr.y), lerp(p[2][4], p[3][4], fr.y), lerp(p[2][5], p[3][5], fr.y),
                             phase.x) * w.y;
        }
        [branch] if (w.z > 0.0) {
            /* 45 degrees: seven samples along the diagonal, six of them by where the pixel sits. */
            float pb = 0.5 + 0.5 * (fr.x - fr.y);
            float t1 = lerp(p[2][1], p[1][2], pb);
            float t3 = lerp(p[3][2], p[2][3], pb);
            float t5 = lerp(p[4][3], p[3][4], pb);
            pb = pb - 0.5;
            bool pos = pb >= 0.0;
            float t0 = lerp(p[1][1], pos ? p[0][2] : p[2][0], abs(pb));
            float t2 = lerp(p[2][2], pos ? p[1][3] : p[3][1], abs(pb));
            float t4 = lerp(p[3][3], pos ? p[2][4] : p[4][2], abs(pb));
            float t6 = lerp(p[4][4], pos ? p[3][5] : p[5][3], abs(pb));
            float pp = fr.x + fr.y;
            bool up = pp >= 1.0;
            pp = up ? pp - 1.0 : pp;
            opY += nis_poly6(up ? t1 : t0, up ? t2 : t1, up ? t3 : t2, up ? t4 : t3, up ? t5 : t4, up ? t6 : t5,
                             floor(pp * 64.0)) * w.z;
        }
        [branch] if (w.w > 0.0) {
            /* 135 degrees, the same along the other diagonal. */
            float pb = 0.5 * (fr.x + fr.y);
            float t1 = lerp(p[3][1], p[4][2], pb);
            float t3 = lerp(p[2][2], p[3][3], pb);
            float t5 = lerp(p[1][3], p[2][4], pb);
            pb = pb - 0.5;
            bool pos = pb >= 0.0;
            float t0 = lerp(p[4][1], pos ? p[5][2] : p[3][0], abs(pb));
            float t2 = lerp(p[3][2], pos ? p[4][3] : p[2][1], abs(pb));
            float t4 = lerp(p[2][3], pos ? p[3][4] : p[1][2], abs(pb));
            float t6 = lerp(p[1][4], pos ? p[2][5] : p[0][3], abs(pb));
            float pp = 1.0 + (fr.x - fr.y);
            bool up = pp >= 1.0;
            pp = up ? pp - 1.0 : pp;
            opY += nis_poly6(up ? t1 : t0, up ? t2 : t1, up ? t3 : t2, up ? t4 : t3, up ? t5 : t4, up ? t6 : t5,
                             floor(pp * 64.0)) * w.w;
        }
    }
    /* The colour from a bilinear tap at the same place, its luma moved to the filters' (SDR: by adding the
     * difference to each channel). */
    float4 op = fetch(s3, (src + 0.5) * kSrcNorm);
    float y = nis_y(op.rgb);
    float corr = opY - y;
    return float4(op.rgb + corr, 1.0);
}

/* ------------------------------------------------------------------------------------------- FXAA 3.11 Quality */

/* Preset 39 (extreme quality): twelve search steps, the first five one pixel each. */
#define FXAA_PS 12
static const float FXAA_STEP[12] = {1.0, 1.0, 1.0, 1.0, 1.0, 1.5, 2.0, 2.0, 2.0, 2.0, 4.0, 8.0};
/* Its tuning, at the defaults its header gives: sub-pixel 0.75, edge threshold 0.166, darks trimmed below 0.0833. */
#define FXAA_SUBPIX 0.75
#define FXAA_EDGE 0.166
#define FXAA_EDGE_MIN 0.0833

/* The luma FXAA works on, from gamma-space colour as its header gives it for input with no luma in alpha. */
float fxaa_luma(float4 c)
{
    return dot(c.rgb, float3(0.299, 0.587, 0.114));
}

/* s0: the game's picture with a bilinear filter (FXAA reads between texels). */
float4 ps_fxaa(float2 vpos : VPOS) : COLOR
{
    float2 rcpFrame = c_in.zw;
    float2 posM = centre_uv(vpos, c_in);
    float4 rgbyM = fetch(s0, posM);
    float lumaM = fxaa_luma(rgbyM);
    float lumaS = fxaa_luma(fetch(s0, posM + float2(0.0, 1.0) * rcpFrame));
    float lumaE = fxaa_luma(fetch(s0, posM + float2(1.0, 0.0) * rcpFrame));
    float lumaN = fxaa_luma(fetch(s0, posM + float2(0.0, -1.0) * rcpFrame));
    float lumaW = fxaa_luma(fetch(s0, posM + float2(-1.0, 0.0) * rcpFrame));
    /* The local contrast; too little (against the brightest, or in the dark) is no edge. */
    float maxSM = max(lumaS, lumaM);
    float minSM = min(lumaS, lumaM);
    float maxESM = max(lumaE, maxSM);
    float minESM = min(lumaE, minSM);
    float maxWN = max(lumaN, lumaW);
    float minWN = min(lumaN, lumaW);
    float rangeMax = max(maxWN, maxESM);
    float rangeMin = min(minWN, minESM);
    float rangeMaxScaled = rangeMax * FXAA_EDGE;
    float range = rangeMax - rangeMin;
    float rangeMaxClamped = max(FXAA_EDGE_MIN, rangeMaxScaled);
    [branch] if (range < rangeMaxClamped)
        return float4(rgbyM.rgb, 1.0);
    float lumaNW = fxaa_luma(fetch(s0, posM + float2(-1.0, -1.0) * rcpFrame));
    float lumaSE = fxaa_luma(fetch(s0, posM + float2(1.0, 1.0) * rcpFrame));
    float lumaNE = fxaa_luma(fetch(s0, posM + float2(1.0, -1.0) * rcpFrame));
    float lumaSW = fxaa_luma(fetch(s0, posM + float2(-1.0, 1.0) * rcpFrame));
    /* Whether the edge runs across or down, from the 3x3's second differences. */
    float lumaNS = lumaN + lumaS;
    float lumaWE = lumaW + lumaE;
    float subpixRcpRange = 1.0 / range;
    float subpixNSWE = lumaNS + lumaWE;
    float edgeHorz1 = (-2.0 * lumaM) + lumaNS;
    float edgeVert1 = (-2.0 * lumaM) + lumaWE;
    float lumaNESE = lumaNE + lumaSE;
    float lumaNWNE = lumaNW + lumaNE;
    float edgeHorz2 = (-2.0 * lumaE) + lumaNESE;
    float edgeVert2 = (-2.0 * lumaN) + lumaNWNE;
    float lumaNWSW = lumaNW + lumaSW;
    float lumaSWSE = lumaSW + lumaSE;
    float edgeHorz4 = (abs(edgeHorz1) * 2.0) + abs(edgeHorz2);
    float edgeVert4 = (abs(edgeVert1) * 2.0) + abs(edgeVert2);
    float edgeHorz3 = (-2.0 * lumaW) + lumaNWSW;
    float edgeVert3 = (-2.0 * lumaS) + lumaSWSE;
    float edgeHorz = abs(edgeHorz3) + edgeHorz4;
    float edgeVert = abs(edgeVert3) + edgeVert4;
    float subpixNWSWNESE = lumaNWSW + lumaNESE;
    float lengthSign = rcpFrame.x;
    bool horzSpan = edgeHorz >= edgeVert;
    float subpixA = subpixNSWE * 2.0 + subpixNWSWNESE;
    if (!horzSpan) lumaN = lumaW;
    if (!horzSpan) lumaS = lumaE;
    if (horzSpan) lengthSign = rcpFrame.y;
    float subpixB = (subpixA * (1.0 / 12.0)) - lumaM;
    /* Which side of the edge is the pixel's pair. */
    float gradientN = lumaN - lumaM;
    float gradientS = lumaS - lumaM;
    float lumaNN = lumaN + lumaM;
    float lumaSS = lumaS + lumaM;
    bool pairN = abs(gradientN) >= abs(gradientS);
    float gradient = max(abs(gradientN), abs(gradientS));
    if (pairN) lengthSign = -lengthSign;
    float subpixC = saturate(abs(subpixB) * subpixRcpRange);
    /* Search both ways along the edge from its middle, in the preset's steps, for its ends. */
    float2 posB = posM;
    float2 offNP;
    offNP.x = (!horzSpan) ? 0.0 : rcpFrame.x;
    offNP.y = (horzSpan) ? 0.0 : rcpFrame.y;
    if (!horzSpan) posB.x += lengthSign * 0.5;
    if (horzSpan) posB.y += lengthSign * 0.5;
    float2 posN = posB - offNP * FXAA_STEP[0];
    float2 posP = posB + offNP * FXAA_STEP[0];
    float subpixD = ((-2.0) * subpixC) + 3.0;
    float lumaEndN = fxaa_luma(fetch(s0, posN));
    float subpixE = subpixC * subpixC;
    float lumaEndP = fxaa_luma(fetch(s0, posP));
    if (!pairN) lumaNN = lumaSS;
    float gradientScaled = gradient * 1.0 / 4.0;
    float lumaMM = lumaM - lumaNN * 0.5;
    float subpixF = subpixD * subpixE;
    bool lumaMLTZero = lumaMM < 0.0;
    lumaEndN -= lumaNN * 0.5;
    lumaEndP -= lumaNN * 0.5;
    bool doneN = abs(lumaEndN) >= gradientScaled;
    bool doneP = abs(lumaEndP) >= gradientScaled;
    if (!doneN) posN -= offNP * FXAA_STEP[1];
    bool doneNP = (!doneN) || (!doneP);
    if (!doneP) posP += offNP * FXAA_STEP[1];
    /* Each further step only while one side is still searching (the header's nested ifs, flattened). */
    [unroll] for (int s = 2; s < FXAA_PS; s++) {
        [branch] if (doneNP) {
            if (!doneN) lumaEndN = fxaa_luma(fetch(s0, posN));
            if (!doneP) lumaEndP = fxaa_luma(fetch(s0, posP));
            if (!doneN) lumaEndN = lumaEndN - lumaNN * 0.5;
            if (!doneP) lumaEndP = lumaEndP - lumaNN * 0.5;
            doneN = abs(lumaEndN) >= gradientScaled;
            doneP = abs(lumaEndP) >= gradientScaled;
            if (!doneN) posN -= offNP * FXAA_STEP[s];
            doneNP = (!doneN) || (!doneP);
            if (!doneP) posP += offNP * FXAA_STEP[s];
        }
    }
    /* How far along the edge this pixel is, which way to move it, and by how much (or the sub-pixel blend). */
    float dstN = posM.x - posN.x;
    float dstP = posP.x - posM.x;
    if (!horzSpan) dstN = posM.y - posN.y;
    if (!horzSpan) dstP = posP.y - posM.y;
    bool goodSpanN = (lumaEndN < 0.0) != lumaMLTZero;
    float spanLength = (dstP + dstN);
    bool goodSpanP = (lumaEndP < 0.0) != lumaMLTZero;
    float spanLengthRcp = 1.0 / spanLength;
    bool directionN = dstN < dstP;
    float dst = min(dstN, dstP);
    bool goodSpan = directionN ? goodSpanN : goodSpanP;
    float subpixG = subpixF * subpixF;
    float pixelOffset = (dst * (-spanLengthRcp)) + 0.5;
    float subpixH = subpixG * FXAA_SUBPIX;
    float pixelOffsetGood = goodSpan ? pixelOffset : 0.0;
    float pixelOffsetSubpix = max(pixelOffsetGood, subpixH);
    if (!horzSpan) posM.x += pixelOffsetSubpix * lengthSign;
    if (horzSpan) posM.y += pixelOffsetSubpix * lengthSign;
    return float4(fetch(s0, posM).rgb, 1.0);
}

/* ------------------------------------------------------------------------------------------- the layer's glass */

/* The in-game layer's panels are opaque frosted glass: the game's frame behind them, blurred, a dark tint laid over it,
 * and the panel's own picture (its edges, words and buttons, drawn by look.c) over that. The blur is made once a frame
 * while a panel shows, at an eighth of the game's size (160x96), which keeps it cheap at any window size. */

/* The game's frame averaged 8x8 into an eighth-size target: each bilinear read at the shared corner of a 2x2 block
 * averages that block, and sixteen of them cover the 8x8 block exactly (s0 bilinear; c0 the input's size). */
float4 ps_ui_down(float2 vpos : VPOS) : COLOR
{
    float2 base = floor(vpos) * 8.0;
    float3 s = 0.0;
    for (int y = 0; y < 4; y++)
        for (int x = 0; x < 4; x++)
            s += fetch(s0, (base + float2(2.0 * x + 1.0, 2.0 * y + 1.0)) * c_in.zw).rgb;
    return float4(s / 16.0, 1.0);
}

/* A Gaussian across or down that eighth-size frame: c2.xy the direction (one texel across, or one down), c3 and c4.x
 * the weights (the middle's first, then each distance out to 4), 9 reads at the texels' centres (s0 point, clamped). */
float4 ps_ui_blur(float2 vpos : VPOS) : COLOR
{
    float2 uv = centre_uv(vpos, c_in);
    float w[5] = {c_p3.x, c_p3.y, c_p3.z, c_p3.w, c_p4.x};
    float3 s = fetch(s0, uv).rgb * w[0];
    for (int i = 1; i <= 4; i++) {
        float2 d = c_p2.xy * (float)i * c_in.zw;
        s += (fetch(s0, uv + d).rgb + fetch(s0, uv - d).rgb) * w[i];
    }
    return float4(s, 1.0);
}

/* One part of the layer composed into a texture of its own, once for a blurred frame and a picture (the frame drawn
 * after shows that texture alone, which costs a software renderer a fraction of reading the blurred frame each time):
 * the same glass as ps_ui_glass at the part's place in the output, opacity whole (the fade is the drawing's). VPOS is
 * the pixel of the part's texture; c2.xy the part's top left in the output (pixels), c2.zw one over its textures' size;
 * c3.y the tint's opacity; c4 the tint; c1 the output's size, where the blurred frame is read. */
float4 ps_ui_compose(float2 vpos : VPOS) : COLOR
{
    /* This texel's centre, and the same texel of the picture and the mask (point). */
    float2 p = floor(vpos) + 0.5;
    float2 t = p * c_p2.zw;
    float4 picture = fetch(s0, t);
    float mask = fetch(s1, t).a;
    /* The blurred frame at the output's pixel this texel lands on, then the tint over it. */
    float3 behind = fetch(s2, (p + c_p2.xy) * c_out.zw).rgb;
    float3 glass = lerp(behind, c_p4.rgb, c_p3.y);
    /* The picture (premultiplied) over the glass where the mask has it: premultiplied as well. */
    float3 rgb = picture.rgb + (1.0 - picture.a) * mask * glass;
    float alpha = picture.a + (1.0 - picture.a) * mask;
    return float4(rgb, alpha);
}

/* One part of the layer over the game: s0 its picture (premultiplied), s1 its mask (alpha: where the glass is), both
 * read at their texels' centres (point); s2 the blurred frame (bilinear) at this pixel's place in the output. c2 the
 * part's top left in the output (pixels) and one over its textures' size; c3.x the part's opacity (its fade), c3.y the
 * tint's opacity; c4 the tint. The result is premultiplied and blended as such (one, one minus its alpha). */
float4 ps_ui_glass(float2 vpos : VPOS) : COLOR
{
    float2 p = floor(vpos) + 0.5;
    float2 t = (p - c_p2.xy) * c_p2.zw;
    float4 picture = fetch(s0, t);
    float mask = fetch(s1, t).a;
    float3 behind = fetch(s2, (p - c_origin.xy) * c_out.zw).rgb;
    float3 glass = lerp(behind, c_p4.rgb, c_p3.y);
    float3 rgb = picture.rgb + (1.0 - picture.a) * mask * glass;
    float alpha = picture.a + (1.0 - picture.a) * mask;
    return float4(rgb, alpha) * c_p3.x;
}
