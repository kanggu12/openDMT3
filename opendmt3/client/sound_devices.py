"""Windows' sound output devices, as DirectSound names them: what the Sound page and --sound-devices list.

The game plays through DirectSound; openDMT3's in-game layer opens the chosen device by its DirectSound GUID
(native/cardreader/hooks.c), so the list comes from DirectSound itself. Off Windows there is none.
"""

import logging
import sys

log = logging.getLogger("opendmt3.launcher")


def _guid_text(raw):
    """A GUID structure's 16 bytes as Windows writes it: {XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}."""
    import uuid
    # The structure keeps its first three parts low byte first, as uuid's bytes_le does.
    return "{%s}" % str(uuid.UUID(bytes_le=bytes(raw))).upper()


def listed(enumerate_devices=None):
    """[(GUID, name)] of every output device, Windows' order; empty off Windows or when DirectSound says nothing.

    enumerate_devices replaces DirectSound for the tests: a function taking the same callback DirectSound calls,
    (GUID bytes or None, description, module)."""
    found = []

    def take(guid, description, module):
        # The first entry DirectSound gives has no GUID: Windows' default output, which is offered on its own.
        if guid is not None:
            found.append((_guid_text(guid), description or ""))
        return True

    if enumerate_devices is not None:
        enumerate_devices(take)
        return found
    if sys.platform != "win32":
        return found
    try:
        _directsound(take)
    except (AttributeError, OSError):
        # No DirectSound (a stripped Windows): only the default output, which needs no list.
        log.warning("Windows did not list its sound devices", exc_info=True)
    return found


def _directsound(take):
    """Ask DirectSound for its output devices; `take` hears each one."""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("raw", ctypes.c_ubyte * 16)]

    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.LPCWSTR,
                                       ctypes.c_void_p)

    def each(guid, description, module, context):
        # A null pointer is the default output; the others are copied out before DirectSound frees them.
        raw = bytes(guid.contents.raw) if guid else None
        return bool(take(raw, description, module))

    callback = callback_type(each)
    dsound = ctypes.WinDLL("dsound")
    dsound.DirectSoundEnumerateW.argtypes = (callback_type, ctypes.c_void_p)
    dsound.DirectSoundEnumerateW(callback, None)


def chosen_is_gone(chosen, devices, windows=sys.platform == "win32"):
    """True when the chosen device (a GUID, not "default") is not among Windows' devices now: the game then plays on
    Windows' default output, and the Sound page says so. Never off Windows, where nothing is listed at all."""
    if not chosen or chosen == "default" or not windows:
        return False
    return chosen.upper() not in {guid.upper() for guid, _ in devices}
