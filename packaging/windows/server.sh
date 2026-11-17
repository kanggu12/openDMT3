#!/bin/bash
# Build the Windows server package on Linux, in containers: opendmt3-server-<version>-windows-x64.zip, a folder that
# runs the server on a Windows PC of its own, without Docker, Python or the launcher.
#   0. the official 7-Zip for Windows (sevenzip.sh), for the client data's archives
#   1. the icon and the version file (assets.py, the UI test image's Linux Python with Pillow)
#   2. PyInstaller under Wine with the launcher build's Windows Python (the same image, the same pinned libraries):
#      one folder with opendmt3-server.exe (server.spec), then the licence texts of everything in it (notices.py)
#   3. the folder: the program, the launcher's installer the site hands out (when one is given), the readme, the
#      licence, three shortcuts for the usual jobs; then the zip and its SHA-256
# Usage: [OPENDMT3_SERVER_INSTALLER=<the launcher's installer>] packaging/windows/server.sh OUT_DIR
#   The version comes from opendmt3/__init__.py. OPENDMT3_SERVER_INSTALLER names the installer to bring (release.sh
#   gives the one it just built); without it the package brings none, and setup --installer adds one later.
# PyInstaller makes a folder program, not one file: one file would unpack itself into a temporary folder at every start
# (slower, and a server that runs for weeks would hold that folder), and the folder is what a zip carries anyway.
set -euo pipefail
OUT=$(realpath -m "${1:?usage: server.sh OUT_DIR}")
REPO=$(cd "$(dirname "$0")/../.." && pwd)
HERE="$REPO/packaging/windows"
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$REPO/opendmt3/__init__.py")
# The package's name: the tool, the part, the version, the system, in lower case, as every release file is named.
NAME="opendmt3-server-$VERSION-windows-x64"
mkdir -p "$OUT/cache" "$OUT/assets"
echo "openDMT3 server $VERSION for Windows -> $OUT/$NAME.zip"

# ---- the build machine: the launcher build's, made by build.sh with the same recipe (its Dockerfile and the Windows
# Python's archive, by the hash build.sh pins); made here the same way when this PC has not built it yet.
PBS_URL=$(sed -n 's/^PBS_URL="\(.*\)"$/\1/p' "$HERE/build.sh")
PBS_SHA256=$(sed -n 's/^PBS_SHA256="\(.*\)"$/\1/p' "$HERE/build.sh")
[ -n "$PBS_URL" ] && [ -n "$PBS_SHA256" ] || { echo "build.sh names no Windows Python (PBS_URL, PBS_SHA256)" >&2; exit 1; }
docker image inspect opendmt3-wine:local >/dev/null 2>&1 || docker build -q -t opendmt3-wine:local "$REPO/packaging/wine" >/dev/null
RECIPE=$(cat "$HERE/Dockerfile" <(echo "$PBS_SHA256") | sha256sum | cut -c1-16)
if [ "$(docker image inspect -f '{{index .Config.Labels "opendmt3.recipe"}}' opendmt3-winbuild:local 2>/dev/null)" != "$RECIPE" ]; then
  [ -f "$OUT/cache/pbs.tar.gz" ] || curl -fsSL -o "$OUT/cache/pbs.tar.gz" "$PBS_URL"
  echo "$PBS_SHA256  $OUT/cache/pbs.tar.gz" | sha256sum -c --quiet
  ctx=$(mktemp -d)
  cp "$HERE/Dockerfile" "$OUT/cache/pbs.tar.gz" "$ctx/"
  docker build -q --label "opendmt3.recipe=$RECIPE" -t opendmt3-winbuild:local "$ctx" >/dev/null || exit 1
  rm -rf "$ctx"
fi

# ---- 0. the official 7-Zip for Windows, checked against the pinned hashes
"$HERE/sevenzip.sh" "$OUT"

# ---- 1. the icon and the version file
RECIPE_UI=$(sha256sum "$REPO/tests/e2e/ui/Dockerfile" | cut -c1-16)
if [ "$(docker image inspect -f '{{index .Config.Labels "opendmt3.recipe"}}' opendmt3-ui:local 2>/dev/null)" != "$RECIPE_UI" ]; then
  docker build -q --label "opendmt3.recipe=$RECIPE_UI" -t opendmt3-ui:local "$REPO/tests/e2e/ui" >/dev/null || exit 1
fi
docker run --rm --network none -e PYTHONDONTWRITEBYTECODE=1 -v "$REPO:/src:ro" -v "$OUT/assets:/out" -w /src \
  opendmt3-ui:local python packaging/windows/assets.py /out "$VERSION"

# ---- 2. PyInstaller under Wine (no network: everything it needs is in the image), then the licence texts
rm -rf "$OUT/dist" "$OUT/work"
docker run --rm --network none -e PYTHONDONTWRITEBYTECODE=1 -e OPENDMT3_BUILD_DIR='Z:\out\assets' \
  -e OPENDMT3_7ZIP_DIR='Z:\out\7zip' -v "$REPO:/src:ro" -v "$OUT:/out" -w /src opendmt3-winbuild:local bash -c "
    wine 'C:\\python\\python.exe' -m PyInstaller --noconfirm --log-level WARN \
      --distpath 'Z:\\out\\dist' --workpath 'Z:\\out\\work' 'Z:\\src\\packaging\\windows\\server.spec' \
      > /out/pyinstaller.log 2>&1; code=\$?; wineserver -w; exit \$code" || { tail -n 40 "$OUT/pyinstaller.log"; exit 1; }
ls "$OUT/dist/opendmt3-server/opendmt3-server.exe" >/dev/null
docker run --rm --network none -e PYTHONDONTWRITEBYTECODE=1 -v "$REPO:/src:ro" -v "$OUT:/out" -w /src \
  opendmt3-winbuild:local bash -c "
    wine 'C:\\python\\python.exe' 'Z:\\src\\packaging\\windows\\notices.py' 'Z:\\out\\dist\\opendmt3-server' 'Z:\\src' \
      > /out/notices.log 2>&1; code=\$?; wineserver -w; exit \$code" || { cat "$OUT/notices.log"; exit 1; }
grep "^licenses:" "$OUT/notices.log"

# ---- 3. the folder people unpack, then the zip
STAGE="$OUT/stage/$NAME"
rm -rf "$OUT/stage" && mkdir -p "$STAGE"
cp -r "$OUT/dist/opendmt3-server/." "$STAGE/"
if [ -n "${OPENDMT3_SERVER_INSTALLER:-}" ]; then
  # The launcher's installer, which the first start puts in the data folder's downloads for the Download page.
  mkdir -p "$STAGE/installer"
  cp "$OPENDMT3_SERVER_INSTALLER" "$STAGE/installer/"
  echo "brings the installer: $(basename "$OPENDMT3_SERVER_INSTALLER")"
else
  echo "brings no installer (OPENDMT3_SERVER_INSTALLER names one)"
fi
# The readme with this version in it, and the licence, with Windows' own line ends (Notepad shows them as lines).
sed "s/@VERSION@/$VERSION/g" "$HERE/server-README.txt" | sed 's/$/\r/' > "$STAGE/README.txt"
sed 's/$/\r/' "$REPO/LICENSE" > "$STAGE/LICENSE.txt"
# Three shortcuts for the jobs without a window of their own, each the program with one command (the program owns
# starting and stopping alike), the window left open to read what it said.
printf '@echo off\r\n"%%~dp0opendmt3-server.exe" start\r\npause\r\n' > "$STAGE/Start in the background.cmd"
printf '@echo off\r\n"%%~dp0opendmt3-server.exe" stop\r\npause\r\n' > "$STAGE/Stop the server.cmd"
printf '@echo off\r\n"%%~dp0opendmt3-server.exe" firewall\r\npause\r\n' > "$STAGE/Open the firewall.cmd"
# The list of the package's own files with their SHA-256, which opendmt3-server repair checks the folder against.
(cd "$STAGE" && find . -type f ! -name files.sha256 | sed 's|^\./||' | LC_ALL=C sort | while read -r f; do
  printf '%s  %s\n' "$(sha256sum "$f" | cut -d' ' -f1)" "$f"; done > files.sha256)
rm -f "$OUT/$NAME.zip"
# The zip from the stage's folder, so it unpacks into one folder named for the version. Python's zipfile (no zip
# program needed), the newest file times kept as they are.
python3 - "$OUT/stage" "$NAME" "$OUT/$NAME.zip" <<'PY'
import os, sys, zipfile
top, name, out = sys.argv[1:]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for folder, dirs, files in os.walk(os.path.join(top, name)):
        dirs.sort()
        for f in sorted(files):
            path = os.path.join(folder, f)
            z.write(path, os.path.relpath(path, top))
PY
(cd "$OUT" && sha256sum "$NAME.zip" > "$NAME.zip.sha256")
du -sh "$STAGE" "$OUT/$NAME.zip"
