"""What the site's areas (pages.py, admin.py, api.py) share: the cookies' names, where a request comes from, a
redirect, the error page, the password check every sign-in goes through (its limits are Site's, in app.py), and
what a page and its API twin both show and do (one reader or change for both, so the twins never differ).

These were closures in create_app (app.py) before the site was split by area. They keep their names, leading
underscore and all, as the web package's own. Each that needs the Site takes it as its first argument, since it is
no longer a closure over it.
"""

import contextlib
import csv
import datetime
import io
import logging
import os
import secrets
import sqlite3
import tempfile
import time
import urllib.parse

from starlette.responses import RedirectResponse, StreamingResponse

from opendmt3 import __version__
from opendmt3.server import db
from opendmt3.core import errors, preset
from opendmt3.core.errors import Worded
from opendmt3.server.services import activity as act
from opendmt3.server.services import backups as bak
from opendmt3.server.services import catalog as cat
from opendmt3.server.services import cards, downloads, files, maintenance, notice, profile, songlist, sources
from opendmt3.server.services import records as rec
# The upload's own reading of a request's body, into a file in backups/ (the Backups tab and its API twin).
# The worker threads a handler hands its work to, its processor time counted (work.py).
from opendmt3.server.web.work import charged, long, threaded
from opendmt3.server.web import upload

# The site's cookies and how long a sign-in lasts, all here: the names share one name space in the browser, so a
# new one is checked against the others in one place.
COOKIE = "opendmt3"
LANG_COOKIE = "opendmt3_lang"
OWNER_COOKIE = "opendmt3_owner"
# The ID of the owner's account the first-run page just made, for the sign-in page that opens after it to say so once.
MADE_COOKIE = "opendmt3_made"
SIGNIN_COOKIE = "opendmt3_signin"
SIGN_IN_DAYS = 30
# The installer's name in the downloads folder (Site.downloads): the Download page offers it, /download/windows hands
# it out, and the admin's Status page says when it is missing.
INSTALLER = "openDMT3-win-Setup.exe"
# The command that imports the song list on the server PC, as the Status page's Song list card shows it.
CATALOG_COMMAND = "./dmt3 catalog"
# The Status page's list of what to look at: a backup older than this is worth a line.
BACKUP_DAYS = 7
# What opening or using the database can raise when the file is missing, broken, from a newer openDMT3 or not
# writable: the pages then say the site is not available right now.
DB_ERRORS = (sqlite3.Error, db.DatabaseError, OSError)

log = logging.getLogger("opendmt3.web")
# Quiet until the program says where its log goes (the server's logging.basicConfig): a library's own manners, and no
# stray lines in the tests' output.
log.addHandler(logging.NullHandler())

# Headers a reverse proxy adds to what it passes on. A browser on this PC sends none of them; a request with one
# came through a proxy, which passes on visitors from anywhere.
FORWARDED = ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip")
# The licences of the fonts the site serves, from the folders the fonts are in: the wide face (made from Saira, the
# launcher's file) and the text faces (made from Pretendard, and Pretendard itself).
HERE = os.path.dirname(os.path.abspath(__file__))
# (The wide face's licence is beside it in the client's assets, opendmt3/client/assets/fonts.)
LICENCES = {"saira": os.path.join(os.path.dirname(os.path.dirname(HERE)), "client", "assets", "fonts", "Saira-OFL.txt"),
            "pretendard": os.path.join(HERE, "static", "fonts", "OFL-Pretendard.txt")}
# Each licence with the site's words for the faces it covers, in the order the Licenses page and its API twin give them.
LICENCE_FACES = (("saira", ("licenses.wide",)), ("pretendard", ("licenses.text", "licenses.pretendard")))
# openDMT3's own licence, beside the package: the repository's LICENSE in a copy of it, /app/LICENSE in the server's
# image (packaging/docker/Dockerfile) and the launcher's copy beside its package (packaging/windows/openDMT3.spec).
OWN_LICENCE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "LICENSE")
# The parts the server and what it hands out (the launcher's installer on the Download page) are made with, as
# OpenDMTQ's Licenses page lists its own: (the parts' names, what they are used for, their licences), the last two the
# site's words. The page and its API twin give them in this order; tests/server/test_licences.py keeps the list to the
# packages the server's image and the launcher's build install, and to what their metadata says of their licences.
LICENCE_PARTS = (
    ("Starlette, Uvicorn, Jinja2, python-multipart", "licenses.use.site", "licenses.lic.site"),
    ("AnyIO, idna, typing_extensions, MarkupSafe, Click, h11, packaging", "licenses.use.libs", "licenses.lic.libs"),
    ("Pillow", "licenses.use.pictures", "licenses.lic.pictures"),
    ("Python 3.12", "licenses.use.python", "licenses.lic.python"),
    ("7-Zip 25.01", "licenses.use.7zip", "licenses.lic.7zip"),
    ("Tcl/Tk, Velopack, PyInstaller", "licenses.use.launcher", "licenses.lic.launcher"),
    ("AMD FidelityFX Super Resolution 1, NVIDIA Image Scaling, SMAA, FXAA 3.11", "licenses.use.passes",
     "licenses.lic.passes"),
    ("mingw-w64, GCC", "licenses.use.runtime", "licenses.lic.runtime"),
    ("Debian 12", "licenses.use.system", "licenses.lic.system"),
    ("DMT3 Wide, DMT3 Text, Pretendard", "licenses.use.fonts", "licenses.lic.fonts"),
)


def _address(request):
    """The address a request came from (the visitor's, behind a proxy given with --proxy)."""
    return request.client.host if request.client else "?"


def _local(request):
    """True for a visit from this PC itself, to this PC's own name (the owner's first-run page is for nobody else).

    The address the page was asked for counts too: a page of another site whose name was pointed at 127.0.0.1
    afterwards comes from this PC, but asks for its own name. A request that came through a proxy (any forwarded
    header) is never from this PC, whatever address the proxy names: a proxy here passes on visitors from anywhere,
    and with --proxy a forwarded header can name 127.0.0.1.
    """
    if any(name in request.headers for name in FORWARDED):
        return False
    if request.client is None or request.client.host not in ("127.0.0.1", "::1"):
        return False
    return (request.url.hostname or "").lower() in ("127.0.0.1", "localhost", "::1")


def _local_path(target, default="/"):
    """`target` when it is a path of this site, else `default`: never another address someone put in a link (two
    slashes, or a slash and a backslash, start one), and never a control character."""
    if not target or not target.startswith("/") or target[1:2] in ("/", "\\"):
        return default
    if any(ord(c) < 32 or ord(c) == 127 for c in target):
        return default
    return target


def _redirect(url):
    # 303: the browser follows a form's POST with a GET.
    return RedirectResponse(url, status_code=303)


def _not_found(site, request):
    """The page that is not there (404), made where it is asked for: a handler's worker thread."""
    return site.render(request, "error.html", status=404)


async def not_found(site, request, exc=None):
    """_not_found from the loop (the 404 handler, an async handler): made on a worker thread, as every page is."""
    return await threaded(_not_found, site, request)


def _allowed(exc):
    """The headers of a 405 answer: Allow, naming the methods the path takes (Starlette puts them on its exception), in
    a steady order. None when the exception names none."""
    allow = (getattr(exc, "headers", None) or {}).get("Allow")
    if not allow:
        return None
    return {"Allow": ", ".join(sorted(m.strip() for m in allow.split(",")))}


def _health(site):
    """(status, answer) for GET /health, which Docker's HEALTHCHECK asks: 200 {"ok": true, "version"} while the
    database opens and takes a write (an empty one, rolled back), else 503 with a short reason (the details go to
    the log, not to whoever asks)."""
    try:
        connection = db.connect(site.db_path)
    except DB_ERRORS:
        log.exception("the health check could not open the database")
        return 503, {"ok": False, "version": __version__, "reason": "the database cannot be opened"}
    try:
        # A write lock taken and given back: the file, its folder and the write-ahead log all take writes.
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("ROLLBACK")
    except sqlite3.Error:
        log.exception("the health check could not write to the database")
        return 503, {"ok": False, "version": __version__, "reason": "the database cannot be written"}
    finally:
        connection.close()
    return 200, {"ok": True, "version": __version__}


async def _check_password(site, request, login_id, password):
    """(the account, None) for a right ID and password, (None, None) for a wrong one, or (None, why) when the try
    must wait: why is (the page's words, the API's message, the seconds to wait: a 429's Retry-After). The check
    runs on a worker thread (Site.gate).

    Every try counts against the address's sign-ins a minute. Right before the check, with nothing awaited between,
    the limits on wrong passwords are read and the try is counted as wrong, then taken back if it was right: tries
    sent at once see each other, so none slips past the limit while others are being checked, and right ones in a
    burst never hold each other back (only HASHING_AT_ONCE are being checked at any moment)."""
    address, local = _address(request), _local(request)
    if not site.sign_in_allowed(address):
        return None, ("signin.wait", "too many sign-ins from this address; wait a minute", site.sign_in_wait(address))
    async with site.gate():
        if site.too_many(address):
            return None, ("signin.wait", "too many failed sign-ins from this address; wait a few minutes",
                          site.wrong_wait(address))
        if not local and site.id_held(login_id):
            # Never for a visit from this PC: the owner can always sign in at the server itself.
            return None, ("signin.wait.id", "too many wrong passwords for this ID; wait a few minutes",
                          site.id_wait(login_id))
        marks = site.failed(address, None if local else login_id)
        # The check and its look into the database on a thread of the long work's own (the request's connection opened
        # there too): the site's own threads go on meanwhile.
        row = await long(_password_matches, site, login_id, password)
    if row is not None:
        site.forgive(marks)
    else:
        # Who tried which ID from where (never the password); %r keeps a typed line break on one log line.
        log.warning("a wrong password for the ID %r from %s (%s)", str(login_id)[:32], address, request.url.path)
    return row, None


def _password_matches(site, login_id, password):
    """The account whose ID and password these are, or None (accounts.check_web), on the request's connection."""
    store = site.accounts()
    try:
        return store.check_web(login_id, password)
    finally:
        store.db.close()


def _accounts_call(site, method, *args, **kwargs):
    """Accounts.<method>(*args, **kwargs) on the request's connection, for a worker thread (Site.hashed runs the ones
    that make a password this way)."""
    store = site.accounts()
    try:
        return getattr(store, method)(*args, **kwargs)
    finally:
        store.db.close()


# ------------------------------------------------------------------ what a page and its API twin both show

def _marked(songs, row):
    """A play as the pages show it (profile.play), with the best it was weighed against: `before` (None before the
    player's first play of the chart), `new` (it beat that best: a page's NEW) and `gain` (by how much)."""
    beat = row["before"] is not None and row["score"] > row["before"]
    return dict(profile.play(songs, row), before=row["before"], new=beat,
                gain=row["score"] - row["before"] if beat else None)


def _recent(site, account_id=None, limit=15):
    """Home's recent plays: the newest `limit` of one player's or everyone's, each marked when it beat the player's
    best on the chart before it, and how many there are in all (the list says when it is cut). Everyone's are kept
    until the plays change (cache.py); one player's are a look into their own index (well under a millisecond)."""
    store = _records(site)
    try:
        if account_id is None:
            # Everyone's newest and their count (a read of every enabled player's plays: 31 ms on 1,000,000), kept.
            rows = _kept(site, store, ("recent", limit), lambda: store.recent(None, limit, before=True))
            total = site.lists.get(store.db, ("count",), lambda: store.count(None))
        else:
            rows, total = store.recent(account_id, limit, before=True), store.count(account_id)
    finally:
        store.db.close()
    songs = cat.load(site.data_dir)
    return [_marked(songs, r) for r in rows], total


def _new_records(site, limit=10):
    """The newest plays that beat the player's previous best on the same chart (records.new_records), with the
    gain over that best, enabled players only; kept until the plays change."""
    store = _records(site)
    try:
        rows = _kept(site, store, ("new_records", limit), lambda: store.new_records(limit))
    finally:
        store.db.close()
    songs = cat.load(site.data_dir)
    return [_marked(songs, r) for r in rows]


def _records(site):
    """The records service on the request's connection (Site.connect; its close() leaves it to the request)."""
    return rec.Records(site.connect())


def _kept(site, store, key, make):
    """make()'s list (rows of the database, as dicts) kept by the site until the plays change (cache.py): the same
    list for every request until a play is kept or a player changes."""
    return site.lists.get(store.db, key, lambda: [dict(row) for row in make()])


_mode_name = profile.mode_name


def _placed(rows):
    """A ranking's rows (records.rankings and its kin, best first) with places: equal totals share a place."""
    out, place, last = [], 0, None
    for i, r in enumerate(rows):
        if r["total"] != last:
            place, last = i + 1, r["total"]
        out.append({"place": place, "player": r["player"], "dj_name": r["dj_name"], "total": r["total"],
                    "charts": r["charts"]})
    return out


def _rankings(site, mode, by="total"):
    """A mode's ranking with places (equal totals share a place); by "total" or "best30" (records.rankings), kept
    until the plays change."""
    store = _records(site)
    try:
        rows = _kept(site, store, ("rankings", mode, by), lambda: store.rankings(mode, by))
    finally:
        store.db.close()
    return _placed(rows)


# The Rankings page's past months: this many before the one running.
MONTHS_BACK = 12


def _month_start(now, back=0):
    """The first moment of the month `back` months before the one `now` is in, on the server's clock (-1: the next
    month's)."""
    t = time.localtime(now)
    year, month = t.tm_year, t.tm_mon - back
    # Months counted past the year's ends move the year.
    while month < 1:
        month, year = month + 12, year - 1
    while month > 12:
        month, year = month - 12, year + 1
    return int(time.mktime((year, month, 1, 0, 0, 0, 0, 0, -1)))


def _month_rankings(site, mode, now=None):
    """A mode's ranking of this calendar month (records.rankings_between, the server's clock) with places, and the
    first three of each of the MONTHS_BACK months before it that anybody played in: {"start", "rows", "past":
    [{"start", "rows"}]}, newest month first."""
    now = now if now is not None else time.time()
    # The month's bounds, and each past month's (start, end), newest first.
    starts = [_month_start(now, back) for back in range(-1, MONTHS_BACK + 1)]
    months = tuple((starts[i + 1], starts[i]) for i in range(1, MONTHS_BACK + 1))
    store = _records(site)
    try:
        # Kept until the plays change, for this month's bounds (the next month asks for other ones).
        rows = _kept(site, store, ("month", mode, starts[1], starts[0]),
                     lambda: store.rankings_between(mode, starts[1], starts[0]))
        past = site.lists.get(store.db, ("past", mode, months),
                              lambda: [[n, [dict(r) for r in top]] for n, top in store.past_months(mode, list(months))])
    finally:
        store.db.close()
    return {"start": starts[1], "rows": _placed(rows),
            "past": [{"start": starts[n + 2], "rows": _placed_rows(top)} for n, top in past]}


def _placed_rows(rows):
    """Rows that come with their places (records.past_months) as the pages show a ranking's rows."""
    return [{"place": r["place"], "player": r["player"], "dj_name": r["dj_name"], "total": r["total"],
             "charts": r["charts"]} for r in rows]


def _month_name(w, start):
    """A month by its first moment, in the page's words: "November 2026", "2026년 11월"."""
    t = time.localtime(start)
    return w("month.name", month=w("month.%d" % t.tm_mon), year=t.tm_year)


def _modes(site):
    """The modes an enabled player has cleared a stage in (records.modes), kept until the plays change."""
    store = _records(site)
    try:
        return site.lists.get(store.db, ("modes",), store.modes)
    finally:
        store.db.close()


def _songs(site):
    """Every song in the server's list, and any song cleared that is not in it, with what was played."""
    store = _records(site)
    try:
        # What was played of each song (a read of every play: 0.4 s on 1,000,000), kept until the plays change.
        played = {r["song"]: r for r in _kept(site, store, ("songs",), store.songs)}
    finally:
        store.db.close()
    songs = cat.load(site.data_dir)
    out = []
    for number in set(songs) | set(played):
        song, stats = songs.get(number, {}), played.get(number)
        out.append({"number": number, "title": cat.title(songs, number), "genre": song.get("genre", ""),
                    "composer": song.get("composer", ""), "plays": stats["plays"] if stats else 0,
                    "players": stats["players"] if stats else 0, "best": stats["best"] if stats else None,
                    "jacket": cat.jacket_path(site.data_dir, number) is not None})
    # Played songs first, the most played on top; the rest by title.
    out.sort(key=lambda s: (-s["plays"], s["title"].lower(), s["number"]))
    return out


def _songs_found(rows, query):
    """What the Songs page's Find leaves of the songs (_songs): those whose title or composer has `query` in any case,
    or whose number it is. Nothing to find leaves every song."""
    if not query:
        return rows
    q = query.lower()
    return [s for s in rows if q in s["title"].lower() or q in s["composer"].lower() or q == str(s["number"])]


def _song(site, number):
    """One song's charts: per mode and pattern, each player's best with places. None for an unknown song.

    The boards (each player's best on each chart, read from every play, made into boards with places: 16 ms for the
    most played song's 8,000 rows on 300,000 plays) are kept until the plays change, for the song list they were made
    with (its levels)."""
    store = _records(site)
    try:
        # The song list's stamp first, then what is made of it inside: a song list put in place between the two never
        # goes in under the newer stamp.
        stamp = files.stamp(os.path.join(site.data_dir, cat.FILE))
        charts = site.lists.get(store.db, ("song boards", number, stamp),
                                lambda: _boards(cat.load(site.data_dir), number, store.boards(number)))
    finally:
        store.db.close()
    songs = cat.load(site.data_dir)
    if number not in songs and not charts:
        return None
    song = songs.get(number, {})
    return {"number": number, "title": cat.title(songs, number), "genre": song.get("genre", ""),
            "composer": song.get("composer", ""), "charts": charts,
            "jacket": cat.jacket_path(site.data_dir, number) is not None}


def _boards(songs, number, rows):
    """The song's boards from each player's best on each of its charts (records.boards, best first per chart): per mode
    and pattern, with its level and each row's place (equal scores share one)."""
    charts = {}
    for r in rows:
        chart = charts.setdefault((r["mode"], r["pattern"]), {"mode": r["mode"], "mode_name": _mode_name(r["mode"]),
                                                               "pattern": r["pattern"], "rows": [],
                                                               "level": cat.level(songs, number, r["mode"],
                                                                                  r["pattern"])})
        board = chart["rows"]
        place = board[-1]["place"] if board and board[-1]["score"] == r["score"] else len(board) + 1
        board.append({"place": place, "player": r["player"], "dj_name": r["dj_name"], "score": r["score"],
                      "at": r["at"]})
    return list(charts.values())


def _dj(site, player):
    """A player's page by their account number (services/profile.py, shared with the launcher). None for nobody
    (or a disabled account).

    What it makes of the player's plays (their numbers, best scores, newest plays, plays by week, mode and song: 0.7 s
    for the busiest player of 1,000,000 plays) is kept until the plays change, for the day it was made (the weeks end
    today); their sessions and play time are read each time (an open session's time grows by itself)."""
    connection = site.connect()
    try:
        row = connection.execute("SELECT * FROM accounts WHERE id = ?", (player,)).fetchone()
        if row is None or row["disabled"]:
            return None
        # The day (its weeks end today) and the song list's and the card tables' files (its titles, levels and card
        # come from them) are part of what it is made of.
        day = act._day_start(time.time())
        tables = (files.stamp(os.path.join(site.data_dir, cat.FILE)),
                  files.stamp(os.path.join(site.data_dir, cards.FILE)))
        # Made of the player's own plays alone: kept while others play, made again once they play (their newest
        # play: the last entry of their part of the index on (account, time)).
        def made_now():
            # The account read again after the state the list is kept under (Lists.get reads that first): a rename or
            # a new card committed between the two never goes in under the newer state.
            again = connection.execute("SELECT * FROM accounts WHERE id = ?", (player,)).fetchone()
            return profile.dj_plays(connection, site.data_dir, again if again is not None else row)
        made = site.lists.get(connection, ("dj", player, day, tables), made_now,
                              newest=("SELECT id FROM plays WHERE account_id = ? ORDER BY played_at DESC, id DESC"
                                      " LIMIT 1", (player,)))
        sessions = act.Activity(connection).sessions(player)
    finally:
        connection.close()
    return profile.dj_page(made, sessions)


def _dj_places(site, player):
    """A player's place in each mode's ranking by total, as the Rankings page counts places (equal totals share
    one), and how many are ranked: [{"mode", "mode_name", "place", "of"}], the game's order. From every enabled
    player's totals (records.totals: 0.3 s on 1,000,000 plays), kept until the plays change."""
    store = _records(site)
    try:
        totals = site.lists.get(store.db, ("totals",),
                                lambda: {mode: dict(players) for mode, players in store.totals().items()})
    finally:
        store.db.close()
    places = rec.places_in(totals, player)
    return [{"mode": mode, "mode_name": _mode_name(mode), "place": place, "of": of}
            for mode, (place, of) in sorted(places.items())]


def _mode_asked(text, modes):
    """The mode a request asks for: a number from 0 to 255, else None. Without one, the first mode played."""
    if text is None or text == "":
        return modes[0] if modes else 0
    try:
        mode = int(text)
    except ValueError:
        return None
    return mode if 0 <= mode <= 255 else None


def _song_number(request):
    """A song number from the path, or None when it cannot be one (the game's numbers are 32-bit)."""
    number = request.path_params["number"]
    return number if 0 <= number < 2 ** 32 else None


def _cabinets(site):
    """The cabinets connected now, with who is logged in on each."""
    if site.game_server is None:
        return []
    out = []
    store = site.accounts()
    try:
        # A copy of the links (GameServer.live): the loop goes on opening and closing them meanwhile.
        for conn in site.game_server.live():
            if not conn["online"]:
                continue
            row = store.by_login(conn["player"]) if conn["player"] else None
            out.append({"address": conn["address"], "version": conn["version"],
                        "player": row["dj_name"] if row else None, "login_id": conn["player"]})
    finally:
        store.db.close()
    return out


def _cabinets_for(site, row):
    """The cabinets connected now, as the account `row` may see them: an admin all of it, a player only who
    plays on each (the DJ name). A cabinet's address and a player's login ID (half of what signs them in) are
    for the admins."""
    cabinets = _cabinets(site)
    if row["is_admin"]:
        return cabinets
    return [{"player": c["player"]} for c in cabinets]


def _known_cabinets(site):
    """Every cabinet seen, with whether it is connected now and who plays on it."""
    live = {}
    for c in _cabinets(site):
        live[c["address"].rsplit(":", 1)[0]] = c
    activity = site.activity()
    try:
        rows = activity.cabinets()
    finally:
        activity.db.close()
    for r in rows:
        now = live.get(r["host"])
        r["connected"] = now is not None
        r["player"] = now["player"] if now else None
    return rows


def _status(site):
    """The server's state and numbers for the admin's Status tab and GET /api/v1/server."""
    activity = site.activity()
    try:
        numbers = activity.status()
    finally:
        activity.db.close()
    made = bak.all_backups(site.data_dir)
    size = sum(os.path.getsize(p) for p in (site.db_path, site.db_path + "-wal") if os.path.isfile(p))
    return dict(numbers, version=__version__, game_port=site.game_port, connected=len(_cabinets(site)),
                started=int(site.game_server.started) if site.game_server else None,
                database_bytes=size, last_backup=made[0]["at"] if made else None,
                maintenance=maintenance.read(site.data_dir) is not None)


def _to_look_at(site, user, now=None):
    """What the admin may want to look at, each only when it is so, as (key, values, page to fix it on or None) for
    the Status page's words: no backup in the last BACKUP_DAYS days, no song list, no installer to hand out, and
    every account but the admin's own disabled (theirs cannot be: they are signed in with it)."""
    now = now if now is not None else time.time()
    out = []
    made = bak.all_backups(site.data_dir)
    if not made or now - made[0]["at"] > BACKUP_DAYS * 86400:
        # The newest backup is the first; none at all counts the same.
        out.append({"key": "backup", "values": {"days": BACKUP_DAYS}, "href": "/admin/backups"})
    if not cat.load(site.data_dir):
        # Without it songs show by number and the DJ cards have nothing to choose from; the Song list tab imports it.
        out.append({"key": "songs", "values": {}, "href": "/admin/song_list"})
    if not os.path.isfile(os.path.join(site.downloads, INSTALLER)):
        # The folder named, so the admin knows where the file goes; in Docker that folder is inside the server's
        # volume, out of the admin's reach, so the command that puts the file there is named instead (_look_text).
        out.append({"key": "installer", "values": {"file": INSTALLER, "folder": site.downloads}, "href": None})
    store = site.accounts()
    try:
        others, enabled = store.db.execute("SELECT COUNT(*), COALESCE(SUM(disabled = 0), 0) FROM accounts"
                                           " WHERE id != ?", (user["id"],)).fetchone()
    finally:
        store.db.close()
    if others and not enabled:
        # Other accounts there are, and none of them can sign in or play.
        out.append({"key": "accounts", "values": {}, "href": "/admin/players"})
    return out


def _look_text(w, item):
    """A line of _to_look_at in the page's words (the Status page and its API twin say the same): its key's words
    with its values, the installer's in Docker with the command to run on the server PC instead of a folder."""
    if item["key"] == "installer" and sources.in_container():
        return w("status.look.installer.command")
    return w("status.look." + item["key"], **item["values"])


def _log(site, limit=100):
    """What the admins changed, and the messages the game server received, newest first."""
    connection = site.connect()
    try:
        changes = [dict(r) for r in connection.execute(
            "SELECT at, who, what FROM changes ORDER BY id DESC LIMIT ?", (limit,))]
    finally:
        connection.close()
    # A copy of what the game server kept (GameServer.received), newest first.
    received = site.game_server.received()[::-1][:limit * 2] if site.game_server else []
    return {"changes": changes, "messages": [dict(m, at=int(m["at"])) for m in received]}


# The plays log: the days a filter can go back (otherwise every play), and plays a page.
LOG_DAYS = (1, 7, 30)
LOG_PAGE = 50
# The CSV's columns, the file's first line.
LOG_COLUMNS = ("when", "dj", "mode", "song", "title", "pattern", "score")


def _plays_wanted(params):
    """The plays log's filter from a request's query: player (an account number), days (one of LOG_DAYS; otherwise
    every play), q (a word in the song title) and page (1 and up). What cannot be read is no filter (page 1); `unread`
    names those values, which the page goes on without and the API refuses."""
    player = params.get("player", "")
    days = params.get("days", "")
    page = params.get("page", "")
    # A page number of a sane length, 1 or more.
    page_read = page.isdigit() and len(page) < 7 and int(page) > 0
    wanted = {"player": int(player) if player.isdigit() and len(player) < 19 else None,
              "days": int(days) if days in [str(d) for d in LOG_DAYS] else None,
              # A word of a sane length: a title is a few dozen characters.
              "q": params.get("q", "").strip()[:64],
              "page": int(page) if page_read else 1}
    # Each value given that could not be read: its filter is left out.
    wanted["unread"] = [name for name, given, read in (("player", player, wanted["player"] is not None),
                                                       ("days", days, wanted["days"] is not None),
                                                       ("page", page, page_read)) if given and not read]
    return wanted


def _songs_with(songs, word):
    """The numbers of the songs whose title has the word (in any case), and the song of that number when the word is
    one ("77" or "#77", as a song missing from the list is shown)."""
    word = word.casefold()
    found = [number for number, song in songs.items() if word in (song.get("title") or "").casefold()]
    digits = word[1:] if word.startswith("#") else word
    if digits.isdigit() and len(digits) < 11 and int(digits) not in found:
        found.append(int(digits))
    return found


def _log_filter(site, wanted, now=None):
    """The records' filter for a plays log request: (account, since, songs)."""
    now = now if now is not None else time.time()
    since = now - wanted["days"] * 86400 if wanted["days"] else None
    songs = _songs_with(cat.load(site.data_dir), wanted["q"]) if wanted["q"] else None
    return wanted["player"], since, songs


def _log_play(songs, row):
    """A row of the plays log as the page and the file show it."""
    return {"id": row["id"], "at": row["played_at"], "player": row["account_id"], "dj": row["dj_name"],
            "login_id": row["login_id"], "mode": row["mode"], "mode_name": _mode_name(row["mode"]),
            "song": row["song"], "title": cat.title(songs, row["song"]), "pattern": row["pattern"],
            "level": cat.level(songs, row["song"], row["mode"], row["pattern"]), "score": row["score"]}


def _plays_log(site, wanted, now=None):
    """One page of the admin's plays log for a filter (_plays_wanted): the plays, what the filter leaves counted
    (plays, players, charts), whether there are older and newer pages, and the accounts to filter by."""
    account, since, songs = _log_filter(site, wanted, now)
    store = _records(site)
    try:
        # One more than a page: whether an older page exists, without counting.
        rows = store.log(account, since, songs, LOG_PAGE + 1, (wanted["page"] - 1) * LOG_PAGE)
        totals = store.log_totals(account, since, songs)
        people = store.db.execute("SELECT id, login_id, dj_name FROM accounts ORDER BY login_id").fetchall()
    finally:
        store.db.close()
    catalog = cat.load(site.data_dir)
    return {"plays": [_log_play(catalog, r) for r in rows[:LOG_PAGE]], "totals": totals,
            "older": len(rows) > LOG_PAGE, "newer": wanted["page"] > 1,
            "people": [dict(p) for p in people]}


def _csv_cell(value):
    """Someone's own text in a CSV cell, never read as a formula by a spreadsheet (a DJ name is the player's own)."""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _plays_csv(site, wanted, now=None):
    """Every play a filter of the plays log leaves (not one page), newest first, as CSV text in pieces: the mark that
    tells a spreadsheet the file is UTF-8, the columns' names, then a row per play with its moment in ISO 8601 (the
    server's clock, with its offset from UTC)."""
    account, since, songs = _log_filter(site, wanted, now)
    catalog = cat.load(site.data_dir)
    store = _records(site)
    try:
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\r\n")
        out.write("﻿")
        writer.writerow(LOG_COLUMNS)
        yield out.getvalue()
        for rows in store.log_all(account, since, songs):
            out.seek(0)
            out.truncate()
            for row in rows:
                play = _log_play(catalog, row)
                # From UTC to the server's own zone: a naive moment turned local asks Windows for a local time before
                # 1970 near the epoch, which it refuses (OSError); an aware one never does.
                moment = datetime.datetime.fromtimestamp(play["at"], datetime.timezone.utc).astimezone().isoformat(
                    timespec="seconds")
                writer.writerow((moment, _csv_cell(play["dj"]), play["mode_name"], play["song"],
                                 _csv_cell(play["title"]), play["pattern"], play["score"]))
            yield out.getvalue()
    finally:
        # Closed when the file is done, or when the download stops half way (the generator is closed then).
        store.db.close()


def _plays_file(site, wanted):
    """Every play a filter of the plays log leaves as a CSV file (_plays_csv), named after today, as the Logs page and
    its API twin hand it out: written as it is read, so a long history never sits in memory whole."""
    name = "openDMT3-plays-%s.csv" % time.strftime("%Y%m%d")
    return StreamingResponse(_counted(_plays_csv(site, wanted)), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="%s"' % name})


def _counted(pieces):
    """A body made piece by piece (Starlette asks for each on a worker thread), each piece's processor time counted to
    the request as the rest of its work is (work.charged): a file of every play is the heaviest answer there is, and
    its caller's fair share counts it (app.Shares)."""
    step = charged(next)
    try:
        while True:
            try:
                piece = step(pieces)
            except StopIteration:
                return
            yield piece
    finally:
        # Closed with the body, when it ends or when the download stops half way: its connection is given back.
        pieces.close()


def _log_counts(site):
    """How many changes the log holds and how many game messages the server keeps, for the Logs page to say when
    its lists (_log) stop short."""
    connection = site.connect()
    try:
        changes = connection.execute("SELECT COUNT(*) FROM changes").fetchone()[0]
    finally:
        connection.close()
    return {"changes": changes, "messages": len(site.game_server.messages) if site.game_server else 0}


def _log_change(site, who, what):
    """A line in the change log (the accounts' own changes write theirs in services/accounts.py)."""
    connection = site.connect()
    try:
        connection.execute("INSERT INTO changes (at, who, what) VALUES (?, ?, ?)", (int(time.time()), who, what))
    finally:
        connection.close()


# ------------------------------------------------------------------ what a page and its API twin both do

def _new_password():
    """A password the server makes (an account made without one, or a new password the admin asks for): 8 hex
    digits, letters and digits within the rules' 6 to 16 (services/accounts.py), shown once."""
    return secrets.token_hex(4)


def _players_address(site, request):
    """(the site's address a player is told, whether another PC reaches it): the one the server was given
    (--site-address, which ./dmt3 setup keeps as its owner chose it), else the one this request came to. An address of
    this PC alone (127.0.0.1, localhost) is one no other PC reaches, whichever of the two it is."""
    address = site.address or str(request.base_url)
    if not address.endswith("/"):
        # As a browser shows a site's top: with its slash.
        address += "/"
    host = (urllib.parse.urlsplit(address).hostname or "").lower()
    return address, host not in ("127.0.0.1", "localhost", "::1")


def _message(site, request, w, login_id, password):
    """The message the admin sends a player after making their account or giving it a new password, in the words `w`
    give (the admin's language): the site's address for players (_players_address: never the admin's own browser's
    when the owner chose one), the ID, the password, and the steps from the Download page on."""
    address = _players_address(site, request)[0]
    return w("admin.message.text", address=address, login_id=login_id, password=password,
             download=address + "download")


def _message_local(site, request):
    """The address in the message when no other PC reaches it (the admin opened the site on the server PC and the
    server was given no address for players), for the page's line that says which address to send; else None."""
    address, reached = _players_address(site, request)
    return None if reached else address


def _set_notice(site, who, text):
    """Show `text` as the notice at the top of every page, or clear it when nothing is left of it (services/notice.py),
    with a line in the change log; returns what shows now ("" once cleared). NoticeError when the rules refuse it."""
    shown = notice.write(site.data_dir, text, who=who)
    _log_change(site, who, "set the notice: %s" % shown if shown else "cleared the notice")
    return shown


def _set_maintenance(site, who, on):
    """Turn maintenance on or off (services/maintenance.py: the game server refuses card logins while it is on), with a
    line in the change log when it changed; returns its state ({"at", "by"} while on, None while off)."""
    state, changed = maintenance.write(site.data_dir, on, who=who)
    if changed:
        _log_change(site, who, "started maintenance" if on else "ended maintenance")
    return state


def _song_list_state(site, w=None):
    """The Status page's Song list card and its API twin (GET /api/v1/server's song_list): each part's count and when
    it was last read, what is missing and why (with `w`, in the page's language too), where the last reading came
    from, whether the server can read its game folder again itself (read_again: a game folder given with --game, in
    Docker the one compose.yaml mounts from GAME_DIR), and the command that imports it on the server PC."""
    out = cat.state(site.data_dir)
    out["read_again"] = bool(site.game_folder)
    # Where it reads from (the path inside the container in Docker), for the admin only, as the button says it.
    out["folder"] = site.game_folder
    # With the folder mounted the front door knows it; otherwise the owner names their game folder or file.
    out["command"] = CATALOG_COMMAND if site.game_folder else CATALOG_COMMAND + " PATH"
    if w is not None:
        for item in out["missing"]:
            # The last reading's reason in the page's language when it has words of its own (errors.py), else as said.
            item["text"] = w.error(Worded(item["why"], item.get("key"))) if item["why"] else None
    return out


def _song_list_places(site):
    """The folders of the server PC the Song list tab looks in (sources.places): the game folder given, and outside
    Docker the server user's usual places."""
    return sources.places(site.game_folder)


def _song_list_found(site):
    """The Song list tab and its API twin (GET /api/v1/server/song_list), looked for on a worker thread: the game's
    files found on the server PC, each with its one line, the places looked in, and whether this server can show its
    PC's other folders (not in Docker, where it sees only the folders kept for it)."""
    places = _song_list_places(site)
    return {"found": sources.as_json(sources.found(places)), "places": places, "browse": not sources.in_container()}


async def _import_song_list(site, who, path=None, upload=None, shown_as=None):
    """Import the song list on a worker thread, one reading at a time: from a path on the server PC in any form (a game
    folder, an archive holding one, a song list), from the game folder the server was given when no path is given
    (Read again), or from an uploaded song list (`upload`, its file; shown_as, the name it came with). Returns
    (report, None) once it is in, with a line in the change log, or (None, (code, why)): "busy" while another runs,
    "refused" for a path or a file that is not what the server takes (its one plain line), "not_read" for anything
    else (the traceback in the server's log and in catalog.log)."""
    source = upload or path or site.game_folder
    if not site.reading.acquire(blocking=False):
        return None, ("busy", "a song list is being imported already")
    try:
        if upload:
            report = await long(songlist.take, upload, site.data_dir, None, shown_as)
        else:
            # traces: a part that cannot be read leaves its traceback in the server's own log as well as catalog.log.
            report = await long(sources.read, source, site.data_dir, None, True)
    except (sources.SourceError, songlist.SongListError, errors.Worded) as e:
        # What the path or the file is, in its own words: nothing changed.
        return None, ("refused", errors.say(e), e)
    except Exception as e:  # noqa: BLE001  (every other reason is said the same way, its traceback kept)
        cat.keep_trace(site.data_dir, "the song list", e)
        log.warning("the song list could not be imported from %s", shown_as or source, exc_info=True)
        return None, ("not_read", cat.why(e), e)
    finally:
        site.reading.release()
    where = ("an uploaded song list (%s)" % shown_as) if upload else source
    # The change log's line written on a worker thread (a write to the database).
    await threaded(_log_change, site, who, "imported the song list from %s: %d songs, %s" % (
        where, report["songs"], ", ".join("%s missing" % part for part in report["missing"]) or "nothing missing"))
    return report, None


async def _upload_song_list(site, request, who, form=False):
    """A song list the admin uploads (the Song list tab's form with its token, or the API's body), written to a file of
    its own in the data folder as it comes, at most songlist.MOST bytes, then imported (_import_song_list) and the file
    removed whatever happened. Returns what _import_song_list returns; SongListError (too large, no file) or FormExpired
    for an upload refused before it was read."""
    if upload.declared_too_large(request, songlist.MOST + (upload.FORM_ROOM if form else 0)):
        raise songlist.too_large()
    fd, part = tempfile.mkstemp(prefix=cat.STAGING + "upload-", suffix=".zip", dir=site.data_dir)
    try:
        with os.fdopen(fd, "wb") as out:
            if form:
                size, name = await upload.form_to(request, out, songlist.MOST, site.csrf(request),
                                                  too_large=songlist.too_large, named=True)
            else:
                size, name = await upload.body_to(request, out, songlist.MOST, too_large=songlist.too_large), None
        if not size:
            raise songlist.no_file()
        return await _import_song_list(site, who, upload=part, shown_as=_upload_name(name))
    except upload.Malformed:
        # A body no page of this site sends: no file to take.
        raise songlist.no_file() from None
    finally:
        cat.remove(part)


def _upload_name(name):
    """The name an uploaded file came with, as the change log and the report keep it: its last part, shortened, or the
    usual name when it came without one (the API's body)."""
    name = (name or songlist.NAME).replace("\\", "/").rsplit("/", 1)[-1].strip() or songlist.NAME
    return name if len(name) <= 80 else name[:77] + "..."


def _delete_backup(site, who, name):
    """Delete one backup, by a backup's own name only (backups.path_of refuses any other: BackupError), with a line in
    the change log."""
    bak.delete(site.data_dir, name)
    _log_change(site, who, "deleted the backup %s" % name)


async def _upload_backup(site, request, who, form=False):
    """A database file the admin uploads, kept as a backup of the kind "upload" (to restore as any other), as the
    Backups tab (`form`: a multipart form with its token) and its API twin (the file is the body) take it: written to
    a file of its own in backups/ as it comes, at most backups.UPLOAD_MOST bytes, then checked on a worker thread
    (backups.keep_upload), named and logged. Returns its name.

    Refused with a BackupError in words (too large, no file, not a database of this project...), or FormExpired (the
    page's token), and its file removed either way: nothing of a refused upload stays."""
    # A body that says beforehand it is too long is refused before a byte of it is read; the form's own fields and
    # boundaries have their room beside the file.
    if upload.declared_too_large(request, bak.UPLOAD_MOST + (upload.FORM_ROOM if form else 0)):
        raise bak.too_large()
    out, part = bak.upload_part(site.data_dir)
    try:
        with out:
            if form:
                size = await upload.form_to(request, out, bak.UPLOAD_MOST, site.csrf(request))
            else:
                size = await upload.body_to(request, out, bak.UPLOAD_MOST)
        if not size:
            # An empty body, or a form sent without its file.
            raise bak.no_file()
    except upload.Malformed:
        # A body no page of this site sends: no file to keep.
        bak.discard(part)
        raise bak.no_file()
    except BaseException:
        # Refused, cut short (the client went away) or failed: the file goes with it.
        bak.discard(part)
        raise
    # The checks read the whole file (seconds for a large one): off the event loop the game server shares.
    name = await long(bak.keep_upload, site.data_dir, part)
    await threaded(_log_change, site, who, "uploaded a backup as %s (%d bytes)" % (name, size))
    return name


def _restore(site, name):
    """Put the database back to a backup (backups.restore: the database as it is backed up first), as the Backups tab
    and its API twin do; returns that first backup's name. The game server's writes wait meanwhile (GameServer.paused):
    a play kept between the first backup and the copy over it would be in neither, so none is; each goes in right
    after, into the database as restored, and no cabinet waits for more than its own login or results meanwhile."""
    # The backups' folder first (a backup being made finishes), then the game server held for the copy alone.
    with bak.changing(), _game_held(site):
        return bak.restore(site.db_path, site.data_dir, name)


def _game_held(site):
    """The game server's writes and reads held for a `with` block (GameServer.paused), or nothing held without a game
    server (the site alone)."""
    return site.game_server.paused() if site.game_server is not None else contextlib.nullcontext()


def _reset_plays(site, who, account=None):
    """Delete every play, or one player's (`account`, their row), as the Players tab and its API twin do: the database
    is backed up first (a backup of the kind "reset", as a restore backs up first), so a restore brings the plays back;
    then the plays go and the change log says how many, and where they are kept. Accounts, DJ cards and settings stay.
    Returns (how many plays went, the backup's name). A backup that cannot be made raises, and nothing is deleted.
    The game server's writes wait from the backup to the deletion, as a restore's do: a play kept between the two would
    be in neither."""
    with bak.changing(), _game_held(site):
        kept = bak.make(site.db_path, site.data_dir, "reset")
        store = _records(site)
        try:
            gone = store.reset(account["id"] if account is not None else None)
        finally:
            store.db.close()
    # Whose plays, how many, and the backup that holds them.
    whose = "the plays of %s" % account["login_id"] if account is not None else "every play"
    _log_change(site, who, "reset %s: %d gone, backed up as %s" % (whose, gone, kept))
    return gone, kept


def _host_port(request):
    """The address the page was opened at, with its port (the scheme's own when the address has none): what the player
    types in the launcher, and what the installer's name carries."""
    host = request.url.hostname or "127.0.0.1"
    return host, request.url.port or (443 if request.url.scheme == "https" else 80)


def _download(site, request):
    """What the Download page says: the installer's facts (downloads.facts: its size, when it was put there and its
    version; None when there is no installer to hand out), the address the launcher asks for, and the name the
    installer is handed out under (both from the address this request came to)."""
    host, port = _host_port(request)
    return {"installer": downloads.facts(os.path.join(site.downloads, INSTALLER)), "address": "%s:%d" % (host, port),
            "file": downloads.download_name(host, port)}


def _installer(site, request):
    """The installer with this server on its end (preset.py), as /download/windows and its API twin hand it out: the
    launcher it installs starts on this server, at the address this request came by, so the player types none. Its
    name carries the address too. None when the server has no installer to hand out."""
    path = os.path.join(site.downloads, INSTALLER)
    if not os.path.isfile(path):
        return None
    end = preset.tail(str(request.base_url).rstrip("/"), request.url.netloc)

    def body():
        # Read in pieces on Starlette's thread pool (a plain generator), then the end.
        with open(path, "rb") as f:
            while True:
                piece = f.read(1 << 20)
                if not piece:
                    break
                yield piece
        yield end

    return StreamingResponse(body(), media_type="application/octet-stream", headers={
        "Content-Disposition": 'attachment; filename="%s"' % downloads.download_name(*_host_port(request)),
        "Content-Length": str(os.path.getsize(path) + len(end))})


def _licence_texts():
    """The licences of the fonts the site serves, read from the files that come with them: {key: text}."""
    texts = {}
    for key, path in LICENCES.items():
        with open(path, encoding="utf-8") as f:
            texts[key] = f.read()
    return texts


def _own_licence():
    """openDMT3's own licence in full, or None when the package runs without its LICENSE beside it (the page then
    names the licence without its text)."""
    try:
        with open(OWN_LICENCE, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _dj_cards(site, rows):
    """Every account's DJ card at once ({account id: card}, profile.dj_cards), for the API's list of players (`rows`,
    every account): how many times each player cleared each chart is one read of every play (0.6 s on 1,000,000), so
    the cards made of it are kept until the plays, an account or a card change, for the song list and the card tables
    they were made with (2,000 small cards, where the counts themselves were hundreds of thousands of rows)."""
    store = _records(site)
    try:
        tables = (files.stamp(os.path.join(site.data_dir, cat.FILE)),
                  files.stamp(os.path.join(site.data_dir, cards.FILE)))
        # The accounts read again inside, after the state the cards are kept under (Lists.get reads that first): a
        # card changed between the caller's look and that state never goes in under the newer state.
        made = site.lists.get(store.db, ("dj_cards", tables), lambda: profile.dj_cards(
            store.db, site.data_dir, store.db.execute("SELECT * FROM accounts ORDER BY login_id").fetchall()))
    finally:
        store.db.close()
    if any(r["id"] not in made for r in rows):
        # An account the kept cards do not have yet (made in another process): made now, for this answer.
        store = _records(site)
        try:
            return profile.dj_cards(store.db, site.data_dir, rows)
        finally:
            store.db.close()
    return made


def _card(site, row):
    """An account's DJ card (services/cards.py): the choices shown, the comment, the level."""
    connection = site.connect()
    try:
        return profile.card(connection, site.data_dir, row)
    finally:
        connection.close()
