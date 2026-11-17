/*
 * The sound's values in the game (ingame.h soundset_*): the master volume, the music's and the key sounds', the
 * equaliser (logic.h SoundValues), as the launcher started the game with them (OPENDMT3_SOUND_VALUES), changed in the
 * in-game sound panel, and kept in the one file the launcher's Sound page writes too (OPENDMT3_SOUND_FILE, sound.ini
 * beside the launcher's settings).
 *
 * Neither writer overwrites the other: each rewrites only the lines of the values it changed, under the file's lock
 * (sound.ini.lock, held open alone while one writes; Windows lets it go if the writer dies), on the file as it is at
 * that moment, through a temporary file swapped in. A change the launcher makes while the game runs is seen within half
 * a second and heard at once; one made here is in the file within a fifth of a second and on the launcher's page when
 * it reads the file again.
 *
 * The file's reads and writes run on a thread of their own: the game's thread only copies values in and out.
 */
#include "ingame.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* The values the game plays with now (the game's thread's own). */
static SoundValues g_now;
/* The file and its lock; empty: no file (the values live only for this run). */
static WCHAR g_path[MAX_PATH * 2], g_lock_path[MAX_PATH * 2], g_tmp_path[MAX_PATH * 2];
/* Between the game's thread and the file's: the values to write and which (a mask), the values another writer put in
 * the file and their count. */
static CRITICAL_SECTION g_cs;
static SoundValues g_to_write;
static unsigned g_write_mask;
static SoundValues g_theirs;
static LONG g_theirs_seq;
static LONG g_seen_seq;
static HANDLE g_wake;
/* Changed (by either side) since the panel last drew them. */
static LONG g_version;

/* --------------------------------------------------------------------------------------------- the file's side */

/* The file's lock, held alone: waited for up to a second (the other writer's write takes milliseconds). */
static HANDLE take_lock(void)
{
    for (int tries = 0; tries < 100; tries++) {
        HANDLE h = CreateFileW(g_lock_path, GENERIC_READ | GENERIC_WRITE, 0, NULL, OPEN_ALWAYS,
                               FILE_ATTRIBUTE_TEMPORARY | FILE_FLAG_DELETE_ON_CLOSE, NULL);
        if (h != INVALID_HANDLE_VALUE)
            return h;
        /* Held by the other writer: a moment later. Any other refusal: none to take. */
        if (GetLastError() != ERROR_SHARING_VIOLATION)
            return NULL;
        Sleep(10);
    }
    return NULL;
}

/* The file's text (empty when there is none yet), its last write's time into *when. */
static void read_file(char *text, int size, FILETIME *when)
{
    text[0] = 0;
    memset(when, 0, sizeof *when);
    HANDLE h = CreateFileW(g_path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL,
                           OPEN_EXISTING, 0, NULL);
    if (h == INVALID_HANDLE_VALUE)
        return;
    DWORD got = 0;
    if (ReadFile(h, text, (DWORD)size - 1, &got, NULL))
        text[got] = 0;
    GetFileTime(h, NULL, NULL, when);
    CloseHandle(h);
}

/* The file's last write's time, or zero. */
static FILETIME file_time(void)
{
    WIN32_FILE_ATTRIBUTE_DATA a;
    FILETIME none = {0, 0};
    return GetFileAttributesExW(g_path, GetFileExInfoStandard, &a) ? a.ftLastWriteTime : none;
}

/* Values the file holds that differ from ours, other than the ones being written: another writer's, published for
 * the game's thread. */
static void publish_theirs(const char *text, unsigned writing)
{
    EnterCriticalSection(&g_cs);
    SoundValues mine = g_theirs_seq ? g_theirs : g_now;
    SoundValues file = mine;
    unsigned named = sound_values_parse(text, &file);
    int differs = 0;
    for (int i = 0; i < SOUND_VALUES; i++)
        if ((named & (1u << i)) && !(writing & (1u << i)) && file.v[i] != mine.v[i]) {
            mine.v[i] = file.v[i];
            differs = 1;
        }
    if (differs) {
        g_theirs = mine;
        g_theirs_seq++;
    }
    LeaveCriticalSection(&g_cs);
}

/* Write the values asked for (only their lines), the file's other lines as they are now. */
static void write_now(FILETIME *seen)
{
    EnterCriticalSection(&g_cs);
    SoundValues v = g_to_write;
    unsigned mask = g_write_mask;
    g_write_mask = 0;
    LeaveCriticalSection(&g_cs);
    if (!mask)
        return;
    HANDLE lock = take_lock();
    if (!lock) {
        ingame_log("sound: the sound's file is held by another writer: not written this time");
        return;
    }
    static char old[4096], out[4096];
    FILETIME when;
    read_file(old, sizeof old, &when);
    /* What the other writer changed since we last looked comes to the game too. */
    publish_theirs(old, mask);
    int n = sound_values_merge(old, &v, mask, out, sizeof out);
    int ok = 0;
    if (n >= 0) {
        HANDLE h = CreateFileW(g_tmp_path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
        DWORD put = 0;
        if (h != INVALID_HANDLE_VALUE) {
            ok = WriteFile(h, out, (DWORD)n, &put, NULL) && put == (DWORD)n;
            CloseHandle(h);
        }
        /* Swapped in whole: a reader never meets half a file. */
        ok = ok && MoveFileExW(g_tmp_path, g_path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
    }
    *seen = file_time();
    CloseHandle(lock);
    ingame_log("sound: the sound's file %s (%d value%s)", ok ? "written" : "not written", __builtin_popcount(mask),
               __builtin_popcount(mask) == 1 ? "" : "s");
}

static DWORD WINAPI file_thread(LPVOID unused)
{
    (void)unused;
    FILETIME seen = file_time();
    for (;;) {
        /* Woken by a change of the game's, or every half second to look at the file. */
        if (WaitForSingleObject(g_wake, 500) == WAIT_OBJECT_0) {
            /* A slider drawn sends many: the ones within a fifth of a second go in one write. */
            Sleep(200);
            write_now(&seen);
            continue;
        }
        FILETIME now = file_time();
        if (CompareFileTime(&now, &seen) == 0)
            continue;
        seen = now;
        /* Written by the launcher (ours are seen at their write): its values come to the game. */
        static char text[4096];
        FILETIME when;
        read_file(text, sizeof text, &when);
        publish_theirs(text, 0);
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
    sound_values_default(&g_now);
    /* The values the launcher started the game with, in the file's names ("master_volume=80;eq_1k=-3;..."). */
    char given[512];
    DWORD got = GetEnvironmentVariableA("OPENDMT3_SOUND_VALUES", given, sizeof given);
    if (got && got < sizeof given) {
        for (char *p = given; *p; p++)
            if (*p == ';')
                *p = '\n';
        sound_values_parse(given, &g_now);
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
    _snwprintf(g_tmp_path, MAX_PATH * 2, L"%ls.tmp-ingame", g_path);
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
    LeaveCriticalSection(&g_cs);
    /* A value of ours still waiting to be written stays ours. */
    for (int i = 0; i < SOUND_VALUES; i++)
        if (!(g_write_mask & (1u << i)))
            g_now.v[i] = theirs.v[i];
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
    /* To the file, on its thread. */
    EnterCriticalSection(&g_cs);
    g_to_write = g_now;
    g_write_mask |= 1u << which;
    /* What the file's thread publishes later is ours from here on for this value. */
    g_theirs = g_theirs_seq ? g_theirs : g_now;
    g_theirs.v[which] = value;
    LeaveCriticalSection(&g_cs);
    SetEvent(g_wake);
}
