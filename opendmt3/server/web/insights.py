"""What the admin pages show of the server's use, beside the numbers common.py gives, each for a page and its API twin:
the machine's last day and what takes the data folder's disk (Status), when players play (Status), the requests log
(Logs, Requests), each player's last two weeks and the Players tab's sorting and file, stopping the server (Status),
and the long jobs that follow a song list's import and a restore (Song list, Backups).

As in common.py, each takes the Site first and runs on a worker thread (the event loop never runs it), but those
that start a job (on the loop: jobs.Jobs.start).
"""

import csv
import datetime
import io
import os
import time

from starlette.responses import StreamingResponse

from opendmt3.server.services import backups as bak
from opendmt3.server.services import catalog as cat
from opendmt3.server.services import cards, machine, requestlog
from opendmt3.server.services.activity import DAY, _day_start
# The jobs' kinds and steps.
from opendmt3.server.web import jobs
from opendmt3.server.web.common import _accounts_call, _counted, _csv_cell, _log_change, _restore

# ------------------------------------------------------------------------------------------------- the machine

# The parts of the data folder the Status tab tells apart, in the order it draws them, each with what it holds (its
# names in the data folder). The rest of the disk (not the server's) and what is free come after them.
DISK_PARTS = (("database", ("openDMT3.sqlite", "openDMT3.sqlite-wal", "openDMT3.sqlite-shm")),
              ("backups", ("backups",)),
              ("song_list", (cat.FILE, cat.JACKETS, cat.READ_FILE, cards.FILE, cards.FOLDER)),
              ("downloads", ("downloads", "updates")),
              ("logs", (requestlog.FOLDER, machine.FILE, cat.LOG_FILE)))
# Seconds the disk's parts are kept counted: walking the folders is the slow part, and they change slowly.
DISK_KEPT = 60.0


def _size(path):
    """The bytes a file or a folder (everything in it, links not followed) takes; 0 when it is not there."""
    try:
        if not os.path.isdir(path) or os.path.islink(path):
            return os.lstat(path).st_size
    except OSError:
        return 0
    total = 0
    for top, _, names in os.walk(path):
        for name in names:
            try:
                total += os.lstat(os.path.join(top, name)).st_size
            except OSError:
                # Gone while counted (a backup pruned, a log turned over): it takes nothing now.
                pass
    return total


def disk_parts(site, now=None):
    """What takes the data folder's disk: {"total", "parts": [{"part", "bytes"}]}, the server's own parts
    (DISK_PARTS), then "other" (what else the disk holds) and "free". Counted at most every DISK_KEPT seconds."""
    now = time.monotonic() if now is None else now
    kept = getattr(site, "_disk_parts", None)
    if kept is not None and now - kept[0] < DISK_KEPT:
        return kept[1]
    usage = machine.read_disk(site.data_dir)
    parts = [{"part": part, "bytes": sum(_size(os.path.join(site.data_dir, n)) for n in names)}
             for part, names in DISK_PARTS]
    if usage is not None:
        ours = sum(p["bytes"] for p in parts)
        # The disk's other files (the system's, other programs'): part of what is used, never less than nothing.
        parts.append({"part": "other", "bytes": max(0, usage["used"] - ours)})
        parts.append({"part": "free", "bytes": usage["free"]})
    out = {"total": usage["total"] if usage else None, "parts": parts}
    site._disk_parts = (now, out)
    return out


def machine_figures(site):
    """GET /api/v1/status/machine: the machine's figures and day (machine.Sampler.figures) and the disk's parts."""
    return dict(site.machine.figures(), disk_parts=disk_parts(site)["parts"])


def _hourly(slots, field):
    """A day of five-minute slots as 24 hours, oldest first: each hour's average of `field` over the points it holds
    (None: none), and its peak."""
    hours = []
    for h in range(24):
        values = [p[field] for p in slots[h * 12:h * 12 + 12] if p and p.get(field) is not None]
        hours.append((round(sum(values) / len(values), 1) if values else None, max(values) if values else None))
    return hours


def _runs(values, top=100.0):
    """A day's values (None: not known) as the chart draws them, in a space as wide as the values and 100 high, the
    floor at 100: [(the line's points, the area's points under it)], one per run of known values (a gap between
    runs is a time nothing was kept). A lone value is a short level line, not a dot."""
    runs, run = [], []
    for i, value in enumerate(values):
        if value is None:
            if run:
                runs.append(run)
            run = []
            continue
        # The value's height, from the floor up, kept inside the chart.
        run.append((i + 0.5, 100 - 96 * max(0.0, min(top, value)) / top))
    if run:
        runs.append(run)
    out = []
    for run in runs:
        if len(run) == 1:
            run = [(run[0][0] - 0.5, run[0][1]), (run[0][0] + 0.5, run[0][1])]
        line = " ".join("%.1f,%.1f" % point for point in run)
        out.append((line, "%.1f,100 %s %.1f,100" % (run[0][0], line, run[-1][0])))
    return out


def machine_view(site, now=None):
    """The Status tab's Resources card: the figures now, and the last day of each measure (cpu, memory, disk) as a
    chart's points (288 five-minute slots, gaps where nothing was kept) and 24 hours for its tips and its table."""
    now = time.time() if now is None else now
    figures = site.machine.figures()
    slots = site.machine.slots(now)
    # The moment each hour of the day starts, oldest first, for the tips, the axis and the table.
    first = now - machine.KEEP * machine.POINT
    hours = [first + h * 3600 for h in range(24)]
    charts = {}
    for field in ("cpu", "memory", "disk"):
        values = [p.get(field) if p else None for p in slots]
        charts[field] = {"runs": _runs(values), "width": len(values),
                         "hours": [(hours[h],) + v for h, v in enumerate(_hourly(slots, field))],
                         "known": sum(1 for v in values if v is not None)}
    return {"figures": figures, "charts": charts, "hours": hours, "since": figures["since"],
            # Less than a day kept yet: the card says since when.
            "partial": now - figures["since"] < machine.KEEP * machine.POINT,
            "disk": disk_parts(site)}


# ------------------------------------------------------------------------------------------------ when people play

# The days the grid of hours goes back.
HOURS_DAYS = 30


def play_hours(site, now=None):
    """When players play: the plays of the last HOURS_DAYS days by day of the week (Monday first) and hour of the
    server's clock, {"days": HOURS_DAYS, "grid": 7 rows of 24 counts, "most": the largest count}. Kept until the plays
    change (cache.py), and made again each day."""
    now = int(time.time() if now is None else now)
    since = _day_start(now) - (HOURS_DAYS - 1) * DAY
    connection = site.connect()
    try:
        def make():
            # SQLite's own day of the week (0 is Sunday) and hour, on the server's clock.
            return [dict(r) for r in connection.execute(
                "SELECT CAST(strftime('%w', played_at, 'unixepoch', 'localtime') AS INTEGER) AS day,"
                " CAST(strftime('%H', played_at, 'unixepoch', 'localtime') AS INTEGER) AS hour, COUNT(*) AS n"
                " FROM plays WHERE played_at >= ? GROUP BY day, hour", (since,))]
        rows = site.lists.get(connection, ("play_hours", since), make)
    finally:
        connection.close()
    grid = [[0] * 24 for _ in range(7)]
    for r in rows:
        # Monday first: SQLite's Sunday (0) goes last.
        grid[(r["day"] + 6) % 7][r["hour"]] = r["n"]
    return {"days": HOURS_DAYS, "grid": grid, "most": max(max(row) for row in grid)}


# ---------------------------------------------------------------------------------------------- the requests log

def requests_wanted(params):
    """The requests log's filter from a query: q (a word of the path, the address or the account) and kind (ok,
    moved, refused or failed, or a status of three digits). What cannot be read is no filter; `unread` names it."""
    kind = params.get("kind", "").strip()
    read = kind in requestlog.KINDS or (kind.isdigit() and len(kind) == 3)
    # The page of the list (the newest first): the Logs tab shows REQUESTS_PAGE a page; a page past the last one there
    # is (a bookmark kept while the log rolled on) says so, with the way to the last (requests_log's past, last_page).
    page = params.get("page", "1").strip()
    return {"q": params.get("q", "").strip()[:64], "kind": kind if read else "",
            "page": max(1, min(int(page), 1000)) if page.isdigit() else 1,
            "unread": ["kind"] if kind and not read else []}


# The requests the Logs tab shows a page (a phone's page of 400 rows was 53 screens long).
REQUESTS_PAGE = 50


def requests_log(site, wanted, now=None, most=200, per=None):
    """The Logs tab's Requests view: the last day by half hours (the chart), and the newest requests the filter
    leaves, at most `most`, with how many it left of those kept in memory. With `per`, one page of them: the
    wanted page's `per` (newer and older say whether there are pages either side), the last page there is
    (last_page) and whether the one asked is past it (past: a bookmark kept while the log rolled on)."""
    page = wanted.get("page", 1)
    if per:
        most = min(requestlog.RECENT, page * per + 1)
    shown, found = site.requests.recent(wanted["q"], wanted["kind"], most)
    older = False
    if per:
        older = len(shown) > page * per
        shown = shown[(page - 1) * per:page * per]
    # The last page there is (1 when nothing is found), of the found the pages reach (they are of those kept).
    last = max(1, -(-found // per)) if per else 1
    chart = site.requests.chart(now)
    return {"chart": chart, "most": max([s["ok"] + s["bad"] for s in chart] + [0]),
            "day": {"ok": sum(s["ok"] for s in chart), "bad": sum(s["bad"] for s in chart)},
            "requests": shown, "found": found, "kept": requestlog.RECENT, "bytes": site.requests.size(),
            "page": page, "newer": bool(per) and page > 1, "older": older, "last_page": last,
            "past": bool(per) and page > last}


def _iso(at):
    """A moment as the CSV files give it: ISO 8601 on the server's clock, with its offset from UTC."""
    return datetime.datetime.fromtimestamp(at, datetime.timezone.utc).astimezone().isoformat(timespec="seconds")


def _requests_csv(site, wanted):
    """Every request the log's files keep that the filter leaves, oldest first, as CSV text in pieces (the plays file's
    shape: the UTF-8 mark, the columns' names, then the rows)."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    out.write("﻿")
    writer.writerow(requestlog.FIELDS)
    yield out.getvalue()
    rows = 0
    for line in site.requests.all(wanted["q"], wanted["kind"]):
        if rows == 0:
            out.seek(0)
            out.truncate()
        # Every text a request brought (and a line an older server wrote, before it kept only HTTP's own methods) never
        # read as a formula by a spreadsheet; the moment, the status and the time are the server's own numbers.
        writer.writerow((_iso(line.get("at", 0)), _csv_cell(line.get("method") or ""), _csv_cell(line.get("path", "")),
                         line.get("status"), line.get("ms"), _csv_cell(line.get("address") or ""),
                         _csv_cell(line.get("who") or "")))
        rows += 1
        # A piece every thousand rows: the file is written as it is read.
        if rows == 1000:
            yield out.getvalue()
            rows = 0
    if rows:
        yield out.getvalue()


def requests_file(site, wanted):
    """The requests log as a CSV file named after today, as the Logs tab and its API twin hand it out."""
    # In lowercase: the tool, what it holds and the day (as the release's files are named).
    name = "opendmt3-requests-%s.csv" % time.strftime("%Y%m%d")
    return StreamingResponse(_counted(_requests_csv(site, wanted)), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="%s"' % name})


# ------------------------------------------------------------------------------------------------ the players

# The days of each player's row of cells.
ACTIVITY_DAYS = 14
# The Players tab's sorting: a column's key, the value it sorts by, and whether its first order is the highest first.
SORTS = {"id": (lambda r: r["login_id"], False), "dj": (lambda r: (r["dj_name"] or "").casefold(), False),
         "last": (lambda r: r["last_login"] or 0, True), "played": (lambda r: r["last_play"] or 0, True),
         "days": (lambda r: r["plays_days"], True), "plays": (lambda r: r["plays"], True)}
# The players file's columns.
PLAYER_COLUMNS = ("login_id", "dj_name", "admin", "disabled", "last_sign_in", "last_play", "plays", "plays_14_days")


def activity(site, now=None):
    """Each player's plays over the last ACTIVITY_DAYS days (one count a day, oldest first, today last), every play
    of theirs counted and their last play: {account id: {"days", "plays", "last_play"}}, and the start of the first
    day. Kept until the plays change, and made again each day."""
    now = int(time.time() if now is None else now)
    start = _day_start(now) - (ACTIVITY_DAYS - 1) * DAY
    connection = site.connect()
    try:
        def make():
            # The day of each play from the first day's start (days of the server's clock: _day_start's), per player.
            days = connection.execute(
                "SELECT account_id, (played_at - ?) / ? AS day, COUNT(*) FROM plays WHERE played_at >= ?"
                " GROUP BY account_id, day", (start, DAY, start)).fetchall()
            # Every player's plays and last play, along each player's own index (plays_by_account).
            totals = connection.execute(
                "SELECT account_id, COUNT(*), MAX(played_at) FROM plays GROUP BY account_id").fetchall()
            return [{"days": [list(r) for r in days], "totals": [list(r) for r in totals]}]
        made = site.lists.get(connection, ("activity", start), make)[0]
    finally:
        connection.close()
    out = {}
    for account, plays, last in made["totals"]:
        out[account] = {"days": [0] * ACTIVITY_DAYS, "plays": plays, "last_play": last}
    for account, day, n in made["days"]:
        if account in out and 0 <= day < ACTIVITY_DAYS:
            out[account]["days"][day] = n
    return out, start


def players_rows(site, sort="played", order=None, now=None):
    """Every account as the Players tab lists it, with its last two weeks (days, plays_days: their sum), every play
    (plays) and its last play, sorted by a column of SORTS (an unknown one: by last play) in its first order, or the
    other with order "asc" / "desc". Returns (rows, the sort used, its order, the first day's start, the most plays of
    any player on one day: the cells' one scale)."""
    rows = [dict(r) for r in _accounts_call(site, "all")]
    days, start = activity(site, now)
    empty = {"days": [0] * ACTIVITY_DAYS, "plays": 0, "last_play": None}
    for r in rows:
        mine = days.get(r["id"], empty)
        r.update(days=mine["days"], plays_days=sum(mine["days"]), plays=mine["plays"], last_play=mine["last_play"])
    if sort not in SORTS:
        sort = "played"
    key, high_first = SORTS[sort]
    if order not in ("asc", "desc"):
        order = "desc" if high_first else "asc"
    rows.sort(key=lambda r: r["login_id"])
    rows.sort(key=key, reverse=order == "desc")
    most = max([max(r["days"]) for r in rows] + [0])
    return rows, sort, order, start, most


def _players_csv(site):
    """Every account as a row of the players file (the plays file's shape), sorted by ID."""
    rows, _, _, _, _ = players_rows(site, "id")
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    out.write("﻿")
    writer.writerow(PLAYER_COLUMNS)
    for r in rows:
        # A time never reached is an empty cell; the DJ name is the player's own text (never a formula).
        writer.writerow((r["login_id"], _csv_cell(r["dj_name"]), int(bool(r["is_admin"])), int(bool(r["disabled"])),
                         _iso(r["last_login"]) if r["last_login"] else "",
                         _iso(r["last_play"]) if r["last_play"] else "", r["plays"], r["plays_days"]))
    yield out.getvalue()


def players_file(site):
    """The players as a CSV file named after today, as the Players tab and its API twin hand it out."""
    # In lowercase: the tool, what it holds and the day (as the release's files are named).
    name = "opendmt3-players-%s.csv" % time.strftime("%Y%m%d")
    return StreamingResponse(_counted(_players_csv(site)), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="%s"' % name})


# ------------------------------------------------------------------------------------------- stopping the server

# The change log's line for each thing the server's runner is asked (strings.py: log.change.server.*).
ASKED = {"stop": "stopped the server", "restart": "restarted the server", "remove": "removed the server",
         "remove_data": "removed the server and its data"}


def ask_runner(site, who, action, delete_data=False):
    """Ask the server's runner to stop, restart or remove it (runner.Runner.ask; remove with its data or not), with a
    line in the change log first: True when it was asked now, False when it cannot be asked this (the page names how
    instead) or was asked something already."""
    if not site.runner.can(action) or site.runner.asked is not None:
        return False
    _log_change(site, who, ASKED["remove_data" if action == "remove" and delete_data else action])
    return site.runner.ask(action, *((bool(delete_data),) if action == "remove" else ()))


def stop_server(site, who):
    """Ask the server's runner to stop it (ask_runner)."""
    return ask_runner(site, who, "stop")


def last_copy(site):
    """Where removing the server's data keeps the database's last copy, beside the data folder (__main__.remove_data:
    its name and the time it goes)."""
    data = os.path.abspath(site.data_dir)
    return os.path.join(os.path.dirname(data), "%s-last-YYYYMMDD-HHMMSS.sqlite" % (os.path.basename(data) or "data"))


# ------------------------------------------------------------------------------------------------- the jobs

def start_restore(site, who, name):
    """A restore as a job (jobs.py): the backup checked first (BackupError at once for one that is not there), then put
    back on a long work's thread, its steps followed, the change log's line written once it is done. Returns the job;
    on the event loop."""
    # The name refused now when it is no backup's: the page says so at once, no job is made.
    bak.path_of(site.data_dir, name)

    def work():
        return {"restored": name, "kept_as": _restore(site, name)}

    def finish(job):
        if job.state == "done":
            _log_change(site, who, "restored the database from %s" % name)
    return site.jobs.start("restore", who, work, details={"name": name}, finish=finish)


def job_words(w, job):
    """A job as the progress card says it: its title, the step it is on, and how it ended (the line the page leaves
    once it is done, or the error in words)."""
    view = job.view()
    view["title"] = w("job." + job.kind)
    view["step_text"] = w("job.step." + job.step) if job.step else w("job.step.start")
    # Done of total within the step when the work counts (the jackets saved, the pages copied).
    view["count_text"] = w("job.count", done=job.done or 0, total=job.total) if job.total else ""
    # Every step a job of its kind may go through, in order: the card lists them all and shows those of this job.
    routes = [jobs.STEPS.get(job.kind, ())] + list(jobs.ROUTES.get(job.kind, {}).values())
    view["all_steps"] = [s for s in ("unpack", "check", "songs", "jackets", "cards", "swap", "backup", "copy", "upgrade")
                         if any(s in steps for steps in routes)]
    if job.state == "done":
        view["text"] = w("job.done." + job.kind, **_done_values(job))
    elif job.state == "failed":
        error = job.exception
        if getattr(error, "key", None):
            # A worded refusal (errors.py): its own line in the page's language.
            view["text"] = w.error(error)
        elif job.kind == "song_list":
            # Any other reason the song list could not be read, as the Song list tab has always said it.
            view["text"] = w("songlist.not_read", why=cat.why(error))
        else:
            view["text"] = w("job.failed", why=str(error))
    else:
        view["text"] = view["step_text"]
    return view


def _done_values(job):
    """The values the line of a job done says."""
    if job.kind == "restore":
        return {"name": job.details.get("name", ""), "safety": (job.result or {}).get("kept_as", "")}
    return {"songs": (job.result or {}).get("songs", 0)}
