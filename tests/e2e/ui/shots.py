"""Open the launcher on the test container's virtual screen, visit every page and guide step, save a screenshot
of each, and measure the layout: text cut off, controls past the window's edge.

Run inside the opendmt3-ui container only (tests/e2e/ui/run.sh); it refuses anywhere else, because it opens windows.
The game folder is made up: small archives written with a random descriptor table, jackets drawn here, and a
stand-in client the launcher is told is supported. No game file is used.

  python tests/e2e/ui/shots.py --out DIR [--lang en|ko] [--size 1180x760] [--resize]
Exit status 1 when the layout check finds a problem; the problems are printed and written to DIR/problems.txt.
--resize also draws every page at every window width (resize_check): a width the window never finishes drawing at
is a problem.
"""

import argparse
import io
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time

# Run from the repository root (the container mounts it at /src).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

from opendmt3.core import game as g  # noqa: E402
from opendmt3.core import safety  # noqa: E402
from opendmt3.core.cabinet import values as choices  # noqa: E402
from opendmt3.client import widgets  # noqa: E402
from opendmt3.core.formats import pak  # noqa: E402

SETTINGS = (
    "[setting]\r\nfullscreen=true\r\npopup_style=true\r\nfixed_frame=false\r\nvsync=true\r\n\r\n"
    "screen_width=1280\r\nscreen_height=768\r\n\r\n"
    "sfx_volume=127\r\nbgm_volume=127\r\n\r\nshow_cursor=false\r\nresource_preload=false\r\n\r\n"
    "[FilePath]\r\nrankFilePath = file/\r\nbookkeepingFilePath = file/\r\ngameSettingFilePath = file/\r\n\r\n"
    "[graphics]\r\nfullscene_glow=true\r\nmultipleSample=1\r\n\r\n[test]\r\nPreLoadMovie = false\r\nUseVedio = true\r\n"
).encode("cp949")
NETWORK = b"[setting]\r\n\r\ntryconnet_time=10000\r\n\r\nserverip=203.0.113.9\r\nport=4725\r\n"
# The stage list offers the eight songs below (the card counts only the songs a mode of the game offers), two levels
# each, the second one hidden for every other song as the game hides some.
STAGE = b"stage1,songname,SP,PT,Hid,SP,PT,Hid\r\n" + b"".join(
    b"%d,song%02d,2,1,0,2,2,%d\r\n" % (i + 1, i, i % 2) for i in range(8))
# The song list as the game keeps it (UTF-16, tab-separated, the columns the catalog reads): eight made-up songs, one
# per jacket below, so the guide counts 8 songs and 8 jackets.
SONGS = ("no\tname\tFullName\tGenre\tComposer\tStar_1\tStar_2\tStar_3\tStar_4\tPop_1\tPop_2\tPop_3\tPop_4\r\n"
         + "".join("%d\tsong%02d\tMade-up Song %d\tPop\tComposer %d\t2\t5\t9\t0\t3\t6\t10\t12\r\n" % (i + 1, i, i + 1, i + 1)
                   for i in range(8))).encode("utf-16")


# Each made-up jacket's colours: the deep and the bright end of its ground, and the light of its motif. Eight sets as
# far apart as a game's own jackets are, deep enough under the launcher's white words.
PALETTES = [
    ((22, 30, 88), (58, 160, 255), (214, 246, 255)),
    ((78, 16, 70), (255, 82, 150), (255, 214, 124)),
    ((12, 58, 66), (34, 206, 164), (214, 255, 128)),
    ((74, 18, 18), (255, 104, 58), (255, 230, 164)),
    ((38, 20, 96), (160, 94, 255), (124, 240, 255)),
    ((18, 28, 40), (82, 116, 150), (255, 198, 88)),
    ((92, 28, 4), (255, 168, 34), (255, 248, 206)),
    ((8, 46, 30), (38, 156, 92), (204, 255, 196)),
]


def _sweep(size, angle):
    """A ramp from 0 to 255 across a square at `angle` degrees, with no corner left out."""
    over = int(size * 1.5)
    ramp = Image.linear_gradient("L").resize((over, over), Image.BICUBIC).rotate(angle, Image.BICUBIC)
    # The middle of the turned ramp: no corner of it reaches past the turned square's edges.
    off = (over - size) // 2
    return ramp.crop((off, off, off + size, off + size))


def disc(i):
    """A made-up song's jacket, 256x256 with the round edge and the centre hole the game's have, as a picture in a
    README reads it: finished art, never a placeholder. A sweep of two colours, a motif of its own (rings, shards, a sun
    over lines, or bars round the hole), the song's number set large in the launcher's wide face with "MADE-UP SONG"
    under it, a disc's sheen and a clear ring round the hole; drawn four times as large and made smaller, so its edges
    are smooth. No song's picture and no song's title: the songs are Made-up Song 1 to 8."""
    big = 1024
    dark, bright, light = PALETTES[i % len(PALETTES)]
    rng = random.Random(1000 + i)
    c = big / 2
    # The ground: the deep colour sweeping into the bright one, at an angle of its own.
    ramp = _sweep(big, rng.choice((25, 70, 115, 160, 205, 250, 295, 340)))
    img = Image.composite(Image.new("RGB", (big, big), bright), Image.new("RGB", (big, big), dark), ramp)
    img = img.convert("RGBA")
    motif = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(motif)
    kind = i % 4
    if kind == 0:
        # Rings spreading from a point off the centre, as a sound does.
        ox, oy = c + rng.uniform(-260, 260), c + rng.uniform(-260, 260)
        for n in range(1, 14):
            r = n * 64 + rng.uniform(-10, 10)
            d.ellipse((ox - r, oy - r, ox + r, oy + r), outline=light + (int(150 - n * 8),), width=int(6 + n * 1.5))
    elif kind == 1:
        # Long shards crossing it, as the launcher's own art has; each one's foot and top within reach of the edge.
        for _ in range(7):
            w, lean = rng.uniform(50, 160), rng.uniform(260, 420)
            x0 = rng.uniform(-lean * 0.6, big - w - lean * 0.4)
            colour = (light if rng.random() < 0.5 else bright) + (int(rng.uniform(70, 150)),)
            d.polygon([(x0, big + 40), (x0 + w, big + 40), (x0 + w + lean, -40), (x0 + lean, -40)], fill=colour)
    elif kind == 2:
        # A sun low over lines that close in towards the horizon.
        sun = Image.new("L", (big, big), 0)
        sx, sy, sr = c + rng.uniform(-120, 120), c - rng.uniform(80, 180), rng.uniform(210, 260)
        ImageDraw.Draw(sun).ellipse((sx - sr, sy - sr, sx + sr, sy + sr), fill=230)
        glow = Image.composite(Image.new("RGBA", (big, big), light + (255,)),
                               Image.new("RGBA", (big, big), bright + (255,)), _sweep(big, 270))
        motif.paste(glow, (0, 0), sun)
        y, step = sy + sr * 0.35, 18.0
        while y < big:
            d.rectangle((0, y, big, y + step * 0.45), fill=dark + (255,))
            y += step
            step *= 1.18
    else:
        # Bars round the hole, as a level meter set in a circle.
        for n in range(64):
            a = 2 * math.pi * n / 64
            h = 60 + 230 * abs(math.sin(n * 0.37 + i)) * rng.uniform(0.5, 1.0)
            x0, y0 = c + 200 * math.cos(a), c + 200 * math.sin(a)
            x1, y1 = c + (200 + h) * math.cos(a), c + (200 + h) * math.sin(a)
            d.line((x0, y0, x1, y1), fill=light + (int(120 + 100 * (h / 290)),), width=18)
    # A soft glow of the motif under it, then the motif itself.
    img = Image.alpha_composite(img, motif.filter(ImageFilter.GaussianBlur(28)))
    img = Image.alpha_composite(img, motif)
    # The song's number, large and wide, low on the disc where the hole does not cut it, a soft shadow under it, and a
    # line of small letters below.
    fonts = os.path.join(os.path.dirname(os.path.abspath(widgets.__file__)), "assets", "fonts")
    number = ImageFont.truetype(os.path.join(fonts, "DMT3Wide-Regular.ttf"), 205)
    small = ImageFont.truetype(os.path.join(fonts, "Pretendard-Bold.ttf"), 46)
    shade = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(shade).text((c, big * 0.845), "%02d" % (i + 1), font=number, anchor="ms", fill=(0, 0, 0, 150))
    img = Image.alpha_composite(img, shade.filter(ImageFilter.GaussianBlur(10)))
    words = ImageDraw.Draw(img)
    words.text((c, big * 0.845), "%02d" % (i + 1), font=number, anchor="ms", fill=(255, 255, 255, 235))
    words.text((c, big * 0.905), "MADE-UP SONG", font=small, anchor="ms", fill=(255, 255, 255, 190))
    # The disc's sheen: a broad soft light from the top left.
    sheen = Image.new("L", (big, big), 0)
    ImageDraw.Draw(sheen).ellipse((-big * 0.35, -big * 0.55, big * 0.75, big * 0.45), fill=70)
    img = Image.composite(Image.new("RGBA", (big, big), (255, 255, 255, 255)), img,
                          sheen.filter(ImageFilter.GaussianBlur(90)))
    # A light rim just inside the round edge.
    edge = 8
    ImageDraw.Draw(img).ellipse((edge + 10, edge + 10, big - edge - 10, big - edge - 10), outline=(255, 255, 255, 80),
                                width=8)
    # The clear ring round the hole: the art shows through it a little, as through a disc's plastic.
    hub, inner = big * 0.16, big * 0.105
    ring = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    r = ImageDraw.Draw(ring)
    r.ellipse((c - hub, c - hub, c + hub, c + hub), fill=(232, 238, 246, 120), outline=(255, 255, 255, 200), width=6)
    r.ellipse((c - inner, c - inner, c + inner, c + inner), outline=(30, 34, 44, 140), width=6)
    img = Image.alpha_composite(img, ring)
    # The disc's shape: round, with the hole open through it.
    shape = Image.new("L", (big, big), 0)
    s = ImageDraw.Draw(shape)
    s.ellipse((edge, edge, big - edge, big - edge), fill=255)
    hole = big * 0.075
    s.ellipse((c - hole, c - hole, c + hole, c + hole), fill=0)
    img.putalpha(shape)
    buf = io.BytesIO()
    img.resize((256, 256), Image.LANCZOS).save(buf, "PNG")
    return buf.getvalue()


def make_game(root, table, rng):
    """A game folder the launcher accepts: stand-in client, settings and stage archives, a disc archive."""
    os.makedirs(os.path.join(root, "pack"))
    os.makedirs(os.path.join(root, "file"))
    with open(os.path.join(root, "Client.exe"), "wb") as f:
        f.write(b"MZ stand-in client")
    with open(os.path.join(root, "file", "game"), "wb") as f:
        f.write(bytes(20))

    def write(name, files):
        template = pak.Header(0x01020304, 0, 2, 0, 0, 0x36, 1, 0)
        key_field = (0x2222).to_bytes(4, "little") + bytes(4)
        pak.write_pak(os.path.join(root, "pack", name + ".pak"), files, table, 0x3C, key_field, template, bytes(32),
                      seed_source=lambda n: rng.randrange(1 << 32).to_bytes(n, "little"))

    write("Config", {"Resource\\Config\\setting.ini": SETTINGS, "Resource\\Config\\networksetting.ini": NETWORK})
    write("DiscInfo", {"Resource\\DiscInfo\\pop_stage_1.csv": STAGE, "Resource\\DiscInfo\\discstock.csv": SONGS})
    write("DiscImg", {"Resource\\DiscImg\\song%02d_0.png" % i: disc(i) for i in range(8)})
    # Stand-ins for the files with the tutorial, the charts, the videos and the previews (only their names are looked
    # at: a copy without them says so).
    for name in [g.TUTORIAL, g.CHARTS] + list(g.VIDEOS) + list(g.PREVIEWS):
        with open(os.path.join(root, "pack", name + ".pak"), "wb") as f:
            f.write(b"stand-in")


def stand_in(root, table):
    """Tell the launcher what each stand-in client is, and give it the made-up table: Client.exe is the PC client as
    released, Modified.exe a modified PC client, Game.exe alone the cabinet's client (which opens nothing here)."""
    def base_client(self):
        path = os.path.join(self.root, "Client.exe")
        return path if os.path.isfile(path) else None

    def table_of(self):
        names = {n.lower(): n for n in os.listdir(self.root)}
        for name, kind in (("client.exe", g.ORIGINAL), ("modified.exe", g.MODIFIED)):
            if name in names:
                self.client = (os.path.join(self.root, names[name]), kind)
                return table
        raise g.GameError("The cabinet's client: does not work here, the PC client is needed.",
                          "error.game.cabinet_client")

    g.Game.base_client = base_client
    g.Game.table = table_of


def seven_zip(args, cwd):
    """The official 7-Zip of the test machine (tests/e2e/ui/Dockerfile), quiet."""
    subprocess.run([os.environ.get("OPENDMT3_7ZIP", "7zz"), args[0], "-bso0", "-bsp0"] + args[1:], cwd=cwd, check=True)


def make_intake(desktop, downloads, table, rng):
    """Every form a player may bring, made up, where the search looks: game folders on the Desktop that the guide must
    tell apart (one damaged, the cabinet's, a modified PC client, one without its videos, its previews, the file with
    the tutorial or the file with the charts, one an earlier PLAY changed), and in Downloads an
    archive of each kind (whole, split, with its names behind a password, inside another, a part missing, cut short).
    Returns {name: path} of what the checks press on."""
    made = {}
    # A copy whose song list's file was only partly copied (it cannot be read).
    half = os.path.join(desktop, "Unfinished copy", "game")
    make_game(half, table, rng)
    with open(os.path.join(half, "pack", "DiscInfo.pak"), "r+b") as f:
        f.truncate(48)
    # The cabinet's folder: its own client alone.
    cabinet = os.path.join(desktop, "Venue cabinet", "game")
    make_game(cabinet, table, rng)
    os.replace(os.path.join(cabinet, "Client.exe"), os.path.join(cabinet, "Game.exe"))
    # A modified PC client: played as it is.
    modified = os.path.join(desktop, "Version modified", "game")
    make_game(modified, table, rng)
    os.replace(os.path.join(modified, "Client.exe"), os.path.join(modified, "Modified.exe"))
    # A copy without the videos: it plays, songs without them (measured on the real client).
    novideo = os.path.join(desktop, "Without videos", "game")
    make_game(novideo, table, rng)
    for name in g.VIDEOS:
        os.remove(os.path.join(novideo, "pack", name + ".pak"))
    # A copy without the file with the tutorial: the game stops at the tutorial (measured), so it does not play here.
    untaught = os.path.join(desktop, "Without tutorial", "game")
    make_game(untaught, table, rng)
    os.remove(os.path.join(untaught, "pack", g.TUTORIAL + ".pak"))
    # A copy without the previews: it plays, the song select shows none (measured).
    unpreviewed = os.path.join(desktop, "Without previews", "game")
    make_game(unpreviewed, table, rng)
    os.remove(os.path.join(unpreviewed, "pack", g.PREVIEWS[0] + ".pak"))
    # A copy without the file with the charts: the game stops when a song starts (measured).
    unscored = os.path.join(desktop, "Without charts", "game")
    make_game(unscored, table, rng)
    os.remove(os.path.join(unscored, "pack", g.CHARTS + ".pak"))
    # A folder an earlier PLAY changed: its backup list names a file that is not its original any more.
    played = os.path.join(desktop, "Was played before", "game")
    make_game(played, table, rng)
    os.makedirs(os.path.join(played, "backup", "pack"))
    with open(os.path.join(played, "pack", "Config.pak"), "rb") as f:
        original = f.read()
    with open(os.path.join(played, "backup", "pack", "Config.pak"), "wb") as f:
        f.write(original)
    with open(os.path.join(played, "pack", "Config.pak"), "ab") as f:
        f.write(b"changed by a stand-in PLAY")
    import hashlib
    import json
    with open(os.path.join(played, "backup", "openDMT3.json"), "w") as f:
        json.dump({"version": 1, "folders": [], "files": {"pack/Config.pak": {
            "existed": True, "sha256": hashlib.sha256(original).hexdigest()}}}, f)
    made["played"] = played
    # The archives, of a made-up game folder named as people name theirs.
    src = tempfile.mkdtemp()
    make_game(os.path.join(src, "TECHNIKA 3"), table, rng)
    # A file of random bytes, as the game's videos are (they do not compress): enough for a split archive's parts.
    with open(os.path.join(src, "TECHNIKA 3", "pack", "filler.pak"), "wb") as f:
        f.write(bytes(rng.randrange(256) for _ in range(300000)))
    os.makedirs(downloads, exist_ok=True)
    seven_zip(["a", "-t7z", os.path.join(downloads, "technika3-copy.7z"), "TECHNIKA 3"], src)
    made["archive"] = os.path.join(downloads, "technika3-copy.7z")
    # A zip, whose song list's files come out at once: the search still says it from its listing alone (no songs).
    seven_zip(["a", "-tzip", os.path.join(downloads, "technika3-zip.zip"), "TECHNIKA 3"], src)
    seven_zip(["a", "-t7z", "-v100k", os.path.join(downloads, "technika3-parts.7z"), "TECHNIKA 3"], src)
    seven_zip(["a", "-t7z", "-pmade-up-1", "-mhe=on", os.path.join(downloads, "djmax-locked.7z"), "TECHNIKA 3"], src)
    made["locked"] = os.path.join(downloads, "djmax-locked.7z")
    seven_zip(["a", "-tzip", "-mx0", os.path.join(downloads, "dmt3-wrapped.zip"), "technika3-copy.7z"], downloads)
    gap = os.path.join(downloads, "parts")
    os.makedirs(gap)
    seven_zip(["a", "-t7z", "-v100k", os.path.join(gap, "technika3-gap.7z"), "TECHNIKA 3"], src)
    os.remove(os.path.join(gap, "technika3-gap.7z.002"))
    with open(made["archive"], "rb") as f:
        whole = f.read()
    # Cut short, as a download that stopped.
    with open(os.path.join(downloads, "technika3-broken.7z"), "wb") as f:
        f.write(whole[:len(whole) // 2])
    made["broken"] = os.path.join(downloads, "technika3-broken.7z")
    shutil.rmtree(src)
    return made


def widgets_of(widget):
    yield widget
    for child in widget.winfo_children():
        yield from widgets_of(child)


def wrap_of(w):
    """A label's wrap width in pixels (Tk returns a screen distance object)."""
    return int(w.winfo_fpixels(str(w.cget("wraplength"))))


def words_of(w):
    """What a widget shows, for a problem's line: a label's words, a button's, a picture's words, or nothing."""
    try:
        # A label's words; a field's and a drop-down's are what is typed or chosen in it.
        text = w.cget("text") if w.winfo_class() == "Label" else (
            w.get() if w.winfo_class() in ("Entry", "TCombobox") else "")
    except Exception:  # noqa: BLE001  (a widget with no text option)
        text = ""
    # A button keeps its words on itself (widgets.Button), a plate or menu entry beside its picture.
    return (text or getattr(w, "words", None) or "")[:60]


def scroll_area_of(child):
    """The page's scroll area (widgets.ScrollArea) whose content frame `child` is, or None."""
    canvas = child.master
    area = getattr(canvas, "master", None)
    # Only the scroll area's own content frame scrolls: any other window on a canvas stays where it is drawn.
    return area if isinstance(area, widgets.ScrollArea) and area.inner is child else None


def scrolls_to(area, w):
    """True when the scroll area can bring the whole of `w`, somewhere in its content, into view: the content's
    scroll region holds the widget's box, and when the content is taller than the area its scroll bar is on screen
    (the bar is how a person sees there is more, and the way in without a wheel)."""
    region = str(area.canvas.cget("scrollregion")).split()
    if len(region) != 4:
        # No region at all: the canvas scrolls nowhere.
        return False
    first, last = area.canvas.yview()
    if (first > 0 or last < 1) and not area.bar.winfo_ismapped():
        # More content than the area shows, and nothing on screen to say so or to scroll with.
        return False
    # The content frame sits at the canvas's origin, so its own pixels are the region's.
    top = w.winfo_rooty() - area.inner.winfo_rooty()
    bottom = top + w.winfo_height()
    # A pixel either way: Tk rounds the region's edges to whole pixels.
    return float(region[1]) - 1 <= top and bottom <= float(region[3]) + 1


def hidden(app, name, problems):
    """Content hidden under the bottom bar or past the window's bottom edge with no way to scroll to it.

    Three kinds: a widget whose box runs below what the boxes around it show (each box shows only what lies inside
    it), where no scroll area can bring it up; a widget its row had no room left for at all (pack and grid then
    unmap it, so a check of what shows never meets it); a label, field or button squeezed shorter than its own
    words. A page in the scroll area (widgets.ScrollArea) that is taller than the window is none of them: it scrolls.
    Returns how many widgets it looked at, so a check that looks at nothing never passes for one that found nothing.
    """
    import tkinter as tk
    root = app.root
    looked = 0
    for w in widgets_of(root):
        if w is root:
            continue
        cls = w.winfo_class()
        if not w.winfo_ismapped():
            parent = w.master
            # Managed by pack or grid in a box on screen, yet not on screen itself: its box had no room left for it.
            # (A widget taken away on purpose, as the scroll bar of a page that fits, is managed by nothing.)
            if w.winfo_manager() in ("pack", "grid") and parent is not None and parent.winfo_ismapped():
                problems.append("%s: no room left for it, past the bottom with no way to scroll to it: %s %r"
                                % (name, cls, words_of(w)))
            continue
        if cls in ("Frame", "Toplevel"):
            # A box shows what is in it; what it holds is measured widget by widget.
            continue
        looked += 1
        content_sized = isinstance(w, (tk.Label, tk.Entry, widgets.Button)) or cls == "TCombobox"
        if content_sized and w.winfo_reqheight() > w.winfo_height() + 2:
            # Its box gave it less height than its words or picture need: the foot of them is cut.
            problems.append("%s: cut at its foot, with no way to scroll to it: %s %r (needs %d px, has %d)"
                            % (name, cls, words_of(w), w.winfo_reqheight(), w.winfo_height()))
        # The lowest line any box around it shows, up to the page's scroll area when that can bring the widget up.
        bottom = w.winfo_rooty() + w.winfo_height()
        edge = None
        child, box = w, w.master
        while box is not None:
            area = scroll_area_of(child)
            if area is not None and scrolls_to(area, w):
                # The page scrolls to it; whether the scroll area itself shows is measured as a widget of its own.
                break
            under = box.winfo_rooty() + box.winfo_height()
            edge = under if edge is None else min(edge, under)
            child, box = box, box.master
        if edge is not None and bottom > edge + 1:
            problems.append("%s: hidden below with no way to scroll to it: %s %r (%d of its %d px under the edge)"
                            % (name, cls, words_of(w), bottom - max(edge, w.winfo_rooty()), w.winfo_height()))
        # A scroll area's own canvas holds the page, which scrolls (the widgets on it are measured one by one).
        page_canvas = isinstance(w.master, widgets.ScrollArea) and w is w.master.canvas
        if (cls == "Canvas" and not isinstance(w, (widgets.Button, widgets.SlimBar)) and not page_canvas
                and w.winfo_manager() != "place" and w.find_all()):
            # A drawing of its own (the page's header and its line of words): nothing drawn past its foot. The
            # pictures of buttons and the scroll bar fit by their making; a dialog (placed over the window) measures
            # its own panel (Dialog.layout_problems).
            drawn = w.bbox(*w.find_all())
            if drawn and drawn[3] > w.winfo_height() + 2:
                problems.append("%s: drawn past its foot, with no way to scroll to it: %d px of a %d px canvas"
                                % (name, drawn[3] - w.winfo_height(), w.winfo_height()))
    return looked


def measure(app, name, problems):
    """Text cut off (a label narrower than its text without wrapping), widgets past the window's right edge, and
    content hidden under the bottom bar or past the window's bottom edge with no way to scroll to it (hidden)."""
    import tkinter as tk
    root = app.root
    root.update()
    while UNSETTLED:
        # The screen was shot while something was still working: what it shows is not the finished page.
        problems.append("%s: still working when it was shot: %s" % (name, UNSETTLED.pop(0)))
    # Below the visible area with no scroll to bring it up: counted, so a run that looked at nothing says so.
    HIDDEN_LOOKS.append(hidden(app, name, problems))
    right = root.winfo_rootx() + root.winfo_width()
    for w in widgets_of(root):
        if not w.winfo_ismapped():
            continue
        cls = w.winfo_class()
        if cls == "Label" and w.cget("text"):
            # Tk shrinks a label when room runs out and cuts its text; the required width says how much it wanted.
            # This holds for wrapping labels too: a wrap width wider than the room left cuts the longest line.
            if w.winfo_reqwidth() > w.winfo_width() + 2:
                problems.append("%s: text cut off: %r (needs %d px, has %d)" % (name, w.cget("text")[:60],
                                                                                w.winfo_reqwidth(), w.winfo_width()))
        if cls in ("Label", "Frame", "Canvas", "TCombobox") and w.winfo_width() > 1:
            if w.winfo_rootx() + w.winfo_width() > right + 1 and w.winfo_viewable():
                # Content inside the scrolled page counts only where it shows.
                problems.append("%s: past the right edge: %s %r" % (name, cls, (w.cget("text") if cls == "Label" else "")[:40]))
        if isinstance(w, tk.Label) and wrap_of(w) == app.ui.px(widgets.START_WRAP) and len(w.cget("text")) > 20:
            # Still at its start width: its box never told it the real room (an error in follow_width, or no event).
            problems.append("%s: wrapping never set: %r" % (name, w.cget("text")[:60]))
        if isinstance(w, widgets.Button) and w.winfo_width() + 1 < w.winfo_reqwidth():
            # A button the row has no room for is squeezed and cuts its words.
            problems.append("%s: button squeezed: %r (needs %d px, has %d)" % (name, w.words, w.winfo_reqwidth(),
                                                                              w.winfo_width()))
        if isinstance(w, tk.Label) and wrap_of(w):
            # A wrapping label must still fit its parent's width.
            parent = w.nametowidget(w.winfo_parent())
            if w.winfo_width() > parent.winfo_width() + 2:
                problems.append("%s: wrapped text wider than its box: %r" % (name, w.cget("text")[:60]))


# Every screenshot taken, so the last line counts what was looked at instead of what was meant to be.
SHOTS = []
# Every resize the resize check looked at (resize_check), counted the same way.
RESIZES = []
# The widest window the resize check draws (the virtual screen is 1920 wide), and the events one redraw may handle
# before the window is taken for one that never finishes: a page drawn at a new width handles about a thousand.
RESIZE_TO = 1900
RESIZE_EVENTS = 40000
# What was still working when settle() gave up waiting: the next measure() reports it with its screen.
UNSETTLED = []
# How many widgets each measure() looked at for content hidden with no way to scroll to it (hidden), and the PLAY
# pages held to the launcher's own size (play_fits_check): counted, so a check that met nothing never reads as a pass.
HIDDEN_LOOKS = []
FITS = []


def shot(app, out, name, root=None):
    """Screenshot of the launcher window, through the X server (what a person would see)."""
    SHOTS.append(name)
    root = root or app.root
    root.update()
    time.sleep(0.25)
    root.update()
    target = os.path.join(out, name + ".png")
    if sys.platform == "win32":
        # Windows' Tk (tests/e2e/ui/run_wine.sh, at a Windows scaling): the window's area of the screen, as Windows
        # draws it, through Pillow's screen grab (there is no X tool on that side).
        from PIL import ImageGrab
        x, y = root.winfo_rootx(), root.winfo_rooty()
        ImageGrab.grab(bbox=(x, y, x + root.winfo_width(), y + root.winfo_height()), all_screens=True).save(target)
        return target
    wid = root.winfo_id()
    # The Tk frame's parent is the top-level window the window manager would decorate.
    top = root.wm_frame()
    subprocess.run(["import", "-window", top if top and top != "0x0" else str(wid), target], check=True)
    return target


# The launcher's short workers, by the names it gives their threads; each hands its result to the window's pump.
# ("game-server" is not one: it lives as long as the server does.)
WORKERS = {"check": "the ready check", "discs": "the song discs", "find": "the folder search",
           "look": "a path being looked at", "password": "a password being checked", "unpack": "an unpacking",
           "play": "PLAY getting the folder ready", "plays": "the session's plays",
           "lan": "the server for the other PCs", "records": "the records", "connect": "the other server's answer",
           "sign-in": "the sign-in", "updates": "the look for updates", "update": "the update",
           "removing": "putting the game back to remove openDMT3", "song-list": "the song list being saved or sent"}


def working(app):
    """What the window still waits for, in words ("" when nothing): a worker that has not ended, or a result one
    of them left for the window's pump."""
    busy = sorted({WORKERS[t.name] for t in threading.enumerate() if t.name in WORKERS and t.is_alive()})
    if not app.tasks.empty():
        # A worker has ended, and its result still waits for the window's pump.
        busy.append("a result not drawn yet")
    return ", ".join(busy)


def settle(app, seconds=6.0):
    """Let worker threads (ready check, discs, folder search) finish and their results reach the window.

    Settled means nothing was working over four looks in a row (200 ms, four turns of the window's 50 ms pump):
    a result drawn by the pump may start the next worker. Running out of time is written down for measure(),
    because a screen that is still loading measures as a clean screen."""
    end = time.time() + seconds
    quiet, what = 0, ""
    while time.time() < end:
        app.root.update()
        what = working(app)
        quiet = 0 if what else quiet + 1
        if quiet >= 4:
            break
        time.sleep(0.05)
    else:
        UNSETTLED.append("%s after %g s" % (what or "nothing for long enough", seconds))
    app.root.update()


def button(app, words):
    """The page's button with these words (the way a person finds it)."""
    for w in widgets_of(app.root):
        if isinstance(w, widgets.Button) and w.words == words and w.winfo_ismapped():
            return w
    raise AssertionError("no button %r on the page" % words)


def wait_out(app, seconds):
    """Let the window run (the dialog's rise, a redraw after a resize) for a while."""
    end = time.time() + seconds
    while time.time() < end:
        app.root.update()
        time.sleep(0.02)


def settles(root, most=RESIZE_EVENTS):
    """The window's waiting work done an event at a time, as update() does it: False when it does not run out.

    update() itself never comes back from a window whose widgets keep sizing each other, and the run would stand
    still until its time is up without a word of where."""
    import _tkinter
    # Every kind of event, never waiting for one: what update() asks Tk for.
    flags = _tkinter.ALL_EVENTS | _tkinter.DONT_WAIT
    for _ in range(most):
        if not root.tk.dooneevent(flags):
            return True
    return False


def resize_check(app, out, tag, problems):
    """Every page at every window width, from the narrowest the window takes to a wide monitor's, a pixel at a time
    as a person dragging the window's edge does: a width at which the window never finishes drawing is a problem.

    PLAY's two cards side by side once handed one pixel back and forth through their wrapping labels: at 8 of these
    widths in English and 12 in Korean the window stopped answering (widgets.wrap_width). The three sizes the
    screenshots are taken at missed every one of them."""
    from opendmt3.client.app import NAV
    back = app.root.geometry()
    narrowest, height = app.root.minsize()[0], app.root.winfo_height()
    for page in NAV:
        app.root.geometry("%dx%d+0+0" % (narrowest, height))
        app.go(page)
        settle(app)
        stuck = []
        for width in range(narrowest, RESIZE_TO + 1):
            app.root.geometry("%dx%d+0+0" % (width, height))
            RESIZES.append((page, width))
            # Twice: the first lays the window out at its new width, the second lets what that started come to rest.
            if not (settles(app.root) and settles(app.root)):
                stuck.append(width)
        if stuck:
            problems.append("%s: the %s page never finishes drawing at %d of %d window widths: %s" % (
                tag, page, len(stuck), RESIZE_TO + 1 - narrowest, " ".join(str(width) for width in stuck[:12])))
    # The window as it was, for whatever follows. A window still busy here would hold the run without a word: said,
    # and the run ends with what it found.
    app.root.geometry(back)
    if not (settles(app.root) and settles(app.root)):
        problems.append("%s: the window never finishes drawing once it is back at %s" % (tag, back))
        finish(out, tag, problems)
    app.go(NAV[0])
    settle(app)


def through_dialog(app, out, name, press, answer, problems, extra=None):
    """Press a page button that asks first, as a person would; screenshot and measure the dialog it opens, then
    answer it with `answer(dialog)`. Returns what the dialog answered (None when none opened)."""
    seen = {}

    def look():
        dialog = app.dialog
        if dialog is None:
            problems.append("%s: the button opened no dialog" % name)
            return
        seen["dialog"] = dialog
        wait_out(app, 0.4)
        shot(app, out, name)
        problems.extend("%s: %s" % (name, p) for p in dialog.layout_problems())
        if extra:
            extra(dialog)
        answer(dialog)

    app.root.after(300, look)
    press()
    dialog = seen.get("dialog")
    if dialog is not None and app.dialog is not None:
        problems.append("%s: the dialog stayed after its answer" % name)
    return dialog.result if dialog is not None else None


def click_button(dialog, i):
    """Move the pointer onto a dialog button and click it, through the X server's events."""
    left, top, right, bottom = dialog._boxes[i]
    x, y = dialog.origin[0] + (left + right) // 2, dialog.origin[1] + (top + bottom) // 2
    c = dialog.canvas
    c.event_generate("<Motion>", x=x, y=y, warp=True)
    c.update()
    c.event_generate("<ButtonPress-1>", x=x, y=y)
    c.event_generate("<ButtonRelease-1>", x=x, y=y)


def scroll_check(app, tag, problems):
    """The page's own scroll bar (widgets.SlimBar) on a page taller than the window: shown, and it pages and drags."""
    area, bar = app.body.canvas, app.body.bar
    app.body.to_top()
    wait_out(app, 0.1)
    if not bar.winfo_ismapped():
        problems.append("%s: no scroll bar on a page taller than the window" % tag)
        return
    # A press under the thumb turns a page.
    low = bar.winfo_height() - 2
    bar.event_generate("<ButtonPress-1>", x=4, y=low)
    bar.event_generate("<ButtonRelease-1>", x=4, y=low)
    wait_out(app, 0.1)
    if area.yview()[0] <= 0:
        problems.append("%s: a press under the scroll bar's thumb did not turn the page" % tag)
    # A drag that takes the thumb to the trough's top brings the page back to its start.
    top, bottom = bar.thumb()
    hold = int((top + bottom) / 2)
    bar.event_generate("<ButtonPress-1>", x=4, y=hold)
    bar.event_generate("<B1-Motion>", x=4, y=hold - int(top) - 40)
    bar.event_generate("<ButtonRelease-1>", x=4, y=hold - int(top) - 40)
    wait_out(app, 0.1)
    if area.yview()[0] != 0:
        problems.append("%s: dragging the scroll bar's thumb up did not bring the page back (%r)" % (tag, area.yview()))
    if bar.grip is not None:
        problems.append("%s: the scroll bar still holds its thumb after the release" % tag)


def dialogs_check(app, out, tag, problems):
    """The launcher's two questions, opened from their pages, answered by key and by click, at a resize too."""
    from opendmt3.client import dialogs
    app.state.mode = "this_pc"
    app.state.save()
    store = app.players()
    if store.by_login("NOVA") is None:
        store.create("NOVA", "pass1234", "DJ NOVA")
    store.create("LONGNAME", "pass1234", "가나다라마바사아")
    store.db.close()
    app.go("online")
    settle(app)
    # The Remove button on the long name's row (the row holds the name's label).
    # The Delete button on the long name's row (the row holds the name's label).
    remove = [w for w in widgets_of(app.root) if isinstance(w, widgets.Button) and w.words == app.words("online.remove")
              and any(getattr(c, "cget", None) and c.winfo_class() == "Label" and c.cget("text") == "가나다라마바사아"
                      for c in w.master.winfo_children())]
    if len(remove) != 1:
        problems.append("%s: expected the long name's Remove button on Online, found %d" % (tag, len(remove)))
        return
    # Esc keeps the player; the ring starts on Cancel, so Enter alone keeps them too.
    def ring_moves(dialog):
        dialog.canvas.event_generate("<Tab>")
        wait_out(app, 0.1)
        shot(app, out, "%s_dialog-remove-ring" % tag)
        if dialog.focus != 1:
            problems.append("%s: Tab did not move the ring to Remove" % tag)
        dialog.canvas.event_generate("<Shift-Tab>" if sys.platform == "win32" else "<ISO_Left_Tab>")
    answer = through_dialog(app, out, "%s_dialog-remove" % tag, remove[-1].press,
                            lambda d: d.canvas.event_generate("<Escape>"), problems, extra=ring_moves)
    if answer is not False:
        problems.append("%s: Esc on the remove dialog answered %r" % (tag, answer))
    answer = through_dialog(app, out, "%s_dialog-remove-enter" % tag, remove[-1].press,
                            lambda d: d.canvas.event_generate("<Return>"), problems)
    store = app.players()
    kept = store.by_login("LONGNAME") is not None
    store.db.close()
    if answer is not False or not kept:
        problems.append("%s: Enter on the remove dialog removed the player (answer %r)" % (tag, answer))
    # A resize while it is open draws it again for the new size.
    def resized(dialog):
        app.root.geometry("960x640")
        wait_out(app, 0.6)
        shot(app, out, "%s_dialog-remove-960" % tag)
        problems.extend("%s_dialog-remove-960: %s" % (tag, p) for p in dialog.layout_problems())
        if dialog.size != (app.root.winfo_width(), app.root.winfo_height()):
            problems.append("%s: the dialog was not drawn again after a resize" % tag)
    answer = through_dialog(app, out, "%s_dialog-remove-click" % tag, remove[-1].press,
                            lambda d: click_button(d, 1), problems, extra=resized)
    store = app.players()
    gone = store.by_login("LONGNAME") is None
    store.db.close()
    if answer is not True or not gone:
        problems.append("%s: clicking Remove did not remove the player (answer %r)" % (tag, answer))
    # The restore question starts on its main button; hovering lights it.
    app.go("help")
    settle(app)

    def hovered(dialog):
        left, top, right, bottom = dialog._boxes[1]
        dialog.canvas.event_generate("<Motion>", x=dialog.origin[0] + left + 8, y=dialog.origin[1] + top + 8,
                                     warp=True)
        wait_out(app, 0.15)
        shot(app, out, "%s_dialog-restore-hover" % tag)
    answer = through_dialog(app, out, "%s_dialog-restore" % tag, button(app, app.words("help.restore.confirm")).press,
                            lambda d: d.canvas.event_generate("<Return>"), problems, extra=hovered)
    if answer is not True:
        problems.append("%s: Enter on the restore dialog answered %r" % (tag, answer))
    if app.status_tone != "ok":
        problems.append("%s: putting files back did not report (status %r)" % (tag, app.status_text))
    # What the look for updates says, under the version: nothing newer, then an update with its button.
    from opendmt3.client import updates
    real_check = updates.check
    w = app.words
    for name, result in (("uptodate", updates.Result("uptodate")), ("update", updates.Result("available", "9.9.9"))):
        updates.check = lambda source=None, result=result: result
        try:
            app.go("about")
            settle(app)
            button(app, w("about.check")).press()
            settle(app)
        finally:
            updates.check = real_check
        shot(app, out, "%s_about-%s" % (tag, name))
        measure(app, "%s_about-%s" % (tag, name), problems)
    # The update's button sits right under the words about it, not at the end of the page.
    said = [x for x in widgets_of(app.root) if x.winfo_class() == "Label" and x.cget("text") == w("about.available", v="9.9.9")]
    press = button(app, w("about.update_now", v="9.9.9"))
    if not said or not 0 <= press.winfo_rooty() - (said[0].winfo_rooty() + said[0].winfo_height()) <= app.ui.px(16):
        problems.append("%s_about-update: the update's button is not under its words" % tag)
    # ...and whole inside the page's visible area, whatever the window's size (the page scrolls to it).
    area = app.body.canvas
    if not (area.winfo_rooty() <= press.winfo_rooty()
            and press.winfo_rooty() + press.winfo_height() <= area.winfo_rooty() + area.winfo_height()):
        problems.append("%s_about-update: the update's button is cut by the page's edge" % tag)
    # The page is taller than this window, so its scroll bar is there to use.
    scroll_check(app, tag, problems)
    # The update under way (client/updating.py opens it while the update is fetched and checked).
    from opendmt3.core import errors
    from opendmt3.client import updating
    app.go("about")
    settle(app)
    shown = updating.Shown(app, "9.9.9")
    dialog = shown.dialog
    wait_out(app, 0.6)
    shot(app, out, "%s_dialog-updating" % tag)
    problems.extend("%s_dialog-updating: %s" % (tag, p) for p in dialog.layout_problems())
    dialog.canvas.event_generate("<Escape>")
    wait_out(app, 0.1)
    if dialog.closed:
        problems.append("%s: Esc closed the update under way" % tag)
    # The same dialog once the whole package is fetched instead of only what changed: its second line says so.
    shown.told("whole")
    wait_out(app, 0.3)
    shot(app, out, "%s_dialog-updating-whole" % tag)
    problems.extend("%s_dialog-updating-whole: %s" % (tag, p) for p in dialog.layout_problems())
    if dialog.detail != w("about.updating.whole"):
        problems.append("%s: the update's dialog does not say the whole update is downloading" % tag)
    shown.close()
    if not dialog.closed or app.dialog is not None:
        problems.append("%s: the update's dialog stayed open" % tag)
    # An update that is not put in, told as updating.run tells it: one that is not signed, one not downloaded.
    for name, key in (("unsigned", "error.update.unsigned"), ("download", "error.update.download")):
        error = updates.UpdateError(errors.TEXT[key][0].format(version="9.9.9"), key, version="9.9.9")
        told = dialogs.Dialog(app.root, app.ui, "error", w("about.update_failed.title"),
                              w("about.apply_failed", error=errors.say(error, app.state.language)), None,
                              [(w("common.ok"), True, dialogs.KINDS["error"]["button"])], default=0, cancel=True)
        wait_out(app, 0.6)
        shot(app, out, "%s_dialog-update-%s" % (tag, name))
        problems.extend("%s_dialog-update-%s: %s" % (tag, name, p) for p in told.layout_problems())
        told.close(True)
    return dialogs


def repair_check(app, out, tag, problems):
    """Repair on Help (pages/help.py, client/repair.py), each way it can end: the work under way, nothing to
    repair, files put back (with the launcher's own among them, or not), some not put back, a package that cannot be
    read, and a launcher run from a plain folder. The repair itself is a stand-in that answers each of them in turn:
    run from source there is no installed package to compare with."""
    import threading
    from opendmt3.client import repair
    w = app.words
    app.go("help")
    settle(app)
    row = button(app, w("help.repair")).master
    app.body.show(row, app.ui.px(14))
    wait_out(app, 0.2)
    shot(app, out, "%s_help-repair" % tag)
    measure(app, "%s_help-repair" % tag, problems)
    current = os.path.join("current", "openDMT3.exe")
    outcomes = [
        ("fine", repair.Result(812, [], [], [])),
        ("done", repair.Result(812, ["Update.exe"], [], [])),
        ("restart", repair.Result(812, [], [current], [])),
        ("partly", repair.Result(812, [], [current, "Update.exe"], [current])),
        ("failed", repair.RepairError("the installed package cannot be read (run openDMT3-win-Setup.exe again and "
                                      "choose Repair)", "error.repair.package")),
        ("source", repair.RepairError("repair works in the launcher installed by openDMT3-win-Setup.exe",
                                      "error.repair.not_installed")),
    ]
    real = repair.run
    try:
        for i, (name, outcome) in enumerate(outcomes):
            go, seen = threading.Event(), {}

            def stand_in(root=None, outcome=outcome, go=go):
                # Held until the work under way has been looked at.
                go.wait(10)
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome

            repair.run = stand_in
            button(app, w("help.repair")).press()
            working = app.dialog
            if working is None:
                problems.append("%s: Repair opened no dialog" % tag)
                continue
            if i == 0:
                wait_out(app, 0.4)
                shot(app, out, "%s_dialog-repair-working" % tag)
                problems.extend("%s_dialog-repair-working: %s" % (tag, p) for p in working.layout_problems())
            label = "%s_dialog-repair-%s" % (tag, name)

            def look(label=label, working=working, seen=seen, tries=[0]):
                # The answer is a dialog of its own once the work is done; it waits for its Enter.
                dialog = app.dialog
                if dialog is None or dialog is working:
                    tries[0] += 1
                    if tries[0] < 100:
                        app.root.after(100, look)
                    return
                seen["dialog"] = dialog
                wait_out(app, 0.4)
                shot(app, out, label)
                problems.extend("%s: %s" % (label, p) for p in dialog.layout_problems())
                dialog.canvas.event_generate("<Return>")

            app.root.after(200, look)
            go.set()
            end = time.time() + 12
            while "dialog" not in seen and time.time() < end:
                wait_out(app, 0.1)
            wait_out(app, 0.3)
            if "dialog" not in seen:
                problems.append("%s: Repair said nothing when it ended" % label)
            elif app.dialog is not None:
                problems.append("%s: the dialog stayed after its answer" % label)
    finally:
        repair.run = real


def remove_check(app, out, tag, made, problems):
    """Uninstall on Help (pages/help.py, client/leaving.py), as a person goes through it.

    Run from source there is nothing to uninstall, and a running game stops it: both are said. Then, with an
    uninstaller made to look present: the question for a game folder that is gone; the question with its two ways on
    after Cancel (the ring starts on Cancel, Esc and Enter there keep everything, Tab moves the ring); and Delete all,
    through the progress dialog and the last step to the hand-over. The hand-over is caught: the window stays and
    Velopack's uninstall is never started here.
    """
    from opendmt3.client import leaving
    from opendmt3.client.pages import help as help_page
    w = app.words
    app.go("help")
    settle(app)
    # The row itself, brought into view as a person scrolls to it.
    row = button(app, w("help.uninstall")).master
    app.body.show(row, app.ui.px(14))
    wait_out(app, 0.2)
    shot(app, out, "%s_help-uninstall" % tag)
    measure(app, "%s_help-uninstall" % tag, problems)

    def uninstall():
        button(app, w("help.uninstall")).press()

    def enter(dialog):
        dialog.canvas.event_generate("<Return>")

    def escape(dialog):
        dialog.canvas.event_generate("<Escape>")

    through_dialog(app, out, "%s_dialog-uninstall-source" % tag, uninstall, enter, problems)
    app.busy = True
    try:
        through_dialog(app, out, "%s_dialog-uninstall-busy" % tag, uninstall, enter, problems)
    finally:
        app.busy = False
    real = (leaving.uninstaller, leaving.start_uninstall, leaving.before_uninstall, app.close)
    started, closed, gate = [], [], threading.Event()
    leaving.uninstaller = lambda: "C:\\Users\\player\\AppData\\Local\\openDMT3\\Update.exe"
    leaving.start_uninstall = lambda updater, everything=False, **kw: started.append((updater, everything))

    def held(state):
        # The progress dialog stays up until it has been shot and measured.
        gate.wait(10)
        return real[2](state)

    def close():
        # The window's own close would end this test: the dialog goes, the window stays.
        closed.append(True)
        if app.dialog is not None:
            app.dialog.close(None)
            app.dialog = None

    leaving.before_uninstall, app.close = held, close
    try:
        folder = app.state.game_folder
        app.state.game_folder = os.path.join(os.path.dirname(folder), "moved away")
        through_dialog(app, out, "%s_dialog-uninstall-gone" % tag, uninstall, escape, problems)

        def names_the_game(named):
            """The question says the game's files go back only when there are some to put back."""
            def look(dialog):
                if (w("help.uninstall.game") in (dialog.detail or "")) != named:
                    problems.append("%s: the uninstall question %s the game's files: %r"
                                    % (tag, "does not name" if named else "names", dialog.detail))
            return look

        # A folder an older openDMT3 changed: its files go back, and the question says so.
        app.state.game_folder = made["played"]
        through_dialog(app, out, "%s_dialog-uninstall-changed" % tag, uninstall, escape, problems,
                       extra=names_the_game(True))
        app.state.game_folder = folder

        def keys(dialog):
            # Cancel, Keep data, Delete all: the ring starts on Cancel.
            if dialog.focus != 0 or [b[1] for b in dialog.buttons] != [None, "keep", "all"]:
                problems.append("%s: the uninstall question is not Cancel, Keep data, Delete all from Cancel" % tag)
            dialog.canvas.event_generate("<Tab>")
            wait_out(app, 0.1)
            if dialog.focus != 1:
                problems.append("%s: Tab did not move the ring to Keep data" % tag)
            dialog.canvas.event_generate("<Shift-Tab>" if sys.platform == "win32" else "<ISO_Left_Tab>")
            wait_out(app, 0.1)
            # The folder PLAY alone used has nothing to put back: the question says nothing of the game's files.
            names_the_game(False)(dialog)
        answer = through_dialog(app, out, "%s_dialog-uninstall" % tag, uninstall, escape, problems, extra=keys)
        if answer is not None or started or closed or app.then is not None:
            problems.append("%s: Esc on the uninstall question did something (answer %r)" % (tag, answer))
        answer = through_dialog(app, out, "%s_dialog-uninstall-enter" % tag, uninstall, enter, problems)
        if answer is not None or started or closed:
            problems.append("%s: Enter on the uninstall question did something (answer %r)" % (tag, answer))

        # Delete all, clicked as a person would.
        def yes():
            dialog = app.dialog
            if dialog is None:
                problems.append("%s: Uninstall opened no question" % tag)
                return
            wait_out(app, 0.3)
            click_button(dialog, 2)
        app.root.after(300, yes)
        uninstall()
        progress = app.dialog
        if progress is None or not progress.progress:
            problems.append("%s: no progress dialog while the game's files go back" % tag)
        else:
            wait_out(app, 0.4)
            name = "%s_dialog-uninstall-removing" % tag
            shot(app, out, name)
            problems.extend("%s: %s" % (name, p) for p in progress.layout_problems())
            # Closing the window now (its X, Alt+F4) waits: the game's files are going back.
            type(app).close(app)
            wait_out(app, 0.1)
            if progress.closed or not app.root.winfo_exists():
                problems.append("%s: closing the window stopped putting the game's files back" % tag)
        gate.set()
        settle(app)
        # The last step: one word in the launcher's own dialog (Velopack's window never shows), then the hand-over.
        last = app.dialog
        if last is None or not last.progress or closed:
            problems.append("%s: no last step in the launcher's own dialog before it closed" % tag)
        else:
            wait_out(app, 0.4)
            name = "%s_dialog-uninstall-done" % tag
            shot(app, out, name)
            problems.extend("%s: %s" % (name, p) for p in last.layout_problems())
        wait_out(app, help_page.LAST_STEP_MS / 1000.0 + 0.4)
        if not closed or app.then is None:
            problems.append("%s: the window did not hand over to the uninstall (closed %r)" % (tag, closed))
        else:
            app.then()
            if started != [(leaving.uninstaller(), True)]:
                problems.append("%s: the uninstall was not started with Delete all: %r" % (tag, started))
    finally:
        gate.set()
        leaving.uninstaller, leaving.start_uninstall, leaving.before_uninstall, app.close = real
        app.then = None


def damaged_database_check(app, out, tag, problems):
    """This PC's database damaged: PLAY and Online say so where the players are listed, with the button to its
    folder, and the window goes on (it once failed to start at all)."""
    real = app.host.path
    damaged = os.path.join(os.path.dirname(real), "damaged", "openDMT3.sqlite")
    os.makedirs(os.path.dirname(damaged), exist_ok=True)
    with open(damaged, "wb") as f:
        f.write(b"not a database " * 512)
    app.host.path, mode = damaged, app.state.mode
    app.state.mode = "this_pc"
    try:
        for page in ("play", "online"):
            app.go(page)
            settle(app)
            name = "%s_%s-damaged-database" % (tag, page)
            shot(app, out, name)
            measure(app, name, problems)
            try:
                button(app, app.words("db.broken.open"))
            except AssertionError:
                problems.append("%s: no word of the damaged database where the players are listed" % name)
    finally:
        app.host.path, app.state.mode = real, mode


def failed_action_check(app, out, tag, problems):
    """A click or a timer whose error nothing caught: said in the launcher's own dialog, and the window goes on."""
    error = RuntimeError("a made-up failure inside a click")
    through_dialog(app, out, "%s_dialog-action-failed" % tag,
                   lambda: app._callback_failed(RuntimeError, error, None),
                   lambda d: d.canvas.event_generate("<Return>"), problems)
    if not app.root.winfo_exists():
        problems.append("%s: the window did not go on after a failed action" % tag)


def song_list_check(app, out, tag, problems):
    """The Game page's song list for a server, as a person uses it: Save the song list... opens the launcher's own Save
    dialog with the path on the desktop chosen whole (typing replaces it), the file is made from the made-up game
    folder while a dialog of work under way shows, and the saved one is said with its size; Send the song list to
    this server shows only to a server's admin, and with no network here its failure is said in the launcher's own
    dialog too. Every dialog is measured like the pages."""
    import tempfile
    from opendmt3.client import dialogs
    from opendmt3.server.services import songlist
    w = app.words
    app.state.mode = "this_pc"
    app.refresh_checks()
    app.go("game")
    settle(app)
    if any(isinstance(x, widgets.Button) and x.words == w("game.songlist.send") for x in widgets_of(app.root)):
        problems.append("%s: Send the song list shows without a server's admin signed in" % tag)
    target = os.path.join(tempfile.mkdtemp(), "saved-song-list.zip")
    seen = {}

    def path_dialog():
        dialog = app.dialog
        if not isinstance(dialog, dialogs.PathDialog):
            problems.append("%s: Save the song list... opened no Save dialog" % tag)
            return
        wait_out(app, 0.4)
        shot(app, out, "%s_dialog-save-song-list" % tag)
        problems.extend("%s_dialog-save-song-list: %s" % (tag, p) for p in dialog.layout_problems())
        seen["start"] = dialog.entry.get()
        seen["chosen"] = app.root.focus_get() is dialog.entry and dialog.entry.selection_present()
        # Typing replaces the whole path, as it was chosen.
        dialog.entry.delete(0, "end")
        dialog.entry.insert(0, target)
        wait_out(app, 0.1)
        shot(app, out, "%s_dialog-save-song-list-typed" % tag)
        dialog.entry.event_generate("<Return>")

    def answered(name, key, tries=200):
        """The dialog that ends the work (one button: it says how it ended), shot and measured once it shows, then
        answered with Enter; the dialog of work under way before it shot once. Each look schedules the next before it
        runs the window (a shot does): the dialog that ends the work opens its own wait inside whatever runs the window
        when the work ends, and the next look, already scheduled, answers it there."""
        def look(left=tries):
            dialog = app.dialog
            final = dialog is not None and not dialog.progress and len(dialog.buttons) == 1
            if not final:
                if left:
                    app.root.after(100, lambda: look(left - 1))
                else:
                    problems.append("%s: no dialog said how %s ended" % (tag, name))
                if dialog is not None and dialog.progress and name + "-working" not in seen:
                    seen[name + "-working"] = True
                    shot(app, out, "%s_dialog-%s-working" % (tag, name))
                    if not dialog.closed:
                        problems.extend("%s_dialog-%s-working: %s" % (tag, name, p) for p in dialog.layout_problems())
                return
            if key in seen:
                # Answered already, by a look that ran inside this one's shot.
                return
            seen[key] = dialog.message
            wait_out(app, 0.4)
            if dialog.closed:
                return
            shot(app, out, "%s_dialog-%s" % (tag, name))
            problems.extend("%s_dialog-%s: %s" % (tag, name, p) for p in dialog.layout_problems())
            dialog.canvas.event_generate("<Return>")
        app.root.after(200, look)

    app.root.after(300, path_dialog)
    answered("song-list-saved", "saved")
    button(app, w("game.songlist.save")).press()
    settle(app, 30)
    if seen.get("start", "").rsplit(os.sep, 1)[-1] != songlist.NAME or not seen.get("chosen"):
        problems.append("%s: the Save dialog did not start on the desktop's %s, chosen whole: %r" % (tag, songlist.NAME, seen))
    try:
        held = songlist.look(target)["songs"]
    except Exception as e:  # noqa: BLE001  (said as a problem of this check)
        held = "not saved: %s" % e
    if held != 8 or seen.get("saved") != w("songlist.saved", songs=8):
        problems.append("%s: the song list saved holds %r songs, said %r" % (tag, held, seen.get("saved")))
    # Signed in as another server's admin: Send shows; with no network here the send fails, said in a dialog.
    app.state.mode, app.state.server_url = "server", "http://192.168.0.10:4730"
    app.state.remote = {"game": "192.168.0.10:4725", "version": "0.3.0", "login_id": "BOSS", "dj_name": "BOSS",
                        "card": "2" * 20, "token": "t", "is_admin": True}
    app.refresh_checks()
    app.go("game")
    settle(app)

    def ask_send():
        dialog = app.dialog
        if dialog is None:
            problems.append("%s: Send the song list asked nothing first" % tag)
            return
        wait_out(app, 0.4)
        shot(app, out, "%s_dialog-send-song-list" % tag)
        problems.extend("%s_dialog-send-song-list: %s" % (tag, p) for p in dialog.layout_problems())
        dialog.canvas.event_generate("<Return>")

    app.root.after(300, ask_send)
    answered("song-list-not-sent", "not_sent")
    button(app, w("game.songlist.send")).press()
    settle(app, 30)
    if seen.get("not_sent") != w("songlist.not_sent"):
        problems.append("%s: a send that could not reach the server was said as %r" % (tag, seen.get("not_sent")))
    app.state.mode, app.state.remote = "this_pc", None
    app.refresh_checks()


def stopped_check(out, tag, lang, problems):
    """The windows of their own the launcher shows when its window is not there: an error nothing caught
    (main._stopped, installer.run), and PLAY from the desktop shortcut that cannot go (main._play_failed)."""
    from opendmt3.client import dialogs, i18n
    w = i18n.Words(lang)
    for name, args in (
            ("launcher-stopped", (w("crash.title"), w("crash.message"),
                                  w("crash.detail", error="A made-up error that stopped the launcher at start.",
                                    path="C:\\Users\\player\\AppData\\Roaming\\openDMT3\\logs\\launcher.log"),
                                  [(w("crash.logs"), "logs", "neutral"), (w("common.close"), "close", "info")])),
            # As main._play_failed makes it: what is so, why (the line that stops PLAY, in its own words), and the way
            # into the launcher.
            ("play-blocked", (w("quick.failed.title"), w("quick.failed"),
                              "%s\n%s" % (w.error(g.GameError(
                                  "no client data (the game's PC client and its files) at or below "
                                  "D:\\Games\\TECHNIKA 3 (moved)", "error.game.no_folder",
                                  path="D:\\Games\\TECHNIKA 3 (moved)")), w("quick.failed.detail")),
                              [(w("common.close"), "close", "neutral"), (w("quick.failed.open"), "open", "info")])),
            ("installer-stopped", (w("crash.title"), w("crash.message"),
                                   w("crash.detail", error="A made-up error that stopped the installer.",
                                     path="C:\\Users\\player\\AppData\\Local\\Temp\\openDMT3-setup.log"),
                                   [(w("common.close"), "close", "info")]))):
        # The kind each one has in the product: the ready check's stop is a warning, the others errors.
        kind = "warn" if name == "play-blocked" else "error"
        root, dialog = dialogs.window(kind, *args, default=len(args[3]) - 1, cancel="close", language=lang)
        end = time.time() + 1.0
        while time.time() < end:
            root.update()
            time.sleep(0.02)

        class Holder:
            pass
        holder = Holder()
        holder.root = root
        shot(holder, out, "%s_%s" % (tag, name), root=root)
        problems.extend("%s_%s: %s" % (tag, name, p) for p in dialog.layout_problems())
        dialog.canvas.event_generate("<Escape>")
        root.update()
        if not dialog.closed:
            problems.append("%s: Esc did not close the %s window" % (tag, name))


def standalone_check(out, tag, lang, problems):
    """The window the launcher shows when it cannot read its settings (main._cannot_start), in the language
    Windows is shown in (here the run's own)."""
    from opendmt3.client import dialogs, i18n
    w = i18n.Words(lang)
    root, dialog = dialogs.window("error", w("start.title"), w("start.broken"),
                                  w("start.broken.detail",
                                    path="C:\\Users\\player\\AppData\\Roaming\\openDMT3\\launcher.json"),
                                  [(w("common.close"), "close", "neutral"), (w("start.over"), "reset", "warn")],
                                  default=1, cancel="close", language=lang)
    end = time.time() + 1.0
    while time.time() < end:
        root.update()
        time.sleep(0.02)

    class Holder:
        pass
    holder = Holder()
    holder.root = root
    shot(holder, out, "%s_cannot-start" % tag, root=root)
    problems.extend("%s_cannot-start: %s" % (tag, p) for p in dialog.layout_problems())
    dialog.canvas.event_generate("<Escape>")
    root.update()
    # The answer starts as "close" (the cancel value): only a closed dialog proves Esc answered it.
    if not dialog.closed or dialog.result != "close":
        problems.append("%s: Esc did not answer the start-up dialog (closed %r, answer %r)"
                        % (tag, dialog.closed, dialog.result))


def installer_check(out, tag, problems):
    """The installer's dialogs (opendmt3/client/installer.py) around a stand-in for Velopack's setup: every question, the
    work under way, the end, and a failure. Velopack itself runs in the Wine tests (tests/e2e/windows)."""
    from opendmt3 import __version__
    from opendmt3.client import installer
    home = tempfile.mkdtemp()
    os.environ["LOCALAPPDATA"] = home
    app = os.path.join(home, "openDMT3")
    os.makedirs(os.path.join(app, "current"))
    # The installed launcher's stub: here a script that only leaves a mark that it ran.
    stub = os.path.join(app, "openDMT3.exe")
    if sys.platform == "win32":
        # Windows starts only a real program under that name: the mark is left where the stub would be started.
        installer.start_launcher = lambda: open(os.path.join(home, "started"), "w").close()
    else:
        with open(stub, "w") as f:
            f.write("#!/bin/sh\ntouch '%s/started'\n" % home)
        os.chmod(stub, 0o755)

    def fake_setup(code, version):
        """A stand-in for Velopack's setup that takes a second, then installs `version` or fails."""
        if sys.platform == "win32":
            # Windows runs a .cmd by that name; it hands its arguments to this Python, which does the same work.
            helper = os.path.join(home, "setup-%d.py" % code)
            with open(helper, "w") as f:
                f.write("import sys, time\ntime.sleep(1)\n")
                if code == 0:
                    f.write("open(%r, 'w').write('<version>%s</version>')\n" % (os.path.join(app, "current", "sq.version"),
                                                                               version))
                else:
                    f.write("open(sys.argv[3], 'a').write('[12:00:01] [ERROR] Not enough space on the disk.\\n')\n")
                f.write("sys.exit(%d)\n" % code)
            path = os.path.join(home, "setup-%d.cmd" % code)
            with open(path, "w") as f:
                f.write('@"%s" "%s" %%*\r\n@exit /b %%errorlevel%%\r\n' % (sys.executable, helper))
            os.environ["OPENDMT3_VELOPACK_SETUP"] = path
            return
        path = os.path.join(home, "setup-%d.sh" % code)
        with open(path, "w") as f:
            f.write("#!/bin/sh\nsleep 1\n")
            if code == 0:
                f.write("printf '<version>%s</version>' > '%s/current/sq.version'\n" % (version, app))
            else:
                f.write("echo '[12:00:01] [ERROR] Not enough space on the disk.' >> \"$3\"\n")
            f.write("exit %d\n" % code)
        os.chmod(path, 0o755)
        os.environ["OPENDMT3_VELOPACK_SETUP"] = path

    def installed(version):
        sq = os.path.join(app, "current", "sq.version")
        if version is None:
            if os.path.exists(sq):
                os.remove(sq)
        else:
            with open(sq, "w") as f:
                f.write("<version>%s</version>" % version)

    def run_until(inst, seconds, until=lambda: False):
        end = time.time() + seconds
        while time.time() < end and not until():
            try:
                inst.root.update()
            except Exception:  # noqa: BLE001  (the window closed itself)
                return
            time.sleep(0.02)

    class Shot:
        def __init__(self, root):
            self.root = root

    for name, have, running in (("fresh", None, False), ("update", "0.4.1", True), ("same", __version__, False),
                                ("newer", "9.0.0", False)):
        installed(have)
        installer.launcher_open = lambda running=running: running
        inst = installer.Installer()
        run_until(inst, 0.6)
        shot(Shot(inst.root), out, "%s_setup-%s" % (tag, name), root=inst.root)
        problems.extend("%s_setup-%s: %s" % (tag, name, p) for p in inst.dialog.layout_problems())
        inst.dialog.canvas.event_generate("<Escape>")
        run_until(inst, 0.3)
    # Install from nothing, with an installer a server's site handed out (preset.py): the question says which
    # server it is set up for; then the work under way, the end, the launcher started, and the server left for it.
    from opendmt3.core import preset
    from opendmt3.client import state as launcher_state
    handed = os.path.join(home, "openDMT3-win-Setup.exe")
    with open(handed, "wb") as f:
        f.write(b"MZ stand-in" + preset.tail("http://192.168.0.10:4730", "192.168.0.10:4730"))
    os.environ["OPENDMT3_SETUP_FILE"] = handed
    installed(None)
    fake_setup(0, __version__)
    inst = installer.Installer()
    run_until(inst, 0.5)
    shot(Shot(inst.root), out, "%s_setup-from-a-server" % tag, root=inst.root)
    problems.extend("%s_setup-from-a-server: %s" % (tag, p) for p in inst.dialog.layout_problems())
    if inst.words("setup.for", name="192.168.0.10:4730") not in (inst.dialog.detail or ""):
        problems.append("%s: the installer did not say the server it is set up for: %r" % (tag, inst.dialog.detail))
    inst.dialog.canvas.event_generate("<Return>")
    run_until(inst, 0.5)
    shot(Shot(inst.root), out, "%s_setup-working" % tag, root=inst.root)
    problems.extend("%s_setup-working: %s" % (tag, p) for p in inst.dialog.layout_problems())
    inst.dialog.canvas.event_generate("<Escape>")
    run_until(inst, 1.2, until=lambda: inst.process.poll() is not None)
    run_until(inst, 0.4)
    shot(Shot(inst.root), out, "%s_setup-done" % tag, root=inst.root)
    run_until(inst, 2.0)
    if not os.path.exists(os.path.join(home, "started")):
        problems.append("%s: the installer did not start the launcher" % tag)
    if installer.installed_version() != __version__:
        problems.append("%s: the stand-in setup did not install" % tag)
    if not os.path.isfile(os.path.join(launcher_state.config_dir(), preset.FILE_NAME)):
        problems.append("%s: the installer did not leave its server for the launcher" % tag)
    os.environ.pop("OPENDMT3_SETUP_FILE", None)
    preset.take(launcher_state.config_dir())
    # A failure: Velopack's last error line and where the log is.
    installed(None)
    fake_setup(1, __version__)
    inst = installer.Installer()
    run_until(inst, 0.5)
    inst.dialog.canvas.event_generate("<Return>")
    run_until(inst, 2.5, until=lambda: inst.process is not None and inst.process.poll() is not None)
    run_until(inst, 0.6)
    shot(Shot(inst.root), out, "%s_setup-failed" % tag, root=inst.root)
    problems.extend("%s_setup-failed: %s" % (tag, p) for p in inst.dialog.layout_problems())
    if "Not enough space" not in (inst.dialog.detail or ""):
        problems.append("%s: the failure did not show Velopack's error: %r" % (tag, inst.dialog.detail))
    inst.root.destroy()
    # Velopack's setup missing (an antivirus took it): a failure with no log to open, and Close works.
    os.environ["OPENDMT3_VELOPACK_SETUP"] = os.path.join(home, "missing.exe")
    inst = installer.Installer()
    run_until(inst, 0.5)
    inst.dialog.canvas.event_generate("<Return>")
    run_until(inst, 0.6)
    shot(Shot(inst.root), out, "%s_setup-missing" % tag, root=inst.root)
    words = [b[1] for b in inst.dialog.buttons]
    if words != ["close"]:
        problems.append("%s: a failure without a log offers %r" % (tag, words))
    inst.dialog.canvas.event_generate("<Return>")
    run_until(inst, 0.3)
    # A game running on this PC: the installer waits instead of closing the launcher and its server.
    installed("0.4.1")
    installer.game_running = lambda: True
    inst = installer.Installer()
    run_until(inst, 0.5)
    shot(Shot(inst.root), out, "%s_setup-game-running" % tag, root=inst.root)
    problems.extend("%s_setup-game-running: %s" % (tag, p) for p in inst.dialog.layout_problems())
    if inst.dialog.message != inst.words("setup.game"):
        problems.append("%s: the installer did not wait for the game: %r" % (tag, inst.dialog.message))
    inst.root.destroy()


# ------------------------------------------------------------------------------- taking the game in

# Where the made-up game folders and archives are, by the names EXPECTED gives them: the home folder's Desktop and
# Downloads on Linux, the ones Windows names on Windows (main() sets them).
PLACES = {}
# What each path made up for the search must read as on its card: (where it is, below its place; its state).
EXPECTED = (
    ("Desktop/TECHNIKA 3/unpacked/game", "ready"),
    ("Desktop/Unfinished copy/game", "not_here"),
    ("Desktop/Venue cabinet/game", "not_here"),
    ("Desktop/Version modified/game", "ready"),
    ("Desktop/Was played before/game", "ready"),
    ("Desktop/Without charts/game", "not_here"),
    ("Desktop/Without previews/game", "ready"),
    ("Desktop/Without tutorial/game", "not_here"),
    ("Desktop/Without videos/game", "ready"),
    ("Downloads/technika3-copy.7z", "unpack"),
    ("Downloads/technika3-zip.zip", "unpack"),
    ("Downloads/technika3-parts.7z.001", "unpack"),
    ("Downloads/djmax-locked.7z", "unpack"),
    ("Downloads/dmt3-wrapped.zip", "unpack"),
    ("Downloads/parts/technika3-gap.7z.001", "not_here"),
    ("Downloads/technika3-broken.7z", "not_here"),
)


def card_of(app, path):
    """The card of a path on the page (client/cards.py), the way a person finds it."""
    from opendmt3.client import cards
    for w in widgets_of(app.root):
        if isinstance(w, cards.Card) and os.path.normcase(w.found.path) == os.path.normcase(path) and w.winfo_ismapped():
            return w
    raise AssertionError("no card for %s" % path)


def button_in(widget, words):
    """The button with these words inside one card."""
    for w in widgets_of(widget):
        if isinstance(w, widgets.Button) and w.words == words:
            return w
    raise AssertionError("no button %r in the card" % words)


def placed(rel):
    """The real path of a made-up path EXPECTED names ("Desktop/...", "Downloads/...")."""
    first, *rest = rel.split("/")
    return os.path.join(PLACES[first], *rest)


def unplaced(path):
    """A path the search found, said as EXPECTED says it (below its place), or whole when it is in none of them."""
    for name, base in PLACES.items():
        inside = os.path.relpath(path, base) if os.path.splitdrive(path)[0] == os.path.splitdrive(base)[0] else ".."
        if not inside.startswith(".."):
            return "/".join([name] + inside.split(os.sep))
    return path


def disc_check(app, out, tag, made, problems):
    """DISC CHECK after the search: every form made up above is on the list with the state it must have, the best
    folder is the one in use, and the list is shot from its top to its end."""
    guide = app.guide
    items = {os.path.normcase(f.path): f for f in guide.found.items or []}
    for rel, state in EXPECTED:
        path = os.path.normcase(placed(rel))
        found = items.get(path)
        if found is None:
            problems.append("%s: DISC CHECK did not list %s" % (tag, rel))
        elif found.state != state:
            problems.append("%s: %s reads %s, not %s (%s)" % (tag, rel, found.state, state,
                                                             found.sentence(app.words)))
    if len(items) != len(EXPECTED):
        problems.append("%s: DISC CHECK lists %d paths, %d were made" % (tag, len(items), len(EXPECTED)))
    for found in items.values():
        if found.kind == "archive" and found.songs is not None:
            # An archive the search found is said from its listing alone: counting its songs took files out of it.
            problems.append("%s: %s was found and its songs counted" % (tag, unplaced(found.path)))
    # The best folder is the one in use: one that plays with the original PC client (not the modified one).
    using = items.get(os.path.normcase(app.state.game_folder or ""))
    if using is None or using.state != "ready" or using.client != "original":
        problems.append("%s: the folder in use is %r, not one with the original PC client" % (tag, app.state.game_folder))
    # The rest of the screens are made with the first folder.
    app.set_folder(made["root"])
    guide.found.paint()
    settle(app)
    # The list from its top to its end, a screen at a time.
    area = guide.body.canvas
    for i, at in enumerate((0.0, 0.5, 1.0)):
        area.yview_moveto(at)
        wait_out(app, 0.15)
        name = "%s_guide2-list%d" % (tag, i + 1)
        shot(app, out, name)
        measure(app, name, problems)
    guide.body.to_top()
    # Every card's state in its own words: what --inspect says too.
    with open(os.path.join(out, "lines-%s.txt" % tag), "w", encoding="utf-8") as f:
        for found in guide.found.items or []:
            f.write("%-9s %s\n          %s\n" % (found.state, unplaced(found.path), found.sentence(app.words)))


def drive(app, out, tag, start, steps, problems, seconds=40):
    """Press `start` and answer the dialogs it opens one after another, as a person would. steps are (shot name, the
    dialog's message, answer(dialog), optional): each new dialog is matched to the next step with its message, shot
    and measured, then answered. An optional step may pass unseen (a check over before it could be shot)."""
    state = {"i": 0, "seen": None, "tries": 0}

    def poll():
        if state["i"] >= len(steps):
            return
        dialog = app.dialog
        if dialog is None or dialog is state["seen"] or dialog.closed:
            state["tries"] += 1
            if state["tries"] < seconds * 20:
                app.root.after(50, poll)
            else:
                problems.append("%s: no dialog came for %s" % (tag, steps[state["i"]][0]))
            return
        state["seen"], state["tries"] = dialog, 0
        j = state["i"]
        # Optional steps the dialogs went past: only those may be skipped.
        while j < len(steps) and steps[j][1] != dialog.message and steps[j][3]:
            j += 1
        if j >= len(steps) or steps[j][1] != dialog.message:
            problems.append("%s: %s expected, a dialog saying %r came" % (tag, steps[state["i"]][0], dialog.message))
            state["i"] = len(steps)
            dialog.close(dialog.cancel_value)
            return
        name, _, answer, optional = steps[j]
        state["i"] = j + 1
        wait_out(app, 0.5)
        if dialog.closed:
            # Over before it could be shot (a quick check): only an optional step may pass so.
            if not optional:
                problems.append("%s: %s closed before it could be shot" % (tag, name))
            app.root.after(50, poll)
            return
        shot(app, out, "%s_%s" % (tag, name))
        if dialog.closed:
            # Over while it was shot (a quick check ends by itself, as a password's did under Wine): its drawing is
            # gone, so there is nothing to measure or answer, and only an optional step may end so. Measuring it
            # anyway raised in this timer and the steps after it were never answered: the run stood still.
            if not optional:
                problems.append("%s: %s closed while it was shot" % (tag, name))
            app.root.after(50, poll)
            return
        problems.extend("%s_%s: %s" % (tag, name, p) for p in dialog.layout_problems())
        answer(dialog)
        app.root.after(50, poll)

    app.root.after(100, poll)
    start()
    missing = [step[0] for step in steps[state["i"]:] if not step[3]]
    if missing:
        problems.append("%s: the dialogs ended before %s" % (tag, ", ".join(missing)))


def type_in(dialog, words):
    """Type into a dialog's field (a password) and press its main button with Enter."""
    field = dialog.entry()
    field.delete(0, "end")
    field.insert(0, words)
    field.event_generate("<Return>")


def unpack_check(app, out, tag, made, problems):
    """Unpack... from the cards, as a person goes through it: where it goes and the room; the work under way (held,
    to be shot) with Stop asked and Keep unpacking; the end; a password asked, a password that does not open the
    archive, the right one; an unpacking that fails; and a real one, whose game folder is listed ready and used."""
    import threading
    from opendmt3.client import intake, unpack
    w = app.words
    guide = app.guide
    enter = lambda d: d.canvas.event_generate("<Return>")  # noqa: E731  (an answer, as short as the step it is)
    escape = lambda d: d.canvas.event_generate("<Escape>")  # noqa: E731
    real = unpack.Unpacking
    gate = threading.Event()

    class Held:
        """The work stood in for: it says how far it is, then waits until the shots are taken."""

        def __init__(self, archive, parent, password=None, progress=None, cancel=None):
            self.progress, self.cancel = progress, cancel

        def run(self):
            self.progress(0.42, 260)
            gate.wait(30)
            if self.cancel.is_set():
                raise unpack.Stopped()
            return made["root"]

    def keep(dialog):
        # Keep unpacking: the work goes on under a new progress dialog.
        click_button(dialog, 0)

    def end_work(dialog):
        # The work ends (its gate opens) and its dialog closes by itself.
        gate.set()

    asked, working, done = w("unpack.ask"), w("unpack.working"), w("unpack.done")
    try:
        unpack.Unpacking = Held
        drive(app, out, tag, button_in(card_of(app, made["archive"]), w("intake.unpack")).press, [
            ("unpack-ask", asked, enter, False),
            ("unpack-working", working, lambda d: click_button(d, 0), False),
            ("unpack-stop", w("unpack.stop.ask"), keep, False),
            ("unpack-working-again", working, end_work, False),
            ("unpack-done", done, enter, False),
        ], problems)
        gate.clear()
        settle(app, 10)

        class Fails(Held):
            def run(self):
                raise intake.said("error.source.damaged")

        unpack.Unpacking = Fails
        drive(app, out, tag, button_in(card_of(app, made["archive"]), w("intake.unpack")).press, [
            ("unpack-ask-again", asked, enter, False),
            ("unpack-failed", w("unpack.failed"), enter, False),
        ], problems)
    finally:
        unpack.Unpacking = real
    settle(app, 10)
    # The password: asked first, said when it does not open the archive, then the room asked as for any archive.
    locked, checking = w.error(intake.said("error.source.password")), w("unpack.checking")
    drive(app, out, tag, button_in(card_of(app, made["locked"]), w("intake.unpack")).press, [
        ("unpack-password", locked, lambda d: type_in(d, "not-it"), False),
        ("unpack-password-checking", checking, lambda d: None, True),
        ("unpack-password-again", locked, lambda d: type_in(d, "made-up-1"), False),
        ("unpack-password-checking-again", checking, lambda d: None, True),
        ("unpack-ask-unlocked", asked, escape, False),
    ], problems, seconds=60)
    settle(app, 10)
    # A real unpacking, through the official 7-Zip: the new game folder is listed ready, and used.
    drive(app, out, tag, button_in(card_of(app, made["archive"]), w("intake.unpack")).press, [
        ("unpack-ask-real", asked, enter, False),
        ("unpack-working-real", working, lambda d: None, True),
        ("unpack-done-real", done, enter, False),
    ], problems, seconds=60)
    settle(app, 20)
    unpacked = os.path.join(os.path.dirname(made["archive"]), "technika3-copy")
    found = next((f for f in app.guide.found.items or [] if os.path.normcase(f.path) == os.path.normcase(unpacked)
                  or os.path.normcase(f.root or "") == os.path.normcase(os.path.join(unpacked, "TECHNIKA 3"))), None)
    if found is None or found.state != intake.READY:
        problems.append("%s: the unpacked game folder is not listed ready (%r)" % (tag, found and found.state))
    elif os.path.normcase(app.state.game_folder or "") != os.path.normcase(found.root):
        problems.append("%s: the unpacked game folder is not the one in use" % tag)
    leftovers = [n for n in os.listdir(os.path.dirname(made["archive"])) if n.startswith(unpack.WORK_PREFIX)]
    if leftovers:
        problems.append("%s: the unpacking left %s behind" % (tag, leftovers))
    guide.body.to_top()
    settle(app)
    shot(app, out, "%s_guide2-unpacked" % tag)
    measure(app, "%s_guide2-unpacked" % tag, problems)
    # Back to the folder the rest of the screens are made with.
    app.set_folder(made["root"])
    guide.found.paint()
    settle(app)


def game_page_check(app, out, tag, problems):
    """The Game page's card: the folder in use, the list Change... opens under it, and no folder chosen yet."""
    from opendmt3.client import find
    w = app.words
    app.go("game")
    settle(app, 10)
    button(app, w("game.change")).press()
    settle(app, 40)
    for name, at in (("game-change", 0.0), ("game-change-end", 1.0)):
        app.body.canvas.yview_moveto(at)
        wait_out(app, 0.15)
        shot(app, out, "%s_%s" % (tag, name))
        measure(app, "%s_%s" % (tag, name), problems)
    button(app, w("game.change")).press()
    settle(app)
    # No folder chosen, and none found: the card says so, and the list under it says where to choose one.
    kept, paths = app.state.game_folder, find.paths
    find.paths = lambda where=None, depth=None, cancel=None: iter(())
    try:
        app.state.game_folder = None
        app.folder_look = None
        # As the launcher does when the folder changes: the ready check made again, so the status line and PLAY are
        # those of this state (the shot once showed "Ready to play" and PLAY lit over "no game folder chosen").
        app.refresh_checks()
        app.go("game")
        settle(app, 10)
        shot(app, out, "%s_game-none" % tag)
        measure(app, "%s_game-none" % tag, problems)
        if app.status_text != w("status.choose_folder") or app.ready():
            problems.append("%s_game-none: with no folder the status says %r and PLAY is %s"
                            % (tag, app.status_text, "lit" if app.ready() else "off"))
    finally:
        find.paths = paths
        if app.game_list is not None:
            app.game_list.stop()
        app.game_list = None
        app.state.game_folder = kept
        app.folder_look = None
    app.refresh_checks()
    app.go("game")
    settle(app, 10)


def labels(app):
    """The words of every label showing on the page, as a person reads them."""
    return [x.cget("text") for x in widgets_of(app.root)
            if x.winfo_class() == "Label" and x.winfo_ismapped() and x.cget("text")]


def play_states_check(app, out, tag, made, problems):
    """The Play page in the states a first walk through the launcher meets and the pages' own run never showed: no
    folder chosen, the cabinet's client, a copy without the file with the tutorial (the game would stop), a copy whose
    song list was cut short, a modified PC client, a guest and a player on this PC, offline, and another server with
    nobody signed in. Each is shot and measured, and held to what the page must say there: why PLAY cannot go, under
    the line that stops it and on the status line (in the player's language), the way to the page that fixes it by
    that page's name, and the How to play line of who plays."""
    w = app.words
    desktop = os.path.dirname(os.path.dirname(os.path.dirname(made["root"])))
    kept = (app.state.game_folder, app.state.mode, app.state.player, app.state.server_url, app.state.remote)

    def show(name, folder, mode="this_pc", player="NOVA", remote=None):
        app.state.game_folder, app.state.mode, app.state.player = folder, mode, player
        app.state.server_url, app.state.remote = ("http://192.168.0.10:4730", remote) if mode == "server" else (None, None)
        app.discs = None
        app.refresh_checks()
        app.go("play")
        settle(app, 10)
        shot(app, out, "%s_play-%s" % (tag, name))
        measure(app, "%s_play-%s" % (tag, name), problems)
        return labels(app)

    def held(name, said, *wanted, ready=False, status=None, absent=()):
        """Each of `wanted` is a label on the page, none of `absent` is; PLAY is lit or not; the status line."""
        for words in wanted:
            if words not in said:
                problems.append("%s_play-%s: the page does not say %r" % (tag, name, words))
        for words in absent:
            if words in said:
                problems.append("%s_play-%s: the page says %r" % (tag, name, words))
        if app.ready() != ready:
            problems.append("%s_play-%s: PLAY is %s" % (tag, name, "lit" if app.ready() else "off"))
        if status is not None and app.status_text != status:
            problems.append("%s_play-%s: the status line says %r, not %r" % (tag, name, app.status_text, status))

    try:
        # No folder chosen yet: the line's own reason, the way to the Game page by its name, the status line.
        said = show("no-folder", None)
        held("no-folder", said, w.error(g.GameError("no client data chosen yet", "error.game.not_chosen")),
             w("play.go.game") + " \u203a", status=w("status.choose_folder"))
        # The cabinet's client: the card's own sentence under the line and on the status line; the link leads to the
        # Game page, where another folder is chosen (it once led to Help, which said the same list again).
        cabinet = w.error(g.GameError("The cabinet's client: does not work here, the PC client is needed.",
                                      "error.game.cabinet_client"))
        said = show("cabinet", os.path.join(desktop, "Venue cabinet", "game"))
        held("cabinet", said, cabinet, w("play.go.game") + " \u203a", status=cabinet)
        # A copy without the file with the tutorial: what the game would do, and the one thing to do.
        said = show("no-tutorial", os.path.join(desktop, "Without tutorial", "game"))
        held("no-tutorial", said, w("intake.line.no_tutorial"), w("play.go.game") + " \u203a",
             status=w("intake.line.no_tutorial"))
        # A copy whose song list was cut short while it was copied: said with its reason, never a bare line.
        said = show("damaged", os.path.join(desktop, "Unfinished copy", "game"))
        held("damaged", said, w("play.go.game") + " \u203a")
        if app.status_text not in said:
            # The status line's reason is the one under the line that stops PLAY.
            problems.append("%s_play-damaged: the page does not say why PLAY cannot go (%r)" % (tag, app.status_text))
        # A modified PC client plays: the note of what it plays without, under its line.
        said = show("modified", os.path.join(desktop, "Version modified", "game"))
        held("modified", said, w("intake.line.modified"), ready=True)
        # A player's card goes in: the game logs in by itself; a guest presses NO ID CARD, and nothing is recorded.
        said = show("player", made["root"])
        held("player", said, w("play.how.3.card"), w("play.how.4"), w("play.who.hint"), ready=True,
             absent=(w("play.how.3"), w("play.who.hint.guest")))
        said = show("guest", made["root"], player=None)
        held("guest", said, w("play.how.3"), w("play.how.4"), w("play.who.hint.guest"), ready=True,
             absent=(w("play.how.3.card"), w("play.who.hint")))
        # Offline: everyone a guest, and where that is changed.
        said = show("offline", made["root"], mode="offline", player=None)
        held("offline", said, w("play.offline"), w("play.how.3"), ready=True)
        # Another server, connected, nobody signed in: nothing is broken, the status line says to sign in.
        said = show("server-signed-out", made["root"], mode="server", player=None,
                    remote={"game": "192.168.0.10:4725", "version": "0.3.0"})
        held("server-signed-out", said, w("play.who.signin"), w("check.remote"), w("play.go.online") + " \u203a",
             status=w("status.sign_in_first"))
        # A guest has no records: the Records page says so, with the way to the Play page where a player is chosen.
        app.state.game_folder, app.state.mode, app.state.player = made["root"], "this_pc", None
        app.state.server_url, app.state.remote = None, None
        app.go("records")
        settle(app, 10)
        shot(app, out, "%s_records-guest" % tag)
        measure(app, "%s_records-guest" % tag, problems)
        try:
            button(app, w("nav.play"))
        except AssertionError:
            problems.append("%s_records-guest: no way to the Play page for a guest" % tag)
    finally:
        app.state.game_folder, app.state.mode, app.state.player, app.state.server_url, app.state.remote = kept
        app.discs = None
        app.refresh_checks()
        app.load_discs()
        app.go("play")
        settle(app, 10)


# The longest kind of title a session lists: it wraps over lines in a narrow card.
LONG_TITLE = "An Extremely Long Made-up Song Title That Wraps Over Lines (Extended Mix)"


def play_fits_check(app, out, tag, problems):
    """PLAY, the page the launcher opens on, shows whole at the size the launcher opens at (app._size_window: 1180x760
    at 100 %, never more than 92 % of the screen), in the states a player meets there: no session yet, after a
    session of three cleared stages (the most the page lists) with long titles, and after a crash.

    After such a session the page ran 147 to 276 px under the bottom bar with Windows' fonts (100 to 200 %), and 152
    to 170 in this Linux run: it scrolled, but a player saw My records cut by the bar and nothing under it. Where the
    screen leaves the window less than the launcher's full size (150 % on a 1080-line screen), the page may scroll
    there: shot and measured as every page is, not held to fit."""
    back = app.root.geometry()
    kept = (app.state.mode, app.state.player, app.state.last_session)
    # The window as the launcher opens it on this screen, and the launcher's full size at this scale.
    app._size_window()
    settle(app)
    size = (app.root.winfo_width(), app.root.winfo_height())
    whole = size[0] >= app.ui.px(1180) and size[1] >= app.ui.px(760)
    plays = [{"title": LONG_TITLE, "pattern": 3, "score": 987654},
             {"title": "가나다라마바사아자차카타파하", "pattern": 1, "score": 4530},
             {"title": "Made-up Song 7", "pattern": 2, "score": 301220}]
    sessions = (("no-session", None),
                ("three-plays", {"seconds": 754, "exit_code": 0, "dumps": 0, "crashed": False, "plays": plays}),
                ("crashed", {"seconds": 42, "exit_code": -1073741819, "dumps": 1, "crashed": True, "plays": []}))
    try:
        # A player of this PC: the page shows the most for one (their records' button with its line).
        app.state.mode, app.state.player = "this_pc", "NOVA"
        for name, session in sessions:
            app.state.last_session = session
            app.go("play")
            settle(app)
            label = "%s_play-fits-%s" % (tag, name)
            shot(app, out, label)
            measure(app, label, problems)
            # The page's height past the area that shows it, once what was just drawn is laid out.
            app.root.update_idletasks()
            over = app.body.inner.winfo_height() - app.body.canvas.winfo_height()
            if whole:
                FITS.append(label)
                if over > 1:
                    problems.append("%s: PLAY does not show whole at the launcher's own size %dx%d: %d px under "
                                    "the bottom bar" % (label, size[0], size[1], over))
    finally:
        app.state.mode, app.state.player, app.state.last_session = kept
        app.root.geometry(back)
        settle(app)


def at_smallest(app, out, name, problems):
    """The screen on show again at the smallest size the window takes (its minsize, which a person dragging its edge
    stops at): shot and measured there, then the window back at the size it had."""
    back = app.root.geometry()
    app.root.geometry("%dx%d+0+0" % tuple(app.root.minsize()))
    settle(app)
    shot(app, out, name + "-smallest")
    measure(app, name + "-smallest", problems)
    app.root.geometry(back)
    settle(app)


def planted_check(app, out, tag, problems):
    """The check for hidden content (hidden) tried on a page made up to need it, at this run's own fonts and scale:
    forty made-up lines, taller than any window, where the page goes. In the page's scroll area they scroll, and
    nothing may be said; in a scroll area that cannot scroll (its region cut to what shows, so no scroll bar) the
    lines below must be said hidden; in a plain box where the scroll area stands (a page built without
    widgets.ScrollArea) the lines its box has no room for must be said too. A check that missed either would pass a
    page whose foot no player can reach."""
    import tkinter as tk
    from opendmt3.client import theme
    area = app.body

    def lines(parent):
        # The made-up page: plain lines in the page's text, one under another.
        for i in range(40):
            tk.Label(parent, text="Made-up line %d of a page taller than the window" % (i + 1), font=app.fonts.body,
                     fg=theme.TEXT, bg=theme.BG, anchor="w").pack(fill="x")

    def found(name):
        # What the check says of the made-up lines as the window is now, shot for a look; kept apart from the run's
        # problems (the rest of the window is measured on its own screens).
        app.root.update()
        said = []
        hidden(app, name, said)
        shot(app, out, name)
        return [p for p in said if "Made-up line" in p]

    app.go("play")
    settle(app)
    for child in area.inner.winfo_children():
        child.destroy()
    lines(area.inner)
    app.root.update()
    area.to_top()
    scrolls = found("%s_planted-scrolls" % tag)
    if scrolls:
        problems.append("%s: the check for hidden content said a page that scrolls is hidden: %s" % (tag, scrolls[0]))
    # The same page with its scroll region cut to the area that shows: the bar goes, and the lines below with it. The
    # content's own region comes back whenever the content frame changes size (the bar leaving widens it), so the
    # area forgets that while the cut is measured, and takes it back after.
    regrow = area.inner.bind("<Configure>")
    area.inner.unbind("<Configure>")
    try:
        area.canvas.configure(scrollregion=(0, 0, area.canvas.winfo_width(), area.canvas.winfo_height()))
        stuck = found("%s_planted-cannot-scroll" % tag)
    finally:
        area.inner.bind("<Configure>", regrow)
    if not any("hidden below with no way to scroll to it" in p for p in stuck):
        problems.append("%s: the check for hidden content missed a page that cannot scroll (%d said)"
                        % (tag, len(stuck)))
    # In a plain box where the scroll area stands: pack runs out of room and leaves the last lines off the screen.
    area.pack_forget()
    plain = tk.Frame(area.master, bg=theme.BG)
    plain.pack(fill="both", expand=True)
    lines(plain)
    boxed = found("%s_planted-no-scroll-area" % tag)
    if not any("no room left for it" in p or "cut at its foot" in p for p in boxed):
        problems.append("%s: the check for hidden content missed a page without a scroll area (%d said)"
                        % (tag, len(boxed)))
    # The window as it was: the scroll area back after the bottom bar, as _build_main packs it, and PLAY in it with
    # its scroll region the content's own again.
    plain.destroy()
    area.pack(fill="both", expand=True)
    app.go("play")
    settle(app)
    area.canvas.configure(scrollregion=area.canvas.bbox("all"))
    app.root.update()


def guide_states_check(app, out, tag, problems):
    """LOG IN in the guide on another server (not connected yet) and offline, which its own run never showed: with no
    way on, the step says what lets it go on; offline, Next is lit and nothing more is asked."""
    guide, w = app.guide, app.words
    kept = (app.state.mode, app.state.server_url, app.state.remote, app.state.player)
    try:
        app.state.mode, app.state.server_url, app.state.remote, app.state.player = "server", None, None, None
        guide.show(guide.index)
        settle(app)
        shot(app, out, "%s_guide4-server" % tag)
        measure(app, "%s_guide4-server" % tag, problems)
        if w("guide.login.need.server") not in labels(app) or guide.next_button.enabled:
            problems.append("%s_guide4-server: Next is %s and the step %s what lets it go on" % (
                tag, "lit" if guide.next_button.enabled else "off",
                "says" if w("guide.login.need.server") in labels(app) else "does not say"))
        app.state.mode = "offline"
        guide.show(guide.index)
        settle(app)
        shot(app, out, "%s_guide4-offline" % tag)
        measure(app, "%s_guide4-offline" % tag, problems)
        if not guide.next_button.enabled or w("guide.login.need") in labels(app):
            problems.append("%s_guide4-offline: offline does not let the guide go on" % tag)
    finally:
        app.state.mode, app.state.server_url, app.state.remote, app.state.player = kept
        guide.show(guide.index)
        settle(app)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--lang", default="en")
    parser.add_argument("--size", default="1180x760")
    # Every page at every window width (resize_check): once a language is enough, the widths are the same at any
    # height, so the runner asks for it at one size.
    parser.add_argument("--resize", action="store_true")
    # Every guide step and page again at the smallest size the window takes (at_smallest): the Wine run, whose one
    # size is the launcher's own, asks for it (the Linux run has a run at the smallest size of its own).
    parser.add_argument("--smallest", action="store_true")
    args = parser.parse_args()
    if not safety.on_virtual_display():
        sys.exit("refusing: this opens windows; run it through tests/e2e/ui/run.sh")
    if sys.platform == "win32":
        # As the launcher does before its first window: Windows' own pixels at any scaling, not a stretched copy.
        from opendmt3.client import main as launcher_main
        launcher_main._dpi_aware()
    os.makedirs(args.out, exist_ok=True)
    rng = random.Random(7)
    table = bytes(rng.randrange(256) for _ in range(256))
    home = tempfile.mkdtemp()
    os.environ["HOME"] = home
    os.environ["OPENDMT3_CONFIG_DIR"] = os.path.join(home, "config")
    # The game where people keep it: on the Desktop, two levels inside the folder it came in, and archives in
    # Downloads. Windows' search looks in the Desktop and Downloads Windows names (known folders, not HOME): there,
    # inside the Wine prefix of tests/e2e/ui/run_wine.sh.
    PLACES["Desktop"], PLACES["Downloads"] = os.path.join(home, "Desktop"), os.path.join(home, "Downloads")
    if sys.platform == "win32":
        from opendmt3.client import find
        for name, guid in (("Desktop", find.DESKTOP), ("Downloads", find.DOWNLOADS)):
            PLACES[name] = find.known_folder(guid)
            # A profile Wine has just made may not have them yet; Windows makes them at a first sign-in.
            os.makedirs(PLACES[name], exist_ok=True)
        # Wine's Z: is its door to the container's own files (the repository is mounted there), which no player's
        # PC has: the search looks through the profile's folders and C:, as on a PC with one drive.
        find.drives = lambda: ["C:\\"]
    desktop = PLACES["Desktop"]
    root = os.path.join(desktop, "TECHNIKA 3", "unpacked", "game")
    make_game(root, table, rng)
    stand_in(root, table)
    # Every other form the guide must tell apart, beside it and in Downloads.
    made = make_intake(desktop, PLACES["Downloads"], table, rng)
    made["root"] = root
    from opendmt3.client import state as st
    from opendmt3.client.app import LauncherApp
    problems = []
    w, h = (int(x) for x in args.size.split("x"))
    tag = "%s-%s" % (args.lang, args.size)

    # ---- the first-start guide, every step
    s = st.LauncherState()
    s.language = args.lang
    s.save()
    app = LauncherApp(s)
    app.root.geometry("%dx%d+0+0" % (w, h))
    import traceback

    def callback_error(kind, value, tb):
        problems.append("callback error: %s" % "".join(traceback.format_exception_only(kind, value)).strip())
        traceback.print_exception(kind, value, tb)

    app.root.report_callback_exception = callback_error
    guide = app.guide
    from opendmt3.client import guide as guide_module
    # Only the cards' screens (DISC CHECK, the unpacking, the Game page), or only the cards themselves (the variants'
    # comparison: DISC CHECK's list and the Game page).
    only = os.environ.get("OPENDMT3_SHOTS_ONLY", "")
    only_cards = only in ("cards", "variants")
    for i in range(len(guide_module.STEPS)):
        if only_cards and i > 1:
            break
        if i == 1:
            # DISC CHECK on a PC with nothing in the usual places, first: the step says so and where to choose one,
            # and Next waits. Then the list is made anew for the search that finds the made-up folders.
            from opendmt3.client import find, found_list
            paths, find.paths = find.paths, lambda where=None, depth=None, cancel=None: iter(())
            try:
                guide.show(1)
                settle(app, 10)
                shot(app, args.out, "%s_guide2-none" % tag)
                measure(app, "%s_guide2-none" % tag, problems)
                if app.words("guide.2.none") not in labels(app) or guide.next_button.enabled:
                    problems.append("%s_guide2-none: with nothing found the step %s so and Next is %s" % (
                        tag, "says" if app.words("guide.2.none") in labels(app) else "does not say",
                        "lit" if guide.next_button.enabled else "off"))
            finally:
                find.paths = paths
                guide.found.stop()
                guide.found = found_list.FoundList(app, on_update=guide._update_next)
        if i:
            guide.show(i)
        if i == 1:
            # The search runs on a thread, then each path found is looked at (archives by 7-Zip): wait for it all.
            settle(app, 40)
            guide.show(1)
            disc_check(app, args.out, tag, made, problems)
        settle(app)
        name = "%s_guide%d" % (tag, i + 1)
        shot(app, args.out, name)
        measure(app, name, problems)
        if args.smallest:
            at_smallest(app, args.out, name, problems)
        if i == 1 and only != "variants":
            unpack_check(app, args.out, tag, made, problems)
        if guide_module.STEPS[i] == "login":
            # Before a player is made Next is off: the step says what lets it go on.
            if app.words("guide.login.need") not in labels(app) or guide.next_button.enabled:
                problems.append("%s: LOG IN with no player does not say what lets the guide go on" % name)
            guide_states_check(app, args.out, tag, problems)
            # A player made through the form, as a person would: the list and the radio then show.
            store = app.players()
            store.create("NOVA", "pass1234", "DJ NOVA")
            store.db.close()
            guide._choose_player("NOVA")
            settle(app)
            name = "%s_guide%d-player" % (tag, i + 1)
            shot(app, args.out, name)
            measure(app, name, problems)
            if app.words("guide.login.need") in labels(app) or not guide.next_button.enabled:
                problems.append("%s: with a player chosen the guide still waits" % name)
        if i == len(guide_module.STEPS) - 1:
            # STAGE START: what PLAY makes ready by itself is one line, and how to leave the game is said here, before
            # the first PLAY.
            said = labels(app)
            for key in ("play.rest", "play.how.4"):
                if app.words(key) not in said:
                    problems.append("%s: the last step does not say %r" % (name, app.words(key)))
            if sum(1 for text in said if text.endswith("  \u00b7  " + app.words("play.will_change"))) > 1:
                # One alone is said by its name; several are the one line (they were six, each "PLAY makes it").
                problems.append("%s: the last step lists each thing PLAY makes ready" % name)
    guide.finish(play=False)
    if only_cards:
        game_page_check(app, args.out, tag, problems)
        app.root.destroy()
        return finish(args.out, tag, problems)
    # NOVA's plays over the last weeks, for the Records page (its chart and lists).
    import time as _time
    plays = app.host.records()
    try:
        store = app.players()
        nova = store.by_login("NOVA")
        store.db.close()
        # Each cleared stage in a session of a few minutes (a card login to the game's end), as the server keeps
        # them: 14 stages, 14 sessions, about an hour played (the page once showed 14 stages in 0 sessions).
        from opendmt3.server.services import activity as _activity
        sessions = _activity.Activity(plays.db)
        for n in range(14):
            at = _time.time() - n * 5 * 86400
            session = sessions.start("127.0.0.1", nova["id"], at=at - 240)
            plays.add(nova["id"], "127.0.0.1:1", n % 2, {"song": 1 + n % 4, "pattern": 1 + n % 3,
                                                        "score": 500000 + n * 31337, "counts": [0] * 7,
                                                        "raw": bytes(47)}, at=at, session_id=session)
            sessions.end(session, "127.0.0.1", at=at + 30)
    finally:
        plays.db.close()
    # The DJ card's tables as --catalog leaves them (made up: experience points and level steps only), and a
    # comment as long as the game takes: the Records page then shows a level and the comment beside the name.
    import json as _json
    from opendmt3.server.services import cards as _cards
    data_dir = os.path.dirname(app.host.path)
    with open(os.path.join(data_dir, _cards.FILE), "w") as f:
        _json.dump({"icon": [], "plate": [], "pattern": [], "points": {"1": 9},
                    "levels": [12, 42, 92, 162, 252, 362, 492, 642, 812, 1002]}, f)
    store = app.players()
    store.db.execute("UPDATE accounts SET comment = ? WHERE login_id = 'NOVA'", ("가나다라마바사아자차카타",))
    store.db.close()
    # ---- every page of the launcher
    from opendmt3.client.app import NAV
    for page in NAV:
        app.go(page)
        settle(app)
        name = "%s_%s" % (tag, page)
        shot(app, args.out, name)
        measure(app, name, problems)
        if args.smallest:
            at_smallest(app, args.out, name, problems)
    game_page_check(app, args.out, tag, problems)
    play_states_check(app, args.out, tag, made, problems)
    # The Launcher page's end: the licence and the two notice lines, as OpenDMTQ words them.
    app.go("about")
    settle(app)
    app.body.canvas.yview_moveto(1.0)
    wait_out(app, 0.15)
    shot(app, args.out, tag + "_about-notice")
    measure(app, tag + "_about-notice", problems)
    notice = [x for x in widgets_of(app.root) if x.winfo_class() == "Label" and x.cget("text") == app.words("about.notice")]
    if len(notice) != 1 or len(app.words("about.notice").split("\n")) != 2:
        problems.append("%s: the Launcher page does not show the two notice lines" % tag)
    # ---- the PLAY page after a session with cleared stages (a long title wraps beside its score)
    app.state.last_session = {"seconds": 754, "exit_code": 0, "dumps": 0, "crashed": False, "plays": [
        {"title": "An Extremely Long Made-up Song Title That Wraps Over Lines (Extended Mix)", "pattern": 3,
         "score": 987654},
        {"title": "가나다라마바사아자차카타파하", "pattern": 1, "score": 4530}]}
    app.go("play")
    settle(app)
    shot(app, args.out, tag + "_play-session")
    measure(app, tag + "_play-session", problems)
    if args.smallest:
        at_smallest(app, args.out, tag + "_play-session", problems)
    # ---- PLAY whole at the size the launcher opens at, and the check for hidden content tried on a made-up page
    play_fits_check(app, args.out, tag, problems)
    planted_check(app, args.out, tag, problems)
    # ---- another server: not connected, connected, signed in (no network: the remembered state is drawn)
    for name, url, remote_state in (
            ("server-none", None, None),
            ("server-connected", "http://192.168.0.10:4730", {"game": "192.168.0.10:4725", "version": "0.3.0"}),
            ("server-signed", "http://192.168.0.10:4730", {"game": "192.168.0.10:4725", "version": "0.3.0",
                                                          "login_id": "WWWWWWWW", "dj_name": "가나다라마바사아",
                                                          "card": "1" * 20, "token": "t"}),
            # Signed in as the server's admin: the Game page offers to send it the song list.
            ("server-admin", "http://192.168.0.10:4730", {"game": "192.168.0.10:4725", "version": "0.3.0",
                                                         "login_id": "BOSS", "dj_name": "BOSS", "card": "2" * 20,
                                                         "token": "t", "is_admin": True})):
        app.state.mode, app.state.server_url, app.state.remote = "server", url, remote_state
        app.state.save()
        # As the Online page does after a change: the ready check now has its line for the sign-in.
        app.refresh_checks()
        for page in (("online", "game") if name == "server-admin" else ("online", "play", "records")):
            app.go(page)
            settle(app)
            shot(app, args.out, "%s_%s-%s" % (tag, page, name))
            measure(app, "%s_%s-%s" % (tag, page, name), problems)
    # ---- TS-LAUNCHER-21: PLAY on another server that does not answer (no network here) stops, saying why
    app.go("play")
    settle(app)
    app.play()
    end = time.time() + 20
    while time.time() < end and app.busy:
        app.root.update()
        time.sleep(0.05)
    settle(app)
    shot(app, args.out, tag + "_play-server-down")
    measure(app, tag + "_play-server-down", problems)
    if app.status_tone != "bad" or app.session is not None:
        problems.append("PLAY on a server that does not answer: %r (%s), a game %s"
                        % (app.status_text, app.status_tone, "started" if app.session else "did not start"))
    app.state.mode = "this_pc"
    app.refresh_checks()
    # ---- TS-LAUNCHER-20: the last session ended in a crash
    app.state.last_session = {"seconds": 42, "exit_code": -1073741819, "dumps": 1, "crashed": True, "plays": []}
    app.go("play")
    settle(app)
    shot(app, args.out, tag + "_play-crashed")
    measure(app, tag + "_play-crashed", problems)
    app.state.last_session = None
    # ---- PLAY's progress look: what PLAY does until the game starts (here at the client's copy), on its track
    from opendmt3.client import getting_ready
    ready = getting_ready.Shown(app)
    ready.at("client")
    wait_out(app, 0.6)
    shot(app, args.out, tag + "_play-getting-ready")
    problems.extend("%s_play-getting-ready: %s" % (tag, p) for p in ready.dialog.layout_problems())
    if ready.dialog.fraction is None or not ready.dialog.status:
        problems.append("%s_play-getting-ready: no share on the track or no line under it" % tag)
    ready.close()
    if app.dialog is not None:
        problems.append("%s_play-getting-ready: the progress look stayed after PLAY" % tag)
    # ---- this PC's server opened to the other PCs at home (no network in the container: no home address)
    app.set_lan(True)
    settle(app, 8)
    app.go("online")
    settle(app)
    shot(app, args.out, tag + "_online-home")
    measure(app, tag + "_online-home", problems)
    # Open, with no address to reach it at: said as that on the page and on the status line, in the colour of
    # something to look at (it was green, "open to the other PCs", over a list of no address).
    if (app.words("online.home.none") not in labels(app) or app.status_tone != "warn"
            or app.status_text != app.words("online.home.open.no_address")):
        problems.append("%s_online-home: with no network address the page says %r (%s)"
                        % (tag, app.status_text, app.status_tone))
    app.set_lan(False)
    settle(app, 4)
    # ---- the screen page in window mode (the size row appears)
    app.changed("display_mode", "window")
    app.go("screen")
    settle(app)
    shot(app, args.out, tag + "_screen-window")
    measure(app, tag + "_screen-window", problems)
    # ---- the screen page with a filter that sharpens (the sharpness row appears), on top of window mode's size row,
    # so the longest form of the page is measured too
    app.changed("upscale", "fsr1")
    app.go("screen")
    settle(app)
    shot(app, args.out, tag + "_screen-sharpness")
    measure(app, tag + "_screen-sharpness", problems)
    # Back to the default, so the screens after this one look as before.
    app.changed("upscale", choices.UPSCALE_DEFAULT)
    # ---- the keyboard: a switch and a button take the focus (their rings); Space flips the switch, and back
    app.go("screen")
    settle(app)
    switch = [x for x in widgets_of(app.root) if isinstance(x, widgets.Toggle) and x.winfo_ismapped()][0]
    before = switch.value
    switch.focus_force()
    wait_out(app, 0.2)
    shot(app, args.out, tag + "_focus-switch")
    measure(app, tag + "_focus-switch", problems)
    switch.event_generate("<space>")
    wait_out(app, 0.2)
    if switch.value == before:
        problems.append("keyboard: Space did not flip the focused switch")
    switch.event_generate("<space>")
    wait_out(app, 0.2)
    pressable = [x for x in widgets_of(app.root) if isinstance(x, widgets.Button) and x.winfo_ismapped()]
    pressable[-1].focus_force()
    wait_out(app, 0.2)
    shot(app, args.out, tag + "_focus-button")
    measure(app, tag + "_focus-button", problems)
    if not pressable[-1].focused:
        problems.append("keyboard: a page button did not take the focus")
    app.root.focus_force()
    # ---- the dialogs, opened from their pages
    app.root.geometry("%dx%d+0+0" % (w, h))
    settle(app)
    dialogs_check(app, args.out, tag, problems)
    repair_check(app, args.out, tag, problems)
    remove_check(app, args.out, tag, made, problems)
    damaged_database_check(app, args.out, tag, problems)
    failed_action_check(app, args.out, tag, problems)
    song_list_check(app, args.out, tag, problems)
    if args.resize:
        # Last of the window's checks: a window that never settles would hold every check after it.
        resize_check(app, args.out, tag, problems)
    # Jobs the window still has waiting would fire into the next window's event loop once it is gone.
    for job in app.root.tk.splitlist(app.root.tk.call("after", "info")):
        app.root.after_cancel(job)
    app.root.destroy()
    standalone_check(args.out, tag, args.lang, problems)
    stopped_check(args.out, tag, args.lang, problems)
    # The installer speaks the launcher's language (the one this run saved), as the OpenDMTQ PC client's does.
    installer_check(args.out, tag, problems)
    finish(args.out, tag, problems)


def finish(out, tag, problems):
    """Write the problems down, say how many screens and problems there were, and end with 1 when there are any."""
    with open(os.path.join(out, "problems-%s.txt" % tag), "w", encoding="utf-8") as f:
        f.write("\n".join(problems) + ("\n" if problems else ""))
    if RESIZES:
        # The widths the resize check drew, counted the same way (a line of its own: the next one is read by the
        # runners as it is).
        print("%s: %d resizes over %d pages" % (tag, len(RESIZES), len({page for page, _ in RESIZES})))
    # What the check for content hidden with no way to scroll to it looked at, and the PLAY pages held to the
    # launcher's own size, counted the same way.
    print("%s: %d widgets looked at for hidden content over %d screens, %d PLAY pages held to the launcher's own size"
          % (tag, sum(HIDDEN_LOOKS), len(HIDDEN_LOOKS), len(FITS)))
    # Counted, not worked out: a screen that was skipped must show in the number.
    print("%s: %d screens, %d problems" % (tag, len(SHOTS), len(problems)))
    for p in problems:
        print("  " + p)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
