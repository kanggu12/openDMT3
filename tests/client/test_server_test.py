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
    """A made-up openDMT3 site: /health with its version, /api/v1/status with its game port, /api/v1/me taking
    one token; and, when asked, something listening on the game port."""

    def __init__(self, version=__version__, game_open=True, token="good"):
        self.version, self.token = version, token
        # The game's port: a listening socket while it is open, else a port nothing listens on.
        self.game = None
        if game_open:
            self.game = socket.socket()
            self.game.bind(("127.0.0.1", 0))
            self.game.listen(4)
            self.game_port = self.game.getsockname()[1]
        else:
            self.game_port = free_port()
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
                    self.answer(200, {"server": "openDMT3", "version": made.version, "game_port": made.game_port})
                elif self.path == "/api/v1/me":
                    if self.headers.get("Authorization") == "Bearer " + made.token:
                        self.answer(200, {"login_id": "NOVA", "dj_name": "DJ NOVA", "card": None, "is_admin": False})
                    else:
                        self.answer(401, {"error": {"code": "sign_in", "message": "sign in again"}})
                else:
                    self.answer(404, {"error": {"code": "not_found", "message": "no such page"}})

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.http.server_address[1]
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def close(self):
        self.http.shutdown()
        self.http.server_close()
        if self.game is not None:
            self.game.close()


class ServerTestTest(unittest.TestCase):
    def run_against(self, **kw):
        server = MadeUpServer(**{k: v for k, v in kw.items() if k != "token_sent"})
        self.addCleanup(server.close)
        seen = []
        steps = server_test.run(server.url, kw.get("token_sent"), report=lambda s: seen.append([x.state for x in s]))
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
        self.assertIn("Stopped at The game's port.", err)

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
