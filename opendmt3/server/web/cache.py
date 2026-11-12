"""The lists the site makes from everyone's plays (rankings, songs, a song's boards, the totals behind a DJ's places, a
DJ's page, Home's newest plays and records), kept until what they are made of changes.

On a history of 300,000 plays each of them took 80 to 400 ms of the database's time a request (1,000,000: up to 1.5 s),
and 20 visitors at once waited 2.5 to 9 seconds for a page. A list is the same for every visitor until a play is
kept or a player changes, so it is made once and handed to everyone until then:

- Each list is kept under its name and arguments together with the database's state when it was made: the newest
  play's number (SELECT MAX(id) FROM plays: one look at the end of the table's own index), which every play the game
  server keeps moves on, and records.changes(), which a disabled, enabled, renamed or deleted player, a new DJ card,
  plays reset and a restore move on (in this process). A request asks with the state now, so it never gets a list
  older than the plays it can see. A list made of one player's plays alone (a DJ's page) gives its own newest play
  instead: it stays while others play.
- One list a name and arguments: a list made in a newer state takes the place of the older one, which no request can
  ask for again (on a server where a play is kept every second, the old ones would otherwise fill the table).
- A list older than KEEP_SECONDS is made again whatever the state says: a change made by another program while the
  server runs (the command line's --restore) shows within that time.
- A list is made once for everyone asking at the same moment: the first request makes it, the others wait for it (a
  burst of 20 visitors after a new play does the work once, not 20 times). A list that fails to be made is not kept,
  and each of those waiting tries again.
- What is kept is shared by every request, so it is made read-only (files.frozen: a page that changes a list must
  change a copy, dict() or list() of it).

The site's requests run on worker threads: the table is guarded by one lock, held only to look up and store, never
while a list is made.
"""

import collections
import threading
import time

from opendmt3.server.services import files, records

# Lists kept at most: a few per mode and ranking, one per song's boards and per DJ looked at lately. The one used
# longest ago goes first.
MOST = 512
# Seconds a list is handed out for at most, whatever the database's state says (see above).
KEEP_SECONDS = 300.0


def _order(state):
    """A state's place in time (state()): the change count first (it only goes up), then the newest play's number (it
    only goes up between two changes)."""
    return state[1], state[0] if state[0] is not None else -1


class _Entry:
    """One list: its value once made (or the failure that left it unmade), when it was made, and the event the
    requests waiting for it wait on."""

    __slots__ = ("value", "made", "ready", "failed")

    def __init__(self):
        self.value = None
        self.made = None
        self.ready = threading.Event()
        self.failed = False


class Lists:
    """The kept lists of one site (one database)."""

    def __init__(self, most=MOST, keep=KEEP_SECONDS, clock=time.monotonic):
        self.most = most
        self.keep = keep
        self.clock = clock
        # (name and arguments, state) -> _Entry; the one used last at the end.
        self._entries = collections.OrderedDict()
        # name and arguments -> the (name and arguments, state) kept for them now: one list a name, the newest.
        self._current = {}
        self._lock = threading.Lock()
        # How many lists were made and how many were handed out as kept (the tests and the measurements read them).
        self.made = 0
        self.kept = 0

    @staticmethod
    def state(connection, newest=None):
        """What the lists of this database are made of, now: (the newest play's number, the process's change count).
        `newest`: the newest play a list is made of when it is not everyone's (a query and its arguments)."""
        if newest is None:
            newest = ("SELECT MAX(id) FROM plays", ())
        row = connection.execute(*newest).fetchone()
        # The play's number (None before any play), and the count of changes beside the plays.
        return (row[0] if row is not None else None), records.changes()

    def get(self, connection, key, make, newest=None):
        """The list `key` (a tuple: its name and arguments) of the database on `connection`, as make() makes it from
        the database now: the kept one when it was made in the same state and not too long ago, else made (once for
        every request asking at the same moment) and kept, read-only. `newest`: the query (and its arguments) of the
        newest play the list is made of, when it is made of some plays only (state())."""
        full = (key, self.state(connection, newest))
        while True:
            with self._lock:
                entry = self._entries.get(full)
                if entry is not None and entry.ready.is_set() and not entry.failed \
                        and self.clock() - entry.made <= self.keep:
                    # Made in the same state, not too long ago: handed out as it is.
                    self._entries.move_to_end(full)
                    self.kept += 1
                    return entry.value
                if entry is None or entry.ready.is_set():
                    # Nobody is making it: this request does (a stale or failed one is replaced).
                    entry = self._entries[full] = _Entry()
                    self._entries.move_to_end(full)
                    mine = True
                else:
                    # Another request is making it right now: wait for that one.
                    mine = False
            if not mine:
                entry.ready.wait()
                # Made (handed out above at the next turn), or failed (this request makes it then).
                continue
            try:
                value = files.frozen(make())
                # The state again, now that the list is made: the same as before means nothing changed while it was
                # made, so the database is in that state now, whatever was kept before (another program may have put
                # an older database back, the newest play's number going down with it).
                now = self.state(connection, newest)
            except BaseException:
                with self._lock:
                    entry.failed = True
                    # Not kept: the next request makes it again.
                    if self._entries.get(full) is entry:
                        del self._entries[full]
                entry.ready.set()
                raise
            with self._lock:
                entry.value, entry.made = value, self.clock()
                self.made += 1
                kept = self._current.get(key)
                if kept is not None and kept != full and now != full[1] and _order(kept[1]) > _order(full[1]):
                    # A request that read the database before the last change made this one late (the state moved
                    # while it was made): the newer list stays, and this one goes to its request only.
                    if self._entries.get(full) is entry:
                        del self._entries[full]
                    entry.ready.set()
                    return value
                if kept is not None and kept != full:
                    # The same list in an older state: no request asks for it again.
                    self._entries.pop(kept, None)
                self._current[key] = full
                while len(self._entries) > self.most:
                    # The list used longest ago goes (a list being made is rarely the oldest: it was just added).
                    gone, _ = self._entries.popitem(last=False)
                    if self._current.get(gone[0]) == gone:
                        del self._current[gone[0]]
            entry.ready.set()
            return value

    def clear(self):
        """Forget every list (a restore in this process counts as a change already; the tests use this)."""
        with self._lock:
            self._entries.clear()
            self._current.clear()
