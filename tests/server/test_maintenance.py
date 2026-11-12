"""Tests for maintenance on the site: the admin turns it on and off on the Status page and through its API twin, every
page says it is on beside the notice, the change log says who, and it is kept in data/maintenance.json as the notice is
kept. What the game server does while it is on is tested at the protocol level in tests/server/test_server.py
(test_maintenance_refuses_card_logins_and_keeps_the_cabinets_online).

The service needs nothing more; the pages and the API need the web libraries (skipped without them).
"""

import os
import shutil
import tempfile
import unittest

from opendmt3.server.services import maintenance
# The API's calls with a token and the site's forms (tests/server/test_api.py).
from tests.server.test_api import ApiBase
from tests.server.test_web import WEB


class MaintenanceFileTest(unittest.TestCase):
    """services/maintenance.py: on and off, kept as a file, and a broken file counts as off."""

    def setUp(self):
        self.data = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.data)

    def test_on_and_off_change_once_and_keep_who_and_when(self):
        self.assertIsNone(maintenance.read(self.data))
        self.assertEqual(maintenance.write(self.data, True, who="BOSS", now=1000), ({"at": 1000, "by": "BOSS"}, True))
        # On again: nothing changes, the first moment and admin stay.
        self.assertEqual(maintenance.write(self.data, True, who="KAI", now=2000), ({"at": 1000, "by": "BOSS"}, False))
        self.assertEqual(maintenance.read(self.data), {"at": 1000, "by": "BOSS"})
        self.assertEqual(maintenance.write(self.data, False), (None, True))
        self.assertEqual(maintenance.write(self.data, False), (None, False))
        # Off is no file; nothing half written is left either.
        self.assertEqual(os.listdir(self.data), [])

    def test_admins_turning_it_on_at_once_never_leave_a_broken_file(self):
        # Eight threads turn it on (and the notice written beside it) at the same moment, again and again: no write
        # fails, and the file is always whole, so maintenance reads as on (a broken one reads as off).
        import json
        import threading
        from opendmt3.server.services import notice
        failures, barrier = [], threading.Barrier(8)

        def admin(k):
            barrier.wait()
            for n in range(40):
                try:
                    if n % 2:
                        maintenance.write(self.data, False, "ADMIN%d" % k)
                    maintenance.write(self.data, True, "ADMIN%d" % k)
                    notice.write(self.data, "notice %d from %d" % (n, k), "ADMIN%d" % k)
                except Exception as e:  # noqa: BLE001  (any failure is the test's answer)
                    failures.append(repr(e))
        threads = [threading.Thread(target=admin, args=(k,)) for k in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(failures, [])
        # The last write of every admin was "on": on, whole, by one of them.
        with open(os.path.join(self.data, maintenance.FILE), encoding="utf-8") as f:
            self.assertIn(json.load(f)["by"], {"ADMIN%d" % k for k in range(8)})
        self.assertIsNotNone(maintenance.read(self.data))
        with open(os.path.join(self.data, notice.FILE), encoding="utf-8") as f:
            self.assertTrue(json.load(f)["text"].startswith("notice 39 from "))

    def test_a_file_that_cannot_be_read_is_off_and_off_takes_it_away(self):
        with open(os.path.join(self.data, maintenance.FILE), "w") as f:
            f.write("{not json")
        self.assertIsNone(maintenance.read(self.data))
        maintenance.write(self.data, False)
        self.assertEqual(os.listdir(self.data), [])


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class MaintenanceSiteTest(ApiBase):
    """The Status page's Maintenance, the line on every page, and the API's twin."""

    BAR = '<div class="site-notice maintenance" role="status">'

    def test_the_admin_turns_it_on_and_off_on_the_status_page_and_every_page_says_so(self):
        self.admin()
        self.make()
        page = self.client.get("/admin/status").text
        self.assertIn("Off: the cabinets log in as usual.", page)
        self.assertNotIn(self.BAR, page)
        token = self.form_token(self.client, "/admin/status")
        # Another site's form (no token): nothing changes.
        self.client.post("/admin/status", data={"action": "maintenance_on"})
        self.assertIsNone(maintenance.read(self.tmp))
        page = self.client.post("/admin/status", data={"csrf": token, "action": "maintenance_on"}).text
        self.assertIn("Maintenance is on: the game server refuses card logins.", page)
        self.assertIn("On since ", page)
        self.assertEqual(maintenance.read(self.tmp)["by"], "BOSS")
        self.assertEqual(self.changes()[0], "started maintenance")
        # Every page says so, beside the notice (before it), a player's and the sign-in page too.
        self.call("POST", "/api/v1/notice", self.token("BOSS"), json={"text": "Back at nine"})
        for path in ("/", "/rankings", "/admin/players", "/account"):
            page = self.client.get(path).text
            self.assertIn(self.BAR, page, path)
            self.assertLess(page.index(self.BAR), page.index('<div class="site-notice" role="status">'), path)
        self.assertIn("The game cannot log in until maintenance ends.", self.client.get("/").text)
        from starlette.testclient import TestClient
        stranger = TestClient(self.app, client=("203.0.113.9", 50000))
        self.assertIn(self.BAR, stranger.get("/signin").text)
        self.sign_in(stranger)
        self.assertIn(self.BAR, stranger.get("/songs").text)
        # Korean: 점검.
        stranger.cookies.set("opendmt3_lang", "ko")
        self.assertIn("점검이 끝날 때까지 게임에 로그인할 수 없습니다.", stranger.get("/").text)
        # The Status page's numbers say it too, as its API twin does.
        self.assertTrue(self.call("GET", "/api/v1/server", self.token("BOSS")).json()["maintenance"])
        # Off again: logged, and the line goes from every page.
        page = self.client.post("/admin/status", data={"csrf": token, "action": "maintenance_off"}).text
        self.assertIn("Maintenance is over: the cabinets log in again.", page)
        self.assertNotIn(self.BAR, self.client.get("/").text)
        self.assertEqual(self.changes()[0], "ended maintenance")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, maintenance.FILE)))
        # A player has no Status page to turn it on with.
        r = stranger.post("/admin/status", data={"csrf": "x", "action": "maintenance_on"})
        self.assertEqual(r.status_code, 404)
        self.assertIsNone(maintenance.read(self.tmp))

    def test_the_api_reads_it_for_anyone_signed_in_and_admins_turn_it_on_and_off(self):
        self.make("BOSS", dj="BOSS", admin=True)
        self.make()
        boss, player = self.token("BOSS"), self.token()
        # Who may: a token for reading, an admin's to change.
        self.refused(self.call("GET", "/api/v1/maintenance"), 401, "sign_in")
        self.refused(self.call("POST", "/api/v1/maintenance", player), 403, "admin_only")
        self.refused(self.call("DELETE", "/api/v1/maintenance", player), 403, "admin_only")
        self.assertEqual(self.call("GET", "/api/v1/maintenance", player).json(), {"on": False})
        on = self.call("POST", "/api/v1/maintenance", boss).json()
        self.assertEqual((on["on"], on["by"]), (True, "BOSS"))
        self.assertIsInstance(on["at"], int)
        # A player reads that it is on and since when; who turned it on is for admins.
        self.assertEqual(self.call("GET", "/api/v1/maintenance", player).json(), {"on": True, "at": on["at"]})
        # On again changes nothing and logs nothing; a HEAD changes nothing either.
        self.assertEqual(self.call("POST", "/api/v1/maintenance", boss).json(), on)
        self.assertEqual(self.call("HEAD", "/api/v1/maintenance", boss).status_code, 200)
        self.assertEqual(self.changes().count("started maintenance"), 1)
        self.assertEqual(self.call("DELETE", "/api/v1/maintenance", boss).json(), {"on": False})
        self.assertEqual(self.changes()[0], "ended maintenance")
        self.assertIsNone(maintenance.read(self.tmp))


if __name__ == "__main__":
    unittest.main()
