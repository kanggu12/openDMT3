"""What a path a player brings is, to the launcher: a game folder, an archive holding one, part of one, or nothing of
the game's, judged by its content before anything changes (as OpenDMTQ's inspect judges a client).

inspect(path) answers with a Found: the state its card shows (ready, unpack to play, does not work here), what it
holds (the PC client, songs, jackets...), the one problem with the one thing to do, and what can be done with it
(choose it, unpack it, put back what an earlier openDMT3 changed in it). The first-start guide's DISC CHECK, the Game
page's card, --find and --inspect all say what inspect says, so a path reads the same everywhere.

The server's reading of a path does the work underneath (server/services/sources.py and catalog.py, which the launcher
may use: it hosts the server on this PC): game folders by content in any letter case, the client's kind, the song list
through the layers of the game's files, archives listed by the official 7-Zip, and the worded lines of what stops a
path (core/errors.py). The launcher adds what only a player's PC has: the room to unpack into, files kept only in
OneDrive's cloud, the files an earlier openDMT3 changed in the folder, and whether the cabinet's operator data comes
along. PLAY only reads a game folder (core/cabinet/steps.py), so a folder in Program Files, on a disc or on a drive
mounted read only plays as any other.
"""

import logging
import os
import shutil
import threading

from opendmt3.core import errors
from opendmt3.core import game as g

log = logging.getLogger("opendmt3.launcher")

# The states a card shows, by what can be done with the path: play from it, unpack it first, nothing here (the line
# says why), not chosen yet (the Game page with no folder), or still being looked at.
READY, UNPACK, NOT_HERE, NOT_YET, CHECKING = "ready", "unpack", "not_here", "not_yet", "checking"
# What the path is: a game folder (at the path or below it), an archive (whole, or a split one by its first part).
FOLDER, ARCHIVE = "folder", "archive"
# The tones of a card's line: a problem (the error colour) or a plain note (the hint colour).
PROBLEM, NOTE = "problem", "note"
# What a card offers: picking the folder, unpacking the archive, putting back what openDMT3 changed in the folder.
CHOOSE, UNPACK_IT, PUT_BACK = "choose", "unpack", "put_back"
# Room kept free beside an unpacked game folder: Windows and the game itself need some (the game writes its logs).
SPARE = 256 << 20
# How long a test of one file may take before a password counts as the archive's: a password that is not the
# archive's fails in the first bytes, while a right one may go on through a long solid block.
PASSWORD_SECONDS = 5


def said(key, **values):
    """One of the worded lines (core/errors.py) as an error that says itself in either language."""
    return errors.Worded(errors.TEXT[key][0].format(**values), key, **values)


class Found:
    """One path as the launcher sees it (inspect). Words are kept as keys with their values, so the guide, the Game
    page and the command line each say them in their own language; a line from the reading underneath keeps its own
    words (core/errors.py)."""

    def __init__(self, path, kind=None, state=CHECKING):
        self.path = path                # what the card names: the game folder, or the archive (its first part)
        self.kind = kind                # FOLDER, ARCHIVE, or None for nothing of the game's
        self.state = state              # READY, UNPACK, NOT_HERE, NOT_YET or CHECKING
        self.facts = []                 # what it holds, short: [(key, values)]
        self.line = None                # the one problem or note: (key, values), or an error with words of its own
        self.tone = PROBLEM             # how the line is coloured
        self.actions = []               # CHOOSE, UNPACK_IT, PUT_BACK
        self.root = None                # a game folder's own path (the path, or the folder found below it)
        self.client = None              # the client's kind: g.ORIGINAL, g.FIXED, g.MODIFIED (or None)
        self.songs = None               # songs the game offers in any mode (core/charts.py; None: not counted)
        self.jackets = None             # how many of them have their jacket
        self.changed = 0                # game files openDMT3 changed in the folder (Put back undoes them)
        self.size = None                # an archive: what its game folder holds, in bytes
        self.needed = None              # an archive: the room unpacking it takes (its size and a little more)
        self.free = None                # an archive: the free room beside it, in bytes
        self.parts = 0                  # a split archive: its parts present
        self.inner = False              # an archive: the game is in an archive inside it
        self.password = False           # an archive: it has a password (asked for before unpacking)
        self.inside = None              # an archive: the game folder's path inside it ("" at its top)

    # ------------------------------------------------------------------------------------------------ words

    def fact_words(self, w):
        """What it holds, in w's language: ["original PC client", "177 songs", ...]."""
        return [w(key, **values) for key, values in self.facts]

    def line_words(self, w):
        """The one problem or note in w's language, or None."""
        if self.line is None:
            return None
        if isinstance(self.line, Exception):
            # A line from the reading underneath says itself (core/errors.py), in the reader's language.
            return w.error(self.line)
        key, values = self.line
        return w(key, **values)

    def sentence(self, w):
        """The path in one plain line, as --inspect and --find print it: what it is and what it holds, then its
        state; a path that does not work here says the one problem and the one thing to do."""
        if self.state == NOT_HERE:
            return self.line_words(w) or w("intake.said." + self.state)
        # The room an archive needs goes after its state, in brackets, as the design's line has it.
        facts = [(k, v) for k, v in self.facts if k != "intake.space"]
        room = [w(k, **v) for k, v in self.facts if k == "intake.space"]
        what = ([w("intake.kind." + self.kind)] if self.kind else []) + [w(k, **v) for k, v in facts]
        state = w("intake.said." + self.state) + ("(%s)" % room[0] if room and w.language == "ko" else
                                                   " (%s)" % room[0] if room else "")
        text = "%s: %s" % (", ".join(what), state) if what else state
        line = self.line_words(w)
        return "%s. %s" % (text, line) if line else text


# --------------------------------------------------------------------------------------------- sizes and room

def size_words(size):
    """A size for a sentence: "41 GB", "1.5 GB", "720 MB" (the same in both languages)."""
    if size >= 10 << 30:
        return "%d GB" % round(size / float(1 << 30))
    if size >= 1 << 30:
        return "%.1f GB" % (size / float(1 << 30))
    return "%d MB" % max(1, round(size / float(1 << 20)))


def free_room(folder):
    """The free room on the drive holding `folder` (or the nearest folder above it that exists), or None."""
    here = os.path.abspath(folder)
    while not os.path.isdir(here):
        up = os.path.dirname(here)
        if up == here:
            return None
        here = up
    try:
        return shutil.disk_usage(here).free
    except OSError:
        # A drive that went away, or one that does not say.
        return None


# ------------------------------------------------------------------------------------------------ inspect

def inspect(path, cancel=None, picked=True):
    """What `path` is (a Found), by its content. Reads only: nothing is unpacked or written. `cancel` (a
    threading.Event) stops it between its steps; a stopped look answers what it knew so far. `picked`: the player chose
    this path (Choose an archive..., --inspect); one the search found (picked False) is an archive judged from its
    listing alone (what it holds by its names and sizes), as the design has it: its songs are counted only once the
    player picks it, or from the folder Unpack makes."""
    found = Found(path)
    try:
        if not os.path.exists(path):
            found.state, found.line = NOT_HERE, ("intake.line.gone", {})
            return found
        if os.path.isdir(path):
            return _folder(found, cancel)
        return _file(found, cancel, picked)
    except Exception as e:  # noqa: BLE001  (a path the reading did not expect is said, never a stopped guide)
        log.exception("could not look at %s", path)
        found.state = NOT_HERE
        found.line = e if isinstance(e, errors.Worded) else ("intake.line.unreadable", {})
        return found


def _stopped(cancel):
    return cancel is not None and cancel.is_set()


def _charts_soon(path):
    """without_charts() for the game folder at or below path, started now on a thread of its own: the charts' check
    reads the most of a look (the charts' family is 1.2 GB in a whole game folder), so it goes on while the survey and
    the rest of the look do (it waits on the drive, they mostly on Python). A function that gives its answer, waiting
    for it; None when there is no game folder there or it has no charts' family (the look says so its own way). Its
    answer is kept by size and time either way (core/charts.py), so a look stopped meanwhile wastes none of it."""
    try:
        game = g.Game.find(path)
    except (g.GameError, OSError):
        return None
    if "charts" in game.missing():
        return None
    done = {}

    def work():
        try:
            done["answer"] = without_charts(game)
        except BaseException as e:  # noqa: BLE001  (raised where the answer is asked for, as it was before)
            done["error"] = e

    thread = threading.Thread(target=work, daemon=True, name="charts")
    thread.start()

    def answer():
        thread.join()
        if "error" in done:
            raise done["error"]
        return done["answer"]

    return answer


def _folder(found, cancel):
    """A folder: the game folder at it or up to four levels below it, judged by what it holds."""
    # The launcher hosts the server on this PC, so the client may use the server's reading (never the reverse).
    from opendmt3.server.services import catalog
    charts_answer = _charts_soon(found.path)
    survey = catalog.survey(found.path)
    if survey.get("folder") is None:
        found.state, found.line = NOT_HERE, said("error.source.nothing")
        return found
    found.kind, found.root, found.path = FOLDER, survey["folder"], survey["folder"]
    found.client = survey.get("client_kind")
    if found.client:
        found.facts.append(("intake.client." + found.client, {}))
    if survey.get("problem"):
        # The reading's own words: the cabinet's client, a client without the table, a damaged song list...
        key = survey.get("problem_key")
        found.state = NOT_HERE
        found.line = said(key) if key in errors.TEXT else errors.Worded(survey["problem"])
        return found
    game = g.Game(found.root)
    if survey.get("songs") is not None:
        # The card counts the songs the game offers in any mode and their jackets: a row of the song list that no mode's
        # table names is never shown to a player (the server's count keeps every row, for the records' titles and
        # levels).
        found.songs, found.jackets = _offered_counts(game, survey.get("jackets"))
    reasons = survey.get("reasons") or {}
    if reasons.get("jackets") in errors.TEXT and reasons["jackets"].startswith("error.game.damaged"):
        # The file with the jackets damaged: said with what to do (what the game does without them is measured in a
        # whole song before PLAY is held back for it).
        found.line, found.tone = said(reasons["jackets"]), PROBLEM
    if found.songs is not None:
        found.facts.append(("intake.songs", {"n": found.songs}))
    if found.jackets:
        found.facts.append(("intake.jackets", {"n": found.jackets}))
    found.state, found.actions = READY, [CHOOSE]
    # The card's one line: each later one says more than the one before it, so the last that applies is shown.
    if _cabinet_data_comes(game):
        # A copy of a cabinet's drives: its operator data (drive e) is taken at the first PLAY, once.
        found.line, found.tone = ("intake.line.cabinet_data", {}), NOTE
    if found.client == g.MODIFIED:
        # Used as it is, without the screen fit (the places it changes may not hold the bytes it expects).
        found.line, found.tone = ("intake.line.modified", {}), NOTE
    missing = game.missing()
    if "previews" in missing:
        # Measured: the song select shows no preview, and songs play.
        found.line, found.tone = ("intake.line.no_previews", {}), NOTE
    if "videos" in missing:
        # Measured: songs play on a black background where their video was.
        found.line, found.tone = ("intake.line.no_videos", {}), NOTE
    if _stopped(cancel):
        return found
    found.changed = _changed_files(game)
    if found.changed:
        found.facts.append(("intake.changed", {"n": found.changed}))
        found.actions.append(PUT_BACK)
        # What Put back does, in the card's one line (PLAY works either way: it reads the originals kept in backup).
        found.line, found.tone = ("intake.line.older_changes", {}), NOTE
    if "charts" not in missing and not _stopped(cancel):
        # Songs without charts (core/charts.py: worked out once per change of the charts' files), from the check
        # started with the look.
        unplayable = charts_answer() if charts_answer is not None else without_charts(game)
        if unplayable and unplayable["first"]:
            # Measured: the game stops when a song without its chart starts, and this one it shows first.
            found.state, found.actions = NOT_HERE, [a for a in found.actions if a != CHOOSE]
            found.line, found.tone = ("intake.line.first_song_no_charts", {}), PROBLEM
            return found
        if unplayable and unplayable["without"]:
            found.line, found.tone = ("intake.line.songs_no_charts", {"n": len(unplayable["without"])}), PROBLEM
    from opendmt3.client import find
    if find.cloud_only(found.root):
        # Played from the cloud, every file would come down while the game waits: said before PLAY.
        found.line, found.tone = ("intake.line.onedrive", {}), PROBLEM
    for part in ("tutorial", "charts"):
        if part in missing:
            # Measured: the game stops when the tutorial, or a song, starts; the folder does not play here as it is.
            found.state, found.actions = NOT_HERE, [a for a in found.actions if a != CHOOSE]
            found.line, found.tone = ("intake.line.no_" + part, {}), PROBLEM
    return found


def _offered_counts(game, jackets):
    """(how many songs the game offers, how many of them have their jacket) for a game folder (core/charts.py). The
    survey's count of every row's jackets comes in `jackets`: none counted (the jackets' family missing or damaged,
    which the survey says) stays as it is. (None, None) when the songs offered cannot be told."""
    from opendmt3.core import charts
    from opendmt3.core.formats import pak
    from opendmt3.server.services import catalog
    try:
        songs = charts.offered(game)
    except (OSError, ValueError, g.GameError, pak.PakError) as e:
        # The card goes on without the count, as when the song list cannot be read.
        log.info("the songs offered in %s were not counted: %s", game.root, e)
        return None, None
    if songs is None:
        # No song list at all: nothing to count.
        return None, None
    if not jackets:
        # Not one jacket among every row's: none among the songs offered either, and the family is not opened again.
        return len(songs), jackets
    try:
        with game.layers("DiscImg") as layers:
            names = layers.names()
    except (OSError, g.GameError, pak.PakError) as e:
        log.info("the jackets in %s were not counted: %s", game.root, e)
        return len(songs), None
    # Each song offered by its jacket's path, as the server finds it (its first picture).
    return len(songs), sum((catalog.JACKET_PATH % s["name"]).lower() in names for s in songs)


def without_charts(game):
    """core/charts.py's answer for a game folder, kept in openDMT3's own folder (None when it cannot be told)."""
    from opendmt3.client import state
    from opendmt3.core import charts
    try:
        return charts.check(game, state.own_folder().path("openDMT3-charts.json"))
    except (OSError, ValueError, g.GameError) as e:
        log.warning("the songs' charts of %s could not be counted: %s", game.root, e)
        return None


def _cabinet_data_comes(game):
    """True when PLAY would take the operator data from a copy of a cabinet's drives (drive e beside the game
    folder's drive d) and openDMT3 has none of its own yet: the one time that says something."""
    from opendmt3.client import state
    from opendmt3.core.cabinet import steps
    try:
        _, kind = steps.FreePlay.source(game)
    except OSError:
        return False
    return kind == "cabinet" and not os.path.isfile(state.own_folder().path(steps.FreePlay.GAME_FILE))


def _changed_files(game):
    """How many game files an earlier PLAY changed in the folder (its backup's list says which, by their hashes)."""
    from opendmt3.core.backup import Backup
    try:
        return len(Backup(game).still_changed())
    except (OSError, ValueError) as e:
        # A backup list that cannot be read changes nothing here; Help's Put back says more.
        log.warning("the backup list of %s could not be read: %s", game.root, e)
        return 0


def _file(found, cancel, picked=True):
    """A file: an archive (or a split archive's part), a file of a game folder, or nothing of the game's."""
    from opendmt3.server.services import sources
    kind = sources.kind_of(found.path)
    if kind == "part":
        number, _ = sources.part_of(found.path)
        found.state, found.line = NOT_HERE, said("error.source.later_part", n=number)
        return found
    if kind == "archive":
        return _archive(found, cancel, picked=picked)
    # One file of a game folder (the client alone, one of the game's files): the folder around it.
    around = sources.around(found.path)
    if around is not None:
        found.path = around
        return _folder(found, cancel)
    found.state = NOT_HERE
    found.line = said("error.source.part" if found.path.lower().endswith((".pak", ".exe")) else "error.source.nothing")
    return found


def _archive(found, cancel, password=None, picked=True):
    """An archive: listed (never unpacked) to find the game folder in it, the room it takes and the room there is. One
    the player picked has its songs counted from its song list's few files (_songs_inside); one the search found is
    said from its listing alone."""
    from opendmt3.server.services import sources
    found.kind = ARCHIVE
    number, _ = sources.part_of(found.path)
    if number is not None:
        found.parts = _parts_present(found.path)
        found.facts.append(("intake.parts", {"n": found.parts}))
    gap = sources.missing_part(found.path)
    if gap is not None:
        found.state, found.line = NOT_HERE, said("error.source.missing_part", n=gap)
        return found
    try:
        entries = sources.listing(found.path, password)
    except sources.SourceError as e:
        if e.key == "error.source.password":
            # Its names are hidden too: the password comes first, in the Unpack dialog.
            found.password = True
            found.state, found.actions = UNPACK, [UNPACK_IT]
            found.line, found.tone = e, NOTE
            return found
        if e.key == "error.source.no_7zip":
            found.state, found.line = NOT_HERE, ("intake.line.no_7zip", {})
            return found
        found.state, found.line = NOT_HERE, e
        return found
    if _stopped(cancel):
        return found
    root = sources.game_in(entries)
    if root is None:
        inside = sources.inner_archives(entries)
        if not inside:
            found.state, found.line = NOT_HERE, said("error.source.nothing")
            return found
        refused = next((e for e in inside if sources.cannot_take(e)), None)
        if refused is not None:
            # One the unpacking would refuse (no size in the listing, a link...): said now, as it would be then.
            found.state, found.line = NOT_HERE, sources.entry_refused(refused.name)
            return found
        # The game is in an archive inside this one: both are opened when it is unpacked. Until the one inside is
        # out its own entries are not known: its size stands for them, and the room counts it twice (the archive
        # taken out, and the game folder from it).
        found.inner = True
        found.size = sum(e.size for e in inside)
        found.needed = found.size * 2 + SPARE
    else:
        found.inside = root
        mine = [e for e in entries if not e.folder and e.name.lower().startswith(root.lower())]
        # An unsafe name, a link, no size, or a name twice: the unpacking would refuse it, so the card says so now.
        refused = next((e for e in mine if sources.cannot_take(e)), None) or sources.twice(mine)
        if refused is not None:
            found.state, found.line = NOT_HERE, sources.entry_refused(refused.name)
            return found
        found.size = sum(e.size for e in mine)
        found.needed = found.size + SPARE
        found.password = any(e.encrypted for e in mine)
        if picked and not found.password and not _stopped(cancel):
            found.songs = _songs_inside(found.path, mine, root)
            if found.songs is not None:
                found.facts.append(("intake.songs", {"n": found.songs}))
    found.free = free_room(os.path.dirname(os.path.abspath(found.path)))
    found.facts.append(("intake.space", {"needed": size_words(found.needed),
                                         "free": size_words(found.free) if found.free is not None else "?"}))
    found.state, found.actions = UNPACK, [UNPACK_IT]
    if found.inner:
        found.line, found.tone = ("intake.line.nested", {}), NOTE
    elif found.password:
        found.line, found.tone = said("error.source.password"), NOTE
    return found


def _vint(data, at):
    """A RAR5 number at `at` (seven bits a byte, the high bit saying another byte follows): (value, where it ends)."""
    value, shift = 0, 0
    while at < len(data):
        byte = data[at]
        at += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return value, at
    # Cut short: no number there.
    raise ValueError("no number")


def quick(path):
    """True when one file of an archive comes out at once, wherever it is in the archive: a zip, or a RAR that is not
    solid (by its main header). A 7z, or a solid RAR, keeps its files in blocks where one near the end means unpacking
    all before it."""
    try:
        with open(path, "rb") as f:
            head = f.read(64)
    except OSError:
        return False
    if head.startswith(b"PK\x03\x04"):
        # A zip: each file is read where its local header is.
        return True
    try:
        if head.startswith(b"Rar!\x1a\x07\x01\x00"):
            # RAR5: the main header after the signature and its CRC: its size, its type (1), its flags, an extra
            # area's size when flag 1 says there is one, then the archive's flags, 4 meaning solid.
            _, at = _vint(head, 12)
            kind, at = _vint(head, at)
            flags, at = _vint(head, at)
            if flags & 1:
                _, at = _vint(head, at)
            archive_flags, _ = _vint(head, at)
            return kind == 1 and not archive_flags & 0x0004
        if head.startswith(b"Rar!\x1a\x07\x00"):
            # RAR 4: the main header's type (0x73) and its flags, 8 meaning solid.
            return head[9] == 0x73 and not int.from_bytes(head[10:12], "little") & 0x0008
    except (ValueError, IndexError):
        # A header cut short: not counted, as for a 7z.
        return False
    return False


def _songs_inside(path, mine, root):
    """How many songs the game folder in an archive has, from its song list: the programs, the settings' file and the
    song list's files (about 25 MB) taken out into a folder of the launcher's own, read, and removed. None when that
    would be slow (a 7z's solid blocks) or does not work."""
    import tempfile
    from opendmt3.server.services import catalog, sources
    if not quick(path):
        # Counting would mean unpacking much of it: the count comes once it is unpacked.
        return None
    take = []
    for e in mine:
        rest = e.name[len(root):].lower()
        if ("/" not in rest and rest.endswith(".exe")) or rest == "pack/config.pak" or (
                rest.startswith("pack/discinfo") and rest.endswith(".pak") and "/" not in rest[5:]):
            take.append(e)
    folder = tempfile.mkdtemp(prefix="openDMT3-look-")
    try:
        sources.extract(path, take, folder)
        # The folder as the archive spells it.
        game = os.path.join(folder, *root.rstrip("/").split("/")) if root else folder
        survey = catalog.survey(game)
        if survey.get("songs") is None:
            # The song list cannot be read there: no count.
            return None
        # The songs the game offers, as a game folder's card counts them (the jackets are not taken out to count).
        return _offered_counts(g.Game.find(game), None)[0]
    except Exception as e:  # noqa: BLE001  (the card goes on without the count)
        log.info("the songs in %s were not counted: %s", path, e)
        return None
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _parts_present(path):
    """How many parts of a split archive are beside its first part (the first included)."""
    from opendmt3.server.services import sources
    _, stem = sources.part_of(path)
    folder = os.path.dirname(os.path.abspath(path)) or "."
    try:
        names = os.listdir(folder)
    except OSError:
        return 1
    count = 0
    for name in names:
        n, s = sources.part_of(os.path.join(folder, name))
        if n is not None and s.lower() == stem.lower():
            count += 1
    return max(1, count)


def inspect_archive(path, password):
    """An archive looked at again with its password (its names may have been hidden without it)."""
    return _archive(Found(path), None, password)


def password_opens(path, password):
    """True when `password` opens the archive: its names list with it, and its first encrypted file starts to come
    out (7-Zip's test, stopped after PASSWORD_SECONDS)."""
    from opendmt3.client import unpack
    from opendmt3.server.services import sources
    try:
        entries = sources.listing(path, password)
    except sources.SourceError as e:
        if e.key in ("error.source.password", "error.source.wrong_password"):
            return False
        raise
    first = next((e for e in entries if e.encrypted and not e.folder), None)
    if first is None:
        # Only the names were hidden, and the password showed them.
        return True
    import tempfile
    enough = threading.Event()
    timer = threading.Timer(PASSWORD_SECONDS, enough.set)
    timer.daemon = True
    folder = tempfile.mkdtemp(prefix="openDMT3-password-")
    try:
        # The one entry by its name as listed, matched as it is (no wildcards), from a list file: a name that starts
        # with "-" or "@" is never read as a switch or a list, and the archive's comes after "--".
        listed = sources.names_file(os.path.join(folder, "names.txt"), [first])
        timer.start()
        code, out = unpack.Run(["t", "-spd", "-scsUTF-8", listed, "--", path], password, cancel=enough).go()
    except unpack.Stopped:
        # Still going after a while: the password decrypts, or it would have failed at once.
        return True
    finally:
        timer.cancel()
        shutil.rmtree(folder, ignore_errors=True)
    return code == 0 or not ("Wrong password" in out or "Data Error in encrypted" in out)
