"""The game folders and archives found on this PC, and those the player chooses, as cards (client/cards.py): the
first-start guide's DISC CHECK, and the Game page's list when Change... opens it.

The search and every look at a path run on worker threads, so the window never waits: a path found is shown at once
as being checked, then with what it is. A search can be stopped; a new one stops the one before. Unpack... and
Put back... start from a card (client/unpacking.py, actions.put_back), and a game folder that comes out of an archive
is listed ready and chosen.
"""

import logging
import os
import threading
import tkinter as tk
from tkinter import filedialog

from PIL import Image, ImageTk

from opendmt3.core import game as g
from opendmt3.client import art, cards, find, intake, theme, widgets

log = logging.getLogger("opendmt3.launcher")

# The kinds of file the archive picker shows first; "All files" stays for anything else 7-Zip opens.
ARCHIVE_TYPES = (("Archives", "*.zip *.7z *.rar *.001 *.iso"), ("All files", "*.*"))


class FoundList:
    """The list and its two buttons, drawn into a frame by build(). on_update() runs after the list is drawn again
    (a pick, a path looked at, an unpacking that ended with a ready folder): DISC CHECK's Next follows it."""

    def __init__(self, app, on_update=None, on_pick=None, hide_chosen=False):
        self.app = app
        # The Game page lists what to change to: the folder in use has its own card above the list.
        self.hide_chosen = hide_chosen
        self.on_update = on_update or (lambda: None)
        # What a pick does after the folder is in use (the Game page closes its list).
        self.on_pick = on_pick
        self.items = None              # the paths found and chosen, as Found (None: the search has not ended)
        self.thumbs = {}               # a ready folder's jackets for its card, by its path (PhotoImages)
        self.pictures = {}             # the same as pictures, kept to make the PhotoImages on the window's thread
        self.cancel = None             # the running search's stop
        self.searching = False         # a search is under way (its line and Stop show above the cards)
        self.box = None                # the frame the cards are drawn in
        self.wanted = None             # a path the player chose: used as soon as it reads ready
        self.queued = False            # a drawing is asked for, to run once the window's thread is idle
        self.drawn = {}                # the cards in the box by path: ((the Found, in use, its jackets), the card)
        self.top = None                # the line above the cards: (what it says, its frame)
        self.none = None               # the words that say nothing was found, while they show

    # ------------------------------------------------------------------------------------------- drawing

    def build(self, parent):
        """The list and, under it, Choose a folder... and Choose an archive...; the search starts the first time."""
        ui, px, w = self.app.ui, self.app.ui.px, self.app.words
        # The cards' own frame: drawn again on its own as paths are looked at, the buttons under it staying put.
        self.box = tk.Frame(parent, bg=parent["bg"])
        self.box.pack(fill="x")
        # A new box holds no card yet (the old one's went with the page or step drawn before).
        self.drawn, self.top, self.none = {}, None, None
        # The two ways to choose one by hand, under the list, as OpenDMTQ's setup has its folder picker under its list.
        row = tk.Frame(parent, bg=parent["bg"])
        row.pack(fill="x", pady=(px(14), 0))
        widgets.Button(row, ui, w("guide.2.choose"), self.choose_folder).pack(side="left")
        widgets.Button(row, ui, w("intake.choose_archive"), self.choose_archive).pack(side="left", padx=(px(8), 0))
        if self.items is None and not self.searching:
            # The first time the list is on screen: the search starts, once (it is kept across steps and pages).
            self.search()
        chosen = self.app.state.game_folder
        if chosen and not self.hide_chosen and not any(os.path.normcase(f.root or f.path) == os.path.normcase(chosen)
                                                      for f in self.items or []):
            # The folder in use, wherever it is, is on the list too (a guide shown again, a folder outside the places).
            self.add(chosen, use=False)
            return
        self.paint()

    def paint(self):
        """Draw the list again, once the window's thread has done what it is doing now (on the window's thread): every
        change asked for meanwhile goes into that one drawing. A search's results come many to one turn of the
        window's queue, and each drew the whole list before (33 drawings in one DISC CHECK, the window still for up to
        0.9 s at once)."""
        box = self.box
        if self.queued or box is None or not box.winfo_exists():
            return
        self.queued = True
        # Asked of the window itself, not of the box: a box drawn again meanwhile (a step left and come back to)
        # would take its waiting call with it, and the list would never be drawn again.
        self.app.root.after_idle(self._redraw)

    def _redraw(self):
        """Draw what changed since the last drawing: the line above the cards, and each card whose path was looked at
        again, became the folder in use (or stopped being it) or got its jackets. The other cards keep their widgets,
        put in the list's order."""
        self.queued = False
        box = self.box
        if box is None or not box.winfo_exists():
            # The step or page with the list was left meanwhile.
            return
        ui, px, w = self.app.ui, self.app.ui.px, self.app.words
        # Above the cards: where the search looks while it runs (with Stop), then the list's name; drawn again only
        # when it is to say something else.
        says = "searching" if self.searching else "found" if self.items else None
        if self.top is None or self.top[0] != says or not self.top[1].winfo_exists():
            if self.top is not None:
                self.top[1].destroy()
            top = tk.Frame(box, bg=box["bg"])
            if says == "searching":
                widgets.label(top, ui, w("guide.2.searching"), fg=theme.MUTED, bg=box["bg"]).pack(side="left")
                stop = tk.Label(top, text=w("guide.2.stop") + " ›", font=ui.fonts.body_bold, fg=ui.section["accent"],
                                bg=box["bg"], cursor="hand2")
                stop.pack(side="right")
                stop.bind("<Button-1>", lambda e: self.stop())
            elif says == "found":
                widgets.section(top, ui, w("guide.2.found"), bg=box["bg"]).pack(side="left")
            self.top = (says, top)
        # Nothing found once the search is over: said, with where to choose one (the buttons under the list).
        nothing = not self.items and not self.searching
        if nothing and (self.none is None or not self.none.winfo_exists()):
            self.none = widgets.label(box, ui, w("guide.2.none"), fg=theme.AMBER, bg=box["bg"], wrap_margin=0)
        elif not nothing and self.none is not None:
            self.none.destroy()
            self.none = None
        chosen = os.path.normcase(self.app.state.game_folder or "")

        def in_use(found):
            """True for the card of the folder PLAY starts the game from."""
            return bool(chosen) and found.kind == intake.FOLDER and os.path.normcase(found.root or "") == chosen

        drawn, self.drawn = self.drawn, {}
        order = []
        # The folder in use first, whatever else was found: Next is lit for it, so it is what the step shows on top
        # (it was the fourth card once, under the fold). The rest keep their order (sorted() is stable).
        for found in sorted(self.items or [], key=lambda f: not in_use(f)):
            # The folder in use is marked on its card.
            on = in_use(found)
            if on and self.hide_chosen:
                continue
            self._make_thumbs(found)
            thumbs = self.thumbs.get(found.path, ())
            key = os.path.normcase(found.path)
            # What the card shows comes from these three: a look makes a new Found, a pick moves the mark, and the
            # jackets come with the look (each compared by identity: a Found is never changed once made).
            made_of = (found, on, thumbs)
            old = drawn.pop(key, None)
            if (old is not None and old[0][0] is found and old[0][1] == on and old[0][2] is thumbs
                    and old[1].winfo_exists()):
                card = old[1]
            else:
                if old is not None:
                    old[1].destroy()
                card = cards.Card(box, self.app, found, chosen=on, on_choose=self.pick, on_unpack=self.unpack,
                                  on_put_back=self.put_back, thumbs=thumbs)
            self.drawn[key] = (made_of, card)
            order.append(card)
        for _, card in drawn.values():
            # A path no longer on the list (two paths found to be one game folder show once).
            card.destroy()
        # Everything in place in the list's order: packing again moves the widgets, nothing is drawn anew.
        shown = [self.top[1]] + ([self.none] if self.none is not None else []) + order
        for widget in shown:
            widget.pack_forget()
        self.top[1].pack(fill="x", pady=(0, px(12)))
        if self.none is not None:
            self.none.pack(fill="x")
        for card in order:
            card.pack(fill="x", pady=(0, px(10)))
        self.on_update()

    def _make_thumbs(self, found):
        """A ready folder's three jackets, made once into the card's size."""
        if found.path in self.thumbs or found.path not in self.pictures:
            return
        # The size of a card's line of words, so the jackets sit beside them without making the card taller.
        size = self.app.ui.px(34)
        self.thumbs[found.path] = [ImageTk.PhotoImage(p.resize((size, size), Image.LANCZOS), master=self.app.root)
                                   for p in self.pictures[found.path]]

    # ------------------------------------------------------------------------------------------- searching

    def search(self):
        """Look in the usual places on a worker thread; each path found shows at once, then with what it is."""
        # One search at a time: a new one stops the one before.
        self.stop()
        cancel = self.cancel = threading.Event()
        self.searching = True
        # The paths chosen by hand stay while the search adds what it finds.
        self.items = list(self.items or [])

        def work():
            seen = []
            try:
                # Every place looked through first (seconds), each path shown as it turns up.
                for path in find.paths(cancel=cancel):
                    seen.append(path)
                    self.app.post(lambda path=path: self._seen(path, cancel))
                # Then what each one is, in the order found (a folder's look is quick; an archive's is 7-Zip's
                # listing of its entries).
                for path in seen:
                    if cancel.is_set():
                        break
                    # Found, not picked: an archive is said from its listing alone, nothing of it taken out.
                    self._look(path, cancel, picked=False)
            except Exception:  # noqa: BLE001  (the search ends with what it found, never a stopped guide)
                log.exception("the search for client data stopped")
            self.app.post(lambda: self._ended(cancel))

        threading.Thread(target=work, daemon=True, name="find").start()
        self.paint()

    def stop(self):
        """Stop the search under way (the paths found so far stay)."""
        if self.cancel is not None:
            self.cancel.set()
        if self.searching:
            self.searching = False
            # The search's line goes at once, not when its worker next looks up from a listing.
            self.paint()

    def _seen(self, path, cancel):
        """A path the search turned up: on the list at once, as being checked."""
        if cancel is not self.cancel:
            # A search that was stopped or replaced says nothing more.
            return
        if not any(os.path.normcase(f.path) == os.path.normcase(path) for f in self.items):
            self.items.append(intake.Found(path))
            self.paint()

    def _look(self, path, cancel, picked=True):
        """What one path is (on the worker), with a ready folder's jackets, then shown. `picked`: the player chose it
        (or an unpacking made it); one the search found is an archive said from its listing alone (intake.inspect)."""
        found = intake.inspect(path, cancel=cancel, picked=picked)
        pictures = []
        if found.state == intake.READY and found.kind == intake.FOLDER:
            # Three of its own jackets: the player's game, at a glance (read here, on the worker).
            try:
                pictures = art.read_discs(g.Game(found.root), 3, seed="guide")
            except Exception:  # noqa: BLE001  (a card without its jackets still says what it is)
                log.exception("the jackets of %s could not be read", found.root)
        # Tk is touched on the window's thread only.
        self.app.post(lambda: self._looked(path, found, pictures))

    def _looked(self, path, found, pictures):
        """What a path is, in its place on the list (the path asked for may have been a folder above the game's)."""
        if pictures:
            self.pictures[found.path] = pictures
        for i, item in enumerate(self.items or []):
            if os.path.normcase(item.path) == os.path.normcase(path):
                self.items[i] = found
                break
        else:
            # A path the list no longer had (a page drawn again since): first.
            self.items = [found] + list(self.items or [])
        # Two paths that are the same game folder (a folder chosen above it, and the folder itself) show once.
        seen, kept = set(), []
        for item in self.items:
            key = os.path.normcase(item.path)
            if key not in seen:
                seen.add(key)
                kept.append(item)
        self.items = _ordered(kept)
        if (self.wanted and os.path.normcase(self.wanted) == os.path.normcase(path) and found.state == intake.READY
                and found.kind == intake.FOLDER):
            # The folder the player chose (or an unpacking made) plays: it is the one in use now.
            self.wanted = None
            self.pick(found)
            return
        self.paint()

    def _ended(self, cancel):
        """The search is over: the best folder used when none is yet, and the list without its search line."""
        if cancel is self.cancel:
            self.searching = False
        best = _best(self.items or [])
        if not self.app.state.game_folder and best is not None:
            # None chosen yet: the best folder that plays is (the original PC client first, then the most songs).
            self.pick(best)
            return
        self.paint()

    # ---------------------------------------------------------------------------------------- choosing

    def pick(self, found):
        """Use this game folder."""
        if found.state != intake.READY or found.kind != intake.FOLDER:
            # Only a game folder that plays is used; its card says why another is not.
            return
        self.app.set_folder(found.root)
        if self.on_pick is not None:
            self.on_pick()
            return
        self.paint()

    def chosen(self):
        """The Found of the folder in use, when the list has it."""
        chosen = os.path.normcase(self.app.state.game_folder or "")
        for found in self.items or []:
            if chosen and found.kind == intake.FOLDER and os.path.normcase(found.root or "") == chosen:
                return found
        return None

    def add(self, path, use=True):
        """A path the player chose (or an unpacking made): listed first as being checked, then with what it is, and
        used when it is a game folder that plays (`use`)."""
        found = intake.Found(path)
        if use:
            self.wanted = path
        # First on the list, where the player looks after choosing it.
        self.items = [found] + [f for f in (self.items or []) if os.path.normcase(f.path) != os.path.normcase(path)]
        self.paint()
        # Looked at off the window's thread (an archive's listing takes 7-Zip a moment).
        threading.Thread(target=self._look, args=(path, None), daemon=True, name="look").start()

    def choose_folder(self):
        """Windows' own folder picker, then the folder's card."""
        picked = filedialog.askdirectory(parent=self.app.root, title=self.app.words("guide.2.choose"))
        if picked:
            self.add(os.path.normpath(picked))

    def choose_archive(self):
        """Windows' own file picker for an archive, then the archive's card."""
        picked = filedialog.askopenfilename(parent=self.app.root, title=self.app.words("intake.choose_archive"),
                                            filetypes=ARCHIVE_TYPES)
        if picked:
            self.add(os.path.normpath(picked))

    def unpack(self, found):
        """Unpack the archive (its dialogs: client/unpacking.py); the game folder it makes is listed and chosen."""
        from opendmt3.client import unpacking
        made = unpacking.unpack_archive(self.app, found)
        if made:
            self.add(made)

    def put_back(self, found):
        """Put back what openDMT3 changed in that folder; its card says what it is then."""
        if put_back_folder(self.app, found):
            self.add(found.root, use=False)


def put_back_folder(app, found):
    """Put back what openDMT3 changed in a card's folder: the same question and work as Help's Put back. True when
    the work was done."""
    from opendmt3.client import actions, dialogs, playing
    w = app.words
    if app.busy or playing.game_running(app.session):
        app.set_status(w("help.restore.busy"), "warn")
        return False
    if not dialogs.ask(app, "warn", w("help.restore.title"), w("help.restore.ask"), w("help.restore.detail"),
                       w("help.restore.confirm")):
        return False
    try:
        done = actions.put_back(found.root)
    except Exception as e:  # noqa: BLE001  (the game open, a file in use: said, never swallowed)
        log.exception("putting the game's files back failed")
        app.set_status(w("status.error", error=w.error(e)), "bad")
        return False
    app.set_status(w("help.restore.done", n=len(done)) if done else w("help.restore.nothing"), "ok")
    app.refresh_checks()
    return True


def _best(items):
    """The folder to use when none is chosen: ready, the original PC client before a changed one, the most songs."""
    ready = [f for f in items if f.state == intake.READY and f.kind == intake.FOLDER]
    if not ready:
        return None
    return min(ready, key=lambda f: (f.client not in (g.ORIGINAL, g.FIXED), -(f.songs or 0)))


def _ordered(items):
    """Ready folders first (the original PC client's before a modified one's), then archives to unpack, then the ones
    being checked, then the rest; the order found within each."""
    rank = {intake.READY: 0, intake.UNPACK: 1, intake.CHECKING: 2, intake.NOT_HERE: 3}
    return sorted(items, key=lambda f: (rank.get(f.state, 4), f.client == g.MODIFIED))
