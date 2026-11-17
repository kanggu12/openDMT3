"""The connection test (client/server_test.py) and its command-line twin (--test-server) against made-up servers in
this process: one that passes every step, one nothing answers at, one of another openDMT3 version, one whose game
port is closed, and one that no longer takes the launcher's token. Plain http.server: no web libraries needed."""

import contextlib
import io
import json
import os
import socket
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from opendmt3 import __version__
from opendmt3.client import i18n, server_test
from opendmt3.client import state as st


def free_port():
    """A port nothing listens on (bound and let go at once)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class MadeUpServer:
    """A made-up openDMT3 site: /health with its version, /api/v1/status with its game port and its name, /api/v1/me
    taking one token (every Authorization it was sent kept in `sent`), a sign-in that refuses BOB as banned; and, when
    asked, something listening on the game port."""

    def __init__(self, version=__version__, game_open=True, token="good", name="openDMT3"):
        self.version, self.token, self.name, self.sent = version, token, name, []
        # The game's port: a listening socket while it is open; closed, a socket bound to it that does not listen, so
        # a connection is refused and no other test running at the same time can take the port meanwhile.
        self.game = socket.socket()
        self.game.bind(("127.0.0.1", 0))
        if game_open:
            self.game.listen(4)
        self.game_port = self.game.getsockname()[1]
        made = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                # Quiet: the test's output is the steps.
                pass

            def answer(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/health":
                    self.answer(200, {"ok": True, "version": made.version})
                elif self.path == "/api/v1/status":
                    self.answer(200, {"server": made.name, "version": made.version, "game_port": made.game_port})
                elif self.path == "/api/v1/me":
                    # What it was sent, kept: a token another server made must never come here.
                    made.sent.append(self.headers.get("Authorization"))
                    if self.headers.get("Authorization") == "Bearer " + made.token:
                        self.answer(200, {"login_id": "NOVA", "dj_name": "DJ NOVA", "card": None, "is_admin": False})
                    else:
                        self.answer(401, {"error": {"code": "sign_in", "message": "sign in again"}})
                else:
                    self.answer(404, {"error": {"code": "not_found", "message": "no such page"}})

            def do_POST(self):
                # The sign-in: BOB is banned, with the reason the admin wrote; anyone else signs in.
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if self.path != "/api/v1/session":
                    self.answer(404, {"error": {"code": "not_found", "message": "no such page"}})
                elif body.get("login_id") == "BOB":
                    self.answer(403, {"error": {"code": "banned", "message": "this account is banned",
                                                "reason": "Made-up reason"}})
                else:
                    self.answer(200, {"login_id": body.get("login_id"), "dj_name": "DJ NOVA", "card": "12345678",
                                      "is_admin": False, "token": made.token})

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.http.server_address[1]
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def close(self):
        self.http.shutdown()
        self.http.server_close()
        self.game.close()


class NotASite:
    """What the game's port answers a browser: bytes that are no HTTP (the game server sends its seed first), on a
    line of their own, then nothing more until the caller goes. With `answer` and `close`, any other bytes, the
    connection closed after them (an answer cut short)."""

    def __init__(self, answer=b"\xc2\xfavU \xe8O\xec|1e\xe5\r\n", close=False):
        self.answer, self.close_after = answer, close
        self.listening = socket.socket()
        self.listening.bind(("127.0.0.1", 0))
        self.listening.listen(4)
        self.url = "http://127.0.0.1:%d" % self.listening.getsockname()[1]
        self.links = []
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                link, _ = self.listening.accept()
            except OSError:
                # Closed: the test is over.
                return
            self.links.append(link)
            if self.close_after:
                # The request read first, so the close after the answer is a clean end, never a reset.
                link.recv(65536)
            # A seed's made-up bytes, as a status line would never be (or the answer given).
            link.sendall(self.answer)
            if self.close_after:
                link.close()

    def close(self):
        self.listening.close()
        for link in self.links:
            link.close()


def signed(url, token):
    """The launcher's state, connected to `url` and signed in there with `token` (None: no state at all)."""
    if token is None:
        return None
    state = st.LauncherState()
    state.mode, state.server_url, state.remote = "server", url, {"token": token, "login_id": "NOVA"}
    return state


class ServerTestTest(unittest.TestCase):
    def run_against(self, **kw):
        server = MadeUpServer(**{k: v for k, v in kw.items() if k != "token_sent"})
        self.addCleanup(server.close)
        seen = []
        steps = server_test.run(server.url, signed(server.url, kw.get("token_sent")),
                                report=lambda s: seen.append([x.state for x in s]))
        return server, steps, seen

    def states(self, steps):
        return [s.state for s in steps]

    def test_every_step_passes_on_a_server_that_works(self):
        server, steps, seen = self.run_against(token_sent="good")
        self.assertEqual(self.states(steps), ["ok"] * 4)
        # Each step's time, and what it found in words both languages have.
        self.assertTrue(all(isinstance(s.ms, int) and s.ms >= 0 for s in steps))
        for language in ("en", "ko"):
            w = i18n.Words(language)
            text = server_test.as_text(steps, w)
            self.assertIn(str(server.game_port), text)
            self.assertIn(w("server_test.passed"), text)
        self.assertEqual(server_test.exit_code(steps), 0)
        # The window saw each step running, then done, one after another.
        self.assertIn(["ok", "running", "waiting", "waiting"], seen)

    def test_no_sign_in_is_not_a_failure(self):
        _server, steps, _seen = self.run_against()
        self.assertEqual(self.states(steps), ["ok", "ok", "ok", "not_run"])
        self.assertEqual(steps[3].said[0], "server_test.sign_in.none")
        self.assertTrue(server_test.passed(steps))

    def test_nothing_answering_stops_at_the_site(self):
        steps = server_test.run("http://127.0.0.1:%d" % free_port(), None, timeout=2)
        self.assertEqual(self.states(steps), ["ok", "failed", "not_run", "not_run"])
        self.assertEqual(steps[1].said[0], "server_test.site.none")
        self.assertEqual(steps[1].fix[0], "server_test.site.none.fix")
        self.assertEqual(server_test.exit_code(steps), 3)

    def test_a_name_that_does_not_resolve_stops_at_the_address(self):
        def nowhere(*args, **kw):
            raise socket.gaierror("no such name")

        steps = server_test.run("dmt3.invalid", None, resolve=nowhere)
        self.assertEqual(self.states(steps), ["failed", "not_run", "not_run", "not_run"])
        self.assertEqual((steps[0].said[0], steps[0].said[1]["host"]), ("server_test.address.unknown", "dmt3.invalid"))
        self.assertEqual(server_test.exit_code(steps), 2)
        # Not an address at all.
        self.assertEqual(server_test.run("   ", None)[0].said[0], "server_test.address.bad")

    def test_another_version_says_which_to_update(self):
        _server, steps, _seen = self.run_against(version="9.9.0")
        self.assertEqual(self.states(steps), ["ok", "failed", "not_run", "not_run"])
        self.assertEqual(steps[1].said, ("server_test.site.version", {"server": "9.9.0", "launcher": __version__}))
        # A newer server: this launcher is the one to update.
        self.assertEqual(steps[1].fix[0], "server_test.site.version.fix.newer")
        _server, steps, _seen = self.run_against(version="0.0.1")
        self.assertEqual(steps[1].fix[0], "server_test.site.version.fix.older")

    def test_a_closed_game_port_names_the_port_to_open(self):
        server, steps, _seen = self.run_against(game_open=False, token_sent="good")
        self.assertEqual(self.states(steps), ["ok", "ok", "failed", "not_run"])
        self.assertEqual(steps[2].fix, ("server_test.game.closed.fix", {"port": server.game_port}))
        self.assertEqual(server_test.exit_code(steps), 4)

    def test_a_token_the_server_no_longer_takes(self):
        _server, steps, _seen = self.run_against(token_sent="old")
        self.assertEqual(self.states(steps), ["ok", "ok", "ok", "failed"])
        self.assertEqual(steps[3].said[0], "server_test.sign_in.gone")
        self.assertEqual(server_test.exit_code(steps), 5)

    def test_the_kept_sign_in_goes_only_to_the_server_it_was_made_on(self):
        first, other = MadeUpServer(), MadeUpServer()
        for server in (first, other):
            self.addCleanup(server.close)
        # Signed in to the first: its token kept with its address.
        state = signed(first.url, "good")
        # The other typed: the first's token never goes there, and the sign-in is not tested.
        steps = server_test.run(other.url, state)
        self.assertEqual(self.states(steps), ["ok", "ok", "ok", "not_run"])
        self.assertEqual(other.sent, [])
        # The first, typed as a player types it (no scheme, a slash at its end): the same server, its sign-in tested.
        steps = server_test.run(first.url.split("://", 1)[1] + "/", state)
        self.assertEqual(self.states(steps), ["ok"] * 4)
        self.assertEqual(first.sent, ["Bearer good"])
        # The window hands the test its state and keeps no rule of its own: the one above is both's.
        top = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        with open(os.path.join(top, "opendmt3", "client", "pages", "online.py"), encoding="utf-8") as f:
            # The test's card alone (its sign-out elsewhere on the page sends the token to its own server).
            window = f.read().split("def test_card(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("server_test.run(address_typed, app.state, report)", window)
        self.assertNotIn('.get("token")', window)

    def test_an_address_that_answers_but_is_no_site_stops_at_the_site(self):
        from opendmt3.client import remote
        # The game's port typed for the site's: what answers is no HTTP.
        game = NotASite()
        self.addCleanup(game.close)
        steps = server_test.run(game.url, None, timeout=2)
        self.assertEqual(self.states(steps), ["ok", "failed", "not_run", "not_run"])
        self.assertEqual(steps[1].said, ("server_test.site.not_a_site", {"base": game.url}))
        self.assertEqual(steps[1].fix[0], "server_test.site.not_a_site.fix")
        self.assertEqual(server_test.exit_code(steps), 3)
        # Connect says it in its words too, never the bytes that came.
        with self.assertRaises(remote.RemoteError) as caught:
            remote.status(game.url)
        self.assertEqual(caught.exception.key, "error.remote.not_a_site")
        self.assertNotIn("\xe8", i18n.Words("en").error(caught.exception))

    def test_an_error_whose_answer_is_cut_short_is_said_in_words(self):
        from opendmt3.client import remote
        # An HTTP error whose body comes in chunks, the first said to be 16 bytes, then the connection ends after a few:
        # reading it is no answer either.
        cut = NotASite(answer=b"HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\nTransfer-Encoding: "
                              b"chunked\r\n\r\n10\r\n{\"err", close=True)
        self.addCleanup(cut.close)
        with self.assertRaises(remote.RemoteError) as caught:
            remote.status(cut.url)
        self.assertEqual((caught.exception.key, caught.exception.params), ("error.remote.answered", {"status": 400}))
        steps = server_test.run(cut.url, None, timeout=2)
        self.assertEqual((self.states(steps), steps[1].said[0]), (["ok", "failed", "not_run", "not_run"],
                                                                  "server_test.site.other"))

    def test_a_step_that_breaks_fails_where_it_was_and_never_passes(self):
        with mock.patch.object(server_test, "_get", side_effect=RuntimeError("made-up")):
            steps = server_test.run("http://127.0.0.1:1", None)
        self.assertEqual(self.states(steps), ["ok", "failed", "not_run", "not_run"])
        self.assertFalse(server_test.passed(steps))
        self.assertEqual(server_test.exit_code(steps), 3)

    def test_the_games_port_is_tried_at_every_address_of_the_name_ipv4_first(self):
        server = MadeUpServer()
        self.addCleanup(server.close)
        tried = []

        def resolve(host, port, type=0):
            # IPv6 first, as Windows answers for localhost, and as a name with both kinds of address may be answered.
            return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", port, 0, 0)),
                    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

        def connect_at(*good):
            def connect(address, timeout):
                tried.append(address[0])
                if address[0] not in good:
                    raise ConnectionRefusedError(111, "refused")
                return socket.create_connection(("127.0.0.1", address[1]), timeout)
            return connect

        # The server listens on IPv4 alone (0.0.0.0, its default): the game's address, the one IPv4 gives, passes.
        steps = server_test.run(server.url, None, resolve=resolve, connect=connect_at("127.0.0.1"))
        self.assertEqual(self.states(steps), ["ok", "ok", "ok", "not_run"])
        self.assertEqual((steps[0].said[1]["ip"], steps[2].said[1]["ip"], tried), ("127.0.0.1", "127.0.0.1",
                                                                                 ["127.0.0.1"]))
        # Only IPv6 takes it: tried after IPv4, and named the way an address with a port is written.
        del tried[:]
        steps = server_test.run(server.url, None, resolve=resolve, connect=connect_at("::1"))
        self.assertEqual(self.states(steps)[2], "ok")
        self.assertEqual((steps[2].said[1]["ip"], tried), ("[::1]", ["127.0.0.1", "::1"]))
        # None takes it: the step fails at the first address tried, the one the game uses.
        steps = server_test.run(server.url, None, resolve=resolve, connect=connect_at())
        self.assertEqual(steps[2].said, ("server_test.game.closed", {"ip": "127.0.0.1", "port": server.game_port}))

    def test_a_site_that_is_no_opendmt3_server_stops_at_the_site(self):
        from opendmt3.client import remote
        # A look-alike: its health and version are an openDMT3 site's, its status says it is another server.
        _server, steps, _seen = self.run_against(name="Made-up look-alike", token_sent="good")
        self.assertEqual(self.states(steps), ["ok", "failed", "not_run", "not_run"])
        self.assertEqual(steps[1].said[0], "server_test.site.other")
        self.assertEqual(server_test.exit_code(steps), 3)
        # Connect refuses it with the same check.
        with self.assertRaises(remote.RemoteError) as caught:
            remote.status(_server.url)
        self.assertEqual(caught.exception.key, "error.remote.not_opendmt3")

    def test_every_step_has_its_words_in_both_languages(self):
        for key in [k for k in i18n.TEXT if k.startswith("server_test.")]:
            english, korean = i18n.TEXT[key]
            self.assertTrue(english and korean, key)
            # Plain words of what happened and what to do: no warning words (the product gives none).
            self.assertNotIn("warning", english.lower(), key)


class CommandLineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        patcher = mock.patch.dict(os.environ, {"OPENDMT3_CONFIG_DIR": self.tmp})
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, *argv, state=None):
        from opendmt3.client import cli
        args = cli.parse(list(argv))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.run_jobs(args, state or st.LauncherState(), lambda *a, **k: 1)
        return code, out.getvalue(), err.getvalue()

    def test_the_command_line_says_each_step_and_exits_by_the_failed_one(self):
        server = MadeUpServer(game_open=False)
        self.addCleanup(server.close)
        code, out, err = self.run_cli("--test-server", server.url)
        self.assertEqual(code, 4)
        # A line a step that ran, the game's port among the failed lines with what to do.
        self.assertIn("Address", out)
        self.assertIn(str(server.game_port), err)
        # The step's name inside the sentence as words in a sentence are.
        self.assertIn("Stopped at the game's port.", err)

    def test_the_server_in_use_with_its_sign_in(self):
        server = MadeUpServer()
        self.addCleanup(server.close)
        state = st.LauncherState()
        state.mode, state.server_url, state.remote = "server", server.url, {"token": "good", "login_id": "NOVA"}
        code, out, _err = self.run_cli("--test-server", state=state)
        self.assertEqual(code, 0)
        self.assertIn("Signed in as DJ NOVA (NOVA).", out)

    def test_no_server_to_test(self):
        code, _out, err = self.run_cli("--test-server")
        self.assertEqual(code, 2)
        self.assertIn("No server to test", err)

    def test_the_games_port_typed_for_the_site_is_said_and_stops_at_the_site(self):
        game = NotASite()
        self.addCleanup(game.close)
        code, _out, err = self.run_cli("--test-server", game.url)
        # The site's step, in words: no traceback, and no bytes of what answered.
        self.assertEqual(code, 3)
        self.assertIn("answers, but not as a site does", err)
        self.assertNotIn("Traceback", err)

    def test_a_server_given_with_the_test_is_connected_to_first(self):
        server = MadeUpServer()
        self.addCleanup(server.close)
        state = st.LauncherState()
        code, out, err = self.run_cli("--server", server.url, "--test-server", state=state)
        self.assertEqual(code, 0, err)
        self.assertIn("Connected to %s" % server.url, out)
        self.assertIn("Every step passed", out)
        self.assertEqual(state.server_url, server.url)

    def test_the_command_lines_fixes_name_its_own_flags(self):
        # A sign-in the server no longer takes: sign in again with --sign-in, never on the window's card.
        server = MadeUpServer()
        self.addCleanup(server.close)
        code, _out, err = self.run_cli("--test-server", state=signed(server.url, "old"))
        self.assertEqual(code, 5)
        self.assertIn("--sign-in", err)
        self.assertNotIn("card", err)
        # A newer server: this launcher is updated with --update, not on the window's LAUNCHER page.
        newer = MadeUpServer(version="9.9.0")
        self.addCleanup(newer.close)
        code, _out, err = self.run_cli("--test-server", newer.url)
        self.assertEqual(code, 3)
        self.assertIn("--update", err)
        self.assertNotIn("page", err)

    def test_signing_in_to_a_banned_account_says_the_reason(self):
        server = MadeUpServer()
        self.addCleanup(server.close)
        state = st.LauncherState()
        state.mode, state.server_url = "server", server.url
        with mock.patch("sys.stdin", io.StringIO("pass1234\n")):
            code, _out, err = self.run_cli("--sign-in", "BOB", state=state)
        # The window's words, with the reason the admin gave.
        self.assertEqual(code, 2)
        self.assertIn("This account is banned on this server. The reason: Made-up reason", err)
