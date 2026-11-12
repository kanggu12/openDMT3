"""An update under way, in the launcher's own dialogs (the Launcher page's Update button).

While the update is fetched and checked (updates.apply, on a worker thread) a dialog in the launcher's design says
what happens; when the delta packages did not give the signed package and the whole one is fetched instead, the same
dialog says so; an update that is refused or cannot be downloaded is said in a dialog of the launcher's too, in the
player's language. Velopack shows nothing of its own (it is told to work silently), and the launcher closes once the
update is handed over.
"""

import logging
import threading

from opendmt3.core import errors
from opendmt3.client import dialogs, updates

log = logging.getLogger("opendmt3.launcher")


class Shown:
    """The dialog over the launcher's window while an update is fetched and checked; told() and close() from the
    window's thread."""

    def __init__(self, app, version):
        w = app.words
        self.app = app
        # No buttons: the launcher closes by itself once the update is handed over, and a download cut short halfway
        # leaves nothing behind (it is fetched outside the install folder).
        self.dialog = dialogs.Dialog(app.root, app.ui, "info", w("about.updating.title"),
                                     w("about.updating.message", v=version), w("about.updating.detail"), progress=True)
        app.dialog = self.dialog

    def told(self, what):
        """updates.apply said what it turned to: "whole" is the whole package instead of only what changed."""
        if what == "whole" and not self.dialog.closed:
            # In the dialog already open, so the player reads why this update takes longer than the last.
            self.dialog.set_words(detail=self.app.words("about.updating.whole"))

    def close(self):
        if not self.dialog.closed:
            self.dialog.close(None)
        if self.app.dialog is self.dialog:
            self.app.dialog = None


def run(app, result):
    """Put the update in: the dialog, then updates.apply on a worker thread (the network may be slow), then the
    launcher closes for Velopack to do the rest. A failure closes the dialog and is told in another of the launcher's
    dialogs, with the error's own words in the player's language."""
    w = app.words
    shown = Shown(app, result.version)

    def failed(text):
        shown.close()
        dialogs.tell(app, "error", w("about.update_failed.title"), w("about.apply_failed", error=text))

    def work():
        try:
            # What apply turns to is said on the window's thread: the dialog is Tk's, the worker is not.
            updates.apply(result, tell=lambda what: app.post(lambda: shown.told(what)))
        except Exception as e:  # noqa: BLE001  (shown, never swallowed)
            log.exception("the update failed")
            # In the player's language when the error has words of its own (an unsigned update, a failed download).
            app.post(lambda text=errors.say(e, app.state.language): failed(text))
            return
        log.info("closing for the update to %s", result.version)
        app.post(app.close)

    threading.Thread(target=work, daemon=True, name="update").start()
    return shown
