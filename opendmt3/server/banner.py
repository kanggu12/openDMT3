"""What the server prints once it is up, however it was started (python -m opendmt3.server, the Windows server
package, the container's log, ./dmt3 up): a text logo, its version, and the addresses in a box (the players', this
PC's, the game's port), with a line for the first start.

ASCII alone, so every Windows console font draws it. Colour only where it is seen as colour: a terminal, unless
NO_COLOR is set (https://no-color.org); a file, a pipe and a container's log get the same text plain.
"""

import os
import sys

# The logo in ASCII letters (figlet's small font), indented by two like the rest.
LOGO = ["                    ___  __  __ _____ ____",
        " ___ _ __  ___ _ _ |   \\|  \\/  |_   _|__ /",
        "/ _ \\ '_ \\/ -_) ' \\| |) | |\\/| | | |  |_ \\",
        "\\___/ .__/\\___|_||_|___/|_|  |_| |_| |___/",
        "    |_|"]
# The colours of each role, as terminals number them: the logo cyan, the labels dim, the addresses bold green, a
# line to act on amber (yellow).
CYAN, DIM, GREEN, AMBER, RESET = "\033[36m", "\033[2m", "\033[1;32m", "\033[33m", "\033[0m"


def windows_colour(stream):
    """On Windows, turn on the console's own colour codes (ENABLE_VIRTUAL_TERMINAL_PROCESSING, Windows 10 and on);
    True when they are on. Elsewhere True."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        import msvcrt
        handle = msvcrt.get_osfhandle(stream.fileno())
        mode = ctypes.c_ulong()
        kernel = ctypes.windll.kernel32
        if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        # 0x0004: the console reads the colour codes instead of printing them.
        return bool(kernel.SetConsoleMode(handle, mode.value | 0x0004))
    except (AttributeError, OSError, ValueError):
        return False


def coloured(stream=None):
    """True when this stream shows colour: a terminal, NO_COLOR not set, and (on Windows) a console that reads the
    codes."""
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    try:
        if not stream.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    return windows_colour(stream)


def text(version, rows, notes=(), colour=False):
    """The banner: the logo with the version under it, then the rows ((label, value), ...) in a box, then each note.
    Plain ASCII with colour codes only when colour is True."""
    def paint(code, words):
        return code + words + RESET if colour else words

    lines = [paint(CYAN, "  " + line) for line in LOGO]
    lines.append("  " + paint(DIM, "server") + " " + version)
    if rows:
        width = max(len(label) for label, _ in rows)
        inner = max(width + 3 + len(value) for label, value in rows) + 2
        lines.append("  +" + "-" * inner + "+")
        for label, value in rows:
            gap = inner - 2 - width - 3 - len(value)
            lines.append("  | " + paint(DIM, label.ljust(width)) + "   " + paint(GREEN, value) + " " * gap + " |")
        lines.append("  +" + "-" * inner + "+")
    lines += ["  " + paint(AMBER, note) for note in notes]
    return "\n".join(lines)


def show(version, rows, notes=(), stream=None):
    """Print the banner on stream (standard output), coloured when it is seen as colour."""
    stream = stream or sys.stdout
    # Only ASCII is printed: a console's code page, a pipe's encoding, any of them takes it.
    stream.write(text(version, rows, notes, coloured(stream)) + "\n")
    stream.flush()


def rows(players, here, game_port):
    """The box's rows: the players' address (when one is known), this PC's, and the game's port."""
    return ([("Players", players)] if players else []) + [("This PC", here), ("Game", "TCP %d" % game_port)]
