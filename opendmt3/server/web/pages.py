"""The public site: signing in and out, the owner's first account, the language, Home, the rankings, the songs and
a song's charts, the DJ pages, the player's own account, the Download page and the Licenses page, with the files these
pages hand out (a song's picture, the DJ card's pictures, the installer with this server on its end, the site's icon,
robots.txt).

routes(site) gives create_app (app.py) their routes, in the order the route table has always had them.

A handler that reads nothing from the request's body is a plain function: Starlette runs it on a worker thread, so its
queries and its page never run on the event loop the game server shares. One that does (a form, a password check)
reads the body on the loop and hands the rest to a worker thread (work.threaded).
"""

import hmac
import logging
import os
import secrets

from starlette.responses import FileResponse, PlainTextResponse
from starlette.routing import Route

from opendmt3.server.services import accounts as acc
from opendmt3.server.services import cards
from opendmt3.server.services import catalog as cat
from opendmt3.server.services import records as rec
from opendmt3.server.services import tokens as tok
# The worker threads a handler hands its work to, its processor time counted (work.py).
from opendmt3.server.web.work import threaded
from opendmt3.server.web import session as sess
from opendmt3.server.web import strings
# The cookies' names and the helpers the admin pages and the API use too (common.py).
from opendmt3.server.web.common import (COOKIE, DB_ERRORS, LANG_COOKIE, LICENCE_FACES, MADE_COOKIE, OWNER_COOKIE,
                                 SIGN_IN_DAYS,
                                 SIGNIN_COOKIE, _accounts_call, _cabinets_for, _card, _check_password, _dj, _dj_places,
                                 _download, _installer, _licence_texts, _local, _local_path, _mode_asked, _mode_name,
                                 _modes, _month_name, _month_rankings, _new_records, _not_found, _rankings, _recent,
                                 _redirect, _song, _song_number, _songs, _songs_found, LICENCE_PARTS, _own_licence)

HERE = os.path.dirname(os.path.abspath(__file__))
log = logging.getLogger("opendmt3.web")
# Home's lists: the newest plays of each list, and the newest records.
RECENT_SHOWN = 15
RECORDS_SHOWN = 10
# Home's top DJs: the first this many of the first mode's ranking by total.
TOP_SHOWN = 5
# A ranking's table and a chart's board: the first this many rows.
RANKING_SHOWN = 100
# A DJ page's best scores: the first this many.
BESTS_SHOWN = 20


def _number(text):
    """A form's number as an int; anything else as it came (the card's check refuses it), None when absent."""
    if text is None or text == "":
        return None
    return int(text) if text.isdigit() and len(text) < 12 else text


def routes(site):
    """The public site's routes for one Site. The handlers are made here as closures over the Site, as they were in
    create_app; _number above needs no Site, so it is a plain function."""

    def _signin_page(request, target, status=200, error=None, login_id=""):
        """The sign-in page. Its form carries a token kept in a cookie of its own (strict: only this site's own
        pages send it), so a page of another site cannot sign a visitor in to an account of its choosing. After a
        try that failed, the ID typed stays in its box (never the password)."""
        token = request.cookies.get(SIGNIN_COOKIE) or secrets.token_urlsafe(24)
        # The owner's account made a moment ago on the first-run page (its cookie, read once): the page says so and
        # has the ID typed, so what is left is the password.
        made = _made_id(request.cookies.get(MADE_COOKIE)) if not error else None
        response = site.render(request, "signin.html", status=status, user=None, target=target, error=error,
                               signin_token=token, login_id=login_id or made or "", made=made)
        response.set_cookie(SIGNIN_COOKIE, token, max_age=3600, httponly=True, samesite="strict",
                            secure=request.url.scheme == "https")
        if MADE_COOKIE in request.cookies:
            # Said once.
            response.delete_cookie(MADE_COOKIE)
        return response

    def _made_id(text):
        """The ID in the first-run page's cookie when it reads as one (letters and digits, the accounts' length);
        anything else is not shown: the cookie comes back from a browser."""
        return text if text and acc.ID_PATTERN.match(text) else None

    def _no_account():
        """True while the server has no account yet (the owner's first-run page comes first), on a worker thread."""
        return not _accounts_call(site, "has_any")

    async def signin(request):
        w = strings.words(site.language(request))
        # Only paths on this site, never another address someone put in a link.
        target = _local_path(request.query_params.get("next"))
        # The form read first, on the loop (it comes over the network); everything else on worker threads.
        form = await request.form() if request.method == "POST" else None
        try:
            empty = await threaded(_no_account)
        except DB_ERRORS:
            # No account can be checked: the page says so (503), the ID typed stays, the reason goes to the log.
            log.exception("the sign-in page could not read the accounts")
            typed = form.get("login_id", "").strip() if form is not None else ""
            return await threaded(_signin_page, request, target, 503, w("signin.down"), typed)
        if empty and _local(request):
            return _redirect("/owner")
        if form is None:
            return await threaded(_signin_page, request, target)
        login_id = form.get("login_id", "").strip()
        token = request.cookies.get(SIGNIN_COOKIE, "")
        if not token or not hmac.compare_digest(form.get("csrf", ""), token):
            # Not posted from this site's own sign-in page: nobody is signed in, the page asks again.
            return await threaded(_signin_page, request, target, 400, w("form.expired"), login_id)
        try:
            row, held = await _check_password(site, request, login_id, form.get("password", ""))
        except DB_ERRORS:
            log.exception("a sign-in could not be checked")
            return await threaded(_signin_page, request, target, 503, w("signin.down"), login_id)
        if held:
            response = await threaded(_signin_page, request, target, 429, w(held[0]), login_id)
            # How long the limit holds this address or ID back, in seconds, as every 429 says it.
            response.headers["Retry-After"] = str(held[2])
            return response
        if row is None:
            return await threaded(_signin_page, request, target, 401, w("signin.wrong"), login_id)
        response = _signed_in(request, row, target)
        # The form's token is used up with the sign-in.
        response.delete_cookie(SIGNIN_COOKIE)
        return response

    def _signed_in(request, row, target):
        """Go on to `target` signed in as `row` (the sign-in cookie, tied to the account's password and to its round
        of sign-ins, which a sign-out ends)."""
        response = _redirect(target)
        cookie = site.signer.sign({"kind": "web", "uid": row["id"], "pw": sess.password_mark(row["password"]),
                                   "g": row["session_generation"]})
        response.set_cookie(COOKIE, cookie, max_age=SIGN_IN_DAYS * 86400, httponly=True, samesite="lax",
                            secure=request.url.scheme == "https")
        return response

    def signin_once(request):
        """The link the launcher on this PC opens (Site.once): signs the player in and shows their page, or the
        page asked for. Only a visit from this PC counts, and each link works once."""
        if not _local(request):
            return _redirect("/signin")
        account_id = site.redeem(request.path_params["token"])
        row = None
        if account_id is not None:
            store = site.accounts()
            try:
                row = store.db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
            finally:
                store.db.close()
        if row is None or row["disabled"]:
            return _redirect("/signin")
        # Only paths on this site; the player's own page otherwise.
        target = _local_path(request.query_params.get("next"), "/dj/%d" % row["id"])
        response = _signed_in(request, row, target)
        # The site in the launcher's language.
        if request.query_params.get("lang") in ("en", "ko"):
            response.set_cookie(LANG_COOKIE, request.query_params["lang"], max_age=365 * 86400, samesite="lax")
        return response

    def _end_sign_ins(request):
        """The signed-in account's round of sign-ins ends (signout), on a worker thread."""
        row = site.account(request)
        if row is not None:
            # The cookie is not only dropped by this browser: its round of sign-ins ends, so a copy of it (and the
            # account's other sign-ins on the site) no longer works. The launcher's tokens are not cookies: they stay.
            _accounts_call(site, "end_sign_ins", row["id"])

    async def signout(request):
        form = await request.form()
        if not hmac.compare_digest(form.get("csrf", ""), site.csrf(request)):
            # Not from this site's own page (or from an old one): nothing changes.
            return _redirect("/")
        await threaded(_end_sign_ins, request)
        response = _redirect("/signin")
        response.delete_cookie(COOKIE)
        return response

    async def owner(request):
        """The first account, made from the server PC while the server has none.

        The page is open (nobody can sign in yet), so its form carries a token of its own: one kept in a
        cookie this page set, which a page of another site can neither read nor send.
        """
        if not _local(request):
            return _redirect("/signin")
        w = strings.words(site.language(request))
        form = await request.form() if request.method == "POST" else None
        if not await threaded(_no_account):
            return _redirect("/signin")
        error = None
        token = request.cookies.get(OWNER_COOKIE, "")
        if form is not None:
            if not token or not hmac.compare_digest(form.get("csrf", ""), token):
                error = w("form.expired")
            else:
                try:
                    # Its password is hashed on a worker thread (Site.hashed), as every password is.
                    made = form.get("login_id", "").strip().upper()
                    await site.hashed(_accounts_call, site, "create", made, form.get("password", ""),
                                      form.get("dj_name", "").strip() or None, is_admin=True, who="owner")
                    response = _redirect("/signin")
                    response.delete_cookie(OWNER_COOKIE)
                    # The sign-in page that opens next says the account was made (read once there; strict: only a
                    # request that starts on this site carries it).
                    response.set_cookie(MADE_COOKIE, made, max_age=120, httponly=True, samesite="strict")
                    return response
                except acc.AccountError as e:
                    error = w.error(e)
        if not token:
            token = secrets.token_urlsafe(24)
        response = await threaded(lambda: site.render(
            request, "owner.html", user=None, error=error, owner_token=token, password_min=acc.PASSWORD_MIN,
            password_max=acc.PASSWORD_MAX))
        # Strict: the browser sends it only with requests that start on this site.
        response.set_cookie(OWNER_COOKIE, token, max_age=3600, httponly=True, samesite="strict")
        return response

    async def language(request):
        code = "ko" if request.path_params["code"] == "ko" else "en"
        # Back to the page the switch was on (next=, a path of this site; Home for anything else).
        response = _redirect(_local_path(request.query_params.get("next")))
        response.set_cookie(LANG_COOKIE, code, max_age=365 * 86400, samesite="lax")
        return response

    def licenses(request):
        """openDMT3's own licence, the parts the server and what it hands out are made with and their licences, and
        the fonts the site serves with theirs, read from the files that come with them (open to anyone, as the parts'
        licences ask that whoever receives them can see them; common.py, shared with the API's twin)."""
        return site.render(request, "licenses.html", own=_own_licence(), parts=LICENCE_PARTS, texts=_licence_texts(),
                           licences=LICENCE_FACES)

    async def robots(request):
        """Search engines are asked to leave the whole site alone: every page is for the server's players."""
        return PlainTextResponse("User-agent: *\nDisallow: /\n")

    async def favicon(request):
        """The launcher's mark, where browsers look for a site's icon without being told (pages name it with its
        version: base.html)."""
        return FileResponse(os.path.join(HERE, "static", "favicon.ico"), media_type="image/x-icon",
                            headers={"Cache-Control": "public, max-age=86400"})

    def rankings(request):
        modes = _modes(site)
        mode = _mode_asked(request.query_params.get("mode"), modes)
        if mode is None:
            mode = _mode_asked(None, modes)
        # By total (the default), by the best 30's average, or this month's total with the months before it.
        by = request.query_params.get("by") if request.query_params.get("by") in ("best30", "month") else "total"
        w = strings.words(site.language(request))
        month = None
        if by == "month":
            month = _month_rankings(site, mode)
            rows = month["rows"]
            # Each month named in the page's words.
            month["name"] = _month_name(w, month["start"])
            for past in month["past"]:
                past["name"] = _month_name(w, past["start"])
        else:
            rows = _rankings(site, mode, by)
        # The table shows the first RANKING_SHOWN rows and says how many there are when it stops short.
        return site.render(request, "rankings.html", mode=mode, modes=[(m, _mode_name(m)) for m in modes],
                           rows=rows, shown=RANKING_SHOWN, by=by, best_of=rec.Records.BEST_OF, month=month)

    def songs_page(request):
        query = request.query_params.get("q", "").strip()
        rows = _songs(site)
        # Every song this server has: the filter box counts the songs it shows out of these. Find narrows them as the
        # API's twin does (common.py).
        return site.render(request, "songs.html", rows=_songs_found(rows, query), query=query, total=len(rows))

    def song_page(request):
        number = _song_number(request)
        song = _song(site, number) if number is not None else None
        if song is None:
            return _not_found(site, request)
        # Each chart's board shows its first RANKING_SHOWN and says how many there are when it stops short.
        return site.render(request, "song.html", song=song, shown=RANKING_SHOWN)

    def dj_page(request):
        dj = _dj(site, request.path_params["player"]) if request.path_params["player"] < 2 ** 63 else None
        if dj is None:
            return _not_found(site, request)
        # Where the DJ stands in each mode's ranking by total; the best scores show their first BESTS_SHOWN.
        return site.render(request, "dj.html", dj=dj, places=_dj_places(site, dj["player"]), bests_shown=BESTS_SHOWN)

    def home(request):
        user = site.account(request)
        # The player's own plays and everyone's, the newest RECENT_SHOWN of each with how many there are in all.
        mine, mine_total = _recent(site, user["id"], RECENT_SHOWN)
        everyone, everyone_total = _recent(site, None, RECENT_SHOWN)
        # The first DJs of the mode the Rankings page opens on (the first mode played).
        modes = _modes(site)
        top = {"mode": modes[0], "name": _mode_name(modes[0]),
               "rows": _rankings(site, modes[0])[:TOP_SHOWN]} if modes else None
        return site.render(request, "home.html", user=user, cabinets=_cabinets_for(site, user), mine=mine,
                           mine_total=mine_total, everyone=everyone, everyone_total=everyone_total,
                           records=_new_records(site, RECORDS_SHOWN), shown=RECENT_SHOWN, top=top)

    def download(request):
        user = site.account(request)
        # The installer's size, when it was put there and its version (None: no installer to hand out), the address
        # and the file's name, as the API's twin gives them (common.py).
        return site.render(request, "download.html", user=user, **_download(site, request))

    def installer(request):
        """The installer with this server on its end (common._installer, shared with the API's twin), or the page that
        is not there when the server has none."""
        answer = _installer(site, request)
        if answer is None:
            return _not_found(site, request)
        return answer

    def jacket(request):
        """A song's disc picture, read from the server owner's own game files at --catalog (never shipped)."""
        path = cat.jacket_path(site.data_dir, request.path_params["number"])
        if path is None:
            # A picture that is not there: a plain answer, never a page made for it (pictures are not counted).
            return PlainTextResponse("Not Found", status_code=404)
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})

    async def account_page(request):
        """The signed-in player's own account: the DJ card, the DJ name, the password (a new card goes with it) and the
        API's named tokens (made, shown once, listed, revoked: services/tokens.py, shared with the API's twins).

        Each change ends on a redirect back here (the page's form token follows the new sign-in after a new
        password); the current password is counted like a sign-in, so this form cannot be used to guess it. The form
        is read on the loop; every change and the page are made on worker threads.
        """
        w = strings.words(site.language(request))
        form = await request.form() if request.method == "POST" else None
        user = await threaded(site.account, request)
        # A token made just now: shown in this answer only (never in an address or a redirect), with its name.
        error, made, notice = None, None, None
        if form is not None:
            if not hmac.compare_digest(form.get("csrf", ""), site.csrf(request)):
                error = w("form.expired")
            elif form.get("action") in ("token_make", "token_revoke", "card", "dj_name"):
                # A change without a password: made on a worker thread; a done one goes back to the page.
                error, made, notice, back = await threaded(_account_change, w, user, form)
                if back:
                    return _redirect(back)
            elif form.get("action") == "password":
                # The current password is checked like a sign-in: the same limits, on a worker thread.
                checked, held = await _check_password(site, request, user["login_id"], form.get("current", ""))
                if held:
                    error = w(held[0])
                elif checked is None:
                    error = w("me.password.wrong")
                elif form.get("new", "") != form.get("again", ""):
                    error = w("me.password.mismatch")
                else:
                    try:
                        await site.hashed(_accounts_call, site, "set_password", user["login_id"], form.get("new", ""),
                                          who=user["login_id"])
                        # Signed in again here with the new password; every other sign-in and token ends.
                        fresh = await threaded(_accounts_call, site, "by_login", user["login_id"])
                        return _signed_in(request, fresh, "/account?done=password")
                    except acc.AccountError as e:
                        error = w.error(e)
        done = request.query_params.get("done")
        if notice is None and done in ("dj_name", "password", "card") and not error:
            notice = w("me.%s.done" % done)
        return await threaded(_account_shown, request, user, notice, error, made)

    def _account_change(w, user, form):
        """account_page's changes that need no password, on a worker thread: (error, the token made, the notice, the
        address to go back to when done)."""
        action = form.get("action")
        store = site.accounts()
        try:
            if action in ("token_make", "token_revoke"):
                tokens = tok.Tokens(store.db)
                try:
                    if action == "token_make":
                        # Logged by the player's ID, as the API's twin logs it by the caller's.
                        row, token = tokens.make(user, form.get("name", ""), form.get("scope", ""),
                                                 who=user["login_id"])
                        return None, {"name": row["name"], "token": token}, None, None
                    # Asked first on the page, in the site's own dialog.
                    name = tokens.revoke(user, form.get("id", ""), who=user["login_id"])
                    return None, None, w("me.tokens.revoked", name=name), None
                except tok.TokenError as e:
                    return w.error(e), None, None, None
            if action == "card":
                try:
                    # The choices as the form sends them (a radio button's number); a box left alone sends none.
                    store.set_card(user["login_id"], cards.load(site.data_dir), icon=_number(form.get("icon")),
                                   plate=_number(form.get("plate")), pattern=_number(form.get("pattern")),
                                   comment=form.get("comment", ""), who=user["login_id"])
                    return None, None, None, "/account?done=card"
                except cards.CardError as e:
                    return w.error(e), None, None, None
            try:
                store.set_dj_name(user["login_id"], form.get("dj_name", "").strip(), who=user["login_id"])
                return None, None, None, "/account?done=dj_name"
            except acc.AccountError as e:
                return w.error(e), None, None, None
        finally:
            store.db.close()

    def _account_shown(request, user, notice, error, made):
        """The account page itself, on a worker thread: the player's named tokens, newest first (names, scopes and
        times, never the tokens), the DJ card and the choices."""
        store = site.accounts()
        try:
            listed = tok.Tokens(store.db).all(user["id"])
        finally:
            store.db.close()
        return site.render(request, "account.html", user=user, notice=notice, error=error, card=_card(site, user),
                           choices=cards.load(site.data_dir), comment_max=cards.COMMENT_MAX,
                           password_min=acc.PASSWORD_MIN, password_max=acc.PASSWORD_MAX, dj_max=acc.DJ_NAME_MAX,
                           tokens=listed, made=made, token_name_max=tok.NAME_MAX, tokens_most=tok.MOST)

    def card_picture(request):
        """A picture of the DJ card's choices, read from the server owner's own game files at --catalog."""
        path = cards.picture(site.data_dir, request.path_params["kind"], request.path_params["number"])
        if path is None:
            # A picture that is not there: a plain answer, never a page made for it (pictures are not counted).
            return PlainTextResponse("Not Found", status_code=404)
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})

    # The route table's first run, in its order: create_app puts the admin pages' routes right after it.
    return [
        Route("/signin", signin, methods=["GET", "POST"]),
        Route("/signin/once/{token}", signin_once),
        Route("/signout", signout, methods=["POST"]),
        Route("/owner", owner, methods=["GET", "POST"]),
        Route("/lang/{code}", language),
        Route("/", home),
        Route("/rankings", rankings),
        Route("/songs", songs_page),
        Route("/songs/{number:int}", song_page),
        Route("/jackets/{number:int}.png", jacket),
        Route("/cards/{kind}/{number:int}.png", card_picture),
        Route("/dj/{player:int}", dj_page),
        Route("/account", account_page, methods=["GET", "POST"]),
        Route("/download", download),
        Route("/download/windows", installer),
        Route("/licenses", licenses),
        Route("/robots.txt", robots),
        Route("/favicon.ico", favicon),
    ]
