/*
 * The last stage of the game's sound (ingame.h mix_*): the master volume and the equaliser the player sets (the 0.4.0
 * list's #11), on the mix itself as it goes to Windows, whichever mixer made it.
 *
 * Every mixer the launcher offers writes its mix through Windows' audio client in this process: Windows' own
 * DirectSound (dsound.dll mixes the game's buffers into a WASAPI stream of its own), and OpenAL Soft behind DSOAL, in
 * shared or in exclusive mode (its WASAPI backend). Each asks its IAudioRenderClient for room (GetBuffer), writes the
 * mix there and hands it on (ReleaseBuffer). Those two methods, the audio client's Initialize and GetService that say
 * each stream's format, and both objects' Release (a stream torn down leaves the table), sit in tables every such
 * object of the process shares: they are turned to ours once, before the game opens its sound (mix_install, from
 * hooks.c's DirectSound open), so the mix is shaped in place between its writing and its hand-over. Nothing is added to
 * the way: no buffer of ours, no frame later; the stage's own time is measured and logged with the caller that wrote
 * the mix (the proof of which mixer it was).
 *
 * At 100 % and flat nothing is touched. 32-bit float, 16-bit, packed 24-bit and 32-bit samples are shaped; any other
 * format, or more than eight channels, passes as it is, said once in the log. The log lines are written from the
 * game's thread (mix_frame): a mixer's thread never waits for a file.
 */
#define COBJMACROS
#include "ingame.h"

#include <mmsystem.h>
#include <mmdeviceapi.h>
#include <audioclient.h>
#include <stdio.h>
#include <string.h>

/* The tables' places: both objects' Release, IAudioClient's Initialize and GetService, IAudioRenderClient's GetBuffer
 * and ReleaseBuffer. */
#define M_RELEASE 2
#define M_CLIENT_INITIALIZE 3
#define M_CLIENT_GET_SERVICE 14
#define M_RENDER_GET_BUFFER 3
#define M_RENDER_RELEASE_BUFFER 4

typedef ULONG(STDMETHODCALLTYPE *ReleaseFn)(IUnknown *);
typedef HRESULT(STDMETHODCALLTYPE *InitializeFn)(IAudioClient *, AUDCLNT_SHAREMODE, DWORD, REFERENCE_TIME,
                                                 REFERENCE_TIME, const WAVEFORMATEX *, LPCGUID);
typedef HRESULT(STDMETHODCALLTYPE *GetServiceFn)(IAudioClient *, REFIID, void **);
typedef HRESULT(STDMETHODCALLTYPE *GetBufferFn)(IAudioRenderClient *, UINT32, BYTE **);
typedef HRESULT(STDMETHODCALLTYPE *ReleaseBufferFn)(IAudioRenderClient *, UINT32, DWORD);
/* The real methods, each stored before its table's entry is turned to ours (a mixer's thread may call at once). */
static ReleaseFn volatile real_client_release;
static ReleaseFn volatile real_render_release;
static InitializeFn volatile real_initialize;
static GetServiceFn volatile real_get_service;
static GetBufferFn volatile real_get_buffer;
static ReleaseBufferFn volatile real_release_buffer;

/* The sample kinds the stage shapes. */
enum { KIND_NONE = 0, KIND_FLOAT, KIND_S16, KIND_S24, KIND_S32 };

/* One stream: its audio client and render client, its format, the room GetBuffer handed out, its filters' state. */
typedef struct {
    int used;              /* a stream of a live client (0: a free place) */
    IAudioClient *client;
    IAudioRenderClient *render;
    int kind, channels, rate, exclusive;
    BYTE *data;            /* the room the last GetBuffer gave (written by the mixer, shaped at its release) */
    MixState state;
    int version;           /* the values' version its shape was made for */
    MixShape shape;
    ULONGLONG last_use;    /* when its mix last passed (a full table gives the longest unused place to a new one) */
    char writer[48];       /* the module that wrote its first mix (dsound.dll, the OpenAL library) */
    int said;              /* its first pass said in the log */
    unsigned said_dropped; /* the bands said in the log as left off at its rate */
} Stream;
/* Room for every stream a game opens and opens again (a device change, an OpenAL Soft reopen); a stream torn down
 * leaves it, and a full table hands the longest unused place to a new stream (said in the log). */
#define STREAMS 64
static Stream g_streams[STREAMS];
static SRWLOCK g_lock = SRWLOCK_INIT;
/* Places taken from a stream still in the table because it was full: said in the log by the game's thread. */
static volatile LONG g_recycled;

/* The values (set by the game's thread, read by the mixers' threads) and their version. */
static SoundValues g_values;
static volatile LONG g_version;
static int g_have_values;

/* The stage's own time: buffers shaped and passed, the counter's ticks spent, the longest; frames shaped. */
static volatile LONG g_shaped, g_passed;
static volatile LONGLONG g_ticks, g_longest, g_frames;
static LARGE_INTEGER g_frequency;

/* ------------------------------------------------------------------------------------------------ the streams */

/* The sample kind of a format: float, or 16, 24 (packed) or 32-bit whole numbers (an extensible format by its
 * subformat's first part: 3 float, 1 PCM; a 24-bit sample in 32 bits is a 32-bit one, its low byte zero). */
static int kind_of(const WAVEFORMATEX *f)
{
    WORD tag = f->wFormatTag;
    if (tag == WAVE_FORMAT_EXTENSIBLE && f->cbSize >= 22)
        tag = (WORD)((const WAVEFORMATEXTENSIBLE *)f)->SubFormat.Data1;
    if (tag == 3 && f->wBitsPerSample == 32)
        return KIND_FLOAT;
    if (tag == WAVE_FORMAT_PCM && f->wBitsPerSample == 16)
        return KIND_S16;
    if (tag == WAVE_FORMAT_PCM && f->wBitsPerSample == 24)
        return KIND_S24;
    if (tag == WAVE_FORMAT_PCM && f->wBitsPerSample == 32)
        return KIND_S32;
    return KIND_NONE;
}

static const char *const KIND_NAMES[] = {"a format not shaped", "32-bit float", "16-bit", "24-bit", "32-bit"};

/* A stream by its render client (under the lock): a live one only. */
static Stream *by_render(IAudioRenderClient *r)
{
    for (int i = 0; i < STREAMS; i++)
        if (g_streams[i].used && g_streams[i].render == r)
            return &g_streams[i];
    return NULL;
}

/* The place for a client's stream (under the lock held alone): its own, a free one, or the longest unused. */
static Stream *place_for(IAudioClient *c)
{
    Stream *free_place = NULL, *oldest = NULL;
    for (int i = 0; i < STREAMS; i++) {
        Stream *s = &g_streams[i];
        if (s->used && s->client == c)
            return s;
        if (!s->used && !free_place)
            free_place = s;
        if (s->used && (!oldest || s->last_use < oldest->last_use))
            oldest = s;
    }
    if (free_place)
        return free_place;
    InterlockedIncrement(&g_recycled);
    return oldest;
}

static ULONG STDMETHODCALLTYPE our_client_release(IUnknown *o)
{
    ULONG left = real_client_release(o);
    /* Gone: its stream leaves the table, so a new client at the same address starts as a new stream. */
    if (!left) {
        AcquireSRWLockExclusive(&g_lock);
        for (int i = 0; i < STREAMS; i++)
            if (g_streams[i].used && g_streams[i].client == (IAudioClient *)o)
                memset(&g_streams[i], 0, sizeof g_streams[i]);
        ReleaseSRWLockExclusive(&g_lock);
    }
    return left;
}

static ULONG STDMETHODCALLTYPE our_render_release(IUnknown *o)
{
    ULONG left = real_render_release(o);
    /* Gone: no stream's writes come through that address any more (a new render client there is another stream's). */
    if (!left) {
        AcquireSRWLockExclusive(&g_lock);
        for (int i = 0; i < STREAMS; i++)
            if (g_streams[i].render == (IAudioRenderClient *)o)
                g_streams[i].render = NULL;
        ReleaseSRWLockExclusive(&g_lock);
    }
    return left;
}

static HRESULT STDMETHODCALLTYPE our_initialize(IAudioClient *c, AUDCLNT_SHAREMODE mode, DWORD flags,
                                                REFERENCE_TIME duration, REFERENCE_TIME period,
                                                const WAVEFORMATEX *f, LPCGUID session)
{
    HRESULT hr = real_initialize(c, mode, flags, duration, period, f, session);
    if (FAILED(hr) || !f)
        return hr;
    AcquireSRWLockExclusive(&g_lock);
    /* The client's format kept, a new stream's filters starting from rest. */
    Stream *s = place_for(c);
    memset(s, 0, sizeof *s);
    s->used = 1;
    s->client = c;
    s->kind = f->nChannels <= MIX_CHANNELS ? kind_of(f) : KIND_NONE;
    s->channels = f->nChannels;
    s->rate = (int)f->nSamplesPerSec;
    s->exclusive = mode == AUDCLNT_SHAREMODE_EXCLUSIVE;
    s->version = -1;
    s->last_use = GetTickCount64();
    ReleaseSRWLockExclusive(&g_lock);
    return hr;
}

static HRESULT STDMETHODCALLTYPE our_get_service(IAudioClient *c, REFIID riid, void **out)
{
    HRESULT hr = real_get_service(c, riid, out);
    if (FAILED(hr) || !out || !*out || !IsEqualIID(riid, &IID_IAudioRenderClient))
        return hr;
    /* The render client of a client whose format is kept: its writes are that stream's, and no other stream's (one
     * whose render client was at that address before, not yet seen gone). */
    AcquireSRWLockExclusive(&g_lock);
    for (int i = 0; i < STREAMS; i++)
        if (g_streams[i].render == (IAudioRenderClient *)*out)
            g_streams[i].render = NULL;
    for (int i = 0; i < STREAMS; i++)
        if (g_streams[i].used && g_streams[i].client == c)
            g_streams[i].render = (IAudioRenderClient *)*out;
    ReleaseSRWLockExclusive(&g_lock);
    return hr;
}

static HRESULT STDMETHODCALLTYPE our_get_buffer(IAudioRenderClient *r, UINT32 frames, BYTE **data)
{
    HRESULT hr = real_get_buffer(r, frames, data);
    /* The room handed out, for its release. */
    AcquireSRWLockShared(&g_lock);
    Stream *s = by_render(r);
    if (s)
        s->data = SUCCEEDED(hr) && data ? *data : NULL;
    ReleaseSRWLockShared(&g_lock);
    return hr;
}

/* Each 24-bit sample (three bytes) through the shape, by way of 32 bits. */
static void run_s24(Stream *s, BYTE *p, UINT32 frames)
{
    int32_t block[256];
    UINT32 total = frames * (UINT32)s->channels;
    for (UINT32 at = 0; at < total;) {
        /* Whole frames a block (256 samples hold at least 32 of eight channels). */
        UINT32 n = total - at < 256 ? total - at : 256 / (UINT32)s->channels * (UINT32)s->channels;
        for (UINT32 i = 0; i < n; i++) {
            BYTE *b = p + (at + i) * 3;
            block[i] = (int32_t)((uint32_t)b[0] << 8 | (uint32_t)b[1] << 16 | (uint32_t)b[2] << 24);
        }
        mix_run_s32(&s->shape, &s->state, block, (int)(n / (UINT32)s->channels), s->channels);
        for (UINT32 i = 0; i < n; i++) {
            BYTE *b = p + (at + i) * 3;
            uint32_t v = (uint32_t)block[i];
            b[0] = (BYTE)(v >> 8);
            b[1] = (BYTE)(v >> 16);
            b[2] = (BYTE)(v >> 24);
        }
        at += n;
    }
}

static HRESULT STDMETHODCALLTYPE our_release_buffer(IAudioRenderClient *r, UINT32 frames, DWORD flags)
{
    void *caller = __builtin_return_address(0);
    AcquireSRWLockShared(&g_lock);
    Stream *s = by_render(r);
    if (s && s->data && frames && !(flags & AUDCLNT_BUFFERFLAGS_SILENT)) {
        s->last_use = GetTickCount64();
        /* Who wrote this stream's mix: the module the call came from, once. */
        if (!s->writer[0]) {
            HMODULE m = NULL;
            WCHAR path[MAX_PATH];
            char name[sizeof s->writer] = "?";
            if (GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                                   (LPCWSTR)caller, &m) && GetModuleFileNameW(m, path, MAX_PATH)) {
                WCHAR *base = wcsrchr(path, L'\\');
                WideCharToMultiByte(CP_UTF8, 0, base ? base + 1 : path, -1, name, sizeof name, NULL, NULL);
            }
            memcpy(s->writer, name, sizeof s->writer);
        }
        /* The shape for the values as they are now (made again when they change). A change of which bands run starts
         * the filters' state again (each band's state would feed another's filter: a click); a change of gains alone
         * keeps it, so a value drawn along its track glides. */
        LONG version = g_version;
        if (s->version != version && g_have_values) {
            SoundValues v = g_values;
            unsigned had = s->version < 0 ? ~0u : s->shape.mask;
            mix_shape(&s->shape, &v, s->rate);
            if (s->shape.mask != had)
                memset(&s->state, 0, sizeof s->state);
            s->version = version;
        }
        if (s->kind != KIND_NONE && s->shape.on) {
            LARGE_INTEGER t0, t1;
            QueryPerformanceCounter(&t0);
            if (s->kind == KIND_FLOAT)
                mix_run_float(&s->shape, &s->state, (float *)s->data, (int)frames, s->channels);
            else if (s->kind == KIND_S16)
                mix_run_s16(&s->shape, &s->state, (int16_t *)s->data, (int)frames, s->channels);
            else if (s->kind == KIND_S32)
                mix_run_s32(&s->shape, &s->state, (int32_t *)s->data, (int)frames, s->channels);
            else
                run_s24(s, s->data, frames);
            QueryPerformanceCounter(&t1);
            LONGLONG d = t1.QuadPart - t0.QuadPart;
            InterlockedIncrement(&g_shaped);
            InterlockedExchangeAdd64(&g_ticks, d);
            InterlockedExchangeAdd64(&g_frames, frames);
            if (d > g_longest)
                g_longest = d;
        } else {
            InterlockedIncrement(&g_passed);
        }
    }
    if (s)
        s->data = NULL;
    ReleaseSRWLockShared(&g_lock);
    return real_release_buffer(r, frames, flags);
}

/* ------------------------------------------------------------------------------------------------ the install */

/* Turn a method table's entry to `ours`: the real method stored first (into *real, never overwritten once stored: the
 * tables are shared, so a second object's entry is ours already), then the entry written, so no thread ever finds our
 * method there without its real one. */
static void patch(void *object, int index, void *ours, void *volatile *real)
{
    void **table = *(void ***)object;
    if (table[index] == ours)
        return;
    *real = table[index];
    MemoryBarrier();
    DWORD old;
    if (!VirtualProtect(&table[index], sizeof(void *), PAGE_READWRITE, &old))
        return;
    table[index] = ours;
    VirtualProtect(&table[index], sizeof(void *), old, &old);
}

typedef HRESULT(WINAPI *CoInitFn)(LPVOID, DWORD);
typedef void(WINAPI *CoUninitFn)(void);
typedef HRESULT(WINAPI *CoCreateFn)(REFCLSID, LPUNKNOWN, DWORD, REFIID, LPVOID *);
typedef void(WINAPI *CoFreeFn)(LPVOID);

/* On a thread of its own in COM's multithreaded apartment (the game's thread joins none): an audio client and its
 * render client of Windows' default output, made only to reach their tables, turned to ours, then let go. It says its
 * own result in the log (the game's thread waits for it a second at most, and may be on its way when it ends). */
static DWORD WINAPI install_thread(LPVOID unused)
{
    (void)unused;
    HMODULE ole = LoadLibraryW(L"ole32.dll");
    CoInitFn co_init = ole ? (CoInitFn)(void *)GetProcAddress(ole, "CoInitializeEx") : NULL;
    CoUninitFn co_uninit = ole ? (CoUninitFn)(void *)GetProcAddress(ole, "CoUninitialize") : NULL;
    CoCreateFn co_create = ole ? (CoCreateFn)(void *)GetProcAddress(ole, "CoCreateInstance") : NULL;
    CoFreeFn co_free = ole ? (CoFreeFn)(void *)GetProcAddress(ole, "CoTaskMemFree") : NULL;
    if (!co_init || !co_uninit || !co_create || !co_free || FAILED(co_init(NULL, COINIT_MULTITHREADED))) {
        ingame_log("mix: the last stage of the game's sound (master volume, equaliser): no COM");
        return 0;
    }
    IMMDeviceEnumerator *en = NULL;
    IMMDevice *dev = NULL;
    IAudioClient *client = NULL;
    IAudioRenderClient *render = NULL;
    WAVEFORMATEX *mix = NULL;
    HRESULT hr = co_create(&CLSID_MMDeviceEnumerator, NULL, CLSCTX_ALL, &IID_IMMDeviceEnumerator, (void **)&en);
    if (SUCCEEDED(hr))
        hr = IMMDeviceEnumerator_GetDefaultAudioEndpoint(en, eRender, eConsole, &dev);
    if (SUCCEEDED(hr))
        hr = IMMDevice_Activate(dev, &IID_IAudioClient, CLSCTX_ALL, NULL, (void **)&client);
    /* Initialize, GetService and Release turned first: the render client below is made through ours too (and its
     * stream leaves the table when it is let go). */
    if (SUCCEEDED(hr)) {
        patch(client, M_RELEASE, (void *)our_client_release, (void *volatile *)&real_client_release);
        patch(client, M_CLIENT_INITIALIZE, (void *)our_initialize, (void *volatile *)&real_initialize);
        patch(client, M_CLIENT_GET_SERVICE, (void *)our_get_service, (void *volatile *)&real_get_service);
        hr = IAudioClient_GetMixFormat(client, &mix);
    }
    /* A shared stream of 100 ms (never started) for its render client's table. */
    if (SUCCEEDED(hr))
        hr = real_initialize(client, AUDCLNT_SHAREMODE_SHARED, 0, 1000000, 0, mix, NULL);
    if (SUCCEEDED(hr))
        hr = real_get_service(client, &IID_IAudioRenderClient, (void **)&render);
    if (SUCCEEDED(hr)) {
        patch(render, M_RELEASE, (void *)our_render_release, (void *volatile *)&real_render_release);
        patch(render, M_RENDER_GET_BUFFER, (void *)our_get_buffer, (void *volatile *)&real_get_buffer);
        patch(render, M_RENDER_RELEASE_BUFFER, (void *)our_release_buffer, (void *volatile *)&real_release_buffer);
    }
    ingame_log("mix: the last stage of the game's sound (master volume, equaliser): %s (0x%08lx)",
               real_release_buffer && real_get_service ? "in place" : "not in place: the mix passes as it is",
               (unsigned long)hr);
    if (render)
        IAudioRenderClient_Release(render);
    if (mix)
        co_free(mix);
    if (client)
        IAudioClient_Release(client);
    if (dev)
        IMMDevice_Release(dev);
    if (en)
        IMMDeviceEnumerator_Release(en);
    co_uninit();
    return 0;
}

void mix_install(void)
{
    static LONG done;
    if (InterlockedExchange(&done, 1))
        return;
    QueryPerformanceFrequency(&g_frequency);
    /* Before the game's sound opens, so its stream's Initialize is seen; waited for a second at most (the audio
     * service starting), never longer: the game then opens its sound as it is, and a stream it opens before the
     * install ends passes as it is. */
    HANDLE t = CreateThread(NULL, 0, install_thread, NULL, 0, NULL);
    if (!t) {
        ingame_log("mix: the last stage of the game's sound (master volume, equaliser): no thread");
        return;
    }
    if (WaitForSingleObject(t, 1000) != WAIT_OBJECT_0)
        ingame_log("mix: the last stage of the game's sound is not ready within a second: the game's sound opens now");
    CloseHandle(t);
}

void mix_set(const SoundValues *v)
{
    /* Copied whole, then the version moved: a mixer's thread makes its shape again at its next buffer. */
    AcquireSRWLockExclusive(&g_lock);
    g_values = *v;
    g_have_values = 1;
    ReleaseSRWLockExclusive(&g_lock);
    InterlockedIncrement(&g_version);
}

unsigned mix_bands_off(void)
{
    /* The bands any live stream leaves off at its rate (the in-game panel shows them off). */
    unsigned off = 0;
    AcquireSRWLockShared(&g_lock);
    for (int i = 0; i < STREAMS; i++)
        if (g_streams[i].used && g_streams[i].version >= 0)
            off |= g_streams[i].shape.dropped;
    ReleaseSRWLockShared(&g_lock);
    return off;
}

void mix_frame(void)
{
    static double next;
    double now = (double)GetTickCount64();
    /* Each stream's first pass, and the bands its rate leaves off, said once each (from the game's thread). */
    AcquireSRWLockShared(&g_lock);
    for (int i = 0; i < STREAMS; i++) {
        Stream *s = &g_streams[i];
        if (!s->used)
            continue;
        if (s->writer[0] && !s->said) {
            s->said = 1;
            ingame_log("mix: a stream written by %s passes the last stage: %s, %d Hz, %d channels, %s mode%s",
                       s->writer, KIND_NAMES[s->kind], s->rate, s->channels, s->exclusive ? "exclusive" : "shared",
                       s->kind == KIND_NONE ? " (passed as it is)" : "");
        }
        unsigned dropped = s->version >= 0 ? s->shape.dropped : 0;
        if (dropped != s->said_dropped) {
            s->said_dropped = dropped;
            for (int b = 0; b < EQ_BANDS; b++)
                if (dropped & (1u << b))
                    ingame_log("mix: at %d Hz the equaliser's %d Hz band is at or above half the rate: left off",
                               s->rate, EQ_HZ[b]);
        }
    }
    ReleaseSRWLockShared(&g_lock);
    LONG recycled = InterlockedExchange(&g_recycled, 0);
    if (recycled)
        ingame_log("mix: the table of streams was full: %ld new stream%s took the longest unused place", (long)recycled,
                   recycled == 1 ? "" : "s");
    /* The stage's time, every 10 s while it shapes anything. */
    if (now < next)
        return;
    next = now + 10000.0;
    LONG shaped = InterlockedExchange(&g_shaped, 0), passed = InterlockedExchange(&g_passed, 0);
    LONGLONG ticks = InterlockedExchange64(&g_ticks, 0), frames = InterlockedExchange64(&g_frames, 0);
    LONGLONG longest = InterlockedExchange64(&g_longest, 0);
    if (!shaped || !g_frequency.QuadPart)
        return;
    double us = 1e6 / (double)g_frequency.QuadPart;
    ingame_log("mix: %ld buffers shaped in 10 s (%ld passed untouched), %.0f frames each, %.1f us each, longest "
               "%.1f us", (long)shaped, (long)passed, (double)frames / shaped, ticks * us / shaped, longest * us);
}
