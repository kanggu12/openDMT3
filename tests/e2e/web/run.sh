#!/bin/bash
# The site's layout check: the server in Docker with made-up data (seed.py), headless Chrome in Docker (shoot.js),
# both on a network of their own with no way out. Every page of the players' site and of the admin site (its own port,
# published on that network) in English and Korean at a desktop and two phone widths, signed in on each; it fails when
# any page sticks out past the right edge, cuts words off inside a box that hides its overflow, shows a cell of a
# stacked row with no label at the phone width, a word of the phone menu that does not fit, a button whose words are
# out of its middle, a number or a date broken over two lines, or a frame not its site's (measure.js), when a question
# asked first does not fit or keep its promise, when the songs filter, the message
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
# 32 pages (the players' site: its sign-in page, 10 pages signed in, and the admin pages' old address on its port; the
# admin site: its sign-in page, 12 pages signed in with two players' own pages and its Licenses page; then the players
# page with a message to send, the Status page with a line to look at, the songs page filtered, the account page with a
# token just made, the backups page after an upload, the Song list tab after a song list's upload, the Status page with
# maintenance off) x 3 widths (1280, 390, 360) x 2 languages; eight
# questions (a player deleted, a player's plays reset, a new password, every play reset, a backup deleted, a token
# revoked, a player banned, one's own account deleted), one message, one list to look at, one songs filter, one token, one upload of each kind and one maintenance
# off and on, and the toast and the phone's menu sheet pressed each round.
EXPECTED_PAGES=192
EXPECTED_DIALOGS=48
EXPECTED_ROUNDS=6
# The empty server (empty.js): the first-run page (the admin site's) in 2 languages x 3 widths and once refused in each
# language, the admin site's sign-in page after the owner was made, a wrong password in each language, 21 pages (11 of
# the players' site, 10 of the admin site) x 3 widths x 2 languages, the players page with an account made x 3 x 2, and
# a plain player's 4 pages (3, and the admin site's door refusing them) x 3 x 2; its states that must hold: the
# first run (6) and refused (2), the owner made (1), a wrong password (2), the Download page and the Status page of
# the empty server (6 each), the message (6), a plain player (6).
EXPECTED_EMPTY_PAGES=167
EXPECTED_EMPTY_STATES=35
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
cp "$OUT/data/opendmt3-song-list.zip" "$OUT/shots/"
docker network create --internal "$NET" >/dev/null
# The server is given the address its players reach it at (as ./dmt3 setup keeps the one chosen): the message to send
# a player must carry that one, not the address the browser of this run reaches it by (http://site:4730).
# The admin site listens on the container's every address, so the browser on this run's network reaches it at
# http://site:4731 (on a PC, ADMIN_BIND keeps the published port to the PC itself).
docker run -d --name "$SRV" --network "$NET" --network-alias site -e OPENDMT3_SITE_ADDRESS=http://192.168.0.5:4730/ \
  -e OPENDMT3_ADMIN_HOST=0.0.0.0 -v "$OUT/data:/data" "$TAG" >/dev/null
# Up when both sites' health checks answer (from inside: the network has no way to this PC).
for _ in $(seq 60); do
  docker exec "$SRV" python -c "import urllib.request; [urllib.request.urlopen('http://127.0.0.1:%d/health' % p, timeout=2) for p in (4730, 4731)]" \
    >/dev/null 2>&1 && break
  sleep 0.5
done
# The upload field's words in both languages, from the site's own table, for the browser to hold the page to.
WORDS=$(cd "$REPO" && python3 -I -c 'import json, sys; sys.path.insert(0, "."); from opendmt3.server.web.strings import TEXT
print(json.dumps({k: TEXT[k] for k in ("upload.none", "upload.choose", "upload.change")}))') || { echo "FAIL: the words"; exit 1; }
# The server by its own address on that network too, as a player on a LAN reaches it: plain http on an IP address, where
# the browser gives a page no clipboard (the Copy keys' other way is checked there).
LANIP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$SRV")
timeout 1500 docker run --rm --name "$NAME-browser-$$" --network "$NET" -e SITE=http://site:4730 -e ADMIN=http://site:4731 -e LANIP="$LANIP" -e NODE_PATH=/usr/src/app/node_modules -e WORDS="$WORDS" \
  -v "$REPO/tests/e2e/web:/w:ro" -v "$OUT/shots:/out" -w /usr/src/app zenika/alpine-chrome:with-puppeteer node /w/shoot.js \
  > "$OUT/shoot.txt" 2>&1
status=$?
docker logs "$SRV" > "$OUT/server.log" 2>&1
# The empty server: no data seeded, no network at all but its own (the browser joins it, so its visits come from
# 127.0.0.1, which the first-run page asks for).
docker run -d --name "$EMPTY" --network none -v "$OUT/empty-data:/data" "$TAG" >/dev/null
for _ in $(seq 60); do
  docker exec "$EMPTY" python -c "import urllib.request; [urllib.request.urlopen('http://127.0.0.1:%d/health' % p, timeout=2) for p in (4730, 4731)]" \
    >/dev/null 2>&1 && break
  sleep 0.5
done
timeout 1500 docker run --rm --name "$NAME-empty-browser-$$" --network "container:$EMPTY" -e NODE_PATH=/usr/src/app/node_modules \
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
                  ("pages have a button's words out of its middle", "askew"),
                  ("pages have boxes touching, words nearer than their padding, a gap off the scale or words on the "
                   "bare page", "spacing"), ("pages have a floating layer off the screen or under something",
                                             "layer_faults"),
                  ("pages have a form part out of its design (FORMS.md)", "form_faults"),
                  ("pages have their bar, the menu item showing or the side menu off the screen or under something "
                   "(at the top or halfway down), or the other site's frame", "frame_faults"),
                  ("pages break a number or a date over two lines, or part a figure from its unit or a time from its date",
                   "wrap_faults")):
    if s.get(key, 0) + e.get(key, 0):
        problems.append("%s: %d" % (what, s.get(key, 0) + e.get(key, 0)))
if empty_status:
    problems.append("the empty server's browser exited %d" % empty_status)
if s["dialog_faults"]:
    problems.append("%d questions misbehaved" % s["dialog_faults"])
if s["filters"] != rounds or s["filter_faults"]:
    problems.append("the songs filter: %d of %d runs misbehaved" % (s["filter_faults"], s["filters"]))
if s["messages"] != rounds or s["message_faults"]:
    problems.append("the message to send: %d of %d runs misbehaved" % (s["message_faults"], s["messages"]))
# The phone's MENU sheets pictured: the players' and the admin site's, at two phone widths in two languages.
if s.get("sheets", 0) != 8:
    problems.append("the MENU sheets pictured: %d, not 8" % s.get("sheets", 0))
# Copy over plain http on the LAN address: a token on the players' site and a message on the admin site, two languages.
if s.get("copies", 0) != 4 or s.get("copy_faults", 0):
    problems.append("Copy over plain http: %d of %d misbehaved" % (s.get("copy_faults", 0), s.get("copies", 0)))
# The DJ card's pickers opened by a tap, every round: the chosen picture whole in its box, each box a well.
if s.get("pickers", 0) != rounds or s.get("picker_faults", 0):
    problems.append("the DJ card's pickers: %d of %d runs misbehaved" % (s.get("picker_faults", 0), s.get("pickers", 0)))
if s["bars"] != rounds or s["bar_faults"]:
    problems.append("the toast (its place, and in one run its time) and the phone's menu sheet: %d of %d runs "
                    "misbehaved" % (s["bar_faults"], s["bars"]))
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
# The floating layers: the full server's pages have the charts and the DJ's weeks, so some were opened.
if not s["layers"]:
    problems.append("no floating layer was opened")
if status:
    problems.append("the browser exited %d" % status)
print("FAIL: " + "; ".join(problems) if problems else "PASS: %d pages and %d of an empty server, nothing sticks out, "
      "no words cut off, no cell without a label, the phone menu whole, every button's words in its middle, boxes "
      "apart and on the scale, every form in its design, every number and date whole and with its unit, each site's "
      "frame on screen, the MENU sheets pictured, Copy over plain http fine, the DJ card's pickers opened fine, "
      "%d floating layers "
      "whole and on top; the toast and the "
      "phone's menu sheet pressed; %d "
      "questions fine; %d upload fields fine; the songs filter, the message to send, the list to look at, the token "
      "shown once, both uploads and maintenance off and on fine in %d runs; the empty server's %d states hold" % (
          s["pages"], e["pages"], s["layers"], s["dialogs"], s["drops"], rounds, e["states"]))
sys.exit(1 if problems else 0)
PY
