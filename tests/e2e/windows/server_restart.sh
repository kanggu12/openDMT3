#!/bin/bash
# The real client through a restart of this repository's game server, under Wine with no network: the game goes
# online, the server is stopped and started again on the same database DOWN_SECONDS later, and the game must come
# back online by itself on a new connection and stay, as a cabinet does when its server restarts.
#
#   tests/e2e/windows/server_restart.sh GAME_DIR OUT_DIR [LINK_SOURCE] [WINE_DLLS] [DOWN_SECONDS]
#
# GAME_DIR is a test copy of the game folder; its archives may be links into LINK_SOURCE (mounted read-only). It is
# mounted read only: openDMT3's own folder for it is made in the container. WINE_DLLS as for net_green.sh.
set -u
GAME=$(realpath "${1:?usage: server_restart.sh GAME_DIR OUT_DIR [LINK_SOURCE] [WINE_DLLS] [DOWN_SECONDS]}")
OUT=$(realpath -m "${2:?}")
LINKS=${3:-}
DLLS=${4:-}
DOWN=${5:-15}
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
mkdir -p "$OUT"
C=opendmt3-restart
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
  # The repository's code from any folder (the game runs from its own).
  export PYTHONPATH=/src
  cd /src
  # Point the game at the server with the launcher's own steps, into openDMT3's own folder (the game folder is only
  # read); the card reader is the one built before the container started.
  OPENDMT3_CARD_READER=/native/CRT_R1.dll python3 -m opendmt3 setup /game --to /own --server 127.0.0.1:4725 \
    > /out/setup.txt 2>&1 || { cat /out/setup.txt; exit 1; }
  : > /out/server.log
  serve() { python3 -m opendmt3.server --data /tmp/data --web-port 0 --host 127.0.0.1 --port 4725 >> /out/server.log 2>&1 & }
  wait_s() { python3 -c \"import time; time.sleep(\$1)\"; }
  shot() { xwd -root -silent | convert xwd:- png:/out/\$1.png; }
  serve
  server=\$!
  cd /game
  wine '/own/Client (openDMT3).exe' > /out/game.log 2>&1 &
  # Online first (the title's NET green), then a while of keep-alives.
  for i in \$(seq 120); do grep -q ' online: client ' /out/server.log && break; wait_s 1; done
  wait_s 20; shot 1-online
  echo \"== server stopped \$(date +%s)\" >> /out/server.log
  kill \$server; wait \$server
  wait_s $DOWN; shot 2-server-down
  echo \"== server started again \$(date +%s)\" >> /out/server.log
  serve
  for i in \$(seq 180); do sed -n '/== server started again/,\$p' /out/server.log | grep -q ' online: client ' && break; wait_s 1; done
  echo \"== back online by \$(date +%s)\" >> /out/server.log
  # Staying online after coming back: a few keep-alive rounds.
  wait_s 40; shot 3-back-online
  echo '== end of run' >> /out/server.log
  wineserver -k
"
LOG="$OUT/server.log"
before=$(sed '/== server stopped/q' "$LOG" | grep -c " online: client ")
after=$(sed -n '/== server started again/,/== end of run/p' "$LOG" | grep -c " online: client ")
dropped=$(sed -n '/== server started again/,/== end of run/p' "$LOG" | grep -cE "silent for|disconnected$")
started=$(sed -n 's/^== server started again \([0-9]*\)$/\1/p' "$LOG")
back=$(sed -n 's/^== back online by \([0-9]*\)$/\1/p' "$LOG")
if [ "$after" = 0 ]; then took="never, in $((back - started)) s"; else took="$((back - started)) s after the start"; fi
echo "online before the restart: $before, after it: $after, dropped after it: $dropped, back online: $took (server log: $LOG)"
[ "$before" = 1 ] && [ "$after" = 1 ] && [ "$dropped" = 0 ] \
  && echo "PASS: back online by itself $((back - started)) s after the server started again, down for ${DOWN}s" || { echo FAIL; exit 1; }
