"""A release's files (packaging/release_files.py), the server's packages for Linux and macOS (packaging/server/
bundle.py) and the guides' download lines (packaging/doc_versions.py): every file named in lowercase with its version
but the launcher's update files, the one-line installers fetching the files the release has by their names, the
packages' pinned files in step with every other place that pins them, put together the same way each time, the
OpenAL sources checked against the build's hashes, the SHA-256 sums over every file, the maintainer's Files table, no
guide naming another version than the code's, and none naming a file the release does not have."""

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


def load(name):
    """A script of packaging/ as a module: no package holds it, so it is loaded from its file, as release.sh runs it."""
    spec = importlib.util.spec_from_file_location(name.replace("/", "_"), os.path.join(ROOT, "packaging", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


files = load("release_files")
doc_versions = load("doc_versions")
bundle = load("server/bundle")
# A made-up version, so nothing here passes only because it is the tree's own.
V = "9.8.7"


def build(folder, signed=True, delta=True):
    """A made-up build folder as packaging/windows/build.sh leaves it: the installer, Velopack's files (and the extra
    ones of vpk's that are no part of a release), and the two LGPL archives with their SHA256SUMS."""
    releases = Path(folder) / "releases"
    releases.mkdir(parents=True)
    names = ["opendmt3-launcher-%s-windows-x64-installer.exe" % V, "openDMT3-%s-full.nupkg" % V, "releases.win.json",
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

    def test_every_file_with_its_role_its_version_and_the_sha256_sums(self):
        code, table, err = run(files, "v" + V, str(build(Path(self.tmp) / "build")), str(self.out))
        self.assertEqual((code, err), (0, ""))
        got = sorted(os.listdir(self.out))
        self.assertEqual(got, sorted([
            "opendmt3-launcher-%s-windows-x64-installer.exe" % V,
            "opendmt3-launcher-%s-openal-sources.zip" % V, "opendmt3-%s-sha256sums.txt" % V,
            "openDMT3-%s-full.nupkg" % V, "openDMT3-%s-delta.nupkg" % V, "openDMT3-%s-full.nupkg.sig" % V,
            "openDMT3-%s-delta.nupkg.sig" % V, "releases.win.json",
            # The one-line installers are made from the tree each time; the server's built files come with --server.
            "opendmt3-server-%s-linux-installer.sh" % V, "opendmt3-server-%s-macos-installer.sh" % V,
            "opendmt3-server-%s-windows-installer.ps1" % V]))
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
        self.assertIn("| `opendmt3-server-%s-windows-installer.ps1` | The one-line install of the server on Windows" % V,
                      table)
        self.assertEqual((self.out.parent / "FILES.md").read_text(), table)

    def test_the_servers_built_files_come_from_their_folder_under_the_release_names(self):
        server = Path(self.tmp) / "server"
        server.mkdir()
        (server / ("opendmt3-server-%s-windows-x64.zip" % V)).write_bytes(b"PK windows")
        (server / ("opendmt3-%s.tgz" % V)).write_bytes(b"chart")
        for target in files.UNIX_TARGETS:
            (server / ("opendmt3-server-%s-%s.tar.gz" % (V, target))).write_bytes(target.encode())
        code, _, err = run(files, V, str(build(Path(self.tmp) / "build")), str(self.out), "--server", str(server))
        self.assertEqual((code, err), (0, ""))
        # Helm's own name for the chart's package, the server's chart's name in the release.
        self.assertEqual((self.out / ("opendmt3-server-%s-helm-chart.tgz" % V)).read_bytes(), b"chart")
        self.assertTrue((self.out / ("opendmt3-server-%s-windows-x64.zip" % V)).is_file())
        # The four packages for Linux and macOS, as bundle.py names them.
        for target in files.UNIX_TARGETS:
            self.assertEqual((self.out / ("opendmt3-server-%s-%s.tar.gz" % (V, target))).read_bytes(), target.encode())
            self.assertEqual(bundle.name_of(V, target) + ".tar.gz", files.UNIX_PACKAGE.format(v=V) % target)
        # The installers carry the version where the script has its mark, and the sums name them all.
        script = (self.out / ("opendmt3-server-%s-linux-installer.sh" % V)).read_text()
        self.assertEqual(script, (self.out / ("opendmt3-server-%s-macos-installer.sh" % V)).read_text())
        self.assertIn("VERSION=%s\n" % V, script)
        self.assertNotIn("@VERSION@", script)
        # What the installer downloads is what the release has, by name: the package for the machine, by the very
        # pattern the release names them by, and the sums naming it.
        self.assertIn('name="%s"' % files.UNIX_PACKAGE.format(v="$VERSION")[:-len(".tar.gz")].replace("%s", "$key"),
                      script)
        self.assertIn('archive="$name.tar.gz"', script)
        self.assertIn('fetch "%s"' % files.SUMS.format(v="$VERSION"), script)
        # The words for the machine are the release's: linux or macos, x64 or arm64.
        for word in ("system=linux", "system=macos", "processor=x64", "processor=arm64"):
            self.assertIn(word, script)
        # The Windows installer: the version written in, the Windows package and the sums by the release's names.
        windows = (self.out / ("opendmt3-server-%s-windows-installer.ps1" % V)).read_text()
        self.assertIn("$version = '%s'" % V, windows)
        self.assertNotIn("@VERSION@", windows)
        self.assertIn('$name = "%s"' % "opendmt3-server-{v}-windows-x64.zip".format(v="$version")[:-len(".zip")],
                      windows)
        self.assertIn('$archive = "$name.zip"', windows)
        self.assertIn('$sums = "%s"' % files.SUMS.format(v="$version"), windows)
        sums = (self.out / ("opendmt3-%s-sha256sums.txt" % V)).read_text()
        for name in ["opendmt3-server-%s-helm-chart.tgz", "opendmt3-server-%s-windows-x64.zip",
                     "opendmt3-server-%s-macos-installer.sh", "opendmt3-server-%s-windows-installer.ps1"] + [
                         "opendmt3-server-%%s-%s.tar.gz" % target for target in files.UNIX_TARGETS]:
            self.assertIn("  " + name % V + "\n", sums)
        # A --server folder without them is a release missing them: the chart, or a package for one system.
        (server / ("opendmt3-%s.tgz" % V)).unlink()
        code, _, err = run(files, V, str(build(Path(self.tmp) / "build2")), str(self.out), "--server", str(server))
        self.assertEqual(code, 1)
        self.assertIn("helm-chart.tgz", err)
        (server / ("opendmt3-%s.tgz" % V)).write_bytes(b"chart")
        (server / ("opendmt3-server-%s-macos-arm64.tar.gz" % V)).unlink()
        code, _, err = run(files, V, str(build(Path(self.tmp) / "build3")), str(self.out), "--server", str(server))
        self.assertEqual(code, 1)
        self.assertIn("macos-arm64.tar.gz", err)

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

    def test_a_rehearsal_without_the_key_or_a_previous_release(self):
        # No signatures, no delta: the rest is there, and the table names only what is.
        code, table, err = run(files, V, str(build(Path(self.tmp) / "build", signed=False, delta=False)),
                               str(self.out))
        self.assertEqual((code, err), (0, ""))
        self.assertNotIn(".sig", table)
        self.assertNotIn("delta", table)
        # Without the installer, no release.
        os.remove(Path(self.tmp) / "build" / "releases" / ("opendmt3-launcher-%s-windows-x64-installer.exe" % V))
        code, _, err = run(files, V, str(Path(self.tmp) / "build"), str(self.out))
        self.assertEqual(code, 1)
        self.assertIn("missing: opendmt3-launcher-%s-windows-x64-installer.exe" % V, err)

    def test_names_out_of_line_are_refused(self):
        problems = files.check_names(V, ["opendmt3-launcher-%s-windows-x64-installer.exe" % V, "Openal-soft.tar.gz",
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


class BundleTest(unittest.TestCase):
    """The server's packages for Linux and macOS (packaging/server/bundle.py), without building one: the pinned files
    each is made from, the parts left out of its Python, the wheels laid out as pip lays them, the archive written the
    same way each time, and the files written from the templates. CI's package job builds and runs the real ones."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_every_target_is_made_from_pinned_files_alone(self):
        self.assertEqual(sorted(bundle.TARGETS), sorted(files.UNIX_TARGETS))
        for key, target in bundle.TARGETS.items():
            found = bundle.inputs([key])
            names = [name for name, _, _ in found]
            # Its Python, its 7-Zip and every library's wheel, each once, and the builder's Python (linux-x64's).
            self.assertIn(target.python, names)
            self.assertIn(target.sevenzip, names)
            self.assertIn(bundle.TARGETS["linux-x64"].python, names)
            self.assertEqual(len(names), len(set(names)))
            self.assertEqual(sum(n.endswith(".whl") for n in names), len(bundle.WHEELS) + len(target.wheels))
            for name, url, sha in found:
                # Each by HTTPS, each by its SHA-256, the file named as its address names it.
                self.assertTrue(url.startswith("https://"), url)
                self.assertRegex(sha, r"^[0-9a-f]{64}$")
                self.assertTrue(url.endswith("/" + name) or url.endswith("/" + name.replace("+", "%2B")), url)
            # A wheel with a compiled part is the target's own: its system and processor in its name.
            system, processor = key.split("-")
            for url, _ in target.wheels:
                wheel = url.rsplit("/", 1)[1]
                self.assertIn("manylinux" if system == "linux" else "macosx", wheel)
                self.assertIn({"x64": "x86_64", "arm64": "aarch64" if system == "linux" else "arm64"}[processor], wheel)

    def test_the_pins_are_those_of_every_other_place_that_pins_them(self):
        # The Python release the launcher's Windows build pins, the same CPython.
        build_sh = Path(ROOT, "packaging", "windows", "build.sh").read_text(encoding="utf-8")
        self.assertIn("/releases/download/%s/cpython-%s%%2B%s-" % (bundle.PYTHON_RELEASE, bundle.PYTHON_VERSION,
                                                                  bundle.PYTHON_RELEASE), build_sh)
        # The 7-Zip the server's image and CI take, by the same archive and hash.
        dockerfile = Path(ROOT, "packaging", "docker", "Dockerfile").read_text(encoding="utf-8")
        ci = Path(ROOT, ".github", "workflows", "ci.yml").read_text(encoding="utf-8")
        for key in ("linux-x64", "linux-arm64"):
            target = bundle.TARGETS[key]
            self.assertIn("--checksum=sha256:%s \\\n    https://www.7-zip.org/a/%s" % (target.sevenzip_sha256,
                                                                                     target.sevenzip), dockerfile)
        self.assertIn("%s  $RUNNER_TEMP/7z.tar.xz" % bundle.TARGETS["linux-x64"].sevenzip_sha256, ci)
        # One 7-Zip release for every system (the Mac's archive is one for both processors).
        self.assertEqual({t.sevenzip.split("-")[0] for t in bundle.TARGETS.values()}, {"7z2501"})
        self.assertEqual(bundle.TARGETS["macos-x64"].sevenzip_sha256, bundle.TARGETS["macos-arm64"].sevenzip_sha256)
        # The site's libraries at the versions the server's image and CI pin.
        pinned = dict(re.findall(r"\b(starlette|jinja2|uvicorn|python-multipart|pillow)==([0-9.]+)", dockerfile))
        self.assertEqual(len(pinned), 5)
        for target in bundle.TARGETS.values():
            wheels = {re.sub(r"[-_]", "-", w.rsplit("/", 1)[1].split("-")[0].lower()): w.rsplit("/", 1)[1].split("-")[1]
                      for w, _ in bundle.WHEELS + target.wheels}
            for name, version in pinned.items():
                self.assertEqual(wheels[name.replace("_", "-")], version, name)
        for name, version in pinned.items():
            self.assertIn("%s==%s" % (name, version), ci)

    def test_what_the_python_leaves_out(self):
        for gone in ("include/python3.12/Python.h", "share/terminfo/x/xterm", "lib/tcl9.0/init.tcl", "lib/libtcl9.0.so",
                     "lib/libpython3.12.so.1.0", "lib/libpython3.12.dylib", "bin/pip3", "bin/idle3.12",
                     "bin/python3.12-config", "lib/python3.12/tkinter/__init__.py", "lib/python3.12/ensurepip",
                     "lib/python3.12/lib-dynload/_tkinter.cpython-312-x86_64-linux-gnu.so",
                     "lib/python3.12/lib-dynload/_dbm.cpython-312-darwin.so",
                     "lib/python3.12/site-packages/pip/__init__.py",
                     "lib/python3.12/site-packages/pip-26.2.2.dist-info/METADATA"):
            self.assertTrue(bundle.left_out(gone), gone)
        for kept in ("bin/python3", "bin/python3.12", "lib/python3.12/os.py", "lib/python3.12/sqlite3/__init__.py",
                     "lib/python3.12/lib-dynload/.empty", "lib/python3.12/LICENSE.txt", "lib/python3.12/site-packages",
                     "lib/python3.12/turtle_like.py", "lib/python3.12/encodings/utf_8.py"):
            self.assertFalse(bundle.left_out(kept), kept)

    def wheel(self, name, entries):
        """A made-up wheel of these entries ({name: bytes}), with a .dist-info of the name given."""
        path = self.tmp / ("%s-1.0-py3-none-any.whl" % name)
        with zipfile.ZipFile(path, "w") as zf:
            for entry, data in entries.items():
                zf.writestr(entry, data)
        return path

    def test_a_wheel_goes_in_as_pip_lays_it_out(self):
        site = self.tmp / "site"
        site.mkdir()
        meta = "Metadata-Version: 2.4\nName: Made-up\nVersion: 1.0\nLicense-Expression: MIT\nLicense-File: LICENSE\n"
        path = self.wheel("made_up", {"made_up/__init__.py": b"x = 1\n", "made_up-1.0.dist-info/METADATA": meta,
                                      "made_up-1.0.dist-info/licenses/LICENSE": b"MIT text\n",
                                      "made_up-1.0.data/platlib/_made_up.so": b"\x7fELF"})
        self.assertEqual(bundle.install_wheel(path, site), "made_up-1.0.dist-info")
        # Its modules and its .data/platlib part at the top, its licence where its metadata names it.
        self.assertTrue((site / "made_up" / "__init__.py").is_file())
        self.assertTrue((site / "_made_up.so").is_file())
        name, version, licence, texts = bundle.dist_licences(site, "made_up-1.0.dist-info")
        self.assertEqual((name, version, licence), ("Made-up", "1.0", "MIT"))
        self.assertEqual([p.read_bytes() for p in texts], [b"MIT text\n"])
        # A wheel bringing scripts, or a path outside its folder, is no wheel the packages take.
        for entries in ({"x/__init__.py": b"", "x-1.0.data/scripts/x": b"#!/bin/sh\n"},
                        {"../outside.py": b"", "x-1.0.dist-info/METADATA": meta}):
            with self.assertRaises(ValueError):
                bundle.install_wheel(self.wheel("x", entries), self.tmp / "site2")
        # Metadata naming no licence at all stops the build.
        (site / "made_up-1.0.dist-info" / "METADATA").write_text("Metadata-Version: 2.1\nName: Made-up\nVersion: 1.0\n")
        with self.assertRaises(ValueError):
            bundle.dist_licences(site, "made_up-1.0.dist-info")

    def stage(self, root):
        """A made-up package folder: a program, a nested file, a link to a file and an empty folder."""
        stage = root / "opendmt3-server-9.8.7-linux-x64"
        (stage / "lib" / "python" / "bin").mkdir(parents=True)
        (stage / "opendmt3-server").write_text("#!/bin/sh\n")
        (stage / "opendmt3-server").chmod(0o775)
        (stage / "lib" / "python" / "bin" / "python3.12").write_bytes(b"\x7fELF made up")
        (stage / "lib" / "python" / "bin" / "python3.12").chmod(0o700)
        os.symlink("python3.12", stage / "lib" / "python" / "bin" / "python3")
        (stage / "README.txt").write_text("words\n")
        (stage / "lib" / "empty").mkdir()
        return stage

    def test_the_archive_is_the_same_bytes_from_the_same_folder(self):
        import tarfile
        one = self.stage(self.tmp / "one")
        two = self.stage(self.tmp / "two")
        # The second folder made at another time with other permissions for the group: nothing of that goes in.
        os.utime(two / "README.txt", (1, 1))
        (two / "README.txt").chmod(0o664)
        bundle.manifest(one)
        bundle.manifest(two)
        bundle.write_archive(one, self.tmp / "one.tar.gz")
        bundle.write_archive(two, self.tmp / "two.tar.gz")
        self.assertEqual((self.tmp / "one.tar.gz").read_bytes(), (self.tmp / "two.tar.gz").read_bytes())
        # gzip's header carries no time (bytes 4 to 8) and no name (no FNAME flag).
        head = (self.tmp / "one.tar.gz").read_bytes()[:10]
        self.assertEqual(head[4:8], b"\0\0\0\0")
        self.assertFalse(head[3] & 0x08)
        with tarfile.open(self.tmp / "one.tar.gz") as archive:
            members = archive.getmembers()
        names = [m.name for m in members]
        # One top folder of the package's name, every member in sorted order under it.
        self.assertEqual(names[0], "opendmt3-server-9.8.7-linux-x64")
        self.assertTrue(all(n.startswith(names[0] + "/") for n in names[1:]))
        self.assertEqual(names[1:], sorted(names[1:]))
        by_name = {m.name.split("/", 1)[-1]: m for m in members}
        for member in members:
            self.assertEqual((member.mtime, member.uid, member.gid, member.uname, member.gname),
                             (bundle.FIXED_TIME, 0, 0, "", ""))
        # Modes as they mean: programs and folders 0755, the rest 0644; the link a link.
        self.assertEqual(by_name["opendmt3-server"].mode, 0o755)
        self.assertEqual(by_name["lib/python/bin/python3.12"].mode, 0o755)
        self.assertEqual(by_name["README.txt"].mode, 0o644)
        self.assertEqual(by_name["lib/empty"].mode, 0o755)
        self.assertTrue(by_name["lib/python/bin/python3"].issym())
        self.assertEqual(by_name["lib/python/bin/python3"].linkname, "python3.12")
        # files.sha256 lists every file but itself and the link, sorted, as sha256sum writes it.
        listed = (one / "files.sha256").read_text().splitlines()
        self.assertEqual([line.split("  ", 1)[1] for line in listed],
                         ["README.txt", "lib/python/bin/python3.12", "opendmt3-server"])
        self.assertEqual(listed[0].split("  ")[0], hashlib.sha256(b"words\n").hexdigest())

    def test_the_templates_fill_every_mark(self):
        from opendmt3.server import standalone
        for key, target in bundle.TARGETS.items():
            name = bundle.name_of(V, key)
            values = {"VERSION": V, "SYSTEM": target.system, "NAME": name, "TARGET": key,
                      "QUARANTINE": bundle.QUARANTINE % name if key.startswith("macos-") else ""}
            readme = bundle.from_template(Path(ROOT, "packaging", "server", "README.txt"), values)
            program = bundle.from_template(Path(ROOT, "packaging", "server", "opendmt3-server.sh"), values)
            self.assertIn("openDMT3 server %s for %s" % (V, target.system), readme)
            # On macOS only, the words for a download a browser marked.
            self.assertEqual("xattr -dr com.apple.quarantine %s" % name in readme, key.startswith("macos-"))
            # The program names its folder to the server by the server's own variable, and runs the package's
            # Python isolated, with the server's command line.
            self.assertIn("%s=$here\n" % standalone.PACKAGE_ENV, program)
            self.assertIn('exec "$here/lib/python/bin/python3" -I -B -m opendmt3.server.standalone "$@"', program)
            self.assertEqual(bundle.PROGRAM, standalone.PROG)
        # A mark nothing fills stops the build.
        planted = self.tmp / "planted.txt"
        planted.write_text("openDMT3 @VERSION@ on @WHERE@\n")
        with self.assertRaises(ValueError):
            bundle.from_template(planted, {"VERSION": V})

    def test_the_scripts_parse(self):
        # The package's program and the one-line installer, read by the shell they run in (where there is one).
        if not shutil.which("sh"):
            self.skipTest("no sh here")
        import subprocess
        for script in ("opendmt3-server.sh", "install.sh"):
            done = subprocess.run(["sh", "-n", os.path.join(ROOT, "packaging", "server", script)],
                                  capture_output=True, text=True)
            self.assertEqual((done.returncode, done.stderr), (0, ""), script)

    def test_the_trees_files_are_the_servers_parts(self):
        listing = self.tmp / "listing"
        listing.write_bytes(b"\0".join(n.encode() for n in (
            "opendmt3/__init__.py", "opendmt3/server/standalone.py", "opendmt3/client/main.py",
            "opendmt3/client/assets/fonts/Saira-OFL.txt", "opendmt3/core/game.py", "LICENSE", "tests/x.py",
            "opendmt3/serverless.py")) + b"\0")
        self.assertEqual(bundle.tree_files(listing), [
            "LICENSE", "opendmt3/__init__.py", "opendmt3/client/assets/fonts/Saira-OFL.txt", "opendmt3/core/game.py",
            "opendmt3/server/standalone.py"])

    def test_the_windows_installer_runs_on_windows_powershell(self):
        # Windows PowerShell 5.1, which every Windows 10 and 11 has, reads none of PowerShell 7's newer syntax: no
        # pipeline chains, no ternary, no null-coalescing, outside comments and strings.
        script = Path(ROOT, "packaging", "server", "install.ps1").read_text(encoding="utf-8")
        code = "\n".join(re.sub(r"'[^']*'|\"[^\"]*\"", "''", line.split("#", 1)[0]) for line in script.splitlines())
        for newer in ("&&", "||", "??", "?.", " ? "):
            self.assertNotIn(newer, code)
        # Run through iex, everything is in one script block, so a failure ends the install and not the window.
        lines = [line for line in script.splitlines() if line and not line.startswith("#")]
        self.assertEqual((lines[0], lines[-1]), ("& {", "}"))

class DocVersionsTest(unittest.TestCase):
    def test_the_guides_name_the_code_s_version(self):
        version = doc_versions.code_version(Path(ROOT))
        self.assertEqual(doc_versions.stale(Path(ROOT), version), [])
        # The README's download is this version's installer, from this version's release.
        readme = Path(ROOT, "README.md").read_text(encoding="utf-8")
        self.assertIn("releases/download/v%s/opendmt3-launcher-%s-windows-x64-installer.exe" % (version, version), readme)

    def test_the_guides_name_only_files_a_release_has(self):
        # Every release file a page names by a version (this one, <version> or X.Y.Z) is one the release makes, so a
        # file renamed leaves no guide or download line under its old name.
        version = doc_versions.code_version(Path(ROOT))
        known = set(files.names(version))
        named = re.compile(r"opendmt3-[A-Za-z0-9.<>-]+?\.(?:tar\.gz|zip|exe|sh|ps1|tgz|txt)\b")
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
        # The instrument reads the pages: the guides name the server's packages, its installers, its Helm chart and
        # the sums.
        for name in ("opendmt3-server-%s-windows-x64.zip", "opendmt3-server-%s-linux-x64.tar.gz",
                     "opendmt3-server-%s-linux-installer.sh", "opendmt3-server-%s-windows-installer.ps1",
                     "opendmt3-server-%s-helm-chart.tgz", "opendmt3-%s-sha256sums.txt"):
            self.assertIn(name % version, seen)

    def test_another_version_is_found_and_written_over(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        (tmp / "opendmt3").mkdir()
        (tmp / "opendmt3" / "__init__.py").write_text('__version__ = "1.2.4"\n')
        (tmp / "docs").mkdir()
        (tmp / "docs" / "install.md").write_text(
            "curl -LO https://x/releases/download/v1.2.3/opendmt3-launcher-1.2.3-windows-x64-installer.exe\n"
            "tar -xzf opendmt3-server-1.2.3-linux-x64.tar.gz\ncd opendmt3-server-1.2.3-linux-x64\n"
            "opendmt3-server-1.2.3-helm-chart.tgz, opendmt3-1.2.3-sha256sums.txt and "
            "opendmt3-launcher-1.2.3-openal-sources.zip\nopendmt3-launcher-<version>-windows-x64-installer.exe stays\n")
        code, _, err = run(doc_versions, "--root", str(tmp))
        self.assertEqual(code, 1)
        # Each name's version: the address and the installer, the package and its folder, the chart, the sums, the
        # sources.
        self.assertEqual(err.count("names 1.2.3"), 7)
        run(doc_versions, "--root", str(tmp), "--write")
        text = (tmp / "docs" / "install.md").read_text()
        # The version alone changed: the part after it stays (-windows-x64), and a pattern without one stays.
        self.assertIn("v1.2.4/opendmt3-launcher-1.2.4-windows-x64-installer.exe", text)
        self.assertIn("opendmt3-server-1.2.4-linux-x64.tar.gz\ncd opendmt3-server-1.2.4-linux-x64\n", text)
        self.assertIn("opendmt3-server-1.2.4-helm-chart.tgz, opendmt3-1.2.4-sha256sums.txt and "
                      "opendmt3-launcher-1.2.4-openal-sources.zip", text)
        self.assertIn("opendmt3-launcher-<version>-windows-x64-installer.exe stays", text)
        self.assertEqual(run(doc_versions, "--root", str(tmp))[0], 0)


if __name__ == "__main__":
    unittest.main()
