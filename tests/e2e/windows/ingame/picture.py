"""The in-game post-process chain's frames against each other and against the screen (tests/e2e/windows/ingame.sh).

    python3 picture.py OUT_DIR

OUT_DIR holds the chain's measuring dump of one frame ("e2e": the game's picture, every filter and anti-aliasing pass,
and the frame as presented), the screen captured after it (screen-e2e.bmp) and the game's picture just before that
capture and just after it ("e2e1-src", "e2e2-src"). Passes when:
  - the presented frame is byte for byte the chain's SMAA High then FSR 1 (the options the test chose);
  - FSR 1 differs from bilinear on the same frame (a known difference: it sharpens), and so does Anime4K (its
    network's picture, enlarged twice, then fitted to the window; bilinear in its place would differ by nothing: 0.42
    a byte on the title screen at 1920x1080, where FSR 1 differs by 0.79);
  - where the game's picture held still over the three frames, the screen shows the chain's output, closer to it
    than to bilinear (the screen is a later frame than the dump, so only still parts can be compared; a part of the
    game that pulses can show alike in two frames a pulse apart, so the two beside the capture are held to as well).
Plain Python (the test image has no imaging library): 24-bit BMP files only.
"""
import struct
import sys

# The game's own picture size (native/cardreader/logic.h GAME_W, GAME_H).
GAME_W, GAME_H = 1280, 768


def bmp(path):
    """A 24-bit BMP: (width, height, rows top first, each a bytes object of b, g, r triples)."""
    data = open(path, "rb").read()
    offset = struct.unpack_from("<I", data, 10)[0]
    w, h = struct.unpack_from("<ii", data, 18)
    bits = struct.unpack_from("<H", data, 28)[0]
    if bits != 24:
        raise SystemExit("%s: %d bits a pixel, not 24" % (path, bits))
    row = (w * 3 + 3) & ~3
    # A positive height is stored bottom row first.
    rows = [data[offset + (abs(h) - 1 - y if h > 0 else y) * row:][:w * 3] for y in range(abs(h))]
    return w, abs(h), rows


def mean_diff(a, b, points):
    """Mean absolute difference a byte over the given (x, y) pixels."""
    total = 0
    for x, y in points:
        ra, rb = a[2][y], b[2][y]
        for i in range(3 * x, 3 * x + 3):
            total += abs(ra[i] - rb[i])
    return total / (3.0 * max(1, len(points)))


def main(out):
    shown, chain = bmp(out + "/e2e-out.bmp"), bmp(out + "/e2e-aa-smaa-high.bmp")
    w, h = shown[0], shown[1]
    same = shown[2] == chain[2]
    print("  the presented frame is SMAA High then FSR 1 at 80: %s (%dx%d)" % (same, w, h))
    fsr, smooth = bmp(out + "/e2e-up-fsr1.bmp"), bmp(out + "/e2e-up-smooth.bmp")
    # Every 4th pixel of the middle half: enough to see a sharpening filter's difference.
    middle = [(x, y) for y in range(h // 4, 3 * h // 4, 4) for x in range(w // 4, 3 * w // 4, 4)]
    d = mean_diff(fsr, smooth, middle)
    print("  FSR 1 against bilinear on the same frame: %.2f a byte" % d)
    a4k = mean_diff(bmp(out + "/e2e-up-anime4k.bmp"), smooth, middle)
    print("  Anime4K against bilinear on the same frame: %.2f a byte" % a4k)
    # The game's picture where it held still: a game pixel and its eight neighbours equal in the dumped frame, in the
    # frame just before the screen was captured and in the frame just after it.
    a = bmp(out + "/e2e-src.bmp")
    later = [bmp(out + "/e2e1-src.bmp"), bmp(out + "/e2e2-src.bmp")]
    still = set()
    for y in range(1, GAME_H - 1):
        for x in range(1, GAME_W - 1):
            if all(a[2][y + dy][3 * (x - 1):3 * (x + 2)] == b[2][y + dy][3 * (x - 1):3 * (x + 2)]
                   for b in later for dy in (-1, 0, 1)):
                still.add((x, y))
    # The screen's pixels over still game pixels, every 2nd, away from where the in-game layer may draw (its bar, toast
    # and panels in the top fifth, its frame rate chip in the game's bottom band: native/cardreader/logic.c fps_box,
    # from line 742 of 768, so every row from line 736 down is left out).
    screen = bmp(out + "/screen-e2e.bmp")
    band_y = h * 736 // GAME_H
    points = []
    for y in range(h // 5, band_y, 2):
        for x in range(0, w, 2):
            gx, gy = int((x + 0.5) * GAME_W / w), int((y + 0.5) * GAME_H / h)
            if (gx, gy) in still:
                points.append((x, y))
    to_chain, to_smooth = mean_diff(screen, shown, points), mean_diff(screen, smooth, points)
    print("  the screen where the game held still (%d pixels): %.2f a byte from the chain's output, %.2f from bilinear"
          % (len(points), to_chain, to_smooth))
    ok = same and d > 0.3 and a4k > 0.1 and len(points) > 1000 and to_chain < 2.0 and to_chain < to_smooth
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main(sys.argv[1])
