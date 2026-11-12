"""Where the launcher's window goes: the room windows have on the screen (on Windows its work area, the screen
less the taskbar), the height Windows puts around a window's own area, and the window's box in that room. Plain
numbers and ctypes, no Tk: app.py places its window with them, and they are tested where Tk is missing."""

# Windows' calls for the room a window has: SystemParametersInfo's SPI_GETWORKAREA, and GetSystemMetrics' caption
# height, sizing frame and padded border.
SPI_GETWORKAREA = 0x0030
SM_CYCAPTION, SM_CYSIZEFRAME, SM_CXPADDEDBORDER = 4, 33, 92


def work_area(root):
    """(left, top, width, height) of where a window may go: on Windows its work area (the main screen less the
    taskbar, wherever the taskbar sits), elsewhere the whole screen."""
    import sys
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            rect = wintypes.RECT()
            # In the pixels this process sees, as winfo_screenwidth's are.
            if ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
                if rect.right > rect.left and rect.bottom > rect.top:
                    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
        except (AttributeError, OSError, ValueError):
            # An older Windows or Wine without the call: the whole screen, as before.
            pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def title_bar_height():
    """What Windows puts above and below a window's own area (its title bar and its sizing frame), in pixels; 0 where
    the window manager's decorations are not Windows'."""
    import sys
    if sys.platform == "win32":
        try:
            import ctypes
            metric = ctypes.windll.user32.GetSystemMetrics
            # The caption, and the sizing frame with its padding at the top and at the bottom.
            return max(0, int(metric(SM_CYCAPTION) + 2 * (metric(SM_CYSIZEFRAME) + metric(SM_CXPADDEDBORDER))))
        except (AttributeError, OSError, ValueError):
            pass
    return 0


def window_box(room, caption, want_w, want_h):
    """The launcher window's (width, height, x, y) in room (left, top, width, height): its wanted size, never more
    than 92 % of the room (the title bar and frame, caption, counted in the height), centred across and a third of
    the way down, so the whole window, its title bar included, stays inside the room."""
    left, top, room_w, room_h = room
    w = max(1, min(want_w, int(room_w * 0.92)))
    h = max(1, min(want_h, int(room_h * 0.92) - caption))
    # x and y place the window's outer frame (Tk's geometry on Windows), so the caption is part of what is centred.
    x = left + (room_w - w) // 2
    y = top + max(0, (room_h - (h + caption)) // 3)
    return w, h, x, y


# GetDeviceCaps' vertical refresh rate (VREFRESH): the screen's refresh in hertz.
VREFRESH = 116


def refresh_rate():
    """The main screen's refresh rate in hertz as Windows sets it now (the game shows on the main screen), or None
    where it cannot be read (elsewhere than Windows, or a driver that gives 0 or 1: the hardware's default)."""
    import sys
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        # The whole screen's device context, read and let go at once.
        dc = user32.GetDC(0)
        if not dc:
            return None
        try:
            hz = int(gdi32.GetDeviceCaps(dc, VREFRESH))
        finally:
            user32.ReleaseDC(0, dc)
    except (AttributeError, OSError, ValueError):
        return None
    # 0 and 1 stand for the display's own default rate, which says nothing of what it is.
    return hz if hz > 1 else None


def strobe_offered(hz):
    """Whether motion clarity has sub-frames to show at this refresh rate: a whole multiple of 60 from 120 up, within
    1 Hz (Windows gives 119.88 and 239.76 Hz as 119 and 239), the in-game layer's own rule (native/cardreader/logic.c
    strobe_refreshes)."""
    if not hz:
        return False
    # The nearest whole multiple of 60, and the rate's distance from it.
    n = (hz + 30) // 60
    return n >= 2 and abs(hz - n * 60) <= 1
