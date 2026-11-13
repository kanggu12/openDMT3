"""ONLINE: where logins and records are kept (this PC, another server, offline), its players, and this PC's server
opened to the other PCs on its network, each on a card as OpenDMTQ's ONLINE has its server and its sign-in."""

import threading
import tkinter as tk

from opendmt3.client import actions, dialogs, hosting, theme, widgets
# The limits the accounts themselves check, so the add-player hint never says other numbers.
from opendmt3.server.services import accounts

from opendmt3.client.pages.common import card, database_trouble, main_button


def player_form(app, parent, on_added, bg=None):
    """ID, password, DJ name and an Add button; on_added(login_id) after the account is made. On its parent's colour
    unless told (the card it is on)."""
    ui, w = app.ui, app.words
    bg = bg or parent.cget("bg")
    form = tk.Frame(parent, bg=bg)
    fields = {}
    for col, (key, secret, width) in enumerate((("online.id", False, 10), ("online.password", True, 12),
                                                 ("online.dj", False, 10))):
        tk.Label(form, text=w(key), font=ui.fonts.small, fg=theme.MUTED, bg=bg).grid(row=0, column=col, sticky="w",
                                                                                   padx=(0, ui.px(12)))
        field = widgets.entry(form, ui, width=width, secret=secret)
        field.grid(row=1, column=col, sticky="w", padx=(0, ui.px(12)), ipady=ui.px(4))
        fields[key] = field
    message = widgets.label(parent, ui, w("online.add.hint", min=accounts.PASSWORD_MIN, max=accounts.PASSWORD_MAX), font=ui.fonts.small, fg=theme.MUTED, bg=bg,
                            wrap_margin=0)

    def add():
        from opendmt3.server.services import accounts as acc
        login_id = fields["online.id"].get().strip()
        password = fields["online.password"].get()
        dj_name = fields["online.dj"].get().strip() or login_id
        try:
            store = app.players()
        except hosting.HostingError as e:
            # The database cannot be opened: said where the form says what went wrong.
            message.configure(text=w.error(e), fg=theme.PINK)
            return
        try:
            store.create(login_id.upper(), password, dj_name, who="launcher")
        except acc.AccountError as e:
            message.configure(text=w.error(e), fg=theme.PINK)
            return
        finally:
            store.db.close()
        app.set_status(w("online.added", name=dj_name), "ok")
        on_added(login_id.upper())

    # Adding a player is the card's main action: lit while PLAY waits, quiet beside a lit PLAY.
    main_button(app, form, w("online.add"), add).grid(row=1, column=3, sticky="w")
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
    password and Sign in)."""
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
        return
    sign = card(parent, ui, w("online.signin"), last=True)
    if remote_state.get("card"):
        signed = tk.Frame(sign.body, bg=bg)
        signed.pack(fill="x")
        lamp = widgets.Lamp(signed, ui, theme.LIME)
        lamp.pack(side="left", anchor="n", pady=(lamp.drop, 0))
        widgets.label(signed, ui, w("online.signed", dj=remote_state.get("dj_name", ""),
                                    login_id=remote_state.get("login_id", "")), wrap_margin=160).pack(
            side="left", padx=(ui.px(9), 0))

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
        return
    form = tk.Frame(sign.body, bg=bg)
    form.pack(anchor="w")
    fields = {}
    for col, (key, secret) in enumerate((("online.id", False), ("online.password", True))):
        tk.Label(form, text=w(key), font=ui.fonts.small, fg=theme.MUTED, bg=bg).grid(row=0, column=col, sticky="w")
        field = widgets.entry(form, ui, width=14, secret=secret)
        field.grid(row=1, column=col, sticky="w", padx=(0, ui.px(12)), ipady=ui.px(4))
        fields[key] = field
    message = widgets.label(sign.body, ui, w("online.signin.hint"), font=ui.fonts.small, fg=theme.MUTED,
                            wrap_margin=0)

    def sign_in():
        message.configure(text=w("online.connecting"), fg=theme.MUTED)
        login_id, password = fields["online.id"].get().strip(), fields["online.password"].get()

        def work():
            try:
                me = remote.sign_in(app.state.server_url, login_id, password)
                app.post(lambda: signed_in(me))
            except Exception as e:  # noqa: BLE001
                app.post(lambda text=w.error(e): message.winfo_exists() and message.configure(text=text, fg=theme.PINK))

        threading.Thread(target=work, daemon=True, name="sign-in").start()

    def signed_in(me):
        actions.signed_in(app.state, me)
        app.state.save()
        app.refresh_checks()
        rerender()

    for field in fields.values():
        field.bind("<Return>", lambda e: sign_in())
    # Connected: typing goes to the ID; Tab to the password; Enter signs in.
    fields["online.id"].after_idle(fields["online.id"].focus_set)
    # Signing in is the card's main action: lit while PLAY waits, quiet beside a lit PLAY.
    main_button(app, form, w("online.signin"), sign_in).grid(row=1, column=2, sticky="w")
    message.pack(fill="x", pady=(ui.px(8), 0))


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
    players = card(parent, ui, w("online.players"))
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
        line = tk.Frame(players.body, bg=theme.PANEL)
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
            app.go("online")

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
            app.go("online")

        widgets.Button(line, ui, w("online.remove"), remove, kind="danger").pack(side="right")
        if not on:
            widgets.Button(line, ui, w("online.pick"), pick).pack(side="right", padx=(0, ui.px(8)))
        else:
            tk.Label(line, text=w("online.plays"), font=ui.fonts.small, fg=theme.LIME, bg=theme.PANEL).pack(
                side="right", padx=(0, ui.px(12)))
    add = card(parent, ui, w("online.add"))

    def added(login_id):
        # The first player plays next without asking; later ones are picked on this page or on PLAY.
        if not app.state.player:
            app.state.player = login_id
            app.state.save()
        app.go("online")

    player_form(app, add.body, added)
    _home_panel(app, parent)


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
