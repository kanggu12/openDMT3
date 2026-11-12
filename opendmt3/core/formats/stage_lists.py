"""The STAR and POP song lists of each stage (DiscInfo\\star_stage_N.csv, pop_stage_N.csv).

Each row is: song number, song id, then up to four groups of (speed, pattern number, hidden). A pattern
whose hidden flag is 1 is not offered to a player without a card that unlocked it.
"""

import re

# star_stage_1.csv .. pop_stage_3.csv; the bonus stage lists are left as the game has them.
LIST_NAME = re.compile(r"(?i)^(star|pop)_stage_[123]\.csv$")


def is_stage_list(path):
    """True for a STAR or POP list of stage 1 to 3, by the file name at the end of an archive path."""
    return bool(LIST_NAME.match(path.replace("/", "\\").rsplit("\\", 1)[-1]))


def _fields(line):
    return line.split(",")


def count_hidden(raw):
    """How many patterns the list hides."""
    hidden = 0
    for line in raw.decode("ascii").splitlines()[1:]:
        f = _fields(line)
        for i in range(4, len(f), 3):          # the third field of each (speed, pattern, hidden) group
            if f[i].strip() not in ("", "0"):
                hidden += 1
    return hidden


def show_all(raw):
    """The list with every hidden flag set to 0, edited field by field so nothing else changes."""
    out = []
    # Each line keeps its own ending (the game's lists use CRLF; nothing here depends on it).
    for n, line in enumerate(raw.decode("ascii").splitlines(keepends=True)):
        body = line.rstrip("\r\n")
        end = line[len(body):]
        if n == 0:
            out.append(line)                   # the header row
            continue
        f = _fields(body)
        for i in range(4, len(f), 3):
            if f[i].strip() not in ("", "0"):
                f[i] = "0"
        out.append(",".join(f) + end)
    return "".join(out).encode("ascii")
