"""The licence texts of everything the installed launcher carries, gathered when it is built.

    python packaging/windows/notices.py DIST REPO      (the build's own Windows Python, right after PyInstaller)

DIST is PyInstaller's folder of the launcher (dist/openDMT3), REPO the repository it was built from. Writes
DIST/licenses: each part's licence text in full, and NOTICES.txt, which says for each part what it is, its version,
its licence and which file holds the text. What it lists comes from the build itself, not from a list kept by hand:

- the Python packages: the modules inside the programs (the archive PyInstaller put in openDMT3.exe, read with
  PyInstaller's own reader) and the folders beside them, matched to the packages installed in this Python, each with
  its version, its licence as its metadata says it and the licence files its metadata names;
- Python itself: its own LICENSE.txt (the PSF License, with bzip2's and Tcl/Tk's terms and Microsoft's for its C
  runtime), Tk's license.terms, and the libraries in its modules that the folder holds, each with the version this
  Python reports;
- openDMT3's own: its LICENSE, and the texts the build put beside its parts (the fonts', 7-Zip's, the card reader
  library's notices).

The texts this Python does not carry (the libraries in its modules, Velopack's) are kept unchanged in
packaging/windows/licenses, whose README.md says where each was taken from. Exits 1, naming it, when the folder holds a
part with no licence text or a library no part claims: a build does not go out carrying what its notices leave out.
Standard library only (and PyInstaller's reader, which the build's Python has); it also runs on Python 3.10 for the
unit tests.
"""

import argparse
import fnmatch
import importlib.metadata
import os
import re
import shutil
import sys

# The texts this Python does not carry, kept unchanged beside this script (licenses/README.md says where from).
KEPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "licenses")
# The folder the installed program's texts go in, beside openDMT3.exe (docs/notice.md names it).
FOLDER = "licenses"
# The file in it that says which text is whose.
NOTICES = "NOTICES.txt"


def _openssl():
    """OpenSSL's version as Python's ssl reports it ("OpenSSL 3.5.9 29 Sep 2026" -> "3.5.9")."""
    import ssl
    return ssl.OPENSSL_VERSION.split()[1]


def _sqlite():
    """The SQLite library's own version (not the module's)."""
    import sqlite3
    return sqlite3.sqlite_version


def _zlib():
    """The zlib Python runs with, which may differ from the one it was built against."""
    import zlib
    return zlib.ZLIB_RUNTIME_VERSION


def _expat():
    """Expat's version ("expat_2.9.0" -> "2.9.0")."""
    import pyexpat
    return pyexpat.EXPAT_VERSION.split("_")[-1]


def _mpdecimal():
    """mpdecimal's version, which Python's decimal module is built on."""
    import decimal
    return decimal.__libmpdec_version__


def _tcl():
    """Tcl's patch level ("8.6.15"), from an interpreter without a window (Tk's version is the same)."""
    import tkinter
    return tkinter.Tcl().eval("info patchlevel")


# The libraries inside Python's own modules, each known by the files that carry it in a build (any one is enough):
# (name, those files, what it does there, what reports its version, its licence, its kept text). Python's own
# LICENSE.txt has no text for them; bzip2's and Tcl/Tk's it has, so those two are in Python's row and Tcl/Tk's below.
LIBRARIES = [
    ("OpenSSL", ("libssl-*.dll", "libcrypto-*.dll", "_ssl.pyd", "_hashlib.pyd"), "in Python's ssl and hashlib",
     _openssl, "Apache-2.0", "OpenSSL-LICENSE.txt"),
    ("libffi", ("libffi-*.dll", "_ctypes.pyd"), "in Python's ctypes", None, "MIT", "libffi-LICENSE.txt"),
    ("SQLite", ("sqlite3.dll", "_sqlite3.pyd"), "in Python's sqlite3, where the launcher's own server keeps its "
     "players and records", _sqlite, "public domain", "SQLite-LICENSE.txt"),
    ("zlib", ("python3*.dll", "zlib1.dll"), "in Python's zlib and in Tk", _zlib, "Zlib", "zlib-LICENSE.txt"),
    ("Expat", ("pyexpat.pyd", "_elementtree.pyd"), "in Python's XML readers", _expat, "MIT", "Expat-LICENSE.txt"),
    ("mpdecimal", ("_decimal.pyd",), "in Python's decimal", _mpdecimal, "BSD-2-Clause", "mpdecimal-LICENSE.txt"),
    ("XZ Utils' liblzma", ("_lzma.pyd",), "in Python's lzma", None, "0BSD", "liblzma-LICENSE.txt"),
]
# Packages whose metadata names no licence file of their own, with the kept text that is theirs.
KEPT_FOR = {"velopack": "Velopack-LICENSE.txt"}
# The Apache License 2.0 in full (OpenSSL's licence is that text, unchanged): a package under it whose own file is
# only the short notice gets the whole licence beside it, as the licence asks.
APACHE = ("Apache-2.0.txt", "OpenSSL-LICENSE.txt")
# What a package's part is in the launcher, for the reader of NOTICES.txt (the rest are the libraries the site and the
# window are made with, or what those bring along).
ROLES = {
    "pillow": "the pictures (jackets, DJ cards, the launcher's own); the image libraries in it are listed with their "
              "licences in its text",
    "pyinstaller": "its bootloader, which starts openDMT3.exe and openDMT3-cmd.exe, and its loader",
    "velopack": "the installer's setup, Update.exe and the launcher's updates; the libraries in its Python module "
                "are listed with their licences in its SBOM",
    "starlette": "the site the launcher runs for playing on this PC", "uvicorn": "the same site's web server",
    "jinja2": "the same site's pages", "python-multipart": "the same site's uploads",
}


def _key(name):
    """A package's name as Python's packaging compares names: lower case, runs of - _ . as one -."""
    return re.sub(r"[-_.]+", "-", name).lower()


# ------------------------------------------------------------------------------------------------ what the build holds

def frozen_modules(programs):
    """The top-level names of every module inside the PyInstaller programs: their archive of pure Python modules
    (PYZ) and the scripts and loader modules beside it, read with PyInstaller's own reader."""
    from PyInstaller.archive.readers import CArchiveReader
    names = set()
    for program in programs:
        archive = CArchiveReader(program)
        for name, entry in archive.toc.items():
            # The type code is each entry's last field: z is the PYZ, m and M modules, s scripts.
            kind = entry[-1]
            if kind == "z":
                names.update(module.split(".")[0] for module in archive.open_embedded_archive(name).toc)
            elif kind in ("m", "M", "s"):
                names.add(name.split(".")[0])
    return names


def contents(dist):
    """The folder PyInstaller puts everything but the programs in (_internal since PyInstaller 6, the folder itself
    before), and the top-level names in it."""
    inner = os.path.join(dist, "_internal")
    folder = inner if os.path.isdir(inner) else dist
    # The licence folder this script writes is no part the build brought.
    return folder, sorted(name for name in os.listdir(folder) if name != FOLDER)


def bundled(names, owners, installed):
    """The installed packages the build holds: those owning a module or a folder it carries (owners: top-level name ->
    package names, as importlib.metadata.packages_distributions() gives it), and PyInstaller, whose bootloader is
    every program. A copied .dist-info folder counts for its package. installed: package key -> Distribution."""
    found = {"pyinstaller"} & set(installed)
    for name in names:
        if name.endswith(".dist-info"):
            # click-8.5.1.dist-info: the name before the version.
            found.add(_key(name[:-len(".dist-info")].rsplit("-", 1)[0]))
            continue
        for owner in owners.get(name, ()):
            found.add(_key(owner))
    # Only what is installed here has metadata to read; a name nothing owns is Python's own or openDMT3's.
    return sorted(found & set(installed))


# ------------------------------------------------------------------------------------------------ a package's licence

def licence_of(metadata):
    """A package's licence as its metadata says it: License-Expression (an SPDX expression), else a short License
    field, else its licence classifiers, else nothing (the text alone then says it)."""
    expression = (metadata.get("License-Expression") or "").strip()
    if expression:
        return expression
    field = (metadata.get("License") or "").strip()
    # Some packages put the whole licence text in License; one line of a sensible length is a name.
    if field and "\n" not in field and len(field) <= 200:
        return field
    classifiers = [c.split("::")[-1].strip() for c in metadata.get_all("Classifier") or []
                   if c.startswith("License ::")]
    return ", ".join(classifiers)


def licence_files(dist):
    """A package's licence texts as (name in its metadata, text): the files License-File names (PEP 639 keeps them in
    .dist-info/licenses/, older tools beside METADATA)."""
    found = []
    for name in dist.metadata.get_all("License-File") or []:
        # PEP 639's place first, then the older one.
        text = dist.read_text("licenses/" + name)
        if text is None:
            text = dist.read_text(name)
        if text is not None:
            found.append((name, text))
    return found


def sboms(dist):
    """The SBOMs a package carries (PEP 770, .dist-info/sboms/), as (name, text): each lists the libraries built into
    the package with their licences."""
    found = []
    for record in dist.files or []:
        parts = record.parts
        # Files in the .dist-info folder's own sboms/ folder.
        if len(parts) == 3 and parts[0].endswith(".dist-info") and parts[1] == "sboms":
            text = dist.read_text("sboms/" + parts[2])
            if text is not None:
                found.append((parts[2], text))
    return found


# ------------------------------------------------------------------------------------------------ the notices

class Notices:
    """The rows of NOTICES.txt and the texts they name, written into one folder; problems are kept, not raised, so
    one run says every one."""

    def __init__(self, folder):
        self.folder = folder
        self.rows = []
        self.problems = []
        # Each file written: its name -> its content. The same text under the same name (the site's copy of a font's
        # licence) is written once; another text under a taken name gets a name of its own.
        self._written = {}

    def text(self, name, content):
        """Write one text under a name of its own; returns the name it has in the folder."""
        # A file name only (no folder), readable with a double click on Windows: .txt unless it is .txt or .json.
        name = re.sub(r"[\\/:*?\"<>|]+", "-", name)
        stem, dot, suffix = name.rpartition(".")
        if not dot:
            name += ".txt"
        elif suffix.lower() in ("md", "rst"):
            name = stem + ".txt"
        elif suffix.lower() not in ("txt", "json"):
            name += ".txt"
        base, number = name, 1
        while name in self._written and self._written[name] != content:
            number += 1
            stem, _, suffix = base.rpartition(".")
            name = "%s-%d.%s" % (stem, number, suffix)
        if name not in self._written:
            with open(os.path.join(self.folder, name), "w", encoding="utf-8", newline="") as f:
                f.write(content)
            self._written[name] = content
        return name

    def copy(self, name, path):
        """A file's text under a name of its own, or a problem when the file is not there."""
        try:
            with open(path, encoding="utf-8", errors="replace", newline="") as f:
                return self.text(name, f.read())
        except OSError:
            self.problems.append("no licence text at %s" % path)
            return None

    def row(self, what, licence, texts):
        """One part: what it is, its licence, the files with its texts (a part with none is a problem)."""
        # Each file once, in the order given (a text two copies share is one file).
        texts = list(dict.fromkeys(t for t in texts if t))
        if not texts:
            self.problems.append("no licence text for %s" % what)
        self.rows.append((what, licence, texts))

    def write(self):
        """NOTICES.txt; then every file in the folder is named by a row, and every name is a file in it."""
        lines = ["openDMT3's launcher for Windows carries these programs and parts, each under its own licence. The",
                 "full texts are in this folder. openDMT3's own code is under the MIT License (openDMT3-LICENSE.txt).",
                 ""]
        for what, licence, texts in self.rows:
            lines += [what, "  License: " + (licence or "as its text says"), "  Text:    " + ", ".join(texts), ""]
        with open(os.path.join(self.folder, NOTICES), "w", encoding="utf-8", newline="") as f:
            # Windows' own line breaks: the folder is read on Windows, in any editor.
            f.write("\r\n".join(lines))
        named = {t for _, _, texts in self.rows for t in texts}
        present = set(os.listdir(self.folder)) - {NOTICES}
        for orphan in sorted(present - named):
            self.problems.append("%s is in %s but no part names it" % (orphan, FOLDER))
        for missing in sorted(named - present):
            self.problems.append("a part names %s, which is not in %s" % (missing, FOLDER))


def _version_of(repo):
    """openDMT3's version, as opendmt3/__init__.py writes it (the line build.sh reads)."""
    with open(os.path.join(repo, "opendmt3", "__init__.py"), encoding="utf-8") as f:
        found = re.search(r'^__version__ = "([^"]*)"', f.read(), re.M)
    return found.group(1) if found else "?"


def _has(names, patterns):
    """True when the folder's top level has a file matching any of the patterns (in any letter case, as Windows)."""
    return any(fnmatch.fnmatch(name.lower(), pattern.lower()) for name in names for pattern in patterns)


def gather(dist, repo, modules, installed=None, owners=None, python_root=None, kept=KEPT):
    """Every part the launcher's folder holds and its texts, into DIST/licenses; returns the Notices (its problems
    say what is missing). modules: the top-level names inside the programs. installed and owners default to this
    Python's packages; python_root to this Python's own folder (the tests give made-up ones)."""
    folder = os.path.join(dist, FOLDER)
    # Made afresh: a text left from an earlier build would be named by no row.
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    notes = Notices(folder)
    if installed is None:
        installed = {_key(d.metadata["Name"]): d for d in importlib.metadata.distributions()}
    if owners is None:
        owners = importlib.metadata.packages_distributions()
    python_root = python_root or sys.base_prefix
    inside, names = contents(dist)

    # openDMT3 itself, first: the rest is what it is built with.
    notes.row("openDMT3 %s: the launcher, the site it runs for playing on this PC, and the installer's dialogs"
              % _version_of(repo), "MIT", [notes.copy("openDMT3-LICENSE.txt", os.path.join(repo, "LICENSE"))])

    # Python, with what its own LICENSE.txt covers: its C runtime's terms, bzip2's and Tcl/Tk's.
    runtime = sorted(n for n in names if n.lower().startswith("vcruntime") and n.lower().endswith(".dll"))
    # bzip2's terms are in Python's own text; it is said when its module is in the folder.
    bzip2 = " and bzip2 in its bz2 module" if _has(names, ("_bz2.pyd",)) else ""
    notes.row("Python %d.%d.%d, with the Microsoft C runtime it ships (%s)%s"
              % (sys.version_info[:3] + (", ".join(runtime) or "none", bzip2)),
              "Python-2.0 (the PSF License Agreement), with bzip2's and Tcl/Tk's terms; the C runtime under "
              "Microsoft's terms for its distributable code",
              [notes.copy("Python-LICENSE.txt", os.path.join(python_root, "LICENSE.txt"))])
    if _has(names, ("_tkinter.pyd", "tk86*.dll")):
        # Tk's own terms, from the copy PyInstaller put beside its library, else this Python's.
        terms = os.path.join(inside, "_tk_data", "license.terms")
        tcl = os.path.join(python_root, "tcl")
        if not os.path.isfile(terms) and os.path.isdir(tcl):
            # tcl/tk8.6/license.terms in a Windows Python.
            found = sorted(p for p in (os.path.join(tcl, d, "license.terms") for d in os.listdir(tcl)
                                       if d.lower().startswith("tk")) if os.path.isfile(p))
            terms = found[0] if found else terms
        notes.row("Tcl/Tk %s: the launcher's window" % _tcl(), "TCL (BSD-style)",
                  [notes.copy("Tcl-Tk-license.terms.txt", terms)])
    for name, files, where, version, licence, text in LIBRARIES:
        if not _has(names, files):
            continue
        said = (" " + version()) if version else ""
        notes.row("%s%s, %s" % (name, said, where), licence, [notes.copy(text, os.path.join(kept, text))])

    # The Python packages the build holds.
    for key in bundled(set(modules) | set(names), owners, installed):
        dist = installed[key]
        name = dist.metadata["Name"]
        own = licence_files(dist)
        texts = [notes.text("%s-%s" % (name, os.path.basename(path)), content) for path, content in own]
        if key in KEPT_FOR:
            texts.insert(0, notes.copy(KEPT_FOR[key], os.path.join(kept, KEPT_FOR[key])))
        elif not own:
            # An SBOM lists what is inside a package; it is not the package's own licence.
            notes.problems.append("%s %s names no licence file in its metadata" % (name, dist.version))
        licence = licence_of(dist.metadata)
        if "Apache-2.0" in licence and not any("TERMS AND CONDITIONS FOR USE" in content for _, content in own):
            texts.append(notes.copy(APACHE[0], os.path.join(kept, APACHE[1])))
        texts += [notes.text("%s-%s" % (name, path), content) for path, content in sboms(dist)]
        role = ROLES.get(key)
        notes.row("%s %s%s" % (name, dist.version, (": " + role) if role else ""), licence, texts)

    # openDMT3's parts made by others, with the texts the build put beside them.
    sevenzip = os.path.join(inside, "opendmt3", "client", "bin", "7-Zip")
    if os.path.isdir(sevenzip):
        try:
            with open(os.path.join(sevenzip, "readme.txt"), encoding="utf-8", errors="replace") as f:
                # The readme's first line is "7-Zip 25.01".
                release = f.readline().strip()
        except OSError:
            release = "7-Zip"
        notes.row("%s for Windows (7z.exe, 7z.dll): the launcher lists, tests and unpacks the game's archives with it"
                  % release, "GNU LGPL, with the unRAR license restriction and BSD licences for some code",
                  [notes.copy("7-Zip-License.txt", os.path.join(sevenzip, "License.txt"))])
    cabinet = os.path.join(inside, "opendmt3", "core", "cabinet", "bin")
    if os.path.isfile(os.path.join(cabinet, "CRT_R1.dll")):
        # Beside the library in the program, and beside it wherever the launcher puts it (core/cabinet/native.py).
        notes.row("openDMT3's card reader library (CRT_R1.dll), with AMD FidelityFX Super Resolution 1, NVIDIA Image "
                  "Scaling, SMAA and FXAA 3.11 in it, and the runtime its compiler links in",
                  "MIT (openDMT3, FSR 1, NIS, SMAA); NVIDIA's notice (FXAA 3.11); the mingw-w64 runtime's licences; "
                  "GPL 3 with the GCC Runtime Library Exception (libgcc)",
                  [notes.copy("card-reader-NOTICES.txt", os.path.join(cabinet, "card-reader-NOTICES.txt"))])
    if any(os.path.isfile(os.path.join(cabinet, name)) for name in ("openDMT3-dsoal.dll", "dsoal-aldrv.dll")):
        # The Sound page's OpenAL Soft mixer beside the library (native/openal/build.sh made the notices with them,
        # each licence text in full, read from the source archives the release carries).
        notes.row("DSOAL (openDMT3-dsoal.dll) and OpenAL Soft (dsoal-aldrv.dll): the Sound page's OpenAL Soft mixer, "
                  "beside the card reader library",
                  "GNU LGPL 2.1 or later (DSOAL) and GNU LGPL 2 or later (OpenAL Soft), with the BSD 3-Clause, PFFFT, "
                  "{fmt} and GSL (MIT) licences of parts of them",
                  [notes.copy("openal-NOTICES.txt", os.path.join(cabinet, "openal-NOTICES.txt"))])
    fonts = os.path.join(inside, "opendmt3", "client", "assets", "fonts")
    if os.path.isdir(fonts):
        notes.row("The fonts: DMT3 Wide (cut from Saira), Pretendard, and DMT3 Text (cut from Pretendard) for the site",
                  "OFL-1.1 (the SIL Open Font License 1.1)",
                  [notes.copy(name, os.path.join(fonts, name)) for name in sorted(os.listdir(fonts))
                   if name.endswith("-OFL.txt")]
                  # The site's copy, written once when it is the same text as the launcher's.
                  + [notes.copy("Pretendard-OFL.txt", os.path.join(inside, "opendmt3", "server", "web", "static",
                                                                   "fonts", "OFL-Pretendard.txt"))])

    # A library at the top of the folder that no part claims would go out without its notice.
    own = set(os.listdir(python_root)) | set(os.listdir(os.path.join(python_root, "DLLs"))
                                             if os.path.isdir(os.path.join(python_root, "DLLs")) else ())
    claimed = {p for _, files, _, _, _, _ in LIBRARIES for p in files} | {"vcruntime*.dll", "_tkinter.pyd", "tk86*.dll",
                                                                       "tcl86*.dll"}
    for name in names:
        if name.lower().endswith((".dll", ".pyd")) and name not in own and not _has([name], claimed):
            notes.problems.append("%s is in the program, and no part of NOTICES.txt claims it" % name)
    notes.write()
    return notes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dist", help="PyInstaller's folder of the launcher (dist/openDMT3)")
    parser.add_argument("repo", help="the repository it was built from")
    args = parser.parse_args(argv)
    # Both programs: what is inside either is in the folder people install.
    programs = sorted(os.path.join(args.dist, n) for n in os.listdir(args.dist) if n.lower().endswith(".exe"))
    notes = gather(args.dist, args.repo, frozen_modules(programs))
    for problem in notes.problems:
        print("licenses: " + problem, file=sys.stderr)
    if notes.problems:
        return 1
    print("licenses: %d parts, %d files in %s" % (len(notes.rows), len(os.listdir(notes.folder)),
                                                 os.path.join(args.dist, FOLDER)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
