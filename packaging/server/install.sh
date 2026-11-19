#!/bin/sh
# The openDMT3 server @VERSION@ on Linux or macOS with one command, without Docker:
#
#   curl -fsSL https://github.com/kanggu12/openDMT3/releases/download/v@VERSION@/opendmt3-server-@VERSION@-linux-installer.sh | sh
#   (on macOS the same file is opendmt3-server-@VERSION@-macos-installer.sh)
#
# It takes this release's server package (opendmt3-server-@VERSION@-linux-macos.zip), checked against the release's
# SHA-256 sums (opendmt3-@VERSION@-sha256sums.txt), into ~/.local/share/opendmt3-server (OPENDMT3_SERVER_DIR says
# where), with a Python environment of its own holding the site's libraries at the versions the server's image pins,
# and the official 7-Zip for the client data's archives; then the command opendmt3-server in ~/.local/bin. Run again,
# or a newer release's, it makes this version's Python environment first, beside the running server's; only then it
# stops the server it finds running, puts the new code in place and starts it again: the data stays (accounts, plays,
# backups, settings). A step that fails before the stop (a download, the libraries) leaves the running server as it
# was, and says so.
#
#   sh -s -- --uninstall      (after the pipe's sh: the server stopped, the program removed, the data kept)
#
# Needs curl, unzip or Python's own unzip, and Python 3.10 or newer with its venv module. Everything is in functions,
# called on the last line: a shell reads a script from a pipe as it goes, so nothing runs from a download cut short.
set -eu

VERSION=@VERSION@
REPO=kanggu12/openDMT3
# Where the release's files come from; OPENDMT3_SERVER_FILES names a folder of them instead (the install's test).
FILES=${OPENDMT3_SERVER_FILES:-https://github.com/$REPO/releases/download/v$VERSION}
# The site's libraries, the versions packaging/docker/Dockerfile pins.
LIBRARIES="starlette==0.47.3 jinja2==3.1.6 uvicorn==0.35.0 python-multipart==0.0.20 pillow==11.3.0"

say() { printf '%s\n' "$*"; }
die() { printf 'opendmt3-server install: %s\n' "$*" >&2; exit 1; }

# The official 7-Zip for this system, pinned by its hash (the release the server's image and the launcher bring).
sevenzip() {
  case "$(uname -s)-$(uname -m)" in
    Linux-x86_64) printf '%s %s\n' 7z2501-linux-x64.tar.xz 4ca3b7c6f2f67866b92622818b58233dc70367be2f36b498eb0bdeaaa44b53f4 ;;
    Linux-aarch64|Linux-arm64) printf '%s %s\n' 7z2501-linux-arm64.tar.xz 39c5140f02ce4436599303c59a149f654cb1bbc47cdc105a942120d747ae040d ;;
    Darwin-*) printf '%s %s\n' 7z2501-mac.tar.xz 26aa75bc262bb10bf0805617b95569c3035c2c590a99f7db55c7e9607b2685e0 ;;
    *) return 1 ;;
  esac
}

# A file of the release, into $2: copied from the folder OPENDMT3_SERVER_FILES names, or downloaded.
fetch() {
  case $FILES in
    http*) curl -fsSL --connect-timeout 30 --retry 2 -o "$2" "$FILES/$1" || die "could not download $FILES/$1" ;;
    *) cp "$FILES/$1" "$2" || die "no $1 in $FILES" ;;
  esac
}

# A SHA-256, by whichever program this system has.
sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

# The Python that runs the server: python3, 3.10 or newer, with venv.
python_found() {
  command -v python3 >/dev/null 2>&1 || return 1
  python3 -c 'import sys, venv, ensurepip; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null
}

# The command, opendmt3-server, for the environment $1: this install's Python, its code, its 7-Zip and its data folder
# (OPENDMT3_DATA still wins).
write_command() {
  cat > "$BIN/opendmt3-server" <<EOF
#!/bin/sh
# The openDMT3 server $VERSION, installed by opendmt3-server-$VERSION-linux-installer.sh (or -macos-) into $DIR.
export PYTHONPATH="$DIR/code"
export OPENDMT3_DATA="\${OPENDMT3_DATA:-$DIR/data}"
[ -x "$DIR/bin/7zz" ] && export OPENDMT3_7ZIP="$DIR/bin/7zz"
exec "$1/bin/python" -m opendmt3.server.standalone "\$@"
EOF
  chmod 0755 "$BIN/opendmt3-server"
}

uninstall() {
  if [ -x "$BIN/opendmt3-server" ]; then
    # The server stops by its own command, which started it.
    "$BIN/opendmt3-server" stop || true
  fi
  rm -rf "$DIR/code" "$DIR/venv" "$DIR"/venv-* "$DIR/bin"
  rm -f "$BIN/opendmt3-server"
  say "The openDMT3 server is removed. Its data stays in $DIR/data (delete that folder to remove it too)."
}

install() {
  command -v curl >/dev/null 2>&1 || die "curl is needed: install it, then run this again"
  python_found || die "Python 3.10 or newer with venv is needed: on Debian or Ubuntu, sudo apt install python3 python3-venv; on macOS, brew install python"
  work=$(mktemp -d "${TMPDIR:-/tmp}/opendmt3-server.XXXXXX")
  trap 'rm -rf "$work"' EXIT
  say "openDMT3 server $VERSION into $DIR"
  zip="opendmt3-server-$VERSION-linux-macos.zip"
  fetch "$zip" "$work/$zip"
  fetch "opendmt3-$VERSION-sha256sums.txt" "$work/sha256sums.txt"
  # The package as the release made it, or nothing at all.
  want=$(grep "  $zip\$" "$work/sha256sums.txt" | cut -d' ' -f1)
  [ -n "$want" ] || die "the release's SHA-256 sums name no $zip"
  [ "$(sha256 "$work/$zip")" = "$want" ] || die "$zip is not the release's (its SHA-256 differs): run this again"
  python3 -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' "$work/$zip" "$work/code"
  # The package's one top folder (opendmt3-server-<version>-linux-macos/), or its files at the top.
  top=$(find "$work/code" -mindepth 1 -maxdepth 1 -type d | head -n 1)
  [ -f "$top/opendmt3/server/standalone.py" ] || top=$work/code
  [ -f "$top/opendmt3/server/standalone.py" ] || die "$zip holds no server"
  if seven=$(sevenzip); then
    set -- $seven
    # From 7-Zip's own site (a folder of files given for a test may bring it, to need no network).
    if [ -f "$FILES/$1" ]; then cp "$FILES/$1" "$work/$1"
    else curl -fsSL --connect-timeout 30 -o "$work/$1" "https://www.7-zip.org/a/$1" || die "could not download 7-Zip"; fi
    [ "$(sha256 "$work/$1")" = "$2" ] || die "$1 is not the 7-Zip that was tested (its SHA-256 differs)"
    mkdir -p "$work/bin"
    # With the data filter where this Python has it (no link or device out of the archive).
    python3 -c 'import sys, tarfile; tarfile.open(sys.argv[1]).extract("7zz", sys.argv[2], **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))' "$work/$1" "$work/bin"
    chmod 0755 "$work/bin/7zz"
  else
    say "no 7-Zip of this project's for $(uname -s) $(uname -m): archives are read with a 7z on PATH, if there is one"
  fi
  mkdir -p "$DIR" "$BIN"
  # Whether a server runs now: it is stopped only once everything this version needs is ready, so a failure before
  # that leaves it running as it was.
  was_running=
  if [ -x "$BIN/opendmt3-server" ] && "$BIN/opendmt3-server" status >/dev/null 2>&1; then
    was_running=yes
  fi
  unchanged="nothing was changed"
  [ -z "$was_running" ] || unchanged="nothing was changed: the server runs as it was"
  # This version's own Python environment, made beside the one the running server uses (a release's libraries are
  # pinned with it): made and filled first, while that server still runs.
  venv="$DIR/venv-$VERSION"
  made_venv=
  if [ ! -x "$venv/bin/python" ]; then
    python3 -m venv "$venv" || { rm -rf "$venv"; die "the Python environment could not be made (python3 -m venv); $unchanged"; }
    made_venv=yes
  fi
  if ! "$venv/bin/python" -m pip install --quiet --disable-pip-version-check $LIBRARIES; then
    # An environment made for this version alone goes again; one the running server uses (this same version) stays.
    [ -z "$made_venv" ] || rm -rf "$venv"
    die "the site's libraries could not be installed (pip); $unchanged"
  fi
  # Now the running server stops, by its own command, and starts again at the end on the new version.
  if [ -n "$was_running" ]; then
    "$BIN/opendmt3-server" stop
  fi
  # The old code, 7-Zip and command kept aside until the new ones are in place: put back if that fails, and the old
  # server started again.
  rm -rf "$DIR/code.old" "$DIR/bin.old" "$BIN/opendmt3-server.old"
  [ ! -d "$DIR/code" ] || mv "$DIR/code" "$DIR/code.old"
  [ ! -d "$DIR/bin" ] || mv "$DIR/bin" "$DIR/bin.old"
  [ ! -f "$BIN/opendmt3-server" ] || cp "$BIN/opendmt3-server" "$BIN/opendmt3-server.old"
  if ! { mv "$top" "$DIR/code" && { [ ! -d "$work/bin" ] || mv "$work/bin" "$DIR/bin"; } && write_command "$venv"; }; then
    rm -rf "$DIR/code" "$DIR/bin"
    [ ! -d "$DIR/code.old" ] || mv "$DIR/code.old" "$DIR/code"
    [ ! -d "$DIR/bin.old" ] || mv "$DIR/bin.old" "$DIR/bin"
    [ ! -f "$BIN/opendmt3-server.old" ] || mv "$BIN/opendmt3-server.old" "$BIN/opendmt3-server"
    [ -z "$was_running" ] || "$BIN/opendmt3-server" start
    die "the new version could not be put in place in $DIR; the old one is back${was_running:+ and runs again}"
  fi
  rm -rf "$DIR/code.old" "$DIR/bin.old" "$BIN/opendmt3-server.old"
  # The environments of other versions (and the one before environments carried a version) are no one's now.
  for old in "$DIR/venv" "$DIR"/venv-*; do
    [ "$old" = "$venv" ] || [ ! -d "$old" ] || rm -rf "$old"
  done
  "$BIN/opendmt3-server" --version
  if [ -n "$was_running" ]; then
    "$BIN/opendmt3-server" start
  fi
  case ":$PATH:" in
    *":$BIN:"*) cmd=opendmt3-server ;;
    *) cmd="$BIN/opendmt3-server"; say "($BIN is not on PATH: add it, or type the whole path)" ;;
  esac
  say ""
  say "Next:"
  say "  $cmd setup --admin BOSS        the owner's account, with the admin pages (its password printed)"
  say "  $cmd start                     the server, in the background"
  say "  $cmd setup --game PATH         the song list from your client data (a folder or an archive)"
  say "  $cmd firewall                  the commands that open its ports"
  say "  $cmd --help                    every command"
  say "The admin pages: http://127.0.0.1:4731/ on this PC ($cmd setup --admin-host 0.0.0.0 opens them to the network)."
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
