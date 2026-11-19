#!/bin/bash
# A song's chart against its music across holds, on either renderer (OPENDMT3_WINE_GPU=1 for this PC's GPU, gpu.sh),
# with the sound clock of song.sh's image (gpu/sound/Dockerfile: PulseAudio's null sink, which plays in real time). The
# real client starts afresh as a guest on a virtual screen with no network, as song.sh starts it: its title clicked
# 40 s after the layer attaches, the guest's tutorial, then a song, no presses. The score is watched
# (OPENDMT3_LINE_WATCH: a row a frame, line.c), and the game is held still at the times given, each timed from its
# music's start as the layer's log shows it:
#   HOLDS="32 50"   the bar's X opens the question that many seconds into the tutorial's music and into the song's, for
#                   HOLD_S seconds (5), then Keep playing (then the 3, 2, 1 of 1.5 s before the song goes on);
#                   TUT_HOLDS, when set, the tutorial's instead (empty: none in it); "32 50" unless given
#   MINIMISE="68"   (unless given) the bar's minimise chip that many seconds into the song's music, HOLD_S seconds
#                   minimised, then the taskbar's restore (ingame/restore.c, built here)
# line.py holds then judges each hold (the score counted only the time between its two frames that was not held,
# within a tick and 20 ms) and gives what each moved the score against the music over two seconds each side; line.py
# gives the whole run's numbers. Nothing reaches a real screen or a speaker.
#
#   [OPENDMT3_WINE_GPU=1] [SCREEN=1280x768] [HOLDS=...] [TUT_HOLDS=...] [MINIMISE=...] [HOLD_S=5] [MUSICS=2]
#   [OPENDMT3_E2E_NAME=odt3-holds]
#     tests/e2e/windows/gpu/holds.sh GAME_PARENT BUILD_DIR OUT_DIR [LINK_SOURCE] [WINE_DLLS] [VAR=VALUE...]
#
# The arguments are song.sh's: BUILD_DIR is ./dmt3 build's output (native/CRT_R1.dll, the layer, with multiDLL.dll
# beside it) or a folder holding them; each VAR=VALUE is passed to the game on top of the layer's defaults as a player
# has them (OPENDMT3_STALL=200, say: the layer's own stall 20 s into each music). MUSICS=1 ends the run with the
# tutorial's music (gpu/judge.sh's runs). Exit: line.py holds' (0 when every hold was judged and the chart held with
# the music); with no holds asked (HOLDS, TUT_HOLDS and MINIMISE empty), 0 once the run has played its music.
set -u
SRC=$(realpath "${1:?usage: holds.sh GAME_PARENT BUILD_DIR OUT_DIR [LINK_SOURCE] [WINE_DLLS] [VAR=VALUE...]}")
BUILD=$(realpath "${2:?}")
OUT=$(realpath -m "${3:?}")
LINKS=${4:-}
DLLS=${5:-}
shift $(($# < 5 ? $# : 5))
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../../.." && pwd)
# The renderer: the CPU image by default, the GPU image with OPENDMT3_WINE_GPU=1 (gpu.sh), with the sound server.
. "$HERE/../gpu.sh"
RENDERER=$(wine_on_gpu && echo gpu || echo cpu)
BASE=$(wine_image opendmt3-wine:local)
IMAGE=${BASE%:*}-sound:local
SCREEN=${SCREEN:-1280x768}
W=${SCREEN%x*}
H=${SCREEN#*x}
HOLD_S=${HOLD_S:-5}
# The holds testing.md measured unless given (an empty value: none).
HOLDS=${HOLDS-32 50}
TUT_HOLDS=${TUT_HOLDS-$HOLDS}
MINIMISE=${MINIMISE-68}
DLL=$BUILD/native/CRT_R1.dll
[ -f "$DLL" ] || DLL=$BUILD/CRT_R1.dll
[ -f "$DLL" ] || { echo "FAIL: no native/CRT_R1.dll in $BUILD (./dmt3 build's output)"; exit 1; }
wait_s() { python3 -c "import time; time.sleep($1)"; }
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  docker build -q --build-arg BASE="$BASE" -t "$IMAGE" "$HERE/sound" >/dev/null \
    || { echo "FAIL: $IMAGE did not build"; exit 1; }
fi
C=${OPENDMT3_E2E_NAME:-odt3-holds}-$RENDERER-$$

# ---- the game's copy, the layer in it as PLAY puts it (song.sh's steps), and the taskbar's restore
rm -rf "$OUT"
mkdir -p "$OUT/game"
cp -a "$SRC/." "$OUT/game/"
CLIENT=$(find "$OUT/game" -maxdepth 6 -name "Client (openDMT3).exe" | head -1)
[ -n "$CLIENT" ] || { echo "FAIL: no Client (openDMT3).exe under $SRC"; exit 1; }
DMT3=$(dirname "$CLIENT")
REL_DMT3=${DMT3#"$OUT/game/"}
rm -f "$DMT3/openDMT3-card.txt" "$DMT3/openDMT3-picture.txt"
cp "$DLL" "$DMT3/CRT_R1.dll"
TOUCH=$(dirname "$DLL")/multiDLL.dll
if [ -f "$TOUCH" ]; then
  find "$DMT3" -maxdepth 1 -iname "multidll.dll" -delete
  cp "$TOUCH" "$DMT3/multiDLL.dll"
fi
F="$REPO/opendmt3/client/assets/fonts"
cp "$F/Pretendard-Bold.ttf" "$DMT3/openDMT3-Pretendard-Bold.ttf"
cp "$F/Pretendard-Regular.ttf" "$DMT3/openDMT3-Pretendard-Regular.ttf"
cp "$F/DMT3Wide-Regular.ttf" "$DMT3/openDMT3-DMT3Wide.ttf"
# Not executable: a Windows program is never started from here (WSL would hand it to Windows).
find "$OUT/game" -type f -iname "*.exe" -exec chmod 0644 {} +
docker run --rm --network none --name "$C-build" -v "$HERE/../ingame:/src:ro" -v "$OUT:/out" opendmt3-mingw:local \
  i686-w64-mingw32-gcc -O2 -o /out/restore.exe /src/restore.c -luser32 || { echo "FAIL: the restore helper did not build"; exit 1; }
chmod 0644 "$OUT/restore.exe"

# ---- the container: the virtual screen, a fresh prefix, the sound server with its null sink as the default
mounts=(-v "$OUT/game:/root/Desktop/game" -v "$OUT:/out")
[ -n "$LINKS" ] && mounts+=(-v "$LINKS:$LINKS:ro")
[ -n "$DLLS" ] && mounts+=(-v "$(realpath "$DLLS"):/dlls:ro")
# The layer's choices as a player has them, the measuring ones, then the caller's.
envs=(-e OPENDMT3_LANGUAGE=en -e OPENDMT3_CURSOR=on -e OPENDMT3_PACING=music -e OPENDMT3_FPS=off
      -e OPENDMT3_UPSCALE=fsr1 -e OPENDMT3_SHARPNESS=50 -e OPENDMT3_ANTIALIASING=off -e OPENDMT3_SAFETY=off
      -e OPENDMT3_SOUND_WATCH=1 -e 'OPENDMT3_INGAME_FRAMES=Z:\out\frames.txt' -e 'OPENDMT3_LINE_WATCH=Z:\out\line.csv')
for e in "$@"; do envs+=(-e "$e"); done
echo "$(date +%T) holds on the $RENDERER at $SCREEN: $DLL ($(sha256sum "$DLL" | cut -c1-16)), ${*:-the defaults}; holds at '$HOLDS' s (the tutorial's '$TUT_HOLDS'), minimise at '$MINIMISE' s, ${HOLD_S} s each; load $(cut -d' ' -f1-3 /proc/loadavg)" \
  | tee "$OUT/run.txt"
docker run -d --name "$C" --network none --ulimit core=1 -e SCREEN="$SCREEN" -e REL_DMT3="$REL_DMT3" \
  "${WINE_RUN_ARGS[@]}" "${mounts[@]}" "${envs[@]}" "$IMAGE" bash -c '
  env -u GALLIUM_DRIVER -u LD_LIBRARY_PATH Xvfb :99 -screen 0 ${SCREEN}x24 -nolisten tcp >/dev/null 2>&1 &
  export WINEPREFIX=/w DISPLAY=:99 WINEDLLOVERRIDES="mscoree,mshtml=" WINEDEBUG=-all XDG_RUNTIME_DIR=/tmp/xdg
  mkdir -p /tmp/xdg && chmod 700 /tmp/xdg
  printf "pcm.!default { type pulse }\nctl.!default { type pulse }\n" > /etc/asound.conf
  pulseaudio -D --exit-idle-time=-1 --system=false -n --load="module-null-sink sink_name=out" \
    --load=module-native-protocol-unix > /out/pulse.txt 2>&1
  sleep 1
  pactl set-default-sink out >> /out/pulse.txt 2>&1
  wineboot -i >/dev/null 2>&1; wineserver -w
  [ -d /dlls ] && cp /dlls/*.dll /w/drive_c/windows/syswow64/
  cd "/root/Desktop/game/$REL_DMT3"
  OPENDMT3_INGAME_LOG="Z:\\out\\ingame.log" wine "Client (openDMT3).exe" > /out/wine.txt 2>&1
  echo "exit $?" > /out/exit.txt
  sleep infinity' >/dev/null || { echo "FAIL: the container did not start"; exit 1; }
L=$OUT/ingame.log
x() { docker exec -e DISPLAY=:99 "$C" sh -c "$1"; }
stop() { docker rm -f "$C" >/dev/null 2>&1; }
note() { echo "$(date +%T) $*" | tee -a "$OUT/run.txt"; }
seen() { grep -cE "$1" "$L" 2>/dev/null; }
end=$((SECONDS + 300))
until grep -q "layer: attached" "$L" 2>/dev/null || [ $SECONDS -gt $end ]; do wait_s 2; done
grep -q "layer: attached" "$L" 2>/dev/null || { echo "FAIL: the layer never attached"; stop; exit 1; }
grep -E "^[0-9]+ (clock|score|offset|line): " "$L" | sed 's/^/  /' | tee -a "$OUT/run.txt"
wait_s 40
proof=$(gpu_proof "$C" 'Client (openDMT3).exe'); drawn=$?
echo "$proof" | tee -a "$OUT/run.txt"
[ $drawn = 0 ] || { stop; exit 1; }
x "xdotool mousemove $((W / 2)) $((H * 830 / 1080)) mousedown 1 sleep 0.15 mouseup 1"
# The bar's chips and the question's Keep playing during a song, on the game's 1280x768 picture as the screen shows it
# (logic.c ui_layout: the X 37 from the picture's right edge, minimise 149, 35 down; Keep playing 231.5 from it, 156
# down with the song's line).
U=$(python3 -c "print($H / 768.0)")
PW=$(python3 -c "print(min($W, $H * 5 / 3))")
PR=$(python3 -c "print(($W + $PW) / 2)")
at() { python3 -c "print('%d %d' % ($1, $2))"; }
X_AT=$(at "$PR - $U * 37" "$U * 35")
MIN_AT=$(at "$PR - $U * 149" "$U * 35")
KEEP_AT=$(at "$PR - $U * 231.5" "$U * 156")
show_bar() {
  # The pointer resting at the very top edge, away from the mark (three tries).
  local i before
  for i in 1 2 3; do
    before=$(seen "layer: bar on the screen")
    x "xdotool mousemove $((W * 2 / 3)) $((H / 2)) sleep 0.2 mousemove $((W * 2 / 3)) 0"; wait_s 2
    [ "$(seen "layer: bar on the screen")" -gt "$before" ] && return 0
  done
  return 1
}
hold() {
  # The question under the bar's X held HOLD_S seconds, then Keep playing.
  local went
  went=$(seen "hold: the game goes on")
  show_bar || note "  the bar did not come for the hold ($1)"
  x "xdotool mousemove $X_AT sleep 0.5 click 1"; wait_s 1
  wait_s "$HOLD_S"
  x "xdotool mousemove $KEEP_AT sleep 0.3 click 1"; wait_s 1.5
  x "xdotool mousemove $((W / 2)) $((H * 3 / 4))"
  [ "$(seen "hold: the game goes on")" -gt "$went" ] || note "  the hold for $1 did not end"
  grep -E "hold: the game (held|goes)" "$L" | tail -2 | sed 's/^/  /' | tee -a "$OUT/run.txt"
}
minimise() {
  # The bar's minimise chip, HOLD_S seconds minimised, then the taskbar's restore.
  local went
  went=$(seen "hold: the game goes on")
  show_bar || note "  the bar did not come for the minimise ($1)"
  x "xdotool mousemove $MIN_AT sleep 0.5 click 1"; wait_s 1
  wait_s "$HOLD_S"
  docker exec -e WINEPREFIX=/w -e WINEDEBUG=-all -e DISPLAY=:99 "$C" sh -c "wine /out/restore.exe ClientApp" 2>/dev/null \
    | sed 's/^/  restore: /'
  wait_s 1.5
  x "xdotool mousemove $((W / 2)) $((H * 3 / 4))"
  [ "$(seen "hold: the game goes on")" -gt "$went" ] || note "  the minimise for $1 did not end"
  grep -E "hold: the game (held|goes)" "$L" | tail -2 | sed 's/^/  /' | tee -a "$OUT/run.txt"
}
# A music play: the game's own Play of the 40 MB buffer (its "plays from frame" line; a hold's "held" line names the
# same buffer and is none).
PLAY='stream [0-9a-f]+ \(41943040 bytes.*plays from frame'
# The holds of one music play, from `start` (SECONDS when its play line was seen), while it plays.
events() {
  local name=$1 start=$2 stream=$3 stops0 holds list t kind
  stops0=$(seen "stream $stream stops at")
  holds=$HOLDS
  [ "$name" = tutorial ] && holds=$TUT_HOLDS
  list=$( { for h in $holds; do echo "$h hold"; done
            [ "$name" = song ] && for m in $MINIMISE; do echo "$m minimise"; done; } | sort -n)
  while read -r t kind; do
    [ -n "$t" ] || continue
    while [ $((SECONDS - start)) -lt "$t" ]; do wait_s 0.5; done
    [ "$(seen "stream $stream stops at")" -gt "$stops0" ] && { note "  $name's music stopped before the $kind at $t s"; return; }
    note "$name: $kind at $t s"
    "$kind" "$name-$t"
  done <<< "$list"
}
# The tutorial's music, then the song's, within 20 minutes of the title's click.
end=$((SECONDS + 1200))
until [ "$(seen "$PLAY")" -ge 1 ] || [ $SECONDS -gt $end ]; do wait_s 0.5; done
tut=$(grep -E "$PLAY" "$L" | sed -n 1p | cut -d' ' -f4)
[ -n "$tut" ] || { echo "FAIL: no tutorial within 20 minutes"; stop; exit 1; }
note "the tutorial's music started (stream $tut)"
tut_stops=$(seen "stream $tut stops at")
events tutorial $SECONDS "$tut"
# The tutorial's music alone (MUSICS=1): to its end, and the run is over.
if [ "${MUSICS:-2}" = 1 ]; then
  until [ "$(seen "stream $tut stops at")" -gt "$tut_stops" ] || [ $SECONDS -gt $end ]; do wait_s 1; done
  [ "$(seen "stream $tut stops at")" -gt "$tut_stops" ] ||
    { echo "FAIL: the tutorial's music did not stop"; stop; exit 1; }
  grep -E "stream $tut stops at" "$L" | tail -1 | sed 's/^/  /' | tee -a "$OUT/run.txt"
  note "the tutorial's music stopped; load $(cut -d' ' -f1-3 /proc/loadavg)"
  stop
  python3 "$HERE/line.py" "$OUT/line.csv" "$OUT/line.json" > /dev/null
  [ -z "$HOLDS$TUT_HOLDS$MINIMISE" ] && exit 0
  python3 "$HERE/line.py" holds "$OUT/line.csv" "$L" --windows > "$OUT/holds.txt"
  code=$?
  tee -a "$OUT/run.txt" < "$OUT/holds.txt"
  exit $code
fi
until [ "$(seen "$PLAY")" -ge 2 ] || [ $SECONDS -gt $end ]; do wait_s 0.5; done
song=$(grep -E "$PLAY" "$L" | sed -n 2p | cut -d' ' -f4)
[ -n "$song" ] || { echo "FAIL: no song within 20 minutes"; stop; exit 1; }
note "the song's music started (stream $song)"
stops=$(seen "stream $song stops at")
events song $SECONDS "$song"
until [ "$(seen "stream $song stops at")" -gt "$stops" ] || [ $SECONDS -gt $end ]; do wait_s 1; done
[ "$(seen "stream $song stops at")" -gt "$stops" ] || { echo "FAIL: the song did not stop within 20 minutes"; stop; exit 1; }
grep -E "stream ($tut|$song) stops at" "$L" | sed 's/^/  /' | tee -a "$OUT/run.txt"
note "the song's music stopped; load $(cut -d' ' -f1-3 /proc/loadavg)"
stop
python3 "$HERE/line.py" "$OUT/line.csv" "$OUT/line.json" > /dev/null
# No holds asked: the run itself was all.
[ -z "$HOLDS$TUT_HOLDS$MINIMISE" ] && exit 0
python3 "$HERE/line.py" holds "$OUT/line.csv" "$L" --windows > "$OUT/holds.txt"
code=$?
tee -a "$OUT/run.txt" < "$OUT/holds.txt"
exit $code
