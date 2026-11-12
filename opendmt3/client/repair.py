"""Repair of the installed launcher, from the package Velopack keeps beside it (Help, Repair; --repair).

Velopack leaves the package it installed in packages\\ of the install folder (openDMT3-<version>-full.nupkg, a zip),
and current\\ holds exactly the files under the package's lib/app/ (its updater and its starter live one folder up).
So a file of the program that went missing or changed (a cleaner, an antivirus, a disk fault) is found by comparing
sizes and CRC-32s, and comes back from the package: no download and no installer. The launcher's settings, the
players and records, and the game folder are no part of the program and are never touched here.

Windows does not let a file of a running program be written over, but lets it be renamed: such a file is moved
aside first, and the aside copy goes at the next repair. What still cannot be put back is counted, and the
installer's own Repair (openDMT3-win-Setup.exe run again) takes over from there. As in the OpenDMTQ PC client.
"""

import logging
import os
import sys
import time
import zipfile
import zlib

from opendmt3.core.errors import Worded

log = logging.getLogger("opendmt3.launcher")

PACKAGE_ID = "openDMT3"
# Where a package keeps the program's files.
APP_PREFIX = "lib/app/"
# The package's copy of Velopack's updater, and the ending of its copy of the starter of the current version: both
# live in the install folder itself, above current\, under these names.
UPDATER_ENTRY, UPDATER = "Squirrel.exe", "Update.exe"
STUB_ENDING = "_ExecutionStub.exe"
# A file moved aside because it was in use, and one still being written.
ASIDE, PART = ".opendmt3-old", ".opendmt3-new"
# Read and written a megabyte at a time.
CHUNK = 1 << 20
# Tries at swapping a file in, a moment apart: a virus scanner holds a file it has just seen being written.
TRIES, PAUSE = 3, 0.2


class RepairError(Worded):
    """The repair cannot be made here; its words say why and what to do instead (errors.py)."""


class Result:
    """What a repair found and did: how many files it compared, which were missing or changed (paths relative to
    the install folder), and which of those it could not put back."""

    def __init__(self, checked, missing, changed, failed):
        self.checked, self.missing, self.changed, self.failed = checked, missing, changed, failed

    @property
    def restored(self):
        """How many files came back."""
        return len(self.missing) + len(self.changed) - len(self.failed)

    @property
    def needs_restart(self):
        """Whether a file of the launcher itself came back: the running one goes on with what it loaded at start."""
        back = [n for n in self.missing + self.changed if n not in self.failed]
        # Everything in current\ is the launcher's, but the version file Velopack reads.
        return any(n.startswith("current" + os.sep) and n != os.path.join("current", "sq.version") for n in back)


def install_root():
    """The install folder of the launcher that runs (current\\ is the folder of its program), or None when it runs
    from source or a copied folder."""
    if not getattr(sys, "frozen", False):
        return None
    here = os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(here) if os.path.basename(here).lower() == "current" else None


def installed_version(root):
    """The version Velopack installed in root (current\\sq.version), or None."""
    from opendmt3.client import installer
    return installer.installed_version(root)


def package_path(root):
    """The package of the installed version in the install folder; RepairError when it is not there."""
    version = installed_version(root)
    path = os.path.join(root, "packages", "%s-%s-full.nupkg" % (PACKAGE_ID, version)) if version else None
    if not path or not os.path.isfile(path):
        raise RepairError("the installed package is not on this PC (run openDMT3-win-Setup.exe again and choose "
                          "Repair)", "error.repair.no_package")
    return path


def _target(root, entry):
    """Where a package's entry belongs on the disk, or None for an entry that is no file of the program."""
    if not entry.startswith(APP_PREFIX) or entry.endswith("/"):
        return None
    name = entry[len(APP_PREFIX):]
    parts = name.split("/")
    # Names that would leave the install folder are no part of a package Velopack made.
    if not name or any(p in ("", ".", "..") or ":" in p or "\\" in p for p in parts):
        return None
    if len(parts) == 1 and name == UPDATER_ENTRY:
        return os.path.join(root, UPDATER)
    if len(parts) == 1 and name.endswith(STUB_ENDING):
        return os.path.join(root, name[:-len(STUB_ENDING)] + ".exe")
    return os.path.join(root, "current", *parts)


def _crc(path):
    """The CRC-32 of a file, as a zip keeps it."""
    value = 0
    with open(path, "rb") as f:
        while True:
            piece = f.read(CHUNK)
            if not piece:
                return value & 0xFFFFFFFF
            value = zlib.crc32(piece, value)


def _sweep(root):
    """Remove what earlier repairs moved aside or left half written; a file still in use stays for the next one."""
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith((ASIDE, PART)):
                try:
                    os.remove(os.path.join(folder, name))
                except OSError:
                    pass


def _swap_in(part, target):
    """Put the written file in its place; OSError when Windows keeps refusing. A file in use by a running program
    (this one, most likely) cannot be written over but can be renamed: it goes aside first, and comes back when the
    new one still cannot take its place, so a changed file never becomes a missing one."""
    for attempt in range(TRIES):
        try:
            os.replace(part, target)
            return
        except OSError:
            if attempt < TRIES - 1:
                time.sleep(PAUSE)
    aside = target + ASIDE
    os.replace(target, aside)
    try:
        os.replace(part, target)
    except OSError:
        os.replace(aside, target)
        raise


def _put_back(package, info, target):
    """One file out of the package into its place; False when Windows does not let it be replaced."""
    part = target + PART
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        # Written beside its place first: a repair that stops half way leaves the file there as it was.
        with package.open(info) as source, open(part, "wb") as out:
            while True:
                piece = source.read(CHUNK)
                if not piece:
                    break
                out.write(piece)
        _swap_in(part, target)
        return True
    except OSError as e:
        log.warning("repair: could not put %s back: %s", target, e)
        try:
            os.remove(part)
        except OSError:
            pass
        return False


def run(root=None):
    """Compare the installed program with its package and put back what is missing or changed; returns the Result.

    RepairError when this launcher was not installed by openDMT3-win-Setup.exe, or its package is gone or cannot be
    read.
    """
    root = root or install_root()
    if not root or not installed_version(root):
        raise RepairError("repair works in the launcher installed by openDMT3-win-Setup.exe",
                          "error.repair.not_installed")
    path = package_path(root)
    _sweep(root)
    missing, changed, failed, checked = [], [], [], 0
    try:
        with zipfile.ZipFile(path) as package:
            entries = [(info, _target(root, info.filename)) for info in package.infolist()]
            for info, target in entries:
                if not target:
                    continue
                name = os.path.relpath(target, root)
                try:
                    if not os.path.isfile(target):
                        kind = missing
                    elif os.path.getsize(target) != info.file_size or _crc(target) != info.CRC:
                        kind = changed
                    else:
                        kind = None
                except OSError as e:
                    # A file that cannot be read is put back as a changed one; the files after it are still compared.
                    log.warning("repair: could not read %s: %s", target, e)
                    kind = changed
                if kind is not None:
                    kind.append(name)
                    if not _put_back(package, info, target):
                        failed.append(name)
                checked += 1
    except (zipfile.BadZipFile, zlib.error, EOFError, OSError) as e:
        # The package itself is damaged or cannot be opened: only the installer has another copy.
        log.warning("repair: the installed package cannot be read: %s", e)
        raise RepairError("the installed package cannot be read (run openDMT3-win-Setup.exe again and choose "
                          "Repair)", "error.repair.package") from e
    log.info("repair: %d files compared, %d missing, %d changed, %d not put back", checked, len(missing),
             len(changed), len(failed))
    for name in missing + changed:
        log.info("repair: %s%s", name, " (not put back)" if name in failed else "")
    return Result(checked, missing, changed, failed)
