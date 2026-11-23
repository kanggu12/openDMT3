#!/bin/sh
# The openDMT3 server @VERSION@ on Linux or macOS with one command, without Docker or Python:
#
#   curl -fsSL https://github.com/kanggu12/openDMT3/releases/download/v@VERSION@/opendmt3-server-@VERSION@-linux-installer.sh | sh
#   (on macOS the same file is opendmt3-server-@VERSION@-macos-installer.sh; the same script, for the system it runs on)
#
# It takes this release's server package for this machine (opendmt3-server-@VERSION@-<system>-<processor>.tar.gz:
# linux or macos, x64 or arm64), checked against the release's SHA-256 sums (opendmt3-@VERSION@-sha256sums.txt), into
# ~/.local/share/opendmt3-server (OPENDMT3_SERVER_DIR says where), and puts the command opendmt3-server in
# ~/.local/bin (OPENDMT3_SERVER_BIN). The package brings its own Python, the site's libraries, the official 7-Zip and
# the launcher's installer for the Download page; the data (accounts, plays, backups, settings) is in the data folder
# beside it, which every version uses. Run again, or a newer release's, it unpacks this version's package first and
# starts it once (--version), while the running server goes on; only then it stops the server it finds running, puts
# the new package in place and starts it again. A step that fails before the stop (a download, a checksum, a package
# that does not start on this machine) leaves the running server as it was, and says so. An install made by an older
# release's script (with a Python environment of its own) is taken over the same way, its data kept. A first install
# (no command there before) ends with the server running: the owner's account asked for at the terminal when there is
# one (the script itself comes through curl's pipe, so the questions go to /dev/tty), none made without one (setup then
# says the one command that makes it), then the server started, its banner naming the site's and the admin pages'
# addresses.
#
#   sh -s -- --uninstall      (after the pipe's sh: the server stopped, the program removed, the data kept)
#
# Needs curl, tar and gzip; on Linux, the GNU C library (glibc 2.28 or newer: Debian 10, Ubuntu 20.04, RHEL 8 and
# newer). Everything is in functions, called on the last line: a shell reads a script from a pipe as it goes, so
# nothing runs from a download cut short.
set -eu

VERSION=@VERSION@
REPO=kanggu12/openDMT3
# Where the release's files come from; OPENDMT3_SERVER_FILES names a folder of them instead (the install's tests).
FILES=${OPENDMT3_SERVER_FILES:-https://github.com/$REPO/releases/download/v$VERSION}

say() { printf '%s\n' "$*"; }
die() { printf 'opendmt3-server install: %s\n' "$*" >&2; exit 1; }

# This machine as the release's files name it: linux or macos, then x64 (what uname calls x86_64) or arm64 (Linux's
# aarch64 too). Anything else has no package.
target() {
  case "$(uname -s)" in
    Linux) system=linux ;;
    Darwin) system=macos ;;
    *) die "no package for $(uname -s): on Windows, the release's opendmt3-server-$VERSION-windows-installer.ps1" ;;
  esac
  case "$(uname -m)" in
    x86_64 | amd64) processor=x64 ;;
    aarch64 | arm64) processor=arm64 ;;
    *) die "no package for $(uname -m): the server runs from a copy of the repository with Python there" \
         "(docs/server.md, With Python)" ;;
  esac
  if [ "$system" = linux ] && ! getconf GNU_LIBC_VERSION >/dev/null 2>&1; then
    # musl (Alpine) and the like: the package's Python is built for the GNU C library.
    die "the package needs the GNU C library (glibc), which this Linux does not have: the Docker image runs here" \
        "(docs/server.md, With Docker)"
  fi
  printf '%s-%s\n' "$system" "$processor"
}

# A file of the release, into $2: copied from the folder OPENDMT3_SERVER_FILES names, or downloaded from GitHub by
# HTTPS only (redirects too, TLS 1.2 or newer), so no downgrade on the way can hand over another package with its own
# sums.
fetch() {
  case $FILES in
    http*) curl --proto =https --proto-redir =https --tlsv1.2 -fsSL --connect-timeout 30 --retry 2 -o "$2" "$FILES/$1" \
             || die "could not download $FILES/$1" ;;
    *) cp "$FILES/$1" "$2" || die "no $1 in $FILES" ;;
  esac
}

# A SHA-256, by whichever program this system has (sha256sum on Linux, shasum on macOS).
sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

# The command, opendmt3-server, for the package in $1: the package's own program, with the install's data folder
# (OPENDMT3_DATA still wins), so every version finds the same data.
write_command() {
  cat > "$BIN/opendmt3-server.new" <<EOF
#!/bin/sh
# The openDMT3 server $VERSION, installed by opendmt3-server-$VERSION-$system-installer.sh into $DIR.
OPENDMT3_DATA="\${OPENDMT3_DATA:-$DIR/data}"
export OPENDMT3_DATA
exec "$1/opendmt3-server" "\$@"
EOF
  chmod 0755 "$BIN/opendmt3-server.new"
  # Renamed into place: the command is whole at every moment, the old or the new.
  mv "$BIN/opendmt3-server.new" "$BIN/opendmt3-server"
}

# What an older release's script left beside the data (its code, its Python environments, its 7-Zip), and the
# packages of other versions: no one's once this version is in place.
tidy() {
  for old in "$DIR/code" "$DIR/code.old" "$DIR/venv" "$DIR"/venv-* "$DIR/bin" "$DIR/bin.old" \
             "$DIR"/opendmt3-server-*; do
    [ "$old" = "$DIR/$name" ] || [ ! -e "$old" ] || rm -rf "$old"
  done
  rm -rf "$DIR/.incoming" "$DIR/.replaced"
}

uninstall() {
  if [ -x "$BIN/opendmt3-server" ]; then
    # The server stops by its own command, which started it.
    "$BIN/opendmt3-server" stop || true
  fi
  name=
  tidy
  rm -f "$BIN/opendmt3-server" "$BIN/opendmt3-server.old"
  say "The openDMT3 server is removed. Its data stays in $DIR/data (delete that folder to remove it too)."
}

install() {
  # curl for the release's files (a folder of them needs none).
  command -v curl >/dev/null 2>&1 || [ "${FILES#http}" = "$FILES" ] \
    || die "curl is needed: install it, then run this again"
  command -v tar >/dev/null 2>&1 || die "tar is needed: install it, then run this again"
  key=$(target)
  system=${key%-*}
  name="opendmt3-server-$VERSION-$key"
  archive="$name.tar.gz"
  work=$(mktemp -d "${TMPDIR:-/tmp}/opendmt3-server.XXXXXX")
  trap 'rm -rf "$work"' EXIT
  say "openDMT3 server $VERSION for $key into $DIR"
  fetch "$archive" "$work/$archive"
  fetch "opendmt3-$VERSION-sha256sums.txt" "$work/sha256sums.txt"
  # The package as the release made it, or nothing at all.
  want=$(grep "  $archive\$" "$work/sha256sums.txt" | cut -d' ' -f1)
  [ -n "$want" ] || die "the release's SHA-256 sums name no $archive"
  [ "$(sha256 "$work/$archive")" = "$want" ] \
    || die "$archive is not the release's (its SHA-256 differs): run this again"
  mkdir -p "$DIR" "$BIN"
  # A first install: no command of any release's here yet (an older release's own counts as one), so the end sets the
  # server up and starts it. An install again, or an update, leaves a stopped server stopped.
  first=
  [ -e "$BIN/opendmt3-server" ] || first=yes
  # Whether a server runs now: it is stopped only once this version is unpacked and has started here, so a failure
  # before that leaves it running as it was. Its status says 0 when it runs and answers, 1 when it runs and does not
  # answer (yet), 3 when none runs.
  was_running=
  if [ -x "$BIN/opendmt3-server" ]; then
    code=0
    "$BIN/opendmt3-server" status >/dev/null 2>&1 || code=$?
    case $code in 0 | 1) was_running=yes ;; esac
  fi
  unchanged="nothing was changed"
  [ -z "$was_running" ] || unchanged="nothing was changed: the server runs as it was"
  # This version's package unpacked beside the installed ones (on the same disk, so putting it in place is a rename),
  # then started once: a package this machine cannot run stops here.
  rm -rf "$DIR/.incoming" && mkdir -p "$DIR/.incoming"
  tar -xzf "$work/$archive" -C "$DIR/.incoming" \
    || { rm -rf "$DIR/.incoming"; die "$archive could not be unpacked; $unchanged"; }
  new="$DIR/.incoming/$name"
  [ -x "$new/opendmt3-server" ] \
    || { rm -rf "$DIR/.incoming"; die "$archive holds no $name/opendmt3-server; $unchanged"; }
  # It must answer with its own version: anything else (a loader's error, nothing at all) is a package this machine
  # does not run.
  started=$("$new/opendmt3-server" --version 2>&1) || true
  if [ "$started" != "openDMT3 server $VERSION" ]; then
    rm -rf "$DIR/.incoming"
    die "the package does not start on this machine (${started:-it said nothing}); $unchanged"
  fi
  # Now the running server stops, by its own command, and starts again at the end on the new version; one that does
  # not stop is left as it is, with nothing changed.
  if [ -n "$was_running" ] && ! "$BIN/opendmt3-server" stop; then
    rm -rf "$DIR/.incoming"
    die "the running server did not stop ($BIN/opendmt3-server stop); $unchanged"
  fi
  # The same version installed before (an install run again) is set aside, and the command kept, until the new ones
  # are in place: put back if that fails, and the old server started again.
  rm -rf "$DIR/.replaced" && mkdir -p "$DIR/.replaced"
  [ ! -d "$DIR/$name" ] || mv "$DIR/$name" "$DIR/.replaced/$name"
  rm -f "$BIN/opendmt3-server.old"
  [ ! -f "$BIN/opendmt3-server" ] || cp "$BIN/opendmt3-server" "$BIN/opendmt3-server.old"
  if ! { mv "$new" "$DIR/$name" && write_command "$DIR/$name"; }; then
    rm -rf "$DIR/$name"
    [ ! -d "$DIR/.replaced/$name" ] || mv "$DIR/.replaced/$name" "$DIR/$name"
    [ ! -f "$BIN/opendmt3-server.old" ] || mv "$BIN/opendmt3-server.old" "$BIN/opendmt3-server"
    [ -z "$was_running" ] || "$BIN/opendmt3-server" start
    die "the new version could not be put in place in $DIR; the old one is back${was_running:+ and runs again}"
  fi
  rm -f "$BIN/opendmt3-server.old"
  tidy
  "$BIN/opendmt3-server" --version
  # The command as the person types it next: by name when its folder is on PATH, else by its whole path.
  case ":$PATH:" in
    *":$BIN:"*) cmd=opendmt3-server ;;
    *) cmd="$BIN/opendmt3-server" ;;
  esac
  started=
  if [ -n "$was_running" ]; then
    "$BIN/opendmt3-server" start
    started=yes
  elif [ -n "$first" ]; then
    # The owner's account before the first start, asked at the terminal when there is one: this script's own input
    # is curl's pipe, so the questions read /dev/tty, and setup asks only when its output is a terminal too. With none
    # (a script, a CI job), setup makes no account and says the one command that makes it. Data kept from an earlier
    # install that has accounts is asked nothing.
    if [ -t 1 ] && (exec </dev/tty) 2>/dev/null; then
      "$BIN/opendmt3-server" setup </dev/tty || say "(no account made: $cmd setup --admin BOSS makes it)"
    else
      "$BIN/opendmt3-server" setup </dev/null || true
    fi
    # Started in the background; its banner names the players' address, this PC's, the admin pages' and the game's
    # port (and, with no account yet, the page that makes it). A start that fails says why, and the install stands.
    if "$BIN/opendmt3-server" start; then
      started=yes
    else
      say "The server is installed, not started: $cmd start starts it once that is fixed."
    fi
  fi
  say ""
  [ "$cmd" = opendmt3-server ] || say "($BIN is not on PATH: add it, or type the whole path)"
  say "Next:"
  # A server this install did not start (one stopped before an update, or a start that failed).
  [ -n "$started" ] || say "  $cmd start                       the server, in the background"
  say "  $cmd setup --game PATH           the song list from your client data (a folder or an archive)"
  say "  $cmd firewall                    the commands that open its ports"
  say "  $cmd --help                      every command"
  say "  $cmd setup --admin-host 0.0.0.0  the admin pages for the other PCs of the network too"
  if [ -n "$started" ]; then
    # Last, the site's and the admin pages' addresses in the server's own words (its ports and reach as kept).
    "$BIN/opendmt3-server" status 2>/dev/null | sed -n -e '/^Players: /p' -e '/^The admin pages: /p'
  fi
}

main() {
  DIR=${OPENDMT3_SERVER_DIR:-$HOME/.local/share/opendmt3-server}
  BIN=${OPENDMT3_SERVER_BIN:-$HOME/.local/bin}
  [ "$(id -u)" -ne 0 ] || [ -n "${OPENDMT3_SERVER_AS_ROOT:-}" ] || die "run this as the user who runs the server, not as root"
  case "${1:-}" in
    --uninstall) uninstall ;;
    "") install ;;
    *) die "usage: sh $0 [--uninstall]" ;;
  esac
}

main "$@"
