"""The server on a PC of its own, without Docker or the launcher: the Windows server package's opendmt3-server.exe,
and the same commands with Python on Linux or macOS (python -m opendmt3.server.standalone, or the opendmt3-server
command the one-line install puts on PATH).

    opendmt3-server                  run here until this window closes (Ctrl+C, or opendmt3-server stop elsewhere)
    opendmt3-server start | stop | restart | status | logs
    opendmt3-server setup [--address A] [--game PATH] [--installer FILE] [--admin ID [--password P]]
    opendmt3-server invite | firewall | expose NAME [--admin-public] | add-player ID | backup | backups | restore NAME
    opendmt3-server catalog PATH

Every command works on one data folder: beside the program in the Windows package (data\\), else --data, or
OPENDMT3_DATA, else ./data. Whatever starts the server, run or start, its stop is this same program's stop: the
running server watches its data folder for the request and ends itself (the site finishes its requests, the database
is closed), so stop works from any window, and a server started in the background has no window to close. Restart is
asked the same way: the running server ends and runs again in its own process (its window, or none, kept). The
admin's Server tab asks the running server through the same requests (web/runner.py, "standalone").
The settings a run starts with (the players' address, the ports, HTTPS behind a proxy) are kept in settings.json in
the data folder: setup and expose write them, run reads them. The rest is the server's own command line
(python -m opendmt3.server), run in this same process.
"""

import argparse
import asyncio
import contextlib
import getpass
import json
import logging
import logging.handlers
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

from opendmt3 import __version__
from opendmt3.server import __main__ as server_cli
from opendmt3.server import edge
from opendmt3.server.services import qr

# The command's name, as people type it (the Windows package's program, the install's command).
PROG = "opendmt3-server"
# The two ports the server listens on by default: the game's, then the site's (server/__main__.py).
GAME_PORT, WEB_PORT = 4725, 4730
# The admin pages, a site of their own (docs/admin.md): their port, and the address they listen on (this PC alone
# unless the owner opens them to the network: setup --admin-host 0.0.0.0), the server's own defaults.
ADMIN_PORT, ADMIN_HOST = 4731, "127.0.0.1"
# The ID the owner's account is offered when it is made in the terminal (as ./dmt3 setup's).
OWNER = "BOSS"
# In the data folder: the running server's record (its process and ports), the request to stop it, the settings a run
# starts with, and the log folder.
RUNNING, STOP, SETTINGS, LOGS = "server-running.json", "server-stop.request", "settings.json", "logs"
# The request to restart it: the running server ends and runs again in its own process.
RESTART = "server-restart.request"
# The players' address setup kept, while expose has the site at https://NAME/: expose --off gives it back.
BEFORE_EXPOSE = "site_address_before_expose"
# The log a run writes: this size, then it starts a new file, keeping this many old ones (8 MB in all at most).
LOG_BYTES, LOG_KEPT = 2 * 1024 * 1024, 3
# The installer the site's Download page hands out from the downloads folder, under the name dmt3 copies it as too.
INSTALLER = "openDMT3-win-Setup.exe"
# Where the Windows package keeps the launcher's installer it brings: run copies it into an empty downloads folder.
BUNDLED_INSTALLER = "installer"
# How long stop waits for the server to end by itself before it ends the process.
STOP_SECONDS = 20
# How often the running server looks for a stop request.
POLL_SECONDS = 0.5
# Windows' process creation flags for a server in the background: a process group of its own, no console window.
DETACHED_PROCESS, CREATE_NEW_PROCESS_GROUP, CREATE_NO_WINDOW = 0x00000008, 0x00000200, 0x08000000
# The firewall rules' names, one for each port, so a second run replaces them and --remove finds them.
RULE = "openDMT3 server (TCP %d)"


class Refused(Exception):
    """A command that cannot go on, said in one line (no traceback)."""


def say(text=""):
    """A line of ours, flushed at once (a console window and a log file alike)."""
    print(text, flush=True)


# ---------------------------------------------------------------------------------------------- the data folder

def frozen():
    """True in the Windows package (PyInstaller's program), where the data folder is beside the program."""
    return bool(getattr(sys, "frozen", False))


def package_folder():
    """The folder the program is in: the Windows package's top (opendmt3-server.exe is there), else this repository's
    top, two folders above this file's package."""
    if frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def default_data():
    """The data folder when --data is not given: OPENDMT3_DATA, the package's data\\ beside the program, or ./data."""
    if os.environ.get("OPENDMT3_DATA"):
        return os.environ["OPENDMT3_DATA"]
    return os.path.join(package_folder(), "data") if frozen() else "data"


def read_json(path, default=None):
    """A JSON file's object, or `default` when it is missing or cannot be read (a half-written one counts as missing)."""
    try:
        with open(path, encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else default
    except (OSError, ValueError):
        return default


def write_json(path, value):
    """A JSON file written whole or not at all: a new file put in the old one's place."""
    with open(path + ".new", "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(path + ".new", path)


def settings(data):
    """The settings a run starts with: the players' address, the ports, the client data folder kept for the Song
    list tab, and the proxy in front of the site (expose)."""
    kept = read_json(os.path.join(data, SETTINGS), {})
    return {"site_address": kept.get("site_address"), "game_port": int(kept.get("game_port") or GAME_PORT),
            "web_port": int(kept.get("web_port") or WEB_PORT), "game": kept.get("game"),
            "proxy": kept.get("proxy"), "webhook": kept.get("webhook"),
            # The admin pages' port and address (None for the server's own defaults, 4731 on this PC alone).
            # 0 kept is the admin pages off (setup --admin-port 0), not the usual port.
            "admin_port": int(kept["admin_port"]) if kept.get("admin_port") is not None else ADMIN_PORT,
            "admin_host": kept.get("admin_host") or ADMIN_HOST,
            # What expose chose (the name, the authority, the admin pages behind Caddy too), for Caddy's settings to
            # be written again when a port moves: none before expose (or after --off, or from a release before it).
            "edge": kept.get("edge") or {},
            # The admin pages behind Caddy too, at the name and the admin port (expose --admin-public).
            "admin_public": bool((kept.get("edge") or {}).get("admin_public"))}


def admin_opened(kept):
    """True when the owner opened the admin pages to other PCs (an address other than this PC's own)."""
    return kept["admin_host"] not in ("127.0.0.1", "localhost", "::1")


def behind_caddy(kept):
    """True while the Caddy beside the server has the admin pages too (expose NAME --admin-public): its HTTPS on the
    admin port, in front of the admin listener."""
    return bool(kept["proxy"] and kept["admin_public"])


def admin_listens(kept):
    """Where the admin listener is for a run, as (address, port): behind Caddy, this PC alone at the port after the
    admin port (one port of a PC cannot be both, and Caddy's HTTPS has the admin port itself then); else the address
    and the port kept."""
    if behind_caddy(kept):
        return "127.0.0.1", kept["admin_port"] + 1
    return kept["admin_host"], kept["admin_port"]


def admin_reached(kept):
    """True when other PCs reach the admin port: the admin pages opened to the network, or Caddy's HTTPS for them
    (expose --admin-public). Only then does the firewall open it; never while they are off (port 0)."""
    return bool(kept["admin_port"]) and (admin_opened(kept) or behind_caddy(kept))


def own_ports(kept):
    """The ports this server's parts listen on, each needing its own: the game's, the site's, the admin listener's,
    and Caddy's admin port while it has the admin pages (expose --admin-public)."""
    return [kept["game_port"], kept["web_port"]] + ([admin_listens(kept)[1]] if kept["admin_port"] else []) + (
        [kept["admin_port"]] if behind_caddy(kept) else [])


def keep(data, **changes):
    """Set these settings (None takes one out) and keep them for the next run."""
    os.makedirs(data, exist_ok=True)
    path = os.path.join(data, SETTINGS)
    kept = read_json(path, {})
    for name, value in changes.items():
        if value is None:
            kept.pop(name, None)
        else:
            kept[name] = value
    write_json(path, kept)


# ---------------------------------------------------------------------------------------------- the running one

def alive(pid):
    """True while a process with this ID runs."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        kernel = ctypes.windll.kernel32
        # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION: enough to ask for its exit code, granted for one's own.
        handle = kernel.OpenProcess(0x00100000 | 0x1000, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            # STILL_ACTIVE (259) while it runs.
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        # A child of this process that ended is still there until it is reaped (a test's, or a start's own while it
        # waits): reaped here, it counts as ended.
        if os.waitpid(pid, os.WNOHANG)[0] == pid:
            return False
    except ChildProcessError:
        # Not this process's child: the system's own answer below.
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Another user's process is there all the same.
        return True
    return True


def running(data):
    """The running server's record ({pid, game_port, web_port, started, background}), or None when none runs on this
    data folder (a record left by a server that was ended without its stop is no running server)."""
    record = read_json(os.path.join(data, RUNNING))
    if record and alive(int(record.get("pid") or 0)):
        return record
    return None


def port_free(port, host="0.0.0.0"):
    """True when nothing listens on this TCP port."""
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        if os.name != "nt":
            # As the server binds it (uvicorn and asyncio set it): a port in TIME_WAIT after a stop is free.
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def health(port, timeout=2.0):
    """The site's /health answer ({"ok": true, "version": ...}) on this PC, or None."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/health" % port, timeout=timeout) as answer:
            return json.loads(answer.read().decode("utf-8"))
    except (OSError, ValueError):
        return None


def lan_addresses():
    """This PC's IPv4 addresses other PCs on its network reach it by, the likeliest first (the one the default
    route leaves from: no packet goes out for a UDP connect)."""
    found = []
    try:
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as probe:
            probe.connect(("192.0.2.1", 9))
            found.append(probe.getsockname()[0])
    except OSError:
        pass
    try:
        found += socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    out = []
    for ip in found:
        if not ip.startswith("127.") and ip not in out:
            out.append(ip)
    return out


def players_address(data):
    """The site's address for players: the one kept (setup --address, expose), else this PC's first address on its
    network, else this PC's own (no other PC reaches that)."""
    kept = settings(data)
    if kept["site_address"]:
        return kept["site_address"]
    addresses = lan_addresses()
    return "http://%s:%d/" % (addresses[0] if addresses else "127.0.0.1", kept["web_port"])


def site_address(text, web_port=WEB_PORT):
    """An address as given (192.168.0.5, a name, or a whole https://... address) as the site's top for players."""
    text = text.strip()
    if "://" not in text:
        text = "http://%s:%d" % (text, web_port)
    return text if text.endswith("/") else text + "/"


# ---------------------------------------------------------------------------------------------- run, start, stop

def server_args(data):
    """The server's own arguments for a run with the kept settings: every address of this PC for the game, the site
    beside it, or the site on this PC only behind the proxy expose set up."""
    kept = settings(data)
    argv = ["--data", data, "--host", "0.0.0.0", "--port", str(kept["game_port"]), "--web-port", str(kept["web_port"])]
    if kept["proxy"]:
        # Behind a proxy on this PC: the site is reached through it alone, and its forwarded headers are believed
        # from this PC's own address only.
        argv += ["--web-host", "127.0.0.1", "--proxy", kept["proxy"]]
    # The players' address: the one kept, else this PC's address on its network, so the message to send a player and
    # the invite carry an address other PCs reach even before setup --address (none when this PC has no network).
    address = players_address(data)
    if "//127.0.0.1:" not in address:
        argv += ["--site-address", address]
    if kept["game"]:
        argv += ["--game", kept["game"]]
    if kept["webhook"]:
        argv += ["--webhook", kept["webhook"]]
    # The admin listener's port and address: behind Caddy always given (this PC alone, the next port, whatever the
    # environment says), else only when the owner chose others than the server's own (4731, this PC).
    host, port = admin_listens(kept)
    if port != ADMIN_PORT or behind_caddy(kept):
        argv += ["--admin-port", str(port)]
    if host != ADMIN_HOST or behind_caddy(kept):
        argv += ["--admin-host", host]
    return argv


def log_to(data, console):
    """The run's log: a file in data/logs that starts a new one at LOG_BYTES (LOG_KEPT kept), and the console too when
    there is one to see it."""
    folder = os.path.join(data, LOGS)
    os.makedirs(folder, exist_ok=True)
    handlers = [logging.handlers.RotatingFileHandler(os.path.join(folder, "server.log"), maxBytes=LOG_BYTES,
                                                     backupCount=LOG_KEPT, encoding="utf-8")]
    if console:
        handlers.append(logging.StreamHandler(sys.stdout))
    # force: the server's own basicConfig never ran in this process, but a test's may have.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers,
                        force=True)


def hand_out_bundled(data):
    """The launcher's installer the Windows package brings, into the downloads folder under its release name
    (opendmt3-launcher-<version>-windows-x64-setup.exe) when it is not there yet: of the installers there the site
    hands out the newest version (services/downloads.py), so a newer package moved onto an older data folder hands out
    its own, and an installer the owner put there is never replaced or deleted. One without a release name goes in only
    when the folder has none."""
    folder = os.path.join(package_folder(), BUNDLED_INSTALLER)
    downloads = os.path.join(data, "downloads")
    try:
        brought = sorted(n for n in os.listdir(folder) if n.lower().endswith(".exe"))
    except OSError:
        return None
    os.makedirs(downloads, exist_ok=True)
    if not brought:
        return None
    from opendmt3.server.services import downloads as handed
    name = brought[-1]
    there = os.listdir(downloads)
    if handed.RELEASED.match(name):
        if name in there:
            return None
        target = name
    elif any(n.lower().endswith(".exe") for n in there):
        return None
    else:
        target = INSTALLER
    shutil.copyfile(os.path.join(folder, name), os.path.join(downloads, target))
    return name


def first_account_needed(data):
    """True while the database has no account (the owner's first-run page is then the site's top on this PC)."""
    import sqlite3
    path = os.path.join(data, "openDMT3.sqlite")
    if not os.path.exists(path):
        return True
    try:
        with contextlib.closing(sqlite3.connect(path)) as connection:
            return connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0
    except sqlite3.Error:
        return True


def show_banner(data):
    """The server's banner as the running one printed it (server/banner.py, its rows the server's own: the players'
    address, this PC's, the admin pages', the game's port), for start, whose server prints its own into its log
    folder."""
    from opendmt3.server import banner
    kept = settings(data)
    # The first-run page is the admin pages' (the site's when the server has none).
    first = admin_here(data) or "http://127.0.0.1:%d/" % kept["web_port"]
    banner.show(__version__, server_cli.banner_rows(server_args_namespace(data), kept["game_port"]),
                ["First start: open %s on this PC to make the owner's account." % first]
                if first_account_needed(data) else [])


def admin_here(data):
    """The admin pages' address on this PC, where their first-run page answers: the admin listener's port as the run
    will have it (behind Caddy the next one; nothing kept here, the server's own default or its environment's). None
    when the server has no admin pages of their own (--admin-port 0)."""
    port = server_args_namespace(data).admin_port
    return "http://127.0.0.1:%d/" % port if port else None


def admin_line(data):
    """Where the admin pages are, in ./dmt3's words: through Caddy at the site's name and the admin port (expose
    --admin-public), on the network too (setup --admin-host 0.0.0.0), or on this PC alone."""
    kept = settings(data)
    if not kept["admin_port"]:
        return "The admin pages: off (%s setup --admin-port %d turns them on)." % (PROG, ADMIN_PORT)
    if behind_caddy(kept):
        return "The admin pages: https://%s:%d/ (through Caddy)." % (kept["edge"]["name"], kept["admin_port"])
    here = admin_here(data)
    if not admin_opened(kept):
        return "The admin pages: %s (this PC only)." % here
    addresses = lan_addresses()
    if not addresses:
        return "The admin pages: %s (other PCs too, at this PC's address on the network)." % here
    return "The admin pages: http://%s:%d/ (on this PC also %s)." % (addresses[0], kept["admin_port"], here)


def cmd_run(args):
    """The server in this process until it is stopped: Ctrl+C, the window closed, or a stop request (stop)."""
    data = os.path.abspath(args.data)
    os.makedirs(data, exist_ok=True)
    other = running(data)
    if other and other.get("pid") != os.getpid():
        raise Refused("the server already runs on this data folder (process %s): %s stop stops it"
                      % (other["pid"], PROG))
    kept = settings(data)
    if len(set(own_ports(kept))) != len(own_ports(kept)):
        # Two of its own parts on one port (a site's port kept from before the admin pages had theirs): one of them
        # could not listen.
        raise Refused("each part needs a port of its own: %s (%s setup --game-port/--web-port/--admin-port moves one)"
                      % (", ".join(str(port) for port in own_ports(kept)), PROG))
    # The admin listener's port as the run will have it (behind Caddy the next one; the environment's when this
    # folder keeps none): a port another program holds would stop the server just after its start.
    admin = server_args_namespace(data).admin_port
    for port in [kept["game_port"], kept["web_port"]] + ([admin] if admin else []):
        if not port_free(port):
            raise Refused("port %d is taken by another program: stop it, or choose other ports with %s setup "
                          "--game-port/--web-port/--admin-port" % (port, PROG))
    log_to(data, console=not args.background)
    brought = hand_out_bundled(data)
    if brought:
        logging.getLogger("opendmt3.server").info("the Download page hands out %s", brought)
    stop_file, restart_file = os.path.join(data, STOP), os.path.join(data, RESTART)
    for name in (stop_file, restart_file):
        with contextlib.suppress(FileNotFoundError):
            # A request left from before is for a server long gone.
            os.remove(name)
    # What the admin's Server tab asked beyond a stop: the data deleted once the server has stopped.
    asked = {"delete_data": False}

    def request(path):
        # The same request file the commands write (stop, restart), so the page and the commands ask alike.
        with open(path, "w", encoding="utf-8") as f:
            f.write("%d\n" % os.getpid())

    def remove(delete_data):
        asked["delete_data"] = bool(delete_data)
        request(stop_file)

    from opendmt3.server.web import runner as runners
    # This process started the server, so it is the one the Server tab asks to stop, restart or remove it.
    run_by = runners.Runner("standalone", stop=lambda: request(stop_file), restart=lambda: request(restart_file),
                            remove=remove)

    async def until_asked():
        # A stop or restart request, looked for twice a second: then the server ends itself as after Ctrl+C.
        while not (os.path.exists(stop_file) or os.path.exists(restart_file)):
            await asyncio.sleep(POLL_SECONDS)

    async def serve(first):
        # The banner (server/banner.py) comes from the server once its site answers, with how this run stops.
        notes = [] if args.background else [
            "It runs while this window is open. To stop it: close the window, press Ctrl+C, or run %s stop." % PROG]
        task = asyncio.ensure_future(server_cli.serve(server_args_namespace(data), data, until=until_asked,
                                                      notes=notes, runner=run_by))
        if first and not args.background and not args.no_browser and first_account_needed(data):
            for _ in range(100):
                # Asked from a thread: the site answers on this same loop, which must not wait on the question.
                if task.done() or await asyncio.to_thread(health, kept["web_port"], 0.5):
                    break
                await asyncio.sleep(0.1)
            if not task.done():
                # The first start, at the PC: the admin pages, a site of their own on this PC, where the owner's
                # account is made (their first-run page), at the admin listener itself (behind Caddy too: a visit
                # through it is never this PC's).
                import webbrowser
                webbrowser.open(admin_here(data) or "http://127.0.0.1:%d/" % kept["web_port"])
        await task

    first = True
    try:
        while True:
            write_json(os.path.join(data, RUNNING), run_record(data, args.background))
            asyncio.run(serve(first))
            if not os.path.exists(restart_file) or os.path.exists(stop_file):
                break
            # Restart: the same run again in this process (the settings read anew), its window kept.
            os.remove(restart_file)
            run_by = runners.Runner("standalone", stop=lambda: request(stop_file),
                                    restart=lambda: request(restart_file), remove=remove)
            logging.getLogger("opendmt3.server").info("starting again: asked to restart")
            kept, first = settings(data), False
            # Asked from the admin pages, no command looked first: a port another program holds now ends the run here
            # with one line, never halfway through the start (the ports this run had are free again by now).
            run = server_args_namespace(data)
            for _ in range(10):
                taken = held_elsewhere({}, [run.port, run.web_port, run.admin_port])
                if not taken:
                    break
                # A moment for a port this run just let go of to be free to bind again.
                time.sleep(0.2)
            if taken:
                logging.getLogger("opendmt3.server").error(
                    "port %d is taken by another program: the server stops (stop that program, then %s start)",
                    taken, PROG)
                break
    except KeyboardInterrupt:
        pass
    finally:
        for name in (RUNNING, STOP, RESTART):
            with contextlib.suppress(FileNotFoundError):
                os.remove(os.path.join(data, name))
        logging.getLogger("opendmt3.server").info("stopped")
    if asked["delete_data"]:
        # The log is in the data folder: closed first, so the folder can go (Windows keeps an open file). Each handler
        # taken off before it is closed, and no record made after: a file handler that is closed opens its file again
        # for the next record, which a thread still ending could write.
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            handler.close()
        logging.disable(logging.CRITICAL)
        logging.shutdown()
        if args.background:
            # Started in the background, this run writes what it prints to data/logs/output.txt (cmd_start), a file
            # Windows will not delete while it is open: its output goes nowhere from here, so the folder can go.
            release_output()
        kept_copy = server_cli.remove_data(data)
        say("The server's data in %s is deleted; its last backup is %s" % (data, kept_copy))
        if os.name == "nt":
            say("Its firewall rules stay: %s firewall --remove takes them out." % PROG)
    return 0


def release_output():
    """This process's standard output and error let go of the file they write to: the null device in its place."""
    for stream in (sys.stdout, sys.stderr):
        # What was written so far reaches the file before it is let go.
        with contextlib.suppress(Exception):
            stream.flush()
    nowhere = os.open(os.devnull, os.O_WRONLY)
    try:
        # Each descriptor's file closed as the null device takes its place (on Windows its handle too).
        os.dup2(nowhere, 1)
        os.dup2(nowhere, 2)
    finally:
        os.close(nowhere)


def server_args_namespace(data):
    """The server's own parsed arguments for this run (its parser's defaults, then the kept settings)."""
    return server_cli.parser().parse_args(server_args(data))


def self_command():
    """How this program starts itself again: the Windows package's program, or this Python with this module."""
    if frozen():
        return [sys.executable]
    return [sys.executable, "-m", "opendmt3.server.standalone"]


def cmd_start(args):
    """The server in the background, with no window: its log is data/logs/server.log, and stop stops it."""
    data = os.path.abspath(args.data)
    os.makedirs(os.path.join(data, LOGS), exist_ok=True)
    record = running(data)
    if record:
        say("The server already runs (process %s)." % record["pid"])
        return 0
    # What the server prints outside its log (a crash before it could log one), kept beside it; each start begins it
    # again, so it never grows past one run.
    out = open(os.path.join(data, LOGS, "output.txt"), "w", encoding="utf-8")
    command = self_command() + ["--data", data, "run", "--background"]
    options = {"stdin": subprocess.DEVNULL, "stdout": out, "stderr": subprocess.STDOUT, "close_fds": True}
    if os.name == "nt":
        options["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    else:
        # A session of its own: closing the terminal that started it does not end it.
        options["start_new_session"] = True
    process = subprocess.Popen(command, **options)
    out.close()
    port = settings(data)["web_port"]
    for _ in range(300):
        if health(port, timeout=0.5) and running(data):
            show_banner(data)
            say("It runs in the background (process %d): %s stop stops it, %s logs shows its log."
                % (process.pid, PROG, PROG))
            return 0
        if process.poll() is not None:
            break
        time.sleep(0.1)
    say("The server did not start:")
    with open(os.path.join(data, LOGS, "output.txt"), encoding="utf-8", errors="replace") as f:
        say(f.read().strip()[-2000:])
    return 1


def end_process(pid):
    """The process ended at once: the last resort of stop, after its request went unanswered."""
    import signal
    with contextlib.suppress(OSError):
        # On Windows os.kill ends the process (TerminateProcess); elsewhere SIGKILL.
        os.kill(pid, signal.SIGTERM if os.name == "nt" else signal.SIGKILL)


def cmd_stop(args):
    """Ask the running server to end, wait for it, and end its process only when it does not by itself."""
    data = os.path.abspath(args.data)
    record = running(data)
    if not record:
        say("The server is not running.")
        return 0
    pid = int(record["pid"])
    with open(os.path.join(data, STOP), "w", encoding="utf-8") as f:
        f.write("%d\n" % pid)
    deadline = time.monotonic() + STOP_SECONDS
    while time.monotonic() < deadline:
        if not alive(pid):
            say("The server stopped.")
            return 0
        time.sleep(0.2)
    end_process(pid)
    for name in (RUNNING, STOP):
        with contextlib.suppress(FileNotFoundError):
            os.remove(os.path.join(data, name))
    say("The server did not stop within %d seconds; its process was ended." % STOP_SECONDS)
    return 0


def cmd_restart(args):
    """Ask the running server to end and run again in its own process (its window, or none, kept); wait until it
    answers again. Not running: started in the background, as start does."""
    data = os.path.abspath(args.data)
    record = running(data)
    if not record:
        say("The server was not running; starting it.")
        return cmd_start(args)
    taken = held_elsewhere(record, next_ports(data, record))
    if taken:
        # Asked before the server is: it runs on as it is, and the line says what to do (a restart would stop it
        # halfway, the port not its to take).
        raise Refused("port %d is taken by another program: stop it first (Caddy, when it still has its settings "
                      "from before expose --off), then %s restart" % (taken, PROG))
    with open(os.path.join(data, RESTART), "w", encoding="utf-8") as f:
        f.write("%d\n" % int(record["pid"]))
    deadline = time.monotonic() + STOP_SECONDS + 30
    while time.monotonic() < deadline:
        now = running(data)
        if not alive(int(record["pid"])):
            say("The server stopped instead of starting again; %s logs shows why." % PROG)
            return 1
        if now and now.get("started") != record.get("started") and health(int(now["web_port"]), timeout=0.5):
            say("The server runs again (process %s)." % now["pid"])
            return 0
        time.sleep(0.2)
    say("The server did not answer again within %d seconds; %s logs shows why." % (STOP_SECONDS + 30, PROG))
    return 1


def run_record(data, background):
    """What the running server keeps of itself in its data folder (RUNNING): its process, its ports (the admin
    listener's as this run has it, which a restart must not take for another program's), when it started, how, and
    its version."""
    kept = settings(data)
    return {"pid": os.getpid(), "game_port": kept["game_port"], "web_port": kept["web_port"],
            "admin_port": server_args_namespace(data).admin_port,
            # The admin port this process takes when the folder keeps none (its environment's, else the usual): a
            # restart asked from another window cannot see this process's environment.
            "admin_default": int(os.environ.get("OPENDMT3_ADMIN_PORT") or ADMIN_PORT), "started": time.time(),
            "background": bool(background), "version": __version__}


def next_ports(data, record):
    """The ports the next run of the running server listens on (its record's), as this folder's settings give them
    now: the game's and the site's as kept; the admin listener's as kept (or behind Caddy), else the running process's
    own default (its environment's, which another window cannot see)."""
    kept = settings(data)
    if read_json(os.path.join(data, SETTINGS), {}).get("admin_port") is not None or behind_caddy(kept):
        admin = admin_listens(kept)[1]
    else:
        admin = int(record.get("admin_default") or ADMIN_PORT)
    return [kept["game_port"], kept["web_port"], admin]


def held_elsewhere(record, ports):
    """The first of these ports that another program holds now, or None: the running server's own (its record's) are
    its own, freed as it restarts. Caddy still on the admin port after expose --off is one."""
    own = {int(record.get(name) or 0) for name in ("game_port", "web_port", "admin_port")}
    for port in ports:
        if port and port not in own and not port_free(port):
            return port
    return None


def cmd_status(args):
    """Whether the server runs, its health, and where players and the owner reach it. 0 when it runs and answers."""
    data = os.path.abspath(args.data)
    record = running(data)
    if not record:
        say("The server is not running (data in %s). %s start starts it." % (data, PROG))
        return 3
    answer = health(int(record["web_port"]))
    say("The server runs (process %s%s), version %s." % (record["pid"], ", in the background" if record.get(
        "background") else "", (answer or {}).get("version", "?")))
    say("Health: %s" % ("ok" if answer and answer.get("ok") else "the site does not answer"))
    say("Players: %s" % players_address(data))
    say("On this PC: http://127.0.0.1:%s/" % record["web_port"])
    say(admin_line(data))
    return 0 if answer and answer.get("ok") else 1


def cmd_logs(args):
    """The last lines of the server's log."""
    path = os.path.join(os.path.abspath(args.data), LOGS, "server.log")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        say("No log yet (%s)." % path)
        return 0
    for line in lines[-args.tail:]:
        say(line)
    return 0


# ---------------------------------------------------------------------------------------------- setup

def cmd_setup(args):
    """The settings and the first things a server needs: the players' address, the ports, the song list from the
    client data, the installer to hand out, the owner's account. Each only when given; the rest stays as it is."""
    data = os.path.abspath(args.data)
    os.makedirs(os.path.join(data, "downloads"), exist_ok=True)
    # As they were: what a refused port goes back to, and what Caddy's settings and the firewall follow from.
    was, raw = settings(data), read_json(os.path.join(data, SETTINGS), {})
    if args.game_port or args.web_port:
        old_web = settings(data)["web_port"]
        # Only the ones given: the other one stays as it was kept.
        keep(data, **{name: port for name, port in (("game_port", args.game_port), ("web_port", args.web_port))
                      if port})
        new_web = settings(data)["web_port"]
        if new_web != old_web:
            # The players' address follows the site to its new port (an http address on the old one; one through a
            # proxy stays), and so does the one kept from before expose, for expose --off to give back.
            kept = read_json(os.path.join(data, SETTINGS), {})
            keep(data, **{name: edge.moved_address(kept[name], old_web, new_web) for name in ("site_address",
                                                                                        BEFORE_EXPOSE)
                          if kept.get(name)})
    # The admin port given, 0 among them (the admin pages off).
    admin_given = args.admin_port is not None
    if admin_given or args.admin_host:
        port = args.admin_port if admin_given else was["admin_port"]
        # The server's own defaults are kept as none, so a run passes nothing for them.
        keep(data, **{"admin_port": None if port == ADMIN_PORT else port,
                      "admin_host": None if (args.admin_host or was["admin_host"]) == ADMIN_HOST
                      else args.admin_host or was["admin_host"]})
    now = settings(data)
    if any((args.game_port, args.web_port, admin_given, args.admin_host)) and len(set(own_ports(now))) != len(
            own_ports(now)):
        # Undone, all of it: two parts on one port would leave one of them unreachable.
        write_json(os.path.join(data, SETTINGS), raw)
        raise Refused("each part needs a port of its own: %s" % ", ".join(str(port) for port in own_ports(now)))
    if args.game_port or args.web_port:
        say("ports: the game %d, the site %d" % (now["game_port"], now["web_port"]))
    if admin_given or args.admin_host:
        say("the admin pages: off" if not now["admin_port"] else "the admin pages: port %d, %s" % (
            now["admin_port"], "other PCs on the network too" if admin_opened(now) else "this PC only"))
    if now["proxy"] and now["edge"] and (now["web_port"], now["admin_port"]) != (was["web_port"], was["admin_port"]):
        # Behind Caddy, its settings follow the ports: the site's, the admin pages' and the listener behind them.
        say("Caddy's settings, for the new ports: %s (Caddy reads them when it starts)" % write_caddyfile(data))
    # Windows' firewall follows the admin port's reach: its rule in when other PCs reach it, out when none do.
    follow_admin_rule(data, was)
    if args.address:
        address = site_address(args.address, settings(data)["web_port"])
        keep(data, site_address=address)
        say("the players' address: %s" % address)
    if args.game:
        # The song list (with its jackets and the DJ cards), read now; a folder is kept so the admin's Song list tab
        # can read it again.
        code = server_cli.main(["--data", data, "--catalog", args.game, "--setup-only"])
        if code:
            return code
        if os.path.isdir(args.game):
            keep(data, game=os.path.abspath(args.game))
    if args.installer:
        if not os.path.isfile(args.installer):
            raise Refused("no installer at %s" % args.installer)
        from opendmt3.server.services import downloads as handed
        # Under its release name when it has one (the newest version there is handed out), else the stored name, in
        # place of the one before.
        name = os.path.basename(args.installer)
        shutil.copyfile(args.installer, os.path.join(data, "downloads", name if handed.RELEASED.match(name)
                                                     else INSTALLER))
        say("the Download page hands out %s" % os.path.basename(args.installer))
    if not args.admin and first_account_needed(data) and at_terminal():
        # No account yet, and a person at this terminal: the owner's account made here, so a PC with no screen of its
        # own needs no browser (the admin pages' first-run page answers this PC alone).
        say("The owner's account, with the admin pages (Enter takes what is in brackets):")
        args.admin, args.password = ask_owner()
    if args.admin:
        if not first_account_needed(data):
            say("accounts are there already: no first account is made (%s add-player makes one)" % PROG)
        else:
            argv = ["--data", data, "--add-player", args.admin, "--admin"]
            code = server_cli.main(argv + (["--password", args.password] if args.password else []))
            if code:
                return code
    if not (args.game or settings(data)["game"]):
        say("The song list: %s catalog PATH reads it from your client data (a folder or an archive), or the admin "
            "pages' Song list." % PROG)
    if first_account_needed(data):
        say("The owner's account: %s setup --admin ID makes it here (its password printed), or start the server and "
            "open the admin pages, %s, on this PC." % (PROG, admin_here(data) or "http://127.0.0.1:%d/" % settings(
                data)["web_port"]))
    return 0


def ask_owner():
    """The owner's ID and password typed at this terminal, by the server's own rules: each refusal said in the server's
    words and asked again, the password typed twice to catch a slip (empty: one is made and printed)."""
    from opendmt3.server.services import accounts
    while True:
        login_id = (input("  ID [%s]: " % OWNER).strip() or OWNER).upper()
        try:
            accounts.check_id(login_id)
            break
        except accounts.AccountError as e:
            say("  %s" % e)
    while True:
        password = getpass.getpass("  password (6 to 16 letters or digits; empty: one is made): ").strip()
        if not password:
            return login_id, None
        try:
            accounts.check_password(password)
        except accounts.AccountError as e:
            say("  %s" % e)
            continue
        if getpass.getpass("  the same password again: ").strip() == password:
            return login_id, password
        say("  the two passwords differ")


def at_terminal():
    """True when a person types at this program (its input and output a terminal), not a script."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def cmd_catalog(args):
    """The song list from client data, an archive or a saved song list; --save makes a song list for a server
    elsewhere instead."""
    if args.save:
        return server_cli.main(["--catalog", args.path, "--save", args.save])
    data = os.path.abspath(args.data)
    code = server_cli.main(["--data", data, "--catalog", args.path, "--setup-only"])
    if code == 0 and running(data):
        say("The site shows the new song list now; the game takes it at its next login.")
    return code


def cmd_passthrough(args):
    """add-player, backup, backups, restore: the server's own command line on this data folder."""
    data = os.path.abspath(args.data)
    if args.command == "add-player":
        argv = ["--add-player", args.id] + (["--password", args.password] if args.password else []) + (
            ["--dj", args.dj] if args.dj else []) + (["--admin"] if args.admin else [])
    elif args.command == "restore":
        argv = ["--restore", args.name]
    else:
        argv = ["--" + args.command]
    return server_cli.main(["--data", data] + argv)


# ---------------------------------------------------------------------------------------------- invite, firewall

def cmd_invite(args):
    """The address players open, and its QR code to scan from this screen."""
    address = players_address(os.path.abspath(args.data))
    say("Players open %s" % address)
    if "//127." in address or "//localhost" in address:
        say("(that is this PC's own address: %s setup --address gives the one other PCs reach)" % PROG)
    say(qr.terminal(address))
    return 0


def firewall_commands(ports, remove=False, public=False):
    """The netsh commands that open these TCP ports in Windows' firewall (or take the rules out again): one rule a
    port, named so that a second run finds and replaces it. Private and domain networks; public ones too when asked."""
    commands = []
    for port in ports:
        name = RULE % port
        # The rule of that name first goes, so a run again never leaves two.
        commands.append(["netsh", "advfirewall", "firewall", "delete", "rule", "name=" + name])
        if not remove:
            commands.append(["netsh", "advfirewall", "firewall", "add", "rule", "name=" + name, "dir=in",
                             "action=allow", "protocol=TCP", "localport=%d" % port,
                             "profile=" + ("private,domain,public" if public else "private,domain")])
    return commands


def on_windows():
    """True on Windows, where the firewall's rules are this program's to make and take out (netsh)."""
    return os.name == "nt"


def firewall_ports(data):
    """The ports the firewall opens for this data folder's server: the game's, and the site's, or Caddy's 80 and 443
    while the site is behind it (expose)."""
    kept = settings(data)
    # The admin pages' port only while other PCs reach it (opened to the network, or Caddy's HTTPS for them with
    # expose --admin-public): on this PC alone it needs no rule, nor does the admin listener behind Caddy.
    return [kept["game_port"]] + ([80, 443] if kept["proxy"] else [kept["web_port"]]) + (
        [kept["admin_port"]] if admin_reached(kept) else [])


def firewall_rules(ports):
    """Of these ports, those whose rule (RULE) Windows' firewall has: netsh lists a rule by its name without an
    administrator, and answers 1 when no rule has it."""
    found = []
    for port in ports:
        done = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule", "name=" + RULE % port],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if done.returncode == 0:
            found.append(port)
    return found


def firewall_follow(data, close, open_):
    """Windows' firewall after the admin pages' reach changed: the rules of `close` taken out (those there are) and
    those of `open_` added, each with the administrator's question the firewall command asks. A no (or a failure)
    leaves things as they were, said as such, and never stops the setting: the server runs with it either way."""
    there = firewall_rules(close) if close else []
    for ports, remove in ((there, True), (open_, False)):
        if not ports:
            continue
        try:
            left = cmd_firewall(argparse.Namespace(data=data, remove=remove, public=False, print=False,
                                                   ports=",".join(str(p) for p in ports)))
        except Refused:
            left = 1
        if left:
            say("Windows' firewall %s TCP %s: %s firewall%s does it later." % (
                "still opens" if remove else "does not open", ", ".join(str(p) for p in ports), PROG,
                " --remove" if remove else ""))


def follow_admin_rule(data, was):
    """Windows' firewall after the admin port's reach or number changed (setup --admin-host or --admin-port, expose
    --admin-public, without it, or --off): the rule out for the port other PCs reached, in for the one they reach now,
    as firewall_follow asks for them. Nothing elsewhere: the firewall command prints its commands there."""
    now = settings(data)
    if on_windows() and (admin_reached(now), now["admin_port"]) != (admin_reached(was), was["admin_port"]):
        firewall_follow(data, [was["admin_port"]] if admin_reached(was) else [],
                        [now["admin_port"]] if admin_reached(now) else [])


def is_admin():
    """True when this Windows process may change the firewall (it runs as an administrator)."""
    import ctypes
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def elevated(argv):
    """This program again with argv, as an administrator (Windows asks the person at the PC), waited for; its exit
    code, or None when the person said no."""
    import ctypes
    from ctypes import wintypes

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    command = self_command()
    info = ShellExecuteInfo(cbSize=ctypes.sizeof(ShellExecuteInfo), fMask=0x00000040, lpVerb="runas",
                            lpFile=command[0], lpParameters=subprocess.list2cmdline(command[1:] + argv), nShow=0)
    # SEE_MASK_NOCLOSEPROCESS (0x40): the process handle comes back, to wait for it.
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        return None
    ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
    code = wintypes.DWORD()
    ctypes.windll.kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(info.hProcess)
    return code.value


def cmd_firewall(args):
    """Windows: open the server's two ports in Windows' firewall (Windows asks for an administrator's yes). Elsewhere:
    the commands for the usual firewalls, to run with sudo."""
    data = os.path.abspath(args.data)
    # The ports given (remove passes the ones its data folder kept, before the folder goes), else this data folder's.
    ports = [int(p) for p in args.ports.split(",")] if getattr(args, "ports", None) else firewall_ports(data)
    if not on_windows() or args.print:
        if on_windows():
            for command in firewall_commands(ports, args.remove, args.public):
                say(subprocess.list2cmdline(command))
            return 0
        say("ufw (Ubuntu, Debian):")
        for port in ports:
            say("  sudo ufw %s %d/tcp" % ("delete allow" if args.remove else "allow", port))
        say("firewalld (Fedora, RHEL):")
        for port in ports:
            say("  sudo firewall-cmd --permanent --%s-port=%d/tcp" % ("remove" if args.remove else "add", port))
        say("  sudo firewall-cmd --reload")
        say("macOS asks by itself the first time the server listens: choose Allow.")
        return 0
    if not is_admin():
        # Once more as an administrator, which Windows asks the person at this PC for, on these same ports.
        code = elevated(["--data", data, "firewall", "--ports", ",".join(str(p) for p in ports)] + (
            ["--remove"] if args.remove else []) + (["--public"] if args.public else []))
        if code is None:
            raise Refused("the firewall was not changed: Windows' question was answered no")
        return code
    failed = 0
    for command in firewall_commands(ports, args.remove, args.public):
        done = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        # Deleting a rule that is not there fails, and that is fine; adding one must work.
        if done.returncode and command[3] == "add":
            failed += 1
            say(done.stdout.strip())
    if failed:
        return 1
    say("Windows' firewall %s TCP %s." % ("no longer opens" if args.remove else "opens",
                                         ", ".join(str(p) for p in ports)))
    return 0


# ---------------------------------------------------------------------------------------------- expose

def cmd_expose(args):
    """The site over HTTPS behind Caddy on this PC: the Caddyfile in the data folder, the players' address
    https://NAME/, and the site on this PC only with the proxy's headers believed. With --admin-public the admin pages
    too, at https://NAME:<admin port>/, the admin listener behind Caddy on this PC alone at the next port; without it
    nothing of the admin site is behind Caddy. --off undoes it."""
    data = os.path.abspath(args.data)
    # As it was: what Windows' firewall follows from (the admin port's rule).
    was = settings(data)
    if args.off:
        # The players' address is the one setup kept before expose (none when there was none); the admin pages leave
        # Caddy too, on this PC (or the network, as setup --admin-host keeps them) on their own port again.
        before = read_json(os.path.join(data, SETTINGS), {}).get(BEFORE_EXPOSE)
        keep(data, proxy=None, site_address=before, edge=None, **{BEFORE_EXPOSE: None})
        if before:
            say("The players' address is %s again." % before)
        if behind_caddy(was):
            # Caddy holds the admin port until it stops: the admin listener can have it back only then.
            say("The site is on its own port again for other PCs: stop Caddy (it has port %d), then restart the "
                "server (%s restart)." % (was["admin_port"], PROG))
        else:
            say("The site is on its own port again for other PCs (restart the server: %s restart)." % PROG)
        say(admin_line(data))
        follow_admin_rule(data, was)
        return 0
    if not args.name:
        raise Refused("expose needs the site's name: %s expose dmt3.example.org" % PROG)
    # What expose chose, kept so Caddy's settings can be written again when a port moves (setup).
    choice = {"email": args.email, "ca": "staging" if args.staging else args.ca, "local_ca": args.local_ca or None,
              "admin_public": args.admin_public or None}
    if args.admin_public and not was["admin_port"]:
        # Off (setup --admin-port 0): nothing to put behind Caddy.
        raise Refused("the admin pages are off: %s setup --admin-port %d turns them on" % (PROG, ADMIN_PORT))
    # The admin port is Caddy's then, and the admin listener moves to the next one: neither may be another part's.
    would = dict(was, proxy="127.0.0.1", admin_public=bool(args.admin_public))
    if len(set(own_ports(would))) != len(own_ports(would)) or own_ports(would)[2] > 65535:
        raise Refused("each part needs a port of its own: %s" % ", ".join(str(port) for port in own_ports(would)))
    try:
        # Checked before anything is kept: a name no authority signs, or an authority with the local one.
        edge.caddyfile(args.name, "127.0.0.1:%d" % was["web_port"], email=choice["email"], ca=choice["ca"],
                       local_ca=args.local_ca)
        name = edge.check_name(args.name, args.local_ca)
    except edge.EdgeError as e:
        raise Refused(str(e))
    os.makedirs(data, exist_ok=True)
    # The address setup kept is kept aside, once (a second expose keeps the first one's), for expose --off.
    aside = {BEFORE_EXPOSE: was["site_address"]} if not was["proxy"] and was["site_address"] else {}
    keep(data, proxy="127.0.0.1", site_address="https://%s/" % name,
         edge={key: value for key, value in dict(choice, name=name).items() if value}, **aside)
    path = write_caddyfile(data)
    now = settings(data)
    say("The players' address: https://%s/" % name)
    say(admin_line(data))
    say("Caddy's settings: %s" % path)
    server = "Restart the server (%s stop, then %s start): the site then answers through Caddy only." % (PROG, PROG)
    caddy = ("Run Caddy (https://caddyserver.com/download) beside it: caddy run --config \"%s\" (caddy reload, with the "
             "same --config, while it runs)" % path)
    if behind_caddy(was) and not behind_caddy(now):
        # The admin pages leave Caddy: Caddy lets go of their port first, or the admin listener cannot have it back.
        steps = [caddy + ", so it lets go of port %d" % was["admin_port"], server]
    else:
        # The server first: behind Caddy the admin listener leaves the admin port for Caddy to take.
        steps = [server, caddy]
    say("Next:")
    for number, step in enumerate(steps, 1):
        say("  %d. %s" % (number, step))
    # The admin pages' HTTPS port too, only when they are behind Caddy (--admin-public), in ./dmt3's words.
    admin = " and TCP %d (the admin pages, HTTPS)" % now["admin_port"] if behind_caddy(now) else ""
    say("  3. On the router, forward TCP 80 and 443 (Caddy)%s and %d (the game) to this PC; %s firewall opens them "
        "here." % (admin, now["game_port"], PROG))
    follow_admin_rule(data, was)
    return 0


def write_caddyfile(data):
    """Caddy's settings in the data folder from what expose chose (the name, the authority, the admin pages too) and
    the ports as they are now: the site's for the site, the admin port and the listener behind it for the admin
    pages. The file's path."""
    kept = settings(data)
    choice = kept["edge"]
    admin = (kept["admin_port"], "127.0.0.1:%d" % admin_listens(kept)[1]) if behind_caddy(kept) else None
    text = edge.caddyfile(choice["name"], "127.0.0.1:%d" % kept["web_port"], email=choice.get("email"),
                          ca=choice.get("ca"), local_ca=bool(choice.get("local_ca")), admin=admin)
    path = os.path.join(data, "Caddyfile")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


# ---------------------------------------------------------------------------------------------- repair, remove

# The Windows package's list of its own files with their SHA-256 (server.sh writes it), which repair checks.
MANIFEST = "files.sha256"


def damaged(folder):
    """The package's files that are missing or changed against its list, as paths relative to the folder; None when
    the folder has no list (a copy of the repository)."""
    import hashlib
    try:
        with open(os.path.join(folder, MANIFEST), encoding="utf-8") as f:
            listed = [line.rstrip("\r\n").split("  ", 1) for line in f if line.strip()]
    except OSError:
        return None
    bad = []
    for digest, name in listed:
        path = os.path.join(folder, *name.split("/"))
        try:
            with open(path, "rb") as f:
                ok = hashlib.sha256(f.read()).hexdigest() == digest
        except OSError:
            ok = False
        if not ok:
            bad.append(name)
    return bad


def cmd_repair(args):
    """The program's files against the package's list (the Windows package), the libraries the server needs (a copy
    run with Python), and the data folder: what is wrong, and the one thing that fixes it. 0 when nothing is."""
    folder = package_folder()
    bad = damaged(folder)
    problems = 0
    if bad is None:
        # Run with Python: the site's libraries are what the server needs beside the code.
        missing = []
        for module in ("starlette", "jinja2", "uvicorn", "multipart", "PIL"):
            try:
                __import__(module)
            except ImportError:
                missing.append(module)
        if missing:
            problems += 1
            say("missing libraries: %s (fix: the one-line install again, or pip install -r its list)" % ", ".join(
                missing))
        else:
            say("ok    the server's libraries are there")
    elif bad:
        problems += 1
        say("damaged or missing in %s: %s" % (folder, ", ".join(bad[:10]) + (" and %d more" % (len(bad) - 10)
                                                                           if len(bad) > 10 else "")))
        say("        fix: stop the server, unpack the zip of this version again over this folder (the data folder "
            "stays as it is)")
    else:
        say("ok    the package's files are as they were made")
    data = os.path.abspath(args.data)
    try:
        os.makedirs(data, exist_ok=True)
        probe = os.path.join(data, ".write-test")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        say("ok    the data folder %s can be written" % data)
    except OSError as e:
        problems += 1
        say("the data folder %s cannot be written (%s)" % (data, e))
    # The admin listener's port as the run will have it, beside the game's and the site's.
    admin = server_args_namespace(data).admin_port
    for port in [settings(data)["game_port"], settings(data)["web_port"]] + ([admin] if admin else []):
        if running(data) or port_free(port):
            say("ok    port %d is free or the server's" % port)
        else:
            problems += 1
            say("port %d is taken by another program (fix: stop it, or %s setup --game-port/--web-port/--admin-port)"
                % (port, PROG))
    return 1 if problems else 0


def cmd_remove(args):
    """Stop the server; with --delete-data delete its data folder too, after a backup kept beside it (its owner's
    alone); then, on Windows, take out the firewall rules there are (Windows asks for an administrator only when one
    is there, and a no leaves them, said as such: the data never waits on that question). The package itself is a
    folder: deleting it removes the rest (nothing else was put on this PC)."""
    data = os.path.abspath(args.data)
    if args.delete_data and not args.yes:
        if not sys.stdin.isatty() or input("Delete the server's data in %s (accounts, plays, backups)? A backup is "
                                           "kept beside it first. [y/N] " % data).strip().lower() not in ("y", "yes"):
            say("Nothing was removed.")
            return 1
    cmd_stop(args)
    # The ports the firewall's rules may be for, read while the data folder (its settings) is still there: the game's,
    # the site's, and Caddy's 80 and 443 (an expose before, or now). Only the rules there are are taken out.
    kept = settings(data)
    ports = sorted({kept["game_port"], kept["web_port"], kept["admin_port"], 80, 443})
    if args.delete_data and os.path.isdir(data):
        kept = None
        database = os.path.join(data, "openDMT3.sqlite")
        if os.path.exists(database):
            from opendmt3.server import db
            from opendmt3.server.services import backups
            db.connect(database).close()
            name = backups.make(database, data, "manual")
            kept = os.path.join(os.path.dirname(data), "opendmt3-backup-%s.sqlite" % time.strftime("%Y%m%d-%H%M%S"))
            shutil.copyfile(os.path.join(data, "backups", name), kept)
            # Card numbers and password hashes are in it: its owner's alone, as the database is.
            os.chmod(kept, 0o600)
        shutil.rmtree(data)
        if kept:
            say("the last backup, kept: %s" % kept)
        say("The server's data is deleted.")
    if on_windows():
        # The firewall's rules last, and only those there are (Windows asks for an administrator only then): the data
        # never waits on the question, and a no leaves the rules, said as such.
        there = firewall_rules(ports)
        if there:
            try:
                left = cmd_firewall(argparse.Namespace(data=data, remove=True, public=False, print=False,
                                                       ports=",".join(str(p) for p in there)))
            except Refused:
                left = 1
            if left:
                say("Its firewall rules stay (TCP %s): %s firewall --remove takes them out."
                    % (", ".join(str(p) for p in there), PROG))
    where = package_folder() if frozen() else "this copy"
    say("The server is stopped%s. To remove it, delete %s." % ("" if args.delete_data else " and its data kept in %s"
                                                               % data, where))
    return 0


# ---------------------------------------------------------------------------------------------- the command line

COMMANDS = [
    ("run", "run the server in this window until it closes (the default)"),
    ("start", "start the server in the background"),
    ("stop", "stop the running server (started by run or start)"),
    ("restart", "stop the running server and run it again where it ran (its window, or the background)"),
    ("status", "whether the server runs, its health and its addresses"),
    ("logs", "the last lines of the server's log"),
    ("setup", "the players' address, the ports, the song list, the installer to hand out, the first account"),
    ("catalog", "import the song list from your client data (a folder or an archive) or a saved song list"),
    ("invite", "the address players open, with its QR code"),
    ("firewall", "open the server's ports in the firewall (Windows asks for an administrator's yes)"),
    ("expose", "the site over HTTPS at a name, behind Caddy on this PC"),
    ("add-player", "make an account; its password is printed"),
    ("repair", "check the program's files, the data folder and the ports, with the fix for each problem"),
    ("remove", "stop the server and take its firewall rules out; --delete-data deletes its data too"),
    ("backup", "back the database up now"),
    ("backups", "list the backups"),
    ("restore", "put the database back to a backup (the current one is backed up first)"),
]


def parser():
    p = argparse.ArgumentParser(prog=PROG, description="The openDMT3 server (the game and the site) on this PC.")
    p.add_argument("--version", action="version", version="openDMT3 server " + __version__)
    p.add_argument("--data", default=None, metavar="FOLDER",
                   help="the data folder (the database, backups, the installer to hand out, the settings); by "
                        "default data beside the program, OPENDMT3_DATA, or ./data")
    sub = p.add_subparsers(dest="command", metavar="<command>")
    c = {name: sub.add_parser(name, help=text, description=text) for name, text in COMMANDS}
    c["run"].add_argument("--background", action="store_true", help=argparse.SUPPRESS)
    c["run"].add_argument("--no-browser", action="store_true",
                          help="do not open the owner's first-run page in the browser on the first start")
    c["logs"].add_argument("-n", "--tail", type=int, default=100, help="how many of the last lines (100)")
    c["setup"].add_argument("--address", help="the address players reach this PC at (192.168.0.5, a name, or a "
                                              "whole https://... address)")
    c["setup"].add_argument("--game", metavar="PATH", help="import the song list from your client data (a folder "
                                                           "or an archive) or a saved song list")
    c["setup"].add_argument("--installer", metavar="FILE", help="the launcher's installer for the Download page")
    c["setup"].add_argument("--admin", metavar="ID", help="make the first account, with the admin pages")
    c["setup"].add_argument("--password", help="its password (made and printed when not given)")
    c["setup"].add_argument("--game-port", type=int, help="the game's port (4725)")
    c["setup"].add_argument("--web-port", type=int, help="the site's port (4730)")
    c["setup"].add_argument("--admin-port", type=int, help="the admin pages' port (4731; 0 turns them off)")
    c["setup"].add_argument("--admin-host", metavar="ADDRESS",
                            help="the address the admin pages listen on: 127.0.0.1, this PC only (the usual), or "
                                 "0.0.0.0, other PCs on the network too (Windows' firewall then opens their port)")
    c["catalog"].add_argument("path", metavar="PATH", help="your client data's folder, an archive holding it, or a "
                                                           "saved song list")
    c["catalog"].add_argument("--save", metavar="FILE", help="save the song list into FILE instead of importing it")
    c["firewall"].add_argument("--remove", action="store_true", help="take the rules out again")
    c["firewall"].add_argument("--public", action="store_true", help="on public networks too (Windows)")
    c["firewall"].add_argument("--print", action="store_true", help="print the commands instead of running them")
    # The ports, as remove passes them to the program asked as an administrator (its data folder may be gone then).
    c["firewall"].add_argument("--ports", help=argparse.SUPPRESS)
    c["expose"].add_argument("name", nargs="?", help="the site's name (dmt3.example.org): it must lead to this PC")
    c["expose"].add_argument("--email", help="the address Let's Encrypt writes to about the certificate")
    choice = c["expose"].add_mutually_exclusive_group()
    choice.add_argument("--staging", action="store_true", help="Let's Encrypt's staging authority (to try it out)")
    choice.add_argument("--ca", metavar="URL", help="another ACME authority's directory")
    choice.add_argument("--local-ca", action="store_true",
                        help="Caddy's own authority, for a closed network (players trust its root once)")
    c["expose"].add_argument("--admin-public", action="store_true",
                             help="the admin pages too, over HTTPS at https://NAME:4731/ (the admin port) through Caddy")
    c["expose"].add_argument("--off", action="store_true", help="back to the site on its own port")
    c["add-player"].add_argument("id", help="the account's ID")
    c["add-player"].add_argument("--password", help="its password (made and printed when not given)")
    c["add-player"].add_argument("--dj", metavar="NAME", help="its DJ name (the ID when not given)")
    c["add-player"].add_argument("--admin", action="store_true", help="with the admin pages")
    c["restore"].add_argument("name", help="a backup's name, as backups lists it")
    c["remove"].add_argument("--delete-data", action="store_true",
                             help="delete the data folder too, after a backup kept beside it")
    c["remove"].add_argument("--yes", action="store_true", help="do not ask before --delete-data")
    return p


def plain_output():
    """Output to a file or a pipe in UTF-8 (Windows would write its own code page there, which has no block letters
    for the QR code); a console keeps its own (Python writes Unicode to it directly)."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure") and not stream.isatty():
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv=None):
    plain_output()
    p = parser()
    args = p.parse_args(argv)
    args.data = args.data or default_data()
    if not args.command:
        # The program alone (a double click on opendmt3-server.exe), or with --data only: the server, here.
        args = p.parse_args(list(sys.argv[1:] if argv is None else argv) + ["run"])
        args.data = args.data or default_data()
    jobs = {"run": cmd_run, "start": cmd_start, "stop": cmd_stop, "restart": cmd_restart, "status": cmd_status, "logs": cmd_logs,
            "setup": cmd_setup, "catalog": cmd_catalog, "invite": cmd_invite, "firewall": cmd_firewall,
            "expose": cmd_expose, "repair": cmd_repair, "remove": cmd_remove}
    try:
        return jobs.get(args.command, cmd_passthrough)(args)
    except Refused as e:
        print("%s: %s" % (PROG, e), file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
