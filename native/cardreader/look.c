/*
 * The in-game layer's pictures (look.h), drawn with paint.c only.
 */
#include "look.h"

#include <math.h>
#include <stdio.h>
#include <string.h>


/* Korean labels' size against the English capitals' (look.h): at 1.25 its strokes are as thick as the capitals' (15 of
 * 100 pixels each) and a label carries 79 % of the English one's ink (51 % at the same size), measured on Pretendard
 * Bold; larger, it would outgrow the panel's title. */
const float look_ko_label = 1.25f;

/* ------------------------------------------------------------------------------------------------ helpers */

void sprite_make(Sprite *s, float w, float h, float room)
{
    /* Whole pixels: the box and its room on both sides, rounded up so nothing is cut. */
    int cw = (int)ceilf(w + 2 * room), ch = (int)ceilf(h + 2 * room);
    s->room = room;
    s->content = canvas_new(cw, ch);
    s->mask = canvas_new(cw, ch);
}

void sprite_free(Sprite *s)
{
    canvas_free(s->content);
    canvas_free(s->mask);
    s->content = s->mask = NULL;
}

/* A gradient through `n` stops between heights y0 and y1, at an opacity. */
static Paint ramp_stops(const Stop *stops, int n, float y0, float y1, float alpha)
{
    Paint p;
    memset(&p, 0, sizeof p);
    p.nstops = n;
    memcpy(p.stops, stops, (size_t)n * sizeof *stops);
    p.y0 = y0;
    p.y1 = y1;
    p.alpha = alpha;
    return p;
}

/* A rectangle with rounded corners of radius r as an outline (clockwise from the top left's arc), into out; its
 * point count. Six steps a corner keep a 5 pixel radius smooth at any size the layer draws. */
static int round_rect(float x, float y, float w, float h, float r, Pt *out)
{
    if (r > w / 2)
        r = w / 2;
    if (r > h / 2)
        r = h / 2;
    /* The four corners' centres, in the order the outline goes round. */
    const float cx[4] = {x + r, x + w - r, x + w - r, x + r};
    const float cy[4] = {y + r, y + r, y + h - r, y + h - r};
    int n = 0;
    for (int k = 0; k < 4; k++) {
        /* Each corner's arc: a quarter turn, starting where the last one ended (left, top, right, foot). */
        float a0 = 3.14159265f * (1.0f + 0.5f * (float)k);
        for (int i = 0; i <= 6; i++) {
            float a = a0 + 3.14159265f * 0.5f * (float)i / 6.0f;
            out[n].x = cx[k] + r * cosf(a);
            out[n].y = cy[k] + r * sinf(a);
            n++;
        }
    }
    return n;
}

/* A box's four corners as an outline, clockwise from the top left. */
static void rect_points(float x, float y, float w, float h, Pt out[4])
{
    out[0] = (Pt){x, y};
    out[1] = (Pt){x + w, y};
    out[2] = (Pt){x + w, y + h};
    out[3] = (Pt){x, y + h};
}

/* The game's title tab hanging from a top edge: as wide as the box at its top, each end leaning in by the game's
 * slope (30 over 37) down to its foot. */
static void tab_points(const Box *b, Pt out[4])
{
    float lean = b->h * 30.0f / 37.0f;
    out[0] = (Pt){b->x, b->y};
    out[1] = (Pt){b->x + b->w, b->y};
    out[2] = (Pt){b->x + b->w - lean, b->y + b->h};
    out[3] = (Pt){b->x + lean, b->y + b->h};
}

/* Where the glass is: the shape filled solid on the mask. */
static void glass(Sprite *s, const Pt *pts, int n)
{
    Paint solid = paint_solid(0xffffff, 1.0f);
    paint_polygon(s->mask, pts, n, &solid);
}

/* A soft shadow round a shape on the content, falling a little below it (the game's notice casts one): rings round
 * the outline, grown step by step and moved 2 down, each fainter. Only the rings are filled (the outline itself left
 * out by the even-odd rule): under the glass a shadow would never show, and filling it there was most of a panel's
 * drawing time. */
static void shadow(Canvas *c, const Pt *pts, int n, float u, float strength)
{
    Pt both[128];
    if (n > 64)
        return;
    for (int i = 4; i >= 1; i--) {
        /* Grown by i steps of 1.5 game pixels, and moved 2 down, so it shows most under the shape. */
        float d = -1.5f * u * (float)i;
        if (!offset_outline(pts, n, d, both))
            continue;
        for (int k = 0; k < n; k++)
            both[k].y += 2.0f * u;
        /* The shape's own outline as the ring's hole. */
        memcpy(both + n, pts, (size_t)n * sizeof *pts);
        int counts[2] = {n, n};
        Paint shade = paint_solid(0x000000, strength * 0.09f);
        paint_fill(c, both, counts, 2, &shade);
    }
}

/* A line along an outline's edge from point a to point b, `width` thick. */
static void edge(Canvas *c, Pt a, Pt b, float width, const Paint *p)
{
    paint_line(c, a, b, width, p);
}

/* The game's metal frame round a box that hangs from the bar's foot (q: its four corners, clockwise from the top
 * left), lit as its dialogs' frames are (measured: #dfe0e1 right, #868c8f left, #72767a foot): down its right side,
 * along its foot and up its left side; its top is the bar's foot line, which it comes out from under. `t` is its
 * thickness. */
static void metal_hung(Canvas *c, const Pt q[4], float t, float y0, float y1)
{
    Stop metal[4] = {{0.0f, 0xd6dde0}, {0.25f, 0xa7b1b6}, {0.7f, 0x7a848a}, {1.0f, 0x5b6268}};
    Paint p = ramp_stops(metal, 4, y0, y1, 1.0f);
    /* The right side, the foot, the left side: the edges after the top one. */
    for (int i = 1; i < 4; i++)
        edge(c, q[i], q[(i + 1) % 4], t, &p);
}

/* The game's glossy two-tone button (NO ID CARD, measured): a light top, a hard step at the middle to a deep colour
 * that lightens towards the foot, a light inner rim, a thin dark edge, corners of radius 5. The game's own white
 * label sits on its light half at 2.1:1; here the light stays above the letters (its top fifth) and the band behind
 * them is the button's darker blue, so white words keep 4.5:1 or more in both languages. */
typedef struct {
    uint32_t top, upper, lower, deep, foot, rim, outline;
} Gloss;
/* The game's own blue (its button) for going on. */
static const Gloss BLUE = {0x8ec2ea, 0x2f6ea3, 0x2a6599, 0x163d63, 0x2a5f92, 0xc9e0f2, 0x1d4a75};
/* Red for the answer that ends the game: the same light top and hard step, white words 6.8:1 on its middle. */
static const Gloss RED = {0xf2a7a7, 0xb8333b, 0xa82c34, 0x6b1219, 0x8e2129, 0xf5cdd0, 0x4f0c12};
/* The question's quiet answer: the launcher's quiet metal (the bar's chips') in the same glossy two-tone, white words
 * 8.3:1 on its middle. Quitting wears it until it is the answer chosen (under the pointer or the keys' ring), then the
 * red: the answer that ends a song is never the loudest thing on the screen, as OpenDMTQ's quit is its quiet button. */
static const Gloss METAL = {0x9aa4ae, 0x4a5561, 0x46505c, 0x2b323b, 0x3a434e, 0xc3cbd2, 0x1c2228};

/* One glossy button in a box: lit when under the pointer, sunk a little when held. */
static void gloss_button(Canvas *c, const Box *b0, const Gloss *g, float u, int lit, int held)
{
    Box b = *b0;
    /* Held, it goes down a pixel, as a key does. */
    if (held)
        b.y += 1.0f * u;
    Pt q[28], inner[28];
    float r = 5.0f * u;
    int n = round_rect(b.x, b.y, b.w, b.h, r, q);
    /* The thin dark edge all round (the button's own outline against whatever is behind). */
    Paint outline = paint_solid(g->outline, 1.0f);
    paint_polygon(c, q, n, &outline);
    /* Inside it, the rim: the light line a pixel in. */
    int m = round_rect(b.x + 1.0f * u, b.y + 1.0f * u, b.w - 2.0f * u, b.h - 2.0f * u, r - 1.0f * u, inner);
    Paint rim = paint_ramp(g->rim, g->upper, b.y, b.y + b.h * 0.6f, 1.0f);
    paint_polygon(c, inner, m, &rim);
    /* The face: the light top falling to the darker blue by a fifth of the way down (above the letters, Korean's
     * taller ones too), then the hard step at the middle to the deep half that lightens towards the foot. */
    float in = 2.0f * u;
    m = round_rect(b.x + in, b.y + in, b.w - 2 * in, b.h - 2 * in, r - in, inner);
    Stop face[5] = {{0.0f, g->top}, {0.2f, g->upper}, {0.499f, g->lower}, {0.5f, g->deep}, {1.0f, g->foot}};
    Paint p = ramp_stops(face, 5, b.y + in, b.y + b.h - in, 1.0f);
    paint_polygon(c, inner, m, &p);
    /* Under the pointer the whole face lightens (held, it darkens), so the answer the click will take is seen. */
    if (lit || held) {
        Paint over = paint_solid(held ? 0x000000 : 0xffffff, held ? 0.18f : 0.14f);
        paint_polygon(c, inner, m, &over);
    }
}

/* The keyboard's ring round a box: the game's light blue, two pixels out from the button's edge, as the game marks
 * its own choice with a lit frame. */
static void key_ring(Canvas *c, const Box *b, float u)
{
    Pt q[28], inner[28];
    float g = 3.0f * u, t = 2.0f * u;
    int n = round_rect(b->x - g - t, b->y - g - t, b->w + 2 * (g + t), b->h + 2 * (g + t), 7.0f * u, q);
    int m = round_rect(b->x - g, b->y - g, b->w + 2 * g, b->h + 2 * g, 6.0f * u, inner);
    /* A ring: the outer outline and the inner one, filled by the even-odd rule. */
    Pt both[56];
    memcpy(both, q, (size_t)n * sizeof *q);
    memcpy(both + n, inner, (size_t)m * sizeof *inner);
    int counts[2] = {n, m};
    Paint ring = paint_solid(RGB_ACCENT, 1.0f);
    paint_fill(c, both, counts, 2, &ring);
}

/* A chip's glyph, white with a faint dark edge, centred in its box: the menu's three bars, minimise's one bar low,
 * full screen's four corners pointing out (back to a window: pointing in), the X. Sized by the chip's height. */
enum { GLYPH_MENU, GLYPH_MIN, GLYPH_FULL, GLYPH_WINDOW, GLYPH_X };
static void glyph(Canvas *c, const Box *b, float u, int kind, uint32_t rgb)
{
    float cx = b->x + b->w / 2, cy = b->y + b->h / 2;
    float stroke = 2.2f * u, s = b->h;
    Paint ink = paint_solid(0x05070a, 0.45f), face = paint_solid(rgb, 1.0f);
    for (int pass = 0; pass < 2; pass++) {
        /* The dark edge first, a little wider, then the glyph over it. */
        const Paint *p = pass ? &face : &ink;
        float w = pass ? stroke : stroke + 1.6f * u;
        if (kind == GLYPH_X) {
            float h = s * 0.2f;
            paint_line(c, (Pt){cx - h, cy - h}, (Pt){cx + h, cy + h}, w, p);
            paint_line(c, (Pt){cx - h, cy + h}, (Pt){cx + h, cy - h}, w, p);
        } else if (kind == GLYPH_MENU) {
            float h = s * 0.24f, step = s * 0.17f;
            for (int i = -1; i <= 1; i++)
                paint_line(c, (Pt){cx - h, cy + (float)i * step}, (Pt){cx + h, cy + (float)i * step}, w, p);
        } else if (kind == GLYPH_MIN) {
            /* One bar under the middle, where a window goes down to. */
            float h = s * 0.22f;
            paint_line(c, (Pt){cx - h, cy + s * 0.18f}, (Pt){cx + h, cy + s * 0.18f}, w, p);
        } else {
            /* Four corners round a square 0.46 of the chip's height across, each arm a third of its side; for the way
             * back to a window the corners turn round, pointing in. */
            float h = s * 0.23f, arm = s * 0.15f;
            int in = kind == GLYPH_WINDOW;
            for (int k = 0; k < 4; k++) {
                float sx = (k & 1) ? 1.0f : -1.0f, sy = (k & 2) ? 1.0f : -1.0f;
                /* The corner's point, and its two arms running along the square's sides (inward: away from it). */
                Pt corner = {cx + sx * h, cy + sy * h};
                float ax = in ? sx * arm : -sx * arm, ay = in ? sy * arm : -sy * arm;
                if (in)
                    corner = (Pt){cx + sx * (h - arm), cy + sy * (h - arm)};
                paint_line(c, corner, (Pt){corner.x + ax, corner.y}, w, p);
                paint_line(c, corner, (Pt){corner.x, corner.y + ay}, w, p);
            }
        }
    }
}

/* The game's dark notice's sheen: light from the top left falling across the glass, a triangle from the top left
 * corner to 62 % of the top edge and down the left side, fading downwards (measured #81a2a6 at its top). */
static void sheen(Canvas *c, float x, float y, float w, float h, float strength)
{
    Pt tri[3] = {{x, y}, {x + w * 0.62f, y}, {x, y + h}};
    Stop fall[3] = {{0.0f, 0xb4d4d9}, {0.6f, 0x8ea7b4}, {1.0f, 0x6a7487}};
    Paint p = ramp_stops(fall, 3, y, y + h, strength);
    paint_polygon(c, tri, 3, &p);
}

/* -------------------------------------------------------------------------------------------------- the bar */

void look_bar(Sprite *s, const UiLayout *l, const Canvas *mark)
{
    canvas_clear(s->content);
    canvas_clear(s->mask);
    float u = l->u, o = s->room;
    float w = l->bar.w, h = l->bar.h;
    /* The bar in its sprite (its room below it holds its shadow). */
    Pt q[4];
    rect_points(o, o, w, h, q);
    glass(s, q, 4);
    /* Its shadow on the game under its foot: a few lines fading downwards. */
    for (int i = 0; i < 6; i++) {
        Paint shade = paint_solid(0x000000, 0.22f * (1.0f - (float)i / 6.0f));
        paint_rect(s->content, 0, (int)(o + h) + i, s->content->w, 1, &shade);
    }
    /* The game's notice's light across the glass from the top left. */
    sheen(s->content, o, o, w * 0.5f, h, 0.10f);
    /* The foot catching light: the game's metal, a light line over a dark one (two pixels each from 150 %). */
    Paint light = paint_solid(0xc9d2d6, 0.95f), dark = paint_solid(0x14181b, 1.0f);
    int t = u >= 1.5f ? 2 : 1;
    paint_rect(s->content, 0, (int)lroundf(o + h) - 2 * t, s->content->w, t, &light);
    paint_rect(s->content, 0, (int)lroundf(o + h) - t, s->content->w, t, &dark);
    /* The product's mark: the launcher's own picture of it (art.py logo, made into the DLL when it is built), drawn to
     * the layout's height in the bar's middle, never letters set in its face. */
    if (mark && mark->w > 0 && mark->h > 0) {
        float mh = l->name_h, mw = mh * (float)mark->w / (float)mark->h;
        paint_image(s->content, mark, o + l->name_x, o + (h - mh) / 2, mw, mh);
    }
}

/* The launcher's buttons (art.py BUTTON_LOOKS): the fill's top and foot for each state, its edge's top and foot (0 for
 * none: a light line along the top instead), and the glyph's colour. */
typedef struct {
    uint32_t top[3], foot[3];     /* normal, under the pointer, held */
    uint32_t edge_top, edge_foot; /* the one-pixel edge (edge_top 0: no edge) */
    uint32_t ink;
} ButtonLook;
/* The main action's look (the technika section's "info", the title screen's blue) and the quiet metal ("neutral").
 * Under the pointer each is lit further than the launcher's own (over the game's moving picture its step was too
 * small to see: the blue lit as PLAY lights, #8fb2ff into #3a6dff, the metal two steps up). */
static const ButtonLook MAIN = {{0x3d6ff5, 0x8fb2ff, 0x2a5ff0}, {0x2a5ff0, 0x3a6dff, 0x1d47c4}, 0, 0, 0xffffff};
static const ButtonLook QUIET = {{0x3a434e, 0x5f6b7a, 0x2b323b}, {0x2b323b, 0x46505c, 0x232931}, 0x5a6573, 0x343c47,
                                 0xeef2f6};

/* One of the launcher's buttons on a box: its leaning plate filled top to foot, its edge or its top's light line,
 * as art.py button_face draws it. */
static void launcher_button(Canvas *c, const Box *b, const ButtonLook *look, int state, float u)
{
    Pt q[4];
    lean_outline(b->x, b->y, b->w, b->h, 0, q);
    Paint fill = paint_ramp(look->top[state], look->foot[state], b->y, b->y + b->h, 1.0f);
    paint_polygon(c, q, 4, &fill);
    if (look->edge_top) {
        /* One pixel of edge all round (a pixel in from the plate's outline), lighter at the top. */
        Pt e[4];
        lean_outline(b->x, b->y, b->w - 1.0f, b->h - 1.0f, 0, e);
        Paint edge = paint_ramp(look->edge_top, look->edge_foot, b->y, b->y + b->h, 1.0f);
        for (int i = 0; i < 4; i++)
            paint_line(c, e[i], e[(i + 1) % 4], 1.0f * u, &edge);
    } else {
        /* A bright line along the top, the game's chrome highlight (as on PLAY): from where the top starts to its end. */
        Paint shine = paint_solid(0xffffff, 110.0f / 255.0f);
        float lean = PAINT_LEAN * b->h;
        paint_line(c, (Pt){b->x + lean, b->y + 1.5f * u}, (Pt){b->x + b->w - 2.0f * u, b->y + 1.5f * u}, 1.0f * u,
                   &shine);
    }
}

void look_chips(Sprite *s, const UiLayout *l, int hover, int pressed, int full)
{
    canvas_clear(s->content);
    canvas_clear(s->mask);
    float u = l->u, o = s->room;
    /* Over the bar's glass (they have none of their own): the X as the launcher's main button, the rest its quiet
     * metal, each lit under the pointer and darker held. */
    static const int glyphs[CHIPS] = {GLYPH_MENU, GLYPH_MIN, GLYPH_FULL, GLYPH_X};
    for (int i = 0; i < CHIPS; i++) {
        Box b = l->chip[i];
        b.x += o - l->chip[0].x;
        b.y += o - l->chip[0].y;
        const ButtonLook *look = i == CHIP_X ? &MAIN : &QUIET;
        int state = pressed == i ? 2 : hover == i ? 1 : 0;
        launcher_button(s->content, &b, look, state, u);
        /* Full screen's glyph says where the chip goes: to full screen, or back to a window when the game fills it. */
        int g = glyphs[i] == GLYPH_FULL && full ? GLYPH_WINDOW : glyphs[i];
        glyph(s->content, &b, u, g, look->ink);
    }
}

/* ------------------------------------------------------------------------------------------------ the mark */

void look_mark(Sprite *s, float u, int lit)
{
    canvas_clear(s->content);
    canvas_clear(s->mask);
    float o = s->room;
    /* The handle's box at its depth now (the sprite holds the lit one, the deeper): the rail across its top, the tab
     * hanging from the rail's middle. */
    float w = (float)s->content->w - 2 * o;
    float h = (lit ? 12.0f : 9.0f) * u;
    /* The rail: two game pixels along the top edge, the game's light metal (the bar's foot line); lit, the game's light
     * blue, as the game marks a choice. */
    Pt rail[4];
    rect_points(o, o, w, 2.0f * u, rail);
    Paint rp = lit ? paint_solid(RGB_ACCENT, 1.0f) : paint_solid(0xc9d2d6, 0.8f);
    /* The tab: 32 game pixels wide at the rail, its ends leaning in with the game's tab slope; a piece of the bar's dark
     * glass (its tint: no live blur, so the handle costs the game nothing), deeper while lit. */
    float tw = 32.0f * u;
    Box t = {o + (w - tw) / 2, o, tw, h};
    Pt q[4];
    tab_points(&t, q);
    Paint tint = paint_solid(GLASS_TINT, lit ? 0.92f : 0.78f);
    paint_polygon(s->content, q, 4, &tint);
    /* Its slanted ends in the game's metal, lit from the top, as the notice's are. */
    Stop metal[3] = {{0.0f, 0xb9c3c8}, {0.6f, 0x7a848a}, {1.0f, 0x5b6268}};
    Paint mp = ramp_stops(metal, 3, o, o + h, 1.0f);
    edge(s->content, q[1], q[2], 1.0f * u, &mp);
    edge(s->content, q[3], q[0], 1.0f * u, &mp);
    /* The rail over the tab's top. */
    paint_polygon(s->content, rail, 4, &rp);
    /* A chevron pointing down in the tab, under the rail: the bar comes down from here. 8 game pixels across, in the
     * rail's colour. */
    float cx = o + w / 2, cy = o + 2.0f * u + (h - 2.0f * u) / 2, half = 4.0f * u, fall = 2.6f * u;
    Paint cp = lit ? paint_solid(RGB_ACCENT, 1.0f) : paint_solid(0xdbe6ea, 0.92f);
    paint_line(s->content, (Pt){cx - half, cy - fall / 2}, (Pt){cx, cy + fall / 2}, 1.4f * u, &cp);
    paint_line(s->content, (Pt){cx, cy + fall / 2}, (Pt){cx + half, cy - fall / 2}, 1.4f * u, &cp);
}

/* ------------------------------------------------------------------------------------------ the menu and question */

void look_panel(Sprite *s, const Card *card, const UiLayout *l, int hover, int pressed, TextFn text, void *ctx)
{
    canvas_clear(s->content);
    canvas_clear(s->mask);
    float u = l->u, o = s->room;
    /* The panel's box in its sprite. */
    Box p = {o, o, l->panel.w, l->panel.h};
    Pt q[4];
    rect_points(p.x, p.y, p.w, p.h, q);
    shadow(s->content, q, 4, u, 1.0f);
    glass(s, q, 4);
    /* The game's dialog on its notice's glass: the sheen from the top left, the metal frame down its sides and along
     * its foot (it hangs from the bar's foot, whose line is its top). */
    sheen(s->content, p.x, p.y, p.w, p.h, 0.16f);
    metal_hung(s->content, q, 2.0f * u, p.y, p.y + p.h);
    const char *title = card_title(card), *line = card_line(card);
    if (title) {
        /* The title in the game's teal tab hanging from the top edge, in its body's weight as the game writes it. */
        Box t = {l->tab.x - l->panel.x + o, o + 1.0f * u, l->tab.w, l->tab.h};
        Pt tab[4];
        tab_points(&t, tab);
        /* The tab's colour, measured on the game's: teal-grey, lighter at its middle, a light line at its foot. */
        Stop teal[5] = {{0.0f, 0x85a1a9}, {0.55f, 0x98afb6}, {0.9f, 0x89a4ac}, {0.93f, 0xacbcc2}, {1.0f, 0x9fb3b9}};
        Paint tp = ramp_stops(teal, 5, t.y, t.y + t.h, 1.0f);
        paint_polygon(s->content, tab, 4, &tp);
        text(ctx, s->content, title, l->px_title, t.x + t.w / 2, t.y + t.h / 2, 0x0e1317, TEXT_REGULAR);
    }
    /* The one line, as the game writes its messages: a sentence in its regular face. */
    if (line)
        text(ctx, s->content, line, l->px_line, p.x + p.w / 2, l->line_y - l->panel.y + o, RGB_WORDS, TEXT_REGULAR);
    /* The answers. */
    for (int i = 0; i < l->count; i++) {
        int danger = 0;
        const char *words = card_label(card, i, &danger);
        Box b = l->rows[i];
        b.x += o - l->panel.x;
        b.y += o - l->panel.y;
        int lit = hover == i, held = pressed == i;
        /* Korean where English is in capitals: its own size, so both fill the button alike. */
        float px = card->korean ? l->px_button * look_ko_label : l->px_button;
        if (card->open == CARD_QUIT) {
            /* The question's two: going on in the game's blue; quitting in quiet metal, red once it is the answer chosen
             * (the pointer on it, held, or the keys' ring on it). */
            const Gloss *g = i == 0 ? &BLUE : lit || held || card->focus == i ? &RED : &METAL;
            gloss_button(s->content, &b, g, u, lit, held);
            text(ctx, s->content, words, px, b.x + b.w / 2, b.y + b.h / 2 + (held ? u : 0), 0xffffff, TEXT_EDGE);
        } else {
            /* The menu's rows: plain on the glass, the chosen one (the keys' or the pointer's) a glossy plate (red for
             * the row that quits, whose words are red when not chosen). */
            int chosen = card->focus == i || lit;
            if (chosen)
                gloss_button(s->content, &b, danger ? &RED : &BLUE, u, 0, held);
            else if (i > 0) {
                /* A hairline between rows, as the game's dotted separators. */
                Paint sep = paint_solid(0xffffff, 0.10f);
                paint_rect(s->content, (int)(b.x + 8 * u), (int)(b.y - 2.5f * u), (int)(b.w - 16 * u), 1, &sep);
            }
            uint32_t ink = chosen ? 0xffffff : danger ? RGB_DANGER : RGB_WORDS;
            text(ctx, s->content, words, px, b.x + 14 * u, b.y + b.h / 2 + (held ? u : 0), ink,
                 TEXT_LEFT | (chosen ? TEXT_EDGE : 0));
            /* A row's state at its right, as a switch shows it: on in the game's light blue, off quieter. */
            const char *state = card_state(card, i);
            if (state) {
                uint32_t sink = chosen ? 0xffffff : card->fps ? RGB_ACCENT : RGB_QUIET;
                text(ctx, s->content, state, px, b.x + b.w - 14 * u, b.y + b.h / 2 + (held ? u : 0), sink,
                     TEXT_RIGHT | (chosen ? TEXT_EDGE : 0));
            }
        }
    }
    /* The keys' ring on the question's answer they are on (the menu's chosen row is its glossy plate). */
    if (card->open == CARD_QUIT && card->focus >= 0 && card->focus < l->count) {
        Box b = l->rows[card->focus];
        b.x += o - l->panel.x;
        b.y += o - l->panel.y;
        key_ring(s->content, &b, u);
    }
}

/* ------------------------------------------------------------------------------------------------ the toast */

void look_toast(Sprite *s, float u, const char *words, TextFn text, void *ctx)
{
    canvas_clear(s->content);
    canvas_clear(s->mask);
    float o = s->room;
    float w = (float)s->content->w - 2 * o, h = (float)s->content->h - 2 * o;
    /* The game's tab as a card hanging from the top edge: wide at its top, leaning in to its foot. */
    Box b = {o, o, w, h};
    Pt q[4];
    tab_points(&b, q);
    shadow(s->content, q, 4, u, 1.0f);
    glass(s, q, 4);
    sheen(s->content, o, o, w, h, 0.14f);
    /* The metal edge down its ends and a light line along its foot (its top is the screen's edge). */
    Stop metal[3] = {{0.0f, 0xb9c3c8}, {0.6f, 0x7a848a}, {1.0f, 0x5b6268}};
    Paint mp = ramp_stops(metal, 3, o, o + h, 1.0f);
    edge(s->content, q[1], q[2], 1.5f * u, &mp);
    edge(s->content, q[3], q[0], 1.5f * u, &mp);
    Paint foot = paint_solid(0xc9d2d6, 0.95f);
    edge(s->content, q[2], q[3], 1.5f * u, &foot);
    text(ctx, s->content, words, 14 * u, o + w / 2, o + h / 2, RGB_WORDS, TEXT_REGULAR);
}

/* ------------------------------------------------------------------------------------------- the frame rate chip */

/* The chip's sizes, in game pixels: the number, and FPS and the frame's length (one line, as tall as the game's own
 * FREE PLAY beside it: their capitals 9 and 7 tall, FREE PLAY's 9). */
#define FPS_BIG 12.0f
#define FPS_SMALL 10.0f
/* Its words 6 in from each end: the number and FPS from its left, the frame's length to its right end (so neither moves
 * when the number gains a digit). */
#define FPS_PAD 6.0f

void look_fps_base(Sprite *s, float u)
{
    canvas_clear(s->content);
    canvas_clear(s->mask);
    float o = s->room;
    float w = (float)s->content->w - 2 * o, h = (float)s->content->h - 2 * o;
    /* The game's own badges in the same bottom band (ID CARD, NET, PATCH) are rounded boxes: the chip is one too. */
    Pt q[28];
    int n = round_rect(o, o, w, h, 4 * u, q);
    /* The bar's glass, faint (FPS_ALPHA: the game shows through it), its words over it whole. */
    Paint faint = paint_solid(0xffffff, FPS_ALPHA);
    paint_polygon(s->mask, q, n, &faint);
    /* The bar's light across the glass from the top left, and a thin silver edge lit along its top, faint with it. */
    sheen(s->content, o, o, w, h, 0.10f * FPS_ALPHA);
    Paint frame = paint_ramp(0xb9bec3, 0x3f444a, o, o + h, FPS_ALPHA);
    for (int i = 0; i < n; i++)
        edge(s->content, q[i], q[(i + 1) % n], 1.0f * u, &frame);
}

void look_fps_glyphs(float u, TextFn text, void *ctx)
{
    /* Measuring each set once makes its pieces: the number's digits, FPS, and the length's digits, point and unit. */
    text(ctx, NULL, "0123456789", FPS_BIG * u, 0, 0, 0, TEXT_WIDE | TEXT_GLYPHS);
    text(ctx, NULL, "FPS", FPS_SMALL * u, 0, 0, 0, TEXT_GLYPHS);
    text(ctx, NULL, "0123456789", FPS_SMALL * u, 0, 0, 0, TEXT_REGULAR | TEXT_GLYPHS);
    text(ctx, NULL, ".", FPS_SMALL * u, 0, 0, 0, TEXT_REGULAR | TEXT_GLYPHS);
    text(ctx, NULL, " ms", FPS_SMALL * u, 0, 0, 0, TEXT_REGULAR | TEXT_GLYPHS);
}

void look_fps(Sprite *s, const Sprite *base, float u, double fps, int mask_too, TextFn text, void *ctx)
{
    /* The glass and edge as drawn once for this size (a copy of whole rows: the two canvases are the same size); the
     * mask only the first time (the words are not in it). */
    if (base->content->w == s->content->w && base->content->h == s->content->h) {
        memcpy(s->content->px, base->content->px, (size_t)s->content->w * (size_t)s->content->h * 4);
        if (mask_too)
            memcpy(s->mask->px, base->mask->px, (size_t)s->mask->w * (size_t)s->mask->h * 4);
    } else {
        look_fps_base(s, u);
    }
    float o = s->room;
    float w = (float)s->content->w - 2 * o, h = (float)s->content->h - 2 * o;
    /* One line, its capitals' middle in the chip's: the number in white, in the wide face, with FPS after it in the
     * game's light blue (lighter, as small words on faint glass need), as OpenDMTQ's counter has its FPS in its game's
     * lime and the number in white; the frame's mean length at the right end, quieter (what a player reads: the
     * chain's own time goes to the log). Every piece kept, so no GDI work here. */
    char number[16], ms[16];
    double shown = fps < 0 ? 0.0 : fps > 999 ? 999.0 : fps;
    snprintf(number, sizeof number, "%.0f", shown);
    snprintf(ms, sizeof ms, "%.1f ms", shown > 0 ? 1000.0 / shown : 0.0);
    float big = FPS_BIG * u, small = FPS_SMALL * u, mid = o + h / 2;
    float wn = text(ctx, s->content, number, big, o + FPS_PAD * u, mid, RGB_WORDS, TEXT_WIDE | TEXT_LEFT | TEXT_GLYPHS);
    text(ctx, s->content, "FPS", small, o + FPS_PAD * u + wn + 3 * u, mid, RGB_ACCENT_SMALL, TEXT_LEFT | TEXT_GLYPHS);
    text(ctx, s->content, ms, small, o + w - FPS_PAD * u, mid, RGB_QUIET, TEXT_REGULAR | TEXT_RIGHT | TEXT_GLYPHS);
}

void look_cursor(Canvas *c, int pressed, int *hot_x, int *hot_y)
{
    paint_cursor(c, CURSOR_CHOSEN, pressed, hot_x, hot_y);
}
