"""What openDMT3 makes to play a game folder, step by step, in openDMT3's own folder: the game folder is only read.

openDMT3 keeps what it needs to play a game folder in a folder of its own (Own): a copy of the game's client (with the
screen fit when it is the PC client) and the client's libraries from the game folder beside it, openDMT3's card reader
library, the game's settings for a PC, the operator data, and copies of the two archives a PC needs changed (the
server's address, the hidden patterns). A list beside the library (openDMT3-files.txt) names which of the game's paths
are openDMT3's; the library gives those to the game in place of the game folder's own (native/cardreader/files.c).

Measured under Wine, the game folder read only, a whole song each:
  * the client finds its own folder with GetModuleFileNameA and makes it the current folder: the library answers with
    the game folder, so the game's relative paths (pack\\, Resource\\, TECHNIKA\\) stay the game folder's;
  * run from another folder, Windows takes a library of the same name from System32 before the game folder's (Wine's
    own D3DX 9: the game stopped at its first sound): the client's libraries are copied beside the copy of it;
  * the game reads each file from the newest archive of its family that has it (the base, then its patches in number
    order; of 31 files in more than one archive, each was read from the newest): a changed file goes in a copy of that
    archive. An archive openDMT3 writes itself as an extra patch was not taken by the game (the address in it unused).

Each step answers two questions: is openDMT3's folder already the way the options ask (status), and if not, make it so
(apply). A game folder an earlier openDMT3 changed is read through its backup\\ (Originals), and the list gives the game
those originals wherever openDMT3 gives none of its own.
"""

import hashlib
import json
import logging
import os
import tempfile
import time

from opendmt3 import __version__
from opendmt3.core import game as g
from opendmt3.core.backup import MANIFEST, Backup
from opendmt3.core.cabinet import display, native, values as choices
from opendmt3.core.formats import game_settings, pak, pe, settings_ini, stage_lists

log = logging.getLogger(__name__)

# Which openDMT3 made a copy: a record from another version is no record (its fix or its changes may differ).
MADE_BY = __version__


class Options:
    """What the person asked for; the defaults are what most players want."""

    def __init__(self, values=None, unlock=True, server=None, display_mode=None, card_reader=False):
        # The launcher's choices (screen, sound), checked now so a bad one fails before any file is touched.
        given = dict(values or {})
        # The older keyword (from the command line's --window) still works and wins over values.
        if display_mode is not None:
            given["display_mode"] = display_mode
        self.values = choices.normalize(given)
        self.unlock = unlock               # show every hidden STAR and POP pattern without a card
        self.server = server               # None or "official": the game's own address; "host:port": that server
        self.card_reader = card_reader     # a card goes in (logins by card); openDMT3's library goes in either way

    @property
    def display_mode(self):
        """'fullscreen' (borderless over the whole monitor) or 'window' (a framed window)."""
        return self.values["display_mode"]


class Status:
    def __init__(self, done, detail):
        self.done = done
        self.detail = detail


def _write_atomically(path, data):
    """Write next to the target and swap it in, so a crash never leaves half a file behind."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".opendmt3-")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _remove(path):
    """Take a file of openDMT3's away if it is there (a choice turned off)."""
    if os.path.isfile(path):
        os.remove(path)


def _stamp(path):
    """A file's size and time ([bytes, ns]), or None when it is not there: what a copy's record compares, so a check
    from the second PLAY on reads no file whose size and time are the same."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return [st.st_size, st.st_mtime_ns]


# ----------------------------------------------------------------------------------------------- the places

class Own:
    """openDMT3's own folder for playing a game folder: everything PLAY makes, and the card reader's card."""

    # The list the card reader library reads beside itself (native/cardreader/redirect.h).
    LIST = "openDMT3-files.txt"
    # What each copy was made from (its source's fingerprint), so a copy is made again only when its source changed.
    MADE = "openDMT3-made.json"
    SETTINGS = "setting.ini"
    # Crash dumps the game writes go here instead of the game folder's Dump\\ (launch.crash_dumps reads them).
    DUMPS = "Dump"

    def __init__(self, folder):
        self.folder = folder

    def path(self, *parts):
        return os.path.join(self.folder, *parts)

    def client(self):
        """openDMT3's copy of the client, the program PLAY starts."""
        return self.path(g.FIXED_EXE)

    def made(self):
        """{what: the fingerprint of what it was made from} (empty when nothing was recorded or the record is not
        readable: everything is then made again)."""
        try:
            with open(self.path(self.MADE), encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def record(self, what, fingerprint):
        """Remember what a copy was made from (None forgets it)."""
        data = self.made()
        if fingerprint is None:
            data.pop(what, None)
        else:
            data[what] = fingerprint
        _write_atomically(self.path(self.MADE), json.dumps(data, indent=1, sort_keys=True).encode("utf-8"))


class Originals:
    """The game folder's files as they came. Where an earlier openDMT3 changed a file and kept its original in the game
    folder's backup\\, that original; nothing here writes (the backup list is only read)."""

    @classmethod
    def of(cls, game):
        """The one view of a game folder's originals (kept on the Game, so each file is fingerprinted once)."""
        if getattr(game, "_originals", None) is None:
            game._originals = cls(game)
        return game._originals

    def __init__(self, game):
        self.game = game
        self.kept = None
        self._changed = None
        # {relative path: the kept original, or None}, worked out once each.
        self._copies = {}
        if os.path.isfile(game.path(g.BACKUP_DIR, MANIFEST)):
            try:
                self.kept = Backup(game)
            except (OSError, ValueError, AttributeError):
                # A list that cannot be read keeps nothing openDMT3 can vouch for: the folder's own files then.
                log.warning("the client data's backup list cannot be read; its own files are used", exc_info=True)

    def changed(self):
        """The files an earlier openDMT3 changed that still differ from their originals ("/" separated), once."""
        if self._changed is None:
            self._changed = self.kept.still_changed() if self.kept else []
        return self._changed

    def kept_copy(self, rel):
        """The original an earlier openDMT3 kept for a file it changed, when there is one; else None."""
        key = rel.replace("\\", "/")
        if key not in self._copies:
            self._copies[key] = None
            entry = self.kept.files.get(key) if self.kept else None
            if entry and entry.get("existed") and key in self.changed():
                copy = os.path.join(self.kept.dir, *key.split("/"))
                # Only a copy that is the recorded original: a copy changed since is no original any more.
                if os.path.isfile(copy) and g.sha256_file(copy) == entry.get("sha256"):
                    self._copies[key] = copy
        return self._copies[key]

    def path(self, rel):
        """Where the file as it came is read: the kept original, or the game folder's own."""
        return self.kept_copy(rel) or self.game.path(*rel.replace("\\", "/").split("/"))


# ----------------------------------------------------------------------------------------------------- client

class Client:
    """openDMT3's copy of the game's client (the screen fit in when it is the PC client) with the client's libraries
    from the game folder beside it."""

    name = "client"

    def _source(self, game):
        """The client the game's files are opened with (the PC client first, as Game.table chooses), as bytes."""
        game.table()
        return _read(game.client[0])

    def _made(self, data):
        """The copy openDMT3 runs: the PC client with the screen fit; a client that has it already as it is; a modified
        one with only the large-address flag (played without the fit, which is the PC build's)."""
        digest = hashlib.sha256(data).hexdigest()
        if digest in (g.PC_BUILD, g.PC_BUILD_DISPLAY_FIX_EARLIER):
            return display.patch(data)
        if digest == g.PC_BUILD_DISPLAY_FIX:
            return data
        try:
            return display.large_address_aware(data)
        except display.PatchError:
            # Not a program openDMT3 can read the header of: copied as it is.
            return data

    def libraries(self, game, data):
        """The client's libraries in the game folder: its imports and theirs in turn that are files there (any letter
        case), openDMT3's card reader left out, and the touch screen's library when this build has openDMT3's own (the
        library step puts it in place). {name as the game folder spells it: its path}."""
        found = {}
        try:
            todo = list(pe.imports(data))
        except pe.PeError as e:
            # A client whose import table cannot be read has nothing to copy beside it (Windows finds what it needs).
            log.warning("the client's libraries cannot be read (%s): none copied", e)
            return found
        seen = set()
        # openDMT3's own touch screen library, when this build has it: the client data's (the cabinet's touch frame's)
        # is never loaded, nor what it needs in turn.
        ours = {"crt_r1.dll"} | ({native.TOUCH.lower()} if native.touch_library() else set())
        while todo:
            name = todo.pop(0)
            low = name.lower()
            # Each name once; the card reader is openDMT3's (the cabinet's is never loaded).
            if low in seen or low in ours:
                continue
            seen.add(low)
            real = g.real_name(game.root, name)
            path = game.path(real) if real else None
            # Not in the game folder: one of Windows' own (KERNEL32, d3d9...), found where Windows keeps it.
            if not path or not os.path.isfile(path):
                continue
            found[real] = path
            try:
                todo += pe.imports(_read(path))
            except pe.PeError:
                # A library that is no program: copied all the same, as the game would load it.
                pass
        return found

    def _wanted(self, game):
        """{file in openDMT3's folder: (bytes or a path to copy, its sha256)}, and {each source's path: its stamp}."""
        data = self._source(game)
        made = self._made(data)
        wanted = {g.FIXED_EXE: (made, hashlib.sha256(made).hexdigest())}
        sources = {os.path.normcase(game.client[0]): _stamp(game.client[0])}
        for name, path in self.libraries(game, data).items():
            wanted[name] = (path, g.known_sha256(path))
            sources[os.path.normcase(path)] = _stamp(path)
        return wanted, sources

    def _recorded(self, game, own):
        """The record of the last copy when nothing it names changed since (the client, each library, each copy, by
        size and time): the check then reads no file. None otherwise."""
        record = own.made().get(self.name)
        if not isinstance(record, dict) or not isinstance(record.get("sources"), dict) or record.get("by") != MADE_BY:
            return None
        game.table()
        if os.path.normcase(game.client[0]) not in record["sources"]:
            return None
        if any(_stamp(path) != stamp for path, stamp in record["sources"].items()):
            return None
        if any(_stamp(own.path(name)) != stamp for name, stamp in (record.get("copies") or {}).items()):
            return None
        return record

    def _record(self, own, wanted, sources, words):
        """Keep what the copies were made from and the copies themselves, by size and time."""
        own.record(self.name, {"sources": sources, "copies": {name: _stamp(own.path(name)) for name in wanted},
                               "words": words, "by": MADE_BY})

    def status(self, game, own, options):
        record = self._recorded(game, own)
        if record:
            return Status(True, record.get("words") or "ready")
        if not os.path.isfile(own.client()):
            # Nothing copied yet (a first PLAY): said without reading the client, which apply reads once.
            return Status(False, "not copied yet")
        wanted, sources = self._wanted(game)
        missing = [name for name, (_, digest) in wanted.items()
                   if not os.path.isfile(own.path(name)) or g.known_sha256(own.path(name)) != digest]
        if missing:
            return Status(False, "%d of %d files to copy" % (len(missing), len(wanted)))
        fixed = wanted[g.FIXED_EXE][1] == g.PC_BUILD_DISPLAY_FIX
        words = "ready%s, %d libraries" % (" with the screen fit" if fixed else "", len(wanted) - 1)
        # Read once: from now on the check compares sizes and times.
        self._record(own, wanted, sources, words)
        return Status(True, words)

    def apply(self, game, own, options):
        record = own.made().get(self.name) if isinstance(own.made().get(self.name), dict) else {}
        before = record.get("sources") or {} if record.get("by") == MADE_BY else {}
        copies = record.get("copies") or {} if record.get("by") == MADE_BY else {}
        data = self._source(game)
        made = self._made(data)
        libraries = self.libraries(game, data)
        sources = {os.path.normcase(game.client[0]): _stamp(game.client[0])}
        copied = 0
        # The client copy: written again only when the client or the copy changed since the record of the last one.
        if before.get(os.path.normcase(game.client[0])) != sources[os.path.normcase(game.client[0])] \
                or copies.get(g.FIXED_EXE) != _stamp(own.client()) or not os.path.isfile(own.client()):
            _write_atomically(own.client(), made)
            copied += 1
        for name, path in libraries.items():
            key = os.path.normcase(path)
            sources[key] = _stamp(path)
            target = own.path(name)
            # A library copied before, unchanged since on both sides, is not read again.
            if before.get(key) == sources[key] and copies.get(name) == _stamp(target) and os.path.isfile(target):
                continue
            # Read once, written beside the client copy (a copy cut short is never left: written aside, then swapped).
            _write_atomically(target, _read(path))
            copied += 1
        fixed = hashlib.sha256(made).hexdigest() == g.PC_BUILD_DISPLAY_FIX
        wanted = [g.FIXED_EXE] + list(libraries)
        self._record(own, wanted, sources, "ready%s, %d libraries" % (" with the screen fit" if fixed else "",
                                                                      len(libraries)))
        return "%d files copied" % copied


# ------------------------------------------------------------------------------------------------ card reader

class CardReader:
    """CRT_R1.dll: openDMT3's library in place of the cabinet's card reader, with the faces its in-game layer writes in
    (and their licences), beside the client copy, which loads it from there.

    The game loads this library by name before its own code runs. It is the card reader (a card is a text file the
    launcher writes beside it: the game logs a player in only by card in this build), it serves openDMT3's files in
    the game folder's place (the list), and it is openDMT3's in-game layer (the bar with the menu and the X, the
    question before quitting, the toast, the frame rate chip, the pointer, the sound device, frame pacing, the
    picture's filters). Offline there is no card file, so the reader is empty and the game plays with NO ID CARD.
    """

    name = "game library"
    REL = "CRT_R1.dll"
    # The layer's words are in the launcher's own faces, loaded by the DLL for the game's process only: Pretendard
    # Bold (labels) and Regular (lines), and DMT3 Wide (the product's name), each family with its licence.
    FONT = "openDMT3-Pretendard-Bold.ttf"
    FONT_REGULAR = "openDMT3-Pretendard-Regular.ttf"
    FONT_WIDE = "openDMT3-DMT3Wide.ttf"
    LICENCE = "openDMT3-Pretendard-OFL.txt"
    LICENCE_WIDE = "openDMT3-Saira-OFL.txt"
    # The notices of the code built into the library (the picture's passes, the compiler's runtime), beside it
    # wherever it goes, as their licences ask.
    NOTICES = "openDMT3-card-reader-NOTICES.txt"
    FILES = (REL, FONT, FONT_REGULAR, FONT_WIDE, LICENCE, LICENCE_WIDE, NOTICES)
    # The names an earlier launcher gave a file of these in openDMT3's folder: taken away when the files are written
    # again, so one copy of each is there (the earlier ones named the notices after the library's file).
    FORMER = ("openDMT3-CRT_R1-NOTICES.txt",)

    def _sources(self):
        """{file in openDMT3's folder: the copy in this build}, or None when this is not a build that has the library."""
        ours = native.card_reader()
        if ours is None:
            return None
        sources = {self.REL: ours, self.FONT: native.font(), self.FONT_REGULAR: native.font_regular(),
                   self.FONT_WIDE: native.font_wide(), self.LICENCE: native.font_licence(),
                   self.LICENCE_WIDE: native.font_wide_licence()}
        # The library's notices go with it from the same folder (every build has them; a library a test made has
        # none, and goes alone).
        found = native.notices()
        if found:
            sources[self.NOTICES] = found
        # The Sound page's OpenAL Soft mixer, beside the library, which loads it from there when it is chosen: DSOAL
        # and OpenAL Soft with their notices, in every build that has them (native.openal: all three or none).
        sources.update(native.openal())
        # openDMT3's own touch screen library in place of the client data's, in every build that has it: the game
        # loads it from beside the client copy, and it hands the game every finger through this library.
        touch = native.touch_library()
        if touch:
            sources[native.TOUCH] = touch
        return sources

    def status(self, game, own, options):
        sources = self._sources()
        if sources is None:
            # Without it the game cannot be given openDMT3's files (a copy of the repository without a build).
            return Status(False, "openDMT3's card reader is not part of this build")
        # By size and time from the second look on (known_sha256): the 9 MB of the library and its faces are read
        # again only when one changed.
        done = all(os.path.isfile(own.path(rel)) and g.known_sha256(own.path(rel)) == g.known_sha256(src)
                   for rel, src in sources.items())
        if not done:
            return Status(False, "not copied yet")
        if options.card_reader:
            return Status(True, "openDMT3's library: the card reader and the in-game menu")
        return Status(True, "openDMT3's library: the in-game menu, no card (NO ID CARD)")

    def apply(self, game, own, options):
        sources = self._sources()
        if sources is None:
            raise g.GameError("openDMT3's card reader is not part of this build", "error.game.no_card_reader")
        for rel, src in sources.items():
            _write_atomically(own.path(rel), _read(src))
            # The copy is the source byte for byte: its fingerprint is the source's, with no reading again.
            g.known_as(own.path(rel), g.known_sha256(src))
        for former in self.FORMER:
            try:
                # Written above under its name of today: the copy under the earlier name is one too many.
                os.remove(own.path(former))
            except OSError:
                # Never there (a folder this launcher made), or in use: nothing reads it either way.
                pass
        return "openDMT3's library in place"


# --------------------------------------------------------------------------------------------------- settings

class Settings:
    """Resource\\config\\setting.ini for the game: its own, from its Config.pak, with only what a PC needs changed."""

    name = "settings"
    SOURCE = "Resource\\Config\\setting.ini"

    def desired(self, game, originals, options):
        with game.open_pak(originals.path("pack/" + os.path.basename(game.pak_path("Config")))) as p:
            entry = p.find(self.SOURCE)
            if entry is None:
                raise g.GameError("the file with the game's settings has no %s" % self.SOURCE, "error.game.config",
                                  name=self.SOURCE)
            text = settings_ini.decode(p.read(entry))
        changes = {
            # A window: exclusive full screen fails on recent Windows and graphics drivers.
            "fullscreen": "false",
            # Rankings, bookkeeping and operator settings in TECHNIKA\\ (no spaces: the game drops them); the library
            # gives the game openDMT3's folder of them.
            "rankFilePath": g.DATA_DIR + "/RANK/",
            "bookkeepingFilePath": g.DATA_DIR + "/BOOK/",
            "gameSettingFilePath": g.DATA_DIR + "/GAME/",
        }
        # The player's choices: borderless or framed, window size, sync, glow, videos, pointer, volumes.
        changes.update(choices.ini_changes(options.values))
        text = settings_ini.set_values(text, changes)
        return settings_ini.encode(text)

    def _key(self, game, options):
        """What the settings are made from: the file that holds the game's own (by size and time) and the choices."""
        source = Originals.of(game).path("pack/" + os.path.basename(game.pak_path("Config")))
        return [os.path.normcase(source), _stamp(source), json.dumps(choices.ini_changes(options.values), sort_keys=True),
                MADE_BY]

    def _words(self, options):
        v = options.values
        # One line a person can read back: how the screen opens and how loud it plays.
        shape = "borderless over the whole monitor" if v["display_mode"] == "fullscreen" else "window " + v["window_size"]
        return "%s, music %d%%, keys %d%%" % (shape, v["music_volume"], v["key_volume"])

    def status(self, game, own, options):
        path = own.path(Own.SETTINGS)
        if not os.path.isfile(path):
            return Status(False, "not made yet (the PC client closes at once without it)")
        record = own.made().get(self.name)
        key = self._key(game, options)
        # Made from the same file and choices, and not changed since: nothing to read.
        if isinstance(record, dict) and record.get("from") == key and record.get("made") == _stamp(path):
            return Status(True, self._words(options))
        if _read(path) == self.desired(game, Originals.of(game), options):
            own.record(self.name, {"from": key, "made": _stamp(path)})
            return Status(True, self._words(options))
        return Status(False, "differs from what the options ask")

    def apply(self, game, own, options):
        _write_atomically(own.path(Own.SETTINGS), self.desired(game, Originals.of(game), options))
        own.record(self.name, {"from": self._key(game, options), "made": _stamp(own.path(Own.SETTINGS))})
        return "written"


# ------------------------------------------------------------------------------------------------- free play

class FreePlay:
    """The operator data (rankings, bookkeeping, the operator's settings) in openDMT3's folder, with free play on.

    Taken once, the first time: from the game folder's TECHNIKA\\ (an earlier openDMT3 kept the player's rankings
    there), else from a copy of a cabinet's drives (drive e\\TECHNIKA beside drive d\\, the game folder's), else from
    the game folder's file\\ (the operator data the game starts from), else the game's defaults. From then on the game
    writes openDMT3's copy as it is played.
    """

    name = "free play"
    GAME_FILE = os.path.join(g.DATA_DIR, "GAME", "game")

    @staticmethod
    def source(game):
        """(where the operator data would be taken from, its kind: "game", "cabinet", "file"), or (None, None)."""
        mine = g.real_name(game.root, g.DATA_DIR)
        if mine and os.path.isfile(os.path.join(game.path(mine), "GAME", "game")):
            return game.path(mine), "game"
        # A copy of a cabinet's drives: the game folder is drive d\\DMT3, the operator data drive e\\TECHNIKA.
        parent = os.path.dirname(game.root)
        if os.path.basename(parent).lower() == "drive d":
            drives = os.path.dirname(parent)
            e = g.real_name(drives, "drive e")
            data = g.real_name(os.path.join(drives, e), g.DATA_DIR) if e else None
            if data and os.path.isfile(os.path.join(drives, e, data, "GAME", "game")):
                return os.path.join(drives, e, data), "cabinet"
        files = g.real_name(game.root, "file")
        if files and os.path.isfile(os.path.join(game.path(files), "game")):
            return game.path(files), "file"
        return None, None

    def _take(self, game, own):
        """Fill openDMT3's TECHNIKA\\ the first time; how it was filled."""
        src, kind = self.source(game)
        target = own.path(g.DATA_DIR)
        if kind in ("game", "cabinet"):
            # The same layout: BOOK\\, GAME\\ and RANK\\ with the game's own file names.
            for sub in ("BOOK", "GAME", "RANK"):
                real = g.real_name(src, sub)
                os.makedirs(os.path.join(target, sub), exist_ok=True)
                if not real:
                    continue
                for name in sorted(os.listdir(os.path.join(src, real))):
                    path = os.path.join(src, real, name)
                    if os.path.isfile(path):
                        _write_atomically(os.path.join(target, sub, name), _read(path))
            return "taken from %s" % src
        for sub in ("BOOK", "GAME", "RANK"):
            os.makedirs(os.path.join(target, sub), exist_ok=True)
        if kind == "file":
            for name in sorted(os.listdir(src)):
                path = os.path.join(src, name)
                if not os.path.isfile(path):
                    continue
                # The settings and the bookkeeping have their own folders; everything else is a ranking.
                sub = {"game": "GAME", "book": "BOOK"}.get(name, "RANK")
                _write_atomically(os.path.join(target, sub, name), _read(path))
            return "taken from file\\"
        # No operator data at all: the operator's settings with the game's defaults; empty rankings and bookkeeping.
        _write_atomically(own.path(self.GAME_FILE), game_settings.GameSettings().build())
        return "the game's defaults"

    def status(self, game, own, options):
        path = own.path(self.GAME_FILE)
        if not os.path.isfile(path):
            return Status(False, "not taken yet")
        s = game_settings.GameSettings.parse(_read(path))
        return Status(s.free_play == 1, "free play %s" % ("on" if s.free_play == 1 else "off"))

    def apply(self, game, own, options):
        how = ""
        if not os.path.isfile(own.path(self.GAME_FILE)):
            how = self._take(game, own) + ", "
        s = game_settings.GameSettings.parse(_read(own.path(self.GAME_FILE)))
        s.free_play = 1
        _write_atomically(own.path(self.GAME_FILE), s.build())
        return how + "free play on"


# ---------------------------------------------------------------------------------------- changed archives

class _ArchiveCopy:
    """Copies of the game's archives in openDMT3's folder (its pack\\) with some files changed: each changed file in a
    copy of the newest archive of its family that has it, since the game reads every file from there (measured: of
    31 files in more than one archive, each was read from the newest). None when the options want the game's own.
    A copy is made again whenever what it is made from changed."""

    name = family = None

    def wanted(self, options):
        """Whether the options want changed copies."""
        raise NotImplementedError

    def changes(self, name):
        """Whether a file of the family (by its name inside) is one this step changes."""
        raise NotImplementedError

    def change(self, name, data, options):
        """The new bytes of one file the step changes."""
        raise NotImplementedError

    def key(self, options):
        """What of the options the copies depend on, as words."""
        raise NotImplementedError

    def plan(self, game, options):
        """{archive ("pack/<name>.pak", as the game folder spells it): {name inside: new bytes}}: every file the step
        changes, in the newest archive that has it. An archive openDMT3 cannot read yet is left as the game has it."""
        originals = Originals.of(game)
        newest = {}
        # Base first, then the patches in number order: a later archive replaces what the ones before it had.
        for path in game.layer_paths(self.family):
            rel = "pack/" + os.path.basename(path)
            try:
                with game.open_pak(originals.path(rel)) as p:
                    mine = {}
                    for e in p.entries:
                        # Inside one archive the first entry of a path is the one the game keeps.
                        if self.changes(e.name) and e.name.lower() not in mine:
                            mine[e.name.lower()] = (rel, e.name, p.read(e))
                    newest.update(mine)
            except pak.PakUnreadable:
                continue
        plan = {}
        for rel, name, data in newest.values():
            plan.setdefault(rel, {})[name] = self.change(name, data, options)
        return plan

    def _fingerprint(self, game, rel, options):
        return "%s %s" % (g.known_sha256(Originals.of(game).path(rel)), self.key(options))

    def _family_stamp(self, game, options):
        """The family's files by size and time, with what of the options the copies depend on: when it equals the
        record of the last copies, nothing needs reading."""
        originals = Originals.of(game)
        layers = [[os.path.normcase(originals.path("pack/" + os.path.basename(p))),
                   _stamp(originals.path("pack/" + os.path.basename(p)))] for p in game.layer_paths(self.family)]
        return {"layers": layers, "key": self.key(options) if self.wanted(options) else None, "by": MADE_BY}

    def _copies_stamp(self, game, own):
        return {rel: _stamp(own.path(*rel.split("/"))) for rel in self._mine(game, own)}

    def _mine(self, game, own):
        """The copies of this family's archives in openDMT3's folder now ("pack/<name>.pak")."""
        names = {os.path.basename(p).lower() for p in game.layer_paths(self.family)}
        folder = own.path("pack")
        return ["pack/" + n for n in sorted(os.listdir(folder)) if n.lower() in names] if os.path.isdir(folder) else []

    def status(self, game, own, options):
        mine = self._mine(game, own)
        if not self.wanted(options):
            return Status(not mine, "the game's own")
        made = own.made()
        record = made.get(self.family)
        # The same files of the family and the same choice as the copies were made from, the copies unchanged since.
        if isinstance(record, dict) and record.get("from") == self._family_stamp(game, options) \
                and record.get("copies") == self._copies_stamp(game, own) and mine:
            return Status(True, self.key(options))
        plan = self.plan(game, options)
        if set(mine) != set(plan) or any(made.get(rel) != self._fingerprint(game, rel, options) for rel in plan):
            return Status(False, "not made yet")
        own.record(self.family, {"from": self._family_stamp(game, options), "copies": self._copies_stamp(game, own)})
        return Status(True, self.key(options))

    def apply(self, game, own, options):
        plan = self.plan(game, options) if self.wanted(options) else {}
        # Copies no longer wanted (a choice turned off, another game folder's archives) go.
        for rel in self._mine(game, own):
            if rel not in plan:
                _remove(own.path(*rel.split("/")))
                own.record(rel, None)
        for rel, replacements in plan.items():
            target = own.path(*rel.split("/"))
            tmp = target + ".opendmt3-new"
            os.makedirs(os.path.dirname(target), exist_ok=True)
            pak.rebuild_pak(Originals.of(game).path(rel), tmp, replacements, game.table())
            os.replace(tmp, target)
            own.record(rel, self._fingerprint(game, rel, options))
        own.record(self.family, {"from": self._family_stamp(game, options), "copies": self._copies_stamp(game, own)}
                   if plan else None)
        return self.key(options) if plan else "the game's own"


class GuestUnlock(_ArchiveCopy):
    """DiscInfo with every hidden STAR and POP pattern shown in its stage lists."""

    name = "guest unlock"
    family = "DiscInfo"

    def wanted(self, options):
        return bool(options.unlock)

    def changes(self, name):
        return stage_lists.is_stage_list(name)

    def change(self, name, data, options):
        return stage_lists.show_all(data)

    def key(self, options):
        return "every pattern shown"


class ServerAddress(_ArchiveCopy):
    """Config with the server's address in its networksetting.ini."""

    name = "server address"
    family = "Config"
    SOURCE = "Resource\\Config\\networksetting.ini"

    def wanted(self, options):
        return options.server not in (None, "official")

    def changes(self, name):
        return name.lower() == self.SOURCE.lower()

    def key(self, options):
        return "now %s" % options.server

    def _address(self, options):
        host, _, port = options.server.rpartition(":")
        if not host or not port.isdigit():
            raise g.GameError("server address must be host:port, not %r" % options.server, "error.game.server_address",
                              value=options.server)
        return host, port

    def change(self, name, data, options):
        host, port = self._address(options)
        return settings_ini.set_values(data.decode("ascii"), {"serverip": host, "port": port}).encode("ascii")

    def current(self, game, path):
        """(serverip, port) in an archive's networksetting.ini."""
        with game.open_pak(path) as p:
            text = p.read(p.find(self.SOURCE)).decode("ascii")
        return settings_ini.get_value(text, "serverip"), settings_ini.get_value(text, "port")

    def apply(self, game, own, options):
        # A bad address is said before anything is made.
        if self.wanted(options):
            self._address(options)
        return _ArchiveCopy.apply(self, game, own, options)


# The order matters only for the words PLAY shows; every step reads the game folder and writes openDMT3's folder.
STEPS = [Client(), CardReader(), Settings(), FreePlay(), GuestUnlock(), ServerAddress()]


# ------------------------------------------------------------------------------------------------- the list

# What starts a path in the list named from the game folder (native/cardreader/redirect.h): an original an earlier
# openDMT3 kept in the game folder's backup. Every other path is named from openDMT3's own folder; no path is whole.
GAME_MARK = "<game>\\"


def list_lines(game, own):
    """The list's lines (redirect.h): which of the game's paths are openDMT3's files, and the originals an earlier
    openDMT3 kept for files it changed and openDMT3 gives none of its own for. Every path is relative (to openDMT3's
    folder, or to the game folder after GAME_MARK), so the list names no file outside the two."""
    lines = [
        # The settings, from openDMT3's folder (the game reads them by their whole path in its folder).
        "Resource\\config\\setting.ini\t" + Own.SETTINGS,
        # The operator data the game reads and writes as it is played.
        g.DATA_DIR + "\\\t" + g.DATA_DIR,
        # Crash dumps, which the game writes into its folder.
        "Dump\\\t" + Own.DUMPS,
        # The client's own path in the game folder (the library tells the client it runs from there).
        g.FIXED_EXE + "\t" + g.FIXED_EXE,
    ]
    served = {"resource/config/setting.ini", g.DATA_DIR.lower(), "dump", g.FIXED_EXE.lower()}
    for step in STEPS:
        if isinstance(step, _ArchiveCopy):
            # openDMT3's copies of the game's archives, under the names the game folder gives them.
            for rel in step._mine(game, own):
                lines.append(rel.replace("/", "\\") + "\t" + rel.replace("/", "\\"))
                served.add(rel.lower())
    originals = Originals.of(game)
    for key in originals.changed():
        copy = originals.kept_copy(key)
        if not copy or key.lower() in served or key.lower().split("/")[0] in served:
            continue
        # The kept original by its place in the game folder (backup\ and the same path; Backup takes plain paths only).
        lines.append(key.replace("/", "\\") + "\t" + GAME_MARK + g.BACKUP_DIR + "\\" + key.replace("/", "\\"))
    return lines


def write_list(game, own):
    """Write the list beside the library (only when it differs); the lines written."""
    lines = list_lines(game, own)
    data = ("\r\n".join(lines) + "\r\n").encode("utf-8")
    path = own.path(Own.LIST)
    if not os.path.isfile(path) or _read(path) != data:
        _write_atomically(path, data)
    return lines


def prepare(game, own, options, report=lambda name: None, took=None):
    """See _prepare; the fingerprints learned are kept for the next PLAY whatever happens."""
    try:
        return _prepare(game, own, options, report, took)
    finally:
        g.save_hash_cache()


def _prepare(game, own, options, report=lambda name: None, took=None):
    """Bring openDMT3's folder in line with the game folder and the options, then write the list; the lines of what
    changed. report(name) is told each step that has something to do, before it does it; `took` (a list) gets each
    step's time, as "name 1.2 s"."""
    done = []
    for step in STEPS:
        at = time.perf_counter()
        if not step.status(game, own, options).done:
            report(step.name)
            done.append("%s: %s" % (step.name, step.apply(game, own, options)))
        if took is not None:
            took.append("%s %.1f s" % (step.name, time.perf_counter() - at))
    write_list(game, own)
    return done

