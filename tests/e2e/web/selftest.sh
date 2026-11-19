#!/bin/bash
# The layout check tested on itself: a copy of the tree with eight known faults planted, each of a kind run.sh must
# catch:
#   - the phone width no longer hides the song board's wide columns, so the table runs past the screen (sticks out);
#   - a page's own hero is a box of a fixed height again, so a long song title pushes its genre and composer out of
#     it (words cut off);
#   - the stacked rows of a phone's tables lose their cells' labels (a cell with no label);
#   - a row's actions are all made plain inline blocks again, so the link that looks like a button loses the box that
#     centres its words (a button's words out of its middle);
#   - the phone width no longer moves the menu into MENU's sheet, so its words stay in the bar's one row and run past
#     the screen (the phone menu cut);
#   - a group's name in English is set smaller than the rows under it again (a heading under its words);
#   - the small keys take wider sides than their role's (a key off its role's padding);
#   - the head's stage stands a step under the bar (its shards would end in that gap).
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
    '  .bar:not(.door-bar) .menu, .bar:not(.door-bar) .tools { display: none; }' \
    'h3 { display: flex; align-items: center; gap: 12px; font: 400 15px/1.3 var(--wide); letter-spacing: 0.04em;' \
    '.btn.small { height: var(--ctl-sm); min-width: 76px; font-size: 13px; padding: 0 12px; }' \
    '.hero { position: relative; overflow: hidden; height: auto; min-height: 220px;'; do
  grep -qF "$rule" "$CSS" || { echo "FAIL: the rule to break is not in site.css any more: $rule"; exit 1; }
done
sed -i 's/  .table .wide-only { display: none; }//' "$CSS"
sed -i 's/\.hero\.small { height: auto; min-height: 172px; }/.hero.small { height: 172px; }/' "$CSS"
sed -i 's/content: attr(data-label);/content: none;/' "$CSS"
sed -i 's/\.table \.actions > form { display: inline-block; }/.table .actions > * { display: inline-block; }/' "$CSS"
sed -i 's/  \.bar:not(\.door-bar) \.menu, \.bar:not(\.door-bar) \.tools { display: none; }/  .bar:not(.door-bar) .tools { display: none; }/' "$CSS"
sed -i 's/^h3 { display: flex; align-items: center; gap: 12px; font: 400 15px\/1.3 var(--wide);/h3 { display: flex; align-items: center; gap: 12px; font: 400 11px\/1.3 var(--wide);/' "$CSS"
sed -i 's/^\.btn\.small { height: var(--ctl-sm); min-width: 76px; font-size: 13px; padding: 0 12px; }/.btn.small { height: var(--ctl-sm); min-width: 76px; font-size: 13px; padding: 0 16px; }/' "$CSS"
sed -i 's/^\.hero { position: relative; overflow: hidden; height: auto; min-height: 220px;/.hero { position: relative; overflow: hidden; height: auto; min-height: 220px; margin-top: 12px;/' "$CSS"
OPENDMT3_REPO="$COPY" "$REPO/tests/e2e/web/run.sh" "$OUT/run" > "$OUT/run.txt" 2>&1
caught=$?
tail -3 "$OUT/run.txt"
missed=""
for said in "pages stick out" "pages cut words off" "pages have a cell with no label" \
    "pages have a button's words out of its middle" "pages cut the phone menu" \
    "pages have a heading smaller than the words under it" "pages have a key off its role's height or side padding" \
    "pages have the head's stage off the bar or under another box"; do
  grep -q "$said" "$OUT/run.txt" || missed="$missed '$said'"
done
if [ "$caught" -ne 0 ] && [ -z "$missed" ]; then
  echo "PASS: the planted fault was caught, each of the eight kinds"
else
  echo "FAIL: the check passed a tree with a planted fault (not said:$missed)"
  exit 1
fi
