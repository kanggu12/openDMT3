/*
 * The game's sound, followed (ingame.h, sound_*): which of its DirectSound buffers plays and how far, so the frame
 * clock can follow a song's music (OPENDMT3_PACING=music: the song's music is one buffer of minutes, played once from
 * its start). With OPENDMT3_SOUND_WATCH (measuring only), also its buffers' play and write cursors, to count underruns
 * (the play cursor overtaking what the game wrote, so stale sound plays) and to log when each stream starts against
 * the frame count, so the music's timing against the notes can be compared with the layer and without it.
 *
 * Nothing here changes sound data: the buffers' Unlock, Play, SetCurrentPosition, Stop and SetVolume are only noted on
 * their way to the real ones (during a hold's fade, a volume the game sets and a sound it starts get the fade's share
 * of their volume), and the cursors are read once a frame from the device's present. While the game is held still (the menu or the question
 * open during a song, hooks.c), the buffers playing are faded out over the hold's first eight frames and stopped, then
 * played again from the place the hold found them and faded in over the next eight frames: the music goes on from the
 * note it stopped at, in step with the frames, which stopped there too.
 *
 * The game writes each buffer through one Lock at its start and keeps writing its music into that memory as it plays
 * (measured: one Unlock a buffer in a whole session), so an underrun cannot be seen from its writes. It is seen from
 * the sound itself: each 20 ms block of a stream is read just before the play cursor reaches it, and a block that holds
 * exactly what it held a lap earlier (and is not silence) is stale sound about to play, which is what an underrun is. The DirectSound object the game makes is
 * the one hooks.c opened on the device the launcher chose.
 */
#include "ingame.h"

#include <mmsystem.h>
#include <dsound.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* IDirectSound8's and IDirectSoundBuffer's methods, by their place in the tables. */
#define M_CREATE_BUFFER 3
#define M_DUPLICATE_BUFFER 5
#define M_BUF_RELEASE 2
#define M_BUF_LOCK 11
#define M_BUF_PLAY 12
#define M_BUF_SET_POSITION 13
#define M_BUF_STOP 18
#define M_BUF_UNLOCK 19
#define M_BUF_SET_VOLUME 15
#define M_BUF_GET_FORMAT 5
#define M_BUF_SET_FORMAT 14
#define M_SET_COOPERATIVE 6
typedef HRESULT(STDMETHODCALLTYPE *CreateBufferFn)(IDirectSound8 *, LPCDSBUFFERDESC, LPDIRECTSOUNDBUFFER *, LPUNKNOWN);
typedef ULONG(STDMETHODCALLTYPE *ReleaseFn)(IDirectSoundBuffer *);
typedef HRESULT(STDMETHODCALLTYPE *PlayFn)(IDirectSoundBuffer *, DWORD, DWORD, DWORD);
typedef HRESULT(STDMETHODCALLTYPE *StopFn)(IDirectSoundBuffer *);
typedef HRESULT(STDMETHODCALLTYPE *SetPositionFn)(IDirectSoundBuffer *, DWORD);
static SetPositionFn real_set_position;
typedef HRESULT(STDMETHODCALLTYPE *UnlockFn)(IDirectSoundBuffer *, LPVOID, DWORD, LPVOID, DWORD);
static CreateBufferFn real_create;
typedef HRESULT(STDMETHODCALLTYPE *SetFormatFn)(IDirectSoundBuffer *, LPCWAVEFORMATEX);
static SetFormatFn real_set_format;
typedef HRESULT(STDMETHODCALLTYPE *CooperativeFn)(IDirectSound8 *, HWND, DWORD);
static CooperativeFn real_cooperative;
static ReleaseFn real_release;
static PlayFn real_play;
static StopFn real_stop;
static UnlockFn real_unlock;
typedef HRESULT(STDMETHODCALLTYPE *SetVolumeFn)(IDirectSoundBuffer *, LONG);
static SetVolumeFn real_set_volume;
/* The game's own volume changes, ruled by a hold's fades (below). */
static HRESULT STDMETHODCALLTYPE our_set_volume(IDirectSoundBuffer *b, LONG v);
/* A buffer the game plays while a fade in runs joins it (below). */
static void join_fade_in(IDirectSoundBuffer *b);
/* The game's copies of its buffers (its key sounds played over themselves): DuplicateSoundBuffer. */
typedef HRESULT(STDMETHODCALLTYPE *DuplicateFn)(IDirectSound8 *, LPDIRECTSOUNDBUFFER, LPDIRECTSOUNDBUFFER *);
static DuplicateFn real_duplicate;

/* One buffer the game made: its size, whether it plays round in a loop, the bytes played out of
 * it since its play began, the last play cursor read, and its underruns. */
typedef struct {
    IDirectSoundBuffer *buf;
    DWORD size, bytes_a_second;
    int looping, playing;
    int music;              /* a loop, or a buffer of a second or more: music (key sounds are short), its timing logged */
    LONGLONG played;
    DWORD last_cursor;
    LONG underruns;
    LONG started_frame;
    DWORD block;            /* bytes in a 20 ms block */
    DWORD *hash;            /* each block's content hash from the last lap (0: not seen yet) */
    DWORD checked;          /* the next block to read before the play cursor reaches it */
    LONG blocks_read, blocks_stale, blocks_changed;
} Watched;
/* Room for every buffer the game keeps at once, its copies too (a song's first 20 s: 1570 made, 1128 of them copies). */
#define WATCHED 4096
static Watched g_w[WATCHED];
/* Each buffer's slot by its address (logic.c's slot index): a DirectSound call finds its buffer in a step or two, where
 * a walk over the 4096 slots took up to 4096 (the game calls Play and Unlock for each key sound it plays). */
static SlotIndex g_index;
/* The free slots, a stack (filled on the first buffer: slot 0 on top). */
static int g_free[WATCHED], g_nfree = -1;
/* The slots of the music playing now (music, playing, its buffer alive), which is all the frame's own work looks at
 * (the lock to the music, its position, whether a song plays): a handful, where the 4096 slots were walked three times
 * a frame. g_music_at holds each slot's place in it plus one (0: not in it). */
static int g_music[WATCHED], g_nmusic, g_music_at[WATCHED];
/* The whole run's counts. */
static LONG g_buffers, g_underruns, g_plays;
/* Unlocks seen, and those on a buffer of the table (the game's writes). */
static LONG g_unlocks, g_unlocks_known;
static int g_watch;

/* The watched entry of a buffer, or NULL. */
static Watched *find(IDirectSoundBuffer *b)
{
    int slot = slot_index_get(&g_index, b);
    return slot >= 0 ? &g_w[slot] : NULL;
}

/* A slot in the list of the music playing, or out of it, as its entry says now (called wherever its buffer, its playing
 * or its being music changes). The list keeps the order slots came into it; a slot taken out leaves the last one in
 * its place. */
static void music_list(Watched *w)
{
    int slot = (int)(w - g_w);
    int in = w->buf && w->playing && w->music;
    if (in && !g_music_at[slot]) {
        g_music[g_nmusic] = slot;
        g_music_at[slot] = ++g_nmusic;
    } else if (!in && g_music_at[slot]) {
        int at = g_music_at[slot] - 1, last = g_music[--g_nmusic];
        g_music[at] = last;
        g_music_at[last] = at + 1;
        g_music_at[slot] = 0;
    }
}

/* Put `ours` in a method table's entry, keeping what was there (once: the game's buffers share one table). */
static void *swap(void *object, int index, void *ours)
{
    void **table = *(void ***)object;
    if (table[index] == ours)
        return NULL;
    void *was = table[index];
    DWORD old;
    if (!VirtualProtect(&table[index], sizeof(void *), PAGE_READWRITE, &old))
        return NULL;
    table[index] = ours;
    VirtualProtect(&table[index], sizeof(void *), old, &old);
    return was;
}

static ULONG STDMETHODCALLTYPE our_release(IDirectSoundBuffer *b)
{
    ULONG left = real_release(b);
    /* Gone: its entry free for the next buffer (an address may come back for a new one): out of the music playing, out
     * of the index, its slot back on the free stack. */
    if (left == 0) {
        Watched *w = find(b);
        if (w) {
            free(w->hash);
            memset(w, 0, sizeof *w);
            music_list(w);
            slot_index_del(&g_index, b);
            g_free[g_nfree++] = (int)(w - g_w);
        }
    }
    return left;
}

static HRESULT STDMETHODCALLTYPE our_unlock(IDirectSoundBuffer *b, LPVOID p1, DWORD n1, LPVOID p2, DWORD n2)
{
    /* What the game wrote: the bytes handed back from its Lock. */
    Watched *w = find(b);
    g_unlocks++;
    if (w)
        g_unlocks_known++;
    return real_unlock(b, p1, n1, p2, n2);
}

/* Plays of buffers the game's own DirectSound object did not make (another object in the process, as a video
 * library's own would be): counted, the first few logged with their size. */
static LONG g_foreign_plays;

static HRESULT STDMETHODCALLTYPE our_play(IDirectSoundBuffer *b, DWORD r, DWORD prio, DWORD flags)
{
    Watched *w = find(b);
    if (!w && g_watch && g_foreign_plays++ < 8) {
        DSBCAPS caps;
        caps.dwSize = sizeof caps;
        caps.dwBufferBytes = 0;
        IDirectSoundBuffer_GetCaps(b, &caps);
        ingame_log("sound: a buffer not made by the game's DirectSound object plays (%lu bytes%s) at frame %ld",
                   (unsigned long)caps.dwBufferBytes, (flags & DSBPLAY_LOOPING) ? ", a loop" : "", ingame_frame());
    }
    if (w) {
        /* A new play: the count of played bytes starts from its cursor. */
        DWORD play = 0, write = 0;
        IDirectSoundBuffer_GetCurrentPosition(b, &play, &write);
        w->looping = (flags & DSBPLAY_LOOPING) != 0;
        /* Music: what loops (the menus' streams) or lasts a second or more (a song's music in one buffer). */
        w->music = w->looping || (w->bytes_a_second && w->size >= w->bytes_a_second);
        if (!w->playing) {
            w->played = 0;
            w->last_cursor = play;
            /* A fresh lap of blocks: nothing to compare with yet. */
            if (w->hash)
                memset(w->hash, 0, (w->size / w->block + 1) * sizeof(DWORD));
            w->checked = w->block ? play / w->block : 0;
            w->started_frame = ingame_frame();
            g_plays++;
            /* Music: when each starts, against the frame count. */
            if (w->music && g_watch)
                ingame_log("sound: stream %p (%lu bytes, %lu a second, %s) plays from frame %ld", (void *)b,
                           (unsigned long)w->size, (unsigned long)w->bytes_a_second, w->looping ? "a loop" : "once",
                           (long)w->started_frame);
        }
        w->playing = 1;
        /* Music that plays: in the frame's list. */
        music_list(w);
    }
    /* Started while the music fades back in after a hold: at the fade's share, so it comes in with the rest. */
    join_fade_in(b);
    return real_play(b, r, prio, flags);
}

static HRESULT STDMETHODCALLTYPE our_set_position(IDirectSoundBuffer *b, DWORD to)
{
    /* The game moves the play cursor itself: counted from there, not as a lap of the ring. */
    HRESULT hr = real_set_position(b, to);
    Watched *w = find(b);
    if (w && SUCCEEDED(hr))
        w->last_cursor = to;
    return hr;
}

static HRESULT STDMETHODCALLTYPE our_stop(IDirectSoundBuffer *b)
{
    Watched *w = find(b);
    if (w && w->playing) {
        w->playing = 0;
        /* Stopped: out of the frame's list. */
        music_list(w);
        if (w->music && g_watch)
            ingame_log("sound: stream %p stops at frame %ld after %.0f ms played, %ld underruns", (void *)b,
                       (long)ingame_frame(), w->bytes_a_second ? (double)w->played * 1000.0 / w->bytes_a_second : 0.0,
                       (long)w->underruns);
    }
    return real_stop(b);
}

/* A wave format in words for the log (measuring only). */
static void format_words(const WAVEFORMATEX *f, char *out, size_t size)
{
    if (!f)
        snprintf(out, size, "none");
    else
        snprintf(out, size, "%lu Hz, %u bits, %u channels, tag %u", (unsigned long)f->nSamplesPerSec,
                 (unsigned)f->wBitsPerSample, (unsigned)f->nChannels, (unsigned)f->wFormatTag);
}

/* The game's own call to set the primary buffer's format (the format DirectSound mixes into), logged on its way. */
static HRESULT STDMETHODCALLTYPE our_set_format(IDirectSoundBuffer *b, LPCWAVEFORMATEX f)
{
    HRESULT hr = real_set_format(b, f);
    char words[96];
    format_words(f, words, sizeof words);
    ingame_log("sound: the game sets the primary buffer to %s: 0x%08lx", words, (unsigned long)hr);
    return hr;
}

static HRESULT STDMETHODCALLTYPE our_cooperative(IDirectSound8 *ds, HWND w, DWORD level)
{
    ingame_log("sound: the game's cooperative level %lu (1 normal, 2 priority, 3 exclusive, 4 write primary)",
               (unsigned long)level);
    return real_cooperative(ds, w, level);
}

/* Each different format of the game's buffers, once (measuring only). */
static void note_format(const DSBUFFERDESC *desc)
{
    static DWORD seen[16][3];
    static int count;
    if (!g_watch || !desc->lpwfxFormat)
        return;
    DWORD key[3] = {desc->lpwfxFormat->nSamplesPerSec, desc->lpwfxFormat->wBitsPerSample, desc->lpwfxFormat->nChannels};
    for (int i = 0; i < count; i++)
        if (!memcmp(seen[i], key, sizeof key))
            return;
    if (count < 16)
        memcpy(seen[count++], key, sizeof key);
    char words[96];
    format_words(desc->lpwfxFormat, words, sizeof words);
    ingame_log("sound: a buffer of the game's in %s (flags 0x%lx)", words, (unsigned long)desc->dwFlags);
}

/* How many of the buffers made were the game's copies of others, and how many found the table full (not followed). */
static LONG g_copies, g_unfollowed;

/* A buffer into the table: its size and rate, its 20 ms blocks (whole sample frames) and a hash for each, kept from one
 * lap to the next. A full table leaves it out (followed by nothing, held by no hold). */
static void watch_buffer(IDirectSoundBuffer *b, DWORD size, const WAVEFORMATEX *f)
{
    g_buffers++;
    /* No size known: nothing to follow round. */
    if (!size)
        return;
    /* The free stack, filled on the first buffer (slot 0 on top, as the walk found it first). */
    if (g_nfree < 0)
        for (g_nfree = 0; g_nfree < WATCHED; g_nfree++)
            g_free[g_nfree] = WATCHED - 1 - g_nfree;
    /* An address still in the table (its release not seen): its old entry let go first, so the new buffer is the one
     * found at it. */
    Watched *old = find(b);
    if (old) {
        free(old->hash);
        memset(old, 0, sizeof *old);
        music_list(old);
        g_free[g_nfree++] = (int)(old - g_w);
    }
    if (!g_nfree) {
        g_unfollowed++;
        return;
    }
    int i = g_free[--g_nfree];
    memset(&g_w[i], 0, sizeof g_w[i]);
    g_w[i].buf = b;
    g_w[i].size = size;
    g_w[i].bytes_a_second = f ? f->nAvgBytesPerSec : 0;
    DWORD align = f && f->nBlockAlign ? f->nBlockAlign : 4;
    g_w[i].block = g_w[i].bytes_a_second / 50 / align * align;
    if (g_w[i].block)
        g_w[i].hash = calloc(g_w[i].size / g_w[i].block + 1, sizeof(DWORD));
    /* Found by its address from now on. */
    slot_index_put(&g_index, b, i);
}

static HRESULT STDMETHODCALLTYPE our_create(IDirectSound8 *ds, LPCDSBUFFERDESC desc, LPDIRECTSOUNDBUFFER *out,
                                            LPUNKNOWN outer)
{
    HRESULT hr = real_create(ds, desc, out, outer);
    if (FAILED(hr) || !out || !*out || !desc)
        return hr;
    if (desc->dwFlags & DSBCAPS_PRIMARYBUFFER) {
        /* Measuring only: the primary buffer's format as made, and the game's own change to it. */
        if (g_watch) {
            WAVEFORMATEX f;
            DWORD got = 0;
            memset(&f, 0, sizeof f);
            char words[96] = "not read";
            if (SUCCEEDED(IDirectSoundBuffer_GetFormat(*out, &f, sizeof f, &got)))
                format_words(&f, words, sizeof words);
            ingame_log("sound: the primary buffer made, in %s", words);
            void *was = swap(*out, M_BUF_SET_FORMAT, (void *)our_set_format);
            if (was)
                real_set_format = (SetFormatFn)was;
        }
        return hr;
    }
    note_format(desc);
    /* The buffer's methods turned to ours (all the game's buffers share one table, its copies too). */
    void *was;
    if ((was = swap(*out, M_BUF_RELEASE, (void *)our_release)))
        real_release = (ReleaseFn)was;
    if ((was = swap(*out, M_BUF_PLAY, (void *)our_play)))
        real_play = (PlayFn)was;
    if ((was = swap(*out, M_BUF_SET_POSITION, (void *)our_set_position)))
        real_set_position = (SetPositionFn)was;
    if ((was = swap(*out, M_BUF_STOP, (void *)our_stop)))
        real_stop = (StopFn)was;
    if ((was = swap(*out, M_BUF_UNLOCK, (void *)our_unlock)))
        real_unlock = (UnlockFn)was;
    if ((was = swap(*out, M_BUF_SET_VOLUME, (void *)our_set_volume)))
        real_set_volume = (SetVolumeFn)was;
    watch_buffer(*out, desc->dwBufferBytes, desc->lpwfxFormat);
    return hr;
}

static HRESULT STDMETHODCALLTYPE our_duplicate(IDirectSound8 *ds, LPDIRECTSOUNDBUFFER original, LPDIRECTSOUNDBUFFER *out)
{
    HRESULT hr = real_duplicate(ds, original, out);
    if (FAILED(hr) || !out || !*out)
        return hr;
    /* A copy: the same sound with its own cursor and volume (the game plays a key sound over itself this way). Watched
     * as the buffers it makes are, so a hold stops and starts it too; its size and format asked of it. */
    DSBCAPS caps;
    caps.dwSize = sizeof caps;
    caps.dwBufferBytes = 0;
    IDirectSoundBuffer_GetCaps(*out, &caps);
    WAVEFORMATEX f;
    DWORD got = 0;
    memset(&f, 0, sizeof f);
    /* A format larger than a WAVEFORMATEX is not read: the copy is watched without its rate (no blocks to hash). */
    int known = SUCCEEDED(IDirectSoundBuffer_GetFormat(*out, &f, sizeof f, &got));
    watch_buffer(*out, caps.dwBufferBytes, known ? &f : NULL);
    g_copies++;
    return hr;
}

void sound_attach(void *direct_sound)
{
    /* Watching (its log lines and the underrun count) is for measuring (OPENDMT3_SOUND_WATCH): a player's game never
     * runs it. Following which buffers play is for the music lock and for holding the game still, so always. */
    char value[8];
    g_watch = GetEnvironmentVariableA("OPENDMT3_SOUND_WATCH", value, sizeof value) > 0;
    if (!direct_sound)
        return;
    void *was = swap(direct_sound, M_CREATE_BUFFER, (void *)our_create);
    if (was)
        real_create = (CreateBufferFn)was;
    /* Its copies of its buffers too: a song's key sounds are copies, and a hold holds them with the music. */
    if ((was = swap(direct_sound, M_DUPLICATE_BUFFER, (void *)our_duplicate)))
        real_duplicate = (DuplicateFn)was;
    if (g_watch) {
        if ((was = swap(direct_sound, M_SET_COOPERATIVE, (void *)our_cooperative)))
            real_cooperative = (CooperativeFn)was;
        ingame_log("sound: watching the game's buffers (frame %ld; nothing has played yet)", (long)ingame_frame());
    }
}

/* Read how far each music buffer has played (its play cursor's advance since the last read, round the ring). */
static void follow(Watched *w)
{
    DWORD play = 0, write = 0;
    /* A buffer of no known size has no ring to go round. */
    if (!w->size || FAILED(IDirectSoundBuffer_GetCurrentPosition(w->buf, &play, &write)))
        return;
    w->played += (LONGLONG)((play + w->size - w->last_cursor) % w->size);
    w->last_cursor = play;
}

/* After a hold: the buffers played again, their volume coming back over the next frames (the fade in). `volume` is the
 * game's own (read when the hold began, or set by the game during a fade), `k` the share of it the fade gives now. */
typedef struct {
    IDirectSoundBuffer *buf;
    DWORD at, flags;
    LONG volume;
    double k;
    int ramp;
    int stopped;
} Held;
/* Room for the music and the key sounds playing over it at a hold, and those started while it fades back in. */
#define HELD 64
static Held g_held[HELD];
/* The fade in's frames still to go after a hold, and the fade out's while one begins (a step a frame, eight of them:
 * 133 ms, each step an eighth of the music's level, too small a change to click). */
static int g_nheld, g_ramp_frames, g_fade_frames;
#define RAMP_FRAMES 8
/* How often the game set a held buffer's volume itself during a fade, and how many buffers it started during a fade
 * in (for the log). */
static LONG g_game_volume_calls, g_joined;

/* The performance counter's time in seconds, for the log (the recording of the Wine tests is timed by the same clock). */
static double counter_s(void)
{
    LARGE_INTEGER t, f;
    QueryPerformanceCounter(&t);
    QueryPerformanceFrequency(&f);
    return (double)t.QuadPart / (double)f.QuadPart;
}

/* DirectSound's volume (hundredths of a decibel, 0 the buffer's own, -10000 silence) for a share k of a base volume. */
static LONG volume_at(LONG base, double k)
{
    if (k <= 0.001)
        return DSBVOLUME_MIN;
    double v = (double)base + 2000.0 * log10(k);
    return v < DSBVOLUME_MIN ? DSBVOLUME_MIN : (LONG)v;
}

/* A held buffer at a share k of the game's own volume, through the real SetVolume (not the hook, which would take the
 * call for the game's). */
static void set_share(Held *h, double k)
{
    h->k = k;
    if (!h->ramp)
        return;
    LONG v = volume_at(h->volume, k);
    if (real_set_volume)
        real_set_volume(h->buf, v);
    else
        IDirectSoundBuffer_SetVolume(h->buf, v);
}

static HRESULT STDMETHODCALLTYPE our_set_volume(IDirectSoundBuffer *b, LONG v)
{
    /* During a fade, the game's own volume for a held buffer becomes the fade's goal, and the fade's share of it is what
     * plays: the game sets its sounds' volumes while they play (16 or 17 times over a song's fade in: measured), which
     * would otherwise undo the fade's step. */
    if (g_ramp_frames || g_fade_frames)
        for (int i = 0; i < g_nheld; i++)
            if (g_held[i].buf == b) {
                g_game_volume_calls++;
                g_held[i].volume = v;
                return real_set_volume(b, volume_at(v, g_held[i].k));
            }
    return real_set_volume(b, v);
}

/* The fade in after a hold, a step a frame; the buffers let go when it is done. */
static void ramp_step(void)
{
    if (!g_ramp_frames)
        return;
    g_ramp_frames--;
    double k = (double)(RAMP_FRAMES - g_ramp_frames) / RAMP_FRAMES;
    for (int i = 0; i < g_nheld; i++)
        set_share(&g_held[i], k);
    if (!g_ramp_frames) {
        ingame_log("sound: faded in over %d frames at frame %ld (the game started %ld sounds and set a held buffer's "
                   "volume %ld times meanwhile)", RAMP_FRAMES, ingame_frame(), (long)g_joined,
                   (long)g_game_volume_calls);
        for (int i = 0; i < g_nheld; i++)
            IDirectSoundBuffer_Release(g_held[i].buf);
        g_nheld = 0;
    }
}

static void join_fade_in(IDirectSoundBuffer *b)
{
    /* Only while a fade in runs, once for each buffer, while there is room. */
    if (!g_ramp_frames || g_nheld >= HELD)
        return;
    for (int i = 0; i < g_nheld; i++)
        if (g_held[i].buf == b)
            return;
    Held *h = &g_held[g_nheld++];
    memset(h, 0, sizeof *h);
    h->buf = b;
    /* Kept alive until the fade in is done, as the held ones are. */
    IDirectSoundBuffer_AddRef(b);
    /* The volume the game gave it, at the share the held ones have reached; up with them from the next frame. */
    h->ramp = SUCCEEDED(IDirectSoundBuffer_GetVolume(b, &h->volume));
    set_share(h, (double)(RAMP_FRAMES - g_ramp_frames) / RAMP_FRAMES);
    g_joined++;
}

int sound_song_playing(void)
{
    /* A song's music: a buffer of 10 s or more played once (sound_music_position's rule), as the hooks saw it (such a
     * buffer is music: it lasts a second or more). */
    for (int k = 0; k < g_nmusic; k++) {
        Watched *w = &g_w[g_music[k]];
        if (w->buf && w->playing && !w->looping && w->bytes_a_second && w->size >= 10 * w->bytes_a_second)
            return 1;
    }
    return 0;
}

void sound_hold(void)
{
    /* A fade in still running from the last hold: finished at once (its buffers let go). */
    while (g_ramp_frames)
        ramp_step();
    g_nheld = 0;
    if (!real_stop || !real_play || !real_set_position)
        return;
    for (int i = 0; i < WATCHED && g_nheld < HELD; i++) {
        Watched *w = &g_w[i];
        DWORD status = 0;
        if (!w->buf || !w->playing || FAILED(IDirectSoundBuffer_GetStatus(w->buf, &status)) ||
            !(status & DSBSTATUS_PLAYING))
            continue;
        memset(&g_held[g_nheld], 0, sizeof g_held[g_nheld]);
        /* Its place now, counted into how far it has played (the music lock's count goes on from it). */
        follow(w);
        Held *h = &g_held[g_nheld++];
        h->buf = w->buf;
        /* Kept alive until the fade in is done, whatever the game does with it meanwhile. */
        IDirectSoundBuffer_AddRef(w->buf);
        h->at = w->last_cursor;
        h->flags = status & DSBSTATUS_LOOPING ? DSBPLAY_LOOPING : 0;
        h->volume = 0;
        h->ramp = SUCCEEDED(IDirectSoundBuffer_GetVolume(w->buf, &h->volume));
    }
    /* The fade out: a step a frame over the hold's first frames (a cut mid-wave would click), the first now; then each
     * is stopped through the real Stop, so the watch still counts it as playing. The music plays on a little past the
     * place kept, faded: it is set back there when the game goes on. */
    for (int i = 0; i < g_nheld; i++)
        g_held[i].k = 1.0;
    g_game_volume_calls = 0;
    g_joined = 0;
    g_fade_frames = RAMP_FRAMES;
    sound_hold_step();
    for (int i = 0; i < g_nheld; i++) {
        Held *h = &g_held[i];
        DSBCAPS caps;
        caps.dwSize = sizeof caps;
        caps.dwBufferBytes = 0;
        IDirectSoundBuffer_GetCaps(h->buf, &caps);
        ingame_log("sound: held %p (%lu bytes, %s, volume %ld%s) at byte %lu", (void *)h->buf,
                   (unsigned long)caps.dwBufferBytes, h->flags & DSBPLAY_LOOPING ? "a loop" : "once", (long)h->volume,
                   h->ramp ? "" : ", no volume control", (unsigned long)h->at);
    }
    ingame_log("sound: %d buffers held at frame %ld (%.3f s by the counter)", g_nheld, ingame_frame(), counter_s());
}

void sound_hold_step(void)
{
    if (!g_fade_frames)
        return;
    g_fade_frames--;
    /* Seven eighths, six, down to none, then the stop. */
    double k = (double)g_fade_frames / RAMP_FRAMES;
    for (int i = 0; i < g_nheld; i++) {
        Held *h = &g_held[i];
        set_share(h, k);
        if (!g_fade_frames && !h->stopped) {
            real_stop(h->buf);
            h->stopped = 1;
        }
    }
}

void sound_resume(int play)
{
    /* A hold shorter than its fade: the fade's last step now (silent, stopped). */
    while (g_fade_frames)
        sound_hold_step();
    for (int i = 0; i < g_nheld; i++) {
        Held *h = &g_held[i];
        Watched *w = find(h->buf);
        if (play) {
            /* Back to where the hold found it (the fade out played on a little past it), silent, playing again. */
            real_set_position(h->buf, h->at);
            if (w)
                w->last_cursor = h->at;
            set_share(h, 0.0);
            real_play(h->buf, 0, 0, h->flags);
        } else {
            /* Quitting: only its own volume back. */
            set_share(h, 1.0);
        }
    }
    if (play && g_nheld) {
        /* The fade in over the next frames. */
        g_ramp_frames = RAMP_FRAMES;
        ingame_log("sound: %d buffers going on from where they stopped at frame %ld (%.3f s by the counter)", g_nheld,
                   ingame_frame(), counter_s());
    } else {
        for (int i = 0; i < g_nheld; i++)
            IDirectSoundBuffer_Release(g_held[i].buf);
        g_nheld = 0;
    }
}

int sound_music_position(double *ms, long *started_frame)
{
    /* The song's music: a buffer of 10 s or more played once (the menus' music loops, a key sound is short); the one
     * started last, when two overlap. */
    Watched *best = NULL;
    for (int k = 0; k < g_nmusic; k++) {
        Watched *w = &g_w[g_music[k]];
        if (!w->buf || !w->playing || w->looping || !w->bytes_a_second || w->size < 10 * w->bytes_a_second)
            continue;
        /* Two started on the same frame: the lower slot, as the walk over the slots found it first. */
        if (!best || w->started_frame > best->started_frame || (w->started_frame == best->started_frame && w < best))
            best = w;
    }
    if (!best)
        return 0;
    /* Read now (the frame's own read comes later in it): the position this frame is paced against. */
    follow(best);
    *ms = (double)best->played * 1000.0 / (double)best->bytes_a_second;
    *started_frame = best->started_frame;
    return 1;
}

/* FNV-1a over a block's bytes. */
static DWORD hash_of(const BYTE *p, DWORD n, int *silent)
{
    DWORD h = 2166136261u;
    *silent = 1;
    for (DWORD i = 0; i < n; i++) {
        h = (h ^ p[i]) * 16777619u;
        /* Silence (every byte the same) repeats legitimately: never called stale. */
        if (p[i] != p[0])
            *silent = 0;
    }
    return h ? h : 1;
}

/* Read block `k` of a stream (as the sound card is about to): stale if it holds what it held a lap ago. */
static void check_block(Watched *w, DWORD k)
{
    void *p1 = NULL, *p2 = NULL;
    DWORD n1 = 0, n2 = 0;
    /* A read-only look through Lock; its Unlock goes straight to the real one (it is not a write of the game's). */
    if (FAILED(IDirectSoundBuffer_Lock(w->buf, k * w->block, w->block, &p1, &n1, &p2, &n2, 0)) || !p1)
        return;
    int silent = 1;
    DWORD h = hash_of(p1, n1, &silent);
    real_unlock(w->buf, p1, n1, p2, n2);
    w->blocks_read++;
    /* Compared only from the second lap on (a first lap has nothing before it). */
    if (w->hash[k] && w->hash[k] != h)
        w->blocks_changed++;
    /* Stale: the same sound as a lap ago in a stream the game writes into (some block of it changed between laps). A
     * buffer whose blocks never change is a loop played as it is, not a stream: its repeats are not underruns. */
    if (!silent && w->hash[k] == h && w->blocks_changed > 0) {
        w->blocks_stale++;
        w->underruns++;
        g_underruns++;
        ingame_log("sound: underrun on stream %p at frame %ld: block %lu holds what it held a lap ago", (void *)w->buf,
                   (long)ingame_frame(), (unsigned long)k);
    }
    w->hash[k] = h;
}

void sound_frame(void)
{
    ramp_step();
    if (!g_watch && !g_settings.music_lock)
        return;
    for (int k = 0; k < g_nmusic; k++) {
        Watched *w = &g_w[g_music[k]];
        if (!w->buf || !w->playing || !w->music || !w->size)
            continue;
        /* The play cursor's advance since the last frame. */
        follow(w);
        DWORD play = w->last_cursor;
        /* Underruns are measuring only. */
        if (!g_watch)
            continue;
        /* A loop's blocks the play cursor reaches within the next 40 ms, each read once a lap, before it plays (a buffer
         * played once holds all its sound before it starts: nothing to underrun). */
        if (!w->hash || !w->block || !w->looping)
            continue;
        DWORD blocks = w->size / w->block, ahead = (play / w->block + 2) % blocks;
        while (w->checked != ahead) {
            check_block(w, w->checked);
            w->checked = (w->checked + 1) % blocks;
        }
    }
}

void sound_summary(void)
{
    if (!g_watch)
        return;
    /* Every stream playing now: how far it is (in ms) and against which frame it started. */
    int streams = 0;
    for (int k = 0; k < g_nmusic; k++) {
        Watched *w = &g_w[g_music[k]];
        if (!w->buf || !w->playing || !w->music)
            continue;
        streams++;
        ingame_log("sound: stream %p at frame %ld: %.1f ms played since frame %ld; %ld blocks read before playing, %ld changed since their last lap, %ld stale",
                   (void *)w->buf, (long)ingame_frame(),
                   w->bytes_a_second ? (double)w->played * 1000.0 / w->bytes_a_second : 0.0, (long)w->started_frame,
                   (long)w->blocks_read, (long)w->blocks_changed, (long)w->blocks_stale);
    }
    ingame_log("sound: %ld buffers made (%ld of them copies, %ld not followed), %ld plays, %d streams playing, underruns "
               "%ld (%ld writes, %ld on known buffers; %ld plays of other buffers)", (long)g_buffers, (long)g_copies,
               (long)g_unfollowed, (long)g_plays, streams, (long)g_underruns, (long)g_unlocks, (long)g_unlocks_known,
               (long)g_foreign_plays);
}
