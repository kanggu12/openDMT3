"""What PLAY is doing, in the launcher's own progress look, from the moment it is pressed until the game starts.

PLAY's first run takes a while (measured under Wine: 25 s, most of it reading the song list and copying the client
for openDMT3's folder); later ones take a few seconds. Meanwhile a dialog in the launcher's design shows each part as
it starts (actions.PHASES: the server, the song list, openDMT3's steps, starting the game) on its track, so the window
never looks still. The launcher's window shows it over its page (Shown); the desktop shortcut's PLAY, which has no
window, shows it in a window of its own (standalone).
"""

import logging
import queue
import threading

from opendmt3.client import actions, dialogs

log = logging.getLogger("opendmt3.launcher")


def phase_words(words, phase):
    """The line under the track for a part of PLAY."""
    if phase == "server":
        return words("status.server")
    if phase == "song list":
        return words("play.phase.song_list")
    if phase == "starting":
        return words("status.starting")
    return words("check.step:" + phase)


def share(phase):
    """How far PLAY is when a part starts (0 to 1): its place among every part, done or not."""
    try:
        return actions.PHASES.index(phase) / float(len(actions.PHASES))
    except ValueError:
        return None


class Shown:
    """The progress dialog over the launcher's window while PLAY gets the game ready; at() from the window's thread."""

    def __init__(self, app):
        w = app.words
        self.app = app
        # No buttons: the work cannot be stopped halfway (openDMT3's folder would be half made), and it is short.
        self.dialog = dialogs.Dialog(app.root, app.ui, "info", w("play.getting_ready.title"), w("play.getting_ready"),
                                     None, [], progress=True, status=w("status.starting"))
        app.dialog = self.dialog

    def at(self, phase):
        """A part of PLAY has started: its line, and the share on the track."""
        if not self.dialog.closed:
            self.dialog.set_progress(share(phase), phase_words(self.app.words, phase))

    def close(self):
        if not self.dialog.closed:
            self.dialog.close(None)
        if self.app.dialog is self.dialog:
            self.app.dialog = None


def standalone(language, work):
    """Run work(report) on a worker thread with the progress look in a window of its own, until work ends; returns
    what work returned, or raises what it raised. report(phase) may be called from the worker."""
    from opendmt3.client import art, i18n
    w = i18n.Words(language)
    # A window of its own over the title screen's shards, as every dialog without the launcher's window.
    root, ui = dialogs.window_root(language=language)
    shown = dialogs.Dialog(root, ui, "info", w("play.getting_ready.title"), w("play.getting_ready"), None, [],
                           progress=True, status=w("status.starting"),
                           window=lambda width, height: art.shards(width, height, seed=29),
                           on_close=lambda value: root.destroy())
    dialogs.fit(root, ui, shown)
    # Closing the window does not stop PLAY halfway: it goes on, and the game starts as it would.
    root.protocol("WM_DELETE_WINDOW", lambda: None)
    told = queue.Queue()
    outcome = {}

    def run():
        try:
            outcome["value"] = work(lambda phase: told.put(phase))
        except BaseException as e:  # noqa: BLE001  (handed to the caller)
            outcome["error"] = e
        told.put(None)

    def pump():
        while True:
            try:
                phase = told.get_nowait()
            except queue.Empty:
                break
            if phase is None:
                shown.close(None)
                return
            shown.set_progress(share(phase), phase_words(w, phase))
        root.after(50, pump)

    threading.Thread(target=run, daemon=True, name="play").start()
    root.after(50, pump)
    root.mainloop()
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("value")
