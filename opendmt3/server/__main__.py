"""Run the openDMT3 server: the game server and the site in one process.

  python -m opendmt3.server [--data DIR] [--host 0.0.0.0] [--port 4725] [--web-host ADDRESS] [--web-port 4730]
                            [--proxy ADDRESS] [--verbose]
  python -m opendmt3.server --data DIR [--catalog PATH] [--add-player ID ...] [--setup-only]
  python -m opendmt3.server --catalog PATH --save FILE   (save the song list from PATH into FILE, and exit)
  python -m opendmt3.server ... --game FOLDER   (the client data the admin's Song list tab finds and imports again)
  python -m opendmt3.server ... --site-address URL   (the site's address for players, in the message to send one)

PATH is the client data's folder (or a folder above it), an archive holding the client data (only the files the
server needs are taken out), or a song list the launcher saved. An archive's password comes from
OPENDMT3_ARCHIVE_PASSWORD.
  python -m opendmt3.server --data DIR --backup | --backups | --restore NAME

The game connects on --port; people open the site on --web-port (0 turns the site off), at --web-host (the same
address as --host unless given: 127.0.0.1 keeps the site for a reverse proxy on this PC). DIR holds the
database, the site's signing secret, backups/ (one a day while it runs, a week kept) and downloads/ (put a release's
opendmt3-launcher-<version>-windows-x64-setup.exe there, as it is, to hand it out).
On a first start with no account, open the site from this PC to make the owner's account.
"""

import argparse
import asyncio
import logging
import os
import sys

from opendmt3 import __version__
from opendmt3.server import banner, db
from opendmt3.server.server import DEFAULT_PORT, GameServer
from opendmt3.core import errors
from opendmt3.server.services import accounts, activity, backups, catalog, notify, records, songlist, sources

WEB_PORT = 4730


def web_host(args):
    """The address the site listens on: --web-host, else the game's --host."""
    return getattr(args, "web_host", None) or args.host


def web_config(uvicorn, app, args):
    """The site's server settings. Behind a reverse proxy (--proxy) its forwarded headers are believed, from that
    address only: without it every visitor would seem to come from the proxy (one wrong password would hold back
    everyone's sign-ins) and an HTTPS visit would look like plain HTTP."""
    return uvicorn.Config(app, host=web_host(args), port=args.web_port, log_level="warning",
                          proxy_headers=bool(args.proxy), forwarded_allow_ips=args.proxy or "")


# An archive's password, from the environment (never on a command line others can read): ./dmt3 asks for it.
PASSWORD_ENV = "OPENDMT3_ARCHIVE_PASSWORD"
# The refusals that are one plain line of their own (what was found and the one thing to do): no traceback is kept.
WORDED = (sources.SourceError, songlist.SongListError, errors.Worded)


def read_catalog(path, data):
    """--catalog: the song list, its jackets and the DJ cards read from a game folder, an archive holding one or a song
    list the launcher saved, into data, each part one plain line on the screen (a missing optional part says what
    still works). 0 once the song list is read, 2 when it cannot be: the reason as one line too, a traceback (for an
    error that is not one of the worded refusals) in the data folder's catalog.log, never on the screen. Run as root
    on a data folder someone else owns (./dmt3 catalog, for a game folder only root may read), root only reads: the
    data folder is written by its owner alone (catalog.read_as)."""
    password = os.environ.get(PASSWORD_ENV) or None
    writer = catalog.writer_for(data)
    try:
        if writer is None:
            report = sources.read(path, data, password=password)
        else:
            report = catalog.read_as(writer, data, lambda into: sources.read(path, into, password=password))
    except Exception as e:  # noqa: BLE001  (every reason a list cannot be read is said the same way)
        if isinstance(e, WORDED):
            print("song list: not read. %s" % errors.say(e))
            return 2
        catalog.keep_trace(data, "the song list", e)
        print("song list: not read (%s); details in %s" % (catalog.why(e), os.path.join(data, catalog.LOG_FILE)))
        return 2
    for _, text in catalog.lines(report):
        print(text)
    if report["missing"]:
        print("details in %s" % os.path.join(data, catalog.LOG_FILE))
    return 0


def save_song_list(path, out):
    """--catalog PATH --save FILE: the song list read from PATH (any form) into a song list at FILE, checked as a
    server takes it; the server's data folder is not touched. 0 when saved, 2 with the reason when not."""
    out = os.path.abspath(out)
    if os.path.isdir(out):
        # A folder named: the file goes in it under its usual name.
        out = os.path.join(out, songlist.NAME)
    password = os.environ.get(PASSWORD_ENV) or None
    # Saved as root into a folder someone else owns: root only reads, the file is written by that owner alone.
    writer = catalog.writer_for(os.path.dirname(out))
    try:
        if writer is None:
            manifest, report = sources.save(path, out, password=password)
        else:
            manifest, report = catalog.save_as(writer, out, lambda made, work: sources.save(path, made,
                                                                                           password=password,
                                                                                           work=work))
    except Exception as e:  # noqa: BLE001  (said in one line, never a traceback on the screen)
        print("song list: not saved. %s" % (errors.say(e) if isinstance(e, WORDED) else catalog.why(e)))
        return 2
    for _, text in catalog.lines(report):
        print(text)
    print("saved %s (%d KB)" % (out, os.path.getsize(out) // 1024))
    return 0


async def serve(args, data, until=None, notes=(), runner=None):
    """The game server and the site on args' addresses, until they are cancelled (Ctrl+C), or until `until` (a
    coroutine function, when given) returns: the server's own command line for a PC of its own (standalone.py) stops
    it that way when asked to from another window. Either way the site finishes the requests it has, and the game
    server and the database are closed. Once the site answers, the banner (banner.py) says where it is, with `notes`
    under it (the caller's own lines). runner: who started the server, which the admin's Status tab asks to stop it
    (web/runner.py); without one, Docker Compose's in a container, else one it cannot tell."""
    # The folder the Download page hands the installer out from, there to put the file in.
    os.makedirs(os.path.join(data, "downloads"), exist_ok=True)
    connection = db.connect(os.path.join(data, "openDMT3.sqlite"))
    game = await GameServer(args.host, args.port, accounts=accounts.Accounts(connection),
                            records=records.Records(connection), activity=activity.Activity(connection),
                            webhook=notify.Webhook(args.webhook, data) if args.webhook else None,
                            data=data).start()
    # One backup a day, the week's kept (backups.py); checked hourly while the server runs.
    tasks = [asyncio.ensure_future(backups.keep_daily(os.path.join(data, "openDMT3.sqlite"), data))]
    web = None
    # The banner's task: it ends once it has printed, so it is never one of the tasks whose end ends the server.
    announcing = None
    if args.web_port:
        # The site needs its own libraries; the game server alone does not.
        import uvicorn
        from opendmt3.server.web.app import Site, create_app
        # The game folder only when it is there: an empty mount point offers no button.
        game_folder = args.game if args.game and os.path.isdir(args.game) else None
        site = Site(data, game_server=game, game_port=game.port, game_folder=game_folder,
                    address=args.site_address, runner=runner)
        config = web_config(uvicorn, create_app(site), args)
        web = uvicorn.Server(config)
        web_task = asyncio.ensure_future(web.serve())
        tasks.append(web_task)
        # An address to open on this PC: a server on every address (0.0.0.0, ::) is on the loopback one too,
        # the name the owner's first-run page asks for (web.common._local).
        shown = {"0.0.0.0": "127.0.0.1", "::": "[::1]"}.get(web_host(args), web_host(args))
        logging.getLogger("opendmt3.server").info("site on http://%s:%d/", shown, args.web_port)

        async def announce():
            # Once uvicorn listens: the addresses then work.
            while not web.started:
                await asyncio.sleep(0.05)
            said = list(notes)
            first = connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0
            if first and not sources.in_container():
                # The first-run page answers a visit from this PC itself (in a container no visit is one).
                said.insert(0, "First start: open http://%s:%d/ on this PC to make the owner's account."
                            % (shown, args.web_port))
            banner.show(__version__, banner.rows(args.site_address, "http://%s:%d/" % (shown, args.web_port),
                                                 game.port), said)
        announcing = asyncio.ensure_future(announce())
    try:
        if until is None:
            await asyncio.gather(*tasks)
        else:
            stopper = asyncio.ensure_future(until())
            await asyncio.wait(tasks + [stopper], return_when=asyncio.FIRST_COMPLETED)
            if web is not None:
                # The site's own way to stop: it answers what it has started, then its task ends.
                web.should_exit = True
                await asyncio.wait([web_task], timeout=10)
            for task in tasks + [stopper]:
                task.cancel()
            # Each cancelled task is let finish its cancellation before the database closes under it.
            await asyncio.gather(*tasks, stopper, return_exceptions=True)
    finally:
        if announcing is not None and not announcing.done():
            # Stopped before the site came up: nothing to say.
            announcing.cancel()
        await game.close()
        connection.close()


def parser():
    """The server's command line (standalone.py reads a run's settings with it too)."""
    p = argparse.ArgumentParser(prog="opendmt3.server", description="The openDMT3 server: game and site.")
    p.add_argument("--data", default=os.environ.get("OPENDMT3_DATA", "data"), help="folder for the database and files")
    p.add_argument("--host", default="127.0.0.1", help="address to listen on (0.0.0.0 for other PCs)")
    # Both ports from the environment too (compose.yaml gives them, ./dmt3 ports chose them), else the usual ones.
    p.add_argument("--port", type=int, default=int(os.environ.get("OPENDMT3_GAME_PORT") or DEFAULT_PORT),
                   help="the game's port (or OPENDMT3_GAME_PORT)")
    p.add_argument("--web-host", metavar="ADDRESS",
                   help="the site's address to listen on, when not --host's (127.0.0.1 behind a reverse proxy on "
                        "this PC)")
    p.add_argument("--web-port", type=int, default=int(os.environ.get("OPENDMT3_WEB_PORT") or WEB_PORT),
                   help="the site's port, for the site, the admin pages and the API (0: no site; or OPENDMT3_WEB_PORT)")
    p.add_argument("--webhook", metavar="URL", default=os.environ.get("OPENDMT3_WEBHOOK"),
                   help="a Discord or Slack webhook told when someone takes a chart's first place from another player "
                        "(or OPENDMT3_WEBHOOK)")
    p.add_argument("--proxy", metavar="ADDRESS",
                   help="the reverse proxy in front of the site, by the address its connections come from (several "
                        "with commas): its X-Forwarded-For and X-Forwarded-Proto are believed, so visitors are told "
                        "apart and HTTPS sign-ins get secure cookies")
    p.add_argument("--catalog", metavar="PATH",
                   help="read the song list (with its jackets and the DJ cards) from client data, in a folder or an "
                        "archive, or from a song list the launcher saved, then start")
    p.add_argument("--save", metavar="FILE",
                   help="with --catalog: save the song list read from PATH into FILE (" + songlist.NAME + "), and exit; "
                        "the server's data is not touched")
    # The folder the admin's Song list tab lists and imports again: in Docker, the one compose.yaml mounts read-only
    # from GAME_DIR (./dmt3 setup sets it); without it the tab offers none.
    p.add_argument("--game", metavar="FOLDER", default=os.environ.get("OPENDMT3_GAME") or None,
                   help="the folder holding the client data, which the admin's Song list tab finds and imports again "
                        "(or OPENDMT3_GAME)")
    # The address the players reach the site at, which the admin's browser on the server PC does not use
    # (127.0.0.1): the message to send a player carries this one. In Docker, compose.yaml gives it from SITE_ADDRESS
    # (./dmt3 setup keeps the address chosen there).
    p.add_argument("--site-address", metavar="URL", default=os.environ.get("OPENDMT3_SITE_ADDRESS") or None,
                   help="the site's address as players reach it (http://192.168.0.5:4730/), for the message to send a "
                        "player; without it the address the admin's browser used stands in (or OPENDMT3_SITE_ADDRESS)")
    p.add_argument("--verbose", action="store_true",
                   help="log every message with its first bytes (otherwise each unhandled kind is named once)")
    # The admin page's "Make an account", from the command line (scripts, a first start without a browser).
    p.add_argument("--add-player", metavar="ID", help="make an account, print it, and exit")
    p.add_argument("--password", help="its password (made and printed when not given)")
    p.add_argument("--dj", metavar="NAME", help="its DJ name (the ID when not given)")
    p.add_argument("--admin", action="store_true", help="with the admin pages")
    p.add_argument("--backup", action="store_true", help="back the database up now, print its name, and exit")
    p.add_argument("--backups", action="store_true", help="list the backups and exit")
    p.add_argument("--restore", metavar="NAME", help="put the database back to a backup (the current one is backed up "
                                                    "first) and exit")
    p.add_argument("--setup-only", action="store_true", help="do --catalog and --add-player, then exit without serving")
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    data = os.path.abspath(args.data)
    if args.save and not args.catalog:
        p.error("--save goes with --catalog PATH")
    if args.save:
        # A song list made from PATH, then the run ends: nothing else is asked of the server.
        return save_song_list(args.catalog, args.save)
    if args.catalog:
        code = read_catalog(args.catalog, data)
        if code:
            return code
    if args.add_player:
        import secrets
        password = args.password or secrets.token_hex(4)
        connection = db.connect(os.path.join(data, "openDMT3.sqlite"))
        try:
            row = accounts.Accounts(connection).create(args.add_player.upper(), password, args.dj, is_admin=args.admin,
                                                       who="command line")
        except accounts.AccountError as e:
            print("refused: %s" % e, file=sys.stderr)
            return 2
        finally:
            connection.close()
        print("made %s, DJ name %s%s, password %s" % (row["login_id"], row["dj_name"],
                                                      ", admin pages" if args.admin else "", password))
    database = os.path.join(data, "openDMT3.sqlite")
    if args.backup or args.backups or args.restore:
        # The same as the admin page's Backups (and the API's /api/v1/backups); each ends the run.
        try:
            if args.backup:
                db.connect(database).close()
                print("backed up as %s" % backups.make(database, data, "manual"))
            elif args.restore:
                print("restored %s; the database as it was is backed up as %s"
                      % (args.restore, backups.restore(database, data, args.restore)))
            else:
                for b in backups.all_backups(data):
                    print("%s  %-7s  %8d bytes" % (b["name"], b["kind"], b["size"]))
        except backups.BackupError as e:
            print("refused: %s" % e, file=sys.stderr)
            return 2
        return 0
    if args.add_player or args.setup_only:
        # An account made from the command line ends the run, like --setup-only: the server is started on its own.
        return 0

    # What the admin's Status tab asked this command (web/runner.py): it started the server, so it stops it. In a
    # container Docker Compose runs this command and starts it again when it ends: the tab names the command there.
    holder = {}

    def ask():
        # From the site's timer thread: the loop ends the server as after Ctrl+C.
        holder["loop"].call_soon_threadsafe(holder["event"].set)

    async def until():
        holder["loop"], holder["event"] = asyncio.get_running_loop(), asyncio.Event()
        await holder["event"].wait()
        logging.getLogger("opendmt3.server").info("stopping: asked on the admin page")

    from opendmt3.server.web import runner as runners
    run_by = runners.default(True) if sources.in_container() else runners.Runner("python", stop=ask)
    try:
        asyncio.run(serve(args, data, until=None if sources.in_container() else until, runner=run_by))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
