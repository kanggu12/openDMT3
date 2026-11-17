/*
 * The in-game layer's decisions (logic.h): no Windows calls here, so the native tests check each one.
 */
#include "logic.h"
#include "postmath.h"

#include <ctype.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Windows' virtual-key numbers the layer reads (winuser.h), written out so this file needs no Windows header. */
#define K_LBUTTON 0x01
#define K_RBUTTON 0x02
#define K_TAB 0x09
#define K_RETURN 0x0D
#define K_ESCAPE 0x1B
#define K_SPACE 0x20
#define K_LEFT 0x25
#define K_UP 0x26
#define K_RIGHT 0x27
#define K_DOWN 0x28

/* The corners' names, in the order of CORNER_* (the launcher's words for them, values.py FPS_POSITIONS). */
static const char *const CORNER_NAMES[4] = {"top_left", "top_right", "bottom_left", "bottom_right"};

void settings_default(Settings *s)
{
    memset(s, 0, sizeof *s);
    /* Our pointer is on unless the launcher says the game hides it (a touch screen). */
    s->cursor = 1;
    /* The chip's corner: the one that covers none of the game's own labels on any of its screens (logic.h). */
    s->fps_corner = CORNER_BOTTOM_RIGHT;
    /* The picture's defaults, as the launcher's (values.py): the ones that looked best on this game's frames. */
    s->upscale = UPSCALE_DEFAULT;
    s->sharpness = SHARPNESS_DEFAULT;
    s->antialiasing = AA_DEFAULT;
    /* The sound engine's shortest period is asked for unless the launcher says not to (engine.c). */
    s->low_latency = 1;
}

/* Text equal to `word`, whatever its case. */
static int same(const char *a, const char *word)
{
    for (; *a && *word; a++, word++)
        if (tolower((unsigned char)*a) != tolower((unsigned char)*word))
            return 0;
    return *a == *word;
}

const char *const SETTINGS_NAMES[] = {"OPENDMT3_LANGUAGE", "OPENDMT3_CURSOR", "OPENDMT3_PACING", "OPENDMT3_FPS",
                                      "OPENDMT3_FPS_POSITION", "OPENDMT3_SOUND_DEVICE", "OPENDMT3_UPSCALE",
                                      "OPENDMT3_SHARPNESS", "OPENDMT3_ANTIALIASING", "OPENDMT3_PICTURE_SHAPE",
                                      "OPENDMT3_PASS_TIMES", "OPENDMT3_LOW_LATENCY", "OPENDMT3_SOUND_PATH",
                                      "OPENDMT3_RENDER", "OPENDMT3_AUDIO_OFFSET", "OPENDMT3_MOTION_CLARITY",
                                      "OPENDMT3_FLIP_MODEL",
                                      /* The sound's values, read by soundset.c itself (settings_read passes them). */
                                      "OPENDMT3_SOUND_VALUES"};

/* The sound paths' names, in the order of SOUND_PATH_* (the launcher's words for them, values.py SOUND_PATHS). */
const char *const SOUND_PATH_NAMES[SOUND_PATHS] = {"directsound", "openal", "openal-exclusive"};
const int SETTINGS_COUNT = sizeof SETTINGS_NAMES / sizeof SETTINGS_NAMES[0];

void settings_read(Settings *s, const char *name, const char *value)
{
    if (!name || !value)
        return;
    if (!strcmp(name, "OPENDMT3_LANGUAGE")) {
        /* Korean only when asked for; anything else is the launcher's first language, English. */
        s->korean = same(value, "ko");
    } else if (!strcmp(name, "OPENDMT3_CURSOR")) {
        /* "off": the launcher's touch-screen choice; the game's own pointer rules stay. */
        s->cursor = !same(value, "off");
    } else if (!strcmp(name, "OPENDMT3_PACING")) {
        /* "even": openDMT3's clock; "music": that clock led by a song's music while one plays; anything else the
         * client's own steps. */
        s->music_lock = same(value, "music");
        s->even_pacing = s->music_lock || same(value, "even");
    } else if (!strcmp(name, "OPENDMT3_FPS")) {
        s->show_fps = same(value, "on");
    } else if (!strcmp(name, "OPENDMT3_FPS_POSITION")) {
        /* A known corner's name; anything else leaves the default. */
        int c = corner_from_name(value);
        if (c >= 0)
            s->fps_corner = c;
    } else if (!strcmp(name, "OPENDMT3_UPSCALE")) {
        /* A known filter's name; anything else leaves the default. */
        int u = upscale_from_name(value);
        if (u >= 0)
            s->upscale = u;
    } else if (!strcmp(name, "OPENDMT3_ANTIALIASING")) {
        int a = aa_from_name(value);
        if (a >= 0)
            s->antialiasing = a;
    } else if (!strcmp(name, "OPENDMT3_SHARPNESS")) {
        /* Whole numbers 0 to 100 only; anything else leaves the default. */
        char *end = NULL;
        long v = strtol(value, &end, 10);
        if (end && end != value && !*end && v >= 0 && v <= 100)
            s->sharpness = (int)v;
    } else if (!strcmp(name, "OPENDMT3_PICTURE_SHAPE")) {
        /* "fill" stretches; anything else keeps the game's shape (the default). */
        s->fill = same(value, "fill");
    } else if (!strcmp(name, "OPENDMT3_AUDIO_OFFSET")) {
        /* Whole milliseconds 0 to AUDIO_OFFSET_MAX only; anything else leaves the default (none). */
        char *end = NULL;
        long v = strtol(value, &end, 10);
        if (end && end != value && !*end && v >= 0 && v <= AUDIO_OFFSET_MAX)
            s->audio_offset = (int)v;
    } else if (!strcmp(name, "OPENDMT3_MOTION_CLARITY")) {
        /* "crt" the rolling beam, "bfi" black frames; anything else leaves it off (the default). */
        s->motion = same(value, "crt") ? MOTION_CRT : same(value, "bfi") ? MOTION_BFI : MOTION_OFF;
    } else if (!strcmp(name, "OPENDMT3_FLIP_MODEL")) {
        /* "on" asks for the flip model; anything else leaves the copy model (the default). */
        s->flip = same(value, "on");
    } else if (!strcmp(name, "OPENDMT3_PASS_TIMES")) {
        /* "on" measures the picture's GPU time by pass; anything else leaves it off (the default). */
        s->pass_times = same(value, "on");
    } else if (!strcmp(name, "OPENDMT3_RENDER")) {
        /* "display" draws the game at the picture's size in the window; anything else at its own (the default). */
        s->render_display = same(value, "display");
    } else if (!strcmp(name, "OPENDMT3_SOUND_DEVICE")) {
        /* A GUID: that device; empty or not a GUID: Windows' default output. */
        s->has_device = parse_guid(value, s->device);
    } else if (!strcmp(name, "OPENDMT3_LOW_LATENCY")) {
        /* "off" leaves Windows' sound engine at its own period; anything else keeps the default, on. */
        s->low_latency = !same(value, "off");
    } else if (!strcmp(name, "OPENDMT3_SOUND_PATH")) {
        /* A known path's name; anything else leaves Windows' own DirectSound (the default). */
        for (int i = 0; i < SOUND_PATHS; i++)
            if (same(value, SOUND_PATH_NAMES[i]))
                s->sound_path = i;
    }
}

int corner_from_name(const char *name)
{
    if (!name)
        return -1;
    /* The launcher's four names, in any case. */
    for (int i = 0; i < 4; i++)
        if (same(name, CORNER_NAMES[i]))
            return i;
    return -1;
}

/* One hexadecimal digit's value, or -1. */
static int hex(int c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    c = tolower(c);
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    return -1;
}

int parse_guid(const char *text, uint8_t out[16])
{
    if (!text)
        return 0;
    size_t n = strlen(text);
    /* The braces are optional; without them the text is 36 characters. */
    if (n == 38 && text[0] == '{' && text[37] == '}') {
        text++;
        n = 36;
    }
    if (n != 36)
        return 0;
    /* 32 digits in groups of 8-4-4-4-12, hyphens between the groups. */
    uint8_t raw[16];
    int digits = 0;
    for (size_t i = 0; i < 36; i++) {
        if (i == 8 || i == 13 || i == 18 || i == 23) {
            if (text[i] != '-')
                return 0;
            continue;
        }
        int v = hex((unsigned char)text[i]);
        if (v < 0)
            return 0;
        /* Two digits a byte, the first one the high half. */
        if (digits % 2 == 0)
            raw[digits / 2] = (uint8_t)(v << 4);
        else
            raw[digits / 2] |= (uint8_t)v;
        digits++;
    }
    /* The text writes Data1 (4 bytes), Data2 and Data3 (2 each) high byte first; the structure keeps them low byte
     * first. Data4 (8 bytes) stays in order. */
    out[0] = raw[3];
    out[1] = raw[2];
    out[2] = raw[1];
    out[3] = raw[0];
    out[4] = raw[5];
    out[5] = raw[4];
    out[6] = raw[7];
    out[7] = raw[6];
    memcpy(out + 8, raw + 8, 8);
    return 1;
}

void format_guid(const uint8_t in[16], char out[39])
{
    /* The reverse of parse_guid: Data1-3 read low byte first. */
    snprintf(out, 39, "{%02X%02X%02X%02X-%02X%02X-%02X%02X-%02X%02X-%02X%02X%02X%02X%02X%02X}", in[3], in[2], in[1],
             in[0], in[5], in[4], in[7], in[6], in[8], in[9], in[10], in[11], in[12], in[13], in[14], in[15]);
}

void pacer_start(Pacer *p, int64_t frequency, int fps)
{
    /* No limit (or no clock): a period of 0 never waits. */
    p->period = fps > 0 && frequency > 0 ? frequency / fps : 0;
    p->next = 0;
}

int64_t pacer_wait(Pacer *p, int64_t now)
{
    if (p->period <= 0)
        return 0;
    /* The first frame goes at once and starts the count. */
    if (p->next == 0) {
        p->next = now + p->period;
        return 0;
    }
    int64_t wait = p->next - now;
    if (wait > 0) {
        /* Early: wait for its time, and the next one is a period after it (even spacing, no drift). */
        p->next += p->period;
        return wait;
    }
    if (-wait > p->period) {
        /* More than a frame late (a load, a stall): start again from now instead of hurrying to catch up. */
        p->next = now + p->period;
    } else {
        /* A little late: on at once, the count kept so the average stays at the limit. */
        p->next += p->period;
    }
    return 0;
}

void music_lock_start(MusicLock *m)
{
    m->smooth = 0;
    m->primed = 0;
}

int64_t music_lock_step(MusicLock *m, double ahead_ms, int64_t period)
{
    /* The first reading as it is; then a tenth of each new one (the cursor's steps average out). */
    m->smooth = m->primed ? m->smooth * 0.9 + ahead_ms * 0.1 : ahead_ms;
    m->primed = 1;
    double e = m->smooth;
    /* Within 1 ms: nothing to correct (less than the cursor's own steps). */
    if (e > -1.0 && e < 1.0)
        return 0;
    /* A twentieth of the distance a frame: a drift goes in about a second, with no step a player sees. */
    double ms = e * 0.05;
    /* Small drifts at most 1 ms a frame; a stall's distance (over 50 ms) at most 4 ms a frame (a quarter of a frame). */
    double most = (e > 50.0 || e < -50.0) ? 4.0 : 1.0;
    if (ms > most)
        ms = most;
    if (ms < -most)
        ms = -most;
    /* Milliseconds to the counter's ticks (a period is 1000/60 ms). */
    return (int64_t)(ms * (double)period * 60.0 / 1000.0);
}

double music_lock_most(const MusicLock *m)
{
    /* The same bounds as music_lock_step's: a stall's distance (over 50 ms, or not read yet) 4 ms, a drift 1 ms. */
    if (!m->primed || m->smooth > 50.0 || m->smooth < -50.0)
        return 4.0;
    return 1.0;
}

void song_lock_start(SongLock *s)
{
    /* No song locked yet, nothing read. */
    s->song = -1;
    s->base = 0;
    s->fresh = 1;
    s->playing = 0;
    music_lock_start(&s->lock);
}

void song_lock_pause(SongLock *s)
{
    /* The readings from before (a reset's stall, a gap) say nothing of the next one: started again then. The song and
     * its start stay, so the same song goes on from its own start. */
    s->fresh = 1;
    s->playing = 0;
}

int64_t song_lock_frame(SongLock *s, long started, double ahead, int offset, int64_t period, int *began, double *off)
{
    *began = 0;
    if (started != s->song) {
        /* A new song: its first distance is how the game itself started the music against its frames; kept for it. */
        s->song = started;
        s->base = ahead;
        s->fresh = 1;
        *began = 1;
    }
    /* The first frame of a song, or the first after a reset or a gap: the readings start again (the song's start
     * kept). */
    if (s->fresh) {
        music_lock_start(&s->lock);
        s->fresh = 0;
    }
    s->playing = 1;
    /* The audio offset: the frames held that much further behind the music than the game's own start put them. The lock
     * reaches it as it wins back any distance (1 ms a frame, 4 ms while over 50 ms away). */
    *off = ahead - s->base - offset;
    return music_lock_step(&s->lock, *off, period);
}

int64_t display_lock_step(double phase, int64_t refresh_ticks)
{
    if (phase < 0 || refresh_ticks <= 0)
        return 0;
    /* How far from the middle of its refresh the tick fell (-0.5 to 0.5 of a refresh). */
    double off = phase - 0.5;
    /* Near the middle: left as it is (the counter and the display drift apart slowly). */
    if (off > -0.125 && off < 0.125)
        return 0;
    /* A sixteenth of the distance, at most a 64th of a refresh a frame (under 0.07 ms at 240 Hz): late in the refresh
     * moves the next tick earlier, early moves it later. */
    double move = off / 16.0;
    if (move > 1.0 / 64.0)
        move = 1.0 / 64.0;
    if (move < -1.0 / 64.0)
        move = -1.0 / 64.0;
    return (int64_t)(-move * (double)refresh_ticks);
}

int catchup_display(int vsync, int hz)
{
    /* VSync on and a known refresh under CATCHUP_HZ: its refreshes are at most a millisecond a frame shorter than a
     * frame (1000/64 = 15.6 ms), so frames sooner than that never show. VSync off, or no rate known: frames go out as
     * the lock's ticks say. */
    return vsync && hz > 0 && hz < CATCHUP_HZ;
}

void catchup_start(CatchUp *c)
{
    memset(c, 0, sizeof *c);
}

/* The median of the readings kept (CATCHUP_READINGS of them, odd: the middle one in order). */
static double catchup_median(const CatchUp *c)
{
    double v[CATCHUP_READINGS];
    memcpy(v, c->read, sizeof v);
    /* Insertion sort: five numbers. */
    for (int i = 1; i < CATCHUP_READINGS; i++) {
        double x = v[i];
        int k = i - 1;
        for (; k >= 0 && v[k] > x; k--)
            v[k + 1] = v[k];
        v[k + 1] = x;
    }
    return v[CATCHUP_READINGS / 2];
}

int catchup_frame(CatchUp *c, double behind_ms, int may)
{
    /* The frame shown is the catch-up's too while one runs. */
    if (c->running)
        c->frames++;
    /* After a frame too late: the rest counts down with each frame shown. */
    if (c->rest > 0)
        c->rest--;
    /* The reading kept, the oldest out once the window is full. */
    c->read[c->at] = behind_ms;
    c->at = (c->at + 1) % CATCHUP_READINGS;
    if (c->n < CATCHUP_READINGS)
        c->n++;
    /* A window's worth since the last frame left unshown (or tried), or no decision yet: that spaces the skips. */
    if (c->n < CATCHUP_READINGS)
        return 0;
    double behind = catchup_median(c);
    const double frame = 1000.0 / GAME_FPS;
    if (behind <= frame) {
        /* Within a frame: nothing to win back by a whole frame (and a catch-up running is over). */
        if (c->running) {
            c->running = 0;
            c->to_ms = behind;
            c->done = 1;
        }
        return 0;
    }
    /* More than a frame behind, but not now: a panel up, the display or its refresh not known, a rest after a frame
     * too late, or too many of those this song. The readings go on. */
    if (!may || c->rest > 0 || c->late_song >= CATCHUP_LATE)
        return 0;
    if (!c->running) {
        /* A catch-up begins: its numbers from here. */
        c->running = 1;
        c->skips = c->late = c->unfit = 0;
        c->frames = 0;
        c->from_ms = behind;
    }
    c->to_ms = behind;
    return 1;
}

int64_t catchup_deadline(int64_t now, int64_t tick, int64_t refresh, double phase)
{
    /* The skipped frame would have gone out at its tick, or now when it came after it. */
    int64_t at = tick > now ? tick : now;
    if (refresh <= 0)
        return at;
    /* No phase read: the display lock keeps the tick within an eighth of the middle of its refresh, so the next
     * refresh begins three eighths of one after it at the earliest. */
    if (phase < 0)
        return at + refresh * 3 / 8;
    /* The display's phase then: now's and the time to it (as the display lock reads the tick's), within its refresh. */
    double then = phase + (double)(at - now) / (double)refresh;
    then -= floor(then);
    /* The rest of that refresh's visible lines: where its blank, the next refresh's turn, begins. */
    return at + (int64_t)((1.0 - then) * CATCHUP_VISIBLE * (double)refresh);
}

int64_t catchup_work(int64_t cpu, int64_t chain)
{
    /* The processor's part, then the chain's on the GPU after it (none counted when not timed, or a reading below 0). */
    return (cpu > 0 ? cpu : 0) + (chain > 0 ? chain : 0);
}

int catchup_fits(int64_t now, int64_t tick, int64_t deadline, int64_t work, int64_t refresh)
{
    /* No refresh known: no place in it to make sure of. */
    if (refresh <= 0)
        return 0;
    /* The next frame goes out when its work from now is done, its picture's on the GPU too, and not before the tick it
     * takes over. */
    int64_t out = now + (work > 0 ? work : 0);
    if (out < tick)
        out = tick;
    /* An eighth of a refresh (2 ms at 60 Hz) before that refresh's turn: room for the estimate's own error and the
     * present to be taken. */
    return out <= deadline - refresh / 8;
}

void catchup_pause(CatchUp *c)
{
    /* The readings from before the reset are no reading of after it: a window's worth again before the next decision. */
    c->n = c->at = 0;
}

void catchup_skipped(CatchUp *c)
{
    c->skips++;
    /* The frame left unshown is a frame of the game's all the same. */
    c->frames++;
    /* The readings from before it are a frame behind what the next will say: read again from the next frame. */
    c->n = c->at = 0;
}

void catchup_unfit(CatchUp *c)
{
    if (c->running)
        c->unfit++;
    /* Read again: the next try a window's worth of frames on, not at once. */
    c->n = c->at = 0;
}

void catchup_after(CatchUp *c, int in_time)
{
    if (in_time)
        return;
    /* The frame after a skip too late: the skip may have won nothing and the frame before shown twice. A rest first,
     * and none in the rest of the song after CATCHUP_LATE of them. */
    c->late++;
    c->late_song++;
    c->rest = CATCHUP_REST;
}

void jit_start(JitClock *j, int64_t frequency, int fps)
{
    memset(j, 0, sizeof *j);
    /* No clock (the client's own steps): no tick to start a frame ahead of. */
    j->period = fps > 0 && frequency > 0 ? frequency / fps : 0;
    j->frequency = frequency;
    /* The least spare from the start: a frame whose work is known gets its millisecond. */
    j->spare = (int64_t)(JIT_SPARE_MS * (double)frequency / 1000.0);
    /* The game's loading first: its frames start at once (their work is measured all the same). */
    j->settle = JIT_SETTLE;
}

void jit_frame(JitClock *j, int64_t work, int in_time, int early)
{
    if (j->period <= 0)
        return;
    /* Kept in the window, the oldest out (a negative reading is the counter's own error: none). */
    j->work[j->at] = work > 0 ? work : 0;
    j->at = (j->at + 1) % JIT_WINDOW;
    if (j->kept < JIT_WINDOW)
        j->kept++;
    if (j->settle > 0)
        j->settle--;
    /* A rest after a streak of misses counts down with every frame, started at once as they are. */
    if (j->rest > 0)
        j->rest--;
    int64_t least = (int64_t)(JIT_SPARE_MS * (double)j->frequency / 1000.0), most = j->period / 4;
    if (!in_time && early) {
        /* Started late by this clock and not done by its tick. With the spare already at its most, one more of a
         * streak: JIT_STREAK in a row mean the GPU takes longer than any spare covers, and the next JIT_REST frames
         * start at once (held, they would only be late). */
        if (j->spare >= most && ++j->streak >= JIT_STREAK) {
            j->rest = JIT_REST;
            j->streak = 0;
        }
        /* A millisecond more spare, at most a quarter of a frame, and the calm counted again (a frame started at once
         * that misses says nothing of the spare: its lateness is the work's own, which the window holds). */
        j->spare += j->frequency / 1000;
        if (j->spare > most)
            j->spare = most;
        j->calm = 0;
        return;
    }
    if (!early)
        return;
    /* Started late and in time: the streak of misses is over. */
    j->streak = 0;
    /* In time: after five seconds of it in a row, the spare goes back a tenth of a millisecond a frame. */
    if (++j->calm >= JIT_CALM && j->spare > least) {
        j->spare -= j->frequency / 10000;
        if (j->spare < least)
            j->spare = least;
    }
}

int64_t jit_work(const JitClock *j)
{
    if (j->kept <= 0)
        return 0;
    /* The slowest 1 %: the rank'th largest, rank one more than a hundredth of the frames kept (the second of 120). */
    int rank = j->kept / 100 + 1;
    /* The `rank` largest so far, in order (rank is at most 2 here: JIT_WINDOW is under 200). */
    int64_t top[2] = {-1, -1};
    for (int i = 0; i < j->kept; i++) {
        int64_t v = j->work[i];
        if (v > top[0]) {
            top[1] = top[0];
            top[0] = v;
        } else if (v > top[1]) {
            top[1] = v;
        }
    }
    return top[rank > 1 ? 1 : 0] > 0 ? top[rank > 1 ? 1 : 0] : 0;
}

int strobe_refreshes(int hz)
{
    /* The nearest whole multiple of 60, and how far the rate is from it. */
    int n = (hz + 30) / 60, off = hz - n * 60;
    /* From 120 up and within 1 Hz of it (a rate given whole, 239 for 239.76); anything else shows frames whole. */
    return hz > 0 && n >= 2 && off >= -1 && off <= 1 ? n : 0;
}

int refresh_advice(int current, int highest, int signal)
{
    /* Nothing known of what programs are given: nothing to say. */
    if (current <= 0)
        return REFRESH_AS_IS;
    /* The monitor carries more refreshes than programs are given (2 Hz over: 119.88 is given as 119): dynamic. */
    if (signal > current + 1)
        return REFRESH_DYNAMIC;
    /* A faster mode at this size that is not chosen. */
    if (highest > current + 1)
        return REFRESH_SET_LOWER;
    return REFRESH_AS_IS;
}

int refresh_offered(int current, int highest)
{
    /* The highest at this size when it is known (the row is never hidden by a setting of Windows'), else the current. */
    return highest > current ? highest : current;
}

int display_follows(int refreshes_a_frame, long steps, long one_steps)
{
    /* A fixed rate of two or more refreshes a frame, two seconds' worth of single presents to judge, and nine in ten
     * of them a refresh after the one before: the display waits for the frames. */
    return refreshes_a_frame >= 2 && steps >= 60 && one_steps * 10 >= steps * 9;
}

int64_t jit_lead(const JitClock *j, int64_t slack)
{
    /* No clock, the loading, a rest after a streak of misses, or no frame measured yet: the next frame starts at
     * once. */
    if (j->period <= 0 || j->settle > 0 || j->rest > 0 || j->kept <= 0)
        return 0;
    /* Its work, the spare, and what may still move its tick earlier (never less than nothing). */
    return jit_work(j) + j->spare + (slack > 0 ? slack : 0);
}

int guard_frame_shown(Guard *g, double frame_ms, double chain_ms, int presents)
{
    /* Shown over sub-frames: the frame's lateness is the sub-frames' wait, not the chain's; neither judged nor
     * counted. */
    if (presents > 1)
        return 0;
    return guard_frame(g, frame_ms, chain_ms);
}

void guard_start(Guard *g)
{
    g->seen = g->late = g->bad = 0;
    /* The game's first 10 s load its screens, a stall of its own whatever the chain costs: not counted. */
    g->settle = 600;
    g->chain_ms = -1;
}

int guard_frame(Guard *g, double frame_ms, double chain_ms)
{
    /* The chain's time, smoothed over a few frames (one slow reading is not the chain's cost). */
    if (chain_ms >= 0)
        g->chain_ms = g->chain_ms < 0 ? chain_ms : g->chain_ms * 0.75 + chain_ms * 0.25;
    if (g->settle > 0) {
        g->settle--;
        return 0;
    }
    /* With no reading of the chain's time there is nothing to say it is the chain. */
    if (g->chain_ms < 0)
        return 0;
    const double budget = 1000.0 / 60.0 + 1.0;
    /* Late, and in time without the chain: the chain's doing (a load or a stall of the game's own is not). */
    if (frame_ms > budget && frame_ms - g->chain_ms <= budget)
        g->late++;
    if (++g->seen < GUARD_WINDOW)
        return 0;
    /* Two late windows in a row: the chain's cost holds, not a moment's. */
    g->bad = g->late >= GUARD_NEED ? g->bad + 1 : 0;
    int step = g->bad >= 2;
    /* A new window either way; after a step, its readings settle first (the GPU time is read four frames late). */
    g->seen = g->late = 0;
    if (step) {
        g->bad = 0;
        g->settle = 8;
        g->chain_ms = -1;
    }
    return step;
}

int hold_keys(uint8_t keys[256], int card_open, int waiting)
{
    /* The keys and buttons a player answers the layer with. */
    static const unsigned answer[] = {K_LBUTTON, K_RBUTTON, K_TAB,  K_RETURN, K_ESCAPE,
                                      K_SPACE,   K_LEFT,    K_UP,   K_RIGHT,  K_DOWN};
    const int count = (int)(sizeof answer / sizeof answer[0]);
    if (card_open) {
        /* The menu or the question is up: the game sees nothing pressed (it goes on, untouched), and once it
         * closes the answer's keys must be let go before the game sees them again. */
        memset(keys, 0, 256);
        return 1;
    }
    /* Esc never reaches the game: its own Esc ends it at once, with no question (a stray key would end a song), a quit
     * by a key as Alt+F4 would be; only the bar's X quits, after asking. */
    keys[K_ESCAPE] = 0;
    if (!waiting)
        return 0;
    int still = 0;
    for (int i = 0; i < count; i++) {
        /* The high bit of a key's byte says it is down. */
        if (keys[answer[i]] & 0x80) {
            still = 1;
            keys[answer[i]] = 0;
        }
    }
    /* Every one of them up: the game has its keys back. */
    return still;
}

/* The words: the buttons in the game's capitals (it writes its own so: NO ID CARD), Korean as it is written. */
static const char *const MENU_EN[] = {"BACK TO THE GAME", "SHOW FPS", "SOUND", "QUIT THE GAME"};
static const char *const MENU_KO[] = {"게임으로 돌아가기", "FPS 표시", "사운드", "게임 끝내기"};
/* The sound panel's columns: the three volumes, then the bands by their middles. */
static const char *const SOUND_EN[] = {"ALL", "MUSIC", "KEYS", "60", "250", "1K", "4K", "12K"};
static const char *const SOUND_KO[] = {"전체", "음악", "키음", "60", "250", "1K", "4K", "12K"};
static const char *const QUIT_EN[] = {"KEEP PLAYING", "QUIT THE GAME"};
static const char *const QUIT_KO[] = {"계속하기", "게임 끝내기"};

int card_count(const Card *c)
{
    return c->open == CARD_MENU ? 4 : c->open == CARD_QUIT ? 2 : c->open == CARD_SOUND ? 8 : 0;
}

/* The answer that quits: the last one, in both cards. */
static int quit_index(const Card *c)
{
    return card_count(c) - 1;
}

const char *card_label(const Card *c, int i, int *danger)
{
    /* The quitting answer in the menu and the question; nothing in the sound panel quits. */
    if (danger)
        *danger = c->open != CARD_SOUND && i == quit_index(c);
    if (i < 0 || i >= card_count(c))
        return "";
    if (c->open == CARD_SOUND)
        return c->korean ? SOUND_KO[i] : SOUND_EN[i];
    if (c->open == CARD_MENU)
        return c->korean ? MENU_KO[i] : MENU_EN[i];
    return c->korean ? QUIT_KO[i] : QUIT_EN[i];
}

const char *card_state(const Card *c, int i)
{
    /* A sound column's value: a volume in percent, a band's gain signed (0 flat). Room for every column at once. */
    if (c->open == CARD_SOUND && i >= SOUND_EQ0 && i < 8 && (c->sound_off & (1u << (i - SOUND_EQ0))))
        /* A band left off at the sound's rate (12 kHz at 22050 Hz or less): said off, whatever its value. */
        return c->korean ? "끔" : "OFF";
    if (c->open == CARD_SOUND && i >= 0 && i < 8) {
        static char words[8][8];
        snprintf(words[i], sizeof words[i], i < SOUND_EQ0 || !c->sound[i] ? "%d" : "%+d", c->sound[i]);
        return words[i];
    }
    /* Show FPS says what it is now, at its row's right, as a switch does. */
    if (c->open != CARD_MENU || i != 1)
        return NULL;
    return c->fps ? (c->korean ? "켬" : "ON") : (c->korean ? "끔" : "OFF");
}

const char *card_title(const Card *c)
{
    /* The menu is a list under its chip, with no title; the X asks before anything ends. Titles are sentences, as
     * the game's own ("Data authentication failed"). */
    if (c->open == CARD_SOUND)
        return c->korean ? "사운드" : "Sound";
    if (c->open != CARD_QUIT)
        return NULL;
    return c->korean ? "게임을 끝낼까요?" : "Quit the game?";
}

const char *card_line(const Card *c)
{
    /* What quitting loses, plainly: the game sends a play's results when the play ends, so a play cut short (its
     * stages so far and the song in progress) is not kept. Said only while a song plays, where it is true: on the
     * game's menus no play may be going on. */
    if (c->open != CARD_QUIT || !c->song)
        return NULL;
    return c->korean ? "진행 중인 플레이는 기록되지 않습니다." : "A play in progress is not kept.";
}

void card_open(Card *c, int what)
{
    c->open = what;
    /* The first answer goes on with the game: Enter at once never ends a song. */
    c->focus = 0;
}

int sound_step(int which)
{
    return which < SOUND_EQ0 ? 5 : 1;
}

int card_key(Card *c, unsigned vk)
{
    int n = card_count(c);
    if (!n)
        return ACT_NONE;
    if (c->open == CARD_SOUND) {
        /* The panel's columns side by side: Left and Right (and Tab) go along them, Up and Down move the value the
         * ring is on (the layer moves it by sound_step), Enter goes back to the game, Esc too. */
        if (vk == K_UP || vk == K_DOWN) {
            c->step = vk == K_UP ? 1 : -1;
            return ACT_SOUND;
        }
        if (vk == K_RETURN || vk == K_SPACE) {
            c->open = CARD_NONE;
            return ACT_CLOSE;
        }
    }
    if (vk == K_LEFT || vk == K_UP) {
        /* Round the answers, as a list does. */
        c->focus = (c->focus + n - 1) % n;
        return ACT_REDRAW;
    }
    if (vk == K_RIGHT || vk == K_DOWN || vk == K_TAB) {
        c->focus = (c->focus + 1) % n;
        return ACT_REDRAW;
    }
    if (vk == K_RETURN || vk == K_SPACE)
        return card_choose(c, c->focus);
    if (vk == K_ESCAPE) {
        /* Esc closes: back to the game. */
        c->open = CARD_NONE;
        return ACT_CLOSE;
    }
    /* Any other key waits while the card is open. */
    return ACT_NONE;
}

int card_choose(Card *c, int i)
{
    if (i < 0 || i >= card_count(c))
        return ACT_NONE;
    /* A sound column chosen (a click on it): its value is set where it was pressed (the layer), the panel stays. */
    if (c->open == CARD_SOUND)
        return ACT_NONE;
    if (c->open == CARD_MENU && i == 1) {
        /* Show FPS: turned over, the menu stays (its row now says the other state). */
        c->fps = !c->fps;
        return ACT_FPS;
    }
    if (c->open == CARD_MENU && i == 2) {
        /* Sound: the sound panel in the menu's place, its ring on the master volume. */
        c->open = CARD_SOUND;
        c->focus = 0;
        return ACT_SOUND_OPEN;
    }
    if (i == quit_index(c)) {
        /* Quit the game: in the question it is the answer; in the menu the player already went looking for it. */
        c->open = CARD_NONE;
        return ACT_QUIT;
    }
    /* The first answer: back to the game. */
    c->open = CARD_NONE;
    return ACT_CLOSE;
}

float ui_unit(int area_h)
{
    /* The game's own 768 lines to the area's; a window never smaller than the game's picture keeps it at 1 or more. */
    float u = (float)area_h / (float)GAME_H;
    return u < 1.0f ? 1.0f : u;
}

/* The measures, in game pixels (multiplied by the unit). The bar is as tall as the game's own top bar in a song (its
 * band ends at line 69 of 768, measured: SKIP or GUIDE ON, the score, the groove meter's label), so it covers that
 * band whole and no more. Its chips are the launcher's buttons (34 tall, their ends leaning as its buttons' do), 50
 * wide, in the bar's middle: the window's three 6 apart with the X 12 from the right edge, the menu's 16 further left.
 * The question is 300 wide (the game's panels hold 16 pixel lines in 627; this one holds one line and two answers),
 * its right edge under the X's; the menu as wide as the chips' row, from its own chip's left edge to the X's right
 * edge (228), so the notice at the top centre never reaches it. Both hang from the bar's foot, sheets the bar lets
 * down (they slide out from under it: logic.h's slides), and are at most 114 tall, so with their shadows they end above
 * a quarter of the game's height (line 192 of 768) on a screen of any shape: nothing of the layer reaches the middle of
 * the game. The title tab keeps the game's slope: each end leans in 30 pixels over 37. */
#define BAR_H 70.0f
#define CHIP_W 50.0f
#define CHIP_H 34.0f
#define CHIP_GAP 6.0f
#define MENU_GAP 16.0f
#define EDGE 12.0f
#define QUIT_W 300.0f
/* The chips' row from the menu's chip's left edge to the X's right edge: four chips, the window's three 6 apart and the
 * menu's 16 further left. */
#define CHIPS_ROW_W (4 * CHIP_W + 2 * CHIP_GAP + MENU_GAP)
#define TAB_H 28.0f
#define PAD 16.0f
#define ANSWER_H 32.0f
#define ROW_H 22.0f
#define ROW_GAP 2.0f
/* The sound panel: 340 wide (its eight columns' names, MUSIC and KEYS side by side, need the room), its right edge
 * under the X's; under its title tab, eight columns, each a
 * value over a track 42 tall over its name; 112 tall in all, so it ends with its shadow above line 192 as the others
 * do. */
#define SOUND_W 340.0f
#define SOUND_VALUE_H 14.0f
#define SOUND_TRACK_H 42.0f
#define SOUND_NAME_H 14.0f

void ui_layout(const Card *c, int area_w, int area_h, UiLayout *l)
{
    memset(l, 0, sizeof *l);
    float u = ui_unit(area_h), w = (float)area_w;
    l->u = u;
    /* The bar across the whole top; its height the game's own top bar's. */
    l->bar = (Box){0, 0, w, BAR_H * u};
    /* The product's mark at the left, the launcher's picture of it (cut to what it draws) 46 of the bar's 70 lines
     * tall, in its middle: DMT3's capitals then 23 lines, as the mark set at 34 was. */
    l->px_name = 34 * u;
    l->name_h = 46 * u;
    l->name_x = 20 * u;
    l->name_y = BAR_H * u / 2;
    /* The X at the right edge, minimise and full screen left of it, the menu's chip a little apart: all in the bar's
     * middle. */
    float top = (BAR_H - CHIP_H) / 2 * u;
    l->chip[CHIP_X] = (Box){w - (EDGE + CHIP_W) * u, top, CHIP_W * u, CHIP_H * u};
    l->chip[CHIP_FULL] = (Box){l->chip[CHIP_X].x - (CHIP_GAP + CHIP_W) * u, top, CHIP_W * u, CHIP_H * u};
    l->chip[CHIP_MIN] = (Box){l->chip[CHIP_FULL].x - (CHIP_GAP + CHIP_W) * u, top, CHIP_W * u, CHIP_H * u};
    l->chip[CHIP_MENU] = (Box){l->chip[CHIP_MIN].x - (MENU_GAP + CHIP_W) * u, top, CHIP_W * u, CHIP_H * u};
    /* Type sizes: the title as the game's tab writes (1.2 times its lines), the line as its messages, the answers as its
     * buttons. */
    l->px_title = 17 * u;
    l->px_line = 15 * u;
    l->px_button = 13 * u;
    /* The sound panel's values and names, as the game's small labels. */
    l->px_small = 11 * u;
    l->count = card_count(c);
    if (c->open == CARD_QUIT) {
        /* The question under the X, its right edge on the X's, its top on the bar's foot. */
        float pw = QUIT_W * u;
        l->panel = (Box){l->chip[CHIP_X].x + l->chip[CHIP_X].w - pw, BAR_H * u, pw, 0};
        /* The tab hangs from the panel's top edge across most of it, narrowing down with the game's slope. */
        l->tab = (Box){l->panel.x + 28 * u, l->panel.y, pw - 56 * u, TAB_H * u};
        /* The one line under the tab while a song plays; with none, the answers come up into its place. */
        float below = card_line(c) ? 36.0f : 12.0f;
        l->line_y = card_line(c) ? l->panel.y + (TAB_H + 19) * u : 0.0f;
        /* The two answers side by side, Keep playing first (left), as the keys go. */
        float aw = (QUIT_W - 2 * PAD - 10) / 2 * u, ay = l->panel.y + (TAB_H + below) * u;
        for (int i = 0; i < l->count && i < 2; i++)
            l->rows[i] = (Box){l->panel.x + PAD * u + (float)i * (aw + 10 * u), ay, aw, ANSWER_H * u};
        l->panel.h = (TAB_H + below + ANSWER_H + 10) * u;
    } else if (c->open == CARD_MENU) {
        /* The menu under its chip and the chips beside it: from the chip's left edge to the X's right edge, its top on
         * the bar's foot, its rows one under the other. */
        float pw = CHIPS_ROW_W * u;
        l->panel = (Box){l->chip[CHIP_MENU].x, BAR_H * u, pw, 0};
        for (int i = 0; i < l->count && i < 8; i++)
            l->rows[i] = (Box){l->panel.x + 8 * u, l->panel.y + (8 + (float)i * (ROW_H + ROW_GAP)) * u, pw - 16 * u,
                               ROW_H * u};
        l->panel.h = (16 + (float)l->count * ROW_H + (float)(l->count - 1) * ROW_GAP) * u;
    } else if (c->open == CARD_SOUND) {
        /* Under the X as the question, its title tab hanging from its top, its eight columns side by side. */
        float pw = SOUND_W * u;
        l->panel = (Box){l->chip[CHIP_X].x + l->chip[CHIP_X].w - pw, BAR_H * u, pw, 0};
        l->tab = (Box){l->panel.x + 28 * u, l->panel.y, pw - 56 * u, TAB_H * u};
        float cw = (SOUND_W - 2 * PAD) / 8 * u, top = l->panel.y + (TAB_H + 6) * u;
        for (int i = 0; i < 8; i++) {
            /* A column: its value, its track (a little narrower than the column, so a finger finds its middle), its
             * name; the whole column takes a press. */
            float x = l->panel.x + PAD * u + (float)i * cw;
            l->rows[i] = (Box){x, top, cw, (SOUND_VALUE_H + SOUND_TRACK_H + SOUND_NAME_H) * u};
            l->track[i] = (Box){x + cw / 2 - 5 * u, top + SOUND_VALUE_H * u, 10 * u, SOUND_TRACK_H * u};
        }
        l->panel.h = (TAB_H + 6 + SOUND_VALUE_H + SOUND_TRACK_H + SOUND_NAME_H + 8) * u;
    }
}

/* A sound value's range: a volume 0 to 100, a band -12 to 12. */
static void sound_range(int i, int *low, int *high)
{
    *low = i < SOUND_EQ0 ? 0 : -EQ_MAX_DB;
    *high = i < SOUND_EQ0 ? 100 : EQ_MAX_DB;
}

int ui_sound_value_at(const UiLayout *l, int i, float y)
{
    if (i < 0 || i >= 8 || l->track[i].h <= 0)
        return 0;
    int low, high;
    sound_range(i, &low, &high);
    /* The track's top the highest, its foot the lowest; beyond either end, that end. */
    float t = (l->track[i].y + l->track[i].h - y) / l->track[i].h;
    t = t < 0 ? 0 : t > 1 ? 1 : t;
    int v = (int)lroundf((float)low + t * (float)(high - low));
    /* A volume in whole steps of its own (5 %), so a finger lands on the values the keys reach. */
    if (i < SOUND_EQ0)
        v = (v + 2) / 5 * 5;
    return v;
}

float ui_sound_y(const UiLayout *l, int i, int value)
{
    int low, high;
    sound_range(i, &low, &high);
    float t = (float)(value - low) / (float)(high - low);
    return l->track[i].y + l->track[i].h * (1.0f - t);
}

/* Inside a box. */
static int inside(const Box *b, float x, float y)
{
    return x >= b->x && x < b->x + b->w && y >= b->y && y < b->y + b->h;
}

int ui_hit(const UiLayout *l, float x, float y)
{
    /* The answers first (they are inside the panel), then the panel, then the chips, then the rest of the bar. */
    for (int i = 0; i < l->count && i < 8; i++)
        if (inside(&l->rows[i], x, y))
            return i;
    if (l->panel.w > 0 && inside(&l->panel, x, y))
        return HIT_PANEL;
    /* A chip is easier to hit with a little room round it (half the gap between the window's chips). */
    static const int hits[CHIPS] = {HIT_MENU, HIT_MIN, HIT_FULL, HIT_X};
    for (int i = 0; i < CHIPS; i++) {
        Box b = l->chip[i];
        float r = CHIP_GAP / 2 * l->u;
        Box near = {b.x - r, b.y - r, b.w + 2 * r, b.h + 2 * r};
        if (inside(&near, x, y))
            return hits[i];
    }
    if (inside(&l->bar, x, y))
        return HIT_BAR;
    return HIT_NONE;
}

int ui_hit_chip(int hit)
{
    /* The chips' hits back to their places in the bar. */
    return hit == HIT_MENU ? CHIP_MENU : hit == HIT_MIN ? CHIP_MIN : hit == HIT_FULL ? CHIP_FULL : hit == HIT_X ? CHIP_X : -1;
}

int ui_at_top_edge(float y, int area_h)
{
    /* The top two lines of a 768-line game (3 at 1080 lines): where a mouse stops against the screen's edge, above
     * every control of the game's (its top bar's buttons start 8 lines down). */
    return y <= 2.0f * ui_unit(area_h);
}

int ui_swipe_down(float start_y, float y, int area_h)
{
    float u = ui_unit(area_h);
    /* Begun within the top 4 lines (a finger cannot land on the very edge) and drawn down 24 lines or more. */
    return start_y <= 4.0f * u && y - start_y >= 24.0f * u;
}

/* The mark, the bar's handle (OpenDMTQ's word for its own): a rail along the top edge 72 game pixels wide, and a tab
 * hanging from its middle, 32 wide at its top and leaning in with the game's tab slope, 9 deep (12 with the pointer on
 * it). The game's top centre holds the groove meter in a song, whose chrome rim takes its top 12 lines and its gauge
 * the lines from 14 down (measured on its screens): the handle stays on the rim, never over the gauge. */
#define MARK_W 72.0f
#define MARK_H 9.0f
#define MARK_LIT_H 12.0f
#define MARK_NEAR 10.0f

Box ui_mark_box(int area_w, int area_h, int lit)
{
    float u = ui_unit(area_h);
    Box b;
    /* In the middle of the top edge: the rail's width, the tab's depth. */
    b.w = MARK_W * u;
    b.h = (lit ? MARK_LIT_H : MARK_H) * u;
    b.x = ((float)area_w - b.w) / 2;
    b.y = 0;
    return b;
}

int ui_on_mark(float x, float y, int area_w, int area_h)
{
    float u = ui_unit(area_h);
    /* The lit mark's box with room round it: a pointer resting near enough is on it (it is small to aim at). */
    Box b = ui_mark_box(area_w, area_h, 1);
    float r = MARK_NEAR * u;
    Box near = {b.x - r, b.y - r, b.w + 2 * r, b.h + 2 * r};
    return inside(&near, x, y);
}

void gate_start(RevealGate *g)
{
    /* No press yet: the game has been quiet for as long as can be. */
    g->pressed_at = -1e12;
    g->down = 0;
    g->armed = 0;
    g->rest_at = 0;
}

void gate_press(RevealGate *g, double now, int down)
{
    /* The game is played: the time of it, whether a button stays down, and no rest from before. */
    g->pressed_at = now;
    g->down = down;
    g->armed = 0;
}

void gate_move(RevealGate *g, double now, int at_place, int button_down)
{
    /* Held down, or away from the edge and the mark: no rest. */
    if (button_down || !at_place) {
        g->armed = 0;
        return;
    }
    /* Come to the place: its rest starts now (a move within the place keeps the rest it has). */
    if (!g->armed) {
        g->armed = 1;
        g->rest_at = now;
    }
}

int gate_due(RevealGate *g, double now, int still_there)
{
    if (!g->armed)
        return 0;
    /* Gone from the place, or a button down on the game: the rest is over. */
    if (!still_there || g->down) {
        g->armed = 0;
        return 0;
    }
    /* Not long enough there yet, or the game played too lately: the rest waits (it may still come). */
    if (now - g->rest_at < REVEAL_REST_MS || now - g->pressed_at < REVEAL_QUIET_MS)
        return 0;
    /* The bar comes; the rest is used up. */
    g->armed = 0;
    return 1;
}

int gate_quiet(const RevealGate *g, double now)
{
    /* Nothing down, and the last press or release long enough ago. */
    return !g->down && now - g->pressed_at >= REVEAL_QUIET_MS;
}

void gate_stall(RevealGate *g, double now, double gap)
{
    /* Where the pause began: what came before it moves on by the pause, what the game heard within it stays. */
    double from = now - gap;
    /* The last press or release before the pause: its quiet counts the game's running time only. */
    if (g->pressed_at < from)
        g->pressed_at += gap;
    /* A rest begun before the pause: it has lasted only while the game ran. */
    if (g->armed && g->rest_at < from)
        g->rest_at += gap;
}

int mark_press_begin(MarkPress *m, double now, int on_mark, int quiet, int song, float y)
{
    /* The overlay's only on the handle, after the game's quiet, and outside a song (there every press is play). */
    m->on = on_mark && quiet && !song;
    /* A new press: nothing brought yet, still on the handle, its time and place for the hold and the draw down. */
    m->fired = 0;
    m->off = 0;
    m->at = now;
    m->y0 = y;
    return m->on;
}

int mark_press_move(MarkPress *m, int on_mark, float y, int area_h)
{
    /* No press of the handle's, or one that brought the bar already. */
    if (!m->on || m->fired)
        return 0;
    /* Drawn down from the handle as far as a swipe from the top edge goes (ui_swipe_down): the bar, even when the
     * finger left the handle's box on its way down (it is small: a draw down soon leaves it). */
    if (y - m->y0 >= 24.0f * ui_unit(area_h)) {
        m->fired = 1;
        return 1;
    }
    /* Off the handle: the player changed their mind; it stays off even when it comes back. */
    if (!on_mark)
        m->off = 1;
    return 0;
}

int mark_press_due(MarkPress *m, double now)
{
    /* Held on the handle long enough, once. */
    if (!m->on || m->fired || m->off || now - m->at < MARK_HOLD_MS)
        return 0;
    m->fired = 1;
    return 1;
}

int mark_press_end(MarkPress *m, int on_mark)
{
    /* A tap: let go on the handle, never off it, before its hold brought the bar. */
    int tap = m->on && !m->fired && !m->off && on_mark;
    /* The press is over: the next one starts again. */
    m->on = 0;
    return tap;
}

void bar_clock_start(BarClock *b)
{
    /* Not shown, never brought. */
    b->since = b->stay = b->reveal_until = 0;
    b->by_touch = 0;
    b->parked = 0;
}

void bar_clock_rest(BarClock *b, double now)
{
    /* A finger's bar keeps its four seconds: the pointer it leaves behind is no mouse on it. */
    if (b->by_touch && now < b->since + b->stay)
        return;
    b->by_touch = 0;
    b->since = now;
    b->stay = BAR_STAY_MS;
}

void bar_clock_touch(BarClock *b, double now)
{
    /* Whole for a finger's time, whatever the pointer it leaves does. */
    b->by_touch = 1;
    b->since = now;
    b->stay = BAR_TOUCH_MS;
}

void bar_clock_reveal(BarClock *b, double now)
{
    /* By itself: whole until then whatever the pointer does (the pointer on it may keep it longer after, once it has
     * moved: where it was when the bar came is no player's doing). */
    b->reveal_until = now + BAR_REVEAL_MS;
    b->parked = 1;
}

void bar_clock_hide(BarClock *b)
{
    /* Its times over: it fades out from now. */
    bar_clock_start(b);
}

void bar_clock_moved(BarClock *b)
{
    /* A real move of the mouse: a finger's bar keeps no longer, and a parked pointer is a pointer again. */
    b->by_touch = 0;
    b->parked = 0;
}

int bar_clock_pointer_counts(const BarClock *b)
{
    /* Neither the pointer a finger leaves nor one that has not moved since the bar came by itself. */
    return !b->by_touch && !b->parked;
}

int bar_clock_whole(const BarClock *b, double now)
{
    /* The later of its stay after the pointer and a showing by itself. */
    double until = b->since + b->stay > b->reveal_until ? b->since + b->stay : b->reveal_until;
    return (b->since > 0 || b->reveal_until > 0) && now < until;
}

Box toast_box(int area_w, int area_h, float text_w)
{
    float u = ui_unit(area_h);
    Box b;
    /* The words with room each side for the tab's slanted ends, 40 tall, hanging from the top edge in the middle as the
     * game's title tab hangs from its panel: inside the game's top band (with the bar down it hangs from the bar's foot,
     * logic.h slide_top). */
    b.w = text_w + 2 * (22 + 40 * 30.0f / 37.0f) * u;
    b.h = 40 * u;
    b.x = ((float)area_w - b.w) / 2;
    b.y = 0;
    /* Clear of the menu, the question and the sound panel, which hang from the bar's foot at its right end (the sound
     * panel the widest, past the chips' row): its right end a menu gap left of them, moved left when the middle would
     * reach further (a narrow screen filled, as 5:4), never past the left edge's room. */
    float panels = QUIT_W > CHIPS_ROW_W ? QUIT_W : CHIPS_ROW_W;
    panels = SOUND_W > panels ? SOUND_W : panels;
    float limit = (float)area_w - (EDGE + panels + MENU_GAP) * u;
    if (b.x + b.w > limit)
        b.x = limit - b.w < EDGE * u ? EDGE * u : limit - b.w;
    return b;
}

/* The chip: one line, 118 x 13 game pixels (the frames a second, FPS and the frame's mean length, three digits and
 * all). The game's notes come right up to the sides, and a note of its third lower row (its centre on line 693 of 768,
 * measured in a song) has the foot of its ring on line 748, the line of the game's own labels at its foot (FREE PLAY's
 * capitals on lines 743 to 752): so at the foot the chip sits on that line, beside the labels, where at most the foot of
 * a note's ring passes (above FREE PLAY half such a note came under it): from line 742, at the right its right end 8
 * game pixels left of FREE PLAY (from x 1131), at the left 8 right of the game's badges (ID CARD, NET and PATCH, to x
 * 193). Those places are the game's own pixels: across, they follow the picture's own width, which a filled picture
 * stretches. At the top it is 6 down and 12 in from its side, in the game's top band, where no note comes. */
#define FPS_W 118.0f
#define FPS_H 13.0f
#define FPS_BAND 742.0f
#define FREE_PLAY_X 1131.0f
#define BADGES_END 193.0f
#define LABEL_GAP 8.0f

Box fps_box(int area_w, int area_h, int corner)
{
    float u = ui_unit(area_h);
    /* The game's own pixels to the area's, across and down (a filled picture stretches the game across). */
    float sx = (float)area_w / (float)GAME_W, sy = (float)area_h / (float)GAME_H;
    Box b;
    b.w = FPS_W * u;
    b.h = FPS_H * u;
    int right = corner == CORNER_TOP_RIGHT || corner == CORNER_BOTTOM_RIGHT;
    int foot = corner == CORNER_BOTTOM_LEFT || corner == CORNER_BOTTOM_RIGHT;
    if (foot) {
        /* In the bottom band, beside the game's labels on their line. */
        b.x = right ? (FREE_PLAY_X - LABEL_GAP) * sx - b.w : (BADGES_END + LABEL_GAP) * sx;
        b.y = FPS_BAND * sy;
    } else {
        /* In the top band, 12 in from its side, 6 down. */
        b.x = right ? (float)area_w - EDGE * u - b.w : EDGE * u;
        b.y = 6 * u;
    }
    return b;
}

void note_words(int korean, int aa_changed, int aa, char *out, int size)
{
    /* One short sentence, as the game says its own; what the picture is now in brackets, in the launcher's words for
     * it (the Screen page's names). "Quality lowered", as the Korean says (화질을 낮췄습니다): "lightened" read as a
     * brighter picture. */
    const char *what;
    if (aa_changed)
        what = aa == AA_FXAA ? "FXAA" : korean ? "안티에일리어싱 끔" : "Anti-aliasing off";
    else
        what = korean ? "부드럽게 확대" : "Smooth upscale";
    snprintf(out, (size_t)size, korean ? "60 FPS를 지키려고 화질을 낮췄습니다(%s)" : "Picture quality lowered to keep 60 FPS (%s)",
             what);
}

/* ------------------------------------------------------------------------------------------ the picture's place */

PicRect picture_rect(int cw, int ch, int fill)
{
    PicRect r = {0, 0, cw, ch};
    if (fill || cw <= 0 || ch <= 0)
        return r;
    if ((long long)cw * GAME_H > (long long)ch * GAME_W) {
        /* Wider than the game: its whole height, bars left and right (the width rounded to a whole pixel). */
        r.w = (int)(((long long)ch * GAME_W + GAME_H / 2) / GAME_H);
        r.x = (cw - r.w) / 2;
    } else if ((long long)cw * GAME_H < (long long)ch * GAME_W) {
        /* Taller: its whole width, bars above and below. */
        r.h = (int)(((long long)cw * GAME_H + GAME_W / 2) / GAME_W);
        r.y = (ch - r.h) / 2;
    }
    return r;
}

void render_size_after_reset(int own, int kept_w, int kept_h, int chosen_w, int chosen_h, int *w, int *h)
{
    /* openDMT3's own reset, with a size from before it: the game's targets live on at that size, so it stays. */
    int keep = own && kept_w > 0 && kept_h > 0;
    *w = keep ? kept_w : chosen_w;
    *h = keep ? kept_h : chosen_h;
}

void render_size_for(int cw, int ch, int fill, int max_w, int max_h, int *w, int *h)
{
    PicRect r = picture_rect(cw, ch, fill);
    /* Past the device's largest texture: the largest of the picture's shape that fits. */
    if (max_w > 0 && max_h > 0 && (r.w > max_w || r.h > max_h)) {
        double k = (double)max_w / r.w, kh = (double)max_h / r.h;
        if (kh < k)
            k = kh;
        r.w = (int)(r.w * k);
        r.h = (int)(r.h * k);
    }
    /* Smaller than the game's own picture either way: its own size (its art is drawn for it). */
    if (r.w < GAME_W || r.h < GAME_H) {
        r.w = GAME_W;
        r.h = GAME_H;
    }
    *w = r.w;
    *h = r.h;
}

long scale_edge(long v, int from, int to)
{
    /* In 64 bits, the half added away from zero before the division. */
    long long n = (long long)v * to;
    return (long)(n >= 0 ? (n + from / 2) / from : -((-n + from / 2) / from));
}

void game_from_client(int qx, int qy, int cw, int ch, int *gx, int *gy)
{
    /* As the helper's imul and idiv do: C's division, towards zero. */
    *gx = cw > 0 ? qx * GAME_W / cw : qx;
    *gy = ch > 0 ? qy * GAME_H / ch : qy;
}

/* One axis: the game pixel whose area holds the centre of picture pixel `p` (the picture `size` wide, starting at
 * `at`, the game `game` pixels across it): floor((p - at + 0.5) * game / size), in whole numbers. */
static long long game_axis(int p, int at, int size, int game)
{
    /* The centre's place times two, so the half pixel stays a whole number. */
    long long num = (long long)(2 * (p - at) + 1) * game, den = 2LL * size;
    /* C's division goes towards zero: a centre left of the picture (a bar) is rounded down all the same. */
    return num >= 0 ? num / den : -((-num + den - 1) / den);
}

void game_pixel_under(int px, int py, PicRect r, int *gx, int *gy)
{
    /* A picture of no size (none placed yet): the point as it is, as pointer_for_game hands it on. */
    *gx = r.w > 0 ? (int)game_axis(px, r.x, r.w, GAME_W) : px;
    *gy = r.h > 0 ? (int)game_axis(py, r.y, r.h, GAME_H) : py;
}

/* One axis: the client coordinate whose helper sum (q * game / client, towards zero) gives the game pixel under the
 * centre of picture pixel `p` (the picture `size` wide, starting at `at`). */
static int pointer_axis(int p, int at, int size, int client, int game)
{
    if (size <= 0 || client <= 0)
        return p;
    /* The game pixel whose area holds the centre (game_axis, the same sum a finger's point takes). */
    long long g = game_axis(p, at, size, game);
    /* The smallest q with q * game / client >= g (for g < 0 the largest with q * game / client <= g, as division goes
     * towards zero there): the first client coordinate inside that game pixel. */
    long long q = g >= 0 ? (g * client + game - 1) / game : -((-g * client + game - 1) / game);
    return (int)q;
}

void pointer_for_game(int px, int py, int cw, int ch, PicRect r, int *qx, int *qy)
{
    *qx = pointer_axis(px, r.x, r.w, cw, GAME_W);
    *qy = pointer_axis(py, r.y, r.h, ch, GAME_H);
}

/* ------------------------------------------------------------------------------------------------- slot index */

/* A key's first place: Fibonacci hashing of its address (its low bits are its alignment, the same for every key), the
 * product's top bits. */
static unsigned slot_home(const void *key)
{
    unsigned long long v = (unsigned long long)(uintptr_t)key * 0x9E3779B97F4A7C15ull;
    /* 8192 places: the product's top 13 bits. */
    return (unsigned)(v >> 51) & (SLOT_INDEX_SIZE - 1);
}

int slot_index_get(const SlotIndex *x, const void *key)
{
    unsigned mask = SLOT_INDEX_SIZE - 1;
    /* From its first place on, until the key or an empty place (where it would have been put). */
    for (unsigned i = slot_home(key), n = 0; n < SLOT_INDEX_SIZE; i = (i + 1) & mask, n++) {
        if (!x->key[i])
            return -1;
        if (x->key[i] == key)
            return x->slot[i];
    }
    return -1;
}

int slot_index_put(SlotIndex *x, const void *key, int slot)
{
    unsigned mask = SLOT_INDEX_SIZE - 1;
    /* The key's own place when it is in already, else the first empty one from its first place on. */
    for (unsigned i = slot_home(key), n = 0; n < SLOT_INDEX_SIZE; i = (i + 1) & mask, n++) {
        if (!x->key[i] || x->key[i] == key) {
            x->key[i] = key;
            x->slot[i] = slot;
            return 1;
        }
    }
    return 0;
}

void slot_index_del(SlotIndex *x, const void *key)
{
    unsigned mask = SLOT_INDEX_SIZE - 1, hole = slot_home(key);
    /* Its place, or nothing to do. */
    for (unsigned n = 0;; hole = (hole + 1) & mask, n++) {
        if (n == SLOT_INDEX_SIZE || !x->key[hole])
            return;
        if (x->key[hole] == key)
            break;
    }
    /* The keys after it, up to the next empty place, moved back into the hole when the hole lies between a key's first
     * place and where it is (so every key stays reachable from its first place), the hole moving on with each. */
    for (unsigned j = (hole + 1) & mask; x->key[j]; j = (j + 1) & mask) {
        unsigned home = slot_home(x->key[j]);
        if (((j - home) & mask) >= ((j - hole) & mask)) {
            x->key[hole] = x->key[j];
            x->slot[hole] = x->slot[j];
            hole = j;
        }
    }
    x->key[hole] = NULL;
}

/* Each result's word for the log and the launcher's note, in the order of ENGINE_* (opendmt3/client/actions.py reads
 * them back). */
const char *const ENGINE_NAMES[ENGINE_RESULTS] = {"off", "no-device", "no-client3", "no-answer", "none-shorter",
                                                  "locked", "refused", "unchanged", "held"};

unsigned engine_period_ask(unsigned def, unsigned step, unsigned min, unsigned max)
{
    /* Each number must be there, and in the order the API promises: minimum <= default <= maximum. */
    if (!def || !step || !min || !max || min > max || def < min || def > max)
        return 0;
    /* The minimum as a whole number of steps (it is one already when the driver keeps the rules): rounded up, so it
     * never asks for less than the driver offers. */
    unsigned ask = (min + step - 1) / step * step;
    /* Rounded past the maximum, or nothing shorter than the default: nothing to ask. */
    if (ask > max || ask >= def)
        return 0;
    return ask;
}

int engine_period_held(unsigned def, unsigned got)
{
    /* Read, and shorter than the default: the engine runs in shorter steps while the stream runs. */
    return got > 0 && got < def;
}

double engine_ms(unsigned frames, unsigned rate)
{
    /* No rate read: no time to give. */
    return rate ? frames * 1000.0 / rate : 0.0;
}

void engine_note(const EngineReport *r, char *out, int size)
{
    /* A result out of range is never written as some other's word. */
    const char *word = r->result >= 0 && r->result < ENGINE_RESULTS ? ENGINE_NAMES[r->result] : "unknown";
    /* The device by its GUID, as the launcher keeps its choice (format_guid's upper case with braces). */
    char device[39];
    format_guid(r->device, device);
    /* Words then numbers, one space apart, as key=value: the launcher takes the ones it knows. */
    snprintf(out, (size_t)size, "engine %s output=%s device=%s rate=%u default=%u step=%u min=%u max=%u before=%u "
             "asked=%u got=%u hr=0x%08lx", word, r->chosen ? "chosen" : "default", device, r->rate, r->def, r->step,
             r->min, r->max, r->before, r->asked, r->got, r->hr);
}

/* -------------------------------------------------------------------------------------------- the layer's slides */

/* A share held to 0..1. */
static float share01(float t)
{
    return t < 0.0f ? 0.0f : t > 1.0f ? 1.0f : t;
}

float slide_ease_down(float t)
{
    /* What is left of the way's time, cubed: quick at first, the last of the way the slowest. */
    float left = 1.0f - share01(t);
    return 1.0f - left * left * left;
}

float slide_ease_up(float t)
{
    /* The time gone, squared: slow at first, gathering speed (gentler than the way down's cubic, so the part is seen to
     * set out at once rather than wait and then be gone). */
    float done = share01(t);
    return done * done;
}

void slide_rest(Slide *s, float place)
{
    /* There, still: no way under way. */
    s->from = s->to = share01(place);
    s->began = 0;
    s->lasts = 0;
}

int slide_moving(const Slide *s, double now)
{
    /* A way with a length, its end not yet reached. */
    return s->lasts > 0 && now < s->began + s->lasts;
}

float slide_at(const Slide *s, double now)
{
    /* At rest, or past the way's end: where it was headed, exactly. */
    if (!slide_moving(s, now))
        return s->to;
    /* Before its start (a clock read a moment earlier): where it set out. */
    if (now <= s->began)
        return s->from;
    float t = (float)((now - s->began) / s->lasts);
    /* Down slows into its place, up gathers speed, each over the way's own length. */
    float pace = s->to > s->from ? slide_ease_down(t) : slide_ease_up(t);
    return s->from + (s->to - s->from) * pace;
}

void slide_aim(Slide *s, float target, double now, int animate)
{
    float here = slide_at(s, now);
    target = share01(target);
    /* Headed there already (a way under way keeps its own pace), or there: nothing changes. */
    if (target == s->to && (slide_moving(s, now) || here == target))
        return;
    s->from = here;
    s->to = target;
    s->began = now;
    /* The way's length, and the whole way's time for its direction: a way from midway takes its share of it. */
    float way = target > here ? target - here : here - target;
    double whole = target > here ? SLIDE_DOWN_MS : SLIDE_UP_MS;
    /* Windows' animation effects off: there at once. */
    s->lasts = animate ? whole * (double)way : 0.0;
}

float slide_rows(float place, float bar_h, float shade)
{
    /* The bar's foot below the top edge: its whole travel (its height and its shadow's room) times its place, less the
     * shadow's room, never above the edge nor below its height. */
    float rows = share01(place) * (bar_h + shade) - shade;
    return rows < 0.0f ? 0.0f : rows > bar_h ? bar_h : rows;
}

float slide_top(float place, float rows, float h, float shade)
{
    /* On the foot when in place; a whole travel (its height and its shadow's room) higher when out of sight. */
    return rows - (1.0f - share01(place)) * (h + shade);
}

int ui_hit_moved(const UiLayout *l, float x, float y, float bar_dy, float panel_dy)
{
    /* Nothing of the layer above the game's top edge: a part on its way out of it is cut there (post.c part_quad), and
     * above a kept picture is the window's bar, where a press is the game's as ever. */
    if (y < 0.0f)
        return HIT_NONE;
    /* The bar first: it lies over the panel while the panel slides out from under it. Its chips, then the rest of it,
     * where they stand now. */
    UiLayout bar = *l;
    bar.count = 0;
    bar.panel.w = 0;
    bar.bar.y += bar_dy;
    for (int i = 0; i < CHIPS; i++)
        bar.chip[i].y += bar_dy;
    int hit = ui_hit(&bar, x, y);
    if (hit != HIT_NONE)
        return hit;
    /* Then the panel and its answers where they stand now (none open: nothing more). */
    if (l->panel.w <= 0)
        return HIT_NONE;
    UiLayout panel = *l;
    panel.panel.y += panel_dy;
    panel.tab.y += panel_dy;
    for (int i = 0; i < l->count && i < 8; i++) {
        panel.rows[i].y += panel_dy;
        panel.track[i].y += panel_dy;
    }
    /* The bar and its chips out of reach here (the pass above had them): only an answer or the panel can be hit. */
    panel.bar.y = -1e9f;
    for (int i = 0; i < CHIPS; i++)
        panel.chip[i].y = -1e9f;
    return ui_hit(&panel, x, y);
}

/* ---------------------------------------------------------------------------------------------- the sound's values */

const int EQ_HZ[EQ_BANDS] = {60, 250, 1000, 4000, 12000};
const char *const SOUND_NAMES[SOUND_VALUES] = {"master_volume", "music_volume", "key_volume", "eq_60",
                                               "eq_250", "eq_1k", "eq_4k", "eq_12k"};

void sound_values_default(SoundValues *s)
{
    /* The three volumes whole, every band flat. */
    for (int i = 0; i < SOUND_VALUES; i++)
        s->v[i] = i < SOUND_EQ0 ? 100 : 0;
}

int sound_value_clamp(int which, int value)
{
    /* A volume in percent, a band in dB. */
    int low = which < SOUND_EQ0 ? 0 : -EQ_MAX_DB, high = which < SOUND_EQ0 ? 100 : EQ_MAX_DB;
    return value < low ? low : value > high ? high : value;
}

/* The value a line names (its index), and where its value starts; -1 for any other line. */
static int sound_line(const char *line, int len, const char **value)
{
    /* Spaces before the name are no part of it. */
    while (len > 0 && (*line == ' ' || *line == '\t')) {
        line++;
        len--;
    }
    for (int i = 0; i < SOUND_VALUES; i++) {
        int n = (int)strlen(SOUND_NAMES[i]);
        const char *p = line + n;
        if (len <= n || strncmp(line, SOUND_NAMES[i], (size_t)n))
            continue;
        /* name, spaces, '=': that value's line. */
        while (p < line + len && (*p == ' ' || *p == '\t'))
            p++;
        if (p < line + len && *p == '=') {
            *value = p + 1;
            return i;
        }
    }
    return -1;
}

/* A UTF-8 byte order mark at a text's start (Notepad may save one): its length, or 0. */
static int bom_at(const char *text)
{
    return text && (unsigned char)text[0] == 0xEF && (unsigned char)text[1] == 0xBB && (unsigned char)text[2] == 0xBF
               ? 3
               : 0;
}

int sound_line_value(const char *line, int len, int *value)
{
    const char *v = NULL;
    int i = sound_line(line, len, &v);
    if (i < 0)
        return -1;
    const char *end = line + len;
    /* Spaces and tabs before the number. */
    while (v < end && (*v == ' ' || *v == '\t'))
        v++;
    /* A minus sign or none (no plus: one way to write a number), then one to four ASCII digits. */
    int minus = v < end && *v == '-';
    v += minus;
    int digits = 0, n = 0;
    while (v < end && *v >= '0' && *v <= '9' && digits < 5) {
        n = n * 10 + (*v - '0');
        digits++;
        v++;
    }
    /* After it only spaces, tabs and the line's own \r. */
    while (v < end && (*v == ' ' || *v == '\t' || *v == '\r'))
        v++;
    if (!digits || digits > 4 || v != end)
        return i;
    n = minus ? -n : n;
    /* Within the value's range, or the line is none the rule takes (a volume below 0, a band past 12 dB). */
    if (n != sound_value_clamp(i, n))
        return i;
    *value = n;
    return i;
}

unsigned sound_values_parse(const char *text, SoundValues *s, int *refused, const char **first_refused)
{
    unsigned named = 0;
    if (refused)
        *refused = 0;
    if (first_refused)
        *first_refused = NULL;
    /* A byte order mark at the start is no part of the first line. */
    text += bom_at(text);
    while (text && *text) {
        const char *end = strchr(text, '\n');
        int len = end ? (int)(end - text) : (int)strlen(text);
        int value = 0x7fffffff;
        int i = sound_line_value(text, len, &value);
        if (i >= 0 && value != 0x7fffffff) {
            /* A value the rule takes: read. */
            s->v[i] = value;
            named |= 1u << i;
        } else if (i >= 0) {
            /* A line naming a value with anything else: left as if it were not there, counted for the log. */
            if (refused)
                (*refused)++;
            if (first_refused && !*first_refused)
                *first_refused = text;
        }
        text = end ? end + 1 : text + len;
    }
    return named;
}

int sound_values_merge(const char *old, const SoundValues *s, unsigned changed, char *out, int size)
{
    int at = 0;
    unsigned written = 0;
    /* A byte order mark at the start is dropped: the file is written as UTF-8 without one, as the launcher writes it. */
    old += bom_at(old);
    /* Each line of the file as it is now: a changed value's line rewritten, every other line kept as it was. */
    while (old && *old) {
        const char *end = strchr(old, '\n');
        int len = end ? (int)(end - old) : (int)strlen(old);
        /* A line's own \r (a file saved by Notepad) is no part of it. */
        int text_len = len > 0 && old[len - 1] == '\r' ? len - 1 : len;
        const char *value = NULL;
        int i = sound_line(old, text_len, &value);
        int n;
        if (i >= 0 && (changed & (1u << i)) && !(written & (1u << i))) {
            n = snprintf(out + at, size > at ? (size_t)(size - at) : 0, "%s=%d\n", SOUND_NAMES[i], s->v[i]);
            written |= 1u << i;
        } else if (i >= 0 && (changed & (1u << i))) {
            /* A second line of a value already written: dropped, so the file says it once. */
            n = 0;
        } else {
            n = snprintf(out + at, size > at ? (size_t)(size - at) : 0, "%.*s\n", text_len, old);
        }
        if (n < 0 || at + n >= size)
            return -1;
        at += n;
        old = end ? end + 1 : old + len;
    }
    /* A changed value the file had no line for: added at its end. */
    for (int i = 0; i < SOUND_VALUES; i++) {
        if (!(changed & (1u << i)) || (written & (1u << i)))
            continue;
        int n = snprintf(out + at, size > at ? (size_t)(size - at) : 0, "%s=%d\n", SOUND_NAMES[i], s->v[i]);
        if (n < 0 || at + n >= size)
            return -1;
        at += n;
    }
    return at;
}

int game_volume_value(int percent)
{
    /* The percent on the game's 0 to 127, rounded to the nearest step, never 0 (values.to_game_volume). */
    int v = (int)lround(percent * 127.0 / 100.0);
    return v < 1 ? 1 : v > 127 ? 127 : v;
}

double game_curve_db(int value)
{
    /* Twice an amplitude's: the game's gain falls as the square of the value. */
    return 40.0 * log10((value < 1 ? 1 : value) / 127.0);
}

/* A DirectSound volume held to its range. */
static long within_volume(long v)
{
    return v > 0 ? 0 : v < -10000 ? -10000 : v;
}

long volume_moved(long game_v, int launch, int now)
{
    /* 0 %: silent, whatever the game set. */
    if (now <= 0)
        return -10000;
    /* The game made its volume from setting.ini's value of the launch percent: the move is its own curve's step from
     * that value to the one of the percent now, in hundredths of a dB. */
    double step = game_curve_db(game_volume_value(now)) - game_curve_db(game_volume_value(launch));
    return within_volume(game_v + lround(100.0 * step));
}

long volume_for_kind(long game_v, int kind, int launch, int now)
{
    if (kind == VOLUME_SONG)
        return volume_moved(game_v, launch, now);
    if (kind == VOLUME_KEYS) {
        /* openDMT3's own volume, by the game's curve from 100 %: the game's own setting never moved them. */
        if (now <= 0)
            return -10000;
        return within_volume(game_v + lround(100.0 * game_curve_db(game_volume_value(now))));
    }
    /* The menus' loops: as the game set them (the master moves them at the last stage). */
    return game_v;
}

/* RBJ's cookbook: a peak (shelf 0), a low shelf (1) or a high shelf (2) of `db` at `hz`, normalised (a0 = 1). */
static Biquad biquad(int shelf, double hz, double db, double rate)
{
    const double PI = 3.14159265358979323846;
    double A = pow(10.0, db / 40.0), w = 2.0 * PI * hz / rate, cw = cos(w), sw = sin(w);
    double b0, b1, b2, a0, a1, a2;
    if (!shelf) {
        /* A peak an octave and a third wide (Q 1). */
        double alpha = sw / 2.0;
        b0 = 1 + alpha * A;
        b1 = -2 * cw;
        b2 = 1 - alpha * A;
        a0 = 1 + alpha / A;
        a1 = -2 * cw;
        a2 = 1 - alpha / A;
    } else {
        /* A shelf of slope 1. */
        double alpha = sw / 2.0 * sqrt(2.0), sa = 2 * sqrt(A) * alpha, s = shelf == 1 ? 1.0 : -1.0;
        b0 = A * ((A + 1) - s * (A - 1) * cw + sa);
        b1 = s * 2 * A * ((A - 1) - s * (A + 1) * cw);
        b2 = A * ((A + 1) - s * (A - 1) * cw - sa);
        a0 = (A + 1) + s * (A - 1) * cw + sa;
        a1 = -s * 2 * ((A - 1) + s * (A + 1) * cw);
        a2 = (A + 1) + s * (A - 1) * cw - sa;
    }
    Biquad q = {(float)(b0 / a0), (float)(b1 / a0), (float)(b2 / a0), (float)(a1 / a0), (float)(a2 / a0)};
    return q;
}

int volume_kind(int looping, unsigned long size, unsigned long bytes_a_second)
{
    /* A loop: the menus'; a buffer of 10 s or more played once: a song's music; the rest the key sounds'. */
    if (looping)
        return VOLUME_MENU;
    return bytes_a_second && size >= 10 * bytes_a_second ? VOLUME_SONG : VOLUME_KEYS;
}

int volume_reapply(int applied, int kind_now, int moved_now)
{
    /* Its kind's volume moved, or its volume last set for the other kind. */
    return moved_now || (applied && applied != kind_now + 1);
}

/* One biquad's gain in dB at the angle w (radians a sample): |b0 + b1 z^-1 + b2 z^-2| / |1 + a1 z^-1 + a2 z^-2|. */
static double biquad_db(const Biquad *q, double w)
{
    double c1 = cos(w), s1 = sin(w), c2 = cos(2 * w), s2 = sin(2 * w);
    double nr = q->b0 + q->b1 * c1 + q->b2 * c2, ni = -(q->b1 * s1 + q->b2 * s2);
    double dr = 1 + q->a1 * c1 + q->a2 * c2, di = -(q->a1 * s1 + q->a2 * s2);
    return 10.0 * log10((nr * nr + ni * ni) / (dr * dr + di * di));
}

double mix_curve_db(const MixShape *m, double hz, int rate)
{
    const double PI = 3.14159265358979323846;
    double w = 2.0 * PI * hz / rate, db = 0;
    /* The bands one after the other: their gains in dB add up. */
    for (int b = 0; b < m->bands; b++)
        db += biquad_db(&m->band[b], w);
    return db;
}

void mix_shape(MixShape *m, const SoundValues *s, int rate)
{
    memset(m, 0, sizeof *m);
    /* Only the bands that are not flat run (a flat one changes nothing), and only below the rate's half: one at or
     * above it (12 kHz at 22050 Hz or less) is left off, and said so (`dropped`). */
    for (int b = 0; b < EQ_BANDS; b++) {
        if (!s->v[SOUND_EQ0 + b])
            continue;
        if (rate <= 2 * EQ_HZ[b]) {
            m->dropped |= 1u << b;
            continue;
        }
        m->band[m->bands++] = biquad(b == 0 ? 1 : b == EQ_BANDS - 1 ? 2 : 0, EQ_HZ[b], s->v[SOUND_EQ0 + b], rate);
        m->mask |= 1u << b;
    }
    /* The automatic preamp: the curve's highest gain over the hearing range (20 Hz to 20 kHz, or to just below half
     * the rate), read at 96 points a twelfth of an octave or so apart, taken off before the bands, so a boost raises
     * its band over the others and never takes the mix past where it was (neighbouring peaks add up: every band at
     * +12 dB reaches +14 dB between them). */
    double top = 0, high = rate * 0.45 < 20000.0 ? rate * 0.45 : 20000.0;
    for (int k = 0; k < 96 && m->bands; k++) {
        double hz = 20.0 * pow(high / 20.0, k / 95.0), db = mix_curve_db(m, hz, rate);
        if (db > top)
            top = db;
    }
    /* At each band's own middle too: the grid could pass a narrow peak's top by. */
    for (int b = 0; b < EQ_BANDS && m->bands; b++) {
        double db = EQ_HZ[b] < high ? mix_curve_db(m, EQ_HZ[b], rate) : 0;
        if (db > top)
            top = db;
    }
    m->preamp_db = (float)-top;
    m->gain = (float)(s->v[SOUND_MASTER] / 100.0 * pow(10.0, -top / 20.0));
    m->on = m->bands > 0 || s->v[SOUND_MASTER] != 100;
}

/* One sample of channel c through every band (transposed direct form II), after the master volume and the preamp. */
static float mix_sample(const MixShape *m, MixState *st, float x, int c)
{
    x *= m->gain;
    for (int b = 0; b < m->bands; b++) {
        const Biquad *q = &m->band[b];
        float y = q->b0 * x + st->z1[b][c];
        st->z1[b][c] = q->b1 * x - q->a1 * y + st->z2[b][c];
        st->z2[b][c] = q->b2 * x - q->a2 * y;
        x = y;
    }
    return x;
}

/* After a run: a state value that is not a finite number (a NaN came in) starts the whole state again, so one bad
 * sample never silences the stream for good; one too small to be heard is taken to 0 (no denormal numbers). */
static void mix_clean(MixState *st)
{
    float *z = &st->z1[0][0];
    int n = (int)(sizeof *st / sizeof *z), bad = 0;
    for (int i = 0; i < n; i++) {
        if (!isfinite(z[i]))
            bad = 1;
        else if (fabsf(z[i]) < 1e-20f)
            z[i] = 0.0f;
    }
    if (bad)
        memset(st, 0, sizeof *st);
}

/* A sample held within full scale (the last guard: the preamp keeps a steady sound below it). */
static float within_full_scale(float y)
{
    /* A NaN out of a NaN in goes out as silence. */
    if (!(y == y))
        return 0.0f;
    return y > 1.0f ? 1.0f : y < -1.0f ? -1.0f : y;
}

void mix_run_float(const MixShape *m, MixState *st, float *x, int frames, int channels)
{
    if (!m->on || channels < 1 || channels > MIX_CHANNELS)
        return;
    for (int i = 0; i < frames * channels; i++)
        x[i] = within_full_scale(mix_sample(m, st, x[i], i % channels));
    mix_clean(st);
}

void mix_run_s16(const MixShape *m, MixState *st, int16_t *x, int frames, int channels)
{
    if (!m->on || channels < 1 || channels > MIX_CHANNELS)
        return;
    for (int i = 0; i < frames * channels; i++) {
        float y = within_full_scale(mix_sample(m, st, x[i] / 32768.0f, i % channels)) * 32768.0f;
        /* Within the 16 bits: +1.0 is one step past their top, so it is held there, never wrapped round. */
        x[i] = (int16_t)(y > 32767.0f ? 32767 : y < -32768.0f ? -32768 : lrintf(y));
    }
    mix_clean(st);
}

void mix_run_s32(const MixShape *m, MixState *st, int32_t *x, int frames, int channels)
{
    if (!m->on || channels < 1 || channels > MIX_CHANNELS)
        return;
    for (int i = 0; i < frames * channels; i++) {
        double y = (double)within_full_scale(mix_sample(m, st, (float)(x[i] / 2147483648.0), i % channels)) *
                   2147483648.0;
        x[i] = (int32_t)(y > 2147483647.0 ? 2147483647 : y < -2147483648.0 ? -2147483648.0 : llrint(y));
    }
    mix_clean(st);
}
