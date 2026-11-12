#!/bin/bash
# The real client against this repository's game server, under Wine with no network:
#   the server on 127.0.0.1:4725 inside the container, the game pointed at it (by the same steps the launcher runs, into
#   openDMT3's own folder), the game started, and the link watched for SECONDS seconds.
# Passes when the server saw exactly one connection go online and stay (the title's NET is green; the
# screenshots show it) with keep-alives answered all along.
#
#   tests/e2e/windows/net_green.sh GAME_DIR OUT_DIR [LINK_SOURCE] [WINE_DLLS] [SECONDS]
#
# GAME_DIR is a test copy of the game folder; its archives may be links into LINK_SOURCE (mounted read-only). It is
# mounted read only: openDMT3's own folder for it is made in the container.
set -u
GAME=$(realpath "${1:?usage: net_green.sh GAME_DIR OUT_DIR [LINK_SOURCE] [WINE_DLLS] [SECONDS]}")
OUT=$(realpath -m "${2:?}")
LINKS=${3:-}
DLLS=${4:-}
RUN=${5:-150}
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
mkdir -p "$OUT"
C=opendmt3-net
docker rm -f "$C" >/dev/null 2>&1
# openDMT3's card reader, built as the release build builds it.
"$REPO/native/cardreader/build.sh" "$OUT/native" >/dev/null || { echo "FAIL: the card reader did not build"; exit 1; }
mounts=(-v "$GAME:/game:ro" -v "$REPO:/src:ro" -v "$OUT:/out" -v "$OUT/native:/native:ro")
[ -n "$LINKS" ] && mounts+=(-v "$LINKS:$LINKS:ro")
[ -n "$DLLS" ] && mounts+=(-v "$(realpath "$DLLS"):/dlls:ro")
docker run --rm --name "$C" --network none -e PYTHONDONTWRITEBYTECODE=1 "${mounts[@]}" opendmt3-wine:local bash -c "
  set -u
  Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp >/dev/null 2>&1 &
  export WINEPREFIX=/w DISPLAY=:99 WINEDLLOVERRIDES='mscoree,mshtml=' WINEDEBUG=-all
  printf 'pcm.!default { type null }\nctl.!default { type hw card 0 }\n' > /etc/asound.conf
  # The loopback interface is all a container without network has; the server listens there.
  ip link set lo up 2>/dev/null
  wineboot -i >/dev/null 2>&1; wineserver -w
  [ -d /dlls ] && cp /dlls/*.dll /w/drive_c/windows/syswow64/
  cd /src
  # Point the game at the server with the launcher's own steps, into openDMT3's own folder (the game folder is only
  # read); the card reader is the one built before the container started.
  OPENDMT3_CARD_READER=/native/CRT_R1.dll python3 -m opendmt3 setup /game --to /own --server 127.0.0.1:4725 \
    > /out/setup.txt 2>&1 || { cat /out/setup.txt; exit 1; }
  # Appending (>>), so the end-of-run mark the shell adds is not written over by the server's next line.
  : > /out/server.log
  # The game server alone (no site: the Wine image has no web libraries), its database in the container.
  # --verbose: the server writes a line for every link it takes only at that level (a link that never comes online
  # is not worth one otherwise), and the check below counts those lines.
  python3 -m opendmt3.server --data /tmp/data --web-port 0 --host 127.0.0.1 --port 4725 --verbose >> /out/server.log 2>&1 &
  cd /game
  wine '/own/Client (openDMT3).exe' > /out/game.log 2>&1 &
  shot() { xwd -root -silent | convert xwd:- png:/out/\$1.png; }
  python3 -c 'import time; time.sleep(40)'; shot net-040s
  python3 -c 'import time; time.sleep($RUN - 40)'; shot net-${RUN}s
  # Closing the game ends the link; mark the moment, so only drops before it count against the run.
  echo \"== end of run\" >> /out/server.log
  wineserver -k
"
connected=$(grep -c " connected$" "$OUT/server.log")
online=$(grep -c " online: client " "$OUT/server.log")
dropped=$(sed '/== end of run/q' "$OUT/server.log" | grep -cE "silent for|disconnected$")
echo "connections: $connected, online: $online, dropped before the end: $dropped (server log: $OUT/server.log)"
grep -E "online: client|no handler" "$OUT/server.log" | head -5
[ "$connected" = 1 ] && [ "$online" = 1 ] && [ "$dropped" = 0 ] && echo "PASS: online for ${RUN}s on one connection" || { echo FAIL; exit 1; }
