"""Tests for the launcher's work without its window: remembered settings, the ready check, PLAY, the report,
and the guard that keeps tests from opening windows.

The game folder is the made-up one from test_setup (small archives, a stand-in client the launcher is told is
supported). The game is never started: PLAY gets a stand-in process.
"""

import gc
import importlib.util
import io
import json
import logging
import os
import shutil
import tempfile
import threading
import time
import unittest
import zipfile
from unittest import mock

from opendmt3.core import game as g
from opendmt3.core import safety
from opendmt3.core.cabinet import launch, steps, values
from opendmt3.client import actions, report
from opendmt3.client import state as st
from tests.core import older_setup as older
from tests.core.made_up_game import GameCase
from tests.core.test_setup import FolderCase, settle_looks

try:
    # Only whether this Python has Tk: a server's may not (the launcher brings its own).
    import tkinter
    TK = tkinter.TkVersion >= 8.6
except ImportError:
    TK = False


def _drop_log_file():
    """main() opens the launcher's log in the test's own folder; close it before that folder goes."""
    log = logging.getLogger("opendmt3")
    for handler in [h for h in log.handlers if getattr(h, "opendmt3_log", False)]:
        log.removeHandler(handler)
        handler.close()


class FakeRegistry:
    """The few winreg calls shortcuts.autostart makes, over a dict."""
    HKEY_CURRENT_USER, REG_SZ = "HKCU", 1

    def __init__(self):
        self.values = {}

    def CreateKey(self, root, path):
        return path

    def OpenKey(self, root, path):
        return path

    def CloseKey(self, key):
        pass

    def SetValueEx(self, key, name, reserved, kind, value):
        self.values[(key, name)] = value

    def DeleteValue(self, key, name):
        if (key, name) not in self.values:
            raise FileNotFoundError(name)
        del self.values[(key, name)]

    def QueryValueEx(self, key, name):
        if (key, name) not in self.values:
            raise FileNotFoundError(name)
        return self.values[(key, name)], 1


class FakeProcess:
    """Stands in for the game's process: running until told it exited."""

    def __init__(self):
        self.pid = 4242
        self.code = None

    def poll(self):
        return self.code


class LauncherTest(FolderCase):
    """On FolderCase's made-up game folder (setUp builds it, tearDown removes it)."""

    def setUp(self):
        super().setUp()
        self.config = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"OPENDMT3_CONFIG_DIR": self.config})
        self.env.start()
        # The launcher is told the stand-in client is the supported build, and the table came from it.
        client = self.game.path("Client.exe")
        self.base = mock.patch.object(g.Game, "base_client", lambda game: client)
        self.base.start()
        self.patcher.stop()
        table = self.table

        def table_of(game):
            game.client = (game.path("Client.exe"), g.ORIGINAL)
            return table

        self.patcher = mock.patch.object(g.Game, "table", table_of)
        self.patcher.start()
        # A stand-in for openDMT3's built card reader library (a copy of the repository has none).
        self.dll = os.path.join(self.config, "built", "CRT_R1.dll")
        os.makedirs(os.path.dirname(self.dll))
        with open(self.dll, "wb") as f:
            f.write(b"MZ openDMT3 library stand-in")
        self.library = mock.patch.dict(os.environ, {"OPENDMT3_CARD_READER": self.dll})
        self.library.start()
        self.state = st.LauncherState()
        self.state.game_folder = self.tmp
        # On Windows a PLAY holds the playing mutex until its game closes (client/playing.py), and the stand-in game
        # never does: let go after each test, or every later one in this process finds a game running.
        from opendmt3.client import playing
        self.addCleanup(playing.release)

    def tearDown(self):
        # A look's charts' check still going ends first, while this test's folders and stand-ins are there.
        settle_looks()
        _drop_log_file()
        self.library.stop()
        self.base.stop()
        self.env.stop()
        shutil.rmtree(self.config)
        super().tearDown()

    # ------------------------------------------------------------------------------------- state

    def test_state_round_trip_and_defaults(self):
        self.state.set_value("music_volume", 60)
        self.state.language = "ko"
        self.state.save()
        again = st.LauncherState.load()
        self.assertEqual((again.values["music_volume"], again.language, again.game_folder), (60, "ko", self.tmp))
        # Choices not changed keep the game's own defaults.
        self.assertEqual(again.values["vsync"], values.DEFAULTS["vsync"])

    def test_the_language_is_windows_until_the_player_picks_one(self):
        # A first start (no file): the language Windows is shown in, kept as no choice at all.
        fresh = st.LauncherState()
        self.assertIsNone(fresh.picked_language)
        with mock.patch.object(st, "system_language", return_value="ko"):
            self.assertEqual(fresh.language, "ko")
            fresh.save()
            self.assertIsNone(st.LauncherState.load().picked_language)
            self.assertEqual(st.LauncherState.load().language, "ko")
            # Picked: kept whatever Windows says; "system" (or anything unknown) goes back to Windows'.
            fresh.language = "en"
            fresh.save()
            self.assertEqual(st.LauncherState.load().language, "en")
            fresh.language = "system"
            self.assertEqual((fresh.picked_language, fresh.language), (None, "ko"))
        # A file the earliest versions wrote always has a language: their guide asked, so it is the player's choice.
        with open(st.LauncherState.path(), "w", encoding="utf-8") as f:
            json.dump({"version": 1, "language": "en"}, f)
        self.assertEqual(st.LauncherState.load().picked_language, "en")
        # Off Windows the answer is English, so no test depends on the computer's language.
        self.assertEqual(st.system_language(), "en")

    def test_repair_puts_back_the_programs_files_from_the_installed_package(self):
        import zipfile
        from opendmt3.client import main, repair
        root = os.path.join(self.config, "install")
        os.makedirs(os.path.join(root, "packages"))
        # The package as Velopack makes it, with an entry that would leave the install folder and one that is no
        # file of the program.
        package = {"lib/app/openDMT3.exe": b"MZ launcher", "lib/app/openDMT3-cmd.exe": b"MZ cmd",
                   "lib/app/sq.version": b"<version>9.9.9</version>", "lib/app/_internal/base.zip": b"python",
                   "lib/app/Squirrel.exe": b"MZ updater", "lib/app/openDMT3_ExecutionStub.exe": b"MZ starter",
                   "lib/app/../outside.txt": b"never", "openDMT3.nuspec": b"<package/>"}
        with zipfile.ZipFile(os.path.join(root, "packages", "openDMT3-9.9.9-full.nupkg"), "w") as z:
            for name, data in package.items():
                z.writestr(name, data)
        # Installed as Velopack lays it out: current\\ and, one folder up, the updater and the starter.
        laid = {("current", "openDMT3.exe"): b"MZ launcher", ("current", "openDMT3-cmd.exe"): b"MZ cmd",
                ("current", "sq.version"): b"<version>9.9.9</version>", ("current", "_internal", "base.zip"): b"python",
                ("Update.exe",): b"MZ updater", ("openDMT3.exe",): b"MZ starter"}
        for parts, data in laid.items():
            os.makedirs(os.path.join(root, *parts[:-1]), exist_ok=True)
            with open(os.path.join(root, *parts), "wb") as f:
                f.write(data)
        first = repair.run(root)
        self.assertEqual((first.checked, first.restored), (6, 0))
        # A file gone (a cleaner), one changed (a disk fault), one in use that Windows will not let be written over.
        os.remove(os.path.join(root, "current", "_internal", "base.zip"))
        with open(os.path.join(root, "Update.exe"), "wb") as f:
            f.write(b"MZ damaged")
        locked = os.path.join(root, "current", "openDMT3.exe")
        with open(locked, "wb") as f:
            f.write(b"MZ damaged too")
        real_replace = os.replace
        moved = []

        def in_use(src, dst):
            # As Windows treats a running program's file: never written over, but it can be renamed away.
            if src == locked:
                moved.append(dst)
            elif dst == locked and src.endswith(repair.PART) and not moved:
                raise PermissionError(13, "in use", dst)
            return real_replace(src, dst)

        with mock.patch.object(repair.os, "replace", in_use), mock.patch.object(repair, "PAUSE", 0):
            done = repair.run(root)
        self.assertEqual(done.missing, [os.path.join("current", "_internal", "base.zip")])
        self.assertEqual(sorted(done.changed), sorted([os.path.join("current", "openDMT3.exe"), "Update.exe"]))
        self.assertEqual((done.restored, done.failed, done.needs_restart), (3, [], True))
        for parts, data in ((("current", "_internal", "base.zip"), b"python"), (("Update.exe",), b"MZ updater"),
                            (("current", "openDMT3.exe"), b"MZ launcher")):
            with open(os.path.join(root, *parts), "rb") as f:
                self.assertEqual(f.read(), data, parts)
        # The file in use went aside; the next repair (the program closed by then) takes it away.
        self.assertEqual(moved, [locked + repair.ASIDE])
        self.assertFalse(os.path.exists(os.path.join(self.config, "outside.txt")))
        again = repair.run(root)
        self.assertEqual((again.checked, again.restored), (6, 0))
        self.assertFalse([n for _, _, names in os.walk(root) for n in names if n.endswith((repair.ASIDE, repair.PART))])
        # A file Windows will not let go of at all: counted, kept as it was (never made a missing one).
        with open(locked, "wb") as f:
            f.write(b"MZ damaged again")

        def held(src, dst):
            if locked in (src, dst):
                raise PermissionError(13, "held", dst)
            return real_replace(src, dst)

        with mock.patch.object(repair.os, "replace", held), mock.patch.object(repair, "PAUSE", 0):
            partly = repair.run(root)
        self.assertEqual((partly.restored, partly.failed), (0, [os.path.join("current", "openDMT3.exe")]))
        with open(locked, "rb") as f:
            self.assertEqual(f.read(), b"MZ damaged again")
        # No package, a package that is not one, a launcher that was not installed: said in words.
        package_file = os.path.join(root, "packages", "openDMT3-9.9.9-full.nupkg")
        with open(package_file, "wb") as f:
            f.write(b"not a zip")
        for undo, key in ((lambda: None, "error.repair.package"),
                          (lambda: os.remove(package_file), "error.repair.no_package"),
                          (lambda: os.remove(os.path.join(root, "current", "sq.version")), "error.repair.not_installed")):
            undo()
            with self.assertRaises(repair.RepairError) as caught:
                repair.run(root)
            self.assertEqual(caught.exception.key, key)
        # From source there is no install to repair: --repair says so and ends with 2.
        self.assertEqual(main.main(["--repair"]), 2)

    def test_the_card_is_in_openDMT3s_folder_only_while_the_game_runs(self):
        from types import SimpleNamespace
        from opendmt3.client import actions
        game = self.state.own()
        folder = game.folder
        os.makedirs(folder)
        # A link planted at the card file's name: the card goes into a new file, the link's target is untouched.
        target = os.path.join(self.config, "elsewhere.txt")
        with open(target, "w") as f:
            f.write("someone's file")
        os.symlink(target, os.path.join(folder, actions.CARD_FILE))
        actions.put_card(game, "12345678901234567890")
        self.assertFalse(os.path.islink(os.path.join(folder, actions.CARD_FILE)))
        with open(target) as f:
            self.assertEqual(f.read(), "someone's file")
        with open(os.path.join(folder, actions.CARD_FILE)) as f:
            self.assertEqual(f.read(), "12345678901234567890\n")
        # Only a number the card reader takes.
        with self.assertRaises(ValueError):
            actions.put_card(game, "1234\r\nserverip=6.6.6.6")
        # The game has closed: the card leaves the folder with the run's record.
        actions.put_card(game, "12345678901234567890")
        session = SimpleNamespace(seconds=lambda: 60.0, exit_code=lambda: 0, started=0)
        with mock.patch("opendmt3.core.cabinet.launch.crash_dumps", lambda own, since: []):
            actions.finish(self.state, session)
        self.assertFalse(os.path.lexists(os.path.join(folder, actions.CARD_FILE)))

    def test_an_installer_from_a_servers_site_starts_the_launcher_on_that_server(self):
        from opendmt3.client import installer
        from opendmt3.core import preset
        from opendmt3.client import main
        # The installer's file as a server's site hands it out: its own bytes, then the server on its end.
        exe = os.path.join(self.config, "openDMT3-win-Setup.exe")
        with open(exe, "wb") as f:
            f.write(b"MZ the installer" + preset.tail("http://192.168.0.10:4730", "192.168.0.10:4730"))
        with mock.patch.dict(os.environ, {"OPENDMT3_SETUP_FILE": exe}):
            details = preset.read(installer.setup_file())
        self.assertEqual(details, {"url": "http://192.168.0.10:4730", "name": "192.168.0.10:4730"})
        # A release's own installer, or an end that is not one: nothing.
        with open(exe, "wb") as f:
            f.write(b"MZ the installer" + b"\xff" * 4 + preset.MAGIC)
        self.assertIsNone(preset.read(exe))
        # Installed: left for the launcher, which takes it once at its next start and plays on that server.
        self.state.mode, self.state.server_url, self.state.remote = "this_pc", "http://192.0.2.9:4730", {"card": "1"}
        self.state.save()
        installer.hand_over(details)
        self.assertEqual(main.main(["--status"]), 1)
        saved = st.LauncherState.load()
        self.assertEqual((saved.mode, saved.server_url, saved.remote), ("server", "http://192.168.0.10:4730", None))
        self.assertFalse(os.path.exists(os.path.join(self.config, preset.FILE_NAME)))

    def test_the_installer_speaks_the_launchers_language(self):
        from opendmt3.client import installer
        from opendmt3.client import i18n
        self.state.language = "ko"
        self.state.save()
        self.assertEqual(installer.language(), "ko")
        kind, tab, question, detail, words, action = installer.plan(None, "0.11.0", False, i18n.Words("ko"))
        self.assertEqual((tab, question, words, action), ("설치", "openDMT3 0.11.0 버전을 설치할까요?", "설치", "install"))
        # Settings it cannot read: the language Windows is shown in.
        with open(st.LauncherState.path(), "w", encoding="utf-8") as f:
            f.write("{ broken")
        with mock.patch.object(st, "system_language", return_value="ko"):
            self.assertEqual(installer.language(), "ko")

    def test_a_newer_file_is_refused_and_a_bad_value_falls_back(self):
        path = st.LauncherState.path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": st.VERSION + 1}, f)
        with self.assertRaises(st.StateError):
            st.LauncherState.load()
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "values": {"music_volume": 900}, "language": "fr"}, f)
        loaded = st.LauncherState.load()
        # A hand-edited value out of range does not stop the launcher; the defaults come back.
        self.assertEqual((loaded.values["music_volume"], loaded.language), (100, "en"))

    # --------------------------------------------------------------------------------- ready check

    def test_ready_check_lists_what_play_will_change(self):
        checks = {c.key: c for c in actions.readiness(self.state)}
        self.assertTrue(checks["folder"].ok)
        self.assertTrue(checks["client"].ok)
        # Nothing is set up yet, so the steps are listed as work for PLAY, not as problems.
        self.assertFalse(checks["step:settings"].ok)
        # With no server chosen, the address line is left out.
        self.assertNotIn("step:server address", checks)

    def test_ready_check_stops_play_without_the_tutorial(self):
        os.remove(self.game.path("pack", g.TUTORIAL + ".pak"))
        checks = actions.readiness(self.state)
        self.assertEqual([(c.key, c.ok) for c in checks][-1], ("files", False))
        self.assertIn("tutorial", checks[-1].detail)
        self.assertFalse(actions.can_play(checks))

    def test_ready_check_stops_play_when_the_first_song_has_no_charts(self):
        from opendmt3.core import charts
        with mock.patch.object(charts, "check", lambda game, keep=None: {"songs": 3, "without": ["b"], "first": ["b"]}):
            checks = actions.readiness(self.state)
        self.assertEqual([(c.key, c.ok) for c in checks][-1], ("files", False))
        self.assertIn("first song", checks[-1].detail)
        self.assertFalse(actions.can_play(checks))
        # Songs without charts that the game does not show first: PLAY goes (the card says how many).
        with mock.patch.object(charts, "check", lambda game, keep=None: {"songs": 3, "without": ["b"], "first": []}):
            self.assertTrue(actions.can_play(actions.readiness(self.state)))

    def test_ready_check_without_a_folder(self):
        self.state.game_folder = None
        checks = actions.readiness(self.state)
        self.assertEqual([(c.key, c.ok) for c in checks], [("folder", False)])

    def test_a_line_that_stops_play_says_why_in_the_players_language_and_where_to_fix_it(self):
        from opendmt3.client import i18n
        en, ko = i18n.Words("en"), i18n.Words("ko")

        def cabinets(game):
            raise g.GameError("The cabinet's client: does not work here, the PC client is needed.",
                              "error.game.cabinet_client")

        # The cabinet's client: the card's own sentence, and the Game page (where another folder is chosen), never
        # Help, which only repeated the check.
        with mock.patch.object(g.Game, "table", cabinets):
            checks = actions.readiness(self.state)
        stop = checks[-1]
        self.assertEqual((stop.key, stop.ok, stop.page), ("client", False, "game"))
        self.assertEqual(actions.blocking(checks), [stop])
        self.assertEqual(actions.said(stop, ko), "기체용 클라이언트: 여기서는 못 씁니다. PC 클라이언트가 필요합니다.")
        self.assertEqual(actions.why_not(stop, en), "The cabinet's client: does not work here, the PC client is needed.")
        # A copy without the file with the tutorial: the card's line, in both languages.
        os.remove(self.game.path("pack", g.TUTORIAL + ".pak"))
        stop = actions.readiness(self.state)[-1]
        self.assertEqual((stop.key, stop.page, stop.line), ("files", "game", ("intake.line.no_tutorial", {})))
        self.assertTrue(actions.why_not(stop, ko).startswith("튜토리얼이 든 파일이 없어"))
        self.assertTrue(actions.why_not(stop, en).startswith("The file with the tutorial is missing"))
        # No folder: its own reason. A sign-in that is missing and a game that is open have the launcher's sentence.
        self.state.game_folder = None
        self.assertEqual(actions.why_not(actions.readiness(self.state)[0], en), "No client data chosen yet.")
        self.assertEqual(actions.why_not(actions.Check("remote", False, "not signed in", page="online"), en),
                         "Sign in on the Online page first.")
        self.assertEqual(actions.why_not(actions.Check("running", False, "the game is open: close it first"), ko),
                         "게임이 열려 있습니다. 먼저 닫으세요.")
        # A line with nothing under it says nothing there.
        self.assertIsNone(actions.said(actions.Check("remote", False, "not signed in", page="online"), en))

    def test_a_game_file_cut_short_stops_play_in_the_cards_words(self):
        from opendmt3.client import i18n
        # A copy that stopped half way: the files with the song list are a few bytes each.
        cut = [name for name in os.listdir(self.game.path("pack")) if name.lower().startswith("discinfo")]
        self.assertTrue(cut)
        for name in cut:
            with open(self.game.path("pack", name), "r+b") as f:
                f.truncate(48)
        checks = actions.readiness(self.state)
        stop = checks[-1]
        self.assertEqual((stop.key, stop.ok, stop.page), ("files", False, "game"))
        self.assertFalse(actions.can_play(checks))
        # The card's own sentence in the player's language, never the reader's ("shorter than an archive's header").
        self.assertEqual(stop.error.key, "error.game.damaged.songs")
        self.assertEqual(actions.why_not(stop, i18n.Words("ko")),
                         "곡 목록이 든 파일이 손상됐습니다. 클라이언트 데이터를 다시 복사하거나 압축 파일을 다시 푸세요.")
        self.assertNotIn("header", actions.why_not(stop, i18n.Words("en")))
        # PLAY itself says the same when it is pressed all the same (the command line's --play).
        with self.assertRaises(g.GameError) as e:
            actions.prepare(self.state)
        self.assertTrue(e.exception.key.startswith("error.game.damaged"))

    def test_a_modified_pc_client_plays_with_a_note_under_its_line(self):
        from opendmt3.client import i18n
        table = self.table

        def modified(game):
            game.client = (game.path("Client.exe"), g.MODIFIED)
            return table

        with mock.patch.object(g.Game, "table", modified):
            checks = {c.key: c for c in actions.readiness(self.state)}
        # It plays (the line is fine), and the card's line says what it plays without.
        self.assertTrue(checks["client"].ok)
        self.assertEqual(actions.said(checks["client"], i18n.Words("en")), "Played without the screen fit.")
        self.assertEqual(actions.said(checks["client"], i18n.Words("ko")), "화면 맞춤 없이 씁니다.")
        # The PC client as released has nothing to add, and one name in the check: its copy is named apart.
        self.assertIsNone(actions.said(actions.readiness(self.state)[1], i18n.Words("en")))
        self.assertEqual((i18n.Words("en")("check.client"), i18n.Words("en")("check.step:client")),
                         ("PC client", "Copy of the PC client"))

    def test_the_command_lines_ready_check_uses_the_windows_names(self):
        from opendmt3.client import cli, main
        said = []
        # The command line reads what the launcher keeps: the made-up folder, kept.
        self.state.save()
        with mock.patch.object(cli, "say", lambda text, error=False: said.append(text)):
            self.assertEqual(main.main(["--check"]), 0)
        text = "\n".join(said)
        # Each line by the name the window gives it; what PLAY makes ready by itself is not a thing to do.
        self.assertIn("  [ok  ] Client data: ", text)
        self.assertIn("  [ok  ] PC client: supported client", text)
        self.assertIn("  [play] Game settings (screen, sound): ", text)
        self.assertNotIn("step:", text)
        self.assertNotIn("[todo]", text)
        # A line that stops PLAY is the thing to do.
        self.state.game_folder = os.path.join(self.config, "moved away")
        self.state.save()
        said.clear()
        with mock.patch.object(cli, "say", lambda text, error=False: said.append(text)):
            self.assertEqual(main.main(["--check"]), 1)
        self.assertTrue(said[0].startswith("  [todo] Client data: no client data (the game's PC client and its files) "
                                           "at or below "))

    # ------------------------------------------------------------------------------------- PLAY

    def test_play_makes_openDMT3s_folder_then_starts_the_game(self):
        # The stand-in client is no build the screen fit knows: its copy is the client as it is (test_own covers
        # the fit and the libraries).
        before = self._files()
        own = self.state.own()
        started = []

        def popen(args, cwd, env=None):
            started.append((args, cwd, env))
            return FakeProcess()

        self.state.set_value("display_mode", "window")
        self.state.set_value("frame_pacing", "even")
        self.state.set_value("sound_device", "{0000000a-0000-0000-0000-00000000000b}")
        self.state.language = "ko"
        session = actions.play(self.state, popen=popen)
        # openDMT3's copy of the client starts from openDMT3's folder, the game folder as its current folder, and
        # nothing in the game folder changed.
        self.assertEqual([s[:2] for s in started], [([own.client()], self.game.root)])
        self.assertEqual(self._files(), before)
        self.assertFalse(os.path.exists(self.game.path("backup")))
        # The in-game layer's choices go in the game's environment, on top of the launcher's own.
        env = started[0][2]
        self.assertEqual((env["OPENDMT3_LANGUAGE"], env["OPENDMT3_PACING"], env["OPENDMT3_SOUND_DEVICE"],
                          env["OPENDMT3_CURSOR"]), ("ko", "even", "{0000000A-0000-0000-0000-00000000000B}", "on"))
        self.assertEqual(env.get("PATH"), os.environ.get("PATH"))
        self.assertTrue(session.running())
        # openDMT3's settings for the game now have the choice: a framed window.
        with open(own.path("setting.ini"), "rb") as f:
            self.assertIn(b"popup_style=false", f.read())
        session.process.code = 0
        # The layer's safety net stepped the picture down in this run: its note is read into the log and goes.
        with open(own.path(actions.PICTURE_NOTE), "w", encoding="ascii") as f:
            f.write("stepped down to upscale nis, anti-aliasing fxaa at frame 400\n")
        with self.assertLogs("opendmt3", level="INFO") as said:
            record = actions.finish(self.state, session)
        self.assertEqual((record["exit_code"], record["dumps"], record["crashed"]), (0, 0, False))
        self.assertEqual(record["picture_steps"], ["stepped down to upscale nis, anti-aliasing fxaa at frame 400"])
        self.assertTrue(any("in-game picture stepped down" in line for line in said.output))
        self.assertFalse(os.path.exists(own.path(actions.PICTURE_NOTE)))
        self.assertEqual(record["picture_times"], [])
        # The picture's GPU time by pass, when it was measured: each line of the layer's note into the log, and it goes.
        times = ("1920x1080 keep, upscale fsr1, sharpness 50, anti-aliasing off: game 900.0 us, timestamp 1.0 us, "
                 "easu 400.0 us, rcas 150.0 us, all 560.0 us (600 frames)")
        with open(own.path(actions.PICTURE_TIMES_NOTE), "w", encoding="ascii") as f:
            f.write(times + "\n" + times + "\n")
        with self.assertLogs("opendmt3", level="INFO") as said:
            record = actions.finish(self.state, session)
        self.assertEqual(record["picture_times"], [times, times])
        self.assertEqual(sum("picture's GPU time by pass at 1920x1080 keep" in line for line in said.output), 2)
        self.assertFalse(os.path.exists(own.path(actions.PICTURE_TIMES_NOTE)))
        self.assertIsNone(record["sound_engine"])
        # The sound engine's period the game ran at: the layer's note read into the log and kept with the run.
        with open(own.path(actions.SOUND_NOTE), "w", encoding="ascii") as f:
            f.write("engine held output=default device={0000000A-0000-0000-0000-00000000000B} rate=48000 default=480 "
                    "step=16 min=128 max=480 before=480 asked=128 got=128 hr=0x00000000\n")
        with self.assertLogs("opendmt3", level="INFO") as said:
            record = actions.finish(self.state, session)
        self.assertEqual((record["sound_engine"]["result"], record["sound_engine"]["got"],
                          record["sound_engine"]["rate"]), ("held", 128, 48000))
        self.assertTrue(any("sound engine ran at 128 frames (2.7 ms) a period on Windows' default output" in line
                            for line in said.output), said.output)
        self.assertFalse(os.path.exists(own.path(actions.SOUND_NOTE)))
        # An error code within the first half minute: the game never got going (a missing DLL under Wine did this).
        session.process.code = 53
        self.assertTrue(actions.finish(self.state, session)["crashed"])

    def test_the_sound_engines_period_from_the_layers_note(self):
        from opendmt3.client import i18n
        own = self.state.own()
        os.makedirs(own.folder, exist_ok=True)
        chosen = "{0000000A-0000-0000-0000-00000000000B}"
        line = ("engine held output=chosen device=%s rate=48000 default=480 step=16 min=128 max=480 before=480 "
                "asked=128 got=128 hr=0x00000000" % chosen)
        # Every word and number the layer writes, read back.
        self.assertEqual(actions.engine_from_line(line),
                         {"result": "held", "output": "chosen", "device": chosen, "rate": 48000, "default": 480,
                          "step": 16, "min": 128, "max": 480, "before": 480, "asked": 128, "got": 128,
                          "hr": "0x00000000"})
        # A line that is not the layer's is no record; what it does not know is left out.
        self.assertIsNone(actions.engine_from_line("engine faster rate=48000"))
        self.assertIsNone(actions.engine_from_line("held rate=48000"))
        self.assertEqual(actions.engine_from_line("engine off rate=x device=Speakers extra=1"), {"result": "off"})
        # The note: read, logged, gone; one that is not the layer's is said and goes too; none is nothing.
        with open(own.path(actions.SOUND_NOTE), "w", encoding="ascii") as f:
            f.write("not a note\n")
        with self.assertLogs("opendmt3", level="WARNING"):
            self.assertEqual(actions.sound_notes(own), (None, None))
        self.assertFalse(os.path.exists(own.path(actions.SOUND_NOTE)))
        self.assertEqual(actions.sound_notes(own), (None, None))
        # Both of the layer's lines: who mixed the run, then the engine's period.
        with open(own.path(actions.SOUND_NOTE), "w", encoding="ascii") as f:
            f.write("mixer chosen=openal played=openal failed=- hr=0x00000000\n" + line + "\n")
        with self.assertLogs("opendmt3", level="INFO") as said:
            mixer, engine = actions.sound_notes(own)
        self.assertEqual((mixer["played"], engine["result"]), ("openal", "held"))
        self.assertTrue(any("mixed by OpenAL Soft (shared)" in out for out in said.output), said.output)
        # The Sound page's line: the period the last game ran at on the device chosen now, and only then.
        held = actions.engine_from_line(line)
        self.assertEqual(actions.sound_engine_line(held, chosen.lower()),
                         ("sound.low_latency.held", {"ms": "2.7", "usual": "10"}))
        self.assertIsNone(actions.sound_engine_line(held, "{0000000C-0000-0000-0000-00000000000D}"))
        self.assertIsNone(actions.sound_engine_line(held, values.DEFAULT_DEVICE))
        default = dict(held, output="default")
        self.assertIsNotNone(actions.sound_engine_line(default, values.DEFAULT_DEVICE))
        self.assertIsNone(actions.sound_engine_line(default, chosen))
        # The engine kept its default (Wine; a driver with nothing shorter): said as the period it stayed at.
        kept = dict(default, result="unchanged", asked=240, got=480)
        self.assertEqual(actions.sound_engine_line(kept, values.DEFAULT_DEVICE),
                         ("sound.low_latency.kept", {"ms": "10"}))
        # Another program's shorter period held: what the game's sound went in, from the period before the ask.
        locked = dict(default, result="locked", before=256, got=0)
        self.assertEqual(actions.sound_engine_line(locked, values.DEFAULT_DEVICE),
                         ("sound.low_latency.other", {"ms": "5.3"}))
        # Held at a period another program had asked for already: not credited to Low latency either.
        self.assertEqual(actions.sound_engine_line(dict(default, before=128), values.DEFAULT_DEVICE)[0],
                         "sound.low_latency.other")
        # Off, or nothing known of the periods: no line.
        for none in ({"result": "off", "output": "default"}, {"result": "no-device", "output": "default"},
                     None, {}):
            with self.subTest(record=none):
                self.assertIsNone(actions.sound_engine_line(none, values.DEFAULT_DEVICE))
        # The page's words take their values in both languages.
        for language in ("en", "ko"):
            words = i18n.Words(language)
            self.assertIn("2.7", words("sound.low_latency.held", ms="2.7", usual="10"))
            self.assertIn("10", words("sound.low_latency.kept", ms="10"))
            self.assertIn("5.3", words("sound.low_latency.other", ms="5.3"))
        # The log's line for one that changed nothing names what it found.
        self.assertIn("not made shorter on Windows' default output", actions.engine_said(kept))
        self.assertIn("left as Windows has it", actions.engine_said({"result": "off"}))

    def test_the_mixer_from_the_layers_note(self):
        # Every word the layer writes, read back; OpenAL Soft's failure with its step and error, and the device.
        chosen = "{0000000A-0000-0000-0000-00000000000B}"
        line = ("mixer chosen=openal-exclusive played=directsound output=chosen device=%s failed=device "
                "hr=0x88780078" % chosen)
        self.assertEqual(actions.mixer_from_line(line), {"chosen": "openal-exclusive", "played": "directsound",
                                                          "output": "chosen", "device": chosen, "failed": "device",
                                                          "hr": "0x88780078"})
        self.assertEqual(actions.mixer_from_line("mixer chosen=directsound played=directsound failed=- hr=x"),
                         {"chosen": "directsound", "played": "directsound", "output": None, "device": None,
                          "failed": None, "hr": None})
        # Names the launcher does not offer are not the layer's line.
        for bad in ("mixer chosen=xaudio played=directsound", "mixer played=directsound", "engine held", ""):
            with self.subTest(line=bad):
                self.assertIsNone(actions.mixer_from_line(bad))
        record = actions.mixer_from_line(line)
        self.assertIn("OpenAL Soft (exclusive) was chosen and did not open (at its device, 0x88780078): Windows' "
                      "DirectSound mixed the game's sound", actions.mixer_said(record))
        # The Sound page says DirectSound played only for the Mixer and the device chosen now, and only when OpenAL
        # Soft did not open.
        self.assertEqual(actions.sound_mixer_line(record, "openal-exclusive", chosen.lower()), "sound.mixer.fell_back")
        self.assertIsNone(actions.sound_mixer_line(record, "openal", chosen))
        self.assertIsNone(actions.sound_mixer_line(record, "openal-exclusive", values.DEFAULT_DEVICE))
        other = "{0000000C-0000-0000-0000-00000000000D}"
        self.assertIsNone(actions.sound_mixer_line(record, "openal-exclusive", other))
        self.assertIsNone(actions.sound_mixer_line(dict(record, played="openal-exclusive"), "openal-exclusive", chosen))
        self.assertIsNone(actions.sound_mixer_line(None, "directsound", chosen))
        # Windows' default output then and now; the libraries not loading said apart from the device not opening.
        default = dict(record, output="default", device="{00000000-0000-0000-0000-000000000000}")
        self.assertEqual(actions.sound_mixer_line(default, "openal-exclusive", values.DEFAULT_DEVICE),
                         "sound.mixer.fell_back")
        for step in ("path", "settings", "openal", "dsoal"):
            with self.subTest(step=step):
                self.assertEqual(actions.sound_mixer_line(dict(default, failed=step), "openal-exclusive",
                                                          values.DEFAULT_DEVICE), "sound.mixer.not_loaded")
        from opendmt3.client import i18n
        for language in ("en", "ko"):
            for key in ("sound.mixer.fell_back", "sound.mixer.not_loaded"):
                self.assertIn("OpenAL Soft", i18n.Words(language)(key))

    def test_two_launchers_never_get_the_game_ready_at_once(self):
        from opendmt3.client import playing
        made, closed = [], []

        class Kernel32:
            def CreateMutexW(self, attributes, owner, name):
                made.append(name)
                return 100 + len(made)

            def CloseHandle(self, handle):
                closed.append(handle)

        errors = iter([0, playing.ALREADY_EXISTS])
        with mock.patch.object(playing, "_windows", lambda: True), \
                mock.patch.object(playing, "_kernel32", lambda: Kernel32()), \
                mock.patch.object(playing, "_last_error", lambda: next(errors)), \
                mock.patch.object(playing, "_handle", None):
            # The first launcher's PLAY holds the mutex from its start.
            self.assertTrue(playing.claim())
            # A second launcher (another process) finds it held: its look closes and it says so.
            playing._handle = None
            self.assertFalse(playing.claim())
            self.assertEqual(closed, [102])
        # PLAY refuses in its words, and changes nothing in openDMT3's folder.
        with mock.patch.object(playing, "claim", lambda: False):
            with self.assertRaises(g.GameError) as e:
                actions.play(self.state, popen=lambda *a, **k: FakeProcess())
        self.assertEqual(e.exception.key, "error.game.another_play")
        self.assertFalse(os.path.exists(self.state.own().folder))

    def test_a_play_that_fails_lets_the_next_one_go(self):
        from opendmt3.client import playing
        let_go = []
        with mock.patch.object(playing, "claim", lambda: True), \
                mock.patch.object(playing, "release", lambda: let_go.append(True)), \
                mock.patch.object(actions, "prepare", side_effect=g.GameError("stand-in", "error.game.damaged")):
            with self.assertRaises(g.GameError):
                actions.play(self.state, popen=lambda *a, **k: FakeProcess())
        self.assertEqual(let_go, [True])

    def test_a_short_path_left_by_a_launcher_that_ended_goes_at_the_next_start(self):
        from opendmt3.client import playing
        place = os.path.join(self.config, "links")
        os.makedirs(place)
        target = os.path.join(self.config, "a game")
        os.makedirs(target)
        os.symlink(target, os.path.join(place, "game"))
        with mock.patch.object(launch, "link_places", lambda: [place]):
            # A game running (another launcher's): the link it plays through stays.
            with mock.patch.object(playing, "running", lambda: True):
                actions.tidy_after_an_end(self.state)
            self.assertTrue(os.path.lexists(os.path.join(place, "game")))
            actions.tidy_after_an_end(self.state)
        self.assertFalse(os.path.lexists(os.path.join(place, "game")))
        self.assertTrue(os.path.isdir(target))

    def test_a_game_folder_moved_or_gone_between_plays(self):
        started = []

        def popen(args, cwd, env=None):
            started.append(cwd)
            return FakeProcess()

        # The game folder itself is the one chosen (as the guide keeps it).
        self.state.game_folder = self.game.root
        actions.play(self.state, popen=popen)
        first = self.game.root
        # Moved: the folder chosen before is gone, so the ready check stops PLAY and says where to choose one.
        moved = os.path.join(self.tmp, "moved")
        shutil.move(os.path.join(self.tmp, "unpacked"), moved)
        checks = actions.readiness(self.state)
        self.assertEqual([(c.key, c.ok) for c in checks], [("folder", False)])
        with self.assertRaises(g.GameError):
            actions.prepare(self.state)
        # Chosen again where it is now: openDMT3's folder follows it, the client copy started there.
        self.state.game_folder = moved
        with open(os.path.join(moved, "game", "Client.exe"), "ab") as f:
            f.write(b" changed")
        actions.play(self.state, popen=popen)
        self.assertNotEqual(started[-1], first)
        self.assertEqual(started[-1], os.path.join(moved, "game"))
        with open(self.state.own().client(), "rb") as f:
            self.assertTrue(f.read().endswith(b" changed"))

    def test_the_song_list_is_read_ahead_once_and_play_waits_for_it(self):
        from opendmt3.client import hosting
        host = hosting.BuiltinServer(path=os.path.join(self.config, "data", "openDMT3.sqlite"))
        calls, gate, read = [], threading.Event(), {}

        def slow_import(folder, data):
            calls.append(folder)
            gate.wait(10)
            read[1] = {"title": "made-up"}

        with mock.patch.object(hosting.catalog, "import_from", slow_import), \
                mock.patch.object(hosting.catalog, "load", lambda folder: dict(read)), \
                mock.patch.object(hosting.cards, "load", lambda folder: True):
            reading = host.import_catalog_soon(self.tmp)
            self.assertIsNotNone(reading)
            # Asked again while it reads: no second reading.
            self.assertIsNone(host.import_catalog_soon(self.tmp))
            # PLAY's own reading waits for the one under way, then has nothing left to read.
            waiting = threading.Thread(target=host.import_catalog, args=(self.tmp,))
            waiting.start()
            time.sleep(0.2)
            self.assertTrue(waiting.is_alive())
            gate.set()
            waiting.join(10)
            self.assertEqual(calls, [self.tmp])
            # Read: nothing more ahead of the next PLAY.
            self.assertIsNone(host.import_catalog_soon(self.tmp))

    @unittest.skipUnless(TK, "needs Tk, the launcher's window toolkit")
    def test_plays_progress_names_every_part_in_both_languages(self):
        from opendmt3.client import getting_ready, i18n
        shares = [getting_ready.share(phase) for phase in actions.PHASES]
        self.assertEqual(shares, sorted(shares))
        self.assertEqual((shares[0], actions.PHASES[-1]), (0.0, "starting"))
        for language in ("en", "ko"):
            words = i18n.Words(language)
            for phase in actions.PHASES:
                said = getting_ready.phase_words(words, phase)
                self.assertTrue(said and "." not in said.split()[0][:1] and not said.startswith("check."), (phase, said))
            self.assertNotEqual(words("play.getting_ready"), "play.getting_ready")

    def test_play_refuses_while_the_game_runs(self):
        with mock.patch.object(launch, "running_clients", lambda game: [game.path("Client.exe")]):
            with self.assertRaises(g.GameError):
                actions.prepare(self.state)
            with self.assertRaises(g.GameError):
                actions.restore(self.state)

    def test_crash_dumps_of_this_session_only(self):
        # The game writes them into Dump\, which openDMT3's library gives it in openDMT3's folder.
        own = self.state.own()
        dump = own.path("Dump")
        os.makedirs(dump)
        old = os.path.join(dump, "old.dmp")
        with open(old, "wb") as f:
            f.write(b"x")
        os.utime(old, (1000, 1000))
        new = os.path.join(dump, "new.dmp")
        with open(new, "wb") as f:
            f.write(b"x")
        self.assertEqual(launch.crash_dumps(own, since=2000), [new])

    # ------------------------------------------------------------------------------------ report

    def test_report_has_no_user_name(self):
        self.state.save()
        home = os.path.expanduser("~")
        # A log line with the home folder in it, as every path under C:\\Users\\<name> would be.
        logs = os.path.join(self.config, "logs")
        os.makedirs(logs)
        with open(os.path.join(logs, "launcher.log"), "w", encoding="utf-8") as f:
            f.write("opened %s\\Desktop\\game\n" % home)
        out = tempfile.mkdtemp()
        try:
            path = report.make(self.state, out)
            with zipfile.ZipFile(path) as z:
                text = "".join(z.read(n).decode("utf-8", "replace") for n in z.namelist())
            self.assertNotIn(home, text)
            self.assertIn("<user>", text)
        finally:
            shutil.rmtree(out)


    def test_report_leaves_out_what_signs_in(self):
        self.state.mode = "server"
        self.state.server_url = "http://203.0.113.7:4730"
        self.state.remote = {"game": "203.0.113.7:4725", "login_id": "NOVA", "dj_name": "DJ NOVA",
                             "token": "made-up-token-value", "card": "12345678901234567890"}
        self.state.save()
        # The log names the server it plays on, and could hold a card number: both are taken out there too, and
        # a longer number that only contains the address stays as it is.
        logs = os.path.join(self.config, "logs")
        os.makedirs(logs, exist_ok=True)
        with open(os.path.join(logs, "launcher.log"), "w", encoding="utf-8") as f:
            f.write("plays on http://203.0.113.7:4730\ngame at 203.0.113.7:4725 card 12345678901234567890\n"
                    "a neighbour 1203.0.113.70 stays\n")
        out = tempfile.mkdtemp()
        try:
            with zipfile.ZipFile(report.make(self.state, out)) as z:
                text = "".join(z.read(n).decode("utf-8", "replace") for n in z.namelist())
        finally:
            shutil.rmtree(out)
        for secret in ("made-up-token-value", "12345678901234567890", "203.0.113.7:", "//203.0.113.7"):
            self.assertNotIn(secret, text)
        self.assertIn("game at <server>:4725 card <card>", text)
        self.assertIn("1203.0.113.70", text)

    # ------------------------------------------------------------------------------- which card

    def test_the_card_on_this_pc_is_the_chosen_players(self):
        from opendmt3.client import hosting
        host = hosting.BuiltinServer()
        store = host.accounts()
        try:
            row = store.create("NOVA", "pass1234", "DJ NOVA")
        finally:
            store.db.close()
        self.state.mode, self.state.player = "this_pc", "NOVA"
        self.assertEqual(actions.card_for(self.state, host), row["card"])
        self.state.player = None
        self.assertIsNone(actions.card_for(self.state, host))

    def test_another_server_is_asked_for_the_card_at_every_play(self):
        from opendmt3.client import remote
        self.state.mode, self.state.server_url = "server", "http://203.0.113.7:4730"
        self.state.remote = {"game": "203.0.113.7:4725", "token": "t", "card": "11111111111111111111"}
        # The owner set a new password since the sign-in: the server has a new card for it.
        with mock.patch.object(remote, "me", return_value={"card": "22222222222222222222"}):
            self.assertEqual(actions.card_for(self.state), "22222222222222222222")
        # The server no longer takes the sign-in: PLAY stops and the sign-in is forgotten.
        with mock.patch.object(remote, "me", side_effect=remote.RemoteError("sign in first", "sign_in")):
            with self.assertRaises(actions.SignedOut):
                actions.card_for(self.state)
        actions.forget_sign_in(self.state)
        self.assertEqual(self.state.remote, {"game": "203.0.113.7:4725"})
        # The server cannot be reached: PLAY stops with that reason (test_play_stops_when_the_other_server_...).
        self.state.remote = {"game": "203.0.113.7:4725", "token": "t", "card": "11111111111111111111"}
        with mock.patch.object(remote, "me", side_effect=remote.RemoteError("cannot reach")):
            with self.assertRaises(remote.RemoteError):
                actions.card_for(self.state)

    def test_signing_out_ends_the_token_on_the_server_first_then_forgets_it_whatever_it_says(self):
        from opendmt3.client import remote
        self.state.mode, self.state.server_url = "server", "http://203.0.113.7:4730"
        signed = {"game": "203.0.113.7:4725", "version": "0.11.0", "updates": False, "login_id": "NOVA",
                  "dj_name": "DJ NOVA", "card": "1" * 20, "token": "t"}
        kept = {"game": "203.0.113.7:4725", "version": "0.11.0", "updates": False}
        seen = []

        def ended(base, token):
            # What the launcher still knew when it asked the server.
            seen.append((base, token, dict(self.state.remote)))
            return True

        self.state.remote = dict(signed)
        with mock.patch.object(remote, "sign_out", side_effect=ended):
            actions.sign_out(self.state)
        # The server first, with the token still known; then the sign-in forgotten, the server's address kept.
        self.assertEqual(seen, [("http://203.0.113.7:4730", "t", signed)])
        self.assertEqual(self.state.remote, kept)
        # A server that did not end it (no answer, an older one without the call) or any failure on the way: the
        # sign-in is forgotten all the same, and a failure is logged.
        self.state.remote = dict(signed)
        with mock.patch.object(remote, "sign_out", return_value=False):
            actions.sign_out(self.state)
        self.assertEqual(self.state.remote, kept)
        for failure in (remote.RemoteError("cannot reach"), OSError("down"), ValueError("an odd answer")):
            self.state.remote = dict(signed)
            with mock.patch.object(remote, "sign_out", side_effect=failure), \
                    self.assertLogs("opendmt3.launcher", level="ERROR"):
                actions.sign_out(self.state)
            self.assertEqual(self.state.remote, kept, repr(failure))
        # Not signed in: nothing to end, the server is not asked.
        with mock.patch.object(remote, "sign_out") as asked:
            actions.sign_out(self.state)
        asked.assert_not_called()
        self.assertEqual(self.state.remote, kept)

    def test_an_address_with_a_bad_port_is_worded(self):
        from opendmt3.client import remote
        for bad in ("10.0.0.5:4730x", "10.0.0.5:99999"):
            with self.assertRaises(remote.RemoteError, msg=bad):
                remote.normalize(bad)

    def test_a_database_that_cannot_open_is_worded(self):
        from opendmt3.client import hosting
        # A folder where the database file should be: SQLite cannot open it.
        path = os.path.join(self.config, "server", "openDMT3.sqlite")
        os.makedirs(path)
        host = hosting.BuiltinServer(path=path, port=0)
        with self.assertRaises(hosting.HostingError) as e:
            host.start()
        # One plain line: the system's own reason (here "unable to open database file") goes to the log, not here.
        self.assertEqual(str(e.exception), "the server's database cannot be opened")
        # A damaged file: the pages' own connections say the same, worded, instead of failing the window at start.
        damaged = os.path.join(self.config, "damaged.sqlite")
        with open(damaged, "wb") as f:
            f.write(b"not a database " * 512)
        for read in ("accounts", "records", "player_rows"):
            with self.assertRaises(hosting.HostingError, msg=read) as e:
                getattr(hosting.BuiltinServer(path=damaged, port=0), read)()
            self.assertEqual(e.exception.key, "error.host.db")
        # Damaged past its first page: it opens, then the first read of the players fails; the lists say it the same.
        deeper = os.path.join(self.config, "deeper.sqlite")
        host = hosting.BuiltinServer(path=deeper, port=0)
        store = host.accounts()
        store.create("NOVA", "pass1234", "DJ NOVA")
        store.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        # The page the players' table starts on, written over: the file's first page (its version) still reads.
        root = store.db.execute("SELECT rootpage FROM sqlite_master WHERE name = 'accounts'").fetchone()[0]
        size = store.db.execute("PRAGMA page_size").fetchone()[0]
        store.db.close()
        with open(deeper, "r+b") as f:
            f.seek(size * (root - 1))
            f.write(b"\xff" * size)
        host.accounts().db.close()
        with self.assertRaises(hosting.HostingError) as e:
            host.player_rows()
        self.assertEqual(e.exception.key, "error.host.db")


    # ------------------------------------------------------------------------------ records page

    def test_the_records_link_says_why_not(self):
        from opendmt3.client import hosting, i18n
        host = hosting.BuiltinServer(path=os.path.join(self.config, "server", "openDMT3.sqlite"), port=0, web_port=0)
        self.state.mode = "offline"
        with self.assertRaises(g.GameError) as e:
            actions.records_link(self.state, host)
        self.assertEqual(e.exception.key, "error.records.mode")
        self.state.mode, self.state.player = "this_pc", None
        with self.assertRaises(g.GameError) as e:
            actions.records_link(self.state, host)
        self.assertEqual(i18n.Words("ko").error(e.exception), "먼저 플레이할 사람을 고르세요. 손님은 기록 페이지가 없습니다.")
        self.assertIsNone(host.thread)

    # Every library this PC's site needs (python-multipart too): without one the site is not built at all.
    @unittest.skipUnless(all(importlib.util.find_spec(m) for m in ("uvicorn", "starlette", "jinja2", "multipart")),
                         "needs the web libraries")
    def test_the_records_link_opens_the_players_page_on_this_pcs_site(self):
        import http.cookiejar
        import urllib.request
        from opendmt3.client import hosting
        host = hosting.BuiltinServer(path=os.path.join(self.config, "server", "openDMT3.sqlite"), port=0, web_port=0)
        try:
            store = host.accounts()
            made = store.create("NOVA", "pass1234", "DJ NOVA")
            store.db.close()
            self.state.mode, self.state.player, self.state.language = "this_pc", "NOVA", "ko"
            link = actions.records_link(self.state, host)
            self.assertTrue(link.startswith("http://127.0.0.1:"), link)
            browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            with browser.open(link, timeout=10) as page:
                self.assertTrue(page.geturl().endswith("/dj/%d" % made["id"]), page.geturl())
                self.assertIn("DJ NOVA", page.read().decode("utf-8"))
            # The game server runs beside the site, as at PLAY.
            self.assertIsNotNone(host.server)
        finally:
            host.stop()
        self.assertIsNone(host.web_url)

    def test_the_records_page_reads_this_pcs_database_or_says_why_not(self):
        from opendmt3.client import hosting, i18n, remote
        host = hosting.BuiltinServer(path=os.path.join(self.config, "server", "openDMT3.sqlite"), port=0, web_port=0)
        store = host.accounts()
        made = store.create("NOVA", "pass1234", "DJ NOVA")
        store.db.close()
        plays = host.records()
        try:
            plays.add(made["id"], "127.0.0.1:1", 0, {"song": 7, "pattern": 2, "score": 812345, "counts": [0] * 7,
                                                    "raw": bytes(47)})
        finally:
            plays.db.close()
        self.state.mode, self.state.player = "this_pc", "NOVA"
        dj = actions.records(self.state, host)
        self.assertEqual((dj["dj_name"], dj["summary"]["plays"], dj["recent"][0]["score"]), ("DJ NOVA", 1, 812345))
        self.assertEqual(len(dj["activity"]["weeks"]), 12)
        # Never the game server: reading records starts nothing.
        self.assertIsNone(host.thread)
        for mode, player, key in (("this_pc", None, "error.records.guest"), ("offline", "NOVA", "error.records.offline"),
                                  ("server", "NOVA", "error.records.signin")):
            self.state.mode, self.state.player, self.state.remote = mode, player, None
            with self.assertRaises(g.GameError) as e:
                actions.records(self.state, host)
            self.assertEqual(e.exception.key, key)
            self.assertTrue(i18n.Words("ko").error(e.exception))
        # Another server older than the Records page: its /me has no player number.
        self.state.mode, self.state.server_url, self.state.remote = "server", "http://192.0.2.1:4730", {"token": "t"}
        with mock.patch.object(remote, "me", return_value={"login_id": "NOVA"}):
            with self.assertRaises(g.GameError) as e:
                actions.records(self.state, host)
        self.assertEqual(e.exception.key, "error.records.old_server")
        with mock.patch.object(remote, "me", return_value={"player": 4}), \
                mock.patch.object(remote, "dj", return_value={"dj_name": "X"}) as asked:
            self.assertEqual(actions.records(self.state, host), {"dj_name": "X"})
        asked.assert_called_once_with("http://192.0.2.1:4730", "t", 4)

    # ----------------------------------------------------------------------------- removing openDMT3

    def _played(self):
        """The folder as an earlier openDMT3's PLAY left it on this PC (tests/core/older_setup.py): set up in the game
        folder, a card in its reader, the shortcut and starting with Windows on. Returns (the game folder's files
        before, the desktop folder, the registry)."""
        from opendmt3.client import shortcuts
        before = self._files()
        # The steps an earlier PLAY ran for this PC's server (its card reader needed a built launcher).
        from opendmt3.core.backup import Backup
        kept, options = Backup(self.game), older.Options(server="127.0.0.1:4725")
        for rel in older.MANAGED:
            kept.protect(rel)
        # The display fix needs the real client: its fixed copy is written by hand, as the step would write it.
        with open(self.game.path(g.FIXED_EXE), "wb") as f:
            f.write(b"MZ fixed stand-in")
        with mock.patch.object(older.DisplayFix, "status", lambda *a: older.Status(True, "stand-in")):
            for step in older.STEPS:
                if not step.status(self.game, kept, options).done:
                    step.apply(self.game, kept, options)
        actions.put_card(self.game, "1234567890123456")
        self.assertNotEqual(self._files(), before)
        desktop = os.path.join(self.config, "Desktop")
        os.makedirs(desktop, exist_ok=True)
        for name in (shortcuts.SHORTCUT_NAME, "Someone else's.lnk"):
            with open(os.path.join(desktop, name), "wb") as f:
                f.write(b"shortcut")
        registry = FakeRegistry()
        shortcuts.autostart(True, exe="C:\\x\\current\\openDMT3.exe", registry=registry)
        self.state.save()
        return before, desktop, registry

    def _files(self):
        """Every file in the game folder with its hash, backup\\ left out."""
        found = {}
        for folder, dirs, names in os.walk(self.game.root):
            dirs[:] = [d for d in dirs if os.path.join(folder, d) != self.game.path("backup")]
            for name in names:
                path = os.path.join(folder, name)
                found[os.path.relpath(path, self.game.root)] = g.sha256_file(path)
        return found

    def test_removing_openDMT3_puts_the_game_back_and_takes_its_own_things_away(self):
        from opendmt3.client import leaving, shortcuts
        before, desktop, registry = self._played()
        done = leaving.tidy(registry=registry, desktops=[desktop], environ={})
        # The game folder is as it came: every file back, every added file gone, no backup\ left behind.
        self.assertEqual(self._files(), before)
        self.assertFalse(os.path.exists(self.game.path("backup")))
        self.assertIsNone(done["note"])
        # The shortcut that plays at once and starting with Windows are gone; someone else's shortcut stays.
        self.assertEqual(os.listdir(desktop), ["Someone else's.lnk"])
        self.assertFalse(shortcuts.autostart(registry=registry))
        # The settings stay (the app list cannot ask, so nothing is deleted without being asked for).
        self.assertIsNone(done["data"])
        self.assertTrue(os.path.isfile(st.LauncherState.path()))
        # A second run (the hook after Help's Uninstall did the work) changes nothing and says nothing wrong.
        again = leaving.tidy(registry=registry, desktops=[desktop], environ={})
        self.assertEqual((again["game"].put_back, again["note"], again["shortcuts"]), ([], None, []))
        self.assertEqual(self._files(), before)

    def test_uninstalling_names_the_games_files_only_when_an_older_opendmt3_changed_some(self):
        from opendmt3.client import i18n, leaving
        # A folder PLAY alone used: nothing there to put back, so what uninstalling says does not name the game.
        self.assertFalse(leaving.changed_before(self.state))
        # No folder chosen, or one that is gone: nothing to say either.
        folder, self.state.game_folder = self.state.game_folder, None
        self.assertFalse(leaving.changed_before(self.state))
        self.state.game_folder = os.path.join(self.config, "moved away")
        self.assertFalse(leaving.changed_before(self.state))
        # A folder an older openDMT3 changed: its files go back, and only then is that said.
        self.state.game_folder = folder
        self._played()
        self.assertTrue(leaving.changed_before(self.state))
        # The words of the two states: the game's files are named in one line that is there or not.
        en = i18n.Words("en")
        self.assertEqual(en("help.uninstall.game"),
                         "The files an older openDMT3 changed in the client data go back to how they were.")
        self.assertEqual(en("help.uninstall.hint"), "Removes openDMT3 from this PC. You choose then whether the "
                                                    "settings, players and records stay.")
        self.assertNotIn("game", en("help.uninstall.closes"))

    def test_removing_while_the_game_is_open_leaves_word_on_what_is_still_changed(self):
        from opendmt3.core.backup import Backup
        from opendmt3.client import leaving, main, shortcuts
        before, desktop, registry = self._played()
        changed = Backup(self.game).still_changed()
        with mock.patch.object(launch, "running_clients", return_value=[self.game.path("Client.exe")]), \
                mock.patch.object(shortcuts, "desktops", return_value=[desktop]):
            # As Velopack runs it: through the hook, which never fails the removal.
            done = main._before_uninstall("0.10.0")
        # Nothing was written while the game had its files open; the note says what to do by hand.
        self.assertEqual(Backup(self.game).still_changed(), changed)
        self.assertEqual(done["note"], os.path.join(self.game.path("backup"), leaving.NOTE))
        with open(done["note"], encoding="utf-8-sig") as f:
            text = f.read()
        self.assertIn("copy backup\\pack\\DiscInfo.pak back over pack\\DiscInfo.pak", text)
        self.assertIn("delete %s (openDMT3 added it)" % g.SETTINGS.replace("/", "\\"), text)
        # The shortcut goes all the same.
        self.assertEqual(os.listdir(desktop), ["Someone else's.lnk"])
        # In the player's language.
        self.state.language = "ko"
        self.state.save()
        with mock.patch.object(launch, "running_clients", return_value=["x"]):
            with open(leaving.tidy(desktops=[desktop], environ={})["note"], encoding="utf-8-sig") as f:
                self.assertIn("게임을 원래대로 돌리려면", f.read())
        # Removed again once the game is closed: everything goes back, and the note with the rest.
        leaving.tidy(desktops=[desktop], environ={})
        self.assertEqual(self._files(), before)
        self.assertFalse(os.path.exists(self.game.path("backup")))

    def test_removing_with_a_game_folder_that_is_gone_or_never_chosen(self):
        from opendmt3.client import leaving, shortcuts
        desktop = os.path.join(self.config, "Desktop")
        self.state.game_folder = os.path.join(self.config, "moved away")
        self.state.save()
        self.assertFalse(leaving.tidy(desktops=[desktop], environ={})["game"].folder)
        self.state.game_folder = None
        self.state.save()
        self.assertIsNone(leaving.tidy(desktops=[desktop], environ={})["game"])
        # Settings that cannot be read: the game folder is unknown, the rest still goes.
        with open(st.LauncherState.path(), "w", encoding="utf-8") as f:
            f.write("{ broken")
        registry = FakeRegistry()
        registry.values[(shortcuts.RUN_KEY, "openDMT3")] = "x"
        self.assertIsNone(leaving.tidy(registry=registry, desktops=[desktop], environ={})["game"])
        self.assertEqual(registry.values, {})

    def test_removing_everything_deletes_only_what_the_launcher_wrote(self):
        from opendmt3.client import leaving, main
        folder = os.path.join(self.config, "openDMT3")
        with mock.patch.dict(os.environ, {"OPENDMT3_CONFIG_DIR": folder}):
            self.state.save()
            main._logging()
            for name in ("update-pending.json", "launcher.json.broken-20261110-101010", ".launcher-abc123"):
                with open(os.path.join(folder, name), "w") as f:
                    f.write("{}")
            for sub in ("backups", "jackets", "cards/icon", "downloads"):
                os.makedirs(os.path.join(folder, "server", *sub.split("/")))
            os.makedirs(os.path.join(folder, "server", ".song-list-abc123", "jackets"))
            for name in ("openDMT3.sqlite", "openDMT3.sqlite-wal", "openDMT3.sqlite.v3-20261110-101010.bak",
                         "catalog.json", "cards.json", "web.secret", "backups/openDMT3-20261110-000000-daily.sqlite",
                         "jackets/12.png", "cards/icon/6.png", "catalog-read.json", "catalog.log", "catalog.log.1",
                         ".song-list.lock", "maintenance.json", "notice.json.new", ".song-list-upload-x1.zip",
                         ".song-list-abc123/catalog.json", ".song-list-abc123/jackets/3.png"):
                with open(os.path.join(folder, "server", *name.split("/")), "wb") as f:
                    f.write(b"x")
            # Not the launcher's: files someone put there, beside its own and among them.
            for name in ("notes.txt", "server/notes.txt", "server/backups/mine.sqlite"):
                with open(os.path.join(folder, *name.split("/")), "w") as f:
                    f.write("mine")
            desktop = os.path.join(self.config, "Desktop")
            # Asked for by nobody: the app list's removal keeps everything, and so does a variable set by hand.
            for environ in ({}, {leaving.EVERYTHING: "1"}):
                self.assertIsNone(leaving.tidy(desktops=[desktop], environ=environ)["data"])
                self.assertIn("launcher.json", os.listdir(folder))
            # The uninstall the launcher started with the choice on: its token, written in the launcher's folder.
            token = leaving.ask_for_everything(folder)
            done = leaving.tidy(desktops=[desktop], environ={leaving.EVERYTHING: token})
            self.assertEqual(done["data"], ["notes.txt", "server"])
            left = sorted(os.path.relpath(os.path.join(d, n), folder).replace(os.sep, "/")
                          for d, _, names in os.walk(folder) for n in names)
            self.assertEqual(left, ["notes.txt", "server/backups/mine.sqlite", "server/notes.txt"])
            # The log was closed before its folder went, and nothing writes to it after.
            self.assertFalse([h for h in logging.getLogger("opendmt3").handlers if getattr(h, "opendmt3_log", 0)])
            # Without the strangers' files, the folders go too.
            for name in ("notes.txt", "server/notes.txt", "server/backups/mine.sqlite"):
                os.remove(os.path.join(folder, *name.split("/")))
            self.state.save()
            self.assertEqual(leaving.delete_data(folder), [])
            self.assertFalse(os.path.exists(folder))
        # A folder named like the launcher's but holding someone else's things is left alone.
        os.makedirs(os.path.join(folder, "server"))
        with open(os.path.join(folder, "server", "photo.jpg"), "wb") as f:
            f.write(b"x")
        self.assertEqual(leaving.delete_data(folder), ["server"])
        # A file that will not go (in use on Windows) stays, and everything else still goes.
        with open(os.path.join(folder, "launcher.json"), "w") as f:
            f.write("{}")
        with open(os.path.join(folder, "update-pending.json"), "w") as f:
            f.write("{}")
        real_remove = os.remove

        def in_use(path):
            if path.endswith("launcher.json"):
                raise PermissionError(32, "in use by another program", path)
            real_remove(path)
        with mock.patch("os.remove", in_use), mock.patch("os.chmod"):
            self.assertEqual(leaving.delete_data(folder), ["launcher.json", "server"])

    def test_delete_all_knows_every_file_the_server_makes(self):
        # Each name the server's code gives a file in its data folder (a *FILE constant) is one Delete all takes: a new
        # one is never left behind, as catalog-read.json and catalog.log once were.
        import glob
        import re
        from opendmt3.client import leaving
        top = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        names = set()
        for path in glob.glob(os.path.join(top, "opendmt3", "server", "**", "*.py"), recursive=True):
            with open(path, encoding="utf-8") as f:
                names.update(re.findall(r'^[A-Z_]*FILE = "([^"]+)"', f.read(), re.M))
        # The ones this was made for are among them, so the search itself is known to find them.
        self.assertTrue({"catalog.json", "catalog-read.json", "catalog.log", "web.secret"} <= names, names)
        self.assertEqual([n for n in sorted(names) if not leaving.SERVER_NAME.match(n)], [])

    def test_remove_on_the_command_line(self):
        from opendmt3.client import leaving, main, shortcuts
        updater = os.path.join(self.config, "Update.exe")
        with mock.patch.object(leaving, "uninstaller", return_value=None):
            # Not installed by the installer: said, nothing done.
            self.assertEqual(main.main(["--uninstall", "--yes"]), 2)
        before, desktop, registry = self._played()
        with mock.patch.object(leaving, "uninstaller", return_value=updater), \
                mock.patch.object(leaving, "start_uninstall") as start, \
                mock.patch.object(shortcuts, "desktops", return_value=[desktop]):
            # Asked first: no answer, nothing changes.
            with mock.patch("builtins.input", return_value=""):
                self.assertEqual(main.main(["--uninstall"]), 1)
            start.assert_not_called()
            self.assertNotEqual(self._files(), before)
            # The game open: said, nothing changes and nothing is uninstalled.
            with mock.patch.object(launch, "running_clients", return_value=["x"]):
                self.assertEqual(main.main(["--uninstall", "--yes"]), 2)
            start.assert_not_called()
            self.assertIn(shortcuts.SHORTCUT_NAME, os.listdir(desktop))
            self.assertEqual(main.main(["--uninstall", "--yes", "--delete-data"]), 0)
            # The game back first, then Velopack's uninstall, without a window, carrying the choice.
            self.assertEqual(self._files(), before)
            self.assertEqual(os.listdir(desktop), ["Someone else's.lnk"])
            start.assert_called_once_with(updater, True)
            # Settings that cannot be read do not stop it (as in Windows' app list): no game folder is known then.
            with open(st.LauncherState.path(), "w", encoding="utf-8") as f:
                f.write("{ broken")
            self.assertEqual(main.main(["--uninstall", "--yes"]), 0)
            self.assertEqual(start.call_count, 2)

    def test_the_uninstall_starts_on_its_own_and_carries_only_this_choice(self):
        from opendmt3.client import leaving
        started = []
        popen = lambda args, **kw: started.append((args, kw))
        with mock.patch.dict(os.environ, {leaving.EVERYTHING: "1"}):
            # A value from the surroundings never deletes anything.
            leaving.start_uninstall("C:\\o\\Update.exe", popen=popen)
            leaving.start_uninstall("C:\\o\\Update.exe", everything=True, popen=popen)
        (first, kw1), (second, kw2) = started
        # Always silent: Velopack's plain window at the end never shows (the launcher's dialogs said what happens).
        self.assertEqual(first, ["C:\\o\\Update.exe", "--uninstall", "--silent"])
        self.assertNotIn(leaving.EVERYTHING, kw1["env"])
        self.assertEqual(second, ["C:\\o\\Update.exe", "--uninstall", "--silent"])
        # With the choice on, the uninstall carries the token the launcher wrote in its own folder at that moment.
        with open(os.path.join(self.config, leaving.TOKEN), encoding="ascii") as f:
            self.assertEqual(kw2["env"][leaving.EVERYTHING], f.read())
        self.assertTrue(leaving.asked_for_everything(kw2["env"], self.config))
        self.assertFalse(leaving.asked_for_everything({leaving.EVERYTHING: "1"}, self.config))
        # An uninstall that did not happen leaves a token nobody holds: the next removal's hook takes it away.
        leaving.tidy(desktops=[os.path.join(self.config, "Desktop")], environ={})
        self.assertFalse(os.path.exists(os.path.join(self.config, leaving.TOKEN)))
        # Run from source there is nothing to uninstall.
        self.assertIsNone(leaving.uninstaller())

    def test_play_stops_when_the_other_server_does_not_answer(self):
        # TS-LAUNCHER-21: signed in on another server that is down. PLAY stops with the reason; no game starts.
        from opendmt3.client import i18n, remote
        self.state.mode, self.state.server_url = "server", "http://192.0.2.1:4730"
        self.state.remote = {"game": "192.0.2.1:4725", "card": "1" * 20, "token": "t", "dj_name": "DJ NOVA"}
        down = remote.RemoteError("Cannot reach http://192.0.2.1:4730. Check the address and the network.",
                                  key="error.remote.unreachable", base="http://192.0.2.1:4730")
        with mock.patch.object(remote, "me", side_effect=down):
            with self.assertRaises(remote.RemoteError) as e:
                actions.card_for(self.state)
        # What to do, never the system's own reason ("[Errno 101] Network is unreachable" is for the log).
        self.assertEqual(i18n.Words("ko").error(e.exception),
                         "http://192.0.2.1:4730에 연결할 수 없습니다. 주소와 네트워크를 확인하세요.")
        # A sign-in the server no longer takes still sends the player to sign in again.
        with mock.patch.object(remote, "me", side_effect=remote.RemoteError("sign in first", "sign_in")):
            with self.assertRaises(actions.SignedOut):
                actions.card_for(self.state)

    def test_a_game_that_closed_by_itself_is_told_as_a_crash(self):
        # TS-LAUNCHER-20: a crash dump written during the session, or an error code in its first half minute.
        session = mock.Mock(started=time.time() - 60)
        session.seconds.return_value = 60
        session.exit_code.return_value = 0
        self.state.game_folder = self.tmp
        self.assertFalse(actions.finish(self.state, session)["crashed"])
        # The client writes its dump into Dump\, which openDMT3's library gives it in openDMT3's folder.
        own = self.state.own()
        os.makedirs(own.path("Dump"), exist_ok=True)
        with open(own.path("Dump", "crash.dmp"), "wb") as f:
            f.write(b"dump")
        record = actions.finish(self.state, session)
        self.assertEqual((record["crashed"], record["dumps"]), (True, 1))
        session.started = time.time() + 5          # a dump from before this session does not count
        session.seconds.return_value = 10
        session.exit_code.return_value = -1073741819
        self.assertTrue(actions.finish(self.state, session)["crashed"])   # an error code within 30 s
        session.seconds.return_value = 600
        self.assertFalse(actions.finish(self.state, session)["crashed"])  # the same code after ten minutes

    def test_shortcuts_need_the_installed_launcher_and_say_so(self):
        from opendmt3.client import i18n, shortcuts
        with self.assertRaises(g.GameError) as e:
            shortcuts.launcher_exe()
        self.assertEqual(i18n.Words("ko").error(e.exception), "설치한 런처(Windows)에서만 만들 수 있습니다.")

    def test_the_desktop_shortcut_is_made_by_windows_itself(self):
        from opendmt3.client import shortcuts
        ran = []

        def run(command, **kw):
            ran.append((command, kw))
            return mock.Mock(returncode=0, stderr="")

        # Every quote PowerShell ends a string at: the plain one and the curly ones.
        exe = "C:\\Users\\O'Neil \u2018Q\u2019 \u201aR\u201b\\AppData\\Local\\openDMT3\\current\\openDMT3.exe"
        path = shortcuts.make_shortcut(exe=exe, folder=self.config, run=run)
        self.assertEqual(path, os.path.join(self.config, shortcuts.SHORTCUT_NAME))
        script, env = ran[0][0][-1], ran[0][1]["env"]
        # No path in the script: PowerShell reads them from the environment as they are; the shortcut plays at once.
        self.assertNotIn("Neil", script)
        self.assertEqual((env["OPENDMT3_EXE"], env["OPENDMT3_SHORTCUT"]), (exe, path))
        self.assertIn("$s.TargetPath = $env:OPENDMT3_EXE", script)
        self.assertIn("$s.Arguments = '--play'", script)
        failing = lambda command, **kw: mock.Mock(returncode=1, stderr="access denied")
        with self.assertRaises(g.GameError) as e:
            shortcuts.make_shortcut(exe=exe, folder=self.config, run=failing)
        self.assertIn("access denied", str(e.exception))

    def test_playing_when_windows_starts_is_one_value_in_the_users_run_key(self):
        from opendmt3.client import shortcuts
        reg = FakeRegistry()
        self.assertFalse(shortcuts.autostart(registry=reg))
        self.assertTrue(shortcuts.autostart(True, exe="C:\\x\\openDMT3.exe", registry=reg))
        self.assertEqual(reg.values[(shortcuts.RUN_KEY, "openDMT3")], '"C:\\x\\openDMT3.exe" --play')
        self.assertFalse(shortcuts.autostart(False, registry=reg))
        # Off when it is already off is fine.
        self.assertFalse(shortcuts.autostart(False, registry=reg))

    def test_the_uninstall_hook_is_registered_with_velopack(self):
        from opendmt3.client import main
        fake = mock.MagicMock()
        with mock.patch.dict("sys.modules", {"velopack": fake}):
            main._velopack_hooks([])
        app = fake.App.return_value
        app.on_before_uninstall_fast_callback.assert_called_once_with(main._before_uninstall)
        # After every install and update, the app list's line is made the quiet one.
        app.on_after_install_fast_callback.assert_called_once_with(main._after_install)
        app.on_after_update_fast_callback.assert_called_once_with(main._after_install)
        app.run.assert_called_once_with()

    def test_the_app_lists_uninstall_runs_without_velopacks_window(self):
        from opendmt3.client import leaving

        class AppList(FakeRegistry):
            KEY_READ, KEY_SET_VALUE = 1, 2

            def OpenKey(self, root, path, reserved=0, access=0):
                if not any(key == path for key, _ in self.values):
                    raise FileNotFoundError(path)
                return path

        reg = AppList()
        # Not installed: no line to change.
        self.assertFalse(leaving.quiet_app_list(registry=reg))
        line = '"C:\\Users\\p\\AppData\\Local\\openDMT3\\Update.exe" --uninstall'
        reg.values[(leaving.APP_LIST_KEY, "UninstallString")] = line
        reg.values[(leaving.APP_LIST_KEY, "QuietUninstallString")] = line + " --silent"
        self.assertTrue(leaving.quiet_app_list(registry=reg))
        self.assertEqual(reg.values[(leaving.APP_LIST_KEY, "UninstallString")], line + " --silent")
        # Already quiet: left as it is.
        self.assertFalse(leaving.quiet_app_list(registry=reg))

    @unittest.skipUnless(TK, "needs Tk, the launcher's window toolkit")
    def test_play_from_the_shortcut_says_why_it_cannot_go_in_a_window(self):
        # The desktop shortcut runs the window copy with --play: no console, so a printed reason is never seen.
        from opendmt3.client import dialogs, main
        shown = []
        self.state.language = "ko"
        self.state.game_folder = os.path.join(self.config, "moved away")
        self.state.save()
        with mock.patch.object(main, "_windowed", return_value=True), \
                mock.patch.object(dialogs, "standalone", lambda *a, **kw: shown.append(a) or "close"):
            self.assertEqual(main.main(["--play"]), 2)
        kind, title, message, detail = shown[0][:4]
        # What is so, then why in the player's language (the folder's own line, not the code's English), and the way
        # into the launcher.
        self.assertEqual((kind, title, message), ("warn", "플레이", "아직 게임을 시작할 수 없습니다."))
        self.assertIn("아래에 클라이언트 데이터(게임의 PC 클라이언트와 게임 파일)가 없습니다.", detail)
        self.assertNotIn("no client data", detail)
        self.assertTrue(detail.endswith("런처를 열어 확인하세요."))
        self.assertEqual([b[1] for b in shown[0][4]], ["close", "open"])
        # The console copy prints it and opens nothing.
        with mock.patch.object(main, "_windowed", return_value=False), \
                mock.patch.object(dialogs, "standalone") as window:
            self.assertEqual(main.main(["--play"]), 2)
        window.assert_not_called()

    @unittest.skipUnless(TK, "needs Tk, the launcher's window toolkit")
    def test_an_error_nothing_caught_is_said_in_the_launchers_own_window(self):
        from opendmt3.client import dialogs, main
        shown = []
        with mock.patch.object(main, "main", side_effect=RuntimeError("a surprise")), \
                mock.patch.object(main, "_windowed", return_value=True), \
                mock.patch.object(dialogs, "standalone", lambda *a, **kw: shown.append(a) or "close"):
            self.assertEqual(main.run([]), 2)
        kind, title, message, detail = shown[0][:4]
        self.assertEqual((kind, title), ("error", "openDMT3 stopped"))
        # In the window's words (a sentence starts with a capital letter).
        self.assertIn("a surprise", detail.lower())
        # The console copy prints it instead (no window).
        with mock.patch.object(main, "main", side_effect=RuntimeError("a surprise")), \
                mock.patch.object(main, "_windowed", return_value=False), \
                mock.patch.object(dialogs, "standalone") as window:
            self.assertEqual(main.run([]), 2)
        window.assert_not_called()

    def test_one_test_of_a_running_game_for_updates_and_the_installer(self):
        from opendmt3.client import installer
        from opendmt3.client import playing
        running = mock.Mock()
        running.running.return_value = True
        self.assertTrue(playing.game_running(running))
        self.assertFalse(playing.game_running(None))
        with mock.patch.object(playing, "running", return_value=True):
            # A game another launcher (openDMT3-cmd --play) started counts for both.
            self.assertTrue(playing.game_running(None))
            self.assertTrue(installer.game_running())

    def test_this_pcs_server_opens_to_the_other_pcs_only_when_asked(self):
        from opendmt3.client import hosting
        path = os.path.join(self.config, "server", "openDMT3.sqlite")
        for lan, address in ((False, "127.0.0.1"), (True, "0.0.0.0")):
            host = hosting.BuiltinServer(path=path, port=0, web_port=0, lan=lan)
            try:
                host.start()
                game = host.server._server.sockets[0].getsockname()[0]
                self.assertEqual(game, address, lan)
                if lan:
                    # Every address the other PCs see is a private one, with the site's port.
                    for url in host.addresses():
                        ip = url.split("//")[1].split(":")[0]
                        self.assertTrue(ip.startswith(("10.", "192.168.")) or ip.split(".")[0] == "172", url)
                        self.assertTrue(url.endswith(":" + host.web_url.rstrip("/").rsplit(":", 1)[1]), url)
                else:
                    self.assertEqual(host.addresses(), [])
            finally:
                host.stop()
        # The switch is remembered.
        self.state.lan = True
        self.state.save()
        self.assertTrue(st.LauncherState.load().lan)

    def test_lan_and_serve_on_the_command_line(self):
        import contextlib
        import io
        from opendmt3.client import main
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main.main(["--lan", "on"]), 0)
        self.assertTrue(st.LauncherState.load().lan)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main.main(["--lan", "off"]), 0)
        self.assertFalse(st.LauncherState.load().lan)

    def test_updates_come_from_the_server_that_hands_them_out(self):
        from opendmt3.client import updates
        with mock.patch.object(updates, "UPDATE_SOURCE", "https://example.org/built-in"):
            self.state.mode = "this_pc"
            self.assertEqual(updates.source_for(self.state), "https://example.org/built-in")
            self.state.mode, self.state.server_url = "server", "http://192.0.2.1:4730/"
            self.state.remote = {"game": "192.0.2.1:4725", "updates": False}
            self.assertEqual(updates.source_for(self.state), "https://example.org/built-in")
            self.state.remote["updates"] = True
            self.assertEqual(updates.source_for(self.state), "http://192.0.2.1:4730/updates")
        # A check against that feed keeps it for the download (apply uses result.source).
        fake = mock.MagicMock()
        fake.UpdateManager.return_value.check_for_updates.return_value = None
        with mock.patch.dict("sys.modules", {"velopack": fake}):
            result = updates.check("http://192.0.2.1:4730/updates")
        self.assertEqual((result.kind, result.source), ("uptodate", "http://192.0.2.1:4730/updates"))
        fake.UpdateManager.assert_called_with("http://192.0.2.1:4730/updates")

    def test_records_as_text_on_the_command_line(self):
        import contextlib
        import io
        from opendmt3.client import hosting, main
        host = hosting.BuiltinServer()
        store = host.accounts()
        store.create("NOVA", "pass1234", "DJ NOVA")
        store.db.close()
        self.state.mode, self.state.player = "this_pc", "NOVA"
        self.state.save()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main.main(["--records", "--text"]), 0)
        self.assertIn("DJ NOVA: 0 stages cleared", out.getvalue())

    # ------------------------------------------------------------------------- command line twins

    def test_play_on_the_command_line_stops_where_the_window_does(self):
        from opendmt3.client import main
        # Another server without a sign-in: the window's PLAY waits for one; so does --play.
        self.state.mode, self.state.server_url = "server", "http://203.0.113.7:4730"
        self.state.remote = {"game": "203.0.113.7:4725"}
        self.state.save()
        checks = actions.readiness(self.state)
        self.assertFalse(actions.can_play(checks))
        with mock.patch.object(actions, "play") as play:
            self.assertEqual(main.main(["--play"]), 2)
        play.assert_not_called()
        self.assertEqual(main.main(["--check"]), 1)

    def test_the_in_game_layer_choices_have_command_line_twins(self):
        from opendmt3.client import main, sound_devices
        self.state.save()
        # The Screen page's pacing and frame rate chip and the Sound page's device, by --set, kept as the window keeps
        # them.
        self.assertEqual(main.main(["--set", "frame_pacing=even", "--set", "show_fps=on", "--set",
                                    "fps_position=top_left", "--set", "picture_shape=fill", "--set",
                                    "sound_device={0000000a-0000-0000-0000-00000000000b}", "--set", "pass_times=on",
                                    "--set", "audio_offset=180"]), 0)
        saved = st.LauncherState.load()
        self.assertEqual((saved.values["frame_pacing"], saved.values["show_fps"], saved.values["fps_position"],
                          saved.values["picture_shape"], saved.values["sound_device"], saved.values["pass_times"],
                          saved.values["audio_offset"]),
                         ("even", True, "top_left", "fill", "{0000000A-0000-0000-0000-00000000000B}", True, 180))
        # A value the pages do not offer is said, and nothing changes.
        self.assertEqual(main.main(["--set", "frame_pacing=120"]), 2)
        self.assertEqual(st.LauncherState.load().values["frame_pacing"], "even")
        # The Sound page's Low latency, by --set, and what --status says of it with the last game's period, as the
        # page shows it.
        self.assertEqual(main.main(["--set", "low_latency=off"]), 0)
        self.assertIs(st.LauncherState.load().values["low_latency"], False)
        saved = st.LauncherState.load()
        saved.values["low_latency"] = True
        saved.last_session = {"sound_engine": actions.engine_from_line(
            "engine held output=chosen device={0000000A-0000-0000-0000-00000000000B} rate=48000 default=480 step=16 "
            "min=128 max=480 before=480 asked=128 got=128 hr=0x00000000")}
        saved.save()
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            main.main(["--status"])
        self.assertIn("sound: low latency on. In the last game, this device's sound went in 2.7 ms steps (10 ms "
                      "without this).", out.getvalue())
        self.assertIn("sound: {0000000A-0000-0000-0000-00000000000B}, mixer directsound.", out.getvalue())
        # The Mixer by --set, as the page keeps it; a name it does not offer refused; with exclusive mode --status
        # leaves Low latency out (the shared engine is not on its way) and says when DirectSound played instead.
        self.assertEqual(main.main(["--set", "sound_path=OpenAL-Exclusive"]), 0)
        self.assertEqual(st.LauncherState.load().values["sound_path"], "openal-exclusive")
        self.assertEqual(main.main(["--set", "sound_path=xaudio2"]), 2)
        saved = st.LauncherState.load()
        saved.last_session = {"sound_mixer": actions.mixer_from_line(
            "mixer chosen=openal-exclusive played=directsound output=chosen "
            "device={0000000A-0000-0000-0000-00000000000B} failed=device hr=0x88780078")}
        saved.save()
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            main.main(["--status"])
        self.assertIn("mixer openal-exclusive. In the last game, OpenAL Soft could not open the device, so DirectSound "
                      "played.", out.getvalue())
        # Low latency's line too, as the page keeps its row with every Mixer.
        self.assertIn("sound: low latency on.", out.getvalue())
        for bad in ("audio_offset=501", "audio_offset=-20", "audio_offset=fast"):
            with self.subTest(bad=bad):
                self.assertEqual(main.main(["--set", bad]), 2)
        self.assertEqual(st.LauncherState.load().values["audio_offset"], 180)
        # Refused while the window is open, as every write is.
        with mock.patch("opendmt3.client.cli.window_open", return_value=True):
            self.assertEqual(main.main(["--set", "sound_device=default"]), 2)
        self.assertNotEqual(st.LauncherState.load().values["sound_device"], "default")
        # The list of devices: Windows' default first, the chosen one marked, a gone one said.
        out = io.StringIO()
        with mock.patch.object(sound_devices, "listed", return_value=[("{11111111-0000-0000-0000-000000000000}", "Speakers")]), \
                mock.patch.object(sound_devices, "chosen_is_gone", return_value=True), mock.patch("sys.stdout", out):
            self.assertEqual(main.main(["--sound-devices"]), 0)
        text = out.getvalue()
        self.assertIn("default  Windows' default output", text)
        self.assertIn("{11111111-0000-0000-0000-000000000000}  Speakers", text)
        self.assertIn("not connected", text)

    def test_the_slider_maps_its_range_onto_its_track(self):
        from types import SimpleNamespace
        from opendmt3.client import widgets
        # The slider's own state with no window behind it: a 320 px track at scale 1, its ends 10 px in.
        ui = SimpleNamespace(px=lambda n: n)
        s = SimpleNamespace(ui=ui, w=320, low=0, high=500, value=0, _draw=lambda: None)
        # The audio offset's 0 to 500: 250 mid-track, the ends at the track's ends.
        self.assertEqual(widgets.Slider._x(s, 250), 160.0)
        self.assertEqual((widgets.Slider._x(s, 0), widgets.Slider._x(s, 500)), (10.0, 310.0))
        # A drag takes the nearest whole value, never past either end.
        for x, value in ((-50, 0), (10, 0), (160, 250), (161, 252), (310, 500), (900, 500)):
            widgets.Slider._drag(s, SimpleNamespace(x=x))
            self.assertEqual(s.value, value)
        # The volumes' 0 to 100, as before.
        s.high = 100
        widgets.Slider._drag(s, SimpleNamespace(x=160))
        self.assertEqual(s.value, 50)

    def test_the_picture_choices_have_command_line_twins(self):
        from opendmt3.client import main
        self.state.save()
        # The Screen page's upscale filter, its sharpness and anti-aliasing, by --set, kept as the page keeps them.
        self.assertEqual(main.main(["--set", "upscale=nis", "--set", "sharpness=75", "--set",
                                    "antialiasing=SMAA-High"]), 0)
        saved = st.LauncherState.load()
        self.assertEqual((saved.values["upscale"], saved.values["sharpness"], saved.values["antialiasing"]),
                         ("nis", 75, "smaa-high"))
        # Values the page does not offer are said, and nothing changes.
        for bad in ("upscale=dlss", "sharpness=101", "antialiasing=msaa16"):
            with self.subTest(bad=bad):
                self.assertEqual(main.main(["--set", bad]), 2)
        saved = st.LauncherState.load()
        self.assertEqual((saved.values["upscale"], saved.values["sharpness"], saved.values["antialiasing"]),
                         ("nis", 75, "smaa-high"))
        # Refused while the window is open, as every write is.
        with mock.patch("opendmt3.client.cli.window_open", return_value=True):
            self.assertEqual(main.main(["--set", "upscale=off"]), 2)
        self.assertEqual(st.LauncherState.load().values["upscale"], "nis")
        # --help names each value, from the same lists the page offers.
        out = io.StringIO()
        with mock.patch("sys.stdout", out), self.assertRaises(SystemExit):
            main.main(["--help"])
        text = " ".join(out.getvalue().split())
        for value in values.UPSCALES + ("sharpness", "smaa-") + values.ANTIALIASINGS[-3:] + values.RENDER_SIZES:
            self.assertIn(value, text)
        # The Sound page's audio offset with its range.
        self.assertIn("audio_offset %d to %d ms" % values.AUDIO_OFFSET_RANGE, text)
        # The size the game draws at, by --set as well.
        self.assertEqual(main.main(["--set", "render_size=display"]), 0)
        self.assertEqual(st.LauncherState.load().values["render_size"], "display")
        self.assertEqual(main.main(["--set", "render_size=4k"]), 2)

    def test_the_picture_rows_have_words_in_both_languages(self):
        from opendmt3.client import i18n
        # Every row, its hint and every value's label, in English and Korean, none falling back to the key.
        keys = ["screen.upscale", "screen.upscale.hint", "screen.sharpness", "screen.sharpness.hint",
                "screen.antialiasing", "screen.antialiasing.hint", "screen.fps", "screen.fps.hint.off",
                "screen.fps.hint.on", "screen.fps.position", "screen.fps.position.hint", "screen.shape",
                "screen.shape.hint", "screen.pass_times", "screen.pass_times.hint"]
        keys += ["screen.fps.position." + value for value in values.FPS_POSITIONS]
        keys += ["screen.shape." + value for value in values.PICTURE_SHAPES]
        keys += ["screen.upscale." + value for value in values.UPSCALES]
        keys += ["screen.render", "screen.render.hint.game", "screen.render.hint.display",
                 "screen.antialiasing.hint.display"]
        keys += ["screen.render." + value for value in values.RENDER_SIZES]
        keys += ["screen.antialiasing." + value for value in values.ANTIALIASINGS]
        # The Sound page's audio offset and its hint.
        keys += ["sound.offset", "sound.offset.hint"]
        for key in keys:
            with self.subTest(key=key):
                en, ko = i18n.TEXT[key]
                self.assertTrue(en and ko)
                # No dash between clauses, the house style for every word the launcher shows.
                self.assertNotIn("\u2014", en + ko)
        # The frame rate row is named for what it does; its hint says what the chip shows and its corner's what the
        # bottom right is over (one fact each), and no key in the game turns the chip (only the menu's row there does).
        self.assertEqual(i18n.Words("en")("screen.fps"), "Show FPS")
        self.assertEqual(i18n.Words("ko")("screen.fps"), "FPS 표시")
        for key in ("screen.fps.hint.off", "screen.fps.hint.on", "screen.fps.position.hint"):
            for language in ("en", "ko"):
                self.assertNotIn("F12", i18n.Words(language)(key))
        self.assertEqual(i18n.Words("en")("screen.fps.hint.off"), "Shows the frames a second over the game.")
        self.assertEqual(i18n.Words("en")("screen.fps.position.hint"), "Bottom right is above the game's FREE PLAY.")
        self.assertEqual(i18n.Words("ko")("screen.fps.position.hint"), "오른쪽 아래는 게임의 FREE PLAY 위입니다.")
        # The pacing named plainly, the music lock first (the default).
        self.assertEqual(i18n.Words("en")("screen.pacing.music"), "Locked to the music")
        self.assertEqual(i18n.Words("ko")("screen.pacing.music"), "음악에 맞춤")

    def test_every_page_has_its_command_line_twin(self):
        from opendmt3.client import main, remote
        self.state.save()
        # Settings: the language (and back to Windows'), the guide again, where logins live, the hidden patterns.
        self.assertEqual(main.main(["--language", "ko", "--guide", "--mode", "offline", "--set", "unlock=off"]), 0)
        saved = st.LauncherState.load()
        self.assertEqual((saved.picked_language, saved.guide_done, saved.mode, saved.unlock), ("ko", False, "offline", False))
        self.assertEqual(main.main(["--language", "system"]), 0)
        self.assertIsNone(st.LauncherState.load().picked_language)
        # Players on this PC: made with the password from standard input, chosen, removed after y/N (or --yes).
        with mock.patch("sys.stdin", io.StringIO("pass1234\n")):
            self.assertEqual(main.main(["--mode", "this_pc", "--add-player", "nova", "--dj", "DJ NOVA"]), 0)
        self.assertEqual(main.main(["--player", "NOVA"]), 0)
        self.assertEqual(st.LauncherState.load().player, "NOVA")
        self.assertEqual(main.main(["--player", "nobody"]), 2)
        with mock.patch("builtins.input", return_value=""):
            self.assertEqual(main.main(["--delete-player", "NOVA"]), 0)
        self.assertEqual(st.LauncherState.load().player, "NOVA")
        # Delete, as the Online page and the site say it; the flag's name before still works.
        self.assertEqual(main.parse(["--remove-player", "NOVA"]).remove_player, "NOVA")
        self.assertEqual(main.main(["--delete-player", "NOVA", "--yes"]), 0)
        self.assertIsNone(st.LauncherState.load().player)
        # Another server: connect, sign in (the password from standard input), sign out; its address stays.
        with mock.patch.object(remote, "status", return_value={"game": "192.0.2.1:4725", "version": "0.11.0"}), \
                mock.patch.object(remote, "sign_in", return_value={"login_id": "NOVA", "dj_name": "DJ NOVA",
                                                                   "card": "1" * 20, "token": "t"}) as signing, \
                mock.patch("sys.stdin", io.StringIO("secret\n")):
            self.assertEqual(main.main(["--server", "192.0.2.1:4730", "--sign-in", "NOVA"]), 0)
        signing.assert_called_once_with("http://192.0.2.1:4730", "NOVA", "secret")
        saved = st.LauncherState.load()
        self.assertEqual((saved.mode, saved.server_url, saved.remote["card"]), ("server", "http://192.0.2.1:4730", "1" * 20))
        # Signing out asks the server to end the token first, then forgets it here.
        with mock.patch.object(remote, "sign_out", return_value=True) as ending:
            self.assertEqual(main.main(["--sign-out"]), 0)
        ending.assert_called_once_with("http://192.0.2.1:4730", "t")
        self.assertEqual(st.LauncherState.load().remote, {"game": "192.0.2.1:4725", "version": "0.11.0",
                                                          "updates": False})
        # The status: exit 1 while PLAY cannot go (here: no game folder known on another server, not signed in).
        self.assertEqual(main.main(["--status"]), 1)
        # A report where it is asked for; the log folder's path.
        folder = os.path.join(self.config, "reports")
        os.makedirs(folder)
        self.assertEqual(main.main(["--report", folder]), 0)
        self.assertEqual(len(os.listdir(folder)), 1)
        # The log folder shown in Explorer on Windows (elsewhere its path is said alone): never from a test, where it would
        # open a window, so only asked for here.
        with mock.patch.object(actions, "open_folder") as shown:
            self.assertEqual(main.main(["--open-log"]), 0)
        self.assertEqual(shown.call_args_list,
                         [mock.call(os.path.join(self.config, "logs"))] if os.name == "nt" else [])
        # The guide's search for game folders, on its own: nothing breaks when the usual places hold none.
        from opendmt3.client import find
        with mock.patch.object(find, "places", return_value=[os.path.dirname(self.tmp)]):
            self.assertEqual(main.main(["--find"]), 0)

    def test_the_command_line_says_what_it_does_not_know_and_waits_for_the_window(self):
        from opendmt3.client import installer
        from opendmt3.client import main
        # A typo is said (argparse's exit code 2), never taken for the window.
        with self.assertRaises(SystemExit) as end:
            main.main(["--unistall"])
        self.assertEqual(end.exception.code, 2)
        # Velopack's own arguments, with their values, are let through.
        self.assertFalse(main.parse(["--veloapp-install", "0.11.0"]).play)
        # While the window is open, a change to what it keeps is refused: the window would write its copy over it.
        with mock.patch.object(installer, "launcher_open", return_value=True):
            self.assertEqual(main.main(["--language", "ko"]), 2)
            self.assertEqual(main.main(["--check"]), 1)
        self.assertNotEqual(st.LauncherState.load().picked_language, "ko")

    def test_update_on_the_command_line(self):
        from opendmt3.client import main, updates
        with mock.patch.object(updates, "check", return_value=updates.Result("no_source")):
            self.assertEqual(main.main(["--update"]), 2)
        with mock.patch.object(updates, "check", return_value=updates.Result("uptodate")):
            self.assertEqual(main.main(["--update"]), 0)
        found = updates.Result("available", version="9.9.9", info=object())
        with mock.patch.object(updates, "check", return_value=found), mock.patch.object(updates, "apply") as apply:
            # Asked first: no answer, no update.
            with mock.patch("builtins.input", return_value=""):
                self.assertEqual(main.main(["--update"]), 1)
            apply.assert_not_called()
            self.assertEqual(main.main(["--update", "--yes"]), 0)
            # The update found, and a way for it to say what it turns to (tests/client/test_updates.py has the line).
            apply.assert_called_once()
            self.assertEqual((apply.call_args[0], sorted(apply.call_args[1])), ((found,), ["tell"]))

    def test_a_failing_velopack_hook_still_ends_the_hook_cleanly(self):
        from opendmt3.client import main

        class Panic(BaseException):
            """What a Rust panic inside Velopack arrives as: not an Exception."""

        class App:
            def run(self):
                raise Panic("a panic inside Velopack")

        fake = mock.MagicMock()
        fake.App = App
        # As main() does it: the log is open before Velopack runs.
        main._logging()
        with mock.patch.dict("sys.modules", {"velopack": fake}):
            # Run by the installer for its install step: logged, and the step ends as finished.
            with self.assertRaises(SystemExit) as end:
                main._velopack_hooks(["--veloapp-install", "0.4.1"])
            self.assertEqual(end.exception.code, 0)
            # Started by a person: logged, and the launcher goes on.
            main._velopack_hooks([])
        with open(os.path.join(self.config, "logs", "launcher.log"), encoding="utf-8") as f:
            self.assertIn("a panic inside Velopack", f.read())

    def test_the_update_address_is_the_one_the_build_wrote_in(self):
        from opendmt3.client import updates
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        written = os.path.join(folder, "update-source.txt")
        with open(written, "w", encoding="utf-8") as f:
            f.write("https://github.com/someone/openDMT3\n")
        with mock.patch.object(updates, "SOURCE_FILE", written), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENDMT3_UPDATE_SOURCE", None)
            self.assertEqual(updates._update_source(), "https://github.com/someone/openDMT3")
            # An empty file (a build given no address) means none.
            with open(written, "w", encoding="utf-8") as f:
                f.write("")
            self.assertEqual(updates._update_source(), "")
            # The variable at run time wins, for trying a feed out.
            with mock.patch.dict(os.environ, {"OPENDMT3_UPDATE_SOURCE": "C:\\updates"}):
                self.assertEqual(updates._update_source(), "C:\\updates")


class WindowGuardTest(unittest.TestCase):
    """Nothing a test runs may open a window outside the test container's virtual screen."""

    def test_the_guard_is_on_in_tests(self):
        self.assertTrue(safety.testing())

    @unittest.skipUnless(TK, "needs Tk, the launcher's window toolkit")
    def test_launcher_window_and_game_are_refused(self):
        with mock.patch.dict(os.environ, {"OPENDMT3_VIRTUAL_DISPLAY": ""}):
            from opendmt3.client.app import LauncherApp
            # The refusal comes before Tk is touched, so no window flashes up either.
            with self.assertRaises(safety.WindowRefused):
                LauncherApp(st.LauncherState())
            game = g.Game(tempfile.gettempdir())
            with self.assertRaises(safety.WindowRefused):
                launch.start(game, steps.Own(tempfile.gettempdir()))
            with self.assertRaises(safety.WindowRefused):
                actions.open_folder(tempfile.gettempdir())
            with self.assertRaises(safety.WindowRefused):
                actions.open_link("http://127.0.0.1:4730/")


class StartupAndUpdateTest(unittest.TestCase):
    """A settings file that cannot be read, the installer's order of versions, and an update's outcome."""

    def setUp(self):
        self.config = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"OPENDMT3_CONFIG_DIR": self.config})
        self.env.start()

    def tearDown(self):
        _drop_log_file()
        self.env.stop()
        shutil.rmtree(self.config)

    def write(self, text):
        from opendmt3.client import state as st
        with open(st.LauncherState.path(), "w", encoding="utf-8") as f:
            f.write(text)

    def test_damage_is_not_a_newer_launcher(self):
        from opendmt3.client import state as st
        for version in ('"1"', "null", "1.0", "true"):
            self.write('{"version": %s}' % version)
            with self.assertRaises(st.StateError) as caught:
                st.LauncherState.load()
            self.assertFalse(caught.exception.newer, version)
        self.write('{"version": 99}')
        with self.assertRaises(st.StateError) as caught:
            st.LauncherState.load()
        self.assertTrue(caught.exception.newer)

    def test_a_field_of_the_wrong_kind_is_damage_not_a_crash(self):
        from opendmt3.client import state as st
        for data in ('{"values": "abc"}', '{"values": [1]}', "[1, 2]"):
            self.write(data)
            with self.assertRaises(st.StateError, msg=data):
                st.LauncherState.load()

    def test_versions_in_semantic_order(self):
        from opendmt3.client import installer
        order = ["0.4.1", "0.5.0-rc.1", "0.5.0-rc.2", "0.5.0-rc.10", "0.5.0", "0.5.1-updatetest", "0.5.1", "1.0.0"]
        self.assertEqual(sorted(reversed(order), key=installer.version_key), order)
        # An older pre-release installed asks to update, not to repair.
        self.assertEqual(installer.plan("0.5.0-rc.1", "0.5.0-rc.2", False)[-1], "update")
        self.assertIsNone(installer.plan("0.5.0", "0.5.0+build.7", False))

    def test_an_updates_outcome_is_said_once(self):
        from opendmt3.client import updates
        self.assertIsNone(updates.outcome())
        with mock.patch.object(updates, "current_version", return_value="0.5.0"):
            updates._note_pending("0.5.1")
            self.assertEqual(updates.outcome(), ("not_updated", "0.5.1", "0.5.0"))
            self.assertIsNone(updates.outcome())
        with mock.patch.object(updates, "current_version", return_value="0.5.1"):
            updates._note_pending("0.5.1")
            self.assertEqual(updates.outcome(), ("updated", "0.5.1"))


class Tied:
    """Stands in for a picture in a reference cycle: only the collector frees it, and it writes down the thread
    that did (a real picture calls Tk from that thread)."""

    def __init__(self, freed_on):
        self.me, self.freed_on = self, freed_on

    def __del__(self):
        self.freed_on.append(threading.current_thread().name)


class CollectorTest(unittest.TestCase):
    """While a window is open, garbage is collected on the window's thread only (client/collecting.py)."""

    def setUp(self):
        # Whatever a test leaves, the next one starts with the automatic collector on and nothing pending.
        self.addCleanup(gc.enable)
        gc.enable()
        gc.collect()

    def worker(self, freed_on, kept):
        """A worker's life: leave one tied object behind, then make enough objects for a pass to be due."""
        Tied(freed_on)
        kept.extend([] for _ in range(20 * 700))

    def run_worker(self, freed_on):
        kept = []
        thread = threading.Thread(target=self.worker, args=(freed_on, kept), name="worker")
        thread.start()
        thread.join()
        return kept

    def test_the_failure_it_is_for(self):
        # Left alone, Python frees the tied object on the worker: the thread a picture must not be freed on.
        freed_on = []
        self.run_worker(freed_on)
        self.assertEqual(freed_on, ["worker"])

    def test_garbage_waits_for_the_windows_thread(self):
        from opendmt3.client import collecting
        freed_on = []
        collector = collecting.OnThisThread()
        self.assertFalse(gc.isenabled())
        kept = self.run_worker(freed_on)
        # The worker made thousands of objects and nothing was collected on it.
        self.assertEqual(freed_on, [])
        # The window's next look frees it, among what is new.
        self.assertEqual(collector.tick(), 0)
        self.assertEqual(freed_on, [threading.current_thread().name])
        collector.stop()
        self.assertTrue(gc.isenabled())
        del kept

    def test_an_idle_window_does_not_collect(self):
        from opendmt3.client import collecting
        now = [0.0]
        with mock.patch.object(collecting.gc, "get_count", return_value=(40, 0, 0)), \
                mock.patch.object(collecting.gc, "collect") as collect:
            collector = collecting.OnThisThread(clock=lambda: now[0])
            for now[0] in (1.0, 10.0, 100.0):
                # The count moves a little with the pump itself; that is not being busy.
                collecting.gc.get_count.return_value = (40 + collecting.STIR - 1, 0, 0)
                self.assertIsNone(collector.tick())
            collect.assert_not_called()

    def test_everything_is_looked_at_a_little_after_the_window_was_busy(self):
        from opendmt3.client import collecting
        now = [0.0]
        with mock.patch.object(collecting.gc, "get_count", return_value=(500, 0, 0)) as count, \
                mock.patch.object(collecting.gc, "collect") as collect:
            collector = collecting.OnThisThread(clock=lambda: now[0])
            # A page was left: hundreds of objects freed, too few made for a pass of what is new.
            count.return_value = (500 - collecting.STIR, 0, 0)
            now[0] = collecting.FULL_AFTER - 0.1
            self.assertIsNone(collector.tick())
            now[0] = collecting.FULL_AFTER
            self.assertEqual(collector.tick(), 2)
            collect.assert_called_once_with()
            # A burst of new objects right after: only what is new, at once.
            count.return_value = (collecting.YOUNG, 0, 0)
            now[0] += 0.05
            self.assertEqual(collector.tick(), 0)
            collect.assert_called_with(0)
            # Everything again when its time has come, and then nothing however long the window stays open.
            count.return_value = (3, 0, 0)
            now[0] += collecting.FULL_AFTER
            self.assertEqual(collector.tick(), 2)
            self.assertEqual(collect.call_count, 3)
            now[0] += 100 * collecting.FULL_AFTER
            self.assertIsNone(collector.tick())
            self.assertEqual(collect.call_count, 3)

    def test_a_collector_that_was_off_stays_off(self):
        from opendmt3.client import collecting
        gc.disable()
        collecting.OnThisThread().stop()
        self.assertFalse(gc.isenabled())


if __name__ == "__main__":
    unittest.main()


class FolderFoundTest(FolderCase):
    """The first-start guide's cards (client/intake.py) say what each game folder holds before it is chosen: the songs
    the game offers (those its modes' tables name) and their jackets, read through the server's catalog, or why it cannot
    be played."""

    def setUp(self):
        super().setUp()
        from opendmt3.core.formats import discstock
        from tests.server.test_catalog import LIST, png
        # The launcher's own folder one of this test's: a card's look keeps its charts' count there, and main() its
        # fingerprints and its log.
        self.config = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.config, True)
        env = mock.patch.dict(os.environ, {"OPENDMT3_CONFIG_DIR": self.config})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(_drop_log_file)
        root = self.game.root
        # The stand-in client counts as the PC client the setup builds from.
        client = os.path.join(root, "Client.exe")
        patcher = mock.patch.object(g.Game, "base_client", lambda game: client if os.path.isfile(client) else None)
        patcher.start()
        self.addCleanup(patcher.stop)
        # The list's two songs, both on a stage list: the card counts the songs the game offers.
        self._pak(self.game.pak_path("DiscInfo"), {
            discstock.PATH: LIST,
            "Resource\\DiscInfo\\star_stage_1.csv": b"stage1,songname,SP,PT,Hid\r\n1,madeup,2,1,0\r\n2,nodisc,1,1,0\r\n"})
        picture = png(64)
        if picture is not None:
            # One of the list's two songs has its jacket.
            self._pak(self.game.pak_path("DiscImg"), {"Resource\\DiscImg\\madeup_0.png": picture})
        self.has_pictures = picture is not None

    def test_a_folder_says_its_songs_and_jackets(self):
        from opendmt3.client import intake
        found = intake.inspect(self.game.root)
        self.assertEqual(found.state, intake.READY)
        self.assertEqual(found.songs, 2)
        if self.has_pictures:
            self.assertEqual(found.jackets, 1)
        self.assertIn(intake.CHOOSE, found.actions)

    def test_a_half_copied_song_list_is_said_and_never_picked(self):
        from opendmt3.client import i18n, intake
        with open(self.game.pak_path("DiscInfo"), "r+b") as f:
            f.truncate(48)
        found = intake.inspect(self.game.root)
        self.assertEqual(found.state, intake.NOT_HERE)
        self.assertNotIn(intake.CHOOSE, found.actions)
        # The words exist in both languages and name no file.
        for language in ("en", "ko"):
            said = found.line_words(i18n.Words(language))
            self.assertTrue(said)
            self.assertNotIn(".pak", said)
            self.assertNotIn("error.", said)

    def test_a_folder_without_a_client_that_opens_the_games_files_reads_nothing(self):
        from opendmt3.client import intake

        def no_table(game):
            raise g.GameError("The game's files cannot be opened with this client.", "error.game.no_table")

        with mock.patch.object(g.Game, "table", no_table):
            found = intake.inspect(self.game.root)
        # The game's files stay closed without the client: only that is said.
        self.assertEqual(found.state, intake.NOT_HERE)
        self.assertIsNone(found.songs)
        self.assertEqual(found.line.key, "error.game.no_table")

    def test_the_command_line_list_says_the_songs_too(self):
        from opendmt3.client import find, main
        out = io.StringIO()
        with mock.patch.object(find, "places", return_value=[self.tmp]), mock.patch("sys.stdout", out):
            self.assertEqual(main.main(["--find"]), 0)
        self.assertIn("2 songs", out.getvalue())
        self.assertIn(self.game.root, out.getvalue())


class SongListLauncherTest(GameCase):
    """The Game page's song list for a server and its command-line twins: --save-song-list makes the file a server takes
    from the game folder in use (the desktop when no file is given, in a folder when one is), --send-song-list sends
    it with the launcher's sign-in to the server whose admin it is, and says why not otherwise."""

    def setUp(self):
        super().setUp()
        self.config = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.config)
        env = mock.patch.dict(os.environ, {"OPENDMT3_CONFIG_DIR": self.config})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(_drop_log_file)
        state = st.LauncherState()
        state.game_folder = self.game.root
        state.save()

    def test_save_song_list_on_the_command_line(self):
        from opendmt3.client import main, shortcuts
        from opendmt3.server.services import songlist
        out = os.path.join(self.tmp, "for-the-server.zip")
        with mock.patch("sys.stdout", io.StringIO()) as said:
            self.assertEqual(main.main(["--save-song-list", out]), 0)
        self.assertIn("Saved the song list: %s (3 songs" % out, said.getvalue())
        self.assertEqual(songlist.look(out)["songs"], 3)
        # No file named: on the desktop, under the usual name; a folder named: in it.
        desktop = os.path.join(self.tmp, "Desktop")
        os.makedirs(desktop)
        with mock.patch.object(shortcuts, "desktop", lambda: desktop), mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(main.main(["--save-song-list"]), 0)
            self.assertEqual(main.main(["--save-song-list", self.tmp]), 0)
        self.assertTrue(os.path.isfile(os.path.join(desktop, songlist.NAME)))
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, songlist.NAME)))
        # A game folder whose song list is damaged: said, exit 2, nothing left behind.
        self.cut("DiscInfo01.pak", -10)
        broken = os.path.join(self.tmp, "broken.zip")
        with mock.patch("sys.stderr", io.StringIO()) as err:
            self.assertEqual(main.main(["--save-song-list", broken]), 2)
        self.assertIn("The file with the song list is damaged.", err.getvalue())
        self.assertFalse(os.path.exists(broken))

    def test_send_song_list_needs_the_sign_in_of_the_servers_admin(self):
        from opendmt3.client import actions, main, remote
        from opendmt3.server.services import songlist
        with mock.patch("sys.stderr", io.StringIO()) as err:
            self.assertEqual(main.main(["--send-song-list"]), 2)
        self.assertIn("sign in on the Online page first", err.getvalue())
        state = st.LauncherState.load()
        state.mode, state.server_url = "server", "http://192.0.2.1:4730"
        actions.signed_in(state, {"login_id": "BOSS", "dj_name": "BOSS", "card": "1" * 20, "token": "t",
                                  "is_admin": True})
        self.assertTrue(actions.is_server_admin(state))
        state.save()
        sent = []

        def send(base, token, path):
            # What the server would get: a song list as it takes them.
            sent.append((base, token, songlist.look(path)["songs"]))
            return {"song_list": {"songs": {"count": 3}}, "lines": ["song list: 3 songs"]}
        with mock.patch.object(remote, "send_song_list", send), mock.patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(main.main(["--send-song-list"]), 0)
        self.assertEqual(sent, [("http://192.0.2.1:4730", "t", 3)])
        self.assertIn("Sent the song list to http://192.0.2.1:4730.", out.getvalue())
        # A player's sign-in: not offered on the page, and the server's refusal said on the command line.
        actions.signed_in(state, {"login_id": "NOVA", "dj_name": "NOVA", "card": "1" * 20, "token": "p",
                                  "is_admin": False})
        self.assertFalse(actions.is_server_admin(state))


class WindowBoxTest(unittest.TestCase):
    """The launcher's window fits the room windows have: on Windows the work area (the screen less the taskbar), its
    title bar and frame counted, so no part of it hides under the taskbar at any scaling (window_room.window_box,
    plain numbers: these run where Tk is missing too)."""

    def test_the_window_and_its_title_bar_stay_inside_the_work_area(self):
        from opendmt3.client import window_room as app
        # (work area, title bar and frame, wanted size): 100 % and 150 % with the taskbar at the foot, 150 % with it on
        # the left, a small screen, and no taskbar (Wine, Linux: the caption 0).
        cases = [((0, 0, 1920, 1032), 39, 1180, 760), ((0, 0, 1920, 1008), 58, 1770, 1140),
                 ((72, 0, 1848, 1080), 58, 1770, 1140), ((0, 0, 1366, 728), 39, 1180, 760),
                 ((0, 0, 1920, 1080), 0, 1770, 1140)]
        for room, caption, want_w, want_h in cases:
            with self.subTest(room=room, caption=caption):
                left, top, room_w, room_h = room
                w, h, x, y = app.window_box(room, caption, want_w, want_h)
                # Never wider or taller than wanted, nor than 92 % of the room with the title bar counted.
                self.assertLessEqual(w, min(want_w, room_w * 0.92))
                self.assertLessEqual(h + caption, room_h * 0.92 + 1)
                # The whole frame, its title bar included, inside the room.
                self.assertGreaterEqual(x, left)
                self.assertGreaterEqual(y, top)
                self.assertLessEqual(x + w, left + room_w)
                self.assertLessEqual(y + h + caption, top + room_h)

    def test_the_150_percent_screen_the_taskbar_covered(self):
        from opendmt3.client import window_room as app
        # 1920x1080 at 150 %: the taskbar 72 pixels, the title bar and frame 58. Before, the window took 92 % of the
        # whole screen's height (993) a third of the way down (29), its frame ending at 1080, under the taskbar.
        w, h, x, y = app.window_box((0, 0, 1920, 1008), 58, 1770, 1140)
        self.assertLessEqual(y + h + 58, 1008)
        self.assertEqual(w, 1766)
