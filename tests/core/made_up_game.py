"""A made-up game folder with every family of the game's files a server reads, in layers as the game keeps them, for
the tests of the layers (test_layers.py) and of the song list (tests/server/test_songlist.py, test_sources.py):
archives written with a random table (FolderCase), tables shaped like the game's, PNG pictures drawn here. Nothing in
it is the game's.

The song list is in the base and in two patches, the newest of which (patch 01) has one song more; the base's stage
list offers all three songs; one song's jacket is only in a patch; a newer experience table is in a patch of the
script family; a patch of the script family is another build's (written with another table, so this reader cannot
open it). No file of a whole game folder is one: that patch is for the reader's refusal, never called damaged.
"""

import io
import os
import random

from opendmt3.core import game as g
from opendmt3.core.formats import discstock, pak
from tests.core.test_setup import FolderCase

HEADER = "no\tname\tFullName\tGenre\tComposer\tStar_1\tStar_2\tStar_3\tStar_4\tPop_1\tPop_2\tPop_3\tPop_4\r\n"
# The songs each layer's list has: (number, internal name, title). The newest has a third song.
BASE_SONGS = ((1, "alpha", "Made-up Alpha"), (2, "beta", "Made-up Beta"))
OLDER_SONGS = ((1, "alpha", "Made-up Alpha (older)"),)
NEWEST_SONGS = BASE_SONGS + ((3, "gamma", "Made-up Gamma"),)
# The base's stage list (POP's first stage): it offers all three songs, gamma first (a song only the newest list has,
# as a stage list of the game may name one), none of their patterns hidden. A row of the song list that no table of
# the game's modes names is never offered, so the card would not count it.
STAGE_LIST = b"stage1,songname,SP,PT,Hid\r\n3,gamma,2,1,0\r\n1,alpha,2,1,0\r\n2,beta,1,1,0\r\n"


def song_list(rows):
    """A song list as the game keeps it (UTF-16, tab-separated, the columns the reader takes)."""
    lines = "".join("%d\t%s\t%s\tPop\tComposer %d\t2\t5\t9\t0\t3\t6\t10\t12\r\n" % (n, name, title, n)
                    for n, name, title in rows)
    return (HEADER + lines).encode("utf-16")


def png(width, height, colour=(200, 40, 120, 255)):
    """A real PNG of this size in one colour (Pillow), with a gamma chunk and some text that the server's one form
    drops; None without Pillow."""
    try:
        from PIL import Image
        from PIL.PngImagePlugin import PngInfo
    except ImportError:
        return None
    info = PngInfo()
    # Something that is not pixels: kept by the game's file, gone from the server's one form.
    info.add_text("made", "by a test")
    out = io.BytesIO()
    Image.new("RGBA", (width, height), colour).save(out, "PNG", pnginfo=info)
    return out.getvalue()


def table(*lines):
    """A table as the game writes most of them: plain text, commas, Windows line ends."""
    return "".join(line + "\r\n" for line in lines).encode("ascii")


def unreadable(path, files, rng):
    """An archive written with another table than the folder's client holds, as another build of the game would write
    it: this reader cannot open it with the folder's table (pak.PakUnreadable)."""
    other = bytes(random.Random(99).randrange(256) for _ in range(256))
    template = pak.Header(0x01020304, 0, 2, 0, 0, 0x36, 1, 0)
    key_field = (0x2222).to_bytes(4, "little") + bytes(4)
    pak.write_pak(path, files, other, 0x3C, key_field, template, bytes(32),
                  seed_source=lambda n: rng.randrange(1 << 32).to_bytes(n, "little"))


class GameCase(FolderCase):
    """FolderCase with the song list's, the jackets' and the DJ cards' families, each in layers."""

    def setUp(self):
        super().setUp()
        self.pack = os.path.join(self.game.root, "pack")
        self.write_game()
        # Found again: the folder's file list changed after FolderCase found it.
        self.game = g.Game.find(self.tmp)
        self.data = os.path.join(self.tmp, "data")

    def write_game(self):
        pack = self.pack
        # The song list: the base, an older patch, and the newest patch the reader must take.
        self._pak(os.path.join(pack, "DiscInfo.pak"), {discstock.PATH: song_list(BASE_SONGS),
                                                      "Resource\\DiscInfo\\pop_stage_1.csv": STAGE_LIST})
        self._pak(os.path.join(pack, "DiscInfo00.pak"), {discstock.PATH: song_list(OLDER_SONGS)})
        self._pak(os.path.join(pack, "DiscInfo01.pak"), {discstock.PATH: song_list(NEWEST_SONGS)})
        # Jackets: the first two songs' in the base (at the game's size), the third's only in a patch.
        self._pak(os.path.join(pack, "DiscImg.pak"), {
            "Resource\\DiscImg\\alpha_0.png": png(256, 256), "Resource\\DiscImg\\beta_0.png": png(256, 256, (9, 9, 200, 255))})
        self._pak(os.path.join(pack, "DiscImg00.pak"), {"Resource\\DiscImg\\gamma_0.png": png(256, 256, (9, 200, 9, 255))})
        levels = "이름\t표시숫자\t경험치\tBackImage\tNumberImage\r\nDJ Lv.2\t2\t42\t0.png\tn.png\r\nDJ Lv.1\t1\t12\t0.png\tn.png\r\n"
        self._pak(os.path.join(pack, "Script.pak"), {
            "Resource\\Script\\Uidata\\icon.csv": table("Index,path,file,grade", "0,resource/icon/,nocard.png,-",
                                                        "1,resource/icon/,basic.png,", "6,resource/icon/,s001.png,S"),
            "Resource\\Script\\Uidata\\UserTitlePlate.csv": table(
                "Index,filePath,fileName,grade", "32768,Resource/emblem/plate\\,basic.png,",
                "32769,Resource\\emblem\\plate\\reward\\,1.png,"),
            "Resource\\Script\\Uidata\\UserTitlePattern.csv": table(
                "Index,filePath,fileName,grade", "7,resource/Emblem/pattern/,a01.png,A"),
            "Resource\\Script\\Item\\ResultExpPoint.csv": table("Level,S++,S+,S,A++,A+,A,B,C,F", "1,7,7,7,6,6,6,5,5,1"),
            "Resource\\Script\\Uidata\\expTitle.csv": b"\xff\xfe" + levels.encode("utf-16-le"),
        })
        # A newer experience table in a patch: the reader takes this one.
        self._pak(os.path.join(pack, "Script00.pak"), {
            "Resource\\Script\\Item\\ResultExpPoint.csv": table("Level,S++,S+,S,A++,A+,A,B,C,F", "1,10,10,10,9,9,9,8,8,1",
                                                                "2,11,10,10,10,9,9,9,8,1")})
        # A patch of another build (written with another table): this reader cannot open it with the folder's table.
        self.unreadable(os.path.join(pack, "Script01.pak"),
                        {"Resource\\Script\\Item\\ResultExpPoint.csv": table("Level,A", "1,99")})
        self._pak(os.path.join(pack, "Icon.pak"), {"Resource\\Icon\\nocard.png": png(104, 64, (1, 1, 1, 255)),
                                                   "Resource\\Icon\\basic.png": png(104, 64, (2, 2, 2, 255))})
        self._pak(os.path.join(pack, "emblem.pak"), {
            "Resource\\emblem\\plate\\basic.png": png(204, 64, (3, 3, 3, 255)),
            "Resource\\emblem\\plate\\reward\\1.png": png(204, 64, (4, 4, 4, 255)),
            "Resource\\emblem\\pattern\\a01.png": png(204, 64, (5, 5, 5, 255))})

    def unreadable(self, path, files):
        unreadable(path, files, self.rng)

    def cut(self, name, keep):
        """Cut one of the game's files short, keeping its first `keep` bytes (a half-copied file)."""
        path = os.path.join(self.pack, name)
        with open(path, "rb") as f:
            data = f.read()
        with open(path, "wb") as f:
            f.write(data[:keep] if keep >= 0 else data[:len(data) + keep])
