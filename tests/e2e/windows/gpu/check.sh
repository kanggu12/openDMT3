#!/bin/bash
# What the GPU image draws with, proved, before a game is run on it: a 32-bit Direct3D 9 program (d3d9probe.c, built
# as the game is built: 32-bit, MinGW) under the GPU image with WSL's GPU, under the same image without it (Mesa's
# llvmpipe, 64-bit) and under the CPU image the tests use by default (classic Wine: 32-bit llvmpipe). Each says its
# OpenGL renderer and draws a known picture; compare.py passes when the GPU's renderer names D3D12, every run drew
# the picture right, the GPU's frame is llvmpipe's, and each screen shows what was drawn. glxinfo's summary of the
# GPU image's OpenGL is kept beside them. Nothing reaches a real screen: every window is on a container's virtual one.
#
#   tests/e2e/windows/gpu/check.sh OUT_DIR
set -u
OUT=$(realpath -m "${1:?usage: check.sh OUT_DIR}")
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$OUT"
# WSL's GPU and the GPU image (built the first time).
OPENDMT3_WINE_GPU=1
. "$HERE/../gpu.sh"
# The probe, 32-bit, with the in-game layer's compiler (its image made as native/cardreader/build.sh makes it).
docker image inspect opendmt3-mingw:local >/dev/null 2>&1 || {
  ctx=$(mktemp -d)
  printf 'FROM debian:12\nRUN apt-get update && apt-get install -y --no-install-recommends gcc-mingw-w64-i686 && rm -rf /var/lib/apt/lists/*\n' > "$ctx/Dockerfile"
  docker build -q -t opendmt3-mingw:local "$ctx" >/dev/null
  rm -rf "$ctx"
}
# Not executable: a Windows program is never started from here (WSL would hand it to Windows).
docker run --rm --network none -v "$HERE:/src:ro" -v "$OUT:/out" opendmt3-mingw:local sh -c \
  'i686-w64-mingw32-gcc -O2 -s -Wall -o /out/d3d9probe.exe /src/d3d9probe.c -ld3d9 -lopengl32 -lgdi32 -luser32 && chmod 0644 /out/d3d9probe.exe' \
  || { echo "FAIL: the probe did not build"; exit 1; }
# probe NAME IMAGE [docker run arguments]: a fresh prefix, the probe drawing its picture in a 256 x 256 window at the
# screen's top left, the screen's copy of that window taken while it waits, its lines and exit code in NAME.txt.
probe() {
  local name=$1 image=$2
  shift 2
  local c=odt3-gpu-check-$name
  docker rm -f "$c" >/dev/null 2>&1
  rm -f "$OUT/$name.txt" "$OUT/$name.bmp" "$OUT/$name-screen.bmp"
  # No core dumps from any of the three (gpu.sh says why).
  docker run --rm --name "$c" --network none --ulimit core=1 "$@" -v "$OUT:/out" "$image" bash -c '
    env -u GALLIUM_DRIVER -u LD_LIBRARY_PATH Xvfb :99 -screen 0 1024x768x24 -nolisten tcp >/dev/null 2>&1 &
    export WINEPREFIX=/w DISPLAY=:99 WINEDLLOVERRIDES="mscoree,mshtml=" WINEDEBUG=-all
    # glxinfo where the image has it (the GPU image): what Mesa gives this container.
    sleep 1; command -v glxinfo >/dev/null && glxinfo -B > "/out/$0-glxinfo.txt" 2>&1
    wineboot -i >/dev/null 2>&1; wineserver -w
    # The probe waits 5 s after its last frame; the screen is read in that time.
    wine /out/d3d9probe.exe "Z:\\out\\$0.bmp" 5000 > "/out/$0.txt" 2>&1 &
    probe=$!
    for i in $(seq 1 120); do grep -q "^timing: 500" "/out/$0.txt" 2>/dev/null && break; sleep 0.5; done
    sleep 1
    import -window root -crop 256x256+0+0 +repage -type TrueColor "bmp3:/out/$0-screen.bmp"
    wait $probe
    echo "exit $?" >> "/out/$0.txt"
    wineserver -k' "$name"
  echo "== $name ($image)"
  sed 's/^/  /' "$OUT/$name.txt"
}
probe gpu "$WINE_GPU_IMAGE" "${WINE_RUN_ARGS[@]}"
probe wow64-cpu "$WINE_GPU_IMAGE"
probe cpu opendmt3-wine:local
echo "== glxinfo in the GPU image with WSL's GPU"
grep -E "OpenGL (vendor|renderer|core profile version|version) string|Accelerated" "$OUT/gpu-glxinfo.txt" | sed 's/^ */  /'
echo "== the three side by side"
python3 "$HERE/compare.py" "$OUT" gpu wow64-cpu cpu && echo "PASS: the GPU image draws a 32-bit Direct3D 9 program on the graphics card through D3D12, the picture as llvmpipe draws it"
