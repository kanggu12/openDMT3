"""Tests for the song list saved into one file and taken in by a server (services/songlist.py): the same result as
reading the game folder it came from, byte for byte; and every refusal of a file that is not what openDMT3 saves (an
entry outside its names, a path outside, a link, a bomb, a broken picture, a table of another shape, a newer format, a
manifest that says more than the file holds), each in plain words with nothing in the server changed.

The game folder is made up (tests/core/made_up_game.py)."""

import hashlib
import io
import json
import os
import unittest
import warnings
import zipfile
from unittest import mock

from opendmt3.server.services import cards, catalog, pictures, songlist, sources
from tests.core.made_up_game import GameCase, png


def tree(folder):
    """{path in the folder: sha256} of every file in it, the reading's own leftovers (none expected) included."""
    out = {}
    for here, _, names in os.walk(folder):
        for name in names:
            path = os.path.join(here, name)
            with open(path, "rb") as f:
                out[os.path.relpath(path, folder)] = hashlib.sha256(f.read()).hexdigest()
    return out


def many(path, count, said=None):
    """A zip of one stored empty entry and `count` central directory records naming it, whose end records say `said`
    entries (`count` by default), with zip64's records past 65535: the security review's proof 7 made smaller."""
    import struct
    said = count if said is None else said
    name = b"a"
    local = struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 0, 0, 0, 0, 0, 0, len(name), 0) + name
    record = struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0, 0, 0, 0, 0, 0, 0, len(name), 0, 0, 0, 0, 0,
                         0) + name
    with open(path, "wb") as f:
        f.write(local)
        at = f.tell()
        f.write(record * count)
        size = f.tell() - at
        if said > 0xFFFF:
            z64 = f.tell()
            f.write(struct.pack("<IQHHIIQQQQ", 0x06064B50, 44, 45, 45, 0, 0, said, said, size, at))
            f.write(struct.pack("<IIQI", 0x07064B50, 0, z64, 1))
            f.write(struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0))
        else:
            f.write(struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, said, said, size, at, 0))
    return path


@unittest.skipUnless(pictures.available(), "needs Pillow")
class SongListTest(GameCase):

    def setUp(self):
        super().setUp()
        self.file = os.path.join(self.tmp, songlist.NAME)
        self.manifest, self.report = sources.save(self.tmp, self.file, now=1000)
        # A server that read the same game folder directly, to compare with.
        self.direct = os.path.join(self.tmp, "direct")
        catalog.read(self.tmp, self.direct, now=1000)

    def zip_with(self, changes=None, drop=(), extra=None, name="changed.zip"):
        """The saved song list rewritten with entries changed ({name: bytes}), dropped or added (a list of
        (ZipInfo or name, bytes)); returns its path."""
        out = os.path.join(self.tmp, name)
        with zipfile.ZipFile(self.file) as src, zipfile.ZipFile(out, "w") as dst:
            for info in src.infolist():
                if info.filename in drop:
                    continue
                data = (changes or {}).get(info.filename, src.read(info))
                dst.writestr(info, data)
            for entry, data in extra or ():
                if isinstance(entry, str):
                    # The name exactly as given: zipfile turns a backslash into a slash on Windows (its os.sep), and a
                    # name with one is what a test of the reader's refusals hands it.
                    info = zipfile.ZipInfo("entry")
                    info.filename = entry
                    entry = info
                dst.writestr(entry, data)
        return out

    def manifest_with(self, **fields):
        """The manifest's bytes with these fields changed."""
        return json.dumps(dict(self.manifest, **fields)).encode("utf-8")

    def refused(self, path, key):
        """Taking `path` is refused with this key, and the server's data (a reading already there) stays as it was,
        with nothing of the reading's own left in it."""
        data = os.path.join(self.tmp, "server")
        catalog.read(self.tmp, data, now=1)
        before = tree(data)
        with self.assertRaises((songlist.SongListError, sources.SourceError)) as caught:
            songlist.take(path, data)
        self.assertEqual(caught.exception.key, key, str(caught.exception))
        self.assertEqual(tree(data), before)
        return caught.exception

    # ------------------------------------------------------------------------------------------- the same result

    def test_the_file_holds_the_song_list_its_jackets_and_the_dj_cards_and_nothing_else(self):
        with zipfile.ZipFile(self.file) as z:
            names = sorted(z.namelist())
        self.assertEqual(names, ["cards.json", "cards/icon/0.png", "cards/icon/1.png", "cards/pattern/7.png",
                                 "cards/plate/32768.png", "cards/plate/32769.png", "catalog.json", "jackets/1.png",
                                 "jackets/2.png", "jackets/3.png", "manifest.json"])
        # What it says it holds: the newest song list's three songs, every song's jacket (one only in a patch).
        self.assertEqual((self.manifest["songs"], self.manifest["jackets"], self.manifest["cards"]),
                         (3, 3, {"icon": 2, "plate": 2, "pattern": 2}))
        self.assertEqual((self.manifest["format"], self.manifest["version"], self.manifest["missing"]),
                         (songlist.FORMAT, songlist.VERSION, {}))

    def test_taking_it_gives_what_reading_the_folder_gives_byte_for_byte(self):
        data = os.path.join(self.tmp, "taken")
        report = songlist.take(self.file, data, now=2000)
        taken, direct = tree(data), tree(self.direct)
        # The report differs (where it came from); everything else is the same, file by file.
        for name in (catalog.READ_FILE,):
            taken.pop(name)
            direct.pop(name)
        self.assertEqual(taken, direct)
        self.assertGreaterEqual(len(taken), 10)
        self.assertEqual((report["from"], report["path"], report["made"], report["songs"], report["jackets"]),
                         ("file", songlist.NAME, 1000, 3, 3))
        self.assertEqual(catalog.read_report(data)["from"], "file")
        self.assertEqual(catalog.state(data)["source"], {"from": "file", "path": songlist.NAME, "made": 1000})

    def test_the_same_game_folder_saves_the_same_file(self):
        again = os.path.join(self.tmp, "again.zip")
        sources.save(self.tmp, again, now=1000)
        with open(self.file, "rb") as a, open(again, "rb") as b:
            self.assertEqual(a.read(), b.read())

    def test_a_song_list_without_jackets_leaves_the_servers_own(self):
        data = os.path.join(self.tmp, "server")
        catalog.read(self.tmp, data, now=1)
        before = tree(os.path.join(data, catalog.JACKETS))
        # A song list saved from a folder whose jackets could not be read.
        manifest = self.manifest_with(jackets=None, missing={"jackets": "The game's files have no jackets."},
                                      reasons={"jackets": "error.game.no_jackets"})
        path = self.zip_with({"manifest.json": manifest}, drop=("jackets/1.png", "jackets/2.png", "jackets/3.png"))
        report = songlist.take(path, data)
        self.assertEqual(report["missing"], {"jackets": "The game's files have no jackets."})
        self.assertEqual(tree(os.path.join(data, catalog.JACKETS)), before)
        self.assertEqual(catalog.state(data)["missing"],
                         [{"part": "jackets", "why": "The game's files have no jackets.", "key": "error.game.no_jackets"}])

    # ------------------------------------------------------------------------------------------- refusals

    def test_an_entry_outside_its_names_or_its_folders_is_refused(self):
        for name in ("../evil.png", "/etc/evil", "jackets/../../evil.png", "notes.txt", "jackets/01.png",
                     "cards/icon/1.PNG", "cards/other/1.png", "jackets\\1.png", "C:/x.png"):
            with self.subTest(name=name):
                path = self.zip_with(extra=[(name, b"x")], name="extra.zip")
                error = self.refused(path, "error.songlist.entry")
                # As the reader saw it: Windows' zipfile reads a backslash in a name as its os.sep, a slash.
                self.assertIn(name[:20].replace(os.sep, "/"), str(error))

    def test_a_link_an_encrypted_entry_or_one_named_twice_is_refused(self):
        link = zipfile.ZipInfo("jackets/1.png")
        # The unix kind bits of a link, as a zip made on Linux keeps them.
        link.external_attr = 0o120777 << 16
        path = self.zip_with(drop=("jackets/1.png",), extra=[(link, b"/etc/passwd")])
        self.refused(path, "error.songlist.entry")
        with warnings.catch_warnings():
            # Python's zip writer warns of the name it is asked to write twice: that is the case tried.
            warnings.simplefilter("ignore", UserWarning)
            twice = self.zip_with(extra=[("jackets/2.png", png(160, 160))], name="twice.zip")
        self.refused(twice, "error.songlist.entry")
        # Marked encrypted (Python's zip writer clears the mark, so it is set in the file's bytes afterwards).
        path = self.zip_with(name="locked.zip")
        self.mark_encrypted(path, "jackets/1.png")
        self.refused(path, "error.songlist.entry")

    def mark_encrypted(self, path, name):
        """Set the "encrypted" bit of one entry, in its local header and in the central directory."""
        with zipfile.ZipFile(path) as z:
            info = z.getinfo(name)
        with open(path, "rb") as f:
            data = bytearray(f.read())
        # The local header's flags are 6 bytes after its signature.
        data[info.header_offset + 6] |= 0x1
        # The central directory's record of it: each record's signature, its name 46 bytes in; its flags 8 bytes in.
        at = data.find(b"PK\x01\x02")
        while at >= 0:
            length = int.from_bytes(data[at + 28:at + 30], "little")
            if data[at + 46:at + 46 + length] == name.encode():
                break
            at = data.find(b"PK\x01\x02", at + 4)
        data[at + 8] |= 0x1
        with open(path, "wb") as f:
            f.write(data)

    def test_a_bomb_is_refused_before_it_is_unpacked(self):
        # One picture that unpacks past what any picture may be.
        bomb = self.zip_with({"jackets/1.png": b"\x00" * (songlist.MOST_ENTRY["picture"] + 1)}, name="bomb.zip")
        self.refused(bomb, "error.songlist.entry")
        # All of them past what a song list may unpack to (the limit made small for the test).
        with mock.patch.object(songlist, "MOST_UNPACKED", 1000):
            self.refused(self.file, "error.songlist.unpacked")
        # Too many entries: said in their own words.
        with mock.patch.object(songlist, "MOST_ENTRIES", 5):
            self.refused(self.file, "error.songlist.entries")
        # The file itself past the upload's limit.
        with mock.patch.object(songlist, "MOST", 100):
            self.refused(self.file, "error.songlist.too_large")


    def test_entries_past_the_cap_are_refused_before_the_directory_is_read(self):
        # The end records say how many: past MOST_ENTRIES (zip64's record too), or a directory that could name more,
        # refused in its own words before Python's zip reader holds an entry of it (it never opens the file at all).
        cases = {"9000 entries": many(os.path.join(self.tmp, "9000.zip"), 9000),
                 "70000 entries, zip64": many(os.path.join(self.tmp, "70000.zip"), 70000),
                 "a directory of 50000 that says 1": many(os.path.join(self.tmp, "lies.zip"), 50000, said=1)}
        for case, path in cases.items():
            with self.subTest(case=case), mock.patch.object(songlist.zipfile, "ZipFile",
                                                            side_effect=AssertionError("the directory was read")):
                error = self.refused(path, "error.songlist.entries")
                self.assertEqual(str(error), "This song list holds more than 8192 entries. Save it again in the "
                                             "launcher.")
                self.assertFalse(songlist.is_song_list(path))
                with self.assertRaises(songlist.SongListError):
                    songlist.look(path)
        # End records that say fewer than a small directory holds: counted once it is read, the same words.
        self.refused(many(os.path.join(self.tmp, "fewer.zip"), 9000, said=1), "error.songlist.entries")
        # An archive on the server PC is counted the same way against its own cap.
        with mock.patch.object(sources, "ENTRIES_MOST", 100), \
                mock.patch.object(sources.zipfile, "ZipFile", side_effect=AssertionError("the directory was read")):
            with self.assertRaises(sources.SourceError) as caught:
                sources.listing(many(os.path.join(self.tmp, "technika.zip"), 500))
        self.assertEqual(caught.exception.key, "error.source.entry")

    def test_a_broken_picture_or_one_too_large_or_not_a_png_is_refused(self):
        good = png(160, 160)
        for case, data in (("cut", good[:len(good) // 2]), ("not a picture", b"\x89PNG\r\n\x1a\nnothing"),
                           ("too large", png(161, 160)), ("a jpeg", self.jpeg())):
            with self.subTest(case=case):
                path = self.zip_with({"jackets/1.png": data}, name="picture.zip")
                self.refused(path, "error.songlist.picture")
        # A DJ card picture larger than its kind may be.
        path = self.zip_with({"cards/icon/1.png": png(600, 64)}, name="card.zip")
        self.refused(path, "error.songlist.picture")

    def jpeg(self):
        from PIL import Image
        out = io.BytesIO()
        Image.new("RGB", (16, 16)).save(out, "JPEG")
        return out.getvalue()

    def test_a_table_of_another_shape_is_refused(self):
        songs = json.loads(zipfile.ZipFile(self.file).read("catalog.json"))
        for case, changed in (
                ("not JSON", b"{"),
                ("a number as text", json.dumps({"songs": [dict(songs["songs"][0], number="1")]})),
                ("a field more", json.dumps({"songs": [dict(songs["songs"][0], extra=1)]})),
                ("a line break", json.dumps({"songs": [dict(songs["songs"][0], title="a\nb")]})),
                ("levels", json.dumps({"songs": [dict(songs["songs"][0], star=[1, 2, 3])]})),
                ("twice", json.dumps({"songs": [songs["songs"][0], songs["songs"][0]]}))):
            with self.subTest(case=case):
                data = changed if isinstance(changed, bytes) else changed.encode()
                path = self.zip_with({"catalog.json": data}, name="shape.zip")
                self.refused(path, "error.songlist.shape")
        tables = json.loads(zipfile.ZipFile(self.file).read("cards.json"))
        path = self.zip_with({"cards.json": json.dumps(dict(tables, points={"x": 1})).encode()}, name="cards.zip")
        self.refused(path, "error.songlist.shape")

    def test_a_song_list_from_a_newer_openDMT3_says_so(self):
        path = self.zip_with({"manifest.json": self.manifest_with(version=songlist.VERSION + 1)})
        error = self.refused(path, "error.songlist.newer")
        self.assertIn("format %d" % (songlist.VERSION + 1), str(error))

    def test_what_is_not_a_song_list_is_said_so(self):
        other = os.path.join(self.tmp, "other.zip")
        with zipfile.ZipFile(other, "w") as z:
            z.writestr("readme.txt", "made up")
        self.refused(other, "error.songlist.entry")
        no_manifest = self.zip_with(drop=("manifest.json",))
        self.refused(no_manifest, "error.songlist.not_ours")
        text = os.path.join(self.tmp, "text.zip")
        with open(text, "w") as f:
            f.write("not a zip")
        self.refused(text, "error.songlist.not_ours")
        empty = os.path.join(self.tmp, "empty.zip")
        open(empty, "wb").close()
        self.refused(empty, "error.songlist.no_file")

    def test_a_manifest_that_says_more_than_the_file_holds_is_refused(self):
        for fields in ({"songs": 4}, {"jackets": 2}, {"cards": {"icon": 3, "plate": 2, "pattern": 2}}):
            with self.subTest(fields=fields):
                path = self.zip_with({"manifest.json": self.manifest_with(**fields)})
                self.refused(path, "error.songlist.counts")
        # A DJ card the table offers without its picture.
        path = self.zip_with(drop=("cards/plate/32769.png",))
        self.refused(path, "error.songlist.counts")
        # A jacket of a song the list does not have.
        path = self.zip_with(extra=[("jackets/9.png", png(160, 160))], name="stray.zip")
        self.refused(path, "error.songlist.entry")

    def test_a_damaged_entry_is_said_so(self):
        with open(self.file, "rb") as f:
            data = bytearray(f.read())
        # A byte of the first jacket's data changed: its CRC no longer matches.
        with zipfile.ZipFile(self.file) as z:
            info = z.getinfo("jackets/1.png")
        at = info.header_offset + 30 + len(info.filename) + 40
        data[at] ^= 0xFF
        path = os.path.join(self.tmp, "damaged.zip")
        with open(path, "wb") as f:
            f.write(data)
        self.refused(path, "error.songlist.damaged")

    def test_the_pictures_lose_everything_but_their_pixels(self):
        with zipfile.ZipFile(self.file) as z:
            jacket = z.read("jackets/1.png")
        # The made-up game's jackets carry a text chunk; the server's one form has none.
        self.assertNotIn(b"by a test", jacket)
        self.assertEqual(pictures.canonical(jacket, "jacket"), jacket)


@unittest.skipUnless(pictures.available(), "needs Pillow")
class SongListPartsTest(GameCase):
    def test_a_folder_without_dj_cards_saves_a_song_list_that_says_so_and_is_taken(self):
        for name in ("Script.pak", "Script00.pak", "Script01.pak"):
            os.remove(os.path.join(self.pack, name))
        path = os.path.join(self.tmp, songlist.NAME)
        manifest, _ = sources.save(self.tmp, path)
        self.assertEqual(manifest["missing"], {"cards": "The game's files have no DJ cards."})
        self.assertEqual(manifest["reasons"], {"cards": "error.card.tables"})
        report = songlist.take(path, os.path.join(self.tmp, "server"))
        self.assertIsNone(report["cards"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "server", cards.FILE)))


if __name__ == "__main__":
    unittest.main()
