#!/bin/bash
# How the game judges a press with the audio offset, on either renderer (OPENDMT3_WINE_GPU=1 for this PC's GPU,
# gpu.sh): two runs of gpu/holds.sh's play (the guest's tutorial, then a song; no holds), the layer pressing each plain
# note itself (native/cardreader/press.c, OPENDMT3_PRESS_LATE) at the first frame the score's own count reaches the
# note's time plus MS or plus nothing, the notes taking the two in turn; the song's presses judged (the tutorial plays
# itself, its notes judged on their own as soon as the count shown is past them):
#   offset  OPENDMT3_AUDIO_OFFSET=MS: a press MS after its note (where a player hears it on a device MS late) is
#           judged on its time, one on the note's own time MS early
#   none    no offset: a press on the note's time is judged on it, one MS after it MS late
# line.py presses judges each (within a frame after the time expected, the distance the game took being the count it
# judged less the note's), and line.py lag the count the line and the notes are drawn by: MS behind the score's own
# with the offset, the score's own with none, within half a tick. MS is OFFSET_MS, 80 unless given (within the game's
# outermost window, so each early or late press is still judged). Nothing reaches a real screen or a speaker.
#
#   [OPENDMT3_WINE_GPU=1] [OFFSET_MS=80] [OPENDMT3_E2E_NAME=odt3-judge]
#     tests/e2e/windows/gpu/judge.sh GAME_PARENT BUILD_DIR OUT_DIR [LINK_SOURCE] [WINE_DLLS]
#
# The arguments are holds.sh's. Exit 0 when both runs played the tutorial to its end and every press was judged as
# expected.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=${1:?usage: judge.sh GAME_PARENT BUILD_DIR OUT_DIR [LINK_SOURCE] [WINE_DLLS]}
BUILD=${2:?}
OUT=$(realpath -m "${3:?}")
LINKS=${4:-}
DLLS=${5:-}
MS=${OFFSET_MS:-80}
export OPENDMT3_E2E_NAME=${OPENDMT3_E2E_NAME:-odt3-judge}
mkdir -p "$OUT"
code=0
# One run: its name, the offset, what each press time is expected to be judged as.
run() {
  local name=$1 offset=$2
  shift 2
  echo "$(date +%T) judge: $name (audio offset $offset ms, presses $MS and 0 ms after their notes in turn)"
  if ! HOLDS= TUT_HOLDS= MINIMISE= bash "$HERE/holds.sh" "$SRC" "$BUILD" "$OUT/$name" "$LINKS" "$DLLS" \
      "OPENDMT3_AUDIO_OFFSET=$offset" "OPENDMT3_PRESS_LATE=$MS,0" > "$OUT/$name.txt" 2>&1; then
    tail -5 "$OUT/$name.txt"
    echo "FAIL: the $name run did not play the tutorial and the song to their ends"
    code=1
    return
  fi
  # What the layer said of the offset and the presses, then the judgement.
  grep -E "^[0-9]+ (offset|press): [a-z]" "$OUT/$name/ingame.log" | grep -v "press: music from frame" | sed 's/^/  /'
  python3 "$HERE/line.py" presses "$OUT/$name/ingame.log" --last-music "$@" ||
    { echo "FAIL: the $name run's presses"; code=1; }
  python3 "$HERE/line.py" lag "$OUT/$name/line.csv" "$offset" || { echo "FAIL: the $name run's count shown"; code=1; }
}
run offset "$MS" "$MS=on" "0=early:$MS"
run none 0 "0=on" "$MS=late:$MS"
[ $code = 0 ] && echo "PASS: with an offset of $MS ms a press $MS ms after its note judged on time and one on it" \
  "$MS ms early; with none, on time and $MS ms late"
exit $code
