"""Every end-to-end script parses: bash -n reads each one through. One that does not never runs, and nothing else says
so: tests/e2e/upgrade/run.sh did not, from its first commit, for an apostrophe in a comment inside the single quotes of
the Python it passes to the earlier release's server."""

import glob
import os
import shutil
import subprocess
import unittest

# The repository's top folder (this file is in tests/).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The end-to-end scripts: the tests' own, and the Helm chart's on a kind cluster.
SCRIPTS = sorted(glob.glob(os.path.join(ROOT, "tests", "e2e", "**", "*.sh"), recursive=True)
                 + glob.glob(os.path.join(ROOT, "deploy", "**", "*.sh"), recursive=True))


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class ScriptsParseTest(unittest.TestCase):
    def test_every_e2e_script_parses(self):
        # The upgrade's, the expose's, the install's and the Windows package's among them.
        names = [os.path.relpath(path, ROOT) for path in SCRIPTS]
        for name in ("tests/e2e/upgrade/run.sh", "tests/e2e/expose/run.sh", "tests/e2e/install/run.sh",
                     "tests/e2e/windows/server_package.sh", "deploy/kind/up.sh"):
            self.assertIn(name, names)
        for path in SCRIPTS:
            with self.subTest(script=os.path.relpath(path, ROOT)):
                # Read, never run: -n parses the script and stops.
                done = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
                self.assertEqual(done.returncode, 0, done.stderr)


if __name__ == "__main__":
    unittest.main()
