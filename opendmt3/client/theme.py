"""Colours, fonts and sizes of the launcher: the game's metal, and the game's colours where they mean something.

The surfaces are neutral gunmetal (the same family as OpenDMTQ, openDMT3's sister project for TECHNIKA Q), never
tinted by one brand colour, laid out as OpenDMTQ's launcher is: a column down the left with the mark, the menu and,
at its foot, the status and PLAY; beside it the page, its title at the top and its parts on cards. Colour comes from TECHNIKA 3's own screens and marks a section or a meaning: the title
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
BAR = "#0c0e11"         # the column down the left with the mark, the menu and PLAY, a step darker than the page
NAV_HOVER = "#15191e"   # the quiet slab under the pointer in that column's menu, between it and a card
PANEL = "#1a1f25"       # cards, and the menu's slab under the page on show
PANEL_HI = "#232931"    # a hovered or chosen row, the top of a card
RAIL = "#2b323b"        # quiet metal: buttons and tracks
RAIL_UP = "#3a434e"     # the same under the pointer
LINE = "#343c47"        # 1-pixel seams and rules
FIELD = "#0d1014"       # inside inputs and lists: a form's slot (FORMS.md)
# A form's slot (FORMS.md, the site's --slot-*): its edge at rest and under the pointer, the shade along its top inside,
# and the slot that cannot be used now (between the well and the plate, its edge quieter than the plate's seam).
SLOT_EDGE = "#3a434e"
SLOT_EDGE_HOVER = "#56616e"
SLOT_SHADE = "#07090b"
SLOT_OFF = "#14181d"
SLOT_OFF_EDGE = "#2b323b"
# A tick box's and a switch's edge under the pointer (a step past the slot's).
TICK_EDGE_HOVER = "#8a95a1"
# A banned account's plate: its edge, the problem's pink at 55 % over the slot (FORMS.md).
BAN_EDGE = "#923361"
DIVIDER = "#2b3035"     # the faint line between two rows of a card (white at 7.5 % on the card, as OpenDMTQ's)

# Text.
TEXT = "#eef2f6"        # body text
MUTED = "#aab4bf"       # hints under a setting, a field's name (FORMS.md's ash)
HINT = "#939eaa"        # what a field takes, under it: dimmer than its name (FORMS.md: 6:1 on a card)
BAD_INK = "#ff9cc8"     # what is wrong with a field, under it: a pink light enough to read (FORMS.md: 8:1)
FAINT = "#7a8592"       # disabled text and small labels (4.5:1 on the page)
STEP_TO_COME = "#6b7581"  # the guide's big numbers of the steps to come: dimmer than their names, so that only the blue
#                           ones read as taken or on show (3:1 and more on the page, as large text)
INK = "#0b0e12"         # words on a bright colour (a lime, amber or pink button)

# The game's colours.
BLUE = "#2a5ff0"        # TECHNIKA 3's title screen: the main action (white words on it)
BLUE_HI = "#5b8cff"     # the same, lit
BLUE_DEEP = "#0d2a8f"   # the dark end of its gradients and shards
LIME = "#b4f02a"        # STAR MIXING: the settings' section colour (its keys and accents), never "fine"
PINK = "#ff4fa0"        # POP MIXING: a crash, an error, removing for good
AMBER = "#ffb33d"       # something PLAY will change, a warning
CYAN = "#5fd3ff"        # the keyboard's place (focus rings)

# The theme's details (_work/theme/THEME.md), measured from TECHNIKA 3's screens and the Platinum Crew site.
# A card's edge as one line: a hairline round it, lit along its top (the light follows the cut corner down its
# diagonal), a step darker along its foot (the raised plate in one pixel).
SEAM = "#2b3139"
RIM = "#46505c"
FOOT = "#111317"
# A lamp lit for "fine", "ready", "connected": the cabinet's NET lamp (lime is STAR MIXING's, a section's colour).
NET = "#32a923"
# TECHNIKA 3's score colour (its result screen's SCORE, #e25906 on white, lifted for a dark card: 6.6:1 on PANEL).
SCORE = "#ff7f3a"
# The cabinet's lamps with their words (ID CARD, NET and PATCH at the game's foot), lit: the body's top and foot, white
# words over it at 5.2:1 and more. Off: black glass, a grey rim, grey words (5.2:1).
CHIPS = {"net": ("#0f4a1a", "#25841b"), "card": ("#014a72", "#0682a6"), "patch": ("#4c0858", "#a018a2")}
CHIP_OFF, CHIP_OFF_RIM, CHIP_OFF_INK = "#0b0d10", "#464f5a", "#7a8592"
# The DJ level's badge: a gem in its tier's colour, a tier every ten levels (the game's level table), the master's at 99.
LEVEL_TIERS = ("#85929d", "#c67c2f", "#d6c50c", "#b1c80b", "#2ddc3c", "#0ac1b1", "#0995df", "#2370f4", "#dc23ad",
               "#ed1134")
LEVEL_MASTER = "#dd8630"


def level_tier(level):
    """A DJ level's tier: one every ten levels, "master" at 99."""
    return "master" if level >= 99 else max(0, level // 10)

# A section's colour lights its head's shards, its title's tail, the rule beside its name in the menu and its main
# buttons.
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
        # The menu in the wide face, its names in English in both languages as both sites' menus and the game's are
        # (13.3 px); a step smaller where the window is too narrow for the menu in one line at the full size.
        self.nav = tkfont.Font(root, family=DISPLAY, size=10)
        self.nav_small = tkfont.Font(root, family=DISPLAY, size=9)
        # The first-start guide's step names down the menu column, in the same face (English in both languages too).
        self.step = tkfont.Font(root, family=DISPLAY, size=9)
        self.section = tkfont.Font(root, family=section[0], size=section[1])         # section headings
        self.display = tkfont.Font(root, family=DISPLAY, size=10)                    # Latin labels in the game's style
        self.display_big = tkfont.Font(root, family=DISPLAY, size=17)                # PLAY
        self.body = tkfont.Font(root, family=TEXT_FONT, size=10)                     # text
        self.body_bold = tkfont.Font(root, family=TEXT_BOLD, size=10)                # labels and buttons
        # Scores and counts in the game's heavy figures (Pretendard Bold, bundled; one width each where it has them).
        self.figures = tkfont.Font(root, family=TEXT_FONT, size=11, weight="bold")
        self.small = tkfont.Font(root, family=TEXT_FONT, size=9)                     # hints
        # A form's words (FORMS.md's launcher mapping): a field's name small and semibold, what is typed in the
        # sign-in's large fields a step larger than the page's text, a key inside a field (Show) small and semibold,
        # the sign-in's large key a step larger than a page's.
        self.label = tkfont.Font(root, family=TEXT_BOLD, size=9)                     # a field's name over it
        self.field = tkfont.Font(root, family=TEXT_FONT, size=11)                    # typed in a large field
        self.key = tkfont.Font(root, family=TEXT_BOLD, size=9)                       # a key inside a field
        self.button_lg = tkfont.Font(root, family=TEXT_BOLD, size=11)                # the sign-in's key
        tab = (TEXT_BOLD, 10) if korean else (DISPLAY, 8)
        self.dialog_tab = tkfont.Font(root, family=tab[0], size=tab[1])              # a dialog's title tab
        self.dialog_title = tkfont.Font(root, family=TEXT_BOLD, size=13)             # a dialog's question
        self.dialog_button = tkfont.Font(root, family=TEXT_BOLD, size=10)            # a dialog's buttons
        self.language = language


def scale_of(root):
    """Pixels per 1/96 inch: 1.0 at 100 % Windows scaling, 1.5 at 150 %."""
    return max(1.0, root.winfo_fpixels("1i") / 96.0)
