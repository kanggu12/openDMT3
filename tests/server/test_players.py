"""Tests for what an admin controls of a player and what a player decorates (services/players.py, web/control.py,
web/player_pages.py, the account area): the game's login answer carries each of them (a banned card refused, a
decorated DJ card, the MAX points and the level served, a session's MAX points kept), the admin's page of a player and
its API twins, a ban said to the player, the picture made safe, signing out elsewhere, deleting one's own account,
and a new name and password taken by the launcher and the game. Every name, reason and picture is made up.
"""

import asyncio
import io
import json
import os
import random
import shutil
import struct
import tempfile
import unittest

from opendmt3.server import db, messages
from opendmt3.server.server import GameServer
from opendmt3.server.services import accounts, cards, players, records
# The game server's tests, by their module: a class named here would be found and run again in this file.
from tests.server import test_server as game
from tests.server.test_api import ApiBase
from tests.server.test_web import WEB

# The DJ card's tables as a song list's reading leaves them, made up: two icons, two plates, a pattern, three levels.
TABLES = {"icon": [{"number": 1, "grade": ""}, {"number": 6, "grade": "S"}],
          "plate": [{"number": 32768, "grade": ""}, {"number": 32769, "grade": ""}],
          "pattern": [{"number": 0, "grade": ""}, {"number": 7, "grade": "A"}],
          "points": {"1": 9}, "levels": [12, 42, 92]}


def made_up_picture(width=300, height=200, kind="PNG"):
    """A picture drawn here (two colours side by side), as a file of `kind`."""
    from PIL import Image
    picture = Image.new("RGB", (width, height), (40, 90, 200))
    picture.paste((250, 180, 60), (0, 0, width // 2, height))
    out = io.BytesIO()
    picture.save(out, kind)
    return out.getvalue()


def write_tables(folder):
    """TABLES and a stand-in picture of each choice, where the site and the game server read them."""
    with open(os.path.join(folder, cards.FILE), "w") as f:
        json.dump(TABLES, f)
    for kind in cards.KINDS:
        os.makedirs(os.path.join(folder, cards.FOLDER, kind), exist_ok=True)
        for item in TABLES[kind]:
            with open(os.path.join(folder, cards.FOLDER, kind, "%d.png" % item["number"]), "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n" + kind.encode())


class RulesTest(unittest.TestCase):
    """The rules of services/players.py on a database of their own."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = db.connect(os.path.join(self.tmp, "server.sqlite"))
        self.accounts = accounts.Accounts(self.db)
        self.nova = self.accounts.create("NOVA", "pass1234", "DJ NOVA")
        self.rio = self.accounts.create("RIO", "pass1234", "RIO")
        self.players = players.Players(self.db)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)

    def row(self, login_id="NOVA"):
        return self.accounts.by_login(login_id)

    def test_the_balance_stays_in_its_range_and_unlimited_shows_the_most(self):
        self.players.set_points("NOVA", 900_000)
        # Many at once (every player without IDs), each kept within the range.
        self.assertEqual(self.players.add_points(None, 200_000), 2)
        self.assertEqual((self.row()["max_points"], self.row("RIO")["max_points"]), (players.POINTS_MOST, 200_000))
        self.players.add_points(["RIO"], -300_000)
        self.assertEqual(self.row("RIO")["max_points"], 0)
        for wrong in ("x", 1.5, True, -1, players.POINTS_MOST + 1):
            with self.assertRaises(players.PlayerError):
                self.players.set_points("NOVA", wrong)
        with self.assertRaises(players.PlayerError):
            self.players.add_points(["NOVA"], 0)
        with self.assertRaises(players.PlayerError):
            self.players.add_points(["NOBODY"], 5)
        self.players.set_points("NOVA", 4200)
        self.players.set_unlimited("NOVA", True)
        self.assertEqual(players.points_shown(self.row()), players.UNLIMITED_SHOWN)
        # The balance stays underneath, and shows again when the switch is off.
        self.players.set_unlimited("NOVA", False)
        self.assertEqual(players.points_shown(self.row()), 4200)

    def test_a_session_earns_up_to_what_a_login_can(self):
        self.assertTrue(self.players.earned(self.nova["id"], 180))
        self.assertFalse(self.players.earned(self.nova["id"], players.EARNED_MOST + 1))
        self.assertFalse(self.players.earned(self.nova["id"], -5))
        self.assertEqual(self.row()["max_points"], 180)

    def test_a_level_set_by_an_admin_grows_with_the_plays_after_it(self):
        # Levels hold up to 12, 42 and 92: level 3 starts at 43.
        self.assertEqual(players.level_start(TABLES, 1), 0)
        self.assertEqual(players.level_start(TABLES, 3), 43)
        extra = self.players.set_level("NOVA", 3, TABLES, earned=9)
        self.assertEqual(extra, 34)
        self.assertEqual(cards.level(TABLES, players.experience(self.row(), 9)), 3)
        # Nine more experience from a stage cleared: still level 3, above its start.
        self.assertEqual(players.experience(self.row(), 18), 52)
        with self.assertRaises(players.PlayerError):
            self.players.set_level("NOVA", 4, TABLES, earned=9)
        with self.assertRaises(players.PlayerError):
            self.players.set_level("NOVA", 2, {}, earned=9)
        self.players.clear_level("NOVA")
        self.assertEqual(players.experience(self.row(), 9), 9)

    def test_a_ban_disables_with_its_reason_and_never_the_last_admin(self):
        self.players.ban("NOVA", "  Made-up reason  ")
        row = self.row()
        self.assertEqual((row["disabled"], row["ban_reason"]), (1, "Made-up reason"))
        for reason in ("", "two\nlines", "x" * (players.REASON_MAX + 1)):
            with self.assertRaises(players.PlayerError):
                self.players.ban("RIO", reason)
        self.players.unban("NOVA")
        self.assertEqual((self.row()["disabled"], self.row()["ban_reason"]), (0, None))
        # Enabled from the Players list (or its API twin), a ban's reason goes too.
        self.players.ban("NOVA", "Made-up reason")
        self.accounts.set_disabled("NOVA", False)
        self.assertIsNone(self.row()["ban_reason"])
        boss = self.accounts.create("BOSS", "pass1234", "BOSS", is_admin=True)
        with self.assertRaises(accounts.AccountError):
            self.players.ban("BOSS", "Made-up reason")
        self.assertEqual((self.row("BOSS")["disabled"], self.row("BOSS")["ban_reason"]), (0, None))
        # Every change made to NOVA is in their own history, newest first.
        said = [r["what"] for r in self.players.history(self.nova["id"])]
        self.assertEqual(said[:3], ["enabled the account NOVA", "banned NOVA: Made-up reason",
                                    "disabled the account NOVA"])
        self.assertEqual(said.count("banned NOVA: Made-up reason"), 2)
        self.assertEqual(self.players.history(boss["id"])[0]["what"], "made the account BOSS")

    @unittest.skipUnless(WEB, "needs Pillow (with the web libraries)")
    def test_a_picture_is_made_a_square_png_of_its_pixels_alone(self):
        from PIL import Image
        for kind in ("PNG", "JPEG", "WEBP", "GIF"):
            png = players.make_picture(made_up_picture(kind=kind))
            with Image.open(io.BytesIO(png)) as made:
                self.assertEqual((made.format, made.size, made.mode), ("PNG", (256, 256), "RGBA"), kind)
                # Nothing of the upload but its pixels: no text, no profile.
                self.assertEqual(made.info.keys() - {"dpi"}, set(), kind)
        for wrong in (b"not a picture", b"<svg xmlns='http://www.w3.org/2000/svg'/>", made_up_picture(kind="BMP"),
                      b"\x89PNG\r\n\x1a\n" + bytes(64)):
            with self.assertRaises(players.PlayerError):
                players.make_picture(wrong)
        with self.assertRaises(players.PlayerError) as caught:
            players.make_picture(bytes(players.PICTURE_UPLOAD_MOST + 1))
        self.assertEqual(caught.exception.key, "error.player.picture.size")
        with self.assertRaises(players.PlayerError) as caught:
            players.make_picture(made_up_picture(5000, 4000))
        self.assertEqual(caught.exception.key, "error.player.picture.pixels")


class GameAnswerTest(game.LoopTest):
    """What the game's card login answer carries of an admin's control and a player's decoration."""

    # The card login's own setting up and steps (test_server.py), without its tests.
    card = game.CardLoginTest.card
    login_answer = game.CardLoginTest.login_answer
    asyncTearDown = game.CardLoginTest.asyncTearDown

    async def asyncSetUp(self):
        # As CardLoginTest sets up: a player on a database of its own, the game server, a client online.
        await super().asyncSetUp()
        self.tmp = tempfile.mkdtemp()
        self.db = db.connect(os.path.join(self.tmp, "server.sqlite"))
        self.accounts = accounts.Accounts(self.db)
        self.row = self.accounts.create("NOVA", "pass1234", "DJ NOVA")
        self.records = records.Records(self.db)
        self.server = await GameServer("127.0.0.1", 0, rng=random.Random(5), accounts=self.accounts,
                                       records=self.records).start()
        reader, writer = await asyncio.open_connection("127.0.0.1", self.server.port)
        self.client = game.StandInClient(reader, writer)
        await self.client.handshake()
        write_tables(self.tmp)
        self.server.data = self.tmp
        self.players = players.Players(self.db)

    async def test_a_banned_card_is_refused_with_the_failed_login_alone(self):
        self.players.ban("NOVA", "Made-up reason")
        await self.card(self.row["card"])
        # The result alone: no records, no player, no first places.
        result = await self.client.read(9)
        self.assertEqual((result[0], result[8]), (0x64, messages.AUTH_FAILED))
        self.assertIsNone(next(iter(self.server.connections)).player)
        # Lifted: the same card logs in again.
        self.players.unban("NOVA")
        await self.card(self.row["card"])
        info = (await self.login_answer())["info"]
        self.assertEqual(info[20:38].decode("utf-16-le").rstrip("\0"), "DJ NOVA")

    async def test_a_decorated_card_with_its_points_and_level_is_served(self):
        # The player's own choices (the account page's), an admin's MAX points and level.
        self.accounts.set_card("NOVA", TABLES, icon=6, plate=32768, pattern=7, comment="MADE UP")
        self.players.set_points("NOVA", 4200)
        self.players.set_level("NOVA", 3, TABLES, earned=0)
        await self.card(self.row["card"])
        info = (await self.login_answer())["info"]
        self.assertEqual(struct.unpack_from("<II", info, messages.ICON_AT), (6, (7 << 16) | 32768))
        self.assertEqual(struct.unpack_from("<I", info, messages.COMMENT_STYLE_AT)[0], 1)
        self.assertEqual(info[54:78].decode("utf-16-le").rstrip("\0"), "MADE UP")
        # Level 3's start (43), which the game's own table shows as Lv 3.
        self.assertEqual(struct.unpack_from("<I", info, messages.EXP_AT)[0], 43)
        self.assertEqual(struct.unpack_from("<I", info, messages.POINTS_AT)[0], 4200)
        # The note skin after the comment stays 0 (the one folder every client has).
        self.assertEqual(info[78:82], bytes(4))
        self.players.set_unlimited("NOVA", True)
        await self.card(self.row["card"])
        info = (await self.login_answer())["info"]
        self.assertEqual(struct.unpack_from("<I", info, messages.POINTS_AT)[0], players.UNLIMITED_SHOWN)

    def points(self, user, earned):
        msg = bytearray(16)
        msg[0] = 0x79
        struct.pack_into("<II", msg, 8, user, earned)
        return bytes(msg)

    async def until_points(self, want):
        for _ in range(50):
            if self.accounts.by_login("NOVA")["max_points"] == want:
                return
            await asyncio.sleep(0.02)
        self.assertEqual(self.accounts.by_login("NOVA")["max_points"], want)

    async def test_a_sessions_max_points_are_kept_for_the_player_logged_in(self):
        # A guest's points are nobody's.
        self.client.write(self.points(self.row["id"], 150))
        await self.client.writer.drain()
        await asyncio.sleep(0.2)
        self.assertEqual(self.accounts.by_login("NOVA")["max_points"], 0)
        await self.card(self.row["card"])
        await self.login_answer()
        self.client.write(self.points(self.row["id"], 180))
        await self.client.writer.drain()
        await self.until_points(180)
        # Another account's number, or more than a login can earn in all, is not kept.
        self.client.write(self.points(self.row["id"] + 1, 100))
        self.client.write(self.points(self.row["id"], players.EARNED_MOST))
        await self.client.writer.drain()
        await asyncio.sleep(0.2)
        self.assertEqual(self.accounts.by_login("NOVA")["max_points"], 180)
        # The next login shows the balance on the song select.
        await self.card(self.row["card"])
        info = (await self.login_answer())["info"]
        self.assertEqual(struct.unpack_from("<I", info, messages.POINTS_AT)[0], 180)

    async def test_a_new_name_and_password_are_taken_at_the_next_login(self):
        old_card = self.row["card"]
        # What the account page and its API twin do (accounts.set_dj_name, set_password).
        self.accounts.set_dj_name("NOVA", "NOVA X")
        self.accounts.set_password("NOVA", "fresh567")
        # The launcher signs in with the new password and gets the new card (GET /api/v1/me's card).
        fresh = self.accounts.check_web("NOVA", "fresh567")
        self.assertIsNotNone(fresh)
        self.assertNotEqual(fresh["card"], old_card)
        await self.card(old_card)
        result = await self.client.read(9)
        self.assertEqual(result[8], messages.AUTH_FAILED)
        await self.card(fresh["card"])
        info = (await self.login_answer())["info"]
        self.assertEqual(info[20:38].decode("utf-16-le").rstrip("\0"), "NOVA X")


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class AdminPlayerPageTest(ApiBase):
    """The admin's page of one player, its controls, and their API twins."""

    def setUp(self):
        super().setUp()
        write_tables(self.tmp)
        self.boss = self.admin()
        self.nova = self.make()

    def post(self, path, **data):
        token = self.form_token(self.client, path)
        return self.client.post(path, data=dict(data, csrf=token))

    def test_the_page_shows_the_player_and_each_control_changes_them(self):
        page = self.client.get("/admin/players/nova")
        self.assertEqual(page.status_code, 200)
        for part in ("DJ NOVA", "MAX points", "Unlimited MAX points", 'role="switch"', 'aria-checked="false"', "Ban"):
            self.assertIn(part, page.text)
        # The list links each player to their page.
        self.assertIn('href="/admin/players/NOVA"', self.client.get("/admin/players").text)
        self.assertIn("MAX points: 300 now.", self.post("/admin/players/NOVA", action="points_set", amount="300").text)
        self.assertIn("MAX points: 250 now.", self.post("/admin/players/NOVA", action="points_add", amount="-50").text)
        page = self.post("/admin/players/NOVA", action="points_set", amount="abc").text
        self.assertIn("MAX points are 0 to 999999", page)
        page = self.post("/admin/players/NOVA", action="unlimited_on").text
        self.assertIn('aria-checked="true"', page)
        self.assertIn("The level is 3 now.", self.post("/admin/players/NOVA", action="level_set", level="3").text)
        self.assertIn("Lv 3", self.client.get("/dj/%d" % self.nova["id"]).text)
        self.post("/admin/players/NOVA", action="card", icon="6", plate="32768", pattern="7", comment="MADE UP")
        row = self.site.accounts().by_login("NOVA")
        self.assertEqual((row["icon"], row["plate"], row["pattern"], row["comment"], row["max_points"],
                          row["unlimited_points"]), (6, 32768, 7, "MADE UP", 250, 1))
        # A ban asks first in the site's own dialog, then says the reason on the page.
        page = self.client.get("/admin/players/NOVA").text
        self.assertIn('data-ask="Ban NOVA?"', page)
        page = self.post("/admin/players/NOVA", action="ban", reason="Made-up reason").text
        self.assertIn("Banned: Made-up reason", page)
        self.assertIn('class="ban-reason">Made-up reason<', page)
        # Every change, in the player's own history, worded in Korean for a Korean reader.
        self.client.cookies.set("opendmt3_lang", "ko")
        page = self.client.get("/admin/players/NOVA").text
        for said in ("NOVA 이용 정지: Made-up reason", "NOVA의 레벨을 3(으)로 정함", "NOVA의 MAX 포인트 무제한 켬",
                     "NOVA의 MAX 포인트 50 뺌"):
            self.assertIn(said, page)
        self.client.cookies.set("opendmt3_lang", "en")
        self.post("/admin/players/NOVA", action="unban")
        self.assertEqual(self.site.accounts().by_login("NOVA")["disabled"], 0)
        # A new password, shown once with the message to send.
        page = self.post("/admin/players/NOVA", action="password").text
        self.assertIn("New password for NOVA, shown this once", page)
        self.assertIn('id="message"', page)

    def test_a_player_page_is_for_admins_and_existing_players_only(self):
        self.assertEqual(self.client.get("/admin/players/NOBODY").status_code, 404)
        from starlette.testclient import TestClient
        player = TestClient(self.app, client=("203.0.113.8", 50003))
        self.sign_in(player)
        self.assertEqual(player.get("/admin/players/NOVA").status_code, 404)

    def test_the_api_controls_a_player_as_the_page_does(self):
        admin = self.token("BOSS")
        r = self.call("POST", "/api/v1/players/nova/max_points", admin, json={"amount": 1000})
        self.assertEqual((r.status_code, r.json()["max_points"]), (200, 1000))
        r = self.call("POST", "/api/v1/players/NOVA/max_points", admin, json={"add": -1500})
        self.assertEqual(r.json()["max_points"], 0)
        r = self.call("POST", "/api/v1/players/NOVA/max_points", admin, json={"unlimited": True})
        self.assertEqual((r.json()["unlimited_points"], r.json()["points_shown"]), (True, 999999))
        self.refused(self.call("POST", "/api/v1/players/NOVA/max_points", admin, json={"unlimited": "yes"}),
                     400, "bad_request")
        self.refused(self.call("POST", "/api/v1/players/NOVA/max_points", admin, json={"amount": -1}), 400, "refused")
        r = self.call("POST", "/api/v1/players/max_points", admin, json={"add": 7, "login_ids": ["nova", "BOSS"]})
        self.assertEqual(r.json(), {"players": 2})
        self.refused(self.call("POST", "/api/v1/players/max_points", admin, json={"add": 7, "login_ids": ["NOBODY"]}),
                     404, "unknown_player")
        r = self.call("POST", "/api/v1/players/NOVA/level", admin, json={"level": 2})
        self.assertEqual((r.json()["dj_card"]["level"], r.json()["exp_extra"]), (2, 13))
        self.refused(self.call("POST", "/api/v1/players/NOVA/level", admin, json={"level": 9}), 400, "refused")
        self.assertEqual(self.call("DELETE", "/api/v1/players/NOVA/level", admin).json()["exp_extra"], 0)
        r = self.call("POST", "/api/v1/players/NOVA/ban", admin, json={"reason": "Made-up reason"})
        self.assertEqual((r.json()["banned"], r.json()["ban_reason"]), (True, "Made-up reason"))
        # The launcher's sign-in is told why; a wrong password is told nothing more than for any account.
        r = self.call("POST", "/api/v1/session", json={"login_id": "NOVA", "password": "pass1234"})
        self.assertEqual((r.status_code, r.json()["error"]["code"], r.json()["error"]["reason"]),
                         (403, "banned", "Made-up reason"))
        self.refused(self.call("POST", "/api/v1/session", json={"login_id": "NOVA", "password": "nope1234"}),
                     401, "wrong_sign_in")
        self.assertFalse(self.call("DELETE", "/api/v1/players/NOVA/ban", admin).json()["banned"])
        self.refused(self.call("POST", "/api/v1/players/NOVA/ban", admin, json={"reason": ""}), 400, "refused")
        # A player's token makes no admin's call.
        self.refused(self.call("GET", "/api/v1/players/BOSS", self.token()), 403, "admin_only")
        state = self.call("GET", "/api/v1/players/NOVA", admin).json()
        self.assertEqual(state["history"][0]["what"], "enabled the account NOVA")
        self.assertEqual(state["card_end"], self.site.accounts().by_login("NOVA")["card"][-4:])

    def test_a_ban_ends_every_sign_in_and_lifting_it_brings_none_back(self):
        from starlette.testclient import TestClient
        browser = TestClient(self.app, client=("203.0.113.12", 50007))

        def signed_in():
            # NOVA on the site in a browser, a launcher's sign-in token and a named token of a program of theirs.
            self.sign_in(browser)
            launcher = self.token()
            named = self.call("POST", "/api/v1/tokens", launcher, json={"name": "bot", "scope": "write"}).json()
            return launcher, named["token"]

        def working(launcher, named):
            # What each answers: the Account page (303 back to the sign-in once it ends) and the account's API call.
            return (browser.get("/account", follow_redirects=False).status_code,
                    self.call("GET", "/api/v1/me", launcher).status_code, self.call("GET", "/api/v1/me", named).status_code)

        card = self.site.accounts().by_login("NOVA")["card"]
        boss = self.token("BOSS")
        # Banned on the player's page, lifted there; banned through the API, lifted with the Players list's Enable.
        for ban, lift in ((lambda: self.post("/admin/players/NOVA", action="ban", reason="Made-up reason"),
                           lambda: self.post("/admin/players/NOVA", action="unban")),
                          (lambda: self.call("POST", "/api/v1/players/NOVA/ban", boss, json={"reason": "Made-up"}),
                           lambda: self.call("POST", "/api/v1/players/NOVA/enable", boss))):
            launcher, named = signed_in()
            self.assertEqual(working(launcher, named), (200, 200, 200))
            ban()
            # Every one ends at the ban.
            self.assertEqual(working(launcher, named), (303, 401, 401))
            lift()
            # Lifting it brings none of them back: the player signs in anew, and that works.
            self.assertEqual(working(launcher, named), (303, 401, 401))
            self.assertEqual(working(*signed_in()), (200, 200, 200))
        # The card number stays: the card keeps logging in at the cabinet once the ban is lifted.
        self.assertEqual(self.site.accounts().by_login("NOVA")["card"], card)

    def test_a_banned_player_is_told_the_reason_when_signing_in(self):
        from starlette.testclient import TestClient
        store = self.site.accounts()
        try:
            players.Players(store.db).ban("NOVA", "Made-up reason", who="BOSS")
        finally:
            store.db.close()
        visitor = TestClient(self.app, client=("203.0.113.9", 50004))
        r = self.sign_in(visitor)
        self.assertEqual(r.status_code, 403)
        self.assertIn("This account is banned: Made-up reason", r.text)
        r = self.sign_in(visitor, password="nope1234")
        self.assertEqual(r.status_code, 401)
        self.assertNotIn("Made-up reason", r.text)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class AccountAreaTest(ApiBase):
    """The account area: the profile and its picture, the account, its security."""

    def setUp(self):
        super().setUp()
        write_tables(self.tmp)
        self.nova = self.make()
        self.sign_in(self.client)

    def test_the_page_has_three_sections_and_the_card_preview(self):
        page = self.client.get("/account").text
        for part in ('id="profile"', 'id="account"', 'id="security"', 'class="card-preview"', "data-card-editor",
                     'data-reveal="pw-new"', "/static/profile.js", 'id="password-rules"'):
            self.assertIn(part, page)
        self.client.cookies.set("opendmt3_lang", "ko")
        page = self.client.get("/account").text
        for part in ("프로필", "보안", "다른 곳 모두 로그아웃", "내 계정 삭제"):
            self.assertIn(part, page)

    def test_a_password_mistake_is_said_under_its_field(self):
        token = self.form_token(self.client, "/account")
        page = self.client.post("/account", data={"csrf": token, "action": "password", "current": "pass1234",
                                                  "new": "fresh567", "again": "other567"}).text
        self.assertIn('id="pw-again-error"', page)
        self.assertIn('aria-invalid="true" autofocus', page)
        self.assertIn('data-open="security"', page)

    def upload(self, data, client=None):
        client = client or self.client
        token = self.form_token(client, "/account")
        return client.post("/account/picture", data={"csrf": token}, files={"file": ("me.png", data, "image/png")},
                           follow_redirects=False)

    def test_a_picture_is_uploaded_served_and_removed(self):
        r = self.upload(made_up_picture(kind="JPEG"))
        self.assertEqual(r.headers["location"], "/account?done=picture#profile")
        row = self.site.accounts().by_login("NOVA")
        self.assertEqual(row["picture"], 1)
        page = self.client.get("/account?done=picture").text
        self.assertIn("/pictures/%d.png?v=1" % row["id"], page)
        self.assertIn("Your picture is saved.", page)
        served = self.client.get("/pictures/%d.png" % row["id"])
        self.assertEqual((served.status_code, served.headers["content-type"]), (200, "image/png"))
        self.assertTrue(served.content.startswith(b"\x89PNG"))
        # The DJ page and the API show it too.
        self.assertIn("/pictures/%d.png" % row["id"], self.client.get("/dj/%d" % row["id"]).text)
        api = self.call("GET", "/api/v1/djs/%d/picture.png" % row["id"], self.token())
        self.assertEqual(api.content, served.content)
        # Not a picture, or a form from elsewhere: refused, said on the page.
        r = self.upload(b"<svg onload='made-up'/>")
        self.assertEqual(r.headers["location"], "/account?picture=kind#profile")
        self.assertIn("That file is not a picture.", self.client.get(r.headers["location"]).text)
        r = self.client.post("/account/picture", data={"csrf": "nope"}, files={"file": ("me.png", b"x", "image/png")},
                             follow_redirects=False)
        self.assertEqual(r.headers["location"], "/account?picture=expired#profile")
        token = self.form_token(self.client, "/account")
        r = self.client.post("/account/picture", data={"csrf": token, "action": "clear"}, follow_redirects=False)
        self.assertEqual(r.headers["location"], "/account?done=picture_clear#profile")
        self.assertEqual(self.client.get("/pictures/%d.png" % row["id"]).status_code, 404)

    def test_a_picture_past_its_limit_stops_at_that_byte(self):
        r = self.upload(bytes(players.PICTURE_UPLOAD_MOST + 10))
        self.assertEqual(r.headers["location"], "/account?picture=size#profile")
        self.assertIn("A picture is up to 2 MB.", self.client.get(r.headers["location"]).text)
        # Through the API, the body itself.
        token = self.token()
        self.refused(self.call("POST", "/api/v1/me/picture", token, content=bytes(players.PICTURE_UPLOAD_MOST + 10)),
                     413, "too_large")
        self.refused(self.call("POST", "/api/v1/me/picture", token, content=b"made-up"), 400, "refused")
        r = self.call("POST", "/api/v1/me/picture", token, content=made_up_picture())
        self.assertEqual(r.json()["picture"], 1)

    def test_signing_out_everywhere_else_keeps_this_sign_in(self):
        from starlette.testclient import TestClient
        other = TestClient(self.app, client=("203.0.113.10", 50005))
        self.sign_in(other)
        self.assertEqual(other.get("/account", follow_redirects=False).status_code, 200)
        launcher = self.token()
        token = self.form_token(self.client, "/account")
        r = self.client.post("/account", data={"csrf": token, "action": "signout_others"}, follow_redirects=False)
        self.assertEqual(r.headers["location"], "/account?done=signout_others")
        self.assertIn("Every other browser is signed out.", self.client.get("/account?done=signout_others").text)
        self.assertEqual(other.get("/account", follow_redirects=False).status_code, 303)
        # The launcher stays signed in.
        self.assertEqual(self.call("GET", "/api/v1/me", launcher).status_code, 200)

    def test_deleting_ones_own_account_asks_for_its_password(self):
        token = self.form_token(self.client, "/account")
        page = self.client.post("/account", data={"csrf": token, "action": "delete_me", "current": "nope1234"}).text
        self.assertIn('id="delete-current-error"', page)
        self.assertIsNotNone(self.site.accounts().by_login("NOVA"))
        token = self.form_token(self.client, "/account")
        r = self.client.post("/account", data={"csrf": token, "action": "delete_me", "current": "pass1234"},
                             follow_redirects=False)
        self.assertEqual(r.headers["location"], "/signin?gone=1")
        self.assertIsNone(self.site.accounts().by_login("NOVA"))
        self.assertIn("Your account is deleted.", self.client.get("/signin?gone=1").text)

    def test_the_only_admin_keeps_their_account(self):
        from starlette.testclient import TestClient
        self.make("BOSS", dj="BOSS", admin=True)
        boss = TestClient(self.app, client=("203.0.113.11", 50006))
        self.sign_in(boss, "BOSS")
        token = self.form_token(boss, "/account")
        page = boss.post("/account", data={"csrf": token, "action": "delete_me", "current": "pass1234"}).text
        self.assertIn("You are the server&#39;s only admin", page)
        self.assertIsNotNone(self.site.accounts().by_login("BOSS"))
        self.refused(self.call("DELETE", "/api/v1/me", self.token("BOSS"), json={"password": "pass1234"}),
                     400, "refused")

    def test_a_new_password_gives_the_launcher_the_card_the_game_logs_in_with(self):
        r = self.call("POST", "/api/v1/me/password", self.token(), json={"password": "pass1234",
                                                                         "new_password": "fresh567"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["card"], self.site.accounts().by_login("NOVA")["card"])
        r = self.call("POST", "/api/v1/me/dj_name", r.json()["token"], json={"dj_name": "NOVA X"})
        self.assertEqual(self.site.accounts().by_card(r.json()["card"])["dj_name"], "NOVA X")


if __name__ == "__main__":
    unittest.main()
