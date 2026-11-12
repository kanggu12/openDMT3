#!/bin/bash
# The site's layout check: the server in Docker with made-up data (seed.py), headless Chrome in Docker (shoot.js),
# both on a network of their own with no way out. Every page in English and Korean at a desktop and a phone width,
# signed in; it fails when any page sticks out past the right edge, cuts words off inside a box that hides its
# overflow, shows a cell of a stacked row with no label at the phone width, a word of the phone menu that does not fit
# or a button whose words are out of its middle (measure.js), when a question asked first does not fit or keep its
# promise, when the songs filter, the message
# to send, the list to look at, a token shown once, an upload field, the upload or maintenance's card misbehaves, or
# when fewer pages were looked at than there are.
# Then a second server with nothing in it, its browser on the server's own network (so the server sees the server PC
# itself: empty.js): the first-run page, the owner made, a wrong password, every page empty, the Download page without
# an installer, the message to send with an address only that PC reaches, and a plain player, measured the same way.
#
#   tests/e2e/web/run.sh OUT_DIR        (screenshots in OUT_DIR/shots, the per-page lines in OUT_DIR/shoot.txt and
#                                        OUT_DIR/empty.txt)
#
# OPENDMT3_REPO points the run at another copy (the check itself is tested on a copy with a planted fault:
# tests/e2e/web/selftest.sh).
set -u
OUT=$(realpath -m "${1:?usage: run.sh OUT_DIR}")
REPO=${OPENDMT3_REPO:-$(cd "$(dirname "$0")/../../.." && pwd)}
# 25 pages (the sign-in page, 17 signed in, the players page with a message to send, the Status page with a line to
# look at, the songs page filtered, the account page with a token just made, the backups page after an upload, the
# Song list tab after a song list's upload, the Status page with maintenance off) x 2 widths x 2 languages; five
# questions (a player deleted, a player's plays reset, a new password, every play reset, a backup deleted, a token
# revoked), one message, one list to look at, one songs filter, one token, one upload of each kind and one maintenance
# off and on each round.
EXPECTED_PAGES=100
EXPECTED_DIALOGS=24
EXPECTED_ROUNDS=4
# The empty server (empty.js): the first-run page in 2 languages x 2 widths and once refused in each language, the
# sign-in page after the owner was made, a wrong password in each language, 18 pages x 2 widths x 2 languages, the
# players page with an account made x 2 x 2, and a plain player's 4 pages x 2 x 2; its states that must hold: the
# first run (4) and refused (2), the owner made (1), a wrong password (2), the Download page and the Status page of
# the empty server (4 each), the message (4), a plain player (4).
EXPECTED_EMPTY_PAGES=101
EXPECTED_EMPTY_STATES=25
# Names of this run's own (odt3-*, with its process number), so two runs at once (the self-test's and another's, or
# CI's) never stop each other's server or use each other's image; each goes when its run ends.
# (odt3-web-*, or the name OPENDMT3_E2E_NAME gives in its place, so whoever runs several at once tells theirs apart.)
NAME=${OPENDMT3_E2E_NAME:-odt3-web}
TAG=opendmt3-webcheck:run-$$
NET=$NAME-net-$$
SRV=$NAME-server-$$
# The second server, with nothing in it.
EMPTY=$NAME-empty-$$
# The browsers too: a run cut short by its time limit leaves its container behind otherwise.
cleanup() { docker rm -f "$SRV" "$EMPTY" "$NAME-browser-$$" "$NAME-empty-browser-$$" "$NAME-seed-$$" >/dev/null 2>&1; docker network rm "$NET" >/dev/null 2>&1; docker image rm "$TAG" >/dev/null 2>&1; }
cleanup
mkdir -p "$OUT/shots" "$OUT/data" "$OUT/empty-data"
# The containers' own users write here.
chmod 777 "$OUT/shots" "$OUT/data" "$OUT/empty-data"
# The server image from the tree under test, every time (a tag of its own: a copy with a planted fault never
# becomes the image other tests use).
docker build -q -f "$REPO/packaging/docker/Dockerfile" -t "$TAG" "$REPO" >/dev/null || { echo "FAIL: the image did not build"; exit 1; }
docker run --rm --name "$NAME-seed-$$" --network none -e PYTHONPATH=/app -v "$OUT/data:/data" -v "$REPO/tests/e2e/web:/t:ro" --entrypoint python "$TAG" /t/seed.py /data \
  || { echo "FAIL: the data did not seed"; exit 1; }
# The song list the seed saved, where the browser can upload it from.
cp "$OUT/data/openDMT3-song-list.zip" "$OUT/shots/"
docker network create --internal "$NET" >/dev/null
# The server is given the address its players reach it at (as ./dmt3 setup keeps the one chosen): the message to send
# a player must carry that one, not the address the browser of this run reaches it by (http://site:4730).
docker run -d --name "$SRV" --network "$NET" --network-alias site -e OPENDMT3_SITE_ADDRESS=http://192.168.0.5:4730/ \
  -v "$OUT/data:/data" "$TAG" >/dev/null
# Up when its health check answers (from inside: the network has no way to this PC).
for _ in $(seq 60); do
  docker exec "$SRV" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4730/health', timeout=2)" \
    >/dev/null 2>&1 && break
  sleep 0.5
done
# The upload field's words in both languages, from the site's own table, for the browser to hold the page to.
WORDS=$(cd "$REPO" && python3 -I -c 'import json, sys; sys.path.insert(0, "."); from opendmt3.server.web.strings import TEXT
print(json.dumps({k: TEXT[k] for k in ("upload.none", "upload.choose", "upload.change")}))') || { echo "FAIL: the words"; exit 1; }
timeout 300 docker run --rm --name "$NAME-browser-$$" --network "$NET" -e SITE=http://site:4730 -e NODE_PATH=/usr/src/app/node_modules -e WORDS="$WORDS" \
  -v "$REPO/tests/e2e/web:/w:ro" -v "$OUT/shots:/out" -w /usr/src/app zenika/alpine-chrome:with-puppeteer node /w/shoot.js \
  > "$OUT/shoot.txt" 2>&1
status=$?
docker logs "$SRV" > "$OUT/server.log" 2>&1
# The empty server: no data seeded, no network at all but its own (the browser joins it, so its visits come from
# 127.0.0.1, which the first-run page asks for).
docker run -d --name "$EMPTY" --network none -v "$OUT/empty-data:/data" "$TAG" >/dev/null
for _ in $(seq 60); do
  docker exec "$EMPTY" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4730/health', timeout=2)" \
    >/dev/null 2>&1 && break
  sleep 0.5
done
timeout 300 docker run --rm --name "$NAME-empty-browser-$$" --network "container:$EMPTY" -e NODE_PATH=/usr/src/app/node_modules \
  -v "$REPO/tests/e2e/web:/w:ro" -v "$OUT/shots:/out" -w /usr/src/app zenika/alpine-chrome:with-puppeteer node /w/empty.js \
  > "$OUT/empty.txt" 2>&1
empty_status=$?
docker logs "$EMPTY" > "$OUT/empty-server.log" 2>&1
cleanup
summary=$(tail -1 "$OUT/shoot.txt")
empty=$(tail -1 "$OUT/empty.txt")
echo "$summary"
echo "$empty"
grep -hE "STICKS OUT|CUT OFF|NO LABEL|MENU CUT|BUTTON ASKEW|FAULT" "$OUT/shoot.txt" "$OUT/empty.txt"
python3 - "$summary" "$status" "$EXPECTED_PAGES" "$EXPECTED_DIALOGS" "$EXPECTED_ROUNDS" "$empty" "$empty_status" \
  "$EXPECTED_EMPTY_PAGES" "$EXPECTED_EMPTY_STATES" <<'PY'
import json, sys
summary, status, pages, dialogs, rounds = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
empty, empty_status, empty_pages, empty_states = sys.argv[6], int(sys.argv[7]), int(sys.argv[8]), int(sys.argv[9])
try:
    s = json.loads(summary)
except ValueError:
    sys.exit("FAIL: the browser run ended early (exit %d); see shoot.txt" % status)
try:
    e = json.loads(empty)
except ValueError:
    sys.exit("FAIL: the empty server's browser run ended early (exit %d); see empty.txt" % empty_status)
problems = []
if s["pages"] != pages:
    problems.append("looked at %d pages, not %d" % (s["pages"], pages))
if s["dialogs"] != dialogs:
    problems.append("opened the questions %d times, not %d" % (s["dialogs"], dialogs))
if e["pages"] != empty_pages:
    problems.append("looked at %d pages of the empty server, not %d" % (e["pages"], empty_pages))
if e["states"] != empty_states or e["state_faults"]:
    problems.append("the empty server's states: %d of %d did not hold" % (e["state_faults"], e["states"]))
# The layout's measure, the full server's pages and the empty one's together: each kind of fault and how many pages
# have it (the kinds' words are what docs/test-cases.md and selftest.sh look for).
for what, key in (("pages stick out", "sticking"), ("pages cut words off", "cut"),
                  ("pages have a cell with no label", "unlabelled"), ("pages cut the phone menu", "menu_cut"),
                  ("pages have a button's words out of its middle", "askew")):
    if s[key] + e[key]:
        problems.append("%s: %d" % (what, s[key] + e[key]))
if empty_status:
    problems.append("the empty server's browser exited %d" % empty_status)
if s["dialog_faults"]:
    problems.append("%d questions misbehaved" % s["dialog_faults"])
if s["filters"] != rounds or s["filter_faults"]:
    problems.append("the songs filter: %d of %d runs misbehaved" % (s["filter_faults"], s["filters"]))
if s["messages"] != rounds or s["message_faults"]:
    problems.append("the message to send: %d of %d runs misbehaved" % (s["message_faults"], s["messages"]))
if s["looks"] != rounds or s["look_faults"]:
    problems.append("the list to look at: %d of %d runs misbehaved" % (s["look_faults"], s["looks"]))
# Two upload fields a round, the Backups tab's and the Song list tab's.
if s["drops"] != 2 * rounds or s["drop_faults"]:
    problems.append("the upload fields: %d of %d misbehaved" % (s["drop_faults"], s["drops"]))
for what, done, faults in (("the token shown once", "tokens", "token_faults"), ("the upload", "uploads", "upload_faults"),
                           ("the song list's upload", "song_lists", "song_list_faults"),
                           ("maintenance off and on", "maintenances", "maintenance_faults")):
    if s[done] != rounds or s[faults]:
        problems.append("%s: %d of %d runs misbehaved" % (what, s[faults], s[done]))
if status:
    problems.append("the browser exited %d" % status)
print("FAIL: " + "; ".join(problems) if problems else "PASS: %d pages and %d of an empty server, nothing sticks out, "
      "no words cut off, no cell without a label, the phone menu whole, every button's words in its middle; %d "
      "questions fine; %d upload fields fine; the songs filter, the message to send, the list to look at, the token "
      "shown once, both uploads and maintenance off and on fine in %d runs; the empty server's %d states hold" % (
          s["pages"], e["pages"], s["dialogs"], s["drops"], rounds, e["states"]))
sys.exit(1 if problems else 0)
PY
