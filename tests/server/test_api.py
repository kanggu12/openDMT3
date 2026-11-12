"""Tests for the API's twins of the site's pages and actions (docs/api.md): the new records and NEW marks, the month's
rankings, a DJ's places, the songs' Find and pictures, the notice, the Status page's list, the plays log and its CSV,
accounts made without a password, admin rights, renaming, the last enabled admin, deleting a backup, the Download
page and the installer, the Licenses page and signing out; the HTTP details every answer keeps (Retry-After, Allow,
Cache-Control); and that the guide and the routes agree, each call answering only whom its row names.

They need the web libraries (Starlette, Jinja2, httpx for the test client); without them they are skipped.
"""

import csv
import io
import os
import re
import time
import unittest

# The site on a temporary data folder with plays, a song list and forms (tests/server/test_site_features.py), and a small
# Windows program with a version resource for the installer.
from tests.server.test_site_features import SiteBase, windows_program
from tests.server.test_web import WEB

# The repository's top folder (this file is in tests/).
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# The open routes programs read beside the API, which the guide documents with it.
PROGRAMS = ("/health", "/updates/{name}")
# A call's row in the guide's tables: `METHOD /path` in the first cell, who may call it in the second.
ROW = re.compile(r"^\| `([A-Z]+) (/[^` ]*)` \| ([^|]*?) \|", re.M)
# What a {name} in a documented path stands for when a test calls it (anything else: 1).
SAMPLES = {"login_id": "NOVA", "name": "nothing.sqlite", "kind": "icon"}
# The words a row's Who may have.
WHO = ("anyone", "signed in", "admin")
# What a row's Takes cell names: a query's ?name=, or a body's "name".
TAKES = re.compile(r'\?(\w+)=|"(\w+)"')
# An error in a row's Errors cell: `400 bad_request`.
ERRORS = re.compile(r"`(\d{3}) (\w+)`")


def guide_rows():
    """Every call the guide's tables document under Calls, as a dict: method, path, who, area (the heading it sits
    under), the names it takes (each ?name= and "name" in its Takes cell) and its errors ((status, code) in its
    Errors cell)."""
    with open(os.path.join(ROOT, "docs", "api.md"), encoding="utf-8") as f:
        text = f.read()
    # Only the Calls section: the shapes and errors after it have no rows of calls.
    calls = text.split("\n## Calls\n", 1)[1].split("\n## ", 1)[0]
    rows, area = [], None
    for line in calls.split("\n"):
        if line.startswith("### "):
            area = line[4:].strip()
        elif ROW.match(line):
            # A row's six cells: the call, who, takes, answers, errors, the page (no cell holds a | of its own).
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            method, path = cells[0].strip("`").split(" ", 1)
            rows.append({"method": method, "path": path, "who": cells[1], "area": area, "cells": len(cells),
                         "takes": {a or b for a, b in TAKES.findall(cells[2])},
                         "errors": {(int(status), code) for status, code in ERRORS.findall(cells[4])}})
    return rows


def documented():
    """Every call the guide's tables document under Calls: (method, path, who)."""
    return [(row["method"], row["path"], row["who"]) for row in guide_rows()]


def shape(path):
    """A path with each {name} (and its converter, as a route writes it) made one mark, so the guide's `{id}` and
    the route's `{cabinet:int}` compare as the same address."""
    return re.sub(r"\{[^}]*\}", "{}", path)


class ApiBase(SiteBase):
    """SiteBase with sign-ins through the API and calls carrying a token."""

    def token(self, login_id="NOVA", password="pass1234", client=None):
        """A token from POST /api/v1/session, as the launcher signs in."""
        r = (client or self.client).post("/api/v1/session", json={"login_id": login_id, "password": password})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["token"]

    def call(self, method, path, token=None, **kwargs):
        """A request to the API with the token (none: without one)."""
        headers = dict(kwargs.pop("headers", {}))
        if token:
            headers["Authorization"] = "Bearer " + token
        return self.client.request(method, path, headers=headers, **kwargs)

    def changes(self):
        """What the change log holds, newest first, read from the database."""
        from opendmt3.server import db
        connection = db.connect(self.site.db_path)
        try:
            return [r[0] for r in connection.execute("SELECT what FROM changes ORDER BY id DESC")]
        finally:
            connection.close()

    def refused(self, response, status, code):
        """The error's code and status, as every error under /api/ gives them. An answer that is no error fails here
        too, with its status and the start of its body."""
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        error = body.get("error") if isinstance(body, dict) else None
        self.assertEqual((response.status_code, (error or {}).get("code")), (status, code), response.text[:300])


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class RecordsTwinsTest(ApiBase):
    """Home's lists, the month's rankings, a DJ's places, and the songs' Find and pictures, through the API."""

    def test_plays_carry_their_new_marks_and_the_newest_records(self):
        nova, rio, ghost = self.make(), self.make("RIO", dj="RIO"), self.make("GHOST", dj="GHOST")
        self.catalog([{"number": 1, "title": "Made-up Song"}])
        # NOVA: a first play, a record (+50), a play under the best; RIO a first play only; GHOST a record, then
        # disabled (out of everyone's lists).
        self.play(nova, 1, 1, 100, at=1000)
        self.play(nova, 1, 1, 150, at=2000)
        self.play(nova, 1, 1, 120, at=3000)
        self.play(rio, 1, 1, 500, at=2500)
        self.play(ghost, 1, 1, 10, at=1500)
        self.play(ghost, 1, 1, 90, at=1600)
        self.disable("GHOST")
        token = self.token()
        mine = self.call("GET", "/api/v1/plays", token).json()
        self.assertEqual(mine["total"], 3)
        self.assertEqual([(p["score"], p["before"], p["new"], p["gain"]) for p in mine["plays"]],
                         [(120, 150, False, None), (150, 100, True, 50), (100, None, False, None)])
        # What a play always had stays: the title from the song list, who and when.
        self.assertEqual((mine["plays"][0]["title"], mine["plays"][0]["dj"], mine["plays"][0]["at"]),
                         ("Made-up Song", "DJ NOVA", 3000))
        everyone = self.call("GET", "/api/v1/plays?everyone=1", token).json()
        self.assertEqual((everyone["total"], {p["dj"] for p in everyone["plays"]}), (4, {"DJ NOVA", "RIO"}))
        # The newest records, as Home lists them: NOVA's +50 only (a first play is none; GHOST is disabled).
        records = self.call("GET", "/api/v1/plays?records=true", token).json()
        self.assertEqual([(p["dj"], p["score"], p["before"], p["gain"], p["new"]) for p in records["plays"]],
                         [("DJ NOVA", 150, 100, 50, True)])

    def test_this_months_ranking_with_the_first_three_of_the_months_before(self):
        from opendmt3.server.web import common
        now = time.time()
        this, last = common._month_start(now), common._month_start(now, 1)
        nova, rio = self.make(), self.make("RIO", dj="RIO")
        hana, kai = self.make("HANA", dj="HANA"), self.make("KAI", dj="KAI")
        # This month: NOVA alone. Last month: four players, of whom the first three show.
        self.play(nova, 1, 1, 300, at=this + 60)
        for person, score in ((rio, 500), (hana, 400), (kai, 300), (nova, 100)):
            self.play(person, 2, 1, score, at=last + 60)
        token = self.token()
        month = self.call("GET", "/api/v1/rankings?by=month", token).json()
        self.assertEqual((month["by"], month["mode"], month["start"]), ("month", 0, this))
        self.assertEqual([(r["place"], r["dj_name"], r["total"]) for r in month["rows"]], [(1, "DJ NOVA", 300)])
        self.assertEqual(month["past"][0]["start"], last)
        self.assertEqual([(r["place"], r["dj_name"]) for r in month["past"][0]["rows"]],
                         [(1, "RIO"), (2, "HANA"), (3, "KAI")])
        # By total, every month together, as before: no months in it.
        total = self.call("GET", "/api/v1/rankings", token).json()
        self.assertEqual((total["by"], total["rows"][0]["dj_name"], "past" in total), ("total", "RIO", False))
        self.refused(self.call("GET", "/api/v1/rankings?by=week", token), 400, "bad_request")

    def test_a_djs_place_in_each_modes_ranking(self):
        nova, rio = self.make(), self.make("RIO", dj="RIO")
        self.play(nova, 1, 1, 300)
        self.play(rio, 1, 1, 200)
        self.play(rio, 1, 1, 50, mode=1)
        dj = self.call("GET", "/api/v1/djs/%d" % rio["id"], self.token()).json()
        self.assertEqual(dj["places"], [{"mode": 0, "mode_name": "STAR", "place": 2, "of": 2},
                                        {"mode": 1, "mode_name": "POP", "place": 1, "of": 1}])
        # The places the DJ page shows.
        self.sign_in(self.client)
        self.assertIn('<span class="value">2 / 2</span>', self.client.get("/dj/%d" % rio["id"]).text)
        self.refused(self.call("GET", "/api/v1/djs/999", self.token()), 404, "unknown_player")

    def test_the_songs_find_and_their_pictures(self):
        self.catalog([{"number": 1, "title": "Made-up Opening", "composer": "Someone"},
                      {"number": 2, "title": "Another Song", "composer": "Nobody"}])
        self.make()
        token = self.token()
        every = self.call("GET", "/api/v1/songs", token).json()
        self.assertEqual((len(every["songs"]), every["total"]), (2, 2))
        # Find: a word of the title or the composer in any case, or the song's number; the total stays.
        found = self.call("GET", "/api/v1/songs?q=NOBODY", token).json()
        self.assertEqual(([s["number"] for s in found["songs"]], found["total"]), ([2], 2))
        self.assertEqual([s["number"] for s in self.call("GET", "/api/v1/songs?q=1", token).json()["songs"]], [1])
        # A song's picture, where the server has one.
        os.makedirs(os.path.join(self.tmp, "jackets"))
        with open(os.path.join(self.tmp, "jackets", "1.png"), "wb") as f:
            f.write(b"\x89PNG made-up")
        r = self.call("GET", "/api/v1/songs/1/jacket.png", token)
        self.assertEqual((r.status_code, r.headers["content-type"], r.content), (200, "image/png", b"\x89PNG made-up"))
        for path in ("/api/v1/songs/2/jacket.png", "/api/v1/songs/99999999999/jacket.png"):
            self.refused(self.call("GET", path, token), 404, "not_found")


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class NoticeTwinTest(ApiBase):
    """The notice at the top of every page: read by anyone signed in, set and cleared by admins."""

    def setUp(self):
        super().setUp()
        self.make("BOSS", dj="BOSS", admin=True)
        self.make()
        self.boss, self.nova = self.token("BOSS"), self.token()

    def test_players_read_the_notice_and_admins_set_and_clear_it(self):
        self.assertEqual(self.call("GET", "/api/v1/notice", self.nova).json(), {"notice": None})
        r = self.call("POST", "/api/v1/notice", self.boss, json={"text": "Closed on Sunday\nfor a backup"})
        shown = r.json()["notice"]
        self.assertEqual((r.status_code, shown["text"], shown["by"]), (200, "Closed on Sunday for a backup", "BOSS"))
        # Every page shows it, as when it is set on the Status page.
        self.sign_in(self.client)
        self.assertIn("Closed on Sunday for a backup", self.client.get("/").text)
        # A player reads the line and since when, never who set it (a login ID is for admins).
        self.assertEqual(set(self.call("GET", "/api/v1/notice", self.nova).json()["notice"]), {"text", "at"})
        # A player can neither set nor clear it; a HEAD reads and clears nothing.
        for method in ("POST", "DELETE"):
            self.refused(self.call(method, "/api/v1/notice", self.nova, json={"text": "a player's"}), 403,
                         "admin_only")
        self.assertEqual(self.call("HEAD", "/api/v1/notice", self.boss).status_code, 200)
        self.assertEqual(self.call("GET", "/api/v1/notice", self.nova).json()["notice"]["text"],
                         "Closed on Sunday for a backup")
        # An empty line clears it, and so does DELETE; each in the change log.
        self.assertEqual(self.call("POST", "/api/v1/notice", self.boss, json={"text": "  "}).json(), {"notice": None})
        self.call("POST", "/api/v1/notice", self.boss, json={"text": "again"})
        self.assertEqual(self.call("DELETE", "/api/v1/notice", self.boss).json(), {"notice": None})
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "notice.json")))
        changes = self.changes()
        self.assertIn("set the notice: Closed on Sunday for a backup", changes)
        self.assertEqual(changes.count("cleared the notice"), 2)

    def test_a_notice_too_long_or_not_text_is_refused_in_words(self):
        from opendmt3.core import errors
        from opendmt3.server.services import notice
        self.call("POST", "/api/v1/notice", self.boss, json={"text": "x" * 200})
        for text in ("y" * 201, "turned ‮around", "bell \x07"):
            r = self.call("POST", "/api/v1/notice", self.boss, json={"text": text})
            self.assertEqual((r.status_code, r.json()["error"]),
                             (400, {"code": "refused", "message": "a notice is one line of up to 200 characters"}))
        self.assertEqual(self.call("GET", "/api/v1/notice", self.boss).json()["notice"]["text"], "x" * 200)
        # A body without a line of text: nothing is cleared by mistake.
        for body in ({}, {"text": None}, {"text": 5}, ["text"]):
            self.refused(self.call("POST", "/api/v1/notice", self.boss, json=body), 400, "bad_request")
        self.assertEqual(self.call("GET", "/api/v1/notice", self.boss).json()["notice"]["text"], "x" * 200)
        # The refusal's words in Korean, as the Status page shows them (errors.py).
        with self.assertRaises(notice.NoticeError) as caught:
            notice.check("y" * 201)
        self.assertEqual(errors.say(caught.exception, "ko"), "공지는 200자까지 한 줄로 씁니다.")


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class StatusAndLogsTwinTest(ApiBase):
    """The Status page's list of what to look at, and the Logs tab: its counts, the plays log and its CSV."""

    def setUp(self):
        super().setUp()
        self.admin()
        self.boss = self.token("BOSS")

    def test_status_lists_what_to_look_at_in_words(self):
        from unittest import mock
        from opendmt3.server.services import sources
        # A server run as a program (not in a container): the installer's line names the folder to put it in. In a
        # container it names ./dmt3 setup instead (tests/server/test_site_features.py LookTest checks both).
        with mock.patch.object(sources, "in_container", lambda: False):
            server = self.call("GET", "/api/v1/server", self.boss).json()
        # A new server: no backup, no song list, no installer (and no other account).
        self.assertEqual([item["key"] for item in server["look"]], ["backup", "songs", "installer"])
        self.assertEqual(server["look"][0], {"key": "backup", "values": {"days": 7}, "href": "/admin/backups",
                                             "text": "No backup in the last 7 days."})
        self.assertIn("put openDMT3-win-Setup.exe in " + self.site.downloads, server["look"][2]["text"])
        # The numbers as before.
        self.assertEqual(server["accounts"], {"all": 1, "disabled": 0})
        ko = self.call("GET", "/api/v1/server?lang=ko", self.boss).json()
        self.assertEqual(ko["look"][0]["text"], "최근 7일 동안 백업이 없습니다.")
        # Every other account disabled: the line comes, as on the page.
        self.make()
        self.call("POST", "/api/v1/players/NOVA/disable", self.boss)
        keys = [item["key"] for item in self.call("GET", "/api/v1/server", self.boss).json()["look"]]
        self.assertEqual(keys[-1], "accounts")

    def test_the_log_says_how_many_changes_and_messages_there_are(self):
        self.make()
        log = self.call("GET", "/api/v1/log", self.boss).json()
        self.assertEqual(log["counts"], {"changes": len(self.changes()), "messages": 0})
        self.assertEqual(log["changes"][0]["what"], "made the account NOVA")

    def test_the_plays_log_filters_pages_and_counts_as_the_logs_tab(self):
        now = int(time.time())
        nova, rio = self.make(), self.make("RIO", dj="RIO")
        self.catalog([{"number": 1, "title": "Made-up Opening"}, {"number": 2, "title": "Another Song"},
                      {"number": 3, "title": "Closing Opening Theme"}])
        # The Logs tab's own test's plays: NOVA 55 over 50 days, RIO three today.
        for n in range(55):
            self.play(nova, 1, 1, 1000 + n, at=now - (n % 50) * 86400 - n)
        for song in (2, 3, 77):
            self.play(rio, song, 2, 500, mode=1, at=now - 60)
        first = self.call("GET", "/api/v1/log/plays", self.boss).json()
        self.assertEqual((len(first["plays"]), first["totals"], first["older"], first["newer"], first["page"]),
                         (50, {"plays": 58, "players": 2, "charts": 4}, True, False, 1))
        self.assertEqual(sorted(p["login_id"] for p in first["people"]), ["BOSS", "NOVA", "RIO"])
        self.assertEqual(set(first["plays"][0]), {"id", "at", "player", "dj", "login_id", "mode", "mode_name", "song",
                                                  "title", "pattern", "level", "score"})
        second = self.call("GET", "/api/v1/log/plays?page=2", self.boss).json()
        self.assertEqual((len(second["plays"]), second["older"], second["newer"]), (8, False, True))
        # The filters: a player, the days, a word of the title in any case, a song missing from the list by number.
        for query, count in (("player=%d" % rio["id"], 3), ("days=1", 5), ("days=7", 15),
                             ("q=OPENING&player=%d" % rio["id"], 1), ("q=%2377", 1), ("q=nothing+like+it", 0)):
            self.assertEqual(len(self.call("GET", "/api/v1/log/plays?" + query, self.boss).json()["plays"]), count,
                             query)
        # A value that cannot be read is refused: the page leaves it out, a program is told.
        for query in ("page=x", "page=0", "days=5", "player=nova"):
            r = self.call("GET", "/api/v1/log/plays?" + query, self.boss)
            self.refused(r, 400, "bad_request")
            self.assertIn(query.split("=")[0], r.json()["error"]["message"])
        # The file: what the Logs tab's file holds, byte for byte, filters and all.
        api = self.call("GET", "/api/v1/log/plays.csv?q=another", self.boss)
        page = self.client.get("/admin/log/plays.csv?q=another")
        self.assertEqual((api.content, api.headers["content-disposition"], api.headers["content-type"]),
                         (page.content, page.headers["content-disposition"], "text/csv; charset=utf-8"))
        rows = list(csv.reader(io.StringIO(api.content.decode("utf-8-sig"))))
        self.assertEqual((rows[0][0], [(r[3], r[4]) for r in rows[1:]]), ("when", [("2", "Another Song")]))
        self.assertEqual(len(list(csv.reader(io.StringIO(self.call(
            "GET", "/api/v1/log/plays.csv", self.boss).content.decode("utf-8-sig"))))), 1 + 58)
        self.refused(self.call("GET", "/api/v1/log/plays.csv?days=2", self.boss), 400, "bad_request")


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class PlayersTwinTest(ApiBase):
    """The admin's Players page through the API: an account made without a password, a new password with the
    message to send, admin rights, a new DJ name, and the last enabled admin kept."""

    def setUp(self):
        super().setUp()
        self.make("BOSS", dj="BOSS", admin=True)
        self.boss = self.token("BOSS")

    def test_an_account_made_without_a_password_gets_one_with_the_message_to_send(self):
        from starlette.testclient import TestClient
        # The program reached the server at its public name over HTTPS: the message gives that address.
        program = TestClient(self.app, base_url="https://dmt.example", client=("203.0.113.9", 50000))
        auth = {"Authorization": "Bearer " + self.boss}
        r = program.post("/api/v1/players", json={"login_id": "minho", "dj_name": "MINHO"}, headers=auth)
        made = r.json()
        self.assertEqual((r.status_code, made["login_id"], made["dj_name"]), (201, "MINHO", "MINHO"))
        self.assertRegex(made["password"], r"^[0-9a-f]{8}$")
        self.assertEqual(made["message"], "Your account on this openDMT3 server.\nAddress: https://dmt.example/\n"
                                          "ID: MINHO\nPassword: %s\n\n1. Open the Download page and sign in with "
                                          "this ID and password: https://dmt.example/download\n2. Download the "
                                          "launcher there and follow the page's steps." % made["password"])
        # The password in the answer is the one that signs in.
        self.token("MINHO", made["password"])
        # A password sent comes back as sent; the message in Korean with ?lang=ko.
        r = program.post("/api/v1/players?lang=ko", json={"login_id": "rio", "password": "secret12"}, headers=auth)
        self.assertEqual(r.json()["password"], "secret12")
        self.assertIn("주소: https://dmt.example/\nID: RIO\n비밀번호: secret12\n", r.json()["message"])
        # The rules still refuse a password sent too short, and an ID taken.
        for body, message in (({"login_id": "kai", "password": "x"}, "a password is 6 to 16 letters or digits"),
                              ({"login_id": "minho"}, "the ID MINHO is taken")):
            r = program.post("/api/v1/players", json=body, headers=auth)
            self.assertEqual((r.status_code, r.json()["error"]), (400, {"code": "refused", "message": message}))
        self.assertIn("made the account MINHO", self.changes())

    def test_a_new_password_comes_with_the_message_to_send(self):
        self.make()
        nova = self.token()
        made = self.call("POST", "/api/v1/players/nova/password", self.boss).json()
        self.assertEqual(set(made), {"login_id", "password", "message"})
        self.assertIn("Address: http://testserver/\nID: NOVA\nPassword: %s\n" % made["password"], made["message"])
        # The old token ended with the old password; the new password signs in.
        self.assertEqual(self.call("GET", "/api/v1/me", nova).status_code, 401)
        self.token("NOVA", made["password"])
        self.refused(self.call("POST", "/api/v1/players/NOBODY/password", self.boss), 404, "unknown_player")

    def test_admin_rights_are_given_and_taken_but_never_from_the_last_enabled_admin(self):
        self.make()
        self.assertEqual(self.call("POST", "/api/v1/players/nova/admin", self.boss).json(),
                         {"login_id": "NOVA", "is_admin": True})
        nova = self.token()
        self.assertEqual(self.call("GET", "/api/v1/players", nova).status_code, 200)
        self.assertEqual(self.call("DELETE", "/api/v1/players/NOVA/admin", self.boss).json(),
                         {"login_id": "NOVA", "is_admin": False})
        self.assertEqual(self.call("GET", "/api/v1/players", nova).status_code, 403)
        # BOSS is the only enabled admin now: the rights stay, in the words of the rule.
        r = self.call("DELETE", "/api/v1/players/BOSS/admin", self.boss)
        self.assertEqual((r.status_code, r.json()["error"]), (400, {
            "code": "refused", "message": "the server needs an enabled admin, and BOSS is the only one"}))
        changes = self.changes()
        self.assertIn("gave admin rights to NOVA", changes)
        self.assertIn("took admin rights from NOVA", changes)
        self.assertNotIn("took admin rights from BOSS", changes)
        for method in ("POST", "DELETE"):
            self.refused(self.call(method, "/api/v1/players/NOBODY/admin", self.boss), 404, "unknown_player")
        # Their own rights, taken while another admin has some: done, and the token is a player's from then on.
        self.call("POST", "/api/v1/players/NOVA/admin", self.boss)
        self.assertEqual(self.call("DELETE", "/api/v1/players/BOSS/admin", self.boss).json(),
                         {"login_id": "BOSS", "is_admin": False})
        self.refused(self.call("GET", "/api/v1/players", self.boss), 403, "admin_only")

    def test_the_only_enabled_admin_is_never_disabled(self):
        self.make("RIO", dj="RIO", admin=True)
        # RIO disabled: BOSS is the only enabled admin, and the API refuses to disable them, as the page does.
        self.assertEqual(self.call("POST", "/api/v1/players/RIO/disable", self.boss).json(),
                         {"login_id": "RIO", "disabled": True})
        r = self.call("POST", "/api/v1/players/boss/disable", self.boss)
        self.assertEqual((r.status_code, r.json()["error"]), (400, {
            "code": "refused", "message": "the server needs an enabled admin, and BOSS is the only one"}))
        self.assertEqual(self.call("GET", "/api/v1/me", self.boss).status_code, 200)
        self.assertNotIn("disabled the account BOSS", self.changes())
        # With RIO enabled again, BOSS may go (by their own hand even): RIO still opens the admin pages.
        self.call("POST", "/api/v1/players/RIO/enable", self.boss)
        self.assertEqual(self.call("POST", "/api/v1/players/BOSS/disable", self.boss).json()["disabled"], True)
        self.assertEqual(self.call("GET", "/api/v1/players", self.token("RIO")).status_code, 200)

    def test_two_admins_disabling_each_other_at_once_cannot_both_win(self):
        from unittest import mock
        from opendmt3.server import db
        from opendmt3.server.services import accounts
        self.make("TWO", admin=True)
        store = accounts.Accounts(db.connect(self.site.db_path))
        try:
            store.set_disabled("TWO", True)
            # BOSS's check made before TWO's change went through (it saw two admins): the change itself refuses.
            with mock.patch.object(accounts.Accounts, "leaves_no_admin", return_value=False):
                with self.assertRaises(accounts.AccountError) as refused:
                    store.set_disabled("BOSS", True)
            self.assertEqual(refused.exception.key, "error.account.last_admin")
            self.assertEqual(store.db.execute("SELECT COUNT(*) FROM accounts WHERE is_admin = 1 AND disabled = 0")
                             .fetchone()[0], 1)
            # Enabling is never held back; an ID no account has changes nothing and logs nothing.
            store.set_disabled("TWO", False)
            store.set_disabled("NOBODY", True)
        finally:
            store.db.close()
        self.assertNotIn("disabled the account NOBODY", self.changes())

    def test_an_admin_renames_a_dj_by_the_account_pages_rules(self):
        self.make()
        r = self.call("POST", "/api/v1/players/nova/dj_name", self.boss, json={"dj_name": " 노바 NOVA "})
        self.assertEqual(r.json(), {"login_id": "NOVA", "dj_name": "노바 NOVA"})
        self.assertEqual(self.call("GET", "/api/v1/me", self.token()).json()["dj_name"], "노바 NOVA")
        self.assertIn("named NOVA 노바 NOVA", self.changes())
        # Too long, or nothing: the account page's own refusal; the name stays.
        for name in ("NINE CHAR", ""):
            r = self.call("POST", "/api/v1/players/NOVA/dj_name", self.boss, json={"dj_name": name})
            self.assertEqual((r.status_code, r.json()["error"]),
                             (400, {"code": "refused", "message": "a DJ name is 1 to 8 characters"}))
        self.refused(self.call("POST", "/api/v1/players/NOVA/dj_name", self.boss, content=b"not json",
                               headers={"content-type": "application/json"}), 400, "bad_request")
        self.refused(self.call("POST", "/api/v1/players/NOBODY/dj_name", self.boss, json={"dj_name": "X"}), 404,
                     "unknown_player")
        self.assertEqual(self.call("GET", "/api/v1/me", self.token()).json()["dj_name"], "노바 NOVA")


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class FilesTwinTest(ApiBase):
    """A backup deleted, the Download page and the installer, and the Licenses page, through the API."""

    def test_a_backup_is_deleted_by_its_own_name_only(self):
        from opendmt3.server.services import backups
        self.make("BOSS", dj="BOSS", admin=True)
        boss = self.token("BOSS")
        name = self.call("POST", "/api/v1/backups", boss).json()["made"]
        self.make("RIO")
        # A HEAD asks for the file's headers only: nothing is restored (RIO stays) or deleted.
        self.assertEqual(self.call("HEAD", "/api/v1/backups/" + name, boss).status_code, 200)
        self.assertEqual([b["name"] for b in backups.all_backups(self.tmp)], [name])
        self.assertIn("RIO", [p["login_id"] for p in self.call("GET", "/api/v1/players", boss).json()["players"]])
        self.assertEqual(self.call("DELETE", "/api/v1/backups/" + name, boss).json(), {"deleted": name})
        self.assertEqual(backups.all_backups(self.tmp), [])
        self.assertIn("deleted the backup %s" % name, self.changes())
        # Gone now, or never a backup: nothing outside backups/ goes.
        for wrong in (name, "openDMT3.sqlite", "nothing.sqlite"):
            self.refused(self.call("DELETE", "/api/v1/backups/" + wrong, boss), 404, "unknown_backup")
        self.assertEqual(self.call("DELETE", "/api/v1/backups/..%2FopenDMT3.sqlite", boss).status_code, 404)
        self.assertTrue(os.path.isfile(self.site.db_path))

    def test_the_download_pages_facts_and_the_installer_with_this_server_on_its_end(self):
        from starlette.testclient import TestClient
        from opendmt3.core import preset
        self.make()
        program = TestClient(self.app, base_url="https://dmt.example", client=("203.0.113.9", 50000))
        auth = {"Authorization": "Bearer " + self.token(client=program)}
        self.assertEqual(program.get("/api/v1/download", headers=auth).json(),
                         {"installer": None, "address": "dmt.example:443", "file": "openDMT3-win-Setup-dmt.example-443.exe"})
        self.refused(program.get("/api/v1/download/windows", headers=auth), 404, "no_installer")
        os.makedirs(self.site.downloads)
        path = os.path.join(self.site.downloads, "openDMT3-win-Setup.exe")
        with open(path, "wb") as f:
            f.write(windows_program((1, 2, 3, 0)))
        moment = time.mktime((2026, 11, 2, 9, 30, 0, 0, 0, -1))
        os.utime(path, (moment, moment))
        self.assertEqual(program.get("/api/v1/download", headers=auth).json()["installer"],
                         {"size": os.path.getsize(path), "at": int(moment), "version": "1.2.3"})
        got = program.get("/api/v1/download/windows", headers=auth)
        self.assertEqual(got.headers["content-disposition"],
                         'attachment; filename="openDMT3-win-Setup-dmt.example-443.exe"')
        self.assertEqual(int(got.headers["content-length"]), len(got.content))
        # The installer as kept, then this server's address on its end: the launcher it installs starts here.
        self.assertTrue(got.content.startswith(windows_program((1, 2, 3, 0))))
        handed = os.path.join(self.tmp, "as-downloaded.exe")
        with open(handed, "wb") as f:
            f.write(got.content)
        self.assertEqual(preset.read(handed), {"url": "https://dmt.example", "name": "dmt.example"})
        # Byte for byte what the Download page's button hands out.
        self.sign_in(program)
        self.assertEqual(program.get("/download/windows").content, got.content)

    def test_the_licenses_page_has_its_twin_open_to_anyone(self):
        from opendmt3.server.web import common
        licences = self.client.get("/api/v1/licenses").json()["licenses"]
        self.assertEqual([item["name"] for item in licences], ["SIL Open Font License 1.1"] * 2)
        self.assertEqual([len(item["faces"]) for item in licences], [1, 2])
        self.assertTrue(licences[0]["faces"][0].startswith("DMT3 Wide"))
        texts = common._licence_texts()
        self.assertEqual([item["text"] for item in licences], [texts["saira"], texts["pretendard"]])
        self.assertTrue(self.client.get("/api/v1/licenses?lang=ko").json()["licenses"][0]["faces"][0]
                        .startswith("DMT3 Wide(제목 글꼴)"))


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class SignOutTest(ApiBase):
    """DELETE /api/v1/session: the token sent ends, no other; its id kept until it would have expired anyway."""

    def test_signing_out_ends_the_token_sent_and_no_other(self):
        from opendmt3.server.web import session as sess
        row = self.make()
        here, there = self.token(), self.token()
        # Each sign-in's token is its own, even within one second.
        self.assertNotEqual(here, there)
        self.sign_in(self.client)
        r = self.call("DELETE", "/api/v1/session", here)
        self.assertEqual((r.status_code, r.json()), (200, {"signed_out": True}))
        self.refused(self.call("GET", "/api/v1/me", here), 401, "sign_in")
        # The other launcher's token and the site's sign-in go on.
        self.assertEqual(self.call("GET", "/api/v1/me", there).status_code, 200)
        self.assertEqual(self.client.get("/", follow_redirects=False).status_code, 200)
        # Signed out already, or no token at all: nothing to end.
        self.refused(self.call("DELETE", "/api/v1/session", here), 401, "sign_in")
        self.refused(self.call("DELETE", "/api/v1/session"), 401, "sign_in")
        # A token made before tokens had an id of their own signs out the same way.
        old = self.site.signer.sign({"kind": "api", "uid": row["id"], "pw": sess.password_mark(row["password"])})
        self.assertEqual(self.call("GET", "/api/v1/me", old).status_code, 200)
        self.assertEqual(self.call("DELETE", "/api/v1/session", old).status_code, 200)
        self.refused(self.call("GET", "/api/v1/me", old), 401, "sign_in")
        self.assertEqual(self.call("GET", "/api/v1/me", there).status_code, 200)

    def test_an_ended_tokens_id_is_kept_until_it_would_have_expired_and_then_pruned(self):
        from unittest import mock
        from opendmt3.server import db
        from opendmt3.server.web import api
        from opendmt3.server.web import session as sess
        self.make()
        first = self.token()
        self.call("DELETE", "/api/v1/session", first)

        def kept():
            connection = db.connect(self.site.db_path)
            try:
                return [tuple(r) for r in connection.execute("SELECT id, expires FROM revoked_tokens")]
            finally:
                connection.close()

        made = self.site.signer.unsign(first, api.TOKEN_DAYS * 86400)["t"]
        # Its id (a hash: the token itself, which signs in, is kept nowhere) until it would have expired.
        self.assertEqual(kept(), [(sess.token_id(first), made + api.TOKEN_DAYS * 86400)])
        self.assertNotIn(first, kept()[0][0])
        # A month and a day later: the first token is refused for its age anyway, and the next sign-out prunes it.
        with mock.patch("time.time", return_value=time.time() + (api.TOKEN_DAYS + 1) * 86400):
            self.refused(self.call("GET", "/api/v1/me", first), 401, "sign_in")
            second = self.token()
            self.call("DELETE", "/api/v1/session", second)
        self.assertEqual([k[0] for k in kept()], [sess.token_id(second)])


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class HttpDetailsTest(ApiBase):
    """What every answer says beside its body: when to try again, the methods a path takes, never to store it."""

    def test_a_429_says_when_to_try_again(self):
        from opendmt3.server.web import app as web_app
        self.make()
        for _ in range(web_app.TRIES):
            self.client.post("/api/v1/session", json={"login_id": "NOVA", "password": "wrong999"})
        r = self.client.post("/api/v1/session", json={"login_id": "NOVA", "password": "pass1234"})
        self.refused(r, 429, "too_many_tries")
        # Until the oldest wrong password leaves the window: nearly all of it, in whole seconds.
        self.assertIn("retry-after", r.headers)
        self.assertTrue(web_app.WINDOW - 30 <= int(r.headers["retry-after"]) <= web_app.WINDOW, r.headers)
        # The sign-in page's 429 says it too.
        page = self.sign_in(self.client)
        self.assertEqual((page.status_code, "retry-after" in page.headers), (429, True))
        self.assertTrue(1 <= int(page.headers["retry-after"]) <= web_app.WINDOW, page.headers)

    def test_the_wait_lasts_until_enough_tries_leave_the_window(self):
        from opendmt3.server.services import limits
        now = [1000.0]
        table = limits.Recent(600, lambda: 100, clock=lambda: now[0])
        for at in (1000.0, 1100.0, 1200.0):
            now[0] = at
            table.add("x")
        now[0] = 1300.0
        # Three tries in the window: under a limit of four, no wait; at three, until the oldest leaves (1600); at
        # two, until the second oldest does (1700).
        self.assertEqual([table.wait("x", most) for most in (4, 3, 2)], [0, 300.0, 400.0])
        self.assertEqual(table.wait("nobody", 1), 0)

    def test_a_405_names_the_methods_the_path_takes(self):
        r = self.client.get("/api/v1/session")
        self.refused(r, 405, "method_not_allowed")
        self.assertEqual(r.headers.get("allow"), "DELETE, POST")
        self.assertEqual(self.client.put("/api/v1/notice").headers.get("allow"), "DELETE, GET, HEAD, POST")
        self.assertEqual(self.client.post("/api/v1/rankings").headers.get("allow"), "GET, HEAD")
        # A page's 405 too.
        r = self.client.get("/signout")
        self.assertEqual((r.status_code, r.headers.get("allow")), (405, "POST"))

    def test_every_api_answer_says_never_to_store_it(self):
        from opendmt3.server.web import app as web_app
        self.make("BOSS", dj="BOSS", admin=True)
        boss = self.token("BOSS")
        name = self.call("POST", "/api/v1/backups", boss).json()["made"]
        answers = {
            "open": self.client.get("/api/v1/status"),
            "signed in": self.call("GET", "/api/v1/me", boss),
            "401": self.client.get("/api/v1/me"),
            "404": self.client.get("/api/v1/nothing"),
            "405": self.client.get("/api/v1/session"),
            "a file": self.call("GET", "/api/v1/backups/" + name, boss),
            "a stream": self.call("GET", "/api/v1/log/plays.csv", boss),
            # Refused by the wall before any route: too large.
            "413": self.client.post("/api/v1/session", content=b"x" * (web_app.BODY_LIMIT + 1)),
        }
        for what, r in answers.items():
            self.assertEqual(r.headers.get("cache-control"), "no-store", what)
        self.assertEqual(answers["413"].status_code, 413)
        # The site's pages keep their own.
        self.assertEqual(self.client.get("/signin").headers["cache-control"], "private, no-store")


def served_calls(app):
    """Every route the app serves under /api/v1/ as {(method, shape): (path as written, with converters)}."""
    from starlette.routing import Route
    served = {}
    for route in app.routes:
        if isinstance(route, Route) and route.path.startswith("/api/v1/"):
            # HEAD comes with every GET by itself.
            for method in route.methods - {"HEAD"}:
                served[(method, shape(route.path))] = route.path
    return served


def is_of(value, kind):
    """Whether a JSON value is of one of the table's types ("integer", "object|null", ...)."""
    checks = {"string": lambda v: isinstance(v, str),
              "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
              "boolean": lambda v: isinstance(v, bool), "array": lambda v: isinstance(v, list),
              "object": lambda v: isinstance(v, dict), "null": lambda v: v is None,
              "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)}
    return any(checks[one](value) for one in kind.split("|"))


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class RouteDocsTest(ApiBase):
    """docs/api.md, the table of calls (web/calls.py), the OpenAPI document made from it and the routes agree: every
    route under /api/ (and the open ones programs read) is in the guide and the table, every call there is a route,
    with the same who, parameters, errors and area, the document says the same, each call answers only whom its row
    names, and each answer has the main fields the table gives it."""

    def test_the_table_the_guide_and_the_routes_are_one(self):
        from opendmt3.server.web import calls
        table = {(c.method, c.path): c for c in calls.CALLS}
        # The table has dozens of calls, each once, each of its own name.
        self.assertGreater(len(table), 45)
        self.assertEqual(len(table), len(calls.CALLS), "a call is in the table twice")
        self.assertEqual(len({c.name for c in calls.CALLS}), len(calls.CALLS), "two calls have one name")
        # The routes: the same calls, and each part of a path named alike (a number's converter an integer).
        served = served_calls(self.app)
        self.assertEqual(sorted(served), sorted((method, shape(path)) for method, path in table))
        for call in calls.CALLS:
            route_path = served[(call.method, shape(call.path))]
            with self.subTest(call="%s %s" % (call.method, call.path)):
                parts = re.findall(r"\{(\w+)(?::(\w+))?\}", route_path)
                self.assertEqual([name for name, _ in parts], [p.name for p in call.where("path")])
                for (name, converter), param in zip(parts, call.where("path")):
                    self.assertEqual(converter == "int", param.type == "integer", name)
        # The guide: the same calls under /api/v1/, each with the table's who, area, parameters and errors.
        rows = {(row["method"], row["path"]): row for row in guide_rows() if row["path"].startswith("/api/v1/")}
        self.assertEqual(sorted(rows), sorted(table))
        self.assertEqual([row["path"] for row in guide_rows() if not row["path"].startswith("/api/v1/")],
                         list(PROGRAMS))
        checked = 0
        for key, call in table.items():
            row = rows[key]
            with self.subTest(call="%s %s" % key):
                self.assertEqual(row["cells"], 6)
                self.assertIn(call.who, WHO)
                self.assertIn(call.area, calls.AREAS)
                self.assertEqual((row["who"], row["area"]), (call.who, call.area))
                self.assertEqual(row["takes"], {p.name for p in call.params if p.where != "path"})
                self.assertEqual(row["errors"], set(call.errors))
                # Every type is JSON's; a call gives JSON fields or a file, never both.
                self.assertTrue(all(p.type in calls.TYPES for p in call.params))
                self.assertTrue(all(t in calls.TYPES for kind in call.answer.values() for t in kind.split("|")))
                self.assertNotEqual(bool(call.answer), bool(call.files))
                checked += 1
        # The instrument itself: every call was looked at.
        self.assertEqual(checked, len(table))

    def test_the_song_lists_calls_and_the_licenses_keys_have_their_one_name(self):
        # The thing a server takes is the song list, in the API's names as in its words: the calls are .../song_list
        # with a song_list field, and the licenses call's keys are spelled as its address is. No other name answers,
        # in the routes or in the document the server serves.
        from opendmt3.server.web import calls
        self.make("BOSS", dj="BOSS", admin=True)
        boss = self.token("BOSS")
        document = self.client.get("/api/v1/openapi.json").json()
        self.assertEqual(sorted(document["paths"]["/api/v1/server/song_list"]), ["get", "post"])
        # No path and no answer's field by the older names, in the table the document and docs/api.md are made from.
        names = [call.path for call in calls.CALLS] + [key for call in calls.CALLS for key in call.answer]
        self.assertEqual([name for name in names if "game_data" in name or "licence" in name], [])
        for method in ("GET", "POST"):
            self.refused(self.call(method, "/api/v1/server/game_data", boss), 404, "not_found")
        self.assertIn("song_list", self.call("GET", "/api/v1/server", boss).json())
        self.assertEqual(sorted(self.call("GET", "/api/v1/server/song_list", boss).json()),
                         ["browse", "found", "places", "song_list"])
        licenses = self.client.get("/api/v1/licenses").json()
        self.assertEqual((sorted(licenses), sorted(licenses["parts"][0])),
                         (["licenses", "own", "parts"], ["license", "part", "used_for"]))

    def test_the_openapi_document_is_the_tables_and_open_to_anyone(self):
        from opendmt3 import __version__
        from opendmt3.server.web import calls
        r = self.client.get("/api/v1/openapi.json")
        self.assertEqual((r.status_code, r.headers["cache-control"]), (200, "no-store"))
        document = r.json()
        # Made from the table, at this version.
        self.assertEqual(document, calls.openapi(__version__))
        self.assertEqual((document["openapi"], document["info"]["version"]), ("3.1.0", __version__))
        operations = {(method.upper(), path): op for path, ops in document["paths"].items()
                      for method, op in ops.items()}
        # The same calls as the routes serve.
        self.assertEqual(sorted((m, shape(p)) for m, p in operations), sorted(served_calls(self.app)))
        for call in calls.CALLS:
            op = operations[(call.method, call.path)]
            with self.subTest(call="%s %s" % (call.method, call.path)):
                self.assertEqual((op["x-who"], op["operationId"], op["tags"]), (call.who, call.name, [call.area]))
                # Who may: no token for anyone, the document's token for the rest.
                self.assertEqual(op.get("security"), [] if call.who == "anyone" else None)
                self.assertEqual([(p["name"], p["in"]) for p in op.get("parameters", [])],
                                 [(p.name, p.where) for p in call.params if p.where != "body"])
                body = op.get("requestBody", {}).get("content", {})
                if call.where("body"):
                    self.assertEqual(sorted(body["application/json"]["schema"]["properties"]),
                                     sorted(p.name for p in call.where("body")))
                else:
                    self.assertEqual(list(body), [call.upload] if call.upload else [])
                answer = op["responses"][str(call.status)]["content"]
                if call.files:
                    self.assertEqual(list(answer), [call.files])
                else:
                    self.assertEqual(sorted(answer["application/json"]["schema"]["properties"]),
                                     sorted(name.rstrip("?") for name in call.answer))
                # Its own errors are among its responses, and a call that needs a token answers 401.
                codes = {(int(status), code) for status, response in op["responses"].items() if int(status) >= 400
                         for code in response["description"].split(", ")}
                self.assertTrue(set(call.errors) <= codes, codes)
                self.assertEqual((401, "sign_in") in codes, call.who != "anyone")

    def test_each_answer_has_the_main_fields_the_table_gives_it(self):
        """Every call made once, in an order where each works, with an admin's token where one is needed: its status
        is the table's, and its answer has the table's main fields of the table's types (or is the table's file)."""
        from opendmt3.server.services import backups
        from opendmt3.server.web import calls
        self.make("BOSS", dj="BOSS", admin=True)
        nova = self.make()
        self.make("PASS", dj="PASS")
        self.catalog([{"number": 1, "title": "Made-up Song"}])
        self.play(nova, 1, 1, 500)
        # A picture of a song and of an icon, an installer, a cabinet seen and a backup, so their calls answer.
        for folder, name in (("jackets", "1.png"), (os.path.join("cards", "icon"), "1.png"),
                             ("downloads", "openDMT3-win-Setup.exe")):
            os.makedirs(os.path.join(self.tmp, folder), exist_ok=True)
            with open(os.path.join(self.tmp, folder, name), "wb") as f:
                f.write(b"\x89PNG made-up" if name.endswith(".png") else b"MZ made-up")
        with open(os.path.join(self.tmp, "cards.json"), "w") as f:
            f.write('{"icon": [{"number": 1, "grade": ""}], "plate": [], "pattern": []}')
        store = self.site.activity()
        try:
            store.seen("198.51.100.7", "test", "198.51.100.7:50000")
            cabinet = store.cabinets()[0]["id"]
        finally:
            store.db.close()
        kept = backups.make(self.site.db_path, self.tmp, "manual")
        with open(os.path.join(self.tmp, "backups", kept), "rb") as f:
            backup_file = f.read()
        admin = self.token("BOSS")
        made = {}
        # Each call's request: its address, what it sends, and the token it uses (the admin's unless another).
        plan = [
            ("GET", "/api/v1/status", "/api/v1/status", {}),
            ("GET", "/api/v1/openapi.json", "/api/v1/openapi.json", {}),
            ("POST", "/api/v1/session", "/api/v1/session", {"json": {"login_id": "NOVA", "password": "pass1234"}}),
            ("GET", "/api/v1/licenses", "/api/v1/licenses", {}),
            ("GET", "/api/v1/me", "/api/v1/me", {}),
            ("POST", "/api/v1/me/dj_name", "/api/v1/me/dj_name", {"json": {"dj_name": "BOSS"}}),
            ("POST", "/api/v1/me/password", "/api/v1/me/password",
             {"json": {"password": "pass1234", "new_password": "pass5678"}, "token": self.token("PASS")}),
            ("POST", "/api/v1/me/dj_card", "/api/v1/me/dj_card", {"json": {"comment": "HI"}}),
            ("GET", "/api/v1/dj_cards", "/api/v1/dj_cards", {}),
            ("GET", "/api/v1/dj_cards/{kind}/{number}.png", "/api/v1/dj_cards/icon/1.png", {}),
            ("POST", "/api/v1/tokens", "/api/v1/tokens", {"json": {"name": "bot", "scope": "read"}}),
            ("GET", "/api/v1/tokens", "/api/v1/tokens", {}),
            ("DELETE", "/api/v1/tokens/{id}", "/api/v1/tokens/{made_token}", {}),
            ("GET", "/api/v1/plays", "/api/v1/plays", {}),
            ("GET", "/api/v1/rankings", "/api/v1/rankings", {}),
            ("GET", "/api/v1/songs", "/api/v1/songs", {}),
            ("GET", "/api/v1/songs/{number}", "/api/v1/songs/1", {}),
            ("GET", "/api/v1/songs/{number}/jacket.png", "/api/v1/songs/1/jacket.png", {}),
            ("GET", "/api/v1/djs/{player}", "/api/v1/djs/%d" % nova["id"], {}),
            ("GET", "/api/v1/cabinets", "/api/v1/cabinets", {}),
            ("GET", "/api/v1/download", "/api/v1/download", {}),
            ("GET", "/api/v1/download/windows", "/api/v1/download/windows", {}),
            ("GET", "/api/v1/players", "/api/v1/players", {}),
            ("POST", "/api/v1/players", "/api/v1/players", {"json": {"login_id": "NEW1"}}),
            ("POST", "/api/v1/players/{login_id}/password", "/api/v1/players/NEW1/password", {}),
            ("POST", "/api/v1/players/{login_id}/dj_name", "/api/v1/players/NEW1/dj_name", {"json": {"dj_name": "N"}}),
            ("POST", "/api/v1/players/{login_id}/admin", "/api/v1/players/NEW1/admin", {}),
            ("DELETE", "/api/v1/players/{login_id}/admin", "/api/v1/players/NEW1/admin", {}),
            ("POST", "/api/v1/players/{login_id}/disable", "/api/v1/players/NEW1/disable", {}),
            ("POST", "/api/v1/players/{login_id}/enable", "/api/v1/players/NEW1/enable", {}),
            ("DELETE", "/api/v1/players/{login_id}/plays", "/api/v1/players/NEW1/plays", {}),
            ("DELETE", "/api/v1/players/{login_id}", "/api/v1/players/NEW1", {}),
            ("POST", "/api/v1/cabinets/{id}/name", "/api/v1/cabinets/%d/name" % cabinet, {"json": {"name": "Left"}}),
            ("GET", "/api/v1/server", "/api/v1/server", {}),
            ("GET", "/api/v1/server/song_list", "/api/v1/server/song_list", {}),
            ("POST", "/api/v1/server/song_list", "/api/v1/server/song_list", {}),
            ("GET", "/api/v1/server/folders", "/api/v1/server/folders", {}),
            ("POST", "/api/v1/notice", "/api/v1/notice", {"json": {"text": "Hello"}}),
            ("GET", "/api/v1/notice", "/api/v1/notice", {}),
            ("DELETE", "/api/v1/notice", "/api/v1/notice", {}),
            ("POST", "/api/v1/maintenance", "/api/v1/maintenance", {}),
            ("GET", "/api/v1/maintenance", "/api/v1/maintenance", {}),
            ("DELETE", "/api/v1/maintenance", "/api/v1/maintenance", {}),
            ("GET", "/api/v1/log", "/api/v1/log", {}),
            ("GET", "/api/v1/log/plays", "/api/v1/log/plays", {}),
            ("GET", "/api/v1/log/plays.csv", "/api/v1/log/plays.csv", {}),
            ("GET", "/api/v1/backups", "/api/v1/backups", {}),
            ("POST", "/api/v1/backups", "/api/v1/backups", {}),
            ("POST", "/api/v1/backups/upload", "/api/v1/backups/upload", {"content": backup_file}),
            ("GET", "/api/v1/backups/{name}", "/api/v1/backups/" + kept, {}),
            ("DELETE", "/api/v1/backups/{name}", "/api/v1/backups/{made_upload}", {}),
            ("POST", "/api/v1/backups/{name}/restore", "/api/v1/backups/%s/restore" % kept, {}),
            ("DELETE", "/api/v1/plays", "/api/v1/plays", {}),
            ("DELETE", "/api/v1/session", "/api/v1/session", {"token": self.token()}),
        ]
        table = {(c.method, c.path): c for c in calls.CALLS}
        # The song list read again: a game folder given, and its reading made up (the reading itself is
        # tests/server/test_sources.py's); the server PC's look through its folders made up too.
        from unittest import mock
        from opendmt3.server.services import sources
        self.site.game_folder = self.tmp
        made_up = {"at": 1, "from": "folder", "path": self.tmp, "folder": self.tmp, "songs": 1, "jackets": 0,
                   "cards": None, "missing": {"cards": "The game's files have no DJ cards."},
                   "reasons": {"cards": "error.card.tables"}}
        for patch in (mock.patch.object(sources, "read", lambda *a, **k: made_up),
                      mock.patch.object(sources, "found", lambda where: [])):
            patch.start()
            self.addCleanup(patch.stop)
        # Every call of the table has its request here: a new call without one fails here.
        self.assertEqual(sorted((m, p) for m, p, _, _ in plan), sorted(table))
        checked = 0
        for method, path, url, kwargs in plan:
            call = table[(method, path)]
            kwargs = dict(kwargs)
            token = kwargs.pop("token", admin if call.who != "anyone" else None)
            with self.subTest(call="%s %s" % (method, path)):
                r = self.call(method, url.format(**made), token, **kwargs)
                self.assertEqual(r.status_code, call.status, r.text[:300])
                if call.files:
                    self.assertTrue(r.headers["content-type"].startswith(call.files), r.headers["content-type"])
                else:
                    answer = r.json()
                    for name, kind in call.answer.items():
                        if name.endswith("?") and name[:-1] not in answer:
                            # A field only some answers have.
                            continue
                        self.assertIn(name.rstrip("?"), answer)
                        self.assertTrue(is_of(answer[name.rstrip("?")], kind), (name, answer[name.rstrip("?")]))
                    # What a later call of the plan names: the token made, the backup uploaded.
                    if (method, path) == ("POST", "/api/v1/tokens"):
                        made["made_token"] = answer["id"]
                    if (method, path) == ("POST", "/api/v1/backups/upload"):
                        made["made_upload"] = answer["uploaded"]
                checked += 1
        # The instrument itself: every call was made and looked at.
        self.assertEqual(checked, len(table))

    def test_every_route_is_in_the_guide_and_every_call_there_is_a_route(self):
        from starlette.routing import Route
        rows = documented()
        # The guide has dozens of calls; a pattern that stopped matching would pass with none.
        self.assertGreater(len(rows), 40)
        written = {(method, shape(path)) for method, path, _ in rows}
        self.assertEqual(len(written), len(rows), "a call is written twice")
        served = set()
        for route in self.app.routes:
            if isinstance(route, Route) and (route.path.startswith("/api/") or route.path in PROGRAMS):
                # HEAD comes with every GET by itself.
                served |= {(method, shape(route.path)) for method in route.methods if method != "HEAD"}
        self.assertEqual(sorted(served - written), [], "routes the guide does not document")
        self.assertEqual(sorted(written - served), [], "calls the guide documents that are not routes")

    def test_each_call_answers_only_whom_its_row_names(self):
        self.make("BOSS", dj="BOSS", admin=True)
        self.make()
        player = self.token()
        rows = documented()
        self.assertEqual({who for _, _, who in rows}, set(WHO))
        for method, path, who in rows:
            url = re.sub(r"\{([^}]*)\}", lambda m: SAMPLES.get(m.group(1), "1"), path)
            with self.subTest(call="%s %s" % (method, path), who=who):
                self.assertIn(who, WHO)
                if who == "anyone":
                    self.assertNotIn(self.call(method, url).status_code, (401, 403))
                    continue
                # No token: sign in first.
                self.refused(self.call(method, url), 401, "sign_in")
                # A player's token (a fresh one where the call ends it): an admin's call refuses it, the others take it.
                token = self.token() if (method, path) == ("DELETE", "/api/v1/session") else player
                r = self.call(method, url, token)
                if who == "admin":
                    self.refused(r, 403, "admin_only")
                else:
                    self.assertNotIn(r.status_code, (401, 403), r.text)


if __name__ == "__main__":
    unittest.main()
