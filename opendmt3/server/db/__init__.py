"""The server's database: one SQLite file, its tables created and upgraded in numbered steps.

Each step is a list of SQL statements run in one transaction, and PRAGMA user_version records how many have
run, so an older database is brought up to date on open and a newer one (from a later openDMT3) is refused.
Before any step runs on an existing file, a copy of it is kept next to it.
"""

import contextlib
import os
import sqlite3
import threading
import time

# Each entry upgrades the database by one version. Never edit a step once released; add a new one.
STEPS = [
    # 1: accounts (the ID typed at the cabinet is also the site's sign-in), cabinets seen, the change log.
    [
        """CREATE TABLE accounts (
               id INTEGER PRIMARY KEY,
               login_id TEXT NOT NULL UNIQUE COLLATE NOCASE,
               password TEXT NOT NULL,
               dj_name TEXT NOT NULL,
               card TEXT UNIQUE,
               is_admin INTEGER NOT NULL DEFAULT 0,
               disabled INTEGER NOT NULL DEFAULT 0,
               created_at INTEGER NOT NULL,
               last_login INTEGER
           )""",
        """CREATE TABLE cabinets (
               id INTEGER PRIMARY KEY,
               machine_key TEXT NOT NULL UNIQUE,
               name TEXT,
               version TEXT,
               address TEXT,
               first_seen INTEGER NOT NULL,
               last_seen INTEGER NOT NULL
           )""",
        """CREATE TABLE changes (
               id INTEGER PRIMARY KEY,
               at INTEGER NOT NULL,
               who TEXT NOT NULL,
               what TEXT NOT NULL
           )""",
    ],
    # 2: plays, one row per cleared stage the game reported (0x6e). The 47 bytes the game sent are kept as they
    # came, so fields understood later can still be read from old plays.
    [
        """CREATE TABLE plays (
               id INTEGER PRIMARY KEY,
               account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
               cabinet TEXT,
               mode INTEGER NOT NULL,
               song INTEGER NOT NULL,
               pattern INTEGER NOT NULL,
               score INTEGER NOT NULL,
               counts TEXT NOT NULL,
               record BLOB NOT NULL,
               played_at INTEGER NOT NULL
           )""",
        "CREATE INDEX plays_by_account ON plays (account_id, played_at)",
        "CREATE INDEX plays_best ON plays (account_id, mode, song, pattern, score)",
    ],
    # 3: play sessions, from a card login to the end of the link (or the next login on the same cabinet), for the
    # admin's status page and each DJ's activity; plays remember the session they came in. Cabinets (step 1) are
    # now written as they connect, keyed by their address.
    [
        """CREATE TABLE sessions (
               id INTEGER PRIMARY KEY,
               cabinet TEXT NOT NULL,
               account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
               started_at INTEGER NOT NULL,
               ended_at INTEGER
           )""",
        "CREATE INDEX sessions_by_account ON sessions (account_id, started_at)",
        "CREATE INDEX sessions_by_time ON sessions (started_at)",
        "ALTER TABLE plays ADD COLUMN session_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL",
    ],
    # 4: the DJ card the game shows beside the name: an icon, a title plate with a pattern drawn over it, and a
    # one-line comment over the plate (services/cards.py). Every account starts with the basic DJ icon (1) and
    # the Platinum Crew plate (32769) with no pattern, the values the game showed in the tests.
    [
        "ALTER TABLE accounts ADD COLUMN icon INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE accounts ADD COLUMN plate INTEGER NOT NULL DEFAULT 32769",
        "ALTER TABLE accounts ADD COLUMN pattern INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE accounts ADD COLUMN comment TEXT NOT NULL DEFAULT ''",
    ],
    # 5: the account's round of sign-ins on the site. Each sign-in cookie carries the round it was made in, and a
    # sign-out starts the next one, so the cookie (and any copy of it) stops working; the launcher's tokens do not
    # carry it and stay. Every account starts at round 0, the round of the cookies made before this step.
    [
        "ALTER TABLE accounts ADD COLUMN session_generation INTEGER NOT NULL DEFAULT 0",
    ],
    # 6: the API's tokens ended one by one before their time (DELETE /api/v1/session, the launcher's Sign out): each
    # by its id (a hash of the token, never the token itself), with the moment it would have expired anyway, after
    # which the row goes (services/accounts.py, end_token). The account's other tokens go on.
    [
        """CREATE TABLE revoked_tokens (
               id TEXT PRIMARY KEY,
               account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
               expires INTEGER NOT NULL
           )""",
    ],
    # 7: the API's named tokens a player makes on the Account page (services/tokens.py): each with the id that names it
    # in lists, the name its owner gave it, its scope (read, or write: read and write), the SHA-256 of the token (the
    # token itself is shown once and kept nowhere), when it was made and last used. They go with their account.
    [
        """CREATE TABLE api_tokens (
               id TEXT PRIMARY KEY,
               account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
               name TEXT NOT NULL,
               scope TEXT NOT NULL,
               hash TEXT NOT NULL,
               created_at INTEGER NOT NULL,
               used_at INTEGER
           )""",
        "CREATE INDEX api_tokens_by_account ON api_tokens (account_id, created_at)",
    ],
    # 8: indexes for what grows with the history (measured on a made-up history of 300,000 plays and 1,000,000).
    # Each chart's plays from its best down (the higher score, then the earlier play, then the lower id, the order
    # every first place is picked by): a chart's first place is its first entry, so the game server finds every
    # chart's first place by skipping through it (30-35 ms whatever the history's length, where a window function
    # over every play took 0.7 s and 2.7 s; records.first_places), and one chart's (records.top) at once, where
    # it took 18 ms. A cabinet's sessions and a session's plays: the admin's Cabinets page counts them per cabinet,
    # which read every session and every play for each cabinet without them (768 ms on 300,000 plays, 61 with them).
    [
        "CREATE INDEX plays_by_chart ON plays (mode, song, pattern, score DESC, played_at, id)",
        "CREATE INDEX sessions_by_cabinet ON sessions (cabinet)",
        "CREATE INDEX plays_by_session ON plays (session_id)",
    ],
]
VERSION = len(STEPS)
# How long a statement waits for another connection's write to end before it gives up with "database is locked", in
# seconds. Writes here take milliseconds; what holds the file longer is a restore copying a backup over it (a few
# seconds for a large one) or another program (the command line's --restore). Python's own default is 5 seconds.
BUSY_SECONDS = 15.0


class DatabaseError(Exception):
    """The database file is from a newer openDMT3, or cannot be opened."""


def schema_of(connection):
    """A database's tables as {table: (its columns' names, in order)}, SQLite's own tables (sqlite_...) left out:
    what tells this project's database from any other SQLite file."""
    tables = [r[0] for r in connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\'")]
    # Each table's columns by the pragma's table form, the name a parameter (never written into the SQL).
    return {table: tuple(r[0] for r in connection.execute("SELECT name FROM pragma_table_info(?) ORDER BY cid",
                                                          (table,)))
            for table in tables}


def schema(version):
    """The tables a database of `version` has, as schema_of() gives them: made by running the first `version` steps
    on an empty database in memory, so it can never differ from what the steps make."""
    connection = sqlite3.connect(":memory:")
    try:
        for step in STEPS[:version]:
            for statement in step:
                connection.execute(statement)
        return schema_of(connection)
    finally:
        connection.close()


class Lent(sqlite3.Connection):
    """A connection lent to every part of one piece of work (the site opens one for each request: web/app.py): a part's
    close() leaves it open for the next part, and whoever lent it closes it with release() once the work is done.

    Each part of a page used to open a connection of its own (3 to 7 a page); with one a request, a part keeps its
    try/finally close() as it was. A Lent connection the program forgets is still closed when it is collected
    (SQLite's own close, not this method)."""

    def close(self):
        # Given back, not closed: the request's next part uses it too.
        pass

    def release(self):
        # The real close, once the request's answer is sent.
        super().close()


@contextlib.contextmanager
def immediate(connection):
    """One write transaction on `connection`, its write lock taken at once (BEGIN IMMEDIATE, waiting up to
    BUSY_SECONDS for another connection's write): what is read inside it cannot change before what is written inside
    it (a check that an ID is free, then the account; a count of tokens, then one more). All of it is kept, or none
    when the block raises. Inside a transaction the caller began already, the block is part of that one."""
    if connection.in_transaction:
        yield
        return
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")


def connect(path, factory=None):
    """Open (creating or upgrading) the database at path; returns a sqlite3 connection with rows by name.

    factory: the connection's class (Lent for the site's requests), sqlite3's own when not given."""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    existed = os.path.isfile(path)
    if not existed:
        # Card numbers live here: a new database is its owner's alone (the umask may say otherwise).
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600))
        os.chmod(path, 0o600)
    # Autocommit (isolation_level=None): each statement is its own transaction unless a caller begins one. Usable from
    # any thread, one at a time (the site's request moves between worker threads; the game server's connection lives
    # on its database thread). A write waits up to BUSY_SECONDS for another connection's write to end.
    db = sqlite3.connect(path, timeout=BUSY_SECONDS, isolation_level=None, check_same_thread=False,
                         factory=factory or sqlite3.Connection)
    try:
        return _prepare(db, path, existed)
    except BaseException:
        # Not left open on a failure: Windows would keep the file locked while someone puts a backup in its place.
        # (sqlite3's own close: a Lent connection's close() would leave it open.)
        sqlite3.Connection.close(db)
        raise


# One upgrade at a time in this process (_prepare).
_UPGRADING = threading.Lock()


def _keep_copy(db, path, version):
    """A copy of the database before an upgrade changes anything, named after the version it was. SQLite's own backup
    reads the database as one moment, the part still in the write-ahead log included (a file copy would miss it)."""
    kept = "%s.v%d-%s.bak" % (path, version, time.strftime("%Y%m%d-%H%M%S"))
    # The card numbers are in the copy too: made readable by its owner only before anything is written into it,
    # as the database is (SQLite gives its journal the same permissions).
    os.close(os.open(kept, os.O_WRONLY | os.O_CREAT, 0o600))
    os.chmod(kept, 0o600)
    copy = sqlite3.connect(kept)
    try:
        db.backup(copy)
    finally:
        copy.close()


def _upgrade(db, version):
    """Each step from `version` on, each in its own transaction."""
    for number in range(version, VERSION):
        # The write lock first (IMMEDIATE), then the version again under it: another process (the command line beside
        # a running server) may find the same older database at once. The second waits here for the first's step and
        # then finds it done, instead of running it again ("index already exists").
        db.execute("BEGIN IMMEDIATE")
        try:
            if db.execute("PRAGMA user_version").fetchone()[0] > number:
                # Another connection ran this step meanwhile.
                db.execute("COMMIT")
                continue
            for statement in STEPS[number]:
                db.execute(statement)
            # user_version cannot take a parameter; the number is ours, not input.
            db.execute("PRAGMA user_version=%d" % (number + 1))
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise


def _while_locked(work):
    """work(), asked again every 50 ms while the database is locked, up to BUSY_SECONDS; any other error at once."""
    end = time.monotonic() + BUSY_SECONDS
    while True:
        try:
            return work()
        except sqlite3.OperationalError as e:
            # Locked by another connection's turn (it ends): asked again until the time is up; anything else is raised.
            if "locked" not in str(e) or time.monotonic() >= end:
                raise
            time.sleep(0.05)


def _prepare(db, path, existed):
    """connect()'s work on the open connection: refuse a newer database, then bring an older one up to date."""
    db.row_factory = sqlite3.Row
    # The version first: a database from a newer openDMT3 is refused before anything here writes to it (even the
    # journal mode below is a write to the file's header).
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version > VERSION:
        raise DatabaseError("%s is from a newer openDMT3 (version %d, this one knows %d)" % (path, version, VERSION))
    # WAL keeps the site's reads from waiting on the game server's writes. Turning a file to it takes the file whole:
    # connections opening at once in this process take turns (two that both read the file and then both ask for it
    # whole get "database is locked" at once, SQLite's busy wait being no use to either), and one held off by another
    # program's connection asks again for up to BUSY_SECONDS. A file in WAL already needs none of it.
    with _UPGRADING:
        _while_locked(lambda: db.execute("PRAGMA journal_mode=WAL").fetchone())
    db.execute("PRAGMA foreign_keys=ON")
    if version < VERSION:
        # One upgrade at a time in this process (_UPGRADING), the version read again under it: the site's threads
        # open a connection each, and each found the same older file and copied all of it into the same copy of the
        # same second. The one that upgrades makes the copy; the others find it done.
        with _UPGRADING:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version < VERSION and existed and version > 0:
                _keep_copy(db, path, version)
            _upgrade(db, version)
    return db
