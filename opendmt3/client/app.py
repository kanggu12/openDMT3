"""The launcher window, laid out as OpenDMTQ's launcher and both sites are: the bar across the top with the mark, the
version and the menu, the page under it (its head, the title over the section's shards, then its cards, scrolling
together), and the strip along the foot with the status line and PLAY.

Slow work (checking the game folder, rewriting archives, reading song discs, update checks) runs on worker
threads; they hand results back through a queue the window empties every 50 ms, because Tk may only be touched
from the thread that created it.
"""

import logging
import queue
import threading
import tkinter as tk

from PIL import ImageTk

from opendmt3.core import safety
from opendmt3.core import game as g
from opendmt3.client import actions, art, collecting, hosting, i18n, theme, updates, widgets
# Where the window goes: plain numbers, importable without Tk (and so tested where Tk is missing).
from opendmt3.client.window_room import title_bar_height, window_box, work_area

log = logging.getLogger("opendmt3.launcher")

# The menu, left to right.
NAV = ("play", "screen", "sound", "controls", "game", "online", "records", "help", "about")
# The page head's height (logical pixels): the title and the line under it over the section's shards (PLAY's discs at
# its right), scrolling with the page under the bar as a page of the site does under its own.
HEAD = 128
# Where the title stands in the head and where the line under it starts (left edge and baseline, left edge and top).
TITLE_AT, SUB_AT = (32, 60), (32, 78)
# The strip along the foot: its least height inside its padding (PLAY's slab and its keyboard ring), the same on every
# page and every step of the guide, so the page above it never moves as Next turns into PLAY (OpenDMTQ's BAR_HEIGHT).
BAR_HEIGHT = 54
# Each page gets its own arrangement of shards, so moving between pages feels like moving.
SEEDS = {"play": 7, "screen": 11, "sound": 23, "controls": 31, "game": 5, "online": 13, "records": 19, "help": 17,
         "about": 41}


class LauncherApp:
    """The whole launcher: owns the Tk root, the remembered state and the game session."""

    def __init__(self, state, root=None):
        # The launcher's own window: never on a real screen from a test.
        safety.refuse_windows_in_tests("the launcher window")
        self.state = state
        # Fonts must be registered before Tk measures any text.
        theme.register_fonts()
        self.root = root or tk.Tk()
        self.root.title("openDMT3")
        self.root.configure(bg=theme.BG)
        # A failed action in the window is said in the launcher's own dialog (Tk would print it nowhere).
        self.root.report_callback_exception = self._callback_failed
        self._telling_failure = False
        # The mark in the title bar and on the taskbar, not Tk's feather.
        from opendmt3.client import dialogs
        dialogs.set_icon(self.root)
        self.tasks = queue.Queue()      # functions from worker threads, run on the Tk thread
        # Pictures freed on a worker thread would call Tk from it: this thread collects instead (collecting.py).
        self.collector = collecting.OnThisThread()
        self.session = None             # the running game, while it runs
        self.discs = None               # song discs from the player's archives (None: not read yet)
        self.checks = None              # the last ready check (None: being made)
        self.page = "play"              # the page on show
        self.busy = False               # PLAY is getting the folder ready
        self.status_text, self.status_tone = "", "normal"
        self.status_sticky = False            # a message the ready check must not replace (an update's outcome)
        self._header_job = None
        self.host = hosting.BuiltinServer(lan=state.lan)   # the server for playing on this PC, started at PLAY
        self.quit_after_game = False          # the window was closed while the game ran
        self.dialog = None                    # the dialog on show (dialogs.py), while one is
        self.then = None                      # what main() runs once the window is gone (removing openDMT3)
        self.removing = False                 # the game's files are going back to remove openDMT3
        self.guide = None                     # the first-start guide, while it is on show
        self.main_buttons = []                # the page's main buttons (pages.main_button), lit while PLAY is not
        self.folder_look = None               # what the folder in use is (client/intake.py), for the Game page
        self.game_list = None                 # the Game page's list of folders to change to, while it is open
        self._setup_fonts()
        self._size_window()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(50, self._pump)
        self.show()
        self._update_outcome()
        if self.state.mode == "this_pc" and self.state.lan:
            # Open to the other PCs on this network: the server runs while the launcher is open, not only at PLAY.
            threading.Thread(target=self._start_home_server, daemon=True, name="lan").start()
        self.read_song_list_ahead()

    def read_song_list_ahead(self):
        """Playing on this PC with a game folder chosen: the server's song list is read now, apart from the window,
        so the first PLAY does not wait for it (it waits only for what is left of it)."""
        if self.state.mode == "this_pc" and self.state.game_folder:
            self.host.import_catalog_soon(self.state.game_folder)

    def _start_home_server(self):
        try:
            self.host.start()
        except Exception as e:  # noqa: BLE001  (shown, never swallowed)
            log.exception("the server for the other PCs did not start")
            self.post(lambda e=e: self.set_status(self.words("status.error", error=self.words.error(e)), "bad"))

    # --------------------------------------------------------------------------------------- frame

    def _setup_fonts(self):
        """Fonts, words and DPI scale for the current language (a language change rebuilds them)."""
        self.scale = theme.scale_of(self.root)
        self.words = i18n.Words(self.state.language)
        self.fonts = theme.Fonts(self.root, self.state.language)
        self.ui = widgets.Ui(self.root, self.fonts, self.scale, self.words)
        widgets.style_ttk(self.ui)

    def _size_window(self):
        """1180x760 at 100 % scaling, never more than 92 % of the room windows have (on Windows the work area: the
        screen less the taskbar, the title bar counted too), centred across it and a third of the way down."""
        px = self.ui.px
        w, h, x, y = window_box(work_area(self.root), title_bar_height(), px(1180), px(760))
        self.root.geometry("%dx%d+%d+%d" % (w, h, x, y))
        self.root.minsize(min(px(960), w), min(px(640), h))

    def show(self):
        """Build the guide on a first start, else the launcher itself."""
        for child in self.root.winfo_children():
            child.destroy()
        if not self.state.guide_done:
            from opendmt3.client import guide
            self.guide = guide.Guide(self)
            self.guide.build()
            return
        # The launcher's own pages: the guide is done with.
        self.guide = None
        self._build_main()
        self.go(self.page)
        self.refresh_checks()
        self.load_discs()

    def _build_main(self):
        ui, px, w = self.ui, self.ui.px, self.words
        from opendmt3.client import pages
        # ---- the bar across the top: the mark and the version, then the menu, as both sites' bars and OpenDMTQ's
        # launcher's (each name as its page's title)
        self.header = self.make_header(self.root, nav=[(key, pages.TITLES[key]) for key in NAV], on_nav=self.go)
        # ---- the strip along the foot: what is going on at the left, a report and PLAY at the right
        bottom = tk.Frame(self.root, bg=theme.PANEL)
        bottom.pack(side="bottom", fill="x")
        tk.Frame(bottom, bg=theme.LINE, height=1).pack(fill="x", side="top")
        bar = tk.Frame(bottom, bg=theme.PANEL)
        bar.pack(fill="x", padx=px(24), pady=px(12))
        # As tall as PLAY with its keyboard ring at the least, on every page and every step of the guide; a status line
        # long enough to wrap past that makes it taller rather than being cut (an error with a long path).
        tk.Frame(bar, bg=theme.PANEL, width=1, height=px(BAR_HEIGHT)).pack(side="left")
        self.play_button = self._make_play(bar)
        self.play_button.pack(side="right")
        widgets.Button(bar, ui, w("bottom.report"), self.save_report).pack(side="right", padx=(0, px(14)))
        # The lamp before the line: an outline while there is nothing to say, lit in the colour of what happened.
        self.status_lamp = widgets.Lamp(bar, ui, theme.MUTED, lit=False, bg=theme.PANEL)
        self.status_lamp.pack(side="left")
        self.status_label = tk.Label(bar, text="", font=self.fonts.body, fg=theme.MUTED, bg=theme.PANEL,
                                     justify="left", anchor="w", wraplength=px(520))
        self.status_label.pack(side="left", fill="x", expand=True, padx=(px(9), px(12)))
        # The line wraps at the room the bar leaves it (a long error would be cut at a fixed width).
        self.status_label.bind("<Configure>", self._wrap_status)
        # ---- the page: its head and its cards, scrolling together under the bar
        self.body = widgets.ScrollArea(self.root, ui)
        self.body.pack(fill="both", expand=True)
        # The head is drawn again for a new width, once a drag settles (the first width draws it at once).
        self.body.on_width = lambda width: self._queue_header(now=self.body.canvas.head_picture is None)
        # Tab goes as the window reads: the menu, the page, then the strip along the foot. Tk's Tab follows each
        # parent's stacking order, the order its children were made in until one is raised. (Misc's own raise: a
        # canvas's raise moves its items instead.)
        tk.Misc.tkraise(bottom)
        self._paint_status()

    def make_header(self, parent, nav=(), on_nav=None, steps=()):
        """The bar across the window's top (widgets.Header): the mark with LAUNCHER and the version beside it
        (art.brand), then the menu; the guide's has its steps under the bar instead."""
        header = widgets.Header(parent, self.ui, art.brand(self.scale, updates.shown_version()), nav=nav,
                                on_nav=on_nav, steps=steps)
        header.pack(side="top", fill="x")
        return header

    # -------------------------------------------------------------------------------------- PLAY

    def _make_play(self, parent):
        """PLAY: the angular blue slab, its word in the game's wide letters."""
        px = self.ui.px
        size = (px(212), px(50))
        self._play_pictures = {s: art.play_button(*size, state=s)
                               for s in ("normal", "hover", "pressed", "disabled", "playing")}
        self._play_images = {s: ImageTk.PhotoImage(p, master=self.root) for s, p in self._play_pictures.items()}
        # The keyboard reaches it too, as OpenDMTQ's PLAY: Tab brings a cyan ring round it, Enter or Space presses it.
        button = tk.Label(parent, image=self._play_images["normal"], text=self.words("bottom.play"),
                          compound="center", font=self.fonts.display_big, fg=theme.TEXT, bg=theme.PANEL,
                          cursor="hand2", bd=0, takefocus=1, highlightthickness=max(1, px(2)),
                          highlightbackground=theme.PANEL, highlightcolor=theme.CYAN)
        button.bind("<Enter>", lambda e: self._paint_play("hover"))
        button.bind("<Leave>", lambda e: self._paint_play())
        button.bind("<Button-1>", lambda e: self._paint_play("pressed"))
        button.bind("<ButtonRelease-1>", lambda e: self.play())
        for key in ("<Return>", "<KP_Enter>", "<space>"):
            button.bind(key, lambda e: self.play())
        return button

    def _paint_play(self, mouse=None):
        """The button's look follows the state first (busy, playing), then the mouse."""
        if not hasattr(self, "play_button") or not self.play_button.winfo_exists():
            # The guide is on show: it has no PLAY bar.
            return
        if self.session is not None and self.session.running():
            look, text = "playing", self.words("bottom.playing")
        elif self.busy or not self.ready():
            look, text = "disabled", self.words("bottom.play")
        else:
            look, text = mouse or "normal", self.words("bottom.play")
        self.play_button.opendmt3_picture = self._play_pictures[look]
        self.play_button.configure(image=self._play_images[look], text=text,
                                   fg=theme.TEXT if look not in ("disabled", "playing") else theme.FAINT,
                                   cursor="hand2" if look not in ("disabled", "playing") else "arrow")
        # One lit main action on the screen, as OpenDMTQ's launcher has it: a page's main button (Connect, Sign in,
        # Add a player, the launcher's update) is quiet beside a lit PLAY, and lit while PLAY waits, when it is the
        # next thing to do.
        kind = "secondary" if self.play_lit() else "primary"
        for button in self.main_buttons:
            if button.winfo_exists():
                button.set_kind(kind)

    def play_lit(self):
        """True while PLAY can be pressed (lit), so that a page's main button stays quiet beside it."""
        return not (self.busy or (self.session is not None and self.session.running()) or not self.ready())

    def ready(self):
        """True when nothing blocks PLAY (a folder, a supported client, the game closed)."""
        if not self.checks:
            return bool(self.state.game_folder)
        return actions.can_play(self.checks)

    def play(self):
        """Get the folder in line with the choices on a worker thread, then start the game."""
        if self.busy or (self.session is not None and self.session.running()):
            return
        if not self.ready():
            self.set_status(self.why_not_ready(), "warn")
            self._paint_play()
            return
        self.busy = True
        self._paint_play()
        self.set_status(self.words("status.starting"), "normal")
        # What PLAY is doing, in the launcher's own progress look, until the game starts or PLAY stops.
        from opendmt3.client import getting_ready
        self.getting_ready = getting_ready.Shown(self)

        def at(step):
            self.set_status(self.words("status.preparing", step=self._step_name(step)), "normal")
            if self.getting_ready is not None:
                self.getting_ready.at(step)

        def work():
            try:
                # Asked for here, off the window's thread: another server is asked for the card at every PLAY.
                card = actions.card_for(self.state, self.host)
                session = actions.play(self.state, report=lambda step: self.post(lambda: at(step)),
                                       host=self.host, card=card)
                self.post(lambda: self._started(session))
            except actions.SignedOut:
                log.info("the server no longer takes the sign-in")
                self.post(self._signed_out)
            except Exception as e:  # noqa: BLE001  (any failure is shown, never swallowed)
                log.exception("PLAY failed")
                # Python forgets e when the except block ends; the message is taken now, the window shows it later.
                self.post(lambda error=e: self._failed(error))

        threading.Thread(target=work, daemon=True, name="play").start()

    def why_not_ready(self):
        """Why PLAY cannot go, as the status line says it: no folder chosen yet, or the first line of the ready check
        that stops it, in its own words (never a pointer to another part of the window)."""
        if not self.state.game_folder:
            return self.words("status.choose_folder")
        stopping = actions.blocking(self.checks or [])
        return actions.why_not(stopping[0], self.words) if stopping else self.words("status.choose_folder")

    def _step_name(self, step):
        from opendmt3.client import getting_ready
        return getting_ready.phase_words(self.words, step)

    def _ready_shown(self):
        """PLAY's progress look goes (the game started, or PLAY stopped and says why)."""
        if getattr(self, "getting_ready", None) is not None:
            self.getting_ready.close()
            self.getting_ready = None

    def _callback_failed(self, kind, value, tb):
        """An error nothing caught in a click or a timer: logged with its traceback, and said in a dialog of the
        launcher's own (one at a time); the window goes on."""
        log.error("a window action failed", exc_info=(kind, value, tb))
        if self._telling_failure or not self.root.winfo_exists():
            return
        self._telling_failure = True
        try:
            from opendmt3.core import errors
            from opendmt3.client import dialogs
            w = self.words
            # A line of its own: it ends with a full stop like the lines around it, whatever error it was.
            dialogs.tell(self, "error", w("crash.action.title"), w("crash.action.message"),
                         w("crash.action.detail", error=errors.closed(w.error(value), {})))
        except Exception:  # noqa: BLE001  (the log has it; a second failure is not told again)
            log.exception("could not tell a failed window action")
        finally:
            self._telling_failure = False

    def players(self):
        """The built-in server's accounts, on a connection for this (the window's) thread."""
        return self.host.accounts()

    def player_rows(self):
        """Every player on this PC, for the pages' lists (HostingError, worded, when the database cannot be read)."""
        return self.host.player_rows()

    def _started(self, session):
        self._ready_shown()
        self.busy = False
        self.session = session
        # PLAY holds the playing mutex from its start (actions.play): the installer refuses while it is held, and so
        # does another launcher's PLAY; _watch lets it go when the game closes.
        self.set_status(self.words("status.playing"), "ok")
        self._paint_play()
        # Out of the way while the game has the screen; it comes back when the game closes.
        self.root.iconify()
        self.root.after(1000, self._watch)

    def _watch(self):
        if self.session is not None and self.session.running():
            self.root.after(1000, self._watch)
            return
        from opendmt3.client import playing
        playing.release()
        record = actions.finish(self.state, self.session)
        started = self.session.started
        self.state.save()
        self.session = None
        self._collect_plays(started)
        if self.quit_after_game:
            # The window was closed while the game ran; the server stayed for the game, and now both go.
            self.host.stop()
            self.root.destroy()
            return
        self.root.deiconify()
        minutes = record["seconds"] // 60
        span = self.words("common.minutes", m=minutes) if minutes else self.words("common.seconds", s=record["seconds"])
        crashed = record["crashed"]
        self.set_status(self.words("status.crashed") if crashed else self.words("status.ended", time=span),
                        "bad" if crashed else "ok")
        self.refresh_checks()
        # The pages that say what the last game did: PLAY (its stages), Sound (the steps its sound went in).
        if self.page in ("play", "sound"):
            self.go(self.page)

    def _collect_plays(self, since):
        """The stages cleared in the session that just ended, for the PLAY page (on a worker thread)."""
        state = self.state

        def work():
            plays = []
            try:
                if state.mode == "this_pc" and state.player:
                    from opendmt3.server.services import catalog
                    accounts, records = self.host.accounts(), self.host.records()
                    try:
                        row = accounts.by_login(state.player)
                        rows = records.recent(row["id"], 3, since=since) if row else []
                    finally:
                        accounts.db.close()
                        records.db.close()
                    songs = self.host.catalog()
                    plays = [{"title": catalog.title(songs, r["song"]), "pattern": r["pattern"], "score": r["score"]}
                             for r in rows]
                elif state.mode == "server" and state.remote and state.remote.get("token"):
                    from opendmt3.client import remote
                    plays = [p for p in remote.plays(state.server_url, state.remote["token"]) if p["at"] >= since][:3]
            except Exception:  # noqa: BLE001  (the session's line still shows without its plays)
                log.exception("could not read the session's plays")
            self.post(lambda: self._plays_collected(plays))

        threading.Thread(target=work, daemon=True, name="plays").start()

    def _plays_collected(self, plays):
        if self.state.last_session is not None:
            self.state.last_session["plays"] = plays
            self.state.save()
        if self.page == "play":
            self.go("play")

    def set_lan(self, on):
        """Online's switch: open this PC's server to the other PCs on its network (it then runs while the launcher
        is open), or back to this PC only. A running server starts again on the new address."""
        self.state.lan = bool(on)
        self.state.save()
        self.set_status(self.words("online.home.opening" if on else "online.home.closing"), "normal")

        def work():
            try:
                if self.host.running:
                    self.host.stop()
                self.host.lan = self.state.lan
                if self.state.lan and self.state.mode == "this_pc":
                    self.host.start()
            except Exception as e:  # noqa: BLE001  (shown, never swallowed)
                log.exception("opening the server to the other PCs failed")
                self.post(lambda e=e: self.set_status(self.words("status.error", error=self.words.error(e)), "bad"))
                return
            # Open with no address to reach it at is said as it is, in the colour of something to look at.
            reached = bool(self.host.addresses()) if self.state.lan else True
            said = ("online.home.open.done" if reached else "online.home.open.no_address") if self.state.lan \
                else "online.home.closed"
            self.post(lambda: (self.set_status(self.words(said), "ok" if reached else "warn"),
                               self.page == "online" and self.go("online")))

        threading.Thread(target=work, daemon=True, name="lan").start()

    def open_records(self):
        """PLAY's [My records]: the chosen player's page on this PC's site, signed in, in the browser."""
        self.set_status(self.words("play.records.opening"), "normal")

        def work():
            try:
                # Starting the server and site can take a moment: never on the window's thread.
                actions.open_link(actions.records_link(self.state, self.host))
            except Exception as e:  # noqa: BLE001  (shown, never swallowed)
                log.exception("opening the records failed")
                self.post(lambda e=e: self.set_status(self.words("status.error", error=self.words.error(e)), "bad"))
                return
            self.post(lambda: self.set_status(self.words("play.records.opened"), "ok"))

        threading.Thread(target=work, daemon=True, name="records").start()

    def _failed(self, error):
        self._ready_shown()
        self.busy = False
        self.set_status(self.words("status.error", error=self.words.error(error)), "bad")
        self.refresh_checks()

    def _signed_out(self):
        """Another server stopped taking the sign-in: forget it, and send the player to sign in again."""
        self._ready_shown()
        self.busy = False
        actions.forget_sign_in(self.state)
        self.state.save()
        self.set_status(self.words("status.signed_out"), "warn")
        self.refresh_checks()
        self._paint_play()

    def _update_outcome(self):
        """Say whether the update handed to Velopack at the last close went in (a silent update says nothing)."""
        from opendmt3.client import updates
        try:
            outcome = updates.outcome()
        except Exception:  # noqa: BLE001  (a note that cannot be read is no reason to stop the launcher)
            log.exception("could not read the update note")
            return
        if outcome is None:
            return
        self.status_sticky = True
        if outcome[0] == "updated":
            self.set_status(self.words("status.updated", v=outcome[1]), "ok")
        else:
            log.warning("the update to %s did not go in (this is %s)", outcome[1], outcome[2])
            self.set_status(self.words("status.not_updated", v=outcome[1], now=outcome[2]), "warn")

    # ----------------------------------------------------------------------------------- pages

    def go(self, page):
        """Show a page: its name lit on the bar, its head (title and line) and its cards."""
        from opendmt3.client import pages
        self.page = page
        # The page's widgets take its section's colour.
        self.ui.use_section(page)
        self.header.set_current(page)
        # The page's main buttons are made again with it (pages.main_button).
        self.main_buttons = []
        for child in self.body.inner.winfo_children():
            child.destroy()
        content = tk.Frame(self.body.inner, bg=theme.BG)
        content.pack(fill="both", expand=True, padx=self.ui.px(32), pady=(self.ui.px(4), self.ui.px(28)))
        pages.BUILDERS[page](self, content)
        # One column for the names of the page's settings, as wide as the widest in either language and of the rows a
        # choice brings, so the controls stand on one line as rows come and go (OpenDMTQ's pages do the same).
        widgets.fit_names(content, self.ui, pages.rows_that_come(page))
        self.body.to_top()
        # The page's head in the same turn as the page: the shards are kept from the page's last visit at this size
        # (art.header_shards).
        self._queue_header(now=True)

    def redraw(self, page):
        """The page on show drawn again for a choice that adds or takes rows, or an answer that came: where it was
        scrolled to and with the keyboard on the control it was on (widgets.ScrollArea.keep_place)."""
        if self.page == page:
            self.body.keep_place(lambda: self.go(page))

    def _queue_header(self, now=False):
        """Draw the page's head again: at once (`now`: a page switch, the PLAY page's discs, the area's first width), or
        once the size settles (a drag fires many resize events: drawn 90 ms after the last)."""
        if self._header_job is not None:
            self.root.after_cancel(self._header_job)
            self._header_job = None
        if now:
            self._draw_header()
            return
        self._header_job = self.root.after(90, self._draw_header)

    def _draw_header(self):
        from opendmt3.client import pages
        self._header_job = None
        if not hasattr(self, "body") or not self.body.winfo_exists() or getattr(self, "guide", None) is not None:
            # The guide is on show; it draws its own heads.
            return
        width = self.body.canvas.winfo_width()
        if width < 50:
            return
        px = self.ui.px
        discs = self.discs if (self.page == "play" and self.discs) else ()
        title, sub = pages.HEADERS[self.page](self)
        colours = theme.section_colours(self.page)
        # The title is part of the picture: chrome letters, the TECHNIKA 3 logo's blue 3 on PLAY.
        picture = art.header(width, px(HEAD), discs, seed=SEEDS.get(self.page, 7), colours=colours, title=title,
                             title_tail="3" if title.endswith(" 3") else None, scale=self.scale, title_at=TITLE_AT)
        # The line under the title, as wide as the room the discs and the brightest shards leave it.
        self.body.set_head(picture, sub, (px(SUB_AT[0]), px(SUB_AT[1])), max(px(300), int(width * 0.52)))

    # ------------------------------------------------------------------------------ background

    def post(self, fn):
        """Run fn on the Tk thread (the only thread that may touch the window)."""
        self.tasks.put(fn)

    def _pump(self):
        """Run what the worker threads handed over. One failing task is logged and the rest still run: without
        this the window would stop taking results for good (PLAY stuck as busy, nothing shown)."""
        while True:
            try:
                task = self.tasks.get_nowait()
            except queue.Empty:
                break
            try:
                task()
            except Exception:  # noqa: BLE001
                log.exception("a task for the window failed")
        # The garbage the workers and the pages left, freed here where Tk may be called.
        self.collector.tick()
        self.root.after(50, self._pump)

    def refresh_checks(self):
        """Make the ready check again on a worker thread; the PLAY page and button follow it."""
        self.checks = None

        def work():
            try:
                checks = actions.readiness(self.state)
            except Exception as e:  # noqa: BLE001
                log.exception("ready check failed")
                # Said under the line in its own words (the player's language when the error has them).
                checks = [actions.Check("folder", False, str(e), page="game", error=e)]
            self.post(lambda: self._checked(checks))

        threading.Thread(target=work, daemon=True, name="check").start()

    def _checked(self, checks):
        self.checks = checks
        if not self.busy and not (self.session and self.session.running()):
            if not self.state.game_folder:
                self.set_status(self.words("status.choose_folder"), "warn")
            elif not self.ready():
                self.set_status(self.why_not_ready(), "warn")
            elif self.status_tone not in ("ok", "bad") and not self.status_sticky:
                self.set_status(self.words("status.ready"), "normal")
        self._paint_play()
        # The PLAY page, the HELP page and the guide's last step each show the check when they are on screen.
        from opendmt3.client import pages
        pages.refresh_checks(self)
        if self.guide is not None:
            # The guide's last step: its PLAY follows the check.
            self.guide.checks_changed()

    def load_discs(self):
        """Read a few song discs from the player's archives for the PLAY header (once per folder)."""
        if self.discs is not None or not self.state.game_folder:
            return

        def work():
            try:
                discs = art.read_discs(self.state.game())
            except g.GameError:
                discs = []
            self.post(lambda: self._discs_loaded(discs))

        threading.Thread(target=work, daemon=True, name="discs").start()

    def _discs_loaded(self, discs):
        self.discs = discs
        if self.page == "play":
            # The discs as soon as they are read.
            self._queue_header(now=True)
        elif self.page == "game":
            # The Game page's card shows three of them.
            self.go("game")

    # ---------------------------------------------------------------------------------- status

    def _wrap_status(self, event):
        label = self.status_label
        inside = 2 * sum(label.winfo_pixels(str(label.cget(o))) for o in ("padx", "bd", "highlightthickness"))
        wrap = max(self.ui.px(120), event.width - inside)
        if int(str(label.cget("wraplength"))) != wrap:
            label.configure(wraplength=wrap)

    def set_status(self, text, tone="normal"):
        self.status_text, self.status_tone = text, tone
        self._paint_status()

    def _paint_status(self):
        if not hasattr(self, "status_label") or not self.status_label.winfo_exists():
            return
        colour = {"normal": theme.MUTED, "ok": theme.LIME, "warn": theme.AMBER, "bad": theme.PINK}[self.status_tone]
        self.status_lamp.show(colour, lit=self.status_tone != "normal")
        self.status_label.configure(text=self.status_text, fg=theme.TEXT if self.status_tone != "normal" else theme.MUTED)

    # ------------------------------------------------------------------------------- changes

    def changed(self, name, value):
        """A setting changed on a page: remember it, and check the folder against it again."""
        self.state.set_value(name, value)
        self.state.save()
        self.set_status(self.words("status.saved"), "normal")
        self.refresh_checks()

    def set_unlock(self, on):
        self.state.unlock = bool(on)
        self.state.save()
        self.set_status(self.words("status.saved"), "normal")
        self.refresh_checks()

    def set_language(self, language):
        """Switch the words and fonts: the whole window is rebuilt in the other language. "system" follows Windows'
        display language again (the state keeps no choice then)."""
        self.state.language = None if language == "system" else language
        self.state.save()
        self._setup_fonts()
        self.show()

    def set_folder(self, folder):
        self.state.game_folder = folder
        self.discs = None
        self.state.save()
        self.refresh_checks()
        self.load_discs()
        self.read_song_list_ahead()

    def save_report(self):
        """Write a report zip to the Desktop (or the home folder) and say where it is."""
        import os
        from opendmt3.client import report, shortcuts
        # Windows' own desktop folder (it may be moved to OneDrive or another drive), else the home folder.
        target = shortcuts.desktop()
        if not os.path.isdir(target):
            target = os.path.expanduser("~")
        try:
            path = report.make(self.state, target)
            self.set_status(self.words("help.report.done", path=path), "ok")
        except OSError as e:
            # The system's reason as words (errors.say), never Python's "[Errno 28] ..." form.
            log.warning("the report could not be saved", exc_info=True)
            self.set_status(self.words("status.error", error=self.words.error(e)), "bad")

    def close(self):
        """Close the launcher. A game playing on this PC keeps its server: the launcher hides until the game ends."""
        if self.removing:
            # The game's files are going back (Help, Uninstall): stopping now would leave them half done. The
            # window closes by itself in a moment, when the work hands over to the uninstall.
            return
        if self.dialog is not None:
            # Closing the window answers an open question with Cancel.
            self.dialog.close(self.dialog.cancel_value)
        self.state.save()
        if self.session is not None and self.session.running() and self.host.running:
            self.quit_after_game = True
            self.root.withdraw()
            return
        self.host.stop()
        # No window, no pump: Python collects by itself again.
        self.collector.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()
