"""What the launcher remembers between runs: the game folder, the player's choices, the language.

Kept in one small JSON file per Windows user (%APPDATA%\\openDMT3\\launcher.json), outside the program folder,
so an update or a reinstall keeps it. Writes go through a temporary file so a crash never leaves half of it.
"""

import json
import os
import sys
import tempfile

from opendmt3.core import game as g
from opendmt3.core.cabinet import steps, values as choices

FILE_NAME = "launcher.json"
# Bumped when a field changes meaning; an older file is read and upgraded, a newer one is refused.
VERSION = 1
LANGUAGES = ("en", "ko")
MODES = ("offline", "this_pc", "server")
# Where the game finds the built-in server (the launcher's hosting module listens there).
GAME_ADDRESS = "127.0.0.1:4725"


def config_dir():
    """The folder for the launcher's settings and logs.

    OPENDMT3_CONFIG_DIR overrides it (the tests use a temporary folder); otherwise the per-user application data
    folder on Windows, the XDG one elsewhere (for development on Linux).
    """
    override = os.environ.get("OPENDMT3_CONFIG_DIR")
    if override:
        return override
    if sys.platform == "win32":
        # Roaming application data, where per-user program settings belong on Windows.
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "openDMT3")
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "openDMT3")


def own_folder():
    """openDMT3's own folder for playing (steps.Own): the client copy, the card reader library, the settings, the
    operator data and the changed archives, beside the launcher's settings; the game folder is only read."""
    return steps.Own(os.path.join(config_dir(), "game"))


def system_language():
    """The language Windows is shown in, as the launcher's: "ko" when the user's first display language is Korean,
    "en" for any other (as the OpenDMTQ PC client decides it). "en" off Windows, so no test depends on the computer's
    language."""
    if sys.platform != "win32":
        return "en"
    try:
        tag = _windows_display_language()
    except (AttributeError, OSError, ValueError):
        # No answer from Windows: English, the launcher's own first language.
        return "en"
    # "ko-KR", "ko": the language is the part before the first hyphen.
    return "ko" if tag.split("-")[0].lower() == "ko" else "en"


def _windows_display_language():
    """The first of the user's display languages as Windows names it ("ko-KR"), or "ko"/"en" from the older call."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.windll.kernel32
    mui_language_name = 0x8
    count, size = wintypes.ULONG(0), wintypes.ULONG(0)
    # Asked twice: first for the size of the list, then for the list itself (names, each ended by a NUL).
    if kernel.GetUserPreferredUILanguages(mui_language_name, ctypes.byref(count), None, ctypes.byref(size)) and size.value:
        names = ctypes.create_unicode_buffer(size.value)
        if kernel.GetUserPreferredUILanguages(mui_language_name, ctypes.byref(count), names, ctypes.byref(size)) \
                and count.value and names.value:
            # The buffer's value stops at the first NUL: the first language alone.
            return names.value
    # Older Windows: the display language as a number, whose low 10 bits name the language (0x12 is Korean).
    return "ko" if kernel.GetUserDefaultUILanguage() & 0x3FF == 0x12 else "en"


class StateError(Exception):
    """The settings file is from a newer launcher (`newer`), or broken beyond reading."""

    def __init__(self, message, path, newer=False):
        super().__init__(message)
        self.path, self.newer = path, newer


class LauncherState:
    """The remembered settings. Each field has a safe default, so a missing file means a first start."""

    def __init__(self):
        self.game_folder = None          # the folder the player chose (the game folder or one above it)
        self.picked_language = None      # the language the player chose; None: the one Windows is shown in
        self.values = choices.normalize({})   # screen and sound choices, all filled in
        self.unlock = True               # show the patterns the cabinet hid from guests
        self.guide_done = False          # the first-start guide was finished or skipped
        self.last_session = None         # {"seconds": .., "exit_code": .., "dumps": n} of the last game run
        self.mode = "offline"            # "this_pc": the built-in server; "server": someone's server; "offline"
        self.player = None               # this PC: the ID whose card goes in the reader at PLAY (None: a guest)
        self.server_url = None           # another server: its site's address (http://host:port)
        self.remote = None               # another server: {login_id, dj_name, card, token, game} after signing in
        self.lan = False                 # this PC: open the built-in server to the other PCs on its network as well

    # ------------------------------------------------------------------------------------------- files

    @property
    def language(self):
        """The launcher's language: the one the player chose, else the one Windows is shown in (system_language)."""
        return self.picked_language or system_language()

    @language.setter
    def language(self, value):
        # Setting it is the player's choice, kept from then on; anything but a known language goes back to Windows'.
        self.picked_language = value if value in LANGUAGES else None

    @classmethod
    def path(cls):
        return os.path.join(config_dir(), FILE_NAME)

    @classmethod
    def load(cls, path=None):
        """The saved state, or a fresh one when there is no file yet."""
        path = path or cls.path()
        state = cls()
        if not os.path.isfile(path):
            return state
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            raise StateError("cannot read %s: %s" % (path, e), path) from None
        if not isinstance(data, dict):
            raise StateError("cannot read %s: not a settings file" % path, path)
        version = data.get("version", 1)
        if not isinstance(version, int) or isinstance(version, bool):
            # A version that is not a whole number is damage, not a newer launcher.
            raise StateError("cannot read %s: its version is %r" % (path, version), path)
        if version > VERSION:
            # A newer launcher wrote it; reading it with old rules could drop what it added.
            raise StateError("%s is from a newer openDMT3; update the launcher" % path, path, newer=True)
        try:
            return cls._from(data, state)
        except (TypeError, AttributeError, ValueError) as e:
            # A field of the wrong kind (a hand-edited file): the same as a file that cannot be read.
            raise StateError("cannot read %s: %s" % (path, e), path) from None

    @classmethod
    def _from(cls, data, state):
        """Fill `state` from a settings file's data (any field of the wrong kind raises)."""
        state.game_folder = data.get("game_folder") or None
        # A file the earliest versions wrote always has one: their guide asked, so it is taken as the player's choice.
        state.picked_language = data.get("language") if data.get("language") in LANGUAGES else None
        try:
            state.values = choices.normalize(data.get("values") or {})
        except choices.ChoiceError:
            # A hand-edited file with a bad value: fall back to the defaults instead of refusing to start.
            state.values = choices.normalize({})
        state.unlock = bool(data.get("unlock", True))
        state.guide_done = bool(data.get("guide_done", False))
        state.last_session = data.get("last_session")
        state.mode = data.get("mode") if data.get("mode") in MODES else "offline"
        state.player = data.get("player") or None
        state.server_url = data.get("server_url") or None
        state.remote = data.get("remote") if isinstance(data.get("remote"), dict) else None
        state.lan = bool(data.get("lan", False))
        return state

    def save(self, path=None):
        """Write the state through a temporary file in the same folder, then swap it in."""
        path = path or self.path()
        folder = os.path.dirname(path)
        os.makedirs(folder, exist_ok=True)
        data = {
            "version": VERSION,
            "game_folder": self.game_folder,
            "language": self.picked_language,
            "values": self.values,
            "unlock": self.unlock,
            "guide_done": self.guide_done,
            "last_session": self.last_session,
            "mode": self.mode,
            "player": self.player,
            "server_url": self.server_url,
            "remote": self.remote,
            "lan": self.lan,
        }
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".launcher-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)

    # -------------------------------------------------------------------------------------------- views

    def set_value(self, name, value):
        """Change one choice; a value the launcher does not offer raises ChoiceError and changes nothing."""
        merged = dict(self.values)
        merged[name] = value
        self.values = choices.normalize(merged)

    def options(self):
        """The setup options the choices amount to.

        Playing on this PC or on another server points the game at that server and puts a card in; offline the game
        keeps its own server address. openDMT3's library (the card reader, the files it gives the game and the
        in-game layer) is used either way: offline its reader simply has no card.
        """
        if self.mode == "this_pc":
            return steps.Options(values=self.values, unlock=self.unlock, server=GAME_ADDRESS, card_reader=True)
        if self.mode == "server" and self.remote and self.remote.get("game"):
            return steps.Options(values=self.values, unlock=self.unlock, server=self.remote["game"], card_reader=True)
        return steps.Options(values=self.values, unlock=self.unlock, server="official", card_reader=False)

    def own(self):
        """openDMT3's own folder for playing (own_folder())."""
        return own_folder()

    def game(self):
        """The game folder, found at or below the chosen folder; GameError when it is missing or gone."""
        if not self.game_folder:
            raise g.GameError("no game folder chosen yet", "error.game.not_chosen")
        return g.Game.find(self.game_folder)
