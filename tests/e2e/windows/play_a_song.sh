#!/bin/bash
# A whole song on the real client, under Wine on a virtual screen with no network: the installer, the guide, PLAY
#   and a card login as install_and_play.sh does them, then the game's own timers carry it on with no input (the
#   mode select, the tutorial, the song select, a song to its end, and back to the title). With no note touched the
#   stage is failed, so no result is sent; what this proves is the real client running a song on this setup.
# Passes when, six minutes after the login, the game is still open, its link to the launcher's server never
# dropped, and it wrote no crash dump. Screenshots every 30 s land in OUT_DIR. The game folder is mounted read only:
# PLAY only reads it, so a song played from it proves nothing of the game's had to be written.
#
#   [GAME_AT=NAME] [MODIFIED=1] tests/e2e/windows/play_a_song.sh GAME_PARENT RELEASES_DIR OUT_DIR [LINK_SOURCE] [WINE_DLLS]
#
# The arguments are install_and_play.sh's. GAME_AT is where the game parent is put on the virtual Desktop (default:
# its own name): a name with Korean letters (a path outside the ANSI code page of this English Windows) or folders
# long enough that the path passes 260 characters; the launcher then plays through its short path. MODIFIED=1: the
# copy's client is a modified PC client, played without the screen fit (the game's window is its own size).
# UNPACK_FROM=ARCHIVE: the game comes in an archive instead (GAME_PARENT then holds no game): the installed launcher's
# own --unpack takes it into Documents with the official 7-Zip for Windows it brings, and the guide finds the folder.
# OPENDMT3_WINE_GPU=1 draws on this PC's graphics card through WSL instead of the CPU (gpu.sh); the run then also
# fails when the game's process does not draw through WSL's D3D12. Either way the in-game layer's log goes to OUT_DIR
# and the frames of the six minutes are summed up at the end (gpu/frames.py).
set -u
PARENT=$(realpath "${1:?usage: play_a_song.sh GAME_PARENT RELEASES_DIR OUT_DIR [LINK_SOURCE] [WINE_DLLS]}")
REL=$(realpath "${2:?}")
OUT=$(realpath -m "${3:?}")
LINKS=${4:-}
DLLS=${5:-}
NAME=${GAME_AT:-$(basename "$PARENT")}
mkdir -p "$OUT"
HERE=$(cd "$(dirname "$0")" && pwd)
# The renderer: the CPU image by default, the GPU image with OPENDMT3_WINE_GPU=1 (gpu.sh).
. "$HERE/gpu.sh"
C=$(wine_name opendmt3-song)
docker rm -f "$C" >/dev/null 2>&1
# Read only: nothing of the game folder may be written.
mounts=(-v "$PARENT:/root/Desktop/$NAME:ro" -v "$REL:/rel:ro" -v "$OUT:/out")
[ -n "$LINKS" ] && mounts+=(-v "$LINKS:$LINKS:ro")
[ -n "$DLLS" ] && mounts+=(-v "$(realpath "$DLLS"):/dlls:ro")
[ -n "${UNPACK_FROM:-}" ] && mounts+=(-v "$(realpath "$UNPACK_FROM"):/archive/$(basename "$UNPACK_FROM"):ro")
# UTF-8 file names on the Linux side (a Korean folder name reaches Windows whole); Windows' own code page stays 1252.
# The in-game layer's log into OUT_DIR (the launcher hands its environment on to the game): its frame counter's lines.
rm -f "$OUT/ingame.log"
docker run -d --name "$C" --network none -e LANG=C.UTF-8 -e 'OPENDMT3_INGAME_LOG=Z:\out\ingame.log' "${WINE_RUN_ARGS[@]}" \
  "${mounts[@]}" "$(wine_image opendmt3-wine:local)" bash -c '
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
# The guide's walk, each Next followed until its step shows, and where its buttons are (guide.sh).
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
if [ -n "${UNPACK_FROM:-}" ]; then
  echo "== unpack, with the launcher's own command"
  docker exec -e WINEPREFIX=/w -e WINEDEBUG=-all "$C" sh -c "wine 'C:\\users\\root\\AppData\\Local\\openDMT3\\current\\openDMT3-cmd.exe' --unpack 'Z:\\archive\\$(basename "$UNPACK_FROM")' --to 'C:\\users\\root\\Documents' --yes > /out/unpack.txt 2>&1; echo \"exit \$?\" >> /out/unpack.txt"
  cat "$OUT/unpack.txt"
  grep -q "^exit 0" "$OUT/unpack.txt" || fail "the launcher did not unpack the archive"
  docker exec "$C" sh -c "find /w/drive_c/users/root/Documents -maxdepth 4 -iname Client.exe" | grep -q . \
    || fail "no game folder came out of the archive"
fi
echo "== guide"
# Next is in the strip along the window's foot, at its right end (guide.sh's click_next).
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
# The last step's PLAY, where Next stood (guide.sh).
click_play
wait_for "\|ClientApp\|" 120 || fail "the game's window did not open"
if [ "${MODIFIED:-}" = 1 ]; then
  # A modified client is played without the screen fit: its window keeps the game's own size.
  windows | grep "|ClientApp|" | grep -q "Geometry: 1920x1080" && fail "the modified client got the screen fit"
else
  windows | grep "|ClientApp|" | grep -q "Geometry: 1920x1080" || fail "the game's window does not cover the screen"
fi
LOG=/w/drive_c/users/root/AppData/Roaming/openDMT3/logs/launcher.log
# openDMT3's own folder for the game, where the client writes its crash dumps.
OWN=/w/drive_c/users/root/AppData/Roaming/openDMT3/game
end=$((SECONDS + 120)); until docker exec "$C" grep -q "online: client" "$LOG" 2>/dev/null || [ $SECONDS -gt $end ]; do wait_s 2; done
docker exec "$C" grep -q "online: client" "$LOG" || fail "the game did not get online with the built-in server"
# On the GPU: the game's own process draws through WSL's D3D12 (no quiet fall back to the CPU).
gpu_proof "$C" 'Client (openDMT3).exe' || fail "the game is not drawn on the GPU"
wait_s 10; shot 08-game-title
echo "== TOUCH to START, then the card screen"
# The game draws 1280x768 over its window (stretched over the screen with the fit): TOUCH to START is at (640, 590)
# of its picture, so at that share of the window.
geo=$(windows | grep "|ClientApp|" | head -1)
gx=$(sed -E 's/.*Position: ([0-9]+),([0-9]+).*/\1/' <<<"$geo"); gy=$(sed -E 's/.*Position: ([0-9]+),([0-9]+).*/\2/' <<<"$geo")
gw=$(sed -E 's/.*Geometry: ([0-9]+)x([0-9]+).*/\1/' <<<"$geo"); gh=$(sed -E 's/.*Geometry: ([0-9]+)x([0-9]+).*/\2/' <<<"$geo")
docker exec -e DISPLAY=:99 "$C" xdotool mousemove $((gx + gw * 640 / 1280)) $((gy + gh * 590 / 768)) mousedown 1 sleep 0.15 mouseup 1
end=$((SECONDS + 60)); until docker exec "$C" grep -q "logged in: NOVA" "$LOG" 2>/dev/null || [ $SECONDS -gt $end ]; do wait_s 2; done
wait_s 3; shot 09-logged-in
docker exec "$C" sh -c "grep -E 'online: client|logged in|refused' $LOG" | tee "$OUT/server-lines.txt"
grep -q "logged in: NOVA (DJ NOVA)" "$OUT/server-lines.txt" || fail "the card login did not reach the server"
# The login's moment on the layer's clock (the monotonic clock in milliseconds): the frames after it are summed up.
logged_at=$(python3 -c 'import time; print(int(time.monotonic() * 1000))')
echo "== after the login"
# The login screen is not the end: the next one (mode select) loads much more of the game, which is where a
# client short of address space gave up. Still there 15 s later, still connected, and no crash dump.
wait_s 15; shot 10-after-login
windows | grep -q "|ClientApp|" || fail "the game closed after the login"
drops=$(docker exec "$C" sh -c "sed -n '/logged in: NOVA/,\$p' $LOG | grep -c ' disconnected\$'")
[ "$drops" = 0 ] || fail "the game dropped its link after the login"
dumps=$(docker exec "$C" sh -c "find /root/Desktop $OWN -name '*.dmp' -newer /out/.prefix-ready | wc -l")
[ "$dumps" = 0 ] || fail "the game wrote a crash dump after the login"
echo "== six minutes of the game's own flow: mode select, tutorial, song select, a song, the title"
for i in $(seq 1 12); do
  wait_s 30; shot "song-$(printf %02d $i)" >/dev/null
  windows | grep -q "|ClientApp|" || fail "the game closed $((i * 30)) s after the login"
done
drops=$(docker exec "$C" sh -c "sed -n '/logged in: NOVA/,\$p' $LOG | grep -c ' disconnected\$'")
[ "$drops" = 0 ] || fail "the game dropped its link during the song"
dumps=$(docker exec "$C" sh -c "find /root/Desktop $OWN -name '*.dmp' -newer /out/.prefix-ready | wc -l")
[ "$dumps" = 0 ] || fail "the game wrote a crash dump during the song"
# How long PLAY took to start the game, and each part of it (the launcher's own line).
docker exec "$C" sh -c "grep 'PLAY started the game' $LOG" | tee "$OUT/play-time.txt"
# The game was given the folder through the launcher's short path when its own could not be (one line in the log).
docker exec "$C" sh -c "grep 'played through' $LOG" | tee "$OUT/short-path.txt"
# The frames of the six minutes after the login, as the layer's counter saw them (said, not judged: the game's own
# loads between its screens make long frames on any renderer).
python3 "$HERE/gpu/frames.py" "$OUT/ingame.log" --from "$logged_at" | tee "$OUT/frames.txt"
echo "PASS: logged in by card, then a song played to its end and the game still open six minutes later, its link kept, no crash dump, the game folder read only"
docker rm -f "$C" >/dev/null
