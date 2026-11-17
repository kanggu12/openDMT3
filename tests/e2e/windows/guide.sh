# The first-start guide's walk for the Wine tests: sourced by install_and_play.sh, offline_play.sh, play_a_song.sh,
# ingame.sh and remote_play.sh, which define C (the container), wait_s, windows and click_from_foot before.
#
# Each Next is followed until the guide shows the step it leads to, read from the screen, instead of a fixed wait: the
# game folder step keeps Next off while it searches for game folders, which took over 25 s on a busy machine.

# The guide's buttons at the menu column's foot (the column 248 pixels wide at 100 %, its room 18 pixels either side,
# 211 between, the foot 20 pixels over the window's bottom edge: app.make_foot), each clicked inside it, given as an
# offset from the launcher window's bottom-left corner (click_from_foot): Next at the right end of the row of Back and
# Next (34 pixels tall), and the PLAY slab that stands under Back in Next's place on the last step (STAGE START), as
# wide as the column holds and 54 pixels tall with its keyboard ring.
click_next() { click_from_foot 209 37; }
click_play() { click_from_foot 123 47; }

# Which step of the guide is on show (1 to 5), read from the screen: the five steps stand down the menu column under
# its mark (the list's top 86 pixels under the window's top at 100 %: the room over the mark, the mark, the room under
# it; each step 50 pixels tall, 4 apart: widgets.RailList). The step on show stands on a slab with a blue rule along
# its left edge, 3 pixels wide, 12 pixels in from the window's left; the other steps have no slab there. The rule is
# read down those 3 columns: its run of blue rows says which step it stands by. 0 when there is no such rule (not the
# guide), or more than one.
guide_step() {
  local geo px py
  geo=$(windows | grep "|openDMT3|" | head -1)
  [ -n "$geo" ] || { echo 0; return; }
  px=$(sed -E 's/.*Position: ([0-9]+),([0-9]+).*/\1/' <<<"$geo")
  py=$(sed -E 's/.*Position: ([0-9]+),([0-9]+).*/\2/' <<<"$geo")
  # The rule's three columns, from a little over the list's top down past its fifth step, one pixel a text line.
  docker exec -e DISPLAY=:99 "$C" sh -c "xwd -root -silent | convert xwd:- -crop 3x300+$((px + 12))+$((py + 80)) -depth 8 txt:-" \
    2>/dev/null | python3 -c '
import re, sys
# Each pixel a line "X,Y: (R,G,B..."; a rule pixel is the guide'"'"'s blue: its blue well over its red, and bright.
rows = {}
for m in re.finditer(r"^(\d+),(\d+): \((\d+),(\d+),(\d+)", sys.stdin.read(), re.M):
    if int(m.group(5)) > int(m.group(3)) + 80 and int(m.group(5)) > 150:
        rows[int(m.group(2))] = rows.get(int(m.group(2)), 0) + 1
# The runs of rows blue across the three columns: the rule is one run as tall as a step (50 rows; 30 or more counts).
runs, start = [], None
for y in range(301):
    if rows.get(y, 0) >= 2 and start is None:
        start = y
    elif rows.get(y, 0) < 2 and start is not None:
        runs.append((start, y))
        start = None
runs = [r for r in runs if r[1] - r[0] >= 30]
# The step whose row the rule starts in (the list 6 rows under the crop'"'"'s top, each row 50 tall and 4 apart; rounded,
# so the mark'"'"'s few pixels more or less on another system move nothing).
print(int(round((runs[0][0] - 6) / 54.0)) + 1 if len(runs) == 1 and runs[0][0] < 6 + 5 * 54 else 0)'
}

# Next, then until the guide shows step $1, at most $2 seconds; Next again while it still shows the step before (a
# step still at work keeps Next off, and a click then does nothing; the page moves only on a click, so a step is never
# skipped). 1 when the step never came.
next_to() {
  local end=$((SECONDS + $2))
  click_next
  wait_s 1
  while [ "$(guide_step)" != "$1" ]; do
    [ $SECONDS -ge $end ] && return 1
    wait_s 3
    [ "$(guide_step)" = "$(($1 - 1))" ] && click_next
  done
  return 0
}
