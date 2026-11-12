"""Unpack... on an archive's card, in the launcher's own dialogs: the password when the archive has one, where the game
folder goes with the room it needs and the room there is, the work with how far it is and the time left (and Stop,
which removes what was made), then what came of it. The work itself is client/unpack.py, on a worker thread; so is
every look at the archive, while a dialog's light sweeps.
"""

import logging
import math
import os
import threading
import time
from tkinter import filedialog

from opendmt3.client import dialogs, intake, unpack

log = logging.getLogger("opendmt3.launcher")

# How often the progress line is drawn again at most (7-Zip says its percent many times a second).
REDRAW_SECONDS = 0.2


def left_words(w, seconds):
    """The time left in words: "40 s", "4 min", "1 h 5 min" (rounded up, as a wait is felt)."""
    seconds = max(1, int(math.ceil(seconds)))
    if seconds < 60:
        return w("common.seconds", s=seconds)
    minutes = int(math.ceil(seconds / 60.0))
    if minutes < 60:
        return w("common.minutes", m=minutes)
    return w("common.hours", h=minutes // 60, m=minutes % 60)


def unpack_archive(app, found):
    """The whole of Unpack... for one archive's card. Returns the new game folder's path, or None when nothing was
    made (cancelled, stopped, or it could not be unpacked: each said in a dialog)."""
    w = app.words
    password = None
    if found.password:
        password, found = ask_password(app, found)
        if password is None:
            return None
        if found.state != intake.UNPACK:
            # With its password the archive said what it holds, and it is not a game folder to unpack.
            dialogs.tell(app, "error", w("unpack.title"), w("unpack.failed"), found.line_words(w))
            return None
    # Beside the archive unless the player picks another folder.
    parent = ask_where(app, found, unpack.default_parent(found.path))
    if parent is None:
        return None
    return work(app, found, parent, password)


def ask_password(app, found):
    """The password, asked in the launcher's dialog until it opens the archive: (the password, what the archive is
    with it), or (None, None) when the player cancels."""
    w = app.words
    # The line under the question: empty at first, then why the last try did not open it.
    detail = None
    while True:
        dialog = dialogs.Dialog(app.root, app.ui, "info", w("unpack.password.title"),
                                w.error(intake.said("error.source.password")),
                                detail, [(w("common.cancel"), None, "neutral"), (w("unpack.password.go"), True, "info")],
                                default=1, cancel=None, field="secret")
        app.dialog = dialog
        try:
            answer = dialog.wait()
        finally:
            app.dialog = None
        if not answer:
            return None, None
        password = dialog.value
        if not password:
            # Nothing typed: asked again, as at first.
            detail = w.error(intake.said("error.source.password"))
            continue
        looked = _with_password(app, found, password)
        if looked is not None:
            return password, looked
        detail = w.error(intake.said("error.source.wrong_password"))


def _with_password(app, found, password):
    """What the archive is with this password (a Found), or None when the password does not open it: checked on a
    worker while the window waits with a light that sweeps."""
    w = app.words
    answer = {}

    def check():
        try:
            if intake.password_opens(found.path, password):
                # Its names and the room it needs, now that they can be read.
                answer["found"] = intake.inspect_archive(found.path, password)
        except Exception:  # noqa: BLE001  (an archive that cannot be checked is said as one the password does not open)
            log.exception("could not check the password of %s", found.path)
        app.post(lambda: dialog.close(True))

    dialog = dialogs.Dialog(app.root, app.ui, "info", w("unpack.password.title"), w("unpack.checking"), None,
                            progress=True)
    app.dialog = dialog
    threading.Thread(target=check, daemon=True, name="password").start()
    try:
        dialog.wait()
    finally:
        app.dialog = None
    return answer.get("found")


def _where_words(w, found, parent):
    """Where the game folder goes, and the room: the dialog's detail, and whether it can go there."""
    free = unpack.room(parent)
    needed = found.needed or 0
    lines = [w("unpack.where", path=unpack.target(parent, found.path))]
    if not unpack.writable(parent):
        # A disc, a share or another user's folder: the one thing to do is to choose another.
        return "\n".join(lines + [w("unpack.not_writable")]), False
    if free is not None and needed and free < needed:
        return "\n".join(lines + [w("intake.line.no_space", needed=intake.size_words(needed),
                                    free=intake.size_words(free))]), False
    if needed:
        lines.append(w("unpack.space", needed=intake.size_words(needed),
                       free=intake.size_words(free) if free is not None else "?"))
    return "\n".join(lines), True


def ask_where(app, found, parent):
    """Where the game folder goes: beside the archive unless the player picks another folder. Returns the parent
    folder, or None when cancelled."""
    w = app.words
    while True:
        detail, fits = _where_words(w, found, parent)
        picked = {}

        def other():
            # Windows' own folder picker (the one window the launcher does not draw itself).
            folder = filedialog.askdirectory(parent=app.root, initialdir=parent, title=w("unpack.other"))
            if folder:
                picked["folder"] = os.path.normpath(folder)
                dialog.close("other")

        message = w("unpack.ask.nested" if found.inner else "unpack.ask")
        # Unpack only where it fits: else Cancel and Another folder... are the ways on.
        buttons = [(w("common.cancel"), None, "neutral")] + ([(w("unpack.go"), True, "warn")] if fits else [])
        dialog = dialogs.Dialog(app.root, app.ui, "warn", w("unpack.title"), message, detail, buttons,
                                default=len(buttons) - 1, cancel=None, link=(w("unpack.other"), other))
        app.dialog = dialog
        try:
            answer = dialog.wait()
        finally:
            app.dialog = None
        if answer == "other":
            # Asked again for the folder picked: its room may differ.
            parent = picked["folder"]
            continue
        return parent if answer else None


def work(app, found, parent, password):
    """The unpacking with its progress dialog and Stop; then what came of it. Returns the new folder, or None."""
    w = app.words
    cancel = threading.Event()
    # What the worker leaves: "folder", "stopped" or "error".
    outcome = {}
    # The whole the share is of, for "12 GB of 41 GB".
    total = found.size or found.needed or 0
    last = [0.0]
    # The dialog on screen now (a new one after Keep unpacking), for the worker's posts.
    holder = {"dialog": None}

    def progress(fraction, left):
        now = time.monotonic()
        if now - last[0] < REDRAW_SECONDS and fraction < 1.0:
            # 7-Zip says its percent often; the window draws a few times a second.
            return
        last[0] = now
        done = intake.size_words(int(total * fraction)) if total else "%d%%" % int(fraction * 100)
        whole = intake.size_words(total) if total else "100%"
        # The time left once there is a rate to tell it by.
        text = (w("unpack.progress", done=done, total=whole, left=left_words(w, left)) if left is not None
                else w("unpack.progress.early", done=done, total=whole))
        app.post(lambda: holder["dialog"] and holder["dialog"].set_progress(fraction, text))

    def run():
        try:
            outcome["folder"] = unpack.Unpacking(found.path, parent, password, progress, cancel).run()
        except unpack.Stopped:
            outcome["stopped"] = True
        except Exception as e:  # noqa: BLE001  (said in a dialog, logged, never swallowed)
            log.exception("unpacking %s failed", found.path)
            outcome["error"] = e
        # The dialog on screen closes itself: the work is over.
        app.post(lambda: holder["dialog"] and holder["dialog"].close("ended"))

    threading.Thread(target=run, daemon=True, name="unpack").start()
    while True:
        # The line under the track says the archive is being read until 7-Zip gives its first percent.
        dialog = dialogs.Dialog(app.root, app.ui, "warn", w("unpack.title"), w("unpack.working"), found.path,
                                [(w("unpack.stop"), "stop", "neutral")], default=0, cancel="stop", progress=True,
                                status=w("unpack.starting"))
        holder["dialog"] = dialog
        app.dialog = dialog
        try:
            answer = dialog.wait()
        finally:
            app.dialog = None
            holder["dialog"] = None
        if answer == "stop" and not outcome:
            # Asked first: the work goes on while the question is up, and Keep unpacking brings its dialog back.
            if not dialogs.ask(app, "danger", w("unpack.title"), w("unpack.stop.ask"), w("unpack.stop.detail"),
                               w("unpack.stop"), cancel=w("unpack.stop.keep")):
                if not outcome:
                    continue
            else:
                cancel.set()
        break
    if not outcome:
        # Stopping: 7-Zip ends at once, and what it made is removed; the light sweeps until that is done.
        waiting = dialogs.Dialog(app.root, app.ui, "warn", w("unpack.title"), w("unpack.stop.detail"), None,
                                 progress=True)
        holder["dialog"] = waiting
        app.dialog = waiting
        try:
            waiting.wait()
        finally:
            app.dialog = None
    if outcome.get("folder"):
        # Where it went, said once: the folder is listed ready and used under the dialog.
        dialogs.tell(app, "info", w("unpack.title"), w("unpack.done"), outcome["folder"])
        return outcome["folder"]
    if outcome.get("stopped"):
        dialogs.tell(app, "info", w("unpack.title"), w("unpack.stopped"))
        return None
    error = outcome.get("error")
    # Why, in the player's words: the archive damaged, a part missing, the disk full, a password...
    dialogs.tell(app, "error", w("unpack.title"), w("unpack.failed"), w.error(error) if error else None)
    return None
