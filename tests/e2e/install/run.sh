#!/bin/bash
# The one-line install (packaging/server/install.sh) as a server owner runs it on Linux, in containers, as a user of
# its own, from a folder of release files: this tree's server package for Linux x64 (packaging/server/bundle.sh, as the
# release makes it), the SHA-256 sums and the installer with this version put in.
#   1. In a bare Debian 10 (glibc 2.28, no Python, no curl) with no network: the install from a script (no terminal:
#      no account made and its one command said, the server started, the site's and the admin pages' addresses said
#      last), the command it puts on PATH (--version, setup, start finding it running, /health and the admin pages',
#      status), the installer again while the server runs (an update: stopped, put in place, started again), a later
#      release whose package is not the release's (refused by its SHA-256) and one whose package does not start there
#      (refused at its --version), each leaving the running server as it was, then --uninstall, the data still there;
#      then a first install at a terminal that `script` gives it (the owner's account asked for there and made, the
#      server started with it).
#   2. In python:3.12-slim-bookworm, with the network for an older release's own download: 0.4.1's one line from its
#      release (the server with a Python environment of its own) and a first account, then this version's one line
#      over that install while it runs (the package in its place, the old code and environments gone, the account
#      kept); expose --admin-public with Caddy beside it (the release Caddy ./dmt3 runs, copied out of its image: the
#      site and the admin pages over HTTPS at the name), then without it and --off; then --uninstall.
# Each step says PASS or FAIL; the exit code is the number that failed.
#
#   tests/e2e/install/run.sh OUT_DIR
#
# OPENDMT3_E2E_NAME names the containers (two runs at once name their own); OPENDMT3_BUNDLE_CACHE the folder the
# packages' pinned files are kept in between runs (default: _work/cache/server-packages in this tree).
set -u
OUT=$(realpath -m "${1:?usage: tests/e2e/install/run.sh OUT_DIR}")
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$REPO/opendmt3/__init__.py")
C=${OPENDMT3_E2E_NAME:-odt3-srv}-install
# The bare Debian 10 CI runs the Linux packages in, and the image the earlier release's install ran in.
DEBIAN="debian:buster-slim@sha256:bb3dc79fddbca7e8903248ab916bb775c96ec61014b3d02b4f06043b604726dc"
PYTHON_IMAGE="python:3.12-slim-bookworm"
# The release whose one line the second part takes over: one that installed the server with a Python of its own.
EARLIER=0.4.1
rm -rf "$OUT" && mkdir -p "$OUT/files"
docker rm -f "$C" "$C-old" >/dev/null 2>&1

# ---- the release's files, as packaging/release.sh names them
PACKAGE=opendmt3-server-$VERSION-linux-x64
OPENDMT3_BUNDLE_CACHE=${OPENDMT3_BUNDLE_CACHE:-$REPO/_work/cache/server-packages} \
  "$REPO/packaging/server/bundle.sh" "$OUT/packages" linux-x64 > "$OUT/packages.txt" 2>&1 \
  || { tail -n 20 "$OUT/packages.txt"; echo "FAIL the server package for the test"; exit 1; }
cp "$OUT/packages/$PACKAGE.tar.gz" "$OUT/files/"
(cd "$OUT/files" && sha256sum "$PACKAGE.tar.gz" > "opendmt3-$VERSION-sha256sums.txt")
sed "s/@VERSION@/$VERSION/g" "$REPO/packaging/server/install.sh" > "$OUT/files/opendmt3-server-$VERSION-linux-installer.sh"
# Two later releases that must leave the running server as it was: one whose sums name another package (a download
# that is not the release's), one whose package does not start on this machine (its Python cut to nothing, its sums
# its own). Each is this package under the later version's name, its one folder renamed to match.
later() {
  local version=$1 how=$2 stage="$OUT/later-$1"
  rm -rf "$stage" && mkdir -p "$stage"
  tar -xzf "$OUT/files/$PACKAGE.tar.gz" -C "$stage"
  mv "$stage/$PACKAGE" "$stage/opendmt3-server-$version-linux-x64"
  # The package's Python in place of one that cannot start on this machine, as a loader's error says it.
  if [ "$how" = broken ]; then
    printf '#!/bin/sh\necho "python3.12: cannot run on this machine (made up)" >&2\nexit 127\n' \
      > "$stage/opendmt3-server-$version-linux-x64/lib/python/bin/python3.12"
  fi
  tar -czf "$OUT/files/opendmt3-server-$version-linux-x64.tar.gz" -C "$stage" "opendmt3-server-$version-linux-x64"
  rm -rf "$stage"
  if [ "$how" = mismatched ]; then
    printf '%064d  %s\n' 0 "opendmt3-server-$version-linux-x64.tar.gz" > "$OUT/files/opendmt3-$version-sha256sums.txt"
  else
    (cd "$OUT/files" && sha256sum "opendmt3-server-$version-linux-x64.tar.gz" > "opendmt3-$version-sha256sums.txt")
  fi
  sed "s/@VERSION@/$version/g" "$REPO/packaging/server/install.sh" > "$OUT/files/opendmt3-server-$version-linux-installer.sh"
}
MISMATCHED=${VERSION}8
BROKEN=${VERSION}9
later "$MISMATCHED" mismatched
later "$BROKEN" broken

# ---- 1. a bare Debian 10, no network
docker run --rm --name "$C" --network none -v "$OUT/files:/files:ro" -v "$OUT:/out" -e VERSION="$VERSION" \
  -e PACKAGE="$PACKAGE" -e MISMATCHED="$MISMATCHED" -e BROKEN="$BROKEN" "$DEBIAN" bash -c '
  set -u
  failed=0
  step() { if [ "$2" = 0 ]; then echo "PASS $1"; else echo "FAIL $1"; failed=$((failed + 1)); fi; }
  useradd -m owner
  as() { su owner -c "export PATH=/home/owner/.local/bin:\$PATH OPENDMT3_SERVER_FILES=/files; $1"; }
  # The package'"'"'s own Python reads the pages (this machine has none of its own).
  get() { /home/owner/.local/share/opendmt3-server/$PACKAGE/lib/python/bin/python3 -I -c "import sys, urllib.request; print(urllib.request.urlopen(sys.argv[1], timeout=5).read().decode())" "$1"; }
  ! command -v python3 >/dev/null 2>&1 && ! command -v curl >/dev/null 2>&1
  r=$?; step "this machine has no Python and no curl of its own" $r
  as "cat /files/opendmt3-server-$VERSION-linux-installer.sh | sh" > /out/install.txt 2>&1
  r=$?; step "the one line installs the server" $r
  # A first install from a script, with no terminal: no account made and the one command that makes it said, the
  # server started, and the site and the admin pages named last.
  as "opendmt3-server status" > /out/first-status.txt 2>&1
  r1=$?
  [ $r1 = 0 ] && grep -q "setup --admin ID makes it" /out/install.txt && ! grep -q "^made " /out/install.txt \
    && grep -q "^Players: http" /out/install.txt && grep -q "^The admin pages: http://127.0.0.1:4731/" /out/install.txt
  r=$?; step "a first install with no terminal: no account made, its command said, the server started, its addresses said" $r
  as "opendmt3-server --version" > /out/version.txt 2>&1; grep -q "openDMT3 server $VERSION" /out/version.txt
  r=$?; step "opendmt3-server --version: $(cat /out/version.txt)" $r
  [ -x /home/owner/.local/share/opendmt3-server/$PACKAGE/lib/7-zip/7zz ] \
    && [ -f /home/owner/.local/share/opendmt3-server/$PACKAGE/licenses/NOTICES.txt ]
  r=$?; step "the package in its place, with the official 7-Zip and its notices" $r
  as "opendmt3-server setup --admin BOSS --password pass1234 && opendmt3-server start" > /out/start.txt 2>&1
  r=$?; grep -q "made BOSS" /out/start.txt && grep -q "already runs" /out/start.txt || r=1
  step "setup makes the owner'"'"'s account, and start finds the server running" $r
  get http://127.0.0.1:4730/health > /out/health.txt 2>&1
  grep -q "\"ok\":true" /out/health.txt && grep -q "\"version\":\"$VERSION\"" /out/health.txt
  r=$?; step "/health: $(cat /out/health.txt)" $r
  # The admin pages, a site of their own, on this PC (their own port and /health).
  get http://127.0.0.1:4731/health > /out/admin-health.txt 2>&1
  grep -q "\"ok\":true" /out/admin-health.txt
  r=$?; step "the admin pages answer on this PC: $(cat /out/admin-health.txt)" $r
  # The data beside the packages, not in one: the next version finds it.
  [ -f /home/owner/.local/share/opendmt3-server/data/openDMT3.sqlite ] && [ ! -e /home/owner/.local/share/opendmt3-server/$PACKAGE/data ]
  r=$?; step "the data in the install folder'"'"'s data/, outside the package" $r
  as "cat /files/opendmt3-server-$VERSION-linux-installer.sh | sh" > /out/update.txt 2>&1
  r1=$?
  as "opendmt3-server status" > /out/status.txt 2>&1
  r2=$?
  [ $r1 = 0 ] && [ $r2 = 0 ] && grep -q "Health: ok" /out/status.txt
  r=$?; step "the installer again while it runs: stopped, put in place, running again" $r
  for later in "$MISMATCHED:is not the release" "$BROKEN:does not start on this machine"; do
    version=${later%%:*}; said=${later#*:}
    as "cat /files/opendmt3-server-$version-linux-installer.sh | sh" > /out/later-$version.txt 2>&1
    r1=$?
    as "opendmt3-server status" > /out/status-$version.txt 2>&1
    r2=$?
    as "opendmt3-server --version" > /out/version-$version.txt 2>&1
    [ $r1 != 0 ] && [ $r2 = 0 ] && grep -q "openDMT3 server $VERSION" /out/version-$version.txt \
      && grep -q "$said" /out/later-$version.txt && ! ls -d /home/owner/.local/share/opendmt3-server/*$version* 2>/dev/null
    r=$?; step "a later release whose package $said: refused, the server still running $VERSION ($(tail -n 1 /out/later-$version.txt))" $r
  done
  as "sh /files/opendmt3-server-$VERSION-linux-installer.sh --uninstall" > /out/uninstall.txt 2>&1
  [ ! -e /home/owner/.local/bin/opendmt3-server ] && [ -f /home/owner/.local/share/opendmt3-server/data/openDMT3.sqlite ] \
    && [ -z "$(ls -A /home/owner/.local/share/opendmt3-server | grep -v "^data$")" ]
  r=$?; step "--uninstall: stopped and removed, the data kept" $r
  # A first install at a terminal, which script gives it as a person'"'"'s window would: the owner'"'"'s account asked for
  # there and made, then the server started with it. Each answer goes in once its question is on the screen (the
  # password'"'"'s question empties whatever was typed before it), through a pipe that stays open until the end.
  useradd -m owner2
  mkfifo /tmp/answers && chmod 0666 /tmp/answers
  su owner2 -c "export OPENDMT3_SERVER_FILES=/files; timeout 300 script -qfec \"cat /files/opendmt3-server-$VERSION-linux-installer.sh | sh\" /tmp/tty.txt" \
    < /tmp/answers > /out/tty-run.txt 2>&1 &
  driver=$!
  exec 3>/tmp/answers
  answer() { for i in $(seq 600); do grep -q "$1" /tmp/tty.txt 2>/dev/null && { printf "%s\n" "$2" >&3; return 0; }; sleep 0.1; done; return 1; }
  answer "ID \[BOSS\]" NOVA && answer "password (6 to 16" pass1234 && answer "the same password again" pass1234
  asked=$?
  wait $driver
  ran=$?
  exec 3>&-
  cp /tmp/tty.txt /out/tty.txt 2>/dev/null
  su owner2 -c "/home/owner2/.local/bin/opendmt3-server status" > /out/tty-status.txt 2>&1
  r1=$?
  [ $asked = 0 ] && [ $ran = 0 ] && [ $r1 = 0 ] && grep -q "made NOVA" /tmp/tty.txt && ! grep -q "First start: open" /tmp/tty.txt \
    && grep -q "^The admin pages: http://127.0.0.1:4731/" /tmp/tty.txt
  r=$?; step "a first install at a terminal: the owner'"'"'s account asked for there and made, the server started with it" $r
  su owner2 -c "sh /files/opendmt3-server-$VERSION-linux-installer.sh --uninstall" > /out/uninstall-tty.txt 2>&1
  echo "failed: $failed"
  exit $failed
'
first=$?

# ---- 2. an install the earlier release made, taken over; expose with Caddy beside it
# The Caddy ./dmt3 runs (the exact release its edge.yaml names), its program copied out of that image for the server's
# own program to run beside it, as an owner without Docker runs Caddy's own build for Linux.
CADDY_IMAGE=$(sed -n 's/^ *image: \(caddy:[^ ]*\)$/\1/p' "$REPO/packaging/docker/edge.yaml")
docker rm -f "$C-caddy" >/dev/null 2>&1
{ docker create --name "$C-caddy" "$CADDY_IMAGE" >/dev/null && docker cp "$C-caddy:/usr/bin/caddy" "$OUT/files/caddy" \
    >/dev/null; } || { docker rm -f "$C-caddy" >/dev/null 2>&1; echo "FAIL Caddy for the test ($CADDY_IMAGE)"; exit 1; }
docker rm -f "$C-caddy" >/dev/null 2>&1
docker run --rm --name "$C-old" -v "$OUT/files:/files:ro" -v "$OUT:/out" -e VERSION="$VERSION" -e EARLIER="$EARLIER" \
  -e PACKAGE="$PACKAGE" "$PYTHON_IMAGE" bash -c '
  set -u
  failed=0
  step() { if [ "$2" = 0 ]; then echo "PASS $1"; else echo "FAIL $1"; failed=$((failed + 1)); fi; }
  apt-get update -qq >/dev/null && apt-get install -y -qq --no-install-recommends curl >/dev/null 2>&1
  useradd -m owner
  as() { su owner -c "export PATH=/home/owner/.local/bin:\$PATH; $1"; }
  # The earlier release'"'"'s one line, as its guide gave it: from its release on GitHub, its libraries from PyPI.
  as "curl -fsSL https://github.com/kanggu12/openDMT3/releases/download/v$EARLIER/opendmt3-server-$EARLIER-linux-installer.sh | sh" > /out/old-install.txt 2>&1
  r1=$?
  as "opendmt3-server setup --admin BOSS --password pass1234 && opendmt3-server start" > /out/old-start.txt 2>&1
  r2=$?
  [ $r1 = 0 ] && [ $r2 = 0 ] && [ -d /home/owner/.local/share/opendmt3-server/code ]
  r=$?; step "$EARLIER'"'"'s one line installs its server with a Python of its own, and it runs" $r
  as "OPENDMT3_SERVER_FILES=/files; export OPENDMT3_SERVER_FILES; cat /files/opendmt3-server-$VERSION-linux-installer.sh | sh" > /out/take-over.txt 2>&1
  r1=$?
  as "opendmt3-server --version" > /out/version-over.txt 2>&1
  as "opendmt3-server status" > /out/status-over.txt 2>&1
  r2=$?
  D=/home/owner/.local/share/opendmt3-server
  [ $r1 = 0 ] && [ $r2 = 0 ] && grep -q "openDMT3 server $VERSION" /out/version-over.txt && [ -x "$D/$PACKAGE/opendmt3-server" ] \
    && [ ! -e "$D/code" ] && ! ls -d "$D"/venv* 2>/dev/null && [ ! -e "$D/bin" ]
  r=$?; step "this version'"'"'s one line over it while it runs: the package in place, its code and environments gone, running $VERSION" $r
  as "opendmt3-server setup --admin OTHER" > /out/first-kept.txt 2>&1
  grep -q "no first account is made" /out/first-kept.txt
  r=$?; step "the account the earlier release made is kept: $(tail -n 1 /out/first-kept.txt)" $r
  # expose --admin-public with Caddy beside it, as the owner runs it: the site and the admin pages over HTTPS at the
  # name, through Caddy (its own authority, whose root it keeps in the owner home), the admin pages behind it at the
  # next port on this PC alone; then without it nothing of the admin site at the admin port, and --off.
  D=$D/data
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
  as "sh /files/opendmt3-server-$VERSION-linux-installer.sh --uninstall" > /out/uninstall-over.txt 2>&1
  [ ! -e /home/owner/.local/bin/opendmt3-server ] && [ -f /home/owner/.local/share/opendmt3-server/data/openDMT3.sqlite ] \
    && ! python3 -c "import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:4730/health\", timeout=3)" 2>/dev/null
  r=$?; step "--uninstall: stopped and removed, the data kept" $r
  echo "failed: $failed"
  exit $failed
'
second=$?
echo "failed in all: $((first + second))"
exit $((first + second))
