#!/bin/bash
# The one-line install (packaging/server/install.sh) as a server owner runs it on Linux, in a container
# (odt3-srv-install, python:3.12-slim-bookworm, as a user of its own): the installer from a folder of release files
# (the server package made here from this tree, as the release makes it, with the checksums), then the command it
# puts on PATH: setup, start, /health, status, stop; the installer again while the server runs (an update: stopped,
# put in place, started again, the data kept); --uninstall, the data still there. Each step says PASS or FAIL; the
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
docker run --rm --name "$C" -v "$OUT/files:/files:ro" -v "$OUT:/out" -e VERSION="$VERSION" \
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
  as "sh /files/opendmt3-server-$VERSION-linux-installer.sh --uninstall" > /out/uninstall.txt 2>&1
  [ ! -e /home/owner/.local/bin/opendmt3-server ] && [ -f /home/owner/.local/share/opendmt3-server/data/openDMT3.sqlite ] \
    && ! python3 -c "import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:4730/health\", timeout=3)" 2>/dev/null
  r=$?; step "--uninstall: stopped and removed, the data kept" $r
  echo "failed: $failed"
  exit $failed
'
