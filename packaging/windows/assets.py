"""Make the pictures and the version file the Windows build needs, from the launcher's own drawing code.

  python packaging/windows/assets.py OUT_DIR VERSION

Writes openDMT3.ico (the program and installer icon), splash.png (shown while Velopack updates), setup-splash.png
(shown while the installer unpacks itself), and version.txt and setup-version.txt (the file properties Windows
shows for the launcher and the installer).
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from PIL import ImageDraw, ImageFont  # noqa: E402

from opendmt3.client import art, theme  # noqa: E402


def icon(path):
    """The mark at every size Windows asks for, from 16 to 256 pixels."""
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    # Each size is drawn on its own (not scaled from the largest), so small ones stay sharp.
    images = [art.mark(s) for s in sizes]
    images[-1].save(path, format="ICO", sizes=[(s, s) for s in sizes], append_images=images[:-1])


def splash(path, version):
    """The picture shown while openDMT3 installs or updates: the title screen's shards, the name in chrome."""
    width, height = 720, 400
    img = art.shards(width, height, seed=19).convert("RGBA")
    mark = art.logo(300, 1.4)
    img.alpha_composite(mark, (54, 118))
    small = ImageFont.truetype(theme.WIDE_FILE, 13)
    draw = ImageDraw.Draw(img)
    draw.text((60, 120 + mark.height + 14), "TECHNIKA 3  ·  %s" % version, font=small, fill=theme.MUTED)
    img.convert("RGB").save(path)


def setup_splash(path, version):
    """The installer's first picture, shown while its one file unpacks itself: the splash, smaller."""
    width, height = 560, 312
    img = art.shards(width, height, seed=19).convert("RGBA")
    mark = art.logo(240, 1.1)
    img.alpha_composite(mark, (42, 92))
    small = ImageFont.truetype(theme.WIDE_FILE, 11)
    draw = ImageDraw.Draw(img)
    draw.text((46, 94 + mark.height + 12), "SETUP  ·  %s" % version, font=small, fill=theme.MUTED)
    img.convert("RGB").save(path)


def version_file(path, version, description="openDMT3 launcher for TECHNIKA 3"):
    """PyInstaller's version resource: what Explorer shows under the program's Properties > Details."""
    parts = (version.split("+")[0].split(".") + ["0", "0", "0"])[:4]
    numbers = ", ".join(str(int(p)) for p in parts)
    text = """VSVersionInfo(
  ffi=FixedFileInfo(filevers=(%(n)s), prodvers=(%(n)s), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                    subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'openDMT3'),
    StringStruct('FileDescription', '%(d)s'),
    StringStruct('FileVersion', '%(v)s'),
    StringStruct('LegalCopyright', 'MIT License'),
    StringStruct('ProductName', 'openDMT3'),
    StringStruct('ProductVersion', '%(v)s')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
""" % {"n": numbers, "v": version, "d": description}
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    out, version = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    icon(os.path.join(out, "openDMT3.ico"))
    splash(os.path.join(out, "splash.png"), version)
    setup_splash(os.path.join(out, "setup-splash.png"), version)
    version_file(os.path.join(out, "version.txt"), version)
    version_file(os.path.join(out, "setup-version.txt"), version, "openDMT3 setup")


if __name__ == "__main__":
    main()
