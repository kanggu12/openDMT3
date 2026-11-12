"""Unpack the game folder from an archive a player brought, with the official 7-Zip (the launcher's own copy).

The archive is listed and judged first (server/services/sources.py: no absolute path, no "..", no device name, no
link, every part of a split archive there), then only the game folder's entries are taken out, into a new folder of
the launcher's own beside the place it goes (.openDMT3-unpacking-...), and checked file by file (each the size its
entry said, no link) before that folder is renamed into place in one step. Stopped or failed, the half-made folder is
removed: nothing is left behind. An archive inside an archive (two levels at most) is taken out first, then opened the
same way, and removed with the rest.

7-Zip runs as a child process; its progress (the percent it prints with -bsp1) becomes the share done and the time
left, and a stop ends it at once, as does writing more than the entries said (an archive whose sizes lie). A
password is passed on its standard input, never on its command line (which any user of the PC can read while it
runs), and a line no archive has goes there when none was given, so 7-Zip never waits for an answer no one sees.
"""

import logging
import os
import re
import secrets
import shutil
import threading
import time

from opendmt3.core.errors import Worded

log = logging.getLogger("opendmt3.launcher")

# The launcher's own folder beside the place a game folder goes, while it is being unpacked.
WORK_PREFIX = ".openDMT3-unpacking-"
# 7-Zip's percent in its progress lines ("  42% 12 - TECHNIKA 3/pack/..."), overwritten in place.
PERCENT = re.compile(rb"(\d{1,3})%")
# How many seconds of work before the time left is said (the first seconds are 7-Zip reading the archive's headers).
SETTLE = 3.0
# The time left is also reckoned from the last seconds of work alone: a disk slows down once its cache is full (a
# whole game measured: twice as slow in its second half), and the longer of the two reckonings is said.
RECENT = 20.0
# The first test of the few files the game needs most may take this long; past it the unpacking itself tests them.
FIRST_TEST_SECONDS = 15
# Room kept free beside an unpacked game folder (as intake.SPARE).
SPARE = 256 << 20
# Tries at moving the finished folder into place: a virus scanner may hold a new file for a moment on Windows.
RENAME_TRIES, RENAME_WAIT = 10, 0.5


class UnpackError(Worded):
    """Why an unpacking did not happen or stopped, in a player's words (the launcher's keys in i18n)."""


class Stopped(Exception):
    """The player stopped the unpacking; what it made is gone."""


def default_parent(archive):
    """Where a game folder is unpacked when nothing else is chosen: the archive's own folder."""
    return os.path.dirname(os.path.abspath(archive))


def folder_name(archive):
    """The new folder's name: the archive's name without its kinds and part numbers ("technika3" for technika3.7z,
    technika3.part1.rar and technika3.7z.001)."""
    name = os.path.basename(archive)
    # A RAR's part, a numbered part of any kind, then a whole archive: the name before them.
    for pattern in (r"(.+)\.part\d+\.rar", r"(.+)\.(?:7z|zip|rar)\.\d{3}", r"(.+)\.(?:7z|zip|rar|iso)"):
        m = re.fullmatch(pattern, name, re.I)
        if m:
            # A name that is only spaces and a kind still makes a folder.
            return m.group(1).strip() or "game"
    return os.path.splitext(name)[0] or "game"


def target(parent, archive):
    """The new game folder's path in `parent`: named after the archive, with " (2)", " (3)"... when taken."""
    base = folder_name(archive)
    path, n = os.path.join(parent, base), 2
    # Never into a folder that is there: what is in it stays as it is.
    while os.path.exists(path):
        path, n = os.path.join(parent, "%s (%d)" % (base, n)), n + 1
    return path


def room(parent):
    """The free room on the drive holding `parent` (or the nearest folder above it), or None."""
    from opendmt3.client import intake
    return intake.free_room(parent)


def writable(parent):
    """True when a new folder can be made in `parent` (a disc, a share or a folder of another user cannot)."""
    try:
        os.makedirs(parent, exist_ok=True)
        # A folder made and removed at once: the one way to know without asking Windows for rights.
        probe = os.path.join(parent, WORK_PREFIX + "probe-" + secrets.token_hex(4))
        os.mkdir(probe)
        os.rmdir(probe)
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------------------------- 7-Zip runs

class Run:
    """One 7-Zip run as a child process: its percent read as it goes (progress(fraction)), stopped when `cancel` is
    set; go() returns (exit code, everything it said apart from the progress). args are 7-Zip's command, its
    switches, then "--" and the archive. With a watch (sources.Watch) it is stopped as soon as it writes more than the
    entries said, and go() says the archive is damaged."""

    def __init__(self, args, password=None, progress=None, cancel=None, watch=None):
        from opendmt3.server.services import sources
        try:
            # The 7-Zip the reading underneath uses (the launcher's own, from client/main.py). Its percent on the
            # output, its errors with it, in one stream; names in UTF-8 whatever Windows' code page.
            self.command = sources.seven_zip_command(args, ["-bsp1", "-bse1"])
        except sources.SourceError:
            raise UnpackError("this launcher has no 7-Zip to open archives with", "intake.line.no_7zip") from None
        # The password is never on the command line: 7-Zip reads it on its standard input (sources.popen_7zip).
        self.password = password
        self.progress, self.cancel, self.watch = progress, cancel, watch
        # Set when the watch stopped it: what it wrote was more than the entries said.
        self.overran = False

    def go(self):
        from opendmt3.client import intake
        from opendmt3.server.services import sources
        # No window of its own on Windows (7z.exe is a console program); its standard input holds the password line
        # and then ends, so it can never wait on it.
        proc = sources.popen_7zip(self.command, self.password)
        said, buffered = [], b""
        if self.cancel is not None or self.watch is not None:
            # A stop, or more written than the entries said, ends 7-Zip at once, wherever it is in its work.
            threading.Thread(target=self._watch, args=(proc,), daemon=True, name="unpack-stop").start()
        try:
            while True:
                # Whatever is there, without waiting for a full block: the percent comes a few bytes at a time.
                chunk = proc.stdout.read1(65536) if hasattr(proc.stdout, "read1") else proc.stdout.read(4096)
                if not chunk:
                    break
                buffered += chunk
                # Progress is overwritten in place (backspaces on Linux, carriage returns on Windows); words end a
                # line.
                pieces = re.split(rb"[\b\r\n]", buffered)
                # The last piece may be cut in the middle: kept for the next chunk.
                buffered = pieces.pop()
                for piece in pieces:
                    self._piece(piece, said)
            self._piece(buffered, said)
            code = proc.wait()
        except BaseException:
            # Never left running behind the launcher (an error here, an interrupt on the command line).
            proc.kill()
            proc.wait()
            raise
        finally:
            proc.stdout.close()
        if self.cancel is not None and self.cancel.is_set():
            # Stopped on purpose: whatever 7-Zip said after its end is not why.
            raise Stopped()
        if self.overran:
            # It wrote more than the archive's entries said: an archive whose sizes are not what it holds.
            raise intake.said("error.source.damaged")
        return code, "\n".join(said)

    def _piece(self, piece, said):
        """One piece of 7-Zip's output: a percent for the progress, or words kept for what went wrong."""
        text = piece.strip()
        if not text:
            return
        m = PERCENT.match(text)
        if m:
            if self.progress:
                self.progress(min(100, int(m.group(1))) / 100.0)
            return
        said.append(text.decode("utf-8", "replace"))

    def _watch(self, proc):
        """End 7-Zip when the stop comes, or when it has written more than the entries said (both checked twenty times
        a second while it runs)."""
        from opendmt3.server.services import sources
        if self.watch is not None:
            # What 7-Zip writes is read from its own process (sources.Watch.follow).
            self.watch.follow(proc)
        while proc.poll() is None:
            stopped = self.cancel.wait(sources.WATCH_EVERY) if self.cancel is not None else None
            if self.cancel is None:
                # Nothing to stop it but the watch: the same pace.
                time.sleep(sources.WATCH_EVERY)
            if not stopped and self.watch is not None and self.watch.over():
                self.overran = True
                stopped = True
            if stopped:
                try:
                    proc.kill()
                except OSError:
                    # It ended by itself in the meantime.
                    pass
                return


def _verdict(code, out, password, archive):
    """The worded error for what 7-Zip said when it did not end well: a password, a part missing, a full disk, or a
    damaged archive."""
    from opendmt3.client import intake
    if "Wrong password" in out or "encrypted archive" in out:
        # 7-Zip's own words for both a password missing and one that is not the archive's.
        return intake.said("error.source.wrong_password" if password else "error.source.password")
    m = re.search(r"Missing volume : (.+)", out)
    if m:
        from opendmt3.server.services import sources
        # The part by its name, as 7-Zip names it: its number is said.
        number, _ = sources.part_of(os.path.join(os.path.dirname(archive), m.group(1).strip()))
        if number:
            return intake.said("error.source.missing_part", n=number)
    if "not enough space" in out.lower() or "no space left" in out.lower():
        # Windows' and Linux' words for a full disk.
        return UnpackError("the disk filled up while unpacking", "unpack.full")
    # A file that does not come out as its entry says (a CRC, data that does not decode, an archive cut short).
    return intake.said("error.source.damaged")


# ------------------------------------------------------------------------------------------------ the work

class Unpacking:
    """One archive unpacked into a parent folder. progress(fraction, seconds_left or None) is called from the work's
    thread as it goes; cancel (threading.Event) stops it. run() returns the new game folder's path."""

    def __init__(self, archive, parent, password=None, progress=None, cancel=None):
        self.archive, self.parent, self.password = archive, parent, password
        self.report = progress or (lambda fraction, left: None)
        self.cancel = cancel or threading.Event()
        # The launcher's own folder for the work, beside the place the game folder goes (the same drive: one rename).
        self.work = None
        # When the long work began: the time left is reckoned from it.
        self.started = None
        # The share of the whole that the 7-Zip run under way stands for: (where it starts, how much it is).
        self.weights = (0.0, 1.0)
        # (when, share done) of the last RECENT seconds, for the recent rate.
        self.samples = []

    def _progress(self, fraction):
        """A 7-Zip run's percent as the share of the whole, with the time left: what was done in the time it took,
        the rest at the same rate."""
        start, span = self.weights
        done = start + span * fraction
        now = time.monotonic()
        elapsed = now - self.started
        self.samples.append((now, done))
        # Only the last RECENT seconds are kept: the rate of the work as it goes now.
        while len(self.samples) > 2 and now - self.samples[0][0] > RECENT:
            self.samples.pop(0)
        left = None
        if elapsed >= SETTLE and done > 0.01:
            # The rest at the rate of the whole work so far...
            left = elapsed * (1 - done) / done
            first_at, first_done = self.samples[0]
            if now - first_at >= SETTLE and done > first_done:
                # ...or at the rate of the last seconds, when that is slower: a promise kept rather than a quick one.
                left = max(left, (now - first_at) * (1 - done) / (done - first_done))
        self.report(done, left)

    def run(self):
        self.started = time.monotonic()
        os.makedirs(self.parent, exist_ok=True)
        self.work = os.path.join(self.parent, WORK_PREFIX + secrets.token_hex(6))
        os.mkdir(self.work)
        try:
            game = self._open(self.archive, 1, (0.0, 1.0))
            final = target(self.parent, self.archive)
            # One rename on the same drive: the game folder is there whole, or not at all.
            self._move(game, final)
            self.report(1.0, 0)
            return final
        finally:
            # Whatever happened, the launcher's own folder goes: a stop, a failure and a success leave nothing.
            shutil.rmtree(self.work, ignore_errors=True)
            if os.path.exists(self.work):
                log.warning("could not remove all of %s", self.work)

    def _move(self, game, final):
        """Rename the finished folder into place, again for a few seconds while Windows holds one of its files (a virus
        scanner reading a new file): an hour of unpacking is not thrown away for that."""
        for attempt in range(RENAME_TRIES):
            try:
                os.rename(game, final)
                return
            except PermissionError:
                if attempt == RENAME_TRIES - 1:
                    raise
                time.sleep(RENAME_WAIT)

    def _open(self, archive, depth, weights):
        """The game folder unpacked from `archive` (inside self.work), through archives inside it up to two levels."""
        from opendmt3.client import intake
        from opendmt3.server.services import sources
        if self.cancel.is_set():
            raise Stopped()
        gap = sources.missing_part(archive)
        if gap is not None:
            # Said before anything is made: every part must be beside the first.
            raise intake.said("error.source.missing_part", n=gap)
        # A refusal of the listing (a password, a part missing, damaged) says itself.
        entries = sources.listing(archive, self.password)
        root = sources.game_in(entries)
        if root is None:
            inside = sources.inner_archives(entries)
            if not inside or depth >= sources.NESTING_MOST:
                # No game folder, and no archive inside within two levels: nothing of the game's.
                raise intake.said("error.source.nothing")
            first = inside[0]
            # A split archive inside comes out with all its parts.
            _, stem = sources.part_of(os.path.basename(first.name))
            parts = [e for e in entries if not e.folder and stem
                     and sources.part_of(os.path.basename(e.name))[1] == stem and e is not first]
            take = [first] + parts
            for e in take:
                # No unsafe name, no link, and a size for each (what 7-Zip writes is held to it).
                if sources.cannot_take(e):
                    raise sources.entry_refused(e.name)
            again = sources.twice(take)
            if again is not None:
                # The same name twice (in any letter case): one would land on the other.
                raise sources.entry_refused(again.name)
            # The room for the archive inside and the game folder from it, about as large again.
            self._room(sum(e.size for e in take) * 2 + SPARE)
            # The archive inside first (half the work), then the game folder from it (the other half).
            half = (weights[0], weights[1] / 2.0)
            out = os.path.join(self.work, "inner%d" % depth)
            os.mkdir(out)
            self._extract(archive, take, out, half)
            return self._open(os.path.join(out, *first.name.split("/")), depth + 1,
                              (weights[0] + weights[1] / 2.0, weights[1] / 2.0))
        # Only the game folder's own entries: notes or other programs beside it in the archive stay in it.
        lowered = root.lower()
        take = [e for e in entries if not e.folder and e.name.lower().startswith(lowered)]
        for e in take:
            # No unsafe name, no link, and a size for each (what 7-Zip writes is held to it).
            if sources.cannot_take(e):
                raise sources.entry_refused(e.name)
        again = sources.twice(take)
        if again is not None:
            # The same name twice (in any letter case): on Windows one file would stand for both.
            raise sources.entry_refused(again.name)
        self._room(sum(e.size for e in take) + SPARE)
        if any(e.encrypted for e in take) and not self.password:
            # Its files need the password even when its names did not.
            raise intake.said("error.source.password")
        out = os.path.join(self.work, "game%d" % depth)
        os.mkdir(out)
        self._first_test(archive, take, root)
        self._extract(archive, take, out, weights)
        # The game folder as the archive spells it, inside the launcher's own folder.
        return os.path.join(out, *root.rstrip("/").split("/")) if root else out

    def _room(self, needed):
        """UnpackError, before anything is made, when the drive has not the room the work needs."""
        from opendmt3.client import intake
        free = room(self.parent)
        if free is not None and free < needed:
            raise UnpackError("not enough free space", "intake.line.no_space", needed=intake.size_words(needed),
                              free=intake.size_words(free))

    def _first_test(self, archive, take, root):
        """Test the few files the game needs most (the programs and the song list's) before the long work: a
        damaged one is said in seconds. In one solid block they may sit behind everything else: past
        FIRST_TEST_SECONDS the unpacking itself tests them."""
        needed = [e for e in take if "/" not in e.name[len(root):] or
                  re.fullmatch(r"pack/(config|discinfo)(\d\d)?\.pak", e.name[len(root):], re.I)]
        if not needed:
            return
        from opendmt3.server.services import sources
        # The names in a list file, matched as they are (no wildcards), in UTF-8.
        names = os.path.join(self.work, "first-test.txt")
        listed = sources.names_file(names, needed)
        # The test stops at the player's stop, or when it takes too long.
        enough = threading.Event()
        timer = threading.Timer(FIRST_TEST_SECONDS, enough.set)
        timer.daemon = True
        timer.start()
        both = _Either(self.cancel, enough)
        try:
            # The list by its switch, then "--": the archive's name is never read as a switch.
            code, said = Run(["t", "-spd", "-scsUTF-8", listed, "--", archive], self.password, cancel=both).go()
        except Stopped:
            if self.cancel.is_set():
                raise
            # Too slow to test apart: the unpacking tests every file anyway.
            return
        finally:
            timer.cancel()
            os.remove(names)
        if code != 0:
            raise _verdict(code, said, self.password, archive)

    def _extract(self, archive, take, out, weights):
        """Take the entries out into `out`, then check what came: each file the size its entry said, no link,
        nothing else."""
        from opendmt3.server.services import sources
        self.weights = weights
        # The names in a list file beside `out` (not in it: the check finds nothing but the entries there).
        names = out + ".names"
        listed = sources.names_file(names, take)
        try:
            # Watched while it runs: stopped as soon as what it wrote is more than the entries said.
            code, said = Run(["x", "-y", "-bso0", "-spd", "-scsUTF-8", "-o" + out, listed, "--", archive],
                             self.password, progress=self._progress, cancel=self.cancel,
                             watch=sources.Watch(out, sum(e.size for e in take))).go()
        finally:
            os.remove(names)
        if code != 0:
            raise _verdict(code, said, self.password, archive)
        # Each file the size its entry said, no link, nothing else: the server's own check of what came out.
        sources._check_extracted(take, out)


class _Either:
    """Two events read as one: set when either is (a stop, or a time up)."""

    def __init__(self, a, b):
        self.a, self.b = a, b

    def is_set(self):
        return self.a.is_set() or self.b.is_set()

    def wait(self, seconds):
        """As Event.wait: True as soon as either is set, else False after `seconds`."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.is_set():
                return True
            # Fine enough for a stop to feel at once, light enough to cost nothing.
            time.sleep(0.02)
        return self.is_set()
