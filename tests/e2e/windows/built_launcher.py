"""The launcher built with PyInstaller by a Windows Python and started, with no game files anywhere: CI's windows job on
Windows itself, and the same script under Wine with the build machine's Windows Python on a Linux PC.

    python tests/e2e/windows/built_launcher.py PARTS_DIR OUT_DIR      (from the repository's top, a Windows Python)

PARTS_DIR holds what the release build makes on Linux first and this Python cannot: openDMT3's card reader library
with its notices (native/cardreader/build.sh) and the official 7-Zip for Windows in 7zip/ (packaging/windows/
sevenzip.sh). In OUT_DIR, as packaging/windows/build.sh does it: the pictures and the version file (assets.py), the
program folder (openDMT3.spec), its licences (notices.py); then the console program answers --version with the
version this tree carries, and --inspect on a made-up folder in the shape of a game folder (a program of a made-up
name and the files every pack folder has, all made-up bytes) with the reader's own words for a client it cannot open,
exit 1. Each step says PASS or FAIL; the exit code is the number of steps that failed. Nothing here opens a window:
the console program with --version or --inspect has none.
"""

import os
import re
import shutil
import subprocess
import sys

# The repository's top: this file is in tests/e2e/windows/.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

from opendmt3 import __version__  # noqa: E402
from opendmt3.core import errors  # noqa: E402
from opendmt3.core import game as g  # noqa: E402

# Each step's time limit: PyInstaller takes a few minutes under Wine, a start a few seconds.
BUILD_SECONDS = 1200
RUN_SECONDS = 120


def step(name, ok, detail=""):
    """One step's line; returns 0 when it held, 1 when it did not."""
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, (": " + detail) if detail else ""), flush=True)
    return 0 if ok else 1


def run(cmd, seconds, env=None):
    """A command from the repository's top: (exit code, its output and errors together)."""
    try:
        done = subprocess.run(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=seconds, text=True, encoding="utf-8", errors="replace")
        return done.returncode, done.stdout
    except subprocess.TimeoutExpired as e:
        return None, (e.stdout or "") if isinstance(e.stdout, str) else ""


def made_up_folder(out):
    """A folder in the shape of a game folder and nothing of the game's: a program of a made-up name (bytes that are
    no program) and, in the pack folder, the files every game folder has, by the names the reader looks for (bytes
    that are no archive)."""
    folder = os.path.join(out, "made-up", "Game")
    os.makedirs(os.path.join(folder, g.PACK_DIR), exist_ok=True)
    with open(os.path.join(folder, "Game.exe"), "wb") as f:
        f.write(b"made-up bytes, not a program\n" * 4)
    for name in g.MARKS:
        with open(os.path.join(folder, g.PACK_DIR, name), "wb") as f:
            f.write(b"made-up bytes, not an archive\n")
    return os.path.dirname(folder)


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[2].strip())
        return 2
    parts, out = (os.path.abspath(a) for a in argv)
    failed = 0
    # Made afresh: a folder from an earlier run would hide a step that no longer makes it.
    shutil.rmtree(out, ignore_errors=True)
    assets = os.path.join(out, "assets")

    # The pictures and the version file, and an empty update address (this build looks for no updates), as build.sh.
    code, said = run([sys.executable, os.path.join("packaging", "windows", "assets.py"), assets, __version__],
                     RUN_SECONDS)
    made = code == 0 and os.path.isfile(os.path.join(assets, "version.txt"))
    failed += step("the pictures and the version file", made, said.strip()[-400:])
    with open(os.path.join(assets, "update-source.txt"), "w", encoding="utf-8") as f:
        f.write("")
    # And no test's update key: the launcher takes the project's alone, as a release's.
    with open(os.path.join(assets, "update-test-keys.txt"), "w", encoding="utf-8") as f:
        f.write("")

    # The program folder, from the same recipe as a release: PyInstaller with the build's folders.
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", OPENDMT3_BUILD_DIR=assets, OPENDMT3_NATIVE_DIR=parts,
               OPENDMT3_7ZIP_DIR=os.path.join(parts, "7zip"))
    dist = os.path.join(out, "dist")
    code, said = run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--log-level", "WARN", "--distpath", dist,
                      "--workpath", os.path.join(out, "work"), os.path.join("packaging", "windows", "openDMT3.spec")],
                     BUILD_SECONDS, env)
    program = os.path.join(dist, "openDMT3")
    console = os.path.join(program, "openDMT3-cmd.exe")
    failed += step("PyInstaller made openDMT3.exe and openDMT3-cmd.exe",
                   code == 0 and os.path.isfile(console) and os.path.isfile(os.path.join(program, "openDMT3.exe")),
                   said.strip()[-1200:])
    if not os.path.isfile(console):
        return failed + 1

    # The licence texts of what it carries, as build.sh gathers them.
    code, said = run([sys.executable, os.path.join("packaging", "windows", "notices.py"), program, ROOT], RUN_SECONDS)
    failed += step("its licences in licenses/ with NOTICES.txt", code == 0 and os.path.isfile(
        os.path.join(program, "licenses", "NOTICES.txt")), said.strip()[-1200:])

    # Started: its version, the one this tree carries, on a line of its own (Velopack's own start-up may say a line of
    # its own first: a program PyInstaller built and nothing installed is not one of its installs).
    code, said = run([console, "--version"], RUN_SECONDS)
    failed += step("openDMT3-cmd.exe --version", code == 0 and "openDMT3 " + __version__ in said.splitlines(),
                   said.strip())

    # Started on a made-up folder: found in the shape of a game folder, its program no client the reader can open, said
    # in the reader's own words, exit 1 (the folder cannot be used).
    folder = made_up_folder(out)
    code, said = run([console, "--inspect", folder], RUN_SECONDS)
    words = errors.TEXT["error.game.no_table"][0]
    found = re.search(r"made-up[\\/]Game\s", said) is not None
    failed += step("openDMT3-cmd.exe --inspect on a made-up folder", code == 1 and found and words in said,
                   said.strip())
    print("%d of 5 steps failed" % failed if failed else "all 5 steps passed", flush=True)
    return failed


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
