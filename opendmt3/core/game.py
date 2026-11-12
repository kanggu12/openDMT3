"""A game folder: where it is, which client it has, and where the files the setup touches live.

The game folder is the one holding the client executable and pack\\ (the game's files). It may be given directly or as
any folder above it (up to four levels). Names in it are matched without letter case, as Windows matches them, so a
copy on a Linux server reads as it does on the PC it came from.

The game's files come in families: a base (name.pak) and numbered patches (name00.pak to name99.pak; the client opens
them by the pattern %s%02d.pak, up to the first number missing). For each file inside, the newest one that has it wins
(measured by where the client's reads land): layers() reads a family that way. In a whole game folder the song list is in the base and in four of its patches (the client uses the last one's),
one song's jackets are only in a patch, and a newer table of the DJ cards' experience is in a patch too.

What a client is, by content (as OpenDMTQ's inspect does it for its game): the PC client as it was released, the PC
client openDMT3 fixed, a modified PC client (another hash, with the table that opens the game's files in its
read-only data), the cabinet's client (it needs the cabinet's security keys), or none of the game's.
"""

import errno
import hashlib
import os

from opendmt3.core import parallel
from opendmt3.core.errors import Worded
from opendmt3.core.formats import pak

# Client builds by the SHA-256 of their executable. Only fingerprints are kept here, never the files.
PC_BUILD = "ae7ddbaa6f5fed30a13e5298caef79330a91b65fa237cd50135a9db6a9141dc9"
PC_BUILD_DISPLAY_FIX = "89fceb81405668be7f13f1b5bf117f372f7260623f88cf988504327daed9c260"
# The fix as the earliest versions of openDMT3 made it: the same, without the large-address flag. PLAY makes the current
# one from it (or from the PC build).
PC_BUILD_DISPLAY_FIX_EARLIER = "7a5eb11c22ddf15af9400c4d70878af40b7e4542d0e46e01c3b0c650142a8f66"
CABINET_BUILD = "cc9e20c261aa22be477085e77c99ad269a824d96becf94c578a802547a47852d"
CLIENT_BUILDS = {
    PC_BUILD: "PC build",
    PC_BUILD_DISPLAY_FIX: "PC build with the openDMT3 display fix",
    PC_BUILD_DISPLAY_FIX_EARLIER: "PC build with an earlier openDMT3 display fix (PLAY updates it)",
    CABINET_BUILD: "cabinet build (needs the cabinet's security keys; not supported)",
}
# What a client is (Game.client): the PC client as released, the PC client openDMT3 fixed, a modified PC client (its
# table found in another build), the cabinet's client.
ORIGINAL, FIXED, MODIFIED, CABINET = "original", "fixed", "modified", "cabinet"
# Programs smaller than this are no client (the client is about 12 MB; a game folder also holds a 6 KB error reporter):
# their read-only data is not searched for the table, which takes seconds for each.
CLIENT_LEAST = 1 << 20

# Names inside the game folder that the setup reads or writes.
CLIENT_EXE = "Client.exe"
FIXED_EXE = "Client (openDMT3).exe"
PACK_DIR = "pack"
SETTINGS = os.path.join("Resource", "config", "setting.ini")
DATA_DIR = "TECHNIKA"
BACKUP_DIR = "backup"
# The two files every game folder has in pack\\ (any letter case), by which a game folder is known.
MARKS = ("config.pak", "discinfo.pak")
# Families of the game's files a copy may lack, by what the game does without them (measured under Wine, a whole song
# each): the client looks for the songs' videos as movie1 to movie20, and without them plays songs on a black
# background; without the song select's previews it shows none and plays on; without the tutorial's family (its
# chart, video and voice) it stops when the tutorial starts; without the charts' family (the songs' charts and key
# sounds) it stops when a song starts.
VIDEOS = tuple("movie%d" % n for n in range(1, 21))
PREVIEWS = ("Preview", "Previewogg", "PreviewState")
TUTORIAL = "Tutorial"
CHARTS = "pattern"
# The patches of a family are numbered 00 to 99 after its base's name.
PATCHES = 100


# Fingerprints of files by their size and time (known_sha256), kept between runs in a file the launcher names
# (use_hash_cache): PLAY looks at the same game files every time, and a 12 MB client or a 9 MB archive is read again
# only when its size or time changed. Not for the backup's originals, which are always read (core/backup.py).
_known = {"path": None, "entries": {}, "changed": False}
# More entries than a game folder and openDMT3's own folder have files PLAY looks at; past this the oldest go.
KNOWN_MOST = 512


def use_hash_cache(path):
    """Keep the fingerprints known by size and time in this file (JSON), read now; one that cannot be read starts
    empty."""
    import json
    _known["path"], _known["entries"], _known["changed"] = path, {}, False
    if not path:
        # None: kept in memory only (the tests, a copy of the repository).
        return
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # Only entries of the shape written here: [size, time in ns, hex digest].
        _known["entries"] = {k: v for k, v in data.items() if isinstance(v, list) and len(v) == 3}
    except (OSError, ValueError, AttributeError):
        pass


def save_hash_cache():
    """Write the fingerprints learned since use_hash_cache, when there are new ones (the newest KNOWN_MOST)."""
    import json
    import tempfile
    if not _known["path"] or not _known["changed"]:
        return
    entries = dict(list(_known["entries"].items())[-KNOWN_MOST:])
    folder = os.path.dirname(_known["path"])
    try:
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".opendmt3-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(entries, f)
        os.replace(tmp, _known["path"])
        _known["changed"] = False
    except OSError:
        # Not kept: the next run reads the files again, nothing worse.
        pass


def known_sha256(path):
    """sha256_file, read again only when the file's size or time changed since it was last read (kept in memory, and in
    the file use_hash_cache named)."""
    st = os.stat(path)
    key = os.path.normcase(os.path.abspath(path))
    entry = _known["entries"].get(key)
    if entry and entry[0] == st.st_size and entry[1] == st.st_mtime_ns:
        return entry[2]
    digest = sha256_file(path)
    # Moved to the end, so the newest stay when the cache is cut.
    _known["entries"].pop(key, None)
    _known["entries"][key] = [st.st_size, st.st_mtime_ns, digest]
    _known["changed"] = True
    return digest


def known_as(path, digest):
    """Say a file just written holds what `digest` fingerprints (a copy of a file whose fingerprint is known): the next
    look at it by size and time needs no reading."""
    st = os.stat(path)
    key = os.path.normcase(os.path.abspath(path))
    _known["entries"].pop(key, None)
    _known["entries"][key] = [st.st_size, st.st_mtime_ns, digest]
    _known["changed"] = True


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def real_name(folder, name):
    """The name a file or folder has in `folder` when it matches `name` without letter case (the exact name first),
    or None when there is none (or the folder cannot be listed). Always from the folder's listing: where letter case
    tells no names apart (Windows, a Windows drive under WSL) a name typed in any case is there, and only the listing
    says how the folder spells it."""
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    if name in names:
        # Spelt as given.
        return name
    wanted = name.lower()
    # Sorted, so two names that differ only in case (possible on Linux) always give the same one.
    return next((n for n in sorted(names) if n.lower() == wanted), None)


class GameError(Worded):
    """Something about the folder that stops the setup, worded for the person running it (errors.py)."""


class Layers:
    """One family of the game's files read the way the client reads it: the base, then each patch in number order,
    every file taken from the newest one that has it.

    Every archive of a whole game folder opens (pak.py). One this reader cannot open (pak.PakUnreadable: another build's)
    is left out and kept in `unread`, never called damaged; one damaged or cut short is left out too and kept in
    `damaged`, so the reader of a file it needs can say so. FileNotFoundError when the family has no file in the
    folder; PermissionError when one of them cannot be read by this user (a patch left out would hide newer files);
    GameError without a client that opens the game's files."""

    def __init__(self, game, family):
        self.family = family
        # The archives opened, base first: (path, the open archive).
        self.opened = []
        # {path: why} of those left out: not readable by openDMT3 yet, or damaged.
        self.unread, self.damaged = {}, {}
        paths = game.layer_paths(family)
        if not paths:
            # Not one file of the family: said as a missing file, as opening the base would have said it.
            raise FileNotFoundError(errno.ENOENT, "no %s in the client data" % family, game.pak_path(family))
        # The client's table first, once: without a client that opens the game's files nothing is opened (GameError,
        # as the first opening said it), and the openings below share it.
        game.table()

        def opening(path):
            # (path, the open archive or what opening it raised): each on a thread of its own.
            try:
                return path, game.open_pak(path)
            except BaseException as e:  # noqa: BLE001  (sorted out below, in the family's order)
                return path, e

        # The family's files opened together (core/parallel.py): each walk waits on the drive, and the base's walk
        # (1.2 GB for the charts' family of a whole game folder) no longer holds up its patches'.
        refused = None
        for path, opened in parallel.ordered(opening, paths, name="opendmt3-open"):
            if isinstance(opened, pak.PakUnreadable):
                # The game opens it; this reader does not know its scheme yet.
                self.unread[path] = str(opened)
            elif isinstance(opened, pak.PakError):
                # Cut short, or not written by the game.
                self.damaged[path] = str(opened)
            elif isinstance(opened, BaseException):
                # A refusal (a file this user cannot read): the first in the family's order is the one said.
                refused = refused or opened
            else:
                self.opened.append((path, opened))
        if refused is not None:
            # What was opened is closed again: a family read without one of its files would hide newer ones.
            self.close()
            raise refused
        # Every file of the family by its lower-case path: the newest archive's entry wins, as in the client.
        self.index = {}
        for _, archive in self.opened:
            own = {}
            for entry in archive.entries:
                # Inside one archive the first entry of a path is the one the client keeps.
                own.setdefault(entry.name.lower(), (archive, entry))
            # A later archive (a newer patch) replaces what the ones before it had.
            self.index.update(own)

    def find(self, name):
        """(the archive, its entry) of the newest file with this path (either slash, any case), or None."""
        return self.index.get(name.replace("/", "\\").lower())

    def read(self, name):
        """The bytes of the newest file with this path, or None when no archive opened has it. pak.PakError when its
        data is damaged or cut short."""
        found = self.find(name)
        if found is None:
            return None
        archive, entry = found
        return archive.read(entry)

    def names(self):
        """Every path the family holds, in lower case."""
        return set(self.index)

    def close(self):
        """Close every archive opened."""
        for _, archive in self.opened:
            archive.close()
        self.opened = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class Game:
    def __init__(self, root):
        self.root = root
        self._table = None
        # The client the table came from, and what it is (ORIGINAL, FIXED or MODIFIED), once table() found it.
        self.client = None
        # The pack folder's names, listed once: every family's base and patches are looked up in it.
        self._pack_names = None
        # The game folder's own names, listed once (its programs are looked for there).
        self._root_names = None

    # ----------------------------------------------------------------------------------------- finding

    @classmethod
    def find(cls, path):
        """The game folder at or below path (up to four levels down). The listings that told it a game folder are
        kept on it, so nothing lists them again (each listing of a slow drive costs, 0.7 s under Wine on a shared
        one)."""
        path = os.path.abspath(path)
        listed = cls._listing(path)
        if listed:
            return cls._found(path, listed)
        base_depth = path.rstrip(os.sep).count(os.sep)
        for dirpath, dirnames, _ in os.walk(path):
            # The game's files' folder is large; never walk into it.
            dirnames[:] = [d for d in dirnames if d.lower() != PACK_DIR]
            if dirpath.count(os.sep) - base_depth > 4:
                dirnames[:] = []
                continue
            listed = cls._listing(dirpath)
            if listed:
                return cls._found(dirpath, listed)
        raise GameError("no client data (the game's PC client and its files) at or below %s" % path,
                        "error.game.no_folder", path=path)

    @classmethod
    def _found(cls, path, listed):
        game = cls(path)
        game._root_names, pack_names = listed
        # Sorted, so of two names that differ only in case the first is always the one kept (as _pack does it).
        game._pack_names = {}
        for n in sorted(pack_names):
            game._pack_names.setdefault(n.lower(), n)
        return game

    @staticmethod
    def _listing(path):
        """(the folder's names, its pack folder's names) when it is a game folder: a program (.exe) and a pack folder
        holding the two files every game folder has, in any letter case; else None."""
        try:
            names = os.listdir(path)
        except OSError:
            return None
        if not any(n.lower().endswith(".exe") for n in names):
            return None
        pack = next((n for n in sorted(names) if n.lower() == PACK_DIR), None)
        if pack is None:
            return None
        try:
            inside = os.listdir(os.path.join(path, pack))
        except OSError:
            return None
        if not all(mark in {n.lower() for n in inside} for mark in MARKS):
            return None
        return names, inside

    @staticmethod
    def _looks_like_game(path):
        """True for a folder with a program (.exe) and a pack folder holding the two files every game folder has, in
        any letter case."""
        return Game._listing(path) is not None

    # ------------------------------------------------------------------------------------------- paths

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def pack_dir(self):
        """The game's files' folder, by its own name (any letter case)."""
        if self._root_names is not None:
            listed = next((n for n in sorted(self._root_names) if n.lower() == PACK_DIR), None)
            if listed:
                return self.path(listed)
        return self.path(real_name(self.root, PACK_DIR) or PACK_DIR)

    def _pack(self):
        """{lower-case name: name} of the pack folder, listed once for this Game."""
        if self._pack_names is None:
            try:
                names = os.listdir(self.pack_dir())
            except OSError:
                names = []
            # Sorted, so of two names that differ only in case the first is always the one kept.
            self._pack_names = {}
            for n in sorted(names):
                self._pack_names.setdefault(n.lower(), n)
        return self._pack_names

    def pak_path(self, name):
        """The path of one of the game's files by its name without .pak, as the folder spells it (a name it does not
        have keeps the spelling given)."""
        wanted = name + ".pak"
        return os.path.join(self.pack_dir(), self._pack().get(wanted.lower(), wanted))

    def missing(self):
        """What of the game's files the folder lacks, by what the game does without them: "charts" and "tutorial" (the
        game stops when a song or the tutorial starts), "videos" (songs play without them), "previews" (the song select
        shows none)."""
        names = self._pack()
        out = []
        # Each by its base file, which the client opens first.
        if (CHARTS + ".pak").lower() not in names:
            out.append("charts")
        if (TUTORIAL + ".pak").lower() not in names:
            out.append("tutorial")
        if any((video + ".pak").lower() not in names for video in VIDEOS):
            out.append("videos")
        if any((preview + ".pak").lower() not in names for preview in PREVIEWS):
            out.append("previews")
        return out

    def layer_paths(self, family):
        """The paths of a family's files the client reads: its base when the folder has it, then its patches in number
        order up to the first number missing (measured: the client looks for name00.pak, name01.pak... and stops at
        the first it does not find, so a patch after a gap is never read)."""
        listed = self._pack()
        paths = [self.pak_path(family)] if (family + ".pak").lower() in listed else []
        for n in range(PATCHES):
            name = "%s%02d" % (family, n)
            if (name + ".pak").lower() not in listed:
                break
            paths.append(self.pak_path(name))
        return paths

    def layers(self, family):
        """The family read as the client reads it (Layers): use it in a `with` block."""
        return Layers(self, family)

    # ----------------------------------------------------------------------------------------- clients

    def client_build(self, name=CLIENT_EXE):
        """(sha256, description) of an executable in the folder, or (None, None) when it is missing."""
        p = self.path(name)
        if not os.path.isfile(p):
            return None, None
        digest = known_sha256(p)
        return digest, CLIENT_BUILDS.get(digest, "unknown build")

    def programs(self):
        """Every program (.exe) right in the folder, by name without letter case: [path]."""
        if self._root_names is None:
            try:
                self._root_names = os.listdir(self.root)
            except OSError:
                return []
        names = sorted(self._root_names, key=lambda n: (n.lower(), n))
        return [self.path(n) for n in names if n.lower().endswith(".exe") and os.path.isfile(self.path(n))]

    def base_client(self):
        """Path of the PC client the setup builds from, or None."""
        for p in self.programs():
            if known_sha256(p) == PC_BUILD:
                return p
        return None

    # ------------------------------------------------------------------------------------------ archives

    def table(self):
        """The 256-byte table that opens the game's files, read from the folder's client: the PC client as released,
        else the one openDMT3 fixed, else a modified PC client (any other program in the folder whose read-only data
        holds it). Sets self.client to (its path, what it is). GameError when none has it: worded for the cabinet's
        client when that is all there is."""
        if self._table is None:
            self._table, path, kind = self._find_table()
            self.client = (path, kind)
        return self._table

    def _table_of(self, path):
        """pak.load_table for a client, kept by the client's fingerprint (with the fingerprints by size and time): a
        second PLAY does not search the 12 MB client again."""
        key = "table:" + known_sha256(path)
        kept = _known["entries"].get(key)
        if kept and kept[0] == "table":
            return bytes.fromhex(kept[2])
        table = pak.load_table(path)
        _known["entries"][key] = ["table", 0, table.hex()]
        _known["changed"] = True
        return table

    def _find_table(self):
        """(table, path, kind) from the first client that holds it, in the order table() says."""
        # Each program's fingerprint, taken once (a client is 12 MB).
        digests = {p: known_sha256(p) for p in self.programs()}
        fixed = self.path(real_name(self.root, FIXED_EXE) or FIXED_EXE)
        tried = [(p, ORIGINAL) for p, d in digests.items() if d == PC_BUILD]
        if os.path.isfile(fixed):
            tried.append((fixed, FIXED))
        cabinet = False
        for p, digest in digests.items():
            if any(p == t for t, _ in tried):
                continue
            if digest == CABINET_BUILD:
                # Its table is behind the cabinet's protection, and it needs the cabinet's security keys anyway.
                cabinet = True
            elif digest in (PC_BUILD_DISPLAY_FIX, PC_BUILD_DISPLAY_FIX_EARLIER):
                # A fixed copy under another name.
                tried.append((p, FIXED))
            elif os.path.getsize(p) >= CLIENT_LEAST:
                # Another build: a modified PC client when its read-only data holds the table (a small tool beside the
                # client never does, and is not searched).
                tried.append((p, MODIFIED))
        for p, kind in tried:
            try:
                return self._table_of(p), p, kind
            except (pak.PakError, OSError, ValueError):
                # Not this one: another program of the folder, or one packed so the table cannot be seen.
                continue
        if cabinet:
            raise GameError("The cabinet's client: does not work here, the PC client is needed.",
                            "error.game.cabinet_client")
        raise GameError("The game's files cannot be opened with this client.", "error.game.no_table")

    def open_pak(self, path):
        return pak.Pak(path, self.table())
