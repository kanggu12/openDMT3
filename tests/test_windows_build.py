"""The Windows build's own rules (packaging/windows): which earlier package the delta package is made from, what the
launcher's folder leaves out, how the console program finds its modules, and with which key the update packages are
signed. Made-up files only: no build is run (the signing step is, on made-up packages with a key made here)."""

import contextlib
import glob
import io
import os
import re
import runpy
import shutil
import subprocess
import tempfile
import unittest
import zipfile

from opendmt3.core import signing

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOWS = os.path.join(ROOT, "packaging", "windows")


def text_of(*parts):
    """A file of the repository as text."""
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def load(name):
    """One of packaging/windows' scripts as a module's names (they are run as scripts, not imported)."""
    return runpy.run_path(os.path.join(WINDOWS, name))


class PreviousReleaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.previous = load("previous.py")
        self.releases = os.path.join(self.tmp, "releases")
        os.makedirs(self.releases)

    def make(self, folder, *names):
        for name in names:
            with open(os.path.join(folder, name), "w") as f:
                f.write(name)

    def test_versions_in_semver_order(self):
        order = self.previous["order"]
        ranked = ["0.9.9", "0.14.0-rc.1", "0.14.0-rc.2", "0.14.0-rc.10", "0.14.0", "0.14.1-updatetest", "0.14.1",
                  "0.15.0", "1.0.0"]
        self.assertEqual(sorted(reversed(ranked), key=order), ranked)

    def test_the_newest_earlier_package_stays_and_nothing_else(self):
        # An earlier build in the same folder: its packages, signatures, installer and feed files.
        self.make(self.releases, "openDMT3-0.14.0-full.nupkg", "openDMT3-0.14.1-full.nupkg",
                  "openDMT3-0.14.1-full.nupkg.sig", "openDMT3-0.14.1-delta.nupkg", "openDMT3-0.14.2-full.nupkg",
                  "openDMT3-win-Setup.exe", "releases.win.json", "RELEASES", "assets.win.json")
        kept = self.previous["keep_previous"](self.releases, "0.14.2")
        # The version built now is no previous one (a build made again replaces it), and the newest before it stays.
        self.assertEqual(kept, "0.14.1")
        self.assertEqual(os.listdir(self.releases), ["openDMT3-0.14.1-full.nupkg"])

    def test_the_release_before_is_copied_in(self):
        before = os.path.join(self.tmp, "0.14.0", "build", "releases")
        os.makedirs(before)
        self.make(before, "openDMT3-0.14.0-full.nupkg", "openDMT3-0.14.0-full.nupkg.sig", "openDMT3-win-Setup.exe")
        self.assertEqual(self.previous["keep_previous"](self.releases, "0.14.1", [before]), "0.14.0")
        self.assertEqual(os.listdir(self.releases), ["openDMT3-0.14.0-full.nupkg"])
        # The release's own folder is left as it was.
        self.assertEqual(len(os.listdir(before)), 3)
        # A package named by itself is taken as well.
        os.remove(os.path.join(self.releases, "openDMT3-0.14.0-full.nupkg"))
        package = os.path.join(before, "openDMT3-0.14.0-full.nupkg")
        self.assertEqual(self.previous["keep_previous"](self.releases, "0.14.1", [package]), "0.14.0")

    def test_no_previous_package_for_the_first_release(self):
        # Only later versions there (a build made again of a newer one): no delta, and the folder left empty.
        self.make(self.releases, "openDMT3-0.2.0-full.nupkg", "openDMT3-win-Setup.exe")
        self.assertIsNone(self.previous["keep_previous"](self.releases, "0.1.0"))
        self.assertEqual(os.listdir(self.releases), [])


class LeftOutTest(unittest.TestCase):
    def test_tcl_data_the_window_never_reads(self):
        kept = load("launcher_parts.py")["kept_data"]
        for dest in ("_tcl_data\\tzdata\\Asia\\Seoul", "_tcl_data/msgs/de.msg", "_tcl_data/encoding/koi8-r.enc",
                     "_tcl_data/encoding/euc-kr.enc"):
            self.assertFalse(kept(dest), dest)
        # The Windows code pages (any can be the system's), Tcl's own scripts, Tk's data and everything else stay.
        for dest in ("_tcl_data\\encoding\\cp949.enc", "_tcl_data/encoding/cp1252.enc", "_tcl_data/encoding/cp932.enc",
                     "_tcl_data/init.tcl", "_tcl_data/clock.tcl", "_tk_data/msgs/de.msg", "opendmt3/client/x.txt"):
            self.assertTrue(kept(dest), dest)

    def test_pillow_codecs_never_used(self):
        excludes = load("launcher_parts.py")["EXCLUDES"]
        for module in ("PIL._avif", "PIL._webp", "PIL._imagingcms", "unittest"):
            self.assertIn(module, excludes)

    def test_one_set_of_fonts_in_the_folder(self):
        # The in-game layer's fonts come from the launcher's own (core/cabinet/native.py falls back to them): the
        # recipe copies none beside the card reader library.
        with open(os.path.join(WINDOWS, "openDMT3.spec"), encoding="utf-8") as f:
            recipe = f.read()
        self.assertNotIn('"Pretendard-Bold.ttf", "Pretendard-Regular.ttf"', recipe)
        from opendmt3.core.cabinet import native
        for found in (native.font(), native.font_regular(), native.font_wide(), native.font_licence(),
                      native.font_wide_licence()):
            self.assertTrue(os.path.isfile(found), found)
            self.assertIn(os.path.join("client", "assets", "fonts"), found)


class ConsoleModulesTest(unittest.TestCase):
    def test_the_console_program_reads_the_windows_archive(self):
        # The recipe gives the console program an empty archive and its own runtime hook first, and writes where the
        # window's archive is; the hook reads that file and checks the archive as PyInstaller does.
        with open(os.path.join(WINDOWS, "openDMT3.spec"), encoding="utf-8") as f:
            recipe = f.read()
        self.assertIn('console_scripts = [("pyi_rth_opendmt3_modules"', recipe)
        self.assertIn("PYZ([], name=", recipe)
        self.assertIn('"openDMT3.exe?%d\\n"', recipe)
        with open(os.path.join(WINDOWS, "console_modules.py"), encoding="utf-8") as f:
            hook = f.read()
        self.assertIn("openDMT3-modules.txt", hook)
        self.assertIn("check_pymagic=True", hook)


@unittest.skipUnless(shutil.which("bash") and shutil.which("python3"), "needs bash and python3, as the build does")
class SigningStepTest(unittest.TestCase):
    """packaging/windows/sign.sh as build.sh runs it, on made-up packages, with a key pair made here and thrown away."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.releases = os.path.join(self.tmp, "releases")
        os.makedirs(self.releases)
        # This version's whole package and delta package, and the previous release's package kept for the delta.
        for name in ("openDMT3-0.14.1-full.nupkg", "openDMT3-0.14.1-delta.nupkg", "openDMT3-0.14.0-full.nupkg"):
            with zipfile.ZipFile(os.path.join(self.releases, name), "w") as z:
                z.writestr("openDMT3.nuspec", name)
        self.key = os.path.join(self.tmp, "throwaway.key")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            signing.main(["new-key", self.key])
        self.public = out.getvalue().strip()

    def sign(self, version="0.14.1", **variables):
        """Run the step with these variables and no others of its own; (exit code, what it said, the .sig files)."""
        env = {k: v for k, v in os.environ.items() if k not in ("OPENDMT3_SIGNING_KEY", "OPENDMT3_TEST_UPDATE_KEY")}
        env.update(variables, PYTHONDONTWRITEBYTECODE="1")
        done = subprocess.run(["bash", os.path.join(WINDOWS, "sign.sh"), self.releases, version], env=env,
                              capture_output=True, text=True, timeout=120)
        return done.returncode, done.stdout + done.stderr, sorted(n for n in os.listdir(self.releases)
                                                                  if n.endswith(".sig"))

    def test_the_build_signs_only_with_a_key_named_in_the_environment(self):
        # No key named: nothing signed, said, and the build goes on (its packages are no updates for a launcher).
        code, said, sigs = self.sign()
        self.assertEqual((code, sigs), (0, []), said)
        self.assertIn("no signing key named (OPENDMT3_SIGNING_KEY)", said)
        # Named and not there, or a folder: a mistake in the name stops the build.
        for missing in (os.path.join(self.tmp, "no-such.key"), self.tmp):
            code, said, sigs = self.sign(OPENDMT3_SIGNING_KEY=missing)
            self.assertEqual((code, sigs), (1, []), said)
            self.assertIn("no signing key at %s" % missing, said)
        # No package of the version: nothing to sign is a stop as well.
        self.assertEqual(self.sign("9.9.9", OPENDMT3_SIGNING_KEY=self.key)[0], 1)

    def test_packages_signed_with_a_key_no_launcher_takes_stop_the_build(self):
        # The key made here is not built into any launcher: its signatures are removed again.
        code, said, sigs = self.sign(OPENDMT3_SIGNING_KEY=self.key)
        self.assertEqual((code, sigs), (1, []), said)
        self.assertIn("not signed with a key the launcher takes", said)

    def test_a_test_build_signs_with_its_own_key_this_versions_packages_alone(self):
        code, said, sigs = self.sign(OPENDMT3_SIGNING_KEY=self.key, OPENDMT3_TEST_UPDATE_KEY=self.public)
        self.assertEqual(code, 0, said)
        # The whole package and the delta of this version; the previous release's package was signed with its own.
        self.assertEqual(sigs, ["openDMT3-0.14.1-delta.nupkg.sig", "openDMT3-0.14.1-full.nupkg.sig"])
        for name in ("openDMT3-0.14.1-full.nupkg", "openDMT3-0.14.1-delta.nupkg"):
            path = os.path.join(self.releases, name)
            with open(path + ".sig", "rb") as f:
                sig = f.read()
            # By that key, and by no key built in.
            self.assertTrue(signing.checks_out(sig, path, name, (self.public,)))
            self.assertTrue(signing.content_checks_out(sig, path, name, (self.public,)))
            self.assertFalse(signing.checks_out(sig, path, name))
        # The key itself is in nothing the step wrote or said.
        with open(self.key, encoding="ascii") as f:
            secret = f.read().strip()
        self.assertNotIn(secret, said)
        for name in os.listdir(self.releases):
            with open(os.path.join(self.releases, name), "rb") as f:
                self.assertNotIn(secret.encode(), f.read(), name)


class SigningKeyRulesTest(unittest.TestCase):
    """Where a signing key may come from, read from the scripts themselves."""

    def test_no_script_tries_a_key_of_its_own(self):
        scripts = sorted(glob.glob(os.path.join(ROOT, "packaging", "**", "*"), recursive=True)
                         + glob.glob(os.path.join(ROOT, "tests", "e2e", "**", "*.sh"), recursive=True)
                         + glob.glob(os.path.join(ROOT, ".github", "workflows", "*")) + [os.path.join(ROOT, "dmt3")])
        looked = 0
        for path in scripts:
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
            looked += 1
            name = os.path.relpath(path, ROOT)
            # The folder the release machine keeps its key in is no script's business.
            self.assertNotIn("_work/keys", text, name)
            self.assertNotIn("update-signing.key", text, name)
            # The variable is read with nothing to fall back on.
            for fallback in re.findall(r"\$\{OPENDMT3_SIGNING_KEY:-([^}]*)\}", text):
                self.assertEqual(fallback, "", name)
        # The build's scripts, the Wine tests and the workflows: a pattern that stopped matching would pass with none.
        self.assertGreater(looked, 30)
        for name in ("sign.sh",):
            self.assertIn("KEY=${OPENDMT3_SIGNING_KEY:-}", text_of("packaging", "windows", name))
        self.assertIn("KEY=${OPENDMT3_SIGNING_KEY:-}", text_of("packaging", "release.sh"))
        # No workflow has a secret to sign with: releases are signed on the release machine.
        for path in glob.glob(os.path.join(ROOT, ".github", "workflows", "*")):
            self.assertNotIn("SIGNING_KEY", text_of(path), os.path.basename(path))

    def test_the_wine_update_tests_sign_with_a_key_made_for_the_run(self):
        for name in ("update.sh", "update_delta.sh"):
            script = text_of("tests", "e2e", "windows", name)
            with self.subTest(script=name):
                # A key pair of the run's own, in a folder no container is given; the launcher under test told to
                # take its public half; never the key a build is given.
                self.assertIn('KEYS=$(mktemp -d)', script)
                self.assertIn('python3 -m opendmt3.core.signing new-key "$KEY"', script)
                self.assertIn('printf \'%s\\n\' "$PUBLIC" > "$TEST_KEYS"', script)
                self.assertIn("_internal/opendmt3/core/update-test-keys.txt", script)
                self.assertNotIn("OPENDMT3_SIGNING_KEY", script)
                # The key and everything signed with it go whichever way the run ends.
                self.assertIn("trap tidy EXIT", script)
                tidy = re.search(r"^tidy\(\) \{ (.*) \}$", script, re.M).group(1)
                for gone in ('"$KEYS"', "*.nupkg", "*.nupkg.sig"):
                    self.assertIn(gone, tidy)
                # And the made-up update must not pass for one the project signed.
                self.assertIn("the made-up update passes for one the project signed", script)

    def test_a_releases_launcher_takes_the_projects_key_alone(self):
        # The build writes a test's key into the launcher only when given one, and says so; the recipe carries the
        # file beside signing.py; CI's own build writes an empty one.
        build = text_of("packaging", "windows", "build.sh")
        self.assertIn('TEST_KEY=${OPENDMT3_TEST_UPDATE_KEY:-}', build)
        self.assertIn('printf \'%s\' "$TEST_KEY" > "$OUT/assets/update-test-keys.txt"', build)
        self.assertIn("TEST BUILD, not for release", build)
        self.assertIn('(os.path.join(BUILD, "update-test-keys.txt"), os.path.join("opendmt3", "core"))',
                      text_of("packaging", "windows", "openDMT3.spec"))
        self.assertEqual(os.path.basename(signing.TEST_KEYS_FILE), "update-test-keys.txt")
        self.assertEqual(os.path.dirname(signing.TEST_KEYS_FILE), os.path.join(ROOT, "opendmt3", "core"))
        self.assertIn('os.path.join(assets, "update-test-keys.txt")', text_of("tests", "e2e", "windows",
                                                                              "built_launcher.py"))
        # A release refuses a test's key in the environment, and looks at the launcher it built.
        release = text_of("packaging", "release.sh")
        self.assertIn('if [ -n "${OPENDMT3_TEST_UPDATE_KEY:-}" ]; then', release)
        self.assertIn('[ -f "$TEST_KEYS" ] && [ ! -s "$TEST_KEYS" ]', release)


if __name__ == "__main__":
    unittest.main()
