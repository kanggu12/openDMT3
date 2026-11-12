"""The site's work never runs on the event loop the game server shares, each request has one connection to the
database, and the lists it keeps (web/cache.py) are always the lists made from the database now.

They need the web libraries (Starlette, Jinja2, httpx); without them they are skipped.
"""

import asyncio
import json
import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from tests.server.test_web import WEB


def stage(song, pattern, score):
    """A cleared stage as messages.stage_results gives it."""
    return {"song": song, "pattern": pattern, "score": score, "counts": [0] * 7, "raw": bytes(47)}


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class SiteWorkTest(unittest.TestCase):

    def setUp(self):
        from opendmt3.server import db
        from opendmt3.server.services import accounts, records
        from opendmt3.server.web.app import Site, create_app
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "openDMT3.sqlite")
        connection = db.connect(self.path)
        store = accounts.Accounts(connection)
        self.boss = store.create("BOSS", "pass1234", "DJ BOSS", is_admin=True)
        self.nova = store.create("NOVA", "pass1234", "DJ NOVA")
        self.rio = store.create("RIO", "pass1234", "RIO")
        plays = records.Records(connection)
        # A small history on a few charts of two modes, some of them beaten later (records).
        for n, (who, mode, song, pattern, score) in enumerate([
                (self.nova, 0, 1, 1, 4000), (self.rio, 0, 1, 1, 5000), (self.nova, 0, 1, 1, 6000),
                (self.boss, 1, 2, 2, 9000), (self.rio, 1, 2, 2, 9500), (self.nova, 0, 3, 1, 100)]):
            plays.add(who["id"], "10.0.0.5:1", mode, stage(song, pattern, score), at=1_700_000_000 + n)
        connection.close()
        with open(os.path.join(self.tmp, "catalog.json"), "w") as f:
            json.dump({"songs": [{"number": 1, "title": "Song One"}, {"number": 2, "title": "Song Two"},
                                 {"number": 3, "title": "Song Three"}]}, f)
        self.site = Site(self.tmp)
        self.app = create_app(self.site)

    def tearDown(self):
        import gc
        gc.collect()
        shutil.rmtree(self.tmp)

    async def signed_in(self, client, login_id):
        """The site's sign-in form as a browser sends it."""
        page = (await client.get("/signin")).text
        token = page.split('name="csrf" value="', 1)[1].split('"', 1)[0]
        r = await client.post("/signin", data={"csrf": token, "login_id": login_id, "password": "pass1234"})
        self.assertEqual(r.status_code, 303)

    def test_the_loop_never_runs_a_query_and_a_request_opens_one_connection(self):
        import httpx
        from opendmt3.server import db
        statements, opened = [], []
        real = db.connect

        def traced(path, **kwargs):
            # Every connection the site opens: counted, and each statement it runs noted with its thread.
            connection = real(path, **kwargs)
            opened.append(threading.get_ident())
            connection.set_trace_callback(lambda sql: statements.append((threading.get_ident(), sql)))
            return connection

        pages = ["/", "/rankings", "/rankings?by=best30", "/rankings?by=month", "/songs", "/songs/1",
                 "/dj/%d" % self.nova["id"], "/account", "/download", "/admin/players", "/admin/cabinets",
                 "/admin/status", "/admin/log", "/admin/log/plays", "/admin/backups", "/no-such-page"]
        calls = ["/api/v1/me", "/api/v1/rankings", "/api/v1/songs", "/api/v1/songs/1",
                 "/api/v1/djs/%d" % self.nova["id"], "/api/v1/plays?everyone=1", "/api/v1/plays?records=1",
                 "/api/v1/players", "/api/v1/server", "/api/v1/log", "/api/v1/cabinets?all=1", "/api/v1/tokens"]

        async def main():
            loop = threading.get_ident()
            transport = httpx.ASGITransport(app=self.app, client=("203.0.113.5", 50000))
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                await self.signed_in(client, "BOSS")
                token = (await client.post("/api/v1/session", json={"login_id": "BOSS", "password": "pass1234"}
                                           )).json()["token"]
                auth = {"Authorization": "Bearer " + token}
                answers = {}
                with mock.patch.object(db, "connect", traced):
                    del opened[:]
                    for path in pages:
                        answers[path] = (await client.get(path)).status_code
                    for path in calls:
                        answers[path] = (await client.get(path, headers=auth)).status_code
                    # Changes too: a form (the DJ name), a JSON call (the notice), the sign-in itself.
                    page = (await client.get("/account")).text
                    csrf = page.split('name="csrf" value="', 1)[1].split('"', 1)[0]
                    answers["dj_name"] = (await client.post("/account", data={
                        "csrf": csrf, "action": "dj_name", "dj_name": "BOSS 2"})).status_code
                    answers["notice"] = (await client.post("/api/v1/notice", json={"text": "hello"},
                                                           headers=auth)).status_code
                    answers["session"] = (await client.post("/api/v1/session", json={
                        "login_id": "NOVA", "password": "pass1234"})).status_code
            return loop, answers

        loop, answers = asyncio.run(main())
        self.assertEqual({k: v for k, v in answers.items() if v not in (200, 303)}, {"/no-such-page": 404})
        # Every statement of every request on a worker thread, none on the loop's.
        self.assertTrue(statements)
        on_loop = [sql for thread, sql in statements if thread == loop]
        self.assertEqual(on_loop, [], "statements run on the event loop")
        self.assertNotIn(loop, opened, "a connection opened on the event loop")
        # One connection a request, at most (a page that needs none opens none); the page and the token's check share
        # it. Each GET of /account above is one request: 16 pages, 12 calls, 4 more (the account page, its form, the
        # notice, the sign-in).
        self.assertLessEqual(len(opened), len(pages) + len(calls) + 4)

    def answers(self, site_app):
        """What the API says of every list kept, as an admin's token gets it (the plays of everyone, the records, the
        rankings by total, best 30 and month, the songs, a song's boards, each DJ, every player's card)."""
        from starlette.testclient import TestClient
        client = TestClient(site_app)
        token = client.post("/api/v1/session", json={"login_id": "BOSS", "password": "pass1234"}).json()["token"]
        auth = {"Authorization": "Bearer " + token}
        out = {}
        for path in ("/api/v1/plays?everyone=1", "/api/v1/plays?records=1", "/api/v1/rankings?mode=0",
                     "/api/v1/rankings?mode=1", "/api/v1/rankings?mode=0&by=best30", "/api/v1/rankings?mode=0&by=month",
                     "/api/v1/songs", "/api/v1/songs/1", "/api/v1/songs/2", "/api/v1/players"):
            out[path] = client.get(path, headers=auth).json()
        for row in client.get("/api/v1/players", headers=auth).json()["players"]:
            r = client.get("/api/v1/djs/%d" % row["player"], headers=auth)
            out["dj %d" % row["player"]] = r.json() if r.status_code == 200 else r.status_code
        # The time a sign-in was made is no list's: left out of the comparison.
        for row in out["/api/v1/players"]["players"]:
            row.pop("last_login", None)
        return out

    def fresh(self):
        """The same answers from a site that keeps nothing (a new Site each time: every list made now)."""
        from opendmt3.server.web.app import Site, create_app
        return self.answers(create_app(Site(self.tmp)))

    def test_kept_lists_are_always_the_lists_made_now(self):
        from opendmt3.server import db
        from opendmt3.server.services import accounts, backups, records
        kept_app = self.app
        # Every list made once and kept.
        self.assertEqual(self.answers(kept_app), self.fresh())
        made = self.site.lists.made
        # Asked again with nothing changed: every list handed out as kept, none made again.
        self.answers(kept_app)
        self.assertEqual(self.site.lists.made, made)
        backup = backups.make(self.path, self.tmp, "manual")
        changes = [
            ("a play kept", lambda c: records.Records(c).add(self.rio["id"], "x", 0, stage(1, 1, 7000))),
            ("a player disabled", lambda c: accounts.Accounts(c).set_disabled("RIO", True)),
            ("a player enabled", lambda c: accounts.Accounts(c).set_disabled("RIO", False)),
            ("a player renamed", lambda c: accounts.Accounts(c).set_dj_name("NOVA", "NOVA 2")),
            ("a DJ card changed", lambda c: accounts.Accounts(c).set_card("NOVA", {}, icon=1, comment="hi")),
            ("one player's plays reset", lambda c: records.Records(c).reset(self.nova["id"])),
            ("a restore", lambda c: backups.restore(self.path, self.tmp, backup)),
            ("a player deleted", lambda c: accounts.Accounts(c).delete("RIO")),
            ("every play reset", lambda c: records.Records(c).reset()),
        ]
        for name, change in changes:
            connection = db.connect(self.path)
            try:
                change(connection)
            finally:
                connection.close()
            self.assertEqual(self.answers(kept_app), self.fresh(), "after %s" % name)

    def test_a_songs_boards_follow_the_song_list_they_were_made_with(self):
        # The boards are kept until the plays change and for the song list they were made with: a song list put in
        # place with other levels shows them at once.
        from starlette.testclient import TestClient
        client = TestClient(self.app)
        token = client.post("/api/v1/session", json={"login_id": "BOSS", "password": "pass1234"}).json()["token"]
        auth = {"Authorization": "Bearer " + token}

        def levels():
            charts = client.get("/api/v1/songs/1", headers=auth).json()["charts"]
            return sorted((c["mode"], c["pattern"], c["level"]) for c in charts)
        self.assertEqual(levels(), [(0, 1, None)])
        with open(os.path.join(self.tmp, "catalog.json"), "w") as f:
            json.dump({"songs": [{"number": 1, "title": "Song One", "star": [7, 8, 9, 10]},
                                 {"number": 2, "title": "Song Two"}, {"number": 3, "title": "Song Three"}]}, f)
        # A new file: another moment and size, so another stamp.
        os.utime(os.path.join(self.tmp, "catalog.json"), (1_800_000_000, 1_800_000_000))
        self.assertEqual(levels(), [(0, 1, 7)])

    def test_a_list_that_fails_is_not_kept_and_everyone_waiting_tries_again(self):
        from opendmt3.server.web import cache
        lists = cache.Lists()
        from opendmt3.server import db
        connection = db.connect(self.path)
        try:
            calls = []

            def failing():
                calls.append(1)
                raise RuntimeError("made-up failure")
            with self.assertRaises(RuntimeError):
                lists.get(connection, ("x",), failing)
            # Not kept: the next request makes it.
            self.assertEqual(lists.get(connection, ("x",), lambda: [1, 2]), [1, 2])
            # What is kept cannot be changed by a page: a copy can.
            kept = lists.get(connection, ("x",), lambda: [3])
            self.assertEqual(kept, [1, 2])
            with self.assertRaises(TypeError):
                kept.append(3)
            self.assertEqual(list(kept) + [3], [1, 2, 3])
            # Twenty threads asking at once for a list nobody has: made once, the same list for all. The database's
            # state held still meanwhile: a change counted in this process (records.changes(), by another test's
            # thread still at work) is a new state, whose list is rightly made again, and that is not this test's.
            lists.state = lambda connection, newest=None: (None, 0)
            made, barrier, got = [], threading.Barrier(20), []

            def slow():
                made.append(1)
                threading.Event().wait(0.2)
                return ["once"]

            def ask():
                barrier.wait()
                got.append(lists.get(connection, ("y",), slow))
            threads = [threading.Thread(target=ask) for _ in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual((len(made), len(got), {tuple(g) for g in got}), (1, 20, {("once",)}))
        finally:
            connection.close()

    def test_one_list_a_name_and_a_late_request_never_takes_the_newer_ones_place(self):
        from opendmt3.server.web import cache
        lists = cache.Lists()
        # Each list made reads the state twice (before and after it is made); a kept one once.
        states = iter([(10, 0), (10, 0), (11, 0), (11, 0), (10, 0), (11, 0), (11, 0), (11, 1), (11, 1), (11, 0),
                       (11, 1), (5, 1), (5, 1), (5, 1)])
        made = []

        def make():
            made.append(1)
            return [len(made)]
        with mock.patch.object(cache.Lists, "state", staticmethod(lambda connection, newest=None: next(states))):
            self.assertEqual(lists.get(None, ("x",), make), [1])
            # A newer state: made again, and the older list goes (one list a name).
            self.assertEqual(lists.get(None, ("x",), make), [2])
            self.assertEqual(len(lists._entries), 1)
            # A request that read the database before the newest play: made for it, the newer list kept.
            self.assertEqual(lists.get(None, ("x",), make), [3])
            self.assertEqual(lists.get(None, ("x",), make), [2])
            # A change of players or plays (the count moved): a newer state whatever the play's number; a request that
            # read before it is late again.
            self.assertEqual(lists.get(None, ("x",), make), [4])
            self.assertEqual(lists.get(None, ("x",), make), [5])
            # Another program put an older database back (the newest play's number went down, the count did not
            # move): the state did not move while the list was made, so it is the database's now, and kept.
            self.assertEqual(lists.get(None, ("x",), make), [6])
            self.assertEqual(lists.get(None, ("x",), make), [6])
        self.assertEqual(len(lists._entries), 1)


if __name__ == "__main__":
    unittest.main()
