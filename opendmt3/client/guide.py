"""The first-start guide: five steps from nothing to the first song, laid out as OpenDMTQ's guide is.

POWER ON (language, what is needed), DISC CHECK (find the client data), SOUND CHECK (screen and sound), LOG IN (play
on this PC with a DJ of your own, on another server with the ID its owner made, or offline as a guest), STAGE START
(the ready check, and how to leave the game). The steps stand down the launcher's column where its menu stands, as
OpenDMTQ's guide has them, each step's name is its page's title with its question in the line under it, and Skip, Back
and Next (PLAY under Back on the last step) stand at the column's foot. Every choice is the same setting the launcher's pages show, so the guide never knows anything the pages do not.
"""

import tkinter as tk

from PIL import ImageTk

from opendmt3.client import art, found_list, hosting, intake, pages, theme, widgets
from opendmt3.client.pages.common import card

# Step keys name the words in i18n (guide.<key>.name, .title, .text); the number shown is the place in this list.
STEPS = ("1", "2", "3", "login", "4")
# The few words each step says after its question, in the line under its title.
LEADS = {"4": "guide.4.text"}


class Guide:
    def __init__(self, app):
        self.app = app
        self.index = 0                   # the step on show
        self._header_job = None          # a head drawing waiting for a resize to settle
        # DISC CHECK's list: kept across the steps (and a change of language), so the search runs once.
        self.found = found_list.FoundList(app, on_update=self._update_next)

    # ------------------------------------------------------------------------------------- frame

    def build(self):
        app, ui, w = self.app, self.app.ui, self.app.words
        root = app.root
        # The guide is PLAY's way in: the title screen's blue throughout.
        ui.use_section("play")
        # The launcher's column: the mark and the version, then the five steps down it where the menu stands, as
        # OpenDMTQ's guide.
        self.rail = app.make_rail(root, steps=[w("guide.%s.name" % key) for key in STEPS])
        # The step's page: its head (the step's name over the blue shards, its question under it) and its cards.
        self.body = app.make_page(root)
        # The head is drawn again for a new width, once a drag settles (the first width draws it at once).
        self.body.on_width = lambda width: self._queue_header(now=self.body.canvas.head_picture is None)
        # The column's foot, made after the page so that Tab goes the page, then Skip, Back and Next (Tk's Tab follows
        # the order things were made in).
        foot = app.make_foot(self.rail)
        # Leaving the guide for the launcher: a quiet link over the buttons, which the keyboard reaches too (packed by
        # show(), which leaves it out on the last step, where PLAY is the way on and its page has the link instead).
        self.skip = widgets.link(foot, ui, w("guide.skip"), lambda: self.finish(play=False), fg=theme.MUTED,
                                 bg=theme.BAR, chevron=False)
        self.skip.configure(font=app.fonts.small)
        # Back at the left, Next at the right, in one row as wide as the column holds.
        self.buttons = tk.Frame(foot, bg=theme.BAR)
        self.buttons.pack(side="top", fill="x")
        self.back_button = widgets.Button(self.buttons, ui, w("guide.back"), self.back)
        self.back_button.pack(side="left")
        self.next_button = widgets.Button(self.buttons, ui, w("guide.next"), self.next, kind="primary")
        self.next_button.pack(side="right")
        # The last step's PLAY: the launcher's own blue slab under Back, as wide as the column (not packed until then),
        # lit while the ready check lets it go.
        self.play_slab = self._make_play(foot)
        self.foot = foot
        self.show(self.index)

    def _make_play(self, parent):
        """The last step's PLAY, as the launcher's column has it (the leaning blue slab, its word in the game's wide
        letters): a click released over it starts the game, and Enter or Space once Tab has reached it."""
        app, px = self.app, self.app.ui.px
        # The launcher's own PLAY's size: as wide as the column holds.
        size = app.play_size(self.rail)
        self._play_pictures = {look: art.play_button(*size, state=look) for look in ("normal", "hover", "pressed",
                                                                                     "disabled")}
        self._play_images = {look: ImageTk.PhotoImage(p, master=app.root) for look, p in self._play_pictures.items()}
        slab = tk.Label(parent, image=self._play_images["normal"], text=app.words("bottom.play"), compound="center",
                        font=app.fonts.display_big, fg=theme.TEXT, bg=theme.BAR, cursor="hand2", bd=0, takefocus=1,
                        highlightthickness=max(1, px(2)), highlightbackground=theme.BAR, highlightcolor=theme.CYAN)
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
        from opendmt3.client.app import SUB_AT, TITLE_AT
        self._header_job = None
        w, px = self.app.words, self.app.ui.px
        if not self.body.winfo_exists():
            # The guide was left (or drawn again in another language) while a drawing waited.
            return
        width = self.body.canvas.winfo_width()
        if width < 50:
            return
        key = STEPS[self.index]

        def question_of(step):
            question, lead = w("guide.%s.title" % step), LEADS.get(step)
            if lead:
                question += (" " if question.endswith(("?", ".", "!")) else ". ") + w(lead)
            return question

        question = question_of(key)
        # The line under the title as wide as the shards leave the head (no discs here), and the head one height for
        # every step, the tallest's: Next never moves the cards up or down (the final review's A-10, W-03).
        sub_width = max(px(300), int(width * 0.66))
        tallest = max(self.app.head_height(question_of(step), sub_width) for step in STEPS)
        # The same stage as every page's (one composition), in the title screen's blue.
        picture = art.header(width, tallest, (), title=w("guide.%s.name" % key),
                             scale=self.app.scale, title_at=TITLE_AT)
        self.body.set_head(picture, question, (px(SUB_AT[0]), px(SUB_AT[1])), sub_width)

    # ------------------------------------------------------------------------------------- steps

    def show(self, index):
        self.index = index
        px = self.app.ui.px
        # The step's main buttons are made again with it (pages.main_button).
        self.app.main_buttons = []
        for child in self.body.inner.winfo_children():
            child.destroy()
        content = tk.Frame(self.body.inner, bg=theme.BG)
        from opendmt3.client.app import FOOT
        content.pack(fill="both", expand=True, padx=px(32), pady=(px(4), px(FOOT)))
        [self._welcome, self._folder, self._screen, self._login, self._ready][index](content)
        # One column for the names of the step's settings, as a page has (common.ROWS_THAT_COME names the guide's own
        # as "guide:<step>", apart from the pages').
        widgets.fit_names(content, self.app.ui, pages.rows_that_come("guide:" + STEPS[index]))
        # The step on show lit in the column (the numbers say where the guide is: no counter besides).
        self.rail.set_step(index)
        self.back_button.enable(index > 0)
        last = index == len(STEPS) - 1
        # Next on every step but the last, where the big PLAY stands under Back in its place; Skip over them on every
        # step but the last too, as the last one sets nothing up that Skip would leave undone (its page has the way to
        # the launcher).
        from opendmt3.client.app import OVER_PLAY
        if last:
            self.next_button.pack_forget()
            self.skip.pack_forget()
            self.play_slab.pack(side="top", anchor="w", pady=(px(OVER_PLAY), 0))
        else:
            self.play_slab.pack_forget()
            self.next_button.pack(side="right")
            if not self.skip.winfo_manager():
                self.skip.pack(side="top", anchor="w", before=self.buttons, pady=(0, px(10)))
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
        can = self._can_go_on()
        self.next_button.enable(can)
        # One lit main action on the screen: the step's own main button (Add a player, Sign in, Connect) while Next
        # waits for it, quiet once Next is lit and going on is the next thing to do.
        self.app.main_buttons = [b for b in self.app.main_buttons if b.winfo_exists()]
        for button in self.app.main_buttons:
            button.set_kind("secondary" if can else "primary")
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
        # One group of rows (a card for one choice said little but its name): the language, what a first start needs,
        # and the notice under them, each row parted by the card's faint line.
        start = card(parent, ui, last=True)
        widgets.setting_row(start.body, ui, w("about.language"),
                            lambda p: widgets.Segmented(p, ui, pages.language_options(app),
                                                        app.state.picked_language or "system",
                                                        self._language)).pack(fill="x")
        widgets.divider(start.body, ui)
        widgets.text_row(start.body, ui, w("guide.1.need"), [w("guide.1.need.1"), w("guide.1.need.2")]).pack(fill="x")
        widgets.divider(start.body, ui)
        # The notice in the LAUNCHER page's own words for it: a request, not an error, in the hints' ink.
        widgets.label(start.body, ui, w("guide.1.notice"), font=ui.fonts.small, fg=theme.MUTED,
                      wrap_margin=0).pack(fill="x")

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
        and what the player chooses, each on a card of its own (client/found_list.py: the GAME page's card), with
        Choose a folder... and Choose an archive... under them. The list stands on the page itself: a card round its
        cards would only frame them again, and push Choose... under the foot of the window the launcher opens at."""
        self.found.build(parent)

    def _chosen_usable(self):
        """DISC CHECK goes on with client data that plays: the chosen one, ready."""
        found = self.found.chosen()
        return found is not None and found.state == intake.READY

    # ------------------------------------------------------------------------- 3 SOUND CHECK

    def _screen(self, parent):
        app, ui, w = self.app, self.app.ui, self.app.words
        # The same rows as the SCREEN, CONTROLS and SOUND pages, the ones a first start needs, in one group (cards of
        # one or two rows said little but their names); a choice makes its own row again with its new hint and no
        # other (pages.Sections).
        group = card(parent, ui, last=True)
        sections = pages.Sections(app, group.body, pages.rows_that_come("guide:3"))

        def chose(name, value, section):
            app.changed(name, value)
            # The hint under the choice says the new one: its card again, where it was.
            sections.redo(section)

        class _Part:
            # A part of the group: its rows go into the holder Sections made for it.
            def __init__(self, holder):
                self.body = holder

        def display(holder):
            mode = app.state.values["display_mode"]
            made = _Part(holder)
            widgets.setting_row(made.body, ui, w("screen.mode"),
                                lambda p: widgets.Segmented(p, ui, [("fullscreen", w("screen.mode.fullscreen")),
                                                                    ("window", w("screen.mode.window"))], mode,
                                                            lambda value: chose("display_mode", value, "display")),
                                w("screen.mode.hint." + mode)).pack(fill="x")

        def controls(holder):
            device = "mouse" if app.state.values["cursor"] else "touch"
            made = _Part(holder)
            widgets.divider(made.body, ui)
            widgets.setting_row(made.body, ui, w("controls.input"),
                                lambda p: widgets.Segmented(p, ui, [("mouse", w("controls.input.mouse")),
                                                                    ("touch", w("controls.input.touch"))], device,
                                                            lambda d: chose("cursor", d == "mouse", "input")),
                                w("controls.input.hint." + device)).pack(fill="x")

        def volume(holder):
            v = app.state.values
            made = _Part(holder)
            for name, key in (("music_volume", "sound.music"), ("key_volume", "sound.keys")):
                widgets.divider(made.body, ui)
                widgets.setting_row(made.body, ui, w(key),
                                    lambda p, n=name: widgets.Slider(p, ui, v[n], lambda val, n=n: app.changed(n, val)),
                                    w(key + ".hint")).pack(fill="x")

        for name, build in (("display", display), ("input", controls), ("volume", volume)):
            sections.add(name, build)

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

        # Where you play, on the ONLINE page's own card; on this PC the players and the form that adds one are rows of
        # the same group, with another server its address, its sign-in and its test (a card for one choice said little
        # but its name). The test's card, when it shows, keeps its own gap above it.
        where = card(parent, ui, w("online.where"), last=True)
        choice = widgets.setting_row(where.body, ui, w("online.mode"),
                                     lambda p: widgets.Segmented(p, ui, [("this_pc", w("online.mode.this_pc")),
                                                                         ("server", w("online.mode.server")),
                                                                         ("offline", w("online.mode.offline"))], mode,
                                                                 set_mode),
                                     w("online.mode.hint." + mode))
        choice.pack(fill="x")
        if mode == "server":
            # The server's rows in the same group; what lets the guide go on at its foot.
            last = pages.server_panel(app, where, parent, lambda: self.show(self.index), choice)
            self._needed(last.body, "guide.login.need.server")
            return
        if mode != "this_pc":
            return
        try:
            rows = app.player_rows()
        except hosting.HostingError as e:
            # The database cannot be read: said in place of the players, and the guide still goes on.
            widgets.divider(where.body, ui)
            pages.database_trouble(app, where.body, e)
            return
        if rows:
            players = where
            widgets.divider(players.body, ui)
            for i, r in enumerate(rows):
                if i:
                    widgets.divider(players.body, ui, pady=6)
                on = r["login_id"] == app.state.player
                line = tk.Frame(players.body, bg=theme.PANEL_HI if on else players.body.cget("bg"), padx=px(10),
                                pady=px(6), cursor="hand2")
                line.pack(fill="x")
                parts = [widgets.Lamp(line, ui, theme.BLUE_HI if on else theme.MUTED, lit=on),
                         tk.Label(line, text=r["dj_name"], font=app.fonts.body_bold, fg=theme.TEXT, bg=line["bg"]),
                         tk.Label(line, text=r["login_id"], font=app.fonts.small, fg=theme.MUTED, bg=line["bg"])]
                for j, part in enumerate(parts):
                    part.pack(side="left", padx=(0 if j == 0 else px(10), 0))
                for widget in [line] + parts:
                    widget.bind("<Button-1>", lambda e, login_id=r["login_id"]: self._choose_player(login_id))
        # The form that adds a player, named by its key (Add a player), under the group's faint line.
        widgets.divider(where.body, ui, pady=14)
        pages.player_form(app, where.body, self._choose_player)
        self._needed(where.body, "guide.login.need")

    def _needed(self, body, key):
        """LOG IN's word on why Next is off, while it is: what lets the guide go on, at the foot of the step's last
        card (`body`), parted from what is above it by the card's faint line, inside the card's padding (words never
        lie on the page's field outside a card)."""
        if self._can_go_on():
            return
        ui = self.app.ui
        widgets.divider(body, ui)
        widgets.label(body, ui, self.app.words(key), fg=theme.MUTED, wrap_margin=0).pack(fill="x")

    def _choose_player(self, login_id):
        self.app.state.player = login_id
        self.app.state.save()
        self.show(self.index)

    # ------------------------------------------------------------------------- 4 STAGE START

    def _ready(self, parent):
        app, ui, px, w = self.app, self.app.ui, self.app.ui.px, self.app.words
        ready = card(parent, ui, w("play.ready"), last=True, kind="status")
        app.check_box = tk.Frame(ready.body, bg=ready.body.cget("bg"))
        app.check_box.pack(fill="x")
        app.refresh_checks()
        pages.refresh_checks(app)
        # The way to the launcher's pages without playing, where Skip stood on the steps before, under the ready check
        # and parted from it by the card's faint line. (How the game plays and how to leave it are the guides' in the
        # docs: the launcher shows no card of instructions.)
        widgets.divider(ready.body, ui)
        widgets.link(ready.body, ui, w("guide.4.launcher"), lambda: self.finish(play=False)).pack(anchor="w",
                                                                                                  pady=(px(12), 0))
