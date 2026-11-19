#!/bin/bash
# The one-line install (packaging/server/install.sh) as a server owner runs it on Linux, in a container
# (odt3-srv-install, python:3.12-slim-bookworm, as a user of its own): the installer from a folder of release files
# (the server package made here from this tree, as the release makes it, with the SHA-256 sums), then the command it
# puts on PATH: setup, start, /health and the admin pages', status, stop; expose --admin-public with Caddy beside it
# (the release Caddy ./dmt3 runs, copied out of its image: the site and the admin pages over HTTPS at the name), then
# without it and --off; the installer again while the server runs (an update: stopped, put in place, started again,
# the data kept); a later release whose libraries cannot be had (refused, the running server left as it was);
# --uninstall, the data still there. Each step says PASS or FAIL; the exit code is the number that failed. Its network
# is for pip and 7-Zip's site only.
#
#   tests/e2e/install/run.sh OUT_DIR
set -u
OUT=$(realpath -m "${1:?usage: tests/e2e/install/run.sh OUT_DIR}")
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$REPO/opendmt3/__init__.py")
C=${OPENDMT3_E2E_NAME:-odt3-srv}-install
rm -rf "$OUT" && mkdir -p "$OUT/files"
docker rm -f "$C" >/dev/null 2>&1
# The release's files: the server package (its one top folder named as the zip, the parts a server needs), the
# SHA-256 sums, and the installer with this version put in, under the names packaging/release.sh gives them.
PACKAGE=opendmt3-server-$VERSION-linux-macos
(cd "$REPO" && git ls-files -z --cached --others --exclude-standard -- dmt3 compose.yaml LICENSE packaging/docker \
   opendmt3/__init__.py opendmt3/__main__.py opendmt3/core opendmt3/server opendmt3/client/assets/fonts \
   | tar --null -T - -cf -) | (mkdir -p "$OUT/stage/$PACKAGE" && tar -xf - -C "$OUT/stage/$PACKAGE")
(cd "$OUT/stage" && python3 -c "import os, sys, zipfile
with zipfile.ZipFile(sys.argv[1], 'w', zipfile.ZIP_DEFLATED) as z:
    for top, dirs, files in os.walk(sys.argv[2]):
        for f in files: z.write(os.path.join(top, f))" "$OUT/files/$PACKAGE.zip" "$PACKAGE")
(cd "$OUT/files" && sha256sum "$PACKAGE.zip" > "opendmt3-$VERSION-sha256sums.txt")
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
cp "$OUT/files/$PACKAGE.zip" "$OUT/files/opendmt3-server-$NEXT-linux-macos.zip"
(cd "$OUT/files" && sha256sum "opendmt3-server-$NEXT-linux-macos.zip" > "opendmt3-$NEXT-sha256sums.txt")
sed "s/@VERSION@/$NEXT/g; s/pillow==[0-9.]*/pillow==0.0.1/" "$REPO/packaging/server/install.sh" \
  > "$OUT/files/opendmt3-server-$NEXT-linux-installer.sh"
# The Caddy ./dmt3 runs (the exact release its edge.yaml names), its program copied out of that image for the server's
# own program to run beside it, as an owner without Docker runs Caddy's own build for Linux.
CADDY_IMAGE=$(sed -n 's/^ *image: \(caddy:[^ ]*\)$/\1/p' "$REPO/packaging/docker/edge.yaml")
docker rm -f "$C-caddy" >/dev/null 2>&1
{ docker create --name "$C-caddy" "$CADDY_IMAGE" >/dev/null && docker cp "$C-caddy:/usr/bin/caddy" "$OUT/files/caddy" \
    >/dev/null; } || { docker rm -f "$C-caddy" >/dev/null 2>&1; echo "FAIL Caddy for the test ($CADDY_IMAGE)"; exit 1; }
docker rm -f "$C-caddy" >/dev/null 2>&1
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
  # The admin pages, a site of their own, on this PC (their own port and /health).
  python3 -c "import urllib.request; print(urllib.request.urlopen(\"http://127.0.0.1:4731/health\", timeout=5).read().decode())" > /out/admin-health.txt 2>&1
  grep -q "\"ok\":true" /out/admin-health.txt
  r=$?; step "the admin pages answer on this PC: $(cat /out/admin-health.txt)" $r
  # expose --admin-public with Caddy beside it, as the owner runs it: the site and the admin pages over HTTPS at the
  # name, through Caddy (its own authority, whose root it keeps in the owner home), the admin pages behind it at the
  # next port on this PC alone; then without it nothing of the admin site at the admin port, and --off.
  D=/home/owner/.local/share/opendmt3-server/data
  root=/home/owner/.local/share/caddy/pki/authorities/local/root.crt
  over() { curl -s --max-time 5 --cacert "$root" --connect-to "dmt3.test:$1:127.0.0.1:$1" -o "/out/https-$1.json" \
             -w "%{http_code}" "https://dmt3.test:$1/health"; }
  # Caddy as the owner, its log in the owner home (copied out at the end: the output folder is not the owner one).
  caddy() { as "nohup /files/caddy run --config $D/Caddyfile > /home/owner/caddy-$1.txt 2>&1 & echo \$! > /home/owner/caddy.pid"; }
  as "opendmt3-server expose dmt3.test --local-ca --admin-public && opendmt3-server restart" > /out/expose-admin.txt 2>&1
  r1=$?
  caddy admin
  for i in $(seq 60); do [ "$(over 4731)" = 200 ] && break; sleep 1; done
  site=$(over 443); admin=$(over 4731)
  [ $r1 = 0 ] && [ "$site" = 200 ] && [ "$admin" = 200 ] && grep -q "\"ok\":true" /out/https-4731.json \
    && grep -q "The admin pages: https://dmt3.test:4731/ (through Caddy)." /out/expose-admin.txt
  r=$?; step "expose --admin-public, Caddy beside it: https://dmt3.test/ $site, the admin pages at https://dmt3.test:4731/ $admin" $r
  python3 -c "import urllib.request; print(urllib.request.urlopen(\"http://127.0.0.1:4732/health\", timeout=5).read().decode())" > /out/admin-behind.txt 2>&1
  grep -q "\"ok\":true" /out/admin-behind.txt
  r=$?; step "behind Caddy the admin pages are at 127.0.0.1:4732 on this PC alone: $(cat /out/admin-behind.txt)" $r
  as "opendmt3-server expose dmt3.test --local-ca" > /out/expose-site.txt 2>&1
  # A restart first, while Caddy still has the admin port: said in one line, and the server runs on as it was.
  as "opendmt3-server restart" > /out/restart-early.txt 2>&1
  r1=$?
  python3 -c "import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:4730/health\", timeout=5)" 2>/dev/null
  r2=$?
  [ $r1 != 0 ] && [ $r2 = 0 ] && grep -q "port 4731 is taken by another program" /out/restart-early.txt
  r=$?; step "a restart while Caddy still has the admin port says so, the server running on ($(tail -1 /out/restart-early.txt))" $r
  # In the order expose gives: Caddy with the new settings first, so it lets go of the admin port, then the server,
  # whose admin listener takes it back.
  as "/files/caddy reload --config $D/Caddyfile" > /out/caddy-reload.txt 2>&1
  as "opendmt3-server restart" >> /out/expose-site.txt 2>&1
  for i in $(seq 60); do [ "$(over 443)" = 200 ] && break; sleep 1; done
  site=$(over 443); admin=$(over 4731)
  [ "$site" = 200 ] && [ "$admin" != 200 ] && grep -q "The admin pages: http://127.0.0.1:4731/ (this PC only)." /out/expose-site.txt \
    && grep -q "so it lets go of port 4731" /out/expose-site.txt && grep -q "The server runs again" /out/expose-site.txt
  r=$?; step "without --admin-public nothing of the admin site behind Caddy (https://dmt3.test:4731/ $admin), the site there ($site)" $r
  as "kill \$(cat /home/owner/caddy.pid)"
  cp /home/owner/caddy-*.txt /out/ 2>/dev/null
  as "opendmt3-server expose --off && opendmt3-server restart" > /out/expose-off.txt 2>&1
  python3 -c "import urllib.request; print(urllib.request.urlopen(\"http://127.0.0.1:4731/health\", timeout=5).read().decode())" > /out/admin-again.txt 2>&1
  grep -q "\"ok\":true" /out/admin-again.txt
  r=$?; step "expose --off: the admin pages on their own port again" $r
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
