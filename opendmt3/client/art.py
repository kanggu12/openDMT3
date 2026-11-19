"""Pictures the launcher draws for itself, in the style of TECHNIKA 3's screens.

Everything here is drawn in code (no game art ships with openDMT3). When the player's game folder is known, the
header also shows a few song discs read from the player's own archives at run time; they are never saved.
Shapes are drawn three times larger and scaled down, because Tk's own canvas does not smooth diagonal edges.
"""

import collections
import functools
import io
import itertools
import logging
import math
import random
import threading
import time

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from opendmt3.client import theme

log = logging.getLogger("opendmt3.launcher")

# Draw at this many times the final size, then scale down: smooth edges without a drawing library.
SS = 3
# The stage's facets are drawn at twice their size, not three times: their edges are low in contrast, and the third
# time cost more than the long shards over them.
FACET_SS = 2
# The stage behind every head (core/stage.py), without its colour, by the head's size in pixels (which carries the
# scaling): one picture for every page of a window size, since every page has the same composition. A resize leaves the
# old size's to go first.
_STAGES = collections.OrderedDict()
STAGES_KEPT = 4
# A head's ground (the stage with its section's colour, its fade and its spotlight) by size and colours: a page shown
# again takes it from here. The stage is most of a head's drawing; the colour adds about 2 ms at 100 % (5 ms at 200 %).
_GROUNDS = collections.OrderedDict()
GROUNDS_KEPT = 10
_grounds_lock = threading.Lock()
# The kept small pictures (_kept) are looked up and stored one thread at a time.
_kept_lock = threading.Lock()


def _key_of(value):
    """An argument as part of a kept picture's key: a dict (a section's colours) and a list (a row's words) as
    tuples, anything else as it is."""
    if isinstance(value, dict):
        # The colours by name, in one order whatever order the dict has them in.
        return tuple(sorted((name, _key_of(v)) for name, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_key_of(v) for v in value)
    return value


def _kept(most):
    """Keep what a picture function draws, by its arguments, the `most` last asked for (a decorator).

    A page is made anew at every visit, its cards, buttons, switches and rows of choices with it, and each drew its
    pictures again: about 30 ms of a page switch at 200 % went to drawing what the last visit had drawn, and
    buttons and switches that look alike drew alike pictures each. The function must draw from its arguments and the
    theme alone, and its callers never change the picture they get (each makes its own Tk image of it). A call drawn
    over another picture (a dialog's button over its panel's pixels: button_face's `under`) is drawn every time, as
    one whose arguments cannot make a key."""
    def keep(draw):
        # key -> picture, the least recently asked for first.
        found = collections.OrderedDict()

        @functools.wraps(draw)
        def kept(*args, **kwargs):
            if any(isinstance(v, Image.Image) for v in itertools.chain(args, kwargs.values())):
                # Drawn over another picture: nothing to keep it by.
                return draw(*args, **kwargs)
            try:
                # The arguments as they were given (positional, then by name in one order).
                key = (_key_of(args), _key_of(sorted(kwargs.items())))
                hash(key)
            except TypeError:
                # An argument that cannot be a key (none of today's callers gives one): drawn as before.
                return draw(*args, **kwargs)
            with _kept_lock:
                picture = found.get(key)
                if picture is not None:
                    found.move_to_end(key)
                    return picture
            # Drawn outside the lock: two threads asking at once each draw it, and the second's is kept.
            picture = draw(*args, **kwargs)
            with _kept_lock:
                found[key] = picture
                while len(found) > most:
                    # The least recently asked for goes first (another window scaling's, a page not seen for long).
                    found.popitem(last=False)
            return picture

        # The kept pictures, for the tests.
        kept.kept = found
        return kept
    return keep


# Steel chrome, top to bottom (TECHNIKA 3's title-screen wordmark, measured): bright, a bright line just over the dark
# band where the horizon reflects, the band, then bright again.
CHROME = ((0.0, "#ffffff"), (0.40, "#e4e8ed"), (0.465, "#f7f9fb"), (0.50, "#737c88"), (0.57, "#c7cdd5"),
          (0.76, "#b2b9c2"), (1.0, "#eef1f4"))


def _rgb(hex_colour):
    """'#1f5bff' -> (31, 91, 255)."""
    h = hex_colour.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lit_chrome(colour):
    """Chrome that turns into a colour towards its foot, for the last letter of a mark (the logo's blue 3)."""
    return ((0.0, "#ffffff"), (0.38, "#e9eefc"), (0.6, colour), (1.0, colour))


def _ramp(size, stops):
    """A vertical gradient through several colours: stops are (place 0..1, colour)."""
    w, h = size
    column = Image.new("RGB", (1, max(2, h)))
    for y in range(column.height):
        t = y / float(column.height - 1)
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if t0 <= t <= t1:
                k = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
                a, b = _rgb(c0), _rgb(c1)
                column.putpixel((0, y), tuple(int(round(a[i] + (b[i] - a[i]) * k)) for i in range(3)))
                break
    return column.resize((max(1, w), max(1, h)), Image.BILINEAR)


def _stage_pieces():
    """The stage's pieces (core/stage.py), read once."""
    from opendmt3.core import stage as composition
    global _PIECES
    if _PIECES is None:
        _PIECES = composition.pieces()
    return _PIECES


_PIECES = None
# The tones of the stage's pieces that have no colour (the coloured ones take the section's).
_TONES = {"white": (255, 255, 255), "black": (0, 0, 0)}


def _stage(width, height):
    """The stage without its colour (core/stage.py): the faceted ground and the long shards over the window's metal, an
    RGBA picture, before its fade. Kept by size (_STAGES)."""
    from opendmt3.core import stage as composition
    key = (width, height)
    with _grounds_lock:
        kept = _STAGES.get(key)
        if kept is not None:
            _STAGES.move_to_end(key)
            return kept
    img = Image.new("RGBA", (width, height), _rgb(theme.BG) + (255,))
    for k, wanted in ((FACET_SS, ("white", "black")), (SS, ("charcoal", "steel"))):
        # The facets on a layer of their own at twice the size, then the shards at three times, each brought down.
        layer = Image.new("RGBA", (width * k, height * k), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        for piece in _stage_pieces():
            if piece["tone"] not in wanted:
                continue
            colour = _TONES.get(piece["tone"]) or (composition.CHARCOAL if piece["tone"] == "charcoal" else composition.STEEL)
            draw.polygon([(x * width * k, y * height * k) for x, y in piece["points"]],
                         fill=colour + (int(round(piece["alpha"] * 255)),))
        img.alpha_composite(layer.resize((width, height), Image.LANCZOS))
    with _grounds_lock:
        _STAGES[key] = img
        while len(_STAGES) > STAGES_KEPT:
            _STAGES.popitem(last=False)
    return img


def stage_ground(width, height, colours):
    """A head's ground: the stage, its four coloured pieces in the section's colours (drawn each in its own small box,
    three times larger), the fade from the left (the title on plain metal), and the spotlight from above behind the
    title. Kept by size and colours (_GROUNDS); callers never change the picture they get."""
    from opendmt3.core import stage as composition
    key = (width, height, tuple(sorted(colours.items())))
    with _grounds_lock:
        kept = _GROUNDS.get(key)
        if kept is not None:
            _GROUNDS.move_to_end(key)
            return kept
    img = _stage(width, height).copy()
    for piece in _stage_pieces():
        if not composition.coloured(piece):
            continue
        pts = [(x * width, y * height) for x, y in piece["points"]]
        x0, y0 = max(0, int(min(p[0] for p in pts))), max(0, int(min(p[1] for p in pts)))
        x1, y1 = min(width, int(max(p[0] for p in pts)) + 1), min(height, int(max(p[1] for p in pts)) + 1)
        if x1 <= x0 or y1 <= y0:
            continue
        # Only the piece's own box is drawn three times larger: four pieces cost what one small picture does.
        mask = Image.new("L", ((x1 - x0) * SS, (y1 - y0) * SS), 0)
        ImageDraw.Draw(mask).polygon([((x - x0) * SS, (y - y0) * SS) for x, y in pts],
                                     fill=int(round(piece["alpha"] * 255)))
        mask = mask.resize((x1 - x0, y1 - y0), Image.LANCZOS)
        colour = _rgb(colours["deep"] if piece["tone"] == "deep" else colours["light"])
        img.paste(colour + (255,), (x0, y0, x1, y1), mask)
    # The fade from the left: the stage comes in from nothing to all of it by FADE_TO of the width.
    fade = Image.linear_gradient("L").rotate(90, expand=True).resize((width, height))
    plain = Image.new("RGBA", (width, height), _rgb(theme.BG) + (255,))
    img = Image.composite(img, plain, fade.point(lambda v: min(255, int(v / composition.FADE_TO))))
    # The spotlight from above behind the title: an ellipse of light, white with a little of the section's colour,
    # strongest at its middle and falling off as the square of the distance.
    spot = composition.SPOT
    rx, ry = max(1, int(spot["rx"] * width)), max(1, int(spot["ry"] * width))
    radial = Image.radial_gradient("L").resize((2 * rx, 2 * ry), Image.BILINEAR).point(
        lambda v: int(255 * spot["alpha"] * max(0.0, 1 - v / 255.0) ** 2))
    light = Image.new("L", (width, height), 0)
    light.paste(radial, (int(spot["x"] * width) - rx, int(spot["y"] * height) - ry))
    img.paste(composition.spot_colour(_rgb(colours["accent"])) + (255,), (0, 0), light)
    picture = img.convert("RGB")
    with _grounds_lock:
        _GROUNDS[key] = picture
        while len(_GROUNDS) > GROUNDS_KEPT:
            # The least recently shown go first (another window size's, after a resize).
            _GROUNDS.popitem(last=False)
    return picture


def shards(width, height, seed=None, density=1.0, colours=None):
    """The stage behind a window of its own (a dialog with no launcher behind it, the installer's pictures): the same
    composition as every head (`seed` and `density` are no longer used: one composition everywhere), in the section's
    colours, the title screen's blue unless told."""
    return stage_ground(width, height, colours or theme.SECTION_COLOURS["technika"])


def tube(img, colours, scale=1.0):
    """The section's colour as a thin tube along a head's foot (the Platinum Crew site's line over its pages): three
    rows light, full, light, and a shade under them, each row a logical pixel. Drawn on `img` in place."""
    row = max(1, int(round(scale)))
    w, h = img.size
    draw = ImageDraw.Draw(img)
    for i, colour in enumerate((_rgb(colours["light"]), _rgb(colours["accent"]), _rgb(colours["light"]), (8, 10, 12))):
        draw.rectangle([0, h - (4 - i) * row, w - 1, h - (3 - i) * row - 1], fill=colour)


def read_discs(game, count=4, seed=None):
    """A few song discs (round song art) from the player's own archives, chosen by date so they change daily.

    Returns PIL images, or [] when the archive cannot be read; the header then shows the shards alone.
    """
    try:
        with game.open_pak(game.pak_path("DiscImg")) as pak:
            # "_0" is each song's main disc; the others are smaller variants of the same art.
            entries = [e for e in pak.entries if e.name.lower().endswith("_0.png")]
            if not entries:
                return []
            rng = random.Random(seed if seed is not None else time.strftime("%Y%m%d"))
            picks = rng.sample(entries, min(count, len(entries)))
            return [Image.open(io.BytesIO(pak.read(e))).convert("RGBA") for e in picks]
    except Exception:  # noqa: BLE001  (a header picture must never stop the launcher)
        # The head shows the stage alone; why is in the log (a damaged or missing archive was said nowhere).
        log.warning("the song discs for PLAY's head could not be read", exc_info=True)
        return []


def _title_font(text, size):
    """The wide face for Latin, Pretendard Bold where there is Hangul (the wide face has none)."""
    hangul = any("가" <= ch <= "힣" or "ㄱ" <= ch <= "ㆎ" for ch in text)
    return ImageFont.truetype(theme.HANGUL_TITLE_FILE if hangul else theme.WIDE_FILE, size)


def chrome_text(parts, size, scale=1.0):
    """Words with a chrome face, a dark rim and a soft shadow, like the game's logo lettering.

    parts: [(text, stops)] drawn one after another, so a mark can end in another colour (the logo's blue 3).
    Returns an RGBA picture just big enough, and the baseline's height in it.
    """
    font = _title_font("".join(t for t, _ in parts), size)
    rim = max(1, int(round(1.4 * scale)))
    pad = rim + int(6 * scale)
    ascent, descent = font.getmetrics()
    width = int(sum(font.getlength(t) for t, _ in parts)) + 2 * pad
    height = ascent + descent + 2 * pad
    baseline = pad + ascent
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    fill_mask = Image.new("L", img.size, 0)
    rim_mask = Image.new("L", img.size, 0)
    colour = Image.new("RGB", img.size, (0, 0, 0))
    x = pad
    # The gradient spans the capitals, so the dark band sits across every letter at the same height.
    top = baseline - int(font.getbbox("H")[3] - font.getbbox("H")[1])
    for text, stops in parts:
        piece = Image.new("L", img.size, 0)
        ImageDraw.Draw(piece).text((x, baseline), text, font=font, fill=255, anchor="ls")
        ImageDraw.Draw(rim_mask).text((x, baseline), text, font=font, fill=255, anchor="ls", stroke_width=rim,
                                      stroke_fill=255)
        ramp = _ramp((width, baseline - top + 2), stops)
        layer = Image.new("RGB", img.size, _rgb(stops[-1][1]))
        layer.paste(_rgb(stops[0][1]), (0, 0, width, top))
        layer.paste(ramp, (0, top))
        colour.paste(layer, (0, 0), piece)
        fill_mask.paste(255, (0, 0), piece)
        x += font.getlength(text)
    shadow = rim_mask.filter(ImageFilter.GaussianBlur(3 * scale)).point(lambda v: int(v * 0.7))
    img.paste((0, 0, 0, 255), (0, int(2 * scale)), shadow)
    img.paste(_rgb(theme.INK) + (255,), (0, 0), rim_mask)
    rgba = colour.convert("RGBA")
    img.paste(rgba, (0, 0), fill_mask)
    return img, baseline


# PLAY's discs made to the head's size, with their shadows, by disc and size (_disc_at): PLAY's head is drawn at every
# visit of the page and after every resize, and the discs stay the same all day. Four discs at two sizes.
_DISCS = collections.OrderedDict()
DISCS_KEPT = 8


def _disc_at(disc, size):
    """`disc` (a song's round art, RGBA) at `size` pixels and its shadow, a blurred dark copy that lifts it off the
    head: (disc, shadow), kept by the disc and the size. The disc itself is kept with them, so another disc that
    Python gives the same id later never takes its place."""
    key = (id(disc), size)
    with _kept_lock:
        found = _DISCS.get(key)
        if found is not None and found[0] is disc:
            _DISCS.move_to_end(key)
            return found[1], found[2]
    d = disc.resize((size, size), Image.LANCZOS)
    # Three quarters of the disc's own shape in black, blurred.
    shadow = Image.new("RGBA", d.size, (0, 0, 0, 0))
    shadow.putalpha(d.getchannel("A").point(lambda a: a * 0.75))
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(2, size // 22)))
    with _kept_lock:
        _DISCS[key] = (disc, d, shadow)
        while len(_DISCS) > DISCS_KEPT:
            # Another day's discs, or another window size's, go first.
            _DISCS.popitem(last=False)
    return d, shadow


# The shade over the discs at the head's size: the window's size now and the last one.
@_kept(2)
def _discs_shade(width, height):
    """The shade over PLAY's discs, the window's colour from nothing at the head's right edge to 55 % at its left, so
    that the title keeps its contrast: an RGBA picture of the head's size."""
    fade = Image.linear_gradient("L").rotate(90, expand=True).resize((width, height))
    shade = Image.new("RGBA", (width, height), _rgb(theme.BG) + (0,))
    shade.putalpha(fade.point(lambda v: int((255 - v) * 0.55)))
    return shade


def header(width, height, discs=(), seed=None, colours=None, title=None, title_tail=None, scale=1.0,
           title_at=(32, 98)):
    """The page header: the stage (one composition on every page, `seed` no longer used) with its section's colour, the
    discs along the right edge, the page's title in steel chrome (its tail, such as the 3 of TECHNIKA 3, in the
    section's colour), and the section's tube along its foot.

    title_at is the title's left edge and baseline in logical pixels.
    """
    colours = colours or theme.SECTION_COLOURS["technika"]
    # The ground kept for this size and section (drawn the first time), copied to draw the rest over (convert copies).
    img = stage_ground(width, height, colours).convert("RGBA")
    if discs:
        # The discs are as tall as most of the header and overlap like a row of records.
        size = int(height * 0.78)
        step = int(size * 0.62)
        x = width - size - int(height * 0.18)
        y = (height - size) // 2
        for disc in discs:
            # The disc at its size and its shadow, kept from the last head of this size (_disc_at).
            d, shadow = _disc_at(disc, size)
            img.alpha_composite(shadow, (x + size // 30, y + size // 24))
            img.alpha_composite(d, (x, y))
            x -= step
            if x < width * 0.45:
                # Never under the title on the left.
                break
        # Darken the discs a little towards the left so the title keeps the contrast.
        img.alpha_composite(_discs_shade(width, height))
    if title:
        parts = [(title, CHROME)]
        if title_tail and title.endswith(title_tail):
            parts = [(title[:-len(title_tail)], CHROME), (title_tail, lit_chrome(colours["accent"]))]
        words, baseline = chrome_text(parts, int(round(34 * scale)), scale)
        pad = int(6 * scale) + max(1, int(round(1.4 * scale)))
        img.alpha_composite(words, (int(title_at[0] * scale) - pad, int(title_at[1] * scale) - baseline))
    img = img.convert("RGB")
    tube(img, colours, scale)
    return img


def logo(width, scale=1.0, label="LAUNCHER", accent=theme.BLUE_HI, version=None):
    """openDMT3's mark, `width` pixels wide, in the proportions of the family's logo (OpenDMTQ's, measured from its
    drawing): OPEN in heavy capitals a third as tall as the name's (0.345 of them), right over it (a quarter of the
    name's height apart), with a slab after it running grey into the accent up to the right edge; DMT3 in chrome with
    the TECHNIKA 3 logo's blue 3, upright as that logo stands; the label small at DMT3's foot on the right. With
    `version`, the version stands over the label in light text, where a product's version usually sits.

    DMT3 keeps one size whatever the version: the room beside it is as wide as "v0.0.0" in 12 px. A longer version
    takes a smaller size there (down to 9 px), and one longer still goes on a line of its own under the mark."""
    tiny = ImageFont.truetype(theme.WIDE_FILE, max(7, int(round(7.5 * scale))))
    shown = "v" + version if version else ""

    def version_font(points):
        return ImageFont.truetype(theme.WIDE_FILE, max(8, int(round(points * scale))))

    # Larger than the label: the version is read, not just seen (12 px at 100 % scaling).
    room = version_font(12).getlength("v0.0.0") if shown else 0
    label_w = int(max(tiny.getlength(label), room)) + int(6 * scale)
    pad = int(6 * scale) + max(1, int(round(1.4 * scale)))   # chrome_text's room around its letters
    # The label and the version start 4 px after the 3's last pixel (chrome_text's picture keeps `pad` of room right
    # of it): one lockup, not a name and a block set apart.
    after = int(round(4 * scale)) - pad
    # DMT3 as large as the width allows beside its label.
    size = int(round(44 * scale))
    while size > 12:
        big, baseline = chrome_text([("DMT", CHROME), ("3", lit_chrome(accent))], size, scale)
        if big.width + after + label_w <= width:
            break
        size -= 1
    cap = 0.688 * size                                        # the face's capital height (OS/2), DMT3's letters
    # OPEN: capitals 0.345 of DMT3's, spaced 0.2 of their size apart (the family logo's measures).
    o_size = max(6, int(round(0.345 * cap / 0.688)))
    small = ImageFont.truetype(theme.WIDE_FILE, o_size)
    o_cap = 0.688 * o_size
    o_top = 2 * scale                                         # OPEN's capitals start just under the picture's top
    o_base = o_top + o_cap
    # DMT3's capitals a quarter of their height under OPEN's foot; chrome_text's picture has its baseline at
    # `baseline`, the capitals' top `cap` above it.
    d_cap_top = o_base + 0.25 * cap
    d_top = int(round(d_cap_top + cap - baseline))
    # The version's size: the largest from 12 px down to 9 px that fits beside DMT3, else 12 px on a line below.
    beside = width - (big.width + after) - 1
    vfont, below = None, False
    if shown:
        for points in (12, 11, 10, 9):
            if version_font(points).getlength(shown) <= beside:
                vfont = version_font(points)
                break
        if vfont is None:
            vfont, below = version_font(12), True
    line = int(round(18 * scale)) if below else 0
    height = d_top + big.height + line
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # OPEN, letter by letter, starting where DMT3's first letter starts (chrome_text's pad).
    x = pad
    for ch in "OPEN":
        draw.text((x, o_base), ch, font=small, fill=_rgb(theme.TEXT) + (255,), anchor="ls")
        x += small.getlength(ch) + 0.2 * o_size
    # The slab: after OPEN by 0.86 of its height, as thick as half of it along its top, to the right edge, its end cut
    # on the slant of the game's plates; grey turning into the accent. With nothing beside DMT3 (no label, no version:
    # the in-game bar's mark) it ends over the 3's last pixel, never running on over nothing.
    left, right = x - 0.2 * o_size + 0.86 * o_cap, width - 1
    if not label and not shown:
        # The 3's own edge: its pixels more than half covered (its rim's faint fringe left out).
        right = big.getchannel("A").point(lambda v: 255 if v > 128 else 0).getbbox()[2] - 1
    top, foot = o_top + 0.03 * o_cap, o_top + 0.52 * o_cap
    mask = _mask(img.size, lambda d, k: d.polygon([(left * k, top * k), (right * k, top * k),
                                                   ((right - (foot - top)) * k, foot * k), (left * k, foot * k)],
                                                  fill=255))
    ramp = Image.linear_gradient("L").rotate(90, expand=True).resize(img.size)
    tint = Image.composite(Image.new("RGBA", img.size, _rgb(accent) + (255,)),
                           Image.new("RGBA", img.size, (0x8f, 0x99, 0xa4, 255)), ramp)
    img.paste(tint, (0, 0), mask)
    # chrome_text leaves room over the capitals (the face's ascent); what is cut off above is empty.
    img.alpha_composite(big, (0, max(0, d_top)), (0, max(0, -d_top)))
    # The label sits on the big letters' baseline, after them.
    foot_y = d_top + baseline
    draw.text((big.width + after, foot_y), label, font=tiny, fill=_rgb(accent) + (255,), anchor="ls")
    if shown and not below:
        # Over the label, a line apart, in the text colour (readable at a glance, unlike the faint footers).
        draw.text((big.width + after, foot_y - int(round(13 * scale))), shown, font=vfont,
                  fill=_rgb(theme.TEXT) + (255,), anchor="ls")
    elif shown:
        # Too long to stand beside DMT3: under the mark, lined up with OPEN.
        draw.text((pad, height - int(round(4 * scale))), shown, font=vfont, fill=_rgb(theme.TEXT) + (255,),
                  anchor="ls")
    return img


# How far a leaning edge runs sideways for each pixel of its height: one slope for every plate, tab and button.
LEAN = 0.36

# The menu column's lockup: its width in logical pixels, the column's room between its sides (widgets.Rail: 248 wide,
# 18 either side, and its seam).
BRAND_WIDTH = 210


def brand(scale=1.0, version="", label="LAUNCHER", width=BRAND_WIDTH, accent=theme.BLUE_HI):
    """The menu column's top: openDMT3's lockup as the site's bar sets DMT3 SERVER (logo: OPEN and its slab over DMT3
    with the TECHNIKA 3 logo's blue 3, the label at DMT3's foot on the right and the version over it, right beside
    DMT3 under the slab's end), `width` logical pixels wide at `scale`. DMT3 is the same size whatever the version, and
    a usual one is set at the version's 12 px. Cut to its first and last pixels, so that the column's rooms alone
    place it. Returns an RGBA picture."""
    made = logo(int(round(width * scale)), scale, label=label, accent=accent, version=version or None)
    return made.crop(made.getbbox())


def numeral(text, colour, scale=1.0, size=28):
    """A step's number, upright in the wide face in one colour, as the guide's steps down the menu column set it
    (OpenDMTQ's lean, TECHNIKA 3's stand). Returns an RGBA picture just as tall as the figure."""
    k = SS
    t = size * scale * k
    font = ImageFont.truetype(theme.WIDE_FILE, max(1, int(round(t))))
    # The figure's own height (the face's capitals, 0.688 of its size) and a pixel of room round it.
    cap = 0.688 * t
    width = int(math.ceil(font.getlength(text) + 2 * k))
    height = int(math.ceil(cap + 2 * k))
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((k, k + cap), text, font=font, fill=_rgb(colour) + (255,), anchor="ls")
    return img.resize((max(1, width // k), max(1, height // k)), Image.LANCZOS)


def cut_masks(cut):
    """A cut top-right corner (a card's, a dialog's, the menu's lit slab's), as masks of its `cut` x `cut` square at
    the box's top-right: (beyond, seam). beyond is what lies past the cut, where the page shows; seam is the box's
    one-pixel edge going on along the cut's diagonal at the edge's own weight (a pixel across, at right angles to it),
    from the top edge at the square's left side to the right edge at its foot, so that no square corner is left. Drawn
    SS times larger and brought down by area, so the diagonal is smooth and its ends meet the straight edges."""
    k = SS
    s = cut * k
    beyond = Image.new("L", (s, s), 0)
    ImageDraw.Draw(beyond).polygon([(0, 0), (s, 0), (s, s)], fill=255)
    # One pixel across a 45-degree line is the square root of two down a column.
    band = math.sqrt(2) * k
    seam = Image.new("L", (s, s), 0)
    ImageDraw.Draw(seam).polygon([(0, 0), (s, s), (s - band, s), (0, band)], fill=255)
    return beyond.resize((cut, cut), Image.BOX), seam.resize((cut, cut), Image.BOX)


# A card's corner: one or two looks at a scaling (on a card, on a dialog), every card of every page.
@_kept(16)
def corner(size, inside, outside, seam=None, rim=None):
    """A card's top-right corner, cut as the family's panels are (both sites' and OpenDMTQ's launcher's): the picture
    laid over the card's square corner, seam included (cut_masks): the page's colour beyond the cut, the card's seam
    along it, the card's inside under it. With `rim`, the seam along the cut starts in the top edge's light and fades to
    the seam's colour at the right edge (the top light follows the cut)."""
    beyond, line = cut_masks(size)
    img = Image.new("RGB", (size, size), _rgb(inside))
    img.paste(_rgb(outside), (0, 0), beyond)
    if seam:
        img.paste(_gradient((size, size), rim, seam) if rim else _rgb(seam), (0, 0), line)
    return img


def _slanted(size, slant, cut_left=True):
    """A parallelogram's points in a box: the game's plates lean, their ends cut on the same slope."""
    w, h = size
    return [(slant if cut_left else 0, 0), (w, 0), (w - slant, h), (0, h)]


def striped_plate(width, height, fill, light, edge, rim=True, cut_left=True):
    """The game's chosen plate (TOUCH TO START on the mode select): a leaning slab of one colour with light stripes
    running across it on the slant, a bright rim along the top and a darker one along the foot.

    fill: the slab, light: its stripes and top rim, edge: the foot. Returns an RGBA picture."""
    w, h = width * SS, height * SS
    slant = int(h * LEAN)
    shape = Image.new("L", (w, h), 0)
    ImageDraw.Draw(shape).polygon(_slanted((w, h), slant, cut_left), fill=255)
    slab = Image.new("RGBA", (w, h), _rgb(fill) + (255,))
    # Stripes: bands a third of the height wide, leaning the other way, at a quarter strength.
    bands = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(bands)
    step = max(4, h * 2 // 3)
    for x in range(-h, w + h, step):
        draw.polygon([(x, h), (x + step // 2, h), (x + step // 2 + h, 0), (x + h, 0)], fill=64)
    slab.paste(Image.new("RGBA", (w, h), _rgb(light) + (255,)), (0, 0), bands)
    # A sheen over the upper half, as on the game's glossy plates.
    sheen = Image.linear_gradient("L").resize((w, h)).point(lambda v: int(max(0, 128 - v) * 0.45))
    slab.paste(Image.new("RGBA", (w, h), (255, 255, 255, 255)), (0, 0), sheen)
    if rim:
        line = Image.new("L", (w, h), 0)
        ImageDraw.Draw(line).line([(slant, SS), (w - 1, SS)], fill=200, width=2 * SS)
        slab.paste(Image.new("RGBA", (w, h), _rgb(light) + (255,)), (0, 0), line)
        foot = Image.new("L", (w, h), 0)
        ImageDraw.Draw(foot).line([(0, h - SS * 2), (w - slant, h - SS * 2)], fill=220, width=2 * SS)
        slab.paste(Image.new("RGBA", (w, h), _rgb(edge) + (255,)), (0, 0), foot)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    img.paste(slab, (0, 0), shape)
    return img.resize((width, height), Image.LANCZOS)


def plain_plate(width, height, fill, top=None, cut_left=True):
    """A leaning slab of one colour (a choice under the pointer, a section's name plate), with a faint light top
    edge."""
    w, h = width * SS, height * SS
    slant = int(h * LEAN)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(img).polygon(_slanted((w, h), slant, cut_left), fill=_rgb(fill) + (255,))
    if top:
        line = Image.new("L", (w, h), 0)
        ImageDraw.Draw(line).line([(slant, SS // 2), (w - 1, SS // 2)], fill=255, width=SS)
        shape = Image.new("L", (w, h), 0)
        ImageDraw.Draw(shape).polygon(_slanted((w, h), slant, cut_left), fill=255)
        img.paste(Image.new("RGBA", (w, h), _rgb(top) + (255,)), (0, 0), Image.composite(line, Image.new("L", (w, h), 0), shape))
    return img.resize((width, height), Image.LANCZOS)


# A field is a slot sunk into its plate (FORMS.md): the well's dark, one pixel of machined edge, a shade along its top
# inside. Its edge by state: at rest, a step lighter under the pointer, the keyboard's cyan (two pixels, drawn inward)
# while it is typed in, the problem's pink while what was typed there is refused, quieter while it cannot be used.
FIELD_EDGES = {"normal": theme.SLOT_EDGE, "hover": theme.SLOT_EDGE_HOVER, "focus": theme.CYAN, "error": theme.PINK,
               "disabled": theme.SLOT_OFF_EDGE}
# The well's own colour by state: the slot's dark, between the well and the plate while it cannot be used.
FIELD_FILLS = {"disabled": theme.SLOT_OFF}


def _mixed(colour, other, amount):
    """`colour` with `amount` (0 to 1) of `other` over it, as RGB."""
    a, b = _rgb(colour), _rgb(other)
    return tuple(int(round(x + (y - x) * amount)) for x, y in zip(a, b))


def field_face(width, height, state="normal", scale=1.0, bg=None):
    """A text field's (or a drop-down's) face, as FORMS.md draws the slot: square (plates and keys are cut, slots are
    not), the well's dark, one pixel of edge in the state's colour (FIELD_EDGES; two pixels of the keyboard's cyan,
    drawn inward, while it is typed in; the pink edge with a faint pink line inside it while wrong), and one pixel of
    shade along its top inside (none while it cannot be used). Returns an RGB picture of the field's size (`bg` is
    not used: the face fills its box)."""
    fill = FIELD_FILLS.get(state, theme.FIELD)
    img = Image.new("RGB", (width, height), _rgb(fill))
    draw = ImageDraw.Draw(img)
    e = max(1, int(round(scale)))
    if state not in ("disabled", "focus"):
        # The shade inside the top edge, one pixel (two at 200 %) under it.
        draw.rectangle([e, e, width - 1 - e, 2 * e - 1], fill=_rgb(theme.SLOT_SHADE))
    edge = _rgb(FIELD_EDGES[state])
    # The edge, then a second ring inside it while typed in (the field keeps its size).
    for ring in range((2 if state == "focus" else 1) * e):
        draw.rectangle([ring, ring, width - 1 - ring, height - 1 - ring], outline=edge)
    if state == "error":
        # The faint pink halo (FORMS.md), drawn inside: the field keeps its box.
        halo = _mixed(fill, theme.PINK, 0.18)
        for ring in range(e, 2 * e):
            draw.rectangle([ring, ring, width - 1 - ring, height - 1 - ring], outline=halo)
    return img


def slot_key(width, height, state="normal", scale=1.0, focused=False):
    """A key inside a slot (a password's Show, a Copy): small quiet metal with two corners cut, as the keys lean (the
    top left and the foot's right); lighter under the pointer, lit while it is pressed in (Show while the password
    shows: a cyan line along its foot inside), and the keyboard's cyan ring inside its edge while it has the keyboard.
    Returns an RGBA picture."""
    k = SS
    w, h = width * k, height * k
    cut = max(1, int(round(4 * scale))) * k
    shape = [(cut, 0), (w, 0), (w, h - cut), (w - cut, h), (0, h), (0, cut)]
    fill = {"normal": theme.RAIL, "hover": theme.RAIL_UP, "on": theme.RAIL_UP}[state]
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.polygon(shape, fill=_rgb(fill) + (255,))
    line = max(1, int(round(2 * scale))) * k
    if state == "on":
        # Pressed in: the keyboard's cyan along its foot, inside.
        draw.rectangle([cut, h - 2 * line, w - cut - 1, h - line - 1], fill=_rgb(theme.CYAN) + (255,))
    if focused:
        draw.line(shape + shape[:1], fill=_rgb(theme.CYAN) + (255,), width=line)
    return img.resize((width, height), Image.LANCZOS)


def field_mark(kind, size, colour, scale=1.0):
    """A mark at a slot's left end (FORMS.md): the sign-in's person and lock, a search's magnifier, drawn in lines of
    1.8 logical pixels in `colour`, `size` logical pixels square. Returns an RGBA picture."""
    k = SS * 2
    px = int(round(size * scale))
    w = px * k
    img = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    line = max(k, int(round(1.8 * scale * k)))
    ink = _rgb(colour) + (255,)
    u = w / 16.0
    if kind == "person":
        # A head over the shoulders' curve.
        draw.ellipse([5.2 * u, 1.8 * u, 10.8 * u, 7.4 * u], outline=ink, width=line)
        draw.arc([2.2 * u, 9.6 * u, 13.8 * u, 21.0 * u], 200, 340, fill=ink, width=line)
    elif kind == "lock":
        # The shackle over the body.
        draw.arc([4.6 * u, 1.6 * u, 11.4 * u, 10.0 * u], 180, 360, fill=ink, width=line)
        draw.line([(4.6 * u, 5.8 * u), (4.6 * u, 7.6 * u)], fill=ink, width=line)
        draw.line([(11.4 * u, 5.8 * u), (11.4 * u, 7.6 * u)], fill=ink, width=line)
        draw.rounded_rectangle([2.8 * u, 7.4 * u, 13.2 * u, 14.6 * u], radius=1.4 * u, outline=ink, width=line)
    elif kind == "search":
        draw.ellipse([2.0 * u, 2.0 * u, 11.0 * u, 11.0 * u], outline=ink, width=line)
        draw.line([(10.0 * u, 10.0 * u), (14.0 * u, 14.0 * u)], fill=ink, width=line)
    return img.resize((px, px), Image.LANCZOS)


# A card's and a section's name, in pixels at 100 %: as large as the body (10 points, 13.33 px) so that a heading is
# never smaller than the words under it, on a plate tall enough to hold its capitals with air above and below.
PLATE_TEXT, PLATE_HEIGHT, PLATE_PAD = 10 * 96 / 72.0, 26, 12


# A card's tab and a section's plate: a few on each page, the same each visit.
@_kept(64)
def name_plate(text, scale=1.0, fill=None, colour=None):
    """A section's name as the game labels a part of its screen (NO CREW on the song select): white words on a dark
    leaning plate, its right end cut on the slant, the words' ink (their capitals, or their Hangul) in the plate's
    middle. Returns an RGBA picture just big enough."""
    hangul = any("가" <= ch <= "힣" for ch in text)
    face = theme.HANGUL_TITLE_FILE if hangul else theme.WIDE_FILE
    size = PLATE_TEXT * scale * (1.1 if hangul else 1.0)
    font = ImageFont.truetype(face, size)
    height = int(round(PLATE_HEIGHT * scale))
    pad = int(round(PLATE_PAD * scale))
    width = int(font.getlength(text)) + 2 * pad + int(height * LEAN)
    img = plain_plate(width, height, fill or theme.INK, top=theme.LINE, cut_left=False)
    # On the baseline that puts the ink band in the middle (ink_band), not the font's ascender over its descender.
    top, bottom = ink_band(face, size, text)
    ImageDraw.Draw(img).text((pad, height / 2.0 - (top + bottom) / 2.0), text, font=font,
                             fill=_rgb(colour or theme.TEXT) + (255,), anchor="ls")
    return img


@functools.lru_cache(maxsize=512)
def ink_band(font_file, size, text):
    """Where `text`'s ink stands from its baseline when set at `size` pixels: (top, bottom), up negative. The band a
    reader takes for the words' height: their Hangul syllables' when they have Hangul, else the face's capitals' (the
    ink of "H": a "g" hanging under the line or an "l" over the capitals does not move what reads as the middle).
    Measured four times larger, for a quarter of a pixel's precision. (A sign with no letter, a window key's × or −,
    is the font's own business: has_letters.)"""
    big = ImageFont.truetype(font_file, max(1.0, size * 4))
    hangul = "".join(ch for ch in text if "가" <= ch <= "힣")
    left, top, right, bottom = big.getbbox(hangul or "H", anchor="ls")
    return top / 4.0, bottom / 4.0


def has_letters(text):
    """Whether `text` has a letter or a figure (whose ink band ink_band measures), not only signs (× −), which Tk may
    draw from another font and centres by their own shape."""
    return any(ch.isalpha() or ch.isdigit() for ch in text or "")


# PLAY's five looks at its size: the guide's last step and the launcher's column share them, and a window made again
# (another language) takes them.
@_kept(12)
def play_button(width, height, state="normal"):
    """The PLAY button as the game sets its chosen mode (TOUCH TO START): a leaning blue slab with light stripes on
    the slant and a bright top rim; flat and dark while it cannot be pressed or the game is open."""
    look = {
        "normal": (theme.BLUE, "#6f9bff", "#1a3fb8"),
        "hover": ("#3a6dff", "#8fb2ff", "#1a3fb8"),
        "pressed": ("#2150d6", "#5b8cff", "#12309a"),
    }
    if state in look:
        return striped_plate(width, height, *look[state])
    return plain_plate(width, height, {"disabled": "#262d37", "playing": "#2c3646"}[state], top=theme.LINE)


# A tick box's looks: ticked or not, by the pointer and the keyboard, in a section's colour.
@_kept(32)
def tick_box(checked, state="normal", scale=1.0, colours=None, focused=False):
    """A tick box (FORMS.md): a 20 px square slot, its edge a step lighter than a field's (it is small), lighter still
    under the pointer; ticked, filled in the section's colour with the tick in its ink; the keyboard's cyan ring two
    pixels out while it has the keyboard; quieter while it cannot be used. The picture has room round the box for the
    ring (RING_ROOM logical pixels each side). Returns an RGBA picture."""
    k = SS
    room = int(round(TICK_RING_ROOM * scale))
    size = int(round(20 * scale))
    total = size + 2 * room
    w = total * k
    img = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    x0, x1 = room * k, (room + size) * k - 1
    e = max(1, int(round(scale))) * k
    colours = colours or theme.SECTION_COLOURS["technika"]
    if state == "disabled":
        draw.rectangle([x0, x0, x1, x1], fill=_rgb(theme.SLOT_OFF) + (255,))
        draw.rectangle([x0, x0, x1, x1], outline=_rgb(theme.SLOT_OFF_EDGE) + (255,), width=e)
        if checked:
            draw.rectangle([x0, x0, x1, x1], fill=_rgb(theme.RAIL_UP) + (255,))
    elif checked:
        draw.rectangle([x0, x0, x1, x1], fill=_rgb(colours["fill"]) + (255,))
    else:
        draw.rectangle([x0, x0, x1, x1], fill=_rgb(theme.FIELD) + (255,))
        draw.rectangle([x0 + e, x0 + e, x1 - e, x0 + 2 * e - 1], fill=_rgb(theme.SLOT_SHADE) + (255,))
        edge = theme.TICK_EDGE_HOVER if state == "hover" else theme.SLOT_EDGE_HOVER
        draw.rectangle([x0, x0, x1, x1], outline=_rgb(edge) + (255,), width=e)
    if checked:
        # The tick: a short stroke down and a long one up (the site's 16 px mark, square ends), in the fill's ink.
        u = size * k / 20.0
        ink = colours["ink"] if state != "disabled" else theme.FAINT
        points = [(x0 + 4.8 * u, x0 + 10.4 * u), (x0 + 8.4 * u, x0 + 14.0 * u), (x0 + 15.6 * u, x0 + 6.2 * u)]
        draw.line(points, fill=_rgb(ink) + (255,), width=max(k, int(round(2.4 * u))))
    if focused:
        ring = max(1, int(round(2 * scale))) * k
        gap = max(1, int(round(2 * scale))) * k
        draw.rectangle([x0 - gap - ring, x0 - gap - ring, x1 + gap + ring, x1 + gap + ring],
                       outline=_rgb(theme.CYAN) + (255,), width=ring)
    return img.resize((total, total), Image.LANCZOS)


# The room a tick box's and a switch's picture keeps round it for the keyboard's ring (logical pixels): 2 of gap and
# 2 of ring.
TICK_RING_ROOM = 4


# A switch's looks: every switch of a page shares them (SCREEN has seven).
@_kept(32)
def switch(on, state="normal", scale=1.0, colours=None, focused=False):
    """A switch (FORMS.md): a 42 by 24 round track (only switches, lamps and badges are round); off, the slot with the
    knob in the ash's grey at its left; on, the track in the section's colour with the knob in its ink at its right;
    the edge lighter under the pointer; the keyboard's cyan ring two pixels out; quieter while it cannot be used. The
    picture keeps TICK_RING_ROOM round the track for the ring. Returns an RGBA picture."""
    k = SS
    room = int(round(TICK_RING_ROOM * scale))
    width, height = int(round(42 * scale)), int(round(24 * scale))
    tw, th = (width + 2 * room) * k, (height + 2 * room) * k
    img = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    x0, y0, x1, y1 = room * k, room * k, (room + width) * k - 1, (room + height) * k - 1
    r = (y1 - y0) / 2.0
    e = max(1, int(round(scale))) * k
    colours = colours or theme.SECTION_COLOURS["technika"]
    if state == "disabled":
        track, edge, knob_colour = theme.SLOT_OFF, theme.SLOT_OFF_EDGE, theme.RAIL_UP
    elif on:
        track, edge, knob_colour = colours["fill"], colours["fill"], colours["ink"]
    else:
        track = theme.FIELD
        edge = theme.TICK_EDGE_HOVER if state == "hover" else theme.SLOT_EDGE_HOVER
        knob_colour = theme.MUTED
    draw.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=_rgb(track) + (255,), outline=_rgb(edge) + (255,), width=e)
    # The knob: 14 px across, its middle 11 px in from the track's end.
    d = 14 * scale * k
    middle_x = (x1 - 11 * scale * k) if on else (x0 + 11 * scale * k)
    middle_y = (y0 + y1) / 2.0
    draw.ellipse([middle_x - d / 2, middle_y - d / 2, middle_x + d / 2, middle_y + d / 2], fill=_rgb(knob_colour) + (255,))
    if focused:
        ring = max(1, int(round(2 * scale))) * k
        gap = max(1, int(round(2 * scale))) * k
        draw.rounded_rectangle([x0 - gap - ring, y0 - gap - ring, x1 + gap + ring, y1 + gap + ring],
                               radius=r + gap + ring, outline=_rgb(theme.CYAN) + (255,), width=ring)
    return img.resize((width + 2 * room, height + 2 * room), Image.LANCZOS)


# A slider's four knobs: every slider shares them (SOUND has nine sliders, each made all four).
@_kept(16)
def slider_knob(scale=1.0, state="normal", focused=False):
    """A slider's knob (FORMS.md): 10 by 22, chalk, standing upright, a pixel of ink round it and a soft shadow under
    it; white under the pointer; the metal while it cannot be used; the keyboard's cyan ring round it. The picture
    keeps 4 logical pixels round the knob for the ring and the shadow. Returns an RGBA picture."""
    k = SS
    room = 4
    w, h = int(round((10 + 2 * room) * scale)), int(round((22 + 2 * room) * scale))
    img = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    x0, y0 = room * scale * k, room * scale * k
    x1, y1 = x0 + 10 * scale * k - 1, y0 + 22 * scale * k - 1
    # The shadow: a pixel down, a little wider, at 60 %.
    draw.rounded_rectangle([x0 - k, y0 + 1 * scale * k, x1 + k, y1 + 2 * scale * k], radius=2 * k,
                           fill=(0, 0, 0, 150))
    face = {"normal": theme.TEXT, "hover": "#ffffff", "disabled": theme.RAIL_UP}[state]
    draw.rounded_rectangle([x0, y0, x1, y1], radius=1 * scale * k, fill=_rgb(face) + (255,),
                           outline=_rgb(theme.INK) + (255,), width=max(k, int(round(scale * k))))
    if focused:
        ring = max(1, int(round(2 * scale))) * k
        draw.rounded_rectangle([x0 - ring, y0 - ring, x1 + ring, y1 + ring], radius=2 * k,
                               outline=_rgb(theme.CYAN) + (255,), width=ring)
    return img.resize((w, h), Image.LANCZOS)


def busy_stripes(width, height, phase, scale=1.0):
    """The game's moving stripes over a key at work (FORMS.md's busy key): white bands 7 px wide every 14 px leaning
    at 60 degrees, at 16 %, shifted `phase` (0 to 1) along one period. Returns an RGBA picture to lay over the key's
    face."""
    k = 2
    w, h = width * k, height * k
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    period = 14 * scale * k
    band = 7 * scale * k
    lean = h * 0.577  # tan(30 degrees): the bands lean at 60 degrees from the key's foot
    shift = phase * period
    x = -lean - period + shift
    while x < w + period:
        draw.polygon([(x, h), (x + band, h), (x + band + lean, 0), (x + lean, 0)], fill=(255, 255, 255, 41))
        x += period
    return img.resize((width, height), Image.LANCZOS)


def busy_frames(face, scale=1.0, count=8):
    """A key at work (FORMS.md's busy key): its own face a little dimmer, with the game's moving stripes over it inside
    its leaning outline, as `count` pictures one period apart, to be shown in turn. `face` is the key's face at rest
    (button_face, margin 0). Returns RGB pictures."""
    w, h = face.size
    shape = _mask((w, h), lambda d, s: d.polygon(lean_outline(0, 0, w * s, h * s), fill=255))
    dim = Image.eval(face.convert("RGB"), lambda v: int(v * 0.92))
    base = face.convert("RGB").copy()
    base.paste(dim, (0, 0), shape)
    frames = []
    for i in range(count):
        stripes = busy_stripes(w, h, i / float(count), scale)
        alpha = Image.composite(stripes.getchannel("A"), Image.new("L", (w, h), 0), shape)
        frame = base.copy()
        frame.paste(Image.new("RGB", (w, h), (255, 255, 255)), (0, 0), alpha)
        frames.append(frame)
    return frames


# An unlit lamp: quiet metal, dark at its top and a step lighter at its foot.
QUIET = ("#1c2127", "#3a434e")


# A lamp by its colour, its state and its size: each check line has one, the status line one.
@_kept(32)
def lamp(colour, lit=True, scale=1.0, size=(13, 10)):
    """A small leaning light beside a line, as the cabinet's lamps are: lit, its body dark at the top and lit from below
    to its colour, a pixel of light along its top edge and nothing round it; "quiet", unlit metal (a state with nothing
    to say); False, an outline in its colour (what PLAY will change). It says how a check stands (fine, will change,
    problem) and which row of a list is the chosen one; a smaller one (`size`, logical pixels) before a field's error.
    Returns an RGBA picture."""
    width, height = int(round(size[0] * scale)), int(round(size[1] * scale))
    w, h = width * SS, height * SS
    shape = Image.new("L", (w, h), 0)
    ImageDraw.Draw(shape).polygon(lean_outline(0, 0, w - 1, h - 1), fill=255)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if lit is False:
        # An outline: a line of even width along the shape, its middle empty.
        line = 1.6 * scale * SS
        ring = Image.new("L", (w, h), 0)
        ImageDraw.Draw(ring).polygon(lean_outline(0, 0, w - 1, h - 1), fill=255)
        ImageDraw.Draw(ring).polygon(lean_outline(0, 0, w - 1, h - 1, grow=-line), fill=0)
        img.paste(_rgb(colour) + (255,), (0, 0), ring)
        return img.resize((width, height), Image.LANCZOS)
    if lit == "quiet":
        top, foot = QUIET
    else:
        # Lit from below: the colour at its foot, the same colour with most of its light gone at its top.
        top, foot = "#%02x%02x%02x" % _mixed(colour, "#000000", 0.58), colour
    img.paste(_gradient((w, h), top, foot).convert("RGBA"), (0, 0), shape)
    if lit != "quiet":
        # A pixel of light along its top edge, inside the shape, as the cabinet's lamps have their light rim.
        edge = Image.new("L", (w, h), 0)
        ImageDraw.Draw(edge).rectangle([0, 0, w, SS - 1], fill=120)
        img.paste((255, 255, 255, 255), (0, 0), ImageChops.darker(edge, shape))
    return img.resize((width, height), Image.LANCZOS)


# The cabinet's two lamps, lit or not.
@_kept(8)
def lamp_chip(word, kind, lit=True, scale=1.0):
    """The cabinet's status lamp with its word (ID CARD, NET at the game's foot): a small plate rounded as the game's
    lamps are, its word in capitals in the wide face. Lit: its body dark at the top and lit from below
    (theme.CHIPS[kind]), a light rim, white words (5.2:1 and more over the body); off: black glass, a grey rim, grey
    words. Nothing round it. Returns an RGBA picture just big enough."""
    font = ImageFont.truetype(theme.WIDE_FILE, max(6, int(round(8.5 * scale * SS))))
    pad = int(round(8 * scale))
    w = int(round(font.getlength(word) / SS)) + 2 * pad
    h = int(round(18 * scale))
    big = (w * SS, h * SS)
    shape = Image.new("L", big, 0)
    radius = 3 * scale * SS
    ImageDraw.Draw(shape).rounded_rectangle([0, 0, big[0] - 1, big[1] - 1], radius=radius, fill=255)
    ring = Image.new("L", big, 0)
    ImageDraw.Draw(ring).rounded_rectangle([0, 0, big[0] - 1, big[1] - 1], radius=radius, outline=255,
                                           width=max(SS, int(round(1.2 * scale * SS))))
    img = Image.new("RGBA", big, (0, 0, 0, 0))
    if lit:
        top, foot = theme.CHIPS[kind]
        img.paste(_gradient(big, top, foot).convert("RGBA"), (0, 0), shape)
        rim, ink = (238, 244, 246), (255, 255, 255)
    else:
        img.paste(_rgb(theme.CHIP_OFF) + (255,), (0, 0), shape)
        rim, ink = _rgb(theme.CHIP_OFF_RIM), _rgb(theme.CHIP_OFF_INK)
    img.paste(rim + (int(255 * 0.85) if lit else 255,), (0, 0), ring)
    words = Image.new("L", big, 0)
    ImageDraw.Draw(words).text((big[0] / 2, big[1] / 2 + 0.5 * scale * SS), word, font=font, fill=255, anchor="mm")
    img.paste(ink + (255,), (0, 0), words)
    return img.resize((w, h), Image.LANCZOS)


def level_gem(tier, scale=1.0, size=12):
    """The DJ level's tier as the game's level badges show it: a gem in four facets, the top-left lit, the bottom-right
    in shade, the other two in the tier's colour (theme.LEVEL_TIERS, a tier every ten levels; "master" at 99).
    Returns an RGBA picture."""
    colour = theme.LEVEL_MASTER if tier == "master" else theme.LEVEL_TIERS[max(0, min(len(theme.LEVEL_TIERS) - 1, tier))]
    s = max(4, int(round(size * scale)))
    big = s * SS
    c = big / 2.0
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    lit, shade, body = _mixed(colour, "#ffffff", 0.45), _mixed(colour, "#000000", 0.45), _rgb(colour)
    top, right, bottom, left, mid = (c, 0), (big, c), (c, big), (0, c), (c, c)
    draw.polygon([top, mid, left], fill=lit + (255,))
    draw.polygon([top, right, mid], fill=body + (255,))
    draw.polygon([left, mid, bottom], fill=body + (255,))
    draw.polygon([mid, right, bottom], fill=shade + (255,))
    return img.resize((s, s), Image.LANCZOS)


# A row of choices in each look it shows (its choice, the pointer, the keyboard) and in the room it has (`room` is part
# of what it is kept by): each visit drew them again.
@_kept(48)
def choice_row(texts, chosen, hover, colours, scale=1.0, focused=None, enabled=True, room=None):
    """A row of 2 to 4 choices of which one is on (FORMS.md's segmented keys): the game's leaning keys side by side, 2
    px apart, 34 px tall, the metal with words in the ash's grey, the metal's lighter shade with chalk words under the
    pointer, the chosen one filled in the section's colour with its ink; the keyboard's cyan two pixels inside the key
    it is on (`focused`); quieter while it cannot be used.

    texts: the words; chosen, hover, focused: indexes (hover and focused may be None); room: the width it has, when
    known: a row wider than that takes its keys' side room in, down to 8 px, so that every choice is seen (SCREEN's
    five upscale filters at the window's smallest size). Returns (an RGBA picture, each choice's left and right edge in
    it at half its height, for telling which one a click is on).
    """
    font = ImageFont.truetype(theme.TEXT_BOLD_FILE, int(round(13.33 * scale)))
    height = int(round(34 * scale))
    pad, gap = int(round(18 * scale)), int(round(2 * scale))
    lean = int(height * LEAN)

    def across(side):
        return sum(int(font.getlength(text)) + 2 * side + lean - lean + gap for text in texts) - gap + lean

    least = int(round(8 * scale))
    while room and pad > least and across(pad) > room:
        pad -= 1
    widths = [int(font.getlength(text)) + 2 * pad + lean for text in texts]
    # Each key starts where the one before ends less the lean: their slanted ends run side by side, a gap apart.
    total = sum(w - lean + gap for w in widths) - gap + lean
    img = Image.new("RGBA", (total, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    x, edges = 0, []
    for i, (text, w) in enumerate(zip(texts, widths)):
        if not enabled:
            fill, colour = (theme.RAIL_UP if i == chosen else theme.SLOT_OFF), theme.FAINT
        elif i == chosen:
            fill, colour = colours["fill"], colours["ink"]
        elif i == hover:
            fill, colour = theme.RAIL_UP, theme.TEXT
        else:
            fill, colour = theme.RAIL, theme.MUTED
        plate = plain_plate(w, height, fill)
        if i == focused and enabled:
            # The keyboard's ring, two pixels inside the key's own outline.
            ring = Image.new("RGBA", (w * SS, height * SS), (0, 0, 0, 0))
            points = lean_outline(0, 0, w * SS - 1, height * SS - 1, grow=-3 * scale * SS)
            ImageDraw.Draw(ring).line(points + points[:2], fill=_rgb(theme.CYAN) + (255,),
                                      width=max(SS, int(round(2 * scale * SS))))
            plate.alpha_composite(ring.resize((w, height), Image.LANCZOS))
        img.alpha_composite(plate, (x, 0))
        draw.text((x + w / 2, height / 2), text, font=font, fill=_rgb(colour) + (255,), anchor="mm")
        edges.append((x + lean // 2, x + w - lean // 2))
        x += w - lean + gap
    # The edges as a tuple: the row is kept (_kept), and what is kept is never changed by a caller.
    return img, tuple(edges)


# ------------------------------------------------------------------------------------------------ dialogs
#
# A dialog is drawn as opaque pictures only: the dimmed window behind it, the panel over that window's own pixels,
# and each button over the panel's own pixels. Tk then never has to blend a half-transparent picture, which it
# does differently on each platform.


def lean_outline(x, y, width, height, grow=0.0):
    """The outline of a leaning plate in the box (x, y, width, height): the game's parallelogram, its two ends on
    one slope. `grow` moves every side out by that many pixels (in, for a negative number): a focus ring follows a
    button at the same distance all round, which on the leaning sides takes a little more sideways."""
    lean = LEAN * height
    side = grow * (1 + LEAN * LEAN) ** 0.5
    top, foot = y - grow, y + height + grow
    return [(x + lean + LEAN * grow - side, top), (x + width + LEAN * grow + side, top),
            (x + width - lean - LEAN * grow + side, foot), (x - LEAN * grow - side, foot)]


def _gradient(size, top, bottom):
    """An opaque picture fading from one colour at the top to another at the bottom."""
    grad = Image.linear_gradient("L").resize(size)
    return Image.composite(Image.new("RGB", size, _rgb(bottom)), Image.new("RGB", size, _rgb(top)), grad)


def _mask(size, draw_shape):
    """A smooth-edged mask: the shape drawn SS times larger, then scaled down to `size`."""
    big = Image.new("L", (size[0] * SS, size[1] * SS), 0)
    draw_shape(ImageDraw.Draw(big), SS)
    return big.resize(size, Image.LANCZOS)


def _soft(window, radius):
    """The window out of focus. Blurred at half size, then scaled back: the same look for a quarter of the work."""
    w, h = window.size
    small = window.resize((max(1, w // 2), max(1, h // 2)), Image.BILINEAR)
    return small.filter(ImageFilter.GaussianBlur(max(1, radius / 2))).resize((w, h), Image.BILINEAR)


def dialog_scene(window, box, scale):
    """What shows behind a dialog: the window blurred and dimmed like the game's screen behind its popups, with
    the panel's shadow under it.

    `window` is the window as a picture (snapshot.py) and `box` the panel's (x, y, width, height) in it. Returns
    the scene and the blurred window before dimming, which the panel's glass is made from.
    """
    w, h = window.size
    soft = _soft(window, 9 * scale)
    scene = Image.blend(soft, Image.new("RGB", (w, h), _rgb(theme.BG)), 0.58)
    x, y, bw, bh = box
    # The shadow is only blurred near the panel: a blur over the whole window would cost much more.
    reach = int(40 * scale)
    area = (max(0, x - reach), max(0, y - reach), min(w, x + bw + reach), min(h, y + bh + reach + int(12 * scale)))
    size = (area[2] - area[0], area[3] - area[1])
    mask = Image.new("L", size, 0)
    # It falls a little below the panel, as from a light above, the panel's cut corner cut in it too.
    left, top = x - area[0], y - area[1] + int(12 * scale)
    cut = panel_cut(scale)
    ImageDraw.Draw(mask).polygon([(left, top), (left + bw - cut, top), (left + bw, top + cut), (left + bw, top + bh),
                                  (left, top + bh)], fill=int(255 * 0.72))
    mask = mask.filter(ImageFilter.GaussianBlur(20 * scale))
    region = scene.crop(area)
    region.paste(Image.new("RGB", size, (0, 0, 0)), (0, 0), mask)
    scene.paste(region, area[:2])
    return scene, soft


def panel_cut(scale):
    """A dialog panel's cut top-right corner, in pixels: the cards' 14 logical pixels (widgets.Card.CUT)."""
    return max(2, int(round(14 * scale)))


def dialog_panel(soft, box, tab, scale, scene=None):
    """The panel: gunmetal glass over the blurred window with a sheen at its head and a light rim along its top,
    and the title tab hanging from the top edge as on the game's popups; its top-right corner cut as the cards' are
    (cut_masks), what lies behind the panel showing past the cut (`scene`, the picture under it).

    tab: (width, height, slant, top colour, bottom colour) in the panel's own pixels. Returns an opaque picture of
    the box.
    """
    x, y, bw, bh = box
    # Glass: the blurred window through gunmetal, as OpenDMTQ's panels (86 %), brighter at its head.
    panel = Image.blend(soft.crop((x, y, x + bw, y + bh)), Image.new("RGB", (bw, bh), _rgb(theme.PANEL)), 0.86)
    reach = max(1, int(240 * scale))
    sheen = Image.linear_gradient("L").resize((1, reach)).point(lambda v: int(14 * (1 - v / 255.0) ** 1.6))
    panel.paste(Image.new("RGB", (bw, min(reach, bh)), (255, 255, 255)), (0, 0), sheen.resize((bw, reach)).crop(
        (0, 0, bw, min(reach, bh))))
    # The game's popups' light from the top-left corner, in the dialog's own colour (its tab's top), gone by 38 % of the
    # way across: drawn small and stretched, a diagonal ramp costs nothing.
    ramp = Image.new("L", (64, 64), 0)
    ramp.putdata([int(255 * 0.22 * max(0.0, 1 - (x + y) / (2 * 64 * 0.38))) for y in range(64) for x in range(64)])
    panel.paste(_rgb(tab[3]), (0, 0), ramp.resize((bw, bh), Image.BILINEAR))
    # The edge: one pixel of seam, lit along the top like polished metal, going on along the cut corner's diagonal.
    cut = min(panel_cut(scale), bw, bh)
    beyond, seam = cut_masks(cut)
    edge = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(edge).rectangle([0, 0, bw - 1, bh - 1], outline=255)
    edge.paste(seam, (bw - cut, 0))
    panel.paste(_gradient((bw, bh), "#626d7c", theme.LINE), (0, 0), edge)
    # Past the cut, what is behind the panel (the scene at the panel's place), or the window's colour.
    behind = scene.crop((x + bw - cut, y, x + bw, y + cut)) if scene is not None else \
        Image.new("RGB", (cut, cut), _rgb(theme.BG))
    panel.paste(behind, (bw - cut, 0), beyond)
    # The tab: wider at the panel's edge, narrowing downwards, in the dialog's colour.
    tw, th, slant, top, bottom = tab
    tx = (bw - tw) // 2
    tab_shape = _mask((bw, bh), lambda d, s: d.polygon(
        [(tx * s, 0), ((tx + tw) * s, 0), ((tx + tw - slant) * s, th * s), ((tx + slant) * s, th * s)], fill=255))
    filled = Image.new("RGB", (bw, bh))
    filled.paste(_gradient((tw, th), top, bottom), (tx, 0))
    panel.paste(filled, (0, 0), tab_shape)
    shine = _mask((bw, bh), lambda d, s: d.line([((tx + 2) * s, s), ((tx + tw - 2) * s, s)], fill=130, width=s))
    panel.paste(Image.new("RGB", (bw, bh), (255, 255, 255)), (0, 0), shine)
    return panel


# A button's colours for each look: (top, bottom) of its fill, its edge (None for none), and its words.
BUTTON_LOOKS = {
    "neutral": {"normal": (theme.RAIL_UP, theme.RAIL), "hover": ("#4a5461", "#3a434e"),
                "pressed": (theme.RAIL, "#232931"), "disabled": ("#20262e", "#1c2128"),
                "edge": ("#5a6573", theme.LINE), "text": theme.TEXT},
    "danger": {"normal": ("#ff6bb0", theme.PINK), "hover": ("#ff8cc2", "#ff63aa"), "pressed": (theme.PINK, "#d93684"),
               "disabled": ("#20262e", "#1c2128"), "edge": None, "text": theme.INK},
    "warn": {"normal": ("#ffc55e", theme.AMBER), "hover": ("#ffd27d", "#ffbf57"), "pressed": (theme.AMBER, "#d9962c"),
             "disabled": ("#20262e", "#1c2128"), "edge": None, "text": theme.INK},
    "star": {"normal": ("#c6f553", theme.LIME), "hover": ("#d3f875", "#c0f348"), "pressed": (theme.LIME, "#97cc1d"),
             "disabled": ("#20262e", "#1c2128"), "edge": None, "text": theme.INK},
    "info": {"normal": ("#3d6ff5", theme.BLUE), "hover": ("#4a78f6", "#2d61f0"), "pressed": (theme.BLUE, "#1d47c4"),
             "disabled": ("#20262e", "#1c2128"), "edge": None, "text": "#ffffff"},
    # Removing or putting back: metal with a pink tint and pink words, filled pink under the pointer.
    "danger_quiet": {"normal": ("#5a3a52", "#4b3044"), "hover": ("#ff6bb0", theme.PINK),
                     "pressed": (theme.PINK, "#d93684"), "disabled": ("#20262e", "#1c2128"),
                     "edge": ("#7a4d6c", "#4b3044"), "text": "#ffb8d9", "hover_text": theme.INK},
}
# The section a page belongs to gives its main buttons their look: the settings' lime (THEME.md: STAR's colour for
# the settings' keys), elsewhere openDMT3's blue. Never the pink of what failed or the amber of something to look at
# (ONLINE's Connect and Sign in were pink, LAUNCHER's update amber: the final review's colour rule).
SECTION_LOOKS = {"technika": "info", "star": "star", "pop": "info", "console": "info"}


# A button's faces (four for each button, four more once it has the keyboard): the faces of a page's buttons are
# the same each visit, and buttons with the same words share them. A dialog's, drawn over its panel, are not kept.
@_kept(128)
def button_face(size, margin, look, state, focused, scale, under=None, bg=None):
    """A button's picture, leaning like PLAY and every plate of the game: quiet metal, or a fill in a section's
    colour.

    `under` is what lies beneath (a dialog's panel pixels) or `bg` a plain colour; `margin` pixels on every side
    hold the focus ring when the button has the keyboard.
    """
    colours = BUTTON_LOOKS[look]
    w, h = size
    img = under.copy() if under is not None else Image.new("RGB", size, _rgb(bg or theme.BG))
    bw, bh = w - 2 * margin, h - 2 * margin
    shape = _mask((w, h), lambda d, s: d.polygon(lean_outline(margin * s, margin * s, bw * s, bh * s), fill=255))
    filled = Image.new("RGB", (w, h))
    filled.paste(_gradient((bw, bh), *colours[state]), (margin, margin))
    img.paste(filled, (0, 0), shape)
    if colours["edge"] and state != "disabled":
        # One pixel of edge all round, lighter at the top.
        def outline(d, s):
            points = lean_outline(margin * s, margin * s, bw * s - s, bh * s - s)
            d.line(points + points[:1], fill=200, width=s)
        edged = Image.new("RGB", (w, h))
        edged.paste(_gradient((bw, bh), *colours["edge"]), (margin, margin))
        img.paste(edged, (0, 0), _mask((w, h), outline))
    elif state != "disabled":
        # A bright line along the top, the game's chrome highlight (as on PLAY).
        shine = _mask((w, h), lambda d, s: d.line([((margin + LEAN * bh) * s, (margin + 1) * s),
                                                   ((margin + bw - 2) * s, (margin + 1) * s)], fill=110, width=s))
        img.paste(Image.new("RGB", (w, h), (255, 255, 255)), (0, 0), shine)
    if focused:
        # The keyboard's ring follows the button's own outline in the focus colour: a little outside it when the
        # picture has room around the button (a dialog's), else just inside its edge (a page's, drawn edge to edge).
        gap = max(2, int(round(3 * scale)))
        width = max(2, int(round(2 * scale)))
        grow = gap if margin >= gap else -(width // 2 + 1)

        def ring(d, s):
            points = lean_outline(margin * s, margin * s, bw * s - s, bh * s - s, grow * s)
            d.line(points + points[:2], fill=255, width=width * s)
        img.paste(Image.new("RGB", (w, h), _rgb(theme.CYAN)), (0, 0), _mask((w, h), ring))
    return img


def mark(size):
    """The openDMT3 mark: a slanted blue shard with a lime edge, for the program's icon."""
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Two shards leaning like the title screen's, the front one blue and the back one lime.
    draw.polygon([(s * 0.30, s * 0.05), (s * 0.95, s * 0.05), (s * 0.70, s * 0.95), (s * 0.05, s * 0.95)],
                 fill=_rgb("#2f6bff") + (255,))
    draw.polygon([(s * 0.78, s * 0.05), (s * 0.95, s * 0.05), (s * 0.70, s * 0.95), (s * 0.53, s * 0.95)],
                 fill=_rgb(theme.LIME) + (255,))
    return img.resize((size, size), Image.LANCZOS)


# The member's platinum card (CARDS.md, "member"): the sites' .djcard in the launcher, as a picture. Its stops are the
# sites' platinum, toned to a mid platinum so that it does not glare on the dark page (a band of shade across its
# middle, as brushed metal holds the light), its rim the sites' platinum rim.
PLATINUM_STOPS = ((0.0, "#d9dfe3"), (0.46, "#c5ccd2"), (0.50, "#b3bbc2"), (0.72, "#c1c8ce"), (1.0, "#cfd5da"))
# A card's proportions (ISO/IEC 7810 ID-1, 85.60 by 53.98 mm: 1.586 to 1) at the launcher's modest size, and the
# rounding of its corners (logical pixels).
MEMBER_CARD, MEMBER_ROUND = (176, 111), 9


def _platinum(w, h):
    """The platinum's face, `w` by `h` pixels: its stops from top to foot, the game's perforation faint in it."""
    face = Image.new("RGB", (1, h))
    stops = [(int(at * (h - 1)), _rgb(colour)) for at, colour in PLATINUM_STOPS]
    for y in range(h):
        # Between the two stops round this line, in proportion.
        for (y0, c0), (y1, c1) in zip(stops, stops[1:]):
            if y0 <= y <= y1:
                t = (y - y0) / float(max(1, y1 - y0))
                face.putpixel((0, y), tuple(int(round(a + (b - a) * t)) for a, b in zip(c0, c1)))
                break
    return face.resize((w, h))


@_kept(16)
def member_card(name, login_id, scale=1.0):
    """The one who plays as the Platinum Crew member's card (the sites' DJ card): a platinum card of a card's
    proportions, rounded as one piece (the one rounded thing: an object held in the hand), a thin metal rim and a
    white light along its top just inside it, the game's perforation faint in the metal, the DJ name in heavy dark ink
    at its foot and the ID under it in the second ink. No crest, no logo. Returns an RGBA picture."""
    width, height = int(round(MEMBER_CARD[0] * scale)), int(round(MEMBER_CARD[1] * scale))
    # Drawn SS times larger and brought down, for smooth arcs and words.
    w, h = width * SS, height * SS
    radius = int(round(MEMBER_ROUND * scale * SS))
    face = _platinum(w, h)
    # The perforation: two offset lattices of faint dots every 8 logical pixels (the game's member card's surface).
    dots = ImageDraw.Draw(face)
    step, r = 8 * scale * SS, 0.85 * scale * SS
    y, row = 2 * scale * SS, 0
    while y < h:
        x = (2 if row % 2 == 0 else 6) * scale * SS
        while x < w:
            dots.ellipse([x - r, y - r, x + r, y + r], fill=(176, 184, 191))
            x += step
        y += step / 2.0
        row += 1
    # The card's shape: rounded at all four corners.
    shape = Image.new("L", (w, h), 0)
    ImageDraw.Draw(shape).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    img.paste(face, (0, 0), shape)
    draw = ImageDraw.Draw(img)
    # The rim round it, and the white light along its top just inside the rim.
    line = max(1, int(round(scale))) * SS
    draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, outline=_rgb(theme.PLATINUM_RIM), width=line)
    draw.line([(radius, line), (w - radius, line)], fill=(255, 255, 255), width=line)
    # The words, in the type's steps: the DJ name in heavy ink (13 points), the ID under it (9 points).
    pad = 12 * scale * SS
    big = ImageFont.truetype(theme.HANGUL_TITLE_FILE, 13 * 96 / 72.0 * scale * SS)
    small = ImageFont.truetype(theme.TEXT_BOLD_FILE, 9 * 96 / 72.0 * scale * SS)
    draw.text((pad, h - pad - 15 * scale * SS), name, font=big, fill=_rgb(theme.PLATINUM_INK), anchor="ls")
    draw.text((pad, h - pad), login_id, font=small, fill=_rgb(theme.PLATINUM_INK_2), anchor="ls")
    return img.resize((width, height), Image.LANCZOS)


@_kept(8)
def member_plate(name, scale=1.0):
    """The signed-in player's small platinum nameplate (a page's lead, CARDS.md): the member card's metal and rim,
    rounded, the DJ name in its dark ink in the body's size. Returns an RGBA picture."""
    font_px = 10 * 96 / 72.0 * scale
    height = int(round(22 * scale))
    probe = ImageFont.truetype(theme.TEXT_BOLD_FILE, font_px)
    width = int(round(probe.getlength(name) + 2 * 10 * scale))
    w, h = width * SS, height * SS
    face = _platinum(w, h)
    shape = Image.new("L", (w, h), 0)
    radius = int(round(5 * scale * SS))
    ImageDraw.Draw(shape).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    img.paste(face, (0, 0), shape)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, outline=_rgb(theme.PLATINUM_RIM),
                           width=max(1, int(round(scale))) * SS)
    # The name's ink band in the plate's middle (ink_band), as every word on a key or a tab stands.
    font = ImageFont.truetype(theme.TEXT_BOLD_FILE, font_px * SS)
    top, bottom = ink_band(theme.TEXT_BOLD_FILE, font_px * SS, name)
    draw.text((10 * scale * SS, h / 2.0 - (top + bottom) / 2.0), name, font=font, fill=_rgb(theme.PLATINUM_INK),
              anchor="ls")
    return img.resize((width, height), Image.LANCZOS)


@_kept(8)
def corner_foot(size, inside, outside, seam):
    """The result panel's second cut, at its foot's left (the game's result frames are cut at two opposite corners):
    the top-right corner's picture turned half round, its seam along the cut."""
    return corner(size, inside, outside, seam=seam).rotate(180)


@_kept(8)
def member_slot(words, scale=1.0):
    """Where the member's card stands when no card goes in (a guest, offline, before a sign-in): the card's place,
    sunken into the plate (a well's dark, the shade along its top inside and the light caught at its foot), rounded as
    the card, the game's words for it (NO ID CARD) in the tab's face and the hints' grey where a DJ name would be.
    Returns an RGBA picture as large as the card."""
    width, height = int(round(MEMBER_CARD[0] * scale)), int(round(MEMBER_CARD[1] * scale))
    w, h = width * SS, height * SS
    radius = int(round(MEMBER_ROUND * scale * SS))
    line = max(1, int(round(scale))) * SS
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=_rgb(theme.WELL), outline=_rgb(theme.SEAM),
                           width=line)
    # Sunken: the shade along its top inside, the light caught along its foot inside.
    draw.line([(radius, 2 * line), (w - radius, 2 * line)], fill=_rgb(theme.WELL_SHADE), width=line)
    draw.line([(radius, h - 1 - 2 * line), (w - radius, h - 1 - 2 * line)], fill=_rgb(theme.WELL_LIGHT), width=line)
    font = ImageFont.truetype(theme.WIDE_FILE, PLATE_TEXT * scale * SS)
    pad = 12 * scale * SS
    draw.text((pad, h - pad), words, font=font, fill=_rgb(theme.MUTED), anchor="ls")
    return img.resize((width, height), Image.LANCZOS)
