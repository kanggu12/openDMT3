"""A player for the in-game layer's tests: a shell script of xdotool steps that plays a song with the mouse all over the
screen, the game's top band and its very top edge included, and between notes rests the pointer at the top edge (on
the mark too) a little less than the layer's quiet time, so that the bar must never come (tests/e2e/windows/ingame.sh).

    python3 player.py SECONDS SEED > player.sh

The script runs in the test's container (DISPLAY set), for about SECONDS. Taps, held notes (drawn a little while
held) and rests at the top edge, in any order; no two presses or releases further apart than 1.2 s, and a rest at the
top ends within 1.0 s of the last release, so the game is never quiet the 1.5 s a rest needs. The game's SKIP button
(the top right of its top band, on a 1920x1080 screen) is left alone: it would end the song.
"""
import random
import sys

W, H = 1920, 1080
# The game's picture on this screen, its own shape kept (native/cardreader/logic.c picture_rect): 1800 x 1080 from 60
# across, bars beside it.
PX, PW = 60, 1800
# The game's top band on this screen (70 of its 768 lines), and its SKIP button there (1112 to 1275 of 1280 across).
BAND = int(70 * H / 768)
SKIP = (PX + int(1100 * PW / 1280), PX + PW)


def point(rng, top_share):
    """A place to press: anywhere, the top band in `top_share` of the presses, never on SKIP."""
    while True:
        if rng.random() < top_share:
            x, y = rng.randint(PX + 20, PX + PW - 20), rng.randint(0, BAND)
        else:
            x, y = rng.randint(PX + 20, PX + PW - 20), rng.randint(BAND, H - 20)
        if y <= BAND + 10 and SKIP[0] <= x <= SKIP[1]:
            continue
        return x, y


def main(seconds, seed):
    rng = random.Random(seed)
    lines = ["#!/bin/sh", "# Made by tests/e2e/windows/ingame/player.py: a song played all over the screen."]
    t = 0.0
    while t < seconds:
        kind = rng.random()
        if kind < 0.45:
            # A tap, a third of them in the top band, some at its very top edge.
            x, y = point(rng, 0.35)
            if rng.random() < 0.15:
                y = rng.randint(0, 2)
            lines.append("xdotool mousemove %d %d click 1" % (x, y))
            gap = rng.uniform(0.15, 0.9)
        elif kind < 0.7:
            # A held note: down, drawn a little while it is held, up.
            x, y = point(rng, 0.3)
            hold = rng.uniform(0.3, 1.0)
            dx, dy = rng.randint(-120, 120), rng.randint(-60, 60)
            lines.append("xdotool mousemove %d %d mousedown 1" % (x, y))
            lines.append("sleep %.2f" % (hold / 2))
            lines.append("xdotool mousemove %d %d" % (max(0, x + dx), max(0, y + dy)))
            lines.append("sleep %.2f" % (hold / 2))
            lines.append("xdotool mouseup 1")
            t += hold
            gap = rng.uniform(0.1, 0.6)
        else:
            # A rest at the very top edge (on the mark at the top centre a third of the time) right after a tap: a
            # little under the quiet the bar needs, then the next tap.
            x, y = point(rng, 0.3)
            lines.append("xdotool mousemove %d %d click 1" % (x, y))
            rx = W // 2 + rng.randint(-25, 25) if rng.random() < 0.35 else rng.randint(PX + 20, PX + PW - 20)
            if SKIP[0] <= rx <= SKIP[1]:
                rx = W // 3
            lines.append("xdotool mousemove %d %d" % (rx, rng.randint(0, 2)))
            gap = rng.uniform(0.4, 1.0)
        lines.append("sleep %.2f" % gap)
        t += gap
    print("\n".join(lines))


if __name__ == "__main__":
    main(float(sys.argv[1]), int(sys.argv[2]))
