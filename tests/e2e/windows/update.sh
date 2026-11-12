#!/bin/bash
# An installed launcher updating itself, under Wine on a virtual screen with no network:
#   the launcher of a finished build is packed twice with Velopack, as its own version A and a newer B, both
#   looking for updates in C:\updates (the address a build is given with OPENDMT3_UPDATE_SOURCE); A's installer
#   is run as a person would; B's packages are put in C:\updates; "openDMT3-cmd.exe --update --yes" finds B,
#   fetches it into a folder of its own, checks it and hands it to Velopack, which closes the launcher, updates it and
#   starts it again. Before that, B's packages without a signature the launcher takes (opendmt3/core/signing.py) are
#   refused: the launcher stays A, says so, and nothing of B is in the install folder (packages\ holds A's package
#   alone, Update.exe is A's own, byte for byte).
#   Passes when the installed version is B and the launcher then says it is the newest, and the desktop shortcut
#   and playing when Windows starts (both set before the update) are still there and still point at the launcher.
#
#   tests/e2e/windows/update.sh BUILD_DIR OUT_DIR
#
# BUILD_DIR is the OUT_DIR of packaging/windows/build.sh: its dist/openDMT3 and assets/ are used as they are
# (nothing is rebuilt, and the build itself is not changed). No game folder is needed.
# The made-up update is signed with a key pair made for this run and removed at its end, and this run's copy of the
# launcher is told to take that key (the file build.sh writes for a test build): nothing here is ever signed with the
# project's key, and no launcher but this run's takes what is signed here. OPENDMT3_CONTAINER names the container
# (two runs at once, from two copies of the tree, each name their own).
set -u
BUILD=$(realpath "${1:?usage: update.sh BUILD_DIR OUT_DIR}")
OUT=$(realpath -m "${2:?}")
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$REPO/opendmt3/__init__.py")
# B: the next patch number with a pre-release tag, so it can never be taken for a real release.
NEXT=$(python3 -c "v='$VERSION'.split('.'); print('%s.%s.%d-updatetest' % (v[0], v[1], int(v[2]) + 1))")
C=${OPENDMT3_CONTAINER:-opendmt3-update}
rm -rf "$OUT" && mkdir -p "$OUT"
docker rm -f "$C" >/dev/null 2>&1
# This run's key (in a folder of its own, which no container is given), and what is signed with it: gone whichever
# way the run ends (the pictures and the logs stay).
KEYS=$(mktemp -d)
KEY="$KEYS/throwaway.key"
tidy() { rm -rf "$KEYS" "$OUT/other" "$OUT"/rel-*/*.nupkg "$OUT"/rel-*/*.nupkg.sig; }
trap tidy EXIT

echo "== packing $VERSION and $NEXT, both looking in C:\\updates"
cp -r "$BUILD/dist/openDMT3" "$OUT/dist"
# The same file build.sh writes, with the test's address in it.
printf '%s' 'C:\updates' > "$OUT/dist/_internal/opendmt3/client/update-source.txt"
# And the file build.sh writes for a test build, with this run's public key in it: both versions packed below take
# updates signed with this run's key (and the project's, of which nothing here has any).
TEST_KEYS="$OUT/dist/_internal/opendmt3/core/update-test-keys.txt"
[ -f "$TEST_KEYS" ] || { echo "FAIL: $BUILD is not a build of this tree (its launcher has no update-test-keys.txt)"; exit 1; }
PUBLIC=$(cd "$REPO" && python3 -m opendmt3.core.signing new-key "$KEY") || { echo "FAIL: no key pair made"; exit 1; }
printf '%s\n' "$PUBLIC" > "$TEST_KEYS"
for v in "$VERSION" "$NEXT"; do
  docker run --rm --network none -v "$OUT:/out" -v "$BUILD/assets:/assets:ro" opendmt3-vpk:local vpk "[win]" pack \
    --packId openDMT3 --packVersion "$v" --packDir /out/dist --mainExe openDMT3.exe --packTitle openDMT3 \
    --packAuthors openDMT3 --icon /assets/openDMT3.ico --splashImage /assets/splash.png \
    --outputDir "/out/rel-$v" > "$OUT/vpk-$v.log" 2>&1 || { echo "FAIL: vpk pack $v"; cat "$OUT/vpk-$v.log"; exit 1; }
done
ls "$OUT/rel-$VERSION/openDMT3-win-Setup.exe" "$OUT/rel-$NEXT/releases.win.json" >/dev/null || { echo "FAIL: no packages"; exit 1; }
# Signed as the release build signs them, with this run's key, and checked as this run's launcher will check them.
(cd "$REPO" && python3 -m opendmt3.core.signing sign "$KEY" "$OUT/rel-$NEXT/"*.nupkg >/dev/null \
  && python3 -m opendmt3.core.signing check --key "$PUBLIC" "$OUT/rel-$NEXT/"*.nupkg >/dev/null) || { echo "FAIL: signing"; exit 1; }
# The project's own key has signed nothing here: without this run's key the same packages are not signed.
(cd "$REPO" && python3 -m opendmt3.core.signing check "$OUT/rel-$NEXT/"*.nupkg >/dev/null 2>&1) \
  && { echo "FAIL: the made-up update passes for one the project signed"; exit 1; }

echo "== installing $VERSION"
docker run -d --name "$C" --network none -v "$OUT:/out" opendmt3-wine:local bash -c '
  Xvfb :99 -screen 0 1600x1000x24 -nolisten tcp >/dev/null 2>&1 &
  export WINEPREFIX=/w DISPLAY=:99 WINEDLLOVERRIDES="mscoree,mshtml=" WINEDEBUG=-all
  wineboot -i >/dev/null 2>&1; wineserver -w
  touch /out/.prefix-ready
  sleep infinity' >/dev/null
wait_s() { python3 -c "import time; time.sleep($1)"; }
in_c() { docker exec -e WINEPREFIX=/w -e DISPLAY=:99 -e WINEDEBUG=-all "$C" bash -c "$1"; }
shot() { docker exec -e DISPLAY=:99 "$C" sh -c "xwd -root -silent | convert xwd:- png:/out/$1.png"; echo "  $OUT/$1.png"; }
# On a failure the launcher's and Velopack's logs come out of the prefix before the container goes.
fail() {
  echo "FAIL: $*"; shot 99-failure
  docker cp "$C:/w/drive_c/users/root/AppData/Roaming/openDMT3/logs" "$OUT/launcher-logs" >/dev/null 2>&1
  docker cp "$C:/w/drive_c/users/root/AppData/Local/velopack/velopack.log" "$OUT/velopack.log" >/dev/null 2>&1
  docker rm -f "$C" >/dev/null 2>&1; exit 1
}
end=$((SECONDS + 180)); until [ -f "$OUT/.prefix-ready" ] || [ $SECONDS -gt $end ]; do wait_s 1; done
[ -f "$OUT/.prefix-ready" ] || fail "the Wine prefix was not made"
APP=/w/drive_c/users/root/AppData/Local/openDMT3
in_c "wine /out/rel-$VERSION/openDMT3-win-Setup.exe > /out/setup.log 2>&1 &"
# The installer's own log says when it is done, and whether every step went well (its splash window has the
# launcher's title, so a window alone proves nothing).
end=$((SECONDS + 180))
until grep -qE "Installation completed successfully|Partially|non-zero exit code|\[ERROR\]" "$OUT/setup.log" 2>/dev/null \
  || [ $SECONDS -gt $end ]; do wait_s 2; done
if ! grep -q "Installation completed successfully" "$OUT/setup.log"; then
  tr -d '\r' < "$OUT/setup.log" | grep -E "WARN|ERROR|Hook|Partial" | tail -5
  fail "the installer did not finish cleanly"
fi
end=$((SECONDS + 120))
until in_c "xdotool search --onlyvisible --name '^openDMT3\$'" >/dev/null 2>&1 || [ $SECONDS -gt $end ]; do wait_s 2; done
in_c "xdotool search --onlyvisible --name '^openDMT3\$'" >/dev/null 2>&1 || fail "the launcher did not open after the installer"
installed() { in_c "grep -o '<version>[^<]*' $APP/current/sq.version | cut -d'>' -f2"; }
# A failure inside Velopack's hook handling no longer fails the install (the launcher logs it and ends the hook
# as finished); it is still shown here, so a run that met one says so.
LOGS=/w/drive_c/users/root/AppData/Roaming/openDMT3/logs
in_c "grep -h -A 3 'start-up hook failed' $LOGS/launcher.log* 2>/dev/null" | sed 's/^/  NOTE: /'
echo "  installed: $(installed)"
[ "$(installed)" = "$VERSION" ] || fail "the installer did not install $VERSION"
shot 01-installed
# The person closes the launcher, then updates from the command line.
in_c "wine taskkill /IM openDMT3.exe /F >/dev/null 2>&1"; wait_s 3
# Set before the update: playing when Windows starts, and the desktop shortcut (a stand-in under its name:
# PowerShell, which makes the real one, is not in Wine).
RUN_KEY='HKCU\Software\Microsoft\Windows\CurrentVersion\Run'
LNK="/w/drive_c/users/root/Desktop/TECHNIKA 3 (openDMT3).lnk"
in_c "cd $APP/current && wine openDMT3-cmd.exe --autostart on > /dev/null 2>&1"
in_c "touch '$LNK'"
in_c "wine reg query '$RUN_KEY' /v openDMT3 2>/dev/null" | tr -d '\r' | grep -q "current.openDMT3.exe\" --play" \
  || fail "--autostart on did not set the Run value"

echo "== $NEXT without a signature the launcher takes: refused, and nothing of it in the install folder"
# The update offered here carries another Update.exe than the installed one (other_updater.py; A's and B's are the
# same file), and its list gives that package's own hashes: Update.exe as it was afterwards means the refused
# package's was never put in its place.
python3 "$REPO/tests/e2e/windows/other_updater.py" "$OUT/rel-$NEXT" "$OUT/other" >/dev/null || fail "no package with another Update.exe made"
# What the install folder holds before: its packages, and Update.exe's hash.
inside() { in_c "ls $APP/packages/ 2>/dev/null | sort | tr '\n' ' '; sha256sum < $APP/Update.exe"; }
before=$(inside)
in_c "mkdir -p /w/drive_c/updates && cp /out/other/* /w/drive_c/updates/"
in_c "cd $APP/current && wine openDMT3-cmd.exe --update --yes > /out/update-unsigned.log 2>&1"
cat "$OUT/update-unsigned.log" | tr -d '\r' | sed 's/^/  /'
grep -q "not signed by the openDMT3 project" "$OUT/update-unsigned.log" || fail "an unsigned update was not refused"
wait_s 10
[ "$(installed)" = "$VERSION" ] || fail "an unsigned update was put in"
in_c "ls $APP/packages/ 2>/dev/null" | grep -q -- "-$NEXT-full.nupkg" && fail "the unsigned package was left for Velopack"
[ "$(inside)" = "$before" ] || fail "the refused update changed the install folder: before '$before', after '$(inside)'"
echo "  refused: still $(installed), packages and Update.exe as before ($before)"
# Signed by a key the launcher does not take (one made here and thrown away at once): refused the same way.
STRANGER="$KEYS/stranger.key"
(cd "$REPO" && python3 -m opendmt3.core.signing new-key "$STRANGER" >/dev/null) || fail "no second key made"
(cd "$REPO" && python3 -m opendmt3.core.signing sign "$STRANGER" "$OUT/other/"*.nupkg >/dev/null); rm -f "$STRANGER"
in_c "cp /out/other/*.sig /w/drive_c/updates/"; rm -rf "$OUT/other"
in_c "cd $APP/current && wine openDMT3-cmd.exe --update --yes > /out/update-stranger.log 2>&1"
grep -q "not signed by the openDMT3 project" "$OUT/update-stranger.log" || fail "an update signed by a stranger's key was not refused"
wait_s 5
[ "$(installed)" = "$VERSION" ] && [ "$(inside)" = "$before" ] || fail "an update signed by a stranger's key changed the install folder"
echo "  refused with a stranger's signature too"
echo "== updating to $NEXT"
# The feed as the build made it, with this run's signatures: its package and list in place of the other's.
in_c "rm -f /w/drive_c/updates/* && cp /out/rel-$NEXT/* /w/drive_c/updates/"
in_c "cd $APP/current && wine openDMT3-cmd.exe --update --yes > /out/update.log 2>&1"
cat "$OUT/update.log" | tr -d '\r'
grep -q "openDMT3 $NEXT is available" "$OUT/update.log" || fail "the launcher did not find $NEXT"
# What shows while Velopack puts the update in (its window carries the package's splash picture).
for i in 1 2 3; do wait_s 0.7; shot "01-applying-$i" >/dev/null; done
# Velopack updates once the launcher has closed, then starts the new one.
end=$((SECONDS + 180)); until [ "$(installed)" = "$NEXT" ] || [ $SECONDS -gt $end ]; do wait_s 2; done
echo "  installed: $(installed)"
[ "$(installed)" = "$NEXT" ] || fail "the installed version is not $NEXT"
end=$((SECONDS + 120))
until in_c "xdotool search --onlyvisible --name '^openDMT3\$'" >/dev/null 2>&1 || [ $SECONDS -gt $end ]; do wait_s 2; done
in_c "xdotool search --onlyvisible --name '^openDMT3\$'" >/dev/null 2>&1 || fail "the launcher did not start again after the update"
shot 02-updated
in_c "wine taskkill /IM openDMT3.exe /F >/dev/null 2>&1"; wait_s 3
in_c "cd $APP/current && wine openDMT3-cmd.exe --update > /out/update-again.log 2>&1"
cat "$OUT/update-again.log" | tr -d '\r'
grep -q "This is the newest version ($NEXT)" "$OUT/update-again.log" || fail "the updated launcher does not know it is the newest"
# What the person set up stays through the update, pointing at the launcher's current folder as before.
in_c "wine reg query '$RUN_KEY' /v openDMT3 2>/dev/null" | tr -d '\r' | grep -q "current.openDMT3.exe\" --play" \
  || fail "the update took away playing when Windows starts"
in_c "[ -e '$LNK' ]" || fail "the update took away the desktop shortcut"
echo "  playing when Windows starts and the desktop shortcut: still there"
docker rm -f "$C" >/dev/null 2>&1
echo "PASS: installed $VERSION, refused $NEXT unsigned and signed by a stranger with the install folder left as it was, updated itself to $NEXT signed with this run's key from C:\\updates, started again, knows it is the newest, and kept the shortcut and the Run value"
