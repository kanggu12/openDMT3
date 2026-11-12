/*
 * The game's sound through DSOAL and OpenAL Soft (ingame.h openal_create): DSOAL is a DirectSound of its own that
 * plays each DirectSound buffer as an OpenAL source, and OpenAL Soft mixes them and writes the mix to the device
 * through WASAPI, in shared mode or in exclusive mode (the launcher's Mixer). Windows' own DirectSound mixer and, in
 * exclusive mode, Windows' shared audio engine are out of the way.
 *
 * Both libraries sit beside this DLL in openDMT3's folder: OpenAL Soft as dsoal-aldrv.dll (the name DSOAL loads it
 * by), DSOAL as openDMT3-dsoal.dll (not dsound.dll: Windows' own stays the game's import, the way back). OpenAL Soft is
 * loaded first by its whole path, so DSOAL's own load of it by name finds it loaded. OpenAL Soft's settings come from
 * openDMT3-alsoft.ini, written beside this DLL here and named in ALSOFT_CONF, read after any of the player's own. Both
 * libraries read the C runtime's copy of the environment (msvcrt.dll's, which this DLL shares with them), made when it
 * was loaded and never updated by Windows' own SetEnvironmentVariable: the name goes in through the runtime's own
 * _wputenv, which sets Windows' copy too.
 *
 * Any failure (a library missing or refusing, DSOAL's DirectSoundCreate8 failing) gives back nothing, and the caller
 * opens Windows' own DirectSound as it would have: the log says which step failed.
 */
#include "ingame.h"

#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>

/* DSOAL's DirectSoundCreate8, as Windows' own is called. */
typedef HRESULT(WINAPI *Create8Fn)(LPCGUID, void **, void *);

/* OpenAL Soft's settings for the game: WASAPI only; 256-frame updates, two of them (5.3 ms each at 48 kHz: its own
 * default is 512 frames and three); the game's sound as it is made, with no 3D processing of its own (plain panning
 * even on headphones, no HRTF, no crossfeed: the game's buffers are plain stereo and mono); its band-limited resampler
 * for the game's 44.1 kHz buffers on a 48 kHz device. Exclusive mode when the path asks for it. */
static int write_settings(int exclusive, WCHAR *path, size_t room)
{
    if (!ingame_beside(L"openDMT3-alsoft.ini", path, room))
        return 0;
    FILE *f = _wfopen(path, L"w");
    if (!f)
        return 0;
    fprintf(f, "[general]\ndrivers = wasapi\nperiod_size = 256\nperiods = 2\nstereo-mode = speakers\n"
               "stereo-encoding = basic\ncf_level = 0\nresampler = bsinc12\n\n[wasapi]\nexclusive-mode = %s\n"
               "allow-resampler = true\n", exclusive ? "true" : "false");
    return fclose(f) == 0;
}

void *openal_create(LPCGUID device, int exclusive, const char **failed, unsigned long *hr)
{
    WCHAR driver[MAX_PATH * 4], dsoal[MAX_PATH * 4], settings[MAX_PATH * 4];
    *hr = 0;
    /* Both libraries beside this DLL; their absence is the first way back. */
    if (!ingame_beside(L"dsoal-aldrv.dll", driver, MAX_PATH * 4) ||
        !ingame_beside(L"openDMT3-dsoal.dll", dsoal, MAX_PATH * 4)) {
        ingame_log("sound: OpenAL Soft's path is too long: Windows' DirectSound");
        *failed = "path";
        return NULL;
    }
    /* Its settings first: OpenAL Soft reads them once, at its first device's opening (inside DSOAL's
     * DirectSoundCreate8 below), from the runtime's copy of the environment. */
    WCHAR assignment[MAX_PATH * 4 + 16];
    if (!write_settings(exclusive, settings, MAX_PATH * 4) ||
        _snwprintf(assignment, MAX_PATH * 4 + 16, L"ALSOFT_CONF=%ls", settings) < 0 || _wputenv(assignment) != 0 ||
        /* Windows' own copy as well, whatever the runtime's _wputenv does with it. */
        !SetEnvironmentVariableW(L"ALSOFT_CONF", settings)) {
        ingame_log("sound: OpenAL Soft's settings were not written: Windows' DirectSound");
        *failed = "settings";
        return NULL;
    }
    /* OpenAL Soft by its whole path: DSOAL's load of it by its name then finds it already loaded. */
    HMODULE al = LoadLibraryW(driver);
    if (!al) {
        *hr = GetLastError();
        ingame_log("sound: OpenAL Soft (dsoal-aldrv.dll) did not load (%lu): Windows' DirectSound", *hr);
        *failed = "openal";
        return NULL;
    }
    HMODULE ds = LoadLibraryW(dsoal);
    Create8Fn create = ds ? (Create8Fn)(void *)GetProcAddress(ds, "DirectSoundCreate8") : NULL;
    if (!create) {
        *hr = GetLastError();
        ingame_log("sound: DSOAL (openDMT3-dsoal.dll) did not load (%lu): Windows' DirectSound", *hr);
        *failed = "dsoal";
        /* Our own references given back (OpenAL Soft and DSOAL each keep themselves loaded once they are: unused). */
        if (ds)
            FreeLibrary(ds);
        FreeLibrary(al);
        return NULL;
    }
    void *object = NULL;
    HRESULT result = create(device, &object, NULL);
    if (FAILED(result) || !object) {
        /* DSOAL could not open the device through OpenAL Soft (exclusive mode refused, no WASAPI device): the
         * libraries stay loaded (each keeps itself loaded once it is), unused. */
        *hr = (unsigned long)result;
        ingame_log("sound: DSOAL did not open the device (0x%08lx): Windows' DirectSound", *hr);
        *failed = "device";
        return NULL;
    }
    ingame_log("sound: the game's sound goes through DSOAL and OpenAL Soft on WASAPI, %s mode",
               exclusive ? "exclusive" : "shared");
    return object;
}
