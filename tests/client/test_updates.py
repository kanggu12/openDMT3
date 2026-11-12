"""Tests for the launcher's update (opendmt3/client/updates.py, updating.py): nothing of a download is in the install
folder before its signature is checked.

A made-up install folder (packages\\, Update.exe, the installed version's package), a feed folder, and stand-ins for
the two things the launcher hands work to: Velopack's update manager (it only ever puts in a package already checked,
and its own download must never run) and Update.exe's patch command (it zips the new package again, as Velopack's
does). Every key is the test's own; the project's key is never read.
"""

import contextlib
import io
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
import unittest
import zipfile
from types import SimpleNamespace
from unittest import mock

from opendmt3 import __version__
from opendmt3.client import i18n, updates
from opendmt3.core import errors, signing

try:
    # Only whether this Python has Tk: a server's may not (the launcher brings its own).
    import tkinter
    TK = tkinter.TkVersion >= 8.6
except ImportError:
    TK = False

# The test's own key, and a stranger's.
SEED, STRANGER = bytes(range(32)), bytes(range(1, 33))
# The version installed, the one offered, and one older than both.
INSTALLED, VERSION, OLDER = "9.9.8", "9.9.9", "1.0.0"
UNSIGNED = "error.update.unsigned"
# For a stand-in's field left as a release has it (None is a value a feed may give).
AS_RELEASED = object()
# Every entry's time in a made-up package: the same files in the same order are the same bytes, whenever written.
WRITTEN = (2026, 1, 1, 0, 0, 0)


def named(version, kind="full"):
    """A package's file name, as vpk names it."""
    return "openDMT3-%s-%s.nupkg" % (version, kind)


def files_of(version, **changed):
    """A package's files: the manifest with its version, the program, Velopack's updater, one more."""
    files = {"openDMT3.nuspec": ("<package><metadata><id>openDMT3</id><version>%s</version></metadata></package>"
                                 % version).encode(),
             "lib/app/openDMT3.exe": b"MZ the program of " + version.encode(),
             "lib/app/Squirrel.exe": b"MZ the updater of " + version.encode(),
             "lib/app/x.txt": b"x"}
    files.update(changed)
    return files


def zipped(path, files, order=None):
    """A package of these files, in this order (the names' own order when none is given)."""
    with zipfile.ZipFile(path, "w") as z:
        for name in order or sorted(files):
            entry = zipfile.ZipInfo(name, WRITTEN)
            entry.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(entry, files[name])
    return path


class Velopack:
    """Velopack's update manager as the launcher drives it: it is told to put in a package, nothing else."""

    def __init__(self, case):
        self.case = case

    def download_updates(self, *args, **kwargs):
        # Velopack's own download writes into packages\\ and over Update.exe before any check: never used.
        raise AssertionError("Velopack's own download ran")

    def wait_exit_then_apply_updates(self, info, silent, restart):
        # What Velopack is handed, and what packages\\ and Update.exe hold at that moment.
        self.case.handed.append((info, silent, restart, self.case.in_packages(), self.case.updater_bytes()))


class UpdateCase(unittest.TestCase):
    """The made-up install folder, feed and stand-ins."""

    def setUp(self):
        self.top = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.top)
        self.feed, self.install = os.path.join(self.top, "feed"), os.path.join(self.top, "install")
        self.packages, self.temp = os.path.join(self.install, "packages"), os.path.join(self.top, "temp")
        for folder in (self.feed, self.packages, self.temp, os.path.join(self.top, "config")):
            os.makedirs(folder)
        # The installed version's package, where Velopack keeps it, and Velopack's updater beside packages\\.
        self.base = zipped(os.path.join(self.packages, named(INSTALLED)), files_of(INSTALLED))
        self.updater = os.path.join(self.install, "Update.exe")
        with open(self.updater, "wb") as f:
            f.write(b"MZ the updater of " + INSTALLED.encode())
        # A file beside the install folder's own that no update may touch.
        self.beside = os.path.join(self.install, "keep-me.txt")
        with open(self.beside, "w", encoding="utf-8") as f:
            f.write("not a package")
        self.handed, self.told, self.patches, self.fetched = [], [], [], []
        fetch = updates._fetch

        def fetching(result, name, version, folder):
            # Every package the launcher fetches, by its name, in the order asked for.
            self.fetched.append(name)
            return fetch(result, name, version, folder)

        # What the update writes in the log is kept out of the tests' own output (a test that reads it asks for it).
        quiet, logger = logging.NullHandler(), logging.getLogger(updates.__name__)
        logger.addHandler(quiet)
        self.addCleanup(logger.removeHandler, quiet)
        for patch in (mock.patch.dict(os.environ, {"OPENDMT3_CONFIG_DIR": os.path.join(self.top, "config")}),
                      mock.patch.object(updates, "packages_dir", lambda: self.packages),
                      mock.patch.object(updates, "current_version", lambda: INSTALLED),
                      mock.patch.object(updates, "_manager", lambda source: Velopack(self)),
                      mock.patch.object(updates, "_fetch", fetching),
                      # The launcher's own folder is made in the temporary folder: the test's, to look into it.
                      mock.patch.object(tempfile, "tempdir", self.temp),
                      mock.patch.object(signing, "KEYS", (signing.public_key(SEED).hex(),))):
            patch.start()
            self.addCleanup(patch.stop)

    # ---- what a release puts in a feed
    def sign(self, path, seed=SEED, **changed):
        """Write the package's .sig beside it, with fields changed when a test says so."""
        with open(path + ".sig", "w", encoding="utf-8") as f:
            json.dump(dict(signing.sign_package(seed, path), **changed), f)

    def release(self, version=VERSION, files=None, seed=SEED):
        """The whole package of a version and its .sig in the feed; returns the package's path."""
        path = zipped(os.path.join(self.feed, named(version)), files or files_of(version))
        self.sign(path, seed)
        return path

    def delta(self, version=VERSION, seed=SEED, data=b"PK what changed", signed_as=None):
        """A delta package and its .sig in the feed (its contents are Update.exe's to read, not the launcher's);
        `signed_as` signs other bytes than the feed then holds."""
        path = os.path.join(self.feed, named(version, "delta"))
        with open(path, "wb") as f:
            f.write(data if signed_as is None else signed_as)
        self.sign(path, seed)
        if signed_as is not None:
            # The feed then holds other bytes than the ones signed.
            with open(path, "wb") as f:
                f.write(data)
        return path

    def result(self, version=VERSION, name=AS_RELEASED, deltas=(), base=AS_RELEASED, sha256=AS_RELEASED):
        """What a check of the feed found: the whole package, and delta packages when the feed has them."""
        whole = os.path.join(self.feed, named(version))
        if sha256 is AS_RELEASED:
            # As vpk writes it: the whole package's hash, in capitals.
            sha256 = signing.sha256_of(whole).upper() if os.path.isfile(whole) else "0" * 64
        info = SimpleNamespace(
            TargetFullRelease=SimpleNamespace(FileName=named(version) if name is AS_RELEASED else name,
                                              Version=version, SHA256=sha256),
            DeltasToTarget=[SimpleNamespace(FileName=n, Version=v) for n, v in deltas],
            # The package Velopack found in packages\\: the installed version's.
            BaseRelease=SimpleNamespace(FileName=named(INSTALLED) if base is AS_RELEASED else base) if deltas else None)
        return updates.Result("available", version=version, info=info, source=self.feed)

    def with_delta(self, **kwargs):
        """A check that found the delta package from the version installed."""
        return self.result(deltas=[(named(VERSION, "delta"), VERSION)], **kwargs)

    # ---- the stand-in for Update.exe's patch command
    def patcher(self, files=None, code=0, error=None, writes=True):
        """A `run` for updates.apply: Update.exe putting the package together, zipped again in another order; or not
        starting at all (`error`), ending with an exit code, writing nothing."""
        def run(args, **kwargs):
            # How it was run, and what packages\\ held at that moment.
            self.patches.append((list(args), kwargs, self.in_packages()))
            if error is not None:
                raise error
            if writes:
                written = files_of(VERSION) if files is None else files
                zipped(args[args.index("--output") + 1], written, sorted(written, reverse=True))
            return SimpleNamespace(returncode=code, stderr=b"it could not")
        return run

    # ---- what is where
    def in_packages(self):
        return sorted(os.listdir(self.packages))

    def updater_bytes(self):
        with open(self.updater, "rb") as f:
            return f.read()

    def own_folders(self):
        """The launcher's own folders still in the temporary folder."""
        return [name for name in os.listdir(self.temp) if name.startswith(updates.OWN_PREFIX)]

    def apply(self, result, run=None):
        updates.apply(result, tell=self.told.append, run=run or self.patcher())

    def refused(self, result, run=None, key=UNSIGNED):
        """The update is refused with these words, nothing is handed to Velopack, and the install folder is as it was:
        the installed package alone in packages\\, Update.exe the installed one, the file beside them there."""
        with self.assertRaises(errors.Worded) as caught:
            self.apply(result, run)
        self.assertEqual(caught.exception.key, key)
        self.assertEqual(self.handed, [])
        self.assertEqual(self.in_packages(), [named(INSTALLED)])
        self.assertEqual(self.updater_bytes(), b"MZ the updater of " + INSTALLED.encode())
        self.assertTrue(os.path.isfile(self.beside))
        self.assertEqual(self.own_folders(), [])
        # No note of an update under way: the next start says nothing of one.
        self.assertIsNone(updates.outcome())
        return caught.exception


class WholePackageTest(UpdateCase):

    def test_a_signed_update_is_checked_outside_the_install_folder_and_only_then_handed_to_velopack(self):
        released = self.release()
        checked = []
        real = signing.checks_out

        def checks_out(sig, path, name, keys=None):
            # Where the package is when it is checked, and what the install folder holds at that moment.
            checked.append((os.path.abspath(path), self.in_packages(), self.updater_bytes()))
            return real(sig, path, name, keys)

        result = self.result()
        with mock.patch.object(signing, "checks_out", checks_out):
            self.apply(result)
        # Checked once, in the launcher's own folder in the temporary folder, the install folder still as it was.
        self.assertEqual(len(checked), 1)
        where, packages_then, updater_then = checked[0]
        self.assertTrue(where.startswith(os.path.join(self.temp, updates.OWN_PREFIX)), where)
        self.assertFalse(where.startswith(self.install))
        self.assertEqual(packages_then, [named(INSTALLED)])
        self.assertEqual(updater_then, b"MZ the updater of " + INSTALLED.encode())
        # Then moved into packages\\ (the installed version's package stays for Repair), Update.exe the package's own,
        # and Velopack told to put it in silently and start the launcher again.
        self.assertEqual(len(self.handed), 1)
        info, silent, restart, packages_handed, updater_handed = self.handed[0]
        self.assertIs(info, result.info)
        self.assertEqual((silent, restart), (True, True))
        self.assertEqual(packages_handed, [named(INSTALLED), named(VERSION)])
        self.assertEqual(updater_handed, b"MZ the updater of " + VERSION.encode())
        with open(os.path.join(self.packages, named(VERSION)), "rb") as f, open(released, "rb") as g:
            self.assertEqual(f.read(), g.read())
        # Nothing left in the temporary folder, nobody told of anything, Update.exe never run, and the next start
        # knows an update was handed over.
        self.assertEqual((self.own_folders(), self.told, self.patches), ([], [], []))
        self.assertEqual(updates.outcome(), ("not_updated", VERSION, INSTALLED))

    def test_an_update_that_is_not_the_projects_never_reaches_the_install_folder(self):
        def one_bit_off(path):
            # The project's key named, the hash right, and a signature that key never made.
            signature = bytearray(bytes.fromhex(signing.sign_package(SEED, path)["signature"]))
            signature[0] ^= 1
            self.sign(path, signature=signature.hex())

        def no_signature_file(path):
            with open(path + ".sig", "w", encoding="utf-8") as f:
                f.write("not json")

        cases = {
            "no .sig in the feed": lambda path: os.remove(path + ".sig"),
            "signed by a key not built in": lambda path: self.sign(path, STRANGER),
            "signed, then other bytes": lambda path: zipped(path, files_of(VERSION, **{"lib/app/x.txt": b"y"})),
            "the .sig of another file name": lambda path: self.sign(path, file=named(OLDER)),
            "a signature one bit off": one_bit_off,
            "not a .sig at all": no_signature_file,
            "a .sig longer than any": lambda path: self.sign(path, padding="x" * signing.SIG_LIMIT),
        }
        for what, spoil in cases.items():
            with self.subTest(what=what):
                spoil(self.release())
                with self.assertLogs(updates.__name__, "WARNING") as logged:
                    error = self.refused(self.result())
                # The log says what was wrong with it and where it came from; the player reads the one sentence.
                self.assertIn("refused the update to 9.9.9 from %s: " % self.feed, logged.output[-1])
                self.assertEqual(str(error), "the update to 9.9.9 is not signed by the openDMT3 project, so it was "
                                             "not put in")

    def test_without_a_signature_the_package_is_not_even_fetched(self):
        os.remove(self.release() + ".sig")
        self.refused(self.result())
        self.assertEqual(self.fetched, [])
        # With one, it is: fetched once, after its signature.
        self.release()
        self.apply(self.result())
        self.assertEqual(self.fetched, [named(VERSION)])

    def test_a_download_that_fails_says_so_and_leaves_nothing(self):
        released = self.release()
        os.remove(released)
        # The .sig is there, the package is not: nothing to hand over, and words of its own in both languages.
        error = self.refused(self.result(), key="error.update.download")
        self.assertEqual(errors.say(error, "en"),
                         "The update to 9.9.9 could not be downloaded. Check the connection and try again.")
        self.assertEqual(errors.say(error, "ko"), "9.9.9 업데이트를 내려받지 못했습니다. 연결을 확인하고 다시 해 보세요.")
        # A feed that sends more than any package holds is cut off, and one that takes all day.
        self.release()
        with mock.patch.object(updates, "FETCH_LIMIT", 16):
            self.refused(self.result(), key="error.update.download")
        with mock.patch.object(updates, "FILE_SECONDS", -1):
            self.refused(self.result(), key="error.update.download")

    def test_update_exe_stays_when_the_package_carries_none_or_cannot_take_its_place(self):
        files = files_of(VERSION)
        del files["lib/app/Squirrel.exe"]
        self.release(files=files)
        self.apply(self.result())
        # Handed over all the same: the installed Update.exe puts a package in as well.
        self.assertEqual(self.handed[0][4], b"MZ the updater of " + INSTALLED.encode())
        self.assertEqual(os.listdir(self.install).count("Update.exe" + updates.PART), 0)
        # In use (a scanner reading it): the installed one stays whole, and no half-written file beside it.
        os.remove(os.path.join(self.packages, named(VERSION)))
        self.release()
        real = os.replace

        def replace(source, target):
            if os.path.basename(target) == "Update.exe":
                raise PermissionError("in use")
            return real(source, target)

        with mock.patch.object(os, "replace", replace):
            self.apply(self.result())
        self.assertEqual(self.handed[1][4], b"MZ the updater of " + INSTALLED.encode())
        self.assertEqual(sorted(os.listdir(self.install)), ["Update.exe", "keep-me.txt", "packages"])

    def test_a_package_from_another_drive_is_copied_in_whole_or_not_at_all(self):
        released = self.release()
        real = os.replace

        def replace(source, target):
            # A rename from the temporary folder's drive to the install folder's: Windows and Linux both refuse.
            if os.path.dirname(source) != os.path.dirname(target):
                raise OSError(18, "Invalid cross-device link")
            return real(source, target)

        with mock.patch.object(os, "replace", replace):
            self.apply(self.result())
        with open(os.path.join(self.packages, named(VERSION)), "rb") as f, open(released, "rb") as g:
            self.assertEqual(f.read(), g.read())
        self.assertEqual(self.in_packages(), [named(INSTALLED), named(VERSION)])
        # A copy cut short never takes the package's name, and never stays.
        os.remove(os.path.join(self.packages, named(VERSION)))
        self.handed.clear()

        def cut_short(source, target):
            with open(source, "rb") as f, open(target, "wb") as out:
                out.write(f.read()[:-1])

        with mock.patch.object(os, "replace", replace), mock.patch.object(shutil, "copyfile", cut_short), \
                self.assertRaises(OSError):
            self.apply(self.result())
        self.assertEqual((self.handed, self.in_packages(), self.own_folders()), ([], [named(INSTALLED)], []))

    def test_what_an_earlier_update_left_under_the_packages_name_goes_first(self):
        left = os.path.join(self.packages, named(VERSION))
        for path in (left, left + updates.PART):
            with open(path, "wb") as f:
                f.write(b"PK left by an update that never finished")
        # Refused (no signature in the feed): the leftovers are gone all the same, the installed package is not.
        os.remove(self.release() + ".sig")
        self.refused(self.result())
        # Put in: what is under the name is the package that was checked.
        with open(left, "wb") as f:
            f.write(b"PK left again")
        released = self.release()
        self.apply(self.result())
        with open(left, "rb") as f, open(released, "rb") as g:
            self.assertEqual(f.read(), g.read())

    def test_a_folder_left_by_a_launcher_that_ended_mid_update_goes_once_it_is_old(self):
        old, fresh, other = (os.path.join(self.temp, name) for name in (
            updates.OWN_PREFIX + "old", updates.OWN_PREFIX + "fresh", "someone-elses"))
        for folder in (old, fresh, other):
            os.makedirs(folder)
            with open(os.path.join(folder, named(VERSION)), "wb") as f:
                f.write(b"PK")
        # Two hours old: no update takes that long. The fresh one may be another launcher's update under way.
        long_ago = time.time() - 2 * updates.OWN_STALE
        os.utime(old, (long_ago, long_ago))
        os.utime(other, (long_ago, long_ago))
        self.release()
        self.apply(self.result())
        self.assertEqual(sorted(os.listdir(self.temp)), [updates.OWN_PREFIX + "fresh", "someone-elses"])


class OfferTest(UpdateCase):

    def refused_before_anything(self, result):
        """Refused with the feed never read, no folder made and nothing removed anywhere: before anything is fetched
        or deleted."""
        with mock.patch.object(updates, "_reader") as read, mock.patch.object(os, "remove") as remove, \
                mock.patch.object(shutil, "rmtree") as remove_folder, mock.patch.object(tempfile, "mkdtemp") as made:
            with self.assertRaises(errors.Worded) as caught:
                self.apply(result)
        for what in (read, remove, remove_folder, made):
            what.assert_not_called()
        self.assertEqual(caught.exception.key, UNSIGNED)
        self.assertEqual((self.handed, self.in_packages(), self.own_folders()), ([], [named(INSTALLED)], []))
        self.assertTrue(os.path.isfile(self.beside))

    def test_a_plain_file_name_is_one_name_and_nothing_else(self):
        for name in (named(VERSION), "a", "a.b", "..a", "a b", "한글.nupkg"):
            self.assertTrue(updates.plain(name), name)
        for name in ("", None, 7, b"a", ".", "..", "...", "a/b", "a\\b", "/a", "\\a", "../a", "..\\a", "C:a", "C:\\a",
                     "a:b", "a.", "a ", " a", "a\n", "a\x00b", "a\tb"):
            self.assertFalse(updates.plain(name), repr(name))

    def test_names_from_the_feed_are_plain_file_names_before_anything_is_fetched_or_deleted(self):
        self.release()
        self.delta()
        whole = named(VERSION)
        # The package's name: a folder above, a drive, a path of its own, a stream, an end Windows drops, no name.
        for name in ("../keep-me.txt", "..\\keep-me.txt", self.beside, os.path.join(self.packages, named(INSTALLED)),
                     "C:\\Users\\x\\" + whole, "C:" + whole, "packages/" + whole, whole + ":x", whole + ".",
                     whole + " ", ".", "..", "", None):
            with self.subTest(package=name):
                self.refused_before_anything(self.result(name=name))
        # A delta package's name, and the name of the package the deltas start from.
        for name in ("../" + named(VERSION, "delta"), "..\\x", self.beside, "C:" + named(VERSION, "delta"), "..", None):
            with self.subTest(delta=name):
                self.refused_before_anything(self.result(deltas=[(name, VERSION)]))
        for base in ("../" + named(INSTALLED), self.beside, ".."):
            with self.subTest(base=base):
                # Nothing to refuse (the whole package is the project's): the deltas are left alone, Update.exe never
                # reads a package from outside packages\\.
                self.told.clear()
                self.apply(self.with_delta(base=base))
                self.assertEqual((self.patches, self.told), ([], []))
                os.remove(os.path.join(self.packages, named(VERSION)))

    def test_the_package_is_the_one_named_for_the_version_offered(self):
        # An older release under its own name with its own signature, offered as the newer version.
        self.release(OLDER)
        self.refused_before_anything(self.result(name=named(OLDER)))
        # A delta package named for another version than the feed gives it, or for none.
        self.release()
        for delta in ((named(OLDER, "delta"), VERSION), (named(VERSION, "delta"), "not a version"),
                      (named(VERSION), VERSION)):
            with self.subTest(delta=delta):
                self.refused_before_anything(self.result(deltas=[delta]))
        # A version that is none: every file name is made of it. The feed's file name as released, then named for
        # that version itself (plain names among them, and versions that would count as newer).
        for version in ("", "9.9", "10", "10.0", "10.0.0.1", "10.0.0 x", "9.9.9/../x", "9.9.9\\x", "v9.9.9", "9.9.9 ",
                        "9.9.9\n", "10.0.0-", "10.0.0+", None):
            for name in (AS_RELEASED, named(version)):
                with self.subTest(version=version, name=name):
                    result = self.result(name=name)
                    result.version = version
                    self.refused_before_anything(result)

    def test_the_version_offered_is_newer_than_the_one_installed(self):
        for version in (INSTALLED, "9.9.7", OLDER, "9.9.8-rc.1"):
            with self.subTest(version=version):
                self.release(version)
                self.refused_before_anything(self.result(version))
        # A pre-release of a newer version is newer; so is a release after its own pre-release.
        self.release("9.9.9-rc.1")
        self.apply(self.result("9.9.9-rc.1"))
        self.assertEqual(len(self.handed), 1)

    def test_the_version_written_inside_the_package_is_the_one_offered(self):
        # Signed under the newer name with the test's key, and another version inside: what Velopack would put in.
        cases = {
            "another version inside": files_of(OLDER),
            "no manifest": {k: v for k, v in files_of(VERSION).items() if not k.endswith(".nuspec")},
            # Both say the version offered: Velopack takes the first it finds, so two are no answer at all.
            "two manifests": files_of(VERSION, **{"lib/app/other.nuspec": files_of(VERSION)["openDMT3.nuspec"]}),
            "a manifest with no version": files_of(VERSION, **{"openDMT3.nuspec": b"<package/>"}),
        }
        for what, files in cases.items():
            with self.subTest(what=what):
                self.release(files=files)
                self.refused(self.result())
        # The version as a package gives it; a package that is no zip gives none.
        self.assertEqual(updates.inside_version(self.release()), VERSION)
        self.assertIsNone(updates.inside_version(self.updater))


class DeltaPackagesTest(UpdateCase):

    def test_an_update_from_delta_packages_is_checked_delta_by_delta_then_by_its_files(self):
        # The feed holds the delta package and the signatures, and not the whole package: what is put in can only
        # have come from the delta.
        whole = self.release()
        with open(whole, "rb") as f:
            released = f.read()
        result = self.with_delta()
        os.remove(whole)
        delta = self.delta()
        checked = []
        real = signing.checks_out

        def checks_out(sig, path, name, keys=None):
            checked.append((name, real(sig, path, name, keys), len(self.patches)))
            return checked[-1][1]

        with mock.patch.object(signing, "checks_out", checks_out):
            self.apply(result)
        # The delta checked by its bytes before Update.exe was run; what Update.exe wrote is other bytes than the
        # release's (zipped again), so it was taken by the files it holds.
        self.assertEqual(checked, [(named(VERSION, "delta"), True, 0), (named(VERSION), False, 1)])
        args, kwargs, packages_then = self.patches[0]
        own = os.path.dirname(args[args.index("--output") + 1])
        self.assertEqual(args, [self.updater, "patch", "--old", self.base,
                                "--output", os.path.join(own, named(VERSION)),
                                "--delta", os.path.join(own, named(VERSION, "delta"))])
        # Written into the launcher's own folder, the install folder as it was; no window, no console read.
        self.assertTrue(own.startswith(os.path.join(self.temp, updates.OWN_PREFIX)), own)
        self.assertEqual(packages_then, [named(INSTALLED)])
        self.assertEqual((kwargs["stdin"], kwargs["capture_output"], kwargs["timeout"]),
                         (subprocess.DEVNULL, True, updates.PATCH_SECONDS))
        # Handed over: the same files as the release, other bytes; nobody told of anything else.
        self.assertEqual(len(self.handed), 1)
        put_in = os.path.join(self.packages, named(VERSION))
        with open(put_in, "rb") as f:
            self.assertNotEqual(f.read(), released)
        with open(delta + ".sig", "rb") as f:
            self.assertFalse(signing.content_checks_out(f.read(), put_in, named(VERSION)))
        with open(whole + ".sig", "rb") as f:
            self.assertTrue(signing.content_checks_out(f.read(), put_in, named(VERSION)))
        self.assertEqual((self.told, self.own_folders()), ([], []))

    def test_the_whole_package_is_taken_when_the_deltas_do_not_give_the_signed_one_and_the_player_is_told(self):
        changed = files_of(VERSION, **{"lib/app/x.txt": b"y"})
        timeout = subprocess.TimeoutExpired("Update.exe", updates.PATCH_SECONDS)
        # what: (what is wrong in the feed or the install folder, the stand-in for Update.exe, whether it is run)
        cases = {
            "the delta has no .sig": (lambda: os.remove(self.delta() + ".sig"), self.patcher(), False),
            "the delta is signed by a key not built in": (lambda: self.delta(seed=STRANGER), self.patcher(), False),
            "the delta is other bytes than signed": (
                lambda: self.delta(data=b"PK something else", signed_as=b"PK what changed"), self.patcher(), False),
            "the delta's .sig is the whole package's": (
                lambda: shutil.copy(os.path.join(self.feed, named(VERSION) + ".sig"), self.delta() + ".sig"),
                self.patcher(), False),
            "the delta is not in the feed": (lambda: os.remove(self.delta()), self.patcher(), False),
            "the package the deltas start from is gone": (
                lambda: self.delta() and os.rename(self.base, self.base + ".away"), self.patcher(), False),
            "Update.exe fails": (self.delta, self.patcher(code=1, writes=False), True),
            "Update.exe fails after it wrote the package": (self.delta, self.patcher(code=1), True),
            "Update.exe is not there": (self.delta, self.patcher(error=FileNotFoundError("Update.exe")), True),
            "Update.exe never comes back": (self.delta, self.patcher(error=timeout), True),
            "Update.exe ends well and writes nothing": (self.delta, self.patcher(writes=False), True),
            "a file of the package put together is not the signed one": (self.delta, self.patcher(changed), True),
            "the package put together holds a file more": (
                self.delta, self.patcher(files_of(VERSION, **{"lib/app/more.dll": b"MZ"})), True),
        }
        for what, (spoil, run, runs) in cases.items():
            with self.subTest(what=what):
                for seen in (self.told, self.handed, self.patches, self.fetched):
                    seen.clear()
                released = self.release()
                spoil()
                with self.assertLogs(updates.__name__, "WARNING") as logged:
                    self.apply(self.with_delta(), run)
                # The log says what was wrong in one line (no traceback for a way of failing that is expected), then
                # that the whole package is fetched.
                self.assertEqual(logged.output[-1], "WARNING:%s:downloading the whole package of 9.9.9 instead"
                                 % updates.__name__)
                self.assertEqual(len(logged.output), 2, logged.output)
                self.assertNotIn("Traceback", logged.output[0])
                if "Update.exe" in what:
                    self.assertIn("Update.exe could not put the package together", logged.output[0])
                # A delta is fetched only with a signature of its own in the feed; the whole package after it.
                self.assertEqual(self.fetched, ([] if what in ("the delta has no .sig",
                                                               "the package the deltas start from is gone")
                                                else [named(VERSION, "delta")]) + [named(VERSION)])
                # Told once, before the whole package is fetched; that package checked by its bytes and handed over.
                self.assertEqual(self.told, ["whole"])
                self.assertEqual(len(self.handed), 1)
                # Update.exe reads a delta only once the delta's own signature checked out.
                self.assertEqual(len(self.patches), 1 if runs else 0)
                with open(os.path.join(self.packages, named(VERSION)), "rb") as f, open(released, "rb") as g:
                    self.assertEqual(f.read(), g.read())
                self.assertEqual(self.own_folders(), [])
                # As before the next case.
                os.remove(os.path.join(self.packages, named(VERSION)))
                if os.path.exists(self.base + ".away"):
                    os.rename(self.base + ".away", self.base)

    def test_an_error_nobody_expected_among_the_deltas_still_ends_with_the_whole_package(self):
        released = self.release()
        self.delta()
        # Not one of Update.exe's own ways of failing: logged with where it came from, and the update goes on.
        with self.assertLogs(updates.__name__, "ERROR") as logged:
            self.apply(self.with_delta(), self.patcher(error=RuntimeError("nobody expected this")))
        self.assertIn("the delta packages of 9.9.9 could not be used", logged.output[0])
        self.assertIn("RuntimeError: nobody expected this", logged.output[0])
        self.assertEqual((self.told, len(self.handed)), (["whole"], 1))
        with open(os.path.join(self.packages, named(VERSION)), "rb") as f, open(released, "rb") as g:
            self.assertEqual(f.read(), g.read())

    def test_a_copy_that_cannot_be_written_leaves_nothing_in_packages(self):
        self.release()

        def no_room(source, target):
            # The disk fills while the package is copied in: a part of it is written, then the error.
            with open(target, "wb") as out:
                out.write(b"PK a part")
            raise OSError(28, "No space left on device")

        with mock.patch.object(os, "replace", side_effect=OSError(18, "Invalid cross-device link")), \
                mock.patch.object(shutil, "copyfile", no_room), self.assertRaises(OSError):
            self.apply(self.result())
        self.assertEqual((self.handed, self.in_packages(), self.own_folders()), ([], [named(INSTALLED)], []))

    def test_the_files_signature_is_taken_only_when_the_feed_gives_another_sha256_for_the_whole_package(self):
        self.release()
        self.delta()
        put_together = zipped(os.path.join(self.top, "as-update-exe-writes-it"), files_of(VERSION),
                              sorted(files_of(VERSION), reverse=True))
        # No SHA-256 in the feed, one that is none, and the very hash of what Update.exe wrote (bytes the feed chose
        # are checked by their bytes): the whole package each time.
        written = signing.sha256_of(put_together)
        for sha256 in ("", None, "0" * 63, "x" * 64, written, written.upper()):
            with self.subTest(sha256=sha256):
                self.told.clear()
                self.apply(self.with_delta(sha256=sha256))
                self.assertEqual(self.told, ["whole"])
                os.remove(os.path.join(self.packages, named(VERSION)))
        # The feed's hash is the whole package's, and what Update.exe wrote is other bytes: taken by its files.
        self.told.clear()
        self.apply(self.with_delta())
        self.assertEqual(self.told, [])

    def test_when_the_whole_package_is_refused_too_nothing_is_handed_over(self):
        changed = files_of(VERSION, **{"lib/app/x.txt": b"y"})
        # Neither what the deltas give nor the whole package in the feed is what the project signed.
        zipped(self.release(), changed)
        self.delta()
        result = self.with_delta()
        self.refused(result, self.patcher(changed))
        # Tried once each way, in that order: the deltas, then (said to the player) the whole package.
        self.assertEqual((len(self.patches), self.told), (1, ["whole"]))
        # The whole package cannot be fetched at all: said as a download that failed, after the same one try.
        self.told.clear()
        self.patches.clear()
        os.remove(os.path.join(self.feed, named(VERSION)))
        self.refused(result, self.patcher(changed), key="error.update.download")
        self.assertEqual((len(self.patches), self.told), (1, ["whole"]))

    def test_a_chain_of_delta_packages_ends_at_the_version_offered_or_is_left_alone(self):
        self.release()
        self.delta()
        self.delta("9.9.9-rc.1")
        both = [(named("9.9.9-rc.1", "delta"), "9.9.9-rc.1"), (named(VERSION, "delta"), VERSION)]
        self.apply(self.result(deltas=both))
        args = self.patches[0][0]
        own = os.path.dirname(args[args.index("--output") + 1])
        # Each delta in the feed's order, after --old and --output.
        self.assertEqual(args[6:], ["--delta", os.path.join(own, both[0][0]), "--delta", os.path.join(own, both[1][0])])
        self.assertEqual(self.told, [])
        # A chain that stops short of the version offered, or one too long to be worth it: the whole package, and no
        # word of it (nothing was tried).
        for deltas in (both[:1], [both[0]] * updates.MOST_DELTAS + [both[1]]):
            os.remove(os.path.join(self.packages, named(VERSION)))
            self.patches.clear()
            self.apply(self.result(deltas=deltas))
            self.assertEqual((self.patches, self.told), ([], []))


class FeedAddressTest(unittest.TestCase):

    def test_a_file_of_a_release_is_asked_for_where_the_feed_keeps_it(self):
        asked = []

        def urlopen(url, timeout):
            asked.append((url, timeout))
            return io.BytesIO(b"PK")

        with mock.patch("urllib.request.urlopen", urlopen):
            # A GitHub repository: under the release's tag. A feed address: beside releases.win.json.
            updates._reader("https://github.com/someone/openDMT3/", "openDMT3-1.2.3-full.nupkg", "1.2.3").close()
            updates._reader("https://github.com/someone/openDMT3", "openDMT3-1.2.3+b 1-delta.nupkg",
                            "1.2.3+b 1").close()
            updates._reader("http://192.0.2.1:4730/updates/", "openDMT3-1.2.3-full.nupkg", "1.2.3").close()
            self.assertEqual(updates._signature("http://192.0.2.1:4730/updates", "openDMT3-1.2.3-full.nupkg", "1.2.3"),
                             b"PK")
        self.assertEqual(asked, [
            ("https://github.com/someone/openDMT3/releases/download/v1.2.3/openDMT3-1.2.3-full.nupkg", 30),
            ("https://github.com/someone/openDMT3/releases/download/v1.2.3%2Bb%201/openDMT3-1.2.3%2Bb%201-delta.nupkg",
             30),
            ("http://192.0.2.1:4730/updates/openDMT3-1.2.3-full.nupkg", 30),
            ("http://192.0.2.1:4730/updates/openDMT3-1.2.3-full.nupkg.sig", 30),
        ])
        # No answer, or no such file: no signature, which refuses the update.
        with mock.patch("urllib.request.urlopen", side_effect=OSError("no answer")):
            self.assertIsNone(updates._signature("http://192.0.2.1:4730/updates", "openDMT3-1.2.3-full.nupkg", "1.2.3"))
        self.assertIsNone(updates._signature(tempfile.gettempdir(), "no-such-openDMT3-package.nupkg", "1.2.3"))


class Dialog:
    """The launcher's dialog as updating.py uses it, without a window: what it was made with and told since."""
    made = []

    def __init__(self, root, ui, kind, title, message, detail=None, buttons=(), **kwargs):
        self.kind, self.title, self.message, self.detail, self.buttons = kind, title, message, detail, buttons
        self.progress, self.closed = kwargs.get("progress", False), False
        Dialog.made.append(self)

    def set_words(self, message=None, detail=None):
        self.message, self.detail = message or self.message, detail or self.detail

    def close(self, value):
        self.closed = True


class Inline:
    """A thread that runs its work at start(), on the caller's thread: the test reads what happened right after."""

    def __init__(self, target, **kwargs):
        self.target = target

    def start(self):
        self.target()


@unittest.skipUnless(TK, "needs Tk, the launcher's window toolkit")
class UpdateDialogsTest(unittest.TestCase):
    """The Launcher page's Update button from its press on (client/updating.py), with stand-ins for the window."""

    def setUp(self):
        from opendmt3.client import dialogs, updating
        self.updating, self.told = updating, []
        Dialog.made = []
        for patch in (mock.patch.object(dialogs, "Dialog", Dialog),
                      mock.patch.object(dialogs, "tell", lambda app, *words: self.told.append(words)),
                      mock.patch.object(updating.threading, "Thread", Inline)):
            patch.start()
            self.addCleanup(patch.stop)
        self.result = updates.Result("available", version=VERSION, info=object(), source="feed")

    def app(self, language):
        """The launcher's window as updating.py needs it: its words, its language, post() and close()."""
        app = SimpleNamespace(root=None, ui=None, words=i18n.Words(language), state=SimpleNamespace(language=language),
                              dialog=None, closed=[])
        # What the worker posts runs at once, as the window's thread would run it next.
        app.post = lambda work: work()
        app.close = lambda: app.closed.append(True)
        return app

    def test_the_whole_package_instead_is_said_in_the_open_dialog(self):
        said = {"en": "The whole update is downloading instead of only what changed. Keep the launcher open.",
                "ko": "바뀐 부분 대신 업데이트 전체를 내려받고 있습니다. 런처를 열어 두세요."}
        for language, words in said.items():
            with self.subTest(language=language):
                Dialog.made = []
                app = self.app(language)
                seen = []

                def apply(result, tell):
                    # Before: the dialog as it opened. Then the launcher turns to the whole package.
                    seen.append((Dialog.made[0].detail, Dialog.made[0].closed))
                    tell("whole")
                    seen.append((Dialog.made[0].detail, Dialog.made[0].closed))

                with mock.patch.object(updates, "apply", apply):
                    self.updating.run(app, self.result)
                # One dialog of the launcher's, for work under way, saying the update; then the same one saying why
                # it takes longer; nothing told as a failure, and the launcher closes for Velopack.
                self.assertEqual(len(Dialog.made), 1)
                dialog = Dialog.made[0]
                self.assertEqual((dialog.kind, dialog.progress, dialog.title),
                                 ("info", True, app.words("about.updating.title")))
                self.assertEqual(dialog.message, app.words("about.updating.message", v=VERSION))
                self.assertEqual(seen, [(app.words("about.updating.detail"), False), (words, False)])
                self.assertEqual((self.told, app.closed), ([], [True]))

    def test_an_update_that_is_refused_is_told_in_the_launchers_own_dialog(self):
        refusals = {
            UNSIGNED: {"en": "The update failed: The update to 9.9.9 is not signed by the openDMT3 project, so it was "
                             "not put in.",
                       "ko": "업데이트하지 못했습니다: 9.9.9 업데이트에 openDMT3 프로젝트의 서명이 없어 설치하지 않았습니다."},
            "error.update.download": {
                "en": "The update failed: The update to 9.9.9 could not be downloaded. Check the connection and try "
                      "again.",
                "ko": "업데이트하지 못했습니다: 9.9.9 업데이트를 내려받지 못했습니다. 연결을 확인하고 다시 해 보세요."},
        }
        for key, said in refusals.items():
            for language, words in said.items():
                with self.subTest(key=key, language=language):
                    Dialog.made, self.told[:] = [], []
                    app = self.app(language)
                    error = updates.UpdateError(errors.TEXT[key][0].format(version=VERSION), key, version=VERSION)
                    with mock.patch.object(updates, "apply", side_effect=error), self.assertLogs("opendmt3.launcher"):
                        self.updating.run(app, self.result)
                    # The dialog for work under way is closed, and the reason is told in a dialog of the launcher's:
                    # an error, with the launcher's title and the error's own words in the player's language.
                    self.assertTrue(Dialog.made[0].closed)
                    self.assertEqual(self.told, [("error", app.words("about.update_failed.title"), words)])
                    # The launcher stays open, on no dialog.
                    self.assertEqual((app.closed, app.dialog), ([], None))

    def test_an_error_of_no_words_of_its_own_is_told_as_it_is(self):
        app = self.app("ko")
        with mock.patch.object(updates, "apply", side_effect=RuntimeError("velopack said no")), \
                self.assertLogs("opendmt3.launcher"):
            self.updating.run(app, self.result)
        self.assertEqual(self.told, [("error", "업데이트 실패", "업데이트하지 못했습니다: Velopack said no")])


class StartTest(unittest.TestCase):

    def test_velopack_is_told_at_every_start_to_put_in_nothing_by_itself(self):
        from opendmt3.client import main
        calls = []

        class App:
            """Velopack's start-up object: what the launcher calls on it, in order."""

            def set_auto_apply_on_startup(self, apply):
                calls.append(("auto apply", apply))

            def run(self):
                calls.append("run")

        fake = mock.MagicMock()
        fake.App = App
        with mock.patch.dict("sys.modules", {"velopack": fake}):
            main._velopack_hooks([])
        # Before run(): Velopack would otherwise put in whatever package it finds in packages\\ at start.
        self.assertEqual(calls, [("auto apply", False), "run"])
        # A Velopack without the switch: said in the log, so it is seen.
        del App.set_auto_apply_on_startup
        with mock.patch.dict("sys.modules", {"velopack": fake}), \
                self.assertLogs("opendmt3.launcher", "WARNING") as logged:
            main._velopack_hooks([])
        self.assertIn("leave packages alone", logged.output[0])


class CommandLineTest(unittest.TestCase):

    def test_the_command_line_says_the_whole_package_instead_as_a_line(self):
        from opendmt3.client import cli
        found = updates.Result("available", version=VERSION, info=object())
        out = io.StringIO()
        with mock.patch.object(updates, "check", return_value=found), \
                mock.patch.object(updates, "apply", lambda result, tell: tell("whole")), \
                contextlib.redirect_stdout(out), self.assertLogs("opendmt3.launcher"):
            self.assertEqual(cli._update(True, None), 0)
        self.assertEqual(out.getvalue().splitlines(), [
            "openDMT3 9.9.9 is available (this is %s)." % (updates.current_version() or __version__),
            "The whole update is downloading instead of only what changed.",
            "Updating: the launcher starts again in a few seconds."])


if __name__ == "__main__":
    unittest.main()
