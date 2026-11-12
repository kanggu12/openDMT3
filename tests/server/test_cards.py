"""Tests for the DJ card's tables and pictures (services/cards.py), on a made-up game folder: archives written here
with tables shaped like the game's and pictures drawn here (Pillow), kept in the server's one form."""

import os
import unittest

from opendmt3.core import game as g
from opendmt3.server.services import cards, pictures
from tests.core.made_up_game import png, unreadable
from tests.core.test_setup import FolderCase


def picture(number):
    """A DJ card picture of its kind's size, its colour from its number (so each is its own)."""
    return png(104 if number < 100 else 204, 64, (number % 256, number // 256 % 256, 99, 255))


def table(*lines):
    """A table as the game writes most of them: plain text, commas, Windows line ends."""
    return "".join(line + "\r\n" for line in lines).encode("ascii")


@unittest.skipUnless(pictures.available(), "needs Pillow")
class CardsImportTest(FolderCase):
    def setUp(self):
        super().setUp()
        pack = os.path.join(self.game.root, "pack")
        levels = "이름\t표시숫자\t경험치\tBackImage\tNumberImage\r\nDJ Lv.2\t2\t42\t0.png\tn.png\r\nDJ Lv.1\t1\t12\t0.png\tn.png\r\n"
        # The script archive's tables (kept: a test writes them again with more icons).
        self.tables = {
            # The icons: 0 the no-card one, 1 the basic one, 6 an S-grade one whose picture is missing.
            "Resource\\Script\\Uidata\\icon.csv": table("Index,path,file,grade", "0,resource/icon/,nocard_djicon.png,-",
                                                        "1,resource/icon/,dj_icon_basic.png,", "6,resource/icon/,s001.png,S"),
            # Plates with both slashes in their folders, as the game's table has them.
            "Resource\\Script\\Uidata\\UserTitlePlate.csv": table(
                "Index,filePath,fileName,grade", "32768,Resource/emblem/usertitleplate\\,basic_tbg.png,",
                "32769,Resource\\emblem\\usertitleplate\\reward\\,1.png,"),
            "Resource\\Script\\Uidata\\UserTitlePattern.csv": table(
                "Index,filePath,fileName,grade", "7,resource/Emblem/usertitlepattern/,a_dp_01.png,A"),
            "Resource\\Script\\Item\\ResultExpPoint.csv": table("Level,S++,S+,S,A++,A+,A,B,C,F", "0,0,0,0,0,0,0,0,0,0",
                                                                "1,7,7,7,6,6,6,5,5,1"),
            # The levels in UTF-16 with tabs, as the game keeps this one (and out of order: they are sorted).
            "Resource\\Script\\Uidata\\expTitle.csv": b"\xff\xfe" + levels.encode("utf-16-le"),
        }
        self._pak(os.path.join(pack, "Script.pak"), self.tables)
        # A later script archive replaces one table: the experience points.
        self._pak(os.path.join(pack, "Script00.pak"), {
            "Resource\\Script\\Item\\ResultExpPoint.csv": table("Level,S++,S+,S,A++,A+,A,B,C,F", "1,10,10,10,9,9,9,8,8,1",
                                                                "2,11,10,10,10,9,9,9,8,1")})
        # A numbered patch this reader cannot open (another build's: written with another table) is left out, never
        # called damaged.
        unreadable(os.path.join(pack, "Script01.pak"),
                   {"Resource\\Script\\Item\\ResultExpPoint.csv": table("Level,A", "1,99")}, self.rng)
        self._pak(os.path.join(pack, "Icon.pak"), {"Resource\\Icon\\nocard_djicon.png": picture(0),
                                                   "Resource\\Icon\\dj_icon_basic.png": picture(1)})
        self._pak(os.path.join(pack, "emblem.pak"), {
            "Resource\\emblem\\usertitleplate\\basic_tbg.png": picture(32768),
            "Resource\\emblem\\usertitleplate\\reward\\1.png": picture(32769),
            "Resource\\emblem\\usertitlepattern\\a_dp_01.png": picture(7)})
        # Found again: the folder's file list changed after FolderCase found it.
        self.game = g.Game.find(self.tmp)
        self.data = os.path.join(self.tmp, "data")

    def test_the_survey_counts_what_the_reading_offers_without_saving(self):
        counts = cards.survey(self.game)
        self.assertFalse(os.path.exists(self.data))
        cards.import_from(self.game, self.data)
        tables = cards.load(self.data)
        self.assertEqual(counts, {kind: len(tables[kind]) for kind in cards.KINDS})

    def test_pictures_converted_side_by_side_are_the_same_files_and_tables_as_one_after_another(self):
        import shutil
        import tempfile
        from unittest import mock
        pack = os.path.join(self.game.root, "pack")
        # Sixty icons in the table (the third of them in a picture that is not one), each its own colours.
        rows = ["Index,path,file,grade"] + ["%d,resource/icon/,i%02d.png,%s" % (n, n, "SA"[n % 2]) for n in range(60)]
        icons = {"Resource\\Icon\\i%02d.png" % n: (picture(n) if n % 20 != 3 else b"not a picture")
                 for n in range(60)}
        tables = dict(self.tables, **{"Resource\\Script\\Uidata\\icon.csv": table(*rows)})
        self._pak(os.path.join(pack, "Script.pak"), tables)
        self._pak(os.path.join(pack, "Icon.pak"), icons)
        game = g.Game.find(self.tmp)

        def read(workers):
            # Every file the reading wrote and the lines it said, the pictures converted on `workers` threads.
            data = tempfile.mkdtemp(dir=self.tmp)
            with mock.patch.object(pictures, "threads", lambda: workers), \
                    self.assertLogs("opendmt3.cards", "INFO") as lines:
                saved = cards.import_from(game, data)
            files = {}
            for folder, _, names in os.walk(data):
                for name in names:
                    path = os.path.join(folder, name)
                    with open(path, "rb") as f:
                        files[os.path.relpath(path, data)] = f.read()
            shutil.rmtree(data)
            return saved, files, lines.output
        one, side = read(1), read(8)
        self.assertEqual(one[0], 60 - 3 + 3)
        self.assertEqual(one, side)
        self.assertEqual([line.split("icon ")[1].split(":")[0] for line in side[2]], ["3", "23", "43"])

    def test_the_tables_and_pictures_come_from_the_players_game_files(self):
        self.assertEqual(cards.import_from(self.game, self.data), 5)
        tables = cards.load(self.data)
        # Only what has a picture is offered; pattern 0 (none) always is.
        self.assertEqual(tables["icon"], [{"number": 0, "grade": ""}, {"number": 1, "grade": ""}])
        self.assertEqual([p["number"] for p in tables["plate"]], [32768, 32769])
        self.assertEqual(tables["pattern"], [{"number": 0, "grade": ""}, {"number": 7, "grade": "A"}])
        # The later archive's points (the A column), the levels in order.
        self.assertEqual(tables["points"], {"1": 9, "2": 9})
        self.assertEqual(tables["levels"], [12, 42])
        # Kept while the file stays the same, and shared read-only (services/files.py).
        self.assertIs(cards.load(self.data), tables)
        with self.assertRaises(TypeError):
            tables["icon"].append({"number": 6, "grade": ""})
        with open(cards.picture(self.data, "plate", 32769), "rb") as f:
            # The game's picture in the server's one form: its pixels, nothing else.
            self.assertEqual(f.read(), pictures.canonical(picture(32769), "plate"))
        self.assertIsNone(cards.picture(self.data, "icon", 6))
        self.assertIsNone(cards.picture(self.data, "../secret", 1))

    def test_a_damaged_patch_says_the_dj_cards_file_is_damaged(self):
        # A patch that is not as the game wrote it may hold newer tables: none are read from the family then.
        with open(os.path.join(self.game.root, "pack", "Script01.pak"), "wb") as f:
            f.write(b"not an archive")
        game = g.Game.find(self.tmp)
        with self.assertRaises(g.GameError) as caught:
            cards.import_from(game, self.data)
        self.assertEqual(caught.exception.key, "error.game.damaged.cards")

    def test_a_folder_without_the_tables_says_so(self):
        os.remove(os.path.join(self.game.root, "pack", "Script.pak"))
        with self.assertRaises(cards.CardError) as caught:
            cards.import_from(self.game, self.data)
        self.assertEqual(caught.exception.key, "error.card.tables")


class CardTest(unittest.TestCase):
    TABLES = {"icon": [{"number": 1}, {"number": 6}], "plate": [{"number": 32769}], "pattern": [{"number": 0}],
              "points": {"1": 9, "2": 9, "3": 10}, "levels": [12, 42, 92]}

    def test_the_level_is_the_first_that_holds_the_experience(self):
        self.assertEqual([cards.level(self.TABLES, e) for e in (0, 12, 13, 42, 92, 93, 10 ** 9)], [1, 1, 2, 2, 3, 3, 3])
        self.assertIsNone(cards.level({}, 100))

    def test_experience_adds_each_cleared_stage_by_its_charts_level(self):
        songs = {56: {"star": [1, 3, 0, 0], "pop": [2, 2, 2, 2]}}
        # Two clears of a level-3 STAR chart, one of a level-2 POP chart, one of a song not in the list (level 1),
        # one of a chart above the table's top level (counted as the top).
        cleared = [(0, 56, 2, 2), (1, 56, 1, 1), (0, 99, 1, 1)]
        self.assertEqual(cards.experience(self.TABLES, songs, cleared), 10 * 2 + 9 + 9)
        self.assertEqual(cards.experience(self.TABLES, {57: {"star": [12, 0, 0, 0]}}, [(0, 57, 1, 1)]), 10)
        self.assertEqual(cards.experience({}, songs, cleared), 0)

    def test_choices_must_be_in_the_tables_and_the_comment_fit(self):
        cards.check(self.TABLES, icon=6, plate=32769, pattern=0, comment="한글ABCDEFGHIJ")
        for bad in ({"icon": 7}, {"icon": "6"}, {"icon": True}, {"plate": 32768}, {"pattern": 7},
                    {"comment": "ABCDEFGHIJKLM"}, {"comment": "line\nbreak"}):
            with self.assertRaises(cards.CardError, msg=bad):
                cards.check(self.TABLES, **bad)
        # Before the tables are read, only the defaults.
        cards.check({}, icon=cards.ICON, plate=cards.PLATE, pattern=cards.PATTERN)
        with self.assertRaises(cards.CardError):
            cards.check({}, icon=6)


if __name__ == "__main__":
    unittest.main()
