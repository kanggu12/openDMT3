#!/bin/bash
# The native tests of the in-game layer (test_native.c): built with the DLL's compiler (MinGW, 32-bit), run under
# Wine in the Wine image, both in containers with no network. Exit 0 when every check holds. methods.c is the one file
# with Windows calls among them: its watch writes a table as Direct3D's would be, in this program's own image.
#   native/cardreader/test.sh
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT
# The compiler image, as build.sh makes it.
docker image inspect opendmt3-mingw:local >/dev/null 2>&1 || "$HERE/build.sh" "$OUT/dll" >/dev/null
docker run --rm --network none -v "$HERE:/src:ro" -v "$OUT:/out" opendmt3-mingw:local \
  i686-w64-mingw32-gcc -O2 -Wall -o /out/test_native.exe /src/test_native.c /src/look.c /src/logic.c /src/postmath.c /src/paint.c /src/redirect.c /src/passtimes.c /src/contacts.c /src/methods.c -lm \
  || { echo "FAIL: the native tests did not build"; exit 1; }
# Not executable here: only Wine, in its container, runs it. Changed in a container as the compiler's wrote it (as
# root, which a CI runner's own user may not change).
docker run --rm --network none -v "$OUT:/out" opendmt3-mingw:local chmod 0644 /out/test_native.exe
# The Wine image, as packaging/windows/build.sh makes it (a machine that never built the launcher has none).
docker image inspect opendmt3-wine:local >/dev/null 2>&1 \
  || docker build -q -t opendmt3-wine:local "$HERE/../../packaging/wine" >/dev/null || { echo "FAIL: the Wine image did not build"; exit 1; }
docker run --rm --network none -v "$OUT:/out:ro" opendmt3-wine:local bash -c \
  'export WINEPREFIX=/tmp/w WINEDEBUG=-all; wineboot -i >/dev/null 2>&1; wine /out/test_native.exe; code=$?; wineserver -w; exit $code'
