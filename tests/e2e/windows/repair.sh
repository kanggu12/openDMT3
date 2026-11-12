#!/bin/bash
# The installer over the same version, under Wine on a virtual screen with no network: the install is damaged
# first (a program file deleted from the launcher's folder), then openDMT3-win-Setup.exe is run as a person would.
# It must say this version is installed and offer Repair beside Open; Repair (the ring moved to it with the arrow
# key, then Enter) must put the missing file back, keep the settings as they were, and start the launcher.
# Before that, Help's Repair (openDMT3-cmd --repair) puts back a launcher file that went missing and an updater that
# changed, from the package the install left in packages\, and a second run finds nothing to do. The file the
# installer then puts back is openDMT3.exe itself: without it the console program cannot run (its modules are in
# openDMT3.exe, packaging/windows/console_modules.py), and it says so in two lines, naming the installer's Repair.
#
#   tests/e2e/windows/repair.sh BUILD_DIR OUT_DIR
#
# BUILD_DIR is the OUT_DIR of packaging/windows/build.sh: its setup/velopack-setup.exe installs the version first,
# its releases/openDMT3-win-Setup.exe is the installer people run. No game folder is needed.
set -u
BUILD=$(realpath "${1:?usage: repair.sh BUILD_DIR OUT_DIR}")
OUT=$(realpath -m "${2:?}")
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$(dirname "$0")/../../../opendmt3/__init__.py")
mkdir -p "$OUT"
C=opendmt3-repair
docker rm -f "$C" >/dev/null 2>&1
docker run -d --name "$C" --network none -v "$BUILD/setup/velopack-setup.exe:/setup/Setup.exe:ro" \
  -v "$BUILD/releases:/rel:ro" -v "$OUT:/out" opendmt3-wine:local bash -c '
  Xvfb :99 -screen 0 1600x1000x24 -nolisten tcp >/dev/null 2>&1 &
  export WINEPREFIX=/w DISPLAY=:99 WINEDLLOVERRIDES="mscoree,mshtml=" WINEDEBUG=-all
  wineboot -i >/dev/null 2>&1; wineserver -w
  touch /out/.prefix-ready
  sleep infinity' >/dev/null
wait_s() { python3 -c "import time; time.sleep($1)"; }
in_c() { docker exec -e WINEPREFIX=/w -e DISPLAY=:99 -e WINEDEBUG=-all "$C" bash -c "$1"; }
shot() { docker exec -e DISPLAY=:99 "$C" sh -c "xwd -root -silent | convert xwd:- png:/out/$1.png"; echo "  $OUT/$1.png"; }
windows() { in_c 'for w in $(xdotool search --onlyvisible --name . 2>/dev/null); do echo "$w|$(xdotool getwindowname $w)"; done'; }
fail() { echo "FAIL: $*"; windows; shot 99-failure; docker rm -f "$C" >/dev/null 2>&1; exit 1; }
APP=/w/drive_c/users/root/AppData/Local/openDMT3
CONF=/w/drive_c/users/root/AppData/Roaming/openDMT3
installed() { in_c "grep -o '<version>[^<]*' $APP/current/sq.version 2>/dev/null | cut -d'>' -f2"; }
end=$((SECONDS + 180)); until [ -f "$OUT/.prefix-ready" ] || [ $SECONDS -gt $end ]; do wait_s 1; done
[ -f "$OUT/.prefix-ready" ] || fail "the Wine prefix was not made"

echo "== $VERSION installed, its settings made, then a program file lost"
in_c "wine /setup/Setup.exe --silent > /dev/null 2>&1"
[ "$(installed)" = "$VERSION" ] || fail "Velopack's setup did not install $VERSION"
python3 -c 'import json, sys; json.dump({"version": 1, "language": "en", "guide_done": True, "mode": "offline", "unlock": False},
  open(sys.argv[1], "w"))' "$OUT/launcher.json"
in_c "mkdir -p $CONF && cp /out/launcher.json $CONF/launcher.json"

echo "== Help's Repair (--repair): a launcher file gone and the updater changed, back from the installed package"
in_c "ls $APP/packages/" | tr -d '\r' | sed 's/^/  packages\\/'
# A file of the window's (the console program never reads it) and the updater: what --repair can put back.
FONT="$APP/current/_internal/opendmt3/client/assets/fonts/Pretendard-Bold.ttf"
in_c "[ -s '$FONT' ]" || fail "the launcher has no $FONT to take away"
in_c "rm '$FONT' && printf damaged > $APP/Update.exe"
in_c "cd $APP/current && wine openDMT3-cmd.exe --repair 2>&1" | tr -d '\r' > "$OUT/repair-cli.txt"
sed 's/^/  | /' "$OUT/repair-cli.txt"
grep -q "Files put back: 2." "$OUT/repair-cli.txt" || fail "--repair did not put the two files back"
in_c "[ -s '$FONT' ] && [ \$(stat -c %s $APP/Update.exe) -gt 1000 ]" \
  || fail "--repair said so, but the files are not back"
in_c "cd $APP/current && wine openDMT3-cmd.exe --repair 2>&1" | tr -d '\r' > "$OUT/repair-cli-again.txt"
grep -q "Nothing to repair" "$OUT/repair-cli-again.txt" || fail "a second --repair still found something: $(cat "$OUT/repair-cli-again.txt")"
echo "  --repair: both back, and nothing left to repair after"

in_c "rm $APP/current/openDMT3.exe"
in_c "[ ! -e $APP/current/openDMT3.exe ]" || fail "the program file was not taken away"
# Without openDMT3.exe the console program says what to do, in two lines, and fails: no traceback.
in_c "cd $APP/current && wine openDMT3-cmd.exe --repair 2>&1; echo \"exit \$?\"" | tr -d '\r' > "$OUT/no-window.txt"
sed 's/^/  | /' "$OUT/no-window.txt"
grep -q "Run openDMT3-win-Setup.exe again and choose Repair." "$OUT/no-window.txt" && grep -q "^exit 1$" "$OUT/no-window.txt" \
  || fail "without openDMT3.exe the console program did not name the installer's Repair and fail"
grep -qiE "traceback|PYI-[0-9]+:ERROR" "$OUT/no-window.txt" && fail "without openDMT3.exe the console program printed a traceback"

echo "== the installer"
in_c "wine /rel/openDMT3-win-Setup.exe > /out/setup.log 2>&1 &"
end=$((SECONDS + 120)); until windows | grep -q "|openDMT3 Setup$" || [ $SECONDS -gt $end ]; do wait_s 1; done
windows | grep -q "|openDMT3 Setup$" || fail "the installer's window did not open"
wait_s 2; shot 01-asks
in_c "cat /w/drive_c/users/root/AppData/Local/Temp/openDMT3-setup.log" > "$OUT/installer.log"
grep -q "installed $VERSION, this $VERSION" "$OUT/installer.log" || fail "the installer did not see $VERSION installed"
# The ring starts on Open: the left arrow takes it to Repair, Enter repairs.
in_c "xdotool search --name 'openDMT3 Setup' windowfocus --sync key --delay 200 Left"
wait_s 1; shot 02-repair-ringed
in_c "xdotool search --name 'openDMT3 Setup' windowfocus --sync key Return"
wait_s 1; shot 03-repairing
end=$((SECONDS + 180))
until in_c "[ -e $APP/current/openDMT3.exe ]" && windows | grep -q "|openDMT3$" || [ $SECONDS -gt $end ]; do wait_s 2; done
in_c "[ -e $APP/current/openDMT3.exe ]" || fail "Repair did not put the lost program file back"
windows | grep -q "|openDMT3$" || fail "the launcher did not start after Repair"
[ "$(installed)" = "$VERSION" ] || fail "the installed version is $(installed), not $VERSION"
end=$((SECONDS + 30)); while windows | grep -q "|openDMT3 Setup$" && [ $SECONDS -lt $end ]; do wait_s 1; done
windows | grep -q "|openDMT3 Setup$" && fail "the installer's window stayed after the launcher started"
wait_s 3; shot 04-launcher
in_c "cat $CONF/launcher.json" > "$OUT/launcher-after.json"
python3 -c 'import json, sys
before, after = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
missing = {k: v for k, v in before.items() if k != "version" and after.get(k) != v}
sys.exit("settings changed: %r" % missing if missing else 0)' "$OUT/launcher.json" "$OUT/launcher-after.json" \
  || fail "Repair changed the settings"
docker rm -f "$C" >/dev/null 2>&1
echo "PASS: --repair put back a lost launcher file and a changed updater; openDMT3.exe lost, the console program named the installer's Repair, the installer offered it, Repair put openDMT3.exe back, kept the settings and started the launcher"
