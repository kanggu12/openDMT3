"""Programs openDMT3 builds from its own C source and ships with the launcher (native/ in the repository).

They sit in bin/ next to this module in a build; when running from source without a build there are none, and
the steps that need them say so instead of failing later.
"""

import os

BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")


def card_reader():
    """openDMT3's CRT_R1.dll (native/cardreader: the card reader and the in-game layer), or None when this is not a build that has it."""
    path = os.environ.get("OPENDMT3_CARD_READER") or os.path.join(BIN, "CRT_R1.dll")
    return path if os.path.isfile(path) else None


# The notices of the code built into CRT_R1.dll (the picture's passes and the compiler's runtime, with their licences),
# which native/cardreader/build.sh writes beside it and a build keeps beside it in bin/.
NOTICES = "card-reader-NOTICES.txt"


def notices():
    """The library's notices beside the library in use (bin/ in a build, or beside OPENDMT3_CARD_READER's), or None
    when there are none there (a library a test made)."""
    library = card_reader()
    # The same folder as the library: the notices are made with it and travel with it.
    path = os.path.join(os.path.dirname(library), NOTICES) if library else os.path.join(BIN, NOTICES)
    return path if os.path.isfile(path) else None


# The Sound page's OpenAL Soft mixer (native/openal/build.sh): DSOAL and OpenAL Soft with their notices, which a build
# keeps in bin/ beside the card reader library; PLAY puts them beside its copy, where the in-game layer loads them
# from when the mixer is chosen (native/cardreader/openal.c).
OPENAL_FILES = ("dsoal-aldrv.dll", "openDMT3-dsoal.dll", "openal-NOTICES.txt")


def openal():
    """{file name: path} of DSOAL and OpenAL Soft with their notices in this build (bin/, or the folder
    OPENDMT3_OPENAL_DIR names), or an empty dict when the build lacks any of them (a copy of the repository: the mixer
    then always finds them missing and Windows' DirectSound plays)."""
    folder = os.environ.get("OPENDMT3_OPENAL_DIR") or BIN
    found = {name: os.path.join(folder, name) for name in OPENAL_FILES}
    # All three or none: the libraries never go without their notices.
    return found if all(os.path.isfile(path) for path in found.values()) else {}


# The launcher's own fonts, as files (a build copies the one the in-game layer uses beside the DLL in bin/; a copy of
# the repository has them in the launcher's assets).
_ASSET_FONTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                            "client", "assets", "fonts")


def font():
    """Pretendard Bold, the face the in-game layer writes in (bin/ in a build, the launcher's assets otherwise)."""
    kept = os.path.join(BIN, "Pretendard-Bold.ttf")
    return kept if os.path.isfile(kept) else os.path.join(_ASSET_FONTS, "Pretendard-Bold.ttf")


def font_licence():
    """The SIL Open Font License that comes with Pretendard, beside it wherever the font goes."""
    kept = os.path.join(BIN, "Pretendard-OFL.txt")
    return kept if os.path.isfile(kept) else os.path.join(_ASSET_FONTS, "Pretendard-OFL.txt")


def _asset(name):
    """One of the launcher's font files: bin/'s copy in a build that has one, the launcher's assets otherwise."""
    kept = os.path.join(BIN, name)
    return kept if os.path.isfile(kept) else os.path.join(_ASSET_FONTS, name)


def font_regular():
    """Pretendard Regular, the in-game layer's lines of text (the game writes its own messages in a regular face)."""
    return _asset("Pretendard-Regular.ttf")


def font_wide():
    """DMT3 Wide, the launcher's wordmark face: the product's name on the in-game bar and the frame rate's number."""
    return _asset("DMT3Wide-Regular.ttf")


def font_wide_licence():
    """The SIL Open Font License of Saira, which DMT3 Wide is made from, beside it wherever it goes."""
    return _asset("Saira-OFL.txt")
