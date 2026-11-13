"""Where the in-game layer drew on one frame (tests/e2e/windows/ingame.sh).

    python3 layer.py OUT_DIR LABEL ZONE...

The chain's measuring dump wrote LABEL-out.bmp (the frame as the chain made it, before the layer) and LABEL-ui.bmp
(the same frame with the layer drawn over it), so the pixels that differ are the layer's, whatever the game was
doing. The zones are native/cardreader/logic.c's measures, in game pixels times the picture's height over 768, in the
picture as the chain placed it in the frame (its own shape kept, bars on two sides, or filling the frame with
OPENDMT3_PICTURE_SHAPE=fill in this script's environment), each with room for its shadow and the keys' ring:
  bar       the band of the bar across the top (70 lines, its shadow under it)
  question  the question, hanging from the bar's foot under the X at the right
  menu      the menu, hanging from the bar's foot under its own chip and the chips beside it (from the menu's chip's
            left edge to the X's right edge)
  toast     the toast, hanging from the top edge in the middle
  mark      the bar's handle at the top centre: a rail along the top edge and a small tab under it
  chip      the frame rate chip in the bottom right corner, beside the game's FREE PLAY in its bottom band
  middle    the middle half of the game, where the notes come
ZONE: the zones that must hold drawn pixels, "!ZONE" for one that must hold none, or "none" (nothing drawn at all).
Passes when the layer drew nothing in the middle half, in every zone named, nowhere outside the zones named, and in
none of the "!" zones. Plain Python, 24-bit BMP files only (picture.py's reader).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from picture import GAME_H, GAME_W, bmp  # noqa: E402


def picture(w, h, fill):
    """Where the game's picture lies in a frame of w x h (native/cardreader/logic.c picture_rect): (x, y, width,
    height), the largest rectangle of its own 5:3 shape centred, or the whole frame when it fills it."""
    if fill or w * GAME_H == h * GAME_W:
        return 0, 0, w, h
    if w * GAME_H > h * GAME_W:
        pw = (h * GAME_W + GAME_H // 2) // GAME_H
        return (w - pw) // 2, 0, pw, h
    ph = (w * GAME_H + GAME_W // 2) // GAME_W
    return 0, (h - ph) // 2, w, ph


def zones(w, h, fill=False):
    """Each zone's box (x0, y0, x1, y1) in a frame of w x h, in the picture's place there."""
    px, py, pw, ph = picture(w, h, fill)
    u = ph / GAME_H
    x_right = px + pw - 12 * u
    # The menu's chip's left edge: left of the X, full screen and minimise (50 wide, 6 apart), 16 more and its own 50.
    menu_left = x_right - (4 * 50 + 2 * 6 + 16) * u
    return {
        "bar": (px, py, px + pw, py + (70 + 10) * u),
        # Both hang from the bar's foot (70 lines), at most 106 tall, with room for their shadows and the keys' ring.
        "question": (x_right - 300 * u - 10 * u, py + 70 * u, px + pw, py + (70 + 106 + 12) * u),
        "menu": (menu_left - 10 * u, py + 70 * u, px + pw, py + (70 + 106 + 12) * u),
        "toast": (px + pw * 0.15, py, px + pw * 0.85, py + (40 + 12) * u),
        # The rail 72 wide along the top edge, the tab 12 deep lit, with a little room.
        "mark": (px + pw / 2 - 38 * u, py, px + pw / 2 + 38 * u, py + 14 * u),
        # One line, 118 x 13, from line 742 of 768, its right end 8 game pixels left of FREE PLAY (from x 1131), the
        # game's own pixels across (a filled picture stretches them), with room.
        "chip": (px + (1131 - 8) * pw / GAME_W - (118 + 6) * u, py + (742 - 6) * ph / GAME_H,
                 px + (1131 - 8) * pw / GAME_W + 6 * u, py + (742 + 13 + 6) * ph / GAME_H),
        "middle": (px + pw / 4, py + ph / 4, px + 3 * pw / 4, py + 3 * ph / 4),
    }


def main(out, label, names):
    wanted = [n for n in names if not n.startswith("!")]
    empty = [n[1:] for n in names if n.startswith("!")]
    before, after = bmp("%s/%s-out.bmp" % (out, label)), bmp("%s/%s-ui.bmp" % (out, label))
    w, h = before[0], before[1]
    z = zones(w, h, os.environ.get("OPENDMT3_PICTURE_SHAPE", "keep") == "fill")
    count = {name: 0 for name in z}
    outside = 0
    box = None
    for y in range(h):
        ra, rb = before[2][y], after[2][y]
        if ra == rb:
            continue
        for x in range(w):
            if ra[3 * x:3 * x + 3] == rb[3 * x:3 * x + 3]:
                continue
            inside = [name for name, (x0, y0, x1, y1) in z.items() if x0 <= x < x1 and y0 <= y < y1]
            for name in inside:
                count[name] += 1
            if not any(name in wanted for name in inside):
                outside += 1
            box = (min(box[0], x), min(box[1], y), max(box[2], x), max(box[3], y)) if box else (x, y, x, y)
    print("  %s: the layer drew %s; pixels in each zone: %s; outside the zones named: %d" % (
        label, "within %s" % (box,) if box else "nothing",
        ", ".join("%s %d" % (name, n) for name, n in count.items()), outside))
    ok = count["middle"] == 0 and outside == 0 and all(count[name] > 0 for name in wanted if name != "none")
    ok = ok and all(count[name] == 0 for name in empty)
    if "none" in wanted:
        ok = box is None
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
