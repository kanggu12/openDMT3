"""LAUNCHER: the language, the first-start guide, the version and its updates in one group; under it, playing without
this window beside what openDMT3 is, as OpenDMTQ's LAUNCHER page has its General and About."""

import os
import threading
import tkinter as tk

from opendmt3.client import playing, theme, updates, updating, widgets
from opendmt3.client.pages.common import Pair, card, main_button, pair_card


def _play_without_window(app, parent):
    """A desktop shortcut that plays at once, and playing when Windows starts (client/shortcuts.py), a group of their
    own on one side of a pair (`parent`)."""
    from opendmt3.client import shortcuts
    ui, w = app.ui, app.words
    quick = pair_card(parent, ui, w("about.quick"))

    def make():
        try:
            path = shortcuts.make_shortcut()
        except Exception as e:  # noqa: BLE001  (said in the status line)
            app.set_status(w("status.error", error=w.error(e)), "bad")
            return
        app.set_status(w("about.shortcut.done", name=os.path.basename(path)), "ok")

    widgets.setting_row(quick.body, ui, w("about.shortcut"),
                        lambda p: widgets.Button(p, ui, w("about.shortcut.make"), make),
                        w("about.shortcut.hint")).pack(fill="x")
    try:
        on = shortcuts.autostart()
    except Exception:  # noqa: BLE001  (not on Windows: shown off, and the switch says why when used)
        on = False

    def flip(value):
        try:
            shortcuts.autostart(value)
        except Exception as e:  # noqa: BLE001
            app.set_status(w("status.error", error=w.error(e)), "bad")
            app.go("about")
            return
        app.set_status(w("about.autostart.on" if value else "about.autostart.off"), "ok")

    widgets.divider(quick.body, ui)
    widgets.setting_row(quick.body, ui, w("about.autostart"), lambda p: widgets.Toggle(p, ui, on, flip),
                        None).pack(fill="x")


def language_options(app):
    """The language row's choices: Windows' own first (the first start's), then the two languages by name."""
    return [("system", app.words("about.language.system")), ("en", "English"), ("ko", "한국어")]


def build_about(app, parent):
    ui, w = app.ui, app.words
    general = card(parent, ui, w("about.general"))
    widgets.setting_row(general.body, ui, w("about.language"),
                        lambda p: widgets.Segmented(p, ui, language_options(app),
                                                    app.state.picked_language or "system", app.set_language)).pack(
        fill="x")

    def rerun():
        app.state.guide_done = False
        app.state.save()
        app.show()

    # The first-start guide, again: a second row of GENERAL (a card for one key said little but its name).
    widgets.divider(general.body, ui)
    widgets.setting_row(general.body, ui, w("about.guide.row"),
                        lambda p: widgets.Button(p, ui, w("about.guide.run"), rerun), None).pack(fill="x")
    # The version and the look for updates: GENERAL's last row (a card for one key said little but its name).
    widgets.divider(general.body, ui)
    version = updates.shown_version()
    # The version as the row's name and Check for updates as its control, in the column the rows above use (the
    # final review's C-08: the button once stood right after the words, on a line of its own).
    box = widgets.setting_row(general.body, ui, w("about.version", v=version),
                              # check is made below: looked up when pressed.
                              lambda p: widgets.Button(p, ui, w("about.check"), lambda: check()))
    box.pack(fill="x")
    # What the look for updates found, and the button that puts an update in: right under the version, and no
    # room taken while there is nothing to say.
    found = tk.Frame(general.body, bg=theme.PANEL)
    found.pack(fill="x")
    # Playing without this window beside what openDMT3 is: two short groups, one pair (one under the other in a small
    # window).
    pair = Pair(app, parent, last=True)
    _play_without_window(app, pair.left)

    def say(text, fg=theme.MUTED, result=None):
        """Show `text` under the version; with a `result` that has an update, its button below."""
        for child in found.winfo_children():
            child.destroy()
        widgets.label(found, ui, text, fg=fg, wrap_margin=0).pack(fill="x", pady=(ui.px(10), 0))
        if result is not None:
            # The update is the page's main action: lit while PLAY waits, quiet beside a lit PLAY.
            main_button(app, found, w("about.update_now", v=result.version), lambda: update(result)).pack(
                anchor="w", pady=(ui.px(10), 0))
        # In a small window the words (and the button) may land past the window's foot: bring them into view.
        app.body.show(found, ui.px(14))

    def check():
        say(w("about.checking"))

        def work():
            result = updates.check(updates.source_for(app.state))
            app.post(lambda: show(result))

        threading.Thread(target=work, daemon=True, name="updates").start()

    def show(result):
        if not found.winfo_exists():
            return
        if result.kind == "available":
            say(w("about.available", v=result.version), theme.TEXT, result)
            return
        say({
            "not_installed": w("about.not_installed"),
            "no_source": w("about.no_source"),
            "uptodate": w("about.uptodate"),
            "failed": w("about.update_failed", error=result.error),
        }[result.kind])

    def update(result):
        if app.busy or playing.game_running(app.session):
            # The launcher closes to update; the game (and the server on this PC) would lose it mid-song.
            say(w("about.update_busy"), theme.AMBER, result)
            return
        # The launcher's own dialogs say what happens while the update is fetched and checked, and why when it is
        # not put in; then the launcher closes and Velopack puts the update in without a window of its own and starts
        # the new launcher (client/updating.py).
        updating.run(app, result)

    legal = pair_card(pair.right, ui, w("about.legal"))
    for i, key in enumerate(("about.license", "about.notice")):
        if i:
            widgets.divider(legal.body, ui, pady=8)
        widgets.label(legal.body, ui, w(key), fg=theme.MUTED, wrap_margin=0).pack(fill="x")
