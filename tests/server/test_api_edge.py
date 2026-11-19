"""Tests for the API's edge, from the final review of the API as a service (the 0.4.0 release candidate): each value a
call keeps is of its JSON kind or refused in words with its field named (a switch true or false, text a string, a
number a number), a body no program sends (nested past any depth, too large) is a JSON error and never a failure, a
long job's quick answer is its id, paging values that cannot be read are refused, a read-only token signs itself out,
the ban's sentence names its reason for an older launcher, and the small answers the review found apart from the rest.

They need the web libraries (Starlette, Jinja2, httpx for the test client); without them they are skipped.
"""

import logging
import os
import time
import unittest

from tests.server.test_api import ApiBase
from tests.server.test_web import WEB


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class KindsTest(ApiBase):
    """Each value a call keeps is of its JSON kind, or 400 bad_request with the field named; nothing is made of
    another kind's value (str() of null was "None", bool() of "false" was an admin)."""

    def setUp(self):
        super().setUp()
        self.make("BOSS", dj="BOSS", admin=True)
        self.admin_token = self.token("BOSS")

    def bad(self, method, path, body, field, token=None):
        """The call refused as a bad request whose message names the field."""
        r = self.call(method, path, token or self.admin_token, json=body)
        self.refused(r, 400, "bad_request")
        self.assertIn(field, r.json()["error"]["message"], (path, body))
        return r

    def test_a_switch_is_true_or_false_alone(self):
        # The review's: "false" and "no" made admins. Text, numbers and null are no switch, whatever they say.
        for value in ("false", "no", 0, 1, None, "true"):
            with self.subTest(value=value):
                self.bad("POST", "/api/v1/players", {"login_id": "TMP4", "is_admin": value}, "is_admin")
        # None of them made the account.
        self.assertIsNone(self.site.accounts().by_login("TMP4"))
        # JSON's own false and true: a player and an admin.
        made = self.call("POST", "/api/v1/players", self.admin_token, json={"login_id": "TMP4", "is_admin": False})
        self.assertEqual((made.status_code, made.json()["is_admin"]), (201, False))
        made = self.call("POST", "/api/v1/players", self.admin_token, json={"login_id": "TMP5", "is_admin": True})
        self.assertEqual((made.status_code, made.json()["is_admin"]), (201, True))
        # Without it: no admin rights.
        made = self.call("POST", "/api/v1/players", self.admin_token, json={"login_id": "TMP6"})
        self.assertEqual(made.json()["is_admin"], False)

    def test_text_is_a_string_alone(self):
        self.make()
        player = self.token()
        # The review's: a name became "None" or "123", a reason "['x']", a password the text of a number.
        self.bad("POST", "/api/v1/me/dj_name", {"dj_name": None}, "dj_name", player)
        self.bad("POST", "/api/v1/me/dj_name", {"dj_name": 123}, "dj_name", player)
        self.bad("POST", "/api/v1/players/NOVA/dj_name", {"dj_name": None}, "dj_name")
        self.bad("POST", "/api/v1/players/NOVA/ban", {"reason": ["x"]}, "reason")
        self.bad("POST", "/api/v1/players", {"login_id": "TMP7", "password": 12345678}, "password")
        self.bad("POST", "/api/v1/players", {"login_id": 7}, "login_id")
        self.bad("POST", "/api/v1/players", {"login_id": "TMP7", "dj_name": 5}, "dj_name")
        self.bad("POST", "/api/v1/me/password", {"password": 1234, "new_password": "fresh567"}, "password", player)
        self.bad("POST", "/api/v1/me/password", {"password": "pass1234", "new_password": 12345678}, "new_password",
                 player)
        self.bad("POST", "/api/v1/tokens", {"name": 5, "scope": "read"}, "name", player)
        self.bad("POST", "/api/v1/tokens", {"name": "bot", "scope": True}, "scope", player)
        self.bad("POST", "/api/v1/me/dj_card", {"comment": 5}, "comment", player)
        # The sign-in's own, before any password is checked (and so never counted as a wrong one).
        for body, field in (({"login_id": 5, "password": "pass1234"}, "login_id"),
                            ({"login_id": "NOVA", "password": None}, "password")):
            r = self.client.post("/api/v1/session", json=body)
            self.refused(r, 400, "bad_request")
            self.assertIn(field, r.json()["error"]["message"])
        # Nothing of them was kept.
        row = self.site.accounts().by_login("NOVA")
        self.assertEqual((row["dj_name"], row["disabled"]), ("DJ NOVA", 0))
        self.assertIsNone(self.site.accounts().by_login("TMP7"))

    def test_a_number_is_a_json_number_alone_and_one_change_at_a_time(self):
        self.make()
        # Text of digits, a fraction and true were read as numbers (or refused as a rule's); a level left out too.
        for path, body, field in (("/api/v1/players/NOVA/max_points", {"amount": "5"}, "amount"),
                                  ("/api/v1/players/NOVA/max_points", {"add": "5"}, "add"),
                                  ("/api/v1/players/NOVA/max_points", {"amount": 1.5}, "amount"),
                                  ("/api/v1/players/NOVA/max_points", {"amount": True}, "amount"),
                                  ("/api/v1/players/NOVA/level", {"level": "7"}, "level"),
                                  ("/api/v1/players/NOVA/level", {}, "level"),
                                  ("/api/v1/players/max_points", {"add": "5"}, "add"),
                                  ("/api/v1/players/NOVA/dj_card", {"icon": "6"}, "icon")):
            with self.subTest(path=path, body=body):
                self.bad("POST", path, body, field)
        # One of amount, add and unlimited, as the guide says: two at once are refused, nothing applied.
        self.bad("POST", "/api/v1/players/NOVA/max_points", {"amount": 1, "add": 2}, "one of")
        self.bad("POST", "/api/v1/players/NOVA/max_points", {"add": 2, "unlimited": True}, "one of")
        row = self.site.accounts().by_login("NOVA")
        self.assertEqual((row["max_points"], row["unlimited_points"]), (0, 0))
        # A JSON number alone is taken.
        r = self.call("POST", "/api/v1/players/NOVA/max_points", self.admin_token, json={"amount": 5})
        self.assertEqual((r.status_code, r.json()["max_points"]), (200, 5))

    def test_a_cabinets_name_past_its_length_is_refused_in_words(self):
        from opendmt3.server import db
        from opendmt3.server.services import activity
        connection = db.connect(self.site.db_path)
        try:
            # A cabinet the game server has seen, by its address.
            act = activity.Activity(connection)
            act.seen("198.51.100.7", "test", "198.51.100.7:5000")
            cabinet = act.cabinets()[0]["id"]
        finally:
            connection.close()
        path = "/api/v1/cabinets/%d/name" % cabinet
        # One past the page's field: said in words, where it was cut to 32 in silence.
        r = self.call("POST", path, self.admin_token, json={"name": "x" * 33})
        self.refused(r, 400, "refused")
        self.assertEqual(r.json()["error"]["message"], "a cabinet's name is up to 32 characters")
        self.bad("POST", path, {"name": 5}, "name")
        # The longest the page takes is taken.
        self.assertEqual(self.call("POST", path, self.admin_token, json={"name": "x" * 32}).status_code, 200)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class BodiesTest(ApiBase):
    """A body no program sends: answered as a bad request in JSON, never a failure with a traceback for each."""

    def test_json_nested_past_any_depth_is_a_bad_request_with_nothing_logged(self):
        self.make("BOSS", dj="BOSS", admin=True)
        boss = self.token("BOSS")
        # Past the decoder's depth, within the site's 64 KB.
        deep = "[" * 30000 + "]" * 30000
        # Nothing for the log: no traceback for each such body.
        with self.assertNoLogs("opendmt3", level=logging.ERROR):
            # The review's: anonymous, the sign-in.
            r = self.client.post("/api/v1/session", content=deep, headers={"Content-Type": "application/json"})
            self.refused(r, 400, "bad_request")
            # A signed-in change, through the same reader.
            r = self.call("POST", "/api/v1/me/dj_name", boss, content=deep,
                          headers={"Content-Type": "application/json"})
            self.refused(r, 400, "bad_request")
            # The song list's import, which reads its small JSON body itself (it also takes files).
            nested = '{"path": ' + "[" * 30000 + "]" * 30000 + "}"
            r = self.call("POST", "/api/v1/server/song_list", boss, content=nested,
                          headers={"Content-Type": "application/json"})
            self.refused(r, 400, "bad_request")

    def test_a_body_json_reads_is_read_as_before(self):
        # UTF-8 with a byte order mark (a file saved by an older Notepad, sent with curl --data @file): read as
        # Starlette's request.json() read it, before the API read every body in one place.
        self.make()
        r = self.client.post("/api/v1/session", content=b'\xef\xbb\xbf{"login_id": "NOVA", "password": "pass1234"}',
                             headers={"Content-Type": "application/json"})
        self.assertEqual(r.status_code, 200, r.text)
        # Bytes that are no text JSON reads: a bad request, as before.
        r = self.client.post("/api/v1/session", content=b'{"login_id": "\xff"}',
                             headers={"Content-Type": "application/json"})
        self.refused(r, 400, "bad_request")

    def test_a_body_too_large_is_the_apis_json_error(self):
        from opendmt3.server.web import app as web_app
        # A JSON body just past the site's limit.
        big = b'{"login_id": "' + b"x" * (web_app.BODY_LIMIT + 10) + b'"}'
        headers = {"Content-Type": "application/json"}
        # With its length said: the API's JSON error (it was the page's plain text).
        r = self.client.post("/api/v1/session", content=big, headers=headers)
        self.refused(r, 413, "too_large")
        # Sent in chunks, without a length, the same.
        r = self.client.post("/api/v1/session", content=(big[i:i + 4096] for i in range(0, len(big), 4096)),
                             headers=headers)
        self.refused(r, 413, "too_large")
        # A page's form keeps its plain answer: only the API answers in JSON.
        r = self.client.post("/signin", content=big, headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual((r.status_code, r.headers["content-type"].split(";")[0]), (413, "text/plain"))


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class AnswersTest(ApiBase):
    """The small answers the review found apart from the rest."""

    def test_a_long_jobs_quick_answer_is_its_id(self):
        from starlette.testclient import TestClient
        from opendmt3.server.services import backups
        self.make("BOSS", dj="BOSS", admin=True)
        # A backup to restore, made now.
        name = backups.make(self.site.db_path, self.tmp, "manual")
        # One loop for every request: the job's task outlives the call that started it.
        with TestClient(self.app, client=("203.0.113.5", 50000)) as client:
            token = client.post("/api/v1/session", json={"login_id": "BOSS", "password": "pass1234"}).json()["token"]
            headers = {"Authorization": "Bearer " + token}
            # Not waited for: answered at once.
            r = client.post("/api/v1/backups/%s/restore?wait=0" % name, headers=headers)
            self.assertEqual(r.status_code, 202)
            job = r.json()["job"]
            # The job's id, as the guide and the answer without ?wait=0 give it: the address to follow is jobs/<id>,
            # followed here to its end (the restore never outlives the test's folder).
            self.assertIsInstance(job, str)
            deadline = time.monotonic() + 30
            while True:
                followed = client.get("/api/v1/jobs/" + job, headers=headers).json()
                if followed["state"] != "running" or time.monotonic() > deadline:
                    break
                time.sleep(0.05)
            self.assertEqual((followed["id"], followed["state"]), (job, "done"))

    def test_an_uploads_import_knows_its_steps_from_the_start(self):
        import asyncio
        from opendmt3.server.web import common, jobs
        # An upload's file as the upload leaves it for its job (what it holds is the job's to check: here, no list).
        part = os.path.join(self.tmp, "upload.zip")
        with open(part, "wb") as f:
            f.write(b"not a song list")

        async def started():
            # On the loop, as the API's call starts it.
            job, _ = common._start_import(self.site, "BOSS", upload=part, shown_as="mine.zip")
            # Before its work says a word: an upload is a song list to check, then to swap in.
            steps = list(job.view()["steps"])
            # Its end (refused: no song list), before the test's folder goes.
            await job.finished
            return steps
        self.assertEqual(asyncio.run(started()), list(jobs.ROUTES["song_list"]["check"]))

    def test_a_jobs_view_is_of_one_moment(self):
        import sys
        import threading
        from opendmt3.server.web import insights, jobs, strings
        w = strings.words("en")
        # A folder's reading on its jackets (counted), then its cards (not), again and again on the work's thread,
        # while a reader asks for the job as GET /api/v1/jobs/{id} gives it, the threads switched as often as Python
        # lets them: each answer is of one moment, its step one of its steps with that step's count and words (read
        # apart, the review's "check" came with the steps of another reading).
        job = jobs.Job("song_list", "BOSS")
        job.say("songs")
        stop, torn = threading.Event(), []

        def work():
            while not stop.is_set():
                job.say("jackets", 1, 2)
                job.say("cards")

        old = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        thread = threading.Thread(target=work)
        thread.start()
        try:
            # A second: the views read apart tore within a tenth of one.
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline and not torn:
                view = insights.job_words(w, job)
                counted = (view["done"], view["total"], bool(view["count_text"]))
                if (view["step"] not in view["steps"]
                        or counted != ((1, 2, True) if view["step"] == "jackets" else (None, None, False))
                        or view["step_text"] != w("job.step." + view["step"])):
                    torn.append(view)
        finally:
            stop.set()
            thread.join()
            sys.setswitchinterval(old)
        self.assertEqual(torn, [])

    def test_paging_that_cannot_be_read_is_refused(self):
        self.make("BOSS", dj="BOSS", admin=True)
        boss = self.token("BOSS")
        # The review's (clamped or left out in silence), and digits of other scripts: outside "1 to 200", "1 and up".
        for query in ("per=0", "per=-1", "per=abc", "per=201", "per=1&page=-1", "per=1&page=0", "per=1&page=abc",
                      "per=1&page=99999999999999999999", "per=%C2%B2", "per=1&page=%C2%B2", "per=%EF%BC%91"):
            with self.subTest(query=query):
                r = self.call("GET", "/api/v1/log/requests?" + query, boss)
                self.refused(r, 400, "bad_request")
        # The most a page holds, and a page past the last (said by past), are read.
        self.assertEqual(self.call("GET", "/api/v1/log/requests?per=200&page=3", boss).status_code, 200)
        # The plays log's and the requests' filter: a digit str.isdigit() takes and int() refuses ("²") is no number
        # either (it failed with a traceback, on the API and on the Logs tab).
        with self.assertNoLogs("opendmt3", level=logging.ERROR):
            for path in ("/api/v1/log/plays?page=%C2%B2", "/api/v1/log/plays?player=%C2%B2",
                         "/api/v1/log/plays.csv?page=%C2%B2", "/api/v1/log/requests?kind=%C2%B2%C2%B2%C2%B2"):
                with self.subTest(path=path):
                    self.refused(self.call("GET", path, boss), 400, "bad_request")
            # A word to look for is any text, that one too.
            self.assertEqual(self.call("GET", "/api/v1/log/plays?q=%C2%B2", boss).status_code, 200)
            # The Logs tab's page keeps its lenient reading: what it cannot read is no filter.
            self.sign_in(self.client, "BOSS")
            for path in ("/admin/log/requests?page=abc", "/admin/log/requests?page=%C2%B2",
                         "/admin/log/requests?kind=%C2%B2%C2%B2%C2%B2", "/admin/log/plays?page=%C2%B2",
                         "/admin/log/plays?player=%C2%B2", "/admin/log/plays?q=%C2%B2"):
                with self.subTest(path=path):
                    self.assertEqual(self.client.get(path).status_code, 200)

    def test_a_folders_path_with_a_nul_is_refused(self):
        self.make("BOSS", dj="BOSS", admin=True)
        boss = self.token("BOSS")
        # Refused in words, nothing for the log (the review's was a 500 with the system's ValueError).
        with self.assertNoLogs("opendmt3", level=logging.ERROR):
            # The NUL alone, and inside a path.
            self.refused(self.call("GET", "/api/v1/server/folders?path=%00", boss), 400, "refused")
            self.refused(self.call("GET", "/api/v1/server/folders?path=/tmp%00x", boss), 400, "refused")
            # The import's path, which goes to the same system calls.
            self.refused(self.call("POST", "/api/v1/server/song_list", boss, json={"path": "/tmp\x00x"}), 400,
                         "refused")

    def test_a_read_only_token_signs_itself_out(self):
        self.make()
        # Two read-only tokens of one account, made with its sign-in.
        signed = self.token()
        reader = self.call("POST", "/api/v1/tokens", signed, json={"name": "reader", "scope": "read"}).json()
        other = self.call("POST", "/api/v1/tokens", signed, json={"name": "other", "scope": "read"}).json()
        # By its id: ending itself; another token of the account stays a change it may not make.
        self.refused(self.call("DELETE", "/api/v1/tokens/" + other["id"], reader["token"]), 403, "read_only")
        self.assertEqual(self.call("DELETE", "/api/v1/tokens/" + reader["id"], reader["token"]).status_code, 200)
        self.refused(self.call("GET", "/api/v1/me", reader["token"]), 401, "sign_in")
        # Or by signing out with it.
        self.assertEqual(self.call("DELETE", "/api/v1/session", other["token"]).json(), {"signed_out": True})
        self.refused(self.call("GET", "/api/v1/me", other["token"]), 401, "sign_in")

    def test_the_ban_sentence_names_the_reason(self):
        from opendmt3.server.services import players
        self.make()
        # NOVA banned, with the reason the admin wrote.
        store = self.site.accounts()
        try:
            players.Players(store.db).ban("NOVA", "Made-up reason", who="BOSS")
        finally:
            store.db.close()
        r = self.client.post("/api/v1/session", json={"login_id": "NOVA", "password": "pass1234"})
        error = r.json()["error"]
        # An older launcher shows the server's sentence: it carries the reason; a newer one reads reason itself.
        self.assertEqual((r.status_code, error["code"], error["message"], error["reason"]),
                         (403, "banned", "this account is banned: Made-up reason", "Made-up reason"))

    def test_one_second_is_said_as_one(self):
        from opendmt3.server.web import app as web_app
        # One second said as one ("1 seconds" was the review's); more in the plural.
        self.assertEqual(web_app.share_said(1), "this caller asked for more than its share of the server's work; "
                                                "try again in 1 second")
        self.assertTrue(web_app.share_said(3).endswith("in 3 seconds"))

    def test_no_such_song_or_dj_is_one_code_whatever_the_number(self):
        self.make()
        token = self.token()
        # No number (the routes' converter takes none of them), and a number nobody has: one code for each.
        for path in ("/api/v1/songs/-1", "/api/v1/songs/abc", "/api/v1/songs/99999999999999999999999"):
            self.refused(self.call("GET", path, token), 404, "unknown_song")
        for path in ("/api/v1/djs/-1", "/api/v1/djs/abc", "/api/v1/djs/99999999"):
            self.refused(self.call("GET", path, token), 404, "unknown_player")

    def test_a_tokens_name_on_two_lines_is_refused(self):
        self.make()
        # The guide's "on one line": the break was made a space.
        r = self.call("POST", "/api/v1/tokens", self.token(), json={"name": "a\nb", "scope": "read"})
        self.refused(r, 400, "refused")

    def test_the_upload_limits_are_said_alike_and_health_is_never_stored(self):
        from opendmt3.server.services import backups, songlist
        # In lower case and with no full stop, as every refusal's English (the song list's had both).
        self.assertEqual(str(songlist.too_large()), "an uploaded song list is at most 64 MB")
        self.assertEqual(str(backups.too_large()), "an uploaded backup is at most 256 MB")
        # A monitor's answer kept by no cache on the way, as the API's are.
        self.assertEqual(self.client.get("/health").headers.get("cache-control"), "no-store")


if __name__ == "__main__":
    unittest.main()
