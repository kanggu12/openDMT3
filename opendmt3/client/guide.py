"""The first-start guide: five steps from nothing to the first song.

POWER ON (language, what is needed), DISC CHECK (find the game folder), SOUND CHECK (screen and sound), LOG IN
(play on this PC with a DJ of your own, on another server with the ID its owner made, or offline as a guest),
STAGE START (the ready check, and how to leave the game). Every choice
is the same setting the launcher's pages show, so the guide never knows anything the pages do not.
"""

import tkinter as tk

from PIL import ImageTk

from opendmt3.client import art, found_list, hosting, intake, pages, theme, updates, widgets

# Step keys name the words in i18n (guide.<key>.name, .sub, .title); the number shown is the place in this list.
STEPS = ("1", "2", "3", "login", "4")


class Guide:
    def __init__(self, app):
        self.app = app
        self.index = 0                   # the step on show
        self._header_job = None          # a header drawing waiting for a resize to settle
        # DISC CHECK's list: kept across the steps (and a change of language), so the search runs once.
        self.found = found_list.FoundList(app, on_update=self._update_next)

    # ------------------------------------------------------------------------------------- frame

    def build(self):
        app, ui, px, w = self.app, self.app.ui, self.app.ui.px, self.app.words
        root = app.root
        side = tk.Frame(root, bg=theme.SIDEBAR, width=px(258))
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        # The guide is PLAY's way in: the title screen's blue throughout.
        ui.use_section("play")
        brand = tk.Frame(side, bg=theme.SIDEBAR)
        brand.pack(fill="x", padx=px(24), pady=(px(28), px(8)))
        picture = art.logo(px(258) - px(48), app.scale, version=updates.shown_version())
        self._logo = ImageTk.PhotoImage(picture, master=root)
        mark = tk.Label(brand, image=self._logo, bg=theme.SIDEBAR, bd=0)
        mark.opendmt3_picture = picture
        mark.pack(anchor="w")
        # What the list under it is, named like every part of a page: on the game's dark name plate.
        widgets.section(brand, ui, w("guide.heading"), bg=theme.SIDEBAR).pack(anchor="w", pady=(px(18), 0))
        self.step_rows = []
        steps_box = tk.Frame(side, bg=theme.SIDEBAR)
        steps_box.pack(fill="x", padx=px(12), pady=(px(14), 0))
        for i, key in enumerate(STEPS):
            self.step_rows.append(self._step_row(steps_box, i, key))
        skip = tk.Label(side, text=w("guide.skip"), font=app.fonts.small, fg=theme.MUTED, bg=theme.SIDEBAR,
                        cursor="hand2")
        skip.pack(side="bottom", pady=px(22))
        skip.bind("<Button-1>", lambda e: self.finish(play=False))
        right = tk.Frame(root, bg=theme.BG)
        right.pack(side="left", fill="both", expand=True)
        self.header = tk.Canvas(right, height=px(116), bg=theme.BG, highlightthickness=0)
        self.header.pack(fill="x")
        # As the launcher's header: drawn at once at its first size, and once a drag settles after that (a drag fires
        # a resize event at every step: 39 drawings in a 40-step drag, the drag 2.7 s long).
        self.header.bind("<Configure>", lambda e: self._queue_header(
            now=getattr(self.header, "opendmt3_picture", None) is None))
        bottom = tk.Frame(right, bg=theme.PANEL)
        bottom.pack(side="bottom", fill="x")
        tk.Frame(bottom, bg=theme.LINE, height=1).pack(fill="x")
        bar = tk.Frame(bottom, bg=theme.PANEL)
        bar.pack(fill="x", padx=px(24), pady=px(14))
        self.counter = tk.Label(bar, text="", font=app.fonts.section, fg=theme.MUTED, bg=theme.PANEL)
        self.counter.pack(side="left")
        self.next_button = widgets.Button(bar, ui, w("guide.next"), self.next, kind="primary")
        self.next_button.pack(side="right")
        self.back_button = widgets.Button(bar, ui, w("guide.back"), self.back)
        self.back_button.pack(side="right", padx=(0, px(10)))
        self.body = widgets.ScrollArea(right, ui)
        self.body.pack(fill="both", expand=True)
        self.show(self.index)

    def _step_row(self, parent, i, key):
        """One step of the list, drawn like an entry of the launcher's menu (art.menu_entry): the step on show on
        the striped plate, the steps taken in white words, the ones to come in grey; a line of small words under
        each."""
        app, px = self.app, self.app.ui.px
        row = tk.Frame(parent, bg=theme.SIDEBAR)
        row.pack(fill="x", pady=(0, px(10)))
        words = app.words("guide.%s.name" % key)
        size = (px(258) - px(24), px(34))
        # Each state drawn once; the entry swaps pictures as the guide moves.
        pictures = {state: art.menu_entry(words, *size, state, app.ui.section, app.scale)
                    for state in ("off", "done", "on")}
        images = {state: ImageTk.PhotoImage(p, master=row) for state, p in pictures.items()}
        entry = tk.Label(row, image=images["off"], bg=theme.SIDEBAR, bd=0)
        entry.images, entry.pictures, entry.words = images, pictures, words
        entry.opendmt3_picture = pictures["off"]
        entry.pack(anchor="w")
        small = tk.Label(row, text=app.words("guide.%s.sub" % key), font=app.fonts.small, fg=theme.FAINT,
                         bg=theme.SIDEBAR)
        # Under the plate's words, which start past the plate's leaning end.
        small.pack(anchor="w", padx=(int(size[1] * art.LEAN) + int(12 * app.scale), 0))
        return entry, small

    def _paint_steps(self):
        for i, (entry, small) in enumerate(self.step_rows):
            state = "done" if i < self.index else ("on" if i == self.index else "off")
            entry.configure(image=entry.images[state])
            # The window's picture behind a dialog (snapshot.py) shows the entry as it is now.
            entry.opendmt3_picture = entry.pictures[state]
            small.configure(fg=theme.MUTED if i <= self.index else theme.FAINT)

    def _queue_header(self, now=False):
        """Draw the header again: at once (`now`), or 90 ms after the last of a drag's resize events."""
        if self._header_job is not None:
            self.app.root.after_cancel(self._header_job)
            self._header_job = None
        if now:
            self._draw_header()
            return
        self._header_job = self.app.root.after(90, self._draw_header)

    def _draw_header(self):
        self._header_job = None
        c, w = self.header, self.app.words
        if not c.winfo_exists():
            # The guide was left (or drawn again in another language) while a drawing waited.
            return
        width, height = c.winfo_width(), c.winfo_height()
        if width < 50:
            return
        key = STEPS[self.index]
        title = w("guide.%s.title" % key)
        # The step's title is part of the picture, in chrome like the launcher's pages.
        picture = art.header(width, height, (), seed=3 + 10 * self.index, title=title, scale=self.app.scale,
                             title_at=(32, 70))
        self._header_img = ImageTk.PhotoImage(picture, master=c)
        c.opendmt3_picture = picture
        c.delete("all")
        c.create_image(0, 0, image=self._header_img, anchor="nw")

    # ------------------------------------------------------------------------------------- steps

    def show(self, index):
        self.index = index
        px, w = self.app.ui.px, self.app.words
        for child in self.body.inner.winfo_children():
            child.destroy()
        content = tk.Frame(self.body.inner, bg=theme.BG)
        content.pack(fill="both", expand=True, padx=px(32), pady=(px(20), px(28)))
        [self._welcome, self._folder, self._screen, self._login, self._ready][index](content)
        self._paint_steps()
        self.counter.configure(text=w("guide.step", n=index + 1, total=len(STEPS)).upper()
                               if w.language == "en" else w("guide.step", n=index + 1, total=len(STEPS)))
        self.back_button.enable(index > 0)
        last = index == len(STEPS) - 1
        self.next_button.set_text(w("bottom.play") if last else w("guide.next"))
        self._update_next()
        self.body.to_top()
        # The step's title at once (a drawing that waited for a resize is folded into this one).
        self._queue_header(now=True)

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

    def next(self):
        if self.index == len(STEPS) - 1:
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
        app, ui, px, w = self.app, self.app.ui, self.app.ui.px, self.app.words
        widgets.label(parent, ui, w("guide.1.text"), wrap_margin=0).pack(fill="x", pady=(0, px(18)))
        widgets.setting_row(parent, ui, w("about.language"),
                            lambda p: widgets.Segmented(p, ui, pages.language_options(app),
                                                        app.state.picked_language or "system",
                                                        self._language)).pack(
            fill="x", pady=(0, px(20)))
        # The notice on a plain panel, in the Launcher page's own words for it: a request, not an error.
        notice = tk.Frame(parent, bg=theme.LINE, padx=1, pady=1)
        notice.pack(fill="x", pady=(0, px(20)))
        inner = tk.Frame(notice, bg=theme.PANEL, padx=px(16), pady=px(12))
        inner.pack(fill="x")
        widgets.label(inner, ui, w("guide.1.notice"), bg=theme.PANEL, wrap_margin=0).pack(fill="x")
        card = widgets.Card(parent, ui, title=w("guide.1.need"))
        card.pack(fill="x")
        for key in ("guide.1.need.1", "guide.1.need.2"):
            row = tk.Frame(card.body, bg=theme.PANEL)
            row.pack(fill="x", pady=(0, px(6)))
            # A list's mark: a grey lamp (the coloured ones say how a check stands).
            lamp = widgets.Lamp(row, ui, theme.MUTED, bg=theme.PANEL)
            lamp.pack(side="left", anchor="n", pady=(lamp.drop, 0))
            widgets.label(row, ui, w(key), bg=theme.PANEL, wrap_margin=0, beside=[lamp]).pack(
                side="left", padx=(px(9), 0))

    def _language(self, language):
        """Switching language rebuilds the guide in the other language, on the same step."""
        index = self.index
        self.app.state.language = None if language == "system" else language
        self.app.state.save()
        self.app._setup_fonts()
        for child in self.app.root.winfo_children():
            child.destroy()
        self.build()
        self.show(index)

    # -------------------------------------------------------------------------- 2 DISC CHECK

    def _folder(self, parent):
        """Where the game is: what the search finds on this PC and what the player chooses, as cards
        (client/found_list.py), with Choose a folder... and Choose an archive... under them."""
        ui, px, w = self.app.ui, self.app.ui.px, self.app.words
        widgets.label(parent, ui, w("guide.2.text"), wrap_margin=0).pack(fill="x", pady=(0, px(16)))
        self.found.build(parent)

    def _chosen_usable(self):
        """DISC CHECK goes on with a game folder that plays: the chosen one, ready."""
        found = self.found.chosen()
        return found is not None and found.state == intake.READY

    # ------------------------------------------------------------------------- 3 SOUND CHECK

    def _screen(self, parent):
        app, ui, px, w = self.app, self.app.ui, self.app.ui.px, self.app.words
        v = app.state.values
        # The same rows as the Screen, Controls and Sound pages, the ones a first start needs.
        widgets.section(parent, ui, w("screen.display")).pack(fill="x", pady=(0, px(14)))
        widgets.setting_row(parent, ui, w("screen.mode"),
                            lambda p: widgets.Segmented(p, ui, [("fullscreen", w("screen.mode.fullscreen")),
                                                                ("window", w("screen.mode.window"))],
                                                        v["display_mode"], self._set_and_redraw("display_mode")),
                            w("screen.mode.hint." + v["display_mode"])).pack(fill="x", pady=(0, px(16)))
        device = "mouse" if v["cursor"] else "touch"
        widgets.setting_row(parent, ui, w("controls.input"),
                            lambda p: widgets.Segmented(p, ui, [("mouse", w("controls.input.mouse")),
                                                                ("touch", w("controls.input.touch"))], device,
                                                        lambda d: self._set_and_redraw("cursor")(d == "mouse")),
                            w("controls.input.hint." + device)).pack(fill="x", pady=(0, px(18)))
        widgets.section(parent, ui, w("sound.volumes")).pack(fill="x", pady=(0, px(14)))
        for name, key in (("music_volume", "sound.music"), ("key_volume", "sound.keys")):
            widgets.setting_row(parent, ui, w(key),
                                lambda p, n=name: widgets.Slider(p, ui, v[n],
                                                                 lambda val, n=n: app.changed(n, val)),
                                w(key + ".hint")).pack(fill="x", pady=(0, px(16)))

    def _set_and_redraw(self, name):
        def setter(value):
            self.app.changed(name, value)
            self.show(self.index)
        return setter

    # ------------------------------------------------------------------------------- LOG IN

    def _login(self, parent):
        from opendmt3.client import pages
        app, ui, px, w = self.app, self.app.ui, self.app.ui.px, self.app.words
        if not getattr(self, "_mode_offered", False):
            # The guide's suggestion: a DJ of your own on this PC (records kept); offline stays one click away.
            self._mode_offered = True
            if app.state.mode == "offline" and not app.state.player:
                app.state.mode = "this_pc"
                app.state.save()
                app.read_song_list_ahead()
        widgets.label(parent, ui, w("guide.login.text"), wrap_margin=0).pack(fill="x", pady=(0, px(16)))
        mode = app.state.mode

        def set_mode(value):
            app.state.mode = value
            app.state.save()
            app.read_song_list_ahead()
            self.show(self.index)

        widgets.setting_row(parent, ui, w("online.mode"),
                            lambda p: widgets.Segmented(p, ui, [("this_pc", w("online.mode.this_pc")),
                                                                ("server", w("online.mode.server")),
                                                                ("offline", w("online.mode.offline"))], mode, set_mode),
                            w("online.mode.hint." + mode)).pack(fill="x", pady=(0, px(18)))
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
            pages.database_trouble(app, parent, e, theme.BG)
            return
        if rows:
            widgets.section(parent, ui, w("online.players")).pack(fill="x", pady=(0, px(12)))
            for r in rows:
                on = r["login_id"] == app.state.player
                line = tk.Frame(parent, bg=theme.PANEL_HI if on else theme.PANEL, padx=px(14), pady=px(8),
                                cursor="hand2")
                line.pack(fill="x", pady=(0, px(6)))
                parts = [widgets.Lamp(line, ui, theme.BLUE_HI if on else theme.MUTED, lit=on, bg=line["bg"]),
                         tk.Label(line, text=r["dj_name"], font=app.fonts.body_bold, fg=theme.TEXT, bg=line["bg"]),
                         tk.Label(line, text=r["login_id"], font=app.fonts.small, fg=theme.MUTED, bg=line["bg"])]
                for i, part in enumerate(parts):
                    part.pack(side="left", padx=(0 if i == 0 else px(10), 0))
                for widget in [line] + parts:
                    widget.bind("<Button-1>", lambda e, login_id=r["login_id"]: self._choose_player(login_id))
            tk.Frame(parent, bg=theme.BG, height=px(10)).pack(fill="x")
        widgets.section(parent, ui, w("online.add")).pack(fill="x", pady=(0, px(12)))
        pages.player_form(app, parent, self._choose_player)
        self._needed(parent, "guide.login.need")

    def _needed(self, parent, key):
        """LOG IN's word on why Next is off, under the form, while it is: what lets the guide go on."""
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
        widgets.label(parent, ui, w("guide.4.text"), wrap_margin=0).pack(fill="x", pady=(0, px(16)))
        card = widgets.Card(parent, ui, title=w("play.ready"))
        card.pack(fill="x")
        app.check_box = tk.Frame(card.body, bg=theme.PANEL)
        app.check_box.pack(fill="x")
        app.refresh_checks()
        pages.refresh_checks(app)
        # How to leave the game, before the first PLAY: no key does, and nothing in the game says where the X is.
        widgets.label(parent, ui, w("play.how.4"), fg=theme.MUTED, wrap_margin=0).pack(fill="x", pady=(px(16), 0))
        link = tk.Label(parent, text=w("guide.4.launcher") + " \u203a", font=app.fonts.body_bold, fg=theme.BLUE_HI,
                        bg=theme.BG, cursor="hand2")
        link.pack(anchor="w", pady=(px(16), 0))
        link.bind("<Button-1>", lambda e: self.finish(play=False))
