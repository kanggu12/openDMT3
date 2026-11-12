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

from starlette.responses import FileResponse, PlainTextResponse
from starlette.routing import Route

from opendmt3.server.services import accounts as acc
from opendmt3.server.services import backups as bak
from opendmt3.server.services import maintenance, notice, songlist, sources
# The worker threads a handler hands its work to, its processor time counted (work.py).
from opendmt3.server.web.work import long, threaded
from opendmt3.server.web import strings, upload
# What the API's twins of these pages show and do too, the error page and a redirect (common.py).
from opendmt3.server.web.common import (LOG_DAYS, _accounts_call, _restore, _delete_backup, _known_cabinets, _log, _log_change,
                                 _log_counts, _message, _new_password, _not_found, _plays_file, _plays_log, _plays_wanted,
                                 _redirect, _reset_plays, _set_maintenance, _set_notice, _status, _to_look_at,
                                 _upload_backup, not_found, _song_list_state, _import_song_list, _song_list_found,
                                 _upload_song_list, _look_text, _message_local)


def routes(site):
    """The admin pages' routes for one Site. The handlers are made here as closures over the Site, as they were in
    create_app."""

    async def admin_players(request):
        w = strings.words(site.language(request))
        form = await request.form() if request.method == "POST" else None
        user = await threaded(site.account, request)
        if not user["is_admin"]:
            return await not_found(site, request)
        notice, error, message = None, None, None
        if form is not None:
            if not hmac.compare_digest(form.get("csrf", ""), site.csrf(request)):
                error = w("form.expired")
            else:
                action, login_id = form.get("action"), form.get("login_id", "").strip().upper()
                try:
                    if action == "make":
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
                except acc.AccountError as e:
                    error = w.error(e)
        return await threaded(_players_shown, request, user, notice, error, message)

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

    def _players_shown(request, user, notice, error, message):
        """The Players page itself, on a worker thread."""
        rows = _accounts_call(site, "all")
        # With a message whose address only this PC reaches, the page says which address to send in its place.
        return site.render(request, "admin_players.html", user=user, rows=rows, notice=notice, error=error,
                           message=message, message_local=_message_local(site, request) if message else None,
                           dj_max=acc.DJ_NAME_MAX)

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
        return site.render(request, "admin_cabinets.html", user=user, cabinets=_known_cabinets(site), notice=notice,
                           error=error)

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
                           maintenance=maintenance.read(site.data_dir))

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
                # A path from the list found, from the folder browser or typed (empty: the game folder given).
                path = form.get("path", "").strip() or None
                done, error = _imported(w, *(await _import_song_list(site, user["login_id"], path=path)))
        return await _song_list_page(request, user, done, error)

    async def _song_list_page(request, user, done, error, status=200):
        """The Song list tab with the line a form left: what is found is looked for on a worker thread (each look is
        kept a little while: sources.found), and the browser's folder from ?browse= (outside Docker)."""
        w = strings.words(site.language(request))
        found = await long(_song_list_found, site)
        for item in found["found"]:
            # Each one's line in the page's language.
            item["said"] = sources.said(item, site.language(request))
        browsing = None
        if found["browse"]:
            asked = request.query_params.get("browse") or (found["places"][0] if found["places"] else "/")
            try:
                browsing = await threaded(sources.folders, asked)
            except sources.SourceError as e:
                error = error or w.error(e)
                browsing = await threaded(sources.folders, "/")
            # The folders in it with their whole paths, and the path's own folders as steps to click back to.
            browsing["links"] = [(name, os.path.join(browsing["path"], name)) for name in browsing["folders"]]
            browsing["crumbs"] = _crumbs(browsing["path"])
        return await threaded(lambda: site.render(
            request, "admin_song_list.html", status=status, here="/admin/song_list", user=user,
            data=_song_list_state(site, w), found=found, browsing=browsing, notice=done, error=error,
            upload_most=songlist.MOST, upload_mb=songlist.MOST >> 20, too_large=w.error(songlist.too_large()),
            quote=quote, command="./dmt3 catalog PATH"))

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
            report, refused = await _upload_song_list(site, request, user["login_id"], form=True)
        except upload.FormExpired:
            # No token, or another one, before the file: nothing was read of it.
            return await _song_list_page(request, user, None, w("form.expired"))
        except songlist.SongListError as e:
            # Too large, or no file: in the admin's language; a body too large says so with its status too.
            return await _song_list_page(request, user, None, w.error(e),
                                         413 if e.key == "error.songlist.too_large" else 200)
        done, error = _imported(w, report, refused)
        return await _song_list_page(request, user, done, error)

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

    def admin_log_plays_csv(request):
        """Every play the log's filter leaves, as a CSV file (common._plays_file, shared with the API's twin)."""
        user = site.account(request)
        if not user["is_admin"]:
            return _not_found(site, request)
        return _plays_file(site, _plays_wanted(request.query_params))

    async def admin_backups(request):
        """Backups of the database: one a day while the server runs (the week's kept), one now, download, restore,
        delete; an upload is posted to its own route (admin_backup_upload) and comes back to this page."""
        form = await request.form() if request.method == "POST" else None
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
                        name = form.get("name", "")
                        # The game server's writes wait meanwhile (common._restore): none falls between the two.
                        safety = _restore(site, name)
                        _log_change(site, user["login_id"], "restored the database from %s" % name)
                        notice = w("backups.restored", name=name, safety=safety)
                    elif form.get("action") == "delete":
                        # Only a backup's own name (path_of refuses any other), asked first on the page; deleted and
                        # logged as the API's twin does it.
                        name = form.get("name", "")
                        _delete_backup(site, user["login_id"], name)
                        notice = w("backups.deleted", name=name)
                except bak.BackupError as e:
                    error = w.error(e)
        return _backups_page(request, user, notice, error)

    def _backups_page(request, user, notice, error, status=200):
        """The Backups tab with the line a form left (done or refused): the list, how many of each kind stay, and the
        upload's limit with what the page says when a chosen file passes it (site.js says it before sending). Shown at
        its own address whichever form was posted (an upload's goes elsewhere), so the language switch comes back
        here."""
        w = strings.words(site.language(request))
        return site.render(request, "admin_backups.html", status=status, here="/admin/backups", user=user,
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
        Route("/admin", lambda r: _redirect("/admin/players")),
        Route("/admin/players", admin_players, methods=["GET", "POST"]),
        Route("/admin/cabinets", admin_cabinets, methods=["GET", "POST"]),
        Route("/admin/status", admin_status, methods=["GET", "POST"]),
        Route("/admin/song_list", admin_song_list, methods=["GET", "POST"]),
        Route("/admin/song_list/upload", admin_song_list_upload, methods=["POST"]),
        Route("/admin/log", admin_log),
        Route("/admin/log/plays", admin_log_plays),
        Route("/admin/log/plays.csv", admin_log_plays_csv),
        Route("/admin/backups", admin_backups, methods=["GET", "POST"]),
        # Before a backup's own address: "upload" is no backup's name, and a POST goes here.
        Route("/admin/backups/upload", admin_backup_upload, methods=["POST"]),
        Route("/admin/backups/{name}", admin_backup_file),
    ]
