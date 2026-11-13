/*
 * openDMT3's stand-in for the cabinet's touch screen library, multiDLL.dll.
 *
 * The PC client imports three calls from it and nothing else (its import table): OpenNexioMulti once at its start,
 * WaitNexioMulti(1, buffer) once a frame while a song plays, CloseNexioMulti at its end; all three __cdecl (the client
 * clears their arguments itself), Open and Close with none. The original is a thin client of the touch frame's own
 * program: it opens that program's shared memory and its event, and its Wait copies the newest points into the game's
 * buffer when the event comes within the wait. A PC has no such program, so its Open fails and the game reads one
 * point from the mouse.
 *
 * This library answers from openDMT3's card reader library instead (CRT_R1.dll, which the game loads first and which
 * holds the in-game layer: touch.c): its Open opens openDMT3's touch screen, every finger Windows reports on the game's
 * window and the mouse as one point; its Wait fills the game's buffer at once. With no openDMT3 library beside it (a
 * card reader of another kind), its Open fails as the original's does on a PC, and the game plays the mouse as before.
 * The exports keep the original's names and numbers (multidll.def).
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

/* The game's buffer, as its INP::OpenNexio allocates it (contacts.h TOUCH_BUFFER): the size openDMT3's read is told,
 * since the game's Wait passes none. */
#define TOUCH_BUFFER 0x3A990u

/* openDMT3's three calls in its card reader library (touch.c). */
typedef int(__cdecl *OpenFn)(void);
typedef int(__cdecl *ReadFn)(void *buffer, unsigned size);
typedef void(__cdecl *CloseFn)(void);
static ReadFn g_read;
static CloseFn g_close;

BOOL WINAPI DllMain(HINSTANCE module, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    /* No calls for each thread the game starts: nothing here needs them. */
    if (reason == DLL_PROCESS_ATTACH)
        DisableThreadLibraryCalls(module);
    return TRUE;
}

/* The touch screen opens: 1 when openDMT3's library is beside it and opens it, 0 otherwise (the game then plays the
 * mouse, as it does when the original's touch frame program is not running). */
__declspec(dllexport) int __cdecl OpenNexioMulti(void)
{
    /* Loaded by the game already (its imports are bound before its code runs): looked up, never loaded here. */
    HMODULE ours = GetModuleHandleA("CRT_R1.dll");
    OpenFn open = ours ? (OpenFn)(void *)GetProcAddress(ours, "openDMT3_touch_open") : NULL;
    ReadFn read = ours ? (ReadFn)(void *)GetProcAddress(ours, "openDMT3_touch_read") : NULL;
    CloseFn close = ours ? (CloseFn)(void *)GetProcAddress(ours, "openDMT3_touch_close") : NULL;
    /* All three or none: a library without them is not openDMT3's (the cabinet's own card reader). */
    if (!open || !read || !close)
        return 0;
    g_read = read;
    g_close = close;
    if (!open()) {
        /* Kept to the game's own mouse (openDMT3's measuring switch): no read ever goes there. */
        g_read = NULL;
        g_close = NULL;
        return 0;
    }
    return 1;
}

/* The game's read, once a frame: its buffer filled with the points now, and 0 (new points), as the original answers
 * when its event came; 2 (a failure, the game leaves its points as they were) when the touch screen is not open. The
 * wait in milliseconds the game gives (1) is not needed: the points are here already. */
__declspec(dllexport) int __cdecl WaitNexioMulti(int wait_ms, void *buffer)
{
    (void)wait_ms;
    if (!g_read || !buffer)
        return 2;
    return g_read(buffer, TOUCH_BUFFER);
}

/* The game's end: openDMT3's touch screen closes. Nonzero, as the original's (its CloseHandle's) answer is. */
__declspec(dllexport) int __cdecl CloseNexioMulti(void)
{
    if (g_close)
        g_close();
    g_read = NULL;
    g_close = NULL;
    return 1;
}
