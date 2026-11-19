"""The in-game test's pacing judgment (tests/e2e/windows/ingame/pace.py): a phase of a part of the layer that misses
60 a second is confirmed by the part's next judged phase before the part fails. A single stall of the machine (one
frame of some 30 ms, whose spread shows in the one or two windows round it) misses one phase; what openDMT3 adds is in
every frame it draws and misses every one. The threshold stays as it is: 59.5 a second with a spread under 0.5 ms in
most of a phase's two-second windows.

The layer's log and the test's marks are made here in their real forms (a counter line every two seconds, a mark a
phase edge with the machine's load), with numbers made up for each case.
"""
import contextlib
import importlib.util
import io
import os
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location("pace", os.path.join(ROOT, "tests", "e2e", "windows", "ingame", "pace.py"))
pace = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(pace)

# A phase of 8 s holds three whole two-second windows.
PHASE_MS = 8000
EVEN = [0.00, 0.01, 0.00]
# One stall of the machine: its long frame and the frame after it spread two of the phase's windows.
STALL = [1.60, 0.70, 0.00]


def judge(rounds):
    """pace.py over rounds of phases: each round a list of (name, the spreads of its windows), the phases of nothing
    between the parts as the test makes them. (exit code, what it printed)."""
    phases = []
    for parts in rounds:
        phases.append(("nothing", EVEN))
        for name, spreads in parts:
            phases += [(name, spreads), ("nothing", EVEN)]
    log, marks = [], []
    t = 1_000_000
    # The counter's lines fall 1 s after each phase's start: the line there ends a window that crosses into the phase.
    log.append("%d frames: 60.0 a second, frame time 16.67 ms (sd 0.00, 99 %% within 17.00, longest 17.00, over 20 ms "
               "0.0 %%); openDMT3 30.0 us a frame (longest 60.0)" % (t + 1000))
    for name, spreads in phases:
        marks.append("%s start %d 2.0 1.0 1.0" % (name, t))
        # Three windows inside the phase, each line at a window's end.
        for k, sd in enumerate(spreads):
            log.append("%d frames: 60.0 a second, frame time 16.67 ms (sd %.2f, 99 %% within 17.00, longest 17.00, "
                       "over 20 ms 0.0 %%); openDMT3 30.0 us a frame (longest 60.0)" % (t + 1000 + 2000 * (k + 1), sd))
        # The phase ends after its third window and before the next line.
        marks.append("%s end %d 2.0 1.0 1.0" % (name, t + PHASE_MS))
        t += PHASE_MS
        # The line at the phase's edge (its window crosses two phases: in neither).
        log.append("%d frames: 60.0 a second, frame time 16.67 ms (sd 0.00, 99 %% within 17.00, longest 17.00, over 20 "
                   "ms 0.0 %%); openDMT3 30.0 us a frame (longest 60.0)" % (t + 1000))
    with tempfile.TemporaryDirectory() as d:
        log_path, marks_path = os.path.join(d, "ingame.log"), os.path.join(d, "pace-marks.txt")
        with open(log_path, "w") as f:
            f.write("\n".join(log) + "\n")
        with open(marks_path, "w") as f:
            f.write("\n".join(marks) + "\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self_exit() as code:
            pace.main(log_path, marks_path, 5.0)
    return code[0], out.getvalue()


@contextlib.contextmanager
def self_exit():
    """pace.main ends with sys.exit: its code, kept."""
    code = [None]
    try:
        yield code
    except SystemExit as e:
        code[0] = e.code


class PaceTest(unittest.TestCase):
    def test_a_single_stall_is_judged_again_and_passes_when_the_next_phase_holds(self):
        code, out = judge([[("bar", STALL)], [("bar", EVEN)]])
        self.assertEqual(code, 0, out)
        self.assertIn("its next judged phase decides", out)
        self.assertIn("failed: none", out)

    def test_two_judged_phases_in_a_row_that_miss_fail_the_part(self):
        code, out = judge([[("bar", STALL)], [("bar", STALL)]])
        self.assertEqual(code, 1, out)
        self.assertIn("the second time in a row", out)
        self.assertIn("failed: bar", out)

    def test_a_miss_with_no_judged_phase_after_it_asks_for_another_round(self):
        # The gate's own case on 0.4.0: the bar missed once in the only round, every other part held.
        code, out = judge([[("chip", EVEN), ("bar", STALL), ("question", EVEN), ("menu", EVEN), ("toast", EVEN)]])
        self.assertEqual(code, 2, out)
        self.assertIn("to judge again: bar; failed: none", out)

    def test_a_part_that_held_and_then_missed_is_judged_again(self):
        code, out = judge([[("question", EVEN)], [("question", STALL)]])
        self.assertEqual(code, 2, out)
        self.assertIn("to judge again: question", out)

    def test_misses_apart_from_each_other_never_add_up_to_a_failure(self):
        code, out = judge([[("menu", STALL)], [("menu", EVEN)], [("menu", STALL)], [("menu", EVEN)]])
        self.assertEqual(code, 0, out)

    def test_the_threshold_is_the_same_for_both_phases(self):
        # A spread just over the limit in two windows of three misses; just under it holds, in either phase.
        self.assertFalse(pace.held([(2000, 0, 60.0, 0.51), (4000, 2000, 60.0, 0.51), (6000, 4000, 60.0, 0.0)]))
        self.assertTrue(pace.held([(2000, 0, 60.0, 0.49), (4000, 2000, 60.0, 0.49), (6000, 4000, 60.0, 0.0)]))
        self.assertFalse(pace.held([(2000, 0, 59.4, 0.0), (4000, 2000, 59.4, 0.0), (6000, 4000, 60.0, 0.0)]))

    def test_each_verdict_from_a_parts_judged_phases(self):
        self.assertEqual(pace.verdict([]), "none")
        self.assertEqual(pace.verdict([True]), "held")
        self.assertEqual(pace.verdict([False]), "again")
        self.assertEqual(pace.verdict([False, True]), "held")
        self.assertEqual(pace.verdict([False, False]), "failed")
        self.assertEqual(pace.verdict([True, False, True, False]), "again")
        self.assertEqual(pace.verdict([False, False, True]), "failed")


if __name__ == "__main__":
    unittest.main()
