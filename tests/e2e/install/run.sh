#!/bin/bash
# The one-line install (packaging/server/install.sh) as a server owner runs it on Linux, in a container
# (odt3-srv-install, python:3.12-slim-bookworm, as a user of its own): the installer from a folder of release files
# (the server package made here from this tree, as the release makes it, with the checksums), then the command it
# puts on PATH: setup, start, /health, status, stop; the installer again while the server runs (an update: stopped,
# put in place, started again, the data kept); a later release whose libraries cannot be had (refused, the running
# server left as it was); --uninstall, the data still there. Each step says PASS or FAIL; the
# exit code is the number that failed. Its network is for pip and 7-Zip's site only.
#
#   tests/e2e/install/run.sh OUT_DIR
set -u
OUT=$(realpath -m "${1:?usage: tests/e2e/install/run.sh OUT_DIR}")
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$REPO/opendmt3/__init__.py")
C=${OPENDMT3_E2E_NAME:-odt3-srv}-install
rm -rf "$OUT" && mkdir -p "$OUT/files"
docker rm -f "$C" >/dev/null 2>&1
# The release's files: the server package (its one top folder, the parts a server needs), the checksums, and the
# installer with this version put in, as packaging/release.sh makes them.
(cd "$REPO" && git ls-files -z --cached --others --exclude-standard -- dmt3 compose.yaml LICENSE packaging/docker \
   opendmt3/__init__.py opendmt3/__main__.py opendmt3/core opendmt3/server opendmt3/client/assets/fonts \
   | tar --null -T - -cf -) | (mkdir -p "$OUT/stage/opendmt3-server-$VERSION" && tar -xf - -C "$OUT/stage/opendmt3-server-$VERSION")
(cd "$OUT/stage" && python3 -c "import os, sys, zipfile
with zipfile.ZipFile(sys.argv[1], 'w', zipfile.ZIP_DEFLATED) as z:
    for top, dirs, files in os.walk(sys.argv[2]):
        for f in files: z.write(os.path.join(top, f))" "$OUT/files/opendmt3-server-$VERSION.zip" "opendmt3-server-$VERSION")
(cd "$OUT/files" && sha256sum "opendmt3-server-$VERSION.zip" > "opendmt3-$VERSION-checksums.txt")
sed "s/@VERSION@/$VERSION/g" "$REPO/packaging/server/install.sh" > "$OUT/files/opendmt3-server-$VERSION-linux-installer.sh"
# The official 7-Zip the installer takes for this container (x86-64), beside the release's files, where the installer
# looks first: fetched once into the working folder's cache and checked against the installer's own hash, so every
# install and update of the test reads it from there, whatever 7-Zip's site answers that day.
SEVEN=7z2501-linux-x64.tar.xz
SEVEN_SHA=$(sed -n "s/.*$SEVEN \([0-9a-f]\{64\}\).*/\1/p" "$REPO/packaging/server/install.sh")
CACHE=$REPO/_work/cache
mkdir -p "$CACHE"
if ! echo "$SEVEN_SHA  $CACHE/$SEVEN" | sha256sum -c --quiet - 2>/dev/null; then
  curl -fsSL --retry 3 -o "$CACHE/$SEVEN" "https://www.7-zip.org/a/$SEVEN" \
    && echo "$SEVEN_SHA  $CACHE/$SEVEN" | sha256sum -c --quiet - || { echo "FAIL 7-Zip for the test"; exit 1; }
fi
cp "$CACHE/$SEVEN" "$OUT/files/"
# A later release whose libraries cannot be had (a pin no package index has, and no index to ask): its install fails at
# pip, and must leave the running server as it was. Its package is this one under the later version's name.
NEXT=${VERSION}9
cp "$OUT/files/opendmt3-server-$VERSION.zip" "$OUT/files/opendmt3-server-$NEXT.zip"
(cd "$OUT/files" && sha256sum "opendmt3-server-$NEXT.zip" > "opendmt3-$NEXT-checksums.txt")
sed "s/@VERSION@/$NEXT/g; s/pillow==[0-9.]*/pillow==0.0.1/" "$REPO/packaging/server/install.sh" \
  > "$OUT/files/opendmt3-server-$NEXT-linux-installer.sh"
docker run --rm --name "$C" -v "$OUT/files:/files:ro" -v "$OUT:/out" -e VERSION="$VERSION" -e NEXT="$NEXT" \
  python:3.12-slim-bookworm bash -c '
  set -u
  failed=0
  step() { if [ "$2" = 0 ]; then echo "PASS $1"; else echo "FAIL $1"; failed=$((failed + 1)); fi; }
  apt-get update -qq >/dev/null && apt-get install -y -qq --no-install-recommends curl >/dev/null 2>&1
  useradd -m owner
  as() { su owner -c "export PATH=/home/owner/.local/bin:\$PATH OPENDMT3_SERVER_FILES=/files; $1"; }
  # The one line, as the guide gives it (the release files from the folder instead of GitHub).
  as "cat /files/opendmt3-server-$VERSION-linux-installer.sh | sh" > /out/install.txt 2>&1
  r=$?; step "the one line installs the server" $r
  as "opendmt3-server --version" > /out/version.txt 2>&1; grep -q "openDMT3 server $VERSION" /out/version.txt
  r=$?; step "opendmt3-server --version: $(cat /out/version.txt)" $r
  [ -x /home/owner/.local/share/opendmt3-server/bin/7zz ]
  r=$?; step "the official 7-Zip beside it" $r
  as "opendmt3-server setup --admin BOSS --password pass1234 && opendmt3-server start" > /out/start.txt 2>&1
  r=$?; step "setup and start" $r
  python3 -c "import urllib.request; print(urllib.request.urlopen(\"http://127.0.0.1:4730/health\", timeout=5).read().decode())" > /out/health.txt 2>&1
  grep -q "\"ok\":true" /out/health.txt
  r=$?; step "/health: $(cat /out/health.txt)" $r
  as "cat /files/opendmt3-server-$VERSION-linux-installer.sh | sh" > /out/update.txt 2>&1
  as "opendmt3-server status" > /out/status.txt 2>&1
  r=$?; step "the installer again while it runs: stopped, put in place, running again" $r
  # The later release that cannot get its libraries (no index to ask): it says so and fails, and the running server
  # stays as it was, never stopped.
  as "export PIP_INDEX_URL=http://127.0.0.1:9/simple PIP_RETRIES=0 PIP_TIMEOUT=3; cat /files/opendmt3-server-$NEXT-linux-installer.sh | sh" > /out/failed-update.txt 2>&1
  r1=$?
  as "opendmt3-server status" > /out/status-after-failure.txt 2>&1
  r2=$?
  as "opendmt3-server --version" > /out/version-after-failure.txt 2>&1
  [ $r1 != 0 ] && [ $r2 = 0 ] && grep -q "openDMT3 server $VERSION" /out/version-after-failure.txt \
    && grep -q "runs as it was" /out/failed-update.txt
  r=$?; step "a later release whose libraries cannot be had: refused, the server still running $VERSION ($(tail -n 1 /out/failed-update.txt))" $r
  as "sh /files/opendmt3-server-$VERSION-linux-installer.sh --uninstall" > /out/uninstall.txt 2>&1
  [ ! -e /home/owner/.local/bin/opendmt3-server ] && [ -f /home/owner/.local/share/opendmt3-server/data/openDMT3.sqlite ] \
    && ! python3 -c "import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:4730/health\", timeout=3)" 2>/dev/null
  r=$?; step "--uninstall: stopped and removed, the data kept" $r
  echo "failed: $failed"
  exit $failed
'
