#!/bin/bash
# Build the Windows launcher and its installer on Linux, in containers:
#   0. openDMT3's card reader and in-game layer (32-bit C, MinGW) -> CRT_R1.dll with its notices; the official 7-Zip
#      for Windows (sevenzip.sh); DSOAL and OpenAL Soft for the Sound page's mixer, with their notices and sources
#      (native/openal/build.sh)
#   1. pictures, version file and update address (Linux Python with Pillow, the UI test image)
#   2. PyInstaller under Wine with a Windows Python -> one folder with openDMT3.exe and openDMT3-cmd.exe, and the
#      licence texts of what it carries in its licenses folder, with NOTICES.txt (notices.py, with that Python)
#   3. Velopack's vpk (.NET) -> Velopack's setup, a portable zip and the update packages: the whole package, and a
#      delta package from the previous release's when it is kept (previous.py: an update then downloads what changed)
#   4. PyInstaller again -> openDMT3-win-Setup.exe: the installer's dialogs with Velopack's setup inside
# Usage: [OPENDMT3_UPDATE_SOURCE=<where releases are published>] [OPENDMT3_PREVIOUS_RELEASE=<folder or package>]
#        [OPENDMT3_SIGNING_KEY=<the signing key's file>] [OPENDMT3_TEST_UPDATE_KEY=<a public key>]
#        packaging/windows/build.sh OUT_DIR
#   The version comes from opendmt3/__init__.py. OPENDMT3_UPDATE_SOURCE is a GitHub repository URL or a folder
#   (local or HTTP) holding the update packages; the launcher looks for updates there. Without it, none.
#   OPENDMT3_PREVIOUS_RELEASE names the previous release's full package, or a folder holding it (the last build into
#   OUT_DIR keeps its own too); without one, no delta package is made.
#   OPENDMT3_SIGNING_KEY names the key the update packages are signed with (sign.sh); it is named here and nowhere
#   else, and without it the packages are not signed. OPENDMT3_TEST_UPDATE_KEY makes a test build: its launcher takes
#   updates signed with that key as well as the project's (a test's own key pair; never set for a release).
set -euo pipefail
OUT=$(realpath -m "${1:?usage: build.sh OUT_DIR}")
REPO=$(cd "$(dirname "$0")/../.." && pwd)
HERE="$REPO/packaging/windows"
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$REPO/opendmt3/__init__.py")
# The Windows Python archive, fetched once and checked against this hash before every use.
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.12.16%2B20261026-x86_64-pc-windows-msvc-install_only.tar.gz"
PBS_SHA256="590dfcbe3a34c07301e6332e13e2188b98655cd072b08afa45a7998dc4c22bc5"
# Velopack's packaging tool, the same release line as the velopack Python package the launcher bundles.
VPK_VERSION="${VPK_VERSION:-1.2.161}"
mkdir -p "$OUT/cache" "$OUT/assets"
echo "openDMT3 $VERSION -> $OUT"

# ---- the build machine (cached by Docker once made), on the Wine image of packaging/wine
docker image inspect opendmt3-wine:local >/dev/null 2>&1 || docker build -q -t opendmt3-wine:local "$REPO/packaging/wine" >/dev/null
# Made again whenever its recipe changes (the image carries the recipe's hash as a label): an image made from an
# older recipe would build this tree without the libraries it now needs.
RECIPE=$(cat "$HERE/Dockerfile" <(echo "$PBS_SHA256") | sha256sum | cut -c1-16)
if [ "$(docker image inspect -f '{{index .Config.Labels "opendmt3.recipe"}}' opendmt3-winbuild:local 2>/dev/null)" != "$RECIPE" ]; then
  [ -f "$OUT/cache/pbs.tar.gz" ] || curl -fsSL -o "$OUT/cache/pbs.tar.gz" "$PBS_URL"
  echo "$PBS_SHA256  $OUT/cache/pbs.tar.gz" | sha256sum -c --quiet
  ctx=$(mktemp -d)
  cp "$HERE/Dockerfile" "$OUT/cache/pbs.tar.gz" "$ctx/"
  docker build -q --label "opendmt3.recipe=$RECIPE" -t opendmt3-winbuild:local "$ctx" >/dev/null || exit 1
  rm -rf "$ctx"
fi

# ---- 0. openDMT3's card reader and in-game layer (32-bit, like the game)
"$REPO/native/cardreader/build.sh" "$OUT/native"

# ---- 0b. the official 7-Zip for Windows: 7z.exe, 7z.dll, its licence and readme, checked against the pinned hashes
"$HERE/sevenzip.sh" "$OUT"

# ---- 0c. the Sound page's OpenAL Soft mixer: DSOAL and OpenAL Soft from their pinned source archives (kept in
#      OUT_DIR/openal/sources: the release carries them beside the installer, as their LGPL asks), with their notices
"$REPO/native/openal/build.sh" "$OUT/openal"

# ---- 1. pictures and the version file (the UI test image: Linux Python with Pillow, made again when its recipe moves)
RECIPE_UI=$(sha256sum "$REPO/tests/e2e/ui/Dockerfile" | cut -c1-16)
if [ "$(docker image inspect -f '{{index .Config.Labels "opendmt3.recipe"}}' opendmt3-ui:local 2>/dev/null)" != "$RECIPE_UI" ]; then
  docker build -q --label "opendmt3.recipe=$RECIPE_UI" -t opendmt3-ui:local "$REPO/tests/e2e/ui" >/dev/null || exit 1
fi
docker run --rm --network none -e PYTHONDONTWRITEBYTECODE=1 -v "$REPO:/src:ro" -v "$OUT/assets:/out" -w /src \
  opendmt3-ui:local python packaging/windows/assets.py /out "$VERSION"
# The update address goes into the launcher as a file (empty: this build does not look for updates).
printf '%s' "${OPENDMT3_UPDATE_SOURCE:-}" > "$OUT/assets/update-source.txt"
echo "update address: ${OPENDMT3_UPDATE_SOURCE:-(none)}"
# A test build's own update key goes in the same way, beside signing.py (empty: the launcher takes the project's key
# alone, as every release's does). Anything but a public key stops the build: it would be a launcher that takes none.
TEST_KEY=${OPENDMT3_TEST_UPDATE_KEY:-}
[[ -z "$TEST_KEY" || "$TEST_KEY" =~ ^[0-9a-fA-F]{64}$ ]] \
  || { echo "OPENDMT3_TEST_UPDATE_KEY is not a public key (64 hex digits)" >&2; exit 2; }
printf '%s' "$TEST_KEY" > "$OUT/assets/update-test-keys.txt"
[ -z "$TEST_KEY" ] || echo "TEST BUILD, not for release: its launcher also takes updates signed with the key $TEST_KEY"

# ---- 2. PyInstaller under Wine (no network: everything it needs is in the image)
rm -rf "$OUT/dist" "$OUT/work"
docker run --rm --network none -e PYTHONDONTWRITEBYTECODE=1 -e OPENDMT3_BUILD_DIR='Z:\out\assets' \
  -e OPENDMT3_NATIVE_DIR='Z:\out\native' -e OPENDMT3_7ZIP_DIR='Z:\out\7zip' -e OPENDMT3_OPENAL_DIR='Z:\out\openal' \
  -v "$REPO:/src:ro" -v "$OUT:/out" -w /src opendmt3-winbuild:local bash -c "
    wine 'C:\\python\\python.exe' -m PyInstaller --noconfirm --log-level WARN \
      --distpath 'Z:\\out\\dist' --workpath 'Z:\\out\\work' 'Z:\\src\\packaging\\windows\\openDMT3.spec' \
      > /out/pyinstaller.log 2>&1; code=\$?; wineserver -w; exit \$code"
ls "$OUT/dist/openDMT3/openDMT3.exe" "$OUT/dist/openDMT3/openDMT3-cmd.exe" >/dev/null

# ---- 2b. the licence texts of everything the program carries, in its licenses folder with NOTICES.txt: gathered by
# the same Windows Python from what it built (the modules inside the programs, the packages' metadata, Python's own
# files); a part without its text stops the build here.
docker run --rm --network none -e PYTHONDONTWRITEBYTECODE=1 -v "$REPO:/src:ro" -v "$OUT:/out" -w /src \
  opendmt3-winbuild:local bash -c "
    wine 'C:\\python\\python.exe' 'Z:\\src\\packaging\\windows\\notices.py' 'Z:\\out\\dist\\openDMT3' 'Z:\\src' \
      > /out/notices.log 2>&1; code=\$?; wineserver -w; exit \$code" || { cat "$OUT/notices.log"; exit 1; }
grep "^licenses:" "$OUT/notices.log"

# ---- 3. Velopack: the installer and the update packages
# Made again when VPK_VERSION or the recipe changes (the label holds both). vpk makes delta packages with zstd's own
# program (--patch-from), which the .NET image does not have.
VPK_RECIPE="vpk-$VPK_VERSION-zstd"
if [ "$(docker image inspect -f '{{index .Config.Labels "opendmt3.recipe"}}' opendmt3-vpk:local 2>/dev/null)" != "$VPK_RECIPE" ]; then
  ctx=$(mktemp -d)
  printf 'FROM mcr.microsoft.com/dotnet/sdk:8.0\nRUN apt-get update && apt-get install -y --no-install-recommends zstd && rm -rf /var/lib/apt/lists/*\nRUN dotnet tool install -g vpk --version %s\nENV PATH="${PATH}:/root/.dotnet/tools"\n' "$VPK_VERSION" > "$ctx/Dockerfile"
  docker build -q --label "opendmt3.recipe=$VPK_RECIPE" -t opendmt3-vpk:local "$ctx" >/dev/null || exit 1
  rm -rf "$ctx"
fi
# The previous release's full package stays beside the new one, and vpk makes the delta package from it: what an
# update downloads when the PC has that version (Velopack puts the new package together from the one installed). Only
# that one stays (an earlier build's other files would go into the new feed: previous.py).
previous=$(python3 "$HERE/previous.py" "$OUT/releases" "$VERSION" ${OPENDMT3_PREVIOUS_RELEASE:+"$OPENDMT3_PREVIOUS_RELEASE"})
echo "delta package from: $previous"
docker run --rm --network none -v "$OUT:/out" opendmt3-vpk:local vpk "[win]" pack \
  --packId openDMT3 --packVersion "$VERSION" --packDir /out/dist/openDMT3 --mainExe openDMT3.exe \
  --packTitle openDMT3 --packAuthors openDMT3 --icon /out/assets/openDMT3.ico \
  --splashImage /out/assets/splash.png --outputDir /out/releases > "$OUT/vpk.log" 2>&1 || { cat "$OUT/vpk.log"; exit 1; }
# The signature beside each of this version's packages (sign.sh): with the key OPENDMT3_SIGNING_KEY names, which stays
# off the repository and is named nowhere else; without the variable the packages are not signed, and it says so.
"$HERE/sign.sh" "$OUT/releases" "$VERSION" || { echo "the packages could not be signed"; exit 1; }
ls -la "$OUT/releases"

# ---- 4. the installer people run: openDMT3's dialogs around Velopack's setup, in one file
rm -rf "$OUT/setup" && mkdir -p "$OUT/setup"
mv "$OUT/releases/openDMT3-win-Setup.exe" "$OUT/setup/velopack-setup.exe"
docker run --rm --network none -e PYTHONDONTWRITEBYTECODE=1 -e OPENDMT3_BUILD_DIR='Z:\out\assets' \
  -e OPENDMT3_VELOPACK_SETUP='Z:\out\setup\velopack-setup.exe' \
  -v "$REPO:/src:ro" -v "$OUT:/out" -w /src opendmt3-winbuild:local bash -c "
    wine 'C:\\python\\python.exe' -m PyInstaller --noconfirm --log-level WARN \
      --distpath 'Z:\\out\\setup\\dist' --workpath 'Z:\\out\\setup\\work' 'Z:\\src\\packaging\\windows\\setup.spec' \
      > /out/pyinstaller-setup.log 2>&1; code=\$?; wineserver -w; exit \$code"
cp "$OUT/setup/dist/openDMT3-win-Setup.exe" "$OUT/releases/openDMT3-win-Setup.exe"
ls -la "$OUT/releases/openDMT3-win-Setup.exe"
