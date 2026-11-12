"""Look for the game where people usually keep it: game folders, and archives that may hold one.

The first-start guide shows what is found so a player picks from a list instead of typing a path. A game folder is
known by its content (a program, and a pack folder with the two files every game folder has, in any letter case), at
most DEPTH levels below each place, whatever the folders around it are called. An archive is taken when its name holds
one of the game's words (Downloads holds other archives too, and each would be opened to be judged); one the player
picks is judged whatever its name (client/intake.py). A split archive is found by its first part.

The search only lists names (no file is opened), stays out of the folders that never hold a game (Windows' own,
programs' data, the game's own pack folder), and stops as soon as it is asked to: it runs on a worker thread and hands
each path over as it turns up.
"""

import collections
import logging
import os
import re
import string
import sys

from opendmt3.core import game as g

log = logging.getLogger("opendmt3.launcher")

# How far below each place to look: a game folder often sits a level or two inside the folder it came in.
DEPTH = 4

# Windows' known-folder ids for the places people keep things (they follow OneDrive and folders moved elsewhere).
DESKTOP = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"
DOWNLOADS = "{374DE290-123F-4565-9164-39C4925E467B}"
DOCUMENTS = "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}"

# Folders that never hold a player's game: Windows' own, programs' data, version control and package caches, and the
# game's own pack folder (thousands of large files, nothing else to find in it). Compared in lower case.
SKIPPED = {g.PACK_DIR, "windows", "$recycle.bin", "system volume information", "programdata", "appdata",
           "node_modules", ".git", "$windows.~bt", "$windows.~ws", "msocache", "recovery", "perflogs",
           "windowsapps", "config.msi"}
# Words the game's archives are usually named with (as OpenDMTQ's and the server's look through a folder).
GAME_WORDS = ("technika", "djmax", "dmt3")
# Archives by their names: whole ones, and the first part of a split one (the later parts are read through it).
WHOLE = re.compile(r".+\.(?:zip|7z|rar|iso)", re.I)
FIRST_PART = re.compile(r".+(?:\.part0*1\.rar|\.(?:7z|zip|rar)\.001)", re.I)
LATER_PART = re.compile(r".+(?:\.part0*(?:[2-9]|\d{2,})\.rar|\.(?:7z|zip|rar)\.(?:00[2-9]|0[1-9]\d|[1-9]\d\d)|\.r\d\d)",
                        re.I)
# Windows marks a file kept only in the cloud (OneDrive's files on demand) with these attributes; reading such a file
# downloads it first. FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS, FILE_ATTRIBUTE_RECALL_ON_OPEN, FILE_ATTRIBUTE_OFFLINE.
CLOUD_ONLY = 0x00400000 | 0x00040000 | 0x00001000


def known_folder(guid):
    """A Windows known folder (follows OneDrive and moved folders), or None."""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]

    # Parse "{xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx}" into the structure the API takes.
    import uuid
    u = uuid.UUID(guid)
    value = GUID(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))
    out = ctypes.c_wchar_p()
    # SHGetKnownFolderPath allocates the string; CoTaskMemFree releases it.
    if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(value), 0, None, ctypes.byref(out)) != 0:
        return None
    try:
        return out.value
    finally:
        ctypes.windll.ole32.CoTaskMemFree(out)


def drives():
    """The drives Windows has (asked of Windows, not tried letter by letter: a network drive that is not connected
    can hold a look for seconds)."""
    if hasattr(os, "listdrives"):
        try:
            return os.listdrives()
        except OSError:
            pass
    import ctypes
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    return ["%s:\\" % c for i, c in enumerate(string.ascii_uppercase) if mask >> i & 1]


def places():
    """The folders to look in, most likely first, without duplicates."""
    found = []
    if sys.platform == "win32":
        # Desktop, Downloads, Documents: the known-folder ids, which follow OneDrive redirection.
        for guid in (DESKTOP, DOWNLOADS, DOCUMENTS):
            path = known_folder(guid)
            if path:
                found.append(path)
        # The top of every drive.
        found += drives()
    else:
        # Development on Linux: the same three folders under home.
        home = os.path.expanduser("~")
        found += [os.path.join(home, n) for n in ("Desktop", "Downloads", "Documents")]
    seen, out = set(), []
    for p in found:
        key = os.path.normcase(os.path.abspath(p))
        if key not in seen and os.path.isdir(p):
            seen.add(key)
            out.append(p)
    return out


def archive_name(name):
    """True when a file name is an archive's (whole, or a split one's first part) with one of the game's words."""
    # Names are matched without letter case, as Windows matches them.
    low = name.lower()
    if LATER_PART.fullmatch(low):
        # A later part is read through its first: the first stands for them all.
        return False
    if not (WHOLE.fullmatch(low) or FIRST_PART.fullmatch(low)):
        # Not an archive by its name (a path a player picks is judged by its content instead).
        return False
    # Downloads holds other archives too: only those named like the game's are opened to be judged.
    return any(word in low for word in GAME_WORDS)


def _game_here(names, path):
    """True when a folder whose entries are `names` is a game folder (core/game.py's test, from the listing at hand)."""
    # A program right in it: the client (its kind is judged later, by its content).
    if not any(n.lower().endswith(".exe") for n in names):
        return False
    # The game's files' folder, in any letter case.
    pack = next((n for n in names if n.lower() == g.PACK_DIR), None)
    if pack is None:
        return False
    try:
        inside = {n.lower() for n in os.listdir(os.path.join(path, pack))}
    except OSError:
        # A pack folder this user cannot read: no game folder to use here.
        return False
    # The two files every game folder has.
    return "config.pak" in inside and "discinfo.pak" in inside


def paths(where=None, depth=DEPTH, cancel=None):
    """Every game folder and every archive named like the game's in the usual places (or `where`), at most `depth`
    levels down, as they turn up. A game folder holds nothing else to find; a place inside another is looked through
    once."""
    # Folders already looked through (Documents may be inside a drive's top too): each once.
    done = set()
    for place in (where if where is not None else places()):
        base = os.path.abspath(place)
        if cancel is not None and cancel.is_set():
            return
        # Folders still to look in, with their depth below the place: nearest first, so a game folder near the top
        # turns up before a long look through a deep tree.
        todo = collections.deque([(base, 0)])
        while todo:
            # A stop is taken between two folders: never more than one listing late.
            if cancel is not None and cancel.is_set():
                return
            folder, level = todo.popleft()
            key = os.path.normcase(folder)
            if key in done:
                continue
            done.add(key)
            try:
                # One listing per folder, its entries' kinds with it (no stat of its own on Windows).
                with os.scandir(folder) as listing:
                    entries = list(listing)
            except OSError:
                # A folder this user cannot read (another user's, a disconnected drive) is passed by.
                continue
            names = [e.name for e in entries]
            if _game_here(names, folder):
                yield folder
                # A game folder holds nothing else to find, and its pack folder thousands of large files.
                continue
            subfolders = []
            for e in entries:
                try:
                    if e.is_dir(follow_symlinks=False):
                        # Deeper only within the depth, never into the folders that hold no player's game, nor hidden.
                        if level < depth and e.name.lower() not in SKIPPED and not e.name.startswith("."):
                            subfolders.append((e.path, level + 1))
                    elif archive_name(e.name) and e.is_file():
                        yield e.path
                except OSError:
                    # An entry gone between the listing and the look: passed by.
                    continue
            # In name order, so the same tree gives the same list every time.
            todo.extend(sorted(subfolders, key=lambda f: f[0].lower()))


def cloud_only(root):
    """True when any of the game's files in root is kept only in the cloud (its attributes say so; looking at them
    downloads nothing)."""
    # The pack folder by its own name (any letter case).
    pack = os.path.join(root, g.real_name(root, g.PACK_DIR) or g.PACK_DIR)
    try:
        names = os.listdir(pack)
    except OSError:
        # No pack folder to look at: nothing is said about the cloud.
        return False
    for name in names:
        try:
            # st_file_attributes exists on Windows only; elsewhere nothing is in a cloud of Windows'.
            attributes = getattr(os.stat(os.path.join(pack, name)), "st_file_attributes", 0)
        except OSError:
            # A file that cannot be looked at says nothing about the cloud either.
            continue
        if attributes & CLOUD_ONLY:
            return True
    return False
