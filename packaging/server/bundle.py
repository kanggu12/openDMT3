"""The server's packages for Linux and macOS: opendmt3-server-<version>-<system>-<processor>.tar.gz, each one folder
that runs the server on that system and processor with nothing else installed (no Python, no Docker), as the Windows
server package does on Windows.

    python3 packaging/server/bundle.py fetch CACHE [TARGET ...]
        (the build machine's own Python, with the network: every pinned file into CACHE, each checked by its SHA-256)
    PYTHON -I packaging/server/bundle.py build CACHE FILES OUT [--installer FILE] [TARGET ...]
        (the pinned Python for Linux x64 itself, in a container with no network: packaging/server/bundle.sh)

TARGET is linux-x64, linux-arm64, macos-x64 or macos-arm64; with none, all four. Each package is put together on
Linux from pinned files alone, the same way for every system (as jukecord's programs are), and run on its own system
by CI (.github/workflows/ci.yml, the package job):

  opendmt3-server                the program: a shell script that runs the package's Python with the server's command
                                 line (opendmt3/server/standalone.py), every command the Windows package's
                                 opendmt3-server.exe has; it names the package's folder to the server
                                 (OPENDMT3_SERVER_PACKAGE), whose data folder is then beside it, as in the Windows
                                 package
  README.txt, LICENSE.txt        how to start it, and openDMT3's licence
  installer/                     the launcher's installer of the same release, for the site's Download page (when
                                 --installer names it: packaging/release.sh gives the one it just built)
  licenses/                      NOTICES.txt, which says what each part is and which text is its licence, and the texts
  lib/python/                    python-build-standalone's CPython for that system (the release the Windows build
                                 pins), without what the server never runs (Tk, the tests' and tools' modules, pip, C
                                 headers), with the site's libraries in its site-packages at the versions the server's
                                 image runs, each wheel checked by its SHA-256
  lib/opendmt3/, lib/LICENSE     the server's code (core, server, the fonts the site serves), from the files git tracks
  lib/7-zip/                     the official 7-Zip for that system, for the client data's archives, with its licence
  files.sha256                   every file above with its SHA-256, which opendmt3-server repair checks the folder by

Every byte comes from the tree and the pinned files: the same tree makes the same packages (sorted members, one time,
no owner, a gzip header with no time or name), whichever machine builds them. The standard library only.
"""

import argparse
import gzip
import hashlib
import io
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

# The repository: this file is in packaging/server/.
ROOT = Path(__file__).resolve().parent.parent.parent
# python-build-standalone's release and the CPython it builds: the release packaging/windows/build.sh pins for the
# launcher's Windows Python, so the server runs the same Python on every system.
PYTHON_RELEASE, PYTHON_VERSION = "20261026", "3.12.16"
PYTHON_URL = "https://github.com/astral-sh/python-build-standalone/releases/download/%s/%s"
# The official 7-Zip's releases (the release the server's image, the launcher and the tests bring).
SEVENZIP_URL = "https://www.7-zip.org/a/%s"
# The site's libraries, each at the version the server's image runs (packaging/docker/Dockerfile pins the first five;
# the rest are what they need, as pip took them for the image). The ones with no compiled part are one wheel for every
# system: (its file on PyPI, that file's SHA-256).
PYPI = "https://files.pythonhosted.org/packages/"
WHEELS = [
    (PYPI + "ce/fd/901cfa59aaa5b30a99e16876f11abe38b59a1a2c51ffb3d7142bb6089069/starlette-0.47.3-py3-none-any.whl",
     "89c0778ca62a76b826101e7c709e70680a1699ca7da6b44d38eb0a7e61fe4b51"),
    (PYPI + "62/a1/3d680cbfd5f4b8f15abc1d571870c5fc3e594bb582bc3b64ea099db13e56/jinja2-3.1.6-py3-none-any.whl",
     "85ece4451f492d0c13c5dd7c13a64681a86afae63a5f347908daf103ce6d2f67"),
    (PYPI + "d2/e2/dc81b1bd1dcfe91735810265e9d26bc8ec5da45b4c0f6237e286819194c3/uvicorn-0.35.0-py3-none-any.whl",
     "197535216b25ff9b785e29a0b79199f55222193d47f820816e7da751e9bc8d4a"),
    (PYPI + "45/58/38b5afbc1a800eeea951b9285d3912613f2603bdf897a4ab0f4bd7f405fc/"
     "python_multipart-0.0.20-py3-none-any.whl", "8a62d3a8335e06589fe01f2a3e178cdcc632f3fbe0d492ad9ee0ec35aab1f104"),
    (PYPI + "a9/16/7757fb84c819accc7d7e9af5291b261e4abb8627ee040f99e7d35ef2457a/anyio-4.16.0-py3-none-any.whl",
     "c66ae634e0b8228396b801741beb3294326d4b6102f7bba4041c0dfb58c29026"),
    (PYPI + "31/7d/164b7ffc8624fe9efb4221bf9af485d5c1e41b9ae118045d2b6dc5457d8b/click-8.5.1-py3-none-any.whl",
     "8bb5376d2006950386f8c6427613334a2acadc5f559cb80e638d00b4df957e37"),
    (PYPI + "04/4b/29cac41a4d98d144bf5f6d33995617b185d14b22401f75ca86f384e87ff1/h11-0.16.0-py3-none-any.whl",
     "63cf8bbe7522de3bf65932fda1d9c2772064ffb3dae62d55932da54b31cb6c86"),
    (PYPI + "58/a2/bb081bab032533a855d44de1d56f8e8426114ff1ba5d1f07a438a0a654f8/idna-3.20-py3-none-any.whl",
     "ab7ae7122974553370f0bdb919e1a960b2cd1bc1ef0276416d896db81c14582c"),
    (PYPI + "49/d3/b8441a820a491ddfc024b0b0cf0393375b75ea13866d9c66727e54c2fc80/"
     "typing_extensions-4.16.0-py3-none-any.whl", "481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8"),
]
# The libraries' licence texts the packages' Python does not carry (its modules' libraries), kept unchanged in the
# tree: the launcher's build keeps most (packaging/windows/licenses), the rest are kept here (licenses/README.md says
# where each was taken from). Each: (its name in NOTICES.txt, what it does there, its licence, its kept file).
KEPT_WINDOWS = ROOT / "packaging" / "windows" / "licenses"
KEPT_HERE = ROOT / "packaging" / "server" / "licenses"
LIBRARIES = {
    "openssl": ("OpenSSL 3", "Python's ssl and hashlib", "Apache License 2.0", KEPT_WINDOWS / "OpenSSL-LICENSE.txt"),
    "sqlite": ("SQLite", "Python's sqlite3, the server's database", "Public domain",
               KEPT_WINDOWS / "SQLite-LICENSE.txt"),
    "libffi": ("libffi", "Python's ctypes", "MIT", KEPT_WINDOWS / "libffi-LICENSE.txt"),
    "expat": ("Expat", "Python's XML readers", "MIT", KEPT_WINDOWS / "Expat-LICENSE.txt"),
    "mpdecimal": ("mpdecimal", "Python's decimal", "BSD 2-Clause", KEPT_WINDOWS / "mpdecimal-LICENSE.txt"),
    "liblzma": ("XZ Utils' liblzma", "Python's lzma", "BSD Zero Clause", KEPT_WINDOWS / "liblzma-LICENSE.txt"),
    "bzip2": ("bzip2", "Python's bz2", "bzip2-1.0.6", KEPT_HERE / "bzip2-LICENSE.txt"),
    "libuuid": ("util-linux's libuuid", "Python's uuid", "BSD 3-Clause", KEPT_HERE / "libuuid-LICENSE.txt"),
    "zlib": ("zlib", "Python's zlib", "zlib License", KEPT_WINDOWS / "zlib-LICENSE.txt"),
    "zlib-ng": ("zlib-ng", "Python's zlib", "zlib License", KEPT_HERE / "zlib-ng-LICENSE.txt"),
    "libedit": ("libedit", "Python's readline", "BSD 3-Clause", KEPT_HERE / "libedit-LICENSE.txt"),
    "ncurses": ("ncurses", "Python's curses and readline", "X11 (MIT)", KEPT_HERE / "ncurses-LICENSE.txt"),
}


class Target:
    """One system and processor a package is made for, with the pinned files it is made from."""

    def __init__(self, triple, python_sha256, sevenzip, sevenzip_sha256, wheels, libraries, system):
        # python-build-standalone's name for it, and its stripped install's SHA-256.
        self.triple, self.python_sha256 = triple, python_sha256
        # The official 7-Zip's archive for it, and that archive's SHA-256.
        self.sevenzip, self.sevenzip_sha256 = sevenzip, sevenzip_sha256
        # The wheels with a compiled part, built for it: (their file on PyPI, its SHA-256).
        self.wheels = wheels
        # The libraries its Python carries inside it, by LIBRARIES' keys (from that release's PYTHON.json: on macOS
        # zlib, libedit and ncurses are the system's own, which the package does not carry).
        self.libraries = libraries
        # The system's name as README.txt says it.
        self.system = system

    @property
    def python(self):
        """The stripped install of python-build-standalone for this target: its file name."""
        return "cpython-%s+%s-%s-install_only_stripped.tar.gz" % (PYTHON_VERSION, PYTHON_RELEASE, self.triple)


# The libraries every target's Python carries, and those only Linux's does.
EVERYWHERE = ["openssl", "sqlite", "libffi", "expat", "mpdecimal", "liblzma", "bzip2", "libuuid"]
LINUX_ONLY = ["zlib", "zlib-ng", "libedit", "ncurses"]
TARGETS = {
    "linux-x64": Target(
        "x86_64-unknown-linux-gnu", "ce4f6d0a6cfdb3bed6e44c2f9affd85943c76a42e25ad3a259002f31d6fb8a20",
        "7z2501-linux-x64.tar.xz", "4ca3b7c6f2f67866b92622818b58233dc70367be2f36b498eb0bdeaaa44b53f4",
        [(PYPI + "4f/a7/aeedb5140afa41fc74c225e9184ab96723a6e873b6ee1c9fede7283456d8/markupsafe-3.0.4-cp312-cp312-"
          "manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl",
          "8e124f974786f831d6043728e38296969d3579db8896fe004682f5758e613581"),
         (PYPI + "8d/33/e9200d2bd7ba00dc3ddb78df1198a6e80d7669cce6c2bdbeb2530a74ec58/pillow-11.3.0-cp312-cp312-"
          "manylinux2014_x86_64.manylinux_2_17_x86_64.whl",
          "67172f2944ebba3d4a7b54f2e95c786a3a50c21b88456329314caaa28cda70f6")],
        EVERYWHERE + LINUX_ONLY, "Linux (x64)"),
    "linux-arm64": Target(
        "aarch64-unknown-linux-gnu", "bb4b6392670c5d3f93876996fcaa19858a4a413a0c7720144c18b0d6f1f0db2d",
        "7z2501-linux-arm64.tar.xz", "39c5140f02ce4436599303c59a149f654cb1bbc47cdc105a942120d747ae040d",
        [(PYPI + "0d/f2/8f18e0b806eb13c1f8d07d917a720831ead54253a6dec011fbc78098a6f8/markupsafe-3.0.4-cp312-cp312-"
          "manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl",
          "6a45c3d514f2436064db00d7fc8778d888f0236ebfed649b53d13a59e69ad51b"),
         (PYPI + "8e/1e/b9e12bbe6e4c2220effebc09ea0923a07a6da1e1f1bfbc8d7d29a01ce32b/pillow-11.3.0-cp312-cp312-"
          "manylinux2014_aarch64.manylinux_2_17_aarch64.whl",
          "eb76541cba2f958032d79d143b98a3a6b3ea87f0959bbe256c0b5e416599fd5d")],
        EVERYWHERE + LINUX_ONLY, "Linux (arm64)"),
    "macos-x64": Target(
        "x86_64-apple-darwin", "37c38fda76fec1fbf310adcbafb7f0d96af13b5511bf8ea954c3aa8eec185734",
        "7z2501-mac.tar.xz", "26aa75bc262bb10bf0805617b95569c3035c2c590a99f7db55c7e9607b2685e0",
        [(PYPI + "81/09/4c59d56b8461ae8eb0d8ba34bb25b7e618547044679d58a82ef9b2479fc1/markupsafe-3.0.4-cp312-cp312-"
          "macosx_10_13_x86_64.whl", "61631e08084be9e21a8967ec3139c7616ed7c5e9368e05c86d1b39562c8a57b6"),
         (PYPI + "40/fe/1bc9b3ee13f68487a99ac9529968035cca2f0a51ec36892060edcc51d06a/pillow-11.3.0-cp312-cp312-"
          "macosx_10_13_x86_64.whl", "fdae223722da47b024b867c1ea0be64e0df702c5e0a60e27daad39bf960dd1e4")],
        EVERYWHERE, "macOS (Intel, x64)"),
    "macos-arm64": Target(
        "aarch64-apple-darwin", "353d5f1b4fd2715e7053f12f068435d5bbad16b91e057006b5d01e0925709a7e",
        "7z2501-mac.tar.xz", "26aa75bc262bb10bf0805617b95569c3035c2c590a99f7db55c7e9607b2685e0",
        [(PYPI + "a2/f0/d6613774d86fbf6d145751d43c59875e47a6f9f17daee0aef173bd36d90e/markupsafe-3.0.4-cp312-cp312-"
          "macosx_11_0_arm64.whl", "0930db9bdc62d22944e10b066448bb65dc9abe9112880c7cab8da54db4284d5f"),
         (PYPI + "2c/32/7e2ac19b5713657384cec55f89065fb306b06af008cfd87e572035b27119/pillow-11.3.0-cp312-cp312-"
          "macosx_11_0_arm64.whl", "921bd305b10e82b4d1f5e802b6850677f965d8394203d182f078873851dada69")],
        EVERYWHERE, "macOS (Apple silicon, arm64)"),
}
# What of the Python is left out, as paths below lib/python (a name ending in / is a folder, * matches within one name):
# Tk and Tcl (no window is drawn) with the modules that use them, dbm and crypt (never used, and crypt is the system's
# libcrypt), the tools' modules and commands (IDLE, 2to3, pydoc's pages, pip and the wheel it installs from), the C
# headers, static library and build settings (nothing is compiled against it), the terminal database and the manual
# pages, and the shared libpython (for programs that embed Python: this Python's own program has it built in).
LEFT_OUT = [
    "include/", "share/", "lib/pkgconfig/", "lib/tcl9.0/", "lib/tk9.0/", "lib/tcl9/", "lib/itcl*/", "lib/thread*/",
    "lib/libtcl*", "lib/libpython3*", "bin/idle*", "bin/2to3*", "bin/pydoc*", "bin/pip*", "bin/python*-config",
    "lib/python3.12/config-3.12-*/", "lib/python3.12/lib-dynload/_tkinter.*", "lib/python3.12/lib-dynload/_dbm.*",
    "lib/python3.12/lib-dynload/_crypt.*", "lib/python3.12/tkinter/", "lib/python3.12/idlelib/",
    "lib/python3.12/turtledemo/", "lib/python3.12/turtle.py", "lib/python3.12/ensurepip/",
    "lib/python3.12/lib2to3/", "lib/python3.12/pydoc_data/", "lib/python3.12/site-packages/pip/",
    "lib/python3.12/site-packages/pip-*.dist-info/",
]
# The server's files from the tree, as paths git tracks: the package's top files, core and server, the fonts the site
# serves (kept with the launcher's, one copy for both), and openDMT3's licence beside them (the site's Licenses page
# reads it there). bundle.sh lists them, so the build needs no git.
FROM_TREE = ["opendmt3/__init__.py", "opendmt3/__main__.py", "opendmt3/core", "opendmt3/server",
             "opendmt3/client/assets/fonts", "LICENSE"]
# Where things go in the package's folder.
PROGRAM, README, NOTICES, MANIFEST = "opendmt3-server", "README.txt", "NOTICES.txt", "files.sha256"
# Every member of a package carries this time (1980-01-01, as the release's zips carry): the same tree makes the same
# archive, whenever it is built.
FIXED_TIME = 315532800
# README.txt's words for macOS alone, in the words the project's other packages use (jukecord's guide): a browser's
# download carries a mark that keeps the programs from starting; curl's carries none.
QUARANTINE = ("\nOn macOS\n--------\n\nDownloaded with a browser, macOS keeps the programs in the folder from "
              "starting until they are let\nthrough: xattr -dr com.apple.quarantine %s (in the folder that holds it). "
              "curl, as the one-line\ninstall uses it, leaves no such mark.\n")
# The site-packages folder below lib/python, where the libraries and the path file go.
SITE = "lib/python3.12/site-packages"
# The path file there: the folder holding opendmt3/ (lib/), as a path from site-packages (site.py reads one path a
# line, relative to the file's own folder), so the package's Python imports the server's code with -I.
PATH_FILE = ("opendmt3-server.pth", "../../../..\n")


def name_of(version, target):
    """The package's name (its file without .tar.gz, and its one folder): opendmt3-server-1.2.3-linux-x64."""
    return "opendmt3-server-%s-%s" % (version, target)


def sha256_of(path):
    """A file's SHA-256 in lower-case hex, read a megabyte at a time."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for piece in iter(lambda: f.read(1 << 20), b""):
            digest.update(piece)
    return digest.hexdigest()


def inputs(targets):
    """Every pinned file the targets are made from, once each: [(file name in the cache, address, SHA-256)]."""
    found = {}
    for key in targets:
        target = TARGETS[key]
        found[target.python] = (PYTHON_URL % (PYTHON_RELEASE, urllib.parse.quote(target.python)), target.python_sha256)
        found[target.sevenzip] = (SEVENZIP_URL % target.sevenzip, target.sevenzip_sha256)
        for url, sha in WHEELS + target.wheels:
            found[url.rsplit("/", 1)[1]] = (url, sha)
    # The builder's own Python (linux-x64's): bundle.sh runs the build with it, whatever the targets.
    builder = TARGETS["linux-x64"]
    found[builder.python] = (PYTHON_URL % (PYTHON_RELEASE, urllib.parse.quote(builder.python)), builder.python_sha256)
    return [(name, url, sha) for name, (url, sha) in sorted(found.items())]


def fetch(cache, targets):
    """Every pinned file into the cache: one there already with its SHA-256 is kept, any other fetched again and
    checked, so a file that is not the pinned one never reaches a package. Then the builder's Python unpacked in the
    cache's builder/ folder, for bundle.sh. Returns the number fetched."""
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    fetched = 0
    for name, url, sha in inputs(targets):
        path = cache / name
        if path.is_file() and sha256_of(path) == sha:
            # Kept from an earlier run, the very file pinned.
            continue
        # Written beside its place, then renamed: a download cut short is never taken for the file.
        part = cache / (name + ".part")
        # GitHub's releases and PyPI's files, by HTTPS only (urllib follows their redirects within HTTPS).
        with urllib.request.urlopen(url, timeout=120) as answer, open(part, "wb") as out:
            shutil.copyfileobj(answer, out, 1 << 20)
        got = sha256_of(part)
        if got != sha:
            part.unlink()
            raise ValueError("%s is not the file pinned (SHA-256 %s, pinned %s)" % (url, got, sha))
        os.replace(part, path)
        fetched += 1
    # The builder's Python, unpacked once a release (its folder named for it, so a new pin unpacks the new one), as a
    # package's is: what the packages leave out it needs no more than they do.
    builder = cache / ("builder-" + PYTHON_RELEASE)
    if not (builder / "python" / "bin" / "python3").is_file():
        shutil.rmtree(builder, ignore_errors=True)
        builder.mkdir()
        unpack_python(cache, TARGETS["linux-x64"], builder)
    return fetched


def left_out(rel):
    """True when a path below lib/python is one LEFT_OUT names (or inside one of its folders)."""
    from fnmatch import fnmatchcase
    for pattern in LEFT_OUT:
        if pattern.endswith("/"):
            # A folder: the path is it, or inside it (each part matched against the pattern's parts).
            parts, want = rel.split("/"), pattern.rstrip("/").split("/")
            if len(parts) >= len(want) and all(fnmatchcase(p, w) for p, w in zip(parts, want)):
                return True
        elif fnmatchcase(rel, pattern):
            return True
    return False


def unpack_python(cache, target, lib):
    """The target's Python into lib/python, without what LEFT_OUT names: members as the archive has them (its links,
    which point within it, kept as links), checked to stay inside the folder."""
    with tarfile.open(Path(cache) / target.python) as archive:
        members = []
        for member in archive.getmembers():
            rel = member.name
            if not rel.startswith("python/") or rel == "python/":
                # Only the install's own folder (the top folder itself is made below).
                continue
            if left_out(rel[len("python/"):]):
                continue
            members.append(member)
        # The data filter where this Python has it (3.12 does): no member or link leaving the folder, no device.
        archive.extractall(lib, members=members, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
    # What LEFT_OUT names must be gone; a pin to a release that lays out its files otherwise would leave it in.
    python = lib / "python"
    if not (python / "bin" / "python3").exists() or not (python / SITE).is_dir():
        raise ValueError("%s has no bin/python3 or %s" % (target.python, SITE))


def install_wheel(path, site):
    """A wheel's files into site-packages as pip lays them out (a wheel is a zip of them): its .data/purelib and
    .data/platlib parts at the top too; it brings no scripts, headers or data (none of the pinned ones does). Returns
    its .dist-info folder's name."""
    dist_info = None
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            name = info.filename
            if name.endswith("/"):
                # Folders are made for their files.
                continue
            parts = PurePosixPath(name).parts
            if ".." in parts or name.startswith("/"):
                raise ValueError("%s holds a path outside its folder: %s" % (path.name, name))
            if parts[0].endswith(".data"):
                if len(parts) < 3 or parts[1] not in ("purelib", "platlib"):
                    # Scripts, headers or data files: a wheel the server's packages are not made with.
                    raise ValueError("%s brings %s, which the package does not take" % (path.name, name))
                parts = parts[2:]
            if parts[0].endswith(".dist-info"):
                dist_info = parts[0]
            target = site.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
            # The executable bit as the wheel gives it (a compiled library may carry one), the rest 0644.
            target.chmod(0o755 if (info.external_attr >> 16) & 0o111 else 0o644)
    if dist_info is None:
        raise ValueError("%s has no .dist-info folder" % path.name)
    return dist_info


def dist_licences(site, dist_info):
    """A library's name, version, licence and licence files, from its own .dist-info: (name, version, licence,
    [paths of its licence files])."""
    from email.parser import Parser
    folder = site / dist_info
    meta = Parser().parsestr((folder / "METADATA").read_text(encoding="utf-8"))
    # The licence as the metadata says it: its SPDX expression first (PEP 639).
    licence = (meta.get("License-Expression") or "").strip()
    field = (meta.get("License") or "").strip()
    if not licence and field and "\n" not in field and len(field) <= 80:
        # Else the License field, when it names the licence rather than holding its whole text.
        licence = field
    if not licence:
        # Else the classifiers' names for it.
        licence = ", ".join(c.split("::")[-1].strip() for c in meta.get_all("Classifier") or []
                            if c.startswith("License ::"))
    if not licence:
        raise ValueError("%s names no licence in its metadata" % dist_info)
    files = []
    for name in meta.get_all("License-File") or []:
        # PEP 639 puts them in .dist-info/licenses/; older tools beside METADATA.
        for candidate in (folder / "licenses" / name, folder / name):
            if candidate.is_file():
                files.append(candidate)
                break
    if not files:
        # Older metadata names none: the usual names in the folder.
        files = sorted(p for p in folder.rglob("*") if p.is_file() and p.name.upper().startswith(("LICENSE",
                                                                                                    "LICENCE",
                                                                                                    "COPYING")))
    return meta["Name"], meta["Version"], licence, files


def copy_tree_files(root, files, lib):
    """The server's files from the tree (paths git listed) into lib/, as they are; only the executable bit kept."""
    for rel in files:
        source = Path(root) / rel
        if not source.is_file():
            # Listed by git and gone from the working tree (deleted, not committed): not part of this tree's server.
            continue
        target = lib / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        target.chmod(0o755 if os.access(source, os.X_OK) else 0o644)


def unpack_7zip(cache, target, lib):
    """The official 7-Zip's program for the target, with its licence and readme, into lib/7-zip."""
    folder = lib / "7-zip"
    folder.mkdir(parents=True)
    with tarfile.open(Path(cache) / target.sevenzip) as archive:
        for name in ("7zz", "License.txt", "readme.txt"):
            data = archive.extractfile(name).read()
            (folder / name).write_bytes(data)
            (folder / name).chmod(0o755 if name == "7zz" else 0o644)


def from_template(path, values):
    """A file of packaging/server with each @KEY@ put in; ValueError naming a placeholder left with no value."""
    import re
    text = Path(path).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("@%s@" % key, value)
    left = re.search(r"@[A-Z]+@", text)
    if left:
        raise ValueError("%s has %s, which nothing fills" % (Path(path).name, left.group(0)))
    return text


def notices(stage, version, target, libraries_found):
    """licenses/ in the package: each part's licence text, and NOTICES.txt saying for each part what it is, its
    version, its licence and which file holds its text. A part with no text stops the build: a package does not go
    out carrying what its notices leave out."""
    folder = stage / "licenses"
    folder.mkdir()
    rows = []

    def text(source, name):
        """A licence text copied into licenses/ under `name`; returns its path in the package."""
        data = Path(source).read_bytes()
        if not data.strip():
            raise ValueError("the licence text %s is empty" % source)
        (folder / name).write_bytes(data)
        return "licenses/" + name

    rows.append(("openDMT3 %s" % version, "the server, its site and this package", "MIT", "LICENSE.txt"))
    rows.append(("Python %s (python-build-standalone %s)" % (PYTHON_VERSION, PYTHON_RELEASE),
                 "runs the server (lib/python)", "PSF License",
                 text(stage / "lib" / "python" / "lib" / "python3.12" / "LICENSE.txt", "Python-LICENSE.txt")))
    for key in target.libraries:
        title, use, licence, source = LIBRARIES[key]
        rows.append((title, "in %s" % use, licence, text(source, Path(source).name)))
    for name, version, licence, files in libraries_found:
        kept = [text(path, "%s-%s" % (name, path.name)) for path in files]
        if not kept:
            raise ValueError("%s %s brings no licence text" % (name, version))
        rows.append(("%s %s" % (name, version), "the site (lib/python's site-packages)", licence, ", ".join(kept)))
    rows.append(("7-Zip 25.01", "reads the client data's archives (lib/7-zip/7zz)", "GNU LGPL, with the unRAR "
                 "restriction", text(stage / "lib" / "7-zip" / "License.txt", "7-Zip-License.txt")))
    fonts = stage / "lib" / "opendmt3"
    rows.append(("DMT3 Wide (from Saira), Pretendard", "the site's lettering", "SIL Open Font License 1.1",
                 ", ".join([text(fonts / "client" / "assets" / "fonts" / "Saira-OFL.txt", "Saira-OFL.txt"),
                            text(fonts / "server" / "web" / "static" / "fonts" / "OFL-Pretendard.txt",
                                 "Pretendard-OFL.txt")])))
    if (stage / "installer").is_dir():
        rows.append(("The launcher's installer", "the site's Download page (installer/)", "MIT (openDMT3), with the "
                     "licences of what it carries inside it", "LICENSE.txt"))
    width = max(len(r[0]) for r in rows)
    lines = ["The programs and parts this package brings, and their licences", "=" * 64, ""]
    for title, use, licence, where in rows:
        lines.append("%s  %s" % (title.ljust(width), use))
        lines.append("%s  %s: %s" % (" " * width, licence, where))
    (folder / NOTICES).write_text("\n".join(lines) + "\n", encoding="utf-8")


def compile_all(stage):
    """Every module's bytecode, made now by this same Python (the package's own release of it), so a start compiles
    nothing and writes nothing into the package: checked by nothing at start (unchecked hash), as the server's image
    makes its own, since the package's sources never change. One process, and each file's name as a path within the
    package (the stage's own folder taken off): the same bytes whichever folder builds them. Python puts the file's
    real place back when it loads one (importlib fixes a code object's file name to its source's)."""
    import compileall
    import py_compile
    for folder in (stage / "lib" / "python" / "lib" / "python3.12", stage / "lib" / "opendmt3"):
        ok = compileall.compile_dir(str(folder), quiet=2, workers=1, force=True, stripdir=str(stage),
                                    invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
        if not ok:
            raise ValueError("a module of %s does not compile" % folder)


def manifest(stage):
    """files.sha256: every file of the package (not its links, not itself) with its SHA-256, sorted, as sha256sum
    writes it."""
    lines = []
    for path in sorted(p for p in stage.rglob("*") if p.is_file() and not p.is_symlink()):
        rel = path.relative_to(stage).as_posix()
        if rel != MANIFEST:
            lines.append("%s  %s" % (sha256_of(path), rel))
    (stage / MANIFEST).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_archive(stage, out):
    """The folder as a .tar.gz that unpacks into one folder of its name: members sorted, each with the fixed time, no
    owner, the mode reduced to what it means (0755 a folder or a program, 0644 the rest), links kept as links; gzip's
    header with no time and no name. The same folder makes the same bytes."""
    top = stage.name
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as archive:
        paths = [stage] + sorted(stage.rglob("*"), key=lambda p: p.relative_to(stage).as_posix())
        for path in paths:
            rel = path.relative_to(stage).as_posix()
            info = tarfile.TarInfo(top if rel == "." else "%s/%s" % (top, rel))
            info.mtime, info.uid, info.gid, info.uname, info.gname = FIXED_TIME, 0, 0, "", ""
            if path.is_symlink():
                info.type, info.linkname, info.mode = tarfile.SYMTYPE, os.readlink(path), 0o777
                archive.addfile(info)
            elif path.is_dir():
                info.type, info.mode = tarfile.DIRTYPE, 0o755
                archive.addfile(info)
            else:
                data = path.read_bytes()
                info.size = len(data)
                info.mode = 0o755 if path.stat().st_mode & stat.S_IXUSR else 0o644
                archive.addfile(info, io.BytesIO(data))
    with open(out, "wb") as f, gzip.GzipFile(filename="", mode="wb", fileobj=f, mtime=0, compresslevel=9) as z:
        z.write(raw.getvalue())


def build_one(cache, files, out, version, key, installer=None, root=ROOT):
    """One target's package in `out`; returns its path. The folder is put together in out/stage first, made again
    from nothing each time."""
    target = TARGETS[key]
    name = name_of(version, key)
    stage = Path(out) / "stage" / name
    shutil.rmtree(stage, ignore_errors=True)
    lib = stage / "lib"
    lib.mkdir(parents=True)
    unpack_python(cache, target, lib)
    site = lib / "python" / SITE
    found = []
    for url, _ in WHEELS + target.wheels:
        dist_info = install_wheel(Path(cache) / url.rsplit("/", 1)[1], site)
        found.append(dist_licences(site, dist_info))
    (site / PATH_FILE[0]).write_text(PATH_FILE[1], encoding="utf-8")
    copy_tree_files(root, files, lib)
    unpack_7zip(cache, target, lib)
    values = {"VERSION": version, "SYSTEM": target.system, "NAME": name, "TARGET": key,
              "QUARANTINE": QUARANTINE % name if key.startswith("macos-") else ""}
    program = stage / PROGRAM
    program.write_text(from_template(Path(root) / "packaging" / "server" / "opendmt3-server.sh", values),
                       encoding="utf-8")
    program.chmod(0o755)
    (stage / README).write_text(from_template(Path(root) / "packaging" / "server" / "README.txt", values),
                                encoding="utf-8")
    (stage / "LICENSE.txt").write_bytes((Path(root) / "LICENSE").read_bytes())
    if installer:
        # The launcher's installer, which the first start puts in the data folder's downloads for the Download page.
        (stage / "installer").mkdir()
        shutil.copyfile(installer, stage / "installer" / Path(installer).name)
    notices(stage, version, target, sorted(found, key=lambda d: d[0].lower()))
    compile_all(stage)
    manifest(stage)
    path = Path(out) / (name + ".tar.gz")
    write_archive(stage, path)
    return path


def tree_files(listing):
    """The paths in bundle.sh's listing of the tree (git ls-files -z), within FROM_TREE."""
    names = [n for n in Path(listing).read_bytes().decode("utf-8").split("\0") if n]
    return sorted(n for n in names if any(n == p or n.startswith(p + "/") for p in FROM_TREE))


def code_version(root=ROOT):
    """`__version__` as opendmt3/__init__.py writes it."""
    import re
    text = (Path(root) / "opendmt3" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'^__version__ = "([^"]*)"', text, re.M).group(1)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("fetch", help="every pinned file into CACHE, checked")
    one.add_argument("cache", type=Path)
    one.add_argument("targets", nargs="*", default=[])
    two = sub.add_parser("build", help="the packages, from CACHE and the tree's files FILES lists")
    two.add_argument("cache", type=Path)
    two.add_argument("files", type=Path, help="git ls-files -z of the tree (bundle.sh writes it)")
    two.add_argument("out", type=Path)
    two.add_argument("--installer", type=Path, help="the launcher's installer to bring")
    two.add_argument("--root", type=Path, default=ROOT, help="the tree the server's files come from")
    two.add_argument("targets", nargs="*", default=[])
    args = parser.parse_args(argv)
    targets = args.targets or sorted(TARGETS)
    unknown = [t for t in targets if t not in TARGETS]
    if unknown:
        parser.error("no such target: %s (%s)" % (", ".join(unknown), ", ".join(sorted(TARGETS))))
    try:
        if args.command == "fetch":
            print("fetched %d file(s) into %s" % (fetch(args.cache, targets), args.cache))
            return 0
        if sys.version_info[:2] != (3, 12) or sys.version.split()[0] != PYTHON_VERSION:
            # Another Python would compile other bytes: the packages are made by the one they carry.
            print("the packages are built by Python %s (bundle.sh runs it), not %s" % (PYTHON_VERSION,
                                                                                     sys.version.split()[0]),
                  file=sys.stderr)
            return 1
        files = tree_files(args.files)
        version = code_version(args.root)
        for key in targets:
            path = build_one(args.cache, files, args.out, version, key, args.installer, args.root)
            print("%s  %s" % (sha256_of(path), path.name))
        return 0
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile, subprocess.CalledProcessError) as e:
        print("the server's packages: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
