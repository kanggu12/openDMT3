"""PLAY: who plays, the ready check, how to play and the last session."""

import tkinter as tk

from opendmt3.client import actions, hosting, theme, widgets

from opendmt3.client.pages.common import _gap, database_trouble


def _who_plays(app, parent):
    """The card that goes in at PLAY: a player on this PC, or a guest; offline says how to go online. Returns the
    card, whose body takes the player's records under the choice."""
    ui, w = app.ui, app.words
    card = widgets.Card(parent, ui, title=w("play.who"))
    card.pack(fill="x", pady=(0, ui.px(16)))
    line = tk.Frame(card.body, bg=theme.PANEL)
    line.pack(fill="x")
    if app.state.mode == "server":
        # Another server: the signed-in player is the one; changing player means signing in again (Online).
        remote_state = app.state.remote or {}
        text = (w("online.signed", dj=remote_state.get("dj_name", ""), login_id=remote_state.get("login_id", ""))
                if remote_state.get("card") else w("play.who.signin"))
        widgets.label(line, ui, text, fg=theme.TEXT if remote_state.get("card") else theme.AMBER, bg=theme.PANEL,
                      wrap_margin=0).pack(side="left", fill="x", expand=True)
        return card
    if app.state.mode != "this_pc":
        widgets.label(line, ui, w("play.offline"), fg=theme.MUTED, bg=theme.PANEL, wrap_margin=0).pack(
            side="left", fill="x", expand=True)
        return card
    try:
        rows = [(r["login_id"], "%s  (%s)" % (r["dj_name"], r["login_id"])) for r in app.player_rows()
                if not r["disabled"]]
    except hosting.HostingError as e:
        # The database cannot be read: said in place of the list, and the rest of the launcher still works.
        line.destroy()
        database_trouble(app, card.body, e, theme.PANEL)
        return card
    options = [(None, w("online.guest"))] + rows

    def chosen(login_id):
        app.state.player = login_id
        app.state.save()
        app.set_status(w("status.saved"), "normal")

    widgets.Select(line, ui, options, app.state.player, chosen, width=26).pack(side="left")
    # A guest has no card: the line under the choice says what a guest's play is, a player's that their card goes in.
    hint = "play.who.hint" if any(app.state.player == login_id for login_id, _ in rows) else "play.who.hint.guest"
    widgets.label(card.body, ui, w(hint), font=ui.fonts.small, fg=theme.MUTED, bg=theme.PANEL,
                  wrap_margin=0).pack(fill="x", pady=(ui.px(8), 0))
    return card


def card_goes_in(app):
    """True when PLAY puts a card in: a player chosen on this PC, or a sign-in on another server."""
    if app.state.mode == "this_pc":
        return bool(app.state.player)
    return app.state.mode == "server" and bool((app.state.remote or {}).get("card"))


def how_to_play(app):
    """The How to play lines, in order: the third by who plays (a card logs in by itself; a guest presses NO ID
    CARD), the last how to leave the game (no key does: the bar at the top edge has the X)."""
    return ("play.how.1", "play.how.2", "play.how.3.card" if card_goes_in(app) else "play.how.3", "play.how.4")


def build_play(app, parent):
    """Two columns, so the page shows whole in the window the launcher opens at, after a session of three cleared
    stages too: on the left who plays (with their records) over the ready check, on the right how to play and the
    last session. With who plays across the whole width over them, the page after such a session ran 147 to 276 px
    under the bottom bar there with Windows' fonts (100 to 200 %), and 152 to 170 on Linux."""
    ui, w = app.ui, app.words
    row = tk.Frame(parent, bg=theme.BG)
    row.pack(fill="x")
    row.columnconfigure(0, weight=3, uniform="cards")
    row.columnconfigure(1, weight=2, uniform="cards")
    # The left column: as tall as the card beside it, its last card stretched to the same foot.
    left = tk.Frame(row, bg=theme.BG)
    left.grid(row=0, column=0, sticky="nsew", padx=(0, ui.px(16)))
    who = _who_plays(app, left)
    if app.state.mode == "this_pc" and app.state.player:
        # This PC's site: rankings, songs and the player's page, opened signed in (actions.records_link): the chosen
        # player's records, under the choice.
        widgets.Button(who.body, ui, w("play.records"), app.open_records).pack(anchor="w", pady=(ui.px(12), 0))
        widgets.label(who.body, ui, w("play.records.hint"), font=ui.fonts.small, fg=theme.MUTED, bg=theme.PANEL,
                      wrap_margin=0).pack(fill="x", pady=(ui.px(6), 0))
    # Under it, the ready check, filled in when the worker thread finishes it.
    ready = widgets.Card(left, ui, title=w("play.ready"))
    ready.pack(fill="both", expand=True)
    app.check_box = tk.Frame(ready.body, bg=theme.PANEL)
    app.check_box.pack(fill="x")
    # Right: how to play, and how the last session went.
    how = widgets.Card(row, ui, title=w("play.how"))
    how.grid(row=0, column=1, sticky="nsew")
    for key in how_to_play(app):
        widgets.label(how.body, ui, w(key), bg=theme.PANEL, fg=theme.TEXT, wrap_margin=0).pack(
            fill="x", pady=(0, ui.px(6)))
    _gap(how.body, ui, 10)
    widgets.section(how.body, ui, w("play.last"), bg=theme.PANEL).pack(fill="x", pady=(0, ui.px(10)))
    widgets.label(how.body, ui, _last_session(app), bg=theme.PANEL, fg=theme.MUTED, wrap_margin=0).pack(fill="x")
    for play in (app.state.last_session or {}).get("plays", []):
        # Per cleared stage: the song on its own line (titles run long), then its pattern and the score in lime.
        widgets.label(how.body, ui, play["title"], font=ui.fonts.body_bold, bg=theme.PANEL, wrap_margin=0).pack(
            fill="x", pady=(ui.px(8), 0))
        line = tk.Frame(how.body, bg=theme.PANEL)
        line.pack(fill="x")
        tk.Label(line, text=w("play.pattern", n=play["pattern"]), font=ui.fonts.small, fg=theme.MUTED,
                 bg=theme.PANEL).pack(side="left")
        tk.Label(line, text="{:,}".format(play["score"]), font=ui.fonts.display, fg=theme.LIME, bg=theme.PANEL).pack(
            side="right")
    refresh_checks(app)


def _last_session(app):
    record, w = app.state.last_session, app.words
    if not record:
        return w("play.last.none")
    minutes = record.get("seconds", 0) // 60
    span = w("common.minutes", m=minutes) if minutes else w("common.seconds", s=record.get("seconds", 0))
    # Records from before the verdict was stored fall back to the dump count.
    crashed = record.get("crashed", record.get("dumps", 0) > 0)
    return w("play.last.crash" if crashed else "play.last.ok", time=span)


def refresh_checks(app):
    """Fill the ready check (PLAY page) or the checks (Help page) from app.checks."""
    box = getattr(app, "check_box", None)
    if box is None or not box.winfo_exists():
        return
    for child in box.winfo_children():
        child.destroy()
    ui, w = app.ui, app.words
    if app.checks is None:
        widgets.label(box, ui, "...", bg=theme.PANEL, fg=theme.MUTED).pack(anchor="w")
        return
    # What PLAY makes ready by itself and has not yet: several are said in one line under the list (a first start has
    # all of them), one alone by its name.
    rest = [c for c in app.checks if c.key.startswith("step:") and not c.ok]
    for check in app.checks:
        name = w("check." + check.key)
        if check.key == "folder" and check.ok:
            # The folder line shows where the game is, which is what a player wants to confirm.
            name = "%s  ·  %s" % (name, check.detail)
        link = None
        if check.ok:
            state, action = "ok", None
        elif check.key.startswith("step:"):
            if len(rest) > 1:
                continue
            # PLAY does this by itself; the line only says it will.
            state, action = "change", None
            name = "%s  ·  %s" % (name, w("play.will_change"))
        else:
            state = "bad"
            action = (lambda p=check.page: app.go(p)) if check.page else None
            # The link is named after where it leads: the Game page's folder, the Online page's sign-in.
            link = w("play.go." + check.page) if check.page else None
        # What stands under the line: why it stops PLAY, in the card's words, or a note (a modified PC client).
        under = actions.said(check, w)
        widgets.check_line(box, ui, state, name, link, action).pack(fill="x", pady=(0, ui.px(2 if under else 7)))
        if under:
            widgets.check_note(box, ui, under, problem=not check.ok).pack(fill="x", pady=(0, ui.px(7)))
    if len(rest) > 1:
        widgets.check_line(box, ui, "change", w("play.rest")).pack(fill="x", pady=(0, ui.px(7)))
