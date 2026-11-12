"""The DJ card: what the game shows for a player beside their name, and the choices a player has for it.

The game draws the card from the player's details (0x65): a level, an icon, a title plate with a pattern drawn over
it, and a one-line comment over the plate. The pictures, and the tables that number them, are in the player's own
game files. Whoever runs the server reads them from there with the song list (catalog.py): the tables go in
cards.json and the pictures, small as they are, in cards/<kind>/<number>.png, so the site can offer them. Nothing of
it ships with openDMT3; without it, every card keeps the defaults below.

The level comes from experience, which the game turns into a level with its own table (expTitle). The server adds
experience up from the stages a player cleared, by the game's table of points per chart level and rank
(ResultExpPoint). The rank is not read from the results yet, so every cleared stage counts as an A.
"""

import contextlib
import json
import logging
import os

from opendmt3.core import game as g
from opendmt3.core.errors import Worded
from opendmt3.core.formats import pak as P
from opendmt3.server.services import files, pictures

log = logging.getLogger("opendmt3.cards")

FILE = "cards.json"
FOLDER = "cards"
KINDS = ("icon", "plate", "pattern")

# A new card (each value seen on the game's screen): the basic DJ icon, the Platinum Crew plate, no pattern.
ICON, PLATE, PATTERN = 1, 0x8001, 0
COMMENT_MAX = 12            # the game sizes the comment's letters for 1 to 12 characters (UserTitleCommentSize)
RANK = "A"                  # the rank every cleared stage counts as, until the results give theirs

# The tables, in the game's script files (the newest of the base and its patches that has each one).
TABLES = {
    "icon": "Resource\\Script\\Uidata\\icon.csv",
    "plate": "Resource\\Script\\Uidata\\UserTitlePlate.csv",
    "pattern": "Resource\\Script\\Uidata\\UserTitlePattern.csv",
    "points": "Resource\\Script\\Item\\ResultExpPoint.csv",
    "levels": "Resource\\Script\\Uidata\\expTitle.csv",
}
# The family of the game's files each kind's pictures are in.
PICTURES = {"icon": "Icon", "plate": "emblem", "pattern": "emblem"}


class CardError(Worded, ValueError):
    """A choice the game's tables do not have, worded for the player who made it (errors.py)."""


# ------------------------------------------------------------------------------------------- reading

def _text(raw):
    """A table's text: UTF-16 when it starts with a byte-order mark, the game's Korean code page otherwise."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    return raw.decode("cp949", "replace")


def _rows(raw):
    """The table's rows as lists of cells (tabs or commas, whichever the header uses), header first."""
    lines = [line for line in _text(raw).splitlines() if line.strip()]
    separator = "\t" if lines and "\t" in lines[0] else ","
    return [[cell.strip() for cell in line.split(separator)] for line in lines]


def _pictures_table(raw):
    """{number: (archive path, grade)} from icon.csv or UserTitlePlate/Pattern.csv (Index, path, file, grade)."""
    found = {}
    for row in _rows(raw)[1:]:
        if len(row) < 3 or not row[0].isdigit():
            continue
        # The folder and the name join into the archive's path; the tables mix both slashes.
        folder = row[1].replace("/", "\\").rstrip("\\")
        found[int(row[0])] = (folder + "\\" + row[2], row[3] if len(row) > 3 else "")
    return found


def _points(raw):
    """{chart level: experience for a stage cleared at RANK} from ResultExpPoint.csv (Level, S++, ..., F)."""
    rows = _rows(raw)
    column = rows[0].index(RANK)
    return {int(row[0]): int(row[column]) for row in rows[1:] if row and row[0].isdigit() and len(row) > column}


def _levels(raw):
    """The experience each level holds up to, in level order, from expTitle.csv (name, number, experience, ...)."""
    rows = _rows(raw)[1:]
    return [int(row[2]) for row in sorted((r for r in rows if len(r) > 2 and r[1].isdigit()), key=lambda r: int(r[1]))]


def _damaged():
    """The DJ cards' files damaged or cut short (one of the family's files, or a table or picture in one), as one
    plain line with the thing to do."""
    return g.GameError("The file with the DJ cards is damaged. Copy the client data again, or unpack the archive again.",
                       "error.game.damaged.cards")


def _layers(game, family):
    """A family of the game's files (game.Layers); CardError when the folder has none of it."""
    try:
        return game.layers(family)
    except FileNotFoundError:
        raise CardError("the game's files have no DJ cards", "error.card.tables") from None


def _read_tables(game):
    """Each table's bytes from the newest of the script files that has it (a patch replaces the base's), as the client
    reads them; a patch this reader cannot open (another build's) is left out. GameError (damaged) when one of
    them is damaged or cut short: a newer table in it would be read as an older one."""
    with _layers(game, "Script") as layers:
        if layers.damaged:
            raise _damaged()
        found = {}
        for key, name in TABLES.items():
            try:
                data = layers.read(name)
            except P.PakError:
                # The table's own bytes are cut short or not the game's.
                raise _damaged() from None
            if data is not None:
                found[key] = data
    return found


def _tables(game):
    """The tables parsed: ({kind: the pictures' table}, the experience points, the levels). CardError when one of the
    tables is not there, GameError (damaged) when one is not shaped as the game's (a column missing, a number that is
    none)."""
    raw = _read_tables(game)
    if not all(key in raw for key in TABLES):
        raise CardError("the game's files have no DJ cards", "error.card.tables")
    try:
        return ({kind: _pictures_table(raw[kind]) for kind in KINDS}, _points(raw["points"]),
                _levels(raw["levels"]))
    except (ValueError, IndexError, UnicodeError):
        # The table is there but not as the game writes it: half-written, or not the game's.
        raise _damaged() from None


def _each_picture(game, tables):
    """(kind, number, grade, picture bytes) for each number the tables name and the game's files have a picture for,
    kind by kind in KINDS' order, numbers in order. Each picture from the newest file that has it."""
    for kind in KINDS:
        with _layers(game, PICTURES[kind]) as layers:
            if layers.damaged:
                # A damaged file may hold newer pictures: none is offered from a family that has one.
                raise _damaged()
            for number, (path, grade) in sorted(tables[kind].items()):
                found = layers.find(path)
                if found is None:
                    # A number without a picture (some plates have none) is not offered: the game shows nothing.
                    continue
                archive, entry = found
                try:
                    data = archive.read(entry)
                except P.PakError:
                    raise _damaged() from None
                yield kind, number, grade, data


def survey(game):
    """{kind: how many pictures import_from would offer} without saving anything (./dmt3 setup's live check);
    CardError when the tables are missing, OSError when the game's files cannot be opened, GameError when one that
    holds them is damaged."""
    tables, _, _ = _tables(game)
    names = {}
    # Each family opened once (the plates and the patterns share one): opening walks every entry, slow on a network
    # or a Windows drive.
    for family in sorted(set(PICTURES.values())):
        with _layers(game, family) as layers:
            if layers.damaged:
                raise _damaged()
            names[family] = layers.names()
    counts = {kind: sum(path.lower() in names[PICTURES[kind]] for path, _ in tables[kind].values()) for kind in KINDS}
    # A pattern of 0 is "none", offered even without a picture, as import_from offers it.
    if 0 not in tables["pattern"]:
        counts["pattern"] += 1
    return counts


def import_from(game, data_dir):
    """Read the card tables and pictures from a game folder into data_dir; returns how many pictures were saved.

    Each picture is kept in the server's one form (pictures.canonical) when Pillow is there, so a song list taken in
    later gives the same bytes; one that does not decode, or is larger than a DJ card's picture may be, is not
    offered. Without Pillow the game's own bytes are kept."""
    tables, points, levels = _tables(game)
    keep = pictures.available()
    saved, offered = 0, {kind: [] for kind in KINDS}
    for kind in KINDS:
        os.makedirs(os.path.join(data_dir, FOLDER, kind), exist_ok=True)
    # Each picture tagged with what it is, its kind riding along with its bytes to its thread.
    read = (((kind, number, grade), (kind, data)) for kind, number, grade, data in _each_picture(game, tables))

    def kept(item):
        # In the one form on a picture thread (pictures.in_order); the game's own bytes without Pillow.
        kind, data = item
        return pictures.canonical(data, kind) if keep else data
    # Converted side by side, each handed back in the tables' order: the same files and the same tables as one after
    # another (closing: no picture thread outlives the reading, whatever stops it).
    with contextlib.closing(pictures.in_order(read, kept, None if keep else 1)) as converted:
        for (kind, number, grade), data in converted:
            if isinstance(data, pictures.PictureError):
                # Not offered, as a number without a picture is not: the game would show nothing for it either.
                log.info("left out %s %d: its picture cannot be kept", kind, number)
                continue
            target = os.path.join(data_dir, FOLDER, kind, "%d.png" % number)
            # Never through a link left at the name (files.open_new).
            with files.open_new(target + ".new") as f:
                f.write(data)
            os.replace(target + ".new", target)
            offered[kind].append({"number": number, "grade": grade if grade not in ("-",) else ""})
            saved += 1
    # A pattern of 0 is "none", always there (its picture is an empty one).
    if not any(p["number"] == 0 for p in offered["pattern"]):
        offered["pattern"].insert(0, {"number": 0, "grade": ""})
    data = dict(offered, points={str(k): v for k, v in points.items()}, levels=levels)
    tmp = os.path.join(data_dir, FILE + ".new")
    with files.open_new(tmp, text=True) as f:
        json.dump(data, f)
    os.replace(tmp, os.path.join(data_dir, FILE))
    return saved


def load(data_dir):
    """The saved tables, or {} before any were read. Read once and kept while the file stays the same (files.py):
    the answer is shared, so it cannot be changed (dict() of it can)."""
    return files.load(os.path.join(data_dir, FILE), missing=files.FrozenDict())


def picture(data_dir, kind, number):
    """A saved picture's path, or None."""
    if kind not in KINDS:
        return None
    path = os.path.join(data_dir, FOLDER, kind, "%d.png" % int(number))
    return path if os.path.isfile(path) else None


# ------------------------------------------------------------------------------------------- the card

def title(plate, pattern):
    """The game's one number for the plate and the pattern over it: the pattern high, the plate low."""
    return (int(pattern) << 16) | int(plate)


def level(tables, exp):
    """The level the game shows for this much experience (the first level that holds it), or None without tables."""
    for number, top in enumerate(tables.get("levels") or [], start=1):
        if exp <= top:
            return number
    return len(tables["levels"]) if tables.get("levels") else None


def experience(tables, catalog, cleared):
    """The experience of the stages cleared: rows of (mode, song, pattern, how many times) and the song list's
    levels (catalog.level). A chart whose level is not known counts as level 1."""
    from opendmt3.server.services.catalog import level as chart_level
    points = {int(k): v for k, v in (tables.get("points") or {}).items()}
    if not points:
        return 0
    # The table stops at the game's highest level; anything above counts as the top (found once, not per chart).
    top = max(points)
    total = 0
    for mode, song, pattern, times in cleared:
        at = chart_level(catalog, song, mode, pattern) or 1
        total += points.get(min(at, top), 0) * times
    return total


def numbers(tables, kind):
    """The numbers of one kind the game has pictures for (as read); empty before any tables were read."""
    return {item["number"] for item in tables.get(kind, [])}


def check(tables, icon=None, plate=None, pattern=None, comment=None):
    """Refuse a choice the game has no picture for, or a comment it cannot show; values left as None are not checked.

    Before the tables are read only the defaults are taken: a number the game does not have may crash it."""
    def missing(kind, value, default):
        # A whole number the tables have a picture for (before any were read, only the default).
        return value is not None and (type(value) is not int or value not in (numbers(tables, kind) or {default}))
    if missing("icon", icon, ICON):
        raise CardError("there is no icon %s" % icon, "error.card.icon", number=icon)
    if missing("plate", plate, PLATE):
        raise CardError("there is no plate %s" % plate, "error.card.plate", number=plate)
    if missing("pattern", pattern, PATTERN):
        raise CardError("there is no plate pattern %s" % pattern, "error.card.pattern", number=pattern)
    # Counted as the game stores it (UTF-16 places); only printable letters (no line breaks).
    if comment is not None and (len(comment.encode("utf-16-le")) // 2 > COMMENT_MAX or not comment.isprintable()):
        raise CardError("a comment is up to %d characters" % COMMENT_MAX, "error.card.comment", max=COMMENT_MAX)


def _kept(tables, kind, value, default):
    """The account's choice when the tables still have it, else the default (tables read again from other game
    files may lack a number chosen before; the game must never get a number it has no picture for)."""
    return value if value in (numbers(tables, kind) or {default}) else default


def shown(row, tables):
    """The icon, plate and pattern an account's card shows: its choices the tables still have, else the defaults."""
    return (_kept(tables, "icon", row["icon"], ICON), _kept(tables, "plate", row["plate"], PLATE),
            _kept(tables, "pattern", row["pattern"], PATTERN))


def of(row, tables, catalog, records):
    """What the game's 0x65 needs for an account row: experience, icon, title and comment."""
    cleared = records.cleared(row["id"]) if records is not None else []
    icon, plate, pattern = shown(row, tables)
    return {"exp": experience(tables, catalog, cleared), "icon": icon, "title": title(plate, pattern),
            "comment": row["comment"]}


def view(row, tables, catalog, cleared):
    """An account's card as the site, the API and the launcher show it: the choices shown, the comment, the
    experience and the level the game gives it, and whether the server has the pictures."""
    icon, plate, pattern = shown(row, tables)
    exp = experience(tables, catalog, cleared)
    return {"icon": icon, "plate": plate, "pattern": pattern, "comment": row["comment"], "exp": exp,
            "level": level(tables, exp), "pictures": bool(tables.get("icon"))}
