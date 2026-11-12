#!/bin/sh
# The notices of the code built into CRT_R1.dll, in one text file that goes wherever the library goes (the launcher
# puts both in place together: opendmt3/core/cabinet/steps.py, CardReader; the installed program keeps a copy in its
# licenses folder). Run by build.sh in the compiler's image, which has the runtime the compiler links in and that
# runtime's own copyright file:
#   sh notices.sh OUT_FILE      (from this folder, or with this folder mounted at /src)
# The picture's passes come with their licences from third_party/; the runtime's versions and licences are the
# compiler image's own packages', read here, not written by hand.
set -eu
OUT=${1:?usage: notices.sh OUT_FILE}
# This folder: third_party/ is beside this script.
HERE=$(cd "$(dirname "$0")" && pwd)
# The packages that put a runtime into the library: the mingw-w64 C runtime (its start-up code and the few functions
# the C library lacks) and GCC's (libgcc, linked statically with -static-libgcc).
MINGW=$(dpkg-query -W -f='${Version}' mingw-w64-i686-dev)
GCC=$(dpkg-query -W -f='${Version}' gcc-mingw-w64-i686-win32)
RULE="================================================================================"

# One text in full under a heading that names it and where it came from; a text that ends without a line break
# gets one, so the next heading starts a line of its own.
text() {
  printf '\n%s\n%s\n%s\n\n' "$RULE" "$1" "$RULE"
  cat "$2"
  [ -z "$(tail -c 1 "$2")" ] || echo
}

{
  echo "openDMT3's card reader library, CRT_R1.dll, holds openDMT3's own code (MIT License) and code from these"
  echo "projects, each under its own licence. The texts follow in full."
  echo
  echo "- AMD FidelityFX Super Resolution 1, the upscale filter AMD FSR 1: MIT License"
  echo "- NVIDIA Image Scaling, the upscale filter NVIDIA NIS: MIT License"
  echo "- SMAA with its area and search textures, the anti-aliasing SMAA: MIT License"
  echo "- FXAA 3.11, the algorithm the anti-aliasing FXAA is written from: NVIDIA's notice"
  echo "- The mingw-w64 C runtime $MINGW, linked in by the compiler: the licences its copyright file lists"
  echo "- The GCC runtime library (libgcc) $GCC, linked in by the compiler:"
  echo "  GPL 3 with the GCC Runtime Library Exception, which asks nothing of a program built with it"
  text "AMD FidelityFX Super Resolution 1 (third_party/fsr/LICENSE.txt)" "$HERE/third_party/fsr/LICENSE.txt"
  text "NVIDIA Image Scaling (third_party/nis/LICENSE.txt)" "$HERE/third_party/nis/LICENSE.txt"
  text "SMAA (third_party/smaa/LICENSE.txt)" "$HERE/third_party/smaa/LICENSE.txt"
  text "FXAA 3.11 (third_party/fxaa/NOTICE.txt)" "$HERE/third_party/fxaa/NOTICE.txt"
  text "The mingw-w64 C runtime $MINGW (Debian's copyright file of mingw-w64-i686-dev)" \
    /usr/share/doc/mingw-w64-i686-dev/copyright
} > "$OUT"
