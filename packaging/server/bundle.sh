#!/bin/bash
# Build the server's packages for Linux and macOS on Linux: opendmt3-server-<version>-<system>-<processor>.tar.gz for
# linux-x64, linux-arm64, macos-x64 and macos-arm64, each one folder that runs the server there without Docker or
# Python (packaging/server/bundle.py says what each holds).
#   1. every pinned file (python-build-standalone's Python for each target, the site's libraries' wheels, the official
#      7-Zip) into the cache, each checked by its SHA-256, with this machine's own Python (bundle.py fetch);
#   2. the server's files from the tree as git lists them (tracked, and new ones not ignored: a release's tree has
#      nothing uncommitted, release.sh checks it);
#   3. the packages put together by the pinned Python for Linux x64 itself, in a bare Debian container with no network
#      (bundle.py build): the same tree makes the same bytes on any machine.
# Usage: [OPENDMT3_SERVER_INSTALLER=<the launcher's installer>] packaging/server/bundle.sh OUT_DIR [TARGET ...]
#   The version comes from opendmt3/__init__.py. OPENDMT3_SERVER_INSTALLER names the installer each package brings for
#   the site's Download page (release.sh gives the one it just built); without it they bring none, and setup
#   --installer adds one later. OPENDMT3_BUNDLE_CACHE names the folder the pinned files are kept in between builds
#   (default: OUT_DIR/cache; CI keeps it in its cache). With no TARGET, all four.
set -euo pipefail
OUT=$(realpath -m "${1:?usage: bundle.sh OUT_DIR [TARGET ...]}")
shift
REPO=$(cd "$(dirname "$0")/../.." && pwd)
# The bare Debian 10 CI runs the Linux packages in (glibc 2.28, nothing installed): the builder's Python needs no more.
DEBIAN="debian:buster-slim@sha256:bb3dc79fddbca7e8903248ab916bb775c96ec61014b3d02b4f06043b604726dc"
CACHE=$(realpath -m "${OPENDMT3_BUNDLE_CACHE:-$OUT/cache}")
mkdir -p "$OUT" "$CACHE"
echo "openDMT3 server packages for ${*:-every target} -> $OUT"

# ---- 1. the pinned files, checked, and the builder's Python unpacked in the cache
python3 "$REPO/packaging/server/bundle.py" fetch "$CACHE" "$@"

# ---- 2. the server's files as git lists them (bundle.py keeps those of the server's parts)
git -C "$REPO" ls-files -z --cached --others --exclude-standard > "$OUT/tree-files"

# ---- 3. the packages, by the pinned Python, with no network, as this user (the files it writes are this user's)
# The installer, when one is given, is read from a folder of its own.
installer=()
if [ -n "${OPENDMT3_SERVER_INSTALLER:-}" ]; then
  INSTALLER=$(realpath "$OPENDMT3_SERVER_INSTALLER")
  installer=(-v "$INSTALLER:/installer/$(basename "$INSTALLER"):ro")
  echo "brings the installer: $(basename "$INSTALLER")"
else
  echo "brings no installer (OPENDMT3_SERVER_INSTALLER names one)"
fi
BUILDER=$(sed -n 's/^PYTHON_RELEASE, PYTHON_VERSION = "\([0-9]*\)".*/\1/p' "$REPO/packaging/server/bundle.py")
[ -n "$BUILDER" ] || { echo "bundle.py names no PYTHON_RELEASE" >&2; exit 1; }
# The repository, the cache and the installer read-only, the output folder writable; HOME for nothing to write into.
docker run --rm --network none -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$REPO:/src:ro" -v "$CACHE:/cache:ro" \
  -v "$OUT:/out" "${installer[@]}" "$DEBIAN" "/cache/builder-$BUILDER/python/bin/python3" -I \
  /src/packaging/server/bundle.py build /cache /out/tree-files /out --root /src \
  ${INSTALLER:+--installer "/installer/$(basename "$INSTALLER")"} "$@" | tee "$OUT/packages.sha256"
# The folders the packages were put together in: each package holds the same, unpacked.
rm -rf "$OUT/stage"
ls -l "$OUT"/opendmt3-server-*.tar.gz
