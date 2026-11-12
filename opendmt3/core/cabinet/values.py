"""The choices a player makes before the game starts, and the setting.ini lines each one writes.

Only values whose effect is known are offered. The game also reads multipleSample and fixed_frame, but where
those end up has not been traced yet, so they keep the game's own values (the setting step never touches them).

The client always draws a 1280x768 picture; the window size only stretches it. In full-screen mode the display
fix sizes the window to the whole monitor, so the window size matters only in window mode.
"""

import re

# Display modes: a borderless window over the whole monitor (the display fix stretches it), or a framed window.
DISPLAY_MODES = ("fullscreen", "window")

# Window sizes offered in window mode: the game's 1280x768 picture at 1, 1.25, 1.5, 1.75, 2, 2.5 and 3 times,
# all in its 5:3 shape. The launcher hides the ones larger than the monitor's work area.
WINDOW_SIZES = ("1280x768", "1600x960", "1920x1152", "2240x1344", "2560x1536", "3200x1920", "3840x2304")

# How the game's 60 frames a second are paced (openDMT3's in-game layer, native/cardreader). The game runs its logic
# once a frame, so it must stay at 60 (measured: its timers count frames; a faster rate runs the game faster): "game"
# is the client's own steps (17, 17 and 16 ms), "even" openDMT3's clock at exactly 60.0, each frame the same length,
# "music" that clock led by a song's music while one plays, so frame k of a song is shown at k/60 s of its music and
# the notes stay on the music after a stall (the layer's music lock).
FRAME_PACINGS = ("music", "even", "game")

# How the game's 1280x768 picture is enlarged to the window, openDMT3's in-game layer's own step (native/cardreader):
# "off" sharp bilinear (each game pixel a block of the same width), "smooth" bilinear (Direct3D's own stretch), "fsr1" AMD FidelityFX Super
# Resolution 1, "nis" NVIDIA Image Scaling. The names are the layer's (UPSCALE_NAMES in native/cardreader/postmath.c).
UPSCALES = ("off", "smooth", "fsr1", "nis")

# The upscale filters that sharpen, and so the ones the sharpness reads (the others ignore it).
SHARPENING_UPSCALES = ("fsr1", "nis")

# How much FSR 1 and NIS sharpen, from 0 (none) to 100 (the most).
SHARPNESS_RANGE = (0, 100)

# Smoothing of the game's jagged edges before the picture is enlarged: FXAA or SMAA at its four presets. No
# multisampling: it changes no pixel of the game's static pictures (docs/architecture.md). The names are the layer's
# (AA_NAMES in native/cardreader/postmath.c).
ANTIALIASINGS = ("off", "fxaa", "smaa-low", "smaa-medium", "smaa-high", "smaa-ultra")

# The picture choices' defaults, kept in one place and equal to the layer's own (UPSCALE_DEFAULT, SHARPNESS_DEFAULT
# and AA_DEFAULT in native/cardreader/postmath.h), so a game started without the launcher looks the same.
UPSCALE_DEFAULT = "fsr1"
SHARPNESS_DEFAULT = 50
ANTIALIASING_DEFAULT = "off"

# The frame rate chip's corner while it is on, in the layer's order (CORNER_* in native/cardreader/logic.h). The bottom
# right is the default: there, above the game's FREE PLAY label, the chip covers none of the game's own labels or
# buttons on any of its screens (measured), where the very edge of every corner holds some.
FPS_POSITIONS = ("top_left", "top_right", "bottom_left", "bottom_right")
FPS_POSITION_DEFAULT = "bottom_right"

# The game's 1280x768 picture (5:3) in a window or screen of another shape: "keep" its shape, the largest such
# rectangle centred with bars of the launcher's darkest neutral on the other two sides (the default: at 16:9 a
# stretched picture is 6.7 % wider than drawn, at 21:9 43 %, at 5:4 25 % narrower), or "fill" the window. The pointer
# and a finger reach the game pixel under them either way (native/cardreader/logic.c pointer_for_game).
PICTURE_SHAPES = ("keep", "fill")
PICTURE_SHAPE_DEFAULT = "keep"

# The sound device: Windows' default output (followed when Windows changes it), or one output device by its
# DirectSound GUID, as the Sound page lists them (client/sound_devices.py).
DEFAULT_DEVICE = "default"
_GUID = re.compile(r"\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}")

# The game's volume scale (setting.ini comment: "0 ~ 127").
VOLUME_MAX = 127

# Every choice with its default. The defaults are the game's own values in its original setting.ini, except the
# mouse pointer, which a PC needs (the cabinet hid it under the touch screen).
DEFAULTS = {
    "display_mode": "fullscreen",   # borderless over the whole primary monitor
    "window_size": "1280x768",      # used in window mode only
    "vsync": True,                  # setting.ini vsync=true
    "glow": True,                   # setting.ini fullscene_glow=true
    "videos": True,                 # setting.ini UseVedio=true (the background videos behind the notes)
    "preload": False,               # setting.ini resource_preload=false and PreLoadMovie=false
    "cursor": True,                 # setting.ini show_cursor: shown for a mouse, hidden for a touch screen
    "music_volume": 100,            # percent of bgm_volume 127
    "key_volume": 100,              # percent of sfx_volume 127 (notes and key sounds)
    "frame_pacing": "music",        # 60.0 a second by openDMT3's clock, led by a song's music (measured: the notes
                                    # stay within a frame of the music over a song; the client's own steps fall behind
                                    # it by about a quarter of a second a minute); not a setting.ini line
    "show_fps": False,              # the frame rate chip over the game (the layer's)
    "fps_position": FPS_POSITION_DEFAULT,  # its corner while it is on (the layer's; kept while it is off)
    "picture_shape": PICTURE_SHAPE_DEFAULT,  # the game's own shape kept with bars, or filling the window (the layer's)
    "sound_device": DEFAULT_DEVICE, # Windows' default output (not a setting.ini line: the layer's)
    "low_latency": True,            # Windows' sound engine at the shortest period the game's output offers while the
                                    # game runs, 10 ms otherwise (the layer's: native/cardreader/engine.c)
    "upscale": UPSCALE_DEFAULT,     # how the picture is enlarged to the window (the layer's)
    "sharpness": SHARPNESS_DEFAULT, # how much fsr1 and nis sharpen (the layer's)
    "antialiasing": ANTIALIASING_DEFAULT,  # edge smoothing before the enlarging (the layer's)
    "pass_times": False,            # the picture's GPU time measured by pass, into the launcher's log when the game
                                    # closes (the layer's; Help, Save a report carries it)
}

# The choices openDMT3's in-game layer reads when the game starts, not lines of setting.ini.
LAYER_CHOICES = ("frame_pacing", "show_fps", "fps_position", "sound_device", "upscale", "sharpness", "antialiasing",
                 "picture_shape", "pass_times", "low_latency")


class ChoiceError(ValueError):
    """A choice that is not one the launcher offers, worded for the person who made it."""


def _bool(name, value):
    """A yes/no choice; accepts the forms a settings file or a command line gives."""
    # JSON and the launcher pass real booleans.
    if isinstance(value, bool):
        return value
    # A command line passes text.
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    raise ChoiceError("%s takes on or off, not %r" % (name, value))


def _named(name, value, offered):
    """One of a fixed list of names; case and spaces around do not matter (the layer reads any case too)."""
    text = str(value).strip().lower()
    if text not in offered:
        # The whole list is said, so the person sees what to type instead.
        raise ChoiceError("%s takes %s, not %r" % (name, " or ".join(offered), value))
    return text


def _percent(name, value):
    """A volume or a strength in percent, 0 to 100."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ChoiceError("%s takes a number from 0 to 100, not %r" % (name, value)) from None
    # Out-of-range numbers are refused rather than clamped, so a typo never passes silently.
    if not 0 <= number <= 100:
        raise ChoiceError("%s takes a number from 0 to 100, not %r" % (name, value))
    return number


def normalize(values):
    """Every choice, checked, with the defaults filled in for those not given.

    Unknown names are refused: a misspelt choice would otherwise be kept and never take effect.
    """
    # Start from the defaults so a partial set (an old settings file, one command-line change) is complete.
    out = dict(DEFAULTS)
    for name, value in (values or {}).items():
        if name not in DEFAULTS:
            raise ChoiceError("there is no setting called %r" % name)
        if name == "display_mode":
            if value not in DISPLAY_MODES:
                raise ChoiceError("display_mode takes %s, not %r" % (" or ".join(DISPLAY_MODES), value))
            out[name] = value
        elif name == "window_size":
            if value not in WINDOW_SIZES:
                raise ChoiceError("window_size takes one of %s, not %r" % (", ".join(WINDOW_SIZES), value))
            out[name] = value
        elif name == "frame_pacing":
            out[name] = _named(name, value, FRAME_PACINGS)
        elif name == "upscale":
            out[name] = _named(name, value, UPSCALES)
        elif name == "antialiasing":
            out[name] = _named(name, value, ANTIALIASINGS)
        elif name == "fps_position":
            out[name] = _named(name, value, FPS_POSITIONS)
        elif name == "picture_shape":
            out[name] = _named(name, value, PICTURE_SHAPES)
        elif name == "sound_device":
            text = str(value).strip()
            if text.lower() == DEFAULT_DEVICE:
                out[name] = DEFAULT_DEVICE
            elif _GUID.fullmatch(text):
                # GUIDs are kept in upper case, as Windows writes them, so one device is always one text.
                out[name] = text.upper()
            else:
                raise ChoiceError("sound_device takes default or a device's GUID ({xxxxxxxx-xxxx-xxxx-xxxx-"
                                  "xxxxxxxxxxxx}, as --sound-devices lists them), not %r" % value)
        elif name in ("music_volume", "key_volume", "sharpness"):
            out[name] = _percent(name, value)
        else:
            # The rest are on/off choices.
            out[name] = _bool(name, value)
    return out


def to_game_volume(percent):
    """Percent (0 to 100) on the game's 0 to 127 scale, rounded to the nearest step."""
    return int(round(percent * VOLUME_MAX / 100.0))


def ini_changes(values):
    """The setting.ini lines the choices write, as {key: text}.

    The setting step adds the lines every PC needs (no exclusive full screen, the data folder paths) on top.
    """
    v = normalize(values)
    # Window mode keeps the frame; full-screen mode is a borderless window the display fix stretches.
    borderless = v["display_mode"] == "fullscreen"
    # The window size is written only for window mode; full screen keeps the game's 1280x768, which the fix
    # replaces with the monitor's size when the window opens.
    width, height = (v["window_size"] if not borderless else "1280x768").split("x")
    # setting.ini spells booleans in lower case.
    flag = lambda b: "true" if b else "false"
    return {
        "popup_style": flag(borderless),
        "screen_width": width,
        "screen_height": height,
        "vsync": flag(v["vsync"]),
        "fullscene_glow": flag(v["glow"]),
        "UseVedio": flag(v["videos"]),
        "resource_preload": flag(v["preload"]),
        "PreLoadMovie": flag(v["preload"]),
        "show_cursor": flag(v["cursor"]),
        "bgm_volume": str(to_game_volume(v["music_volume"])),
        "sfx_volume": str(to_game_volume(v["key_volume"])),
    }


def layer_environment(values, language="en"):
    """What openDMT3's in-game layer (CRT_R1.dll, native/cardreader) reads from its environment when the game starts:
    the words' language, whether it draws its own pointer, the frame pacing, the frame rate chip and its corner, the
    sound device and whether its sound engine's shortest period is asked for, the upscale filter with its sharpness,
    the anti-aliasing, the picture's shape, whether the picture's GPU time is measured by pass. PLAY starts the game
    with these on top of the launcher's own environment."""
    v = normalize(values)
    return {
        # The menu's and the question's words follow the launcher's language.
        "OPENDMT3_LANGUAGE": "ko" if language == "ko" else "en",
        # A touch screen hides the pointer (show_cursor in setting.ini): the layer then leaves it to the game.
        "OPENDMT3_CURSOR": "on" if v["cursor"] else "off",
        # The client's own 60 a second, or openDMT3's even clock at the same rate.
        "OPENDMT3_PACING": v["frame_pacing"],
        # The frame rate chip over the game, and its corner.
        "OPENDMT3_FPS": "on" if v["show_fps"] else "off",
        "OPENDMT3_FPS_POSITION": v["fps_position"],
        # Empty: Windows' default output, as the game opens it by itself.
        "OPENDMT3_SOUND_DEVICE": "" if v["sound_device"] == DEFAULT_DEVICE else v["sound_device"],
        # The sound engine's shortest period on that device while the game runs, or Windows' own.
        "OPENDMT3_LOW_LATENCY": "on" if v["low_latency"] else "off",
        # How the picture is enlarged to the window, by the layer's names for it.
        "OPENDMT3_UPSCALE": v["upscale"],
        # FSR 1's and NIS's sharpening as decimal text; always passed, so the layer never falls back to its own.
        "OPENDMT3_SHARPNESS": str(v["sharpness"]),
        # Edge smoothing before the enlarging, by the layer's names for it.
        "OPENDMT3_ANTIALIASING": v["antialiasing"],
        # The game's own shape kept with bars beside it, or the window filled.
        "OPENDMT3_PICTURE_SHAPE": v["picture_shape"],
        # The picture's GPU time by pass: the layer's note beside it, read into the launcher's log at the game's end.
        "OPENDMT3_PASS_TIMES": "on" if v["pass_times"] else "off",
    }
