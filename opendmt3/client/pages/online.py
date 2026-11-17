"""ONLINE: where logins and records are kept (this PC, another server, offline), its players, and this PC's server
opened to the other PCs on its network, each on a card as OpenDMTQ's ONLINE has its server and its sign-in."""

import logging
import threading
import tkinter as tk

from opendmt3.client import actions, dialogs, hosting, theme, widgets
# The limits the accounts themselves check, so the add-player hint never says other numbers.
from opendmt3.server.services import accounts

from opendmt3.client.pages.common import Sections, card, database_trouble, main_button

log = logging.getLogger("opendmt3.launcher")


# Which field an error is about, by its words' key: said under that field (said); any other under the whole form.
ACCOUNT_FIELDS = {"error.account.id": "online.id", "error.account.taken": "online.id",
                  "error.account.password": "online.password", "error.account.dj": "online.dj"}
SIGN_IN_FIELDS = {"error.api.wrong_sign_in": "online.password", "error.api.unknown_player": "online.id"}


def said(errors, message, error, w, fields):
    """`error` in words under the field it is about (`fields`: its key to the field's), or in the form's own line
    under it all when it is about no one field (a server that does not answer, a database that cannot be read)."""
    key = fields.get(getattr(error, "key", None))
    if key in errors:
        errors[key].say(w.error(error))
    else:
        message.configure(text=w.error(error), fg=theme.PINK)


def player_form(app, parent, on_added, bg=None):
    """ID, password, DJ name and an Add button; on_added(login_id) after the account is made. On its parent's colour
    unless told (the card it is on)."""
    ui, w = app.ui, app.words
    bg = bg or parent.cget("bg")
    # Each field's name above it and what is wrong with it under it (widgets.form_fields); the password's Show.
    form, fields, errors = widgets.form_fields(parent, ui, (("online.id", w("online.id"), 10, False),
                                                            ("online.password", w("online.password"), 12, True),
                                                            ("online.dj", w("online.dj"), 10, False)), bg)
    hint = w("online.add.hint", min=accounts.PASSWORD_MIN, max=accounts.PASSWORD_MAX)
    message = widgets.label(parent, ui, hint, font=ui.fonts.small, fg=theme.MUTED, bg=bg, wrap_margin=0)

    def add():
        from opendmt3.server.services import accounts as acc
        login_id = fields["online.id"].get().strip()
        password = fields["online.password"].get()
        dj_name = fields["online.dj"].get().strip() or login_id
        # What the last try said goes: the hint again, no field marked.
        for error in errors.values():
            error.clear()
        message.configure(text=hint, fg=theme.MUTED)
        try:
            store = app.players()
        except hosting.HostingError as e:
            # The database cannot be opened: no one field's fault, said in the form's own line.
            message.configure(text=w.error(e), fg=theme.PINK)
            return
        try:
            store.create(login_id.upper(), password, dj_name, who="launcher")
        except acc.AccountError as e:
            # Under the field it is about (an ID taken or not allowed, a password too short, a DJ name too long).
            said(errors, message, e, w, ACCOUNT_FIELDS)
            return
        finally:
            store.db.close()
        app.set_status(w("online.added", name=dj_name), "ok")
        on_added(login_id.upper())

    # Adding a player is the card's main action: lit while PLAY waits, quiet beside a lit PLAY.
    main_button(app, form, w("online.add"), add).grid(row=1, column=3, sticky="nw")
    # Typing goes ID, Tab, password, Tab, DJ name, Enter: no reaching for the mouse between fields.
    for field in fields.values():
        field.bind("<Return>", lambda e: add())
    fields["online.id"].after_idle(fields["online.id"].focus_set)
    form.pack(anchor="w")
    message.pack(fill="x", pady=(ui.px(8), 0))
    return form


def server_panel(app, parent, rerender):
    """Another server, on two cards as OpenDMTQ's ONLINE has them: the server (its site's address and Connect, and the
    line under them), then the sign-in that brings back the player's card (who is signed in and Sign out, or the ID and
    password and Sign in). Returns the last card made (the guide puts its line under it)."""
    from opendmt3.client import remote
    ui, w = app.ui, app.words
    server = card(parent, ui, w("online.server"))
    bg = theme.PANEL
    row = tk.Frame(server.body, bg=bg)
    row.pack(fill="x")
    tk.Label(row, text=w("online.address"), font=ui.fonts.small, fg=theme.MUTED, bg=bg).grid(row=0, column=0, sticky="w")
    address = widgets.entry(row, ui, width=30)
    address.grid(row=1, column=0, sticky="w", padx=(0, ui.px(12)), ipady=ui.px(4))
    address.insert(0, app.state.server_url or "")
    answer = widgets.label(server.body, ui, "", font=ui.fonts.small, fg=theme.MUTED, wrap_margin=0)
    answer.pack(fill="x", pady=(ui.px(8), 0))
    remote_state = app.state.remote or {}
    connected = bool(app.state.server_url and remote_state.get("game"))
    if connected:
        answer.configure(text=w("online.connected", base=app.state.server_url, version=remote_state.get("version", "?"),
                                game=remote_state["game"]), fg=theme.LIME)

    def connect():
        answer.configure(text=w("online.connecting"), fg=theme.MUTED)
        typed = address.get()

        def work():
            try:
                base, found = actions.server_status(typed)
                app.post(lambda: connected_to(base, found))
            except Exception as e:  # noqa: BLE001  (RemoteError, or anything else: shown, never a silent stop)
                app.post(lambda text=w.error(e): answer.winfo_exists() and answer.configure(text=text, fg=theme.PINK))

        threading.Thread(target=work, daemon=True, name="connect").start()

    def connected_to(base, found):
        actions.use_server(app.state, base, found)
        app.state.save()
        app.refresh_checks()
        rerender()

    address.bind("<Return>", lambda e: connect())
    if connected:
        # Connected: connecting again is no longer the next thing to do, so the button is a quiet one.
        widgets.Button(row, ui, w("online.connect"), connect).grid(row=1, column=1, sticky="w")
    else:
        # Not connected yet: Connect is the card's main action; typing goes to the address, Enter connects.
        main_button(app, row, w("online.connect"), connect).grid(row=1, column=1, sticky="w")
        address.after_idle(address.focus_set)
        # The connection test of the address as typed, on its own card under the server's.
        return test_card(app, parent, address.get)
    sign = card(parent, ui, w("online.signin"))
    if remote_state.get("card"):
        signed = tk.Frame(sign.body, bg=bg)
        signed.pack(fill="x")
        lamp = widgets.Lamp(signed, ui, theme.LIME)
        lamp.pack(side="left", anchor="n", pady=(lamp.drop, 0))
        widgets.label(signed, ui, w("online.signed", dj=remote_state.get("dj_name", ""),
                                    login_id=remote_state.get("login_id", "")), wrap_margin=160).pack(
            side="left", padx=(ui.px(8), 0))

        def sign_out():
            # actions.sign_out's two steps, split across threads: the server ends the token first, off the window's
            # thread (one that does not answer takes a few seconds to give up), with the button greyed meanwhile;
            # then the sign-in is forgotten here, on the window's thread, whatever the server said.
            leave.enable(False)
            base, token = app.state.server_url, (app.state.remote or {}).get("token")

            def work():
                actions.end_token(base, token)
                app.post(forget)

            threading.Thread(target=work, daemon=True, name="sign-out").start()

        def forget():
            actions.signed_out(app.state)
            app.state.save()
            app.refresh_checks()
            rerender()

        leave = widgets.Button(signed, ui, w("online.signout"), sign_out)
        leave.pack(side="right")
        return test_card(app, parent, address.get)
    form, fields, errors = widgets.form_fields(sign.body, ui, (("online.id", w("online.id"), 14, False),
                                                               ("online.password", w("online.password"), 14, True)), bg)
    form.pack(anchor="w")
    # The last ID signed in with on this server, kept after signing out and across restarts (never its password).
    last_id = remote_state.get("login_id") or ""
    fields["online.id"].insert(0, last_id)
    message = widgets.label(sign.body, ui, w("online.signin.hint"), font=ui.fonts.small, fg=theme.MUTED,
                            wrap_margin=0)

    def sign_in():
        for error in errors.values():
            error.clear()
        message.configure(text=w("online.connecting"), fg=theme.MUTED)
        login_id, password = fields["online.id"].get().strip(), fields["online.password"].get()

        def work():
            try:
                me = remote.sign_in(app.state.server_url, login_id, password)
                app.post(lambda: signed_in(me))
            except Exception as e:  # noqa: BLE001
                app.post(lambda e=e: refused(e))

        threading.Thread(target=work, daemon=True, name="sign-in").start()

    def refused(error):
        if not message.winfo_exists():
            # The page went while the server was asked.
            return
        # The hint back in the form's line, then the error under the field it is about (a wrong password under the
        # password), or in that line when it is about neither field (a server that does not answer).
        message.configure(text=w("online.signin.hint"), fg=theme.MUTED)
        said(errors, message, error, w, SIGN_IN_FIELDS)

    def signed_in(me):
        actions.signed_in(app.state, me)
        app.state.save()
        app.refresh_checks()
        rerender()

    for field in fields.values():
        field.bind("<Return>", lambda e: sign_in())
    # Connected: typing goes to the ID (to the password when the ID is remembered); Tab to the next; Enter signs in.
    first = fields["online.password" if last_id else "online.id"]
    first.after_idle(first.focus_set)
    # Signing in is the card's main action: lit while PLAY waits, quiet beside a lit PLAY.
    main_button(app, form, w("online.signin"), sign_in).grid(row=1, column=2, sticky="nw")
    message.pack(fill="x", pady=(ui.px(8), 0))
    return test_card(app, parent, address.get)


# A step's lamp by its state: waiting and not run an outline, running an amber outline, passed lime, failed pink.
TEST_LAMPS = {"waiting": (theme.MUTED, False), "not_run": (theme.FAINT, False), "running": (theme.AMBER, False),
              "ok": (theme.LIME, True), "failed": (theme.PINK, True)}


def test_card(app, parent, typed):
    """The connection test's card (client/server_test.py), the page's last: its four steps one under another, each
    with its lamp, its name, what it found and its time, and under a failed one what to do; the outcome under them
    with Copy the result; Test the connection (Test again) at the card's title. It tests the address as typed
    (`typed()`) with the sign-in the launcher keeps for this server. The test runs on a thread; each step's outcome
    comes to the card as it ends, and only the card's own inside is drawn again. Its last result stays with the window
    (app.server_test) while the page is drawn again or left."""
    from opendmt3.client import server_test
    ui, w = app.ui, app.words
    made = card(parent, ui, w("server_test"), last=True)
    inside = tk.Frame(made.body, bg=theme.PANEL)
    inside.pack(fill="x")

    def draw():
        if not inside.winfo_exists():
            return
        for child in inside.winfo_children():
            child.destroy()
        kept = getattr(app, "server_test", None)
        if kept is None:
            widgets.label(inside, ui, w("server_test.idle"), fg=theme.MUTED, wrap_margin=0).pack(fill="x")
            return
        steps, running = kept["steps"], kept["running"]
        for i, step in enumerate(steps):
            if i:
                widgets.divider(inside, ui, pady=8)
            line = tk.Frame(inside, bg=theme.PANEL)
            line.pack(fill="x")
            colour, lit = TEST_LAMPS[step.state]
            lamp = widgets.Lamp(line, ui, colour, lit=lit)
            lamp.pack(side="left", anchor="n", pady=(lamp.drop, 0))
            took = "%d ms" % step.ms if step.ms is not None else ""
            # The time at the right end, in the hints' grey, as a ready check's value stands.
            tk.Label(line, text=took, font=ui.fonts.small, fg=theme.MUTED, bg=theme.PANEL).pack(side="right",
                                                                                              anchor="n")
            words = tk.Frame(line, bg=theme.PANEL)
            words.pack(side="left", fill="x", expand=True, padx=(ui.px(8), ui.px(12)))
            tk.Label(words, text=w("server_test." + step.key), font=ui.fonts.body_bold, fg=theme.TEXT,
                     bg=theme.PANEL, anchor="w").pack(fill="x")
            if step.said:
                widgets.label(words, ui, w(step.said[0], **step.said[1]), font=ui.fonts.small, fg=theme.MUTED,
                              wrap_margin=0).pack(fill="x")
            if step.fix:
                # What to do, in plain words, in the text's own colour: the step's lamp already says it failed.
                widgets.label(words, ui, w(step.fix[0], **step.fix[1]), font=ui.fonts.small, fg=theme.TEXT,
                              wrap_margin=0).pack(fill="x", pady=(ui.px(4), 0))
        widgets.divider(inside, ui, pady=8)
        foot = tk.Frame(inside, bg=theme.PANEL)
        foot.pack(fill="x")
        if running:
            said, colour = w("server_test.running"), theme.MUTED
        else:
            failed = [s for s in steps if s.state == "failed"]
            said = (w("server_test.failed", step=w("server_test." + failed[0].key + ".in")) if failed
                    else w("server_test.passed"))
            colour = theme.PINK if failed else theme.LIME
            # The whole result as text, for a message to the server's owner.
            widgets.link(foot, ui, w("server_test.copy"), copy, fg=theme.MUTED, chevron=False).pack(side="right")
        widgets.label(foot, ui, said, fg=colour, wrap_margin=0).pack(side="left", fill="x", expand=True)

    def copy():
        kept = getattr(app, "server_test", None)
        if kept is None:
            return
        app.root.clipboard_clear()
        app.root.clipboard_append(server_test.as_text(kept["steps"], w))
        app.set_status(w("server_test.copied"), "ok")

    def run():
        kept = getattr(app, "server_test", None)
        if kept is not None and kept["running"]:
            return
        address_typed = typed()
        app.server_test = {"steps": [server_test.Step(key) for key in server_test.STEPS], "running": True}
        button.enable(False)
        draw()

        def report(steps):
            # A copy of each step as it is now, for the window's thread (the worker goes on changing them).
            shown = [_copy_step(s) for s in steps]
            app.post(lambda: shown_now(shown, True))

        def work():
            try:
                steps = server_test.run(address_typed, app.state, report)
            except Exception:  # noqa: BLE001  (logged; the card says where it stopped)
                log.exception("the connection test failed")
                steps = app.server_test["steps"]
            app.post(lambda: shown_now([_copy_step(s) for s in steps], False))

        threading.Thread(target=work, daemon=True, name="server-test").start()

    def shown_now(steps, running):
        app.server_test = {"steps": steps, "running": running}
        if button.winfo_exists():
            button.enable(not running)
            button.set_text(w("server_test.again"))
        draw()

    tested = getattr(app, "server_test", None) is not None
    button = made.action(w("server_test.again" if tested else "server_test.run"), run)
    running_now = tested and app.server_test["running"]
    button.enable(not running_now)
    draw()
    return made


def _copy_step(step):
    """A step as it is now (server_test.Step), apart from the one the worker goes on changing."""
    from opendmt3.client import server_test
    made = server_test.Step(step.key)
    made.state, made.ms, made.said, made.fix = step.state, step.ms, step.said, step.fix
    return made


def build_online(app, parent):
    """Where you play on its card; then another server's two cards (server_panel), or this PC's players, the form that
    adds one and this PC's server for the other PCs on its network, each on its card."""
    ui, w = app.ui, app.words
    mode = app.state.mode

    def set_mode(value):
        app.state.mode = value
        app.state.save()
        app.read_song_list_ahead()
        if value != "this_pc" and app.state.lan and app.host.running and app.session is None:
            # Open to the other PCs on this network only while playing on this PC.
            threading.Thread(target=app.host.stop, daemon=True, name="lan").start()
        app.refresh_checks()
        app.go("online")

    where = card(parent, ui, w("online.where"), last=mode == "offline")
    widgets.setting_row(where.body, ui, w("online.mode"),
                        lambda p: widgets.Segmented(p, ui, [("this_pc", w("online.mode.this_pc")),
                                                            ("server", w("online.mode.server")),
                                                            ("offline", w("online.mode.offline"))], mode, set_mode),
                        w("online.mode.hint." + mode)).pack(fill="x")
    if mode == "server":
        server_panel(app, parent, lambda: app.go("online"))
        return
    if mode != "this_pc":
        return
    # The players and the form that adds one, each a card made again on its own when a player is added, chosen or
    # deleted (Sections): the other cards, and what is typed in the form, stay as they were.
    sections = Sections(app, parent)

    def players_card(holder):
        players = card(holder, ui, w("online.players"))
        try:
            rows = app.player_rows()
        except hosting.HostingError as e:
            # The database cannot be read: said in place of the list, and the rest of the page still works.
            database_trouble(app, players.body, e)
            return
        if not rows:
            widgets.label(players.body, ui, w("online.players.none"), fg=theme.MUTED, wrap_margin=0).pack(fill="x")
        for i, r in enumerate(rows):
            if i:
                # One line a player, parted by the card's faint lines.
                widgets.divider(players.body, ui, pady=8)
            _player_line(app, players.body, r, lambda: sections.redo("players"))

    def add_card(holder):
        add = card(holder, ui, w("online.add"))

        def added(login_id):
            # The first player plays next without asking; later ones are picked on this page or on PLAY.
            if not app.state.player:
                app.state.player = login_id
                app.state.save()
            # The list with the new player, and the form empty again for the next one.
            sections.redo("players")
            sections.redo("add")

        player_form(app, add.body, added)

    sections.add("players", players_card)
    sections.add("add", add_card)
    _home_panel(app, parent)


def _player_line(app, parent, r, changed):
    """One player on the Players card: the lamp lit for the one who goes in at PLAY, the DJ name and ID, Delete, and
    Play next for the others; `changed()` makes the card again after a choice."""
    ui, w = app.ui, app.words
    line = tk.Frame(parent, bg=theme.PANEL)
    line.pack(fill="x")
    on = r["login_id"] == app.state.player
    # The player who goes in at PLAY has the lit lamp.
    widgets.Lamp(line, ui, ui.section["accent"] if on else theme.MUTED, lit=on).pack(side="left")
    tk.Label(line, text=r["dj_name"], font=ui.fonts.body_bold, fg=theme.TEXT, bg=theme.PANEL).pack(
        side="left", padx=(ui.px(10), ui.px(8)))
    tk.Label(line, text=r["login_id"], font=ui.fonts.small, fg=theme.MUTED, bg=theme.PANEL).pack(side="left")

    def pick(login_id=r["login_id"]):
        app.state.player = login_id
        app.state.save()
        changed()

    def remove(login_id=r["login_id"], name=r["dj_name"]):
        if not dialogs.ask(app, "danger", w("online.remove.title"), w("online.remove.ask", name=name),
                           w("online.remove.detail"), w("online.remove")):
            return
        try:
            store = app.players()
        except hosting.HostingError as e:
            app.set_status(w("status.error", error=w.error(e)), "bad")
            return
        try:
            store.delete(login_id, who="launcher")
        finally:
            store.db.close()
        if app.state.player == login_id:
            app.state.player = None
            app.state.save()
        changed()

    widgets.Button(line, ui, w("online.remove"), remove, kind="danger").pack(side="right")
    if not on:
        widgets.Button(line, ui, w("online.pick"), pick).pack(side="right", padx=(0, ui.px(8)))
    else:
        tk.Label(line, text=w("online.plays"), font=ui.fonts.small, fg=theme.LIME, bg=theme.PANEL).pack(
            side="right", padx=(0, ui.px(12)))


def _home_panel(app, parent):
    """Open this PC's server to the other PCs on its network, on the page's last card: they choose Another server and
    type one of these addresses, then sign in with a player made here."""
    ui, w = app.ui, app.words
    home = card(parent, ui, w("online.home"), last=True)
    found = app.host.addresses() if app.state.lan else []
    # The hint names the addresses only while they are listed under it: off (or with no address) it says what the
    # switch is for.
    widgets.setting_row(home.body, ui, w("online.home.open"),
                        lambda p: widgets.Toggle(p, ui, app.state.lan, app.set_lan),
                        w("online.home.hint.on" if found else "online.home.hint")).pack(fill="x")
    if not app.state.lan:
        return
    if not found:
        # Still starting, or open with no address to reach it at: the second in the colour of something to look at.
        waiting = not app.host.running
        widgets.label(home.body, ui, w("online.home.starting") if waiting else w("online.home.none"),
                      fg=theme.MUTED if waiting else theme.AMBER, wrap_margin=0).pack(fill="x", pady=(ui.px(10), 0))
        return
    widgets.divider(home.body, ui)
    for address in found:
        widgets.label(home.body, ui, address, font=ui.fonts.body_bold).pack(anchor="w")
    widgets.label(home.body, ui, w("online.home.firewall"), font=ui.fonts.small, fg=theme.MUTED, wrap_margin=0).pack(
        fill="x", pady=(ui.px(6), 0))
