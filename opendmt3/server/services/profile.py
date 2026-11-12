"""A player's records as the site's DJ page, its API (GET /api/v1/djs/{player}) and the launcher's Records page show
them: counts, best scores, recent plays and activity, with song titles and chart levels from the song list.

One function for all three, so the launcher on this PC (reading its own database) and a server's site agree.
"""

import time

from opendmt3.server import db
from opendmt3.server import messages
from opendmt3.server.services import activity as act
from opendmt3.server.services import cards, catalog, records

RECENT = 10


def mode_name(mode):
    return messages.MODE_NAMES.get(mode, "MODE %d" % mode)


def play(songs, row):
    """One play (a row of records.recent) as the pages show it."""
    return {"title": catalog.title(songs, row["song"]), "song": row["song"], "pattern": row["pattern"],
            "score": row["score"], "mode": row["mode"], "mode_name": mode_name(row["mode"]), "dj": row["dj_name"],
            "player": row["account_id"], "level": catalog.level(songs, row["song"], row["mode"], row["pattern"]),
            "at": row["played_at"]}


def weeks(counts, now=None):
    """The weekly counts with each week's first and last day (the last week ends today)."""
    today = act._day_start(now if now is not None else time.time())
    out = []
    for i, n in enumerate(counts):
        end = today - (len(counts) - 1 - i) * act.WEEK
        out.append({"from": end - 6 * act.DAY, "to": end, "plays": n})
    return out


def card(connection, data_dir, row):
    """An account's DJ card (cards.view) on an open connection, for the API's answers about the signed-in player."""
    return cards.view(row, cards.load(data_dir), catalog.load(data_dir), records.Records(connection).cleared(row["id"]))


def dj_cards(connection, data_dir, rows, cleared=None):
    """The DJ cards of many accounts at once ({account id: card}), for the list of players: one query over the plays
    for all of them (or `cleared`, what Records.cleared_by_account gave, kept by the caller), and the tables and the
    song list read once."""
    tables, songs = cards.load(data_dir), catalog.load(data_dir)
    if cleared is None:
        cleared = records.Records(connection).cleared_by_account()
    return {row["id"]: cards.view(row, tables, songs, cleared.get(row["id"], [])) for row in rows}


def dj(db_path, data_dir, player):
    """A player's records by account number, or None for nobody (or a disabled account)."""
    connection = db.connect(db_path)
    try:
        row = connection.execute("SELECT * FROM accounts WHERE id = ?", (player,)).fetchone()
        if row is None or row["disabled"]:
            return None
        made = dj_plays(connection, data_dir, row)
        sessions = act.Activity(connection).sessions(row["id"])
    finally:
        connection.close()
    return dj_page(made, sessions)


def dj_plays(connection, data_dir, row, now=None):
    """What dj() makes of an account's plays (`row`, its account), on an open connection: everything but its sessions
    and play time, so the same until a play is kept, the day ends, or the song list or the card tables change (the
    site keeps it that long: web/common.py)."""
    store = records.Records(connection)
    summary, bests = store.summary(row["id"]), store.bests(row["id"])
    recent = store.recent(row["id"], RECENT)
    done = act.Activity(connection).dj_plays(row["id"], now)
    cleared = store.cleared(row["id"])
    songs = catalog.load(data_dir)
    return {"player": row["id"], "dj_name": row["dj_name"], "summary": summary,
            "dj_card": cards.view(row, cards.load(data_dir), songs, cleared),
            "bests": [{"song": b["song"], "title": catalog.title(songs, b["song"]), "mode": b["mode"],
                       "mode_name": mode_name(b["mode"]), "pattern": b["pattern"], "score": b["score"],
                       "level": catalog.level(songs, b["song"], b["mode"], b["pattern"]), "at": b["at"]}
                      for b in bests],
            "recent": [play(songs, r) for r in recent],
            "activity": {"weeks": weeks(done["weeks"], now),
                         "modes": [{"mode": m, "mode_name": mode_name(m), "plays": n} for m, n in done["modes"].items()],
                         "songs": [dict(s, title=catalog.title(songs, s["song"])) for s in done["songs"]]}}


def dj_page(plays, sessions):
    """A player's records as dj() gives them, from dj_plays() and their (sessions, play time in seconds)
    (activity.Activity.sessions). `plays` is left as it is (a kept copy may be shared)."""
    activity = dict(plays["activity"], sessions=sessions[0], seconds=sessions[1])
    return dict(plays, activity=activity)
