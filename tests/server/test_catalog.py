"""Tests for the song list and its pictures (services/catalog.py), read from a made-up game folder's archives.

The list keeps each chart's level (STAR's column for mode 0, POP's for POP and CLUB); each song's disc picture is
read from DiscImg.pak, made small when Pillow is there, and saved beside the list. Nothing here is the game's.
"""

import io
import os
import shutil
import tempfile
import unittest

from opendmt3.core.formats import discstock
from opendmt3.server.services import catalog
from tests.core.test_setup import FolderCase

HEADER = "no\tname\tFullName\tGenre\tComposer\tStar_1\tStar_2\tStar_3\tStar_4\tPop_1\tPop_2\tPop_3\tPop_4\r\n"
LIST = (HEADER + "1\tmadeup\tMade-up Song\tPop\tComposer A\t2\t5\t9\t0\t3\t6\t10\t12\r\n"
        "2\tnodisc\tNo Picture\tRock\tComposer B\t1\t0\t0\t0\t1\t0\t0\t0\r\n").encode("utf-16")


def png(size):
    """A real PNG of `size` pixels square (Pillow), or None without Pillow."""
    try:
        from PIL import Image
    except ImportError:
        return None
    out = io.BytesIO()
    Image.new("RGBA", (size, size), (200, 40, 120, 255)).save(out, "PNG")
    return out.getvalue()


class CatalogTest(FolderCase):

    def setUp(self):
        super().setUp()
        root = self.game.root
        self._pak(os.path.join(root, "pack", "DiscInfo.pak"), {discstock.PATH: LIST})
        self.picture = png(256)
        if self.picture is not None:
            self._pak(os.path.join(root, "pack", "DiscImg.pak"),
                      {"Resource\\DiscImg\\madeup_0.png": self.picture, "Resource\\DiscImg\\madeup_1.png": self.picture})
        self.data = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.data)
        super().tearDown()

    def test_the_list_keeps_each_charts_level(self):
        self.assertEqual(catalog.import_from(self.tmp, self.data), 2)
        songs = catalog.load(self.data)
        self.assertEqual(catalog.title(songs, 1), "Made-up Song")
        self.assertEqual(catalog.level(songs, 1, 0, 3), 9)       # STAR, pattern 3
        self.assertEqual(catalog.level(songs, 1, 1, 4), 12)      # POP, pattern 4
        self.assertEqual(catalog.level(songs, 1, 2, 1), 3)       # CLUB reads POP's column
        self.assertIsNone(catalog.level(songs, 1, 0, 4))         # no such pattern (0 in the list)
        self.assertIsNone(catalog.level(songs, 1, 3, 1))         # CREW RACE has no column
        self.assertIsNone(catalog.level(songs, 9, 0, 1))         # no such song

    def test_the_list_is_read_once_kept_while_the_file_stays_and_shared_read_only(self):
        import json
        from unittest import mock
        catalog.import_from(self.tmp, self.data)
        # The file's bytes are parsed with json.loads (services/files.py reads them whole first).
        with mock.patch("json.loads", wraps=json.loads) as parsed:
            first, again = catalog.load(self.data), catalog.load(self.data)
        # Read once: the second load is the first one's answer, with no file read.
        self.assertIs(first, again)
        self.assertEqual(parsed.call_count, 1)
        # Shared, so no caller can change it for the others; a copy can be changed.
        for change in (lambda: first.__setitem__(3, {}), lambda: first[1].__setitem__("title", "x"),
                       lambda: first[1]["star"].append(1), lambda: first.pop(1), lambda: first[1].update(title="x")):
            with self.assertRaises(TypeError):
                change()
        mine = dict(first[1])
        mine["title"] = "Mine"
        self.assertEqual(catalog.title(catalog.load(self.data), 1), "Made-up Song")
        # It reads as JSON as plain data does.
        self.assertEqual(json.loads(json.dumps(first[1]))["star"], [2, 5, 9, 0])
        # A new list read from the game replaces the file: the next load has it.
        path = os.path.join(self.data, catalog.FILE)
        with open(path + ".new", "w", encoding="utf-8") as f:
            json.dump({"songs": [{"number": 1, "title": "Read Again"}]}, f)
        os.replace(path + ".new", path)
        self.assertEqual(catalog.title(catalog.load(self.data), 1), "Read Again")
        # No file: nothing, and nothing kept.
        os.remove(path)
        self.assertEqual(catalog.load(self.data), {})

    def test_a_file_windows_refuses_while_it_is_replaced_is_read_once_the_moment_passes(self):
        # On Windows a file refuses to open (PermissionError) while os.replace moves a new copy into its place: a login
        # that read the song list in that moment lost its cabinet's link, and its results. Tried again there; on any
        # other system, and on Windows once REFUSED_WAIT has passed, a refusal is a real one and is raised.
        import json
        from unittest import mock
        from opendmt3.server.services import files
        path = os.path.join(self.tmp, "replaced.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"songs": [{"number": 1, "title": "Made-up Song"}]}, f)
        real_open, refused = open, []

        def refusing(name, *args, **kwargs):
            # The file's first two opens refused, as in the moment of a replace; every other open as it is.
            if name == path and len(refused) < 2:
                refused.append(name)
                raise PermissionError(13, "Permission denied", name)
            return real_open(name, *args, **kwargs)
        with mock.patch.object(files, "_on_windows", return_value=True), mock.patch("builtins.open", refusing):
            self.assertEqual(files.load(path)["songs"][0]["title"], "Made-up Song")
        self.assertEqual(len(refused), 2)
        # A refusal that stays (another file, never read before): raised on Windows once the wait is over, after tries
        # again, and at the first try anywhere else.
        stays = os.path.join(self.tmp, "refused.json")
        with open(stays, "w", encoding="utf-8") as f:
            json.dump({"songs": []}, f)
        for windows, tries in ((True, lambda n: n > 1), (False, lambda n: n == 1)):
            tried = []

            def always(name, *args, **kwargs):
                if name == stays:
                    tried.append(name)
                    raise PermissionError(13, "Permission denied", name)
                return real_open(name, *args, **kwargs)
            with mock.patch.object(files, "_on_windows", return_value=windows), \
                    mock.patch.object(files, "REFUSED_WAIT", 0.05), mock.patch("builtins.open", always):
                with self.assertRaises(PermissionError):
                    files.load(stays)
            self.assertTrue(tries(len(tried)), (windows, len(tried)))

    @unittest.skipUnless(png(8), "needs Pillow")
    def test_a_songs_picture_is_saved_small_and_a_song_without_one_has_none(self):
        from PIL import Image
        catalog.import_from(self.tmp, self.data)
        path = catalog.jacket_path(self.data, 1)
        self.assertIsNotNone(path)
        with Image.open(path) as saved:
            self.assertEqual(saved.size, (catalog.JACKET_SIZE, catalog.JACKET_SIZE))
        self.assertIsNone(catalog.jacket_path(self.data, 2))

    @unittest.skipIf(png(4) is None, "needs Pillow")
    def test_jackets_converted_side_by_side_are_the_same_files_as_one_after_another(self):
        from unittest import mock
        from PIL import Image
        from opendmt3.server.services import pictures
        root = self.game.root
        rows, jackets = [], {}
        for n in range(1, 41):
            rows.append("%d\tsong%02d\tSong %d\tPop\tComposer\t1\t2\t3\t4\t1\t2\t3\t4\r\n" % (n, n, n))
            if n % 9 == 0:
                # Not a picture at all: left out, and said, in its place.
                jackets["Resource\\DiscImg\\song%02d_0.png" % n] = b"not a picture %d" % n
                continue
            # Sizes from small (kept as they are) to large (made smaller), each its own colours.
            size = 40 + n * 7
            picture = Image.new("RGBA", (size, size // 2 + 10), (n * 5 % 256, n * 11 % 256, n * 17 % 256, 255))
            for x in range(0, size, 5):
                picture.putpixel((x, x % (size // 2 + 10)), (255 - n, x % 256, 0, 255))
            out = io.BytesIO()
            picture.save(out, "PNG")
            jackets["Resource\\DiscImg\\song%02d_0.png" % n] = out.getvalue()
        self._pak(os.path.join(root, "pack", "DiscInfo.pak"),
                  {discstock.PATH: (HEADER + "".join(rows)).encode("utf-16")})
        self._pak(os.path.join(root, "pack", "DiscImg.pak"), jackets)

        def read(workers):
            # The whole reading, with the pictures converted on `workers` threads; every file it wrote and its lines.
            data = tempfile.mkdtemp(dir=self.data)
            with mock.patch.object(pictures, "threads", lambda: workers), \
                    self.assertLogs("opendmt3.catalog", "INFO") as lines:
                report = catalog.read(self.tmp, data)
            files = {}
            for folder, _, names in os.walk(data):
                for name in names:
                    path = os.path.join(folder, name)
                    with open(path, "rb") as f:
                        files[os.path.relpath(path, data)] = f.read()
            # The report's own moment differs between two readings, and so does the time on the DJ cards' traceback
            # (this folder has none of them) at the head of its log: the rest is the same.
            files.pop(catalog.READ_FILE)
            files[catalog.LOG_FILE] = files[catalog.LOG_FILE].split(b" ", 2)[2]
            return report["jackets"], files, [line for line in lines.output if "left out" in line]
        one, side = read(1), read(8)
        self.assertEqual(one[0], 36)
        self.assertEqual(sorted(one[1]), sorted(side[1]))
        self.assertEqual([name for name in one[1] if one[1][name] != side[1][name]], [])
        self.assertEqual(one, side)
        # The four that are not pictures said in the songs' order.
        self.assertEqual([line.split("song ")[1].split(":")[0] for line in side[2]], ["9", "18", "27", "36"])

    def test_a_game_folder_without_pictures_still_gives_the_list(self):
        os.remove(os.path.join(self.game.root, "pack", "DiscImg.pak")) if self.picture is not None else None
        # Nothing at ERROR: a missing optional part is a plain line, its traceback in the data folder's log.
        with self.assertNoLogs("opendmt3.catalog", level="INFO"):
            self.assertEqual(catalog.import_from(self.tmp, self.data), 2)
        self.assertIsNone(catalog.jacket_path(self.data, 1))

    def test_each_part_is_one_plain_line_and_a_missing_one_says_what_still_works(self):
        os.remove(os.path.join(self.game.root, "pack", "DiscImg.pak")) if self.picture is not None else None
        report = catalog.read(self.tmp, self.data, now=1000)
        self.assertEqual((report["at"], report["songs"], report["jackets"], report["cards"]), (1000, 2, None, None))
        self.assertEqual(report["folder"], self.game.root)
        # The jackets' files are not there; the DJ cards' are not either. Each in the words a person reads, by key too.
        self.assertEqual(report["missing"], {"jackets": "The game's files have no jackets.",
                                             "cards": "The game's files have no DJ cards."})
        self.assertEqual(report["reasons"], {"jackets": "error.game.no_jackets", "cards": "error.card.tables"})
        self.assertEqual(catalog.lines(report), [
            (True, "song list: 2 songs"),
            (False, "jackets: not yet, songs show without them. The game's files have no jackets."),
            (False, "DJ cards: not yet, every DJ card keeps the basic icon and plate. The game's files have no DJ "
                    "cards.")])
        # The tracebacks are in the data folder's log, and the report is kept for the Status page.
        with open(os.path.join(self.data, catalog.LOG_FILE), encoding="utf-8") as f:
            kept = f.read()
        self.assertIn("jackets could not be read", kept)
        self.assertIn("Traceback (most recent call last)", kept)
        self.assertEqual(catalog.read_report(self.data)["missing"], report["missing"])

    def test_the_log_of_tracebacks_stays_small(self):
        path = os.path.join(self.data, catalog.LOG_FILE)
        with open(path, "w") as f:
            f.write("x" * (catalog.LOG_MOST + 1))
        catalog.keep_trace(self.data, "jackets", ValueError("made up"))
        # The full one became the one before; the new one starts with this trace.
        self.assertEqual(os.path.getsize(path + ".1"), catalog.LOG_MOST + 1)
        self.assertLess(os.path.getsize(path), 1000)

    def test_the_survey_says_what_a_read_would_find_without_saving_anything(self):
        found = catalog.survey(self.tmp)
        self.assertEqual((found["folder"], found["client"], found["songs"], found["problem"]),
                         (self.game.root, True, 2, None))
        self.assertEqual(found["jackets"], 1 if self.picture is not None else None)
        self.assertEqual(found["missing"]["cards"], "The game's files have no DJ cards.")
        # Nothing was written.
        self.assertEqual(os.listdir(self.data), [])
        # No game folder at or below a path: one line, the problem, and nothing else.
        empty = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, empty)
        nothing = catalog.survey(empty)
        self.assertIsNone(nothing["folder"])
        self.assertEqual(catalog.lines(nothing), [(False, nothing["problem"])])
        self.assertEqual(nothing["problem"], "This is neither a game folder nor an archive holding one.")

    def test_a_song_list_that_is_not_the_games_text_is_said_never_raised_as_a_traceback(self):
        from opendmt3.core import game as g
        # A half-written list (an odd number of bytes, which UTF-16 cannot decode), an empty one, and text that is
        # not the game's table (its columns start with the number and the internal name).
        for raw in (b"no\r\n\x00", b"", "garbage\r\n1\t2\r\n".encode("utf-16")):
            self._pak(os.path.join(self.game.root, "pack", "DiscInfo.pak"), {discstock.PATH: raw})
            found = catalog.survey(self.tmp)
            self.assertIsNone(found["songs"])
            self.assertEqual(found["problem"], "The file with the song list is damaged. Copy the game folder again, or "
                                               "unpack the archive again.")
            # The reading says it as the list that cannot be read, which every caller already handles.
            with self.assertRaises(g.GameError) as raised:
                catalog.read(self.tmp, self.data)
            self.assertEqual(raised.exception.key, "error.game.damaged.songs")

    def test_a_folder_without_a_client_the_server_can_read_stops_the_survey(self):
        from unittest import mock
        from opendmt3.core import game as g
        refusal = g.GameError("The game's files cannot be opened with this client.", "error.game.no_table")
        with mock.patch.object(g.Game, "table", side_effect=refusal):
            found = catalog.survey(self.tmp)
        self.assertEqual((found["folder"], found["client"], found["songs"]), (self.game.root, False, None))
        self.assertEqual((found["problem"], found["problem_key"]),
                         ("The game's files cannot be opened with this client.", "error.game.no_table"))

    def test_the_server_prints_each_part_and_a_list_it_cannot_read_as_one_line(self):
        import contextlib
        from opendmt3.server import __main__ as server
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(server.read_catalog(self.tmp, self.data), 0)
        self.assertIn("song list: 2 songs\n", out.getvalue())
        self.assertIn("DJ cards: not yet", out.getvalue())
        self.assertNotIn("Traceback", out.getvalue() + err.getvalue())
        # A folder with no game: one line, exit 2, the traceback only in the log.
        empty = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, empty)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(server.read_catalog(empty, self.data), 2)
        self.assertEqual(out.getvalue(), "song list: not read. This is neither a game folder nor an archive holding "
                                         "one.\n")
        self.assertNotIn("Traceback", out.getvalue() + err.getvalue())

    def test_the_status_page_state_counts_each_part_and_names_what_is_missing(self):
        # Before any reading: every part missing, never read.
        self.assertEqual([m["part"] for m in catalog.state(self.data)["missing"]], ["songs", "jackets", "cards"])
        catalog.read(self.tmp, self.data, now=1000)
        state = catalog.state(self.data)
        self.assertEqual(state["songs"]["count"], 2)
        self.assertIsNotNone(state["songs"]["at"])
        self.assertEqual(state["read_at"], 1000)
        missing = {m["part"]: m["why"] for m in state["missing"]}
        # The card tables were not there; their reason is the last reading's.
        self.assertEqual(missing["cards"], "The game's files have no DJ cards.")
        self.assertEqual(state["source"], {"from": "folder", "path": self.game.root, "made": None})
        if self.picture is not None:
            self.assertEqual(state["jackets"]["count"], 1)
            self.assertNotIn("jackets", missing)

    # Root and owners are a Linux server's (Windows has neither: writer_for is None there, so the walk never runs).
    @unittest.skipUnless(os.name == "posix", "root and the owners of folders as a Linux server has them")
    def test_root_gives_what_it_wrote_to_the_data_folders_owner(self):
        from unittest import mock
        catalog.read(self.tmp, self.data)
        with mock.patch.object(catalog, "writer_for", return_value=(4725, 4725)), \
                mock.patch.object(catalog.os, "chown", create=True) as chown:
            catalog.give_to_owner(self.data)
        given = {os.path.relpath(c.args[0], self.data) for c in chown.call_args_list}
        self.assertIn(catalog.FILE, given)
        self.assertIn(catalog.READ_FILE, given)
        self.assertTrue(all(c.args[1:] == (4725, 4725) for c in chown.call_args_list))
        # Not root (writer_for's own answer as anyone but root): nothing changes hands.
        with mock.patch.object(catalog.os, "geteuid", return_value=1000, create=True), \
                mock.patch.object(catalog.os, "chown", create=True) as chown:
            self.assertIsNone(catalog.writer_for(self.data))
            catalog.give_to_owner(self.data)
        chown.assert_not_called()


@unittest.skipUnless(os.name == "posix", "links and owners as a Linux server has them")
class LinksTest(FolderCase):
    """Links someone left in a data folder (the security review's proof 4): the server never writes through one, never
    gives one or what it leads to away, and run as root it writes a folder someone else owns as that owner alone."""

    def setUp(self):
        super().setUp()
        self._pak(os.path.join(self.game.root, "pack", "DiscInfo.pak"), {discstock.PATH: LIST})
        self.data = os.path.join(self.tmp, "data")
        self.outside = os.path.join(self.tmp, "outside")
        os.makedirs(self.data)
        os.makedirs(self.outside)
        # What is not the data folder's: a file of settings, a log, a lock, and a folder with a file in it.
        for name in ("other.conf", "log", "lock", "new.json"):
            with open(os.path.join(self.outside, name), "w") as f:
                f.write("someone else's %s\n" % name)
        os.makedirs(os.path.join(self.outside, "kept"))
        with open(os.path.join(self.outside, "kept", "kept.txt"), "w") as f:
            f.write("someone else's\n")
        # The links, where the reading writes: the report's and the list's new copies, the log, the lock, the DJ
        # cards' folder (a game folder without them leaves it as it is) and the jackets' folder.
        for name, target in ((catalog.READ_FILE + ".new", "other.conf"), (catalog.FILE + ".new", "new.json"),
                             (catalog.LOG_FILE, "log"), (catalog.LOCK_FILE, "lock"), ("cards", "kept")):
            os.symlink(os.path.join(self.outside, target), os.path.join(self.data, name))

    def outside_now(self):
        """Every file outside the data folder: its bytes and its owner."""
        out = {}
        for here, _, names in os.walk(self.outside):
            for name in names:
                path = os.path.join(here, name)
                with open(path, "rb") as f:
                    out[os.path.relpath(path, self.outside)] = (f.read(), os.stat(path).st_uid)
        return out

    def test_links_left_in_the_data_folder_are_never_written_through(self):
        from unittest import mock
        before = self.outside_now()
        report = catalog.read(self.tmp, self.data)
        self.assertEqual(report["songs"], 2)
        self.assertEqual(self.outside_now(), before)
        # The report and the list are files of the data folder's own; the link at the DJ cards' name is left alone.
        for name in (catalog.FILE, catalog.READ_FILE):
            self.assertFalse(os.path.islink(os.path.join(self.data, name)), name)
        self.assertEqual(catalog.read_report(self.data)["songs"], 2)
        # Root's walk to give what it wrote to the folder's owner passes the link by, and what it leads to.
        with mock.patch.object(catalog, "writer_for", return_value=(4725, 4725)), \
                mock.patch.object(catalog.os, "chown", create=True) as chown:
            catalog.give_to_owner(self.data)
        given = [c.args[0] for c in chown.call_args_list]
        self.assertFalse([p for p in given if "kept" in p or p.startswith(self.outside)], given)
        self.assertIn(os.path.join(self.data, catalog.FILE), given)

    @unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() == 0, "needs root, as ./dmt3 catalog runs it")
    def test_root_writes_a_data_folder_someone_else_owns_as_that_owner(self):
        import subprocess
        import sys
        # The data folder is the server user's (as Docker's volume is); every folder on its way open to that user.
        os.chown(self.data, 4725, 4725)
        os.chmod(self.tmp, 0o755)
        before = self.outside_now()
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        # The server's own command line in a process of its own, as root, with the made-up folder's table (its
        # stand-in client holds none).
        run = ("import sys; from unittest import mock; from opendmt3.core import game as g; "
               "mock.patch.object(g.Game, 'table', lambda game: bytes.fromhex(sys.argv[1])).start(); "
               "from opendmt3.server.__main__ import main; sys.exit(main(sys.argv[2:]))")
        done = subprocess.run([sys.executable, "-c", run, self.table.hex(), "--data", self.data, "--catalog",
                               self.tmp, "--setup-only"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL, timeout=120)
        said = done.stdout.decode("utf-8", "replace")
        self.assertEqual(done.returncode, 0, said)
        self.assertIn("song list: 2 songs", said)
        # Nothing outside it written or given away; what it holds now is the owner's.
        self.assertEqual(self.outside_now(), before)
        for name in (catalog.FILE, catalog.READ_FILE):
            st = os.lstat(os.path.join(self.data, name))
            self.assertEqual((st.st_uid, os.path.islink(os.path.join(self.data, name))), (4725, False), name)
        self.assertEqual(catalog.read_report(self.data)["from"], "folder")

    @unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() == 0, "needs root, as ./dmt3 catalog --save runs it")
    def test_root_saves_a_song_list_into_a_folder_someone_else_owns_as_that_owner(self):
        import subprocess
        import sys
        from opendmt3.server.services import pictures, songlist
        if not pictures.available():
            self.skipTest("needs Pillow (a saved song list is checked as a server takes it)")
        # The folder --save writes in is someone else's, with a link where the file's new copy is written.
        out = os.path.join(self.tmp, "out")
        os.makedirs(out)
        os.symlink(os.path.join(self.outside, "other.conf"), os.path.join(out, songlist.NAME + ".new"))
        os.chown(out, 4725, 4725)
        os.chmod(self.tmp, 0o755)
        before = self.outside_now()
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        run = ("import sys; from unittest import mock; from opendmt3.core import game as g; "
               "mock.patch.object(g.Game, 'table', lambda game: bytes.fromhex(sys.argv[1])).start(); "
               "from opendmt3.server.__main__ import main; sys.exit(main(sys.argv[2:]))")
        done = subprocess.run([sys.executable, "-c", run, self.table.hex(), "--data", self.data, "--catalog", self.tmp,
                               "--save", out], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL, timeout=120)
        said = done.stdout.decode("utf-8", "replace")
        self.assertEqual(done.returncode, 0, said)
        self.assertEqual(self.outside_now(), before)
        saved = os.lstat(os.path.join(out, songlist.NAME))
        self.assertEqual((saved.st_uid, os.path.islink(os.path.join(out, songlist.NAME))), (4725, False))
        self.assertEqual(songlist.look(os.path.join(out, songlist.NAME))["songs"], 2)


class SwapTest(unittest.TestCase):
    """A reading's parts moved into place together or not at all (the security review's proof 6): whatever move fails,
    the song list, the jackets, the DJ cards and the report are all the ones before."""

    NAMES = ("catalog.json", "jackets/1.png", "cards.json", "cards/icon/1.png", catalog.READ_FILE)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def put(self, folder, word):
        for name in self.NAMES[:-1]:
            path = os.path.join(folder, *name.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(word)

    def contents(self, data):
        out = {}
        for name in self.NAMES:
            with open(os.path.join(data, *name.split("/"))) as f:
                out[name] = f.read()
        return out

    def test_a_failed_move_puts_every_part_and_the_report_back(self):
        from unittest import mock
        real = os.replace
        report = {"at": 2, "missing": {}}
        # The move of the DJ cards' table aside (the last part), then the report's move into place: each made to fail.
        for case, fails in (("the DJ cards' table", lambda src, dst: os.path.basename(dst) == "cards.json"),
                            ("the report", lambda src, dst: os.path.basename(src) == catalog.READ_FILE
                             and ".song-list-" in src and ".before" not in src)):
            with self.subTest(case=case):
                data = os.path.join(self.tmp, case)
                self.put(data, "old")
                catalog._save_report(data, {"at": 1, "missing": {}})
                before = self.contents(data)
                staging = catalog.new_staging(data)
                self.put(staging, "new")

                def failing(src, dst, fails=fails):
                    if fails(src, dst):
                        raise OSError("made to fail")
                    return real(src, dst)
                with mock.patch.object(catalog.os, "replace", failing), self.assertRaises(OSError):
                    catalog.swap_in(staging, data, report)
                self.assertEqual(self.contents(data), before)
                catalog.remove(staging)
        # Nothing made to fail: every part and the report are the new ones.
        data = os.path.join(self.tmp, "whole")
        self.put(data, "old")
        staging = catalog.new_staging(data)
        self.put(staging, "new")
        catalog.swap_in(staging, data, report)
        moved = self.contents(data)
        self.assertEqual([moved[n] for n in self.NAMES[:-1]], ["new"] * 4)
        self.assertEqual(catalog.read_report(data), report)


if __name__ == "__main__":
    unittest.main()
