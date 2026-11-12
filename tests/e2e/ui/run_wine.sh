#!/bin/bash
# The launcher's screens at Windows scaling: tests/e2e/ui/shots.py run by Windows' Python and Tk under Wine, on a
# virtual screen, with Windows' DPI set as a person sets their display's scale (100 %, 125 %, 150 % or 200 %). The
# window opens at the size the launcher itself would take there (1180x760 at 100 %, never more than 92 % of the
# screen), and every screen, dialog and page is measured as on Linux: text cut off, anything past the edge or hidden
# under the bottom bar with no way to scroll to it, a dialog's layout. Every page is measured again at the smallest
# size the window takes (shots.py --smallest). No network inside; nothing reaches the person's own screen.
#
#   tests/e2e/ui/run_wine.sh OUT_DIR [COMBO ...]
#
# A COMBO is LANG-SCALE-WIDTHxHEIGHT (the screen's pixels), for example ko-150-1920x1080. Without any: en and ko at
# 100 %, 125 % and 150 % on 1920x1080 and at 200 % on 3840x2160. Uses the image packaging/windows/build.sh makes
# (opendmt3-winbuild:local), which holds Windows' Python with the launcher's libraries.
# The made-up archives the screens list, test and unpack are made and read with the official 7-Zip for Windows, the
# one the launcher brings: packaging/windows/sevenzip.sh fetches its pinned release, checks it and takes 7z.exe out
# of it into OUT_DIR/7zip (the downloads are kept in OUT_DIR/cache: put them there first on a PC with no network).
set -u
OUT=$(realpath -m "${1:?usage: tests/e2e/ui/run_wine.sh OUT_DIR [LANG-SCALE-WxH ...]}")
shift
# OPENDMT3_REPO points the run at another copy, as run.sh's does (the checks are tried on a copy with a planted fault).
REPO=${OPENDMT3_REPO:-$(cd "$(dirname "$0")/../../.." && pwd)}
COMBOS=("$@")
[ ${#COMBOS[@]} -gt 0 ] || COMBOS=(en-100-1920x1080 ko-100-1920x1080 en-125-1920x1080 ko-125-1920x1080
                                   en-150-1920x1080 ko-150-1920x1080 en-200-3840x2160 ko-200-3840x2160)
docker image inspect opendmt3-winbuild:local >/dev/null 2>&1 || { echo "no opendmt3-winbuild:local: run packaging/windows/build.sh first"; exit 2; }
mkdir -p "$OUT"
# The container's own user writes the screenshots here.
chmod 777 "$OUT"
# The 7-Zip for Windows, checked against the pins before every run (a copy left from an earlier run is checked too).
"$REPO/packaging/windows/sevenzip.sh" "$OUT" >/dev/null || { echo "FAIL: no 7-Zip for Windows (packaging/windows/sevenzip.sh)"; exit 2; }
# Each combo's container has a name of its own (odt3-uiwine-*, or the one OPENDMT3_E2E_NAME gives, with this run's
# process number), so it is told from any other run's; one still there when the run is stopped is removed with it.
NAME=${OPENDMT3_E2E_NAME:-odt3-uiwine}-$$
trap 'docker rm -f $(docker ps -aq --filter "name=^$NAME-") >/dev/null 2>&1' EXIT
failed=0
for combo in "${COMBOS[@]}"; do
  IFS=- read -r lang scale screen <<<"$combo"
  sw=${screen%x*}; sh=${screen#*x}
  # Windows' DPI for that scale (96 at 100 %), and the window the launcher opens there (app.py's rule).
  dpi=$((96 * scale / 100))
  w=$(python3 -c "print(min(round(1180 * $scale / 100), int($sw * 0.92)))")
  h=$(python3 -c "print(min(round(760 * $scale / 100), int($sh * 0.92)))")
  echo "== $combo: DPI $dpi, window ${w}x${h}"
  # The shots of one combo take about three minutes: a screen that waits for an answer no step gives would hold the
  # run for good, so each has 20.
  docker run --rm --name "$NAME-$combo" --network none -e OPENDMT3_VIRTUAL_DISPLAY=1 -e PYTHONDONTWRITEBYTECODE=1 \
    -e 'OPENDMT3_7ZIP=Z:\out\7zip\7z.exe' -v "$REPO:/src:ro" -v "$OUT:/out" opendmt3-winbuild:local bash -c "
      export WINEDEBUG=-all DISPLAY=:99
      Xvfb :99 -screen 0 ${sw}x${sh}x24 -nolisten tcp >/dev/null 2>&1 &
      sleep 1
      # Windows' scale: the DPI every program on this Windows is told.
      wine reg add 'HKCU\\Control Panel\\Desktop' /v LogPixels /t REG_DWORD /d $dpi /f >/dev/null 2>&1
      wine reg add 'HKLM\\System\\CurrentControlSet\\Hardware Profiles\\Current\\Software\\Fonts' /v LogPixels /t REG_DWORD /d $dpi /f >/dev/null 2>&1
      wineserver -w
      cd /src && timeout 1200 wine 'C:\\python\\python.exe' tests/e2e/ui/shots.py --out 'Z:\\out\\$combo' --lang $lang \
        --size ${w}x${h} --smallest
    " > "$OUT/$combo.log" 2>&1
  line=$(grep -E "screens, [0-9]+ problems" "$OUT/$combo.log" | tail -1)
  echo "  ${line:-no result: see $OUT/$combo.log}"
  case "$line" in *" 0 problems"*) ;; *) failed=1 ;; esac
done
[ $failed = 0 ] && echo "PASS: every combo measured with 0 problems" || { echo "FAIL: see the logs in $OUT"; exit 1; }
