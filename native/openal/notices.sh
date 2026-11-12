#!/bin/bash
# The notices of DSOAL and OpenAL Soft as built by build.sh, on standard output: what each is and does here, its
# version, the archive it is built from with its address and hash (the release carries both archives: their source,
# as the GNU LGPL asks), and every licence text in those archives in full, read from the archives themselves.
#   notices.sh OUT_DIR OPENAL_VERSION OPENAL_URL OPENAL_SHA256 DSOAL_COMMIT DSOAL_URL DSOAL_SHA256
set -euo pipefail
OUT=$1; ALV=$2; ALURL=$3; ALSHA=$4; DSC=$5; DSURL=$6; DSSHA=$7
AL="$OUT/cache/openal-soft-$ALV.tar.gz"
DS="$OUT/cache/dsoal-$DSC.tar.gz"
RULE="================================================================================"
# One text from an archive in full under a heading that names it and where in the archive it is.
text() {
  printf '\n%s\n%s\n%s\n\n' "$RULE" "$1" "$RULE"
  tar -xzOf "$2" "$3"
  echo
}
echo "The Sound page's OpenAL Soft mixer: two libraries beside openDMT3's card reader library, each under its own"
echo "licence, built from the source archives named below without changes. Their texts follow in full."
echo
echo "- DSOAL (openDMT3-dsoal.dll, DSOAL's dsound.dll under another name): DirectSound's calls as OpenAL's."
echo "  GNU Lesser General Public License 2.1 or any later version. Source: commit $DSC,"
echo "  $DSURL (SHA-256 $DSSHA)."
echo "  It holds the {fmt} library 11.2.0: MIT License."
echo "- OpenAL Soft $ALV (dsoal-aldrv.dll, the name DSOAL loads it by): the mixer, writing to the sound device"
echo "  through WASAPI. GNU Library General Public License 2 or any later version, with parts under the"
echo "  BSD 3-Clause License and PFFFT's licence (their texts below); it holds the {fmt} library 11.2.0 (MIT"
echo "  License) and Microsoft's GSL (MIT License), and its default HRTF data set, made from the KEMAR HRTF data"
echo "  of the MIT Media Lab (Bill Gardner and Keith Martin). Source: $ALURL"
echo "  (SHA-256 $ALSHA)."
echo "- Both are linked with the mingw-w64 runtime and GCC's runtime libraries (libgcc and libstdc++, GPL 3 with the"
echo "  GCC Runtime Library Exception, which asks nothing of a program built with them); the mingw-w64 runtime's"
echo "  licences are in card-reader-NOTICES.txt beside them."
echo
echo "The release that brings these libraries carries both source archives beside its installer. Under the LGPL"
echo "either library may be replaced by another build of it under the same file name: in the installed launcher's"
echo "_internal\\opendmt3\\core\\cabinet\\bin folder, from where PLAY puts them beside the card reader library."
text "DSOAL: LICENSE (GNU LGPL 2.1)" "$DS" "dsoal-$DSC/LICENSE"
text "DSOAL: fmt-11.2.0/LICENSE ({fmt})" "$DS" "dsoal-$DSC/fmt-11.2.0/LICENSE"
text "OpenAL Soft: COPYING (GNU LGPL 2)" "$AL" "openal-soft-$ALV/COPYING"
text "OpenAL Soft: BSD-3Clause" "$AL" "openal-soft-$ALV/BSD-3Clause"
text "OpenAL Soft: LICENSE-pffft" "$AL" "openal-soft-$ALV/LICENSE-pffft"
text "OpenAL Soft: fmt-11.2.0/LICENSE ({fmt})" "$AL" "openal-soft-$ALV/fmt-11.2.0/LICENSE"
text "OpenAL Soft: gsl/LICENSE (Microsoft GSL)" "$AL" "openal-soft-$ALV/gsl/LICENSE"
text "OpenAL Soft: docs/hrtf.txt (where its default HRTF data set comes from)" "$AL" "openal-soft-$ALV/docs/hrtf.txt"
