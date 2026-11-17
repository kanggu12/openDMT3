"""The site's requests log: every page and API call the site answered, for the admin's Logs tab (Requests) and GET
/api/v1/log/requests.

Each request is one line of JSON in logs/requests.log in the data folder: when, the method, the path (a one-use
sign-in link's token left out), the status, how long the answer took, the address it came from and the account that
asked, if one did. The files every page loads (styles, fonts, pictures) and the health check are not logged: they are
many and say nothing about who used the site.

The log keeps itself small: a file reaches MOST_BYTES, then it becomes requests.log.1 (the one before becomes .2, and
so on), FILES of them in all; a file whose newest line is older than DAYS days goes too. At most MOST_BYTES x FILES
on disk, whatever the traffic.

The event loop the game server shares only appends a request to a list (add(): no file, no lock held long); once
WRITE_EVERY seconds have passed since the last write, the site writes the lines waiting on a worker thread right after
a request is answered (app.Logged: due(), then write()), so the log writes only while the site answers, never into a
data folder that has gone. The Logs tab's list and filter read the newest RECENT lines from the files when asked
(nothing of them is kept in memory), and the last day is counted by half hours for its chart, so the chart reads no
file.
Only the standard library.
"""

import collections
import json
import os
import threading
import time

# The log's folder in the data folder, and its file's name.
FOLDER = "logs"
NAME = "requests.log"
# A file's size before it is turned over, the files kept (the current one with them), and the days a file is kept.
MOST_BYTES = 2 * 1024 * 1024
FILES = 4
DAYS = 14
# Requests kept in memory for the Logs tab (the newest), seconds between two writes of the lines waiting, and the
# lines that may wait at most (a disk that refuses them for long loses the oldest, never the site's memory).
RECENT = 5000
WRITE_EVERY = 1.0
WAITING_MOST = 20000
# The chart's slots: half hours, a day of them.
SLOT = 1800
SLOTS = 48
# The longest path kept, in characters: a query can be long, and a line stays one line of a sane length.
PATH_MOST = 300
# The methods kept as they came: HTTP's own. Any other (a method is any token, and a token may hold + - ' | !, which a
# spreadsheet reads as a formula in the CSV file) is kept as one word.
METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
OTHER_METHOD = "OTHER"
# The longest address kept, in characters: an IPv6 address with its zone fits; behind --proxy the address is what the
# proxy's forwarded header names, which may be anything.
ADDRESS_MOST = 64
# A one-use sign-in link (the launcher's, from this PC) carries its token in its path: kept as this prefix alone.
SECRET_PATHS = ("/signin/once/",)
# The statuses a filter can ask for, by their first digit, and the words a program sends for them.
KINDS = {"ok": "2", "moved": "3", "refused": "4", "failed": "5"}
# The fields of a line, in the order a CSV file gives them.
FIELDS = ("at", "method", "path", "status", "ms", "address", "who")


def kept_path(path):
    """A path as the log keeps it: a secret part left out, cut to PATH_MOST characters."""
    for prefix in SECRET_PATHS:
        if path.startswith(prefix):
            return prefix + "..."
    return path if len(path) <= PATH_MOST else path[:PATH_MOST - 3] + "..."


def kept_method(method):
    """A method as the log keeps it: one of HTTP's own (METHODS) as it came, any other as OTHER_METHOD."""
    return method if method in METHODS else OTHER_METHOD


def kept_address(address):
    """An address as the log keeps it: as text, cut to ADDRESS_MOST characters."""
    address = str(address)
    return address if len(address) <= ADDRESS_MOST else address[:ADDRESS_MOST - 3] + "..."


def kind_of(status):
    """The kind of a status for the filter and the chart: ok, moved, refused or failed."""
    first = str(status)[:1]
    for kind, digit in KINDS.items():
        if first == digit:
            return kind
    return "failed"


class RequestLog:
    """One data folder's requests log (one server's)."""

    def __init__(self, data_dir, clock=time.time, most_bytes=MOST_BYTES, files=FILES, days=DAYS):
        self.data_dir = data_dir
        self.folder = os.path.join(data_dir, FOLDER)
        self.clock, self.most_bytes, self.files, self.days = clock, most_bytes, files, days
        # The lines waiting for the writer, as the loop added them: a deque's append is safe from any thread.
        self._waiting = collections.deque(maxlen=WAITING_MOST)
        # The last day by half hours: slot number -> [ok and moved, refused and failed].
        self._slots = {}
        # Guards _slots and the files (the writer turns a file over while the tab's download reads them).
        self._lock = threading.Lock()
        # One write at a time (two requests may find it due at once), and when the last one began (monotonic).
        self._writing = threading.Lock()
        self._written = time.monotonic()
        # Whether the files' last day has been counted into the chart and the newest lines into memory.
        self._loaded = False

    @property
    def path(self):
        return os.path.join(self.folder, NAME)

    # ------------------------------------------------------------------------------------------- adding

    def add(self, method, path, status, ms, address, who=None, at=None):
        """One request answered (on the event loop: cheap). Kept as a tuple in FIELDS' order: a third of a dict's
        memory, for the RECENT kept."""
        # The method one of HTTP's, the path and the address cut to a sane length: a line holds nothing a client chose
        # beyond what it is for.
        line = (round(self.clock() if at is None else at, 3), kept_method(method), kept_path(path), int(status),
                round(ms, 1), kept_address(address), who)
        # The file's line made here, once (a few microseconds), so the writer only joins and writes strings.
        self._waiting.append(json.dumps(dict(zip(FIELDS, line)), ensure_ascii=False, separators=(",", ":")) + "\n")
        self._count(line)

    def _count(self, line):
        """The request in its half hour of the chart, the slots older than a day forgotten."""
        # A line's moment and status, by their places in FIELDS.
        slot = int(line[0] // SLOT)
        bad = 1 if line[3] >= 400 else 0
        with self._lock:
            counts = self._slots.get(slot)
            if counts is None:
                counts = self._slots[slot] = [0, 0]
                # A new half hour: the day's oldest one goes (a dict of SLOTS + 1 entries at most).
                for old in [s for s in self._slots if s <= slot - SLOTS]:
                    del self._slots[old]
            counts[bad] += 1

    def due(self):
        """True when lines wait and WRITE_EVERY seconds have passed since the last write (or the files were never
        read in): the site then calls write() on a worker thread."""
        return (bool(self._waiting) or not self._loaded) and time.monotonic() - self._written >= WRITE_EVERY

    # ------------------------------------------------------------------------------------------- writing

    def write(self):
        """Every line waiting written to the file, turning it over when it passes most_bytes (the files' last day read
        in first, once). Returns how many; 0 while another write runs, and when the data folder is not there (its
        lines are dropped: nothing makes a data folder again)."""
        if not self._writing.acquire(blocking=False):
            return 0
        try:
            self._written = time.monotonic()
            if not os.path.isdir(self.data_dir):
                self._waiting.clear()
                return 0
            self.load()
            try:
                return self._write()
            except OSError:
                # A disk that is full or refuses the file loses those lines, never the site's answer.
                return 0
        finally:
            self._writing.release()

    def _write(self):
        """write()'s lines to the file, under _writing."""
        lines = []
        while self._waiting:
            lines.append(self._waiting.popleft())
        if not lines:
            return 0
        text = "".join(lines)
        with self._lock:
            # The log's own folder, in a data folder that is there (write() looked).
            if not os.path.isdir(self.folder):
                os.mkdir(self.folder)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(text)
                size = f.tell()
            if size >= self.most_bytes:
                self._turn_over()
        return len(lines)

    def _turn_over(self):
        """requests.log becomes .1, .1 becomes .2 and so on; the oldest past `files` goes, and so does any file whose
        newest line is older than `days` days (by its time of last change). Under _lock."""
        oldest = os.path.join(self.folder, "%s.%d" % (NAME, self.files - 1))
        if os.path.exists(oldest):
            os.remove(oldest)
        for n in range(self.files - 2, 0, -1):
            older = os.path.join(self.folder, "%s.%d" % (NAME, n))
            if os.path.exists(older):
                os.replace(older, os.path.join(self.folder, "%s.%d" % (NAME, n + 1)))
        os.replace(self.path, self.path + ".1")
        self.tidy()

    def tidy(self):
        """Files older than `days` days removed (the current one too: a quiet server's log ages as well)."""
        limit = self.clock() - self.days * 86400
        for path in self.paths():
            try:
                if os.path.getmtime(path) < limit:
                    os.remove(path)
            except OSError:
                pass

    def paths(self):
        """The log's files that are there, oldest first."""
        names = ["%s.%d" % (NAME, n) for n in range(self.files - 1, 0, -1)] + [NAME]
        return [p for p in (os.path.join(self.folder, n) for n in names) if os.path.isfile(p)]

    # ------------------------------------------------------------------------------------------- reading

    def load(self):
        """Once, at the first write (before this process's own lines go in): the last day of the files (from before a
        restart) counted into the chart."""
        if self._loaded:
            return
        self._loaded = True
        since = self.clock() - SLOTS * SLOT
        for line in self._lines():
            at, status = line.get("at"), line.get("status")
            if isinstance(at, (int, float)) and isinstance(status, int) and at >= since:
                self._count(tuple(line.get(name) for name in FIELDS))

    def _newest(self, most):
        """The newest `most` lines of the files, newest first, as dicts (the newest file read first, from its end)."""
        with self._lock:
            paths = self.paths()[::-1]
        taken = 0
        for path in paths:
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    texts = f.read().splitlines()
            except OSError:
                continue
            for text in reversed(texts):
                try:
                    line = json.loads(text)
                except ValueError:
                    continue
                if isinstance(line, dict):
                    yield line
                    taken += 1
                    if taken >= most:
                        return

    def _lines(self):
        """Every line of the files, oldest first, as dicts; a line cut short (a server stopped mid-write) left out."""
        with self._lock:
            paths = self.paths()
        for path in paths:
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    for text in f:
                        try:
                            line = json.loads(text)
                        except ValueError:
                            continue
                        if isinstance(line, dict):
                            yield line
            except OSError:
                # Turned over or removed while read: what was read stands.
                continue

    def recent(self, q="", kind="", most=200):
        """The newest requests (of the newest RECENT the files hold: the lines waiting written first) the filter leaves,
        newest first, at most `most`, and how many of them it left in all. q: text in the path, the address or the
        account (in any case); kind: ok, moved, refused or failed, or a status itself ("404"). Read from the files
        when asked (a few milliseconds for the Logs tab), never kept in memory: thousands of small lines kept for long
        among each request's own short-lived ones held far more of the server's memory than their size."""
        self.write()
        matches = self._matcher(q, kind)
        found, shown = 0, []
        for line in self._newest(RECENT):
            if matches(line):
                found += 1
                if len(shown) < most:
                    shown.append(line)
        return shown, found

    def all(self, q="", kind=""):
        """Every line the files hold that the filter leaves, oldest first (the Logs tab's file): the writer's waiting
        lines written first, so the file has the newest too."""
        self.write()
        matches = self._matcher(q, kind)
        for line in self._lines():
            if matches(line):
                yield line

    @staticmethod
    def _matcher(q, kind):
        """The filter as a test of one line."""
        word = (q or "").strip().casefold()
        kind = (kind or "").strip()

        def matches(line):
            if kind:
                if kind.isdigit():
                    if str(line.get("status")) != kind:
                        return False
                elif kind_of(line.get("status", 0)) != kind:
                    return False
            if word:
                text = " ".join(str(line.get(k) or "") for k in ("method", "path", "address", "who")).casefold()
                if word not in text:
                    return False
            return True
        return matches

    def chart(self, end=None):
        """The last day in SLOTS half hours ending with the one `end` (now) is in, oldest first: [{"at" (the half
        hour's start), "ok" (answered or moved on), "bad" (refused or failed)}]."""
        end = self.clock() if end is None else end
        last = int(end // SLOT)
        with self._lock:
            slots = dict(self._slots)
        return [{"at": s * SLOT, "ok": slots.get(s, (0, 0))[0], "bad": slots.get(s, (0, 0))[1]}
                for s in range(last - SLOTS + 1, last + 1)]

    def size(self):
        """The bytes the log's files take now."""
        total = 0
        for path in self.paths():
            try:
                total += os.path.getsize(path)
            except OSError:
                pass
        return total


# One log a data folder, for the whole process: every Site of that folder shares it (and its writer).
_logs = {}
_logs_lock = threading.Lock()


def for_dir(data_dir):
    """The data folder's requests log, made the first time it is asked for."""
    key = os.path.abspath(data_dir)
    with _logs_lock:
        found = _logs.get(key)
        if found is None:
            found = _logs[key] = RequestLog(data_dir)
        return found
