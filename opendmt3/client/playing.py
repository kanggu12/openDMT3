"""A named mutex the launcher holds from the moment PLAY starts getting the game ready until the game it started
closes.

The installer looks for it and refuses to install then: Velopack's setup closes a running launcher before it
replaces it, and with the launcher would go the server on this PC that the game is playing on, mid-song. The
launcher's own update refuses in the same moment for the same reason (pages.build_about). Two launchers (the window
and openDMT3-cmd --play) never get the game ready or play at once: PLAY claims the mutex first, and a launcher that
finds it held by another says so instead of writing openDMT3's folder under the other's game.
"""

import sys

NAME = "Local\\openDMT3.playing"
_handle = None


def _kernel32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.restype = wintypes.HANDLE
    k.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    k.OpenMutexW.restype = wintypes.HANDLE
    k.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    return k


def _windows():
    return sys.platform == "win32"


def _last_error():
    import ctypes
    return ctypes.get_last_error()


# Windows' word for a named object that was there before this call made it.
ALREADY_EXISTS = 183


def claim():
    """Hold the mutex for this PLAY: True when this launcher holds it now (or already did), False when another launcher
    holds it (it is getting a game ready, or a game it started runs). Elsewhere than Windows always True."""
    global _handle
    if not _windows() or _handle:
        return True
    k = _kernel32()
    handle = k.CreateMutexW(None, False, NAME)
    if not handle:
        # The mutex cannot be made at all: nothing to tell by, so PLAY goes on as it did before there was one.
        return True
    if _last_error() == ALREADY_EXISTS:
        # Another launcher's: this handle only looked.
        k.CloseHandle(handle)
        return False
    _handle = handle
    return True


def hold():
    """Say a game is running (until release(), or until this process ends); claim() that cannot fail."""
    global _handle
    if not _windows() or _handle:
        return
    _handle = _kernel32().CreateMutexW(None, False, NAME)


def release():
    global _handle
    if _handle:
        _kernel32().CloseHandle(_handle)
        _handle = None


def game_running(session=None):
    """The one test of whether a game is running, for everything that would end it: this launcher's own session,
    or a game any launcher (the window, or openDMT3-cmd --play) says it started."""
    return (session is not None and session.running()) or running()


def running():
    """True while some launcher says a game it started is running."""
    if sys.platform != "win32":
        return False
    k = _kernel32()
    synchronize = 0x00100000
    handle = k.OpenMutexW(synchronize, False, NAME)
    if handle:
        k.CloseHandle(handle)
        return True
    return False
