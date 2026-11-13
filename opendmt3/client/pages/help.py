"""HELP: the ready check, what to do when the game closes by itself, the tools (a report, the launcher's log, Repair),
and what puts back and takes away (the client data's files an older openDMT3 changed, Uninstall)."""

import logging
import os
import threading
import tkinter as tk

from opendmt3.client import actions, dialogs, leaving, playing, theme, widgets
from opendmt3.client import state as st

log = logging.getLogger("opendmt3.launcher")
# How long Uninstall's last step stays, to be read, before the window closes (as the installer's last one).
LAST_STEP_MS = 2200

from opendmt3.client.pages.common import TITLES, card
from opendmt3.client.pages.play import refresh_checks


def build_help(app, parent):
    """Four cards, as OpenDMTQ's HELP has them: the checks (Check again at the title's right end), what to try when the
    game closes by itself (each line with the page it names one press away), the tools (a report, the launcher's log,
    Repair), and what puts back and takes away, from the least to the most (the client data's files an older openDMT3
    changed, then openDMT3 itself)."""
    ui, w = app.ui, app.words
    checks = card(parent, ui, w("help.checks"))
    checks.action(w("help.recheck"), app.refresh_checks)
    app.check_box = tk.Frame(checks.body, bg=theme.PANEL)
    app.check_box.pack(fill="x")
    refresh_checks(app)
    crash = card(parent, ui, w("help.crash"))
    for i, (key, page) in enumerate((("help.crash.1", "screen"), ("help.crash.2", "screen"), ("help.crash.3", None))):
        if i:
            widgets.divider(crash.body, ui, pady=9)
        line = tk.Frame(crash.body, bg=theme.PANEL)
        line.pack(fill="x")
        beside = ()
        if page:
            # The page the line names, by the menu's own name, reached by the mouse or the keyboard.
            to = widgets.link(line, ui, TITLES[page], lambda p=page: app.go(p))
            to.pack(side="right", anchor="n")
            beside = (to,)
        widgets.label(line, ui, w(key), wrap_margin=12, beside=beside).pack(side="left", fill="x")
    tools = card(parent, ui, w("help.tools"))
    # Each row is named by what it is about, its button by what it does (never the same words twice on a line).
    widgets.setting_row(tools.body, ui, w("help.report"),
                        lambda p: widgets.Button(p, ui, w("help.report.save"), app.save_report),
                        w("help.report.hint")).pack(fill="x")
    widgets.divider(tools.body, ui)
    logs = os.path.join(st.config_dir(), "logs")
    widgets.setting_row(tools.body, ui, w("help.logs"),
                        lambda p: widgets.Button(p, ui, w("common.open"), lambda: actions.open_folder(logs)),
                        w("help.logs.hint")).pack(fill="x")
    widgets.divider(tools.body, ui)
    widgets.setting_row(tools.body, ui, w("help.repair.row"),
                        lambda p: widgets.Button(p, ui, w("help.repair"), lambda: repair_program(app)),
                        w("help.repair.hint")).pack(fill="x")

    def restore():
        if app.busy or playing.game_running(app.session):
            # PLAY is writing the folder, or the game has it open: putting files back now would mix the two.
            app.set_status(w("help.restore.busy"), "warn")
            return
        if not dialogs.ask(app, "warn", w("help.restore.title"), w("help.restore.ask"), w("help.restore.detail"),
                           w("help.restore.confirm")):
            return
        try:
            done = actions.restore(app.state)
        except Exception as e:  # noqa: BLE001  (the game open, a file in use: said, never swallowed)
            log.exception("putting the game's files back failed")
            app.set_status(w("status.error", error=w.error(e)), "bad")
            return
        app.set_status(w("help.restore.done", n=len(done)) if done else w("help.restore.nothing"), "ok")
        app.refresh_checks()

    # What puts back and takes away, on a card of its own as OpenDMTQ's "Reset and remove": the least first.
    remove = card(parent, ui, w("help.remove"), last=True)
    widgets.setting_row(remove.body, ui, w("help.restore"),
                        lambda p: widgets.Button(p, ui, w("help.restore.confirm"), restore, kind="danger"),
                        w("help.restore.hint")).pack(fill="x")
    widgets.divider(remove.body, ui)
    # The last, as in the OpenDMTQ PC client: the one that takes everything away.
    widgets.setting_row(remove.body, ui, w("help.uninstall.row"),
                        lambda p: widgets.Button(p, ui, w("help.uninstall"), lambda: uninstall(app), kind="danger"),
                        w("help.uninstall.hint")).pack(fill="x")


def repair_program(app):
    """Help, Repair (client/repair.py): the program's files compared with the installed package and what is
    missing or changed put back, in the launcher's own dialogs. Nothing of the game, the settings or the records is
    touched, so neither a running game nor PLAY's work stands in its way."""
    from opendmt3.client import repair
    w = app.words
    title = w("help.repair")
    app.dialog = dialogs.Dialog(app.root, app.ui, "info", title, w("help.repair.working"),
                                w("help.repair.working.detail"), progress=True)

    def work():
        try:
            result = repair.run()
        except Exception as e:  # noqa: BLE001  (shown, never swallowed)
            log.exception("repair failed")
            app.post(lambda e=e: finished(None, e))
            return
        app.post(lambda: finished(result, None))

    def finished(result, error):
        if app.dialog is not None:
            app.dialog.close(None)
            app.dialog = None
        if error is not None:
            # A launcher run from a plain folder has nothing to repair from: said as a fact, not a failure.
            plain = getattr(error, "key", None) == "error.repair.not_installed"
            dialogs.tell(app, "info" if plain else "error", title, w.error(error) if plain else w("help.repair.failed"),
                         None if plain else w.error(error))
        elif result.failed:
            dialogs.tell(app, "warn", title, w("help.repair.partly"),
                         w("help.repair.partly.detail", n=result.restored, failed=len(result.failed)))
        elif result.restored:
            detail = "help.repair.done.restart" if result.needs_restart else "help.repair.done.detail"
            dialogs.tell(app, "info", title, w("help.repair.done"), w(detail, n=result.restored))
        else:
            dialogs.tell(app, "info", title, w("help.repair.fine"), w("help.repair.fine.detail", n=result.checked))

    threading.Thread(target=work, daemon=True, name="repair").start()


def uninstall(app):
    """Uninstall openDMT3 (client/leaving.py), asked as the OpenDMTQ PC client asks: Cancel, Keep data or Delete
    all. The game's files go back while this window shows it; then the window closes and Velopack's uninstall
    starts after it (main() runs app.then)."""
    w = app.words
    title = w("help.uninstall")
    if playing.game_running(app.session):
        # The game has its files open, and closing the launcher would end the server it plays on.
        dialogs.tell(app, "info", title, w("help.uninstall.busy"), w("help.uninstall.busy.detail"))
        return
    if app.busy:
        # PLAY is writing the game folder right now.
        dialogs.tell(app, "info", title, w("help.uninstall.busy.play"))
        return
    updater = leaving.uninstaller()
    if updater is None:
        dialogs.tell(app, "info", title, w("help.uninstall.not_installed"), w("help.uninstall.not_installed.detail"))
        return
    size = leaving.megabytes(leaving.data_size(st.config_dir()))
    # The game's files are named only when an older openDMT3 changed some: otherwise nothing of the game changes.
    changed = leaving.changed_before(app.state)
    first = ([w("help.uninstall.game")] if changed else []) + [w("help.uninstall.closes")]
    detail = "%s\n\n%s" % (" ".join(first), w("help.uninstall.choices", size=size))
    # Cancel first, with the ring: Enter alone takes nothing away.
    choice = dialogs.choose(app, "danger", title, w("help.uninstall.ask"), detail,
                            [(w("help.uninstall.keep"), "keep", "warn"), (w("help.uninstall.all"), "all", "danger")])
    if choice not in ("keep", "all"):
        return
    everything = choice == "all"
    # While files go back the dialog says so; with nothing to put back it only says what is under way.
    app.dialog = dialogs.Dialog(app.root, app.ui, "danger", title,
                                w("help.uninstall.working" if changed else "help.uninstall.working.plain"),
                                w("help.uninstall.working.detail" if changed else "help.uninstall.closes"),
                                progress=True)
    # Busy for PLAY and the other pages; removing for the window's close, which waits for the work to end.
    app.busy = app.removing = True

    def work():
        try:
            outcome = leaving.before_uninstall(app.state)
        except Exception as e:  # noqa: BLE001  (shown, never swallowed: nothing is uninstalled then)
            log.exception("uninstalling openDMT3 failed")
            app.post(lambda text=w.error(e): failed(text))
            return
        log.info("uninstalling openDMT3: put back %d game file(s); %d original(s) stay in backup",
                 len(outcome.put_back), len(outcome.stays))
        app.post(lambda: last_step(outcome))

    def failed(text):
        app.busy = app.removing = False
        if app.dialog is not None:
            app.dialog.close(None)
            app.dialog = None
        dialogs.tell(app, "error", title, w("help.uninstall.failed"), w("help.uninstall.failed.detail", error=text))

    def last_step(outcome):
        """The work is done: one last word in the launcher's own dialog (Velopack's window never shows), then the
        window closes by itself and the program goes."""
        if app.dialog is not None:
            app.dialog.close(None)
        # Said only when files went back: a folder PLAY alone used has nothing put back.
        lines = ([w("help.uninstall.done.game")] if outcome.put_back else []) + [w("help.uninstall.closes")]
        if everything:
            lines.append(w("help.uninstall.done.all"))
        app.dialog = dialogs.Dialog(app.root, app.ui, "danger", title, w("help.uninstall.done"), " ".join(lines),
                                    progress=True)
        app.root.after(LAST_STEP_MS, hand_over)

    def hand_over():
        # Velopack closes every program in the install folder before it begins: the window goes first, with the
        # settings saved and this PC's server stopped, and the uninstall starts after it (main()).
        app.then = lambda: leaving.start_uninstall(updater, everything)
        app.busy = app.removing = False
        app.close()

    threading.Thread(target=work, daemon=True, name="removing").start()
