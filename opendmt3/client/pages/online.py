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


# Which field an error is about, by its words' key: said under that field; any other in the form's own line. The
# server answers one code for a wrong ID and a wrong password alike (so that nobody learns which IDs it has): said
# under the password, with both fields' edges in the error's colour.
ACCOUNT_FIELDS = {"error.account.id": "online.id", "error.account.taken": "online.id",
                  "error.account.password": "online.password", "error.account.dj": "online.dj"}
SIGN_IN_FIELDS = {"error.api.wrong_sign_in": "online.password", "error.account.id": "online.id",
                  "error.account.password": "online.password"}
# How many characters a form's fields are wide (FORMS.md: as wide as the longest real value plus room): an ID and a
# DJ name 12, a password 16 (and Show), an address 32; and the sign-in's width (logical pixels: the site's door holds
# its fields 364 px wide in a 420 px card; at the launcher's scale, 340).
ID_CHARS, PASSWORD_CHARS, ADDRESS_CHARS, SIGN_IN_WIDTH = 12, 16, 32, 340


def _main(app):
    """A form's key as a page's main action (pages.main_button: lit while PLAY waits, quiet beside a lit PLAY)."""
    return lambda parent, words, command, size, fill: main_button(app, parent, words, command, size, fill)


def _plain(app):
    """A form's key in the quiet metal: what the form does is no longer the next thing to do."""
    return lambda parent, words, command, size, fill: widgets.Button(parent, app.ui, words, command, size=size,
                                                                     fill=fill)


def said(form, error, w, fields, action=None):
    """`error` in words under the field it is about (`fields`: its words' key to the field's key), or in the form's
    own line under it all when it is about no one field (a server that does not answer, a database that cannot be
    read), with `action` (words, command) as the way on."""
    key = fields.get(getattr(error, "key", None))
    if key in form.fields:
        form.say(key, w.error(error))
    else:
        form.tell(w.error(error), "bad", action)


def player_form(app, parent, on_added, bg=None):
    """A player made on this PC (FORMS.md's side-by-side form): the ID, the password with Show and the DJ name in one
    row, each named over its field with what it takes under it (the accounts' own limits: services/accounts.py), and
    Add a player in the fields' row; on_added(login_id) after the account is made. Typing goes ID, Tab, the password,
    Tab (its Show), Tab, the DJ name; Enter in any field adds the player. What is wrong is said under the field it is
    about, in place of what it takes."""
    ui, w = app.ui, app.words
    form = widgets.Form(parent, ui, bg=bg)
    form.pack(fill="x")
    form.field("online.id", w("online.id"), width=ID_CHARS, row=0, column=0, placeholder=w("online.id.example"),
               hint=w("online.id.hint", max=accounts.ID_MAX))
    form.field("online.password", w("online.password"), width=PASSWORD_CHARS, secret=True, row=0, column=1,
               hint=w("online.password.hint", min=accounts.PASSWORD_MIN, max=accounts.PASSWORD_MAX))
    form.field("online.dj", w("online.dj"), width=ID_CHARS, row=0, column=2, placeholder=w("online.dj.example"),
               hint=w("online.dj.hint", max=accounts.DJ_NAME_MAX))

    def add():
        from opendmt3.server.services import accounts as acc
        login_id = form.fields["online.id"].get().strip()
        password = form.fields["online.password"].get()
        dj_name = form.fields["online.dj"].get().strip() or login_id
        # What the last try said goes: every field's hint again, no line over the key.
        form.clear()
        form.tell(None)
        try:
            store = app.players()
        except hosting.HostingError as e:
            # The database cannot be opened: no one field's fault, said in the form's own line.
            form.tell(w.error(e), "bad")
            form.into_view()
            return
        try:
            store.create(login_id.upper(), password, dj_name, who="launcher")
        except acc.AccountError as e:
            # Under the field it is about (an ID taken or not allowed, a password too short, a DJ name too long), on
            # the screen.
            said(form, e, w, ACCOUNT_FIELDS)
            form.into_view()
            return
        finally:
            store.db.close()
        app.set_status(w("online.added", name=dj_name), "ok")
        on_added(login_id.upper())

    # Adding a player is the card's main action: lit while PLAY waits, quiet beside a lit PLAY; in the fields' row.
    form.button(w("online.add"), add, row=0, column=3, beside=True, main=_main(app))
    form.fields["online.id"].after_idle(form.fields["online.id"].focus_set)
    return form


def server_panel(app, parent, rerender, lead=None):
    """Another server, on its cards as OpenDMTQ's ONLINE has them: the server (its site's address and Connect, and how
    it stands under them), the sign-in (the server it signs in to, the ID and the password, Sign in; or who is signed
    in, where, and Sign out), and the connection test. Returns the last card made (the guide puts its line in it).

    Connected with nobody signed in, signing in is the next thing to do: its card leads the page, before `lead` (the
    Where you play card), so that the whole of it, its key included, is on the screen at the window's smallest size
    whatever it says; the server it signs in to is its first line, with Change, and the server's own card is folded
    away into that line. Change opens the server's card as it is before connecting (its address chosen whole to type
    over, Connect the main action, no sign-in until a server answers; app.server_open: the address it was opened
    for, forgotten once a server answers or the page is left)."""
    ui = app.ui
    remote_state = app.state.remote or {}
    connected = bool(app.state.server_url and remote_state.get("game"))
    signing_in = connected and not remote_state.get("card")
    # The server's card folds into the sign-in's first line, unless Change opened it for this very address.
    changing = signing_in and getattr(app, "server_open", None) == app.state.server_url
    folded = signing_in and not changing
    # The connection test's card, made last: a failure's line leads to it (filled in once it is made).
    tester = {}

    def test_link():
        """The way from a failure to the connection test: its card in view, the test run."""
        made = tester.get("card")
        if made is not None and made.winfo_exists():
            app.body.show(made, ui.px(16))
            made.run()

    def change():
        """Change, on the sign-in's server line: the server's card open again, its address ready to type over."""
        app.server_open = app.state.server_url
        rerender()

    # The address the connection test checks: the one typed in the server's card, or the one connected to.
    typed = (lambda: app.state.server_url or "") if folded else _server_card(app, parent, rerender,
                                                                            connected and not changing, test_link,
                                                                            changing)
    if not connected or changing:
        return _test_card_for(app, parent, typed, tester)
    if remote_state.get("card"):
        _signed_card(app, parent, remote_state, rerender)
    else:
        sign = _sign_in_card(app, parent, remote_state, rerender, test_link, None if not folded else change)
        if lead is not None and lead.winfo_exists():
            # First on the page: the next thing to do, whole on the screen.
            sign.pack_configure(before=lead)
    return _test_card_for(app, parent, typed, tester, rerender)


def _server_card(app, parent, rerender, connected, test_link, changing=False):
    """The server's card: its site's address, named over its field with an example of one in it, Connect on the
    field's line, and how it stands under them; `changing`, opened by Change, the address chosen whole so that typing
    replaces it. Returns the way to read the address typed."""
    ui, w = app.ui, app.words
    remote_state = app.state.remote or {}
    server = card(parent, ui, w("online.server"))
    place = widgets.Form(server.body, ui)
    place.pack(fill="x")
    address = place.field("address", w("online.address"), width=ADDRESS_CHARS,
                          placeholder=w("online.address.example"), row=0, column=0)
    address.refresh()
    address.insert(0, app.state.server_url or "")
    if connected:
        place.tell(w("online.connected", base=app.state.server_url, version=remote_state.get("version", "?"),
                     game=remote_state["game"]), "ok")

    def connect():
        place.tell(w("online.connecting"))
        address.set_error(False)
        place.busy(True)
        typed = address.get()

        def work():
            try:
                base, found = actions.server_status(typed)
                app.post(lambda: connected_to(base, found))
            except Exception as e:  # noqa: BLE001  (RemoteError, or anything else: shown, never a silent stop)
                app.post(lambda e=e: refused(e))

        threading.Thread(target=work, daemon=True, name="connect").start()

    def refused(error):
        if not address.winfo_exists():
            # The page went while the server was asked.
            return
        place.busy(False)
        # The address is what the server's answer is about: its edge says so, the line under it why, and the way to
        # the test that finds the step that fails.
        address.set_error(True)
        place.tell(w.error(error), "bad", (w("server_test.run"), test_link))
        place.into_view()

    def connected_to(base, found):
        actions.use_server(app.state, base, found)
        app.state.save()
        # Connected: the server's card folds into the sign-in's line again.
        app.server_open = None
        app.refresh_checks()
        rerender()

    # Not connected yet, Connect is the card's main action (typing goes to the address, Enter connects); connected,
    # connecting again is no longer the next thing to do, so it is a quiet one.
    place.button(w("online.connect"), connect, row=0, column=1, beside=True,
                 main=_plain(app) if connected else _main(app))
    if not connected:
        def ready():
            # Typing goes to the address; opened by Change, it replaces the one connected to.
            if address.winfo_exists():
                address.focus_set()
                if changing:
                    address.entry.select_range(0, "end")
                    address.entry.icursor("end")

        address.after_idle(ready)
    return address.get


def _test_card_for(app, parent, typed, tester, rerender=None):
    """The connection test's card, kept in `tester` for the lines that lead to it; `rerender` draws the server's cards
    again when the test finds the server no longer takes the sign-in (it is forgotten then: app.token_refused)."""
    made = test_card(app, parent, typed, rerender)
    tester["card"] = made
    return made


def _sign_in_card(app, parent, remote_state, rerender, test_link, change=None):
    """The sign-in, as the site's door (FORMS.md): the server it signs in to, the ID with the person's mark and the
    password with the lock's and Show inside, each named over its field, Remember my ID on this PC, and Sign in across
    the form; under a seam, what to do when the password is gone. The ID kept by Remember my ID is there already and
    the password takes the keyboard. Enter in either field signs in; while the server is asked the fields wait and the
    key shows the game's moving stripes. What is wrong is said where it is: an empty field under it, a wrong ID or
    password under the password in one sentence (the server tells the two apart to nobody: IDs are private), too many
    tries and a server that does not answer right above the key (the latter with the way to the connection test), a
    banned account on a plate in place of the form, with the owner's reason and Sign in with another ID. `change`, when
    the server's own card is folded into the server's line, opens it again (Change on that line)."""
    ui, w = app.ui, app.words
    sign = card(parent, ui, w("online.signin"))
    holder = tk.Frame(sign.body, bg=theme.PANEL)
    holder.pack(fill="x")
    # The ID kept by Remember my ID; or, after the server stopped taking a sign-in (app.token_refused), the ID signed
    # in with, so that only the password is to type again.
    remembered = remote_state.get("remember_id") or (remote_state.get("login_id") if remote_state.get("game") else "")
    remembered = remembered or ""

    def form_again(keep_id=True):
        for child in holder.winfo_children():
            child.destroy()
        _sign_in_form(app, holder, remembered if keep_id else "", rerender, test_link, banned, change)

    def banned(reason, login_id):
        """The account is banned: a plate in place of the form, and the way to sign in with another ID."""
        for child in holder.winfo_children():
            child.destroy()
        _banned_plate(app, holder, reason, lambda: form_again(keep_id=False), change)

    form_again()
    return sign


def _server_line(app, parent, change=None):
    """The server a sign-in goes to: "Signing in to" in the hint's ink over the address in the names' face, its
    openDMT3 version after it, and Change after that when the server's own card is folded into this line (`change`
    opens it again)."""
    ui, w = app.ui, app.words
    remote_state = app.state.remote or {}
    to = tk.Frame(parent, bg=theme.PANEL)
    to.pack(fill="x", pady=(0, ui.px(16)))
    tk.Label(to, text=w("online.signin.to"), font=ui.fonts.label, fg=theme.MUTED, bg=theme.PANEL, padx=0,
             pady=0).pack(anchor="w")
    where = tk.Frame(to, bg=theme.PANEL)
    where.pack(anchor="w", pady=(ui.px(4), 0))
    tk.Label(where, text=app.state.server_url, font=ui.fonts.body_bold, fg=theme.TEXT, bg=theme.PANEL, padx=0,
             pady=0).pack(side="left")
    if remote_state.get("version"):
        tk.Label(where, text="openDMT3 %s" % remote_state["version"], font=ui.fonts.small, fg=theme.HINT,
                 bg=theme.PANEL, padx=0, pady=0).pack(side="left", padx=(ui.px(8), 0))
    if change is not None:
        # The way to another server: the folded server's card opened again, in the section's light as a link is.
        made = widgets.link(where, ui, w("online.server.change"), change, chevron=False)
        made.configure(font=ui.fonts.small)
        made.pack(side="left", padx=(ui.px(12), 0))


def _sign_in_form(app, parent, remembered, rerender, test_link, banned, change=None):
    """The sign-in's form, in `parent` (see _sign_in_card); banned(reason, login_id) when the server says the account
    is banned; `change` opens the server's folded card again (Change on the server's line)."""
    from opendmt3.client import remote
    from opendmt3.server.services import accounts as acc
    ui, w = app.ui, app.words
    _server_line(app, parent, change)
    # A stacked form at a readable width, its fields the sign-in's large ones, each with its mark.
    form = widgets.Form(parent, ui, width=SIGN_IN_WIDTH)
    form.pack(anchor="w")
    form.field("online.id", w("online.id"), width=ID_CHARS, size="lg", mark="person")
    form.field("online.password", w("online.password"), width=PASSWORD_CHARS, secret=True, size="lg", mark="lock")
    form.fields["online.id"].insert(0, remembered)
    # Remember my ID: unticked at first; ticked, the ID stays for the next sign-in on this PC (never the password).
    remember = widgets.Tick(form, ui, w("online.remember"), value=bool(remembered))
    remember.pack(anchor="w", pady=(ui.px(12), 0))
    # One sign-in at a time: Enter pressed twice sends one request (the server counts every try).
    asking = {"now": False}

    def sign_in():
        if asking["now"]:
            return
        login_id, password = form.fields["online.id"].get().strip(), form.fields["online.password"].get()
        form.clear()
        form.tell(None)
        # What can be said here without asking: an empty field, or an ID no account can have.
        if not login_id:
            form.say("online.id", w("error.signin.no_id"))
        else:
            try:
                acc.check_id(login_id.upper())
            except acc.AccountError as e:
                # The accounts' own words for what an ID is; no server asked.
                form.say("online.id", w.error(e))
        if not password:
            form.say("online.password", w("error.signin.no_password"))
        wrong = [key for key in ("online.id", "online.password") if form.fields[key].error]
        if wrong:
            # The first wrong field takes the keyboard, and what is wrong is on the screen.
            form.fields[wrong[0]].focus_set()
            form.into_view()
            return
        asking["now"] = True
        form.busy(True)
        remember.enable(False)

        def work():
            try:
                me = remote.sign_in(app.state.server_url, login_id, password)
                app.post(lambda: signed_in(me, login_id))
            except Exception as e:  # noqa: BLE001
                # The server's own words go to the log (never the password); the form says it plainly.
                log.info("could not sign in to %s as %s: %s", app.state.server_url, login_id, e)
                app.post(lambda e=e: refused(e, login_id))

        threading.Thread(target=work, daemon=True, name="sign-in").start()

    def refused(error, login_id):
        asking["now"] = False
        if not form.winfo_exists():
            # The page went while the server was asked.
            return
        form.busy(False)
        remember.enable(True)
        key, code = getattr(error, "key", None), getattr(error, "code", None)
        password = form.fields["online.password"]
        if code == "banned":
            # The right password of a banned account: the plate with the owner's reason, in place of the form.
            banned(getattr(error, "params", {}).get("reason") or "-", login_id)
            return
        if code == "wrong_sign_in":
            # One sentence for a wrong ID and a wrong password alike, under the password: the ID kept, the password
            # emptied and ready to type again.
            form.say("online.password", w("online.signin.wrong"))
            password.delete(0, "end")
            password.focus_set()
            form.into_view()
            return
        if key in ("error.remote.unreachable", "error.remote.not_an_answer", "error.remote.answered",
                   "error.remote.unknown_host", "error.remote.not_opendmt3"):
            # The server, not the account: right above the key, with the way to the test that finds the step that
            # fails.
            form.tell(w.error(error), "bad", (w("server_test.run"), test_link))
        else:
            # Too many tries (wait), anything else: right above the key.
            form.tell(w.error(error), "bad")
        password.focus_set()
        password.select_range(0, "end")
        # The line above the key on the screen, in a window too small to show the whole card.
        form.into_view()

    def signed_in(me, login_id):
        asking["now"] = False
        actions.signed_in(app.state, me)
        # Remember my ID: kept for the next sign-in on this PC, or forgotten.
        app.state.remote = dict(app.state.remote or {})
        if remember.value:
            app.state.remote["remember_id"] = login_id.upper()
        else:
            app.state.remote.pop("remember_id", None)
        app.state.save()
        app.refresh_checks()
        rerender()

    # Signing in is the card's main action: lit while PLAY waits, quiet beside a lit PLAY; across the form.
    form.button(w("online.signin"), sign_in, main=_main(app), size="lg", fill=True)
    if form.keys is not None:
        form.keys.configure(width=ui.px(SIGN_IN_WIDTH))
    # Under a seam, the way back when the password is gone: one quiet line.
    seam = tk.Frame(parent, bg=theme.PANEL, width=ui.px(SIGN_IN_WIDTH))
    seam.pack(anchor="w", pady=(ui.px(16), 0))
    tk.Frame(seam, bg=theme.DIVIDER, height=1, width=ui.px(SIGN_IN_WIDTH)).pack(anchor="w")
    widgets.label(seam, ui, w("online.forgot"), font=ui.fonts.small, fg=theme.HINT, wraplength=ui.px(SIGN_IN_WIDTH),
                  ).pack(anchor="w", pady=(ui.px(12), 0))
    # Typing goes to the ID (to the password when the ID is remembered); Tab to the next; Enter signs in.
    first = form.fields["online.password" if remembered else "online.id"]
    first.after_idle(first.focus_set)


def _banned_plate(app, parent, reason, again, change=None):
    """A banned account (FORMS.md): a plate on the slot's dark with a pink edge, the problem's lamp and "This account is
    banned", the owner's reason after "Reason", that the owner can lift the ban, and one quiet key, Sign in with
    another ID, which brings the form back with the ID empty; under the server's line (with Change: `change`)."""
    ui, w = app.ui, app.words
    _server_line(app, parent, change)
    # As wide as the sign-in form it stands in place of: a column held to that width by a pixel-high rule of the
    # card's colour, the plate and its key across it, the words wrapped inside it.
    column = tk.Frame(parent, bg=theme.PANEL)
    column.pack(anchor="w")
    tk.Frame(column, bg=theme.PANEL, width=ui.px(SIGN_IN_WIDTH), height=1).pack(anchor="w")
    edge = tk.Frame(column, bg=theme.BAN_EDGE, padx=1, pady=1)
    edge.pack(fill="x")
    plate = tk.Frame(edge, bg=theme.FIELD, padx=ui.px(16), pady=ui.px(14))
    plate.pack(fill="both", expand=True)
    # The room for words inside the plate: the column less the edge and the plate's sides.
    room = ui.px(SIGN_IN_WIDTH) - 2 - 2 * ui.px(16)
    head = tk.Frame(plate, bg=theme.FIELD)
    head.pack(fill="x")
    lamp = widgets.Lamp(head, ui, theme.PINK, bg=theme.FIELD)
    lamp.pack(side="left", anchor="n", pady=(lamp.drop, 0))
    tk.Label(head, text=w("online.banned"), font=ui.fonts.body_bold, fg=theme.TEXT, bg=theme.FIELD, padx=0,
             pady=0).pack(side="left", padx=(ui.px(8), 0))
    why = tk.Frame(plate, bg=theme.FIELD)
    why.pack(fill="x", pady=(ui.px(8), 0))
    named = w("online.banned.reason")
    tk.Label(why, text=named, font=ui.fonts.label, fg=theme.MUTED, bg=theme.FIELD, padx=0,
             pady=0).pack(side="left", anchor="n")
    # The owner's reason, as written, beside its name; wrapped within the plate however long it is.
    widgets.label(why, ui, reason, bg=theme.FIELD, padx=0, pady=0,
                  wraplength=room - ui.fonts.label.measure(named) - ui.px(8)).pack(side="left", fill="x", expand=True,
                                                                                     padx=(ui.px(8), 0))
    widgets.label(plate, ui, w("online.banned.lift"), font=ui.fonts.small, fg=theme.HINT, bg=theme.FIELD, padx=0,
                  pady=0, wraplength=room).pack(fill="x", pady=(ui.px(6), 0))
    keys = tk.Frame(column, bg=theme.PANEL)
    keys.pack(fill="x", pady=(ui.px(16), 0))
    other = widgets.Button(keys, ui, w("online.banned.other"), again, size="lg", fill=True)
    other.pack(fill="x")
    other.after_idle(other.focus_set)


def _signed_card(app, parent, remote_state, rerender):
    """Signed in: who (the DJ name, the ID under it), on which server, that the game logs in with this card, and Sign
    out at the right end."""
    ui, w = app.ui, app.words
    sign = card(parent, ui, w("online.signed.title"))
    line = tk.Frame(sign.body, bg=theme.PANEL)
    line.pack(fill="x")

    def sign_out():
        # actions.sign_out's two steps, split across threads: the server ends the token first, off the window's
        # thread (one that does not answer takes a few seconds to give up), with the button saying so meanwhile;
        # then the sign-in is forgotten here, on the window's thread, whatever the server said.
        leave.enable(False)
        leave.set_text(w("online.signing_out"))
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

    leave = widgets.Button(line, ui, w("online.signout"), sign_out)
    leave.pack(side="right", anchor="n")
    lamp = widgets.Lamp(line, ui, theme.LIME)
    lamp.pack(side="left", anchor="n", pady=(lamp.drop, 0))
    who = tk.Frame(line, bg=theme.PANEL)
    who.pack(side="left", fill="x", expand=True, padx=(ui.px(8), ui.px(16)))
    name = tk.Frame(who, bg=theme.PANEL)
    name.pack(anchor="w")
    tk.Label(name, text=remote_state.get("dj_name", ""), font=ui.fonts.body_bold, fg=theme.TEXT, bg=theme.PANEL,
             padx=0, pady=0).pack(side="left")
    tk.Label(name, text=remote_state.get("login_id", ""), font=ui.fonts.small, fg=theme.MUTED, bg=theme.PANEL,
             padx=0, pady=0).pack(side="left", padx=(ui.px(8), 0))
    widgets.label(who, ui, w("online.signed.on", base=app.state.server_url), font=ui.fonts.small, fg=theme.MUTED,
                  wrap_margin=0).pack(fill="x", pady=(ui.px(2), 0))
    return sign


# A step's lamp by its state: waiting and not run an outline, running an amber outline, passed lime, failed pink.
TEST_LAMPS = {"waiting": (theme.MUTED, False), "not_run": (theme.FAINT, False), "running": (theme.AMBER, False),
              "ok": (theme.LIME, True), "failed": (theme.PINK, True)}


def test_card(app, parent, typed, rerender=None):
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
            # What the test does, said as every card's hint is (small, the hint's ink) until it runs.
            widgets.label(inside, ui, w("server_test.idle"), font=ui.fonts.small, fg=theme.HINT,
                          wrap_margin=0).pack(fill="x")
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
        gone = [s for s in steps if s.key == "sign_in" and s.state == "failed" and s.said
                and s.said[0] == "server_test.sign_in.gone"]
        if not running and gone and app.token_refused() and rerender is not None:
            # The server no longer takes the sign-in: forgotten (app.token_refused), and the sign-in card gives way to
            # its form, the ID kept; the test's card shows its result again under it.
            rerender()

    tested = getattr(app, "server_test", None) is not None
    button = made.action(w("server_test.again" if tested else "server_test.run"), run)
    # The way a failure's line elsewhere runs it (server_panel's test_link).
    made.run = run
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
        # Another way to play: the server's card folds again when its sign-in comes back.
        app.server_open = None
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
        # Connected with nobody signed in, the sign-in's card leads, before this one.
        server_panel(app, parent, lambda: app.go("online"), lead=where)
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
        else:
            # This PC's server's admin pages (its own site on this PC's address), opened signed in as its admin: at the
            # card's head, as a card's action is.
            players.action(w("online.admin"), app.open_admin)
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
