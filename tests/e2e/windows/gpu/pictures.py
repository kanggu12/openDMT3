#!/usr/bin/env python3
"""One build's pictures held against another's: the chain's measuring dumps of the same frames (measure.sh's pictures
runs, OPENDMT3_POSTFX_DUMP_AT), file by file. The game's own frame (*-src.bmp) must be the same in both, or the two runs
did not show the same picture and nothing after it is compared. For every other file: the pixels that differ, the
largest difference in any channel (0 to 255) and the PSNR over the whole picture (inf when identical).

    python3 pictures.py A_DIR B_DIR
Exit 0 when every file is the same to the pixel, 1 when any differs (the table says by how much), 2 when the two runs'
frames were not the same picture.
"""
import math
import os
import sys

import numpy as np
from PIL import Image


def load(path):
    """A dump as an array of its red, green and blue (the dumps are 24- or 32-bit BMPs; alpha is not the picture's)."""
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"), dtype=np.int16)


def compare(a, b):
    """(pixels that differ, their share in %, the largest channel difference, PSNR in dB)."""
    d = np.abs(a - b)
    # A pixel differs when any of its channels does.
    differ = int(np.count_nonzero(d.max(axis=2)))
    mse = float(np.mean(d.astype(np.float64) ** 2))
    psnr = math.inf if mse == 0 else 10 * math.log10(255.0 ** 2 / mse)
    return differ, 100.0 * differ / (a.shape[0] * a.shape[1]), int(d.max()), psnr


def main(argv):
    a_dir, b_dir = argv[0], argv[1]
    names = sorted(n for n in os.listdir(a_dir) if n.endswith(".bmp") and os.path.exists(os.path.join(b_dir, n)))
    if not names:
        print("no dumps in common")
        return 2
    # The game's own frames first: the same picture in both runs, or nothing else means anything.
    for n in names:
        if n.endswith("-src.bmp"):
            differ, _, top, _ = compare(load(os.path.join(a_dir, n)), load(os.path.join(b_dir, n)))
            print("%s: the game's frame %s" % (n, "the same in both" if differ == 0 else
                                               "differs (%d px, by up to %d): not the same picture" % (differ, top)))
            if differ:
                return 2
    print("| Dump | Pixels that differ | Share | Largest difference | PSNR (dB) |")
    print("|---|---|---|---|---|")
    worst = 0
    for n in names:
        if n.endswith("-src.bmp"):
            continue
        a, b = load(os.path.join(a_dir, n)), load(os.path.join(b_dir, n))
        if a.shape != b.shape:
            print("| %s | sizes differ %s and %s | | | |" % (n, a.shape[:2], b.shape[:2]))
            worst = max(worst, 255)
            continue
        differ, share, top, psnr = compare(a, b)
        worst = max(worst, top)
        print("| %s | %d | %.4f %% | %d | %s |" % (n, differ, share, top, "inf" if psnr == math.inf else "%.1f" % psnr))
    return 0 if worst == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
