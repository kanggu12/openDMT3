"""Tests of what PLAY makes in openDMT3's own folder from a game folder it only reads (core/cabinet/steps.py), of the
libraries a program imports (core/formats/pe.py), and of the short path to a game folder (core/cabinet/launch.py).

The game folder is a made-up one (tests/core/test_setup.py FolderCase): a client the setup does not know, two small
archives written with a random descriptor table, the operator data the game starts from in file\\.
"""

import hashlib
import os
import shutil
import struct
import tempfile
import unittest
from unittest import mock

from opendmt3.core import game as g
from opendmt3.core.cabinet import launch, steps
from opendmt3.core.formats import game_settings, pak, pe, settings_ini, stage_lists
from tests.core import older_setup as older
from tests.core.test_setup import FolderCase, _read


def tiny_pe(imports):
    """A made-up 32-bit program whose import table names `imports` (no code: only what the loader's table holds)."""
    # The DOS header points at the PE header at 0x40; one section (.idata) at RVA 0x1000, in the file at 0x200.
    head = bytearray(0x200)
    head[0:2] = b"MZ"
    struct.pack_into("<I", head, 0x3C, 0x40)
    head[0x40:0x44] = b"PE\x00\x00"
    # COFF: i386, one section, a PE32 optional header of 0xE0 bytes.
    struct.pack_into("<HHIIIHH", head, 0x44, 0x14C, 1, 0, 0, 0, 0xE0, 0x102)
    struct.pack_into("<H", head, 0x58, 0x10B)
    # The import directory (data directory 1) at RVA 0x1000.
    table = bytearray()
    names = bytearray()
    first_name = 0x1000 + 20 * (len(imports) + 1)
    for i, name in enumerate(imports):
        rva = first_name + len(names)
        # OriginalFirstThunk, TimeDateStamp, ForwarderChain, Name, FirstThunk (any non-zero place).
        table += struct.pack("<IIIII", 0, 0, 0, rva, 0x1800 + 4 * i)
        names += name.encode("ascii") + b"\x00"
    table += bytes(20)
    body = table + names
    struct.pack_into("<II", head, 0xC0, 0x1000, len(table))
    # The section header: .idata, its virtual size and address, raw size and file offset.
    struct.pack_into("<8sIIII", head, 0x138, b".idata", len(body), 0x1000, len(body), 0x200)
    return bytes(head) + bytes(body)


def snapshot(root):
    """Every file under a folder with its fingerprint, and every folder: what a run may not change."""
    seen = {}
    for folder, dirs, files in os.walk(root):
        rel = os.path.relpath(folder, root)
        seen[rel + "/"] = None
        for name in files:
            seen[os.path.join(rel, name)] = g.sha256_file(os.path.join(folder, name))
    return seen


class OwnCase(FolderCase):
    """A made-up game folder and an empty folder of openDMT3's, with a stand-in for openDMT3's built library."""

    def setUp(self):
        super().setUp()
        self.patcher.stop()
        table = self.table

        # The table as Game.table finds it, with the client it came from (the folder's only program).
        def table_of(game):
            game.client = (game.path("Client.exe"), g.MODIFIED)
            return table

        self.patcher = mock.patch.object(g.Game, "table", table_of)
        self.patcher.start()
        self.own = steps.Own(os.path.join(self.tmp, "openDMT3", "game"))
        self.dll = os.path.join(self.tmp, "built", "CRT_R1.dll")
        os.makedirs(os.path.dirname(self.dll))
        with open(self.dll, "wb") as f:
            f.write(b"MZ openDMT3 library stand-in")
        env = mock.patch.dict(os.environ, {"OPENDMT3_CARD_READER": self.dll})
        env.start()
        self.addCleanup(env.stop)

    def prepare(self, options=None):
        # A new Game each time, as each PLAY finds the folder again.
        return steps.prepare(g.Game(self.game.root), self.own, options or steps.Options(server="127.0.0.1:4725"))


class OwnFolderTest(OwnCase):
    def test_play_only_reads_the_game_folder(self):
        before = snapshot(self.tmp + "/unpacked")
        done = self.prepare()
        self.assertEqual([line.split(":")[0] for line in done],
                         ["client", "game library", "settings", "free play", "guest unlock", "server address"])
        self.assertEqual(snapshot(self.tmp + "/unpacked"), before)
        for name in (g.FIXED_EXE, "CRT_R1.dll", "setting.ini", "openDMT3-files.txt", os.path.join("pack", "Config.pak"),
                     os.path.join("pack", "DiscInfo.pak"), os.path.join("TECHNIKA", "GAME", "game")):
            self.assertTrue(os.path.isfile(self.own.path(name)), name)
        # The client copy: a client the fix does not know is copied as it is (played without the screen fit).
        self.assertEqual(_read(self.own.client()), _read(self.game.path("Client.exe")))

    def test_a_second_check_reads_no_file_that_did_not_change(self):
        self.prepare()
        g.save_hash_cache()

        real_read = steps._read

        def no_reading(path, *args, **kwargs):
            # openDMT3's own small files may be read (the operator data's settings, which the game may change); the
            # game's files and the copies are not.
            if isinstance(path, str) and path.startswith(self.own.folder) and not path.endswith((".exe", ".dll", ".pak")):
                return real_read(path)
            raise AssertionError("read %s, whose size and time did not change" % path)

        # Every step's check, from the records and the fingerprints by size and time alone.
        game = g.Game(self.game.root)
        game.table()
        with mock.patch.object(steps, "_read", no_reading), mock.patch.object(g, "sha256_file", no_reading), \
                mock.patch.object(pak, "Pak", no_reading):
            for step in steps.STEPS:
                self.assertTrue(step.status(game, self.own, steps.Options(server="127.0.0.1:4725")).done, step.name)
        # A file that changed is read again (its size changed here).
        with open(self.game.pak_path("DiscInfo"), "ab") as f:
            f.write(b"more")
        self.assertFalse(steps.GuestUnlock().status(g.Game(self.game.root), self.own, steps.Options()).done)

    def test_fingerprints_by_size_and_time_are_kept_between_runs(self):
        cache = os.path.join(self.tmp, "hashes.json")
        g.use_hash_cache(cache)
        self.addCleanup(g.use_hash_cache, None)
        path = self.game.pak_path("Config")
        digest = g.known_sha256(path)
        g.save_hash_cache()
        # A new run (the cache read again): the same answer without reading the file.
        g.use_hash_cache(cache)
        with mock.patch.object(g, "sha256_file", lambda p: "read again"):
            self.assertEqual(g.known_sha256(path), digest)
            os.utime(path, ns=(1, 1))
            self.assertEqual(g.known_sha256(path), "read again")

    def test_a_second_play_makes_nothing_again(self):
        self.prepare()
        made = snapshot(self.own.folder)
        self.assertEqual(self.prepare(), [])
        self.assertEqual(snapshot(self.own.folder), made)

    def test_the_settings_are_the_games_own_with_what_a_pc_needs(self):
        self.prepare()
        text = settings_ini.decode(_read(self.own.path("setting.ini")))
        self.assertEqual(settings_ini.get_value(text, "fullscreen"), "false")
        self.assertEqual(settings_ini.get_value(text, "gameSettingFilePath"), "TECHNIKA/GAME/")

    def test_the_operator_data_is_taken_once_with_free_play_on(self):
        self.prepare()
        s = game_settings.GameSettings.parse(_read(self.own.path("TECHNIKA", "GAME", "game")))
        self.assertEqual((s.free_play, s.coins_per_credit), (1, 2))
        self.assertTrue(os.path.isfile(self.own.path("TECHNIKA", "RANK", "club")))
        # The game writes openDMT3's copy as it is played; the game folder's own is never taken again.
        with open(self.own.path("TECHNIKA", "RANK", "club"), "wb") as f:
            f.write(b"played since")
        with open(self.game.path("file", "game"), "wb") as f:
            f.write(game_settings.GameSettings(coins_per_credit=5).build())
        self.prepare()
        self.assertEqual(_read(self.own.path("TECHNIKA", "RANK", "club")), b"played since")
        s = game_settings.GameSettings.parse(_read(self.own.path("TECHNIKA", "GAME", "game")))
        self.assertEqual(s.coins_per_credit, 2)

    def test_the_operator_data_of_a_copy_of_a_cabinets_drives(self):
        # drive d\DMT3 is the game folder; drive e\TECHNIKA the cabinet's operator data, in any letter case.
        drives = os.path.join(self.tmp, "cabinet")
        root = os.path.join(drives, "drive d", "DMT3")
        shutil.copytree(self.game.root, root)
        data = os.path.join(drives, "Drive E", "TECHNIKA")
        for sub in ("BOOK", "GAME", "RANK"):
            os.makedirs(os.path.join(data, sub))
        with open(os.path.join(data, "GAME", "game"), "wb") as f:
            f.write(game_settings.GameSettings(coins_per_credit=3).build())
        with open(os.path.join(data, "RANK", "cabinet-ranking"), "wb") as f:
            f.write(b"the cabinet's")
        game = g.Game(root)
        self.assertEqual(steps.FreePlay.source(game), (data, "cabinet"))
        steps.FreePlay().apply(game, self.own, steps.Options())
        self.assertEqual(_read(self.own.path("TECHNIKA", "RANK", "cabinet-ranking")), b"the cabinet's")
        s = game_settings.GameSettings.parse(_read(self.own.path("TECHNIKA", "GAME", "game")))
        self.assertEqual((s.free_play, s.coins_per_credit), (1, 3))

    def test_the_operator_data_an_earlier_openDMT3_kept_in_the_game_folder_comes_first(self):
        self._run_setup(older.Options())
        with open(self.game.path("TECHNIKA", "RANK", "the-players"), "wb") as f:
            f.write(b"rankings played with an earlier openDMT3")
        self.assertEqual(steps.FreePlay.source(g.Game(self.game.root))[1], "game")
        self.prepare()
        self.assertEqual(_read(self.own.path("TECHNIKA", "RANK", "the-players")),
                         b"rankings played with an earlier openDMT3")

    def test_no_operator_data_at_all_starts_from_the_games_defaults(self):
        shutil.rmtree(self.game.path("file"))
        self.prepare()
        self.assertEqual(sorted(os.listdir(self.own.path("TECHNIKA"))), ["BOOK", "GAME", "RANK"])
        self.assertEqual(game_settings.GameSettings.parse(_read(self.own.path("TECHNIKA", "GAME", "game"))).free_play, 1)

    def test_the_changed_archives_and_the_list(self):
        self.prepare()
        with pak.Pak(self.own.path("pack", "DiscInfo.pak"), self.table) as p:
            self.assertEqual(stage_lists.count_hidden(p.read(p.find("Resource\\DiscInfo\\pop_stage_1.csv"))), 0)
            self.assertEqual(p.read(p.find("Resource\\DiscInfo\\discstock.csv")), b"no,name\r\n")
        self.assertEqual(steps.ServerAddress().current(self.game, self.own.path("pack", "Config.pak")),
                         ("127.0.0.1", "4725"))
        lines = _read(self.own.path("openDMT3-files.txt")).decode("utf-8").split("\r\n")
        self.assertEqual(lines, ["Resource\\config\\setting.ini\tsetting.ini", "TECHNIKA\\\tTECHNIKA", "Dump\\\tDump",
                                 g.FIXED_EXE + "\t" + g.FIXED_EXE, "pack\\DiscInfo.pak\tpack\\DiscInfo.pak",
                                 "pack\\Config.pak\tpack\\Config.pak", ""])
        # Offline with the patterns kept hidden: the game's own archives, so neither copy nor its lines.
        self.prepare(steps.Options(server="official", unlock=False))
        self.assertFalse(os.path.exists(self.own.path("pack", "DiscInfo.pak")))
        self.assertFalse(os.path.exists(self.own.path("pack", "Config.pak")))
        self.assertNotIn("pack", _read(self.own.path("openDMT3-files.txt")).decode("utf-8"))

    def test_a_list_a_patch_holds_is_changed_in_that_patch(self):
        # The newest archive with the stage list is a patch: the game reads it from there, so its copy is the patch's.
        self._pak(os.path.join(self.game.root, "pack", "DiscInfo00.pak"),
                  {"Resource\\DiscInfo\\pop_stage_1.csv": b"stage1,songname,SP,PT,Hid\r\n1,songc,2,1,1\r\n"})
        self.prepare()
        self.assertFalse(os.path.exists(self.own.path("pack", "DiscInfo.pak")))
        with pak.Pak(self.own.path("pack", "DiscInfo00.pak"), self.table) as p:
            self.assertEqual(stage_lists.count_hidden(p.read(p.find("Resource\\DiscInfo\\pop_stage_1.csv"))), 0)
        lines = _read(self.own.path("openDMT3-files.txt")).decode("utf-8").split("\r\n")
        self.assertIn("pack\\DiscInfo00.pak\tpack\\DiscInfo00.pak", lines)
        self.assertNotIn("pack\\DiscInfo.pak\tpack\\DiscInfo.pak", lines)

    def test_a_copy_is_made_again_when_its_source_changed(self):
        self.prepare()
        first = _read(self.own.path("pack", "Config.pak"))
        # Another address: made again; the same address from another game folder's archive: made again too.
        self.prepare(steps.Options(server="127.0.0.2:5000"))
        self.assertEqual(steps.ServerAddress().current(self.game, self.own.path("pack", "Config.pak")),
                         ("127.0.0.2", "5000"))
        self._pak(self.game.pak_path("Config"), {"Resource\\Config\\setting.ini": _setting(),
                                                "Resource\\Config\\networksetting.ini": b"serverip=1\r\nport=2\r\n"})
        self.prepare()
        self.assertNotEqual(_read(self.own.path("pack", "Config.pak")), first)
        self.assertEqual(steps.ServerAddress().current(self.game, self.own.path("pack", "Config.pak")),
                         ("127.0.0.1", "4725"))

    def test_a_bad_address_is_said_before_anything_is_made(self):
        with self.assertRaises(g.GameError) as e:
            steps.ServerAddress().apply(self.game, self.own, steps.Options(server="nowhere"))
        self.assertEqual(e.exception.key, "error.game.server_address")
        self.assertFalse(os.path.exists(self.own.path("pack")))

    def test_a_folder_an_earlier_openDMT3_changed_is_read_through_its_backup(self):
        original = _read(self.game.pak_path("Config"))
        self._run_setup(older.Options(server="127.0.0.1:4725"))
        self.assertNotEqual(_read(self.game.pak_path("Config")), original)
        before = snapshot(self.tmp + "/unpacked")
        # Offline: no address of openDMT3's, so the game is given the original kept in backup\, named from the game
        # folder (the list names no whole path).
        self.prepare(steps.Options(server="official"))
        self.assertEqual(snapshot(self.tmp + "/unpacked"), before)
        lines = _read(self.own.path("openDMT3-files.txt")).decode("utf-8").split("\r\n")
        self.assertIn("pack\\Config.pak\t<game>\\backup\\pack\\Config.pak", lines)
        # Every path in the list is relative: to openDMT3's folder, or to the game folder after <game>\.
        for line in filter(None, lines):
            left, right = line.split("\t")
            for path in (left, right[len(steps.GAME_MARK):] if right.startswith(steps.GAME_MARK) else right):
                self.assertFalse(os.path.isabs(path) or ":" in path or ".." in path.split("\\"), line)
        # The guest unlock is openDMT3's own copy, so the older change to DiscInfo.pak is not given as well.
        self.assertEqual([line for line in lines if line.startswith("pack\\DiscInfo")],
                         ["pack\\DiscInfo.pak\tpack\\DiscInfo.pak"])
        # Another address is made from the original, never from the older change.
        self.prepare(steps.Options(server="127.0.0.2:5000"))
        with pak.Pak(self.own.path("pack", "Config.pak"), self.table) as mine, \
                pak.Pak(self.game.path("backup", "pack", "Config.pak"), self.table) as kept:
            self.assertEqual(mine.read(mine.find("Resource\\Config\\setting.ini")),
                             kept.read(kept.find("Resource\\Config\\setting.ini")))
        self.assertEqual(steps.ServerAddress().current(self.game, self.own.path("pack", "Config.pak")),
                         ("127.0.0.2", "5000"))

    def test_a_backup_list_that_cannot_be_read_gives_the_folders_own_files(self):
        os.makedirs(self.game.path("backup"))
        with open(self.game.path("backup", "openDMT3.json"), "w") as f:
            f.write("{ not json")
        self.prepare()
        self.assertTrue(os.path.isfile(self.own.path("pack", "Config.pak")))

    def test_without_openDMT3s_library_nothing_can_be_given_to_the_game(self):
        with mock.patch.dict(os.environ, {"OPENDMT3_CARD_READER": os.path.join(self.tmp, "none.dll")}):
            self.assertFalse(steps.CardReader().status(self.game, self.own, steps.Options()).done)
            with self.assertRaises(g.GameError) as e:
                steps.CardReader().apply(self.game, self.own, steps.Options())
        self.assertEqual(e.exception.key, "error.game.no_card_reader")

    def test_the_library_and_its_faces_beside_the_client(self):
        from opendmt3.core.cabinet import native
        self.prepare()
        self.assertEqual(_read(self.own.path("CRT_R1.dll")), b"MZ openDMT3 library stand-in")
        self.assertEqual(_read(self.own.path(steps.CardReader.FONT)), _read(native.font()))
        self.assertEqual(_read(self.own.path(steps.CardReader.LICENCE_WIDE)), _read(native.font_wide_licence()))
        status = steps.CardReader().status(self.game, self.own, steps.Options(card_reader=False))
        self.assertIn("NO ID CARD", status.detail)


def _setting():
    from tests.core.test_setup import SETTINGS
    return SETTINGS


class ClientTest(OwnCase):
    """openDMT3's copy of the client and the client's libraries from the game folder."""

    def setUp(self):
        super().setUp()
        # A client importing Windows' own libraries, one of the game's (which imports another of the game's in turn)
        # and the card reader; the cabinet's card reader is in the folder too.
        with open(self.game.path("Client.exe"), "wb") as f:
            f.write(tiny_pe(["KERNEL32.dll", "libmadeup.DLL", "CRT_R1.dll", "d3d9.dll", "KERNEL32.DLL"]))
        with open(self.game.path("LibMadeUp.dll"), "wb") as f:
            f.write(tiny_pe(["KERNEL32.dll", "libdeep.dll"]))
        with open(self.game.path("libdeep.dll"), "wb") as f:
            f.write(b"MZ a library that is no program")
        with open(self.game.path("CRT_R1.dll"), "wb") as f:
            f.write(b"MZ the cabinet's reader")

    def test_the_libraries_the_client_needs_from_the_game_folder(self):
        found = steps.Client().libraries(self.game, _read(self.game.path("Client.exe")))
        self.assertEqual(sorted(found), ["LibMadeUp.dll", "libdeep.dll"])
        self.prepare()
        self.assertEqual(_read(self.own.path("LibMadeUp.dll")), _read(self.game.path("LibMadeUp.dll")))
        self.assertEqual(_read(self.own.path("libdeep.dll")), _read(self.game.path("libdeep.dll")))
        # openDMT3's card reader, never the cabinet's.
        self.assertEqual(_read(self.own.path("CRT_R1.dll")), b"MZ openDMT3 library stand-in")
        self.assertTrue(steps.Client().status(self.game, self.own, steps.Options()).done)

    def test_a_library_changed_in_the_game_folder_is_copied_again(self):
        self.prepare()
        with open(self.game.path("libdeep.dll"), "wb") as f:
            f.write(b"MZ a newer one")
        self.assertFalse(steps.Client().status(self.game, self.own, steps.Options()).done)
        self.prepare()
        self.assertEqual(_read(self.own.path("libdeep.dll")), b"MZ a newer one")

    def test_a_modified_client_gets_the_large_address_flag_alone(self):
        from opendmt3.core.cabinet import display
        client = tiny_pe(["KERNEL32.dll"])
        made = steps.Client()._made(client)
        pe = struct.unpack_from("<I", client, 0x3C)[0]
        # The flag on, every other byte the same.
        self.assertEqual(made[pe + 0x16], client[pe + 0x16] | display.LARGE_ADDRESS_AWARE)
        self.assertEqual(made[:pe + 0x16] + made[pe + 0x17:], client[:pe + 0x16] + client[pe + 0x17:])
        # What is no program is copied as it is.
        self.assertEqual(steps.Client()._made(b"MZ not a known client"), b"MZ not a known client")
        with self.assertRaises(display.PatchError):
            display.large_address_aware(b"PK not a program")

    def test_the_pc_client_gets_the_screen_fit(self):
        made = []
        with mock.patch.object(steps.display, "patch", lambda data: made.append(data) or b"fixed " + data):
            fixed = steps.Client()._made(b"pc client")
            self.assertEqual(made, [])
            self.assertEqual(fixed, b"pc client")
            digest = hashlib.sha256(b"pc client").hexdigest()
            with mock.patch.object(g, "PC_BUILD", digest):
                self.assertEqual(steps.Client()._made(b"pc client"), b"fixed pc client")


class ImportsTest(unittest.TestCase):
    def test_the_names_a_program_imports_each_once(self):
        self.assertEqual(pe.imports(tiny_pe(["KERNEL32.dll", "a.dll", "kernel32.DLL", "b.dll"])),
                         ["KERNEL32.dll", "a.dll", "b.dll"])
        self.assertEqual(pe.imports(tiny_pe([])), [])

    def test_what_is_no_program_is_said(self):
        for data in (b"", b"MZ", b"MZ not a known client", b"PK\x03\x04", tiny_pe(["a.dll"])[:0x150]):
            with self.assertRaises(pe.PeError):
                pe.imports(data)


class StandInSystem(launch.System):
    """The short path's calls to the system as a test sets them, the same on every system: the game folder's 8.3 short
    name (or none), and which folders are this user's alone (those it made, or made its own; any in `others` is
    someone else's)."""

    def __init__(self, short=None):
        self.short, self.mine, self.others = short, set(), set()

    def short_name(self, path):
        return self.short

    def make_folder(self, path):
        os.mkdir(path)
        self.mine.add(os.path.normcase(path))

    def own(self, path):
        return os.path.isdir(path) and not launch._is_link(path) and os.path.normcase(path) in self.mine

    def make_own(self, path):
        if os.path.normcase(path) in self.others or not os.path.isdir(path) or launch._is_link(path):
            return False
        self.mine.add(os.path.normcase(path))
        return True


class ShortPathTest(unittest.TestCase):
    """A game folder the client cannot be given as it is goes through a short path: its own 8.3 short name when that
    fits, else a link of openDMT3's (a junction on Windows; a symbolic link stands in for it here) in a folder of this
    user's alone, which leads to the game folder and nowhere else, is checked again right before the game starts, and
    goes again. The system's calls are a stand-in's (StandInSystem; WindowsCallsTest has Windows' own)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.made = []
        self.system = StandInSystem()
        patch = mock.patch.object(launch, "SYSTEM", self.system)
        patch.start()
        self.addCleanup(patch.stop)

    def folder(self, *parts):
        """A real folder under the test's own (a game folder the link can lead to)."""
        path = os.path.join(self.tmp, *parts)
        os.makedirs(path, exist_ok=True)
        return path

    def make(self, target, link):
        # A stand-in for the junction: a link to the folder asked for.
        self.made.append((target, link))
        os.symlink(target, link)

    def test_a_folder_that_fits_is_given_as_it_is(self):
        root = "C:\\Games\\DMT3"
        self.assertEqual(launch.short_path(root, [self.tmp], self.make), root)
        self.assertEqual(self.made, [])

    def test_a_long_folder_goes_through_the_first_place_that_fits(self):
        root = self.folder("L" * 200)
        too_long = os.path.join(self.tmp, "x" * 200)
        place = os.path.join(self.tmp, "links")
        link = launch.short_path(root, [too_long, place], self.make)
        self.assertEqual(link, os.path.join(place, "game"))
        self.assertEqual(self.made, [(root, link)])
        self.assertEqual(os.path.realpath(link), os.path.realpath(root))
        # The next PLAY makes it again (it may be another game folder by then); the game's end takes it away.
        launch.short_path(root, [place], self.make)
        self.assertEqual(len(self.made), 2)
        self.assertTrue(launch.take_short_path_away(place))
        self.assertFalse(os.path.lexists(link))
        self.assertTrue(os.path.isdir(root))

    def test_a_folder_outside_the_ansi_code_page(self):
        root = self.folder("테크니카", "DMT3")
        with mock.patch.object(launch, "ansi", lambda path: "테" not in path):
            self.assertEqual(launch.needs_short_path(root), "not ANSI")
            link = launch.short_path(root, [os.path.join(self.tmp, "테"), os.path.join(self.tmp, "links")], self.make)
        self.assertEqual(link, os.path.join(self.tmp, "links", "game"))

    def test_no_place_that_fits_is_said(self):
        with self.assertRaises(launch.LaunchError):
            launch.short_path(self.folder("L" * 200), [os.path.join(self.tmp, "x" * 200)], self.make)

    def test_a_folder_of_its_own_at_the_links_name_is_never_removed(self):
        # Someone's folder where openDMT3's link would go: left as it is, with what is in it, and the place passed by.
        mine = self.folder("taken", "game")
        with open(os.path.join(mine, "keep.txt"), "w") as f:
            f.write("someone's")
        self.assertFalse(launch.take_short_path_away(os.path.join(self.tmp, "taken")))
        self.assertTrue(os.path.isfile(os.path.join(mine, "keep.txt")))
        link = launch.short_path(self.folder("L" * 200), [os.path.join(self.tmp, "taken"),
                                                          os.path.join(self.tmp, "free")], self.make)
        self.assertEqual(link, os.path.join(self.tmp, "free", "game"))
        self.assertTrue(os.path.isfile(os.path.join(mine, "keep.txt")))

    def test_a_link_that_leads_anywhere_else_is_taken_away_and_said(self):
        elsewhere = self.folder("elsewhere")
        with self.assertRaises(launch.LaunchError):
            launch.short_path(self.folder("x" * 200), [os.path.join(self.tmp, "links")],
                              lambda target, link: os.symlink(elsewhere, link))
        self.assertFalse(os.path.lexists(os.path.join(self.tmp, "links", "game")))
        # What it led to is untouched.
        self.assertTrue(os.path.isdir(elsewhere))

    def test_taking_the_short_paths_away_leaves_the_game_folder(self):
        root = self.folder("y" * 200)
        with open(os.path.join(root, "Client.exe"), "w") as f:
            f.write("the game's")
        link = launch.short_path(root, [os.path.join(self.tmp, "links")], self.make)
        with mock.patch.object(launch, "link_places", lambda: [os.path.join(self.tmp, "links")]):
            launch.take_short_paths_away()
        self.assertFalse(os.path.lexists(link))
        self.assertTrue(os.path.isfile(os.path.join(root, "Client.exe")))

    def test_the_game_folders_own_short_name_comes_first(self):
        root = self.folder("L" * 200)
        # The drive keeps 8.3 names: the folder's own (a link stands in for it here) fits, and no junction is made.
        short = os.path.join(self.tmp, "LLLLLL~1")
        os.symlink(root, short)
        self.system.short = short
        self.assertEqual(launch.short_path(root, [os.path.join(self.tmp, "links")], self.make), short)
        self.assertEqual(self.made, [])
        # One that does not fit, or leads elsewhere, is not used: the junction is.
        self.system.short = os.path.join(self.tmp, "x" * 200)
        self.assertEqual(launch.short_path(root, [os.path.join(self.tmp, "links")], self.make),
                         os.path.join(self.tmp, "links", "game"))

    def test_a_shared_folder_gets_a_folder_of_this_users_alone_named_so_no_one_can_guess_it(self):
        # The user's own %LocalAppData% cannot be given to the game (letters outside the ANSI code page): the link
        # goes in a folder every user shares, in a folder made for this PLAY, new, under a random name, this user's.
        root = self.folder("테크니카", "DMT3")
        shared = self.folder("Public")
        with mock.patch.object(launch, "ansi", lambda path: "테" not in path), \
                mock.patch.dict(os.environ, {"LOCALAPPDATA": os.path.join(self.tmp, "테", "AppData"),
                                             "PUBLIC": shared, "ProgramData": ""}):
            first = launch.short_path(root, None, self.make)
            holder = os.path.dirname(first)
            self.assertEqual(os.path.dirname(holder), shared)
            self.assertRegex(os.path.basename(holder), r"^openDMT3-[0-9a-f]{16}$")
            self.assertTrue(self.system.own(holder))
            self.assertTrue(os.path.realpath(first) == os.path.realpath(root))
            # Another PLAY, another name: none is ever made from what another user could work out.
            second = launch.short_path(root, None, self.make)
            self.assertNotEqual(os.path.dirname(second), holder)
            # A folder of that form that is someone else's is never touched; this user's go with their links.
            theirs = self.folder("Public", "openDMT3-%s" % ("a" * 16))
            launch.take_short_paths_away()
        self.assertEqual(os.listdir(shared), [os.path.basename(theirs)])
        self.assertTrue(os.path.isdir(root))

    def test_a_name_someone_made_first_is_never_used(self):
        root = self.folder("x" * 200)
        shared = self.folder("Public")
        # Someone else's folder where this user's own place would be: passed by. In a shared folder a name already
        # there is passed by for another random one.
        theirs = self.folder("theirs")
        self.system.others.add(os.path.normcase(theirs))
        taken = self.folder("Public", "openDMT3-%s" % ("b" * 16))
        names = iter(["b" * 16, "c" * 16])
        with mock.patch.object(launch.secrets, "token_hex", lambda n: next(names)):
            link = launch.short_path(root, [theirs, (shared, True)], self.make)
        self.assertEqual(link, os.path.join(shared, "openDMT3-%s" % ("c" * 16), "game"))
        self.assertEqual(os.listdir(taken), [])
        self.assertFalse(os.path.lexists(os.path.join(theirs, "game")))

    def test_the_short_path_is_checked_again_right_before_the_game_starts(self):
        own = steps.Own(self.folder("own"))
        with open(own.client(), "wb") as f:
            f.write(b"MZ stand-in")
        started = []
        game = g.Game(self.folder("L" * 200))
        # Its folder no longer this user's alone between the making and the start: no game.
        real = launch.short_path

        def taken_meanwhile(*args, **kwargs):
            link = real(*args, **kwargs)
            self.system.mine.discard(os.path.normcase(os.path.dirname(link)))
            return link
        with mock.patch.object(launch, "short_path", taken_meanwhile), self.assertRaises(launch.LaunchError):
            launch.start(game, own, popen=lambda *a, **k: started.append(a), places=[os.path.join(self.tmp, "links")],
                         make=self.make)
        # The link led elsewhere at the last moment: no game, and the link is taken away.
        elsewhere = self.folder("elsewhere")

        def swapped(*args, **kwargs):
            link = real(*args, **kwargs)
            os.unlink(link)
            os.symlink(elsewhere, link)
            return link
        with mock.patch.object(launch, "short_path", swapped), self.assertRaises(launch.LaunchError):
            launch.start(game, own, popen=lambda *a, **k: started.append(a), places=[os.path.join(self.tmp, "links2")],
                         make=self.make)
        self.assertEqual(started, [])
        self.assertFalse(os.path.lexists(os.path.join(self.tmp, "links2", "game")))
        self.assertTrue(os.path.isdir(elsewhere))

    def test_the_client_copy_starts_with_the_game_folder_as_its_current_folder(self):
        own = steps.Own(self.folder("own"))
        with open(own.client(), "wb") as f:
            f.write(b"MZ stand-in")
        started = []

        def popen(args, cwd=None, env=None):
            started.append((args, cwd))
            return mock.Mock()

        game = g.Game(self.folder("L" * 200))
        launch.start(game, own, popen=popen, places=[os.path.join(self.tmp, "links")], make=self.make)
        self.assertEqual(started, [([own.client()], os.path.join(self.tmp, "links", "game"))])
        game = g.Game(self.folder("short"))
        launch.start(game, own, popen=popen, places=[], make=self.make)
        self.assertEqual(started[-1], ([own.client()], game.root))


class FakeWindows:
    """kernel32 and advapi32 as stand-ins: C functions (ctypes callbacks) that answer the short path's calls as Windows
    would, so each call goes through ctypes' own conversion of its arguments (the C types launch.py gives them), and
    what they were given is kept in `calls`. The process's user and the owner it gives what it makes are ME; the
    folder asked about has `owner` and the access list `access`."""

    ME, OTHER = "S-1-5-21-1-2-3-1001", "S-1-5-21-1-2-3-1002"

    def __init__(self, short=None):
        import ctypes
        import types
        from ctypes import wintypes
        self.short, self.owner, self.access = short, self.ME, "D:PAI(A;OICI;FA;;;%s)" % self.ME
        self.calls, self.kept, self.error = [], [], 0
        self.kernel32, self.advapi32 = types.SimpleNamespace(), types.SimpleNamespace()
        p = ctypes.c_void_p
        # Made-up pointers: the process's user and owner, the folder's owner, its access list and security.
        sids = {0x1001: lambda: self.ME, 0x1002: lambda: self.ME, 0x2001: lambda: self.owner}

        def put(address, kind, value):
            ctypes.cast(address, ctypes.POINTER(kind))[0] = value

        def wide(address, text):
            # A string Windows would allocate, kept alive while the caller reads it.
            buf = ctypes.create_unicode_buffer(text)
            self.kept.append(buf)
            put(address, p, ctypes.addressof(buf))

        def define(dll, name, result, args, body):
            function = ctypes.CFUNCTYPE(result, *args)(body)
            self.kept.append(function)
            setattr(dll, name, function)

        def short_path(path, buf, size):
            self.calls.append(("GetShortPathNameW", path))
            if self.short is None:
                return 0
            needed = len(self.short) + 1
            if not buf or size < needed:
                return needed
            ctypes.memmove(buf, ctypes.create_unicode_buffer(self.short), needed * ctypes.sizeof(ctypes.c_wchar))
            return needed - 1

        def token_information(token, kind, buf, size, needed):
            if not buf:
                put(needed, wintypes.DWORD, ctypes.sizeof(p))
                return 0
            put(buf, p, 0x1001 if kind == 1 else 0x1002)
            return 1

        def descriptor_from(text, revision, out, size):
            self.calls.append(("ConvertStringSecurityDescriptorToSecurityDescriptorW", text))
            put(out, p, 0x5000)
            return 1

        def create(path, security):
            class SECURITY_ATTRIBUTES(ctypes.Structure):
                _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", p), ("bInheritHandle", wintypes.BOOL)]
            self.calls.append(("CreateDirectoryW", path, SECURITY_ATTRIBUTES.from_address(security).lpSecurityDescriptor))
            if os.path.exists(path):
                # ERROR_ALREADY_EXISTS, as Windows leaves it for GetLastError.
                self.error = 183
                return 0
            os.mkdir(path)
            return 1

        def named_security(path, kind, info, owner, group, access, sacl, descriptor):
            self.calls.append(("GetNamedSecurityInfoW", path, info))
            put(owner, p, 0x2001)
            put(access, p, 0x3000)
            put(descriptor, p, 0x4000)
            return 0

        def descriptor_text(descriptor, revision, info, out, size):
            wide(out, self.access)
            return 1

        def sid_text(sid, out):
            wide(out, sids[sid]())
            return 1

        def access_of(descriptor, present, access, defaulted):
            put(present, wintypes.BOOL, 1)
            put(access, p, 0x3100)
            put(defaulted, wintypes.BOOL, 0)
            return 1

        def set_security(path, kind, info, owner, group, access, sacl):
            self.calls.append(("SetNamedSecurityInfoW", path, info, access))
            self.access = "D:PAI(A;OICI;FA;;;%s)" % self.ME
            return 0

        def open_token(process, access, token):
            put(token, p, 0x77)
            return 1

        for dll, name, result, args, body in (
                (self.kernel32, "GetShortPathNameW", wintypes.DWORD, [wintypes.LPCWSTR, p, wintypes.DWORD], short_path),
                (self.kernel32, "GetCurrentProcess", p, [], lambda: 0x99),
                (self.kernel32, "CloseHandle", wintypes.BOOL, [p], lambda handle: 1),
                (self.kernel32, "LocalFree", p, [p], lambda memory: 0),
                (self.kernel32, "CreateDirectoryW", wintypes.BOOL, [wintypes.LPCWSTR, p], create),
                (self.advapi32, "OpenProcessToken", wintypes.BOOL, [p, wintypes.DWORD, p], open_token),
                (self.advapi32, "GetTokenInformation", wintypes.BOOL, [p, ctypes.c_int, p, wintypes.DWORD, p],
                 token_information),
                (self.advapi32, "ConvertSidToStringSidW", wintypes.BOOL, [p, p], sid_text),
                (self.advapi32, "ConvertStringSecurityDescriptorToSecurityDescriptorW", wintypes.BOOL,
                 [wintypes.LPCWSTR, wintypes.DWORD, p, p], descriptor_from),
                (self.advapi32, "GetNamedSecurityInfoW", wintypes.DWORD,
                 [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, p, p, p, p, p], named_security),
                (self.advapi32, "ConvertSecurityDescriptorToStringSecurityDescriptorW", wintypes.BOOL,
                 [p, wintypes.DWORD, wintypes.DWORD, p, p], descriptor_text),
                (self.advapi32, "GetSecurityDescriptorDacl", wintypes.BOOL, [p, p, p, p], access_of),
                (self.advapi32, "SetNamedSecurityInfoW", wintypes.DWORD,
                 [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, p, p, p, p], set_security)):
            define(dll, name, result, args, body)


class WindowsCallsTest(unittest.TestCase):
    """The short path's Windows calls (launch.WindowsSystem), with kernel32 and advapi32 as stand-ins (FakeWindows):
    the 8.3 short name asked for (with the long-path prefix past MAX_PATH), a folder made in one step with an access
    list for this user alone, a folder that is this user's alone told from one that is not, and an access list set
    so. On Windows itself the same with Windows' own calls (test_windows_own_calls)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_the_calls_make_check_and_set_a_folder_of_this_users_alone(self):
        fake = FakeWindows(short="C:\\GAMES~1\\DMT3")
        system = launch.WindowsSystem(fake.kernel32, fake.advapi32, last_error=lambda: fake.error)
        self.assertEqual(system.short_name("C:\\Games\\테크니카"), "C:\\GAMES~1\\DMT3")
        self.assertEqual(fake.calls[-1], ("GetShortPathNameW", "C:\\Games\\테크니카"))
        # Past MAX_PATH: asked with the long-path prefix, which comes off the answer.
        fake.short = "\\\\?\\C:\\GAMES~1\\DMT3"
        self.assertEqual(system.short_name("C:\\" + "L" * 300), "C:\\GAMES~1\\DMT3")
        self.assertEqual(fake.calls[-1], ("GetShortPathNameW", "\\\\?\\C:\\" + "L" * 300))
        fake.short = None
        self.assertIsNone(system.short_name("C:\\Games"))
        # Made in one step with its access list: protected, full access for this user alone.
        folder = os.path.join(self.tmp, "openDMT3-%s" % ("0" * 16))
        system.make_folder(folder)
        self.assertIn(("ConvertStringSecurityDescriptorToSecurityDescriptorW", "D:P(A;OICI;FA;;;%s)" % fake.ME),
                      fake.calls)
        self.assertIn(("CreateDirectoryW", folder, 0x5000), fake.calls)
        with self.assertRaises(FileExistsError):
            system.make_folder(folder)
        # This user's alone: owned by this user, protected, one entry for this user.
        self.assertTrue(system.own(folder))
        for owner, access in ((FakeWindows.OTHER, None), (None, "D:AI(A;OICI;FA;;;%s)" % fake.ME),
                              (None, "D:PAI(A;OICI;FA;;;%s)(A;OICI;FA;;;WD)" % fake.ME),
                              (None, "D:PAI(A;OICI;FA;;;%s)" % FakeWindows.OTHER)):
            fake.owner, fake.access = owner or fake.ME, access or "D:PAI(A;OICI;FA;;;%s)" % fake.ME
            self.assertFalse(system.own(folder), (owner, access))
        # A folder of this user's set so: its access list protected, from the made-up descriptor's.
        fake.owner, fake.access = fake.ME, "D:AI(A;OICI;FA;;;WD)"
        self.assertTrue(system.make_own(folder))
        self.assertIn(("SetNamedSecurityInfoW", folder, launch.WindowsSystem.DACL | launch.WindowsSystem.PROTECTED,
                       0x3100), fake.calls)
        # Someone else's: left as it is.
        fake.calls.clear()
        fake.owner = FakeWindows.OTHER
        self.assertFalse(system.make_own(folder))
        self.assertFalse([c for c in fake.calls if c[0] == "SetNamedSecurityInfoW"])

    @unittest.skipUnless(os.name == "nt", "Windows' own calls")
    def test_windows_own_calls(self):
        system = launch.WindowsSystem()
        made = os.path.join(self.tmp, "made")
        system.make_folder(made)
        self.assertTrue(system.own(made))
        there = os.path.join(self.tmp, "there")
        os.mkdir(there)
        self.assertTrue(system.make_own(there))
        self.assertTrue(system.own(there))
        short = system.short_name(self.tmp)
        self.assertTrue(short and launch._leads_to(short, self.tmp), short)


if __name__ == "__main__":
    unittest.main()
