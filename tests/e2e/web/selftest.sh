#!/bin/bash
# The layout check tested on itself: a copy of the tree with five known faults planted, each of a kind run.sh must
# catch:
#   - the phone width no longer hides the song board's wide columns, so the table runs past the screen (sticks out);
#   - a page's own hero is a box of a fixed height again, so a long song title pushes its genre and composer out of
#     it (words cut off);
#   - the stacked rows of a phone's tables lose their cells' labels (a cell with no label);
#   - a row's actions are all made plain inline blocks again, so the link that looks like a button loses the box that
#     centres its words (a button's words out of its middle);
#   - the phone menu's words get their wider padding back, so the five of them fit a 390 px screen and not a 360 px
#     one (the phone menu cut).
#
#   tests/e2e/web/selftest.sh OUT_DIR
set -u
OUT=$(realpath -m "${1:?usage: selftest.sh OUT_DIR}")
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
COPY="$OUT/tree"
rm -rf "$COPY" && mkdir -p "$COPY"
# Only what the check builds and runs from.
cp -r "$REPO/opendmt3" "$REPO/packaging" "$REPO/.dockerignore" "$REPO/LICENSE" "$COPY/" && mkdir -p "$COPY/tests/e2e" && cp -r "$REPO/tests/e2e/web" "$COPY/tests/e2e/"
CSS="$COPY/opendmt3/server/web/static/site.css"
# Each rule to break must be there as written: a fault that plants nothing would prove nothing.
for rule in '  .table .wide-only { display: none; }' '.hero.small { height: auto; min-height: 172px; }' \
    'content: attr(data-label);' '.table .actions > form { display: inline-block; }' \
    '  .menu a { padding: 8px 4px; font-size: 11px;'; do
  grep -qF "$rule" "$CSS" || { echo "FAIL: the rule to break is not in site.css any more: $rule"; exit 1; }
done
sed -i 's/  .table .wide-only { display: none; }//' "$CSS"
sed -i 's/\.hero\.small { height: auto; min-height: 172px; }/.hero.small { height: 172px; }/' "$CSS"
sed -i 's/content: attr(data-label);/content: none;/' "$CSS"
sed -i 's/\.table \.actions > form { display: inline-block; }/.table .actions > * { display: inline-block; }/' "$CSS"
sed -i 's/  \.menu a { padding: 8px 4px; font-size: 11px;/  .menu a { padding: 8px 9px; font-size: 11px;/' "$CSS"
OPENDMT3_REPO="$COPY" "$REPO/tests/e2e/web/run.sh" "$OUT/run" > "$OUT/run.txt" 2>&1
caught=$?
tail -3 "$OUT/run.txt"
missed=""
for said in "pages stick out" "pages cut words off" "pages have a cell with no label" \
    "pages have a button's words out of its middle" "pages cut the phone menu"; do
  grep -q "$said" "$OUT/run.txt" || missed="$missed '$said'"
done
if [ "$caught" -ne 0 ] && [ -z "$missed" ]; then
  echo "PASS: the planted fault was caught, each of the five kinds"
else
  echo "FAIL: the check passed a tree with a planted fault (not said:$missed)"
  exit 1
fi
