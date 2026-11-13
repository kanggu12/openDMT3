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
    int sound_path;        /* OPENDMT3_SOUND_PATH: SOUND_PATH_* below (Windows' DirectSound unless chosen) */
    int render_display;    /* OPENDMT3_RENDER=display: the game drawn at the picture's size in the window (render.c),
                            * not at its own 1280x768 enlarged after (game, the default) */
    int audio_offset;      /* OPENDMT3_AUDIO_OFFSET: milliseconds the frames are kept behind a song's music, for a sound
                            * device that plays late (Sound page, Audio offset; 0 to AUDIO_OFFSET_MAX, 0 by default);
                            * with the music lock only */
    int motion;            /* OPENDMT3_MOTION_CLARITY: MOTION_* (Screen page, Motion clarity; off by default) */
    int flip;              /* OPENDMT3_FLIP_MODEL=on: Direct3D 9Ex's flip model for the borderless window (Screen page,
                            * Advanced, Flip model; off by default) */
} Settings;
/* Motion clarity's choices (strobe.c): off, a CRT's rolling beam, black frames (every row lit from the frame's first
 * refresh), by the launcher's names off, crt and bfi (values.py MOTION_CLARITIES). */
enum { MOTION_OFF = 0, MOTION_CRT = 1, MOTION_BFI = 2 };
/* The audio offset's most, ms: past the delays of Bluetooth and HDMI outputs (100 to 300 ms). The frames can always be
 * held back to a later music; none is offered the other way: on a 60 Hz display with VSync, frames cannot come sooner
 * than one a refresh, so frames ahead of the game's own start would never be reached. */
#define AUDIO_OFFSET_MAX 500

/* The way the game's DirectSound calls reach the device (openal.c), in the launcher's order: Windows' own DirectSound
 * (the default), or DSOAL's DirectSound over OpenAL Soft on WASAPI in shared mode or in exclusive mode. */
enum { SOUND_PATH_DIRECTSOUND = 0, SOUND_PATH_OPENAL = 1, SOUND_PATH_OPENAL_EXCLUSIVE = 2, SOUND_PATHS = 3 };
/* Their names (the launcher's, values.py SOUND_PATHS). */
extern const char *const SOUND_PATH_NAMES[SOUND_PATHS];

/* The game's own picture, and its frame rate: its logic runs once a frame, so it holds 60 a second (measured: its
 * timers count frames). */
#define GAME_W 1280
#define GAME_H 768
#define GAME_FPS 60

/* The frame rate chip's corners, in the launcher's order (values.py FPS_POSITIONS). The bottom right is the default:
 * measured on the game's screens, the chip there (one line beside the game's FREE PLAY label, on its line, where at most
 * the foot of a note's ring passes) covers none of the game's own labels or buttons, where every corner's very edge
 * holds some. */
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
/* The most the lock's next step may take off a tick, in ms: 4 while it wins back a stall (or before its first reading,
 * which may be one), 1 otherwise (the frame started just in time keeps that much spare for it). */
double music_lock_most(const MusicLock *m);

/* The music lock over a game's songs (hooks.c lock_to_music): the song locked (its music's start frame), the distance
 * the game itself started that music at against its frames, kept for the whole song, and the lock's readings. Through a
 * reset of the device or a frame with no reading, the same song goes on from its own start: a reset's stall is won back
 * as any stall is, and the audio offset stays counted once. A song with another start frame takes its own. */
typedef struct {
    long song;             /* the locked song's music start frame (-1: none yet) */
    double base;           /* that song's first distance, ms (the game's own start, kept) */
    int fresh;             /* the lock's readings start again at the song's next frame (after a reset or a gap) */
    int playing;           /* a song was read at the last frame (its lock moved that frame's tick) */
    MusicLock lock;        /* the readings, smoothed */
} SongLock;
void song_lock_start(SongLock *s);
/* A reset of the device, or a frame with no song to read: the lock's readings start again at the next song frame,
 * the song and its start kept. */
void song_lock_pause(SongLock *s);
/* A song frame: the song's music started at frame `started` and is `ahead` ms ahead of this frame at its tick; the
 * frames are held `offset` ms more behind it (the audio offset). The ticks to take off the next tick (negative: to
 * add); *began set when this frame began the lock of a song, *off the distance from the lock's target, ms. */
int64_t song_lock_frame(SongLock *s, long started, double ahead, int offset, int64_t period, int *began, double *off);

/* Locked to the display (VSync on): the pacer's ticks kept in the middle of a refresh, so each frame's present
 * waits for the same refresh every time (on a 240 Hz display, every fourth) and a tick never wavers either side of
 * one. `phase` is where in its refresh the tick fell (0 the start of the refresh, 1 its end; negative: not known);
 * returns the ticks to move the next tick by (at most a 64th of a refresh a frame). */
int64_t display_lock_step(double phase, int64_t refresh_ticks);

/* Catching up with the music on a display that takes no frame sooner than its refresh. With VSync on, a present waits
 * for the display's next refresh, so a display under CATCHUP_HZ (60 Hz, the usual one, 59 for 59.94, or slower) shows
 * a new frame at most a millisecond a frame sooner than the game's 60 a second: the music lock's step taken off a tick
 * never reaches the screen, and frames behind the music after a stall would stay behind for the rest of the song. On
 * such a display the lock takes nothing off a tick (it still holds frames back, which a later refresh shows), and a
 * frame is left unshown instead: the game runs it, its present is not made, and the next frame goes out on its tick,
 * a whole frame (16.7 ms) further into the song. A display from CATCHUP_HZ up (75, 120, 144, 240 Hz), or VSync off,
 * takes the lock's own steps: nothing is left unshown there. */
#define CATCHUP_HZ 64
/* Whether a display takes no frame sooner than its refresh: VSync on and a refresh rate (Hz, as Windows gives it;
 * 0: not known) above 0 and under CATCHUP_HZ. */
int catchup_display(int vsync, int hz);
/* The frames' distance behind the music (the lock's reading at each frame shown, ms past its target; positive: behind)
 * is read over the frames shown since the last frame left unshown: when the median of the last CATCHUP_READINGS is
 * more than a frame, the next frame is left unshown, so at most one frame in CATCHUP_SPACING (one left out, five
 * shown) and never two in a row; once that median is within a frame, the catch-up is over. A frame is left unshown
 * only when the next one's work, the GPU's too, can be done before the refresh the skipped frame would have been shown
 * at; a frame after a skip that goes out, or has its picture done, later than a sixteenth of a refresh before it may
 * have missed it (the frame before shown twice, nothing won): no frame is left unshown for CATCHUP_REST frames after
 * it, nor for the rest of the song after CATCHUP_LATE of them. */
#define CATCHUP_READINGS 5
#define CATCHUP_SPACING (CATCHUP_READINGS + 1)
#define CATCHUP_REST 300
#define CATCHUP_LATE 3
typedef struct {
    double read[CATCHUP_READINGS]; /* the readings since the last frame left unshown, ms behind the music */
    int n, at;             /* how many of them (the oldest replaced past CATCHUP_READINGS), and where the next goes */
    int rest;              /* frames shown before one may be left unshown again (after one too late) */
    int late_song;         /* frames after a skip too late this song */
    int running;           /* a catch-up runs: it began with a frame to leave unshown and is not within a frame yet */
    int skips, late, unfit;    /* in it: frames left unshown, frames after them too late, frames not left unshown after
                                * all (the next one would not have been ready before the refresh, or a panel came) */
    long frames;           /* in it: the game's frames since it began, shown and not */
    double from_ms, to_ms; /* how far behind the music it began, and is now (ms) */
    int done;              /* a catch-up just ended within a frame (its numbers above, for its line): the caller
                            * clears it */
} CatchUp;
/* A new song's catch-up, nothing read yet. */
void catchup_start(CatchUp *c);
/* One frame shown while a song's music leads: the lock's reading `behind_ms`, and whether a frame may be left
 * unshown now (`may`: a display that takes no frame sooner, its ticks kept to its refresh, no glass panel up). 1 when
 * the next frame is to be left unshown (the caller then calls catchup_skipped or catchup_unfit for it). */
int catchup_frame(CatchUp *c, double behind_ms, int may);
/* For the frame to be left unshown, at `now` (its present asked for), due at the frame clock's `tick`, with the
 * display's `phase` now (0 the start of its refresh, 1 its end; negative: not known), every time a counter's: when the
 * blank begins that ends the refresh it would have been shown in, the first after its tick (after now, when it came
 * past its tick). The phase runs over the visible lines only (the raster's line over the mode's height), so the rest
 * of a refresh is taken as CATCHUP_VISIBLE of what it says: the blank after the visible lines is a few hundredths of a
 * refresh at the usual timings (45 lines of 1125 at 1080p). With no phase known, the earliest the display lock leaves
 * it: three eighths of a refresh after the tick. */
#define CATCHUP_VISIBLE 0.95
int64_t catchup_deadline(int64_t now, int64_t tick, int64_t refresh, double phase);
/* The least the next frame takes from the skipped frame's present to its picture done on the GPU: its work on the
 * processor (`cpu`: the slowest of the recent frames', from the game's control back to the frame ready to present),
 * then the post-process chain's passes on the GPU (`chain`: the slowest of the recent frames' chain on the GPU, timed
 * by its timestamps; 0: not timed), which start only once the processor's part hands them over. The game's own GPU
 * work is not timed: a frame after a skip whose picture comes too late for its refresh says so (catchup_after). */
int64_t catchup_work(int64_t cpu, int64_t chain);
/* Whether the next frame, started at once at `now`, goes out with its picture done an eighth of a `refresh` before
 * that `deadline` at the latest: done by its `work` (catchup_work), and not before the skipped frame's `tick`, which it
 * takes over. It then takes the refresh the skipped frame would have had. */
int catchup_fits(int64_t now, int64_t tick, int64_t deadline, int64_t work, int64_t refresh);
/* A reset of the device in the song: the readings start again at the song's next frame shown, the catch-up running and
 * its numbers kept, and the song's frames too late with them (the song goes on from its own start, as the lock does). */
void catchup_pause(CatchUp *c);
/* The planned frame was left unshown. */
void catchup_skipped(CatchUp *c);
/* The planned frame was shown after all (its next would not have been ready, or a panel came): the readings start
 * again, so the next try is CATCHUP_SPACING frames on. */
void catchup_unfit(CatchUp *c);
/* The frame after a skip went out: `in_time` whether it left, its picture done on the GPU, a sixteenth of a refresh
 * before the deadline at least. */
void catchup_after(CatchUp *c, int in_time);

/* Starting each frame just in time: the game reads its input at the start of its frame (GetKeyboardState, as soon as a
 * present hands control back), so a frame that waits for its tick at its end shows input a whole period old. With this
 * clock, the wait moves to before the frame instead: after a present, the game's next frame is held until its tick less
 * the time its work takes on the processor (from the moment it gets control back to the frame ready to present, the
 * slowest 1 % of the last JIT_WINDOW frames), less a spare that grows when a frame misses its tick (its picture not
 * done on the GPU by then) and shrinks back slowly while frames are in time. Ticks themselves do not move: the frames
 * still leave at 60.0 a second on their ticks, locked to the music and kept to the display as before. The first
 * JIT_SETTLE frames (the game's loading) start at once, as without it, and so do JIT_REST frames after JIT_STREAK
 * frames started late in a row missed their tick with the spare at its most (a GPU slower than the spare can cover:
 * holding frames would only make them late). */
#define JIT_WINDOW 120
#define JIT_SETTLE 600
typedef struct {
    int64_t period;        /* ticks a frame (0: no clock, never early) */
    int64_t frequency;     /* the counter's ticks a second */
    int64_t work[JIT_WINDOW];  /* the last frames' work on the processor, ticks: from the game's control back to the
                                * frame ready to present (its draws handed over, the frame before done on the GPU) */
    int kept, at;          /* how many of them are kept, and where the next goes */
    int64_t spare;         /* ticks kept spare before the tick, beyond the work */
    int calm;              /* frames in a row in time since the spare last grew */
    int settle;            /* frames still started at once (the game's loading) */
    int streak;            /* frames started late in a row that missed their tick with the spare at its most */
    int rest;              /* frames still started at once after such a streak */
} JitClock;
/* The spare's least and most: 1 ms, and a quarter of a frame. A miss adds 1 ms; after JIT_CALM frames in a row in time
 * (5 s) it gives back a tenth of a millisecond a frame down to the least. */
#define JIT_SPARE_MS 1.0
#define JIT_CALM 300
/* Three misses in a row at the most spare: five seconds of frames started at once, then the clock tries again. */
#define JIT_STREAK 3
#define JIT_REST 300
void jit_start(JitClock *j, int64_t frequency, int fps);
/* One frame's work on the processor in ticks, and whether its picture was done before its tick (`in_time` 0: it was
 * not); `early` whether the frame was started late by this clock (a miss there grows the spare; a frame started at once
 * tells the work alone). */
void jit_frame(JitClock *j, int64_t work, int in_time, int early);
/* How long before the next tick the next frame should start, in ticks: its work, the spare, and `slack` (what may still
 * move the tick earlier before the frame leaves: the music lock's and the display lock's most); 0 when the next frame
 * should start at once (no clock, still loading, resting after a streak of misses, or no room in a period). */
int64_t jit_lead(const JitClock *j, int64_t slack);
/* The work the lead counts on, ticks: the slowest 1 % of the kept frames (the second slowest of 120). */
int64_t jit_work(const JitClock *j);

/* Motion clarity's refreshes a frame for a display's rate in Hz: N for a whole multiple N of 60 from 120 up, within
 * 1 Hz (Windows gives a rate of 119.88 or 239.76 Hz as 119 or 239), 0 for any other rate. */
int strobe_refreshes(int hz);

/* The flip model's present statistics over two seconds, judged: whether the display follows the frames (a variable
 * refresh rate). `refreshes_a_frame` is what the display's mode gives a 60 a second frame (4 at 240 Hz); `steps` the
 * game's own frames that were the only present shown since the one before, `one_steps` those shown one refresh after
 * it. It follows when the mode gives two or more and nine in ten of at least 60 such frames took one. */
int display_follows(int refreshes_a_frame, long steps, long one_steps);

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
/* guard_frame for a frame shown in `presents` presents: one shown over motion clarity's sub-frames (more than one) is
 * not judged, nor counted (the sub-frames' own wait leaves the game's next frame a refresh, which says nothing of the
 * chain's cost: a lighter picture would not give it more); 0 then, guard_frame's answer otherwise. */
int guard_frame_shown(Guard *g, double frame_ms, double chain_ms, int presents);

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
    Box panel;             /* the menu or the question, hanging from the bar's foot under its chip (w 0: none open) */
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

/* The mark at the top centre that says where the bar is, the bar's handle (OpenDMTQ's word): a rail along the top edge
 * and a small tab in the game's own tab shape hanging from it, deeper while the pointer is on it (`lit`), within the
 * game's top 12 lines (the groove meter's chrome rim in a song). Its box is the rail's width and the tab's depth.
 * Clicks go through it to the game. */
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
 * brought it), then it slides back up into the top edge (the layer's slides, below); a finger's bar whole for
 * BAR_TOUCH_MS (a finger leaves no pointer on it); by itself (the game's first screen, a switch between a window and
 * full screen) whole for BAR_REVEAL_MS whatever the pointer does. Times in milliseconds of any one clock. */
#define BAR_STAY_MS 600.0
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
/* A press on the game: it goes at once (sliding up). */
void bar_clock_hide(BarClock *b);
/* The mouse moved with its button up: the pointer is the mouse's again (no finger's, not parked). */
void bar_clock_moved(BarClock *b);
/* Whether the pointer on the bar's band keeps it whole now: not a finger's, and not one parked there before the bar
 * came by itself (it would keep the bar on the game for good while nobody moves it). */
int bar_clock_pointer_counts(const BarClock *b);
/* Whether it is wanted whole now (after that it slides up). */
int bar_clock_whole(const BarClock *b, double now);

/* The toast: hanging from the game's top edge in the middle, as wide as its words need (`text_w` pixels), its right end
 * kept a gap left of the menu and the question, which hang under the bar's right end (moved left on a screen too
 * narrow). */
Box toast_box(int area_w, int area_h, float text_w);
/* The frame rate chip, one line, in its corner (CORNER_*): at the foot on the line of the game's own labels, below its
 * notes but the foot of a ring (left of FREE PLAY at the right, after ID CARD, NET and PATCH at the left); at the top 6
 * down and 12 in from its side. */
Box fps_box(int area_w, int area_h, int corner);
/* The chip's glass's opacity: faint, so the game shows through it, and its words, drawn over it whole, keep 4.5:1 over
 * a white screen (the lightest, its quieter grey line: 4.8:1; at 62 %, the whole chip's opacity before, its words over
 * the game's brightest song came to 2.8:1). */
#define FPS_ALPHA 0.80f

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
/* The size the game is drawn at when it is drawn at the picture's size (OPENDMT3_RENDER=display, render.c): the
 * picture's place in a client of cw x ch (picture_rect), held in the picture's own shape to the device's largest
 * texture sides (max_w x max_h; 0 for no limit), and never smaller than the game's own 1280x768 (in a window that small
 * the game is drawn at its own size and shrunk after). */
void render_size_for(int cw, int ch, int fill, int max_w, int max_h, int *w, int *h);
/* The size the game is drawn at after a reset of the device: chosen anew (`chosen_w` x `chosen_h`, render_size_for's)
 * after the game's own reset, which makes its targets again; kept (`kept_w` x `kept_h`, the size before) after one of
 * openDMT3's own (`own`: the flip model's, for a window that changed size), which the game does not know of and through
 * which its targets made at the render size live on (a 9Ex reset keeps them). */
void render_size_after_reset(int own, int kept_w, int kept_h, int chosen_w, int chosen_h, int *w, int *h);
/* One of the game's coordinates (a rectangle's edge, in its pixels) on an axis of `from` pixels to one of `to`,
 * rounded to the nearest whole pixel, halves away from zero; the same sum turns it back (from and to swapped). */
long scale_edge(long v, int from, int to);
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

/* -------------------------------------------------------------------------------------------- the layer's slides */

/* How the bar comes down out of the game's top edge and goes back up into it, and the menu, the question and the notice
 * out from under its foot (layer.c moves them by it once a frame, on the frame's clock, so each step of the way is one
 * of the display's refreshes): a place from 0 (out of sight) to 1 (in place). A way down takes SLIDE_DOWN_MS and slows
 * into its place (a cubic ease out: a thing that arrives is watched); a way up takes SLIDE_UP_MS and gathers speed (a
 * quadratic ease in: a thing that leaves is not waited for). A way begun midway (the pointer back on a bar on its way
 * up) starts from where the part is and takes the share of the whole way's time its length is, so a turn never jumps.
 * With Windows' animation effects off a way takes no time: the part comes and goes at once. The same motion as
 * OpenDMTQ's bar, so the two products move alike. */
#define SLIDE_DOWN_MS 220.0
#define SLIDE_UP_MS 170.0
typedef struct {
    float from, to;        /* where the way set out from and where it is headed (0 or 1) */
    double began;          /* when it set out, ms of any one clock */
    double lasts;          /* how long the way takes, ms (0: at rest at `to`) */
} Slide;
/* At rest at `place` from now on, whatever it was doing. */
void slide_rest(Slide *s, float place);
/* Where it is at `now`: from 0 to 1. */
float slide_at(const Slide *s, double now);
/* Whether it is on its way at `now` (not yet where it is headed). */
int slide_moving(const Slide *s, double now);
/* Headed for `target` (0 or 1) from where it is at `now`; a way already headed there goes on as it is. `animate` 0
 * (Windows' animation effects off): there at once. */
void slide_aim(Slide *s, float target, double now, int animate);
/* The way down's pace and the way up's, from a share of the way's time: 0 at 0, 1 at 1, never back. */
float slide_ease_down(float t);
float slide_ease_up(float t);

/* The room under a part's foot that its soft shadow takes, in game pixels: a part slides by its own height and this,
 * so nothing of it shows at place 0, its shadow neither. */
#define SLIDE_SHADE 8.0f
/* How far below the game's top edge the bar's foot is at `place` (output pixels, 0 to bar_h; `shade` the room its
 * shadow takes, output pixels): what hangs from the bar (the menu, the question, the notice, the handle, a frame rate
 * chip in a top corner) hangs that much lower than at the top edge, and the handle fades as it grows. */
float slide_rows(float place, float bar_h, float shade);
/* The top of a part `h` tall that slides out from under a foot `rows` below the top edge (the top edge itself: 0): at
 * place 0 it is out of sight above the foot (its shadow too), at 1 its top is on the foot. The bar itself is such a
 * part under the top edge. */
float slide_top(float place, float rows, float h, float shade);

/* What a point of the game area is on (ui_hit's codes) while the bar and the panel slide: the bar and its chips
 * `bar_dy` from their places (negative: higher), the menu or the question `panel_dy` from theirs. The bar lies over the
 * panel (the panel slides out from under it), so on the bar a point is the bar's; above the game's top edge nothing of
 * the layer's. A press counts against the places the parts stood at when it was pressed, so a chip pressed while the
 * bar still comes down acts too. */
int ui_hit_moved(const UiLayout *l, float x, float y, float bar_dy, float panel_dy);

#endif
