#!/bin/bash
# The whole openDMT3 path on two machines and a closed network (no way out to the internet):
#   a server in Docker (game and site, the song list read from a game folder, the installer to hand out), and a
#   Windows PC (Wine on a virtual screen) whose player signs in on the server's site, downloads the launcher from
#   it, installs it, connects to that server in the guide, signs in with the ID the owner made, and presses PLAY;
#   the game then logs in on that server with the player's card. Passes when the server logs that login.
#
#   tests/e2e/windows/remote_play.sh GAME_PARENT RELEASES_DIR OUT_DIR [LINK_SOURCE] [WINE_DLLS]
#
# GAME_PARENT is a folder with a test copy of the game folder inside it (up to four levels down); the copy's
# archives may be links into LINK_SOURCE (read-only).
set -u
PARENT=$(realpath "${1:?usage: remote_play.sh GAME_PARENT RELEASES_DIR OUT_DIR [LINK_SOURCE] [WINE_DLLS]}")
REL=$(realpath "${2:?}")
OUT=$(realpath -m "${3:?}")
LINKS=${4:-}
DLLS=${5:-}
NAME=$(basename "$PARENT")
NET=odt3-e2e-net
SRV=odt3-e2e-server
PC=odt3-e2e-pc
mkdir -p "$OUT"
cleanup() { docker rm -f "$SRV" "$PC" >/dev/null 2>&1; docker network rm "$NET" >/dev/null 2>&1; }
cleanup
# --internal: the two can reach each other and nothing else.
docker network create --internal "$NET" >/dev/null
links=()
[ -n "$LINKS" ] && links=(-v "$LINKS:$LINKS:ro")

echo "== server"
# The server image from this source tree on every run (Docker's cache keeps an unchanged tree quick): an image built
# for an earlier test would pass this one on an older server. It must be the version of the launcher under test.
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
docker build -q -f "$REPO/packaging/docker/Dockerfile" -t opendmt3-server:local "$REPO" >/dev/null \
  || { echo "FAIL: the server image did not build"; cleanup; exit 1; }
WANT=$(ls "$REL"/openDMT3-*-full.nupkg 2>/dev/null | sed -n 's/.*openDMT3-\(.*\)-full\.nupkg$/\1/p' | head -1)
GOT=$(docker run --rm --network none --entrypoint python opendmt3-server:local -c "import opendmt3; print(opendmt3.__version__)")
[ -n "$WANT" ] && [ "$GOT" = "$WANT" ] \
  || { echo "FAIL: the server image is ${GOT:-?}, the launcher under test ${WANT:-?}"; cleanup; exit 1; }
echo "server and launcher: $GOT"
DATA="$OUT/server-data"
rm -rf "$DATA" && mkdir -p "$DATA/downloads" && chmod -R 777 "$DATA"
# The song list from the owner's game folder, the owner's account and a player's, as the owner would make them.
# The song list as root: the test copy's archives are links into a folder the image's own user cannot read.
# Only the list is made here (one file); the database is made by the server's own user below, so it can write it.
docker run --rm --network none --user 0 -v "$DATA:/data" -v "$PARENT:/game:ro" "${links[@]}" opendmt3-server:local \
  --catalog /game --setup-only
chmod -R a+rwX "$DATA"
docker run --rm --network none -v "$DATA:/data" opendmt3-server:local --add-player BOSS --password pass1234 --dj BOSS --admin
docker run --rm --network none -v "$DATA:/data" opendmt3-server:local --add-player NOVA --password pass1234 --dj "DJ NOVA"
[ -f "$DATA/catalog.json" ] || { echo "FAIL: no song list"; cleanup; exit 1; }
cp "$REL/openDMT3-win-Setup.exe" "$DATA/downloads/"
docker run -d --name "$SRV" --network "$NET" --network-alias dmt-server -v "$DATA:/data" opendmt3-server:local >/dev/null

echo "== PC"
mounts=(-v "$PARENT:/root/Desktop/$NAME" -v "$OUT:/out" "${links[@]}")
[ -n "$DLLS" ] && mounts+=(-v "$(realpath "$DLLS"):/dlls:ro")
docker run -d --name "$PC" --network "$NET" "${mounts[@]}" opendmt3-wine:local bash -c '
  Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp >/dev/null 2>&1 &
  export WINEPREFIX=/w DISPLAY=:99 WINEDLLOVERRIDES="mscoree,mshtml=" WINEDEBUG=-all
  printf "pcm.!default { type null }\nctl.!default { type hw card 0 }\n" > /etc/asound.conf
  wineboot -i >/dev/null 2>&1; wineserver -w
  [ -d /dlls ] && cp /dlls/*.dll /w/drive_c/windows/syswow64/
  # The player signs in on the server s site and downloads the launcher from its Download page.
  python3 - <<EOF
import http.cookiejar, time, urllib.parse, urllib.request
jar = http.cookiejar.CookieJar()
web = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
for _ in range(60):
    try:
        web.open("http://dmt-server:4730/health", timeout=3); break
    except OSError:
        time.sleep(1)
# The sign-in form carries a token from its page (and a cookie the jar keeps): the page first, as a browser does.
page = web.open("http://dmt-server:4730/signin", timeout=10).read().decode()
token = page.split("name=" + chr(34) + "csrf" + chr(34) + " value=" + chr(34), 1)[1].split(chr(34), 1)[0]
web.open("http://dmt-server:4730/signin", urllib.parse.urlencode({"csrf": token, "login_id": "NOVA", "password": "pass1234"}).encode(), timeout=10)
data = web.open("http://dmt-server:4730/download/windows", timeout=60).read()
open("/tmp/openDMT3-win-Setup.exe", "wb").write(data)
print("downloaded", len(data), "bytes")
EOF
  # No settings written beforehand: the installer from the site carries the server on its end (preset.py), and the
  # launcher it installs starts on that server by itself.
  touch /out/.pc-ready
  wine /tmp/openDMT3-win-Setup.exe > /out/setup.log 2>&1 &
  sleep infinity' >/dev/null
wait_s() { python3 -c "import time; time.sleep($1)"; }
shot() { docker exec -e DISPLAY=:99 "$PC" sh -c "xwd -root -silent | convert xwd:- png:/out/$1.png"; echo "  $OUT/$1.png"; }
windows() { docker exec -e DISPLAY=:99 "$PC" sh -c 'for w in $(xdotool search --onlyvisible --name . 2>/dev/null); do echo "$w|$(xdotool getwindowname $w)|$(xdotool getwindowgeometry $w | tr "\n" " ")"; done'; }
wait_for() { local end=$((SECONDS + $2)); while [ $SECONDS -lt $end ]; do windows | grep -qE "$1" && return 0; wait_s 1; done; return 1; }
fail() { echo "FAIL: $*"; windows; shot 99-failure; docker logs "$SRV" > "$OUT/server.log" 2>&1; cleanup; exit 1; }
click_from_corner() {
  local geo x y w h
  geo=$(windows | grep "|openDMT3|" | head -1)
  x=$(sed -E 's/.*Position: ([0-9]+),([0-9]+).*/\1/' <<<"$geo"); y=$(sed -E 's/.*Position: ([0-9]+),([0-9]+).*/\2/' <<<"$geo")
  w=$(sed -E 's/.*Geometry: ([0-9]+)x([0-9]+).*/\1/' <<<"$geo"); h=$(sed -E 's/.*Geometry: ([0-9]+)x([0-9]+).*/\2/' <<<"$geo")
  docker exec -e DISPLAY=:99 "$PC" xdotool mousemove $((x + w - $1)) $((y + h - $2)) sleep 0.15 click 1
}
keys() { local win; win=$(windows | grep "|openDMT3|" | head -1 | cut -d'|' -f1); docker exec -e DISPLAY=:99 "$PC" sh -c "xdotool windowfocus --sync $win; $1"; }
end=$((SECONDS + 180)); until [ -f "$OUT/.pc-ready" ] || [ $SECONDS -gt $end ]; do wait_s 1; done
[ -f "$OUT/.pc-ready" ] || fail "the PC did not get the launcher from the server's site"
# The installer's own window asks first; Enter presses its Install.
wait_for "\|openDMT3 Setup\|" 120 || fail "the installer's window did not open"
wait_s 2; shot 00-setup
docker exec -e DISPLAY=:99 "$PC" sh -c 'xdotool search --name "openDMT3 Setup" windowfocus --sync key Return'
wait_for "\|openDMT3\|" 120 || fail "the launcher did not open after the installer"
wait_s 4; shot 01-guide
echo "== guide"
click_from_corner 72 33; wait_s 25; shot 02-folder
click_from_corner 72 33; wait_s 3
click_from_corner 72 33; wait_s 4; shot 03-login
# The address is filled in and has the focus: Enter connects. Then the ID has the focus.
keys "xdotool key Return"; wait_s 6; shot 04-connected
keys "xdotool type --delay 60 NOVA; xdotool key Tab; xdotool type --delay 60 pass1234; xdotool key Return"
wait_s 6; shot 05-signed-in
click_from_corner 72 33; wait_s 6; shot 06-ready
echo "== PLAY"
click_from_corner 72 33
wait_for "\|ClientApp\|" 120 || fail "the game's window did not open"
end=$((SECONDS + 120)); until docker logs "$SRV" 2>&1 | grep -q "online: client" || [ $SECONDS -gt $end ]; do wait_s 2; done
docker logs "$SRV" 2>&1 | grep -q "online: client" || fail "the game did not get online with the server"
wait_s 10; shot 07-title
docker exec -e DISPLAY=:99 "$PC" xdotool mousemove 960 830 mousedown 1 sleep 0.15 mouseup 1
end=$((SECONDS + 60)); until docker logs "$SRV" 2>&1 | grep -q "logged in: NOVA" || [ $SECONDS -gt $end ]; do wait_s 2; done
wait_s 3; shot 08-logged-in
docker logs "$SRV" > "$OUT/server.log" 2>&1
grep -E "online: client|logged in|refused" "$OUT/server.log"
grep -q "logged in: NOVA (DJ NOVA)" "$OUT/server.log" || fail "the card login did not reach the server"
# Past the login screen too: the game is still there 15 s later and still connected to the server.
wait_s 15; shot 09-after-login
windows | grep -q "|ClientApp|" || fail "the game closed after the login"
docker logs "$SRV" > "$OUT/server.log" 2>&1
drops=$(sed -n '/logged in: NOVA/,$p' "$OUT/server.log" | grep -c " disconnected$")
[ "$drops" = 0 ] || fail "the game dropped its link after the login"
echo "PASS: downloaded from the server's site, installed, signed in there, DJ NOVA logged in by card on that server and still playing 15 s later"
cleanup
