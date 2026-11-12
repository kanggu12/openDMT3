"""The test suite. Importing it marks the process as a test run, so nothing opens a window on a real screen, and gives
the launcher's own folder a temporary one of the process's, so nothing is read from or written to this PC's."""

import atexit
import os
import shutil
import tempfile

# Every function that opens a window (the launcher, the game, a browser) refuses while this is set, unless the
# test container's virtual screen is in use (opendmt3/core/safety.py).
os.environ["OPENDMT3_TESTING"] = "1"
# The launcher's own folder (its settings, logs, kept fingerprints and charts: client/state.py) for a test that names
# none of its own: one of this process's, removed when it ends. A test that forgot had kept 512 fingerprints of made-up
# files in this PC's real one, among them a table for a made-up client that answered another test's.
_CONFIG = tempfile.mkdtemp(prefix="opendmt3-tests-config-")
os.environ["OPENDMT3_CONFIG_DIR"] = _CONFIG
atexit.register(shutil.rmtree, _CONFIG, True)
