"""The launcher's pages, one module each. Each builder fills the page area; HEADERS gives each page's header words.

A setting row changes the remembered state right away (app.changed); the files in the game folder change only
when PLAY runs, so nothing is written while the game might be open.
"""

from opendmt3.client.pages.about import build_about, language_options
from opendmt3.client.pages.common import _plain_header, database_trouble
from opendmt3.client.pages.help import build_help
from opendmt3.client.pages.online import build_online, player_form, server_panel
from opendmt3.client.pages.play import build_play, refresh_checks
from opendmt3.client.pages.records import build_records
from opendmt3.client.pages.settings import build_controls, build_game, build_screen, build_sound

__all__ = ["BUILDERS", "HEADERS", "build_about", "database_trouble", "language_options", "player_form",
           "refresh_checks", "server_panel"]

HEADERS = {"play": lambda app: (app.words("play.title"), app.words("app.tagline"))}
HEADERS.update({key: _plain_header(key) for key in ("screen", "sound", "controls", "game", "online", "records", "help",
                                                   "about")})


BUILDERS = {
    "records": build_records,
    "play": build_play, "screen": build_screen, "sound": build_sound, "controls": build_controls,
    "game": build_game, "online": build_online, "help": build_help, "about": build_about,
}
