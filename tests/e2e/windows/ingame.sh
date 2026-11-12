#!/bin/bash
# openDMT3's in-game layer on the real client, under Wine on a virtual screen with no network:
#   1. On this PC, from the installer (as install_and_play.sh): the guide, a DJ, PLAY, the card login. The bar came
#      down by itself at the game's first screen, its 3 s and its fade on the screen and no more. The pointer over the
#      game is openDMT3's dart, read through XFixes,
#      up and pressed. The pointer in the game's top quarter brings nothing but the mark at the top centre; a click on
#      the game, then the pointer resting on the mark: no bar for 1.5 s after the click, then the bar; resting at the
#      very top edge brings it too; its X drops the question down under it (no line on the game's menus), Keep playing
#      keeps the game 15 s more; Esc and Alt+F4 do nothing (the game alive, no question); the window's close (the
#      taskbar's, as WM_DELETE_WINDOW: ingame/close.py) asks the same question; the bar's menu chip drops the menu
#      down, Esc closes it; a toast hangs from the top edge; full screen to a window (its title bar and borders, no
#      buttons; the bar by itself after the switch, its 3 s and its fade) and back; minimise and back (the taskbar's restore:
#      ingame/restore.c); the X again, Quit the game, and the game ends with exit code 0 and the launcher's window
#      says so. Where the layer drew is read from the chain's measuring dump of one frame without it and with it
#      (ingame/layer.py): in the bar's band, under the X or the menu chip, the toast's place, the mark's, never the
#      middle half of the game.
#   2. Offline, from openDMT3-cmd.exe with VSync off, pacing locked to the music, the frame rate chip, a sound device
#      and the picture defaults (upscale fsr1, sharpness 50, no anti-aliasing) chosen: at most one frame is queued, its
#      log names the device it opened and the picture options it got; each of the layer's parts shown for 8 s in turn
#      with 8 s of nothing between holds 60 a second wherever the game alone did next to it on a quiet machine
#      (ingame/pace.py, ingame/quiet.py: rounds wait for other programs' load to fall, 25 minutes at most, then the
#      pacing is not judged and the test fails; Wine's software renderer misses 60 by itself in some stretches, which
#      are not judged either), and the chip's own CPU time, its updates and their GDI drawings (none) are within its
#      targets (ingame/costs.py); the chip is in the bottom right corner above the game's FREE PLAY, the menu's Show
#      FPS hides and shows it; in the tutorial's song, the X's question (with its line) holds the game still (two
#      screenshots 2 s apart the same in the middle half, the chip hidden, the sound faded out, held, and played again
#      from where it stopped with a fade in), Keep playing lets it go on; Esc does nothing; a minute of the song played
#      all over the screen (ingame/player.py: the top band and its edge included, the pointer resting at the top edge
#      between notes a little under the 1.5 s of quiet) never brings the bar on the screen, and a call on purpose
#      after 1.6 s of quiet brings it, gone 0.9 s after the pointer leaves it; minimised, the song is held and goes on
#      when it is back; Quit ends it, and --play returns.
#   3. Offline again with sharpness 80 and SMAA High: the post-process chain runs them (its measuring dump: the frame
#      presented is the chain's SMAA High then FSR 1 at 80, FSR 1 differs from bilinear on the same frame, and the
#      screen matches the chain's output where the game's picture holds still); before that, on the title screen,
#      what each part adds to a frame as it is drawn (OPENDMT3_LAYER_TIMING=frame: the chain's and the layer's work
#      timed whole; turns with the part and without, ingame/costs.py): the chip's under 0.2 ms at the median turn,
#      the bar's and the question's said; Quit ends it. The frame rate is not judged here: under Wine the passes run
#      on the CPU's software renderer, where SMAA High's cost alone can take a frame's 16.67 ms on a busy machine, and
#      the measuring stalls each frame; the pacing is judged in 2, on the defaults. The safety net is off for this
#      play (OPENDMT3_SAFETY=off), so the options checked are the ones chosen.
#   4. Offline with NVIDIA NIS and SMAA Ultra, the heaviest choice, which makes frames late on Wine's software
#      renderer: the safety net steps it down to bilinear with no anti-aliasing, its toast shows, the counter is back
#      at 60 a second evenly after the last step, and the launcher's log has the steps.
#   Over all four: every part of the layer has its textures made when the layer first draws at a size (the game's
#   loading, the changes between full screen and a window), never while a game plays (the layer's log says each).
#   The safety net is off in 1 to 3 (on Wine's software renderer a busy machine makes it step FSR 1 down, and its
#   toast would be one more part on the screen than the step checked) and on in 4, which tests it.
#   OPENDMT3_WINE_GPU=1 draws on this PC's graphics card through WSL instead of the CPU (gpu.sh): the game's process
#   must then draw through WSL's D3D12, and in 4 the heaviest choice is not heavy for a GPU: the net must leave it as
#   it is (no step, no note) while the game holds 60 evenly.
#   Screenshots of each stage land in OUT_DIR; the run fails at the first stage that does not happen.
#
#   tests/e2e/windows/ingame.sh GAME_PARENT RELEASES_DIR OUT_DIR [LINK_SOURCE] [WINE_DLLS]
#
# The arguments are install_and_play.sh's. GAME_PARENT is copied into OUT_DIR first (links stay links), so every
# run starts from the same folder and the one given is never written.
set -u
SRC=$(realpath "${1:?usage: ingame.sh GAME_PARENT RELEASES_DIR OUT_DIR [LINK_SOURCE] [WINE_DLLS]}")
REL=$(realpath "${2:?}")
OUT=$(realpath -m "${3:?}")
LINKS=${4:-}
DLLS=${5:-}
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$OUT"
# The renderer: the CPU image by default, the GPU image with OPENDMT3_WINE_GPU=1 (gpu.sh).
. "$HERE/gpu.sh"
# A fresh copy of the test game for this run.
rm -rf "$OUT/game"
mkdir -p "$OUT/game"
cp -a "$SRC/." "$OUT/game/"
PARENT="$OUT/game"
NAME=$(basename "$SRC")
# The Wine image with python3-xlib for XFixes (built once from this folder's ingame/Dockerfile; the GPU image has it).
wine_on_gpu || docker image inspect opendmt3-wine-ingame:local >/dev/null 2>&1 \
  || docker build -q -t opendmt3-wine-ingame:local "$HERE/ingame" >/dev/null || { echo "FAIL: the test image"; exit 1; }
# The taskbar's restore as a Windows program (ingame/restore.c), built with the DLL's compiler (its image made as
# native/cardreader/build.sh makes it).
docker image inspect opendmt3-mingw:local >/dev/null 2>&1 || {
  ctx=$(mktemp -d)
  printf 'FROM debian:12\nRUN apt-get update && apt-get install -y --no-install-recommends gcc-mingw-w64-i686 && rm -rf /var/lib/apt/lists/*\n' > "$ctx/Dockerfile"
  docker build -q -t opendmt3-mingw:local "$ctx" >/dev/null
  rm -rf "$ctx"
}
docker run --rm --network none -v "$HERE/ingame:/src:ro" -v "$OUT:/out" opendmt3-mingw:local \
  i686-w64-mingw32-gcc -O2 -o /out/restore.exe /src/restore.c -luser32 || { echo "FAIL: the restore helper did not build"; exit 1; }
C=$(wine_name opendmt3-ingame)
docker rm -f "$C" >/dev/null 2>&1
mounts=(-v "$PARENT:/root/Desktop/$NAME" -v "$REL:/rel:ro" -v "$OUT:/out" -v "$HERE/ingame:/probe:ro")
[ -n "$LINKS" ] && mounts+=(-v "$LINKS:$LINKS:ro")
[ -n "$DLLS" ] && mounts+=(-v "$(realpath "$DLLS"):/dlls:ro")
# The layer's log goes to OUT_DIR: the launcher hands its environment on to the game.
# The chain's measuring dump into OUT_DIR too (dump.now, toast.now: only the tests set it).
# The safety net off (measuring: OPENDMT3_SAFETY=off) wherever the layer's places and its frames are checked: on Wine's
# software renderer a busy machine makes it step FSR 1 down, and its toast is one more part on the screen than the
# step being checked; the run that tests the net (4) turns it on.
docker run -d --name "$C" --network none -e 'OPENDMT3_INGAME_LOG=Z:\out\ingame.log' -e 'OPENDMT3_POSTFX_DUMP=Z:\out' \
  -e OPENDMT3_SAFETY=off "${WINE_RUN_ARGS[@]}" "${mounts[@]}" \
  "$(wine_image opendmt3-wine-ingame:local)" bash -c '
  # The virtual screen kept off the GPU (gpu.sh; plain Xvfb on the CPU image).
  env -u GALLIUM_DRIVER -u LD_LIBRARY_PATH Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp >/dev/null 2>&1 &
  export WINEPREFIX=/w DISPLAY=:99 WINEDLLOVERRIDES="mscoree,mshtml=" WINEDEBUG=-all
  # Silent sound: the default, and a second output with a name of its own, so a device can be chosen.
  printf "pcm.!default { type null }\npcm.second { type null\n hint { show on\n description \"Second output\" } }\nctl.!default { type hw card 0 }\n" > /etc/asound.conf
  wineboot -i >/dev/null 2>&1; wineserver -w
  [ -d /dlls ] && cp /dlls/*.dll /w/drive_c/windows/syswow64/
  touch /out/.prefix-ready
  wine /rel/openDMT3-win-Setup.exe > /out/setup.log 2>&1 &
  sleep infinity' >/dev/null
rm -f "$OUT/ingame.log"
wait_s() { python3 -c "import time; time.sleep($1)"; }
# The whole virtual screen (import composes the layer's shaped windows over the game, as the screen shows them).
shot() { docker exec -e DISPLAY=:99 "$C" sh -c "import -window root /out/$1.png"; echo "  $OUT/$1.png"; }
x() { docker exec -e DISPLAY=:99 "$C" sh -c "$1"; }
windows() { x 'for w in $(xdotool search --onlyvisible --name . 2>/dev/null); do echo "$w|$(xdotool getwindowname $w)|$(xdotool getwindowgeometry $w | tr "\n" " ")"; done'; }
wait_for() {   # wait_for <title regex> <seconds>
  local end=$((SECONDS + $2))
  while [ $SECONDS -lt $end ]; do
    windows | grep -qE "$1" && return 0
    wait_s 1
  done
  return 1
}
# Wait for a line in the layer's log (a regex), up to some seconds.
wait_log() {
  local end=$((SECONDS + $2))
  until grep -qE "$1" "$OUT/ingame.log" 2>/dev/null || [ $SECONDS -gt $end ]; do wait_s 1; done
  grep -qE "$1" "$OUT/ingame.log" 2>/dev/null
}
# How many lines of the layer's log match (a regex); and a wait until more than a count do (the log already holds
# such lines from earlier steps, so a step is judged by the new one it adds).
seen() { grep -cE "$1" "$OUT/ingame.log" 2>/dev/null; }
# The game's frames of over 100 ms between two moments on the log's clock (ms), their lengths summed in seconds, from
# the counter's lines whose 2 s overlap them (each says its longest frame). The layer looks at its clock once a frame
# and its motion moves at most 100 ms in one (a load moves nothing at once), so on a busy machine such a frame makes a
# bar stay or fade that much longer: the upper bounds below grow by it, and with none they are as written.
stall_s() {
  python3 - "$OUT/ingame.log" "$1" "$2" <<'EOF'
import re, sys
log, a, b = open(sys.argv[1]).read(), int(sys.argv[2]), int(sys.argv[3])
lines = [(int(m.group(1)), float(m.group(2))) for m in re.finditer(r"^(\d+) frames: .*?longest ([\d.]+),", log, re.M)]
# Each line's 2 s: from the line before it (the first one's from 2 s before).
wins = [(lines[i - 1][0] if i else end - 2000, end, longest) for i, (end, longest) in enumerate(lines)]
print("%.2f" % (sum(longest for prev, end, longest in wins if end > a and prev < b and longest > 100.0) / 1000.0))
EOF
}
# The time on the log's clock of the first "bar gone" line after a moment (ms), waited for up to $2 s (0: none came).
gone_after() {
  local end=$((SECONDS + $2)) t
  while :; do
    t=$(grep -oE "^[0-9]+ layer: bar gone after" "$OUT/ingame.log" | cut -d' ' -f1 | awk -v a="$1" '$1 > a' | head -1)
    { [ -n "$t" ] || [ $SECONDS -gt $end ]; } && break
    wait_s 0.5
  done
  echo "${t:-0}"
}
wait_more() {
  local end=$((SECONDS + $3))
  until [ "$(seen "$1")" -gt "$2" ] || [ $SECONDS -gt $end ]; do wait_s 0.5; done
  [ "$(seen "$1")" -gt "$2" ]
}
fail() {
  echo "FAIL: $*"; windows; shot 99-failure
  # The load sampler of the pacing's rounds, when it runs.
  [ -n "${sampler:-}" ] && kill "$sampler" 2>/dev/null
  docker rm -f "$C" >/dev/null; exit 1
}
# The layer's textures in the game whose log this is (WHICH names it): every part's made when the layer first drew at
# a size (the game's loading, the changes between full screen and a window), none while the game played.
textures() {
  local made
  made=$(grep -c "layer: [0-9]* parts' textures made for" "$OUT/ingame.log" 2>/dev/null)
  echo "  the layer's textures in $1: made ${made:-0} times, at its first frame at a size ($(grep -o "parts' textures made for [0-9x]* in [0-9.]* ms" "$OUT/ingame.log" 2>/dev/null | sed "s/parts' textures made for //" | paste -sd, - | sed 's/,/, /g'))"
  [ "${made:-0}" -ge 1 ] || fail "the layer's textures were not made at its first frame ($1)"
  grep "textures made while the game plays" "$OUT/ingame.log" | head -3
  grep -q "textures made while the game plays" "$OUT/ingame.log" && fail "a part's textures were made while the game played ($1)"
  return 0
}
click_from_corner() {
  local geo px py w h
  geo=$(windows | grep "|openDMT3|" | head -1)
  px=$(sed -E 's/.*Position: ([0-9]+),([0-9]+).*/\1/' <<<"$geo"); py=$(sed -E 's/.*Position: ([0-9]+),([0-9]+).*/\2/' <<<"$geo")
  w=$(sed -E 's/.*Geometry: ([0-9]+)x([0-9]+).*/\1/' <<<"$geo"); h=$(sed -E 's/.*Geometry: ([0-9]+)x([0-9]+).*/\2/' <<<"$geo")
  x "xdotool mousemove $((px + w - $1)) $((py + h - $2)) sleep 0.15 click 1"
}
# The guide's walk, each Next followed until its step shows (guide.sh).
. "$(cd "$(dirname "$0")" && pwd)/guide.sh"
# A program still running under Wine (an ended one may stay as a zombie of the shell that started it: not counted).
running() { x "ps -eo stat=,args= | grep -v '^Z' | grep -q '$1'"; }
game_alive() { running 'Client (openDMT3)\.exe'; }
# Where the layer's parts are on the 1920x1080 screen (native/cardreader/logic.c ui_layout, in game pixels times
# 1080 / 768): the bar's chips 50 x 34 in its middle (35 down), the X's middle 37 from the picture's right edge, full screen's 56
# further, minimise's 56 more, the menu's 66 more; the question 300 wide under the X, its answers 129 x 32, 40 under
# its top (76 down) on the game's menus and 64 during a song (its line above them); the menu 216 wide under its chip.
U=1.40625
at() { python3 -c "print('%d %d' % ($1, $2))"; }
# The game's picture keeps its own shape on this 16:9 screen (the launcher's default): 1800 x 1080 from 60 across, bars
# beside it (native/cardreader/logic.c picture_rect); the layer lies in it, so its right edge is at 1860.
PR=1860
X_AT=$(at "$PR - $U * 37" "$U * 35"); FULL_AT=$(at "$PR - $U * 93" "$U * 35")
MIN_AT=$(at "$PR - $U * 149" "$U * 35"); MENU_AT=$(at "$PR - $U * 215" "$U * 35")
KEEP_AT=$(at "$PR - $U * 231.5" "$U * (76 + 40 + 16)"); KEEP_SONG_AT=$(at "$PR - $U * 231.5" "$U * (76 + 64 + 16)")
# The monotonic clock in milliseconds, the layer's log's.
now_ms() { python3 -c 'import time; print(int(time.monotonic() * 1000))'; }
# Whether the bar is on the screen now, by the layer's log: its last "on the screen" line after its last "gone" line.
bar_up() {
  local on gone
  on=$(grep -n "layer: bar on the screen" "$OUT/ingame.log" 2>/dev/null | tail -1 | cut -d: -f1)
  gone=$(grep -n "layer: bar gone after" "$OUT/ingame.log" 2>/dev/null | tail -1 | cut -d: -f1)
  [ -n "$on" ] && [ "$on" -gt "${gone:-0}" ]
}
# The bar: the pointer moved to the very top edge with its button up, from the game's middle, resting there (away from
# the mark at the top centre, which brings it too); it comes 150 ms later once the game has had no press for 1.5 s (a
# click just before makes it wait that long). A game loading (a song its own timer chose on the song select) draws no
# frame and reads no pointer for seconds, and a click made then would land on the game: the rest is made again while
# the log does not say the bar is on the screen, three times at most.
show_bar() {
  local i
  for i in 1 2 3; do
    x "xdotool mousemove 1300 540 sleep 0.2 mousemove 1300 0"; wait_s 2
    bar_up && return 0
  done
}
# The pointer away from the layer (the bar goes 0.7 s after it leaves).
away() { x "xdotool mousemove 960 700"; wait_s 1.5; }
# The game's window given the keyboard (Wine, with no window manager, may leave it with the launcher's window).
focus() { x "xdotool search --name '^ClientApp$' windowfocus --sync" 2>/dev/null; }
# The frame rate chip on or off through the menu's Show FPS (its second row: Down, Enter), the menu closed after.
fps_menu() {
  show_bar; x "xdotool mousemove $MENU_AT sleep 0.4 click 1"; wait_s 1; focus
  x "xdotool key Down"; wait_s 0.3; x "xdotool key Return"; wait_s 0.5; x "xdotool key Escape"; away
}
# Quit through the bar's X: its question, Right to Quit the game, Enter.
quit_by_x() { show_bar; x "xdotool mousemove $X_AT sleep 0.4 click 1"; wait_s 1.5; focus; x "xdotool key Right"; wait_s 0.5; x "xdotool key Return"; }
# Ask the chain's measuring dump for this frame and the same frame with the layer, and wait for both.
ask_dump() {
  echo "$1 ${2:-}" > "$OUT/dump.now"
  local end=$((SECONDS + 60))
  while [ -f "$OUT/dump.now" ] && [ $SECONDS -lt $end ]; do wait_s 0.5; done
  [ ! -f "$OUT/dump.now" ]
}
# Where the layer drew on a dumped frame: the zones named, never the middle half (ingame/layer.py).
drew() { local label=$1; shift; ask_dump "$label" || fail "the chain did not write the frame $label"; python3 "$HERE/ingame/layer.py" "$OUT" "$label" "$@"; }
LOG=/w/drive_c/users/root/AppData/Roaming/openDMT3/logs/launcher.log
SETTINGS=/w/drive_c/users/root/AppData/Roaming/openDMT3/launcher.json
APP='C:\users\root\AppData\Local\openDMT3\current\openDMT3-cmd.exe'

echo "== installer, guide, PLAY (as install_and_play.sh)"
end=$((SECONDS + 120)); until [ -f "$OUT/.prefix-ready" ] || [ $SECONDS -gt $end ]; do wait_s 1; done
wait_for "\|openDMT3 Setup\|" 120 || fail "the installer's window did not open"
wait_s 2
x 'xdotool search --name "openDMT3 Setup" windowfocus --sync key Return'
wait_s 10
windows | grep -q "|openDMT3 Setup|" && x 'xdotool search --name "openDMT3 Setup" windowfocus --sync key Return'
wait_for "\|openDMT3\|" 120 || fail "the launcher did not open after the installer"
wait_s 6
next_to 2 30 || fail "the guide did not go to its game folder step"
next_to 3 150 || fail "the guide's game folder step did not let it go on"
next_to 4 30 || fail "the guide did not go to its LOG IN step"
wait_s 2
win=$(windows | grep "|openDMT3|" | head -1 | cut -d'|' -f1)
x "xdotool windowfocus --sync $win; xdotool type --delay 60 NOVA; xdotool key Tab; xdotool type --delay 60 pass1234; xdotool key Tab; xdotool type --delay 60 'DJ NOVA'; xdotool key Return"
wait_s 3
next_to 5 30 || fail "the guide did not go to its last step"
wait_s 3; shot 01-ready
click_from_corner 72 33
wait_for "\|ClientApp\|" 120 || fail "the game's window did not open"
end=$((SECONDS + 120)); until x "grep -q 'online: client' $LOG" 2>/dev/null || [ $SECONDS -gt $end ]; do wait_s 2; done
wait_log "layer: attached" 60 || fail "the in-game layer did not attach to the game's window"
# On the GPU: the game's own process draws through WSL's D3D12 (no quiet fall back to the CPU).
gpu_proof "$C" 'Client (openDMT3).exe' || fail "the game is not drawn on the GPU"
grep -q "hooks: sound 1, picture 1, keys 1" "$OUT/ingame.log" || fail "the layer did not take the game's imports"
grep -q "picture: vsync on, pacing even" "$OUT/ingame.log" || fail "VSync on with even pacing (the default) was not taken"
wait_s 10; shot 02-title
x "xdotool mousemove 960 830 mousedown 1 sleep 0.15 mouseup 1"
end=$((SECONDS + 60)); until x "grep -q 'logged in: NOVA' $LOG" 2>/dev/null || [ $SECONDS -gt $end ]; do wait_s 2; done
x "grep -q 'logged in: NOVA (DJ NOVA)' $LOG" || fail "the card login did not reach the server"
wait_s 8

echo "== the pointer over the game (XFixes)"
x "xdotool mousemove 700 700 sleep 0.3 mousemove 705 705"; wait_s 0.6
up=$(x "python3 /probe/pointer.py /out/pointer-up.png")
echo "  up: $up"
# Pressed where the game has nothing to touch (the bottom left corner). A busy machine may keep the game from hearing
# the press for a while (a load average of 48 kept it past 0.6 s): read again until the chrome goes, 3 s at most.
x "xdotool mousemove 40 1040 sleep 0.3 mousedown 1"
for i in 1 2 3 4 5; do
  wait_s 0.6
  down=$(x "python3 /probe/pointer.py /out/pointer-down.png")
  read -r _ _ _ _ _ _ _ _ _ chrome_now <<<"$down"
  [ "${chrome_now:-99}" -lt 5 ] && break
done
x "xdotool mouseup 1"
echo "  pressed: $down"
# Ours: 32 pixels with the hot spot at the dart's tip (3,3); up it has its chrome edge round a blue core, pressed it
# is all blue (no chrome) and a little smaller.
read -r _ size _ hot _ opaque_up _ blue_up _ chrome_up <<<"$up"
read -r _ size_d _ hot_d _ opaque_d _ blue_d _ chrome_d <<<"$down"
[ "$size" = 32x32 ] && [ "$hot" = 3,3 ] || fail "the pointer is not openDMT3's dart ($up)"
[ "$chrome_up" -gt 20 ] && [ "$blue_up" -gt 20 ] || fail "the pointer has not the dart's chrome and blue ($up)"
[ "$chrome_d" -lt 5 ] && [ "$blue_d" -gt "$blue_up" ] && [ "$opaque_d" -lt "$opaque_up" ] \
  || fail "the pressed pointer is not the dart's pressed look ($down)"

echo "== the bar by itself, the mark, the guard, the top edge, the question under the X, Keep playing, Esc and Alt+F4, the window's close, the menu, a toast; nothing in the middle"
# The bar came down by itself when the game's first screen showed (and went 3 s later).
grep -q "layer: bar shown by itself for 3 s (the game's first screen)" "$OUT/ingame.log" \
  || fail "the bar did not show by itself at the game's first screen"
# Its time on the screen then: its 3 s and its fade (0.3 s), no more (the pointer was not on it).
first=$(grep -oE "layer: bar gone after [0-9.]+ s on the screen" "$OUT/ingame.log" | head -1 | grep -oE "[0-9.]+")
revealed=$(grep -m1 -oE "^[0-9]+ layer: bar shown by itself" "$OUT/ingame.log" | cut -d' ' -f1)
slow=$(stall_s "${revealed:-0}" "$(python3 -c "print(int(${revealed:-0} + 1000 * ${first:-0}))")")
echo "  the bar by itself at the first screen: ${first:-?} s on the screen (the game's frames over 100 ms then: $slow s)"
python3 -c "import sys; sys.exit(0 if 3.0 <= float('${first:-0}') <= 3.8 + $slow else 1)" \
  || fail "the bar by itself at the first screen was ${first:-?} s on the screen (3.3 s wanted, frames over 100 ms $slow s)"
# Moving in the top quarter (not its edge) brings nothing: a song played with the mouse never shows the bar. The mark
# alone is there, at the top centre.
x "xdotool mousemove 960 540 sleep 0.2 mousemove 1500 230 sleep 0.2 mousemove 1650 150"; wait_s 0.8
drew r0 mark || fail "something of the layer but the mark showed without the pointer at the top edge"
grep -q "layer: bar shown (" "$OUT/ingame.log" && fail "the bar came without the pointer at the top edge"
# A click on the game (where it has nothing to touch, as above), then the pointer onto the mark at once: no bar for
# 1.5 s after the click, then the bar.
x "xdotool mousemove 40 1040 click 1"; clicked=$(now_ms)
x "xdotool mousemove 960 14"; wait_s 0.3
# Looked at only while it is surely under 1.5 s since the click (a slow machine is not judged here: the bar's own line
# below says how long after the press it came).
if [ $(($(now_ms) - clicked)) -lt 1200 ]; then
  grep -q "layer: bar shown (" "$OUT/ingame.log" && fail "the bar came within 1.5 s of a click on the game"
fi
shot 03a-mark-lit
wait_log "layer: bar shown \(the pointer rested on the mark" 5 || fail "resting on the mark did not bring the bar"
quiet=$(grep -oE "rested on the mark, [0-9.]+ s after the game's last press" "$OUT/ingame.log" | tail -1 | grep -oE "[0-9.]+ s" | cut -d' ' -f1)
echo "  the bar came from the mark ${quiet:-?} s after the click on the game"
python3 -c "import sys; sys.exit(0 if 1.5 <= float('${quiet:-0}') < 3 else 1)" || fail "the bar came ${quiet:-?} s after the click (1.5 s wanted)"
away
show_bar; shot 03-bar
wait_log "layer: bar shown \(the pointer rested at the top edge" 5 || fail "the bar did not come at the top edge"
drew r1 bar || fail "the bar is not where it belongs, or something is in the middle"
x "xdotool mousemove $X_AT"; wait_s 0.6; shot 04-bar-x-under-pointer
x "xdotool click 1"; wait_s 1.0; shot 05-question
wait_log "layer: question opened" 5 || fail "the X did not ask"
# After the login the game's own timers may have started a song by now: the question has its line exactly when one
# plays, and the game is held still under it only then (the title screen of the offline plays checks it has none).
keep=$KEEP_AT
if grep "layer: question opened" "$OUT/ingame.log" | tail -1 | grep -q "with its line"; then
  wait_log "hold: the game held still" 3 || fail "the question had a song's line with no song held"
  echo "  a song plays: the question with its line, the game held"
  keep=$KEEP_SONG_AT
else
  grep -q "hold: the game held still" "$OUT/ingame.log" && fail "the game was held under a question with no song's line"
  echo "  no song plays: the question with no line"
fi
drew q1 bar question || fail "the question did not drop down under the X, or something is in the middle"
x "xdotool mousemove $keep sleep 0.3 click 1"; wait_s 1.0; shot 06-kept-playing
wait_log "layer: closed, back to the game" 5 || fail "Keep playing did not close the question"
wait_s 15
game_alive || fail "the game closed after Keep playing"
windows | grep -q "|ClientApp|" || fail "the game's window went after Keep playing"
# Esc and Alt+F4 do nothing: no question, the game goes on (it never sees Esc: its own would end it at once).
asked=$(seen "layer: question opened")
focus
x "xdotool key Escape"; wait_s 1; x "xdotool key alt+F4"; wait_s 2; shot 06a-esc-altf4
wait_log "layer: Esc kept from the game" 3 || fail "Esc did not reach the game's window"
wait_log "layer: Alt\+F4 does nothing" 3 || fail "Alt+F4 did not reach the game's window"
[ "$(seen "layer: question opened")" = "$asked" ] || fail "Esc or Alt+F4 opened the question"
game_alive || fail "Esc or Alt+F4 ended the game"
# The window's close from outside (the taskbar's, sent as WM_DELETE_WINDOW): the same question; Enter keeps playing.
x "python3 /probe/close.py ClientApp"
wait_more "layer: question opened" "$asked" 5 || fail "the window's close did not ask"
wait_s 1; shot 06b-close-asks
focus; x "xdotool key Return"; wait_s 1
game_alive || fail "the game ended after the window's close"
away
show_bar
closed=$(seen "layer: closed, back to the game")
x "xdotool mousemove $MENU_AT sleep 0.4 click 1"; wait_s 1.0; shot 06c-menu
wait_log "layer: menu opened" 5 || fail "the menu chip did not open the menu"
drew m1 bar menu || fail "the menu did not drop down under its chip, or something is in the middle"
focus
x "xdotool key Escape"; wait_s 0.5
wait_more "layer: closed, back to the game" "$closed" 3 || fail "Esc did not close the menu"
away
echo "Picture quality lowered to keep 60 FPS (Smooth upscale)" > "$OUT/toast.now"
wait_log "layer: toast shown" 10 || fail "the toast was not shown"
wait_s 0.8; shot 06d-toast
drew t1 toast || fail "the toast is not hanging from the top edge, or something is in the middle"
game_alive || fail "the game ended while the layer was shown"
wait_s 7

echo "== full screen to a window and back, minimise and back"
show_bar
# The chip, and the pointer away from the bar at once: the bar by itself for its 3 s after the switch, then gone.
x "xdotool mousemove $FULL_AT sleep 0.4 click 1 sleep 0.05 mousemove 960 700"; wait_s 1.5; shot 06e-window
wait_log "layer: in a window" 5 || fail "the full screen chip did not put the game in a window"
wait_s 3.5
switched=$(grep -oE "^[0-9]+ layer: in a window" "$OUT/ingame.log" | tail -1 | cut -d' ' -f1)
gone=$(gone_after "${switched:-0}" 10)
slow=$(stall_s "${switched:-0}" "$gone")
echo "  after the switch the bar was $(python3 -c "print('%.2f' % ((${gone:-0} - ${switched:-0}) / 1000.0))") s on the screen (the game's frames over 100 ms then: $slow s)"
python3 -c "import sys; d = (${gone:-0} - ${switched:-0}) / 1000.0; sys.exit(0 if 3.0 <= d <= 3.8 + $slow else 1)" \
  || fail "after the switch the bar was not on the screen its 3.3 s and then gone"
grep -oE "layer: in a window .*" "$OUT/ingame.log" | tail -1 | sed 's/^/  /'
# Its title bar (WS_CAPTION) and borders that size it (WS_THICKFRAME), and none of Windows' buttons (WS_SYSMENU, its
# minimise and maximise).
style=$(grep -oE "layer: in a window \([0-9]+ x [0-9]+, style 0x[0-9a-f]+" "$OUT/ingame.log" | tail -1 | grep -oE "0x[0-9a-f]+$")
python3 -c "import sys; s = int('${style:-0}', 16); sys.exit(0 if s & 0xC00000 == 0xC00000 and s & 0x40000 and not s & 0xB0000 else 1)" \
  || fail "the window has not its title bar and borders only (style ${style:-none})"
wait_log "bar shown by itself for 3 s \(a switch between a window and full screen\)" 3 \
  || fail "the bar did not show by itself after the switch"
# The window's place, then the bar from its top edge and its full screen chip (the window's own pixels: the unit is
# its height over 768).
geo=$(x "xdotool search --name '^ClientApp$' getwindowgeometry" | tr '\n' ' ')
px=$(sed -E 's/.*Position: ([0-9]+),([0-9]+).*/\1/' <<<"$geo"); py=$(sed -E 's/.*Position: ([0-9]+),([0-9]+).*/\2/' <<<"$geo")
gw=$(sed -E 's/.*Geometry: ([0-9]+)x([0-9]+).*/\1/' <<<"$geo"); gh=$(sed -E 's/.*Geometry: ([0-9]+)x([0-9]+).*/\2/' <<<"$geo")
wait_s 3
x "xdotool mousemove $((px + gw / 2)) $((py + gh / 2)) sleep 0.2 mousemove $((px + gw / 2)) $((py + 1))"; wait_s 2
x "xdotool mousemove $(python3 -c "u = max(1.0, $gh / 768); print('%d %d' % ($px + $gw - 93 * u, $py + 35 * u))") sleep 0.4 click 1 sleep 0.05 mousemove 960 700"
wait_s 1.5; shot 06f-full-screen-again
wait_log "layer: full screen \(1920 x 1080" 5 || fail "the full screen chip did not take the game back to full screen"
wait_s 3.5
# Minimise: Windows' own state of the window says minimised (with no window manager, Wine leaves its X window on the
# screen, black); the taskbar's restore brings it back, the game going on.
show_bar
x "xdotool mousemove $MIN_AT sleep 0.4 click 1"; wait_s 1.5
wait_log "layer: minimised" 5 || fail "the minimise chip did not minimise the game"
win_state() { docker exec -e WINEPREFIX=/w -e WINEDEBUG=-all -e DISPLAY=:99 "$C" sh -c "wine /out/restore.exe $*" 2>/dev/null; }
win_state --state ClientApp | grep -q "minimised: 1" || fail "the game's window was not minimised ($(win_state --state ClientApp))"
win_state ClientApp | sed 's/^/  /'
wait_s 2; shot 06g-restored
win_state --state ClientApp | grep -q "minimised: 0" || fail "the game's window did not come back"
game_alive || fail "the game ended after minimise"

echo "== the X, Quit the game"
show_bar
x "xdotool mousemove $X_AT sleep 0.4 click 1"; wait_s 1.5
[ "$(grep -c 'layer: question opened' "$OUT/ingame.log")" -ge 2 ] || fail "the X did not ask the second time"
# Which window has the keyboard now (Wine, with no window manager, may leave it with the launcher's window, which
# started the game; on Windows the game keeps it): said, then the game's.
echo "  the keyboard is with: $(x 'xdotool getwindowfocus getwindowname' 2>/dev/null | tail -1)"
x "xdotool search --name '^ClientApp$' windowfocus --sync" 2>/dev/null
# Right to Quit the game, as the keys choose, then a screenshot, then Enter.
x "xdotool key Right"; wait_s 1.2; shot 07-question-quit-chosen
x "xdotool key Return"
wait_log "quit: the player chose Quit the game" 5 || fail "Quit the game was not taken"
end=$((SECONDS + 30)); while game_alive && [ $SECONDS -lt $end ]; do wait_s 1; done
game_alive && fail "the game did not end after Quit the game"
grep -q "quit: the game had not ended" "$OUT/ingame.log" && echo "  (the game's own close took more than 10 s: ended by the layer)"
end=$((SECONDS + 30)); until x "grep -q 'the game closed after' $LOG" 2>/dev/null || [ $SECONDS -gt $end ]; do wait_s 1; done
x "grep 'the game closed after' $LOG" | tail -1 | tee "$OUT/launcher-saw.txt"
grep -q "exit code 0, 0 crash dump" "$OUT/launcher-saw.txt" || fail "the launcher did not see the game end cleanly"
wait_s 2; shot 08-launcher-after-quit
windows | grep -q "|openDMT3|" || fail "the launcher's window went with the game"

echo "== offline, VSync off, pacing locked to the music, the frame rate chip, a sound device, the picture defaults, from openDMT3-cmd.exe"
# The window keeps its own copy of the settings: closed first, as --set asks.
# Closed as a person closes it: Alt+F4 on its window; then wait until its program has ended.
x "xdotool search --name '^openDMT3$' windowfocus --sync key alt+F4" 2>/dev/null
end=$((SECONDS + 60)); while running 'openDMT3\.exe' && [ $SECONDS -lt $end ]; do wait_s 1; done
if running 'openDMT3\.exe'; then
  x 'ps -eo pid,args | grep -i opendmt3 | grep -v grep' | cut -c1-200
  x "tail -20 $LOG"
  fail "the launcher did not end after its window closed"
fi
docker exec -e WINEPREFIX=/w -e WINEDEBUG=-all -e DISPLAY=:99 "$C" sh -c "wine '$APP' --sound-devices > /out/sound-devices.txt 2>&1"
cat "$OUT/sound-devices.txt"
# The last device listed (the second output when Wine offers it, else the only one).
GUID=$(grep -oE "\{[0-9A-F-]{36}\}" "$OUT/sound-devices.txt" | tail -1)
[ -n "$GUID" ] || fail "openDMT3-cmd --sound-devices listed no device"
textures "the game the launcher started"
rm -f "$OUT/ingame.log"
# The sound watched (OPENDMT3_SOUND_WATCH, the tests only): its log says when the tutorial's song starts.
docker exec -d -e WINEPREFIX=/w -e WINEDEBUG=-all -e DISPLAY=:99 -e 'OPENDMT3_INGAME_LOG=Z:\out\ingame.log' \
  -e OPENDMT3_SOUND_WATCH=1 "$C" sh -c \
  "wine '$APP' --mode offline --set vsync=off --set frame_pacing=music --set show_fps=on --set 'sound_device=$GUID' --set upscale=fsr1 --set sharpness=50 --set antialiasing=off --play > /out/play-offline.txt 2>&1; echo \"exit \$?\" >> /out/play-offline.txt"
wait_for "\|ClientApp\|" 120 || fail "the game did not start offline"
wait_log "layer: attached" 60 || fail "the layer did not attach offline"
grep -q "picture: vsync off, pacing even (openDMT3's clock), locked to a song's music" "$OUT/ingame.log" \
  || fail "the layer did not take pacing locked to the music"
# Said at the first frame the chain draws, which comes a few seconds after the layer attaches (its pictures made then).
wait_log "picture: at most one frame queued" 30 || fail "the layer did not keep the queue to one frame"
grep -q "upscale fsr1, sharpness 50, anti-aliasing off" "$OUT/ingame.log" \
  || fail "the picture defaults did not reach the layer ($(grep 'start:' "$OUT/ingame.log"))"
grep -q "post: on" "$OUT/ingame.log" || fail "the post-process chain did not start ($(grep 'post:' "$OUT/ingame.log" | tail -3))"
wait_log "sound: opened" 60 || fail "the game did not open DirectSound"
grep "sound:" "$OUT/ingame.log" | tee "$OUT/sound.txt"
grep -q "sound: opened the chosen device $GUID" "$OUT/sound.txt" || fail "the chosen device $GUID did not reach DirectSound"
# Low latency (on by default): the sound engine's shortest period asked for on that same device, and what came of it
# said (Wine has no shared engine: it answers a shortest period, keeps its own, and the stream is let go).
wait_log "sound: the engine's period on " 10 || fail "the layer did not say what came of the sound engine's period"
grep "sound: the engine's period on " "$OUT/ingame.log" | sed 's/^/  /'
grep -qE "sound: the engine's period on [^(]*\($GUID\): (held|unchanged|none-shorter|locked|refused|no-answer)" \
  "$OUT/ingame.log" || fail "the sound engine's period was not asked for on the chosen device $GUID"
wait_s 20
# What openDMT3 adds to the frames, judged fairly (ingame/pace.py): each part of the layer shown for 8 s in turn, with
# 8 s of nothing shown between (the chip, the bar, the question, the menu, a toast), on the title screen (it waits for
# TOUCH to START as long as it is left: the game's later screens count down to the tutorial, which the hold below
# needs). A part is judged only on a quiet machine and next to a phase where the game alone held 60 (Wine's software
# renderer misses 60 by itself in some stretches), and there it must hold 60 too. Rounds go on until every part is
# judged or the time for them runs out (QUIET_WAIT seconds, the waits for a quiet machine among them): then the
# pacing could not be judged, and the test fails saying so (never a pass).
# A quiet machine: the others' share of the 1-minute load average under QUIET_LOAD. The others' share is the load
# average less our container's CPU over the last minute (ingame/quiet.py: the game alone keeps about a dozen of Wine's
# rendering threads busy, which the load average counts). QUIET_LOAD is the 1-minute load average of the test PC with
# nothing else running (2.8 to 4.2 in samples 10 s apart), rounded up: a build or another test beside puts it at 10 to
# 25. OPENDMT3_QUIET_LOAD raises it on a PC shared with other work: a part is still judged only next to a phase where
# the game alone held 60, so a busy machine leaves parts not judged, never passes one that does not hold.
QUIET_LOAD=${OPENDMT3_QUIET_LOAD:-5}
QUIET_WAIT=${OPENDMT3_QUIET_WAIT:-1500}
# Our container's CPU time (its cgroup, read from this side) and the load average every 2 s, for quiet.py.
cgroup=$(find /sys/fs/cgroup -maxdepth 3 -type d -name "*$(docker inspect -f '{{.Id}}' "$C")*" 2>/dev/null | head -1)
[ -r "$cgroup/cpu.stat" ] || echo "  the container's CPU time cannot be read here: the whole load average counts as the others'"
(while :; do
  echo "$(python3 -c 'import time; print(int(time.monotonic() * 1000))') $(awk '/^usage_usec/ {print $2}' "$cgroup/cpu.stat" 2>/dev/null || echo 0) $(cut -d' ' -f1 /proc/loadavg)"
  sleep 2
done) > "$OUT/load-samples.txt" &
sampler=$!
load_now() { python3 "$HERE/ingame/quiet.py" "$OUT/load-samples.txt"; }
pace_mark() { echo "$1 $2 $(python3 -c 'import time; print(int(time.monotonic() * 1000))') $(load_now)" >> "$OUT/pace-marks.txt"; }
pace() { pace_mark "$1" start; wait_s "${2:-8}"; pace_mark "$1" end; }
# Wait until the others' share is under QUIET_LOAD, at most until the rounds' time runs out (1: it never was).
wait_quiet() {
  local load ours others
  while :; do
    read -r load ours others < <(load_now)
    python3 -c "import sys; sys.exit(0 if $others < $QUIET_LOAD else 1)" && return 0
    [ $SECONDS -ge $pace_end ] && return 1
    wait_s 10
  done
}
TOAST_WORDS="Picture quality lowered to keep 60 FPS (Smooth upscale)"
rm -f "$OUT/pace-marks.txt" "$OUT/pace.txt"
focus
# In a container with no GPU device (WSL's /dev/dxg, a Linux /dev/dri) Mesa draws the game on the CPU (llvmpipe; the
# adapter Direct3D names under Wine is a made-up card either way): the game alone misses 60 in stretches there and each
# draw of the layer costs CPU time a GPU does not spend, so its frame times say little about a player's PC. There one
# round runs for its numbers and nothing is judged; on a GPU the rounds go on until every part is judged.
software=1
x "test -e /dev/dxg -o -d /dev/dri" && software=0
echo "  the game is drawn on $([ $software = 1 ] && echo "the CPU (Mesa's software renderer: no GPU device in the container)" || echo "a GPU")"
# The chip is on from the start (--set show_fps=on): off for the first phase of nothing.
fps_menu
pace_end=$((SECONDS + QUIET_WAIT))
verdict=2
round=0
while [ $verdict -eq 2 ] && [ $SECONDS -lt $pace_end ]; do
  round=$((round + 1))
  [ $software = 1 ] || wait_quiet || break
  read -r load ours others < <(load_now)
  echo "  round $round: the 1-minute load average $load, our container $ours CPUs, the others' share $others (quiet under $QUIET_LOAD)"
  pace nothing
  fps_menu; pace chip
  fps_menu; pace nothing
  show_bar; pace bar
  away; pace nothing
  show_bar; x "xdotool mousemove $X_AT sleep 0.4 click 1"; wait_s 1; pace question
  focus; x "xdotool key Return"; away; pace nothing
  show_bar; x "xdotool mousemove $MENU_AT sleep 0.4 click 1"; wait_s 1; pace menu
  focus; x "xdotool key Escape"; away; pace nothing
  # The toast lasts 6 s: the same words again half way keep it up (its picture as it was).
  echo "$TOAST_WORDS" > "$OUT/toast.now"; wait_s 1
  pace_mark toast start; wait_s 4; echo "$TOAST_WORDS" > "$OUT/toast.now"; wait_s 4; pace_mark toast end
  wait_s 3; pace nothing
  python3 "$HERE/ingame/pace.py" "$OUT/ingame.log" "$OUT/pace-marks.txt" "$QUIET_LOAD" > "$OUT/pace.txt"; verdict=$?
  # On the software renderer one round, for its numbers.
  [ $software = 1 ] && break
done
# The question in the rounds was asked on the title screen, where no song plays: never with the song's line.
grep "layer: question opened" "$OUT/ingame.log" | grep -q "with its line" && fail "the question on the title screen had a song's line"
kill "$sampler" 2>/dev/null
[ -f "$OUT/pace.txt" ] && cat "$OUT/pace.txt"
# A part that did not hold 60, or no judgement in the time: said, and the run fails at its end (never a pass), the
# steps after it still run and checked.
unjudged=""
paced="every part of the layer holding 60 where the game alone did on a quiet machine"
if [ $software = 1 ]; then
  paced="the pacing measured and not judged on Wine's software renderer"
  echo "  the pacing not judged: the game was drawn on the CPU"
  verdict=0
fi
[ $verdict -eq 1 ] && unjudged="a part of the layer did not hold 60 where the game alone did, on a quiet machine ($(grep -oE 'failed: .*' "$OUT/pace.txt" | head -1))"
[ $verdict -eq 2 ] && unjudged="the pacing could not be judged in $QUIET_WAIT s ($(grep -oE 'phases not judged: .*' "$OUT/pace.txt" 2>/dev/null || echo 'no round on a quiet machine: the others'"'"' share of the load never under '"$QUIET_LOAD"))"
[ -n "$unjudged" ] && echo "  $unjudged"
# The chip's own cost as a player has it: its CPU time a frame alone, its updates, no GDI drawing in them. Read from
# the rounds' marks: with no round run (the machine never quiet), not measured, and the run fails at its end with the
# reason above, after the steps below.
if [ -s "$OUT/pace-marks.txt" ]; then
  python3 "$HERE/ingame/costs.py" play "$OUT/ingame.log" "$OUT/pace-marks.txt" || fail "the chip costs more than its targets"
else
  echo "  the chip's own cost not measured: no round ran"
fi
# The chip on again for the checks below, then past TOUCH to START and its loading.
fps_menu
x "xdotool mousemove 960 830 mousedown 1 sleep 0.15 mouseup 1"
wait_s 25
shot 09-offline-chip

echo "== a song held still under the question: the picture and the sound stop, and go on together"
# The tutorial's song: the first play of the long one-shot music buffer (its music in one buffer, played once).
end=$((SECONDS + 180)); until grep -q "(41943040 bytes, [0-9]* a second, once) plays" "$OUT/ingame.log" || [ $SECONDS -gt $end ]; do wait_s 1; done
grep -q "(41943040 bytes, [0-9]* a second, once) plays" "$OUT/ingame.log" || fail "the tutorial's song did not start"
wait_s 6
focus
# The bar from the top edge (nothing pressed since TOUCH to START: the game is quiet), its X: the question with its
# line, the song held still.
show_bar
x "xdotool mousemove $X_AT sleep 0.4 click 1"
wait_log "hold: the game held still at frame" 5 || fail "the question did not hold the song still"
grep "layer: question opened" "$OUT/ingame.log" | tail -1 | grep -q "with its line" || fail "the question during a song had not its line"
wait_s 1.0; x "import -window root -type TrueColor bmp3:/out/held-a.bmp"; shot 11a-held
wait_s 2.0; x "import -window root -type TrueColor bmp3:/out/held-b.bmp"
python3 "$HERE/ingame/still.py" "$OUT/held-a.bmp" "$OUT/held-b.bmp" || fail "the game's picture moved while it was held"
# The chip is on here (the menu brought it back above) but hidden while the game is held: never a 60 of frames shown
# again.
drew h1 bar question '!chip' || fail "the question is not under the X while the game is held, the chip shows, or something is in the middle"
focus
grep -E "^[0-9]+ sound: [0-9]+ buffers held" "$OUT/ingame.log" | tail -1 | sed 's/^/  /'
x "xdotool key Return"
wait_log "hold: the game goes on at frame" 5 || fail "Keep playing did not let the song go on"
held=$(grep -oE "hold: the game held still at frame [0-9]+" "$OUT/ingame.log" | tail -1 | grep -oE "[0-9]+$")
went=$(grep -oE "hold: the game goes on at frame [0-9]+" "$OUT/ingame.log" | tail -1 | grep -oE "[0-9]+$")
[ "$held" = "$went" ] || fail "the game's frames went on while it was held ($held, then $went)"
grep -q "sound: [0-9]* buffers going on from where they stopped" "$OUT/ingame.log" || fail "the sound was not played again from where it stopped"
# The fade in: its eight steps done over the next frames (the fade out's are in the hold's first frames).
wait_log "sound: faded in over [0-9]+ frames" 5 || fail "the sound did not fade back in after the hold"
grep -E "^[0-9]+ (hold: |sound: faded in)" "$OUT/ingame.log" | tail -3 | sed 's/^/  /'
wait_s 3
game_alive || fail "the game ended after the hold"
# Esc in a song does nothing: no question, no hold, the game goes on (the keyboard with the game's window, as above).
echo "  the keyboard is with: $(x 'xdotool getwindowfocus getwindowname' 2>/dev/null | tail -1)"
focus
asked=$(seen "layer: question opened"); holds=$(seen "hold: the game held still"); kept=$(seen "layer: Esc kept")
x "xdotool mousemove 960 700 sleep 0.3 key Escape"; wait_s 1.5; shot 11b-offline-esc-song
wait_more "layer: Esc kept from the game" "$kept" 3 || fail "Esc did not reach the game's window in the song"
[ "$(seen "layer: question opened")" = "$asked" ] && [ "$(seen "hold: the game held still")" = "$holds" ] \
  || fail "Esc in a song opened the question or held the game"
game_alive || fail "Esc ended the game"
# Minimised in a song: held still; the taskbar's restore brings it back and the song goes on (before the minute of
# play below: the tutorial's song ends sooner when its notes are hit).
holds=$(seen "hold: the game held still"); went=$(seen "hold: the game goes on")
show_bar
x "xdotool mousemove $MIN_AT sleep 0.4 click 1"
wait_more "hold: the game held still" "$holds" 5 || fail "minimised in a song, the game was not held still"
wait_s 2
win_state ClientApp | sed 's/^/  /'
wait_more "hold: the game goes on" "$went" 5 || fail "brought back, the song did not go on"
wait_s 2; shot 11d-back-in-song
game_alive || fail "the game ended after minimise in a song"
# The bar never on the screen while the song is played: a minute of it played all over the screen, the game's top band
# and its very top edge included, held notes too, the pointer resting at the top edge (and on the mark) between notes a
# little under the 1.5 s of quiet a rest needs (ingame/player.py). The song may end within the minute: the load of its
# result is a pause with no frame, which is neither rest nor quiet (logic.c gate_stall), so the bar stays away then too.
python3 "$HERE/ingame/player.py" 60 7 > "$OUT/player.sh"
# The pointer off the bar first (it rested on minimise), so the play starts with the bar gone.
away
on=$(seen "layer: bar on the screen")
x "sh /out/player.sh"
played=$(grep -c "^xdotool" "$OUT/player.sh")
[ "$(seen "layer: bar on the screen")" = "$on" ] || fail "the bar came on the screen while the song was played ($(grep 'layer: bar shown (' "$OUT/ingame.log" | tail -1))"
echo "  a minute of the song played ($played steps of the mouse, the top band and its edge included): the bar on the screen 0 s"
# Then a call on purpose: 1.6 s of quiet, the pointer moved to the top edge and resting there: the bar, 1.5 s or more
# after the last press; the pointer away after a second: gone 0.9 s later (600 ms whole, 300 ms of fade).
x "xdotool mousemove 960 700"; wait_s 1.6
bars=$(seen "layer: bar shown \(")
x "xdotool mousemove 1300 0"; wait_s 1.15; shot 11c-called
wait_more "layer: bar shown \(the pointer rested at the top edge" "$bars" 3 || fail "a call on purpose did not bring the bar"
quiet=$(grep -oE "rested at the top edge, [0-9.]+ s after the game's last press" "$OUT/ingame.log" | tail -1 | grep -oE "[0-9.]+ s" | cut -d' ' -f1)
python3 -c "import sys; sys.exit(0 if 1.5 <= float('${quiet:-0}') < 3.5 else 1)" || fail "the bar came ${quiet:-?} s after the last press (1.5 s wanted)"
left=$(now_ms); x "xdotool mousemove 960 700"; wait_s 2
gone=$(gone_after "$left" 5)
slow=$(stall_s "$left" "$gone")
echo "  called on purpose: the bar ${quiet:-?} s after the last press, gone $(python3 -c "print('%.2f' % ((${gone:-0} - $left) / 1000.0))") s after the pointer left it (the game's frames over 100 ms then: $slow s)"
python3 -c "import sys; d = (${gone:-0} - $left) / 1000.0; sys.exit(0 if 0.7 <= d <= 1.3 + $slow else 1)" \
  || fail "the bar did not go 0.9 s after the pointer left it"
# The chip in its corner checked after the song (the song needs its time first: the tutorial lasts four minutes).
echo "== the chip in the corner: the menu's Show FPS"
# The pointer off the bar (it rested on minimise): the bar gone, the mark and the chip alone.
away
drew c1 mark chip || fail "the chip is not showing in the bottom right corner above FREE PLAY, or something is in the middle"
# The log holds the rounds' lines already: each step below is judged by the line it adds.
opened=$(seen "layer: menu opened"); off=$(seen "layer: frame rate chip off"); on=$(seen "layer: frame rate chip on")
closed=$(seen "layer: closed, back to the game")
show_bar
x "xdotool mousemove $MENU_AT sleep 0.4 click 1"; wait_s 1.0; shot 10a-offline-menu
wait_more "layer: menu opened" "$opened" 5 || fail "the menu chip did not open the menu"
x "xdotool search --name '^ClientApp$' windowfocus --sync" 2>/dev/null
# Show FPS is the menu's second row: Down, then Enter turns the chip off and the menu stays.
x "xdotool key Down"; wait_s 0.4; x "xdotool key Return"; wait_s 1.0; shot 10b-offline-menu-fps-off
wait_more "layer: frame rate chip off" "$off" 5 || fail "the menu's Show FPS did not turn the chip off"
drew c2 bar menu '!chip' || fail "the chip still shows after Show FPS off, or the menu is not under its chip"
x "xdotool key Return"; wait_s 1.0
wait_more "layer: frame rate chip on" "$on" 5 || fail "the menu's Show FPS did not turn the chip on again"
x "xdotool key Escape"; wait_s 0.5
wait_more "layer: closed, back to the game" "$closed" 5 || fail "Esc did not close the menu"
away
drew c3 mark chip || fail "the chip is not back after Show FPS on"
# F12 is the game's again: it turns nothing of the layer's.
focus
off=$(seen "layer: frame rate chip off")
x "xdotool key F12"; wait_s 0.8
[ "$(seen "layer: frame rate chip off")" = "$off" ] || fail "F12 turned the chip off"
game_alive || fail "the game ended while the chip was turned"
shot 10-offline-chip

quit_by_x
wait_log "quit: the player chose Quit the game" 5 || fail "Quit the game was not taken offline"
end=$((SECONDS + 40)); until grep -q "^exit " "$OUT/play-offline.txt" 2>/dev/null || [ $SECONDS -gt $end ]; do wait_s 1; done
cat "$OUT/play-offline.txt"
grep -q "^exit 0" "$OUT/play-offline.txt" || fail "openDMT3-cmd --play did not return after the game ended"
game_alive && fail "the game is still running offline"
# The layer's note of the sound engine's period read into the launcher's log when the game ended (the Sound page and
# --status show it from there), and the note gone.
docker exec "$C" sh -c "grep -E 'the sound engine' $LOG | tail -1" | sed 's/^/  /'
docker exec "$C" grep -qE \
  "the sound engine('s period was not made shorter on| ran at [0-9]+ frames).* the chosen device $GUID" "$LOG" \
  || fail "the launcher's log has no line of the sound engine's period on the chosen device"
docker exec "$C" sh -c "ls /w/drive_c/users/root/AppData/Roaming/openDMT3/game/openDMT3-sound.txt" >/dev/null 2>&1 \
  && fail "the layer's note of the sound engine's period was left after the game ended"

textures "the offline game"
echo "== offline again with sharpness 80 and SMAA High: the chain's own frame, FSR 1 against bilinear, the screen"
rm -f "$OUT/ingame.log"
# The chain's measuring dump (OPENDMT3_POSTFX_DUMP, never set by the launcher) writes into OUT_DIR when asked; every
# frame's chain and layer work timed whole (OPENDMT3_LAYER_TIMING=frame, the tests only: it stalls each frame), the
# chip on.
docker exec -d -e WINEPREFIX=/w -e WINEDEBUG=-all -e DISPLAY=:99 -e 'OPENDMT3_INGAME_LOG=Z:\out\ingame.log' \
  -e 'OPENDMT3_POSTFX_DUMP=Z:\out' -e OPENDMT3_SAFETY=off -e OPENDMT3_LAYER_TIMING=frame "$C" sh -c \
  "wine '$APP' --mode offline --set upscale=fsr1 --set sharpness=80 --set antialiasing=smaa-high --set show_fps=on --play > /out/play-picture.txt 2>&1; echo \"exit \$?\" >> /out/play-picture.txt"
wait_for "\|ClientApp\|" 120 || fail "the game did not start offline the second time"
wait_log "layer: attached" 60 || fail "the layer did not attach offline the second time"
grep -q "upscale fsr1, sharpness 80, anti-aliasing smaa-high" "$OUT/ingame.log" \
  || fail "the picture options did not reach the layer ($(grep 'start:' "$OUT/ingame.log"))"
grep -q "post: on" "$OUT/ingame.log" || fail "the post-process chain did not start ($(grep 'post:' "$OUT/ingame.log" | tail -3))"
wait_s 20
# What each part adds to a frame as it is drawn (ingame/costs.py turns), on the title screen (it waits as long as it
# is left): eight turns of 4 s with the chip and 4 s without, then five each with the bar and with the question.
# The median turn of the chip must stay under 0.2 ms a frame; the bar's and the question's are said.
turn() { pace_mark "$1" start; wait_s 4.2; pace_mark "$1" end; }
rm -f "$OUT/pace-marks.txt"
x "xdotool search --name '^ClientApp$' windowfocus --sync" 2>/dev/null
x "xdotool mousemove 960 700"; wait_s 0.5
# The chip off and on through the menu's Show FPS between its turns (the menu's own frames are in neither).
for i in 1 2 3 4 5 6 7 8; do
  turn chip; fps_menu; turn off-chip; fps_menu
done
for i in 1 2 3 4 5; do
  show_bar; turn bar; away; turn off-bar
done
for i in 1 2 3 4 5; do
  show_bar; x "xdotool mousemove $X_AT sleep 0.4 click 1"; wait_s 0.8; turn question
  focus; x "xdotool key Return"; away; turn off-question
done
# Judged on a GPU only, as the pacing above: on the CPU's renderer a frame's whole time is its drawing on the CPU (and
# on a busy machine the turns spread by tens of milliseconds), said here and not judged.
added="what each part adds to a frame (the chip under 0.2 ms)"
if [ $software = 1 ]; then
  python3 "$HERE/ingame/costs.py" turns "$OUT/ingame.log" "$OUT/pace-marks.txt" || echo "  not judged: the game was drawn on the CPU"
  added="what each part adds to a frame (said, not judged: the game drawn on the CPU)"
else
  python3 "$HERE/ingame/costs.py" turns "$OUT/ingame.log" "$OUT/pace-marks.txt" || fail "the chip adds over 0.2 ms to a frame"
fi
# Past TOUCH to START and its loading, as above, so the frames compared are of a settled screen.
x "xdotool mousemove 960 830 mousedown 1 sleep 0.15 mouseup 1"
wait_s 25
# Every pass on one frame, then the screen between two of the game's pictures taken as close to it as they can be
# (what holds still): the game's own button on this screen pulses about once a second, and with one later frame
# alone it showed alike in the two frames a pulse apart and differently on the screen captured between them (3.03 a
# byte from the chain's output in such a run, 0.14 to 1.69 in four others, every differing pixel on that button).
# The layer takes a request up within ten frames: the one before the capture is waited for in short steps, the one
# after is asked the moment the capture returns.
ask_dump e2e all || fail "the chain did not write its frames"
echo "e2e1 src" > "$OUT/dump.now"
end=$((SECONDS + 20)); while [ -f "$OUT/dump.now" ] && [ $SECONDS -lt $end ]; do wait_s 0.05; done
[ ! -f "$OUT/dump.now" ] || fail "the chain did not write the frame before the screen"
x "import -window root -type TrueColor bmp3:/out/screen-e2e.bmp"
ask_dump e2e2 src || fail "the chain did not write the frame after the screen"
shot 09b-offline-picture
x "python3 /probe/picture.py /out" || fail "the frame shown is not the chain's"

# The X, then Quit the game, as above.
asked=$(seen "layer: question opened")
quit_by_x
wait_more "layer: question opened" "$asked" 5 || fail "the X did not ask the second time"
wait_log "quit: the player chose Quit the game" 5 || fail "Quit the game was not taken the second time"
end=$((SECONDS + 40)); until grep -q "^exit " "$OUT/play-picture.txt" 2>/dev/null || [ $SECONDS -gt $end ]; do wait_s 1; done
cat "$OUT/play-picture.txt"
grep -q "^exit 0" "$OUT/play-picture.txt" || fail "openDMT3-cmd --play did not return after the second game ended"
game_alive && fail "the game is still running after the second offline play"

if wine_on_gpu; then
echo "== offline with NVIDIA NIS and SMAA Ultra on the GPU: the heaviest choice holds 60 and the safety net leaves it"
# On a graphics card the heaviest choice's passes take a fraction of a millisecond: the net, on for this play, must find
# nothing to step down (no step, no note) while the game holds 60 evenly past its loading (its first 600 frames, which
# the net does not judge) and 30 s more.
textures "the game with sharpness 80 and SMAA High"
rm -f "$OUT/ingame.log"
docker exec -d -e WINEPREFIX=/w -e WINEDEBUG=-all -e DISPLAY=:99 -e 'OPENDMT3_INGAME_LOG=Z:\out\ingame.log' \
  -e OPENDMT3_SAFETY=on "$C" sh -c \
  "wine '$APP' --mode offline --set upscale=nis --set sharpness=50 --set antialiasing=smaa-ultra --play > /out/play-heavy.txt 2>&1; echo \"exit \$?\" >> /out/play-heavy.txt"
wait_for "\|ClientApp\|" 120 || fail "the game did not start offline the third time"
wait_log "layer: attached" 60 || fail "the layer did not attach offline the third time"
grep -q "upscale nis, sharpness 50, anti-aliasing smaa-ultra" "$OUT/ingame.log" || fail "the heavy choice did not reach the layer"
stepped="the heaviest choice holding 60 on the GPU, the safety net leaving it"
wait_log "post: the game's first screen" 120 || fail "the game's first screen did not come offline the third time"
wait_s 30
shot 12-offline-heavy-on-gpu
grep -E "post: stepped down|layer: note shown" "$OUT/ingame.log" | sed 's/^/  /'
grep -qE "post: stepped down|layer: note shown" "$OUT/ingame.log" && fail "the safety net stepped the heaviest choice down on the GPU"
grep "post: GPU" "$OUT/ingame.log" | tail -1 | sed 's/^/  /'
grep "frames:" "$OUT/ingame.log" | tail -5 | tee "$OUT/frames-heavy.txt"
python3 - "$OUT/frames-heavy.txt" <<'PY' || fail "with NIS and SMAA Ultra on the GPU the game is not at 60 frames a second, evenly"
import re, sys
lines = [(float(m.group(1)), float(m.group(2))) for m in
         re.finditer(r"frames: ([0-9.]+) a second, frame time [0-9.]+ ms \(sd ([0-9.]+)", open(sys.argv[1]).read())]
even = [rate for rate, sd in lines if 57.0 <= rate <= 63.0 and sd < 1.0]
print("  %d of %d counts at 60 a second with a spread under 1 ms" % (len(even), len(lines)))
sys.exit(0 if len(lines) >= 5 and len(even) >= 4 else 1)
PY
else
echo "== offline with NVIDIA NIS and SMAA Ultra: the safety net steps the chain down and the game holds 60 again"
# The heaviest choice on Wine's software renderer, where its passes take about two frames' time: the net must step it
# down (SMAA Ultra to FXAA to none, then NIS to bilinear), say so on the screen and in the log, and the frames after
# the last step must be 60 a second evenly again.
textures "the game with sharpness 80 and SMAA High"
rm -f "$OUT/ingame.log"
# The net on for this play (the container has it off for the others).
docker exec -d -e WINEPREFIX=/w -e WINEDEBUG=-all -e DISPLAY=:99 -e 'OPENDMT3_INGAME_LOG=Z:\out\ingame.log' \
  -e OPENDMT3_SAFETY=on "$C" sh -c \
  "wine '$APP' --mode offline --set upscale=nis --set sharpness=50 --set antialiasing=smaa-ultra --play > /out/play-heavy.txt 2>&1; echo \"exit \$?\" >> /out/play-heavy.txt"
wait_for "\|ClientApp\|" 120 || fail "the game did not start offline the third time"
wait_log "layer: attached" 60 || fail "the layer did not attach offline the third time"
grep -q "upscale nis, sharpness 50, anti-aliasing smaa-ultra" "$OUT/ingame.log" || fail "the heavy choice did not reach the layer"
# The game's first 600 frames are not judged (its loading: at 25 to 30 frames a second, about 20 s), then three
# steps, each after two windows of 60 frames with 30 late by the chain's doing: about 5 s each.
wait_log "layer: note shown" 120 || fail "the safety net did not step the heavy chain down ($(grep -E 'frames:|post: GPU' "$OUT/ingame.log" | tail -2))"
shot 12-offline-safety-note
wait_log "post: stepped down from nis with off to smooth with off" 120 \
  || fail "the safety net did not reach bilinear ($(grep 'post: stepped' "$OUT/ingame.log"))"
grep "post: stepped down" "$OUT/ingame.log" | sed 's/^/  /'
# Ten seconds after the last step: the counter's last five lines, as in the pacing check above.
wait_s 12
grep "frames:" "$OUT/ingame.log" | tail -5 | tee "$OUT/frames-after-step.txt"
# 60 again after the steps: judged on a GPU only, as the pacing above (on the CPU's renderer a busy machine keeps the
# game alone under 60); said either way.
stepped="the safety net stepping the heaviest choice down to 60 again"
[ $software = 1 ] && stepped="the safety net stepping the heaviest choice down (60 again said, not judged: the game drawn on the CPU)"
python3 - "$OUT/frames-after-step.txt" <<'EOF' || { [ $software = 1 ] && echo "  not judged: the game was drawn on the CPU"; } || fail "after the safety net's steps the game is not at 60 frames a second, evenly"
import re, sys
lines = [(float(m.group(1)), float(m.group(2))) for m in
         re.finditer(r"frames: ([0-9.]+) a second, frame time [0-9.]+ ms \(sd ([0-9.]+)", open(sys.argv[1]).read())]
even = [rate for rate, sd in lines if 57.0 <= rate <= 63.0 and sd < 1.0]
print("  %d of %d counts at 60 a second with a spread under 1 ms" % (len(even), len(lines)))
sys.exit(0 if len(lines) >= 5 and len(even) >= 4 else 1)
EOF
fi
quit_by_x
wait_log "layer: question opened" 5 || fail "the X did not ask the third time"
end=$((SECONDS + 40)); until grep -q "^exit " "$OUT/play-heavy.txt" 2>/dev/null || [ $SECONDS -gt $end ]; do wait_s 1; done
grep -q "^exit 0" "$OUT/play-heavy.txt" || fail "openDMT3-cmd --play did not return after the third game ended"
# The launcher put the steps in its log and took the note away (on the CPU, where the net stepped).
x "grep 'the in-game picture stepped down' $LOG" | tail -3 | sed 's/^/  /'
wine_on_gpu || x "grep -q 'the in-game picture stepped down' $LOG" || fail "the launcher's log does not have the safety net's steps"
game_alive && fail "the game is still running after the third offline play"
dumps=$(x "find /root/Desktop /w/drive_c/users/root/AppData/Roaming/openDMT3 -name '*.dmp' -newer /out/.prefix-ready | wc -l")
[ "$dumps" = 0 ] || fail "the game wrote a crash dump"
textures "the game with NVIDIA NIS and SMAA Ultra"
# Every other step held; the pacing not judged in its time is a failure all the same.
[ -n "$unjudged" ] && fail "$unjudged"
echo "PASS: the bar by itself at the first screen; the dart up and pressed; the bar only from a rest at the top edge or on the mark, never within 1.5 s of a click; the question dropping down under its X with Keep playing and Quit (exit 0, seen by the launcher), no line on the menus; Esc and Alt+F4 doing nothing; the window's close asking; the menu under its chip, a toast at the top, nothing of the layer in the middle; a window with its title bar and borders only and back to full screen; minimise and back; offline the chip in the corner above FREE PLAY, pacing locked to the music with one frame queued, the chosen sound device opened, $paced, the chip within its costs, Show FPS; a song held still under the question (with its line, the chip hidden) and going on with its sound; Esc doing nothing in a song; no bar from clicks at the top; minimised in a song held and going on; the picture options run by the chain and shown, $added, $stepped"
docker rm -f "$C" >/dev/null
