"""The game server: accepts cabinets on TCP 4725 and hands each decrypted message to its handler.

Handlers are registered by header with @handles. Until the handshake has let a client online, only its answer
(0x02) is read. A message with no handler yet is named in the log once per connection, and logged with its first
bytes at the debug level (--verbose), so a session with the real client shows what to build next; otherwise it is
ignored: the client keeps going without an answer for the messages it only reports.

The last MESSAGES_KEPT messages received are also kept in memory for the admin's log page: the header, the
size, and only for messages without a handler their first bytes (handled ones carry card numbers, and so do the
login messages without a handler yet: messages.CARRIES_SECRETS).

One address (an IPv6 /64, services/limits.py) holds at most PER_ADDRESS links and sends at most
connection.BYTES_PER_MINUTE a minute over all of them, a budget a new link does not refill. What is refused (links,
cards, results) is logged once per address a minute, with how many there were (Refusals).

The event loop never runs a query: every look into the database and every write runs on the game server's own
database thread (GameServer.database), one at a time and in the order asked, while the loop goes on answering every
cabinet's keep-alives. A card login's first places come from memory (services/firsts.py). A write that finds the
database held by another connection waits for it, and a write transaction that still finds it held is tried again
until it goes through (write): a player's results are never lost to a busy file, and no cabinet waits meanwhile.
"""

import asyncio
import collections
import concurrent.futures
import contextlib
import functools
import logging
import sqlite3
import threading
import time

from opendmt3.server import connection, crypto, db, messages
from opendmt3.server.services import accounts as accounts_service
from opendmt3.server.services import cards, catalog, firsts, limits, maintenance
from opendmt3.server.services import records as records_service

log = logging.getLogger("opendmt3.server")

DEFAULT_PORT = 4725         # the port in the game's networksetting.ini
MAX_CONNECTIONS = 64        # cabinets at once; a small server has a few, a flood gets no more than this
# Links from one address at once. Cabinets behind one router (a game centre, a house) share its address; a server
# has far fewer than this, and one address can no longer take every place.
PER_ADDRESS = 16
# Cleared stages kept from one card login. The game sends a credit's results once, at its end, in one 0x6E with
# room for three stages; how many stages a credit holds is not known from the game, so this is a cap with
# room to spare, not a value of the game. Normal play never comes near it; forged results stop at it.
STAGES_PER_LOGIN = 8
LOGGED_BYTES = 64           # how much of an unhandled message the debug log shows
MESSAGES_KEPT = 500         # received messages the admin's log page can show (older ones drop off)
KEPT_BYTES = 32             # how much of an unhandled message that page shows
MINUTE = 60.0               # the stretch the byte budget and the refusal log count over
SENDERS_KEPT = 4096         # addresses the byte budgets and the refusal log remember at most
SWEEP_EVERY = 15.0          # seconds between tidying them (a minute that ended is told and forgotten)
# How long a write transaction of the game server is tried again while the database stays held past the busy timeout
# (db.BUSY_SECONDS each try), before it gives up and the failure is logged: far past any restore or backup.
WRITE_PATIENCE = 600.0
# A pause between two tries, so a held database is not asked again at once.
WRITE_RETRY_PAUSE = 0.2
# The longest paused() waits for the game server's threads to be free (a write waiting for a database another program
# holds), before it gives up with an error rather than run its block unheld.
PAUSE_MOST = 300.0
# The longest a hold lasts once had, counted from when the block began, whatever the block does (a restore or a reset
# of the largest database takes minutes): past it the game server goes on, and says so.
HOLD_MOST = 3600.0
# Threads that read for the game server beside its one writer (a card login's records and DJ card), each on a
# connection of its own: with the write-ahead log a read never waits for the writer, and a long history's records (45
# ms for the busiest player of 300,000 plays) no longer hold up every other cabinet's writes and logins.
READ_THREADS = 2

HANDLERS = {}


def _busy(error):
    """True for SQLite's "the database is held by another connection" (SQLITE_BUSY, "database is locked")."""
    text = str(error).lower()
    return isinstance(error, sqlite3.OperationalError) and ("locked" in text or "busy" in text)


def handles(header):
    """Register a function(server, connection, message) for one client header."""
    def register(fn):
        if header in HANDLERS:
            raise ValueError("two handlers for 0x%02x" % header)
        if header not in messages.TO_SERVER and header not in messages.VARIABLE_TO_SERVER:
            raise ValueError("0x%02x is not a message the client sends" % header)
        HANDLERS[header] = fn
        return fn
    return register


class Refusals:
    """What was refused, logged once per address a minute: the first refusal at once (with its detail), then at the
    minute's end how many more came and why, so a flood of refusals writes a line a minute, not a line each."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        # address -> [start of its minute, how many more of each reason]; the oldest minute first.
        self._open = collections.OrderedDict()

    def note(self, who, reason, detail=""):
        """One refusal of `who` (an address, limits.sender) for `reason`; `detail` goes only in the first line."""
        now = self.clock()
        self.flush(now)
        counted = self._open.get(who)
        if counted is not None:
            # Already told this minute: counted, and told at the minute's end.
            counted[1][reason] += 1
            return
        log.warning("%s refused: %s%s", who, reason, " (%s)" % detail if detail else "")
        self._open[who] = [now, collections.Counter()]
        if len(self._open) > SENDERS_KEPT:
            # Too many addresses at once: the oldest minute is told now instead of kept.
            oldest, (_, reasons) = self._open.popitem(last=False)
            self._tell(oldest, reasons)

    def flush(self, now=None, everything=False):
        """Tell the minutes that ended (all of them with `everything`, when the server stops)."""
        now = self.clock() if now is None else now
        while self._open:
            who, (start, reasons) = next(iter(self._open.items()))
            if not everything and now - start < MINUTE:
                # Oldest first: the rest are younger still.
                break
            del self._open[who]
            self._tell(who, reasons)
            if reasons and not everything:
                # Still coming: the next minute's are counted too, and told at its end (one line a minute).
                self._open[who] = [now, collections.Counter()]

    @staticmethod
    def _tell(who, reasons):
        if reasons:
            log.warning("%s refused %d more times in a minute: %s", who, sum(reasons.values()),
                        ", ".join("%s (%d)" % (reason, n) for reason, n in reasons.most_common()))


class GameServer:
    """Listens for cabinets; keeps the live connections for the pages that list them."""

    def __init__(self, host="127.0.0.1", port=DEFAULT_PORT, rng=None, accounts=None, records=None, activity=None,
                 webhook=None, data=None):
        self.host, self.port = host, port
        # The data folder: the song list and the card tables read from the game, and whether the admin put the
        # server in maintenance (services/maintenance.py).
        self.data = data
        self.rng = rng                   # tests pass a seeded one; otherwise the system's
        self.accounts = accounts         # services.accounts.Accounts; without it every login is refused
        self.records = records           # services.records.Records; without it results are only logged
        self.activity = activity         # services.activity.Activity; without it cabinets and sessions go unrecorded
        self.webhook = webhook           # services.notify.Webhook: told when a first place changes hands
        self.connections = set()
        self.messages = collections.deque(maxlen=MESSAGES_KEPT)
        # The site reads those two from its worker threads while the loop changes them: each change and each copy
        # (live(), received()) takes this lock, so a reader never meets a table changing under it.
        self.lock = threading.Lock()
        self.started = time.time()
        self.links = collections.Counter()      # address -> links open from it now
        self.budgets = {}                        # address -> [start of its minute, bytes received in it]
        self.refusals = Refusals()
        # Each chart's first place, in memory (services/firsts.py), made at start() when the server keeps records.
        self.firsts = None
        # The first places as the messages a login sends (first_places): (the table's version, the song list, the
        # messages), the database thread's own.
        self._first_messages = None
        # The one thread every write of the game server runs on, in the order asked (database()), made at start() and
        # ended at close().
        self._database = None
        # The threads its reads run on beside it (read()), each with its own connection to the database file
        # (_reader), made at start() for a database in a file and ended at close(); None: reads go to the writer.
        self._reading = None
        self._read_path = None
        self._readers = threading.local()
        # Every reading connection opened, closed at close() (each thread opens its own, so a list of them all).
        self._read_connections = []
        self._read_lock = threading.Lock()
        # The tasks serving the links now: close() waits for them to end (their sessions' ends are written) before
        # it ends the database's thread.
        self._serving = set()
        self._server = None
        self._sweeper = None

    # ------------------------------------------------------------------------------ the database's thread

    async def database(self, fn, *args, **kwargs):
        """fn(*args, **kwargs) on the game server's database thread, its result (or its exception) back here: the
        loop goes on with every other cabinet while it runs or waits for a busy database. One at a time, in the order
        asked, so the connection the services share is never used by two threads at once."""
        if self._database is None:
            # Before start() or after close() (a test's direct call): on this thread, as before there was one.
            return fn(*args, **kwargs)
        return await asyncio.get_running_loop().run_in_executor(self._database, functools.partial(fn, *args, **kwargs))

    @contextlib.contextmanager
    def paused(self):
        """Hold the game server's database thread for as long as the `with` block runs (from any thread but the loop:
        a site's request putting a backup back). The thread first finishes what it was doing; what cabinets ask of it
        meanwhile waits and runs after, in order (the loop answers their keep-alives all the while). Held for
        PAUSE_MOST seconds at most."""
        pools = [(pool, 1) for pool in (self._database,) if pool is not None]
        if self._reading is not None:
            # The reading threads too, every one of them: no login reads the database while it is put back.
            pools.append((self._reading, READ_THREADS))
        if not pools:
            # No thread (not started, or closed): nothing to hold.
            yield
            return
        release = threading.Event()
        holding = threading.Semaphore(0)
        # When the block began (every thread held), for the holds' own limit.
        began = [None]

        def hold():
            # Runs once a thread is free: it waits here until the block ends, HOLD_MOST from the block's beginning at
            # the very most (said, for a block that never ends).
            holding.release()
            while not release.wait(1.0):
                if began[0] is not None and time.monotonic() - began[0] > HOLD_MOST:
                    log.error("the game server was held for %d s by a restore or a reset: it goes on", HOLD_MOST)
                    return
        held = 0
        try:
            for pool, count in pools:
                for _ in range(count):
                    pool.submit(hold)
                    held += 1
        except RuntimeError:
            # The server is closing (its threads take nothing new, and what is queued still runs): the block would run
            # beside it unheld, so it does not run.
            release.set()
            raise RuntimeError("the game server is closing") from None
        try:
            # Every thread asked for is free and held from here on; one that is not within PAUSE_MOST (a write waiting
            # that long for a database another program holds) is an error, never a block run unheld.
            deadline = time.monotonic() + PAUSE_MOST
            for _ in range(held):
                if not holding.acquire(timeout=max(0.0, deadline - time.monotonic())):
                    raise TimeoutError("the game server's database work did not stop within %d s" % PAUSE_MOST)
            began[0] = time.monotonic()
            yield
        finally:
            release.set()

    def _file(self):
        """The file the game server's database is in, or None (no database, or one in memory: no other connection
        reaches it)."""
        shared = self._db()
        if shared is None:
            return None
        for _, name, path in shared.execute("PRAGMA database_list").fetchall():
            if name == "main":
                return path or None
        return None

    def _db(self):
        """The connection the services share (the records', else the accounts'), or None without either."""
        for service in (self.records, self.accounts, self.activity):
            if service is not None:
                return service.db
        return None

    def write(self, work):
        """work() inside one write transaction on the database thread: all of it is kept or none. The write lock is
        taken first (BEGIN IMMEDIATE), waiting up to db.BUSY_SECONDS for another connection's write; while the
        database stays held, the whole transaction is tried again (nothing of a failed try was kept), for up to
        WRITE_PATIENCE seconds. The first places follow what it wrote (services/firsts.py)."""
        db = self._db()
        started, told = time.monotonic(), False
        while True:
            # What the connection had written before this transaction: the first places follow from there.
            before = db.total_changes
            try:
                db.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as e:
                # Anything but a held database, or held for too long: the caller's failure (logged there).
                if not _busy(e) or time.monotonic() - started >= WRITE_PATIENCE:
                    raise
                if not told:
                    # Said once per write: the database is held by someone else (a restore, another program).
                    log.warning("the database is busy; the game server's write waits for it")
                    told = True
                time.sleep(WRITE_RETRY_PAUSE)
                continue
            try:
                result = work()
                db.execute("COMMIT")
            except BaseException:
                # Nothing of it is kept: a later try (or the caller) starts from where the database was.
                db.execute("ROLLBACK")
                raise
            if self.firsts is not None:
                # The game server's own write: the first places followed its plays already (offer).
                self.firsts.follow(before)
            return result

    # ------------------------------------------------------------------------- what the site reads of it

    def live(self):
        """The links open now, as the site lists them (from any thread): [{"address", "online", "player" (the login ID
        logged in, or None), "version"}], by address. Each value is the link's as the loop last set it."""
        with self.lock:
            links = list(self.connections)
        return sorted(({"address": c.address, "online": c.online, "player": c.player,
                        "version": c.answer.version if c.answer else ""} for c in links), key=lambda c: c["address"])

    def received(self):
        """The messages kept for the admin's log (from any thread), oldest first: a copy."""
        with self.lock:
            return list(self.messages)

    # ------------------------------------------------------------------------------- what a login sends

    def card(self, row, records=None):
        """The DJ card's fields for an account's 0x65 (services/cards.py): its experience from the stages it
        cleared (read through `records`: the game server's own, or a reading thread's), and its icon, title and
        comment, as far as the game's tables (read into the data folder) have them."""
        tables = cards.load(self.data) if self.data else {}
        songs = catalog.load(self.data) if self.data else {}
        return cards.of(row, tables, songs, records if records is not None else self.records)

    def songs(self):
        """The server's song list ({} without one: then every song number is taken as it comes)."""
        return catalog.load(self.data) if self.data else {}

    def my_records(self, row, songs, records=None):
        """The messages of the player's own best on each chart they cleared, for the song select's MY RECORD (before
        0x65), read through `records` (the game server's own, or a reading thread's): emptied first, the last player's
        records with it (the game would otherwise show them to this one)."""
        out = [messages.clear_my_records()]
        records = records if records is not None else self.records
        if records is None:
            return out
        for best in records.bests(row["id"]):
            # Only what the game keeps lists for: STAR and POP, its four patterns, songs it has.
            if best["mode"] in messages.SONG_SELECT_MODES and _charted(songs, best):
                out.append(messages.my_record(best["mode"], best["song"], best["pattern"], best["score"]))
        return out

    def first_places(self, songs):
        """The messages of each chart's first place on this server, for the song select's BEST RECORD and its DJ,
        from memory (services/firsts.py: built again first only when the database changed in a way it did not
        follow). None without records."""
        if self.records is None:
            return None
        if self.firsts is None:
            # A server that was never started (a test's own): the table made for it on first use.
            self.firsts = firsts.FirstPlaces(self.records)
        places = self.firsts.places()
        made = self._first_messages
        if made is not None and made[0] == self.firsts.version and (made[1] is songs or made[1] == songs):
            # The same table and the same song list as the last login: the same messages (made once, 35 ms on a long
            # history). The song list's object stays the same while its file does; without a file each look gives an
            # empty one of its own, equal to the last.
            return made[2]
        out = [messages.clear_bests()]
        for first in places:
            # The game indexes its lists by mode without a check: only its own modes and patterns go out, and with a
            # song list only its songs (a first place on a song nobody has would go to every cabinet).
            if first.mode in messages.BEST_MODES and _charted(songs, first._asdict()):
                out.append(messages.best_record(first.mode, first.song, first.pattern, first.score, first.dj_name))
        # Kept by the database thread, the only one that makes them; a tuple, so no login changes another's.
        self._first_messages = (self.firsts.version, songs, tuple(out))
        return self._first_messages[2]

    def card_login(self, card, host, last_session):
        """A card login's whole look into the database, on the database thread: the account whose card it is, and for
        an enabled one everything its answer sends (its records, its DJ card, the server's first places) and its new
        play session on the cabinet `host` (ending the cabinet's last one, `last_session`). Returns (the account's
        row or None, None) for a card that does not log in, else (row, {"records", "card", "firsts", "session"})."""
        row = self.accounts.by_card(card) if self.accounts is not None else None
        if row is None or row["disabled"]:
            return row, None
        songs = self.songs()
        answer = {"records": self.my_records(row, songs), "card": self.card(row),
                  "firsts": self.first_places(songs), "session": None}
        if self.activity is not None:
            def session():
                # Another card on the same cabinet ends the last player's session; the new one starts with it.
                self.activity.end(last_session)
                return self.activity.start(host, row["id"])
            answer["session"] = self.write(session)
        return row, answer

    async def read(self, fn, *args):
        """fn(accounts, records, *args) on a reading thread, with that thread's own services on its own connection
        (_reader), its result (or its exception) back here; on the database's thread with the game server's own
        services when there are no reading threads (before start(), or a database not in a file)."""
        if self._reading is None:
            return await self.database(fn, self.accounts, self.records, *args)
        return await asyncio.get_running_loop().run_in_executor(self._reading,
                                                                functools.partial(self._on_reader, fn, *args))

    def _on_reader(self, fn, *args):
        """read()'s work on a reading thread: fn with the thread's own services."""
        accounts, records = self._reader()
        return fn(accounts, records, *args)

    def _reader(self):
        """This reading thread's own (accounts, records) on a connection of its own, opened at its first read and
        closed at close(). Each read is its own transaction (autocommit): it sees every write committed before it."""
        mine = getattr(self._readers, "services", None)
        if mine is None:
            own = db.connect(self._read_path)
            with self._read_lock:
                self._read_connections.append(own)
            mine = self._readers.services = (
                accounts_service.Accounts(own) if self.accounts is not None else None,
                records_service.Records(own) if self.records is not None else None)
        return mine

    def login_reads(self, accounts, records, card):
        """A card login's reads, on a reading thread (read()): the account whose card it is and, for an enabled one,
        what its answer sends from the database but the first places: its records and its DJ card. (row, None) for a
        card that does not log in."""
        # The count of changes to players and plays first (a reset, a restore, a player renamed or disabled): the
        # writer finds it moved when one came between these reads and its own look (login_writes).
        changes = records_service.changes()
        row = accounts.by_card(card) if accounts is not None else None
        if row is None or row["disabled"]:
            return row, None
        songs = self.songs()
        return row, {"records": self.my_records(row, songs, records), "card": self.card(row, records),
                     "changes": changes}

    def login_writes(self, card, read, changes, host, last_session):
        """The rest of a card login, on the database's thread: the account looked up again on the writer's own
        connection, then the first places (from memory) and the new play session. None when the account is not the
        one the reads found (deleted, disabled or given another card since, or put back from a backup), or when
        players or plays changed since the reads (`changes`: a reset or a restore held the writer between them): the
        caller logs in again on this thread alone (card_login), so no answer mixes before and after."""
        row = self.accounts.by_card(card)
        if row is None or row["disabled"] or row["id"] != read["id"] or records_service.changes() != changes:
            return None
        answer = {"firsts": self.first_places(self.songs()), "session": None}
        if self.activity is not None:
            def session():
                # Another card on the same cabinet ends the last player's session; the new one starts with it.
                self.activity.end(last_session)
                return self.activity.start(host, row["id"])
            answer["session"] = self.write(session)
        return row, answer

    async def login(self, card, host, last_session):
        """A card login's look into the database: its reads on a reading thread beside the writer (login_reads),
        the rest on the database's thread (login_writes). (row or None, None) for a card that does not log in, else
        (row, {"records", "card", "firsts", "session"}), as card_login gives them."""
        if self.accounts is None:
            return None, None
        row, read = await self.read(self.login_reads, card)
        if read is None:
            return row, None
        changes = read.pop("changes")
        written = await self.database(self.login_writes, card, row, changes, host, last_session)
        if written is None:
            # The account, or the players and plays, changed between the reads and the writer's look (rare): all of
            # it again, on the writer.
            return await self.database(self.card_login, card, host, last_session)
        row, rest = written
        return row, dict(read, **rest)

    def keep_results(self, player, address, session, mode, records, kept_before):
        """A 0x6E's stages, on the database thread: the account logged in (`player`, its login ID) checked again, then
        each stage the game can have sent kept for it, all in one write transaction with the session's end (an account
        the site disables meanwhile cannot slip in between the check and the plays). Returns (row, what became of each
        stage: (record, why it was not kept or None, the first place it took from another player or None)); row None
        (a guest) or disabled: (row, None), nothing kept."""
        songs = self.songs()

        def keep():
            row = self.accounts.by_login(player) if self.accounts is not None else None
            if row is None or row["disabled"]:
                return row, None
            outcome, kept = [], kept_before
            for record in records:
                why = _why_not_kept(mode, record, songs)
                if why is None and kept >= STAGES_PER_LOGIN:
                    why = "more than %d stages on one card login" % STAGES_PER_LOGIN
                if why is not None:
                    outcome.append((record, why, None))
                    continue
                kept += 1
                taken = None
                if self.records is not None:
                    # The chart's first place before this play, for the players' chat (only when it is told).
                    before = self.records.top(mode, record["song"], record["pattern"]) if self.webhook else None
                    number, moment = self.records.add(row["id"], address, mode, record,
                                                      session_id=self._session_kept(session))
                    if self.firsts is not None:
                        # The first places follow the play at once: the next login sends it without a look.
                        self.firsts.offer(firsts.Place(mode, record["song"], record["pattern"], record["score"],
                                                       row["dj_name"], moment, number, row["id"]))
                    if before is not None and before[0] != row["id"] and record["score"] > before[2]:
                        # First place taken from someone else.
                        taken = before
                outcome.append((record, None, taken))
            if self.activity is not None and session is not None:
                # The results come when the player's game is over: the session ends here, not when the cabinet (left
                # on for days) finally disconnects. The next card starts the next one.
                self.activity.end(session)
            return row, outcome
        return self.write(keep)

    def _session_kept(self, session):
        """`session` when the database still has it, else None: a restore can take the session a cabinet is in back
        out of the database, and a play pointing at a session that is not there would be refused."""
        if session is None:
            return None
        found = self._db().execute("SELECT 1 FROM sessions WHERE id = ?", (session,)).fetchone()
        return session if found else None

    def spend(self, who, size):
        """Count `size` bytes received from `who` this minute; False once its minute's bytes pass
        connection.BYTES_PER_MINUTE. Every link from the address shares the count, and a new link keeps it."""
        now = time.monotonic()
        budget = self.budgets.get(who)
        if budget is None or now - budget[0] >= MINUTE:
            if budget is None and len(self.budgets) >= SENDERS_KEPT:
                # Many addresses at once: the minutes that ended go first.
                self._sweep_budgets(now)
            budget = self.budgets[who] = [now, 0]
        budget[1] += size
        return budget[1] <= connection.BYTES_PER_MINUTE

    def _sweep_budgets(self, now):
        """Forget the budgets whose minute ended (an address heard from again starts a new one)."""
        for who in [w for w, (start, _) in self.budgets.items() if now - start >= MINUTE]:
            del self.budgets[who]

    async def _sweep(self):
        """Every SWEEP_EVERY seconds: the refusal minutes that ended are told, the budgets that ended forgotten."""
        while True:
            await asyncio.sleep(SWEEP_EVERY)
            self.refusals.flush()
            self._sweep_budgets(time.monotonic())

    async def start(self):
        # The database's thread: every write of the game server from here on, in order (database()).
        self._database = concurrent.futures.ThreadPoolExecutor(1, thread_name_prefix="opendmt3-game-db")
        self._read_path = await self.database(self._file)
        if self._read_path is not None and READ_THREADS > 0:
            # Its reads beside it, each thread on its own connection to the same file (read()).
            self._reading = concurrent.futures.ThreadPoolExecutor(READ_THREADS, thread_name_prefix="opendmt3-game-read")
        if self.records is not None:
            # The first places, built now on that thread: the first card login does not wait for them.
            self.firsts = firsts.FirstPlaces(self.records)
            await self.database(self.firsts.places)
        if self.activity is not None:
            # Sessions a stopped server left open are over.
            await self.database(self.write, self.activity.close_left_open)
        self._server = await asyncio.start_server(self._accept, self.host, self.port)
        # Port 0 asks the system for a free one (the tests do); report the real one.
        self.port = self._server.sockets[0].getsockname()[1]
        self._sweeper = asyncio.ensure_future(self._sweep())
        log.info("game server listening on %s:%d", self.host, self.port)
        return self

    async def _accept(self, reader, writer):
        peer = writer.get_extra_info("peername") or ("?", 0)
        who = limits.sender(peer[0])
        if len(self.connections) >= MAX_CONNECTIONS:
            self.refusals.note(who, "the server has %d links already" % MAX_CONNECTIONS)
            writer.close()
            return
        if self.links[who] >= PER_ADDRESS:
            self.refusals.note(who, "%d links from this address already" % PER_ADDRESS)
            writer.close()
            return
        if not self.spend(who, connection.LINK_BYTES):
            # A new link spends part of the address's budget (reconnecting over and over is sending too); one that
            # spent its minute's bytes gets no new link until the minute ends.
            self.refusals.note(who, "more than %d bytes in a minute" % connection.BYTES_PER_MINUTE)
            writer.close()
            return
        conn = connection.Connection(self, reader, writer, rng=self.rng)
        with self.lock:
            self.connections.add(conn)
        self.links[who] += 1
        # This link's task, for close() to wait on.
        task = asyncio.current_task()
        self._serving.add(task)
        try:
            await conn.run()
        finally:
            with self.lock:
                self.connections.discard(conn)
            self.links[who] -= 1
            if self.links[who] <= 0:
                # Only addresses with links open stay in the table.
                del self.links[who]
            try:
                # What the link asked of the database is done first (results on their way are kept, a login
                # answered), so the session that ends is the last one it started.
                await conn.finish()
                if self.activity is not None and conn.answer is not None:
                    # The player's session ends with the link; the cabinet was last seen now (on the database's
                    # thread).
                    await self.database(self.write, functools.partial(self.activity.end, conn.session, conn.host))
            except Exception:  # noqa: BLE001  (a link's end is logged; the server goes on)
                log.exception("%s: the end of its session could not be written", conn.address)
            finally:
                # Only now is the link's work all done (close() waits for this).
                self._serving.discard(task)

    async def dispatch(self, conn, msg):
        handler = HANDLERS.get(msg[0])
        # The login messages carry what logs a player in: kept and logged without their bytes, handled or not.
        secret = msg[0] in messages.CARRIES_SECRETS
        kept = {"at": time.time(), "cabinet": conn.host, "header": msg[0], "name": messages.name(msg[0]),
                "size": len(msg), "handled": handler is not None,
                "bytes": "" if handler is not None or secret else bytes(msg[:KEPT_BYTES]).hex()}
        with self.lock:
            self.messages.append(kept)
        if not conn.online and msg[0] != 0x02:
            # Nothing counts before the handshake: a login or a result from a client that never answered it.
            log.debug("%s -> %s before the handshake: ignored", conn.address, messages.name(msg[0]))
            return
        if handler is None:
            if msg[0] not in conn.unhandled:
                conn.unhandled.add(msg[0])
                log.info("%s -> %s (%d bytes): no handler yet", conn.address, messages.name(msg[0]), len(msg))
            log.debug("%s -> %s: %s", conn.address, messages.name(msg[0]),
                      "(bytes not shown: a login message)" if secret else msg[:LOGGED_BYTES].hex())
            return
        result = handler(self, conn, msg)
        if asyncio.iscoroutine(result):
            # A handler that waits for the database (a card login, results) runs after the link's earlier ones, in
            # the order their messages came, apart from the link's reading (Connection.queue): the link's keep-alives
            # are answered while it waits, however long the database is held.
            conn.queue(result)

    async def close(self):
        if self._sweeper is not None:
            self._sweeper.cancel()
            # Waited for, so the loop closing next finds no task of ours still pending.
            await asyncio.gather(self._sweeper, return_exceptions=True)
            self._sweeper = None
        # What was counted and not told yet is told now.
        self.refusals.flush(everything=True)
        if self._server is not None:
            # No new link from here on.
            self._server.close()
        # Every link closed before the wait: since Python 3.12 the server's wait_closed waits for its links too, so
        # with them still open it waited until each ended by itself (90 seconds after its last message, and never
        # while a cabinet kept its link alive).
        with self.lock:
            links = list(self.connections)
        for conn in links:
            conn.writer.close()
        if self._server is not None:
            await self._server.wait_closed()
        if self._serving:
            # Each closed link ends its session on the database's thread as its task ends: waited for (a few
            # seconds at most), so none is cut off by the thread's end below.
            await asyncio.wait(set(self._serving), timeout=5)
        if self._database is not None:
            # What was asked of the database's thread (a session's end as a link closed) is done before the caller
            # closes the connection; waited for off the loop, which goes on meanwhile.
            # Forgotten only once it has ended: until then nothing runs here on the loop beside it (database()).
            await asyncio.get_running_loop().run_in_executor(None, functools.partial(self._database.shutdown,
                                                                                     wait=True))
            self._database = None
        if self._reading is not None:
            # The reading threads ended (what they were asked is done), then their connections closed.
            await asyncio.get_running_loop().run_in_executor(None, functools.partial(self._reading.shutdown,
                                                                                     wait=True))
            self._reading = None
            with self._read_lock:
                opened, self._read_connections = self._read_connections, []
            for reading in opened:
                reading.close()


def _charted(songs, row):
    """Whether a chart (a row with song and pattern) is one the game has: one of its patterns, and with a song list
    one of its songs."""
    return row["pattern"] in messages.PATTERNS and (not songs or row["song"] in songs)


# --------------------------------------------------------------------------------------------- handlers


@handles(0x02)
def handshake_answer(server, conn, msg):
    """The client's answer: check it holds the same table, then let it online (or refuse)."""
    if conn.online:
        # One handshake per connection; a second answer changes nothing.
        return
    answer = messages.HandshakeAnswer(msg, conn.index0, conn.index1, crypto.TABLE)
    conn.answer = answer
    if not answer.words_match:
        server.refusals.note(conn.sender, "a handshake answer with other table words", conn.address)
        conn.send(messages.handshake_result(ok=False))
        # The result is sent, then the link closes: a client that failed the check gets no second try on it.
        conn.closing = True
        return
    conn.send(messages.handshake_result(ok=True))
    conn.online = True
    if server.activity is not None:
        # The cabinet as the admin pages know it, written on the database's thread after the link's earlier work.
        conn.queue(server.database(server.write, functools.partial(server.activity.seen, conn.host, answer.version,
                                                                   conn.address)))
    log.info("%s online: client %s, machine %08x", conn.address, answer.version, answer.machine)


@handles(0x5E)
def online_notify(server, conn, msg):
    """The client says it entered its online state; nothing to answer."""
    log.debug("%s online notice", conn.address)


@handles(0x0A)
def alive(server, conn, msg):
    """Keep-alive: answer at once, or the client reconnects after about a minute."""
    conn.send(messages.alive_ack())


@handles(0x07)
def pong(server, conn, msg):
    """The answer to our ping; receiving it is all that matters (the idle timer saw data)."""


@handles(0x60)
async def card_auth(server, conn, msg):
    """A card in the reader: the player whose card it is, or a refusal the game shows as a failed login. While the
    server is in maintenance (services/maintenance.py) every card is refused that way, before it is looked up.

    What the answer needs is looked up off the loop (GameServer.login): the account, its records and its DJ card on a
    reading thread beside the database's writer, the first places from memory and the new session on the writer; the
    loop only sends what came back, so a login never holds up another cabinet."""
    if server.data is not None and maintenance.read(server.data) is not None:
        # The game shows a failed membership authentication and goes back to its card screen; the link stays online,
        # and a player who logged in before goes on playing. Told once a minute per address, as other refusals are.
        server.refusals.note(conn.sender, "a card login during maintenance", conn.address)
        conn.send(messages.auth_in_ack(messages.AUTH_FAILED))
        return
    card = messages.card_number(msg)
    row, answer = await server.login(card, conn.host, conn.session)
    if answer is None:
        # A card number logs in by itself, so the log shows only its last four digits; once a minute per address.
        server.refusals.note(conn.sender, "an unknown card" if row is None else "a disabled account's card",
                             "%s, card ...%s" % (conn.address, card[-4:]))
        conn.send(messages.auth_in_ack(messages.AUTH_FAILED))
        return
    # The link's state first, then the answer: what the game reads next (its results) finds the player logged in.
    conn.player = row["login_id"]
    # A new login: its own count of stages kept.
    conn.stages_kept = 0
    if server.activity is not None:
        # The session card_login started (the cabinet's last one ended there).
        conn.session = answer["session"]
    # The player's records, then the player, then the result: the game takes the records over as it reads 0x65,
    # and fills its DJ card from 0x65 as it shows the success screen. Then the server's first places, thousands of
    # messages on a long history. Each part encrypted together off the loop (Connection.send_all), the result first so
    # the game shows it before the first places are ready.
    await conn.send_all(list(answer["records"]) + [messages.user_info(row["id"], row["dj_name"], **answer["card"]),
                                                    messages.auth_in_ack(messages.AUTH_OK)])
    await conn.send_all(answer["firsts"] or ())
    log.info("%s logged in: %s (%s)", conn.address, row["login_id"], row["dj_name"])


def _why_not_kept(mode, record, songs):
    """Why a stage of a 0x6E is not one the game can have sent, or None: a mode it does not have, a pattern outside
    its four, or (with a song list) a song it does not have."""
    if mode not in messages.MODE_NAMES:
        return "mode %d" % mode
    if record["pattern"] not in messages.PATTERNS:
        return "pattern %d" % record["pattern"]
    if songs and record["song"] not in songs:
        return "song %d, not in the song list" % record["song"]
    return None


def _not_kept(conn, why):
    """Say once per link why results were not kept (a client sending many would otherwise fill the log)."""
    if conn.results_told:
        log.debug("%s results not kept: %s", conn.address, why)
        return
    conn.results_told = True
    log.info("%s results not kept: %s (no more lines about results on this link)", conn.address, why)


@handles(0x6E)
async def stage_results(server, conn, msg):
    """The session's cleared stages: kept for the player logged in on this cabinet (guests' are not kept, and
    neither are those of an account disabled since it logged in), when the game can have sent them: its modes,
    patterns and songs, and no more than STAGES_PER_LOGIN stages a card login. Kept on the database's thread, all
    of a message's stages in one transaction with the session's end (GameServer.keep_results)."""
    user, mode, cleared, records = messages.stage_results(msg)
    row, outcome = (None, None)
    if server.accounts is not None and conn.player:
        row, outcome = await server.database(server.keep_results, conn.player, conn.address, conn.session, mode,
                                             records, conn.stages_kept)
    if outcome is None:
        _not_kept(conn, "%d stages of %s" % (len(records), "a guest" if row is None else "a disabled account"))
        return
    for record, why, taken in outcome:
        if why is not None:
            _not_kept(conn, "%s: %s" % (row["login_id"], why))
            continue
        conn.stages_kept += 1
        if taken is not None:
            # First place taken from someone else: a line to the players' chat (on a thread of its own).
            server.webhook.new_top(row["dj_name"], taken[1], mode, record)
        # Each stage kept, in the log: what the player cleared, as the server read it.
        log.info("%s %s: %s song %d pattern %d score %d", conn.address, row["login_id"],
                 messages.MODE_NAMES.get(mode, "mode %d" % mode), record["song"], record["pattern"], record["score"])
    if server.activity is not None and conn.session is not None:
        # keep_results ended the session with the results; the next card starts the next one.
        conn.session = None
