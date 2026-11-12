"""Counting what one sender does over a stretch of time, for the limits the game server and the site keep.

A sender is the address a connection or a request comes from. IPv6 gives one home or one server a whole /64 of
addresses, so those count as one sender; an IPv4 address written the IPv6 way (::ffff:192.0.2.1, what a server
listening on :: sees) is that IPv4 address. Tables of senders forget the one heard from longest ago first, so a
flood of new addresses cannot grow them past their size.

The site counts on the event loop and on its worker threads: each table changes under its own lock, so two counts at
the same moment never lose one or leave a key half forgotten.
"""

import collections
import ipaddress
import threading
import time


def sender(host):
    """The key one sender's counts go under: an IPv4 address as it is, an IPv6 address as its /64, anything that is
    not an address (a test client's name) as it came."""
    try:
        # Brackets come with IPv6 addresses written in a URL; the scope (%eth0) is not part of who sends.
        ip = ipaddress.ip_address(str(host).strip("[]").split("%", 1)[0])
    except ValueError:
        return str(host)
    if ip.version == 6 and ip.ipv4_mapped is not None:
        # An IPv4 visitor of a server listening on both: the same sender as on an IPv4 server.
        return str(ip.ipv4_mapped)
    if ip.version == 6:
        # The /64 a home or a server is given: one sender, however many of its addresses it uses.
        return str(ipaddress.ip_network((ip, 64), strict=False))
    return str(ip)


class Recent:
    """When each key's events happened, over the last `window` seconds, for at most `kept()` keys.

    `table` maps a key to the times of its events (oldest first); the key heard from last is at its end, so the one
    heard from longest ago is dropped first when there are too many. Times come from `clock` (wall-clock seconds by
    default, which the tests move by hand).
    """

    def __init__(self, window, kept, clock=time.time):
        self.window = window            # seconds an event counts for
        self.kept = kept                # a function: how many keys the table holds at most (read at each event)
        self.clock = clock
        self.table = collections.OrderedDict()
        # Every read and change of the table, one at a time (re-entrant: wait() counts first).
        self.lock = threading.RLock()

    def count(self, key):
        """The key's events within the window; older ones are forgotten here, and a key left with none goes."""
        with self.lock:
            times = self.table.get(key)
            if not times:
                return 0
            now = self.clock()
            # Oldest first: drop from the front until the first one still counts.
            while times and now - times[0] > self.window:
                times.popleft()
            if not times:
                # Nothing recent: the key is forgotten, so the table holds only keys heard from lately.
                del self.table[key]
                return 0
            return len(times)

    def wait(self, key, most):
        """Seconds until the key has fewer than `most` events within the window (0 when it has already): how long a
        sender held back by a limit of `most` waits, for an answer's Retry-After."""
        with self.lock:
            n = self.count(key)
            if n < most:
                return 0
            # Oldest first: once the n - most + 1 oldest events have left the window, fewer than `most` are left, and
            # the last of those to leave is the one at n - most. An event leaves once it is older than the window.
            return max(0, self.table[key][n - most] + self.window - self.clock())

    def add(self, key):
        """One event for the key, now; returns a mark that take_back() uses to undo it."""
        with self.lock:
            at = self.clock()
            times = self.table.get(key)
            if times is None:
                times = self.table[key] = collections.deque()
            else:
                # Heard from now: the last to be dropped.
                self.table.move_to_end(key)
            times.append(at)
            while len(self.table) > self.kept():
                # The key heard from longest ago goes first: O(1), whatever the table's size.
                self.table.popitem(last=False)
            return key, at

    def take_back(self, mark):
        """Undo one add() (a sign-in counted as wrong before its password was checked, which turned out right)."""
        key, at = mark
        with self.lock:
            times = self.table.get(key)
            if not times:
                return
            try:
                times.remove(at)
            except ValueError:
                # Already forgotten (too old, or the key was dropped and came back): nothing to undo.
                return
            if not times:
                del self.table[key]


class Spent:
    """How many seconds of work each key spent over the last `window` seconds, for at most `kept()` keys: the site's
    fair shares (web/app.py, Shares). As Recent, the key heard from longest ago is forgotten first, and every read
    and change takes the table's lock (counted on the loop, read by tests on other threads)."""

    def __init__(self, window, kept, clock=time.monotonic):
        self.window = window            # seconds a cost counts for
        self.kept = kept                # a function: how many keys the table holds at most
        self.clock = clock
        # key -> [deque of (when, seconds), their sum]; the key heard from last at the end.
        self.table = collections.OrderedDict()
        self.lock = threading.Lock()

    def _trim(self, key, now):
        """The key's entry with the costs older than the window dropped (the key itself when none is left), or None."""
        entry = self.table.get(key)
        if entry is None:
            return None
        costs = entry[0]
        while costs and now - costs[0][0] > self.window:
            # Oldest first: what left the window no longer counts.
            entry[1] -= costs.popleft()[1]
        if not costs:
            # Nothing recent: the key is forgotten.
            del self.table[key]
            return None
        return entry

    def spent(self, key):
        """The key's seconds within the window."""
        with self.lock:
            entry = self._trim(key, self.clock())
            # A sum of floats taken apart again can end a hair below zero: never less than nothing.
            return max(0.0, entry[1]) if entry else 0.0

    def wait(self, key, most):
        """Seconds until the key's spending is below `most` (0 when it is): what a 429's Retry-After says."""
        with self.lock:
            now = self.clock()
            entry = self._trim(key, now)
            if entry is None or entry[1] < most:
                return 0.0
            # The oldest costs leave first; once enough of them have left, the rest is below `most`.
            left = entry[1]
            for at, cost in entry[0]:
                left -= cost
                if left < most:
                    return max(0.0, at + self.window - now)
            return self.window

    def add(self, key, seconds):
        """`seconds` of work spent by the key, now."""
        with self.lock:
            now = self.clock()
            entry = self._trim(key, now)
            if entry is None:
                entry = self.table[key] = [collections.deque(), 0.0]
            else:
                # Heard from now: the last to be forgotten.
                self.table.move_to_end(key)
            entry[0].append((now, seconds))
            entry[1] += seconds
            while len(self.table) > self.kept():
                # The key heard from longest ago goes first.
                self.table.popitem(last=False)
