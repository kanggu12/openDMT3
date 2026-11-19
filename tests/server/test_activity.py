"""Tests for services/activity.py: cabinets by address, play sessions, the admin's numbers and a DJ's weeks."""

import os
import shutil
import tempfile
import time
import unittest

from opendmt3.server import db
from opendmt3.server.services import accounts, activity, records


class ActivityTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = db.connect(os.path.join(self.tmp, "server.sqlite"))
        self.accounts = accounts.Accounts(self.db)
        self.nova = self.accounts.create("NOVA", "pass1234", "DJ NOVA")
        self.act = activity.Activity(self.db)
        self.plays = records.Records(self.db)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)

    def play(self, session, at, song=1, mode=0):
        self.plays.add(self.nova["id"], "198.51.100.7:5000", mode, {"song": song, "pattern": 1, "score": 500000,
                                                                     "counts": [0] * 7, "raw": bytes(47)},
                       at=at, session_id=session)

    def test_a_cabinet_keeps_its_name_as_it_comes_back(self):
        self.act.seen("198.51.100.7", "1.0", "198.51.100.7:5000", at=100)
        cabinet = self.act.cabinets()[0]
        self.assertTrue(self.act.rename_cabinet(cabinet["id"], "  Living room  "))
        self.act.seen("198.51.100.7", "1.1", "198.51.100.7:6000", at=200)
        again = self.act.cabinets()
        self.assertEqual(len(again), 1)
        self.assertEqual((again[0]["name"], again[0]["version"], again[0]["first_seen"], again[0]["last_seen"]),
                         ("Living room", "1.1", 100, 200))
        # An empty name goes back to the address; a cabinet that is not there is said so.
        self.assertTrue(self.act.rename_cabinet(cabinet["id"], ""))
        self.assertIsNone(self.act.cabinets()[0]["name"])
        self.assertFalse(self.act.rename_cabinet(999, "x"))

    def test_sessions_count_their_time_and_their_stages(self):
        # Noon of today, not the clock: ten minutes before "now" must still be today, also just after midnight.
        now = activity._day_start(time.time()) + 12 * 3600
        self.act.seen("198.51.100.7", "1.0", "198.51.100.7:5000", at=now - 600)
        session = self.act.start("198.51.100.7", self.nova["id"], at=now - 600)
        self.play(session, now - 300)
        self.play(session, now - 200, song=2, mode=1)
        self.act.end(session, "198.51.100.7", at=now - 60)
        cabinet = self.act.cabinets()[0]
        self.assertEqual((cabinet["sessions"], cabinet["plays"]), (1, 2))
        mine = self.act.dj(self.nova["id"], now=now)
        self.assertEqual((mine["sessions"], mine["seconds"]), (1, 540))
        self.assertEqual(mine["weeks"][-1], 2)
        self.assertEqual(sum(mine["weeks"]), 2)
        self.assertEqual(mine["modes"], {0: 1, 1: 1})
        status = self.act.status(now=now)
        self.assertEqual((status["today"]["plays"], status["today"]["players"], status["today"]["sessions"]), (2, 1, 1))
        self.assertEqual(status["month"]["seconds"], 540)

    def test_weeks_end_today_and_older_plays_fall_out(self):
        now = time.time()
        self.play(None, now - 8 * activity.DAY)          # last week's bucket
        self.play(None, now - 100 * activity.DAY)        # older than twelve weeks
        weeks = self.act.dj(self.nova["id"], now=now)["weeks"]
        self.assertEqual(len(weeks), 12)
        self.assertEqual(weeks[-2], 1)
        self.assertEqual(sum(weeks), 1)

    def test_the_numbers_of_the_day_week_and_month_read_their_own_plays_not_the_whole_history(self):
        # The admin's Status and Server pages ask for these on every visit: they read the whole history's index for
        # each stretch (50 ms a visit on 300,000 plays, more as the history grows) where the stretch's own plays and
        # sessions are a range of an index on their time. Counted in SQLite's own steps (a progress handler called
        # every 1,000 of them), whatever this PC's speed: 20,000 plays of half a year ago, 10 of today.
        now = activity._day_start(time.time()) + 12 * 3600
        old = now - 180 * activity.DAY
        # In one transaction: one write of the file, not one each.
        with db.immediate(self.db):
            self.db.executemany(
                "INSERT INTO plays (account_id, cabinet, mode, song, pattern, score, counts, record, played_at)"
                " VALUES (?, 'x', 0, 1, 1, 1, '0,0,0,0,0,0,0', x'00', ?)",
                [(self.nova["id"], old + i) for i in range(20000)]
                + [(self.nova["id"], now - 60 - i) for i in range(10)])
            self.db.executemany(
                "INSERT INTO sessions (cabinet, account_id, started_at, ended_at) VALUES ('x', ?, ?, ?)",
                [(self.nova["id"], old + i, old + i + 60) for i in range(5000)]
                + [(self.nova["id"], now - 600 - i, now - 300) for i in range(5)])
        steps = [0]

        def counted():
            steps[0] += 1
            # Go on (a true value would stop the statement).
            return 0
        self.db.set_progress_handler(counted, 1000)
        try:
            status = self.act.status(now=now)
        finally:
            self.db.set_progress_handler(None, 1000)
        self.assertEqual((status["today"]["plays"], status["week"]["plays"], status["month"]["plays"]), (10, 10, 10))
        self.assertEqual((status["today"]["sessions"], status["month"]["seconds"]), (5, sum(300 + i for i in range(5))))
        # Reading the 20,000 plays' index three times took 150 thousand steps and more here; the stretches' own
        # entries take a few hundred.
        self.assertLess(steps[0], 20, "%d thousand steps for the numbers" % steps[0])

    def test_a_session_a_stopped_server_left_open_is_closed_at_its_start(self):
        session = self.act.start("198.51.100.7", self.nova["id"], at=1000)
        self.act.close_left_open()
        row = self.db.execute("SELECT started_at, ended_at FROM sessions WHERE id = ?", (session,)).fetchone()
        self.assertEqual(tuple(row), (1000, 1000))


if __name__ == "__main__":
    unittest.main()
