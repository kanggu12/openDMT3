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

    def test_the_bundled_installer_goes_in_under_its_release_name(self):
        package = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, package)
        os.makedirs(os.path.join(package, standalone.BUNDLED_INSTALLER))
        name = "opendmt3-launcher-1.2.3-windows-x64-setup.exe"
        with open(os.path.join(package, standalone.BUNDLED_INSTALLER, name), "wb") as f:
            f.write(b"MZ bundled")
        downloads = os.path.join(self.data, "downloads")
        os.makedirs(downloads)
        # The owner's (an older one, under the stored name) stays; the bundled one goes in beside it.
        with open(os.path.join(downloads, standalone.INSTALLER), "wb") as f:
            f.write(b"MZ the owner's")
        with mock.patch.object(standalone, "package_folder", return_value=package):
            self.assertEqual(standalone.hand_out_bundled(self.data), name)
            # Once there, a second start copies nothing.
            self.assertIsNone(standalone.hand_out_bundled(self.data))
        self.assertEqual(sorted(os.listdir(downloads)), sorted([standalone.INSTALLER, name]))
        with open(os.path.join(downloads, standalone.INSTALLER), "rb") as f:
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


class OperationsReviewTest(unittest.TestCase):
    """What the operations review of 0.4.0 found in the server's own command line, each kept from coming back: the
    players' address on a new port, the last backup's rights, the firewall step that kept the data, and the address
    after expose --off. A data folder of the test's own; Windows' firewall and its administrator question made up."""

    def setUp(self):
        # The data folder inside a folder of the test's own: a removal keeps its last backup beside it.
        self.base = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.base)
        self.data = os.path.join(self.base, "data")
        os.makedirs(self.data)

    def test_a_new_site_port_moves_the_players_address(self):
        quiet("--data", self.data, "setup", "--address", "192.168.0.5")
        self.assertEqual(standalone.settings(self.data)["site_address"], "http://192.168.0.5:4730/")
        quiet("--data", self.data, "setup", "--web-port", "8080")
        self.assertEqual(standalone.settings(self.data)["site_address"], "http://192.168.0.5:8080/")
        # The run, the invite and its QR code all say the new one.
        argv = standalone.server_args(self.data)
        self.assertEqual(argv[argv.index("--site-address") + 1], "http://192.168.0.5:8080/")
        self.assertIn("Players open http://192.168.0.5:8080/", quiet("--data", self.data, "invite")[1])

    def test_the_last_backup_kept_on_removal_is_its_owners_alone(self):
        quiet("--data", self.data, "setup", "--admin", "BOSS", "--password", "pass1234")
        with mock.patch.object(standalone, "on_windows", return_value=False):
            self.assertEqual(quiet("--data", self.data, "remove", "--delete-data", "--yes")[0], 0)
        kept = [n for n in os.listdir(self.base) if n.startswith("opendmt3-backup-")]
        self.assertEqual(len(kept), 1)
        if os.name != "nt":
            self.assertEqual(os.stat(os.path.join(self.base, kept[0])).st_mode & 0o777, 0o600)

    def test_on_windows_the_data_goes_even_when_the_firewall_question_is_answered_no(self):
        quiet("--data", self.data, "setup", "--admin", "BOSS", "--password", "pass1234", "--game-port", "5725")
        asked = []
        with mock.patch.object(standalone, "on_windows", return_value=True), \
                mock.patch.object(standalone, "is_admin", return_value=False), \
                mock.patch.object(standalone, "firewall_rules", return_value=[5725]), \
                mock.patch.object(standalone, "elevated", side_effect=lambda argv: asked.append(argv)):
            code, said = quiet("--data", self.data, "remove", "--delete-data", "--yes")
        # Windows was asked (the rule is there), answered no: the data went all the same, and what stays is said.
        self.assertEqual(code, 0, said)
        self.assertEqual(len(asked), 1)
        # The rules of the ports the data folder kept, named for the program asked as an administrator.
        self.assertIn("5725", " ".join(asked[0]))
        self.assertFalse(os.path.exists(self.data))
        self.assertIn("firewall --remove", said)
        # No rule there: Windows is not asked at all.
        os.makedirs(self.data)
        with mock.patch.object(standalone, "on_windows", return_value=True), \
                mock.patch.object(standalone, "is_admin", return_value=False), \
                mock.patch.object(standalone, "firewall_rules", return_value=[]), \
                mock.patch.object(standalone, "elevated", side_effect=lambda argv: asked.append(argv)):
            self.assertEqual(quiet("--data", self.data, "remove")[0], 0)
        self.assertEqual(len(asked), 1)

    def test_expose_off_gives_back_the_address_setup_kept(self):
        quiet("--data", self.data, "setup", "--address", "192.168.0.5")
        quiet("--data", self.data, "expose", "dmt3.example.org")
        self.assertEqual(standalone.settings(self.data)["site_address"], "https://dmt3.example.org/")
        quiet("--data", self.data, "expose", "--off")
        self.assertEqual(standalone.settings(self.data)["site_address"], "http://192.168.0.5:4730/")

    def test_an_address_as_the_sites_name_is_its_certificates_too(self):
        # A client sends no name for an address, so Caddy is told which certificate to give then (default_sni).
        text = edge.caddyfile("192.168.0.5", "127.0.0.1:4730", local_ca=True)
        self.assertIn("default_sni 192.168.0.5", text)
        self.assertIn("192.168.0.5 {", text)
        self.assertIn("tls internal", text)
        # A name: the client sends it, and nothing more is needed.
        self.assertNotIn("default_sni", edge.caddyfile("dmt3.lan", "127.0.0.1:4730", local_ca=True))

    def test_the_banner_names_only_addresses_that_open_where_it_is_read(self):
        from opendmt3.server import __main__ as server_cli
        args = server_cli.parser().parse_args(["--host", "0.0.0.0", "--web-host", "127.0.0.1", "--proxy", "127.0.0.1",
                                               "--site-address", "https://dmt3.example.org/"])
        # In a container behind Caddy, this PC's 127.0.0.1 is not the container's: no such line, the site's name only.
        with mock.patch.object(server_cli.sources, "in_container", return_value=True):
            rows = dict(server_cli.banner_rows(args, 4725))
        self.assertEqual(rows.get("Players"), "https://dmt3.example.org/")
        self.assertNotIn("This PC", rows)
        # On the PC itself (the server's own program behind Caddy there): the site's own port opens on this PC.
        with mock.patch.object(server_cli.sources, "in_container", return_value=False):
            rows = dict(server_cli.banner_rows(args, 4725))
        self.assertEqual(rows["This PC"], "http://127.0.0.1:4730/")
        self.assertEqual(rows["Game"], "TCP 4725")


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

    def test_restart_and_the_server_tab_ask_the_running_server_itself(self):
        # Whoever starts the server stops it: the running opendmt3-server is the Server tab's runner ("standalone"),
        # restart runs it again in its own process, and a remove with the data asked on the tab deletes the folder
        # once it has stopped, a last copy kept beside it.
        import time
        import httpx
        parent = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, parent, True)
        data = os.path.join(parent, "data")
        self.addCleanup(quiet, "--data", data, "stop")
        quiet("--data", data, "setup", "--admin", "BOSS", "--password", "pass1234")
        for _ in range(5):
            game, web = free_port(), free_port()
            quiet("--data", data, "setup", "--game-port", str(game), "--web-port", str(web))
            with mock.patch.dict(os.environ, {"PYTHONPATH": os.pathsep.join([os.getcwd()] + sys.path)}):
                code, said = quiet("--data", data, "start")
            if "is taken by another program" not in said:
                break
        self.assertEqual(code, 0, said)
        before = standalone.running(data)
        code, said = quiet("--data", data, "restart")
        self.assertEqual(code, 0, said)
        after = standalone.running(data)
        # The same process, a new run in it.
        self.assertEqual(after["pid"], before["pid"])
        self.assertNotEqual(after["started"], before["started"])
        base = "http://127.0.0.1:%d" % web
        token = httpx.post(base + "/api/v1/session", json={"login_id": "BOSS", "password": "pass1234"}).json()
        boss = {"Authorization": "Bearer " + token["token"]}
        runner = httpx.get(base + "/api/v1/server", headers=boss).json()["runner"]
        self.assertEqual((runner["kind"], runner["can"]), ("standalone", ["stop", "restart", "remove"]))
        self.assertEqual(runner["commands"]["restart"], "opendmt3-server restart")
        r = httpx.post(base + "/api/v1/server/remove", headers=boss, json={"delete_data": True})
        self.assertEqual(r.status_code, 202, r.text)
        for _ in range(300):
            if not standalone.alive(int(before["pid"])):
                break
            time.sleep(0.1)
        self.assertFalse(standalone.alive(int(before["pid"])))
        self.assertFalse(os.path.exists(data))
        self.assertEqual(len([n for n in os.listdir(parent) if n.startswith("data-last-")]), 1, os.listdir(parent))


if __name__ == "__main__":
    unittest.main()
