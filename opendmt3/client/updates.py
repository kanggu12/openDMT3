"""Updates of the installed launcher, through Velopack (the installer's own update channel).

Only a launcher installed by openDMT3-win-Setup.exe can update itself; one run from source or from a copied
folder says so instead. Where releases are published is set when the launcher is built: build.sh writes the
OPENDMT3_UPDATE_SOURCE it was given (a GitHub repository URL, an HTTP folder or a local folder) into
update-source.txt next to this module. A build made without one has no update address and says so. The same
variable at run time takes its place, for trying a feed out. Every call here may be slow (network), so the window
runs them on a worker thread.

An update is put in only when its package carries the project's signature (opendmt3/core/signing.py): the feed can be
a server's plain HTTP address, and whoever answers for it writes the feed's list as well. So nothing of a download is
in the install folder before its signature is checked (apply):

  1. the feed's names are checked before anything is fetched or deleted: plain file names, the package the one named
     for the version offered, that version newer than the one installed (offered);
  2. the launcher fetches the update itself into a folder of its own in the temporary folder: the package's .sig
     first, then the package; or, when the feed has delta packages from the version installed, each delta with its own
     .sig, checked by its bytes before the installed Update.exe puts the new package together from them, into that
     same folder;
  3. the package is checked there, by its bytes or (put together from deltas) by the files it holds, and the version
     written inside it is the one offered;
  4. only then it is moved into packages\\, the installed Update.exe is replaced by the one the package carries, and
     Velopack is told to put the package in once this program has ended.

Velopack's own download (UpdateManager.download_updates) is never used: it writes what it downloads straight into
packages\\ under the names the feed gives, and puts the downloaded package's Update.exe over the installed one before
it returns (Velopack 1.2.161, manager.rs). Keeping the installed Update.exe aside and putting it back after a refusal
would leave the downloaded one in place for a launcher that ends in between.
"""

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

from opendmt3.core.errors import Worded

log = logging.getLogger(__name__)

SOURCE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "update-source.txt")
# The package's name in Velopack's feed and in its files' names: openDMT3-<version>-full.nupkg, -delta.nupkg.
PACKAGE_ID = "openDMT3"
# A version as a feed may give it (Semantic Versioning's letters only): a file name made of it has no folder, no drive
# and no part of dots only.
VERSION = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")
# The launcher's own folders for what it fetches start with this in the temporary folder; one left by a launcher that
# ended mid-update goes at the next update once it is this many seconds old.
OWN_PREFIX, OWN_STALE = "openDMT3-update-", 3600
# A file written beside its place until it is whole (a package copied in from another drive, the new Update.exe): a
# name Velopack reads as no package.
PART = ".opendmt3-new"
# The most bytes one fetched file may hold (a package is some 26 MB), the seconds one read may wait and one file may
# take, the seconds Update.exe may take to put a package together, and the most delta packages taken in a row.
FETCH_LIMIT, READ_SECONDS, FILE_SECONDS, PATCH_SECONDS, MOST_DELTAS = 512 << 20, 30, 1800, 600, 10


def _update_source():
    """The release feed: the variable when it is set, else the one written in at build time, else none."""
    if os.environ.get("OPENDMT3_UPDATE_SOURCE"):
        return os.environ["OPENDMT3_UPDATE_SOURCE"].strip()
    try:
        with open(SOURCE_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


UPDATE_SOURCE = _update_source()


def source_for(state=None):
    """Where this launcher looks for updates: the server it plays on when that server hands them out (its
    /updates/, so the operator's one copy updates every launcher there), else the address built in."""
    remote = (state.remote or {}) if state is not None else {}
    if state is not None and state.mode == "server" and state.server_url and remote.get("updates"):
        return state.server_url.rstrip("/") + "/updates"
    return UPDATE_SOURCE


class UpdateError(Worded):
    """An update that is not put in, worded for the player (errors.py)."""


class Result:
    """What a check found: kind is 'none', 'not_installed', 'no_source', 'uptodate', 'available' or 'failed'."""

    def __init__(self, kind, version=None, info=None, error=None, source=None):
        self.kind, self.version, self.info, self.error = kind, version, info, error
        self.source = source        # the feed it came from; apply() downloads from the same one


def _manager(source=None):
    """The Velopack update manager for a feed (the built-in one by default), or None without a feed."""
    source = source or UPDATE_SOURCE
    if not source:
        return None
    import velopack
    # A GitHub repository URL reads the repository's releases; anything else is a feed folder or URL.
    if source.startswith("https://github.com/"):
        source = velopack.GithubSource(source, None, False)
    return velopack.UpdateManager(source)


def current_version():
    """The installed version, or None outside an installed launcher."""
    try:
        import velopack
        return velopack.UpdateManager(UPDATE_SOURCE or ".").get_current_version()
    except Exception:  # noqa: BLE001  (not installed: run from source or a copied folder)
        return None


def shown_version():
    """The version the launcher shows, beside its logo and on the Launcher page: the installed one, or the code's
    own when it runs from source or a copied folder."""
    from opendmt3 import __version__
    return current_version() or __version__


def check(source=None):
    """Ask the release feed (source_for(state), or the built-in one) whether a newer version exists."""
    source = source or UPDATE_SOURCE
    try:
        import velopack  # noqa: F401  (only to know whether the update library is there)
    except ImportError:
        return Result("not_installed")
    if not source:
        return Result("no_source")
    try:
        manager = _manager(source)
        info = manager.check_for_updates()
    except Exception as e:  # noqa: BLE001
        text = str(e)
        # Velopack refuses outside an installation; that is a state, not a failure.
        if "not installed" in text.lower() or "locator" in text.lower():
            return Result("not_installed")
        return Result("failed", error=text, source=source)
    if not info:
        return Result("uptodate", source=source)
    return Result("available", version=info.TargetFullRelease.Version, info=info, source=source)


def plain(name):
    """True when a name from a feed is one file's name and nothing else: no folder, no drive, no stream, not a name
    of dots only (the folder itself, the one above). Whatever is fetched or deleted is this name inside a folder the
    launcher chose, never a path the feed chose."""
    if not isinstance(name, str) or not name:
        # No name at all (a feed without the field), or something that is no text.
        return False
    if any(c in name for c in "/\\:") or any(ord(c) < 32 for c in name):
        # A separator leaves the folder, a colon names a drive or a file's other stream, a control character no file.
        return False
    # A name of dots only is the folder itself or the one above, and Windows drops dots and spaces at a name's end
    # ("x." and "x " would be the file x): none of these is the file as written.
    return name == name.strip() and not name.endswith(".")


def _refuse(result, why):
    """An update that is not the project's own release of the version offered is not put in: the log says what was
    wrong with it, the player reads the one sentence."""
    log.warning("refused the update to %s from %s: %s", result.version, result.source, why)
    raise UpdateError("the update to %s is not signed by the openDMT3 project, so it was not put in" % result.version,
                      "error.update.unsigned", version=result.version)


def offered(result):
    """What the feed offers, checked before anything is fetched or deleted: (the package's file name, the delta
    packages to it as [(file name, version)], the file name of the local package they start from). No deltas and no
    local package mean the whole package is fetched. Refused: a version that is none, a file name that is not plain,
    a package that is not the one named for the version offered, a version not newer than the one installed."""
    from opendmt3 import __version__
    from opendmt3.client import installer
    info, version = result.info, str(result.version)
    if not VERSION.fullmatch(version):
        # Every file name below is made of it: anything but a version's letters could name another place.
        _refuse(result, "the feed's version %r is not a version" % version)
    name = getattr(info.TargetFullRelease, "FileName", None)
    if not plain(name):
        _refuse(result, "the feed's file name %r is not a plain file name" % (name,))
    if name != "%s-%s-full.nupkg" % (PACKAGE_ID, version):
        # The signature is over the file's name: an older release under its own name and signature, offered as a
        # newer version, is refused here.
        _refuse(result, "the feed names %s as version %s" % (name, version))
    installed = current_version() or __version__
    if installer.version_key(version) <= installer.version_key(installed):
        # Velopack offers only a newer version; a feed's list is never taken for that alone.
        _refuse(result, "version %s is not newer than the one installed, %s" % (version, installed))
    deltas = []
    for delta in getattr(info, "DeltasToTarget", None) or []:
        delta_name, delta_version = getattr(delta, "FileName", None), str(getattr(delta, "Version", ""))
        if not plain(delta_name) or not VERSION.fullmatch(delta_version) \
                or delta_name != "%s-%s-delta.nupkg" % (PACKAGE_ID, delta_version):
            # A feed that names anything else beside the package is not one the project made: nothing of it is fetched.
            _refuse(result, "the feed's delta package %r of version %r is not named for its version"
                    % (delta_name, delta_version))
        deltas.append((delta_name, delta_version))
    # The package Velopack found in packages\\ to start from: a local file's name, checked like the feed's all the same.
    base = getattr(getattr(info, "BaseRelease", None), "FileName", None)
    if not deltas or not plain(base) or len(deltas) > MOST_DELTAS or deltas[-1][1] != version:
        # No deltas, nothing to start from, a chain too long to be worth it, or one that does not end at the version
        # offered: the whole package.
        return name, [], None
    return name, deltas, base


def _own_folder():
    """A new folder of the launcher's own for what it fetches, in the temporary folder: outside the install folder,
    so nothing reaches that before it is checked. A folder left by a launcher that ended mid-update goes first, once
    it is old enough to be no other launcher's update under way."""
    top = tempfile.gettempdir()
    try:
        names = os.listdir(top)
    except OSError:
        # The temporary folder cannot be listed: nothing to tidy, and mkdtemp below says what is wrong with it.
        names = []
    for name in names:
        path = os.path.join(top, name)
        try:
            if name.startswith(OWN_PREFIX) and time.time() - os.path.getmtime(path) > OWN_STALE:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            # Gone meanwhile (another launcher tidied it): nothing left to do.
            pass
    return tempfile.mkdtemp(prefix=OWN_PREFIX)


def _reader(source, name, version):
    """The file `name` of the release `version`, open for reading from the feed the update came from; the caller
    closes it. `name` is a plain file name (offered), so it stays inside the feed's folder or address."""
    from urllib.parse import quote
    if source.startswith("https://github.com/"):
        # A GitHub release keeps its files under its tag, which is v and the version.
        url = "%s/releases/download/v%s/%s" % (source.rstrip("/"), quote(version), quote(name))
    elif source.startswith(("http://", "https://")):
        # A feed address: the packages and their .sig sit beside releases.win.json.
        url = "%s/%s" % (source.rstrip("/"), quote(name))
    else:
        # A feed folder.
        return open(os.path.join(source, name), "rb")
    import urllib.request
    return urllib.request.urlopen(url, timeout=READ_SECONDS)


def _signature(source, name, version):
    """The .sig of a package from the feed the package comes from (as bytes, at most one byte past the limit), or
    None when the feed has none."""
    from opendmt3.core import signing
    try:
        with _reader(source, name + ".sig", version) as f:
            return f.read(signing.SIG_LIMIT + 1)
    except Exception:  # noqa: BLE001  (no .sig there, or no answer: the update is refused either way)
        return None


def _fetch(result, name, version, folder):
    """One package of the release `version` fetched into the launcher's own folder; returns its path. It stops at
    FETCH_LIMIT bytes and FILE_SECONDS seconds: a feed is never given the whole disk or the whole day. An update that
    cannot be downloaded says so."""
    path = os.path.join(folder, name)
    started = time.monotonic()
    try:
        with _reader(result.source, name, version) as f, open(path, "wb") as out:
            size = 0
            # A megabyte at a time: a package is tens of megabytes.
            for piece in iter(lambda: f.read(1 << 20), b""):
                size += len(piece)
                if size > FETCH_LIMIT:
                    raise OSError("%s is larger than any update package (%d bytes and more)" % (name, size))
                if time.monotonic() - started > FILE_SECONDS:
                    raise OSError("%s took longer than %d seconds" % (name, FILE_SECONDS))
                out.write(piece)
    except Exception as e:  # noqa: BLE001  (the network's errors are of many kinds; each ends the same way)
        log.warning("could not fetch %s from %s: %s", name, result.source, e)
        raise UpdateError("The update to %s could not be downloaded. Check the connection and try again."
                          % result.version, "error.update.download", version=result.version) from e
    return path


def updater():
    """Velopack's Update.exe of the installed launcher: beside packages\\, above current\\."""
    return os.path.join(os.path.dirname(packages_dir()), "Update.exe")


def _put_together(base, deltas, out, run):
    """Have the installed Update.exe put the new package together from the installed one and the delta packages
    (Velopack's own command, as its library runs it); True when it wrote `out`. Every delta was checked by its own
    signature before this, and `out` is in the launcher's own folder."""
    args = [updater(), "patch", "--old", base, "--output", out]
    for delta in deltas:
        args += ["--delta", delta]
    try:
        # No window of its own, nothing read from this program's console (the window copy has none).
        done = run(args, stdin=subprocess.DEVNULL, capture_output=True, timeout=PATCH_SECONDS,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as e:
        # No Update.exe, or it never came back: the whole package instead.
        log.warning("Update.exe could not put the package together: %s", e)
        return False
    if done.returncode != 0:
        # Whatever it wrote before it failed is not taken: the end of what it said goes to the log.
        log.warning("Update.exe could not put the package together (exit %s): %s", done.returncode,
                    (done.stderr or b"")[-400:])
        return False
    if not os.path.isfile(out):
        # It ended well and wrote nothing: said, so the log has why the whole package was fetched.
        log.warning("Update.exe could not put the package together: it wrote no package")
        return False
    return True


def _feed_sha256(info):
    """The SHA-256 the feed gives for the whole package (64 hex digits, lower case), or None without one."""
    value = str(getattr(info.TargetFullRelease, "SHA256", "") or "").lower()
    return value if re.fullmatch(r"[0-9a-f]{64}", value) else None


def _from_deltas(result, name, deltas, base, sig, folder, run):
    """The package put together from delta packages, in the launcher's own folder: its path when it checked out, or
    None (the caller fetches the whole package). Each delta is fetched with its own .sig and checked by its bytes
    before Update.exe reads it; what Update.exe wrote is checked by its bytes, or by the files it holds when the feed
    gives the whole package's SHA-256 and these bytes are others."""
    from opendmt3.core import signing
    old = os.path.join(packages_dir(), base)
    if not os.path.isfile(old):
        log.warning("no %s in packages to start the delta packages from", base)
        return None
    fetched = []
    for delta_name, delta_version in deltas:
        delta_sig = _signature(result.source, delta_name, delta_version)
        if delta_sig is None:
            # Nothing of a delta without a signature is fetched.
            log.warning("the feed has no signature for the delta package %s", delta_name)
            return None
        try:
            path = _fetch(result, delta_name, delta_version, folder)
        except UpdateError:
            # A delta the feed lists and does not hold (_fetch said so in the log): the whole package instead.
            return None
        if not signing.checks_out(delta_sig, path, delta_name):
            log.warning("the delta package %s is not signed by the project", delta_name)
            return None
        fetched.append(path)
    out = os.path.join(folder, name)
    if not _put_together(old, fetched, out, run):
        return None
    if signing.checks_out(sig, out, name):
        # Update.exe wrote the very bytes the release built.
        log.info("the update %s, put together from delta packages, carries the project's signature", name)
        return out
    feed = _feed_sha256(result.info)
    if feed is not None and signing.sha256_of(out) != feed and signing.content_checks_out(sig, out, name):
        log.info("the update %s, put together from delta packages, holds the files the project signed", name)
        return out
    log.warning("the package put together from delta packages is not the one the project signed")
    try:
        # The whole package is fetched under the same name next.
        os.remove(out)
    except OSError:
        pass
    return None


def inside_version(package):
    """The version a package itself gives (its one .nuspec, the file Velopack reads the version to put in from), or
    None for a package with no such file, more than one, or one with no version."""
    try:
        with zipfile.ZipFile(package) as archive:
            specs = [info for info in archive.infolist() if info.filename.endswith(".nuspec")]
            # Velopack takes the first it finds: with two, which one that is depends on the order, so neither counts.
            if len(specs) != 1 or specs[0].file_size > 1 << 20:
                return None
            text = archive.read(specs[0]).decode("utf-8", "replace")
    except (zipfile.BadZipFile, OSError, ValueError, EOFError):
        return None
    found = re.search(r"<version>\s*([^<\s]+)\s*</version>", text)
    return found.group(1) if found else None


def _checked(result, name, deltas, base, folder, tell, run):
    """The update's package in the launcher's own folder, checked: put together from delta packages when the feed has
    them from the version installed, else (or when that did not give the signed package) the whole one, which
    tell("whole") says first. Refused: no signature, a package that is not the signed one, a package whose own
    version is not the one offered."""
    from opendmt3.client import installer
    from opendmt3.core import signing
    # The signature first: without one nothing else is fetched.
    sig = _signature(result.source, name, result.version)
    if sig is None:
        _refuse(result, "the feed has no signature for %s" % name)
    package = None
    if deltas:
        try:
            package = _from_deltas(result, name, deltas, base, sig, folder, run)
        except Exception:  # noqa: BLE001  (whatever went wrong among the deltas: the whole package instead)
            log.exception("the delta packages of %s could not be used", result.version)
        if package is None:
            log.warning("downloading the whole package of %s instead", result.version)
            if tell is not None:
                tell("whole")
    if package is None:
        package = _fetch(result, name, result.version, folder)
        if not signing.checks_out(sig, package, name):
            _refuse(result, "the signature does not check out for %s" % name)
        log.info("the update %s carries the project's signature", name)
    inside = inside_version(package)
    if inside is None or installer.version_key(inside) != installer.version_key(result.version):
        # What Velopack puts in is the version written inside the package, whatever the feed called it.
        _refuse(result, "the package says it is version %s, the feed %s" % (inside, result.version))
    return package


def _leftovers(name):
    """Take away what an earlier update left in packages\\ under the package's name (a package never handed over, a
    copy never finished): nothing under that name is there but what this update checks."""
    for path in (os.path.join(packages_dir(), name), os.path.join(packages_dir(), name + PART)):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as e:
            # In use, or no rights: the checked package is moved over it below, or that move says what is wrong.
            log.warning("could not remove %s, left by an earlier update: %s", path, e)


def _hand_in(package, name):
    """Move a package that checked out into packages\\, where Velopack takes it from. From another drive it is copied
    in under a name Velopack reads as no package, compared with the one checked, and renamed: a package is under its
    own name only whole and checked."""
    from opendmt3.core import signing
    os.makedirs(packages_dir(), exist_ok=True)
    target = os.path.join(packages_dir(), name)
    try:
        os.replace(package, target)
        return
    except OSError:
        # The temporary folder is on another drive than the install folder: a rename cannot cross drives.
        pass
    part = target + PART
    try:
        shutil.copyfile(package, part)
        if signing.sha256_of(part) != signing.sha256_of(package):
            raise OSError("the update's package was not copied whole into %s" % packages_dir())
        os.replace(part, target)
    except OSError:
        # The copy never stays behind: under its own name the package is whole and checked, or it is not there.
        try:
            os.remove(part)
        except OSError:
            pass
        raise


def _refresh_updater(package):
    """Velopack's updater as the checked package carries it (lib/app/Squirrel.exe), over the installed Update.exe: the
    new package is put in by its own updater, as with Velopack's own download, but only from a package that checked
    out. Written beside Update.exe first and renamed over it, so Update.exe is whole at every moment; a failure leaves
    the installed one (it puts the package in as well) and is logged."""
    from opendmt3.client import repair
    entry, target = repair.APP_PREFIX + repair.UPDATER_ENTRY, updater()
    part = target + PART
    try:
        with zipfile.ZipFile(package) as archive:
            carried = [info.filename for info in archive.infolist() if info.filename.endswith(repair.UPDATER_ENTRY)]
            if carried != [entry] or not os.path.isfile(target):
                # A package with no updater of its own (or two), or no Update.exe to replace: left as it is.
                return
            with archive.open(entry) as f, open(part, "wb") as out:
                shutil.copyfileobj(f, out, 1 << 20)
        os.replace(part, target)
    except (OSError, zipfile.BadZipFile, ValueError, EOFError) as e:
        log.warning("Update.exe stays as installed: %s", e)
        try:
            os.remove(part)
        except OSError:
            pass


def apply(result, tell=None, run=subprocess.run):
    """Fetch the update, check it, and hand it to Velopack, which puts it in once this program has ended and then
    starts the new launcher. The caller ends the program right after. tell("whole") is called when the whole package
    is fetched after the delta packages did not give the signed one (the caller says so to the player); `run` starts
    Update.exe (a test gives its own).

    Nothing of the download is in the install folder before it is checked: it is fetched into a folder of the
    launcher's own, checked there, and only then moved into packages\\ (the module's description has the steps).
    Velopack applies it silently: the launcher's own dialog has said what happens, and Velopack's would be a plain
    system window with a progress bar.
    """
    # Before anything is fetched or deleted: plain names, the package named for the version, a newer version.
    name, deltas, base = offered(result)
    manager = _manager(result.source)
    _leftovers(name)
    folder = _own_folder()
    try:
        package = _checked(result, name, deltas, base, folder, tell, run)
        _hand_in(package, name)
    finally:
        # Whatever was fetched and not handed in goes with the folder, checked or not.
        shutil.rmtree(folder, ignore_errors=True)
    _refresh_updater(os.path.join(packages_dir(), name))
    # A note for the next start: Velopack says nothing when a silent update fails, so the new start compares.
    _note_pending(result.version)
    manager.wait_exit_then_apply_updates(result.info, silent=True, restart=True)


def packages_dir():
    """Where Velopack keeps the packages it puts in: packages\\ beside current\\, the folder this program runs
    from in an installed launcher."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(sys.executable))), "packages")


PENDING = "update-pending.json"


def _note_pending(version):
    import json
    from opendmt3 import __version__
    from opendmt3.client import state as st
    os.makedirs(st.config_dir(), exist_ok=True)
    with open(os.path.join(st.config_dir(), PENDING), "w", encoding="utf-8") as f:
        json.dump({"to": version, "from": current_version() or __version__}, f)


def outcome():
    """After an update was handed to Velopack: ("updated", version) or ("not_updated", version, this version),
    once; None when no update was waiting."""
    import json
    from opendmt3 import __version__
    from opendmt3.client import state as st
    path = os.path.join(st.config_dir(), PENDING)
    try:
        with open(path, encoding="utf-8") as f:
            note = json.load(f)
    except (OSError, ValueError):
        return None
    try:
        os.remove(path)
    except OSError:
        pass
    now = current_version() or __version__
    target = str(note.get("to", ""))
    if target and now == target:
        return ("updated", target)
    return ("not_updated", target, now)
