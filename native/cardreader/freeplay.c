/*
 * The game's FREE PLAY left out (ingame.h freeplay_*).
 *
 * The client says FREE PLAY on its screens while its coin mode is free play, as a cabinet that takes no coins does:
 * on the title at the middle of its foot, in a song and on the other screens at the bottom right. On a PC it says
 * nothing, and it stood where the frame rate chip belongs. The words are no picture: the client's font draws them from
 * a string, "     FREE  PLAY     " (its own spaces round the words), of which its read-only data holds five copies,
 * each handed to the font by one push only (one copy for each place the words are drawn). When every copy and its push
 * hold the bytes measured, each copy is made as many spaces: the font then draws twenty blank characters where it drew
 * the words, with the same calls in the same order, so nothing else of the frame changes (the badges, the copyright
 * line and every other word come from strings of their own). A client with other bytes at any of those places is left
 * as it is, and the log says so, once.
 */
#include "ingame.h"

#include <string.h>

/* The five places in the build measured: where the push of a copy's address is (68 and the address), and the copy. */
static const struct {
    DWORD push, text;
} PLACES[FREE_PLAY_PLACES] = {
    {0x0053ee5a, 0x00769698}, /* the screens' common draw (a method of most of their tables): the bottom right */
    {0x0053ef18, 0x007696c8}, /* the same draw's other place, at the middle of the foot */
    {0x0054cb38, 0x0076a440}, /* the coin output parts' own draws (Game::Component's CCoinOutput_Default, */
    {0x0054d056, 0x0076a538}, /* CCoinOutput_Logo */
    {0x0054d5c6, 0x0076a60c}, /* and CCoinOutput_Title, by their tables' RTTI names) */
};

/* Whether `n` bytes from `p` are in memory that can be read (committed, not guarded): a client laid out otherwise may
 * have nothing there. */
static int readable(const void *p, size_t n)
{
    MEMORY_BASIC_INFORMATION info;
    if (!VirtualQuery(p, &info, sizeof info) || info.State != MEM_COMMIT ||
        (info.Protect & (PAGE_NOACCESS | PAGE_GUARD)))
        return 0;
    return (const BYTE *)info.BaseAddress + info.RegionSize >= (const BYTE *)p + n;
}

/* A copy as measured (the words: FREE_PLAY_WHOLE), made blank already (FREE_PLAY_BLANK), or anything else. */
enum { FREE_PLAY_OTHER, FREE_PLAY_WHOLE, FREE_PLAY_BLANK };
static int copy_state(const char *text)
{
    /* Its bytes and its end: the words with their spaces, or as many spaces. */
    if (!memcmp(text, FREE_PLAY_TEXT, sizeof FREE_PLAY_TEXT))
        return FREE_PLAY_WHOLE;
    for (size_t i = 0; i + 1 < sizeof FREE_PLAY_TEXT; i++)
        if (text[i] != ' ')
            return FREE_PLAY_OTHER;
    return text[sizeof FREE_PLAY_TEXT - 1] == '\0' ? FREE_PLAY_BLANK : FREE_PLAY_OTHER;
}

int freeplay_turn(BYTE *const push[], char *const text[], int n)
{
    /* Every place looked at first: any one with other bytes leaves them all as they are (another build of the
     * client, where these addresses hold something else). */
    int whole = 0;
    for (int i = 0; i < n; i++) {
        if (!readable(push[i], 5) || !readable(text[i], sizeof FREE_PLAY_TEXT))
            return FREE_PLAY_LEFT;
        /* The push: 68 and the copy's own address (the client's code hands the font this copy and no other). */
        DWORD to;
        memcpy(&to, push[i] + 1, sizeof to);
        if (push[i][0] != 0x68 || to != (DWORD)(uintptr_t)text[i])
            return FREE_PLAY_LEFT;
        int state = copy_state(text[i]);
        if (state == FREE_PLAY_OTHER)
            return FREE_PLAY_LEFT;
        whole += state == FREE_PLAY_WHOLE;
    }
    /* Blank already (a second device): nothing to write. */
    if (!whole)
        return FREE_PLAY_OUT;
    for (int i = 0; i < n; i++) {
        if (copy_state(text[i]) != FREE_PLAY_WHOLE)
            continue;
        /* The client's read-only data made writable for the words' bytes alone, then as it was. The end stays. */
        DWORD old;
        if (!VirtualProtect(text[i], sizeof FREE_PLAY_TEXT - 1, PAGE_READWRITE, &old))
            return FREE_PLAY_LEFT;
        memset(text[i], ' ', sizeof FREE_PLAY_TEXT - 1);
        VirtualProtect(text[i], sizeof FREE_PLAY_TEXT - 1, old, &old);
    }
    return FREE_PLAY_OUT;
}

void freeplay_attach(void)
{
    /* Once a process: a device made again or reset finds the copies blank and says nothing more. */
    static int done;
    if (done)
        return;
    done = 1;
    /* OPENDMT3_FREE_PLAY=keep (measuring only: frames with the words, to compare with frames without) keeps them. */
    char value[8];
    if (GetEnvironmentVariableA("OPENDMT3_FREE_PLAY", value, sizeof value) > 0 && !lstrcmpiA(value, "keep")) {
        ingame_log("label: the game's FREE PLAY kept (measuring)");
        return;
    }
    BYTE *push[FREE_PLAY_PLACES];
    char *text[FREE_PLAY_PLACES];
    for (int i = 0; i < FREE_PLAY_PLACES; i++) {
        push[i] = (BYTE *)(uintptr_t)PLACES[i].push;
        text[i] = (char *)(uintptr_t)PLACES[i].text;
    }
    if (freeplay_turn(push, text, FREE_PLAY_PLACES) == FREE_PLAY_OUT)
        ingame_log("label: the game's FREE PLAY left out (its %d strings made blank)", FREE_PLAY_PLACES);
    else
        ingame_log("label: the game's FREE PLAY left as it is: the client is not the build measured");
}
