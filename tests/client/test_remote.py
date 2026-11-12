"""The launcher against a real openDMT3 site (in this process, on a free port): finding it, signing in, the
answers to a wrong address or password. Needs the web libraries; skipped without them."""

import importlib.util
import shutil
import socket
import tempfile
import threading
import time
import unittest

from opendmt3.client import remote

WEB = all(importlib.util.find_spec(m) for m in ("starlette", "jinja2", "uvicorn", "multipart"))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(WEB, "needs starlette, jinja2, uvicorn and python-multipart")
class RemoteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import uvicorn
        from opendmt3.server.web.app import Site, create_app
        cls.tmp = tempfile.mkdtemp()
        cls.site = Site(cls.tmp, game_port=24725)
        store = cls.site.accounts()
        cls.row = store.create("NOVA", "pass1234", "DJ NOVA")
        # The server's admin, who may send it a song list.
        store.create("BOSS", "pass1234", "BOSS", is_admin=True)
        store.db.close()
        cls.port = free_port()
        cls.server = uvicorn.Server(uvicorn.Config(create_app(cls.site), host="127.0.0.1", port=cls.port,
                                                   log_level="error"))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        end = time.time() + 10
        while not cls.server.started and time.time() < end:
            time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(5)
        shutil.rmtree(cls.tmp)

    def test_addresses_are_completed(self):
        self.assertEqual(remote.normalize("192.168.0.10"), "http://192.168.0.10:4730")
        self.assertEqual(remote.normalize("https://dmt.example/"), "https://dmt.example:4730")
        self.assertEqual(remote.normalize("10.0.0.5:8000"), "http://10.0.0.5:8000")
        # The address a site behind a TLS proxy shows on its Download page.
        self.assertEqual(remote.normalize("dmt.example:443"), "https://dmt.example:443")
        self.assertEqual(remote.normalize("http://dmt.example:443"), "http://dmt.example:443")
        with self.assertRaises(remote.RemoteError):
            remote.normalize("  ")

    def test_status_names_the_game_address(self):
        found = remote.status("http://127.0.0.1:%d" % self.port)
        # The game goes to the same host as the site, on the game port the server reports.
        self.assertEqual(found["game"], "127.0.0.1:24725")

    def test_sign_in_brings_the_card(self):
        me = remote.sign_in("http://127.0.0.1:%d" % self.port, "nova", "pass1234")
        self.assertEqual((me["dj_name"], me["card"]), ("DJ NOVA", self.row["card"]))

    def test_wrong_password_and_no_server_are_worded(self):
        with self.assertRaises(remote.RemoteError) as e:
            remote.sign_in("http://127.0.0.1:%d" % self.port, "NOVA", "wrong123")
        self.assertIn("do not match", str(e.exception))
        with self.assertRaises(remote.RemoteError) as e:
            remote.status("http://127.0.0.1:%d" % free_port())
        # What to do, with no word of the system's own reason ("[Errno 111] Connection refused").
        self.assertEqual(str(e.exception), "Cannot reach http://127.0.0.1:%d. Check the address and the network."
                         % int(str(e.exception).split(":")[2].split(".")[0]))
        self.assertNotIn("Errno", str(e.exception))

    def test_signing_out_ends_that_launchers_token_only(self):
        base = "http://127.0.0.1:%d" % self.port
        # Two launchers signed in to the same account (two PCs): each token is its own.
        here = remote.sign_in(base, "NOVA", "pass1234")["token"]
        there = remote.sign_in(base, "NOVA", "pass1234")["token"]
        self.assertNotEqual(here, there)
        self.assertTrue(remote.sign_out(base, here))
        # The token signed out no longer works, wherever a copy of it is; the other PC's goes on.
        with self.assertRaises(remote.RemoteError) as e:
            remote.me(base, here)
        self.assertEqual(e.exception.code, "sign_in")
        self.assertEqual(remote.me(base, there)["login_id"], "NOVA")
        # Signed out already: the server no longer takes it, and the call says so without raising.
        self.assertFalse(remote.sign_out(base, here))

    def test_an_admin_sends_the_song_list_and_a_player_cannot(self):
        import os
        from opendmt3.client import i18n
        from opendmt3.server.services import catalog
        from tests.server.test_site_features import small_song_list
        base = "http://127.0.0.1:%d" % self.port
        path = small_song_list(os.path.join(self.tmp, "sent.zip"), songs=4)
        admin = remote.sign_in(base, "BOSS", "pass1234")
        # Signing in says whether the account is the server's admin (the Game page offers the send then).
        self.assertIs(admin["is_admin"], True)
        answer = remote.send_song_list(base, admin["token"], path)
        self.assertEqual(answer["song_list"]["songs"]["count"], 4)
        self.assertEqual(answer["lines"][0], "song list: 4 songs")
        self.assertEqual(len(catalog.load(self.tmp)), 4)
        # A player's token is refused, in the launcher's own words.
        player = remote.sign_in(base, "NOVA", "pass1234")
        with self.assertRaises(remote.RemoteError) as e:
            remote.send_song_list(base, player["token"], path)
        self.assertEqual(e.exception.code, "admin_only")
        self.assertEqual(i18n.Words("ko").error(e.exception), "이 서버의 관리자만 곡 목록을 보낼 수 있습니다.")
        # A file that is no song list is refused with the server's reason.
        bad = os.path.join(self.tmp, "bad.zip")
        with open(bad, "wb") as f:
            f.write(b"not a zip")
        with self.assertRaises(remote.RemoteError) as e:
            remote.send_song_list(base, admin["token"], bad)
        self.assertEqual((e.exception.code, str(e.exception)), ("refused", "This is not a song list saved by openDMT3."))

    def test_signing_out_of_a_server_that_is_not_there_never_raises(self):
        started = time.monotonic()
        self.assertFalse(remote.sign_out("http://127.0.0.1:%d" % free_port(), "a-token"))
        self.assertLess(time.monotonic() - started, remote.SIGN_OUT_TIMEOUT + 1)



class StrangerServerTest(unittest.TestCase):
    """The launcher against a server that does not answer as openDMT3 does: it sends the player elsewhere, answers
    without end, or hands over a card number the card reader would not take. Nothing of it is followed, read whole
    or kept."""

    @classmethod
    def setUpClass(cls):
        import json
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        cls.seen = []
        answers = {
            "/api/v1/me": (302, None, "http://localhost:{other}/api/v1/me"),
            "/api/v1/status": (302, None, "/api/v1/status-moved"),
            "/api/v1/status-moved": (200, {"server": "openDMT3", "game_port": 4725}, None),
            "/big/api/v1/status": (200, b"{" + b" " * (remote.ANSWER_LIMIT + 10) + b"}", None),
            "/list/api/v1/status": (200, [1, 2, 3], None),
            "/port/api/v1/status": (200, {"server": "openDMT3", "game_port": "4725; x"}, None),
            "/card/api/v1/me": (200, {"login_id": "NOVA", "dj_name": "DJ", "card": "1234\r\nserverip=6.6.6.6"}, None),
            "/token/api/v1/session": (200, {"login_id": "NOVA", "dj_name": "DJ", "card": "12345", "token": 7}, None),
            # An openDMT3 server from before DELETE /api/v1/session: the path takes POST only.
            "/old/api/v1/session": (405, {"error": {"code": "method_not_allowed",
                                                    "message": "this path does not take DELETE"}}, None),
        }

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                # Every request with the token it carried, by the host it reached.
                cls.seen.append((self.headers.get("Host"), self.path, self.headers.get("Authorization")))
                code, body, where = answers.get(self.path, (404, {"error": {"code": "x", "message": "no"}}, None))
                self.send_response(code)
                if where:
                    self.send_header("Location", where.format(other=cls.other_port))
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_POST = do_GET
            do_DELETE = do_GET

            def log_message(self, *args):
                pass

        cls.servers = [ThreadingHTTPServer(("127.0.0.1", 0), Handler) for _ in range(2)]
        cls.port, cls.other_port = (srv.server_address[1] for srv in cls.servers)
        for srv in cls.servers:
            threading.Thread(target=srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        for srv in cls.servers:
            srv.shutdown()
            srv.server_close()

    def base(self, prefix=""):
        return "http://127.0.0.1:%d%s" % (self.port, prefix)

    def test_the_token_never_follows_a_redirect_to_another_host(self):
        with self.assertRaises(remote.RemoteError):
            remote.me(self.base(), "the-players-token")
        # The other host never heard of it.
        self.assertFalse([s for s in self.seen if s[0] and s[0].startswith("localhost")])

    def test_a_redirect_on_the_same_host_is_followed(self):
        self.assertEqual(remote.status(self.base())["game"], "127.0.0.1:4725")

    def test_signing_out_of_an_older_or_another_server_never_raises(self):
        # An openDMT3 server older than the call (405), and a server that is not openDMT3 (404): False, no error, so
        # the launcher forgets the sign-in all the same.
        self.assertFalse(remote.sign_out(self.base("/old"), "the-players-token"))
        self.assertFalse(remote.sign_out(self.base(), "the-players-token"))

    def test_answers_that_are_not_openDMT3_answers_are_refused(self):
        for prefix in ("/big", "/list", "/port"):
            with self.assertRaises(remote.RemoteError) as e:
                remote.status(self.base(prefix))
            self.assertEqual(e.exception.key, "error.remote.not_an_answer", prefix)
        # A card number that would write more than a number into the game folder, and a token that is not text.
        with self.assertRaises(remote.RemoteError):
            remote.me(self.base("/card"), "t")
        with self.assertRaises(remote.RemoteError):
            remote.sign_in(self.base("/token"), "NOVA", "pass1234")


class OpenerTest(unittest.TestCase):
    def test_the_certificates_load_with_the_first_call_not_at_import(self):
        # Every launcher start imports this module (main.py reads an installer's server with it); most starts call no
        # server. In a fresh Python: nothing made at import, then one opener for every call.
        import subprocess
        import sys
        code = ("import ssl\n"
                "made = []\n"
                "real = ssl.create_default_context\n"
                "ssl.create_default_context = lambda *a, **k: made.append(1) or real(*a, **k)\n"
                "from opendmt3.client import remote\n"
                "print(remote._OPENER is None, len(made))\n"
                "first = remote._opener()\n"
                "print(first is remote._opener(), type(first).__name__)\n")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.stdout.split(), ["True", "0", "True", "OpenerDirector"], out.stderr)


if __name__ == "__main__":
    unittest.main()
