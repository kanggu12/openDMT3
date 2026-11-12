/*
 * openDMT3's three SMAA 1x passes (post.c): SMAA.hlsl itself (third_party/smaa, MIT, Copyright (C) 2013 Jorge Jimenez,
 * Jose I. Echevarria, Belen Masia, Fernando Navarro, Diego Gutierrez) is put in front of this text when the shaders
 * are compiled, with its Direct3D 9 path (SMAA_HLSL_3), the preset chosen (SMAA_PRESET_LOW to _ULTRA) and these
 * definitions. Its vertex shader parts only work out offsets from a texture coordinate, so they run here in the pixel
 * shader, from the pixel's own position: no coordinate is interpolated and Direct3D 9's half-pixel offset never comes
 * into it.
 *
 * Samplers (post.c sets them): s0 the game's picture, point for the edge pass (it reads whole texels) and bilinear
 * for the blend; s1 the edges or the blending weights, bilinear; s2 the area texture, bilinear; s3 the search texture,
 * point (SMAA reads it with point filtering).
 */

sampler2D s_color : register(s0);
sampler2D s_mid : register(s1);
sampler2D s_area : register(s2);
sampler2D s_search : register(s3);

/* This pixel's centre in the picture's normalised coordinates (SMAA_RT_METRICS.xy is one texel). */
float2 smaa_uv(float2 vpos)
{
    return (floor(vpos) + 0.5) * SMAA_RT_METRICS.xy;
}

/* Luma edge detection, as SMAA recommends for colour input. Pixels with no edge are discarded: post.c clears the
 * target first. */
float4 ps_smaa_edges(float2 vpos : VPOS) : COLOR
{
    float2 uv = smaa_uv(vpos);
    float4 offset[3];
    SMAAEdgeDetectionVS(uv, offset);
    return float4(SMAALumaEdgeDetectionPS(uv, offset, s_color), 0.0, 0.0);
}

/* The blending weights from the edges, with the precomputed area and search textures (no sub-sample indices: 1x). */
float4 ps_smaa_weights(float2 vpos : VPOS) : COLOR
{
    float2 uv = smaa_uv(vpos);
    float2 pixcoord;
    float4 offset[3];
    SMAABlendingWeightCalculationVS(uv, pixcoord, offset);
    return SMAABlendingWeightCalculationPS(uv, pixcoord, offset, s_mid, s_area, s_search, float4(0.0, 0.0, 0.0, 0.0));
}

/* The neighbourhood blend of the game's picture by those weights. */
float4 ps_smaa_blend(float2 vpos : VPOS) : COLOR
{
    float2 uv = smaa_uv(vpos);
    float4 offset;
    SMAANeighborhoodBlendingVS(uv, offset);
    return float4(SMAANeighborhoodBlendingPS(uv, offset, s_color, s_mid).rgb, 1.0);
}
