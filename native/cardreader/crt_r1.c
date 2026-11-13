/*
 * openDMT3's stand-in for the cabinet's card reader library, CRT_R1.dll.
 *
 * The game opens the reader with CommOpen("Com6"); on its card screen it asks RF_DetectCard every frame, and
 * when a card is there it reads the card's UID, loads the sector key and reads blocks 1 and 2 of sector 0:
 * the first 20 bytes are the card number it sends to the server. The cabinet's reader is a serial device; a
 * PC has none, so this library answers from a text file instead.
 *
 * The card is the file openDMT3-card.txt beside this DLL, in openDMT3's folder (or the path in OPENDMT3_CARD_FILE):
 * while it exists and starts with 1 to 20 printable characters, a card with that number is in the reader. The
 * launcher writes the chosen player's card number there before it starts the game.
 * With OPENDMT3_CARD_LOG set, every call is appended to that file (empty value: openDMT3-card.log beside the DLL).
 *
 * Every export is __stdcall with the argument sizes of the original library (crt_r1.def keeps the plain names
 * the game imports). The game imports these ten of the original's 68 exports and nothing else; the library's three
 * others (openDMT3_touch_*, touch.c) are for openDMT3's own multiDLL.dll, the touch screen's.
 *
 * The game loads this library by name before its own code runs, in every way of playing, so it also carries
 * openDMT3's in-game layer (ingame.h): DllMain starts it. Without a card file the reader is simply empty, and the
 * game's NO ID CARD plays as a guest.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "ingame.h"

#define API __declspec(dllexport) __stdcall

/* The card number, at most 20 characters, zero-terminated. */
static char g_card[21];
/* Blocks a game may write (it keeps 16 bytes of its own in sector 15); held while the game runs. */
static BYTE g_store[16][4][16];

/* Append one line to the call log, when the log is turned on. */
static void trace(const char *fmt, ...)
{
    WCHAR path[MAX_PATH * 4];
    /* No variable: no log (the normal case). A value too long for the buffer comes back as the size it needs,
       with nothing written: not a path to open. */
    DWORD got = GetEnvironmentVariableW(L"OPENDMT3_CARD_LOG", path, MAX_PATH * 4);
    if (!got || got >= MAX_PATH * 4)
        return;
    /* An empty value means the default name beside this DLL (openDMT3's folder). */
    if (!path[0] && !ingame_beside(L"openDMT3-card.log", path, MAX_PATH * 4))
        return;
    FILE *f = _wfopen(path, L"a");
    if (!f)
        return;
    va_list ap;
    va_start(ap, fmt);
    vfprintf(f, fmt, ap);
    va_end(ap);
    fputc('\n', f);
    fclose(f);
}

/* Read the card number from the card file; its length, or 0 when no card is in the reader. */
static int load_card(void)
{
    WCHAR path[MAX_PATH * 4];
    /* The launcher may name another file; otherwise the one beside this DLL (openDMT3's folder, where the launcher
       writes it at PLAY). A value too long for the buffer comes back as the size it needs, with nothing written: the
       default then. Wide, so a folder with any letters works. */
    DWORD got = GetEnvironmentVariableW(L"OPENDMT3_CARD_FILE", path, MAX_PATH * 4);
    memset(g_card, 0, sizeof g_card);
    if ((!got || got >= MAX_PATH * 4) && !ingame_beside(L"openDMT3-card.txt", path, MAX_PATH * 4))
        return 0;
    FILE *f = _wfopen(path, L"rb");
    /* No file: no card. */
    if (!f)
        return 0;
    char buf[64] = {0};
    size_t n = fread(buf, 1, sizeof buf - 1, f);
    fclose(f);
    int len = 0;
    /* The first word only: a line ending or a space ends the number. */
    for (size_t i = 0; i < n && len < 20; i++) {
        unsigned char c = (unsigned char)buf[i];
        if (c < 0x21 || c > 0x7e)
            break;
        g_card[len++] = (char)c;
    }
    return len;
}

/* The library is loaded: the in-game layer starts (its settings, the game's imports turned to ours). */
BOOL WINAPI DllMain(HINSTANCE module, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        /* No calls for each thread the game starts: nothing here needs them. */
        DisableThreadLibraryCalls(module);
        ingame_attach(module);
    }
    return TRUE;
}

/* Open the reader: any non-zero handle, which the game only passes back (it treats 0 as no reader). */
API HANDLE CommOpen(const char *port)
{
    /* If the game's imports were not bound yet when DllMain ran, they are now: turn them to ours here. */
    ingame_hook_late();
    trace("CommOpen(%s)", port ? port : "(null)");
    return (HANDLE)1;
}

/* Close the reader: nothing to release. */
API int CommClose(HANDLE h)
{
    trace("CommClose(%p)", h);
    return 0;
}

/* Serial settings ("9600,n,8,1"): accepted, there is no port. */
API int CommSetting(HANDLE h, const char *setting)
{
    trace("CommSetting(%p, %s)", h, setting ? setting : "(null)");
    return 0;
}

/* Reader status: always ready. */
API int CRT286_GetStatus(HANDLE h, BYTE *status)
{
    if (status)
        *status = 0;
    trace("CRT286_GetStatus");
    return 0;
}

/* Eject: the card stays as long as its file does (the launcher writes the file at PLAY). */
API int CRT286_Eject(HANDLE h)
{
    trace("CRT286_Eject");
    return 0;
}

/* Is a card in the reader? 0 means yes, as the original answers. The file is read again each time, so a
 * new player's card is seen at the next card screen. */
API int RF_DetectCard(HANDLE h)
{
    ingame_hook_late();
    int len = load_card();
    trace("RF_DetectCard -> %s", len ? g_card : "none");
    return len ? 0 : 1;
}

/* The card's 4-byte UID: made from the card number (FNV-1a), so one card always has the same UID. */
API int RF_GetCardID(HANDLE h, BYTE *uid)
{
    unsigned int x = 2166136261u;
    for (const char *p = g_card; *p; p++)
        x = (x ^ (unsigned char)*p) * 16777619u;
    if (uid)
        memcpy(uid, &x, 4);
    trace("RF_GetCardID -> %08x", x);
    return 0;
}

/* Load a sector key: any key opens any sector (there is no real card to protect). */
API int RF_LoadSecKey(HANDLE h, BYTE sector, BYTE type, const BYTE *key)
{
    trace("RF_LoadSecKey(sector %u, type %u)", sector, type);
    return 0;
}

/* Read 16 bytes: sector 0 blocks 1 and 2 hold the card number (20 bytes), other blocks what was written. */
API int RF_ReadBlock(HANDLE h, BYTE sector, BYTE block, BYTE *out)
{
    BYTE data[16] = {0};
    if (sector == 0 && block == 1)
        memcpy(data, g_card, 16);
    else if (sector == 0 && block == 2)
        memcpy(data, g_card + 16, 4);
    else if (sector < 16 && block < 4)
        memcpy(data, g_store[sector][block], 16);
    if (out)
        memcpy(out, data, 16);
    trace("RF_ReadBlock(sector %u, block %u)", sector, block);
    return 0;
}

/* Write 16 bytes: kept in memory for the game's later reads (the card number itself is not writable). */
API int RF_WriteBlock(HANDLE h, BYTE sector, BYTE block, const BYTE *in)
{
    if (sector < 16 && block < 4 && in)
        memcpy(g_store[sector][block], in, 16);
    trace("RF_WriteBlock(sector %u, block %u)", sector, block);
    return 0;
}
