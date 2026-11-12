/*
 * The in-game layer's drawing, in plain C with no Windows calls, so it builds and runs in the native tests too.
 *
 * A canvas is 32-bit premultiplied BGRA, the layout Windows' layered windows and cursors take (one uint32_t per
 * pixel, 0xAARRGGBB). Shapes are polygons filled with anti-aliased edges: each pixel row is sampled on several
 * lines and each crossing is measured to a fraction of a pixel across, which keeps a 32-pixel cursor smooth.
 * Text is not here: the layer draws it with GDI (layer.c) and blends it in with paint_coverage().
 */
#ifndef OPENDMT3_PAINT_H
#define OPENDMT3_PAINT_H

#include <stdint.h>

/* A picture to draw on: w x h pixels, row after row from the top, premultiplied 0xAARRGGBB. */
typedef struct {
    int w, h;
    uint32_t *px;
} Canvas;

/* A point, in pixels; (0, 0) is the top-left corner of the top-left pixel. */
typedef struct {
    float x, y;
} Pt;

/* One stop of a gradient: where (0 at the gradient's top, 1 at its foot) and its colour (0xRRGGBB). */
typedef struct {
    float at;
    uint32_t rgb;
} Stop;

/* How a shape is filled: one colour, or a gradient from top to foot through its stops (between y0 and y1). */
typedef struct {
    int nstops;          /* 1: a plain colour (stops[0]); more: a vertical gradient */
    Stop stops[6];       /* the colours, in order of `at` */
    float y0, y1;        /* the gradient's top and foot, in the canvas's pixels */
    float alpha;         /* the whole fill's opacity, 0 to 1 */
} Paint;

/* The most points one shape may have (a circle takes 96, the dart fewer than 16). */
#define PAINT_MAX_POINTS 512

/* A plain colour at an opacity. */
Paint paint_solid(uint32_t rgb, float alpha);
/* A vertical gradient from `top` at y0 to `foot` at y1. */
Paint paint_ramp(uint32_t top, uint32_t foot, float y0, float y1, float alpha);

/* An empty canvas (every pixel clear); free it with canvas_free. NULL when memory runs out. */
Canvas *canvas_new(int w, int h);
void canvas_free(Canvas *c);
/* Every pixel clear. */
void canvas_clear(Canvas *c);

/*
 * Fill a shape made of one or more closed outlines (counts[i] points each, one after another in `pts`), the
 * even-odd rule deciding inside: a ring is its outer outline followed by its inner one.
 */
void paint_fill(Canvas *c, const Pt *pts, const int *counts, int outlines, const Paint *paint);
/* Fill one closed outline. */
void paint_polygon(Canvas *c, const Pt *pts, int n, const Paint *paint);
/* A straight line `width` pixels thick from a to b, with round ends. */
void paint_line(Canvas *c, Pt a, Pt b, float width, const Paint *paint);
/* A filled circle. */
void paint_circle(Canvas *c, float cx, float cy, float r, const Paint *paint);
/* A ring: the circle's edge, `width` pixels thick, its middle on radius r. */
void paint_ring(Canvas *c, float cx, float cy, float r, float width, const Paint *paint);
/* A rectangle's area, any size, with no smoothing (edges on whole pixels). */
void paint_rect(Canvas *c, int x, int y, int w, int h, const Paint *paint);
/* Blend `rgb` in where `coverage` (w x h bytes, 0 to 255) says, with its top-left at (x, y): text drawn by GDI. */
void paint_coverage(Canvas *c, int x, int y, int w, int h, const uint8_t *coverage, int stride, uint32_t rgb,
                    float alpha);
/* The same with a paint (a gradient down the words, as the wordmark's chrome), its rows on the canvas's rows. */
void paint_coverage_paint(Canvas *c, int x, int y, int w, int h, const uint8_t *coverage, int stride,
                          const Paint *paint);
/* A picture (premultiplied) drawn over the canvas into the box (x, y, w, h), each pixel the average of the picture's
 * pixels it covers (by area): sharp when drawn smaller, as the launcher's own pictures are. */
void paint_image(Canvas *c, const Canvas *src, float x, float y, float w, float h);

/*
 * The leaning plate of the launcher's buttons and the game's plates (art.py lean_outline): a parallelogram in the
 * box (x, y, w, h), both ends on the slope LEAN, every side moved out by `grow` pixels (in, when negative).
 */
#define PAINT_LEAN 0.36f
void lean_outline(float x, float y, float w, float h, float grow, Pt out[4]);
/* An outline moved inward by d pixels on every side (mitred corners), into out (n points); 0 when it cannot be. */
int offset_outline(const Pt *pts, int n, float d, Pt *out);
/* The title tab of the launcher's dialogs: wide at the panel's top edge, narrowing downwards by `slant` a side. */
void tab_outline(float x, float y, float w, float h, float slant, Pt out[4]);

/*
 * The cursor: a dart, its tip the hot spot, drawn on a size x size canvas (32 at 96 dpi). `pressed` draws the state
 * while the mouse's button is down. The tip is at (*hot_x, *hot_y). `look` picks one of the drawings compared when
 * the cursor was chosen (CURSOR_LOOKS of them; CURSOR_CHOSEN is the one the game shows).
 */
#define CURSOR_LOOKS 5
#define CURSOR_CHOSEN 3
void paint_cursor(Canvas *c, int look, int pressed, int *hot_x, int *hot_y);

/* The logo's colours (opendmt3/client/theme.py, art.py), shared by the layer and the cursor. */
#define RGB_BG 0x101317u        /* the launcher's window behind everything */
#define RGB_PANEL 0x1a1f25u     /* a dialog's panel */
#define RGB_PANEL_HI 0x232931u  /* a raised row */
#define RGB_RAIL 0x2b323bu      /* quiet metal: buttons */
#define RGB_RAIL_UP 0x3a434eu   /* the same under the pointer */
#define RGB_LINE 0x343c47u      /* one-pixel seams */
#define RGB_TEXT 0xeef2f6u      /* body text */
#define RGB_MUTED 0xaab4bfu     /* hints */
#define RGB_INK 0x0b0e12u       /* words on a bright colour */
#define RGB_BLUE 0x2a5ff0u      /* the title screen's blue */
#define RGB_BLUE_HI 0x5b8cffu   /* the same, lit: the logo's 3 */
#define RGB_BLUE_DEEP 0x0d2a8fu /* the dark end of its gradients */
#define RGB_PINK 0xff4fa0u      /* removing, quitting */
#define RGB_CYAN 0x5fd3ffu      /* the keyboard's ring */

#endif
