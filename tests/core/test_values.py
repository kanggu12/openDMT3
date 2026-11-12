"""Tests for the player's choices and the setting.ini lines they write."""

import os
import re
import unittest

from opendmt3.core.cabinet import values


class NormalizeTest(unittest.TestCase):
    def test_defaults_fill_what_is_not_given(self):
        out = values.normalize({"music_volume": 40})
        # The one given choice is kept, everything else is the game's own value.
        self.assertEqual(out["music_volume"], 40)
        self.assertEqual(out["display_mode"], "fullscreen")
        self.assertTrue(out["vsync"])

    def test_command_line_text_is_read(self):
        # A command line gives text; it must read the same as real booleans and numbers.
        out = values.normalize({"vsync": "off", "videos": "yes", "key_volume": "75"})
        self.assertEqual((out["vsync"], out["videos"], out["key_volume"]), (False, True, 75))

    def test_unknown_and_out_of_range_are_refused(self):
        # A misspelt name or a volume of 120 must fail loudly, never be stored and ignored.
        for bad in ({"vsinc": True}, {"music_volume": 120}, {"display_mode": "exclusive"},
                    {"window_size": "1000x600"}, {"glow": "maybe"}):
            with self.assertRaises(values.ChoiceError, msg=bad):
                values.normalize(bad)


class LayerChoicesTest(unittest.TestCase):
    """The frame pacing, the frame rate chip and the sound device: openDMT3's in-game layer reads them, setting.ini
    never has them."""

    def test_the_offered_values_and_a_device_by_its_guid(self):
        out = values.normalize({"frame_pacing": "EVEN", "show_fps": "on",
                                "sound_device": "{0000000a-0000-0000-0000-00000000000b}"})
        # Text from a command line reads as the pages' values; GUIDs as Windows writes them.
        self.assertEqual((out["frame_pacing"], out["show_fps"]), ("even", True))
        self.assertEqual(out["sound_device"], "{0000000A-0000-0000-0000-00000000000B}")
        self.assertEqual(values.normalize({"sound_device": "Default"})["sound_device"], "default")
        # The defaults: pacing locked to the music, no chip (its corner the bottom right), Windows' default output.
        self.assertEqual((values.DEFAULTS["frame_pacing"], values.DEFAULTS["show_fps"], values.DEFAULTS["fps_position"],
                          values.DEFAULTS["sound_device"]), ("music", False, "bottom_right", "default"))
        # The chip's four corners by name, in any case; the layer's order (CORNER_* in native/cardreader/logic.h).
        self.assertEqual(values.FPS_POSITIONS, ("top_left", "top_right", "bottom_left", "bottom_right"))
        self.assertEqual(values.normalize({"fps_position": "Top_Left"})["fps_position"], "top_left")
        # The three pacings by their names, the music lock among them.
        self.assertEqual(values.normalize({"frame_pacing": "Music"})["frame_pacing"], "music")
        # The picture's shape: the game's own kept by default, or the window filled, by name in any case.
        self.assertEqual((values.DEFAULTS["picture_shape"], values.PICTURE_SHAPES), ("keep", ("keep", "fill")))
        self.assertEqual(values.normalize({"picture_shape": "Fill"})["picture_shape"], "fill")
        # The picture's GPU time by pass: not measured unless asked for, on and off as the other switches take them.
        self.assertIs(values.DEFAULTS["pass_times"], False)
        self.assertIs(values.normalize({"pass_times": "on"})["pass_times"], True)

    def test_a_value_not_offered_and_a_device_that_is_no_guid_are_refused(self):
        # No frame limit: the game's logic runs once a frame, so a number would change its speed.
        for bad in ({"frame_pacing": "120"}, {"frame_limit": "60"}, {"show_fps": "maybe"}, {"fps_position": "middle"},
                    {"picture_shape": "stretch"}, {"pass_times": "sometimes"},
                    {"sound_device": "Speakers"}, {"sound_device": "0000000a-0000-0000-0000-00000000000b"},
                    {"sound_device": "{0000000a}"}):
            with self.assertRaises(values.ChoiceError, msg=bad):
                values.normalize(bad)

    def test_the_audio_offset_is_whole_milliseconds_in_its_range(self):
        # None by default: the game's own start of the music against its frames.
        self.assertEqual(values.DEFAULTS["audio_offset"], 0)
        self.assertEqual(values.AUDIO_OFFSET_RANGE, (0, 500))
        # A command line's text or the slider's number, kept as a number, and handed to the layer as decimal text.
        self.assertEqual(values.normalize({"audio_offset": " 180 "})["audio_offset"], 180)
        self.assertEqual(values.normalize({"audio_offset": 500})["audio_offset"], 500)
        self.assertEqual(values.layer_environment({"audio_offset": 180})["OPENDMT3_AUDIO_OFFSET"], "180")
        # Below 0 (frames ahead of the music, which a 60 Hz display cannot show sooner), past the most, a fraction or
        # words: refused, never clamped.
        for bad in (-1, 501, "12.5", "40ms", "", None):
            with self.subTest(bad=bad), self.assertRaises(values.ChoiceError):
                values.normalize({"audio_offset": bad})
        # Never a line of setting.ini: the layer's.
        self.assertIn("audio_offset", values.LAYER_CHOICES)
        self.assertEqual(values.ini_changes({"audio_offset": 200}), values.ini_changes({}))

    def test_they_are_no_lines_of_the_settings_file(self):
        lines = values.ini_changes({"frame_pacing": "even", "show_fps": True,
                                    "sound_device": "{0000000A-0000-0000-0000-00000000000B}"})
        self.assertEqual(lines, values.ini_changes({}))

    def test_the_layer_reads_them_from_the_game_environment(self):
        env = values.layer_environment({"frame_pacing": "even", "show_fps": True, "cursor": False}, "ko")
        self.assertEqual(env, {"OPENDMT3_LANGUAGE": "ko", "OPENDMT3_CURSOR": "off", "OPENDMT3_PACING": "even",
                               "OPENDMT3_FPS": "on", "OPENDMT3_FPS_POSITION": "bottom_right", "OPENDMT3_SOUND_DEVICE": "",
                               "OPENDMT3_UPSCALE": "fsr1", "OPENDMT3_SHARPNESS": "50", "OPENDMT3_ANTIALIASING": "off",
                               "OPENDMT3_PICTURE_SHAPE": "keep", "OPENDMT3_PASS_TIMES": "off",
                               "OPENDMT3_LOW_LATENCY": "on", "OPENDMT3_SOUND_PATH": "directsound",
                               "OPENDMT3_RENDER": "game", "OPENDMT3_AUDIO_OFFSET": "0"})
        # Who mixes the game's sounds: Windows' DirectSound unless OpenAL Soft is chosen, by the layer's names.
        self.assertEqual(values.DEFAULTS["sound_path"], "directsound")
        self.assertEqual(values.layer_environment({"sound_path": "OpenAL"})["OPENDMT3_SOUND_PATH"], "openal")
        with self.assertRaises(values.ChoiceError):
            values.normalize({"sound_path": "xaudio2"})
        # The sound engine's shortest period is asked for unless the Sound page's Low latency is off.
        self.assertIs(values.DEFAULTS["low_latency"], True)
        self.assertEqual(values.layer_environment({"low_latency": "off"})["OPENDMT3_LOW_LATENCY"], "off")
        with self.assertRaises(values.ChoiceError):
            values.normalize({"low_latency": "lowest"})
        self.assertEqual(values.layer_environment({"picture_shape": "fill"})["OPENDMT3_PICTURE_SHAPE"], "fill")
        # The game drawn at the screen's size by the layer's word for it; any other value refused, never kept.
        self.assertEqual(values.layer_environment({"render_size": "Display"})["OPENDMT3_RENDER"], "display")
        with self.assertRaises(values.ChoiceError):
            values.normalize({"render_size": "native"})
        # The GPU time by pass by the layer's word for it ("on"; anything else leaves it off).
        self.assertEqual(values.layer_environment({"pass_times": True})["OPENDMT3_PASS_TIMES"], "on")
        # The chosen corner by its name.
        env = values.layer_environment({"show_fps": True, "fps_position": "top_right"})
        self.assertEqual(env["OPENDMT3_FPS_POSITION"], "top_right")
        # Any language but Korean is the launcher's first one; a chosen device goes by its GUID.
        env = values.layer_environment({"sound_device": "{0000000A-0000-0000-0000-00000000000B}"}, "fr")
        self.assertEqual((env["OPENDMT3_LANGUAGE"], env["OPENDMT3_PACING"], env["OPENDMT3_FPS"],
                          env["OPENDMT3_SOUND_DEVICE"]), ("en", "music", "off", "{0000000A-0000-0000-0000-00000000000B}"))


class IniChangesTest(unittest.TestCase):
    def test_full_screen_keeps_the_game_size(self):
        lines = values.ini_changes({"display_mode": "fullscreen", "window_size": "1920x1152"})
        # Borderless, and the window size is the game's own (the display fix sizes the window to the monitor).
        self.assertEqual((lines["popup_style"], lines["screen_width"], lines["screen_height"]), ("true", "1280", "768"))

    def test_window_mode_writes_its_size(self):
        lines = values.ini_changes({"display_mode": "window", "window_size": "1920x1152"})
        self.assertEqual((lines["popup_style"], lines["screen_width"], lines["screen_height"]), ("false", "1920", "1152"))

    def test_volumes_use_the_game_scale(self):
        lines = values.ini_changes({"music_volume": 100, "key_volume": 50})
        # 100% is the game's maximum, 127; half rounds to the nearest step.
        self.assertEqual((lines["bgm_volume"], lines["sfx_volume"]), ("127", "64"))

    def test_preload_writes_both_keys(self):
        lines = values.ini_changes({"preload": True})
        self.assertEqual((lines["resource_preload"], lines["PreLoadMovie"]), ("true", "true"))

    def test_untraced_keys_are_never_written(self):
        # multipleSample and fixed_frame keep the game's values until their effect is known.
        lines = values.ini_changes({})
        self.assertNotIn("multipleSample", lines)
        self.assertNotIn("fixed_frame", lines)


# The in-game layer's sources, read only: the launcher's names and defaults must be the ones it reads.
NATIVE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      "native", "cardreader")


def _native(name):
    with open(os.path.join(NATIVE, name), encoding="utf-8") as f:
        return f.read()


class PictureChoicesTest(unittest.TestCase):
    """The upscale filter, its sharpness and anti-aliasing: the in-game layer reads them by its own names, setting.ini
    never has them."""

    def test_the_picture_choices_reach_the_layer_by_its_names(self):
        # Command-line text in any case reads as the page's values; the sharpness as a number.
        out = values.normalize({"upscale": " FSR1 ", "sharpness": "80", "antialiasing": "SMAA-Ultra"})
        self.assertEqual((out["upscale"], out["sharpness"], out["antialiasing"]), ("fsr1", 80, "smaa-ultra"))
        env = values.layer_environment(out)
        # The sharpness goes as decimal text, the names as the layer spells them.
        self.assertEqual((env["OPENDMT3_UPSCALE"], env["OPENDMT3_SHARPNESS"], env["OPENDMT3_ANTIALIASING"]),
                         ("fsr1", "80", "smaa-ultra"))
        # Both ends of the sharpness are offered, and every name of both lists passes through unchanged.
        self.assertEqual(values.layer_environment({"sharpness": 0})["OPENDMT3_SHARPNESS"], "0")
        self.assertEqual(values.layer_environment({"sharpness": 100})["OPENDMT3_SHARPNESS"], "100")
        for name in values.UPSCALES:
            self.assertEqual(values.layer_environment({"upscale": name})["OPENDMT3_UPSCALE"], name)
        for name in values.ANTIALIASINGS:
            self.assertEqual(values.layer_environment({"antialiasing": name})["OPENDMT3_ANTIALIASING"], name)
        # They are the layer's: no setting.ini line changes for any of them.
        self.assertEqual(values.ini_changes({"upscale": "nis", "sharpness": 10, "antialiasing": "smaa-ultra"}),
                         values.ini_changes({}))
        self.assertTrue({"upscale", "sharpness", "antialiasing"} <= set(values.LAYER_CHOICES))

    def test_values_the_page_does_not_offer_are_refused(self):
        # A misspelling or an out-of-range strength fails loudly rather than being stored and ignored.
        for bad in ({"upscale": "fsr2"}, {"upscale": "dlss"}, {"upscale": ""}, {"sharpness": "101"},
                    {"sharpness": "-1"}, {"sharpness": "sharp"}, {"sharpness": "50.5"}, {"antialiasing": "msaa4"},
                    {"antialiasing": "smaa"}, {"antialiasing": "taa"}):
            with self.assertRaises(values.ChoiceError, msg=bad):
                values.normalize(bad)

    def test_the_names_and_defaults_are_the_layers_own(self):
        source = _native("postmath.c")
        # The name lists in native/cardreader/postmath.c, in its order (the enums' order).
        lists = {}
        for array in ("UPSCALE_NAMES", "AA_NAMES"):
            body = re.search(array + r"\[[^\]]*\]\s*=\s*\{(.*?)\}", source, re.S).group(1)
            lists[array] = tuple(re.findall(r'"([^"]*)"', body))
        self.assertEqual(lists["UPSCALE_NAMES"], values.UPSCALES)
        self.assertEqual(lists["AA_NAMES"], values.ANTIALIASINGS)
        header = _native("postmath.h")
        define = lambda name: re.search(r"#define\s+%s\s+(\w+)" % name, header).group(1)
        # An enum name to the launcher's: UPSCALE_SMOOTH is smooth, AA_SMAA_LOW is smaa-low.
        spelt = lambda enum, prefix: enum[len(prefix):].lower().replace("_", "-")
        self.assertEqual(spelt(define("UPSCALE_DEFAULT"), "UPSCALE_"), values.UPSCALE_DEFAULT)
        self.assertEqual(int(define("SHARPNESS_DEFAULT")), values.SHARPNESS_DEFAULT)
        self.assertEqual(spelt(define("AA_DEFAULT"), "AA_"), values.ANTIALIASING_DEFAULT)
        # DEFAULTS takes them from the one place.
        self.assertEqual((values.DEFAULTS["upscale"], values.DEFAULTS["sharpness"], values.DEFAULTS["antialiasing"]),
                         (values.UPSCALE_DEFAULT, values.SHARPNESS_DEFAULT, values.ANTIALIASING_DEFAULT))


if __name__ == "__main__":
    unittest.main()


class TheLayerReadsEveryVariable(unittest.TestCase):
    """Every variable the launcher hands the game is one the in-game layer reads (native/cardreader/logic.c
    SETTINGS_NAMES): the chip's corner once went unread because its name was missing from the DLL's list."""

    def test_every_variable_is_in_the_dlls_list(self):
        here = os.path.dirname(os.path.abspath(__file__))
        logic = open(os.path.join(here, "..", "..", "native", "cardreader", "logic.c"), encoding="utf-8").read()
        listed = re.search(r"SETTINGS_NAMES\[\] = \{(.*?)\};", logic, re.S).group(1)
        names = set(re.findall(r'"(OPENDMT3_[A-Z_]+)"', listed))
        made = set(values.layer_environment({}))
        self.assertEqual(made - names, set())

    def test_the_sound_engines_words_are_the_layers_own(self):
        # The results the layer writes in its note of the sound engine's period (logic.c ENGINE_NAMES, in its order)
        # are the ones the launcher reads back (client/actions.py ENGINE_RESULTS).
        from opendmt3.client import actions
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "..", "..", "native", "cardreader", "logic.c"), encoding="utf-8") as f:
            logic = f.read()
        listed = re.search(r"ENGINE_NAMES\[ENGINE_RESULTS\] = \{(.*?)\};", logic, re.S).group(1)
        self.assertEqual(tuple(re.findall(r'"([a-z0-9-]+)"', listed)), actions.ENGINE_RESULTS)
        # The Mixer's names are the layer's, in its order (SOUND_PATH_* in logic.h).
        listed = re.search(r"SOUND_PATH_NAMES\[SOUND_PATHS\] = \{(.*?)\};", logic, re.S).group(1)
        self.assertEqual(tuple(re.findall(r'"([a-z0-9-]+)"', listed)), values.SOUND_PATHS)

