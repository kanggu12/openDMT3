"""The game's song list, Resource\\DiscInfo\\discstock.csv in DiscInfo.pak.

UTF-16 text, one song per line, fields separated by tabs (a title with commas is in quotes): number, internal
name, title, genre, composer, video folder, series, licence, original video, loop, then the levels of the four
STAR and four POP patterns (0: no such pattern).
"""

import csv
import io

PATH = "Resource\\DiscInfo\\discstock.csv"


def parse(raw):
    """[{number, name, title, genre, composer, star: [4 levels], pop: [4 levels]}, ...] from the file's bytes."""
    text = raw.decode("utf-16")
    rows = list(csv.reader(io.StringIO(text), delimiter="\t"))
    header = [h.strip().lower() for h in rows[0]] if rows else []
    if header[:2] != ["no", "name"]:
        # The game's table starts with the number and the internal name: anything else is a damaged file, never a
        # list of no songs.
        raise ValueError("not the game's song list (its columns start %r)" % header[:2])
    songs = []
    for row in rows[1:]:
        if not row or not row[0].strip().isdigit():
            continue
        cell = dict(zip(header, row))
        level = lambda key: int(cell.get(key, "0") or 0) if (cell.get(key, "0") or "0").strip().isdigit() else 0
        songs.append({
            "number": int(row[0]),
            "name": cell.get("name", ""),
            "title": cell.get("fullname", ""),
            "genre": cell.get("genre", ""),
            "composer": cell.get("composer", ""),
            "star": [level("star_%d" % i) for i in range(1, 5)],
            "pop": [level("pop_%d" % i) for i in range(1, 5)],
        })
    return songs
