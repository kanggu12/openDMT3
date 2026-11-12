#!/bin/bash
# A release of openDMT3, made on the release machine: the one that holds the project's update-signing key, which never
# leaves it (launchers put in only packages signed with it: opendmt3/core/signing.py). In order:
#   1. the tag, __version__ in opendmt3/__init__.py and CHANGELOG.md name one version, with notes for it
#      (.github/release_notes.py: no section, no release);
#   2. with --publish: the tag is this commit, the tree has nothing uncommitted, and the tag is on GitHub (what is
#      built is what is tagged, and the release is made from that tag);
#   3. the launcher and its installer built as packaging/windows/build.sh builds them, looking for updates in this
#      repository's releases, every update package signed with the key and its signature checked;
#   4. with --publish: the GitHub release, titled with the tag itself (v1.2.3), the changelog's section as its notes
#      (GitHub's compare link under them), with the installer and the files launchers update from.
# Without --publish it stops after step 3 and shows the release it would make: a rehearsal. With no key named the
# rehearsal's packages are unsigned, and it says so; publishing needs them signed.
#
#   OPENDMT3_SIGNING_KEY=<the key's file> packaging/release.sh vX.Y.Z OUT_DIR [--publish]
#
#   OPENDMT3_SIGNING_KEY    the key's file: named here and nowhere else (no path is tried when it is not set)
#   OPENDMT3_UPDATE_SOURCE  where the launchers look for updates (default: the GitHub repository of the remote "origin")
#   OPENDMT3_PREVIOUS_RELEASE  the previous release's full package, or the folder of its build's releases: the delta
#                           package is made from it (packaging/windows/build.sh), so a launcher of that version downloads
#                           only what changed
set -euo pipefail
USAGE="usage: packaging/release.sh vX.Y.Z OUT_DIR [--publish]"
TAG=${1:?$USAGE}
OUT=$(realpath -m "${2:?$USAGE}")
# Publishing is asked for by name; anything else after the folder is a mistake, not a rehearsal.
PUBLISH=no
case "${3:-}" in
  "") ;;
  --publish) PUBLISH=yes ;;
  *) echo "$USAGE" >&2; exit 2 ;;
esac
REPO=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO"
# Each step says what it checks or makes before it starts, so a stop names the step it stopped in.
step() { printf '== %s\n' "$*"; }
mkdir -p "$OUT"

step "The tag, __version__ and CHANGELOG.md name one version"
python3 .github/release_notes.py "$TAG" > "$OUT/release-notes.md"
echo "notes: $OUT/release-notes.md ($(wc -l < "$OUT/release-notes.md") lines)"

if [ "$PUBLISH" = yes ]; then
  step "The tag is this commit, nothing is uncommitted, the tag is on GitHub"
  # The tag's commit, not the tag object: an annotated tag names a commit of its own.
  [ "$(git rev-parse -q --verify "refs/tags/$TAG^{commit}" || true)" = "$(git rev-parse HEAD)" ] \
    || { echo "$TAG is not this commit: tag it first (CONTRIBUTING.md, Versions and releases)" >&2; exit 1; }
  # Untracked files count too: the build reads the tree, not the commit.
  [ -z "$(git status --porcelain)" ] || { echo "the tree has changes that are not committed" >&2; exit 1; }
  # gh release create --verify-tag makes the release only from a tag GitHub already has.
  git ls-remote --exit-code --tags origin "refs/tags/$TAG" >/dev/null \
    || { echo "$TAG is not on origin: git push origin $TAG" >&2; exit 1; }
fi

step "Where the launchers look for updates"
if [ -z "${OPENDMT3_UPDATE_SOURCE:-}" ]; then
  origin=$(git remote get-url origin 2>/dev/null || true)
  # git@github.com:OWNER/NAME.git or https://github.com/OWNER/NAME(.git), as https://github.com/OWNER/NAME: the
  # address launchers read the releases from (client/updates.py), and the .sig files beside them.
  name=$(printf '%s' "$origin" | sed -E 's#^(git@github\.com:|https://github\.com/)##; s#\.git$##')
  [[ "$origin" != "$name" && "$name" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] \
    || { echo "no GitHub remote named origin: set OPENDMT3_UPDATE_SOURCE to the repository's address" >&2; exit 1; }
  OPENDMT3_UPDATE_SOURCE="https://github.com/$name"
fi
echo "updates from: $OPENDMT3_UPDATE_SOURCE"

step "The launcher and its installer"
# The key is the one named in the environment: no path is tried by itself.
KEY=${OPENDMT3_SIGNING_KEY:-}
# Publishing needs the key; the rehearsal builds without it, as build.sh does, and says so below.
if [ "$PUBLISH" = yes ] && [ ! -f "$KEY" ]; then
  echo "no signing key${KEY:+ at $KEY}: a release's packages are signed (OPENDMT3_SIGNING_KEY names the key's file)" >&2
  exit 1
fi
# A release's launcher takes the project's key alone: a test's key in the environment is a mistake here.
if [ -n "${OPENDMT3_TEST_UPDATE_KEY:-}" ]; then
  echo "OPENDMT3_TEST_UPDATE_KEY is set: that makes a test build, not a release" >&2
  exit 1
fi
BUILD="$OUT/build"
# The build log beside the notes: build.sh prints each stage, and a stop shows its last lines here too.
OPENDMT3_UPDATE_SOURCE="$OPENDMT3_UPDATE_SOURCE" OPENDMT3_SIGNING_KEY="$KEY" \
  packaging/windows/build.sh "$BUILD" > "$OUT/build.log" 2>&1 || { tail -n 40 "$OUT/build.log"; exit 1; }
echo "build log: $OUT/build.log"
# And the launcher as built says the same: the file a test build's key would be in is there and empty.
TEST_KEYS="$BUILD/dist/openDMT3/_internal/opendmt3/core/update-test-keys.txt"
[ -f "$TEST_KEYS" ] && [ ! -s "$TEST_KEYS" ] \
  || { echo "the launcher built takes a key besides the project's ($TEST_KEYS): not a release" >&2; exit 1; }

step "The files of the release"
# The installer people download, Velopack's packages with the project's signature beside each, and the feed files
# Velopack reads from a GitHub release (releases.win.json, RELEASES for older readers). vpk's portable zip and its own
# list of what it made are no part of a release: the installer installs, and the packages update.
files=("$BUILD/releases/openDMT3-win-Setup.exe" "$BUILD/releases/releases.win.json" "$BUILD/releases/RELEASES")
# This version's packages, the whole one and the delta from the previous release when one was made; the previous
# release's own package, kept beside them to make the delta, is in its own release already (Velopack looks for a
# package in every release of the repository).
packages=("$BUILD"/releases/openDMT3-"${TAG#v}"-*.nupkg)
[ -f "${packages[0]}" ] || { echo "the build made no update package in $BUILD/releases" >&2; exit 1; }
unsigned=0
for package in "${packages[@]}"; do
  files+=("$package")
  if [ -f "$package.sig" ]; then files+=("$package.sig"); else unsigned=$((unsigned + 1)); fi
done
for file in "${files[@]}"; do
  [ -f "$file" ] || { echo "missing: $file" >&2; exit 1; }
done
if [ "$unsigned" -gt 0 ]; then
  echo "$unsigned of ${#packages[@]} packages are not signed (no key named): launchers would not put them in"
  [ "$PUBLISH" = no ] || exit 1
else
  # Each signature against the keys built into the launcher (opendmt3/core/signing.py), as a launcher checks it.
  python3 -m opendmt3.core.signing check "${packages[@]}"
fi
sha256sum "$BUILD/releases/openDMT3-win-Setup.exe"

# The release: the tag as its title, the changelog's section as its notes, GitHub's compare link under them.
release=(gh release create "$TAG" "${files[@]}" --title "$TAG" --notes-file "$OUT/release-notes.md" --generate-notes
         --verify-tag)
if [ "$PUBLISH" = no ]; then
  step "Rehearsal: the release it would make (packaging/release.sh $TAG OUT_DIR --publish makes it)"
  printf '  %q\n' "${release[@]}"
  exit 0
fi
step "The GitHub release $TAG"
"${release[@]}"
step "published $TAG"
