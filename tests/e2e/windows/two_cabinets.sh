#!/bin/bash
# Two real clients on one server at once, under Wine on virtual screens, on a network of their own with no way out:
#   a game server in one container with two players, and two "cabinets" in two more, each with its own copy of the
#   game folder and openDMT3's own folder made the way PLAY makes it (the server's address, openDMT3's card reader,
#   the display fix) with its own player's card in the reader's file. Both games start, go online, take TOUCH to START and log their
#   player in by card, then play side by side.
# Passes when the server saw both cabinets come online from their own addresses, logged both players in, and lost
# neither link before the end (HOLD seconds after the second login).
#
#   tests/e2e/windows/two_cabinets.sh GAME_DIR OUT_DIR [LINK_SOURCE] [WINE_DLLS] [HOLD]
#
# GAME_DIR is a test copy of the game folder (the one with the client .exe); it is copied twice into OUT_DIR, links as
# links, and never written itself. Its archives may be links into LINK_SOURCE (mounted read-only). WINE_DLLS holds
# the 32-bit DLLs the game needs that Wine lacks. The card reader is built from native/cardreader first.
set -u
GAME=$(realpath "${1:?usage: two_cabinets.sh GAME_DIR OUT_DIR [LINK_SOURCE] [WINE_DLLS] [HOLD]}")
OUT=$(realpath -m "${2:?}")
LINKS=${3:-}
DLLS=${4:-}
HOLD=${5:-60}
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
NET=opendmt3-pair
SERVER=opendmt3-pair-server
mkdir -p "$OUT"
wait_s() { python3 -c "import time; time.sleep($1)"; }
cleanup() { docker rm -f "$SERVER" opendmt3-pair-a opendmt3-pair-b >/dev/null 2>&1; docker network rm "$NET" >/dev/null 2>&1; }
fail() { echo "FAIL: $*"; docker logs "$SERVER" > "$OUT/server-container.log" 2>&1; cleanup; exit 1; }
cleanup
# The card reader the launcher puts in, built as the release build builds it.
"$REPO/native/cardreader/build.sh" "$OUT/native" >/dev/null || { echo "FAIL: the card reader did not build"; exit 1; }
for cab in a b; do
  cp -a "$GAME" "$OUT/game-$cab"
done
# --internal: the three reach each other and nothing else.
docker network create --internal "$NET" >/dev/null || fail "no network"
links=()
[ -n "$LINKS" ] && links=(-v "$LINKS:$LINKS:ro")

# ---- the server, with two players
mkdir -p "$OUT/data" && chmod 777 "$OUT/data"
docker run -d --name "$SERVER" --network "$NET" -e PYTHONDONTWRITEBYTECODE=1 -v "$REPO:/src:ro" -v "$OUT:/out" \
  opendmt3-wine:local bash -c "
    cd /src
    for p in A B; do python3 -m opendmt3.server --data /out/data --add-player \$p --password pass1234 --dj \"DJ \$p\" >/dev/null; done
    python3 -c 'from opendmt3.server import db
c = db.connect(\"/out/data/openDMT3.sqlite\")
for login_id, card in c.execute(\"SELECT login_id, card FROM accounts ORDER BY login_id\"):
    open(\"/out/card-%s.txt\" % login_id.lower(), \"w\").write(card)'
    : > /out/server.log
    # --verbose: a line for every link the server takes (the count below reads them).
    python3 -m opendmt3.server --data /out/data --web-port 0 --host 0.0.0.0 --port 4725 --verbose >> /out/server.log 2>&1
  " >/dev/null || fail "the server did not start"
end=$((SECONDS + 60)); until grep -q "game server listening" "$OUT/server.log" 2>/dev/null || [ $SECONDS -gt $end ]; do wait_s 1; done
grep -q "game server listening" "$OUT/server.log" || fail "the server is not listening"
IP=$(docker inspect -f "{{(index .NetworkSettings.Networks \"$NET\").IPAddress}}" "$SERVER")
echo "== server at $IP:4725, players A and B"

# ---- two cabinets: each sets its copy up as PLAY does, puts its player's card in, and starts the game
for cab in a b; do
  mounts=(-v "$OUT/game-$cab:/game" -v "$REPO:/src:ro" -v "$OUT:/out" -v "$OUT/native:/native:ro" "${links[@]}")
  [ -n "$DLLS" ] && mounts+=(-v "$(realpath "$DLLS"):/dlls:ro")
  docker run -d --name "opendmt3-pair-$cab" --network "$NET" -e PYTHONDONTWRITEBYTECODE=1 \
    -e OPENDMT3_CARD_READER=/native/CRT_R1.dll "${mounts[@]}" opendmt3-wine:local bash -c "
      Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp >/dev/null 2>&1 &
      export WINEPREFIX=/w DISPLAY=:99 WINEDLLOVERRIDES='mscoree,mshtml=' WINEDEBUG=-all
      printf 'pcm.!default { type null }\nctl.!default { type hw card 0 }\n' > /etc/asound.conf
      wineboot -i >/dev/null 2>&1; wineserver -w
      [ -d /dlls ] && cp /dlls/*.dll /w/drive_c/windows/syswow64/
      cd /src
      # The steps PLAY runs, with this server's address and openDMT3's card reader, into openDMT3's own folder.
      python3 -c 'import sys
from opendmt3.core import game as g
from opendmt3.core.cabinet import steps
game = g.Game.find(\"/game\")
steps.prepare(game, steps.Own(\"/own\"), steps.Options(server=sys.argv[1], card_reader=True))
print(game.root)' $IP:4725 > /out/setup-$cab.txt 2>&1 || exit 1
      root=\$(tail -1 /out/setup-$cab.txt)
      # This cabinet's player's card, as the launcher writes it at PLAY: beside the card reader.
      { cat /out/card-$cab.txt; echo; } > /own/openDMT3-card.txt
      cd \"\$root\" && wine '/own/Client (openDMT3).exe' > /out/game-$cab.log 2>&1 &
      sleep infinity
    " >/dev/null || fail "cabinet $cab did not start"
done
online() { grep -c " online: client " "$OUT/server.log"; }
end=$((SECONDS + 300)); until [ "$(online)" -ge 2 ] || [ $SECONDS -gt $end ]; do wait_s 2; done
[ "$(online)" -ge 2 ] || fail "only $(online) of the two cabinets came online (see $OUT/setup-a.txt, setup-b.txt)"
echo "== both online; TOUCH to START on each"
wait_s 15
for cab in a b; do
  docker exec -e DISPLAY=:99 "opendmt3-pair-$cab" sh -c "xwd -root -silent | convert xwd:- png:/out/$cab-1-title.png"
  # The game draws 1280x768 stretched over 1920x1080: TOUCH to START is at (640, 590) of its picture.
  docker exec -e DISPLAY=:99 "opendmt3-pair-$cab" xdotool mousemove 960 830 mousedown 1 sleep 0.15 mouseup 1
done
end=$((SECONDS + 120))
until { grep -q "logged in: A " "$OUT/server.log" && grep -q "logged in: B " "$OUT/server.log"; } || [ $SECONDS -gt $end ]; do wait_s 2; done
grep -q "logged in: A " "$OUT/server.log" || fail "player A was not logged in by card"
grep -q "logged in: B " "$OUT/server.log" || fail "player B was not logged in by card"
echo "== both logged in; holding ${HOLD}s"
wait_s "$HOLD"
for cab in a b; do
  docker exec -e DISPLAY=:99 "opendmt3-pair-$cab" sh -c "xwd -root -silent | convert xwd:- png:/out/$cab-2-after.png"
done
echo "== end of run" >> "$OUT/server.log"
addresses=$(grep " online: client " "$OUT/server.log" | sed -E 's/.* ([0-9.]+):[0-9]+ online: client.*/\1/' | sort -u | wc -l)
dropped=$(sed '/== end of run/q' "$OUT/server.log" | grep -cE "silent for|disconnected$")
grep -E "online: client|logged in" "$OUT/server.log" | sed 's/^/  /'
echo "  online from $addresses addresses, dropped before the end: $dropped"
cleanup
[ "$addresses" = 2 ] || { echo "FAIL: the two cabinets did not come online from two addresses"; exit 1; }
[ "$dropped" = 0 ] || { echo "FAIL: a link dropped while both played"; exit 1; }
echo "PASS: two cabinets online from their own addresses, players A and B logged in by card, both still online ${HOLD}s later"
