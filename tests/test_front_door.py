"""The front door, ./dmt3: its arguments and the commands it builds from them. Nothing here runs Docker: every
command is looked at as the list it would run."""

import contextlib
import importlib.machinery
import importlib.util
import io
import os
import re
import tempfile
import unittest
from unittest import mock

# The repository's top folder (this file is in tests/).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load():
    """dmt3 as a module: it is a program without the .py ending, so it is loaded from its path."""
    loader = importlib.machinery.SourceFileLoader("dmt3_front_door", os.path.join(ROOT, "dmt3"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


dmt3 = load()
# Every docker compose command starts with this.
COMPOSE = ["docker", "compose", "-f", os.path.join(ROOT, "compose.yaml")]


def args_of(*argv):
    """The parsed arguments of ./dmt3 argv."""
    return dmt3.parser().parse_args(list(argv))


class LoadedAsModuleTest(unittest.TestCase):
    def test_loading_it_keeps_the_test_process_s_pipe_handling(self):
        # Run as the program, dmt3 lets a closed pipe end it quietly (`| head`); loaded here as a module it must not
        # change that for the whole test process, where a write to a closed socket has to stay an error (a test that
        # stops a server's thread ended the unit tests with SIGPIPE, exit 243).
        import signal
        load()
        self.assertEqual(signal.getsignal(signal.SIGPIPE), signal.SIG_IGN)

    def test_run_as_the_program_it_starts_where_the_platform_has_no_such_signal(self):
        # Windows' Python has no SIGPIPE: the front door starts there all the same (it stopped with an
        # AttributeError before it read its command line).
        import subprocess
        import sys
        code = ("import runpy, signal, sys\n"
                "del signal.SIGPIPE\n"
                "sys.argv = ['dmt3']\n"
                "runpy.run_path(%r, run_name='__main__')\n" % os.path.join(ROOT, "dmt3"))
        done = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr[-400:])
        self.assertIn("usage: ./dmt3 <command>", done.stdout)


class ArgumentsTest(unittest.TestCase):
    def test_alone_it_lists_every_command(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(dmt3.main([]), 0)
        for name, _ in dmt3.COMMANDS:
            self.assertRegex(out.getvalue(), r"\n  %s +\S" % re.escape(name))

    def test_help_lists_the_commands_in_the_same_order(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            dmt3.main(["--help"])
        # Each command starts its own line, indented by four spaces.
        positions = [out.getvalue().index("\n    %s" % n) for n, _ in dmt3.COMMANDS]
        self.assertEqual(positions, sorted(positions))

    def test_the_commands_are_the_ones_the_guides_name(self):
        self.assertEqual([n for n, _ in dmt3.COMMANDS],
                         ["setup", "catalog", "image", "up", "down", "restart", "status", "logs", "backup", "backups",
                          "restore", "add-player", "check", "invite", "ports", "expose", "doctor", "repair", "remove", "build", "test"])

    def test_restore_needs_a_name_and_an_unknown_command_is_refused(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                args_of("restore")
            with self.assertRaises(SystemExit):
                args_of("deploy")

    def test_defaults(self):
        self.assertEqual(args_of("setup").admin, "BOSS")
        self.assertEqual(args_of("logs").tail, 200)
        self.assertEqual(args_of("build").out, os.path.join(ROOT, "build", "windows"))


class CommandsTest(unittest.TestCase):
    def test_up_down_restart_status_and_logs(self):
        # The image is got before (cmd_up): Compose then neither builds nor pulls.
        self.assertEqual(dmt3.simple_command(args_of("up"), False),
                         COMPOSE + ["up", "-d", "--no-build", "--pull", "never"])
        self.assertEqual(dmt3.simple_command(args_of("down"), False), COMPOSE + ["down"])
        self.assertEqual(dmt3.simple_command(args_of("restart"), False), COMPOSE + ["restart", "server"])
        self.assertEqual(dmt3.simple_command(args_of("status"), False), COMPOSE + ["ps", "server"])
        self.assertEqual(dmt3.simple_command(args_of("logs", "-f", "-n", "50"), False),
                         COMPOSE + ["logs", "--tail", "50", "-f", "server"])

    def test_the_database_commands_use_the_servers_own_command_line(self):
        # In the running container with exec (which skips the image's entry point, so --data is given) ...
        self.assertEqual(dmt3.simple_command(args_of("backup"), True),
                         COMPOSE + ["exec", "-T", "server", "python", "-m", "opendmt3.server", "--data", "/data",
                                    "--backup"])
        # ... or in a new container that goes away, which gets --data from the entry point.
        self.assertEqual(dmt3.simple_command(args_of("backups"), False),
                         COMPOSE + ["run", "--rm", "-T", "server", "--backups"])
        self.assertEqual(dmt3.simple_command(args_of("restore", "openDMT3-20261101-120000-manual.sqlite"), False),
                         COMPOSE + ["run", "--rm", "-T", "server", "--restore",
                                    "openDMT3-20261101-120000-manual.sqlite"])

    def test_add_player_passes_only_what_was_given(self):
        self.assertEqual(dmt3.simple_command(args_of("add-player", "nova"), False),
                         COMPOSE + ["run", "--rm", "-T", "server", "--add-player", "nova"])
        self.assertEqual(dmt3.simple_command(args_of("add-player", "NOVA", "--password", "pass1234", "--dj", "DJ NOVA",
                                                     "--admin"), True)[-7:],
                         ["--add-player", "NOVA", "--password", "pass1234", "--dj", "DJ NOVA", "--admin"])

    def test_build_runs_the_windows_build_into_the_folder_given(self):
        self.assertEqual(dmt3.simple_command(args_of("build", "/tmp/out"), False),
                         [os.path.join(ROOT, "packaging", "windows", "build.sh"), "/tmp/out"])

    def test_the_commands_that_do_more_build_no_single_command(self):
        for name in ("setup", "catalog", "check", "doctor", "test"):
            with self.subTest(name=name):
                self.assertIsNone(dmt3.simple_command(args_of(name), False))

    def test_backup_asks_whether_the_server_runs_and_runs_one_command(self):
        with mock.patch.object(dmt3, "is_running", return_value=True), \
                mock.patch.object(dmt3, "run", return_value=(0, "")) as ran:
            self.assertEqual(dmt3.main(["backup"]), 0)
        ran.assert_called_once()
        self.assertIn("exec", ran.call_args[0][0])

    def test_test_runs_the_unit_tests_the_boundary_test_and_pyflakes(self):
        names = [n for n, _ in dmt3.test_commands("/usr/bin/python3")]
        self.assertEqual(names, ["unit tests", "the boundary test", "pyflakes"])
        commands = dict(dmt3.test_commands("/usr/bin/python3"))
        # The unit tests on several processes at once (tests/parallel.py), as CI runs them; one with --one-process, N
        # with --jobs.
        self.assertEqual(commands["unit tests"], ["/usr/bin/python3", "-m", "tests.parallel"])
        self.assertEqual(dict(dmt3.test_commands("/usr/bin/python3", one_process=True))["unit tests"][-1],
                         "--one-process")
        self.assertEqual(dict(dmt3.test_commands("/usr/bin/python3", jobs=3))["unit tests"][-2:], ["--jobs", "3"])
        # pyflakes on the same Python as the tests (--python's, where a virtual environment has it), never on the one
        # that runs ./dmt3, which may have no pip to put it in (PEP 668).
        self.assertEqual(dict(dmt3.test_commands("/opt/venv/bin/python"))["pyflakes"][:3],
                         ["/opt/venv/bin/python", "-m", "pyflakes"])
        with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8") as f:
            self.assertIn("run: python -m tests.parallel", f.read())
        # The package, the tests, the front door, and the scripts that build and release it (the wizard among them).
        self.assertEqual(commands["pyflakes"][-5:], ["opendmt3", "tests", "dmt3", "packaging", ".github"])
        self.assertTrue(dmt3.WIZARD.startswith("packaging"))


class ImageTest(unittest.TestCase):
    """./dmt3 image: the published image of this version unless --build, built when it cannot be pulled."""

    def setUp(self):
        # Nothing here runs Docker or writes .env: every command and every write is recorded instead.
        self.ran, self.env, self.here = [], {}, set()
        patches = [mock.patch.object(dmt3, "run", side_effect=self.fake_run),
                   mock.patch.object(dmt3, "write_env", side_effect=self.env.update),
                   mock.patch.object(dmt3, "read_env", side_effect=lambda: {k: v for k, v in self.env.items() if v}),
                   mock.patch.object(dmt3, "has_image", side_effect=lambda name: name in self.here),
                   mock.patch.object(dmt3, "say"), mock.patch.dict(os.environ, {}, clear=False)]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        # The variable from the test's own environment would choose for it.
        os.environ.pop(dmt3.IMAGE_ENV, None)
        self.pull_works = True

    def fake_run(self, cmd, capture=False):
        self.ran.append(cmd)
        if cmd[:2] == ["docker", "pull"]:
            return (0 if self.pull_works else 1), ""
        return 0, ""

    def test_the_published_image_is_pulled_when_it_is_not_here(self):
        self.assertEqual(dmt3.cmd_image(args_of("image")), 0)
        self.assertEqual(self.ran, [["docker", "pull", dmt3.published_image()]])
        # Nothing is kept: .env names no image, so the next version's is the next one pulled.
        self.assertNotIn(dmt3.IMAGE, self.env.values())

    def test_an_image_already_here_is_neither_pulled_nor_built(self):
        self.here.add(dmt3.published_image())
        self.assertEqual(dmt3.cmd_image(args_of("image")), 0)
        self.assertEqual(self.ran, [])

    def test_no_published_image_builds_this_clone_and_keeps_it(self):
        self.pull_works = False
        self.assertEqual(dmt3.cmd_image(args_of("image")), 0)
        # With the recipe, which names the build this clone's own.
        self.assertEqual(self.ran[-1], COMPOSE + ["-f", dmt3.BUILD_FILE, "build", "server"])
        self.assertEqual(self.env[dmt3.IMAGE_ENV], dmt3.IMAGE)

    def test_build_builds_and_published_goes_back(self):
        dmt3.cmd_image(args_of("image", "--build"))
        self.assertEqual(self.ran, [COMPOSE + ["-f", dmt3.BUILD_FILE, "build", "server"]])
        self.assertEqual(dmt3.chosen_image(), dmt3.IMAGE)
        self.ran.clear()
        dmt3.cmd_image(args_of("image", "--published"))
        self.assertEqual(self.ran, [["docker", "pull", dmt3.published_image()]])
        self.assertEqual(dmt3.chosen_image(), dmt3.published_image())

    def test_published_asked_for_by_name_is_never_built_instead(self):
        self.pull_works = False
        self.assertEqual(dmt3.cmd_image(args_of("image", "--published")), 1)
        self.assertNotIn(COMPOSE + ["-f", dmt3.BUILD_FILE, "build", "server"], self.ran)

    def test_the_setup_gets_the_image_with_this_same_file(self):
        step = dmt3.setup_plan(args_of("setup", "--build"), accounts=1)[0]
        self.assertEqual(step[0], "image")
        self.assertEqual(step[2][1:], [os.path.join(ROOT, "dmt3"), "image", "--build"])


class ExposeTest(unittest.TestCase):
    """./dmt3 expose: the Caddyfile and .env, and every Compose command reading edge.yaml while the site is exposed."""

    def setUp(self):
        # .env and the Caddyfile's folder are the test's own; nothing runs Docker.
        self.env, self.ran = {}, []
        self.edge = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.edge)
        patches = [mock.patch.object(dmt3, "write_env", side_effect=self.write),
                   mock.patch.object(dmt3, "read_env", side_effect=lambda: dict(self.env)),
                   mock.patch.object(dmt3, "EDGE_DIR", self.edge),
                   mock.patch.object(dmt3, "is_running", return_value=True),
                   mock.patch.object(dmt3, "run", side_effect=lambda cmd, capture=False: self.ran.append(cmd) or (0, "")),
                   mock.patch.object(dmt3, "say")]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, values):
        for name, value in values.items():
            if value is None:
                self.env.pop(name, None)
            else:
                self.env[name] = value

    def test_expose_writes_the_caddyfile_and_starts_caddy_beside_the_server(self):
        self.assertEqual(dmt3.cmd_expose(args_of("expose", "dmt3.example.org", "--email", "me@example.org")), 0)
        with open(os.path.join(self.edge, "Caddyfile"), encoding="utf-8") as f:
            caddy = f.read()
        # Caddy shares the server's network: the site at 127.0.0.1:4730.
        self.assertIn("dmt3.example.org {\n    reverse_proxy 127.0.0.1:4730", caddy)
        self.assertEqual(self.env, {"EDGE_NAME": "dmt3.example.org", "SITE_ADDRESS": "https://dmt3.example.org/"})
        edge_compose = ["docker", "compose", "-f", dmt3.COMPOSE_FILE, "-f", dmt3.EDGE_FILE]
        # The server again with edge.yaml, then Caddy started again to read its new Caddyfile.
        self.assertEqual(self.ran, [edge_compose + ["up", "-d", "--no-build", "--pull", "never"],
                                    edge_compose + ["restart", "edge"]])

    def test_off_goes_back_to_compose_yaml_alone_and_caddy_goes(self):
        self.env.update(EDGE_NAME="dmt3.example.org", SITE_ADDRESS="https://dmt3.example.org/")
        self.assertEqual(dmt3.cmd_expose(args_of("expose", "--off")), 0)
        self.assertEqual(self.env, {})
        self.assertEqual(self.ran, [COMPOSE + ["up", "-d", "--no-build", "--pull", "never", "--remove-orphans"]])

    def test_a_private_authority_brings_its_root(self):
        root = os.path.join(self.edge, "given-root.pem")
        with open(root, "w") as f:
            f.write("-----BEGIN CERTIFICATE-----\n")
        dmt3.cmd_expose(args_of("expose", "dmt3.lan", "--ca", "https://ca.lan/acme/directory", "--ca-root", root))
        with open(os.path.join(self.edge, "Caddyfile"), encoding="utf-8") as f:
            caddy = f.read()
        self.assertIn("acme_ca https://ca.lan/acme/directory", caddy)
        # Where edge.yaml mounts .edge/ in Caddy's container.
        self.assertIn("acme_ca_root /etc/caddy/ca-root.pem", caddy)
        self.assertTrue(os.path.isfile(os.path.join(self.edge, "ca-root.pem")))

    def test_an_address_needs_the_local_authority(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            dmt3.cmd_expose(args_of("expose", "192.168.0.5"))
        dmt3.cmd_expose(args_of("expose", "192.168.0.5", "--local-ca"))
        self.assertEqual(self.env["SITE_ADDRESS"], "https://192.168.0.5/")

    def test_edge_yaml_puts_caddy_in_the_servers_network(self):
        with open(dmt3.EDGE_FILE, encoding="utf-8") as f:
            text = f.read()
        self.assertIn('network_mode: "service:server"', text)
        self.assertIn('command: ["--web-host", "127.0.0.1", "--proxy", "127.0.0.1"]', text)
        # The site's own port is not published beside Caddy's.
        self.assertIn("ports: !override", text)
        self.assertNotIn("4730:4730", text)
        self.assertIn("- ./.edge:/etc/caddy:ro", text)


class EnvFileTest(unittest.TestCase):
    """.env saved by Notepad (a byte-order mark, CRLF, spaces around = ) reads as the same variables."""

    def test_a_notepad_env_reads_the_same_and_is_tidied(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, folder)
        path = os.path.join(folder, ".env")
        with open(path, "wb") as f:
            f.write("\ufeffGAME_DIR = '/srv/game'\r\n# a note\r\nSITE_ADDRESS= http://192.168.0.5:4730/ \r\n".encode())
        with mock.patch.object(dmt3, "ENV_FILE", path):
            self.assertEqual(dmt3.read_env(), {"GAME_DIR": "/srv/game", "SITE_ADDRESS": "http://192.168.0.5:4730/"})
            dmt3.tidy_env()
            with open(path, "rb") as f:
                self.assertEqual(f.read(), b"GAME_DIR='/srv/game'\n# a note\nSITE_ADDRESS=http://192.168.0.5:4730/\n")
            # Written again, the variables stay and nothing else moves.
            dmt3.write_env({"EDGE_NAME": "dmt3.example.org"})
            self.assertEqual(dmt3.read_env()["GAME_DIR"], "/srv/game")
            self.assertEqual(dmt3.read_env()["EDGE_NAME"], "dmt3.example.org")


class PortsTest(unittest.TestCase):
    """./dmt3 ports: kept in .env, read by every command; two parts never on one port."""

    def setUp(self):
        self.env, self.ran = {}, []
        patches = [mock.patch.object(dmt3, "write_env", side_effect=lambda v: [self.env.pop(k, None) if x is None else
                                                                             self.env.__setitem__(k, x)
                                                                             for k, x in v.items()]),
                   mock.patch.object(dmt3, "read_env", side_effect=lambda: dict(self.env)),
                   mock.patch.object(dmt3, "is_running", return_value=True),
                   mock.patch.object(dmt3, "run", side_effect=lambda cmd, capture=False: self.ran.append(cmd) or (0, "")),
                   mock.patch.object(dmt3, "say")]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_new_ports_are_kept_and_the_server_starts_again_on_them(self):
        self.assertEqual(dmt3.cmd_ports(args_of("ports", "--game", "5725", "--web", "8080")), 0)
        self.assertEqual(self.env, {"GAME_PORT": "5725", "WEB_PORT": "8080"})
        self.assertEqual((dmt3.game_port(), dmt3.web_port()), (5725, 8080))
        self.assertEqual(self.ran, [COMPOSE + ["up", "-d", "--no-build", "--pull", "never"]])
        # The usual one again: nothing kept for it.
        dmt3.cmd_ports(args_of("ports", "--web", "4730"))
        self.assertEqual(self.env, {"GAME_PORT": "5725"})

    def test_one_port_for_two_parts_is_refused_and_undone(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            dmt3.cmd_ports(args_of("ports", "--game", "4730"))
        self.assertEqual(self.env, {})

    def test_remove_keeps_the_data_unless_asked_and_asked_again(self):
        # .env and the Caddyfile that a removal with the data deletes are the test's own (none), never the clone's.
        folder = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, folder)
        with mock.patch.object(dmt3, "has_image", return_value=False), \
                mock.patch.object(dmt3, "ENV_FILE", os.path.join(folder, ".env")), \
                mock.patch.object(dmt3, "EDGE_DIR", folder), mock.patch.dict(os.environ, {}, clear=False):
            # The project as compose.yaml names it, whatever the environment running the tests says.
            os.environ.pop("COMPOSE_PROJECT_NAME", None)
            self.assertEqual(dmt3.cmd_remove(args_of("remove")), 0)
            self.assertEqual(self.ran, [COMPOSE + ["down", "--remove-orphans"]])
            self.ran.clear()
            # --delete-data with no --yes and no terminal to ask at: nothing goes.
            with mock.patch.object(dmt3, "ask", return_value=False):
                self.assertEqual(dmt3.cmd_remove(args_of("remove", "--delete-data")), 1)
            self.assertEqual(self.ran, [])
            # With --yes: a backup read out first, then the volume with the rest.
            with mock.patch.object(dmt3, "last_backup_out", return_value="/clone/opendmt3-backup.sqlite") as backup:
                self.assertEqual(dmt3.cmd_remove(args_of("remove", "--delete-data", "--yes")), 0)
            backup.assert_called_once()
            # edge.yaml too, so Caddy's volumes go with the data; then what Docker still has of the project is looked
            # at.
            self.assertEqual(self.ran, [COMPOSE + ["-f", dmt3.EDGE_FILE, "down", "--remove-orphans", "-v"],
                                        ["docker", "volume", "ls", "-q", "--filter",
                                         "label=com.docker.compose.project=opendmt3"]])


class SetupTest(unittest.TestCase):
    def setUp(self):
        # No installer from an earlier build may join the steps by itself.
        patcher = mock.patch.object(dmt3, "default_installer", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_first_run_makes_the_image_the_folder_the_owner_and_starts(self):
        steps = dmt3.setup_steps(args_of("setup"), accounts=0)
        what = [w for w, _ in steps]
        self.assertEqual(what, ["the server image", "the data folder", "the first account, BOSS, with the admin pages",
                                "the server"])
        self.assertEqual(steps[2][1], COMPOSE + ["run", "--rm", "-T", "server", "--add-player", "BOSS", "--admin"])
        self.assertEqual(steps[-1][1], COMPOSE + ["up", "-d", "server"])

    def test_a_second_run_makes_no_account(self):
        what = [w for w, _ in dmt3.setup_steps(args_of("setup"), accounts=2)]
        self.assertFalse(any("account" in w for w in what))

    def test_the_song_list_and_the_installer_are_mounted_read_only(self):
        with tempfile.TemporaryDirectory() as game:
            installer = os.path.join(game, "setup.exe")
            steps = dict(dmt3.setup_steps(args_of("setup", "--game", game, "--installer", installer, "--no-start"),
                                          accounts=1))
        songs = steps["the song list from %s" % game]
        # The game folder read-only at its own path, read as root (a folder only its owner reads), no other service.
        self.assertIn("%s:%s:ro" % (game, game), songs)
        self.assertEqual(songs[songs.index("--user") + 1], "root")
        self.assertIn("--no-deps", songs)
        self.assertEqual(songs[-3:], ["--catalog", game, "--setup-only"])
        copy = steps["the installer for the Download page"]
        self.assertIn("%s:/in/openDMT3-win-Setup.exe:ro" % installer, copy)
        self.assertEqual(copy[-2:], ["/in/openDMT3-win-Setup.exe", "/data/downloads/openDMT3-win-Setup.exe"])
        # --no-start: nothing is started.
        self.assertNotIn("the server", steps)


class ReleasePackageTest(unittest.TestCase):
    def test_the_build_s_installer_is_found_under_the_release_s_name(self):
        with tempfile.TemporaryDirectory() as built:
            releases = os.path.join(built, "releases")
            os.makedirs(releases)
            with mock.patch.object(dmt3, "BUILD_DIR", built):
                # No build yet: no installer to hand out.
                self.assertIsNone(dmt3.default_installer())
                # Two builds' installers in the folder: the newer version's (by its name, these hold no version).
                for version in ("0.3.1", "0.3.10", "0.3.2"):
                    with open(os.path.join(releases, "opendmt3-launcher-%s-windows-x64-setup.exe" % version), "wb") as f:
                        f.write(b"MZ")
                self.assertEqual(os.path.basename(dmt3.default_installer()),
                                 "opendmt3-launcher-0.3.10-windows-x64-setup.exe")

    def test_the_clone_s_own_commands_say_so_in_the_server_package(self):
        # The server package has no tests/ and no packaging/windows/: ./dmt3 test and build say where they run.
        with tempfile.TemporaryDirectory() as package, mock.patch.object(dmt3, "ROOT", package), \
                mock.patch.dict(os.environ):
            # The package's own code is there (its version names the image ./dmt3 runs); the image is not chosen yet,
            # as in CI, where no ./dmt3 before this one set it.
            os.environ.pop(dmt3.IMAGE_ENV, None)
            os.makedirs(os.path.join(package, "opendmt3"))
            with open(os.path.join(package, "opendmt3", "__init__.py"), "w", encoding="utf-8") as f:
                f.write('__version__ = "0.0.0"\n')
            for command in ("test", "build"):
                with self.subTest(command=command), contextlib.redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(dmt3.main([command]), 2)
                self.assertIn("runs in a clone of the repository", out.getvalue())


class SetupOptionsTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(dmt3, "default_installer", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_steps_have_keys_and_a_password_given_goes_to_the_account(self):
        plan = dmt3.setup_plan(args_of("setup", "--admin", "NOVA", "--password", "pass1234"), accounts=0)
        self.assertEqual([key for key, _, _ in plan], ["image", "data", "account", "server"])
        self.assertEqual(plan[2][2][-5:], ["--add-player", "NOVA", "--admin", "--password", "pass1234"])
        # An empty installer is none, even with one from a build.
        with mock.patch.object(dmt3, "default_installer", return_value="/build/setup.exe"):
            self.assertIn("installer", [k for k, _, _ in dmt3.setup_plan(args_of("setup"), accounts=1)])
            none = dmt3.setup_plan(argparse_namespace(installer=""), accounts=1)
        self.assertNotIn("installer", [k for k, _, _ in none])

    def test_only_setup_alone_at_a_terminal_opens_the_wizard(self):
        self.assertTrue(dmt3.asked_nothing(["setup"]))
        self.assertFalse(dmt3.asked_nothing(["setup", "--game", "/g"]))
        self.assertFalse(dmt3.asked_nothing(["up"]))
        with mock.patch.object(dmt3, "wizard") as wizard, mock.patch.object(dmt3, "cmd_setup", return_value=0) as old, \
                mock.patch.object(dmt3.sys.stdin, "isatty", return_value=True), \
                mock.patch.object(dmt3.sys.stdout, "isatty", return_value=True):
            wizard.return_value.run.return_value = 0
            self.assertEqual(dmt3.main(["setup"]), 0)
            wizard.return_value.run.assert_called_once()
            old.assert_not_called()
            # With an option it runs as before, without questions.
            dmt3.main(["setup", "--no-start"])
            old.assert_called_once()
        # From a script (no terminal) too.
        with mock.patch.object(dmt3, "wizard") as wizard, mock.patch.object(dmt3, "cmd_setup", return_value=0) as old, \
                mock.patch.object(dmt3.sys.stdin, "isatty", return_value=False):
            dmt3.main(["setup"])
        wizard.assert_not_called()
        old.assert_called_once()

    def test_catalog_without_a_folder_or_a_kept_one_says_how(self):
        with mock.patch.object(dmt3, "read_env", return_value={}), \
                contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            dmt3.main(["catalog"])
        self.assertIn("./dmt3 catalog PATH", err.getvalue())

    def test_catalog_looks_first_and_reads_nothing_from_a_folder_with_no_game(self):
        with tempfile.TemporaryDirectory() as empty, mock.patch.object(dmt3, "run") as ran, \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(dmt3.main(["catalog", empty]), 1)
        ran.assert_not_called()
        self.assertIn("FAIL  This is not a folder or an archive holding client data.", out.getvalue())
        self.assertNotIn("Traceback", out.getvalue())


def argparse_namespace(**changes):
    """./dmt3 setup's arguments with some changed (as the wizard gives them)."""
    args = args_of("setup")
    for name, value in changes.items():
        setattr(args, name, value)
    return args


class GameFolderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp)
        # A game folder whose archives are links into another folder, as a copy that keeps the big files elsewhere.
        self.game = os.path.join(self.tmp, "game")
        self.store = os.path.join(self.tmp, "store", "pack")
        os.makedirs(os.path.join(self.game, "pack"))
        os.makedirs(self.store)
        for name in ("Big.pak", "Other.pak"):
            open(os.path.join(self.store, name), "w").close()
            os.symlink(os.path.join(self.store, name), os.path.join(self.game, "pack", name))
        # A relative link inside the folder needs nothing more; a dangling one is left out.
        open(os.path.join(self.game, "Client.exe"), "w").close()
        os.symlink("../Client.exe", os.path.join(self.game, "pack", "inside.exe"))
        os.symlink(os.path.join(self.tmp, "gone", "x.pak"), os.path.join(self.game, "pack", "gone.pak"))

    def test_the_folders_links_point_into_are_mounted_too(self):
        mounts, refused = dmt3.game_mounts(self.game)
        self.assertEqual((mounts, refused), ([self.game, self.store], []))
        self.assertEqual(dmt3.mount_args(mounts), ["-v", "%s:%s:ro" % (self.game, self.game),
                                                   "-v", "%s:%s:ro" % (self.store, self.store)])
        command = dmt3.catalog_command(self.game)
        self.assertIn("%s:%s:ro" % (self.store, self.store), command)
        self.assertEqual(dmt3.kept_game(self.game), (self.game, self.store))

    def test_a_system_folder_is_never_mounted(self):
        os.symlink("/etc/hostname", os.path.join(self.game, "pack", "system.pak"))
        mounts, refused = dmt3.game_mounts(self.game)
        self.assertEqual(refused, ["/etc"])
        self.assertNotIn("/etc", mounts)
        # Kept mounted, the links into it are not.
        self.assertEqual(dmt3.kept_game(self.game), (self.game, ""))

    def test_the_song_list_is_read_as_root_only_when_the_servers_own_user_cannot(self):
        if os.getuid() == dmt3.SERVER_UID:
            self.skipTest("run as the server's own user, every file here is its own")

        def user_of(command):
            return command[command.index("--user") + 1] if "--user" in command else "the image's own"
        # A game folder anyone may read (and the folder its links lead into): read as the image's own user.
        self.assertEqual(user_of(dmt3.catalog_command(self.game)), "the image's own")
        # A folder on the way only its owner may enter: root, to read it (the server then writes as the data folder's
        # owner alone).
        os.chmod(os.path.join(self.game, "pack"), 0o700)
        self.assertEqual(user_of(dmt3.catalog_command(self.game)), "root")
        os.chmod(os.path.join(self.game, "pack"), 0o755)
        # A split archive anyone may read, every part of it: its own user; one part only its owner reads: root.
        downloads = os.path.join(self.tmp, "downloads")
        os.makedirs(downloads)
        for part in ("001", "002"):
            with open(os.path.join(downloads, "technika.7z." + part), "wb") as f:
                f.write(b"7z\xbc\xaf\x27\x1c" + bytes(26))
        first = os.path.join(downloads, "technika.7z.001")
        self.assertEqual(user_of(dmt3.catalog_command(first)), "the image's own")
        os.chmod(os.path.join(downloads, "technika.7z.002"), 0o600)
        self.assertEqual(user_of(dmt3.catalog_command(first)), "root")
        os.chmod(os.path.join(downloads, "technika.7z.002"), 0o644)
        # --save into a folder the server's own user cannot write: root; one open to anyone: its own user.
        out = os.path.join(self.tmp, "out")
        os.makedirs(out)
        os.chmod(out, 0o755)
        self.assertEqual(user_of(dmt3.catalog_command(first, save=out)), "root")
        os.chmod(out, 0o777)
        self.assertEqual(user_of(dmt3.catalog_command(first, save=out)), "the image's own")

    def test_whether_the_servers_own_user_can_read_the_folder(self):
        self.assertTrue(dmt3.server_can_read(self.game))
        os.chmod(os.path.join(self.store, "Big.pak"), 0o600)
        # Owned by someone else than the server's user (unless the tests run as it).
        self.assertEqual(dmt3.server_can_read(self.game), os.stat(os.path.join(self.store, "Big.pak")).st_uid ==
                         dmt3.SERVER_UID)

    def test_the_env_file_keeps_other_lines_and_quotes_paths_as_they_are(self):
        path = os.path.join(self.tmp, ".env")
        with open(path, "w") as f:
            f.write("# mine\nOTHER=1\nGAME_DIR=/old\n")
        with mock.patch.object(dmt3, "ENV_FILE", path):
            dmt3.write_env({"GAME_DIR": "/games/made up (1) $HOME", "GAME_LINKS": None})
            self.assertEqual(dmt3.read_env(), {"OTHER": "1", "GAME_DIR": "/games/made up (1) $HOME"})
            with open(path) as f:
                self.assertEqual(f.read(), "# mine\nOTHER=1\nGAME_DIR='/games/made up (1) $HOME'\n")
            with self.assertRaises(ValueError):
                dmt3.write_env({"GAME_DIR": "/games/it's"})

    def test_the_address_chosen_for_the_players_is_kept_for_the_server(self):
        # An address of this PC as the wizard lists them, a name, or a whole address behind a proxy: each as the
        # site's address a player opens, with its last slash.
        self.assertEqual(dmt3.site_address("192.168.0.5"), "http://192.168.0.5:4730/")
        self.assertEqual(dmt3.site_address(" dmt3.example "), "http://dmt3.example:4730/")
        self.assertEqual(dmt3.site_address("https://dmt3.example"), "https://dmt3.example/")
        path = os.path.join(self.tmp, ".env")
        with open(path, "w") as f:
            f.write("GAME_DIR='/games/made-up'\n")
        with mock.patch.object(dmt3, "ENV_FILE", path):
            dmt3.keep_address("192.168.0.5")
            # Beside the game folder kept before it, in the file Compose reads (compose.yaml hands it to the server).
            self.assertEqual(dmt3.read_env(), {"GAME_DIR": "/games/made-up", "SITE_ADDRESS": "http://192.168.0.5:4730/"})
            dmt3.FrontDoor().keep_address("10.0.0.7")
            self.assertEqual(dmt3.read_env()["SITE_ADDRESS"], "http://10.0.0.7:4730/")
        self.assertEqual(dmt3.parser().parse_args(["setup", "--address", "192.168.0.5"]).address, "192.168.0.5")
        self.assertIsNone(dmt3.parser().parse_args(["setup"]).address)

    def test_status_ends_with_where_the_site_is(self):
        published = (0, "0.0.0.0:4730\n")
        with mock.patch.object(dmt3, "run", return_value=published), \
                mock.patch.object(dmt3, "lan_addresses", return_value=[("192.168.0.5", "eth0"), ("127.0.0.1", "")]):
            # The address kept at setup first (the one to open and to send), then this PC's own.
            with mock.patch.object(dmt3, "read_env", return_value={"SITE_ADDRESS": "https://dmt3.example/"}):
                self.assertEqual(dmt3.site_lines(),
                                 "The site: https://dmt3.example/ (on this PC also http://127.0.0.1:4730/).")
            # None kept: this PC's address on its network.
            with mock.patch.object(dmt3, "read_env", return_value={}):
                self.assertEqual(dmt3.site_lines(),
                                 "The site: http://192.168.0.5:4730/ (on this PC also http://127.0.0.1:4730/).")
            # An address of this PC alone is said as that.
            with mock.patch.object(dmt3, "read_env", return_value={"SITE_ADDRESS": "http://127.0.0.1:4730/"}):
                self.assertEqual(dmt3.site_lines(), "The site: http://127.0.0.1:4730/ (this PC only).")
        with mock.patch.object(dmt3, "run", return_value=published), mock.patch.object(dmt3, "read_env", return_value={}), \
                mock.patch.object(dmt3, "lan_addresses", return_value=[("127.0.0.1", "this PC only")]):
            self.assertEqual(dmt3.site_lines(), "The site: http://127.0.0.1:4730/ (this PC only).")
        # The server down: its port is not published, and there is no site to name.
        with mock.patch.object(dmt3, "run", return_value=(1, "")):
            self.assertIsNone(dmt3.site_lines())
        # status says it last, after the container's state and the health.
        said = []
        with mock.patch.object(dmt3, "run", return_value=(0, "")), mock.patch.object(dmt3, "cmd_check", return_value=0), \
                mock.patch.object(dmt3, "site_lines", return_value="The site: X"), \
                mock.patch.object(dmt3, "say", said.append):
            self.assertEqual(dmt3.main(["status"]), 0)
        self.assertEqual(said, ["The site: X"])

    def test_the_help_keeps_a_files_name_whole(self):
        import contextlib
        import io
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"COLUMNS": "80"}), contextlib.redirect_stdout(out), \
                self.assertRaises(SystemExit):
            dmt3.parser().parse_args(["catalog", "--help"])
        text = out.getvalue()
        # Broken at spaces only: the file's name (and a flag's) is never cut at a hyphen.
        self.assertIn("openDMT3-song-list.zip", text)
        self.assertNotRegex(text, r"openDMT3-\n|song-\n")
        # An account's ID is for the site and the launcher (the PC client logs in by card: nothing is typed at it).
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            dmt3.parser().parse_args(["add-player", "--help"])
        self.assertIn("the account's ID, for the site and the launcher", " ".join(out.getvalue().split()))


class CatalogFormsTest(unittest.TestCase):
    """./dmt3 catalog with an archive or a song list: its folder mounted read-only (where a split archive's other
    parts are), --save writing a song list into a folder mounted for it, an archive's password passed by the
    environment's name alone, and an archive this PC has no 7-Zip for left to the server's own."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp)
        self.archive = os.path.join(self.tmp, "downloads", "technika.7z")
        os.makedirs(os.path.dirname(self.archive))
        with open(self.archive, "wb") as f:
            # The first bytes of a 7z archive: an archive by its content, whatever this PC can open.
            f.write(b"7z\xbc\xaf\x27\x1c" + bytes(26))

    def test_a_file_is_mounted_with_its_folder_and_save_writes_into_a_folder_of_its_own(self):
        command = dmt3.catalog_command(self.archive)
        folder = os.path.dirname(self.archive)
        self.assertIn("%s:%s:ro" % (folder, folder), command)
        self.assertEqual(command[-3:], ["--catalog", self.archive, "--setup-only"])
        out = os.path.join(self.tmp, "out", "openDMT3-song-list.zip")
        os.makedirs(os.path.dirname(out))
        command = dmt3.catalog_command(self.archive, save=out)
        self.assertIn("%s:%s" % (os.path.dirname(out), os.path.dirname(out)), command)
        self.assertEqual(command[-4:], ["--catalog", self.archive, "--save", out])
        self.assertNotIn(dmt3.PASSWORD_ENV, command)
        # A password goes in by the environment's name alone, never its value on the command line.
        with mock.patch.dict(os.environ, {dmt3.PASSWORD_ENV: "made-up"}):
            command = dmt3.catalog_command(self.archive)
        self.assertEqual(command[command.index("-e") + 1], dmt3.PASSWORD_ENV)
        self.assertNotIn("made-up", " ".join(command))

    def test_an_archive_this_pc_cannot_open_is_left_to_the_servers_own_7zip(self):
        from opendmt3.server.services import sources
        with mock.patch.object(sources, "seven_zip", lambda: None), mock.patch.object(dmt3, "docker_ready",
                                                                                    lambda: True), \
                mock.patch.object(dmt3, "run", return_value=(0, "")) as ran, \
                mock.patch.object(dmt3, "is_running", lambda: False), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(dmt3.main(["catalog", self.archive, "--save", self.tmp]), 0)
        self.assertIn("the server's own 7-Zip", out.getvalue())
        self.assertEqual(ran.call_args[0][0][-4:], ["--catalog", self.archive, "--save", self.tmp])


class PiecesTest(unittest.TestCase):
    def test_a_published_port_is_reached_at_an_address_of_this_pc(self):
        self.assertEqual(dmt3.published("0.0.0.0:4730\n"), ("127.0.0.1", 4730))
        self.assertEqual(dmt3.published("[::]:4725"), ("127.0.0.1", 4725))
        self.assertEqual(dmt3.published("127.0.0.1:14730"), ("127.0.0.1", 14730))

    def test_a_port_is_taken_only_by_a_listener(self):
        import socket
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("0.0.0.0", 0))
            listener.listen()
            port = listener.getsockname()[1]
            self.assertFalse(dmt3.port_free(port))
            # A connection left closing (TIME_WAIT on this side) once the listener is gone holds no port.
            client = socket.create_connection(("127.0.0.1", port))
            accepted, _ = listener.accept()
            accepted.close()
            client.close()
        self.assertTrue(dmt3.port_free(port))

    def test_only_the_known_lint_line_is_let_through(self):
        known = "opendmt3/client/updates.py:89:9 'velopack' imported but unused\n"
        self.assertEqual(dmt3.unexpected_lint(known), [])
        self.assertEqual(dmt3.unexpected_lint(known + "dmt3:3:1 'os' imported but unused\n"),
                         ["dmt3:3:1 'os' imported but unused"])

    def test_compose_yaml_names_what_the_front_door_uses(self):
        with open(os.path.join(ROOT, "compose.yaml"), encoding="utf-8") as f:
            text = f.read()
        # The project's name gives the data volume its name (doctor looks for PROJECT_data).
        self.assertRegex(text, r"(?m)^name: %s$" % dmt3.PROJECT)
        self.assertRegex(text, r"(?m)^  %s:$" % dmt3.SERVICE)
        # The image by its variable, the published one of this version by default (the release's, moved with it).
        self.assertIn("image: ${%s:-%s}" % (dmt3.IMAGE_ENV, dmt3.published_image()), text)
        from opendmt3 import __version__
        self.assertEqual(dmt3.published_image(), "ghcr.io/kanggu12/opendmt3-server:" + __version__)
        # Each port the same inside and out, the one .env keeps (./dmt3 ports) or the usual one, told to the server.
        for name, port in ((dmt3.GAME_PORT_ENV, dmt3.GAME_PORT), (dmt3.WEB_PORT_ENV, dmt3.WEB_PORT)):
            self.assertIn('"${%s:-%d}:${%s:-%d}"' % (name, port, name, port), text)
        self.assertIn("OPENDMT3_GAME_PORT: ${GAME_PORT:-4725}", text)
        self.assertIn("OPENDMT3_WEB_PORT: ${WEB_PORT:-4730}", text)
        # The game folder kept mounted: read-only, at its own path, and told to the server.
        self.assertIn("OPENDMT3_GAME: ${GAME_DIR:-}", text)
        # The site's address for players, told to the server (its --site-address reads it).
        self.assertIn("OPENDMT3_SITE_ADDRESS: ${SITE_ADDRESS:-}", text)
        for name in ("GAME_DIR", "GAME_LINKS"):
            self.assertRegex(text, r"source: \$\{%s:-[^}]+\}\n\s+target: \$\{%s:-[^}]+\}\n\s+read_only: true"
                             % (name, name))


class OperationsReviewTest(unittest.TestCase):
    """What the operations review of 0.4.0 found in ./dmt3, each kept from coming back: the setup's image, the players'
    address on a new port, the last backup's rights, Caddy's volumes on removal, the address after expose --off, the
    router's ports, and the setup's own failures. .env, the Caddyfile's folder and the clone's folder are the test's
    own; nothing runs Docker: every command is recorded, and Docker's answers are made up."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.folder)
        # Commands run, in order; the images Docker has; what each command answers (by its first words).
        self.ran, self.images, self.answers = [], set(), {}
        patches = [mock.patch.object(dmt3, "ENV_FILE", os.path.join(self.folder, ".env")),
                   mock.patch.object(dmt3, "EDGE_DIR", os.path.join(self.folder, ".edge")),
                   mock.patch.object(dmt3, "run", side_effect=self.fake_run),
                   mock.patch.object(dmt3, "has_image", side_effect=lambda name: name in self.images),
                   mock.patch.object(dmt3, "docker_ready", return_value=True),
                   mock.patch.object(dmt3, "default_installer", return_value=None),
                   mock.patch.object(dmt3, "is_running", return_value=False),
                   mock.patch.dict(os.environ, {}, clear=False)]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        # The test's own environment must not choose the image.
        os.environ.pop(dmt3.IMAGE_ENV, None)
        self.said = []
        patcher = mock.patch.object(dmt3, "say", side_effect=self.said.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_run(self, cmd, capture=False):
        self.ran.append(cmd)
        if cmd[:2] == ["docker", "pull"]:
            # A pull brings the image.
            self.images.add(cmd[2])
        for start, answer in self.answers.items():
            if " ".join(cmd).startswith(start) or start in " ".join(cmd):
                return answer
        # The accounts' count, run inside the server's container (count_accounts), prints how many there are; any
        # other command prints nothing.
        return 0, "0\n" if capture and "--entrypoint" in cmd and "python" in cmd else ""

    def env(self):
        """.env as written now."""
        return dmt3.read_env()

    def test_setup_gets_the_published_image_before_anything_runs_in_it(self):
        # Before: the accounts were counted in a container first, and Compose built this clone under the published
        # name to run it; the image step then found that tag and never pulled.
        dmt3.cmd_setup(args_of("setup", "--admin", "BOSS", "--password", "pass1234", "--no-start"))
        pull = self.ran.index(["docker", "pull", dmt3.published_image()])
        runs = [i for i, cmd in enumerate(self.ran) if cmd[:2] == ["docker", "compose"] and "run" in cmd]
        self.assertTrue(runs and min(runs) > pull, self.ran)
        # The image step is not run a second time as a command of its own.
        self.assertFalse([cmd for cmd in self.ran if cmd[1:3] == [os.path.join(ROOT, "dmt3"), "image"]])

    def test_a_local_build_never_carries_the_published_name(self):
        # compose.yaml has no recipe: a Compose command with the image missing pulls it, and never builds it under the
        # published name.
        with open(dmt3.COMPOSE_FILE, encoding="utf-8") as f:
            self.assertNotRegex(f.read(), r"(?m)^\s+build:")
        # The recipe is in a file of its own, which names what it builds as this clone's own.
        with open(dmt3.BUILD_FILE, encoding="utf-8") as f:
            recipe = f.read()
        self.assertIn("image: %s" % dmt3.IMAGE, recipe)
        self.assertIn("dockerfile: packaging/docker/Dockerfile", recipe)
        dmt3.cmd_image(args_of("image", "--build"))
        self.assertEqual(self.ran[-1], ["docker", "compose", "-f", dmt3.COMPOSE_FILE, "-f", dmt3.BUILD_FILE,
                                        "build", "server"])
        self.assertEqual(self.env()[dmt3.IMAGE_ENV], dmt3.IMAGE)

    def test_setup_says_which_step_failed(self):
        # Docker not answering: said so.
        with mock.patch.object(dmt3, "docker_ready", return_value=False), \
                self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()) as err:
            dmt3.cmd_setup(args_of("setup", "--no-start"))
        self.assertIn("Docker is not ready", err.getvalue())
        # The image cannot be had (no network, no build): said so, with no word of Docker not being ready.
        self.answers = {"docker pull": (1, ""), "docker compose -f %s -f %s build" % (dmt3.COMPOSE_FILE,
                                                                                     dmt3.BUILD_FILE): (1, "")}
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()) as err:
            dmt3.cmd_setup(args_of("setup", "--no-start"))
        self.assertIn("the server image", err.getvalue())
        self.assertNotIn("Docker is not ready", err.getvalue())
        # The accounts cannot be counted (a broken .env, say): Compose's own words, not Docker's readiness.
        self.images.add(dmt3.published_image())
        self.answers = {"--entrypoint python": (1, "yaml: line 3: could not find expected ':'\n")}
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()) as err:
            dmt3.cmd_setup(args_of("setup", "--no-start"))
        self.assertIn("could not find expected", err.getvalue())
        self.assertNotIn("Docker is not ready", err.getvalue())

    def test_a_new_site_port_moves_the_players_address(self):
        dmt3.write_env({"SITE_ADDRESS": "http://192.168.0.5:4730/"})
        dmt3.cmd_ports(args_of("ports", "--web", "8080"))
        self.assertEqual(self.env()["SITE_ADDRESS"], "http://192.168.0.5:8080/")
        # Back to the usual port: the address follows again.
        dmt3.cmd_ports(args_of("ports", "--web", "4730"))
        self.assertEqual(self.env()["SITE_ADDRESS"], "http://192.168.0.5:4730/")
        # An address of its own, through a proxy (https, no port of the site's): it stays as it was given.
        dmt3.write_env({"SITE_ADDRESS": "https://dmt3.example.org/"})
        dmt3.cmd_ports(args_of("ports", "--web", "8080"))
        self.assertEqual(self.env()["SITE_ADDRESS"], "https://dmt3.example.org/")
        # setup --address with --web-port: the address on the new port.
        dmt3.cmd_ports(args_of("ports", "--web", "4730"))
        self.images.add(dmt3.published_image())
        dmt3.cmd_setup(args_of("setup", "--address", "192.168.0.9", "--web-port", "8090", "--no-start"))
        self.assertEqual(self.env()["SITE_ADDRESS"], "http://192.168.0.9:8090/")

    def test_the_last_backup_kept_on_removal_is_its_owners_alone(self):
        # The backup comes out of the volume as the container prints it.
        done = mock.Mock(returncode=0, stdout=b"SQLite format 3\x00 made-up")
        # Kept in the clone's folder: here the test's own.
        with mock.patch.object(dmt3.subprocess, "run", return_value=done), mock.patch.object(dmt3, "ROOT", self.folder):
            path = dmt3.last_backup_out()
        self.assertEqual(os.path.dirname(path), self.folder)
        if os.name != "nt":
            # Card numbers and password hashes are in it: read and written by its owner alone, as the database is.
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_removal_with_the_data_takes_caddys_volumes_after_expose_off(self):
        # Exposed once, then --off: edge.yaml is no longer read, but Caddy's volumes (its certificates and its local
        # authority's key) are still there to go with the data.
        dmt3.write_env({"SITE_ADDRESS": "http://192.168.0.5:4730/"})
        with mock.patch.object(dmt3, "last_backup_out", return_value=None):
            self.assertEqual(dmt3.cmd_remove(args_of("remove", "--delete-data", "--yes")), 0)
        down = [cmd for cmd in self.ran if "down" in cmd][0]
        self.assertEqual(down, ["docker", "compose", "-f", dmt3.COMPOSE_FILE, "-f", dmt3.EDGE_FILE, "down",
                                "--remove-orphans", "-v"])
        # It looks for what is left of the project before it says everything went.
        self.assertTrue([cmd for cmd in self.ran if cmd[:3] == ["docker", "volume", "ls"]], self.ran)
        self.assertIn("The server and its data are removed", " ".join(self.said))
        # A volume left behind is named, not said gone.
        self.ran.clear()
        self.said.clear()
        self.answers = {"docker volume ls": (0, "opendmt3_edge-data\n")}
        with mock.patch.object(dmt3, "last_backup_out", return_value=None):
            dmt3.cmd_remove(args_of("remove", "--delete-data", "--yes"))
        self.assertIn("opendmt3_edge-data", " ".join(self.said))
        self.assertNotIn("The server and its data are removed", " ".join(self.said))

    def test_expose_off_gives_back_the_address_setup_kept(self):
        dmt3.write_env({"SITE_ADDRESS": "http://192.168.0.5:4730/"})
        dmt3.cmd_expose(args_of("expose", "dmt3.example.org"))
        self.assertEqual(self.env()["SITE_ADDRESS"], "https://dmt3.example.org/")
        dmt3.cmd_expose(args_of("expose", "--off"))
        self.assertEqual(self.env().get("SITE_ADDRESS"), "http://192.168.0.5:4730/")
        # None kept before: none after.
        dmt3.write_env({"SITE_ADDRESS": None})
        dmt3.cmd_expose(args_of("expose", "dmt3.example.org"))
        dmt3.cmd_expose(args_of("expose", "--off"))
        self.assertIsNone(self.env().get("SITE_ADDRESS"))

    def test_the_router_line_names_caddys_own_ports(self):
        dmt3.write_env({"HTTP_PORT": "8081", "HTTPS_PORT": "8443"})
        dmt3.cmd_expose(args_of("expose", "dmt3.example.org"))
        line = [s for s in self.said if s.startswith("On the router")][0]
        self.assertIn("80 to this PC's 8081", line)
        self.assertIn("443 to its 8443", line)
        # The usual ports: the usual line.
        dmt3.write_env({"HTTP_PORT": None, "HTTPS_PORT": None})
        self.said.clear()
        dmt3.cmd_expose(args_of("expose", "dmt3.example.org"))
        self.assertIn("forward TCP 80 and 443 (Caddy)", [s for s in self.said if s.startswith("On the router")][0])


if __name__ == "__main__":
    unittest.main()
