"""The song list, read from a game folder's own files and kept beside the server's database as catalog.json, with each
song's jacket in jackets/ and the DJ cards' tables and pictures (cards.py) beside them. The three together are what a
server takes from the game: the song list (it holds the jackets and the DJ cards too); nothing else of the game.

The server never ships them: whoever runs it reads them from their own game files (the launcher does so for the
server on this PC; a standalone server takes --catalog with a game folder, an archive holding one, or a song list the
launcher saved: sources.py). Without them, pages show song numbers and no jackets. A song's levels are the list's
STAR and POP columns, by pattern.

Each file is read the way the client reads it: from the newest of a family's base and patches that has it
(game.Layers). A reading is written into a folder of its own inside the data folder first and moved into place at
once, part by part, when it is done: the server never shows half of one.

survey() looks at a game folder without saving anything (./dmt3 setup's live check and ./dmt3 catalog's first look);
read() reads it into the data folder and says, part by part, what it read and what is missing. The song list is
needed; the jackets and the DJ cards are not: a part that cannot be read is one plain line (lines()), what still works
said with it, and its traceback goes to catalog.log in the data folder, never to the screen.
"""

import contextlib
import errno
import json
import logging
import os
import shutil
import stat
import tempfile
import time
import traceback

try:
    # The lock that keeps two readings from moving their parts at once; Windows (the launcher's own server, one
    # reading at a time in one process) has none.
    import fcntl
except ImportError:
    fcntl = None

log = logging.getLogger("opendmt3.catalog")

from opendmt3.core import errors
from opendmt3.core import game as g
from opendmt3.core.formats import discstock
from opendmt3.core.formats import pak as P
from opendmt3.server.services import cards, files, pictures

FILE = "catalog.json"
JACKETS = "jackets"
# Jackets are kept at this size (the game's are 256 px and about 230 KB each; a list of 177 would be 40 MB).
JACKET_SIZE = pictures.MOST["jacket"][0]
# Where each song's jacket is in the game's files, by its internal name (its first pattern's picture).
JACKET_PATH = "Resource\\DiscImg\\%s_0.png"
# What the last read found, part by part (the admin's Status page shows it): when, from where, how many, what not.
READ_FILE = "catalog-read.json"
# The tracebacks of the parts that could not be read, for whoever looks into it; kept small, the one before beside it.
LOG_FILE = "catalog.log"
LOG_MOST = 256 * 1024
# The parts, in the order they are read and shown; the optional ones after the song list: the jackets, the DJ cards.
PARTS = ("songs", "jackets", "cards")
OPTIONAL = ("jackets", "cards")
# What still works without each optional part, said with the line that names it missing.
STILL_WORKS = {"jackets": "songs show without them",
               "cards": "every DJ card keeps the basic icon and plate"}
# Each part's name in the lines.
NAMES = {"songs": "song list", "jackets": "jackets", "cards": "DJ cards"}
# What each part is in the data folder: its files and folders, moved into place together.
PLACES = {"songs": (FILE,), "jackets": (JACKETS,), "cards": (cards.FILE, cards.FOLDER)}
# A reading's own folder inside the data folder while it is made (moved from there at once), and how old one left by a
# reading that never finished (the server stopped) is before the next reading removes it.
STAGING = ".song-list-"
STAGING_STALE = 3600
# One reading moves its parts into place at a time, across processes (./dmt3 catalog beside a running server).
LOCK_FILE = ".song-list.lock"


# ------------------------------------------------------------------------------------------- reading

def import_from(game_folder, data_dir):
    """Read the song list, its jackets and the DJ cards into data_dir; returns the number of songs (the launcher's
    server on this PC calls it so). Only the song list is needed: see read()."""
    return read(game_folder, data_dir)["songs"]


def read(game_folder, data_dir, now=None, traces=False):
    """Read the game folder's song list (needed: a game.GameError, pak.PakError or OSError when it cannot be), then
    the jackets and the DJ cards (each may be missing). Returns the report read_report() keeps: when, where from, the
    counts, and {part: why} for each optional part not read. A part not read has its traceback in catalog.log; with
    traces (a running server's own reading, whose log is no one's screen) in this log too."""
    game = g.Game.find(game_folder)
    return read_game(game, data_dir, now=now, traces=traces, source={"from": "folder", "path": game.root})


def read_game(game, data_dir, now=None, traces=False, source=None):
    """read() for a game folder already found (an archive's, taken out to a folder of its own: sources.py). source
    says where it came from, for the report: {"from": "folder" or "archive", "path": ...}."""
    songs = _songs(game)
    os.makedirs(data_dir, exist_ok=True)
    staging = new_staging(data_dir)
    try:
        _write_json(os.path.join(staging, FILE), {"songs": songs}, ensure_ascii=False)
        report = {"at": int(now if now is not None else time.time()), "from": "folder", "path": game.root,
                  "folder": game.root, "songs": len(songs), "jackets": None, "cards": None, "missing": {},
                  "reasons": {}}
        report.update(source or {})
        if report["from"] != "folder":
            # The game folder of an archive is a folder of the reading's own, gone once it is done.
            report["folder"] = None
        for part, reader in (("jackets", lambda: import_jackets(game, songs, staging)),
                             ("cards", lambda: _import_cards(game, staging))):
            try:
                report[part] = reader()
            except Exception as e:  # noqa: BLE001  (an optional part: the list is what matters, pages do without it)
                missing(report, data_dir, part, e, traces)
                # Nothing half read of it goes in: what an earlier reading left stays, as the report says.
                for name in PLACES[part]:
                    remove(os.path.join(staging, name))
        swap_in(staging, data_dir, report)
    finally:
        remove(staging)
    give_to_owner(data_dir)
    return report


def missing(report, data_dir, part, error, traces=False):
    """Note in the report that an optional part was not read, and why (in words and by key), with its traceback in
    the data folder's log (and in this log with traces)."""
    report["missing"][part] = why(error)
    report.setdefault("reasons", {})[part] = getattr(error, "key", None)
    keep_trace(data_dir, NAMES[part], error)
    # On the command line the caller prints the line itself, so the log has it only for --verbose.
    log.log(logging.WARNING if traces else logging.DEBUG, "%s", line(part, report), exc_info=error if traces else None)


def import_cards(game_folder, data_dir):
    """Only the DJ cards' tables and pictures (a song list read by an older openDMT3 lacks them)."""
    return cards.import_from(g.Game.find(game_folder), data_dir)


def _damaged_songs():
    """The song list's files damaged or cut short, as one plain line with the thing to do."""
    return g.GameError("The file with the song list is damaged. Copy the game folder again, or unpack the archive "
                       "again.", "error.game.damaged.songs")


def _songs(game):
    """The song list's rows from the newest of the song list's files that has it, as the client reads it. GameError
    when the game's files have none, or when one of those files is damaged or cut short (a newer list in it would be
    read as an older one); one this reader cannot open (another build's: every file of a whole game folder opens) is
    left out."""
    with game.layers("DiscInfo") as layers:
        if layers.damaged:
            raise _damaged_songs()
        try:
            raw = layers.read(discstock.PATH)
        except P.PakError:
            # The list's own bytes are cut short, or not the game's.
            raise _damaged_songs() from None
    if raw is None:
        raise g.GameError("the game's files have no song list", "error.game.no_song_list")
    try:
        return discstock.parse(raw)
    except (UnicodeError, ValueError) as e:
        # Bytes that are not the game's UTF-16 table (a damaged or half-written file, or an empty one): the list that
        # cannot be read, as every caller already says it, never a traceback out of the server's wizard or the
        # launcher's guide. What the decoder said stays chained to it for the log.
        raise _damaged_songs() from e


def _import_cards(game, data_dir):
    """The card tables and pictures read and saved; {kind: how many pictures} as the saved tables offer them."""
    cards.import_from(game, data_dir)
    with open(os.path.join(data_dir, cards.FILE), encoding="utf-8") as f:
        tables = json.load(f)
    return {kind: len(tables.get(kind, [])) for kind in cards.KINDS}


def import_jackets(game, songs, data_dir):
    """Each song's jacket from the newest of the jackets' files that has it, made smaller and kept in the server's one
    form (pictures.canonical) when Pillow is there, saved as jackets/<number>.png; returns how many. A jacket that does
    not decode is left out (the song shows without it); GameError when the game's files have none, or one that holds
    them is damaged."""
    try:
        layers = game.layers("DiscImg")
    except FileNotFoundError:
        raise g.GameError("the game's files have no jackets", "error.game.no_jackets") from None
    folder = os.path.join(data_dir, JACKETS)
    os.makedirs(folder, exist_ok=True)
    keep = pictures.available()
    saved = 0

    def read():
        # Each song's jacket as the game's files have it, read here one after another (the files are read from one
        # position), song by song.
        for song in songs:
            try:
                data = layers.read(JACKET_PATH % song["name"])
            except P.PakError:
                raise g.GameError("The file with the jackets is damaged. Copy the game folder again, or unpack the "
                                  "archive again.", "error.game.damaged.jackets") from None
            if data is not None:
                yield song, data

    def shrunk(data):
        # Made smaller and put in the one form on a picture thread (pictures.in_order); as it came without Pillow.
        return pictures.canonical(data, "jacket", shrink=True) if keep else data
    with layers:
        if layers.damaged:
            raise g.GameError("The file with the jackets is damaged. Copy the game folder again, or unpack the archive "
                              "again.", "error.game.damaged.jackets")
        # Converted side by side, each handed back in the songs' order: the same files, saved in the same order, as
        # one after another (closing: no picture thread outlives the reading, whatever stops it).
        with contextlib.closing(pictures.in_order(read(), shrunk, None if keep else 1)) as converted:
            for song, data in converted:
                if isinstance(data, pictures.PictureError):
                    log.info("left out the jacket of song %d: it cannot be kept", song["number"])
                    continue
                path = os.path.join(folder, "%d.png" % song["number"])
                # Never through a link left at the name (files.open_new).
                with files.open_new(path + ".new") as f:
                    f.write(data)
                os.replace(path + ".new", path)
                saved += 1
    return saved


# ------------------------------------------------------------------------------------------- moving into place

def new_staging(data_dir):
    """A new folder of a reading's own inside the data folder (the same disk, so its parts move into place at once),
    after removing those a reading left behind when the server stopped mid-way."""
    try:
        for name in os.listdir(data_dir):
            path = os.path.join(data_dir, name)
            if name.startswith(STAGING) and time.time() - os.path.getmtime(path) > STAGING_STALE:
                remove(path)
    except OSError:
        # A look that fails leaves them for the next one.
        pass
    return tempfile.mkdtemp(prefix=STAGING, dir=data_dir)


def swap_in(staging, data_dir, report):
    """Move the parts read (the song list always; the jackets and the DJ cards when they were read) from the reading's
    folder into the data folder, each replacing the one before whole, and the report with them, last: the pictures'
    folders first, then the tables and the list, so a page never names a picture that is not there yet. A part not
    read leaves the one before in place. Each one before steps aside into the reading's own folder first, files as
    folders, so a failure anywhere (a move, the report) puts every one back: the server is as it was. One reading moves
    its parts at a time."""
    done = [part for part in PARTS if part not in report.get("missing", {})]
    with _locked(data_dir):
        old = os.path.join(staging, ".before")
        os.makedirs(old, exist_ok=True)
        # The report written beside the parts first: it goes in with them, or not at all.
        _save_report(staging, report)
        # Folders (jackets/, cards/) before files (catalog.json, cards.json), then the report.
        names = sorted((n for part in done for n in PLACES[part]), key=lambda n: n.endswith(".json")) + [READ_FILE]
        aside, moved = set(), set()
        try:
            for name in names:
                new, target = os.path.join(staging, name), os.path.join(data_dir, name)
                if not os.path.lexists(new):
                    continue
                if os.path.lexists(target):
                    # The one before steps aside, into the reading's own folder (which goes with it), so it can come
                    # back whole: a folder cannot replace another in one step, and a file replaced is gone.
                    os.replace(target, os.path.join(old, name))
                    aside.add(name)
                os.replace(new, target)
                moved.add(name)
        except BaseException:
            # Every one as it was, the last moved first: the new one out, the one before back.
            for name in reversed(names):
                target = os.path.join(data_dir, name)
                try:
                    if name in moved:
                        remove(target)
                    if name in aside:
                        os.replace(os.path.join(old, name), target)
                except OSError:
                    # One that cannot come back stops none of the others.
                    log.warning("could not put %s back as it was", target, exc_info=True)
            raise


class _locked:
    """An exclusive lock on the data folder's lock file while parts move into place (a no-op where there is none)."""

    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, LOCK_FILE)
        self.fd = None

    def __enter__(self):
        if fcntl is None:
            return self
        try:
            # Never through a link left at its name.
            self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
            fcntl.flock(self.fd, fcntl.LOCK_EX)
        except OSError:
            # A data folder that takes no lock (a network share, a link at its name): the move goes on without one.
            if self.fd is not None:
                os.close(self.fd)
            self.fd = None
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            os.close(self.fd)


def remove(path):
    """Remove a file or a folder (and all in it); one already gone is fine."""
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
    except FileNotFoundError:
        pass


def _write_json(path, data, **kwargs):
    """A JSON file written whole or not at all, never through a link left at its name (files.open_new)."""
    with files.open_new(path + ".new", text=True) as f:
        json.dump(data, f, **kwargs)
    os.replace(path + ".new", path)


# ------------------------------------------------------------------------------------------- looking first

def survey(game_folder):
    """What read() would find in a folder, without saving anything: the game folder found (or None), whether a client
    this server can open the game's files with is there and what it is, the number of songs, of jackets and of the DJ
    cards' pictures by kind, {part: why} for the optional parts that are not there, and the one problem that stops the
    song list (None when there is none). Fast enough to run as a person types a path (half a second on a whole game
    folder)."""
    found = {"kind": "folder", "folder": None, "client": False, "client_kind": None, "songs": None, "jackets": None,
             "cards": None, "missing": {}, "reasons": {}, "problem": None, "problem_key": None}
    try:
        game = g.Game.find(game_folder)
    except (g.GameError, OSError):
        # Nothing that looks like a game folder at or below the path (or a path that cannot be listed).
        return _problem(found, NOTHING_KEY)
    found["folder"] = game.root
    try:
        game.table()
        found["client"] = True
        # What the client is (none said when the table came from elsewhere: a test's made-up one).
        found["client_kind"] = game.client[1] if game.client else None
    except g.GameError as e:
        # The cabinet's client, or none that opens the game's files: nothing more can be looked at.
        return _problem(found, e.key, errors.say(e))
    except OSError as e:
        return _problem(found, "error.game.permission", why(e))
    try:
        songs = _songs(game)
    except (g.GameError, P.PakError, OSError) as e:
        return _problem(found, getattr(e, "key", None), why(e))
    found["songs"] = len(songs)
    try:
        with game.layers("DiscImg") as layers:
            if layers.damaged:
                raise g.GameError("The file with the jackets is damaged. Copy the game folder again, or unpack the "
                                  "archive again.", "error.game.damaged.jackets")
            names = layers.names()
        found["jackets"] = sum((JACKET_PATH % s["name"]).lower() in names for s in songs)
    except Exception as e:  # noqa: BLE001  (said as a missing part, as read() would)
        found["missing"]["jackets"], found["reasons"]["jackets"] = why(e), getattr(e, "key", None)
    try:
        found["cards"] = cards.survey(game)
    except Exception as e:  # noqa: BLE001  (said as a missing part, as read() would)
        found["missing"]["cards"], found["reasons"]["cards"] = why(e), getattr(e, "key", None)
    return found


# The words of a path that is no game folder (sources.py raises them as its own: a path may also be an archive).
NOTHING_KEY = "error.source.nothing"


def _problem(found, key, text=None):
    """The survey with its one problem: the words given, or those of the key."""
    found["problem"] = text or errors.TEXT[key][0]
    found["problem_key"] = key
    return found


# ------------------------------------------------------------------------------------------- the words

def why(error):
    """A plain reason for an error, without a traceback, as a sentence: what is missing or what stopped the reading.
    Errors with words of their own (errors.py) say them."""
    if isinstance(error, FileNotFoundError) or (isinstance(error, OSError) and error.errno == errno.ENOENT):
        return errors.say(g.GameError("the game folder has no file this part is in", "error.game.no_file"))
    if isinstance(error, PermissionError):
        return errors.say(g.GameError("the game's files cannot be read by this user", "error.game.permission"))
    if isinstance(error, errors.Worded):
        # These carry their own sentence (errors.py).
        return errors.say(error)
    if isinstance(error, P.PakError):
        # A file of the game's damaged or cut short, the part unknown here.
        return errors.say(g.GameError("One of the game's files is damaged. Copy the game folder again, or unpack the "
                                      "archive again.", "error.game.damaged"))
    if isinstance(error, OSError) and error.strerror:
        # By its kind and the system's words alone: its paths are the server's own (the API says this to its caller).
        return "%s: %s" % (type(error).__name__, error.strerror)
    # Anything else by its kind and its first line.
    text = str(error).strip().splitlines()
    return "%s%s" % (type(error).__name__, ": " + text[0][:120] if text else "")


def line(part, report):
    """One part of a survey or a read as one plain line."""
    if part in report.get("missing", {}):
        # The part, its state, what still works, and why it is not there with the one thing to do.
        return "%s: not yet, %s. %s" % (NAMES[part], STILL_WORKS[part], report["missing"][part])
    count = report.get(part)
    if part == "songs":
        return "song list: %d songs" % count
    if part == "jackets":
        return "jackets: %d of %d songs" % (count, report["songs"])
    # The DJ cards' pictures by kind, in the card's own order.
    return "DJ cards: %d icons, %d plates, %d patterns" % tuple(count.get(k, 0) for k in cards.KINDS)


def lines(report):
    """A survey or a read as plain lines, each (ok, text): the problem alone when there is one, else every part."""
    if report.get("problem"):
        return [(False, report["problem"])]
    out = [(True, line("songs", report))]
    for part in OPTIONAL:
        out.append((part not in report["missing"], line(part, report)))
    return out


# ------------------------------------------------------------------------------------------- what is kept

def keep_trace(data_dir, what, error):
    """Append an error's traceback to catalog.log in the data folder (made when missing), the file kept under
    LOG_MOST bytes: a full one becomes catalog.log.1, replacing the one before. Run as root in a data folder someone
    else owns, it is written as that owner alone (as_user)."""
    text = "%s %s could not be read\n%s" % (time.strftime("%Y-%m-%d %H:%M:%S"), what,
                                           "".join(traceback.format_exception(type(error), error, error.__traceback__)))
    writer = writer_for(data_dir)
    try:
        if writer is None:
            _append_log(data_dir, text)
        else:
            as_user(writer, lambda: _append_log(data_dir, text))
    except OSError:
        # A data folder that cannot be written fails the reading itself; the trace is not worth a second error.
        log.debug("could not write %s", os.path.join(data_dir, LOG_FILE), exc_info=True)


def _append_log(data_dir, text):
    """Text added to the end of catalog.log in the data folder (the one before kept as catalog.log.1 past LOG_MOST),
    never through a link at its name and never into a file another name shares (a hard link to someone's file)."""
    path = os.path.join(data_dir, LOG_FILE)
    os.makedirs(data_dir, exist_ok=True)
    try:
        st = os.lstat(path)
        if stat.S_ISREG(st.st_mode) and st.st_size > LOG_MOST:
            # A full log goes aside whole (a rename moves a link itself, never what it leads to).
            os.replace(path, path + ".1")
    except FileNotFoundError:
        pass
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_BINARY", 0), 0o666)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise OSError("%s is not a log of its own" % LOG_FILE)
        f.write(text)


def _save_report(data_dir, report):
    """The last read's report, beside the list, written whole or not at all."""
    _write_json(os.path.join(data_dir, READ_FILE), report)


def read_report(data_dir):
    """The last read's report (read()), or None before one was kept (a list read by an older openDMT3)."""
    try:
        with open(os.path.join(data_dir, READ_FILE), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def give_to_owner(data_dir):
    """When run as root in a data folder someone else owns, what a reading wrote there goes to that owner, so the
    server can read and replace it later. The server's own command line never writes such a folder as root (read_as);
    this is for any other caller. Never through a link: a name this module writes that is a link is passed by, with
    what it leads to, and the folders are walked by handle (os.fwalk), so one swapped for a link meanwhile is not
    entered."""
    owner = writer_for(data_dir)
    if owner is None:
        # Not root (or not a system with owners), or root's own folder: what was written is the writer's already.
        return
    # Each file and folder this module and cards.py write, and everything in the folders.
    for name in (FILE, READ_FILE, LOG_FILE, LOG_FILE + ".1", LOCK_FILE, cards.FILE, JACKETS, cards.FOLDER):
        top = os.path.join(data_dir, name)
        try:
            kind = os.lstat(top).st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(kind):
            # Not what this module wrote: neither the link nor what it leads to changes hands.
            continue
        os.chown(top, owner[0], owner[1], follow_symlinks=False)
        if stat.S_ISDIR(kind):
            for _, dirs, names, folder in os.fwalk(top, follow_symlinks=False):
                for entry in dirs + names:
                    # By the folder's handle and the entry's own name: a link in it is the link alone.
                    os.chown(entry, owner[0], owner[1], dir_fd=folder, follow_symlinks=False)


# ------------------------------------------------------------------------------------------- root and its folders

def writer_for(folder):
    """(uid, gid) of the user this process writes `folder` as: its owner (or the owner of the nearest folder above it
    that is there) when this process runs as root and the folder is someone else's; None when it writes as itself
    (not root, a folder of root's own, or a system without owners)."""
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        return None
    here = os.path.abspath(folder)
    while True:
        try:
            st = os.stat(here)
            break
        except FileNotFoundError:
            up = os.path.dirname(here)
            if up == here:
                return None
            here = up
    return None if st.st_uid == 0 else (st.st_uid, st.st_gid)


def as_user(user, work):
    """work() in a child process that is `user` (uid, gid) alone, for good: root hands a folder of someone else's back
    to its owner's own hands, so whatever it writes there is theirs and goes only where they may write, wherever a
    link of theirs leads. Returns once it ended; OSError with its reason when work() failed. The child uses what this
    process has loaded already (the owner may not read the program's own folder)."""
    reading, writing = os.pipe()
    pid = os.fork()
    if pid == 0:
        # The child: never back into the caller's code, whatever happens.
        code = 1
        try:
            os.close(reading)
            # Root's groups first (only root may set them), then the group, then the user: no way back.
            os.setgroups([])
            os.setgid(user[1])
            os.setuid(user[0])
            work()
            code = 0
        except BaseException as e:  # noqa: BLE001  (said to the parent in one line, never raised here)
            try:
                os.write(writing, why(e).encode("utf-8", "replace")[:4000])
            except BaseException:  # noqa: BLE001
                pass
        finally:
            os._exit(code)
    os.close(writing)
    with os.fdopen(reading, "rb") as f:
        said = f.read().decode("utf-8", "replace")
    _, status = os.waitpid(pid, 0)
    if os.waitstatus_to_exitcode(status) != 0:
        raise OSError(said or "the data folder could not be written as its owner")


def read_as(user, data_dir, reading):
    """A reading as root into a data folder someone else owns (in Docker: a game folder only root may read, into the
    server's volume): reading(folder) reads the song list into a folder of root's own outside the data folder, where
    nobody else leaves a link; then a child process that is the data folder's owner alone (as_user) moves the parts
    into place with the report, and adds what the reading's log says to the data folder's. Returns the report;
    raises what the reading raised, and nothing in the data folder changed."""
    private = tempfile.mkdtemp(prefix="openDMT3-reading-")
    try:
        into = os.path.join(private, "data")
        report = reading(into)
        # What was read, in memory (the song list, the pictures and the tables: about 16 MB of a whole game folder),
        # so the owner never needs to enter root's own folder.
        parts = {}
        for name in PLACES["songs"] + PLACES["jackets"] + PLACES["cards"]:
            _keep(os.path.join(into, name), name, parts)
        logged = {}
        _keep(os.path.join(into, LOG_FILE), LOG_FILE, logged)
    finally:
        remove(private)
    trace = logged.get(LOG_FILE, b"").decode("utf-8", "replace")
    as_user(user, lambda: _write_parts(data_dir, parts, report, trace))
    return report


def save_as(user, out_path, saving):
    """A song list saved as root into a folder someone else owns: saving(file, folder) saves it into a folder of root's
    own, then a child process that is that folder's owner alone puts it at out_path, never through a link at its name.
    Returns what saving returned."""
    private = tempfile.mkdtemp(prefix="openDMT3-saving-")
    try:
        made = os.path.join(private, os.path.basename(out_path))
        result = saving(made, private)
        with open(made, "rb") as f:
            data = f.read()
    finally:
        remove(private)

    def write():
        with files.open_new(out_path + ".new") as f:
            f.write(data)
        os.replace(out_path + ".new", out_path)
    as_user(user, write)
    return result


def _keep(path, name, parts):
    """A file or a folder of root's own reading kept in `parts`, by its path relative to the data folder: a file's
    bytes, a folder as None (it is made even when empty); anything else is left out."""
    try:
        kind = os.lstat(path).st_mode
    except FileNotFoundError:
        return
    if stat.S_ISREG(kind):
        with open(path, "rb") as f:
            parts[name] = f.read()
    elif stat.S_ISDIR(kind):
        parts[name] = None
        for entry in sorted(os.listdir(path)):
            _keep(os.path.join(path, entry), name + "/" + entry, parts)


def _write_parts(data_dir, parts, report, trace):
    """As the data folder's owner (as_user): the parts read into a new folder of the reading's own in the data folder,
    moved into place with the report (swap_in), then the reading's log added to the data folder's."""
    os.makedirs(data_dir, exist_ok=True)
    staging = new_staging(data_dir)
    try:
        # Folders before the files in them (a folder's name sorts before its files').
        for name in sorted(parts):
            target = os.path.join(staging, *name.split("/"))
            if parts[name] is None:
                os.makedirs(target, exist_ok=True)
                continue
            with files.open_new(target) as f:
                f.write(parts[name])
        swap_in(staging, data_dir, report)
    finally:
        remove(staging)
    if trace:
        try:
            _append_log(data_dir, trace)
        except OSError:
            # The parts are in; a log that cannot be written (a link at its name) is not worth failing them for.
            log.debug("could not add to %s", os.path.join(data_dir, LOG_FILE), exc_info=True)


# ------------------------------------------------------------------------------------------- what pages use

def jacket_path(data_dir, number):
    """A song's saved jacket, or None."""
    path = os.path.join(data_dir, JACKETS, "%d.png" % number)
    return path if os.path.isfile(path) else None


def level(catalog, number, mode, pattern):
    """A chart's level from the list (STAR's column for mode 0, POP's for POP and CLUB), or None."""
    song = catalog.get(number)
    column = "star" if mode == 0 else "pop" if mode in (1, 2) else None
    if not song or column is None or not 1 <= pattern <= len(song.get(column, [])):
        return None
    return song[column][pattern - 1] or None


def load(data_dir):
    """{song number: song} from the saved list, or {} when there is none. Read once and kept while the file stays
    the same (files.py): the answer is shared, so it cannot be changed (dict() of it can)."""
    return files.load(os.path.join(data_dir, FILE), lambda data: {s["number"]: s for s in data.get("songs", [])},
                      missing=files.FrozenDict())


def title(catalog, number):
    """A song's title for pages: its name from the list, else its number."""
    song = catalog.get(number)
    return song["title"] if song and song.get("title") else "#%d" % number


def state(data_dir):
    """The song list as the admin's Status page shows it: for the list, the jackets and the DJ cards' pictures, how
    many there are and when they were last written (None before any), with why each missing part was not read the last
    time (from read_report, when there is one, by its words and its key), and where the last reading came from."""
    report = read_report(data_dir) or {}
    songs = load(data_dir)
    out = {"songs": {"count": len(songs), "at": _mtime(os.path.join(data_dir, FILE)) if songs else None}}
    folder = os.path.join(data_dir, JACKETS)
    try:
        jackets = [n for n in os.listdir(folder) if n.endswith(".png")]
    except OSError:
        jackets = []
    # A folder's time changes as each jacket is put in it: it is the last time any was.
    out["jackets"] = {"count": len(jackets), "at": _mtime(folder) if jackets else None}
    tables = cards.load(data_dir)
    counts = {kind: len(tables.get(kind, [])) for kind in cards.KINDS}
    out["cards"] = {"count": counts, "at": _mtime(os.path.join(data_dir, cards.FILE)) if tables else None}
    # Each part with nothing in it, or not read the last time (what an earlier read left is kept and still shown),
    # with the last read's reason when there is one (None: never read).
    kept = report.get("missing") or {}
    keys = report.get("reasons") or {}
    out["missing"] = [{"part": part, "why": kept.get(part), "key": keys.get(part)} for part in PARTS
                      if not out[part]["at"] or part in kept]
    out["read_at"] = report.get("at")
    # Where the last reading came from: a game folder, an archive holding one, or a song list the launcher saved.
    out["source"] = {"from": report.get("from", "folder" if report else None), "path": report.get("path"),
                     "made": report.get("made")} if report else None
    return out


def _mtime(path):
    """A file's or a folder's last change in whole seconds, or None when it is not there."""
    try:
        return int(os.path.getmtime(path))
    except OSError:
        return None
