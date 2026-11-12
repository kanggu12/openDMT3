"""openDMT3's installer: the launcher's own dialogs around Velopack's setup.

Velopack's setup (bundled as velopack-setup.exe) does the work: it puts the launcher in %LocalAppData%\\openDMT3,
makes the shortcuts and the uninstall entry, and keeps the update packages. Run with --silent it shows nothing
and asks nothing, so every question and every message comes from here instead, in the shape of the game's popups
like the launcher's: install, update, repair or go back a version, close a launcher that is open first, wait
while a game is running, and what went wrong if it failed. When it is done the launcher starts.

  openDMT3-win-Setup.exe                         the dialogs
  openDMT3-win-Setup.exe --silent [--no-start]   no dialog: install or update, then start the launcher
"""

import glob
import logging
import logging.handlers
import os
import re
import subprocess
import sys
import tempfile
import time

from opendmt3 import __version__

log = logging.getLogger("opendmt3.installer")

# Velopack's setup, next to this program inside the frozen installer (sys._MEIPASS) or given by a test.
SETUP_NAME = "velopack-setup.exe"
# The launcher's named mutex (client/main.py): it exists while a launcher window is open.
LAUNCHER_MUTEX = "Local\\openDMT3.launcher"
# How long Velopack's setup may take before the installer stops waiting for it.
SETUP_LIMIT = 300
# Velopack's logs of earlier runs kept in the temporary folder.
LOGS_KEPT = 5


def app_dir():
    """Where Velopack installs for this Windows user."""
    return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "openDMT3")


def installed_version(folder=None):
    """The version installed for this user (Velopack's current\\sq.version), or None."""
    path = os.path.join(folder or app_dir(), "current", "sq.version")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            found = re.search(r"<version>\s*([^<\s]+)\s*</version>", f.read())
    except OSError:
        return None
    return found.group(1) if found else None


def version_key(text):
    """A key that orders versions as Semantic Versioning does: 1.2.3-rc.1 < 1.2.3-rc.2 < 1.2.3 (build data after
    + is ignored)."""
    core, _, pre = (text or "0").partition("+")[0].partition("-")
    numbers = tuple(int(n) if n.isdigit() else 0 for n in (core.split(".") + ["0", "0"])[:3])
    if not pre:
        # A release comes after every pre-release of it.
        return numbers, 1, ()
    # Pre-release parts: numbers before words, numbers by value, words by their letters.
    parts = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))
    return numbers, 0, parts


def _mutex_exists(name):
    if sys.platform != "win32":
        return False
    import ctypes
    synchronize = 0x00100000
    handle = ctypes.windll.kernel32.OpenMutexW(synchronize, False, name)
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    return False


def launcher_open():
    """True while a launcher window is open (its mutex exists); False on other systems."""
    return _mutex_exists(LAUNCHER_MUTEX)


def game_running():
    """True while a launcher says a game it started is running (client/playing.py, the same test as the
    launcher's own update)."""
    from opendmt3.client import playing
    return playing.game_running()


def setup_path():
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.environ.get("OPENDMT3_VELOPACK_SETUP") or os.path.join(base, SETUP_NAME)


def failure_line(log_path):
    """The last error Velopack wrote in its log, for the dialog (None when there is none)."""
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            lines = [line.strip() for line in f if "[ERROR]" in line]
    except OSError:
        return None
    if not lines:
        return None
    # "[12:00:13] [ERROR] Something": the message after the level.
    return lines[-1].split("[ERROR]", 1)[1].strip()[:300] or None


def start_launcher():
    """Start the installed launcher the way its shortcut does (Velopack's stub picks the current version)."""
    stub = os.path.join(app_dir(), "openDMT3.exe")
    log.info("starting %s", stub)
    subprocess.Popen([stub], cwd=app_dir(), close_fds=True)


def run_setup(log_path):
    """Start Velopack's setup without a window; returns the process."""
    flags = 0x08000000 if sys.platform == "win32" else 0      # CREATE_NO_WINDOW
    return subprocess.Popen([setup_path(), "--silent", "--log", log_path], creationflags=flags, close_fds=True)


def setup_file():
    """This installer's own file, whose end may carry a server (preset.py); OPENDMT3_SETUP_FILE in its place for the
    UI tests, None when it runs from source."""
    if os.environ.get("OPENDMT3_SETUP_FILE"):
        return os.environ["OPENDMT3_SETUP_FILE"]
    return sys.executable if getattr(sys, "frozen", False) else None


def hand_over(details):
    """Leave the server this installer is set up for, for the launcher's next start (nothing without one)."""
    from opendmt3.core import preset
    from opendmt3.client import state as st
    if details:
        try:
            preset.hand_over(details, st.config_dir())
            log.info("the launcher plays on %s from its next start", details["url"])
        except OSError:
            log.exception("could not leave the server for the launcher")


def language():
    """The language the installer speaks: the launcher's (its player's choice, else Windows'), or Windows' when the
    launcher's settings cannot be read (the launcher asks about them at its own start); as the OpenDMTQ PC client's."""
    from opendmt3.client import state as st
    try:
        return st.LauncherState.load().language
    except Exception:  # noqa: BLE001  (settings that cannot be read: the language Windows is shown in)
        return st.system_language()


def plan(have, here, running, words=None):
    """What to ask, from the version installed (None: none), this installer's and whether a launcher is open.

    Returns (kind, tab, question, detail, action words, action), or None for "repair or open".
    action is what the work under way is called: install, update or back.
    """
    from opendmt3.client import i18n
    w = words or i18n.Words("en")
    closing = (" " + w("setup.closing")) if running else ""
    if have is None:
        return ("info", w("setup.tab"), w("setup.install.ask", v=here), w("setup.install.detail"),
                w("setup.install"), "install")
    if version_key(have) < version_key(here):
        return ("info", w("setup.tab.update"), w("setup.update.ask", v=here),
                w("setup.update.detail", have=have) + closing, w("setup.update"), "update")
    if version_key(have) > version_key(here):
        return ("warn", w("setup.tab"), w("setup.back.ask"), w("setup.back.detail", have=have, here=here) + closing,
                w("setup.back", here=here), "back")
    return None


# What the work under way is called, by action: the keys of the tab and of the line.
WORK = {
    "install": ("setup.work.install", "setup.work.install.line"),
    "update": ("setup.work.update", "setup.work.update.line"),
    "repair": ("setup.work.repair", "setup.work.repair.line"),
    "back": ("setup.work.back", "setup.work.back.line"),
}


class Installer:
    """The installer's window: one dialog after another in a window of its own."""

    def __init__(self):
        from opendmt3.client import dialogs, i18n
        self.dialogs = dialogs
        # The launcher's language, decided once for every dialog of this run.
        self.language = language()
        # The server a site's download is set up for (its end), or None for a release's own installer.
        from opendmt3.core import preset
        path = setup_file()
        self.preset = preset.read(path) if path else None
        self.words = i18n.Words(self.language)
        self.root, self.ui = dialogs.window_root(title=self.words("setup.window"), language=self.language)
        self.dialog = None
        self.process = None
        self.started_at = None
        self.action = "install"
        self.log_path = os.path.join(tempfile.gettempdir(), "openDMT3-setup-%s.log" % time.strftime("%Y%m%d-%H%M%S"))
        self.root.protocol("WM_DELETE_WINDOW", self._close_window)
        self.ask()

    def show(self, kind, title, message, detail, buttons=(), default=0, cancel=None, progress=False):
        """Replace the dialog on show with another, the window fitted to it."""
        from opendmt3.client import art
        if self.dialog is not None:
            self.dialog.on_close = None
            self.dialog.close(None)
        self.dialog = self.dialogs.Dialog(self.root, self.ui, kind, title, message, detail, buttons, default=default,
                                          cancel=cancel, progress=progress,
                                          window=lambda w, h: art.shards(w, h, seed=29), on_close=self._answered)
        self.dialogs.fit(self.root, self.ui, self.dialog)

    def ask(self):
        w = self.words
        have, running = installed_version(), launcher_open()
        log.info("installed %s, this %s, launcher open %s", have, __version__, running)
        if have is not None and game_running():
            # Velopack would close the launcher, and with it the server the game plays on.
            self.show("warn", w("setup.tab"), w("setup.game"), w("setup.game.detail"),
                      [(w("setup.close"), "cancel", "neutral"), (w("setup.again"), "again", "info")], default=1,
                      cancel="cancel")
            return
        asked = plan(have, __version__, running, w)
        if asked is None:
            detail = w("setup.repair.detail") + ((" " + w("setup.repair.closing")) if running else "")
            self.show("info", w("setup.tab"), w("setup.installed", v=__version__), detail,
                      [(w("setup.repair"), "repair", "neutral"), (w("setup.open"), "open", "info")], default=1,
                      cancel="cancel")
            return
        kind, tab, question, detail, words, action = asked
        if self.preset:
            # Downloaded from a server's site: the launcher will start on that server.
            detail += " " + w("setup.for", name=self.preset["name"])
        self.show(kind, tab, question, detail, [(w("setup.cancel"), "cancel", "neutral"), (words, action, kind)],
                  default=1, cancel="cancel")

    def _answered(self, value):
        if value in WORK:
            self.install(value)
        elif value == "again":
            self.ask()
        elif value == "open":
            self._start_or_say(wait=0)
        elif value == "log":
            try:
                os.startfile(self.log_path)
            except (AttributeError, OSError):
                log.exception("could not open %s", self.log_path)
            self.root.destroy()
        else:
            self.root.destroy()

    def _start_or_say(self, wait=1400):
        """Start the launcher and close (after `wait` ms, time to read the end); if it cannot start, say so
        instead of leaving an empty window."""
        try:
            start_launcher()
        except OSError as e:
            log.exception("could not start the launcher")
            self.failed(self.words("setup.not_started.detail", error=self.words.error(e)),
                        title=self.words("setup.not_started"))
            return
        self.root.after(wait, self.root.destroy)

    def install(self, action):
        w = self.words
        self.action = action
        tab, line = WORK[action]
        self.show("info", w(tab), w(line, v=__version__), w("setup.work.detail"), progress=True)
        try:
            self.process = run_setup(self.log_path)
        except OSError as e:
            log.exception("could not start Velopack's setup")
            self.failed(w("setup.no_setup", error=w.error(e)))
            return
        self.started_at = time.time()
        self.root.after(100, self._wait)

    def _wait(self):
        code = self.process.poll()
        if code is None:
            if time.time() - self.started_at > SETUP_LIMIT:
                # A setup that hangs never ends on its own: stop it and say so.
                log.error("Velopack's setup did not finish in %d s", SETUP_LIMIT)
                self.process.kill()
                self.failed(self.words("setup.too_long", m=SETUP_LIMIT // 60))
                return
            self.root.after(100, self._wait)
            return
        log.info("Velopack's setup ended with %s", code)
        found = installed_version()
        if code != 0:
            self.failed(failure_line(self.log_path) or self.words("setup.code", code=code))
            return
        if found != __version__:
            self.failed(self.words("setup.wrong_version", found=found, here=__version__))
            return
        # The server this installer is set up for, for the launcher that starts next.
        hand_over(self.preset)
        try:
            # Velopack has written the app list's line by now: removing from there runs without its plain window.
            from opendmt3.client import leaving
            leaving.quiet_app_list()
        except Exception:  # noqa: BLE001  (the launcher's next start does it again)
            log.exception("could not make the app list's uninstall quiet")
        self.show("info", self.words("setup.tab.done"), self.words("setup.done", v=__version__),
                  self.words("setup.starting"), progress=True)
        self._start_or_say()

    def failed(self, why, title=None):
        """What went wrong, with the way to Velopack's log when there is one."""
        w = self.words
        title = title or w("setup.failed")
        if os.path.isfile(self.log_path):
            self.show("error", w("setup.tab"), title, w("setup.failed.log", why=why, path=self.log_path),
                      [(w("setup.close"), "close", "neutral"), (w("setup.open_log"), "log", "info")], default=1,
                      cancel="close")
        else:
            self.show("error", w("setup.tab"), title, why, [(w("setup.close"), "close", "info")], default=0,
                      cancel="close")

    def _close_window(self):
        if self.process is not None and self.process.poll() is None:
            # Velopack is writing files: the window stays until it is done (or the time limit stops it).
            return
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def _logging():
    """The installer's own log next to Velopack's, in the temporary folder, with a size cap; Velopack's logs of
    earlier runs beyond the last few are removed."""
    folder = tempfile.gettempdir()
    handler = logging.handlers.RotatingFileHandler(os.path.join(folder, "openDMT3-setup.log"), maxBytes=200_000,
                                                   backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root = logging.getLogger("opendmt3")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    runs = sorted(glob.glob(os.path.join(folder, "openDMT3-setup-2*.log")))
    for old in runs[:-LOGS_KEPT]:
        try:
            os.remove(old)
        except OSError:
            pass


def _close_splash():
    """The picture PyInstaller shows while the installer unpacks itself goes as soon as Python runs."""
    try:
        import pyi_splash
        pyi_splash.close()
    except ImportError:
        pass


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    _close_splash()
    _logging()
    log.info("openDMT3 setup %s: %s", __version__, " ".join(argv))
    if "--silent" in argv:
        # No dialog: Velopack's own silent install, then the launcher, as the dialogs would do.
        path = os.path.join(tempfile.gettempdir(), "openDMT3-setup-%s.log" % time.strftime("%Y%m%d-%H%M%S"))
        try:
            code = run_setup(path).wait(timeout=SETUP_LIMIT)
            if code == 0:
                from opendmt3.core import preset
                where = setup_file()
                hand_over(preset.read(where) if where else None)
                # As after the dialogs' install: removing from Windows' app list runs without Velopack's window.
                try:
                    from opendmt3.client import leaving
                    leaving.quiet_app_list()
                except Exception:  # noqa: BLE001  (the launcher's next start does it again)
                    log.exception("could not make the app list's uninstall quiet")
            if code == 0 and "--no-start" not in argv:
                start_launcher()
        except (OSError, subprocess.TimeoutExpired):
            log.exception("the silent install failed")
            return 2
        return code
    Installer().run()
    return 0


def run(argv=None):
    """main() as openDMT3-win-Setup.exe starts it: an error nothing caught ends in the installer's own error
    window, never in PyInstaller's plain one, and in its log."""
    try:
        return main(argv)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001  (said and logged here: this is the last place that can)
        log.exception("the installer stopped")
        from opendmt3.client import dialogs
        log_path = os.path.join(tempfile.gettempdir(), "openDMT3-setup.log")
        from opendmt3.core import errors
        # The same words as the launcher's stopped window (and the OpenDMTQ PC client's), in the installer's language.
        from opendmt3.client import i18n
        lang = language()
        w = i18n.Words(lang)
        dialogs.standalone("error", w("crash.title"), w("crash.message"),
                           w("crash.detail", error=errors.closed(errors.say(e, lang), {}), path=log_path),
                           [(w("common.close"), "close", "info")], default=0, cancel="close", language=lang)
        return 2


if __name__ == "__main__":
    sys.exit(run())
