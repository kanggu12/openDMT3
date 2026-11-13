"""LAUNCHER: the language, playing without this window, updates, the first-start guide and what openDMT3 is, each on a
card as OpenDMTQ's LAUNCHER page has them."""

import os
import threading
import tkinter as tk

from opendmt3.client import playing, theme, updates, updating, widgets
from opendmt3.client.pages.common import card, main_button


def _play_without_window(app, parent):
    """A desktop shortcut that plays at once, and playing when Windows starts (client/shortcuts.py), on their card."""
    from opendmt3.client import shortcuts
    ui, w = app.ui, app.words
    quick = card(parent, ui, w("about.quick"))

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
                        w("about.autostart.hint")).pack(fill="x")


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
    _play_without_window(app, parent)
    updates_card = card(parent, ui, w("about.updates"))
    version = updates.shown_version()
    box = tk.Frame(updates_card.body, bg=theme.PANEL)
    box.pack(fill="x")
    widgets.label(box, ui, w("about.version", v=version), font=ui.fonts.body_bold).pack(side="left")
    # What the look for updates found, and the button that puts an update in: right under the version, and no
    # room taken while there is nothing to say.
    found = tk.Frame(updates_card.body, bg=theme.PANEL)
    found.pack(fill="x")

    def say(text, fg=theme.MUTED, result=None):
        """Show `text` under the version; with a `result` that has an update, its button below."""
        for child in found.winfo_children():
            child.destroy()
        widgets.label(found, ui, text, fg=fg, wrap_margin=0).pack(fill="x", pady=(ui.px(10), 0))
        if result is not None:
            # The update is the page's main action: lit while PLAY waits, quiet beside a lit PLAY.
            main_button(app, found, w("about.update_now", v=result.version), lambda: update(result)).pack(
                anchor="w", pady=(ui.px(10), 0))
        # In a small window the words (and the button) may land under the bottom bar: bring them into view.
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

    widgets.Button(box, ui, w("about.check"), check).pack(side="left", padx=(ui.px(16), 0))
    guide = card(parent, ui, w("about.guide"))

    def rerun():
        app.state.guide_done = False
        app.state.save()
        app.show()

    widgets.Button(guide.body, ui, w("about.guide.run"), rerun).pack(anchor="w")
    legal = card(parent, ui, w("about.legal"), last=True)
    for i, key in enumerate(("about.license", "about.notice")):
        if i:
            widgets.divider(legal.body, ui, pady=9)
        widgets.label(legal.body, ui, w(key), fg=theme.MUTED, wrap_margin=0).pack(fill="x")
