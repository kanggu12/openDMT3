/*
 * The methods openDMT3 puts in Direct3D's method tables, watched and put back (methods.h).
 */
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

#include "methods.h"

/* One watched entry, and how many times it was put back. */
typedef struct {
    void **entry;
    void *ours;
    const char *name;
    int index;
    long times;
} Watched;
static Watched g_watched[METHODS_MOST];
/* Watched entries; their adding and the looks both come on the game's own thread (its device's making and its frames),
 * but the count is written after its entry, so a look never meets half of one. */
static volatile LONG g_count;

/* Whether an address lies in a loaded module's image (a library's or the game's): such a table lives as long as its
 * module, which the game never lets go, so reading it at any time is safe. */
static int in_image(const void *p)
{
    HMODULE m = NULL;
    return GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                              (LPCWSTR)p, &m) && m;
}

int methods_write(void **entry, void *value)
{
    DWORD old;
    /* The tables are in read-only memory: writable for the one write, then as they were (as every patch here does). */
    if (!VirtualProtect(entry, sizeof *entry, PAGE_READWRITE, &old))
        return 0;
    *(void *volatile *)entry = value;
    VirtualProtect(entry, sizeof *entry, old, &old);
    return 1;
}

int methods_watch(void **entry, void *ours, const char *name, int index)
{
    LONG n = g_count;
    for (LONG i = 0; i < n; i++) {
        if (g_watched[i].entry != entry)
            continue;
        /* Watched already: another of openDMT3's methods over the first (it calls that one), so it is the one kept. */
        g_watched[i].ours = ours;
        g_watched[i].name = name;
        return 1;
    }
    /* No room, or a table that could go with its object: not watched. */
    if (n >= METHODS_MOST || !in_image(entry))
        return 0;
    g_watched[n].entry = entry;
    g_watched[n].ours = ours;
    g_watched[n].name = name;
    g_watched[n].index = index;
    g_watched[n].times = 0;
    /* The entry whole before a look can count it. */
    InterlockedExchange(&g_count, n + 1);
    return 1;
}

/* Whether this time is worth a line: the 1st, the 10th, the 100th... (one table filled in again each frame would say
 * so a few times, never once a frame). */
static int worth_saying(long times)
{
    while (times >= 10 && times % 10 == 0)
        times /= 10;
    return times == 1;
}

int methods_check(MethodBack *out, int room, int *noted)
{
    int back = 0, n = 0;
    LONG count = g_count;
    for (LONG i = 0; i < count; i++) {
        Watched *w = &g_watched[i];
        /* Read as it is now (Direct3D may have written it since the last look). */
        void *now = *(void *volatile *)w->entry;
        if (now == w->ours)
            continue;
        /* Not openDMT3's: put back. The real method openDMT3's calls stays the one it kept when it turned the entry. */
        if (!methods_write(w->entry, w->ours))
            continue;
        back++;
        w->times++;
        if (n < room && worth_saying(w->times)) {
            out[n].name = w->name;
            out[n].index = w->index;
            out[n].held = now;
            out[n].times = w->times;
            n++;
        }
    }
    if (noted)
        *noted = n;
    return back;
}
