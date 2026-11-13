/*
 * The in-game layer's pictures, after TECHNIKA 3's own panels (measured on the game's screens: its dialogs' title tab
 * and metal frame, its dark notice's smoked glass, its glossy two-tone buttons) in an opaque frosted glass. Each part
 * of the layer is a sprite: a picture of what is drawn over the glass (edges, words, buttons, shadows) and a mask of
 * where the glass is. The glass itself (the game's frame behind, blurred and tinted dark) is made in the Present chain
 * (ui.c), which lays the picture over it. No Windows calls: the words come through a TextFn, which the DLL backs with
 * GDI (text.c) and the native tests with a stand-in.
 */
#ifndef OPENDMT3_LOOK_H
#define OPENDMT3_LOOK_H

#include "logic.h"
#include "paint.h"

/* How a TextFn draws: a faint dark edge round the letters, the face (Pretendard Bold unless one of these), a chrome
 * ramp in place of the colour, and where cx is (the words' middle unless one of these). */
#define TEXT_EDGE 1
#define TEXT_REGULAR 2
#define TEXT_WIDE 4
#define TEXT_CHROME 8
#define TEXT_LEFT 16
#define TEXT_RIGHT 32
/* With TEXT_CHROME: the chrome lit into the logo's blue towards its foot (the 3 of the product's mark). */
#define TEXT_BLUE 64
/* Changing numbers (the chip's): drawn from pieces kept for good, each digit alone in a cell as wide as the widest
 * digit (so a number does not shift as it changes) and each run of other characters as one piece; a piece is made by
 * GDI the first time it is drawn at a size, never again. */
#define TEXT_GLYPHS 128

/* Draw `utf8` at `px` pixels, its capitals' middle on cy and placed across by cx as the flags say, in `rgb`; or, when
 * `c` is NULL, only measure it. Returns the words' width in pixels. */
typedef float (*TextFn)(void *ctx, Canvas *c, const char *utf8, float px, float cx, float cy, uint32_t rgb, int flags);

/* One part of the layer as pictures: `content` (premultiplied, laid over the glass and the game) and `mask` (its
 * opacity is where the glass shows), both the part's box grown by `room` on every side (for shadows and the keys'
 * ring), so the part's box starts at (room, room) in them. */
typedef struct {
    Canvas *content, *mask;
    float room;
} Sprite;

/* Make a sprite's two canvases for a box of w x h with `room` round it (NULL canvases when memory runs out). */
void sprite_make(Sprite *s, float w, float h, float room);
void sprite_free(Sprite *s);

/* The bar: its glass, the product's mark at its left, its lit foot. Its sprite is the bar's box. `mark` is the
 * launcher's own picture of the mark (premultiplied, any size: drawn to the layout's height for it), NULL for none. */
void look_bar(Sprite *s, const UiLayout *l, const Canvas *mark);
/* The bar's chips at its right (CHIP_*: the menu, minimise, full screen or back to a window, the X), in the
 * launcher's button shape and looks: the X as its main button (the title screen's blue), the others its quiet metal.
 * `hover` and `pressed` are the chips under the pointer and held (-1 none); `full` whether the game fills the screen
 * now (the full screen chip then shows the way back to a window). Its sprite spans the four, from the menu chip's top
 * left. */
void look_chips(Sprite *s, const UiLayout *l, int hover, int pressed, int full);
/* The mark at the top centre, the bar's handle (ui_mark_box): a rail along the top edge and a small tab of the bar's
 * dark glass hanging from it in the game's tab shape, a chevron in it pointing down; rail and chevron in the game's
 * light blue while the pointer is on it, the tab deeper then. Its sprite is the lit handle's box; no glass of its own
 * (the tab is the glass's tint alone, so the handle needs no live blur). */
void look_mark(Sprite *s, float u, int lit);
/* The open menu or question, a sheet hanging from the bar's foot: its sprite is the panel's box, its metal frame down
 * its sides and along its foot. `hover` and `pressed` are answers (-1 none); the keys' ring is on card->focus. */
void look_panel(Sprite *s, const Card *card, const UiLayout *l, int hover, int pressed, TextFn text, void *ctx);
/* A toast with one line of words: its sprite is toast_box's. */
void look_toast(Sprite *s, float u, const char *words, TextFn text, void *ctx);
/* The frame rate chip's glass and edge, without its words: drawn once for a size, into a sprite of fps_box's. Its
 * glass is faint (FPS_ALPHA), its words drawn over it whole. */
void look_fps_base(Sprite *s, float u);
/* The chip's pieces of words made ready for a size (its digits, the point, FPS and ms), so that no update draws a
 * piece for the first time. */
void look_fps_glyphs(float u, TextFn text, void *ctx);
/* The frame rate chip: its base (look_fps_base, the same size) copied in (its mask too when `mask_too`: it never
 * changes after), then the frames a second large, FPS beside it and the frame's mean length under it, from the pieces
 * (TEXT_GLYPHS). */
void look_fps(Sprite *s, const Sprite *base, float u, double fps, int mask_too, TextFn text, void *ctx);

/* Korean words on a button or a row, where English is in capitals, as a share of the English size (Pretendard Bold's
 * Hangul has strokes a fifth thinner than its capitals and half their width a label: set alike it looks smaller). */
extern const float look_ko_label;

/* The dart cursor (paint_cursor with the chosen look). */
void look_cursor(Canvas *c, int pressed, int *hot_x, int *hot_y);

/* The glass's tint: the game's frame behind a panel, blurred, then this colour laid over it at this opacity. Over a
 * white frame the glass is #3b3d40 at its lightest; over six of the game's screens (bright, dark, mode select, song
 * select, a song, the result) the design renderer measured each line of words against the glass and the picture
 * behind it, at its worst point: white lines 8.5:1 or more, the quieter grey 6.9:1, the labels on the buttons 5.4:1,
 * the wordmark's darkest chrome 4.7:1. */
#define GLASS_TINT 0x0a0d10u
/* The bars beside the game's picture when its shape is kept: the launcher's darkest neutral (theme.py SIDEBAR,
 * #0c0e11), opaque, as Direct3D writes a colour (ARGB). */
#define BAR_COLOR 0xff0c0e11u
#define GLASS_TINT_ALPHA 0.80f
/* The frame rate chip's tint: deeper, as its glass is faint as a whole (FPS_ALPHA) and reads a blurred frame made when
 * it first showed (no live blur under it alone): 8 % of that frame comes through the tint, too little to tell an old
 * screen from the one behind it. */
#define FPS_TINT_ALPHA 0.92f

/* The game's colours the layer uses, measured on its own screens. */
#define RGB_ACCENT 0x7cc4f2u      /* the light blue of its glossy buttons' upper half: the keys' ring, the handle under
                                   * the pointer */
#define RGB_ACCENT_SMALL 0xa8dbfau /* the same blue lighter, for the chip's small FPS on its faint glass: 4.5:1 over the
                                    * game's brightest screens, where the full blue came to 4.2:1 */
#define RGB_WORDS 0xf2f5f7u       /* words on glass */
#define RGB_QUIET 0xb9c2cau       /* a quieter line on glass */
#define RGB_DANGER 0xff9aa4u      /* the words of the row that quits: a light red that keeps 5.2:1 on the glass */

#endif
