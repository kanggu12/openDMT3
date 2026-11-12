"""Each chart's first place, kept in memory for the game's song select.

Every card login sends the server's first places (the song select's BEST RECORD and its DJ, server.send_firsts).
Asking the database each time held the game server's loop for 716 ms a login on a history of 300,000 plays and 2.7 s
on 1,000,000 (a window function over every play): with 64 cabinets a keep-alive waited 7.8 s at the median. The table
here answers at once. It is built from the database (records.first_places, 30-35 ms whatever the history's length),
follows each play the game server keeps (offer: one comparison), and is built again only when the database changed in
a way it did not follow:

- another connection committed something (the site disabled, renamed or deleted a player, reset plays, restored a
  backup; another program wrote): SQLite's PRAGMA data_version on the table's own connection says so;
- a write on the table's own connection that the game server did not hand over (follow): the connection's
  total_changes moved past what the table was told of (the tests write their plays this way).

The game server uses it from its database thread, the only user of its connection; every method takes the table's
lock all the same, so a reader on any other thread sees the table whole, before or after a change, never half of one.
"""

import collections
import threading

# One chart's first place: the play's mode, song and pattern, its score, its player's DJ name, when it was kept, its
# number (the earlier play wins a tie in score, then the lower number) and its player's account.
Place = collections.namedtuple("Place", "mode song pattern score dj_name played_at id account_id")


class FirstPlaces:
    """The first places of the database on `connection` (the game server's own), built and kept as above."""

    def __init__(self, records):
        # services.records.Records on the connection the table watches.
        self.records = records
        # Guards the four values below: the table, its sorted copy, the database state it matches, the builds' count.
        self._lock = threading.Lock()
        # (mode, song, pattern) -> Place.
        self._table = {}
        # Every Place by mode, song and pattern, made from the table when asked for after a change (None until then).
        self._sorted = None
        # (data_version, total_changes) of the connection when the table last matched the database; None: never built.
        self._stamp = None
        # How many times the table was built from the database (the tests and the measurements read it).
        self.builds = 0
        # Moves on with every change of the table (a build, a play that took a place): what is made of the table (the
        # messages a login sends: server.GameServer.first_places) is made again when it moves.
        self.version = 0

    def _state(self):
        """What changes when the database does: (another connection's commits, this connection's own writes)."""
        db = self.records.db
        # data_version changes when another connection commits; total_changes counts this connection's own rows.
        return db.execute("PRAGMA data_version").fetchone()[0], db.total_changes

    def places(self):
        """Every chart's first place (Place tuples) by mode, song and pattern, as records.first_places gives them now:
        built again first when the database changed in a way the table did not follow."""
        state = self._state()
        with self._lock:
            if self._stamp == state:
                if self._sorted is None:
                    # Sorted once per change of the table, then shared (a tuple: no caller can change it).
                    self._sorted = tuple(self._table[key] for key in sorted(self._table))
                return self._sorted
        # Built outside the lock (a few tens of milliseconds): a reader on another thread meanwhile gets the table
        # as it was, whole. The state was read before the build, so a change committed during it is seen next time.
        table = {(r["mode"], r["song"], r["pattern"]): Place(r["mode"], r["song"], r["pattern"], r["score"],
                                                              r["dj_name"], r["played_at"], r["id"], r["account_id"])
                 for r in self.records.first_places()}
        with self._lock:
            self._table, self._sorted, self._stamp = table, None, state
            self.builds += 1
            self.version += 1
            self._sorted = tuple(table[key] for key in sorted(table))
            return self._sorted

    def top(self, mode, song, pattern):
        """The chart's first place as the table has it (a Place, or None), without looking at the database."""
        with self._lock:
            return self._table.get((mode, song, pattern))

    def offer(self, place):
        """A play the game server has just kept (a Place): the chart's first place from now on when it beats the one
        there by score (an equal score never does: the earlier play keeps the place, as the database orders them),
        or when the chart had none. True when it took the place."""
        key = (place.mode, place.song, place.pattern)
        with self._lock:
            now = self._table.get(key)
            # The order first places are picked by: the higher score, then the earlier play, then the lower number.
            if now is not None and (-now.score, now.played_at, now.id) <= (-place.score, place.played_at, place.id):
                return False
            self._table[key] = place
            # The sorted copy is made again when next asked for.
            self._sorted = None
            self.version += 1
            return True

    def follow(self, before):
        """The game server's own writes since `before` (the connection's total_changes then) are ones the table
        follows already (a play it was offered, a session, a cabinet): the table still matches the database. Nothing
        moves when the table was out of date before them (a write it was not told of): it is built at the next look."""
        with self._lock:
            if self._stamp is not None and self._stamp[1] == before:
                self._stamp = (self._stamp[0], self.records.db.total_changes)
