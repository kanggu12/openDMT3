#!/bin/bash
# The game and openDMT3's in-game layer at the screen sizes players have, on either renderer (the CPU image, or this
# PC's graphics card with OPENDMT3_WINE_GPU=1: gpu.sh), each size at the Windows scaling a PC of it has by default:
# 1920x1080 at 100 %, 2560x1440 at 125 %, 3840x2160 at 150 %, 3440x1440 (21:9: bars beside the game's 5:3 picture) at
# 100 % and 2560x1600 (16:10: bars over and under it) at 150 %. The real client starts afresh as a guest on a virtual
# screen of that size with no network, on gpu/song.sh's image (a sound server whose null sink plays in real time, so
# the music lock paces the game at 60 a second as a sound card does), twice a size: drawn at the game's own 1280x768
# (game) and at the screen's size (display, the launcher's Drawn at), the layer's other choices as a player has them
# (locked to the music, FSR 1 at 50, or bilinear when drawn at the screen's size, no anti-aliasing, the frame rate chip
# on), the safety net off so the picture stays as chosen. In each start, in this order:
#   title     the title screen with every picture choice in turn through the chain's measuring choice.now (game: Off,
#             Smooth, FSR 1, NIS, Anime4K; display: no anti-aliasing, FXAA, SMAA Low to Ultra), 2.5 s to settle and
#             7.5 s measured each, then the defaults again
#   overlay   (game) the layer's parts on the title, each made by the pointer at its place, answered in the layer's
#             log, shot, and its cost measured for 6 s: the bar from a rest at the top edge, a toast, the menu from its
#             chip, the sound panel from the menu's row, the question from the X with Keep playing clicked;
#             (display) the bar and the menu
#   pointer   the game reads its pointer on a press: TOUCH to START pressed at its place (in the smallest window in
#             the game start), and in the tutorial a press at the picture's edges, its middle and each bar; each point
#             and the game pixel the game read there in the layer's log (OPENDMT3_POINTER_LOG); the dart's own picture
#             through XFixes (ingame/pointer.py)
#   window    (game) the full screen chip, a window of the game's shape: its menu chip, a phase measured in it; the
#             window sized to a 16:9 client 0.6 of the screen tall (bars beside the picture) and to the layer's
#             smallest unit (960x576), each shot, the smallest with its menu from its chip and TOUCH to START pressed
#             in it; back to full screen by its chip; minimise and back; (display) a window, a phase in it, and back
#   switches  (3840x2160, display) five switches to a window and back
#   tutorial  TOUCH to START at its place; in the guest's tutorial (its song has no title, jacket or video): the
#             defaults and the heaviest choice measured (game: FSR 1, Anime4K; display: none, SMAA Ultra), plain frames
#             shot, the bar called and shot, the question with its line and Keep playing (Enter), the 3, 2, 1 shot,
#             then (3840x2160, display) the chain's measuring lost device (reset.now: the game must reset the device
#             itself; the game alive 15 s after), then the X's Quit the game, its bar shot as it quits, the game's end
#             timed
# Then (HEAVY=1, the default) two starts at 3840x2160 with the heaviest choices as a player has them (no measuring
# folder, so only the passes chosen are made): drawn at the screen's size with SMAA Ultra and the flip model (a reset
# of the device at every change of the window's size) at 200 %, and at 1280x768 with Anime4K at 100 %: 20 s of the
# title, five switches to a window and back, the window at two sizes and back, then 20 s of the tutorial and the quit.
# In every start the process's address space and the device's texture memory are logged every 10 s
# (OPENDMT3_MEMORY_WATCH), and the card's memory in use is read beside them (OUT_DIR/card.txt), its clocks all along
# (gpu/clocks.py). Each start keeps its layer's log, its phases' marks with the machine's load at their edges
# (ingame/quiet.py), its steps and their answers, its pointer's points and its shots (OUT_DIR/SIZE-DPI/KIND/, the heavy
# ones OUT_DIR/heavy-KIND/); sizes.py judges them all at the end (OUT_DIR/summary.md and results.json, its exit code
# this script's). Nothing reaches a real screen or a speaker; the containers are odt3-res-*, each removed after its
# start. About 70 minutes on the GPU.
#
#   [OPENDMT3_WINE_GPU=1] [SIZES="1920x1080@96 2560x1440@120 ..."] [KINDS="game display"] [HEAVY=1] [HEAVY_BUILD=DIR]
#     tests/e2e/windows/gpu/sizes.sh GAME_PARENT BUILD_DIR OUT_DIR [LINK_SOURCE] [WINE_DLLS]
#
# GAME_PARENT, LINK_SOURCE and WINE_DLLS are song.sh's (the parent of a game set up by openDMT3, holding Client
# (openDMT3).exe; copied for each start, links stay links, the one given is never written); BUILD_DIR is ./dmt3 build's
# output or native/cardreader/build.sh's (its CRT_R1.dll is the layer, with multiDLL.dll beside it when there is one).
# SIZES is WIDTHxHEIGHT@DPI words, the dots an inch Windows gives a program aware of its scaling (96 is 100 %).
# KINDS names the kinds of start each size has (game, display: both by default), to run one part again; HEAVY=display
# or HEAVY=game runs one of the two heavy starts, HEAVY=0 neither. HEAVY_BUILD is
# the build the two heavy starts take, BUILD_DIR by default (a release's build measured as it is, with the room's
# lines from a build that has them: a layer without OPENDMT3_MEMORY_WATCH logs none).
set -u
SRC=$(realpath "${1:?usage: sizes.sh GAME_PARENT BUILD_DIR OUT_DIR [LINK_SOURCE] [WINE_DLLS]}")
BUILD=$(realpath "${2:?}")
OUT=$(realpath -m "${3:?}")
LINKS=${4:-}
DLLS=${5:-}
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../../.." && pwd)
. "$HERE/../gpu.sh"
RENDERER=$(wine_on_gpu && echo gpu || echo cpu)
# The sound server's image on top of the renderer's (on the CPU the in-game tests' image, which reads the dart's
# picture through XFixes; the GPU image can already).
BASE=$(wine_image opendmt3-wine-ingame:local)
IMAGE=${BASE%:*}-sound:local
SIZES=${SIZES:-1920x1080@96 2560x1440@120 3840x2160@144 3440x1440@96 2560x1600@144}
KINDS=${KINDS:-game display}
HEAVY=${HEAVY:-1}
DLL=$BUILD/native/CRT_R1.dll
[ -f "$DLL" ] || DLL=$BUILD/CRT_R1.dll
[ -f "$DLL" ] || { echo "FAIL: no CRT_R1.dll in $BUILD or its native folder"; exit 1; }
HEAVY_DLL=$DLL
if [ -n "${HEAVY_BUILD:-}" ]; then
  HEAVY_DLL=$(realpath "$HEAVY_BUILD")/native/CRT_R1.dll
  [ -f "$HEAVY_DLL" ] || HEAVY_DLL=$(realpath "$HEAVY_BUILD")/CRT_R1.dll
  [ -f "$HEAVY_DLL" ] || { echo "FAIL: no CRT_R1.dll in $HEAVY_BUILD or its native folder"; exit 1; }
fi
wait_s() { python3 -c "import time; time.sleep($1)"; }
now_ms() { python3 -c 'import time; print(int(time.monotonic() * 1000))'; }

# ---- the images and the window helper
wine_on_gpu || docker image inspect opendmt3-wine-ingame:local >/dev/null 2>&1 \
  || docker build -q -t opendmt3-wine-ingame:local "$HERE/../ingame" >/dev/null || { echo "FAIL: the test image"; exit 1; }
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  docker build -q --build-arg BASE="$BASE" -t "$IMAGE" "$HERE/sound" >/dev/null || { echo "FAIL: $IMAGE did not build"; exit 1; }
fi
mkdir -p "$OUT/tools"
# The window's place and size as Windows has them, and its size as a drag of its border sets it (ingame/restore.c),
# built with the DLL's compiler (its image made as ingame.sh makes it).
docker image inspect opendmt3-mingw:local >/dev/null 2>&1 || {
  ctx=$(mktemp -d)
  printf 'FROM debian:12\nRUN apt-get update && apt-get install -y --no-install-recommends gcc-mingw-w64-i686 && rm -rf /var/lib/apt/lists/*\n' > "$ctx/Dockerfile"
  docker build -q -t opendmt3-mingw:local "$ctx" >/dev/null
  rm -rf "$ctx"
}
# Not executable: a Windows program is never started from here (WSL would hand it to Windows), only by Wine in the
# container.
docker run --rm --network none -v "$HERE/../ingame:/src:ro" -v "$OUT/tools:/out" opendmt3-mingw:local sh -c \
  'i686-w64-mingw32-gcc -O2 -o /out/restore.exe /src/restore.c -luser32 && chmod 0644 /out/restore.exe' \
  || { echo "FAIL: the window helper did not build"; exit 1; }
# What showing one frame costs the test itself at each size (gpu/measure.sh's present run: a window over the screen
# cleared and presented 300 times; on the GPU each frame shown is read back from the card to the virtual screen first,
# a cost a player's PC does not have, inside every frame time here), 32-bit as the game.
docker run --rm --network none -v "$HERE:/src:ro" -v "$OUT/tools:/out" opendmt3-mingw:local sh -c \
  'i686-w64-mingw32-gcc -O2 -s -Wall -o /out/d3d9probe.exe /src/d3d9probe.c -ld3d9 -lopengl32 -lgdi32 -luser32 && chmod 0644 /out/d3d9probe.exe' \
  || { echo "FAIL: the present probe did not build"; exit 1; }

# ---- the run's notes, the card's clocks all along, its memory in use at the steps that count
NVSMI=/usr/lib/wsl/lib/nvidia-smi
[ -x "$NVSMI" ] || NVSMI=$(command -v nvidia-smi || true)
wine_on_gpu || NVSMI=
{
  echo "$(date '+%F %T') sizes on the $RENDERER: the tree $(git -C "$REPO" log --oneline -1 2>/dev/null), the layer $(sha256sum "$DLL" | cut -c1-16), the heavy starts' $(sha256sum "$HEAVY_DLL" | cut -c1-16)"
  [ -n "$NVSMI" ] && echo "the card: $("$NVSMI" --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>/dev/null | head -1)"
  echo "sizes $SIZES; kinds $KINDS; heavy $HEAVY; load $(cut -d' ' -f1-3 /proc/loadavg)"
} | tee "$OUT/run.txt"
: > "$OUT/card.txt"
card() { [ -n "$NVSMI" ] && echo "$(now_ms) $1: $("$NVSMI" --query-gpu=memory.used,memory.total --format=csv,noheader 2>/dev/null | head -1)" >> "$OUT/card.txt"; }
rm -f "$OUT/.clocks-stop"
[ -n "$NVSMI" ] && python3 "$HERE/clocks.py" "$OUT/gpu-clocks.txt" "$OUT/.clocks-stop" 10800 &
C= SAMPLER=
cleanup() {
  [ -n "$SAMPLER" ] && kill "$SAMPLER" 2>/dev/null
  [ -n "$C" ] && docker rm -f "$C" >/dev/null 2>&1
  touch "$OUT/.clocks-stop"
}
trap cleanup EXIT

# ---- one start's helpers (C its container, D its folder, LOG its layer's log, SIZE W H DPI NAME its own)
x() { docker exec -e DISPLAY=:99 "$C" sh -c "$1"; }
win() { docker exec -e WINEPREFIX=/w -e WINEDEBUG=-all -e DISPLAY=:99 "$C" sh -c "wine /tools/restore.exe $*" 2>/dev/null; }
seen() { grep -cE "$1" "$LOG" 2>/dev/null; }
# wait_more REGEX COUNT SECONDS: until the log has more than COUNT such lines (1 when it never does).
wait_more() {
  local end=$((SECONDS + $3))
  until [ "$(seen "$1")" -gt "$2" ]; do [ $SECONDS -ge $end ] && return 1; wait_s 0.25; done
}
# step NAME ok|fail [DETAIL]: an act and what the layer answered, for sizes.py.
step() { echo "$(now_ms) $1 $2 ${3:-}" >> "$D/steps.txt"; echo "  $SIZE $NAME $1: $2 ${3:-}"; }
# act NAME REGEX SECONDS COMMAND: the command in the container, then the layer's line for it within SECONDS.
act() {
  local before
  before=$(seen "$2")
  x "$4"
  if wait_more "$2" "$before" "$3"; then step "$1" ok; return 0; fi
  step "$1" fail "no line \"$2\" within $3 s"
  return 1
}
# A phase's edges on the log's clock with the machine's load then (ingame/pace.py's marks, ingame/quiet.py's load).
mark() { echo "$1 $2 $(now_ms) $(python3 "$HERE/../ingame/quiet.py" "$D/load-samples.txt")" >> "$D/marks.txt"; }
phase() { mark "$1" start; wait_s "${2:-7.5}"; mark "$1" end; }
# measure PHASE "UPSCALE SHARPNESS ANTIALIASING SHAPE": the choice through choice.now (looked for every tenth frame),
# 2.5 s for the stretch it splits to pass, then the phase.
measure() {
  local before
  before=$(seen "post: choice now")
  echo "$2" > "$D/choice.now"
  wait_more "post: choice now" "$before" 5 || { step "choice-$1" fail "the chain did not take \"$2\""; return 1; }
  wait_s 2.5
  phase "$1" "${3:-7.5}"
}
# The whole virtual screen as it shows (the pointer is not in it), and the layer's last frame count before it.
shot() {
  x "import -window root /out/shots/$1.png"
  echo "$1 $(now_ms) $(grep -E '^[0-9]+ frames: ' "$LOG" | tail -1 | cut -d' ' -f2-9)" >> "$D/shots.txt"
}
# The picture's place in a client CW CH at OX OY and the layer's parts there (sizes.py places: PX PY PW PH U, the *_AT
# points on the screen, PROBES in the client's pixels).
places() {
  # The scaling the layer's smallest unit follows: a layer that says its unit with its textures has the smallest unit
  # grow with the scaling (logic.c ui_unit_floor); 0.4.0's never did (96 here: 0.75 whatever the scaling).
  local floor_dpi=96
  grep -q "parts' textures made for .* output pixels a game pixel" "$LOG" 2>/dev/null && floor_dpi=$DPI
  eval "$(python3 "$HERE/sizes.py" places "$1" "$2" "${3:-0}" "${4:-0}" "$floor_dpi")"
}
# Whether the bar is on the screen now: the layer's last "on the screen" line after its last "gone" line.
bar_up() {
  local on gone
  on=$(grep -n "layer: bar on the screen" "$LOG" 2>/dev/null | tail -1 | cut -d: -f1)
  gone=$(grep -n "layer: bar gone after" "$LOG" 2>/dev/null | tail -1 | cut -d: -f1)
  [ -n "$on" ] && [ "$on" -gt "${gone:-0}" ]
}
# The bar from a rest at the client's top edge (from the picture's middle), three tries; the pointer stays there.
show_bar() {
  local i
  for i in 1 2 3; do
    x "xdotool mousemove $AWAY_AT sleep 0.2 mousemove $TOP_AT"; wait_s 2
    bar_up && return 0
  done
  step bar fail "the bar did not come from a rest at the top edge (3 tries)"
  return 1
}
away() { x "xdotool mousemove $AWAY_AT"; wait_s 1.5; }
focus() { x "xdotool search --name '^ClientApp$' windowfocus --sync" 2>/dev/null; }
game_alive() { x "ps -eo stat=,args= | grep -v '^Z' | grep -q 'Client (openDMT3)\.exe'"; }
# press MODE LABEL CX CY: a press of the mouse at a client point (the game reads its pointer on a press, not on a
# rest: the layer's OPENDMT3_POINTER_LOG line then says the game pixel it got), written down in the client's pixels.
press() {
  echo "$(now_ms) press $1 $2 $OX $OY $3 $4" >> "$D/probes.txt"
  x "xdotool mousemove $((OX + $3)) $((OY + $4)) mousedown 1 sleep 0.1 mouseup 1"
  wait_s 0.4
}
# probe MODE: a press at each of PROBES (only where a press does nothing of note: in the tutorial).
probe() {
  local p label cx cy
  for p in $PROBES; do
    IFS=: read -r label cx cy <<<"$p"
    press "$1" "$label" "$cx" "$cy"
  done
}
# The dart over the game, as XFixes has it.
cursor() { x "xdotool mousemove $AWAY_AT"; wait_s 0.6; x "python3 /probe/pointer.py /out/shots/cursor.png" > "$D/cursor.txt" 2>&1; }
# The game's window as it is now: its client's place and size (restore.c --client), and the places there.
in_window() {
  local c o s
  c=$(win --client ClientApp | grep -oE "client -?[0-9]+,-?[0-9]+ [0-9]+x[0-9]+")
  [ -n "$c" ] || { step window-place fail "the window's client was not found"; return 1; }
  o=${c#client }; o=${o% *}; s=${c##* }
  places "${s%x*}" "${s#*x}" "${o%,*}" "${o#*,}"
}
# The bar's full screen chip: to a window (to_window) or back to full screen (to_full), the pointer away at once.
to_window() {
  show_bar || return 1
  act "$1" "layer: in a window" 5 "xdotool mousemove $FULL_AT sleep 0.4 click 1 sleep 0.05 mousemove $AWAY_AT" || return 1
  wait_s 1.5
  in_window
}
to_full() {
  show_bar || return 1
  act "$1" "layer: full screen" 5 "xdotool mousemove $FULL_AT sleep 0.4 click 1 sleep 0.05 mousemove $AWAY_AT" || return 1
  wait_s 1.5
  places "$W" "$H"
}
# drag NAME CW CH: the window sized so its client is CW x CH, as a drag of its border would; the picture's new size.
drag() {
  local before
  before=$(seen "post: the picture [0-9]+x[0-9]+ in the window's client")
  win --size "$2" "$3" ClientApp >/dev/null
  if wait_more "post: the picture [0-9]+x[0-9]+ in the window's client" "$before" 5; then
    step "$1" ok "$(grep -oE "post: the picture .*" "$LOG" | tail -1 | cut -c7-)"
  else
    step "$1" fail "no new picture size for a client of $2x$3"
  fi
  wait_s 1.5
  in_window
}
minimise() {
  show_bar || return 1
  act minimise "layer: minimised" 5 "xdotool mousemove $MIN_AT sleep 0.4 click 1" || return 1
  win --state ClientApp | grep -q "minimised: 1" || step minimised-state fail "Windows does not say it is minimised"
  win ClientApp >/dev/null
  wait_s 2
  if win --state ClientApp | grep -q "minimised: 0"; then step restored ok; else step restored fail "the window did not come back"; fi
  wait_s 2
}

# start NAME SIZE DPI VAR=VALUE...: a fresh copy of the game and a container for one start; 0 when the layer attached
# and the game drew its title for 40 s (on the GPU through WSL's D3D12, or the start fails).
start() {
  NAME=$1 SIZE=$2 DPI=$3
  shift 3
  W=${SIZE%x*} H=${SIZE#*x}
  # A folder a size and scaling (the same size at two scalings is two starts).
  D=$OUT/$SIZE-$DPI/$NAME
  case $NAME in heavy-*) D=$OUT/$NAME ;; esac
  LOG=$D/ingame.log
  rm -rf "$D"
  mkdir -p "$D/game" "$D/shots"
  cp -a "$SRC/." "$D/game/"
  local client dmt3 rel touch f e
  client=$(find "$D/game" -maxdepth 6 -name "Client (openDMT3).exe" | head -1)
  [ -n "$client" ] || { echo "FAIL: no Client (openDMT3).exe under $SRC"; exit 1; }
  dmt3=$(dirname "$client")
  rel=${dmt3#"$D/game/"}
  rm -f "$dmt3/openDMT3-card.txt" "$dmt3/openDMT3-picture.txt"
  cp "$DLL" "$dmt3/CRT_R1.dll"
  # openDMT3's touch screen library in place of the client data's, as PLAY puts it, when the build has it.
  touch=$(dirname "$DLL")/multiDLL.dll
  if [ -f "$touch" ]; then
    find "$dmt3" -maxdepth 1 -iname "multidll.dll" -delete
    cp "$touch" "$dmt3/multiDLL.dll"
  fi
  f="$REPO/opendmt3/client/assets/fonts"
  cp "$f/Pretendard-Bold.ttf" "$dmt3/openDMT3-Pretendard-Bold.ttf"
  cp "$f/Pretendard-Regular.ttf" "$dmt3/openDMT3-Pretendard-Regular.ttf"
  cp "$f/DMT3Wide-Regular.ttf" "$dmt3/openDMT3-DMT3Wide.ttf"
  find "$D/game" -type f -iname "*.exe" -exec chmod 0644 {} +
  # The layer's choices as a player has them with the chip on, the measuring ones, then this start's.
  local envs=(-e OPENDMT3_LANGUAGE=en -e OPENDMT3_CURSOR=on -e OPENDMT3_PACING=music -e OPENDMT3_FPS=on
              -e OPENDMT3_UPSCALE=fsr1 -e OPENDMT3_SHARPNESS=50 -e OPENDMT3_ANTIALIASING=off -e OPENDMT3_SAFETY=off
              -e OPENDMT3_PASS_TIMES=on -e OPENDMT3_SOUND_WATCH=1 -e OPENDMT3_POINTER_LOG=1 -e OPENDMT3_MEMORY_WATCH=on)
  for e in "$@"; do envs+=(-e "$e"); done
  printf 'SIZE=%s\nDPI=%s\nKIND=%s\nCHOICES=%s\nLAYER=%s\n' "$SIZE" "$DPI" "$NAME" "$*" "$(sha256sum "$DLL" | cut -c1-16)" > "$D/start.txt"
  C=odt3-res-$RENDERER-$W-$H-$NAME-$$
  local mounts=(-v "$D/game:/root/Desktop/game" -v "$D:/out" -v "$HERE/../ingame:/probe:ro" -v "$OUT/tools:/tools:ro")
  [ -n "$LINKS" ] && mounts+=(-v "$LINKS:$LINKS:ro")
  [ -n "$DLLS" ] && mounts+=(-v "$(realpath "$DLLS"):/dlls:ro")
  echo "== $SIZE $NAME at $DPI dpi: $*"
  card "$SIZE $NAME before"
  docker run -d --name "$C" --network none --ulimit core=1 -e SCREEN="$SIZE" -e DPI="$DPI" -e REL_DMT3="$rel" \
    -e PRESENT="$([ "$NAME" = game ] && echo 1)" \
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
    # Windows scaling as a PC of this size has it: the dots an inch a program aware of the scaling is given.
    wine reg add "HKCU\\Control Panel\\Desktop" /v LogPixels /t REG_DWORD /d "$DPI" /f >/dev/null 2>&1
    wine reg add "HKLM\\System\\CurrentControlSet\\Hardware Profiles\\Current\\Software\\Fonts" /v LogPixels \
      /t REG_DWORD /d "$DPI" /f >/dev/null 2>&1
    wineserver -w
    [ -d /dlls ] && cp /dlls/*.dll /w/drive_c/windows/syswow64/
    # What draws OpenGL here, as the game will be drawn.
    glxinfo -B 2>/dev/null | grep -E "OpenGL (renderer|version) string" > /out/glx.txt
    # What showing a frame costs the test itself at this size, before the game (the first start of a size only).
    [ -n "$PRESENT" ] && (cd /out && wine /tools/d3d9probe.exe --present ${SCREEN%x*} ${SCREEN#*x} > /out/present.txt 2>&1; \
      wineserver -w)
    cd "/root/Desktop/game/$REL_DMT3"
    OPENDMT3_INGAME_LOG="Z:\\out\\ingame.log" wine "Client (openDMT3).exe" > /out/wine.txt 2>&1
    echo "exit $?" > /out/exit.txt
    sleep infinity' >/dev/null || { echo "FAIL: the container did not start"; C=; return 1; }
  # Our container's CPU time and the load average every 2 s, for quiet.py (the others' share of the load).
  local cgroup
  cgroup=$(find /sys/fs/cgroup -maxdepth 3 -type d -name "*$(docker inspect -f '{{.Id}}' "$C")*" 2>/dev/null | head -1)
  (while :; do
    echo "$(now_ms) $(awk '/^usage_usec/ {print $2}' "$cgroup/cpu.stat" 2>/dev/null || echo 0) $(cut -d' ' -f1 /proc/loadavg)"
    sleep 2
  done) > "$D/load-samples.txt" &
  SAMPLER=$!
  local end=$((SECONDS + 300)) proof drawn
  until grep -q "layer: attached" "$LOG" 2>/dev/null || [ $SECONDS -gt $end ]; do wait_s 2; done
  grep -q "layer: attached" "$LOG" 2>/dev/null || { step attached fail "the layer never attached in 300 s"; return 1; }
  wait_s 40
  proof=$(gpu_proof "$C" 'Client (openDMT3).exe')
  drawn=$?
  echo "RENDERER_SAID=$(sed -n 's/^OpenGL renderer string: //p' "$D/glx.txt" 2>/dev/null | head -1)${proof:+;}$(echo "$proof" | sed 's/^ *//')" >> "$D/start.txt"
  [ $drawn = 0 ] || { step on-the-gpu fail "$proof"; return 1; }
  step attached ok "$(grep -m1 -oE 'layer: attached .*' "$LOG" | cut -c8-)"
  places "$W" "$H"
  card "$SIZE $NAME title"
  return 0
}
finish() {
  [ -n "$SAMPLER" ] && kill "$SAMPLER" 2>/dev/null
  SAMPLER=
  [ -n "$C" ] && docker rm -f "$C" >/dev/null 2>&1
  C=
  rm -rf "$D/game"
}

# ---- the parts of a start
# The layer's parts on the title, each shot and its cost measured while it shows.
overlay_title() {
  local before
  shot title
  # A toast, as the safety net shows its note (toast.now).
  before=$(seen "layer: toast shown")
  echo "Picture quality lowered to keep 60 FPS: now Smooth upscale" > "$D/toast.now"
  if wait_more "layer: toast shown" "$before" 5; then
    step toast ok; wait_s 0.8; shot toast
    # The toast lasts 6 s: the same words again keep it up (its picture as it was) for a phase of whole windows.
    mark parts:toast start; wait_s 2.5
    echo "Picture quality lowered to keep 60 FPS: now Smooth upscale" > "$D/toast.now"; wait_s 3.5; mark parts:toast end
  else
    step toast fail "not shown in 5 s"
  fi
  wait_s 5
  show_bar && { step bar ok; shot bar; phase parts:bar 6; }
  act menu "layer: menu opened" 5 "xdotool mousemove $MENU_AT sleep 0.4 click 1" && { wait_s 0.6; shot menu; phase parts:menu 6; }
  # The menu's SOUND row by its place: the sound panel; Esc back to the menu, Esc again to the game.
  act sound-panel "layer: sound panel opened" 5 "xdotool mousemove $SOUND_AT sleep 0.3 click 1" \
    && { x "xdotool mousemove $AWAY_AT"; wait_s 0.8; shot sound; }
  focus
  act sound-back "layer: back to the menu from the sound panel" 3 "xdotool key Escape"
  act menu-closed "layer: closed, back to the game" 3 "xdotool key Escape"
  away
  # The X's question (no line on the game's menus), Keep playing by its place.
  show_bar && act question "layer: question opened" 5 "xdotool mousemove $X_AT sleep 0.4 click 1" \
    && { wait_s 0.6; shot question; phase parts:question 6; \
         act keep-playing "layer: closed, back to the game" 3 "xdotool mousemove $KEEP_AT sleep 0.4 click 1"; }
  away
}
# A window from the chip, its points, a phase in it, two sizes of it, back to full screen, minimise and back.
window_part() {
  to_window window || return 1
  shot window
  show_bar && act menu-in-window "layer: menu opened" 5 "xdotool mousemove $MENU_AT sleep 0.4 click 1" \
    && { wait_s 0.6; shot window-menu; focus; x "xdotool key Escape"; }
  away
  measure window:fsr1 "fsr1 50 off keep"
  # A 16:9 client 0.6 of the screen tall (bars beside the picture), then the layer's smallest unit (960x576).
  local ah=$((H * 6 / 10))
  drag window-16x9 $((ah * 16 / 9)) "$ah" && { show_bar && shot window-16x9; away; }
  drag window-smallest 960 576 && {
    show_bar && act menu-smallest "layer: menu opened" 5 "xdotool mousemove $MENU_AT sleep 0.4 click 1" \
      && { wait_s 0.6; shot window-smallest; focus; x "xdotool key Escape"; }
    away
    # TOUCH to START pressed here, in the smallest window: the game's own read of the pointer in a window (the guest's
    # screens then count down to the tutorial by themselves, back in full screen).
    press window-smallest start $((${START_AT%% *} - OX)) $((${START_AT##* } - OY)); }
  to_full full-again
  wait_s 3.5
  minimise
}
# Five switches to a window and back.
switches() {
  local i
  for i in 1 2 3 4 5; do
    to_window "switch-$i-window" || break
    wait_s 3
    to_full "switch-$i-full" || break
    wait_s 3
  done
}
# The measuring lost device (reset.now: a reset made with the game's objects alive, which fails and leaves the device
# to be reset): the game must reset its device itself; 0 when it did. Last in its start: a game that cannot reset it
# draws nothing more.
lost_device() {
  local made back
  made=$(seen "post: measuring reset made")
  # The device back: the chain made again after a reset that worked (a reset that fails says so, and the game tries
  # again; its first try's lines come before the reset is made, so they say nothing of whether it worked).
  back=$(seen "post: the chain's objects made again after the reset")
  touch "$D/reset.now"
  if wait_more "post: measuring reset made" "$made" 6; then
    step lost-device ok "$(grep -oE 'post: measuring reset made.*' "$LOG" | tail -1 | cut -c7-)"
    if wait_more "post: the chain's objects made again after the reset" "$back" 15; then
      step device-back ok "$(grep -oE "post: the chain's objects made again.*" "$LOG" | tail -1 | cut -c7-)"
    else
      step device-back fail "the game's own reset did not work in 15 s ($(grep -oE 'post: the reset failed.*' "$LOG" | tail -1 | cut -c7-))"
      return 1
    fi
  else
    step lost-device fail "the measuring reset was not made"
    return 1
  fi
  wait_s 15
  if game_alive; then step alive-after-resets ok; else step alive-after-resets fail "the game ended"; return 1; fi
  card "$SIZE $NAME after the lost device"
}
# TOUCH to START at its place (unless it was pressed in a window already), then the guest's screens count down to
# the tutorial by themselves.
to_tutorial() {
  grep -q " start " "$D/probes.txt" 2>/dev/null || press full start $((${START_AT%% *} - OX)) $((${START_AT##* } - OY))
  local end=$((SECONDS + 300))
  until grep -q "(41943040 bytes" "$LOG" 2>/dev/null || [ $SECONDS -gt $end ]; do wait_s 1; done
  TUT=$(grep "(41943040 bytes" "$LOG" | head -1 | cut -d' ' -f4)
  [ -n "$TUT" ] || { step tutorial fail "its song did not start within 300 s of TOUCH to START"; return 1; }
  step tutorial ok "stream $TUT"
  wait_s 6
}
# Whether the tutorial's song has stopped (the song select comes next: no shot of it is ever taken).
over() { grep -q "stream $TUT stops at" "$LOG"; }
# tutorial_part DEFAULT HEAVY DEFAULT_NAME HEAVY_NAME: both measured, frames shot, the bar, the question and its 3, 2, 1.
tutorial_part() {
  local before
  over || measure "play:$3" "$1"
  over || measure "play:$4" "$2"
  over || { echo "$1" > "$D/choice.now"; wait_s 1.5; }
  # The game's own read of the pointer at the picture's edges, its middle and each bar: presses, which a tutorial
  # takes as it takes any.
  over || probe full
  over || { x "xdotool mousemove $AWAY_AT"; wait_s 1; over || shot play-1; }
  over || { wait_s 2; over || shot play-2; }
  over || { show_bar && { over || shot play-bar; }; away; }
  over && return 0
  show_bar || return 0
  act question-in-song "layer: question opened \(a song plays" 5 "xdotool mousemove $X_AT sleep 0.4 click 1" || return 0
  wait_s 0.6
  shot play-question
  focus
  # Keep playing (Enter): the 3, 2, 1 shot in its first second, then the way back into the song said.
  before=$(seen "layer: back into the song")
  x "xdotool key Return"
  wait_s 0.5
  shot play-resume
  if wait_more "layer: back into the song" "$before" 6; then
    step resume ok "$(grep -oE 'layer: back into the song.*' "$LOG" | tail -1 | cut -c8-)"
  else
    step resume fail "no way back into the song in 6 s"
  fi
  over || { wait_s 2; over || shot play-3; }
}
# The X's Quit the game (Right, Enter), its bar shot as it quits, the game's end timed.
quit_part() {
  local t0 end
  show_bar || return 1
  act quit-question "layer: question opened" 5 "xdotool mousemove $X_AT sleep 0.4 click 1" || return 1
  wait_s 0.6
  focus
  x "xdotool key Right"
  wait_s 0.4
  t0=$(now_ms)
  x "xdotool key Return"
  wait_s 0.3
  over || shot play-quitting
  end=$((SECONDS + 15))
  until [ -f "$D/exit.txt" ] || [ $SECONDS -gt $end ]; do wait_s 0.25; done
  if [ -f "$D/exit.txt" ]; then
    step quit ok "$(cat "$D/exit.txt") $(python3 -c "print('%.1f' % (($(now_ms) - $t0) / 1000.0))") s after Quit the game"
  else
    step quit fail "the game had not ended 15 s after Quit the game"
  fi
}

# ---- the sizes
for spec in $SIZES; do
  size=${spec%@*} dpi=${spec#*@}
  # Drawn at the game's own 1280x768: every upscale filter, the layer's parts, the pointer, the window.
  if [[ " $KINDS " == *" game "* ]] && start game "$size" "$dpi" OPENDMT3_RENDER=game 'OPENDMT3_POSTFX_DUMP=Z:\out'; then
    for c in off smooth fsr1 nis anime4k; do measure "title:$c" "$c 50 off keep"; done
    echo "fsr1 50 off keep" > "$D/choice.now"
    wait_s 2.5
    overlay_title
    cursor
    window_part
    to_tutorial && { tutorial_part "fsr1 50 off keep" "anime4k 50 off keep" fsr1 anime4k; quit_part; }
  fi
  finish
  # Drawn at the screen's size: every anti-aliasing, the bar and the menu, a window, at 3840x2160 the resets.
  if [[ " $KINDS " == *" display "* ]] && start display "$size" "$dpi" OPENDMT3_RENDER=display 'OPENDMT3_POSTFX_DUMP=Z:\out'; then
    for a in off fxaa smaa-low smaa-medium smaa-high smaa-ultra; do measure "title:$a" "smooth 50 $a keep"; done
    echo "smooth 50 off keep" > "$D/choice.now"
    wait_s 2.5
    shot title
    show_bar && { step bar ok; shot bar; }
    act menu "layer: menu opened" 5 "xdotool mousemove $MENU_AT sleep 0.4 click 1" \
      && { wait_s 0.6; shot menu; focus; x "xdotool key Escape"; }
    away
    to_window window && { measure window:off "smooth 50 off keep"; shot window; to_full full-again; }
    [ "$size" = 3840x2160 ] && switches
    if to_tutorial; then
      tutorial_part "smooth 50 off keep" "smooth 50 smaa-ultra keep" off smaa-ultra
      # At 3840x2160 the lost device last (a game that cannot reset its device draws nothing more), the quit after it
      # when the device came back.
      if [ "$size" != 3840x2160 ] || lost_device; then quit_part; fi
    fi
  fi
  finish
done

# ---- the heaviest choices at 3840x2160 as a player has them (no measuring folder: only the chosen passes made)
heavy() {
  local name=$1 dpi=$2 i keep=$DLL
  shift 2
  DLL=$HEAVY_DLL
  if start "$name" 3840x2160 "$dpi" "$@"; then
    phase title:heavy 20
    card "$SIZE $NAME the title"
    for i in 1 2 3 4 5; do
      to_window "switch-$i-window" || break
      wait_s 3
      to_full "switch-$i-full" || break
      wait_s 3
    done
    to_window window-again && {
      drag window-16x9 2304 1296; wait_s 3
      drag window-smallest 960 576; wait_s 3
      to_full full-again; }
    card "$SIZE $NAME after the changes"
    wait_s 15
    if game_alive; then step alive-after-changes ok; else step alive-after-changes fail "the game ended"; fi
    to_tutorial && {
      phase play:heavy 20
      card "$SIZE $NAME in the tutorial"
      over || { x "xdotool mousemove $AWAY_AT"; wait_s 1; over || shot play-1; }
      quit_part; }
  fi
  finish
  DLL=$keep
}
# HEAVY=1 both, display or game the one, 0 none.
if [ "$HEAVY" = 1 ] || [ "$HEAVY" = display ]; then
  heavy heavy-display 192 OPENDMT3_RENDER=display OPENDMT3_ANTIALIASING=smaa-ultra OPENDMT3_FLIP_MODEL=on
fi
if [ "$HEAVY" = 1 ] || [ "$HEAVY" = game ]; then
  heavy heavy-game 96 OPENDMT3_RENDER=game OPENDMT3_UPSCALE=anime4k
fi

touch "$OUT/.clocks-stop"
echo "== the report"
python3 "$HERE/sizes.py" report "$OUT"
