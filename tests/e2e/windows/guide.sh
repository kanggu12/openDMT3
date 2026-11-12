# The first-start guide's walk for the Wine tests: sourced by install_and_play.sh, offline_play.sh, play_a_song.sh and
# ingame.sh, which define C (the container), wait_s, windows and click_from_corner before.
#
# Each Next is followed until the guide shows the step it leads to, read from the screen, instead of a fixed wait: the
# game folder step keeps Next off while it searches for game folders, which took over 25 s on a busy machine.

# Which step of the guide is lit (1 to 5), read from the screen: the column 30 pixels into the launcher's window
# across its list of steps, where the lit step's plate is blue (the first step's middle 183 pixels down, the others
# 64 apart, at 100 %); 0 when none is.
guide_step() {
  local geo px py
  geo=$(windows | grep "|openDMT3|" | head -1)
  [ -n "$geo" ] || { echo 0; return; }
  px=$(sed -E 's/.*Position: ([0-9]+),([0-9]+).*/\1/' <<<"$geo")
  py=$(sed -E 's/.*Position: ([0-9]+),([0-9]+).*/\2/' <<<"$geo")
  docker exec -e DISPLAY=:99 "$C" sh -c "xwd -root -silent | convert xwd:- -crop 1x340+$((px + 30))+$((py + 150)) -depth 8 txt:-" \
    2>/dev/null | python3 -c '
import re, sys
# Each pixel a line "0,Y: (R,G,B..."; the lit plate is blue: its blue well over its red, and bright.
rows = [int(m.group(1)) for m in re.finditer(r"^0,(\d+): \((\d+),(\d+),(\d+)", sys.stdin.read(), re.M)
        if int(m.group(4)) > int(m.group(2)) + 80 and int(m.group(4)) > 150]
print(int(round((sum(rows) / len(rows) + 150 - 183) / 64.0)) + 1 if rows else 0)'
}

# Next, then until the guide shows step $1, at most $2 seconds; Next again while it still shows the step before (a
# step still at work keeps Next off, and a click then does nothing; the page moves only on a click, so a step is never
# skipped). 1 when the step never came.
next_to() {
  local end=$((SECONDS + $2))
  click_from_corner 72 33
  wait_s 1
  while [ "$(guide_step)" != "$1" ]; do
    [ $SECONDS -ge $end ] && return 1
    wait_s 3
    [ "$(guide_step)" = "$(($1 - 1))" ] && click_from_corner 72 33
  done
  return 0
}
