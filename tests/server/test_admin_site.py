"""Tests for the admin pages as a site of their own (ADMIN-SITE.md): the players' port answering their old addresses (a
308 on the server PC, the players' "not here" anywhere else), the admin site's own door that lets only admins in, each
site's own cookies (neither opens the other), the round of sign-ins the two share, the admin site's headers, the API on
both ports, the first run on the admin site, the players' footer's way to the admin pages, the admin site's links to the
players' pages, the launcher's one-use links for each site, the start banner's Admin row, the server's command with its
flags, and a real server listening on both ports.

They need the web libraries (Starlette, Jinja2, httpx for the test client); without them they are skipped.
"""

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

# The site on a temporary data folder (tests/server/test_web.py), its helpers to make accounts and sign in.
from tests.server.test_web import WEB, WebBase

# The admin site's address on the server PC in these tests (Site.admin_address), and the players' site's port.
ADMIN = "http://127.0.0.1:4731/"
SITE_PORT = 4730


def free_port():
    """A port nobody listens on now (the system's pick), for a real server."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class AdminSiteBase(WebBase):
    """A Site whose admin pages are a site of their own, as the server's command makes it: the players' app (on the
    site's port: a visitor from another PC, one from the server PC) and the admin app (on its port: a visit from the
    server PC, one from another PC on the network)."""

    def setUp(self):
        super().setUp()
        from starlette.testclient import TestClient
        from opendmt3.server.web.app import Site, create_admin_app, create_app
        # The players' site's address the owner chose (./dmt3 setup), as the server's --site-address gives it.
        self.site = Site(self.tmp, address="http://192.168.0.5:4730/", admin_address=ADMIN, admin_on_site_port=False,
                         site_port=SITE_PORT)
        self.app = create_app(self.site)
        self.admin_app = create_admin_app(self.site)
        self.client = TestClient(self.app, client=("203.0.113.5", 50000))
        self.local = TestClient(self.app, base_url="http://127.0.0.1:4730", client=("127.0.0.1", 50001))
        self.console = TestClient(self.admin_app, base_url="http://127.0.0.1:4731", client=("127.0.0.1", 50002))
        self.far_console = TestClient(self.admin_app, base_url="http://192.168.0.5:4731", client=("192.168.0.9", 50003))

    def admin(self, login_id="BOSS"):
        """An admin's account (not signed in anywhere yet)."""
        return self.make(login_id, dj=login_id, admin=True)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class PlayersPortTest(AdminSiteBase):
    """The admin pages' old addresses on the players' port."""

    def test_the_server_pc_goes_on_to_the_admin_site_and_a_post_stays_a_post(self):
        for path in ("/admin", "/admin/status", "/admin/players/NOVA", "/admin/log/plays?player=2&days=7"):
            r = self.local.get(path, follow_redirects=False)
            self.assertEqual((r.status_code, r.headers["location"]), (308, ADMIN.rstrip("/") + path), path)
        # A form's POST is sent on as a POST (308, never 303): the admin site then asks for its own sign-in.
        r = self.local.post("/admin/players", data={"action": "make"}, follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (308, ADMIN + "admin/players"))
        # The first run likewise: it is the admin site's now.
        r = self.local.get("/owner", follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (308, ADMIN + "owner"))

    def test_anyone_else_gets_the_players_page_that_is_not_there_signed_in_or_not(self):
        self.admin()
        for path in ("/admin", "/admin/status", "/admin/players/BOSS", "/owner"):
            r = self.client.get(path, follow_redirects=False)
            # Not the sign-in page first: these addresses are nothing on this site for this visitor.
            self.assertEqual(r.status_code, 404, path)
            self.assertNotIn('class="bar console', r.text, path)
            self.assertNotIn("4731", r.text, path)
        self.sign_in(self.client, "BOSS")
        r = self.client.post("/admin/status", data={"action": "maintenance_on"}, follow_redirects=False)
        self.assertEqual(r.status_code, 404)
        # Behind a proxy the visit is never the server PC's, whatever address the proxy names.
        r = self.local.get("/admin/status", headers={"X-Forwarded-For": "127.0.0.1"}, follow_redirects=False)
        self.assertEqual(r.status_code, 404)

    def test_the_players_bar_has_no_admin_pages(self):
        self.admin()
        self.sign_in(self.client, "BOSS")
        page = self.client.get("/").text
        bar = page.split('<header class="bar', 1)[1].split("</header>", 1)[0]
        self.assertNotIn("/admin", bar)
        sheet = page.split('id="menu-sheet"', 1)[1].split("</div>\n</div>", 1)[0]
        self.assertNotIn("/admin", sheet)

    def test_a_site_whose_port_serves_the_admin_pages_too_keeps_them_there(self):
        from starlette.testclient import TestClient
        from opendmt3.server.web.app import Site, create_app
        site = Site(self.tmp, admin_address=ADMIN, admin_on_site_port=True, site_port=SITE_PORT)
        browser = TestClient(create_app(site), client=("203.0.113.5", 50000))
        self.admin()
        self.sign_in(browser, "BOSS")
        page = browser.get("/admin/status")
        # The admin pages on the site's port, in the console's frame, with the players' own sign-in.
        self.assertEqual(page.status_code, 200)
        self.assertIn('<header class="bar console">', page.text)
        # Its footer's way back to the players' pages is this same address.
        self.assertIn('<p><a href="/">Players&#39; site</a></p>', page.text)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class AdminDoorTest(AdminSiteBase):
    """The admin site's own sign-in: admins only, its own cookie."""

    def test_its_top_goes_to_the_status_page_which_asks_for_its_own_sign_in(self):
        self.admin()
        r = self.console.get("/", follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/admin/status"))
        r = self.console.get("/admin/status", follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/signin?next=/admin/status"))
        door = self.console.get("/signin").text
        # The door: the family's mark with ADMIN, the server's version over it, and its own line; no rail, no keys.
        from opendmt3 import __version__
        self.assertIn('<span class="tail"><i class="v">v%s</i><span class="s">ADMIN</span></span>' % __version__, door)
        self.assertIn("The server&#39;s admin pages", door)
        self.assertNotIn('class="rail"', door)
        self.assertNotIn('<nav class="menu"', door)

    def test_only_an_account_with_admin_rights_gets_in_and_is_told_after_its_password(self):
        self.admin()
        self.make()
        # A wrong password: the one sentence for every wrong try, never a word of the account's rights.
        r = self.sign_in(self.console, "NOVA", "wrong123")
        self.assertEqual(r.status_code, 401)
        self.assertNotIn("admin rights", r.text)
        # The right password of a player: told so, for the whole form, and nobody is signed in.
        r = self.sign_in(self.console, "NOVA")
        self.assertEqual(r.status_code, 403)
        self.assertIn('<p class="form-error" role="alert">This account has no admin rights.</p>', r.text)
        self.assertIsNone(self.console.cookies.get("opendmt3_admin"))
        # The admin: on to the Status page, with the admin site's own cookie (strict) and not the players'.
        r = self.sign_in(self.console, "BOSS")
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/admin/status"))
        made = [h for h in r.headers.get_list("set-cookie") if h.startswith("opendmt3_admin=")]
        self.assertEqual(len(made), 1)
        self.assertIn("httponly", made[0].lower())
        self.assertIn("samesite=strict", made[0].lower())
        self.assertFalse(any(h.startswith("opendmt3=") for h in r.headers.get_list("set-cookie")))
        page = self.console.get("/admin/status").text
        self.assertIn('<header class="bar console">', page)
        self.assertIn('<div class="rail">', page)

    def test_the_sign_in_back_comes_to_the_page_asked_for(self):
        self.admin()
        r = self.console.post("/signin?next=/admin/backups", data={
            "csrf": self.signin_token(self.console), "login_id": "BOSS", "password": "pass1234"},
            follow_redirects=False)
        self.assertEqual(r.headers["location"], "/admin/backups")

    def test_over_https_the_admin_sites_cookie_is_secure(self):
        from starlette.testclient import TestClient
        self.admin()
        secure = TestClient(self.admin_app, base_url="https://dmt3.example:4731", client=("203.0.113.5", 50000))
        r = self.sign_in(secure, "BOSS")
        made = [h for h in r.headers.get_list("set-cookie") if h.startswith("opendmt3_admin=")][0]
        self.assertIn("secure", made.lower())


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class TwoSessionsTest(AdminSiteBase):
    """Each site reads its own cookie of its own kind; the account's round of sign-ins is one."""

    def test_neither_sites_sign_in_opens_the_other(self):
        self.admin()
        self.sign_in(self.client, "BOSS")
        players = self.client.cookies.get("opendmt3")
        self.assertTrue(players)
        # The players' cookie, under either name, does not open the admin site.
        for name in ("opendmt3", "opendmt3_admin"):
            self.console.cookies.clear()
            self.console.cookies.set(name, players)
            r = self.console.get("/admin/status", follow_redirects=False)
            self.assertEqual(r.status_code, 303, name)
        self.console.cookies.clear()
        self.sign_in(self.console, "BOSS")
        admin = self.console.cookies.get("opendmt3_admin")
        # The admin site's cookie, under the players' name, does not open the players' site.
        self.client.cookies.clear()
        self.client.cookies.set("opendmt3", admin)
        self.assertEqual(self.client.get("/", follow_redirects=False).status_code, 303)
        # The language is one choice for both.
        self.console.get("/lang/ko?next=/admin/status")
        self.assertEqual(self.console.cookies.get("opendmt3_lang"), "ko")
        self.assertIn('<html lang="ko">', self.console.get("/admin/status").text)

    def test_a_sign_out_ends_the_accounts_round_on_both_sites(self):
        self.admin()
        self.sign_in(self.client, "BOSS")
        self.sign_in(self.console, "BOSS")
        self.assertEqual(self.client.get("/", follow_redirects=False).status_code, 200)
        token = self.console.get("/admin/status").text.split('name="csrf" value="', 1)[1].split('"', 1)[0]
        r = self.console.post("/signout", data={"csrf": token}, follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/signin"))
        # The round of sign-ins is the account's: every browser's, the players' site's too.
        self.assertEqual(self.client.get("/", follow_redirects=False).status_code, 303)

    def test_rights_taken_end_the_admin_sign_in_at_once(self):
        self.admin()
        self.admin("CHIEF")
        self.sign_in(self.console, "BOSS")
        self.assertEqual(self.console.get("/admin/status").status_code, 200)
        store = self.site.accounts()
        try:
            store.set_admin("BOSS", False, who="CHIEF")
        finally:
            store.db.close()
        r = self.console.get("/admin/status", follow_redirects=False)
        self.assertEqual(r.status_code, 303)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class AdminAnswersTest(AdminSiteBase):
    """The admin site's headers, the API on both ports, and the players' address seen from the admin site."""

    HEADERS = {"x-frame-options": "DENY", "x-content-type-options": "nosniff", "referrer-policy": "same-origin"}

    def test_every_answer_of_the_admin_site_carries_its_headers(self):
        self.admin()
        for path in ("/signin", "/admin/status", "/nowhere", "/static/site.css", "/health", "/api/v1/status"):
            r = self.console.get(path, follow_redirects=False)
            for name, value in self.HEADERS.items():
                self.assertEqual(r.headers.get(name), value, (path, name))
        # The players' site has the frame protection alone (FramesTest), not the admin site's other headers.
        self.assertIsNone(self.client.get("/signin").headers.get("referrer-policy"))

    def test_the_api_answers_on_both_ports_with_the_same_tokens(self):
        self.admin()
        token = self.client.post("/api/v1/session", json={"login_id": "BOSS", "password": "pass1234"}).json()["token"]
        signed = {"Authorization": "Bearer " + token}
        for client in (self.client, self.console):
            r = client.get("/api/v1/server", headers=signed)
            self.assertEqual(r.status_code, 200)
        # The invite asked on the admin site's port is the players' address, never the admin site's.
        invite = self.console.get("/api/v1/server/invite", headers=signed).json()
        self.assertEqual(invite["address"], "http://192.168.0.5:4730/")

    def test_without_a_chosen_address_the_admin_site_names_the_players_site_on_its_own_host(self):
        from starlette.testclient import TestClient
        from opendmt3.server.web.app import Site, create_admin_app
        site = Site(self.tmp, admin_address=ADMIN, admin_on_site_port=False, site_port=SITE_PORT)
        console = TestClient(create_admin_app(site), base_url="http://127.0.0.1:4731", client=("127.0.0.1", 50002))
        self.admin()
        self.sign_in(console, "BOSS")
        page = console.get("/admin/status").text
        # The rail's address and the footer's way back: this host, on the players' site's port.
        self.assertIn('<a class="addr" href="http://127.0.0.1:4730/"', page)
        self.assertIn('<p><a href="http://127.0.0.1:4730/">Players&#39; site</a></p>', page)
        token = console.post("/api/v1/session", json={"login_id": "BOSS", "password": "pass1234"}).json()["token"]
        invite = console.get("/api/v1/server/invite", headers={"Authorization": "Bearer " + token}).json()
        self.assertEqual((invite["address"], invite["reached"]), ("http://127.0.0.1:4730/", False))

    def test_the_admin_pages_links_to_the_players_pages_go_to_the_players_site(self):
        boss = self.admin()
        self.make()
        self.sign_in(self.console, "BOSS")
        page = self.console.get("/admin/players/NOVA").text
        nova = self.site.accounts()
        try:
            player = nova.by_login("NOVA")["id"]
        finally:
            nova.db.close()
        self.assertIn('href="http://192.168.0.5:4730/dj/%d"' % player, page)
        self.assertIn('<p><a href="http://192.168.0.5:4730/">Players&#39; site</a></p>', page)
        self.assertNotIn('href="/dj/', page)
        self.assertTrue(boss["is_admin"])


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class FirstRunTest(AdminSiteBase):
    """The owner's first account is made on the admin site."""

    def test_the_server_pc_is_sent_to_the_admin_sites_first_run_and_signs_in_there(self):
        # The players' port: a visit from the server PC with no account goes to the admin site's first run.
        r = self.local.get("/signin", follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, ADMIN + "owner"))
        # The admin site: its own sign-in sends there too, and the page is its door.
        r = self.console.get("/signin", follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/owner"))
        page = self.console.get("/owner")
        self.assertEqual(page.status_code, 200)
        self.assertIn('<span class="s">ADMIN</span>', page.text)
        self.assertIsNotNone(self.console.cookies.get("opendmt3_admin_owner"))
        token = page.text.split('name="csrf" value="', 1)[1].split('"', 1)[0]
        r = self.console.post("/owner", data={"csrf": token, "login_id": "boss", "password": "pass1234",
                                              "dj_name": "BOSS"}, follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/signin"))
        # The admin site's door says the account was made, with the ID typed.
        door = self.console.get("/signin").text
        self.assertIn('value="BOSS"', door)
        r = self.sign_in(self.console, "BOSS")
        self.assertEqual(r.headers["location"], "/admin/status")

    def test_another_pc_never_gets_the_first_run(self):
        r = self.far_console.get("/owner", follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/signin"))
        r = self.client.get("/owner", follow_redirects=False)
        self.assertEqual(r.status_code, 404)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class WayBetweenTest(AdminSiteBase):
    """The players' footer's way to the admin pages, only where they are within reach of the visitor."""

    LINK = '<p><a href="%s">Admin pages</a></p>'

    def test_an_admin_on_the_server_pc_gets_the_admin_sites_address(self):
        self.admin()
        self.sign_in(self.local, "BOSS")
        self.assertIn(self.LINK % ADMIN, self.local.get("/").text)

    def test_an_admin_elsewhere_gets_it_only_when_the_admin_site_is_open_and_reached_straight(self):
        self.admin()
        self.sign_in(self.client, "BOSS")
        self.assertNotIn("Admin pages", self.client.get("/").text)
        self.site.admin_open = True
        # The same host the visitor used, on the admin site's port.
        self.assertIn(self.LINK % "http://testserver:4731/", self.client.get("/").text)
        # Through a proxy the visitor's host is the proxy's name, not the admin site's: no link.
        self.assertNotIn("Admin pages", self.client.get("/", headers={"X-Forwarded-For": "198.51.100.1"}).text)

    def test_a_player_never_gets_it(self):
        self.make()
        self.sign_in(self.local, "NOVA")
        self.assertNotIn("Admin pages", self.local.get("/").text)

    def test_one_port_for_everything_links_its_own_admin_pages(self):
        from starlette.testclient import TestClient
        from opendmt3.server.web.app import Site, create_app
        browser = TestClient(create_app(Site(self.tmp)), client=("203.0.113.5", 50000))
        self.admin()
        self.sign_in(browser, "BOSS")
        self.assertIn(self.LINK % "/admin", browser.get("/").text)


def at(app, address, base="http://testserver"):
    """A browser at `address` on `app`, asking for the site by `base`."""
    from starlette.testclient import TestClient
    return TestClient(app, base_url=base, client=(address, 50000))


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class LockoutTest(AdminSiteBase):
    """Each site's door counts its own wrong passwords, and the admin door never holds back the visits the server knows
    are this PC's own (the second review's V1: in Docker anyone could keep the owner out of the admin site)."""

    def test_wrong_passwords_at_one_door_never_hold_the_other(self):
        from opendmt3.server.web import app as web_app
        self.admin()
        self.make("RIO", dj="RIO")
        # The review's: ten wrong passwords for BOSS at the players' door, from anyone's addresses.
        for n in range(web_app.ID_TRIES):
            self.assertEqual(self.sign_in(at(self.app, "198.51.100.%d" % n), "BOSS", "nope1234").status_code, 401)
        # The players' door holds BOSS now; the admin door does not, from another PC of the network either.
        self.assertEqual(self.sign_in(at(self.app, "198.51.100.200"), "BOSS").status_code, 429)
        self.assertEqual(self.sign_in(self.far_console, "BOSS").status_code, 303)
        # The other way: ten wrong passwords for RIO at the admin door leave RIO's sign-in on the players' site alone.
        for n in range(web_app.ID_TRIES):
            self.sign_in(at(self.admin_app, "198.51.100.%d" % (100 + n), "http://192.168.0.5:4731"), "RIO", "nope1234")
        self.assertEqual(self.sign_in(at(self.app, "198.51.100.201"), "RIO").status_code, 303)

    def test_the_admin_door_never_holds_back_this_pcs_own_visits(self):
        from opendmt3.server.web import app as web_app
        self.admin()
        # In Docker with the admin port published on this PC's loopback alone (OPENDMT3_ADMIN_LOCAL_ONLY, which ./dmt3
        # sets when ADMIN_BIND is 127.0.0.1): every visit comes from the Docker gateway, and only this PC can make one.
        self.site.admin_local_only = True
        gateway = at(self.admin_app, "172.17.0.1", "http://127.0.0.1:4731")
        with mock.patch.object(web_app, "SIGN_INS", 1000):
            # Wrong passwords past every limit: the address's for any IDs, the ID's at the address and from anywhere.
            for n in range(web_app.ADDRESS_TRIES + web_app.ID_TRIES):
                self.assertEqual(self.sign_in(gateway, "BOSS" if n % 2 else "ID%d" % n, "nope1234").status_code, 401)
            # The owner's right password still gets in; a wrong one is still no sign-in.
            self.assertEqual(self.sign_in(gateway, "BOSS", "nope1234").status_code, 401)
            self.assertEqual(self.sign_in(gateway, "BOSS").status_code, 303)
            # Through a proxy (./dmt3 expose --admin-public) a visit is never this PC's own, whatever its address.
            proxied = at(self.admin_app, "172.17.0.1", "http://127.0.0.1:4731")
            token = self.signin_token(proxied)
            r = proxied.post("/signin", data={"csrf": token, "login_id": "BOSS", "password": "pass1234"},
                             headers={"X-Forwarded-For": "198.51.100.7"}, follow_redirects=False)
            self.assertEqual(r.status_code, 429)
            # With the admin port open to the network, the gateway is anyone's: held as any address is.
            self.site.admin_local_only = False
            self.assertEqual(self.sign_in(at(self.admin_app, "172.17.0.1", "http://127.0.0.1:4731"), "BOSS").status_code,
                             429)

    def test_compose_says_who_reaches_the_admin_pages_and_where(self):
        from opendmt3.server import __main__ as server_cli

        def settings(*argv, **env):
            args = CommandTest.parse(None, *argv, env=env)
            return (server_cli.admin_address(args), server_cli.admin_open(args), server_cli.admin_local_only(args),
                    server_cli.admin_public(args))

        with mock.patch.object(server_cli.sources, "in_container", return_value=True):
            # Compose's default: ADMIN_BIND 127.0.0.1, so this PC alone (the admin door's limits relaxed), on the PC's
            # own port for the admin pages (the listener's in the container is always 4731).
            self.assertEqual(settings(OPENDMT3_ADMIN_HOST_BIND="127.0.0.1", OPENDMT3_ADMIN_HOST_PORT="4831"),
                             ("http://127.0.0.1:4831/", False, True, None))
            # Opened to the network (ADMIN_BIND 0.0.0.0): open, no limit relaxed.
            self.assertEqual(settings(OPENDMT3_ADMIN_HOST_BIND="0.0.0.0", OPENDMT3_ADMIN_HOST_PORT="4831"),
                             ("http://127.0.0.1:4831/", True, False, None))
            # Behind Caddy (expose --admin-public): the edge's 0.0.0.0 and the public address, as it is.
            self.assertEqual(settings(OPENDMT3_ADMIN_HOST_BIND="0.0.0.0", OPENDMT3_ADMIN_HOST_PORT="4831",
                                      OPENDMT3_ADMIN_ADDRESS="https://dmt3.example:4831"),
                             ("http://127.0.0.1:4831/", True, False, "https://dmt3.example:4831/"))
            # None given (not compose): the listener's own address, never open, nothing assumed.
            self.assertEqual(settings(), ("http://127.0.0.1:4731/", False, False, None))
            # The flags say the same as the environment.
            self.assertEqual(settings("--admin-host-bind", "127.0.0.1", "--admin-host-port", "4831")[:3],
                             ("http://127.0.0.1:4831/", False, True))
        # Outside a container the listener's own address and port decide, whatever the environment says.
        with mock.patch.object(server_cli.sources, "in_container", return_value=False):
            self.assertEqual(settings(OPENDMT3_ADMIN_HOST_BIND="0.0.0.0", OPENDMT3_ADMIN_HOST_PORT="4831"),
                             ("http://127.0.0.1:4731/", False, False, None))


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class InAContainerTest(AdminSiteBase):
    """In a container the server PC's browser comes from the Docker gateway: the name it asks for (this PC's own) says
    it is the server PC, for the way to the admin site alone (the second review's V2)."""

    def setUp(self):
        super().setUp()
        from opendmt3.server.services import sources
        patch = mock.patch.object(sources, "in_container", return_value=True)
        patch.start()
        self.addCleanup(patch.stop)

    def test_this_pcs_name_goes_on_to_the_admin_site_and_shows_its_link(self):
        pc = at(self.app, "172.17.0.1", "http://127.0.0.1:4730")
        for path in ("/admin/status", "/owner"):
            r = pc.get(path, follow_redirects=False)
            self.assertEqual((r.status_code, r.headers.get("location")), (308, ADMIN.rstrip("/") + path), path)
        for name in ("localhost:4730", "[::1]:4730"):
            # The name as the browser sent it (the test client takes no IPv6 address for its own).
            r = pc.get("/admin", headers={"Host": name}, follow_redirects=False)
            self.assertEqual(r.status_code, 308, name)
        self.admin()
        self.sign_in(pc, "BOSS")
        self.assertIn(WayBetweenTest.LINK % ADMIN, pc.get("/").text)
        # Another name (this PC's address on the network) or a proxy's visit: the page that is not there, no link.
        elsewhere = at(self.app, "172.17.0.1", "http://192.168.0.5:4730")
        self.assertEqual(elsewhere.get("/admin", follow_redirects=False).status_code, 404)
        self.assertEqual(pc.get("/admin", headers={"X-Forwarded-For": "127.0.0.1"}, follow_redirects=False).status_code,
                         404)
        self.assertNotIn("Admin pages", pc.get("/", headers={"X-Real-IP": "198.51.100.1"}).text)

    def test_the_name_decides_no_sign_in_and_no_limit(self):
        from opendmt3.server.web import app as web_app
        self.admin()
        # The per-ID limit from anywhere still holds a visit that names this PC: the name is any client's to send.
        for n in range(web_app.ID_TRIES):
            self.sign_in(at(self.app, "198.51.100.%d" % n), "BOSS", "nope1234")
        self.assertEqual(self.sign_in(at(self.app, "172.17.0.1", "http://127.0.0.1:4730"), "BOSS").status_code, 429)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class OpenAdminSiteTest(AdminSiteBase):
    """The ways to an admin site opened to the network, and to one behind the proxy at its public address: every PC that
    reaches it is sent on there and linked there (in Docker ADMIN_BIND 0.0.0.0 broke 0.3.1's bookmarks otherwise)."""

    def made(self, **settings):
        from opendmt3.server.web.app import Site, create_app
        # The PC's side of the admin port as compose passes it (4831 here, the container's own being 4731).
        site = Site(self.tmp, admin_address="http://127.0.0.1:4831/", admin_on_site_port=False, site_port=SITE_PORT,
                    **settings)
        return create_app(site)

    def test_open_to_the_network_any_pc_goes_on_to_it_on_the_pcs_port(self):
        app = self.made(admin_open=True)
        other = at(app, "192.168.0.9", "http://192.168.0.5:4730")
        r = other.get("/admin/status?view=day", follow_redirects=False)
        self.assertEqual((r.status_code, r.headers.get("location")), (308, "http://192.168.0.5:4831/admin/status?view=day"))
        self.admin()
        self.sign_in(other, "BOSS")
        self.assertIn(WayBetweenTest.LINK % "http://192.168.0.5:4831/", other.get("/").text)
        # Through the proxy (the internet's, ./dmt3 expose without --admin-public): no way there, no link.
        proxied = {"X-Forwarded-For": "198.51.100.9"}
        self.assertEqual(other.get("/admin", headers=proxied, follow_redirects=False).status_code, 404)
        self.assertNotIn("Admin pages", other.get("/", headers=proxied).text)
        # This PC itself: its own address, on the PC's port.
        self.assertEqual(at(app, "127.0.0.1", "http://127.0.0.1:4730").get("/admin", follow_redirects=False)
                         .headers["location"], "http://127.0.0.1:4831/admin")

    def test_with_a_public_address_every_way_names_it_as_it_is(self):
        app = self.made(admin_open=True, admin_public="https://dmt3.example:4831/")
        self.admin()
        for client, headers in ((at(app, "127.0.0.1", "http://127.0.0.1:4730"), {}),
                                (at(app, "127.0.0.1", "http://dmt3.example"), {"X-Forwarded-For": "198.51.100.9"}),
                                (at(app, "192.168.0.9", "http://192.168.0.5:4730"), {})):
            r = client.get("/admin/players", headers=headers, follow_redirects=False)
            self.assertEqual((r.status_code, r.headers.get("location")), (308, "https://dmt3.example:4831/admin/players"))
            self.sign_in(client, "BOSS")
            self.assertIn(WayBetweenTest.LINK % "https://dmt3.example:4831/", client.get("/", headers=headers).text)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class FramesTest(AdminSiteBase):
    """No page of either site is framed by another site's, and the admin pages carry the admin site's headers whichever
    listener serves them (the second review's V4 and V5)."""

    def test_the_admin_pages_carry_their_headers_on_the_sites_port_too(self):
        from opendmt3.server.web.app import Site, create_app
        # --admin-on-site-port (Helm's admin.onPublicPort): the players' listener serves the admin pages too.
        site = Site(self.tmp, admin_address=ADMIN, admin_on_site_port=True, site_port=SITE_PORT)
        browser = at(create_app(site), "203.0.113.5")
        self.admin()
        self.sign_in(browser, "BOSS")
        for path in ("/admin", "/admin/status", "/admin/players", "/admin/players/BOSS", "/admin/nowhere"):
            r = browser.get(path, follow_redirects=False)
            for name, value in AdminAnswersTest.HEADERS.items():
                self.assertEqual(r.headers.get(name), value, (path, name))

    def test_no_page_of_the_players_site_can_be_framed(self):
        self.make()
        self.sign_in(self.client)
        for path in ("/", "/account", "/signin", "/nowhere", "/static/site.css", "/api/v1/status"):
            r = self.client.get(path, follow_redirects=False)
            self.assertEqual(r.headers.get("x-frame-options"), "DENY", path)
            self.assertIn("frame-ancestors 'none'", r.headers.get("content-security-policy", ""), path)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class OneOwnerTest(AdminSiteBase):
    """The first run makes one owner, however many of its forms come at once (the second review's V6)."""

    def test_first_run_forms_sent_at_once_make_one_owner(self):
        import threading
        page = self.console.get("/owner").text
        token = page.split('name="csrf" value="', 1)[1].split('"', 1)[0]
        codes, start = [], threading.Barrier(6)

        def post(n):
            start.wait()
            codes.append(self.console.post("/owner", data={"csrf": token, "login_id": "OWN%d" % n, "password": "pass1234"},
                                           follow_redirects=False).status_code)

        threads = [threading.Thread(target=post, args=(n,)) for n in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        store = self.site.accounts()
        try:
            made = [row["login_id"] for row in store.all()]
        finally:
            store.db.close()
        # One account, whichever came first; every form is answered (each goes on to the sign-in).
        self.assertEqual(len(made), 1, made)
        self.assertEqual(codes, [303] * 6)


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class OneUseLinkTest(AdminSiteBase):
    """The launcher's one-use sign-in links, each for the site it was made for."""

    def test_an_admin_link_opens_the_admin_site_once_and_nothing_else(self):
        boss = self.admin()
        token = self.site.once(boss["id"], admin=True)
        r = self.console.get("/signin/once/%s?lang=ko" % token, follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/admin/status"))
        self.assertIsNotNone(self.console.cookies.get("opendmt3_admin"))
        self.assertEqual(self.console.cookies.get("opendmt3_lang"), "ko")
        # Used up.
        self.console.cookies.clear()
        r = self.console.get("/signin/once/" + token, follow_redirects=False)
        self.assertEqual(r.headers["location"], "/signin")

    def test_a_link_for_one_site_is_refused_by_the_other(self):
        boss = self.admin()
        token = self.site.once(boss["id"], admin=True)
        self.assertEqual(self.local.get("/signin/once/" + token, follow_redirects=False).headers["location"], "/signin")
        token = self.site.once(boss["id"])
        self.assertEqual(self.console.get("/signin/once/" + token, follow_redirects=False).headers["location"],
                         "/signin")
        self.assertIsNone(self.console.cookies.get("opendmt3_admin"))

    def test_an_admin_link_for_a_player_or_from_another_pc_signs_nobody_in(self):
        nova = self.make()
        token = self.site.once(nova["id"], admin=True)
        self.assertEqual(self.console.get("/signin/once/" + token, follow_redirects=False).headers["location"],
                         "/signin")
        boss = self.admin()
        token = self.site.once(boss["id"], admin=True)
        self.assertEqual(self.far_console.get("/signin/once/" + token, follow_redirects=False).headers["location"],
                         "/signin")


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class DatesTest(unittest.TestCase):
    """A date never breaks inside itself on a page."""

    def test_a_date_is_joined_after_each_hyphen_and_reads_as_before(self):
        from opendmt3.server.web.app import JOINER, _when
        shown = _when(time.mktime((2026, 11, 17, 9, 30, 0, 0, 0, -1)))
        self.assertEqual(shown, "2026-%s11-%s17 09:30" % (JOINER, JOINER))
        self.assertEqual(shown.replace(JOINER, ""), "2026-11-17 09:30")
        self.assertEqual(_when(None), "")


class CommandTest(unittest.TestCase):
    """The server's command: the admin site's flags, their environment twins, and the banner's Admin row."""

    def parse(self, *argv, env=None):
        from opendmt3.server import __main__ as server_cli
        with mock.patch.dict(os.environ, env or {}, clear=False):
            for name in ("OPENDMT3_ADMIN_PORT", "OPENDMT3_ADMIN_HOST", "OPENDMT3_ADMIN_ON_SITE_PORT",
                         "OPENDMT3_ADMIN_HOST_BIND", "OPENDMT3_ADMIN_HOST_PORT", "OPENDMT3_ADMIN_ADDRESS"):
                if not env or name not in env:
                    os.environ.pop(name, None)
            return server_cli.parser().parse_args(list(argv))

    def test_the_admin_site_is_on_its_own_port_on_this_pc_unless_told_otherwise(self):
        from opendmt3.server import __main__ as server_cli
        args = self.parse()
        self.assertEqual((args.admin_port, args.admin_host, args.admin_on_site_port), (4731, "127.0.0.1", False))
        self.assertEqual(server_cli.admin_address(args), "http://127.0.0.1:4731/")
        with mock.patch.object(server_cli.sources, "in_container", return_value=False):
            self.assertFalse(server_cli.admin_open(args))
            self.assertTrue(server_cli.admin_open(self.parse("--admin-host", "0.0.0.0")))
        # In a container every address is the container's own: only the PC's mapping says who reaches it.
        with mock.patch.object(server_cli.sources, "in_container", return_value=True):
            self.assertFalse(server_cli.admin_open(self.parse("--admin-host", "0.0.0.0")))
        # Every address is this PC's loopback one too; an IPv6 address in brackets.
        self.assertEqual(server_cli.admin_address(self.parse("--admin-host", "0.0.0.0")), "http://127.0.0.1:4731/")
        self.assertEqual(server_cli.admin_address(self.parse("--admin-host", "::")), "http://[::1]:4731/")
        # 0: no admin site; no site, no admin site either.
        self.assertIsNone(server_cli.admin_address(self.parse("--admin-port", "0")))
        self.assertIsNone(server_cli.admin_address(self.parse("--web-port", "0")))

    def test_the_environment_gives_the_same_settings(self):
        args = self.parse(env={"OPENDMT3_ADMIN_PORT": "5731", "OPENDMT3_ADMIN_HOST": "0.0.0.0",
                               "OPENDMT3_ADMIN_ON_SITE_PORT": "1"})
        self.assertEqual((args.admin_port, args.admin_host, args.admin_on_site_port), (5731, "0.0.0.0", True))
        self.assertFalse(self.parse(env={"OPENDMT3_ADMIN_ON_SITE_PORT": "0"}).admin_on_site_port)

    def test_the_banner_names_the_admin_pages(self):
        from opendmt3.server import __main__ as server_cli
        with mock.patch.object(server_cli.sources, "in_container", return_value=False):
            rows = dict(server_cli.banner_rows(self.parse("--admin-port", "4831"), 4725))
            self.assertEqual(rows["Admin"], "http://127.0.0.1:4831/")
            self.assertNotIn("Admin", dict(server_cli.banner_rows(self.parse("--admin-port", "0"), 4725)))
        # In a container the server knows only its own port, never the PC's mapping of it: no row (./dmt3 names it).
        with mock.patch.object(server_cli.sources, "in_container", return_value=True):
            self.assertNotIn("Admin", dict(server_cli.banner_rows(self.parse("--admin-host", "0.0.0.0"), 4725)))
            self.assertNotIn("Admin", dict(server_cli.banner_rows(self.parse(), 4725)))
        # Its place: after this PC's address, before the game's port.
        self.assertEqual([label for label, _ in server_cli.banner.rows("http://x/", "http://y/", 4725, admin="http://z/")],
                         ["Players", "This PC", "Admin", "Game"])

    def test_the_admin_sites_server_settings(self):
        import uvicorn
        from opendmt3.server.__main__ import admin_config
        args = argparse.Namespace(admin_host="127.0.0.1", admin_port=4731, proxy="127.0.0.1")
        config = admin_config(uvicorn, object(), args)
        self.assertEqual((config.host, config.port, config.proxy_headers), ("127.0.0.1", 4731, True))


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class RealServerTest(unittest.TestCase):
    """The server's command on free ports: the players' site and the admin site both listen, each answers its health
    check, and the players' port sends the server PC on to the admin site."""

    def test_both_sites_listen_and_the_old_addresses_go_on(self):
        import httpx
        parent = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, parent, True)
        data = os.path.join(parent, "data")
        game, web, admin = free_port(), free_port(), free_port()
        env = dict(os.environ, PYTHONPATH=os.getcwd())
        env.pop("OPENDMT3_IN_CONTAINER", None)
        server = subprocess.Popen([sys.executable, "-m", "opendmt3.server", "--data", data, "--port", str(game),
                                   "--web-port", str(web), "--admin-port", str(admin)], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            for base in ("http://127.0.0.1:%d" % web, "http://127.0.0.1:%d" % admin):
                for _ in range(400):
                    try:
                        if httpx.get(base + "/health", timeout=1).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.05)
                else:
                    self.fail("%s did not answer" % base)
            r = httpx.get("http://127.0.0.1:%d/admin/status" % web)
            self.assertEqual((r.status_code, r.headers["location"]),
                             (308, "http://127.0.0.1:%d/admin/status" % admin))
            # No account yet: the admin site's first run.
            r = httpx.get("http://127.0.0.1:%d/signin" % admin)
            self.assertEqual((r.status_code, r.headers["location"]), (303, "/owner"))
            self.assertEqual(httpx.get("http://127.0.0.1:%d/owner" % admin).status_code, 200)
        finally:
            server.terminate()
            out, _ = server.communicate(timeout=30)
        said = out.decode("utf-8", "replace")
        # The banner names the admin site and its first run on a PC of its own; in a container (CI's jobs run in one:
        # /.dockerenv, which the server reads as the test does) the PC's port is not the server's to know, and no
        # visit is the server PC's: neither line (sources.in_container, the child's environment without its variable).
        if os.path.exists("/.dockerenv"):
            self.assertNotIn("Admin  ", said)
            self.assertNotIn("First start", said)
        else:
            self.assertIn("Admin     http://127.0.0.1:%d/" % admin, said)
            self.assertIn("First start: open http://127.0.0.1:%d/ on this PC" % admin, said)


if __name__ == "__main__":
    unittest.main()
