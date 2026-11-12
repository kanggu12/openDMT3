"""The product's mark for the in-game bar, drawn by the launcher's own code (opendmt3.client.art.logo) so the bar
shows the same picture the launcher shows, never letters set in the mark's face.

    python native/cardreader/mark.py OUT_FILE

build.sh runs it (in the launcher's UI test image, which has Pillow and the fonts) before it builds the DLL, which
carries the file as a resource (post.rc). The file: its width and height as two little-endian 32-bit numbers, then its
pixels row after row from the top, each a little-endian 32-bit 0xAARRGGBB premultiplied by its opacity (the layer's
canvases, paint.h). The mark is drawn without the launcher's label or version, at 2.25 times the launcher's size, so the
bar's at 4K (2160 lines) is still drawn smaller from it, and cut to what it draws.
"""

import os
import struct
import sys

# The repository's root on the path, so the launcher's code is found wherever this runs from.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from opendmt3.client import art, theme  # noqa: E402

# The launcher's size times this: the bar at 4K is 46 * 2.8125 = 129 pixels tall, under this picture's 134.
SCALE = 2.25


def picture():
    """The mark as the launcher draws it, without its label, as wide as its own DMT3 needs: an RGBA picture."""
    # DMT3 at the launcher's full size (44 at 1x), and the width that just holds it (logo() makes the name as large as
    # the width allows beside its label; with no label, the label's room is its 6 pixels of gap).
    size = int(round(44 * SCALE))
    big, _ = art.chrome_text([("DMT", art.CHROME), ("3", art.lit_chrome(theme.BLUE_HI))], size, SCALE)
    img = art.logo(big.width + int(6 * SCALE), SCALE, label="")
    # Cut to what it draws (logo() leaves room for the face's ascent and descent).
    return img.crop(img.getbbox())


def premultiplied(img):
    """The picture's pixels as the layer's canvases hold them: 0xAARRGGBB, each colour times its opacity."""
    out = bytearray()
    for r, g, b, a in img.getdata():
        # Rounded to the nearest, as the layer's own drawing blends.
        pr, pg, pb = (r * a + 127) // 255, (g * a + 127) // 255, (b * a + 127) // 255
        out += struct.pack("<I", (a << 24) | (pr << 16) | (pg << 8) | pb)
    return bytes(out)


def main(path):
    img = picture().convert("RGBA")
    with open(path, "wb") as f:
        # The size first, then the rows.
        f.write(struct.pack("<II", img.width, img.height))
        f.write(premultiplied(img))
    print("the mark: %dx%d -> %s" % (img.width, img.height, path))


if __name__ == "__main__":
    main(sys.argv[1])
