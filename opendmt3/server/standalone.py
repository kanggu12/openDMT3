"""The server on a PC of its own, without Docker or the launcher: the Windows server package's opendmt3-server.exe,
and the same commands with Python on Linux or macOS (python -m opendmt3.server.standalone, or the opendmt3-server
command the one-line install puts on PATH).

    opendmt3-server                  run here until this window closes (Ctrl+C, or opendmt3-server stop elsewhere)
    opendmt3-server start | stop | status | logs
    opendmt3-server setup [--address A] [--game PATH] [--installer FILE] [--admin ID [--password P]]
    opendmt3-server invite | firewall | expose NAME | add-player ID | backup | backups | restore NAME | catalog PATH

Every command works on one data folder: beside the program in the Windows package (data\\), else --data, or
OPENDMT3_DATA, else ./data. Whatever starts the server, run or start, its stop is this same program's stop: the
running server watches its data folder for the request and ends itself (the site finishes its requests, the database
is closed), so stop works from any window, and a server started in the background has no window to close.
The settings a run starts with (the players' address, the ports, HTTPS behind a proxy) are kept in settings.json in
the data folder: setup and expose write them, run reads them. The rest is the server's own command line
(python -m opendmt3.server), run in this same process.
"""

import argparse
import asyncio
import contextlib
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
# In the data folder: the running server's record (its process and ports), the request to stop it, the settings a run
# starts with, and the log folder.
RUNNING, STOP, SETTINGS, LOGS = "server-running.json", "server-stop.request", "settings.json", "logs"
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
            "proxy": kept.get("proxy"), "webhook": kept.get("webhook")}


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
    """The launcher's installer the Windows package brings, into an empty downloads folder: the site's Download page
    then hands it out from the first start. One the owner put there is never replaced."""
    folder = os.path.join(package_folder(), BUNDLED_INSTALLER)
    downloads = os.path.join(data, "downloads")
    try:
        brought = sorted(n for n in os.listdir(folder) if n.lower().endswith(".exe"))
    except OSError:
        return None
    os.makedirs(downloads, exist_ok=True)
    if not brought or any(n.lower().endswith(".exe") for n in os.listdir(downloads)):
        return None
    shutil.copyfile(os.path.join(folder, brought[-1]), os.path.join(downloads, INSTALLER))
    return brought[-1]


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
    """The server's banner as the running one printed it (server/banner.py), for start, whose server prints its own into
    its log folder."""
    from opendmt3.server import banner
    kept = settings(data)
    banner.show(__version__, banner.rows(players_address(data), "http://127.0.0.1:%d/" % kept["web_port"],
                                         kept["game_port"]),
                ["First start: open http://127.0.0.1:%d/ on this PC to make the owner's account." % kept["web_port"]]
                if first_account_needed(data) else [])


def cmd_run(args):
    """The server in this process until it is stopped: Ctrl+C, the window closed, or a stop request (stop)."""
    data = os.path.abspath(args.data)
    os.makedirs(data, exist_ok=True)
    other = running(data)
    if other and other.get("pid") != os.getpid():
        raise Refused("the server already runs on this data folder (process %s): %s stop stops it"
                      % (other["pid"], PROG))
    kept = settings(data)
    for port in (kept["game_port"], kept["web_port"]):
        if not port_free(port):
            raise Refused("port %d is taken by another program: stop it, or choose other ports with %s setup "
                          "--game-port/--web-port" % (port, PROG))
    log_to(data, console=not args.background)
    brought = hand_out_bundled(data)
    if brought:
        logging.getLogger("opendmt3.server").info("the Download page hands out %s", brought)
    stop_file = os.path.join(data, STOP)
    with contextlib.suppress(FileNotFoundError):
        # A request left from before is for a server long gone.
        os.remove(stop_file)
    write_json(os.path.join(data, RUNNING), {"pid": os.getpid(), "game_port": kept["game_port"],
                                             "web_port": kept["web_port"], "started": int(time.time()),
                                             "background": bool(args.background), "version": __version__})

    async def until_asked():
        # The stop request, looked for twice a second: then the server ends itself as after Ctrl+C.
        while not os.path.exists(stop_file):
            await asyncio.sleep(POLL_SECONDS)

    async def serve():
        # The banner (server/banner.py) comes from the server once its site answers, with how this run stops.
        notes = [] if args.background else [
            "It runs while this window is open. To stop it: close the window, press Ctrl+C, or run %s stop." % PROG]
        task = asyncio.ensure_future(server_cli.serve(server_args_namespace(data), data, until=until_asked,
                                                      notes=notes))
        if not args.background and not args.no_browser and first_account_needed(data):
            for _ in range(100):
                # Asked from a thread: the site answers on this same loop, which must not wait on the question.
                if task.done() or await asyncio.to_thread(health, kept["web_port"], 0.5):
                    break
                await asyncio.sleep(0.1)
            if not task.done():
                # The first start, at the PC: the owner's first-run page, where the owner's account is made.
                import webbrowser
                webbrowser.open("http://127.0.0.1:%d/" % kept["web_port"])
        await task

    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass
    finally:
        for name in (RUNNING, STOP):
            with contextlib.suppress(FileNotFoundError):
                os.remove(os.path.join(data, name))
        logging.getLogger("opendmt3.server").info("stopped")
    return 0


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
    if args.game_port or args.web_port:
        keep(data, game_port=args.game_port or None, web_port=args.web_port or None)
        say("ports: the game %d, the site %d" % (settings(data)["game_port"], settings(data)["web_port"]))
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
        shutil.copyfile(args.installer, os.path.join(data, "downloads", INSTALLER))
        say("the Download page hands out %s" % os.path.basename(args.installer))
    if args.admin:
        if not first_account_needed(data):
            say("accounts are there already: no first account is made (%s add-player makes one)" % PROG)
        else:
            argv = ["--data", data, "--add-player", args.admin, "--admin"]
            code = server_cli.main(argv + (["--password", args.password] if args.password else []))
            if code:
                return code
    if not (args.game or settings(data)["game"]):
        say("The song list: %s catalog PATH reads it from your client data (a folder or an archive), or the site's "
            "Admin, Song list tab." % PROG)
    if first_account_needed(data):
        say("The owner's account: start the server and open http://127.0.0.1:%d/ on this PC." % settings(data)[
            "web_port"])
    return 0


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
    kept = settings(data)
    ports = [kept["game_port"]] + ([] if kept["proxy"] else [kept["web_port"]])
    if kept["proxy"]:
        # Behind the proxy the site is reached on 80 and 443 (Caddy's), not on its own port.
        ports += [80, 443]
    if os.name != "nt" or args.print:
        if os.name == "nt":
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
        # Once more as an administrator, which Windows asks the person at this PC for.
        code = elevated(["--data", data, "firewall"] + (["--remove"] if args.remove else []) + (
            ["--public"] if args.public else []))
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
    https://NAME/, and the site on this PC only with the proxy's headers believed. --off undoes it."""
    data = os.path.abspath(args.data)
    if args.off:
        keep(data, proxy=None, site_address=None)
        say("The site is on its own port again for other PCs (restart the server: %s stop, then %s start)."
            % (PROG, PROG))
        return 0
    if not args.name:
        raise Refused("expose needs the site's name: %s expose dmt3.example.org" % PROG)
    try:
        text = edge.caddyfile(args.name, "127.0.0.1:%d" % settings(data)["web_port"], email=args.email,
                              ca="staging" if args.staging else args.ca, local_ca=args.local_ca)
        name = edge.check_name(args.name, args.local_ca)
    except edge.EdgeError as e:
        raise Refused(str(e))
    os.makedirs(data, exist_ok=True)
    path = os.path.join(data, "Caddyfile")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    keep(data, proxy="127.0.0.1", site_address="https://%s/" % name)
    say("The players' address: https://%s/" % name)
    say("Caddy's settings: %s" % path)
    say("Next:")
    say("  1. Restart the server (%s stop, then %s start): the site then answers through Caddy only." % (PROG, PROG))
    say("  2. Run Caddy (https://caddyserver.com/download) beside it: caddy run --config \"%s\"" % path)
    say("  3. On the router, forward TCP 80 and 443 (Caddy) and %d (the game) to this PC; %s firewall opens them here."
        % (settings(data)["game_port"], PROG))
    return 0


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
    for port in (settings(data)["game_port"], settings(data)["web_port"]):
        if running(data) or port_free(port):
            say("ok    port %d is free or the server's" % port)
        else:
            problems += 1
            say("port %d is taken by another program (fix: stop it, or %s setup --game-port/--web-port)" % (port, PROG))
    return 1 if problems else 0


def cmd_remove(args):
    """Stop the server and take its firewall rules out; with --delete-data delete its data folder too, after a backup
    kept beside it. The package itself is a folder: deleting it removes the rest (nothing else was put on this PC)."""
    data = os.path.abspath(args.data)
    if args.delete_data and not args.yes:
        if not sys.stdin.isatty() or input("Delete the server's data in %s (accounts, plays, backups)? A backup is "
                                           "kept beside it first. [y/N] " % data).strip().lower() not in ("y", "yes"):
            say("Nothing was removed.")
            return 1
    cmd_stop(args)
    if os.name == "nt":
        # The rules firewall made, by their names (Windows asks for an administrator's yes).
        cmd_firewall(argparse.Namespace(data=data, remove=True, public=False, print=False))
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
        shutil.rmtree(data)
        if kept:
            say("the last backup, kept: %s" % kept)
        say("The server's data is deleted.")
    where = package_folder() if frozen() else "this copy"
    say("The server is stopped%s. To remove it, delete %s." % ("" if args.delete_data else " and its data kept in %s"
                                                               % data, where))
    return 0


# ---------------------------------------------------------------------------------------------- the command line

COMMANDS = [
    ("run", "run the server in this window until it closes (the default)"),
    ("start", "start the server in the background"),
    ("stop", "stop the running server (started by run or start)"),
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
    c["catalog"].add_argument("path", metavar="PATH", help="your client data's folder, an archive holding it, or a "
                                                           "saved song list")
    c["catalog"].add_argument("--save", metavar="FILE", help="save the song list into FILE instead of importing it")
    c["firewall"].add_argument("--remove", action="store_true", help="take the rules out again")
    c["firewall"].add_argument("--public", action="store_true", help="on public networks too (Windows)")
    c["firewall"].add_argument("--print", action="store_true", help="print the commands instead of running them")
    c["expose"].add_argument("name", nargs="?", help="the site's name (dmt3.example.org): it must lead to this PC")
    c["expose"].add_argument("--email", help="the address Let's Encrypt writes to about the certificate")
    choice = c["expose"].add_mutually_exclusive_group()
    choice.add_argument("--staging", action="store_true", help="Let's Encrypt's staging authority (to try it out)")
    choice.add_argument("--ca", metavar="URL", help="another ACME authority's directory")
    choice.add_argument("--local-ca", action="store_true",
                        help="Caddy's own authority, for a closed network (players trust its root once)")
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
    jobs = {"run": cmd_run, "start": cmd_start, "stop": cmd_stop, "status": cmd_status, "logs": cmd_logs,
            "setup": cmd_setup, "catalog": cmd_catalog, "invite": cmd_invite, "firewall": cmd_firewall,
            "expose": cmd_expose, "repair": cmd_repair, "remove": cmd_remove}
    try:
        return jobs.get(args.command, cmd_passthrough)(args)
    except Refused as e:
        print("%s: %s" % (PROG, e), file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
