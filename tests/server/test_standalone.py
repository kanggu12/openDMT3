"""The server on a PC of its own (opendmt3/server/standalone.py, the Windows server package's opendmt3-server.exe) and
the Caddyfile its expose and ./dmt3 expose write (opendmt3/server/edge.py): the settings a run starts with, the
firewall's commands, and a real start, status and stop on free ports in a folder of the test's own."""

import contextlib
import io
import json
import os
import socket
import sys
import tempfile
import unittest
import urllib.request
from unittest import mock

from opendmt3.server import edge, standalone
from tests.server.test_web import WEB


def quiet(*argv):
    """standalone.main with these arguments, its output kept: (exit code, what it printed)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = standalone.main(list(argv))
    return code, out.getvalue()


def free_port():
    """A TCP port nothing listens on now."""
    with contextlib.closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class SettingsTest(unittest.TestCase):
    def setUp(self):
        # The data folder inside a folder of the test's own: a removal keeps its last backup beside it.
        base = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, base)
        self.data = os.path.join(base, "data")
        os.makedirs(self.data)

    def test_a_new_data_folder_runs_on_the_usual_ports_for_every_pc(self):
        # This PC's address on its network stands in for the players' address until one is kept.
        with mock.patch.object(standalone, "lan_addresses", return_value=["192.168.0.7"]):
            argv = standalone.server_args(self.data)
        self.assertEqual(argv, ["--data", self.data, "--host", "0.0.0.0", "--port", "4725", "--web-port", "4730",
                                "--site-address", "http://192.168.0.7:4730/"])
        # A PC with no network: no address for players is made up.
        with mock.patch.object(standalone, "lan_addresses", return_value=[]):
            self.assertNotIn("--site-address", standalone.server_args(self.data))

    def test_setup_keeps_the_address_and_the_ports(self):
        code, _ = quiet("--data", self.data, "setup", "--address", "192.168.0.5", "--web-port", "14830")
        self.assertEqual(code, 0)
        kept = standalone.settings(self.data)
        # An address alone gets the site's port, and the last slash, as a browser shows it.
        self.assertEqual(kept["site_address"], "http://192.168.0.5:14830/")
        self.assertIn("--site-address", standalone.server_args(self.data))
        self.assertEqual(standalone.players_address(self.data), "http://192.168.0.5:14830/")

    def test_setup_makes_the_first_account_only(self):
        code, said = quiet("--data", self.data, "setup", "--admin", "boss", "--password", "pass1234")
        self.assertEqual(code, 0)
        self.assertIn("made BOSS", said)
        self.assertFalse(standalone.first_account_needed(self.data))
        code, said = quiet("--data", self.data, "setup", "--admin", "OTHER")
        self.assertIn("no first account is made", said)

    def test_the_installer_goes_into_the_downloads_folder(self):
        installer = os.path.join(self.data, "setup.exe")
        with open(installer, "wb") as f:
            f.write(b"MZ")
        self.assertEqual(quiet("--data", self.data, "setup", "--installer", installer)[0], 0)
        self.assertTrue(os.path.isfile(os.path.join(self.data, "downloads", standalone.INSTALLER)))
        self.assertEqual(quiet("--data", self.data, "setup", "--installer", installer + ".none")[0], 2)

    def test_the_bundled_installer_fills_an_empty_downloads_folder_only(self):
        package = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, package)
        os.makedirs(os.path.join(package, standalone.BUNDLED_INSTALLER))
        with open(os.path.join(package, standalone.BUNDLED_INSTALLER, "opendmt3-launcher-1.2.3-windows-x64-setup.exe"),
                  "wb") as f:
            f.write(b"MZ bundled")
        with mock.patch.object(standalone, "package_folder", return_value=package):
            self.assertEqual(standalone.hand_out_bundled(self.data), "opendmt3-launcher-1.2.3-windows-x64-setup.exe")
            put = os.path.join(self.data, "downloads", standalone.INSTALLER)
            with open(put, "wb") as f:
                f.write(b"MZ the owner's")
            # One there already (the owner's) stays.
            self.assertIsNone(standalone.hand_out_bundled(self.data))
        with open(put, "rb") as f:
            self.assertEqual(f.read(), b"MZ the owner's")

    def test_expose_puts_the_site_behind_the_proxy_and_off_takes_it_back(self):
        code, said = quiet("--data", self.data, "expose", "dmt3.example.org", "--email", "owner@example.org")
        self.assertEqual(code, 0, said)
        argv = standalone.server_args(self.data)
        # The site on this PC only, its forwarded headers believed from this PC's own address, the address HTTPS.
        self.assertEqual(argv[argv.index("--web-host") + 1], "127.0.0.1")
        self.assertEqual(argv[argv.index("--proxy") + 1], "127.0.0.1")
        self.assertEqual(argv[argv.index("--site-address") + 1], "https://dmt3.example.org/")
        with open(os.path.join(self.data, "Caddyfile"), encoding="utf-8") as f:
            caddy = f.read()
        self.assertIn("dmt3.example.org {", caddy)
        self.assertIn("reverse_proxy 127.0.0.1:4730", caddy)
        self.assertIn("email owner@example.org", caddy)
        self.assertEqual(quiet("--data", self.data, "expose", "--off")[0], 0)
        self.assertNotIn("--proxy", standalone.server_args(self.data))
        # A name no authority signs is refused in one line.
        self.assertEqual(quiet("--data", self.data, "expose", "192.168.0.5")[0], 2)

    def test_the_firewall_opens_each_port_by_a_rule_of_its_own(self):
        commands = standalone.firewall_commands([4725, 4730])
        # Each rule's name taken out first, then added: a second run leaves one rule a port.
        self.assertEqual([c[3] for c in commands], ["delete", "add", "delete", "add"])
        add = commands[1]
        self.assertEqual(add[:4], ["netsh", "advfirewall", "firewall", "add"])
        self.assertIn("name=openDMT3 server (TCP 4725)", add)
        self.assertIn("localport=4725", add)
        self.assertIn("profile=private,domain", add)
        self.assertIn("profile=private,domain,public", standalone.firewall_commands([4725], public=True)[1])
        self.assertEqual([c[3] for c in standalone.firewall_commands([4725], remove=True)], ["delete"])

    def test_the_firewall_elsewhere_prints_the_commands(self):
        if os.name == "nt":
            self.skipTest("Windows runs netsh")
        code, said = quiet("--data", self.data, "firewall")
        self.assertEqual(code, 0)
        self.assertIn("sudo ufw allow 4725/tcp", said)
        self.assertIn("sudo firewall-cmd --permanent --add-port=4730/tcp", said)

    def test_repair_finds_a_changed_file_of_the_package(self):
        package = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, package)
        import hashlib
        with open(os.path.join(package, "opendmt3-server.exe"), "wb") as f:
            f.write(b"MZ as built")
        with open(os.path.join(package, standalone.MANIFEST), "w") as f:
            f.write("%s  opendmt3-server.exe\n%s  _internal/gone.dll\n" % (hashlib.sha256(b"MZ as built").hexdigest(),
                                                                         "0" * 64))
        self.assertEqual(standalone.damaged(package), ["_internal/gone.dll"])
        with mock.patch.object(standalone, "package_folder", return_value=package):
            code, said = quiet("--data", self.data, "repair")
        self.assertEqual(code, 1)
        self.assertIn("unpack the zip of this version again", said)

    def test_remove_keeps_the_data_unless_asked(self):
        quiet("--data", self.data, "setup", "--admin", "BOSS", "--password", "pass1234")
        code, said = quiet("--data", self.data, "remove")
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(os.path.join(self.data, "openDMT3.sqlite")))
        # Asked for, with no terminal to ask at and no --yes: nothing goes.
        with mock.patch("sys.stdin", io.StringIO()):
            self.assertEqual(quiet("--data", self.data, "remove", "--delete-data")[0], 1)
        self.assertTrue(os.path.isdir(self.data))
        code, said = quiet("--data", self.data, "remove", "--delete-data", "--yes")
        self.assertEqual(code, 0, said)
        self.assertFalse(os.path.exists(self.data))
        kept = [n for n in os.listdir(os.path.dirname(self.data)) if n.startswith("opendmt3-backup-")]
        self.assertTrue(kept)

    def test_invite_prints_the_address_and_its_code(self):
        quiet("--data", self.data, "setup", "--address", "192.168.0.5")
        code, said = quiet("--data", self.data, "invite")
        self.assertEqual(code, 0)
        self.assertIn("Players open http://192.168.0.5:4730/", said)
        self.assertIn("█", said)


class EdgeTest(unittest.TestCase):
    def test_names_and_addresses(self):
        self.assertEqual(edge.check_name("DMT3.Example.org."), "dmt3.example.org")
        # A public authority signs names only; Caddy's local one signs an address or a single-label name too.
        for bad in ("192.168.0.5", "https://dmt3.example.org", "dmt3.example.org:443", "a_b.example", "dmt3"):
            with self.subTest(name=bad), self.assertRaises(edge.EdgeError):
                edge.check_name(bad)
        self.assertEqual(edge.check_name("192.168.0.5", local_ca=True), "192.168.0.5")
        self.assertEqual(edge.check_name("dmt3", local_ca=True), "dmt3")

    def test_the_authority_choices(self):
        staging = edge.caddyfile("dmt3.example.org", "127.0.0.1:4730", ca="staging")
        self.assertIn("acme_ca %s" % edge.STAGING, staging)
        local = edge.caddyfile("dmt3.lan", "127.0.0.1:4730", local_ca=True)
        self.assertIn("tls internal", local)
        self.assertNotIn("acme_ca", local)
        private = edge.caddyfile("dmt3.test", "server:4730", ca="https://pebble:14000/dir", ca_root="/ca/root.pem")
        self.assertIn("acme_ca_root /ca/root.pem", private)
        with self.assertRaises(edge.EdgeError):
            edge.caddyfile("dmt3.lan", "127.0.0.1:4730", local_ca=True, email="owner@example.org")


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class StartStopTest(unittest.TestCase):
    """A real server in the background on free ports: start, status, a stop request it answers by itself."""

    def test_start_status_stop(self):
        data = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, data, True)
        self.addCleanup(quiet, "--data", data, "stop")
        for _ in range(5):
            # Two free ports; another process on this PC may take one between the look and the start (tests run
            # on several processes at once), and then two others are tried.
            game, web = free_port(), free_port()
            quiet("--data", data, "setup", "--game-port", str(game), "--web-port", str(web))
            # The child is this same Python with this tree's package.
            with mock.patch.dict(os.environ, {"PYTHONPATH": os.pathsep.join([os.getcwd()] + sys.path)}):
                code, said = quiet("--data", data, "start")
            if "is taken by another program" not in said:
                break
        self.assertEqual(code, 0, said)
        record = standalone.running(data)
        self.assertIsNotNone(record)
        self.assertEqual(record["web_port"], web)
        with urllib.request.urlopen("http://127.0.0.1:%d/health" % web, timeout=5) as answer:
            self.assertTrue(json.loads(answer.read())["ok"])
        self.assertEqual(quiet("--data", data, "status")[0], 0)
        # A second start finds it running, and a run on the same folder is refused.
        self.assertIn("already runs", quiet("--data", data, "start")[1])
        self.assertEqual(quiet("--data", data, "run", "--no-browser")[0], 2)
        code, said = quiet("--data", data, "stop")
        # Stopped by its own request, not ended from outside.
        self.assertIn("The server stopped.", said)
        self.assertIsNone(standalone.running(data))
        self.assertEqual(quiet("--data", data, "status")[0], 3)
        with open(os.path.join(data, "logs", "server.log"), encoding="utf-8") as f:
            self.assertTrue(f.read().rstrip().endswith("stopped"))


if __name__ == "__main__":
    unittest.main()
