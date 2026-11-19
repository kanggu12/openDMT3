/*
 * Presses made by the layer itself at a set time after each plain note, to see how the game judges them (ingame.h
 * press_attach). Measuring only: nothing here runs unless OPENDMT3_PRESS_LATE is set (never by the launcher).
 *
 * The client judges a plain note (0x509f30) each frame while the note is within its outermost window: it asks the
 * score player whether the note is pressed (0x532af0), then takes the level the press's distance from the note gives
 * (0x50ac10: from 6, the tightest window, down to 2, the outermost), the distance in whole ticks of the count the score
 * player shows (less the audio offset's lag, score.c). With the watch's variable set, those two calls in that judge
 * are turned to ours, only when their bytes are as measured: a plain note is pressed at the first frame the score's
 * own count (the one it counted on its clock, as a player hears the music) reaches the note's tick plus the
 * milliseconds given, the values taken by the notes in turn as each first comes into the window
 * (OPENDMT3_PRESS_LATE=80,0: the first note pressed 80 ms after its time, the next on it, and so on). Nothing else is
 * pressed, and the game's own press check is not asked. Each press's judgement goes into the log: the music it is in
 * (the frame it started at), the note's tick, the milliseconds asked, the score's own count, the count the judge took,
 * the distance and the level the game gave (tests/e2e/windows/gpu/line.py presses reads them back). The guest's
 * tutorial and the attract screens play themselves (their judge's own-play flag): a note there is judged on its own as
 * soon as the count shown is past it, so only a press made before that is the layer's; a song is the player's.
 */
#include "ingame.h"

#include <string.h>

/* The plain note judge's two calls in the build measured: the bytes from the arguments' pushes to each call's end. */
#define PRESS_CALL 0x0050a018 /* call 0x532af0: is the note pressed (the score player in ECX, three arguments) */
#define LEVEL_CALL 0x0050a033 /* call 0x50ac10: the level of a distance (the judge in ECX, three arguments) */
#define PRESS_FROM 0x0050a009
static const BYTE PRESS_BYTES[20] = {0x6a, 0x00, 0x8b, 0x55, 0x08, 0x52, 0x8b, 0x45, 0x10, 0x50,
                                     0x8b, 0x4d, 0xfc, 0x8b, 0x09, 0xe8, 0xd3, 0x8a, 0x02, 0x00};
#define LEVEL_FROM 0x0050a024
static const BYTE LEVEL_BYTES[20] = {0x8b, 0x45, 0xf0, 0x50, 0x8b, 0x4d, 0xf4, 0x51, 0x8b, 0x55,
                                     0xec, 0x52, 0x8b, 0x4d, 0xfc, 0xe8, 0xd8, 0x0b, 0x00, 0x00};
/* The functions those calls reach (both pop their three arguments themselves). */
#define LEVEL_FN 0x0050ac10

/* The score player's fields, by their offsets (score.c has them all). */
#define SP_MS_PER_TICK 0x20
#define SP_TICK 0x30

/* The milliseconds after each note, taken by the notes in turn, and how many notes have taken one. */
#define PRESS_VALUES 8
static int g_late[PRESS_VALUES], g_values;
static unsigned long g_given;
/* The notes asked about lately and the value each took: a note keeps its own while the judge asks about it, frame
 * after frame (a few notes are in the window at once). */
#define SEEN 64
static struct {
    const void *note;
    int late;
} g_seen[SEEN];
static int g_next_seen;
/* The press just made, for the level's line that follows it in the same judge. */
static struct {
    int made, late;
    long music;
    uint32_t note, own, judged;
    double ms_per_tick;
} g_last;

/* The milliseconds a note is pressed after its time: the one it took, or the next value when it is new. */
static int late_for(const void *note)
{
    for (int i = 0; i < SEEN; i++)
        if (g_seen[i].note == note)
            return g_seen[i].late;
    int late = g_late[g_given++ % (unsigned long)g_values];
    /* Over the oldest of those kept (long judged by now). */
    g_seen[g_next_seen].note = note;
    g_seen[g_next_seen].late = late;
    g_next_seen = (g_next_seen + 1) % SEEN;
    return late;
}

/* The game's level of a distance, called as the judge calls it (ECX the judge; EDX nothing). */
typedef BYTE(__fastcall *LevelFn)(void *judge, void *unused, int distance, int kind, int lane);

/* Is the note pressed: at the first frame the score's own count reaches its tick plus the note's milliseconds. ECX is
 * the score player; the three arguments as the judge pushed them (the note's place first), popped here as the game's
 * own pops them. */
static char __fastcall our_press(void *score, void *unused, int **note, void *input, char flag)
{
    (void)unused;
    (void)input;
    (void)flag;
    const BYTE *p = score;
    int late = late_for(*note);
    double ms_per_tick = *(volatile double *)(p + SP_MS_PER_TICK);
    /* The note's tick is its first word; the milliseconds after it in the song's whole ticks. */
    uint32_t tick = *(const uint32_t *)*note;
    uint32_t own = score_own_count(p);
    if (own < tick + chart_lag_ticks(late, ms_per_tick))
        return 0;
    g_last.made = 1;
    g_last.late = late;
    /* The music it is in: the frame the game's music started at, as the layer reads it (-1: none). */
    double ms;
    long started;
    g_last.music = sound_music_position(&ms, &started) ? started : -1;
    g_last.note = tick;
    g_last.own = own;
    g_last.judged = *(volatile uint32_t *)(p + SP_TICK);
    g_last.ms_per_tick = ms_per_tick;
    return 1;
}

/* The judge's own-play flag: set, it judges a note itself once the count shown is past it (the guest's tutorial, the
 * attract screens). */
#define JUDGE_OWN_PLAY 0x253

/* The level of the press just made, as the game gives it, said in the log with the judge's own-play flag. */
static BYTE __fastcall our_level(void *judge, void *unused, int distance, int kind, int lane)
{
    BYTE level = ((LevelFn)LEVEL_FN)(judge, unused, distance, kind, lane);
    if (g_last.made) {
        g_last.made = 0;
        /* Each count against the note, in ticks and in milliseconds at the song's tempo (signed: before it below 0). */
        int own = (int)(g_last.own - g_last.note), judged = (int)(g_last.judged - g_last.note);
        ingame_log("press: music from frame %ld, a note at tick %u, asked %d ms after it, pressed at the score's own "
                   "count %+d (%+.1f ms), judged at %+d (%+.1f ms): distance %d, level %d, the judge playing itself %d",
                   g_last.music, g_last.note, g_last.late, own, own * g_last.ms_per_tick, judged,
                   judged * g_last.ms_per_tick, distance, level, *((const volatile BYTE *)judge + JUDGE_OWN_PLAY));
    }
    return level;
}

/* A call at `at` turned to `to` when the `n` bytes from `from` (the call's end) are `bytes`. */
static int turn_call(BYTE *from, const BYTE *bytes, size_t n, BYTE *at, void *to)
{
    if (memcmp(from, bytes, n))
        return 0;
    LONG rel = (LONG)((BYTE *)to - (at + 5));
    DWORD old;
    if (!VirtualProtect(at, 5, PAGE_EXECUTE_READWRITE, &old))
        return 0;
    at[0] = 0xe8;
    memcpy(at + 1, &rel, 4);
    VirtualProtect(at, 5, old, &old);
    FlushInstructionCache(GetCurrentProcess(), at, 5);
    return 1;
}

void press_attach(void)
{
    /* Once a process, and only when asked with values that read. */
    static int done;
    char v[64];
    DWORD got = GetEnvironmentVariableA("OPENDMT3_PRESS_LATE", v, sizeof v);
    if (done || !got || got >= sizeof v)
        return;
    done = 1;
    g_values = press_values(v, g_late, PRESS_VALUES);
    if (!g_values) {
        ingame_log("press: OPENDMT3_PRESS_LATE is not whole milliseconds split by commas: no presses");
        return;
    }
    /* Both calls as measured, or neither turned (a press with no level said would say nothing). */
    MEMORY_BASIC_INFORMATION info;
    if (!VirtualQuery((void *)PRESS_FROM, &info, sizeof info) || info.State != MEM_COMMIT ||
        memcmp((void *)PRESS_FROM, PRESS_BYTES, sizeof PRESS_BYTES) ||
        memcmp((void *)LEVEL_FROM, LEVEL_BYTES, sizeof LEVEL_BYTES)) {
        ingame_log("press: the judge is not where it was measured: no presses");
        return;
    }
    turn_call((BYTE *)PRESS_FROM, PRESS_BYTES, sizeof PRESS_BYTES, (BYTE *)PRESS_CALL, (void *)our_press);
    turn_call((BYTE *)LEVEL_FROM, LEVEL_BYTES, sizeof LEVEL_BYTES, (BYTE *)LEVEL_CALL, (void *)our_level);
    ingame_log("press: each plain note pressed %s ms after its time, the values taken in turn (measuring)", v);
}
