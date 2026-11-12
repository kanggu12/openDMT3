"""The card of one path a player brings (client/intake.py's Found). DISC CHECK's list and the Game page draw the same
card, so a game folder or an archive reads the same in both places.

A card names the path, says its state on a chip in the game's capitals (READY, UNPACK, DOES NOT WORK HERE; 쓸 수 있음,
풀면 쓸 수 있음, 여기서는 못 씁니다), what it holds, the one problem with the one thing to do, and what can be done with it:
a game folder that is ready is picked with a click anywhere on it, Unpack... and Put back... are buttons.

Of three shapes drawn over the launcher's real look in both languages at three sizes (a row with a lamp, this plate,
a compact ticket), this one was kept: its chip and the bar down its edge say the state at a glance in the ready
check's colours, and the path has a line of its own, so a long Windows path or a split archive's name never breaks
beside the chip.
"""

import tkinter as tk

from PIL import ImageTk

from opendmt3.client import art, intake, theme, widgets

# The chip's colours by state: lime for ready (a check that passed), amber for unpack (something to do before it plays,
# as PLAY's "will change"), pink for does not work here, quiet metal while it is looked at or not there yet.
CHIP = {
    intake.READY: (theme.LIME, theme.INK),
    intake.UNPACK: (theme.AMBER, theme.INK),
    intake.NOT_HERE: (theme.PINK, theme.INK),
    intake.NOT_YET: (theme.RAIL, theme.MUTED),
    intake.CHECKING: (theme.RAIL, theme.MUTED),
}


def capitals(ui, words):
    """Words in the game's capitals where the launcher writes English (Hangul has no capitals)."""
    return words.upper() if ui.words.language == "en" else words


def chip(parent, ui, state, bg):
    """The state on a leaning plate of its colour, as the game labels a part of its screen."""
    # The plate's fill and the words' colour for this state.
    fill, ink = CHIP[state]
    # READY, UNPACK, DOES NOT WORK HERE in English; the Korean words as they are.
    words = capitals(ui, ui.words("intake.state." + state))
    # Drawn as a picture: the plate leans, which Tk's own shapes cannot.
    picture = art.name_plate(words, ui.scale, fill=fill, colour=ink)
    image = ImageTk.PhotoImage(picture, master=parent)
    plate = tk.Label(parent, image=image, bg=bg, bd=0)
    # Kept on the label: Tk shows a picture only while Python holds it. The words ride along for the tests, and the
    # picture for a dialog's view of the window behind it (snapshot.py).
    plate.image, plate.words, plate.opendmt3_picture = image, words, picture
    return plate


class Card(tk.Frame):
    """One found path. on_choose(found) for a click on a card that can be picked; on_unpack(found) and
    on_put_back(found) for its buttons; `extra` more buttons as (words, function). `chosen` marks the folder in use;
    `thumbs` are three of its jackets (PhotoImages)."""

    def __init__(self, parent, app, found, chosen=False, on_choose=None, on_unpack=None, on_put_back=None, thumbs=(),
                 extra=()):
        self.app, self.ui, self.found = app, app.ui, found
        # The folder in use is marked (its seam and IN USE).
        self.chosen = chosen
        # Only a game folder that plays is picked with a click; anything else says why it is not.
        self.pickable = bool(on_choose) and intake.CHOOSE in found.actions
        self.on_choose = on_choose
        # The seam: the section's blue round the folder in use, else the panel's seam.
        super().__init__(parent, bg=theme.BLUE if chosen else theme.LINE, padx=1, pady=1)
        # The folder in use sits a step lighter, as a chosen row does everywhere in the launcher.
        self.inner_bg = theme.PANEL_HI if chosen else theme.PANEL
        # The parts a click picks the folder from (filled in as they are made).
        self.clickable = []
        # The buttons, in the order a player reads them: what the card offers, then what the page adds.
        actions = []
        if intake.UNPACK_IT in found.actions and on_unpack:
            actions.append((self.ui.words("intake.unpack"), lambda: on_unpack(found)))
        if intake.PUT_BACK in found.actions and on_put_back:
            actions.append((self.ui.words("intake.put_back"), lambda: on_put_back(found)))
        # Buttons the page adds for this card (the Game page's Change... and Open).
        actions += list(extra)
        self._plate(actions, thumbs)
        if self.pickable:
            for widget in self.clickable:
                # The hand says the card can be clicked; anywhere on it picks it.
                widget.configure(cursor="hand2")
                widget.bind("<Button-1>", lambda e: self.on_choose(self.found))

    # ------------------------------------------------------------------------------------------- parts

    def _texts(self, box, bg):
        """The path, then what it holds, then the one line; each wraps at the box's width. Returns the labels."""
        ui, w, found = self.ui, self.ui.words, self.found
        # The path in the body's bold: what a player recognises first.
        path = widgets.label(box, ui, found.path, font=ui.fonts.body_bold, bg=bg, wrap_margin=0)
        path.pack(fill="x")
        made = [path]
        facts = found.fact_words(w)
        if found.state == intake.CHECKING and not facts:
            # Still being looked at: said, so an empty card never reads as nothing found.
            facts = [w("intake.reading")]
        if facts:
            # What it holds, small and quiet, the parts apart by a middle dot.
            line = widgets.label(box, ui, "  ·  ".join(facts), font=ui.fonts.small, fg=theme.MUTED, bg=bg,
                                 wrap_margin=0)
            line.pack(fill="x", pady=(ui.px(3), 0))
            made.append(line)
        said = found.line_words(w)
        if said:
            # The one problem in the error colour; a note (a password to give, an archive inside) in the hint colour.
            colour = theme.PINK if found.tone == intake.PROBLEM else theme.MUTED
            note = widgets.label(box, ui, said, font=ui.fonts.small, fg=colour, bg=bg, wrap_margin=0)
            note.pack(fill="x", pady=(ui.px(3), 0))
            made.append(note)
        return made

    def _buttons(self, box, actions):
        """The card's buttons side by side, the launcher's own leaning ones."""
        for i, (words, command) in enumerate(actions):
            widgets.Button(box, self.ui, words, command).pack(side="left", padx=(0 if i == 0 else self.ui.px(8), 0))

    def _thumbs(self, box, thumbs, bg):
        """Three of the folder's own jackets: the player's game, at a glance."""
        for image in thumbs:
            tk.Label(box, image=image, bg=bg).pack(side="left", padx=(self.ui.px(4), 0))

    # -------------------------------------------------------------------------------------------- drawing

    def _plate(self, actions, thumbs):
        """The card as a plate: a bar of the state's colour down its left edge, the chip and what the path is on top
        (with IN USE on the folder in use), the path, what it holds, the one line, and the buttons along its foot; the
        jackets at the right."""
        ui, px, bg = self.ui, self.ui.px, self.inner_bg
        body = tk.Frame(self, bg=bg)
        body.pack(fill="x")
        # The state's colour down the left edge, so a list reads at a glance.
        bar = tk.Frame(body, bg=CHIP[self.found.state][0], width=px(4))
        bar.pack(side="left", fill="y")
        # The card's room inside its edge, as the launcher's cards keep it.
        inside = tk.Frame(body, bg=bg, padx=px(16), pady=px(12))
        inside.pack(side="left", fill="x", expand=True)
        # The top line: the chip, then what the path is (a game folder, an archive), then IN USE at the right.
        top = tk.Frame(inside, bg=bg)
        top.pack(fill="x")
        plate = chip(top, ui, self.found.state, bg)
        plate.pack(side="left")
        kind = capitals(ui, ui.words("intake.label." + (self.found.kind or intake.FOLDER)))
        # Quiet beside the chip: the state is what matters first.
        kind_label = tk.Label(top, text=kind, font=ui.fonts.section, fg=theme.FAINT, bg=bg)
        kind_label.pack(side="left", padx=(px(10), 0))
        made = [top, plate, kind_label]
        if self.chosen:
            # The folder PLAY starts the game from, in the section's light.
            using = tk.Label(top, text=capitals(ui, ui.words("intake.in_use")), font=ui.fonts.section,
                             fg=theme.BLUE_HI, bg=bg)
            using.pack(side="right")
            made.append(using)
        # Under it: the words at the left, the jackets at the right.
        middle = tk.Frame(inside, bg=bg)
        middle.pack(fill="x", pady=(px(8), 0))
        right = tk.Frame(middle, bg=bg)
        right.pack(side="right", anchor="n")
        self._thumbs(right, thumbs, bg)
        text = tk.Frame(middle, bg=bg)
        # The words keep clear of the jackets when there are some.
        text.pack(side="left", fill="x", expand=True, padx=(0, px(10) if thumbs else 0))
        made += [middle, text] + self._texts(text, bg)
        if actions:
            # The buttons along the foot, left, where the eye ends after the line that says what to do.
            buttons = tk.Frame(inside, bg=bg)
            buttons.pack(anchor="w", pady=(px(10), 0))
            self._buttons(buttons, actions)
        # Every part but the buttons picks the folder.
        self.clickable = [body, inside] + made
