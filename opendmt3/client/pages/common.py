"""What the pages share: the pages' names, a card stacked under the ones before it, a page's cards made again one at
a time (Sections), a page's main button, the rows a choice brings or takes, and what a page shows when this PC's
database cannot be opened."""

import os
import tkinter as tk

# Each page's name in the menu and as its title, in English in both languages as both sites' menus and OpenDMTQ's
# launcher have them (and as the game's own menus are). A sentence that sends the player to a page names it so.
TITLES = {"play": "PLAY", "screen": "SCREEN", "sound": "SOUND", "controls": "CONTROLS", "game": "GAME",
          "online": "ONLINE", "records": "RECORDS", "help": "HELP", "about": "LAUNCHER"}

# The gap between two cards (logical pixels), OpenDMTQ's.
CARD_GAP = 16

# The names of the setting rows a choice or the PC brings to a page or takes from it (a window's size, the counter's
# corner, the upscale filter and its sharpness, motion clarity on a fast screen): counted in the page's names' column
# whether shown or not (widgets.fit_names), so that none of them moves the controls when it comes.
ROWS_THAT_COME = {
    "screen": ("screen.size", "screen.fps.position", "screen.upscale", "screen.sharpness", "screen.motion"),
    # The guide's SOUND CHECK: the Screen page's mode and the Controls page's input, the volumes.
    "guide:3": ("screen.mode", "controls.input", "sound.music", "sound.keys"),
}


# The pages that stand together in the menu share one column for their settings' names, as wide as the widest name of
# any of them in either language: the controls start on one line from page to page, never jumping sideways (the final
# review's B-17, C-08). By their names' keys (tests/e2e/ui/shots.py checks that the controls line up).
GROUPS = (("screen", "sound", "controls", "game"), ("about", "help"))
GROUP_NAMES = {
    "screen": ("screen.mode", "screen.size", "screen.vsync", "screen.pacing", "screen.motion", "screen.fps",
               "screen.fps.position", "screen.shape", "screen.render", "screen.upscale", "screen.sharpness",
               "screen.antialiasing", "screen.glow", "screen.videos", "screen.preload", "screen.pass_times",
               "screen.flip"),
    "sound": ("sound.master", "sound.music", "sound.keys", "sound.eq_60", "sound.eq_250", "sound.eq_1k", "sound.eq_4k",
              "sound.eq_12k", "sound.device", "sound.mixer", "sound.low_latency", "sound.offset"),
    "controls": ("controls.input",),
    "game": ("game.freeplay", "game.unlock"),
    "about": ("about.shortcut", "about.autostart", "about.language", "about.guide.row"),
    "help": ("help.report", "help.logs", "help.repair.row", "help.restore", "help.uninstall.row"),
}


def rows_that_come(page):
    """The names of ROWS_THAT_COME[page] in both languages, for widgets.fit_names."""
    from opendmt3.client import i18n
    return [words for key in ROWS_THAT_COME.get(page, ()) for words in i18n.TEXT[key] if words]


def group_names(page):
    """The settings' names of every page in `page`'s group (GROUPS) in both languages, for widgets.fit_names: one
    column for them all. LAUNCHER's version row too, with the version this launcher shows."""
    from opendmt3.client import i18n, updates
    group = next((pages for pages in GROUPS if page in pages), ())
    names = [words for member in group for key in GROUP_NAMES.get(member, ()) for words in i18n.TEXT[key] if words]
    if "about" in group:
        version = updates.shown_version()
        names += [words.format(v=version) for words in i18n.TEXT["about.version"] if words]
    return names


# The page column's width (logical pixels) from which two groups that belong together stand side by side, as tall as
# each other; in a narrower column (the small window, 960x640) the second stands under the first with the whole width,
# so that neither squeezes its rows (OpenDMTQ's 760).
PAIR_FROM = 760


class Pair(tk.Frame):
    """Two groups that belong together (the ready check and the player; the checks and what to try; the tools and what
    puts back and takes away): side by side and as tall as each other where the page's column is PAIR_FROM wide or
    wider, the first over the second in a narrower one. Each group is made in `left` or `right` (pair_card). Packed
    under what is before it, with the gap between cards under it unless `last`."""

    def __init__(self, app, parent, last=False):
        super().__init__(parent, bg=parent.cget("bg"))
        self.ui, self.wide = app.ui, None
        self.pack(fill="x", pady=(0, 0 if last else app.ui.px(CARD_GAP)))
        # The two sides, on the page's colour: the gap between them is the page's own field.
        self.left = tk.Frame(self, bg=self.cget("bg"))
        self.right = tk.Frame(self, bg=self.cget("bg"))
        # Laid out for the column the page has now (known once the window shows), then again whenever the column
        # crosses PAIR_FROM: its width comes from the page, never from the groups, so a new layout never loops.
        self._lay(app.content_width())
        self.bind("<Configure>", lambda e: self._lay(e.width), add="+")

    def _lay(self, width):
        # Before the window has a width: side by side, as at the launcher's own size.
        wide = width <= 1 or width >= self.ui.px(PAIR_FROM)
        if wide == self.wide:
            # Only a change of side: the same layout again would ask the page to lay itself out for nothing.
            return
        self.wide = wide
        gap = self.ui.px(CARD_GAP)
        if wide:
            # Two columns of one width, the gap between cards between them.
            self.columnconfigure(0, weight=1, uniform="pair")
            self.columnconfigure(1, weight=1, uniform="pair")
            self.left.grid(row=0, column=0, sticky="nsew", padx=(0, gap), pady=0)
            self.right.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        else:
            # One column with the whole width (the second column given nothing), the second group under the first.
            self.columnconfigure(0, weight=1, uniform="")
            self.columnconfigure(1, weight=0, uniform="")
            self.left.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
            self.right.grid(row=1, column=0, sticky="nsew", padx=0, pady=(gap, 0))


def pair_card(holder, ui, title=None):
    """A group's card on one side of a Pair: it fills its side, so that the two stand as tall as each other."""
    from opendmt3.client import widgets
    made = widgets.Card(holder, ui, title=title)
    made.pack(fill="both", expand=True)
    return made


def card(parent, ui, title=None, last=False):
    """A card with its title, stacked under the ones before it with the gap between cards."""
    from opendmt3.client import widgets
    made = widgets.Card(parent, ui, title=title)
    made.pack(fill="x", pady=(0, 0 if last else ui.px(CARD_GAP)))
    return made


class Sections:
    """A page's cards, each made by a function of its own, so that a choice that brings or takes rows, or changes a
    hint, makes its own card again and no other (as OpenDMTQ's pages do): the new card is made beside the old one and
    takes its place in the same turn of the window, so nothing flickers, the page stays where it was scrolled to, the
    other cards (and what is typed in them) stay as they were, and the keyboard stays on the control it was on.

    `parent` is the page's (or the guide step's) content; `more` the names of the rows that come and go on it
    (rows_that_come), counted in its names' column, which a new card takes too."""

    def __init__(self, app, parent, more=()):
        self.app, self.parent, self.more = app, parent, more
        # name -> [the function that makes the card in a holder, the holder on the page]
        self.made = {}

    def add(self, name, build):
        """Make the card `name` with build(holder), in a holder of its own stacked under the cards before it."""
        holder = tk.Frame(self.parent, bg=self.parent.cget("bg"))
        holder.pack(fill="x")
        build(holder)
        self.made[name] = [build, holder]
        return holder

    def redo(self, name):
        """Make the card `name` again where it stands, the keyboard kept on the control it was on in it."""
        from opendmt3.client import widgets
        build, old = self.made[name]
        if not old.winfo_exists():
            return
        root = old.winfo_toplevel()
        # The page's scroll area, and where its view starts in pixels: kept, whatever the page's height does while
        # the new card is laid out (a region measured half way would pull the view up).
        area = next((a for a in _ancestors(self.parent) if isinstance(a, widgets.ScrollArea)), None)
        top = area.canvas.canvasy(0) if area is not None else None
        before = widgets.focus_order(old)
        focused = root.focus_get()
        index = before.index(focused) if focused in before else None
        # The page's main buttons made with the old card go with it (pages.main_button lists the new ones).
        self.app.main_buttons = [b for b in self.app.main_buttons if b.winfo_exists() and not _inside(b, old)]
        holder = tk.Frame(self.parent, bg=self.parent.cget("bg"))
        holder.pack(fill="x", after=old)
        build(holder)
        # The names' column the page has, counted again with the new card's rows, and with its group's names: the
        # column stays the one the page's group shares (group_names; the guide's steps have none).
        group = group_names(self.app.page) if self.app.guide is None else []
        widgets.fit_names(self.parent, self.app.ui, list(self.more) + group)
        old.destroy()
        self.made[name][1] = holder
        if area is not None:
            # Laid out first, so that the region is the new page's; then the view where it was, in pixels.
            root.update_idletasks()
            area._region()
            total = area.head_height + area.inner.winfo_reqheight()
            if total > 0:
                area.canvas.yview_moveto(top / total)
        if index is not None:
            # The rows before the changed one are the same, so the same place in the order is the same control.
            after = widgets.focus_order(holder)
            if index < len(after):
                after[index].focus_set()


def _ancestors(widget):
    """The widgets round `widget`, nearest first."""
    found, parent = [], widget.master
    while parent is not None:
        found.append(parent)
        parent = parent.master
    return found


def _inside(widget, box):
    """True when `widget` is `box` or under it."""
    while widget is not None:
        if widget is box:
            return True
        widget = widget.master
    return False


def main_button(app, parent, text, command, size="normal", fill=False):
    """A page's main action (Connect, Sign in, Add a player, the launcher's update) as a button: lit in its page's colour
    while PLAY is not, and quiet beside a lit PLAY, so that a screen has one lit main action, as OpenDMTQ's launcher has
    it. It follows PLAY as PLAY changes (app._paint_play); the guide's steps, which have no PLAY, light it."""
    from opendmt3.client import widgets
    lit = getattr(app, "play_button", None) is not None and app.play_button.winfo_exists() and app.play_lit()
    button = widgets.Button(parent, app.ui, text, command, kind="secondary" if lit else "primary", size=size, fill=fill)
    app.main_buttons.append(button)
    return button


def database_trouble(app, parent, error, bg=None):
    """Where this PC's players would be listed, when its database cannot be opened (damaged, or from a newer
    openDMT3): what is wrong, how to put its newest daily backup back (a damaged one; none helps with a newer one),
    and the button that opens its folder. The launcher goes on working."""
    from opendmt3.client import actions, theme, widgets
    ui, w = app.ui, app.words
    if app.checks is not None and not any(c.key == "database" for c in app.checks):
        # The page found what the ready check has not yet: the check is made again, and PLAY and the foot follow it
        # (the final review's B-05: PLAY stayed bright and the foot green under this line).
        app.refresh_checks()
    # On the card or the page it is said on.
    bg = bg or parent.cget("bg")
    widgets.label(parent, ui, w.error(error), fg=theme.BAD_INK, bg=bg, wrap_margin=0).pack(fill="x")
    if getattr(error, "key", None) != "error.host.db.newer":
        # A database from a newer openDMT3 is whole: its own line says what to do, and no backup is put back.
        widgets.label(parent, ui, w("db.broken.hint"), font=ui.fonts.small, fg=theme.MUTED, bg=bg,
                      wrap_margin=0).pack(fill="x", pady=(ui.px(6), 0))
    folder = os.path.dirname(app.host.path)
    widgets.Button(parent, ui, w("db.broken.open"), lambda: actions.open_folder(folder)).pack(
        anchor="w", pady=(ui.px(8), 0))
