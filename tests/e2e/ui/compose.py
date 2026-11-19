"""The page's composition and its words, measured, so that what the owner looks at on their own screen is a fault the
UI check finds, not an opinion (the owner on the sister launcher at 150 %, 2026-11-19: keys and words sized, aligned
and laid out as they should be, every word's size, padding, margin and alignment; the decoration never ending at a
card's corner or in the gap between cards).

  problems = compose.check(app, name, screen_pixel)     (a list of words, empty when all is well)
  problems = compose.check_dialog(dialog, ui, name)

What it holds, on every page, guide step and dialog it is given:
- keys of one role alike everywhere: a page's key and a dialog's key one height, one room either side of their words
  and one least width (widgets.Button.HEIGHTS, SIDES, LEAST); a small key (a card's action) its own; no key stretched
  across its box;
- a key's words in its middle by their ink: the band of their capitals (or their Hangul syllables) in the middle of
  the key, up and down (art.ink_band), and their box in its middle across;
- every word in one of the type's steps (theme.TYPE_STEPS), and no heading smaller than the body under it (a card's
  name on its tab, a dialog's tab: their capitals at least the body's);
- a setting's name and its control on one line (their middles), the controls of one group at one edge;
- a control sized for its use: a slider long enough to set a value by;
- a status panel's lamp saying the whole check as the foot does;
- no control or tag in a card's cut corner (the cut and the card's padding), and cards in one row ending on one line;
- a page composed, not a list of boxes: no card that holds one control (a key, a switch, a choice, a field) and at
  most one line of words (fold it into the group it belongs to), and no run of three or more cards each across the
  whole column, one under another, on a page wide enough for two (pages.PAIR_FROM) that leaves a quarter of its view
  empty under them;
- the decoration (the head's stage) never at a card's edge: the page's own colour round every card, in the gaps
  between cards and beyond each cut corner, read from the screen's pixels.
"""

import tkinter as tk
import tkinter.font as tkfont

from opendmt3.client import art, theme, widgets

# How far a key's words may stand from its middle by their ink, in the screen's pixels: Tk sets text on whole pixels,
# so half a pixel is what placing can give; a quarter more for the ink's own measure.
CENTRED = 0.75
# A slider shorter than this (logical pixels) is too short to set a value by.
SLIDER_LEAST = 200
# How far a page's colour may differ in a channel and still be the page's colour (anti-aliasing at an edge).
SAME_COLOUR = 6
# The controls a card can hold: a card with one of them and at most one line of words is a box for one control.
CONTROLS = (widgets.Button, widgets.Toggle, widgets.Segmented, widgets.Select, widgets.Slider, widgets.Field,
            widgets.Tick)
# A card's own padding (widgets.Card's pad, logical pixels): the room a control keeps from the cut corner beyond the cut.
CARD_PAD = 18
# How many full-width cards one under another make a list of boxes, and the share of the page's view left empty under
# them that makes it a short one.
STACK, EMPTY_SHARE = 3, 0.25


def _shown(widget):
    """True when `widget` and every widget round it are on the screen (mapped)."""
    return bool(widget.winfo_ismapped())


def _card_name(card):
    """A card's name as the tests know it: its tab's words, or its name in words (a list's band, an info caption)."""
    named = card.tab if card.tab is not None else getattr(card, "name_label", None)
    return getattr(named, "words", "") if named is not None else ""


def _inside_control(widget, card):
    """True when `widget` is part of a control (a tick's words, a field's own parts), below `card`."""
    parent = widget.master
    while parent is not None and parent is not card:
        if isinstance(parent, CONTROLS):
            return True
        parent = parent.master
    return False


def single_controls(root, ui, name):
    """No card holds one control and at most one line of words: a card for one key, one switch or one choice said
    little but its name (fold it into the group it belongs to, or the page's head)."""
    problems = []
    for card in _walk(root):
        if not isinstance(card, widgets.Card) or not _shown(card):
            continue
        parts = [w for w in _walk(card) if w is not card and _shown(w)]
        controls = [w for w in parts if isinstance(w, CONTROLS) and not _inside_control(w, card)]
        # Words: labels with words of their own (a switch or a row of choices is a label holding a picture), and the
        # objects a card holds (the member's card).
        lines = [w for w in parts if isinstance(w, tk.Label) and not isinstance(w, CONTROLS)
                 and (str(w.cget("text")).strip() or getattr(w, "opendmt3_object", False))
                 and not _inside_control(w, card)]
        if len(controls) == 1 and len(lines) <= 1:
            named = _card_name(card)
            problems.append("%s: the card %r holds one control and %s: a box for one control"
                            % (name, named, "one line" if lines else "no words"))
    return problems


def short_stack(root, ui, name):
    """No list of boxes: three or more cards each across the whole column, one under another, on a page whose column
    is wide enough for two side by side and that leaves a quarter of its view empty under its last card."""
    from opendmt3.client.pages.common import PAIR_FROM
    problems = []
    page = next((w for w in _walk(root) if isinstance(w, widgets.ScrollArea)), None)
    if page is None or not page.inner.winfo_children():
        return problems
    content = page.inner.winfo_children()[0]
    width = content.winfo_width()
    if width < ui.px(PAIR_FROM):
        # A narrow column has its groups one under another: nothing to set side by side.
        return problems
    cards = sorted((c for c in _walk(content) if isinstance(c, widgets.Card) and _shown(c)
                    # The page's own groups, not a card inside another card.
                    and not any(isinstance(a, widgets.Card) for a in _above(c, content))),
                   key=lambda c: c.winfo_rooty())
    if not cards:
        return problems
    # The page's empty view under its last card, scrolled to its top.
    seen = page.canvas.winfo_height()
    used = page.head_height + max(c.winfo_rooty() + c.winfo_height() for c in cards) - page.inner.winfo_rooty()
    empty = seen - used
    run = longest = 0
    for c in cards:
        whole = abs(c.winfo_width() - width) <= 2
        run = run + 1 if whole else 0
        longest = max(longest, run)
    if longest >= STACK and empty > EMPTY_SHARE * seen:
        problems.append("%s: %d cards across the whole column one under another, %d px empty under them: a list of "
                        "boxes where two fit side by side" % (name, longest, empty))
    return problems


def _above(widget, top):
    """The widgets between `widget` and `top`."""
    found, parent = [], widget.master
    while parent is not None and parent is not top:
        found.append(parent)
        parent = parent.master
    return found


def _walk(widget):
    found = [widget]
    for child in widget.winfo_children():
        found.extend(_walk(child))
    return found


def _font(widget, spec):
    """The Tk font of a widget's or a canvas item's font option."""
    try:
        return tkfont.nametofont(spec)
    except tk.TclError:
        return tkfont.Font(root=widget, font=spec)


def _pixels(widget, font):
    """The font's size in the screen's pixels."""
    size = font.actual()["size"]
    return -size if size < 0 else size * widget.winfo_fpixels("1i") / 72.0


def _ink_middle(widget, font, words, top):
    """The middle of `words`' ink band (art.ink_band) when their line box's top is at `top`, in the same pixels."""
    actual = font.actual()
    face = theme.FONT_FILES.get((actual["family"], actual["weight"]))
    if face is None:
        return None
    band_top, band_bottom = art.ink_band(face, round(_pixels(widget, font) * 4) / 4.0, words)
    baseline = top + font.metrics("ascent")
    return baseline + (band_top + band_bottom) / 2.0


def _key_problems(name, words, font, size, box, text_box, widget, ui, role):
    """One key: its height and width as its role's, its words in its middle. `box` (x0, y0, x1, y1) is the key's face,
    `text_box` the words' line box as Tk lays it."""
    problems = []
    px = ui.px
    height = box[3] - box[1]
    expected_height = px(widgets.Button.HEIGHTS[size])
    if abs(height - expected_height) > 1:
        problems.append("%s: the %s key %r is %d px tall, not its role's %d" % (name, role, words, height,
                                                                                expected_height))
    side = px(widgets.Button.SIDES[size]) + int(expected_height * art.LEAN) // 2
    expected_width = max(px(widgets.Button.LEAST[size]), font.measure(words) + 2 * side)
    width = box[2] - box[0]
    if abs(width - expected_width) > 1:
        problems.append("%s: the %s key %r is %d px wide, not %d (its words and its role's room either side)"
                        % (name, role, words, width, expected_width))
    # Only words: a sign alone (a window key's × or −) is centred by its own shape, maybe from another font.
    middle = _ink_middle(widget, font, words, text_box[1]) if art.has_letters(words) else None
    if middle is not None and abs(middle - (box[1] + box[3]) / 2.0) > CENTRED:
        problems.append("%s: the words of %r stand %.2f px off the key's middle (by their ink)"
                        % (name, words, middle - (box[1] + box[3]) / 2.0))
    across = (text_box[0] + text_box[2]) / 2.0 - (box[0] + box[2]) / 2.0
    if abs(across) > 1.0:
        problems.append("%s: the words of %r stand %.1f px off the key's middle across" % (name, words, across))
    return problems


def keys(root, ui, name):
    """Every page key on show: its role's height and room, its words in its middle."""
    problems = []
    for key in _walk(root):
        if not isinstance(key, widgets.Button) or not key.winfo_ismapped() or not key.words:
            continue
        size = "small" if key.size == "small" else "normal"
        font = _font(key, key.itemcget(key.label, "font"))
        box = (0, 0, key.winfo_width(), key.winfo_height())
        text_box = key.bbox(key.label)
        if text_box is None:
            continue
        if key.fill:
            problems.append("%s: the key %r is stretched across its box" % (name, key.words))
            continue
        problems.extend(_key_problems(name, key.words, font, size, box, text_box, key, ui,
                                      "small" if size == "small" else "page"))
    return problems


def check_dialog(dialog, ui, name):
    """A dialog's keys as a page's (one role, one size), their words in their middles; its tab's capitals no smaller
    than its body's."""
    problems = []
    c = dialog.canvas
    # The keys' boxes are the panel's (laid out before the panel is moved to its place on the window: origin).
    ox, oy = getattr(dialog, "origin", (0, 0))
    for i, (left, top, right, bottom) in enumerate(getattr(dialog, "_boxes", [])):
        words = dialog.buttons[i][0]
        items = [item for item in c.find_withtag("button%d" % i) if c.type(item) == "text"]
        if not items:
            continue
        font = _font(c, c.itemcget(items[0], "font"))
        box = (left + ox, top + oy, right + ox, bottom + oy)
        problems.extend(_key_problems(name, words, font, "normal", box, c.bbox(items[0]), c, ui, "dialog"))
    tab_words = dialog.tab_words()
    tab_font = ui.fonts.tab_font(tab_words)
    problems.extend(_heading(c, name, "the dialog's tab %r" % tab_words, tab_font, tab_words, ui.fonts.body))
    for item in c.find_withtag("words"):
        if c.type(item) == "text":
            problems.extend(_step(c, name, _font(c, c.itemcget(item, "font")), c.itemcget(item, "text")))
    return problems


def _step(widget, name, font, words):
    size = font.actual()["size"]
    if size > 0 and size not in theme.TYPE_STEPS:
        return ["%s: %r is set at %s points, none of the type's steps %s" % (name, words[:40], size, theme.TYPE_STEPS)]
    return []


def _cap(widget, font, words):
    """The height of `words`' ink band (their capitals', or their Hangul syllables') in `font`, in pixels."""
    actual = font.actual()
    face = theme.FONT_FILES.get((actual["family"], actual["weight"]))
    if face is None:
        return None
    top, bottom = art.ink_band(face, _pixels(widget, font), words)
    return bottom - top


def _heading(widget, name, what, font, words, body):
    """A heading's capitals no smaller than the body's (a quarter of a pixel of measure's slack)."""
    heading, under = _cap(widget, font, words), _cap(widget, body, "H")
    if heading is not None and under is not None and heading + 0.25 < under:
        return ["%s: %s is smaller than the body under it (its capitals %.1f px, the body's %.1f)"
                % (name, what, heading, under)]
    return []


def words_and_headings(root, ui, name):
    """Every label in the type's steps; every card's name (its tab, a picture: art.name_plate; or its words on a list's
    band or as an info plate's caption) no smaller than the body."""
    problems = []
    body_cap = _cap(root, ui.fonts.body, "H")
    plate_cap = None
    for widget in _walk(root):
        if not widget.winfo_ismapped():
            continue
        if widget.winfo_class() == "Label":
            text = widget.cget("text")
            if text:
                problems.extend(_step(widget, name, _font(widget, widget.cget("font")), text))
        named = getattr(widget, "name_label", None) if isinstance(widget, widgets.Card) else None
        if named is not None and named.winfo_ismapped():
            # A name in words (a list's band, an info plate's caption): its own font measured.
            problems.extend(_heading(named, name, "the card's name %r" % named.words,
                                     _font(named, named.cget("font")), named.words, ui.fonts.body))
        if isinstance(widget, widgets.Card) and widget.tab is not None:
            if plate_cap is None:
                top, bottom = art.ink_band(theme.WIDE_FILE, art.PLATE_TEXT * ui.scale, "H")
                plate_cap = bottom - top
            if body_cap is not None and plate_cap + 0.25 < body_cap:
                problems.append("%s: the card's name %r is smaller than its body (capitals %.1f px, the body's %.1f)"
                                % (name, widget.tab.words, plate_cap, body_cap))
    return problems


def rows(root, ui, name):
    """A setting's name and its control on one line (their middles within a pixel and a half), and the controls of one
    group starting at one edge."""
    problems = []
    groups = {}
    for row in _walk(root):
        control = getattr(row, "control", None)
        if not hasattr(row, "opendmt3_names") or control is None or not control.winfo_ismapped():
            continue
        names = row.grid_slaves(row=0, column=0)
        if names:
            label = names[0]
            label_middle = label.winfo_rooty() + label.winfo_height() / 2.0
            control_middle = control.winfo_rooty() + control.winfo_height() / 2.0
            if abs(label_middle - control_middle) > 1.5 and control.winfo_height() <= ui.px(48):
                problems.append("%s: the setting %r and its control are not on one line (%.1f px apart)"
                                % (name, label.cget("text"), control_middle - label_middle))
        edge = control.winfo_rootx() + getattr(control, "opendmt3_inset", 0)
        groups.setdefault(str(row.master), set()).add(edge)
        if isinstance(control, widgets.Slider) and control.w < ui.px(SLIDER_LEAST):
            problems.append("%s: a slider %d px long is too short to set a value by" % (name, control.w))
    for group, edges in groups.items():
        if max(edges) - min(edges) > 1:
            problems.append("%s: the controls of one group start at %s" % (name, sorted(edges)))
    return problems


def left_line(root, ui, name):
    """One left edge down the page: the head's line under its title and every card that stands on the page's own
    column (not the second of two side by side) start where the page's content starts."""
    problems = []
    page = next((w for w in _walk(root) if isinstance(w, widgets.ScrollArea)), None)
    if page is None or not page.inner.winfo_children():
        return problems
    content = page.inner.winfo_children()[0]
    left = content.winfo_rootx()
    sub = page.canvas.itemcget(page._sub_item, "text") if page._sub_item is not None else ""
    if sub:
        sub_x = page.canvas.winfo_rootx() + page.canvas.coords(page._sub_item)[0]
        if abs(sub_x - left) > 1:
            problems.append("%s: the head's line starts at %d, the page's content at %d" % (name, sub_x, left))
    for card in _walk(content):
        if not isinstance(card, widgets.Card) or not card.winfo_ismapped():
            continue
        # A card on the page's column: packed in the content (or in a part of it that spans it), or the first of a
        # row of cards side by side.
        manager = card.winfo_manager()
        first = manager != "grid" or int(card.grid_info().get("column", 0)) == 0
        if first and card.master is not None and card.master.winfo_rootx() <= left + 1 and \
                abs(card.winfo_rootx() - left) > 1:
            problems.append("%s: the card %r starts at %d, off the page's left edge %d"
                            % (name, _card_name(card), card.winfo_rootx(), left))
    return problems


def decoration(root, ui, name, screen_pixel):
    """The page's own colour round every card on show, in the gaps between them and beyond each cut corner: the
    head's stage (or any light) never ends at a card's edge."""
    problems = []
    if screen_pixel is None:
        return problems
    page = None
    for widget in _walk(root):
        if isinstance(widget, widgets.ScrollArea):
            page = widget
            break
    if page is None:
        return problems
    view_top = page.canvas.winfo_rooty() + max(0, page.head_height - int(page.canvas.canvasy(0)))
    view = (page.canvas.winfo_rootx(), view_top, page.canvas.winfo_rootx() + page.canvas.winfo_width(),
            page.canvas.winfo_rooty() + page.canvas.winfo_height())
    for card in _walk(page.inner):
        if not isinstance(card, widgets.Card) or not card.winfo_ismapped():
            continue
        x, y, w, h = card.winfo_rootx(), card.winfo_rooty(), card.winfo_width(), card.winfo_height()
        colour = art._rgb(card.master.cget("bg"))
        # The card's own cut (its kind's: theme.CARD_LOOKS).
        cut = ui.px(getattr(card, "cut", widgets.Card.CUT))
        # Next to the card's edges and a little out into the gaps, and in the triangle its cut leaves (a result panel's
        # second cut at its foot's left too).
        out = ui.px(10)
        points = [("left of", x - 3, y + h // 2), ("left of", x - out, y + h // 2), ("right of", x + w + 2, y + h // 2),
                  ("under", x + w // 2, y + h + 2), ("under", x + w // 4, y + h + ui.px(8)),
                  ("beyond the cut corner of", x + w - 2, y + 2), ("beyond the cut corner of", x + w - cut // 3, y + 1)]
        foot_cut = ui.px((getattr(card, "look", None) or {}).get("foot_cut") or 0)
        if foot_cut:
            points += [("beyond the foot's cut corner of", x + 1, y + h - 2),
                       ("beyond the foot's cut corner of", x + foot_cut // 3, y + h - 1)]
        for where, px_, py in points:
            if not (view[0] <= px_ < view[2] - ui.px(14) and view[1] <= py < view[3]):
                # Off the page's view (scrolled away, or under the scroll bar's margin).
                continue
            seen = screen_pixel(px_, py)
            if seen is not None and any(abs(a - b) > SAME_COLOUR for a, b in zip(seen, colour)):
                problems.append("%s: something other than the page's colour %s the card %r at (%d, %d): %s"
                                % (name, where, _card_name(card), px_, py, seen))
                break
    return problems


def corner_clear(root, ui, name):
    """No control (a key, a switch, a choice, a field) and no tag in a card's cut corner: each stays out of the square
    at the card's top right as wide and as tall as the cut and the card's own padding together (the owner, twice: a key
    in the 45-degree cut, or flush against it, is the corner handled awkwardly)."""
    problems = []
    room = ui.px(CARD_PAD)
    for card in _walk(root):
        if not isinstance(card, widgets.Card) or not _shown(card):
            continue
        cut = ui.px(getattr(card, "cut", widgets.Card.CUT))
        x, y, w = card.winfo_rootx(), card.winfo_rooty(), card.winfo_width()
        # The cut's corner and the card's padding round it: nothing that is pressed or read as a tag reaches in.
        left, foot = x + w - cut - room, y + cut + room
        for part in _walk(card):
            if part is card or not _shown(part):
                continue
            if not (isinstance(part, CONTROLS) or getattr(part, "opendmt3_tag", False)):
                continue
            if _inside_control(part, card):
                continue
            px_, py_, pw = part.winfo_rootx(), part.winfo_rooty(), part.winfo_width()
            if px_ + pw > left and py_ < foot:
                problems.append("%s: %s reaches into the cut corner of the card %r (%d px into the cut and its room)"
                                % (name, _describe(part), _card_name(card), px_ + pw - left))
    return problems


def _describe(part):
    """A control as a person names it: a key or a tag by its words, else its kind."""
    words = getattr(part, "words", None)
    if isinstance(part, widgets.Button):
        return "the key %r" % words
    if words is None:
        return "a %s" % type(part).__name__.lower()
    return "the %s %r" % ("tag" if getattr(part, "opendmt3_tag", False) else type(part).__name__.lower(), words)


def row_bottoms(root, ui, name):
    """Cards side by side in one row end on one line (within a pixel): the shorter one's body grows to the row's
    height, its content at its top."""
    problems = []
    cards = [c for c in _walk(root) if isinstance(c, widgets.Card) and _shown(c)]
    boxes = [(c, c.winfo_rootx(), c.winfo_rooty(), c.winfo_rootx() + c.winfo_width(),
              c.winfo_rooty() + c.winfo_height()) for c in cards]
    for i, (a, ax, ay, ax2, ay2) in enumerate(boxes):
        for b, bx, by, bx2, by2 in boxes[i + 1:]:
            # Side by side: one top, apart across; one inside the other is no row.
            if abs(ay - by) > 1 or not (ax2 <= bx or bx2 <= ax):
                continue
            if abs(ay2 - by2) > 1:
                problems.append("%s: the cards %r and %r stand in one row but end %d px apart"
                                % (name, _card_name(a), _card_name(b), abs(ay2 - by2)))
    return problems


def status_lamp(app, name):
    """A status panel's lamp says the whole check as the foot does (CARDS.md "status"): green when PLAY can go, amber
    when something is still to do, pink when something went wrong, an outline while the check is made."""
    from opendmt3.client import actions
    panel = getattr(app, "check_card", None)
    if panel is None or not panel.winfo_exists() or not panel.winfo_ismapped() or panel.state_lamp is None:
        return []
    checks = app.checks
    if checks is None:
        wanted = "quiet"
    elif any(not c.ok and actions.failing(c) for c in checks):
        wanted = "bad"
    elif any(not c.ok and not c.key.startswith("step:") for c in checks):
        wanted = "todo"
    else:
        wanted = "ready"
    if panel.state_lamp.tone != wanted:
        return ["%s: the status panel %r says %r, its check %r" % (name, _card_name(panel), panel.state_lamp.tone,
                                                                     wanted)]
    return []


def check(app, name, screen_pixel=None):
    """Everything above on the window's page on show."""
    ui, root = app.ui, app.root
    root.update_idletasks()
    return (keys(root, ui, name) + words_and_headings(root, ui, name) + rows(root, ui, name)
            + left_line(root, ui, name) + single_controls(root, ui, name) + short_stack(root, ui, name)
            + corner_clear(root, ui, name) + row_bottoms(root, ui, name) + status_lamp(app, name)
            + decoration(root, ui, name, screen_pixel))
