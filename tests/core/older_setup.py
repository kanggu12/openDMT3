"""What openDMT3 wrote into a game folder at PLAY before it only read the folder, kept for the tests of reading such
a folder and putting it back (PLAY now writes only openDMT3's own folder: opendmt3/core/cabinet/steps.py).

Each step answered two questions: is the folder already the way the options ask (status), and if not, make it so
(apply). Every game file a step wrote was recorded in the backup first, so restore can undo all of it.
"""

import os
import tempfile

from opendmt3.core import game as g
from opendmt3.core.cabinet import display, native, values as choices
from opendmt3.core.formats import game_settings, pak, settings_ini, stage_lists


class Options:
    """What the person asked for; the defaults are what most players want."""

    def __init__(self, values=None, unlock=True, server=None, display_mode=None, card_reader=False):
        # The launcher's choices (screen, sound), checked now so a bad one fails before any file is touched.
        given = dict(values or {})
        # The older keyword (from the command line's --window) still works and wins over values.
        if display_mode is not None:
            given["display_mode"] = display_mode
        self.values = choices.normalize(given)
        self.unlock = unlock               # show every hidden STAR and POP pattern without a card
        self.server = server               # None: leave as is; "official": the game's own; "host:port": another
        self.card_reader = card_reader     # a card goes in (logins by card); openDMT3's library goes in either way

    @property
    def display_mode(self):
        """'fullscreen' (borderless over the whole monitor) or 'window' (a framed window)."""
        return self.values["display_mode"]


class Status:
    def __init__(self, done, detail):
        self.done = done
        self.detail = detail


def _write_atomically(path, data):
    """Write next to the target and swap it in, so a crash never leaves half a file behind."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".opendmt3-")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


# ------------------------------------------------------------------------------------------------ free play

class FreePlay:
    """The operator data folder (rankings, bookkeeping, operator settings) with free play on."""

    name = "free play"
    GAME_FILE = os.path.join(g.DATA_DIR, "GAME", "game")

    def _seed(self, game, backup):
        """Fill TECHNIKA\\ from the game folder's own operator data (file\\), if TECHNIKA\\ does not exist yet.

        Every file is recorded before it is written, so restoring removes the folder again.
        """
        src = game.path("file")
        if os.path.isfile(os.path.join(src, "game")):
            for name in sorted(os.listdir(src)):
                # The settings and the bookkeeping have their own folders; everything else is a ranking.
                sub = {"game": "GAME", "book": "BOOK"}.get(name, "RANK")
                rel = os.path.join(g.DATA_DIR, sub, name)
                backup.protect(rel)
                with open(os.path.join(src, name), "rb") as f:
                    _write_atomically(game.path(rel), f.read())
            return "copied from file\\"
        # No operator data at all: the operator settings with the game's defaults, and empty folders for the
        # bookkeeping and rankings the game writes as it is played.
        for sub in ("BOOK", "RANK"):
            backup.protect_folder(os.path.join(g.DATA_DIR, sub))
            os.makedirs(game.path(g.DATA_DIR, sub), exist_ok=True)
        backup.protect(self.GAME_FILE)
        _write_atomically(game.path(self.GAME_FILE), game_settings.GameSettings().build())
        return "new"

    def status(self, game, backup, options):
        path = game.path(self.GAME_FILE)
        if not os.path.isfile(path):
            return Status(False, "no %s yet" % self.GAME_FILE)
        with open(path, "rb") as f:
            s = game_settings.GameSettings.parse(f.read())
        return Status(s.free_play == 1, "free play %s" % ("on" if s.free_play == 1 else "off"))

    def apply(self, game, backup, options):
        how = ""
        if not os.path.isfile(game.path(self.GAME_FILE)):
            how = self._seed(game, backup) + ", "
        # Recorded before free play goes on (a no-op when seeding just recorded it as new).
        backup.protect(self.GAME_FILE)
        with open(game.path(self.GAME_FILE), "rb") as f:
            s = game_settings.GameSettings.parse(f.read())
        s.free_play = 1
        _write_atomically(game.path(self.GAME_FILE), s.build())
        return how + "free play on"


# ------------------------------------------------------------------------------------------------- settings

class Settings:
    """Resource\\config\\setting.ini: the game's own file with only what a PC needs changed."""

    name = "settings"
    REL = g.SETTINGS.replace(os.sep, "/")
    SOURCE = "Resource\\Config\\setting.ini"

    def desired(self, game, backup, options):
        with game.open_pak(backup.original("pack/Config.pak")) as p:
            entry = p.find(self.SOURCE)
            if entry is None:
                raise g.GameError("the file with the game's settings has no %s" % self.SOURCE, "error.game.config",
                                  name=self.SOURCE)
            text = settings_ini.decode(p.read(entry))
        changes = {
            # A window: exclusive full screen fails on recent Windows and graphics drivers.
            "fullscreen": "false",
            # Rankings, bookkeeping and operator settings in TECHNIKA\\ (no spaces: the game drops them).
            "rankFilePath": g.DATA_DIR + "/RANK/",
            "bookkeepingFilePath": g.DATA_DIR + "/BOOK/",
            "gameSettingFilePath": g.DATA_DIR + "/GAME/",
        }
        # The player's choices: borderless or framed, window size, sync, glow, videos, pointer, volumes.
        changes.update(choices.ini_changes(options.values))
        text = settings_ini.set_values(text, changes)
        return settings_ini.encode(text)

    def status(self, game, backup, options):
        path = game.path(g.SETTINGS)
        if not os.path.isfile(path):
            return Status(False, "missing (the PC client closes at once without it)")
        with open(path, "rb") as f:
            current = f.read()
        if current == self.desired(game, backup, options):
            v = options.values
            # One line a person can read back: how the screen opens and how loud it plays.
            shape = "borderless over the whole monitor" if v["display_mode"] == "fullscreen" else "window " + v["window_size"]
            return Status(True, "%s, music %d%%, keys %d%%" % (shape, v["music_volume"], v["key_volume"]))
        return Status(False, "differs from what the options ask")

    def apply(self, game, backup, options):
        backup.protect(self.REL)
        _write_atomically(game.path(g.SETTINGS), self.desired(game, backup, options))
        return "written"


# -------------------------------------------------------------------------------------------------- display

class DisplayFix:
    """A copy of the client that fills the screen and reads the mouse correctly in a window."""

    name = "display fix"

    def _source(self, game):
        """What the fixed client is made from: the PC client, or else an earlier fix (it only lacks a flag)."""
        source = game.base_client()
        if source is None and game.client_build(g.FIXED_EXE)[0] == g.PC_BUILD_DISPLAY_FIX_EARLIER:
            source = game.path(g.FIXED_EXE)
        return source

    def status(self, game, backup, options):
        digest, _ = game.client_build(g.FIXED_EXE)
        if digest == g.PC_BUILD_DISPLAY_FIX:
            return Status(True, '"%s" ready' % g.FIXED_EXE)
        if self._source(game) is None:
            return Status(True, "skipped: no PC client to start from")
        if digest == g.PC_BUILD_DISPLAY_FIX_EARLIER:
            return Status(False, '"%s" from an earlier openDMT3: made again' % g.FIXED_EXE)
        return Status(False, '"%s" not made yet' % g.FIXED_EXE)

    def apply(self, game, backup, options):
        source = self._source(game)
        if source is None:
            return "skipped"
        backup.protect(g.FIXED_EXE)
        with open(source, "rb") as f:
            fixed = display.patch(f.read())
        _write_atomically(game.path(g.FIXED_EXE), fixed)
        return 'made "%s"' % g.FIXED_EXE


# ------------------------------------------------------------------------------------------------- unlocks

class GuestUnlock:
    """DiscInfo.pak with every hidden STAR and POP pattern shown (or put back as it was)."""

    name = "guest unlock"
    REL = "pack/DiscInfo.pak"

    def _hidden(self, game, path):
        total = 0
        with game.open_pak(path) as p:
            for e in p.entries:
                if stage_lists.is_stage_list(e.name):
                    total += stage_lists.count_hidden(p.read(e))
        return total

    def status(self, game, backup, options):
        hidden = self._hidden(game, game.pak_path("DiscInfo"))
        if options.unlock:
            return Status(hidden == 0, "every pattern shown" if hidden == 0 else "%d patterns hidden" % hidden)
        return Status(not backup.changed(self.REL), "as the game has it (%d patterns hidden)" % hidden)

    def apply(self, game, backup, options):
        backup.protect(self.REL)
        if not options.unlock:
            backup.put_back(self.REL)
            return "put back"
        original = backup.original(self.REL)
        replacements = {}
        with game.open_pak(original) as p:
            for e in p.entries:
                if stage_lists.is_stage_list(e.name):
                    replacements[e.name] = stage_lists.show_all(p.read(e))
        tmp = game.pak_path("DiscInfo") + ".opendmt3-new"
        pak.rebuild_pak(original, tmp, replacements, game.table())
        os.replace(tmp, game.pak_path("DiscInfo"))
        return "every pattern shown (%d lists)" % len(replacements)


# -------------------------------------------------------------------------------------------- server address

class ServerAddress:
    """Where the client connects: Config.pak's networksetting.ini."""

    name = "server address"
    REL = "pack/Config.pak"
    SOURCE = "Resource\\Config\\networksetting.ini"

    def current(self, game, path=None):
        with game.open_pak(path or game.pak_path("Config")) as p:
            text = p.read(p.find(self.SOURCE)).decode("ascii")
        return settings_ini.get_value(text, "serverip"), settings_ini.get_value(text, "port")

    def status(self, game, backup, options):
        ip, port = self.current(game)
        where = "%s:%s" % (ip, port)
        if options.server is None:
            return Status(True, where)
        if options.server == "official":
            return Status(not backup.changed(self.REL), where)
        return Status(where == options.server, where)

    def apply(self, game, backup, options):
        if options.server is None:
            return "unchanged"
        backup.protect(self.REL)
        if options.server == "official":
            backup.put_back(self.REL)
            return "put back"
        host, _, port = options.server.rpartition(":")
        if not host or not port.isdigit():
            raise g.GameError("server address must be host:port, not %r" % options.server, "error.game.server_address",
                              value=options.server)
        original = backup.original(self.REL)
        with game.open_pak(original) as p:
            entry = p.find(self.SOURCE)
            text = p.read(entry).decode("ascii")
        text = settings_ini.set_values(text, {"serverip": host, "port": port})
        tmp = game.pak_path("Config") + ".opendmt3-new"
        pak.rebuild_pak(original, tmp, {entry.name: text.encode("ascii")}, game.table())
        os.replace(tmp, game.pak_path("Config"))
        return "now %s" % options.server


# ---------------------------------------------------------------------------------------------- card reader

class CardReader:
    """CRT_R1.dll: openDMT3's library in place of the cabinet's card reader, in every way of playing, with the faces
    its in-game layer writes in beside it (and their licences).

    The game loads this library by name before its own code runs. It is the card reader (a card is a text file the
    launcher writes: the game logs a player in only by card in this build) and openDMT3's in-game layer (the bar with
    the menu and the X, the question before quitting, the toast, the frame rate chip, the pointer, the sound device,
    frame pacing, the picture's filters). Offline there is no card file, so the reader is empty and the game plays
    with NO ID CARD as with the cabinet's own reader.
    """

    name = "game library"
    REL = "CRT_R1.dll"
    # The layer's words are in the launcher's own faces, loaded by the DLL for the game's process only: Pretendard
    # Bold (labels) and Regular (lines), and DMT3 Wide (the product's name), each family with its licence.
    FONT = "openDMT3-Pretendard-Bold.ttf"
    FONT_REGULAR = "openDMT3-Pretendard-Regular.ttf"
    FONT_WIDE = "openDMT3-DMT3Wide.ttf"
    LICENCE = "openDMT3-Pretendard-OFL.txt"
    LICENCE_WIDE = "openDMT3-Saira-OFL.txt"
    FILES = (REL, FONT, FONT_REGULAR, FONT_WIDE, LICENCE, LICENCE_WIDE)

    def _sources(self):
        """{file in the game folder: openDMT3's copy}, or None when this is not a build that has the library."""
        ours = native.card_reader()
        if ours is None:
            return None
        return {self.REL: ours, self.FONT: native.font(), self.FONT_REGULAR: native.font_regular(),
                self.FONT_WIDE: native.font_wide(), self.LICENCE: native.font_licence(),
                self.LICENCE_WIDE: native.font_wide_licence()}

    def status(self, game, backup, options):
        sources = self._sources()
        if sources is None:
            if options.card_reader:
                return Status(False, "openDMT3's card reader is not part of this build")
            # Running from a copy of the repository: offline the cabinet's own reader plays as before.
            return Status(not backup.changed(self.REL), "the cabinet's card reader (no openDMT3 library in this copy)")
        done = all(os.path.isfile(game.path(rel)) and g.sha256_file(game.path(rel)) == g.sha256_file(src)
                   for rel, src in sources.items())
        if not done:
            return Status(False, "the cabinet's card reader")
        if options.card_reader:
            return Status(True, "openDMT3's library: the card reader and the in-game menu")
        return Status(True, "openDMT3's library: the in-game menu, no card (NO ID CARD)")

    def apply(self, game, backup, options):
        sources = self._sources()
        if sources is None:
            if options.card_reader:
                raise g.GameError("openDMT3's card reader is not part of this build", "error.game.no_card_reader")
            # Offline from a copy of the repository: the cabinet's own reader, as before.
            backup.protect(self.REL)
            backup.put_back(self.REL)
            return "put back"
        for rel, src in sources.items():
            # Each file recorded first (the faces and their licences as new files, so putting back removes them).
            backup.protect(rel)
            with open(src, "rb") as f:
                _write_atomically(game.path(rel), f.read())
        return "openDMT3's library in place"


# The order matters: the settings point at the data folder, and the display fix expects borderless settings.
STEPS = [FreePlay(), Settings(), DisplayFix(), GuestUnlock(), ServerAddress(), CardReader()]
# Files recorded before any step runs, so a setup made by hand before this tool keeps its real originals.
# Config.pak is left out: it is large and only changes when a server address is asked for, which records it.
MANAGED = [Settings.REL, g.FIXED_EXE, GuestUnlock.REL] + list(CardReader.FILES)
