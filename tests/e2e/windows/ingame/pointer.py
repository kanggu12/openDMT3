"""The pointer's picture on the virtual screen, through XFixes: its size, its hot spot, and how much of it is the
dart's blue core and its chrome edge (python3-xlib, in the image from this folder's Dockerfile).

    python3 pointer.py OUT_PNG

Prints one line: "pointer WxH hot X,Y opaque N blue B chrome C" and saves the picture over a mid grey.
"""
import sys

from Xlib import display


def main(out):
    d = display.Display()
    # The extension's requests come with the display once the server is asked for it.
    d.xfixes_query_version()
    image = d.xfixes_get_cursor_image(d.screen().root)
    w, h = image.width, image.height
    # Each pixel is a 32-bit ARGB number (premultiplied, as X keeps cursors).
    pixels = list(image.cursor_image)
    opaque = blue = chrome = 0
    for p in pixels:
        a, r, g, b = (p >> 24) & 255, (p >> 16) & 255, (p >> 8) & 255, p & 255
        if a < 200:
            continue
        opaque += 1
        # The core's blue: blue well above red (the dart's core runs from a lit cyan-blue to a deep blue).
        if b > 150 and b > r + 60:
            blue += 1
        # The chrome: bright and grey (the three channels close together).
        if min(r, g, b) > 170 and max(r, g, b) - min(r, g, b) < 30:
            chrome += 1
    try:
        from PIL import Image
        img = Image.new("RGB", (w, h), (128, 128, 128))
        for i, p in enumerate(pixels):
            a = ((p >> 24) & 255) / 255.0
            r, g, b = (p >> 16) & 255, (p >> 8) & 255, p & 255
            img.putpixel((i % w, i // w), tuple(int(c + 128 * (1 - a)) for c in (r, g, b)))
        img.resize((w * 4, h * 4)).save(out)
    except ImportError:
        pass
    print("pointer %dx%d hot %d,%d opaque %d blue %d chrome %d" % (w, h, image.xhot, image.yhot, opaque, blue, chrome))


if __name__ == "__main__":
    main(sys.argv[1])
