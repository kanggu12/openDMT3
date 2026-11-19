"""ONLINE: where logins and records are kept (this PC, another server, offline), one group of rows: the choice and, on
this PC, its server opened to the other PCs on its network, then its players; with another server, the server's
address, the sign-in and the connection test's key, as OpenDMTQ's Server card has them."""

import logging
import threading
import tkinter as tk

from opendmt3.client import actions, dialogs, hosting, theme, widgets
# The limits the accounts themselves check, so the add-player hint never says other numbers.
from opendmt3.server.services import accounts

from opendmt3.client.pages.common import CARD_GAP, Sections, card, database_trouble, main_button

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
    # Typing goes to the ID, once the window is idle (on the root: widgets.later).
    widgets.later(form.fields["online.id"], form.fields["online.id"].focus_set)
    return form


def server_panel(app, where, parent, rerender, choice):
    """Another server, as parts of Where you play (`where`, its card; OpenDMTQ's Server card holds them so): until a
    server answers, its site's address with Connect and how it stands under them; once one answers, the server said
    under the choice (`choice`, its row) in place of what the choice means, with Change, and under it the sign-in (the
    ID and the password, Sign in) or who is signed in with Sign out; the connection test's key at the group's title,
    its steps on a card of their own under the group (in `parent`) only while a test is on show. No card for one key
    or one line. Returns `where` (the guide puts its line at its foot).

    The server folded into the choice's line keeps the whole group, the sign-in's key and what it says included, on
    the screen at the window's smallest size. Change opens the address as it is before connecting (chosen whole to type
    over, Connect the main action, no sign-in until a server answers; app.server_open: the address it was opened for,
    forgotten once a server answers or the page is left)."""
    ui = app.ui
    remote_state = app.state.remote or {}
    connected = bool(app.state.server_url and remote_state.get("game"))
    # Change opened the address for the very server connected to: open until a server answers or the page is left.
    changing = connected and getattr(app, "server_open", None) == app.state.server_url
    folded = connected and not changing
    # The connection test, made last: a failure's line leads to it (filled in once it is made).
    tester = {}

    def test_link():
        """The way from a failure to the connection test: the test run, its card in view."""
        made = tester.get("test")
        if made is not None and made.holder.winfo_exists():
            made.run()
            made.into_view()

    def change():
        """Change, on the choice's line: the address open again, ready to type over."""
        app.server_open = app.state.server_url
        rerender()

    body = where.body
    if folded:
        # The server connected to, said under the choice with Change; the address the test checks is that one.
        _connected_line(app, choice, change)

        def typed():
            return app.state.server_url or ""

        # Who plays there: the sign-in, or who is signed in, under the group's faint line.
        widgets.divider(body, ui)
        if remote_state.get("card"):
            _signed_rows(app, body, remote_state, rerender)
        else:
            _sign_in_rows(app, body, remote_state, rerender, test_link)
    else:
        # The address, a part of the group under its faint line: the one typed is the one the test checks.
        widgets.divider(body, ui)
        typed = _server_rows(app, body, rerender, test_link, changing)
    tester["test"] = test_card(app, where, parent, typed, rerender)
    return where


def _connected_line(app, row, change):
    """The server connected to, under the choice of where you play (`row`, its setting row) in place of what the choice
    means: its address, its openDMT3 version and the game's address, then Change, which opens the address again."""
    ui, w = app.ui, app.words
    remote_state = app.state.remote or {}
    if row.hint is not None:
        # What the choice means gives way to where it plays now.
        row.hint.destroy()
    line = tk.Frame(row, bg=row.cget("bg"))
    # Where the row's hint stands: under the name and the choice, across the row.
    line.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(ui.px(4), 0))
    said = widgets.label(line, ui, w("online.connected", base=app.state.server_url,
                                     version=remote_state.get("version", "?"), game=remote_state.get("game", "?")),
                         font=ui.fonts.small, fg=theme.MUTED, bg=row.cget("bg"))
    said.pack(side="left")
    # The way to another server, right after the sentence, in the section's light as a link is.
    to = widgets.link(line, ui, w("online.server.change"), change, chevron=False)
    to.configure(font=ui.fonts.small)
    to.pack(side="left", anchor="n", padx=(ui.px(8), 0))
    # The sentence wraps at the row's width less its link's.
    widgets.follow_width(ui, said, margin=12, beside=(to,))
    row.hint = said


def _server_rows(app, parent, rerender, test_link, changing=False):
    """The server's part of Where you play (`parent`, its card's body) until a server answers: its site's address,
    named over its field with an example of one in it, Connect on the field's line (the main action), and how it
    stands under them; `changing`, opened by Change, the address chosen whole so that typing replaces it. Returns the
    way to read the address typed."""
    ui, w = app.ui, app.words
    place = widgets.Form(parent, ui)
    place.pack(fill="x")
    address = place.field("address", w("online.address"), width=ADDRESS_CHARS,
                          placeholder=w("online.address.example"), row=0, column=0)
    address.refresh()
    address.insert(0, app.state.server_url or "")

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
        # It answered: NET follows what the launcher knows now.
        app.server_reached(True)
        # Connected: the address folds into the choice's line again.
        app.server_open = None
        app.refresh_checks()
        rerender()

    # Connect is the group's main action (typing goes to the address, Enter connects).
    place.button(w("online.connect"), connect, row=0, column=1, beside=True, main=_main(app))

    def ready():
        # Typing goes to the address; opened by Change, it replaces the one connected to.
        if address.winfo_exists():
            address.focus_set()
            if changing:
                address.entry.select_range(0, "end")
                address.entry.icursor("end")

    # Once the window is idle, on the root (widgets.later).
    widgets.later(address, ready)
    return address.get


def _sign_in_rows(app, parent, remote_state, rerender, test_link):
    """The sign-in, a part of Where you play (`parent`, its card's body) under the server it signs in to (said under
    the choice), as the site's door (FORMS.md): the ID with the person's mark and the password with the lock's and
    Show inside, each named over its field, Remember my ID on this PC, and Sign in, a main key sized for its words;
    under a seam, what to do when the password is gone. The ID kept by Remember my ID is there already and the
    password takes the keyboard. Enter in either field signs in; while the server is asked the fields wait and the key
    shows the game's moving stripes. What is wrong is said where it is: an empty field under it, a wrong ID or password
    under the password in one sentence (the server tells the two apart to nobody: IDs are private), too many tries and
    a server that does not answer right above the key (the latter with the way to the connection test), a banned
    account on a plate in place of the form, with the owner's reason and Sign in with another ID."""
    holder = tk.Frame(parent, bg=parent.cget("bg"))
    holder.pack(fill="x")
    # The ID kept by Remember my ID; or, after the server stopped taking a sign-in (app.token_refused), the ID signed
    # in with, so that only the password is to type again.
    remembered = remote_state.get("remember_id") or (remote_state.get("login_id") if remote_state.get("game") else "")
    remembered = remembered or ""
    # Remember my ID shows what the person chose: ticked only when they kept an ID, not because the server's refusal
    # left the ID they signed in with in the field (review round 2, #4).
    ticked = bool(remote_state.get("remember_id"))

    def form_again(keep_id=True):
        for child in holder.winfo_children():
            child.destroy()
        _sign_in_form(app, holder, remembered if keep_id else "", rerender, test_link, banned,
                      ticked=ticked and keep_id)

    def banned(reason, login_id):
        """The account is banned: a plate in place of the form, and the way to sign in with another ID."""
        for child in holder.winfo_children():
            child.destroy()
        _banned_plate(app, holder, reason, lambda: form_again(keep_id=False))

    form_again()
    return holder


def _sign_in_form(app, parent, remembered, rerender, test_link, banned, ticked=False):
    """The sign-in's form, in `parent` (see _sign_in_rows); banned(reason, login_id) when the server says the account
    is banned; `ticked`: Remember my ID as the person left it."""
    from opendmt3.client import remote
    from opendmt3.server.services import accounts as acc
    ui, w = app.ui, app.words
    # A stacked form at a readable width, its fields the sign-in's large ones, each with its mark.
    form = widgets.Form(parent, ui, width=SIGN_IN_WIDTH)
    form.pack(anchor="w")
    form.field("online.id", w("online.id"), width=ID_CHARS, size="lg", mark="person")
    form.field("online.password", w("online.password"), width=PASSWORD_CHARS, secret=True, size="lg", mark="lock")
    form.fields["online.id"].insert(0, remembered)
    # Remember my ID as the person left it (unticked until they tick it); ticked, the ID stays for the next sign-in on
    # this PC (never the password).
    remember = widgets.Tick(form, ui, w("online.remember"), value=ticked)
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
        if actions.unreachable(error):
            # The server did not answer: NET goes out and the ready check says it.
            app.server_reached(False)
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
                   "error.remote.unknown_host", "error.remote.not_opendmt3", "error.remote.not_a_site"):
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
        app.server_reached(True)
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

    # Signing in is the group's main action: lit while PLAY waits, quiet beside a lit PLAY; a main key as every page's
    # and dialog's is, sized for its words (no key stretched across a card).
    form.button(w("online.signin"), sign_in, main=_main(app))
    if form.keys is not None:
        form.keys.configure(width=ui.px(SIGN_IN_WIDTH))
    # Under a seam, the way back when the password is gone: one quiet line.
    seam = tk.Frame(parent, bg=parent.cget("bg"), width=ui.px(SIGN_IN_WIDTH))
    seam.pack(anchor="w", pady=(ui.px(16), 0))
    tk.Frame(seam, bg=theme.DIVIDER, height=1, width=ui.px(SIGN_IN_WIDTH)).pack(anchor="w")
    widgets.label(seam, ui, w("online.forgot"), font=ui.fonts.small, fg=theme.HINT, wraplength=ui.px(SIGN_IN_WIDTH),
                  ).pack(anchor="w", pady=(ui.px(12), 0))
    # Typing goes to the ID (to the password when the ID is remembered); Tab to the next; Enter signs in.
    first = form.fields["online.password" if remembered else "online.id"]
    widgets.later(first, first.focus_set)


def _banned_plate(app, parent, reason, again):
    """A banned account (FORMS.md): a plate on the slot's dark with a pink edge, the problem's lamp and "This account is
    banned", the owner's reason after "Reason", that the owner can lift the ban, and one quiet key, Sign in with
    another ID, which brings the form back with the ID empty."""
    ui, w = app.ui, app.words
    # As wide as the sign-in form it stands in place of: a column held to that width by a pixel-high rule of the
    # card's colour, the plate and its key across it, the words wrapped inside it.
    column = tk.Frame(parent, bg=parent.cget("bg"))
    column.pack(anchor="w")
    tk.Frame(column, bg=column.cget("bg"), width=ui.px(SIGN_IN_WIDTH), height=1).pack(anchor="w")
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
    keys = tk.Frame(column, bg=column.cget("bg"))
    keys.pack(fill="x", pady=(ui.px(16), 0))
    # An ordinary key sized for its words, at the column's left edge (no key stretched across a card).
    other = widgets.Button(keys, ui, w("online.banned.other"), again)
    other.pack(anchor="w")
    widgets.later(other, other.focus_set)


def _signed_rows(app, parent, remote_state, rerender):
    """Signed in, a part of Where you play (`parent`, its card's body): who (the DJ name, the ID beside it), that the
    game logs in with this card, and Sign out at the right end."""
    ui, w = app.ui, app.words
    line = tk.Frame(parent, bg=parent.cget("bg"))
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
    lamp = widgets.Lamp(line, ui, theme.NET)
    lamp.pack(side="left", anchor="n", pady=(lamp.drop, 0))
    who = tk.Frame(line, bg=line.cget("bg"))
    who.pack(side="left", fill="x", expand=True, padx=(ui.px(8), ui.px(16)))
    name = tk.Frame(who, bg=who.cget("bg"))
    name.pack(anchor="w")
    tk.Label(name, text=remote_state.get("dj_name", ""), font=ui.fonts.body_bold, fg=theme.TEXT, bg=name.cget("bg"),
             padx=0, pady=0).pack(side="left")
    tk.Label(name, text=remote_state.get("login_id", ""), font=ui.fonts.small, fg=theme.MUTED, bg=name.cget("bg"),
             padx=0, pady=0).pack(side="left", padx=(ui.px(8), 0))
    widgets.label(who, ui, w("online.signed.on", base=app.state.server_url), font=ui.fonts.small, fg=theme.MUTED,
                  wrap_margin=0).pack(fill="x", pady=(ui.px(2), 0))
    return line


# A step's lamp by its state: waiting and not run quiet, running an amber outline, passed the NET lamp's green, failed
# pink.
TEST_LAMPS = {"waiting": (theme.MUTED, "quiet"), "not_run": (theme.FAINT, "quiet"), "running": (theme.AMBER, False),
              "ok": (theme.NET, True), "failed": (theme.PINK, True)}
# A step's time is said only when it says something: a step this slow (milliseconds) or slower.
SLOW_MS = 500


def _same_server(typed, server_url):
    """True when the address typed for the test is the server the launcher is connected to."""
    from opendmt3.client import remote
    try:
        return remote.normalize(typed.strip()) == server_url
    except Exception:  # noqa: BLE001  (an address that does not read is no server of this launcher's)
        return False


class _Test:
    """The connection test as server_panel holds it: `holder`, where its card stands under the group; run() starts
    it; into_view() brings its card on the screen."""

    def __init__(self, app, holder, run, shown):
        self.app, self.holder, self.run, self._shown = app, holder, run, shown

    def into_view(self):
        made = self._shown.get("card")
        if made is not None and made.winfo_exists():
            self.app.body.show(made, self.app.ui.px(16))


def test_card(app, where, parent, typed, rerender=None):
    """The connection test (client/server_test.py): its key at the title of Where you play (`where`), Test the
    connection, then Test again; its steps on a card of their own under the group (in `parent`), the page's last, only
    while a test is on show (under way, or its result kept): one under another, each with its lamp, its name, what it
    found and its time, and under a failed one what to do; the outcome under them with Copy the result. It tests the
    address as typed (`typed()`) with the sign-in the launcher keeps for this server. The test runs on a thread; each
    step's outcome comes to the card as it ends, and only the card's own inside is drawn again. Its last result stays
    with the window (app.server_test) while the page is drawn again or left."""
    from opendmt3.client import server_test
    ui, w = app.ui, app.words
    # Where the card stands, under the group: empty (no height) until a test is on show.
    holder = tk.Frame(parent, bg=parent.cget("bg"))
    holder.pack(fill="x")
    shown = {}

    def draw():
        if not holder.winfo_exists():
            return
        kept = getattr(app, "server_test", None)
        made = shown.get("card")
        if kept is None:
            # No test on show: no card (a card for one key and a line of what it does said nothing the key does not).
            if made is not None and made.winfo_exists():
                made.destroy()
            shown.pop("card", None)
            return
        if made is None or not made.winfo_exists():
            # The test's card, the gap between cards above it.
            made = shown["card"] = widgets.Card(holder, ui, title=w("server_test"), kind="result")
            made.pack(fill="x", pady=(ui.px(CARD_GAP), 0))
        inside = made.body
        for child in inside.winfo_children():
            child.destroy()
        steps, running = kept["steps"], kept["running"]
        for i, step in enumerate(steps):
            if i:
                widgets.divider(inside, ui, pady=8)
            line = tk.Frame(inside, bg=inside.cget("bg"))
            line.pack(fill="x")
            colour, lit = TEST_LAMPS[step.state]
            lamp = widgets.Lamp(line, ui, colour, lit=lit)
            lamp.pack(side="left", anchor="n", pady=(lamp.drop, 0))
            # The time at the right end, in the hints' grey, only for a slow step: a column of 0 ms and 2 ms said nothing
            # anyone acts on (the copied result keeps every step's time for the server's owner).
            took = "%d ms" % step.ms if step.ms is not None and step.ms >= SLOW_MS else ""
            tk.Label(line, text=took, font=ui.fonts.small, fg=theme.MUTED, bg=line.cget("bg")).pack(side="right",
                                                                                              anchor="n")
            words = tk.Frame(line, bg=line.cget("bg"))
            words.pack(side="left", fill="x", expand=True, padx=(ui.px(8), ui.px(12)))
            tk.Label(words, text=w("server_test." + step.key), font=ui.fonts.body_bold, fg=theme.TEXT,
                     bg=words.cget("bg"), anchor="w").pack(fill="x")
            if step.said:
                widgets.label(words, ui, w(step.said[0], **step.said[1]), font=ui.fonts.small, fg=theme.MUTED,
                              wrap_margin=0).pack(fill="x")
            if step.fix:
                # What to do, in plain words, in the text's own colour: the step's lamp already says it failed.
                widgets.label(words, ui, w(step.fix[0], **step.fix[1]), font=ui.fonts.small, fg=theme.TEXT,
                              wrap_margin=0).pack(fill="x", pady=(ui.px(4), 0))
        widgets.divider(inside, ui, pady=8)
        foot = tk.Frame(inside, bg=inside.cget("bg"))
        foot.pack(fill="x")
        if running:
            said, colour = w("server_test.running"), theme.MUTED
        else:
            failed = [s for s in steps if s.state == "failed"]
            said = (w("server_test.failed", step=w("server_test." + failed[0].key + ".in")) if failed
                    else w("server_test.passed"))
            colour = theme.PINK if failed else theme.NET
            # The whole result as text, for a message to the server's owner: a key, as every action on a card is (the
            # final review's B-13: grey words read as a caption).
            widgets.Button(foot, ui, w("server_test.copy"), copy).pack(side="right", anchor="n")
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
        site = [s for s in steps if s.key == "site"]
        tested_here = bool(app.state.server_url) and _same_server(typed(), app.state.server_url)
        if not running and site and tested_here:
            # What the test learned about the server it is connected to: whether it answers (NET and the ready check
            # follow), and the version it answers with (the server's card shows it, not the one Connect saw).
            said = site[0].said or ("", {})
            if site[0].state == server_test.OK:
                version = said[1].get("version")
                if version and (app.state.remote or {}).get("version") != version:
                    app.state.remote = dict(app.state.remote or {}, version=version)
                    app.state.save()
                    if rerender is not None and not gone:
                        app.root.after_idle(rerender)
                app.server_reached(True)
            elif said[0] == "server_test.site.none":
                app.server_reached(False)
        if not running and gone and app.token_refused() and rerender is not None:
            # The server no longer takes the sign-in: forgotten (app.token_refused), and the sign-in card gives way to
            # its form, the ID kept; the test's card shows its result again under it.
            rerender()

    tested = getattr(app, "server_test", None) is not None
    # The group's action, at its title's right end as Check again is the ready check's.
    button = where.action(w("server_test.again" if tested else "server_test.run"), run)
    running_now = tested and app.server_test["running"]
    button.enable(not running_now)
    draw()
    # The way a failure's line elsewhere runs it and shows its card (server_panel's test_link).
    return _Test(app, holder, run, shown)


def _copy_step(step):
    """A step as it is now (server_test.Step), apart from the one the worker goes on changing."""
    from opendmt3.client import server_test
    made = server_test.Step(step.key)
    made.state, made.ms, made.said, made.fix = step.state, step.ms, step.said, step.fix
    return made


def build_online(app, parent):
    """Where you play, a group of rows: the choice, and on this PC its server opened to the other PCs on its network,
    with another server its address, its sign-in and its test (server_panel); then this PC's players, one group: the
    list and, under its faint line, the form that adds one. No card for one switch or one key."""
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

    # The group's gap under it only when another card follows (this PC's players; another server's test is under its
    # own gap when it shows).
    where = card(parent, ui, w("online.where"), last=mode != "this_pc")
    choice = widgets.setting_row(where.body, ui, w("online.mode"),
                                 lambda p: widgets.Segmented(p, ui, [("this_pc", w("online.mode.this_pc")),
                                                                     ("server", w("online.mode.server")),
                                                                     ("offline", w("online.mode.offline"))], mode,
                                                             set_mode),
                                 w("online.mode.hint." + mode))
    choice.pack(fill="x")
    if mode == "this_pc":
        # This PC's server opened to the other PCs at home: a row of the same group, under its faint line.
        widgets.divider(where.body, ui)
        _home_rows(app, where.body)
    if mode == "server":
        # Another server's address, sign-in and test: rows of the same group.
        server_panel(app, where, parent, lambda: app.go("online"), choice)
        return
    if mode != "this_pc":
        return
    # The players and the form that adds one, one group: each part made again on its own when a player is added,
    # chosen or deleted (Sections), so what is typed in the form stays as it was.
    group = card(parent, ui, w("online.players"), last=True, kind="list")
    sections = Sections(app, group.body)
    # The group's action (Admin pages) once there is a player: made with the list, at the group's head.
    opener = {}

    def players_card(holder):
        players = holder
        try:
            rows = app.player_rows()
        except hosting.HostingError as e:
            # The database cannot be read: said in place of the list, and the rest of the page still works.
            database_trouble(app, players, e)
            return
        if not rows:
            widgets.label(players, ui, w("online.players.none"), fg=theme.MUTED, wrap_margin=0).pack(fill="x")
        elif opener.get("key") is None or not opener["key"].winfo_exists():
            # This PC's server's admin pages (its own site on this PC's address), opened signed in as its admin: at the
            # group's head, as a card's action is. One opening at a time, the key busy while it is under way.
            opener["key"] = group.action(w("online.admin"), lambda: app.open_admin(opener["key"]))
        for i, r in enumerate(rows):
            if i:
                # One line a player, parted by the card's faint lines.
                widgets.divider(players, ui, pady=8)
            _player_line(app, players, r, lambda: sections.redo("players"))

    def add_card(holder):
        if app._database_problem() is not None:
            # The players cannot be read (said above): no form offered that could not work.
            return
        # Under the list and its faint line, named by its key (Add a player): the same group.
        widgets.divider(holder, ui, pady=14)
        add = holder

        def added(login_id):
            # The first player plays next without asking; later ones are picked on this page or on PLAY.
            if not app.state.player:
                app.state.player = login_id
                app.state.save()
            # The list with the new player, and the form empty again for the next one; the cabinet's lamps at once.
            sections.redo("players")
            sections.redo("add")
            app.player_changed()

        player_form(app, add, added)

    sections.add("players", players_card)
    sections.add("add", add_card)


def _player_line(app, parent, r, changed):
    """One player on the Players card: the lamp lit for the one who goes in at PLAY, the DJ name and ID, Delete, and
    Play next for the others; `changed()` makes the card again after a choice."""
    ui, w = app.ui, app.words
    line = tk.Frame(parent, bg=parent.cget("bg"))
    line.pack(fill="x")
    on = r["login_id"] == app.state.player
    # The player who goes in at PLAY has the lit lamp.
    # The player who goes in at PLAY has the lit lamp, in the NET green of every "this one, fine" lamp (the section's
    # pink reads as a problem on this page).
    widgets.Lamp(line, ui, theme.NET if on else theme.MUTED, lit=on).pack(side="left")
    tk.Label(line, text=r["dj_name"], font=ui.fonts.body_bold, fg=theme.TEXT, bg=line.cget("bg")).pack(
        side="left", padx=(ui.px(10), ui.px(8)))
    tk.Label(line, text=r["login_id"], font=ui.fonts.small, fg=theme.MUTED, bg=line.cget("bg")).pack(side="left")

    def pick(login_id=r["login_id"]):
        app.state.player = login_id
        app.state.save()
        changed()
        app.player_changed()

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
        # The ID CARD lamp goes out with the card at once (review round 2, #5).
        app.player_changed()

    widgets.Button(line, ui, w("online.remove"), remove, kind="danger").pack(side="right")
    if not on:
        widgets.Button(line, ui, w("online.pick"), pick).pack(side="right", padx=(0, ui.px(8)))
    else:
        # Who plays now, said in the hints' ink: the row's lit lamp already marks it (one mark, one accent).
        tk.Label(line, text=w("online.plays"), font=ui.fonts.small, fg=theme.MUTED, bg=line.cget("bg")).pack(
            side="right", padx=(0, ui.px(12)))


def _home_rows(app, parent):
    """Open this PC's server to the other PCs on its network, a row of WHERE YOU PLAY (`parent`, its card's body): they
    choose Another server and type one of these addresses, then sign in with a player made here."""
    ui, w = app.ui, app.words
    found = app.host.addresses() if app.state.lan else []
    # The hint names the addresses only while they are listed under it: off (or with no address) it says what the
    # switch is for.
    widgets.setting_row(parent, ui, w("online.home.open"),
                        lambda p: widgets.Toggle(p, ui, app.state.lan, app.set_lan),
                        w("online.home.hint.on") if found else None).pack(fill="x")
    if not app.state.lan:
        return
    if not found:
        # Still starting, or open with no address to reach it at: the second in the colour of something to look at.
        waiting = not app.host.running
        widgets.label(parent, ui, w("online.home.starting") if waiting else w("online.home.none"),
                      fg=theme.MUTED if waiting else theme.AMBER, wrap_margin=0).pack(fill="x", pady=(ui.px(10), 0))
        return
    widgets.divider(parent, ui)
    for address in found:
        widgets.label(parent, ui, address, font=ui.fonts.body_bold).pack(anchor="w")
    widgets.label(parent, ui, w("online.home.firewall"), font=ui.fonts.small, fg=theme.MUTED, wrap_margin=0).pack(
        fill="x", pady=(ui.px(6), 0))
