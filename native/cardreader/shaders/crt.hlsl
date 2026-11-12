/*
 * Motion clarity's sub-frames (strobe.c), Direct3D 9 shader model 3.0, compiled when the game starts by the game's own
 * D3DX as post.hlsl is. On a display of N times 60 Hz each game frame is presented N times, one refresh each; this pass
 * draws sub-frame k of N from the last two pictures the chain made (the newest, and the one before).
 *
 * The maths is the CRT beam simulator of Mark Rejhon (Blur Busters) and Timothy Lottes, MIT licence, Copyright 2024
 * (github.com/blurbusters/crt-beam-simulator, crt-simulator.glsl; its licence text is in
 * third_party/crt-beam-simulator).
 * Each pixel's light, in linear light and times N and a gain under 1, is a budget of refreshes: it is emitted as early
 * as it can be from the moment the simulated beam reaches the pixel's row, so a dim pixel is lit for a fraction of one
 * refresh and a bright one for up to most of the frame (a longer glow, as an overexcited phosphor's). Over a frame the
 * pixel gives out the gain's share of its light (70 % at 240 Hz and above), each sub-frame what falls in it.
 *
 * Its three frames are taken here as the newest picture (the simulator's previous one, whose scan this frame is: so
 * the scan starts at this frame's present, with no frame of delay) and the one before (its "two back", whose light runs
 * on into this frame's first refreshes); the simulator's newest is never lit at a whole number of refreshes a frame,
 * and is left out. The simulator's slew for LCDs' polarity (N plus 0.001) is left out too: each game frame is exactly
 * N refreshes here, as the frame clock presents them. The rolling scan goes from the top down; the global one lights
 * every row from the frame's first refresh (black frame insertion, with the bright pixels' light spread the same way).
 */

/* c0: x the sub-frame's start in refreshes (k), y the refreshes a frame (N), z the light budget's scale (N times the
 * gain), w 1 for the global scan (every row at once), 0 for the rolling one. c1: x 1 when the frame before exists.
 * c2: x, y one texel of the kept pictures (1/width, 1/height), z one row of the screen's height (1/height). */
float4 c_beam : register(c0);
float4 c_have : register(c1);
float4 c_size : register(c2);

/* The newest picture and the one before it, read texel for texel (point sampling, clamped). */
sampler2D s_newest : register(s0);
sampler2D s_before : register(s1);

/* The triangle's corners come already in clip space. */
float4 vs_crt(float4 pos : POSITION) : POSITION
{
    return pos;
}

/* The display's gamma, as the simulator's default: its light is added up in linear light, so the bands between
 * refreshes add up without seams only with the display's own curve. */
#define GAMMA 2.4

/* Linear light to the display's code value, as the simulator writes it (its clamp: the curve's power part). */
float3 to_code(float3 c)
{
    float3 p = pow(max(c, 0.0), 1.0 / GAMMA) * 1.055 - 0.055;
    return clamp(0.0031308 * 12.92, c * 12.92, p);
}

/* A code value to linear light (sRGB's two parts, with the display's gamma). */
float3 to_linear(float3 c)
{
    float3 lo = c / 12.92;
    float3 hi = pow(c / 1.055 + 0.055 / 1.055, GAMMA);
    return float3(c.r > 0.04045 ? hi.r : lo.r, c.g > 0.04045 ? hi.g : lo.g, c.b > 0.04045 ? hi.b : lo.b);
}

/* How much of the sub-frame [from, from + 1) falls inside the light's interval [start, start + length), per colour. */
float3 overlap(float3 start, float3 length, float from)
{
    return max(0.0, min(start + length, from + 1.0) - max(start, from));
}

float4 ps_crt(float2 vpos : VPOS) : COLOR
{
    /* This pixel's texel in the kept pictures, and its row's place from the top (0) to the bottom (1). */
    float2 uv = (floor(vpos) + 0.5) * c_size.xy;
    float row = (floor(vpos.y) + 0.5) * c_size.z;
    float n = c_beam.y, from = c_beam.x;
    /* The light budgets, in refreshes. */
    float3 newest = to_linear(tex2Dlod(s_newest, float4(uv, 0.0, 0.0)).rgb) * c_beam.z;
    float3 before = c_have.x > 0.5 ? to_linear(tex2Dlod(s_before, float4(uv, 0.0, 0.0)).rgb) * c_beam.z : 0.0;
    /* When the beam reaches the row, in refreshes from the frame's first: its place times N (none for the global
     * scan). The frame before started a frame earlier. */
    float reached = c_beam.w > 0.5 ? 0.0 : row * n;
    float3 lit = overlap(reached, newest, from) + overlap(reached - n, before, from);
    return float4(saturate(to_code(lit)), 1.0);
}
