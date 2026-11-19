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


# What is said of a screen's rates for motion clarity (native/cardreader/logic.h refresh_advice): nothing, set below
# its highest rate at its size, or Windows 11's dynamic refresh rate (programs are given less than the monitor runs at).
AS_IS, SET_LOWER, DYNAMIC = "as_is", "set_lower", "dynamic"


def refresh_advice(current, highest, signal):
    """The in-game layer's own rule (logic.c refresh_advice) for a screen's rate programs are given now (`current`),
    the highest of its modes at its size and the rate on the cable to its monitor (each None or 0 when not known)."""
    current, highest, signal = current or 0, highest or 0, signal or 0
    # Nothing known of what programs are given: nothing to say.
    if current <= 0:
        return AS_IS
    # The monitor carries more refreshes than programs are given (2 Hz over: 119.88 is given as 119): dynamic.
    if signal > current + 1:
        return DYNAMIC
    # A faster mode at this size that is not chosen.
    if highest > current + 1:
        return SET_LOWER
    return AS_IS


def _devmode_type():
    """DEVMODEW as Windows lays it out for a display (its printer half as the display's position and output)."""
    import ctypes
    from ctypes import wintypes

    class DEVMODEW(ctypes.Structure):
        _fields_ = [("dmDeviceName", wintypes.WCHAR * 32), ("dmSpecVersion", wintypes.WORD),
                    ("dmDriverVersion", wintypes.WORD), ("dmSize", wintypes.WORD), ("dmDriverExtra", wintypes.WORD),
                    ("dmFields", wintypes.DWORD), ("dmPositionX", wintypes.LONG), ("dmPositionY", wintypes.LONG),
                    ("dmDisplayOrientation", wintypes.DWORD), ("dmDisplayFixedOutput", wintypes.DWORD),
                    ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short), ("dmYResolution", ctypes.c_short),
                    ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short),
                    ("dmFormName", wintypes.WCHAR * 32), ("dmLogPixels", wintypes.WORD),
                    ("dmBitsPerPel", wintypes.DWORD), ("dmPelsWidth", wintypes.DWORD),
                    ("dmPelsHeight", wintypes.DWORD), ("dmDisplayFlags", wintypes.DWORD),
                    ("dmDisplayFrequency", wintypes.DWORD), ("dmICMMethod", wintypes.DWORD),
                    ("dmICMIntent", wintypes.DWORD), ("dmMediaType", wintypes.DWORD),
                    ("dmDitherType", wintypes.DWORD), ("dmReserved1", wintypes.DWORD),
                    ("dmReserved2", wintypes.DWORD), ("dmPanningWidth", wintypes.DWORD),
                    ("dmPanningHeight", wintypes.DWORD)]
    return DEVMODEW


def _signal_rates():
    """{GDI name of a screen: the rate the cable carries to its monitor, whole hertz rounded down} from Windows 7's
    QueryDisplayConfig (the active paths), {} where it cannot be read."""
    import ctypes
    from ctypes import wintypes

    class LUID(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.LONG)]

    class RATIONAL(ctypes.Structure):
        _fields_ = [("num", ctypes.c_uint32), ("den", ctypes.c_uint32)]

    class PATH(ctypes.Structure):
        # sourceInfo (adapter, id, mode index, status), targetInfo (adapter, id, mode index, output, rotation,
        # scaling, refresh rate, scan lines, available, status), flags: 72 bytes.
        _fields_ = [("s_adapter", LUID), ("s_id", ctypes.c_uint32), ("s_mode", ctypes.c_uint32),
                    ("s_status", ctypes.c_uint32), ("t_adapter", LUID), ("t_id", ctypes.c_uint32),
                    ("t_mode", ctypes.c_uint32), ("t_output", ctypes.c_uint32), ("t_rotation", ctypes.c_uint32),
                    ("t_scaling", ctypes.c_uint32), ("t_refresh", RATIONAL), ("t_scan", ctypes.c_uint32),
                    ("t_available", ctypes.c_int32), ("t_status", ctypes.c_uint32), ("flags", ctypes.c_uint32)]

    class MODE(ctypes.Structure):
        # infoType, id, adapter, then a target mode's video signal (pixel rate, horizontal and vertical rates, sizes,
        # standard, scan lines): 64 bytes, the source and desktop modes sharing the same room.
        _fields_ = [("type", ctypes.c_uint32), ("id", ctypes.c_uint32), ("adapter", LUID),
                    ("pixel_rate", ctypes.c_uint64), ("h_sync", RATIONAL), ("v_sync", RATIONAL),
                    ("active", ctypes.c_uint32 * 2), ("total", ctypes.c_uint32 * 2), ("standard", ctypes.c_uint32),
                    ("scan", ctypes.c_uint32)]

    class SOURCE_NAME(ctypes.Structure):
        # The header (type, size, adapter, id), then the source's GDI name.
        _fields_ = [("type", ctypes.c_uint32), ("size", ctypes.c_uint32), ("adapter", LUID), ("id", ctypes.c_uint32),
                    ("name", wintypes.WCHAR * 32)]

    QDC_ONLY_ACTIVE_PATHS, GET_SOURCE_NAME, MODE_TARGET = 2, 1, 2
    user32 = ctypes.windll.user32
    np, nm = ctypes.c_uint32(), ctypes.c_uint32()
    if user32.GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(np), ctypes.byref(nm)) != 0:
        return {}
    paths, modes = (PATH * np.value)(), (MODE * nm.value)()
    if user32.QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(np), paths, ctypes.byref(nm), modes, None) != 0:
        return {}
    rates = {}
    for path in paths[:np.value]:
        name = SOURCE_NAME(type=GET_SOURCE_NAME, size=ctypes.sizeof(SOURCE_NAME), adapter=path.s_adapter,
                           id=path.s_id)
        if user32.DisplayConfigGetDeviceInfo(ctypes.byref(name)) != 0:
            continue
        # The target's mode: the signal's own vertical rate; else the path's rate.
        rate = path.t_refresh
        if path.t_mode < nm.value and modes[path.t_mode].type == MODE_TARGET and modes[path.t_mode].v_sync.den:
            rate = modes[path.t_mode].v_sync
        if rate.den:
            rates[name.name.lower()] = rate.num // rate.den
    return rates


def screen_rates():
    """Each screen on the desktop as Windows reads it: a dict of its GDI name, whether it is the main one, its size,
    the rate programs are given now, the highest of its modes at that size and the rate on the cable (None where not
    known), and what is said of it (refresh_advice). [] elsewhere than Windows or where nothing can be read."""
    import sys
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        class DISPLAY_DEVICEW(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32),
                        ("DeviceString", wintypes.WCHAR * 128), ("StateFlags", wintypes.DWORD),
                        ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128)]

        DEVMODEW = _devmode_type()
        user32 = ctypes.windll.user32
        ENUM_CURRENT_SETTINGS, ATTACHED, PRIMARY = 0xFFFFFFFF, 0x1, 0x4
        try:
            signals = _signal_rates()
        except (AttributeError, OSError, ValueError):
            # An older Windows or Wine without the display configuration: no rate on the cable known.
            signals = {}
        screens, i = [], 0
        while True:
            dd = DISPLAY_DEVICEW(cb=ctypes.sizeof(DISPLAY_DEVICEW))
            if not user32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
                break
            i += 1
            # Only screens on the desktop.
            if not dd.StateFlags & ATTACHED:
                continue
            now = DEVMODEW(dmSize=ctypes.sizeof(DEVMODEW))
            if not user32.EnumDisplaySettingsW(dd.DeviceName, ENUM_CURRENT_SETTINGS, ctypes.byref(now)):
                continue
            # The highest of its modes at its present size.
            highest, k = 0, 0
            while True:
                m = DEVMODEW(dmSize=ctypes.sizeof(DEVMODEW))
                if not user32.EnumDisplaySettingsW(dd.DeviceName, k, ctypes.byref(m)):
                    break
                k += 1
                if (m.dmPelsWidth, m.dmPelsHeight) == (now.dmPelsWidth, now.dmPelsHeight):
                    highest = max(highest, int(m.dmDisplayFrequency))
            # 0 and 1 stand for the display's own default rate, which says nothing of what it is.
            current = int(now.dmDisplayFrequency) if now.dmDisplayFrequency > 1 else None
            signal = signals.get(dd.DeviceName.lower())
            screens.append({"name": dd.DeviceName, "main": bool(dd.StateFlags & PRIMARY),
                            "size": (int(now.dmPelsWidth), int(now.dmPelsHeight)), "current": current,
                            "highest": highest or None, "signal": signal,
                            "advice": refresh_advice(current, highest, signal)})
        return screens
    except (AttributeError, OSError, ValueError):
        return []


def main_screen():
    """The main screen's entry of screen_rates (the game shows on the main screen), or None."""
    for screen in screen_rates():
        if screen["main"]:
            return screen
    return None


def refresh_rate():
    """The main screen's rate motion clarity is offered from: the highest of its modes at its size (never what
    Windows gives programs now, which Windows 11's dynamic refresh rate keeps at 60), else its rate now; None where it
    cannot be read (elsewhere than Windows)."""
    return rate_of(main_screen())


def rate_of(screen):
    """refresh_rate for a screen's entry the caller has already (main_screen; None for none): a caller that needs the
    entry too asks Windows for every display mode once, not twice."""
    if not screen:
        return None
    return screen["highest"] or screen["current"]


def strobe_offered(hz):
    """Whether motion clarity has sub-frames to show at this refresh rate: a whole multiple of 60 from 120 up, within
    1 Hz (Windows gives 119.88 and 239.76 Hz as 119 and 239), the in-game layer's own rule (native/cardreader/logic.c
    strobe_refreshes)."""
    if not hz:
        return False
    # The nearest whole multiple of 60, and the rate's distance from it.
    n = (hz + 30) // 60
    return n >= 2 and abs(hz - n * 60) <= 1
