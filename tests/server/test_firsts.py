"""The first places the game server keeps in memory (services/firsts.py) and the walk through the index that builds them
(records.first_places): always the answer of the window function they replaced, on a made-up history with ties in
score and in time, disabled players, renames, deletions and resets; built again only when the database changed in a
way the table did not follow.
"""

import os
import random
import shutil
import tempfile
import time
import unittest

from opendmt3.server import db
from opendmt3.server.services import accounts, firsts, records

# The query every card login ran before the first places were kept (records.firsts): each chart's first place among
# enabled players by a window function over every play. The reference the table must always agree with.
WINDOW = ("SELECT mode, song, pattern, score, dj_name FROM ("
          " SELECT p.mode, p.song, p.pattern, p.score, a.dj_name, ROW_NUMBER() OVER ("
          "  PARTITION BY p.mode, p.song, p.pattern ORDER BY p.score DESC, p.played_at, p.id) AS n"
          " FROM plays AS p JOIN accounts AS a ON a.id = p.account_id WHERE a.disabled = 0)"
          " WHERE n = 1 ORDER BY mode, song, pattern")


def stage(song, pattern, score):
    """A cleared stage as messages.stage_results gives it."""
    return {"song": song, "pattern": pattern, "score": score, "counts": [0] * 7, "raw": bytes(47)}


class FirstPlacesTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "openDMT3.sqlite")
        self.db = db.connect(self.path)
        self.accounts = accounts.Accounts(self.db)
        self.records = records.Records(self.db)
        # A fixed seed: a failure says it and comes back the same.
        self.rng = random.Random(4725)
        # Twelve players, made fast: the hash of one copied to the rest (only the plays matter here).
        self.players = [self.accounts.create("P0", "pass1234", "DJ 0")]
        secret = self.players[0]["password"]
        for n in range(1, 12):
            self.db.execute("INSERT INTO accounts (login_id, password, dj_name, card, created_at) VALUES (?, ?, ?, ?, ?)",
                            ("P%d" % n, secret, "DJ %d" % n, "%020d" % n, 0))
        self.players = self.db.execute("SELECT * FROM accounts ORDER BY id").fetchall()

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)

    def window(self, connection=None):
        """The reference answer, as (mode, song, pattern, score, dj_name) rows."""
        return [tuple(r) for r in (connection or self.db).execute(WINDOW)]

    @staticmethod
    def kept(places):
        """The table's answer in the reference's shape."""
        return [(p.mode, p.song, p.pattern, p.score, p.dj_name) for p in places]

    def play(self, player=None, at=None):
        """A random play on one of a few charts, with scores that tie often (a few values) and moments that tie too."""
        player = player or self.rng.choice(self.players)
        record = stage(self.rng.randint(1, 4), self.rng.randint(1, 4), self.rng.choice((1000, 2000, 3000, 3000)))
        mode = self.rng.choice((0, 0, 1, 2))
        moment = at if at is not None else 1_700_000_000 + self.rng.randint(0, 3)
        number, kept_at = self.records.add(player["id"], "x", mode, record, at=moment)
        return firsts.Place(mode, record["song"], record["pattern"], record["score"], player["dj_name"], kept_at,
                            number, player["id"])

    def test_the_walk_through_the_index_gives_the_window_functions_answer(self):
        for _ in range(600):
            self.play()
        # Some top players disabled: their charts' first places go to the next enabled player, or to nobody.
        for player in self.players[:4]:
            self.accounts.set_disabled(player["login_id"], True)
        self.assertEqual([tuple(r)[:5] for r in self.records.first_places()], self.window())
        self.assertEqual([tuple(r.values()) for r in self.records.firsts()], self.window())
        # top() of each chart is the same first place.
        for r in self.window():
            self.assertEqual(self.records.top(*r[:3])[2], r[3])

    def test_the_table_follows_every_change_and_stays_the_window_functions_answer(self):
        table = firsts.FirstPlaces(self.records)
        changes = [
            # The game server's own plays: offered, then followed (as GameServer.write does).
            "play", "play", "play", "play",
            # What the site does on its own connection (another connection: data_version says so).
            "disable", "enable", "rename", "reset", "delete",
            # A write on the table's own connection it is not told of (a test's own play).
            "unfollowed",
        ]
        other = db.connect(self.path)
        try:
            for step in range(300):
                change = self.rng.choice(changes)
                if change == "play":
                    # The game server keeps the plays of enabled players only (GameServer.keep_results checks the
                    # account in the same write transaction).
                    enabled = [p for p in self.players if not p["disabled"]]
                    if not enabled:
                        continue
                    before = self.db.total_changes
                    table.offer(self.play(self.rng.choice(enabled)))
                    table.follow(before)
                elif change == "unfollowed":
                    self.play()
                else:
                    who = self.rng.choice(self.players)["login_id"]
                    site = accounts.Accounts(other)
                    if change in ("disable", "enable"):
                        try:
                            site.set_disabled(who, change == "disable")
                        except accounts.AccountError:
                            # The last enabled admin stays (P0 is no admin: never refused here).
                            pass
                    elif change == "rename":
                        site.set_dj_name(who, "R%d" % step)
                    elif change == "reset":
                        records.Records(other).reset(site.by_login(who)["id"])
                    else:
                        site.delete(who)
                        # A deleted player is made again, so the history goes on with twelve.
                        other.execute("INSERT INTO accounts (login_id, password, dj_name, card, created_at)"
                                      " VALUES (?, 'x', ?, ?, 0)", (who, "NEW " + who, "%020d" % (1000 + step)))
                    self.players = self.db.execute("SELECT * FROM accounts ORDER BY id").fetchall()
                self.assertEqual(self.kept(table.places()), self.window(), "after step %d (%s)" % (step, change))
        finally:
            other.close()

    def test_a_play_takes_the_place_by_score_then_the_earlier_play_then_the_lower_number(self):
        table = firsts.FirstPlaces(self.records)
        table.places()
        a, b = self.players[1], self.players[2]
        first = self.play(a, at=100)
        self.assertTrue(table.offer(first))
        # The same score later: the earlier play keeps it.
        self.assertFalse(table.offer(first._replace(account_id=b["id"], dj_name=b["dj_name"], played_at=101,
                                                    id=first.id + 1)))
        # The same score at the same moment with a higher number: still the first.
        self.assertFalse(table.offer(first._replace(account_id=b["id"], id=first.id + 1)))
        # A higher score takes it.
        self.assertTrue(table.offer(first._replace(account_id=b["id"], dj_name=b["dj_name"], score=first.score + 1,
                                                   played_at=102, id=first.id + 2)))
        self.assertEqual(table.top(first.mode, first.song, first.pattern).dj_name, b["dj_name"])

    def test_the_table_is_built_again_only_when_the_database_changed_elsewhere(self):
        table = firsts.FirstPlaces(self.records)
        for _ in range(20):
            self.play()
        table.places()
        self.assertEqual(table.builds, 1)
        # The game server's own play, followed: no build.
        before = self.db.total_changes
        table.offer(self.play())
        table.follow(before)
        table.places()
        self.assertEqual(table.builds, 1)
        # A cabinet's session, the game server's own too: no build.
        before = self.db.total_changes
        self.db.execute("INSERT INTO sessions (cabinet, account_id, started_at) VALUES ('c', ?, 0)",
                        (self.players[0]["id"],))
        table.follow(before)
        table.places()
        self.assertEqual(table.builds, 1)
        # Another connection's commit (the site renames a player): built again, once.
        other = db.connect(self.path)
        try:
            accounts.Accounts(other).set_dj_name(self.players[3]["login_id"], "OTHER")
        finally:
            other.close()
        table.places()
        table.places()
        self.assertEqual(table.builds, 2)
        # A write on its own connection it was not told of: built again.
        self.play()
        table.places()
        self.assertEqual(table.builds, 3)
        self.assertEqual(self.kept(table.places()), self.window())

    def test_the_walk_costs_charts_not_plays(self):
        # 3,000 plays and 30,000 of the same charts: the walk takes about as long for both (it looks at each chart's
        # first entry), where the window function read every play. Timed loosely: a busy PC may slow either.
        def timed(fn):
            started = time.perf_counter()
            fn()
            return time.perf_counter() - started

        def fill(n):
            rows = [(self.rng.choice(self.players)["id"], "x", self.rng.randint(0, 2), self.rng.randint(1, 30),
                     self.rng.randint(1, 4), self.rng.randint(1, 300000), "", bytes(47), 1_700_000_000 + i)
                    for i in range(n)]
            self.db.execute("BEGIN")
            self.db.executemany("INSERT INTO plays (account_id, cabinet, mode, song, pattern, score, counts, record,"
                                " played_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
            self.db.execute("COMMIT")
        fill(3000)
        small = min(timed(self.records.first_places) for _ in range(5))
        fill(27000)
        large = min(timed(self.records.first_places) for _ in range(5))
        window = min(timed(lambda: self.db.execute(WINDOW).fetchall()) for _ in range(3))
        self.assertEqual([tuple(r)[:5] for r in self.records.first_places()], self.window())
        # Ten times the plays: the walk well under ten times as long, and faster than the window function.
        self.assertLess(large, small * 5 + 0.005, "walk %.1f ms on 3,000 plays, %.1f ms on 30,000"
                        % (small * 1000, large * 1000))
        self.assertLess(large, window, "walk %.1f ms, window function %.1f ms" % (large * 1000, window * 1000))


if __name__ == "__main__":
    unittest.main()
