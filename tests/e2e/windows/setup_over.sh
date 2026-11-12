#!/bin/bash
# The installer over an older openDMT3 that is open, under Wine on a virtual screen with no network: the older
# release goes in with Velopack's own silent setup, its launcher is started, then openDMT3-win-Setup.exe (the
# installer's dialogs) is run as a person would. It must ask to update and say the open launcher closes first;
# Enter on Update must leave the new version installed and its launcher running, with the desktop shortcut and
# playing when Windows starts (set on the older one) still there.
#
#   tests/e2e/windows/setup_over.sh OLD_VELOPACK_SETUP NEW_RELEASES_DIR OUT_DIR
#
# OLD_VELOPACK_SETUP is an older build's Velopack setup (a build keeps it as setup/velopack-setup.exe);
# NEW_RELEASES_DIR is a newer build's releases folder, with the installer people run.
set -u
OLD=$(realpath "${1:?usage: setup_over.sh OLD_VELOPACK_SETUP NEW_RELEASES_DIR OUT_DIR}")
REL=$(realpath "${2:?}")
OUT=$(realpath -m "${3:?}")
mkdir -p "$OUT"
NEW_VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$(dirname "$0")/../../../opendmt3/__init__.py")
C=opendmt3-setup-over
docker rm -f "$C" >/dev/null 2>&1
docker run -d --name "$C" --network none -v "$OLD:/old/Setup.exe:ro" -v "$REL:/rel:ro" -v "$OUT:/out" opendmt3-wine:local bash -c '
  Xvfb :99 -screen 0 1600x1000x24 -nolisten tcp >/dev/null 2>&1 &
  export WINEPREFIX=/w DISPLAY=:99 WINEDLLOVERRIDES="mscoree,mshtml=" WINEDEBUG=-all
  wineboot -i >/dev/null 2>&1; wineserver -w
  touch /out/.prefix-ready
  sleep infinity' >/dev/null
wait_s() { python3 -c "import time; time.sleep($1)"; }
in_c() { docker exec -e WINEPREFIX=/w -e DISPLAY=:99 -e WINEDEBUG=-all "$C" bash -c "$1"; }
shot() { docker exec -e DISPLAY=:99 "$C" sh -c "xwd -root -silent | convert xwd:- png:/out/$1.png"; echo "  $OUT/$1.png"; }
windows() { in_c 'for w in $(xdotool search --onlyvisible --name . 2>/dev/null); do echo "$w|$(xdotool getwindowname $w)"; done'; }
fail() { echo "FAIL: $*"; windows; shot 99-failure; docker cp "$C:/w/drive_c/users/root/AppData/Local/Temp" "$OUT/temp" >/dev/null 2>&1; docker rm -f "$C" >/dev/null 2>&1; exit 1; }
APP=/w/drive_c/users/root/AppData/Local/openDMT3
installed() { in_c "grep -o '<version>[^<]*' $APP/current/sq.version 2>/dev/null | cut -d'>' -f2"; }
end=$((SECONDS + 180)); until [ -f "$OUT/.prefix-ready" ] || [ $SECONDS -gt $end ]; do wait_s 1; done
[ -f "$OUT/.prefix-ready" ] || fail "the Wine prefix was not made"

echo "== the older release, installed and open"
in_c "wine /old/Setup.exe --silent --log 'C:\\old-setup.log' > /dev/null 2>&1"
OLD_VERSION=$(installed)
[ -n "$OLD_VERSION" ] || fail "the older release did not install"
# The same version would make the installer offer Repair and Open, and Enter would open: not an update.
[ "$OLD_VERSION" != "$NEW_VERSION" ] || fail "the older release is $OLD_VERSION, the same as the new one"
# Set on the older launcher: playing when Windows starts, and the desktop shortcut (a stand-in under its name:
# PowerShell, which makes the real one, is not in Wine).
RUN_KEY='HKCU\Software\Microsoft\Windows\CurrentVersion\Run'
LNK="/w/drive_c/users/root/Desktop/TECHNIKA 3 (openDMT3).lnk"
in_c "cd $APP/current && wine openDMT3-cmd.exe --autostart on > /dev/null 2>&1"
in_c "touch '$LNK'"
in_c "wine reg query '$RUN_KEY' /v openDMT3 2>/dev/null" | tr -d '\r' | grep -q "current.openDMT3.exe\" --play" \
  || fail "--autostart on did not set the Run value on the older launcher"
in_c "cd $APP && wine openDMT3.exe > /dev/null 2>&1 &"
end=$((SECONDS + 120)); until windows | grep -q "|openDMT3$" || [ $SECONDS -gt $end ]; do wait_s 2; done
windows | grep -q "|openDMT3$" || fail "the older launcher did not open"
echo "  $OLD_VERSION installed and open"

echo "== the installer"
in_c "wine /rel/openDMT3-win-Setup.exe > /out/setup.log 2>&1 &"
end=$((SECONDS + 120)); until windows | grep -q "|openDMT3 Setup$" || [ $SECONDS -gt $end ]; do wait_s 1; done
windows | grep -q "|openDMT3 Setup$" || fail "the installer's window did not open"
wait_s 2; shot 01-asks
# What the installer saw and so asked: an update, with the launcher open.
in_c "cat /w/drive_c/users/root/AppData/Local/Temp/openDMT3-setup.log" > "$OUT/installer.log"
grep -q "installed $OLD_VERSION, this $NEW_VERSION, launcher open True" "$OUT/installer.log" \
  || fail "the installer did not see $OLD_VERSION installed and the launcher open"
in_c "xdotool search --name 'openDMT3 Setup' windowfocus --sync key Return"
wait_s 1; shot 02-updating
end=$((SECONDS + 180)); until [ "$(installed)" = "$NEW_VERSION" ] || [ $SECONDS -gt $end ]; do wait_s 2; done
[ "$(installed)" = "$NEW_VERSION" ] || fail "the installed version is $(installed), not $NEW_VERSION"
end=$((SECONDS + 120)); until windows | grep -q "|openDMT3$" && ! windows | grep -q "|openDMT3 Setup$" || [ $SECONDS -gt $end ]; do wait_s 2; done
windows | grep -q "|openDMT3$" || fail "the new launcher did not start"
windows | grep -q "|openDMT3 Setup$" && fail "the installer's window stayed"
wait_s 3; shot 03-new-launcher
in_c "wine reg query '$RUN_KEY' /v openDMT3 2>/dev/null" | tr -d '\r' | grep -q "current.openDMT3.exe\" --play" \
  || fail "the installer took away playing when Windows starts"
in_c "[ -e '$LNK' ]" || fail "the installer took away the desktop shortcut"
in_c "ls /w/drive_c/users/root/AppData/Local/Temp/ | grep -i opendmt3" > "$OUT/temp-logs.txt"
docker rm -f "$C" >/dev/null 2>&1
echo "PASS: $OLD_VERSION open, the installer asked, Enter updated it to $NEW_VERSION and started the new launcher; the shortcut and the Run value stayed"
