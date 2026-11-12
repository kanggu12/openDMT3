"""Ask a window to close the way the taskbar's close and a window manager's do: the ICCCM WM_DELETE_WINDOW message,
which Wine hands to the window as its close request (WM_SYSCOMMAND SC_CLOSE, then WM_CLOSE).

    python3 close.py WINDOW_NAME

Exit 0 when the window was found and the message sent.
"""
import sys

from Xlib import X, display, protocol


def find(window, name):
    """The first window under this one (itself included) with this name, or None."""
    try:
        if window.get_wm_name() == name:
            return window
    except Exception:
        # A window that went meanwhile has no name to read.
        pass
    try:
        children = window.query_tree().children
    except Exception:
        return None
    for child in children:
        found = find(child, name)
        if found is not None:
            return found
    return None


def main(name):
    d = display.Display()
    window = find(d.screen().root, name)
    if window is None:
        print("no window named %r" % name)
        return 1
    # WM_PROTOCOLS with WM_DELETE_WINDOW in its first word: "close, please", as the desktop sends it.
    message = protocol.event.ClientMessage(window=window, client_type=d.intern_atom("WM_PROTOCOLS"),
                                           data=(32, [d.intern_atom("WM_DELETE_WINDOW"), X.CurrentTime, 0, 0, 0]))
    window.send_event(message)
    d.flush()
    print("close asked of %r" % name)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
