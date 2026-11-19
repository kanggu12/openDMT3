"""Every shell script parses: the end-to-end scripts, the Helm chart's on a kind cluster, and those that build, package,
release and install what is handed out (native/, packaging/), each read through by the shell its first line names
(sh -n for #!/bin/sh, which takes none of bash's own syntax; bash -n for the rest, and for a script that is only
sourced). One that does not parse never runs, and nothing else says so: tests/e2e/upgrade/run.sh did not, from its first
commit, for an apostrophe in a comment inside the single quotes of the Python it passes to the earlier release's
server; a build or release script that CI never runs would say so only on the release machine, and the one-line
installer on a player's server."""

import glob
import os
import shutil
import subprocess
import unittest

# The repository's top folder (this file is in tests/).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Every shell script of the tree: the tests' own, the Helm chart's on a kind cluster, the native parts' builds and the
# packaging's (the Windows build, the release, the server's one-line install).
SCRIPTS = sorted(path for folder in ("tests", "deploy", "native", "packaging")
                 for path in glob.glob(os.path.join(ROOT, folder, "**", "*.sh"), recursive=True))


def shell_of(path):
    """The shell that reads a script: sh for one whose first line names /bin/sh, bash otherwise (a script sourced by
    another has no first line of its own to name it, and the scripts that source them are bash's)."""
    with open(path, encoding="utf-8", errors="replace") as f:
        first = f.readline()
    named = first[2:].split() if first.startswith("#!") else []
    return "sh" if named[:1] in (["/bin/sh"], ["/usr/bin/sh"]) else "bash"


@unittest.skipUnless(shutil.which("bash") and shutil.which("sh"), "needs bash and sh")
class ScriptsParseTest(unittest.TestCase):
    # Its name is the one docs/test-cases.md points at, from when it read the end-to-end scripts alone.
    def test_every_e2e_script_parses(self):
        # The upgrade's, the expose's, the install's and the Windows package's among them, and those that build and
        # install what is handed out.
        names = [os.path.relpath(path, ROOT) for path in SCRIPTS]
        for name in ("tests/e2e/upgrade/run.sh", "tests/e2e/expose/run.sh", "tests/e2e/install/run.sh",
                     "tests/e2e/windows/server_package.sh", "deploy/kind/up.sh", "native/openal/inside.sh",
                     "packaging/windows/build.sh", "packaging/release.sh", "packaging/server/install.sh"):
            self.assertIn(name, names)
        # The one-line installer is read by sh, as a server runs it.
        self.assertEqual(shell_of(os.path.join(ROOT, "packaging", "server", "install.sh")), "sh")
        for path in SCRIPTS:
            with self.subTest(script=os.path.relpath(path, ROOT)):
                # Read, never run: -n parses the script and stops.
                done = subprocess.run([shell_of(path), "-n", path], capture_output=True, text=True)
                self.assertEqual(done.returncode, 0, done.stderr)


if __name__ == "__main__":
    unittest.main()
