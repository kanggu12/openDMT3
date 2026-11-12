#!/bin/bash
# What the game and openDMT3's in-game layer cost a frame, the same scenes on this PC's GPU (OPENDMT3_WINE_GPU=1) and on
# the CPU (the CPU image, Mesa's llvmpipe), at one screen size. Each run starts the real client afresh under Wine on a
# virtual screen with no network, as a guest, and measures its title screen (it waits for TOUCH to START as long as it
# is left), after it has settled:
#   renderer        what draws the game: the OpenGL renderer Wine's X11 driver reads in the game's own process (its
#                   wgl channel) and, on the GPU, the process holding WSL's D3D12 (gpu.sh gpu_proof)
#   present         no game: what showing one frame on the virtual screen costs by itself, a window over the screen
#                   cleared and presented 300 times (d3d9probe.exe --present); on the GPU each frame shown is read
#                   back from the card first, a cost a player's PC does not have, inside every frame time below
#   alone           the game without openDMT3 (the cabinet's own card reader DLL, no layer, no chain) and its own
#                   60 a second limiter: every frame's length as Wine's Direct3D times its presents (+frametime)
#   alone-free      the same with that limiter taken out of a copy of the client and VSync off: as fast as it goes
#   both-clocks     openDMT3 at its defaults timed by both clocks at once, the layer's counter and Wine's own frame
#                   times: how the two compare where both exist (Wine's is the only one for the game alone)
#   own-steps       the game's own 60 a second limiter (no clock of ours) with openDMT3's lightest picture (nearest,
#                   no anti-aliasing) and nothing of the layer shown but its mark: the client's own pacing timed by the
#                   layer's counter, the clock every openDMT3 run below is timed by (Wine's own frame times, the only
#                   clock where there is no layer, are its command thread's and spread wider: both-clocks)
#   free            openDMT3 at the picture defaults with the limiter out, no clock of ours and VSync off
#                   (OPENDMT3_INGAME_UNLOCK, measuring only): as fast as it goes with the chain
#   UPSCALE:AA      openDMT3 as a player has it (pacing locked to the music, VSync on) with that picture choice:
#                   fsr1:off is the defaults; the layer's frame counter and the chain's own time, on the GPU from its
#                   timestamps (post: GPU)
#   parts-frame     the defaults with OPENDMT3_LAYER_TIMING=frame (each frame's chain and layer work timed whole, the
#                   device idle before and after) and each part of the layer shown in turns, 4.2 s with it and 4.2 s
#                   without: the chip, the bar, the menu, the question, a toast; the mark is in every turn without (it
#                   shows whenever nothing else is at the top)
#   parts-gpu       the same turns with OPENDMT3_LAYER_TIMING=on: each kind of part's GPU time from its timestamps (on
#                   the CPU's renderer they say nothing, and measure.py leaves them out)
#   passes          the picture's GPU time by pass (OPENDMT3_PASS_TIMES=on), every choice in turn in one run of the game
#                   (every pass is made when measuring, and choice.now turns the choice at once): Off, Smooth, FSR 1,
#                   NIS, Anime4K with no anti-aliasing, then FSR 1 with FXAA and SMAA Low to Ultra, each in the
#                   picture's own shape (Keep) and filling the screen (Fill), 6 s each after 2.5 s to settle; then, at
#                   the defaults, the layer's parts in turn (the chip, the bar, the menu, the question, a toast) for the
#                   glass's blur and the parts' drawing. Each step's time is the gap between its timestamp and the one
#                   before it, with an empty pass (one pixel drawn) and two timestamps in a row to say what any pass and
#                   any timestamp cost before their own work, and the game's own frame from the last present on
#   chip            the frame rate chip on with the limiter out and VSync off: the frame rate moves, so the chip's
#                   number changes at every count (twice a second) and each update is timed (its picture drawn again,
#                   then what changed of it uploaded); with what making every part's textures took at the layer's
#                   first frame, and whether any was made after it
#   pictures:SHAPE  the chain's measuring dump of frames of the title screen (PICTURE_FRAMES, by default 1800 and
#                   2400), every filter and anti-aliasing on each, the picture kept in its shape or filling (keep or
#                   fill). The title's animation does not land on the same picture at a frame number in two runs, so
#                   to hold one build's pictures against another's, the second run is given the first's session
#                   (PICTURE_SOURCE=OUT_DIR/RENDERER-SCREEN of it): each frame it dumps takes the first run's game
#                   picture of that frame in place of its own (OPENDMT3_POSTFX_SOURCE), then pictures.py A_DIR B_DIR
# measure.py turns each run's logs into its numbers (OUT_DIR/RENDERER-SCREEN/results.json) and the table of runs.
# Nothing reaches a real screen; the container (either image) is named odt3-gpu-measure-*, removed at the end.
#
#   [OPENDMT3_WINE_GPU=1] [SCREEN=1920x1080] [TURNS=4] [PICTURE_FRAMES=1800,2400] [PICTURE_SOURCE=SESSION]
#     tests/e2e/windows/gpu/measure.sh GAME_PARENT BUILD_DIR OUT_DIR \
#     [LINK_SOURCE] [WINE_DLLS] [RUN...]
#
# GAME_PARENT, LINK_SOURCE and WINE_DLLS are install_and_play.sh's (the game parent is copied first, links stay links,
# and the one given is never written); BUILD_DIR is ./dmt3 build's output, whose native/CRT_R1.dll is the layer. With
# no RUN given, all of them in the order above but the pictures (about 35 minutes).
set -u
SRC=$(realpath "${1:?usage: measure.sh GAME_PARENT BUILD_DIR OUT_DIR [LINK_SOURCE] [WINE_DLLS] [RUN...]}")
BUILD=$(realpath "${2:?}")
OUT=$(realpath -m "${3:?}")
LINKS=${4:-}
DLLS=${5:-}
shift $(($# < 5 ? $# : 5))
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../../.." && pwd)
# The renderer: the CPU image by default, the GPU image with OPENDMT3_WINE_GPU=1 (gpu.sh).
. "$HERE/../gpu.sh"
SCREEN=${SCREEN:-1920x1080}
W=${SCREEN%x*}
H=${SCREEN#*x}
TURNS=${TURNS:-4}
PICTURE_FRAMES=${PICTURE_FRAMES:-1800,2400}
RENDERER=$(wine_on_gpu && echo gpu || echo cpu)
SESSION="$OUT/$RENDERER-$SCREEN"
RUNS=("$@")
[ ${#RUNS[@]} -gt 0 ] || RUNS=(renderer present alone alone-free both-clocks own-steps free fsr1:off smooth:off nis:off fsr1:fxaa fsr1:smaa-low fsr1:smaa-medium
                              fsr1:smaa-high fsr1:smaa-ultra parts-frame parts-gpu passes chip)
[ -f "$BUILD/native/CRT_R1.dll" ] || { echo "FAIL: no native/CRT_R1.dll in $BUILD (./dmt3 build's output)"; exit 1; }
mkdir -p "$SESSION"
wait_s() { python3 -c "import time; time.sleep($1)"; }
now_ms() { python3 -c 'import time; print(int(time.monotonic() * 1000))'; }

# ---- the game's copy: openDMT3's DLL and the original beside it, a client with its limiter out, VSync off for it
rm -rf "$SESSION/game"
mkdir -p "$SESSION/game"
cp -a "$SRC/." "$SESSION/game/"
CLIENT=$(find "$SESSION/game" -maxdepth 6 -name "Client (openDMT3).exe" | head -1)
[ -n "$CLIENT" ] || { echo "FAIL: no Client (openDMT3).exe under $SRC"; exit 1; }
DMT3=$(dirname "$CLIENT")
REL_DMT3=${DMT3#"$SESSION/game/"}
[ -f "$DMT3/backup/CRT_R1.dll" ] || { echo "FAIL: no backup/CRT_R1.dll (the cabinet's own card reader) in the copy"; exit 1; }
# A guest, as probe runs are: no card for the card reader, no picture choice file of an earlier PLAY.
rm -f "$DMT3/openDMT3-card.txt" "$DMT3/openDMT3-picture.txt"
cp "$DMT3/backup/CRT_R1.dll" "$DMT3/CRT_R1.original.dll"
cp "$BUILD/native/CRT_R1.dll" "$DMT3/CRT_R1.openDMT3.dll"
# The layer's three faces beside it, as PLAY puts them.
F="$REPO/opendmt3/client/assets/fonts"
cp "$F/Pretendard-Bold.ttf" "$DMT3/openDMT3-Pretendard-Bold.ttf"
cp "$F/Pretendard-Regular.ttf" "$DMT3/openDMT3-Pretendard-Regular.ttf"
cp "$F/DMT3Wide-Regular.ttf" "$DMT3/openDMT3-DMT3Wide.ttf"
# The client with its 60 a second limiter out (the jump at 0x455430 back to the function's own first bytes, exactly as
# the layer's OPENDMT3_INGAME_UNLOCK does in memory), for the game alone as fast as it goes.
python3 "$HERE/unlimit.py" "$CLIENT" "$DMT3/Client (free).exe" || { echo "FAIL: the client's limiter could not be taken out"; exit 1; }
# Not executable: a Windows program is never started from here (WSL would hand it to Windows).
chmod 0644 "$DMT3/Client (free).exe"
INI="$DMT3/Resource/config/setting.ini"
cp "$INI" "$SESSION/setting.vsync-on.ini"
sed 's/^vsync=true/vsync=false/' "$INI" > "$SESSION/setting.vsync-off.ini"
grep -q "^vsync=false" "$SESSION/setting.vsync-off.ini" || { echo "FAIL: setting.ini has no vsync=true to turn off"; exit 1; }
# The probe for the present run, 32-bit as the game (gpu/check.sh builds it the same way; not executable here).
docker run --rm --network none -v "$HERE:/src:ro" -v "$SESSION:/out" opendmt3-mingw:local sh -c \
  'i686-w64-mingw32-gcc -O2 -s -Wall -o /out/d3d9probe.exe /src/d3d9probe.c -ld3d9 -lopengl32 -lgdi32 -luser32 && chmod 0644 /out/d3d9probe.exe' \
  || { echo "FAIL: the probe did not build"; exit 1; }

# ---- the container: the virtual screen at SCREEN, a fresh prefix, silent sound
C=odt3-gpu-measure-$RENDERER-$W
docker rm -f "$C" >/dev/null 2>&1
mounts=(-v "$SESSION/game:/root/Desktop/game" -v "$SESSION:/out")
[ -n "$LINKS" ] && mounts+=(-v "$LINKS:$LINKS:ro")
[ -n "$DLLS" ] && mounts+=(-v "$(realpath "$DLLS"):/dlls:ro")
# An earlier run's session, whose game pictures the pictures runs take (read only).
[ -n "${PICTURE_SOURCE:-}" ] && mounts+=(-v "$(realpath "$PICTURE_SOURCE"):/in:ro")
# The CPU image's runs get no core dumps either (one more container on this PC's crash capture is nobody's use).
docker run -d --name "$C" --network none --ulimit core=1 -e SCREEN="$SCREEN" "${WINE_RUN_ARGS[@]}" "${mounts[@]}" \
  "$(wine_image opendmt3-wine:local)" bash -c '
  env -u GALLIUM_DRIVER -u LD_LIBRARY_PATH Xvfb :99 -screen 0 ${SCREEN}x24 -nolisten tcp >/dev/null 2>&1 &
  export WINEPREFIX=/w DISPLAY=:99 WINEDLLOVERRIDES="mscoree,mshtml=" WINEDEBUG=-all
  printf "pcm.!default { type null }\nctl.!default { type hw card 0 }\n" > /etc/asound.conf
  wineboot -i >/dev/null 2>&1; wineserver -w
  [ -d /dlls ] && cp /dlls/*.dll /w/drive_c/windows/syswow64/
  touch /out/.prefix-ready
  sleep infinity' >/dev/null || { echo "FAIL: the container did not start"; exit 1; }
end=$((SECONDS + 180)); until [ -f "$SESSION/.prefix-ready" ] || [ $SECONDS -gt $end ]; do wait_s 1; done
[ -f "$SESSION/.prefix-ready" ] || { echo "FAIL: the prefix was not made"; docker rm -f "$C" >/dev/null; exit 1; }
rm -f "$SESSION/.prefix-ready"
x() { docker exec -e DISPLAY=:99 "$C" sh -c "$1"; }
# The card's clocks over the session, on the GPU: a pass's time scales with the shader clock, which an NVIDIA card
# keeps at a few hundred MHz under a load this light (clocks.py; measure.py puts each phase's beside its times).
rm -f "$SESSION/.clocks-stop" "$SESSION/gpu-clocks.txt"
CLOCKS=
if wine_on_gpu; then python3 "$HERE/clocks.py" "$SESSION/gpu-clocks.txt" "$SESSION/.clocks-stop" & CLOCKS=$!; fi
game_alive() { x "ps -eo stat=,args= | grep -v '^Z' | grep -q 'Client (.*)\.exe'"; }
# The machine's load (1, 5 and 15 minutes) and this container's CPUs over the run, for every result.
cgroup=$(find /sys/fs/cgroup -maxdepth 3 -type d -name "*$(docker inspect -f '{{.Id}}' "$C")*" 2>/dev/null | head -1)
cpu_usec() { awk '/^usage_usec/ {print $2}' "$cgroup/cpu.stat" 2>/dev/null || echo 0; }

# ---- the layer's parts on the screen (native/cardreader/logic.c ui_layout, in game pixels times the picture's height
# over 768): the bar from a rest at the top edge, its X and its menu chip. The picture keeps its own 5:3 shape (the
# default, logic.c picture_rect): the largest such rectangle centred in the screen, the layer lying in it.
read -r PIC_X PIC_W PIC_H < <(python3 -c "
w, h = $W, $H
pw, ph = (round(h * 5 / 3), h) if w * 3 > h * 5 else (w, round(w * 3 / 5))
print((w - pw) // 2, pw, ph)")
U=$(python3 -c "print($PIC_H / 768)")
at() { python3 -c "print('%d %d' % ($1, $2))"; }
X_AT=$(at "$PIC_X + $PIC_W - $U * 37" "$U * 35")
MENU_AT=$(at "$PIC_X + $PIC_W - $U * 215" "$U * 35")
REST_X=$((PIC_X + PIC_W * 1300 / 1920))
show_bar() { x "xdotool mousemove $REST_X $((H / 2)) sleep 0.2 mousemove $REST_X 0"; wait_s 2; }
away() { x "xdotool mousemove $((W / 2)) $((H * 700 / 1080))"; wait_s 1.6; }
focus() { x "xdotool search --name '^ClientApp$' windowfocus --sync" 2>/dev/null; }
fps_menu() { show_bar; x "xdotool mousemove $MENU_AT sleep 0.4 click 1"; wait_s 1; focus; x "xdotool key Down sleep 0.3 key Return sleep 0.5 key Escape"; away; }

# ---- one run: start the client with its choices, wait for its first screen and its settling, measure, end it
# A run's folder: its name with ':' as '-' (a Windows path has no ':' past its drive letter).
dir_of() { echo "${1//:/-}"; }
# start RUN CLIENT_FILE VSYNC(on|off) DLL(openDMT3|original) [VAR=VALUE...]
start() {
  local run=$1 client=$2 vsync=$3 dll=$4
  shift 4
  local d
  d=$(dir_of "$run")
  local dir="$SESSION/$d"
  rm -rf "$dir"
  mkdir -p "$dir"
  cp "$DMT3/CRT_R1.$dll.dll" "$DMT3/CRT_R1.dll"
  cp "$SESSION/setting.vsync-$vsync.ini" "$INI"
  # The layer's log into the run's folder; for the parts' turns the chain's measuring folder too (a toast is asked
  # for there: toast.now), never for the runs that time the frames as a player has them.
  local envs="WINEDEBUG=-all OPENDMT3_INGAME_LOG='Z:\\out\\$d\\ingame.log'"
  case "$run" in parts-* | passes | pictures:*) envs="$envs OPENDMT3_POSTFX_DUMP='Z:\\out\\$d'" ;; esac
  for e in "$@"; do envs="$envs '$e'"; done
  echo "$(date +%T) $run: $client, VSync $vsync, $dll card reader, $*" | tee "$dir/run.txt"
  echo "load at the start: $(cut -d' ' -f1-3 /proc/loadavg)" >> "$dir/run.txt"
  # Detached: the client runs on while the run measures it; its output (Wine's frame times, when asked) in wine.txt.
  docker exec -d -e DISPLAY=:99 "$C" sh -c "cd '/root/Desktop/game/$REL_DMT3' && env WINEPREFIX=/w $envs wine '$client' > '/out/$d/wine.txt' 2>&1"
}
# The first screen (the layer's own line; with no layer, Wine's first presents) and 20 s of settling after it.
settle() {
  local d end=$((SECONDS + 240))
  d=$(dir_of "$1")
  if [ "${2:-}" = alone ]; then
    # With no layer: 600 frames presented (the game's loading done), then 25 s.
    until [ "$(grep -c 'Frame duration' "$SESSION/$d/wine.txt" 2>/dev/null)" -gt 600 ] || [ $SECONDS -gt $end ]; do wait_s 1; done
    wait_s 25
  else
    until grep -q "the game's first screen" "$SESSION/$d/ingame.log" 2>/dev/null || [ $SECONDS -gt $end ]; do wait_s 1; done
    grep -q "the game's first screen" "$SESSION/$d/ingame.log" 2>/dev/null || return 1
    wait_s 20
  fi
  game_alive
}
# A phase's edge on the layer's clock (the monotonic clock in milliseconds), with the 1-minute load and this
# container's CPU time then.
mark() { echo "$1 $2 $(now_ms) $(cut -d' ' -f1 /proc/loadavg) $(cpu_usec)" >> "$SESSION/$(dir_of "$3")/marks.txt"; }
phase() { mark "$1" start "$2"; wait_s "${3:-4.2}"; mark "$1" end "$2"; }
# The window: 30 s of the title screen (the lines of Wine's frame times counted at its edges for the runs without the
# layer).
window() {
  local d
  d=$(dir_of "$1")
  echo "frametime lines at the start: $(grep -c 'Frame duration' "$SESSION/$d/wine.txt" 2>/dev/null)" >> "$SESSION/$d/run.txt"
  phase window "$1" 30
  echo "frametime lines at the end: $(grep -c 'Frame duration' "$SESSION/$d/wine.txt" 2>/dev/null)" >> "$SESSION/$d/run.txt"
}
# The parts in turns (each TURNS times): with it, then without it; the chip on at the start (OPENDMT3_FPS=on).
turns() {
  local run=$1 i
  x "xdotool mousemove $((W / 2)) $((H * 700 / 1080))"; wait_s 1
  for i in $(seq 1 "$TURNS"); do phase chip "$run"; fps_menu; phase off-chip "$run"; fps_menu; done
  # The chip off for the other parts (each part alone on the screen but the mark).
  fps_menu
  for i in $(seq 1 "$TURNS"); do show_bar; phase bar "$run"; away; phase off-bar "$run"; done
  for i in $(seq 1 "$TURNS"); do show_bar; x "xdotool mousemove $MENU_AT sleep 0.4 click 1"; wait_s 0.8; phase menu "$run"; focus; x "xdotool key Escape"; away; phase off-menu "$run"; done
  for i in $(seq 1 "$TURNS"); do show_bar; x "xdotool mousemove $X_AT sleep 0.4 click 1"; wait_s 0.8; phase question "$run"; focus; x "xdotool key Return"; away; phase off-question "$run"; done
  for i in $(seq 1 "$TURNS"); do echo "Picture quality lowered to keep 60 FPS (Smooth upscale)" > "$SESSION/$(dir_of "$run")/toast.now"; wait_s 0.8; phase toast "$run"; wait_s 2.4; phase off-toast "$run"; done
}
# Every picture choice in turn, Keep and Fill, then the layer's parts at the defaults, for the passes run.
CHOICES=("off 50 off" "smooth 50 off" "fsr1 50 off" "nis 50 off" "anime4k 50 off" "fsr1 50 fxaa" "fsr1 50 smaa-low"
         "fsr1 50 smaa-medium" "fsr1 50 smaa-high" "fsr1 50 smaa-ultra")
passes_turns() {
  local run=$1 d shape c
  d=$(dir_of "$run")
  x "xdotool mousemove $((W / 2)) $((H * 700 / 1080))"; wait_s 1
  for shape in keep fill; do
    for c in "${CHOICES[@]}"; do
      # The choice turned (looked for every tenth frame), the stretch it splits let go, then three whole stretches.
      echo "$c $shape" > "$SESSION/$d/choice.now"
      wait_s 2.5
      phase "$shape:${c// /:}" "$run" 6.2
    done
  done
  # The layer's parts at the defaults, kept: each shown for 6.2 s after it has come.
  echo "fsr1 50 off keep" > "$SESSION/$d/choice.now"
  wait_s 2.5
  phase "parts:none" "$run" 6.2
  fps_menu; phase "parts:chip" "$run" 6.2; fps_menu
  show_bar; phase "parts:bar" "$run" 6.2; away
  show_bar; x "xdotool mousemove $MENU_AT sleep 0.4 click 1"; wait_s 0.8; phase "parts:menu" "$run" 6.2
  focus; x "xdotool key Escape"; away
  show_bar; x "xdotool mousemove $X_AT sleep 0.4 click 1"; wait_s 0.8; phase "parts:question" "$run" 6.2
  focus; x "xdotool key Return"; away
  echo "Picture quality lowered to keep 60 FPS (Smooth upscale)" > "$SESSION/$d/toast.now"; wait_s 0.8
  phase "parts:toast" "$run" 4.2
}
# End the game and every Wine program of the prefix, and wait until none is left.
stop() {
  local run=$1 d
  d=$(dir_of "$1")
  x "import -window root '/out/$d/screen.png'" 2>/dev/null
  x "WINEPREFIX=/w wineserver -k" 2>/dev/null
  local end=$((SECONDS + 30))
  while game_alive && [ $SECONDS -lt $end ]; do wait_s 1; done
  game_alive && echo "  $run: the game did not end" | tee -a "$SESSION/$d/run.txt"
  echo "load at the end: $(cut -d' ' -f1-3 /proc/loadavg)" >> "$SESSION/$d/run.txt"
}

DEFAULTS=(OPENDMT3_LANGUAGE=en OPENDMT3_CURSOR=on OPENDMT3_PACING=music OPENDMT3_FPS=off OPENDMT3_FPS_POSITION=bottom_right
          OPENDMT3_SOUND_DEVICE= OPENDMT3_SAFETY=off)
for run in "${RUNS[@]}"; do
  case "$run" in
    renderer)
      start renderer "Client (openDMT3).exe" on openDMT3 "${DEFAULTS[@]}" OPENDMT3_UPSCALE=fsr1 OPENDMT3_SHARPNESS=50 \
        OPENDMT3_ANTIALIASING=off WINEDEBUG=-all,trace+wgl
      settle renderer
      grep -m1 "GL renderer" "$SESSION/renderer/wine.txt" | sed 's/^.*GL renderer *: */  the game'"'"'s OpenGL renderer: /'
      gpu_proof "$C" 'Client (openDMT3).exe' | tee -a "$SESSION/renderer/run.txt" ;;
    present)
      mkdir -p "$SESSION/present"
      echo "$(date +%T) present: d3d9probe.exe --present $W $H" | tee "$SESSION/present/run.txt"
      echo "load at the start: $(cut -d' ' -f1-3 /proc/loadavg)" >> "$SESSION/present/run.txt"
      x "cd /out && WINEPREFIX=/w WINEDEBUG=-all wine /out/d3d9probe.exe --present $W $H > /out/present/probe.txt 2>&1"
      sed 's/^/  /' "$SESSION/present/probe.txt"
      x "WINEPREFIX=/w wineserver -k" 2>/dev/null
      echo "load at the end: $(cut -d' ' -f1-3 /proc/loadavg)" >> "$SESSION/present/run.txt"
      python3 "$HERE/measure.py" run "$SESSION" present | tee -a "$SESSION/present/run.txt"
      continue ;;
    alone)
      start alone "Client (openDMT3).exe" on original WINEDEBUG=-all,trace+frametime
      settle alone alone && window alone ;;
    alone-free)
      start alone-free "Client (free).exe" off original WINEDEBUG=-all,trace+frametime
      settle alone-free alone && window alone-free ;;
    both-clocks)
      start both-clocks "Client (openDMT3).exe" on openDMT3 "${DEFAULTS[@]}" OPENDMT3_UPSCALE=fsr1 OPENDMT3_SHARPNESS=50 \
        OPENDMT3_ANTIALIASING=off WINEDEBUG=-all,trace+frametime
      settle both-clocks && window both-clocks ;;
    own-steps)
      start own-steps "Client (openDMT3).exe" on openDMT3 "${DEFAULTS[@]/OPENDMT3_PACING=music/OPENDMT3_PACING=game}" \
        OPENDMT3_UPSCALE=off OPENDMT3_SHARPNESS=50 OPENDMT3_ANTIALIASING=off
      settle own-steps && window own-steps ;;
    free)
      start free "Client (openDMT3).exe" off openDMT3 "${DEFAULTS[@]/OPENDMT3_PACING=music/OPENDMT3_PACING=game}" \
        OPENDMT3_UPSCALE=fsr1 OPENDMT3_SHARPNESS=50 OPENDMT3_ANTIALIASING=off OPENDMT3_INGAME_UNLOCK=1
      settle free && window free ;;
    chip)
      start chip "Client (openDMT3).exe" off openDMT3 "${DEFAULTS[@]/OPENDMT3_PACING=music/OPENDMT3_PACING=game}" \
        OPENDMT3_UPSCALE=fsr1 OPENDMT3_SHARPNESS=50 OPENDMT3_ANTIALIASING=off OPENDMT3_INGAME_UNLOCK=1 OPENDMT3_FPS=on
      settle chip && window chip ;;
    pictures:*)
      # With an earlier session given, its game pictures of the same run (Z:\in is it in the container).
      taken=()
      [ -n "${PICTURE_SOURCE:-}" ] && taken=(OPENDMT3_POSTFX_SOURCE="Z:\\in\\$(dir_of "$run")")
      start "$run" "Client (openDMT3).exe" on openDMT3 "${DEFAULTS[@]}" OPENDMT3_UPSCALE=fsr1 OPENDMT3_SHARPNESS=50 \
        OPENDMT3_ANTIALIASING=off OPENDMT3_PICTURE_SHAPE="${run#*:}" OPENDMT3_POSTFX_DUMP_AT="$PICTURE_FRAMES" "${taken[@]}"
      # Each frame named dumped once (dump.done gets a line a frame), within four minutes.
      d=$(dir_of "$run"); wanted=$(echo "$PICTURE_FRAMES" | tr ',' '\n' | grep -c .); end=$((SECONDS + 240))
      until [ "$(cat "$SESSION/$d/dump.done" 2>/dev/null | wc -l)" -ge "$wanted" ] || [ $SECONDS -gt $end ]; do wait_s 1; done
      [ "$(cat "$SESSION/$d/dump.done" 2>/dev/null | wc -l)" -ge "$wanted" ] ;;
    passes)
      start passes "Client (openDMT3).exe" on openDMT3 "${DEFAULTS[@]}" OPENDMT3_UPSCALE=fsr1 OPENDMT3_SHARPNESS=50 \
        OPENDMT3_ANTIALIASING=off OPENDMT3_PASS_TIMES=on
      settle passes && passes_turns passes ;;
    parts-frame | parts-gpu)
      timing=frame
      [ "$run" = parts-gpu ] && timing=on
      start "$run" "Client (openDMT3).exe" on openDMT3 "${DEFAULTS[@]/OPENDMT3_FPS=off/OPENDMT3_FPS=on}" \
        OPENDMT3_UPSCALE=fsr1 OPENDMT3_SHARPNESS=50 OPENDMT3_ANTIALIASING=off OPENDMT3_LAYER_TIMING=$timing
      settle "$run" && turns "$run" ;;
    *:*)
      up=${run%%:*}
      aa=${run#*:}
      start "$run" "Client (openDMT3).exe" on openDMT3 "${DEFAULTS[@]}" OPENDMT3_UPSCALE="$up" OPENDMT3_SHARPNESS=50 \
        OPENDMT3_ANTIALIASING="$aa"
      settle "$run" && window "$run" ;;
    *) echo "  unknown run $run"; continue ;;
  esac
  [ $? = 0 ] || echo "  $run: the game did not reach its settled title screen" | tee -a "$SESSION/$(dir_of "$run")/run.txt"
  stop "$run"
  python3 "$HERE/measure.py" run "$SESSION" "$run" | tee -a "$SESSION/$(dir_of "$run")/run.txt"
done
docker rm -f "$C" >/dev/null
# The clocks' reader told to end, and waited for (it reads twice a second).
touch "$SESSION/.clocks-stop"
[ -n "$CLOCKS" ] && wait "$CLOCKS"
python3 "$HERE/measure.py" table "$SESSION"
