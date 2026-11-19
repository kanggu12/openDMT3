#!/bin/sh
# One of the server's packages for Linux and macOS (packaging/server/bundle.sh) on the system it is made for, with
# nothing else of the machine's (no Python, no curl, no 7-Zip): CI's package job runs it on each system and processor,
# Linux's in a bare Debian 10. In a folder of its own:
#   1. unpacked: one folder of the package's name, its program;
#   2. ./opendmt3-server --version is this tree's version; setup makes the owner's account; start runs it in the
#      background; /health and the admin pages' /health answer (read by the package's own Python); status says it
#      runs; the package's 7-Zip makes and lists an archive; repair finds the package's files as they were made; stop;
#   3. the one-line install from a folder of the release's files (this package, its SHA-256 sums, the installer with
#      the version put in): installed, the command answers with the version, started, installed again while it runs
#      (stopped, put in place, running again, the data kept), and --uninstall, the data kept.
# Each step says PASS or FAIL; the exit code is the number that failed.
#
#   sh tests/e2e/package/check.sh PACKAGE.tar.gz      (from the repository's top)
#
# The ports are the server's own (4725, 4730, 4731): a runner has them free.
set -u
ARCHIVE=${1:?usage: sh tests/e2e/package/check.sh PACKAGE.tar.gz}
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' opendmt3/__init__.py)
NAME=$(basename "$ARCHIVE" .tar.gz)
failed=0
step() { if [ "$2" = 0 ]; then echo "PASS $1"; else echo "FAIL $1"; failed=$((failed + 1)); fi; }
# A SHA-256, by whichever program this system has (sha256sum on Linux, shasum on macOS).
sha256() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
WORK=$(mktemp -d "${TMPDIR:-/tmp}/opendmt3-package.XXXXXX")
trap 'rm -rf "$WORK"' EXIT

# ---- 1. unpacked
tar -xzf "$ARCHIVE" -C "$WORK"
[ "$(ls "$WORK")" = "$NAME" ] && [ -x "$WORK/$NAME/opendmt3-server" ]
step "one folder of the package's name, its program in it" $?
P="$WORK/$NAME"
# The package's own Python reads the pages: the machine has none of its own to count on.
get() { "$P/lib/python/bin/python3" -I -c "import sys, urllib.request; print(urllib.request.urlopen(sys.argv[1], timeout=5).read().decode())" "$1"; }

# ---- 2. the package run as it is
said=$("$P/opendmt3-server" --version 2>&1)
[ "$said" = "openDMT3 server $VERSION" ]
step "./opendmt3-server --version: $said" $?
"$P/opendmt3-server" setup --admin BOSS --password pass1234 > "$WORK/setup.txt" 2>&1 && grep -q "made BOSS" "$WORK/setup.txt"
step "setup makes the owner's account" $?
"$P/opendmt3-server" start > "$WORK/start.txt" 2>&1
step "start runs it in the background" $?
get http://127.0.0.1:4730/health > "$WORK/health.txt" 2>&1
grep -q "\"version\":\"$VERSION\"" "$WORK/health.txt"
step "/health: $(cat "$WORK/health.txt")" $?
get http://127.0.0.1:4731/health > "$WORK/admin.txt" 2>&1
grep -q '"ok":true' "$WORK/admin.txt"
step "the admin pages' /health: $(cat "$WORK/admin.txt")" $?
"$P/opendmt3-server" status > "$WORK/status.txt" 2>&1 && grep -q "Health: ok" "$WORK/status.txt"
step "status says it runs" $?
# The data folder beside the program, as the Windows package keeps it.
[ -f "$P/data/openDMT3.sqlite" ]
step "the data folder beside the program" $?
(cd "$WORK" && "$P/lib/7-zip/7zz" a -bd made-up.7z "$P/README.txt" > 7z.txt 2>&1 && "$P/lib/7-zip/7zz" l made-up.7z >> 7z.txt 2>&1) \
  && grep -q "README.txt" "$WORK/7z.txt"
step "the package's 7-Zip makes and lists an archive" $?
"$P/opendmt3-server" repair > "$WORK/repair.txt" 2>&1 && grep -q "the package's files are as they were made" "$WORK/repair.txt"
step "repair finds the package's files as they were made" $?
"$P/opendmt3-server" stop > "$WORK/stop.txt" 2>&1 && grep -q "The server stopped." "$WORK/stop.txt"
step "stop" $?

# ---- 3. the one-line install from a folder of the release's files
FILES="$WORK/files"
mkdir -p "$FILES"
cp "$ARCHIVE" "$FILES/"
printf '%s  %s\n' "$(sha256 "$ARCHIVE")" "$NAME.tar.gz" > "$FILES/opendmt3-$VERSION-sha256sums.txt"
sed "s/@VERSION@/$VERSION/g" packaging/server/install.sh > "$FILES/installer.sh"
# Into the work folder, and as root where the job runs as root (a container's): the installer asks for the user who
# runs the server otherwise.
export OPENDMT3_SERVER_FILES="$FILES" OPENDMT3_SERVER_DIR="$WORK/installed" OPENDMT3_SERVER_BIN="$WORK/bin"
export OPENDMT3_SERVER_AS_ROOT=1
sh "$FILES/installer.sh" > "$WORK/install.txt" 2>&1
step "the one-line install from a folder of its files" $?
said=$("$WORK/bin/opendmt3-server" --version 2>&1)
[ "$said" = "openDMT3 server $VERSION" ]
step "the command it put in place: $said" $?
"$WORK/bin/opendmt3-server" setup --admin BOSS --password pass1234 > /dev/null 2>&1 && "$WORK/bin/opendmt3-server" start > /dev/null 2>&1
step "the installed server set up and started" $?
sh "$FILES/installer.sh" > "$WORK/again.txt" 2>&1 && "$WORK/bin/opendmt3-server" status > "$WORK/status-again.txt" 2>&1 \
  && grep -q "Health: ok" "$WORK/status-again.txt" && [ -f "$WORK/installed/data/openDMT3.sqlite" ]
step "the install again while it runs: stopped, put in place, running again, the data kept" $?
sh "$FILES/installer.sh" --uninstall > "$WORK/uninstall.txt" 2>&1 && [ ! -e "$WORK/bin/opendmt3-server" ] \
  && [ -f "$WORK/installed/data/openDMT3.sqlite" ] && ! get http://127.0.0.1:4730/health > /dev/null 2>&1
step "--uninstall: stopped and removed, the data kept" $?
if [ "$failed" -ne 0 ]; then
  # What each part said, for the run's log.
  for f in "$WORK"/*.txt; do echo "== $(basename "$f")"; tail -n 20 "$f"; done
fi
echo "failed: $failed"
exit "$failed"
