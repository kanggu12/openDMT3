#!/bin/bash
# An installed launcher updating itself with a delta package, under Wine on a virtual screen with no network:
#   the launcher of a finished build is packed with Velopack as its own version A, then, with a file changed and one
#   added, as a newer B into the same folder, so vpk makes B's delta package from A's whole one (as
#   packaging/windows/build.sh does with the previous release kept: packaging/windows/previous.py). A's installer is
#   run as a person would. The feed in C:\updates then holds B's list, its delta package and the signatures, and not
#   B's whole package: "openDMT3-cmd.exe --update --yes" finds B, the launcher fetches the delta into a folder of its
#   own and checks it by its own signature, the installed Update.exe puts B's package together from A's into that same
#   folder (zipped again, so its bytes are not the signed ones), the launcher checks it holds the files that were
#   signed (opendmt3/core/signing.py) and only then moves it into packages\, and Velopack puts it in and starts B.
#   Passes when the installed version is B with B's changed and added files, B started again, and the launcher's log
#   says the package put together from deltas holds the signed files (with no whole package in the feed, B can only
#   have come from the delta).
#
#   tests/e2e/windows/update_delta.sh BUILD_DIR OUT_DIR
#
# BUILD_DIR is the OUT_DIR of packaging/windows/build.sh: its dist/openDMT3 and assets/ are used as they are (nothing
# is rebuilt, and the build itself is not changed). No game folder is needed.
# The made-up update is signed with a key pair made for this run and removed at its end, and this run's copy of the
# launcher is told to take that key (the file build.sh writes for a test build): nothing here is ever signed with the
# project's key, and no launcher but this run's takes what is signed here. OPENDMT3_CONTAINER names the container
# (two runs at once, from two copies of the tree, each name their own).
set -u
BUILD=$(realpath "${1:?usage: update_delta.sh BUILD_DIR OUT_DIR}")
OUT=$(realpath -m "${2:?}")
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$REPO/opendmt3/__init__.py")
# B: the next patch number with a pre-release tag, so it can never be taken for a real release.
NEXT=$(python3 -c "v='$VERSION'.split('.'); print('%s.%s.%d-updatetest' % (v[0], v[1], int(v[2]) + 1))")
C=${OPENDMT3_CONTAINER:-opendmt3-update-delta}
rm -rf "$OUT" && mkdir -p "$OUT"
docker rm -f "$C" >/dev/null 2>&1
# This run's key (in a folder of its own, which no container is given), and what is signed with it: gone whichever
# way the run ends (the pictures and the logs stay).
KEYS=$(mktemp -d)
KEY="$KEYS/throwaway.key"
tidy() { rm -rf "$KEYS" "$OUT"/rel/*.nupkg "$OUT"/rel/*.nupkg.sig; }
trap tidy EXIT
# vpk makes delta packages with zstd's program: the image build.sh makes has it (its recipe label says so).
docker image inspect -f '{{index .Config.Labels "opendmt3.recipe"}}' opendmt3-vpk:local 2>/dev/null | grep -q -- "-zstd$" \
  || { echo "FAIL: opendmt3-vpk:local is not the image packaging/windows/build.sh makes (run the build first)"; exit 1; }

echo "== packing $VERSION, then $NEXT into the same folder (its delta package made from $VERSION's)"
cp -r "$BUILD/dist/openDMT3" "$OUT/dist"
# The same file build.sh writes, with the test's address in it.
printf '%s' 'C:\updates' > "$OUT/dist/_internal/opendmt3/client/update-source.txt"
# And the file build.sh writes for a test build, with this run's public key in it: both versions packed below take
# updates signed with this run's key (and the project's, of which nothing here has any).
TEST_KEYS="$OUT/dist/_internal/opendmt3/core/update-test-keys.txt"
[ -f "$TEST_KEYS" ] || { echo "FAIL: $BUILD is not a build of this tree (its launcher has no update-test-keys.txt)"; exit 1; }
PUBLIC=$(cd "$REPO" && python3 -m opendmt3.core.signing new-key "$KEY") || { echo "FAIL: no key pair made"; exit 1; }
printf '%s\n' "$PUBLIC" > "$TEST_KEYS"
pack() {
  docker run --rm --network none -v "$OUT:/out" -v "$BUILD/assets:/assets:ro" opendmt3-vpk:local vpk "[win]" pack \
    --packId openDMT3 --packVersion "$1" --packDir /out/dist --mainExe openDMT3.exe --packTitle openDMT3 \
    --packAuthors openDMT3 --icon /assets/openDMT3.ico --splashImage /assets/splash.png \
    --outputDir /out/rel > "$OUT/vpk-$1.log" 2>&1 || { echo "FAIL: vpk pack $1"; cat "$OUT/vpk-$1.log"; exit 1; }
}
pack "$VERSION"
# A's installer, kept: packing B into the same folder makes B's.
cp "$OUT/rel/openDMT3-win-Setup.exe" "$OUT/setup-$VERSION.exe"
# B differs from A as a release from the one before it, in part: a file changed (a patch in the delta) and one added.
printf '\n%s\n' "$NEXT" >> "$OUT/dist/_internal/LICENSE"
printf '%s' "$NEXT" > "$OUT/dist/_internal/opendmt3/client/delta-test.txt"
pack "$NEXT"
DELTA="$OUT/rel/openDMT3-$NEXT-delta.nupkg"
FULL="$OUT/rel/openDMT3-$NEXT-full.nupkg"
ls "$DELTA" "$FULL" >/dev/null || { echo "FAIL: vpk made no delta package"; exit 1; }
grep -h "Delta processed" "$OUT/vpk-$NEXT.log" | sed 's/^.*INF\] /  vpk: /'
echo "  $NEXT whole package: $(stat -c %s "$FULL") bytes, delta package: $(stat -c %s "$DELTA") bytes"
# Signed as the release build signs them, with this run's key, and checked as this run's launcher will check them.
(cd "$REPO" && python3 -m opendmt3.core.signing sign "$KEY" "$FULL" "$DELTA" >/dev/null \
  && python3 -m opendmt3.core.signing check --key "$PUBLIC" "$FULL" "$DELTA" >/dev/null) || { echo "FAIL: signing"; exit 1; }
# The project's own key has signed nothing here: without this run's key the same packages are not signed.
(cd "$REPO" && python3 -m opendmt3.core.signing check "$FULL" "$DELTA" >/dev/null 2>&1) \
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
LOGS=/w/drive_c/users/root/AppData/Roaming/openDMT3/logs
APP=/w/drive_c/users/root/AppData/Local/openDMT3
# On a failure the launcher's and Velopack's logs come out of the prefix before the container goes.
fail() {
  echo "FAIL: $*"; shot 99-failure
  docker cp "$C:$LOGS" "$OUT/launcher-logs" >/dev/null 2>&1
  docker cp "$C:/w/drive_c/users/root/AppData/Local/velopack/velopack.log" "$OUT/velopack.log" >/dev/null 2>&1
  docker rm -f "$C" >/dev/null 2>&1; exit 1
}
end=$((SECONDS + 180)); until [ -f "$OUT/.prefix-ready" ] || [ $SECONDS -gt $end ]; do wait_s 1; done
[ -f "$OUT/.prefix-ready" ] || fail "the Wine prefix was not made"
in_c "wine /out/setup-$VERSION.exe > /out/setup.log 2>&1 &"
end=$((SECONDS + 180))
until grep -qE "Installation completed successfully|Partially|non-zero exit code|\[ERROR\]" "$OUT/setup.log" 2>/dev/null \
  || [ $SECONDS -gt $end ]; do wait_s 2; done
grep -q "Installation completed successfully" "$OUT/setup.log" || fail "the installer did not finish cleanly"
end=$((SECONDS + 120))
until in_c "xdotool search --onlyvisible --name '^openDMT3\$'" >/dev/null 2>&1 || [ $SECONDS -gt $end ]; do wait_s 2; done
in_c "xdotool search --onlyvisible --name '^openDMT3\$'" >/dev/null 2>&1 || fail "the launcher did not open after the installer"
installed() { in_c "grep -o '<version>[^<]*' $APP/current/sq.version | cut -d'>' -f2"; }
echo "  installed: $(installed)"
[ "$(installed)" = "$VERSION" ] || fail "the installer did not install $VERSION"
# The package installed is what Velopack puts B together from.
in_c "ls $APP/packages/" | grep -q -- "-$VERSION-full.nupkg" || fail "no $VERSION package in packages\\ to start a delta from"
shot 01-installed
in_c "wine taskkill /IM openDMT3.exe /F >/dev/null 2>&1"; wait_s 3

echo "== updating to $NEXT from a feed with its delta package and no whole package"
# B's list (it names both packages), the delta and the signatures; B's whole package is left out on purpose.
in_c "mkdir -p /w/drive_c/updates && cd /out/rel && cp releases.win.json RELEASES '$(basename "$DELTA")' '$(basename "$DELTA").sig' '$(basename "$FULL").sig' /w/drive_c/updates/"
in_c "ls /w/drive_c/updates/" | grep -q -- "-$NEXT-full.nupkg\$" && fail "the feed holds $NEXT's whole package"
in_c "cd $APP/current && wine openDMT3-cmd.exe --update --yes > /out/update.log 2>&1"
tr -d '\r' < "$OUT/update.log" | sed 's/^/  /'
grep -q "openDMT3 $NEXT is available" "$OUT/update.log" || fail "the launcher did not find $NEXT"
# The delta gave the signed package: the launcher never turned to the whole one (which the feed does not hold).
grep -q "The whole update is downloading" "$OUT/update.log" && fail "the launcher turned to the whole package"
end=$((SECONDS + 180)); until [ "$(installed)" = "$NEXT" ] || [ $SECONDS -gt $end ]; do wait_s 2; done
echo "  installed: $(installed)"
[ "$(installed)" = "$NEXT" ] || fail "the installed version is not $NEXT"
end=$((SECONDS + 120))
until in_c "xdotool search --onlyvisible --name '^openDMT3\$'" >/dev/null 2>&1 || [ $SECONDS -gt $end ]; do wait_s 2; done
in_c "xdotool search --onlyvisible --name '^openDMT3\$'" >/dev/null 2>&1 || fail "the launcher did not start again after the update"
shot 02-updated
docker cp "$C:$LOGS" "$OUT/launcher-logs" >/dev/null 2>&1
said=$(grep -h "put together from delta packages, holds the files the project signed" "$OUT"/launcher-logs/launcher.log* | tail -1)
[ -n "$said" ] || fail "the launcher did not say the package put together from deltas holds the signed files"
echo "  launcher: ${said#* INFO * }"
# B's own files: the changed one and the new one, in the folder Velopack started B from.
in_c "tail -n 1 $APP/current/_internal/LICENSE" | tr -d '\r' | grep -qx "$NEXT" || fail "$NEXT's changed file is not in the folder"
in_c "cat $APP/current/_internal/opendmt3/client/delta-test.txt" | grep -qx "$NEXT" || fail "$NEXT's new file is not in the folder"
in_c "wine taskkill /IM openDMT3.exe /F >/dev/null 2>&1"; wait_s 2
docker rm -f "$C" >/dev/null 2>&1
echo "PASS: installed $VERSION, updated to $NEXT from a feed with only its $(stat -c %s "$DELTA")-byte delta package (the whole one is $(stat -c %s "$FULL") bytes), put together on the PC, checked by its files, started again"
