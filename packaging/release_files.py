"""The files of a release, gathered into one folder with their SHA-256 sums, and a table of them for the maintainer.

    python3 packaging/release_files.py VERSION BUILD_DIR OUT_DIR [--server DIR]

Run by packaging/release.sh after packaging/windows/build.sh has built into BUILD_DIR, and the server's packages and
chart into the folder --server names. Into OUT_DIR it puts, and prints the Markdown table of (FILES.md beside them):

  opendmt3-launcher-<version>-windows-x64-installer.exe   the launcher's installer, for players (build.sh names it so)
  opendmt3-server-<version>-windows-x64.zip               the server on Windows, without Docker or Python (from
                                                          --server: packaging/windows/server.sh built it)
  opendmt3-server-<version>-linux-x64.tar.gz,             the server on Linux and on macOS, on either processor,
  opendmt3-server-<version>-linux-arm64.tar.gz,           without Docker or Python (from --server: packaging/server/
  opendmt3-server-<version>-macos-x64.tar.gz,             bundle.sh built them)
  opendmt3-server-<version>-macos-arm64.tar.gz
  opendmt3-server-<version>-linux-installer.sh,           the one-line install on Linux and on macOS (one script,
  opendmt3-server-<version>-macos-installer.sh            packaging/server/install.sh, with the version put in), which
                                                          takes the package for the machine it runs on
  opendmt3-server-<version>-windows-installer.ps1         the one-line install on Windows (packaging/server/
                                                          install.ps1, with the version put in), which takes the
                                                          Windows package
  opendmt3-server-<version>-helm-chart.tgz                the Helm chart (from --server: helm package made it as
                                                          opendmt3-<version>.tgz, by the chart's own name)
  opendmt3-launcher-<version>-openal-sources.zip          the source archives of OpenAL Soft and DSOAL, the two LGPL
                                                          libraries the launcher brings, as their licence asks of
                                                          whoever hands them on
  openDMT3-<version>-full.nupkg, -delta.nupkg, .sig,      the launcher's update files, under the names Velopack and the
  releases.win.json                                       launchers already installed read
  opendmt3-<version>-sha256sums.txt                       every file above's SHA-256

Every file of a release is named in lowercase: the tool, its part and the version, then the system and processor it
runs on or what it holds (opendmt3-server-<version>-linux-arm64.tar.gz, opendmt3-server-<version>-helm-chart.tgz).
The update files are the exception: an installed launcher takes an update only from a feed that names its package
exactly openDMT3-<version>-full.nupkg (client/updates.py, offered, as every launcher from 0.1.0 on checks it), and
the package's signature is made over that name; Velopack's package ID is the launcher's identity on the PC (its
folder in %LocalAppData%), and releases.win.json is the name Velopack reads a GitHub release's feed by. Renamed,
every launcher installed so far would stop updating.

Nothing goes in that nobody needs: vpk's RELEASES (the feed in the form of Velopack's predecessor, which the Velopack
the launchers carry never reads: a server's /updates/ hands out none, and its launchers update), its portable zip and
its assets.win.json stay out. The server's image is no release file: .github/workflows/release.yml publishes it to
ghcr.io/kanggu12/opendmt3-server for amd64 and arm64 on the tag, which ./dmt3 (from a clone of the repository, or the
release's source archive) and the Helm chart run.

The standard library only: it runs on the release machine's own Python, before anything is installed.
"""

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

# The repository: this file is in packaging/.
ROOT = Path(__file__).resolve().parent.parent
# Velopack's package ID, which the update files carry in their names (packaging/windows/build.sh, vpk --packId).
PACKAGE_ID = "openDMT3"

# The names this script makes itself, with the version put in (the rest come from the build or --server).
SOURCES_ZIP = "opendmt3-launcher-{v}-openal-sources.zip"
SUMS = "opendmt3-{v}-sha256sums.txt"
# The server's packages for Linux and macOS, one for each system and processor (packaging/server/bundle.py names
# them so), in the order the table lists them.
UNIX_TARGETS = ("linux-x64", "linux-arm64", "macos-x64", "macos-arm64")
UNIX_PACKAGE = "opendmt3-server-{v}-%s.tar.gz"
# FILES.md's table: each file, what it is, for whom. Names are made from these with the version put in.
ROLES = [
    ("opendmt3-launcher-{v}-windows-x64-installer.exe", "The launcher's installer for Windows (x64); runs under Wine "
     "on Linux too", "Players"),
    ("opendmt3-server-{v}-windows-x64.zip", "The server on a Windows PC of its own, without Docker or Python, with "
     "the launcher's installer to hand out", "Server owners on Windows"),
    (UNIX_PACKAGE % "linux-x64", "The server on a Linux machine (x64), without Docker or Python, with the launcher's "
     "installer to hand out", "Server owners on Linux"),
    (UNIX_PACKAGE % "linux-arm64", "The same on a Linux machine on arm64", "Server owners on Linux"),
    (UNIX_PACKAGE % "macos-x64", "The same on a Mac with an Intel processor", "Server owners on macOS"),
    (UNIX_PACKAGE % "macos-arm64", "The same on a Mac with Apple silicon", "Server owners on macOS"),
    ("opendmt3-server-{v}-linux-installer.sh", "The one-line install of the server on Linux: the package for the "
     "machine, the command on PATH", "Server owners on Linux"),
    ("opendmt3-server-{v}-macos-installer.sh", "The same install on macOS", "Server owners on macOS"),
    ("opendmt3-server-{v}-windows-installer.ps1", "The one-line install of the server on Windows, for the user, with "
     "the command on PATH", "Server owners on Windows"),
    ("opendmt3-server-{v}-helm-chart.tgz", "The Helm chart, running the published image",
     "Server owners on Kubernetes"),
    (SOURCES_ZIP, "The source archives of OpenAL Soft and DSOAL, the two LGPL libraries the launcher brings for its "
     "sound mixer, as their licence asks", "Anyone who wants the source"),
    ("openDMT3-{v}-full.nupkg", "The launcher's update package (Velopack's name for it, read by installed "
     "launchers)", "Installed launchers"),
    ("openDMT3-{v}-delta.nupkg", "The launcher's update from the previous release, only what changed", "Installed "
     "launchers"),
    ("openDMT3-{v}-full.nupkg.sig", "The project's signature of the update package", "Installed launchers"),
    ("openDMT3-{v}-delta.nupkg.sig", "The project's signature of the delta package", "Installed launchers"),
    ("releases.win.json", "The update feed installed launchers read", "Installed launchers"),
    (SUMS, "The SHA-256 of every file above (`sha256sum -c`)", "Anyone checking a download"),
]
# The server's files built before this script runs (release.sh: packaging/windows/server.sh, packaging/server/
# bundle.sh, helm package), each by the name in the folder --server names and its name in the release; without
# --server none are taken (a test's run). Helm names a chart's package by the chart's own name (opendmt3); the release
# names it as the server's chart.
SERVER_BUILT = {"opendmt3-server-{v}-windows-x64.zip": "opendmt3-server-{v}-windows-x64.zip",
                "opendmt3-{v}.tgz": "opendmt3-server-{v}-helm-chart.tgz"}
SERVER_BUILT.update({UNIX_PACKAGE % key: UNIX_PACKAGE % key for key in UNIX_TARGETS})
# The one-line installers: each script of the tree, with the version put in, under the names of the systems it
# installs on (install.sh is one script for Linux and macOS: it takes the package for the machine it runs on).
INSTALLERS = {"packaging/server/install.sh": ("opendmt3-server-{v}-linux-installer.sh",
                                              "opendmt3-server-{v}-macos-installer.sh"),
              "packaging/server/install.ps1": ("opendmt3-server-{v}-windows-installer.ps1",)}
# The update files, whose names stay Velopack's (the module's docstring says why).
UPDATE_FILES = {"openDMT3-{v}-full.nupkg", "openDMT3-{v}-delta.nupkg", "openDMT3-{v}-full.nupkg.sig",
                "openDMT3-{v}-delta.nupkg.sig", "releases.win.json"}
# Files a release may lack: a delta needs a previous release, and a rehearsal without the key has no signatures.
OPTIONAL = {"openDMT3-{v}-delta.nupkg", "openDMT3-{v}-delta.nupkg.sig", "openDMT3-{v}-full.nupkg.sig"}
# Every file a zip is given the same time, so the same tree makes the same zip (zip's earliest time is 1980).
FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def _entry(zf, name, data, mode):
    """One file into the zip with its Unix mode, at the fixed time."""
    info = zipfile.ZipInfo(name, FIXED_TIME)
    # 3: made on Unix, so unzip reads the mode in the upper half of external_attr.
    info.create_system = 3
    info.external_attr = (0o100000 | mode) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    zf.writestr(info, data)


def openal_sources_zip(build, version, out):
    """opendmt3-launcher-<version>-openal-sources.zip in `out`: the two archives native/openal/build.sh built the
    launcher's DSOAL and OpenAL Soft from, with their SHA256SUMS, each checked against it first, under one folder of
    the zip's name. Returns its path."""
    sources = Path(build) / "openal" / "sources"
    sums = (sources / "SHA256SUMS").read_text(encoding="utf-8")
    name = SOURCES_ZIP.format(v=version)
    # The folder unzip makes is the zip's name without .zip.
    top = name[:-len(".zip")]
    path = Path(out) / name
    with zipfile.ZipFile(path, "w") as zf:
        for line in sums.splitlines():
            digest, name = line.split(None, 1)
            data = (sources / name).read_bytes()
            if hashlib.sha256(data).hexdigest() != digest:
                # Not the archive the libraries were built from: the release would hand on other sources.
                raise ValueError("%s is not the archive SHA256SUMS names" % name)
            _entry(zf, "%s/%s" % (top, name), data, 0o644)
        _entry(zf, "%s/SHA256SUMS" % top, sums.encode("utf-8"), 0o644)
    return path


def names(version):
    """Every name a release's files may have, in the table's order, with the version put in."""
    return [pattern.format(v=version) for pattern, _, _ in ROLES]


def check_names(version, present):
    """What is wrong with the release's file names, as sentences: a name not in the table, one in mixed or upper case
    that is not an update file, one without the version that is not a feed file."""
    problems = []
    known = names(version)
    updates = {p.format(v=version) for p in UPDATE_FILES}
    for name in present:
        if name not in known:
            problems.append("%s is not one of a release's files" % name)
        elif name not in updates and name != name.lower():
            problems.append("%s is not in lowercase" % name)
        elif name not in updates and version not in name:
            problems.append("%s does not carry the version" % name)
    return problems


def table(version, present):
    """A table of the files there are, what each is and for whom: FILES.md, for the maintainer (the notes carry none)."""
    rows = ["| File | What it is | For |", "| :--- | :--- | :--- |"]
    for pattern, what, who in ROLES:
        name = pattern.format(v=version)
        if name in present:
            rows.append("| `%s` | %s | %s |" % (name, what, who))
    # Why some names differ from the rest, said under the table: a reader sees mixed letters and asks.
    note = ("\nThe launcher's update files keep Velopack's names (`openDMT3-<version>-full.nupkg`, "
            "`releases.win.json`): every launcher installed so far looks for them letter for letter.\n")
    # A heading of the changelog section's level: the table opens the notes, the section's parts follow it.
    return "### Files\n\n" + "\n".join(rows) + "\n" + note


def gather(root, version, build, out, server=None):
    """Every file of the release into `out`, with the SHA-256 sums; returns the names there, in the table's order.
    server: the folder holding the server's files built before (SERVER_BUILT); each is then needed."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.iterdir():
        # A folder made again from scratch: an earlier run's file is no file of this release.
        if old.is_file():
            old.unlink()
    releases = Path(build) / "releases"
    for name in names(version):
        source = releases / name
        if source.is_file():
            # The installer and the update files, as build.sh left them.
            (out / name).write_bytes(source.read_bytes())
    openal_sources_zip(build, version, out)
    if server is not None:
        for built, name in SERVER_BUILT.items():
            source = Path(server) / built.format(v=version)
            if source.is_file():
                (out / name.format(v=version)).write_bytes(source.read_bytes())
    for source, names_ in INSTALLERS.items():
        script = (Path(root) / source).read_text(encoding="utf-8").replace("@VERSION@", version)
        for name in names_:
            # Executable as a file too (sh reads it from the pipe either way, and PowerShell from iex).
            path = out / name.format(v=version)
            path.write_text(script, encoding="utf-8", newline="\n")
            path.chmod(0o755)
    present = [n for n in names(version) if (out / n).is_file()]
    # The server's built files are needed when their folder was given, else left out.
    optional = {p.format(v=version) for p in OPTIONAL} | (
        set() if server is not None else {n.format(v=version) for n in SERVER_BUILT.values()})
    # The sums are made last, below, over the rest.
    sums = SUMS.format(v=version)
    missing = [n for n in names(version) if n not in present and n != sums and n not in optional]
    if missing:
        raise ValueError("missing: " + ", ".join(missing))
    # Over every other file, in sha256sum's own form, so `sha256sum -c` reads it.
    lines = ["%s  %s" % (hashlib.sha256((out / n).read_bytes()).hexdigest(), n) for n in present]
    (out / sums).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return present + [sums]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="the release's version, 1.2.3 (a v before it is taken off)")
    parser.add_argument("build", type=Path, help="the folder packaging/windows/build.sh built into")
    parser.add_argument("out", type=Path, help="the folder the release's files go into")
    parser.add_argument("--root", type=Path, default=ROOT, help="the tree the installers' scripts are taken from")
    parser.add_argument("--server", type=Path, help="the folder of the server's files built before (its packages for "
                                                    "Windows, Linux and macOS, the packaged Helm chart)")
    args = parser.parse_args(argv)
    version = args.version[1:] if args.version.startswith("v") else args.version
    try:
        present = gather(args.root, version, args.build, args.out, args.server)
    except (OSError, ValueError) as e:
        print("the release's files: %s" % e, file=sys.stderr)
        return 1
    problems = check_names(version, present)
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    files_md = table(version, present)
    # Beside the files (release.sh puts it at the notes' end), and on standard output for a look.
    (args.out.parent / "FILES.md").write_text(files_md, encoding="utf-8")
    print(files_md, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
