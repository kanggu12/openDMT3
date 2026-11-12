# Fonts

The launcher and the server's site use two open fonts. Each keeps its own licence, in this folder.

| File | Family | Made from | Licence |
|---|---|---|---|
| `DMT3Wide-Regular.ttf` | DMT3 Wide | [Saira](https://github.com/Omnibus-Type/Saira) at its widest (`wdth` 125) and ExtraBold (`wght` 800), Latin only | [Saira-OFL.txt](Saira-OFL.txt) |
| `Pretendard-*.ttf` | Pretendard | [Pretendard](https://github.com/orioncactus/pretendard) 1.3.9, unchanged | [Pretendard-OFL.txt](Pretendard-OFL.txt) |

DMT3 Wide is a modified version of Saira (one instance of its variable font, cut down to Latin), so it carries a
name of its own as the SIL Open Font License asks; it is under the same licence. `packaging/fonts/make_wide.py`
makes it again from Saira's variable font:

    python packaging/fonts/make_wide.py "Saira[wdth,wght].ttf" DMT3Wide-Regular.ttf dmt3-wide.woff2

The `.woff2` it also writes is not kept: the launcher and the site both use the `.ttf`.
