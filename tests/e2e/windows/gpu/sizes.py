#!/usr/bin/env python3
"""gpu/sizes.sh's starts judged, and the places on the screen that script points at.

    python3 sizes.py places CW CH [OX OY [DPI]]   the game's picture in a client CW x CH whose top left is at OX,OY on
                                            the screen, and where the layer's parts and the pointer's points are
                                            there at DPI (96 by default), as shell assignments (sizes.sh evaluates
                                            them)
    python3 sizes.py report OUT_DIR         every start under OUT_DIR judged: OUT_DIR/summary.md and results.json, and
                                            each start's overlay cut out of its shots at 1:1 (OUT_DIR/SIZE/KIND/crops)

A start's folder (OUT_DIR/SIZE/KIND, or OUT_DIR/heavy-KIND) holds what sizes.sh left: start.txt (its size, the
Windows scaling, the choices), ingame.log (the layer's log), marks.txt (each phase's edges on the log's clock with the
machine's load then, ingame/quiet.py), steps.txt (each act and the layer's answer to it), probes.txt (each point the
pointer rested on, in the client's pixels), cursor.txt (the dart's picture through XFixes, ingame/pointer.py) and
shots/ (the whole virtual screen, as import composes it). OUT_DIR/card.txt has the card's memory in use beside them
and gpu-clocks.txt its clocks (gpu/clocks.py).

Judged, each with its numbers:
  attached   the layer at the screen's size, its unit the picture's height over 768 (never under 0.75) and the
             Windows scaling as set (a client that is not aware of the scaling would be given 96)
  steps      every act the layer answered: the bar, the menu, the sound panel, the question, Keep playing, a toast,
             the window and back, minimise and back, the window's two sizes, the resets, the 3, 2, 1, the quit
  pointer    every point in the picture read by the game as the game pixel under it (logic.c game_pixel_under, the
             picture's place as logic.c picture_rect puts it; in a picture smaller than the game's, the nearest the
             display fix's whole-number sums reach), a point on a bar past the game's edge on its side, every press
             read but one on the picture's top edge (the layer's)
  cursor     the dart 32 pixels at 96 dpi, scaled with Windows' scaling (layer.c cursor); in the smallest window
             (960x576) the chips at least as wide as the dart (logic.h: its chips are still a mouse's size)
  pacing     at the defaults in full screen, in the tutorial and on the title: the frames hold 60 (ingame/pace.py's
             rule: most of the phase's two-second windows at 59.5 a second or more with a spread under 0.5 ms), judged
             only where the machine was quiet (the others' load under QUIET_LOAD) and where showing a frame on the
             virtual screen takes the test itself less than a frame (the GPU image reads each frame back from the
             card, a cost a player's PC does not have, and more than a frame at 3840x2160 through WSL); every other
             choice said, and whether it held
  textures   the layer's parts' textures never made while the game plays, nothing of the chain or the layer failing
             to be made at any size, and after each reset and change of the window's size the frames going on
  crisp      the layer's words drawn at the screen's own pixels: the median width of their edges' rise from 10 % to
             90 % of their contrast under 2 pixels in every cut-out of words (the menu, the sound panel, the
             question, a toast, the quitting bar, the FPS counter), at every size. Words drawn at the screen's pixels
             rise over about a pixel whatever their size; drawn at the game's size and enlarged they would rise over
             about the enlargement (2.8 pixels at 3840x2160). The width against 1920x1080's is said, not judged (thin
             strokes at 1920x1080 hold their edges under a pixel, which makes any larger size look softer by it)
Said, not judged: each choice's frame time and the chain's GPU time by pass, the parts' costs, the card's clock;
the layer's measures in pixels and in millimetres on a usual monitor of each size, beside Windows' own 9 point text
at its scaling there; the process's address space and the device's texture memory (OPENDMT3_MEMORY_WATCH) and the
card's memory in use. Exit 0 when everything judged passed, 1 when anything failed, 2 when something could not be
judged (a start missing, or the machine never quiet).
"""
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "ingame"))
import frames  # noqa: E402
import measure  # noqa: E402
import pace  # noqa: E402

GAME_W, GAME_H = 1280, 768
UI_UNIT_MIN = 0.75
# The layer's measures in game pixels (native/cardreader/logic.c ui_layout, read back from it below when the tree is
# there, so a change there is never measured with old numbers): the bar, its chips, the gaps, the type sizes.
LAYOUT = {"BAR_H": 70.0, "CHIP_W": 50.0, "CHIP_H": 34.0, "CHIP_GAP": 6.0, "MENU_GAP": 16.0, "EDGE": 12.0,
          "QUIT_W": 300.0, "ROW_PITCH": 32.0, "SOUND_W": 350.0}
TYPE = {"name": 34.0, "title": 17.0, "line": 15.0, "button": 13.0, "small": 11.0}
# Pretendard's capitals as a share of its size (its OS/2 table: 1448 of 2048, text.c), and Segoe UI's (1434 of 2048),
# Windows' own face, whose 9 point text is Windows' own words at every scaling.
CAP_PRETENDARD = 1448 / 2048
CAP_SEGOE = 1434 / 2048
# A usual monitor of each size (its diagonal in inches), for the measures in millimetres.
MONITORS = {"1920x1080": [24.0], "2560x1440": [27.0], "3840x2160": [27.0, 32.0], "3440x1440": [34.0],
            "2560x1600": [16.0]}
# The game pixel of the title's TOUCH to START (its middle; any press on the title starts, the point is the pointer's
# check there).
START_GAME = (640, 590)
QUIET_LOAD = float(os.environ.get("OPENDMT3_QUIET_LOAD", "5"))


def logic_measures():
    """The layout's numbers from logic.c, where the tree has it: (LAYOUT, TYPE, the names that differed from ours)."""
    path = os.path.join(HERE, "..", "..", "..", "..", "native", "cardreader", "logic.c")
    try:
        src = open(path, encoding="utf-8").read()
    except OSError:
        return LAYOUT, TYPE, []
    lay, typ, differ = dict(LAYOUT), dict(TYPE), []
    for name in LAYOUT:
        m = re.search(r"^#define %s ([\d.]+)f?\s*$" % name, src, re.M)
        if m and float(m.group(1)) != LAYOUT[name]:
            lay[name] = float(m.group(1))
            differ.append(name)
    for name in TYPE:
        m = re.search(r"l->px_%s = ([\d.]+) \* u;" % name, src)
        if m and float(m.group(1)) != TYPE[name]:
            typ[name] = float(m.group(1))
            differ.append("px_" + name)
    return lay, typ, differ


def picture_rect(cw, ch):
    """The game's 5:3 picture kept in a client cw x ch (logic.c picture_rect, Keep): (x, y, w, h)."""
    if cw <= 0 or ch <= 0:
        return 0, 0, cw, ch
    if cw * GAME_H > ch * GAME_W:
        w = (ch * GAME_W + GAME_H // 2) // GAME_H
        return (cw - w) // 2, 0, w, ch
    if cw * GAME_H < ch * GAME_W:
        h = (cw * GAME_H + GAME_W // 2) // GAME_W
        return 0, (ch - h) // 2, cw, h
    return 0, 0, cw, ch


def unit(h, dpi=96):
    """Output pixels per game pixel for a picture h tall (logic.c ui_unit), its smallest at the display's scaling
    (logic.c ui_unit_floor: UI_UNIT_MIN at 96 dpi, as much larger as the scaling makes the pointer)."""
    return max(UI_UNIT_MIN * max(1.0, dpi / 96.0), h / GAME_H)


def game_axis(p, at, size, game):
    """The game pixel whose area holds the centre of picture pixel p (logic.c game_axis: rounded down, bars too)."""
    num, den = (2 * (p - at) + 1) * game, 2 * size
    return num // den


def places(cw, ch, ox=0, oy=0, dpi=96):
    """Where the layer's parts and the pointer's points are, for a client cw x ch at ox,oy on the screen, at a
    display of `dpi` dots an inch."""
    lay, _, _ = logic_measures()
    px, py, pw, ph = picture_rect(cw, ch)
    u = unit(ph, dpi)
    half = lay["CHIP_W"] / 2

    def at(x, y):
        # A point of the picture (its own pixels from its top left) on the screen.
        return "%d %d" % (round(ox + px + x), round(oy + py + y))

    # The chips' middles from the picture's right edge, in the bar's middle (logic.c ui_layout).
    x_mid = lay["EDGE"] + half
    full_mid = x_mid + lay["CHIP_GAP"] + lay["CHIP_W"]
    min_mid = full_mid + lay["CHIP_GAP"] + lay["CHIP_W"]
    menu_mid = min_mid + lay["MENU_GAP"] + lay["CHIP_W"]
    bar_mid = lay["BAR_H"] / 2
    out = {
        "PX": px, "PY": py, "PW": pw, "PH": ph, "U": "%.4f" % u, "OX": ox, "OY": oy, "CW": cw, "CH": ch,
        "X_AT": at(pw - x_mid * u, bar_mid * u), "FULL_AT": at(pw - full_mid * u, bar_mid * u),
        "MIN_AT": at(pw - min_mid * u, bar_mid * u), "MENU_AT": at(pw - menu_mid * u, bar_mid * u),
        # The menu's third row (SOUND), in the middle of the menu under its chip (ingame.sh's SOUND_ROW_AT).
        "SOUND_AT": at(pw - 126 * u, 150 * u),
        # The question's Keep playing: on the game's menus 40 under its top, during a song 64 (its line above them).
        "KEEP_AT": at(pw - 231.5 * u, (76 + 40 + 16) * u), "KEEP_SONG_AT": at(pw - 231.5 * u, (76 + 64 + 16) * u),
        # A rest at the very top edge of the client (a bar above the picture counts as its top edge), away from the
        # mark at the top centre; the pointer away from the layer, low in the picture.
        "TOP_AT": "%d %d" % (round(ox + px + 0.69 * pw), oy), "AWAY_AT": at(pw / 2, 0.65 * ph),
        "START_AT": at((START_GAME[0] + 0.5) * pw / GAME_W, (START_GAME[1] + 0.5) * ph / GAME_H),
    }
    # The pointer's points, in the client's pixels: the picture's left edge and bottom corners, its middle, TOUCH to
    # START's middle, and the middle of each bar there is (none on its top edge, which is the layer's).
    probes = [("left-edge", px, py + ph // 2), ("bottom-left", px, py + ph - 1), ("bottom-right", px + pw - 1, py + ph - 1),
              ("middle", px + pw // 2, py + ph // 2),
              ("start", round(px + (START_GAME[0] + 0.5) * pw / GAME_W), round(py + (START_GAME[1] + 0.5) * ph / GAME_H))]
    if px > 0:
        probes += [("left-bar", px // 2, ch // 2), ("right-bar", px + pw + (cw - px - pw) // 2, ch // 2)]
    if py > 0:
        probes += [("top-bar", cw // 2, py // 2), ("bottom-bar", cw // 2, py + ph + (ch - py - ph) // 2)]
    out["PROBES"] = " ".join("%s:%d:%d" % p for p in probes)
    return out


def shell(values):
    """Shell assignments, each value quoted."""
    return "\n".join("%s='%s'" % (k, v) for k, v in values.items())


# ---------------------------------------------------------------------------------------------------- reading

def read(path):
    try:
        return open(path, errors="replace").read()
    except OSError:
        return ""


def start_info(d):
    """start.txt's KEY=VALUE lines."""
    info = {}
    for line in read(os.path.join(d, "start.txt")).splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip()
    return info


ATTACHED = re.compile(r"^(\d+) layer: attached \((\d+) x (\d+), dpi (\d+), ([\d.]+) output pixels a game pixel, "
                      r"(full screen|in a window)\)", re.M)
POINTER = re.compile(r"^(\d+) pointer: client (-?\d+),(-?\d+) of (\d+)x(\d+), the picture (-?\d+),(-?\d+) (\d+)x(\d+): "
                     r"the game's pixel (-?\d+),(-?\d+)", re.M)
MADE = re.compile(r"^(\d+) layer: (\d+) parts' textures made for (\d+)x(\d+) in ([\d.]+) ms"
                  r"(?:, ([\d.]+) output pixels a game pixel)?", re.M)
PICTURE = re.compile(r"^(\d+) post: the picture (\d+)x(\d+) in the window's client (\d+)x(\d+), drawn at (\d+)x(\d+), "
                     r"upscale (\S+)", re.M)
MEMORY = re.compile(r"^(\d+) memory: address space (\d+) MB free \(the largest free block (\d+) MB\), (\d+) MB reserved, "
                    r"(\d+) MB committed, in (\d+) regions; Windows' count (\d+) MB free of (\d+) MB", re.M)
TEXMEM = re.compile(r"^(\d+) memory: the device's texture memory (\d+) MB available", re.M)
# Lines that say something of the chain or the layer was not made, or the device was not got back.
FAILED = re.compile(r"^\d+ (?:post|layer|flip): .*(?:not made|could not|failed|textures made while the game plays).*$",
                    re.M)


def phases_of(d):
    return pace.phases(read(os.path.join(d, "marks.txt")))


def phase_numbers(log, name, s, e, loads, clocks):
    """One phase's numbers: the frames (frames.py), whether it held 60 (pace.py), the chain's GPU time by pass, the
    parts' costs, the card's clock, the others' load."""
    out = {"phase": name, "ms": e - s}
    out["frames"] = frames.summary(log, s, e)
    wins = [w for w in pace.windows(log) if w[1] >= s and w[0] <= e]
    out["windows"] = len(wins)
    out["held_60"] = pace.held(wins)
    out["others_load"] = loads
    out["quiet"] = bool(loads) and max(loads) < QUIET_LOAD
    steps = {}
    choice = None
    for m in measure.PASSLINE.finditer(log):
        if frames.inside(int(m.group(1)), s, e):
            choice = "%sx%s %s, %s %s, %s" % (m.group(2), m.group(3), m.group(4), m.group(5), m.group(6), m.group(7))
            for sm in measure.STEP.finditer(m.group(8)):
                steps.setdefault(sm.group(1), []).append(float(sm.group(2)))
    out["passes_us"] = {k: frames.median(v) for k, v in steps.items()}
    out["choice"] = choice
    parts = {}
    for m in measure.COST.finditer(log):
        if frames.inside(int(m.group(1)), s, e):
            p = parts.setdefault(m.group(2), {"cpu": [], "gpu": []})
            p["cpu"].append(float(m.group(4)))
            if m.group(5):
                p["gpu"].append(float(m.group(5)))
    out["parts_us"] = {k: {"cpu": frames.median(v["cpu"]), "gpu": frames.median(v["gpu"])} for k, v in parts.items()}
    sm = [c[1] for c in clocks if s <= c[0] <= e]
    out["sm_mhz"] = frames.median(sm)
    return out


def edge_widths(gray):
    """The widths of the strong rises and falls along the rows of a picture (numpy, 0 to 255): from 10 % to 90 % of
    each one's contrast, in pixels, with the crossing points placed between pixels by a straight line. A rise counts
    when it climbs 96 levels or more within 12 pixels with no step back (words on the layer's glass; the glass itself
    and the blurred game behind it change far more slowly)."""
    import numpy as np
    widths = []
    g = gray.astype(np.float64)
    for row in g:
        n = len(row)
        i = 0
        while i < n - 1:
            d = row[i + 1] - row[i]
            if abs(d) < 8:
                i += 1
                continue
            sign = 1 if d > 0 else -1
            j = i + 1
            while j < n - 1 and (row[j + 1] - row[j]) * sign > 0 and j - i < 12:
                j += 1
            lo, hi = row[i], row[j]
            if abs(hi - lo) >= 96:
                a, b = lo + 0.1 * (hi - lo), lo + 0.9 * (hi - lo)

                def cross(level):
                    for k in range(i, j):
                        v0, v1 = row[k], row[k + 1]
                        if (v0 - level) * (v1 - level) <= 0 and v0 != v1:
                            return k + (level - v0) / (v1 - v0)
                    return None
                ca, cb = cross(a), cross(b)
                if ca is not None and cb is not None:
                    widths.append(abs(cb - ca))
            i = j
    return widths


# The layer's places in the picture for its cut-outs, in game pixels from the picture's edges (the unit times them):
# (shot, cut-out, from the right or left edge, x0, x1, y0, y1, words in it).
CROPS = [
    ("bar", "bar-chips", "right", 260, 0, 0, 70, False),
    ("bar", "bar-mark", "left", 0, 260, 0, 70, False),
    ("menu", "menu", "right", 260, 0, 0, 210, True),
    ("sound", "sound", "right", 380, 0, 0, 200, True),
    ("question", "question", "right", 330, 0, 0, 200, True),
    ("toast", "toast", "middle", -320, 320, 0, 60, True),
    ("play-question", "question-song", "right", 330, 0, 0, 200, True),
    ("play-resume", "resume", "middle", -110, 110, 300, 470, False),
    ("play-quitting", "quitting", "right", 640, 0, 0, 70, True),
    ("title", "fps-chip", "right", 330, 0, 690, 768, True),
]


def crops(d, info, out_dir):
    """Each cut-out of the start's shots at 1:1 (PNG files) and the widths of the words' edges in it."""
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return {}
    w, h = (int(v) for v in info.get("SIZE", "0x0").split("x"))
    px, py, pw, ph = picture_rect(w, h)
    u = unit(ph)
    os.makedirs(out_dir, exist_ok=True)
    result = {}
    for shot, name, side, a, b, y0, y1, words in CROPS:
        path = os.path.join(d, "shots", shot + ".png")
        if not os.path.exists(path):
            continue
        with Image.open(path) as im:
            im = im.convert("RGB")
            if side == "right":
                box = (px + pw - a * u, py + y0 * u, px + pw - b * u, py + y1 * u)
            elif side == "left":
                box = (px + a * u, py + y0 * u, px + b * u, py + y1 * u)
            else:
                box = (px + pw / 2 + a * u, py + y0 * u, px + pw / 2 + b * u, py + y1 * u)
            box = tuple(int(round(v)) for v in box)
            cut = im.crop(box)
            cut.save(os.path.join(out_dir, name + ".png"))
            # Every cut-out's edges are measured; only the words' are judged (the 3, 2, 1 is the game's own chrome
            # digits, a picture with soft edges of its own, and the bar's ends are pictures).
            gray = np.asarray(cut.convert("L"))
            ws = edge_widths(gray)
            entry = {"box": box, "words": words, "edges": len(ws), "edge_width_median": frames.median(ws)}
            result[name] = entry
    return result


# ---------------------------------------------------------------------------------------------------- judging

def judge_start(d, clocks):
    info = start_info(d)
    log = read(os.path.join(d, "ingame.log"))
    r = {"dir": d, "info": info, "fails": [], "notes": []}
    if not log:
        r["fails"].append("no layer log: the start did not run")
        return r
    size = info.get("SIZE", "")
    w, h = (int(v) for v in size.split("x")) if "x" in size else (0, 0)
    dpi = int(info.get("DPI", "96"))
    # Attached at the screen's size, its unit and the scaling as set.
    m = ATTACHED.search(log)
    if not m:
        r["fails"].append("the layer never attached")
    else:
        aw, ah, adpi, au = int(m.group(2)), int(m.group(3)), int(m.group(4)), float(m.group(5))
        ph = picture_rect(aw, ah)[3]
        r["attached"] = {"client": [aw, ah], "dpi": adpi, "unit": au, "mode": m.group(6)}
        if (aw, ah) != (w, h):
            r["fails"].append("attached at %dx%d, not the screen's %dx%d" % (aw, ah, w, h))
        if abs(au - round(unit(ph), 2)) > 0.006:
            r["fails"].append("the unit %.2f, not %.2f (the picture %d tall)" % (au, unit(ph), ph))
        if adpi != dpi:
            r["fails"].append("dpi %d, not the %d set (a client not aware of Windows' scaling is given 96)" % (adpi, dpi))
    # Every act answered: steps.txt's lines are "MS NAME ok|fail [DETAIL]".
    r["steps"] = []
    for line in read(os.path.join(d, "steps.txt")).splitlines():
        p = line.split(None, 3)
        if len(p) < 3:
            continue
        said = " ".join(p[1:])
        r["steps"].append(said)
        if p[2] == "fail":
            r["fails"].append("step: " + said)
    # The pointer: every point the game read (it reads on a press: the layer's OPENDMT3_POINTER_LOG line says the
    # client point, the picture's place it was turned by and the game pixel the game got), each named by the press
    # that made it where there was one (probes.txt: "MS press MODE LABEL OX OY CX CY", written just before the press;
    # a line of seven words is a rest of an earlier tool's, which the game never read).
    logged = [(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)),
               tuple(int(m.group(i)) for i in (6, 7, 8, 9)), int(m.group(10)), int(m.group(11)))
              for m in POINTER.finditer(log)]
    presses = []
    for line in read(os.path.join(d, "probes.txt")).splitlines():
        p = line.split()
        if len(p) == 8 and p[1] == "press":
            presses.append((int(p[0]), p[2], p[3], int(p[6]), int(p[7])))
    probes = []
    for at, cx, cy, lcw, lch, pic, gx, gy in logged:
        names = [(mode, label) for ms, mode, label, px_, py_ in presses
                 if (px_, py_) == (cx, cy) and ms - 200 <= at <= ms + 2000]
        mode, label = names[-1] if names else ("", "")
        entry = {"mode": mode, "point": label, "client": [cx, cy], "client_size": [lcw, lch], "picture": list(pic),
                 "read": [gx, gy]}
        want_pic = picture_rect(lcw, lch)
        if pic == (0, 0, lcw, lch) and want_pic != pic:
            # Read before the chain placed the picture (the game's first read at its start): the whole client.
            entry["result"] = "before the chain placed the picture: not judged"
            probes.append(entry)
            continue
        ex = game_axis(cx, pic[0], pic[2], GAME_W)
        ey = game_axis(cy, pic[1], pic[3], GAME_H)
        inside = 0 <= cx - pic[0] < pic[2] and 0 <= cy - pic[1] < pic[3]
        entry["expected"] = [ex, ey] if inside else "past the game's edge on its side"
        name = "%s %s at %d,%d" % (mode or "a press", label, cx, cy) if label else "the point %d,%d" % (cx, cy)
        if pic != want_pic:
            r["fails"].append("pointer %s: turned by the picture %s, not %s in a client %dx%d" % (
                name, pic, want_pic, lcw, lch))
        # The display fix's helper turns a client point into a game pixel by whole-number sums (q * 1280 / width): in
        # a picture smaller than the game's on an axis, a client pixel spans more than one game pixel and some game
        # pixels are reached by no client point, so the one next to it is the nearest there is (logic.c
        # pointer_axis). Anywhere else the very game pixel.
        slack = (1 if pic[2] < GAME_W else 0, 1 if pic[3] < GAME_H else 0)
        if inside and (abs(gx - ex) > slack[0] or abs(gy - ey) > slack[1]):
            r["fails"].append("pointer %s: the game's pixel %d,%d, not %d,%d" % (name, gx, gy, ex, ey))
        elif inside and (gx, gy) != (ex, ey):
            entry["result"] = "the nearest game pixel the helper's sums reach (the picture smaller than the game's)"
        if not inside:
            past = (gx < 0 if cx < pic[0] else gx >= GAME_W if cx >= pic[0] + pic[2] else True) and \
                   (gy < 0 if cy < pic[1] else gy >= GAME_H if cy >= pic[1] + pic[3] else True)
            if not past:
                r["fails"].append("pointer %s: the game's pixel %d,%d is not past the game's edge" % (name, gx, gy))
        probes.append(entry)
    # Each press must have been read by the game, but one on the picture's top edge: the layer's (logic.c
    # ui_at_top_edge, the top two of the game's lines, above every control of the game's), never the game's.
    for ms, mode, label, cx, cy in presses:
        if any(e["client"] == [cx, cy] for e in probes):
            continue
        top = (cy - picture_rect(*(r.get("attached", {}).get("client") or [w, h]))[1]) <= 2 * unit(
            picture_rect(w, h)[3], dpi) if mode == "full" else False
        if top:
            probes.append({"mode": mode, "point": label, "client": [cx, cy], "result": "the layer's top edge: not "
                           "the game's, by design"})
        else:
            r["fails"].append("pointer: the press %s %s at %d,%d was not read by the game" % (mode, label, cx, cy))
    r["pointer"] = probes
    # The dart's own picture: 32 pixels at 96 dpi, as Windows' scaling sizes it.
    cur = re.search(r"pointer (\d+)x(\d+) hot", read(os.path.join(d, "cursor.txt")))
    if cur:
        want = max(32, int(math.floor(32.0 * dpi / 96.0 + 0.5)))
        r["cursor"] = {"size": [int(cur.group(1)), int(cur.group(2))], "expected": want}
        if int(cur.group(1)) != want:
            r["fails"].append("the dart %s px, not %d at %d dpi" % (cur.group(1), want, dpi))
    # The phases.
    r["phases"] = [phase_numbers(log, n, s, e, loads, clocks) for n, s, e, loads in phases_of(d)]
    # Textures and failures.
    r["textures"] = [{"made": int(m.group(2)), "for": [int(m.group(3)), int(m.group(4))], "ms": float(m.group(5)),
                      "unit": float(m.group(6)) if m.group(6) else None} for m in MADE.finditer(log)]
    # The smallest window's chips against the dart: the unit the layer made its parts at for the window 576 tall (as
    # its log says it, or, from a layer that does not say it, 0.4.0's rule: never under 0.75 whatever the scaling).
    small = [t for t in r["textures"] if t["for"][1] <= 576]
    if small and "cursor" in r:
        u = small[-1]["unit"] if small[-1]["unit"] is not None else max(UI_UNIT_MIN, small[-1]["for"][1] / GAME_H)
        lay, _, _ = logic_measures()
        chip = [round(lay["CHIP_W"] * u, 1), round(lay["CHIP_H"] * u, 1)]
        r["smallest_window"] = {"picture": small[-1]["for"], "unit": u, "said": small[-1]["unit"] is not None,
                                "chip_px": chip, "dart_px": r["cursor"]["size"][0]}
        if chip[0] < r["cursor"]["size"][0]:
            r["fails"].append("in the smallest window (%dx%d) the chips %.0f x %.0f px, narrower than the %d px dart "
                              "(unit %.2f at %d dpi)" % (small[-1]["for"][0], small[-1]["for"][1], chip[0], chip[1],
                                                        r["cursor"]["size"][0], u, dpi))
    for line in FAILED.findall(log):
        r["fails"].append("the log: " + line.split(" ", 1)[1])
    r["pictures"] = [m.group(0).split(" ", 1)[1] for m in PICTURE.finditer(log)]
    # After each change of size or reset: a frames line within 6 s at 59.5 a second or more, on a quiet machine.
    changes = [int(m.group(1)) for m in re.finditer(
        r"^(\d+) (?:layer: (?:in a window|full screen) \(|post: measuring reset made|flip: the window changed size|"
        r"post: the picture \d+x\d+ in the window's client)",
        log, re.M)]
    rates = [(int(m.group(1)), float(m.group(2))) for m in frames.FRAMES.finditer(log)]
    after = []
    for t in changes:
        later = [rate for at, rate in rates if t + 2000 < at <= t + 8000]
        after.append({"at": t, "fps_after": max(later) if later else None})
        if not later:
            r["fails"].append("no frames counted in the 8 s after the change at %d" % t)
    r["after_changes"] = after
    # The room: the process's address space and the device's texture memory.
    mem = [(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)), int(m.group(8)))
           for m in MEMORY.finditer(log)]
    tex = [(int(m.group(1)), int(m.group(2))) for m in TEXMEM.finditer(log)]
    if mem:
        r["memory"] = {
            "first": {"free_mb": mem[0][1], "largest_free_mb": mem[0][2], "committed_mb": mem[0][4],
                      "space_mb": mem[0][5]},
            "least_free_mb": min(x[1] for x in mem), "least_largest_free_mb": min(x[2] for x in mem),
            "most_committed_mb": max(x[4] for x in mem), "most_reserved_mb": max(x[3] for x in mem),
            "lines": len(mem)}
    if tex:
        r["texture_memory"] = {"first_mb": tex[0][1], "least_mb": min(x[1] for x in tex), "lines": len(tex)}
    # What showing a frame cost the test itself at this size (d3d9probe.exe --present, before the game).
    pm = re.search(r"present: (\d+)x(\d+) cleared and presented ([\d.]+) ms a frame", read(os.path.join(d, "present.txt")))
    if pm:
        r["present_ms"] = float(pm.group(3))
    # The quit.
    quit_lines = [line.split(" ", 1)[1] for line in re.findall(r"^\d+ quit: .*$", log, re.M)]
    r["quit"] = quit_lines
    r["exit"] = read(os.path.join(d, "exit.txt")).strip()
    # The overlay's cut-outs.
    if os.path.isdir(os.path.join(d, "shots")):
        r["crops"] = crops(d, info, os.path.join(d, "crops"))
    return r


def measures_table(starts):
    """The layer's measures at each size: pixels, and millimetres on a usual monitor, beside Windows' own text."""
    lay, typ, differ = logic_measures()
    rows = []
    for r in starts:
        info = r["info"]
        if info.get("KIND") != "game" or "attached" not in r:
            continue
        size = info["SIZE"]
        w, h = (int(v) for v in size.split("x"))
        dpi = int(info.get("DPI", "96"))
        ph = picture_rect(w, h)[3]
        u = unit(ph)
        for inches in MONITORS.get(size, [24.0]):
            ppi = math.hypot(w, h) / inches
            mm = 25.4 / ppi
            windows_cap = 9 / 72.0 * dpi * CAP_SEGOE
            rows.append({
                "size": size, "dpi": dpi, "monitor_in": inches, "ppi": round(ppi, 1), "unit": round(u, 4),
                "bar_px": round(lay["BAR_H"] * u, 1), "bar_mm": round(lay["BAR_H"] * u * mm, 2),
                "chip_px": [round(lay["CHIP_W"] * u, 1), round(lay["CHIP_H"] * u, 1)],
                "button_cap_mm": round(typ["button"] * u * CAP_PRETENDARD * mm, 2),
                "small_cap_mm": round(typ["small"] * u * CAP_PRETENDARD * mm, 2),
                "smallest_unit_small_cap_mm": round(typ["small"] * UI_UNIT_MIN * CAP_PRETENDARD * mm, 2),
                "windows_9pt_cap_mm": round(windows_cap * mm, 2),
                "dart_px": max(32, int(math.floor(32.0 * dpi / 96.0 + 0.5))),
                "smallest_chip_px": [round(lay["CHIP_W"] * UI_UNIT_MIN, 1), round(lay["CHIP_H"] * UI_UNIT_MIN, 1)]})
    return rows, differ


def report(out):
    clocks = measure.clocks(out)
    dirs = []
    for root, subdirs, files in os.walk(out):
        if "start.txt" in files:
            dirs.append(root)
            subdirs[:] = []
    dirs.sort()
    starts = [judge_start(d, clocks) for d in dirs]
    fails, unjudged = [], []
    # Every start the run meant to make (its run.txt: "sizes A@D B@D ...; heavy N"), and in each what it must have.
    plan = re.search(r"^sizes (.*?);(?: kinds (.*?);)? heavy (\w+)", read(os.path.join(out, "run.txt")), re.M)
    if plan:
        kinds = (plan.group(2) or "game display").split()
        wanted = ["%s/%s" % (spec.split("@")[0], kind) for spec in plan.group(1).split() for kind in kinds]
        wanted += ["heavy-" + k for k in ("display", "game") if plan.group(3) in ("1", k)]
        have = {os.path.relpath(d, out) for d in dirs}
        unjudged += ["%s: the start did not run" % w for w in wanted if w not in have]
    for r in starts:
        kind = r["info"].get("KIND", "")
        name = os.path.relpath(r["dir"], out)
        if not r.get("steps"):
            unjudged.append("%s: no step was made" % name)
        if kind in ("game", "display") and not r.get("pointer"):
            unjudged.append("%s: no pointer point was read" % name)
        if kind in ("game", "display") and not r.get("phases"):
            unjudged.append("%s: no phase was measured" % name)
    # Pacing at the defaults in full screen: the title's and the tutorial's default phase. Where showing a frame on
    # the virtual screen takes the test itself a whole frame or more (the GPU image reads each frame back from the
    # card: d3d9probe's present, measured by the size's first start), no game holds 60 there, so it is said, not
    # judged.
    present = {r["info"].get("SIZE"): r["present_ms"] for r in starts if r.get("present_ms")}
    for r in starts:
        kind = r["info"].get("KIND", "")
        default = {"game": "fsr1", "display": "off"}.get(kind)
        own = present.get(r["info"].get("SIZE"))
        for p in r.get("phases", []):
            name = p["phase"]
            if default and name in ("title:" + default, "play:" + default):
                if own and own >= 1000.0 / 60:
                    unjudged.append("%s %s %s: showing a frame on the virtual screen alone takes the test %.1f ms, "
                                    "more than a frame at 60 (%s a second measured)" % (
                                        r["info"].get("SIZE"), kind, name, own, fmt(p["frames"]["fps_median"])))
                elif not p["quiet"]:
                    unjudged.append("%s %s %s: the machine was busy (others' load %s)" % (
                        r["info"].get("SIZE"), kind, name, p["others_load"]))
                elif not p["held_60"]:
                    r["fails"].append("%s did not hold 60 (%s)" % (name, frames.line(p["frames"])))
    # Crisp words: each cut-out's edge width against 1920x1080's of the same kind of start.
    base = {}
    for r in starts:
        if r["info"].get("SIZE") == "1920x1080":
            for name, c in r.get("crops", {}).items():
                if c.get("edge_width_median"):
                    base[(r["info"].get("KIND"), name)] = c["edge_width_median"]
    for r in starts:
        for name, c in r.get("crops", {}).items():
            b = base.get((r["info"].get("KIND"), name))
            wmed = c.get("edge_width_median")
            if b and wmed:
                c["against_1080p"] = round(wmed / b, 2)
            if c.get("words") and wmed is not None and c.get("edges", 0) >= 20 and wmed >= 2.0:
                r["fails"].append("the %s's words not drawn at the screen's pixels: their edges rise over %.2f px "
                                  "(%d edges)" % (name, wmed, c["edges"]))
    for r in starts:
        for f in r["fails"]:
            fails.append("%s: %s" % (os.path.relpath(r["dir"], out), f))
    table, differ = measures_table(starts)
    if differ:
        unjudged.append("logic.c's layout changed (%s): the measures read from it" % ", ".join(differ))
    card = read(os.path.join(out, "card.txt")).splitlines()
    result = {"starts": starts, "measures": table, "card_memory": card, "fails": fails, "not_judged": unjudged}
    with open(os.path.join(out, "results.json"), "w") as f:
        json.dump(result, f, indent=1, default=str)
    md = summary_md(result, out)
    with open(os.path.join(out, "summary.md"), "w") as f:
        f.write(md)
    print(md)
    if fails:
        return 1
    return 2 if unjudged or not starts else 0


def fmt(v, form="%.1f"):
    return "?" if v is None else form % v


def summary_md(result, out):
    lines = ["# Screen sizes", ""]
    for r in result["starts"]:
        info = r["info"]
        lines.append("## %s %s (%s dpi, %s)" % (info.get("SIZE"), info.get("KIND"), info.get("DPI"),
                                                info.get("CHOICES", "")))
        lines.append("")
        lines.append("- renderer: %s" % info.get("RENDERER_SAID", "?"))
        if "attached" in r:
            a = r["attached"]
            lines.append("- attached: %dx%d, dpi %d, unit %.2f, %s" % (a["client"][0], a["client"][1], a["dpi"],
                                                                    a["unit"], a["mode"]))
        if "present_ms" in r:
            lines.append("- the test's own cost of showing a frame here (read back to the virtual screen): %.2f ms" %
                         r["present_ms"])
        if "cursor" in r:
            lines.append("- the dart: %dx%d px (%d expected)" % (r["cursor"]["size"][0], r["cursor"]["size"][1],
                                                               r["cursor"]["expected"]))
        lines.append("- textures: " + ", ".join("%d for %dx%d in %.1f ms" % (t["made"], t["for"][0], t["for"][1],
                                                                             t["ms"]) for t in r.get("textures", [])))
        if r.get("memory"):
            mm = r["memory"]
            lines.append("- address space: %d MB of %d free at the start (largest block %d); the least free %d MB, "
                         "largest block at least %d MB, at most %d MB committed and %d reserved (%d lines)" % (
                             mm["first"]["free_mb"], mm["first"]["space_mb"], mm["first"]["largest_free_mb"],
                             mm["least_free_mb"], mm["least_largest_free_mb"], mm["most_committed_mb"],
                             mm["most_reserved_mb"], mm["lines"]))
        if r.get("texture_memory"):
            t = r["texture_memory"]
            lines.append("- the device's texture memory: %d MB at first, %d MB at the least" % (t["first_mb"],
                                                                                              t["least_mb"]))
        if r.get("after_changes"):
            lines.append("- after each change of size or reset, frames a second: " + ", ".join(
                fmt(a["fps_after"]) for a in r["after_changes"]))
        if r.get("quit"):
            lines.append("- quit: " + " / ".join(r["quit"][-2:]))
        lines.append("")
        if r.get("phases"):
            lines.append("| phase | frames a second | frame time ms | 99 % within | longest | held 60 | chain GPU us | "
                         "the layer's pass us | top passes us | parts' CPU us | card MHz | others' load |")
            lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
            for p in r["phases"]:
                fr = p["frames"]
                top = sorted(((v, k) for k, v in p["passes_us"].items() if v is not None and k not in (
                    "all", "timestamp", "empty pass")), reverse=True)[:3]
                parts = ", ".join("%s %s" % (k, fmt(v["cpu"])) for k, v in sorted(p["parts_us"].items()))
                lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                    p["phase"], fmt(fr["fps_median"]), fmt(fr["frame_ms_mean"], "%.2f"), fmt(fr["p99_ms_max"], "%.2f"),
                    fmt(fr["longest_ms"], "%.2f"), "yes" if p["held_60"] else "no", fmt(fr["chain_gpu_us_median"]),
                    fmt(p["passes_us"].get("layer")), ", ".join("%s %.0f" % (k, v) for v, k in top), parts,
                    fmt(p["sm_mhz"], "%.0f"), "/".join("%.1f" % x for x in p["others_load"])))
            lines.append("")
        if r.get("crops"):
            lines.append("- words' edges (median px, against 1920x1080): " + ", ".join(
                "%s %s (%s)" % (k, fmt(c.get("edge_width_median"), "%.2f"), c.get("against_1080p", "-"))
                for k, c in r["crops"].items() if "edges" in c))
        pts = r.get("pointer", [])
        judged = [p for p in pts if "expected" in p]
        bad = [p for p in judged if isinstance(p["expected"], list) and p["read"] != p["expected"]
               and "nearest" not in p.get("result", "")]
        lines.append("- pointer: %d points the game read, %d judged (%d in a window), %d wrong: %s" % (
            len(pts), len(judged), sum(1 for p in judged if p["mode"].startswith("window")), len(bad),
            "; ".join("%s %s %d,%d -> %d,%d" % (p["mode"], p["point"], p["client"][0], p["client"][1], p["read"][0],
                                                 p["read"][1]) for p in judged if p["point"])))
        lines.append("- steps: " + "; ".join(r.get("steps", [])))
        for f in r["fails"]:
            lines.append("- **FAIL** " + f)
        lines.append("")
    if result["measures"]:
        lines.append("## The layer's measures")
        lines.append("")
        lines.append("| size | scaling | monitor | unit | bar | chip px | button capitals | small capitals | at the "
                     "smallest unit | Windows' 9 pt capitals | dart px |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for t in result["measures"]:
            lines.append("| %s | %d %% | %g in, %.0f ppi | %.2f | %.0f px, %.1f mm | %.0f x %.0f | %.1f mm | %.1f mm | "
                         "%.1f mm | %.1f mm | %d |" % (
                             t["size"], round(t["dpi"] / 96 * 100), t["monitor_in"], t["ppi"], t["unit"], t["bar_px"],
                             t["bar_mm"], t["chip_px"][0], t["chip_px"][1], t["button_cap_mm"], t["small_cap_mm"],
                             t["smallest_unit_small_cap_mm"], t["windows_9pt_cap_mm"], t["dart_px"]))
        lines.append("")
    if result["card_memory"]:
        lines.append("## The card's memory in use (MiB)")
        lines.append("")
        lines += ["    " + c for c in result["card_memory"]]
        lines.append("")
    lines.append("## Verdict")
    lines.append("")
    for f in result["fails"]:
        lines.append("- FAIL " + f)
    for u in result["not_judged"]:
        lines.append("- not judged: " + u)
    if not result["fails"] and not result["not_judged"]:
        lines.append("- PASS: every start attached at its size and scaling, every act answered, every pointer point "
                     "read as the game pixel under it, the dart at its size, the defaults held 60, nothing failed to be "
                     "made, and the words drawn at the screen's pixels at every size")
    return "\n".join(lines) + "\n"


def main(argv):
    if len(argv) >= 3 and argv[0] == "places":
        cw, ch = int(argv[1]), int(argv[2])
        ox, oy = (int(argv[3]), int(argv[4])) if len(argv) >= 5 else (0, 0)
        dpi = int(argv[5]) if len(argv) >= 6 else 96
        print(shell(places(cw, ch, ox, oy, dpi)))
        return 0
    if len(argv) == 2 and argv[0] == "report":
        return report(argv[1])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
