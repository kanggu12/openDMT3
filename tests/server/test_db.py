"""TS-DB-05: a database from an older openDMT3 is brought up to this version on open, with a copy of it kept first
and every account and play still there; a database from a newer openDMT3 is refused, untouched."""

import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

from opendmt3.server import db


def older(path, version):
    """A database as openDMT3 left it at `version` (its first steps only), with one account and one play."""
    connection = sqlite3.connect(path, isolation_level=None)
    for number in range(version):
        for statement in db.STEPS[number]:
            connection.execute(statement)
    connection.execute("PRAGMA user_version=%d" % version)
    connection.execute("INSERT INTO accounts (login_id, password, dj_name, card, created_at)"
                       " VALUES ('NOVA', 'x', 'DJ NOVA', '12345678901234567890', 1)")
    if version >= 2:
        connection.execute("INSERT INTO plays (account_id, cabinet, mode, song, pattern, score, counts, record,"
                           " played_at) VALUES (1, '198.51.100.7:5000', 0, 56, 1, 4530, '0,0,0,0,0,0,0', x'00', 2)")
    connection.close()


class MigrationTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "openDMT3.sqlite")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_many_connections_opening_an_older_database_at_once_bring_it_up_once(self):
        # The site opens a connection for each request on several threads: right after an older backup is put back,
        # many may find the older version at once. Each step runs once, under the write lock, and every one opens.
        import threading
        older(self.path, db.VERSION - 1)
        failures, barrier = [], threading.Barrier(8)

        def open_it():
            barrier.wait()
            try:
                db.connect(self.path).close()
            except Exception as e:  # noqa: BLE001  (any failure is the test's answer)
                failures.append(repr(e))
        copies_made = []
        real_connect = sqlite3.connect

        def counted(path, *args, **kwargs):
            # Every copy made before an upgrade (a connection to a .bak file).
            if str(path).endswith(".bak"):
                copies_made.append(path)
            return real_connect(path, *args, **kwargs)
        threads = [threading.Thread(target=open_it) for _ in range(8)]
        with mock.patch.object(sqlite3, "connect", counted):
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(failures, [])
        # Copied once, by the connection that upgraded: the others found it done (each copied all of it before).
        self.assertEqual(len(copies_made), 1)
        connection = sqlite3.connect(self.path)
        try:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], db.VERSION)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM plays").fetchone()[0], 1)
        finally:
            connection.close()
        # One copy made before the upgrade, by the one that upgraded, whole and of the older version.
        copies = [n for n in os.listdir(self.tmp) if n.endswith(".bak")]
        self.assertEqual(len(copies), 1)
        copy = sqlite3.connect(os.path.join(self.tmp, copies[0]))
        try:
            self.assertEqual(copy.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(copy.execute("PRAGMA user_version").fetchone()[0], db.VERSION - 1)
        finally:
            copy.close()

    def test_every_older_version_comes_up_with_a_copy_kept_first(self):
        for version in range(1, db.VERSION):
            with self.subTest(version=version):
                for name in os.listdir(self.tmp):
                    os.remove(os.path.join(self.tmp, name))
                older(self.path, version)
                connection = db.connect(self.path)
                try:
                    self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], db.VERSION)
                    self.assertEqual(connection.execute("SELECT dj_name FROM accounts").fetchone()[0], "DJ NOVA")
                    plays = connection.execute("SELECT score, session_id FROM plays").fetchall()
                    self.assertEqual([tuple(p) for p in plays], [(4530, None)] if version >= 2 else [])
                    # The later steps' tables are there, and the account has the DJ card a new one starts with.
                    connection.execute("SELECT COUNT(*) FROM sessions").fetchone()
                    card = connection.execute("SELECT icon, plate, pattern, comment FROM accounts").fetchone()
                    self.assertEqual(tuple(card), (1, 32769, 0, ""))
                    # Step 6: the API's tokens ended before their time, none yet, kept by id until they expire,
                    # and the account's go with it.
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM revoked_tokens").fetchone()[0], 0)
                    connection.execute("INSERT INTO revoked_tokens (id, account_id, expires) VALUES ('t', 1, 2)")
                    # Step 7: the API's named tokens, none yet, kept by a hash, and the account's go with it.
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM api_tokens").fetchone()[0], 0)
                    connection.execute("INSERT INTO api_tokens (id, account_id, name, scope, hash, created_at)"
                                       " VALUES ('0123456789ab', 1, 'bot', 'read', 'h', 1)")
                    connection.execute("DELETE FROM accounts")
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM revoked_tokens").fetchone()[0], 0)
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM api_tokens").fetchone()[0], 0)
                finally:
                    connection.close()
                kept = [n for n in os.listdir(self.tmp) if n.startswith("openDMT3.sqlite.v%d-" % version)]
                self.assertEqual(len(kept), 1, os.listdir(self.tmp))
                # The copy is the old database as it was.
                copy = sqlite3.connect(os.path.join(self.tmp, kept[0]))
                try:
                    self.assertEqual(copy.execute("PRAGMA user_version").fetchone()[0], version)
                finally:
                    copy.close()

    @unittest.skipIf(os.name == "nt", "file modes are Linux's and macOS's")
    def test_the_copy_kept_before_an_upgrade_is_its_owners_only(self):
        # A umask that would let everyone read new files: the copy holds the card numbers, so it is made 0600.
        saved = os.umask(0o022)
        try:
            older(self.path, db.VERSION - 1)
            db.connect(self.path).close()
        finally:
            os.umask(saved)
        kept = [n for n in os.listdir(self.tmp) if n.endswith(".bak")]
        self.assertEqual(len(kept), 1, os.listdir(self.tmp))
        self.assertEqual(os.stat(os.path.join(self.tmp, kept[0])).st_mode & 0o777, 0o600)

    def test_every_account_starts_in_round_zero_of_its_sign_ins(self):
        # Cookies made before the step carry no round: they count as round 0 and stay signed in. The database is the
        # one from right before step 5, which adds the round.
        older(self.path, 4)
        connection = db.connect(self.path)
        try:
            self.assertEqual(connection.execute("SELECT session_generation FROM accounts").fetchone()[0], 0)
        finally:
            connection.close()

    def test_a_newer_database_is_refused_and_left_alone(self):
        older(self.path, 1)
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA user_version=%d" % (db.VERSION + 1))
        connection.close()
        with open(self.path, "rb") as f:
            before = f.read()
        with self.assertRaises(db.DatabaseError):
            db.connect(self.path)
        with open(self.path, "rb") as f:
            self.assertEqual(f.read(), before)


if __name__ == "__main__":
    unittest.main()
