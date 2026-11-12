"""A picture already in the server's one form is kept as it came (services/pictures.py), and only such a picture: any
other chunk, colour type, interlacing, damaged CRC, extra byte or longer pixel stream is encoded again, and what does
not decode is refused as before.
"""

import io
import struct
import unittest
import zlib

from opendmt3.server.services import pictures


def chunk(kind, body):
    """One PNG chunk: its length, type, data and CRC."""
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def png(width=4, height=3, colour=6, interlace=0, extra_chunks=(), after_end=b"", stream_tail=b"", level=9):
    """A PNG made by hand: rows of filter 0 and made-up pixels, compressed at `level`; `stream_tail` goes after the
    zlib stream inside the pixel data, `after_end` after the IEND chunk."""
    channels = {6: 4, 2: 3}[colour]
    rows = b"".join(b"\x00" + bytes((x * 40 + y * 7 + c) % 256 for x in range(width) for c in range(channels))
                    for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, colour, 0, 0, interlace)
    out = pictures.SIGNATURE + chunk(b"IHDR", header)
    for kind, body in extra_chunks:
        out += chunk(kind, body)
    return out + chunk(b"IDAT", zlib.compress(rows, level) + stream_tail) + chunk(b"IEND", b"") + after_end


@unittest.skipUnless(pictures.available(), "needs Pillow")
class PlainPicturesTest(unittest.TestCase):

    def pixels(self, data):
        """The picture's pixels as RGBA, as Pillow decodes them."""
        from PIL import Image
        with Image.open(io.BytesIO(data)) as picture:
            return picture.convert("RGBA").tobytes()

    def test_a_plain_picture_is_kept_as_it_came(self):
        for level in (0, 1, 9):
            data = png(level=level)
            self.assertTrue(pictures.plain(data, 4, 3))
            self.assertEqual(pictures.canonical(data, "icon"), data)
        # Its pixel data split over several IDAT chunks, as encoders do for large pictures: still plain.
        rows = zlib.compress(b"".join(b"\x00" + bytes(16) for _ in range(3)))
        split = (pictures.SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 3, *pictures.PLAIN_HEADER)) +
                 chunk(b"IDAT", rows[:5]) + chunk(b"IDAT", rows[5:]) + chunk(b"IEND", b""))
        self.assertEqual(pictures.canonical(split, "icon"), split)
        # What the server itself encodes is plain: a picture taken twice keeps the first's bytes.
        made = pictures.canonical(png(colour=2), "icon")
        self.assertTrue(pictures.plain(made, 4, 3))
        self.assertEqual(pictures.canonical(made, "icon"), made)

    def test_anything_else_is_encoded_again_with_the_same_pixels(self):
        cases = {
            "a text chunk": png(extra_chunks=[(b"tEXt", b"Comment\x00made by a test")]),
            "a gamma chunk": png(extra_chunks=[(b"gAMA", struct.pack(">I", 45455))]),
            "a private chunk": png(extra_chunks=[(b"prVt", b"x")]),
            "RGB": png(colour=2),
            "a byte after the end": png(after_end=b"\x00"),
            "bytes after the pixel stream": png(stream_tail=b"hidden"),
        }
        for name, data in cases.items():
            with self.subTest(name):
                self.assertFalse(pictures.plain(data, 4, 3))
                kept = pictures.canonical(data, "icon")
                self.assertNotEqual(kept, data)
                # Encoded again: plain itself, with the same pixels.
                self.assertTrue(pictures.plain(kept, 4, 3))
                self.assertEqual(self.pixels(kept), self.pixels(png()) if name != "RGB" else self.pixels(data))

    def test_a_picture_that_only_looks_plain_is_never_kept_as_it_came(self):
        good = png()
        # A wrong CRC on the header.
        broken = bytearray(good)
        broken[8 + 8 + 13] ^= 0xFF
        self.assertFalse(pictures.plain(bytes(broken), 4, 3))
        # A size the header does not say.
        self.assertFalse(pictures.plain(good, 4, 4))
        # A pixel stream with one row too many: never inflated past the picture's rows.
        rows = b"".join(b"\x00" + bytes(16) for _ in range(4))
        longer = (pictures.SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 3, *pictures.PLAIN_HEADER)) +
                  chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
        self.assertFalse(pictures.plain(longer, 4, 3))
        # A row with a filter type the format does not have.
        rows = b"\x00" + bytes(16) + b"\x07" + bytes(16) + b"\x00" + bytes(16)
        filtered = (pictures.SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 3, *pictures.PLAIN_HEADER)) +
                    chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
        self.assertFalse(pictures.plain(filtered, 4, 3))
        # Interlaced: not the one form.
        self.assertFalse(pictures.plain(png(interlace=1), 4, 3))
        # No end, or the end first.
        self.assertFalse(pictures.plain(good[:-12], 4, 3))
        # Still refused as before when it does not decode at all.
        with self.assertRaises(pictures.PictureError):
            pictures.canonical(pictures.SIGNATURE + b"\x00" * 40, "icon")
        # Too large for its kind: refused before anything is decoded, plain or not.
        with self.assertRaises(pictures.PictureError):
            pictures.canonical(png(width=600, height=2), "icon")


class SideBySideTest(unittest.TestCase):
    """pictures.in_order: converted on several threads, handed back in the items' order, the same as one at a time."""

    def no_thread_left(self):
        import threading
        left = [t.name for t in threading.enumerate() if t.name.startswith("opendmt3-pictures")]
        self.assertEqual(left, [])

    def test_each_is_handed_back_in_its_place_whatever_finishes_first(self):
        import random
        import time
        rng = random.Random(5)
        waits = [rng.random() * 0.01 for _ in range(60)]

        def convert(n):
            # The later ones often finish first.
            time.sleep(waits[n])
            if n % 13 == 0:
                raise pictures.PictureError("made-up refusal %d" % n)
            return n * 2
        got = list(pictures.in_order(((n, n) for n in range(60)), convert, workers=4))
        self.assertEqual([tag for tag, _ in got], list(range(60)))
        for tag, value in got:
            if tag % 13 == 0:
                # A refusal is the item's answer, in its place.
                self.assertIsInstance(value, pictures.PictureError)
                self.assertEqual(str(value), "made-up refusal %d" % tag)
            else:
                self.assertEqual(value, tag * 2)
        # One worker gives the same, one after another.
        alone = list(pictures.in_order(((n, n) for n in range(60)), convert, workers=1))
        self.assertEqual([(t, v if not isinstance(v, Exception) else str(v)) for t, v in alone],
                         [(t, v if not isinstance(v, Exception) else str(v)) for t, v in got])
        self.no_thread_left()

    def test_a_reading_error_comes_after_everything_read_before_it(self):
        def items():
            for n in range(7):
                yield n, n
            raise OSError("made-up reading error")
        got = []
        with self.assertRaises(OSError):
            for tag, value in pictures.in_order(items(), lambda n: n + 100, workers=3):
                got.append((tag, value))
        # As one after another: every item read before the error was handed back first.
        self.assertEqual(got, [(n, n + 100) for n in range(7)])
        self.no_thread_left()

    def test_another_error_converting_is_raised_at_its_turn_and_the_rest_given_up(self):
        import threading
        started = []
        lock = threading.Lock()

        def convert(n):
            with lock:
                started.append(n)
            if n == 4:
                raise RuntimeError("made-up failure")
            return n
        got = []
        with self.assertRaises(RuntimeError):
            for tag, value in pictures.in_order(((n, n) for n in range(500)), convert, workers=2):
                got.append(tag)
        self.assertEqual(got, [0, 1, 2, 3])
        # Read ahead no further than AHEAD a worker past the one that failed: the rest never started.
        self.assertLessEqual(max(started), 4 + 2 * pictures.AHEAD)
        self.no_thread_left()

    def test_what_is_read_ahead_is_bounded_and_a_caller_that_stops_leaves_no_thread(self):
        import contextlib
        read = [0]

        def items():
            for n in range(200):
                read[0] += 1
                yield n, n
        ahead = 0
        with contextlib.closing(pictures.in_order(items(), lambda n: n, workers=3)) as converted:
            for handed, (tag, value) in enumerate(converted, 1):
                ahead = max(ahead, read[0] - handed)
                if handed == 50:
                    # The caller stops half way.
                    break
        self.assertLessEqual(ahead, 3 * pictures.AHEAD)
        self.no_thread_left()

    def test_the_threads_never_outnumber_the_cores_this_process_may_use(self):
        from unittest import mock
        with mock.patch.object(pictures.os, "sched_getaffinity", lambda pid: {0, 1, 2}, create=True), \
                mock.patch.object(pictures, "_quota", lambda: None):
            self.assertEqual((pictures.cores(), pictures.threads()), (3, 3))
        with mock.patch.object(pictures.os, "sched_getaffinity", lambda pid: set(range(64)), create=True), \
                mock.patch.object(pictures, "_quota", lambda: 1.5):
            # A container's quota of 1.5 cores: two threads, never the machine's 64.
            self.assertEqual((pictures.cores(), pictures.threads()), (2, 2))
        with mock.patch.object(pictures.os, "sched_getaffinity", lambda pid: set(range(64)), create=True), \
                mock.patch.object(pictures, "_quota", lambda: None):
            self.assertEqual((pictures.cores(), pictures.threads()), (64, pictures.THREADS))


if __name__ == "__main__":
    unittest.main()
