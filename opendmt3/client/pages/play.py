"""PLAY: the ready check beside the player (who plays, their records, their last game), the two as tall as each other,
under the head that says where PLAY plays."""

import tkinter as tk
from urllib.parse import urlsplit

from opendmt3.client import actions, hosting, theme, widgets

from opendmt3.client.pages.common import TITLES, Pair, Sections, database_trouble, main_button, pair_card


def where_play_plays(app):
    """The line under PLAY's title: where PLAY plays now (this PC, another server by its address, or offline), as
    OpenDMTQ's PLAY names the server it plays on."""
    w, state = app.words, app.state
    if state.mode == "this_pc":
        return w("play.on.this_pc")
    if state.mode == "server":
        # The server by its address as the player typed it, without the scheme ("192.168.0.10:4730").
        name = urlsplit(state.server_url or "").netloc
        # No server chosen yet: where the player is going to play, by the choice's own name (the final review's
        # A-08: the project's tagline said nothing of it).
        return w("play.on.server", name=name) if name else w("online.mode.server")
    return w("play.on.offline")


def _who_plays(app, parent, changed):
    """Who plays, at the top of the PLAYER group (`parent`, a part of its card made again on its own): on this PC the
    player whose card goes in (or a guest) and, right beside the choice, their records on this PC's site; on another
    server the player signed in, or the step in front of the person (Connect, Sign in), which leads to ONLINE; offline,
    that everyone plays as a guest. `changed()` makes this part again after a choice (the records' key and the line
    under the choice follow it)."""
    ui, w = app.ui, app.words
    card = parent
    line = tk.Frame(parent, bg=theme.PANEL)
    line.pack(fill="x")
    if app.state.mode == "server":
        # Another server: the signed-in player is the one; changing player means signing in again (ONLINE).
        remote_state = app.state.remote or {}
        if remote_state.get("card"):
            lamp = widgets.Lamp(line, ui, theme.NET)
            lamp.pack(side="left", anchor="n", pady=(lamp.drop, 0))
            words = widgets.label(line, ui, w("online.signed", dj=remote_state.get("dj_name", ""),
                                              login_id=remote_state.get("login_id", "")), wrap_margin=8,
                                  beside=(lamp,))
            words.pack(side="left", fill="x", expand=True, padx=(ui.px(8), 0))
            return card
        # Not signed in: the page's main action is the step in front of the person, on ONLINE (lit while PLAY waits
        # for it): Connect while no server is chosen, else Sign in; under the words that say so, at the group's left
        # edge (the group is half the page: words and key side by side ran into each other).
        chosen = bool(app.state.server_url)
        widgets.label(line, ui, w("play.who.signin" if chosen else "play.who.connect"), fg=theme.AMBER,
                      wrap_margin=0).pack(fill="x")
        main_button(app, line, w("online.signin" if chosen else "online.connect.go"),
                    lambda: app.go("online")).pack(anchor="w", pady=(ui.px(10), 0))
        return card
    if app.state.mode != "this_pc":
        # Offline: everyone is a guest; ONLINE, one press away under the words, changes it.
        widgets.label(line, ui, w("play.offline"), fg=theme.MUTED, wrap_margin=0).pack(fill="x")
        widgets.link(line, ui, TITLES["online"], lambda: app.go("online")).pack(anchor="w", pady=(ui.px(6), 0))
        return card
    try:
        rows = [(r["login_id"], "%s  (%s)" % (r["dj_name"], r["login_id"])) for r in app.player_rows()
                if not r["disabled"]]
    except hosting.HostingError as e:
        # The database cannot be read: said in place of the list, and the rest of the launcher still works.
        line.destroy()
        database_trouble(app, card, e)
        return card
    options = [(None, w("online.guest"))] + rows

    def chosen(login_id):
        app.state.player = login_id
        app.state.save()
        app.set_status(w("status.saved"), "normal")
        # The records' button and the line under the choice follow it: this card again, and no other.
        changed()

    # The choice and, beside it, the player's records: one row, which flows onto two where the group is narrow.
    parts = [widgets.Select(line, ui, options, app.state.player, chosen, width=24)]
    if app.state.player:
        # This PC's site: rankings, songs and the player's page, opened signed in (actions.records_link).
        parts.append(widgets.Button(line, ui, w("play.records"), app.open_records))
    widgets.flow(line, parts, ui.px(8))
    # A guest has no card: the line under the choice says what a guest's play is, a player's that their card goes in.
    hint = "play.who.hint" if any(app.state.player == login_id for login_id, _ in rows) else "play.who.hint.guest"
    widgets.label(card, ui, w(hint), font=ui.fonts.small, fg=theme.MUTED, wrap_margin=0).pack(
        fill="x", pady=(ui.px(8), 0))
    return card


def build_play(app, parent):
    """Two groups side by side, as tall as each other (one under the other in a small window: Pair): the ready check
    (what PLAY will do, and what stops it) and the player (who plays, their records, how their last game went). Where
    PLAY plays is the head's (pages.HEADERS). No card of instructions: how the game plays is the game's and the
    guides' (docs); no card for one choice."""
    ui, w = app.ui, app.words
    row = Pair(app, parent, last=True)
    # The ready check, filled in when the worker thread finishes it; Check again at its title's right end, as
    # OpenDMTQ's has it (the check is made again, the server asked again).
    ready = pair_card(row.left, ui, w("play.ready"))
    ready.action(w("help.recheck"), app.refresh_checks)
    app.check_box = tk.Frame(ready.body, bg=theme.PANEL)
    app.check_box.pack(fill="x")
    # Beside it, the player: who plays (made again on its own when the player changes: Sections), then, under the
    # card's faint line, how their last game went, to the ready check's foot.
    last = pair_card(row.right, ui, w("play.player"))
    sections = Sections(app, last.body)
    sections.add("who", lambda holder: _who_plays(app, holder, lambda: sections.redo("who")))
    widgets.divider(last.body, ui, pady=14)
    widgets.label(last.body, ui, w("play.last"), font=ui.fonts.body_bold, wrap_margin=0).pack(fill="x")
    widgets.label(last.body, ui, _last_session(app), fg=theme.MUTED, wrap_margin=0).pack(fill="x", pady=(ui.px(4), 0))
    for play in (app.state.last_session or {}).get("plays", [])[:plays_shown(app)]:
        # Per cleared stage: the song on its own line (titles run long), then its pattern and the score in lime.
        widgets.divider(last.body, ui, pady=8)
        widgets.label(last.body, ui, play["title"], font=ui.fonts.body_bold, wrap_margin=0).pack(fill="x")
        line = tk.Frame(last.body, bg=theme.PANEL)
        line.pack(fill="x")
        tk.Label(line, text=w("play.pattern", n=play["pattern"]), font=ui.fonts.small, fg=theme.MUTED,
                 bg=theme.PANEL).pack(side="left")
        # The score in TECHNIKA 3's score colour, in the game's heavy figures.
        tk.Label(line, text="{:,}".format(play["score"]), font=ui.fonts.figures, fg=theme.SCORE, bg=theme.PANEL).pack(
            side="right")
    refresh_checks(app)


def plays_shown(app):
    """How many of the last session's cleared stages LAST GAME lists: three, six where the window is tall (900 logical
    pixels and more), so a large window shows more of the session rather than an empty half (the final review's
    A-17); the launcher's own size keeps its three, the most that fit it whole."""
    return 6 if app.root.winfo_height() >= app.ui.px(900) else 3


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
    """Fill the ready check (PLAY page, the guide's last step) or the checks (HELP page) from app.checks: a line for
    each check, parted by the card's faint lines as OpenDMTQ's are."""
    box = getattr(app, "check_box", None)
    if box is None or not box.winfo_exists():
        return
    for child in box.winfo_children():
        child.destroy()
    ui, w = app.ui, app.words
    if app.checks is None:
        # Being made (a worker thread): said as a check line is, its lamp an outline until the answer comes.
        line = tk.Frame(box, bg=theme.PANEL)
        line.pack(fill="x")
        lamp = widgets.Lamp(line, ui, theme.MUTED, lit=False)
        lamp.pack(side="left", anchor="n", pady=(lamp.drop, 0))
        widgets.label(line, ui, w("play.checking"), fg=theme.MUTED).pack(side="left", padx=(ui.px(8), 0))
        return
    # What PLAY makes ready by itself and has not yet: several are said in one line under the list (a first start has
    # all of them), one alone by its name.
    rest = [c for c in app.checks if c.key.startswith("step:") and not c.ok]
    shown = 0

    def next_line():
        # The faint line between two checks (none before the first).
        if shown:
            widgets.divider(box, ui, pady=8)

    for check in app.checks:
        name = w("check." + check.key)
        # The folder line shows where the game is, which is what a player wants to confirm: under its name, broken
        # after its folders' separators, never inside a folder's name ("TECHNIKA / 3" once: the final review's W-07).
        path = check.detail if check.key == "folder" and check.ok else None
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
            # Pink for what went wrong; amber, lit, for what is still to do (signing in, choosing a server, closing
            # the game): the foot says it in the same colour (app.not_ready_tone; the final review's A-05).
            state = "bad" if actions.failing(check) else "todo"
            action = (lambda p=check.page: app.go(p)) if check.page else None
            # The link is named after where it leads: the GAME page's client data, the ONLINE page's sign-in.
            link = w("play.go." + check.page) if check.page else None
        # What stands under the line: why it stops PLAY, in the card's words, or a note (a modified PC client).
        under = actions.said(check, w)
        next_line()
        widgets.check_line(box, ui, state, name, link, action).pack(fill="x")
        if path:
            widgets.check_note(box, ui, path, path=True).pack(fill="x", pady=(ui.px(2), 0))
        if under:
            widgets.check_note(box, ui, under, problem=state == "bad").pack(fill="x", pady=(ui.px(2), 0))
        shown += 1
    if len(rest) > 1:
        next_line()
        widgets.check_line(box, ui, "change", w("play.rest")).pack(fill="x")
