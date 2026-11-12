"""Tests for how the launcher takes the game from a player (client/intake.py, find.py, unpack.py): what a path is, by
its content, in every form a player may bring (a game folder at any depth and letter case, the cabinet's client, a
modified PC client, a damaged song list, a folder an older openDMT3 changed, a copy of a cabinet's drives, a folder
in Program Files, one file of a folder, an archive whole,
split, with a password, inside another, cut short, a part missing), each said in one plain line in both languages;
the search of the usual places; 7-Zip's own words read as the launcher reads them (the real outputs of the official
7-Zip for Windows, run under Wine, and for Linux: tests/fixtures/seven_zip); and unpacking, which leaves nothing
behind when it stops or fails.

Everything is made up (tests/core/made_up_game.py). The unpacking tests run the 7-Zip the launcher would use
(sources.seven_zip: OPENDMT3_7ZIP, else 7zz, 7z or 7za on PATH) and are skipped without one."""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest import mock

from opendmt3.core import errors
from opendmt3.core import game as g
from opendmt3.client import find, i18n, intake, unpack
from opendmt3.server.services import sources
from tests.core.made_up_game import GameCase, NEWEST_SONGS, song_list
from tests.server.test_sources import LYING_LISTING, lying_gzip, seen, seven_z, stand_in, twice_zip

SEVEN_ZIP = sources.seven_zip()
FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "seven_zip")
EN, KO = i18n.Words("en"), i18n.Words("ko")


def fixture(platform):
    """What the official 7-Zip printed for the made-up archives: {"<archive> <run>": {"code", "out", "err"}}."""
    with open(os.path.join(FIXTURES, platform + ".json"), encoding="utf-8") as f:
        return json.load(f)


class Kinds(GameCase):
    """The made-up game folder, its client told apart by its name as the real ones are by their hashes: Client.exe the
    PC client as released, Modified.exe a modified PC client, Game.exe alone the cabinet's client."""

    def setUp(self):
        super().setUp()
        table = self.table
        self.patcher.stop()

        def table_of(game):
            names = {n.lower(): n for n in os.listdir(game.root)}
            for name, kind in (("client.exe", g.ORIGINAL), ("modified.exe", g.MODIFIED)):
                if name in names:
                    game.client = (os.path.join(game.root, names[name]), kind)
                    return table
            raise g.GameError("The cabinet's client: does not work here, the PC client is needed.",
                              "error.game.cabinet_client")

        self.patcher = mock.patch.object(g.Game, "table", table_of)
        self.patcher.start()
        self.root = self.game.root
        # openDMT3's own folder (whether it has the operator data yet) in a folder of the test's.
        self.config = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.config)
        env = mock.patch.dict(os.environ, {"OPENDMT3_CONFIG_DIR": self.config})
        env.start()
        self.addCleanup(env.stop)


class FolderTest(Kinds):
    def test_a_game_folder_below_the_path_reads_ready_with_what_it_holds(self):
        found = intake.inspect(self.tmp)
        self.assertEqual((found.state, found.kind, found.root), (intake.READY, intake.FOLDER, self.root))
        self.assertEqual(found.actions, [intake.CHOOSE])
        self.assertEqual(found.sentence(EN), "Game folder, original PC client, %d songs, %d jackets: ready"
                         % (len(NEWEST_SONGS), len(NEWEST_SONGS)))
        self.assertEqual(found.sentence(KO), "게임 폴더, PC 클라이언트 원본, 곡 %d개, 자켓 %d개: 쓸 수 있음"
                         % (len(NEWEST_SONGS), len(NEWEST_SONGS)))

    def test_a_copy_without_its_videos_plays_and_says_so(self):
        for name in g.VIDEOS[3:7]:
            os.remove(os.path.join(self.root, "pack", name + ".pak"))
        found = intake.inspect(self.root)
        self.assertEqual((found.state, found.tone), (intake.READY, intake.NOTE))
        self.assertTrue(found.sentence(EN).endswith(": ready. The videos are missing: songs play without them."),
                        found.sentence(EN))
        self.assertTrue(found.sentence(KO).endswith(": 쓸 수 있음. 영상 파일이 없습니다. 곡은 영상 없이 진행됩니다."),
                        found.sentence(KO))

    def test_a_copy_without_the_tutorial_does_not_play_here(self):
        os.remove(os.path.join(self.root, "pack", g.TUTORIAL + ".pak"))
        found = intake.inspect(self.root)
        self.assertEqual((found.state, found.tone, found.actions), (intake.NOT_HERE, intake.PROBLEM, []))
        self.assertEqual(found.sentence(EN), "The file with the tutorial is missing: the game stops at the tutorial. "
                                             "Copy the game folder again, or unpack the archive again.")
        self.assertEqual(found.sentence(KO), "튜토리얼이 든 파일이 없어 게임이 튜토리얼에서 멈춥니다. 게임 폴더를 다시 "
                                             "복사하거나 압축 파일을 다시 푸세요.")

    def test_a_copy_without_its_previews_plays_and_says_so(self):
        os.remove(os.path.join(self.root, "pack", g.PREVIEWS[1] + ".pak"))
        found = intake.inspect(self.root)
        self.assertEqual((found.state, found.tone), (intake.READY, intake.NOTE))
        self.assertTrue(found.sentence(EN).endswith(": ready. The previews are missing: the song select shows none."),
                        found.sentence(EN))
        self.assertTrue(found.sentence(KO).endswith("미리보기 파일이 없습니다. 곡 선택에서 미리보기가 나오지 않습니다."),
                        found.sentence(KO))

    def test_a_copy_without_the_charts_does_not_play_here(self):
        os.remove(os.path.join(self.root, "pack", g.CHARTS + ".pak"))
        found = intake.inspect(self.root)
        self.assertEqual((found.state, found.tone, found.actions), (intake.NOT_HERE, intake.PROBLEM, []))
        self.assertEqual(found.sentence(EN), "The file with the charts is missing: the game stops when a song starts. "
                                             "Copy the game folder again, or unpack the archive again.")
        self.assertEqual(found.sentence(KO), "차트가 든 파일이 없어 곡을 시작하면 게임이 멈춥니다. 게임 폴더를 다시 복사하거나 "
                                             "압축 파일을 다시 푸세요.")

    def charts(self, *songs):
        """The charts' family with a chart for each of these songs (made-up charts, as the game names them)."""
        self._pak(os.path.join(self.root, "pack", g.CHARTS + ".pak"),
                  {"pattern\\%s\\%s_star_1.pt" % (name, name): b"made-up chart" for name in songs})

    def test_the_charts_check_goes_on_beside_the_survey(self):
        # The charts' check reads the most of a look: it starts first, on a thread of its own, and the survey goes on
        # meanwhile; its answer is the card's line as before.
        from opendmt3.server.services import catalog
        self.charts("alpha", "gamma")
        started, threads = threading.Event(), []
        real_without, real_survey = intake.without_charts, catalog.survey

        def without(game):
            threads.append(threading.current_thread().name)
            started.set()
            return real_without(game)

        def survey(path):
            # The check has started before the survey goes on.
            self.assertTrue(started.wait(10))
            return real_survey(path)

        with mock.patch.object(intake, "without_charts", without), mock.patch.object(catalog, "survey", survey):
            found = intake.inspect(self.root)
        self.assertEqual(threads, ["charts"])
        self.assertEqual((found.state, found.tone), (intake.READY, intake.PROBLEM))
        self.assertIn("1 song has no charts", found.sentence(EN))

    def test_songs_without_charts_are_counted_and_said(self):
        self.charts("alpha", "gamma")
        found = intake.inspect(self.root)
        self.assertEqual((found.state, found.tone), (intake.READY, intake.PROBLEM))
        self.assertTrue(found.sentence(EN).endswith(": ready. 1 song has no charts and cannot be chosen."),
                        found.sentence(EN))
        self.assertTrue(found.sentence(KO).endswith("곡 1개는 차트가 없어 고를 수 없습니다."), found.sentence(KO))
        # Two songs without: counted.
        self.charts("gamma")
        self.assertIn("2 songs have no charts", intake.inspect(self.root).sentence(EN))

    def newer_list(self, stage_list=None, more=(), tables=None):
        """A newer song list (patch 02) with a fourth song, delta, that has no charts, and the rows in `more`; with
        stage_list, a stage list of the same patch that names it; `tables`, more files of that patch."""
        files = {"Resource\\DiscInfo\\discstock.csv": song_list(NEWEST_SONGS + ((4, "delta", "Made-up Delta"),)
                                                                + tuple(more))}
        if stage_list:
            files["Resource\\DiscInfo\\star_stage_2.csv"] = stage_list
        files.update(tables or {})
        self._pak(os.path.join(self.root, "pack", "DiscInfo02.pak"), files)

    def test_a_song_only_a_club_disc_set_offers_is_counted_and_said(self):
        self.charts("alpha", "beta", "gamma")
        # Delta is on no stage list: the made-up disc set "deltaset" plays it (by number, under a title to show, as the
        # game's single-song sets name theirs), and epsilon is its hidden song. Neither has charts.
        # The disc sets' table: the set's name in its second cell (the header's words are made up here).
        sets = b"id,name,hidden,order,stages,title,random\r\n0,deltaset,x,0,1,DELTA set,x\r\n"
        self._pak(os.path.join(self.root, "pack", "Script02.pak"),
                  {"Resource\\Script\\ClubDiscSetInfo\\DiscSetInfo.csv": sets})
        self.newer_list(more=((5, "epsilon", "Made-up Epsilon"),), tables={
            "Resource\\DiscInfo\\deltaset.csv": b"deltaset,,speed,pattern, ,sum,hidden_number,hidden_name,hidden_level,"
                                                b"hidden_speed,hidden_pattern\r\n4,Delta (Extended Mix),2,1,,9,5,Epsilon,"
                                                b"8,2,1\r\n"})
        found = intake.inspect(self.root)
        self.assertEqual((found.state, found.tone, found.songs, found.jackets), (intake.READY, intake.PROBLEM, 5, 3))
        self.assertTrue(found.sentence(EN).endswith(", 5 songs, 3 jackets: ready. 2 songs have no charts and cannot be "
                                                    "chosen."), found.sentence(EN))

    def test_a_song_only_a_crew_mission_offers_is_counted_and_said(self):
        self.charts("alpha", "beta", "gamma")
        # Delta is on no stage list and in no disc set: a crew mission the game keeps plays it (by number).
        head = ["GSN", "CREWID", "CREWNAME", "MUSICNUM1", "PATTERNNUM1", "MUSICNUM2", "PATTERNNUM2", "MUSICNUM3",
                "PATTERNNUM3"]
        row = ["1", "1", "made-up crew", "1", "1", "4", "1", "2", "1"]
        missions = "\t".join(head) + "\r\n" + "\t".join(row) + "\r\n"
        self._pak(os.path.join(self.root, "pack", "Script02.pak"),
                  {"Resource\\Script\\DefaultMission\\DefaultMission.csv": missions.encode("utf-16")})
        self.newer_list()
        found = intake.inspect(self.root)
        self.assertEqual((found.state, found.tone, found.songs, found.jackets), (intake.READY, intake.PROBLEM, 4, 3))
        self.assertTrue(found.sentence(EN).endswith(", 4 songs, 3 jackets: ready. 1 song has no charts and cannot be "
                                                    "chosen."), found.sentence(EN))

    def test_an_offered_song_without_charts_is_counted_and_said(self):
        self.charts("alpha", "beta", "gamma")
        # Delta is on a stage list: the game offers it, so the card counts it, and it has no charts.
        self.newer_list(b"stage2,songname,SP,PT,Hid\r\n4,delta,1,1,0\r\n")
        found = intake.inspect(self.root)
        self.assertEqual((found.state, found.tone, found.songs), (intake.READY, intake.PROBLEM, 4))
        self.assertTrue(found.sentence(EN).endswith(", 4 songs, 3 jackets: ready. 1 song has no charts and cannot be "
                                                    "chosen."), found.sentence(EN))

    def test_a_song_no_stage_list_names_is_neither_counted_nor_said(self):
        self.charts("alpha", "beta", "gamma")
        # Delta is in the song list but on no stage list: never shown to a player, so neither a song of the card's
        # nor one without charts.
        self.newer_list()
        found = intake.inspect(self.root)
        self.assertEqual((found.state, found.line, found.songs, found.jackets), (intake.READY, None, 3, 3))
        self.assertEqual(found.sentence(EN), "Game folder, original PC client, 3 songs, 3 jackets: ready")
        # The server's song list keeps every row (the records' titles and levels): four there.
        from opendmt3.server.services import catalog
        self.assertEqual(catalog.survey(self.root)["songs"], 4)

    def test_an_answer_kept_by_an_older_openDMT3_is_worked_out_again(self):
        from opendmt3.core import charts
        self.charts("alpha", "gamma")
        game = g.Game(self.root)
        keep = os.path.join(self.config, "openDMT3-charts.json")
        # The same files, an answer kept without this openDMT3's way of working it out (every row counted, or none
        # told while a file of the charts could not be opened).
        key = os.path.normcase(os.path.abspath(game.root))
        with open(keep, "w", encoding="utf-8") as f:
            json.dump({key: {"from": charts._stamps(game), "answer": None}}, f)
        self.assertEqual(charts.check(game, keep)["without"], ["beta"])
        # Kept again, now with the version: the next look takes it as it is.
        with mock.patch.object(charts, "_work_out", side_effect=AssertionError("worked out again")):
            self.assertEqual(charts.check(game, keep)["without"], ["beta"])

    def test_a_chart_patch_with_a_korean_name_first_still_lets_the_count_speak(self):
        self.charts("alpha", "gamma")
        # A chart patch as the game has one: a song's speed notes under a Korean name ("speed notes.txt") come first,
        # then the chart the base lacks. It is read like any other patch, so the count is told, and is now none.
        self._pak(os.path.join(self.root, "pack", g.CHARTS + "00.pak"),
                  {"pattern\\beta\\배속정보.txt": "1.5".encode("cp949"), "pattern\\beta\\beta_star_1.pt": b"made-up chart"})
        self.assertEqual(intake.without_charts(g.Game(self.root))["without"], [])

    def test_the_count_is_worked_out_once_until_the_charts_change(self):
        from opendmt3.core import charts
        self.charts("alpha", "gamma")
        self.assertEqual(intake.without_charts(g.Game(self.root))["without"], ["beta"])
        # Again: from openDMT3's kept answer, without reading the charts' files.
        with mock.patch.object(charts, "_work_out", side_effect=AssertionError("worked out again")):
            self.assertEqual(intake.without_charts(g.Game(self.root))["without"], ["beta"])
        # The charts' file changed (its size here): worked out again.
        self.charts("alpha", "beta", "gamma")
        self.assertEqual(intake.without_charts(g.Game(self.root))["without"], [])

    def test_a_first_song_without_charts_does_not_play_here(self):
        self.charts("alpha", "gamma")
        # The first stage's list for STAR starts with the song that has no chart: the song select shows it first.
        self._pak(os.path.join(self.root, "pack", "DiscInfo02.pak"),
                  {"Resource\\DiscInfo\\star_stage_1.csv": b"stage1,songname,SP,PT,Hid\r\n2,beta,2,1,0\r\n"})
        found = intake.inspect(self.root)
        self.assertEqual((found.state, found.actions), (intake.NOT_HERE, []))
        self.assertEqual(found.sentence(EN), "The first song the game shows has no charts: the game stops when it "
                                             "starts. Copy the game folder again, or unpack the archive again.")

    def test_a_folder_where_nothing_can_be_written_plays_as_any_other(self):
        # PLAY only reads the game folder: Program Files (where only an administrator writes) is no problem.
        protected = os.path.join(self.tmp, "Program Files", "TECHNIKA 3")
        shutil.copytree(self.root, protected)
        found = intake.inspect(protected)
        self.assertEqual((found.state, found.line), (intake.READY, None))

    def test_a_copy_of_a_cabinets_drives_brings_its_operator_data_once(self):
        drives = os.path.join(self.tmp, "cabinet")
        root = os.path.join(drives, "drive d", "DMT3")
        shutil.copytree(self.root, root)
        os.makedirs(os.path.join(drives, "drive e", "TECHNIKA", "GAME"))
        with open(os.path.join(drives, "drive e", "TECHNIKA", "GAME", "game"), "wb") as f:
            f.write(b"the cabinet's operator settings")
        found = intake.inspect(root)
        self.assertEqual((found.state, found.tone), (intake.READY, intake.NOTE))
        self.assertTrue(found.sentence(EN).endswith(": ready. The cabinet's operator data comes along."),
                        found.sentence(EN))
        self.assertTrue(found.sentence(KO).endswith(": 쓸 수 있음. 기체의 운영 데이터도 함께 가져옵니다."),
                        found.sentence(KO))
        # Once openDMT3 has operator data of its own, the cabinet's changes nothing: no line.
        from opendmt3.client import state
        own = state.own_folder().path("TECHNIKA", "GAME")
        os.makedirs(own)
        with open(os.path.join(own, "game"), "wb") as f:
            f.write(b"openDMT3's")
        self.assertIsNone(intake.inspect(root).line)

    def test_a_modified_pc_client_is_played_without_the_screen_fit(self):
        os.replace(os.path.join(self.root, "Client.exe"), os.path.join(self.root, "Modified.exe"))
        found = intake.inspect(self.root)
        self.assertEqual((found.state, found.client, found.tone), (intake.READY, g.MODIFIED, intake.NOTE))
        self.assertTrue(found.sentence(EN).endswith(": ready. Played without the screen fit."), found.sentence(EN))
        self.assertIn("수정된 PC 클라이언트", found.sentence(KO))

    def test_the_cabinets_client_does_not_work_here(self):
        os.replace(os.path.join(self.root, "Client.exe"), os.path.join(self.root, "Game.exe"))
        found = intake.inspect(self.root)
        self.assertEqual(found.state, intake.NOT_HERE)
        self.assertEqual(found.actions, [])
        self.assertEqual(found.sentence(EN), "The cabinet's client: does not work here, the PC client is needed.")
        self.assertEqual(found.sentence(KO), "기체용 클라이언트: 여기서는 못 씁니다. PC 클라이언트가 필요합니다.")

    def test_a_damaged_song_list_says_what_to_do(self):
        self.cut("DiscInfo01.pak", 40)
        found = intake.inspect(self.root)
        self.assertEqual(found.state, intake.NOT_HERE)
        self.assertEqual(found.sentence(EN), "The file with the song list is damaged. Copy the game folder again, or "
                                             "unpack the archive again.")
        self.assertEqual(found.sentence(KO), "곡 목록이 든 파일이 손상됐습니다. 게임 폴더를 다시 복사하거나 압축 파일을 다시 "
                                             "푸세요.")

    def test_files_an_older_openDMT3_changed_are_counted_and_put_back_is_offered(self):
        from tests.core import older_setup
        self._run_setup(older_setup.Options(server="127.0.0.1:4725"))
        found = intake.inspect(self.root)
        self.assertEqual((found.state, found.tone), (intake.READY, intake.NOTE))
        self.assertGreater(found.changed, 0)
        self.assertIn(intake.PUT_BACK, found.actions)
        self.assertIn("files changed by openDMT3" if found.changed > 1 else "1 file changed by openDMT3",
                      found.sentence(EN))
        self.assertTrue(found.sentence(EN).endswith(". An older openDMT3 changed files here. Put back makes them "
                                                    "original again."), found.sentence(EN))
        self.assertTrue(found.sentence(KO).endswith(". 예전 openDMT3가 바꾼 파일이 있습니다. 되돌리면 원본으로 돌아갑니다."),
                        found.sentence(KO))

    def test_one_file_of_a_game_folder_is_the_folder_around_it(self):
        for path in (os.path.join(self.root, "Client.exe"), os.path.join(self.root, "pack", "DiscImg.pak")):
            found = intake.inspect(path)
            self.assertEqual((found.state, found.root), (intake.READY, self.root), path)

    def test_a_file_of_the_game_alone_is_part_of_a_game_folder(self):
        alone = os.path.join(self.tmp, "Config.pak")
        shutil.copy(os.path.join(self.root, "pack", "Config.pak"), alone)
        found = intake.inspect(alone)
        self.assertEqual(found.sentence(EN), "This is part of a game folder. Choose the whole game folder.")
        self.assertEqual(found.sentence(KO), "게임 폴더의 일부입니다. 게임 폴더 전체를 고르세요.")

    def test_what_holds_no_game_and_what_is_gone(self):
        notes = os.path.join(self.tmp, "notes")
        os.makedirs(notes)
        with open(os.path.join(notes, "readme.txt"), "w") as f:
            f.write("made-up")
        for path in (notes, os.path.join(notes, "readme.txt")):
            found = intake.inspect(path)
            self.assertEqual(found.sentence(EN), "This is neither a game folder nor an archive holding one.", path)
            self.assertEqual(found.sentence(KO), "게임 폴더도, 게임이 든 압축 파일도 아닙니다.")
        found = intake.inspect(os.path.join(self.tmp, "gone"))
        self.assertEqual((found.state, found.sentence(EN)), (intake.NOT_HERE, "This is not there any more."))

    def test_files_kept_only_in_onedrives_cloud_are_said_before_play(self):
        real = os.stat

        class Stat:
            def __init__(self, st):
                self.st = st
                # FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS: Windows' mark of a file kept in the cloud alone.
                self.st_file_attributes = 0x00400000

            def __getattr__(self, name):
                return getattr(self.st, name)

        def stat(path, *a, **kw):
            st = real(path, *a, **kw)
            return Stat(st) if os.sep + "pack" + os.sep in str(path) else st

        with mock.patch.object(find.os, "stat", stat):
            found = intake.inspect(self.root)
        self.assertEqual(found.state, intake.READY)
        self.assertEqual(found.line_words(EN), "This game folder is only in OneDrive's cloud. Set it to \"Always keep "
                                               "on this device\".")

    def test_a_stop_ends_the_look_with_what_it_knew(self):
        stop = threading.Event()
        stop.set()
        found = intake.inspect(self.root, cancel=stop)
        # The song list is read; what an earlier PLAY changed is not looked for once stopped.
        self.assertEqual((found.state, found.changed), (intake.READY, 0))


class FindTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def folder(self, *parts, exe="Client.exe", pack="pack", marks=("Config.pak", "DiscInfo.pak")):
        root = os.path.join(self.tmp, *parts)
        os.makedirs(os.path.join(root, pack))
        open(os.path.join(root, exe), "wb").close()
        for name in marks:
            open(os.path.join(root, pack, name), "wb").close()
        return root

    def test_game_folders_by_content_in_any_letter_case_up_to_four_levels_down(self):
        near = self.folder("a")
        upper = self.folder("b", "c", exe="CLIENT.EXE", pack="PACK", marks=("CONFIG.PAK", "DISCINFO.PAK"))
        deep = self.folder("d", "e", "f", "g")
        too_deep = self.folder("h", "i", "j", "k", "l")
        self.folder("m", marks=("Config.pak",))
        self.folder("n", exe="readme.txt")
        got = list(find.paths([self.tmp]))
        self.assertEqual(sorted(got), sorted([near, upper, deep]))
        self.assertNotIn(too_deep, got)

    def test_archives_by_the_games_words_and_split_ones_by_their_first_part(self):
        names = ["technika3.7z", "DJMAX.ZIP", "dmt3-copy.rar", "parts.7z.001", "technika.7z.001", "technika.7z.002",
                 "dmt3.part1.rar", "dmt3.part2.rar", "photos.zip", "technika.iso", "technika-notes.txt"]
        for name in names:
            open(os.path.join(self.tmp, name), "wb").close()
        got = sorted(os.path.basename(p) for p in find.paths([self.tmp]))
        self.assertEqual(got, sorted(["technika3.7z", "DJMAX.ZIP", "dmt3-copy.rar", "technika.7z.001",
                                      "dmt3.part1.rar", "technika.iso"]))

    def test_folders_that_never_hold_a_game_are_passed_by(self):
        self.folder("AppData", "game")
        self.folder("Windows", "game")
        self.folder(".hidden", "game")
        inside = self.folder("x")
        # A game folder's own pack folder holds nothing else to find.
        open(os.path.join(inside, "pack", "technika-in-pack.7z"), "wb").close()
        self.assertEqual(list(find.paths([self.tmp])), [inside])

    def test_a_stop_ends_the_search_at_once(self):
        for i in range(20):
            self.folder("f%02d" % i)
        stop = threading.Event()
        got = []
        for path in find.paths([self.tmp], cancel=stop):
            got.append(path)
            stop.set()
        self.assertEqual(len(got), 1)


class SevenZipWordsTest(unittest.TestCase):
    """The official 7-Zip's own output (for Windows under Wine, and for Linux), read as the launcher reads it."""

    def test_both_7zips_list_the_same_entries(self):
        for name in ("technika3.7z", "technika3.zip", "technika3.rar", "technika3-korean.7z"):
            lists = {}
            for platform in ("linux", "windows"):
                run = fixture(platform)["%s list" % name]
                self.assertEqual(run["code"], 0, (platform, name))
                lists[platform] = sorted(e.name for e in sources._parse_listing(run["out"]))
            self.assertEqual(lists["linux"], lists["windows"], name)
            self.assertTrue(any(n.endswith("pack/DiscInfo.pak") for n in lists["linux"]), name)

    def test_progress_is_read_from_both_7zips(self):
        for platform in ("linux", "windows"):
            run = fixture(platform)["technika3-damaged.7z extract"]
            seen, said = [], []
            reader = unpack.Run.__new__(unpack.Run)
            reader.progress = seen.append
            # The output as 7-Zip writes it: backspaces on Linux, carriage returns on Windows.
            for piece in __import__("re").split(rb"[\b\r\n]", run["out"].encode("utf-8")):
                reader._piece(piece, said)
            self.assertEqual(seen[-1], 1.0, platform)
            self.assertIn("ERROR: CRC Failed : TECHNIKA 3%spack%sfiller.pak" % (("\\",) * 2 if platform == "windows"
                                                                               else ("/",) * 2), said)

    def test_what_7zip_says_is_worded(self):
        for platform in ("linux", "windows"):
            runs = fixture(platform)
            cases = {
                "technika3-damaged.7z test": "error.source.damaged",
                "technika3-pw.zip testwrong": "error.source.wrong_password",
                "technika3-pwnames.7z list": "error.source.password",
            }
            for key, want in cases.items():
                run = runs[key]
                said = run["out"] + run["err"]
                password = "not-it" if key.endswith("testwrong") else None
                self.assertEqual(unpack._verdict(run["code"], said, password, "technika3.7z").key, want, (platform, key))
            missing = runs["missing__technika3-splitrar.part1.rar listprops"]
            error = unpack._verdict(missing["code"], missing["out"] + missing["err"], None, "technika3-splitrar.part1.rar")
            self.assertEqual((error.key, error.params), ("error.source.missing_part", {"n": 2}), platform)

    def test_dangerous_entries_are_seen_in_both_listings(self):
        for platform in ("linux", "windows"):
            entries = sources._parse_listing(fixture(platform)["technika3-dotdot.zip list"]["out"])
            refused = sorted(e.name for e in entries if sources.unsafe(e.name))
            self.assertEqual(refused, sorted(["../../outside.txt", "/abs/outside.txt", "TECHNIKA 3/CON",
                                              "TECHNIKA 3/name:stream"]), platform)
            links = [e.name for e in sources._parse_listing(fixture(platform)["technika3-link.7z list"]["out"]) if e.link]
            self.assertEqual(links, ["TECHNIKA 3/pack/link.pak"], platform)


class LauncherSevenZipTest(unittest.TestCase):
    """The launcher's own 7-Zip runs (unpack.Run): the password on 7-Zip's standard input, never on its command line;
    an entry's name never read as a switch; what 7-Zip writes held to what the entries said; a compressed stream that
    says its size only at its end, and an entry without a size, refused on the card (the security review's proofs 1b,
    3 and 8, made up here)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.downloads = os.path.join(self.tmp, "Downloads")
        os.makedirs(self.downloads)

    def test_the_password_goes_on_7zips_standard_input_never_on_its_command_line(self):
        record = stand_in(self)
        archive = seven_z(os.path.join(self.downloads, "technika3.7z"))
        run = unpack.Run(["t", "-spd", "--", archive], "made-up-pass-1234")
        self.assertFalse([a for a in run.command if "made-up-pass-1234" in a], run.command)
        self.assertEqual(run.go()[0], 0)
        self.assertFalse([a for a in seen(record, "args") if "made-up-pass-1234" in a])
        self.assertEqual(seen(record, "stdin"), b"made-up-pass-1234\n")
        self.assertEqual(seen(record, "args")[-2:], ["--", archive])

    def test_7zip_is_stopped_once_it_writes_more_than_the_entries_said(self):
        record = stand_in(self, LYING_LISTING)
        archive = seven_z(os.path.join(self.downloads, "technika3.7z"))
        with self.assertRaises(errors.Worded) as caught:
            unpack.Unpacking(archive, self.downloads).run()
        self.assertEqual(caught.exception.key, "error.source.damaged")
        # Stopped near its 1000 bytes and the margin, where it would have written 512 MB; the half-made folder gone.
        self.assertLess(seen(record, "written"), 64 << 20)
        self.assertEqual(os.listdir(self.downloads), ["technika3.7z"])

    def test_a_stream_that_says_its_size_at_its_end_does_not_work_here(self):
        gz = lying_gzip(os.path.join(self.downloads, "technika3.zip.gz"))
        found = intake.inspect(gz)
        self.assertEqual(found.state, intake.NOT_HERE)
        self.assertEqual(found.sentence(EN), "This archive says its size only at its end, where it cannot be checked "
                                             "first. Unpack it with another program, then choose what came out.")
        self.assertEqual(found.sentence(KO), "이 압축 파일은 크기를 끝에만 적어 두어 미리 확인할 수 없습니다. 다른 프로그램으로 "
                                             "푼 뒤 나온 것을 고르세요.")
        with self.assertRaises(errors.Worded) as caught:
            unpack.Unpacking(gz, self.downloads).run()
        self.assertEqual(caught.exception.key, "error.source.stream")
        self.assertEqual(os.listdir(self.downloads), ["technika3.zip.gz"])

    def test_an_entry_without_a_size_does_not_work_here(self):
        stand_in(self, LYING_LISTING.replace("Size = 1000\nAttributes = A -rw-r--r--\n\n", "Size = \n\n", 1))
        archive = seven_z(os.path.join(self.downloads, "technika3.7z"))
        found = intake.inspect(archive)
        self.assertEqual(found.state, intake.NOT_HERE)
        self.assertEqual(found.line_words(EN), "An entry in this archive cannot be taken: TECHNIKA 3/Client.exe")
        with self.assertRaises(errors.Worded) as caught:
            unpack.Unpacking(archive, self.downloads).run()
        self.assertEqual(caught.exception.key, "error.source.entry")
        self.assertEqual(os.listdir(self.downloads), ["technika3.7z"])

    def test_an_archive_with_a_name_twice_does_not_work_here(self):
        for second in ("g/pack/DiscInfo.pak", "g/pack/discinfo.PAK"):
            with self.subTest(second=second):
                archive = twice_zip(os.path.join(self.downloads, "technika3.zip"), second)
                found = intake.inspect(archive)
                self.assertEqual(found.state, intake.NOT_HERE)
                self.assertEqual(found.line_words(EN), "An entry in this archive cannot be taken: %s" % second)
                with self.assertRaises(errors.Worded) as caught:
                    unpack.Unpacking(archive, self.downloads).run()
                self.assertEqual(caught.exception.key, "error.source.entry")
                self.assertEqual(os.listdir(self.downloads), ["technika3.zip"])

    @unittest.skipUnless(SEVEN_ZIP, "needs 7-Zip (OPENDMT3_7ZIP, or 7zz, 7z or 7za on PATH)")
    def test_a_password_check_takes_an_entry_named_like_a_switch_as_a_name(self):
        for name in ("-ssw made-up.txt", "@made-up.txt"):
            with self.subTest(name=name):
                src = tempfile.mkdtemp(dir=self.tmp)
                with open(os.path.join(src, name), "w") as f:
                    f.write("made up")
                # Made from a list file too: a distribution's 7-Zip reads "@name" as a list even after "--".
                with open(os.path.join(self.tmp, "names.txt"), "w", encoding="utf-8") as f:
                    f.write(name + "\n")
                archive = os.path.join(self.downloads, "technika3-%d.7z" % len(os.listdir(self.downloads)))
                subprocess.run([SEVEN_ZIP, "a", "-bso0", "-bsp0", "-pmade-up-1", "-spd", "-scsUTF-8",
                                "-i@" + os.path.join(self.tmp, "names.txt"), "--", archive], cwd=src, check=True,
                               stdin=subprocess.DEVNULL)
                self.assertEqual([e.name for e in sources.listing(archive)], [name])
                # Its name read as a switch or a list, 7-Zip would refuse its command line, never the password.
                self.assertFalse(intake.password_opens(archive, "not-it"))
                self.assertTrue(intake.password_opens(archive, "made-up-1"))


class NamesTest(unittest.TestCase):
    def test_the_new_folder_is_named_after_the_archive(self):
        for name, folder in (("technika3.7z", "technika3"), ("technika3.part1.rar", "technika3"),
                             ("Game Copy.7z.001", "Game Copy"), ("dmt3.zip.001", "dmt3"), ("disc.iso", "disc")):
            self.assertEqual(unpack.folder_name(name), folder)
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "technika3"))
            self.assertEqual(unpack.target(d, "technika3.7z"), os.path.join(d, "technika3 (2)"))

    def test_an_archive_whose_files_come_out_one_by_one_is_told_apart(self):
        # The first bytes of RAR5 archives the rar program made here of made-up files: solid, not solid, a solid one's
        # first part, a first part that is not solid; then a zip's, a 7z's and RAR 4's (solid and not), by the format.
        heads = {
            "526172211a0701009c161a8c0c01050804070101cd97ac80": False,
            "526172211a070100e3159c400c01050800070101ab8cac80": True,
            "526172211a070100da0e77e20c01050805070101f29d8680": False,
            "526172211a070100481528da0c01050801070101bdbe8c80": True,
            "504b0304140000000000": True,
            "377abcaf271c0004": False,
            "526172211a0700cf907308000d00": False,
            "526172211a0700cf907300000d00": True,
        }
        with tempfile.TemporaryDirectory() as d:
            for i, (head, quick) in enumerate(heads.items()):
                path = os.path.join(d, "a%d" % i)
                with open(path, "wb") as f:
                    f.write(bytes.fromhex(head) + bytes(40))
                self.assertEqual(intake.quick(path), quick, head)

    def test_one_of_a_thing_has_words_of_its_own(self):
        self.assertEqual(EN("intake.songs", n=1), "1 song")
        self.assertEqual(EN("intake.songs", n=2), "2 songs")
        self.assertEqual(KO("intake.changed", n=1), "openDMT3가 바꾼 파일 1개")

    def test_the_time_left_follows_the_work_as_it_goes_now(self):
        # Half in the first 10 s, then a tenth in the next 20 s (a disk whose cache is full): the slower recent rate
        # says 80 s, where the whole work's rate would promise 20.
        seen = []
        work = unpack.Unpacking("technika3.7z", "parent", progress=lambda f, left: seen.append((f, left)))
        clock = [0.0]
        with mock.patch.object(unpack.time, "monotonic", lambda: clock[0]):
            work.started = 0.0
            for at, share in ((5, 0.25), (10, 0.5), (20, 0.55), (30, 0.6)):
                clock[0] = at
                work._progress(share)
        self.assertAlmostEqual(seen[-1][1], 80.0)
        # The first seconds say no time at all: 7-Zip is reading the archive's headers.
        early = []
        work = unpack.Unpacking("technika3.7z", "parent", progress=lambda f, left: early.append(left))
        with mock.patch.object(unpack.time, "monotonic", lambda: 2.0):
            work.started = 0.0
            work._progress(0.1)
        self.assertEqual(early, [None])

    def test_sizes_read_plainly(self):
        self.assertEqual(intake.size_words(41 << 30), "41 GB")
        self.assertEqual(intake.size_words(int(1.5 * (1 << 30))), "1.5 GB")
        self.assertEqual(intake.size_words(720 << 20), "720 MB")

    def test_every_state_has_its_words_in_both_languages(self):
        for state in (intake.READY, intake.UNPACK, intake.NOT_HERE, intake.NOT_YET, intake.CHECKING):
            for key in ("intake.state." + state, "intake.said." + state):
                en, ko = i18n.TEXT[key]
                self.assertTrue(en and ko and en != ko or state == intake.UNPACK and en, key)


class ArchivesCase(Kinds):
    """The made-up game folder and a Downloads folder beside it for its archives (no tests of its own)."""

    def setUp(self):
        super().setUp()
        self.downloads = os.path.join(self.tmp, "Downloads")
        os.makedirs(self.downloads)
        # A file of random bytes, as the game's videos are: the archive keeps its size.
        with open(os.path.join(self.root, "pack", "filler.pak"), "wb") as f:
            f.write(os.urandom(200000))

    def archive_of(self, name, *switches):
        """An archive of the game folder, under a folder named as people name theirs."""
        src = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, src)
        shutil.copytree(self.root, os.path.join(src, "TECHNIKA 3"))
        path = os.path.join(self.downloads, name)
        subprocess.run([SEVEN_ZIP, "a", "-bso0", "-bsp0"] + list(switches) + [path, "TECHNIKA 3"], cwd=src, check=True,
                       stdin=subprocess.DEVNULL)
        return path

    def leftovers(self):
        return [n for n in os.listdir(self.downloads) if n.startswith(unpack.WORK_PREFIX)]


@unittest.skipUnless(SEVEN_ZIP, "needs 7-Zip (OPENDMT3_7ZIP, or 7zz, 7z or 7za on PATH)")
class UnpackTest(ArchivesCase):

    def test_an_archive_is_unpacked_beside_it_and_the_folder_reads_ready(self):
        archive = self.archive_of("technika3.7z", "-t7z")
        found = intake.inspect(archive)
        self.assertEqual((found.state, found.inside), (intake.UNPACK, "TECHNIKA 3/"))
        seen = []
        made = unpack.Unpacking(archive, self.downloads, progress=lambda f, left: seen.append(f)).run()
        self.assertEqual(made, os.path.join(self.downloads, "technika3"))
        self.assertEqual(intake.inspect(made).state, intake.READY)
        self.assertEqual(seen[-1], 1.0)
        self.assertEqual(self.leftovers(), [])

    def test_a_zip_says_its_songs_before_it_is_unpacked(self):
        archive = self.archive_of("technika3.zip", "-tzip")
        found = intake.inspect(archive)
        self.assertEqual(found.songs, len(NEWEST_SONGS))
        self.assertTrue(found.sentence(EN).startswith("A game folder in an archive, %d songs: unpack to play ("
                                                      % len(NEWEST_SONGS)), found.sentence(EN))
        # Nothing of the look is left anywhere: the files read were taken out into a folder of its own, then removed.
        self.assertEqual(os.listdir(self.downloads), ["technika3.zip"])

    def test_a_stop_leaves_nothing_behind(self):
        archive = self.archive_of("technika3.7z", "-t7z")
        stop = threading.Event()
        stop.set()
        with self.assertRaises(unpack.Stopped):
            unpack.Unpacking(archive, self.downloads, cancel=stop).run()
        self.assertEqual(sorted(os.listdir(self.downloads)), ["technika3.7z"])

    def test_a_damaged_archive_is_said_and_leaves_nothing_behind(self):
        archive = self.archive_of("technika3.zip", "-tzip")
        with open(archive, "r+b") as f:
            f.seek(os.path.getsize(archive) // 2)
            data = f.read(64)
            f.seek(-len(data), 1)
            f.write(bytes(b ^ 0x5A for b in data))
        with self.assertRaises(Exception) as caught:
            unpack.Unpacking(archive, self.downloads).run()
        self.assertEqual(getattr(caught.exception, "key", None), "error.source.damaged")
        self.assertEqual(sorted(os.listdir(self.downloads)), ["technika3.zip"])

    def test_a_password_is_asked_for_and_checked(self):
        archive = self.archive_of("technika3.7z", "-t7z", "-pmade-up-1", "-mhe=on")
        found = intake.inspect(archive)
        self.assertEqual((found.state, found.password), (intake.UNPACK, True))
        self.assertEqual(found.line_words(EN), "This archive has a password. Enter it.")
        self.assertFalse(intake.password_opens(archive, "not-it"))
        self.assertTrue(intake.password_opens(archive, "made-up-1"))
        with self.assertRaises(Exception) as caught:
            unpack.Unpacking(archive, self.downloads, password="not-it").run()
        self.assertEqual(caught.exception.key, "error.source.wrong_password")
        made = unpack.Unpacking(archive, self.downloads, password="made-up-1").run()
        self.assertEqual(intake.inspect(made).state, intake.READY)

    def test_a_split_archive_by_its_first_part_and_a_missing_part_named_first(self):
        first = self.archive_of("technika3.7z", "-t7z", "-v60k")
        first += ".001"
        found = intake.inspect(first)
        self.assertEqual(found.state, intake.UNPACK)
        self.assertGreater(found.parts, 2)
        os.remove(first[:-4] + ".002")
        found = intake.inspect(first)
        self.assertEqual(found.sentence(EN), "Part 2 of this split archive is missing. Put every part in one folder.")
        self.assertEqual(found.sentence(KO), "분할 압축의 2번째 조각이 없습니다. 모든 조각을 한 폴더에 두세요.")
        later = intake.inspect(first[:-4] + ".003")
        self.assertEqual(later.sentence(EN), "This is part 3 of a split archive. Put every part in one folder and "
                                             "choose the first.")

    def test_an_archive_inside_an_archive_is_unpacked_through_both(self):
        inner = self.archive_of("technika3.7z", "-t7z")
        outer = os.path.join(self.downloads, "dmt3-wrapped.zip")
        subprocess.run([SEVEN_ZIP, "a", "-bso0", "-bsp0", "-tzip", outer, "technika3.7z"], cwd=self.downloads,
                       check=True, stdin=subprocess.DEVNULL)
        os.remove(inner)
        found = intake.inspect(outer)
        self.assertEqual((found.state, found.inner), (intake.UNPACK, True))
        self.assertEqual(found.line_words(EN), "It holds another archive. Both are opened.")
        made = unpack.Unpacking(outer, self.downloads).run()
        self.assertEqual(intake.inspect(made).state, intake.READY)
        self.assertEqual(self.leftovers(), [])

    def test_a_7z_that_stores_a_zip_is_read_as_the_7z_it_is(self):
        # Python's own look for a zip finds the stored zip's end near the 7z's end: the 7z's own entries count.
        inner = self.archive_of("technika3.zip", "-tzip")
        outer = os.path.join(self.downloads, "dmt3-stored.7z")
        subprocess.run([SEVEN_ZIP, "a", "-bso0", "-bsp0", "-t7z", "-mx0", outer, "technika3.zip"], cwd=self.downloads,
                       check=True, stdin=subprocess.DEVNULL)
        os.remove(inner)
        self.assertEqual([e.name for e in sources.listing(outer)], ["technika3.zip"])
        found = intake.inspect(outer)
        self.assertEqual((found.state, found.inner), (intake.UNPACK, True))
        made = unpack.Unpacking(outer, self.downloads).run()
        self.assertEqual(intake.inspect(made).state, intake.READY)

    def test_the_room_is_checked_before_anything_is_made(self):
        archive = self.archive_of("technika3.7z", "-t7z")
        with mock.patch.object(unpack, "room", lambda parent: 1000):
            with self.assertRaises(unpack.UnpackError) as caught:
                unpack.Unpacking(archive, self.downloads).run()
        self.assertEqual(caught.exception.key, "intake.line.no_space")
        self.assertTrue(EN.error(caught.exception).startswith("Not enough free space: "))
        self.assertEqual(sorted(os.listdir(self.downloads)), ["technika3.7z"])


@unittest.skipUnless(SEVEN_ZIP, "needs 7-Zip (OPENDMT3_7ZIP, or 7zz, 7z or 7za on PATH)")
class CommandLineTest(ArchivesCase):
    """--inspect, --unpack and --folder say and do what the cards and Unpack... do, in a terminal."""

    def setUp(self):
        super().setUp()
        self.config = os.path.join(self.tmp, "config")
        env = mock.patch.dict(os.environ, {"OPENDMT3_CONFIG_DIR": self.config})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        # main() opened the launcher's log in the test's own folder: closed before that folder goes, as Windows will not
        # remove a file that is open.
        import logging
        log = logging.getLogger("opendmt3")
        for handler in [h for h in log.handlers if getattr(h, "opendmt3_log", False)]:
            log.removeHandler(handler)
            handler.close()
        super().tearDown()

    def run_main(self, *argv):
        """The launcher's command line: (exit code, what it printed)."""
        import io
        from opendmt3.client import main
        out = io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", out):
            code = main.main(list(argv))
        return code, out.getvalue()

    def test_inspect_says_what_a_path_is_and_exits_by_it(self):
        code, said = self.run_main("--inspect", self.tmp)
        self.assertEqual(code, 0)
        self.assertIn("Game folder, original PC client, %d songs" % len(NEWEST_SONGS), said)
        code, said = self.run_main("--inspect", os.path.join(self.tmp, "nothing-here"))
        self.assertEqual(code, 1)
        self.assertIn("This is not there any more.", said)

    def test_an_archive_the_search_found_is_said_from_its_listing_alone(self):
        # The design: an archive found in the usual places has its entries listed, not unpacked; its songs are
        # counted once the player picks it (Choose an archive..., --inspect), or from the folder Unpack makes.
        archive = self.archive_of("technika3.zip", "-tzip")
        taken = []
        real = sources.extract

        def spy(*args, **kwargs):
            taken.append(args[0])
            return real(*args, **kwargs)
        with mock.patch.object(sources, "extract", spy), mock.patch.object(find, "paths", lambda **kw: [archive]):
            # --find, the found list's twin on the command line.
            code, said = self.run_main("--find")
            self.assertEqual(taken, [])
            self.assertIn("A game folder in an archive: unpack to play (", said)
            self.assertNotIn("songs", said)
            # The found list's own search, on a stand-in window that runs what the search's worker hands it.
            from opendmt3.client import found_list
            posted = []
            app = mock.Mock()
            app.post = posted.append
            app.state.game_folder = None
            listed = found_list.FoundList(app)
            with mock.patch.object(found_list.FoundList, "paint", lambda self: None):
                listed.search()
                for _ in range(400):
                    while posted:
                        posted.pop(0)()
                    if not listed.searching:
                        break
                    threading.Event().wait(0.05)
            self.assertEqual([(f.state, f.songs) for f in listed.items], [(intake.UNPACK, None)])
            self.assertEqual(taken, [])
            # Picked by the player (--inspect, Choose an archive...): its songs counted from its song list's files.
            code, said = self.run_main("--inspect", archive)
            self.assertIn("A game folder in an archive, %d songs: unpack to play (" % len(NEWEST_SONGS), said)
            self.assertEqual(len(taken), 1)
        self.assertEqual(os.listdir(self.downloads), ["technika3.zip"])

    def test_unpack_then_folder_take_an_archive_in_a_terminal(self):
        archive = self.archive_of("technika3.7z", "-t7z")
        into = os.path.join(self.tmp, "Games")
        code, said = self.run_main("--unpack", archive, "--to", into, "--yes")
        self.assertEqual(code, 0, said)
        self.assertIn("100%", said)
        made = os.path.join(into, "technika3")
        self.assertIn("Unpacked: %s" % made, said)
        self.assertEqual(intake.inspect(made).state, intake.READY)
        # --unpack changes nothing the launcher keeps; --folder with an archive unpacks and uses the folder.
        from opendmt3.client import state as st
        self.assertIsNone(st.LauncherState.load().game_folder)
        code, said = self.run_main("--folder", archive, "--to", into, "--yes")
        self.assertEqual(code, 0, said)
        self.assertEqual(st.LauncherState.load().game_folder, os.path.join(into, "technika3 (2)"))

    def test_a_path_that_does_not_work_here_is_said_and_nothing_changes(self):
        broken = os.path.join(self.downloads, "technika3-broken.7z")
        with open(self.archive_of("technika3.7z", "-t7z"), "rb") as f:
            data = f.read()
        with open(broken, "wb") as f:
            f.write(data[: len(data) // 2])
        code, said = self.run_main("--folder", broken, "--yes")
        self.assertEqual(code, 2)
        self.assertIn("This archive is damaged or not fully downloaded. Download it again.", said)
        from opendmt3.client import state as st
        self.assertIsNone(st.LauncherState.load().game_folder)


if __name__ == "__main__":
    unittest.main()
