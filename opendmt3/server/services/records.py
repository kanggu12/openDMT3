"""Plays: the cleared stages the game reports at the end of a session, kept per player, and what the site makes
of them: rankings, songs, each chart's board and a player's best scores.

A chart is a song's pattern in one mode. A player's score on a chart is their best on it; a ranking adds up
each player's best on every chart of a mode. Disabled accounts are left out of everything that shows other
players. Players are shown by their account number, never by their login ID (half of what signs them in).
"""

import threading
import time

# The accounts whose plays the lists of everyone's plays show.
ENABLED = "SELECT id FROM accounts WHERE disabled = 0"
# A chart's plays in the order its first place is picked by (the higher score, then the earlier play, then the lower
# id), as the index plays_by_chart (database step 8) holds them: the first of them is the chart's top play.
BEST_FIRST = "q.score DESC, q.played_at, q.id"
# Every chart's top play, by walking the index plays_by_chart from one chart to the next: a chart's top play is its
# first entry, and the next chart's is the first entry past the chart, found by three seeks (the next pattern of the
# same song, else the next song of the same mode, else the next mode; COALESCE stops at the first that finds one).
# A look per chart, so it costs as much for 1,000,000 plays as for 300,000 (30-35 ms for 3,500 charts, where a window
# function over every play took 0.7 s and 2.7 s). Each with its player's DJ name and whether their account is disabled.
TOP_PLAYS = (
    "WITH RECURSIVE c(id, mode, song, pattern) AS ("
    # The first chart's top play: the index's first entry.
    " SELECT id, mode, song, pattern FROM (SELECT q.id, q.mode, q.song, q.pattern FROM plays AS q"
    "  INDEXED BY plays_by_chart ORDER BY q.mode, q.song, q.pattern, " + BEST_FIRST + " LIMIT 1)"
    " UNION ALL"
    # From each chart to the next one's top play.
    " SELECT p.id, p.mode, p.song, p.pattern FROM c JOIN plays AS p ON p.id = COALESCE("
    "  (SELECT q.id FROM plays AS q INDEXED BY plays_by_chart WHERE q.mode = c.mode AND q.song = c.song"
    "   AND q.pattern > c.pattern ORDER BY q.pattern, " + BEST_FIRST + " LIMIT 1),"
    "  (SELECT q.id FROM plays AS q INDEXED BY plays_by_chart WHERE q.mode = c.mode AND q.song > c.song"
    "   ORDER BY q.song, q.pattern, " + BEST_FIRST + " LIMIT 1),"
    "  (SELECT q.id FROM plays AS q INDEXED BY plays_by_chart WHERE q.mode > c.mode"
    "   ORDER BY q.mode, q.song, q.pattern, " + BEST_FIRST + " LIMIT 1)))"
    " SELECT p.mode, p.song, p.pattern, p.score, a.dj_name, p.played_at, p.id, p.account_id, a.disabled"
    " FROM c JOIN plays AS p ON p.id = c.id JOIN accounts AS a ON a.id = p.account_id")
# One chart's first place among enabled players (top() and first_places() when a chart's top play is a disabled
# player's): down the chart's entries in plays_by_chart until an enabled player's.
TOP_ENABLED = (
    "SELECT q.mode, q.song, q.pattern, q.score, a.dj_name, q.played_at, q.id, q.account_id, a.disabled"
    " FROM plays AS q INDEXED BY plays_by_chart JOIN accounts AS a ON a.id = q.account_id"
    " WHERE q.mode = ? AND q.song = ? AND q.pattern = ? AND a.disabled = 0 ORDER BY " + BEST_FIRST + " LIMIT 1")

# What the site's lists of everyone's plays (rankings, songs, a song's boards, a DJ's page) are made of, beyond the
# plays added (which the newest play's number tells, web/cache.py): a count that goes up when a player is disabled,
# enabled, renamed or deleted, their DJ card changes, plays are reset or the database is restored. Shared by every
# thread of the process (the site's workers, the game server's database thread), so it changes under a lock.
_changes = [0]
_changes_lock = threading.Lock()


def changed():
    """Count one change of what the lists are made of (see _changes): the lists made before it are made again."""
    with _changes_lock:
        _changes[0] += 1


def changes():
    """How many changes changed() has counted in this process."""
    with _changes_lock:
        return _changes[0]
# Plays of the same player on the same chart before the play `p` (the id breaks a tie in time), as `e`: what the
# play is weighed against. The index plays_best (account, mode, song, pattern, score) finds them.
EARLIER = ("e.account_id = p.account_id AND e.mode = p.mode AND e.song = p.song AND e.pattern = p.pattern"
           " AND (e.played_at < p.played_at OR (e.played_at = p.played_at AND e.id < p.id))")
# The player's best on the chart before the play `p` (NULL before their first play of it).
BEFORE = "(SELECT MAX(e.score) FROM plays AS e WHERE " + EARLIER + ")"


class Records:
    # How many of the newest plays new_records() checks at first, and the most it checks that way before it takes
    # the bound from each chart's best instead (records_by_chart). Measured on 50,000 plays: checking 1,024 takes
    # about 4 ms; the bound takes 8 ms plus about 1.3 microseconds per chart played twice or more (40 ms with
    # 25,000 of them), where checking every play took 60 to 90 ms.
    CHECKED_FIRST, CHECKED_MOST = 256, 1024

    def __init__(self, db):
        self.db = db

    def add(self, account_id, cabinet, mode, record, at=None, session_id=None):
        """One cleared stage (a record from messages.stage_results), with the session it came in when known. Returns
        the play's number and the moment it was kept, which the game server's first places take it by
        (services/firsts.py)."""
        moment = int(at or time.time())
        cursor = self.db.execute(
            "INSERT INTO plays (account_id, cabinet, mode, song, pattern, score, counts, record, played_at, session_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, cabinet, mode, record["song"], record["pattern"], record["score"],
             ",".join(str(c) for c in record["counts"]), record["raw"], moment, session_id))
        return cursor.lastrowid, moment

    def recent(self, account_id=None, limit=10, since=None, before=False):
        """The newest plays, of one player or of everyone (disabled accounts left out), optionally only after a
        moment. before=True adds `before` to each: the player's best on the chart before that play (None before
        their first play of it), so a page can mark the plays that beat it.

        The newest ids come first, from the index on (account, time), which holds each play's id: read per account
        from the newest down, it stops once `limit` are in hand, and no table page is read for the plays left out
        (on 50,000 plays everyone's newest took 4 ms as a sort of the whole table, 0.1 ms this way)."""
        where, args = [], []
        if account_id is not None:
            # One player's plays, whether their account is enabled or not (their own page decides that).
            where.append("n.account_id = ?")
            args.append(account_id)
        else:
            # Everyone's: the enabled accounts, as a list SQLite walks the index with, one account at a time.
            where.append("n.account_id IN (%s)" % ENABLED)
        if since is not None:
            # Still the same index: a range of time within each account.
            where.append("n.played_at >= ?")
            args.append(int(since))
        newest = ("SELECT n.id FROM plays AS n WHERE %s ORDER BY n.played_at DESC, n.id DESC LIMIT ?"
                  % " AND ".join(where))
        # The rows themselves for those ids only; the best before each is looked up for them only too.
        return self.db.execute(
            "SELECT p.*, accounts.dj_name%s FROM plays AS p JOIN accounts ON accounts.id = p.account_id"
            " WHERE p.id IN (%s) ORDER BY p.played_at DESC, p.id DESC"
            % (", %s AS before" % BEFORE if before else "", newest), args + [limit]).fetchall()

    def count(self, account_id=None):
        """How many plays a list of recent() ones is cut from: one player's, or everyone's (enabled accounts)."""
        if account_id is not None:
            # A range of the index on (account, time), counted without the table.
            return self.db.execute("SELECT COUNT(*) FROM plays WHERE account_id = ?", (account_id,)).fetchone()[0]
        return self.db.execute("SELECT COUNT(*) FROM plays WHERE account_id IN (%s)" % ENABLED).fetchone()[0]

    def new_records(self, limit=10):
        """The newest plays that beat the player's previous best on the same chart (a first play of a chart has no
        best to beat, so it is not one), enabled accounts only, newest first; each row as recent() gives it with
        `before`, the best it beat.

        The newest plays are checked first, a few hundred at a time (each check is a look into the index plays_best);
        when records are rare among the newest CHECKED_MOST plays, the exact answer comes from each chart's best
        instead (records_by_chart), so a long history with few records costs a bounded scan, not a check of every
        play."""
        enabled = self.db.execute("SELECT COUNT(*) FROM plays WHERE account_id IN (%s)" % ENABLED).fetchone()[0]
        checked = self.CHECKED_FIRST
        while True:
            # The newest `checked` plays, with the best before each, and the newest `limit` of those that beat it.
            rows = self.db.execute(
                "SELECT * FROM (SELECT p.*, accounts.dj_name, %s AS before FROM plays AS p"
                " JOIN accounts ON accounts.id = p.account_id WHERE p.id IN ("
                " SELECT n.id FROM plays AS n WHERE n.account_id IN (%s)"
                " ORDER BY n.played_at DESC, n.id DESC LIMIT ?))"
                " WHERE score > before ORDER BY played_at DESC, id DESC LIMIT ?"
                % (BEFORE, ENABLED), (checked, limit)).fetchall()
            if len(rows) >= limit or checked >= enabled:
                # Enough, or every play was checked: exact either way.
                return rows
            if checked >= self.CHECKED_MOST:
                # Few records among the newest plays: the bound from each chart's best.
                return self.records_by_chart(limit)
            # Four times as many the next time round.
            checked *= 4

    def records_by_chart(self, limit=10):
        """new_records() for any history, from each chart's best: the newest record on a chart (one player's) is the
        play that set their best on it, when they had played it before. So the newest `limit` records overall lie
        on the `limit` charts whose best was set last as a record: any other record has `limit` newer ones before
        it. One scan of the index plays_best for the charts played more than once, then those few charts' plays."""
        charts = self.db.execute(
            # Each player's charts played twice or more (only those can hold a record), with their best score.
            "WITH g AS (SELECT account_id, mode, song, pattern, MAX(score) AS best FROM plays"
            "  WHERE account_id IN (%s) GROUP BY account_id, mode, song, pattern HAVING COUNT(*) >= 2),"
            # The play that set it: the first with that score (the id breaks a tie in time).
            # (The index named: without it SQLite walks the player's every play in time order for each chart.)
            " s AS (SELECT (SELECT p.id FROM plays AS p INDEXED BY plays_best WHERE p.account_id = g.account_id"
            "  AND p.mode = g.mode"
            "  AND p.song = g.song AND p.pattern = g.pattern AND p.score = g.best"
            "  ORDER BY p.played_at, p.id LIMIT 1) AS id FROM g)"
            # A record when it was not the chart's first play; the charts of the newest `limit` of those.
            " SELECT p.account_id, p.mode, p.song, p.pattern FROM s JOIN plays AS p ON p.id = s.id"
            " WHERE EXISTS (SELECT 1 FROM plays AS e WHERE %s)"
            " ORDER BY p.played_at DESC, p.id DESC LIMIT ?" % (ENABLED, EARLIER), (limit,)).fetchall()
        found = []
        for chart in charts:
            # Every play of the chart in time order; each one above the best so far is a record.
            best = None
            for row in self.db.execute(
                    # The chart's own plays through plays_best (by time, SQLite would walk the player's every play).
                    "SELECT p.*, accounts.dj_name FROM plays AS p INDEXED BY plays_best"
                    " JOIN accounts ON accounts.id = p.account_id"
                    " WHERE p.account_id = ? AND p.mode = ? AND p.song = ? AND p.pattern = ?"
                    " ORDER BY p.played_at, p.id", tuple(chart)):
                if best is not None and row["score"] > best:
                    # The row as recent(before=True) gives it: its columns and the best it beat.
                    found.append(dict(row, before=best))
                best = row["score"] if best is None else max(best, row["score"])
        # The newest first, as everywhere: by time, then by id.
        found.sort(key=lambda r: (r["played_at"], r["id"]), reverse=True)
        return found[:limit]

    # ------------------------------------------------------------------------------------ the admin's plays log

    @staticmethod
    def _log_where(account_id=None, since=None, songs=None):
        """The plays log's filter as SQL on plays `n`, with its arguments: one player's plays or everyone's (disabled
        accounts too: it is the admin's log), only after a moment, only some songs."""
        if account_id is not None:
            where, args = ["n.account_id = ?"], [account_id]
        else:
            # Every account, as a list SQLite walks the index (account, time) with: newest first without a sort of
            # the whole table.
            where, args = ["n.account_id IN (SELECT id FROM accounts)"], []
        if since is not None:
            where.append("n.played_at >= ?")
            args.append(int(since))
        if songs is not None:
            # The songs whose title has the word; none at all matches no play.
            where.append("n.song IN (%s)" % ", ".join("?" * len(songs)) if songs else "0")
            args.extend(songs)
        return " AND ".join(where), args

    def log(self, account_id=None, since=None, songs=None, limit=50, offset=0):
        """One page of the plays log, newest first: each play with its player's DJ name and login ID."""
        where, args = self._log_where(account_id, since, songs)
        return self.db.execute(
            "SELECT p.id, p.played_at, p.mode, p.song, p.pattern, p.score, p.account_id, a.dj_name, a.login_id"
            " FROM plays AS p JOIN accounts AS a ON a.id = p.account_id WHERE p.id IN ("
            " SELECT n.id FROM plays AS n WHERE %s ORDER BY n.played_at DESC, n.id DESC LIMIT ? OFFSET ?)"
            " ORDER BY p.played_at DESC, p.id DESC" % where, args + [limit, offset]).fetchall()

    def log_totals(self, account_id=None, since=None, songs=None):
        """What the plays log's filter leaves, counted: plays, players and charts."""
        where, args = self._log_where(account_id, since, songs)
        row = self.db.execute(
            "SELECT COUNT(*), COUNT(DISTINCT n.account_id),"
            " (SELECT COUNT(*) FROM (SELECT DISTINCT n.mode, n.song, n.pattern FROM plays AS n WHERE %s))"
            " FROM plays AS n WHERE %s" % (where, where), args + args).fetchone()
        return {"plays": row[0], "players": row[1], "charts": row[2]}

    def log_all(self, account_id=None, since=None, songs=None, batch=1000):
        """Every play the filter leaves, newest first, a batch of rows at a time (for a file of them)."""
        where, args = self._log_where(account_id, since, songs)
        cursor = self.db.execute(
            "SELECT n.id, n.played_at, n.mode, n.song, n.pattern, n.score, n.account_id, a.dj_name, a.login_id"
            " FROM plays AS n JOIN accounts AS a ON a.id = n.account_id WHERE %s"
            " ORDER BY n.played_at DESC, n.id DESC" % where, args)
        while True:
            rows = cursor.fetchmany(batch)
            if not rows:
                return
            yield rows

    # ------------------------------------------------------------------------------------ the admin's reset

    def reset(self, account_id=None):
        """Delete every play, or one player's (account_id): their cleared stages leave the rankings, the boards, the
        DJ pages and the game's song select. Accounts, their DJ cards, the play sessions and the cabinets stay.
        Returns how many plays went."""
        if account_id is None:
            # Every play, in one statement (SQLite empties the table without reading its rows one by one).
            cursor = self.db.execute("DELETE FROM plays")
        else:
            # One player's, found by the index on (account, time).
            cursor = self.db.execute("DELETE FROM plays WHERE account_id = ?", (account_id,))
        # The site's lists of everyone's plays are made again (a reset can leave the newest play's number as it was).
        changed()
        # How many went, for the change log and the answer.
        return cursor.rowcount

    def top(self, mode, song, pattern):
        """A chart's first place among enabled players: (player id, DJ name, score), or None before any clear. The
        chart's first entry in plays_by_chart that is an enabled player's (0 ms on 300,000 plays, where reading the
        chart's plays through the player's index took 18)."""
        row = self.db.execute(TOP_ENABLED, (mode, song, pattern)).fetchone()
        return (row["account_id"], row["dj_name"], row["score"]) if row else None

    def best(self, account_id, mode, song, pattern):
        """The player's best score on one chart before now, or None."""
        row = self.db.execute("SELECT MAX(score) FROM plays WHERE account_id = ? AND mode = ? AND song = ? AND pattern = ?",
                              (account_id, mode, song, pattern)).fetchone()
        return row[0]

    def modes(self):
        """The modes an enabled player has cleared a stage in, in the game's order.

        Read by skipping through the index plays_best (account, mode, ...): per enabled player, their lowest mode,
        then the next one above it, and so on, a few looks per player instead of reading every play (0.4 ms on
        50,000 plays, where the plain DISTINCT read them all in 6.5)."""
        return [row[0] for row in self.db.execute(
            "WITH RECURSIVE m(account, mode) AS ("
            " SELECT a.id, (SELECT MIN(p.mode) FROM plays AS p WHERE p.account_id = a.id) FROM accounts AS a"
            " WHERE a.disabled = 0"
            " UNION ALL SELECT m.account, (SELECT MIN(p.mode) FROM plays AS p WHERE p.account_id = m.account"
            " AND p.mode > m.mode) FROM m WHERE m.mode IS NOT NULL)"
            " SELECT DISTINCT mode FROM m WHERE mode IS NOT NULL ORDER BY mode")]

    # How many of a player's best charts the skill ranking averages.
    BEST_OF = 30

    def rankings(self, mode, by="total"):
        """A mode's ranking, highest first. by="total": each player's best scores on every chart added up (playing
        more raises it). by="best30": the average of each player's BEST_OF best charts, those they have not cleared
        counted as 0 (how well, more than how much); `charts` is then how many of the BEST_OF they have."""
        # Each player's best per chart of the mode read from plays_best (account, mode, song, pattern, score), which
        # holds all of it: named, because SQLite would rather seek the mode in plays_by_chart and read each play's row
        # for its player (1.3 s on 1,000,000 plays, where this takes 0.3).
        if by == "best30":
            return self.db.execute(
                "SELECT player, dj_name, CAST(SUM(best) / ? AS INTEGER) AS total, COUNT(*) AS charts FROM ("
                " SELECT a.id AS player, a.dj_name, b.best,"
                " ROW_NUMBER() OVER (PARTITION BY b.account_id ORDER BY b.best DESC) AS n"
                " FROM (SELECT account_id, song, pattern, MAX(score) AS best FROM plays INDEXED BY plays_best"
                "       WHERE mode = ? GROUP BY account_id, song, pattern) AS b"
                " JOIN accounts AS a ON a.id = b.account_id WHERE a.disabled = 0)"
                " WHERE n <= ? GROUP BY player ORDER BY total DESC, charts DESC, player",
                (self.BEST_OF, mode, self.BEST_OF)).fetchall()
        return self.db.execute(
            "SELECT a.id AS player, a.dj_name, SUM(b.best) AS total, COUNT(*) AS charts"
            " FROM (SELECT account_id, song, pattern, MAX(score) AS best FROM plays INDEXED BY plays_best"
            "       WHERE mode = ? GROUP BY account_id, song, pattern) AS b"
            " JOIN accounts AS a ON a.id = b.account_id WHERE a.disabled = 0"
            " GROUP BY a.id ORDER BY total DESC, charts DESC, a.id", (mode,)).fetchall()

    def rankings_between(self, mode, since, until):
        """A mode's ranking by total, as rankings() makes it, from the plays of a stretch of time only (a month's):
        each player's best on each chart in it, added up. The index on (account, time) gives each enabled player's
        plays of the stretch without reading the rest (named: SQLite would rather read the mode's every play
        through plays_best, 11 ms where this takes 4 on 50,000 plays, and more as the history grows)."""
        return self.db.execute(
            "SELECT a.id AS player, a.dj_name, SUM(b.best) AS total, COUNT(*) AS charts"
            " FROM (SELECT account_id, song, pattern, MAX(score) AS best FROM plays INDEXED BY plays_by_account"
            "       WHERE account_id IN (%s) AND played_at >= ? AND played_at < ? AND mode = ?"
            "       GROUP BY account_id, song, pattern) AS b"
            " JOIN accounts AS a ON a.id = b.account_id"
            " GROUP BY a.id ORDER BY total DESC, charts DESC, a.id" % ENABLED, (since, until, mode)).fetchall()

    def past_months(self, mode, months, places=3):
        """The first `places` places of each month in `months` ((start, end) moments, newest first) in a mode, by
        total as rankings_between() makes it, equal totals sharing a place: [(index in `months`, rows)], months
        nobody played in left out.

        One read of the table from start to end (11 ms on 50,000 plays, where reading each player's months through
        the index took 33), each play put in its month, the disabled players left out before the places."""
        if not months:
            return []
        # Which month a play is in: its index in `months`, or none.
        which = "CASE %s END" % " ".join("WHEN p.played_at >= ? AND p.played_at < ? THEN %d" % i
                                         for i in range(len(months)))
        bounds = [value for start, until in months for value in (start, until)]
        rows = self.db.execute(
            # Each player's best per chart in each month.
            "WITH b AS (SELECT %s AS n, p.account_id, p.song, p.pattern, MAX(p.score) AS best"
            "  FROM plays AS p NOT INDEXED"
            "  WHERE p.played_at >= ? AND p.played_at < ? AND p.mode = ? GROUP BY 1, 2, 3, 4),"
            # Added up per player and month, then placed within the month (RANK: equal totals share a place).
            " t AS (SELECT n, account_id, SUM(best) AS total, COUNT(*) AS charts FROM b WHERE n IS NOT NULL"
            "  GROUP BY n, account_id),"
            " r AS (SELECT t.*, a.dj_name, RANK() OVER (PARTITION BY n ORDER BY total DESC) AS place FROM t"
            "  JOIN accounts AS a ON a.id = t.account_id WHERE a.disabled = 0)"
            " SELECT n, place, account_id AS player, dj_name, total, charts FROM r WHERE place <= ?"
            " ORDER BY n, place, charts DESC, account_id" % which,
            bounds + [min(m[0] for m in months), max(m[1] for m in months), mode, places]).fetchall()
        out = []
        for row in rows:
            if not out or out[-1][0] != row["n"]:
                # A month's first row starts its list.
                out.append((row["n"], []))
            out[-1][1].append(row)
        return out

    def totals(self):
        """Every enabled player's total in each mode, as rankings() adds them up (their best on each chart):
        {mode: {player: total}}. One pass over the index plays_best for every player at once."""
        totals = {}
        for mode, player, total in self.db.execute(
                "SELECT mode, account_id, SUM(best) FROM (SELECT account_id, mode, MAX(score) AS best FROM plays"
                " WHERE account_id IN (%s) GROUP BY account_id, mode, song, pattern) GROUP BY mode, account_id"
                % ENABLED):
            totals.setdefault(mode, {})[player] = total
        return totals

    def places(self, account_id):
        """The player's place in each mode's ranking by total (rankings(); equal totals share a place) and how many
        are ranked: {mode: (place, of)}, for the modes they played (places_in of totals())."""
        return places_in(self.totals(), account_id)

    def songs(self):
        """Per song cleared at least once: plays, players and the best score."""
        return self.db.execute(
            "SELECT p.song, COUNT(*) AS plays, COUNT(DISTINCT p.account_id) AS players, MAX(p.score) AS best"
            " FROM plays AS p JOIN accounts AS a ON a.id = p.account_id WHERE a.disabled = 0"
            " GROUP BY p.song ORDER BY plays DESC, p.song").fetchall()

    def boards(self, song):
        """Every chart of one song that was cleared: each player's best on it, highest first.

        One row per player and chart, with when that best was set (SQLite takes the other columns of an
        aggregate query from the row that holds the MAX)."""
        return self.db.execute(
            "SELECT p.mode, p.pattern, a.id AS player, a.dj_name, MAX(p.score) AS score, p.played_at AS at"
            " FROM plays AS p JOIN accounts AS a ON a.id = p.account_id WHERE p.song = ? AND a.disabled = 0"
            " GROUP BY p.mode, p.pattern, a.id ORDER BY p.mode, p.pattern, score DESC, at, a.id",
            (song,)).fetchall()

    def cleared(self, account_id):
        """How many times a player cleared each chart: rows of (mode, song, pattern, times), for experience."""
        return [tuple(row) for row in self.db.execute(
            "SELECT mode, song, pattern, COUNT(*) FROM plays WHERE account_id = ? GROUP BY mode, song, pattern",
            (account_id,))]

    def cleared_by_account(self):
        """cleared() of every player at once, in one query: {account id: rows of (mode, song, pattern, times)}."""
        out = {}
        for account_id, mode, song, pattern, times in self.db.execute(
                "SELECT account_id, mode, song, pattern, COUNT(*) FROM plays GROUP BY account_id, mode, song, pattern"):
            out.setdefault(account_id, []).append((mode, song, pattern, times))
        return out

    def first_places(self):
        """Each chart's first place among enabled players, as top() picks it (the higher score, then the earlier play,
        then the lower id): rows of mode, song, pattern, score, dj_name, played_at, id (the play's number) and
        account_id, by mode, song and pattern.

        Each chart's top play from the walk through plays_by_chart (TOP_PLAYS); a chart whose top play is a disabled
        player's looks further down its own entries (TOP_ENABLED), and a chart only disabled players cleared has none."""
        out = []
        for row in self.db.execute(TOP_PLAYS).fetchall():
            if row["disabled"]:
                # The chart's first enabled player, below the disabled one(s).
                row = self.db.execute(TOP_ENABLED, (row["mode"], row["song"], row["pattern"])).fetchone()
                if row is None:
                    # Nobody enabled cleared it: no first place, as the window function left it.
                    continue
            out.append(row)
        # The walk goes in the index's order already; sorted all the same, so the order never rests on a plan.
        out.sort(key=lambda r: (r["mode"], r["song"], r["pattern"]))
        return out

    def firsts(self):
        """Each chart's first place among enabled players, as top() picks it (the higher score, then the earlier):
        rows of mode, song, pattern, score and dj_name, for the game's song select (first_places, which the game server
        keeps in memory: services/firsts.py)."""
        return [{"mode": r["mode"], "song": r["song"], "pattern": r["pattern"], "score": r["score"],
                 "dj_name": r["dj_name"]} for r in self.first_places()]

    def bests(self, account_id):
        """A player's best on each chart they cleared, highest first, with when it was set."""
        return self.db.execute(
            "SELECT mode, song, pattern, MAX(score) AS score, played_at AS at FROM plays WHERE account_id = ?"
            " GROUP BY mode, song, pattern ORDER BY score DESC, at", (account_id,)).fetchall()

    def summary(self, account_id):
        """A player's plays, songs and charts cleared, and their last play (None for no play yet)."""
        row = self.db.execute(
            "SELECT COUNT(*) AS plays, COUNT(DISTINCT song) AS songs,"
            " COUNT(DISTINCT mode || '/' || song || '/' || pattern) AS charts, MAX(played_at) AS last"
            " FROM plays WHERE account_id = ?", (account_id,)).fetchone()
        return {"plays": row["plays"], "songs": row["songs"], "charts": row["charts"], "last": row["last"]}


def places_in(totals, account_id):
    """A player's place in each mode's ranking by total and how many are ranked, from every player's totals (as
    Records.totals gives them, or a kept copy of them): {mode: (place, of)}, for the modes the player played."""
    out = {}
    for mode, players in totals.items():
        if account_id in players:
            # Placed after everyone with a higher total.
            mine = players[account_id]
            out[mode] = (1 + sum(1 for t in players.values() if t > mine), len(players))
    return out
