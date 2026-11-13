/*
 * openDMT3's touch screen library (native/cardreader/multidll.c) and the card reader library's touch screen behind it
 * (touch.c, contacts.c), tried without the game (tests/e2e/windows/touch.sh): this program loads the built CRT_R1.dll,
 * then the built multiDLL.dll beside it, as the game's imports load them, and calls the stand-in as the game does: its
 * OpenNexioMulti, then WaitNexioMulti(1, buffer) into a buffer of the game's size once a "frame", each read read back
 * the way the game reads it (its FUN_0070efa0). The contacts are made up with OPENDMT3_TOUCH_INJECT, as no touch screen
 * can be made here:
 *   - the three names the client imports, at the original library's numbers, and nothing else of the stand-in's;
 *   - the touch screen opens; a finger is a press at its place, a second one while it holds is a new finger, the
 *     second let go leaves the first held, both let go is a release; a finger down in the read another came up in
 *     is a press too; after the close the stand-in answers 2;
 *   - "off" (OPENDMT3_MULTI_TOUCH=off) and "alone" (the stand-in loaded without openDMT3's card reader library): the
 *     open fails, as the original's does on a PC, so the game plays the mouse as before.
 *
 *   wine touch_probe.exe [off|alone]     (OPENDMT3_TOUCH_INJECT and OPENDMT3_INGAME_LOG in the environment)
 * Prints one line a finding; exits 0 when every one held, 1 otherwise.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>

/* The stand-in's three calls, __cdecl as the client calls them. */
typedef int(__cdecl *OpenFn)(void);
typedef int(__cdecl *WaitFn)(int, void *);
typedef int(__cdecl *CloseFn)(void);

/* The game's buffer: 16 bytes of head and 100 groups of 100 points of 24 bytes. */
#define BUFFER 0x3A990
static unsigned char g_buffer[BUFFER];

/* A finding: its line, and whether it held (counted against the exit code). */
static int g_bad;
static void say(int ok, const char *what)
{
    printf("%s %s\n", ok ? "ok  " : "FAIL", what);
    g_bad += !ok;
}

/* What the game holds of a read, as its point reader keeps it. */
typedef struct {
    int x[100], y[100];
    int count, touching, pressed, several, new_finger;
    unsigned sum;
} GameTouch;

static unsigned get32(const unsigned char *at)
{
    return (unsigned)at[0] | (unsigned)at[1] << 8 | (unsigned)at[2] << 16 | (unsigned)at[3] << 24;
}

static unsigned get16(const unsigned char *at)
{
    return (unsigned)at[0] | (unsigned)at[1] << 8;
}

/* The game's reader after WaitNexioMulti answered `result`, step by step as the client does it. */
static void game_reads(GameTouch *g, const unsigned char *b, int result)
{
    g->count = 0;
    g->pressed = g->new_finger = 0;
    unsigned h0 = get32(b), h1 = get32(b + 4), h2 = get32(b + 8), h3 = get32(b + 12);
    if (result == 2 || h0 == 0) {
        if (h0 == 0) {
            g->touching = g->several = 0;
            g->sum = h2 + h3;
        }
        return;
    }
    if (!g->touching)
        g->pressed = 1;
    g->touching = 1;
    if (h1 > 1) {
        g->several = 1;
        if (g->sum < h2 + h3)
            g->new_finger = 1;
    }
    g->sum = h2 + h3;
    for (unsigned c = 0; c < h2; c++)
        for (unsigned p = 0; p < h3 && g->count < 100; p++, g->count++) {
            g->x[g->count] = 0x500 - (int)get16(b + 0x10 + c * 0x960 + p * 0x18 + 0xc);
            g->y[g->count] = 0x300 - (int)get16(b + 0x10 + c * 0x960 + p * 0x18 + 0xe);
        }
}

/* One frame's read: the stand-in's answer, and the game's reading of the buffer after it. */
static int frame(WaitFn wait, GameTouch *g)
{
    int r = wait(1, g_buffer);
    game_reads(g, g_buffer, r);
    return r;
}

int main(int argc, char **argv)
{
    const char *mode = argc > 1 ? argv[1] : "";
    /* The card reader library first, as the game's import table has it (the stand-in finds it loaded). */
    HMODULE ours = strcmp(mode, "alone") ? LoadLibraryA("CRT_R1.dll") : NULL;
    HMODULE stand = LoadLibraryA("multiDLL.dll");
    if (!stand || (strcmp(mode, "alone") && !ours)) {
        say(0, "the libraries load");
        return 1;
    }
    OpenFn open = (OpenFn)(void *)GetProcAddress(stand, "OpenNexioMulti");
    WaitFn wait = (WaitFn)(void *)GetProcAddress(stand, "WaitNexioMulti");
    CloseFn close = (CloseFn)(void *)GetProcAddress(stand, "CloseNexioMulti");
    /* The original's numbers: Close 1, Open 2, Wait 3; no fourth. */
    say(open && wait && close && (void *)GetProcAddress(stand, (LPCSTR)1) == (void *)close &&
            (void *)GetProcAddress(stand, (LPCSTR)2) == (void *)open &&
            (void *)GetProcAddress(stand, (LPCSTR)3) == (void *)wait && !GetProcAddress(stand, (LPCSTR)4),
        "the stand-in has the three names the client imports, at the original's numbers, and no other");
    if (!open || !wait || !close)
        return 1;
    if (!strcmp(mode, "alone") || !strcmp(mode, "off")) {
        /* No openDMT3 card reader beside it, or the measuring switch: the open fails, as the original's on a PC. */
        say(open() == 0 && wait(1, g_buffer) == 2, !strcmp(mode, "off")
            ? "OPENDMT3_MULTI_TOUCH=off: the open fails, so the game keeps its own mouse"
            : "without openDMT3's card reader library the open fails, so the game plays the mouse as before");
        return g_bad ? 1 : 0;
    }
    say(open() == 1, "the touch screen opens with openDMT3's card reader library beside it");
    GameTouch g;
    memset(&g, 0, sizeof g);
    /* The game's own first read, at its open: nothing on the screen. */
    int r = frame(wait, &g);
    say(r == 0 && !g.touching, "the game's first read: an answer of new points, nothing on the screen");
    /* Read 2: one made-up finger at the game's pixel 100,600. */
    frame(wait, &g);
    say(g.pressed && g.count == 1 && g.x[0] == 100 && g.y[0] == 600, "a finger: a press, at its own place in the game's "
                                                                     "pixels (the point turned as the frame turned it)");
    /* Read 3: a second at 1180,600 while the first holds. */
    frame(wait, &g);
    say(g.new_finger && !g.pressed && g.count == 2 && g.x[0] == 100 && g.x[1] == 1180,
        "a second finger while the first holds: a new finger, both points, the first still first");
    /* Read 4: the second let go. */
    frame(wait, &g);
    say(g.touching && !g.new_finger && !g.pressed && g.count == 1 && g.x[0] == 100,
        "the second let go: the first still held, no press");
    /* Read 5: both let go; read 6: still nothing. */
    frame(wait, &g);
    int released = !g.touching;
    frame(wait, &g);
    say(released && !g.touching, "both let go: a release, and nothing after");
    /* Read 7: a finger at 300,600; read 8: it comes up as another goes down at 340,600 (the count kept growing by a
     * point off the screen); read 9: up. */
    frame(wait, &g);
    int first = g.pressed && g.count == 1 && g.x[0] == 300;
    frame(wait, &g);
    int on = 0, off = 1;
    for (int i = 0; i < g.count; i++) {
        if (g.x[i] == 340 && g.y[i] == 600)
            on++;
        else if (g.x[i] >= 0 && g.x[i] <= 1280 && g.y[i] >= 0 && g.y[i] <= 768)
            off = 0;
    }
    say(first && (g.pressed || g.new_finger) && on == 1 && off,
        "a finger down in the read another came up in: a press at its place, nothing else on the screen");
    frame(wait, &g);
    close();
    say(wait(1, g_buffer) == 2, "after the close the stand-in answers a failure (the game leaves its points)");
    return g_bad ? 1 : 0;
}
