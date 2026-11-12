"""Tests for the archive reader and writer, with made-up data only: no game file is needed or kept here.

A random 256-byte table and a random key byte stand in for the client's; the writer builds an archive and
the reader must recover the key byte from the paths alone and return every file unchanged.

With OPENDMT3_GAME_DIR set to a game folder (the one holding pack\\ and Client.exe), two more tests read
the player's own archives: every one opens, and an update archive built from one reads back.
"""

import hashlib
import os
import random
import tempfile
import threading
import time
import unittest
from unittest import mock

from opendmt3.core.formats import pak


def _random_bytes(rng, n):
    return bytes(rng.randrange(256) for _ in range(n))


class KeyStreamTest(unittest.TestCase):
    def test_mask_then_unmask_restores_the_bytes(self):
        rng = random.Random(1)
        data = bytearray(_random_bytes(rng, 103))           # a partial last word stays as it is
        seed = 0x12345678
        hidden = bytearray(data)
        pak.mask(hidden, seed)
        self.assertNotEqual(hidden[:100], data[:100])
        self.assertEqual(hidden[100:], data[100:])
        pak.unmask(hidden, seed)
        self.assertEqual(hidden, data)

    def test_even_and_odd_seeds_use_different_functions(self):
        # Same input value through sine and cosine: the words differ.
        self.assertNotEqual(pak.keystream_word(2, 0), pak.keystream_word(1, 1))

    # Seeds where the float32 rounding of seed + i changes its step (2**24 on), where the stream starts to be worked
    # out per run (2**28), the largest ones (whose stream runs past 2**32), and both parities of each.
    EDGE_SEEDS = (0, 1, 2, 3, 2**24 - 3, 2**24 - 2, 2**24 - 1, 2**24, 2**24 + 1, 2**26 - 1, 2**26, 2**28 - 2, 2**28 - 1,
                  2**28, 2**28 + 1, 2**31 - 1, 2**31, 2**31 + 1, 2**32 - 3000, 2**32 - 2, 2**32 - 1)

    def test_the_stream_in_bulk_is_the_stream_word_by_word(self):
        # keystream() gives every word keystream_word gives, bit for bit, at every seed and length that tells the two
        # ways of working it out apart (one value per run of seed + i, or one per word).
        rng = random.Random(4)
        seeds = list(self.EDGE_SEEDS) + [rng.randrange(1 << 32) for _ in range(40)]
        for seed in seeds:
            for count in (0, 1, 2, 7, 600, 3000):
                expected = b"".join(pak.keystream_word(seed, i).to_bytes(4, "little") for i in range(count))
                self.assertEqual(pak.keystream(seed, count), expected, (seed, count))

    def test_a_run_ends_where_float32_rounds_to_the_next_value(self):
        # Every integer up to a run's end rounds to the run's value, the one after it to another: across the steps
        # from 2 to 1024, at the ends of each step's span and in it.
        rng = random.Random(5)
        for e in range(24, 34):
            for k in (1 << e, (1 << e) + 1, (1 << e) + (1 << (e - 24)), (2 << e) - 1, rng.randrange(1 << e, 2 << e)):
                last = pak._run_end(k)
                same = pak._f32.pack(float(k))
                self.assertEqual(pak._f32.pack(float(last)), same, k)
                self.assertNotEqual(pak._f32.pack(float(last + 1)), same, k)

    def test_hiding_and_revealing_wrap_every_word_alone(self):
        # The words added and taken all at once wrap at 2**32 each, never carrying into the word beside them: the
        # same as one word at a time, on words of every bit pattern that carries or borrows (all ones, all zeros).
        rng = random.Random(6)
        for seed in self.EDGE_SEEDS[:6] + (2**31, 2**32 - 1):
            words = [0, 0xFFFFFFFF, 0x80000000, 0x7FFFFFFF] + [rng.randrange(1 << 32) for _ in range(60)]
            data = bytearray(b"".join(w.to_bytes(4, "little") for w in words)) + b"\x01\x02"
            for sign, change in ((1, pak.mask), (-1, pak.unmask)):
                expected = bytearray(data)
                for i in range(len(words)):
                    word = int.from_bytes(expected[4 * i:4 * i + 4], "little")
                    word = (word + sign * pak.keystream_word(seed, i)) & 0xFFFFFFFF
                    expected[4 * i:4 * i + 4] = word.to_bytes(4, "little")
                changed = bytearray(data)
                change(changed, seed)
                # The two bytes after the last whole word stay as they are.
                self.assertEqual(changed, expected, (seed, sign))

    def test_word_zero_of_256_seeds_at_once(self):
        # The key byte search's table: word 0 of each of the 256 seeds that share their three upper bytes.
        for top in (0, 1 << 8, (1 << 24) - 256, 1 << 24, 1 << 28, 1 << 31, (1 << 32) - 256):
            firsts = pak._first_words(top)
            self.assertEqual(list(firsts), [pak.keystream_word(top + b, 0) for b in range(256)], top)


class HeaderTest(unittest.TestCase):
    def test_round_trip(self):
        h = pak.Header(0xCAFEBABE, 0x31, 2, 7, 54, 0xCE, 0, 0x5A)
        back = pak.Header.parse(h.build())
        for field in ("seed", "first", "version", "unknown", "count", "flag", "stream_flag"):
            self.assertEqual(getattr(back, field), getattr(h, field), field)

    def test_build_writes_the_check_byte_the_client_expects(self):
        # The client rejects a header whose check byte does not match its fields.
        for count, first, flag, stream_flag in ((1, 0x31, 0x10, 0), (54, 0x2D30, 0xCE, 0), (7, 0x31, 0xFF, 1)):
            h = pak.Header(1, first, 2, 0, count, flag, stream_flag, 0)
            back = pak.Header.parse(h.build())
            self.assertEqual(back.check, back.expected_check())


class LzoTest(unittest.TestCase):
    def test_stored_streams_decompress_to_the_input(self):
        rng = random.Random(2)
        # Lengths around every encoding boundary of a literal run.
        for n in (0, 1, 3, 4, 17, 238, 239, 240, 270, 271, 600, 70000):
            data = _random_bytes(rng, n)
            self.assertEqual(pak.lzo1x_decompress(pak.lzo1x_store(data)), data, n)

    def test_matches_are_copied_with_overlap(self):
        # A literal run of 4, then a match four bytes back and eight long, so it overlaps itself, then the end
        # marker.
        stream = bytes([17 + 4]) + b"abcd" + bytes([32 | 6, (3 << 2) & 0xFF, 0]) + b"\x11\x00\x00"
        self.assertEqual(pak.lzo1x_decompress(stream), b"abcd" + b"abcdabcd")

    def test_a_crafted_stream_is_refused_before_it_unpacks(self):
        # A few kilobytes that say a match of half a million bytes: refused at the chunk's size, not spelled out.
        huge = bytes([17 + 4]) + b"abcd" + bytes([32]) + bytes(2000) + bytes([1, 3 << 2, 0]) + b"\x11\x00\x00"
        with self.assertRaises(pak.PakError):
            pak.lzo1x_decompress(huge, 4096)
        # Cut short inside an instruction: a PakError, as every other archive fault is.
        with self.assertRaises(pak.PakError):
            pak.lzo1x_decompress(bytes([17 + 4]) + b"abcd" + bytes([32, 0]))


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(3)
        self.table = _random_bytes(self.rng, 256)
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, files, key_byte=0x5D, flag=0xC9):
        template = pak.Header(0x01020304, 0, 2, 0, 0, flag, 0, 0)
        key_field = (0x3333).to_bytes(4, "little") + (0).to_bytes(4, "little")
        path = os.path.join(self.tmp.name, "Sample.pak")
        pak.write_pak(path, files, self.table, key_byte, key_field, template, bytes(32),
                      seed_source=lambda n: self.rng.randrange(1 << 32).to_bytes(n, "little"))
        return path

    def test_every_file_reads_back(self):
        files = {
            "Resource\\Sample\\small.csv": b"a,b,c\r\n1,2,3\r\n",
            "Resource\\Sample\\empty.txt": b"",
            "Resource/Sample/big.bin": _random_bytes(self.rng, pak.CHUNK + 12345),
        }
        path = self._write(files)
        with pak.Pak(path, self.table) as p:
            self.assertEqual([e.name for e in p.entries],
                             ["Resource\\Sample\\small.csv", "Resource\\Sample\\empty.txt", "Resource\\Sample\\big.bin"])
            for name, data in files.items():
                self.assertEqual(p.read(p.find(name)), data, name)
            # One key index was used, and the reader recovered its byte from the paths.
            self.assertEqual(list(p.key_bytes.values()), [0x5D])

    def test_files_longer_than_the_hidden_prefix(self):
        data = _random_bytes(self.rng, pak.MASKED_PREFIX + 99)
        path = self._write({"Resource\\Sample\\long.bin": data})
        with pak.Pak(path, self.table) as p:
            self.assertEqual(p.read(p.entries[0]), data)

    def test_update_archive_from_a_base(self):
        base = self._write({"Resource\\Sample\\a.csv": b"1", "Resource\\Sample\\b.csv": b"2"}, key_byte=0x77, flag=0x10)
        update = os.path.join(self.tmp.name, "Sample00.pak")
        pak.build_update(base, update, {"Resource\\Sample\\a.csv": b"changed"}, self.table)
        with pak.Pak(update, self.table) as p:
            self.assertEqual(p.read(p.find("Resource/Sample/a.csv")), b"changed")
            self.assertEqual(list(p.key_bytes.values()), [0x77])

    def test_a_korean_name_first_under_its_key_byte_opens(self):
        # As in six archives of a whole game folder: the first entry under a key byte has a Korean name (here
        # "keyboard2.jpg" in Korean), and its key byte is recovered from that name like from any other.
        files = {"Resource\\Sample\\키보드2.jpg": b"\xff\xd8\xff made-up picture", "Resource\\Sample\\b.csv": b"2"}
        path = self._write(files)
        with pak.Pak(path, self.table) as p:
            # Every name read back as written, the Korean one first.
            self.assertEqual([e.name for e in p.entries], list(files))
            # Found by its name with either slash, and its data unchanged.
            self.assertEqual(p.read(p.find("Resource/Sample/키보드2.jpg")), files["Resource\\Sample\\키보드2.jpg"])
            # The same one key byte as an archive of ASCII names: one key scheme for both.
            self.assertEqual(list(p.key_bytes.values()), [0x5D])
            # Spelled in the client's code page inside the descriptor, as the game's own archives spell it.
            p.file.seek(p.entries[0].offset - pak.DESC_SIZE)
            raw = p.file.read(pak.DESC_SIZE)
            # The table walk of entry 0 starts at the header's flag (0xC9 in _write) minus its position, 0.
            name = pak._decode_descriptor(raw, 0x5D, self.table, 0xC9)[1]
            self.assertEqual(name, "Resource\\Sample\\키보드2.jpg".encode("cp949"))

    def test_a_patch_of_korean_names_reads_with_its_base_key(self):
        # A patch whose only file has a Korean name ("speed notes.txt", as in a chart patch): opened with the key
        # byte its base uses, recovered from the Korean name itself.
        base = self._write({"Resource\\Sample\\a.csv": b"1"}, key_byte=0x42, flag=0x20)
        update = os.path.join(self.tmp.name, "Sample00.pak")
        notes = "1.5배".encode(pak.PATH_CODEC)
        pak.build_update(base, update, {"Resource\\Sample\\배속정보.txt": notes}, self.table)
        with pak.Pak(update, self.table) as p:
            self.assertEqual([e.name for e in p.entries], ["Resource\\Sample\\배속정보.txt"])
            self.assertEqual(p.read(p.entries[0]), notes)
            self.assertEqual(list(p.key_bytes.values()), [0x42])

    def test_only_bytes_a_file_name_holds_give_a_key_byte(self):
        # One descriptor written by hand for each name, every key byte tried on it as the reader does.
        key_field = (0x3333).to_bytes(4, "little") + bytes(4)
        cases = (
            # A Korean name in the client's code page: its key byte is found.
            ("키보드2.jpg".encode("cp949"), [0x5D]),
            # A name in another code page (Japanese here): any byte a file name holds is taken, whatever it spells.
            ("キー.png".encode("shift_jis"), [0x5D]),
            # A control character is in no file name: no key byte gives a path.
            (b"a\x01.png", []),
            (b"a\x1f.png", []),
        )
        for rest, found in cases:
            name = b"Resource\\Sample\\" + rest
            raw = pak._encode_descriptor(0x1234, name, 10, 10, key_field, 0x5D, self.table, 7)
            self.assertEqual(pak._key_bytes(raw, self.table, 7, None, 0), found, name)

    def test_ascii_names_are_written_byte_for_byte_as_before(self):
        # The archive the writer made before it took Korean names (the writer of an earlier openDMT3), from the same
        # seeded input: the bytes of every archive of ASCII names written so far stay the same.
        rng = random.Random(7)
        table = _random_bytes(rng, 256)
        files = {"Resource\\Sample\\small.csv": b"a,b,c\r\n1,2,3\r\n", "Resource\\Sample\\empty.txt": b"",
                 "Resource/Sample/big.bin": _random_bytes(rng, pak.CHUNK + 4321)}
        template = pak.Header(0x01020304, 0, 2, 0, 0, 0xC9, 0, 0)
        key_field = (0x3333).to_bytes(4, "little") + bytes(4)
        path = os.path.join(self.tmp.name, "Sample.pak")
        pak.write_pak(path, files, table, 0x5D, key_field, template, bytes(32),
                      seed_source=lambda n: rng.randrange(1 << 32).to_bytes(n, "little"))
        with open(path, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(digest, "7e88d2b66b84c4c794deef4bf2c2b20b2af2c1cb6c6ec70690422ae35cfa07d1")


class ListingTest(unittest.TestCase):
    """An archive opened again takes the listing kept from its first walk, as long as it is the same file."""

    def setUp(self):
        self.rng = random.Random(8)
        self.table = _random_bytes(self.rng, 256)
        self.tmp = tempfile.TemporaryDirectory()
        # Every test starts with nothing kept, and counts the walks of the descriptors it causes.
        pak.forget_listings()
        self.walks = 0
        real = pak.Pak._walk

        def counted(archive):
            self.walks += 1
            return real(archive)

        patcher = mock.patch.object(pak.Pak, "_walk", counted)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        pak.forget_listings()
        self.tmp.cleanup()

    def _write(self, files, name="Sample.pak", age=60):
        """An archive of `files`, dated `age` seconds back (None: written just now)."""
        template = pak.Header(0x01020304, 0, 2, 0, 0, 0xC9, 0, 0)
        key_field = (0x3333).to_bytes(4, "little") + bytes(4)
        path = os.path.join(self.tmp.name, name)
        pak.write_pak(path, files, self.table, 0x5D, key_field, template, bytes(32),
                      seed_source=lambda n: self.rng.randrange(1 << 32).to_bytes(n, "little"))
        if age is not None:
            then = time.time() - age
            os.utime(path, (then, then))
        return path

    def test_an_archive_opened_again_is_walked_once(self):
        files = {"Resource\\Sample\\a.csv": b"1,2", "Resource\\Sample\\b.csv": b"3,4,5"}
        path = self._write(files)
        with pak.Pak(path, self.table) as first:
            names = [e.name for e in first.entries]
        with pak.Pak(path, self.table) as again:
            # The listing kept, and the data read through the file opened again.
            self.assertEqual([e.name for e in again.entries], names)
            self.assertEqual(again.read(again.find("Resource/Sample/b.csv")), b"3,4,5")
            self.assertEqual(list(again.key_bytes.values()), [0x5D])
        self.assertEqual(self.walks, 1)

    def test_a_changed_archive_is_walked_again(self):
        path = self._write({"Resource\\Sample\\a.csv": b"1"})
        with pak.Pak(path, self.table):
            pass
        # Another archive at the same path, dated as far back: its own listing, not the one kept.
        self._write({"Resource\\Sample\\a.csv": b"1", "Resource\\Sample\\new.csv": b"22"})
        with pak.Pak(path, self.table) as again:
            self.assertEqual([e.name for e in again.entries], ["Resource\\Sample\\a.csv", "Resource\\Sample\\new.csv"])
        self.assertEqual(self.walks, 2)

    def test_an_archive_written_just_now_is_walked_every_time(self):
        # Rewritten in place at once, at the same size, a file can keep its times on a coarse clock: none is kept.
        path = self._write({"Resource\\Sample\\a.csv": b"1"}, age=None)
        for _ in range(2):
            with pak.Pak(path, self.table):
                pass
        self.assertEqual(self.walks, 2)

    def test_another_table_never_takes_the_listing_kept(self):
        path = self._write({"Resource\\Sample\\a.csv": b"1"})
        with pak.Pak(path, self.table):
            pass
        # The listing was read with this table; another one opens nothing (the archive of another build, as before).
        with self.assertRaises(pak.PakUnreadable):
            pak.Pak(path, bytes(256))

    def test_the_listings_kept_are_bounded(self):
        paths = [self._write({"Resource\\Sample\\a.csv": b"1", "Resource\\Sample\\b.csv": b"2"}, name="S%d.pak" % i)
                 for i in range(2)]
        with mock.patch.object(pak, "LISTED_MOST", 3):
            for path in paths + paths[1:]:
                with pak.Pak(path, self.table):
                    pass
            # The second archive's listing pushed the first one's out (four entries kept would be one too many);
            # the second one, used last, is still kept.
            self.assertEqual(self.walks, 2)
            with pak.Pak(paths[0], self.table):
                pass
            self.assertEqual(self.walks, 3)

    def test_descriptors_are_found_through_growing_and_shrinking_windows(self):
        # Small entries (windows grow while each read serves several) between long ones (they shrink), with windows
        # small enough that every turn happens in a test-sized archive.
        files = {}
        for i in range(60):
            size = 9000 if i % 13 == 5 else self.rng.randrange(0, 300)
            files["Resource\\Sample\\%02d.bin" % i] = _random_bytes(self.rng, size)
        path = self._write(files)
        with mock.patch.object(pak, "WALK_WINDOW_LEAST", 256), mock.patch.object(pak, "WALK_WINDOW_MOST", 4096):
            with pak.Pak(path, self.table) as p:
                self.assertEqual([e.name for e in p.entries], list(files))
                for name, data in files.items():
                    self.assertEqual(p.read(p.find(name)), data, name)


class ReadAheadTest(unittest.TestCase):
    """A large file's walk with its next windows read ahead on threads, and openings of one file at once."""

    def setUp(self):
        self.rng = random.Random(9)
        self.table = _random_bytes(self.rng, 256)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        pak.forget_listings()
        self.addCleanup(pak.forget_listings)

    def _write(self, files):
        template = pak.Header(0x01020304, 0, 2, 0, 0, 0xC9, 0, 0)
        key_field = (0x3333).to_bytes(4, "little") + bytes(4)
        path = os.path.join(self.tmp.name, "Sample.pak")
        pak.write_pak(path, files, self.table, 0x5D, key_field, template, bytes(32),
                      seed_source=lambda n: self.rng.randrange(1 << 32).to_bytes(n, "little"))
        # Left alone a while, so its listing may be kept.
        then = time.time() - 60
        os.utime(path, (then, then))
        return path

    def test_the_walk_read_ahead_finds_what_the_walk_alone_finds(self):
        # Runs of small entries (windows read ahead, descriptors running over a window's end into the next one) with
        # long entries between them (the walk jumps past what was read ahead) and a short one last.
        files = {}
        for i in range(150):
            size = 6000 if i % 23 == 11 else self.rng.randrange(0, 400)
            files["Resource\\Sample\\%03d.bin" % i] = _random_bytes(self.rng, size)
        path = self._write(files)
        listings = []
        for least, most, ahead_from in ((256, 1024, 1 << 40), (256, 1024, 0), (200, 300, 0)):
            pak.forget_listings()
            with mock.patch.object(pak, "WALK_WINDOW_LEAST", least), mock.patch.object(pak, "WALK_WINDOW_MOST", most), \
                    mock.patch.object(pak, "WALK_AHEAD_FROM", ahead_from):
                with pak.Pak(path, self.table) as p:
                    listings.append([(e.index, e.name, e.seed, e.offset, e.packed, e.size) for e in p.entries])
                    for name, data in files.items():
                        self.assertEqual(p.read(p.find(name)), data, name)
        # Read ahead or not, at any window size: the same listing.
        self.assertEqual(listings[1], listings[0])
        self.assertEqual(listings[2], listings[0])
        self.assertEqual(len(listings[0]), len(files))

    def test_a_file_cut_short_is_said_with_the_walk_read_ahead(self):
        path = self._write({"Resource\\Sample\\%02d.bin" % i: bytes(100) for i in range(30)})
        with open(path, "r+b") as f:
            f.truncate(os.path.getsize(path) - 150)
        with mock.patch.object(pak, "WALK_AHEAD_FROM", 0), mock.patch.object(pak, "WALK_WINDOW_LEAST", 256):
            with self.assertRaises(pak.PakError):
                pak.Pak(path, self.table)

    def test_threads_opening_one_file_at_once_walk_it_once(self):
        path = self._write({"Resource\\Sample\\a.csv": b"1", "Resource\\Sample\\b.csv": b"22"})
        walks, gate = [], threading.Event()
        real = pak.Pak._walk

        def slow_walk(archive):
            walks.append(1)
            # The first walk waits until the other threads are opening the file too.
            gate.wait(5)
            return real(archive)

        opened = []
        with mock.patch.object(pak.Pak, "_walk", slow_walk):
            threads = [threading.Thread(target=lambda: opened.append(pak.Pak(path, self.table))) for _ in range(4)]
            for thread in threads:
                thread.start()
            time.sleep(0.2)
            gate.set()
            for thread in threads:
                thread.join(10)
        try:
            self.assertEqual(len(walks), 1)
            self.assertEqual([[e.name for e in p.entries] for p in opened], [["Resource\\Sample\\a.csv",
                                                                               "Resource\\Sample\\b.csv"]] * 4)
        finally:
            for p in opened:
                p.close()


@unittest.skipUnless(os.environ.get("OPENDMT3_GAME_DIR"), "needs OPENDMT3_GAME_DIR (the player's own game folder)")
class PlayerArchiveTest(unittest.TestCase):
    def test_update_built_from_the_players_archive_reads_back(self):
        game = os.environ["OPENDMT3_GAME_DIR"]
        table = pak.load_table(os.path.join(game, "Client.exe"))
        with pak.Pak(os.path.join(game, "pack", "Config.pak"), table) as p:
            names = [e.name for e in p.entries]
        self.assertTrue(any(n.lower().endswith("networksetting.ini") for n in names))
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "Config00.pak")
            pak.build_update(os.path.join(game, "pack", "Config.pak"), out,
                             {"Resource\\Config\\networksetting.ini": b"[setting]\r\nserverip=127.0.0.1\r\nport=4725\r\n"}, table)
            with pak.Pak(out, table) as q:
                self.assertEqual(q.read(q.entries[0]), b"[setting]\r\nserverip=127.0.0.1\r\nport=4725\r\n")

    def test_every_archive_of_the_players_folder_opens(self):
        # Every one of the game's files opens with the one key scheme, names with Korean letters and all (92 in a whole
        # game folder, the first name under a key byte Korean in six of them). Only read, never written.
        game = os.environ["OPENDMT3_GAME_DIR"]
        table = pak.load_table(os.path.join(game, "Client.exe"))
        folder = os.path.join(game, "pack")
        names = sorted(n for n in os.listdir(folder) if n.lower().endswith(".pak"))
        # A folder without archives would pass with none.
        self.assertTrue(names)
        for name in names:
            with self.subTest(archive=name):
                with pak.Pak(os.path.join(folder, name), table) as p:
                    # Every entry the header counts was walked, each with a name read back whole.
                    self.assertEqual(len(p.entries), p.header.count)
                    self.assertFalse([e.name for e in p.entries if "�" in e.name])


if __name__ == "__main__":
    unittest.main()
