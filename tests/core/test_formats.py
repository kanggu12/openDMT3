"""Tests for the settings file, the operator settings file and the stage lists, with made-up contents."""

import unittest

from opendmt3.core.formats import discstock, game_settings, settings_ini, stage_lists

SETTINGS = (
    "[setting]\r\n"
    "fullscreen=true\r\n"
    "popup_style=true\r\n"
    "// 화면 설정\r\n"          # a comment in the game's Korean code page
    "show_cursor=false\r\n"
    "\r\n"
    "[FilePath]\r\n"
    "rankFilePath = file/\r\n"
)


class SettingsIniTest(unittest.TestCase):
    def test_values_change_and_nothing_else_does(self):
        out = settings_ini.set_values(SETTINGS, {"fullscreen": "false", "rankFilePath": "TECHNIKA/RANK/"})
        self.assertIn("fullscreen=false\r\n", out)
        # The spacing around '=' stays as the game wrote it.
        self.assertIn("rankFilePath = TECHNIKA/RANK/\r\n", out)
        self.assertEqual(out.replace("fullscreen=false", "fullscreen=true").replace("TECHNIKA/RANK/", "file/"), SETTINGS)
        # It still encodes to the game's code page.
        self.assertEqual(settings_ini.decode(settings_ini.encode(out)), out)

    def test_get_value(self):
        self.assertEqual(settings_ini.get_value(SETTINGS, "rankfilepath"), "file/")
        self.assertIsNone(settings_ini.get_value(SETTINGS, "nothing"))

    def test_unknown_key_and_spaces_are_refused(self):
        with self.assertRaises(KeyError):
            settings_ini.set_values(SETTINGS, {"no_such_key": "1"})
        with self.assertRaises(ValueError):
            settings_ini.set_values(SETTINGS, {"rankFilePath": "a folder/"})


class GameSettingsTest(unittest.TestCase):
    def test_round_trip_keeps_unused_bytes(self):
        raw = bytes.fromhex("00000000" "02000000" "01000000" "01cccccc" "00000000")
        s = game_settings.GameSettings.parse(raw)
        self.assertEqual((s.coins_per_credit, s.free_play), (2, 0))
        self.assertEqual(s.build(), raw)
        s.free_play = 1
        self.assertEqual(s.build()[16:], b"\x01\x00\x00\x00")
        self.assertEqual(s.build()[:16], raw[:16])

    def test_default_is_twenty_bytes(self):
        self.assertEqual(len(game_settings.GameSettings().build()), game_settings.SIZE)


STAGE = (
    b"stage1,songname,SP,PT,Hid,SP,PT,Hid,SP,PT,Hid,SP,PT,Hid\r\n"
    b"1,songa,2,1,0,2,2,1,2,3,1,,,\r\n"
    b"2,songb,1,1,1,,,,,,,,,\r\n"
)


class StageListsTest(unittest.TestCase):
    def test_names(self):
        self.assertTrue(stage_lists.is_stage_list("Resource\\DiscInfo\\pop_stage_2.csv"))
        self.assertTrue(stage_lists.is_stage_list("Resource/DiscInfo/STAR_STAGE_1.csv"))
        self.assertFalse(stage_lists.is_stage_list("Resource\\DiscInfo\\pop_stage_bonus.csv"))
        self.assertFalse(stage_lists.is_stage_list("Resource\\DiscInfo\\discstock.csv"))

    def test_show_all_changes_only_hidden_flags(self):
        self.assertEqual(stage_lists.count_hidden(STAGE), 3)
        out = stage_lists.show_all(STAGE)
        self.assertEqual(stage_lists.count_hidden(out), 0)
        self.assertEqual(out, STAGE.replace(b"2,2,1,2,3,1", b"2,2,0,2,3,0").replace(b"1,1,1,,", b"1,1,0,,"))


class DiscstockTest(unittest.TestCase):
    def test_reads_the_tab_separated_utf16_list(self):
        # Made-up songs in the game's layout: a title with a comma is quoted, missing patterns are 0.
        text = ("no\tname\tFullName\tGenre\tComposer\tbg_folder\tserieslist\tlicenselist\toriginalbga\tloopBga\t"
                "Star_1\tStar_2\tStar_3\tStar_4\tPop_1\tPop_2\tPop_3\tPop_4\r\n"
                "1\tsonga\t\"First, Song\"\tHouse\tSomeone\tmovie1\t1\t0\t1\tFALSE\t3\t0\t0\t0\t2\t5\t9\t0\r\n"
                "2\tsongb\t노래\tPop\tOther\tmovie1\t1\t0\t1\tFALSE\t1\t0\t0\t0\t1\t0\t0\t0\r\n")
        songs = discstock.parse(text.encode("utf-16"))
        self.assertEqual([s["title"] for s in songs], ["First, Song", "노래"])
        self.assertEqual((songs[0]["number"], songs[0]["star"], songs[0]["pop"]), (1, [3, 0, 0, 0], [2, 5, 9, 0]))


if __name__ == "__main__":
    unittest.main()
