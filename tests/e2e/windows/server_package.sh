#!/bin/bash
# The Windows server package (packaging/windows/server.sh) as an owner uses it, under Wine on a virtual screen in a
# container with no network: the zip unpacked whole, the first account and the players' address set up, the song list
# imported from a saved one (made-up data, tests/e2e/web/seed.py), the server started in the background, its health,
# its pages, the installer it brings handed out by the Download page, its status, the invite and the firewall's
# commands, the launcher of the same release connecting to it and signing in, then stop; and a run in the
# foreground, stopped from another process by the same program. Each step says PASS or FAIL; the exit code is the
# number that failed.
#
#   tests/e2e/windows/server_package.sh ZIP OUT_DIR [LAUNCHER_PACKAGE]
#
# LAUNCHER_PACKAGE is a release's full update package (openDMT3-<version>-full.nupkg): its openDMT3-cmd.exe is the
# launcher that connects. Without it that step is left out. The container is odt3-srv-wine (OPENDMT3_E2E_NAME's
# -wine when it is set).
set -u
ZIP=$(realpath "${1:?usage: server_package.sh ZIP OUT_DIR [LAUNCHER_PACKAGE]}")
OUT=$(realpath -m "${2:?}")
LAUNCHER=${3:+$(realpath "$3")}
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
C=${OPENDMT3_E2E_NAME:-odt3-srv}-wine
mkdir -p "$OUT"
rm -rf "$OUT/seed"
docker rm -f "$C" >/dev/null 2>&1
# The made-up song list, as the launcher saves one, made with this tree's own code (no game file anywhere).
PYTHONPATH="$REPO" python3 "$REPO/tests/e2e/web/seed.py" "$OUT/seed" > "$OUT/seed.log" 2>&1 \
  || { cat "$OUT/seed.log"; echo "FAIL the made-up song list"; exit 1; }
mounts=(-v "$ZIP:/in/package.zip:ro" -v "$OUT/seed/openDMT3-song-list.zip:/in/song-list.zip:ro" -v "$OUT:/out")
[ -n "$LAUNCHER" ] && mounts+=(-v "$LAUNCHER:/in/launcher.nupkg:ro")
docker run --rm --name "$C" --network none -e PYTHONDONTWRITEBYTECODE=1 "${mounts[@]}" opendmt3-wine:local bash -c '
  set -u
  failed=0
  # One step: its name and the status of what was just checked (taken first, so the name may run commands of its own).
  step() { if [ "$2" = 0 ]; then echo "PASS $1"; else echo "FAIL $1"; failed=$((failed + 1)); fi; }
  Xvfb :99 -screen 0 1280x800x24 -nolisten tcp >/dev/null 2>&1 &
  export WINEPREFIX=/w DISPLAY=:99 WINEDLLOVERRIDES="mscoree,mshtml=" WINEDEBUG=-all
  # The loopback interface is all a container without network has; the server and the launcher meet there.
  ip link set lo up 2>/dev/null
  wineboot -i >/dev/null 2>&1; wineserver -w
  # The zip unpacked whole, as the readme asks, into a folder of the owner'"'"'s own.
  python3 -c "import zipfile; zipfile.ZipFile(\"/in/package.zip\").extractall(\"/w/drive_c/srv\")"
  top=$(ls -d /w/drive_c/srv/opendmt3-server-*-windows-x64)
  name=$(basename "$top")
  cd "$top"
  srv() { wine "C:\\srv\\$name\\opendmt3-server.exe" "$@" 2>>/out/wine-errors.txt | tr -d "\r"; return ${PIPESTATUS[0]}; }
  get() { python3 -c "import sys, urllib.request; r = urllib.request.urlopen(sys.argv[1], timeout=5); print(r.status); sys.stdout.write(r.read().decode(\"utf-8\", \"replace\"))" "$1"; }
  ls opendmt3-server.exe README.txt LICENSE.txt licenses/NOTICES.txt installer/*.exe "Stop the server.cmd" >/dev/null 2>&1
  r=$?; step "the package holds the program, its readme, licences, shortcuts and the installer it brings" $r
  srv --version > /out/version.txt; grep -q "openDMT3 server" /out/version.txt
  r=$?; step "opendmt3-server.exe --version: $(cat /out/version.txt)" $r
  srv setup --admin BOSS --password pass1234 --address 127.0.0.1 > /out/setup.txt 2>&1
  grep -q "made BOSS" /out/setup.txt && [ -f data/settings.json ]
  r=$?; step "setup makes the first account, and the data folder is beside the program" $r
  srv catalog "Z:\\in\\song-list.zip" > /out/catalog.txt 2>&1
  grep -qi "song" /out/catalog.txt && [ -f data/catalog.json ]
  r=$?; step "the song list imported from a saved one" $r
  srv start > /out/start.txt 2>&1
  r=$?; step "start: in the background" $r
  get http://127.0.0.1:4730/health > /out/health.txt 2>&1; grep -q "\"ok\":true" /out/health.txt
  r=$?; step "/health answers: $(tail -c 60 /out/health.txt)" $r
  get http://127.0.0.1:4730/ > /out/home.html 2>&1; head -1 /out/home.html | grep -q 200
  r=$?; step "the site answers" $r
  [ -f data/downloads/openDMT3-win-Setup.exe ] && cmp -s data/downloads/openDMT3-win-Setup.exe installer/*.exe
  r=$?; step "the installer it brings is in the downloads folder" $r
  python3 - > /out/api.txt 2>&1 <<"PY"
import json, urllib.request
def call(path, token=None, body=None):
    request = urllib.request.Request("http://127.0.0.1:4730" + path, data=json.dumps(body).encode() if body else None,
                                     headers=dict({"Content-Type": "application/json"},
                                                  **({"Authorization": "Bearer " + token} if token else {})))
    return json.loads(urllib.request.urlopen(request, timeout=10).read())
token = call("/api/v1/session", body={"login_id": "BOSS", "password": "pass1234"})["token"]
songs = call("/api/v1/songs", token)
download = call("/api/v1/download", token)
invite = call("/api/v1/server/invite", token)
print("songs", len(songs.get("songs", songs)), "installer", bool(download.get("installer")), "invite", invite["address"])
assert len(songs.get("songs", songs)) >= 4 and download.get("installer") and invite["svg"].startswith("<svg")
PY
  r=$?; step "the API: the songs, the installer to download, the invite ($(tail -1 /out/api.txt))" $r
  srv status > /out/status.txt 2>&1
  r=$?; step "status: $(head -1 /out/status.txt)" $r
  srv invite > /out/invite.txt 2>&1; grep -q "Players open http://127.0.0.1:4730/" /out/invite.txt
  r=$?; step "invite prints the address and its QR code" $r
  srv firewall --print > /out/firewall.txt 2>&1; grep -q "localport=4725" /out/firewall.txt && grep -q "localport=4730" /out/firewall.txt
  r=$?; step "firewall --print: the two rules" $r
  if [ -f /in/launcher.nupkg ]; then
    python3 -c "import zipfile; z = zipfile.ZipFile(\"/in/launcher.nupkg\"); [z.extract(n, \"/w/drive_c/launcher-pkg\") for n in z.namelist() if n.startswith(\"lib/app/\")]"
    l="C:\\launcher-pkg\\lib\\app\\openDMT3-cmd.exe"
    echo pass1234 | wine "$l" --server http://127.0.0.1:4730/ --sign-in BOSS > /out/launcher.txt 2>&1
    wine "$l" --status >> /out/launcher.txt 2>&1
    tr -d "\r" < /out/launcher.txt | grep -q "signed in as BOSS (BOSS)"
    r=$?; step "the launcher connects to it and signs in: $(tr -d "\r" < /out/launcher.txt | grep "plays:")" $r
  fi
  srv stop > /out/stop.txt 2>&1; grep -q "The server stopped." /out/stop.txt
  r=$?; step "stop: the server stopped by itself" $r
  ! get http://127.0.0.1:4730/health > /dev/null 2>&1
  r=$?; step "nothing answers after the stop" $r
  # The same program in the foreground (the double click), stopped from another process.
  srv run --no-browser > /out/run.txt 2>&1 &
  front=$!
  for i in $(seq 60); do get http://127.0.0.1:4730/health > /dev/null 2>&1 && break; sleep 1; done
  get http://127.0.0.1:4730/health > /dev/null 2>&1
  r=$?; step "run: in the foreground" $r
  srv stop > /out/stop2.txt 2>&1
  for i in $(seq 30); do kill -0 $front 2>/dev/null || break; sleep 1; done
  ! kill -0 $front 2>/dev/null && grep -q "The server stopped." /out/stop2.txt && grep -q "To stop it" /out/run.txt
  r=$?; step "a run in the foreground stops when stop asks it from another process" $r
  # The banner the run printed: the logo, the version and the addresses in a box (plain: the output is a file).
  grep -q "| This PC   http://127.0.0.1:4730/" /out/run.txt && grep -q "server $(sed "s/openDMT3 server //" /out/version.txt)" /out/run.txt
  r=$?; step "the run printed its banner with the addresses in a box" $r
  srv repair > /out/repair.txt 2>&1 && grep -q "the package.s files are as they were made" /out/repair.txt
  r=$?; step "repair: the package files, the data folder and the ports as they should be" $r
  rm -f _internal/opendmt3/server/web/static/site.css
  ! srv repair > /out/repair2.txt 2>&1; grep -q "site.css" /out/repair2.txt
  r=$?; step "repair names a file taken out of the package" $r
  python3 -c "import zipfile; z = zipfile.ZipFile(\"/in/package.zip\"); z.extract(\"$name/_internal/opendmt3/server/web/static/site.css\", \"/w/drive_c/srv\")"
  srv remove --delete-data --yes > /out/remove.txt 2>&1 && [ ! -d data ] && ls opendmt3-backup-*.sqlite > /dev/null
  r=$?; step "remove --delete-data: the data deleted, its last backup kept beside the folder" $r
  tail -n 3 /out/run.txt > /out/server-log-tail.txt
  wineserver -k 2>/dev/null
  echo "failed: $failed"
  exit $failed
'
