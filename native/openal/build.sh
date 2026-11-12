#!/bin/bash
# DSOAL and OpenAL Soft for the Sound page's OpenAL Soft mixer (native/cardreader/openal.c), built for 32-bit Windows
# (like the game) from their pinned sources with MinGW-w64 in a container with no network. Both archives are checked
# against the pinned hashes before every use and kept in OUT_DIR/cache, and copied into OUT_DIR/sources: they are the
# source the libraries are built from, which the release carries beside them (both are under the GNU LGPL).
#   native/openal/build.sh OUT_DIR
#     -> OUT_DIR/dsoal-aldrv.dll       OpenAL Soft (the name DSOAL loads it by)
#        OUT_DIR/openDMT3-dsoal.dll    DSOAL's dsound.dll, renamed: Windows' own stays the game's DirectSound
#        OUT_DIR/openal-NOTICES.txt    what each is, its version, its licences in full and where its source is
#        OUT_DIR/sources/              the two source archives
set -euo pipefail
OUT=$(realpath -m "${1:?usage: build.sh OUT_DIR}")
HERE=$(cd "$(dirname "$0")" && pwd)
# OpenAL Soft's release, and DSOAL's commit (it makes no releases of its own: its master is what its own builds take).
OPENAL_VERSION=1.25.2
OPENAL_URL=https://github.com/kcat/openal-soft/archive/refs/tags/$OPENAL_VERSION.tar.gz
OPENAL_SHA256=fb27e5839aa11f0e5b9d33756965291fad5d6909ab928ea1f796f4a1a6877894
DSOAL_COMMIT=e11128250439d586483ee6598d1670ab52ab5e37
DSOAL_URL=https://github.com/kcat/dsoal/archive/$DSOAL_COMMIT.tar.gz
DSOAL_SHA256=b55fe3845f0dc07082f56d4703ffe81f73b19f37f91159fa501ebc6d278bdab0
OPENAL_TAR=openal-soft-$OPENAL_VERSION.tar.gz
DSOAL_TAR=dsoal-$DSOAL_COMMIT.tar.gz
mkdir -p "$OUT/cache"
# Fetched once into the cache; a download is kept only when its hash is the pinned one (one cut short is never taken
# for the archive by a later run), and a copy from an earlier run is checked like a new one.
fetch() {   # fetch URL FILE SHA256
  if [ ! -f "$OUT/cache/$2" ]; then
    curl -fsSL -o "$OUT/cache/$2.part" "$1"
    echo "$3  $OUT/cache/$2.part" | sha256sum -c --quiet || { rm -f "$OUT/cache/$2.part"; exit 1; }
    mv "$OUT/cache/$2.part" "$OUT/cache/$2"
  fi
  echo "$3  $OUT/cache/$2" | sha256sum -c --quiet
}
fetch "$OPENAL_URL" "$OPENAL_TAR" "$OPENAL_SHA256"
fetch "$DSOAL_URL" "$DSOAL_TAR" "$DSOAL_SHA256"
# The release's copy of the sources: these two archives alone (an earlier pin's are gone), and their hashes in
# SHA256SUMS, which packaging/release.sh takes the list of files from.
rm -rf "$OUT/sources"
mkdir -p "$OUT/sources"
cp "$OUT/cache/$OPENAL_TAR" "$OUT/cache/$DSOAL_TAR" "$OUT/sources/"
printf '%s  %s\n%s  %s\n' "$OPENAL_SHA256" "$OPENAL_TAR" "$DSOAL_SHA256" "$DSOAL_TAR" > "$OUT/sources/SHA256SUMS"
# The compiler's image, made again whenever its recipe changes (it carries the recipe's hash as a label).
RECIPE=$(sha256sum "$HERE/Dockerfile" | cut -c1-16)
if [ "$(docker image inspect -f '{{index .Config.Labels "opendmt3.recipe"}}' opendmt3-openal:local 2>/dev/null)" \
     != "$RECIPE" ]; then
  docker build -q --label "opendmt3.recipe=$RECIPE" -t opendmt3-openal:local "$HERE" >/dev/null
fi
# As the caller's user, so what it writes is theirs (a CI runner is no root); the sources unpacked inside the
# container only. Its name says whose it is, as the other build steps' do.
docker run --rm --name "${OPENDMT3_E2E_NAME:-odt3}-openal-$$" --network none -u "$(id -u):$(id -g)" \
  -v "$OUT:/out" -v "$HERE:/here:ro" -e OPENAL_TAR="$OPENAL_TAR" -e DSOAL_TAR="$DSOAL_TAR" \
  opendmt3-openal:local bash /here/inside.sh
# Not executable here: a Windows program is never started from this machine (WSL would hand it to Windows).
chmod 0644 "$OUT/dsoal-aldrv.dll" "$OUT/openDMT3-dsoal.dll"
# The notices: what each part is, the archives it is built from with their hashes, and every licence text in them.
bash "$HERE/notices.sh" "$OUT" "$OPENAL_VERSION" "$OPENAL_URL" "$OPENAL_SHA256" "$DSOAL_COMMIT" "$DSOAL_URL" \
  "$DSOAL_SHA256" > "$OUT/openal-NOTICES.txt"
echo "DSOAL and OpenAL Soft $OPENAL_VERSION: $OUT/dsoal-aldrv.dll, $OUT/openDMT3-dsoal.dll, $OUT/openal-NOTICES.txt"
