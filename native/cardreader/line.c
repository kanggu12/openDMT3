/*
 * The game's score and its judgement line, watched in the game (ingame.h line_*). Measuring only: nothing here runs
 * unless OPENDMT3_LINE_WATCH names a file (never set by the launcher).
 *
 * The client's score player counts a song in ticks on its clock (clock.c), and its line panel draws the line where
 * that count puts it. With the watch on, the score player's update is followed (score.c, only when it is where it was
 * measured; otherwise nothing is changed and the log says so): the score player and its clock as each frame's update
 * left them, with the count the score itself counted and the one shown and judged (less the audio offset's lag, when
 * one is set). One row a frame goes into the file, at the frame's present: the frame's clock as the score player read
 * it and the ticks it counted, the ticks shown, its tempo, where the line is along its row by the game's own fields,
 * and the music's position as openDMT3 reads it, so the score can be set beside the music with nothing else changed
 * (tests/e2e/windows/gpu/line.py reads it back).
 */
#include "ingame.h"

#include <stdio.h>
#include <string.h>

/* The score player's fields (its base class's first, then its own), by their offsets in it. */
#define SP_CLOCK 0x10        /* 64-bit: the clock its last update read */
#define SP_REM 0x18          /* double: what is left to the next tick, in the clock's 100 ns units */
#define SP_MS_PER_TICK 0x20  /* double: one tick's length, ms */
#define SP_BPM 0x28          /* float: the tempo */
#define SP_PLAYING 0x2c      /* byte: the score plays */
#define SP_TICK 0x30         /* 32-bit: the ticks counted */
#define SP_WIDTH 0x578       /* float: a row of the line's sweep, the game's pixels */
#define SP_MEASURE 0x5c0     /* 32-bit: a quarter of a row's ticks */
#define SP_ROW 0x5d4         /* byte: the row the line sweeps */
#define SP_SIXTEENTH 0x5d8   /* 32-bit: the sixteenth of the row the line is in */
#define SP_POS 0x5dc         /* float: the line's place along its row */
#define SP_BEAT 0x604        /* 32-bit: a beat's ticks */

/* What a frame's update left in the score player, read right after it counted the frame's ticks. */
typedef struct {
    const BYTE *player;      /* the score player (NULL: none updated this frame) */
    LONGLONG qpc;            /* when, by the performance counter */
    uint32_t tick;           /* the ticks the score counted */
    uint32_t shown;          /* the ticks shown and judged (the count less the audio offset's lag) */
    double rem;
    int64_t clock;
    double ms_per_tick;
    int row_ticks;
    float width;
    float bpm;
    int playing;
    int beat;
} Advance;

/* This frame's update, as line_counted read it. */
static Advance g_advance;
/* The watch's file (NULL: no watch), its rows written, and the counter's frequency. */
static FILE *g_rows;
static long g_rows_written;
static LARGE_INTEGER g_freq;

/* After each frame's count (score.c): the score player as the update left it, the ticks it counted and the ones
 * shown. */
static void line_counted(const BYTE *p, uint32_t real, uint32_t shown)
{
    /* When, by the counter (the frame's present comes later). */
    LARGE_INTEGER now;
    QueryPerformanceCounter(&now);
    g_advance.player = p;
    g_advance.qpc = now.QuadPart;
    g_advance.tick = real;
    g_advance.shown = shown;
    g_advance.rem = *(const double *)(p + SP_REM);
    g_advance.clock = *(const int64_t *)(p + SP_CLOCK);
    g_advance.ms_per_tick = *(const double *)(p + SP_MS_PER_TICK);
    /* A row is four of the score player's quarter-rows (its own sum for the line's place). */
    g_advance.row_ticks = *(const int32_t *)(p + SP_MEASURE) * 4;
    g_advance.width = *(const float *)(p + SP_WIDTH);
    g_advance.bpm = *(const float *)(p + SP_BPM);
    g_advance.playing = *(const BYTE *)(p + SP_PLAYING);
    g_advance.beat = *(const int32_t *)(p + SP_BEAT);
}

void line_attach(struct IDirect3DDevice9 *device)
{
    (void)device;
    QueryPerformanceFrequency(&g_freq);
    char path[MAX_PATH];
    DWORD got = GetEnvironmentVariableA("OPENDMT3_LINE_WATCH", path, sizeof path);
    /* No watch (a player's game), one already open (a second device), or a value too long to be a file's name. */
    if (!got || got >= sizeof path || g_rows)
        return;
    /* The score player's update followed (score.c), or nothing to watch. */
    if (!score_follow())
        return;
    g_rows = fopen(path, "w");
    if (!g_rows) {
        ingame_log("line: the watch's file did not open: nothing written");
        return;
    }
    fprintf(g_rows, "frame,qpc,adv_qpc,qpc_freq,updated,clock,now,tick,shown,rem,ms_per_tick,bpm,playing,row_ticks,"
                    "width,beat,pos,row,sixteenth,music_ms,music_frame\n");
    /* Each update's counts from here on. */
    score_watch(line_counted);
    ingame_log("line: watching the score, a row a frame (measuring)");
}

void line_present(long frame)
{
    if (!g_rows)
        return;
    LARGE_INTEGER now;
    QueryPerformanceCounter(&now);
    const Advance *a = &g_advance;
    const BYTE *p = a->player;
    double ms = -1;
    long started = -1;
    if (!sound_music_position(&ms, &started))
        ms = -1, started = -1;
    /* The frame, when it came here and when its update counted its ticks (the counter's own ticks, whole: Direct3D
     * leaves this thread's floating point at single precision, too coarse for them), the score's clock then and the
     * interrupt time now. */
    fprintf(g_rows, "%ld,%lld,%lld,%lld,%d,%lld,%lld", frame, (long long)now.QuadPart, p ? (long long)a->qpc : -1LL,
            (long long)g_freq.QuadPart, p != NULL, p ? (long long)a->clock : -1LL, (long long)clock_interrupt_now());
    if (p)
        fprintf(g_rows, ",%u,%u,%.4f,%.6f,%.3f,%d,%d,%.2f,%d", a->tick, a->shown, a->rem, a->ms_per_tick,
                (double)a->bpm, a->playing, a->row_ticks, (double)a->width, a->beat);
    else
        fprintf(g_rows, ",,,,,,,,,");
    /* The line's place by the score player's own fields after the frame's panels took it (read at the present). */
    if (p)
        fprintf(g_rows, ",%.4f,%d,%d", (double)*(const float *)(p + SP_POS), *(const BYTE *)(p + SP_ROW),
                *(const int32_t *)(p + SP_SIXTEENTH));
    else
        fprintf(g_rows, ",,,");
    fprintf(g_rows, ",%.2f,%ld\n", ms, started);
    /* Half a second at a time reaches the disk (the game's end closes nothing of ours: it loses no more). */
    if (++g_rows_written % 30 == 0)
        fflush(g_rows);
    /* The next frame starts with nothing seen. */
    memset(&g_advance, 0, sizeof g_advance);
}
