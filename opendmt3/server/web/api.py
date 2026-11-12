"""The API (/api/v1/) that the launcher and other programs use, signed in with a token from POST /api/v1/session (or
a named token made on the Account page: services/tokens.py) and signed out with DELETE /api/v1/session (every page and
action of the site has its twin here: docs/api.md lists them for people, calls.py for programs, as the OpenAPI document
GET /api/v1/openapi.json, and tests/server/test_api.py checks both against these routes), and the open route beside it that
programs read: the launcher's update feed (/updates/). The health check is app.py's.

routes(site) gives create_app (app.py) their routes, in the order the route table has always had them;
api_unknown is how create_app answers a wrong path or method under /api/.

As on the site's pages, a call without a body to read is a plain function (Starlette runs it on a worker thread, so its
queries never run on the event loop the game server shares); one with a JSON body reads it on the loop and hands the
rest to a worker thread, and a password is made or checked through Site.hashed and the sign-in limits as everywhere.
"""

import json
import os
import re
import secrets
import stat

from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from opendmt3 import __version__
from opendmt3.server.services import accounts as acc
from opendmt3.server.services import backups as bak
from opendmt3.server.services import cards
from opendmt3.server.services import catalog as cat
from opendmt3.server.services import maintenance
from opendmt3.server.services import notice
from opendmt3.server.services import songlist, sources
from opendmt3.server.services import tokens as tok
# The worker threads a handler hands its work to, its processor time counted (work.py).
from opendmt3.server.web.work import long, threaded
from opendmt3.server.web import calls
from opendmt3.server.web import session as sess
from opendmt3.server.web import strings
# The password check and what the pages show and do too, which the API gives and takes as JSON (common.py).
from opendmt3.server.web.common import (LICENCE_FACES, _accounts_call, _allowed, _cabinets_for, _card, _check_password,
                                 _delete_backup, _dj, _dj_cards, _dj_places, _download, _installer, _known_cabinets,
                                 _licence_texts, _log, _log_change, _log_counts, _message, _mode_asked, _mode_name,
                                 _modes, _month_rankings, _new_password, _new_records, _plays_file, _plays_log,
                                 _plays_wanted, _rankings, _recent, _reset_plays, _restore, _set_maintenance,
                                 _set_notice, _song, _song_number, _songs, _songs_found, _status, _to_look_at,
                                 _upload_backup, _song_list_state, _import_song_list, _song_list_found,
                                 _upload_song_list, LICENCE_PARTS, _own_licence)
# The Status page's lines to look at, in the page's words (a line of its own here: the list above is shared work).
from opendmt3.server.web.common import _look_text

# What the launcher's update feed holds (GET /updates/{name}), by name: the feed for a channel, a package, or a
# package's signature. Letters, digits, dots, dashes, underscores and plus signs, a letter or digit first: no folder,
# no drive, no stream of a file, no space, no name that begins with a dot; 200 characters at most.
UPDATE_FILE = re.compile(r"(?=.{1,200}\Z)(?:(?P<feed>releases\.[a-z0-9]+\.json)"
                         r"|(?P<signature>[A-Za-z0-9][A-Za-z0-9._+-]*\.nupkg\.sig)"
                         r"|(?P<package>[A-Za-z0-9][A-Za-z0-9._+-]*\.nupkg))")
# Each kind's type as it is handed out: the feed is JSON, a package and a signature are bytes to keep as they are.
UPDATE_TYPES = {"feed": "application/json", "package": "application/octet-stream",
                "signature": "application/octet-stream"}

# How long an API token works (the sign-in cookie's own is SIGN_IN_DAYS, in common.py).
TOKEN_DAYS = 30
# The plays answers (GET /api/v1/plays): the newest this many, as the API has always given.
PLAYS_SHOWN = 50
# What a query's yes is (?everyone=1, ?records=true).
YES = ("1", "true", "yes")
# The methods that only read: all a read-only named token may use.
READS = ("GET", "HEAD")
# The most a JSON body sent to the song list's import may be (the route also takes files, so the site's wall leaves its
# body to it).
SMALL_BODY = 64 * 1024


# The helpers below need no Site, so they are plain functions; api_unknown uses the first.
def _error(status, code, message, headers=None):
    # headers: what an error says beside its body (a 429's Retry-After, a 405's Allow).
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status, headers=headers)


async def _json_object(request):
    """The request's JSON body as a dict, or None when it is not JSON or not an object."""
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        return None
    return body if isinstance(body, dict) else None


def _words(request):
    """The words of an answer meant for people (a message to send, a line to look at, a font's faces): English, or
    Korean with ?lang=ko, as the site shows them in either language (strings.py)."""
    return strings.words("ko" if request.query_params.get("lang") == "ko" else "en")


def _waited(held):
    """The 429 of a sign-in the limits hold back (common._check_password's why): its message, and when to try again."""
    return _error(429, "too_many_tries", held[1], headers={"Retry-After": str(held[2])})


# Here rather than in routes(): create_app's 404 and 405 handlers answer with it under /api/.
async def api_unknown(request, exc=None):
    """Under /api/ a wrong path or method answers JSON like every other API error; a wrong method's answer names the
    ones the path takes (Allow)."""
    if getattr(exc, "status_code", 404) == 405:
        return _error(405, "method_not_allowed", "this path does not take %s" % request.method, headers=_allowed(exc))
    return _error(404, "not_found", "no such API path")


def routes(site):
    """The API's routes for one Site, with the update feed. The handlers are made here as closures over the Site, as
    they were in create_app."""

    def _bearer(request):
        """The token the request carries (Authorization: Bearer ...), or ""."""
        header = request.headers.get("authorization", "")
        return header[7:] if header.lower().startswith("bearer ") else ""

    def _signed(request):
        """(the account, what signs it in, the token) for a token that works, else None. A sign-in token (POST
        /api/v1/session; what signs in is its signed values): made here, not too old, of an enabled account, from its
        current password, and not ended by a sign-out (DELETE /api/v1/session). A named token: _named."""
        token = _bearer(request)
        if token.startswith(tok.PREFIX):
            # A named token, made on the Account page: the database knows it, by a hash.
            return _named(token)
        data = site.signer.unsign(token, TOKEN_DAYS * 86400)
        if not data or data.get("kind") != "api":
            return None
        store = site.accounts()
        try:
            row = store.db.execute("SELECT * FROM accounts WHERE id = ?", (data.get("uid"),)).fetchone()
            if row is None or row["disabled"] or data.get("pw") != sess.password_mark(row["password"]):
                return None
            if store.token_ended(sess.token_id(token)):
                # Signed out with this very token: the account's other tokens go on.
                return None
        finally:
            store.db.close()
        return row, data, token

    def _named(token):
        """(the account, the named token's row with kind "named", the token) for a named token (services/tokens.py)
        the database holds, of an enabled account, else None. Its last use is noted (at most once a minute)."""
        store = site.accounts()
        try:
            tokens = tok.Tokens(store.db)
            found = tokens.check(token)
            if found is None:
                return None
            row = store.db.execute("SELECT * FROM accounts WHERE id = ?", (found["account_id"],)).fetchone()
            if row is None or row["disabled"]:
                # A disabled account's tokens stop; they work again once it is enabled.
                return None
            tokens.touch(found)
        finally:
            store.db.close()
        return row, dict(found, kind="named"), token

    def _caller(request, admin=False):
        """(the caller, None) for a working token that may make this call (an admin's for an admin's call, `admin`),
        else (None, the error to answer). The caller is the account's row as a dict, with `who` (how the change log
        names whoever made a change: the ID, and a named token's name beside it) and `admin` (whether this call may
        use the account's admin rights).

        A named token of the read scope makes GET (and HEAD) calls only, and none of an admin's: 403 read_only for
        any other, and `admin` is never true with it (an admin's part of a call, such as the cabinets' addresses,
        is left out). A sign-in token, or a named token of the write scope, has every right of its account."""
        signed = _signed(request)
        if signed is None:
            return None, _error(401, "sign_in", "sign in first (POST /api/v1/session)")
        row, data, _ = signed
        named = data.get("kind") == "named"
        read_only = named and data["scope"] != "write"
        if read_only and request.method not in READS:
            return None, _error(403, "read_only", str(tok.read_only()))
        if admin and not row["is_admin"]:
            return None, _error(403, "admin_only", "an admin account's token is needed")
        if admin and read_only:
            return None, _error(403, "read_only", str(tok.read_only()))
        caller = dict(row)
        # The change log's name for the caller: "NOVA", or "NOVA (token nightly backup)".
        caller["who"] = "%s (token %s)" % (row["login_id"], data["name"]) if named else row["login_id"]
        caller["admin"] = bool(row["is_admin"]) and not read_only
        return caller, None

    def _new_token(row):
        """A token for the account: tied to its password (a new one ends it), with an id of its own (j), so each
        sign-in's token differs from the next and a sign-out ends that one alone."""
        return site.signer.sign({"kind": "api", "uid": row["id"], "pw": sess.password_mark(row["password"]),
                                 "j": secrets.token_urlsafe(12)})

    def _me(row, card=None):
        # player: the account's number, as the rankings and GET /api/v1/djs/{player} name it. card: the card number
        # the game logs in with; dj_card: what the game shows on the DJ card (given when made for many at once).
        return {"login_id": row["login_id"], "dj_name": row["dj_name"], "card": row["card"],
                "is_admin": bool(row["is_admin"]), "player": row["id"],
                "dj_card": card if card is not None else _card(site, row)}

    # ------------------------------------------------------------------ the server, signing in and out

    def api_status(request):
        """What a launcher needs before signing in: that this is openDMT3, its version, the game's port, and whether
        it hands out the launcher's updates (/updates/)."""
        return JSONResponse({"server": "openDMT3", "version": __version__, "game_port": site.game_port,
                             "updates": os.path.isfile(os.path.join(site.updates, "releases.win.json"))})

    def update_file(request):
        """One file of the launcher's update feed (data/updates/), for the connected launchers' Velopack, which
        signs in nowhere: the feed, a package or a package's signature by its plain name (UPDATE_FILE), a file of its
        own right in that folder, with the type its kind has (UPDATE_TYPES). Anything else is not there for anyone:
        another kind of file the folder holds (a copy of the database put there by mistake), a folder, a link, a name
        that reaches above or below."""
        name = request.path_params["name"]
        kind = UPDATE_FILE.fullmatch(name)
        if kind is None:
            return Response("Not Found", status_code=404, media_type="text/plain")
        path = os.path.join(site.updates, name)
        try:
            # The file itself, never what a link at that name points to.
            regular = stat.S_ISREG(os.lstat(path).st_mode)
        except (OSError, ValueError):
            regular = False
        if not regular:
            return Response("Not Found", status_code=404, media_type="text/plain")
        # Its type from its kind, never guessed from the name by this PC's own table (a package came as text/plain),
        # and never guessed again by a browser.
        return FileResponse(path, media_type=UPDATE_TYPES[kind.lastgroup],
                            headers={"X-Content-Type-Options": "nosniff"})

    async def api_session(request):
        """POST: sign in, for the account and a token. DELETE: sign out, ending the token sent (only that one)."""
        if request.method == "DELETE":
            return await threaded(_sign_out, request)
        body = await _json_object(request)
        if body is None:
            return _error(400, "bad_request", "send JSON: {\"login_id\": ..., \"password\": ...}")
        # Checked after the body is read and right before the password, which counts as wrong until it is checked:
        # tries sent at once cannot all slip under the limit (_check_password).
        row, held = await _check_password(site, request, str(body.get("login_id", "")).strip(),
                                          str(body.get("password", "")))
        if held:
            return _waited(held)
        if row is None:
            return _error(401, "wrong_sign_in", "that ID and password do not match an account")
        # The account's card (a look at its plays) on a worker thread.
        return await threaded(lambda: JSONResponse(dict(_me(row), token=_new_token(row))))

    def _sign_out(request):
        """The token sent stops working now (the launcher's Sign out); the account's other tokens, a launcher's on
        another PC, and its sign-ins on the site go on. Its id is kept until it would have expired anyway. A named
        token is revoked as DELETE /api/v1/tokens/{id} does it (a change: not with a read-only one)."""
        signed = _signed(request)
        if signed is None:
            return _error(401, "sign_in", "sign in first (POST /api/v1/session)")
        row, data, token = signed
        if data.get("kind") == "named":
            caller, refused = _caller(request)
            if refused:
                return refused
            store = site.accounts()
            try:
                tok.Tokens(store.db).revoke(caller, data["id"], who=caller["who"])
            finally:
                store.db.close()
            return JSONResponse({"signed_out": True})
        store = site.accounts()
        try:
            store.end_token(sess.token_id(token), row["id"], int(data["t"]) + TOKEN_DAYS * 86400)
        finally:
            store.db.close()
        return JSONResponse({"signed_out": True})

    def api_openapi(request):
        """The OpenAPI document of every call (calls.py): open to anyone, as it holds no data, only what the API takes
        and gives."""
        return JSONResponse(calls.openapi(__version__))

    def api_licenses(request):
        """The Licenses page: openDMT3's own licence (its text when the server has it beside the package), the parts
        the server and what it hands out are made with, each with what it is used for and its licence, and the fonts
        the site serves, each licence with the faces it covers and its text in full. Open to anyone, as the page is."""
        w, texts = _words(request), _licence_texts()
        return JSONResponse({"own": {"name": "MIT License", "text": _own_licence()},
                             "parts": [{"part": part, "used_for": w(use), "license": w(licence)}
                                       for part, use, licence in LICENCE_PARTS],
                             "licenses": [{"name": w("licenses.ofl"), "faces": [w(face) for face in faces],
                                           "text": texts[key]} for key, faces in LICENCE_FACES]})

    # ------------------------------------------------------------------------------- your account

    def api_me(request):
        row, refused = _caller(request)
        if refused:
            return refused
        return JSONResponse(_me(row))

    async def api_me_password(request):
        """POST {"password": current, "new_password": ...}: a new password and card; the answer has a new token
        (the old ones end with the old password)."""
        row, refused = await threaded(_caller, request)
        if refused:
            return refused
        body = await _json_object(request)
        if body is None:
            return _error(400, "bad_request", "send JSON: {\"password\": ..., \"new_password\": ...}")
        # The current password is checked like a sign-in: the same limits, on a worker thread.
        checked, held = await _check_password(site, request, row["login_id"], str(body.get("password", "")))
        if held:
            return _waited(held)
        if checked is None:
            return _error(403, "wrong_password", "the current password is not right")
        try:
            await site.hashed(_accounts_call, site, "set_password", row["login_id"], str(body.get("new_password", "")),
                              who=row["who"])
        except acc.AccountError as e:
            return _error(400, "refused", str(e))

        def answer():
            # The account as it is now, its card and a new token, on a worker thread.
            fresh = _accounts_call(site, "by_login", row["login_id"])
            return JSONResponse(dict(_me(fresh), token=_new_token(fresh)))
        return await threaded(answer)

    async def api_me_dj_name(request):
        """POST {"dj_name": ...}: the name on the DJ card and the site."""
        body = await _json_object(request)
        return await threaded(_me_dj_name, request, body)

    def _me_dj_name(request, body):
        """api_me_dj_name on a worker thread, with its body read."""
        row, refused = _caller(request)
        if refused:
            return refused
        if body is None:
            return _error(400, "bad_request", "send JSON: {\"dj_name\": ...}")
        store = site.accounts()
        try:
            try:
                store.set_dj_name(row["login_id"], str(body.get("dj_name", "")).strip(), who=row["who"])
            except acc.AccountError as e:
                return _error(400, "refused", str(e))
            fresh = store.by_login(row["login_id"])
        finally:
            store.db.close()
        return JSONResponse(_me(fresh))

    async def api_me_dj_card(request):
        """POST {"icon", "plate", "pattern", "comment"} (any of them): the DJ card the game shows from the next
        login. Numbers come from GET /api/v1/dj_cards."""
        body = await _json_object(request)
        return await threaded(_me_dj_card, request, body)

    def _me_dj_card(request, body):
        """api_me_dj_card on a worker thread, with its body read."""
        row, refused = _caller(request)
        if refused:
            return refused
        if body is None:
            return _error(400, "bad_request", "send JSON: {\"icon\": ..., \"plate\": ..., \"pattern\": ..., \"comment\": ...}")
        comment = body.get("comment")
        store = site.accounts()
        try:
            try:
                store.set_card(row["login_id"], cards.load(site.data_dir), icon=body.get("icon"),
                               plate=body.get("plate"), pattern=body.get("pattern"),
                               comment=comment if comment is None else str(comment), who=row["who"])
            except cards.CardError as e:
                return _error(400, "refused", str(e))
            fresh = store.by_login(row["login_id"])
        finally:
            store.db.close()
        return JSONResponse(_me(fresh))

    async def api_tokens(request):
        """GET: the caller's named tokens, newest first (never the tokens themselves). POST {"name", "scope"}: a new
        one for the caller's account, the token itself in this answer only, as the Account page shows it once."""
        body = await _json_object(request) if request.method == "POST" else None
        return await threaded(_tokens, request, body)

    def _tokens(request, body):
        """api_tokens on a worker thread, with a POST's body read."""
        row, refused = _caller(request)
        if refused:
            return refused
        store = site.accounts()
        try:
            tokens = tok.Tokens(store.db)
            if request.method == "POST":
                if body is None:
                    return _error(400, "bad_request", "send JSON: {\"name\": ..., \"scope\": \"read\" or \"write\"}")
                try:
                    made, token = tokens.make(row, body.get("name"), body.get("scope"), who=row["who"])
                except tok.TokenError as e:
                    # A name too long or empty, a scope that is neither, too many tokens: the reason in words.
                    return _error(400, "refused", str(e))
                return JSONResponse(dict(made, token=token), status_code=201)
            return JSONResponse({"tokens": tokens.all(row["id"])})
        finally:
            store.db.close()

    def api_token(request):
        """DELETE: one of the caller's named tokens revoked for good (it may be the one calling), as the Account page's
        Revoke does."""
        row, refused = _caller(request)
        if refused:
            return refused
        token_id = request.path_params["id"]
        store = site.accounts()
        try:
            name = tok.Tokens(store.db).revoke(row, token_id, who=row["who"])
        except tok.TokenError as e:
            # Not one of the caller's: revoked already, never made, or another account's.
            return _error(404, "unknown_token", str(e))
        finally:
            store.db.close()
        return JSONResponse({"revoked": token_id, "name": name})

    def api_dj_cards(request):
        """The DJ card's choices this server has pictures for (read from the owner's game files), each with the
        grade the game gives it, and the comment's length."""
        _, refused = _caller(request)
        if refused:
            return refused
        tables = cards.load(site.data_dir)
        return JSONResponse({kind: tables.get(kind, []) for kind in cards.KINDS} | {"comment_max": cards.COMMENT_MAX})

    def api_card_picture(request):
        """A choice's picture, for programs signed in with a token (the site's own pages use /cards/)."""
        _, refused = _caller(request)
        if refused:
            return refused
        path = cards.picture(site.data_dir, request.path_params["kind"], request.path_params["number"])
        if path is None:
            return _error(404, "not_found", "no such picture")
        return FileResponse(path, media_type="image/png")

    # ------------------------------------------------------------------- records: plays, rankings, songs, DJs

    async def api_plays(request):
        """GET (and HEAD): Home's lists: the caller's newest plays, or everyone's (?everyone=1), each marked when it
        beat its player's best on the chart (NEW), with how many there are in all; or the newest records (?records=1).
        DELETE: an admin resets every play, as the Players tab's Reset every play does (the database backed up first,
        on a thread of the long work's own)."""
        if request.method == "DELETE":
            return await long(_reset_every_play, request)
        return await threaded(_plays, request)

    def _plays(request):
        """api_plays' lists on their thread."""
        row, refused = _caller(request)
        if refused:
            return refused
        if request.query_params.get("records") in YES:
            # The plays that beat their player's best on a chart, enabled players only, newest first.
            return JSONResponse({"plays": _new_records(site, PLAYS_SHOWN)})
        everyone = request.query_params.get("everyone") in YES
        plays, total = _recent(site, None if everyone else row["id"], PLAYS_SHOWN)
        return JSONResponse({"plays": plays, "total": total})

    def _reset_every_play(request):
        """DELETE /api/v1/plays: every player's plays go, the database backed up first (common._reset_plays): how
        many went and the backup that keeps them."""
        row, refused = _caller(request, admin=True)
        if refused:
            return refused
        gone, kept = _reset_plays(site, row["who"])
        return JSONResponse({"plays": gone, "kept_as": kept})

    def api_rankings(request):
        """A mode's ranking by total, by the best 30's average, or this month's (with the first three of the months
        before it), as the Rankings page shows it; Home's top DJs are its first rows by total."""
        _, refused = _caller(request)
        if refused:
            return refused
        modes = _modes(site)
        mode = _mode_asked(request.query_params.get("mode"), modes)
        if mode is None:
            return _error(400, "bad_request", "mode is a number from 0 to 255 (0 is STAR)")
        by = request.query_params.get("by", "total")
        if by not in ("total", "best30", "month"):
            return _error(400, "bad_request", "by is total, best30 or month")
        answer = {"mode": mode, "name": _mode_name(mode), "modes": modes, "by": by}
        if by == "month":
            # This calendar month on the server's clock, and each month before it that anybody played in.
            month = _month_rankings(site, mode)
            return JSONResponse(dict(answer, rows=month["rows"], start=month["start"], past=month["past"]))
        return JSONResponse(dict(answer, rows=_rankings(site, mode, by)))

    def api_songs(request):
        """Every song with what was played, or those Find leaves (?q=), and how many songs there are in all."""
        _, refused = _caller(request)
        if refused:
            return refused
        rows = _songs(site)
        return JSONResponse({"songs": _songs_found(rows, request.query_params.get("q", "").strip()),
                             "total": len(rows)})

    def api_song(request):
        _, refused = _caller(request)
        if refused:
            return refused
        number = _song_number(request)
        song = _song(site, number) if number is not None else None
        if song is None:
            return _error(404, "unknown_song", "no song with that number on this server")
        return JSONResponse(song)

    def api_jacket(request):
        """A song's picture, as the site's pages show it (/jackets/), read from the owner's own game files."""
        _, refused = _caller(request)
        if refused:
            return refused
        number = _song_number(request)
        path = cat.jacket_path(site.data_dir, number) if number is not None else None
        if path is None:
            return _error(404, "not_found", "no such picture")
        return FileResponse(path, media_type="image/png")

    def api_records(request):
        """A DJ's page: their card, numbers, best scores, recent plays, activity, and their place in each mode."""
        _, refused = _caller(request)
        if refused:
            return refused
        player = request.path_params["player"]
        dj = _dj(site, player) if player < 2 ** 63 else None
        if dj is None:
            return _error(404, "unknown_player", "no player with that number on this server")
        # Where they stand in each mode's ranking by total, as the DJ page shows it.
        return JSONResponse(dict(dj, places=_dj_places(site, dj["player"])))

    # ------------------------------------------------------------------------------------- downloads

    def api_download(request):
        """The Download page: the installer's facts (None without one), the address the launcher asks for and the
        name the installer is handed out under, both from the address this request came to."""
        _, refused = _caller(request)
        if refused:
            return refused
        return JSONResponse(_download(site, request))

    def api_installer(request):
        """The installer with this server on its end, as /download/windows hands it out."""
        _, refused = _caller(request)
        if refused:
            return refused
        answer = _installer(site, request)
        if answer is None:
            return _error(404, "no_installer", "this server has no installer to hand out")
        return answer

    # ------------------------------------------------------------------------------------ the players

    async def api_players(request):
        """GET: every account. POST: an account made, with its password (made when none is sent) and the message
        to send the player, as the admin's Players page gives them."""
        if request.method != "POST":
            return await threaded(_players_listed, request)
        row, refused = await threaded(_caller, request, True)
        if refused:
            return refused
        body = await _json_object(request)
        if body is None:
            return _error(400, "bad_request", "send JSON: {\"login_id\": ..., \"password\": ..., \"dj_name\": ...}")
        typed = body.get("password")
        # The password sent, or one the server makes when none is (as the site's form does).
        password = str(typed) if typed not in (None, "") else _new_password()
        try:
            # Hashed on a worker thread (Site.hashed), as every password is.
            made = await site.hashed(_accounts_call, site, "create", str(body.get("login_id", "")).strip().upper(),
                                     password, str(body.get("dj_name") or "") or None,
                                     is_admin=bool(body.get("is_admin")), who=row["who"])
        except acc.AccountError as e:
            return _error(400, "refused", str(e))
        # The password this once, and what the player needs, ready to send (the card made on a worker thread).
        return await threaded(lambda: JSONResponse(
            dict(_me(made), password=password,
                 message=_message(site, request, _words(request), made["login_id"], password)),
            status_code=201))

    def _players_listed(request):
        """GET /api/v1/players on a worker thread: every account with its DJ card."""
        row, refused = _caller(request, admin=True)
        if refused:
            return refused
        rows = _accounts_call(site, "all")
        # Every player's DJ card at once: one query over the plays (kept until the plays change), the tables and the
        # song list read once.
        dj_cards = _dj_cards(site, rows)
        return JSONResponse({"players": [dict(_me(r, dj_cards[r["id"]]), disabled=bool(r["disabled"]),
                                              last_login=r["last_login"]) for r in rows]})

    def _player_named(request):
        """(the admin calling, the ID the path names, None) when an admin's token names an account that is there,
        else (None, None, the error to answer), on a worker thread."""
        row, refused = _caller(request, admin=True)
        if refused:
            return None, None, refused
        login_id = request.path_params["login_id"].upper()
        if _accounts_call(site, "by_login", login_id) is None:
            return None, None, _error(404, "unknown_player", "no player with that ID on this server")
        return row, login_id, None

    def _on_player(request, change):
        """An admin's change to the account the path names, on a worker thread: an admin's token, an account with that
        ID, then change(store, login_id, admin) answers. An account rule's refusal answers 400 with its reason."""
        row, login_id, refused = _player_named(request)
        if refused:
            return refused
        store = site.accounts()
        try:
            try:
                return change(store, login_id, row)
            except acc.AccountError as e:
                return _error(400, "refused", str(e))
        finally:
            store.db.close()

    async def api_player_password(request):
        """A new password (and card) the server makes, with the message to send the player."""
        row, login_id, refused = await threaded(_player_named, request)
        if refused:
            return refused
        password = _new_password()
        try:
            await site.hashed(_accounts_call, site, "set_password", login_id, password, who=row["who"])
        except acc.AccountError as e:
            return _error(400, "refused", str(e))
        return JSONResponse({"login_id": login_id, "password": password,
                             "message": _message(site, request, _words(request), login_id, password)})

    def api_player_disabled(request):
        """POST .../disable or .../enable (the path's last word). The only enabled admin is never disabled."""
        disable = request.url.path.rsplit("/", 1)[1] == "disable"

        def change(store, login_id, admin):
            store.set_disabled(login_id, disable, who=admin["who"])
            return JSONResponse({"login_id": login_id, "disabled": disable})
        return _on_player(request, change)

    def api_player_admin(request):
        """POST: give the account admin rights; DELETE: take them. The only enabled admin keeps theirs."""
        give = request.method == "POST"

        def change(store, login_id, admin):
            store.set_admin(login_id, give, who=admin["who"])
            return JSONResponse({"login_id": login_id, "is_admin": give})
        return _on_player(request, change)

    async def api_player_dj_name(request):
        """POST {"dj_name": ...}: the player's DJ name, by the rules of their own (POST /api/v1/me/dj_name)."""
        body = await _json_object(request)

        def change(store, login_id, admin):
            if body is None:
                return _error(400, "bad_request", "send JSON: {\"dj_name\": ...}")
            name = str(body.get("dj_name", "")).strip()
            store.set_dj_name(login_id, name, who=admin["who"])
            return JSONResponse({"login_id": login_id, "dj_name": name})
        return await threaded(_on_player, request, change)

    async def api_player_plays(request):
        """DELETE: the player's plays go, the database backed up first, as the Players tab's Reset plays does; the
        account, its DJ card and its settings stay. On a thread of the long work's own (the backup copies the
        database)."""
        def change(store, login_id, admin):
            gone, kept = _reset_plays(site, admin["who"], store.by_login(login_id))
            return JSONResponse({"login_id": login_id, "plays": gone, "kept_as": kept})
        return await long(_on_player, request, change)

    def api_player_delete(request):
        """The account goes, and its plays with it; never the caller's own."""
        def change(store, login_id, admin):
            if login_id == admin["login_id"]:
                return _error(400, "refused", "an admin cannot delete their own account")
            store.delete(login_id, who=admin["who"])
            return JSONResponse({"deleted": login_id})
        return _on_player(request, change)

    # ----------------------------------------------------------------- cabinets, status, notice, logs

    def api_cabinets(request):
        row, refused = _caller(request)
        if refused:
            return refused
        if request.query_params.get("all") == "1":
            # Every cabinet seen: the admin's Cabinets tab (an admin's call, so a read-only token is refused it too).
            if not row["is_admin"]:
                return _error(403, "admin_only", "an admin account's token is needed")
            if not row["admin"]:
                return _error(403, "read_only", str(tok.read_only()))
            return JSONResponse({"cabinets": _known_cabinets(site)})
        # A player gets who plays on each; an admin the addresses and login IDs too (Home's cabinets), unless the
        # token is read-only.
        return JSONResponse({"cabinets": _cabinets_for(site, dict(row, is_admin=row["admin"]))})

    async def api_cabinet_name(request):
        """POST {"name": ...}: the name the admin pages show for a cabinet (empty: its address again)."""
        body = await _json_object(request)
        return await threaded(_cabinet_named, request, body)

    def _cabinet_named(request, body):
        """api_cabinet_name on a worker thread, with its body read."""
        row, refused = _caller(request, admin=True)
        if refused:
            return refused
        if body is None:
            return _error(400, "bad_request", "send JSON: {\"name\": ...}")
        activity = site.activity()
        try:
            done = activity.rename_cabinet(request.path_params["id"], str(body.get("name") or ""))
        finally:
            activity.db.close()
        if not done:
            return _error(404, "unknown_cabinet", "no cabinet with that number on this server")
        _log_change(site, row["who"], "named cabinet %s %r" % (request.path_params["id"], body.get("name")))
        return JSONResponse({"cabinets": _known_cabinets(site)})

    def api_server(request):
        """The admin's Status tab as JSON: the numbers, what may want a look (each line only while it is so), and the
        song list's state (its Song list card)."""
        row, refused = _caller(request, admin=True)
        if refused:
            return refused
        w = _words(request)
        # Each line with the words the page shows for it, beside its key and values.
        look = [dict(item, text=_look_text(w, item)) for item in _to_look_at(site, row)]
        return JSONResponse(dict(_status(site), look=look, song_list=_song_list_state(site)))

    async def api_song_list(request):
        """GET: the Song list tab (its twin): the song list's state as GET /api/v1/server gives it, the game's files
        found on the server PC with their lines, the places looked in, and whether this server shows its PC's other
        folders. POST: import the song list, as the tab does: with no body from the game folder the server was given
        (--game; in Docker, GAME_DIR: the Status page's old Read again), with a JSON body {"path"} from that path on
        the server PC (a game folder, an archive holding one, or a song list), or with a song list as the body
        (application/zip: the tab's upload). Answers the song list's state and the reading's own lines."""
        row, refused = await threaded(_caller, request, True)
        if refused:
            return refused
        if request.method == "GET":
            found = await long(_song_list_found, site)
            for item in found["found"]:
                # Each one's line in the words asked for (?lang=ko), beside the English one.
                item["text"] = sources.said(item, "ko" if request.query_params.get("lang") == "ko" else "en")
            return await threaded(lambda: JSONResponse(dict(found, song_list=_song_list_state(site))))
        kind = request.headers.get("content-type", "").split(";")[0].strip().lower()
        try:
            if kind == "application/json":
                body = await _small_json(request)
                if body is None or not isinstance(body.get("path"), str) or not body["path"].strip():
                    return _error(400, "bad_request", 'send JSON: {"path": a folder or file on the server PC}')
                report, failed = await _import_song_list(site, row["who"], path=body["path"].strip())
            elif _has_body(request):
                report, failed = await _upload_song_list(site, request, row["who"])
            else:
                if not site.game_folder:
                    # No folder to read: the tab offers the other ways.
                    return _error(404, "no_game_folder", "the server was not given client data to read (GAME_DIR, "
                                                         "--game); send a path or a song list, or run ./dmt3 catalog "
                                                         "PATH on the server PC")
                report, failed = await _import_song_list(site, row["who"])
        except songlist.SongListError as e:
            # Past the limit: 413, as HTTP says it; no file: 400 with the reason.
            if e.key == "error.songlist.too_large":
                return _error(413, "too_large", str(e))
            return _error(400, "refused", str(e))
        if failed:
            # busy (409), refused (400, the path's or the file's own line) or not_read (409).
            return _error(400 if failed[0] == "refused" else 409, failed[0], failed[1])
        return await threaded(lambda: JSONResponse({"song_list": _song_list_state(site),
                                                             "lines": [text for _, text in cat.lines(report)]}))

    async def api_folders(request):
        """The Song list tab's folder browser: a folder of the server PC (?path=, the top when not given) and the
        folders in it."""
        row, refused = await threaded(_caller, request, True)
        if refused:
            return refused
        try:
            listed = await threaded(sources.folders, request.query_params.get("path") or "/")
        except sources.SourceError as e:
            return _error(400, "refused", str(e))
        return JSONResponse(listed)

    async def _small_json(request):
        """A JSON object sent in a body of at most a form's size (this route's wall is its own: it also takes files),
        or None."""
        data = bytearray()
        async for chunk in request.stream():
            data += chunk
            if len(data) > SMALL_BODY:
                return None
        try:
            body = json.loads(bytes(data).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return body if isinstance(body, dict) else None

    def _has_body(request):
        """True when the request says it brings a body (a length above 0, or one sent in pieces)."""
        length = request.headers.get("content-length")
        if length is not None:
            return length.strip() not in ("", "0")
        return "chunked" in request.headers.get("transfer-encoding", "").lower()

    def _notice_for(row):
        """The notice as an account sees it: its line and since when; who set it (a login ID) for admins only."""
        kept = notice.read(site.data_dir)
        if kept is None:
            return {"notice": None}
        shown = {"text": kept["text"], "at": kept.get("at")}
        if row["admin"]:
            shown["by"] = kept.get("by")
        return {"notice": shown}

    async def api_notice(request):
        """GET (and HEAD): the notice every page shows at its top. POST {"text": ...}: an admin sets it (an empty text
        clears it); DELETE: an admin clears it."""
        body = await _json_object(request) if request.method == "POST" else None
        return await threaded(_notice, request, body)

    def _notice(request, body):
        """api_notice on a worker thread, with a POST's body read."""
        # Only POST and DELETE change it: a HEAD, which Starlette lets through with GET, reads like GET.
        reading = request.method in ("GET", "HEAD")
        row, refused = _caller(request, admin=not reading)
        if refused:
            return refused
        if reading:
            return JSONResponse(_notice_for(row))
        text = ""
        if request.method == "POST":
            if body is None or not isinstance(body.get("text"), str):
                return _error(400, "bad_request", "send JSON: {\"text\": ...}")
            text = body["text"]
        try:
            # Written and logged as the Status page does it.
            _set_notice(site, row["who"], text)
        except notice.NoticeError as e:
            return _error(400, "refused", str(e))
        return JSONResponse(_notice_for(row))

    def _maintenance_for(row):
        """Maintenance as an account sees it: {"on": false}, or {"on": true, "at"} with who turned it on (a login ID)
        for an admin's rights only, as the notice's `by`."""
        state = maintenance.read(site.data_dir)
        if state is None:
            return {"on": False}
        shown = {"on": True, "at": state["at"]}
        if row["admin"]:
            shown["by"] = state["by"]
        return shown

    def api_maintenance(request):
        """GET (and HEAD): whether the server is in maintenance (the line beside the notice on every page). POST: an
        admin turns it on (the game server refuses card logins); DELETE: an admin turns it off. Written and logged as
        the Status page does it."""
        # Only POST and DELETE change it: a HEAD, which Starlette lets through with GET, reads like GET.
        reading = request.method in READS
        row, refused = _caller(request, admin=not reading)
        if refused:
            return refused
        if not reading:
            _set_maintenance(site, row["who"], request.method == "POST")
        return JSONResponse(_maintenance_for(row))

    def api_log(request):
        """The admin's Log tab as JSON: changes and received messages, newest first, and how many there are."""
        _, refused = _caller(request, admin=True)
        if refused:
            return refused
        return JSONResponse(dict(_log(site), counts=_log_counts(site)))

    def _log_wanted(request):
        """(the plays log's filter, None), or (None, the error) when a value given cannot be read: the page leaves
        such a value out, a program is told."""
        wanted = _plays_wanted(request.query_params)
        if wanted["unread"]:
            return None, _error(400, "bad_request", "player is an account number, days is 1, 7 or 30, and page is a "
                                                    "number from 1 (not read: %s)" % ", ".join(wanted["unread"]))
        return wanted, None

    def api_log_plays(request):
        """The Logs tab's plays: every play the filter leaves, a page of 50, with what it leaves counted."""
        _, refused = _caller(request, admin=True)
        if refused:
            return refused
        wanted, refused = _log_wanted(request)
        if refused:
            return refused
        return JSONResponse(dict(_plays_log(site, wanted), page=wanted["page"]))

    def api_log_plays_csv(request):
        """Every play the filter leaves, as the Logs tab's CSV file."""
        _, refused = _caller(request, admin=True)
        if refused:
            return refused
        wanted, refused = _log_wanted(request)
        if refused:
            return refused
        return _plays_file(site, wanted)

    # ------------------------------------------------------------------------------------- backups

    async def api_backups(request):
        """GET: every backup; POST: back up now (on a thread of the long work's own: it copies the database)."""
        return await (long if request.method == "POST" else threaded)(_backups, request)

    def _backups(request):
        """api_backups on its thread."""
        row, refused = _caller(request, admin=True)
        if refused:
            return refused
        if request.method == "POST":
            name = bak.make(site.db_path, site.data_dir, "manual")
            _log_change(site, row["who"], "backed up the database as %s" % name)
            return JSONResponse({"made": name}, status_code=201)
        return JSONResponse({"backups": bak.all_backups(site.data_dir), "keep": bak.KEEP})

    def _backup_refused(e):
        """A backup's BackupError as an answer: no such backup (404), or one this server cannot put back (400)."""
        if e.key == "error.backup.unknown":
            return _error(404, "unknown_backup", str(e))
        return _error(400, "refused", str(e))

    def api_backup(request):
        """GET (and HEAD): the backup's file; DELETE: the backup goes. Only the restore route restores: any other
        method here reads or deletes, never puts the database back."""
        row, refused = _caller(request, admin=True)
        if refused:
            return refused
        name = request.path_params["name"]
        try:
            if request.method == "DELETE":
                # Only a backup's own name (backups.path_of), deleted and logged as the Backups tab does it.
                _delete_backup(site, row["who"], name)
                return JSONResponse({"deleted": name})
            return FileResponse(bak.path_of(site.data_dir, name), filename=name, media_type="application/vnd.sqlite3")
        except bak.BackupError as e:
            return _backup_refused(e)

    async def api_backup_upload(request):
        """POST .../upload: the request's body is a database file (from another server or PC), kept as a backup of the
        kind "upload" once it passes the checks, to restore as any other (common._upload_backup, shared with the
        Backups tab). The body is read only for an admin's token, and only up to the limit."""
        row, refused = await threaded(_caller, request, True)
        if refused:
            return refused
        try:
            name = await _upload_backup(site, request, row["who"])
        except bak.BackupError as e:
            # Past the limit: 413, as HTTP says it; a file refused by the checks, or none: 400 with the reason.
            if e.key == "error.backup.too_large":
                return _error(413, "too_large", str(e))
            return _error(400, "refused", str(e))
        return JSONResponse({"uploaded": name}, status_code=201)

    async def api_backup_restore(request):
        """POST .../restore: put the database back to the backup (the database as it is backed up first; the game
        server's writes wait meanwhile: common._restore), on a thread of the long work's own."""
        return await long(_backup_restored, request)

    def _backup_restored(request):
        """api_backup_restore on its thread."""
        row, refused = _caller(request, admin=True)
        if refused:
            return refused
        name = request.path_params["name"]
        try:
            safety = _restore(site, name)
        except bak.BackupError as e:
            return _backup_refused(e)
        _log_change(site, row["who"], "restored the database from %s" % name)
        return JSONResponse({"restored": name, "kept_as": safety})

    # The route table's last run before the static files, in its order: the launcher's status and update feed, then
    # the rest of the API (the new twins after the routes they join). Each path is one route, with every method it
    # takes, so a wrong method's 405 names them all (Allow).
    return [
        Route("/api/v1/status", api_status),
        Route("/api/v1/openapi.json", api_openapi),
        Route("/updates/{name}", update_file),
        Route("/api/v1/session", api_session, methods=["POST", "DELETE"]),
        Route("/api/v1/licenses", api_licenses),
        Route("/api/v1/backups", api_backups, methods=["GET", "POST"]),
        # Before a backup's own address: "upload" is no backup's name.
        Route("/api/v1/backups/upload", api_backup_upload, methods=["POST"]),
        Route("/api/v1/backups/{name}", api_backup, methods=["GET", "DELETE"]),
        Route("/api/v1/backups/{name}/restore", api_backup_restore, methods=["POST"]),
        Route("/api/v1/me", api_me),
        Route("/api/v1/me/password", api_me_password, methods=["POST"]),
        Route("/api/v1/me/dj_name", api_me_dj_name, methods=["POST"]),
        Route("/api/v1/me/dj_card", api_me_dj_card, methods=["POST"]),
        Route("/api/v1/tokens", api_tokens, methods=["GET", "POST"]),
        Route("/api/v1/tokens/{id}", api_token, methods=["DELETE"]),
        Route("/api/v1/dj_cards", api_dj_cards),
        Route("/api/v1/dj_cards/{kind}/{number:int}.png", api_card_picture),
        Route("/api/v1/players", api_players, methods=["GET", "POST"]),
        Route("/api/v1/cabinets", api_cabinets),
        Route("/api/v1/cabinets/{id:int}/name", api_cabinet_name, methods=["POST"]),
        Route("/api/v1/server", api_server),
        Route("/api/v1/server/song_list", api_song_list, methods=["GET", "POST"]),
        Route("/api/v1/server/folders", api_folders),
        Route("/api/v1/notice", api_notice, methods=["GET", "POST", "DELETE"]),
        Route("/api/v1/maintenance", api_maintenance, methods=["GET", "POST", "DELETE"]),
        Route("/api/v1/log", api_log),
        Route("/api/v1/log/plays", api_log_plays),
        Route("/api/v1/log/plays.csv", api_log_plays_csv),
        Route("/api/v1/plays", api_plays, methods=["GET", "DELETE"]),
        Route("/api/v1/rankings", api_rankings),
        Route("/api/v1/songs", api_songs),
        Route("/api/v1/songs/{number:int}", api_song),
        Route("/api/v1/songs/{number:int}/jacket.png", api_jacket),
        Route("/api/v1/djs/{player:int}", api_records),
        Route("/api/v1/download", api_download),
        Route("/api/v1/download/windows", api_installer),
        Route("/api/v1/players/{login_id}/password", api_player_password, methods=["POST"]),
        Route("/api/v1/players/{login_id}/disable", api_player_disabled, methods=["POST"]),
        Route("/api/v1/players/{login_id}/enable", api_player_disabled, methods=["POST"]),
        Route("/api/v1/players/{login_id}/admin", api_player_admin, methods=["POST", "DELETE"]),
        Route("/api/v1/players/{login_id}/dj_name", api_player_dj_name, methods=["POST"]),
        Route("/api/v1/players/{login_id}/plays", api_player_plays, methods=["DELETE"]),
        Route("/api/v1/players/{login_id}", api_player_delete, methods=["DELETE"]),
    ]
