"""Removing openDMT3 from this PC, and the note it leaves when it cannot put everything back.

Every way out ends in Velopack's own uninstall (Update.exe --uninstall). Velopack closes every program in the
install folder, runs the launcher once with --veloapp-uninstall (main._before_uninstall, which calls tidy() here),
then takes away the install folder, the shortcuts that point into it and openDMT3's line in Windows' app list.
Three ways lead there:

- Help's Uninstall asks first, puts the game back while its window still shows what happens, then starts the
  uninstall;
- openDMT3-cmd --uninstall does the same in a terminal;
- Windows' app list starts the uninstall on its own: the hook is all of openDMT3 that runs then.

The uninstall always runs silent: Velopack's own window at the end (a plain "Uninstall Complete" box) never
shows. The launcher's dialogs have said what happens; the app list's line is made the quiet one
(quiet_app_list(), after every install and update).

tidy() does the same work for all three, and doing it twice changes nothing: the game's files go back as they
were, openDMT3's own copies and list leave backup\\, and the desktop shortcut that plays at once and starting
with Windows go. Settings, players and records stay unless the person asked for them to go too (Uninstall's Delete
all, --delete-data): the launcher then writes a token in its own folder and hands the same token to the uninstall it
starts, and the hook deletes them only when the two match. The app list never deletes them, since it
cannot ask, and neither does a variable someone set by hand.

When the game's files cannot be put back (the game is open, a file is locked), a note goes into the game folder's
backup\\, beside the originals, saying which to copy back and which openDMT3 added: afterwards there is no
launcher left to do it.
"""

import logging
import os
import re
import secrets
import stat
import subprocess
import sys

from opendmt3.core import game as g

log = logging.getLogger("opendmt3.launcher")

NOTE = "README-openDMT3.txt"
# Set on the uninstall the launcher starts when the person asked for settings, players and records to go too; its
# value is the token written in TOKEN in the launcher's folder at the same moment.
EVERYTHING = "OPENDMT3_REMOVE_DATA"
TOKEN = "remove-everything"

# What the launcher writes in its own folder (state.config_dir()), and nothing else, is what delete_data() takes,
# file by file and by the names the launcher gives them. Anything else stays, and the folders holding it.
DATA_FILES = ("launcher.json", "update-pending.json", TOKEN)
DATA_PREFIXES = ("launcher.json.broken-", ".launcher-")
# The log and the two before it (main._logging).
LOG_NAME = re.compile(r"^launcher\.log(\.\d+)?$")
# This PC's server (client/hosting.py, server/__main__.py): the database with its journal files and the copies
# made before an upgrade (db.connect), what was read from the game for the site (catalog.json, cards.json, the
# report of the last reading in catalog-read.json, each with its temporary name), the song list's log and the one
# before it, its lock and a file of its unfinished work (catalog.LOG_FILE, LOCK_FILE, STAGING), the maintenance and
# notice settings (services/maintenance.py, notice.py), and the site's sign-in secret. Every *FILE name the server's
# code gives a file is here (tests/client/test_launcher.py checks it).
SERVER_NAME = re.compile(r"^(openDMT3\.sqlite(-wal|-shm|-journal|\.v\d+-\d{8}-\d{6}\.bak)?"
                         r"|(catalog|catalog-read|cards|maintenance|notice)\.json(\.new)?|web\.secret(\.new)?"
                         r"|catalog\.log(\.1)?|\.song-list\.lock|\.song-list-[^\\/]+)$")
# Its folders: the database's backups (server/services/backups.py, with a copy cut short), the song discs and the DJ
# card's pictures read from the game (server/services/catalog.py, server/services/cards.py: one folder for each kind).
BACKUP_NAME = re.compile(r"^openDMT3-\d{8}-\d{6}-(daily|manual|restore)\.sqlite(\.part)?$")
PICTURE_NAME = re.compile(r"^\d+\.png(\.new)?$")
# Folders the server makes for files people put there (installers to hand out, updates): only taken when empty.
SERVER_EMPTY = ("downloads", "updates")

WORDS = {
    "en": ("openDMT3 was removed while these files in this game folder were still as openDMT3 left them.",
           "To put the game back as it was, close the game, then:",
           "copy backup\\{path} back over {path}",
           "delete {path} (openDMT3 added it)",
           "Then this backup folder can go too."),
    "ko": ("openDMT3를 지울 때 이 게임 폴더의 아래 파일이 openDMT3가 바꾼 그대로였습니다.",
           "게임을 원래대로 돌리려면 게임을 닫은 뒤:",
           "backup\\{path} 를 {path} 자리에 도로 복사",
           "{path} 지우기(openDMT3가 더한 파일)",
           "그다음 이 backup 폴더도 지워도 됩니다."),
}


def note(game, kept, changed, language="en"):
    """Write the note for the changed files (keys of kept.files) into backup\\; returns its path."""
    head, how, copy, delete, tail = WORDS.get(language, WORDS["en"])
    lines = [head, "", how, ""]
    for key in changed:
        path = key.replace("/", "\\")
        lines.append("  - " + (copy if kept.files[key]["existed"] else delete).format(path=path))
    lines += ["", tail, ""]
    os.makedirs(kept.dir, exist_ok=True)
    target = os.path.join(kept.dir, NOTE)
    # Windows' own Notepad reads UTF-8 with a BOM as UTF-8 everywhere (the Korean note needs it).
    with open(target, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write("\n".join(lines))
    return target


class Outcome:
    """What putting the game back did.

    folder: False when there was no game folder to put back (none chosen, or the chosen one is gone);
    put_back: the files put back (relative paths); stays: originals left in backup\\ (not openDMT3's own copies);
    still: files still changed, named in the note at `note`.
    """

    def __init__(self, folder=True, put_back=(), stays=(), still=(), note=None):
        self.folder, self.note = folder, note
        self.put_back, self.stays, self.still = list(put_back), list(stays), list(still)


def put_game_back(state):
    """Put every file PLAY changed back, then take openDMT3's own copies and list out of backup\\.

    GameError (worded) when the game is open, since its files cannot be written while it runs; any other failure
    (a locked file, a full disk) is raised as it is. Nothing is done without a chosen folder, or when it is gone.
    """
    from opendmt3.core.backup import Backup
    from opendmt3.client import actions
    if not state.game_folder:
        return Outcome(folder=False)
    try:
        game = state.game()
    except g.GameError:
        # The chosen folder is gone (moved, renamed, its drive unplugged): there is nothing here to put back.
        return Outcome(folder=False)
    # The same as Help's Put the game's files back (and the card file goes with it).
    done = actions.restore(state)
    kept = Backup(game)
    still = kept.still_changed()
    if still:
        # Something did not go back (a folder where a file was): say what, and keep every copy for it.
        return Outcome(put_back=done, still=still, note=note(game, kept, still, state.language))
    # Everything is back, so a note from an earlier removal no longer says anything true.
    clear_note(kept)
    return Outcome(put_back=done, stays=kept.forget() or [])


def changed_before(state):
    """True when the game folder in use holds files an older openDMT3 changed: only then has uninstalling anything
    to put back there (PLAY changes nothing in the game folder), so only then is the game named in what uninstalling
    says. False without a folder, or with one that is gone."""
    from opendmt3.core.backup import Backup
    if not state.game_folder:
        return False
    try:
        return bool(Backup(state.game()).still_changed())
    except (g.GameError, OSError, ValueError):
        # Chosen once, gone now (moved, renamed, on a drive that is not plugged in), or its list cannot be read.
        return False


def before_uninstall(state, registry=None, desktops=None):
    """Help's Uninstall's and --uninstall's work before Velopack's uninstall starts: the game back as it was, then
    the shortcut and starting with Windows away. GameError (worded) when the game is open or a file did not go
    back: then openDMT3 stays as it was, shortcut and all, and nothing is uninstalled."""
    outcome = put_game_back(state)
    if outcome.still:
        n = len(outcome.still)
        raise g.GameError("game files that did not go back: %d; the note README-openDMT3.txt in the game folder's "
                          "backup names them" % n, "error.remove.still_changed", n=n)
    take_shortcuts_away(registry, desktops)
    return outcome


def clear_note(kept):
    """Take an old note out of backup\\ (the files it named are back)."""
    path = os.path.join(kept.dir, NOTE)
    if os.path.isfile(path):
        os.remove(path)


def leave_note(state):
    """The game could not be put back: a note in backup\\ names the files still changed. Returns its path or None."""
    from opendmt3.core.backup import Backup
    try:
        kept = Backup(state.game())
        changed = kept.still_changed()
        if not changed:
            return None
        return note(kept.game, kept, changed, state.language)
    except Exception:  # noqa: BLE001  (removing never fails over a note)
        log.exception("could not leave the note for the game folder")
        return None


def take_shortcuts_away(registry=None, desktops=None):
    """The desktop shortcut that plays at once, and playing when Windows starts: both go (each only if there).
    Returns the shortcuts removed; never raises (each failure is logged)."""
    from opendmt3.client import shortcuts
    removed = []
    try:
        removed = shortcuts.remove_shortcut(desktops)
    except Exception:  # noqa: BLE001  (a shortcut left behind is said in the log, never a failed removal)
        log.exception("could not remove the desktop shortcut")
    try:
        if registry is not None or sys.platform == "win32":
            shortcuts.autostart(False, registry=registry)
    except Exception:  # noqa: BLE001
        log.exception("could not turn off playing when Windows starts")
    return removed


def ask_for_everything(folder):
    """Write a new token in the launcher's folder; returns it, for the uninstall the launcher starts now."""
    token = secrets.token_hex(16)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, TOKEN), "w", encoding="ascii") as f:
        f.write(token)
    return token


def asked_for_everything(environ, folder):
    """True only in the uninstall the launcher started with the choice on: the value handed to it is the token in
    the launcher's folder. A value from the surroundings never matches a token the launcher wrote."""
    given = environ.get(EVERYTHING) or ""
    try:
        with open(os.path.join(folder, TOKEN), encoding="ascii") as f:
            written = f.read().strip()
    except (OSError, UnicodeDecodeError):
        return False
    return bool(given and written) and secrets.compare_digest(given, written)


def tidy(state=None, registry=None, desktops=None, environ=None):
    """Everything removing openDMT3 leaves to the launcher (see the top of this file); never raises.

    Returns what it did, for the log and the tests: {"game": Outcome or None, "note": path or None,
    "shortcuts": [paths], "data": names left in the settings folder, or None when it was kept}.
    """
    from opendmt3.client import state as st
    environ = os.environ if environ is None else environ
    done = {"game": None, "note": None, "shortcuts": [], "data": None}
    if state is None:
        try:
            state = st.LauncherState.load()
        except Exception:  # noqa: BLE001  (unreadable settings: the game folder is not known, the rest still goes)
            log.exception("could not read the launcher's settings while removing openDMT3")
    if state is not None and state.game_folder:
        try:
            done["game"] = put_game_back(state)
            done["note"] = done["game"].note
            log.info("removing openDMT3: put back %d game file(s), %d original(s) stay in backup",
                     len(done["game"].put_back), len(done["game"].stays))
        except Exception:  # noqa: BLE001  (the game is open, or a file is locked: word is left instead)
            log.exception("could not put the game's files back while removing openDMT3")
            done["note"] = leave_note(state)
        if done["note"]:
            log.warning("removed while game files are still changed; how to put them back: %s", done["note"])
    done["shortcuts"] = take_shortcuts_away(registry, desktops)
    # The short path to a game folder, if a PLAY left one (a link to the player's game must not outlive openDMT3).
    from opendmt3.core.cabinet import launch
    launch.take_short_paths_away()
    folder = st.config_dir()
    if asked_for_everything(environ, folder):
        try:
            # The log is one of the things that go: it is closed first, and nothing is written to it after.
            stop_logging()
            done["data"] = delete_data(folder)
        except Exception:  # noqa: BLE001  (whatever could not go stays, as on any failed delete)
            done["data"] = sorted(os.listdir(folder)) if os.path.isdir(folder) else []
    else:
        # A token from an uninstall that did not happen (cancelled, failed) says nothing any more.
        _delete(os.path.join(folder, TOKEN))
    return done


def stop_logging():
    """Close the launcher's log file (main._logging), so its folder can be deleted."""
    root = logging.getLogger("opendmt3")
    for handler in [h for h in root.handlers if getattr(h, "opendmt3_log", False)]:
        root.removeHandler(handler)
        handler.close()


def _delete(path):
    """Delete one file if it is there (made writable first when Windows has it read-only); True when it went. A
    file that cannot go (in use, no rights) stays, and the rest goes on without it."""
    try:
        try:
            os.remove(path)
        except PermissionError:
            os.chmod(path, stat.S_IWRITE)
            os.remove(path)
        return True
    except OSError:
        return False


def _names(folder):
    """The names in a folder ([] when it is not there or cannot be read)."""
    try:
        return os.listdir(folder)
    except OSError:
        return []


def _remove_if_empty(folder):
    try:
        os.rmdir(folder)
    except OSError:
        # Something else is in it (not the launcher's), or it is gone already: it stays as it is.
        pass


def _named_in(folder, named):
    """The files in `folder` whose names `named` accepts."""
    for name in _names(folder):
        path = os.path.join(folder, name)
        if os.path.isfile(path) and named(name):
            yield path


def _launchers_files(folder):
    """Every file delete_data() takes from `folder`: the launcher's own names in its own places, nothing else."""
    from opendmt3.server.services import cards, catalog
    yield from _named_in(folder, lambda name: name in DATA_FILES or name.startswith(DATA_PREFIXES))
    yield from _named_in(os.path.join(folder, "logs"), LOG_NAME.match)
    server = os.path.join(folder, "server")
    yield from _named_in(os.path.join(server, "backups"), BACKUP_NAME.match)
    yield from _named_in(os.path.join(server, catalog.JACKETS), PICTURE_NAME.match)
    pictures = os.path.join(server, cards.FOLDER)
    for kind in _names(pictures):
        yield from _named_in(os.path.join(pictures, kind), PICTURE_NAME.match)
    yield from _named_in(server, SERVER_NAME.match)
    # A song list's work a stop left in the middle (catalog.STAGING): its folders, by their name, with all they hold.
    for top in _staging(server):
        for inside, _, names in os.walk(top):
            for name in names:
                yield os.path.join(inside, name)


def _staging(server):
    """The folders of a song list's unfinished work in the server's folder (catalog.STAGING), never through a link."""
    from opendmt3.server.services import catalog
    for name in _names(server):
        path = os.path.join(server, name)
        if name.startswith(catalog.STAGING) and os.path.isdir(path) and not os.path.islink(path):
            yield path


def data_size(folder):
    """How much delete_data() would free, in bytes (what Uninstall's question says Delete all takes)."""
    total = 0
    for path in _launchers_files(folder):
        try:
            total += os.path.getsize(path)
        except OSError:
            pass
    return total


def megabytes(size):
    """A size for a sentence: '640 KB', '85 MB', '1.2 GB' (as the OpenDMTQ PC client writes it)."""
    if size >= 1 << 30:
        return "%.1f GB" % (size / float(1 << 30))
    if size >= 1 << 20:
        return "%d MB" % round(size / float(1 << 20))
    # Anything at all is at least 1 KB, so that a sentence never says something small is nothing.
    return "%d KB" % max(1, round(size / 1024.0))


def delete_data(folder):
    """Delete the launcher's settings, its log and this PC's server data (players, records, the backups of them)
    from `folder`, file by file and only by the names the launcher gives them, then each folder once it is empty.
    A file or folder of any other name stays, and the folders holding it. Returns the names left in `folder`."""
    from opendmt3.server.services import cards, catalog
    for path in list(_launchers_files(folder)):
        _delete(path)
    server = os.path.join(folder, "server")
    pictures = os.path.join(server, cards.FOLDER)
    # Deepest first, so each parent is empty by its turn; a folder with anyone else's file in it stays.
    for kind in _names(pictures):
        _remove_if_empty(os.path.join(pictures, kind))
    # A song list's unfinished work: its folders, deepest first, each once its files are gone.
    for top in list(_staging(server)):
        for inside, _, _ in os.walk(top, topdown=False):
            _remove_if_empty(inside)
    for name in (cards.FOLDER, catalog.JACKETS, "backups") + SERVER_EMPTY:
        _remove_if_empty(os.path.join(server, name))
    for path in (server, os.path.join(folder, "logs"), folder):
        _remove_if_empty(path)
    return sorted(_names(folder))


def uninstaller():
    """Velopack's Update.exe above the installed launcher's `current` folder, or None when this launcher was not
    installed by openDMT3-win-Setup.exe (run from source or from a copied folder: there is nothing to uninstall)."""
    from opendmt3.client import shortcuts
    try:
        exe = shortcuts.launcher_exe()
    except g.GameError:
        return None
    path = os.path.join(os.path.dirname(os.path.dirname(exe)), "Update.exe")
    return path if os.path.isfile(path) else None


APP_LIST_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\openDMT3"


def quiet_app_list(registry=None):
    """Make Windows' app list remove openDMT3 without Velopack's plain window at the end: the line it runs becomes
    the quiet one Velopack writes beside it. True when it changed the line (only an installed openDMT3 has one)."""
    from opendmt3.client import shortcuts
    reg = registry or shortcuts._winreg()
    try:
        key = reg.OpenKey(reg.HKEY_CURRENT_USER, APP_LIST_KEY, 0, reg.KEY_READ | reg.KEY_SET_VALUE)
    except FileNotFoundError:
        return False
    try:
        line = reg.QueryValueEx(key, "UninstallString")[0]
        if "--silent" in line:
            return False
        try:
            quiet = reg.QueryValueEx(key, "QuietUninstallString")[0]
        except FileNotFoundError:
            quiet = line + " --silent"
        reg.SetValueEx(key, "UninstallString", 0, reg.REG_SZ, quiet)
        log.info("Windows' app list removes openDMT3 without a window of Velopack's: %s", quiet)
        return True
    finally:
        reg.CloseKey(key)


def start_uninstall(updater, everything=False, popen=subprocess.Popen):
    """Start Velopack's uninstall on its own: it outlives this program, which it closes before it begins. Silent:
    the launcher's dialogs (or the terminal) have said what happens, and Velopack's plain window never shows.

    `everything` asks the hook to delete settings, players and records too.
    """
    from opendmt3.client import state as st
    env = dict(os.environ)
    # Only this run decides: a value from the surroundings never deletes anything.
    env.pop(EVERYTHING, None)
    if everything:
        env[EVERYTHING] = ask_for_everything(st.config_dir())
    args = [updater, "--uninstall", "--silent"]
    flags = 0
    if sys.platform == "win32":
        # Not tied to this program's console or its Ctrl+C: Velopack closes this program, then works on.
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    log.info("starting the uninstall%s", " (settings, players and records too)" if everything else "")
    return popen(args, env=env, cwd=os.path.dirname(updater) or None, close_fds=True, creationflags=flags,
                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
