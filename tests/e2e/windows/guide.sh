# The first-start guide's walk for the Wine tests: sourced by install_and_play.sh, offline_play.sh, play_a_song.sh,
# ingame.sh and remote_play.sh, which define C (the container), wait_s, windows and click_from_corner before.
#
# Each Next is followed until the guide shows the step it leads to, read from the screen, instead of a fixed wait: the
# game folder step keeps Next off while it searches for game folders, which took over 25 s on a busy machine.

# The guide's buttons in the strip along the window's foot, each clicked in its middle, given as an offset from the
# launcher window's bottom-right corner (click_from_corner) at 100 %: Next, and the PLAY slab that stands in Next's
# place on the last step (STAGE START).
click_next() { click_from_corner 60 39; }
click_play() { click_from_corner 140 42; }

# Which step of the guide is on show (1 to 5), read from the screen: the five steps stand across the window under its
# bar (64 pixels tall at 100 %), each over a rule in the 60 pixels below the bar (widgets.Header._draw_steps). The rule
# of the step on show is blue and 3 pixels thick, the steps taken keep a blue rule 2 pixels thick, the steps to come a
# grey one; each rule is read near its right end, where neither the step's number nor its name reaches. 0 when the
# rules are not those of the guide (no rule 3 pixels thick, or more than one).
guide_step() {
  local geo px py w
  geo=$(windows | grep "|openDMT3|" | head -1)
  [ -n "$geo" ] || { echo 0; return; }
  px=$(sed -E 's/.*Position: ([0-9]+),([0-9]+).*/\1/' <<<"$geo")
  py=$(sed -E 's/.*Position: ([0-9]+),([0-9]+).*/\2/' <<<"$geo")
  w=$(sed -E 's/.*Geometry: ([0-9]+)x([0-9]+).*/\1/' <<<"$geo")
  # The band under the bar, the window's whole width, one text line a pixel.
  docker exec -e DISPLAY=:99 "$C" sh -c "xwd -root -silent | convert xwd:- -crop ${w}x60+$px+$((py + 64)) -depth 8 txt:-" \
    2>/dev/null | python3 -c '
import re, sys
width = int(sys.argv[1])
# Each pixel a line "X,Y: (R,G,B..."; a rule pixel of the guide is blue: its blue well over its red, and bright.
blue = {}
for m in re.finditer(r"^(\d+),(\d+): \((\d+),(\d+),(\d+)", sys.stdin.read(), re.M):
    if int(m.group(5)) > int(m.group(3)) + 80 and int(m.group(5)) > 150:
        blue[int(m.group(1))] = blue.get(int(m.group(1)), 0) + 1
# The five steps share the width between the margins (32 pixels each side), 10 pixels apart.
cell = (width - 2 * 32 - 4 * 10) / 5.0
thick = []
for i in range(5):
    right = 32 + i * (cell + 10) + cell
    # The 25 columns 5 to 30 pixels short of the right end of the rule: its thickness there, as most of them have it.
    counts = sorted(blue.get(x, 0) for x in range(int(right) - 30, int(right) - 5))
    thick.append(counts[len(counts) // 2])
# One rule 3 thick, the others taken (2) or to come (0): the guide, on the step whose rule is the thick one.
print(thick.index(3) + 1 if thick.count(3) == 1 and all(t in (0, 2, 3) for t in thick) else 0)' "$w"
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
