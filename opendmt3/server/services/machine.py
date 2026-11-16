"""The machine the server runs on, over the last day: its processors, memory and the data folder's disk, for the
admin's Status tab and GET /api/v1/status/machine.

A thread of its own looks every EVERY seconds at how busy the processors were since its last look; every POINT
seconds it keeps one point: the processors' average and peak over those looks, the memory in use, the disk in use
and the cabinets connected. KEEP points make a day. They are written to a small file in the data folder (FILE,
replaced whole each time, never more than that day: a few tens of kilobytes) so the charts outlive a restart; points
older than a day are dropped as new ones come, so the file never grows.

Read from /proc on Linux (inside a container it describes the machine itself), and from the system's own calls on
Windows (the launcher's built-in server). Elsewhere the processors and memory are not known (None), the disk is.
Only the standard library.
"""

import collections
import json
import os
import shutil
import sys
import threading
import time

# Seconds between two looks at the processors.
EVERY = 10
# Seconds one kept point covers, and the points kept: a day in five-minute points.
POINT = 300
KEEP = 288
# The day's points in the data folder.
FILE = "machine.json"


# ------------------------------------------------------------------------------------------------ reading

def read_cpu():
    """(all, idle) processor time since the machine started, in the system's own units (only their differences are
    used), or None where it cannot be read."""
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/stat", encoding="ascii") as f:
                # The first line adds up every processor: user, nice, system, idle, iowait, irq, softirq, steal.
                values = [int(v) for v in f.readline().split()[1:9]]
        except (OSError, ValueError):
            return None
        # Idle and waiting for the disk both count as not busy.
        return sum(values), values[3] + values[4]
    if sys.platform == "win32":
        return _windows_cpu()
    return None


def _windows_cpu():
    """read_cpu() on Windows: GetSystemTimes (kernel time includes idle time there)."""
    try:
        import ctypes
        from ctypes import wintypes
        idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
    except (ImportError, AttributeError, OSError):
        return None
    # A FILETIME is two 32-bit halves of a count of 100-nanosecond steps.
    ticks = lambda t: (t.dwHighDateTime << 32) | t.dwLowDateTime
    return ticks(kernel) + ticks(user), ticks(idle)


def read_memory():
    """{"total", "used"} in bytes (used: what programs hold, without the cache the system gives back at once), or None
    where it cannot be read."""
    if sys.platform.startswith("linux"):
        found = {}
        try:
            with open("/proc/meminfo", encoding="ascii") as f:
                for line in f:
                    name, _, rest = line.partition(":")
                    if name in ("MemTotal", "MemAvailable", "MemFree"):
                        # Each figure is in kilobytes.
                        found[name] = int(rest.split()[0]) * 1024
        except (OSError, ValueError, IndexError):
            return None
        if not found.get("MemTotal"):
            return None
        # MemAvailable counts the cache that can be given back; a very old kernel has only MemFree.
        free = found.get("MemAvailable", found.get("MemFree", 0))
        return {"total": found["MemTotal"], "used": found["MemTotal"] - free}
    if sys.platform == "win32":
        return _windows_memory()
    return None


def _windows_memory():
    """read_memory() on Windows: GlobalMemoryStatusEx."""
    try:
        import ctypes

        class Status(ctypes.Structure):
            # MEMORYSTATUSEX, as the system fills it.
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        status = Status()
        # The call checks the structure's size first.
        status.dwLength = ctypes.sizeof(Status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
    except (ImportError, AttributeError, OSError):
        return None
    return {"total": status.ullTotalPhys, "used": status.ullTotalPhys - status.ullAvailPhys}


def read_disk(path):
    """{"total", "used", "free"} in bytes of the disk `path` is on, or None when it cannot be read."""
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return {"total": usage.total, "used": usage.used, "free": usage.free}


def read_uptime():
    """Seconds since the machine started, or None where it is not known."""
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/uptime", encoding="ascii") as f:
                return int(float(f.read().split()[0]))
        except (OSError, ValueError, IndexError):
            return None
    if sys.platform == "win32":
        try:
            import ctypes
            # Milliseconds since the start, as a 64-bit count (the 32-bit one wraps after 49 days).
            ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
            return int(ctypes.windll.kernel32.GetTickCount64() // 1000)
        except (ImportError, AttributeError, OSError):
            return None
    return None


def read_load():
    """The load averages over 1, 5 and 15 minutes, or None where the system has none (Windows)."""
    try:
        return [round(v, 2) for v in os.getloadavg()]
    except (AttributeError, OSError):
        return None


def share(part):
    """A part of a whole ({"total", "used"}) as a percentage with one decimal, or None when it is not known."""
    if not part or not part.get("total"):
        return None
    return round(100.0 * part["used"] / part["total"], 1)


# ------------------------------------------------------------------------------------------------ the sampler

class Sampler:
    """The day's points of one data folder (one server), and the thread that makes them.

    cabinets: a function giving how many cabinets are connected now (the game server's own count), or None. The
    readers and the clock are its arguments so a test can give its own and call look() and keep() itself."""

    def __init__(self, data_dir, cabinets=None, clock=time.time, cpu=read_cpu, memory=read_memory, disk=read_disk):
        self.data_dir = data_dir
        self.cabinets = cabinets
        self.clock, self.cpu, self.memory, self.disk = clock, cpu, memory, disk
        # The day's points, oldest first: no more than a day's (KEEP) ever.
        self.points = collections.deque(maxlen=KEEP)
        # The processors' last reading, and the busy shares measured since the last point.
        self._last = None
        self._busy = []
        # The processors' share now (the last look's), None until two looks were made.
        self.now = None
        # When it started keeping points: the charts say so while they hold less than a day.
        self.since = clock()
        # Guards points, _busy and now: the thread writes them, the pages' threads read them.
        self._lock = threading.Lock()
        self._thread = None
        self._loaded = False

    @property
    def path(self):
        return os.path.join(self.data_dir, FILE)

    def load(self):
        """The points the file kept (from before a restart), those within the last day; once."""
        if self._loaded:
            return
        self._loaded = True
        try:
            with open(self.path, encoding="utf-8") as f:
                kept = json.load(f).get("points", [])
        except (OSError, ValueError, AttributeError):
            # No file yet, or one cut short: the day starts now.
            return
        now = self.clock()
        fresh = [p for p in kept if isinstance(p, dict) and isinstance(p.get("at"), (int, float))
                 and now - p["at"] < KEEP * POINT]
        with self._lock:
            self.points.extend(fresh)
            if self.points:
                # The charts' day began at the first point kept.
                self.since = min(self.since, self.points[0]["at"])

    def start(self):
        """The thread that looks and keeps points, once per sampler (a daemon: it ends with the server)."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="opendmt3-machine", daemon=True)
        self._thread.start()

    def _run(self):
        """The thread: the file's points read in (off the loop that started it), then a look every EVERY seconds and
        a point every POINT."""
        self.load()
        started = self.clock()
        # Until its data folder goes (a test's, removed): nothing makes a data folder again.
        while os.path.isdir(self.data_dir):
            self.look()
            if self.clock() - started >= POINT:
                self.keep()
                started = self.clock()
            time.sleep(EVERY)

    def look(self):
        """One look at the processors: how busy they were since the last look, in percent."""
        reading = self.cpu()
        if reading is None:
            return
        last, self._last = self._last, reading
        # The first look has nothing to compare with; a count that went back (a new machine?) neither.
        if last is None or reading[0] <= last[0]:
            return
        total = reading[0] - last[0]
        busy = max(0.0, min(100.0, 100.0 * (total - (reading[1] - last[1])) / total))
        with self._lock:
            self._busy.append(busy)
            self.now = busy

    def keep(self):
        """One point from the looks since the last one, kept and written with the day's others. Returns it."""
        with self._lock:
            busy, self._busy = self._busy, []
        memory, disk = self.memory(), self.disk(self.data_dir)
        try:
            cabinets = self.cabinets() if self.cabinets is not None else None
        except Exception:  # noqa: BLE001  (a count the game server cannot give is no reason to lose the point)
            cabinets = None
        point = {"at": int(self.clock()),
                 # The processors' average and peak over the point's looks (None: none was measured).
                 "cpu": round(sum(busy) / len(busy), 1) if busy else None,
                 "peak": round(max(busy), 1) if busy else None,
                 "memory": share(memory), "disk": share(disk), "cabinets": cabinets}
        with self._lock:
            self.points.append(point)
            kept = list(self.points)
        self._write(kept)
        return point

    def _write(self, points):
        """The day's points written whole, through a file beside it: a restart reads the old day or the new one."""
        part = self.path + ".part"
        if not os.path.isdir(self.data_dir):
            return
        try:
            with open(part, "w", encoding="utf-8") as f:
                json.dump({"points": points}, f, separators=(",", ":"))
            os.replace(part, self.path)
        except OSError:
            # A data folder that cannot be written (full, read-only) costs the charts their restart, nothing else.
            pass

    def figures(self):
        """The machine now and over the day, as numbers: processors (count), uptime (seconds), cpu (percent now),
        memory and disk ({"total", "used"}, the disk's "free" too), load (1, 5, 15 minutes), since (when the day's
        points began) and the points themselves, oldest first."""
        with self._lock:
            points = [dict(p) for p in self.points]
            now = self.now
        return {"cores": os.cpu_count() or 1, "uptime": read_uptime(),
                "cpu": None if now is None else round(now, 1),
                "memory": self.memory(), "disk": self.disk(self.data_dir), "load": read_load(),
                "since": int(self.since), "every": POINT, "points": points}

    def slots(self, end=None):
        """The last day as KEEP five-minute slots ending at `end` (now), oldest first, each the point kept in it or
        None: a chart's columns, gaps where the server was not running."""
        end = self.clock() if end is None else end
        with self._lock:
            points = list(self.points)
        out = [None] * KEEP
        for p in points:
            back = int((end - p["at"]) // POINT)
            if 0 <= back < KEEP:
                out[KEEP - 1 - back] = p
        return out


# One sampler a data folder, for the whole process: every Site of that folder (a test makes many) shares it.
_samplers = {}
_samplers_lock = threading.Lock()


def sampler(data_dir, cabinets=None):
    """The data folder's sampler, made the first time it is asked for (not started: Sampler.start)."""
    key = os.path.abspath(data_dir)
    with _samplers_lock:
        found = _samplers.get(key)
        if found is None:
            found = _samplers[key] = Sampler(data_dir, cabinets)
        elif cabinets is not None:
            # The newest game server's count: a launcher that started its server again has a new one.
            found.cabinets = cabinets
        return found
