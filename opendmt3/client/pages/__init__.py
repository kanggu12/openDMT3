"""The launcher's pages, one module each, laid out as OpenDMTQ's launcher lays its own: a head (the page's title and a
line under it, HEADERS), then cards, one for each part of the page. Each builder fills the page area.

A setting row changes the remembered state right away (app.changed); the files in the client data change only when
PLAY runs, so nothing is written while the game might be open.
"""

from opendmt3.client.pages.about import build_about, language_options
from opendmt3.client.pages.common import (ROWS_THAT_COME, TITLES, Sections, database_trouble, group_names,
                                          main_button, rows_that_come)
from opendmt3.client.pages.help import build_help
from opendmt3.client.pages.online import build_online, lead_state, player_form, server_panel
from opendmt3.client.pages.play import build_play, refresh_checks, where_play_plays
from opendmt3.client.pages.records import build_records
from opendmt3.client.pages.settings import build_controls, build_game, build_screen, build_sound

__all__ = ["BUILDERS", "HEADERS", "ROWS_THAT_COME", "Sections", "TITLES", "build_about", "database_trouble",
           "group_names", "language_options", "lead_state", "main_button", "player_form", "refresh_checks",
           "rows_that_come", "server_panel"]


def _plain_header(key):
    """A page's head: its title (the page's name in the menu) alone. A line under it that listed the page's own cards
    said again what the title and the cards' names say."""
    def words(app):
        return TITLES[key], ""
    return words


# PLAY's head is the game's, as the site's front page has it (TECHNIKA 3 with the logo's blue 3), and its line says
# where PLAY plays, as OpenDMTQ's PLAY says the server it plays on.
HEADERS = {"play": lambda app: (app.words("play.title"), where_play_plays(app)),
           # RECORDS' line is PLAY's: where the records are, the one fact a records page needs.
           "records": lambda app: (TITLES["records"], where_play_plays(app))}
HEADERS.update({key: _plain_header(key) for key in ("screen", "sound", "controls", "game", "online", "help", "about")})


BUILDERS = {
    "records": build_records,
    "play": build_play, "screen": build_screen, "sound": build_sound, "controls": build_controls,
    "game": build_game, "online": build_online, "help": build_help, "about": build_about,
}
