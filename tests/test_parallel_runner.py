"""tests/parallel.py, the runner ./dmt3 test and CI run the unit tests with: what it hands out (whole classes, a long
one in pieces, the longest first, or a seed's order, from the last run's times or a damaged file of them), what a
process sends back for a piece (tests/parallel_samples.py: a pass, a failure, an error, a skip, a test writing and
reading), a process that ends while it runs a piece or sends back something else, and a module that does not import."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from tests import parallel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class UnitsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def units(self, found, times, jobs=2, shuffle=None):
        # The last run's times as a file (bytes as they are, for a damaged one), or none at all (None).
        path = os.path.join(self.tmp, "times.json")
        if times is not None:
            with open(path, "wb") as f:
                f.write(times if isinstance(times, bytes) else json.dumps(times).encode("utf-8"))
        with mock.patch.object(parallel, "TIMES", path):
            return parallel.units(found, jobs, shuffle)

    def test_a_long_class_is_cut_into_pieces_in_order_and_the_longest_go_first(self):
        found = {"a.Long": ["a.Long.t%d" % i for i in range(6)], "a.Short": ["a.Short.t"], "a.Mid": ["a.Mid.t1", "a.Mid.t2"]}
        units = self.units(found, {"a.Long": 12.0, "a.Short": 0.5, "a.Mid": 1.5})
        # A third of a process's share is (14 / 2) / 3 = 2.3 s: the 12-second class in pieces of its tests, in order.
        long_pieces = [tests for label, tests, _ in units if label.startswith("a.Long")]
        self.assertGreater(len(long_pieces), 1)
        self.assertEqual(sum(long_pieces, []), found["a.Long"])
        # The others whole, and the longest first.
        self.assertIn(("a.Short", ["a.Short.t"], 0.5), units)
        self.assertEqual([seconds for _, _, seconds in units], sorted((s for _, _, s in units), reverse=True))

    def test_without_times_the_most_tests_go_first_and_a_seed_gives_one_order(self):
        found = {"a.Few": ["a.Few.t"], "a.Many": ["a.Many.t%d" % i for i in range(5)]}
        self.assertEqual(self.units(found, {}, jobs=1)[0][0], "a.Many")
        first = self.units(found, {}, jobs=1, shuffle=7)
        self.assertEqual(self.units(found, {}, jobs=1, shuffle=7), first)

    def test_a_damaged_file_of_times_hands_out_every_test_once_by_their_number(self):
        found = {"a.Few": ["a.Few.t"], "a.Many": ["a.Many.t%d" % i for i in range(5)]}
        whole = json.dumps({"a.Few": 9.0, "a.Many": 1.0}).encode("utf-8")
        damaged = [None, b"", whole[:len(whole) // 2], b"\xff\xfe\x00 not text", b"[1, 2, 3]", b"null",
                   b'{"a.Few": null, "a.Many": "fast"}', b'{"a.Few": -5, "a.Many": true}',
                   b'{"a.Few": NaN, "a.Many": Infinity}', b'{"a.Few": [9]}']
        for times in damaged:
            with self.subTest(times=times):
                units = self.units(found, times, jobs=1)
                # Nothing read as a time: each test once, and the class with more tests first.
                self.assertEqual(sorted(t for _, tests, _ in units for t in tests),
                                 sorted(found["a.Few"] + found["a.Many"]))
                self.assertEqual(units[0][0], "a.Many")
        # A whole file is read: the class it says is longer goes first.
        self.assertEqual(self.units(found, whole, jobs=1)[0][0], "a.Few")

    def test_what_alone_names_is_found_and_taken_out_of_its_class(self):
        # Every test ALONE names is one there is (a name gone stale would let it run beside the others again).
        for test_id in parallel.ALONE:
            with self.subTest(test=test_id):
                suite = unittest.TestLoader().loadTestsFromName(test_id)
                self.assertEqual(suite.countTestCases(), 1)
                self.assertNotIn("_FailedTest", repr(suite))
        name, test_id = next(iter(parallel.ALONE)).rsplit(".", 1)[0], next(iter(parallel.ALONE))
        found = {name: [name + ".test_other", test_id], "a.Else": ["a.Else.t"]}
        pool, alone = parallel.split_alone(found)
        self.assertEqual(pool, {name: [name + ".test_other"], "a.Else": ["a.Else.t"]})
        self.assertEqual(alone, {name: [test_id]})

    def test_a_module_that_does_not_import_is_run_by_the_runner_to_say_why(self):
        broken = unittest.TestLoader().loadTestsFromName("tests.parallel_samples_not_there")
        with mock.patch.object(unittest.TestLoader, "discover", return_value=unittest.TestSuite([broken])):
            found, failed = parallel.classes()
        self.assertEqual((found, len(failed)), ({}, 1))
        result = unittest.TestResult()
        unittest.TestSuite(failed).run(result)
        self.assertIn("parallel_samples_not_there", result.errors[0][1])


class ProcessTest(unittest.TestCase):
    def test_a_process_sends_back_each_pieces_counts_and_words(self):
        piece = {"label": "tests.parallel_samples.Samples", "tests": [
            "tests.parallel_samples.Samples.%s" % name for name in
            ("test_passes", "test_fails", "test_errs", "test_skipped", "test_writes_and_reads_without_harm")]}
        done = subprocess.run([sys.executable, "-m", "tests.parallel", "--worker"], cwd=ROOT, capture_output=True,
                              text=True, input=json.dumps(piece) + "\n", timeout=120)
        lines = done.stdout.splitlines()
        # One line back, the piece's: what the tests printed went to the process's errors, not among the results.
        self.assertEqual(len(lines), 1, done.stdout)
        result = json.loads(lines[0])
        self.assertEqual((result["class"], result["run"], result["skipped"]), (piece["label"], 5, 1))
        self.assertEqual([t for t, _ in result["failures"]], ["tests.parallel_samples.Samples.test_fails"])
        self.assertIn("made-up failure", result["failures"][0][1])
        self.assertEqual([t for t, _ in result["errors"]], ["tests.parallel_samples.Samples.test_errs"])
        self.assertIn("a line a test printed", done.stderr)

    def test_a_failing_piece_says_what_its_tests_printed_and_a_passing_one_does_not(self):
        printing = "tests.parallel_samples.Samples.test_writes_and_reads_without_harm"
        pieces = [("a failing piece", [printing, "tests.parallel_samples.Samples.test_fails"], 1.0),
                  ("a passing piece", [printing], 0.5)]
        with mock.patch("builtins.print"):
            results = {r["class"]: r for r in parallel.Runner(pieces, 1, False).run()}
        # Only what that piece printed: the two pieces ran on one process, the passing one second or first.
        self.assertEqual(results["a failing piece"]["printed"].count("a line a test printed"), 1)
        self.assertNotIn("printed", results["a passing piece"])

    def test_a_process_that_ends_is_an_error_of_its_piece_and_the_rest_still_runs(self):
        pieces = [("tests.parallel_samples.Crash", ["tests.parallel_samples.Crash.test_ends_its_process"], 1.0),
                  ("tests.parallel_samples.Samples [1/1]", ["tests.parallel_samples.Samples.test_passes"], 0.5)]
        runner = parallel.Runner(pieces, 1, False)
        with mock.patch("builtins.print"):
            results = runner.run()
        by_label = {r["class"]: r for r in results}
        # The piece's error says how its process ended, and what it printed last.
        error = by_label["tests.parallel_samples.Crash"]["errors"][0][1]
        self.assertIn("ended (exit 3)", error)
        self.assertIn("the made-up last words", error)
        # The next piece on a new process, and nothing the tests printed kept after the run.
        self.assertEqual(by_label["tests.parallel_samples.Samples [1/1]"]["run"], 1)
        self.assertEqual(by_label["tests.parallel_samples.Samples [1/1]"]["failures"], [])
        self.assertFalse(os.path.exists(runner.logs))

    def test_a_process_that_sends_back_something_else_is_stopped_and_its_piece_an_error(self):
        pieces = [("a.One", ["a.One.t"], 1.0), ("a.Two", ["a.Two.t"], 1.0)]
        runner = parallel.Runner(pieces, 1, False)
        # A process that answers a piece with a line that is no result, then would wait a minute (one handed nothing
        # ends, as the runner's own processes do when their input closes).
        runner.command = [sys.executable, "-c", "import sys, time\nif sys.stdin.readline():\n    print('not a result')"
                                                "\n    sys.stdout.flush()\n    time.sleep(60)"]
        started = time.monotonic()
        with mock.patch("builtins.print"):
            results = runner.run()
        # Each piece an error saying what came back, and each process stopped, not waited for.
        self.assertEqual(sorted(r["class"] for r in results), ["a.One", "a.Two"])
        for r in results:
            self.assertIn("sent back 'not a result\\n'", r["errors"][0][1])
        self.assertLess(time.monotonic() - started, 30)


if __name__ == "__main__":
    unittest.main()
