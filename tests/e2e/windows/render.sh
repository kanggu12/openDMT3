#!/bin/bash
# The game drawn at the screen's size (native/cardreader/render.c), tried without the game: a 32-bit Direct3D 9 program
# (ingame/render_probe.c) that loads the built CRT_R1.dll as the game does and asks for a 1280x768 back buffer in a
# window over a 1920x1080 virtual screen with OPENDMT3_RENDER=display. It passes when the game would be answered its
# own sizes everywhere it reads one (its back buffer, its render-target texture's level and surface, the viewport, a
# viewport of its own set and read back, a screenshot of its own read into a 1280x768 surface) and the frame it draws,
# dumped by the chain at 1800x1080 (the picture's size there), has each of its parts in the same place of the larger
# frame (ingame/render_probe.py: through its projection, through a copy into its texture and back, and in screen-space
# vertices as its videos are drawn), all of it again after a device reset (as the game makes one when its window turns
# between full screen and a window). The game's own D3DX9_40.dll is put beside the probe, as the game has it, for the
# chain's shaders. Nothing reaches a real screen.
#
#   [OPENDMT3_WINE_GPU=1] tests/e2e/windows/render.sh GAME_PARENT BUILD_DIR OUT_DIR
# GAME_PARENT is a folder holding the client data up to four levels down (only its D3DX9_40.dll is read), BUILD_DIR is
# ./dmt3 build's output (native/CRT_R1.dll) or a folder holding CRT_R1.dll.
set -u
SRC=$(realpath "${1:?usage: render.sh GAME_PARENT BUILD_DIR OUT_DIR}")
BUILD=$(realpath "${2:?}")
OUT=$(realpath -m "${3:?}")
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
. "$HERE/gpu.sh"
DLL="$BUILD/native/CRT_R1.dll"
[ -f "$DLL" ] || DLL="$BUILD/CRT_R1.dll"
[ -f "$DLL" ] || { echo "FAIL: no CRT_R1.dll in $BUILD"; exit 1; }
# The game's own D3DX (the case the client data writes it in, whichever it is), beside the client.
D3DX=$(find "$SRC" -maxdepth 6 -iname "d3dx9_40.dll" | head -1)
[ -n "$D3DX" ] || { echo "FAIL: no D3DX9_40.dll under $SRC"; exit 1; }
rm -rf "$OUT"
mkdir -p "$OUT/probe/out"
# The probe, 32-bit, with the in-game layer's compiler; not executable here (a Windows program is never started from
# this side: WSL would hand it to Windows).
docker run --rm --network none -v "$HERE/ingame:/src:ro" -v "$OUT/probe:/out" opendmt3-mingw:local sh -c \
  'i686-w64-mingw32-gcc -O2 -s -Wall -o /out/render_probe.exe /src/render_probe.c -ld3d9 -luser32 -lgdi32 &&
   chmod 0644 /out/render_probe.exe' || { echo "FAIL: the probe did not build"; exit 1; }
cp "$DLL" "$OUT/probe/CRT_R1.dll"
cp "$D3DX" "$OUT/probe/d3dx9_40.dll"
chmod 0644 "$OUT/probe/CRT_R1.dll" "$OUT/probe/d3dx9_40.dll"
# The layer's faces beside the library, as PLAY puts them.
F="$REPO/opendmt3/client/assets/fonts"
cp "$F/Pretendard-Bold.ttf" "$OUT/probe/openDMT3-Pretendard-Bold.ttf"
cp "$F/Pretendard-Regular.ttf" "$OUT/probe/openDMT3-Pretendard-Regular.ttf"
cp "$F/DMT3Wide-Regular.ttf" "$OUT/probe/openDMT3-DMT3Wide.ttf"
# The container's name: opendmt3-render as the other tests name theirs, or the one OPENDMT3_E2E_NAME gives.
C=$(wine_name "${OPENDMT3_E2E_NAME:-opendmt3-render}")
docker rm -f "$C" >/dev/null 2>&1
# A fresh prefix, the probe over the whole virtual screen, the layer's log and the chain's dump in out/.
docker run --rm --name "$C" --network none --ulimit core=1 "${WINE_RUN_ARGS[@]}" -v "$OUT/probe:/p" \
  "$(wine_image opendmt3-wine:local)" bash -c '
  env -u GALLIUM_DRIVER -u LD_LIBRARY_PATH Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp >/dev/null 2>&1 &
  export WINEPREFIX=/w DISPLAY=:99 WINEDLLOVERRIDES="mscoree,mshtml=" WINEDEBUG=-all
  wineboot -i >/dev/null 2>&1; wineserver -w
  cd /p && OPENDMT3_RENDER=display OPENDMT3_UPSCALE=fsr1 OPENDMT3_INGAME_LOG="Z:\\p\\out\\probe.log" \
    OPENDMT3_POSTFX_DUMP="Z:\\p\\out" wine render_probe.exe > /p/out/probe.txt 2>/dev/null
  echo "exit $?" >> /p/out/probe.txt
  wineserver -k' || true
sed 's/^/  /' "$OUT/probe/out/probe.txt"
# The library's own account of what it turned (the log's render lines).
grep "render:" "$OUT/probe/out/probe.log" 2>/dev/null | cut -d' ' -f2- | sed 's/^/  /'
grep -q "^exit 0" "$OUT/probe/out/probe.txt" || { echo "FAIL: the game would not be answered its own sizes"; exit 1; }
python3 "$HERE/ingame/render_probe.py" "$OUT/probe/out" 1800 1080 ||
  { echo "FAIL: the frame drawn at the screen's size does not have the game's parts in their places"; exit 1; }
echo "PASS: drawn at 1800x1080, the game is answered its own sizes and its parts are in their places, after a reset too"
