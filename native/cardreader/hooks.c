/*
 * The game's imports turned to ours, from inside its own process (ingame.h).
 *
 * The game imports DirectSoundCreate8, Direct3DCreate9, GetKeyboardState and GetCursorPos by name. Their slots in its
 * import table hold the real functions' addresses once Windows has loaded it; each slot holding one of those addresses
 * gets ours instead, which call the real one:
 *   - DirectSoundCreate8 (and DirectSoundCreate): the sound device the launcher chose instead of Windows' default
 *     output, or the default when none was chosen or the chosen one is gone;
 *   - Direct3DCreate9: its object's CreateDevice, whose device's Present counts frames (into the log every two
 *     seconds, the chip twice a second) and, with even pacing, holds them to 60.0 a second by openDMT3's clock in
 *     place of the client's own steps (led by a song's music while one plays, with the music lock, and kept in the
 *     middle of a display refresh with VSync on); it keeps at most one frame queued ahead of the GPU, steps the
 *     post-process chain down when the chain makes frames late, and holds the game still while the menu or the
 *     question is open during a song; the device's window is the game's, where the layer goes;
 *   - GetKeyboardState: the game reads every key and the mouse's buttons with it once a frame, so while the menu or
 *     the question is up it sees nothing pressed (logic.c hold_keys);
 *   - GetCursorPos: in the client with the display fix, the point it reads is turned so that the game pixel it finds is
 *     the one under the pointer in the picture as the chain placed it (the game's pointer, below).
 */
#include "ingame.h"
#include "postmath.h"

/* initguid.h first: this file then holds DSDEVID_DefaultPlayback itself, with no import library for it. */
#include <initguid.h>
/* mmsystem.h: the wave format dsound.h uses, left out by the lean windows.h. */
#include <mmsystem.h>
#include <d3d9.h>
#include <dsound.h>
#include <stdarg.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>

Settings g_settings;
HMODULE g_module;
int g_keys_waiting;

/* The real functions, found in the modules the game already loaded. */
typedef HRESULT(WINAPI *DsCreate8)(LPCGUID, LPDIRECTSOUND8 *, LPUNKNOWN);
typedef HRESULT(WINAPI *DsCreate)(LPCGUID, LPDIRECTSOUND *, LPUNKNOWN);
typedef IDirect3D9 *(WINAPI *D3dCreate)(UINT);
typedef BOOL(WINAPI *KeysGet)(PBYTE);
static DsCreate8 real_ds8;
static DsCreate real_ds;
static D3dCreate real_d3d;
static KeysGet real_keys;
/* The Direct3D methods replaced in their tables. */
typedef HRESULT(STDMETHODCALLTYPE *CreateDeviceFn)(IDirect3D9 *, UINT, D3DDEVTYPE, HWND, DWORD,
                                                   D3DPRESENT_PARAMETERS *, IDirect3DDevice9 **);
typedef HRESULT(STDMETHODCALLTYPE *PresentFn)(IDirect3DDevice9 *, const RECT *, const RECT *, HWND, const RGNDATA *);
typedef HRESULT(STDMETHODCALLTYPE *ResetFn)(IDirect3DDevice9 *, D3DPRESENT_PARAMETERS *);
static CreateDeviceFn real_create_device;
static PresentFn real_present;
static ResetFn real_reset;
/* Whether the import slots were turned (DllMain may come before they are bound; the card reader tries again). */
static int g_hooked;

/* ------------------------------------------------------------------------------------------------------- log */

int ingame_beside(const WCHAR *name, WCHAR *out, size_t room)
{
    /* The DLL's own path, wide: openDMT3's folder may have letters outside the ANSI code page. */
    DWORD n = GetModuleFileNameW(g_module, out, (DWORD)room);
    WCHAR *slash = n && n < room ? wcsrchr(out, L'\\') : NULL;
    /* Room for the name after the folder's backslash. */
    if (!slash || (size_t)(slash + 1 - out) + wcslen(name) + 1 > room)
        return 0;
    wcscpy(slash + 1, name);
    return 1;
}

void ingame_log(const char *fmt, ...)
{
    WCHAR path[MAX_PATH * 4];
    /* No variable: no log (a player's normal case). A value too long for the buffer is not a path to open. */
    DWORD got = GetEnvironmentVariableW(L"OPENDMT3_INGAME_LOG", path, MAX_PATH * 4);
    if (!got || got >= MAX_PATH * 4)
        return;
    /* An empty value means the default name beside the DLL (openDMT3's folder; the game folder is only read). */
    if (!path[0] && !ingame_beside(L"openDMT3-ingame.log", path, MAX_PATH * 4))
        return;
    /* One line at a time from any thread (the sound engine's period is said from a thread of its own, engine.c): each
     * open moves to the file's end and writes there, so two at once could land at the same place, one lost. */
    static SRWLOCK lock = SRWLOCK_INIT;
    AcquireSRWLockExclusive(&lock);
    FILE *f = _wfopen(path, L"a");
    if (f) {
        /* The time since Windows started, in milliseconds: enough to order the lines and measure between them. */
        fprintf(f, "%lu ", (unsigned long)GetTickCount());
        va_list ap;
        va_start(ap, fmt);
        vfprintf(f, fmt, ap);
        va_end(ap);
        fputc('\n', f);
        fclose(f);
    }
    ReleaseSRWLockExclusive(&lock);
}

/* ---------------------------------------------------------------------------------------------- the import table */

/* Put `ours` in every import slot of `module` that holds `real`; how many were changed (files.c turns the client's
 * file calls with it too). */
int ingame_patch_imports(HMODULE module, void *real, void *ours)
{
    if (!module || !real)
        return 0;
    BYTE *base = (BYTE *)module;
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)base;
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(base + dos->e_lfanew);
    IMAGE_DATA_DIRECTORY dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!dir.VirtualAddress)
        return 0;
    int changed = 0;
    /* Each imported library's descriptor, until the empty one that ends the list. */
    for (IMAGE_IMPORT_DESCRIPTOR *d = (IMAGE_IMPORT_DESCRIPTOR *)(base + dir.VirtualAddress); d->Name; d++) {
        /* FirstThunk: the slots the loader filled with the real addresses (the game calls through them). */
        for (IMAGE_THUNK_DATA *t = (IMAGE_THUNK_DATA *)(base + d->FirstThunk); t->u1.Function; t++) {
            if ((void *)t->u1.Function != real)
                continue;
            DWORD old;
            /* The slots are in read-only memory: writable for the one write, then as they were. */
            if (VirtualProtect(&t->u1.Function, sizeof t->u1.Function, PAGE_READWRITE, &old)) {
                t->u1.Function = (ULONG_PTR)ours;
                VirtualProtect(&t->u1.Function, sizeof t->u1.Function, old, &old);
                changed++;
            }
        }
    }
    return changed;
}

/* Put `ours` in entry `index` of a COM object's method table; the method that was there. */
static void *patch_method(void *object, int index, void *ours)
{
    void **table = *(void ***)object;
    void *was = table[index];
    /* Already ours (a second device of the same kind shares the table): nothing to do. */
    if (was == ours)
        return NULL;
    DWORD old;
    if (!VirtualProtect(&table[index], sizeof(void *), PAGE_READWRITE, &old))
        return NULL;
    table[index] = ours;
    VirtualProtect(&table[index], sizeof(void *), old, &old);
    return was;
}

/* ------------------------------------------------------------------------------------------------- the sound */

/* The device the launcher chose, as Windows' GUID structure (only when one was chosen). */
static GUID chosen_device(void)
{
    GUID g;
    memcpy(&g, g_settings.device, sizeof g);
    return g;
}

/* Whether the game asked for Windows' default output (the only request the choice replaces). */
static int asks_default(LPCGUID dev)
{
    return !dev || IsEqualGUID(dev, &DSDEVID_DefaultPlayback);
}

/* The launcher's note of the run's sound, its first line (engine.c adds the engine's period after it): the Mixer
 * chosen, the one that plays, the device the launcher chose (its GUID, all 0 for Windows' default output: the launcher
 * shows the line beside that choice only), and when OpenAL Soft was chosen and did not open, which step failed with its
 * error. Written once the game's DirectSound object is open; once a process: the game opens its sound once. */
static void mixer_note(int played, const char *failed, unsigned long hr)
{
    static LONG written;
    if (InterlockedExchange(&written, 1))
        return;
    char line[200], device[39];
    format_guid(g_settings.device, device);
    snprintf(line, sizeof line, "mixer chosen=%s played=%s output=%s device=%s failed=%s hr=0x%08lx",
             SOUND_PATH_NAMES[g_settings.sound_path], SOUND_PATH_NAMES[played],
             g_settings.has_device ? "chosen" : "default", device, failed ? failed : "-", hr);
    sound_note(line, 1);
}

static HRESULT WINAPI our_ds8(LPCGUID dev, LPDIRECTSOUND8 *out, LPUNKNOWN outer)
{
    char text[39];
    format_guid(g_settings.device, text);
    /* The launcher's Mixer through OpenAL Soft (openal.c): DSOAL's DirectSound on the same device, its objects
     * followed as Windows' own are; Windows' own below when it fails in any way. */
    const char *failed = NULL;
    unsigned long why = 0;
    if (g_settings.sound_path != SOUND_PATH_DIRECTSOUND && out && !outer && asks_default(dev)) {
        GUID g = chosen_device();
        void *object = openal_create(g_settings.has_device ? &g : NULL,
                                     g_settings.sound_path == SOUND_PATH_OPENAL_EXCLUSIVE, &failed, &why);
        if (object) {
            *out = (LPDIRECTSOUND8)object;
            ingame_log("sound: opened %s through OpenAL Soft at frame %ld",
                       g_settings.has_device ? text : "Windows' default output", ingame_frame());
            mixer_note(g_settings.sound_path, NULL, 0);
            sound_attach(object);
            /* In shared mode its stream goes through Windows' engine, whose shortest period helps it too; in
             * exclusive mode the engine is not on the way. */
            if (g_settings.sound_path == SOUND_PATH_OPENAL)
                engine_start(g_settings.has_device ? g_settings.device : NULL);
            return DS_OK;
        }
    } else if (g_settings.sound_path != SOUND_PATH_DIRECTSOUND) {
        /* Chosen, but the game asked for a device of its own (or an aggregate): Windows' own is what it asked for. */
        failed = "not-default";
    }
    if (g_settings.has_device && asks_default(dev)) {
        GUID g = chosen_device();
        HRESULT hr = real_ds8(&g, out, outer);
        if (SUCCEEDED(hr)) {
            ingame_log("sound: opened the chosen device %s at frame %ld", text, ingame_frame());
            /* Windows' own DirectSound plays (chosen, or OpenAL Soft's failure said with it). */
            mixer_note(SOUND_PATH_DIRECTSOUND, failed, why);
            sound_attach(out ? *out : NULL);
            /* The sound engine's shortest period on that device, while the game runs (engine.c). */
            engine_start(g_settings.device);
            return hr;
        }
        /* Gone (unplugged, turned off in Windows): the default output, as the launcher's Sound page says. */
        ingame_log("sound: the chosen device %s did not open (0x%08lx): Windows' default output", text,
                   (unsigned long)hr);
    }
    HRESULT hr = real_ds8(dev, out, outer);
    ingame_log("sound: opened Windows' default output (0x%08lx) at frame %ld", (unsigned long)hr, ingame_frame());
    if (SUCCEEDED(hr)) {
        /* Windows' own DirectSound plays here too. */
        mixer_note(SOUND_PATH_DIRECTSOUND, failed, why);
        sound_attach(out ? *out : NULL);
        /* The game asked for the default output itself only when it named no other device: then that one's period. */
        if (asks_default(dev))
            engine_start(NULL);
    }
    return hr;
}

static HRESULT WINAPI our_ds(LPCGUID dev, LPDIRECTSOUND *out, LPUNKNOWN outer)
{
    char text[39];
    format_guid(g_settings.device, text);
    /* The older call takes no Mixer: Windows' own DirectSound plays (the game imports DirectSoundCreate8). */
    const char *failed = g_settings.sound_path != SOUND_PATH_DIRECTSOUND ? "old-call" : NULL;
    if (g_settings.has_device && asks_default(dev)) {
        GUID g = chosen_device();
        HRESULT hr = real_ds(&g, out, outer);
        if (SUCCEEDED(hr)) {
            ingame_log("sound: opened the chosen device %s", text);
            mixer_note(SOUND_PATH_DIRECTSOUND, failed, 0);
            /* The sound engine's shortest period on that device, as for DirectSoundCreate8 (engine.c). */
            engine_start(g_settings.device);
            return hr;
        }
        ingame_log("sound: the chosen device %s did not open (0x%08lx): Windows' default output", text,
                   (unsigned long)hr);
    }
    HRESULT hr = real_ds(dev, out, outer);
    ingame_log("sound: opened Windows' default output (0x%08lx)", (unsigned long)hr);
    if (SUCCEEDED(hr))
        mixer_note(SOUND_PATH_DIRECTSOUND, failed, 0);
    /* Windows' default output's period, when that is what the game asked for. */
    if (SUCCEEDED(hr) && asks_default(dev))
        engine_start(NULL);
    return hr;
}

/* ------------------------------------------------------------------------------------------------ the picture */

/* Whether the game's present waits for the display, the frame clock (even pacing only), and the counter's clock. */
static Pacer g_pacer;
static int g_vsync = 1;
static LARGE_INTEGER g_frequency;
/* The frame counter over two seconds: frames, the time between them (sum, sum of squares, longest), and the time
 * openDMT3's own code took in them (sum, longest), all in counter ticks. */
static LONG g_frames;
/* The frame lengths measured in those two seconds: one a frame, the frame that crosses into a new two seconds
 * included (it carries the log's own writing, so a slow one there is seen like any other). */
static LONG g_gaps;
static LONGLONG g_count_from, g_last_frame, g_gap_sum, g_gap_max, g_layer_sum, g_layer_max;
static double g_gap_squares;
/* The frames' lengths in quarter milliseconds (the last bucket holds every longer one): their slowest 1 % and the share
 * of frames over 20 ms (a frame that missed its 60 a second turn by more than a display refresh). */
#define BUCKETS 400
static LONG g_buckets[BUCKETS];
/* The chip's numbers: refreshed twice a second. */
static LONGLONG g_chip_from;
static LONG g_chip_frames;
/* The client's own limiter was taken out (even pacing): openDMT3's clock holds the game at 60. */
static int g_own_clock;
/* The music lock's state, and the song it follows (the frame its music started at; -1: none yet). */
static MusicLock g_lock;
static long g_lock_song = -1;
static double g_lock_base;
/* The display's refresh in counter ticks (VSync on; 0: not known), for the display lock. */
static LONGLONG g_refresh_ticks;
static int g_refresh_hz, g_display_h;
/* Where in their refresh the ticks fell over the counter's two seconds (the display lock's own reading, for its line). */
static double g_phase_min = 2, g_phase_max = -1;
/* At most one frame queued: an event query after each present, waited for before the next (OPENDMT3_QUEUE=deep,
 * measuring only, turns it off to compare). */
static IDirect3DQuery9 *g_frame_done;
static int g_frame_done_issued, g_queue_deep, g_queue_checked;
/* The safety net over the post-process chain. */
static Guard g_guard;

/* The client's own frame limiter: the PC build's patch section holds every frame at 17, 17 and 16 ms (timeGetTime and
 * Sleep(1)), entered by a jump written over the first instruction of the game's per-frame function at 0x455430. Taken
 * out (that function's own first bytes put back) for even pacing, where openDMT3's clock holds the same 60 frames a
 * second, and for the measurement of whether the game's speed follows its frame rate (OPENDMT3_INGAME_UNLOCK, with no
 * clock of ours). Only when the bytes are exactly those measured; returns whether it was taken out. */
static int take_out_limiter(void)
{
    BYTE *at = (BYTE *)0x455430;
    /* The jump to the limiter (e9 63 d9 a0 19) and the nop after it, exactly, or nothing is touched. */
    static const BYTE jump[6] = {0xe9, 0x63, 0xd9, 0xa0, 0x19, 0x90};
    static const BYTE prologue[6] = {0x55, 0x8b, 0xec, 0x83, 0xec, 0x0c};
    MEMORY_BASIC_INFORMATION info;
    if (!VirtualQuery(at, &info, sizeof info) || info.State != MEM_COMMIT || memcmp(at, jump, 6)) {
        ingame_log("pacing: the client's limiter is not where it was measured; its own steps stay");
        return 0;
    }
    DWORD old;
    if (!VirtualProtect(at, 6, PAGE_EXECUTE_READWRITE, &old))
        return 0;
    memcpy(at, prologue, 6);
    VirtualProtect(at, 6, old, &old);
    FlushInstructionCache(GetCurrentProcess(), at, 6);
    return 1;
}

/* Read the present parameters the game asked for: whether it waits for the display. */
static void take_parameters(const D3DPRESENT_PARAMETERS *pp)
{
    /* IMMEDIATE is VSync off; every other interval waits for the display's refresh. */
    g_vsync = pp->PresentationInterval != D3DPRESENT_INTERVAL_IMMEDIATE;
    QueryPerformanceFrequency(&g_frequency);
    /* Even pacing: exactly 60 a second by openDMT3's clock, VSync on or off (the game's logic runs once a frame). */
    pacer_start(&g_pacer, g_frequency.QuadPart, g_own_clock ? GAME_FPS : 0);
    /* A new song lock after a reset: the next frame's reading starts it again. */
    g_lock_song = -1;
    ingame_log("picture: vsync %s, pacing %s", g_vsync ? "on" : "off",
               !g_own_clock ? "the client's own"
               : g_settings.music_lock ? "even (openDMT3's clock), locked to a song's music while one plays"
                                       : "even (openDMT3's clock)");
}

/* The display's refresh rate, for the display lock (VSync on): from the device's display mode. */
static void take_refresh(IDirect3DDevice9 *dev)
{
    D3DDISPLAYMODE mode;
    g_refresh_ticks = 0;
    if (!g_vsync || !g_own_clock || FAILED(IDirect3DDevice9_GetDisplayMode(dev, 0, &mode)))
        return;
    /* Measuring only (OPENDMT3_REFRESH): a rate for a display that reports none (a virtual screen under Wine). */
    char v[8];
    if (!mode.RefreshRate && GetEnvironmentVariableA("OPENDMT3_REFRESH", v, sizeof v) > 0)
        mode.RefreshRate = (UINT)atoi(v);
    if (!mode.RefreshRate) {
        ingame_log("picture: the display reports no refresh rate: ticks not kept to it");
        return;
    }
    g_refresh_hz = (int)mode.RefreshRate;
    g_display_h = (int)mode.Height;
    g_refresh_ticks = g_frequency.QuadPart / g_refresh_hz;
    /* Each 60 a second frame spans this many refreshes (4 at 240 Hz); a rate 60 does not divide still gets the lock,
     * the frames then alternate between two counts as they must. */
    ingame_log("picture: display at %d Hz, %.2f refreshes a frame: ticks kept mid-refresh", g_refresh_hz,
               g_refresh_hz / 60.0);
}

/* Where in its refresh the display is now (0 its start, 1 its end; the blank at the end counts as the end), or -1. */
static double refresh_phase(IDirect3DDevice9 *dev)
{
    D3DRASTER_STATUS rs;
    if (!g_refresh_ticks || g_display_h <= 0 || FAILED(IDirect3DDevice9_GetRasterStatus(dev, 0, &rs)))
        return -1;
    if (rs.InVBlank)
        return 1.0;
    double phase = (double)rs.ScanLine / (double)g_display_h;
    return phase > 1.0 ? 1.0 : phase;
}

/* The music lock, before this frame's wait: how far the song's music is ahead of this frame's place in the song, at
 * the moment the frame is due; the pacer's next tick moves by the lock's step. */
static void lock_to_music(LONGLONG now)
{
    double ms;
    long started;
    if (!g_settings.music_lock || !g_own_clock || g_pacer.period <= 0 || !g_pacer.next ||
        !sound_music_position(&ms, &started)) {
        /* No song plays: the frame clock alone (the next song starts a new lock). */
        g_lock_song = -1;
        return;
    }
    /* This frame is the song's frame (frames since its music started, this one included); due at the pacer's tick. */
    double frame_ms = (double)(ingame_frame() + 1 - started) * 1000.0 / GAME_FPS;
    double until_due = (double)(g_pacer.next - now) * 1000.0 / (double)g_frequency.QuadPart;
    double ahead = ms + (until_due > 0 ? until_due : 0) - frame_ms;
    if (started != g_lock_song) {
        /* A new song: its first distance is how the game itself started the music against its frames; kept. */
        g_lock_song = started;
        g_lock_base = ahead;
        music_lock_start(&g_lock);
        ingame_log("pacing: locked to the music started at frame %ld (%.1f ms from its frames)", started, ahead);
    }
    g_pacer.next -= music_lock_step(&g_lock, ahead - g_lock_base, g_pacer.period);
}

/* At most one frame queued: the previous frame's present done on the GPU before this one is handed over. */
static void wait_previous_frame(IDirect3DDevice9 *dev)
{
    if (!g_queue_checked) {
        char v[8];
        g_queue_checked = 1;
        g_queue_deep = GetEnvironmentVariableA("OPENDMT3_QUEUE", v, sizeof v) > 0 && !lstrcmpiA(v, "deep");
        ingame_log("picture: %s", g_queue_deep ? "frames queued as Direct3D allows (measuring)" : "at most one frame queued");
    }
    if (g_queue_deep || !g_frame_done || !g_frame_done_issued)
        return;
    LARGE_INTEGER start, now;
    QueryPerformanceCounter(&start);
    for (;;) {
        HRESULT hr = IDirect3DQuery9_GetData(g_frame_done, NULL, 0, D3DGETDATA_FLUSH);
        /* Done, or the device lost (it answers nothing until the game resets it). */
        if (hr != S_FALSE)
            break;
        QueryPerformanceCounter(&now);
        /* A tenth of a second at most: a frame that slow is a stall, not a queue. */
        if (now.QuadPart - start.QuadPart > g_frequency.QuadPart / 10)
            break;
        /* Asked again after a sleep, not a spin, so the core is free for the driver's threads and the game's own: a
         * millisecond (the game set Windows' timer to 1 ms at its start) while the frame's tick is more than 2 ms off
         * either way or the pacer keeps none; within 2 ms of it, only the rest of this thread's turn given away, so a
         * frame the GPU finishes then still leaves on its tick (the pacer's own wait takes the last 2 ms to it). */
        LONGLONG off = g_pacer.next - now.QuadPart, close_by = g_frequency.QuadPart / 500;
        if (!g_pacer.next || off > close_by || off < -close_by)
            Sleep(1);
        else
            SwitchToThread();
    }
    g_frame_done_issued = 0;
}

/* After the present: the event the next frame waits for. */
static void mark_frame_done(IDirect3DDevice9 *dev)
{
    if (g_queue_deep)
        return;
    if (!g_frame_done && FAILED(IDirect3DDevice9_CreateQuery(dev, D3DQUERYTYPE_EVENT, &g_frame_done)))
        g_frame_done = NULL;
    if (g_frame_done && SUCCEEDED(IDirect3DQuery9_Issue(g_frame_done, D3DISSUE_END)))
        g_frame_done_issued = 1;
}

/* Input latency (OPENDMT3_LATENCY_WATCH, measuring only): a press's time, the frame the game first saw it in, and
 * that frame's present done on the GPU. */
static int g_latency_watch = -1;
static LONGLONG g_press_at;
static long g_press_frame = -1;
static double g_latency_sum, g_latency_max;
static LONG g_latency_count;
static IDirect3DQuery9 *g_latency_done;

void ingame_press(void)
{
    if (g_latency_watch < 0) {
        char v[8];
        g_latency_watch = GetEnvironmentVariableA("OPENDMT3_LATENCY_WATCH", v, sizeof v) > 0;
    }
    if (!g_latency_watch)
        return;
    LARGE_INTEGER now;
    QueryPerformanceCounter(&now);
    /* The message's own time (GetMessageTime, ms) is earlier than now by the wait in the queue: counted too. */
    LONG queued = (LONG)(GetTickCount() - (DWORD)GetMessageTime());
    g_press_at = now.QuadPart - (queued > 0 && queued < 1000 ? (LONGLONG)queued * g_frequency.QuadPart / 1000 : 0);
    g_press_frame = -1;
}

/* The game read the mouse's button down: this frame carries the press (the first after it). */
static void press_seen(const BYTE *keys)
{
    if (g_latency_watch > 0 && g_press_at && g_press_frame < 0 && (keys[VK_LBUTTON] & 0x80))
        g_press_frame = ingame_frame() + 1;
}

/* After the present of the frame that carries the press: wait for it on the GPU, then the press's latency. */
static void press_done(IDirect3DDevice9 *dev)
{
    if (g_latency_watch <= 0 || g_press_frame < 0 || g_press_frame != ingame_frame())
        return;
    if (!g_latency_done && FAILED(IDirect3DDevice9_CreateQuery(dev, D3DQUERYTYPE_EVENT, &g_latency_done)))
        g_latency_done = NULL;
    if (g_latency_done && SUCCEEDED(IDirect3DQuery9_Issue(g_latency_done, D3DISSUE_END))) {
        LARGE_INTEGER start, now;
        QueryPerformanceCounter(&start);
        do {
            QueryPerformanceCounter(&now);
        } while (IDirect3DQuery9_GetData(g_latency_done, NULL, 0, D3DGETDATA_FLUSH) == S_FALSE &&
                 now.QuadPart - start.QuadPart < g_frequency.QuadPart / 2);
        double ms = (double)(now.QuadPart - g_press_at) * 1000.0 / (double)g_frequency.QuadPart;
        g_latency_sum += ms;
        g_latency_count++;
        if (ms > g_latency_max)
            g_latency_max = ms;
        ingame_log("latency: press to its frame done %.2f ms (frame %ld; %s; mean %.2f over %ld, longest %.2f)", ms,
                   g_press_frame, g_queue_deep ? "queue as Direct3D allows" : "one frame queued",
                   g_latency_sum / g_latency_count, (long)g_latency_count, g_latency_max);
    }
    g_press_at = 0;
    g_press_frame = -1;
}

/* Wait `ticks` of the counter: sleep while more than 2 ms is left, then spin to the tick (Sleep alone is too
 * coarse for an even frame). */
static void wait_ticks(LONGLONG ticks)
{
    LARGE_INTEGER start, now;
    QueryPerformanceCounter(&start);
    LONGLONG until = start.QuadPart + ticks;
    for (;;) {
        QueryPerformanceCounter(&now);
        LONGLONG left = until - now.QuadPart;
        if (left <= 0)
            return;
        LONGLONG ms = left * 1000 / g_frequency.QuadPart;
        if (ms > 2)
            Sleep((DWORD)(ms - 2));
        else
            YieldProcessor();
    }
}

/* The post-process chain's cost over the counter's two seconds (CPU ticks summed and longest, the GPU's microseconds
 * summed over the frames that had an answer) and over the chip's half second; the passes of the last frame. */
static LONGLONG g_post_sum, g_post_max;
static double g_gpu_sum;
static LONG g_gpu_frames;
static int g_post_passes;
/* Every frame's length, one a line in milliseconds, when OPENDMT3_INGAME_FRAMES names a file (measuring only). */
static FILE *g_series;

/* This frame's chain cost into the counters. */
static void count_post(void)
{
    LONGLONG cpu;
    double gpu;
    post_cost(&cpu, &gpu, &g_post_passes);
    g_post_sum += cpu;
    if (cpu > g_post_max)
        g_post_max = cpu;
    if (gpu >= 0) {
        g_gpu_sum += gpu;
        g_gpu_frames++;
    }
}

/* The safety net: a frame's length with the chain's time; when the chain has made frames late, one step lighter, said
 * in the log, once on the game's screen and in a note for the launcher. */
static int g_safety = -1;
static void safety(double frame_ms)
{
    /* OPENDMT3_SAFETY=off (measuring only: a test that checks the chain's exact picture) keeps the choice as it is. */
    if (g_safety < 0) {
        char v[8];
        g_safety = !(GetEnvironmentVariableA("OPENDMT3_SAFETY", v, sizeof v) > 0 && !lstrcmpiA(v, "off"));
        if (!g_safety)
            ingame_log("post: safety net off (measuring)");
    }
    if (!g_safety || !post_running())
        return;
    LONGLONG cpu;
    double gpu;
    int passes;
    post_cost(&cpu, &gpu, &passes);
    /* The GPU's own time for the passes where the device measures it; the CPU's otherwise (the layer's left out of
     * both: post_cost gives the picture's own). */
    double chain_ms = gpu >= 0 ? gpu / 1000.0 : (double)cpu * 1000.0 / (double)g_frequency.QuadPart;
    /* A frame with a glass panel on the screen (the bar, the menu or the question, a toast) is not judged: a panel is the
     * player's doing (or the net's own toast), never a reason to make the picture lighter. The chip alone is judged:
     * its cost is a fraction of a millisecond. */
    LONGLONG layer_cpu;
    int parts, panels;
    post_layer_cost(&layer_cpu, &parts, &panels);
    if (panels > 0)
        return;
    if (!guard_frame(&g_guard, frame_ms, chain_ms))
        return;
    int up, aa, aa_changed;
    if (post_lighten(&up, &aa, &aa_changed))
        layer_stepped_down(up, aa, aa_changed);
}

/* Frames presented since the start. */
static LONG g_presented;

long ingame_frame(void)
{
    return g_presented;
}

/* The layer's cost over the counter's two seconds: its CPU time (inside the chain's), the frames it drew in. */
static LONGLONG g_layer_cpu, g_layer_cpu_max;
static LONG g_layer_frames;
/* Frames presented while the game was held still in these two seconds (counted in the line's lengths, not as the
 * game's frames). */
static LONG g_held_frames;

/* Each kind of the layer's parts drawn in the counter's two seconds, a line each: the frames it was drawn in and its CPU
 * time a frame there (its upload and draw calls), its GPU time a frame with the diagnostic switch, its pictures drawn
 * again (each a CPU time, the longest, and the upload after); for the chip, the GDI drawings its updates needed (none
 * once its pieces are made). Then the blur's passes. */
static void layer_costs_lines(double f)
{
    static const char *const names[PART_KINDS] = {"fps chip", "bar", "bar chips", "panel", "toast", "mark"};
    LayerCosts c;
    post_layer_costs(&c);
    long redraws[PART_KINDS], gdi;
    long long ticks[PART_KINDS], longest[PART_KINDS];
    layer_redraws(redraws, ticks, longest, &gdi);
    for (int k = 0; k < PART_KINDS; k++) {
        if (!c.frames[k] && !redraws[k])
            continue;
        char gpu[160] = "GPU not measured", again[160] = "";
        if (c.timing == 1 && c.gpu_n[k])
            snprintf(gpu, sizeof gpu, "GPU %.1f us a frame (%ld read)", c.gpu_us[k] / c.gpu_n[k], c.gpu_n[k]);
        if (c.timing == 2 && c.gpu_n[k] && c.gpu9_n[k] && c.idle_n) {
            /* Measuring alone: one draw with the device made idle around it, nine, and the idle round with nothing.
             * The part's whole cost a frame is one draw past the idle round (its state changes and first draw); one
             * more draw past one is its drawing alone. */
            double one = c.gpu_us[k] / c.gpu_n[k], nine = c.gpu9_us[k] / c.gpu9_n[k], idle = c.idle_us / c.idle_n;
            snprintf(gpu, sizeof gpu, "GPU %.1f us a frame (its drawing %.1f; one draw alone %.1f us, nine %.1f, the idle "
                     "round %.1f; %ld and %ld frames)", one - idle, (nine - one) / 8.0, one, nine, idle, c.gpu_n[k],
                     c.gpu9_n[k]);
        }
        if (redraws[k])
            snprintf(again, sizeof again, ", drawn again %ld times at %.1f us (longest %.1f), uploaded %ld times at %.1f us",
                     redraws[k], (double)ticks[k] * 1e6 / f / redraws[k], (double)longest[k] * 1e6 / f, c.uploads[k],
                     c.uploads[k] ? (double)c.upload_ticks[k] * 1e6 / f / c.uploads[k] : 0.0);
        char tail[48] = "";
        if (k == PART_FPS)
            snprintf(tail, sizeof tail, ", %ld GDI drawings in its updates", gdi);
        ingame_log("layer cost %s: %ld frames, CPU %.1f us a frame, %s%s%s", names[k], c.frames[k],
                   c.frames[k] ? (double)c.cpu[k] * 1e6 / f / c.frames[k] : 0.0, gpu, again, tail);
    }
    if (c.composed)
        ingame_log("layer cost compose: %ld parts composed into their own textures", c.composed);
    if (c.blur_passes || c.blur_gpu_n) {
        char gpu[160] = "GPU not measured";
        if (c.timing == 1 && c.blur_gpu_n)
            snprintf(gpu, sizeof gpu, "GPU %.1f us a frame with passes (%ld read)", c.blur_gpu_us / c.blur_gpu_n,
                     c.blur_gpu_n);
        if (c.timing == 2 && c.blur_gpu_n && c.blur_gpu9_n && c.idle_n) {
            /* Measuring alone: a frame's pass(es) once, nine times over, and the idle round with nothing: their whole
             * cost a frame is once past the idle round (its own target's switch included); one more is their work. */
            double one = c.blur_gpu_us / c.blur_gpu_n, nine = c.blur_gpu9_us / c.blur_gpu9_n, idle = c.idle_us / c.idle_n;
            snprintf(gpu, sizeof gpu, "GPU %.1f us a frame with passes (their work %.1f; once alone %.1f us, nine times "
                     "%.1f, the idle round %.1f; %ld and %ld frames)", one - idle, (nine - one) / 8.0, one, nine, idle,
                     c.blur_gpu_n, c.blur_gpu9_n);
        }
        ingame_log("layer cost blur: %ld passes, %s", c.blur_passes, gpu);
    }
    if (c.timing == 3 && c.frame_n)
        ingame_log("layer cost frame: the chain and the layer %.1f us a frame, the device idle before and after (%ld "
                   "frames)", c.frame_us / c.frame_n, c.frame_n);
}

/* The counter's line every two seconds, and the chip's numbers twice a second. `game`: a frame of the game's (0: one
 * of ours while it is held still, which advances none of its timers, its music or its frame number). */
static void count_present(LONGLONG now, int game)
{
    if (game) {
        g_presented++;
        sound_frame();
    } else {
        g_held_frames++;
    }
    g_frames++;
    g_chip_frames++;
    count_post();
    LONGLONG layer_cpu;
    int parts, panels;
    post_layer_cost(&layer_cpu, &parts, &panels);
    if (parts > 0) {
        g_layer_frames++;
        g_layer_cpu += layer_cpu;
        if (layer_cpu > g_layer_cpu_max)
            g_layer_cpu_max = layer_cpu;
    }
    if (g_last_frame) {
        LONGLONG gap = now - g_last_frame;
        /* One more length counted in this window. */
        g_gaps++;
        g_gap_sum += gap;
        g_gap_squares += (double)gap * (double)gap;
        if (gap > g_gap_max)
            g_gap_max = gap;
        LONGLONG quarter = gap * 4000 / g_frequency.QuadPart;
        g_buckets[quarter < BUCKETS ? quarter : BUCKETS - 1]++;
        /* The series and the safety net follow the game's frames only. */
        if (g_series && game)
            fprintf(g_series, "%.4f\n", (double)gap * 1000.0 / (double)g_frequency.QuadPart);
        if (game)
            safety((double)gap * 1000.0 / (double)g_frequency.QuadPart);
    }
    g_last_frame = now;
    if (!g_count_from)
        g_count_from = g_chip_from = now;
    double f = (double)g_frequency.QuadPart;
    if (now - g_chip_from >= g_frequency.QuadPart / 2) {
        /* The chip: frames a second over the last half second (it shows them and the frame's mean length; the chain's
         * own time is in the log's lines, never on the screen). */
        double fps = g_chip_frames * f / (double)(now - g_chip_from);
        /* The number to the layer, which draws the chip's picture again at the next frame inside the chain, from its
         * kept pieces (no GDI work). */
        layer_fps(fps);
        g_chip_frames = 0;
        g_chip_from = now;
    }
    LONGLONG span = now - g_count_from;
    if (span < 2 * g_frequency.QuadPart)
        return;
    /* Every frame's length since the last line; at least one, so the very first window divides by something. */
    int gaps = g_gaps > 0 ? (int)g_gaps : 1;
    double mean = (double)g_gap_sum / gaps, var = g_gap_squares / gaps - mean * mean;
    /* The slowest 1 %: the length that 99 % of the frames stay within; and the frames over 20 ms. */
    LONG seen = 0, over = 0, need = (LONG)(gaps * 0.99);
    double p99 = 0;
    for (int i = 0; i < BUCKETS; i++) {
        if (seen < need && seen + g_buckets[i] >= need)
            p99 = (i + 1) / 4.0;
        seen += g_buckets[i];
        if (i >= 80)
            over += g_buckets[i];
    }
    ingame_log("frames: %.1f a second, frame time %.2f ms (sd %.2f, 99 %% within %.2f, longest %.2f, over 20 ms %.1f %%); "
               "openDMT3 %.1f us a frame (longest %.1f)", (double)g_frames * f / (double)span, mean * 1000 / f,
               (var > 0 ? sqrt(var) : 0) * 1000 / f, p99, (double)g_gap_max * 1000 / f, 100.0 * over / gaps,
               (double)g_layer_sum * 1e6 / f / g_frames, (double)g_layer_max * 1e6 / f);
    if (post_running())
        ingame_log("post: %d passes a frame, CPU %.1f us a frame (longest %.1f), GPU %s", g_post_passes,
                   (double)g_post_sum * 1e6 / f / g_frames, (double)g_post_max * 1e6 / f,
                   g_gpu_frames ? "measured" : "not measured here");
    if (g_refresh_ticks && g_phase_max >= 0) {
        ingame_log("display: ticks at %.2f to %.2f of a refresh (%d Hz)", g_phase_min, g_phase_max, g_refresh_hz);
        /* A display whose raster never moves (a driver that answers the same line every time) gives no phase: the
         * lock would only push the ticks one way, so it stops. */
        if (g_phase_max - g_phase_min <= 0.0) {
            g_refresh_ticks = 0;
            ingame_log("display: the raster position does not move: ticks not kept to the display");
        }
    }
    g_phase_min = 2;
    g_phase_max = -1;
    if (post_running() && g_gpu_frames)
        ingame_log("post: GPU %.1f us a frame over %ld frames", g_gpu_sum / g_gpu_frames, (long)g_gpu_frames);
    /* The layer: in how many frames it drew, its CPU time in them, and the frames presented while the game was held
     * still; then each kind of part's cost (layer_costs_line). */
    ingame_log("layer: drew in %ld of %ld frames, CPU %.1f us a frame drawn (longest %.1f)%s", (long)g_layer_frames,
               (long)g_frames, g_layer_frames ? (double)g_layer_cpu * 1e6 / f / g_layer_frames : 0.0,
               (double)g_layer_cpu_max * 1e6 / f, g_held_frames ? ", the game held still" : "");
    layer_costs_lines(f);
    /* The picture's GPU time by pass, when measured (OPENDMT3_PASS_TIMES=on). */
    post_pass_times_line();
    g_layer_cpu = g_layer_cpu_max = 0;
    g_layer_frames = 0;
    g_held_frames = 0;
    sound_summary();
    g_post_sum = g_post_max = 0;
    g_gpu_sum = 0;
    g_gpu_frames = 0;
    if (g_series)
        fflush(g_series);
    memset(g_buckets, 0, sizeof g_buckets);
    g_frames = 0;
    g_gap_sum = g_gap_max = g_layer_sum = g_layer_max = 0;
    g_gap_squares = 0;
    g_gaps = 0;
    /* g_last_frame is kept: the next frame's length runs from this one, the log's writing in it. */
    g_count_from = now;
}

/* The time openDMT3's own code took in this frame (the hooks add theirs as they run). */
static LONGLONG g_layer_frame;

void ingame_cost(LONGLONG ticks)
{
    g_layer_frame += ticks;
}

/* Holding the game still (the menu or the question open during a song): the game's frame is kept and presented again
 * at 60 a second with the layer over it, the messages pumped here (none reaching the game's own code), its sound
 * stopped where it was; then both go on from where they stopped, the next frame a period after the music. */
static void hold_still(IDirect3DDevice9 *dev, HWND window, const RECT *dst, const RGNDATA *dirty)
{
    long frame = ingame_frame();
    LARGE_INTEGER t, from;
    QueryPerformanceCounter(&from);
    sound_hold();
    layer_holding(1);
    ingame_log("hold: the game held still at frame %ld (a song plays; the menu or the question is open, or the game "
               "is minimised)", frame);
    /* Our own clock for the held frames: 60 a second whatever the pacing (the client's own limiter is in the game's
     * frame, which does not run now). */
    Pacer held;
    pacer_start(&held, g_frequency.QuadPart, GAME_FPS);
    int lost = 0;
    for (;;) {
        if (!layer_pump() || !layer_hold_wanted())
            break;
        /* A lost device (another program took the display): the game must reset it, so it goes on. */
        if (IDirect3DDevice9_TestCooperativeLevel(dev) != D3D_OK) {
            lost = 1;
            break;
        }
        /* Minimised: nothing to show; the hold goes on, the thread resting. */
        if (window && IsIconic(window)) {
            Sleep(16);
            continue;
        }
        wait_previous_frame(dev);
        QueryPerformanceCounter(&t);
        LONGLONG wait = pacer_wait(&held, t.QuadPart);
        if (wait > 0)
            wait_ticks(wait);
        /* The kept frame (the game's back buffer is the chain's, untouched while the game waits) through the chain,
         * the layer over it. */
        const RECT *shown = post_present(dev);
        QueryPerformanceCounter(&t);
        count_present(t.QuadPart, 0);
        real_present(dev, shown, dst, window, dirty);
        mark_frame_done(dev);
        /* The sound's fade out, a step a held frame. */
        sound_hold_step();
    }
    layer_holding(0);
    /* Quitting: the sound only let go; otherwise played again from where it stopped. */
    sound_resume(!layer_quitting());
    QueryPerformanceCounter(&t);
    /* The game's next frame due a period after its music started again, as if the hold had not been. */
    if (g_pacer.period > 0)
        g_pacer.next = t.QuadPart + g_pacer.period;
    ingame_log("hold: the game goes on at frame %ld after %.2f s held%s", ingame_frame(),
               (double)(t.QuadPart - from.QuadPart) / (double)g_frequency.QuadPart, lost ? " (the device was lost)" : "");
}

static HRESULT STDMETHODCALLTYPE our_present(IDirect3DDevice9 *dev, const RECT *src, const RECT *dst, HWND window,
                                             const RGNDATA *dirty)
{
    LARGE_INTEGER t0, now;
    /* The post-process chain first (its time is the frame's work; the wait below is not): what to present. With no
     * chain, the layer goes into the game's own back buffer. */
    const RECT *shown = post_present(dev);
    if (shown)
        src = shown;
    else
        post_layer_without_chain(dev);
    /* The previous frame done on the GPU before this one goes (at most one queued); within the frame's wait below,
     * so it delays nothing that is on time. */
    wait_previous_frame(dev);
    QueryPerformanceCounter(&t0);
    /* Locked to the music while a song plays: the next tick moved towards the music's clock. */
    lock_to_music(t0.QuadPart);
    /* VSync on: the tick kept in the middle of a refresh, read where the display is now against how long until the
     * tick (the display's phase at the tick is now's phase plus that time). */
    if (g_refresh_ticks && g_pacer.next) {
        double phase = refresh_phase(dev);
        if (phase >= 0) {
            double until = (double)(g_pacer.next - t0.QuadPart) / (double)g_refresh_ticks;
            double at_tick = phase + (until > 0 ? until : 0);
            at_tick -= floor(at_tick);
            if (at_tick < g_phase_min)
                g_phase_min = at_tick;
            if (at_tick > g_phase_max)
                g_phase_max = at_tick;
            g_pacer.next += display_lock_step(at_tick, g_refresh_ticks);
        }
    }
    /* Even pacing: each frame leaves on its tick of 60 a second. */
    LONGLONG wait = pacer_wait(&g_pacer, t0.QuadPart);
    if (wait > 0)
        wait_ticks(wait);
    QueryPerformanceCounter(&now);
    count_present(now.QuadPart, 1);
    trace_frame();
    /* The cost of this frame's own work (the wait for the frame's tick is not work), kept for the counter's line. */
    LARGE_INTEGER t1;
    QueryPerformanceCounter(&t1);
    g_layer_frame += (t1.QuadPart - now.QuadPart) + (wait > 0 ? 0 : now.QuadPart - t0.QuadPart);
    g_layer_sum += g_layer_frame;
    if (g_layer_frame > g_layer_max)
        g_layer_max = g_layer_frame;
    g_layer_frame = 0;
    HRESULT hr = real_present(dev, src, dst, window, dirty);
    /* The event the next frame waits for, then the press measured on this frame (measuring only). */
    mark_frame_done(dev);
    /* By pass (OPENDMT3_PASS_TIMES=on): the game's own next frame begins here. */
    post_after_present(dev);
    press_done(dev);
    /* The menu or the question open during a song: the game held still here until it closes. */
    if (SUCCEEDED(hr) && layer_hold_wanted())
        hold_still(dev, window, dst, dirty);
    return hr;
}

static HRESULT STDMETHODCALLTYPE our_reset(IDirect3DDevice9 *dev, D3DPRESENT_PARAMETERS *pp)
{
    /* A reset may change the interval (the game going between window and full screen). */
    if (pp)
        take_parameters(pp);
    /* The queries go before a reset, as every object of the device's own memory does; made again at the next frame. */
    if (g_frame_done) {
        IDirect3DQuery9_Release(g_frame_done);
        g_frame_done = NULL;
        g_frame_done_issued = 0;
    }
    if (g_latency_done) {
        IDirect3DQuery9_Release(g_latency_done);
        g_latency_done = NULL;
    }
    /* The layer's own state block (drawn without the chain) goes too. */
    post_layer_before_reset();
    HRESULT hr;
    if (!post_running() || !pp) {
        hr = real_reset(dev, pp);
    } else {
        /* The chain's objects go first (a reset fails while any default-pool object is alive), Direct3D gets our back
         * buffer's parameters again for the window as it is now, and the objects come back after. */
        post_before_reset(dev);
        D3DPRESENT_PARAMETERS ours = *pp;
        if (!post_prepare(&ours, layer_window(), 0)) {
            hr = real_reset(dev, pp);
        } else {
            hr = real_reset(dev, &ours);
            post_after_reset(dev, hr);
        }
    }
    /* The display's mode may have changed with it (the display lock's refresh). */
    if (SUCCEEDED(hr))
        take_refresh(dev);
    return hr;
}

/* Put a method of the device's table to ours, keeping the real one in *real (once: a second device shares it). */
static void hook_method(IDirect3DDevice9 *dev, int index, void *ours, void **real)
{
    void *was = patch_method(dev, index, ours);
    if (was)
        *real = was;
}

static HRESULT STDMETHODCALLTYPE our_create_device(IDirect3D9 *d3d, UINT adapter, D3DDEVTYPE type, HWND focus,
                                                   DWORD flags, D3DPRESENT_PARAMETERS *pp, IDirect3DDevice9 **out)
{
    HWND game = pp && pp->hDeviceWindow ? pp->hDeviceWindow : focus;
    /* The post-process chain asks Direct3D for its own back buffer (the window's monitor's size); the game's
     * parameters stay as it wrote them, so whatever it reads back of them is what it asked for. */
    D3DPRESENT_PARAMETERS ours;
    int chain = 0;
    if (pp) {
        ours = *pp;
        chain = post_prepare(&ours, game, 1);
    }
    HRESULT hr = real_create_device(d3d, adapter, type, focus, flags, chain ? &ours : pp, out);
    if (FAILED(hr) && chain) {
        /* Not with ours: as the game asked, with no chain. */
        ingame_log("post: the device was not made with the chain's back buffer (0x%08lx): as the game asked",
                   (unsigned long)hr);
        chain = 0;
        hr = real_create_device(d3d, adapter, type, focus, flags, pp, out);
    }
    if (FAILED(hr) || !out || !*out)
        return hr;
    /* Even pacing takes the client's own limiter out only now, when our clock is sure to run at each present. */
    if (g_settings.even_pacing && !g_own_clock)
        g_own_clock = take_out_limiter();
    if (pp)
        take_parameters(pp);
    take_refresh(*out);
    guard_start(&g_guard);
    /* Present (17) and Reset (16) in IDirect3DDevice9's table. */
    hook_method(*out, 17, (void *)our_present, (void **)&real_present);
    hook_method(*out, 16, (void *)our_reset, (void **)&real_reset);
    /* The chain's objects and its turning of the game's back buffer; if they cannot be made, the device goes back to
     * the game's own parameters (nothing of the game's is on it yet). */
    if (chain && !post_attach(*out)) {
        D3DPRESENT_PARAMETERS back = *pp;
        real_reset(*out, &back);
    }
    /* How the game draws, for study, when asked (after ours, so it sees the game's own calls). */
    trace_attach(*out, pp, flags);
    ingame_log("picture: device made for window %p", (void *)game);
    layer_attach(game);
    return hr;
}

static IDirect3D9 *WINAPI our_d3d(UINT version)
{
    IDirect3D9 *d3d = real_d3d(version);
    if (d3d) {
        /* CreateDevice is entry 16 of IDirect3D9's table. */
        void *was = patch_method(d3d, 16, (void *)our_create_device);
        if (was)
            real_create_device = (CreateDeviceFn)was;
    }
    return d3d;
}

/* --------------------------------------------------------------------------------------------- the keyboard */

static BOOL WINAPI our_keys(PBYTE keys)
{
    BOOL ok = real_keys(keys);
    LARGE_INTEGER t0, t1;
    QueryPerformanceCounter(&t0);
    /* Measuring input latency: the first frame whose read sees a press. */
    if (ok && keys)
        press_seen(keys);
    /* The game's view of the keys while the layer holds them (logic.c hold_keys). */
    if (ok && keys)
        g_keys_waiting = hold_keys(keys, layer_holds_input(), g_keys_waiting);
    QueryPerformanceCounter(&t1);
    /* Its cost counts with the frame's (the game reads the keys once a frame). */
    ingame_cost(t1.QuadPart - t0.QuadPart);
    return ok;
}

/* ------------------------------------------------------------------------------------------- the game's pointer */

/* The game reads its pointer with GetCursorPos through the display fix's helper (opendmt3/core/cabinet/display.py,
 * hook_gcp), which takes the client's origin off and scales from the client's size to 1280x768: right for a picture
 * that fills the client, off by the bars and the scale when the game's shape is kept, and a pixel early where a screen
 * pixel's centre lies past a game pixel's edge. The point it is handed is turned so that its sums give the game pixel
 * under the pointer's pixel in the picture as the chain placed it (logic.c pointer_for_game); only in the client the
 * fix is in (its first call site calls the helper), whose sums these are. */
typedef BOOL(WINAPI *CursorGet)(LPPOINT);
static CursorGet real_cursor;
/* Whether the display fix's helper is in the game (-1: not looked yet); the window its sums use (its own variable). */
static int g_fix_in = -1;
#define FIX_CALL_SITE 0x70ECC7u
#define FIX_HELPER 0x19E63400u
#define FIX_WINDOW 0x19A0BC18u
/* The last client point logged (measuring only: OPENDMT3_POINTER_LOG). */
static int g_pointer_log = -1;
static POINT g_pointer_logged = {-100000, -100000};

/* Memory of the game's image that can be read (a client without the fix may not have these addresses at all). */
static int readable(DWORD at, DWORD size)
{
    MEMORY_BASIC_INFORMATION m;
    if (!VirtualQuery((const void *)(uintptr_t)at, &m, sizeof m) || m.State != MEM_COMMIT ||
        (m.Protect & (PAGE_NOACCESS | PAGE_GUARD)))
        return 0;
    return at + size <= (DWORD)(uintptr_t)m.BaseAddress + (DWORD)m.RegionSize;
}

static BOOL WINAPI our_cursor(LPPOINT p)
{
    BOOL ok = real_cursor(p);
    if (!ok || !p)
        return ok;
    /* Looked for once: a call (E8) to the helper at the fix's first call site. */
    if (g_fix_in < 0) {
        const BYTE *at = (const BYTE *)(uintptr_t)FIX_CALL_SITE;
        LONG rel = 0;
        if (readable(FIX_CALL_SITE, 5) && at[0] == 0xE8)
            memcpy(&rel, at + 1, sizeof rel);
        g_fix_in = rel && (DWORD)(FIX_CALL_SITE + 5 + (DWORD)rel) == FIX_HELPER && readable(FIX_WINDOW, 4);
        ingame_log("pointer: %s", g_fix_in ? "the display fix's helper reads it: turned to the picture's place"
                                           : "no display fix in this client: left as it is");
    }
    if (!g_fix_in)
        return ok;
    /* The window the helper's sums use, its client size, and the pointer there. */
    HWND w = *(HWND volatile *)(uintptr_t)FIX_WINDOW;
    POINT c = *p;
    RECT rc;
    if (!w || !ScreenToClient(w, &c) || !GetClientRect(w, &rc) || rc.right <= 0 || rc.bottom <= 0)
        return ok;
    /* The picture's place (no chain: the whole client, Direct3D's own stretch). */
    PicRect r;
    post_picture(&r.x, &r.y, &r.w, &r.h);
    if (r.w <= 0 || r.h <= 0) {
        r.x = r.y = 0;
        r.w = rc.right;
        r.h = rc.bottom;
    }
    int qx, qy;
    pointer_for_game(c.x, c.y, rc.right, rc.bottom, r, &qx, &qy);
    POINT q = {qx, qy};
    if (!ClientToScreen(w, &q))
        return ok;
    *p = q;
    /* Measuring: each new client point and the game pixel the helper's sums make of it. */
    if (g_pointer_log < 0) {
        char v[4];
        g_pointer_log = GetEnvironmentVariableA("OPENDMT3_POINTER_LOG", v, sizeof v) > 0;
    }
    if (g_pointer_log && (c.x != g_pointer_logged.x || c.y != g_pointer_logged.y)) {
        int gx, gy;
        game_from_client(qx, qy, rc.right, rc.bottom, &gx, &gy);
        ingame_log("pointer: client %ld,%ld of %ldx%ld, the picture %d,%d %dx%d: the game's pixel %d,%d", c.x, c.y,
                   rc.right, rc.bottom, r.x, r.y, r.w, r.h, gx, gy);
        g_pointer_logged = c;
    }
    return ok;
}

/* ------------------------------------------------------------------------------------------------- attaching */

/* Turn every import we replace; logs what it found. Returns how many slots were changed. */
static int hook_all(void)
{
    HMODULE game = GetModuleHandleA(NULL);
    HMODULE dsound = GetModuleHandleA("dsound.dll"), d3d9 = GetModuleHandleA("d3d9.dll");
    HMODULE user32 = GetModuleHandleA("user32.dll");
    /* The real functions: only from modules the game already has (loading one here, in DllMain, is not allowed). */
    real_ds8 = dsound ? (DsCreate8)(void *)GetProcAddress(dsound, "DirectSoundCreate8") : NULL;
    real_ds = dsound ? (DsCreate)(void *)GetProcAddress(dsound, "DirectSoundCreate") : NULL;
    real_d3d = d3d9 ? (D3dCreate)(void *)GetProcAddress(d3d9, "Direct3DCreate9") : NULL;
    real_keys = user32 ? (KeysGet)(void *)GetProcAddress(user32, "GetKeyboardState") : NULL;
    real_cursor = user32 ? (CursorGet)(void *)GetProcAddress(user32, "GetCursorPos") : NULL;
    int sound = ingame_patch_imports(game, (void *)real_ds8, (void *)our_ds8) + ingame_patch_imports(game, (void *)real_ds, (void *)our_ds);
    int picture = ingame_patch_imports(game, (void *)real_d3d, (void *)our_d3d);
    int keys = ingame_patch_imports(game, (void *)real_keys, (void *)our_keys);
    int pointer = ingame_patch_imports(game, (void *)real_cursor, (void *)our_cursor);
    ingame_log("hooks: sound %d, picture %d, keys %d, pointer %d", sound, picture, keys, pointer);
    return sound + picture + keys + pointer;
}

/* The measurement of whether the game's speed follows its frame rate: the client's limiter out and no clock of ours
 * (OPENDMT3_INGAME_UNLOCK; never set by the launcher). */
static void unlock_measure(void)
{
    char value[4];
    if (GetEnvironmentVariableA("OPENDMT3_INGAME_UNLOCK", value, sizeof value) && take_out_limiter())
        ingame_log("unlock: the client's 60 a second limiter taken out (measurement only)");
}

void ingame_attach(HMODULE module)
{
    g_module = module;
    settings_default(&g_settings);
    /* Each of the launcher's choices from its variable (none: the defaults). */
    /* (logic.c's list: the chip's corner was missing from the one kept here, so the launcher's Position never reached
     * the layer.) */
    const char *const *names = SETTINGS_NAMES;
    for (int i = 0; i < SETTINGS_COUNT; i++) {
        char value[128];
        DWORD got = GetEnvironmentVariableA(names[i], value, sizeof value);
        if (got && got < sizeof value)
            settings_read(&g_settings, names[i], value);
    }
    char device[39];
    format_guid(g_settings.device, device);
    ingame_log("start: language %s, cursor %s, pacing %s, frame rate chip %s, sound device %s, upscale %s, sharpness %d, "
               "anti-aliasing %s", g_settings.korean ? "ko" : "en", g_settings.cursor ? "ours" : "the game's",
               g_settings.music_lock ? "music" : g_settings.even_pacing ? "even" : "the client's own",
               g_settings.show_fps ? "on" : "off",
               g_settings.has_device ? device : "default", UPSCALE_NAMES[g_settings.upscale], g_settings.sharpness,
               AA_NAMES[g_settings.antialiasing]);
    QueryPerformanceFrequency(&g_frequency);
    /* Measuring only: every frame's length into a file. */
    char series[MAX_PATH];
    DWORD got_series = GetEnvironmentVariableA("OPENDMT3_INGAME_FRAMES", series, sizeof series);
    if (got_series && got_series < sizeof series)
        g_series = fopen(series, "w");
    g_hooked = hook_all() > 0;
    /* The client's file calls: openDMT3's own files in the game's place (files.c), before the client opens any. */
    files_attach();
    unlock_measure();
}

void ingame_hook_late(void)
{
    /* Once is enough: a slot already ours no longer holds the real address. */
    if (g_hooked)
        return;
    g_hooked = 1;
    hook_all();
}
