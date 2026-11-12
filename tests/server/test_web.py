"""Tests for the server's site and API: the sign-in wall, the owner's first account, the admin pages, the API
the launcher uses, and that a new password ends the old sign-ins and tokens.

They need the web libraries (Starlette, Jinja2, httpx for the test client); without them they are skipped.
"""

import importlib.util
import json
import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

WEB = all(importlib.util.find_spec(m) for m in ("starlette", "jinja2", "httpx", "multipart"))


class WebBase(unittest.TestCase):
    """A site on a temporary data folder, a visitor from another PC and one on the server PC."""

    def setUp(self):
        from starlette.testclient import TestClient
        from opendmt3.server.web.app import Site, create_app
        self.tmp = tempfile.mkdtemp()
        self.site = Site(self.tmp)
        self.app = create_app(self.site)
        # A visitor from another PC, and one on the server PC itself (the owner's page is for this PC only, at
        # this PC's own name).
        self.client = TestClient(self.app, client=("203.0.113.5", 50000))
        self.local = TestClient(self.app, base_url="http://127.0.0.1:4730", client=("127.0.0.1", 50001))
        # The Song list tab looks through the server PC's usual places: in a test, only the game folder the test gives
        # it (never this PC's own Downloads, which may hold anything, large archives included).
        from unittest import mock
        from opendmt3.server.services import sources
        places = mock.patch.object(sources, "places", lambda game_folder=None: [game_folder] if game_folder else [])
        places.start()
        self.addCleanup(places.stop)

    def tearDown(self):
        # The database's connections the test left for the garbage collector closed first: Windows will not remove a
        # file that is open.
        import gc
        gc.collect()
        shutil.rmtree(self.tmp)

    def make(self, login_id="NOVA", password="pass1234", dj="DJ NOVA", admin=False):
        store = self.site.accounts()
        try:
            return store.create(login_id, password, dj, is_admin=admin)
        finally:
            store.db.close()

    def signin_token(self, client):
        """The sign-in form's token, as a browser gets it with the page (and its cookie)."""
        page = client.get("/signin").text
        return page.split('name="csrf" value="', 1)[1].split('"', 1)[0]

    def sign_in(self, client, login_id="NOVA", password="pass1234", path="/signin"):
        """The site's sign-in form as a browser sends it: the page first, then the form with its token."""
        return client.post(path, data={"csrf": self.signin_token(client), "login_id": login_id, "password": password},
                           follow_redirects=False)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class WebTest(WebBase):

    # ------------------------------------------------------------------------------------- the wall

    def test_every_page_asks_for_a_sign_in_first(self):
        self.make()
        for path in ("/", "/download", "/admin/players", "/download/windows"):
            r = self.client.get(path, follow_redirects=False)
            self.assertEqual(r.status_code, 303, path)
            self.assertTrue(r.headers["location"].startswith("/signin?next="), path)
        # The sign-in page itself shows no names, no menu.
        page = self.client.get("/signin").text
        self.assertNotIn("DJ NOVA", page)
        self.assertNotIn('class="menu"', page)

    def owner_token(self, client):
        page = client.get("/owner").text
        return page.split('name="csrf" value="', 1)[1].split('"', 1)[0]

    def test_the_owner_page_only_from_this_pc_and_only_once(self):
        r = self.client.get("/owner", follow_redirects=False)
        self.assertEqual(r.headers["location"], "/signin")
        token = self.owner_token(self.local)
        r = self.local.post("/owner", data={"csrf": token, "login_id": "boss", "password": "pass1234",
                                            "dj_name": "BOSS"}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        store = self.site.accounts()
        row = store.by_login("BOSS")
        store.db.close()
        self.assertTrue(row["is_admin"])
        # Once an account exists the page is gone, even from this PC.
        self.assertEqual(self.local.get("/owner", follow_redirects=False).headers["location"], "/signin")

    def test_the_owner_form_needs_its_own_token(self):
        # As a page of another site would post it: no token from this page.
        r = self.local.post("/owner", data={"login_id": "evil", "password": "pass1234"}, follow_redirects=False)
        self.assertIn("expired", r.text)
        self.local.cookies.clear()
        r = self.local.post("/owner", data={"csrf": "made-up", "login_id": "evil", "password": "pass1234"})
        self.assertIn("expired", r.text)
        store = self.site.accounts()
        self.assertEqual(store.all(), [])
        store.db.close()

    def test_the_owner_page_is_not_shown_under_another_name(self):
        from starlette.testclient import TestClient
        # A page of another site whose name now points at this PC: the visit is from here, the name is not ours.
        rebound = TestClient(self.app, base_url="http://evil.example:4730", client=("127.0.0.1", 50002))
        self.assertEqual(rebound.get("/owner", follow_redirects=False).headers["location"], "/signin")

    def test_signing_out_needs_the_sites_own_form(self):
        self.make()
        self.sign_in(self.client)
        # Posted without the form's token (from another site): still signed in.
        self.client.post("/signout", follow_redirects=False)
        self.assertEqual(self.client.get("/", follow_redirects=False).status_code, 200)
        page = self.client.get("/").text
        token = page.split('name="csrf" value="', 1)[1].split('"', 1)[0]
        self.client.post("/signout", data={"csrf": token}, follow_redirects=False)
        self.assertEqual(self.client.get("/", follow_redirects=False).status_code, 303)

    def test_a_large_body_is_refused_before_it_is_read(self):
        from opendmt3.server.web import app as web_app
        big = "x" * (web_app.BODY_LIMIT + 1)
        self.assertEqual(self.client.post("/signin", data={"login_id": big}).status_code, 413)

        # The same without a length (sent in chunks).
        def chunks():
            for _ in range(5):
                yield b"x" * (web_app.BODY_LIMIT // 4)
        r = self.client.post("/api/v1/session", content=chunks(), headers={"content-type": "application/json"})
        self.assertEqual(r.status_code, 413)

    def test_wrong_requests_get_answers_not_errors(self):
        self.make()
        self.make("BOSS", admin=True)
        # A JSON list, not an object; a password no account can have; text that is not JSON.
        self.assertEqual(self.client.post("/api/v1/session", json=["NOVA"]).status_code, 400)
        self.assertEqual(self.client.post("/api/v1/session", json={"login_id": "NOVA", "password": "비밀"}).status_code,
                         401)
        boss = self.client.post("/api/v1/session", json={"login_id": "BOSS", "password": "pass1234"}).json()["token"]
        r = self.client.post("/api/v1/players", content=b"not json",
                             headers={"Authorization": "Bearer " + boss, "content-type": "application/json"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/v1/players", json={"login_id": "NEW1", "password": "pass1234", "dj_name": 5},
                             headers={"Authorization": "Bearer " + boss})
        self.assertEqual((r.status_code, r.json()["dj_name"]), (201, "5"))

    def test_old_wrong_passwords_are_forgotten(self):
        from opendmt3.server.web import app as web_app
        self.site.failed("203.0.113.9")
        self.site.failures["203.0.113.9"][0] -= web_app.WINDOW + 1
        self.assertFalse(self.site.too_many("203.0.113.9"))
        self.assertNotIn("203.0.113.9", self.site.failures)

    def test_a_flood_of_addresses_does_not_grow_the_table(self):
        from opendmt3.server.web import app as web_app
        with mock.patch.object(web_app, "ADDRESSES_KEPT", 3):
            for n in range(10):
                self.site.failed("198.51.100.%d" % n)
        self.assertEqual(len(self.site.failures), 3)

    def test_sign_in_then_home_shows_the_dj(self):
        self.make()
        r = self.sign_in(self.client)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/"))
        page = self.client.get("/").text
        self.assertIn("DJ NOVA", page)
        self.assertIn("openDMT3", page)

    def test_wrong_passwords_are_slowed_down(self):
        self.make()
        for _ in range(5):
            self.assertEqual(self.sign_in(self.client, password="nope1234").status_code, 401)
        # The sixth try waits, even with the right password.
        self.assertEqual(self.sign_in(self.client).status_code, 429)

    def test_a_link_to_another_site_is_not_followed_after_sign_in(self):
        self.make()
        r = self.sign_in(self.client, path="/signin?next=//evil.example/")
        self.assertEqual(r.headers["location"], "/")

    # ------------------------------------------------------------------------------------ admin pages

    # ---------------------------------------------------------------------------------- my account

    def _account_form(self, client):
        page = client.get("/account").text
        return page.split('name="csrf" value="', 1)[1].split('"', 1)[0]

    def test_a_player_changes_their_own_name_and_password(self):
        self.make()
        self.sign_in(self.client)
        token = self._account_form(self.client)
        r = self.client.post("/account", data={"csrf": token, "action": "dj_name", "dj_name": "NOVA X"},
                             follow_redirects=False)
        self.assertEqual(r.headers["location"], "/account?done=dj_name")
        self.assertIn("NOVA X", self.client.get("/account").text)
        old_card = self.site.accounts().by_login("NOVA")["card"]
        # An API token from before the change.
        api = self.client.post("/api/v1/session", json={"login_id": "NOVA", "password": "pass1234"}).json()["token"]
        token = self._account_form(self.client)
        r = self.client.post("/account", data={"csrf": token, "action": "password", "current": "pass1234",
                                               "new": "fresh567", "again": "fresh567"}, follow_redirects=False)
        self.assertEqual(r.headers["location"], "/account?done=password")
        # Still signed in here (a new sign-in came with the redirect), with a new card; the old token is over.
        page = self.client.get("/account?done=password")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Your password is changed, and your card with it.", page.text)
        self.assertNotEqual(self.site.accounts().by_login("NOVA")["card"], old_card)
        self.assertEqual(self.client.get("/api/v1/me", headers={"Authorization": "Bearer " + api}).status_code, 401)
        self.assertIsNotNone(self.site.accounts().check_web("NOVA", "fresh567"))

    def card_tables(self):
        """The DJ card's tables and pictures as --catalog leaves them, made up: two icons, two plates, a pattern."""
        from opendmt3.server.services import cards
        tables = {"icon": [{"number": 1, "grade": ""}, {"number": 6, "grade": "S"}],
                  "plate": [{"number": 32768, "grade": ""}, {"number": 32769, "grade": ""}],
                  "pattern": [{"number": 0, "grade": ""}, {"number": 7, "grade": "A"}],
                  "points": {"1": 9}, "levels": [12, 42, 92]}
        with open(os.path.join(self.tmp, cards.FILE), "w") as f:
            json.dump(tables, f)
        for kind in cards.KINDS:
            os.makedirs(os.path.join(self.tmp, cards.FOLDER, kind), exist_ok=True)
            for item in tables[kind]:
                with open(os.path.join(self.tmp, cards.FOLDER, kind, "%d.png" % item["number"]), "wb") as f:
                    f.write(b"\x89PNG\r\n\x1a\n" + kind.encode())
        return tables

    def test_a_player_sets_their_dj_card_on_the_account_page(self):
        self.make()
        self.card_tables()
        self.sign_in(self.client)
        page = self.client.get("/account").text
        # The new card: the basic icon chosen, the Platinum Crew plate, no comment.
        self.assertIn('name="icon" value="1" checked', page)
        self.assertIn('name="plate" value="32769" checked', page)
        token = self._account_form(self.client)
        r = self.client.post("/account", data={"csrf": token, "action": "card", "icon": "6", "plate": "32768",
                                               "pattern": "7", "comment": "한글ABCDEFGHIJ"}, follow_redirects=False)
        self.assertEqual(r.headers["location"], "/account?done=card")
        row = self.site.accounts().by_login("NOVA")
        self.assertEqual((row["icon"], row["plate"], row["pattern"], row["comment"]), (6, 32768, 7, "한글ABCDEFGHIJ"))
        page = self.client.get("/account?done=card").text
        self.assertIn("Your DJ card is saved.", page)
        self.assertIn('name="icon" value="6" checked', page)
        # A number the game has no picture for, or a comment longer than the game shows: refused, nothing changed.
        for field, value, words in (("icon", "200", "There is no icon 200"), ("plate", "1", "There is no plate 1"),
                                    ("pattern", "x", "There is no plate pattern x"),
                                    ("comment", "ABCDEFGHIJKLM", "A comment is up to 12 characters")):
            token = self._account_form(self.client)
            page = self.client.post("/account", data={"csrf": token, "action": "card", field: value}).text
            self.assertIn(words, page, field)
        row = self.site.accounts().by_login("NOVA")
        self.assertEqual((row["icon"], row["plate"], row["pattern"], row["comment"]), (6, 32768, 7, "한글ABCDEFGHIJ"))
        # The DJ page shows the card: the pictures, the comment and the level (no plays yet: level 1).
        dj = self.client.get("/dj/%d" % row["id"]).text
        for part in ("/cards/icon/6.png", "/cards/plate/32768.png", "/cards/pattern/7.png", "한글ABCDEFGHIJ", "Lv 1"):
            self.assertIn(part, dj)
        # The pictures, for signed-in visitors only, and only what the server read.
        self.assertEqual(self.client.get("/cards/icon/6.png").headers["content-type"], "image/png")
        self.assertEqual(self.client.get("/cards/icon/999.png").status_code, 404)
        self.assertEqual(self.client.get("/cards/secret/1.png").status_code, 404)
        from starlette.testclient import TestClient
        stranger = TestClient(self.app, client=("203.0.113.9", 50002))
        self.assertEqual(stranger.get("/cards/icon/6.png", follow_redirects=False).status_code, 303)

    def test_the_dj_card_through_the_api(self):
        nova = self.make()
        headers = {"Authorization": "Bearer " + self.client.post(
            "/api/v1/session", json={"login_id": "NOVA", "password": "pass1234"}).json()["token"]}
        # Before the server read the game's tables: only the defaults can be chosen, the comment always.
        self.assertEqual(self.client.post("/api/v1/me/dj_card", json={"icon": 6}, headers=headers).status_code, 400)
        r = self.client.post("/api/v1/me/dj_card", json={"icon": 1, "comment": "HI"}, headers=headers)
        self.assertEqual(r.json()["dj_card"]["comment"], "HI")
        self.assertFalse(r.json()["dj_card"]["pictures"])
        tables = self.card_tables()
        choices = self.client.get("/api/v1/dj_cards", headers=headers).json()
        self.assertEqual((choices["icon"], choices["comment_max"]), (tables["icon"], 12))
        r = self.client.post("/api/v1/me/dj_card", json={"icon": 6, "plate": 32768, "pattern": 7}, headers=headers)
        card = r.json()["dj_card"]
        self.assertEqual((card["icon"], card["plate"], card["pattern"], card["comment"], card["level"]),
                         (6, 32768, 7, "HI", 1))
        refused = self.client.post("/api/v1/me/dj_card", json={"plate": 1}, headers=headers)
        self.assertEqual((refused.status_code, refused.json()["error"]["code"]), (400, "refused"))
        self.assertEqual(self.client.post("/api/v1/me/dj_card", json={"icon": "6"}, headers=headers).status_code, 400)
        # The same card in /me and on the player's DJ page; the pictures with a token.
        self.assertEqual(self.client.get("/api/v1/me", headers=headers).json()["dj_card"], card)
        self.assertEqual(self.client.get("/api/v1/djs/%d" % nova["id"], headers=headers).json()["dj_card"], card)
        self.assertEqual(self.client.get("/api/v1/dj_cards/plate/32768.png", headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/dj_cards/plate/32768.png").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/dj_cards", headers={}).status_code, 401)

    def test_a_wrong_current_password_or_two_different_new_ones_change_nothing(self):
        from opendmt3.server.services import accounts
        self.make()
        self.sign_in(self.client)
        self.client.cookies.set("opendmt3_lang", "ko")
        rule = "비밀번호는 영문자와 숫자로 %d~%d자입니다." % (accounts.PASSWORD_MIN, accounts.PASSWORD_MAX)
        for current, new, again, words in (("nope1234", "fresh567", "fresh567", "지금 비밀번호가 맞지 않습니다."),
                                           ("pass1234", "fresh567", "other567", "새 비밀번호 두 개가 서로 다릅니다."),
                                           ("pass1234", "ab", "ab", rule)):
            token = self._account_form(self.client)
            r = self.client.post("/account", data={"csrf": token, "action": "password", "current": current,
                                                   "new": new, "again": again}, follow_redirects=False)
            self.assertEqual(r.status_code, 200, current)
            self.assertIn(words, r.text)
        self.assertIsNotNone(self.site.accounts().check_web("NOVA", "pass1234"))

    def test_the_account_page_counts_wrong_passwords_like_a_sign_in(self):
        self.make()
        self.sign_in(self.client)
        for _ in range(5):
            token = self._account_form(self.client)
            self.client.post("/account", data={"csrf": token, "action": "password", "current": "nope1234",
                                               "new": "fresh567", "again": "fresh567"})
        token = self._account_form(self.client)
        r = self.client.post("/account", data={"csrf": token, "action": "password", "current": "pass1234",
                                               "new": "fresh567", "again": "fresh567"}, follow_redirects=False)
        # The right password waits too, once the limit is reached.
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(self.site.accounts().check_web("NOVA", "pass1234"))

    def test_my_account_through_the_api(self):
        self.make()
        token = self.client.post("/api/v1/session", json={"login_id": "NOVA", "password": "pass1234"}).json()["token"]
        auth = {"Authorization": "Bearer " + token}
        r = self.client.post("/api/v1/me/dj_name", json={"dj_name": "DJ NEW"}, headers=auth)
        self.assertEqual((r.status_code, r.json()["dj_name"]), (200, "DJ NEW"))
        r = self.client.post("/api/v1/me/password", json={"password": "wrong999", "new_password": "fresh567"},
                             headers=auth)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (403, "wrong_password"))
        r = self.client.post("/api/v1/me/password", json={"password": "pass1234", "new_password": "x"}, headers=auth)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, "refused"))
        r = self.client.post("/api/v1/me/password", json={"password": "pass1234", "new_password": "fresh567"},
                             headers=auth)
        self.assertEqual(r.status_code, 200)
        fresh = r.json()["token"]
        # The old token ends with the old password; the one in the answer works.
        self.assertEqual(self.client.get("/api/v1/me", headers=auth).status_code, 401)
        self.assertEqual(self.client.get("/api/v1/me", headers={"Authorization": "Bearer " + fresh}).json()["dj_name"],
                         "DJ NEW")

    # ---------------------------------------------------------------------- status, log, cabinets

    def _seen_cabinet(self):
        from opendmt3.server import db
        from opendmt3.server.services import activity
        connection = db.connect(self.site.db_path)
        try:
            act = activity.Activity(connection)
            act.seen("198.51.100.7", "test", "198.51.100.7:5000")
            return act.cabinets()[0]["id"]
        finally:
            connection.close()

    def test_the_admin_sees_status_log_and_names_a_cabinet(self):
        self.make("BOSS", admin=True)
        self.sign_in(self.client, "BOSS")
        cabinet = self._seen_cabinet()
        status = self.client.get("/admin/status")
        self.assertEqual(status.status_code, 200)
        self.assertIn("Stages cleared", status.text)
        page = self.client.get("/admin/cabinets").text
        self.assertIn("198.51.100.7", page)
        token = page.split('name="csrf" value="', 1)[1].split('"', 1)[0]
        r = self.client.post("/admin/cabinets", data={"csrf": token, "action": "rename", "id": str(cabinet),
                                                      "name": "Living room"})
        self.assertIn("The cabinet&#39;s name is saved.", r.text)
        self.assertIn('value="Living room"', r.text)
        # The change is in the log.
        self.assertIn("named cabinet", self.client.get("/admin/log").text)

    def test_status_log_and_cabinets_are_for_admins_and_have_api_twins(self):
        self.make("BOSS", admin=True)
        self.make()
        self.sign_in(self.client)
        for path in ("/admin/status", "/admin/log", "/admin/cabinets"):
            self.assertEqual(self.client.get(path).status_code, 404, path)
        cabinet = self._seen_cabinet()
        player = self.client.post("/api/v1/session", json={"login_id": "NOVA", "password": "pass1234"}).json()["token"]
        boss = self.client.post("/api/v1/session", json={"login_id": "BOSS", "password": "pass1234"}).json()["token"]
        for path in ("/api/v1/server", "/api/v1/log", "/api/v1/cabinets?all=1"):
            self.assertEqual(self.client.get(path, headers={"Authorization": "Bearer " + player}).status_code, 403, path)
        auth = {"Authorization": "Bearer " + boss}
        server = self.client.get("/api/v1/server", headers=auth).json()
        self.assertEqual((server["accounts"]["all"], server["cabinets"]), (2, 1))
        self.assertIn("month", server)
        log = self.client.get("/api/v1/log", headers=auth).json()
        # The lists, and how many there are in all (the Logs page says when its lists stop short).
        self.assertEqual(set(log), {"changes", "messages", "counts"})
        r = self.client.post("/api/v1/cabinets/%d/name" % cabinet, json={"name": "Den"}, headers=auth)
        self.assertEqual(r.json()["cabinets"][0]["name"], "Den")
        r = self.client.post("/api/v1/cabinets/999/name", json={"name": "x"}, headers=auth)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (404, "unknown_cabinet"))
        listed = self.client.get("/api/v1/cabinets?all=1", headers=auth).json()["cabinets"]
        self.assertEqual((listed[0]["name"], listed[0]["connected"]), ("Den", False))

    def test_a_djs_page_and_api_show_their_weeks(self):
        row = self.make()
        self.sign_in(self.client)
        page = self.client.get("/dj/%d" % row["id"])
        self.assertIn("Stages cleared, last 12 weeks", page.text)
        token = self.client.post("/api/v1/session", json={"login_id": "NOVA", "password": "pass1234"}).json()["token"]
        dj = self.client.get("/api/v1/djs/%d" % row["id"], headers={"Authorization": "Bearer " + token}).json()
        self.assertEqual(len(dj["activity"]["weeks"]), 12)
        self.assertEqual(set(dj["activity"]), {"weeks", "modes", "songs", "sessions", "seconds"})

    # ------------------------------------------------------------------------------------- backups

    def test_the_admin_backs_up_downloads_and_restores(self):
        self.make("BOSS", admin=True)
        self.sign_in(self.client, "BOSS")
        page = self.client.get("/admin/backups").text
        token = page.split('name="csrf" value="', 1)[1].split('"', 1)[0]
        r = self.client.post("/admin/backups", data={"csrf": token, "action": "make"})
        self.assertIn("Backed up: openDMT3-", r.text)
        name = r.text.split("Backed up: ", 1)[1].split("<", 1)[0].strip()
        self.make("RIO")
        # The file, as the admin keeps it elsewhere.
        got = self.client.get("/admin/backups/" + name)
        self.assertEqual(got.status_code, 200)
        self.assertTrue(got.content.startswith(b"SQLite format 3"))
        r = self.client.post("/admin/backups", data={"csrf": token, "action": "restore", "name": name})
        self.assertIn("Restored " + name, r.text)
        self.assertIsNone(self.site.accounts().by_login("RIO"))
        # Names from the form never leave backups/.
        r = self.client.post("/admin/backups", data={"csrf": token, "action": "restore", "name": "../openDMT3.sqlite"})
        self.assertIn("No backup named", r.text)
        self.assertEqual(self.client.get("/admin/backups/..%2FopenDMT3.sqlite").status_code, 404)

    def test_backups_are_for_admins_only(self):
        self.make()
        self.sign_in(self.client)
        self.assertEqual(self.client.get("/admin/backups").status_code, 404)
        token = self.client.post("/api/v1/session", json={"login_id": "NOVA", "password": "pass1234"}).json()["token"]
        r = self.client.get("/api/v1/backups", headers={"Authorization": "Bearer " + token})
        self.assertEqual(r.status_code, 403)

    def test_backups_through_the_api(self):
        self.make("BOSS", admin=True)
        token = self.client.post("/api/v1/session", json={"login_id": "BOSS", "password": "pass1234"}).json()["token"]
        auth = {"Authorization": "Bearer " + token}
        made = self.client.post("/api/v1/backups", headers=auth)
        self.assertEqual(made.status_code, 201)
        name = made.json()["made"]
        listed = self.client.get("/api/v1/backups", headers=auth).json()
        self.assertEqual([b["name"] for b in listed["backups"]], [name])
        self.assertTrue(self.client.get("/api/v1/backups/" + name, headers=auth).content.startswith(b"SQLite format 3"))
        self.make("RIO")
        r = self.client.post("/api/v1/backups/%s/restore" % name, headers=auth)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["kept_as"].endswith("-restore.sqlite"))
        self.assertIsNone(self.site.accounts().by_login("RIO"))
        r = self.client.post("/api/v1/backups/nothing.sqlite/restore", headers=auth)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (404, "unknown_backup"))

    def test_admin_makes_and_changes_accounts(self):
        self.make("BOSS", admin=True)
        self.sign_in(self.client, "BOSS")
        page = self.client.get("/admin/players").text
        token = page.split('name="csrf" value="', 1)[1].split('"', 1)[0]
        r = self.client.post("/admin/players", data={"csrf": token, "action": "make", "login_id": "minho",
                                                     "dj_name": "MINHO", "password": ""})
        # A password is made when none is typed, and shown once.
        self.assertIn("MINHO", r.text)
        self.assertIn("shown once", r.text)
        self.client.post("/admin/players", data={"csrf": token, "action": "disable", "login_id": "MINHO"})
        store = self.site.accounts()
        self.assertTrue(store.by_login("MINHO")["disabled"])
        store.db.close()
        # A form without the sign-in's token changes nothing.
        r = self.client.post("/admin/players", data={"csrf": "x", "action": "delete", "login_id": "MINHO"})
        self.assertIn("expired", r.text)
        store = self.site.accounts()
        self.assertIsNotNone(store.by_login("MINHO"))
        store.db.close()

    def test_an_account_error_reads_in_the_pages_language(self):
        self.make("BOSS", admin=True)
        self.sign_in(self.client, "BOSS")
        self.client.cookies.set("opendmt3_lang", "ko")
        page = self.client.get("/admin/players").text
        token = page.split('name="csrf" value="', 1)[1].split('"', 1)[0]
        r = self.client.post("/admin/players", data={"csrf": token, "action": "make", "login_id": "no way",
                                                     "dj_name": "X", "password": ""})
        # The account rules' sentence, in the Korean the page is in (errors.py), not the English one.
        self.assertIn("ID는 영문자와 숫자로 1~8자입니다", r.text)
        self.assertNotIn("letters or digits", r.text)

    # ---------------------------------------------------------------- the launcher's updates, from here

    def test_the_update_feed_is_handed_out_without_a_sign_in_and_nothing_else_is(self):
        self.make()
        self.assertFalse(self.client.get("/api/v1/status").json()["updates"])
        self.assertEqual(self.client.get("/updates/releases.win.json").status_code, 404)
        folder = os.path.join(self.tmp, "updates")
        os.makedirs(folder)
        with open(os.path.join(folder, "releases.win.json"), "w") as f:
            f.write('{"Assets": []}')
        with open(os.path.join(self.tmp, "web.secret.copy"), "w") as f:
            f.write("not for anyone")
        self.assertTrue(self.client.get("/api/v1/status").json()["updates"])
        # Velopack signs in nowhere: the feed answers anyone, with the file as it is.
        r = self.client.get("/updates/releases.win.json", follow_redirects=False)
        self.assertEqual((r.status_code, r.text), (200, '{"Assets": []}'))
        # Nothing outside the folder, however it is asked for.
        for path in ("/updates/..%2Fweb.secret.copy", "/updates/%2E%2E%2Fopendmt3.sqlite", "/updates/.hidden",
                     "/updates/..%5Cweb.secret.copy"):
            self.assertEqual(self.client.get(path, follow_redirects=False).status_code, 404, path)

    def test_only_the_feed_its_packages_and_their_signatures_are_handed_out_each_as_its_kind(self):
        # data/updates/ with what a release folder holds and what may end up beside it: the feed, a whole and a delta
        # package and a signature are handed out, each byte for byte and as its own type; nothing else in the folder,
        # nothing below or above it, no link's target, and never a list of it.
        self.make()
        folder = os.path.join(self.tmp, "updates")
        os.makedirs(os.path.join(folder, "old"))
        package = bytes(range(256)) * 64
        held = {"releases.win.json": b'{"Assets": []}', "openDMT3-0.14.0-full.nupkg": package,
                "openDMT3-0.14.0-full.nupkg.sig": b"made-up signature\n", "openDMT3-0.14.0-delta.nupkg": package[:999],
                # Not the feed's: a release folder's other files, notes, a copy of the database, a kept older feed.
                "RELEASES": b"legacy", "assets.win.json": b"{}", "openDMT3-win-Setup.exe": b"MZ made up",
                "notes.txt": b"notes", "openDMT3.sqlite": b"SQLite format 3\x00 a copy", "releases.win.json.bak": b"{}",
                ".hidden.nupkg": b"hidden", "my package.nupkg": b"a space", "old/older.nupkg": b"below"}
        for name, data in held.items():
            with open(os.path.join(folder, *name.split("/")), "wb") as f:
                f.write(data)
        with open(os.path.join(self.tmp, "web.secret.copy"), "wb") as f:
            f.write(b"not for anyone")
        linked = hasattr(os, "symlink") and os.name == "posix"
        if linked:
            # A link in the folder to a file above it, under a package's name.
            os.symlink(os.path.join(self.tmp, "web.secret.copy"), os.path.join(folder, "linked.nupkg"))
        kinds = {"releases.win.json": "application/json", "openDMT3-0.14.0-full.nupkg": "application/octet-stream",
                 "openDMT3-0.14.0-full.nupkg.sig": "application/octet-stream",
                 "openDMT3-0.14.0-delta.nupkg": "application/octet-stream"}
        for name, kind in kinds.items():
            r = self.client.get("/updates/" + name, follow_redirects=False)
            self.assertEqual((r.status_code, r.content, r.headers["content-type"].split(";")[0],
                              r.headers["x-content-type-options"]), (200, held[name], kind, "nosniff"), name)
            # As it is: never packed again on the way (a package is one already, and its length is the download's).
            self.assertNotIn("content-encoding", r.headers)
            self.assertEqual(int(r.headers["content-length"]), len(held[name]))
        refused = ["RELEASES", "assets.win.json", "openDMT3-win-Setup.exe", "notes.txt", "openDMT3.sqlite",
                   "releases.win.json.bak", ".hidden.nupkg", "my%20package.nupkg", "old", "old/older.nupkg",
                   "old%2Folder.nupkg", "old%5Colder.nupkg", "..%2Fweb.secret.copy", "..%5Cweb.secret.copy",
                   "%2E%2E%2Fopendmt3.sqlite", "releases.win.json:stream",
                   "RELEASES.WIN.JSON", "openDMT3-0.14.0-full.nupkg.sig.sig", "x" * 250 + ".nupkg"]
        if linked:
            refused.append("linked.nupkg")
        for name in refused:
            r = self.client.get("/updates/" + name, follow_redirects=False)
            self.assertEqual((r.status_code, r.text), (404, "Not Found"), name)
        # A slash after a file's name is sent to the file's own address (the router's way with every address), no
        # further.
        r = self.client.get("/updates/releases.win.json%2F", follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"].split("//testserver")[-1]),
                         (307, "/updates/releases.win.json"))
        # No list of the folder, with or without its slash, signed in or not.
        for path in ("/updates/", "/updates"):
            r = self.client.get(path, follow_redirects=False)
            self.assertIn(r.status_code, (303, 404), path)
            self.assertNotIn("nupkg", r.text)
        self.sign_in(self.client)
        for path in ("/updates/", "/updates"):
            r = self.client.get(path, follow_redirects=False)
            self.assertEqual(r.status_code, 404, path)
            self.assertNotIn("nupkg", r.text)

    # ------------------------------------------------------------------- the launcher's one-use link

    def test_a_one_use_link_signs_in_once_and_only_from_this_pc(self):
        row = self.make()
        token = self.site.once(row["id"])
        # From another PC the link does nothing (and is not used up by that).
        r = self.client.get("/signin/once/" + token, follow_redirects=False)
        self.assertEqual(r.headers["location"], "/signin")
        # On this PC: signed in, on the player's page (never another site's address), in the launcher's language.
        r = self.local.get("/signin/once/%s?lang=ko&next=//evil.example/x" % token, follow_redirects=False)
        self.assertEqual(r.headers["location"], "/dj/%d" % row["id"])
        self.assertEqual(self.local.cookies.get("opendmt3_lang"), "ko")
        page = self.local.get("/dj/%d" % row["id"])
        self.assertEqual(page.status_code, 200)
        self.assertIn("DJ NOVA", page.text)
        # Used up: a second visit (another browser) is not signed in.
        self.local.cookies.clear()
        r = self.local.get("/signin/once/" + token, follow_redirects=False)
        self.assertEqual(r.headers["location"], "/signin")

    def test_a_one_use_link_expires_and_a_disabled_account_gets_none(self):
        row = self.make()
        token = self.site.once(row["id"])
        # A minute later.
        self.site.onces[token] = (row["id"], 0)
        r = self.local.get("/signin/once/" + token, follow_redirects=False)
        self.assertEqual(r.headers["location"], "/signin")
        token = self.site.once(row["id"])
        store = self.site.accounts()
        store.set_disabled("NOVA", True)
        store.db.close()
        r = self.local.get("/signin/once/" + token, follow_redirects=False)
        self.assertEqual(r.headers["location"], "/signin")
        self.assertIsNone(self.local.cookies.get("opendmt3"))

    def test_the_delete_question_is_one_whole_attribute(self):
        import html.parser
        self.make("BOSS", admin=True)
        self.make()
        self.sign_in(self.client, "BOSS")
        page = self.client.get("/admin/players").text
        found = []

        class Forms(html.parser.HTMLParser):
            def handle_starttag(self, tag, attrs):
                if tag == "form" and dict(attrs).get("data-ask"):
                    found.append(dict(attrs))

        Forms().feed(page)
        # The site's own dialog asks (static/site.js): the question with the ID inside, its title, what goes with
        # the player, and the button's words. The browser's confirm box is gone. (The page's other questions, the
        # plays' resets, are tests/server/test_reset.py's.)
        found = [form for form in found if form["data-ask-yes"] == "Delete"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["data-ask"], "Delete NOVA?")
        self.assertEqual(found[0]["data-ask-yes"], "Delete")
        self.assertTrue(found[0]["data-ask-title"] and found[0]["data-ask-detail"])
        self.assertNotIn("confirm(", page)
        # The script's address carries the version (a browser keeps it until the next one).
        from opendmt3 import __version__
        self.assertIn('<script src="/static/site.js?v=%s"></script>' % __version__, page)

    def test_admin_pages_are_not_for_players(self):
        self.make()
        self.sign_in(self.client)
        self.assertEqual(self.client.get("/admin/players").status_code, 404)

    # -------------------------------------------------------------------------------------------- API

    def test_the_launcher_signs_in_and_gets_the_card(self):
        row = self.make()
        status = self.client.get("/api/v1/status").json()
        self.assertEqual((status["server"], status["game_port"]), ("openDMT3", 4725))
        r = self.client.post("/api/v1/session", json={"login_id": "nova", "password": "pass1234"})
        body = r.json()
        self.assertEqual((body["login_id"], body["dj_name"], body["card"]), ("NOVA", "DJ NOVA", row["card"]))
        me = self.client.get("/api/v1/me", headers={"Authorization": "Bearer " + body["token"]}).json()
        self.assertEqual(me["card"], row["card"])
        self.assertEqual(self.client.post("/api/v1/session", json={"login_id": "NOVA", "password": "x"}).status_code, 401)

    def test_a_new_password_ends_old_sign_ins_and_tokens(self):
        self.make()
        token = self.client.post("/api/v1/session", json={"login_id": "NOVA", "password": "pass1234"}).json()["token"]
        self.sign_in(self.client)
        store = self.site.accounts()
        store.set_password("NOVA", "newpass1")
        store.db.close()
        self.assertEqual(self.client.get("/api/v1/me", headers={"Authorization": "Bearer " + token}).status_code, 401)
        self.assertEqual(self.client.get("/", follow_redirects=False).status_code, 303)

    def test_players_api_is_for_admins(self):
        self.make()
        self.make("BOSS", admin=True)
        player = self.client.post("/api/v1/session", json={"login_id": "NOVA", "password": "pass1234"}).json()["token"]
        boss = self.client.post("/api/v1/session", json={"login_id": "BOSS", "password": "pass1234"}).json()["token"]
        self.assertEqual(self.client.get("/api/v1/players", headers={"Authorization": "Bearer " + player}).status_code, 403)
        listed = self.client.get("/api/v1/players", headers={"Authorization": "Bearer " + boss}).json()["players"]
        self.assertEqual(sorted(p["login_id"] for p in listed), ["BOSS", "NOVA"])

    def test_home_lists_plays_with_titles_from_the_song_list(self):
        import json
        from opendmt3.server import db
        from opendmt3.server.services import records
        row = self.make()
        with open(os.path.join(self.tmp, "catalog.json"), "w", encoding="utf-8") as f:
            json.dump({"songs": [{"number": 56, "title": "Made-up Song"}]}, f)
        connection = db.connect(self.site.db_path)
        records.Records(connection).add(row["id"], "127.0.0.1:1", 0, {"song": 56, "pattern": 1, "score": 4530,
                                                                        "counts": [0] * 7, "raw": bytes(47)})
        records.Records(connection).add(row["id"], "127.0.0.1:1", 0, {"song": 77, "pattern": 2, "score": 12,
                                                                        "counts": [0] * 7, "raw": bytes(47)})
        connection.close()
        self.sign_in(self.client)
        page = self.client.get("/").text
        self.assertIn("Made-up Song", page)
        self.assertIn("4,530", page)
        # A song not in the list shows its number.
        self.assertIn("#77", page)

    # -------------------------------------------------------------------------------------- downloads

    def test_the_download_page_gives_the_address_with_its_port(self):
        from starlette.testclient import TestClient
        self.make()
        secure = TestClient(self.app, base_url="https://dmt.example", client=("203.0.113.5", 50003))
        self.sign_in(secure)
        self.assertIn("dmt.example:443", secure.get("/download").text)

    def test_the_installer_is_handed_out_when_the_server_has_it(self):
        self.make()
        self.sign_in(self.client)
        self.assertIn("releases", self.client.get("/download").text)
        os.makedirs(self.site.downloads)
        with open(os.path.join(self.site.downloads, "openDMT3-win-Setup.exe"), "wb") as f:
            f.write(b"MZ installer")
        self.assertIn("/download/windows", self.client.get("/download").text)
        got = self.client.get("/download/windows")
        # The installer as kept, then this server on its end (preset.py): the launcher it installs starts here.
        self.assertTrue(got.content.startswith(b"MZ installer"))
        self.assertEqual(int(got.headers["content-length"]), len(got.content))
        from opendmt3.core import preset
        handed = os.path.join(self.site.downloads, "as-downloaded.exe")
        with open(handed, "wb") as f:
            f.write(got.content)
        self.assertEqual(preset.read(handed), {"url": "http://testserver", "name": "testserver"})
        # The file the server keeps has no end of its own.
        self.assertIsNone(preset.read(os.path.join(self.site.downloads, "openDMT3-win-Setup.exe")))


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class RankingsTest(WebBase):
    """The rankings, songs, song and DJ pages, and their API twins, from plays put in the way the game server does."""

    def play(self, account, song, pattern, score, mode=0, at=1000):
        from opendmt3.server import db
        from opendmt3.server.services import records as rec
        connection = db.connect(self.site.db_path)
        try:
            rec.Records(connection).add(account["id"], "198.51.100.7", mode, {"song": song, "pattern": pattern,
                                                                             "score": score, "counts": [0] * 7,
                                                                             "raw": bytes(47)}, at=at)
        finally:
            connection.close()

    def test_the_best_30_average_rewards_how_well_more_than_how_much(self):
        many = self.make("MANY", dj="MANY")
        few = self.make("FEW", dj="FEW")
        # MANY: 100 charts at 300,000 (total 30,000,000). FEW: 30 charts at 900,000 (total 27,000,000).
        for n in range(100):
            self.play(many, 100 + n, 1, 300000, at=2000 + n)
        for n in range(30):
            self.play(few, 200 + n, 1, 900000, at=3000 + n)
        # Only the best 30 of MANY count, averaged: 300,000; FEW: 900,000. Five charts only: the rest count as 0.
        some = self.make("SOME", dj="SOME")
        for n in range(5):
            self.play(some, 300 + n, 1, 600000, at=4000 + n)
        self.sign_in(self.client, "MANY")
        token = self.client.post("/api/v1/session", json={"login_id": "MANY", "password": "pass1234"}).json()["token"]
        rows = self.client.get("/api/v1/rankings?mode=0&by=best30",
                               headers={"Authorization": "Bearer " + token}).json()["rows"]
        self.assertEqual([(r["dj_name"], r["total"], r["charts"]) for r in rows],
                         [("FEW", 900000, 30), ("MANY", 300000, 30), ("SOME", 100000, 5)])
        # The total ranks them the other way round: MANY played more.
        totals = self.client.get("/api/v1/rankings?mode=0", headers={"Authorization": "Bearer " + token}).json()["rows"]
        self.assertEqual([r["dj_name"] for r in totals][:2], ["MANY", "FEW"])
        self.assertEqual(self.client.get("/api/v1/rankings?mode=0&by=fun",
                                         headers={"Authorization": "Bearer " + token}).status_code, 400)
        page = self.client.get("/rankings?mode=0&by=best30").text
        self.assertIn("Best 30 average", page)
        self.assertIn("30 of 30", page)

    def catalog(self, songs):
        import json
        with open(os.path.join(self.tmp, "catalog.json"), "w", encoding="utf-8") as f:
            json.dump({"songs": songs}, f)

    def players(self):
        nova = self.make()
        rio = self.make("RIO", dj="RIO")
        ghost = self.make("GHOST", dj="GHOST")
        # NOVA: best 900 on song 1 pattern 1, set before a lower 700; 500 on song 2. RIO: one chart, higher.
        self.play(nova, 1, 1, 900, at=1001)
        self.play(nova, 1, 1, 700, at=1002)
        self.play(nova, 2, 3, 500, at=1003)
        self.play(rio, 1, 1, 1300, at=1004)
        # A disabled account is in nobody's ranking, list or tab: not even a mode only they played.
        self.play(ghost, 1, 1, 99999, at=1005)
        self.play(ghost, 4242, 1, 5, mode=5, at=1006)
        store = self.site.accounts()
        try:
            store.set_disabled("GHOST", True)
        finally:
            store.db.close()
        return nova, rio, ghost

    def token(self, login_id="NOVA"):
        """A token for the player, made once per test (sign-ins from one address are limited per minute)."""
        tokens = self.__dict__.setdefault("_tokens", {})
        if login_id not in tokens:
            tokens[login_id] = self.client.post("/api/v1/session", json={"login_id": login_id,
                                                                         "password": "pass1234"}).json()["token"]
        return tokens[login_id]

    def api(self, path, method="GET", login_id="NOVA"):
        return self.client.request(method, path, headers={"Authorization": "Bearer " + self.token(login_id)})

    def test_the_ranking_adds_each_players_best_charts(self):
        nova, rio, ghost = self.players()
        self.sign_in(self.client)
        rows = self.api("/api/v1/rankings?mode=0").json()
        self.assertEqual((rows["name"], rows["modes"]), ("STAR", [0]))
        self.assertEqual([(r["player"], r["total"], r["charts"], r["place"]) for r in rows["rows"]],
                         [(nova["id"], 1400, 2, 1), (rio["id"], 1300, 1, 2)])
        # Players are named by number, never by the login ID that signs them in.
        self.assertNotIn("login_id", rows["rows"][0])
        page = self.client.get("/rankings").text
        self.assertIn("1,400", page)
        self.assertIn('<tr class="me">', page)
        self.assertNotIn("GHOST", page)
        self.assertNotIn("MODE 5", page)
        self.assertNotIn("RIO</a>" + "RIO", page)

    def test_equal_totals_share_a_place_and_its_plate(self):
        nova = self.make()
        rio = self.make("RIO", dj="RIO")
        self.play(nova, 1, 1, 800)
        self.play(rio, 2, 1, 800)
        self.sign_in(self.client)
        rows = self.api("/api/v1/rankings").json()["rows"]
        self.assertEqual([r["place"] for r in rows], [1, 1])
        page = self.client.get("/rankings").text
        self.assertEqual(page.count("plate place-1"), 2)

    def test_numbers_out_of_range_are_refused_not_crashing(self):
        self.players()
        self.sign_in(self.client)
        self.assertEqual(self.client.get("/rankings?mode=9223372036854775808").status_code, 200)
        self.assertEqual(self.api("/api/v1/rankings?mode=9223372036854775808").status_code, 400)
        self.assertEqual(self.api("/api/v1/rankings?mode=x").status_code, 400)
        self.assertEqual(self.client.get("/songs/111111111111111111111111111111").status_code, 404)
        self.assertEqual(self.api("/api/v1/songs/111111111111111111111111111111").status_code, 404)
        self.assertEqual(self.client.get("/dj/111111111111111111111111111111").status_code, 404)

    def test_songs_list_the_catalogue_and_what_was_played(self):
        self.players()
        self.catalog([{"number": 1, "title": "Song One", "composer": "Someone", "genre": "Pop"},
                      {"number": 3, "title": "Song Three", "composer": "", "genre": ""}])
        self.sign_in(self.client)
        songs = self.api("/api/v1/songs").json()["songs"]
        by_number = {s["number"]: s for s in songs}
        # Song 2 was played but is not in the list: it shows by its number. Song 3 is in the list, unplayed.
        # The disabled player's song 4242 is nowhere.
        self.assertEqual(by_number[1]["best"], 1300)
        self.assertEqual(by_number[2]["title"], "#2")
        self.assertEqual(by_number[3]["plays"], 0)
        self.assertNotIn(4242, by_number)
        self.assertEqual(songs[0]["number"], 1)
        page = self.client.get("/songs?q=someone").text
        self.assertIn("Song One", page)
        self.assertNotIn("Song Three", page)

    def test_a_song_page_has_a_board_per_chart(self):
        nova, rio, _ = self.players()
        self.sign_in(self.client)
        song = self.api("/api/v1/songs/1").json()
        self.assertEqual(len(song["charts"]), 1)
        board = song["charts"][0]["rows"]
        self.assertEqual([(r["player"], r["score"], r["place"]) for r in board], [(rio["id"], 1300, 1), (nova["id"], 900, 2)])
        # When the best was set, not the later, lower play.
        self.assertEqual(board[1]["at"], 1001)
        self.assertEqual(self.client.get("/songs/1").status_code, 200)
        self.assertEqual(self.client.get("/songs/77").status_code, 404)
        self.assertEqual(self.api("/api/v1/songs/77").status_code, 404)

    def test_a_dj_page(self):
        nova, rio, ghost = self.players()
        self.sign_in(self.client)
        dj = self.api("/api/v1/djs/%d" % rio["id"]).json()
        self.assertEqual((dj["dj_name"], dj["summary"]["plays"], dj["bests"][0]["score"]), ("RIO", 1, 1300))
        self.assertEqual(dj["recent"][0]["mode_name"], "STAR")
        page = self.client.get("/dj/%d" % rio["id"]).text
        self.assertIn("RIO", page)
        self.assertIn("STAR · Pattern 1", page)
        # A disabled player has no page, and an unknown number none either.
        self.assertEqual(self.client.get("/dj/%d" % ghost["id"]).status_code, 404)
        self.assertEqual(self.client.get("/dj/999").status_code, 404)

    def test_everyones_plays_leave_disabled_players_out(self):
        self.players()
        self.sign_in(self.client)
        everyone = self.api("/api/v1/plays?everyone=1").json()["plays"]
        self.assertEqual({p["dj"] for p in everyone}, {"DJ NOVA", "RIO"})
        self.assertEqual({p["dj"] for p in self.api("/api/v1/plays").json()["plays"]}, {"DJ NOVA"})
        home = self.client.get("/").text
        self.assertNotIn("GHOST", home)
        self.assertNotIn("4242", home)

    def test_the_admin_pages_actions_have_api_twins(self):
        self.make("BOSS", dj="BOSS", admin=True)
        self.players()
        made = self.api("/api/v1/players/rio/password", "POST", "BOSS").json()
        self.assertEqual(made["login_id"], "RIO")
        self.assertEqual(self.client.post("/api/v1/session", json={"login_id": "RIO", "password": made["password"]}).status_code, 200)
        self.assertTrue(self.api("/api/v1/players/RIO/disable", "POST", "BOSS").json()["disabled"])
        self.assertFalse(self.api("/api/v1/players/RIO/enable", "POST", "BOSS").json()["disabled"])
        self.assertEqual(self.api("/api/v1/players/RIO", "DELETE", "BOSS").json(), {"deleted": "RIO"})
        self.assertEqual(self.api("/api/v1/players/RIO/enable", "POST", "BOSS").status_code, 404)
        self.assertEqual(self.api("/api/v1/players/BOSS", "DELETE", "BOSS").status_code, 400)
        self.assertEqual(self.api("/api/v1/players/NOVA/rename", "POST", "BOSS").status_code, 404)
        # Only an admin.
        self.assertEqual(self.api("/api/v1/players/BOSS/disable", "POST", "NOVA").status_code, 403)

    def test_api_errors_are_json_everywhere(self):
        self.make()
        for path, method, status in (("/api/v1/nothing", "GET", 404), ("/api/v1/rankings", "POST", 405),
                                     ("/api/v1/players", "GET", 401)):
            response = self.client.request(method, path)
            self.assertEqual(response.status_code, status, path)
            self.assertIn("error", response.json(), path)

    def test_every_new_page_and_api_needs_a_sign_in(self):
        nova, _, _ = self.players()
        for path in ("/rankings", "/songs", "/songs/1", "/dj/%d" % nova["id"]):
            self.assertEqual(self.client.get(path, follow_redirects=False).status_code, 303, path)
        for path in ("/api/v1/rankings", "/api/v1/songs", "/api/v1/songs/1", "/api/v1/djs/%d" % nova["id"]):
            self.assertEqual(self.client.get(path).status_code, 401, path)

    def test_the_menu_leads_to_them(self):
        self.make()
        self.sign_in(self.client)
        page = self.client.get("/").text
        for path in ("/rankings", "/songs", "/download"):
            self.assertIn('href="%s"' % path, page)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class AttackTest(WebBase):
    """The site's answers to what the security review tried: each attack, then that it is refused."""

    def api_sign_in(self, client, login_id="NOVA", password="pass1234"):
        return client.post("/api/v1/session", json={"login_id": login_id, "password": password})

    def client_at(self, address, base_url="http://testserver"):
        from starlette.testclient import TestClient
        return TestClient(self.app, base_url=base_url, client=(address, 50000))

    # ------------------------------------------------------------------ sign-ins and the event loop

    def test_sign_ins_never_hold_up_the_event_loop_the_cabinets_share(self):
        """No password check runs on the event loop's thread, and the loop never stands still for the checks.

        What it means is checked directly: each check notes the thread it ran on. The loop's own pauses are measured
        too, against the same loop's pauses while idle in the same run (a busy PC pauses any loop now and then; a
        pause of 25 to 49 ms there failed the old limit of half a check): ten checks on the loop would hold it for
        all of their time (at least five checks' worth even two at once), so its pauses beyond the idle ones must
        stay under two checks' worth. Another program taking the PC's cores in the middle of the sign-ins pauses the
        loop too (99 ms beyond idle once, at a load of 43 on 32 cores): up to three tries, each from an address of its
        own against its own idle time, and one within the limit passes. Checks on the loop fail every try."""
        import asyncio
        import threading
        import time
        import httpx
        from opendmt3.server.services import accounts
        from opendmt3.server.web import app as web_app
        self.make()
        # How long one password check takes here (what each sign-in held the loop for, before).
        started = time.perf_counter()
        accounts._matches(accounts._dummy_hash(), accounts.game_digest("x"))
        one_check = time.perf_counter() - started
        at_once, most, threads = [0], [0], []
        lock = threading.Lock()
        real = accounts._matches

        def counted(stored, digest):
            # How many checks run at the same moment, and on which thread each runs.
            with lock:
                at_once[0] += 1
                most[0] = max(most[0], at_once[0])
                threads.append(threading.get_ident())
            try:
                return real(stored, digest)
            finally:
                with lock:
                    at_once[0] -= 1

        async def pauses(until_done):
            """The loop's pauses past the 5 ms a ticker sleeps, while until_done() is still false: (their sum, how long
            it watched)."""
            total, first = 0.0, time.perf_counter()
            last = first
            while not until_done():
                await asyncio.sleep(0.005)
                now = time.perf_counter()
                total += max(0.0, now - last - 0.005)
                last = now
            return total, last - first

        async def main(address):
            loop = threading.get_ident()
            # The same loop idle first, for as long as the sign-ins will take at the most (five rounds of two checks).
            idle_until = time.perf_counter() + 5 * one_check
            idle = await pauses(lambda: time.perf_counter() >= idle_until)
            done = asyncio.Event()
            busy = asyncio.ensure_future(pauses(done.is_set))
            transport = httpx.ASGITransport(app=self.app, client=(address, 50000))
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                # The review's attack: ten sign-ins at once with a right password (never counted as wrong).
                answers = await asyncio.gather(*[client.post("/api/v1/session", json={"login_id": "NOVA",
                                                                                       "password": "pass1234"})
                                                 for _ in range(10)])
            done.set()
            return loop, answers, idle, await busy

        tries = []
        for attempt in range(3):
            # Each try from an address of its own: an address signs in 20 times a minute at most.
            del threads[:]
            with mock.patch.object(accounts, "_matches", counted):
                loop, answers, idle, busy = asyncio.run(main("203.0.113.%d" % (5 + attempt)))
            self.assertEqual({a.status_code for a in answers}, {200})
            # What it means: not one check ran on the loop's thread, in any try.
            self.assertEqual(len(threads), 10)
            self.assertNotIn(loop, threads, "a password check ran on the event loop")
            # The loop's pauses beyond its own idle ones over as long a time: under two checks' worth (ten checks on
            # it: ten checks' worth).
            beyond = busy[0] - idle[0] * busy[1] / max(idle[1], 1e-6)
            tries.append("%.0f ms more than idle (idle %.0f ms in %.0f ms; busy %.0f ms in %.0f ms)" % (
                beyond * 1000, idle[0] * 1000, idle[1] * 1000, busy[0] * 1000, busy[1] * 1000))
            if beyond < 2 * one_check:
                break
        else:
            self.fail("the loop stood still in every try (one check %.0f ms): %s" % (one_check * 1000,
                                                                                     "; ".join(tries)))
        self.assertLessEqual(most[0], web_app.HASHING_AT_ONCE)

    def test_right_passwords_are_limited_per_address_too(self):
        from opendmt3.server.web import app as web_app
        self.make()
        codes = [self.api_sign_in(self.client).status_code for _ in range(web_app.SIGN_INS)]
        self.assertEqual(set(codes), {200})
        # One more within the minute waits, right password or not; another address does not.
        refused = self.api_sign_in(self.client)
        self.assertEqual((refused.status_code, refused.json()["error"]["code"]), (429, "too_many_tries"))
        self.assertEqual(self.api_sign_in(self.client_at("198.51.100.20")).status_code, 200)
        # The form counts the same way.
        self.assertEqual(self.sign_in(self.client).status_code, 429)

    def test_wrong_passwords_from_one_ipv6_network_count_together(self):
        self.make()
        # Five addresses of one /64: one sender.
        for n in range(5):
            self.assertEqual(self.api_sign_in(self.client_at("2001:db8::%x" % (n + 1)), password="nope1234")
                             .status_code, 401)
        self.assertEqual(self.api_sign_in(self.client_at("2001:db8::ffff")).status_code, 429)
        # Another network is another sender.
        self.assertEqual(self.api_sign_in(self.client_at("2001:db8:0:1::1")).status_code, 200)

    def test_wrong_passwords_for_one_id_from_many_addresses_hold_it_but_never_on_this_pc(self):
        from opendmt3.server.web import app as web_app
        self.make()
        for n in range(web_app.ID_TRIES):
            self.assertEqual(self.api_sign_in(self.client_at("198.51.100.%d" % n), password="nope1234").status_code,
                             401)
        # A fresh address, the right password: the ID waits.
        held = self.api_sign_in(self.client_at("203.0.113.77"))
        self.assertEqual((held.status_code, held.json()["error"]["code"]), (429, "too_many_tries"))
        page = self.sign_in(self.client_at("203.0.113.78"))
        self.assertIn("Too many wrong passwords for this ID", page.text)
        # The server PC itself: the owner is never shut out of their own server.
        self.assertEqual(self.api_sign_in(self.local).status_code, 200)

    # ------------------------------------------------------------------------------ behind a proxy

    def test_a_forwarded_request_is_never_from_this_pc(self):
        # The review's attack: from 127.0.0.1 (a proxy on this PC), saying it is 127.0.0.1, at 127.0.0.1.
        forged = {"X-Forwarded-For": "127.0.0.1"}
        r = self.local.get("/owner", headers=forged, follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/signin"))
        row = self.make()
        token = self.site.once(row["id"])
        r = self.local.get("/signin/once/" + token, headers={"Forwarded": "for=127.0.0.1"}, follow_redirects=False)
        self.assertEqual(r.headers["location"], "/signin")

    def test_a_visitor_through_the_published_port_cannot_pass_as_this_pc(self):
        from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
        from starlette.testclient import TestClient
        # --proxy given as a whole network (Docker's): a visitor through the published port seems to come from the
        # network's gateway, which is in it, so their X-Forwarded-For is believed.
        trusting = ProxyHeadersMiddleware(self.app, trusted_hosts="172.16.0.0/12")

        async def from_the_gateway(scope, receive, send):
            if scope["type"] == "http":
                scope = dict(scope, client=("172.17.0.1", 40000))
            await trusting(scope, receive, send)

        visitor = TestClient(from_the_gateway, base_url="http://127.0.0.1")
        r = visitor.get("/owner", headers={"X-Forwarded-For": "127.0.0.1"}, follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/signin"))
        store = self.site.accounts()
        self.assertEqual(store.all(), [])
        store.db.close()

    # ------------------------------------------------------------------------------- the cabinets

    def with_a_cabinet(self, player):
        """A game server with one cabinet online, `player` logged in on it."""
        class Answer:
            version = "1.2.3.4"

        class Link:
            online, address, answer = True, "203.0.113.7:51234", Answer()

        Link.player = player
        # The site reads the links through the game server's own copy of them (GameServer.live, under its lock).
        from opendmt3.server.server import GameServer
        self.site.game_server = type("Game", (), {"connections": {Link()}, "started": 0, "lock": threading.Lock(),
                                                  "live": GameServer.live, "received": GameServer.received})()

    def test_players_see_who_plays_on_a_cabinet_but_not_its_address_or_login_id(self):
        self.make("BOSS", dj="DJ BOSS", admin=True)
        self.make()
        self.with_a_cabinet("BOSS")
        player = self.api_sign_in(self.client).json()["token"]
        listed = self.client.get("/api/v1/cabinets", headers={"Authorization": "Bearer " + player}).json()
        self.assertEqual(listed, {"cabinets": [{"player": "DJ BOSS"}]})
        self.sign_in(self.client)
        home = self.client.get("/").text
        self.assertIn("DJ BOSS", home)
        self.assertNotIn("203.0.113.7", home)
        self.assertNotIn("BOSS<", home.replace("DJ BOSS", ""))
        # An admin sees it all, as before.
        boss = self.api_sign_in(self.client_at("198.51.100.30"), "BOSS").json()["token"]
        listed = self.client.get("/api/v1/cabinets", headers={"Authorization": "Bearer " + boss}).json()["cabinets"]
        self.assertEqual((listed[0]["address"], listed[0]["login_id"], listed[0]["player"]),
                         ("203.0.113.7:51234", "BOSS", "DJ BOSS"))
        admin = self.client_at("198.51.100.31")
        self.sign_in(admin, "BOSS")
        self.assertIn("203.0.113.7:51234", admin.get("/").text)

    # ---------------------------------------------------------------------------- sign-in, sign-out

    def test_signing_out_ends_the_cookie_wherever_it_was_copied(self):
        self.make()
        token = self.api_sign_in(self.client).json()["token"]
        self.sign_in(self.client)
        copied = self.client.cookies.get("opendmt3")
        page = self.client.get("/").text
        csrf = page.split('name="csrf" value="', 1)[1].split('"', 1)[0]
        self.client.post("/signout", data={"csrf": csrf}, follow_redirects=False)
        # The cookie as it was before the sign-out, in another browser: no longer signed in.
        other = self.client_at("198.51.100.40")
        other.cookies.set("opendmt3", copied)
        self.assertEqual(other.get("/", follow_redirects=False).status_code, 303)
        # The launcher's token is not a sign-in on the site: it goes on until the password changes.
        self.assertEqual(self.client.get("/api/v1/me", headers={"Authorization": "Bearer " + token}).status_code, 200)
        # Signing in again works, with a new cookie.
        self.assertEqual(self.sign_in(self.client).status_code, 303)
        self.assertEqual(self.client.get("/", follow_redirects=False).status_code, 200)

    def test_another_sites_form_cannot_sign_a_visitor_in(self):
        self.make()
        # As a page of another site would post it: the right ID and password of the attacker's account, no token.
        r = self.client.post("/signin", data={"login_id": "NOVA", "password": "pass1234"}, follow_redirects=False)
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(self.client.cookies.get("opendmt3"))
        r = self.client.post("/signin", data={"csrf": "made-up", "login_id": "NOVA", "password": "pass1234"},
                             follow_redirects=False)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.get("/", follow_redirects=False).status_code, 303)

    def test_the_owner_page_asks_for_a_password_of_the_rules_length(self):
        from opendmt3.server.services import accounts
        self.assertIn('minlength="%d"' % accounts.PASSWORD_MIN, self.local.get("/owner").text)

    # ------------------------------------------------------------------------------ the player list

    def test_the_player_list_reads_the_plays_once_for_everyone(self):
        from opendmt3.server import db
        from opendmt3.server.services import records
        WebTest.card_tables(self)
        rows = [self.make("P%d" % n, dj="P%d" % n, admin=(n == 0)) for n in range(6)]
        connection = db.connect(self.site.db_path)
        try:
            for n, row in enumerate(rows):
                for k in range(n):
                    records.Records(connection).add(row["id"], "x", 0, {"song": 1 + k, "pattern": 1, "score": 1,
                                                                        "counts": [0] * 7, "raw": bytes(47)})
        finally:
            connection.close()
        auth = {"Authorization": "Bearer " + self.api_sign_in(self.client, "P0").json()["token"]}
        expected = {row["id"]: self.client.get("/api/v1/djs/%d" % row["id"], headers=auth).json()["dj_card"]
                    for row in rows}
        opened = []
        real = db.connect

        def counted(path, **kwargs):
            opened.append(path)
            return real(path, **kwargs)

        # Not one query per player: the per-player one would fail the call.
        with mock.patch.object(records.Records, "cleared", side_effect=AssertionError("one query per player")), \
                mock.patch.object(db, "connect", counted):
            listed = self.client.get("/api/v1/players", headers=auth).json()["players"]
        self.assertEqual({p["player"]: p["dj_card"] for p in listed}, expected)
        self.assertEqual(listed[5]["dj_card"]["exp"], 5 * 9)
        # The token's check and the list: one connection for the whole request, however many players there are.
        self.assertEqual(len(opened), 1)


@unittest.skipUnless(WEB and importlib.util.find_spec("uvicorn"), "needs the web libraries and uvicorn")
class ProxyTest(unittest.TestCase):
    """Behind a reverse proxy (--proxy) the site believes its forwarded headers, from that proxy only."""

    def run_app(self, args, scope_client, headers):
        import argparse
        import asyncio
        import uvicorn
        from opendmt3.server.__main__ import web_config
        seen = {}

        async def app(scope, receive, send):
            seen["client"], seen["scheme"] = scope["client"][0], scope["scheme"]
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        config = web_config(uvicorn, app, argparse.Namespace(host="127.0.0.1", web_port=0, proxy=args))
        config.load()
        scope = {"type": "http", "client": (scope_client, 5000), "scheme": "http", "headers": headers,
                 "method": "GET", "path": "/", "query_string": b"", "server": ("127.0.0.1", 4730),
                 "http_version": "1.1", "root_path": ""}

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            pass

        asyncio.run(config.loaded_app(scope, receive, send))
        return seen

    def test_the_site_listens_where_web_host_says_and_on_host_without_it(self):
        import argparse
        import uvicorn
        from opendmt3.server.__main__ import web_config
        app = object()
        both = argparse.Namespace(host="0.0.0.0", web_host="127.0.0.1", web_port=4730, proxy="127.0.0.1")
        # The game's port open to everyone, the site on this PC only, behind its proxy.
        self.assertEqual(web_config(uvicorn, app, both).host, "127.0.0.1")
        self.assertEqual(web_config(uvicorn, app, argparse.Namespace(host="0.0.0.0", web_host=None, web_port=4730,
                                                                     proxy=None)).host, "0.0.0.0")

    def test_the_proxys_headers_count_only_from_the_proxy(self):
        forwarded = [(b"x-forwarded-for", b"203.0.113.9"), (b"x-forwarded-proto", b"https")]
        # From the proxy named with --proxy: the visitor's own address, and HTTPS.
        self.assertEqual(self.run_app("127.0.0.1", "127.0.0.1", forwarded), {"client": "203.0.113.9", "scheme": "https"})
        # From anyone else, or without --proxy: the headers are ignored.
        self.assertEqual(self.run_app("127.0.0.1", "198.51.100.4", forwarded), {"client": "198.51.100.4", "scheme": "http"})
        self.assertEqual(self.run_app(None, "127.0.0.1", forwarded), {"client": "127.0.0.1", "scheme": "http"})


class SecretTest(unittest.TestCase):
    def test_a_weak_secret_is_replaced(self):
        from opendmt3.server.web import session
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        path = os.path.join(tmp, session.SECRET_FILE)
        for weak in ("", "abcd", "not hex at all"):
            with open(path, "w") as f:
                f.write(weak)
            secret = session.load_secret(tmp)
            self.assertEqual(len(secret), session.SECRET_BYTES, repr(weak))
        # A good one stays as it is.
        self.assertEqual(session.load_secret(tmp), secret)


if __name__ == "__main__":
    unittest.main()
