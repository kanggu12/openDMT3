"""The unit tests that matter on Windows, with a Windows Python: CI's windows job on Windows itself, and the same under
Wine with the build machine's Windows Python on a Linux PC.

    python tests/e2e/windows/unit_tests.py        (from the repository's top; -v names each test)

What runs on a player's PC, on Windows' own paths, files and processes: tests/core (the game folder, its formats, the
setup), tests/client (the launcher) and tests/server (the server and site the launcher runs for playing on one PC);
and the tests of the scripts that build what is handed out (the licences gathered for the launcher, a release's notes)
with the parts' boundary. What LEFT_OUT names (a module, or one test) is left out only under Wine, each for the
reason it gives: it waits on, times or asks Windows for what a Windows Python under Wine does differently from
Windows itself (a link's end, a loop's pauses, a folder's access list, a process's written bytes). On Windows itself
(CI's Windows job) every test runs, those included, so a real fault there is never hidden by what Wine cannot show.
Exit 1 when a test fails.
"""

import os
import sys
import unittest

# The repository's top: this file is in tests/e2e/windows/.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
# The parts whose every test module runs here, but those LEFT_OUT.
PARTS = ("core", "client", "server")
# The tests of the build's scripts and the boundary, from the top of tests/.
TOP = ("tests.test_launcher_licences", "tests.test_release_notes", "tests.test_architecture")
# The server's tests of 7-Zip's runs, three of which LEFT_OUT names (their names are long).
SEVEN_ZIP_RUNS = "tests.server.test_sources.SevenZipRunsTest."
# Why the tests of the watch on 7-Zip's writing are left out under Wine (one reason, four tests).
NO_WRITE_COUNT = ("what 7-Zip has written, read from the system's count for its process (GetProcessIoCounters): "
                  "under Wine the count is 0 for every process whatever it writes, so the watch measures the folder "
                  "only once a second and the stand-in writes 90 to 140 MB past a bound of 64; Windows counts every "
                  "write, and the watch without a count is tested on every system")
# What Wine cannot show (a module, or one test by its full name), with why: left out under Wine only.
LEFT_OUT = {
    "tests.server.test_web.AttackTest.test_sign_ins_never_hold_up_the_event_loop_the_cabinets_share":
        "the event loop timed to the millisecond while threads check passwords: under Wine its timers and threads "
        "stall it 270 to 320 ms, which says nothing of the code; it holds on Linux, where the server's image runs",
    "tests.core.test_own.WindowsCallsTest.test_windows_own_calls":
        "the short path's folder made and checked with Windows' own security calls: under Wine a folder made with one "
        "protected entry, this user's, comes back unprotected with SYSTEM's beside it, and an access list set is not "
        "kept, so no folder is ever this user's alone; the same calls with stand-ins are tested on every system",
    SEVEN_ZIP_RUNS + "test_the_systems_count_is_what_the_child_wrote": NO_WRITE_COUNT,
    SEVEN_ZIP_RUNS + "test_the_watch_reads_what_7zip_itself_wrote_whatever_others_do_to_the_disk": NO_WRITE_COUNT,
    SEVEN_ZIP_RUNS + "test_7zip_is_stopped_once_it_writes_more_than_the_entries_said": NO_WRITE_COUNT,
    "tests.client.test_intake.LauncherSevenZipTest.test_7zip_is_stopped_once_it_writes_more_than_the_entries_said":
        NO_WRITE_COUNT,
}


def tests_of(suite):
    """Every test case in a suite, however deep its suites go."""
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from tests_of(item)
        else:
            yield item


def under_wine():
    """Whether this Windows Python runs under Wine: Wine's own ntdll exports wine_get_version, Windows' never does."""
    try:
        import ctypes
        # Looked up by name: an attribute error on Windows itself, a function under Wine.
        return hasattr(ctypes.WinDLL("ntdll"), "wine_get_version")
    except (AttributeError, OSError):
        # Not Windows at all (a Linux run of this file): nothing is left out there either.
        return False


def left_out(test_id, wine):
    """Whether a test (by its id, module.Class.method) is one LEFT_OUT names, itself or by its module, under Wine."""
    # On Windows itself every test runs: the list says only what Wine cannot show.
    return wine and any(test_id == name or test_id.startswith(name + ".") for name in LEFT_OUT)


def main(argv):
    sys.path.insert(0, ROOT)
    os.chdir(ROOT)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in TOP:
        suite.addTests(loader.loadTestsFromName(name))
    # Asked once: the same answer for every test of the run.
    wine = under_wine()
    for part in PARTS:
        found = loader.discover(os.path.join(ROOT, "tests", part), top_level_dir=ROOT)
        # A module that failed to load is a test too (unittest's _FailedTest): it stays, and fails the run.
        suite.addTests(t for t in tests_of(found) if not left_out(t.id(), wine))
    result = unittest.TextTestRunner(verbosity=2 if "-v" in argv else 1).run(suite)
    # Said only when something was left out, with why, so a run's log tells which kind of Windows it was.
    for name, why in (LEFT_OUT.items() if wine else ()):
        print("left out under Wine %s: %s" % (name, why))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
