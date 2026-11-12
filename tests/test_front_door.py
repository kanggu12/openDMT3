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
                         ["setup", "catalog", "up", "down", "restart", "status", "logs", "backup", "backups",
                          "restore", "add-player", "check", "doctor", "build", "test"])

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
        self.assertEqual(dmt3.simple_command(args_of("up"), False), COMPOSE + ["up", "-d", "--build"])
        self.assertEqual(dmt3.simple_command(args_of("up", "--no-build"), False), COMPOSE + ["up", "-d"])
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
        self.assertIn("image: %s" % dmt3.IMAGE, text)
        for port in (dmt3.GAME_PORT, dmt3.WEB_PORT):
            self.assertIn('"%d:%d"' % (port, port), text)
        # The game folder kept mounted: read-only, at its own path, and told to the server.
        self.assertIn("OPENDMT3_GAME: ${GAME_DIR:-}", text)
        # The site's address for players, told to the server (its --site-address reads it).
        self.assertIn("OPENDMT3_SITE_ADDRESS: ${SITE_ADDRESS:-}", text)
        for name in ("GAME_DIR", "GAME_LINKS"):
            self.assertRegex(text, r"source: \$\{%s:-[^}]+\}\n\s+target: \$\{%s:-[^}]+\}\n\s+read_only: true"
                             % (name, name))


if __name__ == "__main__":
    unittest.main()
