"""Tests for reading the game's files as the client reads them (core/game.py, core/formats/pak.py): a family's base and
numbered patches, the newest one that has a file winning; a patch whose first name has Korean letters read like any
other; a patch of another build (another table) left out and never called damaged; one cut short or overwritten called
damaged; names in any letter case; and what a client is, by content. Everything here is made up (FolderCase's random
table)."""

import os
import shutil
import unittest
from unittest import mock

from opendmt3.core import game as g
from opendmt3.core.formats import discstock, pak
from tests.core.test_setup import FolderCase
from tests.core.made_up_game import GameCase, NEWEST_SONGS, STAGE_LIST, song_list


class LayersTest(GameCase):

    def test_each_file_comes_from_the_newest_layer_that_has_it(self):
        with self.game.layers("DiscInfo") as layers:
            # Base, patch 00 and patch 01 opened, in that order.
            self.assertEqual([os.path.basename(p) for p, _ in layers.opened],
                             ["DiscInfo.pak", "DiscInfo00.pak", "DiscInfo01.pak"])
            # The song list of patch 01 (three songs), not the base's (two) nor patch 00's (one).
            self.assertEqual(layers.read(discstock.PATH), song_list(NEWEST_SONGS))
            # A file only the base has comes from the base.
            self.assertEqual(layers.read("Resource/DiscInfo/POP_STAGE_1.csv"), STAGE_LIST)
            self.assertIsNone(layers.read("Resource\\DiscInfo\\nothing.csv"))
        with self.game.layers("DiscImg") as layers:
            # The third song's jacket is only in patch 00, and found there.
            self.assertIsNotNone(layers.find("Resource\\DiscImg\\gamma_0.png"))
        with self.game.layers("Script") as layers:
            # Patch 02's experience table, the newest the reader can open.
            self.assertIn(b"1,10,10,10", layers.read("Resource\\Script\\Item\\ResultExpPoint.csv"))

    def test_a_patch_after_a_missing_number_is_never_read(self):
        # Measured: the client looks for name00.pak, name01.pak... and stops at the first it does not find.
        self._pak(os.path.join(self.pack, "DiscInfo03.pak"), {discstock.PATH: song_list(NEWEST_SONGS[:1])})
        game = g.Game.find(self.tmp)
        self.assertEqual([os.path.basename(p) for p in game.layer_paths("DiscInfo")],
                         ["DiscInfo.pak", "DiscInfo00.pak", "DiscInfo01.pak"])
        # Filled in, the gap no longer stops it.
        self._pak(os.path.join(self.pack, "DiscInfo02.pak"), {"Resource\\DiscInfo\\x.csv": b"x"})
        game = g.Game.find(self.tmp)
        self.assertEqual(len(game.layer_paths("DiscInfo")), 5)

    def test_a_layer_hidden_another_way_is_left_out_and_never_called_damaged(self):
        with self.game.layers("Script") as layers:
            self.assertEqual([os.path.basename(p) for p in layers.unread], ["Script01.pak"])
            self.assertEqual(layers.damaged, {})
            # Its newer table is not read: the newest one this reader opens is.
            self.assertNotIn(b"1,99", layers.read("Resource\\Script\\Item\\ResultExpPoint.csv"))
        # Opened alone it says so in its own kind of error, a PakError still (every caller already takes those).
        with self.assertRaises(pak.PakUnreadable):
            self.game.open_pak(self.game.pak_path("Script01"))

    def test_a_patch_whose_first_name_is_korean_is_read_like_any_other(self):
        # As in a whole game folder's newest script patch: a copy of a table under a Korean "copy of" name comes first.
        # The patch is opened, never left out, and the newer file it holds wins as any patch's does.
        newer = b"the newer made-up jacket"
        self._pak(os.path.join(self.pack, "DiscImg01.pak"), {"Resource\\DiscImg\\사본 - alpha_0.png": b"a copy",
                                                            "Resource\\DiscImg\\alpha_0.png": newer})
        game = g.Game.find(self.tmp)
        with game.layers("DiscImg") as layers:
            self.assertEqual((layers.unread, layers.damaged), ({}, {}))
            self.assertEqual([os.path.basename(p) for p, _ in layers.opened],
                             ["DiscImg.pak", "DiscImg00.pak", "DiscImg01.pak"])
            # The newest layer's picture, not the base's.
            self.assertEqual(layers.read("Resource\\DiscImg\\alpha_0.png"), newer)
            # The Korean name is a name like any other: found as written.
            self.assertIn("resource\\discimg\\사본 - alpha_0.png", layers.names())

    def test_a_layer_cut_short_or_overwritten_is_damaged(self):
        # Cut inside its last entry: the path reads, the data runs past the end of the file.
        self.cut("DiscInfo01.pak", -10)
        # Its header overwritten: not as the game wrote it.
        with open(os.path.join(self.pack, "DiscInfo00.pak"), "r+b") as f:
            f.seek(pak.HEADER_OFFSET + 4)
            f.write(b"\x00\x00\x00\x00")
        with self.game.layers("DiscInfo") as layers:
            self.assertEqual(sorted(os.path.basename(p) for p in layers.damaged), ["DiscInfo00.pak", "DiscInfo01.pak"])
            self.assertEqual(layers.unread, {})
        for name in ("DiscInfo00", "DiscInfo01"):
            with self.assertRaises(pak.PakError) as caught:
                self.game.open_pak(self.game.pak_path(name))
            self.assertNotIsInstance(caught.exception, pak.PakUnreadable)

    def test_an_entry_shorter_than_it_says_is_refused_not_handed_on(self):
        with self.game.layers("DiscImg") as layers:
            archive, entry = layers.find("Resource\\DiscImg\\alpha_0.png")
            # The entry says it holds more than its chunks give.
            entry.size += 100
            with self.assertRaises(pak.PakError):
                archive.read(entry)

    def test_a_family_with_no_file_at_all_is_a_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            self.game.layers("Nothing")

    def test_a_family_opened_together_reads_as_opened_one_at_a_time(self):
        # The family's files are opened on a few threads at once (core/parallel.py): the same files in the same order,
        # the same newest entries, the same left out, whatever the number of threads.
        from opendmt3.core import parallel
        seen = []
        for workers in (1, 2, 8):
            with mock.patch.object(parallel, "WORKERS", workers):
                for family in ("DiscInfo", "Script", "DiscImg"):
                    with self.game.layers(family) as layers:
                        seen.append((workers, family, [os.path.basename(p) for p, _ in layers.opened],
                                     sorted(layers.unread), sorted(layers.damaged),
                                     {name: entry.name for name, (_, entry) in layers.index.items()}))
        by_one = [row[1:] for row in seen if row[0] == 1]
        self.assertEqual([row[1:] for row in seen if row[0] == 2], by_one)
        self.assertEqual([row[1:] for row in seen if row[0] == 8], by_one)

    def test_a_file_of_the_family_that_cannot_be_read_closes_the_others(self):
        # As when they were opened one at a time: the first refusal in the family's order is raised, and every file
        # opened is closed again (a family read without one of its files would hide newer ones).
        opened, real = [], pak.Pak

        def opening(path, table):
            if path.endswith("00.pak"):
                raise PermissionError(13, "made-up refusal", path)
            archive = real(path, table)
            opened.append(archive)
            return archive

        with mock.patch.object(pak, "Pak", opening):
            with self.assertRaises(PermissionError) as caught:
                self.game.layers("DiscInfo")
        self.assertTrue(caught.exception.filename.endswith("DiscInfo00.pak"))
        self.assertEqual(len(opened), 2)
        self.assertTrue(all(archive.file.closed for archive in opened))

    def test_names_match_in_any_letter_case_as_on_windows(self):
        # The pack folder and the files renamed as a copy from another PC may have them.
        os.rename(self.pack, os.path.join(self.game.root, "PACK"))
        pack = os.path.join(self.game.root, "PACK")
        os.rename(os.path.join(pack, "DiscInfo01.pak"), os.path.join(pack, "DISCINFO01.PAK"))
        os.rename(os.path.join(pack, "Config.pak"), os.path.join(pack, "config.PAK"))
        game = g.Game.find(self.tmp)
        self.assertEqual(game.root, self.game.root)
        # As the folder spells it on Linux; on Windows, whose names have no letter case, the same file however spelt.
        self.assertTrue(os.path.normcase(game.pak_path("DiscInfo01")).endswith(
            os.path.normcase(os.path.join("PACK", "DISCINFO01.PAK"))))
        with game.layers("DiscInfo") as layers:
            self.assertEqual(layers.read(discstock.PATH), song_list(NEWEST_SONGS))


class ClientKindsTest(FolderCase):
    """What a client is, by content: Game.table() takes the table from the PC client as released, else the fixed one,
    else a modified PC client; the cabinet's client and programs without the table are said in their own words."""

    def setUp(self):
        super().setUp()
        # The table is looked for for real here, in made-up programs.
        self.patcher.stop()
        self.root = self.game.root
        os.remove(os.path.join(self.root, "Client.exe"))
        # Each program's made-up fingerprint and whether its read-only data holds the table.
        self.digests, self.holds = {}, set()
        digest = mock.patch.object(g, "sha256_file", lambda path: self.digests.get(os.path.basename(path), "other"))
        load = mock.patch.object(pak, "load_table", self.load_table)
        for patch in (digest, load):
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        # FolderCase stops its patcher; started again so its stop finds it running.
        self.patcher.start()
        super().tearDown()

    def load_table(self, path):
        if os.path.basename(path) not in self.holds:
            raise pak.PakError("the descriptor table was not found in %s" % path)
        return bytes(256)

    def program(self, name, size=2 << 20, digest="other", holds=False):
        """A made-up program (never run: no program bit is set on it) of this size and fingerprint."""
        with open(os.path.join(self.root, name), "wb") as f:
            f.truncate(size)
        self.digests[name] = digest
        if holds:
            self.holds.add(name)

    def test_the_original_comes_first_then_the_fixed_then_a_modified_one(self):
        self.program("Client.exe", digest=g.PC_BUILD, holds=True)
        self.program(g.FIXED_EXE, digest=g.PC_BUILD_DISPLAY_FIX, holds=True)
        self.program("Other.exe", holds=True)
        game = g.Game(self.root)
        game.table()
        self.assertEqual(game.client, (os.path.join(self.root, "Client.exe"), g.ORIGINAL))
        os.remove(os.path.join(self.root, "Client.exe"))
        game = g.Game(self.root)
        game.table()
        self.assertEqual(game.client[1], g.FIXED)
        os.remove(os.path.join(self.root, g.FIXED_EXE))
        game = g.Game(self.root)
        game.table()
        self.assertEqual(game.client, (os.path.join(self.root, "Other.exe"), g.MODIFIED))

    def test_a_modified_client_with_one_byte_changed_is_used_when_it_holds_the_table(self):
        self.program("Client.exe", holds=True)
        game = g.Game(self.root)
        self.assertEqual(game.table(), bytes(256))
        self.assertEqual(game.client[1], g.MODIFIED)

    def test_the_cabinets_client_alone_does_not_work_here(self):
        self.program("Client.exe", digest=g.CABINET_BUILD, holds=True)
        # A small tool beside it is never searched.
        self.program("ErrorReport.exe", size=6 << 10, holds=True)
        with self.assertRaises(g.GameError) as caught:
            g.Game(self.root).table()
        self.assertEqual(caught.exception.key, "error.game.cabinet_client")
        self.assertEqual(str(caught.exception), "The cabinet's client: does not work here, the PC client is needed.")

    def test_the_china_region_cabinets_client_is_no_modified_pc_client(self):
        # Known by the start of its fingerprint; its read-only data holds the table, as a modified PC client's does.
        china = g.CHINA_CABINET_BUILD + "0123456789abcdef" * 3
        self.program("Client.exe", digest=china, holds=True)
        with self.assertRaises(g.GameError) as caught:
            g.Game(self.root).table()
        self.assertEqual(caught.exception.key, "error.game.cabinet_client")
        self.assertEqual(g.Game(self.root).client_build("Client.exe"),
                         (china, "China-region cabinet build (needs the cabinet's USB lock; not supported)"))
        # Beside the PC client, the PC client is played.
        self.program("Other.exe", digest=g.PC_BUILD, holds=True)
        game = g.Game(self.root)
        game.table()
        self.assertEqual(game.client, (os.path.join(self.root, "Other.exe"), g.ORIGINAL))

    def test_a_fingerprint_is_known_by_its_whole_start_only(self):
        # One digit of the 16 off is another build: a modified PC client when it holds the table.
        other = g.CHINA_CABINET_BUILD[:15] + "0" + "0123456789abcdef" * 3
        self.assertFalse(g.is_cabinet_build(other))
        self.assertEqual(g.build_name(other), "unknown build")
        self.assertTrue(g.is_cabinet_build(g.CABINET_BUILD) and not g.is_cabinet_build(g.PC_BUILD))
        self.assertFalse(g.is_cabinet_build(None) or g.is_cabinet_build(""))
        self.program("Client.exe", digest=other, holds=True)
        game = g.Game(self.root)
        game.table()
        self.assertEqual(game.client[1], g.MODIFIED)

    def test_a_client_without_the_table_cannot_open_the_games_files(self):
        self.program("Client.exe")
        with self.assertRaises(g.GameError) as caught:
            g.Game(self.root).table()
        self.assertEqual(caught.exception.key, "error.game.no_table")


class TableSearchTest(unittest.TestCase):
    def test_a_section_table_claiming_more_than_the_file_is_searched_only_as_far_as_the_file(self):
        import tempfile
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        # A program whose one section says it is 4 GB long: the search stops at the end of the file at once.
        data = bytearray(4096)
        data[0x3C:0x40] = (0x80).to_bytes(4, "little")
        data[0x86:0x88] = (1).to_bytes(2, "little")
        table = 0x80 + 24
        data[table:table + 8] = b".rdata\x00\x00"
        data[table + 16:table + 20] = (0xFFFFFFF0).to_bytes(4, "little")
        data[table + 20:table + 24] = (0x200).to_bytes(4, "little")
        path = os.path.join(folder, "made-up.bin")
        with open(path, "wb") as f:
            f.write(data)
        with self.assertRaises(pak.PakError):
            pak.load_table(path)


if __name__ == "__main__":
    unittest.main()
