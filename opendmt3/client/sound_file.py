"""The player's sound values in the one file the launcher and the in-game layer both write (the 0.4.0 list's #11):
sound.ini beside launcher.json, a name=value line each for the master volume, the music's and the key sounds'
(percent) and the equaliser's five bands (dB). The in-game layer's own reader and writer is
native/cardreader/soundset.c, by the same rules (logic.c sound_values_parse and sound_values_merge).

Neither side overwrites the other: a writer takes the file's lock (sound.ini.lock, held open alone while it writes;
Windows lets it go when the writer dies), reads the file as it is at that moment, rewrites only the lines of the values
it changed and swaps the result in through a temporary file. The launcher reads the file again when it starts, when
its Sound page is drawn, before PLAY and when the game closes, so a change made in the game comes back to it; the game
looks at the file twice a second, so a change made on the Sound page while it runs is heard at once.
"""

import os
import sys
import tempfile
import time

from opendmt3.core.cabinet import values as choices

FILE_NAME = "sound.ini"
# The file's first line, kept as it is by both writers (any line not a value's is).
HEADER = "# openDMT3's sound: the launcher's Sound page and the in-game sound panel both write it, each its own lines.\n"


def path_beside(settings_path):
    """The sound file beside the launcher's settings file."""
    return os.path.join(os.path.dirname(settings_path), FILE_NAME)


def parse(text):
    """{name: value} of the lines naming a sound value with a whole number in its range; any other line is left out
    (a hand-edited value out of range is as if it were not there, as the in-game reader takes it)."""
    out = {}
    for line in (text or "").splitlines():
        name, sep, value = line.partition("=")
        name = name.strip()
        if not sep or name not in choices.SOUND_FILE_VALUES:
            continue
        try:
            number = int(value.strip())
        except ValueError:
            continue
        low, high = choices.sound_range(name)
        if low <= number <= high:
            out[name] = number
    return out


def merge(old, changes):
    """The file's text again with the values in `changes` set and every other line as it was (another writer's values
    kept); a changed value with no line yet goes at the end, and a second line of a changed value is dropped."""
    lines, written = [], set()
    for line in (old or "").splitlines():
        name = line.partition("=")[0].strip() if "=" in line else None
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
    """The file's lock: sound.ini.lock opened alone. On Windows deleted when closed (a writer that dies lets it go);
    elsewhere (development) an advisory lock on it."""

    def __init__(self, path):
        self.path, self.handle, self.fd = path, None, None

    def __enter__(self):
        deadline = time.monotonic() + 1.0
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
            # Elsewhere than Windows the lock file goes too (Windows deletes its own when closed).
            try:
                os.unlink(self.path)
            except OSError:
                pass
            os.close(self.fd)
        return False


def read(path):
    """The file's values ({} when there is no file)."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            return parse(f.read())
    except FileNotFoundError:
        return {}


def write(path, changes):
    """Set these values in the file (only their lines), under its lock; returns the file's values after the write
    (another writer's included)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _Lock(path + ".lock"):
        try:
            with open(path, encoding="utf-8-sig") as f:
                old = f.read()
        except FileNotFoundError:
            # A new file starts with its header.
            old = HEADER
        text = merge(old, changes)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".sound-")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    return parse(text)


def sync(state, settings_path):
    """The launcher's sound values and the file's made one: the file's values taken into the launcher's state; with
    no file yet (the first start of a launcher that has it, or a new player), the file made from the state's, so the
    music and key sounds a player had set in launcher.json play as loud as before."""
    path = path_beside(settings_path)
    found = read(path)
    if not os.path.isfile(path) or set(found) != set(choices.SOUND_FILE_VALUES):
        # Every value the file lacks, written from the state as it is (only those lines).
        missing = {name: state.values[name] for name in choices.SOUND_FILE_VALUES if name not in found}
        try:
            found = write(path, missing)
        except OSError:
            # A folder that cannot be written (a locked profile): the state's values serve this run.
            return
    merged = dict(state.values)
    merged.update(found)
    state.values = choices.normalize(merged)
