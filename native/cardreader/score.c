/*
 * The score player's update followed (ingame.h score_*): the audio offset holds a song's chart behind its music, and
 * the line's watch (line.c) reads each frame's count.
 *
 * The client's score player counts a song in ticks on its clock (clock.c) at each frame's update, starts the chart's
 * own sounds at their ticks (its background tracks, the music's own start), then calls a method of its own that does
 * nothing (its method table's fourth entry). After that update the game's line, its notes and its judging of the
 * presses read the count: the judging takes a press's distance from a note in whole ticks of it. That entry is turned
 * to ours once, only when it holds what it held in the build measured, and only when something needs it: an audio
 * offset (OPENDMT3_AUDIO_OFFSET, the launcher's Sound page) or the watch.
 *
 * With an offset, after each update the count is set back by the offset's lag (logic.c chart_lag_frame), so what is
 * shown and judged is that much behind the music, as a sound device that plays late lets the music be heard. At the
 * next update the count is put back as the score player left it, from the client's clock read at the very start of
 * the count (clock.c calls score_before_count there and nowhere else), so the score loses no tick and its own sounds
 * stay with the music. The count is put back only when it still holds what was written and the score was not started
 * again since (its start clock unchanged: a start sets the count to 0); a score started again starts its lag again
 * at none. Only when the count starts with that clock read as in the build measured, and that read is openDMT3's;
 * otherwise nothing is changed and the log says so (the notes then play with the music, as with no offset).
 */
#include "ingame.h"

#include <string.h>

/* The client's places, in the build measured. */
#define AFTER_COUNT_ENTRY 0x007689e8 /* the score player's table entry its update calls after the count */
#define AFTER_COUNT 0x00530390       /* the method it holds there: one that does nothing */
#define SCORE_TABLE 0x007689dc       /* the score player's method table: a live score player's first word */
#define COUNT 0x00700470             /* the score's count: its first call reads the clock, ECX the score player */
#define COUNT_RETURN 0x0070047e      /* where that call returns to */
#define CLOCK_READ 0x0042e6a0        /* the client's clock read (clock.c turns it) */
/* The count's first bytes: push ebp; mov ebp, esp; sub esp, 0x1c; mov [ebp-0x1c], ecx; then the call of the clock
 * read (from 0x700479 to 0x42e6a0): ECX is still the score player at that call. */
static const BYTE COUNT_BYTES[14] = {0x55, 0x8b, 0xec, 0x83, 0xec, 0x1c, 0x89,
                                     0x4d, 0xe4, 0xe8, 0x22, 0xe2, 0xd2, 0xff};

/* The score player's fields, by their offsets. */
#define SP_MS_PER_TICK 0x20  /* double: one tick's length, ms */
#define SP_TICK 0x30         /* 32-bit: the ticks counted */
#define SP_START 0x38        /* 64-bit: the clock its last start read */

/* A score player followed with the offset: its lag, and what was written in its count until the next count. */
typedef struct {
    BYTE *player;            /* the score player (NULL: a free place) */
    int64_t start;           /* its start clock when its lag began (another one: started again) */
    uint32_t real, shown;    /* its own count at its last update, and the count written for it then */
    int written;             /* the count holds `shown` in place of `real` until the next count */
    unsigned long used;      /* when it was last updated (the updates' own count): the oldest place is taken first */
    ChartLag lag;
} Followed;

/* Four places: one score plays at a time (another state's own, a score made again, a few at most in a session). */
#define FOLLOWED 4
static Followed g_followed[FOLLOWED];
static unsigned long g_uses;
/* The offset's milliseconds (0: none) and the watch's reader (NULL: none). */
static volatile int g_lag_ms;
static volatile ScoreWatch g_watch;
/* The places are kept by the thread that updates the score; a lock all the same, should a score be updated on another
 * (the client makes its scores on a loader thread of its own): held only for a few reads and writes. */
static volatile LONG g_busy;

/* Whether the entry is turned (-1: not tried, 0: it held something else), and the method it held. */
static int g_turned = -1;
typedef void(__fastcall *ThisCall)(void *self, void *unused);
static ThisCall g_after_real;

static void hold_places(void)
{
    /* Taken by one thread at a time: the other one waits the few instructions it is held. */
    while (InterlockedCompareExchange(&g_busy, 1, 0))
        YieldProcessor();
}

static void free_places(void)
{
    InterlockedExchange(&g_busy, 0);
}

/* Whether `n` bytes at `at` are committed memory that can be read. */
static int readable(const void *at, size_t n)
{
    MEMORY_BASIC_INFORMATION info;
    if (!VirtualQuery(at, &info, sizeof info) || info.State != MEM_COMMIT ||
        (info.Protect & (PAGE_NOACCESS | PAGE_GUARD)))
        return 0;
    return (const BYTE *)at + n <= (const BYTE *)info.BaseAddress + info.RegionSize;
}

/* A place given up for another score: a count still written put back first, only when its score player still lives
 * (readable, the score player's table its first word, the count as written and its start unchanged). */
static void let_go(Followed *f)
{
    BYTE *p = f->player;
    if (f->written && readable(p, SP_START + 8) && *(volatile ULONG *)p == SCORE_TABLE &&
        *(volatile uint32_t *)(p + SP_TICK) == f->shown && *(volatile int64_t *)(p + SP_START) == f->start)
        *(volatile uint32_t *)(p + SP_TICK) = f->real;
    memset(f, 0, sizeof *f);
}

/* The place of score player `p`, taken for it when it has none: a free one, or the one updated longest ago. */
static Followed *follow(BYTE *p)
{
    Followed *free_one = NULL, *oldest = NULL;
    for (int i = 0; i < FOLLOWED; i++) {
        Followed *f = &g_followed[i];
        if (f->player == p)
            return f;
        if (!f->player) {
            if (!free_one)
                free_one = f;
        } else if (!oldest || f->used < oldest->used) {
            oldest = f;
        }
    }
    Followed *f = free_one ? free_one : oldest;
    let_go(f);
    f->player = p;
    /* Its start as it is now: its lag begins at none. */
    f->start = *(volatile int64_t *)(p + SP_START);
    chart_lag_start(&f->lag);
    return f;
}

void score_lag_ms(int offset_ms)
{
    /* Milliseconds behind the music; none below 0. */
    g_lag_ms = offset_ms > 0 ? offset_ms : 0;
}

uint32_t score_counted(BYTE *p, uint32_t *real_out)
{
    hold_places();
    Followed *f = follow(p);
    uint32_t now = *(volatile uint32_t *)(p + SP_TICK);
    int64_t start = *(volatile int64_t *)(p + SP_START);
    /* Started again since the last update (its count set to 0, its start clock read again): the lag from none. */
    if (start != f->start) {
        f->start = start;
        f->written = 0;
        chart_lag_start(&f->lag);
    }
    /* The count still as written at the last update and not counted since (the method called again with no count
     * before it): the score's own is the one kept. */
    uint32_t real = f->written && now == f->shown ? f->real : now;
    uint32_t target = chart_lag_ticks(g_lag_ms, *(volatile double *)(p + SP_MS_PER_TICK));
    uint32_t shown = chart_lag_frame(&f->lag, real, target);
    f->real = real;
    f->shown = shown;
    f->used = ++g_uses;
    /* Written only when it differs: with no lag the count is left as the score player has it. */
    f->written = shown != real;
    if (f->written)
        *(volatile uint32_t *)(p + SP_TICK) = shown;
    free_places();
    *real_out = real;
    return shown;
}

void score_before_count(BYTE *p)
{
    hold_places();
    for (int i = 0; i < FOLLOWED; i++) {
        Followed *f = &g_followed[i];
        if (f->player != p)
            continue;
        /* Put back once, and only what this update wrote: a count set since (a start, the game's own) is the game's. */
        if (f->written && *(volatile uint32_t *)(p + SP_TICK) == f->shown &&
            *(volatile int64_t *)(p + SP_START) == f->start)
            *(volatile uint32_t *)(p + SP_TICK) = f->real;
        f->written = 0;
        break;
    }
    free_places();
}

/* After each frame's count: the offset's lag written in it, the watch told, then the score player's own method (which
 * does nothing). */
static void __fastcall our_after_count(void *self, void *unused)
{
    BYTE *p = self;
    if (p) {
        uint32_t real = *(volatile uint32_t *)(p + SP_TICK), shown = real;
        if (g_lag_ms > 0)
            shown = score_counted(p, &real);
        ScoreWatch watch = g_watch;
        if (watch)
            watch(p, real, shown);
    }
    g_after_real(self, unused);
}

int score_follow(void)
{
    if (g_turned >= 0)
        return g_turned;
    g_turned = 0;
    void **entry = (void **)AFTER_COUNT_ENTRY;
    if (!readable(entry, sizeof *entry) || *entry != (void *)AFTER_COUNT) {
        ingame_log("score: the score player is not where it was measured: not followed");
        return 0;
    }
    g_after_real = (ThisCall)(void *)AFTER_COUNT;
    void *ours = (void *)our_after_count;
    DWORD old;
    /* The table is read only: writable for the one write, then as it was. */
    if (!VirtualProtect(entry, sizeof *entry, PAGE_READWRITE, &old))
        return 0;
    *entry = ours;
    VirtualProtect(entry, sizeof *entry, old, &old);
    g_turned = 1;
    ingame_log("score: the score player's update followed");
    return 1;
}

void score_watch(ScoreWatch watch)
{
    g_watch = watch;
}

void score_offset(int offset_ms)
{
    /* Once a process: a device made again or reset finds it done. */
    static int said;
    if (offset_ms <= 0 || said)
        return;
    said = 1;
    /* The count's start as measured, the client's clock read openDMT3's (which puts the count back) and the update
     * followed: all three, or no offset at all (a count set back and never put back would lose ticks every frame). */
    const BYTE *count = (const BYTE *)COUNT;
    if (!readable(count, sizeof COUNT_BYTES) || memcmp(count, COUNT_BYTES, sizeof COUNT_BYTES) ||
        clock_turn((void *)CLOCK_READ) != CLOCK_TURNED || !score_follow()) {
        ingame_log("offset: the score player is not where it was measured: no audio offset (a song's notes with its "
                   "music)");
        return;
    }
    /* The count put back first, then set back: never the one without the other. */
    g_clock_count_return = COUNT_RETURN;
    score_lag_ms(offset_ms);
    ingame_log("offset: a song's notes and their judging held %d ms behind its music (the score player's count set "
               "back after each update, put back before the next)", offset_ms);
}
