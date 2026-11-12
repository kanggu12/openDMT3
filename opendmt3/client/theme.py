"""Colours, fonts and sizes of the launcher: the game's metal, and the game's colours where they mean something.

The surfaces are neutral gunmetal (the same family as OpenDMTQ, openDMT3's sister project for TECHNIKA Q), never
tinted by one brand colour. Colour comes from TECHNIKA 3's own screens and marks a section or a meaning: the title
screen's electric blue for PLAY, STAR MIXING's lime for the cabinet's settings, POP MIXING's pink for playing
online, and amber for the tools. Lime, amber and pink also say "fine", "will change" and "problem" in checks.

Titles stand upright in heavy wide letters with a chrome face, as the TECHNIKA 3 logo does (OpenDMTQ's lean: the
TECHNIKA Q logo leans). Fonts are bundled under open licences: DMT3 Wide (cut from Saira) for Latin titles and
Pretendard for text in both languages. There is no icon font: the few marks (lamps, plates) are drawn in art.py.
"""

import os
import sys

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
FONT_DIR = os.path.join(ASSETS, "fonts")

# Surfaces, darkest first: gunmetal, a step lighter for each layer that sits on another.
BG = "#101317"          # the window behind everything
SIDEBAR = "#0c0e11"     # the menu column, a step darker than the page
PANEL = "#1a1f25"       # cards and the bottom bar
PANEL_HI = "#232931"    # a hovered or chosen row, the top of a card
RAIL = "#2b323b"        # quiet metal: buttons and tracks
RAIL_UP = "#3a434e"     # the same under the pointer
LINE = "#343c47"        # 1-pixel seams and rules
FIELD = "#0d1014"       # inside inputs and lists

# Text.
TEXT = "#eef2f6"        # body text
MUTED = "#aab4bf"       # hints under a setting
FAINT = "#7a8592"       # disabled text and small labels (4.5:1 on the page)
INK = "#0b0e12"         # words on a bright colour (a lime, amber or pink button)

# The game's colours.
BLUE = "#2a5ff0"        # TECHNIKA 3's title screen: the main action (white words on it)
BLUE_HI = "#5b8cff"     # the same, lit
BLUE_DEEP = "#0d2a8f"   # the dark end of its gradients and shards
LIME = "#b4f02a"        # STAR MIXING: "fine" in checks
PINK = "#ff4fa0"        # POP MIXING: a crash, an error, removing for good
AMBER = "#ffb33d"       # something PLAY will change, a warning
CYAN = "#5fd3ff"        # the keyboard's place (focus rings)

# A section's colour lights its header's shards, its title's tail, its menu entry and its main buttons.
SECTION_COLOURS = {
    "technika": {"accent": BLUE_HI, "light": "#2f6bff", "deep": BLUE_DEEP, "fill": BLUE, "ink": "#ffffff"},
    "star": {"accent": LIME, "light": "#8fcc12", "deep": "#2c4406", "fill": LIME, "ink": INK},
    "pop": {"accent": PINK, "light": "#e8338a", "deep": "#5c0c35", "fill": PINK, "ink": INK},
    "console": {"accent": AMBER, "light": "#e3961f", "deep": "#4f3306", "fill": AMBER, "ink": INK},
}
# Which section each page of the launcher belongs to.
PAGE_SECTIONS = {"play": "technika", "screen": "star", "sound": "star", "controls": "star", "game": "star",
                 "online": "pop", "records": "pop", "help": "console", "about": "console"}


def section_colours(page):
    """The colours of the section a page belongs to (PLAY's blue for anything unknown)."""
    return SECTION_COLOURS[PAGE_SECTIONS.get(page, "technika")]


# Bundled font files and the family names Windows and fontconfig give them.
FONT_FILES = ("DMT3Wide-Regular.ttf", "Pretendard-Regular.ttf", "Pretendard-SemiBold.ttf", "Pretendard-Bold.ttf")
DISPLAY = "DMT3 Wide"
TEXT_FONT = "Pretendard"
TEXT_BOLD = "Pretendard SemiBold"
# Files for the titles drawn as pictures (art.py): Latin in the wide face, Korean in Pretendard Bold.
WIDE_FILE = os.path.join(FONT_DIR, "DMT3Wide-Regular.ttf")
HANGUL_TITLE_FILE = os.path.join(FONT_DIR, "Pretendard-Bold.ttf")
TEXT_BOLD_FILE = os.path.join(FONT_DIR, "Pretendard-SemiBold.ttf")


def register_fonts():
    """Make the bundled fonts usable by Tk in this process only (nothing is installed on the PC).

    On Windows each file is added as a private font of this process. On Linux (development and the test
    container) the files must already be known to fontconfig; the container copies them in.
    """
    if sys.platform != "win32":
        return
    import ctypes
    # FR_PRIVATE: only this process sees the font, and it goes away when the launcher closes.
    fr_private = 0x10
    for name in FONT_FILES:
        ctypes.windll.gdi32.AddFontResourceExW(os.path.join(FONT_DIR, name), fr_private, 0)


class Fonts:
    """The named fonts, sized for the window's DPI and chosen for the language.

    DMT3 Wide has no Hangul, so in Korean the headings use Pretendard SemiBold at a size that matches the wide
    face's height; Latin-only labels (PLAY, the guide's step names) stay wide in both languages.
    """

    def __init__(self, root, language):
        import tkinter.font as tkfont
        korean = language == "ko"
        section = (TEXT_BOLD, 10) if korean else (DISPLAY, 8)
        self.title = tkfont.Font(root, family=TEXT_BOLD if korean else DISPLAY, size=21 if korean else 18)
        self.section = tkfont.Font(root, family=section[0], size=section[1])         # section headings
        self.display = tkfont.Font(root, family=DISPLAY, size=10)                    # Latin labels in the game's style
        self.display_big = tkfont.Font(root, family=DISPLAY, size=17)                # PLAY
        self.body = tkfont.Font(root, family=TEXT_FONT, size=10)                     # text
        self.body_bold = tkfont.Font(root, family=TEXT_BOLD, size=10)                # labels and buttons
        self.small = tkfont.Font(root, family=TEXT_FONT, size=9)                     # hints
        tab = (TEXT_BOLD, 10) if korean else (DISPLAY, 8)
        self.dialog_tab = tkfont.Font(root, family=tab[0], size=tab[1])              # a dialog's title tab
        self.dialog_title = tkfont.Font(root, family=TEXT_BOLD, size=13)             # a dialog's question
        self.dialog_button = tkfont.Font(root, family=TEXT_BOLD, size=10)            # a dialog's buttons
        self.language = language


def scale_of(root):
    """Pixels per 1/96 inch: 1.0 at 100 % Windows scaling, 1.5 at 150 %."""
    return max(1.0, root.winfo_fpixels("1i") / 96.0)
