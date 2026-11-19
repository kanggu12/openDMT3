"""The theme's colours and pictures, without a window: words stay readable on every fill, and the pictures the
dialogs and buttons are made of come out at the size asked for."""

import importlib
import unittest

try:
    # Only whether this Python has Tk: a server's may not (the launcher brings its own), and the launcher's pictures
    # are not its business.
    importlib.import_module("tkinter")
except ImportError as e:
    raise unittest.SkipTest("needs Tk, the launcher's window toolkit (%s)" % e)

# Outside the question above: a module of the launcher's that fails to import for a fault of its own is an error of
# this file's, never a skip said to be for Tk.
from opendmt3.client import art, dialogs, snapshot, theme, widgets  # noqa: E402


def luminance(hex_colour):
    """WCAG relative luminance of #rrggbb."""
    def channel(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = art._rgb(hex_colour)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def middle(top, bottom):
    """The colour halfway down a gradient, where the words sit."""
    ta, tb = art._rgb(top), art._rgb(bottom)
    return "#%02x%02x%02x" % tuple((x + y) // 2 for x, y in zip(ta, tb))


class ContrastTest(unittest.TestCase):
    """Text on the launcher's and the site's surfaces reaches 4.5:1 (WCAG AA for normal text)."""

    def test_words_on_every_button(self):
        for look, colours in art.BUTTON_LOOKS.items():
            for state in ("normal", "hover", "pressed"):
                words = colours.get("hover_text", colours["text"]) if state != "normal" else colours["text"]
                ratio = contrast(words, middle(*colours[state]))
                self.assertGreaterEqual(ratio, 4.5, "%s %s: %.2f" % (look, state, ratio))

    def test_the_dialog_tabs(self):
        for kind, style in dialogs.KINDS.items():
            ratio = contrast(theme.INK, middle(*style["tab"]))
            self.assertGreaterEqual(ratio, 4.5, "%s: %.2f" % (kind, ratio))

    def test_main_buttons_in_every_section(self):
        for name, colours in theme.SECTION_COLOURS.items():
            ratio = contrast(colours["ink"], colours["fill"])
            self.assertGreaterEqual(ratio, 4.5, "%s: %.2f" % (name, ratio))

    def test_text_on_the_surfaces(self):
        # The bar across the top (the menu's names), the page, the cards and a chosen row.
        for surface in (theme.BG, theme.BAR, theme.PANEL, theme.PANEL_HI):
            for text, least in ((theme.TEXT, 4.5), (theme.MUTED, 4.5), (theme.FAINT, 3.0)):
                self.assertGreaterEqual(contrast(text, surface), least, "%s on %s" % (text, surface))
        # The guide's big numbers of the steps to come, under the bar: large text, 3:1.
        self.assertGreaterEqual(contrast(theme.STEP_TO_COME, theme.BG), 3.0)
        # The rule under the page on show: each section's colour reads on the bar.
        for name, colours in theme.SECTION_COLOURS.items():
            self.assertGreaterEqual(contrast(colours["accent"], theme.BAR), 3.0, name)
        # The meaning colours are read as words on cards (scores, links, warnings).
        for colour in (theme.LIME, theme.PINK, theme.AMBER, theme.BLUE_HI, theme.CYAN, theme.SCORE):
            self.assertGreaterEqual(contrast(colour, theme.PANEL), 4.5, colour)

    def test_words_on_the_cabinets_lamps(self):
        # A lamp with its word: white words over the lit body all the way down it (the words' foot is the lightest
        # place under them), grey words on the black glass when off.
        for kind, (top, foot) in theme.CHIPS.items():
            self.assertGreaterEqual(contrast("#ffffff", foot), 4.4, kind)
            self.assertGreaterEqual(contrast("#ffffff", middle(top, foot)), 4.5, kind)
        self.assertGreaterEqual(contrast(theme.CHIP_OFF_INK, theme.CHIP_OFF), 4.5)

    def test_the_name_plates(self):
        # A card's tab (the seam's colour), a section's plate on a card and one on the page (widgets.Card, section).
        for fill in (theme.LINE, theme.INK, theme.PANEL_HI):
            self.assertGreaterEqual(contrast(theme.TEXT, fill), 4.5, fill)


class PictureTest(unittest.TestCase):

    def test_button_faces_have_the_size_asked_for(self):
        for look in art.BUTTON_LOOKS:
            face = art.button_face((150, 40), 6, look, "normal", True, 1.0, bg=theme.PANEL)
            self.assertEqual(face.size, (150, 40))
            # The plate leans: the corners it leaves (top left, bottom right) are the colour beneath it.
            self.assertEqual(face.getpixel((2, 2)), art._rgb(theme.PANEL))
            self.assertEqual(face.getpixel((147, 37)), art._rgb(theme.PANEL))

    def test_a_page_made_again_takes_the_pictures_it_had(self):
        from PIL import Image
        # The same arguments give the same picture, drawn once; it is the picture the function draws.
        args = ((120, 34), 0, "neutral", "hover", False, 2.0)
        first = art.button_face(*args, bg=theme.PANEL)
        self.assertIs(art.button_face(*args, bg=theme.PANEL), first)
        self.assertEqual(first.tobytes(), art.button_face.__wrapped__(*args, bg=theme.PANEL).tobytes())
        # Another state, another picture.
        self.assertIsNot(art.button_face((120, 34), 0, "neutral", "normal", False, 2.0, bg=theme.PANEL), first)
        # A section's colours (a dict, in whatever order) and a row's words (a list) are part of what it is kept by.
        row = art.choice_row(["A", "B"], 0, None, theme.SECTION_COLOURS["star"], 1.0)
        reordered = dict(reversed(list(theme.SECTION_COLOURS["star"].items())))
        self.assertIs(art.choice_row(["A", "B"], 0, None, reordered, 1.0), row)
        self.assertIsNot(art.choice_row(["A", "B"], 0, None, theme.SECTION_COLOURS["pop"], 1.0), row)
        # Its edges cannot be changed by the row that takes them.
        self.assertIsInstance(row[1], tuple)
        # Drawn over another picture (a dialog's button over its panel's pixels): drawn each time, never kept.
        under = Image.new("RGB", (120, 34))
        self.assertIsNot(art.button_face((120, 34), 0, "info", "normal", False, 1.0, under=under),
                         art.button_face((120, 34), 0, "info", "normal", False, 1.0, under=under))

    def test_kept_pictures_go_least_recently_asked_first(self):
        from PIL import Image
        drawn = []

        @art._kept(3)
        def draw(n):
            drawn.append(n)
            return Image.new("L", (1, 1), n)

        for n in (0, 1, 2, 0, 3):
            draw(n)
        # 1 was asked for least recently when 3 came: drawn again; 0 is still kept.
        draw(1)
        draw(0)
        self.assertEqual(drawn, [0, 1, 2, 3, 1])
        self.assertEqual(len(draw.kept), 3)
        # An argument that cannot be a key is drawn each time, as before.
        twice = []

        @art._kept(3)
        def draw_set(values):
            twice.append(values)
            return Image.new("L", (1, 1))

        draw_set({1, 2})
        draw_set({1, 2})
        self.assertEqual(len(twice), 2)

    def test_a_dialog_is_opaque_pictures(self):
        from PIL import Image
        window = Image.new("RGB", (800, 600), art._rgb(theme.BG))
        box = (170, 120, 460, 300)
        scene, soft = art.dialog_scene(window, box, 1.0)
        panel = art.dialog_panel(soft, box, (180, 30, 14, "#ff7ab8", "#f0388f"), 1.0)
        self.assertEqual((scene.mode, scene.size), ("RGB", (800, 600)))
        self.assertEqual((panel.mode, panel.size), ("RGB", (460, 300)))

    def test_chrome_titles_in_both_scripts(self):
        for words in ("TECHNIKA 3", "온라인"):
            img, baseline = art.chrome_text([(words, art.CHROME)], 34)
            self.assertEqual(img.mode, "RGBA")
            self.assertTrue(0 < baseline < img.height)
            self.assertIsNotNone(img.getchannel("A").getbbox())

    def test_the_logo_fits_its_width(self):
        for width in (192, 140):
            self.assertEqual(art.logo(width).width, width)

    def test_every_head_has_one_stage_its_colour_by_section(self):
        from unittest import mock
        from opendmt3.core import stage
        drawn = []
        real = art._stage

        def counted(*a, **k):
            if a[:2] not in art._STAGES:
                drawn.append(a[:2])
            return real(*a, **k)

        fresh = type(art._GROUNDS)
        with mock.patch.object(art, "_stage", counted), mock.patch.object(art, "_STAGES", fresh()), \
                mock.patch.object(art, "_GROUNDS", fresh()):
            screen = art.header(300, 60, colours=theme.section_colours("screen"), title="SCREEN")
            # The same page at the same size: the same picture.
            again = art.header(300, 60, colours=theme.section_colours("screen"), title="SCREEN")
            self.assertEqual(again.tobytes(), screen.tobytes())
            # Another page of another section, and the other language, at the same size: the same stage, drawn once.
            art.header(300, 60, colours=theme.section_colours("online"), title="ONLINE")
            art.header(300, 60, colours=theme.section_colours("screen"), title="화면")
            self.assertEqual(drawn, [(300, 60)])
            # Another size draws its own; kept as asked, the oldest going first.
            art.header(320, 60, colours=theme.section_colours("screen"), title="SCREEN")
            self.assertEqual(drawn, [(300, 60), (320, 60)])
            for width in range(art.STAGES_KEPT + 2):
                art.header(40 + width, 20, colours=theme.section_colours("play"))
            self.assertEqual(len(art._STAGES), art.STAGES_KEPT)
            self.assertLessEqual(len(art._GROUNDS), art.GROUNDS_KEPT)
        # Four pieces take the section's colour, the rest none; the same pieces every time (one composition).
        self.assertEqual(sum(stage.coloured(p) for p in stage.pieces()), 4)
        self.assertEqual(stage.pieces(), stage.pieces())

    def test_discs_that_cannot_be_read_leave_the_head_bare_and_say_why_in_the_log(self):
        class Game:
            # A game folder whose discs' archive cannot be opened (damaged, cut short).
            def pak_path(self, name):
                return name + ".pak"

            def open_pak(self, path):
                raise OSError("%s is cut short" % path)

        with self.assertLogs("opendmt3.launcher", "WARNING") as said:
            self.assertEqual(art.read_discs(Game()), [])
        self.assertIn("DiscImg.pak is cut short", "\n".join(said.output))

    def test_plays_head_drawn_again_takes_its_discs_at_their_size(self):
        from unittest import mock
        from PIL import Image, ImageDraw
        # Two round discs, as the player's archives give them.
        discs = []
        for colour in ((200, 40, 90), (40, 160, 220)):
            disc = Image.new("RGBA", (64, 64), colour + (0,))
            mask = Image.new("L", (64, 64), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, 63, 63], fill=255)
            disc.putalpha(mask)
            discs.append(disc)
        resized = []
        real = Image.Image.resize

        def counted(picture, *a, **k):
            # A disc made to a size (by itself, never by its pixels: any picture may be resized here).
            if any(picture is disc for disc in discs):
                resized.append(picture)
            return real(picture, *a, **k)

        fresh = type(art._DISCS)
        with mock.patch.object(art, "_DISCS", fresh()), mock.patch.object(Image.Image, "resize", counted):
            first = art.header(400, 80, discs, title="TECHNIKA 3", title_tail="3")
            again = art.header(400, 80, discs, title="TECHNIKA 3", title_tail="3")
            # The same head, each disc made to its size once.
            self.assertEqual(again.tobytes(), first.tobytes())
            self.assertEqual(resized, discs)
            # Another disc that comes where one was (another day, another folder) is drawn as itself.
            other = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            self.assertNotEqual(art.header(400, 80, [other, discs[1]], title="TECHNIKA 3").tobytes(),
                                first.tobytes())
            self.assertLessEqual(len(art._DISCS), art.DISCS_KEPT)

    def test_a_head_ends_in_its_sections_tube(self):
        for page in ("play", "screen", "online", "help"):
            colours = theme.section_colours(page)
            for scale in (1.0, 2.0):
                head = art.header(int(200 * scale), int(60 * scale), colours=colours, scale=scale)
                row = int(round(scale))
                h = head.height
                # Light, full, light, and the shade under them, a logical pixel each, across the head's foot.
                for i, colour in enumerate((colours["light"], colours["accent"], colours["light"])):
                    self.assertEqual(head.getpixel((head.width // 2, h - (4 - i) * row)), art._rgb(colour), (page, scale))
                self.assertEqual(head.getpixel((head.width // 2, h - 1)), (8, 10, 12), (page, scale))

    def test_a_lamp_has_no_light_round_it(self):
        # Lit, unlit and outlined lamps: nothing is drawn past the lamp's leaning shape (no glow), and a lit lamp is
        # darker at its top than at its foot (lit from below).
        for lit in (True, False, "quiet"):
            for scale in (1.0, 2.0):
                img = art.lamp(theme.NET, lit, scale)
                w, h = img.size
                shape = art._mask((w, h), lambda d, s: d.polygon(art.lean_outline(0, 0, w * s - 1, h * s - 1), fill=255))
                for y in range(h):
                    for x in range(w):
                        if shape.getpixel((x, y)) == 0:
                            self.assertEqual(img.getpixel((x, y))[3], 0, (lit, scale, x, y))
        lit = art.lamp(theme.NET, True, 2.0)
        w, h = lit.size
        top, foot = lit.getpixel((w // 2, int(h * 0.3))), lit.getpixel((w // 2, h - 2))
        self.assertLess(sum(top[:3]), sum(foot[:3]))

    def test_the_columns_lockup_fits_its_room_at_every_scale(self):
        # The column's top (art.brand) is the logo's lockup: OPEN and its slab over DMT3, LAUNCHER at DMT3's foot and
        # the version over it, as the site's bar sets DMT3 SERVER. At every scale from 100 to 200 % it is as wide as
        # the column's room at most, a usual version stands beside DMT3 (no taller for it), and it is the logo's
        # picture at that width cut to its pixels.
        self.assertLessEqual(art.BRAND_WIDTH, widgets.Rail.WIDTH - 2 * widgets.Rail.EDGE - 1)
        for scale in (1.0, 1.25, 1.5, 1.75, 2.0):
            room = int(round(art.BRAND_WIDTH * scale))
            usual = art.brand(scale, "0.4.0")
            self.assertLessEqual(usual.width, room, scale)
            self.assertEqual(usual.height, art.brand(scale, "0.10.12").height, scale)
            whole = art.logo(room, scale, label="LAUNCHER", version="0.4.0")
            self.assertEqual(usual.tobytes(), whole.crop(whole.getbbox()).tobytes(), scale)

    def test_a_cards_corner_is_cut(self):
        # The page's colour beyond the cut (the top right), the card's inside under it (the bottom left), and the seam
        # one outline: it starts where the top edge comes in (the square's top-left pixel), runs down the diagonal and
        # ends where the right edge goes on (its bottom-right pixel), at 100, 150 and 200 %.
        def seam_share(pixel):
            """How much of the seam a pixel on the cut shows over the page (0: the page alone, 1: the seam alone): the
            cut runs through the diagonal pixels' corners, so half of each lies past it, under the page."""
            line, page = art._rgb(theme.LINE), art._rgb(theme.BG)
            return min((p - b) / float(l - b) for p, l, b in zip(pixel, line, page))

        for size in (14, 21, 28):
            corner = art.corner(size, theme.PANEL, theme.BG, seam=theme.LINE)
            self.assertEqual(corner.size, (size, size))
            self.assertEqual(corner.getpixel((size - 1, 0)), art._rgb(theme.BG), size)
            self.assertEqual(corner.getpixel((0, size - 1)), art._rgb(theme.PANEL), size)
            # From the top edge's last pixel down the diagonal to the right edge's first: the seam all the way.
            for i in range(size):
                self.assertGreaterEqual(seam_share(corner.getpixel((i, i))), 0.5, (size, i, corner.getpixel((i, i))))
            # With the top edge's light, the line along the cut starts in it and ends in the seam's colour.
            lit = art.corner(size, theme.PANEL, theme.BG, seam=theme.SEAM, rim=theme.RIM)
            first, last = lit.getpixel((1, 1)), lit.getpixel((size - 2, size - 2))
            self.assertGreater(sum(first), sum(last), size)

    def test_the_version_never_changes_the_mark(self):
        # DMT3 and OPEN, the left part of the logo, are the same pixels whatever the version (the room beside
        # DMT3 is fixed); a version too long for that room goes on a line under the mark.
        for scale in (1.0, 1.5):
            width = int(192 * scale)
            plain = art.logo(width, scale)
            mark = (0, 0, int(width * 0.6), plain.height)
            for version in ("0.7.0", "0.10.12", "1.0.0-rc.1", "0.7.1-updatetest"):
                shown = art.logo(width, scale, version=version)
                self.assertEqual(shown.width, width, version)
                self.assertEqual(shown.crop(mark).tobytes(), plain.crop(mark).tobytes(), (scale, version))
            self.assertEqual(art.logo(width, scale, version="0.7.0").height, plain.height)
            self.assertGreater(art.logo(width, scale, version="0.7.1-updatetest").height, plain.height)

    def test_the_in_game_bar_carries_the_launchers_own_mark(self):
        import contextlib
        import importlib.util
        import io
        import os
        import struct
        import tempfile
        # native/cardreader/mark.py, as the DLL's build runs it: the launcher's logo, without its label, cut to what it
        # draws, written as the layer's canvases hold pixels.
        here = os.path.dirname(os.path.abspath(__file__))
        spec = importlib.util.spec_from_file_location(
            "mark", os.path.join(here, "..", "..", "native", "cardreader", "mark.py"))
        mark = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mark)
        picture = mark.picture()
        # The same pixels as the launcher's logo at that size (the mark's left part: OPEN and DMT3).
        size = int(round(44 * mark.SCALE))
        big, _ = art.chrome_text([("DMT", art.CHROME), ("3", art.lit_chrome(theme.BLUE_HI))], size, mark.SCALE)
        logo = art.logo(big.width + int(6 * mark.SCALE), mark.SCALE, label="")
        self.assertEqual(picture.tobytes(), logo.crop(logo.getbbox()).tobytes())
        # Tall enough that the bar at 4K (46 of 768 lines, 129 pixels) is drawn smaller from it.
        self.assertGreaterEqual(picture.height, 129)
        # With no label or version beside DMT3 the slab over it ends at the 3 (its top corner over the 3's last solid
        # pixel, within a couple of pixels): nothing of it runs on over nothing, as a lockup cut short would.
        solid = picture.getchannel("A").point(lambda v: 255 if v > 128 else 0)
        def right_end(rows):
            box = solid.crop((0, rows[0], picture.width, rows[1])).getbbox()
            return box[2] if box else 0
        slab, name = right_end((0, picture.height // 6)), right_end((picture.height // 3, picture.height))
        self.assertLessEqual(abs(slab - name), 2 * mark.SCALE, (slab, name))
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "mark.bin")
            # Its line for the build's console kept out of the tests' output.
            with contextlib.redirect_stdout(io.StringIO()):
                mark.main(path)
            data = open(path, "rb").read()
        w, h = struct.unpack("<II", data[:8])
        self.assertEqual((w, h, len(data)), (picture.width, picture.height, 8 + w * h * 4))
        # Premultiplied: no colour brighter than its own opacity.
        pixels = struct.unpack("<%dI" % (w * h), data[8:])
        self.assertTrue(all(max((p >> 16) & 255, (p >> 8) & 255, p & 255) <= p >> 24 for p in pixels))
        self.assertTrue(any(p >> 24 == 255 for p in pixels))

    def test_the_logo_and_the_launcher_page_show_one_version(self):
        from unittest import mock
        from opendmt3 import __version__
        from opendmt3.client import updates
        # From source: the code's own version.
        with mock.patch.object(updates, "current_version", return_value=None):
            self.assertEqual(updates.shown_version(), __version__)
        # Installed: what Velopack installed (an update packed under another version says that one).
        with mock.patch.object(updates, "current_version", return_value="0.7.1-updatetest"):
            self.assertEqual(updates.shown_version(), "0.7.1-updatetest")


class ScrollBarTest(unittest.TestCase):
    """Where the scroll bar's thumb sits (widgets.thumb_span), without a window."""

    def test_the_thumb_is_the_share_in_view(self):
        # Half the page shows, from its top: the thumb is the upper half of the trough.
        self.assertEqual(widgets.thumb_span(400, 0.0, 0.5, 32), (0, 200))
        # Scrolled to the end, it ends where the trough does.
        self.assertEqual(widgets.thumb_span(400, 0.5, 1.0, 32), (200, 400))

    def test_a_long_page_keeps_a_thumb_to_catch(self):
        # A hundredth in view would be 4 pixels: the thumb stays 32 long and still reaches both ends.
        self.assertEqual(widgets.thumb_span(400, 0.0, 0.01, 32), (0, 32))
        top, bottom = widgets.thumb_span(400, 0.99, 1.0, 32)
        self.assertEqual((round(top), round(bottom)), (368, 400))
        # Halfway through the part not shown it is halfway down the room left over.
        top, bottom = widgets.thumb_span(400, 0.495, 0.505, 32)
        self.assertEqual((round(top), round(bottom)), (184, 216))

    def test_everything_in_view_or_no_room(self):
        # Nothing to scroll: the thumb fills the trough (the bar is not shown then, but nothing divides by zero).
        self.assertEqual(widgets.thumb_span(400, 0.0, 1.0, 32), (0, 400))
        # A trough shorter than the least thumb: the thumb is the trough.
        self.assertEqual(widgets.thumb_span(20, 0.0, 0.5, 32), (0, 20))
        # Before the window is laid out its height reads as 1.
        self.assertEqual(widgets.thumb_span(1, 0.0, 0.5, 32), (0, 1))


class ScrollIntoViewTest(unittest.TestCase):
    """How far a page scrolls to show something (widgets.view_start), without a window."""

    def test_what_is_in_view_stays_put(self):
        self.assertEqual(widgets.view_start(120, 180, 100, 300), 100)

    def test_below_the_fold_comes_up_just_enough(self):
        # The span ends 50 pixels under a view that shows 100..400: the view moves 50 down.
        self.assertEqual(widgets.view_start(380, 450, 100, 300), 150)

    def test_above_the_view_comes_down_to_its_top(self):
        self.assertEqual(widgets.view_start(40, 90, 100, 300), 40)

    def test_taller_than_the_view_shows_its_top(self):
        self.assertEqual(widgets.view_start(200, 900, 100, 300), 200)


class WrapWidthTest(unittest.TestCase):
    """The width a wrapping label takes from its box (widgets.wrap_width), without a window."""

    def test_a_label_takes_the_room_its_box_has(self):
        # Laid out for the first time: from the start width to the box's own.
        self.assertEqual(widgets.wrap_width(472, 120), 472)
        # The window made narrower: at once, by any amount (the words must fit their box).
        self.assertEqual(widgets.wrap_width(471, 472), 471)
        self.assertEqual(widgets.wrap_width(300, 472), 300)
        # Made wider: taken when it is more than the pixel or two a row hands about.
        self.assertEqual(widgets.wrap_width(475, 472), 475)
        self.assertEqual(widgets.wrap_width(474, 472), 472)

    def test_two_boxes_handing_a_pixel_back_and_forth_come_to_rest(self):
        # PLAY at 1600x1000: the row of two cards is 1291 pixels, three parts to two (774.6 and 516.4). The odd pixel
        # went to the narrow card when its labels wrapped at 472 and to the wide one when they wrapped at 473, and a
        # label that follows its box to the pixel never stopped: the window never came back from drawing the page.
        def room(wrap):
            """The room the narrow card's labels have, by what they wrap at (the row's answer)."""
            return 473 if wrap == 472 else 472

        for start in (120, 472, 473, 600):
            wrap, seen = start, []
            for _ in range(20):
                wrap = widgets.wrap_width(room(wrap), wrap)
                seen.append(wrap)
            # At rest within a few turns, and it stays: the last ten are one width, where the words fit.
            self.assertEqual(set(seen[-10:]), {472}, (start, seen))

        # The label that takes every pixel (no slack) is the one that never stopped.
        wrap, seen = 472, []
        for _ in range(20):
            wrap = widgets.wrap_width(room(wrap), wrap, slack=0)
            seen.append(wrap)
        self.assertEqual(set(seen[-10:]), {472, 473})


class WrapTest(unittest.TestCase):
    """snapshot.wrap cuts lines as Tk does, and the dialogs' even lines never go narrower than a long word."""

    class Font:
        """Every character 10 pixels wide."""
        def measure(self, text):
            return 10 * len(text)

    def test_lines_break_at_spaces_and_newlines(self):
        self.assertEqual(snapshot.wrap(self.Font(), "aaa bbb ccc", 75), ["aaa bbb", "ccc"])
        self.assertEqual(snapshot.wrap(self.Font(), "aaa\nbbb", 0), ["aaa", "bbb"])

    def test_even_lines(self):
        font = self.Font()
        # Two lines either way, but the narrower width splits them evenly instead of leaving one word alone.
        width = dialogs.balanced_width(font, "aaaa bbbb cccc dddd", 150)
        self.assertEqual(len(snapshot.wrap(font, "aaaa bbbb cccc dddd", width)), 2)
        self.assertLess(width, 150)
        # A path has no spaces: the width never goes below it.
        text = "Start over keeps it.\nC:\\Users\\player\\AppData\\openDMT3\\settings.json"
        self.assertGreaterEqual(dialogs.balanced_width(font, text, 600), font.measure(text.split("\n")[1]))


class FinalReviewTest(unittest.TestCase):
    """The launcher's final review (0.4.0): paths broken after their separators, the same jackets for the same folder,
    the status line held to its lines, and a row of choices that fits its room."""

    class Font:
        """Every character 10 pixels wide."""
        def measure(self, text):
            return 10 * len(text)

    def test_a_path_breaks_after_a_separator_never_inside_a_name(self):
        # W-07: "drive d" once came apart at its space.
        path = "C:\\Games\\TECHNIKA 3 (International Final Version)\\drive d\\DMT3"
        lines = widgets.wrap_path(self.Font(), path, 420).split("\n")
        self.assertEqual("".join(lines), path)
        self.assertIn("drive d\\DMT3", lines[-1])
        for line in lines[:-1]:
            self.assertTrue(line.endswith("\\"), lines)
        # A name wider than a line is still cut, and nothing is lost.
        self.assertEqual("".join(widgets.wrap_path(self.Font(), "C:\\" + "x" * 30, 100).split("\n")),
                         "C:\\" + "x" * 30)
        self.assertEqual(widgets.wrap_path(self.Font(), "C:\\a", 500), "C:\\a")

    def test_the_same_folder_shows_the_same_jackets(self):
        # A-15: DISC CHECK draws three, the PLAY head four of which the GAME page's card shows three: the same day's
        # pick starts with the same ones.
        import io
        from PIL import Image

        class Entry:
            def __init__(self, name):
                self.name = name

        class Pak:
            entries = [Entry("disc_%03d_0.png" % i) for i in range(200)] + [Entry("disc_001_1.png")]

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, entry):
                picture = Image.new("RGB", (4, 4), (int(entry.name[5:8]) % 256, 0, 0))
                out = io.BytesIO()
                picture.save(out, "PNG")
                return out.getvalue()

        class Game:
            def pak_path(self, name):
                return name

            def open_pak(self, path):
                return Pak()

        from opendmt3.client import found_list
        three = [p.getpixel((0, 0)) for p in found_list.jackets(Game())]
        four = [p.getpixel((0, 0)) for p in art.read_discs(Game())]
        self.assertEqual(three, four[:3])

    def test_the_status_line_keeps_to_three_lines(self):
        # A-01: the menu above keeps the room of three lines; a longer line ends in an ellipsis.
        from opendmt3.client import app
        text = " ".join(["word"] * 40)
        shown = app.clip_lines(self.Font(), text, 100)
        self.assertEqual(len(shown.split("\n")), 3)
        self.assertTrue(shown.endswith("\u2026"))
        self.assertEqual(app.clip_lines(self.Font(), "short line", 100), "short line")

    def test_korean_lines_never_break_inside_a_phrase(self):
        # C-03: "설치 / 프로그램", "준비하는 / 중입니다", "할 수 / 없습니다", "(약 / 14 MB)" came apart in dialogs.
        from opendmt3.client import i18n
        ko = i18n.Words("ko")
        nbsp = i18n.NBSP
        self.assertIn("설치" + nbsp + "프로그램", ko("help.repair.source"))
        self.assertIn("연결할" + nbsp + "수" + nbsp + "없습니다", i18n.keep_phrases("서버에 연결할 수 없습니다."))
        self.assertIn("준비하는" + nbsp + "중입니다", i18n.keep_phrases("제거를 준비하는 중입니다."))
        self.assertIn("(약" + nbsp + "14" + nbsp + "MB)", i18n.keep_phrases("곡 목록 (약 14 MB)"))
        # A dialog's even lines never cut such a phrase: the narrowest width keeps it whole.
        font = self.Font()
        text = i18n.keep_phrases("이 런처는 openDMT3 설치 프로그램으로 설치하지 않았습니다.")
        for line in snapshot.wrap(font, text, dialogs.balanced_width(font, text, 300)):
            self.assertFalse(line.endswith("설치") and "프로그램" not in line, line)
        # English and the words as TEXT holds them are as they were.
        self.assertEqual(i18n.keep_phrases("Hello world"), "Hello world")
        self.assertEqual(i18n.plain(ko("help.repair.source")), i18n.TEXT["help.repair.source"][1])
        # A card's English name is found from its Korean words with their kept phrases.
        self.assertEqual(i18n.english_of(ko("songlist.send.title")), i18n.TEXT["songlist.send.title"][0])

    def test_a_pages_main_key_is_never_pink_or_amber(self):
        # The colour rule: pink is for what failed, amber for something to look at; a page's main key (ONLINE's
        # Connect and Sign in, LAUNCHER's update) is openDMT3's blue, or the settings' lime on their pages.
        for section, look in art.SECTION_LOOKS.items():
            fill = art.BUTTON_LOOKS[look]["normal"][1]
            self.assertNotIn(fill, (theme.PINK, theme.AMBER), section)
        self.assertEqual(art.SECTION_LOOKS["star"], "star")

    def test_a_row_of_choices_fits_its_room(self):
        # B-01: the fifth upscale filter was cut by the card's edge at the smallest window.
        texts = ["Nearest", "Bilinear", "Bicubic", "Lanczos", "Anime4K"]
        colours = theme.SECTION_COLOURS["technika"]
        wide, _ = art.choice_row(texts, 0, None, colours)
        narrow, edges = art.choice_row(texts, 0, None, colours, room=wide.width - 40)
        self.assertLessEqual(narrow.width, wide.width - 40)
        self.assertEqual(len(edges), 5)
        # With room enough it is as it always was.
        same, _ = art.choice_row(texts, 0, None, colours, room=wide.width + 100)
        self.assertEqual(same.width, wide.width)


class TimerTest(unittest.TestCase):
    """Every timer is on the window's root (widgets.later), never on a widget a page can destroy: a widget's own
    after() or after_idle() ends with it while Tcl's timer still names its command, and a page made again at once could
    give that name to a command of its own, which the old timer then called with nothing (remote_play under Wine,
    2026-11-19: a link's handler, "missing 1 required positional argument: 'e'")."""

    # Timers on what lives as long as the window: the root by any of its names, and the page area's own (the page area
    # is made once with the window). A dialog's timers are its canvas's, each cancelled when the dialog closes.
    ROOTS = ("root.after", "self.root.after", "app.root.after", "self.app.root.after", "root.after_idle",
             "app.root.after_idle", "self.app.root.after_idle")
    KEPT = {("widgets.py", "self.after_idle(self._keyboard_moved)"), ("dialogs.py", "self.canvas.after(ms,")}

    def test_every_timer_is_on_the_root(self):
        import glob
        import os
        import re
        top = os.path.dirname(widgets.__file__)
        found = []
        for path in glob.glob(os.path.join(top, "**", "*.py"), recursive=True):
            with open(path, encoding="utf-8") as f:
                for number, line in enumerate(f, 1):
                    code = line.split("#", 1)[0]
                    for call in re.finditer(r"([\w.\[\]\"()]+)\.(after_idle|after)\(", code):
                        receiver = call.group(1)
                        whole = "%s.%s" % (receiver, call.group(2))
                        if whole.endswith(self.ROOTS) or receiver in ("root", "self.root", "app.root"):
                            continue
                        if any(os.path.basename(path) == name and words in code for name, words in self.KEPT):
                            continue
                        found.append("%s:%d %s" % (os.path.relpath(path, top), number, code.strip()))
        self.assertEqual(found, [], "timers on a widget a page can destroy: use widgets.later")

    def test_a_timer_later_set_is_cancelled_on_the_root(self):
        # A widget's own after_cancel would leave the command's name in the root's list, and the root's end would fail
        # on it: every after_cancel in opendmt3/client is on a root, a dialog's canvas (its own timers) or cancel().
        import glob
        import os
        import re
        top = os.path.dirname(widgets.__file__)
        found = []
        for path in glob.glob(os.path.join(top, "**", "*.py"), recursive=True):
            with open(path, encoding="utf-8") as f:
                for number, line in enumerate(f, 1):
                    for call in re.finditer(r"([\w.]+)\.after_cancel\(", line.split("#", 1)[0]):
                        if not call.group(1).endswith(("root", "canvas", "_root()")):
                            found.append("%s:%d %s" % (os.path.relpath(path, top), number, line.strip()))
        self.assertEqual(found, [], "a timer later() set is stopped with widgets.cancel")

    def test_later_runs_on_the_root_and_only_while_the_widget_is_there(self):
        calls = []

        class Root:
            def after_idle(self, func):
                calls.append(("idle", func))
                return "after#1"

            def after(self, ms, func):
                calls.append((ms, func))
                return "after#2"

        class Widget:
            there = True

            def _root(self):
                return Root()

            def winfo_exists(self):
                return self.there

        widget, ran = Widget(), []
        self.assertEqual(widgets.later(widget, lambda: ran.append(1)), "after#1")
        self.assertEqual(widgets.later(widget, lambda: ran.append(2), 10), "after#2")
        self.assertEqual([when for when, _ in calls], ["idle", 10])
        calls[0][1]()
        widget.there = False
        calls[1][1]()
        # The first ran while the widget was there; the second found it gone and did nothing.
        self.assertEqual(ran, [1])


class ComposeTest(unittest.TestCase):
    """The words' sizes and middles the composition pass holds (tests/e2e/ui/compose.py), measured from the fonts."""

    def test_a_words_ink_band_is_its_capitals_or_its_hangul(self):
        body = 10 * 96 / 72.0
        top, bottom = art.ink_band(theme.TEXT_FILE, body, "H")
        # Pretendard's capitals stand about 0.71 of the size over the baseline, nothing under it.
        self.assertAlmostEqual(-top / body, 0.71, delta=0.04)
        self.assertAlmostEqual(bottom, 0.0, delta=0.3)
        # A "g" under the line or an "l" over the capitals does not move the band: the capitals' it stays.
        self.assertEqual(art.ink_band(theme.TEXT_FILE, body, "Hlg"), (top, bottom))
        # Hangul's own syllables make the band, a little lower and taller than the capitals.
        hangul = art.ink_band(theme.TEXT_FILE, body, "가나다 OK")
        self.assertLess(hangul[0], top)
        self.assertGreater(hangul[1], bottom)

    def test_a_cards_name_is_no_smaller_than_the_body(self):
        # The owner's rule (2026-11-19): no heading smaller than the body under it.
        for scale in (1.0, 1.5, 2.0):
            plate = art.ink_band(theme.WIDE_FILE, art.PLATE_TEXT * scale, "READY CHECK")
            body = art.ink_band(theme.TEXT_FILE, 10 * 96 / 72.0 * scale, "H")
            self.assertGreaterEqual((plate[1] - plate[0]) + 0.25, body[1] - body[0], scale)
            picture = art.name_plate("READY CHECK", scale)
            self.assertEqual(picture.height, int(round(art.PLATE_HEIGHT * scale)))

    def test_every_key_of_a_role_takes_one_size(self):
        # A page's key and a dialog's key: one height and one least width (widgets.Button, dialogs).
        self.assertEqual(dialogs.BUTTON, widgets.Button.HEIGHTS["normal"])
        self.assertEqual(dialogs.BUTTON_MIN, widgets.Button.LEAST["normal"])
        self.assertEqual(dialogs.widgets_side(), widgets.Button.SIDES["normal"])
        # The sign-in's key is a main key: as tall as every other.
        self.assertEqual(widgets.Button.SIDES["lg"], widgets.Button.SIDES["normal"])
        self.assertEqual(widgets.Button.LEAST["lg"], widgets.Button.LEAST["normal"])

    def test_every_card_kind_has_its_whole_look_and_every_page_names_a_kind_there_is(self):
        # A card's look in one place (theme.CARD_LOOKS), a whole one for each kind, so that a kind's own shape and
        # colour (the card identity) slots in without a page changed.
        import glob
        import os
        import re
        for kind in theme.CARD_KINDS:
            look = set(theme.CARD_LOOKS[kind])
            # Every kind's whole edge and name; its parts only from the ones widgets.Card draws.
            self.assertLessEqual({"face", "seam", "rim", "foot", "tab", "tab_ink", "cut"}, look, kind)
            self.assertLessEqual(look - {"face", "seam", "rim", "foot", "tab", "tab_ink", "cut"},
                                 {"well", "foot_cut", "rail", "band"}, kind)
        top = os.path.dirname(theme.__file__)
        named = set()
        for path in glob.glob(os.path.join(top, "**", "*.py"), recursive=True):
            with open(path, encoding="utf-8") as f:
                source = f.read()
            # The kinds the pages and the guide give their cards (card, pair_card, widgets.Card).
            for call in re.findall(r"(?:card|Card)\([^()]*(?:\([^()]*\)[^()]*)*\)", source):
                named.update(re.findall(r"kind=\"(\w+)\"", call))
        self.assertTrue(named)
        self.assertLessEqual(named, set(theme.CARD_KINDS), named - set(theme.CARD_KINDS))

    def test_the_kinds_tell_apart_in_grey_and_the_member_card_reads(self):
        # CARDS.md: raised plates lit from above, sunken ones shaded at the top and lit at the foot.
        def grey(colour):
            r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        looks = theme.CARD_LOOKS
        for kind in ("settings", "status", "steps", "list", "result"):
            self.assertGreater(grey(looks[kind]["rim"]), grey(looks[kind]["foot"]), kind)
        self.assertLess(grey(looks["danger"]["rim"]), grey(looks["danger"]["foot"]))
        # The faces apart: the quiet info plate, the base plate, the sunken tray and the black glass, each its own.
        faces = [grey(looks[k]["face"]) for k in ("settings", "info", "danger", "result")]
        self.assertEqual(len(set(round(f) for f in faces)), 4, faces)

        # The member card's words on its platinum (the darkest stop it has): dark ink 7:1 and more, the second ink
        # 4.5:1 and more (WCAG's contrast).
        def luminance(colour):
            def channel(c):
                c = c / 255.0
                return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
            r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
            return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)

        def contrast(a, b):
            la, lb = sorted((luminance(a), luminance(b)), reverse=True)
            return (la + 0.05) / (lb + 0.05)

        # The metal behind each line of words (the card at 100 %, its words at its foot: the DJ name's capitals over
        # its baseline 27 px over the foot, the ID's over its baseline 12 px over it), at its darkest there.
        width, height = art.MEMBER_CARD
        face = art._platinum(width, height)

        def darkest(first, last):
            return min(("#%02x%02x%02x" % face.getpixel((width // 2, y)) for y in range(first, last)),
                       key=luminance)

        self.assertGreaterEqual(contrast(theme.PLATINUM_INK, darkest(height - 27 - 13, height - 27)), 7.0)
        self.assertGreaterEqual(contrast(theme.PLATINUM_INK_2, darkest(height - 12 - 9, height - 12)), 4.5)
        # A card's proportions (ID-1: 85.60 by 53.98 mm), and the picture at every scale.
        self.assertAlmostEqual(art.MEMBER_CARD[0] / float(art.MEMBER_CARD[1]), 85.60 / 53.98, delta=0.01)
        for scale in (1.0, 1.5, 2.0):
            picture = art.member_card("DJ NOVA", "NOVA", scale)
            self.assertEqual(picture.size, (int(round(176 * scale)), int(round(111 * scale))))

    def test_the_type_steps_name_every_size(self):
        import re
        with open(theme.__file__, encoding="utf-8") as f:
            source = f.read()
        start = source.index("class Fonts")
        sizes = {int(n) for n in re.findall(r"size=(\d+)", source[start:])}
        sizes |= {int(n) for n in re.findall(r"\((?:TEXT_BOLD|DISPLAY), (\d+)\)", source[start:])}
        self.assertTrue(sizes)
        self.assertLessEqual(sizes - set(theme.TYPE_STEPS), set(), sizes)


if __name__ == "__main__":
    unittest.main()
