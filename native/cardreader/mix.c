/*
 * The last stage of the game's sound (ingame.h mix_*): the master volume and the equaliser the player sets (the 0.4.0
 * list's #11), on the mix itself as it goes to Windows, whichever mixer made it.
 *
 * Every mixer the launcher offers writes its mix through Windows' audio client in this process: Windows' own
 * DirectSound (dsound.dll mixes the game's buffers into a WASAPI stream of its own), and OpenAL Soft behind DSOAL, in
 * shared or in exclusive mode (its WASAPI backend). Each asks its IAudioRenderClient for room (GetBuffer), writes the
 * mix there and hands it on (ReleaseBuffer). Those two methods, and the audio client's Initialize and GetService that
 * say each stream's format, sit in tables every such object of the process shares: they are turned to ours once,
 * before the game opens its sound (mix_install, from hooks.c's DirectSound open), so the mix is shaped in place
 * between its writing and its hand-over. Nothing is added to the way: no buffer of ours, no frame later; the
 * stage's own time is measured and logged with the caller that wrote the mix (the proof of which mixer it was).
 *
 * At 100 % and flat nothing is touched. A format it cannot shape (packed 24-bit, more than eight channels) passes as it
 * is, said once in the log.
 */
#define COBJMACROS
#include "ingame.h"

#include <mmsystem.h>
#include <mmdeviceapi.h>
#include <audioclient.h>
#include <stdio.h>
#include <string.h>

/* The tables' places: IAudioClient's Initialize and GetService, IAudioRenderClient's GetBuffer and ReleaseBuffer. */
#define M_CLIENT_INITIALIZE 3
#define M_CLIENT_GET_SERVICE 14
#define M_RENDER_GET_BUFFER 3
#define M_RENDER_RELEASE_BUFFER 4

typedef HRESULT(STDMETHODCALLTYPE *InitializeFn)(IAudioClient *, AUDCLNT_SHAREMODE, DWORD, REFERENCE_TIME,
                                                 REFERENCE_TIME, const WAVEFORMATEX *, LPCGUID);
typedef HRESULT(STDMETHODCALLTYPE *GetServiceFn)(IAudioClient *, REFIID, void **);
typedef HRESULT(STDMETHODCALLTYPE *GetBufferFn)(IAudioRenderClient *, UINT32, BYTE **);
typedef HRESULT(STDMETHODCALLTYPE *ReleaseBufferFn)(IAudioRenderClient *, UINT32, DWORD);
static InitializeFn real_initialize;
static GetServiceFn real_get_service;
static GetBufferFn real_get_buffer;
static ReleaseBufferFn real_release_buffer;

/* The sample kinds the stage shapes. */
enum { KIND_NONE = 0, KIND_FLOAT, KIND_S16, KIND_S24, KIND_S32 };

/* One stream: its audio client and render client, its format, the room GetBuffer handed out, its filters' state. */
typedef struct {
    IAudioClient *client;
    IAudioRenderClient *render;
    int kind, channels, rate, exclusive;
    BYTE *data;            /* the room the last GetBuffer gave (written by the mixer, shaped at its release) */
    MixState state;
    int version;           /* the values' version its shape was made for */
    MixShape shape;
    char writer[48];       /* the module that wrote its first mix (dsound.dll, the OpenAL library) */
    int said;              /* its first pass said in the log */
} Stream;
#define STREAMS 16
static Stream g_streams[STREAMS];
static int g_nstreams;
static SRWLOCK g_lock = SRWLOCK_INIT;

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

/* A stream by its render client (under the lock). */
static Stream *by_render(IAudioRenderClient *r)
{
    for (int i = 0; i < g_nstreams; i++)
        if (g_streams[i].render == r)
            return &g_streams[i];
    return NULL;
}

static HRESULT STDMETHODCALLTYPE our_initialize(IAudioClient *c, AUDCLNT_SHAREMODE mode, DWORD flags,
                                                REFERENCE_TIME duration, REFERENCE_TIME period,
                                                const WAVEFORMATEX *f, LPCGUID session)
{
    HRESULT hr = real_initialize(c, mode, flags, duration, period, f, session);
    if (FAILED(hr) || !f)
        return hr;
    AcquireSRWLockExclusive(&g_lock);
    /* The client's format kept (a client initialised again replaces its entry; a full table keeps the oldest). */
    Stream *s = NULL;
    for (int i = 0; i < g_nstreams && !s; i++)
        if (g_streams[i].client == c)
            s = &g_streams[i];
    if (!s && g_nstreams < STREAMS)
        s = &g_streams[g_nstreams++];
    if (s) {
        memset(s, 0, sizeof *s);
        s->client = c;
        s->kind = f->nChannels <= MIX_CHANNELS ? kind_of(f) : KIND_NONE;
        s->channels = f->nChannels;
        s->rate = (int)f->nSamplesPerSec;
        s->exclusive = mode == AUDCLNT_SHAREMODE_EXCLUSIVE;
        s->version = -1;
    }
    ReleaseSRWLockExclusive(&g_lock);
    return hr;
}

static HRESULT STDMETHODCALLTYPE our_get_service(IAudioClient *c, REFIID riid, void **out)
{
    HRESULT hr = real_get_service(c, riid, out);
    if (FAILED(hr) || !out || !*out || !IsEqualIID(riid, &IID_IAudioRenderClient))
        return hr;
    /* The render client of a client whose format is kept: its writes are that stream's. */
    AcquireSRWLockExclusive(&g_lock);
    for (int i = 0; i < g_nstreams; i++)
        if (g_streams[i].client == c)
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
        /* The shape for the values as they are now (made again when they change). */
        LONG version = g_version;
        if (s->version != version && g_have_values) {
            SoundValues v = g_values;
            mix_shape(&s->shape, &v, s->rate);
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

/* Put `ours` in a method table's entry, keeping what was there (NULL when it is ours already). */
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

typedef HRESULT(WINAPI *CoInitFn)(LPVOID, DWORD);
typedef void(WINAPI *CoUninitFn)(void);
typedef HRESULT(WINAPI *CoCreateFn)(REFCLSID, LPUNKNOWN, DWORD, REFIID, LPVOID *);
typedef void(WINAPI *CoFreeFn)(LPVOID);

/* What the install found, for the log (said from the game's thread). */
static char g_install_words[160];

/* On a thread of its own in COM's multithreaded apartment (the game's thread joins none): an audio client and its
 * render client of Windows' default output, made only to reach their tables, turned to ours, then let go. */
static DWORD WINAPI install_thread(LPVOID unused)
{
    (void)unused;
    HMODULE ole = LoadLibraryW(L"ole32.dll");
    CoInitFn co_init = ole ? (CoInitFn)(void *)GetProcAddress(ole, "CoInitializeEx") : NULL;
    CoUninitFn co_uninit = ole ? (CoUninitFn)(void *)GetProcAddress(ole, "CoUninitialize") : NULL;
    CoCreateFn co_create = ole ? (CoCreateFn)(void *)GetProcAddress(ole, "CoCreateInstance") : NULL;
    CoFreeFn co_free = ole ? (CoFreeFn)(void *)GetProcAddress(ole, "CoTaskMemFree") : NULL;
    if (!co_init || !co_uninit || !co_create || !co_free || FAILED(co_init(NULL, COINIT_MULTITHREADED))) {
        snprintf(g_install_words, sizeof g_install_words, "no COM");
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
    /* Initialize and GetService turned first: the render client below is made through ours too (and dropped). */
    if (SUCCEEDED(hr)) {
        void *was;
        if ((was = swap(client, M_CLIENT_INITIALIZE, (void *)our_initialize)))
            real_initialize = (InitializeFn)was;
        if ((was = swap(client, M_CLIENT_GET_SERVICE, (void *)our_get_service)))
            real_get_service = (GetServiceFn)was;
        hr = IAudioClient_GetMixFormat(client, &mix);
    }
    /* A shared stream of 100 ms (never started) for its render client's table. */
    if (SUCCEEDED(hr))
        hr = real_initialize(client, AUDCLNT_SHAREMODE_SHARED, 0, 1000000, 0, mix, NULL);
    if (SUCCEEDED(hr))
        hr = real_get_service(client, &IID_IAudioRenderClient, (void **)&render);
    if (SUCCEEDED(hr)) {
        void *was;
        if ((was = swap(render, M_RENDER_GET_BUFFER, (void *)our_get_buffer)))
            real_get_buffer = (GetBufferFn)was;
        if ((was = swap(render, M_RENDER_RELEASE_BUFFER, (void *)our_release_buffer)))
            real_release_buffer = (ReleaseBufferFn)was;
    }
    snprintf(g_install_words, sizeof g_install_words, "%s (0x%08lx)",
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
     * service starting), never longer: the game then plays as it is. */
    HANDLE t = CreateThread(NULL, 0, install_thread, NULL, 0, NULL);
    if (!t) {
        snprintf(g_install_words, sizeof g_install_words, "no thread");
    } else {
        if (WaitForSingleObject(t, 1000) != WAIT_OBJECT_0)
            snprintf(g_install_words, sizeof g_install_words, "not ready within a second");
        CloseHandle(t);
    }
    ingame_log("mix: the last stage of the game's sound (master volume, equaliser): %s", g_install_words);
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

void mix_frame(void)
{
    static double next;
    double now = (double)GetTickCount64();
    /* Each stream's first pass, said once (from the game's thread: the log is written from it). */
    AcquireSRWLockShared(&g_lock);
    for (int i = 0; i < g_nstreams; i++) {
        Stream *s = &g_streams[i];
        if (s->writer[0] && !s->said) {
            s->said = 1;
            ingame_log("mix: a stream written by %s passes the last stage: %s, %d Hz, %d channels, %s mode%s",
                       s->writer, KIND_NAMES[s->kind], s->rate, s->channels, s->exclusive ? "exclusive" : "shared",
                       s->kind == KIND_NONE ? " (passed as it is)" : "");
        }
    }
    ReleaseSRWLockShared(&g_lock);
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
