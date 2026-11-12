"""The song list a server takes, saved by openDMT3 into one file (openDMT3-song-list.zip): the song list, its jackets
and the DJ cards, exactly as a server keeps them after reading a game folder, and nothing else of the game.

  manifest.json               what the file is and holds: {"format": "openDMT3 song list", "version": 1, "saved",
                              "by", "songs", "jackets", "cards", "missing", "reasons"}
  catalog.json                the song list
  jackets/<number>.png        each song's jacket
  cards.json                  the DJ cards' tables
  cards/<kind>/<number>.png   each DJ card picture (kind: icon, plate or pattern)

save() makes one from a data folder a reading just filled (sources.save reads any form into one first); take() takes
one into a server's data folder, with the same result as reading the game folder it was saved from: the same
catalog.json, the same cards.json and the same pictures, byte for byte, and catalog-read.json saying it came from a
song list.

A song list comes from anyone (an admin's upload, a file handed over), so take() trusts nothing in it: only the names
and kinds above, no path outside them, sizes capped (the file, each entry, all of them unpacked, how many), each JSON
of the shape openDMT3 writes, every picture decoded and encoded again at the size its kind may have, what it says it
holds checked against what it holds. Nothing is written until all of it passed; then it is moved into place at once
(catalog.swap_in), and a refused file changes nothing.
"""

import contextlib
import json
import os
import re
import struct
import time
import unicodedata
import zipfile
import zlib

from opendmt3 import __version__
from opendmt3.core.errors import Worded
from opendmt3.server.services import cards, catalog, files, pictures

# What a song list says it is, and the newest version of its form this openDMT3 writes and reads.
FORMAT = "openDMT3 song list"
VERSION = 1
# The name the launcher and ./dmt3 save it under.
NAME = "openDMT3-song-list.zip"
MANIFEST = "manifest.json"
# The largest song list taken, as uploaded (a whole game's is about 14 MB: its pictures are already compressed), and
# the most all its entries may unpack to (about 16 MB from a whole game).
MOST = 64 * 1024 * 1024
MOST_UNPACKED = 128 * 1024 * 1024
# The most entries a song list may hold (a whole game's has about 930: 177 jackets, 749 DJ card pictures, 3 tables),
# and the most its central directory may take (a whole game's takes about 60 KB; Python's zip reader holds all of it
# in memory, an object an entry, before anything counts them: 64 MB of it named 1.4 million entries, 565 MB).
MOST_ENTRIES = 8192
DIRECTORY_MOST = MOST_ENTRIES * 256
# A zip's end record, its zip64 end record and the zip64 record's locator, as the format begins them.
END, END64, LOCATOR = b"PK\x05\x06", b"PK\x06\x06", b"PK\x06\x07"
# The largest each kind of entry may be, unpacked: the tables (a whole game's catalog.json is 28 KB, cards.json 24 KB)
# and each picture (the largest DJ card picture is 33 KB; one at the largest size a kind may have stays under 600 KB).
MOST_ENTRY = {"manifest": 64 * 1024, "catalog": 4 * 1024 * 1024, "cards": 4 * 1024 * 1024, "picture": 1024 * 1024}
# Every name a song list may hold, and what each is.
NAMES = (
    (re.compile(r"manifest\.json"), "manifest"),
    (re.compile(r"catalog\.json"), "catalog"),
    (re.compile(r"cards\.json"), "cards"),
    (re.compile(r"jackets/([1-9][0-9]{0,4}|0)\.png"), "jacket"),
    (re.compile(r"cards/(icon|plate|pattern)/([1-9][0-9]{0,4}|0)\.png"), "card"),
)
# The folders those names are in, which some tools list as entries of their own.
FOLDERS = ("jackets/", "cards/", "cards/icon/", "cards/plate/", "cards/pattern/")
# A song's fields, in the order the song list's reader writes them (discstock.parse), and the longest text any of them
# holds (a whole game's longest title is 36 characters).
SONG_FIELDS = ("number", "name", "title", "genre", "composer", "star", "pop")
TEXT_MOST = 200
# The most songs, and the highest song number and DJ card number (the game keeps a plate and a pattern in 16 bits each).
SONGS_MOST = 4096
NUMBER_MOST = 99999
CARD_NUMBER_MOST = 0xFFFF
# A chart's level is 0 (no such chart) to 99; the experience tables' numbers stay under these.
LEVEL_MOST = 99
POINTS_MOST = 10_000_000
LEVELS_MOST = 1000
# The cards.json fields, in the order cards.import_from writes them.
CARD_FIELDS = cards.KINDS + ("points", "levels")
# A fixed time for every entry, so the same song list always makes the same file.
ENTRY_TIME = (2020, 1, 1, 0, 0, 0)


class SongListError(Worded):
    """A song list that is not taken, worded for whoever gave it (errors.py)."""


def _entry_error(name):
    """The refusal of one entry by its name (shortened: it comes from the file)."""
    shown = name if len(name) <= 80 else name[:77] + "..."
    return SongListError("An entry in this song list cannot be taken: %s" % shown, "error.songlist.entry", name=shown)


def _shape(part, detail):
    """The refusal of a table that is not shaped as openDMT3 writes it."""
    return SongListError("The song list's %s is not as openDMT3 saves it (%s)." % (part, detail),
                         "error.songlist.shape", part=part, detail=detail)


def too_large():
    """The refusal of an upload past MOST, in megabytes (the page, the API and the command line all raise it)."""
    mb = MOST >> 20
    return SongListError("An uploaded song list is at most %d MB." % mb, "error.songlist.too_large", mb=mb)


def no_file():
    """The refusal of an upload that brought no file (an empty one, or a form without its file)."""
    return SongListError("No song list came with the upload.", "error.songlist.no_file")


def too_many():
    """The refusal of a song list with more entries than MOST_ENTRIES (or a central directory that could name more)."""
    return SongListError("This song list holds more than %d entries. Save it again in the launcher." % MOST_ENTRIES,
                         "error.songlist.entries", n=MOST_ENTRIES)


def zip_directory(path):
    """(how many entries, how many bytes its central directory takes) as a zip's end records say them, read without
    the directory itself: the zip64 record's when there is one (at the place its locator names, or right before the
    locator: Python's readers look in either), else the end record's. None when no end record is found."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            # The end record and the longest comment after it.
            start = max(0, size - (22 + 0xFFFF))
            f.seek(start)
            tail = f.read()
            # As Python's reader finds it: right at the end when it has no comment, else the last one in the tail.
            if len(tail) >= 22 and tail[-22:-18] == END and tail[-2:] == b"\0\0":
                at = len(tail) - 22
            else:
                at = tail.rfind(END)
            if at < 0 or len(tail) - at < 22:
                return None
            # The entries on this disk and in all, and the directory's size.
            here, total, directory = struct.unpack("<HHI", tail[at + 8:at + 16])
            found = []
            locator = start + at - 20
            if locator >= 0:
                f.seek(locator)
                data = f.read(20)
                if data[:4] == LOCATOR:
                    named = struct.unpack("<Q", data[8:16])[0]
                    for place in {named, locator - 56}:
                        if 0 <= place <= size - 56:
                            f.seek(place)
                            record = f.read(56)
                            if record[:4] == END64:
                                fields = struct.unpack("<4sQHHIIQQQQ", record)
                                found.append((max(fields[6], fields[7]), fields[8]))
    except OSError:
        return None
    if found:
        # A zip64 record's numbers stand for the end record's (which say 0xFFFF and 0xFFFFFFFF then).
        return max(n for n, _ in found), max(d for _, d in found)
    return max(here, total), directory


def _too_many(path):
    """True when a zip's end records say more entries, or a larger directory, than a song list may have."""
    said = zip_directory(path)
    return said is not None and (said[0] > MOST_ENTRIES or said[1] > DIRECTORY_MOST)


# ------------------------------------------------------------------------------------------- saving

def save(data_dir, out_path, report, now=None):
    """Save the song list a reading just put in data_dir (a folder of its own, with nothing older in it) into one file
    at out_path, written whole or not at all; returns the manifest. report: the reading's (catalog.read)."""
    manifest = {"format": FORMAT, "version": VERSION, "saved": int(now if now is not None else time.time()),
                "by": "openDMT3 %s" % __version__, "songs": report["songs"], "jackets": report.get("jackets"),
                "cards": report.get("cards"), "missing": dict(report.get("missing") or {}),
                "reasons": dict(report.get("reasons") or {})}
    tmp = out_path + ".new"
    try:
        # Never through a link left at the name (files.open_new): the folder is whoever's the file goes to.
        with files.open_new(tmp) as f, zipfile.ZipFile(f, "w") as z:
            _add(z, MANIFEST, json.dumps(manifest).encode("utf-8"), zipfile.ZIP_DEFLATED)
            _add(z, catalog.FILE, _read(os.path.join(data_dir, catalog.FILE)), zipfile.ZIP_DEFLATED)
            if "jackets" not in manifest["missing"]:
                folder = os.path.join(data_dir, catalog.JACKETS)
                for name in _pictures_in(folder):
                    # Already compressed pictures are kept as they are.
                    _add(z, "%s/%s" % (catalog.JACKETS, name), _read(os.path.join(folder, name)), zipfile.ZIP_STORED)
            if "cards" not in manifest["missing"]:
                _add(z, cards.FILE, _read(os.path.join(data_dir, cards.FILE)), zipfile.ZIP_DEFLATED)
                for kind in cards.KINDS:
                    folder = os.path.join(data_dir, cards.FOLDER, kind)
                    for name in _pictures_in(folder):
                        _add(z, "%s/%s/%s" % (cards.FOLDER, kind, name), _read(os.path.join(folder, name)),
                             zipfile.ZIP_STORED)
        os.replace(tmp, out_path)
    except BaseException:
        # Nothing half written stays.
        catalog.remove(tmp)
        raise
    return manifest


def _add(z, name, data, method):
    """One entry, with the fixed time and plain permissions, so the same song list makes the same file."""
    info = zipfile.ZipInfo(name, ENTRY_TIME)
    info.compress_type = method
    # A plain file, readable by anyone who has the file (no link, no program).
    info.external_attr = 0o644 << 16
    z.writestr(info, data)


def _pictures_in(folder):
    """The pictures in a folder of the data folder, by number."""
    try:
        names = [n for n in os.listdir(folder) if re.fullmatch(r"\d+\.png", n)]
    except OSError:
        return []
    return sorted(names, key=lambda n: int(n[:-4]))


def _read(path):
    with open(path, "rb") as f:
        return f.read()


# ------------------------------------------------------------------------------------------- taking in

def take(path, data_dir, now=None, shown_as=None):
    """Take the song list at `path` into data_dir: every check first (SongListError for the first that fails, and
    nothing changes), then everything moved into place at once. Returns the report kept as catalog-read.json, which
    says it came from a song list (shown_as: the name to keep for it, the file's own name by default)."""
    if not pictures.available():
        raise SongListError("This server cannot check pictures: it has no Pillow.", "error.songlist.no_pillow")
    try:
        size = os.path.getsize(path)
    except OSError:
        raise no_file() from None
    if not size:
        raise no_file()
    if size > MOST:
        raise too_large()
    if _too_many(path):
        # Counted by its end records, before Python's zip reader reads every entry of the directory into memory.
        raise too_many()
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, zlib.error, EOFError, ValueError):
        # Not a zip at all: not a song list openDMT3 saved.
        raise SongListError("This is not a song list saved by openDMT3.", "error.songlist.not_ours") from None
    with z:
        try:
            checked = _check(z)
        except (zipfile.BadZipFile, zlib.error, EOFError, OSError, NotImplementedError, RuntimeError):
            # An entry whose bytes do not unpack to what its header says (a CRC, a cut, an unknown method).
            raise SongListError("This song list is damaged. Save it again in the launcher.",
                                "error.songlist.damaged") from None
    manifest, songs, tables, jackets, card_pictures = checked
    os.makedirs(data_dir, exist_ok=True)
    staging = catalog.new_staging(data_dir)
    try:
        # Written from what was checked, in the form a reading writes it: the same bytes as a game folder's reading.
        catalog._write_json(os.path.join(staging, catalog.FILE), {"songs": songs}, ensure_ascii=False)
        missing = manifest["missing"]
        if "jackets" not in missing:
            folder = os.path.join(staging, catalog.JACKETS)
            os.makedirs(folder)
            for number, data in jackets.items():
                _write(os.path.join(folder, "%d.png" % number), data)
        if "cards" not in missing:
            for kind in cards.KINDS:
                folder = os.path.join(staging, cards.FOLDER, kind)
                os.makedirs(folder)
                for number, data in card_pictures[kind].items():
                    _write(os.path.join(folder, "%d.png" % number), data)
            catalog._write_json(os.path.join(staging, cards.FILE), tables)
        report = {"at": int(now if now is not None else time.time()), "from": "file",
                  "path": shown_as or os.path.basename(path), "folder": None, "made": manifest["saved"],
                  "songs": len(songs), "jackets": None if "jackets" in missing else len(jackets),
                  "cards": None if "cards" in missing else {kind: len(tables[kind]) for kind in cards.KINDS},
                  "missing": dict(missing), "reasons": dict(manifest["reasons"])}
        catalog.swap_in(staging, data_dir, report)
    finally:
        catalog.remove(staging)
    catalog.give_to_owner(data_dir)
    return report


def _write(path, data):
    # A new file in the reading's own folder, never through a link at its name.
    with files.open_new(path) as f:
        f.write(data)


def is_song_list(path):
    """True when `path` is a zip holding a manifest that says it is a song list openDMT3 saved (any version): what a
    path is, by its content, before it is taken (sources.py)."""
    if _too_many(path):
        # More entries than a song list has: none, and its directory is never read into memory.
        return False
    try:
        with zipfile.ZipFile(path) as z:
            info = z.getinfo(MANIFEST)
            if info.file_size > MOST_ENTRY["manifest"]:
                return False
            manifest = json.loads(z.read(info).decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError,
            RuntimeError):
        return False
    return isinstance(manifest, dict) and manifest.get("format") == FORMAT


def look(path):
    """What a song list holds by its manifest, without taking it (the wizard's and the Status page's first look):
    {"songs", "jackets", "cards", "missing", "saved", "version"}; SongListError when it is none, or from a newer
    openDMT3. The whole check is take()'s."""
    if _too_many(path):
        raise too_many()
    try:
        with zipfile.ZipFile(path) as z:
            info = z.getinfo(MANIFEST)
            if info.file_size > MOST_ENTRY["manifest"]:
                raise _entry_error(MANIFEST)
            manifest = _manifest(z.read(info))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError,
            RuntimeError):
        # Not a zip, no manifest, or one that does not read: not a song list openDMT3 saved.
        raise SongListError("This is not a song list saved by openDMT3.", "error.songlist.not_ours") from None
    return manifest


def _check(z):
    """Every check of an open song list, nothing written: (manifest, songs, the DJ cards' tables, {song number: jacket
    bytes}, {kind: {number: picture bytes}}), the pictures already in the server's one form."""
    infos = z.infolist()
    if len(infos) > MOST_ENTRIES:
        # End records that said fewer than the directory held: the same words.
        raise too_many()
    kinds, seen, unpacked = {}, set(), 0
    for info in infos:
        name = info.filename
        if name in FOLDERS:
            # A folder entry some tools write: nothing to take from it.
            continue
        kind = next((k for pattern, k in NAMES if pattern.fullmatch(name)), None)
        # Only the known names: none with another folder, a backslash, a drive, "..", or anything else.
        if kind is None or name in seen:
            raise _entry_error(name)
        seen.add(name)
        # No link and no program: a plain file (the unix kind bits, when a tool wrote them, say a regular file).
        mode = info.external_attr >> 16
        if mode and (mode & 0o170000) not in (0, 0o100000):
            raise _entry_error(name)
        # Neither encrypted nor packed in a way other than the two openDMT3 writes.
        if info.flag_bits & 0x1 or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise _entry_error(name)
        if info.file_size > MOST_ENTRY["picture" if kind in ("jacket", "card") else kind]:
            raise _entry_error(name)
        unpacked += info.file_size
        if unpacked > MOST_UNPACKED:
            raise SongListError("This song list holds more than %d MB unpacked." % (MOST_UNPACKED >> 20),
                                "error.songlist.unpacked", mb=MOST_UNPACKED >> 20)
        kinds[name] = kind
    if MANIFEST not in kinds or catalog.FILE not in kinds:
        # Without its manifest and its list it is no song list openDMT3 saved.
        raise SongListError("This is not a song list saved by openDMT3.", "error.songlist.not_ours")
    manifest = _manifest(_entry(z, MANIFEST))
    songs = _songs(_entry(z, catalog.FILE))
    numbers = {song["number"] for song in songs}
    missing = manifest["missing"]
    # The jackets: only of songs on the list, none when the list says they are missing.
    jackets = {}

    def jacket_entries():
        # Each jacket's entry checked against the list and read here, one after another (one zip, one position).
        for name in sorted(n for n, k in kinds.items() if k == "jacket"):
            number = int(name[len("jackets/"):-4])
            if "jackets" in missing or number not in numbers:
                raise _entry_error(name)
            yield (name, number), (name, "jacket")
    for (name, number), picture in _pictures(z, jacket_entries()):
        jackets[number] = picture
    tables, card_pictures = None, {kind: {} for kind in cards.KINDS}
    if cards.FILE in kinds:
        if "cards" in missing:
            raise _entry_error(cards.FILE)
        tables = _tables(_entry(z, cards.FILE))

    def card_entries():
        # Each DJ card picture's entry checked against the tables and read here, one after another.
        for name in sorted(n for n, k in kinds.items() if k == "card"):
            _, kind, file_name = name.split("/")
            number = int(file_name[:-4])
            # Only pictures the tables offer.
            if tables is None or number not in {item["number"] for item in tables[kind]}:
                raise _entry_error(name)
            yield (name, kind, number), (name, kind)
    for (name, kind, number), picture in _pictures(z, card_entries()):
        card_pictures[kind][number] = picture
    _counts(manifest, songs, jackets, tables, card_pictures)
    return manifest, songs, tables, jackets, card_pictures


def _entry(z, name):
    """An entry's bytes, read no further than its size allows (the header's size is checked against the limits; the
    reader stops at it and checks the CRC)."""
    with z.open(name) as f:
        return f.read()


def _json(data, part):
    """JSON text as data; the shape refusal when it is not JSON in UTF-8."""
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise _shape(part, "not JSON") from None


def _manifest(data):
    """The manifest, checked: what openDMT3 writes, of a version this server reads."""
    manifest = _json(data, "manifest")
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise SongListError("This is not a song list saved by openDMT3.", "error.songlist.not_ours")
    version = manifest.get("version")
    if not _whole(version, 1, 1 << 30):
        raise _shape("manifest", "its version")
    if version > VERSION:
        # Saved by a newer openDMT3: its form may hold what this server does not know.
        raise SongListError("This song list was saved by a newer openDMT3 (format %d; this server reads up to %d)."
                            % (version, VERSION), "error.songlist.newer", format=version, most=VERSION)
    if set(manifest) != {"format", "version", "saved", "by", "songs", "jackets", "cards", "missing", "reasons"}:
        raise _shape("manifest", "its fields")
    if not _whole(manifest["saved"], 0, 1 << 40) or not _text(manifest["by"], 64):
        raise _shape("manifest", "when and by what it was saved")
    if not _whole(manifest["songs"], 0, SONGS_MOST) or not (manifest["jackets"] is None
                                                             or _whole(manifest["jackets"], 0, SONGS_MOST)):
        raise _shape("manifest", "its counts")
    counts = manifest["cards"]
    if counts is not None and not (isinstance(counts, dict) and set(counts) == set(cards.KINDS)
                                   and all(_whole(v, 0, CARD_NUMBER_MOST + 1) for v in counts.values())):
        raise _shape("manifest", "its DJ cards' counts")
    missing, reasons = manifest["missing"], manifest["reasons"]
    if not (isinstance(missing, dict) and set(missing) <= set(catalog.OPTIONAL)
            and all(_text(v, 500) for v in missing.values())):
        raise _shape("manifest", "what it says is missing")
    from opendmt3.core import errors
    # A reason's key is one of openDMT3's words, or none.
    if not (isinstance(reasons, dict) and set(reasons) <= set(missing)
            and all(v is None or (isinstance(v, str) and v in errors.TEXT) for v in reasons.values())):
        raise _shape("manifest", "why parts are missing")
    return manifest


def _songs(data):
    """The song list's songs, checked field by field and rebuilt in the reader's order."""
    shaped = _json(data, "song list")
    if not isinstance(shaped, dict) or set(shaped) != {"songs"} or not isinstance(shaped["songs"], list):
        raise _shape("song list", "not a list of songs")
    if len(shaped["songs"]) > SONGS_MOST:
        raise _shape("song list", "more than %d songs" % SONGS_MOST)
    songs, numbers = [], set()
    for song in shaped["songs"]:
        if not isinstance(song, dict) or set(song) != set(SONG_FIELDS):
            raise _shape("song list", "a song's fields")
        if not _whole(song["number"], 0, NUMBER_MOST) or song["number"] in numbers:
            raise _shape("song list", "a song's number")
        numbers.add(song["number"])
        if not all(_text(song[field], TEXT_MOST) for field in ("name", "title", "genre", "composer")):
            raise _shape("song list", "a song's words")
        for column in ("star", "pop"):
            levels = song[column]
            if not (isinstance(levels, list) and len(levels) == 4 and all(_whole(v, 0, LEVEL_MOST) for v in levels)):
                raise _shape("song list", "a song's levels")
        # The reader's own order of fields, whatever order the file has them in.
        songs.append({field: song[field] for field in SONG_FIELDS})
    return songs


def _tables(data):
    """The DJ cards' tables, checked and rebuilt in the order cards.import_from writes them."""
    shaped = _json(data, "DJ cards")
    if not isinstance(shaped, dict) or set(shaped) != set(CARD_FIELDS):
        raise _shape("DJ cards", "its tables")
    tables = {}
    for kind in cards.KINDS:
        items = shaped[kind]
        if not isinstance(items, list) or len(items) > CARD_NUMBER_MOST + 1:
            raise _shape("DJ cards", "the %ss" % kind)
        rows, numbers = [], set()
        for item in items:
            if not (isinstance(item, dict) and set(item) == {"number", "grade"}
                    and _whole(item["number"], 0, CARD_NUMBER_MOST) and item["number"] not in numbers
                    and _text(item["grade"], 8)):
                raise _shape("DJ cards", "a %s" % kind)
            numbers.add(item["number"])
            rows.append({"number": item["number"], "grade": item["grade"]})
        tables[kind] = rows
    points = shaped["points"]
    if not (isinstance(points, dict) and len(points) <= LEVELS_MOST
            and all(re.fullmatch(r"[0-9]{1,4}", k) and _whole(v, 0, POINTS_MOST) for k, v in points.items())):
        raise _shape("DJ cards", "the experience points")
    tables["points"] = dict(points)
    levels = shaped["levels"]
    if not (isinstance(levels, list) and len(levels) <= LEVELS_MOST
            and all(_whole(v, 0, POINTS_MOST * 100) for v in levels)):
        raise _shape("DJ cards", "the levels")
    tables["levels"] = list(levels)
    return tables


def _pictures(z, entries):
    """(tag, the picture in the server's one form) for each (tag, (name, kind)) of `entries` in their order: each
    entry read here, then checked and converted side by side with the next ones (pictures.in_order). SongListError
    for the first, in that order, that cannot be kept, as one at a time would say it."""
    read = ((tag, (name, kind, _entry(z, name))) for tag, (name, kind) in entries)

    def converted(item):
        # On a picture thread: the bytes in the one form, or the PictureError that says why not.
        name, kind, data = item
        return pictures.canonical(data, kind)
    with contextlib.closing(pictures.in_order(read, converted)) as done:
        for tag, picture in done:
            if isinstance(picture, pictures.PictureError):
                name, detail = tag[0], str(picture)
                raise SongListError("A picture in this song list cannot be taken: %s (%s)." % (name, detail),
                                    "error.songlist.picture", name=name, detail=detail) from None
            yield tag, picture


def _counts(manifest, songs, jackets, tables, card_pictures):
    """What the manifest says the song list holds, against what it holds; and every DJ card it offers has its picture
    (but the pattern "none", which a reading offers without one), as a reading leaves them."""
    def refuse(detail):
        return SongListError("The song list does not hold what it says it holds (%s)." % detail,
                             "error.songlist.counts", detail=detail)
    missing = manifest["missing"]
    if manifest["songs"] != len(songs):
        raise refuse("songs")
    if "jackets" in missing:
        if manifest["jackets"] is not None:
            raise refuse("jackets")
    elif manifest["jackets"] != len(jackets):
        raise refuse("jackets")
    if "cards" in missing:
        if manifest["cards"] is not None or tables is not None:
            raise refuse("DJ cards")
        return
    if tables is None or manifest["cards"] != {kind: len(tables[kind]) for kind in cards.KINDS}:
        raise refuse("DJ cards")
    for kind in cards.KINDS:
        offered = {item["number"] for item in tables[kind]}
        without = offered - set(card_pictures[kind]) - ({cards.PATTERN} if kind == "pattern" else set())
        if without:
            raise refuse("DJ cards")


def _whole(value, least, most):
    """True for a whole number (not a bool) from least to most."""
    return isinstance(value, int) and not isinstance(value, bool) and least <= value <= most


def _text(value, most):
    """True for text of at most `most` characters without a control character or a lone surrogate (a title may hold
    any other letter or space a build of the game has)."""
    return isinstance(value, str) and len(value) <= most and not any(
        unicodedata.category(c) in ("Cc", "Cs") for c in value)
