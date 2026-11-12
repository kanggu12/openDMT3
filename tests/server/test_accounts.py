"""Tests for the database steps and the accounts: what the game sends at login, and the site's sign-in."""

import hashlib
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

from opendmt3.server import db
from opendmt3.server.services import accounts


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "server.sqlite")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_new_database_has_every_step(self):
        conn = db.connect(self.path)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], db.VERSION)
        conn.close()
        # Opening again runs nothing and keeps no copy (nothing changed).
        db.connect(self.path).close()
        self.assertEqual([n for n in os.listdir(self.tmp) if n.endswith(".bak")], [])

    def test_a_newer_database_is_refused(self):
        raw = sqlite3.connect(self.path)
        raw.execute("PRAGMA user_version=%d" % (db.VERSION + 1))
        raw.close()
        with self.assertRaises(db.DatabaseError):
            db.connect(self.path)


class AccountsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = db.connect(os.path.join(self.tmp, "server.sqlite"))
        self.accounts = accounts.Accounts(self.db)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)

    def test_the_game_login_takes_the_md5_the_game_sends(self):
        self.accounts.create("NOVA", "pass1234", "DJNOVA")
        digest = hashlib.md5(b"pass1234").hexdigest()
        code, row = self.accounts.check_game("NOVA", digest)
        self.assertEqual((code, row["dj_name"]), ("ok", "DJNOVA"))
        # Upper-case hex is the same password.
        self.assertEqual(self.accounts.check_game("NOVA", digest.upper())[0], "ok")
        self.assertEqual(self.accounts.check_game("NOVA", hashlib.md5(b"other").hexdigest())[0], "wrong_password")
        self.assertEqual(self.accounts.check_game("NOBODY", digest)[0], "unknown")

    def test_ids_ignore_case_and_are_unique(self):
        self.accounts.create("Nova", "pass1234")
        self.assertIsNotNone(self.accounts.by_login("NOVA"))
        with self.assertRaises(accounts.AccountError):
            self.accounts.create("nova", "pass5678")

    def test_the_site_sign_in_uses_the_same_secret(self):
        self.accounts.create("MINHO", "abcd12")
        self.assertIsNotNone(self.accounts.check_web("minho", "abcd12"))
        self.assertIsNone(self.accounts.check_web("minho", "abce12"))
        self.accounts.set_disabled("MINHO", True)
        self.assertIsNone(self.accounts.check_web("minho", "abcd12"))
        self.assertEqual(self.accounts.check_game("MINHO", accounts.game_digest("abcd12"))[0], "disabled")

    def test_a_new_password_is_six_letters_or_more_and_an_old_shorter_one_still_signs_in(self):
        # Six, as the sister project asks; five is refused for a new account and for a new password.
        for short in ("abcde", "a1b2c"):
            with self.assertRaises(accounts.AccountError, msg=short):
                self.accounts.create("NOVA", short)
        self.accounts.create("NOVA", "abcdef")
        with self.assertRaises(accounts.AccountError):
            self.accounts.set_password("NOVA", "abc12")
        # An account made when four letters were enough (its hash as that version stored it) keeps signing in.
        self.db.execute("INSERT INTO accounts (login_id, password, dj_name, card, created_at) VALUES (?, ?, ?, ?, ?)",
                        ("OLDIE", accounts._hash(accounts.game_digest("abcd")), "OLDIE", "1" * 20, 1))
        self.assertIsNotNone(self.accounts.check_web("OLDIE", "abcd"))

    def test_the_stored_secret_is_not_the_password_or_its_md5(self):
        row = self.accounts.create("NOVA", "pass1234")
        self.assertNotIn("pass1234", row["password"])
        self.assertNotIn(accounts.game_digest("pass1234"), row["password"])

    def test_rules_follow_the_keypad(self):
        for bad_id in ("", "TOOLONGID", "nova!", "강"):
            with self.assertRaises(accounts.AccountError, msg=bad_id):
                self.accounts.create(bad_id, "pass1234")
        for bad_password in ("abc", "abcde", "x" * 17, "pass word", "비밀번호1"):
            with self.assertRaises(accounts.AccountError, msg=bad_password):
                self.accounts.create("NOVA", bad_password)

    def test_each_account_gets_its_own_card(self):
        a = self.accounts.create("A1", "pass1234")
        b = self.accounts.create("B1", "pass1234")
        self.assertEqual(len(a["card"]), accounts.CARD_DIGITS)
        self.assertNotEqual(a["card"], b["card"])
        self.assertEqual(self.accounts.by_card(b["card"])["login_id"], "B1")

    def test_dj_names_fit_the_games_field(self):
        # Eight places in UTF-16: an emoji takes two, so four of them fill it; control characters never fit.
        self.assertEqual(self.accounts.create("A1", "pass1234", "\U0001F3B5" * 4)["dj_name"], "\U0001F3B5" * 4)
        for bad in ("\U0001F3B5" * 5, "NINECHARS", "TAB\tNAME"):
            with self.assertRaises(accounts.AccountError, msg=repr(bad)):
                self.accounts.create("B1", "pass1234", bad)

    def test_an_unknown_id_costs_a_password_check_too(self):
        self.accounts.create("NOVA", "pass1234")
        with mock.patch.object(accounts, "_matches", wraps=accounts._matches) as matches:
            self.assertEqual(self.accounts.check_game("NOBODY", accounts.game_digest("pass1234"))[0], "unknown")
        self.assertEqual(matches.call_count, 1)

    def test_a_password_no_account_can_have_is_a_wrong_sign_in(self):
        self.accounts.create("NOVA", "pass1234")
        self.assertIsNone(self.accounts.check_web("NOVA", "비밀번호"))

    def test_a_new_password_gives_a_new_card(self):
        old = self.accounts.create("NOVA", "pass1234")["card"]
        self.accounts.set_password("NOVA", "newpass1")
        new = self.accounts.by_login("NOVA")["card"]
        self.assertNotEqual(new, old)
        self.assertIsNone(self.accounts.by_card(old))
        self.assertEqual(len(new), accounts.CARD_DIGITS)

    def test_changes_are_logged(self):
        self.accounts.create("NOVA", "pass1234", who="admin")
        self.accounts.set_password("NOVA", "newpass1", who="admin")
        what = [r["what"] for r in self.db.execute("SELECT what FROM changes ORDER BY id")]
        self.assertEqual(what, ["made the account NOVA", "set a new password (and card) for NOVA"])


if __name__ == "__main__":
    unittest.main()
