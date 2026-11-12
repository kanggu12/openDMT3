/*
 * The in-game layer's decisions, in plain C with no Windows calls, so the native tests run every one of them:
 * the launcher's settings as the DLL reads them, the frame clock, which keys the game may see, the menu and
 * the question (their rows, the keys that move between them), and where everything goes on the game's screen.
 */
#ifndef OPENDMT3_LOGIC_H
#define OPENDMT3_LOGIC_H

#include <stdint.h>

/* ------------------------------------------------------------------------------------------------- settings */

/* The launcher's variables the DLL reads at the game's start (values.py layer_environment makes each; a test there
 * checks every one it makes is in this list). */
extern const char *const SETTINGS_NAMES[];
extern const int SETTINGS_COUNT;

/* What the launcher asked for, read from its environment variables at the game's start (layer_settings). */
typedef struct {
    int korean;            /* OPENDMT3_LANGUAGE=ko: the layer's words in Korean */
    int cursor;            /* OPENDMT3_CURSOR=off: the game's pointer left to the game (a touch screen hides it) */
    int even_pacing;       /* OPENDMT3_PACING=even or music: openDMT3's clock holds 60.0 a second, not the client's own steps */
    int music_lock;        /* OPENDMT3_PACING=music: while a song's music plays, its clock leads (frame k at k/60 s of it) */
    int show_fps;          /* OPENDMT3_FPS=on: the frame rate chip over the game */
    int fps_corner;        /* OPENDMT3_FPS_POSITION: the chip's corner (CORNER_*; the bottom right unless chosen) */
    int has_device;        /* a sound device was chosen (not Windows' default) */
    uint8_t device[16];    /* its GUID, in the byte order of Windows' GUID structure */
    int upscale;           /* OPENDMT3_UPSCALE: off, smooth, fsr1 or nis (postmath.h's UPSCALE_*) */
    int sharpness;         /* OPENDMT3_SHARPNESS: 0 to 100, for FSR 1's RCAS and NIS's sharpening */
    int antialiasing;      /* OPENDMT3_ANTIALIASING: postmath.h's AA_* */
    int fill;              /* OPENDMT3_PICTURE_SHAPE=fill: the picture stretched to the window; keep (the default): its
                            * own 5:3 shape, bars on the other two sides */
    int pass_times;        /* OPENDMT3_PASS_TIMES=on: the picture's GPU time by pass measured (Screen page, Measure the
                            * picture's GPU time; off by default) */
    int low_latency;       /* OPENDMT3_LOW_LATENCY=off: Windows' sound engine left at its own period; on by default,
                            * the shortest one the game's output offers asked for while the game runs (engine.c) */
} Settings;

/* The game's own picture, and its frame rate: its logic runs once a frame, so it holds 60 a second (measured: its
 * timers count frames). */
#define GAME_W 1280
#define GAME_H 768
#define GAME_FPS 60

/* The frame rate chip's corners, in the launcher's order (values.py FPS_POSITIONS). The bottom right is the default:
 * measured on the game's screens, the chip there (above the game's FREE PLAY label) covers none of the game's own
 * labels or buttons, where every corner's very edge holds some. */
enum { CORNER_TOP_LEFT = 0, CORNER_TOP_RIGHT = 1, CORNER_BOTTOM_LEFT = 2, CORNER_BOTTOM_RIGHT = 3 };
/* A corner by the launcher's name for it (top_left, top_right, bottom_left, bottom_right, any case); -1 for none. */
int corner_from_name(const char *name);

/* The defaults: English, our pointer, the client's own frame steps, Windows' default sound device, no frame rate
 * chip (its corner the bottom right). */
void settings_default(Settings *s);
/* Read one value into the settings by the variable's name; an unknown or bad value leaves the default. */
void settings_read(Settings *s, const char *name, const char *value);
/* A GUID in Windows' text form ({xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx}, the braces optional) into 16 bytes, in the
 * order of Windows' GUID structure (Data1-3 little-endian); 1 when it is one. */
int parse_guid(const char *text, uint8_t out[16]);
/* The 16 bytes back to Windows' text form, in upper case with braces (39 bytes with the end). */
void format_guid(const uint8_t in[16], char out[39]);

/* --------------------------------------------------------------------------------------------- frame clock */

/* The frame clock, in ticks of a counter (QueryPerformanceCounter): when the next frame is due. */
typedef struct {
    int64_t period;        /* ticks a frame */
    int64_t next;          /* when the next frame may go out (0: no frame yet) */
} Pacer;

/* A pacer for `fps` frames a second on a counter of `frequency` ticks a second (fps 0: none). The pacer's next tick
 * may be moved by the music lock and the display lock below before pacer_wait reads it. */
void pacer_start(Pacer *p, int64_t frequency, int fps);
/* At `now`, how many ticks to wait before this frame goes out (0: at once); the pacer moves on by one frame.
 * A frame late by more than one period starts the count again from now, so a long load never makes a burst. */
int64_t pacer_wait(Pacer *p, int64_t now);

/* Locked to the music: the game's notes move once a frame, so frame k of a song belongs at k/60 s of its music. Each
 * frame, how far the music is ahead of the frames (ms; positive: the frames are behind, as after a stall) moves the
 * next tick: smoothed over frames (the sound card's cursor moves in steps), nothing within 1 ms, at most 1 ms a
 * frame for a small drift and 4 ms a frame to win back a stall, so a correction is spread over many frames and never
 * skips or doubles one. */
typedef struct {
    double smooth;         /* the smoothed distance, ms */
    int primed;            /* a first reading taken */
} MusicLock;
void music_lock_start(MusicLock *m);
/* The ticks to take off the next frame's tick (negative: to add), for a frame of `period` ticks. */
int64_t music_lock_step(MusicLock *m, double ahead_ms, int64_t period);

/* Locked to the display (VSync on): the pacer's ticks kept in the middle of a refresh, so each frame's present
 * waits for the same refresh every time (on a 240 Hz display, every fourth) and a tick never wavers either side of
 * one. `phase` is where in its refresh the tick fell (0 the start of the refresh, 1 its end; negative: not known);
 * returns the ticks to move the next tick by (at most a 64th of a refresh a frame). */
int64_t display_lock_step(double phase, int64_t refresh_ticks);

/* The post-process chain's safety net: a frame counts against the chain when it took longer than the 60 a second
 * budget (with 1 ms to spare) and would not have without the chain's time; two windows of 60 frames in a row with 30
 * such frames each step the chain down. The game's first 10 s (its loading) are not counted, nor the frames right
 * after a step while its readings catch up. */
typedef struct {
    int seen, late;        /* frames counted in this window, and those late by the chain's doing */
    int bad;               /* windows in a row with GUARD_NEED late frames */
    int settle;            /* frames still not counted after a start or a step */
    double chain_ms;       /* the chain's time a frame, smoothed */
} Guard;
#define GUARD_WINDOW 60
#define GUARD_NEED 30
void guard_start(Guard *g);
/* One frame's length and the chain's time for a recent frame (ms; negative: not known). 1 when the chain should step
 * down now (the window then starts again). */
int guard_frame(Guard *g, double frame_ms, double chain_ms);

/* ------------------------------------------------------------------------------------------- keys the game sees */

/* While the layer holds the input, the game's view of the keyboard and the mouse's buttons (GetKeyboardState's
 * 256 bytes) is changed in place: with the menu or the question up, nothing is down; after they close (or after a
 * press on the layer's buttons), the keys and the button that answered them stay up for the game until they are
 * really released, so the answer never reaches the game as a touch or a key. Esc never reaches the game: the game's
 * own Esc ends it at once with no question, a quit by a key as Alt+F4 would be, and only the bar's X quits. Returns
 * the new `waiting` value. */
int hold_keys(uint8_t keys[256], int card_open, int waiting);

/* ------------------------------------------------------------------------------------------ menu and question */

enum { CARD_NONE = 0, CARD_MENU = 1, CARD_QUIT = 2 };
/* What a key or a choice does. */
enum { ACT_NONE = 0, ACT_REDRAW = 1, ACT_CLOSE = 2, ACT_QUIT = 3, ACT_FPS = 4 };

typedef struct {
    int open;              /* CARD_NONE, CARD_MENU or CARD_QUIT */
    int focus;             /* the row or answer the keyboard's ring is on */
    int korean;
    int fps;               /* whether the frame rate chip shows (the menu's Show FPS row says it and turns it) */
    int song;              /* a song plays: the question says what quitting loses only then (on the game's menus it
                            * would not be true) */
} Card;

/* How many answers the card has: the menu's three rows (Back to the game, Show FPS, Quit the game), the question's
 * two (Keep playing, Quit the game). */
int card_count(const Card *c);
/* The words of answer i, in the card's language (UTF-8, in capitals as the game writes its buttons); whether it is the
 * one that quits. */
const char *card_label(const Card *c, int i, int *danger);
/* The state a row shows at its right (Show FPS: ON or OFF), or NULL. */
const char *card_state(const Card *c, int i);
/* The question's title and its one line (as the game writes its own: a sentence); NULL for the menu, which has
 * neither. The line is there only while a song plays (c->song): NULL on the game's menus. */
const char *card_title(const Card *c);
const char *card_line(const Card *c);
/* Open the menu or the question, the ring on the first answer (going on), so Enter at once keeps the game. */
void card_open(Card *c, int what);
/* A key while the card is open (Windows' virtual-key numbers): what it does. */
int card_key(Card *c, unsigned vk);
/* Answer i chosen (Enter or a click): what it does. The menu's Show FPS turns c->fps over and leaves the menu open
 * (ACT_FPS); the layer shows or hides the chip by it. */
int card_choose(Card *c, int i);

/* ------------------------------------------------------------------------------------------------- layout */

/* A box on the screen, in pixels. */
typedef struct {
    float x, y, w, h;
} Box;

/* Output pixels per game pixel for a game area this many pixels tall: the game draws 768 lines, so everything of the
 * layer keeps the game's own proportions and type sizes at every size of the window, as the game's own panels do
 * (Windows' scaling sizes the pointer, which Windows draws). */
float ui_unit(int area_h);

/* Where the layer's parts go in a game area w x h (output pixels, (0, 0) its top left), with the menu or the question
 * open as the card says. Everything stays in the game's top band and at its right: nothing in the middle, where the
 * notes come. */
/* The bar's chips, left to right at its right end: the menu, then the window's own three as Windows orders them
 * (minimise, full screen or back to a window, the X), a little apart from the menu. */
enum { CHIP_MENU = 0, CHIP_MIN = 1, CHIP_FULL = 2, CHIP_X = 3, CHIPS = 4 };
typedef struct {
    float u;               /* output pixels per game pixel */
    Box bar;               /* the top bar: the game's whole width, as tall as the game's own top bar */
    float name_x, name_y;  /* the product's name: its left edge and its middle */
    float name_h;          /* the product's mark's height (the launcher's picture of it is drawn to this height) */
    Box chip[CHIPS];       /* the bar's chips at its right (CHIP_*), each the box its leaning plate fills */
    Box panel;             /* the menu or the question, dropped down under its chip (w 0: none open) */
    Box tab;               /* the question's title tab, hanging from the panel's top edge */
    float line_y;          /* the question's one line, its capitals' middle (with no line: none) */
    Box rows[4];           /* the menu's rows, or the question's answers side by side */
    int count;
    float px_name, px_title, px_line, px_button;   /* type sizes, output pixels */
} UiLayout;
void ui_layout(const Card *c, int area_w, int area_h, UiLayout *out);

/* What a point of the game area is on while the bar shows: a chip (the menu's, minimise, full screen, the X), an
 * answer (0 to 3), the open panel elsewhere, the bar elsewhere, or nothing of the layer's. */
enum { HIT_NONE = -1, HIT_MENU = 100, HIT_X = 101, HIT_PANEL = 102, HIT_BAR = 103, HIT_MIN = 104, HIT_FULL = 105 };
int ui_hit(const UiLayout *l, float x, float y);
/* The chip a hit is on (CHIP_*), or -1 for any other hit. */
int ui_hit_chip(int hit);

/* The pointer at the very top edge of the game area (the bar's own way in: the band where the game draws no note). */
int ui_at_top_edge(float y, int area_h);
/* A press that began at the top edge and is drawn down this far: a finger asking for the bar. */
int ui_swipe_down(float start_y, float y, int area_h);

/* The mark at the top centre that says where the bar is: a small tab in the game's own tab shape hanging from the top
 * edge, taller while the pointer is on it (`lit`). Clicks go through it to the game. */
Box ui_mark_box(int area_w, int area_h, int lit);
/* Whether a point is on the mark, or near enough to rest there (its box and 10 game pixels round it). */
int ui_on_mark(float x, float y, int area_w, int area_h);

/* When the bar may come from a rest (the pointer at the top edge or on the mark): the pointer must have moved there
 * with no button down and stayed REVEAL_REST_MS, and the game must have had no press or release for REVEAL_QUIET_MS
 * (a click or a held note at the top of a song is play, never a wish for the bar). A press or a release takes the rest
 * back: the pointer must move there again. Times in milliseconds of any one clock. */
#define REVEAL_REST_MS 150.0
#define REVEAL_QUIET_MS 1500.0
typedef struct {
    double pressed_at;     /* the last press or release on the game (far in the past at the start) */
    int down;              /* a button is down on the game now */
    int armed;             /* the pointer came to rest at the top edge or on the mark by moving there */
    double rest_at;        /* when it came there */
} RevealGate;
void gate_start(RevealGate *g);
/* A press (`down` 1) or a release (0) of a mouse button on the game. */
void gate_press(RevealGate *g, double now, int down);
/* The pointer moved over the game: `at_place` whether it is at the top edge or on the mark now, `button_down` whether
 * a button is held. */
void gate_move(RevealGate *g, double now, int at_place, int button_down);
/* Whether the bar comes now from the rest (`still_there`: the pointer is at the place now); 1 takes the rest back. */
int gate_due(RevealGate *g, double now, int still_there);
/* No press or release for REVEAL_QUIET_MS and nothing down: a finger drawn down from the top edge brings the bar only
 * when its press came after such a quiet. */
int gate_quiet(const RevealGate *g, double now);
/* A pause longer than GATE_STALL_MS with no frame of the game's (a load, a hitch, the game held or minimised): the
 * presses made meanwhile reach the game only after it, so the pause is neither rest nor quiet. */
#define GATE_STALL_MS 250.0
/* The game drew no frame for `gap` ms before `now`: a press and a rest from before the pause move on by it, so each
 * stands as far back in the game's running time as it did. */
void gate_stall(RevealGate *g, double now, double gap);

/* How long the bar stays, as OpenDMTQ's bar: whole for BAR_STAY_MS after the pointer was last on it (or after a rest
 * brought it), then fading over BAR_FADE_MS; a finger's bar whole for BAR_TOUCH_MS (a finger leaves no pointer on
 * it); by itself (the game's first screen, a switch between a window and full screen) whole for BAR_REVEAL_MS whatever
 * the pointer does. Times in milliseconds of any one clock. */
#define BAR_STAY_MS 600.0
#define BAR_FADE_MS 300.0
#define BAR_TOUCH_MS 4000.0
#define BAR_REVEAL_MS 3000.0
typedef struct {
    double since, stay;    /* whole until since + stay */
    double reveal_until;   /* and until this, by itself */
    int by_touch;          /* brought by a finger: the pointer Windows parks where it was is no mouse on the bar */
    int parked;            /* came by itself: a pointer left on its band before is no mouse on it until it moves */
} BarClock;
void bar_clock_start(BarClock *b);
/* A rest at the top edge or on the mark brought it, or the pointer is on it now: whole for BAR_STAY_MS from now (a
 * finger's bar keeps its own time). */
void bar_clock_rest(BarClock *b, double now);
/* A finger drawn down from the top edge brought it. */
void bar_clock_touch(BarClock *b, double now);
/* It shows by itself. */
void bar_clock_reveal(BarClock *b, double now);
/* A press on the game: it goes at once (fading). */
void bar_clock_hide(BarClock *b);
/* The mouse moved with its button up: the pointer is the mouse's again (no finger's, not parked). */
void bar_clock_moved(BarClock *b);
/* Whether the pointer on the bar's band keeps it whole now: not a finger's, and not one parked there before the bar
 * came by itself (it would keep the bar on the game for good while nobody moves it). */
int bar_clock_pointer_counts(const BarClock *b);
/* Whether it is whole now (after that it fades out over BAR_FADE_MS). */
int bar_clock_whole(const BarClock *b, double now);

/* The toast: hanging from the game's top edge in the middle, as wide as its words need (`text_w` pixels). */
Box toast_box(int area_w, int area_h, float text_w);
/* The frame rate chip in its corner (CORNER_*): 12 game pixels in from the side; at the top 6 down, at the foot above
 * the game's own labels there (ID CARD and NET at the left, FREE PLAY at the right, which start 35 and 26 lines up). */
Box fps_box(int area_w, int area_h, int corner);
/* The chip's opacity as a whole: faint, so the game shows through it (62 %, as OpenDMTQ's counter). */
#define FPS_ALPHA 0.62f

/* Motion: a value from 0 to 1 eased out (fast at first, settling), for slides and fades. */
float ease_out(float t);

/* The safety net's note: one line saying the picture's quality was lowered and how, in the card's language (UTF-8),
 * into `out`. `aa_changed`: the anti-aliasing changed (to `aa`); otherwise the upscale filter (to bilinear). */
void note_words(int korean, int aa_changed, int aa, char *out, int size);

/* ------------------------------------------------------------------------------------------ the picture's place */

/* Where the game's picture goes in a client area of cw x ch pixels: the whole of it (`fill`), or the largest rectangle
 * of the game's own shape (1280:768, 5:3) centred in it, the rest bars on two sides. Whole pixels. */
typedef struct {
    int x, y, w, h;
} PicRect;
PicRect picture_rect(int cw, int ch, int fill);
/* The display fix's own sums for the game's pointer (opendmt3/core/cabinet/display.py, hook_gcp): a point in client
 * pixels to the game's pixel, scaled from the client's size to 1280x768 with integer division. */
void game_from_client(int qx, int qy, int cw, int ch, int *gx, int *gy);
/* The point (client pixels) to hand those sums so they give the game pixel under the centre of client pixel (px, py)
 * in the picture shown at `r`: the pixel whose area holds that centre, as every upscale filter draws it there. Outside
 * the picture (a bar), the same mapping carried on: the game sees a point past its edge. */
void pointer_for_game(int px, int py, int cw, int ch, PicRect r, int *qx, int *qy);

/* ------------------------------------------------------------------------------------------------- slot index */

/* Where each key (a pointer, never NULL) sits in a table of the caller's, for up to half SLOT_INDEX_SIZE keys: open
 * addressing with linear probing and backward-shift deletion (no tombstones, so a long run's comings and goings keep
 * every look up a step or two). sound.c finds the game's sound buffers so, on each of its DirectSound calls, instead
 * of walking 4096 slots. */
#define SLOT_INDEX_SIZE 8192
typedef struct {
    const void *key[SLOT_INDEX_SIZE];
    int slot[SLOT_INDEX_SIZE];
} SlotIndex;
/* The slot of `key`, or -1. */
int slot_index_get(const SlotIndex *x, const void *key);
/* `key` at `slot` (a key already in it takes the new slot); 0 when the index is full. */
int slot_index_put(SlotIndex *x, const void *key, int slot);
/* `key` out of it (nothing when it is not in it). */
void slot_index_del(SlotIndex *x, const void *key);

/* ---------------------------------------------------------------------------------- the sound engine's period */

/* What became of asking Windows' shared sound engine for its shortest period on the game's output (engine.c), in the
 * order a start meets them; ENGINE_NAMES holds each one's word for the log and the launcher's note. */
enum {
    ENGINE_OFF,            /* the launcher's Low latency is off: nothing asked */
    ENGINE_NO_DEVICE,      /* the game's output not found among Windows' endpoints (or COM not there to look) */
    ENGINE_NO_CLIENT3,     /* the endpoint has no IAudioClient3 (Windows before 10): no way to ask */
    ENGINE_NO_ANSWER,      /* its periods not read, or an answer that breaks the API's own rules */
    ENGINE_NONE_SHORTER,   /* the driver's shortest period is its default: nothing to ask for */
    ENGINE_LOCKED,         /* another program's stream holds the engine at a period of its own */
    ENGINE_REFUSED,        /* the stream was refused for another reason (its HRESULT is in the report) */
    ENGINE_UNCHANGED,      /* the stream ran, but the engine kept its default period (as Wine does): let go */
    ENGINE_HELD,           /* the engine runs at the shorter period, held until the game ends */
    ENGINE_RESULTS
};
extern const char *const ENGINE_NAMES[ENGINE_RESULTS];

/* One start's report, every period in frames at the device's mix rate: GetSharedModeEnginePeriod's four numbers, the
 * engine's own period before the ask and after the stream started, the period asked (0: none), the last HRESULT. */
typedef struct {
    int result;            /* ENGINE_* */
    int chosen;            /* the launcher's chosen device (0: Windows' default output) */
    uint8_t device[16];    /* its DirectSound GUID as the game opened it (all 0: not known) */
    unsigned rate;         /* the device's mix format, frames a second (0: not read) */
    unsigned def, step, min, max;
    unsigned before, asked, got;
    unsigned long hr;
} EngineReport;

/* The period to ask for, from what IAudioClient3 says of the device's mix format: its minimum, made a whole number of
 * its fundamental step and kept within its maximum; 0 when there is nothing to ask: no period shorter than the
 * default, or an answer that breaks the API's own rules (a zero, the minimum past the maximum, the default outside
 * them; Wine's PulseAudio driver answers a minimum of 0). */
unsigned engine_period_ask(unsigned def, unsigned step, unsigned min, unsigned max);
/* Whether the engine's period after the stream started (`got`, 0: not read) is shorter than its default: only then is
 * the stream worth holding (a shorter period another program holds counts too: it stays while the game runs). */
int engine_period_held(unsigned def, unsigned got);
/* Frames at a rate, in milliseconds (0 when the rate is not known). */
double engine_ms(unsigned frames, unsigned rate);
/* The launcher's note (openDMT3-sound.txt beside the DLL), one line of words and numbers it reads back: "engine held
 * output=chosen device={...} rate=48000 default=480 step=16 min=128 max=480 before=480 asked=128 got=128
 * hr=0x00000000" (output=default for Windows' default output). */
void engine_note(const EngineReport *r, char *out, int size);

#endif
