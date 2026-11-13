"""The launcher's building blocks, drawn to match its theme instead of the Windows defaults.

Tk's stock widgets look like 1990s Windows on a dark background, so the controls here are Labels and Canvases
with images from art.py. Each keeps its own images alive (Tk drops an image the moment Python forgets it).
"""

import tkinter as tk
from tkinter import ttk

from PIL import ImageTk

from opendmt3.client import art, theme


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
    """Dark styles for the one ttk widget used (the drop-down list)."""
    s = ttk.Style(ui.root)
    # 'clam' is the built-in theme that honours colours on every platform.
    s.theme_use("clam")
    s.configure("Dark.TCombobox", fieldbackground=theme.FIELD, background=theme.PANEL_HI, foreground=theme.TEXT,
                arrowcolor=theme.TEXT, bordercolor=theme.LINE, lightcolor=theme.LINE, darkcolor=theme.LINE,
                selectbackground=theme.FIELD, selectforeground=theme.TEXT, padding=ui.px(6))
    s.map("Dark.TCombobox", fieldbackground=[("readonly", theme.FIELD)], foreground=[("readonly", theme.TEXT)],
          bordercolor=[("focus", theme.CYAN)], arrowcolor=[("disabled", theme.FAINT)])
    # The list that drops down is a plain Tk listbox; its colours come from the option database.
    ui.root.option_add("*TCombobox*Listbox.background", theme.FIELD)
    ui.root.option_add("*TCombobox*Listbox.foreground", theme.TEXT)
    ui.root.option_add("*TCombobox*Listbox.selectBackground", theme.RAIL_UP)
    ui.root.option_add("*TCombobox*Listbox.selectForeground", theme.TEXT)
    ui.root.option_add("*TCombobox*Listbox.font", ui.fonts.body)


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
        self.delete("all")
        top, bottom = self.thumb()
        # Thin at rest, a little wider under the pointer or in the hand.
        held = self.grip is not None
        inset = self.ui.px(3 if held or self.over else 4)
        colour = theme.FAINT if held else theme.RAIL_UP if self.over else theme.RAIL
        self.create_rectangle(inset, top, self.winfo_width() - inset, bottom, fill=colour, outline="")

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


class Header(tk.Canvas):
    """The bar across the window's top, as both launchers and both sites have it: the mark with its version block
    (art.brand) at its left end, then the menu, its names in the wide face in English in both languages (as both sites'
    menus and the game's are): grey, white under the pointer, the page on show white with a rule in its section's colour
    along the bar's foot, as the site's bar marks its page. Under the bar, for the first-start guide, the guide's steps
    across (set_step): each step's number and name over a rule, the step on show and the steps taken in the guide's
    blue, the steps to come grey.

    The menu takes the keyboard as OpenDMTQ's does: Tab reaches the bar (a cyan ring on the page on show), the arrow keys
    and Tab move the ring along the names, Enter or Space opens the page with the ring, and Tab past the last name (or
    Shift+Tab before the first) goes on to the page.
    """

    # The bar's height, the room at its left end (the page's own margin, so the mark lines up with the cards under it),
    # the room either side of a name, the gap after the mark, and the height of the guide's steps under the bar (logical
    # pixels).
    HEIGHT, EDGE, NAME_PAD, AFTER_MARK, STEPS_H = 64, 32, 13, 26, 60

    def __init__(self, parent, ui, brand, nav=(), on_nav=None, steps=()):
        self.ui = ui
        px = ui.px
        height = px(self.HEIGHT) + (px(self.STEPS_H) if steps else 0)
        # The keyboard reaches the bar only when it has a menu (the guide's has none).
        super().__init__(parent, height=height, bg=theme.BAR, highlightthickness=0, bd=0,
                         takefocus=1 if nav else 0)
        # The mark (a picture), the menu as (key, words), what a name's press does, and the guide's step names.
        self.brand_picture = brand
        self.nav, self.on_nav, self.steps = list(nav), on_nav, list(steps)
        # The page on show, the name under the pointer, the name with the keyboard's ring, the guide's step on show.
        self.current, self.hover, self.ring, self.step = None, None, None, 0
        # A drawing waiting for a resize to settle.
        self._job = None
        # Each name's box on the bar once it is drawn, for the rule under it and the keyboard's ring.
        self.boxes = {}
        self.bind("<Configure>", lambda e: self._queue())
        for key, move in (("<Tab>", 1), ("<Shift-Tab>", -1), ("<ISO_Left_Tab>", -1), ("<Right>", 1), ("<Left>", -1)):
            self.bind(key, lambda e, m=move, k=key: self._move(m, k))
        for key in ("<Return>", "<KP_Enter>", "<space>"):
            self.bind(key, lambda e: self._press(self.ring))
        self.bind("<FocusIn>", lambda e: self._focused(True))
        self.bind("<FocusOut>", lambda e: self._focused(False))

    def _queue(self):
        """Draw again once the size settles (a drag fires many resize events)."""
        if self._job is not None:
            self.after_cancel(self._job)
        self._job = self.after(30, self.draw)

    def draw(self):
        """The bar's picture (its colour, the line along its foot, the mark), the names over it as Tk's own text (as
        crisp as every label), and the guide's steps under it."""
        from PIL import Image
        self._job = None
        if not self.winfo_exists():
            return
        px = self.ui.px
        width, height = max(1, self.winfo_width()), max(1, self.winfo_height())
        bar_h = px(self.HEIGHT)
        self.delete("all")
        picture = Image.new("RGB", (width, height), art._rgb(theme.BAR))
        # The line along the bar's foot, a pixel of seam, as the site's bar has it.
        picture.paste(art._rgb(theme.LINE), (0, bar_h - 1, width, bar_h))
        if self.steps:
            # Under the bar the guide's steps stand on the page's own colour.
            picture.paste(art._rgb(theme.BG), (0, bar_h, width, height))
        brand = self.brand_picture
        bx, by = px(self.EDGE), (bar_h - brand.height) // 2
        picture.paste(brand, (bx, by), brand)
        # A dialog draws the window behind it from the widgets (snapshot.py): the bar as it looks now (_paint puts the
        # page's rule on a copy of it).
        self._picture = picture
        self.opendmt3_picture = picture
        self._image = ImageTk.PhotoImage(picture, master=self)
        self.create_image(0, 0, image=self._image, anchor="nw")
        # The menu after the mark, a step smaller where the window is too narrow for it in one line.
        x = bx + brand.width + px(self.AFTER_MARK)
        font, pad = self.ui.fonts.nav, px(self.NAME_PAD)
        need = sum(font.measure(words) + 2 * pad for _, words in self.nav)
        if x + need + px(self.EDGE) > width:
            font, pad = self.ui.fonts.nav_small, px(8)
        self.boxes = {}
        for key, words in self.nav:
            w = font.measure(words) + 2 * pad
            self.boxes[key] = (x, 0, x + w, bar_h)
            self.create_text(x + w // 2, bar_h // 2, text=words, font=font, tags=("name", "n-" + key))
            for event, handler in (("<Enter>", lambda e, k=key: self._hover(k)), ("<Leave>", lambda e: self._hover(None)),
                                   ("<Button-1>", lambda e, k=key: self._press(k))):
                self.tag_bind("n-" + key, event, handler)
            x += w
        if self.steps:
            self._draw_steps(width)
        self._paint()

    def _draw_steps(self, width):
        """The guide's steps across under the bar, as OpenDMTQ's: each step's number big beside its name, a rule under
        both; the step on show and the steps taken in the guide's blue, the steps to come grey."""
        px, scale = self.ui.px, self.ui.scale
        left, right = px(self.EDGE), width - px(self.EDGE)
        top = px(self.HEIGHT) + px(12)
        gap = px(10)
        cell = (right - left - (len(self.steps) - 1) * gap) / float(len(self.steps))
        # Each number's picture, kept while it shows (Tk drops a picture the moment Python forgets it).
        self._numerals = []
        for i, name in enumerate(self.steps):
            done, now = i < self.step, i == self.step
            x = left + i * (cell + gap)
            colour = theme.BLUE_HI if (done or now) else theme.STEP_TO_COME
            picture = art.numeral(str(i + 1), colour, scale)
            image = ImageTk.PhotoImage(picture, master=self)
            self._numerals.append(image)
            self.create_image(int(x), top, image=image, anchor="nw")
            # The number on the bar's own picture too, for a dialog's view of the window (snapshot.py).
            self._picture.paste(picture, (int(x), int(top)), picture)
            # The name beside the number, standing on the number's foot.
            self.create_text(x + picture.width + px(8), top + picture.height, text=name, anchor="sw",
                             font=self.ui.fonts.step,
                             fill=theme.TEXT if now else (theme.MUTED if done else theme.FAINT), tags=("step",))
            # The rule under the step: thicker for the one on show.
            thick = px(3) if now else px(2)
            y = top + picture.height + px(8)
            self.create_rectangle(x, y, x + cell, y + thick, width=0,
                                  fill=theme.BLUE_HI if (done or now) else theme.LINE)
            self._picture.paste(art._rgb(theme.BLUE_HI if (done or now) else theme.LINE),
                                (int(x), int(y), int(x + cell), int(y + thick)))

    def _paint(self):
        """Each name's colour, the rule under the page on show (its section's colour), and the keyboard's ring."""
        px = self.ui.px
        self.delete("rule", "ring")
        picture = getattr(self, "_picture", None)
        if picture is not None:
            # A dialog's view of the window (snapshot.py): the bar with the page's rule on it.
            self.opendmt3_picture = picture.copy()
        for key, _words in self.nav:
            on = key == self.current
            self.itemconfigure("n-" + key, fill=theme.TEXT if on or key == self.hover else theme.MUTED)
            if on and key in self.boxes:
                x0, _y0, x1, y1 = self.boxes[key]
                rule = (x0 + px(8), y1 - px(3), x1 - px(8), y1)
                self.create_rectangle(*rule, width=0, tags=("rule",), fill=theme.section_colours(key)["accent"])
                if picture is not None:
                    self.opendmt3_picture.paste(art._rgb(theme.section_colours(key)["accent"]), rule)
        if self.ring in self.boxes:
            x0, y0, x1, y1 = self.boxes[self.ring]
            inset = px(12)
            self.create_rectangle(x0 + px(2), y0 + inset, x1 - px(2), y1 - inset, outline=theme.CYAN,
                                  width=max(1, px(2)), tags=("ring",))

    def _hover(self, key):
        self.hover = key
        # The hand over a name, the arrow elsewhere on the bar.
        self.configure(cursor="hand2" if key else "")
        self._paint()

    def _press(self, key):
        if key is not None and self.on_nav:
            self.on_nav(key)

    def _focused(self, on):
        """The keyboard came: the ring on the page on show (or the first name); it went: the ring goes."""
        keys = [key for key, _ in self.nav]
        if on and keys:
            if self.ring not in keys:
                self.ring = self.current if self.current in keys else keys[0]
        else:
            self.ring = None
        self._paint()

    def _move(self, by, key):
        """The ring along the names; Tab past the last (Shift+Tab before the first) leaves the bar, as Tab does."""
        keys = [k for k, _ in self.nav]
        if not keys or self.ring not in keys:
            return None
        i = keys.index(self.ring) + by
        if 0 <= i < len(keys):
            self.ring = keys[i]
            self._paint()
            return "break"
        if key in ("<Left>", "<Right>"):
            # The arrows stay on the bar at its ends.
            return "break"
        return None

    def set_current(self, key):
        """The page on show: its name white, with its section's rule under it."""
        self.current = key
        self._paint()

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
        # What the window does when the area changes width (the head is drawn again for it).
        self.on_width = None
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
        if self.on_width is not None:
            # The head is drawn again for the new width (the window waits for a drag to settle).
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
        if wrap != now:
            # Only a real change: setting the same width again would still ask the box to lay itself out.
            widget.configure(wraplength=wrap)

    # Start narrow: a label that first asks for its whole line would widen its box, and the box's width would
    # then come from the label instead of the page. Narrow first, the box takes the page's width, then the
    # label grows into it.
    widget.configure(wraplength=ui.px(START_WRAP))
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
    words = text.upper() if ui.words.language == "en" else text
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
    # Its height (logical pixels): a page's buttons, and the smaller ones a card has at its title's right end (Check
    # again), which stand in the title tab's row as the site's small buttons stand in a table's.
    HEIGHTS = {"normal": 34, "small": 26}

    def __init__(self, parent, ui, text, command, kind="secondary", size="normal"):
        self.ui, self.bg, self.size = ui, parent.cget("bg"), size
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

    def set_text(self, text):
        """Show other words (the guide's last Next becomes PLAY): the button takes the width they need."""
        if text == self.words:
            return
        self.words = text
        fonts, px = self.ui.fonts, self.ui.px
        height = px(self.HEIGHTS[self.size])
        # The ends lean, so the words keep their distance from the slope, not from the box: half the lean more.
        side = px(14 if self.size == "normal" else 10) + int(height * art.LEAN) // 2
        width = fonts.body_bold.measure(text) + 2 * side
        self.configure(width=width, height=height)
        self.delete("all")
        self.faces = {state: art.button_face((width, height), 0, self.look, state, False, self.ui.scale, bg=self.bg)
                      for state in ("normal", "hover", "pressed", "disabled")}
        self.images = {state: ImageTk.PhotoImage(face, master=self) for state, face in self.faces.items()}
        # The faces with the focus ring are made the first time the button gets the focus.
        self.focused_faces, self.focused_images = None, None
        self.face = self.create_image(0, 0, image=self.images["normal"], anchor="nw")
        self.label = self.create_text(width // 2, height // 2, text=text, font=fonts.body_bold, anchor="center")
        self._paint(self.state if self.enabled else "disabled")

    def _focus(self, on):
        self.focused = on
        if on and self.focused_faces is None:
            width, height = int(self.cget("width")), int(self.cget("height"))
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
        """What a click does, for the keyboard and the tests."""
        if self.enabled and self.command:
            self.command()

    def enable(self, on):
        self.enabled = on
        self.configure(cursor="hand2" if on else "arrow")
        self._paint("normal" if on else "disabled")


class Toggle(tk.Label):
    """An on/off switch, on its parent's colour unless told; command(new_value) runs after each click."""

    def __init__(self, parent, ui, value, command, bg=None):
        bg = bg or parent.cget("bg")
        # A two-pixel ring in the background colour, cyan while it has the keyboard's focus.
        super().__init__(parent, bg=bg, cursor="hand2", bd=0, takefocus=1, highlightthickness=2,
                         highlightbackground=bg, highlightcolor=theme.CYAN)
        self.ui, self.value, self.command = ui, bool(value), command
        size = (ui.px(42), ui.px(23))
        # Both pictures are made once; a click only swaps them.
        colour = ui.section["fill"]
        self.pictures = {True: art.toggle(True, *size, colour=colour, knob=ui.section["ink"]),
                         False: art.toggle(False, *size)}
        self.images = {on: ImageTk.PhotoImage(p, master=parent) for on, p in self.pictures.items()}
        self.configure(image=self.images[self.value])
        # A dialog draws the window behind it from the widgets (snapshot.py): this is the switch's part.
        self.opendmt3_picture = self.pictures[self.value]
        self.bind("<Button-1>", lambda e: self.set(not self.value, notify=True))
        # The keyboard: Tab brings the focus (the cyan ring around it), Space or Enter flips it.
        for key in ("<space>", "<Return>", "<KP_Enter>"):
            self.bind(key, lambda e: self.set(not self.value, notify=True))

    def set(self, value, notify=False):
        self.value = bool(value)
        self.configure(image=self.images[self.value])
        self.opendmt3_picture = self.pictures[self.value]
        if notify:
            self.command(self.value)


class Segmented(tk.Label):
    """A row of choices of which one is on, set as the game sets its plates side by side (art.choice_row): the
    chosen one is the striped plate in the section's colour, as PLAY is striped.

    options: (key, words) pairs; command(key) runs after a click or an arrow key changes the choice.
    """

    def __init__(self, parent, ui, options, value, command, bg=None):
        # On its parent's colour unless told (a card's, or the page's).
        bg = bg or parent.cget("bg")
        # A two-pixel ring in the background colour, cyan while it has the keyboard's focus (as the switches).
        super().__init__(parent, bg=bg, cursor="hand2", bd=0, takefocus=1, anchor="nw", highlightthickness=2,
                         highlightbackground=bg, highlightcolor=theme.CYAN)
        self.ui, self.command, self.options, self.value = ui, command, list(options), value
        # The pictures are made as they are first shown: one for each (chosen, pointed at) pair.
        self.hover, self.edges, self.pictures = None, [], {}
        self.bind("<Button-1>", self._click)
        self.bind("<Motion>", lambda e: self._point(self._at(e.x, e.y)))
        self.bind("<Leave>", lambda e: self._point(None))
        # The keyboard: Tab brings the focus (the cyan ring), the arrows move the choice.
        self.bind("<Left>", lambda e: self._step(-1))
        self.bind("<Right>", lambda e: self._step(1))
        self._paint()

    def _paint(self):
        keys = [key for key, _ in self.options]
        look = (keys.index(self.value) if self.value in keys else None, self.hover)
        if look not in self.pictures:
            picture, self.edges = art.choice_row([words for _, words in self.options], look[0], look[1],
                                                 self.ui.section, self.ui.scale)
            self.pictures[look] = (picture, ImageTk.PhotoImage(picture, master=self))
        # A dialog draws the window behind it from the widgets (snapshot.py): this is the row's part.
        self.opendmt3_picture, image = self.pictures[look]
        self.configure(image=image)

    def _at(self, x, y):
        """Which choice a point of the label is on: the plates lean, so the line between two of them does too."""
        ring = int(self.cget("highlightthickness"))
        height = self.opendmt3_picture.height
        # The same point moved along the slope to half the height, where the edges were measured.
        x = (x - ring) + art.LEAN * ((y - ring) - height / 2)
        for i, (left, right) in enumerate(self.edges):
            # Up to the middle of the gap after a plate counts as that plate: no dead line between two choices.
            if x < right + self.ui.px(2) or i == len(self.edges) - 1:
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

    def set(self, value, notify=False):
        self.value = value
        self._paint()
        if notify:
            self.command(value)


class Slider(tk.Frame):
    """A slider from `low` to `high` (0 to 100 unless given) with its number beside it, `unit` after the number (" ms",
    say); command(value) runs when the drag ends."""

    def __init__(self, parent, ui, value, command, bg=None, width=320, low=0, high=100, unit=""):
        # On its parent's colour unless told (a card's, or the page's).
        bg = bg or parent.cget("bg")
        super().__init__(parent, bg=bg)
        self.ui, self.command, self.value = ui, command, int(value)
        # The range the track spans, and what the number says after itself.
        self.low, self.high, self.unit = int(low), int(high), unit
        self.w, self.h = ui.px(width), ui.px(26)
        self.colour = ui.section["accent"]
        self.knob_img = ImageTk.PhotoImage(art.knob(ui.px(18), ring=self.colour), master=parent)
        self.canvas = tk.Canvas(self, width=self.w, height=self.h, bg=bg, highlightthickness=0, cursor="hand2")
        self.canvas.pack(side="left")
        # Room for the largest number and the unit, so the label never changes width as the knob moves.
        room = max(4, len(str(self.high)) + 1) + len(unit)
        self.number = tk.Label(self, text="", font=ui.fonts.body_bold, fg=theme.TEXT, bg=bg, width=room, anchor="e")
        self.number.pack(side="left", padx=(ui.px(10), 0))
        self.canvas.bind("<Button-1>", self._drag)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", lambda e: self.command(self.value))
        self._draw()

    def _x(self, value):
        """Where a value sits on the track (the knob's centre stays inside the canvas)."""
        pad = self.ui.px(10)
        return pad + (self.w - 2 * pad) * (value - self.low) / float(max(1, self.high - self.low))

    def _drag(self, event):
        pad = self.ui.px(10)
        frac = (event.x - pad) / float(max(1, self.w - 2 * pad))
        # The nearest whole value on the track, never past either end.
        self.value = int(round(self.low + min(1.0, max(0.0, frac)) * (self.high - self.low)))
        self._draw()

    def _draw(self):
        c, mid = self.canvas, self.h // 2
        c.delete("all")
        thick = max(2, self.ui.px(4))
        # The empty track, then the filled part up to the knob.
        c.create_line(self._x(self.low), mid, self._x(self.high), mid, fill=theme.RAIL, width=thick, capstyle="round")
        c.create_line(self._x(self.low), mid, self._x(self.value), mid, fill=self.colour, width=thick, capstyle="round")
        c.create_image(self._x(self.value), mid, image=self.knob_img)
        self.number.configure(text=str(self.value) + self.unit)


class Select(ttk.Combobox):
    """A drop-down of (value, text) pairs; command(value) runs on a choice."""

    def __init__(self, parent, ui, options, value, command, width=24):
        self.options = list(options)
        super().__init__(parent, values=[t for _, t in self.options], state="readonly", width=width,
                         style="Dark.TCombobox", font=ui.fonts.body)
        self.command = command
        self.set_value(value)
        self.bind("<<ComboboxSelected>>", self._chosen)

    def set_value(self, value):
        for i, (v, _) in enumerate(self.options):
            if v == value:
                self.current(i)
                return
        if self.options:
            self.current(0)

    def _chosen(self, event):
        self.selection_clear()
        self.command(self.options[self.current()][0])


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
    # Every control's visible edge on one line: a switch and a row of choices keep their keyboard ring's room before
    # what shows, so the others are set in by as much.
    ring = 2
    inset = int(str(control.cget("highlightthickness"))) if isinstance(control, (Toggle, Segmented)) else 0
    control.grid(row=0, column=1, sticky="w", padx=(ring - inset, 0))
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
        super().__init__(parent, bg=theme.LINE, padx=1, pady=1)
        inside = tk.Frame(self, bg=theme.PANEL)
        inside.pack(fill="both", expand=True)
        top = ui.px(pad - 2)
        # The tab's row: the tab at its left, the card's action at its right end (nothing until a page puts one).
        self.head = tk.Frame(inside, bg=theme.PANEL)
        self.head.pack(fill="x")
        self.tab = None
        if title:
            words = title.upper() if ui.words.language == "en" else title
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
        # The cut: a small picture over the square corner, the page's colour beyond it and the seam along it.
        cut = ui.px(self.CUT)
        picture = art.corner(cut, theme.PANEL, outside, seam=theme.LINE)
        self._corner = ImageTk.PhotoImage(picture, master=self)
        corner = tk.Label(self, image=self._corner, bd=0, highlightthickness=0, bg=outside)
        # A dialog draws the window behind it from the widgets (snapshot.py): the corner as it looks.
        corner.opendmt3_picture = picture
        corner.place(relx=1.0, x=-cut, y=0, width=cut, height=cut)

    def action(self, text, command, kind="secondary"):
        """What the card does, as a small button at the right end of its tab's row (OpenDMTQ's Check again)."""
        button = Button(self.head, self.ui, text, command, kind=kind, size="small")
        button.pack(side="right", padx=(0, self.head_pad[0]), pady=(self.head_pad[1], 0))
        return button


class Lamp(tk.Label):
    """A small leaning light beside a line (art.lamp): filled when lit, an outline when not. `drop` is how far
    below a line's top it sits to stand in the middle of the first line of text."""

    def __init__(self, parent, ui, colour, lit=True, bg=None):
        # On its parent's colour unless told (a card's, or the page's).
        bg = bg or parent.cget("bg")
        super().__init__(parent, bg=bg, bd=0, highlightthickness=0)
        self.ui = ui
        self.show(colour, lit)
        self.drop = max(0, (ui.fonts.body.metrics("linespace") - self.opendmt3_picture.height + 1) // 2)

    def show(self, colour, lit=True):
        # A dialog draws the window behind it from the widgets (snapshot.py): this is the lamp's part.
        self.opendmt3_picture = art.lamp(colour, lit, self.ui.scale)
        self.image = ImageTk.PhotoImage(self.opendmt3_picture, master=self)
        self.configure(image=self.image)


def check_line(parent, ui, state, text, action_text=None, action=None, bg=None):
    """A ready-check line: a lamp (lime: fine; an amber outline: will change; pink: a problem), the words, and an
    optional link, on its parent's colour unless told."""
    bg = bg or parent.cget("bg")
    row = tk.Frame(parent, bg=bg)
    colour, lit = {"ok": (theme.LIME, True), "change": (theme.AMBER, False), "bad": (theme.PINK, True)}[state]
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
    words.pack(side="left", fill="x", padx=(ui.px(9), 0))
    return row


def check_note(parent, ui, text, problem=False, bg=None):
    """What stands under a ready-check line, small, under the line's words (past its lamp): why a failed line stops
    PLAY, in the error colour, or a note on a line that is fine, in the hint colour. On its parent's colour unless
    told."""
    bg = bg or parent.cget("bg")
    row = tk.Frame(parent, bg=bg)
    # As far in as the line's words: the lamp's width and the gap after it.
    indent = art.lamp(theme.MUTED, True, ui.scale).width + ui.px(9)
    words = label(row, ui, text, font=ui.fonts.small, fg=theme.PINK if problem else theme.MUTED, bg=bg, wrap_margin=0)
    words.pack(fill="x", padx=(indent, 0))
    return row


def entry(parent, ui, width=18, secret=False):
    """A text field in the theme: dark inside, a blue edge while typing."""
    field = tk.Entry(parent, width=width, font=ui.fonts.body, bg=theme.FIELD, fg=theme.TEXT, insertbackground=theme.TEXT,
                     relief="flat", highlightthickness=1, highlightbackground=theme.LINE, highlightcolor=theme.CYAN,
                     show="\u2022" if secret else "")
    return field
