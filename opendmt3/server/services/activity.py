"""Who plays where and when: the cabinets as they connect, play sessions, and the numbers made of them.

A cabinet is known by its address (the IP it connects from; the PC client reports no machine number of its
own), so the admin can name it. A session runs from a card login to the player's results (the game sends them
when the credit is over), or to the end of the link or the next login on the same cabinet if those come first; a
guest's play (NO ID CARD) is no one's session. Plays cleared in a session point at it.
Times are seconds since the epoch; "today" and the weeks follow the server's clock.
"""

import time

DAY = 86400
WEEK = 7 * DAY


def _day_start(now):
    """Midnight before `now` on the server's clock."""
    t = time.localtime(now)
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))


class Activity:
    def __init__(self, db):
        self.db = db

    # -------------------------------------------------------------------------------- the game server's side

    def seen(self, host, version, address, at=None):
        """A cabinet came online (or is still there): remember it by its address, keep the name it was given."""
        at = int(at or time.time())
        self.db.execute(
            "INSERT INTO cabinets (machine_key, version, address, first_seen, last_seen) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(machine_key) DO UPDATE SET version = excluded.version, address = excluded.address,"
            " last_seen = excluded.last_seen", (host, version, address, at, at))

    def start(self, host, account_id, at=None):
        """A card login on a cabinet: a new session; returns its id."""
        cursor = self.db.execute("INSERT INTO sessions (cabinet, account_id, started_at) VALUES (?, ?, ?)",
                                 (host, account_id, int(at or time.time())))
        return cursor.lastrowid

    def end(self, session_id, host=None, at=None):
        """The session's end (the link closed, or another card logged in), and the cabinet's last sighting."""
        at = int(at or time.time())
        if session_id is not None:
            self.db.execute("UPDATE sessions SET ended_at = ? WHERE id = ? AND ended_at IS NULL", (at, session_id))
        if host is not None:
            self.db.execute("UPDATE cabinets SET last_seen = ? WHERE machine_key = ?", (at, host))

    def close_left_open(self):
        """Sessions a stopped server never ended: ended where they began (their length is unknown)."""
        self.db.execute("UPDATE sessions SET ended_at = started_at WHERE ended_at IS NULL")

    # ------------------------------------------------------------------------------------ the pages' side

    def cabinets(self):
        """Every cabinet seen, last seen first, with its sessions and the stages cleared on it."""
        return [dict(r) for r in self.db.execute(
            "SELECT c.id, c.machine_key AS host, c.name, c.version, c.first_seen, c.last_seen,"
            " (SELECT COUNT(*) FROM sessions s WHERE s.cabinet = c.machine_key) AS sessions,"
            " (SELECT COUNT(*) FROM plays p JOIN sessions s ON s.id = p.session_id WHERE s.cabinet = c.machine_key)"
            " AS plays"
            " FROM cabinets c ORDER BY c.last_seen DESC, c.id")]

    def rename_cabinet(self, cabinet_id, name):
        """Give a cabinet a name the admin pages show (empty: back to its address); False if there is none."""
        name = (name or "").strip()[:32] or None
        cursor = self.db.execute("UPDATE cabinets SET name = ? WHERE id = ?", (name, cabinet_id))
        return cursor.rowcount > 0

    def status(self, now=None):
        """The server's numbers: plays, active players, sessions and play time over the last day, week and month."""
        now = int(now or time.time())
        today = _day_start(now)
        out = {}
        for label, since in (("today", today), ("week", now - WEEK), ("month", now - 30 * DAY)):
            plays, players = self.db.execute(
                "SELECT COUNT(*), COUNT(DISTINCT p.account_id) FROM plays p JOIN accounts a ON a.id = p.account_id"
                " WHERE p.played_at >= ?", (since,)).fetchone()
            sessions, seconds = self.db.execute(
                "SELECT COUNT(*), COALESCE(SUM(COALESCE(ended_at, ?) - started_at), 0) FROM sessions"
                " WHERE started_at >= ?", (now, since)).fetchone()
            out[label] = {"plays": plays, "players": players, "sessions": sessions, "seconds": seconds}
        accounts, disabled = self.db.execute(
            "SELECT COUNT(*), COALESCE(SUM(disabled), 0) FROM accounts").fetchone()
        out["accounts"] = {"all": accounts, "disabled": disabled}
        out["cabinets"] = self.db.execute("SELECT COUNT(*) FROM cabinets").fetchone()[0]
        return out

    def dj(self, account_id, now=None, weeks=12):
        """One player's activity: stages cleared per week (oldest first, this week last), per mode, their most
        played songs, and their sessions and play time (dj_plays and sessions together)."""
        now = int(now or time.time())
        out = self.dj_plays(account_id, now, weeks)
        out["sessions"], out["seconds"] = self.sessions(account_id, now)
        return out

    def sessions(self, account_id, now=None):
        """(how many sessions the player has had, their play time in seconds): an open session counts until now."""
        now = int(now or time.time())
        sessions, seconds = self.db.execute(
            "SELECT COUNT(*), COALESCE(SUM(COALESCE(ended_at, ?) - started_at), 0) FROM sessions WHERE account_id = ?",
            (now, account_id)).fetchone()
        return sessions, seconds

    def dj_plays(self, account_id, now=None, weeks=12):
        """What dj() makes of the player's plays alone: stages cleared per week (oldest first, this week last; the
        weeks end on `now`'s day), per mode, and their most played songs. The same all day until a play is kept (the
        site keeps it that long: web/cache.py)."""
        now = int(now or time.time())
        start = _day_start(now) - (weeks - 1) * WEEK - 6 * DAY
        per_week = [0] * weeks
        for (at,) in self.db.execute("SELECT played_at FROM plays WHERE account_id = ? AND played_at >= ?",
                                     (account_id, start)):
            # Week buckets end today: the last one holds the last seven days.
            index = weeks - 1 - (_day_start(now) - _day_start(at)) // WEEK
            if 0 <= index < weeks:
                per_week[index] += 1
        modes = {r[0]: r[1] for r in self.db.execute(
            "SELECT mode, COUNT(*) FROM plays WHERE account_id = ? GROUP BY mode ORDER BY mode", (account_id,))}
        songs = [{"song": r[0], "plays": r[1]} for r in self.db.execute(
            "SELECT song, COUNT(*) AS n FROM plays WHERE account_id = ? GROUP BY song ORDER BY n DESC, song LIMIT 5",
            (account_id,))]
        return {"weeks": per_week, "modes": modes, "songs": songs}
