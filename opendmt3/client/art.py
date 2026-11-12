"""Pictures the launcher draws for itself, in the style of TECHNIKA 3's screens.

Everything here is drawn in code (no game art ships with openDMT3). When the player's game folder is known, the
header also shows a few song discs read from the player's own archives at run time; they are never saved.
Shapes are drawn three times larger and scaled down, because Tk's own canvas does not smooth diagonal edges.
"""

import collections
import io
import random
import threading
import time

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from opendmt3.client import theme

# Draw at this many times the final size, then scale down: smooth edges without a drawing library.
SS = 3
# A header's shards by what they are drawn from (the header's size in pixels, which carries the scaling, the page's
# arrangement and its colours): a page shown again takes them from here. They are most of a header's drawing (22 of
# 26 ms at 100 % scaling, 70 of 75 ms at 200 %), and were drawn again at every page switch. One per page of a window
# size is kept (the launcher's nine pages, the guide's five steps); a resize leaves the old size's to go first.
_HEADER_SHARDS = collections.OrderedDict()
HEADER_SHARDS_KEPT = 10
_header_shards_lock = threading.Lock()

# Chrome, top to bottom: bright, a dark band where the horizon reflects, bright again (the TECHNIKA 3 logo's face).
CHROME = ((0.0, "#ffffff"), (0.44, "#e3e8ee"), (0.53, "#727c88"), (0.72, "#b6bec7"), (1.0, "#f3f5f8"))


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


def shards(width, height, seed=7, density=1.0, colours=None):
    """The page behind its title: gunmetal with shards cutting in from the right, like the title screen's. The
    shards take the section's colour (the title screen's blue unless told otherwise)."""
    colours = colours or theme.SECTION_COLOURS["technika"]
    w, h = width * SS, height * SS
    rng = random.Random(seed)
    img = Image.new("RGB", (w, h), _rgb(theme.BG))
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    bright, deep = _rgb(colours["light"]), _rgb(colours["deep"])
    # Large dark planes first, then bright splinters over them, all leaning the same way.
    for i in range(int(16 * density)):
        splinter = i >= 6
        # Shards start on the right two thirds so the title on the left stays on dark metal.
        x = rng.uniform(0.38, 1.08) * w
        y = rng.uniform(-0.3, 1.1) * h
        length = rng.uniform(0.45, 1.3) * h * (1.3 if not splinter else 1.0)
        spread = rng.uniform(0.05, 0.20) * w
        # A long thin triangle: one sharp tip, one short base edge, like broken glass.
        points = [(x, y), (x + spread, y - length * 0.30), (x - spread * rng.uniform(0.3, 1.0), y + length)]
        # Splinters half seen through, so the section's colour lights the page without shouting over the title.
        alpha = rng.randint(115, 165) if splinter else rng.randint(120, 190)
        draw.polygon(points, fill=(bright if splinter else deep) + (alpha,))
    img.paste(layer, (0, 0), layer)
    img = img.resize((width, height), Image.LANCZOS)
    # A soft fade from the left, so the title reads on plain metal.
    fade = Image.linear_gradient("L").rotate(90, expand=True).resize((width, height))
    plain = Image.new("RGB", (width, height), _rgb(theme.BG))
    return Image.composite(img, plain, fade.point(lambda v: min(255, int(v * 1.6))))


def header_shards(width, height, seed, colours):
    """shards() for a page header, kept (_HEADER_SHARDS): the same picture for the same size, arrangement and colours.
    Callers never change the picture they get (header() draws on a copy of it)."""
    key = (width, height, seed, tuple(sorted(colours.items())))
    with _header_shards_lock:
        kept = _HEADER_SHARDS.get(key)
        if kept is not None:
            # Used again: the last to go.
            _HEADER_SHARDS.move_to_end(key)
            return kept
    picture = shards(width, height, seed=seed, colours=colours)
    with _header_shards_lock:
        _HEADER_SHARDS[key] = picture
        while len(_HEADER_SHARDS) > HEADER_SHARDS_KEPT:
            # The least recently shown go first (another window size's, after a resize).
            _HEADER_SHARDS.popitem(last=False)
    return picture


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


def header(width, height, discs=(), seed=7, colours=None, title=None, title_tail=None, scale=1.0,
           title_at=(32, 98)):
    """The page header: shards in the section's colour, the discs along the right edge, and the page's title in
    chrome (its tail, such as the 3 of TECHNIKA 3, in the section's colour).

    title_at is the title's left edge and baseline in logical pixels.
    """
    colours = colours or theme.SECTION_COLOURS["technika"]
    # The shards kept for this size and page (drawn the first time), copied to draw the rest over (convert copies).
    img = header_shards(width, height, seed, colours).convert("RGBA")
    if discs:
        # The discs are as tall as most of the header and overlap like a row of records.
        size = int(height * 0.78)
        step = int(size * 0.62)
        x = width - size - int(height * 0.18)
        y = (height - size) // 2
        for disc in discs:
            d = disc.resize((size, size), Image.LANCZOS)
            # A blurred dark copy under each disc lifts it off the background.
            shadow = Image.new("RGBA", d.size, (0, 0, 0, 0))
            shadow.putalpha(d.getchannel("A").point(lambda a: a * 0.75))
            shadow = shadow.filter(ImageFilter.GaussianBlur(max(2, size // 22)))
            img.alpha_composite(shadow, (x + size // 30, y + size // 24))
            img.alpha_composite(d, (x, y))
            x -= step
            if x < width * 0.45:
                # Never under the title on the left.
                break
        # Darken the discs a little towards the left so the title keeps the contrast.
        fade = Image.linear_gradient("L").rotate(90, expand=True).resize((width, height))
        shade = Image.new("RGBA", (width, height), _rgb(theme.BG) + (0,))
        shade.putalpha(fade.point(lambda v: int((255 - v) * 0.55)))
        img.alpha_composite(shade)
    if title:
        parts = [(title, CHROME)]
        if title_tail and title.endswith(title_tail):
            parts = [(title[:-len(title_tail)], CHROME), (title_tail, lit_chrome(colours["accent"]))]
        words, baseline = chrome_text(parts, int(round(34 * scale)), scale)
        pad = int(6 * scale) + max(1, int(round(1.4 * scale)))
        img.alpha_composite(words, (int(title_at[0] * scale) - pad, int(title_at[1] * scale) - baseline))
    return img.convert("RGB")


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
    # DMT3 as large as the width allows beside its label.
    size = int(round(44 * scale))
    while size > 12:
        big, baseline = chrome_text([("DMT", CHROME), ("3", lit_chrome(accent))], size, scale)
        if big.width + label_w <= width:
            break
        size -= 1
    pad = int(6 * scale) + max(1, int(round(1.4 * scale)))   # chrome_text's room around its letters
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
    beside = width - big.width - int(3 * scale) - 1
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
    # on the slant of the game's plates; grey turning into the accent.
    left, right = x - 0.2 * o_size + 0.86 * o_cap, width - 1
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
    draw.text((big.width + int(3 * scale), foot_y), label, font=tiny, fill=_rgb(accent) + (255,), anchor="ls")
    if shown and not below:
        # Over the label, a line apart, in the text colour (readable at a glance, unlike the faint footers).
        draw.text((big.width + int(3 * scale), foot_y - int(round(13 * scale))), shown, font=vfont,
                  fill=_rgb(theme.TEXT) + (255,), anchor="ls")
    elif shown:
        # Too long to stand beside DMT3: under the mark, lined up with OPEN.
        draw.text((pad, height - int(round(4 * scale))), shown, font=vfont, fill=_rgb(theme.TEXT) + (255,),
                  anchor="ls")
    return img


# How far a leaning edge runs sideways for each pixel of its height: one slope for every plate, tab and button.
LEAN = 0.36


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
    """A leaning slab of one colour (a hovered menu entry, a section's name plate), with a faint light top edge."""
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


def menu_entry(text, width, height, state, colours, scale=1.0):
    """One entry of the menu column as the game's mode select sets its choices: the chosen one ("on") on a striped
    plate in its section's colour with dark (or, on blue, white) words, a hovered one on a dark plate, the rest in
    grey words on the column; "done" (a step of the guide already taken) in white words. Latin in the wide face's
    capitals, Hangul in Pretendard Bold."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    if state == "on":
        plate = striped_plate(width, height, colours["fill"], colours["accent"], colours["deep"])
        img.alpha_composite(plate)
        colour = colours["ink"]
    elif state == "hover":
        img.alpha_composite(plain_plate(width, height, theme.PANEL_HI, top=theme.LINE))
        colour = theme.TEXT
    else:
        colour = theme.TEXT if state == "done" else theme.MUTED
    hangul = any("가" <= ch <= "힣" for ch in text)
    size = int(round((14 if hangul else 12.5) * scale))
    font = ImageFont.truetype(theme.HANGUL_TITLE_FILE if hangul else theme.WIDE_FILE, size)
    # The words from where the plate's leaning edge leaves room, centred on the plate's height.
    x = int(height * LEAN) + int(12 * scale)
    while font.getlength(text) > width - x - int(8 * scale) and size > 8:
        size -= 1
        font = ImageFont.truetype(theme.HANGUL_TITLE_FILE if hangul else theme.WIDE_FILE, size)
    ImageDraw.Draw(img).text((x, height / 2), text, font=font, fill=_rgb(colour) + (255,), anchor="lm")
    return img


def name_plate(text, scale=1.0, fill=None, colour=None):
    """A section's name as the game labels a part of its screen (NO CREW on the song select): white words on a dark
    leaning plate, its right end cut on the slant. Returns an RGBA picture just big enough."""
    hangul = any("가" <= ch <= "힣" for ch in text)
    font = ImageFont.truetype(theme.HANGUL_TITLE_FILE if hangul else theme.WIDE_FILE,
                              int(round((11.5 if hangul else 9.5) * scale)))
    height = int(round(22 * scale))
    pad = int(round(10 * scale))
    width = int(font.getlength(text)) + 2 * pad + int(height * LEAN)
    img = plain_plate(width, height, fill or theme.INK, top=theme.LINE, cut_left=False)
    ImageDraw.Draw(img).text((pad, height / 2), text, font=font, fill=_rgb(colour or theme.TEXT) + (255,), anchor="lm")
    return img


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


def toggle(on, width, height, enabled=True, colour=None, knob=None):
    """An on/off switch: a pill with a round knob, in the section's colour when on (the knob dark on a bright
    colour, light on blue)."""
    w, h = width * SS, height * SS
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    track = (colour or theme.BLUE) if on else theme.RAIL
    if not enabled:
        track = "#20262e"
    draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=_rgb(track) + (255,))
    pad = int(h * 0.16)
    d = h - 2 * pad
    x = w - pad - d if on else pad
    face = (knob if on and knob else theme.TEXT) if enabled else theme.FAINT
    draw.ellipse([x, pad, x + d, pad + d], fill=_rgb(face) + (255,))
    return img.resize((width, height), Image.LANCZOS)


def knob(size, colour=theme.TEXT, ring=theme.BLUE):
    """A slider knob: a light disc with a ring in the section's colour."""
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([0, 0, s - 1, s - 1], fill=_rgb(ring) + (255,))
    inset = int(s * 0.22)
    draw.ellipse([inset, inset, s - 1 - inset, s - 1 - inset], fill=_rgb(colour) + (255,))
    return img.resize((size, size), Image.LANCZOS)


def lamp(colour, lit=True, scale=1.0):
    """A small leaning light beside a line: filled when lit, an outline when not. It says how a check stands
    (fine, will change, problem) and which row of a list is the chosen one. Returns an RGBA picture."""
    width, height = int(round(13 * scale)), int(round(10 * scale))
    w, h = width * SS, height * SS
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.polygon(lean_outline(0, 0, w - 1, h - 1), fill=_rgb(colour) + (255,))
    if not lit:
        # The middle taken out again: what stays is a line of even width along the outline.
        line = 1.6 * scale * SS
        draw.polygon(lean_outline(0, 0, w - 1, h - 1, grow=-line), fill=(0, 0, 0, 0))
    return img.resize((width, height), Image.LANCZOS)


def choice_row(texts, chosen, hover, colours, scale=1.0):
    """A row of choices of which one is on, set as the game sets its plates side by side: every choice a leaning
    slab, the chosen one striped in the section's colour (like the menu's chosen entry and PLAY), the others quiet
    metal with grey words, lighter under the pointer.

    texts: the words; chosen, hover: indexes (hover may be None). Returns (an RGBA picture, each choice's left and
    right edge in it at half its height, for telling which one a click is on).
    """
    font = ImageFont.truetype(theme.TEXT_BOLD_FILE, int(round(13.33 * scale)))
    height = int(round(30 * scale))
    pad, gap = int(round(13 * scale)), int(round(3 * scale))
    lean = int(height * LEAN)
    widths = [int(font.getlength(text)) + 2 * pad + lean for text in texts]
    # Each slab starts where the one before ends less the lean: their slanted ends run side by side, a gap apart.
    total = sum(w - lean + gap for w in widths) - gap + lean
    img = Image.new("RGBA", (total, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    x, edges = 0, []
    for i, (text, w) in enumerate(zip(texts, widths)):
        if i == chosen:
            plate = striped_plate(w, height, colours["fill"], colours["accent"], colours["deep"])
            colour = colours["ink"]
        elif i == hover:
            plate, colour = plain_plate(w, height, theme.RAIL_UP, top="#5a6573"), theme.TEXT
        else:
            plate, colour = plain_plate(w, height, theme.RAIL, top=theme.RAIL_UP), theme.MUTED
        img.alpha_composite(plate, (x, 0))
        draw.text((x + w / 2, height / 2), text, font=font, fill=_rgb(colour) + (255,), anchor="mm")
        edges.append((x + lean // 2, x + w - lean // 2))
        x += w - lean + gap
    return img, edges


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
    # It falls a little below the panel, as from a light above.
    left, top = x - area[0], y - area[1] + int(12 * scale)
    ImageDraw.Draw(mask).rectangle([left, top, left + bw, top + bh], fill=int(255 * 0.72))
    mask = mask.filter(ImageFilter.GaussianBlur(20 * scale))
    region = scene.crop(area)
    region.paste(Image.new("RGB", size, (0, 0, 0)), (0, 0), mask)
    scene.paste(region, area[:2])
    return scene, soft


def dialog_panel(soft, box, tab, scale):
    """The panel: gunmetal glass over the blurred window with a sheen at its head and a light rim along its top,
    and the title tab hanging from the top edge as on the game's popups.

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
    # The edge: one pixel of seam, lit along the top like polished metal.
    edge = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(edge).rectangle([0, 0, bw - 1, bh - 1], outline=255)
    panel.paste(_gradient((bw, bh), "#626d7c", theme.LINE), (0, 0), edge)
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
# The section a page belongs to gives its main buttons their look.
SECTION_LOOKS = {"technika": "info", "star": "star", "pop": "danger", "console": "warn"}


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
