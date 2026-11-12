"""Dialogs drawn inside the launcher's window, in the shape of the game's own popups.

The game asks and tells in a panel over its dimmed screen, its title on a tab hanging from the panel's top edge.
The launcher does the same instead of Windows' message boxes: the window behind is blurred and dimmed (drawn from
its widgets by snapshot.py, so nothing is read from the screen), and the tab and the main button take the colour
of what the dialog is about: pink to remove something for good, amber for a big change PLAY can redo, blue to
tell. Buttons say what they do. Esc cancels, Enter presses the button with the keyboard's ring, Tab and the arrow
keys move that ring.

ask() and tell() wait for the answer like a message box. A window of its own (when the launcher cannot open, so
there is no window to draw over) comes from standalone().
"""

import logging
import re
import sys
import tkinter as tk

from PIL import ImageTk

from opendmt3.core import safety
from opendmt3.client import art, snapshot, theme

log = logging.getLogger("opendmt3.launcher")

# Each kind: its colour (the light along the track of work under way), its tab (top and bottom of the gradient;
# dark words on it) and the look of its main button (art.BUTTON_LOOKS).
KINDS = {
    "danger": {"accent": theme.PINK, "tab": ("#ff7ab8", "#f0388f"), "button": "danger"},
    "warn": {"accent": theme.AMBER, "tab": ("#ffcd70", "#f5a52a"), "button": "warn"},
    "info": {"accent": theme.BLUE_HI, "tab": ("#8fb0ff", "#5b8cff"), "button": "info"},
    "error": {"accent": theme.PINK, "tab": ("#ff7ab8", "#f0388f"), "button": "info"},
}

# Sizes in pixels at 100 % scaling.
WIDTH = 464         # the panel, when the window has room
MARGIN = 24         # the least room between the panel and the window's edge
PAD = 38            # inside the panel, left and right of the text
TAB = 30            # the title tab's height
SLANT = 14          # how far the tab's sides lean in
BUTTON = 40         # a button's height
BUTTON_MIN = 132    # a button's least width
GAP = 12            # between two buttons
RISE = 14           # how far the panel rises as it appears
FRAMES = 8          # the rise, one frame every 16 ms


def _motion_on():
    """False when Windows is set to show no animations (Settings > Accessibility > Animation effects)."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        on = ctypes.c_int(1)
        # SPI_GETCLIENTAREAANIMATION
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(on), 0)
        return bool(on.value)
    except (AttributeError, OSError):
        return True


def path_breaks(font, text, width):
    """`text` with a line break inside each word wider than `width` (a path has no spaces), after one of its folders'
    separators: a path then breaks between its folders, never inside a name that fits on a line."""
    lines = []
    for line in text.split("\n"):
        words = []
        for word in line.split(" "):
            if font.measure(word) <= width:
                words.append(word)
                continue
            # The separator stays at the end of the part before it.
            parts = re.split(r"(?<=[\\/])", word)
            chunks, chunk = [], ""
            for part in parts:
                if chunk and font.measure(chunk + part) > width:
                    chunks.append(chunk)
                    chunk = part
                else:
                    chunk += part
            chunks.append(chunk)
            words.append("\n".join(chunks))
        lines.append(" ".join(words))
    return "\n".join(lines)


def balanced_width(font, text, width):
    """The narrowest wrap width that keeps `text` on as few lines as `width` does, so the lines come out even and
    no word is left alone on the last one (as the web's text-wrap: pretty)."""
    def lines(w):
        return len(snapshot.wrap(font, text, w))
    count = lines(width)
    if count <= 1:
        return width
    # Never narrower than the longest word (a path has no spaces: Tk would cut it between letters).
    longest = max([font.measure(word) for word in text.split()] or [0])
    low, high = min(width, max(width // 2, longest + 4)), width
    while low < high:
        mid = (low + high) // 2
        if lines(mid) <= count:
            high = mid
        else:
            low = mid + 1
    # A few pixels of room: Tk measures a line the same way, but never wraps one that fits exactly.
    return min(width, low + 4)


class Dialog:
    """One dialog over `root`. buttons: [(words, value, look)]; `default` has the ring at first; `cancel` is the
    value Esc, closing the window or a rebuild of the window give. `window` draws the scene behind for a size
    (the launcher's own window by default)."""

    def __init__(self, root, ui, kind, title, message, detail=None, buttons=(), default=0, cancel=None,
                 window=None, on_close=None, progress=False, field=None, link=None, status=None):
        self.root, self.ui = root, ui
        self.style = KINDS[kind]
        self.title, self.message, self.detail = title, message, detail
        self.buttons = list(buttons)
        # A text field in the panel (a password: its words hidden), whose words the main button takes (value).
        self.field, self.value, self._entry = field, "", None
        # A line under the words that does something when clicked: (words, function), Another folder... and the like.
        self.link = link
        # Work under way that knows how far it is: the share done (None: not known yet, the light sweeps) and a line
        # under the track (what is done, the time left), the first one drawn with the dialog itself.
        self.fraction, self.status = None, status or ""
        self.focus, self.hover, self.pressed = default, None, None
        self.cancel_value, self.result, self.closed = cancel, cancel, False
        self.window = window or (lambda width, height: snapshot.render(self.root))
        self.on_close = on_close
        # A dialog for work under way shows a moving light along a track where the buttons would be.
        self.progress = progress
        self.done = tk.BooleanVar(root, False)
        self.size = None
        self.generation = 0
        self._jobs = set()
        self._resize_job = None
        self._before = root.focus_get()
        self.canvas = tk.Canvas(root, highlightthickness=0, bd=0, bg=theme.BG, takefocus=1)
        # Left out of the window's picture: the dialog never draws itself behind itself.
        self.canvas.opendmt3_skip = True
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        # Above every other widget of the window (a Canvas's own lift() moves items, not the widget).
        tk.Misc.tkraise(self.canvas)
        self._bind()
        root.update_idletasks()
        self._draw(rise=_motion_on())
        self._take_input()

    # --------------------------------------------------------------------------------------------- drawing

    def _layout(self, width, height):
        """Where everything goes, in the panel's own pixels; the text items are made here to measure them."""
        px, fonts, c = self.ui.px, self.ui.fonts, self.canvas
        panel_w = max(px(280), min(px(WIDTH), width - 2 * px(MARGIN)))
        text_w = panel_w - 2 * px(PAD)
        tab_words = self.title.upper() if self.ui.words.language == "en" else self.title
        tab_w = min(panel_w - 2 * px(20), fonts.dialog_tab.measure(tab_words) + 2 * px(26) + 2 * px(SLANT))
        # The question stands right under its tab: nothing between the two.
        y = px(TAB) + px(30)
        # A path wider than the panel breaks between its folders (path_breaks), then the lines are evened out.
        words = path_breaks(fonts.dialog_title, self.message, text_w)
        message = c.create_text(panel_w // 2, y, text=words, font=fonts.dialog_title, fill=theme.TEXT,
                                width=balanced_width(fonts.dialog_title, words, text_w), justify="center",
                                anchor="n", tags=("card", "words"))
        y = c.bbox(message)[3]
        detail = None
        if self.detail:
            y += px(9)
            words = path_breaks(fonts.body, self.detail, text_w)
            detail = c.create_text(panel_w // 2, y, text=words, font=fonts.body, fill=theme.MUTED,
                                   width=balanced_width(fonts.body, words, text_w), justify="center",
                                   anchor="n", tags=("card", "words"))
            y = c.bbox(detail)[3]
        link = None
        if self.link:
            # The link right under the words it is about, in the section's light.
            y += px(10)
            link = c.create_text(panel_w // 2, y, text=self.link[0] + " \u203a", font=fonts.body_bold,
                                 fill=self.style["accent"], anchor="n", tags=("card", "words", "link"))
            y = c.bbox(link)[3]
        field = None
        if self.field:
            y += px(16)
            field = (px(PAD), y, panel_w - 2 * px(PAD), px(34))
            y += px(34)
        y += px(28)
        if self.progress:
            track = (px(PAD), y + px(BUTTON) // 2 - px(3), panel_w - px(PAD), y + px(BUTTON) // 2 + px(3))
            y += px(BUTTON)
            status = None
            if self.status or self.fraction is not None:
                # What is done and the time left, small under the track.
                status = c.create_text(panel_w // 2, y - px(6), text=self.status or " ", font=fonts.small,
                                       fill=theme.MUTED, anchor="n", tags=("card", "words", "status"))
                y = c.bbox(status)[3] + px(6)
            y += px(22)
            buttons, button_w = [], 0
            if self.buttons:
                buttons, button_w = self._button_row(panel_w, y)
                y += px(BUTTON) + px(28)
            self._tab_room = tab_w - 2 * px(SLANT)
            return {"panel": (panel_w, y), "tab": (tab_w, tab_words), "message": message, "detail": detail,
                    "buttons": buttons, "button_w": button_w, "track": track, "field": field, "link": link}
        buttons, button_w = self._button_row(panel_w, y)
        y += px(BUTTON) + px(28)
        self._tab_room = tab_w - 2 * px(SLANT)
        return {"panel": (panel_w, y), "tab": (tab_w, tab_words), "message": message, "detail": detail,
                "buttons": buttons, "button_w": button_w, "field": field, "link": link}

    def _button_row(self, panel_w, y):
        """The buttons side by side, centred, at height y: their boxes' left tops, and their width."""
        px, fonts = self.ui.px, self.ui.fonts
        count = len(self.buttons)
        widest = max([fonts.dialog_button.measure(b[0]) for b in self.buttons] or [0])
        # The buttons lean: their words keep clear of both slopes.
        button_w = max(px(BUTTON_MIN), widest + 2 * (px(16) + int(px(BUTTON) * art.LEAN)))
        room = panel_w - 2 * px(22)
        button_w = min(button_w, (room - (count - 1) * px(GAP)) // max(1, count))
        row_w = count * button_w + (count - 1) * px(GAP)
        return [((panel_w - row_w) // 2 + i * (button_w + px(GAP)), y) for i in range(count)], button_w

    def _draw(self, rise=False):
        """Draw the whole dialog for the canvas's present size (again after the window is resized)."""
        c, px, scale = self.canvas, self.ui.px, self.ui.scale
        width, height = max(1, self.root.winfo_width()), max(1, self.root.winfo_height())
        self.size = (width, height)
        # A rise still running belongs to the old drawing: it stops moving anything.
        self.generation += 1
        c.delete("all")
        lay = self._layout(width, height)
        panel_w, panel_h = lay["panel"]
        # A little above the middle, where a reader looks first; never off the top.
        x0, y0 = (width - panel_w) // 2, max(px(12), int((height - panel_h) * 0.44))
        behind = self.window(width, height)
        if behind.size != (width, height):
            behind = behind.resize((width, height))
        box = (x0, y0, panel_w, panel_h)
        scene, soft = art.dialog_scene(behind, box, scale)
        tab_w, tab_words = lay["tab"]
        panel = art.dialog_panel(soft, box, (tab_w, px(TAB), px(SLANT)) + self.style["tab"], scale)
        self._scene, self._panel = ImageTk.PhotoImage(scene, master=c), ImageTk.PhotoImage(panel, master=c)
        c.create_image(0, 0, image=self._scene, anchor="nw", tags=("scene",))
        c.create_image(0, 0, image=self._panel, anchor="nw", tags=("card", "panel"))
        c.create_text(panel_w // 2, px(TAB) // 2, text=tab_words, font=self.ui.fonts.dialog_tab,
                      fill=theme.INK, tags=("card", "words"))
        # The buttons: one picture for each look, drawn over the panel's own pixels.
        margin = max(5, int(round(6 * scale)))
        self._images, self._items, self._boxes = [], [], []
        for i, ((words, _value, look), (bx, by)) in enumerate(zip(self.buttons, lay["buttons"])):
            under = panel.crop((bx - margin, by - margin, bx + lay["button_w"] + margin, by + px(BUTTON) + margin))
            images = {(state, ring): ImageTk.PhotoImage(
                art.button_face(under.size, margin, look, state, ring, scale, under=under), master=c)
                for state in ("normal", "hover", "pressed") for ring in (False, True)}
            tag = "button%d" % i
            picture = c.create_image(bx - margin, by - margin, image=images[("normal", False)], anchor="nw",
                                     tags=("card", tag))
            c.create_text(bx + lay["button_w"] // 2, by + px(BUTTON) // 2, text=words,
                          font=self.ui.fonts.dialog_button, fill=art.BUTTON_LOOKS[look]["text"],
                          tags=("card", tag, "words"))
            self._images.append(images)
            self._items.append(picture)
            self._boxes.append((bx, by, bx + lay["button_w"], by + px(BUTTON)))
            for event, handler in (("<Enter>", self._enter), ("<Leave>", self._leave),
                                   ("<ButtonPress-1>", self._press), ("<ButtonRelease-1>", self._release)):
                c.tag_bind(tag, event, lambda e, i=i, h=handler: h(i, e))
        if lay.get("track"):
            self._track(lay["track"])
        if lay.get("link") is not None:
            c.tag_bind("link", "<Enter>", lambda e: c.configure(cursor="hand2"))
            c.tag_bind("link", "<Leave>", lambda e: c.configure(cursor=""))
            c.tag_bind("link", "<ButtonRelease-1>", lambda e: self.link[1]())
        if lay.get("field") is not None:
            self._place_field(lay["field"])
        c.tag_raise("words")
        self.origin = (x0, y0)
        self.panel_size = (panel_w, panel_h)
        c.move("card", x0, y0)
        for i in range(len(self.buttons)):
            self._paint(i)
        if rise:
            c.move("card", 0, px(RISE))
            self._rise(self.generation, 0, px(RISE))

    def _place_field(self, box):
        """The text field, a real Tk field over the panel (its words typed, hidden for a password)."""
        from opendmt3.client import widgets
        x, y, width, height = box
        if self._entry is None or not self._entry.winfo_exists():
            self._entry = widgets.entry(self.canvas, self.ui, secret=self.field == "secret")
            # Enter in the field presses the main button; Esc cancels, as everywhere in the dialog.
            self._entry.bind("<Return>", lambda e: self.choose(len(self.buttons) - 1))
            self._entry.bind("<KP_Enter>", lambda e: self.choose(len(self.buttons) - 1))
            self._entry.bind("<Escape>", lambda e: self.close(self.cancel_value))
            self._entry.insert(0, self.value)
        self._window = self.canvas.create_window(x, y, window=self._entry, anchor="nw", width=width, height=height,
                                                 tags=("card", "field"))

    def entry(self):
        """The dialog's text field (None without one)."""
        return self._entry

    def set_progress(self, fraction, status):
        """How far the work is (0 to 1, or None while not known) and the line under the track; on the window's
        thread."""
        self.fraction, self.status = fraction, status
        if self.closed or not self.canvas.winfo_exists():
            return
        items = self.canvas.find_withtag("status")
        if not items and status:
            # The first line under the track: the panel grows by a line, so it is drawn again.
            self._draw()
            return
        for item in items:
            self.canvas.itemconfigure(item, text=status or " ")
        self._fill()

    def _fill(self):
        """The share done as a lit bar along the track (the sweeping light while it is not known)."""
        c = self.canvas
        tracks = c.find_withtag("track")
        if not tracks or self.fraction is None:
            return
        left, top, right, bottom = c.coords(tracks[0])
        for item in c.find_withtag("fill"):
            c.delete(item)
        end = left + (right - left) * max(0.0, min(1.0, self.fraction))
        c.create_rectangle(left, top, end, bottom, fill=self.style["accent"], width=0, tags=("card", "fill"))
        # The sweeping light stands down once the share is known.
        for item in getattr(self, "_slices", []):
            c.coords(item, left, top, left, bottom)

    def _track(self, track):
        """The progress track and its light: thin slices fading in and out, moved along every frame."""
        c = self.canvas
        left, top, right, bottom = track
        c.create_rectangle(left, top, right, bottom, fill=theme.RAIL, width=0, tags=("card", "track"))
        accent, rail = art._rgb(self.style["accent"]), art._rgb(theme.RAIL)
        self._slices = []
        count = 24
        for i in range(count):
            # Brightest in the middle of the light, the track's own colour at its ends.
            k = 1 - abs((i + 0.5) / count * 2 - 1)
            colour = "#%02x%02x%02x" % tuple(int(r + (a - r) * k) for a, r in zip(accent, rail))
            self._slices.append(c.create_rectangle(left, top, left, bottom, fill=colour, width=0, tags=("card",)))
        self._light = {"at": 0.0}
        self._sweep(self.generation)

    def _sweep(self, generation):
        """Move the light one step (it runs only while work is going on, and stops with the dialog)."""
        if self.closed or generation != self.generation or not self.canvas.winfo_exists():
            return
        if self.fraction is not None:
            # The share done is drawn instead (_fill); the light waits, still running, in case it is not known again.
            self._fill()
            self._later(100, self._sweep, generation)
            return
        # Where the track is now (the card may still be rising).
        left, top, right, bottom = self.canvas.coords(self.canvas.find_withtag("track")[0])
        span = right - left
        width = span * 0.34
        self._light["at"] = (self._light["at"] + span / 70.0) % (span + width)
        start = left - width + self._light["at"]
        step = width / len(self._slices)
        for i, item in enumerate(self._slices):
            x0 = max(left, min(right, start + i * step))
            x1 = max(left, min(right, start + (i + 1) * step + 1))
            self.canvas.coords(item, x0, top, x1, bottom)
        self._later(16, self._sweep, generation)

    def _rise(self, generation, frame, offset):
        """Ease the panel up into place, quickly at first and slowing at the end."""
        if self.closed or generation != self.generation or not self.canvas.winfo_exists():
            return
        frame += 1
        t = frame / float(FRAMES)
        left = int(round(self.ui.px(RISE) * (1 - t) ** 3))
        self.canvas.move("card", 0, left - offset)
        if frame < FRAMES:
            self._later(16, self._rise, generation, frame, left)

    def _paint(self, i):
        look = "pressed" if self.pressed == i else ("hover" if self.hover == i else "normal")
        self.canvas.itemconfigure(self._items[i], image=self._images[i][(look, self.focus == i)])

    # ------------------------------------------------------------------------------------------- input

    def _bind(self):
        c = self.canvas
        # Work under way (a progress dialog) cannot be cancelled from the keyboard.
        c.bind("<Escape>", lambda e: None if self.progress and not self.buttons else self.close(self.cancel_value))
        for key in ("<Return>", "<KP_Enter>", "<space>"):
            c.bind(key, lambda e: self.choose(self.focus))
        for key, step in (("<Tab>", 1), ("<Right>", 1), ("<Shift-Tab>", -1), ("<ISO_Left_Tab>", -1), ("<Left>", -1)):
            c.bind(key, lambda e, s=step: self.move(s))
        # The page underneath must not scroll while the dialog is up.
        for wheel in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            c.bind(wheel, lambda e: "break")
        c.bind("<Configure>", self._resized)
        c.bind("<Destroy>", self._destroyed)

    def _take_input(self):
        """Keyboard and mouse go to the dialog only, once it is on screen."""
        if self.closed or not self.canvas.winfo_exists():
            return
        if not self.canvas.winfo_viewable():
            self._later(20, self._take_input)
            return
        try:
            self.canvas.grab_set()
        except tk.TclError:
            # Another program holds the grab for a moment; try again shortly.
            self._later(50, self._take_input)
        if self._entry is not None and self._entry.winfo_exists():
            # A dialog that asks for words takes them at once.
            self._entry.focus_set()
        else:
            self.canvas.focus_set()

    def _later(self, ms, fn, *args):
        """A timer on the dialog's canvas, remembered so closing the dialog cancels it."""
        job = self.canvas.after(ms, lambda: (self._jobs.discard(job), fn(*args)))
        self._jobs.add(job)
        return job

    def _cancel_jobs(self):
        for job in list(self._jobs):
            try:
                self.canvas.after_cancel(job)
            except tk.TclError:
                pass
        self._jobs.clear()

    def move(self, step):
        """Move the ring to the next or the previous button."""
        if self.buttons:
            old, self.focus = self.focus, (self.focus + step) % len(self.buttons)
            self._paint(old)
            self._paint(self.focus)
        return "break"

    def _enter(self, i, event):
        self.hover = i
        self.canvas.configure(cursor="hand2")
        self._paint(i)

    def _leave(self, i, event):
        self.hover = None
        self.canvas.configure(cursor="")
        self._paint(i)

    def _press(self, i, event):
        self.pressed = i
        self._paint(i)

    def _release(self, i, event):
        """A click counts when it ends over the same button (drag off to change your mind)."""
        self.pressed = None
        x, y = self.canvas.canvasx(event.x) - self.origin[0], self.canvas.canvasy(event.y) - self.origin[1]
        left, top, right, bottom = self._boxes[i]
        if left <= x < right and top <= y < bottom:
            self.choose(i)
        elif not self.closed:
            self._paint(i)

    def choose(self, i):
        if 0 <= i < len(self.buttons):
            if self._entry is not None and self._entry.winfo_exists():
                # What was typed, for the caller (a password): taken before the field goes with the dialog.
                self.value = self._entry.get()
            self.close(self.buttons[i][1])
        return "break"

    # ----------------------------------------------------------------------------------------- closing

    def close(self, value):
        if self.closed:
            return
        self.closed, self.result = True, value
        self._cancel_jobs()
        try:
            self.canvas.grab_release()
            self.canvas.destroy()
        except tk.TclError:
            pass
        try:
            self.done.set(True)
            if self._before is not None and self._before.winfo_exists():
                self._before.focus_set()
        except tk.TclError:
            # The window itself is going.
            pass
        if self.on_close:
            self.on_close(value)

    def _destroyed(self, event):
        """The window was rebuilt or closed under the dialog: that answers as a cancel."""
        if event.widget is self.canvas and not self.closed:
            self.closed = True
            self._cancel_jobs()
            try:
                self.done.set(True)
            except tk.TclError:
                pass

    def _resized(self, event):
        # Before the first drawing (self.size unset) the size is about to be drawn anyway.
        if self.closed or self.size is None or (event.width, event.height) == self.size:
            return
        if self._resize_job is not None:
            self.canvas.after_cancel(self._resize_job)
        # Drawn again once the size settles (a drag sends many sizes).
        self._resize_job = self._later(80, self._redraw)

    def _redraw(self):
        self._resize_job = None
        if not self.closed and self.canvas.winfo_exists():
            self._draw()

    def set_words(self, message=None, detail=None):
        """Say something else in the open dialog (a folder chosen with its link, a password that did not open the
        archive): it is drawn again for the new words."""
        if message is not None:
            self.message = message
        if detail is not None:
            self.detail = detail
        if not self.closed and self.canvas.winfo_exists():
            self._draw()

    def wait(self):
        """Wait (the window keeps working) until the dialog is answered; returns the answer."""
        if not self.closed:
            try:
                self.root.wait_variable(self.done)
            except tk.TclError:
                pass
        return self.result

    # ------------------------------------------------------------------------------------------ checks

    def layout_problems(self):
        """Text or buttons outside the panel, text over the buttons, the panel outside the window: for the UI
        tests, which measure the dialog like the pages."""
        c, problems = self.canvas, []
        x0, y0 = self.origin
        panel = (x0, y0, x0 + self.panel_size[0], y0 + self.panel_size[1])
        width, height = self.size
        if panel[0] < 0 or panel[1] < 0 or panel[2] > width or panel[3] > height:
            problems.append("dialog: the panel does not fit the window (%r in %dx%d)" % (panel, width, height))
        tops = [y0 + b[1] for b in self._boxes]
        for item in c.find_withtag("words"):
            box = c.bbox(item)
            text = c.itemcget(item, "text")[:40]
            if box[0] < panel[0] or box[2] > panel[2] or box[1] < panel[1] or box[3] > panel[3]:
                problems.append("dialog: text outside the panel: %r" % text)
            if "button" not in " ".join(c.gettags(item)) and tops and box[3] > min(tops):
                problems.append("dialog: text runs into the buttons: %r" % text)
        tab_words = self.title.upper() if self.ui.words.language == "en" else self.title
        if self.ui.fonts.dialog_tab.measure(tab_words) > self._tab_room:
            problems.append("dialog: the title does not fit its tab: %r" % tab_words)
        for i, (left, top, right, bottom) in enumerate(self._boxes):
            words = self.buttons[i][0]
            # Between the two slopes, less a little air on each side.
            lean = int((bottom - top) * art.LEAN)
            if self.ui.fonts.dialog_button.measure(words) > right - left - 2 * (lean + self.ui.px(6)):
                problems.append("dialog: button words do not fit: %r" % words)
        return problems


def _buttons(words, kind, confirm, cancel):
    return [(cancel or words("common.cancel"), False, "neutral"), (confirm, True, KINDS[kind]["button"])]


def ask(app, kind, title, message, detail, confirm, cancel=None):
    """Ask before doing something; True when the player chose `confirm`. Removing for good starts on Cancel, so
    Enter alone never removes anything; other questions start on their main button."""
    dialog = Dialog(app.root, app.ui, kind, title, message, detail, _buttons(app.words, kind, confirm, cancel),
                    default=0 if kind == "danger" else 1, cancel=False)
    app.dialog = dialog
    try:
        return bool(dialog.wait())
    finally:
        app.dialog = None


def choose(app, kind, title, message, detail, answers):
    """Ask a question with more than one way on: `answers` are [(words, value, look)] after Cancel. Returns the value
    chosen, or None for Cancel. It starts on Cancel, so Enter alone does nothing (as the OpenDMTQ PC client's)."""
    buttons = [(app.words("common.cancel"), None, "neutral")] + list(answers)
    dialog = Dialog(app.root, app.ui, kind, title, message, detail, buttons, default=0, cancel=None)
    app.dialog = dialog
    try:
        return dialog.wait()
    finally:
        app.dialog = None


def tell(app, kind, title, message, detail=None, ok=None):
    """Tell the player something that needs reading before going on (one button)."""
    dialog = Dialog(app.root, app.ui, kind, title, message, detail,
                    [(ok or app.words("common.ok"), True, KINDS[kind]["button"])], default=0, cancel=True)
    app.dialog = dialog
    try:
        dialog.wait()
    finally:
        app.dialog = None


def window_root(title="openDMT3", language="en"):
    """A window of its own for dialogs, when there is no launcher window to draw over: (root, ui)."""
    safety.refuse_windows_in_tests("a dialog window")
    from opendmt3.client import i18n, widgets
    theme.register_fonts()
    root = tk.Tk()
    root.title(title)
    root.configure(bg=theme.BG)
    set_icon(root)
    scale = theme.scale_of(root)
    ui = widgets.Ui(root, theme.Fonts(root, language), scale, i18n.Words(language))
    px = ui.px
    width, height = px(WIDTH) + 2 * px(MARGIN) + px(40), px(400)
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry("%dx%d+%d+%d" % (width, height, (sw - width) // 2, (sh - height) // 3))
    root.resizable(False, False)
    # Shown once before a dialog is drawn, so the window has its real size to draw for.
    root.update()
    # The person just started it: it takes the keyboard, so Enter and Esc answer it at once.
    root.focus_force()
    return root, ui


def fit(root, ui, dialog):
    """Make a window of its own as tall as its dialog's panel, with the same room above and below."""
    px = ui.px
    height = dialog.panel_size[1] + 2 * px(MARGIN) + px(16)
    if height != root.winfo_height():
        root.geometry("%dx%d" % (root.winfo_width(), height))


def set_icon(root):
    """The window's own icon (the mark) instead of Tk's feather, in the title bar and on the taskbar."""
    try:
        root.opendmt3_icon = ImageTk.PhotoImage(art.mark(64), master=root)
        root.iconphoto(True, root.opendmt3_icon)
    except tk.TclError:
        pass


def window(kind, title, message, detail=None, buttons=(), default=0, cancel=None, language="en"):
    """A dialog in a window of its own, over the title screen's shards, for when the launcher cannot open its
    window. Returns (root, dialog); the window closes itself once the dialog is answered."""
    root, ui = window_root(language=language)
    dialog = Dialog(root, ui, kind, title, message, detail, buttons, default=default, cancel=cancel,
                    window=lambda w, h: art.shards(w, h, seed=29), on_close=lambda value: root.destroy())
    fit(root, ui, dialog)
    root.protocol("WM_DELETE_WINDOW", lambda: dialog.close(cancel))
    return root, dialog


def standalone(kind, title, message, detail=None, buttons=(), default=0, cancel=None, language="en"):
    """window() and wait for the answer: the chosen button's value (`cancel` when the window is closed)."""
    root, dialog = window(kind, title, message, detail, buttons, default, cancel, language)
    root.mainloop()
    return dialog.result


class PathDialog(Dialog):
    """A dialog with one path to type above its buttons (where a file is saved): the launcher's own Save dialog, in
    the shape of every other one, instead of Windows' file box. The path starts as given and is chosen whole when the
    dialog opens, so typing replaces it; Enter in it presses the main button, Esc cancels, Tab goes to the buttons."""

    # The room the path takes above the buttons, at 100 %: its label, its box, and the gap under it.
    FIELD = 70
    BOX = 36

    def __init__(self, root, ui, kind, title, message, detail, label, path, buttons, **kwargs):
        self.label, self.path = label, path
        # The box, made with the first drawing and kept across the ones after (a resize draws everything again).
        self.entry = None
        # What was typed, read before the box goes with the dialog.
        self.typed = path
        super().__init__(root, ui, kind, title, message, detail, buttons, **kwargs)

    def _layout(self, width, height):
        """The base dialog's layout with the path's label and box where the buttons were, and the buttons under it."""
        lay = super()._layout(width, height)
        from opendmt3.client import widgets
        px, c = self.ui.px, self.canvas
        panel_w, panel_h = lay["panel"]
        top = lay["buttons"][0][1]
        lay["buttons"] = [(x, y + px(self.FIELD)) for x, y in lay["buttons"]]
        lay["panel"] = (panel_w, panel_h + px(self.FIELD))
        if self.entry is None:
            # In the launcher's own field look (widgets.entry), inside the dialog's canvas, so the dialog's grab takes it.
            self.entry = widgets.entry(c, self.ui, width=1)
            self.entry.insert(0, self.path)
            # Enter saves, Esc cancels, Tab goes to the buttons, as everywhere in the dialog.
            self.entry.bind("<Return>", lambda e: self.choose(len(self.buttons) - 1))
            self.entry.bind("<KP_Enter>", lambda e: self.choose(len(self.buttons) - 1))
            self.entry.bind("<Escape>", lambda e: self.close(self.cancel_value))
            self.entry.bind("<Tab>", lambda e: (self.canvas.focus_set(), "break")[1])
        c.create_text(px(PAD), top, text=self.label, font=self.ui.fonts.small, fill=theme.MUTED, anchor="nw",
                      tags=("card", "words"))
        # The box spans the text's width; its window moves with the card as the dialog rises.
        c.create_window(px(PAD), top + px(self.FIELD - self.BOX - 14), window=self.entry, anchor="nw",
                        width=panel_w - 2 * px(PAD), height=px(self.BOX), tags=("card", "field"))
        return lay

    def _take_input(self):
        """The dialog's own grab, then the typing goes to the path, chosen whole."""
        super()._take_input()
        if not self.closed and self.entry is not None and self.canvas.winfo_viewable():
            self.entry.focus_set()
            self.entry.select_range(0, "end")
            self.entry.icursor("end")

    def close(self, value):
        if not self.closed and self.entry is not None:
            try:
                # The box goes with the canvas: what it holds is read first.
                self.typed = self.entry.get()
            except tk.TclError:
                pass
        super().close(value)


def ask_path(app, kind, title, message, detail, label, path, confirm):
    """Ask for a path to save to, in the launcher's own dialog (PathDialog); the path typed (stripped) when the player
    chose `confirm`, None for Cancel. It starts on the main button, as a question that removes nothing does."""
    dialog = PathDialog(app.root, app.ui, kind, title, message, detail, label, path,
                        _buttons(app.words, kind, confirm, None), default=1, cancel=False)
    app.dialog = dialog
    try:
        return dialog.typed.strip() if dialog.wait() else None
    finally:
        app.dialog = None
