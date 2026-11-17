"""The stage behind the players' site's page heads, as SVG (core/stage.py's pieces: the launcher draws the same with
PIL): one composition on every page, its four coloured pieces and its spotlight in the page's section colours, taken
from the page's own CSS custom properties (--accent, --accent-light, --accent-deep), so the server holds no colour of
its own. Made once; every page puts the same markup in its head.
"""

from opendmt3.core import stage as composition

# The drawing's box: the desktop head's proportions (1280 x 220), stretched to whatever the head is (as the launcher
# stretches the same pieces to its own head).
WIDTH, HEIGHT = 1000, 172

_SVG = None


def _points(points):
    return " ".join("%.1f,%.1f" % (x * WIDTH, y * HEIGHT) for x, y in points)


def svg():
    """The stage's SVG markup (made once): the pieces back to front under a fade from the left, the spotlight over
    them. Decorative: hidden from screen readers by its parent."""
    global _SVG
    if _SVG is not None:
        return _SVG
    fills = {"white": 'fill="#fff"', "black": 'fill="#000"', "charcoal": 'fill="rgb(%d,%d,%d)"' % composition.CHARCOAL,
             "steel": 'fill="rgb(%d,%d,%d)"' % composition.STEEL,
             # The section's colours, from the page (inline SVG takes the page's custom properties).
             "deep": 'style="fill: var(--accent-deep)"', "light": 'style="fill: var(--accent-light)"'}
    shapes = "".join('<polygon points="%s" %s fill-opacity="%.3f"/>' % (_points(p["points"]), fills[p["tone"]], p["alpha"])
                     for p in composition.pieces())
    spot = composition.SPOT
    cx, cy = spot["x"] * WIDTH, spot["y"] * HEIGHT
    rx, ry = spot["rx"] * WIDTH, spot["ry"] * WIDTH
    tint = int(round(spot["tint"] * 100))
    # The fade's stops: nothing of the stage before FADE_FROM of the width, all of it from FADE_TO on.
    _SVG = (
        '<svg class="stage" viewBox="0 0 %d %d" preserveAspectRatio="none" focusable="false">' % (WIDTH, HEIGHT)
        + '<defs><linearGradient id="stage-fade" x1="0" x2="1" y1="0" y2="0">'
        + '<stop offset="%.3f" stop-color="#fff" stop-opacity="0"/>' % composition.FADE_FROM
        + '<stop offset="%.3f" stop-color="#fff" stop-opacity="1"/></linearGradient>' % composition.FADE_TO
        + '<mask id="stage-mask"><rect width="%d" height="%d" fill="url(#stage-fade)"/></mask>' % (WIDTH, HEIGHT)
        # The spotlight: an ellipse of light (its half width and half height relative to the head's width, as the
        # launcher's), falling off as the square of the distance (three stops approximate the curve).
        + '<radialGradient id="stage-spot" gradientUnits="userSpaceOnUse" cx="%.1f" cy="%.1f" r="%.1f" '
          'gradientTransform="translate(%.1f %.1f) scale(1 %.4f) translate(%.1f %.1f)">' % (
              cx, cy, rx, cx, cy, ry / rx, -cx, -cy)
        + ''.join('<stop offset="%.2f" style="stop-color: color-mix(in srgb, var(--accent) %d%%, #ffffff)" '
                  'stop-opacity="%.3f"/>' % (t, tint, spot["alpha"] * (1 - t) ** 2) for t in (0.0, 0.35, 0.7, 1.0))
        + '</radialGradient></defs>'
        + '<g mask="url(#stage-mask)">%s</g>' % shapes
        + '<rect width="%d" height="%d" fill="url(#stage-spot)"/></svg>' % (WIDTH, HEIGHT))
    return _SVG
