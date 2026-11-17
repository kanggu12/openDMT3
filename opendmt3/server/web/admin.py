"""The admin pages: the players (their plays reset too), the cabinets, the server's status and its notice, the song
list (found on the server PC, from another folder of it, or uploaded), the logs (changes and game messages; every play,
with a CSV file of them) and the backups, with a backup's file to download. To an account that is not an admin's, each
answers as a page that does not exist would.

routes(site) gives create_app (app.py) their routes, in the order the route table has always had them.

As on the public pages (pages.py), a handler without a body to read is a plain function (Starlette runs it on a worker
thread), and one with a form or an upload reads it on the loop and hands the rest to a worker thread.
"""

import hmac
import os
from urllib.parse import quote, urlencode

from starlette.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.routing import Route

from opendmt3.server.services import accounts as acc
from opendmt3.server.services import backups as bak
from opendmt3.server.services import maintenance, notice, songlist, sources
# The worker threads a handler hands its work to, its processor time counted (work.py).
from opendmt3.server.web.work import long, threaded
from opendmt3.server.web import strings, upload
# What the API's twins of these pages show and do too, the error page and a redirect (common.py).
from opendmt3.server.web.common import (ACCOUNT_FIELDS, LOG_DAYS, _accounts_call, _delete_backup, _known_cabinets, _log,
                                 _log_change,
                                 _log_counts, _message, _new_password, _not_found, _plays_file, _plays_log, _plays_wanted,
                                 _redirect, _reset_plays, _set_maintenance, _set_notice, _status, _to_look_at,
                                 _upload_backup, not_found, _song_list_state, _song_list_found,
                                 _upload_song_list, _look_text, _message_local, _start_import, _import_outcome,
                                 _invite)
# The use of the server the pages show beside those (the machine, when people play, the requests log, the players' last
# two weeks), stopping the server, and the long jobs (insights.py).
from opendmt3.server.web import insights



# What the Players page's forms do (any other action is refused in words).
PLAYER_ACTIONS = ("make", "password", "disable", "enable", "delete", "admin_on", "admin_off", "rename", "reset_plays",
                  "reset_all")

def routes(site):
    """The admin pages' routes for one Site. The handlers are made here as closures over the Site, as they were in
    create_app."""

    async def admin_players(request):
        w = strings.words(site.language(request))
        form = await request.form() if request.method == "POST" else None
        user = await threaded(site.account, request)
        if not user["is_admin"]:
            return await not_found(site, request)
        notice, error, message, field, typed = None, None, None, None, None
        if form is not None:
            if not hmac.compare_digest(form.get("csrf", ""), site.csrf(request)):
                error = w("form.expired")
            else:
                action, login_id = form.get("action"), form.get("login_id", "").strip().upper()
                try:
                    if action == "make":
                        # What was typed comes back in its fields if the rules refuse it (never the password).
                        typed = {"login_id": login_id[:8], "dj_name": form.get("dj_name", "").strip()[:acc.DJ_NAME_MAX]}
                        # The password typed, or one the server makes (as the API's twin does).
                        password = form.get("password") or _new_password()
                        # Hashed on a worker thread (Site.hashed), as every password is.
                        await site.hashed(_accounts_call, site, "create", login_id, password,
                                          form.get("dj_name", "").strip() or None,
                                          is_admin=form.get("is_admin") == "on", who=user["login_id"])
                        notice = w("admin.made", login_id=login_id, password=password)
                        # What the player needs, ready to send: the address, the ID, the password, the steps.
                        message = _message(site, request, w, login_id, password)
                    elif action == "password":
                        password = _new_password()
                        await site.hashed(_accounts_call, site, "set_password", login_id, password,
                                          who=user["login_id"])
                        notice = w("admin.newpass.done", login_id=login_id, password=password)
                        message = _message(site, request, w, login_id, password)
                    else:
                        # Every other change, on a worker thread (a reset backs the database up first: on a thread of
                        # the long work's own); a page to go to instead when it says so.
                        run = long if action in ("reset_plays", "reset_all") else threaded
                        notice, back = await run(_players_change, w, user, action, login_id, form)
                        if back:
                            return _redirect(back)
                        if notice is None:
                            # Nothing was done (one's own account, an ID with no account, a change this page does not
                            # make): said, as the player's page and the API say it.
                            error = _players_nothing(w, user, action, login_id)
                except acc.AccountError as e:
                    error = w.error(e)
                    # The new account's field the refusal is about, under which it is said.
                    field = ACCOUNT_FIELDS.get(getattr(e, "key", "")) if action == "make" else None
        return await threaded(_players_shown, request, user, notice, error, message, field, typed)

    def _players_nothing(w, user, action, login_id):
        """Why a change of the Players page did nothing, in the page's words."""
        if action == "delete" and login_id == user["login_id"]:
            return w("admin.nothing.self")
        if action not in PLAYER_ACTIONS:
            return w("admin.nothing.action")
        return w("admin.nothing.account", login_id=login_id)

    def _players_change(w, user, action, login_id, form):
        """admin_players' changes that make no password, on a worker thread: (the notice, a page to go to instead).
        AccountError when the rules refuse it."""
        store = site.accounts()
        try:
            if action in ("disable", "enable"):
                # The server keeps an enabled admin: disabling the last one is refused (AccountError).
                store.set_disabled(login_id, action == "disable", who=user["login_id"])
            elif action == "delete" and login_id != user["login_id"]:
                store.delete(login_id, who=user["login_id"])
            elif action in ("admin_on", "admin_off") and store.by_login(login_id) is not None:
                # The only enabled admin keeps their rights: taking them is refused (AccountError).
                store.set_admin(login_id, action == "admin_on", who=user["login_id"])
                if login_id == user["login_id"] and action == "admin_off":
                    # Their own rights taken (another admin has some): the admin pages are not theirs any more.
                    return None, "/"
                return w("admin.rights." + ("given" if action == "admin_on" else "taken"), login_id=login_id), None
            elif action == "rename" and store.by_login(login_id) is not None:
                # A player's DJ name, by the account page's own rules (accounts.check_dj_name).
                name = form.get("dj_name", "").strip()
                store.set_dj_name(login_id, name, who=user["login_id"])
                return w("admin.renamed", login_id=login_id, dj=name), None
            elif action == "reset_plays" and store.by_login(login_id) is not None:
                # One player's plays, asked first on the page; backed up first, then reset and logged as the API's
                # twin does it (common._reset_plays).
                gone, kept = _reset_plays(site, user["login_id"], store.by_login(login_id))
                return w("admin.reset.done", login_id=login_id, n=gone, backup=kept), None
            elif action == "reset_all":
                # Every player's plays, asked first on the page, the same way.
                gone, kept = _reset_plays(site, user["login_id"])
                return w("admin.reset.all.done", n=gone, backup=kept), None
            return None, None
        finally:
            store.db.close()

    def _players_shown(request, user, notice, error, message, field=None, typed=None):
        """The Players page itself, on a worker thread: every account sorted as ?sort= and ?order= ask (by last play
        unless they ask otherwise), each with its last two weeks."""
        rows, sort, order, start, most = insights.players_rows(site, request.query_params.get("sort", ""),
                                                               request.query_params.get("order"))
        # Each day of the row of cells, for their tips and the column's words.
        days = [start + n * 86400 for n in range(insights.ACTIVITY_DAYS)]
        # With a message whose address only this PC reaches, the page says which address to send in its place.
        return site.render(request, "admin_players.html", user=user, rows=rows, notice=notice, error=error, field=field,
                           typed=typed,
                           message=message, message_local=_message_local(site, request) if message else None,
                           dj_max=acc.DJ_NAME_MAX, sort=sort, order=order, days=days, most=most,
                           sorts=insights.SORTS, invite=_invite(site, request))

    def admin_players_file(request):
        """Every player as a CSV file (insights.players_file, shared with the API's twin)."""
        user = site.account(request)
        if not user["is_admin"]:
            return _not_found(site, request)
        return insights.players_file(site)

    async def admin_cabinets(request):
        """The cabinets: every one seen (named by the admin, or by its address), and who plays on each now."""
        form = await request.form() if request.method == "POST" else None
        return await threaded(_cabinets_page, request, form)

    def _cabinets_page(request, form):
        """admin_cabinets on a worker thread: a renaming posted, then the page."""
        user = site.account(request)
        if not user["is_admin"]:
            return _not_found(site, request)
        w = strings.words(site.language(request))
        notice, error = None, None
        if form is not None:
            if not hmac.compare_digest(form.get("csrf", ""), site.csrf(request)):
                error = w("form.expired")
            elif form.get("action") == "rename":
                activity = site.activity()
                try:
                    done = activity.rename_cabinet(int(form.get("id", "0") or 0), form.get("name", ""))
                finally:
                    activity.db.close()
                if done:
                    _log_change(site, user["login_id"],
                                "named cabinet %s %r" % (form.get("id"), form.get("name", "").strip()))
                    notice = w("cabinets.renamed")
        # The server and who is on it: the cabinets (the game's connections) and the launchers that asked its API
        # (launchers.py), each PC's by its address.
        return site.render(request, "admin_cabinets.html", user=user, cabinets=_known_cabinets(site), notice=notice,
                           error=error, launchers=site.launchers.view(), launchers_since=site.launchers.since,
                           game_port=site.game_port)

    async def admin_status(request):
        """The server's state and numbers, what may want a look, the song list (what it holds; imported on its own
        tab), the notice every page shows (set or cleared here), and maintenance (on or off here: the game server
        refuses card logins while it is on)."""
        form = await request.form() if request.method == "POST" else None
        return await threaded(_status_page, request, form)

    def _status_page(request, form):
        """admin_status on a worker thread: a change posted, then the page."""
        user = site.account(request)
        if not user["is_admin"]:
            return _not_found(site, request)
        w = strings.words(site.language(request))
        done, error = None, None
        if form is not None:
            if not hmac.compare_digest(form.get("csrf", ""), site.csrf(request)):
                error = w("form.expired")
            elif form.get("action") in ("maintenance_on", "maintenance_off"):
                # Maintenance on or off: the game server refuses card logins while it is on. Written and logged as the
                # API's twin does it.
                on = form.get("action") == "maintenance_on"
                _set_maintenance(site, user["login_id"], on)
                done = w("maintenance.started" if on else "maintenance.ended")
            else:
                # The line typed, or nothing (Clear, or a line left empty): the notice goes.
                text = "" if form.get("action") == "clear" else form.get("text", "")
                try:
                    # Written and logged as the API's twin does it.
                    shown = _set_notice(site, user["login_id"], text)
                except notice.NoticeError as e:
                    # Too long, or not text: the rule's own words, in the admin's language.
                    error = w.error(e)
                else:
                    done = w("notice.saved" if shown else "notice.cleared")
        # The numbers as the API gives them, and above them what may want a look (each line only when it is so).
        # Each line to look at in the page's words (common._look_text, as the API's twin gives it).
        look = [dict(item, text=_look_text(w, item)) for item in _to_look_at(site, user)]
        return site.render(request, "admin_status.html", user=user, server=_status(site),
                           look=look, notice=done, error=error, data=_song_list_state(site, w),
                           kept=notice.read(site.data_dir), notice_max=notice.MOST,
                           maintenance=maintenance.read(site.data_dir), machine=insights.machine_view(site),
                           hours=insights.play_hours(site), here="/admin/status")

    async def admin_server(request):
        """The server itself: what started it, and Restart, Stop and Remove, each asking that one (runner.py), with the
        commands for what it cannot be asked here. After a stop or a restart the page that answers says what happens
        next (the restart's page comes back here once the server answers again)."""
        form = await request.form() if request.method == "POST" else None
        return await threaded(_server_page, request, form)

    def _server_page(request, form):
        """admin_server on a worker thread: a request posted, then the page (or the page of a server going)."""
        user = site.account(request)
        if not user["is_admin"]:
            return _not_found(site, request)
        w = strings.words(site.language(request))
        error = None
        if form is not None:
            action = form.get("action", "")
            if not hmac.compare_digest(form.get("csrf", ""), site.csrf(request)):
                error = w("form.expired")
            elif action in ("stop", "restart", "remove", "remove_data"):
                # Asked of the one that started the server; the page says what happens next before it does.
                if insights.ask_runner(site, user["login_id"], "remove" if action == "remove_data" else action,
                                       delete_data=action == "remove_data"):
                    return site.render(request, "admin_server_going.html", user=user, action=action,
                                       runner=site.runner, run=site.run, data_dir=os.path.abspath(site.data_dir),
                                       kept=insights.last_copy(site))
                error = w("server.not_asked")
        return site.render(request, "admin_server.html", user=user, error=error, runner=site.runner,
                           server=_status(site), data_dir=os.path.abspath(site.data_dir),
                           kept=insights.last_copy(site))

    async def admin_song_list(request):
        """The song list, in the shape of OpenDMTQ's setup page: what the server takes (the song list, with its jackets
        and the DJ cards) and whether it has it, the game's files found on the server PC (each with its one line and
        Import), another folder of the server PC (a path, its quick folders and a folder browser; outside Docker
        only), and the upload of a song list the launcher saved (its own route, admin_song_list_upload). Import is
        posted here; the API's twins are GET and POST /api/v1/server/song_list and GET /api/v1/server/folders."""
        form = await request.form() if request.method == "POST" else None
        user = await threaded(site.account, request)
        if not user["is_admin"]:
            return await not_found(site, request)
        w = strings.words(site.language(request))
        done, error = None, None
        if form is not None:
            if not hmac.compare_digest(form.get("csrf", ""), site.csrf(request)):
                error = w("form.expired")
            elif form.get("action") == "import":
                # A path from the list found, from the folder browser or typed (empty: the game folder given): a job,
                # which the page follows at its own address (?job=) until it ends.
                path = form.get("path", "").strip() or None
                job, refused = _start_import(site, user["login_id"], path=path)
                if job is not None and not await site.jobs.settled(job):
                    return _redirect("/admin/song_list?job=" + job.id)
                done, error = _imported(w, *(_import_outcome(job) if job is not None else (None, refused)))
        return await _song_list_page(request, user, done, error)

    async def _song_list_page(request, user, done, error, status=200):
        """The Song list tab with the line a form left: what is found is looked for on a worker thread (each look is
        kept a little while: sources.found), and the browser's folder from ?browse= (outside Docker)."""
        w = strings.words(site.language(request))
        # The job the page follows (?job=): its progress card while it runs, its line once it ended.
        job = _followed(request, w)
        if job is not None and job["state"] != "running" and not (done or error):
            done, error = (job["text"], None) if job["state"] == "done" else (None, job["text"])
        found = await long(_song_list_found, site)
        for item in found["found"]:
            # Each one's line in the page's language.
            item["said"] = sources.said(item, site.language(request))
        browsing, browse_error = None, None
        if found["browse"]:
            asked = request.query_params.get("browse") or (found["places"][0] if found["places"] else "/")
            try:
                browsing = await threaded(sources.folders, asked)
            except sources.SourceError as e:
                # Said in the folder browser itself (the page's state, not what a form just did).
                browse_error = w.error(e)
                browsing = await threaded(sources.folders, "/")
            # The folders in it with their whole paths, and the path's own folders as steps to click back to.
            browsing["links"] = [(name, os.path.join(browsing["path"], name)) for name in browsing["folders"]]
            browsing["crumbs"] = _crumbs(browsing["path"])
        return await threaded(lambda: site.render(
            request, "admin_song_list.html", status=status, here="/admin/song_list", user=user,
            data=_song_list_state(site, w), found=found, browsing=browsing, browse_error=browse_error, notice=done,
            error=error,
            upload_most=songlist.MOST, upload_mb=songlist.MOST >> 20, too_large=w.error(songlist.too_large()),
            quote=quote, command="./dmt3 catalog PATH", job=job if job and job["state"] == "running" else None))

    def _followed(request, w):
        """The job a page follows (?job= of the kind the page starts), in the page's words, or None."""
        found = site.jobs.get(request.query_params.get("job", ""))
        return insights.job_words(w, found) if found is not None else None

    def _crumbs(path):
        """A folder's path as steps from the top: [(name, the path up to it)], the top as "/"."""
        steps, here = [("/", "/")], "/"
        for part in [p for p in path.split("/") if p]:
            here = os.path.join(here, part)
            steps.append((part, here))
        return steps

    def _imported(w, report, refused):
        """(done, error) for the page from what _import_song_list gave."""
        if refused:
            # busy, refused (the path's or the file's own line, in the page's language) or not read.
            if refused[0] == "refused":
                return None, w.error(refused[2])
            return None, w("songlist." + refused[0], why=refused[1])
        return w("songlist.done", songs=report["songs"]), None

    async def admin_song_list_upload(request):
        """A song list the admin uploads (saved by the launcher, or by ./dmt3 catalog --save): written into the data
        folder as it comes, checked, and taken in (common._upload_song_list, shared with the API's twin). Only an
        admin's form gets this far: anyone else's body is never read."""
        user = await threaded(site.account, request)
        if not user["is_admin"]:
            # A plain answer: no page made for a post nobody but an admin sends.
            return PlainTextResponse("Not Found", status_code=404)
        w = strings.words(site.language(request))
        try:
            job, refused = await _upload_song_list(site, request, user["login_id"], form=True, wait=False)
        except upload.FormExpired:
            # No token, or another one, before the file: nothing was read of it.
            return await _song_list_page(request, user, None, w("form.expired"))
        except songlist.SongListError as e:
            # Too large, or no file: in the admin's language; a body too large says so with its status too.
            return await _song_list_page(request, user, None, w.error(e),
                                         413 if e.key == "error.songlist.too_large" else 200)
        if job is not None and not await site.jobs.settled(job):
            # The import goes on as a job; the tab follows it at its own address.
            return _redirect("/admin/song_list?job=" + job.id)
        done, error = _imported(w, *(_import_outcome(job) if job is not None else (None, refused)))
        return await _song_list_page(request, user, done, error)

    def admin_job(request):
        """One job as the progress card follows it (site.js asks every second), in the page's words: JSON for the
        admin's own browser (the API's twin is GET /api/v1/jobs/{id})."""
        user = site.account(request)
        if not user["is_admin"]:
            return _not_found(site, request)
        found = site.jobs.get(request.path_params["id"])
        if found is None:
            return JSONResponse({"error": {"code": "unknown_job", "message": "no such job"}}, status_code=404)
        return JSONResponse(insights.job_words(strings.words(site.language(request)), found))

    def admin_log(request):
        user = site.account(request)
        if not user["is_admin"]:
            return _not_found(site, request)
        # The newest changes and game messages, with how many there are in all (the lists say when they stop short).
        log = _log(site)
        for change in log["changes"]:
            # Kept as the English line the server wrote; shown in the reader's language (strings.changed).
            change["said"] = strings.changed(site.language(request), change["what"])
        return site.render(request, "admin_log.html", user=user, log=log, counts=_log_counts(site))

    def admin_log_plays(request):
        """The log's plays: every play, filtered by player, days and a word in the song title, LOG_PAGE at a time
        (older and newer pages), with what the filter leaves counted and a file of all of it."""
        user = site.account(request)
        if not user["is_admin"]:
            return _not_found(site, request)
        wanted = _plays_wanted(request.query_params)
        # The filter as the links carry it: the file of it, and the pages before and after this one.
        kept = {key: wanted[key] for key in ("player", "days", "q") if wanted[key]}
        links = {"csv": "/admin/log/plays.csv" + ("?" + urlencode(kept) if kept else ""),
                 "newer": "/admin/log/plays?" + urlencode(dict(kept, page=wanted["page"] - 1)),
                 "older": "/admin/log/plays?" + urlencode(dict(kept, page=wanted["page"] + 1))}
        return site.render(request, "admin_log_plays.html", user=user, wanted=wanted, log=_plays_log(site, wanted),
                           days=LOG_DAYS, links=links)

    def admin_log_requests(request):
        """The log's requests: the last day by half hours, then the newest requests the filter leaves (a word, a kind
        of answer), with a file of all the log keeps."""
        user = site.account(request)
        if not user["is_admin"]:
            return _not_found(site, request)
        wanted = insights.requests_wanted(request.query_params)
        kept = {key: wanted[key] for key in ("q", "kind") if wanted[key]}
        # A page of REQUESTS_PAGE, with the ways to the newer and the older ones (the filter kept in them).
        log = insights.requests_log(site, wanted, per=insights.REQUESTS_PAGE)
        links = {side: "/admin/log/requests?" + urlencode(dict(kept, page=wanted["page"] + step))
                 for side, step in (("newer", -1), ("older", 1))}
        return site.render(request, "admin_log_requests.html", user=user, wanted=wanted, links=links,
                           log=log, kinds=list(insights.requestlog.KINDS),
                           csv="/admin/log/requests.csv" + ("?" + urlencode(kept) if kept else ""),
                           log_mb=(insights.requestlog.MOST_BYTES * insights.requestlog.FILES) >> 20,
                           log_days=insights.requestlog.DAYS)

    def admin_log_requests_csv(request):
        """Every request the log keeps that the filter leaves, as a CSV file (shared with the API's twin)."""
        user = site.account(request)
        if not user["is_admin"]:
            return _not_found(site, request)
        return insights.requests_file(site, insights.requests_wanted(request.query_params))

    def admin_log_plays_csv(request):
        """Every play the log's filter leaves, as a CSV file (common._plays_file, shared with the API's twin)."""
        user = site.account(request)
        if not user["is_admin"]:
            return _not_found(site, request)
        return _plays_file(site, _plays_wanted(request.query_params))

    async def admin_backups(request):
        """Backups of the database: one a day while the server runs (the week's kept), one now, download, restore (a
        job the page follows at its own address, ?job=), delete; an upload is posted to its own route
        (admin_backup_upload) and comes back to this page."""
        form = await request.form() if request.method == "POST" else None
        if form is not None and form.get("action") == "restore":
            started = await _restore_started(request, form)
            if started is not None:
                return started
        # A backup made or put back copies the whole database: on a thread of the long work's own.
        return await long(_backups_posted, request, form)

    def _backups_posted(request, form):
        """admin_backups on a worker thread (a backup copies the whole database): a change posted, then the page."""
        user = site.account(request)
        if not user["is_admin"]:
            return _not_found(site, request)
        w = strings.words(site.language(request))
        notice, error = None, None
        if form is not None:
            if not hmac.compare_digest(form.get("csrf", ""), site.csrf(request)):
                error = w("form.expired")
            else:
                try:
                    if form.get("action") == "make":
                        name = bak.make(site.db_path, site.data_dir, "manual")
                        _log_change(site, user["login_id"], "backed up the database as %s" % name)
                        notice = w("backups.made", name=name)
                    elif form.get("action") == "restore":
                        # Only reached when the restore could not start (admin_backups starts it as a job): the
                        # backup's own refusal, in the admin's words.
                        bak.path_of(site.data_dir, form.get("name", ""))
                    elif form.get("action") == "delete":
                        # Only a backup's own name (path_of refuses any other), asked first on the page; deleted and
                        # logged as the API's twin does it.
                        name = form.get("name", "")
                        _delete_backup(site, user["login_id"], name)
                        notice = w("backups.deleted", name=name)
                except bak.BackupError as e:
                    error = w.error(e)
        return _backups_page(request, user, notice, error)

    async def _restore_started(request, form):
        """A restore posted: started as a job (insights.start_restore) and the page sent to follow it, or None when the
        page answers it itself (not an admin, an expired form, no such backup: _backups_posted says so)."""
        user = await threaded(site.account, request)
        if not user["is_admin"] or not hmac.compare_digest(form.get("csrf", ""), site.csrf(request)):
            return None
        try:
            job = insights.start_restore(site, user["login_id"], form.get("name", ""))
        except bak.BackupError:
            return None
        if await site.jobs.settled(job):
            # Done within a few seconds: the page says how at once.
            w = strings.words(site.language(request))
            said = insights.job_words(w, job)
            ok = job.state == "done"
            return await threaded(_backups_page, request, user, said["text"] if ok else None,
                                  None if ok else said["text"])
        return _redirect("/admin/backups?job=" + job.id)

    def _backups_page(request, user, notice, error, status=200):
        """The Backups tab with the line a form left (done or refused): the list, how many of each kind stay, and the
        upload's limit with what the page says when a chosen file passes it (site.js says it before sending). Shown at
        its own address whichever form was posted (an upload's goes elsewhere), so the language switch comes back
        here."""
        w = strings.words(site.language(request))
        # The restore the page follows (?job=): its progress card while it runs, its line once it ended.
        job = _followed(request, w)
        if job is not None and job["state"] != "running" and not (notice or error):
            notice, error = (job["text"], None) if job["state"] == "done" else (None, job["text"])
        return site.render(request, "admin_backups.html", status=status, here="/admin/backups", user=user,
                           job=job if job and job["state"] == "running" else None,
                           backups=bak.all_backups(site.data_dir), keep=bak.KEEP, notice=notice, error=error,
                           upload_most=bak.UPLOAD_MOST, upload_mb=bak.UPLOAD_MOST >> 20,
                           too_large=w.error(bak.too_large()))

    async def admin_backup_upload(request):
        """A database file the admin uploads (a backup from another server or PC): written into backups/ as it comes,
        checked, and kept as a backup of the kind "upload", to restore as any other (common._upload_backup, shared with
        the API's twin). Only an admin's form gets this far: anyone else's body is never read."""
        user = await threaded(site.account, request)
        if not user["is_admin"]:
            # A plain answer: no page made for a post nobody but an admin sends.
            return PlainTextResponse("Not Found", status_code=404)
        w = strings.words(site.language(request))
        try:
            name = await _upload_backup(site, request, user["login_id"], form=True)
        except upload.FormExpired:
            # No token, or another one, before the file: nothing was read of it.
            return await threaded(_backups_page, request, user, None, w("form.expired"))
        except bak.BackupError as e:
            # Too large, no file, not a database of this project: in the admin's language. A body too large for its
            # limit says so with its status too.
            return await threaded(_backups_page, request, user, None, w.error(e),
                                           413 if e.key == "error.backup.too_large" else 200)
        return await threaded(_backups_page, request, user, w("backups.uploaded", name=name), None)

    def admin_backup_file(request):
        """One backup's file, for the admin to keep elsewhere."""
        user = site.account(request)
        if not user["is_admin"]:
            return _not_found(site, request)
        try:
            path = bak.path_of(site.data_dir, request.path_params["name"])
        except bak.BackupError:
            return _not_found(site, request)
        return FileResponse(path, filename=request.path_params["name"], media_type="application/vnd.sqlite3")

    # The admin pages' run of the route table, in its order: after the public site's, before the API's.
    return [
        # The admin pages open at Status, what the server is doing and what may want a look (as OpenDMTQ's do).
        Route("/admin", lambda r: _redirect("/admin/status")),
        Route("/admin/players", admin_players, methods=["GET", "POST"]),
        # Beside the list, not under it: an ID is letters and digits, so no player's page is the file's.
        Route("/admin/players.csv", admin_players_file),
        Route("/admin/cabinets", admin_cabinets, methods=["GET", "POST"]),
        Route("/admin/status", admin_status, methods=["GET", "POST"]),
        Route("/admin/server", admin_server, methods=["GET", "POST"]),
        Route("/admin/song_list", admin_song_list, methods=["GET", "POST"]),
        Route("/admin/song_list/upload", admin_song_list_upload, methods=["POST"]),
        Route("/admin/log", admin_log),
        Route("/admin/log/plays", admin_log_plays),
        Route("/admin/log/plays.csv", admin_log_plays_csv),
        Route("/admin/log/requests", admin_log_requests),
        Route("/admin/log/requests.csv", admin_log_requests_csv),
        Route("/admin/jobs/{id}", admin_job),
        Route("/admin/backups", admin_backups, methods=["GET", "POST"]),
        # Before a backup's own address: "upload" is no backup's name, and a POST goes here.
        Route("/admin/backups/upload", admin_backup_upload, methods=["POST"]),
        Route("/admin/backups/{name}", admin_backup_file),
    ]
