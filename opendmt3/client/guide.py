"""The first-start guide: five steps from nothing to the first song, laid out as OpenDMTQ's guide is.

POWER ON (language, what is needed), DISC CHECK (find the client data), SOUND CHECK (screen and sound), LOG IN (play
on this PC with a DJ of your own, on another server with the ID its owner made, or offline as a guest), STAGE START
(the ready check, and how to leave the game). The steps stand across under the launcher's bar, each step's name is its
page's title with its question in the line under it, and Skip, Back and Next (PLAY on the last step) stand along the
foot. Every choice is the same setting the launcher's pages show, so the guide never knows anything the pages do not.
"""

import tkinter as tk

from PIL import ImageTk

from opendmt3.client import art, found_list, hosting, intake, pages, theme, widgets
from opendmt3.client.pages.common import card

# Step keys name the words in i18n (guide.<key>.name, .title, .text); the number shown is the place in this list.
STEPS = ("1", "2", "3", "login", "4")
# The few words each step says after its question, in the line under its title.
LEADS = {"1": "guide.1.text", "2": "guide.2.text", "login": "guide.login.text", "4": "guide.4.text"}
# Each step's arrangement of shards in its head, so moving between steps feels like moving.
SEEDS = {"1": 3, "2": 13, "3": 23, "login": 33, "4": 43}


class Guide:
    def __init__(self, app):
        self.app = app
        self.index = 0                   # the step on show
        self._header_job = None          # a head drawing waiting for a resize to settle
        # DISC CHECK's list: kept across the steps (and a change of language), so the search runs once.
        self.found = found_list.FoundList(app, on_update=self._update_next)

    # ------------------------------------------------------------------------------------- frame

    def build(self):
        app, ui, px, w = self.app, self.app.ui, self.app.ui.px, self.app.words
        root = app.root
        # The guide is PLAY's way in: the title screen's blue throughout.
        ui.use_section("play")
        # The launcher's bar (the mark and the version), and the five steps across under it, as OpenDMTQ's guide.
        self.header = app.make_header(root, steps=[w("guide.%s.name" % key) for key in STEPS])
        # The bar along the foot: where the guide is, then Skip, Back and Next (PLAY on the last step).
        bottom = tk.Frame(root, bg=theme.PANEL)
        bottom.pack(side="bottom", fill="x")
        tk.Frame(bottom, bg=theme.LINE, height=1).pack(fill="x")
        # The launcher's bar height on every step: Next and the last step's PLAY sit in the same bar (a strut as tall as
        # PLAY with its keyboard ring holds it).
        from opendmt3.client.app import BAR_HEIGHT
        bar = tk.Frame(bottom, bg=theme.PANEL)
        bar.pack(fill="x", padx=px(24), pady=px(12))
        tk.Frame(bar, bg=theme.PANEL, width=1, height=px(BAR_HEIGHT)).pack(side="left")
        self.counter = tk.Label(bar, text="", font=app.fonts.section, fg=theme.MUTED, bg=theme.PANEL)
        self.counter.pack(side="left")
        self.next_button = widgets.Button(bar, ui, w("guide.next"), self.next, kind="primary")
        self.next_button.pack(side="right")
        # The last step's PLAY: the launcher's own blue slab in place of Next (not packed until then), lit while the
        # ready check lets it go.
        self.play_slab = self._make_play(bar)
        self.back_button = widgets.Button(bar, ui, w("guide.back"), self.back)
        self.back_button.pack(side="right", padx=(0, px(10)))
        # Leaving the guide for the launcher: a quiet link before Back, which the keyboard reaches too (packed by
        # show(), which leaves it out on the last step, where PLAY is the way on and its page has the link instead).
        self.skip = widgets.link(bar, ui, w("guide.skip"), lambda: self.finish(play=False), fg=theme.MUTED,
                                 chevron=False)
        self.skip.configure(font=app.fonts.small)
        # The step's page: its head (the step's name over the blue shards, its question under it) and its cards.
        self.body = widgets.ScrollArea(root, ui)
        self.body.pack(fill="both", expand=True)
        # The head is drawn again for a new width, once a drag settles (the first width draws it at once).
        self.body.on_width = lambda width: self._queue_header(now=self.body.canvas.head_picture is None)
        # Tab goes as the window reads: the page first, then the bar along the foot, left to right (Skip, Back, Next
        # or PLAY). Tk's Tab follows each parent's stacking order. (Misc's own raise: a canvas's raise moves items.)
        tk.Misc.tkraise(bottom)
        for later in (self.skip, self.back_button, self.next_button, self.play_slab):
            tk.Misc.tkraise(later)
        self.show(self.index)

    def _make_play(self, parent):
        """The last step's PLAY, as the launcher's bar has it (the leaning blue slab, its word in the game's wide
        letters): a click released over it starts the game, and Enter or Space once Tab has reached it."""
        app, px = self.app, self.app.ui.px
        size = (px(212), px(50))
        self._play_pictures = {look: art.play_button(*size, state=look) for look in ("normal", "hover", "pressed",
                                                                                     "disabled")}
        self._play_images = {look: ImageTk.PhotoImage(p, master=app.root) for look, p in self._play_pictures.items()}
        slab = tk.Label(parent, image=self._play_images["normal"], text=app.words("bottom.play"), compound="center",
                        font=app.fonts.display_big, fg=theme.TEXT, bg=theme.PANEL, cursor="hand2", bd=0, takefocus=1,
                        highlightthickness=max(1, px(2)), highlightbackground=theme.PANEL, highlightcolor=theme.CYAN)
        slab.opendmt3_picture = self._play_pictures["normal"]
        slab.words, slab.mouse = app.words("bottom.play"), None
        slab.bind("<Enter>", lambda e: self._paint_play("hover"))
        slab.bind("<Leave>", lambda e: self._paint_play(None))
        slab.bind("<Button-1>", lambda e: self._paint_play("pressed"))

        def released(event):
            # Only a release over the slab counts, as with every button (drag off to cancel).
            inside = 0 <= event.x < slab.winfo_width() and 0 <= event.y < slab.winfo_height()
            self._paint_play("hover" if inside else None)
            if inside:
                self.next()

        slab.bind("<ButtonRelease-1>", released)
        for key in ("<Return>", "<KP_Enter>", "<space>"):
            slab.bind(key, lambda e: self.next())
        return slab

    def _paint_play(self, mouse=None):
        """The last step's PLAY: lit (and lit further under the mouse) while PLAY can go, dark and still otherwise."""
        slab = self.play_slab
        slab.mouse = mouse
        lit = self.app.ready()
        look = (mouse or "normal") if lit else "disabled"
        slab.opendmt3_picture = self._play_pictures[look]
        slab.configure(image=self._play_images[look], fg=theme.TEXT if lit else theme.FAINT,
                       cursor="hand2" if lit else "arrow")

    def _queue_header(self, now=False):
        """Draw the step's head again: at once (`now`), or 90 ms after the last of a drag's resize events."""
        if self._header_job is not None:
            self.app.root.after_cancel(self._header_job)
            self._header_job = None
        if now:
            self._draw_header()
            return
        self._header_job = self.app.root.after(90, self._draw_header)

    def _draw_header(self):
        """The step's head, as a page's: its name in chrome over the blue shards, its question and its few words in the
        line under it (OpenDMTQ's guide sets them so)."""
        from opendmt3.client.app import HEAD, SUB_AT, TITLE_AT
        self._header_job = None
        w, px = self.app.words, self.app.ui.px
        if not self.body.winfo_exists():
            # The guide was left (or drawn again in another language) while a drawing waited.
            return
        width = self.body.canvas.winfo_width()
        if width < 50:
            return
        key = STEPS[self.index]
        question, lead = w("guide.%s.title" % key), LEADS.get(key)
        if lead:
            question += (" " if question.endswith(("?", ".", "!")) else ". ") + w(lead)
        picture = art.header(width, px(HEAD), (), seed=SEEDS[key], title=w("guide.%s.name" % key), scale=self.app.scale,
                             title_at=TITLE_AT)
        self.body.set_head(picture, question, (px(SUB_AT[0]), px(SUB_AT[1])), max(px(300), int(width * 0.52)))

    # ------------------------------------------------------------------------------------- steps

    def show(self, index):
        self.index = index
        px, w = self.app.ui.px, self.app.words
        # The step's main buttons are made again with it (pages.main_button).
        self.app.main_buttons = []
        for child in self.body.inner.winfo_children():
            child.destroy()
        content = tk.Frame(self.body.inner, bg=theme.BG)
        content.pack(fill="both", expand=True, padx=px(32), pady=(px(4), px(28)))
        [self._welcome, self._folder, self._screen, self._login, self._ready][index](content)
        # One column for the names of the step's settings, as a page has (common.ROWS_THAT_COME names the guide's own
        # as "guide:<step>", apart from the pages').
        widgets.fit_names(content, self.app.ui, pages.rows_that_come("guide:" + STEPS[index]))
        self.header.set_step(index)
        self.counter.configure(text=w("guide.step", n=index + 1, total=len(STEPS)).upper()
                               if w.language == "en" else w("guide.step", n=index + 1, total=len(STEPS)))
        self.back_button.enable(index > 0)
        last = index == len(STEPS) - 1
        # Next on every step but the last, where the big PLAY takes its place; Skip on every step but the last too, as
        # the last one sets nothing up that Skip would leave undone (its page has the way to the launcher).
        if last:
            self.next_button.pack_forget()
            self.play_slab.pack(side="right", before=self.back_button)
            self.skip.pack_forget()
        else:
            self.play_slab.pack_forget()
            self.next_button.pack(side="right", before=self.back_button)
            # Left of Back, with the room the bar keeps before it.
            self.skip.pack(side="right", padx=(0, px(18)), after=self.back_button)
        self._update_next()
        self.body.to_top()
        # The step's head at once (a drawing that waited for a resize is folded into this one).
        self._queue_header(now=True)

    def redraw(self):
        """The step on show drawn again (a choice changed its rows, an answer came), where it was scrolled to and with
        the keyboard on the control it was on (widgets.ScrollArea.keep_place)."""
        if self.app.guide is self:
            self.body.keep_place(lambda: self.show(self.index))

    def _can_go_on(self):
        """DISC CHECK needs a usable folder; LOG IN needs a player when playing on this PC."""
        if STEPS[self.index] == "2":
            return self._chosen_usable()
        if STEPS[self.index] == "login":
            state = self.app.state
            if state.mode == "server":
                # Another server needs a sign-in (its card) before the game can log in there.
                return bool(state.remote and state.remote.get("card"))
            return state.mode == "offline" or bool(state.player)
        return True

    def _update_next(self):
        self.next_button.enable(self._can_go_on())
        if self.index == len(STEPS) - 1:
            self._paint_play(self.play_slab.mouse)

    def checks_changed(self):
        """The ready check came back (app._checked): the last step's PLAY follows it."""
        self._update_next()

    def next(self):
        if self.index == len(STEPS) - 1:
            # PLAY: only while the ready check lets it go (dark and still otherwise, as the launcher's own).
            if self.app.ready():
                self.finish(play=True)
        elif self._can_go_on():
            self.show(self.index + 1)

    def back(self):
        if self.index > 0:
            self.show(self.index - 1)

    def finish(self, play):
        """Leave the guide for the launcher, and start the game when the last step's PLAY was pressed."""
        # A search still under way has nothing to show any more.
        self.found.stop()
        self.app.state.guide_done = True
        self.app.state.save()
        self.app.page = "play"
        self.app.show()
        if play:
            # The ready check runs first; PLAY waits for nothing else.
            self.app.root.after(400, self.app.play)

    # ---------------------------------------------------------------------------- 1 POWER ON

    def _welcome(self, parent):
        app, ui, w = self.app, self.app.ui, self.app.words
        # The language on a card of its own, its row's name saying what it is.
        language = card(parent, ui)
        widgets.setting_row(language.body, ui, w("about.language"),
                            lambda p: widgets.Segmented(p, ui, pages.language_options(app),
                                                        app.state.picked_language or "system",
                                                        self._language)).pack(fill="x")
        # The notice on a plain card, in the LAUNCHER page's own words for it: a request, not an error.
        notice = card(parent, ui)
        widgets.label(notice.body, ui, w("guide.1.notice"), wrap_margin=0).pack(fill="x")
        need = card(parent, ui, w("guide.1.need"), last=True)
        for i, key in enumerate(("guide.1.need.1", "guide.1.need.2")):
            if i:
                # One thing a line, parted by the card's faint lines, as OpenDMTQ's list of what is needed.
                widgets.divider(need.body, ui, pady=9)
            widgets.label(need.body, ui, w(key), wrap_margin=0).pack(fill="x")

    def _language(self, language):
        """Switching language rebuilds the guide in the other language, on the same step ("system": Windows')."""
        self.app.state.language = None if language == "system" else language
        self.app.state.save()
        self.app._setup_fonts()
        for child in self.app.root.winfo_children():
            child.destroy()
        # build() shows the step the guide is on (self.index), once.
        self.build()

    # -------------------------------------------------------------------------- 2 DISC CHECK

    def _folder(self, parent):
        """Where the game is (the question and its few words are the step's head): what the search finds on this PC
        and what the player chooses, as the client data's cards (client/found_list.py) on the step's card, with
        Choose a folder... and Choose an archive... under them."""
        ui = self.app.ui
        found = card(parent, ui, last=True)
        self.found.build(found.body)

    def _chosen_usable(self):
        """DISC CHECK goes on with client data that plays: the chosen one, ready."""
        found = self.found.chosen()
        return found is not None and found.state == intake.READY

    # ------------------------------------------------------------------------- 3 SOUND CHECK

    def _screen(self, parent):
        app, ui, w = self.app, self.app.ui, self.app.words
        v = app.state.values
        # The same rows as the SCREEN, CONTROLS and SOUND pages, the ones a first start needs, on those pages' cards.
        display = card(parent, ui, w("screen.display"))
        widgets.setting_row(display.body, ui, w("screen.mode"),
                            lambda p: widgets.Segmented(p, ui, [("fullscreen", w("screen.mode.fullscreen")),
                                                                ("window", w("screen.mode.window"))],
                                                        v["display_mode"], self._set_and_redraw("display_mode")),
                            w("screen.mode.hint." + v["display_mode"])).pack(fill="x")
        device = "mouse" if v["cursor"] else "touch"
        controls = card(parent, ui, w("controls.device"))
        widgets.setting_row(controls.body, ui, w("controls.input"),
                            lambda p: widgets.Segmented(p, ui, [("mouse", w("controls.input.mouse")),
                                                                ("touch", w("controls.input.touch"))], device,
                                                        lambda d: self._set_and_redraw("cursor")(d == "mouse")),
                            w("controls.input.hint." + device)).pack(fill="x")
        volume = card(parent, ui, w("sound.volumes"), last=True)
        for i, (name, key) in enumerate((("music_volume", "sound.music"), ("key_volume", "sound.keys"))):
            if i:
                widgets.divider(volume.body, ui)
            widgets.setting_row(volume.body, ui, w(key),
                                lambda p, n=name: widgets.Slider(p, ui, v[n], lambda val, n=n: app.changed(n, val)),
                                w(key + ".hint")).pack(fill="x")

    def _set_and_redraw(self, name):
        def setter(value):
            self.app.changed(name, value)
            # The hint under the choice says the new one: the step drawn again where it was.
            self.redraw()
        return setter

    # ------------------------------------------------------------------------------- LOG IN

    def _login(self, parent):
        app, ui, px, w = self.app, self.app.ui, self.app.ui.px, self.app.words
        if not getattr(self, "_mode_offered", False):
            # The guide's suggestion: a DJ of your own on this PC (records kept); offline stays one click away.
            self._mode_offered = True
            if app.state.mode == "offline" and not app.state.player:
                app.state.mode = "this_pc"
                app.state.save()
                app.read_song_list_ahead()
        mode = app.state.mode

        def set_mode(value):
            app.state.mode = value
            app.state.save()
            app.read_song_list_ahead()
            self.show(self.index)

        # Where you play, on the ONLINE page's own card.
        where = card(parent, ui, w("online.where"), last=mode == "offline")
        widgets.setting_row(where.body, ui, w("online.mode"),
                            lambda p: widgets.Segmented(p, ui, [("this_pc", w("online.mode.this_pc")),
                                                                ("server", w("online.mode.server")),
                                                                ("offline", w("online.mode.offline"))], mode, set_mode),
                            w("online.mode.hint." + mode)).pack(fill="x")
        if mode == "server":
            pages.server_panel(app, parent, lambda: self.show(self.index))
            self._needed(parent, "guide.login.need.server")
            return
        if mode != "this_pc":
            return
        try:
            rows = app.player_rows()
        except hosting.HostingError as e:
            # The database cannot be read: said in place of the players, and the guide still goes on.
            trouble = card(parent, ui, last=True)
            pages.database_trouble(app, trouble.body, e)
            return
        if rows:
            players = card(parent, ui, w("online.players"))
            for i, r in enumerate(rows):
                if i:
                    widgets.divider(players.body, ui, pady=6)
                on = r["login_id"] == app.state.player
                line = tk.Frame(players.body, bg=theme.PANEL_HI if on else theme.PANEL, padx=px(10), pady=px(6),
                                cursor="hand2")
                line.pack(fill="x")
                parts = [widgets.Lamp(line, ui, theme.BLUE_HI if on else theme.MUTED, lit=on),
                         tk.Label(line, text=r["dj_name"], font=app.fonts.body_bold, fg=theme.TEXT, bg=line["bg"]),
                         tk.Label(line, text=r["login_id"], font=app.fonts.small, fg=theme.MUTED, bg=line["bg"])]
                for j, part in enumerate(parts):
                    part.pack(side="left", padx=(0 if j == 0 else px(10), 0))
                for widget in [line] + parts:
                    widget.bind("<Button-1>", lambda e, login_id=r["login_id"]: self._choose_player(login_id))
        add = card(parent, ui, w("online.add"), last=True)
        pages.player_form(app, add.body, self._choose_player)
        self._needed(parent, "guide.login.need")

    def _needed(self, parent, key):
        """LOG IN's word on why Next is off, under the cards, while it is: what lets the guide go on."""
        if self._can_go_on():
            return
        ui, px = self.app.ui, self.app.ui.px
        widgets.label(parent, ui, self.app.words(key), fg=theme.AMBER, wrap_margin=0).pack(fill="x", pady=(px(14), 0))

    def _choose_player(self, login_id):
        self.app.state.player = login_id
        self.app.state.save()
        self.show(self.index)

    # ------------------------------------------------------------------------- 4 STAGE START

    def _ready(self, parent):
        app, ui, px, w = self.app, self.app.ui, self.app.ui.px, self.app.words
        ready = card(parent, ui, w("play.ready"), last=True)
        app.check_box = tk.Frame(ready.body, bg=theme.PANEL)
        app.check_box.pack(fill="x")
        app.refresh_checks()
        pages.refresh_checks(app)
        # How to leave the game, before the first PLAY: no key does, and nothing in the game says where the X is.
        widgets.label(parent, ui, w("play.how.4"), fg=theme.MUTED, wrap_margin=0).pack(fill="x", pady=(px(16), 0))
        # The way to the launcher's pages without playing, where Skip stood on the steps before.
        widgets.link(parent, ui, w("guide.4.launcher"), lambda: self.finish(play=False)).pack(anchor="w",
                                                                                              pady=(px(12), 0))
