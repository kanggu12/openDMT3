"""The launcher's building blocks, drawn to match its theme instead of the Windows defaults.

Tk's stock widgets look like 1990s Windows on a dark background, so the controls here are Labels and Canvases
with images from art.py. Each keeps its own images alive (Tk drops an image the moment Python forgets it).
"""

import tkinter as tk
from tkinter import ttk

from PIL import ImageTk

from opendmt3.client import art, i18n, theme


class Ui:
    """What every widget needs to draw itself: the root, the fonts, the DPI scale, the words, and the section the
    page on show belongs to (its colour lights the page's main buttons, switches and links)."""

    def __init__(self, root, fonts, scale, words):
        self.root = root
        self.fonts = fonts
        self.scale = scale
        self.words = words
        self.section_name = "technika"
        self.section = theme.SECTION_COLOURS["technika"]

    def px(self, n):
        """Logical pixels (at 100 % scaling) to real pixels on this screen."""
        return int(round(n * self.scale))

    def use_section(self, page):
        """Widgets made from now on take the colour of `page`'s section."""
        self.section_name = theme.PAGE_SECTIONS.get(page, "technika")
        self.section = theme.SECTION_COLOURS[self.section_name]


def style_ttk(ui):
    """Tk's themed widgets in the launcher's look: none is used any more (the drop-down is the launcher's own, Select),
    and 'clam' stays the theme so that any that comes honours colours on every platform."""
    ttk.Style(ui.root).theme_use("clam")


def thumb_span(height, first, last, least):
    """Where a scroll bar's thumb sits in a trough `height` pixels long, as (top, bottom): as long as the share of
    the content in view (`first` to `last`, two fractions), but never shorter than `least`, which is still easy to
    catch on a long page."""
    height = max(1, height)
    shown = min(1.0, max(0.0, last - first))
    length = min(height, max(least, shown * height))
    # The thumb travels the room left over while the view travels the part not shown.
    top = (height - length) * min(1.0, first / (1.0 - shown)) if shown < 1.0 else 0
    return top, top + length


def view_start(top, bottom, first, seen):
    """Where a view `seen` pixels tall that starts at `first` should start for the span `top`..`bottom` to be in
    it: unchanged when the span already is, otherwise moved the least that shows it (its top wins when the span is
    taller than the view)."""
    if bottom > first + seen:
        # Below the fold: far enough down for its end to show.
        first = bottom - seen
    # Above the view, or taller than it: its top comes first.
    return min(first, top)


class SlimBar(tk.Canvas):
    """The scroll area's bar: a thin thumb in a bare trough. No arrows: the wheel and the keys do the small steps,
    a press beside the thumb turns a page, a drag moves it."""

    def __init__(self, parent, ui, command, bg=theme.BG):
        # Wide enough to catch with a pointer; the thumb itself is drawn thinner inside.
        super().__init__(parent, width=ui.px(12), bg=bg, highlightthickness=0, bd=0)
        self.ui, self.command = ui, command
        # The part of the content in view, as two fractions of its height (what Tk's yscrollcommand reports).
        self.first, self.last = 0.0, 1.0
        # How far below the thumb's top the drag took hold (None outside a drag), and the pointer being over the bar.
        self.grip, self.over = None, False
        # The thumb's one rectangle once it is made (paint moves it), and the colour it was last given.
        self._thumb, self._thumb_colour = None, None
        self.bind("<Configure>", lambda e: self.paint())
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))

    def set(self, first, last):
        """What the scrolled canvas reports: where the view starts and ends."""
        self.first, self.last = float(first), float(last)
        self.paint()

    def thumb(self):
        """The thumb's top and bottom in pixels."""
        return thumb_span(self.winfo_height(), self.first, self.last, self.ui.px(32))

    def paint(self):
        """The thumb where the view is, in the look the pointer gives it: one rectangle, moved and recoloured.

        The bar paints at every scroll and at every change of the page's height (five times a page switch). Made anew
        each time, the old rectangle took its colour with it, and on X the new one asked the X server for that colour
        again: a round trip that waited for everything the page still had to draw (1.8 ms a paint at 200 % in the UI
        test's container)."""
        top, bottom = self.thumb()
        # Thin at rest, a little wider under the pointer or in the hand.
        held = self.grip is not None
        inset = self.ui.px(3 if held or self.over else 4)
        colour = theme.FAINT if held else theme.RAIL_UP if self.over else theme.RAIL
        box = (inset, top, self.winfo_width() - inset, bottom)
        if self._thumb is None:
            # The first paint makes the rectangle; every later one moves it.
            self._thumb = self.create_rectangle(*box, fill=colour, outline="")
        else:
            self.coords(self._thumb, *box)
            if colour != self._thumb_colour:
                # A new look only under the pointer, in the hand, or back at rest.
                self.itemconfigure(self._thumb, fill=colour)
        self._thumb_colour = colour

    def _hover(self, over):
        self.over = over
        self.paint()

    def _press(self, event):
        top, bottom = self.thumb()
        if top <= event.y <= bottom:
            # On the thumb: the drag keeps this point of it under the pointer.
            self.grip = event.y - top
            self.paint()
        else:
            # Beside it: one page towards the press.
            self.command("scroll", -1 if event.y < top else 1, "pages")

    def _drag(self, event):
        if self.grip is None:
            return
        top, bottom = self.thumb()
        room = self.winfo_height() - (bottom - top)
        if room > 0:
            # The thumb's place in its room is the view's place in the part not shown.
            place = min(1.0, max(0.0, (event.y - self.grip) / room))
            self.command("moveto", place * (1.0 - (self.last - self.first)))

    def _release(self, event):
        self.grip = None
        self.paint()


class Rail(tk.Frame):
    """The column down the window's left side, as OpenDMTQ's launcher has it: openDMT3's lockup with LAUNCHER and the
    version (art.brand, the site bar's DMT3 SERVER in the launcher's words) at its top, then the menu (`nav`: the pages, one under another) or the first-start guide's steps
    (`steps`), and at its foot what the window places there (the status and PLAY, or the guide's Skip, Back and Next,
    LauncherApp.make_foot). Opaque, a step darker than the page, with a seam along its right edge where the page begins.

    The names keep their font at every window height; when the column is short (a small window, a status line that
    wraps to several lines over PLAY), the names stand closer together instead (fit), so the menu never runs under
    its foot."""

    # The column's width, the room inside it either side, above the lockup, and under it (logical pixels). The width
    # holds the lockup (art.BRAND_WIDTH) with the room either side, and PLAY's slab as wide as the column holds.
    WIDTH, EDGE, TOP, UNDER_BRAND = 248, 18, 22, 24
    # The least room between the menu's last name and the foot's top (logical pixels).
    ABOVE_FOOT = 16

    def __init__(self, parent, ui, brand, nav=(), on_nav=None, steps=()):
        px = ui.px
        # The column's own colour, a step darker than the page (theme.BAR).
        super().__init__(parent, bg=theme.BAR, width=px(self.WIDTH))
        self.ui = ui
        # Its own width whatever it holds (the brand and the list never widen it).
        self.pack_propagate(False)
        # The seam along its right edge: the page's field starts after it.
        tk.Frame(self, bg=theme.LINE, width=max(1, px(1))).pack(side="right", fill="y")
        image = ImageTk.PhotoImage(brand, master=self)
        # No room of its own round the picture (Tk's pixel either side): the column's rooms alone place it.
        self.brand = tk.Label(self, image=image, bg=theme.BAR, bd=0, padx=0, pady=0)
        # Kept on the label: Tk drops a picture the moment Python forgets it. A dialog draws the window from it.
        self.brand.image, self.brand.opendmt3_picture = image, brand
        self.brand.pack(side="top", anchor="w", padx=(px(self.EDGE), 0), pady=(px(self.TOP), px(self.UNDER_BRAND)))
        # The menu or the guide's steps under the mark.
        self.list = RailList(self, ui, nav=nav, on_nav=on_nav, steps=steps)
        self.list.pack(side="top", fill="x")
        # The foot the window places over the column's foot (set by LauncherApp.make_foot), measured by fit.
        self.foot = None
        # The column's height changes with the window's: the names find their room again.
        self.bind("<Configure>", lambda e: self.fit(), add="+")

    def inner_width(self):
        """The width of what the column holds between its rooms either side (the foot's buttons, PLAY's slab)."""
        return self.ui.px(self.WIDTH) - 2 * self.ui.px(self.EDGE) - max(1, self.ui.px(1))

    def set_foot(self, foot):
        """The foot placed over the column: its height (a status line that wraps, Next turning into PLAY) leaves the
        menu its room."""
        self.foot = foot
        foot.bind("<Configure>", lambda e: self.fit(), add="+")
        self.fit()

    def fit(self):
        """The menu's rows as tall as the room between the mark and the foot allows, up to their full height."""
        if not self.winfo_exists():
            return
        px = self.ui.px
        height = self.winfo_height()
        if height <= 1:
            # Not laid out yet: the first <Configure> comes back here.
            return
        # The list's top: under the mark and its room.
        top = self.brand.winfo_reqheight() + px(self.TOP) + px(self.UNDER_BRAND)
        # The foot's top, from the column's foot: its height and the room under it (placed by make_foot).
        foot = 0
        if self.foot is not None and self.foot.winfo_exists():
            foot = self.foot.winfo_reqheight() + getattr(self.foot, "opendmt3_under", 0)
        self.list.fit(height - top - foot - px(self.ABOVE_FOOT))

    def set_current(self, key):
        """The page on show, lit in the menu."""
        self.list.set_current(key)

    def set_step(self, index):
        """The guide's step on show."""
        self.list.set_step(index)


class RailList(tk.Canvas):
    """The column's list: the menu's pages, or the guide's steps, one under another.

    The menu: each page's name in the wide face, in English in both languages (as both sites' menus and the game's
    are); grey, white under the pointer on a quiet slab; the page on show white on a raised slab of the cards' colour,
    its top-right corner cut as the cards' are, with a rule along its left edge in its section's colour (TECHNIKA 3's
    blue for PLAY, STAR MIXING's lime for the cabinet's settings, POP MIXING's pink for playing online, amber for the
    tools). The keyboard reaches it first, as OpenDMTQ's: Tab brings a cyan ring to the page on show, the arrow keys
    and Tab move it along the names, Enter or Space opens the page with the ring, and Tab past the last name (or
    Shift+Tab before the first) goes on to the page.

    The guide's steps: each step's number upright in the wide face, its name beside it; the step on show on the
    raised slab with the guide's blue rule, the numbers of the steps taken and on show in the guide's blue, the steps
    to come grey. They take no keyboard (Back and Next move along them)."""

    # A name's full height and the least it shrinks to in a short column, the gap between two, the room before a name
    # inside its slab, the slab's cut corner and its rule, and a step's full and least height (logical pixels).
    ITEM_H, ITEM_LEAST, ITEM_GAP, NAME_PAD, CUT, RULE, STEP_H, STEP_LEAST = 42, 30, 4, 16, 10, 3, 50, 36
    # The room a step's number takes before its name (the names stand in one column whatever each number's width).
    NUMBER_W = 34

    def __init__(self, parent, ui, nav=(), on_nav=None, steps=()):
        self.ui = ui
        self.nav, self.on_nav, self.steps = list(nav), on_nav, list(steps)
        # Each row's height now: the full height until the column says it is short (fit).
        self.row = ui.px(self.ITEM_H) if self.nav else ui.px(self.STEP_H)
        # The keyboard reaches the list only when it is the menu (the guide's steps take none).
        super().__init__(parent, height=self._height(), bg=theme.BAR, highlightthickness=0, bd=0,
                         takefocus=1 if self.nav else 0)
        # The page on show, the name under the pointer, the name with the keyboard's ring, the guide's step on show.
        self.current, self.hover, self.ring, self.step = None, None, None, 0
        # Each entry's box (x0, y0, x1, y1) once drawn: the pointer, the ring and the tests find the entries by it.
        self.boxes = {}
        # A drawing waiting for a resize to settle.
        self._job = None
        self.bind("<Configure>", lambda e: self._queue())
        if self.nav:
            for key, move in (("<Tab>", 1), ("<Shift-Tab>", -1), ("<ISO_Left_Tab>", -1), ("<Down>", 1), ("<Up>", -1)):
                self.bind(key, lambda e, m=move, k=key: self._move(m, k))
            for key in ("<Return>", "<KP_Enter>", "<space>"):
                self.bind(key, lambda e: self._press(self.ring))
            self.bind("<FocusIn>", lambda e: self._focused(True))
            self.bind("<FocusOut>", lambda e: self._focused(False))
            # The pointer is followed over the whole list (the gaps between names too), so the slab under it shows.
            self.bind("<Motion>", lambda e: self._hover(self._at(e.y)))
            self.bind("<Leave>", lambda e: self._hover(None))
            self.bind("<Button-1>", lambda e: self._press(self._at(e.y)))

    def _count(self):
        return len(self.nav) or len(self.steps)

    def _height(self):
        """The list's height at its rows' height now."""
        count = self._count()
        return count * self.row + max(0, count - 1) * self.ui.px(self.ITEM_GAP)

    def fit(self, room):
        """Rows as tall as `room` (pixels) holds for all of them, between their least and full heights."""
        px, count = self.ui.px, self._count()
        if not count:
            return
        full, least = (px(self.ITEM_H), px(self.ITEM_LEAST)) if self.nav else (px(self.STEP_H), px(self.STEP_LEAST))
        row = max(least, min(full, (room - (count - 1) * px(self.ITEM_GAP)) // count))
        if row != self.row:
            self.row = row
            # The new height brings a <Configure>, which draws the list again.
            self.configure(height=self._height())

    def _queue(self):
        """Draw again once the size settles (a drag fires many resize events)."""
        if self._job is not None:
            self.after_cancel(self._job)
        self._job = self.after(10, self.draw)

    def _entries(self):
        return [key for key, _ in self.nav]

    def _at(self, y):
        """The entry whose box holds height `y`, or None (the gap between two)."""
        for key, (_x0, y0, _x1, y1) in self.boxes.items():
            if y0 <= y < y1:
                return key
        return None

    def draw(self):
        """The list's picture (the column's colour, the slab under the entry on show and the one under the pointer)
        and its words over it as Tk's own text (as crisp as every label)."""
        from PIL import Image, ImageDraw
        self._job = None
        if not self.winfo_exists():
            return
        px = self.ui.px
        width, height = max(1, self.winfo_width()), max(1, self.winfo_height())
        self.delete("all")
        # The slabs reach a little past the column's room either side, so the names line up with the mark above.
        left, right = px(Rail.EDGE) - px(6), width - px(Rail.EDGE) + px(6)
        picture = Image.new("RGB", (width, height), art._rgb(theme.BAR))
        draw = ImageDraw.Draw(picture)
        keys = self._entries() if self.nav else list(range(len(self.steps)))
        lit = self.current if self.nav else self.step
        self.boxes = {}
        for i, key in enumerate(keys):
            top = i * (self.row + px(self.ITEM_GAP))
            self.boxes[key] = (left, top, right, top + self.row)
            if (key == lit or (self.nav and key == self.hover)) and right - left > px(self.CUT) and self.row > 0:
                # The slab: the cards' colour under the entry on show, a quieter one under the pointer, its top-right
                # corner cut as the cards' are (once the list has its width: before, there is nothing to draw on).
                cut, bottom = px(self.CUT), top + self.row - 1
                fill = theme.PANEL if key == lit else theme.NAV_HOVER
                draw.rectangle([left, top, right - 1, bottom], fill=art._rgb(fill))
                # The cut as the cards' (art.cut_masks): the column's colour beyond it, the diagonal smooth.
                beyond, _seam = art.cut_masks(cut)
                picture.paste(art._rgb(theme.BAR), (right - cut, top), beyond)
                if key == lit:
                    # The rule along its left edge, where the window is: the page's section's colour, the guide's blue.
                    colour = theme.section_colours(key)["accent"] if self.nav else theme.BLUE_HI
                    draw.rectangle([left, top, left + px(self.RULE) - 1, bottom], fill=art._rgb(colour))
        # The numbers' pictures, kept while they show (Tk drops a picture the moment Python forgets it).
        self._numerals = []
        if self.nav:
            for key, words in self.nav:
                x0, y0, _x1, y1 = self.boxes[key]
                self.create_text(x0 + px(self.NAME_PAD), (y0 + y1) // 2, text=words, font=self.ui.fonts.nav,
                                 anchor="w", tags=("name", "n-" + key))
        else:
            for i, name in enumerate(self.steps):
                x0, y0, _x1, y1 = self.boxes[i]
                done, now = i < self.step, i == self.step
                # Taken and on show in the guide's blue, to come in grey.
                numeral = art.numeral(str(i + 1), theme.BLUE_HI if (done or now) else theme.STEP_TO_COME,
                                      self.ui.scale, size=24)
                nx, ny = x0 + px(self.NAME_PAD), (y0 + y1 - numeral.height) // 2
                # On the list's own picture: crisp, and in a dialog's view of the window too (snapshot.py).
                picture.paste(numeral, (nx, ny), numeral)
                self.create_text(nx + px(self.NUMBER_W), (y0 + y1) // 2, text=name, anchor="w",
                                 font=self.ui.fonts.step, tags=("step",),
                                 fill=theme.TEXT if now else (theme.MUTED if done else theme.FAINT))
        self._picture = picture
        self._image = ImageTk.PhotoImage(picture, master=self)
        # A dialog draws the window from the widgets (snapshot.py): the list as it looks now.
        self.opendmt3_picture = picture
        # Under the words.
        self.tag_lower(self.create_image(0, 0, image=self._image, anchor="nw"))
        self._paint()

    def _paint(self):
        """Each name's colour and the keyboard's ring."""
        px = self.ui.px
        self.delete("ring")
        for key, _words in self.nav:
            self.itemconfigure("n-" + key, fill=theme.TEXT if key in (self.current, self.hover) else theme.MUTED)
        if self.ring in self.boxes:
            x0, y0, x1, y1 = self.boxes[self.ring]
            thick = max(1, px(2))
            # Inside the entry's box, so it never runs over the next name.
            self.create_rectangle(x0 + thick // 2, y0 + thick // 2, x1 - (thick + 1) // 2, y1 - (thick + 1) // 2,
                                  outline=theme.CYAN, width=thick, tags=("ring",))

    def _hover(self, key):
        if key != self.hover:
            self.hover = key
            # The hand over a name, the arrow over the gaps.
            self.configure(cursor="hand2" if key else "")
            # The slab under the pointer is part of the picture.
            self.draw()

    def _press(self, key):
        if key is not None and self.on_nav:
            self.on_nav(key)

    def _focused(self, on):
        """The keyboard came: the ring on the page on show (or the first name); it went: the ring goes."""
        entries = self._entries()
        if on and entries:
            if self.ring not in entries:
                self.ring = self.current if self.current in entries else entries[0]
        else:
            self.ring = None
        self._paint()

    def _move(self, by, key):
        """The ring along the names; Tab past the last (Shift+Tab before the first) leaves the list, as Tab does."""
        entries = self._entries()
        if not entries or self.ring not in entries:
            return None
        i = entries.index(self.ring) + by
        if 0 <= i < len(entries):
            self.ring = entries[i]
            self._paint()
            return "break"
        if key in ("<Up>", "<Down>"):
            # The arrows stay on the list at its ends.
            return "break"
        return None

    def set_current(self, key):
        """The page on show: its name lit on its slab."""
        if key != self.current:
            self.current = key
            self.draw()

    def set_step(self, index):
        """The guide's step on show."""
        self.step = index
        self.draw()


class _PageCanvas(tk.Canvas):
    """The scroll area's canvas, which hands a dialog (snapshot.py) the part of the page's head in view: the head is a
    picture on the canvas that scrolls with the page, so the part shown changes as the page moves."""

    @property
    def opendmt3_picture(self):
        from PIL import Image
        head = getattr(self, "head_picture", None)
        if head is None:
            return None
        width, height = max(1, self.winfo_width()), max(1, self.winfo_height())
        picture = Image.new("RGB", (width, height), art._rgb(theme.BG))
        # The head where it is now: as far up as the page has been scrolled.
        picture.paste(head, (0, -int(self.canvasy(0))))
        return picture


class ScrollArea(tk.Frame):
    """The page area, as a page of the site under its bar: the page's head (its title over the section's shards, a
    picture the window draws, set_head) and the page's cards under it (`inner`) scroll together with the mouse wheel."""

    def __init__(self, parent, ui, bg=theme.BG):
        super().__init__(parent, bg=bg)
        self.ui = ui
        self.canvas = _PageCanvas(self, bg=bg, highlightthickness=0, bd=0)
        self.bar = SlimBar(self, ui, self.canvas.yview, bg=bg)
        self.inner = tk.Frame(self.canvas, bg=bg)
        # The head's height (0 until the window sets one), and its items on the canvas: the picture and the line of
        # words under the title.
        self.head_height, self._head_item, self._sub_item = 0, None, None
        self.canvas.head_picture = None
        # What the window does when the area changes width (the head is drawn again for it), and the width it was last
        # told of (None before the first).
        self.on_width = None
        self._told_width = None
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self._bar_set)
        self.canvas.pack(side="left", fill="both", expand=True)
        # The content's height decides how far it scrolls.
        self.inner.bind("<Configure>", lambda e: self._region())
        # The content is always as wide as the visible area, so text wraps instead of running off.
        self.canvas.bind("<Configure>", self._on_resize)
        # The wheel scrolls whatever is under the pointer, so bind only while the pointer is over this area.
        self.bind("<Enter>", lambda e: self._wheel(True))
        self.bind("<Leave>", lambda e: self._wheel(False))

    def set_head(self, picture, sub="", sub_at=(0, 0), sub_width=0):
        """The page's head: `picture` (PIL, as wide as the area) at the page's top, and `sub`, the line of words under
        the title, at `sub_at` on it wrapping at `sub_width`; the cards start under the picture."""
        c = self.canvas
        c.head_picture = picture
        self._head_image = ImageTk.PhotoImage(picture, master=c)
        if self._head_item is None:
            self._head_item = c.create_image(0, 0, image=self._head_image, anchor="nw")
            self._sub_item = c.create_text(0, 0, text="", font=self.ui.fonts.body, fill=theme.MUTED, anchor="nw")
        else:
            c.itemconfigure(self._head_item, image=self._head_image)
        c.coords(self._sub_item, *sub_at)
        c.itemconfigure(self._sub_item, text=sub, width=max(1, sub_width))
        # The picture under the page's other items, whatever was made first.
        c.tag_lower(self._head_item)
        if picture.height != self.head_height:
            self.head_height = picture.height
            c.coords(self._window, 0, self.head_height)
        self._region()

    def _region(self):
        """How far the page scrolls: the head and the cards under it, as wide as the area."""
        width = max(1, self.canvas.winfo_width())
        self.canvas.configure(scrollregion=(0, 0, width, self.head_height + self.inner.winfo_reqheight()))

    def _bar_set(self, first, last):
        """Show the scroll bar only when the content is taller than the area.

        The bar lies over the area's right edge, in the page's own margin where no card reaches (place), so its coming
        and going leaves the page as wide as it was. Packed beside the page it took its 12 pixels from the page, and
        the page was laid out again at each turn: PLAY at 960 pixels wide in English, within a line of the window's
        height, came out a line taller without the bar and a line shorter with it (its two columns are sized from what
        their labels asked for one layout before, and those follow the columns), so the bar came and went for good and
        the window never finished drawing: on CI's runners of a few cores, and in most runs of a container held to
        one core; on a fast PC almost never."""
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.bar.place_forget()
        elif not self.bar.winfo_ismapped():
            # At the right edge, the area's whole height, over the page: the bar was made after the canvas, so it
            # stands above it (a Canvas's own lift() raises its drawn items, not the widget).
            self.bar.place(relx=1.0, y=0, relheight=1.0, anchor="ne")
        self.bar.set(first, last)

    def _on_resize(self, event):
        # The content is exactly as wide as the visible area; labels wrap to their own box (follow_width). The content
        # frame's new width sets the scrolled region again (its own <Configure>).
        self.canvas.itemconfigure(self._window, width=event.width)
        if self.on_width is not None and event.width != self._told_width:
            # The head is drawn again for a new width (the window waits for a drag to settle). A window made only
            # taller or shorter keeps its head: the head is as wide as the area, and its height is its words'.
            self._told_width = event.width
            self.on_width(event.width)

    def _wheel(self, on):
        if on:
            self.bind_all("<MouseWheel>", self._on_wheel)          # Windows and macOS
            self.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))   # X11 wheel up
            self.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))    # X11 wheel down
        else:
            self.unbind_all("<MouseWheel>")
            self.unbind_all("<Button-4>")
            self.unbind_all("<Button-5>")

    def _on_wheel(self, event):
        # Windows reports 120 per notch.
        self.canvas.yview_scroll(int(-event.delta / 40), "units")

    def to_top(self):
        self.canvas.yview_moveto(0)

    def show(self, widget, margin=0):
        """Scroll the least that brings `widget` (somewhere inside `inner`) into view, with `margin` pixels of air."""
        # The sizes below are the ones after whatever was just packed is laid out.
        self.update_idletasks()
        # The whole page: the head and the cards under it.
        total = self.head_height + self.inner.winfo_height()
        seen = self.canvas.winfo_height()
        if total <= seen:
            # Everything shows already.
            return
        # The widget's top on the page: its place among the cards, under the head.
        top = self.head_height + widget.winfo_rooty() - self.inner.winfo_rooty()
        first = self.canvas.canvasy(0)
        start = view_start(top - margin, top + widget.winfo_height() + margin, first, seen)
        if start != first:
            self.canvas.yview_moveto(max(0, start) / total)

    def keep_place(self, rebuild):
        """The page drawn again by `rebuild()` (a choice that adds or removes rows, an answer that came), kept where it
        was scrolled to and with the keyboard on the control it was on, as OpenDMTQ's pages do: a choice at a page's
        foot does not throw the page back to its top."""
        top = self.canvas.yview()[0]
        root = self.winfo_toplevel()
        before = focus_order(self.inner)
        focused = root.focus_get()
        index = before.index(focused) if focused in before else None
        rebuild()
        # Laid out first, so that the scroll's place is measured on the new page's height.
        root.update_idletasks()
        self._region()
        self.canvas.yview_moveto(top)
        if index is not None:
            # The rows before the changed one are the same, so the same place in the order is the same control.
            after = focus_order(self.inner)
            if index < len(after):
                after[index].focus_set()


def focus_order(widget):
    """The widgets under `widget` that take the keyboard, in the order Tab visits them (the page's packing order)."""
    found = []
    for child in widget.winfo_children():
        # A widget that takes the keyboard (a switch, a row of choices, a button) is one stop; what is inside it is not.
        try:
            takes = str(child.cget("takefocus"))
        except tk.TclError:
            takes = ""
        if takes not in ("", "0"):
            found.append(child)
        else:
            found.extend(focus_order(child))
    return found


# A wrapping label's width before its box is laid out (follow_width).
START_WRAP = 120
# The pixels of new room a wrapping label lets go by before it takes them (follow_width): the odd pixel two boxes
# side by side hand to each other.
WRAP_SLACK = 2


def wrap_width(room, now, slack=WRAP_SLACK):
    """The width a label wraps at when its box has `room` pixels for its words and it wraps at `now`.

    Less room is taken at once (the words must fit); more room only when it is more than `slack` pixels. Two boxes
    side by side share their row in whole pixels, and the odd pixel goes to one or the other by what each asks for:
    a label that took that pixel asked for another width, the row handed the pixel to the other box, the label gave
    it back, and so on. The window never finished drawing (PLAY at 1600x1000, in English)."""
    return room if room < now or room > now + slack else now


def follow_width(ui, widget, margin=0, beside=()):
    """Keep a label's wrap width equal to its box's width, less the widgets beside it on the same line.

    The box (the label's master) gets its width from the page above it, never from the label, so the wrap
    width settles in one pass whatever the window size; the one pixel a row of two boxes hands back and forth is
    let go by (wrap_width).
    """
    master = widget.master

    def inner_padding(w):
        """The room a frame keeps inside its edge (its own padx and border) on both sides."""
        total = 0
        for option in ("padx", "bd", "highlightthickness"):
            try:
                # Tk returns screen distances as objects; winfo_pixels turns any of them into pixels.
                total += w.winfo_pixels(str(w.cget(option)))
            except tk.TclError:
                # Not every widget has every option (a Canvas has no padx).
                pass
        return 2 * total

    def own_padding(w):
        """The space the label's own pack or grid padding takes on both sides."""
        try:
            info = w.pack_info() if w.winfo_manager() == "pack" else w.grid_info()
        except tk.TclError:
            return 0
        pad = info.get("padx", 0)
        if isinstance(pad, (tuple, list)):
            # (left, right), as given to pack or grid.
            return sum(w.winfo_pixels(str(p)) for p in pad)
        return 2 * w.winfo_pixels(str(pad))

    def update(event=None):
        width = master.winfo_width()
        if width <= 1 or not widget.winfo_exists():
            return
        taken = sum(b.winfo_reqwidth() for b in beside if b.winfo_exists())
        # The label's own border and padding come off too: its text has that much less room than its box.
        room = (width - inner_padding(master) - inner_padding(widget) - own_padding(widget) - taken
                - ui.px(margin))
        room = max(ui.px(120), room)
        # What the label wraps at now, in pixels (Tk hands a screen distance back as it was given).
        now = widget.winfo_pixels(str(widget.cget("wraplength")))
        wrap = wrap_width(room, now)
        # Told its real room at least once (the UI run checks every wrapping label was).
        widget.opendmt3_wrap_set = True
        if wrap != now:
            # Only a real change: setting the same width again would still ask the box to lay itself out.
            widget.configure(wraplength=wrap)

    # Start narrow: a label that first asks for its whole line would widen its box, and the box's width would
    # then come from the label instead of the page. Narrow first, the box takes the page's width, then the
    # label grows into it.
    widget.configure(wraplength=ui.px(START_WRAP))
    widget.opendmt3_wrap_set = False
    master.bind("<Configure>", update, add="+")
    widget.after_idle(update)


def label(parent, ui, text, font=None, fg=theme.TEXT, bg=None, wrap_margin=None, beside=(), **kw):
    """A text label in the theme, on its parent's colour unless told (a card's or the page's); with wrap_margin it
    wraps at its box's width minus that margin."""
    bg = bg or parent.cget("bg")
    w = tk.Label(parent, text=text, font=font or ui.fonts.body, fg=fg, bg=bg, justify="left", anchor="w", **kw)
    if wrap_margin is not None:
        follow_width(ui, w, wrap_margin, beside)
    return w


def section(parent, ui, text, bg=None):
    """A heading inside a card (the weeks of the Records page) as the game names a part of its screen (NO CREW on the
    song select): white words on a dark leaning plate (art.name_plate), on its parent's colour unless told."""
    bg = bg or parent.cget("bg")
    row = tk.Frame(parent, bg=bg)
    # A name in English capitals in both languages, as a card's (THEME.md).
    words = i18n.english_of(text).upper()
    # Black on a card, as the game's plates sit on its bright bars; a step lighter than the page on the page itself,
    # where black would not show.
    picture = art.name_plate(words, ui.scale, fill=theme.INK if bg == theme.PANEL else theme.PANEL_HI)
    image = ImageTk.PhotoImage(picture, master=row)
    plate = tk.Label(row, image=image, bg=bg, bd=0)
    # Kept on the label: Tk shows a picture only while Python holds it. The words ride along for the tests.
    plate.image, plate.words, plate.opendmt3_picture = image, words, picture
    plate.pack(side="left")
    return row


class Button(tk.Canvas):
    """A button that leans like PLAY and the game's plates. kind: 'primary' (filled with the section's colour, the
    page's main action), 'secondary' (quiet metal that lights up under the pointer), 'danger' (metal tinted pink,
    filled pink under the pointer: removing or putting back).

    The face is a picture (art.button_face); the words stay Tk text, drawn as crisply as every other label.
    """

    LOOKS = {"secondary": "neutral", "danger": "danger_quiet"}
    # Its height (logical pixels): a page's buttons (as tall as a page's fields, Field "md"), the smaller ones a card
    # has at its title's right end (Check again), which stand in the title tab's row as the site's small buttons stand
    # in a table's, and the sign-in's key, as tall as the sign-in's fields (Field "lg": the site's 48 px door at the
    # launcher's scale, as its 42 px page controls are the launcher's 34).
    HEIGHTS = {"normal": 34, "small": 26, "lg": 40}

    def __init__(self, parent, ui, text, command, kind="secondary", size="normal", fill=False):
        self.ui, self.bg, self.size = ui, parent.cget("bg"), size
        # `fill`: as wide as its box gives it (the sign-in's key across its form), its face drawn again for the width.
        self.fill, self._drawn_width = fill, None
        # The section the page belongs to, taken now: a main button keeps its page's colour.
        self.section_name = ui.section_name
        super().__init__(parent, bg=self.bg, highlightthickness=0, bd=0, cursor="hand2", takefocus=1)
        self.command, self.enabled, self.words, self.state = command, True, None, "normal"
        # The keyboard: Tab brings the focus (a ring inside the edge), Enter or Space presses.
        self.focused = False
        self.bind("<FocusIn>", lambda e: self._focus(True))
        self.bind("<FocusOut>", lambda e: self._focus(False))
        for key in ("<Return>", "<KP_Enter>", "<space>"):
            self.bind(key, lambda e: self.press())
        self._take_look(kind)
        self.set_text(text)
        self.bind("<Enter>", lambda e: self._paint("hover" if self.enabled else "disabled"))
        self.bind("<Leave>", lambda e: self._paint("normal" if self.enabled else "disabled"))
        self.bind("<ButtonPress-1>", lambda e: self.enabled and self._paint("pressed"))
        self.bind("<ButtonRelease-1>", self._click)
        if fill:
            self.bind("<Configure>", lambda e: self._fill(e.width), add="+")

    def _fill(self, width):
        """As wide as its box: the faces drawn again at the new width (the words stay in its middle)."""
        if width > 1 and width != self._drawn_width:
            words, self.words = self.words, None
            self.set_text(words, width)

    def _take_look(self, kind):
        """The kind's look (a main button in its page's section's colour) and its words' colour in each state."""
        self.kind = kind
        self.look = art.SECTION_LOOKS[self.section_name] if kind == "primary" else self.LOOKS[kind]
        colours = art.BUTTON_LOOKS[self.look]
        self.text_colour = {"normal": colours["text"], "hover": colours.get("hover_text", colours["text"]),
                            "pressed": colours.get("hover_text", colours["text"]), "disabled": theme.FAINT}

    def set_kind(self, kind):
        """Another kind (a page's main action lit while PLAY waits, quiet beside a lit PLAY), its faces drawn again."""
        if kind == self.kind:
            return
        self._take_look(kind)
        # Drawn again for the same words: set_text draws only for words it does not show yet.
        words, self.words = self.words, None
        self.set_text(words)

    def set_text(self, text, width=None):
        """Show other words (the guide's last Next becomes PLAY): the button takes the width they need (or `width`,
        when it fills its box)."""
        if text == self.words:
            return
        self.words = text
        fonts, px = self.ui.fonts, self.ui.px
        height = px(self.HEIGHTS[self.size])
        font = fonts.button_lg if self.size == "lg" else fonts.body_bold
        # The ends lean, so the words keep their distance from the slope, not from the box: half the lean more.
        side = px(14 if self.size in ("normal", "lg") else 10) + int(height * art.LEAN) // 2
        need = font.measure(text) + 2 * side
        if width is None and self.fill and self._drawn_width:
            width = self._drawn_width
        width = max(need, width or 0)
        self._drawn_width = width if self.fill else None
        if self.fill:
            # Its own width stays the words' need: the box it fills gives it the rest.
            tk.Canvas.configure(self, width=need, height=height)
        else:
            self.configure(width=width, height=height)
        self.delete("all")
        self.faces = {state: art.button_face((width, height), 0, self.look, state, False, self.ui.scale, bg=self.bg)
                      for state in ("normal", "hover", "pressed", "disabled")}
        self.images = {state: ImageTk.PhotoImage(face, master=self) for state, face in self.faces.items()}
        # The faces with the focus ring are made the first time the button gets the focus.
        self.focused_faces, self.focused_images = None, None
        self.face = self.create_image(0, 0, image=self.images["normal"], anchor="nw")
        self.label = self.create_text(width // 2, height // 2, text=text, font=font, anchor="center")
        self._paint(self.state if self.enabled else "disabled")

    def _focus(self, on):
        self.focused = on
        if on and self.focused_faces is None:
            # The width it is drawn at: its words' need, or its box's when it fills one.
            width, height = self._drawn_width or int(self.cget("width")), int(self.cget("height"))
            self.focused_faces = {state: art.button_face((width, height), 0, self.look, state, True, self.ui.scale,
                                                         bg=self.bg) for state in self.faces}
            self.focused_images = {state: ImageTk.PhotoImage(face, master=self)
                                   for state, face in self.focused_faces.items()}
        self._paint(self.state)

    def _paint(self, state):
        self.state = state
        faces, images = ((self.focused_faces, self.focused_images) if self.focused and self.focused_faces
                         else (self.faces, self.images))
        self.itemconfigure(self.face, image=images[state])
        self.itemconfigure(self.label, fill=self.text_colour[state])
        # A dialog draws the window behind it from the widgets (snapshot.py): this is the button's part.
        self.opendmt3_picture = faces[state]

    def _click(self, event):
        # Only a release over the button counts, like a real button (drag off to cancel).
        inside = 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
        if not self.enabled:
            return
        self._paint("hover" if inside else "normal")
        if inside and self.command:
            self.command()

    def press(self):
        """What a click does, for the keyboard and the tests. The key's words are kept while its action runs, so a
        failure nobody caught names the action it stopped (LauncherApp.report_callback_exception)."""
        if self.enabled and self.command:
            self.ui.last_action = self.words
            self.command()

    def enable(self, on):
        self.enabled = on
        self.configure(cursor="hand2" if on else "arrow")
        self._paint("normal" if on else "disabled")

    # How long each of the busy stripes' pictures shows (ms): one period in 0.7 s, as the site's.
    BUSY_STEP = 88

    def busy(self, on):
        """At work (FORMS.md's busy key): its words stay, the game's moving stripes run over its face, the pointer
        waits, and it cannot be pressed until the answer comes; off, it is itself again."""
        self.busy_now = bool(on)
        if on:
            self.enabled = False
            self.configure(cursor="watch")
            width = self._drawn_width or int(self.cget("width"))
            face = self.faces["normal"]
            if face.size[0] != width:
                face = face.resize((width, face.size[1]))
            self._busy_frames = [ImageTk.PhotoImage(frame, master=self) for frame in art.busy_frames(face, self.ui.scale)]
            self._busy_step(0)
        else:
            job = getattr(self, "_busy_job", None)
            if job is not None:
                self.after_cancel(job)
                self._busy_job = None
            self.enable(True)

    def _busy_step(self, i):
        if not getattr(self, "busy_now", False) or not self.winfo_exists():
            return
        frame = self._busy_frames[i % len(self._busy_frames)]
        self.itemconfigure(self.face, image=frame)
        self.itemconfigure(self.label, fill=self.text_colour["normal"])
        self._busy_job = self.after(self.BUSY_STEP, lambda: self._busy_step(i + 1))


class Toggle(tk.Label):
    """A switch (FORMS.md, art.switch): on or off at once, round (only switches, lamps and badges are); off, the slot
    with the knob in the ash's grey, on, the track in the page's section's colour with the knob in its ink; its edge
    lighter under the pointer, the keyboard's cyan ring two pixels out once Tab has reached it; Space or Enter flips
    it. On its parent's colour unless told; command(new_value) runs after each change."""

    def __init__(self, parent, ui, value, command, bg=None):
        bg = bg or parent.cget("bg")
        super().__init__(parent, bg=bg, cursor="hand2", bd=0, takefocus=1, highlightthickness=0)
        self.ui, self.value, self.command = ui, bool(value), command
        self.colours = ui.section
        # Where the track's visible edge starts inside the picture (the ring's room): setting rows line it up.
        self.opendmt3_inset = ui.px(art.TICK_RING_ROOM)
        self.over, self.focused, self.enabled = False, False, True
        self.pictures = {}
        self.bind("<Button-1>", lambda e: self.enabled and self.set(not self.value, notify=True))
        for key in ("<space>", "<Return>", "<KP_Enter>"):
            self.bind(key, lambda e: self.enabled and self.set(not self.value, notify=True))
        self.bind("<Enter>", lambda e: self._paint(over=True))
        self.bind("<Leave>", lambda e: self._paint(over=False))
        self.bind("<FocusIn>", lambda e: self._paint(focused=True))
        self.bind("<FocusOut>", lambda e: self._paint(focused=False))
        self._paint()

    def _paint(self, over=None, focused=None):
        if over is not None:
            self.over = over
        if focused is not None:
            self.focused = focused
        state = "disabled" if not self.enabled else ("hover" if self.over else "normal")
        look = (self.value, state, self.focused)
        if look not in self.pictures:
            picture = art.switch(self.value, state, self.ui.scale, self.colours, self.focused)
            self.pictures[look] = (picture, ImageTk.PhotoImage(picture, master=self))
        # A dialog draws the window behind it from the widgets (snapshot.py): this is the switch's part.
        self.opendmt3_picture, image = self.pictures[look]
        self.configure(image=image)

    def set(self, value, notify=False):
        self.value = bool(value)
        self._paint()
        if notify:
            self.command(self.value)

    def enable(self, on):
        self.enabled = bool(on)
        self.configure(cursor="hand2" if on else "arrow", takefocus=1 if on else 0)
        self._paint()


class Tick(tk.Frame):
    """A line with a tick box (FORMS.md, art.tick_box): the box, then its words in the text's own size and ink;
    ticked in the page's section's colour with the tick in its ink; the box's edge lighter under the pointer; the
    keyboard's cyan ring round the box once Tab has reached it; Space or Enter, or a click on the box or the words,
    ticks it or takes the tick away. A tick goes with its form's key (nothing happens until the form is sent).
    `value` is whether it is ticked; command(value) after each change, if given."""

    def __init__(self, parent, ui, text, value=False, command=None, bg=None):
        bg = bg or parent.cget("bg")
        super().__init__(parent, bg=bg)
        self.ui, self.value, self.command = ui, bool(value), command
        self.colours = ui.section
        self.over, self.focused, self.enabled = False, False, True
        self.pictures = {}
        self.box = tk.Label(self, bg=bg, bd=0, highlightthickness=0, takefocus=1, cursor="hand2")
        self.box.pack(side="left")
        self.words = tk.Label(self, text=text, font=ui.fonts.body, fg=theme.TEXT, bg=bg, cursor="hand2", padx=0,
                              pady=0)
        # The box's ring room is part of its picture: the words keep 10 px from the box itself.
        self.words.pack(side="left", padx=(ui.px(10) - ui.px(art.TICK_RING_ROOM), 0))
        self.opendmt3_inset = ui.px(art.TICK_RING_ROOM)
        for part in (self.box, self.words):
            part.bind("<Button-1>", lambda e: self.flip())
            part.bind("<Enter>", lambda e: self._paint(over=True))
            part.bind("<Leave>", lambda e: self._paint(over=False))
        for key in ("<space>", "<Return>", "<KP_Enter>"):
            self.box.bind(key, lambda e: self.flip())
        self.box.bind("<FocusIn>", lambda e: self._paint(focused=True))
        self.box.bind("<FocusOut>", lambda e: self._paint(focused=False))
        self._paint()

    def flip(self):
        if self.enabled:
            self.value = not self.value
            self.box.focus_set()
            self._paint()
            if self.command:
                self.command(self.value)
        return "break"

    def set(self, value):
        self.value = bool(value)
        self._paint()

    def enable(self, on):
        self.enabled = bool(on)
        self.words.configure(fg=theme.TEXT if on else theme.FAINT)
        self.box.configure(takefocus=1 if on else 0)
        self._paint()

    def _paint(self, over=None, focused=None):
        if over is not None:
            self.over = over
        if focused is not None:
            self.focused = focused
        state = "disabled" if not self.enabled else ("hover" if self.over else "normal")
        look = (self.value, state, self.focused)
        if look not in self.pictures:
            picture = art.tick_box(self.value, state, self.ui.scale, self.colours, self.focused)
            self.pictures[look] = (picture, ImageTk.PhotoImage(picture, master=self))
        picture, image = self.pictures[look]
        self.box.opendmt3_picture = picture
        self.box.configure(image=image)


class Segmented(tk.Label):
    """A row of 2 to 4 choices of which one is on (FORMS.md's segmented keys, art.choice_row): the game's leaning keys
    side by side, the chosen one filled in the page's section's colour; the metal's lighter shade under the pointer;
    once Tab has reached it, the keyboard's cyan two pixels inside the chosen key, and the arrows move the choice.

    options: (key, words) pairs; command(key) runs after a click or an arrow key changes the choice.
    """

    def __init__(self, parent, ui, options, value, command, bg=None):
        # On its parent's colour unless told (a card's, or the page's).
        bg = bg or parent.cget("bg")
        super().__init__(parent, bg=bg, cursor="hand2", bd=0, takefocus=1, anchor="nw", highlightthickness=0)
        self.ui, self.command, self.options, self.value = ui, command, list(options), value
        self.colours = ui.section
        # The pictures are made as they are first shown: one for each (chosen, pointed at, ring) look.
        self.hover, self.focused, self.edges, self.pictures = None, False, [], {}
        self.bind("<Button-1>", self._click)
        self.bind("<Motion>", lambda e: self._point(self._at(e.x, e.y)))
        self.bind("<Leave>", lambda e: self._point(None))
        # The keyboard: Tab brings the ring to the chosen key, the arrows move the choice.
        self.bind("<Left>", lambda e: self._step(-1))
        self.bind("<Right>", lambda e: self._step(1))
        self.bind("<Home>", lambda e: self._step(-len(self.options)))
        self.bind("<End>", lambda e: self._step(len(self.options)))
        self.bind("<FocusIn>", lambda e: self._ring(True))
        self.bind("<FocusOut>", lambda e: self._ring(False))
        self._paint()

    def _ring(self, on):
        self.focused = on
        self._paint()

    def _paint(self):
        keys = [key for key, _ in self.options]
        chosen = keys.index(self.value) if self.value in keys else None
        look = (chosen, self.hover, chosen if self.focused else None)
        if look not in self.pictures:
            picture, self.edges = art.choice_row([words for _, words in self.options], look[0], look[1],
                                                 self.colours, self.ui.scale, focused=look[2])
            self.pictures[look] = (picture, ImageTk.PhotoImage(picture, master=self))
        # A dialog draws the window behind it from the widgets (snapshot.py): this is the row's part.
        self.opendmt3_picture, image = self.pictures[look]
        self.configure(image=image)

    def _at(self, x, y):
        """Which choice a point of the label is on: the keys lean, so the line between two of them does too."""
        height = self.opendmt3_picture.height
        # The same point moved along the slope to half the height, where the edges were measured.
        x = x + art.LEAN * (y - height / 2)
        for i, (left, right) in enumerate(self.edges):
            # Up to the middle of the gap after a key counts as that key: no dead line between two choices.
            if x < right + self.ui.px(1) or i == len(self.edges) - 1:
                return i

    def _point(self, index):
        if index != self.hover:
            self.hover = index
            self._paint()

    def _click(self, event):
        self.focus_set()
        self.set(self.options[self._at(event.x, event.y)][0], notify=True)

    def _step(self, by):
        keys = [key for key, _ in self.options]
        at = keys.index(self.value) if self.value in keys else 0
        to = min(len(keys) - 1, max(0, at + by))
        if keys[to] != self.value:
            self.set(keys[to], notify=True)
        return "break"

    def set(self, value, notify=False):
        self.value = value
        self._paint()
        if notify:
            self.command(value)


class Slider(tk.Frame):
    """A slider (FORMS.md) from `low` to `high` (0 to 100 unless given): a 4 px track filled from its start in the
    page's section's colour, an upright chalk knob (art.slider_knob), white under the pointer, and the value at its
    right in figures of one width, `unit` after the number (" ms", say). A drag or a click moves it; once Tab has
    reached it (the cyan ring round the knob) the arrows step it by one, Page Up and Page Down by a tenth, Home and End
    to its ends. command(value) runs when the drag ends, and after each key."""

    def __init__(self, parent, ui, value, command, bg=None, width=320, low=0, high=100, unit=""):
        # On its parent's colour unless told (a card's, or the page's).
        bg = bg or parent.cget("bg")
        super().__init__(parent, bg=bg)
        self.ui, self.command, self.value = ui, command, int(value)
        # The range the track spans, and what the number says after itself.
        self.low, self.high, self.unit = int(low), int(high), unit
        self.w, self.h = ui.px(width), ui.px(34)
        self.colour = ui.section["accent"]
        self.over, self.focused = False, False
        self.knobs = {(state, ring): ImageTk.PhotoImage(art.slider_knob(ui.scale, state, ring), master=parent)
                      for state in ("normal", "hover") for ring in (False, True)}
        self.canvas = tk.Canvas(self, width=self.w, height=self.h, bg=bg, highlightthickness=0, cursor="hand2",
                                takefocus=1)
        self.canvas.pack(side="left")
        # Room for the largest number and the unit, so the label never changes width as the knob moves; the figures
        # stand at its right end, and every slider of a page keeps the same room (7 characters: "+12 dB", "500 ms"),
        # so their numbers end on one line.
        room = max(7, len(str(self.high)) + 1 + len(unit))
        self.number = tk.Label(self, text="", font=ui.fonts.body, fg=theme.TEXT, bg=bg, width=room, anchor="e",
                               padx=0, pady=0)
        self.number.pack(side="left", padx=(ui.px(14), 0))
        # A press takes the keyboard too (its ring round the knob), so the arrows go on from where the pointer left it.
        self.canvas.bind("<Button-1>", lambda e: (self.canvas.focus_set(), self._drag(e)))
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", lambda e: self.command(self.value))
        self.canvas.bind("<Enter>", lambda e: self._look(over=True))
        self.canvas.bind("<Leave>", lambda e: self._look(over=False))
        self.canvas.bind("<FocusIn>", lambda e: self._look(focused=True))
        self.canvas.bind("<FocusOut>", lambda e: self._look(focused=False))
        step = max(1, (self.high - self.low) // 10)
        for key, by in (("<Left>", -1), ("<Right>", 1), ("<Down>", -1), ("<Up>", 1), ("<Prior>", step),
                        ("<Next>", -step), ("<Home>", self.low - self.high), ("<End>", self.high - self.low)):
            self.canvas.bind(key, lambda e, by=by: self._step(by))
        self._draw()

    def _look(self, over=None, focused=None):
        if over is not None:
            self.over = over
        if focused is not None:
            self.focused = focused
        self._draw()

    def _x(self, value):
        """Where a value sits on the track (the knob's middle stays inside the canvas)."""
        pad = self.ui.px(10)
        return pad + (self.w - 2 * pad) * (value - self.low) / float(max(1, self.high - self.low))

    def _drag(self, event):
        pad = self.ui.px(10)
        frac = (event.x - pad) / float(max(1, self.w - 2 * pad))
        # The nearest whole value on the track, never past either end.
        self.value = int(round(self.low + min(1.0, max(0.0, frac)) * (self.high - self.low)))
        self._draw()

    def _step(self, by):
        value = min(self.high, max(self.low, self.value + by))
        if value != self.value:
            self.value = value
            self._draw()
            self.command(self.value)
        return "break"

    def _draw(self):
        c, mid = self.canvas, self.h // 2
        c.delete("all")
        thick = max(2, self.ui.px(4))
        # The empty track, then the filled part up to the knob: from the track's start, or from 0 on a track that goes
        # both ways (an equalizer's band: flat at its middle, a cut or a boost filled from there), with a mark at 0.
        c.create_line(self._x(self.low), mid, self._x(self.high), mid, fill=theme.RAIL, width=thick, capstyle="round")
        start = self._x(0) if self.low < 0 < self.high else self._x(self.low)
        if self.low < 0 < self.high:
            c.create_line(start, mid - self.ui.px(7), start, mid + self.ui.px(7), fill=theme.RAIL, width=self.ui.px(2))
        if self.value != 0 or not self.low < 0:
            c.create_line(start, mid, self._x(self.value), mid, fill=self.colour, width=thick, capstyle="round")
        c.create_image(self._x(self.value), mid, image=self.knobs[("hover" if self.over else "normal", self.focused)])
        # A value that goes both ways says its sign (+3 dB, -2 dB), as the in-game panel writes it.
        sign = "+" if self.low < 0 and self.value > 0 else ""
        self.number.configure(text=sign + str(self.value) + self.unit)


class Select(tk.Canvas):
    """A drop-down of (value, text) pairs in the launcher's own look; command(value) runs on a choice.

    Closed, it is a field: the choice's words on the fields' dark inside with their grey edge (cyan with the keyboard
    on it) and a chevron at its right end. A click, or Enter, Space or Down with the keyboard on it, opens its list
    (SelectList) under it, over everything (above it where the screen has no room under it): the choices on a card's
    colour, the chosen one white with a rule in its page's colour along its left edge, the one under the pointer or the
    keys on a lighter slab. Up and Down move along it, Enter or a click chooses, Esc or a click outside closes it; a
    list longer than it shows scrolls with the wheel and the keys. Never Tk's own list, whose look and place the
    launcher cannot set."""

    # The field's room before its words and the chevron's room at its right end, and its height (logical pixels).
    PAD, ARROW, HEIGHT = 10, 30, 34

    def __init__(self, parent, ui, options, value, command, width=24):
        self.ui, self.options, self.command = ui, list(options), command
        bg = parent.cget("bg")
        px = ui.px
        # As wide as `width` characters of the text font, as a field of that width is, with the chevron's room.
        field_width = ui.fonts.body.measure("0") * width + px(self.PAD) + px(self.ARROW)
        super().__init__(parent, width=field_width, height=px(self.HEIGHT), bg=bg, highlightthickness=0, bd=0,
                         takefocus=1, cursor="hand2")
        self.bg, self.index, self.focused, self.over = bg, 0, False, False
        # The list while it is open (None while closed).
        self.list = None
        self.set_value(value)
        self.bind("<Configure>", lambda e: self.paint())
        self.bind("<Button-1>", lambda e: self.open())
        for key in ("<Return>", "<KP_Enter>", "<space>", "<Down>", "<Alt-Down>"):
            self.bind(key, lambda e: (self.open(), "break")[1])
        self.bind("<FocusIn>", lambda e: self._focus(True))
        self.bind("<FocusOut>", lambda e: self._focus(False))
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        # Gone with its page: its list goes too.
        self.bind("<Destroy>", lambda e: e.widget is self and self.close(), add="+")

    @property
    def value(self):
        """The value chosen."""
        return self.options[self.index][0] if self.options else None

    def get(self):
        """The chosen choice's words (as Tk's drop-down answers)."""
        return self.options[self.index][1] if self.options else ""

    def set_value(self, value):
        """Show `value` as chosen (the first choice when it is none of them)."""
        found = [i for i, (v, _) in enumerate(self.options) if v == value]
        self.index = found[0] if found else 0
        self.paint()

    def _focus(self, on):
        self.focused = on
        self.paint()

    def _hover(self, over):
        self.over = over
        self.paint()

    def paint(self):
        """The field's picture (its inside, its edge, the chevron) and the chosen words over it as Tk text."""
        from PIL import Image, ImageDraw
        px = self.ui.px
        width, height = max(1, self.winfo_width()), max(1, self.winfo_height())
        if width <= 1:
            width, height = int(self.cget("width")), int(self.cget("height"))
        self.delete("all")
        picture = Image.new("RGB", (width, height), art._rgb(theme.FIELD))
        draw = ImageDraw.Draw(picture)
        # The slot's face (FORMS.md, as a field's): the keyboard's cyan two pixels wide with the keyboard on it or
        # while its list is open, a step lighter under the pointer, the slot's edge at rest.
        state = "focus" if (self.focused or self.list is not None) else ("hover" if self.over else "normal")
        picture.paste(art.field_face(width, height, state, self.ui.scale), (0, 0))
        # The chevron at the right end, pointing down (up while the list is open over it).
        cx, cy, half = width - px(self.ARROW) // 2, height // 2, px(4)
        up = self.list is not None and self.list.above
        tip = cy - half // 2 if up else cy + half // 2
        base = cy + half // 2 if up else cy - half // 2
        draw.line([(cx - half, base), (cx, tip), (cx + half, base)], fill=art._rgb(theme.MUTED), width=max(1, px(2)))
        self._image = ImageTk.PhotoImage(picture, master=self)
        # A dialog draws the window behind it from the widgets (snapshot.py): the field as it looks now.
        self.opendmt3_picture = picture
        self.create_image(0, 0, image=self._image, anchor="nw")
        # The chosen words, cut with an ellipsis where the field is too narrow for them.
        room = width - px(self.PAD) - px(self.ARROW)
        self.create_text(px(self.PAD), height // 2, text=fit_words(self.ui.fonts.body, self.get(), room),
                         font=self.ui.fonts.body, fill=theme.TEXT, anchor="w")

    def open(self):
        """Open the list under the field (above it when the screen has no room under it)."""
        if self.list is not None or not self.options:
            return
        self.list = SelectList(self)
        self.paint()

    def close(self):
        """Close the list (nothing chosen), the keyboard back on the field."""
        if self.list is None:
            return
        shown, self.list = self.list, None
        shown.destroy()
        if self.winfo_exists():
            self.paint()

    def choose(self, index):
        """Choose the choice at `index`: the list closes, the field shows it, and command runs for a new one."""
        changed = index != self.index
        self.close()
        if not self.winfo_exists():
            return
        self.index = index
        self.paint()
        self.focus_set()
        if changed:
            self.command(self.options[index][0])


class SelectList(tk.Toplevel):
    """A Select's open list: a window of its own with no frame, over everything, as wide as the field, under it or
    above it, its choices drawn on a canvas (Select says how it looks and takes the keys)."""

    # A choice's height, the most that show at once, the room before the words, the rule's width (logical pixels).
    ROW, MOST, PAD, RULE = 32, 8, 10, 3

    def __init__(self, select):
        ui, px = select.ui, select.ui.px
        super().__init__(select, bg=theme.LINE)
        self.select, self.ui = select, ui
        # No title bar or frame: the window manager places it where it is told and keeps it over the launcher.
        self.overrideredirect(True)
        count = len(select.options)
        shown = min(count, self.MOST)
        width = max(select.winfo_width(), px(80))
        height = shown * px(self.ROW) + 2
        # Under the field, or above it where the screen's foot is too near (a field low on a small screen).
        x, below = select.winfo_rootx(), select.winfo_rooty() + select.winfo_height() + px(2)
        self.above = below + height > select.winfo_screenheight()
        y = select.winfo_rooty() - height - px(2) if self.above else below
        # Never past the screen's right edge either.
        x = max(0, min(x, select.winfo_screenwidth() - width))
        self.geometry("%dx%d+%d+%d" % (width, height, x, y))
        # The list's edge is the window's colour round the canvas: one pixel of seam all round, as a card's.
        self.canvas = tk.Canvas(self, bg=theme.PANEL, highlightthickness=0, bd=0, width=width - 2, height=height - 2,
                                takefocus=1)
        self.canvas.pack(padx=1, pady=1)
        # The first choice in view, and the choice the pointer or the keys are on (the chosen one to start with).
        self.top, self.at = 0, select.index
        self.top = max(0, min(self.at - shown // 2, count - shown))
        self.shown = shown
        self.canvas.bind("<Motion>", lambda e: self._point(e.y))
        self.canvas.bind("<ButtonRelease-1>", lambda e: self._release(e))
        for key, by in (("<Down>", 1), ("<Up>", -1), ("<Next>", self.MOST), ("<Prior>", -self.MOST)):
            self.canvas.bind(key, lambda e, by=by: self._move(by))
        self.canvas.bind("<Home>", lambda e: self._move(-count))
        self.canvas.bind("<End>", lambda e: self._move(count))
        for key in ("<Return>", "<KP_Enter>", "<space>"):
            self.canvas.bind(key, lambda e: self.select.choose(self.at))
        self.canvas.bind("<Escape>", lambda e: self.select.close())
        self.canvas.bind("<Tab>", lambda e: (self.select.close(), "break")[1])
        # The wheel, as each system sends it: Windows and macOS a delta, X11 buttons 4 and 5.
        self.canvas.bind("<MouseWheel>", lambda e: self._scroll(-1 if e.delta > 0 else 1))
        self.canvas.bind("<Button-4>", lambda e: self._scroll(-1))
        self.canvas.bind("<Button-5>", lambda e: self._scroll(1))
        # A press anywhere else (the grab sends it here, outside the list) closes it, as any drop-down does.
        self.bind("<ButtonPress-1>", self._outside, add="+")
        self.paint()
        self.update_idletasks()
        # Over everything, and the keys and the pointer to it until it closes.
        self.lift()
        try:
            self.grab_set()
        except tk.TclError:
            # Not viewable yet on a slow screen: the keys still come by the focus below.
            pass
        self.canvas.focus_force()

    def _row_at(self, y):
        """The choice at height `y` of the canvas, or None past the last."""
        index = self.top + int(y // self.ui.px(self.ROW))
        return index if 0 <= y and index < min(len(self.select.options), self.top + self.shown) else None

    def _point(self, y):
        index = self._row_at(y)
        if index is not None and index != self.at:
            self.at = index
            self.paint()

    def _release(self, event):
        inside = 0 <= event.x < self.canvas.winfo_width() and 0 <= event.y < self.canvas.winfo_height()
        index = self._row_at(event.y) if inside else None
        if index is not None:
            self.select.choose(index)

    def _outside(self, event):
        """A press outside the list (its own window's box) closes it."""
        x, y = event.x_root - self.winfo_rootx(), event.y_root - self.winfo_rooty()
        if not (0 <= x < self.winfo_width() and 0 <= y < self.winfo_height()):
            self.select.close()

    def _move(self, by):
        count = len(self.select.options)
        self.at = max(0, min(count - 1, self.at + by))
        # The choice the keys are on stays in view.
        if self.at < self.top:
            self.top = self.at
        elif self.at >= self.top + self.shown:
            self.top = self.at - self.shown + 1
        self.paint()
        return "break"

    def _scroll(self, by):
        self.top = max(0, min(len(self.select.options) - self.shown, self.top + by))
        self.paint()
        return "break"

    def paint(self):
        """The choices in view: the chosen one white with its page's rule, the one under the pointer or the keys on a
        lighter slab, the others grey; a thin thumb at the right edge when there are more than show."""
        ui, px, c = self.ui, self.ui.px, self.canvas
        c.delete("all")
        width, row = int(c.cget("width")), px(self.ROW)
        options = self.select.options
        accent = ui.section["accent"]
        for slot in range(self.shown):
            index = self.top + slot
            y = slot * row
            if index == self.at:
                c.create_rectangle(0, y, width, y + row, fill=theme.PANEL_HI, outline="")
            chosen = index == self.select.index
            if chosen:
                # The rule along the chosen one's left edge, in its page's colour, as the menu marks its page.
                c.create_rectangle(0, y, px(self.RULE) - 1, y + row - 1, fill=accent, outline="")
            words = fit_words(ui.fonts.body, options[index][1], width - 2 * px(self.PAD))
            c.create_text(px(self.PAD), y + row // 2, text=words, anchor="w", font=ui.fonts.body,
                          fill=theme.TEXT if (chosen or index == self.at) else theme.MUTED)
        # The light along the list's top edge, as what floats has (Sidenote's rim): drawn over the first row.
        c.create_line(0, 0, width, 0, fill=theme.RIM)
        count = len(options)
        if count > self.shown:
            # Where the view is in the whole list: a thin thumb, as the page's scroll bar draws it.
            height = self.shown * row
            top, bottom = thumb_span(height, self.top / count, (self.top + self.shown) / count, px(16))
            c.create_rectangle(width - px(5), top + px(2), width - px(2), bottom - px(2), fill=theme.RAIL_UP,
                               outline="")


def fit_words(font, text, room):
    """`text`, cut with an ellipsis where it is wider than `room` pixels in `font` (a long device name in a field)."""
    if font.measure(text) <= room:
        return text
    while text and font.measure(text + "\u2026") > room:
        text = text[:-1]
    return text + "\u2026"


# The room between a setting's name and its control (logical pixels).
LABEL_GAP = 18


def name_width(ui, names):
    """How wide a column of setting names must be for `names`: the widest of them in the names' font, and the room after
    it. Measured, never a number fixed for one system's font: Windows draws Pretendard wider than Linux does."""
    return max(ui.fonts.body_bold.measure(name) for name in names) + ui.px(LABEL_GAP)


def setting_row(parent, ui, title, control_factory, hint=None, bg=None):
    """A setting: its name on the left, the control on the right of it, the hint underneath, on its parent's colour
    unless told. The page fits one column for its rows' names afterwards (fit_names); until then the row's own name
    sets it."""
    from opendmt3.client import i18n
    bg = bg or parent.cget("bg")
    row = tk.Frame(parent, bg=bg)
    row.columnconfigure(1, weight=1)
    # The name in each language the launcher speaks: the page's layout is the same in both, whichever is on show.
    row.opendmt3_names = i18n.every_language(title)
    row.columnconfigure(0, minsize=name_width(ui, row.opendmt3_names))
    tk.Label(row, text=title, font=ui.fonts.body_bold, fg=theme.TEXT, bg=bg, anchor="w",
             width=0).grid(row=0, column=0, sticky="w", padx=(0, ui.px(LABEL_GAP)))
    control = control_factory(row)
    # Every control's visible edge on one line: a switch keeps its keyboard ring's room round its track inside its
    # picture, so the others are set in by as much.
    room = ui.px(art.TICK_RING_ROOM)
    inset = getattr(control, "opendmt3_inset", 0)
    control.grid(row=0, column=1, sticky="w", padx=(room - inset, 0))
    hint_label = None
    if hint:
        hint_label = label(row, ui, hint, font=ui.fonts.small, fg=theme.MUTED, bg=bg, wrap_margin=4)
        hint_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(ui.px(4), 0))
    row.control, row.hint = control, hint_label
    return row


def fit_names(container, ui, more=()):
    """One column for the names of every setting row under `container` (a page, or a step of the guide), as wide as the
    widest of them in either language and of `more` (the names of rows a choice brings or takes on that page, counted
    whether shown or not), so that a page's controls start on one line and stay there as rows come and go, as
    OpenDMTQ's pages do. Returns the column's width (0 for a page without settings)."""
    rows, found = [], [container]
    # Every widget under the container, without recursion (cards, their bodies, the rows in them).
    while found:
        widget = found.pop()
        if hasattr(widget, "opendmt3_names"):
            rows.append(widget)
        found.extend(widget.winfo_children())
    names = [name for row in rows for name in row.opendmt3_names] + list(more)
    if not names:
        return 0
    width = name_width(ui, names)
    for row in rows:
        row.columnconfigure(0, minsize=width)
    return width


def flow(box, children, gap):
    """Lay `children` (made in `box`) out left to right, `gap` pixels apart, starting a new row (`gap` under the last)
    where the next would pass the box's width, as words flow in a line. The box takes the rows' height; it must get its
    width from its own parent (pack fill="x"), never from the children, so a new layout changes only its height and
    never its width (no layout that undoes itself)."""
    # Placed children leave the box's size to it: the box sets its own height.
    box.pack_propagate(False)
    box.grid_propagate(False)

    def lay(event=None):
        width = box.winfo_width()
        if width <= 1:
            # Not laid out yet: one row as wide as they ask, until the box has a width.
            width = sum(child.winfo_reqwidth() for child in children) + gap * len(children)
        x = y = row_height = 0
        for child in children:
            w, h = child.winfo_reqwidth(), child.winfo_reqheight()
            if x and x + w > width:
                # The next row, under the tallest of the row before.
                x, y, row_height = 0, y + row_height + gap, 0
            child.place(x=x, y=y)
            x += w + gap
            row_height = max(row_height, h)
        height = y + row_height
        if int(box.cget("height")) != height:
            # Only a change: a <Configure> for the same height would lay them out again for nothing.
            box.configure(height=height)

    box.bind("<Configure>", lay, add="+")
    lay()


def divider(parent, ui, pady=12):
    """The faint line between two rows of a card, as OpenDMTQ's cards part their rows."""
    line = tk.Frame(parent, bg=theme.DIVIDER, height=1)
    line.pack(fill="x", pady=ui.px(pady))
    return line


def link(parent, ui, text, command, fg=None, bg=None, chevron=True):
    """Words that take the player somewhere (a page by its menu's name, the launcher from the guide's last step): a
    click, or Enter or Space once Tab has reached them (a cyan ring). In the section's light with a chevron after them
    by default, on the parent's colour unless told."""
    bg = bg or parent.cget("bg")
    words = tk.Label(parent, text=text + (" \u203a" if chevron else ""), font=ui.fonts.body_bold,
                     fg=fg or ui.section["accent"], bg=bg, cursor="hand2", takefocus=1,
                     highlightthickness=max(1, ui.px(2)), highlightbackground=bg, highlightcolor=theme.CYAN)
    for sequence in ("<Button-1>", "<Return>", "<KP_Enter>", "<space>"):
        words.bind(sequence, lambda e: command())
    return words


class Card(tk.Frame):
    """A panel as the family's cards are (both launchers' and both sites'): one pixel of seam round it, its top-right
    corner cut, its parts in `body`. With a title, its name hangs from the top-left corner on a tab in the seam's colour
    that leans at its right end, as the game tabs its panels; `head` is the tab's row, whose right end holds what the
    card does (Check again, a small button) as OpenDMTQ's cards hold it at their title's right end."""

    # The cut corner's size (logical pixels), the site's.
    CUT = 14

    def __init__(self, parent, ui, pad=18, title=None):
        self.ui = ui
        outside = parent.cget("bg")
        # The edge: a hairline round the card (theme.SEAM), lit along its top and a step darker along its foot (the
        # lines placed over it below), as the Platinum Crew site's boxes and Sidenote's panels have their light.
        super().__init__(parent, bg=theme.SEAM, padx=1, pady=1)
        inside = tk.Frame(self, bg=theme.PANEL)
        inside.pack(fill="both", expand=True)
        top = ui.px(pad - 2)
        # The tab's row: the tab at its left, the card's action at its right end (nothing until a page puts one).
        self.head = tk.Frame(inside, bg=theme.PANEL)
        self.head.pack(fill="x")
        self.tab = None
        if title:
            # A card's name in the game's capitals, English in both languages as the menu's (THEME.md), the content in
            # the page's language.
            words = i18n.english_of(title).upper()
            picture = art.name_plate(words, ui.scale, fill=theme.LINE)
            image = ImageTk.PhotoImage(picture, master=self)
            self.tab = tk.Label(self.head, image=image, bg=theme.PANEL, bd=0)
            # Kept on the label: Tk shows a picture only while Python holds it. The words ride along for the tests.
            self.tab.image, self.tab.words, self.tab.opendmt3_picture = image, words, picture
            self.tab.pack(side="left", anchor="nw")
            # The tab already stands between the seam and the content.
            top = ui.px(12)
        # A card's action at the head's right end stands a little in from the seam, its top in line with the tab's.
        self.head_pad = (ui.px(pad - 8), ui.px(6))
        self.body = tk.Frame(inside, bg=theme.PANEL, padx=ui.px(pad), pady=0)
        self.body.pack(fill="both", expand=True, pady=(top, ui.px(pad - 2)))
        # The cut: a small picture over the square corner, its seam included (placed from the card's outer edge, not
        # inside the pixel of seam the frame keeps round its inside): the page's colour beyond the cut, the seam going
        # on along it from the top edge to the right one, so that no square corner is left.
        cut = ui.px(self.CUT)
        # The top edge's light, from the left to where the cut begins (it goes on down the cut in the corner's picture),
        # and the foot a step darker: one line round the card, its light from above.
        tk.Frame(self, bg=theme.RIM, height=1, bd=0, highlightthickness=0).place(x=0, y=0, relwidth=1.0, width=-cut,
                                                                                  height=1, bordermode="outside")
        tk.Frame(self, bg=theme.FOOT, height=1, bd=0, highlightthickness=0).place(x=0, rely=1.0, y=-1, relwidth=1.0,
                                                                                   height=1, bordermode="outside")
        picture = art.corner(cut, theme.PANEL, outside, seam=theme.SEAM, rim=theme.RIM)
        self._corner = ImageTk.PhotoImage(picture, master=self)
        corner = tk.Label(self, image=self._corner, bd=0, highlightthickness=0, bg=outside)
        # A dialog draws the window behind it from the widgets (snapshot.py): the corner as it looks.
        corner.opendmt3_picture = picture
        corner.place(relx=1.0, x=-cut, y=0, width=cut, height=cut, bordermode="outside")

    def action(self, text, command, kind="secondary"):
        """What the card does, as a small button at the right end of its tab's row (OpenDMTQ's Check again)."""
        button = Button(self.head, self.ui, text, command, kind=kind, size="small")
        button.pack(side="right", padx=(0, self.head_pad[0]), pady=(self.head_pad[1], 0))
        return button


class Lamp(tk.Label):
    """A small leaning light beside a line (art.lamp): filled when lit, an outline when not. `drop` is how far
    below a line's top it sits to stand in the middle of the first line of text."""

    def __init__(self, parent, ui, colour, lit=True, bg=None, size=(13, 10)):
        # On its parent's colour unless told (a card's, or the page's).
        bg = bg or parent.cget("bg")
        super().__init__(parent, bg=bg, bd=0, highlightthickness=0)
        self.ui, self.size = ui, size
        self.show(colour, lit)
        self.drop = max(0, (ui.fonts.body.metrics("linespace") - self.opendmt3_picture.height + 1) // 2)

    def show(self, colour, lit=True):
        # A dialog draws the window behind it from the widgets (snapshot.py): this is the lamp's part.
        self.opendmt3_picture = art.lamp(colour, lit, self.ui.scale, self.size)
        self.image = ImageTk.PhotoImage(self.opendmt3_picture, master=self)
        self.configure(image=self.image)


def check_line(parent, ui, state, text, action_text=None, action=None, bg=None):
    """A ready-check line: a lamp (lime: fine; an amber outline: will change; pink: a problem), the words, and an
    optional link, on its parent's colour unless told."""
    bg = bg or parent.cget("bg")
    row = tk.Frame(parent, bg=bg)
    colour, lit = {"ok": (theme.NET, True), "change": (theme.AMBER, False), "bad": (theme.PINK, True)}[state]
    lamp = Lamp(row, ui, colour, lit, bg=bg)
    lamp.pack(side="left", anchor="n", pady=(lamp.drop, 0))
    beside = [lamp]
    if action_text and action:
        # The way to fix it, by the mouse or the keyboard (link: a cyan ring once Tab reaches it).
        fix = link(row, ui, action_text, action, bg=bg)
        fix.pack(side="right", anchor="n")
        beside.append(fix)
    words = label(row, ui, text, fg=theme.TEXT if state != "ok" else theme.MUTED, bg=bg, wrap_margin=24,
                  beside=beside)
    words.pack(side="left", fill="x", padx=(ui.px(8), 0))
    return row


def check_note(parent, ui, text, problem=False, bg=None):
    """What stands under a ready-check line, small, under the line's words (past its lamp): why a failed line stops
    PLAY, in the error colour, or a note on a line that is fine, in the hint colour. On its parent's colour unless
    told."""
    bg = bg or parent.cget("bg")
    row = tk.Frame(parent, bg=bg)
    # As far in as the line's words: the lamp's width and the gap after it.
    indent = art.lamp(theme.MUTED, True, ui.scale).width + ui.px(8)
    words = label(row, ui, text, font=ui.fonts.small, fg=theme.PINK if problem else theme.MUTED, bg=bg, wrap_margin=0)
    words.pack(fill="x", padx=(indent, 0))
    return row


# A field's typing in the launcher's colours: the selection in the metal's lighter shade, never Windows' blue.
SELECTION = {"selectbackground": theme.RAIL_UP, "selectforeground": theme.TEXT, "selectborderwidth": 0}


def entry(parent, ui, width=18, secret=False, placeholder=None, size="md"):
    """A text field (Field): `width` characters wide, a password's dots and Show with `secret`, an example of what goes
    there in faint grey while it is empty (`placeholder`)."""
    return Field(parent, ui, width=width, secret=secret, placeholder=placeholder, size=size)


class Field(tk.Canvas):
    """The launcher's one text field (FORMS.md's slot), used by every form, dialog and step: a slot sunk into its
    card (art.field_face), square, its edge in the state's colour: at rest, a step lighter under the pointer, the
    keyboard's cyan two pixels wide while it is typed in, the problem's pink while what was typed there is refused
    (set_error), quieter while it cannot be used (enable). Three heights (`size`, FORMS.md's launcher mapping): "md" a
    page's (34 logical pixels, a page's buttons' height, so a row of fields and keys has one height), "sm" a table
    row's (26, the small buttons'), "lg" the sign-in's (40, as its key: Button size "lg", the site's 48 px door at the
    launcher's scale). The typing goes to a plain Tk entry in the slot's flat middle (`entry`: Windows' own typing,
    Korean input included); a click anywhere on the face puts the caret there.

    `secret`: a password's dots, and Show inside the slot's right end (a small quiet key, two corners cut), which shows
    what was typed until it is pressed again (Hide, the key lit); Tab reaches it right after the field (its cyan
    ring), Enter or Space presses it. `mark`: "person", "lock" or "search" at the slot's left end, faint, cyan while
    the field is typed in. `placeholder`: an example in the faint grey while the field is empty and not typed in.
    Used as a Tk entry is (get, insert, delete, bind, focus_set...): those calls reach the entry inside. Its width is
    `width` characters, or what its box gives it (pack fill, grid sticky, a dialog's window): the face follows."""

    # Its height, the room either side of the words, the key's room and its inset, the mark's size and room, by size
    # (logical pixels).
    HEIGHTS = {"sm": 26, "md": 34, "lg": 40}
    PADS = {"sm": 8, "md": 10, "lg": 12}
    KEY_INSET, KEY_MIN, MARK = 5, 56, {"sm": 14, "md": 16, "lg": 16}

    def __init__(self, parent, ui, width=24, secret=False, placeholder=None, size="md", mark=None):
        self.ui, self.bg, self.secret, self.size, self.mark_kind = ui, parent.cget("bg"), secret, size, mark
        px = ui.px
        super().__init__(parent, bg=self.bg, highlightthickness=0, bd=0, cursor="xterm", takefocus=0)
        font = ui.fonts.field if size == "lg" else ui.fonts.body
        self.entry = tk.Entry(self, width=width, font=font, bg=theme.FIELD, fg=theme.TEXT,
                              insertbackground=theme.TEXT, relief="flat", bd=0, highlightthickness=0,
                              disabledbackground=art.FIELD_FILLS["disabled"], disabledforeground=theme.FAINT,
                              show="\u2022" if secret else "", **SELECTION)
        self.focused, self.under, self.error, self.enabled, self.shown = False, False, False, True, False
        self.height = px(self.HEIGHTS[size])
        self.pad = px(self.PADS[size])
        # The mark's room at the left: the mark and a step after it.
        self.mark_room = (px(self.MARK[size]) + px(14)) if mark else 0
        # Show inside a password's slot: a small key whose look is a picture (art.slot_key), its words Tk's.
        self.toggle, self.key_width = None, 0
        if secret:
            words = (ui.words("field.show"), ui.words("field.hide"))
            self.key_width = max(px(self.KEY_MIN), max(ui.fonts.key.measure(word) for word in words) + 2 * px(10))
            key_height = self.height - 2 * px(self.KEY_INSET)
            self._keys = {(state, ring): art.slot_key(self.key_width, key_height, state, ui.scale, ring)
                          for state in ("normal", "hover", "on") for ring in (False, True)}
            self._key_images = {look: ImageTk.PhotoImage(picture, master=self) for look, picture in self._keys.items()}
            self.toggle = tk.Label(self, text=words[0], font=ui.fonts.key, fg=theme.MUTED, bg=theme.FIELD,
                                   image=self._key_images[("normal", False)], compound="center", bd=0,
                                   highlightthickness=0, cursor="hand2", takefocus=1)
            self._key_under, self._key_ring = False, False
            for sequence in ("<Button-1>", "<Return>", "<KP_Enter>", "<space>"):
                self.toggle.bind(sequence, lambda e: self.flip())
            self.toggle.bind("<Enter>", lambda e: self._paint_key(under=True), add="+")
            self.toggle.bind("<Leave>", lambda e: self._paint_key(under=False), add="+")
            self.toggle.bind("<FocusIn>", lambda e: self._paint_key(ring=True), add="+")
            self.toggle.bind("<FocusOut>", lambda e: self._paint_key(ring=False), add="+")
        # The mark's two looks (at rest, typed in).
        self.marker = None
        if mark:
            self._marks = {focused: ImageTk.PhotoImage(art.field_mark(mark, self.MARK[size],
                                                                      theme.CYAN if focused else theme.FAINT,
                                                                      ui.scale), master=self)
                           for focused in (False, True)}
        # The example over the empty entry, shown while nothing is typed and the field is not typed in.
        self.hint = None
        if placeholder:
            self.hint = tk.Label(self, text=placeholder, font=font, fg=theme.FAINT, bg=theme.FIELD, bd=0,
                                 cursor="xterm", anchor="w", padx=0, pady=0)
            self.hint.bind("<Button-1>", lambda e: self._caret())
        # Its own size: the entry's characters and the rooms round them, its height.
        key_room = (self.key_width + px(self.KEY_INSET) + px(8)) if secret else 0
        tk.Canvas.configure(self, width=self.entry.winfo_reqwidth() + 2 * self.pad + self.mark_room + key_room,
                            height=self.height)
        self._face, self._size = None, None
        self.entry.bind("<FocusIn>", lambda e: self._paint(focused=True), add="+")
        self.entry.bind("<FocusOut>", lambda e: self._paint(focused=False), add="+")
        # Typing takes back an error said about what was there (on_typed: the line under the field goes too).
        self.on_typed = None
        self.entry.bind("<Key>", self._typed, add="+")
        for part in (self, self.entry) + tuple(p for p in (self.toggle, self.hint) if p is not None):
            tk.Misc.bind(part, "<Enter>", lambda e: self._paint(under=True), add="+")
            tk.Misc.bind(part, "<Leave>", lambda e: self._paint(under=False), add="+")
        # A click on the face beside the words: the caret at their end, as a click past the words in the entry does.
        tk.Misc.bind(self, "<Button-1>", lambda e: self._caret())
        tk.Misc.bind(self, "<Configure>", lambda e: self._lay(), add="+")
        self._lay()

    # ---- the face and what stands on it

    def _caret(self):
        if self.enabled:
            self.entry.focus_set()
            self.entry.icursor("end")

    def _lay(self):
        """The face at the field's size now: the mark at its left, the entry in its flat middle, Show at its right."""
        px = self.ui.px
        width = max(1, self.winfo_width() if self.winfo_width() > 1 else int(self.cget("width")))
        height = max(1, self.winfo_height() if self.winfo_height() > 1 else int(self.cget("height")))
        if (width, height) == self._size:
            return
        self._size = (width, height)
        self.faces = {state: art.field_face(width, height, state, self.ui.scale)
                      for state in ("normal", "hover", "focus", "error", "disabled")}
        self.images = {state: ImageTk.PhotoImage(face, master=self) for state, face in self.faces.items()}
        tk.Canvas.delete(self, "all")
        self._face = self.create_image(0, 0, image=self.images["normal"], anchor="nw")
        left = self.pad + self.mark_room
        right = (self.key_width + px(self.KEY_INSET) + px(8)) if self.secret else self.pad
        if self.mark_kind:
            self.marker = self.create_image(self.pad + px(2), height // 2, image=self._marks[False], anchor="w")
        self.create_window(left, height // 2, window=self.entry, anchor="w", width=max(px(20), width - left - right))
        if self.toggle is not None:
            self.create_window(width - px(self.KEY_INSET), height // 2, window=self.toggle, anchor="e")
        if self.hint is not None:
            self._hint_item = self.create_window(left, height // 2, window=self.hint, anchor="w")
        self._paint()

    def _paint(self, focused=None, under=None):
        """The face for the state: not usable, refused, typed in, under the pointer, else at rest; the mark lit while
        typed in; the example while the field is empty and not typed in."""
        if focused is not None:
            self.focused = focused
        if under is not None:
            self.under = under
        if not self.winfo_exists() or self._face is None:
            return
        # Refused wins over the keyboard's ring until the next key typed takes it away (_typed): after a wrong try the
        # field itself says it, not only the line under it (the final review's D-09).
        state = ("disabled" if not self.enabled else "error" if self.error else "focus" if self.focused
                 else "hover" if self.under else "normal")
        self.itemconfigure(self._face, image=self.images[state])
        # A dialog draws the window behind it from the widgets (snapshot.py): the face as it looks now.
        self.opendmt3_picture = self.faces[state]
        if self.marker is not None:
            self.itemconfigure(self.marker, image=self._marks[self.focused])
        if self.hint is not None:
            empty = not self.entry.get()
            self.itemconfigure(self._hint_item, state="normal" if empty and not self.focused else "hidden")

    def _paint_key(self, under=None, ring=None):
        """Show's look: pressed in while the password shows, lighter under the pointer, the ring with the keyboard."""
        if under is not None:
            self._key_under = under
        if ring is not None:
            self._key_ring = ring
        state = "on" if self.shown else ("hover" if self._key_under else "normal")
        self.toggle.configure(image=self._key_images[(state, self._key_ring)],
                              fg=theme.TEXT if (self.shown or self._key_under) else theme.MUTED)
        # A dialog draws the window from the widgets (snapshot.py): the key as it looks now.
        self.toggle.opendmt3_picture = self._keys[(state, self._key_ring)]

    def _typed(self, event):
        if event.keysym in ("Return", "KP_Enter", "Tab", "ISO_Left_Tab", "Escape"):
            return
        if self.error:
            self.set_error(False)
            if self.on_typed:
                self.on_typed()
        # The example goes with the first key (the entry's words come with the key's release).
        self.after_idle(self._paint)

    # ---- what the field does

    def flip(self):
        """Show the typed words, or hide them again; the keyboard stays where it was."""
        if not self.secret:
            return "break"
        self.shown = not self.shown
        self.entry.configure(show="" if self.shown else "\u2022")
        self.toggle.configure(text=self.ui.words("field.hide" if self.shown else "field.show"))
        self._paint_key()
        return "break"

    def set_error(self, on):
        """What was typed here was refused (on: the problem's pink all round), or that is over."""
        if bool(on) != self.error:
            self.error = bool(on)
            self._paint()

    def enable(self, on):
        """Typing in it, or not (a form at work): the quieter face, the words in the faint grey."""
        self.enabled = bool(on)
        self.entry.configure(state="normal" if on else "disabled")
        if self.toggle is not None:
            self.toggle.configure(takefocus=1 if on else 0)
        self._paint()

    def refresh(self):
        """The example shown or not, after words were put into the field by the program."""
        self._paint()

    # The entry's own calls, so a field is used as a Tk entry is.
    def get(self):
        return self.entry.get()

    def insert(self, index, text):
        self.entry.insert(index, text)
        self._paint()

    def delete(self, first, last=None):
        self.entry.delete(first, last)
        self._paint()

    def bind(self, sequence=None, func=None, add=None):
        # Keys typed go to the entry inside (Enter submits, Esc closes a dialog).
        return self.entry.bind(sequence, func, add)

    def focus_set(self):
        return self.entry.focus_set()

    def focus_force(self):
        return self.entry.focus_force()

    def icursor(self, index):
        return self.entry.icursor(index)

    def select_range(self, start, end):
        return self.entry.select_range(start, end)

    def selection_present(self):
        return self.entry.selection_present()

    def event_generate(self, sequence, **kw):
        # A key made by a program (the UI run's Enter) goes where a typed one goes: the entry.
        if sequence.startswith("<Key") or sequence in ("<Return>", "<KP_Enter>", "<Escape>", "<Tab>"):
            return self.entry.event_generate(sequence, **kw)
        return tk.Canvas.event_generate(self, sequence, **kw)


class Said(tk.Frame):
    """One line that says how something stands, in place: a small lamp in its tone's colour and the words, wrapping to
    the line's width; set() says it again. Tones: "ok" (lime), "warn" (amber), "bad" (pink, the words in the pink that
    reads: theme.BAD_INK), None (no lamp, the hint's ink). Under a field it says what is wrong with what was typed
    there (FORMS.md: the problem's 7 px lamp, then the words) or what the field takes (a hint); under a form, how the
    form stands (too many tries, a server that does not answer), with a link under the words when there is a way on."""

    TONES = {"ok": theme.NET, "warn": theme.AMBER, "bad": theme.PINK}

    def __init__(self, parent, ui, font=None, bg=None):
        bg = bg or parent.cget("bg")
        super().__init__(parent, bg=bg)
        self.ui, self.tone, self.text, self.font = ui, None, "", font or ui.fonts.small
        # FORMS.md's lamp before an error: the launcher's leaning one, 9 by 7.
        self.lamp = Lamp(self, ui, theme.MUTED, bg=bg, size=(9, 7))
        self.words = label(self, ui, "", font=self.font, fg=theme.HINT, bg=bg, wrap_margin=0, beside=(self.lamp,))
        self.words.pack(side="right", fill="x", expand=True)
        # A link after the words, when the line has a way on (Test the connection after a server that did not answer).
        self.link = None

    def set(self, text, tone=None, action=None):
        """Say `text` in `tone`; `action` (words, command) adds a link under the words."""
        self.text, self.tone = text or "", tone
        if tone in self.TONES:
            self.lamp.show(self.TONES[tone], True)
            # The lamp on the middle of the words' first line.
            drop = max(0, (self.font.metrics("linespace") - self.lamp.opendmt3_picture.height + 1) // 2)
            self.lamp.pack(side="left", anchor="n", padx=(0, self.ui.px(8)), pady=(drop, 0))
        else:
            self.lamp.pack_forget()
        self.words.configure(text=self.text, fg=theme.BAD_INK if tone == "bad" else theme.HINT if tone is None
                             else theme.TEXT)
        if self.link is not None:
            self.link.destroy()
            self.link = None
        if action:
            self.link = link(self, self.ui, action[0], action[1], bg=self.cget("bg"))
            self.link.configure(font=self.ui.fonts.small)
            self.link.pack(side="bottom", anchor="w", pady=(self.ui.px(4), 0), before=self.words)
        return self


class Form(tk.Frame):
    """A form, as FORMS.md has every form of the launcher: each field named over it (small and semibold, in the ash's
    grey, 6 px over the slot), the field, and under it what the field takes (a hint, in the hint's ink) or, while it
    is wrong, what is wrong with it (the problem's lamp and words, in place of the hint); fields stacked one under
    another or side by side in columns (`field(..., row, column)`, columns top-aligned, so an error under one never
    moves the others); its key under them 24 px down, or beside the fields in their row (`button(beside=True)`); a
    form-level line (too many tries, a server that does not answer) right above the keys (`tell`). Enter in any field
    presses the key; a form at work (`busy`) cannot be typed in, and its key shows the game's moving stripes until the
    answer comes. `width`: the fields' width (logical pixels; a stacked form keeps to a readable width)."""

    # The room between a field's name and the field, between a field and its line under it, between a field and the
    # next name, between columns, above the form's key, and between the form's line and the key (logical pixels:
    # FORMS.md's).
    NAME_GAP, UNDER_GAP, FIELD_GAP, COLUMN_GAP, BUTTON_GAP, LINE_GAP = 6, 6, 16, 16, 24, 12

    # A side-by-side form's columns are at least this wide (logical pixels: FORMS.md's 160), their fields filling them.
    COLUMN_LEAST = 160

    def __init__(self, parent, ui, bg=None, width=None):
        bg = bg or parent.cget("bg")
        super().__init__(parent, bg=bg)
        self.ui, self.bg, self.width = ui, bg, width
        self.fields, self.errors, self.names, self.hints = {}, {}, {}, {}
        self.submit_button, self.submit_words, self.command = None, None, None
        self.grid_frame = tk.Frame(self, bg=bg)
        self.grid_frame.pack(anchor="w", fill="x" if width else None)
        self.keys = None
        self.line = Said(self, ui)

    def field(self, key, name, width=24, secret=False, placeholder=None, row=None, column=0, size="md", mark=None,
              hint=None):
        """A field named `name`, in its row and column (the next row of column 0 by default), `hint` under it."""
        px = self.ui.px
        row = len([k for k in self.fields if self.fields[k].opendmt3_place[1] == column]) if row is None else row
        box = tk.Frame(self.grid_frame, bg=self.bg)
        box.grid(row=row, column=column, sticky="new", padx=(0 if column == 0 else px(self.COLUMN_GAP), 0),
                 pady=(0 if row == 0 else px(self.FIELD_GAP), 0))
        # The column's width: the form's for a stacked one, at least FORMS.md's 160 side by side; the field fills it.
        side_by_side = row == 0 and column > 0 or any(f.opendmt3_place[1] > 0 for f in self.fields.values())
        least = px(self.width) if self.width else px(self.COLUMN_LEAST)
        self.grid_frame.columnconfigure(column, minsize=least)
        if side_by_side and not self.width:
            # The first column too, once a second comes.
            self.grid_frame.columnconfigure(0, minsize=least)
        named = tk.Label(box, text=name, font=self.ui.fonts.label, fg=theme.MUTED, bg=self.bg, anchor="w",
                         padx=0, pady=0)
        named.pack(anchor="w", pady=(0, px(self.NAME_GAP)))
        made = Field(box, self.ui, width=width, secret=secret, placeholder=placeholder, size=size, mark=mark)
        made.pack(anchor="w", fill="x")
        made.opendmt3_place = (row, column)
        error = Said(box, self.ui)
        if hint:
            # What the field takes, under it until an error takes its place.
            error.set(hint)
            error.pack(fill="x", pady=(px(self.UNDER_GAP), 0))
        made.on_typed = lambda key=key: self.say(key, None)
        # Enter in the field presses the form's key.
        for sequence in ("<Return>", "<KP_Enter>"):
            made.bind(sequence, lambda e: self.submit())
        self.fields[key], self.errors[key], self.names[key], self.hints[key] = made, error, named, hint
        return made

    def button(self, words, command, row=None, column=0, beside=False, main=None, size="normal", fill=False):
        """The form's key: under the fields (24 px down), or `beside` them in their row at (row, column), its top on
        the fields' top (under a name's height). `main(parent, words, command, size, fill)` makes it
        (pages.main_button: lit while PLAY waits); the section's main look otherwise."""
        px = self.ui.px
        self.command, self.submit_words = command, words
        if beside:
            holder = tk.Frame(self.grid_frame, bg=self.bg)
            holder.grid(row=row, column=column, sticky="nw", padx=(px(self.COLUMN_GAP), 0))
            # Under the field's name, as the fields are: the name's line and its gap above the key.
            spacer = tk.Frame(holder, bg=self.bg, height=self.ui.fonts.label.metrics("linespace") + px(self.NAME_GAP))
            spacer.pack(side="top")
            parent = holder
            # Where the card is too narrow for the fields and the key in one row (a small window), the key goes under
            # the fields, at the left, 24 px down (FORMS.md: the form wraps when the card is narrow).
            self._beside = (holder, spacer, row, column)
            tk.Misc.bind(self.master, "<Configure>", lambda e: self._wrap_key(), add="+")
            self.after_idle(self._wrap_key)
        else:
            self.keys = parent = tk.Frame(self, bg=self.bg)
            parent.pack(anchor="w", fill="x" if fill else None, pady=(px(self.BUTTON_GAP), 0))
        made = (main(parent, words, self.submit, size, fill) if main
                else Button(parent, self.ui, words, self.submit, kind="primary", size=size, fill=fill))
        made.pack(side="top" if fill else "left", anchor="w", fill="x" if fill else None)
        self.submit_button = made
        return made

    def _wrap_key(self):
        """The key beside the fields while the row holds them all, else under them at the left."""
        holder, spacer, row, column = self._beside
        if not holder.winfo_exists():
            return
        px = self.ui.px
        room = self.master.winfo_width()
        if room <= 1:
            return
        # The fields' row as it asks to be (each column its least width or its field's, the gaps between) and the key
        # with its gap.
        fields = px(self.COLUMN_GAP) * (column - 1)
        for c in range(column):
            boxes = [b for b in self.grid_frame.grid_slaves(column=c) if b is not holder]
            fields += max([int(self.grid_frame.columnconfigure(c)["minsize"])] +
                          [b.winfo_reqwidth() for b in boxes])
        need = fields + px(self.COLUMN_GAP) + self.submit_button.winfo_reqwidth()
        under = need > room
        if under == getattr(self, "_key_under", None):
            return
        self._key_under = under
        if under:
            holder.grid_configure(row=row + 1, column=0, columnspan=column, padx=(0, 0),
                                  pady=(px(self.BUTTON_GAP), 0))
            spacer.pack_forget()
        else:
            holder.grid_configure(row=row, column=column, columnspan=1, padx=(px(self.COLUMN_GAP), 0), pady=(0, 0))
            spacer.pack(side="top", before=self.submit_button)

    def say(self, key, text, tone="bad"):
        """What is wrong with one field, under it in place of its hint (None: nothing wrong, the hint again), its
        edge in the problem's colour while it is."""
        error, made, hint = self.errors[key], self.fields[key], self.hints.get(key)
        if text:
            error.set(text, tone)
        elif hint:
            error.set(hint)
        if text or hint:
            if not error.winfo_manager():
                error.pack(fill="x", pady=(self.ui.px(self.UNDER_GAP), 0))
        elif error.winfo_manager():
            error.pack_forget()
        made.set_error(bool(text) and tone == "bad")

    def tell(self, text, tone=None, action=None):
        """The form's own line, right above its keys (None: hidden): how it stands, or why it could not."""
        if text:
            self.line.set(text, tone, action)
            if not self.line.winfo_manager():
                options = {"fill": "x", "anchor": "w", "pady": (self.ui.px(self.LINE_GAP), 0)}
                if self.keys is not None:
                    self.line.pack(before=self.keys, **options)
                else:
                    self.line.pack(**options)
        elif self.line.winfo_manager():
            self.line.pack_forget()

    def into_view(self):
        """Scroll the page the least that shows what the form just said about a try (its line above the keys, or the
        lowest field's error), with a little air: in a small window the form's foot may be under the page's. Called
        after a try a person made, never while a page is built (it would open the page scrolled)."""
        said = [self.line] if self.line.winfo_manager() and self.line.tone == "bad" else []
        said += [e for e in self.errors.values() if e.winfo_manager() and e.tone == "bad"]
        area = self.master
        while area is not None and not isinstance(area, ScrollArea):
            area = area.master
        if not said or area is None:
            return
        # Laid out first: the line or the error may have been packed just now.
        self.update_idletasks()
        # The lowest of them (the line stands under every field's error), which brings the others with it.
        area.show(max(said, key=lambda x: x.winfo_rooty() + x.winfo_height()), self.ui.px(14))

    def clear(self):
        """Every field's error said no more (their hints again)."""
        for key in self.fields:
            self.say(key, None)

    def submit(self):
        if self.command and (self.submit_button is None or self.submit_button.enabled):
            self.command()
        return "break"

    def busy(self, on):
        """At work (on: the fields cannot be typed in, the key shows the game's moving stripes and cannot be
        pressed), or done."""
        for made in self.fields.values():
            made.enable(not on)
        if self.submit_button is not None:
            self.submit_button.busy(on)
