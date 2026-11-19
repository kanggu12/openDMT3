"""PLAY: the ready check (a status panel) beside the player (the member's plate with their platinum card), and under
them the last game as the game's result panel, under the head that says where PLAY plays."""

import tkinter as tk
from urllib.parse import urlsplit

from PIL import ImageTk

from opendmt3.client import actions, art, hosting, theme, widgets

from opendmt3.client.pages.common import TITLES, Pair, Sections, card, database_trouble, main_button, pair_card


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
    rows, trouble = [], None
    if app.state.mode == "this_pc":
        try:
            rows = [r for r in app.player_rows() if not r["disabled"]]
        except hosting.HostingError as e:
            # The database cannot be read: said in place of the list, below.
            trouble = e
    remote_state = app.state.remote or {}
    # The one whose card goes in, held as the member's platinum card (CARDS.md "member"): this PC's chosen player, or
    # the player signed in on another server; none for a guest, offline or before a sign-in.
    member = None
    if app.state.mode == "this_pc":
        member = next(((r["dj_name"], r["login_id"]) for r in rows if r["login_id"] == app.state.player), None)
    elif app.state.mode == "server" and remote_state.get("card"):
        member = (remote_state.get("dj_name", ""), remote_state.get("login_id", ""))
    # The card at the left, as a card is held (or its empty place: no card goes in); who plays and their records, or
    # the step in front of the person, beside it.
    top = tk.Frame(parent, bg=parent.cget("bg"))
    top.pack(fill="x")
    if member is not None:
        picture = art.member_card(member[0], member[1], ui.scale)
    else:
        picture = art.member_slot(w("play.no_card"), ui.scale)
    image = ImageTk.PhotoImage(picture, master=top)
    shown = tk.Label(top, image=image, bg=top.cget("bg"), bd=0)
    # Kept on the label: Tk shows a picture only while Python holds it; the words ride along for the tests, and it is
    # the card's content, an object (compose.py).
    shown.image, shown.opendmt3_picture, shown.words, shown.opendmt3_object = image, picture, member, True
    shown.pack(side="left", anchor="n", padx=(0, ui.px(16)))
    card_ = tk.Frame(top, bg=top.cget("bg"))
    card_.pack(side="left", fill="x", expand=True, anchor="n")
    line = tk.Frame(card_, bg=card_.cget("bg"))
    line.pack(fill="x")
    if app.state.mode == "server":
        # Another server: the signed-in player is the one; changing player means signing in again (ONLINE).
        if remote_state.get("card"):
            lamp = widgets.Lamp(line, ui, theme.NET)
            lamp.pack(side="left", anchor="n", pady=(lamp.drop, 0))
            words = widgets.label(line, ui, w("online.signed", dj=remote_state.get("dj_name", ""),
                                              login_id=remote_state.get("login_id", "")), wrap_margin=8,
                                  beside=(lamp,))
            words.pack(side="left", fill="x", expand=True, padx=(ui.px(8), 0))
            return parent
        # Not signed in: the page's main action is the step in front of the person, on ONLINE (lit while PLAY waits
        # for it): Connect while no server is chosen, else Sign in; under the words that say so, at the group's left
        # edge (the group is half the page: words and key side by side ran into each other).
        chosen = bool(app.state.server_url)
        widgets.label(line, ui, w("play.who.signin" if chosen else "play.who.connect"), fg=theme.AMBER,
                      wrap_margin=0).pack(fill="x")
        main_button(app, line, w("online.signin" if chosen else "online.connect.go"),
                    lambda: app.go("online")).pack(anchor="w", pady=(ui.px(10), 0))
        return parent
    if app.state.mode != "this_pc":
        # Offline: everyone is a guest; ONLINE, one press away under the words, changes it.
        widgets.label(line, ui, w("play.offline"), fg=theme.MUTED, wrap_margin=0).pack(fill="x")
        widgets.link(line, ui, TITLES["online"], lambda: app.go("online")).pack(anchor="w", pady=(ui.px(6), 0))
        return parent
    if trouble is not None:
        # The database cannot be read: said in place of the list, and the rest of the launcher still works.
        line.destroy()
        database_trouble(app, card_, trouble)
        return parent
    rows = [(r["login_id"], "%s  (%s)" % (r["dj_name"], r["login_id"])) for r in rows]
    options = [(None, w("online.guest"))] + rows

    def chosen(login_id):
        app.state.player = login_id
        app.state.save()
        app.set_status(w("status.saved"), "normal")
        # The records' button and the line under the choice follow it: this card again, and no other.
        changed()

    # The choice and, beside it, the player's records: one row, which flows onto two where the group is narrow (beside
    # the card, the choice as wide as a DJ name and its ID take).
    parts = [widgets.Select(line, ui, options, app.state.player, chosen, width=16 if member else 24)]
    if app.state.player:
        # This PC's site: rankings, songs and the player's page, opened signed in (actions.records_link).
        parts.append(widgets.Button(line, ui, w("play.records"), app.open_records))
    widgets.flow(line, parts, ui.px(8))
    # A guest has no card: the line under the choice says what a guest's play is, a player's that their card goes in.
    hint = "play.who.hint" if any(app.state.player == login_id for login_id, _ in rows) else "play.who.hint.guest"
    widgets.label(card_, ui, w(hint), font=ui.fonts.small, fg=theme.MUTED, wrap_margin=0).pack(
        fill="x", pady=(ui.px(8), 0))
    return parent


def build_play(app, parent):
    """The ready check (a status panel: what PLAY will do and what stops it, its lamp for the whole) beside the player
    (the member's plate: their platinum card, who plays, their records), each as tall as what it holds (one under the
    other in a small window: Pair); under them, the full width, the last game as the game's result panel. Where PLAY
    plays is the head's (pages.HEADERS). No card of instructions: how the game plays is the game's and the guides'
    (docs); no card for one choice."""
    ui, w = app.ui, app.words
    row = Pair(app, parent)
    # The ready check, filled in when the worker thread finishes it; Check again at its title's right end, as
    # OpenDMTQ's has it (the check is made again, the server asked again); its lamp follows the whole check.
    ready = pair_card(row.left, ui, w("play.ready"), kind="status")
    ready.action(w("help.recheck"), app.refresh_checks)
    app.check_card = ready
    app.check_box = tk.Frame(ready.body, bg=ready.body.cget("bg"))
    app.check_box.pack(fill="x")
    # Beside it, the player: their card and who plays (made again on its own when the player changes: Sections).
    # The two end on one line (Pair): the shorter one's body grows to the row's height, its content at its top; the
    # ready check's sunken screen ends with its rows, the plate under it the plate's own face.
    player = pair_card(row.right, ui, w("play.player"), kind="member")
    sections = Sections(app, player.body)
    sections.add("who", lambda holder: _who_plays(app, holder, lambda: sections.redo("who")))
    # Under them, the full width: the last game as the game's result panel, a card of its own.
    result = card(parent, ui, w("play.last"), last=True, kind="result")
    widgets.label(result.body, ui, _last_session(app), fg=theme.MUTED, wrap_margin=0).pack(fill="x")
    for play in (app.state.last_session or {}).get("plays", [])[:plays_shown(app)]:
        # Per cleared stage: the song on its own line (titles run long: they wrap there, never cut), then its pattern
        # on the game's chip and the score at the right end, in the game's heavy figures and its score colour.
        widgets.divider(result.body, ui, pady=8)
        widgets.label(result.body, ui, play["title"], font=ui.fonts.body_bold, wrap_margin=0).pack(fill="x")
        line = tk.Frame(result.body, bg=result.body.cget("bg"))
        line.pack(fill="x", pady=(ui.px(4), 0))
        words = w("play.pattern", n=play["pattern"])
        chip = art.name_plate(words.upper(), ui.scale, fill=theme.WELL_LIGHT)
        chip_image = ImageTk.PhotoImage(chip, master=line)
        badge = tk.Label(line, image=chip_image, bg=line.cget("bg"), bd=0)
        badge.image, badge.opendmt3_picture, badge.words = chip_image, chip, words
        badge.pack(side="left")
        tk.Label(line, text="{:,}".format(play["score"]), font=ui.fonts.figures, fg=theme.SCORE,
                 bg=line.cget("bg")).pack(side="right")
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
    # The status panel's lamp for the whole check (CARDS.md "status"), as the foot says it: an outline while it is
    # made, pink when something went wrong, amber when something is still to do, green when PLAY can go.
    panel = getattr(app, "check_card", None)
    if panel is not None and panel.winfo_exists() and _inside(box, panel):
        if app.checks is None:
            panel.state("quiet")
        elif any(not c.ok and actions.failing(c) for c in app.checks):
            panel.state("bad")
        elif any(not c.ok and not c.key.startswith("step:") for c in app.checks):
            panel.state("todo")
        else:
            panel.state("ready")
    if app.checks is None:
        # Being made (a worker thread): said as a check line is, its lamp an outline until the answer comes.
        line = tk.Frame(box, bg=box.cget("bg"))
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


def _inside(widget, box):
    """True when `widget` is `box` or under it (the check's lines in the card whose lamp says them)."""
    while widget is not None:
        if widget is box:
            return True
        widget = widget.master
    return False
