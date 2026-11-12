/*
 * The shared sound engine's period (ingame.h engine_start). Windows 10's audio engine mixes each output device in steps
 * of its period, 10 ms unless a program asks for less through IAudioClient3; while one does, every program on that
 * device in shared mode, the game's DirectSound among them, goes in those shorter steps, and the 10 ms come back when
 * it stops (Microsoft, "Low Latency Audio"). So on the device the game's DirectSound object opened, openDMT3 asks for
 * the shortest period its driver offers with a silent stream of its own, started and never written to, and holds it
 * until the game's process ends.
 *
 * Where there is nothing to gain, nothing is held: no IAudioClient3 (Windows before 10), a driver whose shortest period
 * is its default (many makers' own drivers keep 10 ms), another program's stream holding the engine at a period of its
 * own, a refusal, or an engine that keeps its period anyway (Wine, which has no shared engine). The in-game log says
 * which, with the periods asked and got, and so does the launcher's note beside the DLL (openDMT3-sound.txt), which the
 * launcher logs when the game ends and shows on its Sound page.
 *
 * It all runs on a thread of its own in COM's multithreaded apartment: the game's thread never joins an apartment it
 * did not choose, and the game's start never waits for Windows' audio service. COM's library is loaded there too, so
 * the DLL's own imports stay as they were (it is loaded before the game's own code runs).
 */
#define COBJMACROS
#include "ingame.h"

/* initguid.h first: this file then holds the audio interfaces' GUIDs itself (no other file of the DLL names them). */
#include <initguid.h>
#include <mmsystem.h>
#include <mmdeviceapi.h>
#include <audioclient.h>
#include <functiondiscoverykeys_devpkey.h>
#include <stdio.h>
#include <string.h>

/* DirectSound's name for Windows' default output, this file's own copy (hooks.c holds dsound.h's). */
static const GUID DEFAULT_PLAYBACK = {0xdef00000, 0x9c6d, 0x47ed, {0xaa, 0xf1, 0x4d, 0xda, 0x8f, 0x2b, 0x5c, 0x03}};

/* COM's calls this file makes, found in ole32.dll once the thread has loaded it. */
typedef HRESULT(WINAPI *CoInitFn)(LPVOID, DWORD);
typedef void(WINAPI *CoUninitFn)(void);
typedef HRESULT(WINAPI *CoCreateFn)(REFCLSID, LPUNKNOWN, DWORD, REFIID, LPVOID *);
typedef void(WINAPI *CoFreeFn)(LPVOID);
typedef HRESULT(WINAPI *PropClearFn)(PROPVARIANT *);
static CoCreateFn co_create;
static CoFreeFn co_free;
static PropClearFn prop_clear;
/* DirectSound's GetDeviceID: the device DirectSound itself means by Windows' default output. */
typedef HRESULT(WINAPI *DeviceIdFn)(LPCGUID, LPGUID);

/* The device the game's DirectSound object opened, handed to the thread: its DirectSound GUID, and whether it is the
 * launcher's chosen one (or Windows' default output). */
static GUID g_device;
static int g_chosen;
/* Started once a process (the game opens DirectSound once; a second open changes nothing here). */
static LONG g_started;

void sound_note(const char *line, int first)
{
    WCHAR path[MAX_PATH * 4];
    /* Beside the DLL, in openDMT3's folder (the client data is only read). */
    if (!ingame_beside(L"openDMT3-sound.txt", path, MAX_PATH * 4))
        return;
    /* The run's first line starts the note again (the last run's is gone); the rest follow it. */
    FILE *f = _wfopen(path, first ? L"w" : L"a");
    if (!f)
        return;
    fprintf(f, "%s\n", line);
    fclose(f);
}

/* The launcher's note: the engine's line after the mixer's (hooks.c writes that one first, when the game opens its
 * sound). */
static void note(const EngineReport *r)
{
    char line[256];
    engine_note(r, line, sizeof line);
    sound_note(line, 0);
}

/* The report into the log (its numbers in milliseconds too) and the launcher's note, in one place for every result. */
static void report(const EngineReport *r, const char *device, const char *name)
{
    if (!r->rate) {
        /* Ended before the device's format was read (off, no device, no IAudioClient3): no periods to give. */
        ingame_log("sound: the engine's period on %s (%s): %s (0x%08lx)", name, device, ENGINE_NAMES[r->result], r->hr);
    } else {
        ingame_log("sound: the engine's period on %s (%s): %s; asked %u frames (%.2f ms), got %u (%.2f ms), before %u "
                   "(%.2f ms); the driver's default %u (%.2f ms), shortest %u (%.2f ms), longest %u, in steps of %u, "
                   "at %u Hz; 0x%08lx", name, device, ENGINE_NAMES[r->result], r->asked, engine_ms(r->asked, r->rate),
                   r->got, engine_ms(r->got, r->rate), r->before, engine_ms(r->before, r->rate), r->def,
                   engine_ms(r->def, r->rate), r->min, engine_ms(r->min, r->rate), r->max, r->step, r->rate, r->hr);
    }
    note(r);
}

/* An endpoint's property as text (UTF-8 into `out`, empty when it has none). */
static void property_text(IPropertyStore *ps, const PROPERTYKEY *key, char *out, int size)
{
    PROPVARIANT pv;
    out[0] = 0;
    PropVariantInit(&pv);
    /* A wide string, as both properties read here are. */
    if (SUCCEEDED(IPropertyStore_GetValue(ps, key, &pv)) && pv.vt == VT_LPWSTR && pv.pwszVal &&
        !WideCharToMultiByte(CP_UTF8, 0, pv.pwszVal, -1, out, size, NULL, NULL))
        /* Too long for the room (a renamed device): no text, never one left without its end. */
        out[0] = 0;
    prop_clear(&pv);
}

/* The render endpoint whose DirectSound GUID (PKEY_AudioEndpoint_GUID, the link Windows keeps between the two names of
 * one device) is `want`, with its friendly name; NULL when none of the active ones is. */
static IMMDevice *endpoint_of(IMMDeviceEnumerator *en, const GUID *want, char *name, int size)
{
    IMMDeviceCollection *all = NULL;
    UINT n = 0;
    /* Only the active ones: a device unplugged cannot be the one the game just opened. */
    if (FAILED(IMMDeviceEnumerator_EnumAudioEndpoints(en, eRender, DEVICE_STATE_ACTIVE, &all)) ||
        FAILED(IMMDeviceCollection_GetCount(all, &n)))
        n = 0;
    IMMDevice *found = NULL;
    for (UINT i = 0; i < n && !found; i++) {
        IMMDevice *d = NULL;
        IPropertyStore *ps = NULL;
        if (FAILED(IMMDeviceCollection_Item(all, i, &d)))
            continue;
        if (SUCCEEDED(IMMDevice_OpenPropertyStore(d, STGM_READ, &ps))) {
            char text[64];
            uint8_t bytes[16];
            property_text(ps, &PKEY_AudioEndpoint_GUID, text, sizeof text);
            /* The GUID as text, read into the structure's bytes as the launcher's choice is (logic.c parse_guid). */
            if (parse_guid(text, bytes) && !memcmp(bytes, want, sizeof bytes)) {
                property_text(ps, &PKEY_Device_FriendlyName, name, size);
                found = d;
            }
            IPropertyStore_Release(ps);
        }
        /* Kept only when it is the one. */
        if (!found)
            IMMDevice_Release(d);
    }
    if (all)
        IMMDeviceCollection_Release(all);
    return found;
}

/* Ask for the shortest period on `device` (its DirectSound GUID): fills the report; the started stream in *held when
 * the engine runs at a shorter period with it (the caller keeps it for good), NULL otherwise. */
static void ask(IMMDeviceEnumerator *en, const GUID *device, EngineReport *r, IAudioClient3 **held, char *name,
                int size)
{
    *held = NULL;
    IMMDevice *d = endpoint_of(en, device, name, size);
    if (!d) {
        r->result = ENGINE_NO_DEVICE;
        return;
    }
    IAudioClient3 *c = NULL;
    /* IAudioClient3 is Windows 10's: its absence is Windows 8.1 or older. */
    r->hr = (unsigned long)IMMDevice_Activate(d, &IID_IAudioClient3, CLSCTX_ALL, NULL, (void **)&c);
    IMMDevice_Release(d);
    if (FAILED((HRESULT)r->hr) || !c) {
        r->result = ENGINE_NO_CLIENT3;
        return;
    }
    WAVEFORMATEX *mix = NULL;
    /* The engine's own format: a shared stream is made in it, and the periods are counted at its rate. */
    r->hr = (unsigned long)IAudioClient3_GetMixFormat(c, &mix);
    if (SUCCEEDED((HRESULT)r->hr) && mix) {
        r->rate = mix->nSamplesPerSec;
        r->hr = (unsigned long)IAudioClient3_GetSharedModeEnginePeriod(c, mix, &r->def, &r->step, &r->min, &r->max);
    }
    if (FAILED((HRESULT)r->hr) || !mix) {
        r->result = ENGINE_NO_ANSWER;
    } else {
        WAVEFORMATEX *now = NULL;
        /* The engine's period before the ask (another program's stream may hold it shorter already). */
        if (SUCCEEDED(IAudioClient3_GetCurrentSharedModeEnginePeriod(c, &now, &r->before)) && now)
            co_free(now);
        r->asked = engine_period_ask(r->def, r->step, r->min, r->max);
        if (!r->asked) {
            /* Nothing shorter than the default, or numbers no stream can be made from. */
            int sane = r->def && r->step && r->min && r->max && r->min <= r->def && r->def <= r->max;
            r->result = sane ? ENGINE_NONE_SHORTER : ENGINE_NO_ANSWER;
        } else {
            /* No flags: a stream that is never written to needs no event; the process's own session, as the
             * game's DirectSound has. */
            r->hr = (unsigned long)IAudioClient3_InitializeSharedAudioStream(c, 0, r->asked, mix, NULL);
            if ((HRESULT)r->hr == AUDCLNT_E_ENGINE_PERIODICITY_LOCKED) {
                /* Another program's stream holds the engine at a period of its own: what it holds is what plays. */
                r->result = ENGINE_LOCKED;
                r->got = r->before;
            } else if (FAILED((HRESULT)r->hr)) {
                r->result = ENGINE_REFUSED;
            } else if (FAILED((HRESULT)(r->hr = (unsigned long)IAudioClient3_Start(c)))) {
                r->result = ENGINE_REFUSED;
            } else {
                /* The engine's period with the stream running, read again after a moment if it has not moved yet. */
                for (int tries = 0; tries < 2; tries++) {
                    now = NULL;
                    if (SUCCEEDED(IAudioClient3_GetCurrentSharedModeEnginePeriod(c, &now, &r->got)) && now)
                        co_free(now);
                    if (engine_period_held(r->def, r->got))
                        break;
                    Sleep(50);
                }
                if (engine_period_held(r->def, r->got)) {
                    r->result = ENGINE_HELD;
                    /* The caller keeps it, running, until the process ends. */
                    *held = c;
                    c = NULL;
                } else {
                    /* Nothing moved: the stream is let go. */
                    r->result = ENGINE_UNCHANGED;
                    IAudioClient3_Stop(c);
                }
            }
        }
    }
    if (mix)
        co_free(mix);
    if (c)
        IAudioClient3_Release(c);
}

static DWORD WINAPI engine_thread(LPVOID unused)
{
    (void)unused;
    EngineReport r;
    memset(&r, 0, sizeof r);
    /* Which device the report is of, for the launcher (it shows the result beside that device's choice only). */
    r.chosen = g_chosen;
    if (!g_chosen) {
        /* Windows' default output, as DirectSound itself names it (it is what the game opened): asked here, so the
         * game's own thread never waits for Windows' audio service. */
        HMODULE ds = GetModuleHandleA("dsound.dll");
        DeviceIdFn id = ds ? (DeviceIdFn)(void *)GetProcAddress(ds, "GetDeviceID") : NULL;
        if (!id || FAILED((HRESULT)(r.hr = (unsigned long)id(&DEFAULT_PLAYBACK, &g_device)))) {
            r.result = ENGINE_NO_DEVICE;
            report(&r, "-", "Windows' default output");
            return 0;
        }
    }
    memcpy(r.device, &g_device, sizeof r.device);
    char device[39], name[256] = "";
    format_guid((const uint8_t *)&g_device, device);
    /* COM from its own library (loaded here, never in DllMain), in this thread's own multithreaded apartment. */
    HMODULE ole = LoadLibraryW(L"ole32.dll");
    CoInitFn co_init = ole ? (CoInitFn)(void *)GetProcAddress(ole, "CoInitializeEx") : NULL;
    CoUninitFn co_uninit = ole ? (CoUninitFn)(void *)GetProcAddress(ole, "CoUninitialize") : NULL;
    co_create = ole ? (CoCreateFn)(void *)GetProcAddress(ole, "CoCreateInstance") : NULL;
    co_free = ole ? (CoFreeFn)(void *)GetProcAddress(ole, "CoTaskMemFree") : NULL;
    prop_clear = ole ? (PropClearFn)(void *)GetProcAddress(ole, "PropVariantClear") : NULL;
    if (!co_init || !co_uninit || !co_create || !co_free || !prop_clear ||
        FAILED((HRESULT)(r.hr = (unsigned long)co_init(NULL, COINIT_MULTITHREADED)))) {
        /* No COM: no way to look for the device at all. */
        r.result = ENGINE_NO_DEVICE;
        report(&r, device, "?");
        return 0;
    }
    IMMDeviceEnumerator *en = NULL;
    IAudioClient3 *held = NULL;
    r.hr = (unsigned long)co_create(&CLSID_MMDeviceEnumerator, NULL, CLSCTX_ALL, &IID_IMMDeviceEnumerator,
                                    (void **)&en);
    if (FAILED((HRESULT)r.hr) || !en) {
        /* No device enumerator (no audio service): nothing to find the device with. */
        r.result = ENGINE_NO_DEVICE;
    } else {
        ask(en, &g_device, &r, &held, name, sizeof name);
        IMMDeviceEnumerator_Release(en);
    }
    report(&r, device, name[0] ? name : "?");
    /* Held: the stream kept running (and this thread with its apartment) until the game's process ends, when Windows
     * lets the stream go and the engine goes back to its own period. */
    while (held)
        Sleep(INFINITE);
    /* Nothing held: the apartment let go, as it was joined. */
    co_uninit();
    return 0;
}

void engine_start(const uint8_t *chosen)
{
    /* Once a process. */
    if (InterlockedExchange(&g_started, 1))
        return;
    EngineReport r;
    memset(&r, 0, sizeof r);
    /* Which device a report is of: the chosen one's GUID, or Windows' default output (its GUID found on the thread). */
    g_chosen = r.chosen = chosen != NULL;
    if (chosen) {
        /* The chosen device, as the game's DirectSound object opened it. */
        memcpy(&g_device, chosen, sizeof g_device);
        memcpy(r.device, chosen, sizeof r.device);
    }
    if (!g_settings.low_latency) {
        /* The launcher's Low latency off: said, and nothing asked. */
        r.result = ENGINE_OFF;
        report(&r, "-", "the game's output");
        return;
    }
    /* The rest on a thread of its own (its handle is not needed: it ends with the process or by itself). */
    HANDLE t = CreateThread(NULL, 0, engine_thread, NULL, 0, NULL);
    if (!t) {
        /* No thread to ask from: said with its error, nothing asked. */
        r.result = ENGINE_REFUSED;
        r.hr = GetLastError();
        report(&r, "-", "the game's output");
        return;
    }
    CloseHandle(t);
}
