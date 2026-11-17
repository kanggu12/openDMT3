"""The admin's page of one player (/admin/players/{login_id}: their state in the game and on the site, and every
control an admin has of them), and the players' own pictures: kept from an upload on the Account page, served to
whoever is signed in.

routes(site) gives create_app (app.py) their routes; the Players list links each player to their page.

As everywhere on the site, a handler without a body is a plain function (Starlette runs it on a worker thread), and one
with a form reads it on the loop and hands the rest to a worker thread.
"""

import hmac
import io

from starlette.responses import FileResponse, PlainTextResponse
from starlette.routing import Route

from opendmt3.server.services import accounts as acc
from opendmt3.server.services import cards
from opendmt3.server.services import pictures
from opendmt3.server.services import players as pl
from opendmt3.server.web import control, strings, upload
from opendmt3.server.web.common import (_accounts_call, _message, _message_local, _new_password, _not_found,
                                        _redirect, _reset_plays, not_found)
# The worker threads a handler hands its work to, its processor time counted (work.py).
from opendmt3.server.web.work import long, threaded

# The routes a picture is uploaded to (app.py UPLOADS): their bodies are read and counted here, not by the site's wall.
PICTURE_UPLOADS = ("/account/picture", "/api/v1/me/picture")


def keep_picture(site, user, data):
    """A picture of the signed-in player's own (`user`, their row), made into the site's own form and kept, on a worker
    thread (the Account page and its API twin). PlayerError when it is no picture the site takes."""
    if not pictures.available():
        # Without Pillow nothing can be made safe to serve: no upload is taken.
        raise pl.PlayerError("not a picture", "error.player.picture.kind")
    png = pl.make_picture(data)
    pl.save_picture(site.data_dir, user["id"], png)
    connection = site.connect()
    try:
        pl.Players(connection).set_picture(user["login_id"], who=user["login_id"])
    finally:
        connection.close()


def clear_picture(site, user):
    """The signed-in player's picture taken away, on a worker thread."""
    connection = site.connect()
    try:
        pl.Players(connection).clear_picture(user["login_id"], site.data_dir, who=user["login_id"])
    finally:
        connection.close()


def routes(site):
    """The player's page, the pictures and their upload, for one Site."""

    async def admin_player(request):
        """One player's page: GET shows it, POST makes one change (asked first in the site's own dialog where it cannot
        be taken back) and shows the page again with what happened."""
        w = strings.words(site.language(request))
        form = await request.form() if request.method == "POST" else None
        user = await threaded(site.account, request)
        if not user["is_admin"]:
            return await not_found(site, request)
        login_id = request.path_params["login_id"].upper()
        notice, error, message = None, None, None
        if form is not None:
            if not hmac.compare_digest(form.get("csrf", ""), site.csrf(request)):
                error = w("form.expired")
            else:
                action = form.get("action", "")
                try:
                    if action == "password":
                        # A password the server makes, shown once with the message to send (as the Players list does).
                        password = _new_password()
                        await site.hashed(_accounts_call, site, "set_password", login_id, password,
                                          who=user["login_id"])
                        notice = w("admin.newpass.done", login_id=login_id, password=password)
                        message = _message(site, request, w, login_id, password)
                    elif action == "reset_plays":
                        # The player's plays reset, the database backed up first, on a thread of the long work's own.
                        notice = await long(_reset, w, user, login_id)
                    else:
                        notice, back = await threaded(_change, w, user, login_id, action, dict(form))
                        if back:
                            return _redirect(back)
                except (pl.PlayerError, acc.AccountError, cards.CardError) as e:
                    error = w.error(e)
        return await threaded(_shown, request, user, login_id, notice, error, message)

    def _reset(w, user, login_id):
        row = _accounts_call(site, "by_login", login_id)
        if row is None:
            raise pl.PlayerError("no player with the ID %s" % login_id, "error.player.unknown", login_id=login_id)
        gone, kept = _reset_plays(site, user["login_id"], row)
        return w("admin.reset.done", login_id=login_id, n=gone, backup=kept)

    def _change(w, user, login_id, action, form):
        """A change that makes no password, on a worker thread: (the notice, a page to go to instead)."""
        store = site.accounts()
        try:
            if store.by_login(login_id) is None:
                raise pl.PlayerError("no player with the ID %s" % login_id, "error.player.unknown", login_id=login_id)
            if action == "rename":
                name = form.get("dj_name", "").strip()
                store.set_dj_name(login_id, name, who=user["login_id"])
                return w("admin.renamed", login_id=login_id, dj=name), None
            if action in ("admin_on", "admin_off"):
                store.set_admin(login_id, action == "admin_on", who=user["login_id"])
                if login_id == user["login_id"] and action == "admin_off":
                    # Their own rights taken: the admin pages are not theirs any more.
                    return None, "/"
                return w("admin.rights." + ("given" if action == "admin_on" else "taken"), login_id=login_id), None
            if action in ("disable", "enable"):
                store.set_disabled(login_id, action == "disable", who=user["login_id"])
                return w("player.done." + action), None
            if action == "delete":
                if login_id == user["login_id"]:
                    raise pl.PlayerError("there is no change named %s" % action, "error.player.action", action=action)
                store.delete(login_id, who=user["login_id"])
                # Nothing left to show: back to the list.
                return None, "/admin/players"
        finally:
            store.db.close()
        key, values = control.change(site, user["login_id"], login_id, action, form)
        return w(key, **values), None

    def _shown(request, user, login_id, notice, error, message):
        """The page itself, on a worker thread (a page that does not exist for an ID no account has)."""
        player = control.state(site, login_id)
        if player is None:
            return _not_found(site, request)
        # Each change in the reader's language, as the Logs tab words it.
        language = site.language(request)
        for line in player["history"]:
            line["said"] = strings.changed(language, line["what"])
        return site.render(request, "admin_player.html", user=user, p=player, notice=notice, error=error,
                           message=message, message_local=_message_local(site, request) if message else None,
                           choices=cards.load(site.data_dir), comment_max=cards.COMMENT_MAX, dj_max=acc.DJ_NAME_MAX,
                           points_most=pl.POINTS_MOST, reason_max=pl.REASON_MAX)

    def player_picture(request):
        """A player's picture (the site's own, the game shows none): to whoever is signed in, kept a day by the browser
        (its address carries its count, so a new picture is a new address)."""
        path = control.picture_file(site, request.path_params["player"])
        if path is None:
            # A picture that is not there: a plain answer, never a page made for it (pictures are not counted).
            return PlainTextResponse("Not Found", status_code=404)
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})

    async def account_picture(request):
        """The Account page's picture form: a new picture (read as it comes, at most PICTURE_UPLOAD_MOST bytes, made
        into the site's own square PNG) or, with action=clear, none. Back to the page with what happened."""
        user = await threaded(site.account, request)
        if upload.declared_too_large(request, pl.PICTURE_UPLOAD_MOST + upload.FORM_ROOM):
            return _redirect("/account?picture=size#profile")
        if request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
            # The remove button's small form (no file), read as it comes up to a form's room (never whole, as
            # Starlette's form() reads it): a body past it is answered as a picture too large is.
            form = await upload.small_form(request)
            if form is None:
                return _redirect("/account?picture=size#profile")
            if not hmac.compare_digest(form.get("csrf", ""), site.csrf(request)):
                return _redirect("/account?picture=expired#profile")
            await threaded(clear_picture, site, user)
            return _redirect("/account?done=picture_clear#profile")
        data = io.BytesIO()
        try:
            size = await upload.form_to(request, data, pl.PICTURE_UPLOAD_MOST, site.csrf(request),
                                        too_large=pl.picture_too_large)
        except upload.FormExpired:
            return _redirect("/account?picture=expired#profile")
        except (upload.Malformed, pl.PlayerError):
            return _redirect("/account?picture=size#profile")
        if not size:
            return _redirect("/account?picture=kind#profile")
        try:
            await threaded(keep_picture, site, user, data.getvalue())
        except pl.PlayerError as e:
            return _redirect("/account?picture=%s#profile" % e.key.rsplit(".", 1)[1])
        return _redirect("/account?done=picture#profile")

    return [
        Route("/admin/players/{login_id}", admin_player, methods=["GET", "POST"]),
        Route("/pictures/{player:int}.png", player_picture),
        Route("/account/picture", account_picture, methods=["POST"]),
    ]
