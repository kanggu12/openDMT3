"""A frame dumped after the game's window was dragged to a new size (tests/e2e/windows/ingame.sh): the picture follows.

    python3 resize.py OUT_DIR LABEL CLIENT_W CLIENT_H

The chain's measuring dump wrote LABEL-src.bmp (the game's own frame, as it drew it) and LABEL-out.bmp (the chain's
output, before the layer). Passes when the output is the window's new client size, and the game's frame is in it at
the picture's place for that size (its own 5:3 shape kept, bars beside it), enlarged or shrunk to it: the output,
read at every fourth pixel of the picture, is within 22 dB PSNR of the game's frame resized there with a plain
bilinear filter (the chosen filter, FSR 1 say, sharpens a little more, never moves anything), and the bars are dark.
A stale picture (the old size's, cut or stretched) is far from it. Plain Python, 24-bit BMP files only.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from layer import picture  # noqa: E402
from picture import bmp  # noqa: E402


def sample(src, x, y):
    """The game's frame at a point in its own pixels, bilinear (b, g, r)."""
    w, h, rows = src
    x = min(max(x, 0.0), w - 1.0)
    y = min(max(y, 0.0), h - 1.0)
    x0, y0 = int(x), int(y)
    x1, y1 = min(x0 + 1, w - 1), min(y0 + 1, h - 1)
    fx, fy = x - x0, y - y0
    out = []
    for c in range(3):
        a = rows[y0][3 * x0 + c] * (1 - fx) + rows[y0][3 * x1 + c] * fx
        b = rows[y1][3 * x0 + c] * (1 - fx) + rows[y1][3 * x1 + c] * fx
        out.append(a * (1 - fy) + b * fy)
    return out


def main():
    out_dir, label, cw, ch = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    src = bmp(os.path.join(out_dir, label + "-src.bmp"))
    out = bmp(os.path.join(out_dir, label + "-out.bmp"))
    problems = []
    if (out[0], out[1]) != (cw, ch):
        problems.append("the output is %dx%d, the window's client %dx%d" % (out[0], out[1], cw, ch))
        print("FAIL: " + "; ".join(problems))
        return 1
    px, py, pw, ph = picture(cw, ch, False)
    # The picture: every fourth pixel against the game's frame resized to the picture's size (pixel centres matched).
    err, n = 0.0, 0
    for y in range(py + 2, py + ph - 2, 4):
        row = out[2][y]
        for x in range(px + 2, px + pw - 2, 4):
            want = sample(src, (x - px + 0.5) * src[0] / pw - 0.5, (y - py + 0.5) * src[1] / ph - 0.5)
            for c in range(3):
                d = row[3 * x + c] - want[c]
                err += d * d
                n += 1
    psnr = 10 * math.log10(255.0 ** 2 / max(err / max(n, 1), 1e-9))
    if psnr < 22.0:
        problems.append("the picture is not the game's frame at %dx%d (PSNR %.1f dB against it resized)" % (pw, ph, psnr))
    # The bars beside it (when the client is not of the game's shape): dark.
    bars = [(x, y) for y in range(0, ch, 8) for x in range(0, cw, 8) if not (px <= x < px + pw and py <= y < py + ph)]
    if bars:
        light = max(max(out[2][y][3 * x:3 * x + 3]) for x, y in bars)
        if light > 24:
            problems.append("a bar beside the picture is not dark (%d)" % light)
    print("  the window's client %dx%d: the picture %dx%d at %d,%d, %.1f dB PSNR against the game's frame resized there"
          % (cw, ch, pw, ph, px, py, psnr))
    if problems:
        print("FAIL: " + "; ".join(problems))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
