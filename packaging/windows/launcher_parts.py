"""What the Windows build leaves out, for both of its PyInstaller recipes (openDMT3.spec for the launcher's folder,
setup.spec for the installer's one file), each loading this with runpy: parts the launcher and its installer never use,
which only made every installer and every update larger.
"""

# Python modules never imported, left out with what they bring:
# - Pillow's AVIF and WebP codecs and its colour management (7.8, 0.4 and 0.3 MB in the folder; the AVIF codec was 4.3 MB
#   of the update and 4.3 MB more of the installer): the launcher's pictures, the game's jackets and the DJ cards are
#   PNG, and Pillow says those formats unsupported without them (its plugins import them in try/except);
# - Python's modules for tests and documentation.
EXCLUDES = ["unittest", "pydoc", "test", "lib2to3", "idlelib", "PIL._avif", "PIL._webp", "PIL._imagingcms"]

# Tcl's character sets kept: the Windows code pages, any of which can be the system's (Tcl takes the system's own when
# it starts), with ASCII and Latin-1. The others are other systems' text, which the window never converts.
TCL_ENCODINGS_KEPT = {"ascii.enc", "iso8859-1.enc", "cp874.enc", "cp932.enc", "cp936.enc", "cp949.enc", "cp950.enc"} | {
    "cp125%d.enc" % n for n in range(9)}


def kept_binary(dest):
    """False for Windows' own C runtime (ucrtbase.dll and its api-ms-win-* forwarders): part of every Windows 10 and 11,
    so the program needs no copy, and a copy would be a part of Microsoft's in it that the notices do not cover. A Python
    built with them beside it (as a hosted one is) has PyInstaller take them in; the build machine's has none. dest is
    the file's place in the program's folder, as PyInstaller gives it."""
    # Only the file's name counts, in any letter case.
    name = dest.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return not (name == "ucrtbase.dll" or (name.startswith("api-ms-win-") and name.endswith(".dll")))


def kept_data(dest):
    """False for a data file of Tcl's that the window never reads: its time zones (1.3 MB: the window never asks Tcl's
    clock for a named zone), its message catalogs (clock's month names in other languages) and the character sets not
    kept above (TCL_ENCODINGS_KEPT). dest is the file's place in the program's folder, as PyInstaller gives it."""
    # PyInstaller's places use the build system's separator (backslashes under Windows).
    parts = dest.replace("\\", "/").split("/")
    if parts[0] != "_tcl_data" or len(parts) < 3:
        # Not inside one of the folders of Tcl's data.
        return True
    if parts[1] in ("tzdata", "msgs"):
        return False
    return parts[1] != "encoding" or parts[2] in TCL_ENCODINGS_KEPT
