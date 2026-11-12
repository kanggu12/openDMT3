"""Start the launcher: Velopack's install, update and uninstall hooks, the log, one window at a time, a
server's address left by the installer (preset.py), and the launcher's own windows for a failure. With flags the
process does the command line's jobs instead (cli.py, where the flags are listed) and opens no window.
"""

import logging
import logging.handlers
import os
import sys

from opendmt3 import __version__
from opendmt3.client import actions, cli
from opendmt3.client import state as st
# The command line's parsing and its way of saying things, for the lines main() says itself.
from opendmt3.client.cli import parse, say as _say

log = logging.getLogger("opendmt3.launcher")


def _velopack_hooks(argv):
    """Let Velopack handle its install, update and uninstall events; it exits the process for those.

    openDMT3 registers nothing to do in them. So when Velopack itself fails in one (it raised once under Wine,
    as the installer ran it), the failure is logged and the process ends as a finished hook would: the
    installer does not report a partly failed install over a step openDMT3 never needed.
    """
    try:
        import velopack
    except ImportError:
        # Run from source or a copied folder: there is no installer around.
        return
    try:
        app = velopack.App()
        if hasattr(app, "set_auto_apply_on_startup"):
            # Velopack would put in at start any package left in packages\\; openDMT3 hands over only packages that
            # carry its signature (updates.apply), right after checking them.
            app.set_auto_apply_on_startup(False)
        else:
            # A Velopack without the switch would put in whatever package it finds at start; said, so it is seen.
            log.warning("this Velopack cannot be told to leave packages alone at start")
        if hasattr(app, "on_before_uninstall_fast_callback"):
            # Removing openDMT3, whichever way it was started: the game back as it was, the shortcuts away.
            app.on_before_uninstall_fast_callback(_before_uninstall)
        for name in ("on_after_install_fast_callback", "on_after_update_fast_callback"):
            if hasattr(app, name):
                # Windows' app list removes openDMT3 without Velopack's plain window (client/leaving.py).
                getattr(app, name)(_after_install)
        app.run()
        if any(a.startswith("--veloapp-") for a in argv):
            # Velopack ends the process after a hook by itself; should it ever return instead, a hook's run still
            # ends here and never goes on to open the window (after an uninstall there is nothing left to open).
            sys.exit(0)
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001  (a Rust panic arrives as a BaseException, not an Exception)
        log.exception("Velopack start-up hook failed")
        if any(a.startswith("--veloapp-") for a in argv):
            sys.exit(0)


def _before_uninstall(version=None):
    """openDMT3 is being removed (Help's Uninstall, --uninstall, or Windows' app list): the game's files go back,
    openDMT3's own copies leave backup\\, the shortcut and starting with Windows go; settings, players and records
    only when the person asked (client/leaving.py). Nothing here can fail the removal, and no window opens."""
    try:
        from opendmt3.client import leaving
        return leaving.tidy()
    except Exception:  # noqa: BLE001  (removing must never fail over what it tidies)
        log.exception("could not tidy up while openDMT3 was removed")
        return None


def _after_install(version=None):
    """The app list's line made the quiet one (never a plain window of Velopack's). Velopack writes that line after
    its install hook has run (measured under Wine), so the hook finds it only on an update; every start of the
    launcher after it (main) and the installer once its setup is done make it so."""
    try:
        from opendmt3.client import leaving
        leaving.quiet_app_list()
    except Exception:  # noqa: BLE001  (an install never fails over this)
        log.exception("could not make the app list's uninstall quiet")


def _logging():
    """One log file with a size cap: 1 MB, the two previous ones kept, nothing older."""
    folder = os.path.join(st.config_dir(), "logs")
    os.makedirs(folder, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(os.path.join(folder, "launcher.log"), maxBytes=1_000_000,
                                                   backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s"))
    handler.opendmt3_log = True
    root = logging.getLogger("opendmt3")
    root.setLevel(logging.INFO)
    # One file handler at a time, even when main() runs more than once in a process (the tests do).
    for old in [h for h in root.handlers if getattr(h, "opendmt3_log", False)]:
        root.removeHandler(old)
        old.close()
    root.addHandler(handler)


def _dpi_aware():
    """Draw at the screen's real resolution instead of being blurred by Windows scaling."""
    if sys.platform != "win32":
        return
    import ctypes
    try:
        # System DPI awareness: sharp on the main monitor at any scaling.
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        ctypes.windll.user32.SetProcessDPIAware()


def _single_instance():
    """True when no other launcher window is open; otherwise bring that one forward and return False."""
    if sys.platform != "win32":
        return True
    import ctypes
    # A named mutex lives as long as the first launcher; a second one sees it already exists.
    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\openDMT3.launcher")
    if ctypes.windll.kernel32.GetLastError() != 183:   # ERROR_ALREADY_EXISTS
        return True
    hwnd = ctypes.windll.user32.FindWindowW(None, "openDMT3")
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 9)        # SW_RESTORE
        ctypes.windll.user32.SetForegroundWindow(hwnd)
    return False


def _windowed():
    """True for the window copy (openDMT3.exe): it has no console, so a printed error is never seen."""
    return sys.stdout is None or sys.stderr is None


def _cannot_start(error):
    """The window copy cannot read its settings: say so in a dialog instead of closing without a word.

    A broken file can be set aside (kept next to it, with the time in its name) to start again from the guide;
    a file from a newer launcher is left alone, because only that launcher reads it right.
    """
    from opendmt3.client import dialogs, i18n
    # The settings that would say the player's language cannot be read: the language Windows is shown in.
    language = st.system_language()
    w = i18n.Words(language)
    if error.newer:
        dialogs.standalone("error", w("start.title"), w("start.newer"), w("start.newer.detail", path=error.path),
                           [(w("common.close"), "close", "info")], default=0, cancel="close", language=language)
        return False
    answer = dialogs.standalone("error", w("start.title"), w("start.broken"),
                                w("start.broken.detail", path=error.path),
                                [(w("common.close"), "close", "neutral"), (w("start.over"), "reset", "warn")],
                                default=1, cancel="close", language=language)
    if answer != "reset":
        return False
    import time
    aside = "%s.broken-%s" % (error.path, time.strftime("%Y%m%d-%H%M%S"))
    try:
        os.replace(error.path, aside)
        log.info("set the unreadable settings aside as %s", aside)
    except FileNotFoundError:
        # Another start of the launcher set it aside a moment ago.
        log.info("the unreadable settings were already set aside")
    return True


def _take_preset(state):
    """The server an installer from a server's site left (preset.py), taken once: this launcher plays on it from now
    on, its address filled in for LOG IN (or Online) to connect. True when it changed the state."""
    from opendmt3.core import preset
    from opendmt3.client import remote
    found = preset.take(st.config_dir())
    if not found:
        return False
    try:
        base = remote.normalize(found["url"])
    except Exception:  # noqa: BLE001  (an address this launcher cannot read: the guide asks for one)
        log.exception("the installer's server cannot be read: %r", found["url"])
        return False
    if state.server_url != base:
        # Another server's sign-in and card do not go with this one.
        state.remote = None
    state.server_url, state.mode = base, "server"
    log.info("plays on %s, the server this launcher was downloaded from", base)
    return True


# The official 7-Zip for Windows the build brings (packaging/windows/build.sh), beside the launcher's own code.
SEVEN_ZIP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin", "7-Zip", "7z.exe")


def _seven_zip():
    """Archives are opened with the launcher's own 7-Zip (the reading underneath looks where OPENDMT3_7ZIP says); a
    7-Zip named before the launcher started stays the one used."""
    if os.path.isfile(SEVEN_ZIP):
        os.environ.setdefault("OPENDMT3_7ZIP", SEVEN_ZIP)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # The log first, so a failure in Velopack's own start-up handling is written down too.
    _logging()
    log.info("openDMT3 %s started%s", __version__, (": " + " ".join(argv)) if argv else "")
    _seven_zip()
    _velopack_hooks(argv)
    if sys.platform == "win32":
        # Every start, the window, the console copy and the desktop shortcut's PLAY alike: one look in the registry.
        _after_install()
    args = parse(argv)
    jobs = cli.has_jobs(args)
    if not jobs:
        # The window copy: sharp at any scaling and only once, settled before any window (a dialog too) opens.
        _dpi_aware()
        if not _single_instance():
            return 0
    try:
        state = st.LauncherState.load()
    except st.StateError as e:
        _say(str(e), error=True)
        if args.uninstall:
            # Removing goes on without them, as Windows' app list does: no game folder is known, so its files stay.
            state = st.LauncherState()
        elif not (_windowed() and not jobs and _cannot_start(e)):
            return 2
        else:
            state = st.LauncherState.load()
    if _take_preset(state):
        state.save()
    # The game files' fingerprints by size and time, kept between runs: a second PLAY reads none that did not change.
    from opendmt3.core import game as g
    g.use_hash_cache(state.own().path("openDMT3-hashes.json"))
    # A short path to the game folder that a launcher ended without taking away (a crash, a closed console) goes now.
    from opendmt3.client import actions
    actions.tidy_after_an_end(state)
    code = cli.run_jobs(args, state, _play_failed)
    if code is not None:
        return code
    if jobs:
        # A settings change, the status or a report from the command line does not open the window.
        return 0
    from opendmt3.client.app import LauncherApp
    app = LauncherApp(state)
    app.run()
    if app.then is not None:
        # Removing openDMT3: the window is gone, its settings saved and this PC's server stopped; Velopack's
        # uninstall starts now and closes what is left of this program.
        try:
            app.then()
        except Exception as e:  # noqa: BLE001  (said in a window of its own: the launcher's is gone)
            log.exception("could not start the uninstall")
            from opendmt3.client import dialogs, i18n
            w = i18n.Words(state.language)
            dialogs.standalone("error", w("help.uninstall"), w("help.uninstall.failed"),
                               w("help.uninstall.start_failed.detail", error=w.error(e)),
                               [(w("common.close"), "close", "info")], default=0, cancel="close",
                               language=state.language)
            return 2
    return 0


def _play_failed(state, key, blocked=(), error=None):
    """--play could not go. The window copy (the desktop shortcut, playing when Windows starts) has no console, so
    it says why in the launcher's own window, in the player's language, with the way into the launcher to fix it;
    the console copy has printed it already. Returns the exit code, 2."""
    if not _windowed():
        return 2
    from opendmt3.core import errors
    from opendmt3.client import dialogs, i18n
    w = i18n.Words(state.language)
    message = w(key) if key else errors.closed(w.error(error), {})
    # Why PLAY cannot go, each line of the ready check that stops it in the player's language (the window's words).
    lines = [actions.why_not(c, w) for c in blocked]
    detail = "\n".join(lines + [w("quick.failed.detail")])
    answer = dialogs.standalone("warn" if blocked else "error", w("quick.failed.title"), message, detail,
                                [(w("common.close"), "close", "neutral"), (w("quick.failed.open"), "open", "info")],
                                default=1, cancel="close", language=state.language)
    if answer == "open" and _single_instance():
        from opendmt3.client.app import LauncherApp
        LauncherApp(state).run()
    return 2


def run(argv=None):
    """main() as the built programs start it (packaging/windows/entry.py). An error nothing caught ends in the
    launcher's own error window (the window copy) or on the terminal (the console copy), never in PyInstaller's
    plain one; it is in the log either way."""
    try:
        return main(argv)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001  (said and logged here: this is the last place that can)
        log.exception("openDMT3 stopped")
        if not _windowed():
            import traceback
            traceback.print_exc()
            return 2
        _stopped(e)
        return 2


def _stopped(error):
    """The launcher's own window for an error nothing caught: what it was, and the way to the log folder."""
    from opendmt3.client import dialogs, i18n
    try:
        language = st.LauncherState.load().language
    except Exception:  # noqa: BLE001  (settings that cannot be read: English, as before the guide)
        language = "en"
    w = i18n.Words(language)
    logs = os.path.join(st.config_dir(), "logs")
    from opendmt3.core import errors
    # A line of its own: it ends with a full stop like the lines around it, whatever error it was; then the log.
    answer = dialogs.standalone("error", w("crash.title"), w("crash.message"),
                                w("crash.detail", error=errors.closed(w.error(error), {}),
                                  path=os.path.join(logs, "launcher.log")),
                                [(w("crash.logs"), "logs", "neutral"), (w("common.close"), "close", "info")],
                                default=1, cancel="close", language=language)
    if answer == "logs":
        actions.open_folder(logs)


if __name__ == "__main__":
    sys.exit(main())
