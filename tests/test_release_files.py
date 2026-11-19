"""A release's files (packaging/release_files.py) and the guides' download lines (packaging/doc_versions.py): every
file named in lowercase with its version but the launcher's update files, the server package holding the server and
nothing of the launcher or the tests, the OpenAL sources checked against the build's hashes, the SHA-256 sums over
every file, the maintainer's Files table, no guide naming another version than the code's, and none naming a file the
release does not have."""

import hashlib
import importlib.util
import io
import os
import re
import shutil
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

# The repository's top folder (this file is in tests/).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The server's package is made from the files git tracks: a tree exported without its .git (a source archive, the
# local run of CI's jobs) cannot make it, so the tests that make it run only in a git checkout.
IN_GIT = os.path.isdir(os.path.join(ROOT, ".git")) or os.path.isfile(os.path.join(ROOT, ".git"))
NEEDS_GIT = unittest.skipUnless(IN_GIT, "the server's package is made from a git checkout's tracked files")


def load(name):
    """A script of packaging/ as a module: no package holds it, so it is loaded from its file, as release.sh runs it."""
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "packaging", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


files = load("release_files")
doc_versions = load("doc_versions")
# A made-up version, so nothing here passes only because it is the tree's own.
V = "9.8.7"


def build(folder, signed=True, delta=True):
    """A made-up build folder as packaging/windows/build.sh leaves it: the installer, Velopack's files (and the extra
    ones of vpk's that are no part of a release), and the two LGPL archives with their SHA256SUMS."""
    releases = Path(folder) / "releases"
    releases.mkdir(parents=True)
    names = ["opendmt3-launcher-%s-windows-x64-setup.exe" % V, "openDMT3-%s-full.nupkg" % V, "releases.win.json",
             "RELEASES", "assets.win.json", "openDMT3-win-Portable.zip", "openDMT3-9.8.6-full.nupkg"]
    names += ["openDMT3-%s-delta.nupkg" % V] if delta else []
    names += [n + ".sig" for n in names if n.startswith("openDMT3-%s-" % V)] if signed else []
    for name in names:
        (releases / name).write_bytes(name.encode())
    sources = Path(folder) / "openal" / "sources"
    sources.mkdir(parents=True)
    sums = []
    for name in ("openal-soft-1.0.0.tar.gz", "dsoal-0123abc.tar.gz"):
        (sources / name).write_bytes(b"source of " + name.encode())
        sums.append("%s  %s" % (hashlib.sha256(b"source of " + name.encode()).hexdigest(), name))
    (sources / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    return Path(folder)


def run(module, *argv):
    """A script's exit code, standard output and standard error."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = module.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class ReleaseFilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.out = Path(self.tmp) / "out" / "files"

    @NEEDS_GIT
    def test_every_file_with_its_role_its_version_and_the_sha256_sums(self):
        code, table, err = run(files, "v" + V, str(build(Path(self.tmp) / "build")), str(self.out))
        self.assertEqual((code, err), (0, ""))
        got = sorted(os.listdir(self.out))
        self.assertEqual(got, sorted([
            "opendmt3-launcher-%s-windows-x64-setup.exe" % V, "opendmt3-server-%s-linux-macos.zip" % V,
            "opendmt3-launcher-%s-openal-sources.zip" % V, "opendmt3-%s-sha256sums.txt" % V,
            "openDMT3-%s-full.nupkg" % V, "openDMT3-%s-delta.nupkg" % V, "openDMT3-%s-full.nupkg.sig" % V,
            "openDMT3-%s-delta.nupkg.sig" % V, "releases.win.json",
            # The one-line installers are made from the tree each time; the server's built files come with --server.
            "opendmt3-server-%s-linux-installer.sh" % V, "opendmt3-server-%s-macos-installer.sh" % V]))
        # vpk's own extras and the previous release's package stay out: each is no file of this release.
        for left in ("RELEASES", "assets.win.json", "openDMT3-win-Portable.zip", "openDMT3-9.8.6-full.nupkg"):
            self.assertNotIn(left, got)
        # Every name but the update files' is lowercase and carries the version.
        for name in got:
            if not (name.startswith("openDMT3-") or name == "releases.win.json"):
                self.assertEqual(name, name.lower())
                self.assertIn(V, name)
        # The SHA-256 sums, in sha256sum's own form, over every other file.
        lines = (self.out / ("opendmt3-%s-sha256sums.txt" % V)).read_text().splitlines()
        self.assertEqual(len(lines), len(got) - 1)
        for line in lines:
            digest, name = line.split("  ", 1)
            self.assertEqual(hashlib.sha256((self.out / name).read_bytes()).hexdigest(), digest)
        # The Files table: a row for each file, the update files said to be the launcher's, FILES.md the same.
        self.assertTrue(table.startswith("### Files\n\n| File | What it is | For |"))
        self.assertEqual(table.count("\n| `"), len(got))
        self.assertIn("| `openDMT3-%s-full.nupkg` | The launcher's update package" % V, table)
        self.assertIn("| Server owners on Linux and macOS |", table)
        self.assertEqual((self.out.parent / "FILES.md").read_text(), table)

    @NEEDS_GIT
    def test_the_servers_built_files_come_from_their_folder_under_the_release_names(self):
        server = Path(self.tmp) / "server"
        server.mkdir()
        (server / ("opendmt3-server-%s-windows-x64.zip" % V)).write_bytes(b"PK windows")
        (server / ("opendmt3-%s.tgz" % V)).write_bytes(b"chart")
        code, _, err = run(files, V, str(build(Path(self.tmp) / "build")), str(self.out), "--server", str(server))
        self.assertEqual((code, err), (0, ""))
        # Helm's own name for the chart's package, the server's chart's name in the release.
        self.assertEqual((self.out / ("opendmt3-server-%s-helm-chart.tgz" % V)).read_bytes(), b"chart")
        self.assertTrue((self.out / ("opendmt3-server-%s-windows-x64.zip" % V)).is_file())
        # The installers carry the version where the script has its mark, and the sums name them all.
        script = (self.out / ("opendmt3-server-%s-linux-installer.sh" % V)).read_text()
        self.assertIn("VERSION=%s\n" % V, script)
        self.assertNotIn("@VERSION@", script)
        # What the installer downloads is what the release has, by name: the server's zip and the sums naming it.
        self.assertIn('zip="%s"' % files.SERVER_ZIP.format(v="$VERSION"), script)
        self.assertIn('fetch "%s"' % files.SUMS.format(v="$VERSION"), script)
        sums = (self.out / ("opendmt3-%s-sha256sums.txt" % V)).read_text()
        for name in ("opendmt3-server-%s-helm-chart.tgz", "opendmt3-server-%s-windows-x64.zip",
                     "opendmt3-server-%s-macos-installer.sh", "opendmt3-server-%s-linux-macos.zip"):
            self.assertIn("  " + name % V + "\n", sums)
        # A --server folder without them is a release missing them.
        (server / ("opendmt3-%s.tgz" % V)).unlink()
        code, _, err = run(files, V, str(build(Path(self.tmp) / "build2")), str(self.out), "--server", str(server))
        self.assertEqual(code, 1)
        self.assertIn("helm-chart.tgz", err)

    @NEEDS_GIT
    def test_the_openal_sources_are_the_archives_the_build_names(self):
        made = build(Path(self.tmp) / "build")
        code, _, _ = run(files, V, str(made), str(self.out))
        self.assertEqual(code, 0)
        # Under one folder named as the zip.
        with zipfile.ZipFile(self.out / ("opendmt3-launcher-%s-openal-sources.zip" % V)) as zf:
            top = "opendmt3-launcher-%s-openal-sources/" % V
            self.assertEqual(sorted(zf.namelist()), sorted(top + n for n in
                                                           ("openal-soft-1.0.0.tar.gz", "dsoal-0123abc.tar.gz",
                                                            "SHA256SUMS")))
        # An archive that is not the one the libraries were built from: no release.
        (made / "openal" / "sources" / "dsoal-0123abc.tar.gz").write_bytes(b"other source")
        code, _, err = run(files, V, str(made), str(self.out))
        self.assertEqual(code, 1)
        self.assertIn("dsoal-0123abc.tar.gz is not the archive SHA256SUMS names", err)

    @NEEDS_GIT
    def test_a_rehearsal_without_the_key_or_a_previous_release(self):
        # No signatures, no delta: the rest is there, and the table names only what is.
        code, table, err = run(files, V, str(build(Path(self.tmp) / "build", signed=False, delta=False)),
                               str(self.out))
        self.assertEqual((code, err), (0, ""))
        self.assertNotIn(".sig", table)
        self.assertNotIn("delta", table)
        # Without the installer, no release.
        os.remove(Path(self.tmp) / "build" / "releases" / ("opendmt3-launcher-%s-windows-x64-setup.exe" % V))
        code, _, err = run(files, V, str(Path(self.tmp) / "build"), str(self.out))
        self.assertEqual(code, 1)
        self.assertIn("missing: opendmt3-launcher-%s-windows-x64-setup.exe" % V, err)

    def test_names_out_of_line_are_refused(self):
        problems = files.check_names(V, ["opendmt3-launcher-%s-windows-x64-setup.exe" % V, "Openal-soft.tar.gz",
                                         "openDMT3-%s-full.nupkg" % V])
        self.assertEqual(problems, ["Openal-soft.tar.gz is not one of a release's files"])
        # The table's own names: only the update files are in other letters.
        for pattern, _, _ in files.ROLES:
            name = pattern.format(v=V)
            if pattern not in files.UPDATE_FILES:
                self.assertEqual(name, name.lower(), name)
        # The update files keep the names client/updates.py checks, letter for letter.
        from opendmt3.client import updates
        self.assertIn("%s-{v}-full.nupkg" % updates.PACKAGE_ID, files.UPDATE_FILES)
        self.assertIn("%s-{v}-delta.nupkg" % updates.PACKAGE_ID, files.UPDATE_FILES)


class ServerPackageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    @NEEDS_GIT
    def test_the_server_and_its_guides_and_nothing_of_the_launcher_or_the_tests(self):
        path = files.server_zip(Path(ROOT), V, self.tmp)
        self.assertEqual(path.name, "opendmt3-server-%s-linux-macos.zip" % V)
        top = "opendmt3-server-%s-linux-macos/" % V
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            infos = {i.filename: i for i in zf.infolist()}
            readme = zf.read(top + "README.md").decode()
        # All under one folder named as the zip.
        self.assertTrue(all(n.startswith(top) for n in names))
        inside = {n[len(top):] for n in names}
        # What ./dmt3 setup and python -m opendmt3.server need.
        for needed in ("dmt3", "compose.yaml", ".dockerignore", "LICENSE", "packaging/docker/Dockerfile",
                       "packaging/docker/wizard.py", "opendmt3/__init__.py", "opendmt3/server/__main__.py",
                       "opendmt3/core/errors.py", "opendmt3/client/assets/fonts/Saira-OFL.txt", "docs/server.md",
                       "docs/images/ways-to-host-light.svg"):
            self.assertIn(needed, inside)
        # Nothing of the launcher's code, its build, the native parts, the tests or a working folder.
        for name in inside:
            self.assertFalse(name.startswith(("tests/", "native/", "packaging/windows/", "_work/", ".github/")), name)
            self.assertFalse(name.startswith("opendmt3/client/") and not name.startswith("opendmt3/client/assets/"),
                             name)
            self.assertNotIn("__pycache__", name)
        # ./dmt3 stays a program after unzip; a guide does not become one.
        self.assertEqual((infos[top + "dmt3"].external_attr >> 16) & 0o777, 0o755)
        self.assertEqual((infos[top + "docs/server.md"].external_attr >> 16) & 0o777, 0o644)
        # The package's own README, quick start first, not the repository's.
        self.assertEqual(readme, Path(ROOT, files.SERVER_README).read_text(encoding="utf-8"))
        self.assertEqual(re.findall(r"^## (.+)$", readme, re.M)[0], "Quick start")
        # The same tree makes the same zip.
        again = files.server_zip(Path(ROOT), V, os.path.join(self.tmp))
        self.assertEqual(again.read_bytes(), path.read_bytes())

    @NEEDS_GIT
    def test_every_link_of_the_package_s_guides_is_in_the_package(self):
        tracked = set(files.tracked(Path(ROOT)))
        taken = set(files.guides(Path(ROOT), tracked))
        # Each guide's links and pictures, followed: none points at a file the package does not hold.
        self.assertIn("docs/client-data.md", taken)
        self.assertIn("docs/images/chart-server-dark.svg", taken)
        # A guide pointing outside what the package holds is refused (the instrument finds what it is for).
        planted = Path(self.tmp) / "tree"
        (planted / "docs").mkdir(parents=True)
        (planted / "docs" / "server.md").write_text("See [the tests](../tests/test_docs.py).\n")
        for guide in files.SERVER_GUIDES[1:]:
            (planted / guide).write_text("Nothing.\n")
        with self.assertRaises(ValueError):
            files.guides(planted, {"docs/server.md", "tests/test_docs.py"} | set(files.SERVER_GUIDES))


class DocVersionsTest(unittest.TestCase):
    def test_the_guides_name_the_code_s_version(self):
        version = doc_versions.code_version(Path(ROOT))
        self.assertEqual(doc_versions.stale(Path(ROOT), version), [])
        # The README's download is this version's installer, from this version's release.
        readme = Path(ROOT, "README.md").read_text(encoding="utf-8")
        self.assertIn("releases/download/v%s/opendmt3-launcher-%s-windows-x64-setup.exe" % (version, version), readme)

    def test_the_guides_name_only_files_a_release_has(self):
        # Every release file a page names by a version (this one, <version> or X.Y.Z) is one the release makes, so a
        # file renamed leaves no guide or download line under its old name.
        version = doc_versions.code_version(Path(ROOT))
        known = set(files.names(version))
        named = re.compile(r"opendmt3-[A-Za-z0-9.<>-]+\.(?:zip|exe|sh|tgz|txt)\b")
        seen = set()
        for page in doc_versions.pages(Path(ROOT)):
            path = Path(ROOT, page)
            if not path.is_file():
                continue
            for name in named.findall(path.read_text(encoding="utf-8")):
                # A name without a version (opendmt3-server.exe, the program inside a package) is no release file.
                plain = name.replace("<version>", version).replace("X.Y.Z", version)
                if version in plain:
                    self.assertTrue(plain in known, "%s names %s, which no release has" % (page, name))
                    seen.add(plain)
        # The instrument reads the pages: the guides name the server's zip, its Helm chart and the sums.
        for name in ("opendmt3-server-%s-linux-macos.zip", "opendmt3-server-%s-helm-chart.tgz",
                     "opendmt3-%s-sha256sums.txt"):
            self.assertIn(name % version, seen)

    def test_another_version_is_found_and_written_over(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        (tmp / "opendmt3").mkdir()
        (tmp / "opendmt3" / "__init__.py").write_text('__version__ = "1.2.4"\n')
        (tmp / "docs").mkdir()
        (tmp / "docs" / "install.md").write_text(
            "curl -LO https://x/releases/download/v1.2.3/opendmt3-launcher-1.2.3-windows-x64-setup.exe\n"
            "unzip opendmt3-server-1.2.3-linux-macos.zip\ncd opendmt3-server-1.2.3-linux-macos\n"
            "opendmt3-server-1.2.3-helm-chart.tgz, opendmt3-1.2.3-sha256sums.txt and "
            "opendmt3-launcher-1.2.3-openal-sources.zip\nopendmt3-launcher-<version>-windows-x64-setup.exe stays\n")
        code, _, err = run(doc_versions, "--root", str(tmp))
        self.assertEqual(code, 1)
        # Each name's version: the address and the installer, the zip and its folder, the chart, the sums, the sources.
        self.assertEqual(err.count("names 1.2.3"), 7)
        run(doc_versions, "--root", str(tmp), "--write")
        text = (tmp / "docs" / "install.md").read_text()
        # The version alone changed: the part after it stays (-windows-x64), and a pattern without one stays.
        self.assertIn("v1.2.4/opendmt3-launcher-1.2.4-windows-x64-setup.exe", text)
        self.assertIn("opendmt3-server-1.2.4-linux-macos.zip\ncd opendmt3-server-1.2.4-linux-macos\n", text)
        self.assertIn("opendmt3-server-1.2.4-helm-chart.tgz, opendmt3-1.2.4-sha256sums.txt and "
                      "opendmt3-launcher-1.2.4-openal-sources.zip", text)
        self.assertIn("opendmt3-launcher-<version>-windows-x64-setup.exe stays", text)
        self.assertEqual(run(doc_versions, "--root", str(tmp))[0], 0)


if __name__ == "__main__":
    unittest.main()
