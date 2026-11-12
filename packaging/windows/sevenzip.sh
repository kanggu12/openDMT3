#!/bin/bash
# The official 7-Zip for Windows that the launcher brings (7z.exe, 7z.dll, its License.txt and readme.txt), taken out
# of the official release's installer without running it: the release's static 7-Zip for Linux reads the installer,
# in a container with no network. Both downloads are checked against the pinned hashes before every use, and kept in
# OUT_DIR/cache. The launcher lists, tests and unpacks the game's archives with it (the distributions' p7zip cannot
# open RAR5); the same release as OpenDMTQ's, and as the server image's 7-Zip for Linux.
#   packaging/windows/sevenzip.sh OUT_DIR      -> OUT_DIR/7zip (build.sh, and CI's native job for the windows job)
set -euo pipefail
OUT=$(realpath -m "${1:?usage: sevenzip.sh OUT_DIR}")
SEVENZIP_VERSION=25.01
SEVENZIP_WIN_URL=https://www.7-zip.org/a/7z2501-x64.exe
SEVENZIP_WIN_SHA256=78afa2a1c773caf3cf7edf62f857d2a8a5da55fb0fff5da416074c0d28b2b55f
SEVENZIP_LINUX_URL=https://www.7-zip.org/a/7z2501-linux-x64.tar.xz
SEVENZIP_LINUX_SHA256=4ca3b7c6f2f67866b92622818b58233dc70367be2f36b498eb0bdeaaa44b53f4
mkdir -p "$OUT/cache"
# Fetched once; a copy from an earlier run is checked like a new one.
[ -f "$OUT/cache/7z-win.exe" ] || curl -fsSL -o "$OUT/cache/7z-win.exe" "$SEVENZIP_WIN_URL"
echo "$SEVENZIP_WIN_SHA256  $OUT/cache/7z-win.exe" | sha256sum -c --quiet
[ -f "$OUT/cache/7z-linux.tar.xz" ] || curl -fsSL -o "$OUT/cache/7z-linux.tar.xz" "$SEVENZIP_LINUX_URL"
echo "$SEVENZIP_LINUX_SHA256  $OUT/cache/7z-linux.tar.xz" | sha256sum -c --quiet
rm -rf "$OUT/7zip"
mkdir -p "$OUT/7zip"
# The server image's base: Python reads the .tar.xz (the slim image has no xz program), then the Linux 7-Zip takes the
# four files out of the Windows installer. As the calling user, so the files are theirs (a CI runner is no root). Its
# container has a name of its own (odt3-7zip-*, or OPENDMT3_E2E_NAME's -7zip-*, as the test runs name theirs), so a
# run that fetches it (tests/e2e/ui/run_wine.sh) tells it from any other.
docker run --rm --name "${OPENDMT3_E2E_NAME:-odt3}-7zip-$$" --network none -u "$(id -u):$(id -g)" -v "$OUT:/out" \
  python:3.12-slim-bookworm sh -c "
    python -c \"import tarfile; tarfile.open('/out/cache/7z-linux.tar.xz').extract('7zzs', '/tmp', filter='data')\" &&
    chmod 0755 /tmp/7zzs &&
    /tmp/7zzs e -y -bso0 -bsp0 -o/out/7zip /out/cache/7z-win.exe 7z.exe 7z.dll License.txt readme.txt"
ls "$OUT/7zip/7z.exe" "$OUT/7zip/7z.dll" "$OUT/7zip/License.txt" "$OUT/7zip/readme.txt" >/dev/null
# Not executable here: a Windows program is never started from this machine (WSL would hand it to Windows).
chmod 0644 "$OUT/7zip/"*
echo "7-Zip $SEVENZIP_VERSION for Windows: $OUT/7zip"
