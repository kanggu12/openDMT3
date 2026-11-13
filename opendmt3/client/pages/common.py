"""What the pages share: the pages' names, a card stacked under the ones before it, a page's main button, the rows a
choice brings or takes, and what a page shows when this PC's database cannot be opened."""

import os

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


def rows_that_come(page):
    """The names of ROWS_THAT_COME[page] in both languages, for widgets.fit_names."""
    from opendmt3.client import i18n
    return [words for key in ROWS_THAT_COME.get(page, ()) for words in i18n.TEXT[key] if words]


def card(parent, ui, title=None, last=False):
    """A card with its title, stacked under the ones before it with the gap between cards."""
    from opendmt3.client import widgets
    made = widgets.Card(parent, ui, title=title)
    made.pack(fill="x", pady=(0, 0 if last else ui.px(CARD_GAP)))
    return made


def main_button(app, parent, text, command):
    """A page's main action (Connect, Sign in, Add a player, the launcher's update) as a button: lit in its page's colour
    while PLAY is not, and quiet beside a lit PLAY, so that a screen has one lit main action, as OpenDMTQ's launcher has
    it. It follows PLAY as PLAY changes (app._paint_play); the guide's steps, which have no PLAY, light it."""
    from opendmt3.client import widgets
    lit = getattr(app, "play_button", None) is not None and app.play_button.winfo_exists() and app.play_lit()
    button = widgets.Button(parent, app.ui, text, command, kind="secondary" if lit else "primary")
    app.main_buttons.append(button)
    return button


def database_trouble(app, parent, error, bg=None):
    """Where this PC's players would be listed, when its database cannot be opened (damaged, or from a newer
    openDMT3): what is wrong, how to put its newest daily backup back (a damaged one; none helps with a newer one),
    and the button that opens its folder. The launcher goes on working."""
    from opendmt3.client import actions, theme, widgets
    ui, w = app.ui, app.words
    # On the card or the page it is said on.
    bg = bg or parent.cget("bg")
    widgets.label(parent, ui, w.error(error), fg=theme.PINK, bg=bg, wrap_margin=0).pack(fill="x")
    if getattr(error, "key", None) != "error.host.db.newer":
        # A database from a newer openDMT3 is whole: its own line says what to do, and no backup is put back.
        widgets.label(parent, ui, w("db.broken.hint"), font=ui.fonts.small, fg=theme.MUTED, bg=bg,
                      wrap_margin=0).pack(fill="x", pady=(ui.px(6), 0))
    folder = os.path.dirname(app.host.path)
    widgets.Button(parent, ui, w("db.broken.open"), lambda: actions.open_folder(folder)).pack(
        anchor="w", pady=(ui.px(8), 0))
