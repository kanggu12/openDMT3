/*
 * The score's clock (ingame.h clock_*): the game's chart held still with the game.
 *
 * The client's score player counts a song in ticks on the system's interrupt time, which it reads in one place of its
 * code (0x42e6a0, called when a score starts and at each frame's update), the only read of that time in the client.
 * While openDMT3 holds the game still in a song (the menu, the question, the sound panel, the game minimised), the
 * song's music is stopped where it was, but that time runs on: when the game went on, its next update counted every
 * tick of the hold at once, and the chart ran that far ahead of its music. So that read is turned to openDMT3's own,
 * which gives the interrupt time less the time the game was held: the chart then stops with the music and goes on with
 * it. Only when the read holds exactly what it held in the build measured; otherwise nothing is changed and the log
 * says so (a hold then lets the chart run on, as before).
 *
 * openDMT3's read (clock_score_read) is written in assembly so that it changes nothing but the result in EDX:EAX, as
 * the client's own read does: the client's compiler may count on every other register and the flags being left as
 * they were. It reads Windows' shared page as Windows reads its own times (the high word, the low word, the high
 * word's second copy, again until the two copies agree), and the held total the same way: the total is written at a
 * hold's end on the game's thread, and the client also reads its clock on a thread of its own while it loads a song
 * (its eye-catch screens make the score player there), so the total is published as Windows publishes a time (the
 * second high word first, the low word, the first high word last) and never read torn.
 *
 * The same read starts the score's count at each frame's update: with an audio offset (score.c), when it is called
 * from there (its return address the count's, g_clock_count_return), the score player's count is first put back as
 * the score left it (score_before_count, with the score player the client's ECX holds there), before the count goes on
 * from it. Called from anywhere else (a score's start, on whatever thread) it only reads.
 */
#include "ingame.h"

#include <string.h>

/* The client's read of the interrupt time and its bytes in the build measured: push ebp; mov ebp, esp; the high word
 * from 0x7ffe000c and the low word from 0x7ffe0008 into EDX:EAX (each with a DS prefix); pop ebp; ret. */
#define CLOCK_READ 0x0042e6a0
static const BYTE CLOCK_BYTES[18] = {0x55, 0x8b, 0xec, 0x3e, 0x8b, 0x15, 0x0c, 0x00, 0xfe,
                                     0x7f, 0x3e, 0xa1, 0x08, 0x00, 0xfe, 0x7f, 0x5d, 0xc3};

/* The time the game was held still, in the interrupt time's 100 ns units, as Windows keeps a time in its shared page:
 * its high word twice and its low word between (clock_held writes them, clock_score_read reads them). Not static: the
 * assembly below names them. */
volatile LONG g_clock_held_high1, g_clock_held_high2;
volatile ULONG g_clock_held_low;
/* Where the client's call of the read in the score's count returns to, with the audio offset on (score.c sets it; 0:
 * no offset, a return address never 0). Not static: the assembly names it. */
volatile ULONG g_clock_count_return;

/* openDMT3's read, which the client's jumps to: EDX:EAX = the interrupt time less the held total, every other register
 * and the flags as they were. Each step says why it is there. */
__attribute__((naked)) void clock_score_read(void)
{
    __asm__(
        /* The flags and the registers used besides EDX:EAX, kept for the caller. */
        "    pushfl\n"
        "    pushl %ecx\n"
        "    pushl %ebx\n"
        /* Called from the score's count with the audio offset on (the caller's return address, above the three just
         * kept): the count put back first (score.c), the score player in ECX handed over as the C function's one
         * argument. It may change EAX, ECX and EDX (the ones the result goes in, and ECX, kept above); the flags are
         * kept above too. */
        "    movl 12(%esp), %ebx\n"
        "    cmpl _g_clock_count_return, %ebx\n"
        "    jne 1f\n"
        "    pushl %ecx\n"
        "    call _score_before_count\n"
        "    addl $4, %esp\n"
        /* The held total: its first high word, its low word, then its second high word again until they agree. */
        "1:  movl _g_clock_held_high1, %ebx\n"
        "    movl _g_clock_held_low, %ecx\n"
        "    cmpl _g_clock_held_high2, %ebx\n"
        "    jne 1b\n"
        /* The interrupt time from Windows' shared page the same way: High1Time, LowPart, then High2Time again. */
        "2:  movl 0x7ffe000c, %edx\n"
        "    movl 0x7ffe0008, %eax\n"
        "    cmpl 0x7ffe0010, %edx\n"
        "    jne 2b\n"
        /* The time less the held total, as 64 bits. */
        "    subl %ecx, %eax\n"
        "    sbbl %ebx, %edx\n"
        /* The caller's registers and flags back. */
        "    popl %ebx\n"
        "    popl %ecx\n"
        "    popfl\n"
        "    ret\n");
}

int64_t clock_interrupt_now(void)
{
    /* The shared page's interrupt time: its first high word, the low word, the second high word, until they agree. */
    volatile const LONG *high1 = (const LONG *)0x7ffe000c, *high2 = (const LONG *)0x7ffe0010;
    volatile const ULONG *low = (const ULONG *)0x7ffe0008;
    for (;;) {
        LONG h = *high1;
        ULONG l = *low;
        if (h == *high2)
            return ((int64_t)h << 32) | l;
    }
}

int64_t clock_held_total(void)
{
    /* Read as clock_score_read reads it, so a test sees what the client's read takes off. */
    for (;;) {
        LONG h = g_clock_held_high1;
        ULONG l = g_clock_held_low;
        if (h == g_clock_held_high2)
            return ((int64_t)h << 32) | l;
    }
}

void clock_held(int64_t held)
{
    /* Nothing held (or a clock gone back): nothing to add. */
    if (held <= 0)
        return;
    /* One writer only (the game's thread, at a hold's end): the total read plainly, then published second high word
     * first, the low word, the first high word last, so a read between sees the two high words differ and reads
     * again. */
    int64_t total = clock_held_total() + held;
    g_clock_held_high2 = (LONG)(total >> 32);
    g_clock_held_low = (ULONG)total;
    g_clock_held_high1 = (LONG)(total >> 32);
}

int clock_turn(void *at)
{
    BYTE *p = at;
    /* The jump to openDMT3's read: E9 and its distance from the next instruction. */
    BYTE jump[5] = {0xe9};
    LONG rel = (LONG)((BYTE *)(void *)clock_score_read - (p + 5));
    memcpy(jump + 1, &rel, 4);
    /* Its bytes committed and readable (a client laid out otherwise may have nothing there). */
    MEMORY_BASIC_INFORMATION info;
    if (!VirtualQuery(p, &info, sizeof info) || info.State != MEM_COMMIT ||
        (info.Protect & (PAGE_NOACCESS | PAGE_GUARD)) ||
        (BYTE *)info.BaseAddress + info.RegionSize < p + sizeof CLOCK_BYTES)
        return CLOCK_LEFT;
    /* Turned already (a second device, a reset): nothing to do. */
    if (!memcmp(p, jump, sizeof jump))
        return CLOCK_TURNED;
    /* Anything but the read measured: left as it is. */
    if (memcmp(p, CLOCK_BYTES, sizeof CLOCK_BYTES))
        return CLOCK_LEFT;
    DWORD old;
    if (!VirtualProtect(p, sizeof jump, PAGE_EXECUTE_READWRITE, &old))
        return CLOCK_LEFT;
    memcpy(p, jump, sizeof jump);
    VirtualProtect(p, sizeof jump, old, &old);
    FlushInstructionCache(GetCurrentProcess(), p, sizeof jump);
    return CLOCK_TURNED;
}

void clock_attach(void)
{
    /* Once a process: a device made again or reset finds it turned and says nothing more. */
    static int said;
    int turned = clock_turn((void *)CLOCK_READ);
    if (said)
        return;
    said = 1;
    if (turned == CLOCK_TURNED)
        ingame_log("clock: the score's clock read turned to openDMT3's: a hold holds the chart with the music");
    else
        ingame_log("clock: the score's clock read is not where it was measured: left alone (a hold lets the chart run "
                   "on as before)");
}
