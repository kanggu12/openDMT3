"""The stage behind every page head: one composition for the launcher and both sites, as TECHNIKA 3's backgrounds and
the Platinum Crew site's page heads are drawn (measured, _work/theme/THEME.md): a faceted ground of charcoal
triangles, long shards over it, most of it without colour, the section's colour in four pieces near the light, a
spotlight from above behind the title, and a fade from the left so the title stands on plain metal.

The pieces are in a box one unit wide and one unit tall (x from the left edge, y from the top), so each surface
stretches them to its head: the launcher draws them with PIL (client/art.py), the sites as SVG (server/web/stage.py).
One seed for every page: the same composition everywhere, only its colour changes with the section (a new scatter on
every page read as generated noise; the site already had one arrangement).

Plain Python, no picture library: the launcher and the server both use it.
"""

import random

# The one composition's seed (the launcher's PLAY page's, which the other pages now share).
SEED = 7
# The faceted ground: a jittered grid from this far across to past the right edge, columns by rows.
GROUND_FROM, GROUND_TO = 0.30, 1.04
COLUMNS, ROWS = 11, 4
# How far a grid point moves, as a share of a cell, and how much the grid leans (x moves this much for each unit of y
# away from the middle): no facet edge stands upright or lies flat, as the game's facets are acute triangles.
JITTER_X, JITTER_Y, LEAN = 0.45, 0.42, 0.07
# Where the head's light comes from (across, down): the coloured facets are the ones nearest it.
LIGHT = (0.80, 0.20)
# The spotlight from above behind the title: its middle (above the head's top), its half width and half height (shares
# of the head's width), its strength at the middle, and how much of the section's colour is in its white.
SPOT = {"x": 0.20, "y": -0.35, "rx": 0.42, "ry": 0.26, "alpha": 0.16, "tint": 0.18}
# The fade from the left: nothing of the stage before this far across, all of it from this far on.
FADE_FROM, FADE_TO = 0.0, 0.625

# The tones a piece is painted in. "deep" and "light" are the section's (theme colours); the rest have no colour.
CHARCOAL = (24, 28, 34)        # the long dark planes
STEEL = (143, 153, 164)        # the grey splinters (white at 3 to 9 % on the facets)


def pieces(seed=SEED):
    """The stage's pieces, back to front: dicts with "points" (x, y in the unit box), "tone" ("deep", "light", "white",
    "black", "charcoal" or "steel") and "alpha" (0 to 1). The same seed gives the same pieces on every surface."""
    out = []
    rng = random.Random(seed * 7919 + 3)
    width = GROUND_TO - GROUND_FROM
    cw, ch = width / COLUMNS, 1.36 / ROWS
    top = -0.18
    # The grid's points: each moved within its cell, and the whole grid leaned.
    grid = [[(GROUND_FROM + i * cw + rng.uniform(-JITTER_X, JITTER_X) * cw + LEAN * (top + j * ch - 0.5),
              top + j * ch + rng.uniform(-JITTER_Y, JITTER_Y) * ch)
             for j in range(ROWS + 1)] for i in range(COLUMNS + 1)]
    triangles = []
    for i in range(COLUMNS):
        for j in range(ROWS):
            a, b, c, d = grid[i][j], grid[i + 1][j], grid[i][j + 1], grid[i + 1][j + 1]
            # Each cell in two triangles, along one diagonal or the other.
            triangles += [(a, b, d), (a, d, c)] if rng.random() < 0.5 else [(a, b, c), (b, d, c)]

    def from_light(t):
        cx, cy = sum(p[0] for p in t) / 3, sum(p[1] for p in t) / 3
        # The head is about eight times as wide as it is tall: distances are taken in its own proportions.
        return ((cx - LIGHT[0]) * 8) ** 2 + (cy - LIGHT[1]) ** 2

    coloured = 0
    for t in sorted(triangles, key=from_light):
        cx = sum(p[0] for p in t) / 3
        across = max(0.0, min(1.0, (cx - GROUND_FROM) / width))
        r = rng.random()
        if coloured < 2 and r < 0.35:
            # The two facets nearest the light that the dice give: the section's deep step, then its light one.
            out.append({"points": t, "tone": "deep" if coloured == 0 else "light", "alpha": 0.50 if coloured == 0 else 0.22})
            coloured += 1
        elif r < 0.30 + 0.25 * across:
            # Grey toward white, more of them to the right.
            out.append({"points": t, "tone": "white", "alpha": round(rng.uniform(0.03, 0.09), 3)})
        else:
            # Near black, in three steps.
            out.append({"points": t, "tone": "black", "alpha": rng.choice((0.10, 0.18, 0.26))})
    # The long shards over the ground: the same sequence the launcher's heads always had (their shapes stay), six dark
    # planes, then splinters: two in the section's light colour, the rest steel grey.
    srng = random.Random(seed)
    for i in range(16):
        splinter = i >= 6
        x = srng.uniform(0.38, 1.08)
        y = srng.uniform(-0.3, 1.1)
        length = srng.uniform(0.45, 1.3) * (1.3 if not splinter else 1.0)
        spread = srng.uniform(0.05, 0.20)
        points = ((x, y), (x + spread, y - length * 0.30), (x - spread * srng.uniform(0.3, 1.0), y + length))
        alpha = (srng.randint(115, 165) if splinter else srng.randint(120, 190)) / 255.0
        if not splinter:
            out.append({"points": points, "tone": "charcoal", "alpha": round(alpha, 3)})
        elif i in (7, 11):
            out.append({"points": points, "tone": "light", "alpha": round(alpha, 3)})
        else:
            out.append({"points": points, "tone": "steel", "alpha": round(alpha * 0.32, 3)})
    return out


def coloured(piece):
    """Whether a piece takes the section's colour (the four that change from page to page)."""
    return piece["tone"] in ("deep", "light")


def spot_colour(accent):
    """The spotlight's colour: white with a little of the section's accent ((r, g, b) in, (r, g, b) out)."""
    t = SPOT["tint"]
    return tuple(int(round(255 * (1 - t) + c * t)) for c in accent)
