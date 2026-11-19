"""The sound file the launcher and the in-game layer both write (opendmt3/client/sound_file.py and
native/cardreader/soundset.c): the one rule for its lines, read from the table both sides' tests read, and the
launcher's changes that cannot be written kept until they are (never undone by the file's older value)."""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from opendmt3.client import sound_file
from opendmt3.client import state as st

TABLE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "sound_lines.txt")


def table():
    """The shared table's lines: (the file's line as written, the line itself, the value read or None)."""
    rows = []
    with open(TABLE, encoding="utf-8") as f:
        for raw in f.read().split("\n"):
            if not raw or raw.startswith("#"):
                continue
            text, _, want = raw.rpartition("\t")
            # \t a tab, \r a carriage return, \B a byte order mark (as test_native.c reads them).
            line = text.replace("\\t", "\t").replace("\\r", "\r").replace("\\B", sound_file.BOM)
            rows.append((text, line, None if want == "-" else int(want)))
    return rows


class SoundFileTest(unittest.TestCase):

    def setUp(self):
        self.config = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"OPENDMT3_CONFIG_DIR": self.config})
        self.env.start()
        # A writer's wait for the lock, short in the tests (a second in the launcher).
        self.wait = mock.patch.object(sound_file, "LOCK_WAIT", 0.1)
        self.wait.start()
        self.path = os.path.join(self.config, "sound.ini")

    def tearDown(self):
        self.wait.stop()
        self.env.stop()
        shutil.rmtree(self.config, ignore_errors=True)

    def hold_lock(self):
        """The file's lock held as another writer holds it (the game, mid-write): the descriptor to let it go."""
        if sys.platform == "win32":
            # Windows: the lock file opened shared with nobody, as sound_file and the game's layer hold it.
            import ctypes
            import msvcrt
            from ctypes import wintypes
            create = ctypes.windll.kernel32.CreateFileW
            create.restype = wintypes.HANDLE
            handle = create(self.path + ".lock", 0xC0000000, 0, None, 4, 0x80, None)
            self.assertNotEqual(handle, wintypes.HANDLE(-1).value)
            # A descriptor over the handle, so os.close lets it go as on Linux.
            return msvcrt.open_osfhandle(handle, os.O_RDWR)
        import fcntl
        fd = os.open(self.path + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    def test_every_line_of_the_shared_table_is_read_as_it_says(self):
        rows = table()
        # The table is the one the game's test reads too; enough of it to cover the rule.
        self.assertGreaterEqual(len(rows), 20)
        for text, line, want in rows:
            with self.subTest(line=text):
                got = sound_file.parse(line)
                self.assertEqual(next(iter(got.values()), None), want)

    def test_a_line_the_rule_does_not_take_is_said_and_kept_at_a_write(self):
        refused = []
        self.assertEqual(sound_file.parse("master_volume=0x20\nkey_volume=40\n", refused), {"key_volume": 40})
        self.assertEqual(refused, ["master_volume=0x20"])
        # A write keeps another line as it is (bad or a comment), drops a byte order mark at the start, and writes the
        # first line after it as a value's.
        merged = sound_file.merge(sound_file.BOM + "master_volume=55\n# mine\neq_1k=1_0\n", {"master_volume": 10})
        self.assertEqual(merged, "master_volume=10\n# mine\neq_1k=1_0\n")

    def test_a_change_the_held_lock_keeps_out_waits_and_is_never_undone_by_a_sync(self):
        state = st.LauncherState.load()
        # Loading the settings only reads (a command that only reads leaves no file); the window's first sync (its
        # Sound page, PLAY) makes the file from the launcher's values.
        self.assertFalse(os.path.exists(self.path))
        state.sync_sound()
        self.assertEqual(sound_file.read(self.path)["master_volume"], 100)
        fd = self.hold_lock()
        try:
            with self.assertLogs("opendmt3.launcher", "WARNING") as said:
                state.set_value("master_volume", 40)
            self.assertIn("kept, written at the next sync", "\n".join(said.output))
            # The state has it, the file not yet, and it waits.
            self.assertEqual(state.values["master_volume"], 40)
            self.assertEqual(state.sound_waiting, {"master_volume": 40})
            # A sync while the lock is still held (the Sound page drawn, PLAY): the file's older 100 never takes its
            # place (the review found the slider jumping back here).
            state.sync_sound()
            self.assertEqual(state.values["master_volume"], 40)
        finally:
            os.close(fd)
        # Let go: the next sync writes it, and it waits no more.
        state.sync_sound()
        self.assertEqual(sound_file.read(self.path)["master_volume"], 40)
        self.assertEqual(state.sound_waiting, {})
        self.assertEqual(state.values["master_volume"], 40)

    def test_a_change_a_read_only_file_refuses_waits_across_a_restart(self):
        state = st.LauncherState.load()
        refused = PermissionError(13, "Access is denied")
        real_replace = os.replace

        def replace(src, dst):
            # The swap onto the sound file refused, as Windows refuses it onto a read-only file or one another program
            # holds open; launcher.json's own swap goes through.
            if os.path.basename(dst) == "sound.ini":
                raise refused
            return real_replace(src, dst)

        with mock.patch.object(sound_file.os, "replace", side_effect=replace):
            with self.assertLogs("opendmt3.launcher", "WARNING"):
                state.set_value("eq_1k", 5)
            state.sync_sound()
            self.assertEqual(state.values["eq_1k"], 5)
            self.assertEqual(state.sound_waiting, {"eq_1k": 5})
            # No temporary left beside the file by the failed swaps.
            self.assertEqual([n for n in os.listdir(self.config) if n.startswith(".sound-")], [])
            state.save()
        # The launcher closed and opened again: the change still waits (loading only reads), and is written at its
        # first sync, with the value the state kept all along.
        again = st.LauncherState.load()
        self.assertEqual((again.sound_waiting, again.values["eq_1k"]), ({"eq_1k": 5}, 5))
        again.sync_sound()
        self.assertEqual(again.sound_waiting, {})
        self.assertEqual(again.values["eq_1k"], 5)
        self.assertEqual(sound_file.read(self.path)["eq_1k"], 5)

    def test_the_launcher_reads_under_the_lock_and_not_past_its_wait(self):
        sound_file.write(self.path, {"master_volume": 70})
        fd = self.hold_lock()
        try:
            # Held past the wait: read as it is (a second at most in the launcher), never left without values.
            self.assertEqual(sound_file.read(self.path)["master_volume"], 70)
        finally:
            os.close(fd)
        # The lock file stays where it is outside Windows (taking it away while held would let a third writer lock a
        # new file beside it).
        self.assertTrue(os.path.exists(self.path + ".lock"))


if __name__ == "__main__":
    unittest.main()
