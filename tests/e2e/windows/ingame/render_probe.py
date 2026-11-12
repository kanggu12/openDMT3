"""Where render_probe.exe's colours landed in the frame as the game drew it (tests/e2e/windows/render.sh): the chain's
measuring dumps of it (probe-src.bmp, and after-src.bmp after a device reset), drawn at the render size W x H, each of
the probe's 1280x768 places turned to it.

    python3 render_probe.py DUMP_DIR W H

Passes when each frame is W x H and:
  - the red quarter (0,0 to 640,384 of the game's pixels, drawn through its projection, then copied into its texture
    and drawn back from it) covers exactly the top-left quarter of the larger frame;
  - the green quarter (640,384 to 1280,768) the bottom-right one;
  - the yellow square of screen-space vertices (1152,0 to 1280,128) the same part of the larger frame, its edges within
    a pixel of where the game's would land, not 128 of the larger frame's pixels at its top-right corner;
  - the rest is the blue the frame was cleared with.
Plain Python (the test image has no imaging library): 24-bit BMP files only (picture.py's reader).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from picture import bmp  # noqa: E402

# The game's own picture size.
GAME_W, GAME_H = 1280, 768
RED, GREEN, BLUE, YELLOW = (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)


def colour(frame, x, y):
    """A pixel's (red, green, blue): the BMP's rows hold blue, green, red."""
    row = frame[2][y]
    return row[3 * x + 2], row[3 * x + 1], row[3 * x]


def main(dump, w, h):
    ok = 1
    # The frame before the reset and the one after it, each held to the same places.
    for label in ("probe", "after"):
        path = os.path.join(dump, label + "-src.bmp")
        if not os.path.exists(path):
            print("  no %s: the chain did not write that frame" % os.path.basename(path))
            ok = 0
            continue
        ok &= places(bmp(path), label, w, h)
    return 0 if ok else 1


def places(frame, label, w, h):
    """Whether one dumped frame has the probe's parts in their places at W x H (one line a finding)."""
    ok = frame[0] == w and frame[1] == h
    print("  %s: the frame as drawn: %dx%d (the render size %dx%d)" % (label, frame[0], frame[1], w, h))
    if not ok:
        return 0
    sx, sy = w / GAME_W, h / GAME_H
    # Each place's edges turned to the larger frame (the viewport's sum: x by the width's ratio, y by the height's).
    place = lambda x0, y0, x1, y1: (round(x0 * sx), round(y0 * sy), round(x1 * sx), round(y1 * sy))
    checks = [("red", place(0, 0, 640, 384), RED), ("green", place(640, 384, 1280, 768), GREEN),
              ("yellow", place(1152, 0, 1280, 128), YELLOW)]
    for name, (x0, y0, x1, y1), want in checks:
        # Inside: a pixel a little in from each corner and the middle; outside: a pixel two out from each edge that
        # touches the cleared blue.
        inside = [(x0 + 2, y0 + 2), (x1 - 3, y0 + 2), (x0 + 2, y1 - 3), (x1 - 3, y1 - 3),
                  ((x0 + x1) // 2, (y0 + y1) // 2)]
        held = all(colour(frame, x, y) == want for x, y in inside)
        print("  %s: %s inside %d,%d to %d,%d" % (name, "as drawn" if held else "NOT as drawn", x0, y0, x1, y1))
        ok &= held
    # The blue around the yellow square: two pixels left of it and two below it; and the top-right quarter's middle.
    yx0, yy0, yx1, yy1 = place(1152, 0, 1280, 128)
    around = [(yx0 - 2, yy1 // 2), ((yx0 + yx1) // 2, yy1 + 2), (round(960 * sx), round(260 * sy))]
    blue = all(colour(frame, x, y) == BLUE for x, y in around)
    print("  the cleared blue beside the yellow square and in the top-right quarter: %s" % ("yes" if blue else "no"))
    ok &= blue
    return ok


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3])))
