/*
 * The layer over the game (ingame.h), in TECHNIKA 3's own panels' look (look.c), drawn by the post-process chain
 * (post.c) at the window's own pixels:
 *
 *   - a bar across the game's top band: openDMT3's mark at its left (the launcher's picture of it); at its right the
 *     menu's chip, then minimise, full screen (or back to a window) and the X, in the launcher's button shapes. It
 *     comes when the pointer, moved to the very top edge or onto the mark below with no button down, rests there and
 *     the game has had no press or release for 1.5 s (a click or a held note at the top of a song is play), or when a
 *     finger is drawn down from the top edge after such a quiet; by itself for 3 s when the game's first screen shows
 *     and after each switch between a window and full screen. No key brings it. It goes soon after the pointer
 *     leaves it. It slides down out of the game's top edge, its foot first, and back up into it (logic.h's slides:
 *     220 ms down, 170 ms up, turned back from where it is, at once with Windows' animation effects off);
 *   - the mark, the bar's handle: a rail along the top edge's middle with a small tab of the bar's glass hanging from it
 *     in the game's tab shape, a chevron in it pointing down; it goes down with the bar's foot, fading; clicks go
 *     through it to the game;
 *   - the menu (Back to the game, Show FPS, Quit the game) under its chip and the chips beside it, and the question
 *     (Keep playing, Quit the game) under the X: sheets that slide out from under the bar's foot and back; the window's
 *     own close request asks the same question; arrow keys and Enter choose, Esc closes them. No other key of the
 *     layer's: Esc never opens the question (the game never sees it either: its own Esc ends it at once), Alt+F4 does
 *     nothing;
 *   - a toast hanging from the top edge for a few seconds (the safety net's note), riding down with the bar's foot; one
 *     that comes during a song waits for the song's end;
 *   - the frame rate chip, faint, in the corner the launcher chose (riding down with the bar's foot in a top one),
 *     hidden while the game is held still;
 *   - the pointer over the game: openDMT3's dart, a Windows cursor sized for the display's scaling.
 *
 * In a window the game's frame keeps its title bar (to move it) and its borders (to size it), with no buttons: the
 * bar's chips minimise it, take it to full screen and back, and quit. Nothing of the layer is in the middle of the
 * game, where the notes come. The game's window is subclassed for its mouse, its keys and its close request; a click
 * on the layer never reaches the game (the keyboard hook keeps the button from it too). While the menu or the question
 * is open during a song, or the game is minimised in one, the device's present holds the game still (hooks.c), and
 * this file pumps the messages meanwhile, the game's own window procedure left out.
 */
#include "ingame.h"
#include "postmath.h"
#include "text.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* The game's window and its own window procedure. */
static HWND g_game;
static WNDPROC g_game_proc;
/* The menu or the question (open: CARD_NONE when neither), and the one last shown (drawn while it fades out). */
static Card g_card, g_shown;
/* Quitting: the game's own close goes through without asking, and nothing of the layer shows. */
static int g_quitting;
/* The game fills its screen (a borderless window over the monitor) or sits in a window; the window's place and size
 * as it was before full screen, to go back to (none yet when the game started in full screen). */
static int g_full;
static WINDOWPLACEMENT g_window_place;
static int g_have_place;
/* The game held still by the present (hooks.c): every message stays away from the game's own window procedure. */
static int g_holding;

/* ----------------------------------------------------------------------------------------------- the clock */

/* Milliseconds by the performance counter (the frame's own clock: motion at the frame rate). */
static double now_ms(void)
{
    static LARGE_INTEGER f;
    LARGE_INTEGER t;
    if (!f.QuadPart)
        QueryPerformanceFrequency(&f);
    QueryPerformanceCounter(&t);
    return (double)t.QuadPart * 1000.0 / (double)f.QuadPart;
}

/* ------------------------------------------------------------------------------------------- what shows */

/* Each part's motion: how far it is in (0 gone, 1 whole), moved towards whether it is wanted at each frame. For the bar,
 * the open panel and the notice `v` is their slide's place (logic.h Slide: down out of the top edge, or out from under
 * the bar's foot, and back); the chip and the handle fade. */
typedef struct {
    float v;
    int want;
} Motion;
static Motion g_bar, g_panel, g_toast, g_fps, g_mark;
/* The bar's, the open panel's and the notice's slides, aimed once a frame at whether each is wanted. */
static Slide g_bar_slide, g_panel_slide, g_toast_slide;
/* Where the bar and the panel stood on the screen at the last frame drawn, from their places (output pixels; negative:
 * higher, on their way): the mouse's handlers, between frames, judge a point against what the player sees. And where
 * they stood when the button went down: a click is judged where it was pressed (a chip pressed while the bar still
 * comes down acts too). */
static float g_bar_dy, g_panel_dy, g_press_bar_dy, g_press_panel_dy;
/* A notice that came while a song played, waiting for its end: nothing of the layer covers the game's top band (its
 * groove meter) during a song unless the player calls the bar. */
static int g_toast_waiting;
/* How long the bar stays (logic.h BarClock, as OpenDMTQ's bar): whole for 600 ms after the pointer was last on it,
 * 4 s after a finger brought it, 3 s by itself, while a panel is open; then fading over 300 ms. The pointer is looked
 * for ten times a second while it shows (it may leave over the window's title bar, where the game hears no move). */
static BarClock g_bar_clock;
static int g_bar_look;
/* When the bar came on the screen (0: it is not on it), for the log's line of how long it showed. */
static double g_bar_on_at;
/* When the game's first screen showed (0: not yet): the chip, the mark and the bar's first showing wait for it. */
static double g_first_at;
/* When a rest at the top edge or on the mark may bring the bar (logic.c RevealGate): the game's presses and the
 * pointer's rests. */
static RevealGate g_gate;
/* Where the pointer last moved to (client pixels): a move message to the same place is no move (Windows sends some
 * after a click), so a rest counts only when the pointer came to it by moving. */
static int g_moved_x = -1, g_moved_y = -1;
/* The pointer on the mark (it is lit then), and whether the press now held began after the game's quiet (a finger
 * drawn down from the top edge brings the bar only then). */
static int g_on_mark, g_swipe_ok;
/* The toast's words and when it goes; how long it stays. */
#define TOAST_MS 6000
static char g_toast_words[192];
static double g_toast_until;
/* Whether the chip shows this run (the launcher's choice at the start, then the menu's Show FPS), and its numbers (none
 * until the first count). */
static int g_fps_on, g_fps_have;
static double g_fps_value;

/* The target the layer is drawn on (the chain's output, or the game's own back buffer), as last drawn; the mouse's
 * client coordinates map onto it. */
static int g_tw, g_th;
/* The layout for that target, with the card as it is now. */
static UiLayout g_lay;
/* The layout the mouse's handlers judge a point against: g_lay without its panel once the panel is closed (one sliding
 * back up under the bar takes no press, as refresh_hover reads it from the card as it is). */
static UiLayout g_hit;

/* The pointer over the layer: what it is on and what was pressed (ui_hit's codes), where a press began, whether the
 * button is down over the game. */
static int g_hover = HIT_NONE, g_pressed = HIT_NONE;
static float g_press_y = -1;
static int g_mouse_down;

/* The parts' pictures and the version each was drawn at (post.c uploads a part again when its version changes). */
static Sprite g_s_bar, g_s_chips, g_s_panel, g_s_toast, g_s_fps, g_s_mark;
/* The largest canvases the panel and the toast take at the size drawn for (warm works them out): the question with
 * its line is taller than without and the menu another shape, a note as wide as its words. */
static int g_room_panel_w, g_room_panel_h, g_room_toast_w, g_room_toast_h;
/* The chip's glass and edge without its words, drawn once for a size: each update starts from a copy of it. Its mask's
 * version, and whether the chip's own mask is still to be copied from it (a new size). */
static Sprite g_s_fps_base;
static unsigned g_v_fps_mask;
static int g_fps_mask_due = 1;
/* The pictures' drawing costs by kind since the logger last read them (layer_redraws), and the GDI drawings during
 * the chip's updates. */
static long g_redraw_n[PART_KINDS], g_chip_gdi;
static long long g_redraw_ticks[PART_KINDS], g_redraw_max[PART_KINDS];
static LARGE_INTEGER g_redraw_t0;
/* Before and after a picture is drawn again: its time counted to its kind. */
static void redraw_start(void)
{
    QueryPerformanceCounter(&g_redraw_t0);
}
static void redraw_end(int kind)
{
    LARGE_INTEGER t1;
    QueryPerformanceCounter(&t1);
    long long d = t1.QuadPart - g_redraw_t0.QuadPart;
    g_redraw_n[kind]++;
    g_redraw_ticks[kind] += d;
    if (d > g_redraw_max[kind])
        g_redraw_max[kind] = d;
}
static unsigned g_v_bar, g_v_chips, g_v_panel, g_v_toast, g_v_fps, g_v_mark;
/* What each picture was drawn for: the target's size and the states it shows (drawn again when any differs). */
static int g_drawn_bar = -1, g_drawn_chips = -1, g_drawn_panel = -1, g_drawn_fps = -1, g_drawn_mark = -1;
static int g_drawn_toast;
static int g_drawn_w, g_drawn_h;

/* One step of a part's fade over `dt` ms: in over `in_ms`, out over `out_ms`; at once with no time to take (Windows'
 * animation effects off). */
static void step(Motion *m, float dt, float in_ms, float out_ms)
{
    if (in_ms <= 0.0f || out_ms <= 0.0f)
        m->v = m->want ? 1.0f : 0.0f;
    else if (m->want)
        m->v = m->v + dt / in_ms > 1.0f ? 1.0f : m->v + dt / in_ms;
    else
        m->v = m->v - dt / out_ms < 0.0f ? 0.0f : m->v - dt / out_ms;
}

/* SystemParametersInfo's "Animation effects" setting (Settings, Accessibility, Visual effects), where an older
 * Windows header has no name for it. */
#ifndef SPI_GETCLIENTAREAANIMATION
#define SPI_GETCLIENTAREAANIMATION 0x1042
#endif

/* Whether Windows shows animations (its Animation effects setting): with them off, nothing of the layer slides or fades,
 * each part comes and goes at once. Asked of Windows at most twice a second (a read of the user's settings, which never
 * waits); where Windows cannot say, as if they were on. */
static int animations(void)
{
    static double asked;
    static int on = 1, said = -1;
    double now = now_ms();
    if (!asked || now - asked >= 500.0) {
        asked = now;
        BOOL shown = TRUE;
        on = !SystemParametersInfoA(SPI_GETCLIENTAREAANIMATION, 0, &shown, 0) || shown;
        /* Said in the log when it is first read and whenever it changes. */
        if (on != said) {
            said = on;
            ingame_log("layer: Windows' animation effects %s",
                       on ? "on: the parts slide" : "off: the parts come and go at once");
        }
    }
    return on;
}

/* The mouse's client coordinates on the target's (the same unless the chain draws the window at another size). */
static void to_target(int cx, int cy, float *x, float *y)
{
    /* The picture's place in the client (the chain's: its own shape kept, bars beside it, or filling it); with no chain
     * the whole client, which Direct3D's own stretch fills. The layer lies in the picture, at its size. */
    int px, py, pw, ph;
    post_picture(&px, &py, &pw, &ph);
    RECT r;
    if ((pw <= 0 || ph <= 0) && GetClientRect(g_game, &r)) {
        px = py = 0;
        pw = r.right;
        ph = r.bottom;
    }
    if (g_tw > 0 && g_th > 0 && pw > 0 && ph > 0) {
        *x = (float)(cx - px) * (float)g_tw / (float)pw;
        *y = (float)(cy - py) * (float)g_th / (float)ph;
    } else {
        *x = (float)cx;
        *y = (float)cy;
    }
}

/* Whether the bar is showing (or coming), so the pointer can be on it. */
static int bar_shown(void)
{
    return g_bar.want || g_bar.v > 0.0f;
}

/* Ask for the bar (a rest at the top edge or on the mark, a panel opening), saying why: whole for 600 ms from now. */
static void ask_bar(const char *why)
{
    if (g_quitting)
        return;
    if (!bar_shown())
        ingame_log("layer: bar shown (%s)", why);
    bar_clock_rest(&g_bar_clock, now_ms());
}

/* A finger drawn down from the top edge: the bar whole for 4 s. */
static void ask_bar_by_finger(void)
{
    if (g_quitting)
        return;
    if (!bar_shown())
        ingame_log("layer: bar shown (a finger drawn down from the top edge)");
    bar_clock_touch(&g_bar_clock, now_ms());
}

/* The bar by itself for 3 s, so that a player sees where it is (the game's first screen, a switch). */
static void reveal_bar(const char *why)
{
    if (g_quitting)
        return;
    bar_clock_reveal(&g_bar_clock, now_ms());
    ingame_log("layer: bar shown by itself for %.0f s (%s)", BAR_REVEAL_MS / 1000.0, why);
}

/* Whether the pointer is at the very top edge of the game's picture, or on the mark while it shows, now, on the game's
 * own window (not on its title bar above, or on another window over it). */
static int pointer_at_place(void)
{
    POINT p, c;
    RECT r;
    if (!g_game || !GetCursorPos(&p) || WindowFromPoint(p) != g_game)
        return 0;
    c = p;
    if (!ScreenToClient(g_game, &c) || !GetClientRect(g_game, &r) || c.x < 0 || c.y < 0 || c.x >= r.right ||
        c.y >= r.bottom)
        return 0;
    float x, y;
    to_target(c.x, c.y, &x, &y);
    return ui_at_top_edge(y, g_th) || (g_mark.v > 0.0f && ui_on_mark(x, y, g_tw, g_th));
}

/* Whether the pointer is on the bar's band now, on the game's own window (not on its title bar or another window over
 * it); never while a finger brought the bar (the pointer it parks is no mouse on it), nor for a bar that came by
 * itself while the pointer has not moved since (it was parked there: logic.c bar_clock_pointer_counts). */
static int pointer_on_bar(void)
{
    POINT p, c;
    RECT r;
    if (!bar_clock_pointer_counts(&g_bar_clock) || !g_game || !GetCursorPos(&p) || WindowFromPoint(p) != g_game)
        return 0;
    c = p;
    if (!ScreenToClient(g_game, &c) || !GetClientRect(g_game, &r) || c.x < 0 || c.y < 0 || c.x >= r.right ||
        c.y >= r.bottom)
        return 0;
    float x, y;
    to_target(c.x, c.y, &x, &y);
    return y < g_lay.bar.h;
}

/* What the pointer is on now, read from Windows (it may not have moved since the layer changed under it: a bar that came
 * from a rest, a panel that closed): the bar or a chip, an answer or the panel of a card still open, or nothing of the
 * layer's. Kept as g_hover, so the bar goes in its time once the pointer leaves it. */
static void refresh_hover(void)
{
    POINT p;
    RECT r;
    g_hover = HIT_NONE;
    if (!g_game || g_tw <= 0 || g_th <= 0 || !GetCursorPos(&p) || !ScreenToClient(g_game, &p) ||
        !GetClientRect(g_game, &r) || p.x < 0 || p.y < 0 || p.x >= r.right || p.y >= r.bottom)
        return;
    float x, y;
    UiLayout now;
    to_target(p.x, p.y, &x, &y);
    ui_layout(&g_card, g_tw, g_th, &now);
    /* Against where the bar and the panel stand on the screen now (they may still be on their way). */
    g_hover = ui_hit_moved(&now, x, y, g_bar_dy, g_panel_dy);
}

/* ------------------------------------------------------------------------------------------------ the words */

/* The product's faces, loaded from beside this DLL the first time the layer draws words. */
static void fonts(void)
{
    static int done;
    if (done)
        return;
    done = 1;
    int found = text_load_fonts(g_module);
    ingame_log("layer: %d of 3 fonts loaded%s", found, found < 3 ? " (Windows' own face for the rest)" : "");
}

/* The launcher's picture of the mark, from this DLL's resource (mark.py made it when the DLL was built): its width and
 * height, then its premultiplied pixels. Read once; NULL when it is not there. */
static const Canvas *mark_picture(void)
{
    static Canvas *mark;
    static int tried;
    if (tried)
        return mark;
    tried = 1;
    HRSRC r = FindResourceA(g_module, MAKEINTRESOURCEA(104), MAKEINTRESOURCEA(10) /* RT_RCDATA */);
    HGLOBAL h = r ? LoadResource(g_module, r) : NULL;
    const uint8_t *bytes = h ? (const uint8_t *)LockResource(h) : NULL;
    DWORD size = r ? SizeofResource(g_module, r) : 0;
    uint32_t w = 0, hh = 0;
    if (bytes && size >= 8) {
        memcpy(&w, bytes, 4);
        memcpy(&hh, bytes + 4, 4);
    }
    /* Its size must match its pixels; anything else is not used. */
    if (w > 0 && hh > 0 && w < 4096 && hh < 4096 && size == 8 + (DWORD)w * hh * 4 && (mark = canvas_new((int)w, (int)hh)))
        memcpy(mark->px, bytes + 8, (size_t)w * hh * 4);
    ingame_log("layer: the mark's picture %s (%ux%u)", mark ? "read" : "missing", (unsigned)w, (unsigned)hh);
    return mark;
}

/* ---------------------------------------------------------------------------------------------- the parts */

/* Draw a part's pictures again for a box of w x h with `room` round it (the canvases made again for a new size). */
static int sprite_for(Sprite *s, float w, float h, float room)
{
    int cw = (int)ceilf(w + 2 * room), ch = (int)ceilf(h + 2 * room);
    if (s->content && s->content->w == cw && s->content->h == ch)
        return 1;
    sprite_free(s);
    sprite_make(s, w, h, room);
    return s->content && s->mask;
}

/* A canvas's size taken into the largest seen (a part's room). */
static void room(const Canvas *c, int *w, int *h)
{
    if (c && c->w > *w)
        *w = c->w;
    if (c && c->h > *h)
        *h = c->h;
}

/* Every picture drawn once for a new size, before any is needed: each face and size of the words is made then (a
 * face's first use reads its file), so opening a panel later costs only its own drawing. */
static void warm(int w, int h)
{
    LARGE_INTEGER t0, t1, f;
    QueryPerformanceCounter(&t0);
    Card c = {0, 0, g_settings.korean, g_fps_on};
    UiLayout l;
    g_room_panel_w = g_room_panel_h = g_room_toast_w = g_room_toast_h = 0;
    /* The question as a song has it (with its line: every word it ever shows, and its tallest), then the menu; the
     * room for the panel is the larger of each side. */
    c.song = 1;
    card_open(&c, CARD_QUIT);
    ui_layout(&c, w, h, &l);
    if (sprite_for(&g_s_panel, l.panel.w, l.panel.h, 8 * l.u)) {
        look_panel(&g_s_panel, &c, &l, -1, -1, text_gdi, NULL);
        room(g_s_panel.content, &g_room_panel_w, &g_room_panel_h);
    }
    c.song = 0;
    card_open(&c, CARD_MENU);
    ui_layout(&c, w, h, &l);
    if (sprite_for(&g_s_panel, l.panel.w, l.panel.h, 8 * l.u)) {
        look_panel(&g_s_panel, &c, &l, -1, -1, text_gdi, NULL);
        room(g_s_panel.content, &g_room_panel_w, &g_room_panel_h);
    }
    /* The safety net's three notes (the anti-aliasing to FXAA, to none, the upscale to bilinear): each drawn once, so
     * its words are made, the room for the toast the widest; the last stays as the toast's picture. */
    char words[160];
    static const int notes[3][2] = {{1, AA_FXAA}, {1, AA_OFF}, {0, AA_OFF}};
    for (int i = 0; i < 3; i++) {
        note_words(g_settings.korean, notes[i][0], notes[i][1], words, sizeof words);
        Box tb = toast_box(w, h, text_gdi(NULL, NULL, words, 14 * l.u, 0, 0, 0, TEXT_REGULAR));
        if (sprite_for(&g_s_toast, tb.w, tb.h, 8 * l.u)) {
            look_toast(&g_s_toast, l.u, words, text_gdi, NULL);
            room(g_s_toast.content, &g_room_toast_w, &g_room_toast_h);
        }
    }
    /* The chip: its base once for the size, its pieces of words made, then a first picture from them. */
    Box fb = fps_box(w, h, g_settings.fps_corner);
    if (sprite_for(&g_s_fps_base, fb.w, fb.h, 2 * l.u))
        look_fps_base(&g_s_fps_base, l.u);
    look_fps_glyphs(l.u, text_gdi, NULL);
    if (g_s_fps_base.content && sprite_for(&g_s_fps, fb.w, fb.h, 2 * l.u)) {
        look_fps(&g_s_fps, &g_s_fps_base, l.u, 60, 1, text_gdi, NULL);
        g_v_fps_mask++;
    }
    g_fps_mask_due = 0;
    /* The bar and its chips as they first show (drawn once for the size; the chips again on a hover). */
    if (sprite_for(&g_s_bar, l.bar.w, l.bar.h, ceilf(8 * l.u))) {
        look_bar(&g_s_bar, &l, mark_picture());
        g_drawn_bar = 1;
        g_v_bar++;
    }
    Box both = {l.chip[0].x, l.chip[0].y, l.chip[CHIP_X].x + l.chip[CHIP_X].w - l.chip[0].x, l.chip[0].h};
    if (sprite_for(&g_s_chips, both.w, both.h, ceilf(2 * l.u)))
        look_chips(&g_s_chips, &l, -1, -1, g_full);
    /* The mark, in its lit box (the taller), unlit as it first shows. */
    Box mb = ui_mark_box(w, h, 1);
    if (sprite_for(&g_s_mark, mb.w, mb.h, ceilf(2 * l.u)))
        look_mark(&g_s_mark, l.u, 0);
    /* All but the bar drawn again for real when they show. */
    g_drawn_panel = g_drawn_fps = g_drawn_chips = g_drawn_mark = -1;
    g_drawn_toast = 0;
    QueryPerformanceCounter(&t1);
    QueryPerformanceFrequency(&f);
    ingame_log("layer: pictures made ready for %dx%d in %.1f ms", w, h,
               (double)(t1.QuadPart - t0.QuadPart) * 1000.0 / (double)f.QuadPart);
}

int layer_parts(LayerPart *out, int max, int w, int h)
{
    static double last;
    double now = now_ms();
    /* The time since the last frame, for the motion (a long pause, as a load, moves it at most a tenth of a second). */
    double gap = last ? now - last : 0.0;
    float dt = (float)gap;
    last = now;
    /* A pause with no frame (a load as a song ends, a hitch, the game held): the presses made meanwhile reach the
     * game only after it, so it counts as neither rest nor quiet for the bar (logic.c gate_stall). */
    if (gap > GATE_STALL_MS)
        gate_stall(&g_gate, now, gap);
    if (dt > 100.0f)
        dt = 100.0f;
    if (!g_game || w <= 0 || h <= 0)
        return 0;
    fonts();
    g_tw = w;
    g_th = h;
    /* A new size: every picture drawn again. */
    if (w != g_drawn_w || h != g_drawn_h) {
        g_drawn_w = w;
        g_drawn_h = h;
        g_drawn_bar = g_drawn_chips = g_drawn_panel = g_drawn_fps = g_drawn_mark = -1;
        g_drawn_toast = 0;
        warm(w, h);
    }
    /* With no chain to look at the game's frames, its first screen is taken to be there from the first frame drawn. */
    if (!g_first_at && !post_running())
        layer_first_screen();
    /* A rest at the top edge or on the mark brings the bar once it has lasted and the game has been quiet, if the
     * pointer is still there (it may have gone up to the window's title bar, where the game hears no move); the log
     * says how long after the game's last press or release. */
    if (g_gate.armed && gate_due(&g_gate, now, pointer_at_place())) {
        char why[96];
        double quiet = (now - g_gate.pressed_at) / 1000.0;
        snprintf(why, sizeof why, "the pointer rested %s, %s", g_on_mark ? "on the mark" : "at the top edge",
                 quiet < 3600 ? "" : "no press yet");
        if (quiet < 3600)
            snprintf(why + strlen(why), sizeof why - strlen(why), "%.2f s after the game's last press", quiet);
        ask_bar(why);
        /* What the pointer is on now, with no move since the bar came (a chip it rests on lights up). */
        refresh_hover();
    }
    /* While the bar shows, the pointer looked for ten times a second: on it, it stays whole 600 ms more; off it (perhaps
     * gone over the window's title bar, where the game hears no move), no chip is under the pointer. */
    int open = g_card.open != CARD_NONE;
    if (bar_shown() && ++g_bar_look >= 6) {
        g_bar_look = 0;
        if (pointer_on_bar())
            bar_clock_rest(&g_bar_clock, now);
        else if (!open)
            g_hover = HIT_NONE;
    }
    int iconic = IsIconic(g_game);
    /* A notice that waited for a song's end shows once no song plays: its few seconds start now. */
    if (g_toast_waiting && !sound_song_playing()) {
        g_toast_waiting = 0;
        g_toast_until = now + TOAST_MS;
        ingame_log("layer: toast shown (it waited for the song's end)");
    }
    /* What is wanted now. The bar: whole in its time (logic.h BarClock), or a panel open. */
    g_bar.want = !g_quitting && (open || bar_clock_whole(&g_bar_clock, now));
    g_panel.want = !g_quitting && open;
    g_toast.want = !g_quitting && now < g_toast_until;
    /* The chip: on, counted, after the first screen (never a 0 before it), not while the game is held still (its
     * count would say a 60 of frames presented again) or minimised. */
    g_fps.want = !g_quitting && g_fps_on && g_fps_have && g_first_at && !g_holding && !iconic;
    /* The handle: after the first screen, while no panel is open and no notice hangs at the top centre where it is, and
     * the game is not held still or minimised; it fades as the bar comes down (below), never hidden for the bar alone,
     * so it goes down with the bar's foot and comes back up with it. */
    g_mark.want = !g_quitting && g_first_at && !open && !g_toast.want && g_toast.v <= 0.0f && !g_holding && !iconic;
    /* The motion, at the display's pace: each frame moves each part to where its way has it at this frame's time. The
     * bar, the panel and the notice slide (down in 220 ms slowing into place, up in 170 ms gathering speed, turned back
     * from where they are when wanted again); the chip and the handle fade in and out over 150 ms. With Windows'
     * animation effects off, all of it at once. */
    int animate = animations();
    float fade_ms = animate ? 150.0f : 0.0f;
    float bar_was = g_bar.v;
    slide_aim(&g_bar_slide, g_bar.want ? 1.0f : 0.0f, now, animate);
    g_bar.v = slide_at(&g_bar_slide, now);
    /* Its time on the screen, from its first frame to its last, in the log (the tests sum it). */
    if (bar_was <= 0.0f && g_bar.v > 0.0f) {
        g_bar_on_at = now;
        ingame_log("layer: bar on the screen");
    } else if (bar_was > 0.0f && g_bar.v <= 0.0f && g_bar_on_at) {
        ingame_log("layer: bar gone after %.2f s on the screen", (now - g_bar_on_at) / 1000.0);
        g_bar_on_at = 0;
    }
    slide_aim(&g_panel_slide, g_panel.want ? 1.0f : 0.0f, now, animate);
    g_panel.v = slide_at(&g_panel_slide, now);
    slide_aim(&g_toast_slide, g_toast.want ? 1.0f : 0.0f, now, animate);
    g_toast.v = slide_at(&g_toast_slide, now);
    step(&g_fps, dt, fade_ms, fade_ms);
    step(&g_mark, dt, fade_ms, fade_ms);
    /* The panel drawn is the open one, or the last one while it slides back up. */
    if (open)
        g_shown = g_card;
    ui_layout(&g_shown, w, h, &g_lay);
    g_hit = g_lay;
    if (!open) {
        g_hit.panel.w = 0;
        g_hit.count = 0;
    }
    float u = g_lay.u;
    /* Where everything stands now. The bar's top, out of sight above the top edge at place 0, and its foot below the
     * top edge, which everything at the top hangs from; the room its shadow takes under it travels with it. */
    float shade = SLIDE_SHADE * u;
    float bar_top = slide_top(g_bar.v, 0.0f, g_lay.bar.h, shade);
    float rows = slide_rows(g_bar.v, g_lay.bar.h, shade);
    /* The panel's top, sliding out from under the bar's foot (on the foot when it is whole), as an offset from its
     * place in the layout (the foot of the bar in place); both kept for the mouse's handlers. */
    float panel_top = g_lay.panel.w > 0 ? slide_top(g_panel.v, rows, g_lay.panel.h, shade) : g_lay.panel.y;
    g_bar_dy = bar_top;
    g_panel_dy = panel_top - g_lay.panel.y;
    /* While the bar or the panel is on its way, what the pointer is on is read again each frame: a still pointer is
     * under another chip or answer as they move. */
    if (slide_moving(&g_bar_slide, now) || slide_moving(&g_panel_slide, now))
        refresh_hover();
    int n = 0;
    /* The chip first (under everything else). In a top corner it hangs that much lower while the bar is down, as
     * OpenDMTQ's counter rides down with its bar's foot. */
    if (g_fps.v > 0.0f && n < max) {
        Box b = fps_box(w, h, g_settings.fps_corner);
        if (g_settings.fps_corner == CORNER_TOP_LEFT || g_settings.fps_corner == CORNER_TOP_RIGHT)
            b.y += rows;
        /* Drawn again only when what it shows changes: the whole frames a second and the tenths of the frame's length. */
        double shown = g_fps_value < 0 ? 0.0 : g_fps_value > 999 ? 999.0 : g_fps_value;
        int key = (int)(shown + 0.5) * 100000 + (shown > 0 ? (int)(10000.0 / shown + 0.5) % 100000 : 0);
        const Canvas *had = g_s_fps.content;
        if (key != g_drawn_fps && g_s_fps_base.content && sprite_for(&g_s_fps, b.w, b.h, 2 * u)) {
            /* A sprite made again (blank) needs its mask from the base again. */
            if (g_s_fps.content != had)
                g_fps_mask_due = 1;
            long before = text_renders();
            redraw_start();
            look_fps(&g_s_fps, &g_s_fps_base, u, g_fps_value, g_fps_mask_due, text_gdi, NULL);
            redraw_end(PART_FPS);
            if (g_fps_mask_due) {
                g_v_fps_mask++;
                g_fps_mask_due = 0;
            }
            /* GDI work in an update would be a piece made late: counted for the log (none expected). */
            g_chip_gdi += text_renders() - before;
            g_drawn_fps = key;
            g_v_fps++;
        }
        /* Its faintness is in its picture (FPS_ALPHA, its words whole over it): drawn at its fade alone. */
        if (g_s_fps.content)
            out[n++] = (LayerPart){&g_s_fps, g_v_fps, (int)lroundf(b.x - g_s_fps.room), (int)lroundf(b.y - g_s_fps.room),
                                   g_fps.v, PART_FPS, g_v_fps_mask};
    }
    /* The handle at the top centre, lit while the pointer is on it (drawn again only when that changes): hanging from
     * the bar's foot and fading as the bar comes down, gone when the bar is whole, back as it goes up. */
    float mark_alpha = g_mark.v * (1.0f - g_bar.v);
    if (mark_alpha > 0.0f && n < max) {
        Box mb = ui_mark_box(w, h, 1);
        int lit = g_on_mark ? 1 : 0;
        if (lit != g_drawn_mark && sprite_for(&g_s_mark, mb.w, mb.h, ceilf(2 * u))) {
            redraw_start();
            look_mark(&g_s_mark, u, lit);
            redraw_end(PART_MARK);
            g_drawn_mark = lit;
            g_v_mark++;
        }
        if (g_s_mark.content)
            out[n++] = (LayerPart){&g_s_mark, g_v_mark, (int)lroundf(mb.x - g_s_mark.room),
                                   (int)lroundf(mb.y + rows - g_s_mark.room), mark_alpha, PART_MARK};
    }
    /* The notice: hanging from the top edge in the middle (from the bar's foot while the bar is down), sliding down out
     * of it and back up into it. Under the bar, so the bar coming down over it carries it down. */
    if (g_toast.v > 0.0f && n < max) {
        float tw = text_gdi(NULL, NULL, g_toast_words, 14 * u, 0, 0, 0, TEXT_REGULAR);
        Box b = toast_box(w, h, tw);
        if (!g_drawn_toast && sprite_for(&g_s_toast, b.w, b.h, 8 * u)) {
            redraw_start();
            look_toast(&g_s_toast, u, g_toast_words, text_gdi, NULL);
            redraw_end(PART_TOAST);
            g_drawn_toast = 1;
            g_v_toast++;
        }
        float top = slide_top(g_toast.v, rows, b.h, shade);
        if (g_s_toast.content)
            out[n++] = (LayerPart){&g_s_toast, g_v_toast, (int)lroundf(b.x - g_s_toast.room),
                                   (int)lroundf(top - g_s_toast.room), 1.0f, PART_TOAST};
    }
    /* The menu or the question: a sheet sliding out from under the bar's foot as it opens and back up under it as it
     * closes. Drawn before the bar, which lies over what of it is still under the bar. */
    if (g_panel.v > 0.0f && g_lay.panel.w > 0 && n < max) {
        int hover = g_hover >= 0 ? g_hover : -1, held = g_pressed >= 0 && g_pressed == g_hover ? g_pressed : -1;
        int key = ((((g_shown.open * 8 + g_shown.focus) * 2 + g_shown.fps) * 2 + g_shown.korean) * 8 + hover + 1) * 8 +
                  held + 1;
        if (key != g_drawn_panel && sprite_for(&g_s_panel, g_lay.panel.w, g_lay.panel.h, 8 * u)) {
            redraw_start();
            look_panel(&g_s_panel, &g_shown, &g_lay, hover, held, text_gdi, NULL);
            redraw_end(PART_PANEL);
            g_drawn_panel = key;
            g_v_panel++;
        }
        if (g_s_panel.content)
            out[n++] = (LayerPart){&g_s_panel, g_v_panel, (int)lroundf(g_lay.panel.x - g_s_panel.room),
                                   (int)lroundf(panel_top - g_s_panel.room), 1.0f, PART_PANEL};
    }
    /* The bar: sliding down out of the game's top edge, its foot first, and back up into it; drawn once for a size. Its
     * chips, drawn again when the pointer goes on or off one, move with it. */
    if (g_bar.v > 0.0f && n + 1 < max) {
        if (g_drawn_bar != 1 && sprite_for(&g_s_bar, g_lay.bar.w, g_lay.bar.h, ceilf(8 * u))) {
            redraw_start();
            look_bar(&g_s_bar, &g_lay, mark_picture());
            redraw_end(PART_BAR);
            g_drawn_bar = 1;
            g_v_bar++;
        }
        /* The chip under the pointer, the one held there (pressed and still on it), and full screen's way. */
        int hover = ui_hit_chip(g_hover);
        int held = g_pressed == g_hover ? ui_hit_chip(g_pressed) : -1;
        int key = ((hover + 1) * 8 + held + 1) * 2 + g_full;
        Box both = {g_lay.chip[0].x, g_lay.chip[0].y, g_lay.chip[CHIP_X].x + g_lay.chip[CHIP_X].w - g_lay.chip[0].x,
                    g_lay.chip[0].h};
        if (key != g_drawn_chips && sprite_for(&g_s_chips, both.w, both.h, ceilf(2 * u))) {
            redraw_start();
            look_chips(&g_s_chips, &g_lay, hover, held, g_full);
            redraw_end(PART_BAR_CHIPS);
            g_drawn_chips = key;
            g_v_chips++;
        }
        if (g_s_bar.content)
            out[n++] = (LayerPart){&g_s_bar, g_v_bar, (int)lroundf(-g_s_bar.room), (int)lroundf(bar_top - g_s_bar.room),
                                   1.0f, PART_BAR};
        if (g_s_chips.content)
            out[n++] = (LayerPart){&g_s_chips, g_v_chips, (int)lroundf(both.x - g_s_chips.room),
                                   (int)lroundf(both.y + bar_top - g_s_chips.room), 1.0f, PART_BAR_CHIPS};
    }
    return n;
}

int layer_warm_parts(LayerPart *out, int max, int w, int h)
{
    /* The pictures made ready for this size (warm), each at its place and a ten thousandth of its opacity. */
    if (layer_parts(out, 0, w, h) < 0 || !g_game)
        return 0;
    Sprite *all[6] = {&g_s_bar, &g_s_chips, &g_s_panel, &g_s_toast, &g_s_fps, &g_s_mark};
    unsigned versions[6] = {g_v_bar, g_v_chips, g_v_panel, g_v_toast, g_v_fps, g_v_mark};
    int kinds[6] = {PART_BAR, PART_BAR_CHIPS, PART_PANEL, PART_TOAST, PART_FPS, PART_MARK};
    /* The chip's mask has its own version (its glass is drawn once for a size); the others' go with their pictures. */
    unsigned masks[6] = {0, 0, 0, 0, g_v_fps_mask, 0};
    /* The room each may take: the panel's and the toast's as warm worked them out, the others' their own size. */
    int room_w[6] = {0, 0, g_room_panel_w, g_room_toast_w, 0, 0};
    int room_h[6] = {0, 0, g_room_panel_h, g_room_toast_h, 0, 0};
    int n = 0;
    for (int i = 0; i < 6 && n < max; i++)
        if (all[i]->content)
            out[n++] = (LayerPart){all[i], versions[i], 0, 0, 0.0001f, kinds[i], masks[i], room_w[i], room_h[i]};
    return n;
}

/* -------------------------------------------------------------------------------------------------- the cursor */

static HCURSOR g_cursors[2];

/* The display's dots an inch (the fixed client is aware of the display's scaling in full screen). */
static int screen_dpi(void)
{
    HDC dc = GetDC(NULL);
    int dpi = dc ? GetDeviceCaps(dc, LOGPIXELSY) : 96;
    if (dc)
        ReleaseDC(NULL, dc);
    return dpi > 0 ? dpi : 96;
}

/* The dart as a Windows cursor of `size` pixels (straight alpha, as Windows takes it for a cursor). */
static HCURSOR make_cursor(int size, int pressed)
{
    Canvas *c = canvas_new(size, size);
    if (!c)
        return NULL;
    int hx = 0, hy = 0;
    look_cursor(c, pressed, &hx, &hy);
    BITMAPV5HEADER bi;
    memset(&bi, 0, sizeof bi);
    bi.bV5Size = sizeof bi;
    bi.bV5Width = size;
    bi.bV5Height = -size;
    bi.bV5Planes = 1;
    bi.bV5BitCount = 32;
    bi.bV5Compression = BI_BITFIELDS;
    bi.bV5RedMask = 0x00ff0000;
    bi.bV5GreenMask = 0x0000ff00;
    bi.bV5BlueMask = 0x000000ff;
    bi.bV5AlphaMask = 0xff000000;
    HDC screen = GetDC(NULL);
    void *bits = NULL;
    HBITMAP colour = CreateDIBSection(screen, (BITMAPINFO *)&bi, DIB_RGB_COLORS, &bits, NULL, 0);
    ReleaseDC(NULL, screen);
    HCURSOR cursor = NULL;
    if (colour) {
        uint32_t *px = bits;
        for (int i = 0; i < size * size; i++) {
            uint32_t p = c->px[i];
            uint32_t a = p >> 24;
            if (!a) {
                px[i] = 0;
                continue;
            }
            /* Premultiplied back to straight colour: each channel divided by the opacity. */
            uint32_t r = ((p >> 16) & 0xff) * 255 / a, g = ((p >> 8) & 0xff) * 255 / a, b = (p & 0xff) * 255 / a;
            px[i] = (a << 24) | ((r > 255 ? 255 : r) << 16) | ((g > 255 ? 255 : g) << 8) | (b > 255 ? 255 : b);
        }
        /* An empty mask: the colour bitmap's alpha decides what shows. */
        HBITMAP mask = CreateBitmap(size, size, 1, 1, NULL);
        ICONINFO info = {FALSE, (DWORD)hx, (DWORD)hy, mask, colour};
        cursor = CreateIconIndirect(&info);
        DeleteObject(mask);
        DeleteObject(colour);
    }
    canvas_free(c);
    return cursor;
}

/* Our pointer, pressed or not, made once at the display's scaling: 32 pixels at 96 dpi. */
static HCURSOR cursor(int pressed)
{
    if (!g_cursors[pressed]) {
        int size = (int)lroundf(32.0f * (float)screen_dpi() / 96.0f);
        if (size < 32)
            size = 32;
        g_cursors[pressed] = make_cursor(size, pressed);
        ingame_log("cursor: made %s, %d px", pressed ? "pressed" : "normal", size);
        /* Windows refused it: its own arrow, a pointer all the same. */
        if (!g_cursors[pressed])
            g_cursors[pressed] = LoadCursor(NULL, IDC_ARROW);
    }
    return g_cursors[pressed];
}

/* Our pointer as it should look now, when the launcher left the pointer to us (pressed only over the game). */
static void set_pointer(void)
{
    if (g_settings.cursor)
        SetCursor(cursor(g_mouse_down && g_pressed == HIT_NONE));
}

/* ------------------------------------------------------------------------------------------- menu and question */

/* The menu or the question open, the first answer chosen; the bar comes with it (the panel hangs from it). */
static void open_card(int what)
{
    if (g_quitting)
        return;
    card_open(&g_card, what);
    g_card.korean = g_settings.korean;
    /* The menu's Show FPS row says the chip's state as it is now. */
    g_card.fps = g_fps_on;
    /* The question says what quitting loses only while a song plays. */
    g_card.song = sound_song_playing();
    ask_bar(what == CARD_MENU ? "the menu" : "the question");
    /* Over a minimised game nothing could be seen: the game comes back first. */
    if (IsIconic(g_game))
        ShowWindow(g_game, SW_RESTORE);
    ingame_log("layer: %s opened%s", what == CARD_MENU ? "menu" : "question",
               what == CARD_QUIT && g_card.song ? " (a song plays: with its line)" : "");
}

/* Back to the game: the panel goes; the answer's keys stay away from the game until they are let go; the bar goes a
 * little later unless the pointer is on it. */
static void close_card(void)
{
    g_card.open = CARD_NONE;
    g_keys_waiting = 1;
    /* The bar stays its 600 ms after the panel goes (longer while the pointer is on it). */
    bar_clock_rest(&g_bar_clock, now_ms());
    /* What the pointer is on now that the panel is gone (it rested on an answer, maybe with no move since): the bar
     * itself, or nothing of the layer's, so the bar goes in its time unless the pointer is on it. */
    refresh_hover();
    ingame_log("layer: closed, back to the game");
}

/* Ending the game the way its own close does, so the launcher sees it end; if the game does not end in ten seconds
 * (its own shutdown stuck), the process ends itself with exit code 0. */
static DWORD WINAPI quit_watch(LPVOID unused)
{
    (void)unused;
    Sleep(10000);
    ingame_log("quit: the game had not ended after 10 s: ended now");
    TerminateProcess(GetCurrentProcess(), 0);
    return 0;
}

static void quit_game(void)
{
    g_quitting = 1;
    g_card.open = CARD_NONE;
    ingame_log("quit: the player chose Quit the game");
    HANDLE watch = CreateThread(NULL, 0, quit_watch, NULL, 0, NULL);
    if (watch)
        CloseHandle(watch);
    /* The game's own close: its window goes, and its message loop ends the program. Posted, so a hold of the game
     * ends first (layer_pump) and the game's own loop takes it. */
    PostMessageA(g_game, WM_CLOSE, 0, 0);
}

/* The chip on or off for this run (the menu's Show FPS). */
static void set_fps(int on)
{
    g_fps_on = on;
    g_card.fps = on;
    ingame_log("layer: frame rate chip %s", on ? "on" : "off");
}

/* Do what a key or a choice asked for. */
static void act(int what)
{
    if (what == ACT_FPS)
        /* The menu stays, its row now saying the other state. */
        set_fps(g_card.fps);
    else if (what == ACT_CLOSE)
        close_card();
    else if (what == ACT_QUIT)
        quit_game();
}

/* A key pressed while the card is up; 1 when it was the card's. */
static int card_keys(WPARAM w)
{
    if (g_card.open == CARD_NONE)
        return 0;
    act(card_key(&g_card, (unsigned)w));
    return 1;
}

/* ------------------------------------------------------------------------------------------- the game's window */

/* The window's styles: in a window, its title bar (to move it) and its borders (to size it) and nothing else; Windows'
 * buttons on the title bar (and its menu there) are the bar's chips' work. */
#define STYLE_WINDOW (WS_OVERLAPPED | WS_CAPTION | WS_THICKFRAME)
#define STYLE_BUTTONS (WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)

/* The game's window in a window: its title bar's buttons taken away and its borders made ones that size it, its
 * picture's size kept. */
static void window_without_buttons(LONG style)
{
    RECT client;
    if (!GetClientRect(g_game, &client))
        return;
    LONG ex = GetWindowLongA(g_game, GWL_EXSTYLE);
    LONG now = (style & ~STYLE_BUTTONS) | STYLE_WINDOW;
    SetWindowLongA(g_game, GWL_STYLE, now);
    /* The frame round the same picture: its new borders added outside it. */
    RECT r = {0, 0, client.right, client.bottom};
    AdjustWindowRectEx(&r, (DWORD)now, FALSE, (DWORD)ex);
    SetWindowPos(g_game, NULL, 0, 0, r.right - r.left, r.bottom - r.top,
                 SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED);
    ingame_log("layer: the window keeps its title bar and borders, no buttons (style 0x%08lx, was 0x%08lx)",
               (unsigned long)now, (unsigned long)style);
}

/* Full screen (a borderless window over its monitor) and back to a window: the window's place and size as they were,
 * or, for a game that started in full screen, a window of the game's shape three quarters as tall as the monitor's
 * work area, in its middle. The bar shows by itself after, so the player sees where it went. */
static void toggle_full(void)
{
    LONG style = GetWindowLongA(g_game, GWL_STYLE), ex = GetWindowLongA(g_game, GWL_EXSTYLE);
    MONITORINFO mi;
    mi.cbSize = sizeof mi;
    if (!GetMonitorInfoA(MonitorFromWindow(g_game, MONITOR_DEFAULTTONEAREST), &mi))
        return;
    if (!g_full) {
        /* Its place as a window first, to come back to. */
        g_window_place.length = sizeof g_window_place;
        g_have_place = GetWindowPlacement(g_game, &g_window_place);
        SetWindowLongA(g_game, GWL_STYLE, (style & ~(STYLE_WINDOW | STYLE_BUTTONS)) | WS_POPUP);
        SetWindowPos(g_game, HWND_TOP, mi.rcMonitor.left, mi.rcMonitor.top, mi.rcMonitor.right - mi.rcMonitor.left,
                     mi.rcMonitor.bottom - mi.rcMonitor.top, SWP_NOOWNERZORDER | SWP_FRAMECHANGED);
        g_full = 1;
    } else {
        LONG now = (style & ~(WS_POPUP | STYLE_BUTTONS)) | STYLE_WINDOW;
        SetWindowLongA(g_game, GWL_STYLE, now);
        if (g_have_place) {
            SetWindowPlacement(g_game, &g_window_place);
            SetWindowPos(g_game, NULL, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOOWNERZORDER | SWP_FRAMECHANGED);
        } else {
            /* The game's 5:3 picture, three quarters of the work area's height (narrower if the area is), centred. */
            int ww = mi.rcWork.right - mi.rcWork.left, wh = mi.rcWork.bottom - mi.rcWork.top;
            int ch = wh * 3 / 4, cw = ch * 5 / 3;
            if (cw > ww * 9 / 10) {
                cw = ww * 9 / 10;
                ch = cw * 3 / 5;
            }
            RECT r = {0, 0, cw, ch};
            AdjustWindowRectEx(&r, (DWORD)now, FALSE, (DWORD)ex);
            int ow = r.right - r.left, oh = r.bottom - r.top;
            SetWindowPos(g_game, NULL, mi.rcWork.left + (ww - ow) / 2, mi.rcWork.top + (wh - oh) / 2, ow, oh,
                         SWP_NOZORDER | SWP_NOOWNERZORDER | SWP_FRAMECHANGED);
        }
        g_full = 0;
    }
    RECT c = {0, 0, 0, 0};
    GetClientRect(g_game, &c);
    ingame_log("layer: %s (%ld x %ld, style 0x%08lx)", g_full ? "full screen" : "in a window", c.right, c.bottom,
               (unsigned long)GetWindowLongA(g_game, GWL_STYLE));
    reveal_bar("a switch between a window and full screen");
}

/* Down to the taskbar (the bar's minimise); a song is held still meanwhile (layer_hold_wanted). */
static void minimise(void)
{
    ingame_log("layer: minimised");
    ShowWindow(g_game, SW_MINIMIZE);
}

/* ----------------------------------------------------------------------------------------- the frame rate chip */

void layer_fps(double fps)
{
    /* The number only: the chip's picture is drawn again with it at the next frame (layer_parts). */
    g_fps_value = fps;
    g_fps_have = 1;
}

void layer_redraws(long count[PART_KINDS], long long ticks[PART_KINDS], long long longest[PART_KINDS], long *chip_gdi)
{
    /* Handed over and started again for the next window. */
    for (int i = 0; i < PART_KINDS; i++) {
        count[i] = g_redraw_n[i];
        ticks[i] = g_redraw_ticks[i];
        longest[i] = g_redraw_max[i];
        g_redraw_n[i] = 0;
        g_redraw_ticks[i] = g_redraw_max[i] = 0;
    }
    *chip_gdi = g_chip_gdi;
    g_chip_gdi = 0;
}

/* The launcher's line for a step: the note beside this DLL in openDMT3's folder, read and removed when the game ends. */
static void note_for_launcher(int upscale, int aa)
{
    WCHAR path[MAX_PATH * 4];
    if (!ingame_beside(L"openDMT3-picture.txt", path, MAX_PATH * 4))
        return;
    FILE *f = _wfopen(path, L"a");
    if (!f)
        return;
    fprintf(f, "stepped down to upscale %s, anti-aliasing %s at frame %ld\n", UPSCALE_NAMES[upscale], AA_NAMES[aa],
            ingame_frame());
    fclose(f);
}

void layer_toast(const char *words)
{
    if (!g_game || g_quitting)
        return;
    /* The same words again while it shows: only its time is lengthened (its picture is as it was). */
    int same = g_drawn_toast && !strcmp(g_toast_words, words);
    snprintf(g_toast_words, sizeof g_toast_words, "%s", words);
    if (sound_song_playing()) {
        /* During a song it would hang over the game's groove meter for its seconds: it waits for the song's end
         * (layer_parts shows it then), and one on the screen goes up out of the way. */
        g_toast_waiting = 1;
        g_toast_until = 0;
        ingame_log("layer: toast waits for the song's end");
    } else {
        g_toast_waiting = 0;
        g_toast_until = now_ms() + TOAST_MS;
        ingame_log("layer: toast shown");
    }
    /* Drawn again with new words. */
    if (!same)
        g_drawn_toast = 0;
}

void layer_stepped_down(int upscale, int aa, int aa_changed)
{
    /* What to say (logic.c, no drawing), the log, the launcher's line, then the toast. */
    char words[160];
    note_words(g_settings.korean, aa_changed, aa, words, sizeof words);
    ingame_log("layer: note shown: %s", words);
    note_for_launcher(upscale, aa);
    layer_toast(words);
}

HWND layer_window(void)
{
    return g_game;
}

/* ------------------------------------------------------------------------------------------- the pointer */

/* The pointer moved to client pixel (cx, cy), (x, y) of the target, with a button held or not (`held`). */
static void pointer_moved(int cx, int cy, float x, float y, int held)
{
    /* A move message to where the pointer already was is no move. */
    int moved = cx != g_moved_x || cy != g_moved_y;
    g_moved_x = cx;
    g_moved_y = cy;
    /* On the mark (while it shows): it lights up. */
    g_on_mark = g_mark.v > 0.0f && ui_on_mark(x, y, g_tw, g_th);
    /* A rest at the very top edge or on the mark, armed by a move there with no button held: the bar comes from it
     * once it has lasted and the game has been quiet (layer_parts looks each frame). */
    if (moved)
        gate_move(&g_gate, now_ms(), !g_quitting && (ui_at_top_edge(y, g_th) || g_on_mark), held);
    /* A finger drawn down from the top edge, its press after the game's quiet: the bar. */
    /* A real move of the mouse, its button up: the pointer is the mouse's again (a finger's bar keeps no longer), and
     * one parked on the bar's band is a pointer on it again (logic.c bar_clock_moved). */
    if (moved && !held)
        bar_clock_moved(&g_bar_clock);
    if (g_mouse_down && g_press_y >= 0 && g_pressed == HIT_NONE && g_swipe_ok && ui_swipe_down(g_press_y, y, g_th)) {
        ask_bar_by_finger();
        /* The finger was asking for the bar, not playing: the game sees the button up until it is let go. */
        g_keys_waiting = 1;
        g_press_y = -1;
    }
    /* What the pointer is on, while something of the layer can be (the bar showing, or a panel open). */
    g_hover = bar_shown() || g_card.open != CARD_NONE ? ui_hit_moved(&g_hit, x, y, g_bar_dy, g_panel_dy) : HIT_NONE;
    /* On the bar: whole 600 ms more from now (not over a finger's own time). */
    if (g_hover != HIT_NONE && bar_shown())
        bar_clock_rest(&g_bar_clock, now_ms());
    /* A row under the pointer is where the keys' ring goes too, so the two never point at different answers. */
    if (g_hover >= 0 && g_hover < card_count(&g_card) && g_hover != g_card.focus)
        g_card.focus = g_hover;
}

/* A press of the button at (x, y) of the target: 1 when it was the layer's (kept from the game). */
static int pointer_pressed(float x, float y)
{
    /* Whether this press came after the game's quiet (judged before it counts): only such a press drawn down from the
     * top edge asks for the bar. */
    g_swipe_ok = gate_quiet(&g_gate, now_ms());
    g_press_y = y;
    /* Judged where the bar and the panel stand on the screen now, and kept for the release (logic.h ui_hit_moved). */
    g_press_bar_dy = g_bar_dy;
    g_press_panel_dy = g_panel_dy;
    int hit = bar_shown() || g_card.open != CARD_NONE ? ui_hit_moved(&g_hit, x, y, g_bar_dy, g_panel_dy) : HIT_NONE;
    if (hit != HIT_NONE) {
        /* On the layer: held there until the button comes up (a click counts where it began and ended). */
        g_pressed = hit;
        g_keys_waiting = 1;
        SetCapture(g_game);
        return 1;
    }
    if (g_card.open != CARD_NONE) {
        /* Beside an open panel: back to the game, the press kept from it. */
        act(card_key(&g_card, VK_ESCAPE));
        g_keys_waiting = 1;
        return 1;
    }
    /* A press on the game is play: no rest brings the bar for a while (logic.c RevealGate), and a bar that shows goes
     * (brought, or by itself), fading. */
    gate_press(&g_gate, now_ms(), 1);
    bar_clock_hide(&g_bar_clock);
    return 0;
}

/* The button up at (x, y): 1 when the press was the layer's. */
static int pointer_released(float x, float y)
{
    int was = g_pressed;
    g_pressed = HIT_NONE;
    if (was == HIT_NONE) {
        /* A release on the game is play too. */
        gate_press(&g_gate, now_ms(), 0);
        return 0;
    }
    ReleaseCapture();
    /* Counted only where it began (slide off to change your mind). */
    if (ui_hit_moved(&g_hit, x, y, g_press_bar_dy, g_press_panel_dy) != was)
        return 1;
    if (was == HIT_MENU)
        /* The menu's chip opens the menu, or closes it when it is open. */
        g_card.open == CARD_MENU ? close_card() : open_card(CARD_MENU);
    else if (was == HIT_X)
        g_card.open == CARD_QUIT ? close_card() : open_card(CARD_QUIT);
    else if (was == HIT_MIN)
        minimise();
    else if (was == HIT_FULL)
        toggle_full();
    else if (was >= 0)
        act(card_choose(&g_card, was));
    return 1;
}

/* Any of the mouse's buttons held, from a mouse message's flags. */
#define BUTTONS_HELD(w) (((w) & (MK_LBUTTON | MK_RBUTTON | MK_MBUTTON)) != 0)

/* The game's window, subclassed: its pointer, its mouse over the layer, its keys while a panel is up, Esc, Alt+F4 and
 * its close request; everything else goes on to the game as before (while the game is held, to Windows' default
 * instead). */
static LRESULT CALLBACK game_proc(HWND h, UINT msg, WPARAM w, LPARAM l)
{
    float x = 0, y = 0;
    if (msg >= WM_MOUSEFIRST && msg <= WM_MOUSELAST)
        to_target((short)LOWORD(l), (short)HIWORD(l), &x, &y);
    switch (msg) {
    case WM_SETCURSOR:
        /* Over the game's picture: our dart (the frame's edges keep Windows' own pointers). */
        if (LOWORD(l) == HTCLIENT && g_settings.cursor) {
            set_pointer();
            return TRUE;
        }
        break;
    case WM_LBUTTONDOWN:
        g_mouse_down = 1;
        /* Measuring input latency: the press's time (nothing when not measuring). */
        ingame_press();
        if (pointer_pressed(x, y)) {
            set_pointer();
            return 0;
        }
        set_pointer();
        break;
    case WM_LBUTTONUP:
        g_mouse_down = 0;
        g_press_y = -1;
        if (pointer_released(x, y)) {
            set_pointer();
            return 0;
        }
        set_pointer();
        break;
    case WM_RBUTTONDOWN:
    case WM_MBUTTONDOWN:
    case WM_RBUTTONUP:
    case WM_MBUTTONUP:
        /* The other buttons are the game's input too: no rest brings the bar for a while after them. */
        gate_press(&g_gate, now_ms(), BUTTONS_HELD(w));
        break;
    case WM_MOUSEMOVE:
        g_mouse_down = (w & MK_LBUTTON) != 0;
        pointer_moved((short)LOWORD(l), (short)HIWORD(l), x, y, BUTTONS_HELD(w));
        /* A drag that began on the layer stays the layer's. */
        if (g_pressed != HIT_NONE)
            return 0;
        break;
    case WM_CLOSE:
        /* The window's own close (the taskbar's) asks first, as the bar's X does; quitting goes through. */
        if (!g_quitting) {
            open_card(CARD_QUIT);
            return 0;
        }
        break;
    case WM_SYSCOMMAND:
        /* Windows' menu mode from the keyboard (Alt alone, F10): nothing, so the keys after it stay the game's. */
        if ((w & 0xFFF0) == SC_KEYMENU)
            return 0;
        /* The window's close from outside (the taskbar's, a window manager's) asks first; the game's own window
         * procedure never gets it, as it would end the game at once (measured under Wine: exit 0, no close request). */
        if ((w & 0xFFF0) == SC_CLOSE && !g_quitting) {
            open_card(CARD_QUIT);
            return 0;
        }
        break;
    case WM_KEYDOWN:
    case WM_SYSKEYDOWN:
        /* Alt+F4 does nothing: quitting is the bar's X's, which asks (Windows would make it the close request). */
        if (msg == WM_SYSKEYDOWN && w == VK_F4) {
            if (!(l & (1L << 30)))
                ingame_log("layer: Alt+F4 does nothing");
            return 0;
        }
        if (card_keys(w))
            return 0;
        /* Esc opens nothing of the layer's, and never reaches the game, whose own Esc would end it at once (said once
         * a press, not for the key's repeats while it is held). */
        if (w == VK_ESCAPE) {
            if (!(l & (1L << 30)))
                ingame_log("layer: Esc kept from the game");
            return 0;
        }
        break;
    case WM_KEYUP:
    case WM_SYSKEYUP:
    case WM_CHAR:
    case WM_SYSCHAR:
        /* Every key waits while the card is up; Esc (its release and its character) never reaches the game, and
         * neither does the character of an Enter that answered the card. */
        if (g_card.open != CARD_NONE || w == VK_ESCAPE || ((msg == WM_CHAR) && w == 0x1B))
            return 0;
        break;
    case WM_ACTIVATEAPP:
        /* Another program came forward: the bar brought by the pointer goes (an open panel stays with the game; a bar
         * showing by itself keeps its time), and no rest is waiting. */
        if (!w) {
            g_bar_clock.since = g_bar_clock.stay = 0;
            g_bar_clock.by_touch = 0;
            g_gate.armed = 0;
        }
        break;
    default:
        break;
    }
    /* Held still: nothing reaches the game's own code (a mouse or key message the layer did not take included). */
    if (g_holding)
        return DefWindowProcA(h, msg, w, l);
    return CallWindowProcA(g_game_proc, h, msg, w, l);
}

void layer_attach(HWND game)
{
    /* Once: a second device for the same window (a reset of the game's picture) finds the layer in place. */
    if (!game || g_game == game)
        return;
    g_game = game;
    /* The frame rate chip as the launcher chose it; the menu's Show FPS turns it for the run. */
    g_fps_on = g_settings.show_fps;
    /* No press yet: the game counts as quiet. */
    gate_start(&g_gate);
    bar_clock_start(&g_bar_clock);
    /* The game's own window procedure stays behind ours. */
    g_game_proc = (WNDPROC)SetWindowLongPtrA(game, GWLP_WNDPROC, (LONG_PTR)game_proc);
    /* Full screen is a borderless window over the monitor; a window has a title bar, whose buttons go. */
    LONG style = GetWindowLongA(game, GWL_STYLE);
    g_full = !(style & WS_CAPTION);
    if (!g_full)
        window_without_buttons(style);
    RECT a = {0, 0, 0, 0};
    GetClientRect(game, &a);
    ingame_log("layer: attached (%ld x %ld, dpi %d, %.2f output pixels a game pixel, %s)", a.right, a.bottom,
               screen_dpi(), ui_unit(a.bottom), g_full ? "full screen" : "in a window");
}

void layer_first_screen(void)
{
    /* Once: the chip, the mark and the bar's first showing wait for it. */
    if (g_first_at || !g_game)
        return;
    g_first_at = now_ms();
    ingame_log("layer: the game's first screen");
    reveal_bar("the game's first screen");
}

int layer_holds_input(void)
{
    return g_card.open != CARD_NONE;
}

int layer_hold_wanted(void)
{
    /* A panel open, or the game minimised, while a song's music plays, and the chain running (it keeps the frozen
     * frame to present again). */
    return !g_quitting && (g_card.open != CARD_NONE || (g_game && IsIconic(g_game))) && post_running() &&
           sound_song_playing();
}

void layer_holding(int on)
{
    g_holding = on;
}

int layer_quitting(void)
{
    return g_quitting;
}

int layer_is_holding(void)
{
    return g_holding;
}

int layer_pump(void)
{
    MSG m;
    while (PeekMessageA(&m, NULL, 0, 0, PM_REMOVE)) {
        if (m.message == WM_QUIT) {
            /* The program is to end: its quit message goes back for the game's own loop, and the hold ends. */
            PostQuitMessage((int)m.wParam);
            return 0;
        }
        /* The game's timers wait with the game (a timer's procedure would run the game's code). */
        if (m.message == WM_TIMER)
            continue;
        TranslateMessage(&m);
        DispatchMessageA(&m);
        /* Quitting: the hold ends before the game's close is taken, so the game's own loop takes it. */
        if (g_quitting)
            return 0;
    }
    return !g_quitting;
}
