"""The launcher's boxes and the room round them, measured as a person sees them, as OpenDMTQ's launcher check measures
its own: two boxes that touch or overlap without meaning to (cards, fields, buttons, switches, the menu column's list
and its foot), words over a box they are no part of or right against one beside them, words closer to the edge of
the box they sit in than its padding, words lying on the page's own field outside any card, and gaps between boxes
stacked one after another that are off the launcher's spacing scale (SCALE). Also an opened drop-down's list
(check_list): on the screen whole, clear of its field, and over everything at its corners.

shots.py runs check() on every screen it measures, at every size and in both languages; it reads the widgets' places
from Tk, never from the code that put them there.

  problems = spacing.check(app.root, ui, name)       (a list of words, empty when all is well)
"""

import tkinter as tk

from opendmt3.client import widgets

# The launcher's spacing scale, in logical pixels: what one box keeps from the next beside or under it in a stack (a
# page's cards, a card's rows, a form's names and fields, the column's foot). 0 is two boxes that meet on purpose (a
# row's name over its own control's line).
SCALE = (0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 24, 28, 32, 40, 48)
# The least room between two boxes side by side or one under the other that are no part of each other: closer, they
# read as one box touching another.
LEAST_GAP = 4
# The least room between words and a box beside them on their line that they are no part of.
LEAST_TEXT_GAP = 4
# A card's padding at its sides and its foot (widgets.Card's 18 and 18 - 2 logical pixels); its top holds the tab,
# which hangs from the corner on purpose.
CARD_SIDES, CARD_FOOT = 18, 16
# The menu column's padding either side (widgets.Rail.EDGE) and under its foot (app.FOOT_UNDER).
RAIL_SIDES, RAIL_FOOT = 18, 20
# Any other band of its own colour: words at least this far from its edges.
BAND_SIDES, BAND_ENDS = 8, 4
# A pixel either way: Tk rounds a scaled size to whole pixels.
SLACK = 1


def _kind(widget):
    """What a widget is to the eye: "card", "field", "button", "control", "rail", "foot", "menu", "text", or None (a frame
    that only holds others, a picture of no box of its own)."""
    if isinstance(widget, widgets.Card):
        return "card"
    if isinstance(widget, widgets.Rail):
        return "rail"
    if isinstance(widget, widgets.RailList):
        return "menu"
    if getattr(widget, "opendmt3_under", None) is not None:
        # The column's foot (app.make_foot), placed over the column.
        return "foot"
    if isinstance(widget, (widgets.SecretField, widgets.Select)) or (
            isinstance(widget, tk.Entry) and not isinstance(widget.master, widgets.SecretField)):
        return "field"
    if isinstance(widget, widgets.Button):
        return "button"
    if isinstance(widget, (widgets.Toggle, widgets.Segmented)):
        return "control"
    if isinstance(widget, tk.Canvas) and isinstance(widget.master, widgets.Slider):
        return "control"
    if isinstance(widget, tk.Label) and str(widget.cget("text")).strip() and not str(widget.cget("image")):
        return "text"
    return None


def _inset(widget):
    """How far inside a widget's box what shows of it begins: its keyboard ring (a switch's, a row of choices', a link's
    and PLAY's: the words or the picture start inside it)."""
    try:
        # Tk answers a screen distance as its own object: in pixels through winfo_pixels.
        return widget.winfo_pixels(str(widget.cget("highlightthickness")))
    except (tk.TclError, ValueError, TypeError):
        return 0


def _shown_box(widget, origin):
    """The part of the widget's box that shows, in the window's pixels (left, top, right, bottom), or None: cut by every
    widget round it (the page area scrolled), and inset by its own ring."""
    x, y = widget.winfo_rootx() - origin[0], widget.winfo_rooty() - origin[1]
    inset = _inset(widget)
    box = [x + inset, y + inset, x + widget.winfo_width() - inset, y + widget.winfo_height() - inset]
    parent = widget.master
    while parent is not None:
        try:
            px, py = parent.winfo_rootx() - origin[0], parent.winfo_rooty() - origin[1]
            pw, ph = parent.winfo_width(), parent.winfo_height()
        except tk.TclError:
            break
        box = [max(box[0], px), max(box[1], py), min(box[2], px + pw), min(box[3], py + ph)]
        parent = parent.master
    if box[0] >= box[2] or box[1] >= box[3]:
        return None
    return tuple(box)


def _raw(widget, origin):
    """The widget's box as Tk places it, its ring and all, in the window's pixels."""
    x, y = widget.winfo_rootx() - origin[0], widget.winfo_rooty() - origin[1]
    return (x, y, x + widget.winfo_width(), y + widget.winfo_height())


def _whole(widget, origin):
    """The widget's whole box (not cut), inset by its ring, in the window's pixels."""
    x, y = widget.winfo_rootx() - origin[0], widget.winfo_rooty() - origin[1]
    inset = _inset(widget)
    return (x + inset, y + inset, x + widget.winfo_width() - inset, y + widget.winfo_height() - inset)


def _text_box(label, origin):
    """Where a label's words are: its box as wide as the words ask (a label packed to fill its line is wider than its
    words), from its left, its right or its middle as it is anchored."""
    box = _shown_box(label, origin)
    if box is None:
        return None
    words = label.winfo_reqwidth() - 2 * _inset(label)
    room = box[2] - box[0]
    if words >= room:
        return box
    anchor = str(label.cget("anchor"))
    if "w" in anchor:
        return (box[0], box[1], box[0] + words, box[3])
    if "e" in anchor:
        return (box[2] - words, box[1], box[2], box[3])
    middle = (box[0] + box[2]) // 2
    return (middle - words // 2, box[1], middle + words - words // 2, box[3])


def _all(root):
    """Every widget under `root`, without recursion."""
    found, stack = [], [root]
    while stack:
        widget = stack.pop()
        for child in widget.winfo_children():
            found.append(child)
            stack.append(child)
    return found


def _ancestors(widget):
    found, parent = [], widget.master
    while parent is not None:
        found.append(parent)
        parent = parent.master
    return found


def _inside(child, parent):
    return any(p is parent for p in _ancestors(child))


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _gap(a, b):
    """The room between two boxes that do not overlap: across when they share rows, down when they share columns, else
    None (diagonal: no line between them to measure)."""
    rows = a[1] < b[3] and b[1] < a[3]
    cols = a[0] < b[2] and b[0] < a[2]
    if rows:
        return max(b[0] - a[2], a[0] - b[2])
    if cols:
        return max(b[1] - a[3], a[1] - b[3])
    return None


def _name(widget):
    """A widget as a person would point at it, for the problems' words."""
    words = getattr(widget, "words", None)
    if isinstance(words, str) and words:
        return "%s %r" % (type(widget).__name__, words[:30])
    try:
        text = str(widget.cget("text"))
    except tk.TclError:
        text = ""
    if text.strip():
        return "%r" % text[:40]
    try:
        names = [str(c.cget("text")) for c in widget.master.winfo_children() if isinstance(c, tk.Label)]
    except tk.TclError:
        names = []
    named = next((n for n in names if n.strip()), "")
    return type(widget).__name__ + (" by %r" % named[:30] if named else "")


def _surface(widget, page_fields):
    """The box `widget`'s words sit on, and what it is: a card ("card"), the menu column or its foot ("rail"), the
    page's field outside any card ("page"), or a band whose colour differs from what is round it ("band"); (None, None)
    for words on the window itself."""
    parent = widget.master
    while parent is not None:
        if isinstance(parent, widgets.SecretField):
            # Show inside a password's field: part of the field, which lays out its own inside.
            return None, None
        if isinstance(parent, widgets.Card):
            return parent, "card"
        if isinstance(parent, widgets.Rail) or getattr(parent, "opendmt3_under", None) is not None:
            return parent, "rail"
        if parent in page_fields:
            return parent, "page"
        try:
            colour, round_it = str(parent.cget("bg")).lower(), str(parent.master.cget("bg")).lower()
        except (tk.TclError, AttributeError):
            colour = round_it = None
        if parent.master is not None and colour and round_it and colour != round_it and parent.winfo_class() == "Frame":
            return parent, "band"
        parent = parent.master
    return None, None


def _in_scale(gap, ui):
    return any(gap == ui.px(step) for step in SCALE)


def _gathered(root, origin):
    """Every widget that shows and is something to the eye, with its kind and its shown box."""
    found, stack = [], [root]
    while stack:
        widget = stack.pop()
        for child in widget.winfo_children():
            try:
                if not child.winfo_ismapped() or not child.winfo_viewable() or getattr(child, "opendmt3_skip", False):
                    continue
            except tk.TclError:
                continue
            if isinstance(child, tk.Toplevel):
                # Another window (an opened drop-down's list): measured by check_list, never against this one's boxes.
                continue
            stack.append(child)
            kind = _kind(child)
            if kind is None:
                continue
            box = _shown_box(child, origin)
            if box is not None:
                found.append((child, kind, box))
    return found


def check(root, ui, name):
    """The problems of the window's boxes and room as they show now (see the module's words)."""
    problems = []
    root.update_idletasks()
    origin = (root.winfo_rootx(), root.winfo_rooty())
    found = _gathered(root, origin)
    solids = [f for f in found if f[1] in ("card", "field", "button", "control", "menu", "foot")]
    texts = [(t, k, _text_box(t, origin)) for t, k, _b in found if k == "text"]
    texts = [t for t in texts if t[2] is not None]
    # ---- two boxes that touch or overlap, neither part of the other.
    for i, (a, _kind_a, box_a) in enumerate(solids):
        for b, _kind_b, box_b in solids[i + 1:]:
            if _inside(a, b) or _inside(b, a):
                continue
            if _overlap(box_a, box_b):
                problems.append("%s: %s and %s overlap" % (name, _name(a), _name(b)))
                continue
            gap = _gap(box_a, box_b)
            if gap is not None and gap < ui.px(LEAST_GAP):
                problems.append("%s: %s and %s touch (%d px apart)" % (name, _name(a), _name(b), gap))
    # ---- words over a box they are no part of, or right against one beside them on their line.
    for text, _kind_t, box_t in texts:
        for b, kind_b, box_b in solids:
            if kind_b in ("card", "menu", "foot") or _inside(text, b) or _inside(b, text):
                continue
            if _overlap(box_t, box_b):
                problems.append("%s: the words %s run over %s" % (name, _name(text), _name(b)))
                continue
            rows = box_t[1] < box_b[3] and box_b[1] < box_t[3]
            gap = _gap(box_t, box_b)
            if rows and gap is not None and gap < ui.px(LEAST_TEXT_GAP):
                problems.append("%s: the words %s touch %s (%d px apart)" % (name, _name(text), _name(b), gap))
    # ---- words inside the padding of the box they sit in: the menu column (its foot with it), the page's own field
    # outside any card (no words belong there: the page's title and its line are drawn on its head, everything else
    # in a card), or a band of its own colour. A card's own words are measured with what else it holds, below.
    page_fields = {area.inner for area in _all(root) if isinstance(area, widgets.ScrollArea)}
    for text, _kind_t, box_t in texts:
        surface, kind = _surface(text, page_fields)
        if surface is None or kind == "card":
            continue
        if kind == "page":
            problems.append("%s: the words %s lie on the page's field, outside any card" % (name, _name(text)))
            continue
        if kind == "rail":
            # The column's own box: the column under the foot, measured from the column's edges.
            column = surface if isinstance(surface, widgets.Rail) else surface.master
            column = column if isinstance(column, widgets.Rail) else next(
                (w for w in _all(root) if isinstance(w, widgets.Rail)), surface)
            whole = _raw(column, origin)
            # Less its seam at the right edge (a pixel).
            room = (whole[0] + ui.px(RAIL_SIDES), whole[1], whole[2] - ui.px(RAIL_SIDES) - max(1, ui.px(1)),
                    whole[3] - ui.px(RAIL_FOOT))
            short = [room[0] - box_t[0], 0, box_t[2] - room[2], box_t[3] - room[3]]
        else:
            whole = _raw(surface, origin)
            room = (whole[0] + ui.px(BAND_SIDES), whole[1] + ui.px(BAND_ENDS), whole[2] - ui.px(BAND_SIDES),
                    whole[3] - ui.px(BAND_ENDS))
            short = [room[0] - box_t[0], room[1] - box_t[1], box_t[2] - room[2], box_t[3] - room[3]]
        edges = [side for side, by in zip(("left", "top", "right", "foot"), short) if by > SLACK]
        if edges:
            problems.append("%s: the words %s are closer to the %s of the %s they sit in than its padding (%s px)" % (
                name, _name(text), "/".join(edges), {"rail": "menu column", "band": "band"}[kind],
                "/".join(str(by) for by in short if by > SLACK)))
    # ---- what a card holds, inside its padding at its sides and its foot (its tab's row hangs from its top on
    # purpose, and its cut corner and its action at the tab's right end are part of its edge).
    for card, kind, _card_box in found:
        if kind != "card":
            continue
        whole = _whole(card, origin)
        room = (whole[0] + ui.px(CARD_SIDES), whole[1], whole[2] - ui.px(CARD_SIDES), whole[3] - ui.px(CARD_FOOT))
        for child, kind_c, box_c in found:
            if child is card or not _inside(child, card) or kind_c == "card" or _inside(child, card.head):
                continue
            # Only what shows whole: a box the page's scroll cuts is measured where it is whole.
            if _whole(child, origin) != box_c:
                continue
            box = _text_box(child, origin) if kind_c == "text" else box_c
            short = [room[0] - box[0], 0, box[2] - room[2], box[3] - room[3]]
            sides = [side for side, by in zip(("left", "top", "right", "foot"), short) if by > SLACK]
            if sides:
                problems.append("%s: %s is closer to its card's %s than the card's padding (%s px)" % (
                    name, _name(child), "/".join(sides), "/".join(str(by) for by in short if by > SLACK)))
    # ---- the gaps between boxes stacked one after another on the same side of their box, on the spacing scale.
    seen = set()
    for widget, _k, _b in found:
        for parent in [widget.master] + _ancestors(widget.master or widget):
            if parent is None or parent in seen:
                continue
            seen.add(parent)
            try:
                slaves = parent.pack_slaves()
            except tk.TclError:
                continue
            sides = {}
            for child in slaves:
                try:
                    if not child.winfo_ismapped() or getattr(child, "opendmt3_skip", False):
                        continue
                    side = child.pack_info().get("side", "top")
                except tk.TclError:
                    continue
                if child.winfo_width() <= 1 and child.winfo_height() <= 1:
                    # Nothing to see (an empty frame).
                    continue
                sides.setdefault(side, []).append(child)
            for side, kids in sides.items():
                for a, b in zip(kids, kids[1:]):
                    ra, rb = _raw(a, origin), _raw(b, origin)
                    gap = {"top": rb[1] - ra[3], "bottom": ra[1] - rb[3], "left": rb[0] - ra[2],
                           "right": ra[0] - rb[2]}[side]
                    if gap < 0 or not _in_scale(gap, ui):
                        if _shown_box(a, origin) is None or _shown_box(b, origin) is None:
                            continue
                        problems.append("%s: %d px between %s and %s, off the spacing scale" % (
                            name, gap, _name(a), _name(b)))
    return sorted(set(problems))


def check_list(shown, ui, name, screen_pixel):
    """An opened drop-down's list (widgets.SelectList): whole on the screen, clear of its field by the least gap, and
    over everything at its four corners: the screen's own pixels there (`screen_pixel(x, y)`, read from the X server)
    are the list's edge."""
    from opendmt3.client import art, theme
    problems = []
    select = shown.select
    lx, ly, lw, lh = shown.winfo_rootx(), shown.winfo_rooty(), shown.winfo_width(), shown.winfo_height()
    sy, sh = select.winfo_rooty(), select.winfo_height()
    width, height = shown.winfo_screenwidth(), shown.winfo_screenheight()
    if lx < 0 or ly < 0 or lx + lw > width or ly + lh > height:
        problems.append("%s: the opened list reaches past the screen" % name)
    gap = ly - (sy + sh) if ly >= sy else sy - (ly + lh)
    if gap < ui.px(2) - SLACK:
        problems.append("%s: the opened list touches its field (%d px apart)" % (name, gap))
    edge = art._rgb(theme.LINE)
    for x, y in ((lx, ly), (lx + lw - 1, ly), (lx, ly + lh - 1), (lx + lw - 1, ly + lh - 1)):
        seen = screen_pixel(x, y)
        if seen is None or any(abs(a - b) > 6 for a, b in zip(seen, edge)):
            problems.append("%s: the opened list is not over everything at (%d, %d): %s there" % (name, x, y, seen))
            break
    return problems
