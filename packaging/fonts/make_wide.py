"""Cut DMT3 Wide from Saira's variable font: its widest width (wdth 125), ExtraBold (wght 800), Latin only, with a
family name of its own (a modified version may not keep the original's name under the SIL Open Font License).

  python packaging/fonts/make_wide.py SAIRA_VARIABLE_TTF OUT_TTF OUT_WOFF2

Needs fontTools (and brotli for the WOFF2 copy).
"""
import sys
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from fontTools import subset

src, out_ttf, out_woff2 = sys.argv[1:4]
font = TTFont(src)
static = instancer.instantiateVariableFont(font, {"wdth": 125, "wght": 800}, updateFontNames=False)
# Latin: ASCII, Latin-1, and the punctuation the launcher and site use in titles.
unicodes = list(range(0x20, 0x7F)) + list(range(0xA0, 0x100)) + [0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D,
                                                                  0x2022, 0x2026, 0x00B7, 0x2192, 0x2190]
options = subset.Options()
options.layout_features = ["kern", "liga", "calt", "locl"]
options.name_IDs = ["*"]
options.notdef_outline = True
sub = subset.Subsetter(options)
sub.populate(unicodes=unicodes)
sub.subset(static)
# A modified version gets a name of its own (OFL); one face, so it is the family's Regular to every system.
name = static["name"]
for record in list(name.names):
    if record.nameID in (16, 17, 21, 22, 25) or record.nameID >= 256:
        name.removeNames(nameID=record.nameID)
for nid, text in ((1, "DMT3 Wide"), (2, "Regular"), (3, "DMT3 Wide; from Saira 1.101 by the Saira Project Authors"),
                  (4, "DMT3 Wide"), (6, "DMT3Wide-Regular")):
    name.setName(text, nid, 3, 1, 0x409)
    name.setName(text, nid, 1, 0, 0)
static["OS/2"].usWeightClass = 400
static["OS/2"].fsSelection = (static["OS/2"].fsSelection & ~0b1100001) | 0b1000000   # REGULAR
static["head"].macStyle = 0
if "DSIG" in static:
    del static["DSIG"]
if "STAT" in static:
    del static["STAT"]
static.save(out_ttf)
static.flavor = "woff2"
static.save(out_woff2)
print("glyphs", len(static.getGlyphOrder()), "names", [n.toUnicode() for n in static["name"].names if n.nameID in (1, 2, 4, 6) and n.platformID == 3])
