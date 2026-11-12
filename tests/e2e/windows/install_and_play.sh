#!/bin/bash
# From installer to a player logged in by card, under Wine on a virtual screen with no network:
#   a fresh Wine prefix, openDMT3-win-Setup.exe run as a person would (Enter on its Install), the first-start
#   guide clicked through
#   (Next, Next, Next, a DJ made on LOG IN with the keyboard, Next, PLAY), the game's own window over the whole
#   screen, TOUCH to START, and the card screen logging the DJ in through the launcher's built-in server.
#   Screenshots of each stage land in OUT_DIR; the run fails at the first stage that does not happen.
#   Nothing reaches a real screen.
#
#   tests/e2e/windows/install_and_play.sh GAME_PARENT RELEASES_DIR OUT_DIR [LINK_SOURCE] [WINE_DLLS]
#
# GAME_PARENT is a folder with a test copy of the game folder inside it (up to four levels down); it is mounted on
# the virtual Desktop, where the guide looks, read only (PLAY only reads a game folder). The copy's archives may be
# links into LINK_SOURCE (mounted read-only at the same path), so a test copy never needs the 40 GB of archives
# copied and the originals are never written.
# WINE_DLLS is a folder of 32-bit system DLLs Windows has and Wine lacks (the game needs mfc42.dll); they go
# into the prefix's SysWOW64, where Windows keeps them.
# OPENDMT3_WINE_GPU=1 draws on this PC's graphics card through WSL instead of the CPU (gpu.sh); the run then also
# fails when the game's process does not draw through WSL's D3D12.
set -u
PARENT=$(realpath "${1:?usage: install_and_play.sh GAME_PARENT RELEASES_DIR OUT_DIR [LINK_SOURCE] [WINE_DLLS]}")
REL=$(realpath "${2:?}")
OUT=$(realpath -m "${3:?}")
LINKS=${4:-}
DLLS=${5:-}
NAME=$(basename "$PARENT")
mkdir -p "$OUT"
# The renderer: the CPU image by default, the GPU image with OPENDMT3_WINE_GPU=1 (gpu.sh).
. "$(cd "$(dirname "$0")" && pwd)/gpu.sh"
C=$(wine_name opendmt3-e2e)
docker rm -f "$C" >/dev/null 2>&1
# Read only: PLAY only reads the game folder, so nothing of it may be written.
mounts=(-v "$PARENT:/root/Desktop/$NAME:ro" -v "$REL:/rel:ro" -v "$OUT:/out")
[ -n "$LINKS" ] && mounts+=(-v "$LINKS:$LINKS:ro")
[ -n "$DLLS" ] && mounts+=(-v "$(realpath "$DLLS"):/dlls:ro")
# UTF-8 file names on the Linux side; Windows' own code page stays 1252.
docker run -d --name "$C" --network none -e LANG=C.UTF-8 "${WINE_RUN_ARGS[@]}" "${mounts[@]}" \
  "$(wine_image opendmt3-wine:local)" bash -c '
  # The virtual screen kept off the GPU (gpu.sh; plain Xvfb on the CPU image).
  env -u GALLIUM_DRIVER -u LD_LIBRARY_PATH Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp >/dev/null 2>&1 &
  export WINEPREFIX=/w DISPLAY=:99 WINEDLLOVERRIDES="mscoree,mshtml=" WINEDEBUG=-all
  # A silent sound card, so the game can open DirectSound without hardware.
  printf "pcm.!default { type null }\nctl.!default { type hw card 0 }\n" > /etc/asound.conf
  wineboot -i >/dev/null 2>&1; wineserver -w
  [ -d /dlls ] && cp /dlls/*.dll /w/drive_c/windows/syswow64/
  touch /out/.prefix-ready
  wine /rel/openDMT3-win-Setup.exe > /out/setup.log 2>&1 &
  sleep infinity' >/dev/null
wait_s() { python3 -c "import time; time.sleep($1)"; }
shot() { docker exec -e DISPLAY=:99 "$C" sh -c "xwd -root -silent | convert xwd:- png:/out/$1.png"; echo "  $OUT/$1.png"; }
windows() { docker exec -e DISPLAY=:99 "$C" sh -c 'for w in $(xdotool search --onlyvisible --name . 2>/dev/null); do echo "$w|$(xdotool getwindowname $w)|$(xdotool getwindowgeometry $w | tr "\n" " ")"; done'; }
wait_for() {   # wait_for <title regex> <seconds>
  local end=$((SECONDS + $2))
  while [ $SECONDS -lt $end ]; do
    windows | grep -qE "$1" && return 0
    wait_s 1
  done
  return 1
}
fail() { echo "FAIL: $*"; windows; shot 99-failure; docker rm -f "$C" >/dev/null; exit 1; }
# A point of the launcher window, given as an offset from its bottom-right corner (where the guide's buttons are).
click_from_corner() {
  local geo x y w h
  geo=$(windows | grep "|openDMT3|" | head -1)
  x=$(sed -E 's/.*Position: ([0-9]+),([0-9]+).*/\1/' <<<"$geo"); y=$(sed -E 's/.*Position: ([0-9]+),([0-9]+).*/\2/' <<<"$geo")
  w=$(sed -E 's/.*Geometry: ([0-9]+)x([0-9]+).*/\1/' <<<"$geo"); h=$(sed -E 's/.*Geometry: ([0-9]+)x([0-9]+).*/\2/' <<<"$geo")
  docker exec -e DISPLAY=:99 "$C" xdotool mousemove $((x + w - $1)) $((y + h - $2)) sleep 0.15 click 1
}
# The guide's walk, each Next followed until its step shows (guide.sh).
. "$(cd "$(dirname "$0")" && pwd)/guide.sh"
echo "== installer"
end=$((SECONDS + 120)); until [ -f "$OUT/.prefix-ready" ] || [ $SECONDS -gt $end ]; do wait_s 1; done
# The installer's own window asks first; Install has the ring, so Enter installs, as a person pressing it would.
wait_for "\|openDMT3 Setup\|" 120 || fail "the installer's window did not open"
wait_s 2; shot 01-setup
docker exec -e DISPLAY=:99 "$C" sh -c 'xdotool search --name "openDMT3 Setup" windowfocus --sync key Return'
wait_s 2; shot 01-installing
wait_for "\|openDMT3\|" 120 || fail "the launcher did not open after the installer"
windows | grep -q "|openDMT3 Setup|" && wait_s 3
windows | grep -q "|openDMT3 Setup|" && fail "the installer's window stayed after the launcher opened"
wait_s 4; shot 02-guide-1
docker exec "$C" sh -c 'ls /w/drive_c/users/root/AppData/Local/openDMT3/current; find /w/drive_c/users -iname "openDMT3*.lnk"' > "$OUT/installed.txt"
grep -q "openDMT3.exe" "$OUT/installed.txt" || fail "the launcher is not in %LocalAppData%\\openDMT3\\current"
echo "== guide"
# Next sits about 70 px from the right and 33 px from the bottom of the window.
next_to 2 30 || fail "the guide did not go to its game folder step"
wait_s 20; shot 03-guide-2-folder
next_to 3 150 || fail "the guide's game folder step did not let it go on"
wait_s 2; shot 04-guide-3-screen
next_to 4 30 || fail "the guide did not go to its LOG IN step"
wait_s 2; shot 05-guide-4-login
# LOG IN: the ID field has the focus; type a DJ the way a person would, Enter adds it.
win=$(windows | grep "|openDMT3|" | head -1 | cut -d'|' -f1)
docker exec -e DISPLAY=:99 "$C" sh -c "xdotool windowfocus --sync $win; xdotool type --delay 60 NOVA; xdotool key Tab; xdotool type --delay 60 pass1234; xdotool key Tab; xdotool type --delay 60 'DJ NOVA'; xdotool key Return"
wait_s 3; shot 06-guide-4-player
next_to 5 30 || fail "the guide did not go to its last step"
wait_s 3; shot 07-guide-5-ready
echo "== PLAY"
click_from_corner 72 33
wait_for "\|ClientApp\|" 120 || fail "the game's window did not open"
windows | grep "|ClientApp|" | grep -q "Geometry: 1920x1080" || fail "the game's window does not cover the screen"
LOG=/w/drive_c/users/root/AppData/Roaming/openDMT3/logs/launcher.log
end=$((SECONDS + 120)); until docker exec "$C" grep -q "online: client" "$LOG" 2>/dev/null || [ $SECONDS -gt $end ]; do wait_s 2; done
docker exec "$C" grep -q "online: client" "$LOG" || fail "the game did not get online with the built-in server"
# On the GPU: the game's own process draws through WSL's D3D12 (no quiet fall back to the CPU).
gpu_proof "$C" 'Client (openDMT3).exe' || fail "the game is not drawn on the GPU"
wait_s 10; shot 08-game-title
echo "== TOUCH to START, then the card screen"
# The game draws 1280x768 stretched over 1920x1080: TOUCH to START is at (640, 590) of its picture.
docker exec -e DISPLAY=:99 "$C" xdotool mousemove 960 830 mousedown 1 sleep 0.15 mouseup 1
end=$((SECONDS + 60)); until docker exec "$C" grep -q "logged in: NOVA" "$LOG" 2>/dev/null || [ $SECONDS -gt $end ]; do wait_s 2; done
wait_s 3; shot 09-logged-in
docker exec "$C" sh -c "grep -E 'online: client|logged in|refused' $LOG" | tee "$OUT/server-lines.txt"
grep -q "logged in: NOVA (DJ NOVA)" "$OUT/server-lines.txt" || fail "the card login did not reach the server"
echo "== after the login"
# The login screen is not the end: the next one (mode select) loads much more of the game, which is where a
# client short of address space gave up. Still there 15 s later, still connected, and no crash dump.
wait_s 15; shot 10-after-login
windows | grep -q "|ClientApp|" || fail "the game closed after the login"
drops=$(docker exec "$C" sh -c "sed -n '/logged in: NOVA/,\$p' $LOG | grep -c ' disconnected\$'")
[ "$drops" = 0 ] || fail "the game dropped its link after the login"
dumps=$(docker exec "$C" sh -c "find /root/Desktop /w/drive_c/users/root/AppData/Roaming/openDMT3 -name '*.dmp' -newer /out/.prefix-ready | wc -l")
[ "$dumps" = 0 ] || fail "the game wrote a crash dump after the login"
# How long PLAY took to start the game, and each part of it (the launcher's own line).
docker exec "$C" sh -c "grep 'PLAY started the game' $LOG" | tee "$OUT/play-time.txt"
echo "== this PC's site"
# The launcher started its site with the built-in server at PLAY, and openDMT3-cmd --records (the twin of PLAY's
# [My records]) hands out a one-use link that opens the player's own page signed in: both from the Windows build.
docker exec "$C" grep -q "site on this PC at http://127.0.0.1:" "$LOG" || fail "the launcher's site did not start"
APP='C:\users\root\AppData\Local\openDMT3\current\openDMT3-cmd.exe'
docker exec -d -e WINEPREFIX=/w -e WINEDEBUG=-all -e DISPLAY=:99 "$C" sh -c \
  "timeout 90 wine '$APP' --records --no-browser > /out/records.txt 2>&1"
end=$((SECONDS + 60)); until grep -q "Sign-in link" "$OUT/records.txt" 2>/dev/null || [ $SECONDS -gt $end ]; do wait_s 2; done
LINK=$(grep -o "http://127.0.0.1:[0-9]*/signin/once/[A-Za-z0-9_-]*?lang=[a-z]*" "$OUT/records.txt" | head -1)
[ -n "$LINK" ] || fail "openDMT3-cmd --records printed no link"
docker exec "$C" python3 -c '
import http.cookiejar, sys, urllib.request
browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
page = browser.open(sys.argv[1], timeout=15)
body = page.read().decode("utf-8")
print("  " + page.geturl())
sys.exit(0 if page.geturl().endswith("/dj/1") and "DJ NOVA" in body else 1)' "$LINK" || fail "the records link did not open DJ NOVA's page"
echo "PASS: installed, guided, the game full screen, DJ NOVA logged in by card and still playing 15 s later; the records page opened"
docker rm -f "$C" >/dev/null
