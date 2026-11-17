"""Tests for what the admin pages show of the server's use, each with its API twin: the requests log (its size cap,
its days, its filter and file), the machine's last day and the disk's parts, when players play, the players' last two
weeks with their sorting and file, the long jobs that follow a song list's import and a restore, and stopping the
server, which asks the one that started it (a real server process, stopped from its admin page's API).

The web parts need the web libraries (Starlette, Jinja2, httpx); without them they are skipped.
"""

import asyncio
import csv
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from tests.server.test_api import ApiBase
from tests.server.test_web import WEB

# The repository's top folder (this file is in tests/server/).
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Clock:
    """A clock a test moves by hand."""

    def __init__(self, now=1_800_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


class RequestLogTest(unittest.TestCase):
    """services/requestlog.py on its own: what a line keeps, the files' cap and days, the filter, the chart."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def made(self, **kwargs):
        from opendmt3.server.services import requestlog
        return requestlog.RequestLog(self.tmp, **kwargs)

    def test_a_line_keeps_what_was_asked_without_a_one_use_links_token(self):
        log = self.made()
        log.add("GET", "/signin/once/SECRET-TOKEN-1234", 303, 1.234, "127.0.0.1")
        log.add("GET", "/songs?q=" + "x" * 500, 200, 2.0, "203.0.113.5", "NOVA")
        self.assertEqual(log.write(), 2)
        with open(log.path, encoding="utf-8") as f:
            lines = [json.loads(line) for line in f]
        self.assertEqual(lines[0]["path"], "/signin/once/...")
        self.assertNotIn("SECRET", open(log.path, encoding="utf-8").read())
        # A long query is cut to a line of a sane length.
        self.assertEqual(len(lines[1]["path"]), 300)
        self.assertEqual((lines[1]["status"], lines[1]["who"], lines[1]["ms"]), (200, "NOVA", 2.0))

    def test_the_files_stay_under_their_cap_and_days(self):
        # The files' own times are this PC's: the clock starts there.
        clock = Clock(time.time())
        log = self.made(clock=clock, most_bytes=4096, files=3, days=2)
        for n in range(400):
            log.add("GET", "/page/%d" % n, 200, 1.0, "203.0.113.5")
            if n % 20 == 19:
                log.write()
        log.write()
        # Three files at most (the current one and two turned over), each just past the cap at most.
        names = sorted(os.listdir(log.folder))
        self.assertTrue({"requests.log.1", "requests.log.2"} <= set(names) <= {"requests.log", "requests.log.1",
                                                                             "requests.log.2"}, names)
        self.assertTrue(all(os.path.getsize(os.path.join(log.folder, n)) < 4096 + 2048 for n in names))
        # The newest lines are in the files, the oldest gone with the files turned over.
        everything = [line["path"] for line in log.all()]
        self.assertEqual(everything[-1], "/page/399")
        self.assertNotIn("/page/0", everything)
        # Two days on, a turn over takes every file older than that.
        old = time.time() - 3 * 86400
        for n in names:
            os.utime(os.path.join(log.folder, n), (old, old))
        clock.now = time.time()
        log.tidy()
        self.assertEqual(os.listdir(log.folder), [])

    def test_the_filter_and_the_chart(self):
        clock = Clock(1_800_000_000.0)
        log = self.made(clock=clock)
        log.add("GET", "/admin/players", 200, 1.0, "203.0.113.5", "BOSS")
        log.add("POST", "/signin", 429, 1.0, "198.51.100.9")
        clock.now += 1800
        log.add("GET", "/nothing", 404, 1.0, "198.51.100.9")
        log.add("GET", "/boom", 500, 1.0, "198.51.100.9")
        # Newest first; a word of the path, the address or the account, in any case; a kind, or a status itself.
        self.assertEqual([r["path"] for r in log.recent()[0]], ["/boom", "/nothing", "/signin", "/admin/players"])
        self.assertEqual([r["path"] for r in log.recent("boss")[0]], ["/admin/players"])
        self.assertEqual([r["path"] for r in log.recent("198.51.100.9", "refused")[0]], ["/nothing", "/signin"])
        self.assertEqual([r["path"] for r in log.recent(kind="500")[0]], ["/boom"])
        self.assertEqual(log.recent(most=1), ([log.recent()[0][0]], 4))
        # The day in 48 half hours, the last one this one: what was answered, and what was refused or failed.
        chart = log.chart()
        self.assertEqual(len(chart), 48)
        self.assertEqual([(s["ok"], s["bad"]) for s in chart[-2:]], [(1, 1), (0, 2)])
        # A day later those half hours are gone from the chart.
        clock.now += 86400
        self.assertEqual(sum(s["ok"] + s["bad"] for s in log.chart()), 0)

    def test_a_restart_finds_the_last_day_in_the_files(self):
        clock = Clock(1_800_000_000.0)
        log = self.made(clock=clock)
        log.add("GET", "/a", 200, 1.0, "203.0.113.5", at=clock.now - 3 * 86400)
        log.add("GET", "/b", 404, 1.0, "203.0.113.5", at=clock.now - 600)
        log.write()
        again = self.made(clock=clock)
        again.write()
        # The list has both; the chart only the last day's.
        self.assertEqual([r["path"] for r in again.recent()[0]], ["/b", "/a"])
        self.assertEqual(sum(s["bad"] for s in again.chart()), 1)
        self.assertEqual(sum(s["ok"] for s in again.chart()), 0)

    def test_nothing_is_written_once_the_data_folder_is_gone(self):
        log = self.made()
        log.add("GET", "/", 200, 1.0, "203.0.113.5")
        shutil.rmtree(self.tmp)
        self.assertEqual(log.write(), 0)
        self.assertFalse(os.path.exists(self.tmp))
        os.makedirs(self.tmp)


class MachineTest(unittest.TestCase):
    """services/machine.py with made-up readings: the processors' share, a point, the day kept small."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_points_from_the_looks_and_a_day_kept_at_most(self):
        from opendmt3.server.services import machine
        clock = Clock()
        readings = iter([(1000, 900), (2000, 1400), (3000, 2400)])
        sampler = machine.Sampler(self.tmp, cabinets=lambda: 3, clock=clock, cpu=lambda: next(readings),
                                  memory=lambda: {"total": 1000, "used": 250},
                                  disk=lambda path: {"total": 100, "used": 40, "free": 60})
        # The first look has nothing to compare with; then 50 % busy, then 0 %.
        sampler.look()
        sampler.look()
        sampler.look()
        point = sampler.keep()
        self.assertEqual({k: point[k] for k in ("cpu", "peak", "memory", "disk", "cabinets")},
                         {"cpu": 25.0, "peak": 50.0, "memory": 25.0, "disk": 40.0, "cabinets": 3})
        # A day's points and no more, in the file too.
        for n in range(machine.KEEP + 20):
            clock.now += machine.POINT
            sampler.keep()
        with open(sampler.path, encoding="utf-8") as f:
            kept = json.load(f)["points"]
        self.assertEqual(len(kept), machine.KEEP)
        self.assertLess(os.path.getsize(sampler.path), 64 * 1024)
        # The day as five-minute slots, every one filled, the newest last.
        slots = sampler.slots(clock.now)
        self.assertEqual((len(slots), slots[-1]["at"], None in slots), (machine.KEEP, int(clock.now), False))
        # A restart reads the day back; points older than a day are left out.
        again = machine.Sampler(self.tmp, clock=clock)
        again.load()
        self.assertEqual(len(again.points), machine.KEEP)
        clock.now += 2 * 86400
        later = machine.Sampler(self.tmp, clock=clock)
        later.load()
        self.assertEqual(len(later.points), 0)

    def test_this_machines_own_readings(self):
        # On Linux (the tests' and the image's) every reading is there; elsewhere a reading may be None, never wrong.
        from opendmt3.server.services import machine
        disk = machine.read_disk(self.tmp)
        self.assertTrue(disk["total"] >= disk["used"] > 0)
        if sys.platform.startswith("linux"):
            self.assertIsNotNone(machine.read_cpu())
            self.assertGreater(machine.read_memory()["total"], 0)
            self.assertGreater(machine.read_uptime(), 0)


class JobTest(unittest.TestCase):
    """web/jobs.py: a job's steps, how far it has come, how it ends, and the work's steps reaching it."""

    def test_a_job_follows_its_works_steps_and_ends(self):
        from opendmt3.server.services import progress
        from opendmt3.server.web import jobs

        def work():
            progress.step("unpack")
            progress.step("jackets", 5, 10)
            return {"songs": 7}

        async def run():
            table = jobs.Jobs()
            job = table.start("song_list", "BOSS", work)
            self.assertEqual(job.state, "running")
            await job.finished
            return table, job
        table, job = asyncio.run(run())
        self.assertEqual((job.state, job.result, job.step), ("done", {"songs": 7}, "jackets"))
        # An archive's first step told which steps an import goes through.
        self.assertEqual(job.steps, ("unpack", "songs", "jackets", "cards", "swap"))
        self.assertEqual(job.share(), 1.0)
        self.assertEqual(table.all(), [job])

    def test_how_far_a_job_has_come(self):
        from opendmt3.server.web import jobs
        job = jobs.Job("restore", "BOSS")
        self.assertEqual(job.share(), 0.0)
        job.say("copy", 50, 100)
        # Two steps of four behind it, half the third.
        self.assertEqual(job.share(), 0.625)
        job.say("upgrade")
        self.assertEqual(job.share(), 0.75)

    def test_a_failure_says_why(self):
        from opendmt3.server.web import jobs

        def work():
            raise RuntimeError("made-up failure")

        async def run():
            job = jobs.Jobs().start("restore", "BOSS", work)
            await job.finished
            return job
        job = asyncio.run(run())
        self.assertEqual((job.state, job.view()["error"]["message"]), ("failed", "made-up failure"))

    def test_a_restore_says_its_steps(self):
        from opendmt3.server import db
        from opendmt3.server.services import backups, progress
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        database = os.path.join(tmp, "openDMT3.sqlite")
        db.connect(database).close()
        name = backups.make(database, tmp, "manual")
        said = []
        token = progress.REPORT.set(lambda step, done, total: said.append((step, done, total)))
        try:
            backups.restore(database, tmp, name)
        finally:
            progress.REPORT.reset(token)
        steps = [s for s, _, _ in said]
        self.assertEqual([s for i, s in enumerate(steps) if s not in steps[:i]], ["check", "backup", "copy", "upgrade"])
        # The copy counts its pages to the end.
        copied = [(d, t) for s, d, t in said if s == "copy" and t]
        self.assertTrue(copied and copied[-1][0] == copied[-1][1], said)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class AdminPagesTest(ApiBase):
    """The admin pages and their API twins: requests, the machine, when people play, the players, jobs, stopping."""

    def test_every_request_is_logged_with_who_asked_but_not_the_files(self):
        self.admin()
        self.client.get("/admin/players")
        self.client.get("/static/site.css")
        self.client.get("/health")
        self.client.get("/nothing-here")
        lines, _ = self.site.requests.recent()
        paths = [(r["path"], r["status"], r["who"]) for r in lines]
        self.assertIn(("/admin/players", 200, "BOSS"), paths)
        self.assertIn(("/nothing-here", 404, "BOSS"), paths)
        self.assertFalse([p for p, _, _ in paths if p.startswith(("/static/", "/health"))])
        # The sign-in's own POST, before anyone was signed in.
        self.assertIn(("/signin", 303, None), paths)

    def test_the_requests_tab_its_filter_its_file_and_its_twin(self):
        self.admin()
        for _ in range(3):
            self.client.get("/missing-page")
        page = self.client.get("/admin/log/requests?kind=refused").text
        self.assertIn("/missing-page", page)
        self.assertNotIn("<code>GET /admin/players</code>", page)
        # The chart's 48 half hours, each with its tip, and the table under it.
        self.assertEqual(page.count('class="slot"'), 48)
        # The file: every line the log keeps that the filter leaves, the first line its columns.
        r = self.client.get("/admin/log/requests.csv?q=missing")
        self.assertEqual(r.headers["content-type"], "text/csv; charset=utf-8")
        rows = list(csv.reader(io.StringIO(r.text.lstrip("﻿"))))
        self.assertEqual(rows[0], ["at", "method", "path", "status", "ms", "address", "who"])
        self.assertEqual([row[2] for row in rows[1:]], ["/missing-page"] * 3)
        boss = self.token("BOSS")
        answer = self.call("GET", "/api/v1/log/requests?kind=refused", boss).json()
        self.assertEqual(len(answer["chart"]), 48)
        self.assertGreaterEqual(answer["found"], 3)
        self.refused(self.call("GET", "/api/v1/log/requests?kind=bad", boss), 400, "bad_request")

    def test_a_page_of_requests_past_the_last_says_so_with_the_way_to_the_last(self):
        self.admin()
        for _ in range(3):
            self.client.get("/missing-page")
        # A bookmark of a page the log has rolled past: said, with the way to the last page there is.
        page = self.client.get("/admin/log/requests?page=50&kind=refused").text
        self.assertIn("This page is past the last one.", page)
        self.assertIn('href="/admin/log/requests?kind=refused&amp;page=1"', page)
        boss = self.token("BOSS")
        answer = self.call("GET", "/api/v1/log/requests?per=2&page=99", boss).json()
        found = answer["found"]
        self.assertEqual((answer["requests"], answer["past"], answer["last_page"]), ([], True, -(-found // 2)))
        # A page that is there says nothing of the kind.
        answer = self.call("GET", "/api/v1/log/requests?per=2&page=1", boss).json()
        self.assertEqual((answer["past"], answer["last_page"]), (False, -(-answer["found"] // 2)))
        self.assertNotIn("This page is past the last one.", self.client.get("/admin/log/requests?page=1").text)

    def test_the_requests_file_never_gives_a_spreadsheet_a_formula(self):
        from starlette.testclient import TestClient
        from opendmt3.server.services import requestlog
        self.admin()
        # The review's attack: anonymous requests whose methods are formulas (HTTP's tokens may hold + - ' | !), from
        # an address that is one too and very long (behind --proxy, what a forwarded header names).
        odd = TestClient(self.app, client=("=1+2" + "9" * 500, 50000))
        for method in ("+cmd|calc!A0", "-2+3", "@SUM(1)", "GET"):
            odd.request(method, "/zz", follow_redirects=False)
        # A line an older server wrote, before it kept only HTTP's own methods: read as it is, never as a formula.
        os.makedirs(os.path.join(self.tmp, requestlog.FOLDER), exist_ok=True)
        with open(os.path.join(self.tmp, requestlog.FOLDER, requestlog.NAME), "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": time.time(), "method": "=HYPERLINK(1)", "path": "/zz-old", "status": 200,
                                "ms": 1.0, "address": "+1-1", "who": "-1"}) + "\n")
        rows = []
        for path in ("/admin/log/requests.csv?q=zz", "/api/v1/log/requests.csv?q=zz"):
            r = self.client.get(path) if path.startswith("/admin/") else self.call("GET", path, self.token("BOSS"))
            # The rows of the requests above (the file's own download matches the filter too, by its query).
            rows.append([row for row in csv.reader(io.StringIO(r.text.lstrip("﻿"))) if row[2:3] in (["/zz"],
                                                                                                          ["/zz-old"])])
        # The page's file and its API twin give the same rows.
        self.assertEqual(rows[0], rows[1])
        # No cell of any row starts as a formula does.
        self.assertEqual([cell for row in rows[0] for cell in row if cell[:1] in ("=", "+", "-", "@", "\t", "\r")], [])
        by_path = {}
        for row in rows[0]:
            by_path.setdefault(row[2], []).append(row)
        # The methods HTTP has are kept as they came; any other is one word; the old line's, made harmless.
        self.assertEqual(sorted(row[1] for row in by_path["/zz"]), ["GET", "OTHER", "OTHER", "OTHER"])
        self.assertEqual([row[1] for row in by_path["/zz-old"]], ["'=HYPERLINK(1)"])
        # The address cut to a sane length and made harmless; the old line's address and account too.
        self.assertTrue(all(len(row[5]) <= requestlog.ADDRESS_MOST + 1 and row[5].startswith("'=1+2")
                            for row in by_path["/zz"]), by_path["/zz"])
        self.assertEqual(by_path["/zz-old"][0][5:], ["'+1-1", "'-1"])

    def test_the_status_tab_shows_the_machine_the_disk_and_when_players_play(self):
        self.admin()
        nova = self.make()
        now = time.time()
        for n in range(3):
            self.play(nova, 1, 1, 500 + n, at=int(now) - 60 * n)
        page = self.client.get("/admin/status").text
        for words in ("Resources", "What takes the disk", "When players play"):
            self.assertIn(words, page)
        # The grid: 7 days of 24 hours, each with its tip; three plays this hour on today's row.
        self.assertEqual(page.count("<i class=\"h"), 7 * 24 + 5)
        hours = self.call("GET", "/api/v1/server", self.token("BOSS")).json()["hours"]
        today = time.localtime(now)
        self.assertEqual(sum(map(sum, hours["grid"])), 3)
        self.assertGreaterEqual(hours["grid"][today.tm_wday][today.tm_hour], 1)
        machine = self.call("GET", "/api/v1/status/machine", self.token("BOSS")).json()
        parts = {p["part"]: p["bytes"] for p in machine["disk_parts"]}
        self.assertGreater(parts["database"], 0)
        self.assertEqual(sorted(parts), sorted(["database", "backups", "song_list", "downloads", "logs", "other",
                                                "free"]))
        # Korean too.
        self.client.cookies.set("opendmt3_lang", "ko")
        page = self.client.get("/admin/status").text
        self.assertIn("플레이 시간대", page)
        self.assertIn("디스크 사용", page)

    def test_players_have_their_two_weeks_sorting_and_a_file(self):
        self.admin()
        nova, rio = self.make(), self.make("RIO", dj="ARIO")
        now = int(time.time())
        for n in range(4):
            self.play(nova, 1, 1, 500 + n, at=now - 86400 * n)
        self.play(rio, 1, 1, 400, at=now - 86400 * 30)
        page = self.client.get("/admin/players").text
        # By last play first: NOVA, then RIO, then the admin who never played.
        order = [page.index("<code>%s</code>" % login) for login in ("NOVA", "RIO", "BOSS")]
        self.assertEqual(order, sorted(order))
        self.assertIn('aria-sort="descending"', page)
        self.assertIn("4 stages in the last 14 days", page)
        # By DJ name, from A: ARIO, BOSS, DJ NOVA; the header says so, and offers the other way.
        page = self.client.get("/admin/players?sort=dj").text
        order = [page.index("<code>%s</code>" % login) for login in ("RIO", "BOSS", "NOVA")]
        self.assertEqual(order, sorted(order))
        self.assertIn('aria-sort="ascending"', page)
        self.assertIn("/admin/players?sort=dj&amp;order=desc", page)
        rows = list(csv.DictReader(io.StringIO(self.client.get("/admin/players.csv").text.lstrip("﻿"))))
        found = {r["login_id"]: r for r in rows}
        self.assertEqual((found["NOVA"]["plays"], found["NOVA"]["plays_14_days"]), ("4", "4"))
        self.assertEqual((found["RIO"]["plays"], found["RIO"]["plays_14_days"]), ("1", "0"))
        listed = self.call("GET", "/api/v1/players?sort=plays", self.token("BOSS")).json()
        self.assertEqual([p["login_id"] for p in listed["players"]][:2], ["NOVA", "RIO"])
        self.assertEqual(listed["players"][0]["days"][-4:], [1, 1, 1, 1])
        self.assertEqual(self.call("GET", "/api/v1/players.csv", self.token("BOSS")).headers["content-type"],
                         "text/csv; charset=utf-8")

    def test_a_player_named_like_a_word_of_the_players_tab_has_a_page_and_the_file_still_comes(self):
        # The file's address is beside the list (players.csv), so an ID as DOWNLOAD (letters, as any ID) is a player.
        self.admin()
        self.make("DOWNLOAD", dj="DL")
        page = self.client.get("/admin/players").text
        self.assertIn('href="/admin/players/DOWNLOAD"', page)
        self.assertIn('href="/admin/players.csv"', page)
        mine = self.client.get("/admin/players/DOWNLOAD")
        self.assertEqual(mine.status_code, 200)
        self.assertIn("DL", mine.text)
        self.assertNotIn("text/csv", mine.headers["content-type"])
        # Lower case too, as an ID is read either way.
        self.assertNotIn("text/csv", self.client.get("/admin/players/download").headers["content-type"])
        listed = self.client.get("/admin/players.csv")
        self.assertIn("text/csv", listed.headers["content-type"])
        self.assertIn("DOWNLOAD", listed.text)
        answer = self.call("GET", "/api/v1/players/download", self.token("BOSS"))
        self.assertEqual(answer.json()["login_id"], "DOWNLOAD")
        self.assertIn("text/csv", self.call("GET", "/api/v1/players.csv", self.token("BOSS")).headers["content-type"])

    def test_a_restore_is_a_job_the_api_can_follow(self):
        from starlette.testclient import TestClient
        from opendmt3.server.services import backups
        self.admin()
        name = backups.make(self.site.db_path, self.tmp, "manual")
        # One loop for every request (the job's task outlives the call that started it).
        with TestClient(self.app, client=("203.0.113.5", 50000)) as client:
            token = client.post("/api/v1/session", json={"login_id": "BOSS", "password": "pass1234"}).json()["token"]
            headers = {"Authorization": "Bearer " + token}
            r = client.post("/api/v1/backups/%s/restore?wait=0" % name, headers=headers)
            self.assertEqual(r.status_code, 202, r.text)
            job = r.json()["job"]
            self.assertEqual((job["kind"], job["details"]["name"]), ("restore", name))
            for _ in range(100):
                job = client.get("/api/v1/jobs/" + job["id"], headers=headers).json()
                if job["state"] != "running":
                    break
                time.sleep(0.05)
            self.assertEqual((job["state"], job["result"]["restored"], job["share"]), ("done", name, 1.0))
            self.assertIn("Restored " + name, job["text"])
            self.assertEqual([j["id"] for j in client.get("/api/v1/jobs", headers=headers).json()["jobs"]],
                             [job["id"]])
            # The page's own twin of it, for the progress card, in the page's words.
            client.post("/signin", data={"csrf": self.signin_token(client), "login_id": "BOSS",
                                         "password": "pass1234"})
            self.assertEqual(client.get("/admin/jobs/" + job["id"]).json()["state"], "done")
            self.assertEqual(client.get("/admin/jobs/nothing").status_code, 404)
        self.refused(self.call("GET", "/api/v1/jobs/nothing", self.token("BOSS")), 404, "unknown_job")
        self.assertIn("restored the database from " + name, self.changes())

    def test_a_running_job_shows_its_progress_card(self):
        from opendmt3.server.web import jobs
        self.admin()
        job = jobs.Job("song_list", "BOSS")
        job.say("unpack")
        job.say("jackets", 40, 160)
        self.site.jobs._jobs[job.id] = job
        page = self.client.get("/admin/song_list?job=" + job.id).text
        self.assertIn('data-job="%s"' % job.id, page)
        self.assertIn("Reading the jackets", page)
        self.assertIn("40 of 160", page)
        self.assertIn('role="progressbar"', page)
        # The bar: two steps of five behind it and a quarter of the third.
        self.assertIn('aria-valuenow="45"', page)
        # Once it ended the page says how, with no card.
        job.state, job.result, job.ended = "done", {"songs": 12}, time.time()
        page = self.client.get("/admin/song_list?job=" + job.id).text
        self.assertNotIn('data-job="', page)
        self.assertIn("Imported the song list: 12 songs.", page)

    def test_the_server_tab_asks_whoever_started_the_server(self):
        from opendmt3.server.web import runner
        self.admin()
        token = self.form_token(self.client, "/admin/server")
        boss = self.token("BOSS")
        # A server the page cannot ask (started some other way): the tab says where to stop it, nothing stops. Set
        # here, as a Site made in a container (CI's) takes Docker Compose's by default.
        self.site.runner = runner.default(False)
        page = self.client.get("/admin/server").text
        self.assertIn("Stop it where it was started", page)
        self.assertNotIn("Stop the server</button>", page)
        for action in ("stop", "restart", "remove"):
            self.refused(self.call("POST", "/api/v1/server/" + action, boss), 409, "not_here")
        # Docker Compose (compose.yaml says so): the commands, on the server PC, and no button.
        self.site.runner = runner.default(True, {"OPENDMT3_RUNNER": "docker"})
        page = self.client.get("/admin/server").text
        for command in ("./dmt3 down", "./dmt3 restart", "./dmt3 remove --delete-data"):
            self.assertIn("<code>%s</code>" % command, page)
        self.assertNotIn("Restart the server</button>", page)
        r = self.call("POST", "/api/v1/server/remove", boss, json={"delete_data": True})
        self.assertEqual(r.json()["runner"]["commands"]["remove_data"], "./dmt3 remove --delete-data")
        self.assertIn("./dmt3 remove --delete-data", r.json()["error"]["message"])
        # The launcher: its own window does it.
        self.site.runner = runner.Runner("launcher")
        self.assertIn("Help, Uninstall", self.client.get("/admin/server").text)
        # The server's own command: each asked first in the site's dialog, then asked once.
        asked = []
        self.site.runner = runner.Runner("python", stop=lambda: asked.append("stop"),
                                         restart=lambda: asked.append("restart"),
                                         remove=lambda data: asked.append(("remove", data)))
        page = self.client.get("/admin/server").text
        for question in ("Stop the server now?", "Restart the server now?", "Delete the server&#39;s data?"):
            self.assertIn('data-ask="%s"' % question, page)
        r = self.client.post("/admin/server", data={"csrf": token, "action": "restart"})
        self.assertIn("The server is starting again.", r.text)
        self.assertIn('data-back="/admin/server"', r.text)
        time.sleep(runner.GRACE + 0.3)
        self.assertEqual(asked, ["restart"])
        # Asked once: a second press, on the page or the API, changes nothing.
        r = self.client.post("/admin/server", data={"csrf": token, "action": "stop"})
        self.assertIn("asked already", r.text)
        self.refused(self.call("POST", "/api/v1/server/stop", boss), 409, "asked_already")
        time.sleep(runner.GRACE + 0.3)
        self.assertEqual(asked, ["restart"])
        # Remove with its data, through the API: asked with the data.
        self.site.runner = runner.Runner("python", remove=lambda data: asked.append(("remove", data)))
        self.refused(self.call("POST", "/api/v1/server/remove", boss, json={"delete_data": "yes"}), 400,
                     "bad_request")
        r = self.call("POST", "/api/v1/server/remove", boss, json={"delete_data": True})
        self.assertEqual((r.status_code, r.json()["asked"], r.json()["delete_data"]), (202, "remove", True))
        time.sleep(runner.GRACE + 0.3)
        self.assertEqual(asked[-1], ("remove", True))
        self.assertTrue({"restarted the server", "removed the server and its data"} <= set(self.changes()))
        # Korean too.
        self.client.cookies.set("opendmt3_lang", "ko")
        self.assertIn("서버 제거", self.client.get("/admin/server").text)

    def test_on_kubernetes_the_server_tab_names_the_clusters_commands(self):
        from opendmt3.server.web import runner
        self.admin()
        boss = self.token("BOSS")
        # As the Helm chart runs it: the cluster's commands with the release's names, and no button (the cluster
        # starts and stops the server).
        self.site.runner = runner.default(True, {"KUBERNETES_SERVICE_HOST": "10.96.0.1", "OPENDMT3_RUNNER": "kubernetes",
                                                 "OPENDMT3_KUBE_NAMESPACE": "games", "OPENDMT3_KUBE_RELEASE": "dmt3",
                                                 "OPENDMT3_KUBE_DEPLOYMENT": "dmt3-opendmt3",
                                                 "OPENDMT3_KUBE_CLAIM": "dmt3-data"})
        page = self.client.get("/admin/server").text
        self.assertIn("Kubernetes", page)
        for command in ("kubectl -n games rollout restart deployment/dmt3-opendmt3",
                        "kubectl -n games scale deployment/dmt3-opendmt3 --replicas=0",
                        "helm -n games uninstall dmt3 &amp;&amp; kubectl -n games delete pvc dmt3-data"):
            self.assertIn("<code>%s</code>" % command, page)
        for button in ("Restart the server</button>", "Stop the server</button>",
                       "Delete the server&#39;s data</button>"):
            self.assertNotIn(button, page)
        self.assertNotIn("./dmt3", page)
        r = self.call("POST", "/api/v1/server/stop", boss)
        self.refused(r, 409, "not_here")
        self.assertIn("kubectl -n games scale deployment/dmt3-opendmt3 --replicas=0", r.json()["error"]["message"])
        self.assertEqual(self.call("GET", "/api/v1/server", boss).json()["runner"]["kind"], "kubernetes")
        # A container started by hand: Docker's own commands for it, never ./dmt3's.
        self.site.runner = runner.default(True, {"HOSTNAME": "3f2a9c1b7d4e"})
        page = self.client.get("/admin/server").text
        self.assertIn("<code>docker restart 3f2a9c1b7d4e</code>", page)
        self.assertNotIn("./dmt3", page)
        # Korean too.
        self.client.cookies.set("opendmt3_lang", "ko")
        self.site.runner = runner.default(True, {"KUBERNETES_SERVICE_HOST": "10.96.0.1"})
        self.assertIn("쿠버네티스", self.client.get("/admin/server").text)


def free_port():
    """A port nothing listens on now."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class RunnerKindsTest(unittest.TestCase):
    """Who started a server run in a container, as the Server tab tells it: Docker Compose (compose.yaml says so),
    Kubernetes (the Helm chart says so, or the cluster's own variable), or a container started by hand. The one that
    started it stops it: neither the cluster nor a plain container is asked from the tab, and each is named by its own
    commands, never by ./dmt3's."""

    def test_compose_kubernetes_and_a_plain_container_are_told_apart(self):
        from opendmt3.server.web import runner
        # compose.yaml's variable: Docker Compose, as before.
        compose = runner.default(True, {"OPENDMT3_RUNNER": "docker"})
        self.assertEqual((compose.kind, compose.view()["can"]), ("docker", []))
        self.assertEqual(compose.commands["remove_data"], "./dmt3 remove --delete-data")
        # The chart's variables: the cluster, with the release's names in its commands; no button.
        kube = runner.default(True, {"OPENDMT3_RUNNER": "kubernetes", "KUBERNETES_SERVICE_HOST": "10.96.0.1",
                                     "OPENDMT3_KUBE_NAMESPACE": "games", "OPENDMT3_KUBE_RELEASE": "dmt3",
                                     "OPENDMT3_KUBE_DEPLOYMENT": "dmt3-opendmt3", "OPENDMT3_KUBE_CLAIM": "dmt3-data"})
        self.assertEqual((kube.kind, kube.view()["can"]), ("kubernetes", []))
        self.assertEqual(kube.commands["restart"], "kubectl -n games rollout restart deployment/dmt3-opendmt3")
        self.assertEqual(kube.commands["stop"], "kubectl -n games scale deployment/dmt3-opendmt3 --replicas=0")
        self.assertEqual(kube.commands["start"], "kubectl -n games scale deployment/dmt3-opendmt3 --replicas=1")
        self.assertEqual(kube.commands["remove"], "helm -n games uninstall dmt3")
        self.assertEqual(kube.commands["remove_data"],
                         "helm -n games uninstall dmt3 && kubectl -n games delete pvc dmt3-data")
        # A cluster without the chart (its own variable only): the cluster's kind, its commands with names to fill.
        bare = runner.default(True, {"KUBERNETES_SERVICE_HOST": "10.96.0.1"})
        self.assertEqual(bare.kind, "kubernetes")
        self.assertNotIn("./dmt3", " ".join(v for v in bare.commands.values() if v))
        # A container started by hand (docker run): Docker's own commands for it, by its name, never ./dmt3.
        plain = runner.default(True, {"HOSTNAME": "3f2a9c1b7d4e"})
        self.assertEqual((plain.kind, plain.view()["can"]), ("container", []))
        self.assertEqual(plain.commands["restart"], "docker restart 3f2a9c1b7d4e")
        self.assertNotIn("./dmt3", " ".join(v for v in plain.commands.values() if v))


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class StopTheRealServerTest(unittest.TestCase):
    """The server's own command (python -m opendmt3.server), asked from its admin pages' API: it runs itself again in
    the same process, and it stops, keeps a last copy of its database beside its data folder and deletes the folder
    (a folder of the test's own)."""

    def test_the_command_restarts_and_removes_its_data_when_its_admin_asks(self):
        import httpx
        if os.path.exists("/.dockerenv"):
            self.skipTest("inside a container the server's runner is Docker Compose")
        # A data folder of the test's own, inside a folder of its own: the last copy lands beside it, in there too.
        parent = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, parent, True)
        data = os.path.join(parent, "data")
        env = dict(os.environ, PYTHONPATH=ROOT)
        env.pop("OPENDMT3_IN_CONTAINER", None)
        made = subprocess.run([sys.executable, "-m", "opendmt3.server", "--data", data, "--add-player", "BOSS",
                               "--password", "pass1234", "--admin"], env=env, capture_output=True, timeout=60)
        self.assertEqual(made.returncode, 0, made.stderr)
        # The admin site's port free too: tests on other processes start servers of their own at the same time.
        game, web, admin = free_port(), free_port(), free_port()
        server = subprocess.Popen([sys.executable, "-m", "opendmt3.server", "--data", data, "--port", str(game),
                                   "--web-port", str(web), "--admin-port", str(admin)], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        base = "http://127.0.0.1:%d" % web

        def up(seconds=20):
            # The site answers its health check (within `seconds`).
            for _ in range(int(seconds / 0.05)):
                try:
                    if httpx.get(base + "/health", timeout=1).status_code == 200:
                        return True
                except httpx.HTTPError:
                    pass
                time.sleep(0.05)
            return False

        def signed():
            token = httpx.post(base + "/api/v1/session", json={"login_id": "BOSS", "password": "pass1234"}).json()
            return {"Authorization": "Bearer " + token["token"]}
        try:
            self.assertTrue(up())
            # Restart: the same process (the window that started it keeps it) ends its server and runs it again.
            r = httpx.post(base + "/api/v1/server/restart", headers=signed())
            self.assertEqual((r.status_code, r.json()["runner"]["kind"], r.json()["runner"]["can"]),
                             (202, "python", ["stop", "restart", "remove"]))
            time.sleep(1.5)
            self.assertTrue(up())
            self.assertIsNone(server.poll())
            # Remove with its data: it stops, keeps the last copy beside the folder, and the folder goes.
            r = httpx.post(base + "/api/v1/server/remove", headers=signed(), json={"delete_data": True})
            self.assertEqual(r.status_code, 202, r.text)
            self.assertEqual(server.wait(timeout=30), 0)
        finally:
            if server.poll() is None:
                server.kill()
                server.wait()
            output = server.stdout.read().decode("utf-8", "replace")
            server.stdout.close()
        self.assertIn("stopping: asked on the admin page (restart)", output)
        self.assertIn("starting again: asked on the admin page", output)
        self.assertFalse(os.path.exists(data), output)
        kept = [n for n in os.listdir(parent) if n.startswith("data-last-") and n.endswith(".sqlite")]
        self.assertEqual(len(kept), 1, os.listdir(parent))
        # The copy is the database, its accounts in it.
        import sqlite3
        connection = sqlite3.connect(os.path.join(parent, kept[0]))
        try:
            self.assertEqual(connection.execute("SELECT login_id FROM accounts").fetchall(), [("BOSS",)])
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
