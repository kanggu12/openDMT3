"""The unit tests on several processes at once: every test `python -m unittest discover -s tests -t .` finds, by class,
handed to a few processes of the Python under test (each takes the next piece as it finishes one, the longest first),
and their results added up and said as one run says them.

    python -m tests.parallel [--jobs N] [--one-process] [--shuffle SEED] [-v]      (from the repository's top)

./dmt3 test runs this, and so does CI. --one-process runs them all in this process, as unittest's discover does (--jobs
1 the same). The classes' times of the last run are kept in build/test-times.json: the longest go first, and a class
long beside the whole run is cut into pieces of its tests (without the file, the class with the most tests goes
first). --shuffle hands the pieces out in an order of the seed's instead.

A piece (a class, or a run of its tests) runs whole in one process with its own setUpClass and tearDownClass, apart
from what other processes run: a test may count on nothing another class left behind (a module's globals, a file, a
port), only on what its own class makes. What the tests print goes to a file of their process's, gone after the run
(--one-process shows it as it comes). A process that ends while it runs a piece (a crash), or sends back something
else than its result, is said as an error of that piece with the end of what it printed, and a new process takes the
rest.
"""

import argparse
import collections
import io
import json
import math
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

# The repository's top: this file is in tests/.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The classes' times of the last run, by class: where the longest are told from.
TIMES = os.path.join(ROOT, "build", "test-times.json")
# What each process of the last run ran, in its order (each piece's label and tests): a test that failed beside others
# and passes alone is run again after what ran before it there.
ORDER = os.path.join(ROOT, "build", "test-order.json")
# At most this many processes by default: past it, the classes' own lengths, not their number, set the time.
MOST_JOBS = 8
# Tests that measure what this PC does while they run (its pace, its disk), with why: run after the rest on a process
# of their own, nothing else of the run's beside them, as a run in one process has them. Beside the other processes
# they measured those processes' load and the files they deleted, not the code.
ALONE = {
    "tests.server.test_web.AttackTest.test_sign_ins_never_hold_up_the_event_loop_the_cabinets_share":
        "the event loop's longest stall timed against one password check: beside seven busy processes it stood still "
        "41 ms against a bound of 32",
    # The game server's and the site's answers timed while one caller misbehaves or the database is held: what they
    # time is how soon the others are answered, which seven busy processes beside them slow.
    "tests.server.test_concurrency.IsolationTest.test_one_bad_cabinet_never_slows_the_others":
        "a keep-alive's answer within 250 ms: 261 ms beside seven busy processes",
    "tests.server.test_concurrency.IsolationTest.test_a_link_that_asks_and_never_reads_is_dropped_holding_nothing":
        "a good cabinet's answers within 250 ms beside a link that never reads",
    "tests.server.test_concurrency.ConcurrencyTest.test_a_held_database_never_reaches_a_player":
        "the cabinets' answers within 500 ms while the database is held",
    "tests.server.test_concurrency.ReadersTest.test_a_long_read_never_holds_up_another_cabinets_write_or_login":
        "a write within 700 ms and a login within 800 ms beside a long read",
    "tests.server.test_concurrency.FairnessTest.test_a_token_asking_over_and_over_gets_its_share_and_others_keep_theirs":
        "the other callers' answers within 500 ms (95 in 100) beside one asking over and over",
    "tests.server.test_concurrency.FairnessTest.test_health_checks_while_the_database_is_held_never_hold_up_a_page":
        "a page within a second behind health checks",
    "tests.server.test_concurrency.FairnessTest.test_a_callers_waiting_requests_hold_no_worker_thread_and_too_many_are_refused":
        "another caller's answer within 400 ms beside one caller's queue",
    "tests.server.test_firsts.FirstPlacesTest.test_the_walk_costs_charts_not_plays":
        "a walk over ten times the plays timed against the walk over a tenth of them",
}


# ------------------------------------------------------------------------------------------------ the classes

def classes():
    """{class id (module.Class): [test ids]} of every test discover finds, in its order, and the tests that could not be
    loaded (a module that does not import: unittest says those as failing tests of their own)."""
    suite = unittest.TestLoader().discover("tests", top_level_dir=ROOT)
    found, broken = {}, []
    for test in _tests_of(suite):
        if type(test).__module__.startswith("unittest."):
            # unittest.loader._FailedTest and its kind: a module that failed to import, run as it is to say why.
            broken.append(test)
            continue
        found.setdefault("%s.%s" % (type(test).__module__, type(test).__qualname__), []).append(test.id())
    return found, broken


def _tests_of(suite):
    """Every test case in a suite, however deep its suites go."""
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _tests_of(item)
        else:
            yield item


def split_alone(found):
    """found in two, by class as found is: the tests that may run beside others, and those ALONE names, to run after
    them on a process of their own."""
    pool, alone = {}, {}
    for name, tests in found.items():
        for test in tests:
            (alone if test in ALONE else pool).setdefault(name, []).append(test)
    return pool, alone


def units(found, jobs, shuffle=None):
    """The pieces handed out: [(label, [test ids], seconds expected)], the longest first. A class is one piece, but one
    long beside the whole run (more than a third of a process's share) is cut into pieces of its tests in their order,
    each run with the class's setUpClass of its own, so no one class holds the run up while the others are done.
    Times are the last run's (build/test-times.json); a class not timed yet counts a tenth of a second a test. With
    shuffle (a seed), the pieces go in an order of its own, to show a test that counts on another class run before it
    in the same process."""
    times = last_times()
    seconds = {name: times.get(name, 0.1 * len(tests)) for name, tests in found.items()}
    share = sum(seconds.values()) / max(1, jobs) / 3
    out = []
    for name, tests in found.items():
        # As many pieces as the class is shares long (at least one, at most one a test); with one process, whole.
        pieces = 1 if jobs < 2 or seconds[name] <= share or len(tests) < 2 else \
            min(len(tests), math.ceil(seconds[name] / share))
        for i in range(pieces):
            part = tests[i * len(tests) // pieces:(i + 1) * len(tests) // pieces]
            label = name if pieces == 1 else "%s [%d/%d]" % (name, i + 1, pieces)
            out.append((label, part, seconds[name] * len(part) / len(tests)))
    if shuffle is not None:
        import random
        random.Random(shuffle).shuffle(out)
        return out
    return sorted(out, key=lambda unit: -unit[2])


def last_times():
    """{class id: seconds} of the last run, from build/test-times.json: only what reads as a class's time (a file
    cut short, not JSON, not a table of names to times, or with other values in it gives nothing of those, and the
    classes it leaves out count by their tests)."""
    try:
        with open(TIMES, encoding="utf-8") as f:
            times = json.load(f)
    except (OSError, ValueError):
        # No file yet, one that cannot be read, or one that is not JSON (cut short, or not text at all).
        return {}
    if not isinstance(times, dict):
        return {}
    # A number of seconds, finite and not below nothing (true and false are numbers to Python, not times).
    return {name: float(value) for name, value in times.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0}


# ------------------------------------------------------------------------------------------------ a process's part

def worker():
    """A process that runs the pieces it is handed on its standard input, a line of JSON each (a label and its tests'
    ids), and writes each one's result as a line of JSON to what was its standard output. The tests' own output goes
    to its standard error (a file the runner reads back for a piece not finished), and their standard input is empty:
    the lines in and out are the runner's alone."""
    import faulthandler
    # A crash in C (a fault, an abort) leaves Python's own report of where each thread was: it ends what the runner
    # says of the piece.
    faulthandler.enable()
    # The runner's two pipes kept for it, and taken away from the tests (and from the programs they start).
    orders = os.fdopen(os.dup(0), "r", encoding="utf-8")
    results = os.fdopen(os.dup(1), "w", encoding="utf-8")
    nothing = os.open(os.devnull, os.O_RDONLY)
    os.dup2(nothing, 0)
    os.dup2(2, 1)
    sys.stdin = open(os.devnull, encoding="utf-8")
    sys.stdout = sys.stderr
    for line in orders:
        if not line.strip():
            continue
        # A piece: its label, and its tests by id (a whole class, or a run of its tests in order).
        piece = json.loads(line)
        stream = io.StringIO()
        started = time.perf_counter()
        suite = unittest.TestLoader().loadTestsFromNames(piece["tests"])
        result = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
        out = {"class": piece["label"], "seconds": round(time.perf_counter() - started, 3), "run": result.testsRun,
               "failures": [[t.id(), text] for t, text in result.failures],
               "errors": [[getattr(t, "id", lambda: str(t))(), text] for t, text in result.errors],
               "skipped": len(result.skipped), "expected_failures": len(result.expectedFailures),
               "unexpected_successes": [t.id() for t in result.unexpectedSuccesses]}
        results.write(json.dumps(out) + "\n")
        results.flush()
    return 0


# ------------------------------------------------------------------------------------------------ the runner

class Runner:
    """The pieces handed to `jobs` processes, the next one to whichever finishes, and their results added up."""

    # A process of the Python under test that runs the pieces it is handed (worker() above).
    command = [sys.executable, "-m", "tests.parallel", "--worker"]
    # The lines of a process's output said with the error of a piece it did not finish.
    LAST_LINES = 40

    def __init__(self, pieces, jobs, verbose):
        self.todo = queue.Queue()
        for label, tests, _ in pieces:
            self.todo.put((label, tests))
        self.jobs, self.verbose = jobs, verbose
        self.results, self.lock = [], threading.Lock()
        # Each process started, with the pieces it ran in their order.
        self.order = []
        # What the tests print, a file a process: read back only for a piece a process did not finish.
        self.logs = tempfile.mkdtemp(prefix="opendmt3-tests-")

    def _next(self):
        """The next piece to run, (label, tests), or None when none are left."""
        try:
            return self.todo.get_nowait()
        except queue.Empty:
            return None

    def _process(self, number):
        """One process of the Python under test running pieces until none are left; a new one when it ends early."""
        # A process is started only for a piece there is to run.
        piece = self._next()
        while piece is not None:
            log = os.path.join(self.logs, "process-%d.log" % number)
            with open(log, "w", encoding="utf-8") as out:
                # The process has its own copy of the file to write to; this one is closed as soon as it started.
                child = subprocess.Popen(self.command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=out, text=True, encoding="utf-8", bufsize=1)
            # What this process ran, in its order: what a test may have counted on that another left behind.
            ran = []
            with self.lock:
                self.order.append({"process": number, "pieces": ran})
            # The piece this process did not finish, with what it sent back instead of its result ("" when it ended).
            unfinished = None
            while piece is not None:
                name, tests = piece
                ran.append({"label": name, "tests": tests})
                # Where this piece's output starts in the process's file: said with the piece when it fails.
                begins = _size(log)
                try:
                    child.stdin.write(json.dumps({"label": name, "tests": tests}) + "\n")
                    child.stdin.flush()
                    line = child.stdout.readline()
                except (OSError, ValueError):
                    # Its input closed under the write: it had ended.
                    line = ""
                try:
                    result = json.loads(line) if line else None
                except ValueError:
                    result = None
                if not isinstance(result, dict) or result.get("class") != name:
                    unfinished = (name, line)
                    break
                # How many pieces ran before it on this process (each one's tests in build/test-order.json).
                result["after"] = len(ran) - 1
                if result["failures"] or result["errors"] or result["unexpected_successes"]:
                    # What its tests printed (a server's log lines, a warning): shown beside its failures, as a run
                    # in one process shows it.
                    result["printed"] = last_lines(log, self.LAST_LINES, begins)
                self._took(result)
                piece = self._next()
            try:
                # No more pieces: its input closed, so it ends.
                child.stdin.close()
            except OSError:
                pass
            if unfinished is not None:
                # One that sent back something else may still run: stopped (nothing is sent to one already ended).
                child.kill()
            child.wait()
            child.stdout.close()
            if unfinished is None:
                return
            # An error of the piece, with the end of what the process printed, and a new process for the rest.
            name, line = unfinished
            how = "sent back %r instead of its result" % line[:200] if line else "ended"
            self._took({"class": name, "seconds": 0, "run": 0, "failures": [], "skipped": 0,
                        "errors": [[name, "the process running it %s (exit %s); the end of what it printed:\n%s"
                                    % (how, child.returncode, last_lines(log, self.LAST_LINES))]],
                        "expected_failures": 0, "unexpected_successes": [], "after": len(ran) - 1})
            piece = self._next()

    def _took(self, result):
        """A piece's result, kept and said (a failing one with how many pieces its process ran before it)."""
        with self.lock:
            self.results.append(result)
            bad = result["failures"] or result["errors"] or result["unexpected_successes"]
            if self.verbose or bad:
                print("%-4s %s (%d tests, %.1f s%s)" % (
                    "FAIL" if bad else "ok", result["class"], result["run"], result["seconds"],
                    "; after %d pieces on its process, build/test-order.json" % result.get("after", 0) if bad else ""),
                    flush=True)

    def run(self):
        """Every piece run, on `jobs` processes at once; the results in the order they came."""
        threads = [threading.Thread(target=self._process, args=(n,), daemon=True) for n in range(self.jobs)]
        try:
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        finally:
            # What the tests printed is not kept: what an unfinished piece printed is in its error already.
            shutil.rmtree(self.logs, ignore_errors=True)
        return self.results


def last_lines(path, count, begins=0):
    """The last lines of a file (a process's output) from byte `begins` on, as text to say."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            f.seek(begins)
            return "".join(collections.deque(f, count)).rstrip() or "(nothing)"
    except OSError:
        return "(it cannot be read)"


def _size(path):
    """How many bytes a process's output file holds now (0 when it cannot be told)."""
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def say(results, broken_result, seconds, jobs):
    """The run said as unittest says one: each failure and error with its traceback, the count, OK or FAILED. Returns
    True when every test passed."""
    failures = [f for r in results for f in r["failures"]] + [[t.id(), text] for t, text in broken_result.failures]
    errors = [e for r in results for e in r["errors"]] + [[getattr(t, "id", lambda: str(t))(), text]
                                                          for t, text in broken_result.errors]
    unexpected = [u for r in results for u in r["unexpected_successes"]]
    run = sum(r["run"] for r in results) + broken_result.testsRun
    skipped = sum(r["skipped"] for r in results)
    expected = sum(r["expected_failures"] for r in results)
    line = "=" * 70
    for kind, items in (("ERROR", errors), ("FAIL", failures)):
        for test, text in items:
            print("%s\n%s: %s\n%s\n%s" % (line, kind, test, "-" * 70, text.rstrip()))
    for r in results:
        if r.get("printed"):
            # What a failing piece's tests printed while it ran, as one process would have shown it among them.
            print("%s\nWhat %s printed (its last lines):\n%s\n%s" % (line, r["class"], "-" * 70, r["printed"]))
    print("-" * 70)
    print("Ran %d tests in %.3fs (%d processes)\n" % (run, seconds, jobs))
    parts = []
    if failures:
        parts.append("failures=%d" % len(failures))
    if errors:
        parts.append("errors=%d" % len(errors))
    if skipped:
        parts.append("skipped=%d" % skipped)
    if expected:
        parts.append("expected failures=%d" % expected)
    if unexpected:
        parts.append("unexpected successes=%d" % len(unexpected))
    good = not (failures or errors or unexpected)
    print(("OK" if good else "FAILED") + (" (%s)" % ", ".join(parts) if parts else ""), flush=True)
    return good


def keep_times(results):
    """Each class's time of this run, for the next run to hand the longest out first."""
    times = {}
    for r in results:
        # A class cut into pieces counts the time of all of them.
        name = r["class"].split(" [", 1)[0]
        times[name] = round(times.get(name, 0) + r["seconds"], 3)
    _keep(TIMES, times)


def _keep(path, data):
    """data as JSON at path (in build/), best effort: a folder that cannot be written changes nothing but the order of
    the next run, and what is said of this one."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Written aside and put in place whole, under a name of this run's (two runs at once each write their own).
        new = "%s.%d.new" % (path, os.getpid())
        with open(new, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=0, sort_keys=True)
        os.replace(new, path)
    except OSError:
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m tests.parallel", description=__doc__.strip().splitlines()[0])
    parser.add_argument("--jobs", type=int, default=0, help="processes at once (default: the cores, at most %d)" % MOST_JOBS)
    parser.add_argument("--one-process", action="store_true", help="every test in this process, as unittest does")
    parser.add_argument("-v", "--verbose", action="store_true", help="a line for each class as it ends")
    parser.add_argument("--shuffle", type=int, metavar="SEED",
                        help="hand the classes out in an order of the seed's (a test that counts on another fails)")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.jobs < 0:
        parser.error("--jobs takes a number of processes, 1 or more")
    os.chdir(ROOT)
    if args.worker:
        return worker()
    jobs = args.jobs or min(MOST_JOBS, os.cpu_count() or 2)
    if args.one_process or jobs == 1:
        # As `python -m unittest discover -s tests -t .` runs them.
        suite = unittest.TestLoader().discover("tests", top_level_dir=ROOT)
        result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
        return 0 if result.wasSuccessful() else 1
    started = time.perf_counter()
    found, broken = classes()
    # What could not be loaded is run here, to say why, as unittest says it.
    broken_result = unittest.TestResult()
    unittest.TestSuite(broken).run(broken_result)
    pool, alone = split_alone(found)
    pieces = units(pool, jobs, args.shuffle)
    jobs = min(jobs, max(1, len(pieces)))
    runner = Runner(pieces, jobs, args.verbose)
    results, order = runner.run(), runner.order
    # Then what ALONE names, a piece for each class, on one process with nothing beside it.
    lone = [("%s [alone]" % name, tests, 0.0) for name, tests in alone.items()]
    if lone:
        runner = Runner(lone, 1, args.verbose)
        results += runner.run()
        order += [{"process": "alone", "pieces": process["pieces"]} for process in runner.order]
        pieces += lone
    _keep(ORDER, order)
    seconds = time.perf_counter() - started
    good = say(results, broken_result, seconds, jobs)
    # Every piece handed out has its result, and the tests run are as many as were found: one missing would be a test
    # never run.
    missing = sorted({label for label, _, _ in pieces} - {r["class"] for r in results})
    found_count, ran = sum(len(tests) for tests in found.values()), sum(r["run"] for r in results)
    if missing:
        print("not run: %s" % ", ".join(missing), flush=True)
        good = False
    elif ran != found_count:
        # A class whose setUpClass failed, or a piece whose process ended: their tests were found, not run.
        print("%d tests found, %d run" % (found_count, ran), flush=True)
        good = False
    keep_times(results)
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
