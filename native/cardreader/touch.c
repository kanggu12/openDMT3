/*
 * The touch screen inside the game's process (ingame.h; its rules in contacts.c): the fingers and pens Windows reports
 * on the game's window, the mouse as one point more, and the three calls openDMT3's own multiDLL.dll makes in place of
 * the cabinet's touch frame program.
 *
 * The layer's window procedure hands this file the window's pointer messages (WM_POINTERDOWN, UPDATE, UP and
 * CAPTURECHANGED) before the game's own window procedure gets them as before, so Windows still makes the first finger
 * the mouse, which the game's menus read; each finger's place becomes the game's pixel under it in the picture as
 * placed. The game's read of its keys each frame (hooks.c) says how it sees the mouse's left button, the overlay's hold
 * applied. At each of the game's reads (its WaitNexioMulti, a frame while a song plays) the contacts are handed by
 * contacts.c's rules.
 *
 * Measuring and testing only, never set by the launcher: OPENDMT3_MULTI_TOUCH=off keeps the game's own one-point
 * reading of the mouse (the touch screen's open fails, as without this library); OPENDMT3_TOUCH_INJECT puts made-up
 * contacts down at given reads (a touch screen cannot be made under Wine); OPENDMT3_TOUCH_WATCH=on writes what the game
 * itself holds after each read into the in-game log, read from its memory in the PC build.
 */
#include "ingame.h"
#include "contacts.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* The pointer messages and their flags, in case the headers are older than Windows 8's. */
#ifndef WM_POINTERUPDATE
#define WM_POINTERUPDATE 0x0245
#define WM_POINTERDOWN 0x0246
#define WM_POINTERUP 0x0247
#define WM_POINTERCAPTURECHANGED 0x024C
#endif
/* The flags in a pointer message's high word: on the screen (not hovering over it), Windows' first contact, cancelled. */
#define FLAG_INCONTACT 0x0004u
#define FLAG_PRIMARY 0x2000u
#define FLAG_CANCELED 0x8000u
/* Windows' kinds of pointer: a finger and a pen are contacts; the mouse is read as the mouse. */
#define KIND_TOUCH 2u
#define KIND_PEN 3u
/* The mark Windows puts on the mouse messages it makes from a finger or a pen (GetMessageExtraInfo). */
#define FROM_TOUCH_MASK 0xFFFFFF00u
#define FROM_TOUCH_MARK 0xFF515700u
/* Made-up contacts' ids (OPENDMT3_TOUCH_INJECT): far from Windows' own small ones. */
#define INJECTED_ID 0x7F000000u
#define INJECT_STEPS 64
#define INJECT_POINTS 8

/* The contacts, their lock (the game's reads and its window's messages may come on different threads), and whether
 * the game opened the touch screen (until then nothing is kept: no read would ever hand it). */
static SRWLOCK g_lock = SRWLOCK_INIT;
static Contacts g_contacts;
static int g_open;
/* The game's reads since it opened the touch screen. */
static long g_reads;
/* Windows' first contact, the one it makes the mouse: its id while it is down. */
static uint32_t g_primary;
static int g_primary_down;
/* The mouse's left button is down because Windows made it from a finger or a pen (that finger is a contact already). */
static int g_button_from_touch;
/* The game's own view of the left button at its last read of the keys, the overlay's hold applied (hooks.c). */
static int g_game_button;
/* Whether a pointer's place comes in the window's own pixels (Windows gave them so) rather than the screen's physical
 * ones: learnt from a press that lies in the window only one way. */
static int g_logical_given;
/* The most fingers at once said in the log so far, and whether the first finger's place was said. */
static int g_said_most, g_said_first, g_said_cursor;

/* Milliseconds by the performance counter (the mouse's hold past its release). */
static double now_ms(void)
{
    static LARGE_INTEGER f;
    LARGE_INTEGER t;
    if (!f.QuadPart)
        QueryPerformanceFrequency(&f);
    QueryPerformanceCounter(&t);
    return (double)t.QuadPart * 1000.0 / (double)f.QuadPart;
}

/* ------------------------------------------------------------------------------------------ a finger's place */

/* A point of the screen's physical pixels in the window's own, at the window's scaling (a game the display fix left
 * unaware of the display's scaling is drawn larger by Windows); as it is where the functions are missing. */
static void to_logical(HWND w, POINT *p)
{
    typedef BOOL(WINAPI * ConvertFn)(HWND, LPPOINT);
    static ConvertFn convert;
    static int looked;
    if (!looked) {
        looked = 1;
        HMODULE user = GetModuleHandleA("user32.dll");
        /* Windows 8.1's, for every monitor's own scaling; Windows Vista's otherwise. */
        convert = user ? (ConvertFn)(void *)GetProcAddress(user, "PhysicalToLogicalPointForPerMonitorDPI") : NULL;
        if (!convert && user)
            convert = (ConvertFn)(void *)GetProcAddress(user, "PhysicalToLogicalPoint");
    }
    if (convert)
        convert(w, p);
}

/* Whether a client point lies in the window's client area. */
static int in_client(HWND w, POINT c)
{
    RECT r;
    return GetClientRect(w, &r) && c.x >= 0 && c.y >= 0 && c.x < r.right && c.y < r.bottom;
}

/* A pointer message's place in the window's client pixels. The message gives it in the screen's physical pixels; at a
 * press, which Windows hands the window under the finger, a place that lies in the window only one way says which it
 * was, and that way is kept. */
static POINT client_point(HWND w, LPARAM l, int press)
{
    /* The place's two halves, signed (a screen left of or above the main one has negative ones). */
    POINT given = {(LONG)(short)LOWORD(l), (LONG)(short)HIWORD(l)};
    POINT physical = given, logical = given;
    to_logical(w, &physical);
    ScreenToClient(w, &physical);
    ScreenToClient(w, &logical);
    if (press) {
        int a = in_client(w, physical), b = in_client(w, logical);
        /* Only one way in the window: that is the way Windows gives places here (said when it changes). */
        if (a != b && g_logical_given != b) {
            g_logical_given = b;
            ingame_log("touch: a finger's place comes in %s pixels", b ? "the window's own" : "the screen's physical");
        }
    }
    return g_logical_given ? logical : physical;
}

/* The game pixel under a client point, in the picture as the chain placed it (the whole client with no chain). */
static void game_point(HWND w, POINT c, int *gx, int *gy)
{
    PicRect r;
    post_picture(&r.x, &r.y, &r.w, &r.h);
    if (r.w <= 0 || r.h <= 0) {
        RECT rc;
        GetClientRect(w, &rc);
        r.x = r.y = 0;
        r.w = rc.right;
        r.h = rc.bottom;
    }
    game_pixel_under(c.x, c.y, r, gx, gy);
}

/* Whether a pointer is a finger or a pen (a mouse in pointer mode is read as the mouse); taken as one when Windows
 * cannot say (only fingers and pens send these messages unless a program asks for the mouse's). */
static int finger_or_pen(UINT32 id)
{
    typedef BOOL(WINAPI * KindFn)(UINT32, DWORD *);
    static KindFn kind;
    static int looked;
    if (!looked) {
        looked = 1;
        HMODULE user = GetModuleHandleA("user32.dll");
        /* Windows 8's; looked up so this library loads where it is missing. */
        kind = user ? (KindFn)(void *)GetProcAddress(user, "GetPointerType") : NULL;
    }
    DWORD k = 0;
    if (!kind || !kind(id, &k))
        return 1;
    return k == KIND_TOUCH || k == KIND_PEN;
}

/* -------------------------------------------------------------------------------------------- the messages */

/* Fingers down on the game now, for the log (the overlay's left out). */
static int fingers_down(void)
{
    int n = 0;
    for (int i = 0; i < g_contacts.n; i++)
        n += g_contacts.c[i].down && !g_contacts.c[i].overlay && g_contacts.c[i].id != CONTACT_MOUSE;
    return n;
}

void touch_pointer(HWND w, UINT msg, WPARAM wp, LPARAM lp)
{
    /* Nothing kept before the game opens the touch screen: no read would ever hand it. */
    if (!g_open)
        return;
    uint32_t id = LOWORD(wp);
    unsigned flags = HIWORD(wp);
    int contact = (flags & FLAG_INCONTACT) && !(flags & FLAG_CANCELED);
    if (!finger_or_pen(id))
        return;
    if (msg == WM_POINTERDOWN || (msg == WM_POINTERUPDATE && contact)) {
        POINT c = client_point(w, lp, msg == WM_POINTERDOWN);
        int gx, gy;
        game_point(w, c, &gx, &gy);
        AcquireSRWLockExclusive(&g_lock);
        /* A contact down already moves (an update, or a press Windows said again); its overlay's part stays as it
         * began. */
        int known = contacts_is_down(&g_contacts, id);
        if (known)
            contacts_move(&g_contacts, id, gx, gy);
        ReleaseSRWLockExclusive(&g_lock);
        if (known) {
            /* Once: the first finger's place against Windows' pointer, which Windows moved to it (the place read at
             * this display's scaling, for the log of a real touch screen). */
            if (!g_said_cursor && g_primary_down && id == g_primary) {
                POINT p;
                if (GetCursorPos(&p) && ScreenToClient(w, &p)) {
                    g_said_cursor = 1;
                    ingame_log("touch: the first finger at client %ld,%ld, Windows' pointer at %ld,%ld", c.x, c.y,
                               p.x, p.y);
                }
            }
            return;
        }
        /* A press: the overlay's when it lands on the bar or a panel, or while the menu or the question is up (asked
         * of the layer outside the lock: it reads the layer's own state only). */
        int overlay = layer_takes_press(c.x, c.y);
        AcquireSRWLockExclusive(&g_lock);
        int kept = contacts_down(&g_contacts, id, gx, gy, overlay);
        int now = fingers_down();
        ReleaseSRWLockExclusive(&g_lock);
        if (flags & FLAG_PRIMARY) {
            /* Windows' first contact: the mouse it makes from it plays the overlay's rules (layer.c). */
            g_primary = id;
            g_primary_down = 1;
        } else if (kept && !overlay) {
            /* Another finger on the game is play, as a click is: the bar goes, and no rest brings it for a while. */
            layer_finger(1, 1);
        }
        if (!g_said_first) {
            g_said_first = 1;
            ingame_log("touch: the first contact at client %ld,%ld, the game's pixel %d,%d%s", c.x, c.y, gx, gy,
                       overlay ? " (the overlay's)" : "");
        }
        if (now > g_said_most) {
            g_said_most = now;
            ingame_log("touch: %d finger%s on the game at once", now, now > 1 ? "s" : "");
        }
        return;
    }
    if (msg == WM_POINTERUP || msg == WM_POINTERCAPTURECHANGED || msg == WM_POINTERUPDATE) {
        /* Up, cancelled, taken away to another window, or a pen lifted to hover: the contact ends. */
        double now = now_ms();
        AcquireSRWLockExclusive(&g_lock);
        int was = contacts_is_down(&g_contacts, id);
        contacts_up(&g_contacts, id, now);
        int still = fingers_down();
        ReleaseSRWLockExclusive(&g_lock);
        if (g_primary_down && id == g_primary)
            g_primary_down = 0;
        else if (was)
            /* Another finger let go: the game is still played while any is down. */
            layer_finger(0, still > 0);
    }
}

void touch_button(int down)
{
    /* At the press: whether Windows made it from a finger or a pen (then that finger is a contact already, and the
     * mouse's button is no point of its own). Kept until the next press. */
    if (down)
        g_button_from_touch = ((DWORD)GetMessageExtraInfo() & FROM_TOUCH_MASK) == FROM_TOUCH_MARK;
}

void touch_keys(const BYTE *keys)
{
    /* The left button as the game reads it this frame, after the overlay's hold (hold_keys). */
    g_game_button = (keys[VK_LBUTTON] & 0x80) != 0;
}

void touch_withhold(int every)
{
    AcquireSRWLockExclusive(&g_lock);
    if (every)
        contacts_withhold(&g_contacts, CONTACT_ALL);
    else if (g_primary_down)
        contacts_withhold(&g_contacts, g_primary);
    ReleaseSRWLockExclusive(&g_lock);
}

void touch_clear(void)
{
    AcquireSRWLockExclusive(&g_lock);
    contacts_clear(&g_contacts);
    ReleaseSRWLockExclusive(&g_lock);
    g_primary_down = 0;
}

/* ------------------------------------------------------------------------------------------ testing, measuring */

/* OPENDMT3_TOUCH_INJECT: "READ:X,Y+X,Y;READ:_+X,Y;READ:-": from the game's read numbered READ on, made-up contacts at
 * those game pixels (the k-th of a step the same contact as the k-th of the step before, so it holds on; "_" no contact
 * there, so the one before comes up), "-" none. */
typedef struct {
    long read;
    int n;
    int x[INJECT_POINTS], y[INJECT_POINTS];
    uint8_t gap[INJECT_POINTS];
} InjectStep;
static InjectStep g_inject[INJECT_STEPS];
static int g_injects, g_injected_down;

static void inject_parse(void)
{
    char text[1024];
    DWORD got = GetEnvironmentVariableA("OPENDMT3_TOUCH_INJECT", text, sizeof text);
    if (!got || got >= sizeof text)
        return;
    char *at = text;
    while (*at && g_injects < INJECT_STEPS) {
        char *end;
        long read = strtol(at, &end, 10);
        /* Each step is its read's number, a colon, then its points or "-". */
        if (end == at || *end != ':')
            break;
        InjectStep *s = &g_inject[g_injects++];
        s->read = read;
        s->n = 0;
        at = end + 1;
        if (*at == '-') {
            at++;
        } else {
            while (s->n < INJECT_POINTS) {
                if (*at == '_') {
                    /* No contact at this place of the step: the one before there comes up. */
                    s->gap[s->n++] = 1;
                    at++;
                } else {
                    long x = strtol(at, &end, 10);
                    if (end == at || *end != ',')
                        break;
                    at = end + 1;
                    long y = strtol(at, &end, 10);
                    if (end == at)
                        break;
                    s->x[s->n] = (int)x;
                    s->y[s->n] = (int)y;
                    s->gap[s->n] = 0;
                    s->n++;
                    at = end;
                }
                if (*at != '+')
                    break;
                at++;
            }
        }
        /* The next step after a semicolon; anything else ends the list. */
        if (*at != ';')
            break;
        at++;
    }
    ingame_log("touch: %d made-up steps of contacts (measuring only)", g_injects);
}

/* At the game's read numbered `read`, at `now`: the step that starts there, if any, put down (the lock held). */
static void inject_step(long read, double now)
{
    for (int k = 0; k < g_injects; k++) {
        const InjectStep *s = &g_inject[k];
        if (s->read != read)
            continue;
        /* The contacts of the step before that this one has no k-th point for come up (and those at its gaps); the
         * rest hold on and move, and a new k-th one is a new contact. */
        for (int i = 0; i < g_injected_down || i < s->n; i++) {
            if (i >= s->n || s->gap[i])
                contacts_up(&g_contacts, INJECTED_ID + (uint32_t)i, now);
            else
                contacts_down(&g_contacts, INJECTED_ID + (uint32_t)i, s->x[i], s->y[i], 0);
        }
        g_injected_down = s->n;
    }
}

/* OPENDMT3_TOUCH_WATCH=on: the game's own touch state after each read, from its memory, said when it changes. Only in
 * the PC build, known by its reader's first instruction that names the state (mov ecx, 0x199FAE10 at 0x70EFA6). Read at
 * the next frame's start: the game's reader clears the state before it asks for a read, and fills it after. */
#define WATCH_CODE 0x70EFA6u
#define WATCH_STATE 0x199FAE10u
static int g_watch = -1;
static char g_watched[256];
static int g_watch_lines;
static long g_watched_read;

/* Whether the bytes at an address of the game's are committed and readable. */
static int readable(DWORD at, DWORD size)
{
    MEMORY_BASIC_INFORMATION m;
    if (!VirtualQuery((const void *)(uintptr_t)at, &m, sizeof m) || m.State != MEM_COMMIT ||
        (m.Protect & (PAGE_NOACCESS | PAGE_GUARD)))
        return 0;
    return at + size <= (DWORD)(uintptr_t)m.BaseAddress + (DWORD)m.RegionSize;
}

static void watch_game(void)
{
    if (g_watch < 0) {
        char v[8];
        g_watch = GetEnvironmentVariableA("OPENDMT3_TOUCH_WATCH", v, sizeof v) > 0 && !_stricmp(v, "on");
        static const BYTE code[] = {0xB9, 0x10, 0xAE, 0x9F, 0x19};
        if (g_watch && (!readable(WATCH_CODE, sizeof code) || memcmp((const void *)(uintptr_t)WATCH_CODE, code,
                                                                     sizeof code) || !readable(WATCH_STATE, 0x328))) {
            ingame_log("touch: watch off: not the PC build's reader");
            g_watch = 0;
        }
    }
    /* A few hundred lines at most: enough for a test's steps. */
    if (!g_watch || g_watch_lines >= 400)
        return;
    const BYTE *s = (const BYTE *)(uintptr_t)WATCH_STATE;
    int count = *(const int *)(s + 0x320);
    char line[256];
    int n = snprintf(line, sizeof line, "%d point%s%s%s%s%s:", count, count == 1 ? "" : "s", s[0x324] ? ", touching" : "",
                     s[0x325] ? ", pressed" : "", s[0x326] ? ", several" : "", s[0x327] ? ", a new finger" : "");
    for (int i = 0; i < count && i < 4 && n > 0 && n < (int)sizeof line - 24; i++)
        n += snprintf(line + n, sizeof line - (size_t)n, " %d,%d", *(const int *)(s + 8 * i), *(const int *)(s + 8 * i + 4));
    /* Only a change (a held finger's reads are all the same). */
    if (!strcmp(line, g_watched))
        return;
    strcpy(g_watched, line);
    g_watch_lines++;
    ingame_log("touch watch: after read %ld the game holds %s", g_reads, line);
}

void touch_frame(void)
{
    /* Once for each read: a frame with none (the game's menus, its window not the active one) says nothing. */
    if (!g_open || g_reads == g_watched_read)
        return;
    g_watched_read = g_reads;
    watch_game();
}

/* ------------------------------------------------------------------------------------------ the three calls */

/* openDMT3's multiDLL.dll's OpenNexioMulti: the touch screen opens (1), unless the measuring switch keeps the game's
 * own one-point reading of the mouse (0, as the original library answers on a PC). */
__declspec(dllexport) int __cdecl openDMT3_touch_open(void)
{
    char v[8];
    if (GetEnvironmentVariableA("OPENDMT3_MULTI_TOUCH", v, sizeof v) && !_stricmp(v, "off")) {
        ingame_log("touch: kept to the game's own one-point mouse (OPENDMT3_MULTI_TOUCH=off)");
        return 0;
    }
    AcquireSRWLockExclusive(&g_lock);
    contacts_start(&g_contacts);
    g_reads = 0;
    g_injected_down = 0;
    g_open = 1;
    ReleaseSRWLockExclusive(&g_lock);
    g_injects = 0;
    inject_parse();
    ingame_log("touch: the game opened the touch screen: every finger on its window, and the mouse as one point");
    return 1;
}

/* openDMT3's multiDLL.dll's WaitNexioMulti: the game's buffer filled as the frame's program filled it, at once (its
 * answer 0: new points). */
__declspec(dllexport) int __cdecl openDMT3_touch_read(void *buffer, unsigned size)
{
    LARGE_INTEGER t0, t1;
    QueryPerformanceCounter(&t0);
    /* The mouse: its button as the game read it this frame, not one Windows made from a finger, at the game pixel
     * under the pointer. */
    int mouse = g_game_button && !g_button_from_touch, mx = 0, my = 0;
    HWND w = layer_window();
    POINT p;
    if (w && GetCursorPos(&p) && ScreenToClient(w, &p))
        game_point(w, p, &mx, &my);
    else
        /* No window of the game's known yet, or no pointer to read: no place to press at. */
        mouse = 0;
    double now = now_ms();
    AcquireSRWLockExclusive(&g_lock);
    g_reads++;
    inject_step(g_reads, now);
    contacts_mouse(&g_contacts, mouse, mx, my, now);
    /* The overlay's menu or question up: nothing reaches the game. */
    contacts_read(&g_contacts, layer_holds_input(), (uint8_t *)buffer, buffer ? size : 0, now);
    ReleaseSRWLockExclusive(&g_lock);
    QueryPerformanceCounter(&t1);
    /* Its time counts with the frame's openDMT3 time (the game reads once a frame). */
    ingame_cost(t1.QuadPart - t0.QuadPart);
    return 0;
}

/* openDMT3's multiDLL.dll's CloseNexioMulti: nothing kept from now on. */
__declspec(dllexport) void __cdecl openDMT3_touch_close(void)
{
    AcquireSRWLockExclusive(&g_lock);
    g_open = 0;
    contacts_start(&g_contacts);
    ReleaseSRWLockExclusive(&g_lock);
    ingame_log("touch: the game closed the touch screen");
}
