"""Tests for the site's pages added from the comparison with OpenDMTQ: new records, the admin's message to send, the
status page's list of what to look at, the plays log, the month's rankings, admin rights, the notice, the DJ page's
places, deleting a backup, Home's top DJs, the songs filter, the Download page's file, the page frame, the sign-in
page, and the quality of every answer (health, errors, caching, compression).

They need the web libraries (Starlette, Jinja2, httpx for the test client); without them they are skipped.
"""

import os
import random
import re
import threading
import time
import unittest

# The site on a temporary data folder, a visitor from another PC and one on the server PC (tests/server/test_web.py).
from tests.server.test_web import WEB, WebBase


class SiteBase(WebBase):
    """WebBase with plays put in as the game server puts them, a song list, and the admin's forms."""

    def play(self, account, song, pattern, score, mode=0, at=1000):
        """One cleared stage of `account`, at a moment of the test's choosing."""
        from opendmt3.server import db
        from opendmt3.server.services import records as rec
        connection = db.connect(self.site.db_path)
        try:
            rec.Records(connection).add(account["id"], "198.51.100.7", mode, {"song": song, "pattern": pattern,
                                                                             "score": score, "counts": [0] * 7,
                                                                             "raw": bytes(47)}, at=at)
        finally:
            connection.close()

    def catalog(self, songs):
        """A song list as --catalog leaves it (made-up titles)."""
        import json
        with open(os.path.join(self.tmp, "catalog.json"), "w", encoding="utf-8") as f:
            json.dump({"songs": songs}, f)

    def disable(self, login_id):
        store = self.site.accounts()
        try:
            store.set_disabled(login_id, True)
        finally:
            store.db.close()

    def form_token(self, client, path):
        """The form token on a page (every form of a signed-in page carries the same one)."""
        page = client.get(path).text
        return page.split('name="csrf" value="', 1)[1].split('"', 1)[0]

    def admin(self, login_id="BOSS"):
        """An admin's account, signed in on self.client."""
        row = self.make(login_id, dj=login_id, admin=True)
        self.sign_in(self.client, login_id)
        return row


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class NewRecordsTest(SiteBase):
    """Item 1: Home's new records and the NEW mark on its recent plays."""

    def test_home_lists_new_records_with_their_gain_and_marks_new_bests(self):
        nova = self.make()
        rio = self.make("RIO", dj="RIO")
        ghost = self.make("GHOST", dj="GHOST")
        self.catalog([{"number": 1, "title": "Made-up Song"}, {"number": 2, "title": "Another Made-up Song"}])
        # NOVA on one chart: a first play (no best to beat), a record (+200), a lower play, a record (+200 again).
        self.play(nova, 1, 1, 500, at=1000)
        self.play(nova, 1, 1, 700, at=1100)
        self.play(nova, 1, 1, 600, at=1200)
        self.play(nova, 1, 1, 900, at=1300)
        # The same score as the best is no record either.
        self.play(nova, 1, 1, 900, at=1350)
        # RIO's first play of the chart is higher than NOVA's, but RIO had no best on it: no record.
        self.play(rio, 1, 1, 1000, at=1400)
        # A disabled player's record is nobody's to see.
        self.play(ghost, 2, 1, 100, at=1500)
        self.play(ghost, 2, 1, 999, at=1600)
        self.disable("GHOST")
        self.sign_in(self.client)
        page = self.client.get("/").text
        records = page.split('class="card records wide"', 1)[1].split("</ul>", 1)[0]
        # Newest first: 900 (+200 over 700), then 700 (+200 over 500).
        self.assertEqual(re.findall(r'class="score">([\d,]+)<span class="gain"', records), ["900", "700"])
        self.assertEqual(re.findall(r">\+([\d,]+)</span>", records), ["200", "200"])
        self.assertIn("Best before: 700", records)
        self.assertNotIn("GHOST", records)
        self.assertNotIn("1,000", records)
        # The NEW mark on the recent plays: the two records in NOVA's own list and in everyone's.
        mine = page.split("Your recent plays", 1)[1].split("</ul>", 1)[0]
        self.assertEqual(mine.count(">NEW</span>"), 2)
        everyone = page.split("Recent plays on this server", 1)[1].split("</ul>", 1)[0]
        self.assertEqual(everyone.count(">NEW</span>"), 2)

    def test_home_shows_ten_records_and_fifteen_plays_and_says_when_cut(self):
        nova = self.make()
        # Twenty plays on one chart, each higher than the last: nineteen records.
        for n in range(20):
            self.play(nova, 1, 1, 100 + n, at=1000 + n)
        self.sign_in(self.client)
        page = self.client.get("/").text
        records = page.split('class="card records wide"', 1)[1].split("</ul>", 1)[0]
        self.assertEqual(records.count("<li>"), 10)
        mine = page.split("Your recent plays", 1)[1].split("</div>", 1)[0]
        self.assertEqual(mine.count("<li>"), 15)
        self.assertIn("The latest 15 of 20", mine)
        # Korean says the same.
        self.client.cookies.set("opendmt3_lang", "ko")
        self.assertIn("전체 20개 중 최근 15개", self.client.get("/").text)

    def test_no_record_yet_says_so(self):
        nova = self.make()
        self.play(nova, 1, 1, 500)
        self.sign_in(self.client)
        page = self.client.get("/").text
        self.assertIn("No new record yet", page)
        self.assertNotIn(">NEW</span>", page)
        # A list that is not cut says nothing about it.
        self.assertNotIn("The latest", page)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class MessageTest(SiteBase):
    """Item 2: the message to send a player after a new account or a new password."""

    def message(self, page):
        """The read-only text of the page's message box, unescaped as a browser shows it."""
        import html
        box = re.search(r'<textarea id="message" class="message" readonly rows="(\d+)">(.*?)</textarea>', page, re.S)
        self.assertIsNotNone(box, "no message box")
        return int(box.group(1)), html.unescape(box.group(2))

    def test_a_new_account_comes_with_a_message_of_what_the_player_needs(self):
        from starlette.testclient import TestClient
        self.make("BOSS", dj="BOSS", admin=True)
        # The admin's browser reached the site at its public name over HTTPS: the message gives that address.
        browser = TestClient(self.app, base_url="https://dmt.example", client=("203.0.113.5", 50000))
        self.sign_in(browser, "BOSS")
        token = self.form_token(browser, "/admin/players")
        page = browser.post("/admin/players", data={"csrf": token, "action": "make", "login_id": "minho",
                                                     "dj_name": "MINHO", "password": "secret12"}).text
        rows, text = self.message(page)
        self.assertEqual(text, "Your account on this openDMT3 server.\nAddress: https://dmt.example/\nID: MINHO\n"
                               "Password: secret12\n\n1. Open the Download page and sign in with this ID and "
                               "password: https://dmt.example/download\n2. Download the launcher there and follow "
                               "the page's steps.")
        # Every line shows without scrolling.
        self.assertEqual(rows, text.count("\n") + 1)
        # A new password: the same message with it, in the admin's language.
        browser.cookies.set("opendmt3_lang", "ko")
        page = browser.post("/admin/players", data={"csrf": token, "action": "password", "login_id": "MINHO"}).text
        _, text = self.message(page)
        password = re.search(r"비밀번호: (\w+)", text).group(1)
        self.assertIn("주소: https://dmt.example/\nID: MINHO\n", text)
        # The page that asks for the sign-in first is the first step, named by its address (a messenger has no
        # "this site").
        self.assertIn("1. 다운로드 페이지를 열고 이 ID와 비밀번호로 로그인하세요: https://dmt.example/download\n"
                      "2. 그 페이지에서 런처를 다운로드하고 안내를 따르세요.", text)
        # An address other PCs reach: the page has nothing to add about it.
        self.assertNotIn("message-local", page)
        # The password in the message is the one that signs in.
        self.assertEqual(self.client.post("/api/v1/session", json={"login_id": "MINHO",
                                                                   "password": password}).status_code, 200)

    def test_the_message_carries_the_address_the_owner_chose_never_the_admins_own(self):
        from starlette.testclient import TestClient
        self.make("BOSS", dj="BOSS", admin=True)
        # The admin opens the site on the server PC itself, as the setup's last page says.
        browser = TestClient(self.app, base_url="http://127.0.0.1:4730", client=("127.0.0.1", 50000))
        self.sign_in(browser, "BOSS")
        token = self.form_token(browser, "/admin/players")

        def made(login_id):
            page = browser.post("/admin/players", data={"csrf": token, "action": "make", "login_id": login_id}).text
            return page, self.message(page)[1]

        # No address chosen for the players (a server started by hand): the message has the admin's own, which no
        # other PC reaches, and the page says which address to send in its place.
        page, text = made("ONE")
        self.assertIn("Address: http://127.0.0.1:4730/\n", text)
        self.assertIn('class="alert look message-local"', page)
        self.assertIn("This message carries an address only this PC reaches (http://127.0.0.1:4730/).", page)
        # The address the owner chose in ./dmt3 setup (the server keeps it): every message carries it, whatever
        # address the admin's browser used, and the page has nothing to add. The API's twin gives the same message.
        self.site.address = "http://192.168.0.5:4730/"
        page, text = made("TWO")
        self.assertIn("Address: http://192.168.0.5:4730/\n", text)
        self.assertIn("this ID and password: http://192.168.0.5:4730/download\n", text)
        self.assertNotIn("127.0.0.1", text)
        self.assertNotIn("message-local", page)
        auth = {"Authorization": "Bearer " + browser.post("/api/v1/session", json={
            "login_id": "BOSS", "password": "pass1234"}).json()["token"]}
        twin = browser.post("/api/v1/players", json={"login_id": "three"}, headers=auth).json()["message"]
        self.assertIn("Address: http://192.168.0.5:4730/\n", twin)
        # An address without its last slash is one too; one of this PC alone is said, chosen or not.
        self.site.address = "http://localhost:4730"
        page, text = made("FOUR")
        self.assertIn("Address: http://localhost:4730/\n", text)
        self.assertIn("message-local", page)

    def test_no_message_without_a_new_password(self):
        self.admin()
        self.make()
        token = self.form_token(self.client, "/admin/players")
        self.assertNotIn('id="message"', self.client.get("/admin/players").text)
        # Disabling, or a refused account, gives none either.
        page = self.client.post("/admin/players", data={"csrf": token, "action": "disable", "login_id": "NOVA"}).text
        self.assertNotIn('id="message"', page)
        page = self.client.post("/admin/players", data={"csrf": token, "action": "make", "login_id": "no way",
                                                        "password": ""}).text
        self.assertNotIn('id="message"', page)


def small_song_list(path, songs=1, title="Made-up Song"):
    """A song list as openDMT3 saves it, at its smallest: the list alone, its jackets and DJ cards said missing."""
    import json
    import zipfile
    from opendmt3.server.services import songlist
    rows = [{"number": n, "name": "made%d" % n, "title": "%s %d" % (title, n), "genre": "Pop", "composer": "Made Up",
             "star": [1, 2, 3, 0], "pop": [1, 0, 0, 0]} for n in range(1, songs + 1)]
    manifest = {"format": songlist.FORMAT, "version": songlist.VERSION, "saved": 1000, "by": "openDMT3 test",
                "songs": songs, "jackets": None, "cards": None,
                "missing": {"jackets": "The game's files have no jackets.", "cards": "The game's files have no DJ cards."},
                "reasons": {"jackets": "error.game.no_jackets", "cards": "error.card.tables"}}
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("manifest.json", json.dumps(manifest))
        z.writestr("catalog.json", json.dumps({"songs": rows}))
    return path


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class SongListPagesTest(SiteBase):
    """The Status page's Song list card, the Song list tab in the shape of OpenDMTQ's setup page (found on the server
    PC, another folder, an upload) and their API twins: each part's state, Import (asked first in the site's own
    dialog), an upload taken in or refused in words, one import at a time."""

    def card(self):
        """The Song list card's HTML on the Status page."""
        page = self.client.get("/admin/status").text
        return page.split('<div class="card game-data">', 1)[1].split("</div>", 1)[0]

    def reading(self, report=None, error=None):
        """sources.read made up: the report it gives, or the error it raises (the reading itself is
        test_sources.py's and test_catalog.py's)."""
        from unittest import mock
        from opendmt3.server.services import catalog as cat
        from opendmt3.server.services import sources

        def read(path, data, now=None, traces=False, password=None):
            if error:
                raise error
            # What a reading leaves: the list and the report.
            self.catalog([{"number": 1, "title": "Made-up Song"}])
            cat._save_report(data, report)
            return report
        return mock.patch.object(sources, "read", read)

    def token(self):
        r = self.client.post("/api/v1/session", json={"login_id": "BOSS", "password": "pass1234"})
        return r.json()["token"]

    def api(self, method, path, **kwargs):
        headers = dict(kwargs.pop("headers", {}), Authorization="Bearer " + self.token())
        return self.client.request(method, path, headers=headers, **kwargs)

    REPORT = {"at": 1000, "from": "folder", "path": "/games/made-up", "folder": "/games/made-up", "songs": 1,
              "jackets": None, "cards": None,
              "missing": {"jackets": "The game's files have no jackets.", "cards": "The game's files have no DJ cards."},
              "reasons": {"jackets": "error.game.no_jackets", "cards": "error.card.tables"}}

    def test_a_new_server_shows_every_part_not_yet_and_the_tab_that_imports_it(self):
        self.admin()
        card = self.card()
        self.assertIn("Song list", card)
        self.assertEqual(card.count("Not yet"), 3)
        # Before any reading the table has said it (and the list to look at above it): no line says it again.
        self.assertEqual(len(re.findall(r'class="alert look data-missing"', card)), 0)
        self.assertIn('href="/admin/song_list"', card)
        server = self.api("GET", "/api/v1/server").json()
        self.assertEqual([m["part"] for m in server["song_list"]["missing"]], ["songs", "jackets", "cards"])
        self.assertFalse(server["song_list"]["read_again"])
        # No body and no game folder given: the API says how else.
        r = self.api("POST", "/api/v1/server/song_list")
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (404, "no_game_folder"))

    def test_the_tab_shows_what_it_takes_what_is_found_and_imports_it(self):
        from unittest import mock
        from opendmt3.server.services import sources
        self.admin()
        self.site.game_folder = "/games/made-up"
        found = [{"path": "/games/made-up", "kind": "folder", "ready": True, "line": "x", "key": "source.folder",
                  "values": {"client": "original", "n": 1}},
                 {"path": "/games/cabinet", "kind": "folder", "ready": False, "line": "x",
                  "key": "error.game.cabinet_client", "values": {}}]
        with mock.patch.object(sources, "found", lambda where: found), \
                mock.patch.object(sources, "in_container", lambda: False):
            page = self.client.get("/admin/song_list?browse=" + self.tmp).text
        # What the server takes, said once where it is first shown.
        self.assertIn("The song list holds the jackets and the DJ cards too.", page)
        self.assertIn("not yet", page)
        # One line each, in the page's words; Import only beside the one that is ready, asked first.
        self.assertIn("Client data in a folder, original PC client, 1 song: ready", page)
        self.assertIn("The cabinet&#39;s client: does not work here, the PC client is needed.", page)
        self.assertEqual(page.count('data-ask-title="Import the song list"'), 2)
        self.assertIn('value="/games/made-up"', page)
        # Another folder on the server PC: its path, the folder browser, Import from this folder.
        self.assertIn("Another folder on the server PC", page)
        self.assertIn("Import from this folder", page)
        self.assertIn('name="browse" value="%s"' % self.tmp, page)
        # Imported from the path, as the page posts it: the line, and the change log's.
        with self.reading(self.REPORT), mock.patch.object(sources, "found", lambda where: found):
            page = self.client.post("/admin/song_list", data={"csrf": self.form_token(self.client, "/admin/status"),
                                                              "action": "import", "path": "/games/made-up"}).text
        self.assertIn("Imported the song list: 1 songs.", page)
        self.assertIn("No jackets: songs show without them. The game&#39;s files have no jackets.", page)
        self.assertIn("imported the song list from /games/made-up: 1 songs, jackets missing, cards missing",
                      self.client.get("/admin/log").text)

    def test_in_docker_the_tab_names_the_command_instead_of_a_folder_browser(self):
        from unittest import mock
        from opendmt3.server.services import sources
        self.admin()
        with mock.patch.object(sources, "in_container", lambda: True), \
                mock.patch.object(sources, "found", lambda where: []):
            page = self.client.get("/admin/song_list").text
        self.assertIn("<code>./dmt3 catalog PATH</code>", page)
        self.assertNotIn("Import from this folder", page)
        self.assertIn("This server sees no folder of the server PC to look in.", page)

    def upload(self, path, csrf=True):
        with open(path, "rb") as f:
            data = {"csrf": self.form_token(self.client, "/admin/status")} if csrf else {}
            return self.client.post("/admin/song_list/upload", data=data, files={"file": ("my-list.zip", f.read())})

    def test_a_song_list_uploaded_is_taken_or_refused_in_words(self):
        from unittest import mock
        from opendmt3.server.services import catalog as cat
        from opendmt3.server.services import songlist
        self.admin()
        good = small_song_list(os.path.join(self.tmp, "good.zip"), songs=2)
        page = self.upload(good).text
        self.assertIn("Imported the song list: 2 songs.", page)
        self.assertEqual(cat.title(cat.load(self.tmp), 2), "Made-up Song 2")
        self.assertEqual(cat.state(self.tmp)["source"], {"from": "file", "path": "my-list.zip", "made": 1000})
        self.assertIn("imported the song list from an uploaded song list (my-list.zip): 2 songs",
                      self.client.get("/admin/log").text)
        # Not a song list: said in words, and nothing changed.
        bad = os.path.join(self.tmp, "bad.zip")
        with open(bad, "wb") as f:
            f.write(b"not a zip at all")
        page = self.upload(bad).text
        self.assertIn("This is not a song list saved by openDMT3.", page)
        self.assertEqual(len(cat.load(self.tmp)), 2)
        # Without the form's token, nothing of it is read.
        self.assertIn("The form expired; try again.", self.upload(good, csrf=False).text)
        # Past the limit: the page says so, with 413.
        with mock.patch.object(songlist, "MOST", 10):
            r = self.upload(good)
        self.assertEqual(r.status_code, 413)
        # Nothing of an upload stays in the data folder.
        self.assertEqual([n for n in os.listdir(self.tmp) if n.startswith(cat.STAGING)], [])

    def test_the_api_imports_a_path_takes_a_file_lists_folders_and_one_at_a_time(self):
        from unittest import mock
        from opendmt3.server.services import sources
        self.admin()
        with self.reading(self.REPORT):
            r = self.api("POST", "/api/v1/server/song_list", json={"path": "/games/made-up"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["lines"][0], "song list: 1 songs")
        self.assertEqual(r.json()["song_list"]["source"], {"from": "folder", "path": "/games/made-up", "made": None})
        self.assertEqual(self.api("POST", "/api/v1/server/song_list", json={"no": "path"}).json()["error"]["code"],
                         "bad_request")
        # A path that is no game: refused with its one line.
        r = self.api("POST", "/api/v1/server/song_list", json={"path": os.path.join(self.tmp, "nothing")})
        self.assertEqual((r.status_code, r.json()["error"]["code"], r.json()["error"]["message"]),
                         (400, "refused", "This is not a folder or an archive holding client data."))
        # A song list as the body.
        with open(small_song_list(os.path.join(self.tmp, "list.zip"), songs=3), "rb") as f:
            r = self.api("POST", "/api/v1/server/song_list", content=f.read(),
                         headers={"Content-Type": "application/zip"})
        self.assertEqual((r.status_code, r.json()["song_list"]["songs"]["count"]), (200, 3), r.text)
        r = self.api("POST", "/api/v1/server/song_list", content=b"not a zip", headers={"Content-Type": "application/zip"})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, "refused"))
        # The tab's twin and the folder browser's.
        with mock.patch.object(sources, "found", lambda where: []):
            tab = self.api("GET", "/api/v1/server/song_list").json()
        self.assertEqual(sorted(tab), ["browse", "found", "places", "song_list"])
        listed = self.api("GET", "/api/v1/server/folders?path=" + self.tmp).json()
        self.assertEqual((listed["path"], listed["up"]), (self.tmp, os.path.dirname(self.tmp)))
        r = self.api("GET", "/api/v1/server/folders?path=" + os.path.join(self.tmp, "none"))
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, "refused"))
        # One import at a time.
        self.site.reading.acquire()
        try:
            r = self.api("POST", "/api/v1/server/song_list", json={"path": "/games/made-up"})
        finally:
            self.site.reading.release()
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (409, "busy"))
        # A player's token is refused, as every admin call refuses it.
        self.make()
        player = self.client.post("/api/v1/session", json={"login_id": "NOVA", "password": "pass1234"}).json()["token"]
        r = self.client.post("/api/v1/server/song_list", headers={"Authorization": "Bearer " + player})
        self.assertEqual(r.status_code, 403)

    def test_an_archive_with_a_name_twice_is_refused_in_words_never_with_a_path(self):
        # The security review's proof 5 through the API: refused (400) with the entry's line, where it was a 409 that
        # said a FileExistsError with a path of the server's.
        from tests.server.test_sources import twice_zip
        self.admin()
        archive = twice_zip(os.path.join(self.tmp, "technika.zip"), "g/pack/DiscInfo.pak")
        r = self.api("POST", "/api/v1/server/song_list", json={"path": archive})
        self.assertEqual((r.status_code, r.json()["error"]["code"], r.json()["error"]["message"]),
                         (400, "refused", "An entry in this archive cannot be taken: g/pack/DiscInfo.pak"), r.text)
        self.assertNotIn(self.tmp, r.text)

    def test_the_card_and_the_tab_in_korean(self):
        from unittest import mock
        from opendmt3.server.services import sources
        self.admin()
        self.client.cookies.set("opendmt3_lang", "ko")
        card = self.card()
        self.assertIn("곡 목록", card)
        self.assertIn("아직 없음", card)
        with mock.patch.object(sources, "found", lambda where: []), \
                mock.patch.object(sources, "in_container", lambda: False):
            page = self.client.get("/admin/song_list").text
        for words in ("곡 목록에는 자켓과 DJ 카드도 들어 있습니다.", "서버 PC에서 찾은 파일", "서버 PC의 다른 폴더",
                      "곡 목록 올리기", "이 폴더에서 가져오기"):
            self.assertIn(words, page)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class LookTest(SiteBase):
    """Item 3: the Status page's list of what to look at, each line only when it is so."""

    def looks(self):
        """The lines of the list on the Status page (none when there is no list)."""
        page = self.client.get("/admin/status").text
        if "To look at" not in page:
            return []
        return re.findall(r'<p class="alert look">(.*?)</p>', page, re.S)

    def test_each_line_shows_only_while_it_is_so(self):
        from unittest import mock
        from opendmt3.server.services import backups, sources
        self.admin()
        # A new server: no backup, no song list, no installer; no other account, so nothing about accounts. Run as a
        # program, not in a container: the installer's line names the folder (in a container, ./dmt3 setup).
        with mock.patch.object(sources, "in_container", lambda: False):
            lines = self.looks()
        self.assertEqual(len(lines), 3)
        self.assertIn("No backup in the last 7 days.", lines[0])
        self.assertIn('href="/admin/backups"', lines[0])
        self.assertIn("No song list", lines[1])
        self.assertIn('href="/admin/song_list"', lines[1])
        self.assertIn("put openDMT3-win-Setup.exe in " + self.site.downloads, lines[2])
        # A backup eight days old is still too old; one now is not.
        backups.make(self.site.db_path, self.tmp, "manual", now=time.time() - 8 * 86400)
        self.assertIn("No backup", self.looks()[0])
        backups.make(self.site.db_path, self.tmp, "manual")
        self.catalog([{"number": 1, "title": "Made-up Song"}])
        os.makedirs(self.site.downloads)
        with open(os.path.join(self.site.downloads, "openDMT3-win-Setup.exe"), "wb") as f:
            f.write(b"MZ")
        self.assertEqual(self.looks(), [])
        # Other accounts, all disabled: nobody but the admin can play.
        self.make()
        self.make("RIO", dj="RIO")
        self.disable("NOVA")
        self.assertEqual(self.looks(), [])
        self.disable("RIO")
        lines = self.looks()
        self.assertEqual(len(lines), 1)
        self.assertIn("Every account but yours is disabled", lines[0])
        self.assertIn('href="/admin/players"', lines[0])
        # In Korean too.
        self.client.cookies.set("opendmt3_lang", "ko")
        self.assertIn("내 계정 말고는 모든 계정이 비활성화되어", self.client.get("/admin/status").text)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class PlaysLogTest(SiteBase):
    """Item 4: the Logs tab's plays: filters, pages of 50, totals and the CSV file."""

    def setUp(self):
        super().setUp()
        self.admin()
        self.now = int(time.time())
        nova = self.make()
        # A DJ name a spreadsheet would read as a formula.
        rio = self.make("RIO", dj="=SUM(1)")
        self.catalog([{"number": 1, "title": "Made-up Opening"}, {"number": 2, "title": "Another Song"},
                      {"number": 3, "title": "Closing Opening Theme"}])
        # NOVA: 55 plays of song 1 over the last 50 days (one a day... and five more today); RIO: three today.
        for n in range(55):
            self.play(nova, 1, 1, 1000 + n, at=self.now - (n % 50) * 86400 - n)
        for song in (2, 3, 77):
            self.play(rio, song, 2, 500, mode=1, at=self.now - 60)
        self.nova, self.rio = nova, rio

    def rows(self, page):
        return re.findall(r'<tr><td class="muted when">', page)

    def test_pages_of_fifty_with_totals_and_older_and_newer(self):
        page = self.client.get("/admin/log/plays").text
        self.assertEqual(len(self.rows(page)), 50)
        # Every play the filter leaves is counted, not only this page's.
        self.assertRegex(page, r'<span class="value">58</span><span class="label">Plays</span>')
        self.assertRegex(page, r'<span class="value">2</span><span class="label">Players</span>')
        self.assertRegex(page, r'<span class="value">4</span><span class="label">Charts</span>')
        self.assertIn('href="/admin/log/plays?page=2">Older</a>', page)
        self.assertNotIn(">Newer</a>", page)
        older = self.client.get("/admin/log/plays?page=2").text
        self.assertEqual(len(self.rows(older)), 8)
        self.assertIn('href="/admin/log/plays?page=1">Newer</a>', older)
        self.assertNotIn(">Older</a>", older)
        # Past the last page: nothing, and the way back.
        self.assertIn("No play matches.", self.client.get("/admin/log/plays?page=9").text)
        # What cannot be read is no filter.
        self.assertEqual(len(self.rows(self.client.get("/admin/log/plays?page=x&days=5&player=y").text)), 50)

    def test_filters_by_player_days_and_a_word_of_the_title(self):
        page = self.client.get("/admin/log/plays?player=%d" % self.rio["id"]).text
        self.assertEqual(len(self.rows(page)), 3)
        self.assertRegex(page, r'<span class="value">1</span><span class="label">Players</span>')
        # The last 24 hours: RIO's three and NOVA's plays of today (n = 0 and 50).
        self.assertEqual(len(self.rows(self.client.get("/admin/log/plays?days=1").text)), 5)
        # Seven days: NOVA's days 0 to 6 (twice for 0 to 4) and RIO's three.
        self.assertEqual(len(self.rows(self.client.get("/admin/log/plays?days=7").text)), 15)
        # A word of the title, in any case: songs 1 and 3 have "opening".
        page = self.client.get("/admin/log/plays?q=OPENING&player=%d" % self.rio["id"]).text
        self.assertEqual(len(self.rows(page)), 1)
        self.assertIn("Closing Opening Theme", page)
        # A song missing from the list goes by its number, as it is shown.
        self.assertEqual(len(self.rows(self.client.get("/admin/log/plays?q=%2377").text)), 1)
        self.assertIn("No play matches.", self.client.get("/admin/log/plays?q=nothing+like+it").text)
        # The filter is kept in the links: the file and the next page.
        self.assertIn('href="/admin/log/plays.csv?days=30&amp;q=opening"',
                      self.client.get("/admin/log/plays?q=opening&days=30").text)
        page = self.client.get("/admin/log/plays?q=opening").text
        self.assertIn('href="/admin/log/plays?q=opening&amp;page=2">Older</a>', page)

    def test_the_csv_holds_every_play_the_filter_leaves(self):
        import csv
        import io
        r = self.client.get("/admin/log/plays.csv")
        self.assertEqual(r.headers["content-type"], "text/csv; charset=utf-8")
        self.assertRegex(r.headers["content-disposition"], r'attachment; filename="openDMT3-plays-\d{8}\.csv"')
        # The mark that tells a spreadsheet the file is UTF-8, then the columns.
        self.assertTrue(r.content.startswith("\ufeff".encode()))
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
        self.assertEqual(rows[0], ["when", "dj", "mode", "song", "title", "pattern", "score"])
        # All of them, not a page; newest first.
        self.assertEqual(len(rows), 1 + 58)
        # ISO 8601 with the server's offset from UTC; the newest is NOVA's play of now.
        self.assertRegex(rows[1][0], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")
        self.assertEqual(time.mktime(time.strptime(rows[1][0][:19], "%Y-%m-%dT%H:%M:%S")), self.now)
        self.assertEqual(rows[1][1:], ["DJ NOVA", "STAR", "1", "Made-up Opening", "1", "1000"])
        # The player's own text never reads as a formula.
        rio = [r for r in rows if r[3] == "2"][0]
        self.assertEqual(rio[1:], ["'=SUM(1)", "POP", "2", "Another Song", "2", "500"])
        # A filtered file: one player's plays of one song.
        rows = list(csv.reader(io.StringIO(self.client.get(
            "/admin/log/plays.csv?player=%d&q=another" % self.rio["id"]).content.decode("utf-8-sig"))))
        self.assertEqual([(r[3], r[4]) for r in rows[1:]], [("2", "Another Song")])

    def test_the_plays_log_is_for_admins_only(self):
        self.client.cookies.clear()
        self.sign_in(self.client)
        self.assertEqual(self.client.get("/admin/log/plays").status_code, 404)
        self.assertEqual(self.client.get("/admin/log/plays.csv").status_code, 404)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class MonthTest(SiteBase):
    """Item 5: the Rankings page's This month, with the first three of each month before it."""

    def test_this_month_counts_this_months_plays_only(self):
        from opendmt3.server.web import common
        now = time.time()
        this, last = common._month_start(now), common._month_start(now, 1)
        nova = self.make()
        rio = self.make("RIO", dj="RIO")
        # NOVA scored high last month (a second before this month began); this month only a little.
        self.play(nova, 1, 1, 5000, at=this - 1)
        self.play(nova, 1, 1, 100, at=this)
        self.play(rio, 1, 1, 300, at=this + 5)
        self.play(rio, 2, 1, 50, at=this + 6)
        self.sign_in(self.client)
        page = self.client.get("/rankings?by=month").text
        # This month: RIO 350 over two charts, NOVA 100; the months before have NOVA's 5,000.
        board = page.split('<table class="table board">', 1)[1].split("</table>", 1)[0]
        self.assertEqual(re.findall(r'class="num score">([\d,]+)<', board), ["350", "100"])
        # The hint names the month ("November 2026"), and the months before it are named the same way.
        from opendmt3.server.web import strings
        self.assertIn("best score on every chart in %s," % common._month_name(strings.words("en"), this), page)
        past = page.split("Past months", 1)[1]
        self.assertIn("<h4>%s</h4>" % common._month_name(strings.words("en"), last), past)
        self.assertIn(time.strftime("%Y", time.localtime(last)), past)
        self.assertRegex(past, r'place-1">1</span><a href="/dj/%d">DJ NOVA</a><span class="score">5,000<' % nova["id"])
        # The total ranks the other way round.
        board = self.client.get("/rankings").text.split('<table class="table board">', 1)[1]
        self.assertEqual(re.findall(r'class="num score">([\d,]+)<', board.split("</table>", 1)[0]), ["5,000", "350"])
        # The tab is there beside the other two, in both languages.
        self.assertIn(">This month</a>", page)
        self.client.cookies.set("opendmt3_lang", "ko")
        page = self.client.get("/rankings?by=month").text
        self.assertIn(">이번 달</a>", page)
        self.assertIn("%d년 %d월" % (time.localtime(last).tm_year, time.localtime(last).tm_mon), page)

    def test_past_months_show_three_places_twelve_months_back_per_mode(self):
        from opendmt3.server.web import common
        now = time.time()
        people = [self.make("P%d" % n, dj="DJ%d" % n) for n in range(5)]
        ghost = self.make("GHOST", dj="GHOST")
        # Last month: five players; two share second place; a disabled player above them all.
        last = common._month_start(now, 1)
        for person, score in zip(people, (900, 800, 800, 700, 600)):
            self.play(person, 1, 1, score, at=last + 100)
        self.play(ghost, 1, 1, 99999, at=last + 100)
        self.disable("GHOST")
        # Twelve months back is shown, thirteen is not; a POP play is in POP's months only.
        self.play(people[4], 1, 1, 10, at=common._month_start(now, 12) + 5)
        self.play(people[4], 1, 1, 20, at=common._month_start(now, 13) + 5)
        self.play(people[3], 1, 1, 30, mode=1, at=last + 5)
        self.sign_in(self.client, "P0")
        past = self.client.get("/rankings?mode=0&by=month").text.split("Past months", 1)[1]
        months = re.findall(r"<h4>(.*?)</h4>", past)
        self.assertEqual(len(months), 2)
        first = past.split("</ol>", 1)[0]
        self.assertEqual(re.findall(r'past-place place-(\d)">', first), ["1", "2", "2"])
        self.assertNotIn("GHOST", past)
        self.assertNotIn("DJ3", first)
        # The oldest month shown: twelve months back, with its one play.
        self.assertIn(">10<", past.split("</ol>")[1])
        # POP's months: the one POP play only.
        past = self.client.get("/rankings?mode=1&by=month").text.split("Past months", 1)[1]
        self.assertEqual(re.findall(r'<a href="/dj/\d+">(.*?)</a>', past.split("</div>\n</section>", 1)[0]), ["DJ3"])
        # A month nobody played in this mode says so, and the months before still show.
        page = self.client.get("/rankings?mode=0&by=month").text
        self.assertIn("No cleared stage in this mode this month yet.", page)

    def test_a_long_ranking_shows_its_first_rows_and_says_how_many(self):
        from unittest import mock
        from opendmt3.server.web import pages
        for n in range(4):
            self.play(self.make("P%d" % n, dj="DJ%d" % n), 1, 1, 100 + n)
        self.sign_in(self.client, "P0")
        with mock.patch.object(pages, "RANKING_SHOWN", 3):
            page = self.client.get("/rankings").text
        board = page.split('<table class="table board">', 1)[1].split("</table>", 1)[0]
        self.assertEqual(board.count("<tr class="), 3)
        self.assertIn("Top 3 of 4", page)
        # Not cut, nothing said.
        self.assertNotIn("Top ", self.client.get("/rankings").text)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class RightsTest(SiteBase):
    """Item 6: admin rights given and taken, never from the only enabled admin, and a DJ renamed by an admin."""

    def post(self, **data):
        token = self.form_token(self.client, "/admin/players")
        return self.client.post("/admin/players", data=dict(data, csrf=token), follow_redirects=False)

    def changes(self):
        return self.client.get("/admin/log").text

    def test_rights_are_given_and_taken_and_logged(self):
        from starlette.testclient import TestClient
        self.admin()
        self.make()
        page = self.post(action="admin_on", login_id="nova").text
        self.assertIn("NOVA has admin rights now.", page)
        self.assertIn("gave admin rights to NOVA", self.changes())
        # NOVA, in a browser of their own, has the admin pages now; then not any more.
        nova = TestClient(self.app, client=("198.51.100.60", 50000))
        self.sign_in(nova)
        self.assertEqual(nova.get("/admin/players").status_code, 200)
        page = self.post(action="admin_off", login_id="NOVA").text
        self.assertIn("NOVA has no admin rights now.", page)
        self.assertIn("took admin rights from NOVA", self.changes())
        self.assertEqual(nova.get("/admin/players").status_code, 404)

    def test_the_only_enabled_admin_keeps_their_rights_and_stays_enabled(self):
        self.admin()
        self.make("RIO", dj="RIO", admin=True)
        # A disabled admin is no admin who can sign in: BOSS is still the only one.
        self.disable("RIO")
        for action in ("admin_off", "disable"):
            page = self.post(action=action, login_id="BOSS").text
            self.assertIn("The server needs an enabled admin, and BOSS is the only one.", page)
        store = self.site.accounts()
        try:
            row = store.by_login("BOSS")
            self.assertEqual((row["is_admin"], row["disabled"]), (1, 0))
        finally:
            store.db.close()
        self.assertNotIn("took admin rights", self.changes())
        # In Korean too.
        self.client.cookies.set("opendmt3_lang", "ko")
        self.assertIn("서버에는 활성화된 관리자가 있어야 하는데 BOSS 한 명뿐입니다.",
                      self.post(action="admin_off", login_id="BOSS").text)

    def test_an_admin_takes_their_own_rights_while_another_admin_is_there(self):
        self.admin()
        self.make(admin=True)
        r = self.post(action="admin_off", login_id="BOSS")
        # Their own rights gone: Home, and the admin pages are not theirs any more.
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/"))
        self.assertEqual(self.client.get("/admin/players").status_code, 404)

    def test_two_admins_taking_each_others_rights_cannot_both_win(self):
        from unittest import mock
        from opendmt3.server import db
        from opendmt3.server.services import accounts
        self.make("ONE", admin=True)
        self.make("TWO", admin=True)
        store = accounts.Accounts(db.connect(self.site.db_path))
        try:
            self.assertTrue(store.set_admin("TWO", False))
            # ONE's check made before TWO's change went through (it saw two admins): the change itself refuses, with
            # the words of the last admin's refusal.
            with mock.patch.object(accounts.Accounts, "leaves_no_admin", return_value=False):
                with self.assertRaises(accounts.AccountError) as refused:
                    store.set_admin("ONE", False)
            self.assertEqual(refused.exception.key, "error.account.last_admin")
            self.assertEqual(store.db.execute("SELECT COUNT(*) FROM accounts WHERE is_admin = 1").fetchone()[0], 1)
            # Giving rights is never refused; an unknown ID changes nothing.
            self.assertTrue(store.set_admin("TWO", True))
            self.assertFalse(store.set_admin("NOBODY", True))
        finally:
            store.db.close()

    def test_an_admin_renames_a_dj_by_the_account_pages_rules(self):
        self.admin()
        self.make()
        page = self.post(action="rename", login_id="NOVA", dj_name=" 노바 NOVA ").text
        self.assertIn("NOVA&#39;s DJ name is now 노바 NOVA.", page)
        self.assertIn("named NOVA 노바 NOVA", self.changes())
        # Too long, or nothing: the account page's own refusal; the name stays.
        for name in ("NINE CHAR", ""):
            page = self.post(action="rename", login_id="NOVA", dj_name=name).text
            self.assertIn("A DJ name is 1 to 8 characters.", page)
        store = self.site.accounts()
        try:
            self.assertEqual(store.by_login("NOVA")["dj_name"], "노바 NOVA")
        finally:
            store.db.close()
        # Without the form's token nothing changes.
        self.client.post("/admin/players", data={"csrf": "x", "action": "rename", "login_id": "NOVA",
                                                 "dj_name": "EVIL"})
        store = self.site.accounts()
        try:
            self.assertEqual(store.by_login("NOVA")["dj_name"], "노바 NOVA")
        finally:
            store.db.close()

    def test_rights_and_names_are_for_admins_only(self):
        self.make("BOSS", admin=True)
        self.make()
        self.sign_in(self.client)
        r = self.client.post("/admin/players", data={"csrf": self.form_token(self.client, "/"), "action": "admin_on",
                                                     "login_id": "NOVA"})
        self.assertEqual(r.status_code, 404)
        store = self.site.accounts()
        try:
            self.assertEqual(store.by_login("NOVA")["is_admin"], 0)
        finally:
            store.db.close()


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class NoticeTest(SiteBase):
    """Item 7: the notice the admin sets on the Status page, shown on every page of the site and nowhere else."""

    def set_notice(self, text, action="set"):
        token = self.form_token(self.client, "/admin/status")
        return self.client.post("/admin/status", data={"csrf": token, "action": action, "text": text})

    def test_the_notice_is_on_every_page_escaped_and_not_in_the_api(self):
        import json
        from starlette.testclient import TestClient
        self.admin()
        page = self.set_notice("Closed on <b>Sunday</b>\nfor a backup").text
        self.assertIn("The notice is on every page now.", page)
        shown = '<span class="text">Closed on &lt;b&gt;Sunday&lt;/b&gt; for a backup</span>'
        # Every page: the admin's, the public ones, a page that is not there, and the sign-in page.
        for path in ("/admin/status", "/", "/rankings", "/songs", "/download", "/account", "/nowhere"):
            self.assertIn(shown, self.client.get(path).text, path)
        stranger = TestClient(self.app, client=("198.51.100.70", 50000))
        self.assertIn(shown, stranger.get("/signin").text)
        # Not the API's other answers, not the health check: the notice's own call is its twin (GET /api/v1/notice).
        token = self.client.post("/api/v1/session", json={"login_id": "BOSS", "password": "pass1234"}).json()["token"]
        for path in ("/api/v1/status", "/api/v1/server", "/health"):
            self.assertNotIn("Sunday", self.client.get(path, headers={"Authorization": "Bearer " + token}).text, path)
        # Kept in the data folder as a small JSON file, nothing half written left beside it.
        with open(os.path.join(self.tmp, "notice.json"), encoding="utf-8") as f:
            kept = json.load(f)
        self.assertEqual((kept["text"], kept["by"]), ("Closed on <b>Sunday</b> for a backup", "BOSS"))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "notice.json.new")))
        self.assertIn("set the notice: Closed on", self.client.get("/admin/log").text)
        # Cleared: gone from every page and from the folder.
        page = self.set_notice("", action="clear").text
        self.assertIn("The notice is cleared.", page)
        self.assertNotIn('class="site-notice"', self.client.get("/").text)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "notice.json")))
        self.assertIn("cleared the notice", self.client.get("/admin/log").text)

    def test_a_notice_is_one_line_of_two_hundred_characters_at_most(self):
        self.admin()
        self.set_notice("x" * 200)
        self.assertIn("x" * 200, self.client.get("/").text)
        # One more is refused, and so are characters that are not text; the notice shown stays.
        for refused in ("y" * 201, "turned ‮around", "bell \x07"):
            page = self.set_notice(refused).text
            self.assertIn("A notice is one line of up to 200 characters.", page, repr(refused))
            self.assertIn("x" * 200, self.client.get("/").text)
        # Korean words for the refusal.
        self.client.cookies.set("opendmt3_lang", "ko")
        self.assertIn("공지는 200자까지 한 줄로 씁니다.", self.set_notice("y" * 201).text)
        # A line left empty clears it too.
        self.set_notice("   ")
        self.assertNotIn('class="site-notice"', self.client.get("/").text)

    def test_only_an_admin_sets_it_with_the_pages_own_form(self):
        self.admin()
        self.client.post("/admin/status", data={"csrf": "x", "action": "set", "text": "from elsewhere"})
        self.assertNotIn("from elsewhere", self.client.get("/").text)
        self.client.cookies.clear()
        self.make()
        self.sign_in(self.client)
        r = self.client.post("/admin/status", data={"csrf": self.form_token(self.client, "/"), "action": "set",
                                                    "text": "a player's"})
        self.assertEqual(r.status_code, 404)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "notice.json")))

    def test_a_notice_file_that_cannot_be_read_shows_no_notice(self):
        self.admin()
        for broken in ("{not json", "[1, 2]", '{"text": 5}'):
            with open(os.path.join(self.tmp, "notice.json"), "w") as f:
                f.write(broken)
            page = self.client.get("/")
            self.assertEqual(page.status_code, 200, broken)
            self.assertNotIn('class="site-notice"', page.text, broken)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class DjPageTest(SiteBase):
    """Item 8: the DJ page says when a list is cut, and shows the DJ's place in each mode's ranking by total."""

    def test_the_dj_page_says_top_20_of_n_and_the_other_cuts(self):
        nova = self.make()
        # 25 charts (25 songs), each played once: 25 bests, 25 plays.
        for n in range(25):
            self.play(nova, 1 + n, 1, 1000 + n, at=1000 + n)
        self.sign_in(self.client)
        page = self.client.get("/dj/%d" % nova["id"]).text
        bests = page.split("Best scores", 1)[1].split("</div>", 1)[0]
        self.assertEqual(bests.count("<li>"), 20)
        self.assertIn("Top 20 of 25", bests)
        # Recent plays: the latest 10 of 25; most played: 5 of the 25 songs.
        self.assertIn("The latest 10 of 25", page.split("Recent plays", 1)[1].split("</div>", 1)[0])
        self.assertIn("Top 5 of 25", page.split("Most played", 1)[1].split("</div>", 1)[0])
        self.client.cookies.set("opendmt3_lang", "ko")
        self.assertIn("전체 25 중 상위 20위까지", self.client.get("/dj/%d" % nova["id"]).text)

    def test_a_list_that_is_not_cut_says_nothing(self):
        nova = self.make()
        for n in range(3):
            self.play(nova, 1 + n, 1, 1000 + n, at=1000 + n)
        self.sign_in(self.client)
        page = self.client.get("/dj/%d" % nova["id"]).text
        self.assertNotIn("Top ", page)
        self.assertNotIn("The latest", page)

    def test_the_djs_place_in_each_modes_ranking(self):
        nova = self.make()
        rio = self.make("RIO", dj="RIO")
        hana = self.make("HANA", dj="HANA")
        ghost = self.make("GHOST", dj="GHOST")
        # STAR totals: NOVA 300; RIO and HANA 200 each (sharing second place); a disabled player counts nowhere.
        self.play(nova, 1, 1, 300)
        self.play(rio, 1, 1, 200)
        self.play(hana, 2, 1, 200)
        self.play(ghost, 1, 1, 999)
        self.disable("GHOST")
        # POP: HANA alone.
        self.play(hana, 1, 1, 50, mode=1)
        self.sign_in(self.client)
        page = self.client.get("/dj/%d" % hana["id"]).text
        places = page.split('class="stats places"', 1)[1].split("</div>\n", 1)[0]
        self.assertIn('<a class="stat" href="/rankings?mode=0"><span class="value">2 / 3</span>'
                      '<span class="label">STAR ranking by total</span></a>', places)
        self.assertIn('<a class="stat" href="/rankings?mode=1"><span class="value">1 / 1</span>'
                      '<span class="label">POP ranking by total</span></a>', places)
        # The same places as the Rankings page gives.
        token = self.client.post("/api/v1/session", json={"login_id": "NOVA", "password": "pass1234"}).json()["token"]
        rows = self.client.get("/api/v1/rankings?mode=0", headers={"Authorization": "Bearer " + token}).json()["rows"]
        self.assertEqual([(r["dj_name"], r["place"]) for r in rows], [("DJ NOVA", 1), ("RIO", 2), ("HANA", 2)])
        self.assertIn('<span class="value">1 / 3</span>', self.client.get("/dj/%d" % nova["id"]).text)
        # A DJ with no play has no place; Korean words for the label.
        self.client.cookies.set("opendmt3_lang", "ko")
        self.assertIn("POP 총점 랭킹", self.client.get("/dj/%d" % hana["id"]).text)
        boss = self.make("BOSS", dj="BOSS")
        self.assertNotIn('class="stats places"', self.client.get("/dj/%d" % boss["id"]).text)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class BackupDeleteTest(SiteBase):
    """Item 9: one backup deleted from the admin's Backups tab, asked first, with the page's own form only."""

    def test_a_backup_is_deleted_after_the_sites_own_question(self):
        import html.parser
        from opendmt3.server.services import backups
        self.admin()
        name = backups.make(self.site.db_path, self.tmp, "manual")
        page = self.client.get("/admin/backups").text
        asks = []

        class Forms(html.parser.HTMLParser):
            def handle_starttag(self, tag, attrs):
                if tag == "form" and dict(attrs).get("data-ask"):
                    asks.append(dict(attrs))

        Forms().feed(page)
        # The site's own dialog asks first (static/site.js), as before deleting a player.
        delete = [a for a in asks if a["data-ask-yes"] == "Delete"]
        self.assertEqual(len(delete), 1)
        self.assertTrue(delete[0]["data-ask"].startswith("Delete the backup of "))
        self.assertTrue(delete[0]["data-ask-title"] and delete[0]["data-ask-detail"])
        token = self.form_token(self.client, "/admin/backups")
        # Another site's form (no token): nothing goes.
        self.client.post("/admin/backups", data={"action": "delete", "name": name})
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "backups", name)))
        page = self.client.post("/admin/backups", data={"csrf": token, "action": "delete", "name": name}).text
        self.assertIn("Deleted %s." % name, page)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "backups", name)))
        self.assertEqual(backups.all_backups(self.tmp), [])
        self.assertIn("deleted the backup %s" % name, self.client.get("/admin/log").text)

    def test_only_a_backups_own_name_and_only_by_an_admin(self):
        from opendmt3.server.services import backups
        self.admin()
        name = backups.make(self.site.db_path, self.tmp, "manual")
        token = self.form_token(self.client, "/admin/backups")
        for wrong in ("../openDMT3.sqlite", "openDMT3.sqlite", "nothing.sqlite"):
            page = self.client.post("/admin/backups", data={"csrf": token, "action": "delete", "name": wrong}).text
            self.assertIn("No backup named %s" % wrong.replace("'", "&#39;"), page)
        self.assertTrue(os.path.isfile(self.site.db_path))
        self.client.cookies.clear()
        self.make()
        self.sign_in(self.client)
        r = self.client.post("/admin/backups", data={"csrf": self.form_token(self.client, "/"), "action": "delete",
                                                     "name": name})
        self.assertEqual(r.status_code, 404)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "backups", name)))


def windows_program(version, tail=b""):
    """A small Windows program file (PE32) with nothing in it but a version resource giving `version` (four
    numbers), the way the build's version file puts one in: DOS header, PE header, one .rsrc section."""
    import struct
    fixed = struct.pack("<13I", 0xFEEF04BD, 0x10000, version[0] << 16 | version[1], version[2] << 16 | version[3],
                        version[0] << 16 | version[1], version[2] << 16 | version[3], 0x3F, 0, 0x40004, 1, 0, 0, 0)
    info = struct.pack("<3H", 6 + 32 + 2 + len(fixed), len(fixed), 0) + "VS_VERSION_INFO\0".encode("utf-16-le")
    info += b"\0\0" + fixed
    # The resource tree: type 16 (RT_VERSION), name 1, language 0x409, then the data's entry and the data itself.
    tree = struct.pack("<12xHH", 0, 1) + struct.pack("<II", 16, 0x80000000 | 0x18)
    tree += struct.pack("<12xHH", 0, 1) + struct.pack("<II", 1, 0x80000000 | 0x30)
    tree += struct.pack("<12xHH", 0, 1) + struct.pack("<II", 0x409, 0x48)
    tree += struct.pack("<IIII", 0x1000 + 0x58, len(info), 0, 0)
    section = tree + info
    dos = b"MZ" + bytes(0x3A) + struct.pack("<I", 0x40)
    optional = bytearray(224)
    struct.pack_into("<H", optional, 0, 0x10B)
    struct.pack_into("<I", optional, 92, 16)
    struct.pack_into("<II", optional, 96 + 2 * 8, 0x1000, len(section))
    coff = struct.pack("<HHIIIHH", 0x14C, 1, 0, 0, 0, 224, 0x102)
    table = b".rsrc\0\0\0" + struct.pack("<IIII", len(section), 0x1000, len(section), 0x200) + bytes(16)
    head = dos + b"PE\0\0" + coff + bytes(optional) + table
    return head + bytes(0x200 - len(head)) + section + tail


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class HomeSongsDownloadTest(SiteBase):
    """Item 10: Home's top DJs, the songs filter's count, the Download page's facts and the installer's name."""

    def test_home_shows_the_first_modes_top_five(self):
        people = [self.make("P%d" % n, dj="DJ%d" % n) for n in range(7)]
        # POP (mode 1) only for P6; STAR (mode 0) for the others, P5 highest.
        for n, person in enumerate(people[:6]):
            self.play(person, 1, 1, 100 * (n + 1))
        self.play(people[6], 1, 1, 9999, mode=1)
        self.sign_in(self.client, "P0")
        page = self.client.get("/").text
        top = page.split("Top DJs, STAR", 1)[1].split("</ol>", 1)[0]
        self.assertEqual(re.findall(r'<a href="/dj/\d+">(DJ\d)</a>', top), ["DJ5", "DJ4", "DJ3", "DJ2", "DJ1"])
        self.assertNotIn("DJ6", top)
        self.assertIn('<a href="/rankings?mode=0">The whole ranking</a>', page)

    def test_home_without_a_play_says_the_ranking_is_empty(self):
        self.make()
        self.sign_in(self.client)
        page = self.client.get("/").text
        self.assertIn("No cleared stage yet.", page)
        # The card is named in the page's words, as its other cards are (not by the menu's capitals).
        self.assertIn("<h3>Rankings</h3>", page)

    def test_the_songs_page_counts_the_songs_shown_and_marks_rows_for_the_filter(self):
        self.catalog([{"number": 1, "title": "Made-up Opening", "composer": "Someone"},
                      {"number": 2, "title": "Another Song", "composer": "Nobody"},
                      {"number": 3, "title": "Third Song", "composer": ""}])
        self.make()
        self.sign_in(self.client)
        page = self.client.get("/songs").text
        self.assertIn('id="song-filter"', page)
        self.assertRegex(page, r'id="song-count" aria-live="polite" data-words="\{n\} of \{of\} songs" '
                               r'data-total="3">3 of 3 songs</p>')
        # What the script matches a typed word against: the title and composer in small letters, and the number.
        self.assertIn('data-find="made-up opening someone" data-number="1"', page)
        # Find (the server's search) narrows the rows too, and the count says so.
        self.assertIn(">1 of 3 songs</p>", self.client.get("/songs?q=nobody").text)
        page = self.client.get("/songs?q=nothing").text
        self.assertIn(">0 of 3 songs</p>", page)
        self.assertRegex(page, r'<p class="muted" id="song-none" data-words="No song matches \{query\}.">'
                               r'No song matches nothing.</p>')
        self.client.cookies.set("opendmt3_lang", "ko")
        self.assertIn(">3곡 중 3곡</p>", self.client.get("/songs").text)

    def test_the_download_page_gives_the_installers_facts_and_name(self):
        from starlette.testclient import TestClient
        self.make()
        browser = TestClient(self.app, base_url="https://dmt.example", client=("203.0.113.5", 50000))
        self.sign_in(browser)
        os.makedirs(self.site.downloads)
        path = os.path.join(self.site.downloads, "openDMT3-win-Setup.exe")
        # Not a Windows program the version can be read from: size and date only.
        with open(path, "wb") as f:
            f.write(b"MZ" + bytes(3 * 1048576))
        moment = time.mktime((2026, 11, 2, 9, 30, 0, 0, 0, -1))
        os.utime(path, (moment, moment))
        page = browser.get("/download").text
        self.assertIn("3.0 MB, put on this server 2026-11-02 09:30", page)
        self.assertNotIn("Version", page.split('class="muted small file-facts"', 1)[1].split("</p>", 1)[0])
        # Step 1 names the file as it comes, with this server's address in it.
        self.assertIn("Run openDMT3-win-Setup-dmt.example-443.exe.", page)
        got = browser.get("/download/windows")
        self.assertEqual(got.headers["content-disposition"],
                         'attachment; filename="openDMT3-win-Setup-dmt.example-443.exe"')
        self.assertEqual(int(got.headers["content-length"]), len(got.content))
        # A program with a version resource: its version too.
        with open(path, "wb") as f:
            f.write(windows_program((1, 2, 3, 0)))
        self.assertIn("Version 1.2.3, 0.0 MB", browser.get("/download").text)
        browser.cookies.set("opendmt3_lang", "ko")
        page = browser.get("/download").text
        self.assertIn("버전 1.2.3", page)
        self.assertIn("openDMT3-win-Setup-dmt.example-443.exe를 실행하세요.", page)

    def test_the_installers_name_keeps_letters_digits_dots_and_dashes_only(self):
        from opendmt3.server.services import downloads
        self.assertEqual(downloads.download_name("dmt.example.org", 4730),
                         "openDMT3-win-Setup-dmt.example.org-4730.exe")
        self.assertEqual(downloads.download_name("::1", 4730), "openDMT3-win-Setup---1-4730.exe")
        self.assertEqual(downloads.download_name("게임.example", 80), "openDMT3-win-Setup---.example-80.exe")
        self.assertEqual(downloads.download_name('a"b/c\\d', 1), "openDMT3-win-Setup-a-b-c-d-1.exe")


class VersionTest(unittest.TestCase):
    """The installer's version from its version resource, and nothing from a file that is not one."""

    def setUp(self):
        import shutil
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def version_of(self, data):
        from opendmt3.server.services import downloads
        path = os.path.join(self.tmp, "x.exe")
        with open(path, "wb") as f:
            f.write(data)
        return downloads.version(path)

    def test_the_version_resource_is_read(self):
        self.assertEqual(self.version_of(windows_program((0, 10, 0, 0))), "0.10.0")
        self.assertEqual(self.version_of(windows_program((1, 0, 0, 114))), "1.0.0.114")
        # The server's end added to the installer it hands out changes nothing.
        self.assertEqual(self.version_of(windows_program((0, 9, 1, 0), tail=b"{}" + b"OPENDMT3-PRESET1")), "0.9.1")

    def test_anything_else_gives_no_version(self):
        good = windows_program((0, 10, 0, 0))
        broken = [b"", b"MZ", b"not a program", good[:0x200], good[:-10],
                  # The fixed part's mark changed; the resource's key changed; the PE mark changed.
                  good.replace(b"\xbd\x04\xef\xfe", b"\0\0\0\0"),
                  good.replace("VS_VERSION_INFO".encode("utf-16-le"), "VS_VERSION_INFX".encode("utf-16-le")),
                  good.replace(b"PE\0\0", b"PX\0\0")]
        for data in broken:
            with self.subTest(size=len(data)):
                self.assertIsNone(self.version_of(data))
        from opendmt3.server.services import downloads
        self.assertIsNone(downloads.version(os.path.join(self.tmp, "missing.exe")))
        self.assertIsNone(downloads.facts(os.path.join(self.tmp, "missing.exe")))


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class FrameTest(SiteBase):
    """Item 11: each page's title, the icon, the menu's aria-current, the language switch's next= and the Licenses
    page."""

    def title(self, page):
        return re.search(r"<title>(.*?)</title>", page, re.S).group(1)

    def test_each_page_has_a_title_of_its_own(self):
        nova = self.admin()
        self.play(nova, 1, 1, 500)
        self.catalog([{"number": 1, "title": "Made-up Song"}])
        for path, title in (("/", "Home · openDMT3"), ("/rankings", "Rankings · openDMT3"),
                            ("/songs", "Songs · openDMT3"), ("/songs/1", "Made-up Song · openDMT3"),
                            ("/dj/%d" % nova["id"], "BOSS · openDMT3"), ("/download", "Download · openDMT3"),
                            ("/account", "My account · openDMT3"), ("/admin/players", "Players · Admin · openDMT3"),
                            ("/admin/log/plays", "Plays · Logs · openDMT3"), ("/nowhere", "Page not found · openDMT3"),
                            ("/licenses", "Licenses · openDMT3")):
            self.assertEqual(self.title(self.client.get(path).text), title, path)
        self.client.cookies.set("opendmt3_lang", "ko")
        self.assertEqual(self.title(self.client.get("/rankings").text), "랭킹 · openDMT3")
        self.client.cookies.clear()
        self.assertEqual(self.title(self.client.get("/signin").text), "Sign in · openDMT3")

    def test_the_icon_is_the_launchers_mark_and_small(self):
        from opendmt3 import __version__
        self.make()
        self.assertIn('<link rel="icon" href="/static/favicon.ico?v=%s"' % __version__, self.client.get("/signin").text)
        # Where browsers look by themselves, without a sign-in.
        r = self.client.get("/favicon.ico", follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["content-type"]), (200, "image/x-icon"))
        self.assertTrue(r.content.startswith(b"\0\0\1\0"))
        self.assertLess(len(r.content), 8 * 1024)

    def test_the_menu_marks_the_page_showing(self):
        self.admin()
        for path, lit in (("/", "/"), ("/rankings", "/rankings"), ("/songs", "/songs"), ("/download", "/download"),
                          ("/admin/status", "/admin/players")):
            menu = self.client.get(path).text.split('<nav class="menu">', 1)[1].split("</nav>", 1)[0]
            self.assertEqual(re.findall(r'<a href="([^"]+)" class="on" aria-current="page">', menu), [lit], path)
            self.assertEqual(menu.count("aria-current"), 1, path)

    def test_the_language_switch_comes_back_to_the_page_and_nowhere_else(self):
        self.make()
        self.sign_in(self.client)
        page = self.client.get("/rankings?mode=1&by=month").text
        self.assertIn('href="/lang/ko?next=/rankings%3Fmode%3D1%26by%3Dmonth"', page)
        r = self.client.get("/lang/ko?next=/rankings%3Fmode%3D1%26by%3Dmonth", follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/rankings?mode=1&by=month"))
        self.assertEqual(self.client.cookies.get("opendmt3_lang"), "ko")
        # Another address, however written, a line break, nothing at all, and the Referer: Home.
        for target in ("//evil.example/x", "/\\evil.example", "https://evil.example/", "evil",
                       "/a\r\nSet-Cookie: x", ""):
            r = self.client.get("/lang/en", params={"next": target} if target else None, follow_redirects=False)
            self.assertEqual(r.headers["location"], "/", repr(target))
        r = self.client.get("/lang/en", headers={"Referer": "http://testserver/songs"}, follow_redirects=False)
        self.assertEqual(r.headers["location"], "/")

    def test_a_line_break_in_next_is_never_followed(self):
        from opendmt3.server.web import common
        self.assertEqual(common._local_path("/a\r\nSet-Cookie: x"), "/")
        self.assertEqual(common._local_path("/\\evil.example"), "/")
        self.assertEqual(common._local_path("//evil.example"), "/")
        self.assertEqual(common._local_path("/songs?q=a b"), "/songs?q=a b")

    def test_the_licenses_page_lists_the_served_fonts_with_their_licences(self):
        self.make()
        # Open to anyone, as the fonts themselves are; linked from every page's foot.
        page = self.client.get("/licenses", follow_redirects=False)
        self.assertEqual(page.status_code, 200)
        self.assertIn('<a href="/licenses" aria-current="page">Licenses</a>', page.text)
        self.assertIn('<a href="/licenses">Licenses</a>', self.client.get("/signin").text)
        for words in ("DMT3 Wide, the titles&#39; face: made from Saira", "DMT3 Text, the text face: made from "
                      "Pretendard 1.3.9", "Pretendard, the launcher&#39;s text face", "Copyright 2020 The Saira "
                      "Project Authors", "Copyright (c) 2021, Kil Hyung-jin", "SIL OPEN FONT LICENSE Version 1.1"):
            self.assertIn(words, page.text)
        self.client.cookies.set("opendmt3_lang", "ko")
        self.assertIn("DMT3 Wide(제목 글꼴): Saira를 가장 넓고 굵게", self.client.get("/licenses").text)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class SignInPageTest(SiteBase):
    """Item 12: the sign-in page keeps the ID after a wrong password, says its errors as alerts, and says when it
    cannot work at all."""

    def test_a_wrong_password_keeps_the_id_but_never_the_password(self):
        self.make()
        page = self.sign_in(self.client, password="wrongpass1").text
        self.assertIn('<p class="alert bad" role="alert">That ID and password do not match an account.</p>', page)
        self.assertIn('<input name="login_id" value="NOVA"', page)
        self.assertNotIn("wrongpass1", page)
        # The password box takes the focus, the ID being typed already.
        self.assertRegex(page, r'<input name="password" type="password" [^>]*autofocus>')
        self.assertNotRegex(page, r'<input name="login_id"[^>]*autofocus')

    def test_sign_in_is_not_available_while_the_database_cannot_be_opened(self):
        self.make()
        token = self.signin_token(self.client)
        with open(self.site.db_path, "wb") as f:
            f.write(b"this is no database " * 100)
        page = self.client.get("/signin")
        self.assertEqual(page.status_code, 503)
        self.assertIn('role="alert">Sign-in is not available right now. Try again in a while.</p>', page.text)
        r = self.client.post("/signin", data={"csrf": token, "login_id": "NOVA", "password": "pass1234"})
        self.assertEqual(r.status_code, 503)
        self.assertIn('value="NOVA"', r.text)
        self.client.cookies.set("opendmt3_lang", "ko")
        self.assertIn("지금은 로그인할 수 없습니다.", self.client.get("/signin").text)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class QualityTest(SiteBase):
    """Item 13: health, failures, caching, bounded lists, the sign-in log, robots.txt and compression."""

    def break_database(self):
        with open(self.site.db_path, "wb") as f:
            f.write(b"this is no database " * 100)

    def test_health_is_checked_once_in_its_seconds_however_often_asked(self):
        # A stream of asks takes the database's write lock once in HEALTH_KEPT seconds at most.
        from unittest import mock
        from opendmt3.server import db
        from opendmt3.server.web import app as web_app
        self.make()
        opened = []
        real = db.connect

        def counted(path, *args, **kwargs):
            opened.append(path)
            return real(path, *args, **kwargs)
        with mock.patch.object(db, "connect", counted), mock.patch.object(web_app, "HEALTH_KEPT", 60.0):
            answers = {self.client.get("/health").status_code for _ in range(50)}
        self.assertEqual((answers, len(opened)), ({200}, 1))

    def test_health_answers_503_when_the_database_cannot_be_opened_or_written(self):
        from unittest import mock
        from opendmt3 import __version__
        from opendmt3.server import db
        from opendmt3.server.web import app as web_app
        # Every ask checked here (the answer is kept a moment otherwise).
        patch = mock.patch.object(web_app, "HEALTH_KEPT", 0.0)
        patch.start()
        self.addCleanup(patch.stop)
        self.make()
        self.assertEqual(self.client.get("/health").json(), {"ok": True, "version": __version__})
        real = db.connect

        class NoWrites:
            """A connection whose writes are refused, as on a read-only disk."""

            def __init__(self, path):
                self.connection = real(path)

            def execute(self, sql, *args):
                if sql.startswith("BEGIN"):
                    import sqlite3
                    raise sqlite3.OperationalError("attempt to write a readonly database")
                return self.connection.execute(sql, *args)

            def close(self):
                self.connection.close()

        with mock.patch.object(db, "connect", NoWrites):
            r = self.client.get("/health")
        self.assertEqual((r.status_code, r.json()), (503, {"ok": False, "version": __version__,
                                                           "reason": "the database cannot be written"}))
        self.break_database()
        r = self.client.get("/health")
        self.assertEqual((r.status_code, r.json()["reason"]), (503, "the database cannot be opened"))

    def test_a_failing_page_answers_503_in_the_sites_look_and_the_api_json_500(self):
        from unittest import mock
        from opendmt3.server.web import api, pages
        self.make()
        self.sign_in(self.client)
        token = self.client.post("/api/v1/session", json={"login_id": "NOVA", "password": "pass1234"}).json()["token"]
        with mock.patch.object(pages, "_songs", side_effect=RuntimeError("a made-up failure")), \
                self.assertLogs("opendmt3.web", "ERROR") as logged:
            page = self.client.get("/songs")
        self.assertEqual(page.status_code, 503)
        self.assertIn("<title>Not available right now · openDMT3</title>", page.text)
        self.assertIn('<span class="m">DMT<b>3</b></span>', page.text)
        self.assertIn("This page cannot be shown right now. Try again in a while.", page.text)
        self.assertEqual(page.headers["cache-control"], "private, no-store")
        # Logged with its traceback.
        self.assertIn("GET /songs failed", logged.output[0])
        self.assertIn("RuntimeError: a made-up failure", logged.output[0])
        with mock.patch.object(api, "_songs", side_effect=RuntimeError("a made-up failure")), \
                self.assertLogs("opendmt3.web", "ERROR"):
            r = self.client.get("/api/v1/songs", headers={"Authorization": "Bearer " + token})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (500, "server_error"))
        # The server goes on: the next page is fine.
        self.assertEqual(self.client.get("/songs").status_code, 200)

    def test_a_database_that_cannot_be_read_answers_503_pages_not_errors(self):
        self.make()
        self.sign_in(self.client)
        self.break_database()
        with self.assertLogs("opendmt3.web", "ERROR"):
            page = self.client.get("/rankings")
        self.assertEqual(page.status_code, 503)
        self.assertIn("Not available right now", page.text)

    def test_pages_are_never_kept_but_files_are(self):
        from opendmt3 import __version__
        self.make()
        self.sign_in(self.client)
        for path in ("/", "/songs", "/nowhere", "/signin", "/licenses"):
            r = self.client.get(path)
            self.assertEqual((r.headers["cache-control"], "Cookie" in r.headers["vary"]),
                             ("private, no-store", True), path)
        # Static files asked for with this version: a year, never asked again; without it, as before.
        for path in ("/static/site.css", "/static/site.js", "/static/favicon.ico", "/fonts/DMT3Wide-Regular.ttf",
                     "/static/fonts/dmt3-text.woff2"):
            r = self.client.get(path + "?v=" + __version__)
            self.assertEqual(r.headers["cache-control"], "public, max-age=31536000, immutable", path)
            self.assertNotIn("cache-control", self.client.get(path).headers, path)
            self.assertNotIn("cache-control", self.client.get(path + "?v=0.0.1").headers, path)
        # Every static address a page asks for carries the version.
        page = self.client.get("/").text
        for address in re.findall(r'(?:href|src)="(/(?:static|fonts)/[^"]+)"|url\("(/[^"]+)"\)', page):
            address = address[0] or address[1]
            self.assertTrue(address.endswith("?v=" + __version__), address)

    def test_boards_and_logs_say_when_they_stop_short(self):
        import collections
        from unittest import mock
        from opendmt3.server import db
        from opendmt3.server.web import pages
        boss = self.admin()
        for n in range(3):
            self.play(self.make("P%d" % n, dj="DJ%d" % n), 1, 1, 100 + n)
        self.play(boss, 1, 1, 1)
        with mock.patch.object(pages, "RANKING_SHOWN", 2):
            page = self.client.get("/songs/1").text
        self.assertEqual(page.split('<table class="table board">', 1)[1].split("</table>", 1)[0].count("<tr class="),
                         2)
        self.assertIn("Top 2 of 4", page)
        # The change log: the newest 100 of all of them; the game's messages: the newest 200 of those kept.
        connection = db.connect(self.site.db_path)
        connection.executemany("INSERT INTO changes (at, who, what) VALUES (?, 'x', 'y')", [(n,) for n in range(110)])
        connection.close()
        messages = collections.deque(({"at": n, "cabinet": "c", "name": "m", "size": 1, "handled": True,
                                       "bytes": ""} for n in range(250)), maxlen=500)
        # The site reads them through the game server's own copies (GameServer.live and received, under its lock).
        from opendmt3.server.server import GameServer
        self.site.game_server = type("Game", (), {"connections": set(), "messages": messages, "started": 0,
                                                  "lock": threading.Lock(), "live": GameServer.live,
                                                  "received": GameServer.received})()
        page = self.client.get("/admin/log").text
        self.assertIn("The latest 100 of 114", page)
        self.assertIn("The latest 200 of 250", page)

    def test_a_wrong_password_is_logged_with_the_address_and_id_never_the_password(self):
        self.make()
        with self.assertLogs("opendmt3.web", "WARNING") as logged:
            self.sign_in(self.client, "NOVA\nforged line", "wrongpass1")
        self.assertEqual(logged.output, ["WARNING:opendmt3.web:a wrong password for the ID 'NOVA\\nforged line' "
                                         "from 203.0.113.5 (/signin)"])
        self.assertNotIn("wrongpass1", "".join(logged.output))

    def test_robots_and_the_icon_answer_without_a_sign_in(self):
        self.make()
        r = self.client.get("/robots.txt", follow_redirects=False)
        self.assertEqual((r.status_code, r.text), (200, "User-agent: *\nDisallow: /\n"))
        self.assertTrue(r.headers["content-type"].startswith("text/plain"))
        self.assertEqual(self.client.get("/favicon.ico", follow_redirects=False).status_code, 200)

    def test_text_answers_are_compressed_and_files_keep_their_lengths(self):
        import json
        from opendmt3.server.services import backups
        boss = self.admin()
        gz = {"Accept-Encoding": "gzip"}
        # A page, the stylesheet and a JSON answer over 1 KB: compressed, told apart by what the browser takes.
        for path in ("/", "/static/site.css", "/static/site.js"):
            r = self.client.get(path, headers=gz)
            self.assertEqual(r.headers.get("content-encoding"), "gzip", path)
            self.assertIn("Accept-Encoding", r.headers["vary"], path)
            plain = self.client.get(path, headers={"Accept-Encoding": "identity"})
            self.assertNotIn("content-encoding", plain.headers, path)
            self.assertEqual(r.content, plain.content, path)
        self.assertIn("Cookie", self.client.get("/", headers=gz).headers["vary"])
        token = self.client.post("/api/v1/session", json={"login_id": "BOSS", "password": "pass1234"}).json()["token"]
        for n in range(30):
            self.play(boss, 1 + n, 1, 1000 + n)
        r = self.client.get("/api/v1/djs/%d" % boss["id"], headers=dict(gz, Authorization="Bearer " + token))
        self.assertEqual(r.headers.get("content-encoding"), "gzip")
        # The length said is the compressed one, as it came over the wire; the JSON reads back whole.
        self.assertEqual(int(r.headers["content-length"]), r.num_bytes_downloaded)
        self.assertLess(r.num_bytes_downloaded, len(r.content))
        self.assertEqual(len(r.json()["bests"]), 30)
        # A small answer is not worth it.
        self.assertNotIn("content-encoding", self.client.get("/health", headers=gz).headers)
        # The installer: as kept, its length right, whatever the browser takes.
        os.makedirs(self.site.downloads)
        with open(os.path.join(self.site.downloads, "openDMT3-win-Setup.exe"), "wb") as f:
            f.write(b"MZ" + b"\0" * 50000)
        r = self.client.get("/download/windows", headers=gz)
        self.assertNotIn("content-encoding", r.headers)
        self.assertEqual(int(r.headers["content-length"]), len(r.content))
        # The update feed's JSON (Velopack reads it as kept), a backup and a picture: never compressed.
        os.makedirs(os.path.join(self.tmp, "updates"))
        with open(os.path.join(self.tmp, "updates", "releases.win.json"), "w") as f:
            json.dump({"Assets": [{"Name": "x" * 40}] * 100}, f)
        r = self.client.get("/updates/releases.win.json", headers=gz)
        self.assertNotIn("content-encoding", r.headers)
        name = backups.make(self.site.db_path, self.tmp, "manual")
        self.assertNotIn("content-encoding", self.client.get("/admin/backups/" + name, headers=gz).headers)
        os.makedirs(os.path.join(self.tmp, "jackets"))
        with open(os.path.join(self.tmp, "jackets", "1.png"), "wb") as f:
            f.write(b"\x89PNG" + bytes(5000))
        self.assertNotIn("content-encoding", self.client.get("/jackets/1.png", headers=gz).headers)
        self.assertNotIn("content-encoding", self.client.get("/admin/log/plays.csv", headers=gz).headers)


class WordsTest(unittest.TestCase):
    """The site's words (strings.py): each in English and Korean with the same gaps, none with a long dash."""

    def test_every_site_word_has_korean_with_the_same_gaps(self):
        import string
        from opendmt3.server.web import strings

        def gaps(text):
            return {field for _, field, _, _ in string.Formatter().parse(text) if field is not None}

        # The table has some 290 words; one that stopped being read would pass with none.
        self.assertGreater(len(strings.TEXT), 250)
        for key, (english, korean) in strings.TEXT.items():
            with self.subTest(key=key):
                self.assertTrue(english and korean)
                self.assertEqual(gaps(english), gaps(korean))
                self.assertNotIn("—", english + korean)


class NewRecordsSqlTest(unittest.TestCase):
    """records.new_records() against a plain computation of every play, by both of its ways (checking the newest
    plays, and the bound from each chart's best), on made-up histories."""

    def setUp(self):
        import shutil
        import tempfile
        from opendmt3.server import db
        from opendmt3.server.services import accounts, records
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.connection = db.connect(os.path.join(self.tmp, "openDMT3.sqlite"))
        self.addCleanup(self.connection.close)
        self.store = records.Records(self.connection)
        accounts_ = accounts.Accounts(self.connection)
        self.ids = [accounts_.create("P%d" % n, "pass1234", "DJ%d" % n)["id"] for n in range(6)]
        # One player disabled: their records are left out.
        accounts_.set_disabled("P5", True)

    def fill(self, seed, plays, charts):
        """`plays` plays over `charts` charts per player, at times out of order with the ids (as a restored or
        imported history may be), some at the same second."""
        rng = random.Random(seed)
        self.connection.execute("BEGIN")
        for _ in range(plays):
            chart = rng.randrange(charts)
            self.store.add(rng.choice(self.ids), "x", chart % 2, {"song": 1 + chart // 6, "pattern": 1 + chart % 3,
                                                                  "score": rng.randrange(50), "counts": [0] * 7,
                                                                  "raw": bytes(47)}, at=1000 + rng.randrange(400))
        self.connection.execute("COMMIT")

    def plain(self, limit):
        """Every play weighed against the same player's earlier plays of its chart, in Python: (id, before)."""
        enabled = {r[0] for r in self.connection.execute("SELECT id FROM accounts WHERE disabled = 0")}
        rows = sorted(self.connection.execute("SELECT * FROM plays"), key=lambda r: (r["played_at"], r["id"]))
        best, found = {}, []
        for r in rows:
            key = (r["account_id"], r["mode"], r["song"], r["pattern"])
            if key in best and r["score"] > best[key] and r["account_id"] in enabled:
                found.append((r["id"], best[key]))
            best[key] = max(best.get(key, r["score"]), r["score"])
        order = {r["id"]: (r["played_at"], r["id"]) for r in rows}
        return sorted(found, key=lambda f: order[f[0]], reverse=True)[:limit]

    def test_both_ways_give_the_plain_answer(self):
        from unittest import mock
        from opendmt3.server.services import records
        for seed, plays, charts in ((1, 400, 30), (2, 300, 200), (3, 200, 400), (4, 600, 12)):
            self.connection.execute("DELETE FROM plays")
            self.fill(seed, plays, charts)
            for limit in (1, 3, 10, 40):
                expected = self.plain(limit)
                with self.subTest(seed=seed, limit=limit):
                    self.assertEqual([(r["id"], r["before"]) for r in self.store.new_records(limit)], expected)
                    self.assertEqual([(r["id"], r["before"]) for r in self.store.records_by_chart(limit)], expected)
                    # Checking only the newest four plays before the bound: the bound answers, the same.
                    with mock.patch.object(records.Records, "CHECKED_FIRST", 4), \
                            mock.patch.object(records.Records, "CHECKED_MOST", 4):
                        self.assertEqual([(r["id"], r["before"]) for r in self.store.new_records(limit)], expected)

    def test_the_modes_played_match_a_plain_read(self):
        self.fill(6, 300, 40)
        # One mode only a disabled player played, and one far above the rest.
        self.store.add(self.ids[5], "x", 7, {"song": 1, "pattern": 1, "score": 1, "counts": [0] * 7, "raw": bytes(47)})
        self.store.add(self.ids[0], "x", 200, {"song": 1, "pattern": 1, "score": 1, "counts": [0] * 7,
                                               "raw": bytes(47)})
        plain = [r[0] for r in self.connection.execute(
            "SELECT DISTINCT p.mode FROM plays AS p JOIN accounts AS a ON a.id = p.account_id WHERE a.disabled = 0"
            " ORDER BY p.mode")]
        self.assertEqual(self.store.modes(), plain)
        self.assertEqual(plain, [0, 1, 200])

    def test_the_newest_plays_come_from_the_index_and_match_a_plain_sort(self):
        self.fill(5, 500, 50)
        enabled = {r[0] for r in self.connection.execute("SELECT id FROM accounts WHERE disabled = 0")}
        rows = sorted((r for r in self.connection.execute("SELECT * FROM plays") if r["account_id"] in enabled),
                      key=lambda r: (r["played_at"], r["id"]), reverse=True)
        self.assertEqual([r["id"] for r in self.store.recent(None, 15)], [r["id"] for r in rows[:15]])
        self.assertEqual(self.store.count(), len(rows))
        # One player's own, with the best before each.
        mine = [r for r in rows if r["account_id"] == self.ids[0]][:7]
        got = self.store.recent(self.ids[0], 7, before=True)
        self.assertEqual([r["id"] for r in got], [r["id"] for r in mine])
        for r in got:
            earlier = [e["score"] for e in self.connection.execute(
                "SELECT score, played_at, id FROM plays WHERE account_id = ? AND mode = ? AND song = ? AND pattern = ?",
                (r["account_id"], r["mode"], r["song"], r["pattern"]))
                if (e["played_at"], e["id"]) < (r["played_at"], r["id"])]
            self.assertEqual(r["before"], max(earlier) if earlier else None)
        # Only after a moment, as the launcher asks for a session's plays.
        since = [r for r in rows if r["account_id"] == self.ids[1] and r["played_at"] >= 1300]
        self.assertEqual([r["id"] for r in self.store.recent(self.ids[1], 500, since=1300)], [r["id"] for r in since])


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class StatesTest(SiteBase):
    """The pages in the states a first walk through the site meets (the words and screens review): each line true in
    the state it is shown in, and each change asked first that takes something away."""

    def api(self, method, path):
        """A call of the API as BOSS, with a token of the sign-in's own."""
        token = self.client.post("/api/v1/session", json={"login_id": "BOSS", "password": "pass1234"}).json()["token"]
        return self.client.request(method, path, headers={"Authorization": "Bearer " + token})

    def test_the_download_page_without_an_installer_says_where_the_launcher_comes_from(self):
        from starlette.testclient import TestClient
        self.make()
        browser = TestClient(self.app, base_url="http://192.168.0.5:4730", client=("192.168.0.9", 50000))
        self.sign_in(browser)
        page = browser.get("/download").text
        self.assertIn("This server has no installer to hand out.", page)
        # No file of this server's to run, and no launcher that knows this server: the release's file, and the
        # address typed by hand.
        self.assertIn("Get openDMT3-win-Setup.exe from the project&#39;s releases and run it.", page)
        self.assertIn("choose Another server, type the address (192.168.0.5:4730) and press Connect.", page)
        self.assertNotIn("openDMT3-win-Setup-192.168.0.5-4730.exe", page)
        self.assertNotIn("opens on this server", page)
        browser.cookies.set("opendmt3_lang", "ko")
        page = browser.get("/download").text
        self.assertIn("프로젝트 릴리스에서 openDMT3-win-Setup.exe를 받아 실행하세요.", page)
        self.assertIn("&#39;다른 서버&#39;를 고르고 주소(192.168.0.5:4730)를 입력한 뒤 &#39;연결&#39;을 누르세요.", page)

    def test_the_first_run_page_names_the_rules_and_the_sign_in_page_says_the_account_was_made(self):
        page = self.local.get("/owner").text
        # The rules before one is broken.
        self.assertIn("ID: up to 8 letters and digits. DJ name: up to 8 characters, shown in the game. Password: 6 "
                      "to 16 letters and digits.", page)
        token = page.split('name="csrf" value="', 1)[1].split('"', 1)[0]
        made = self.local.post("/owner", data={"csrf": token, "login_id": "boss", "password": "pass1234"})
        # The sign-in page that opens next says so once, with the ID typed already.
        self.assertIn('<p class="alert ok" role="status">Made BOSS. Sign in with it.</p>', made.text)
        self.assertIn('name="login_id" value="BOSS"', made.text)
        self.assertNotIn("Made BOSS", self.local.get("/signin").text)
        # Only this site's own first-run page says it: a cookie that is no ID says nothing, and another visitor
        # is told nothing about an account.
        self.local.cookies.set("opendmt3_made", "<b>BOSS</b> and more")
        self.assertNotIn("Made ", self.local.get("/signin").text)
        self.assertNotIn("Made ", self.client.get("/signin").text)

    def test_a_new_password_is_asked_first_as_a_reset_and_a_delete_are(self):
        self.admin()
        self.make()
        page = self.client.get("/admin/players").text
        form = re.search(r'<form method="post" data-ask="Give NOVA a new password\?"[^>]*>', page)
        self.assertIsNotNone(form)
        self.assertIn('data-ask-detail="Their sign-ins end. The new password is shown once."', form.group(0))
        self.assertIn('data-ask-yes="New password"', form.group(0))
        # Every form that changes an account's sign-in or takes plays away asks (enable and admin rights do not).
        self.assertEqual(len(re.findall(r'<form method="post" data-ask="[^"]*"[^>]*><input type="hidden" name="csrf" '
                                        r'value="[^"]*"><input type="hidden" name="action" value="password">', page)), 2)

    def test_the_installers_line_names_the_command_where_the_folder_is_out_of_reach(self):
        from unittest import mock
        from opendmt3.server.services import sources
        self.admin()
        with mock.patch.object(sources, "in_container", return_value=True):
            page = self.client.get("/admin/status").text
            twin = self.api("GET", "/api/v1/server").json()["look"]
        # In Docker the downloads folder is inside the server's volume: the command, never that folder.
        self.assertIn("No installer to hand out on the Download page. On the server PC: ./dmt3 setup --installer "
                      "FILE</p>", page)
        self.assertNotIn(self.site.downloads, page)
        line = next(item for item in twin if item["key"] == "installer")
        self.assertTrue(line["text"].endswith("./dmt3 setup --installer FILE"))

    def test_the_status_page_says_what_a_reading_left_out_only_after_a_reading(self):
        import json
        self.admin()
        page = self.client.get("/admin/status").text
        self.assertNotIn("data-missing", page)
        # A reading that found no jackets and no DJ cards: each said once, with its reason.
        with open(os.path.join(self.tmp, "catalog-read.json"), "w") as f:
            json.dump({"at": 1000, "from": "folder", "path": "/games/made-up", "folder": "/games/made-up", "songs": 1,
                       "jackets": None, "cards": None, "missing": {"jackets": "The game's files have no jackets."},
                       "reasons": {"jackets": "error.game.no_jackets"}}, f)
        self.catalog([{"number": 1, "title": "Made-up Song"}])
        page = self.client.get("/admin/status").text
        self.assertEqual(len(re.findall(r'class="alert look data-missing"', page)), 2)
        self.assertIn("No jackets: songs show without them. The game&#39;s files have no jackets.", page)
        self.assertIn("No DJ cards:", page)

    def test_the_change_log_is_worded_in_the_readers_language_when_shown(self):
        from opendmt3.server.web import strings
        self.admin()
        self.make()
        token = self.form_token(self.client, "/admin/status")
        self.client.post("/admin/status", data={"csrf": token, "action": "maintenance_on"})
        self.assertIn("<td data-label=\"What\">started maintenance</td>", self.client.get("/admin/log").text)
        self.client.cookies.set("opendmt3_lang", "ko")
        page = self.client.get("/admin/log").text
        self.assertIn("점검을 시작했습니다", page)
        self.assertIn("NOVA 계정을 만들었습니다", page)
        self.assertNotIn("started maintenance", page)
        # The API's twin keeps the line as the server wrote it.
        self.assertIn("started maintenance", [c["what"] for c in self.api("GET", "/api/v1/log").json()["changes"]])
        # Every line the server writes has its shape here (the list is the server's own calls, by hand: the count
        # below fails when one is added without its words), with its values carried over.
        lines = {
            "made the account NOVA": "NOVA 계정을 만들었습니다",
            "set a new password (and card) for NOVA": "NOVA의 비밀번호와 카드를 새로 만들었습니다",
            "named NOVA DJ NOVA 2": "NOVA의 DJ 이름을 바꿨습니다: DJ NOVA 2",
            "changed the DJ card of NOVA (comment, icon, pattern, plate)":
                "NOVA의 DJ 카드를 바꿨습니다(코멘트, 아이콘, 플레이트 패턴, 플레이트)",
            "gave admin rights to RIO": "RIO에게 관리자 권한을 주었습니다",
            "took admin rights from RIO": "RIO의 관리자 권한을 뺐습니다",
            "disabled the account RIO": "RIO 계정을 비활성화했습니다",
            "enabled the account RIO": "RIO 계정을 활성화했습니다",
            "deleted the account RIO": "RIO 계정을 삭제했습니다",
            "set the notice: Sunday: backup": "공지를 올렸습니다: Sunday: backup",
            "cleared the notice": "공지를 내렸습니다",
            "started maintenance": "점검을 시작했습니다",
            "ended maintenance": "점검을 끝냈습니다",
            "deleted the backup a.sqlite": "백업을 삭제했습니다: a.sqlite",
            "reset the plays of NOVA: 14 gone, backed up as b.sqlite":
                "NOVA의 플레이 기록을 초기화했습니다. 클리어한 스테이지 14개를 지우고 백업해 두었습니다: b.sqlite",
            "reset every play: 120 gone, backed up as c.sqlite":
                "모든 플레이 기록을 초기화했습니다. 클리어한 스테이지 120개를 지우고 백업해 두었습니다: c.sqlite",
            "made the API token nightly (write) for BOSS": "BOSS의 API 토큰을 만들었습니다: nightly (write)",
            "revoked the API token nightly of BOSS": "BOSS의 API 토큰을 폐기했습니다: nightly",
            "named cabinet 2 'Left one'": "기체 2의 이름을 바꿨습니다: 'Left one'",
            "backed up the database as a.sqlite": "데이터베이스를 백업했습니다: a.sqlite",
            "restored the database from a.sqlite": "데이터베이스를 복원했습니다: a.sqlite",
            "uploaded a backup as u.sqlite (4096 bytes)": "백업을 올렸습니다: u.sqlite(4096바이트)",
            "imported the song list from /games/t3: 177 songs, nothing missing":
                "곡 목록을 가져왔습니다: /games/t3, 곡 177개, 빠진 것 없음",
            "imported the song list from an uploaded song list (list.zip): 5 songs, jackets missing, cards missing":
                "곡 목록을 가져왔습니다: 올린 곡 목록(list.zip), 곡 5개, 자켓 없음, DJ 카드 없음",
        }
        for kept, shown in lines.items():
            self.assertEqual(strings.changed("ko", kept), shown)
            self.assertEqual(strings.changed("en", kept), kept)
        # A line from elsewhere (another version's) is shown as it was kept.
        self.assertEqual(strings.changed("ko", "did something new"), "did something new")
        # The server's calls that write a line: each must be among the shapes above.
        package = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, "opendmt3", "server")
        calls = 0
        for folder, _, names in os.walk(package):
            for name in names:
                if name.endswith(".py"):
                    with open(os.path.join(folder, name), encoding="utf-8") as f:
                        calls += len(re.findall(r"(?<!def )\b_log_change\(|self\._log\(", f.read()))
        self.assertEqual(calls, 19, "a line was added to (or taken from) the change log: give it its words in "
                                    "strings.py (log.change.*) and its line in this test")

    def test_home_puts_the_way_to_play_beside_the_dj(self):
        self.make()
        self.sign_in(self.client)
        page = self.client.get("/").text
        # Your DJ, then Play on your PC (with the page's own words on its button), before the lists.
        order = [page.index(words) for words in ("<h3>Your DJ</h3>", "<h3>Play on your PC</h3>",
                                                 "<h3>Connected cabinets</h3>", "<h3>New records</h3>")]
        self.assertEqual(order, sorted(order))
        self.assertIn('<a class="btn primary" href="/download">Get the launcher</a>', page)

    def test_a_caller_past_their_share_is_told_when_to_try_again_and_nothing_else(self):
        from opendmt3.server.web import strings
        en, ko = strings.words("en"), strings.words("ko")
        # No word about the caller: the page's title says what it is, the line when to come back.
        self.assertEqual(en("error.busy.text", seconds=5), "Try again in 5 seconds.")
        self.assertEqual(en("error.busy.text.one"), "Try again in 1 second.")
        self.assertEqual(ko("error.busy.text", seconds=5), "5초 뒤에 다시 시도하세요.")
        html = self.site.templates.get_template("error.html").render(
            w=en, lang="en", user=None, version="0", path="/", here="/", csrf="", busy=1, unavailable=False)
        self.assertIn("Try again in 1 second.", html)
        self.assertNotIn("1 seconds", html)


if __name__ == "__main__":
    unittest.main()
