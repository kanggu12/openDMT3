#!/bin/bash
# Removing openDMT3 under Wine on a virtual screen with no network, the three ways people do it, each on a fresh
# install and on its own copy of a game folder PLAY has set up:
#   1. Help's Uninstall, answered Delete all (settings, players and records go too), by mouse and keyboard as a
#      person would;
#   2. openDMT3-cmd --uninstall --yes (settings, players and records stay);
#   3. Windows' app list (the uninstall command Velopack registered for it), first while the game is open, then
#      again after it has closed.
# After each one the install folder, openDMT3's line in the app list, the desktop shortcut and starting with
# Windows are gone, and tests/e2e/windows/folder_check.py checks the game folder against its own list in backup\.
# Copy 1 has its list as this version writes it (each copy marked as openDMT3's own) and one copy read-only, as
# copies of files from a CD are, which Windows will not delete as it is; copies 2 and 3 keep the list as the
# folder came (the earliest versions marked nothing, so their copies stay). Copy 1's settings folder also holds a file
# of someone else's, which must stay when settings, players and records go.
#
#   tests/e2e/windows/remove.sh GAME_ROOT BUILD_DIR OUT_DIR
#
# GAME_ROOT is a game folder PLAY has set up (its backup\ holds openDMT3.json); it is copied, links as links
# (never followed), and never written. BUILD_DIR is the output folder of packaging/windows/build.sh. OUT_DIR must
# be new or empty: the copies, screenshots and logs go there.
set -u
GAME=$(realpath "${1:?usage: remove.sh GAME_ROOT BUILD_DIR OUT_DIR}")
BUILD=$(realpath "${2:?}")
OUT=$(realpath -m "${3:?}")
HERE=$(cd "$(dirname "$0")" && pwd)
[ -f "$GAME/backup/openDMT3.json" ] || { echo "no backup\\openDMT3.json in $GAME"; exit 2; }
[ -f "$BUILD/setup/velopack-setup.exe" ] || { echo "no setup/velopack-setup.exe in $BUILD"; exit 2; }
[ -z "$(ls -A "$OUT" 2>/dev/null)" ] || { echo "$OUT is not empty"; exit 2; }
mkdir -p "$OUT/games"
for copy in a b c; do
  cp -a "$GAME" "$OUT/games/$copy"
done
# Copy 1: every copy marked as made by openDMT3, as this version lists them, and one of them read-only.
python3 -c 'import json, sys
path = sys.argv[1]
data = json.load(open(path))
for entry in data["files"].values():
    if entry["existed"]:
        entry["copied"] = True
json.dump(data, open(path, "w"), indent=2)' "$OUT/games/a/backup/openDMT3.json"
READ_ONLY=$(python3 -c 'import json, sys
print(sorted(k for k, e in json.load(open(sys.argv[1]))["files"].items() if e["existed"])[0])' "$OUT/games/a/backup/openDMT3.json")
chmod a-w "$OUT/games/a/backup/$READ_ONLY"
echo "copy 1: its copies marked as openDMT3's own, backup\\$READ_ONLY read-only"
for copy in a b c; do
  # openDMT3's list as it was before removing (removing takes it away).
  cp "$OUT/games/$copy/backup/openDMT3.json" "$OUT/$copy-list.json"
done
C=opendmt3-remove
docker rm -f "$C" >/dev/null 2>&1
docker run -d --name "$C" --network none -v "$BUILD/setup/velopack-setup.exe:/setup/Setup.exe:ro" -v "$OUT:/out" \
  opendmt3-wine:local bash -c '
  Xvfb :99 -screen 0 1600x1000x24 -nolisten tcp >/dev/null 2>&1 &
  export WINEPREFIX=/w DISPLAY=:99 WINEDLLOVERRIDES="mscoree,mshtml=" WINEDEBUG=-all
  wineboot -i >/dev/null 2>&1; wineserver -w
  touch /out/.prefix-ready
  sleep infinity' >/dev/null
wait_s() { python3 -c "import time; time.sleep($1)"; }
in_c() { docker exec -e WINEPREFIX=/w -e DISPLAY=:99 -e WINEDEBUG=-all "$C" bash -c "$1"; }
shot() { docker exec -e DISPLAY=:99 "$C" sh -c "xwd -root -silent | convert xwd:- png:/out/$1.png"; echo "  $OUT/$1.png"; }
windows() { in_c 'for w in $(xdotool search --onlyvisible --name . 2>/dev/null); do echo "$w|$(xdotool getwindowname $w)|$(xdotool getwindowgeometry $w | tr "\n" " ")"; done'; }
fail() { echo "FAIL: $*"; windows; shot 99-failure; docker rm -f "$C" >/dev/null 2>&1; exit 1; }
U=/w/drive_c/users/root
APP=$U/AppData/Local/openDMT3
CONF=$U/AppData/Roaming/openDMT3
LNK="$U/Desktop/TECHNIKA 3 (openDMT3).lnk"
RUN_KEY='HKCU\Software\Microsoft\Windows\CurrentVersion\Run'
APP_LIST='HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\openDMT3'
end=$((SECONDS + 180)); until [ -f "$OUT/.prefix-ready" ] || [ $SECONDS -gt $end ]; do wait_s 1; done
[ -f "$OUT/.prefix-ready" ] || fail "the Wine prefix was not made"

install() {   # install COPY: a fresh install whose settings choose games/COPY, with the shortcut and the Run value
  in_c "wine /setup/Setup.exe --silent > /dev/null 2>&1"
  in_c "[ -f $APP/current/openDMT3.exe ]" || fail "openDMT3 did not install"
  # The settings as the first-start guide leaves them, the game copy chosen; the database and a daily backup of it
  # (empty files: SQLite takes an empty file as an empty database).
  python3 -c 'import json, sys; json.dump({"version": 1, "game_folder": "Z:\\out\\games\\" + sys.argv[1],
    "language": "en", "guide_done": True, "mode": "this_pc"}, open(sys.argv[2], "w"))' "$1" "$OUT/$1-launcher.json"
  in_c "mkdir -p $CONF/server/backups $CONF/logs && cp /out/$1-launcher.json $CONF/launcher.json \
        && : > $CONF/server/openDMT3.sqlite && : > $CONF/server/backups/openDMT3-20261110-000000-daily.sqlite"
  # The shortcut as Windows makes it (PowerShell is not in Wine, so a stand-in under its name), and starting with
  # Windows through the launcher itself.
  in_c "touch '$LNK'"
  in_c "cd $APP/current && wine openDMT3-cmd.exe --autostart on 2>/dev/null" | tr -d '\r' | grep -q "starts with Windows" \
    || fail "openDMT3-cmd --autostart on did not turn it on"
  in_c "wine reg query '$RUN_KEY' /v openDMT3 2>/dev/null" | grep -q -- "--play" || fail "no Run value after --autostart on"
}

removed() {   # removed STEP: wait for the uninstall to end, then what goes in every case
  local end=$((SECONDS + 150))
  until ! in_c "[ -e $APP ]" || [ $SECONDS -gt $end ]; do wait_s 2; done
  in_c "[ ! -e $APP ]" || fail "$1: the install folder is still there"
  # Velopack's own steps finish a moment after the folder goes.
  wait_s 4
  in_c "wine reg query '$APP_LIST' 2>&1" | tr -d '\r' > "$OUT/$1-app-list.txt"
  grep -qi "UninstallString" "$OUT/$1-app-list.txt" && fail "$1: openDMT3 is still in the app list"
  in_c "[ ! -e '$LNK' ]" || fail "$1: the desktop shortcut is still there"
  in_c "wine reg query '$RUN_KEY' 2>&1" | tr -d '\r' > "$OUT/$1-run-key.txt"
  grep -q "openDMT3" "$OUT/$1-run-key.txt" && fail "$1: the game still starts with Windows"
  # Ended programs Wine has not reaped yet (state Z, "<defunct>") do not count: nothing of them runs.
  in_c "ps -eo pid,stat,args | awk '\$2 !~ /^Z/' | grep -i 'openDMT3\|Update.exe' | grep -v grep" > "$OUT/$1-processes.txt"
  [ -s "$OUT/$1-processes.txt" ] && fail "$1: programs of openDMT3 still run: $(cat "$OUT/$1-processes.txt")"
  in_c "ls -laR $CONF 2>&1" > "$OUT/$1-settings-folder.txt"
  echo "  $1: install folder, app list line, shortcut, Run value: gone"
}

window_geometry() {   # x y of the launcher window's top-left corner
  windows | grep "|openDMT3|" | head -1 | sed -E 's/.*Position: ([0-9]+),([0-9]+).*/\1 \2/'
}

colour_centre() {   # colour_centre SHOT COLOUR: the centre "x y" of the pixels of that colour on the screenshot
  in_c "convert /out/$1.png -fuzz 4% -fill black +opaque '$2' -fill white -opaque '$2' -format '%@' info: 2>/dev/null" \
    | python3 -c 'import re, sys; m = re.match(r"(\d+)x(\d+)\+(\d+)\+(\d+)", sys.stdin.read())
w, h, x, y = map(int, m.groups()) if m else (0, 0, 0, 0)
print("%d %d" % (x + w // 2, y + h // 2) if w > 1 and h > 1 else "")'
}

menu_entry() {   # menu_entry SHOT X Y N: the middle y of the menu's Nth entry from its end in the window at X,Y
  # Each row of the menu column, averaged to one grey value: the rows with words stand out of the dark column.
  in_c "convert /out/$1.png -crop 160x700+$(($2 + 20))+$(($3 + 100)) +repage -colorspace Gray -scale 1x700! -depth 8 txt:-" \
    | python3 -c 'import re, sys
rows = [(int(m.group(1)), int(m.group(2))) for m in (re.match(r"0,(\d+): \((\d+)", l) for l in sys.stdin) if m]
base = sorted(v for _, v in rows)[len(rows) // 2]
bands, start = [], None
for y, v in rows:
    if v > base + 6 and start is None:
        start = y
    elif v <= base + 6 and start is not None:
        bands.append((start + y - 1) // 2)
        start = None
n = int(sys.argv[2])
print(bands[-n] + int(sys.argv[1]) + 100 if len(bands) >= n else "")' "$3" "$4"
}

lowest_colour() {   # lowest_colour SHOT COLOUR: the centre "x y" of the lowest words on the screenshot in that colour
  # Each row of the colour's mask, averaged to one value (16 bits, so a row with a few such pixels still counts):
  # the runs of rows with the colour are the lines of words in it, and the last run is the lowest.
  local band top bottom
  band=$(in_c "convert /out/$1.png -fuzz 4% -fill black +opaque '$2' -fill white -opaque '$2' -colorspace Gray -scale 1x1000! -depth 16 txt:-" \
    | python3 -c 'import re, sys
rows = [(int(m.group(1)), int(m.group(2))) for m in (re.match(r"0,(\d+): \((\d+)", l) for l in sys.stdin) if m]
bands, start = [], None
for y, v in rows + [(len(rows), 0)]:
    if v > 0 and start is None:
        start = y
    elif v == 0 and start is not None:
        bands.append((start, y))
        start = None
print("%d %d" % bands[-1] if bands else "")')
  [ -n "$band" ] || return 0
  read -r top bottom <<<"$band"
  # Across that run of rows only: where the words sit from left to right.
  in_c "convert /out/$1.png -crop 1600x$((bottom - top))+0+$top +repage -fuzz 4% -fill black +opaque '$2' -fill white -opaque '$2' -format '%@' info: 2>/dev/null" \
    | python3 -c 'import re, sys; m = re.match(r"(\d+)x(\d+)\+(\d+)\+(\d+)", sys.stdin.read())
w, h, x, y = map(int, m.groups()) if m else (0, 0, 0, 0)
print("%d %d" % (x + w // 2, int(sys.argv[1]) + y + h // 2) if w > 1 and h > 0 else "")' "$top"
}

echo "== 1. Uninstall on Help, Delete all: settings, players and records too"
install a
# Someone else's file among the server's own: it stays when settings, players and records go.
in_c "echo mine > $CONF/server/notes.txt"
python3 "$HERE/folder_check.py" snapshot "$OUT/games/a" "$OUT/a-before.json" || fail "no snapshot"
in_c "cd $APP/current && wine openDMT3.exe > /dev/null 2>&1 &"
end=$((SECONDS + 120)); until windows | grep -q "|openDMT3|" || [ $SECONDS -gt $end ]; do wait_s 2; done
windows | grep -q "|openDMT3|" || fail "the launcher did not open"
wait_s 4
read -r X Y <<<"$(window_geometry)"
shot 1-00-launcher
# HELP, the menu's last entry but one (LAUNCHER is last), found on the screenshot (the words' height differs between
# systems).
MY=$(menu_entry 1-00-launcher "$X" "$Y" 2)
[ -n "$MY" ] || fail "no menu on the launcher"
in_c "xdotool mousemove $((X + 77)) $MY sleep 0.2 click 1"
wait_s 2; shot 1-01-help-page
# Down to the end of the page with the mouse wheel, as a person scrolls.
in_c "xdotool mousemove $((X + 700)) $((Y + 400)) sleep 0.2 click --repeat 25 --delay 60 5"
wait_s 2; shot 1-02-uninstall-row
# Help's two buttons in the danger look (their words are this pink): Put the game's files back, and Uninstall, the
# last of the tools, so the lowest.
read -r BX BY <<<"$(lowest_colour 1-02-uninstall-row '#ffb8d9')"
[ -n "${BX:-}" ] || fail "no Uninstall button on Help"
in_c "xdotool mousemove $BX $BY sleep 0.2 click 1"
wait_s 3; shot 1-03-asked
# The ring starts on Cancel: Tab moves it to Keep data, Tab again to Delete all, and Enter presses that.
in_c "xdotool search --name '^openDMT3\$' windowfocus --sync key --delay 150 Tab Tab"
wait_s 1; shot 1-04-delete-all
in_c "xdotool search --name '^openDMT3\$' windowfocus --sync key --delay 150 Return"
# The progress dialog and the last step in the launcher's own dialogs, then the launcher closes and Velopack's
# uninstall runs silent: each new window is shot, and any window that is not the launcher's fails the run.
seen=""
end=$((SECONDS + 150))
while [ $SECONDS -lt $end ]; do
  list=$(windows)
  while IFS='|' read -r wid title _; do
    [ -z "$wid" ] && continue
    case " $seen " in *" $wid "*) continue ;; esac
    seen="$seen $wid"
    echo "  window: $title" | tee -a "$OUT/1-windows.txt"
    wait_s 1; shot "1-05-window-$wid"
    [ "$title" = "openDMT3" ] || fail "1: a window that is not the launcher's showed: $title"
  done <<<"$list"
  in_c "[ -e $APP ]" || break
  wait_s 1
done
removed 1
python3 "$HERE/folder_check.py" removed "$OUT/games/a" "$OUT/a-list.json" "$OUT/a-before.json" || fail "1: the game folder"
# Only someone else's file is left in the settings folder: the rest of it went, the log included.
left=$(in_c "cd $CONF 2>/dev/null && find . -type f | sort | tr '\n' ' '")
[ "$left" = "./server/notes.txt " ] || fail "1: settings, players and records were to go, and only them: left $left"
echo "  1: settings, players and records: gone, someone else's file kept (the hook was told, and wrote nothing after)"

echo "== 2. openDMT3-cmd --uninstall --yes"
install b
python3 "$HERE/folder_check.py" snapshot "$OUT/games/b" "$OUT/b-before.json" || fail "no snapshot"
in_c "cd $APP/current && timeout 120 wine openDMT3-cmd.exe --uninstall --yes 2>&1" | tr -d '\r' > "$OUT/2-cli.txt"
cat "$OUT/2-cli.txt" | sed 's/^/  | /'
grep -q "Uninstalling openDMT3" "$OUT/2-cli.txt" || fail "2: the command line did not start the removal"
removed 2
python3 "$HERE/folder_check.py" removed "$OUT/games/b" "$OUT/b-list.json" "$OUT/b-before.json" || fail "2: the game folder"
for kept in launcher.json server/openDMT3.sqlite server/backups/openDMT3-20261110-000000-daily.sqlite logs/launcher.log; do
  in_c "[ -f $CONF/$kept ]" || fail "2: $kept was to stay"
done
echo "  2: settings, players, records and the log: kept"

echo "== 3. Windows' app list, while the game is open"
install c
# The game: a program started from the game folder's own top (any .exe there counts as the game).
in_c "cp /w/drive_c/windows/syswow64/notepad.exe /out/games/c/ClientApp.exe && cd /out/games/c && wine ClientApp.exe > /dev/null 2>&1 &"
wait_s 5
python3 "$HERE/folder_check.py" snapshot "$OUT/games/c" "$OUT/c-before.json" || fail "no snapshot"
UNINSTALL=$(in_c "wine reg query '$APP_LIST' /v UninstallString 2>/dev/null" | tr -d '\r' | sed -n 's/.*REG_SZ *//p')
echo "  the app list runs: $UNINSTALL"
[ -n "$UNINSTALL" ] || fail "3: no UninstallString in the app list"
in_c "wine $UNINSTALL > /out/3-uninstall.log 2>&1 &"
seen=""
end=$((SECONDS + 150))
while [ $SECONDS -lt $end ]; do
  list=$(windows)
  while IFS='|' read -r wid title _; do
    [ -z "$wid" ] && continue
    case " $seen " in *" $wid "*) continue ;; esac
    seen="$seen $wid"
    echo "  window: $title" | tee -a "$OUT/3-windows.txt"
    case "$title" in *otepad*) continue ;; esac
    wait_s 1; shot "3-window-$wid"
    fail "3: Windows' app list showed a window: $title"
  done <<<"$list"
  in_c "[ -e $APP ]" || break
  wait_s 1
done
removed 3
python3 "$HERE/folder_check.py" unchanged "$OUT/games/c" "$OUT/c-before.json" || fail "3: the game folder while the game is open"
in_c "[ -f $CONF/launcher.json ] && [ -f $CONF/server/openDMT3.sqlite ]" || fail "3: the app list deleted settings or records"
echo "  3: the game's files stayed while it was open; the note in backup names them; settings kept"

echo "== 3b. the app list again, after the game has closed"
in_c "wine taskkill /f /im ClientApp.exe > /dev/null 2>&1"
wait_s 3
install c
in_c "wine $UNINSTALL > /out/3b-uninstall.log 2>&1 &"
end=$((SECONDS + 150))
while [ $SECONDS -lt $end ]; do
  in_c "[ -e $APP ]" || break
  wait_s 2
done
in_c "xdotool search --onlyvisible --name . 2>/dev/null" | grep -q . && fail "3b: Windows' app list showed a window"
removed 3b
python3 "$HERE/folder_check.py" removed "$OUT/games/c" "$OUT/c-list.json" "$OUT/c-before.json" || fail "3b: the game folder"
docker rm -f "$C" >/dev/null 2>&1
echo "PASS: Uninstall on Help (Delete all), openDMT3-cmd --uninstall and the app list (with the game open, then closed) each left no install, shortcut or Run value, and the game folder as its list says"
