"""Which songs the game offers, and which of them have no charts, so the card can say so before the game stops on one.

The game offers a song when one of its modes' tables names it, each read from the newest file that has it (the
client's modes are STAR, POP, CLUB, CREW RACE and CREW CHALLENGE, and these are the tables it names):

  STAR and POP     the stage lists, star_stage_1.csv to star_stage_bonus.csv and the same four of POP, by the song's
                   internal name (162 songs in a whole game folder)
  CLUB             the disc sets (Script\\ClubDiscSetInfo\\DiscSetInfo.csv), each set's songs in the song list's
                   family's table named after the set, by song number: the songs of its stages, its hidden songs, and
                   the RANDOMIZER set's pool (169 songs; 13 of them on no stage list, ten longer versions among them,
                   each a set of its own)
  CREW CHALLENGE   the crew missions the game keeps (Script\\DefaultMission\\DefaultMission.csv), by song number (52,
                   all of them songs of the modes above)

No table of the game's files names CREW RACE's songs. A row of the song list that no mode's table names is never
shown to a player, so the card counts neither it nor its charts: in a whole game folder 175 of the song list's 177
rows are offered, and the two rows without charts are the two no table names. The server's song list keeps every
row, for the titles and levels of the records.

Measured under Wine: when a song starts, the client opens its chart (pattern\\<the song's internal name>\\<name>_star_1.pt
for STAR's first level, from the charts' family of files); without it the game stops. The song select first shows the
first song of the first stage's list of the mode chosen (the stage lists, star_stage_1.csv for STAR, the mode a guest
starts in), so a copy whose first song has no charts stops at once; one where other songs have none plays until one of
those is chosen.

Reading the charts' family's names is the slow part (56,446 files in a whole game folder: 11.5 s on a shared drive),
so the answer is kept in a file of openDMT3's, by the size and time of each file of the charts', the song list's and
the script families: it is worked out again only when one of them changed, or when it was kept by an openDMT3 that
worked it out another way (VERSION), and only off the window's thread (the card's look, the ready check).
"""

import contextlib

import json
import os
import re
import tempfile
import threading

from opendmt3.core import game as g
from opendmt3.core.formats import discstock, pak

# The stage lists whose first song each mode's song select shows first (star_stage_1.csv: STAR, the guest's first).
FIRST_LISTS = re.compile(r"^resource\\discinfo\\(star|pop|duo)_stage_1\.csv$")
# The stage lists STAR's and POP's song selects offer songs from: stages 1 to 3 and the bonus stage, the eight the client
# names. The DUO lists beside them are named by no string of the client (DUO is none of its modes).
STAGE_LISTS = re.compile(r"^resource\\discinfo\\(star|pop)_stage_(1|2|3|bonus)\.csv$")
# CLUB's disc sets: one row each, the set's name in the second cell; the set's own table is in the song list's family.
DISC_SETS = "Resource\\Script\\ClubDiscSetInfo\\DiscSetInfo.csv"
DISC_SET_TABLE = "Resource\\DiscInfo\\%s.csv"
# CREW CHALLENGE's crew missions as the game keeps them: up to three songs each, by number (MUSICNUM1 to MUSICNUM3).
CREW_MISSIONS = "Resource\\Script\\DefaultMission\\DefaultMission.csv"
CREW_SONG_COLUMN = re.compile(r"^MUSICNUM\d+$")
# The family the disc sets and the crew missions are in.
SCRIPT = "Script"
# A chart: pattern\<song>\<anything>.pt (the folder's name is the song's internal name).
CHART = re.compile(r"^pattern\\([^\\]+)\\[^\\]+\.pt$")
# How the kept answers are worked out: an answer kept with another (or none: before the card counted only the songs
# offered, before every mode's tables were read, and before every file of a whole game folder opened) is worked out
# again, though no file changed.
VERSION = 3


def _stamps(game):
    """The charts', the song list's and the script families by size and time: what the kept answer was worked out
    from."""
    out = []
    for family in (g.CHARTS, "DiscInfo", SCRIPT):
        for path in game.layer_paths(family):
            try:
                st = os.stat(path)
            except OSError:
                continue
            out.append([os.path.basename(path).lower(), st.st_size, st.st_mtime_ns])
    return out


def _table(layers, name):
    """A table's rows, header first, as lists of stripped cells, from the newest file that has it: UTF-16 when it starts
    with a byte-order mark, the client's Korean code page otherwise, cells split by tabs when the header has one and by
    commas otherwise. None when no file of the family has it; [] when its bytes are damaged (what it names is then not
    counted)."""
    try:
        raw = layers.read(name)
    except pak.PakError:
        return []
    if raw is None:
        return None
    text = raw.decode("utf-16", "replace") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("cp949", "replace")
    # Blank lines (a table's last one) are no rows.
    lines = [line for line in text.splitlines() if line.strip()]
    separator = "\t" if lines and "\t" in lines[0] else ","
    return [[cell.strip() for cell in line.split(separator)] for line in lines]


def _numbers(rows, first, column):
    """The song numbers a table names: in each row after the header, its first cell when `first`, and the cells of each
    column whose header `column` takes. A cell that is no number names no song."""
    if not rows:
        return set()
    columns = ([0] if first else []) + [i for i, cell in enumerate(rows[0]) if column(cell)]
    return {int(row[i]) for row in rows[1:] for i in columns if i < len(row) and row[i].isdigit()}


def _first_songs(layers):
    """The internal names of the first song of each first-stage list the game has."""
    names = []
    for name in sorted(layers.names()):
        if not FIRST_LISTS.match(name):
            continue
        # The rows after the header; the first one is the song the song select shows first.
        rows = (_table(layers, name) or [])[1:]
        if rows and len(rows[0]) > 1 and rows[0][1]:
            names.append(rows[0][1])
    return names


def _offered(info, script):
    """The song list's rows the game offers, in the list's order: those a table of one of its modes names (the module's
    docstring). `info` is the song list's family, `script` the script family (None when the folder has none: then no
    disc set or crew mission is read). None when the game's files have no song list."""
    listed = info.read(discstock.PATH)
    if listed is None:
        return None
    names, numbers = set(), set()
    for name in info.names():
        if STAGE_LISTS.match(name):
            for row in (_table(info, name) or [])[1:]:
                # STAR and POP: the internal name is each row's second cell, as the first-song check reads it.
                if len(row) > 1 and row[1]:
                    names.add(row[1].lower())
    if script is not None:
        for row in (_table(script, DISC_SETS) or [])[1:]:
            if len(row) > 1 and row[1]:
                # CLUB: the set's own table by the set's name; its stages' songs by number in the first cell, its hidden
                # songs in each hidden_number column. By number: a single-song set's second cell is a title to show
                # ("~ Y ~ Extended Mix"), not an internal name.
                numbers |= _numbers(_table(info, DISC_SET_TABLE % row[1]), True, lambda c: c.lower() == "hidden_number")
        # CREW CHALLENGE: each crew mission's songs by number.
        numbers |= _numbers(_table(script, CREW_MISSIONS), False, lambda c: bool(CREW_SONG_COLUMN.match(c.upper())))
    # Rows without an internal name are no song; names match without letter case, as the client's paths do.
    return [s for s in discstock.parse(listed)
            if s.get("name") and (s["name"].lower() in names or s.get("number") in numbers)]


def _family(game, family):
    """A family's Layers for a `with` block, or None in it when the folder has no file of the family."""
    try:
        return game.layers(family)
    except FileNotFoundError:
        # A folder without the family offers nothing from it; never an error.
        return contextlib.nullcontext(None)


def offered(game):
    """The songs the game offers (_offered), read from the song list's and the script families as the client reads
    them: the card's count. None when there is no song list; FileNotFoundError without the song list's family, a
    pak.PakError or ValueError when the song list is damaged."""
    with game.layers("DiscInfo") as info, _family(game, SCRIPT) as script:
        return _offered(info, script)


def _work_out(game):
    """{"songs": how many songs the game offers, "without": [internal names of those with no chart], "first": [the
    first songs the game shows that have none]} from the game's files, or None when the charts' family, or a file of
    the script family, cannot be read (nothing is said then)."""
    with game.layers("DiscInfo") as info, _family(game, SCRIPT) as script:
        if script is not None and script.damaged:
            # A damaged script file may hold newer disc sets or crew missions, naming songs whose charts would not be
            # looked for: nothing is said, as for a damaged file of the charts. (One of another build is left out, as
            # the DJ cards leave it.)
            return None
        offered_rows = _offered(info, script)
        if offered_rows is None:
            return None
        # Only what a player can be shown: a row no mode's table names never is, charts or not.
        songs = [s["name"] for s in offered_rows]
        first = _first_songs(info)
    try:
        with game.layers(g.CHARTS) as charts:
            # A file of the family this reader cannot open (another build's: every file of a whole game folder opens)
            # may hold the charts it would call missing: then nothing is said, as for a damaged one.
            if charts.damaged or charts.unread or not charts.opened:
                return None
            have = set()
            for name in charts.names():
                m = CHART.match(name)
                if m:
                    have.add(m.group(1).lower())
    except (FileNotFoundError, pak.PakError):
        return None
    without = [name for name in songs if name.lower() not in have]
    return {"songs": len(songs), "without": without,
            "first": [name for name in first if name.lower() not in have]}


# One working out at a time: the card's look and the ready check may ask at once, and the second then finds the
# first one's answer kept instead of reading the charts' files a second time.
_one_at_a_time = threading.Lock()


def check(game, keep=None):
    """What check says for a game folder (_work_out's answer, or None), kept in the JSON file `keep` (openDMT3's,
    several game folders by their path) and worked out again only when the families' sizes or times changed."""
    with _one_at_a_time:
        return _check(game, keep)


def _check(game, keep):
    stamps = _stamps(game)
    key = os.path.normcase(os.path.abspath(game.root))
    kept = {}
    if keep:
        try:
            with open(keep, encoding="utf-8") as f:
                kept = json.load(f)
            if not isinstance(kept, dict):
                kept = {}
        except (OSError, ValueError):
            kept = {}
        entry = kept.get(key)
        # Kept from the same files, and worked out the way this openDMT3 does it: an older answer (every row counted, or
        # none told while a file of the charts could not be opened) is worked out again.
        if isinstance(entry, dict) and entry.get("from") == stamps and entry.get("version") == VERSION:
            return entry.get("answer")
    answer = _work_out(game)
    if keep:
        kept[key] = {"from": stamps, "version": VERSION, "answer": answer}
        folder = os.path.dirname(keep)
        try:
            os.makedirs(folder, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=folder, prefix=".opendmt3-")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(kept, f)
            os.replace(tmp, keep)
        except OSError:
            # Not kept: worked out again next time, nothing worse.
            pass
    return answer
