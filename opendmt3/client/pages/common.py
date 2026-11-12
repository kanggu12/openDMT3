"""What the pages share: the plain page header, the gap between blocks, and what a page shows when this PC's
database cannot be opened."""

import os
import tkinter as tk


def _plain_header(key):
    """A page header's words: the title (the page's name in the menu) and a line under it."""
    def words(app):
        return app.words(key + ".title"), app.words(key + ".sub")
    return words


def _gap(parent, ui, height=18):
    """Vertical space between blocks, in logical pixels."""
    tk.Frame(parent, bg=parent["bg"], height=ui.px(height)).pack(fill="x")


def database_trouble(app, parent, error, bg):
    """Where this PC's players would be listed, when its database cannot be opened (damaged, or from a newer
    openDMT3): what is wrong, how to put its newest daily backup back (a damaged one; none helps with a newer one),
    and the button that opens its folder. The launcher goes on working."""
    from opendmt3.client import actions, theme, widgets
    ui, w = app.ui, app.words
    widgets.label(parent, ui, w.error(error), fg=theme.PINK, bg=bg, wrap_margin=0).pack(fill="x")
    if getattr(error, "key", None) != "error.host.db.newer":
        # A database from a newer openDMT3 is whole: its own line says what to do, and no backup is put back.
        widgets.label(parent, ui, w("db.broken.hint"), font=ui.fonts.small, fg=theme.MUTED, bg=bg,
                      wrap_margin=0).pack(fill="x", pady=(ui.px(6), 0))
    folder = os.path.dirname(app.host.path)
    widgets.Button(parent, ui, w("db.broken.open"), lambda: actions.open_folder(folder)).pack(
        anchor="w", pady=(ui.px(8), 0))
