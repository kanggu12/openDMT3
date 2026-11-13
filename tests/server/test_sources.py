"""Tests for what a path on the server PC is and the song list read from any form of it (services/sources.py): a game
folder at any depth, one file of it, an archive holding one (zip by Python's own reader; 7z, split, with a password and
inside another archive by 7-Zip, when this PC has one), a song list openDMT3 saved, and what holds no game; each said
in one plain line, an archive's entries judged before anything is unpacked and only what the server needs taken out.

Everything is made up (tests/core/made_up_game.py). The 7-Zip used is the one the server would use (sources.seven_zip:
OPENDMT3_7ZIP, else 7zz, 7z or 7za on PATH); without one those tests are skipped and say why. RAR archives cannot be
made without the rar program, which is not free software: their test is skipped without it."""

import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from unittest import mock

from opendmt3.core import game as g
from opendmt3.core.formats import pak
from opendmt3.server.services import catalog, pictures, songlist, sources
from tests.core.made_up_game import GameCase

SEVEN_ZIP = sources.seven_zip()
# A stand-in for 7-Zip, run by this Python on every system: it keeps its arguments, what came on its standard input and
# whether it leads a session of its own beside RECORD; told to extract (x), it writes the first name of its -i@ list
# into its -o folder without end, a megabyte every 2 ms up to 512 MB, keeping the count as it goes.
STAND_IN = r'''
import os, sys, time
record = os.environ["STAND_IN_RECORD"]
args = sys.argv[1:]
# One argument a line, each ended by \n alone as seen() splits them (Windows' text mode would write \r\n).
with open(record + ".args", "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join(args))
with open(record + ".stdin", "wb") as f:
    f.write(sys.stdin.buffer.read())
with open(record + ".session", "w") as f:
    f.write(str(hasattr(os, "getsid") and os.getsid(0) == os.getpid()))
if args[0] == "l" and os.environ.get("STAND_IN_LISTING"):
    # A listing as 7-Zip's -slt gives it, made up by the test.
    with open(os.environ["STAND_IN_LISTING"], encoding="utf-8") as f:
        sys.stdout.write(f.read())
if args[0] == "x":
    out = next(a[2:] for a in args if a.startswith("-o"))
    # Its list by -i@ (or, as an older openDMT3 gave it, by @ after the archive).
    lists = [a[3:] for a in args if a.startswith("-i@")] + [a[1:] for a in args if a.startswith("@")]
    with open(lists[0], encoding="utf-8") as f:
        first = f.readline().rstrip("\n")
    target = os.path.join(out, *first.split("/"))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    written = 0
    with open(target, "wb") as f:
        while written < 512 << 20:
            f.write(bytes(1 << 20))
            f.flush()
            written += 1 << 20
            # Moved into place whole: killed at any moment, the count read after is a whole number.
            with open(record + ".written.new", "w") as w:
                w.write(str(written))
            os.replace(record + ".written.new", record + ".written")
            time.sleep(0.002)
'''


# The listing the stand-in gives for a game folder in an archive whose sizes it does not keep to: each file 1000 bytes.
LYING_LISTING = "".join("Path = TECHNIKA 3/%s\nSize = 1000\nAttributes = A -rw-r--r--\n\n" % name
                        for name in ("Client.exe", "pack/Config.pak", "pack/DiscInfo.pak"))


def stand_in(case, listing=None):
    """The stand-in 7-Zip for a test (STAND_IN), in its own folder: patches that run it in place of 7-Zip (the
    switches and the rest as sources.py builds them), and where it keeps what it saw. `listing`: what it lists."""
    import sys
    folder = os.path.join(case.tmp, "stand-in")
    os.makedirs(folder, exist_ok=True)
    script = os.path.join(folder, "seven.py")
    with open(script, "w", encoding="utf-8") as f:
        # On POSIX a program of its own, started as 7-Zip is (OPENDMT3_7ZIP names it); on Windows run by this Python.
        f.write(("#!%s\n" % sys.executable if os.name == "posix" else "") + STAND_IN)
    os.chmod(script, 0o755)
    record = os.path.join(folder, "record")
    environment = {"STAND_IN_RECORD": record, sources.SEVEN_ZIP_ENV: script}
    if listing is not None:
        environment["STAND_IN_LISTING"] = os.path.join(folder, "listing.txt")
        with open(environment["STAND_IN_LISTING"], "w", encoding="utf-8") as f:
            f.write(listing)
    patches = [mock.patch.dict(os.environ, environment)]
    if os.name != "posix":
        # Windows starts no script by itself: this Python runs it, with the switches and the rest as sources.py has
        # them.
        real = sources.seven_zip_command
        patches.append(mock.patch.object(sources, "seven_zip_command",
                                         lambda args, switches=(): [sys.executable, script] + real(args, switches)[1:]))
    for patch in patches:
        patch.start()
        case.addCleanup(patch.stop)
    return record


def seven_z(path):
    """A file that starts as a 7z archive does (all 7-Zip's to judge): what the stand-in 7-Zip is asked to open."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"7z\xbc\xaf\x27\x1c" + bytes(26))
    return path


def twice_zip(path, second):
    """A zip of a game folder's three telling entries (a program, the settings' file, the song list's file), and
    `second`, one more entry of the song list's file under the same name or one differing in letter case (None:
    none), as the security review's proof 5 made it."""
    import warnings
    with warnings.catch_warnings():
        # Python's zip writer warns of a name twice; the archive is made so on purpose.
        warnings.simplefilter("ignore")
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("g/Client.exe", b"MZ made up")
            z.writestr("g/pack/Config.pak", b"made up")
            z.writestr("g/pack/DiscInfo.pak", b"made up")
            if second:
                z.writestr(second, b"made up again")
    return path


def lying_gzip(path, real=8 << 20, said=1000):
    """A gzip of `real` zero bytes whose last bytes say `said` (its check of the real bytes kept, so only the size
    lies), as the security review's proof made it."""
    import struct
    import zlib as z
    packer = z.compressobj(9, z.DEFLATED, -15)
    with open(path, "wb") as f:
        f.write(b"\x1f\x8b\x08\x00" + bytes(4) + b"\x02\xff")
        f.write(packer.compress(bytes(real)))
        f.write(packer.flush())
        f.write(struct.pack("<II", z.crc32(bytes(real)) & 0xFFFFFFFF, said))
    return path


def seen(record, what):
    """What the stand-in kept: its arguments (a list), its standard input (bytes), whether it led a session of its own,
    or how many bytes it wrote."""
    with open(record + "." + what, "rb") as f:
        data = f.read()
    if what == "args":
        return data.decode("utf-8").split("\n")
    if what == "written":
        return int(data)
    return data if what == "stdin" else data.decode() == "True"


def files_in(folder):
    """Every file below a folder, as paths relative to it with forward slashes."""
    out = []
    for here, _, names in os.walk(folder):
        out += [os.path.relpath(os.path.join(here, n), folder).replace(os.sep, "/") for n in names]
    return sorted(out)


@unittest.skipUnless(pictures.available(), "needs Pillow")
class FormsTest(GameCase):

    def setUp(self):
        super().setUp()
        # What reading the folder itself gives, to compare every other form with.
        self.direct = os.path.join(self.tmp, "direct")
        catalog.read(self.tmp, self.direct)
        # Files of the game folder no server needs, which an archive of it holds too.
        with open(os.path.join(self.pack, "movie1.pak"), "wb") as f:
            f.write(b"\x00" * 4096)

    def tearDown(self):
        if getattr(self, "table_taken", False):
            self.patcher.start()
        super().tearDown()

    def same_as_the_folder(self, data):
        """The song list, the jackets and the DJ cards read into data are the folder's own, byte for byte."""
        for name in (catalog.FILE, "cards.json"):
            with open(os.path.join(data, name), "rb") as a, open(os.path.join(self.direct, name), "rb") as b:
                self.assertEqual(a.read(), b.read(), name)
        self.assertEqual(files_in(os.path.join(data, catalog.JACKETS)), files_in(os.path.join(self.direct, catalog.JACKETS)))
        # Nothing of the reading's own (an archive's files taken out) is left in the data folder.
        self.assertEqual([n for n in os.listdir(data) if n.startswith(catalog.STAGING)], [])

    def zip_of_the_game(self, path, inside="TECHNIKA 3/drive d/DMT3/", extra=()):
        """A zip of the whole game folder under `inside`, as a copy from a cabinet's drives would be packed."""
        with zipfile.ZipFile(path, "w") as z:
            for name in files_in(self.game.root):
                z.write(os.path.join(self.game.root, name), inside + name)
            for entry, data in extra:
                z.writestr(entry, data)
        return path

    # ------------------------------------------------------------------------------------------- folders and files

    def test_a_game_folder_below_the_path_says_what_it_holds(self):
        found = sources.look(self.tmp)
        self.assertEqual((found["kind"], found["ready"], found["path"]), ("folder", True, self.game.root))
        self.assertEqual(found["line"], "Client data in a folder, original PC client, 3 songs: ready")
        self.assertEqual(sources.folder_line("modified", 3, "ko"), "폴더 안의 클라이언트 데이터, 수정된 PC 클라이언트, 곡 3개: 쓸 수 있음")
        report = sources.read(self.tmp, os.path.join(self.tmp, "data"))
        self.assertEqual((report["from"], report["path"]), ("folder", self.game.root))

    def test_one_file_of_a_game_folder_is_the_folder_around_it(self):
        found = sources.look(os.path.join(self.pack, "DiscInfo.pak"))
        self.assertEqual((found["kind"], found["ready"], found["path"]), ("folder", True, self.game.root))
        # One of the game's files alone, outside any game folder.
        alone = os.path.join(self.tmp, "DiscInfo.pak")
        shutil.copy(os.path.join(self.pack, "DiscInfo.pak"), alone)
        found = sources.look(alone)
        self.assertEqual((found["ready"], found["key"]), (False, "error.source.part"))
        self.assertEqual(found["line"], "This is part of the client data. Choose the folder that holds all of it.")

    def test_what_holds_no_game_is_said_so(self):
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        text = os.path.join(self.tmp, "notes.txt")
        with open(text, "w") as f:
            f.write("made up")
        for path in (empty, text, os.path.join(self.tmp, "nothing here")):
            with self.subTest(path=os.path.basename(path)):
                found = sources.look(path)
                self.assertEqual((found["ready"], found["key"]), (False, "error.source.nothing"))
                self.assertEqual(found["line"], "This is not a folder or an archive holding client data.")
                with self.assertRaises(sources.SourceError):
                    sources.read(path, os.path.join(self.tmp, "data"))

    def test_a_damaged_song_list_is_said_with_the_thing_to_do(self):
        self.cut("DiscInfo01.pak", -10)
        found = sources.look(self.tmp)
        self.assertEqual((found["ready"], found["key"]), (False, "error.game.damaged.songs"))
        self.assertEqual(found["line"], "The file with the song list is damaged. Copy the client data again, or unpack "
                                        "the archive again.")

    # ------------------------------------------------------------------------------------------- clients

    def clients(self, digest, holds):
        """The folder's client made up: its fingerprint and whether its read-only data holds the table. The made-up
        table FolderCase gives every game folder is taken away for it (and given back before FolderCase's own
        tearDown takes it away for good: a cleanup would give it back after, for every test to come)."""
        self.patcher.stop()
        self.table_taken = True
        with open(os.path.join(self.game.root, "Client.exe"), "wb") as f:
            f.truncate(2 << 20)
        for patch in (mock.patch.object(g, "sha256_file", lambda path: digest),
                      mock.patch.object(pak, "load_table", lambda path: self.table if holds else self.no_table(path))):
            patch.start()
            self.addCleanup(patch.stop)

    def no_table(self, path):
        raise pak.PakError("the descriptor table was not found in %s" % path)

    def test_a_modified_pc_client_is_used(self):
        self.clients("another build", holds=True)
        found = sources.look(self.tmp)
        self.assertEqual(found["line"], "Client data in a folder, modified PC client, 3 songs: ready")

    def test_the_cabinets_client_does_not_work_here(self):
        self.clients(g.CABINET_BUILD, holds=False)
        found = sources.look(self.tmp)
        self.assertEqual((found["ready"], found["key"]), (False, "error.game.cabinet_client"))
        self.assertEqual(found["line"], "The cabinet's client: does not work here, the PC client is needed.")

    def test_the_china_region_cabinets_client_does_not_work_here_though_it_holds_the_table(self):
        self.clients(g.CHINA_CABINET_BUILD + "0123456789abcdef" * 3, holds=True)
        found = sources.look(self.tmp)
        self.assertEqual((found["ready"], found["key"]), (False, "error.game.cabinet_client"))
        self.assertEqual(found["line"], "The cabinet's client: does not work here, the PC client is needed.")

    def test_a_client_without_the_table_is_said_so(self):
        self.clients("another build", holds=False)
        found = sources.look(self.tmp)
        self.assertEqual(found["line"], "The game's files cannot be opened with this client.")

    # ------------------------------------------------------------------------------------------- zip archives

    def test_a_zip_holding_the_game_takes_out_only_what_the_server_needs(self):
        path = self.zip_of_the_game(os.path.join(self.tmp, "technika-copy.zip"))
        found = sources.look(path)
        self.assertEqual((found["kind"], found["ready"], found["inside"]), ("archive", True, "TECHNIKA 3/drive d/DMT3/"))
        self.assertEqual(found["line"], "Client data in an archive: ready")
        taken = []
        real = sources.extract

        def spy(archive, take, dest, password=None, most=sources.NEEDED_MOST):
            taken.extend(e.name.rsplit("/", 1)[-1] for e in take)
            return real(archive, take, dest, password, most)

        data = os.path.join(self.tmp, "data")
        with mock.patch.object(sources, "extract", spy):
            report = sources.read(path, data)
        self.same_as_the_folder(data)
        self.assertEqual((report["from"], report["path"], report["inside"], report["folder"]),
                         ("archive", path, "TECHNIKA 3/drive d/DMT3/", None))
        # The client and the families the server reads, nothing else of the game (no video, no operator data).
        self.assertEqual(sorted(taken), sorted([
            "Client.exe", "Config.pak", "DiscInfo.pak", "DiscInfo00.pak", "DiscInfo01.pak", "DiscImg.pak",
            "DiscImg00.pak", "Script.pak", "Script00.pak", "Script01.pak", "Icon.pak", "emblem.pak"]))

    def test_an_entry_the_server_needs_that_is_not_safe_is_refused(self):
        for name, attributes in (("TECHNIKA 3/drive d/DMT3/CON.exe", 0o100644), ("TECHNIKA 3/drive d/DMT3/a:b.exe", 0o100644),
                                 ("TECHNIKA 3/drive d/DMT3/pack/Icon00.pak", 0o120777)):
            with self.subTest(name=name):
                entry = zipfile.ZipInfo(name)
                entry.external_attr = attributes << 16
                path = self.zip_of_the_game(os.path.join(self.tmp, "unsafe.zip"), extra=[(entry, b"x")])
                found = sources.look(path)
                self.assertEqual((found["ready"], found["key"]), (False, "error.source.entry"))
                self.assertEqual(found["line"], "An entry in this archive cannot be taken: %s" % name)
                data = os.path.join(self.tmp, "data")
                with self.assertRaises(sources.SourceError):
                    sources.read(path, data)
                self.assertFalse(os.path.exists(os.path.join(data, catalog.FILE)))

    def test_an_entry_the_server_does_not_need_is_never_taken_out(self):
        # A path that leaves the folder, beside the game: left where it is, never written.
        path = self.zip_of_the_game(os.path.join(self.tmp, "beside.zip"), extra=[("../../outside.txt", b"x")])
        sources.read(path, os.path.join(self.tmp, "data"))
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.tmp), "outside.txt")))

    def test_a_damaged_archive_says_download_it_again(self):
        path = self.zip_of_the_game(os.path.join(self.tmp, "cut.zip"))
        with open(path, "rb") as f:
            data = f.read()
        with open(path, "wb") as f:
            f.write(data[:len(data) // 2])
        found = sources.look(path)
        self.assertEqual(found["line"], "This archive is damaged or not fully downloaded. Download it again.")

    def test_an_archive_inside_an_archive_is_opened_two_levels_deep_and_no_further(self):
        inner = self.zip_of_the_game(os.path.join(self.tmp, "inner.zip"))
        outer = os.path.join(self.tmp, "outer.zip")
        with zipfile.ZipFile(outer, "w") as z:
            z.write(inner, "download/game.zip")
        found = sources.look(outer)
        self.assertEqual((found["ready"], found["line"]), (True, "It holds another archive. Both are opened."))
        data = os.path.join(self.tmp, "data")
        report = sources.read(outer, data)
        self.assertEqual(report["from"], "archive")
        self.same_as_the_folder(data)
        deeper = os.path.join(self.tmp, "deeper.zip")
        with zipfile.ZipFile(deeper, "w") as z:
            z.write(outer, "outer.zip")
        with self.assertRaises(sources.SourceError) as caught:
            sources.read(deeper, os.path.join(self.tmp, "data3"))
        self.assertEqual(caught.exception.key, "error.source.nothing")

    def test_a_song_list_is_known_by_its_content_and_taken(self):
        path = os.path.join(self.tmp, "anything.zip")
        sources.save(self.tmp, path)
        found = sources.look(path)
        self.assertEqual((found["kind"], found["line"]), ("song list", "Song list saved by openDMT3, 3 songs: ready"))
        data = os.path.join(self.tmp, "data")
        self.assertEqual(sources.read(path, data)["from"], "file")
        self.same_as_the_folder(data)

    def test_a_song_list_is_saved_from_an_archive_too(self):
        path = self.zip_of_the_game(os.path.join(self.tmp, "technika.zip"))
        out = os.path.join(self.tmp, songlist.NAME)
        manifest, report = sources.save(path, out)
        self.assertEqual((manifest["songs"], report["from"]), (3, "archive"))
        # Nothing of the reading's own is left beside the file.
        self.assertEqual([n for n in os.listdir(self.tmp) if n.startswith(catalog.STAGING)], [])

    # ------------------------------------------------------------------------------------------- 7-Zip

    def seven(self, *args, cwd=None):
        subprocess.run([SEVEN_ZIP, "a", "-bso0", "-bsp0"] + list(args), check=True, cwd=cwd or self.tmp,
                       stdin=subprocess.DEVNULL)

    def game_copy(self):
        """The game folder copied under a name an archive of a cabinet's drives would have, to pack with 7-Zip, with a
        file of the game's no server needs that does not compress (so a split archive has several parts)."""
        top = os.path.join(self.tmp, "pack-me")
        folder = os.path.join(top, "TECHNIKA 3", "drive d", "DMT3")
        shutil.copytree(self.game.root, folder)
        with open(os.path.join(folder, "pack", "movie2.pak"), "wb") as f:
            f.write(os.urandom(64 * 1024))
        return top

    @unittest.skipUnless(SEVEN_ZIP, "needs 7-Zip (OPENDMT3_7ZIP, or 7zz, 7z or 7za on PATH)")
    def test_a_7z_archive_is_read_through_7zip(self):
        top = self.game_copy()
        self.seven(os.path.join(self.tmp, "game.7z"), "TECHNIKA 3", cwd=top)
        data = os.path.join(self.tmp, "data")
        report = sources.read(os.path.join(self.tmp, "game.7z"), data)
        self.assertEqual((report["from"], report["inside"]), ("archive", "TECHNIKA 3/drive d/DMT3/"))
        self.same_as_the_folder(data)

    @unittest.skipUnless(SEVEN_ZIP, "needs 7-Zip (OPENDMT3_7ZIP, or 7zz, 7z or 7za on PATH)")
    def test_a_split_archive_by_its_first_part_and_a_missing_part_named(self):
        top = self.game_copy()
        os.makedirs(os.path.join(self.tmp, "split"))
        self.seven("-v24k", os.path.join(self.tmp, "split", "game.7z"), "TECHNIKA 3", cwd=top)
        # Several parts, the case tried.
        self.assertGreaterEqual(len(os.listdir(os.path.join(self.tmp, "split"))), 3)
        first = os.path.join(self.tmp, "split", "game.7z.001")
        data = os.path.join(self.tmp, "data")
        sources.read(first, data)
        self.same_as_the_folder(data)
        # A later part chosen: the first is asked for.
        found = sources.look(os.path.join(self.tmp, "split", "game.7z.002"))
        self.assertEqual(found["line"], "This is part 2 of a split archive. Put every part in one folder and choose "
                                        "the first.")
        os.remove(os.path.join(self.tmp, "split", "game.7z.002"))
        found = sources.look(first)
        self.assertEqual(found["line"], "Part 2 of this split archive is missing. Put every part in one folder.")
        with self.assertRaises(sources.SourceError) as caught:
            sources.read(first, os.path.join(self.tmp, "data2"))
        self.assertEqual(caught.exception.key, "error.source.missing_part")

    @unittest.skipUnless(SEVEN_ZIP, "needs 7-Zip (OPENDMT3_7ZIP, or 7zz, 7z or 7za on PATH)")
    def test_an_archive_with_a_password_asks_for_it(self):
        top = self.game_copy()
        for name, extra in (("files.7z", []), ("names.7z", ["-mhe=on"])):
            with self.subTest(name=name):
                path = os.path.join(self.tmp, name)
                self.seven("-pmade-up", *extra, path, "TECHNIKA 3", cwd=top)
                found = sources.look(path)
                self.assertEqual((found["ready"], found["line"]), (False, "This archive has a password. Enter it."))
                with self.assertRaises(sources.SourceError) as caught:
                    sources.read(path, os.path.join(self.tmp, "data"), password="wrong")
                self.assertEqual(caught.exception.key, "error.source.wrong_password")
                data = os.path.join(self.tmp, "data-" + name)
                sources.read(path, data, password="made-up")
                self.same_as_the_folder(data)

    @unittest.skipUnless(SEVEN_ZIP and shutil.which("rar"), "needs 7-Zip and the rar program to make a RAR archive")
    def test_a_rar_archive_is_read_through_7zip(self):
        top = self.game_copy()
        subprocess.run(["rar", "a", "-r", "-idq", os.path.join(self.tmp, "game.rar"), "TECHNIKA 3"], check=True, cwd=top)
        data = os.path.join(self.tmp, "data")
        sources.read(os.path.join(self.tmp, "game.rar"), data)
        self.same_as_the_folder(data)

    # ------------------------------------------------------------------------------------------- the server PC

    def test_the_server_pc_is_looked_through_for_the_games_files(self):
        place = os.path.join(self.tmp, "Downloads")
        os.makedirs(place)
        shutil.copytree(self.game.root, os.path.join(place, "copy", "game"))
        self.zip_of_the_game(os.path.join(place, "djmax-technika.zip"))
        sources.save(self.tmp, os.path.join(place, songlist.NAME))
        # Archives without a game word are other people's downloads: not opened.
        with zipfile.ZipFile(os.path.join(place, "holiday.zip"), "w") as z:
            z.writestr("photo.txt", "made up")
        found = sources.found([place])
        self.assertEqual(sorted(item["kind"] for item in found), ["archive", "folder", "song list"])
        self.assertTrue(all(item["ready"] for item in found))
        listed = sources.folders(place)
        self.assertEqual((listed["path"], listed["up"], listed["folders"]), (place, self.tmp, ["copy"]))
        with self.assertRaises(sources.SourceError):
            sources.folders(os.path.join(place, "none"))


class SevenZipRunsTest(unittest.TestCase):
    """7-Zip as the reading runs it: the password on its standard input, never on its command line; every name after
    "--" or in a list file, so none is read as a switch; and what it writes held to what the entries said (the
    security review's proofs 1, 3 and 8, made up here)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_the_password_goes_on_7zips_standard_input_never_on_its_command_line(self):
        record = stand_in(self)
        archive = seven_z(os.path.join(self.tmp, "technika.7z"))
        sources.listing(archive, "made-up-pass-1234")
        # Nowhere on the command line another user of the PC could read while it runs.
        self.assertFalse([a for a in seen(record, "args") if "made-up-pass-1234" in a], seen(record, "args"))
        self.assertEqual(seen(record, "stdin"), b"made-up-pass-1234\n")
        # The archive's name after "--", every switch before it.
        args = seen(record, "args")
        self.assertEqual(args[-2:], ["--", archive])
        self.assertIn("-sccUTF-8", args[:-2])
        if os.name == "posix":
            # A session of its own: a distribution's p7zip, which asks a terminal it finds, reads the pipe instead.
            self.assertTrue(seen(record, "session"))
        # No password given: a line no archive has, so 7-Zip says "wrong password" instead of waiting.
        sources.listing(archive)
        self.assertRegex(seen(record, "stdin"), rb"^none-[0-9a-f]{24}\n$")
        # A password with a line break fits on no line: refused as not the archive's, 7-Zip never started for it.
        with self.assertRaises(sources.SourceError) as caught:
            sources.listing(archive, "made-up\nsecond line")
        self.assertEqual(caught.exception.key, "error.source.wrong_password")

    def test_7zip_is_stopped_once_it_writes_more_than_the_entries_said(self):
        # An archive whose listing says 1000 bytes a file while 7-Zip writes on without end: stopped near the 1000
        # bytes and the margin, the reading's own folder removed, nothing in the data folder.
        record = stand_in(self, LYING_LISTING)
        archive = seven_z(os.path.join(self.tmp, "technika.7z"))
        data = os.path.join(self.tmp, "data")
        with self.assertRaises(sources.SourceError) as caught:
            sources.read(archive, data)
        self.assertEqual(caught.exception.key, "error.source.damaged")
        self.assertLess(seen(record, "written"), 64 << 20)
        self.assertEqual(os.listdir(data), [])

    def writer(self, folder):
        """A child process that does what the test says on its standard input, a line each, and answers each with a
        line once done: "say N" writes N bytes on its error output (nothing reads them), "write NAME N" writes N bytes
        into a file of the folder, "end" ends it."""
        import sys
        code = ("import os, sys\n"
                "for line in sys.stdin:\n"
                "    words = line.split()\n"
                "    if words[0] == 'say':\n"
                "        sys.stderr.buffer.write(bytes(int(words[1]))); sys.stderr.buffer.flush()\n"
                "    elif words[0] == 'write':\n"
                "        with open(os.path.join(sys.argv[1], words[1]), 'wb') as f:\n"
                "            f.write(bytes(int(words[2])))\n"
                "    else:\n"
                "        break\n"
                "    print('done', flush=True)\n")
        child = subprocess.Popen([sys.executable, "-c", code, folder], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True)

        def end():
            # Ended and waited for, its pipes closed, whatever the test did.
            child.kill()
            child.wait()
            child.stdin.close()
            child.stdout.close()
        self.addCleanup(end)

        def tell(line):
            child.stdin.write(line + "\n")
            child.stdin.flush()
            self.assertEqual(child.stdout.readline().strip(), "done")
        return child, tell

    def test_the_watch_reads_what_7zip_itself_wrote_whatever_others_do_to_the_disk(self):
        folder = os.path.join(self.tmp, "out")
        os.makedirs(folder)
        child, tell = self.writer(folder)
        if sources._wrote(child) is None:
            self.skipTest("this system keeps no count of a process's written bytes")
        measured = []
        real = sources._written

        def counted(path):
            measured.append(path)
            return real(path)
        # The disk's free room is never asked: another program deleting files on the same disk made it grow while
        # 7-Zip wrote, and the look that read it let 7-Zip write on for up to a second.
        with mock.patch.object(sources, "_written", counted), \
                mock.patch.object(shutil, "disk_usage", side_effect=AssertionError("the disk's free room was asked")):
            watch = sources.Watch(folder, 1000)
            watch.follow(child)
            # The first look measures the folder (nothing in it); the next ones read the process's count alone.
            self.assertFalse(watch.over())
            self.assertFalse(watch.over())
            self.assertEqual(len(measured), 1)
            # 3 MB said on its output and 500 bytes written: the folder measured once more (the count passed the
            # bound), found within it, and what it said counted out from then on.
            tell("say %d" % (3 << 20))
            tell("write Client.exe 500")
            self.assertFalse(watch.over())
            self.assertEqual(len(measured), 2)
            self.assertFalse(watch.over())
            self.assertEqual(len(measured), 2)
            # 4 MB where the entries said 1000 bytes: over at the very next look, not a second later.
            tell("write Config.pak %d" % (4 << 20))
            self.assertTrue(watch.over())

    def test_the_systems_count_is_what_the_child_wrote(self):
        folder = os.path.join(self.tmp, "out")
        os.makedirs(folder)
        child, tell = self.writer(folder)
        before = sources._wrote(child)
        if before is None:
            self.skipTest("this system keeps no count of a process's written bytes")
        tell("write one.bin %d" % (1 << 20))
        tell("write two.bin %d" % (2 << 20))
        wrote = sources._wrote(child) - before
        # The files' three megabytes and its few answers, nothing of what others write.
        self.assertGreaterEqual(wrote, 3 << 20)
        self.assertLess(wrote, (3 << 20) + 4096)

    def test_the_folder_is_measured_at_every_look_where_there_is_no_count(self):
        folder = os.path.join(self.tmp, "out")
        os.makedirs(folder)
        child, tell = self.writer(folder)
        with mock.patch.object(sources, "_wrote", lambda process: None):
            watch = sources.Watch(folder, 1000)
            watch.follow(child)
            self.assertFalse(watch.over())
            tell("write Client.exe %d" % (4 << 20))
            self.assertTrue(watch.over())
        # Before 7-Zip runs (no process yet) the same: what the folder holds, against the entries and the margin.
        self.assertTrue(sources.Watch(folder, 1000).over())
        self.assertFalse(sources.Watch(folder, 8 << 20).over())

    def test_a_length_set_without_a_write_is_found_at_the_next_measuring(self):
        # What the count does not see (a file made longer without a byte written) is found when the folder is
        # measured again, every MEASURE_EVERY seconds whatever the count says.
        import time
        folder = os.path.join(self.tmp, "out")
        os.makedirs(folder)
        child, tell = self.writer(folder)
        if sources._wrote(child) is None:
            self.skipTest("this system keeps no count of a process's written bytes")
        with mock.patch.object(sources, "MEASURE_EVERY", 0.2):
            watch = sources.Watch(folder, 1000)
            watch.follow(child)
            tell("write Client.exe 500")
            self.assertFalse(watch.over())
            os.truncate(os.path.join(folder, "Client.exe"), 4 << 20)
            self.assertFalse(watch.over())
            time.sleep(0.25)
            self.assertTrue(watch.over())

    def test_a_stream_that_says_its_size_at_its_end_is_refused_before_it_is_unpacked(self):
        import lzma
        gz = lying_gzip(os.path.join(self.tmp, "technika.zip.gz"))
        xz = os.path.join(self.tmp, "technika.7z.xz")
        with open(xz, "wb") as f:
            f.write(lzma.compress(bytes(1 << 20), format=lzma.FORMAT_XZ))
        data = os.path.join(self.tmp, "data")
        for path in (gz, xz):
            with self.subTest(path=os.path.basename(path)):
                # Known by its content whatever 7-Zip this PC has, or none.
                found = sources.look(path)
                self.assertEqual((found["kind"], found["ready"], found["key"]), ("archive", False, "error.source.stream"))
                self.assertEqual(found["line"], "This archive says its size only at its end, where it cannot be "
                                                "checked first. Unpack it with another program, then choose what "
                                                "came out.")
                with self.assertRaises(sources.SourceError) as caught:
                    sources.read(path, data)
                self.assertEqual(caught.exception.key, "error.source.stream")
                self.assertEqual(os.listdir(data), [])

    def test_an_entry_without_a_size_is_never_taken_out(self):
        listed = sources._parse_listing("Path = TECHNIKA 3/Client.exe\nSize = \n\n"
                                        "Path = TECHNIKA 3/pack/Config.pak\nSize = 8192\n\n"
                                        "Path = TECHNIKA 3/pack/DiscInfo.pak\nSize = 8192\n\n")
        self.assertEqual([e.size for e in listed], [None, 8192, 8192])
        with self.assertRaises(sources.SourceError) as caught:
            sources.needed(listed, "TECHNIKA 3/")
        self.assertEqual((caught.exception.key, caught.exception.params), ("error.source.entry",
                                                                           {"name": "TECHNIKA 3/Client.exe"}))
        with self.assertRaises(sources.SourceError):
            sources.extract(os.path.join(self.tmp, "technika.7z"), listed[:1], self.tmp)

    def test_an_archive_with_a_name_twice_is_refused_in_its_line(self):
        # The same needed name twice, or two names that differ only in letter case (one file on Windows): refused with
        # the entry's line before anything is taken out, never a bare error with a path of the server's.
        data = os.path.join(self.tmp, "data")
        for second in ("g/pack/DiscInfo.pak", "g/pack/discinfo.PAK"):
            with self.subTest(second=second):
                archive = twice_zip(os.path.join(self.tmp, "technika.zip"), second)
                found = sources.look(archive)
                self.assertEqual((found["ready"], found["key"], found["values"]),
                                 (False, "error.source.entry", {"name": second}))
                with self.assertRaises(sources.SourceError) as caught:
                    sources.read(archive, data)
                self.assertEqual(str(caught.exception), "An entry in this archive cannot be taken: %s" % second)
                self.assertEqual(os.listdir(data), [])

    def test_anything_that_goes_wrong_while_taking_out_is_said_without_a_path(self):
        archive = twice_zip(os.path.join(self.tmp, "technika.zip"), None)
        failed = OSError(5, "Input/output error", os.path.join(self.tmp, "data", ".song-list-x", "Client.exe"))
        with mock.patch.object(sources.shutil, "copyfileobj", side_effect=failed):
            with self.assertRaises(sources.SourceError) as caught:
                sources.read(archive, os.path.join(self.tmp, "data"))
        self.assertEqual(caught.exception.key, "error.source.damaged")
        # An error the reading did not word says the system's words alone (the API passes it on to its caller).
        self.assertEqual(catalog.why(failed), "OSError: Input/output error")

    @unittest.skipUnless(SEVEN_ZIP, "needs 7-Zip (OPENDMT3_7ZIP, or 7zz, 7z or 7za on PATH)")
    def test_an_archive_whose_name_starts_with_a_dash_is_an_archive(self):
        top = os.path.join(self.tmp, "pack-me")
        os.makedirs(os.path.join(top, "TECHNIKA 3"))
        with open(os.path.join(top, "TECHNIKA 3", "readme.txt"), "w") as f:
            f.write("made up")
        archive = os.path.join(self.tmp, "-ssw technika.7z")
        subprocess.run([SEVEN_ZIP, "a", "-bso0", "-bsp0", "--", archive, "TECHNIKA 3"], check=True, cwd=top,
                       stdin=subprocess.DEVNULL)
        here = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, here)
        # By a name relative to the folder it is in, as a path typed on the server PC may be: never a switch.
        self.assertEqual([e.name for e in sources.listing("-ssw technika.7z") if not e.folder],
                         ["TECHNIKA 3/readme.txt"])


if __name__ == "__main__":
    unittest.main()
