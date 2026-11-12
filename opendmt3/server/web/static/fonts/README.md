# The site's text face

`dmt3-text.woff2` is DMT3 Text, cut from [Pretendard](https://github.com/orioncactus/pretendard) 1.3.9's variable
font: every weight in one file, with the 2,350 Hangul syllables of KS X 1001, the compatibility jamo, Latin and
punctuation. A cut-down font is a modified version, and the SIL Open Font License reserves the original's name, so
it has a name of its own; it is under the same licence ([OFL-Pretendard.txt](OFL-Pretendard.txt)).
`dmt3-text-bold-hangul.woff2` is the same Hangul held at bold, for the Hangul in the wide titles (a DJ name). Both
are made again by `packaging/fonts/make_text.py`:

    python packaging/fonts/make_text.py PretendardVariable.woff2 opendmt3/server/web/static/fonts/dmt3-text.woff2 \
        opendmt3/server/web/static/fonts/dmt3-text-bold-hangul.woff2

The launcher keeps the full TrueType weights (Tk reads TrueType); the site's wide face is the launcher's
`DMT3Wide-Regular.ttf`.
