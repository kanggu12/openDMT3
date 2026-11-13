#!/bin/bash
# Build CRT_R1.dll (32-bit, like the game) with MinGW-w64 in a Debian container: the card reader and the in-game
# layer. Usage: build.sh OUT_DIR
set -euo pipefail
OUT=$(realpath -m "${1:?usage: build.sh OUT_DIR}")
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$OUT"
# The compiler runs as whoever runs this, so what it writes is theirs to change (a CI runner is no root).
AS="$(id -u):$(id -g)"
docker image inspect opendmt3-mingw:local >/dev/null 2>&1 || {
  ctx=$(mktemp -d)
  printf 'FROM debian:12\nRUN apt-get update && apt-get install -y --no-install-recommends gcc-mingw-w64-i686 && rm -rf /var/lib/apt/lists/*\n' > "$ctx/Dockerfile"
  docker build -q -t opendmt3-mingw:local "$ctx" >/dev/null
  rm -rf "$ctx"
}
# The product's mark for the in-game bar, drawn by the launcher's own code (mark.py) in the launcher's UI test image,
# which has Pillow and the fonts: the bar shows the launcher's picture of the mark. As the caller's user, like every
# step here, so nothing in the output folder belongs to root.
REPO=$(cd "$HERE/../.." && pwd)
docker image inspect opendmt3-ui:local >/dev/null 2>&1 || docker build -q -t opendmt3-ui:local "$REPO/tests/e2e/ui" >/dev/null
docker run --rm --network none -u "$AS" -e PYTHONDONTWRITEBYTECODE=1 -v "$REPO:/src:ro" -v "$OUT:/out" -w /src \
  opendmt3-ui:local python native/cardreader/mark.py /out/mark.bin >/dev/null
# The shaders' sources and the mark go in as resources (post.rc): the shaders compiled when the game starts by its own
# D3DX, the mark found beside the resource script's output (-I /out).
docker run --rm --network none -u "$AS" -v "$HERE:/src:ro" -v "$OUT:/out" -w /src opendmt3-mingw:local \
  i686-w64-mingw32-windres -I /out post.rc -O coff -o /out/post.res
# --kill-at drops the @N of the __stdcall names; static libgcc so the DLL needs nothing beside Windows. The layer's
# pictures need the maths library; its words GDI, its window USER (both part of every Windows). The sound engine's
# period (engine.c) loads COM's library itself when the game opens its sound, so the imports stay these.
docker run --rm --network none -u "$AS" -v "$HERE:/src:ro" -v "$OUT:/out" opendmt3-mingw:local \
  i686-w64-mingw32-gcc -O2 -s -shared -static-libgcc -Wall -o /out/CRT_R1.dll \
    /src/crt_r1.c /src/hooks.c /src/trace.c /src/post.c /src/postmath.c /src/sound.c /src/engine.c /src/openal.c \
    /src/layer.c /src/text.c /src/look.c /src/logic.c /src/paint.c /src/files.c /src/redirect.c /src/passtimes.c \
    /src/render.c /src/strobe.c /src/flip.c /src/methods.c \
    /src/crt_r1.def /out/post.res \
    -Wl,--kill-at -luser32 -lgdi32 -lm
# Not executable: a Windows program is never started from here (WSL would hand it to Windows).
chmod 0644 "$OUT/CRT_R1.dll"
rm -f "$OUT/post.res" "$OUT/mark.bin"
# The notices of the code built into the library, in one file that goes wherever the library goes (notices.sh, in
# the compiler's image, which knows the runtime it links in).
docker run --rm --network none -u "$AS" -v "$HERE:/src:ro" -v "$OUT:/out" opendmt3-mingw:local \
  sh /src/notices.sh /out/card-reader-NOTICES.txt
echo "the card reader library and its notices: $OUT/CRT_R1.dll, $OUT/card-reader-NOTICES.txt"
