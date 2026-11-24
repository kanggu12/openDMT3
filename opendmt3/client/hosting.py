"""The server inside the launcher, for playing on this PC: logins and records stay in one file on this PC.

The game server runs on its own thread with its own asyncio loop, so the window stays responsive. The site (the
rankings, the songs and each DJ's page) runs on the same loop, for this PC only: the launcher opens it in the
browser with a one-use sign-in. The launcher's pages use a separate database connection (SQLite in WAL mode lets
them read and write while the server does). Both stop when the launcher closes; while the game is open the
launcher keeps running, hidden.
"""

import asyncio
import errno
import logging
import os
import socket
import sqlite3
import threading

from opendmt3.server import db
from opendmt3.core.errors import Worded
from opendmt3.client import state as st
from opendmt3.server.server import DEFAULT_PORT, GameServer
from opendmt3.server.services import accounts, activity, backups, cards, catalog, records

log = logging.getLogger("opendmt3.launcher")

ADDRESS = "127.0.0.1"
# Open to the other PCs on this network (the Online page's switch): every address of this PC.
EVERY_ADDRESS = "0.0.0.0"
# The site's port, as on a server; when another program holds it, any free port (the launcher passes the address).
WEB_PORT = 4730
# The admin site's usual port (ADMIN-SITE.md): on this PC's own address only, the next free one when it is taken.
ADMIN_PORT = 4731


def database_path():
    """The built-in server's database, beside the launcher's settings (kept through updates and reinstalls)."""
    return os.path.join(st.config_dir(), "server", "openDMT3.sqlite")


class HostingError(Worded):
    """The built-in server could not start, worded for the player (another server holds the port, ...; errors.py)."""


# The system's "address in use", as Linux and macOS number it and as Windows does (its sockets' own numbers).
IN_USE = {errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", errno.EADDRINUSE)}


def listen_error(port, error):
    """The worded error for a game server that could not listen on `port` (0: any free port), by what the system said:
    a port another program holds; no free port at all (port 0 asked for any and the system had none: every port of its
    range for programs held, as a PC making many short connections can hold them for a minute); or another reason
    (Windows keeping a port from programs, an address that is not this PC's), its own words in the log."""
    if error.errno in IN_USE and port:
        return HostingError("port %d on this PC is taken; close the other server" % port, "error.host.port", port=port)
    if error.errno in IN_USE:
        return HostingError("this PC has no free port for the built-in server", "error.host.ports")
    return HostingError("the built-in server cannot listen on port %d of this PC" % port, "error.host.listen",
                        port=port)


def database_error(error):
    """The worded error for this PC's database that cannot be opened: one from a newer openDMT3 said as that, anything
    else in one plain line. The system's own reason ("file is not a database") goes to the log, never to a window."""
    # The reason as the system gave it, for a report.
    log.info("the server's database could not be opened: %s", error)
    if isinstance(error, db.DatabaseError):
        # The one reason db.connect words itself: the file is from a newer openDMT3 (no backup helps there).
        return HostingError("The server's database is from a newer openDMT3. Install the newer launcher again.",
                            "error.host.db.newer")
    return HostingError("the server's database cannot be opened", "error.host.db")


class BuiltinServer:
    """Starts and stops the game server for this PC."""

    def __init__(self, path=None, port=DEFAULT_PORT, web_port=WEB_PORT, game=True, lan=False):
        self.path = path or database_path()
        # lan: listen on every address, so the other PCs on this network play on this one (the game here still uses
        # 127.0.0.1, and the site's one-use links still work only from this PC).
        self.lan = lan
        self.port = port
        self.web_port = web_port
        # False: the site alone (openDMT3-cmd --records beside a launcher that already runs the game server).
        self.game = game
        self.thread = None
        self.loop = None
        self.server = None
        self.ready = threading.Event()
        self.error = None
        # The site: None until it runs, and when the web libraries are missing (a source checkout without them).
        self.site = None
        self.web = None
        self.web_task = None
        self.web_url = None
        # The admin site beside it (its own listener on this PC's own address), and its address.
        self.admin_web = None
        self.admin_task = None
        self.admin_url = None
        self.backup_task = None
        # One start at a time: a second caller (Admin pages pressed twice, My records with PLAY) waits for the first
        # and finds it running, instead of starting a second server thread over the first's loop.
        self._start_lock = threading.Lock()
        # The admin pages' first opening makes this PC's server's admin once, whoever asks at the same moment.
        self._admin_lock = threading.Lock()
        # The song list read apart from the window before PLAY needs it (import_catalog_soon), once at a time.
        self._catalog_lock = threading.Lock()
        self._catalog_thread = None

    @property
    def listen_address(self):
        return EVERY_ADDRESS if self.lan else ADDRESS

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive() and (self.server is not None or not self.game)

    @property
    def game_address(self):
        """What the game's networksetting.ini gets: this PC, the game's own port."""
        return "%s:%d" % (ADDRESS, self.port)

    def start(self, timeout=10):
        """Start on a thread and wait until it listens, its site and admin site too; HostingError when it cannot. One
        start at a time: a caller that comes while another starts it waits for that start, and finds it running (or
        gets its error) instead of starting a second server over the first."""
        with self._start_lock:
            if self.running and self.ready.is_set():
                return
            self.ready.clear()
            self.error = None
            self.thread = threading.Thread(target=self._run, daemon=True, name="game-server")
            self.thread.start()
            if not self.ready.wait(timeout):
                raise HostingError("the built-in server did not start within %d seconds" % timeout,
                                   "error.host.timeout", seconds=timeout)
            if self.error is not None:
                # The thread of a start that failed ends by itself, closing its loop: waited for here, so a stop()
                # right after (the caller's cleanup) never reaches a loop that is closing.
                self.thread.join(timeout)
                raise self.error

    def _run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            connection = db.connect(self.path)
        except Exception as e:  # noqa: BLE001  (a newer database, a locked or broken file: said in plain words)
            self.error = database_error(e)
            self.ready.set()
            self.loop.close()
            return
        server = None
        try:
            if self.game:
                server = GameServer(self.listen_address, self.port, accounts=accounts.Accounts(connection),
                                    records=records.Records(connection), activity=activity.Activity(connection),
                                    data=os.path.dirname(self.path))
                try:
                    self.loop.run_until_complete(server.start())
                except OSError as e:
                    # Most often: another server (or another launcher) already listens on the game's port. Said as
                    # what the system said (listen_error); its own reason goes to the log and rides with the error
                    # as its cause (a test's lines show it), the window says what happened.
                    log.info("the game server could not listen on port %d: %s", self.port, e)
                    self.error = listen_error(self.port, e)
                    self.error.__cause__ = e
                    try:
                        # What it started before its listener (the database's threads) ends with it.
                        self.loop.run_until_complete(server.close())
                    except Exception:  # noqa: BLE001  (the error to say is the listen's; this one goes to the log)
                        log.exception("the game server that could not listen did not close")
                    self.ready.set()
                    return
                self.server = server
            # A backup a day of this PC's logins and records, as on a server (kept beside the database).
            self.backup_task = self.loop.create_task(backups.keep_daily(self.path, os.path.dirname(self.path)))
            # The site never stops the game server from starting: without it the launcher only hides its button.
            try:
                self._start_site(server)
            except Exception:  # noqa: BLE001
                log.exception("the site on this PC did not start")
            self.ready.set()
            self.loop.run_forever()
            if self.backup_task is not None:
                self.backup_task.cancel()
                self.loop.run_until_complete(asyncio.gather(self.backup_task, return_exceptions=True))
            if self.web is not None:
                # uvicorn's own shutdown: it closes the listening sockets and waits for open requests (the site's and
                # the admin site's, together).
                self.web.should_exit = True
                tasks = [self.web_task]
                if self.admin_web is not None:
                    self.admin_web.should_exit = True
                    tasks.append(self.admin_task)
                self.loop.run_until_complete(asyncio.wait(tasks, timeout=5))
            if server is not None:
                self.loop.run_until_complete(server.close())
        finally:
            connection.close()
            self.server = None
            self.site = self.web = self.web_task = self.web_url = self.backup_task = None
            self.admin_web = self.admin_task = self.admin_url = None
            self.loop.close()

    def _start_site(self, game_server):
        """The site beside the game server, on this PC's own address only."""
        try:
            import uvicorn
            from opendmt3.server.web.app import Site, create_admin_app, create_app
        except ImportError:
            log.info("no site on this PC: the web libraries are not installed")
            return
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind((self.listen_address, self.web_port))
        except OSError:
            # Another program (a server, another launcher's site) has the usual port: any free one will do.
            listener.bind((self.listen_address, 0))
        # The admin site on this PC's own address only, whatever the site listens on (ADMIN-SITE.md), its usual port or
        # any free one.
        admin = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            admin.bind((ADDRESS, ADMIN_PORT))
        except OSError:
            admin.bind((ADDRESS, 0))
        admin_url = "http://%s:%d/" % (ADDRESS, admin.getsockname()[1])
        # The site keeps its files beside the database: the song list, the sign-in secret.
        # The launcher started this server, so the admin page's Stop names the launcher (web/runner.py). The admin pages
        # are the admin site's alone, and its links to the players' pages go to the site's port.
        from opendmt3.server.web.runner import Runner
        site = Site(os.path.dirname(self.path), game_server=game_server, game_port=self.port,
                    runner=Runner("launcher"), admin_address=admin_url, admin_on_site_port=False,
                    site_port=listener.getsockname()[1])

        def served(app, sockets):
            # log_config=None: uvicorn's loggers go to the launcher's own log instead of a setup of their own.
            config = uvicorn.Config(app, log_level="warning", log_config=None, access_log=False, proxy_headers=False,
                                    lifespan="off", loop="none", http="h11", ws="none")
            server = uvicorn.Server(config)
            return server, self.loop.create_task(server.serve(sockets=sockets))

        self.web, self.web_task = served(create_app(site), [listener])
        self.admin_web, self.admin_task = served(create_admin_app(site), [admin])
        # Ready means it takes connections: the launcher opens the browser right after.
        self.loop.run_until_complete(self._site_started())
        if not self.web.started:
            log.warning("the site on this PC did not start")
            self.web.should_exit = self.admin_web.should_exit = True
            self.web = self.web_task = self.admin_web = self.admin_task = None
            return
        self.site = site
        self.web_url = "http://%s:%d/" % (ADDRESS, listener.getsockname()[1])
        log.info("site on this PC at %s", self.web_url)
        if self.admin_web.started:
            self.admin_url = admin_url
            log.info("admin pages on this PC at %s", self.admin_url)
        else:
            # The site still runs; the admin pages are not offered.
            log.warning("the admin site on this PC did not start")

    async def _site_started(self, limit=5.0):
        """Wait (at most `limit` seconds) until both uvicorns listen, or stopped trying."""
        waited = 0.0
        while waited < limit and any(not server.started and not task.done()
                                     for server, task in ((self.web, self.web_task), (self.admin_web, self.admin_task))):
            await asyncio.sleep(0.02)
            waited += 0.02

    def addresses(self):
        """The site's addresses for the other PCs on this network (private IPv4 addresses of this PC), when open to them."""
        if not self.lan or self.web_url is None:
            return []
        port = int(self.web_url.rstrip("/").rsplit(":", 1)[1])
        return ["http://%s:%d" % (ip, port) for ip in home_addresses()]

    def sign_in_link(self, login_id, language="en"):
        """A link that opens `login_id`'s DJ page signed in (Site.once), or None without a site or that player."""
        if self.site is None or not login_id:
            return None
        store = self.accounts()
        try:
            row = store.by_login(login_id)
        finally:
            store.db.close()
        if row is None or row["disabled"]:
            return None
        return "%ssignin/once/%s?lang=%s" % (self.web_url, self.site.once(row["id"]), language)

    def admin_link(self, language="en"):
        """A link that opens this PC's server's admin pages signed in (Site.once for the admin site, from this PC only):
        as its admin, the first enabled admin account. With none yet, the first player made on this PC becomes its
        admin, as a server's first account is its owner's: this PC's server is the PC's owner's, and the admin pages
        take an admin's sign-in alone. Returns (link, made): made is the ID made admin by this very call (never
        silently: the launcher says it once, and its log keeps it), else None; (None, None) without an admin site or
        an enabled player."""
        if self.site is None or self.admin_url is None:
            return None, None
        # The look for an admin and the making of one as one step: two openings at once make one admin, said once.
        with self._admin_lock:
            return self._admin_link(language)

    def _admin_link(self, language):
        made = None
        store = self.accounts()
        try:
            row = store.db.execute("SELECT id, login_id FROM accounts WHERE is_admin = 1 AND disabled = 0 "
                                   "ORDER BY id LIMIT 1").fetchone()
            if row is None:
                first = store.db.execute("SELECT id, login_id FROM accounts WHERE disabled = 0 ORDER BY id LIMIT 1"
                                         ).fetchone()
                if first is None:
                    return None, None
                store.set_admin(first["login_id"], True, who="launcher")
                log.info("%s is now this PC's server's admin (the first player made on this PC; the admin pages take "
                         "an admin's sign-in alone)", first["login_id"])
                row, made = first, first["login_id"]
        finally:
            store.db.close()
        return "%ssignin/once/%s?lang=%s" % (self.admin_url, self.site.once(row["id"], admin=True), language), made

    def stop(self):
        if self.loop is not None and self.thread is not None and self.thread.is_alive():
            try:
                self.loop.call_soon_threadsafe(self.loop.stop)
            except RuntimeError:
                # Its loop closed meanwhile: the thread was ending by itself (a start that failed ends so).
                pass
            # The site gets up to 5 s to finish open requests, then the game server closes.
            self.thread.join(10)
        self.thread = None

    def _connect(self):
        """A connection for the caller's thread; HostingError (worded) when the file cannot be opened as the
        database: damaged, from a newer openDMT3, or something else in its place."""
        try:
            return db.connect(self.path)
        except Exception as e:  # noqa: BLE001  (SQLite's own errors and a newer database alike: in plain words)
            raise database_error(e) from e

    def accounts(self):
        """The accounts, on a connection for the caller's thread (the launcher's pages)."""
        return accounts.Accounts(self._connect())

    def records(self):
        """The plays, on a connection for the caller's thread."""
        return records.Records(self._connect())

    def player_rows(self):
        """Every player, for the launcher's lists. HostingError (worded) when the database cannot be read, at its
        start or further in: a file damaged past its first page opens, then fails at the first read."""
        store = self.accounts()
        try:
            return store.all()
        except sqlite3.Error as e:
            raise database_error(e) from e
        finally:
            store.db.close()

    def import_catalog_soon(self, game_folder):
        """Start reading the song list from the game folder now, apart from the window, when none has been read: the
        first PLAY then finds it read (measured under Wine: 13.6 s of a first PLAY's 25 s). Returns the thread, or
        None when there is nothing to read or a reading is under way."""
        with self._catalog_lock:
            if self._catalog_thread is not None and self._catalog_thread.is_alive():
                return None
            # An empty list is no list: catalog.load answers {} when none was read.
            if self.catalog():
                return None

            def read():
                try:
                    self._import_now(game_folder)
                except Exception:  # noqa: BLE001  (PLAY reads it again and says what stops it)
                    log.warning("the song list could not be read ahead of PLAY", exc_info=True)

            self._catalog_thread = threading.Thread(target=read, daemon=True, name="song list")
            self._catalog_thread.start()
            return self._catalog_thread

    def import_catalog(self, game_folder):
        """Read the song list from the player's game folder once (pages show titles instead of numbers); a reading
        started ahead (import_catalog_soon) is waited for, not done twice."""
        reading = self._catalog_thread
        if reading is not None and reading.is_alive():
            reading.join()
        with self._catalog_lock:
            self._import_now(game_folder)

    def _import_now(self, game_folder):
        folder = os.path.dirname(self.path)
        if not catalog.load(folder):
            catalog.import_from(game_folder, folder)
        elif not cards.load(folder):
            # A list an older launcher read: the DJ card's tables and pictures come now.
            try:
                catalog.import_cards(game_folder, folder)
            except Exception:  # noqa: BLE001  (without them every DJ card keeps its defaults)
                log.exception("the DJ card's tables could not be read")

    def catalog(self):
        return catalog.load(os.path.dirname(self.path))


def home_addresses():
    """This PC's private IPv4 addresses (the ones other PCs on its network reach it by), best guess first."""
    found = []
    try:
        # The address the system would send from: no packet goes out for a UDP "connection".
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("192.0.2.1", 9))
            found.append(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass
    try:
        found += socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    private = []
    for ip in found:
        a, b = (int(part) for part in ip.split(".")[:2])
        if (a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168)) and ip not in private:
            private.append(ip)
    return private
