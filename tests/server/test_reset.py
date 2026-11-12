"""Tests for resetting plays (OpenDMTQ's 초기화): every play, or one player's, from the admin's Players tab and through
the API. The database is backed up first, the page asks first in the site's own dialog, the change log says it, and
accounts, DJ cards and settings stay.

They need the web libraries (Starlette, Jinja2, httpx for the test client); without them they are skipped.
"""

import html.parser
import os
import sqlite3
import unittest

# The API's calls with a token, the site's forms and plays put in as the game server puts them (tests/server/test_api.py).
from tests.server.test_api import ApiBase
from tests.server.test_web import WEB


def asking_forms(page):
    """The forms of a page that ask first in the site's own dialog (static/site.js), each as its attributes."""
    found = []

    class Forms(html.parser.HTMLParser):
        def handle_starttag(self, tag, attrs):
            # A form that carries its question asks before it is sent.
            if tag == "form" and dict(attrs).get("data-ask"):
                found.append(dict(attrs))

    Forms().feed(page)
    return found


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class ResetPlaysTest(ApiBase):
    """The Players tab's Reset plays and Reset every play, and their API twins."""

    def plays_of(self, account=None):
        """How many plays the database holds: one account's, or everyone's."""
        from opendmt3.server import db
        connection = db.connect(self.site.db_path)
        try:
            if account is None:
                return connection.execute("SELECT COUNT(*) FROM plays").fetchone()[0]
            return connection.execute("SELECT COUNT(*) FROM plays WHERE account_id = ?", (account["id"],)).fetchone()[0]
        finally:
            connection.close()

    def plays_in(self, name):
        """How many plays a backup holds, read from its file."""
        connection = sqlite3.connect(os.path.join(self.tmp, "backups", name))
        try:
            return connection.execute("SELECT COUNT(*) FROM plays").fetchone()[0]
        finally:
            connection.close()

    def three_players(self):
        """BOSS (the admin, signed in on the page), NOVA with two plays and a DJ card comment, RIO with one."""
        self.admin()
        nova, rio = self.make(), self.make("RIO", dj="RIO")
        store = self.site.accounts()
        try:
            # A DJ card comment, which must stay (no card tables needed for a comment).
            store.set_card("NOVA", {}, comment="HELLO")
        finally:
            store.db.close()
        self.play(nova, 1, 1, 500, at=1000)
        self.play(nova, 1, 2, 600, at=2000)
        self.play(rio, 1, 1, 700, at=3000)
        return nova, rio

    def test_the_players_tab_asks_first_in_the_sites_own_dialog(self):
        self.three_players()
        page = self.client.get("/admin/players").text
        resets = [form for form in asking_forms(page) if form["data-ask-yes"] == "Reset plays"]
        # One for each player (the admin's own too) and one for every play.
        self.assertEqual(sorted(form["data-ask"] for form in resets),
                         ["Reset BOSS's plays?", "Reset NOVA's plays?", "Reset RIO's plays?",
                          "Reset every player's plays?"])
        for form in resets:
            # Each question has its title and what goes and stays, in the site's own dialog: no browser box.
            self.assertTrue(form["data-ask-title"] and "backed up first" in form["data-ask-detail"], form)
        self.assertNotIn("confirm(", page)
        # Korean says the same, with 초기화.
        self.client.cookies.set("opendmt3_lang", "ko")
        page = self.client.get("/admin/players").text
        self.assertIn("NOVA의 플레이 기록을 초기화할까요?", [form["data-ask"] for form in asking_forms(page)])

    def test_one_players_plays_go_after_a_backup_and_the_rest_stays(self):
        from opendmt3.server.services import backups
        nova, rio = self.three_players()
        token = self.form_token(self.client, "/admin/players")
        # Another site's form (no token): nothing goes, and no backup is made.
        self.client.post("/admin/players", data={"action": "reset_plays", "login_id": "NOVA"})
        self.assertEqual((self.plays_of(nova), backups.all_backups(self.tmp)), (2, []))
        page = self.client.post("/admin/players", data={"csrf": token, "action": "reset_plays",
                                                        "login_id": "NOVA"}).text
        # NOVA's two plays went, RIO's stayed.
        self.assertEqual((self.plays_of(nova), self.plays_of(rio)), (0, 1))
        made = backups.all_backups(self.tmp)
        # The backup made first, of its own kind, holds every play as it was.
        self.assertEqual([b["kind"] for b in made], ["reset"])
        self.assertEqual(self.plays_in(made[0]["name"]), 3)
        self.assertIn("NOVA&#39;s plays are reset (cleared stages gone: 2). The database as it was is backed up as %s."
                      % made[0]["name"], page)
        self.assertEqual(self.changes()[0], "reset the plays of NOVA: 2 gone, backed up as %s" % made[0]["name"])
        # The account, its DJ name and its card stay, and it still signs in.
        store = self.site.accounts()
        try:
            row = store.by_login("NOVA")
        finally:
            store.db.close()
        self.assertEqual((row["dj_name"], row["comment"], row["card"]), ("DJ NOVA", "HELLO", nova["card"]))
        self.token("NOVA")
        # The Backups tab names the new kind.
        self.assertIn("Before a reset", self.client.get("/admin/backups").text)
        # A restore of the backup brings the plays back.
        backups.restore(self.site.db_path, self.tmp, made[0]["name"])
        self.assertEqual(self.plays_of(nova), 2)

    def test_every_play_goes_after_a_backup(self):
        from opendmt3.server.services import backups
        nova, rio = self.three_players()
        token = self.form_token(self.client, "/admin/players")
        page = self.client.post("/admin/players", data={"csrf": token, "action": "reset_all"}).text
        self.assertEqual(self.plays_of(), 0)
        made = backups.all_backups(self.tmp)
        self.assertEqual(([b["kind"] for b in made], self.plays_in(made[0]["name"])), (["reset"], 3))
        self.assertIn("Every play is reset (cleared stages gone: 3).", page)
        self.assertEqual(self.changes()[0], "reset every play: 3 gone, backed up as %s" % made[0]["name"])
        # Every account stays; the rankings start again.
        self.assertEqual(len(self.call("GET", "/api/v1/players", self.token("BOSS")).json()["players"]), 3)
        self.assertEqual(self.call("GET", "/api/v1/rankings", self.token("BOSS")).json()["rows"], [])

    def test_an_unknown_id_resets_nothing_and_makes_no_backup(self):
        from opendmt3.server.services import backups
        nova, _ = self.three_players()
        token = self.form_token(self.client, "/admin/players")
        self.client.post("/admin/players", data={"csrf": token, "action": "reset_plays", "login_id": "NOBODY"})
        self.assertEqual((self.plays_of(), backups.all_backups(self.tmp)), (3, []))

    def test_the_api_resets_one_player_or_everyone_for_admins_only(self):
        from opendmt3.server.services import backups
        nova, rio = self.three_players()
        boss, player = self.token("BOSS"), self.token("NOVA")
        # Who may: nobody without a token, no player; an unknown ID is told.
        self.refused(self.call("DELETE", "/api/v1/players/NOVA/plays"), 401, "sign_in")
        self.refused(self.call("DELETE", "/api/v1/players/NOVA/plays", player), 403, "admin_only")
        self.refused(self.call("DELETE", "/api/v1/plays"), 401, "sign_in")
        self.refused(self.call("DELETE", "/api/v1/plays", player), 403, "admin_only")
        self.refused(self.call("DELETE", "/api/v1/players/NOBODY/plays", boss), 404, "unknown_player")
        # Nothing went, and no backup was made, for any of those.
        self.assertEqual((self.plays_of(), backups.all_backups(self.tmp)), (3, []))
        answer = self.call("DELETE", "/api/v1/players/nova/plays", boss).json()
        self.assertEqual((answer["login_id"], answer["plays"]), ("NOVA", 2))
        self.assertEqual(self.plays_in(answer["kept_as"]), 3)
        self.assertEqual((self.plays_of(nova), self.plays_of(rio)), (0, 1))
        self.assertEqual(self.changes()[0], "reset the plays of NOVA: 2 gone, backed up as %s" % answer["kept_as"])
        every = self.call("DELETE", "/api/v1/plays", boss).json()
        self.assertEqual((every["plays"], self.plays_of(), self.plays_in(every["kept_as"])), (1, 0, 1))
        self.assertEqual(self.changes()[0], "reset every play: 1 gone, backed up as %s" % every["kept_as"])
        # Reading the plays is as it was: a player's token reads, and a HEAD deletes nothing.
        self.play(nova, 2, 1, 900)
        self.assertEqual(self.call("HEAD", "/api/v1/plays", player).status_code, 200)
        self.assertEqual(self.call("GET", "/api/v1/plays", player).json()["total"], 1)

    def test_a_backup_that_cannot_be_made_resets_nothing(self):
        from unittest import mock
        from opendmt3.server.services import backups
        self.three_players()
        # The backups folder cannot be written (a full disk, say): the reset stops before any play goes, and the
        # failure is in the server's log with its reason.
        token = self.token("BOSS")
        with mock.patch.object(backups, "make", side_effect=OSError(28, "No space left on device")):
            with self.assertLogs("opendmt3.web", level="ERROR") as logs:
                r = self.call("DELETE", "/api/v1/plays", token)
        self.refused(r, 500, "server_error")
        self.assertIn("No space left on device", "\n".join(logs.output))
        self.assertEqual(self.plays_of(), 3)
        self.assertNotIn("reset every play", " ".join(self.changes()))


if __name__ == "__main__":
    unittest.main()
