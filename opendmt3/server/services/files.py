"""JSON files beside the database (the song list, the DJ card's tables), read once and kept while they stay the same.

Pages and logins read them many times a second; reading and parsing them each time cost more than the page's own
work. A file is read again when its modification time, size or inode changes (a new list is written to a new file
and moved into place, which always changes the inode). What comes back is shared by every caller, so it is
read-only: dicts and lists that refuse to change, raising TypeError instead of quietly changing everyone's copy.
dict() and list() of them give a copy that can be changed.
"""

import json
import os
import stat
import threading
import time

# How a file the server writes in its data folder is made: new where nothing is (O_EXCL, which follows no link), never
# through a link (O_NOFOLLOW, where the system has it), and without Windows' line ends (O_BINARY, Windows only).
NEW = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)


def open_new(path, text=False):
    """A new file at `path` opened to write (text: in UTF-8), never through a link and never into a file that is there:
    whatever has the name goes first (a link itself, never what it leads to), then the file is made where nothing is.
    A data folder is its owner's: a link they left at a name the server writes never makes it write anywhere else."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    fd = os.open(path, NEW, 0o666)
    return os.fdopen(fd, "w", encoding="utf-8") if text else os.fdopen(fd, "wb")


def _refuse(self, *args, **kwargs):
    # One answer for every way of changing a shared value.
    raise TypeError("this value is read from a file and shared by every caller; change a copy (dict() or list())")


class FrozenDict(dict):
    """A dict that cannot be changed. JSON, Jinja and dict() read it as a plain dict."""

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _refuse

    def __reduce_ex__(self, protocol):
        # copy.copy, copy.deepcopy and pickle make a plain dict of it (their usual way sets its items one by one).
        return dict, (dict(self),)


class FrozenList(list):
    """A list that cannot be changed. JSON, Jinja and list() read it as a plain list."""

    __setitem__ = __delitem__ = append = extend = insert = pop = remove = clear = sort = reverse = _refuse
    __iadd__ = __imul__ = _refuse

    def __reduce_ex__(self, protocol):
        # copy.copy, copy.deepcopy and pickle make a plain list of it.
        return list, (list(self),)


def frozen(value):
    """JSON data (dicts, lists and plain values) as the read-only types above, all the way down."""
    if isinstance(value, dict):
        return FrozenDict((key, frozen(item)) for key, item in value.items())
    if isinstance(value, list):
        return FrozenList(frozen(item) for item in value)
    return value


# path -> (the file's stamp when read, what was made of it). A few files per data folder; tests make many folders.
_KEPT = {}
KEPT_FILES = 32
_LOCK = threading.Lock()
# On Windows a file refuses to open (PermissionError) while os.replace moves a new copy into its place, as every file
# here is written: the handle it moves it by shares nothing with a reader, for a moment. A read waits that out, trying
# again every REFUSED_PAUSE seconds for REFUSED_WAIT at most (a login that raised it lost its cabinet's link).
REFUSED_WAIT, REFUSED_PAUSE = 1.0, 0.002


def _stamp(path):
    """What changes when the file is written again (its modification time, size and inode), or None when there is
    no regular file there."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    # A folder or a device under that name is no file of ours: the same as none.
    return (st.st_mtime_ns, st.st_size, st.st_ino) if stat.S_ISREG(st.st_mode) else None


def stamp(path):
    """What changes when the file at `path` is written again (_stamp), for those who keep what they made of it beside
    other things (the site's DJ pages keep the song list's titles: web/common.py)."""
    return _stamp(path)


def _on_windows():
    """Whether this is Windows, whose files refuse to open while they are replaced (a test says so on any system)."""
    return os.name == "nt"


def _read(path):
    """The file's bytes, read whole and the file closed before they are parsed: on Windows a file open in a reader
    cannot be replaced, so it is held no longer than the read. A refusal while a new copy is moved into its place is
    waited out on Windows (REFUSED_WAIT); anywhere else, or for longer, it is raised."""
    given_up = time.monotonic() + REFUSED_WAIT
    while True:
        try:
            with open(path, "rb") as f:
                return f.read()
        except PermissionError:
            # Windows' moment of a replace passes at once; another system, or a refusal that stays, is a real one.
            if not _on_windows() or time.monotonic() >= given_up:
                raise
            time.sleep(REFUSED_PAUSE)


def load(path, make=lambda data: data, missing=None):
    """make(the file's JSON), read-only (frozen), kept until the file changes; `missing` when there is no file.

    `make` turns the JSON into what callers use (the song list keyed by number, for one); it runs once per change of
    the file, and its result is frozen.
    """
    stamp = _stamp(path)
    if stamp is None:
        with _LOCK:
            # Nothing is kept for a missing file, so one put there later is read then.
            _KEPT.pop(path, None)
        return missing
    kept = _KEPT.get(path)
    if kept is not None and kept[0] == stamp:
        # The same file as last time: what was made of it then.
        return kept[1]
    # The bytes first (_read: closed again at once), then the JSON, in UTF-8 as every one of these files is written.
    value = frozen(make(json.loads(_read(path).decode("utf-8"))))
    with _LOCK:
        # Pages read on the server's loop and the launcher's worker threads: one change of the table at a time.
        if len(_KEPT) >= KEPT_FILES and path not in _KEPT:
            # The file kept longest goes (dicts keep their order): the folders of finished tests, say.
            _KEPT.pop(next(iter(_KEPT)))
        _KEPT[path] = (stamp, value)
    return value
