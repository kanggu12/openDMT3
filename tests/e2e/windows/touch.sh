#!/bin/bash
# openDMT3's touch screen library (native/cardreader/multidll.c) with the card reader library's touch screen behind it
# (touch.c, contacts.c), tried without the game: a 32-bit program (ingame/touch_probe.c) loads the built CRT_R1.dll and
# multiDLL.dll as the game's imports do and calls the stand-in as the game does, with contacts made up by
# OPENDMT3_TOUCH_INJECT (a touch screen cannot be made under Wine). It passes when the stand-in has exactly the three
# names the client imports at the original's numbers; it opens beside openDMT3's library, and the game would read a
# finger as a press at its place, a second while the first holds as a new finger, the second let go with the first
# still held, a release, and a finger down in the read another came up in as a press; it fails to open with OPENDMT3_MULTI_TOUCH=off and without openDMT3's library beside it
# (the game then plays the mouse as before); and the layer's log says the open and the made-up steps. Nothing reaches a
# real screen.
#
#   tests/e2e/windows/touch.sh BUILD_DIR OUT_DIR
# BUILD_DIR is ./dmt3 build's output (native/CRT_R1.dll and native/multiDLL.dll) or a folder holding both.
set -u
BUILD=$(realpath "${1:?usage: touch.sh BUILD_DIR OUT_DIR}")
OUT=$(realpath -m "${2:?}")
HERE=$(cd "$(dirname "$0")" && pwd)
LIBS="$BUILD/native"
[ -f "$LIBS/CRT_R1.dll" ] || LIBS="$BUILD"
for need in CRT_R1.dll multiDLL.dll; do
  [ -f "$LIBS/$need" ] || { echo "FAIL: no $need in $BUILD"; exit 1; }
done
rm -rf "$OUT"
mkdir -p "$OUT/probe/out"
# The probe, 32-bit, with the in-game layer's compiler (its image made as native/cardreader/build.sh makes it); not
# executable here (a Windows program is never started from this side: WSL would hand it to Windows).
docker image inspect opendmt3-mingw:local >/dev/null 2>&1 || "$HERE/../../../native/cardreader/build.sh" "$OUT/build" >/dev/null
docker run --rm --network none -v "$HERE/ingame:/src:ro" -v "$OUT/probe:/out" opendmt3-mingw:local sh -c \
  'i686-w64-mingw32-gcc -O2 -s -Wall -o /out/touch_probe.exe /src/touch_probe.c &&
   chmod 0644 /out/touch_probe.exe' || { echo "FAIL: the probe did not build"; exit 1; }
cp "$LIBS/CRT_R1.dll" "$LIBS/multiDLL.dll" "$OUT/probe/"
chmod 0644 "$OUT/probe/CRT_R1.dll" "$OUT/probe/multiDLL.dll"
# The stand-in alone in a folder of its own: no card reader library of openDMT3's beside it.
mkdir -p "$OUT/probe/alone"
cp "$LIBS/multiDLL.dll" "$OUT/probe/alone/"
cp "$OUT/probe/touch_probe.exe" "$OUT/probe/alone/"
# The container's name: opendmt3-touch as the other tests name theirs, or the one OPENDMT3_E2E_NAME gives.
C="${OPENDMT3_E2E_NAME:-opendmt3-touch}"
docker rm -f "$C" >/dev/null 2>&1
# A fresh prefix and a virtual screen (the layer's library loads user32's parts), the three runs, their lines and the
# layer's log in out/.
docker run --rm --name "$C" --network none --ulimit core=1 -v "$OUT/probe:/p" opendmt3-wine:local bash -c '
  Xvfb :99 -screen 0 1280x768x24 -nolisten tcp >/dev/null 2>&1 &
  export WINEPREFIX=/w DISPLAY=:99 WINEDLLOVERRIDES="mscoree,mshtml=" WINEDEBUG=-all
  wineboot -i >/dev/null 2>&1; wineserver -w
  cd /p && OPENDMT3_TOUCH_INJECT="2:100,600;3:100,600+1180,600;4:100,600;5:-;7:300,600;8:_+340,600;9:-" \
    OPENDMT3_INGAME_LOG="Z:\\p\\out\\probe.log" wine touch_probe.exe > /p/out/probe.txt 2>/dev/null
  echo "exit $?" >> /p/out/probe.txt
  OPENDMT3_MULTI_TOUCH=off wine touch_probe.exe off > /p/out/off.txt 2>/dev/null
  echo "exit $?" >> /p/out/off.txt
  cd /p/alone && wine touch_probe.exe alone > /p/out/alone.txt 2>/dev/null
  echo "exit $?" >> /p/out/alone.txt
  wineserver -k' || true
for run in probe off alone; do
  sed 's/^/  /' "$OUT/probe/out/$run.txt" 2>/dev/null
  grep -q "^exit 0" "$OUT/probe/out/$run.txt" 2>/dev/null || { echo "FAIL: the stand-in ($run) did not answer as the game needs"; exit 1; }
done
# The layer's own account: the open and the made-up steps.
grep "touch:" "$OUT/probe/out/probe.log" 2>/dev/null | cut -d' ' -f2- | sed 's/^/  /'
grep -q "touch: the game opened the touch screen" "$OUT/probe/out/probe.log" 2>/dev/null &&
  grep -q "touch: 7 made-up steps" "$OUT/probe/out/probe.log" ||
  { echo "FAIL: the layer's log does not say the open and the made-up steps"; exit 1; }
echo "PASS: the stand-in opens beside openDMT3's library, and the game would read each finger, a second one and a release"
