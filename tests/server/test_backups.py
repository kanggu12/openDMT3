"""Tests for the database's backups (services/backups.py) and their command-line twin.

A backup holds the database as it was when made; seven of each kind stay; a restore backs up first, can be
undone, and never loses the backup it reads; names from requests never reach outside backups/.
"""

import io
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

from opendmt3.server import db
from opendmt3.server.services import accounts, backups


class BackupsTest(unittest.TestCase):

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.path = os.path.join(self.data, "openDMT3.sqlite")
        connection = db.connect(self.path)
        accounts.Accounts(connection).create("NOVA", "pass1234", "DJ NOVA")
        connection.close()

    def tearDown(self):
        shutil.rmtree(self.data)

    def logins(self, path=None):
        connection = sqlite3.connect(path or self.path)
        try:
            return sorted(r[0] for r in connection.execute("SELECT login_id FROM accounts"))
        finally:
            connection.close()

    def add(self, login_id):
        connection = db.connect(self.path)
        try:
            accounts.Accounts(connection).create(login_id, "pass1234")
        finally:
            connection.close()

    def test_a_backup_holds_the_database_as_it_was(self):
        name = backups.make(self.path, self.data)
        self.add("RIO")
        listed = backups.all_backups(self.data)
        self.assertEqual([b["name"] for b in listed], [name])
        self.assertEqual(listed[0]["kind"], "manual")
        self.assertEqual(self.logins(os.path.join(self.data, "backups", name)), ["NOVA"])
        # Nothing half-written is left beside it.
        self.assertEqual(os.listdir(os.path.join(self.data, "backups")), [name])

    @unittest.skipIf(os.name == "nt", "file modes are POSIX")
    def test_the_database_and_its_backups_are_their_owners_alone(self):
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        name = backups.make(self.path, self.data)
        self.assertEqual(os.stat(os.path.join(self.data, "backups", name)).st_mode & 0o777, 0o600)

    def test_backups_made_and_uploaded_at_the_same_moment_each_get_their_own_file(self):
        # The site's threads, its long work's and the daily backup's may make backups at once (two admins, a restore's
        # first backup, the day's): each must get a name of its own and a whole copy, none lost or half-written.
        import threading
        self.add("RIO")
        moment, results, failures = time.time(), [], []
        # Six made and two uploaded: fewer than KEEP of each kind, so the uploads' pruning removes none of them.
        barrier = threading.Barrier(8)
        uploads = []
        for k in range(2):
            # Two uploaded backups (whole copies of the database) waiting to be kept at the same moment.
            part = os.path.join(self.data, "backups", ".upload-%d.part" % k)
            os.makedirs(os.path.dirname(part), exist_ok=True)
            source, copy = sqlite3.connect(self.path), sqlite3.connect(part)
            source.backup(copy)
            copy.close()
            source.close()
            uploads.append(part)

        def make():
            barrier.wait()
            try:
                results.append(backups.make(self.path, self.data, "manual", now=moment, tidy=False))
            except Exception as e:  # noqa: BLE001  (any failure is the test's answer)
                failures.append(repr(e))

        def upload(part):
            barrier.wait()
            try:
                results.append(backups.keep_upload(self.data, part, now=moment))
            except Exception as e:  # noqa: BLE001
                failures.append(repr(e))
        threads = [threading.Thread(target=make) for _ in range(6)]
        threads += [threading.Thread(target=upload, args=(part,)) for part in uploads]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(failures, [])
        # Eight names, each a whole copy with every account, and nothing half-written beside them.
        self.assertEqual(len(set(results)), 8)
        self.assertEqual(sorted(os.listdir(os.path.join(self.data, "backups"))), sorted(results))
        for name in results:
            path = os.path.join(self.data, "backups", name)
            self.assertEqual(self.logins(path), ["NOVA", "RIO"])
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            finally:
                connection.close()

    def test_the_list_never_fails_on_a_backup_removed_while_it_looks(self):
        # A backup pruned or deleted between the folder's listing and the look at its size is left out, not a failure.
        names = [backups.make(self.path, self.data, "manual", now=1_800_000_000 + n) for n in range(3)]
        real = os.path.getsize

        def gone_meanwhile(path):
            if path.endswith(names[1]):
                raise FileNotFoundError(path)
            return real(path)
        with mock.patch.object(backups.os.path, "getsize", gone_meanwhile):
            listed = [b["name"] for b in backups.all_backups(self.data)]
        self.assertEqual(listed, [names[2], names[0]])

    def test_seven_of_each_kind_stay(self):
        start = time.mktime((2026, 11, 1, 12, 0, 0, 0, 0, -1))
        for day in range(9):
            backups.make(self.path, self.data, "daily", now=start + day * backups.DAY)
        backups.make(self.path, self.data, "manual", now=start)
        kinds = [b["kind"] for b in backups.all_backups(self.data)]
        self.assertEqual(kinds.count("daily"), backups.KEEP)
        self.assertEqual(kinds.count("manual"), 1)
        # The two oldest daily ones went.
        days = sorted(b["at"] for b in backups.all_backups(self.data) if b["kind"] == "daily")
        self.assertEqual(days[0], start + 2 * backups.DAY)

    def test_the_daily_backup_comes_once_a_day(self):
        now = time.time()
        self.assertIsNotNone(backups.daily(self.path, self.data, now=now))
        self.assertIsNone(backups.daily(self.path, self.data, now=now + backups.DAY - 60))
        self.assertIsNotNone(backups.daily(self.path, self.data, now=now + backups.DAY + 60))

    def test_a_restore_backs_up_first_and_can_be_undone(self):
        before = backups.make(self.path, self.data)
        self.add("RIO")
        safety = backups.restore(self.path, self.data, before)
        self.assertEqual(self.logins(), ["NOVA"])
        self.assertTrue(safety.endswith("-restore.sqlite"))
        # Undone: back to the database with RIO.
        backups.restore(self.path, self.data, safety)
        self.assertEqual(self.logins(), ["NOVA", "RIO"])
        # The restored database is this openDMT3's version and still opens.
        db.connect(self.path).close()

    def test_restoring_the_oldest_backup_of_a_kind_keeps_it_until_read(self):
        start = time.mktime((2026, 11, 1, 12, 0, 0, 0, 0, -1))
        for n in range(backups.KEEP):
            backups.make(self.path, self.data, "restore", now=start + n)
            self.add("P%d" % n)
        oldest = backups.all_backups(self.data)[-1]["name"]
        # The safety backup would push the oldest "restore" out: the restore must read it first.
        backups.restore(self.path, self.data, oldest)
        self.assertEqual(self.logins(), ["NOVA"])
        self.assertEqual(len([b for b in backups.all_backups(self.data) if b["kind"] == "restore"]), backups.KEEP)

    def test_names_never_reach_outside_the_backups_folder(self):
        backups.make(self.path, self.data)
        for name in ("../openDMT3.sqlite", "openDMT3.sqlite", "openDMT3-20261101-120000-manual.sqlite", "",
                     "/etc/passwd", "openDMT3-20261101-120000-manual.sqlite/../../x"):
            with self.assertRaises(backups.BackupError, msg=name):
                backups.path_of(self.data, name)

    def test_a_backup_from_a_newer_openDMT3_is_refused(self):
        name = backups.make(self.path, self.data)
        connection = sqlite3.connect(os.path.join(self.data, "backups", name))
        connection.execute("PRAGMA user_version=%d" % (db.VERSION + 1))
        connection.close()
        with self.assertRaises(backups.BackupError) as e:
            backups.restore(self.path, self.data, name)
        self.assertEqual(e.exception.key, "error.backup.newer")
        self.assertEqual(self.logins(), ["NOVA"])

    def test_the_command_line_does_what_the_admin_page_does(self):
        from opendmt3.server import __main__ as server
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(server.main(["--data", self.data, "--backup"]), 0)
        name = out.getvalue().split()[-1]
        self.add("RIO")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(server.main(["--data", self.data, "--backups"]), 0)
        self.assertIn(name, out.getvalue())
        with redirect_stdout(io.StringIO()):
            self.assertEqual(server.main(["--data", self.data, "--restore", name]), 0)
        self.assertEqual(self.logins(), ["NOVA"])
        with mock.patch("sys.stderr", io.StringIO()) as err:
            self.assertEqual(server.main(["--data", self.data, "--restore", "nothing.sqlite"]), 2)
        self.assertIn("no backup named", err.getvalue())


if __name__ == "__main__":
    unittest.main()
