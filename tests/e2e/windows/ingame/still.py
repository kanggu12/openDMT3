"""Whether the game's picture held still between two screenshots (tests/e2e/windows/ingame.sh): the middle half of
the screen, where the in-game layer never draws, byte for byte the same in both.

    python3 still.py FIRST.bmp SECOND.bmp

Plain Python, 24-bit BMP files only (picture.py's reader). Prints how many of the middle half's pixels differ."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from picture import bmp  # noqa: E402


def main(first, second):
    a, b = bmp(first), bmp(second)
    w, h = a[0], a[1]
    differ = 0
    for y in range(h // 4, 3 * h // 4):
        ra, rb = a[2][y][3 * (w // 4):3 * (3 * w // 4)], b[2][y][3 * (w // 4):3 * (3 * w // 4)]
        if ra != rb:
            differ += sum(1 for x in range(0, len(ra), 3) if ra[x:x + 3] != rb[x:x + 3])
    print("  the middle half: %d of %d pixels differ between the two screenshots" % (differ, (w // 2) * (h // 2)))
    sys.exit(0 if differ == 0 else 1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
