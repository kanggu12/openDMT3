#!/bin/bash
# A song's frames and its input latency on either renderer (OPENDMT3_WINE_GPU=1 for this PC's GPU, gpu.sh), with a
# sound clock that runs in real time (gpu/sound/Dockerfile), so the music lock paces the song at 60 a second as a sound
# card does. The real client starts afresh as a guest on a virtual screen with no network: its title is clicked 40 s
# after the in-game layer is attached, the guest's tutorial plays, then a song; from 20 s into the song, PRESSES
# presses (80 by default, none after the song stops) at the screen's bottom left about 1.2 s apart, each timed by the
# layer from the press's own message time to its frame done on the GPU (OPENDMT3_LATENCY_WATCH); every frame's length
# (OPENDMT3_INGAME_FRAMES); the result screen 12 s after the song's music stops. song.py turns the run into its
# numbers (OUT_DIR/results.json). The song is the second play of the game's 40 MB music buffer (the tutorial's is the
# first). Nothing reaches a real screen or a speaker.
#
#   [OPENDMT3_WINE_GPU=1] [SCREEN=1920x1080] [PRESSES=80] [OPENDMT3_E2E_NAME=odt3-gpu-song]
#     tests/e2e/windows/gpu/song.sh GAME_PARENT BUILD_DIR OUT_DIR [LINK_SOURCE] [WINE_DLLS] [VAR=VALUE...]
#
# GAME_PARENT, LINK_SOURCE and WINE_DLLS are measure.sh's; BUILD_DIR is ./dmt3 build's output, whose
# native/CRT_R1.dll is the layer (a folder holding CRT_R1.dll itself is taken too), with the touch screen's library
# beside it when the build has one (multiDLL.dll, put in the copy as PLAY puts it). Each VAR=VALUE is passed to the
# game on top of the layer's defaults as a player has them (locked to the music, FSR 1 at 50, no anti-aliasing, the
# safety net off so the picture stays as chosen): OPENDMT3_JIT=off, say, to compare.
set -u
SRC=$(realpath "${1:?usage: song.sh GAME_PARENT BUILD_DIR OUT_DIR [LINK_SOURCE] [WINE_DLLS] [VAR=VALUE...]}")
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
SCREEN=${SCREEN:-1920x1080}
W=${SCREEN%x*}
H=${SCREEN#*x}
DLL=$BUILD/native/CRT_R1.dll
[ -f "$DLL" ] || DLL=$BUILD/CRT_R1.dll
[ -f "$DLL" ] || { echo "FAIL: no native/CRT_R1.dll in $BUILD (./dmt3 build's output)"; exit 1; }
wait_s() { python3 -c "import time; time.sleep($1)"; }
now_ms() { python3 -c 'import time; print(int(time.monotonic() * 1000))'; }
# The image with the sound server on top of the renderer's, made the first time.
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  docker build -q --build-arg BASE="$BASE" -t "$IMAGE" "$HERE/sound" >/dev/null \
    || { echo "FAIL: $IMAGE did not build"; exit 1; }
fi

# ---- the game's copy: openDMT3's DLL in it, as a guest, the layer's faces beside it as PLAY puts them
rm -rf "$OUT"
mkdir -p "$OUT/game"
cp -a "$SRC/." "$OUT/game/"
CLIENT=$(find "$OUT/game" -maxdepth 6 -name "Client (openDMT3).exe" | head -1)
[ -n "$CLIENT" ] || { echo "FAIL: no Client (openDMT3).exe under $SRC"; exit 1; }
DMT3=$(dirname "$CLIENT")
REL_DMT3=${DMT3#"$OUT/game/"}
rm -f "$DMT3/openDMT3-card.txt" "$DMT3/openDMT3-picture.txt"
cp "$DLL" "$DMT3/CRT_R1.dll"
# openDMT3's touch screen library in place of the client data's, as PLAY puts it, when the build has it (the game then
# reads the mouse through it, and OPENDMT3_TOUCH_INJECT's made-up fingers).
TOUCH=$(dirname "$DLL")/multiDLL.dll
if [ -f "$TOUCH" ]; then
  find "$DMT3" -maxdepth 1 -iname "multidll.dll" -delete
  cp "$TOUCH" "$DMT3/multiDLL.dll"
fi
F="$REPO/opendmt3/client/assets/fonts"
cp "$F/Pretendard-Bold.ttf" "$DMT3/openDMT3-Pretendard-Bold.ttf"
cp "$F/Pretendard-Regular.ttf" "$DMT3/openDMT3-Pretendard-Regular.ttf"
cp "$F/DMT3Wide-Regular.ttf" "$DMT3/openDMT3-DMT3Wide.ttf"
# Not executable: a Windows program is never started from here (WSL would hand it to Windows). Links are left as they
# are (-type f): they point into the folder LINK_SOURCE names, which is only read.
find "$OUT/game" -type f -iname "*.exe" -exec chmod 0644 {} +

# ---- the container: the virtual screen, a fresh prefix, the sound server with its null sink as the default
C=${OPENDMT3_E2E_NAME:-odt3-gpu-song}-$RENDERER-$$
mounts=(-v "$OUT/game:/root/Desktop/game" -v "$OUT:/out")
[ -n "$LINKS" ] && mounts+=(-v "$LINKS:$LINKS:ro")
[ -n "$DLLS" ] && mounts+=(-v "$(realpath "$DLLS"):/dlls:ro")
# The layer's choices as a player has them, the measuring ones, then the caller's.
envs=(-e OPENDMT3_LANGUAGE=en -e OPENDMT3_CURSOR=on -e OPENDMT3_PACING=music -e OPENDMT3_FPS=off
      -e OPENDMT3_UPSCALE=fsr1 -e OPENDMT3_SHARPNESS=50 -e OPENDMT3_ANTIALIASING=off -e OPENDMT3_SAFETY=off
      -e OPENDMT3_LATENCY_WATCH=1 -e OPENDMT3_SOUND_WATCH=1 -e 'OPENDMT3_INGAME_FRAMES=Z:\out\frames.txt')
for e in "$@"; do envs+=(-e "$e"); done
echo "$(date +%T) song on the $RENDERER: $DLL, ${*:-the defaults}; load $(cut -d' ' -f1-3 /proc/loadavg)" \
  > "$OUT/run.txt"
docker run -d --name "$C" --network none --ulimit core=1 -e SCREEN="$SCREEN" -e REL_DMT3="$REL_DMT3" \
  "${WINE_RUN_ARGS[@]}" "${mounts[@]}" "${envs[@]}" "$IMAGE" bash -c '
  env -u GALLIUM_DRIVER -u LD_LIBRARY_PATH Xvfb :99 -screen 0 ${SCREEN}x24 -nolisten tcp >/dev/null 2>&1 &
  export WINEPREFIX=/w DISPLAY=:99 WINEDLLOVERRIDES="mscoree,mshtml=" WINEDEBUG=-all XDG_RUNTIME_DIR=/tmp/xdg
  mkdir -p /tmp/xdg && chmod 700 /tmp/xdg
  # ALSA to the sound server (for a Wine with no PulseAudio driver of its own), whose null sink plays in real time.
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
# The container's CPU time (its cgroup's), read at the song's start and stop: the game and the layer's whole cost.
cgroup=$(find /sys/fs/cgroup -maxdepth 3 -type d -name "*$(docker inspect -f '{{.Id}}' "$C")*" 2>/dev/null | head -1)
cpu_usec() { awk '/^usage_usec/ {print $2}' "$cgroup/cpu.stat" 2>/dev/null || echo 0; }
end=$((SECONDS + 300))
until grep -q "layer: attached" "$L" 2>/dev/null || [ $SECONDS -gt $end ]; do wait_s 2; done
grep -q "layer: attached" "$L" 2>/dev/null \
  || { echo "FAIL: the layer never attached"; docker rm -f "$C" >/dev/null; exit 1; }
wait_s 40
# On the GPU: the game's own process draws through WSL's D3D12, or the run fails.
proof=$(gpu_proof "$C" 'Client (openDMT3).exe')
drawn=$?
echo "$proof" | tee -a "$OUT/run.txt"
[ $drawn = 0 ] || { docker rm -f "$C" >/dev/null; exit 1; }
x "import -window root /out/title.png"
x "xdotool mousemove $((W / 2)) $((H * 830 / 1080)) mousedown 1 sleep 0.15 mouseup 1"
# The song: the second play of the 40 MB buffer, within 20 minutes of the title's click.
end=$((SECONDS + 1200))
until [ "$(grep -c '(41943040 bytes' "$L")" -ge 2 ] || [ $SECONDS -gt $end ]; do wait_s 1; done
song=$(grep '(41943040 bytes' "$L" | sed -n 2p | cut -d' ' -f4)
[ -n "$song" ] || { echo "FAIL: no song played within 20 minutes"; docker rm -f "$C" >/dev/null; exit 1; }
# The song's own stop: one more stop line of its stream than at its start (the tutorial's play of the same buffer, the
# same stream, has stopped by then).
stops=$(grep -c "stream $song stops at" "$L")
stopped() { [ "$(grep -c "stream $song stops at" "$L")" -gt "$stops" ]; }
echo "song stream $song; cpu_usec at its start $(cpu_usec) at $(now_ms) ms" >> "$OUT/run.txt"
wait_s 20
for i in $(seq 1 "${PRESSES:-80}"); do
  # No press after the song: the result screen is no part of it.
  stopped && break
  # A press in the bottom left corner, where the song has no note to hit; 1.0 to 1.3 s apart, so the presses fall at
  # every point of a frame.
  x "xdotool mousemove 60 $((H - 60)) mousedown 1 sleep 0.08 mouseup 1"
  wait_s "1.$((RANDOM % 4))"
done
# The song's stop (its CPU time read then), within 20 minutes of the title's click as before.
until stopped || [ $SECONDS -gt $end ]; do wait_s 1; done
stopped || { echo "FAIL: the song did not stop within 20 minutes"; docker rm -f "$C" >/dev/null; exit 1; }
echo "cpu_usec at the song's stop $(cpu_usec) at $(now_ms) ms; load $(cut -d' ' -f1-3 /proc/loadavg)" >> "$OUT/run.txt"
wait_s 12
x "import -window root /out/result-screen.png"
docker rm -f "$C" >/dev/null
python3 "$HERE/song.py" "$OUT" | tee -a "$OUT/run.txt"
