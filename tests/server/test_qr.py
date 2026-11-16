"""The invite's QR code (opendmt3/server/services/qr.py): the same modules as a reference encoder makes, its fixed
patterns where a reader looks for them, and its forms for the site and the terminal."""

import hashlib
import unittest

from opendmt3.server.services import qr

# Each code's modules, row by row as 1s and 0s, hashed: the matrices python-qrcode 8.2 makes for the same text, version
# 1 to 10, level M, byte mode and mask (every one of 248 such matrices was compared whole when the encoder was made).
REFERENCE = {("http://192.168.0.5:4730/", 3): "ef86f036ba87ccb0e46618f52f7aa3b313b7ac642a8901421218004c8c3af7ad",
             ("https://" + "y" * 120 + "/", 5): "98ba0989d1c39403bf90ca7bde24edb9ae5c8cfe641d0b5f588e3fcf81c51f85",
             ("https://" + "z" * 200 + "/", 1): "ca11daec6828fedff83da7ef241c45454d901448d1641b8982b91bb231c95d61"}


def hashed(grid):
    """A matrix as the reference's hash."""
    return hashlib.sha256("".join("1" if m else "0" for row in grid for m in row).encode()).hexdigest()


class QRTest(unittest.TestCase):
    def test_the_modules_are_the_reference_encoders(self):
        for (text, mask), expected in REFERENCE.items():
            with self.subTest(length=len(text), mask=mask):
                self.assertEqual(hashed(qr.encode(text, mask=mask)), expected)

    def test_the_smallest_version_that_holds_the_text(self):
        # Level M in byte mode: version 1 holds 14 bytes, 2 holds 26, 10 holds 213.
        self.assertEqual(qr.version_for(b"x" * 14), 1)
        self.assertEqual(qr.version_for(b"x" * 15), 2)
        self.assertEqual(qr.version_for(b"x" * 213), 10)
        with self.assertRaises(qr.QRError):
            qr.version_for(b"x" * 214)

    def test_the_finder_patterns_are_in_three_corners(self):
        grid = qr.encode("http://192.168.0.5:4730/")
        size = len(grid)
        self.assertEqual(size, 25)
        finder = [[max(abs(r - 3), abs(c - 3)) != 2 for c in range(7)] for r in range(7)]
        for top, left in ((0, 0), (0, size - 7), (size - 7, 0)):
            self.assertEqual([row[left:left + 7] for row in grid[top:top + 7]], finder)
        # The dark module beside the lower finder is always dark.
        self.assertTrue(grid[size - 8][8])

    def test_the_svg_is_dark_on_white_with_its_quiet_zone(self):
        picture = qr.svg("http://192.168.0.5:4730/")
        self.assertTrue(picture.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 33 33"'))
        self.assertIn('fill="#fff"', picture)
        self.assertIn('fill="#000"', picture)

    def test_the_terminal_form_has_a_line_for_every_two_rows(self):
        lines = qr.terminal("http://192.168.0.5:4730/").splitlines()
        # 25 modules and 4 of quiet zone on each side: 33 wide, 17 lines of two rows (the last with a light one).
        self.assertEqual(len(lines), 17)
        self.assertEqual({len(line) for line in lines}, {33})
        # The quiet zone's first two rows are light: whole lit cells.
        self.assertEqual(lines[0], "█" * 33)


if __name__ == "__main__":
    unittest.main()
