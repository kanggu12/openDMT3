#!/bin/bash
# A release of openDMT3, made on the release machine: the one that holds the project's update-signing key, which never
# leaves it (launchers put in only packages signed with it: opendmt3/core/signing.py). In order:
#   1. the tag, __version__ in opendmt3/__init__.py and CHANGELOG.md name one version, with notes for it
#      (.github/release_notes.py: no section, no release);
#   2. with --publish: the tag is this commit, the tree has nothing uncommitted, and the tag is on GitHub (what is
#      built is what is tagged, and the release is made from that tag);
#   3. the launcher and its installer built as packaging/windows/build.sh builds them, looking for updates in this
#      repository's releases, every update package signed with the key and its signature checked;
#   4. the release's files gathered into OUT_DIR/files by packaging/release_files.py, each named in lowercase with the
#      tool, its part and the version, then the systems it runs on or what it holds (the launcher's update files keep
#      Velopack's names, which installed launchers read), with opendmt3-<version>-sha256sums.txt over them:
#        opendmt3-launcher-<version>-windows-x64-installer.exe   the launcher's installer
#        opendmt3-server-<version>-linux-macos.zip           the server alone on Linux and macOS, for Docker Compose or
#                                                            Python
#        opendmt3-server-<version>-windows-x64.zip           the server on Windows, without Docker or Python
#        opendmt3-server-<version>-linux-installer.sh (-macos-)   the one-line install without Docker
#        opendmt3-server-<version>-helm-chart.tgz            the Helm chart
#        opendmt3-launcher-<version>-openal-sources.zip      the sources of OpenAL Soft and DSOAL, which it brings
#        openDMT3-<version>-full.nupkg (-delta), .sig, releases.win.json   the launcher's update files
#      (the Windows server package, built first by packaging/windows/server.sh with the installer just built in it,
#      and the chart, packaged by Helm's own image; the server's image goes to ghcr.io from .github/workflows/
#      release.yml on the tag, not into the release)
#   5. with --publish: the GitHub release, titled with the tag itself (v1.2.3), its notes one line on which file is whose
#      and one on the launcher's update files (no table: the files' names say it), then the changelog's section and the
#      compare link.
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
python3 .github/release_notes.py "$TAG" > "$OUT/changelog-section.md"
# The guides' download lines name this version's files (packaging/doc_versions.py --write puts it in).
python3 packaging/doc_versions.py

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
# The update packages: this version's, the whole one and the delta from the previous release when one was made; the
# previous release's own package, kept beside them to make the delta, is in its own release already (Velopack looks
# for a package in every release of the repository).
packages=("$BUILD"/releases/openDMT3-"${TAG#v}"-*.nupkg)
[ -f "${packages[0]}" ] || { echo "the build made no update package in $BUILD/releases" >&2; exit 1; }
unsigned=0
for package in "${packages[@]}"; do
  [ -f "$package.sig" ] || unsigned=$((unsigned + 1))
done
if [ "$unsigned" -gt 0 ]; then
  echo "$unsigned of ${#packages[@]} packages are not signed (no key named): launchers would not put them in"
  [ "$PUBLISH" = no ] || exit 1
else
  # Each signature against the keys built into the launcher (opendmt3/core/signing.py), as a launcher checks it.
  python3 -m opendmt3.core.signing check "${packages[@]}"
fi
# The installer, the update files, the server packages, the OpenAL sources and the SHA-256 sums, into one folder made
# again (release_files.py checks every name, each OpenAL archive against the build's SHA256SUMS, and every link of the
# server package's guides); FILES.md beside it lists them for the maintainer, not for the notes.
V=${TAG#v}
SERVER="$OUT/server"
rm -rf "$SERVER" && mkdir -p "$SERVER"
# The Windows server package, bringing the installer just built for the site's Download page.
OPENDMT3_SERVER_INSTALLER="$BUILD/releases/opendmt3-launcher-$V-windows-x64-installer.exe" \
  packaging/windows/server.sh "$OUT/server-windows" > "$OUT/server-windows.log" 2>&1 \
  || { tail -n 40 "$OUT/server-windows.log"; exit 1; }
cp "$OUT/server-windows/opendmt3-server-$V-windows-x64.zip" "$SERVER/"
# The Helm chart at this version, made by Helm's own image (no Helm needed on this machine); release_files.py gives it
# the release's name.
docker run --rm --network none -u "$(id -u):$(id -g)" -v "$PWD/deploy/helm:/charts:ro" -v "$SERVER:/out" \
  alpine/helm:3.16.4 package /charts/opendmt3 --version "$V" --app-version "$V" -d /out > /dev/null
FILES="$OUT/files"
python3 packaging/release_files.py "$TAG" "$BUILD" "$FILES" --server "$SERVER" > /dev/null
# Every file listed in the sums is there with that hash: what a downloader's sha256sum -c will say.
(cd "$FILES" && sha256sum -c --quiet "opendmt3-${TAG#v}-sha256sums.txt")
ls -l "$FILES"
# The notes: one line saying which file is whose (the files' own names say their part, version and system, so no table:
# a table of files in the notes only confused), one saying installed launchers fetch the update files by themselves
# (their names, which those launchers read, are the only ones not in that form), the changelog's section, then the
# compare link from the changelog's own link list. FILES.md stays beside the files for the maintainer's eye; it is not
# published.
compare=$(sed -n "s#^\[${TAG#v}\]: \(https://.*\)#\1#p" CHANGELOG.md)
[ -n "$compare" ] || { echo "CHANGELOG.md has no link for [${TAG#v}] at its end" >&2; exit 1; }
v=${TAG#v}
{ printf 'openDMT3 %s. Players install `opendmt3-launcher-%s-windows-x64-installer.exe`; server owners run `opendmt3-server-%s-windows-x64.zip` on Windows, `opendmt3-server-%s-linux-macos.zip` on Linux or macOS with Docker or Python, the `-linux-installer.sh` or `-macos-installer.sh` for a one-line install without Docker, or the Helm chart ([the server guide](https://github.com/kanggu12/openDMT3/blob/%s/docs/server.md)).\n\n' "$v" "$v" "$v" "$v" "$TAG"
  printf 'The `openDMT3-%s-*.nupkg` files, their `.sig` and `releases.win.json` are the launcher'\''s own update files, fetched by installed launchers: nothing to download by hand.\n\n' "$v"
  cat "$OUT/changelog-section.md"; printf '\n**Full Changelog**: %s\n' "$compare"; } \
  > "$OUT/release-notes.md"
echo "notes: $OUT/release-notes.md ($(wc -l < "$OUT/release-notes.md") lines)"
files=("$FILES"/*)

# The release: the tag as its title, the notes made above (GitHub's own notes would add a second compare link).
release=(gh release create "$TAG" "${files[@]}" --title "$TAG" --notes-file "$OUT/release-notes.md" --verify-tag)
if [ "$PUBLISH" = no ]; then
  step "Rehearsal: the release it would make (packaging/release.sh $TAG OUT_DIR --publish makes it)"
  printf '  %q\n' "${release[@]}"
  exit 0
fi
step "The GitHub release $TAG"
"${release[@]}"
step "published $TAG"
