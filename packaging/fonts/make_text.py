"""Cut DMT3 Text, the site's text face, from Pretendard's variable font: every weight in one WOFF2, with the 2,350
Hangul syllables of KS X 1001, the compatibility jamo, Latin and the punctuation the pages use. A modified version
may not keep the original's name under the SIL Open Font License, so every name in the font is renamed.

  python packaging/fonts/make_text.py PRETENDARD_VARIABLE OUT_WOFF2 [OUT_BOLD_HANGUL_WOFF2]

The second file, when asked for, is the same Hangul held at bold (wght 700) and nothing else: the wide title face has
no Hangul, and a title's Hangul comes from it (a browser picks a face by weight before it looks at its characters,
so the variable file declared at another weight would never be chosen for a title).

PRETENDARD_VARIABLE is Pretendard 1.3.9's PretendardVariable (TTF or WOFF2), the same release as the launcher's
fonts. A syllable outside KS X 1001 (a rare one in a DJ name) is drawn by the browser's next font. Needs fontTools
and brotli.
"""
import os
import sys

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

FAMILY = "DMT3 Text"


def ks_x_1001_syllables():
    """The Hangul syllables KS X 1001 has: those EUC-KR writes in two bytes. (Python's codec writes every other
    syllable too, as an eight-byte jamo sequence, so "can it be written" is not the test.)"""
    found = [code for code in range(0xAC00, 0xD7A4) if len(chr(code).encode("euc_kr")) == 2]
    assert len(found) == 2350, len(found)
    return found


def characters():
    latin = list(range(0x20, 0x7F)) + list(range(0xA0, 0x180))
    punctuation = list(range(0x2010, 0x2028)) + list(range(0x2030, 0x203B)) + [0x2190, 0x2191, 0x2192, 0x2193,
                                                                              0x2122, 0x2116, 0x20A9, 0x2026]
    korean = ks_x_1001_syllables() + list(range(0x3131, 0x318F)) + list(range(0x3000, 0x3019))
    return latin + punctuation + korean


def rename(font):
    """Every name that says Pretendard says DMT3 Text (the weights' and axes' names keep their place and words)."""
    for record in font["name"].names:
        text = record.toUnicode()
        renamed = (text.replace("Pretendard Variable", FAMILY).replace("PretendardVariable", FAMILY.replace(" ", ""))
                   .replace("Pretendard", FAMILY))
        if renamed != text:
            record.string = renamed


def hangul():
    return ks_x_1001_syllables() + list(range(0x3131, 0x318F))


def cut(font, unicodes, out):
    options = subset.Options()
    options.layout_features = ["kern", "liga", "calt", "locl", "ccmp"]
    options.name_IDs = ["*"]
    options.name_languages = ["*"]
    options.notdef_outline = True
    options.flavor = "woff2"
    sub = subset.Subsetter(options)
    sub.populate(unicodes=unicodes)
    sub.subset(font)
    rename(font)
    font.flavor = "woff2"
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    font.save(out)
    print("%s: %d bytes, %s" % (out, os.path.getsize(out), font["name"].getDebugName(1)))


def main(source, out, bold_hangul=None):
    if bold_hangul:
        bold = instancer.instantiateVariableFont(TTFont(source), {"wght": 700}, updateFontNames=False)
        cut(bold, hangul(), bold_hangul)
    cut(TTFont(source), characters(), out)
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
