#!/bin/bash
# Playing offline, from the installer to the game's card screen, under Wine on a virtual screen with no network:
#   a fresh Wine prefix, openDMT3-win-Setup.exe run as a person would (Enter on its Install), the first-start guide
#   clicked through with Offline chosen on LOG IN (no server, no logins, no records), then PLAY: the game's own
#   window over the whole screen, and TOUCH to START, after which the game goes on as a guest (no card in its
#   reader) to the mode select. Passes when the game is still open 15 s after TOUCH to START with no crash dump,
#   no card in openDMT3's folder, and no server started for it, the game folder read only all along. Screenshots of
#   each stage land in OUT_DIR. Nothing reaches a real screen.
#
#   tests/e2e/windows/offline_play.sh GAME_PARENT RELEASES_DIR OUT_DIR [LINK_SOURCE] [WINE_DLLS]
#
# The arguments are install_and_play.sh's: GAME_PARENT holds a test copy of the game folder (mounted read only: PLAY
# only reads it), its archives may be links into LINK_SOURCE (read-only), and WINE_DLLS holds the 32-bit DLLs the
# game needs that Wine lacks.
# OPENDMT3_WINE_GPU=1 draws on this PC's graphics card through WSL instead of the CPU (gpu.sh); the run then also
# fails when the game's process does not draw through WSL's D3D12.
set -u
PARENT=$(realpath "${1:?usage: offline_play.sh GAME_PARENT RELEASES_DIR OUT_DIR [LINK_SOURCE] [WINE_DLLS]}")
REL=$(realpath "${2:?}")
OUT=$(realpath -m "${3:?}")
LINKS=${4:-}
DLLS=${5:-}
NAME=$(basename "$PARENT")
mkdir -p "$OUT"
# The renderer: the CPU image by default, the GPU image with OPENDMT3_WINE_GPU=1 (gpu.sh).
. "$(cd "$(dirname "$0")" && pwd)/gpu.sh"
C=$(wine_name opendmt3-offline)
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
# The launcher window's top-left corner and size, from the window list.
geometry() {
  local geo
  geo=$(windows | grep "|openDMT3|" | head -1)
  sed -E 's/.*Position: ([0-9]+),([0-9]+).*Geometry: ([0-9]+)x([0-9]+).*/\1 \2 \3 \4/' <<<"$geo"
}
# A point of the launcher window, given as an offset from its bottom-right corner (where the guide's buttons are).
click_from_corner() {
  local x y w h
  read -r x y w h <<<"$(geometry)"
  docker exec -e DISPLAY=:99 "$C" xdotool mousemove $((x + w - $1)) $((y + h - $2)) sleep 0.15 click 1
}
# The guide's walk, each Next followed until its step shows (guide.sh).
. "$(cd "$(dirname "$0")" && pwd)/guide.sh"
# A point of the launcher window, given as an offset from its top-left corner (at 100 % scaling, 1180x760).
click_at() {
  local x y w h
  read -r x y w h <<<"$(geometry)"
  docker exec -e DISPLAY=:99 "$C" xdotool mousemove $((x + $1)) $((y + $2)) sleep 0.15 click 1
}
LOG=/w/drive_c/users/root/AppData/Roaming/openDMT3/logs/launcher.log
SETTINGS=/w/drive_c/users/root/AppData/Roaming/openDMT3/launcher.json

echo "== installer"
end=$((SECONDS + 120)); until [ -f "$OUT/.prefix-ready" ] || [ $SECONDS -gt $end ]; do wait_s 1; done
# The installer's own window asks first; Install has the ring, so Enter installs, as a person pressing it would.
wait_for "\|openDMT3 Setup\|" 120 || fail "the installer's window did not open"
# A moment for the window to take keys (a key sent as it appears is lost), as install_and_play.sh waits.
wait_s 2
docker exec -e DISPLAY=:99 "$C" sh -c 'xdotool search --name "openDMT3 Setup" windowfocus --sync key Return'
# Still asking ten seconds later: the key was lost after all, so Enter once more.
wait_s 10
windows | grep "|openDMT3 Setup|" | grep -q "Geometry: 552x279" \
  && docker exec -e DISPLAY=:99 "$C" sh -c 'xdotool search --name "openDMT3 Setup" windowfocus --sync key Return'
wait_for "\|openDMT3\|" 120 || fail "the launcher did not open after the installer"
wait_s 6; shot 01-guide-1

echo "== guide, Offline on LOG IN"
# Next sits about 70 px from the right and 33 px from the bottom of the window.
next_to 2 30 || fail "the guide did not go to its game folder step"
wait_s 20; shot 02-guide-2-folder
next_to 3 150 || fail "the guide's game folder step did not let it go on"
wait_s 2; shot 03-guide-3-screen
next_to 4 30 || fail "the guide did not go to its LOG IN step"
wait_s 2; shot 04-guide-4-login
# LOG IN's choice of where logins and records are kept: Offline is the third of its three buttons.
click_at 604 190; wait_s 2; shot 05-guide-4-offline
next_to 5 30 || fail "the guide did not go to its last step"
wait_s 3; shot 06-guide-5-ready
docker exec "$C" python3 -c 'import json, sys; sys.exit(0 if json.load(open(sys.argv[1])).get("mode") == "offline" else 1)' \
  "$SETTINGS" || fail "the guide did not keep Offline"

echo "== PLAY"
click_from_corner 72 33
wait_for "\|ClientApp\|" 120 || fail "the game's window did not open"
windows | grep "|ClientApp|" | grep -q "Geometry: 1920x1080" || fail "the game's window does not cover the screen"
# On the GPU: the game's own process draws through WSL's D3D12 (no quiet fall back to the CPU).
gpu_proof "$C" 'Client (openDMT3).exe' || fail "the game is not drawn on the GPU"
wait_s 15; shot 07-game-title
echo "== TOUCH to START, then on as a guest"
# The game draws 1280x768 stretched over 1920x1080: TOUCH to START is at (640, 590) of its picture.
docker exec -e DISPLAY=:99 "$C" xdotool mousemove 960 830 mousedown 1 sleep 0.15 mouseup 1
wait_s 15; shot 08-as-a-guest
windows | grep -q "|ClientApp|" || fail "the game closed offline"
dumps=$(docker exec "$C" sh -c "find /root/Desktop /w/drive_c/users/root/AppData/Roaming/openDMT3 -name '*.dmp' -newer /out/.prefix-ready | wc -l")
[ "$dumps" = 0 ] || fail "the game wrote a crash dump offline"
# Offline: no card in the reader's file, and no server started for this game.
docker exec "$C" sh -c "[ ! -e /w/drive_c/users/root/AppData/Roaming/openDMT3/game/openDMT3-card.txt ]" \
  || fail "a card was put in while offline"
docker exec "$C" grep -q "game server listening" "$LOG" && fail "a server was started while offline"
echo "PASS: installed, guided with Offline, the game full screen and still open as a guest 15 s after TOUCH to START, with no card and no server, the game folder read only"
docker rm -f "$C" >/dev/null
