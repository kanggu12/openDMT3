/*
 * The post-process chain's numbers and plan, in plain C with no Windows calls, so the native tests check each one:
 * which passes a choice of upscale filter and anti-aliasing runs, and the constants each filter's shader is given
 * (AMD FSR 1's EASU and RCAS, NVIDIA NIS's scaler), worked out as their published sources work them out on the CPU.
 * post.c runs the passes on the game's Direct3D 9 device.
 */
#ifndef OPENDMT3_POSTMATH_H
#define OPENDMT3_POSTMATH_H

/* The upscale filters (OPENDMT3_UPSCALE): the game's 1280x768 picture to the window's size. */
enum {
    UPSCALE_OFF = 0,       /* nearest: each game pixel as a block, the game's own pixels */
    UPSCALE_SMOOTH = 1,    /* bilinear, as Direct3D's own stretch draws it today */
    UPSCALE_FSR1 = 2,      /* AMD FidelityFX Super Resolution 1: EASU, then RCAS sharpening */
    UPSCALE_NIS = 3,       /* NVIDIA Image Scaling: its 6-tap directional scaler with built-in sharpening */
    UPSCALE_ANIME4K = 4,   /* Anime4K's CNN x2 (S): a small convolutional network doubles the picture, bilinear after */
    UPSCALE_COUNT = 5
};

/* The anti-aliasing choices (OPENDMT3_ANTIALIASING), run on the game's 1280x768 picture before the upscale. */
enum {
    AA_OFF = 0,
    AA_FXAA = 1,           /* FXAA 3.11, its quality version */
    AA_SMAA_LOW = 2,       /* SMAA 1x at its four presets */
    AA_SMAA_MEDIUM = 3,
    AA_SMAA_HIGH = 4,
    AA_SMAA_ULTRA = 5,
    AA_COUNT = 6
};
/* No MSAA choice: measured on the game, multisampling its drawing changes no pixel of its static pictures (the game
 * draws textured quads whose edges are see-through; its hard edges are inside its textures, where samples do not
 * reach). docs/architecture.md has the measurement. */

/* The defaults (the launcher's are the same, in values.py), chosen on the game's own frames at 3840x2160: FSR 1 is
 * sharper than bilinear with no halo past the picture's own values on chrome and lime (none over 16 levels at 50;
 * NIS rings, from 0.08 % to 2.4 % of pixels over 16 levels); RCAS at 50 adds sharpness with that still none, and above
 * 75 it starts to halo; the game's art is drawn already smooth in its textures, so anti-aliasing has little to find
 * and FXAA softens its text: off. */
#define UPSCALE_DEFAULT UPSCALE_FSR1
#define SHARPNESS_DEFAULT 50
#define AA_DEFAULT AA_OFF

/* The names the launcher writes for each choice (the same as its --set values), in the order of the enums. */
extern const char *const UPSCALE_NAMES[UPSCALE_COUNT];
extern const char *const AA_NAMES[AA_COUNT];

/* A name to its choice; -1 when it is not one. Case does not matter. */
int upscale_from_name(const char *name);
int aa_from_name(const char *name);

/* The SMAA preset a choice runs (0 low to 3 ultra), or -1 when it is not SMAA. */
int aa_smaa_preset(int aa);

/* The passes the chain can run, each one draw of a full-screen triangle with one pixel shader. */
enum {
    PASS_FXAA = 0,
    PASS_SMAA_EDGES,       /* SMAA's luma edge detection */
    PASS_SMAA_WEIGHTS,     /* its blending weights, with the area and search textures */
    PASS_SMAA_BLEND,       /* its neighbourhood blending */
    PASS_NEAREST,          /* the upscale passes */
    PASS_BILINEAR,
    PASS_EASU_LEN,         /* EASU's lengths of each texel's edge, at the game's size (once, not per output pixel) */
    PASS_EASU,
    PASS_RCAS,
    PASS_NIS_EDGES,        /* NIS's edge map, at the game's size */
    PASS_NIS_ROWS,         /* NIS's scaler down each of the game's columns, at the game's width and the window's height */
    PASS_NIS_SCALE,        /* NIS's scaler across them and its directions' filters, at the window's size */
    PASS_ANIME4K,          /* Anime4K's network: four layers at the game's size, its 2x picture (anime4k_x2_s.hlsl) */
    PASS_UI_DOWN,          /* the in-game layer's glass: the game's frame averaged to a quarter of its size, */
    PASS_UI_BLUR,          /* blurred, */
    PASS_UI_GLASS,         /* and a panel laid over it, tinted (never in a choice's plan: the layer draws them) */
    PASS_UI_COMPOSE,       /* or a panel composed so into a texture of its own, drawn every frame as that texture */
    PASS_KINDS
};

/* The passes for a choice, in order, into `out` (at most 8); how many. An output smaller than the game's picture in
 * either direction gets bilinear (FSR's EASU and NIS's scaler only enlarge); Anime4K runs when the output is more than
 * 1.2 times the input both ways (its own rule), its 2x picture then brought to the output by bilinear. */
int post_plan(int upscale, int aa, int in_w, int in_h, int out_w, int out_h, int out[8]);

/* The safety net's next lighter choice, in place: SMAA (any preset) to FXAA, FXAA to none, then NVIDIA NIS, AMD FSR 1
 * or Anime4K to bilinear. 0 when nothing lighter is left (nearest or bilinear with no anti-aliasing). */
int post_lighter(int *upscale, int *aa);

/* Whether a choice needs a pass of the chain's for the picture itself: bilinear with no anti-aliasing is what
 * Direct3D's own stretch would show. (The chain runs for it all the same: the in-game layer is drawn in it.) */
int post_wanted(int upscale, int aa);

/* FSR 1's EASU constants (FsrEasuCon in ffx_fsr1.h), as four float4s: con0 the output pixel to input pixel scale and
 * offset, con1 to con3 the offsets between its taps in the input's normalised coordinates. */
void easu_constants(float in_w, float in_h, float out_w, float out_h, float con[16]);

/* RCAS's sharpness in stops (0 the most, each stop half as much), from openDMT3's 0 to 100: as FidelityFX's own
 * remapping of a 0 to 1 slider, stops = 2 - 2 * sharpness. */
float rcas_stops(int sharpness);
/* RCAS's constant (FsrRcasCon): 2 to the power of minus the stops. */
float rcas_constant(float stops);

/* NIS's scaler constants (NVScalerUpdateConfig in NIS_Config.h, its SDR branch), from a 0 to 1 sharpness. */
typedef struct {
    float scale_x, scale_y;          /* input size over output size */
    float src_norm_x, src_norm_y;    /* one over the input's size */
    float detect_ratio, detect_thres, min_contrast_ratio, ratio_norm, contrast_boost, eps;
    float sharp_start_y, sharp_scale_y, sharp_strength_min, sharp_strength_scale, sharp_limit_min, sharp_limit_scale;
} NisConfig;
void nis_config(float sharpness, int in_w, int in_h, int out_w, int out_h, NisConfig *c);

/* NIS's filter banks (coef_scale and coef_usm in NIS_Config.h): 64 phases of 6 taps each. */
#define NIS_PHASES 64
#define NIS_TAPS 6
extern const float NIS_COEF_SCALE[NIS_PHASES][NIS_TAPS];
extern const float NIS_COEF_USM[NIS_PHASES][NIS_TAPS];

/* The back buffer openDMT3 asks for when the chain runs: the window's client size, at least the monitor's (so the
 * window can grow to it with no reset), and never smaller than the game's own picture. */
void back_buffer_size(int client_w, int client_h, int monitor_w, int monitor_h, int *w, int *h);
/* The flip model's back buffer: presented whole (no source rectangle), so exactly the window's client, smaller than the
 * game's picture too (a window the chip makes on a 768-line screen); back_buffer_size's for a client of no size (a
 * window minimised, or not known). */
void flip_back_buffer_size(int client_w, int client_h, int monitor_w, int monitor_h, int *w, int *h);

/* "Off" (sharp bilinear), the shader ps_nearest's sums for one axis: where to read with a bilinear filter, in input
 * texels, for the output pixel whose centre is at `t` input texels, `scale` output pixels to an input one, so each
 * input pixel shows as a box `scale` output pixels wide and the output pixel on a box's edge mixes the two by how much
 * of it each covers (whole multiples of the size give nearest itself; under 1, plain bilinear). */
float sharp_coord(float t, float scale);

#endif
