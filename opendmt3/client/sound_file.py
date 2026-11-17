"""The player's sound values in the one file the launcher and the in-game layer both write (the 0.4.0 list's #11):
sound.ini beside launcher.json, a name=value line each for the master volume, the music's and the key sounds'
(percent) and the equaliser's five bands (dB). The in-game layer's own reader and writer is
native/cardreader/soundset.c, by the same rules (logic.c sound_line_value and sound_values_merge); the table of lines
both readers' tests read is tests/fixtures/sound_lines.txt.

Neither side overwrites the other: a writer takes the file's lock (sound.ini.lock, held open alone while it writes;
Windows lets it go when the writer dies), reads the file as it is at that moment, rewrites only the lines of the values
it changed and swaps the result in through a temporary file. The launcher reads the file under the lock too (a read
holding the file open would refuse the game's swap), again when it starts, when its Sound page is drawn, before PLAY
and when the game closes, so a change made in the game comes back to it; the game looks at the file twice a second, so
a change made on the Sound page while it runs is heard at once.

A change the launcher cannot write (the lock held past a second, the file read-only or held open by another program)
is kept in the launcher's state as waiting (LauncherState's sound changes), said in its log, written at the next sync,
and never replaced by the file's older value meanwhile.
"""

import logging
import os
import re
import sys
import tempfile
import time

from opendmt3.core.cabinet import values as choices

log = logging.getLogger("opendmt3.launcher")

FILE_NAME = "sound.ini"
# The file's first line, kept as it is by both writers (any line not a value's is).
HEADER = "# openDMT3's sound: the launcher's Sound page and the in-game sound panel both write it, each its own lines.\n"
# A UTF-8 byte order mark at the file's start (Notepad may save one): no part of its first line.
BOM = "﻿"
# How long a writer (or a reader) waits for the other's lock: its write takes milliseconds.
LOCK_WAIT = 1.0
# A line's name, and the one rule for its value (logic.c sound_line_value): spaces and tabs round each part, a minus
# sign or none, one to four ASCII digits, nothing after but spaces, tabs and the line's own \r.
_NAME = re.compile(r"[ \t]*([a-z0-9_]+)[ \t]*=")
_VALUE = re.compile(r"[ \t]*(-?[0-9]{1,4})[ \t\r]*", re.ASCII)


def path_beside(settings_path):
    """The sound file beside the launcher's settings file."""
    return os.path.join(os.path.dirname(settings_path), FILE_NAME)


def line_value(line):
    """(name, value) of a line naming a sound value: value None when the rule does not take what follows its '='
    ("40abc", "0x20", "1_0", "+40", out of range); (None, None) for any other line."""
    named = _NAME.match(line)
    if not named or named.group(1) not in choices.SOUND_FILE_VALUES:
        return None, None
    name = named.group(1)
    value = _VALUE.fullmatch(line, named.end())
    if not value:
        return name, None
    number = int(value.group(1))
    low, high = choices.sound_range(name)
    return name, number if low <= number <= high else None


def parse(text, refused=None):
    """{name: value} of the lines the rule takes; a line naming a value with anything else is as if it were not there
    (added to `refused` when given, for the log); a byte order mark at the start is skipped."""
    out = {}
    text = (text or "")
    if text.startswith(BOM):
        text = text[len(BOM):]
    for line in text.split("\n"):
        name, value = line_value(line)
        if name and value is not None:
            out[name] = value
        elif name and refused is not None:
            refused.append(line.rstrip("\r"))
    return out


def merge(old, changes):
    """The file's text again with the values in `changes` set and every other line as it was (another writer's values
    kept, a line the rule does not take kept too); a changed value with no line yet goes at the end, a second line of a
    changed value is dropped, and a byte order mark at the start is dropped (logic.c sound_values_merge)."""
    old = old or ""
    if old.startswith(BOM):
        old = old[len(BOM):]
    lines, written = [], set()
    for line in old.splitlines():
        named = _NAME.match(line)
        name = named.group(1) if named else None
        if name in changes:
            if name not in written:
                lines.append("%s=%d" % (name, changes[name]))
                written.add(name)
            continue
        lines.append(line)
    for name in choices.SOUND_FILE_VALUES:
        if name in changes and name not in written:
            lines.append("%s=%d" % (name, changes[name]))
    return "".join(line + "\n" for line in lines)


class _Lock:
    """The file's lock: sound.ini.lock opened alone. On Windows deleted when closed (a writer that dies lets it go; one
    still being deleted refuses for a moment, as one held does); elsewhere (development) an advisory lock on it, the
    file left in place (taking it away while locked would let a third writer lock a new file beside the held one)."""

    def __init__(self, path):
        self.path, self.handle, self.fd = path, None, None

    def __enter__(self):
        deadline = time.monotonic() + LOCK_WAIT
        while True:
            if self._try():
                return self
            # Held by the other writer, whose write takes milliseconds: a moment later, a second at most.
            if time.monotonic() > deadline:
                raise OSError("the sound file's lock is held: %s" % self.path)
            time.sleep(0.01)

    def _try(self):
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            create = ctypes.windll.kernel32.CreateFileW
            create.restype = wintypes.HANDLE
            # Read and write, shared with nobody, made when missing, temporary, gone when closed.
            handle = create(self.path, 0xC0000000, 0, None, 4, 0x100 | 0x04000000, None)
            if handle in (None, wintypes.HANDLE(-1).value):
                return False
            self.handle = handle
            return True
        import fcntl
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            os.close(self.fd)
            self.fd = None
            return False

    def __exit__(self, *exc):
        if self.handle is not None:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(self.handle)
        if self.fd is not None:
            # Let go (closing the file ends its lock); the file stays, see the class.
            os.close(self.fd)
        return False


def _read_text(path):
    """The file's text ("" when there is none)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def read(path):
    """The file's values ({} when there is no file), read under its lock when it can be had within a second (a read
    holding the file open makes the game's swap fail), else read as it is. A line naming a value with anything the
    rule does not take is said in the log."""
    try:
        with _Lock(path + ".lock"):
            text = _read_text(path)
    except OSError:
        text = _read_text(path)
    refused = []
    values = parse(text, refused)
    for line in refused:
        log.warning("a line of the sound file is not one its rule takes, left as if absent: %r", line[:60])
    return values


def write(path, changes):
    """Set these values in the file (only their lines), under its lock; returns the file's values after the write
    (another writer's included). Raises OSError when it cannot be written."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _Lock(path + ".lock"):
        old = _read_text(path) or HEADER
        text = merge(old, changes)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".sound-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            os.replace(tmp, path)
        except OSError:
            # The temporary goes when the swap fails (a read-only file, one held open by another program).
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    return parse(text)


def sync(state, settings_path, pending=None):
    """The launcher's sound values and the file's made one. `pending` holds the launcher's changes not written yet
    ({name: value}): tried first; what still cannot be written stays in it and stays the state's (the file's older
    value never takes its place). Then the file's values come into the state; with no file yet (the first start of a
    launcher that has it, or a new player), the file is made from the state's, so the music and key sounds a player had
    set in launcher.json play as loud as before."""
    pending = pending if pending is not None else {}
    path = path_beside(settings_path)
    if pending:
        try:
            write(path, dict(pending))
            log.info("the sound file's waiting changes written: %s", ", ".join(sorted(pending)))
            pending.clear()
        except OSError as e:
            log.warning("the sound file still cannot be written (%s): %s kept, tried again at the next sync", e,
                        ", ".join(sorted(pending)))
    found = read(path)
    if not os.path.isfile(path) or set(found) != set(choices.SOUND_FILE_VALUES):
        # Every value the file lacks, written from the state as it is (only those lines).
        missing = {name: state.values[name] for name in choices.SOUND_FILE_VALUES if name not in found}
        try:
            found = write(path, missing)
        except OSError:
            # A folder that cannot be written (a locked profile): the state's values serve this run.
            found = {}
    merged = dict(state.values)
    # The file's values, but not over a change of the launcher's still waiting to be written.
    merged.update({name: value for name, value in found.items() if name not in pending})
    state.values = choices.normalize(merged)
