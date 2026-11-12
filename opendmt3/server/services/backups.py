"""Backups of the server's database: one a day kept for a week, one whenever the owner asks, one before a restore,
one before plays are reset, and the database files the admin uploads.

A backup is SQLite's own copy of the database at one moment (the part still in the write-ahead log included, which
a file copy would miss), written as openDMT3-<date>-<time>-<kind>.sqlite in the data folder's backups/ and moved
into place only when complete. The newest KEEP of each kind stay; older ones are removed as new ones come.
A restore first backs up the database as it is, then copies the backup over it and brings it up to this
openDMT3's version, so a restore can itself be undone.

An upload is written to a file of its own in backups/ whose name the list never shows (upload_part), then checked
(keep_upload): an SQLite file whose integrity check passes, with this project's tables at a version this openDMT3
opens. Only then does it get a backup's name; anything else is refused and its file removed.
"""

import asyncio
import logging
import os
import pathlib
import re
import sqlite3
import tempfile
import threading
import time

from opendmt3.server import db
from opendmt3.core.errors import Worded
from opendmt3.server.services import records

log = logging.getLogger("opendmt3.backups")

# How many of each kind stay (a week of daily ones).
KEEP = 7
# How old the newest daily backup may be before the next is made.
DAY = 86400
# daily: made by the server once a day; manual: asked for; restore: made right before a restore; reset: made right
# before the admin resets plays; upload: a database file the admin brought from elsewhere (upload_part, keep_upload).
KINDS = ("daily", "manual", "restore", "reset", "upload")
NAME = re.compile(r"^openDMT3-(\d{8})-(\d{6})-(daily|manual|restore|reset|upload)\.sqlite$")
# Every change to the backups' folder (a backup made, an upload kept, a restore, a backup deleted, the oldest removed)
# runs one at a time in this process: the site's threads, its long work's and the day's backup may ask at once, and
# two backups of the same second took the same name (_free_name) and wrote the same file ("disk I/O error", or one
# lost). Re-entrant: a restore makes a backup first, and both prune.
_folder_lock = threading.RLock()


def changing():
    """The backups' folder held for one change of the caller's (a `with` block), before anything else is held: a
    restore or a reset takes it first, then holds the game server, so a backup being made meanwhile finishes before
    the game server waits."""
    return _folder_lock


class BackupError(Worded):
    """A backup that cannot be found or used, worded for the owner (errors.py)."""


def folder(data_dir):
    return os.path.join(data_dir, "backups")


def all_backups(data_dir):
    """Every backup, newest first: name, kind, when it was made (seconds) and its size in bytes."""
    found = []
    where = folder(data_dir)
    if not os.path.isdir(where):
        return found
    for name in os.listdir(where):
        match = NAME.match(name)
        if not match:
            continue
        made = time.mktime(time.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S"))
        try:
            size = os.path.getsize(os.path.join(where, name))
        except FileNotFoundError:
            # Removed since the folder was listed (pruned, deleted, put back): not one any more.
            continue
        found.append({"name": name, "kind": match.group(3), "at": int(made), "size": size})
    # Newest first; the name breaks ties (two kinds in the same second).
    return sorted(found, key=lambda b: (b["at"], b["name"]), reverse=True)


def make(db_path, data_dir, kind="manual", now=None, tidy=True):
    """Back the database up now; returns the backup's name. tidy=False leaves the old ones for the caller to prune
    (a restore must not lose the backup it is about to read)."""
    if kind not in KINDS:
        raise ValueError(kind)
    with _folder_lock:
        # Its name chosen and its file written before any other change to the folder (_folder_lock).
        where = folder(data_dir)
        os.makedirs(where, exist_ok=True)
        name = _free_name(where, kind, now)
        partial = os.path.join(where, name + ".part")
        source = sqlite3.connect(db_path)
        try:
            copy = sqlite3.connect(partial)
            try:
                source.backup(copy)
            finally:
                copy.close()
        finally:
            source.close()
        # A copy holds the card numbers too: its owner's alone, like the database.
        os.chmod(partial, 0o600)
        # Only a complete copy gets the name the list looks for.
        os.replace(partial, os.path.join(where, name))
        log.info("backed up the database as %s", name)
        if tidy:
            prune(data_dir)
        return name


def _free_name(where, kind, now=None):
    """A backup's name for a backup of `kind` made now (or at `now`) that no file in `where` has yet: a second later
    for each one already there, so two in the same second each get their own."""
    moment = int(now if now is not None else time.time())
    while True:
        name = "openDMT3-%s-%s.sqlite" % (time.strftime("%Y%m%d-%H%M%S", time.localtime(moment)), kind)
        if not os.path.exists(os.path.join(where, name)):
            return name
        moment += 1


def prune(data_dir):
    """Remove all but the newest KEEP of each kind; returns the names removed."""
    removed = []
    with _folder_lock:
        for kind in KINDS:
            for old in [b for b in all_backups(data_dir) if b["kind"] == kind][KEEP:]:
                try:
                    os.remove(os.path.join(folder(data_dir), old["name"]))
                except FileNotFoundError:
                    # Removed meanwhile by another process (the command line's --backup beside a running server).
                    continue
                removed.append(old["name"])
    return removed


def daily(db_path, data_dir, now=None):
    """Make the day's backup when the newest daily one is a day old (or there is none); its name, or None."""
    now = now if now is not None else time.time()
    with _folder_lock:
        # The newest daily one looked at and the next made with no other change between.
        days = [b for b in all_backups(data_dir) if b["kind"] == "daily"]
        if days and now - days[0]["at"] < DAY:
            return None
        if not os.path.isfile(db_path):
            return None
        return make(db_path, data_dir, "daily", now)


async def keep_daily(db_path, data_dir, every=3600):
    """Check once an hour whether the day's backup is due, so a server that runs for weeks keeps one a day."""
    while True:
        try:
            # The copy reads the whole file: off the loop, so games and pages are not held up.
            await asyncio.get_running_loop().run_in_executor(None, daily, db_path, data_dir)
        except Exception:  # noqa: BLE001  (a failed backup is logged; the server goes on)
            log.exception("the daily backup failed")
        await asyncio.sleep(every)


def path_of(data_dir, name):
    """The file of a backup named in a request; BackupError for any other name (never a path outside backups/)."""
    if not NAME.match(name or "") or not os.path.isfile(os.path.join(folder(data_dir), name)):
        raise BackupError("no backup named %s" % name, "error.backup.unknown", name=name)
    return os.path.join(folder(data_dir), name)


def delete(data_dir, name):
    """Remove one backup (the admin's choice); BackupError for any name that is not a backup in backups/."""
    with _folder_lock:
        # Not while a restore reads it or another request deletes it.
        path = path_of(data_dir, name)
        os.remove(path)
    log.info("deleted the backup %s", name)


def restore(db_path, data_dir, name):
    """Put the database back to a backup; the database as it was is backed up first. Returns that backup's name."""
    with _folder_lock:
        # The backup it reads is not deleted or pruned meanwhile, and two restores go one after the other.
        path = path_of(data_dir, name)
        probe = sqlite3.connect(path)
        try:
            version = probe.execute("PRAGMA user_version").fetchone()[0]
        finally:
            probe.close()
        if version > db.VERSION:
            raise BackupError("%s is from a newer openDMT3" % name, "error.backup.newer", name=name)
        safety = make(db_path, data_dir, "restore", tidy=False)
        source = sqlite3.connect(path)
        try:
            target = sqlite3.connect(db_path)
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
        # A backup from before an upgrade is brought up to this version, as an old database is on open.
        db.connect(db_path).close()
        # Everything the site's lists were made of may differ now (records.changed: they are made again).
        records.changed()
        # Only now: the oldest backup of a kind may be the one just restored.
        prune(data_dir)
        log.info("restored the database from %s (it was kept as %s)", name, safety)
        return safety


# ------------------------------------------------------------------------------------------- uploads

# The most an uploaded backup may be, in bytes: a small server has a database of a few megabytes.
UPLOAD_MOST = 256 * 1024 * 1024
# What every SQLite database file starts with (its header's first 16 bytes).
SQLITE_HEADER = b"SQLite format 3\x00"
# An upload's file while it comes and is checked: in backups/, under a name the list never shows (NAME does not match).
UPLOAD_PREFIX, UPLOAD_SUFFIX = ".upload-", ".part"
# The file of an upload a stopped server never finished is removed by the next upload, once it is this old.
UPLOAD_STALE = DAY


def too_large():
    """The refusal of an upload past UPLOAD_MOST, in megabytes (the page and the API both raise it)."""
    mb = UPLOAD_MOST >> 20
    return BackupError("an uploaded backup is at most %d MB" % mb, "error.backup.too_large", mb=mb)


def no_file():
    """The refusal of an upload that brought no file (an empty one, or a form without its file)."""
    return BackupError("no database file came with the upload", "error.backup.no_file")


def upload_part(data_dir, now=None):
    """A new, empty file in backups/ for an upload to be written into, and its path: (the file open for writing in
    binary, the path). It is readable by its owner only from the start (mkstemp), as a backup holds card numbers.
    The files of uploads that never ended (older than UPLOAD_STALE: the server stopped while one came) go first."""
    where = folder(data_dir)
    os.makedirs(where, exist_ok=True)
    now = now if now is not None else time.time()
    for name in os.listdir(where):
        if name.startswith(UPLOAD_PREFIX) and name.endswith(UPLOAD_SUFFIX):
            path = os.path.join(where, name)
            try:
                if now - os.path.getmtime(path) > UPLOAD_STALE:
                    os.remove(path)
            except OSError:
                # Gone meanwhile (another upload's, ended): nothing to remove.
                pass
    fd, path = tempfile.mkstemp(prefix=UPLOAD_PREFIX, suffix=UPLOAD_SUFFIX, dir=where)
    return os.fdopen(fd, "wb"), path


def check_upload(path):
    """Refuse (BackupError) a file that cannot be a backup of this server: not an SQLite file, one whose integrity
    check fails, one without this project's tables (exactly those its version has, and no views or triggers, which
    this project never makes), or one from a newer openDMT3. Returns its database version.

    The file is opened read-only and as immutable (nothing locks it or makes a journal beside it), with the schema
    not trusted: nothing in a file from elsewhere runs while it is read."""
    with open(path, "rb") as f:
        head = f.read(len(SQLITE_HEADER))
    if head != SQLITE_HEADER:
        raise BackupError("the file is not an SQLite database", "error.backup.not_sqlite")
    # The file's own URI, so a folder with any character in its name opens (as_uri quotes them).
    connection = sqlite3.connect(pathlib.Path(path).resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        try:
            # Functions in the schema (a check, an index on an expression) do not run as the file is read.
            connection.execute("PRAGMA trusted_schema = OFF")
            result = connection.execute("PRAGMA integrity_check").fetchall()
        except sqlite3.DatabaseError:
            # Not readable as a database at all past its header ("file is not a database").
            result = None
        if result != [("ok",)]:
            raise BackupError("the file is damaged (SQLite's integrity check did not pass)", "error.backup.damaged")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > db.VERSION:
            raise BackupError("the file is from a newer openDMT3 (database version %d; this server opens up to %d)"
                              % (version, db.VERSION), "error.backup.too_new", version=version, most=db.VERSION)
        others = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type IN ('view', 'trigger')").fetchone()[0]
        # Version 0 is no openDMT3 database (an empty file, another program's); any other has exactly its steps' tables.
        if version < 1 or others or db.schema_of(connection) != db.schema(version):
            raise BackupError("the file is not an openDMT3 database: its tables are not this project's",
                              "error.backup.not_ours")
        return version
    finally:
        connection.close()


def keep_upload(data_dir, part, now=None):
    """An upload's file (upload_part), checked (check_upload), kept as a backup of the kind "upload" named after the
    moment it came; returns its name. A file refused, or anything else going wrong, takes the file with it."""
    try:
        check_upload(part)
        with _folder_lock:
            # Checked first (the long part), then named and put in place with no other change between.
            where = folder(data_dir)
            name = _free_name(where, "upload", now)
            # Its owner's alone, as every backup is, before it gets the name the list shows.
            os.chmod(part, 0o600)
            os.replace(part, os.path.join(where, name))
    except BaseException:
        # Refused or failed: nothing of it stays.
        discard(part)
        raise
    log.info("kept an uploaded backup as %s", name)
    prune(data_dir)
    return name


def discard(part):
    """Remove an upload's file (refused, cut short or failed); one gone already is fine."""
    try:
        os.remove(part)
    except FileNotFoundError:
        pass
