/*
 * The in-game layer's drawing (paint.h): anti-aliased polygons on a premultiplied BGRA canvas, and the cursor.
 */
#include "paint.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

/* Sample lines per pixel row: eight keeps a 32-pixel cursor's slopes smooth, and a full-screen card fast enough. */
#define ROW_SAMPLES 8

Paint paint_solid(uint32_t rgb, float alpha)
{
    Paint p;
    /* Everything zero first, so unused stops never hold stray values. */
    memset(&p, 0, sizeof p);
    p.nstops = 1;
    p.stops[0].rgb = rgb;
    p.alpha = alpha;
    return p;
}

Paint paint_ramp(uint32_t top, uint32_t foot, float y0, float y1, float alpha)
{
    Paint p;
    memset(&p, 0, sizeof p);
    /* Two stops: the colour at the top, the colour at the foot. */
    p.nstops = 2;
    p.stops[0].at = 0.0f;
    p.stops[0].rgb = top;
    p.stops[1].at = 1.0f;
    p.stops[1].rgb = foot;
    p.y0 = y0;
    p.y1 = y1;
    p.alpha = alpha;
    return p;
}

Canvas *canvas_new(int w, int h)
{
    /* A zero or negative size is still a canvas (of one pixel), so callers never draw through NULL by mistake. */
    if (w < 1)
        w = 1;
    if (h < 1)
        h = 1;
    Canvas *c = malloc(sizeof *c);
    if (!c)
        return NULL;
    /* calloc: every pixel starts clear (0 is transparent black in premultiplied form). */
    c->px = calloc((size_t)w * (size_t)h, sizeof *c->px);
    if (!c->px) {
        free(c);
        return NULL;
    }
    c->w = w;
    c->h = h;
    return c;
}

void canvas_free(Canvas *c)
{
    if (!c)
        return;
    free(c->px);
    free(c);
}

void canvas_clear(Canvas *c)
{
    memset(c->px, 0, (size_t)c->w * (size_t)c->h * sizeof *c->px);
}

/* The paint's colour at a height, as 0xRRGGBB: its one colour, or the gradient's at that place. */
static uint32_t colour_at(const Paint *p, float y)
{
    if (p->nstops < 2)
        return p->stops[0].rgb;
    /* Where the row is between the gradient's top and foot, 0 to 1. */
    float t = p->y1 > p->y0 ? (y - p->y0) / (p->y1 - p->y0) : 0.0f;
    if (t <= p->stops[0].at)
        return p->stops[0].rgb;
    for (int i = 1; i < p->nstops; i++) {
        if (t <= p->stops[i].at) {
            /* Between this stop and the one before: mix the two by how far along it is. */
            const Stop *a = &p->stops[i - 1], *b = &p->stops[i];
            float k = b->at > a->at ? (t - a->at) / (b->at - a->at) : 1.0f;
            uint32_t out = 0;
            /* Each channel on its own: blue, green, red (8 bits apart). */
            for (int shift = 0; shift <= 16; shift += 8) {
                float ca = (float)((a->rgb >> shift) & 0xff), cb = (float)((b->rgb >> shift) & 0xff);
                uint32_t v = (uint32_t)lroundf(ca + (cb - ca) * k);
                out |= (v > 255 ? 255 : v) << shift;
            }
            return out;
        }
    }
    /* Past the last stop: its colour. */
    return p->stops[p->nstops - 1].rgb;
}

/* Blend one pixel of colour `rgb` at opacity `a` (0 to 1) over what the canvas has there. */
static void blend(uint32_t *dst, uint32_t rgb, float a)
{
    if (a <= 0.0f)
        return;
    /* The opacity in 255ths, rounded: whole numbers from here, as fast as the layer's large pictures need. */
    uint32_t ai = a >= 1.0f ? 255u : (uint32_t)(a * 255.0f + 0.5f);
    if (!ai)
        return;
    if (ai == 255) {
        /* Opaque: the colour itself. */
        *dst = 0xff000000u | (rgb & 0xffffffu);
        return;
    }
    uint32_t d = *dst, keep = 255u - ai, out = 0;
    /* "Over" in premultiplied form: the new colour times its opacity, plus what was there times what shows through,
     * each channel rounded to the nearest 255th. */
    for (int shift = 0; shift <= 16; shift += 8) {
        uint32_t v = (((rgb >> shift) & 0xffu) * ai + ((d >> shift) & 0xffu) * keep + 127u) / 255u;
        out |= v << shift;
    }
    /* The opacity channel the same way. */
    out |= ((255u * ai + (d >> 24) * keep + 127u) / 255u) << 24;
    *dst = out;
}

/* A crossing of a sample line by an outline's edge: where, and which way the edge runs (for the winding). */
typedef struct {
    float x;
} Crossing;

static int by_x(const void *a, const void *b)
{
    float d = ((const Crossing *)a)->x - ((const Crossing *)b)->x;
    return d < 0 ? -1 : d > 0 ? 1 : 0;
}

void paint_fill(Canvas *c, const Pt *pts, const int *counts, int outlines, const Paint *paint)
{
    if (!c || outlines <= 0)
        return;
    int total = 0;
    /* How many points in all, and the shape's height on the canvas. */
    float top = 1e9f, foot = -1e9f, left = 1e9f, right = -1e9f;
    for (int o = 0; o < outlines; o++)
        total += counts[o];
    if (total <= 0 || total > PAINT_MAX_POINTS * 4)
        return;
    for (int i = 0; i < total; i++) {
        if (pts[i].y < top)
            top = pts[i].y;
        if (pts[i].y > foot)
            foot = pts[i].y;
        if (pts[i].x < left)
            left = pts[i].x;
        if (pts[i].x > right)
            right = pts[i].x;
    }
    /* Only the rows and columns the shape touches, and only those on the canvas. */
    int y0 = (int)floorf(top), y1 = (int)ceilf(foot);
    int x0 = (int)floorf(left), x1 = (int)ceilf(right);
    if (y0 < 0)
        y0 = 0;
    if (y1 > c->h)
        y1 = c->h;
    if (x0 < 0)
        x0 = 0;
    if (x1 > c->w)
        x1 = c->w;
    if (y0 >= y1 || x0 >= x1)
        return;
    int span = x1 - x0;
    /* One row's coverage, 0 to 1 a pixel, summed over its sample lines: the pixels a span covers only in part go
     * straight into `cover`; the whole ones between are a run, kept as where it starts and stops in `run` and summed
     * across once a row, so a wide shape costs its edges, not its width, on each sample line. */
    float *cover = calloc((size_t)span + 2, sizeof *cover);
    float *run = calloc((size_t)span + 2, sizeof *run);
    Crossing *cross = malloc((size_t)total * sizeof *cross);
    if (!cover || !run || !cross) {
        free(cover);
        free(run);
        free(cross);
        return;
    }
    for (int y = y0; y < y1; y++) {
        memset(cover, 0, ((size_t)span + 2) * sizeof *cover);
        memset(run, 0, ((size_t)span + 2) * sizeof *run);
        for (int s = 0; s < ROW_SAMPLES; s++) {
            /* The sample line's height: evenly spread inside the row, none on its edges. */
            float sy = (float)y + ((float)s + 0.5f) / ROW_SAMPLES;
            int n = 0;
            int start = 0;
            for (int o = 0; o < outlines; o++) {
                for (int i = 0; i < counts[o]; i++) {
                    /* Each edge of this outline, the last point joined back to its first. */
                    Pt a = pts[start + i], b = pts[start + (i + 1) % counts[o]];
                    /* An edge crosses the line when its ends lie on either side (one end counted, never both). */
                    if ((a.y <= sy && b.y > sy) || (b.y <= sy && a.y > sy)) {
                        float t = (sy - a.y) / (b.y - a.y);
                        cross[n++].x = a.x + (b.x - a.x) * t;
                    }
                }
                start += counts[o];
            }
            if (n < 2)
                continue;
            qsort(cross, (size_t)n, sizeof *cross, by_x);
            /* Even-odd: inside between the first and second crossing, the third and fourth, and so on. */
            for (int i = 0; i + 1 < n; i += 2) {
                float xa = cross[i].x - (float)x0, xb = cross[i + 1].x - (float)x0;
                if (xa < 0)
                    xa = 0;
                if (xb > (float)span)
                    xb = (float)span;
                if (xb <= xa)
                    continue;
                int ia = (int)floorf(xa), ib = (int)floorf(xb);
                if (ia == ib) {
                    /* Inside one pixel: the part of it the span covers. */
                    cover[ia] += (xb - xa) / ROW_SAMPLES;
                    continue;
                }
                /* The first pixel's covered part, the run of whole ones between, the last one's part. */
                cover[ia] += ((float)(ia + 1) - xa) / ROW_SAMPLES;
                run[ia + 1] += 1.0f / ROW_SAMPLES;
                run[ib] -= 1.0f / ROW_SAMPLES;
                if (ib < span)
                    cover[ib] += (xb - (float)ib) / ROW_SAMPLES;
            }
        }
        /* The runs summed across into the row's coverage. */
        float acc = 0;
        for (int x = 0; x < span; x++) {
            acc += run[x];
            cover[x] += acc;
        }
        /* The row's colour (a gradient changes only downwards) blended in where the shape covers it. */
        uint32_t rgb = colour_at(paint, (float)y + 0.5f);
        uint32_t *row = c->px + (size_t)y * (size_t)c->w + x0;
        for (int x = 0; x < span; x++) {
            float k = cover[x];
            if (k > 0.002f)
                blend(&row[x], rgb, (k > 1.0f ? 1.0f : k) * paint->alpha);
        }
    }
    free(cover);
    free(run);
    free(cross);
}

void paint_polygon(Canvas *c, const Pt *pts, int n, const Paint *paint)
{
    paint_fill(c, pts, &n, 1, paint);
}

/* Points around a circle, `n` of them, starting at the right and going round clockwise on the screen. */
static void circle_points(float cx, float cy, float r, int n, Pt *out)
{
    for (int i = 0; i < n; i++) {
        float t = (float)i * 6.28318531f / (float)n;
        out[i].x = cx + r * cosf(t);
        out[i].y = cy + r * sinf(t);
    }
}

/* Enough points that the circle's edge never shows a corner: more for a larger circle, 96 at most. */
static int circle_steps(float r)
{
    int n = (int)(r * 3.0f) + 16;
    return n > 96 ? 96 : n;
}

void paint_circle(Canvas *c, float cx, float cy, float r, const Paint *paint)
{
    Pt pts[96];
    int n = circle_steps(r);
    circle_points(cx, cy, r, n, pts);
    paint_polygon(c, pts, n, paint);
}

void paint_ring(Canvas *c, float cx, float cy, float r, float width, const Paint *paint)
{
    Pt pts[192];
    int n = circle_steps(r + width / 2);
    /* The outer circle, then the inner one: even-odd leaves the band between them. */
    circle_points(cx, cy, r + width / 2, n, pts);
    circle_points(cx, cy, r - width / 2, n, pts + n);
    int counts[2] = {n, n};
    paint_fill(c, pts, counts, 2, paint);
}

void paint_line(Canvas *c, Pt a, Pt b, float width, const Paint *paint)
{
    float dx = b.x - a.x, dy = b.y - a.y;
    float len = sqrtf(dx * dx + dy * dy);
    float half = width / 2;
    if (len < 0.0001f) {
        /* No length: a dot as wide as the line. */
        paint_circle(c, a.x, a.y, half, paint);
        return;
    }
    /* Half the width across the line's direction, and half along it for the round ends. */
    float nx = -dy / len * half, ny = dx / len * half;
    float ux = dx / len, uy = dy / len;
    Pt pts[2 * 17];
    int n = 0;
    /* Round ends: a half circle at each end, joined by the line's two sides. */
    for (int i = 0; i <= 16; i++) {
        float t = (float)i / 16.0f * 3.14159265f;
        float cs = cosf(t), sn = sinf(t);
        pts[n].x = b.x + nx * cs + ux * half * sn;
        pts[n].y = b.y + ny * cs + uy * half * sn;
        n++;
    }
    for (int i = 0; i <= 16; i++) {
        float t = (float)i / 16.0f * 3.14159265f;
        float cs = cosf(t), sn = sinf(t);
        pts[n].x = a.x - nx * cs - ux * half * sn;
        pts[n].y = a.y - ny * cs - uy * half * sn;
        n++;
    }
    paint_polygon(c, pts, n, paint);
}

void paint_rect(Canvas *c, int x, int y, int w, int h, const Paint *paint)
{
    /* Clipped to the canvas. */
    int xa = x < 0 ? 0 : x, ya = y < 0 ? 0 : y;
    int xb = x + w > c->w ? c->w : x + w, yb = y + h > c->h ? c->h : y + h;
    for (int row = ya; row < yb; row++) {
        uint32_t rgb = colour_at(paint, (float)row + 0.5f);
        for (int col = xa; col < xb; col++)
            blend(&c->px[(size_t)row * (size_t)c->w + col], rgb, paint->alpha);
    }
}

void paint_coverage(Canvas *c, int x, int y, int w, int h, const uint8_t *coverage, int stride, uint32_t rgb,
                    float alpha)
{
    for (int row = 0; row < h; row++) {
        int cy = y + row;
        if (cy < 0 || cy >= c->h)
            continue;
        for (int col = 0; col < w; col++) {
            int cx = x + col;
            if (cx < 0 || cx >= c->w)
                continue;
            uint8_t k = coverage[(size_t)row * (size_t)stride + col];
            /* Each byte is how much of the pixel the text covers. */
            if (k)
                blend(&c->px[(size_t)cy * (size_t)c->w + cx], rgb, (float)k / 255.0f * alpha);
        }
    }
}

void paint_coverage_paint(Canvas *c, int x, int y, int w, int h, const uint8_t *coverage, int stride,
                          const Paint *paint)
{
    for (int row = 0; row < h; row++) {
        int cy = y + row;
        if (cy < 0 || cy >= c->h)
            continue;
        /* The paint's colour at this row of the canvas (a gradient runs down the words as it would down a shape). */
        uint32_t rgb = colour_at(paint, (float)cy + 0.5f);
        for (int col = 0; col < w; col++) {
            int cx = x + col;
            if (cx < 0 || cx >= c->w)
                continue;
            uint8_t k = coverage[(size_t)row * (size_t)stride + col];
            /* Each byte is how much of the pixel the text covers, times the paint's own opacity. */
            if (k)
                blend(&c->px[(size_t)cy * (size_t)c->w + cx], rgb, (float)k / 255.0f * paint->alpha);
        }
    }
}

void paint_image(Canvas *c, const Canvas *src, float x, float y, float w, float h)
{
    if (!c || !src || src->w <= 0 || src->h <= 0 || w <= 0 || h <= 0)
        return;
    /* The picture's pixels per canvas pixel, across and down. */
    float kx = (float)src->w / w, ky = (float)src->h / h;
    /* The canvas pixels the box touches, kept on the canvas. */
    int x0 = (int)floorf(x), y0 = (int)floorf(y), x1 = (int)ceilf(x + w), y1 = (int)ceilf(y + h);
    if (x0 < 0)
        x0 = 0;
    if (y0 < 0)
        y0 = 0;
    if (x1 > c->w)
        x1 = c->w;
    if (y1 > c->h)
        y1 = c->h;
    for (int ty = y0; ty < y1; ty++) {
        /* The rows of the picture this canvas row covers, as fractions, held to the picture. */
        float sy0 = ((float)ty - y) * ky, sy1 = ((float)ty + 1 - y) * ky;
        if (sy0 < 0)
            sy0 = 0;
        if (sy1 > (float)src->h)
            sy1 = (float)src->h;
        if (sy1 <= sy0)
            continue;
        for (int tx = x0; tx < x1; tx++) {
            float sx0 = ((float)tx - x) * kx, sx1 = ((float)tx + 1 - x) * kx;
            if (sx0 < 0)
                sx0 = 0;
            if (sx1 > (float)src->w)
                sx1 = (float)src->w;
            if (sx1 <= sx0)
                continue;
            /* Each covered picture pixel weighed by the part of it inside this canvas pixel. */
            float sum[4] = {0, 0, 0, 0};
            for (int sy = (int)sy0; sy < (int)ceilf(sy1) && sy < src->h; sy++) {
                float wy = fminf(sy1, (float)sy + 1) - fmaxf(sy0, (float)sy);
                if (wy <= 0)
                    continue;
                for (int sx = (int)sx0; sx < (int)ceilf(sx1) && sx < src->w; sx++) {
                    float wx = fminf(sx1, (float)sx + 1) - fmaxf(sx0, (float)sx);
                    if (wx <= 0)
                        continue;
                    uint32_t p = src->px[(size_t)sy * (size_t)src->w + sx];
                    float k = wx * wy;
                    sum[0] += (float)(p >> 24) * k;
                    sum[1] += (float)((p >> 16) & 0xff) * k;
                    sum[2] += (float)((p >> 8) & 0xff) * k;
                    sum[3] += (float)(p & 0xff) * k;
                }
            }
            /* Divided by a whole canvas pixel's area in the picture: a pixel the box only partly covers is that
             * much less covered. */
            float area = kx * ky;
            float a = sum[0] / area, r = sum[1] / area, g = sum[2] / area, b = sum[3] / area;
            if (a <= 0.0f)
                continue;
            /* Premultiplied over what is there. */
            uint32_t *d = &c->px[(size_t)ty * (size_t)c->w + tx];
            float keep = 1.0f - a / 255.0f;
            float da = (float)(*d >> 24), dr = (float)((*d >> 16) & 0xff), dg = (float)((*d >> 8) & 0xff),
                  db = (float)(*d & 0xff);
            uint32_t oa = (uint32_t)fminf(255.0f, a + da * keep + 0.5f), orr = (uint32_t)fminf(255.0f, r + dr * keep + 0.5f),
                     og = (uint32_t)fminf(255.0f, g + dg * keep + 0.5f), ob = (uint32_t)fminf(255.0f, b + db * keep + 0.5f);
            *d = (oa << 24) | (orr << 16) | (og << 8) | ob;
        }
    }
}

void lean_outline(float x, float y, float w, float h, float grow, Pt out[4])
{
    /* The same outline as art.py's lean_outline: top-left, top-right, foot-right, foot-left. */
    float lean = PAINT_LEAN * h;
    float side = grow * sqrtf(1.0f + PAINT_LEAN * PAINT_LEAN);
    float top = y - grow, foot = y + h + grow;
    out[0].x = x + lean + PAINT_LEAN * grow - side;
    out[0].y = top;
    out[1].x = x + w + PAINT_LEAN * grow + side;
    out[1].y = top;
    out[2].x = x + w - lean - PAINT_LEAN * grow + side;
    out[2].y = foot;
    out[3].x = x - PAINT_LEAN * grow - side;
    out[3].y = foot;
}

void tab_outline(float x, float y, float w, float h, float slant, Pt out[4])
{
    /* As art.py's dialog_panel draws the tab: full width at the top, `slant` in at each side at its foot. */
    out[0].x = x;
    out[0].y = y;
    out[1].x = x + w;
    out[1].y = y;
    out[2].x = x + w - slant;
    out[2].y = y + h;
    out[3].x = x + slant;
    out[3].y = y + h;
}

/* ------------------------------------------------------------------------------------------------- the cursor */

/* A point of the dart's own drawing (tip at 0,0, pointing down its axis, 32-pixel units) placed on the canvas:
 * leaned by `lean` radians so its left edge stands upright as a pointer's does, moved so the tip sits at (tip, tip),
 * scaled by k. */
static Pt place(float x, float y, float lean, float tip, float k)
{
    Pt p;
    p.x = (x * cosf(lean) + y * sinf(lean) + tip) * k;
    p.y = (-x * sinf(lean) + y * cosf(lean) + tip) * k;
    return p;
}

/* A line `width` wide along every edge of an outline, round at its corners. */
static void rim(Canvas *c, const Pt *pts, int n, float width, const Paint *paint)
{
    for (int i = 0; i < n; i++)
        paint_line(c, pts[i], pts[(i + 1) % n], width, paint);
}

/* The highest and lowest point of an outline, for the gradients that run from its top to its foot. */
static void extent(const Pt *pts, int n, float *top, float *foot)
{
    *top = 1e9f;
    *foot = -1e9f;
    for (int i = 0; i < n; i++) {
        if (pts[i].y < *top)
            *top = pts[i].y;
        if (pts[i].y > *foot)
            *foot = pts[i].y;
    }
}

int offset_outline(const Pt *pts, int n, float d, Pt *out)
{
    /* Which way the outline runs (its signed area): inward is to the right of a clockwise one on screen. */
    float area = 0;
    for (int i = 0; i < n; i++) {
        Pt a = pts[i], b = pts[(i + 1) % n];
        area += a.x * b.y - b.x * a.y;
    }
    float side = area > 0 ? 1.0f : -1.0f;
    for (int i = 0; i < n; i++) {
        /* The two edges that meet at this corner, each moved inward by d. */
        Pt p0 = pts[(i + n - 1) % n], p1 = pts[i], p2 = pts[(i + 1) % n];
        float ax = p1.x - p0.x, ay = p1.y - p0.y, bx = p2.x - p1.x, by = p2.y - p1.y;
        float la = sqrtf(ax * ax + ay * ay), lb = sqrtf(bx * bx + by * by);
        if (la < 1e-6f || lb < 1e-6f)
            return 0;
        /* Each edge's inward normal (screen y runs down, so "right of the direction" is (-dy, dx) for this sign). */
        float nax = -ay / la * side, nay = ax / la * side, nbx = -by / lb * side, nby = bx / lb * side;
        /* The corner moves along the bisector of the two normals, far enough that both edges move by d (a mitre). */
        float mx = nax + nbx, my = nay + nby;
        float dot = mx * nax + my * nay;
        if (dot < 0.2f)
            dot = 0.2f;
        out[i].x = p1.x + mx * d / dot;
        out[i].y = p1.y + my * d / dot;
    }
    return 1;
}

/* The logo's chrome (art.py CHROME): bright, the dark band where the horizon reflects, bright again. */
static const Stop CHROME[5] = {{0.0f, 0xffffff}, {0.44f, 0xe3e8ee}, {0.53f, 0x727c88}, {0.72f, 0xb6bec7},
                               {1.0f, 0xf3f5f8}};
/* The logo's 3 (art.py lit_chrome with the lit blue): chrome at its head turning blue towards its foot. */
static const Stop LIT_BLUE[4] = {{0.0f, 0xffffff}, {0.38f, 0xe9eefc}, {0.6f, RGB_BLUE_HI}, {1.0f, RGB_BLUE_HI}};
/* The title disc's glowing core, its lit facet and its shaded one. */
static const Stop CORE_LIT[3] = {{0.0f, 0xbfe9ff}, {0.4f, 0x5fc8ff}, {1.0f, 0x2a7af0}};
static const Stop CORE_SHADE[3] = {{0.0f, 0x6f9dff}, {0.5f, RGB_BLUE}, {1.0f, RGB_BLUE_DEEP}};
/* STAR MIXING's lime, for the one candidate in another game colour. */
static const Stop LIME_LIT[3] = {{0.0f, 0xeaffb0}, {0.45f, 0xb4f02a}, {1.0f, 0x6fa80c}};
static const Stop LIME_SHADE[3] = {{0.0f, 0xb4f02a}, {0.5f, 0x7fb814}, {1.0f, 0x3c6206}};
/* Pressed: the core's blue all over, lit at the top and deep at the foot. */
static const Stop BLUE_ONLY[3] = {{0.0f, 0x9fc0ff}, {0.45f, RGB_BLUE_HI}, {1.0f, RGB_BLUE}};

/* A gradient through the given stops between heights y0 and y1. */
static Paint ramp_of(const Stop *stops, int n, float y0, float y1)
{
    Paint p;
    memset(&p, 0, sizeof p);
    p.nstops = n;
    memcpy(p.stops, stops, (size_t)n * sizeof *stops);
    p.y0 = y0;
    p.y1 = y1;
    p.alpha = 1.0f;
    return p;
}

void paint_cursor(Canvas *c, int look, int pressed, int *hot_x, int *hot_y)
{
    const float k = (float)c->w / 32.0f;
    /* The lean that makes the dart's left edge upright, and where its tip sits (the hot spot), in 32-pixel units. */
    const float lean = 22.5f * 3.14159265f / 180.0f, tip = 3.2f;
    /* Pressed, the dart is a little smaller, as if pressed into the screen. */
    const float size = pressed ? 0.88f : 1.0f;
    const float h = 22.0f * size, half = 8.6f * size, notch = 6.2f * size;
    Pt outline[8];
    int n = 0;
    /* The axis point between the wings, where the core's two facets meet. */
    int axis = 2;
    if (look == 2) {
        /* A shard: a triangle with no notch, its tail cut on the game's lean (the right wing shorter). */
        outline[n++] = place(0, 0, lean, tip, k);
        outline[n++] = place(-half, h, lean, tip, k);
        outline[n++] = place(half, h - 2 * half * PAINT_LEAN, lean, tip, k);
        axis = -1;
    } else if (look == 3) {
        /* A notched dart whose wings end in short cuts on the game's lean, as its plates do. */
        float cut = 2.6f * size;
        outline[n++] = place(0, 0, lean, tip, k);
        outline[n++] = place(-half, h - cut * 0.8f, lean, tip, k);
        outline[n++] = place(-half + cut * 0.9f, h, lean, tip, k);
        outline[n++] = place(0, h - notch, lean, tip, k);
        outline[n++] = place(half - cut * 0.9f, h, lean, tip, k);
        outline[n++] = place(half, h - cut * 0.8f, lean, tip, k);
        axis = 3;
    } else {
        /* The plain notched dart: the tip, a wing either side, the notch between them on the axis. */
        outline[n++] = place(0, 0, lean, tip, k);
        outline[n++] = place(-half, h, lean, tip, k);
        outline[n++] = place(0, h - notch, lean, tip, k);
        outline[n++] = place(half, h, lean, tip, k);
    }
    float top, foot;
    extent(outline, n, &top, &foot);
    /* The soft shadow: the outline a little down and to the right. */
    Paint shade = paint_solid(0x000000, 0.32f);
    Pt moved[8];
    for (int i = 0; i < n; i++) {
        moved[i].x = outline[i].x + 1.0f * k;
        moved[i].y = outline[i].y + 1.6f * k;
    }
    paint_polygon(c, moved, n, &shade);
    rim(c, moved, n, 2.0f * k, &shade);
    /* A dark hairline outside everything: the dart stays seen on the game's white and bright screens. */
    Paint dark = paint_solid(0x07090c, 1.0f);
    rim(c, outline, n, 2.6f * k, &dark);
    if (pressed) {
        /* Pressed: all of it the core's blue, its edge a lighter blue, a little smaller. */
        Paint blue = ramp_of(BLUE_ONLY, 3, top, foot);
        paint_polygon(c, outline, n, &blue);
        Pt inner[8];
        if (offset_outline(outline, n, 2.0f * k, inner)) {
            Paint deep = ramp_of(CORE_SHADE, 3, top, foot);
            paint_polygon(c, inner, n, &deep);
        }
    } else if (look == 0) {
        /* Two faces split on the axis: the left chrome, the right the logo's 3 (the sister project's build). */
        Paint chrome = ramp_of(CHROME, 5, top, foot);
        Paint three = ramp_of(LIT_BLUE, 4, top, foot);
        Pt left_face[3] = {outline[0], outline[1], outline[2]};
        Pt right_face[3] = {outline[0], outline[2], outline[3]};
        paint_polygon(c, left_face, 3, &chrome);
        paint_polygon(c, right_face, 3, &three);
    } else if (look == 1) {
        /* One piece in the 3's material: chrome at the tip turning blue towards the wings. */
        Paint three = ramp_of(LIT_BLUE, 4, top, foot);
        paint_polygon(c, outline, n, &three);
    } else {
        /* The title disc's build: a chrome edge round a glowing core of two facets (lit left, shaded right). */
        Paint chrome = ramp_of(CHROME, 5, top, foot);
        paint_polygon(c, outline, n, &chrome);
        Pt inner[8];
        if (!offset_outline(outline, n, 1.8f * k, inner))
            memcpy(inner, outline, sizeof outline);
        float ct, cf;
        extent(inner, n, &ct, &cf);
        const Stop *lit = look == 4 ? LIME_LIT : CORE_LIT, *shaded = look == 4 ? LIME_SHADE : CORE_SHADE;
        Paint lit_paint = ramp_of(lit, 3, ct, cf), shade_paint = ramp_of(shaded, 3, ct, cf);
        /* A thin dark seam between chrome and core, as the disc's ring sits round its well. */
        Paint seam = paint_solid(0x07090c, 0.8f);
        rim(c, inner, n, 0.7f * k, &seam);
        paint_polygon(c, inner, n, &shade_paint);
        if (axis >= 0) {
            /* The lit facet: from the tip down the left wing to the axis point. */
            Pt facet[4];
            int m = 0;
            for (int i = 0; i <= axis; i++)
                facet[m++] = inner[i];
            paint_polygon(c, facet, m, &lit_paint);
        } else {
            /* The shard: its lit facet from the tip to the middle of the tail. */
            Pt facet[3] = {inner[0], inner[1], {(inner[1].x + inner[2].x) / 2, (inner[1].y + inner[2].y) / 2}};
            paint_polygon(c, facet, 3, &lit_paint);
        }
    }
    /* The hot spot: the dart's tip. */
    *hot_x = (int)lroundf(tip * k);
    *hot_y = (int)lroundf(tip * k);
}
