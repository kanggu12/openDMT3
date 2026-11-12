"""The theme's colours and pictures, without a window: words stay readable on every fill, and the pictures the
dialogs and buttons are made of come out at the size asked for."""

import unittest

try:
    from opendmt3.client import art, dialogs, snapshot, theme, widgets
except ImportError as e:
    # A Python without Tk (a server's: the launcher brings its own): the launcher's pictures are not its business.
    raise unittest.SkipTest("needs Tk, the launcher's window toolkit (%s)" % e)


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
        for surface in (theme.BG, theme.SIDEBAR, theme.PANEL, theme.PANEL_HI):
            for text, least in ((theme.TEXT, 4.5), (theme.MUTED, 4.5), (theme.FAINT, 3.0)):
                self.assertGreaterEqual(contrast(text, surface), least, "%s on %s" % (text, surface))
        # The meaning colours are read as words on cards (scores, links, warnings).
        for colour in (theme.LIME, theme.PINK, theme.AMBER, theme.BLUE_HI, theme.CYAN):
            self.assertGreaterEqual(contrast(colour, theme.PANEL), 4.5, colour)

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

    def test_a_page_header_shown_again_takes_its_shards_kept(self):
        from unittest import mock
        colours = theme.section_colours("screen")
        drawn = []
        real = art.shards

        def counted(*a, **k):
            drawn.append(a[:2])
            return real(*a, **k)

        with mock.patch.object(art, "shards", counted), mock.patch.object(art, "_HEADER_SHARDS", type(art._HEADER_SHARDS)()):
            first = art.header(300, 60, seed=11, colours=colours, title="SCREEN")
            # The same page at the same size: the same picture, its shards drawn once.
            again = art.header(300, 60, seed=11, colours=colours, title="SCREEN")
            self.assertEqual(again.tobytes(), first.tobytes())
            self.assertEqual(len(drawn), 1)
            # Another title (the other language) on the same shards; another size or page draws its own.
            art.header(300, 60, seed=11, colours=colours, title="화면")
            art.header(320, 60, seed=11, colours=colours, title="SCREEN")
            art.header(300, 60, seed=23, colours=theme.section_colours("sound"), title="SOUND")
            self.assertEqual(drawn, [(300, 60), (320, 60), (300, 60)])
            # Kept as asked: the oldest go once more are kept than HEADER_SHARDS_KEPT.
            for seed in range(art.HEADER_SHARDS_KEPT + 2):
                art.header(40, 20, seed=100 + seed, colours=colours)
            self.assertEqual(len(art._HEADER_SHARDS), art.HEADER_SHARDS_KEPT)
            self.assertNotIn((300, 60, 11, tuple(sorted(colours.items()))), art._HEADER_SHARDS)

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


if __name__ == "__main__":
    unittest.main()
