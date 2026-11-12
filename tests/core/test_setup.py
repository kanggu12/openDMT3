"""Tests of a game folder an earlier openDMT3 set up and of its backup, on a made-up game folder.

Earlier versions of openDMT3 wrote into the game folder at PLAY (tests/core/older_setup.py keeps what they did), and
kept the originals in backup\\. PLAY now only reads a game folder (tests/core/test_own.py); such a folder is read
through its backup and put back with it. The folder has a client the setup does not know (so the display fix is
skipped), and two small archives written with a random descriptor table in place of the client's. Every step is run,
checked, and undone.
"""

import json
import os
import random
import shutil
import stat
import tempfile
import threading
import unittest
from unittest import mock

from opendmt3.core import game as g
from opendmt3.core.backup import NOT_ORIGINAL, Backup
from tests.core import older_setup as older
from opendmt3.core.formats import game_settings, pak, settings_ini, stage_lists

# The keys the real file has, in its sections, with the cabinet's values (full screen, hidden pointer).
SETTINGS = (
    "[setting]\r\nfullscreen=true\r\npopup_style=true\r\nfixed_frame=false\r\nvsync=true\r\n\r\n"
    "screen_width=1280\r\nscreen_height=768\r\n\r\n"
    "//sfx = note , bgm = bg , 0 ~ 127\r\nsfx_volume=127\r\nbgm_volume=127\r\n\r\nshow_cursor=false\r\n"
    "resource_preload=false\r\n\r\n"
    "[FilePath]\r\nrankFilePath = file/\r\nbookkeepingFilePath = file/\r\ngameSettingFilePath = file/\r\n\r\n"
    "[graphics]\r\nfullscene_glow=true\r\nmultipleSample=1\r\n\r\n"
    "[test]\r\nPreLoadMovie = false\r\nUseVedio = true\r\n"
).encode("cp949")
NETWORK = b"[setting]\r\n\r\ntryconnet_time=10000\r\n\r\nserverip=203.0.113.9\r\nport=4725\r\n"
STAGE = b"stage1,songname,SP,PT,Hid,SP,PT,Hid\r\n1,songa,2,1,0,2,2,1\r\n2,songb,1,1,1,,,\r\n"


def settle_looks():
    """Wait for the charts' check a look left on its own thread (client/intake.py's "charts"): a look that found a
    problem first, or was stopped, answers before the check is done. Called before a test's folders go and its
    stand-ins stop, so no check reads a folder being removed (Windows removes no file a thread has open) or runs on
    past the test."""
    for thread in threading.enumerate():
        if thread.name == "charts":
            # A made-up folder's check takes milliseconds; the bound only keeps a stuck one from holding the run.
            thread.join(30)


def _read(path):
    with open(path, "rb") as f:
        return f.read()


class FolderCase(unittest.TestCase):
    """A made-up game folder for each test (no tests of its own; other test cases build on it)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.rng = random.Random(7)
        self.table = bytes(self.rng.randrange(256) for _ in range(256))
        # Two levels below the folder the test gives, as when a game folder sits inside the folder it came in.
        root = os.path.join(self.tmp, "unpacked", "game")
        os.makedirs(os.path.join(root, "pack"))
        os.makedirs(os.path.join(root, "file"))
        with open(os.path.join(root, "Client.exe"), "wb") as f:
            f.write(b"MZ not a known client")
        # The cabinet's own data folder: an operator settings file with free play off, and one ranking file.
        with open(os.path.join(root, "file", "game"), "wb") as f:
            f.write(game_settings.GameSettings(coins_per_credit=2).build())
        with open(os.path.join(root, "file", "club"), "wb") as f:
            f.write(b"ranking")
        self._pak(os.path.join(root, "pack", "Config.pak"),
                  {"Resource\\Config\\setting.ini": SETTINGS, "Resource\\Config\\networksetting.ini": NETWORK})
        self._pak(os.path.join(root, "pack", "DiscInfo.pak"),
                  {"Resource\\DiscInfo\\pop_stage_1.csv": STAGE, "Resource\\DiscInfo\\discstock.csv": b"no,name\r\n"})
        # Stand-ins for the files with the tutorial and the videos: a whole copy has them (only their names matter).
        for name in [g.TUTORIAL, g.CHARTS] + list(g.VIDEOS) + list(g.PREVIEWS):
            with open(os.path.join(root, "pack", name + ".pak"), "wb") as f:
                f.write(b"stand-in")
        self.patcher = mock.patch.object(g.Game, "table", lambda game: self.table)
        self.patcher.start()
        # Nothing kept of the fingerprints and tables other tests made (core/game.py keeps them for the process): a
        # table kept for one test's made-up client would answer another's. None left for the next test either.
        g.use_hash_cache(None)
        self.addCleanup(g.use_hash_cache, None)
        self.game = g.Game.find(self.tmp)

    def tearDown(self):
        # A look's charts' check still going ends first, with this test's stand-ins as it began.
        settle_looks()
        self.patcher.stop()
        shutil.rmtree(self.tmp)

    def _pak(self, path, files):
        template = pak.Header(0x01020304, 0, 2, 0, 0, 0x36, 1, 0)
        key_field = (0x2222).to_bytes(4, "little") + bytes(4)
        pak.write_pak(path, files, self.table, 0x3C, key_field, template, bytes(32),
                      seed_source=lambda n: self.rng.randrange(1 << 32).to_bytes(n, "little"))

    def _run_setup(self, options):
        backup = Backup(self.game)
        for rel in older.MANAGED:
            backup.protect(rel)
        for step in older.STEPS:
            if not step.status(self.game, backup, options).done:
                step.apply(self.game, backup, options)
        return backup


class CraftedBackupListTest(FolderCase):
    """A game folder can come from anyone, with its backup list: nothing that list names outside the game folder is
    put back, removed or renamed, whichever way the path leaves it."""

    def test_a_crafted_backup_list_touches_nothing_outside_the_game_folder(self):
        # Files beside the game folder, named by the list in every way a path can leave it.
        outside = os.path.join(self.tmp, "victim")
        os.makedirs(outside)
        for name in ("a.txt", "b.txt", "c.txt", "d.txt"):
            with open(os.path.join(outside, name), "w") as f:
                f.write("mine")
        root = self.game.root
        # A folder link inside the game folder that leads out, as a junction would on Windows.
        os.symlink(outside, os.path.join(root, "linked"))
        os.makedirs(self.game.path(g.BACKUP_DIR), exist_ok=True)
        up = os.path.relpath(outside, root).replace(os.sep, "/")
        nothing = {"existed": False, "sha256": None}
        files = {up + "/a.txt": nothing, outside + "/b.txt": nothing, "C:\\Users\\v\\c.txt": nothing,
                 "pack/../../../victim/d.txt": nothing, "linked/c.txt": nothing, "pack/new.bin": nothing}
        with open(self.game.path(g.BACKUP_DIR, "openDMT3.json"), "w") as f:
            json.dump({"version": 1, "files": files, "folders": [up, "linked", "pack/.."]}, f)
        # The one real entry: a file the setup made, which goes.
        with open(self.game.path("pack", "new.bin"), "w") as f:
            f.write("made by the setup")
        kept = Backup(self.game)
        # Plain paths only; the link is a plain path, but leads out, so it is left alone below.
        self.assertEqual(sorted(kept.files), ["linked/c.txt", "pack/new.bin"])
        self.assertEqual(kept.folders, ["linked"])
        self.assertEqual(kept.restore_all(), ["pack/new.bin"])
        self.assertEqual(kept.forget(), [])
        for name in ("a.txt", "b.txt", "c.txt", "d.txt"):
            self.assertTrue(os.path.isfile(os.path.join(outside, name)), name)
        self.assertTrue(os.path.isdir(outside))
        self.assertFalse(os.path.exists(self.game.path("pack", "new.bin")))

    def test_only_plain_game_folder_paths_are_taken(self):
        from opendmt3.core.backup import plain_path
        for good in ("pack/Config.pak", "file/game", "TECHNIKA/Data/a b.txt"):
            self.assertTrue(plain_path(good), good)
        for bad in ("", "/etc/x", "../x", "a/../x", "a/./x", "a//x", "C:/x", "C:\\x", "a\\..\\x", "a:stream",
                    "a./x", "a /x", " a/x", "a/\x00b", "a" * 401, None, 7):
            self.assertFalse(plain_path(bad), bad)


class SetupTest(FolderCase):
    """What an earlier openDMT3 wrote into a game folder, and putting it back."""

    def test_found_from_above(self):
        self.assertTrue(self.game.root.endswith(os.path.join("unpacked", "game")))

    def test_setup_then_everything_is_done(self):
        options = older.Options(server="127.0.0.1:4725")
        self._run_setup(options)
        backup = Backup(self.game)
        for step in older.STEPS:
            self.assertTrue(step.status(self.game, backup, options).done, step.name)
        # Free play, from the cabinet's data, with the ranking file copied beside it.
        with open(self.game.path("TECHNIKA", "GAME", "game"), "rb") as f:
            s = game_settings.GameSettings.parse(f.read())
        self.assertEqual((s.free_play, s.coins_per_credit), (1, 2))
        self.assertTrue(os.path.isfile(self.game.path("TECHNIKA", "RANK", "club")))
        # The settings file: the game's own with the PC values.
        with open(self.game.path(g.SETTINGS), "rb") as f:
            text = settings_ini.decode(f.read())
        self.assertEqual(settings_ini.get_value(text, "fullscreen"), "false")
        self.assertEqual(settings_ini.get_value(text, "gameSettingFilePath"), "TECHNIKA/GAME/")
        # The lists show everything, the other entry is untouched, and the server moved.
        with pak.Pak(self.game.pak_path("DiscInfo"), self.table) as p:
            self.assertEqual(stage_lists.count_hidden(p.read(p.find("Resource\\DiscInfo\\pop_stage_1.csv"))), 0)
            self.assertEqual(p.read(p.find("Resource\\DiscInfo\\discstock.csv")), b"no,name\r\n")
        self.assertEqual(older.ServerAddress().current(self.game), ("127.0.0.1", "4725"))

    def test_setup_twice_changes_nothing_the_second_time(self):
        options = older.Options(server="127.0.0.1:4725")
        self._run_setup(options)
        before = {rel: _read(self.game.path(*rel.split("/")))
                  for rel in ("pack/DiscInfo.pak", "pack/Config.pak", g.SETTINGS.replace(os.sep, "/"))}
        self._run_setup(options)
        for rel, data in before.items():
            self.assertEqual(_read(self.game.path(*rel.split("/"))), data, rel)

    def test_restore_puts_every_file_back(self):
        originals = {rel: _read(self.game.path(*rel.split("/"))) for rel in ("pack/DiscInfo.pak", "pack/Config.pak")}
        self._run_setup(older.Options(server="127.0.0.1:4725"))
        done = Backup(self.game).restore_all()
        self.assertIn("pack/DiscInfo.pak", done)
        for rel, data in originals.items():
            self.assertEqual(_read(self.game.path(*rel.split("/"))), data, rel)
        # The settings file did not exist before, so it is gone again.
        self.assertFalse(os.path.exists(self.game.path(g.SETTINGS)))
        # So is the operator data folder free play was turned on in, with the folders made for it.
        self.assertFalse(os.path.exists(self.game.path("TECHNIKA")))

    def test_restore_leaves_a_folder_the_game_wrote_in(self):
        self._run_setup(older.Options())
        # A ranking file the game made by itself while it was played.
        with open(self.game.path("TECHNIKA", "RANK", "new-ranking"), "wb") as f:
            f.write(b"the game's own")
        Backup(self.game).restore_all()
        self.assertEqual(os.listdir(self.game.path("TECHNIKA")), ["RANK"])
        self.assertEqual(os.listdir(self.game.path("TECHNIKA", "RANK")), ["new-ranking"])

    def test_free_play_without_operator_data_starts_from_defaults(self):
        shutil.rmtree(self.game.path("file"))
        self._run_setup(older.Options())
        self.assertEqual(sorted(os.listdir(self.game.path("TECHNIKA"))), ["BOOK", "GAME", "RANK"])
        Backup(self.game).restore_all()
        self.assertFalse(os.path.exists(self.game.path("TECHNIKA")))

    def test_a_copy_cut_short_is_never_taken_for_the_original(self):
        kept = self.game.path("backup", "pack", "DiscInfo.pak")

        def cut_short(src, dst, **kwargs):
            # Half the file arrives, then the disk is full.
            with open(src, "rb") as f, open(dst, "wb") as out:
                out.write(f.read()[:100])
            raise OSError(28, "No space left on device")

        with mock.patch("shutil.copy2", cut_short):
            with self.assertRaises(OSError):
                Backup(self.game).protect("pack/DiscInfo.pak")
        # Nothing under the backup's own name, and nothing recorded: the next run copies the whole file.
        self.assertFalse(os.path.exists(kept))
        Backup(self.game).protect("pack/DiscInfo.pak")
        self.assertEqual(_read(kept), _read(self.game.pak_path("DiscInfo")))

    def test_a_copy_already_in_backup_is_taken_as_the_original(self):
        # As when the folder was changed by hand and the original kept in backup\ first.
        kept = self.game.path("backup", "pack", "DiscInfo.pak")
        os.makedirs(os.path.dirname(kept))
        shutil.copy2(self.game.pak_path("DiscInfo"), kept)
        with open(self.game.pak_path("DiscInfo"), "ab") as f:
            f.write(b"changed by hand")
        Backup(self.game).protect("pack/DiscInfo.pak")
        with open(self.game.path("backup", "openDMT3.json"), encoding="utf-8") as f:
            entry = json.load(f)["files"]["pack/DiscInfo.pak"]
        self.assertEqual(entry["sha256"], g.sha256_file(kept))
        self.assertTrue(Backup(self.game).changed("pack/DiscInfo.pak"))

    def _backup_listing(self):
        """Every file under the game folder's backup\\, relative and "/" separated."""
        found = []
        for folder, _, names in os.walk(self.game.path("backup")):
            for name in names:
                found.append(os.path.relpath(os.path.join(folder, name), self.game.path("backup")).replace(os.sep, "/"))
        return sorted(found)

    def test_forgetting_takes_away_only_the_copies_this_tool_made(self):
        # Someone kept an original by hand before openDMT3 came (the way such folders were set up).
        hand = self.game.path("backup", "pack", "Config.pak")
        os.makedirs(os.path.dirname(hand))
        shutil.copy2(self.game.pak_path("Config"), hand)
        before = sorted(os.listdir(self.game.root))
        pack_before = sorted(os.listdir(self.game.path("pack")))
        self._run_setup(older.Options(server="127.0.0.1:4725"))
        kept = Backup(self.game)
        # The copy made here is marked; the one found in backup\ is not.
        self.assertTrue(kept.files["pack/DiscInfo.pak"]["copied"])
        self.assertNotIn("copied", kept.files["pack/Config.pak"])
        # While a file is still changed nothing is forgotten: the copies are its only originals.
        self.assertIsNone(kept.forget())
        self.assertTrue(os.path.isfile(kept.manifest_path))
        kept.restore_all()
        # Left by crashes: a copy cut short in backup\, and one on its way back into the game folder.
        with open(self.game.path("backup", "pack", "DiscInfo.pak.opendmt3-tmp"), "wb") as f:
            f.write(b"half")
        with open(self.game.path("pack", "DiscInfo.pak.opendmt3-tmp"), "wb") as f:
            f.write(b"half")
        stays = Backup(self.game).forget()
        self.assertEqual(stays, ["pack/Config.pak"])
        # Only the hand-kept original is left in backup\, and the game folder holds what it held before.
        self.assertEqual(self._backup_listing(), ["pack/Config.pak"])
        self.assertEqual(sorted(os.listdir(self.game.root)), sorted(before))
        self.assertEqual(sorted(os.listdir(self.game.path("pack"))), pack_before)
        # Forgetting again finds nothing to do.
        self.assertEqual(Backup(self.game).forget(), [])

    def test_forgetting_keeps_copies_it_cannot_vouch_for(self):
        self._run_setup(older.Options(server="127.0.0.1:4725"))
        with open(self.game.path("backup", "openDMT3.json"), encoding="utf-8") as f:
            data = json.load(f)
        # As the earliest versions listed them: no mark on any copy.
        for entry in data["files"].values():
            entry.pop("copied", None)
        with open(self.game.path("backup", "openDMT3.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)
        copies = [key for key, entry in data["files"].items() if entry["existed"]]
        Backup(self.game).restore_all()
        self.assertEqual(Backup(self.game).forget(), sorted(copies))
        # Every copy stays; the list goes (a later PLAY takes each copy as the original again).
        self.assertEqual(self._backup_listing(), sorted(copies))
        self.assertFalse(os.path.exists(self.game.path("backup", "openDMT3.json")))

    def test_forgetting_keeps_a_marked_copy_that_was_changed_since(self):
        self._run_setup(older.Options(server="127.0.0.1:4725"))
        Backup(self.game).restore_all()
        # Someone wrote over the copy in backup\: it is no longer the copy that was listed.
        with open(self.game.path("backup", "pack", "DiscInfo.pak"), "ab") as f:
            f.write(b"someone else's")
        self.assertIn("pack/DiscInfo.pak", Backup(self.game).forget())
        # Kept, under a name no later PLAY takes for the original: that PLAY copies the game's own file instead.
        self.assertIn("pack/DiscInfo.pak" + NOT_ORIGINAL, self._backup_listing())
        original = _read(self.game.pak_path("DiscInfo"))
        Backup(self.game).protect("pack/DiscInfo.pak")
        self.assertEqual(_read(self.game.path("backup", "pack", "DiscInfo.pak")), original)

    def test_forgetting_on_windows_read_only_copies_and_a_copy_that_will_not_go(self):
        self._run_setup(older.Options(server="127.0.0.1:4725"))
        Backup(self.game).restore_all()
        real_remove = os.remove
        stuck = self.game.path("backup", "pack", "Config.pak")

        def windows_remove(path):
            # Windows refuses to delete a read-only file; one copy is held open by another program the whole time.
            if path == stuck or not os.stat(path).st_mode & stat.S_IWRITE:
                raise PermissionError(13, "Access is denied", path)
            real_remove(path)

        # A copy read-only, as copies of files from a CD are.
        os.chmod(self.game.path("backup", "pack", "DiscInfo.pak"), stat.S_IREAD)
        with mock.patch("os.remove", windows_remove):
            stays = Backup(self.game).forget()
        # The read-only one went; the one that would not go stays, and the list went before either was touched,
        # so no later PLAY finds a list naming a copy that is gone.
        self.assertEqual(stays, ["pack/Config.pak"])
        self.assertEqual(self._backup_listing(), ["pack/Config.pak"])
        # The copy left behind is the file the game has, so a later PLAY rightly takes it as the original.
        self.assertEqual(_read(stuck), _read(self.game.pak_path("Config")))

    def test_a_game_folder_with_korean_letters_and_spaces(self):
        # Where people keep games: a folder named in their own language, with spaces and brackets.
        parent = tempfile.mkdtemp(prefix="테크니카 3 (게임) ")
        self.addCleanup(shutil.rmtree, parent)
        root = os.path.join(parent, "새 폴더", "DMT3 게임")
        shutil.copytree(self.game.root, root)
        game = g.Game.find(parent)
        self.assertEqual(game.root, root)
        before = {rel: _read(game.path(*rel.split("/"))) for rel in ("pack/DiscInfo.pak", "pack/Config.pak")}
        kept = Backup(game)
        for rel in older.MANAGED:
            kept.protect(rel)
        options = older.Options(server="127.0.0.1:4725")
        for step in older.STEPS:
            if not step.status(game, kept, options).done:
                step.apply(game, kept, options)
        self.assertTrue(Backup(game).still_changed())
        Backup(game).restore_all()
        for rel, data in before.items():
            self.assertEqual(_read(game.path(*rel.split("/"))), data, rel)
        self.assertEqual(Backup(game).forget(), [])
        self.assertFalse(os.path.exists(game.path("backup")))

    def test_putting_back_from_a_copy_that_is_gone_is_worded(self):
        self._run_setup(older.Options(server="127.0.0.1:4725"))
        os.remove(self.game.path("backup", "pack", "DiscInfo.pak"))
        with self.assertRaises(g.GameError) as e:
            Backup(self.game).restore_all()
        self.assertEqual(e.exception.key, "error.game.original_missing")

    def test_keep_hidden_puts_the_lists_back(self):
        self._run_setup(older.Options())
        self._run_setup(older.Options(unlock=False))
        with pak.Pak(self.game.pak_path("DiscInfo"), self.table) as p:
            self.assertEqual(stage_lists.count_hidden(p.read(p.find("Resource\\DiscInfo\\pop_stage_1.csv"))), 2)


@unittest.skipUnless(os.environ.get("OPENDMT3_GAME_DIR"), "needs OPENDMT3_GAME_DIR (the player's own game folder)")
class DisplayFixTest(unittest.TestCase):
    def test_fix_of_the_players_client(self):
        from opendmt3.core.cabinet import display
        game = g.Game.find(os.environ["OPENDMT3_GAME_DIR"])
        client = game.base_client()
        self.assertIsNotNone(client)
        with open(client, "rb") as f:
            fixed = display.patch(f.read())
        import hashlib
        self.assertEqual(hashlib.sha256(fixed).hexdigest(), g.PC_BUILD_DISPLAY_FIX)
        # Large-address aware: the game may use 4 GB of addresses (under Wine it ran out with 2 GB).
        self.assertTrue(fixed[display.CHARACTERISTICS_AT] & display.LARGE_ADDRESS_AWARE)
        # The fix an earlier openDMT3 made (the same without the flag) becomes the current one.
        earlier = bytearray(fixed)
        earlier[display.CHARACTERISTICS_AT] &= ~display.LARGE_ADDRESS_AWARE & 0xFF
        self.assertEqual(hashlib.sha256(earlier).hexdigest(), g.PC_BUILD_DISPLAY_FIX_EARLIER)
        self.assertEqual(display.patch(bytes(earlier)), fixed)
        # The fixed client is not an input the fix accepts again.
        with self.assertRaises(display.PatchError):
            display.patch(fixed)


if __name__ == "__main__":
    unittest.main()


class GameLibraryTest(FolderCase):
    """An earlier openDMT3 put its CRT_R1.dll (the card reader and the in-game layer) into the game folder in every way
    of playing, with the faces its words are drawn in and their licences; putting the files back takes them out."""

    def setUp(self):
        super().setUp()
        # A stand-in for the built library (a copy of the repository has none).
        self.dll = os.path.join(self.tmp, "built", "CRT_R1.dll")
        os.makedirs(os.path.dirname(self.dll))
        with open(self.dll, "wb") as f:
            f.write(b"MZ openDMT3 library stand-in")
        with open(self.game.path("CRT_R1.dll"), "wb") as f:
            f.write(b"MZ the cabinet's reader")
        patch = mock.patch.dict(os.environ, {"OPENDMT3_CARD_READER": self.dll})
        patch.start()
        self.addCleanup(patch.stop)

    def _library(self):
        return {rel: _read(self.game.path(rel)) if os.path.exists(self.game.path(rel)) else None
                for rel in older.CardReader.FILES}

    def test_every_way_of_playing_puts_the_library_in(self):
        from opendmt3.core.cabinet import native
        for card in (True, False):
            # A card (this PC, another server) or none (offline): the same files.
            self._run_setup(older.Options(server="127.0.0.1:4725" if card else "official", card_reader=card))
            files = self._library()
            self.assertEqual(files["CRT_R1.dll"], b"MZ openDMT3 library stand-in")
            self.assertEqual(files[older.CardReader.FONT], _read(native.font()))
            self.assertEqual(files[older.CardReader.FONT_REGULAR], _read(native.font_regular()))
            self.assertEqual(files[older.CardReader.FONT_WIDE], _read(native.font_wide()))
            self.assertEqual(files[older.CardReader.LICENCE], _read(native.font_licence()))
            self.assertEqual(files[older.CardReader.LICENCE_WIDE], _read(native.font_wide_licence()))
            status = older.CardReader().status(self.game, Backup(self.game), older.Options(card_reader=card))
            self.assertTrue(status.done)
            # Offline the status line says the reader holds no card: the game plays with NO ID CARD.
            self.assertIn("NO ID CARD" if not card else "card reader", status.detail)

    def test_putting_back_takes_the_library_out(self):
        self._run_setup(older.Options(card_reader=False))
        Backup(self.game).restore_all()
        files = self._library()
        self.assertEqual(files["CRT_R1.dll"], b"MZ the cabinet's reader")
        # The faces and their licences were not the game's: they go.
        for rel in older.CardReader.FILES[1:]:
            self.assertIsNone(files[rel], rel)

    def test_a_copy_without_the_library_plays_offline_with_the_cabinet_reader(self):
        with mock.patch.dict(os.environ, {"OPENDMT3_CARD_READER": os.path.join(self.tmp, "none.dll")}):
            status = older.CardReader().status(self.game, Backup(self.game), older.Options(card_reader=False))
            self.assertTrue(status.done)
            self.assertIn("cabinet", status.detail)
            # With a card to put in, the library is needed: said, and the step refuses.
            self.assertFalse(older.CardReader().status(self.game, Backup(self.game), older.Options(card_reader=True)).done)
            with self.assertRaises(g.GameError):
                older.CardReader().apply(self.game, Backup(self.game), older.Options(card_reader=True))
