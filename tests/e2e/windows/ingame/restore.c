/*
 * Bring a minimised window back the way the taskbar's button does: its restore command (WM_SYSCOMMAND SC_RESTORE),
 * posted to the window by its title. Under Wine with no window manager nothing else can (xdotool's map and activate
 * leave Wine's own state minimised).
 *
 *   wine restore.exe WINDOW_TITLE           its restore posted, and whether it was minimised then
 *   wine restore.exe --state WINDOW_TITLE   only whether it is minimised now (Windows' own state: with no window
 *                                           manager, Wine leaves a minimised window's X window on the screen)
 *   wine restore.exe --size W H WINDOW_TITLE  the window sized so its client is W x H, as a drag of its border would
 *                                           (with no window manager, xdotool's size changes only the X window), then
 *                                           "client X,Y WxH": its client's top left on the screen and its size
 *
 * Prints "minimised: 1" or "minimised: 0". Exit 0 when the window was found.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
    /* --state first: only say; --size: a new size for its client. */
    int state_only = argc > 2 && !strcmp(argv[1], "--state");
    int size = argc > 4 && !strcmp(argv[1], "--size");
    const char *title = size ? argv[4] : state_only ? argv[2] : argc > 1 ? argv[1] : NULL;
    if (!title) {
        fprintf(stderr, "usage: restore.exe [--state | --size W H] WINDOW_TITLE\n");
        return 2;
    }
    /* The top-level window with that title, of any class. */
    HWND w = FindWindowA(NULL, title);
    if (!w) {
        printf("no window titled %s\n", title);
        return 1;
    }
    if (size) {
        /* The whole window's size for that client, by its own style; its place kept. */
        RECT r = {0, 0, atoi(argv[2]), atoi(argv[3])};
        AdjustWindowRectEx(&r, (DWORD)GetWindowLongA(w, GWL_STYLE), FALSE, (DWORD)GetWindowLongA(w, GWL_EXSTYLE));
        SetWindowPos(w, NULL, 0, 0, r.right - r.left, r.bottom - r.top, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE);
        /* Its thread takes the change in its turn. */
        Sleep(500);
        RECT c;
        POINT o = {0, 0};
        GetClientRect(w, &c);
        ClientToScreen(w, &o);
        printf("client %ld,%ld %ldx%ld\n", o.x, o.y, c.right, c.bottom);
        return 0;
    }
    int iconic = IsIconic(w) ? 1 : 0;
    if (state_only) {
        printf("minimised: %d\n", iconic);
        return 0;
    }
    /* Posted, as the taskbar posts it: the window's own thread takes it in its turn. */
    PostMessageA(w, WM_SYSCOMMAND, SC_RESTORE, 0);
    printf("restore posted to %s (minimised: %d)\n", title, iconic);
    return 0;
}
