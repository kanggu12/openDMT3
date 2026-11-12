/*
 * The in-game layer inside openDMT3's CRT_R1.dll: what its Windows parts share.
 *
 *   hooks.c  the game's imports turned to ours (DirectSound, Direct3D 9, the keyboard's state), the frame limit,
 *            the frame counter, holding the game still, and the log
 *   layer.c  the bar, the menu, the question, the toast and the frame rate chip: their state, the mouse and the keys
 *            over the game's window, the cursor, quitting
 *   post.c   the post-process chain, which draws the layer's parts over the game at the window's size
 *   text.c   the words (GDI)
 *   look.c, logic.c, paint.c  the pictures and the decisions, with no Windows calls (the native tests run them)
 */
#ifndef OPENDMT3_INGAME_H
#define OPENDMT3_INGAME_H

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

#include "logic.h"
#include "look.h"

/* The launcher's choices, read once when the DLL is loaded. */
extern Settings g_settings;
/* This DLL's own module (its folder holds the font the setup copies beside it). */
extern HMODULE g_module;

/* Called from DllMain: read the settings and turn the game's imports to ours. */
void ingame_attach(HMODULE module);
/* Turn the imports again if DllMain came before the game's imports were bound (called from the card reader's
 * first calls; does nothing once done). */
void ingame_hook_late(void);
/* One line in the in-game log (OPENDMT3_INGAME_LOG; nothing when it is not set). */
void ingame_log(const char *fmt, ...);
/* The path of the file `name` beside this DLL (in openDMT3's folder), wide, in `out` (room for `room` units); 0 when it
 * does not fit. */
int ingame_beside(const WCHAR *name, WCHAR *out, size_t room);
/* Put `ours` in every slot of `module`'s import table that holds `real`; how many slots were changed. */
int ingame_patch_imports(HMODULE module, void *real, void *ours);
/* The client's file calls turned to openDMT3's (files.c): its own files in the game's place, from the list beside the
 * DLL; called once from ingame_attach. */
void files_attach(void);

/* How the game draws, into the log, when OPENDMT3_INGAME_TRACE is set (trace.c): from its device's creation, and at
 * each frame. */
void trace_attach(void *device, const void *parameters, DWORD flags);
void trace_frame(void);

/* Time openDMT3's own code took in this frame, added by each hook that runs once a frame (the counter's line). */
void ingame_cost(LONGLONG ticks);

/* The post-process chain (post.c). Direct3D's types are named as structures, so this header needs no Direct3D one. */
struct IDirect3DDevice9;
struct _D3DPRESENT_PARAMETERS_;
/* Before the device is made (creating 1) or reset (0): whether the chain runs; if so the parameters are changed to the
 * real back buffer's (the window's monitor's size, copied, no depth surface or samples of Direct3D's own). */
int post_prepare(struct _D3DPRESENT_PARAMETERS_ *pp, HWND window, int creating);
/* The device was made with those parameters: the chain's objects, the game's draws turned to its proxy. 0 when it
 * could not be set up (the caller then resets the device to the game's own parameters). */
int post_attach(struct IDirect3DDevice9 *dev);
/* Around the game's reset: ours released before, made again after (0: the chain went off). */
void post_before_reset(struct IDirect3DDevice9 *dev);
int post_after_reset(struct IDirect3DDevice9 *dev, long reset_result);
/* At each present: the passes; the source rectangle to present (NULL: the game's own present, untouched). */
const RECT *post_present(struct IDirect3DDevice9 *dev);
/* The picture's GPU time by pass (OPENDMT3_PASS_TIMES=on): just after each present, the oldest frame's timestamps read
 * and the game's own next frame begun (post.c); every two seconds, the medians into the in-game log and, every ten,
 * into the launcher's note beside this DLL. */
void post_after_present(struct IDirect3DDevice9 *dev);
void post_pass_times_line(void);
/* This frame's cost of the passes: CPU in counter ticks, the GPU's in microseconds (-1: not known), how many. */
void post_cost(LONGLONG *cpu_ticks, double *gpu_us, int *passes);
/* Whether the chain is running. */
int post_running(void);
/* The layer's own CPU time this frame (counter ticks, inside the chain's), how many of its parts it drew, and how many
 * of those were glass panels (not the chip): frames with a panel are left out of the safety net's judgement. The
 * chain's own cost (post_cost) leaves the layer's out. */
void post_layer_cost(LONGLONG *cpu_ticks, int *parts, int *panels);
/* For what openDMT3 draws over the chain's picture before a present (the press mark):
 * the real back buffer the chain draws into (no reference added; NULL while no chain runs) and the client's size the
 * last frame was presented at; and the device's target set to it (ours 1, through the device's own SetRenderTarget,
 * no depth surface) or back to the game's (0: its proxy and its depth surface). */
struct IDirect3DSurface9;
struct IDirect3DSurface9 *post_back_buffer(int *w, int *h);
void post_target(struct IDirect3DDevice9 *dev, int ours);
/* Where the game's picture is in the window's client area (logic.c picture_rect), as the chain placed it at its last
 * present; w and h 0 while no chain runs (Direct3D's own stretch: the picture fills the client). */
void post_picture(int *x, int *y, int *w, int *h);
/* The safety net: the chain one step lighter from the next frame (postmath.c post_lighter), the new choice in *upscale
 * and *aa (*aa_changed: the anti-aliasing was the step); 0 when nothing lighter is left. */
int post_lighten(int *upscale, int *aa, int *aa_changed);

/* The game drawn at the picture's size in the window (render.c, OPENDMT3_RENDER=display). Direct3D's types are named
 * as structures here too. */
struct IDirect3DSurface9;
struct _D3DSURFACE_DESC;
/* The device's methods turned so the game's targets of its own size can be made at the render size and answer its own
 * size when asked (once a device; nothing changes until render_set). 0 when its tables could not be changed. */
int render_attach(struct IDirect3DDevice9 *dev);
/* The render size from now on (the game's own, or 0 x 0: every call passes as it is): the targets the game makes after
 * this at 1280x768 are made at w x h. */
void render_set(int w, int h);
/* Whether the game's targets are made at a render size larger than its own now. */
int render_on(void);
/* A surface's real size and kind, for the chain's own code (the game is answered its own size). */
long render_real_desc(struct IDirect3DSurface9 *s, struct _D3DSURFACE_DESC *d);
/* What the game asked of the replacements since the last call, one line into the log (nothing when none). */
void render_summary(void);
/* The study trace (trace.c) wraps some of the same methods: it hands over the game's own return address before it calls
 * on into them, and NULL after, so they judge the game's call and not the trace's. */
void render_from(const void *ret);

/* The game's sound, watched when OPENDMT3_SOUND_WATCH is set (sound.c): its DirectSound object as made, each frame's
 * cursor reading, and the counts into the log every two seconds. */
void sound_attach(void *direct_sound);
void sound_frame(void);
void sound_summary(void);
/* The song's music as it plays (the music lock): how far it is in ms and the frame it started at; 0 when none plays. */
int sound_music_position(double *ms, long *started_frame);
/* Windows' shared sound engine at the shortest period the game's output offers, while the game runs (engine.c): after
 * the game's DirectSound object opened its device (`chosen`: the launcher's device's 16 GUID bytes; NULL: Windows'
 * default output), once a process, on a thread of its own; the log and openDMT3-sound.txt beside the DLL say what it
 * found. Nothing is asked when the launcher's Low latency is off. */
void engine_start(const uint8_t *chosen);
/* One line of the launcher's note of the run's sound (openDMT3-sound.txt beside the DLL: the mixer's, then the engine's
 * period's): `first` starts the note again, the others are added to it. */
void sound_note(const char *line, int first);
/* The launcher's Mixer through OpenAL Soft (openal.c): DSOAL's DirectSound object on `device` (NULL: Windows' default
 * output), in WASAPI's exclusive mode or its shared one; NULL when any step fails (the log says which, *failed names it
 * for the launcher's note and *hr holds its error), and the caller then opens Windows' own DirectSound. */
void *openal_create(const GUID *device, int exclusive, const char **failed, unsigned long *hr);
/* Frames presented since the game started (the game's own timers count them). */
long ingame_frame(void);

/* The game's window is known (from its Direct3D device): the layer takes its mouse and keys. */
void layer_attach(HWND game);
/* True while the menu or the question is up (the keyboard hook asks: the game then sees no key). */
int layer_holds_input(void);
/* The game's window, once the layer has it (NULL before). */
HWND layer_window(void);
/* The frame rate for the chip (OPENDMT3_FPS=on, the menu's Show FPS), twice a second from the device's present: the
 * chip shows it and the frame's mean length (the chain's own time is the log's, never the screen's). */
void layer_fps(double fps);
/* The game's first screen is showing (the chain saw a frame with something on it): the chip and the mark may show
 * from now on, and the bar shows by itself for a few seconds so the player sees where it is. */
void layer_first_screen(void);
/* The safety net stepped the chain down to this choice (aa_changed: the anti-aliasing was the step): a toast on the
 * game's screen for a few seconds, the log, and a line for the launcher in openDMT3-picture.txt beside the DLL. */
void layer_stepped_down(int upscale, int aa, int aa_changed);
/* The game's window got a press of the mouse's button (input latency, measured with OPENDMT3_LATENCY_WATCH). */
void ingame_press(void);
/* A toast with these words, hanging from the game's top edge for a few seconds. */
void layer_toast(const char *words);

/* The kinds of the layer's parts, for their costs and for the glass: the frame rate chip (its glass still, no live
 * blur under it), the glass panels over a live blur of the game (the bar, its chips, the menu or the question, the
 * toast), and the mark at the top centre (no glass). The chip and the mark are no panels: frames with them are judged
 * by the safety net, and they need no live blur. */
enum { PART_FPS, PART_BAR, PART_BAR_CHIPS, PART_PANEL, PART_TOAST, PART_MARK, PART_KINDS };
/* Whether a kind is a glass panel over a live blur. */
#define PART_IS_PANEL(kind) ((kind) != PART_FPS && (kind) != PART_MARK)
/* One part of the layer to draw this frame: its pictures (look.h), which change version whenever they are drawn
 * again (they are uploaded again then), where its sprite's top left goes on the target, its opacity now and its
 * kind. */
typedef struct {
    const Sprite *sprite;
    unsigned version;
    int x, y;
    float alpha;
    int kind;
    /* The mask's own version when it changes apart from the picture (the chip's glass is drawn once for a size, its
     * words twice a second): its mask is uploaded again only then. 0: with the picture. */
    unsigned mask_version;
    /* From layer_warm_parts only: the largest its pictures get at this size, in pixels (the panel's the question with
     * its line and the menu, the toast's the widest note; 0: as they are now). Its textures are made that large once,
     * so none is made while the game plays. */
    int room_w, room_h;
} LayerPart;
/* The layer's costs by kind of part since they were last read (post_layer_costs): the frames each kind was drawn in
 * and the CPU ticks of its uploads and draw calls there; its pictures uploaded again and their ticks; with the
 * diagnostic switch OPENDMT3_LAYER_TIMING=on (`timing`), its GPU time read four frames late, and the blur passes'. */
typedef struct {
    long frames[PART_KINDS];
    long long cpu[PART_KINDS];
    long uploads[PART_KINDS];
    long long upload_ticks[PART_KINDS];
    long gpu_n[PART_KINDS];
    double gpu_us[PART_KINDS];
    /* Measuring alone (OPENDMT3_LAYER_TIMING=sync), every other frame each part is drawn nine times over (eight copies
     * too faint to change a pixel): what nine cost against one is what one more draw adds, without the cost of making
     * the device idle around it. */
    long gpu9_n[PART_KINDS];
    double gpu9_us[PART_KINDS];
    /* Measuring alone: making the device idle with nothing to wait for, which "one draw alone" pays too (what a draw
     * alone costs past it is the part's whole cost a frame, its state changes and first draw included). */
    long idle_n;
    double idle_us;
    /* OPENDMT3_LAYER_TIMING=frame (measuring only): the chain's and the layer's whole work in a frame, the device made
     * idle before it and after it (nothing between): a phase with a part shown against one with none tells the part's
     * whole cost a frame as it is drawn. */
    long frame_n;
    double frame_us;
    long blur_passes;
    /* The glass parts composed into their own textures (post.c compose_part): a new blurred frame, picture or place. */
    long composed;
    long blur_gpu_n, blur_gpu9_n;
    double blur_gpu_us, blur_gpu9_us;
    int timing;
} LayerCosts;
/* Hand over the costs counted since the last call and start counting again (post.c). */
void post_layer_costs(LayerCosts *out);
/* The most parts in a frame (the chip, the mark, the bar and its chips, a panel, the toast), and the layer's sprites,
 * each with its own textures. */
#define LAYER_PARTS 6
/* The parts to draw this frame on a target of w x h pixels (the window's client area as the chain draws it, or the
 * game's own back buffer without the chain), in the order they are drawn; how many. Their motion (slides and fades)
 * is worked out here, once a frame. */
int layer_parts(LayerPart *out, int max, int w, int h);
/* Every picture the layer has, with the room each may take, at an opacity too small to show: post.c makes their
 * textures and draws them once when the layer first draws at a size, ahead of need. */
int layer_warm_parts(LayerPart *out, int max, int w, int h);
/* The CPU time the layer spent drawing its pictures again since the last call, by kind: how many times, the ticks in
 * all and the longest; and how many times GDI drew words for the chip's updates (none once its pieces are made). The
 * counts start again from zero after each call. */
void layer_redraws(long count[PART_KINDS], long long ticks[PART_KINDS], long long longest[PART_KINDS], long *chip_gdi);
/* Whether the game is to be held still now: the menu or the question is open while a song plays. */
int layer_hold_wanted(void);
/* While the game is held: every waiting message handled (the game's own window procedure is left out, its timers
 * wait); 0 when the hold must end at once (quitting, or the program's quit message, which is posted again). */
int layer_pump(void);
/* The game held still (1) or going on again (0): the layer's window procedure then keeps every message from the
 * game's own. */
void layer_holding(int on);
/* The player chose Quit the game. */
int layer_quitting(void);
/* The game is held still now (its frame does not change). */
int layer_is_holding(void);

/* The layer's drawing without the chain (post.c): its parts into the game's own back buffer, with no glass blur. */
void post_layer_without_chain(struct IDirect3DDevice9 *dev);
/* Its objects released before the game's reset (the fallback's state block). */
void post_layer_before_reset(void);

/* Holding the game's sound still (sound.c): the buffers playing now faded out and stopped where they were; then
 * played again from there with a fade in (play 0: only let go, as when quitting). Whether a song's music plays. */
void sound_hold(void);
/* One frame of the hold's fade out (from each held frame's present): the buffers stopped at its end. */
void sound_hold_step(void);
void sound_resume(int play);
int sound_song_playing(void);

/* The keyboard hook's state between calls: the answer's keys still down after the card closed. */
extern int g_keys_waiting;

#endif
