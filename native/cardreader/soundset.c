/*
 * The sound's values in the game (ingame.h soundset_*): the master volume, the music's and the key sounds', the
 * equaliser (logic.h SoundValues), as the launcher started the game with them (OPENDMT3_SOUND_VALUES), changed in the
 * in-game sound panel, and kept in the one file the launcher's Sound page writes too (OPENDMT3_SOUND_FILE, sound.ini
 * beside the launcher's settings).
 *
 * Neither writer overwrites the other: each rewrites only the lines of the values it changed, under the file's lock
 * (sound.ini.lock, held open alone while one writes; Windows lets it go if the writer dies), on the file as it is at
 * that moment, read whole, through a temporary file swapped in (sound.ini.tmp-ingame). A change the launcher makes while the game runs is
 * seen within half a second and heard at once; one made here is in the file within a fifth of a second and on the
 * launcher's page when it reads the file again.
 *
 * A write that fails (the lock held too long, the file read-only, another program holding it open, a disk full) keeps
 * its values to write: they are tried again every half second, said in the log once a run of failures and again when
 * they are written, and the game's quit tries a last time before the window goes (soundset_flush). Until written,
 * they stay the game's own: a value another writer put in the file never takes their place.
 *
 * The file's reads and writes run on a thread of their own: the game's thread only copies values in and out (and
 * waits for one write at its quit).
 */
#include "ingame.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* The longest file read: a sound.ini of a few hundred bytes, with room for any comments a player adds; a longer one is
 * not read or written (said in the log), never cut. */
#define SOUND_FILE_MAX (64 * 1024)
/* How long a writer waits for the other's lock (its write takes milliseconds). */
#define LOCK_WAIT_MS 1000

/* The values the game plays with now (the game's thread's own). */
static SoundValues g_now;
/* The file and its lock; empty: no file (the values live only for this run). */
static WCHAR g_path[MAX_PATH * 2], g_lock_path[MAX_PATH * 2];
/* Between the game's thread and the file's: the values to write and which (a mask, kept until they are written), the
 * values another writer put in the file and their count. */
static CRITICAL_SECTION g_cs;
static SoundValues g_to_write;
static unsigned g_write_mask;
static SoundValues g_theirs;
static LONG g_theirs_seq;
static LONG g_seen_seq;
static HANDLE g_wake;
/* One write at a time (the file's thread's, or the quit's). */
static CRITICAL_SECTION g_writing;
/* Failed writes in a row (the first said in the log, then the one that worked). */
static int g_failures;
/* Changed (by either side) since the panel last drew them. */
static LONG g_version;

/* --------------------------------------------------------------------------------------------- the file's side */

/* The file's lock, held alone: waited for up to LOCK_WAIT_MS (another writer holding it, or a lock file Windows is
 * still deleting, which refuses with "access denied" for that moment). NULL with the last error when not taken. */
static HANDLE take_lock(DWORD *error)
{
    DWORD start = GetTickCount();
    for (;;) {
        HANDLE h = CreateFileW(g_lock_path, GENERIC_READ | GENERIC_WRITE, 0, NULL, OPEN_ALWAYS,
                               FILE_ATTRIBUTE_TEMPORARY | FILE_FLAG_DELETE_ON_CLOSE, NULL);
        if (h != INVALID_HANDLE_VALUE)
            return h;
        *error = GetLastError();
        /* Held, or going: a moment later. Any other refusal (no folder, no rights): none to take. */
        if ((*error != ERROR_SHARING_VIOLATION && *error != ERROR_ACCESS_DENIED) || GetTickCount() - start > LOCK_WAIT_MS)
            return NULL;
        Sleep(10);
    }
}

/* The file's text, whole (a new buffer, NUL-ended; empty when there is none yet), or NULL with the error when it
 * cannot be read (or is longer than SOUND_FILE_MAX). Its last write's time into *when. */
static char *read_file(FILETIME *when, DWORD *error)
{
    memset(when, 0, sizeof *when);
    HANDLE h = CreateFileW(g_path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL,
                           OPEN_EXISTING, 0, NULL);
    if (h == INVALID_HANDLE_VALUE) {
        *error = GetLastError();
        /* No file yet: an empty text, the file is made at the first write. */
        return *error == ERROR_FILE_NOT_FOUND ? calloc(1, 1) : NULL;
    }
    LARGE_INTEGER size;
    char *text = NULL;
    if (!GetFileSizeEx(h, &size)) {
        *error = GetLastError();
    } else if (size.QuadPart > SOUND_FILE_MAX) {
        *error = ERROR_FILE_TOO_LARGE;
    } else if ((text = malloc((size_t)size.QuadPart + 1))) {
        DWORD got = 0;
        if (ReadFile(h, text, (DWORD)size.QuadPart, &got, NULL)) {
            text[got] = 0;
            GetFileTime(h, NULL, NULL, when);
        } else {
            *error = GetLastError();
            free(text);
            text = NULL;
        }
    }
    CloseHandle(h);
    return text;
}

/* The file's last write's time, or zero. */
static FILETIME file_time(void)
{
    WIN32_FILE_ATTRIBUTE_DATA a;
    FILETIME none = {0, 0};
    return GetFileAttributesExW(g_path, GetFileExInfoStandard, &a) ? a.ftLastWriteTime : none;
}

/* Values the file holds that differ from ours, other than the ones still to be written: another writer's, published
 * for the game's thread. A line naming a value with anything the rule does not take is said in the log, once a text. */
static void publish_theirs(const char *text)
{
    int refused = 0;
    const char *first = NULL;
    EnterCriticalSection(&g_cs);
    SoundValues mine = g_theirs_seq ? g_theirs : g_now;
    SoundValues file = mine;
    unsigned named = sound_values_parse(text, &file, &refused, &first);
    int differs = 0;
    for (int i = 0; i < SOUND_VALUES; i++)
        if ((named & (1u << i)) && !(g_write_mask & (1u << i)) && file.v[i] != mine.v[i]) {
            mine.v[i] = file.v[i];
            differs = 1;
        }
    if (differs) {
        g_theirs = mine;
        g_theirs_seq++;
    }
    LeaveCriticalSection(&g_cs);
    if (refused) {
        int len = (int)strcspn(first, "\r\n");
        ingame_log("sound: %d line%s of the sound file name%s a value with words the rule does not take, left as if "
                   "absent (the first: %.*s)", refused, refused == 1 ? "" : "s", refused == 1 ? "s" : "",
                   len > 60 ? 60 : len, first);
    }
}

int soundset_write_file(const WCHAR *path, const char *old, const SoundValues *v, unsigned mask, DWORD *error)
{
    /* The new text: the old one's lines, the changed values' rewritten. */
    size_t room = (old ? strlen(old) : 0) + SOUND_VALUES * 24 + 1;
    char *out = malloc(room);
    if (!out) {
        *error = ERROR_NOT_ENOUGH_MEMORY;
        return 0;
    }
    int n = sound_values_merge(old, v, mask, out, (int)room);
    int ok = 0;
    if (n < 0) {
        *error = ERROR_INSUFFICIENT_BUFFER;
    } else {
        /* Written beside it, then swapped in whole: a reader never meets half a file. */
        WCHAR tmp[MAX_PATH * 2 + 16];
        _snwprintf(tmp, MAX_PATH * 2 + 16, L"%ls.tmp-ingame", path);
        HANDLE h = CreateFileW(tmp, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
        DWORD put = 0;
        if (h == INVALID_HANDLE_VALUE) {
            *error = GetLastError();
        } else {
            ok = WriteFile(h, out, (DWORD)n, &put, NULL) && put == (DWORD)n;
            if (!ok)
                *error = GetLastError();
            CloseHandle(h);
        }
        if (ok && !MoveFileExW(tmp, path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
            *error = GetLastError();
            ok = 0;
        }
        /* A temporary left by a failure goes. */
        if (!ok)
            DeleteFileW(tmp);
    }
    free(out);
    return ok;
}

/* One try at writing what waits to be written: 1 when nothing waits after it. What it wrote leaves the mask only if
 * no newer change of the same value came meanwhile (that one waits for the next try). */
static int write_now(FILETIME *seen)
{
    EnterCriticalSection(&g_writing);
    EnterCriticalSection(&g_cs);
    SoundValues v = g_to_write;
    unsigned mask = g_write_mask;
    LeaveCriticalSection(&g_cs);
    if (!mask) {
        LeaveCriticalSection(&g_writing);
        return 1;
    }
    DWORD error = 0;
    int ok = 0;
    HANDLE lock = take_lock(&error);
    if (lock) {
        FILETIME when;
        char *old = read_file(&when, &error);
        if (old) {
            /* What the other writer changed since we last looked comes to the game too (not the values to write). */
            publish_theirs(old);
            ok = soundset_write_file(g_path, old, &v, mask, &error);
            free(old);
        }
        *seen = file_time();
        CloseHandle(lock);
    }
    EnterCriticalSection(&g_cs);
    if (ok) {
        /* Written: off the mask, unless the value changed again while it was written. */
        for (int i = 0; i < SOUND_VALUES; i++)
            if ((mask & (1u << i)) && g_to_write.v[i] == v.v[i])
                g_write_mask &= ~(1u << i);
    }
    unsigned left = g_write_mask;
    LeaveCriticalSection(&g_cs);
    if (!ok && !g_failures++)
        ingame_log("sound: the sound's file not written (error %lu: %s): its values kept, tried again every half "
                   "second", (unsigned long)error,
                   error == ERROR_SHARING_VIOLATION || error == ERROR_ACCESS_DENIED ? "held by another program, or read-only"
                   : error == ERROR_FILE_TOO_LARGE ? "longer than 64 KB" : "see the error");
    else if (ok) {
        ingame_log("sound: the sound's file written (%d value%s)%s", __builtin_popcount(mask),
                   __builtin_popcount(mask) == 1 ? "" : "s", g_failures ? " after it could not be for a while" : "");
        g_failures = 0;
    }
    LeaveCriticalSection(&g_writing);
    return !left;
}

static DWORD WINAPI file_thread(LPVOID unused)
{
    (void)unused;
    FILETIME seen = file_time();
    for (;;) {
        /* Woken by a change of the game's, or every half second: to try again what waits, or to look at the file. */
        if (WaitForSingleObject(g_wake, 500) == WAIT_OBJECT_0) {
            /* A slider drawn sends many: the ones within a fifth of a second go in one write. */
            Sleep(200);
            write_now(&seen);
            continue;
        }
        if (g_write_mask) {
            write_now(&seen);
            continue;
        }
        FILETIME now = file_time();
        if (CompareFileTime(&now, &seen) == 0)
            continue;
        seen = now;
        /* Written by the launcher (ours are seen at their write): its values come to the game. */
        FILETIME when;
        DWORD error = 0;
        char *text = read_file(&when, &error);
        if (text) {
            publish_theirs(text);
            free(text);
        }
    }
    return 0;
}

/* ------------------------------------------------------------------------------------------- the game's side */

/* Every value at work: the music's and the key sounds' buffers (sound.c), the master and the equaliser (mix.c). */
static void apply(void)
{
    sound_volumes(g_now.v[SOUND_MUSIC], g_now.v[SOUND_KEYS]);
    mix_set(&g_now);
    InterlockedIncrement(&g_version);
}

void soundset_start(void)
{
    static int started;
    if (started)
        return;
    started = 1;
    InitializeCriticalSection(&g_cs);
    InitializeCriticalSection(&g_writing);
    sound_values_default(&g_now);
    /* The values the launcher started the game with, in the file's names ("master_volume=80;eq_1k=-3;..."). */
    char given[512];
    DWORD got = GetEnvironmentVariableA("OPENDMT3_SOUND_VALUES", given, sizeof given);
    if (got && got < sizeof given) {
        for (char *p = given; *p; p++)
            if (*p == ';')
                *p = '\n';
        sound_values_parse(given, &g_now, NULL, NULL);
    }
    /* The game's buffers start from these (setting.ini has the same music and key sounds' volumes). */
    sound_volumes_start(g_now.v[SOUND_MUSIC], g_now.v[SOUND_KEYS]);
    mix_set(&g_now);
    ingame_log("sound: master %d %%, music %d %%, key sounds %d %%, equaliser %d %d %d %d %d dB", g_now.v[SOUND_MASTER],
               g_now.v[SOUND_MUSIC], g_now.v[SOUND_KEYS], g_now.v[SOUND_EQ0], g_now.v[SOUND_EQ0 + 1],
               g_now.v[SOUND_EQ0 + 2], g_now.v[SOUND_EQ0 + 3], g_now.v[SOUND_EQ0 + 4]);
    /* The file both write, with its lock and its temporary beside it. */
    DWORD n = GetEnvironmentVariableW(L"OPENDMT3_SOUND_FILE", g_path, MAX_PATH * 2);
    if (!n || n >= MAX_PATH * 2 - 16) {
        g_path[0] = 0;
        ingame_log("sound: no sound file given: the panel's changes last this run");
        return;
    }
    _snwprintf(g_lock_path, MAX_PATH * 2, L"%ls.lock", g_path);
    g_wake = CreateEventW(NULL, FALSE, FALSE, NULL);
    HANDLE t = g_wake ? CreateThread(NULL, 0, file_thread, NULL, 0, NULL) : NULL;
    if (t)
        CloseHandle(t);
    else
        g_path[0] = 0;
}

void soundset_frame(void)
{
    if (!g_path[0])
        return;
    /* Another writer's values (the launcher's page while the game runs): heard now. */
    if (g_theirs_seq == g_seen_seq)
        return;
    EnterCriticalSection(&g_cs);
    SoundValues theirs = g_theirs;
    g_seen_seq = g_theirs_seq;
    /* A value of ours still waiting to be written stays ours. */
    for (int i = 0; i < SOUND_VALUES; i++)
        if (!(g_write_mask & (1u << i)))
            g_now.v[i] = theirs.v[i];
    LeaveCriticalSection(&g_cs);
    ingame_log("sound: the sound's file changed: master %d %%, music %d %%, key sounds %d %%", g_now.v[SOUND_MASTER],
               g_now.v[SOUND_MUSIC], g_now.v[SOUND_KEYS]);
    apply();
}

const SoundValues *soundset_values(void)
{
    return &g_now;
}

long soundset_version(void)
{
    return g_version;
}

void soundset_change(int which, int value)
{
    value = sound_value_clamp(which, value);
    if (which < 0 || which >= SOUND_VALUES || g_now.v[which] == value)
        return;
    g_now.v[which] = value;
    apply();
    if (!g_path[0])
        return;
    /* To the file, on its thread; kept in the mask until written. */
    EnterCriticalSection(&g_cs);
    g_to_write = g_now;
    g_write_mask |= 1u << which;
    /* What the file's thread publishes later is ours from here on for this value. */
    g_theirs = g_theirs_seq ? g_theirs : g_now;
    g_theirs.v[which] = value;
    LeaveCriticalSection(&g_cs);
    SetEvent(g_wake);
}

int soundset_flush(void)
{
    /* Nothing to write, or no file: done. */
    if (!g_path[0] || !g_write_mask)
        return 1;
    /* The game is about to end: what waits is written now, tried for a second at most (the launcher reads the file
     * when the game closes). */
    FILETIME seen;
    DWORD start = GetTickCount();
    int done = write_now(&seen);
    while (!done && GetTickCount() - start < 1000) {
        Sleep(50);
        done = write_now(&seen);
    }
    if (!done)
        ingame_log("sound: the sound's file could not be written before the game ended: the panel's last changes are "
                   "this run's only");
    return done;
}
