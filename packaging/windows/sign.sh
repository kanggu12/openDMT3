#!/bin/bash
# The signature beside each update package of one version (opendmt3/core/signing.py): launchers put in only signed
# updates, so a server handing out these packages, or anyone between it and a PC, cannot hand over a program of its
# own. Run by packaging/windows/build.sh once vpk has made the packages.
#
#   OPENDMT3_SIGNING_KEY=<the key's file> packaging/windows/sign.sh RELEASES_DIR VERSION
#
# The key is named in the environment and nowhere else: no path is tried when the variable is not set, so a build
# signs only when whoever runs it says with which key. Without the variable nothing is signed, and the build says so
# (a launcher will not put those packages in as updates). The packages are then checked as the launcher this build
# made will check them: against the keys built in, and against a test build's own (OPENDMT3_TEST_UPDATE_KEY, the public
# key build.sh wrote into that launcher). Signatures by a key no launcher takes are removed again, and the build stops.
set -euo pipefail
USAGE="usage: sign.sh RELEASES_DIR VERSION"
RELEASES=${1:?$USAGE}
VERSION=${2:?$USAGE}
REPO=$(cd "$(dirname "$0")/../.." && pwd)
# This version's packages, the whole one and the delta when one was made: what is signed and published (the previous
# release's package, kept beside them for the delta, was signed with its own release).
PACKAGES=("$RELEASES"/openDMT3-"$VERSION"-*.nupkg)
[ -f "${PACKAGES[0]}" ] || { echo "no package of $VERSION in $RELEASES" >&2; exit 1; }
KEY=${OPENDMT3_SIGNING_KEY:-}
if [ -z "$KEY" ]; then
  echo "no signing key named (OPENDMT3_SIGNING_KEY): these packages are not signed, so launchers will not put them in as updates"
  exit 0
fi
# Named and not there: a mistake in the name, never a build that quietly signs nothing.
[ -f "$KEY" ] || { echo "no signing key at $KEY (OPENDMT3_SIGNING_KEY)" >&2; exit 1; }
cd "$REPO"
python3 -m opendmt3.core.signing sign "$KEY" "${PACKAGES[@]}"
if ! python3 -m opendmt3.core.signing check ${OPENDMT3_TEST_UPDATE_KEY:+--key "$OPENDMT3_TEST_UPDATE_KEY"} "${PACKAGES[@]}"; then
  # A signature no launcher takes says nothing for the package: none is left beside it.
  rm -f "${PACKAGES[@]/%/.sig}"
  echo "the packages are not signed with a key the launcher takes" >&2
  exit 1
fi
