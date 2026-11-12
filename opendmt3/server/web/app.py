"""The server's site, admin pages and API, as one ASGI app (Starlette) beside the game server.

Every page needs a sign-in first (an account made by the owner); only the sign-in page, the language switch,
the static files, the health check, the owner's first-run page (from the server PC only), the Licenses page,
robots.txt, the site's icon and the API (its own tokens) are open. Forms carry a token tied to the sign-in (the
sign-in page and the owner's page, a token in a cookie of their own), so a page of another site cannot post them.
The API is what the launcher talks to: the server's status, and a sign-in that returns the player's card.

The site shares its event loop with the game server, so the loop never runs the site's work: every query, page and
answer is made on Starlette's worker threads (plain handlers, which Starlette runs there, or work.threaded), a
password's slow check (PBKDF2) too (Site.hashed), and the loop only reads requests and sends answers. Each request
has one connection to the database (Site.connect, opened at its first use and closed once its answer is sent), and
the lists made from everyone's plays are kept until the plays change (cache.py). Every caller (a sign-in, a token,
an address) gets a fair share of that work (Shares): a few requests at once, and so many seconds of processor time a
minute.

The site is split by area, each in a module of its own with a routes(site) that create_app joins: pages.py (the
public site), admin.py (the admin pages) and api.py (the API and the launcher's update feed). common.py holds what
they share. This module keeps Site, which every area uses, the health check, and what goes around every request:
compression of text answers, Cache-Control: no-store on every answer of the API, the site's own answer to a failure,
and the sign-in wall.
"""

import asyncio
import functools
import hashlib
import hmac
import logging
import math
import os
import secrets
import threading
import time
import zlib
from urllib.parse import parse_qs, quote

from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.applications import Starlette
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from opendmt3 import __version__
from opendmt3.server import db
from opendmt3.server.services import accounts as acc
from opendmt3.server.services import activity as act
from opendmt3.server.services import limits
from opendmt3.server.services import maintenance
from opendmt3.server.services import notice
# The areas: each builds its own routes for a Site, and create_app joins them into one table.
from opendmt3.server.web import admin, api, pages
# The lists made from everyone's plays, kept until the plays change.
from opendmt3.server.web import cache
# Each request's own connection and processor time, and the worker threads its work runs on.
from opendmt3.server.web.work import REQUEST, Request as _Request, charged, limit_threads, long, threaded
from opendmt3.server.web import session as sess
from opendmt3.server.web import strings
# Under /api/ the 404 and 405 handlers, and a failure, answer as the rest of the API does.
from opendmt3.server.web.api import _error, api_unknown
# Site reads the cookies the pages set, so their names come from common.py, where all the cookies' names are; the
# wall's redirect, the 404 handler's error page, a 405's Allow and the health check come from there too.
from opendmt3.server.web.common import COOKIE, LANG_COOKIE, SIGN_IN_DAYS, _allowed, _health, _redirect, not_found

HERE = os.path.dirname(os.path.abspath(__file__))
# The wide face the site shares with the launcher, kept once in the client's assets (opendmt3/client/assets/fonts):
# a file read, not an import, so the server still imports nothing of the client.
FONTS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "client", "assets", "fonts")
# Wrong passwords from one address (an IPv6 /64 counts as one, services/limits.py): at most this many in this many
# seconds, then it waits.
TRIES, WINDOW = 5, 600
# Wrong passwords for one ID within WINDOW, from wherever they come: a guess spread over many addresses stops here
# too. Visits from the server PC itself never wait for it, so nobody can shut the owner out of their own server.
ID_TRIES = 10
# Sign-ins from one address, right or wrong, at most this many a minute: each costs a slow password check, so a
# right password sent over and over cannot keep the server busy either.
SIGN_INS, SIGN_IN_WINDOW = 20, 60
# Addresses (and IDs) with recent tries kept in memory at most; past it the oldest go (a flood forgets itself).
ADDRESSES_KEPT = 10_000
# Password checks and new passwords (PBKDF2, tens of milliseconds each) on worker threads at once, at most: the
# event loop the game server shares never waits for one, and a burst of sign-ins cannot take every core.
HASHING_AT_ONCE = 2
# The largest request body read: every form and API call here is a few hundred bytes.
BODY_LIMIT = 64 * 1024
# The routes an admin uploads a file to (a backup on the Backups tab and its API twin, a song list on the Song list tab
# and its API twin): their handlers read the body into a file as it comes and count it against the upload's own limit
# (services/backups.py UPLOAD_MOST, services/songlist.py MOST), so the wall leaves a POST to them alone; BODY_LIMIT
# stays for every other request.
UPLOADS = ("/admin/backups/upload", "/api/v1/backups/upload", "/admin/song_list/upload", "/api/v1/server/song_list")
# How long a one-use sign-in link from this PC's launcher works (it is opened at once).
ONCE_SECONDS = 60
# Every HTML page's own headers (Site.render): not stored anywhere, and told apart by the sign-in cookie.
PAGE_HEADERS = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
# What Compress compresses: text answers of these types, of this many bytes or more; never under these paths.
COMPRESSED_TYPES = ("text/html", "text/css", "text/javascript", "application/javascript", "application/json")
COMPRESS_MIN = 1024
NEVER_COMPRESSED = ("/updates/",)
# Where the API's answers are, every one of them never stored (NoStore).
API_PREFIX = "/api/"
# Text answers at least this large are compressed on a worker thread (zlib lets go of the interpreter meanwhile), not
# on the loop: a 2.5 MB page took the loop about 30 ms to compress, a time no cabinet's keep-alive should wait.
COMPRESS_ON_THREAD = 64 * 1024
# Fair shares of the site's work (Shares). A caller is a sign-in (its cookie) or a token (the API's), and every request
# also counts for the address it came from (an IPv6 /64 is one). Each may have this many requests being answered at
# once (the others wait their turn, without holding a worker thread), and spend this many seconds of the server's
# processor time a minute on its requests' work (work.charged: what it used, not what it waited for); past that, 429
# with when to try again. A visitor's page takes a few milliseconds of it (the lists are kept); a program asking for
# the heaviest list over and over gets its share, half a core at most, and everyone else keeps theirs. One request at
# a time for a caller: the site has two worker threads (work.SITE_THREADS), so no caller holds both (a page's files
# are not counted). An address has more room: a game centre's players share one.
CALLER_AT_ONCE, ADDRESS_AT_ONCE = 1, 8
CALLER_SECONDS, ADDRESS_SECONDS = 30.0, 90.0
# Requests of one caller or address waiting for their turn at most; one more is refused at once (429).
WAITING_MOST = 32
# The stretch the seconds are counted over.
SHARE_WINDOW = 60.0
# What costs nothing to hand out and comes many at a time with every page (files read as they are): never counted.
FREE_PATHS = ("/static/", "/fonts/", "/jackets/", "/cards/", "/updates/")
# The single files of the same kind, matched whole (as a prefix "/health" took "/healthX" too).
FREE_FILES = ("/favicon.ico", "/robots.txt", "/health")
# Seconds the health check's answer is kept: Docker asks every 30 seconds, and a stream of asks takes the database's
# write lock once in this long at most, never once each beside the game server's writes.
HEALTH_KEPT = 2.0
# Busy pages kept made ((language, seconds, notice, maintenance) -> the page), at most: a refused request is answered
# from here, never with a page made on the site's threads for each refusal of a flood.
BUSY_PAGES_KEPT = 256


def free(path):
    """True for what costs nothing to hand out and is never counted (FREE_PATHS, FREE_FILES)."""
    return path.startswith(FREE_PATHS) or path in FREE_FILES

log = logging.getLogger("opendmt3.web")


class Site:
    """What the pages share: the database, the signer, the game server (for live cabinets), the words."""

    def __init__(self, data_dir, game_server=None, game_port=4725, downloads=None, game_folder=None, address=None):
        self.data_dir = data_dir
        # The site's address as the players reach it (--site-address: the one its owner chose in ./dmt3 setup), which
        # the message to send a player carries; None: the address the admin's own browser used stands in.
        self.address = address
        # The game folder the admin's Status page may read the song list from again (--game), or None: no button.
        self.game_folder = game_folder
        # One reading at a time: a second press while one runs is told so instead of starting another.
        self.reading = threading.Lock()
        self.db_path = os.path.join(data_dir, "openDMT3.sqlite")
        self.signer = sess.Signer(sess.load_secret(data_dir))
        self.game_server = game_server
        self.game_port = game_port
        self.downloads = downloads or os.path.join(data_dir, "downloads")
        # The launcher's update packages (build.sh's OUT_DIR/releases), handed to the launchers connected here.
        self.updates = os.path.join(data_dir, "updates")
        # Wrong passwords per address, wrong passwords per ID, and every sign-in per address (services/limits.py).
        self.wrong = limits.Recent(WINDOW, lambda: ADDRESSES_KEPT)
        self.wrong_ids = limits.Recent(WINDOW, lambda: ADDRESSES_KEPT)
        self.sign_ins = limits.Recent(SIGN_IN_WINDOW, lambda: ADDRESSES_KEPT)
        # The address table itself: address -> times of its recent wrong passwords.
        self.failures = self.wrong.table
        # (the event loop, a semaphore on it) for hashed(): made on the loop that first needs it.
        self._gate = None
        # One-use sign-in links the launcher on this PC hands the browser: token -> (account id, expiry).
        self.onces = {}
        # once() runs on the launcher's thread, redeem() on the server's.
        self.onces_lock = threading.Lock()
        self.templates = Environment(loader=FileSystemLoader(os.path.join(HERE, "templates")),
                                     autoescape=select_autoescape(["html"]))
        # Times are stored as seconds; pages show them as a date and a time on the server's clock.
        self.templates.filters["when"] = lambda t: time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else ""
        # A day without the year, for the activity chart's weeks.
        self.templates.filters["day"] = lambda t: time.strftime("%m/%d", time.localtime(t))
        # The lists made from everyone's plays, kept until the plays change (cache.py).
        self.lists = cache.Lists()
        # The seconds of requests each caller and each address spent lately (Shares), shared by every thread.
        self.spent = limits.Spent(SHARE_WINDOW, lambda: ADDRESSES_KEPT)
        # The health check's last answer, (when, status, answer), and the look being made now (the loop's own: one at
        # a time).
        self._health = None
        self._health_checking = None
        # The busy pages kept made (busy_page), the lock their table takes, and those being made now (the loop's own:
        # every refusal at the same moment waits for the one page being made).
        self._busy_pages = {}
        self._busy_lock = threading.Lock()
        self._busy_making = {}
        # (the event loop, its _Turns: who is being answered now, per caller and address) for Shares: made on the loop
        # that first needs it, as gate() is.
        self._turns = None

    def connect(self):
        """The database connection for the request being answered: opened at its first use in the request and lent to
        every later one (db.Lent: their close() leaves it open), closed by Work once the answer is sent. Outside a
        request (the launcher's own calls, a test's), a new connection the caller closes."""
        work = REQUEST.get()
        if work is None:
            return db.connect(self.db_path)
        if work.connection is None:
            # The first use in this request: one connection for all of it (each part used to open its own).
            work.connection = db.connect(self.db_path, factory=db.Lent)
        return work.connection

    def accounts(self):
        return acc.Accounts(self.connect())

    def activity(self):
        return act.Activity(self.connect())

    def once(self, account_id):
        """A one-use sign-in for an account, for the launcher on this PC to open in the browser
        (/signin/once/<token>): it works once, for ONCE_SECONDS, and only for a visit from this PC."""
        token = secrets.token_urlsafe(24)
        now = time.monotonic()
        with self.onces_lock:
            # Expired links go first, so unused ones never pile up.
            self.onces = {t: v for t, v in self.onces.items() if v[1] > now}
            self.onces[token] = (account_id, now + ONCE_SECONDS)
        return token

    def redeem(self, token):
        """The account a one-use sign-in is for, or None (unknown, used or expired); it is used up either way."""
        with self.onces_lock:
            entry = self.onces.pop(token, None)
        if entry is None or entry[1] < time.monotonic():
            return None
        return entry[0]

    # --------------------------------------------------------------------------------- requests

    def language(self, request):
        return "ko" if request.cookies.get(LANG_COOKIE) == "ko" else "en"

    def account(self, request):
        """The signed-in account for this request, or None (no cookie, a bad one, an old password, a sign-out since
        the cookie was made). Looked up once a request (the sign-in wall, the page and its template all ask)."""
        cookie = request.cookies.get(COOKIE, "")
        work = REQUEST.get()
        if work is not None and cookie in work.accounts:
            # Asked already in this request, with the same cookie: the same answer.
            return work.accounts[cookie]
        row = self._account(cookie)
        if work is not None:
            work.accounts[cookie] = row
        return row

    def _account(self, cookie):
        """account()'s lookup of the account a sign-in cookie names, in the database."""
        data = self.signer.unsign(cookie, SIGN_IN_DAYS * 86400)
        if not data or data.get("kind") != "web":
            return None
        store = self.accounts()
        try:
            row = store.db.execute("SELECT * FROM accounts WHERE id = ?", (data.get("uid"),)).fetchone()
        finally:
            store.db.close()
        if row is None or row["disabled"] or data.get("pw") != sess.password_mark(row["password"]):
            return None
        # The account's round of sign-ins when the cookie was made (cookies from before rounds counted as 0): a
        # sign-out starts the next round, which ends this cookie wherever a copy of it is.
        if data.get("g", 0) != row["session_generation"]:
            return None
        return row

    def gate(self):
        """The semaphore that lets HASHING_AT_ONCE password checks run at a time, on the running event loop."""
        loop = asyncio.get_running_loop()
        if self._gate is None or self._gate[0] is not loop:
            # A semaphore belongs to one loop: the server has one for good, the tests a new one per client.
            self._gate = (loop, asyncio.Semaphore(HASHING_AT_ONCE))
        return self._gate[1]

    def turns(self):
        """The table of turns (Shares) of the running event loop: made on the loop that first needs it, as gate() is."""
        loop = asyncio.get_running_loop()
        if self._turns is None or self._turns[0] is not loop:
            # Its semaphores belong to one loop: the server has one for good, the tests a new one per client.
            self._turns = (loop, _Turns())
        return self._turns[1]

    async def hashed(self, fn, *args, **kwargs):
        """fn(*args, **kwargs) on a thread of the long work's own (work.long), through the gate, for anything that makes
        a password (PBKDF2): the event loop, which the game server's cabinets share, and the site's own threads go on
        meanwhile."""
        async with self.gate():
            return await long(functools.partial(fn, *args, **kwargs))

    async def health(self):
        """(status, answer) for GET /health (common._health), kept HEALTH_KEPT seconds and answered on the loop
        meanwhile. Past that, one look at a time, on the long work's threads (it may wait up to 15 seconds for a
        database another connection holds: never on the site's two): the request that starts it waits for it, and those
        that come while it runs get the last answer."""
        kept = self._health
        if kept is not None and time.monotonic() - kept[0] < HEALTH_KEPT:
            return kept[1], kept[2]
        loop = asyncio.get_running_loop()
        checking = self._health_checking
        if checking is not None and checking.get_loop() is loop and not checking.done():
            if kept is not None:
                return kept[1], kept[2]
        else:
            checking = self._health_checking = asyncio.ensure_future(long(self._health_now))
        # Shielded: a request that goes away does not take the look from the others.
        return await asyncio.shield(checking)

    def _health_now(self):
        """health()'s look, on a long work's thread, kept with its moment."""
        status, answer = _health(self)
        self._health = (time.monotonic(), status, answer)
        return status, answer

    async def busy_page(self, request, seconds):
        """The page that tells a caller past its share to come back in `seconds` (429), in its language, with the
        notice and maintenance as every page shows them: made once on a worker thread for each of those, then handed
        out as made. Nothing of the caller's own is on it (no account, no form: the language switch comes back to
        Home)."""
        language = self.language(request)
        shown = notice.read(self.data_dir)
        key = (language, seconds, shown["text"] if shown else None, maintenance.read(self.data_dir) is not None)
        page = self._busy_pages.get(key)
        if page is not None:
            return page
        loop = asyncio.get_running_loop()
        making = self._busy_making.get(key)
        if making is None or making.get_loop() is not loop:
            # The first refusal of its kind makes the page; the others at the same moment wait for that one.
            making = self._busy_making[key] = asyncio.ensure_future(threaded(self._busy_made, key))
            making.add_done_callback(lambda done: self._busy_making.pop(key, None)
                                     if self._busy_making.get(key) is done else None)
        # Shielded: a refused request that goes away does not take the page being made from the others.
        return await asyncio.shield(making)

    def _busy_made(self, key):
        """busy_page()'s page made, on a worker thread, and kept (the table emptied once it holds BUSY_PAGES_KEPT)."""
        language, seconds, text, on = key
        page = self.templates.get_template("error.html").render(
            w=strings.words(language), lang=language, user=None, version=__version__, path="/", here="/", csrf="",
            site_notice=text, site_maintenance=on, busy=seconds)
        with self._busy_lock:
            if len(self._busy_pages) >= BUSY_PAGES_KEPT:
                self._busy_pages.clear()
            self._busy_pages[key] = page
        return page

    def csrf(self, request):
        """The form token for this sign-in: an HMAC of the cookie, so it changes with every sign-in."""
        cookie = request.cookies.get(COOKIE, "")
        return hmac.new(self.signer.secret, ("csrf:" + cookie).encode(), "sha256").hexdigest()[:32]

    def render(self, request, name, status=200, **context):
        w = strings.words(self.language(request))
        user = context.pop("user", None) if "user" in context else self.account(request)
        # The admin's notice, at the top of every page (services/notice.py; read again only when it changes), and
        # beside it whether the server is in maintenance (services/maintenance.py, read the same way).
        shown = notice.read(self.data_dir)
        # The page as asked for, query and all: where the language switch comes back to. A page shown in answer to a
        # form posted elsewhere (an upload's) names its own address instead.
        here = context.pop("here", None) or request.url.path + ("?" + request.url.query if request.url.query else "")
        html = self.templates.get_template(name).render(
            w=w, lang=self.language(request), user=user, version=__version__, path=request.url.path, here=here,
            csrf=self.csrf(request), site_notice=shown["text"] if shown else None,
            site_maintenance=maintenance.read(self.data_dir) is not None, **context)
        # A page is the signed-in visitor's own: never kept by a cache on the way, nor by the browser for its Back
        # button after a sign-out; and it differs with the cookie that signs in.
        return HTMLResponse(html, status_code=status, headers=PAGE_HEADERS)

    def too_many(self, address):
        """True while the address has had TRIES wrong passwords within WINDOW."""
        return self.wrong.count(limits.sender(address)) >= TRIES

    def failed(self, address, login_id=None):
        """Count a wrong password from the address, and for the ID when one is given; returns what forgive() takes
        back. The table forgets the address heard from longest ago first (services/limits.py), in constant time."""
        marks = [self.wrong.add(limits.sender(address))]
        if login_id:
            marks.append(self.wrong_ids.add(_id_key(login_id)))
        return marks

    def forgive(self, marks):
        """Take back a wrong password counted before its check (failed()), which turned out right."""
        for table, mark in zip((self.wrong, self.wrong_ids), marks):
            table.take_back(mark)

    def id_held(self, login_id):
        """True while the ID has had ID_TRIES wrong passwords within WINDOW."""
        return bool(login_id) and self.wrong_ids.count(_id_key(login_id)) >= ID_TRIES

    def sign_in_allowed(self, address):
        """Count one sign-in from the address; False (not counted) once it has had SIGN_INS in SIGN_IN_WINDOW."""
        key = limits.sender(address)
        if self.sign_ins.count(key) >= SIGN_INS:
            return False
        self.sign_ins.add(key)
        return True

    # How long a sign-in held back by each limit waits, in whole seconds: what a 429 says in its Retry-After.

    def sign_in_wait(self, address):
        """Until the address may sign in again (sign_in_allowed)."""
        return _whole_seconds(self.sign_ins.wait(limits.sender(address), SIGN_INS))

    def wrong_wait(self, address):
        """Until the address's wrong passwords are fewer than TRIES (too_many)."""
        return _whole_seconds(self.wrong.wait(limits.sender(address), TRIES))

    def id_wait(self, login_id):
        """Until the ID's wrong passwords are fewer than ID_TRIES (id_held)."""
        return _whole_seconds(self.wrong_ids.wait(_id_key(login_id), ID_TRIES))


def _id_key(login_id):
    """An ID as the limits count it: as the database compares it (in any case), cut to a sane length."""
    return str(login_id).strip().upper()[:32]


def _whole_seconds(wait):
    """A wait as Retry-After gives it: whole seconds, rounded up (never sooner than the limit lets go), at least one."""
    return max(1, math.ceil(wait))


def create_app(site):
    """The ASGI app for one Site."""

    # ---------------------------------------------------------------------------------- sign-in wall

    # The Licenses page, robots.txt and the site's icon are for anyone, as the fonts and the sign-in page are.
    open_paths = ("/signin", "/signout", "/owner", "/lang/", "/static/", "/fonts/", "/health", "/api/", "/updates/",
                  "/licenses", "/robots.txt", "/favicon.ico")

    class SignInWall:
        """Every page but the open ones sends a visitor without a sign-in to /signin, then back.

        It also refuses any request whose body is larger than BODY_LIMIT, before the app reads it, but an upload's
        (UPLOADS), which its handler reads and counts itself, after this wall's sign-in check.
        """

        def __init__(self, app):
            self.app = app

        async def _refuse(self, scope, receive, send, status, text):
            response = Response(text, status_code=status, media_type="text/plain")
            await response(scope, receive, send)

        async def __call__(self, scope, receive, send):
            # An upload's body is its handler's to read and count (UPLOADS); every other body is checked here.
            if scope["type"] == "http" and not (scope["method"] == "POST" and scope["path"] in UPLOADS):
                headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
                try:
                    declared = int(headers.get("content-length", "0"))
                except ValueError:
                    declared = BODY_LIMIT + 1
                if declared > BODY_LIMIT:
                    await self._refuse(scope, receive, send, 413, "request too large")
                    return
                if "content-length" not in headers and scope["method"] not in ("GET", "HEAD", "OPTIONS"):
                    # A body sent in chunks has no length to check first: read it here, up to the limit.
                    body = await _read_capped(receive)
                    if body is None:
                        await self._refuse(scope, receive, send, 413, "request too large")
                        return
                    receive = _replay(body, receive)
            if scope["type"] == "http" and not scope["path"].startswith(open_paths):
                request = Request(scope)
                # The account looked up on a worker thread (a query: never on the loop); the request keeps it (Work).
                if await threaded(site.account, request) is None:
                    target = scope["path"] + ("?" + scope["query_string"].decode() if scope["query_string"] else "")
                    response = _redirect("/signin?next=" + quote(target))
                    await response(scope, receive, send)
                    return
            await self.app(scope, receive, send)

    async def _read_capped(receive):
        """The whole body of a request sent in chunks, or None once it passes BODY_LIMIT."""
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > BODY_LIMIT:
                return None
            chunks.append(chunk)
            if not message.get("more_body"):
                break
        return b"".join(chunks)

    def _replay(body, receive):
        """receive() for the app: the body already read, in one piece, then whatever the client does next."""
        sent = {"body": False}

        async def replay():
            if not sent["body"]:
                sent["body"] = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()
        return replay

    # ------------------------------------------------------------------------------- failures

    def _failure(request):
        """The answer to a request that failed: JSON under /api/ (500, as the API's other errors), the site's own
        page for anything else (503, "not available right now"), a line of text if even that page fails."""
        if request.url.path.startswith("/api/"):
            return _error(500, "server_error", "the server could not answer this; the reason is in its log")
        try:
            # Made without the database (no signed-in account looked up): it may be what failed.
            return site.render(request, "error.html", status=503, user=None, unavailable=True)
        except Exception:  # noqa: BLE001  (the plainest answer is still an answer)
            log.exception("the page for a failure could not be made either")
            return PlainTextResponse("Not available right now. Try again in a while.", status_code=503,
                                     headers=PAGE_HEADERS)

    class Errors:
        """An exception below (a page, the API, the sign-in wall) answers in the site's own way and is logged with
        its traceback; the server goes on with the next request. When part of the answer went out already, the
        connection ends instead (the server logs it)."""

        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return
            started = False

            async def watched(message):
                nonlocal started
                if message["type"] == "http.response.start":
                    started = True
                await send(message)

            try:
                await self.app(scope, receive, watched)
            except Exception:
                if started:
                    raise
                log.exception("%s %s failed", scope["method"], scope["path"])
                # The site's own page, made on a worker thread as every page is.
                answer = await threaded(_failure, Request(scope, receive))
                await answer(scope, receive, send)

    # The route table in the order it has always had (Starlette tries the routes in order and the first match
    # answers): each area's routes are one run of it, so joining them in this order keeps it. The health check
    # comes first (its own, here: it answers 503 when the database fails), static files last.
    async def health(request):
        status, answer = await site.health()
        return JSONResponse(answer, status_code=status)

    # Each area's plain handlers count their processor time to their request (work.charged), as threaded() does for
    # the work an async handler hands over: the route made again around the counted handler, as it was otherwise.
    areas = [route if not isinstance(route, Route) or asyncio.iscoroutinefunction(route.endpoint)
             else Route(route.path, charged(route.endpoint), methods=route.methods, name=route.name)
             for route in pages.routes(site) + admin.routes(site) + api.routes(site)]
    routes = [Route("/health", health)] + areas + [
        Mount("/static", VersionedFiles(directory=os.path.join(HERE, "static")), name="static"),
        Mount("/fonts", VersionedFiles(directory=FONTS), name="fonts"),
    ]

    async def missing(request, exc=None):
        if request.url.path.startswith("/api/"):
            return await api_unknown(request, exc)
        if free(request.url.path):
            # A file or picture that is not there: a plain answer, never a page made for it (they are not counted).
            return PlainTextResponse("Not Found", status_code=404)
        return await not_found(site, request, exc)

    async def wrong_method(request, exc=None):
        if request.url.path.startswith("/api/"):
            return await api_unknown(request, exc)
        # Allow names the methods the page takes, as every 405 says them.
        return Response("Method Not Allowed", status_code=405, headers=_allowed(exc))

    # Around the routes, outermost first: text answers compressed, the API's answers never stored, failures answered
    # and logged, the request's own connection and processor time (Work), each caller's fair share of it (Shares), the
    # sign-in wall. NoStore is outside the rest, so their own answers under /api/ carry it too; Errors outside Work and
    # Shares, so a failure anywhere below is answered; Work outside Shares, so Shares counts what Work kept (a refused
    # request opens nothing: the connection is opened at its first use).
    return Starlette(routes=routes, exception_handlers={404: missing, 405: wrong_method},
                     middleware=[Middleware(Compress), Middleware(NoStore), Middleware(Errors), Middleware(Work),
                                 Middleware(Shares, site=site), Middleware(SignInWall)])


class Work:
    """Each HTTP request with a work.Request of its own (REQUEST, which Starlette's worker threads see as well, since it
    copies the context to them): one connection to the database for the whole request, its parts (the sign-in wall,
    the page, its template) sharing it, closed once the answer is sent; and the processor time its work takes, which
    Shares counts."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # The worker threads the work may take at once (work.SITE_THREADS), set once for this loop.
        limit_threads()
        work = _Request()
        token = REQUEST.set(work)
        try:
            await self.app(scope, receive, send)
        finally:
            REQUEST.reset(token)
            if work.connection is not None:
                connection, work.connection = work.connection, None
                try:
                    # Closed on a worker thread: closing can write the database's log back into it.
                    await threaded(connection.release)
                except BaseException:
                    # The request was stopped (its client went away) before the thread ran: closed here instead.
                    connection.release()
                    raise


class _Turns:
    """Who is being answered now, per key of Shares, on one event loop: at most `at_once` requests of a key at a time,
    the others waiting their turn (on the loop, holding no worker thread), WAITING_MOST of them at most. Only the loop
    touches it; a key with nobody answered or waiting is forgotten."""

    def __init__(self):
        # key -> [the semaphore its requests take turns on, how many are answered or waiting now]
        self.keys = {}

    async def enter(self, key, at_once):
        """Wait for the key's turn; False at once (no turn taken) when WAITING_MOST of its requests wait already."""
        slot = self.keys.get(key)
        if slot is None:
            slot = self.keys[key] = [asyncio.Semaphore(at_once), 0]
        if slot[1] >= at_once + WAITING_MOST:
            return False
        slot[1] += 1
        try:
            await slot[0].acquire()
        except BaseException:
            # Stopped while waiting (its client went away): it holds no turn.
            self._gone(key, slot)
            raise
        return True

    def leave(self, key):
        """The key's request is answered: the next one waiting goes."""
        slot = self.keys[key]
        slot[0].release()
        self._gone(key, slot)

    def _gone(self, key, slot):
        slot[1] -= 1
        if slot[1] == 0 and self.keys.get(key) is slot:
            # Nobody answered or waiting: forgotten, so the table holds only the keys in use.
            del self.keys[key]


def _share_keys(scope):
    """The keys a request counts for in Shares, each with its requests at once and seconds a minute: the caller (a
    sign-in by its cookie, or a token; a hash of it, never the secret itself) when it brings one, then its address."""
    request = Request(scope)
    keys = []
    header = request.headers.get("authorization", "")
    credential = header[7:].strip() if header.lower().startswith("bearer ") else request.cookies.get(COOKIE, "")
    if credential:
        keys.append(("caller:" + hashlib.sha256(credential.encode("utf-8", "replace")).hexdigest()[:24],
                     CALLER_AT_ONCE, CALLER_SECONDS))
    address = request.client.host if request.client else "?"
    keys.append(("address:" + limits.sender(address), ADDRESS_AT_ONCE, ADDRESS_SECONDS))
    return keys


class Shares:
    """Each caller's and each address's fair share of the site's work (CALLER_AT_ONCE and CALLER_SECONDS, ADDRESS_AT_ONCE
    and ADDRESS_SECONDS): a few requests answered at once, the next ones waiting their turn, and so many seconds of
    processor time a minute for their work (Work's count of it: what the request's work used on the worker threads,
    SQLite's included, never the time it waited for a thread, the interpreter or another connection's write). Past
    its seconds, or with too many waiting, a request is answered 429 with Retry-After at once, before anything is read
    for it. The files every page loads (FREE_PATHS) and the uploads (their own limits, admins only) are not counted.

    A program asking for the heaviest list over and over takes no more than its share: everyone else's pages go on."""

    def __init__(self, app, site):
        self.app = app
        self.site = site

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or free(scope["path"]):
            await self.app(scope, receive, send)
            return
        keys = _share_keys(scope)
        # An upload (an admin's, with limits of its own: its size, one import or check at a time) takes its turns like
        # any request, so a stream of them waits or is refused, but its seconds are neither checked nor counted: a
        # backup's check may take more than a minute's share.
        uploading = scope["method"] == "POST" and scope["path"] in UPLOADS
        for key, _, most in ([] if uploading else keys):
            # A caller (or address) past its seconds waits until enough of them leave the minute.
            wait = self.site.spent.wait(key, most)
            if wait > 0:
                await self._refuse(scope, receive, send, wait)
                return
        turns = self.site.turns()
        entered = []
        work = REQUEST.get()
        try:
            for key, at_once, _ in keys:
                # The caller's turn first, then the address's: a request waiting for its caller's turn holds none of its
                # address's places, so one caller's queue never keeps others at the same address waiting.
                if not await turns.enter(key, at_once):
                    await self._refuse(scope, receive, send, 1)
                    return
                entered.append(key)
            for key, _, most in ([] if uploading else keys):
                # The seconds again once its turn came: those that waited behind its caller's other requests may find
                # them spent meanwhile, and wait like any other request past them.
                wait = self.site.spent.wait(key, most)
                if wait > 0:
                    await self._refuse(scope, receive, send, wait)
                    return
            await self.app(scope, receive, send)
        finally:
            for key in entered:
                turns.leave(key)
            if entered and work is not None and not uploading:
                # What the request's work cost (Work counted it), for every key it counts for.
                for key, _, _ in keys:
                    self.site.spent.add(key, work.cpu)

    async def _refuse(self, scope, receive, send, wait):
        """429 with Retry-After (whole seconds, at least one): the API's JSON error under /api/, else the site's page."""
        seconds = _whole_seconds(wait)
        request = Request(scope, receive)
        if scope["path"].startswith(API_PREFIX):
            answer = _error(429, "too_many_requests", "this caller asked for more than its share of the server's work; "
                                                      "try again in %d seconds" % seconds,
                            headers={"Retry-After": str(seconds)})
        else:
            # The page kept made for its language and seconds (Site.busy_page): a flood of refused requests costs no
            # page made for each on the site's threads.
            body = await self.site.busy_page(request, seconds)
            answer = HTMLResponse(body, status_code=429, headers=dict(PAGE_HEADERS, **{"Retry-After": str(seconds)}))
        await answer(scope, receive, send)


class NoStore:
    """Every answer under /api/ carries Cache-Control: no-store, the API's errors, files and pictures too: an answer
    is for the token that asked (an account's card, an admin's lists), so no cache on the way and no program's own
    keeps a copy of it."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith(API_PREFIX):
            await self.app(scope, receive, send)
            return

        async def stamped(message):
            if message["type"] == "http.response.start":
                # An answer always starts with its headers; a start without any gets an empty list to add to.
                message.setdefault("headers", [])
                # MutableHeaders on the message itself: the header goes out with it, in place of any the answer had.
                MutableHeaders(scope=message)["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, stamped)


class VersionedFiles(StaticFiles):
    """Static files; asked for with this openDMT3's version (?v=, as every page asks for them), kept by browsers and
    caches for a year without asking again: the next version asks for new addresses."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code in (200, 304) and parse_qs(scope.get("query_string", b"").decode("latin-1")).get(
                "v") == [__version__]:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def _packed(packer, body):
    """A whole answer's body through the compressor, to its end (Compress, on a worker thread)."""
    return packer.compress(body) + packer.flush()


class Compress:
    """gzip for text answers (HTML, CSS, JavaScript, JSON) of COMPRESS_MIN bytes or more, to browsers that take it.

    Nothing else is touched: the installer, backups and pictures are not of those types, and the launcher's update
    feed is left out by its path (its JSON is read as kept), so their lengths stay as they are (the installer's
    Content-Length is what the browser counts the download against). An answer in pieces (a stream) is compressed
    piece by piece and loses its length; one in a piece gets the compressed length."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or scope["path"].startswith(NEVER_COMPRESSED)
                or "gzip" not in Headers(scope=scope).get("accept-encoding", "")):
            await self.app(scope, receive, send)
            return
        # The start of an answer held back until its first piece says whether to compress it, and the compressor.
        held, packer = None, None

        async def compressing(message):
            nonlocal held, packer
            if message["type"] == "http.response.start":
                headers = Headers(raw=message["headers"])
                kind = headers.get("content-type", "").split(";")[0].strip().lower()
                if message["status"] == 200 and kind in COMPRESSED_TYPES and "content-encoding" not in headers:
                    held = message
                    return
                await send(message)
                return
            if message["type"] != "http.response.body":
                # Anything else (a file sent by the server itself) goes as it is, after the start held back.
                if held is not None:
                    await send(held)
                    held = None
                await send(message)
                return
            body, more = message.get("body", b""), message.get("more_body", False)
            if held is not None:
                start, held = held, None
                if not more and len(body) < COMPRESS_MIN:
                    # Too small to be worth it: as it is.
                    await send(start)
                    await send(message)
                    return
                headers = MutableHeaders(raw=start["headers"])
                headers["Content-Encoding"] = "gzip"
                headers.add_vary_header("Accept-Encoding")
                # gzip's own header and trailer (wbits 31), at the level that costs little time.
                packer = zlib.compressobj(6, zlib.DEFLATED, 31)
                if not more and len(body) >= COMPRESS_ON_THREAD:
                    # A large answer in one piece: compressed on a worker thread, while the loop goes on.
                    data = await threaded(_packed, packer, body)
                else:
                    data = packer.compress(body) + (b"" if more else packer.flush())
                if more:
                    del headers["Content-Length"]
                else:
                    headers["Content-Length"] = str(len(data))
                await send(start)
                await send({"type": "http.response.body", "body": data, "more_body": more})
                return
            if packer is None:
                # An answer not compressed: its pieces as they are.
                await send(message)
                return
            await send({"type": "http.response.body", "body": packer.compress(body) + (b"" if more else packer.flush()),
                        "more_body": more})

        await self.app(scope, receive, compressing)
