"""Made-up tests for the parallel runner's own test (tests/test_parallel_runner.py): one that passes, fails, errs, is
skipped, writes to its output and reads its input, and one that ends its process. Not a test module itself (its name
is not test*.py): only the runner's test hands these out."""

import os
import sys
import unittest


class Samples(unittest.TestCase):
    def test_passes(self):
        self.assertTrue(True)

    def test_fails(self):
        self.assertEqual(1, 2, "made-up failure")

    def test_errs(self):
        raise RuntimeError("made-up error")

    @unittest.skip("made-up skip")
    def test_skipped(self):
        pass

    def test_writes_and_reads_without_harm(self):
        # A test's own output and input are not the runner's lines.
        print("a line a test printed")
        sys.stdout.write("{\"not\": \"a result\"}\n")
        self.assertEqual(sys.stdin.read(), "")


class Crash(unittest.TestCase):
    def test_ends_its_process(self):
        import shutil
        import tests
        # Last words, as a process that crashes leaves (a fault's report): the runner says them with the error.
        sys.stderr.write("the made-up last words\n")
        sys.stderr.flush()
        # The process's temporary launcher folder removed first: ending at once skips what removes it at exit.
        shutil.rmtree(tests._CONFIG, ignore_errors=True)
        os._exit(3)
