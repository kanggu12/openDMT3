"""A guard for everything that would put a window on someone's screen.

Tests must never open a window on the developer's own desktop. Under WSL a Tk window lands on the Windows
desktop through WSLg, and starting a Windows program from WSL opens it there too. So each function that opens a
window (the launcher's own, the game, a browser, Explorer) calls refuse_windows_in_tests() first.

A test run sets OPENDMT3_TESTING=1 (tests/__init__.py). Inside the test container, where the screen is a virtual
X server, OPENDMT3_VIRTUAL_DISPLAY=1 lets the UI tests open windows on that screen and nowhere else.
"""

import os


class WindowRefused(RuntimeError):
    """A test tried to open a window outside the virtual screen."""


def testing():
    """True while the test suite runs."""
    return os.environ.get("OPENDMT3_TESTING") == "1"


def on_virtual_display():
    """True only inside the test container, whose X server has no real screen behind it."""
    return os.environ.get("OPENDMT3_VIRTUAL_DISPLAY") == "1"


def refuse_windows_in_tests(what):
    """Stop a test from opening `what` unless the run is on the virtual screen."""
    if testing() and not on_virtual_display():
        raise WindowRefused("a test tried to open %s outside the virtual screen" % what)
