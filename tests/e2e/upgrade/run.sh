#!/bin/bash
# A database an earlier release's server made, opened by the server under test: it must be upgraded with a copy
# kept first (readable by its owner only), keep every account and play, and let the same players sign in with the
# same passwords. The earlier server comes from its release tag, the one under test from this tree (or a commit),
# both as Docker images built from packaging/docker/Dockerfile. The earlier server runs with no network; the one
# under test listens on 127.0.0.1 only. No game files are needed: the plays are written through the earlier
# release's own records service, as its game server stores them.
#
#   tests/e2e/upgrade/run.sh OLD_TAG OUT_DIR [NEW_COMMIT]
#
# OLD_TAG is a release tag (v0.1.0, the release before the one being made). NEW_COMMIT is a commit to build the
# server under test from; without it, this tree as it is. OUT_DIR must be new or empty.
set -u
OLD=${1:?usage: tests/e2e/upgrade/run.sh OLD_TAG OUT_DIR [NEW_COMMIT]}
OUT=$(realpath -m "${2:?usage: tests/e2e/upgrade/run.sh OLD_TAG OUT_DIR [NEW_COMMIT]}")
NEW=${3:-}
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
C=opendmt3-upgrade-test
[ -z "$(ls -A "$OUT" 2>/dev/null)" ] || { echo "$OUT is not empty"; exit 2; }
mkdir -p "$OUT/old-src" "$OUT/data"
# The servers' own user writes the database here.
chmod 777 "$OUT/data"
fail() { echo "FAIL: $*"; docker logs "$C" > "$OUT/server.log" 2>&1; docker rm -f "$C" >/dev/null 2>&1; exit 1; }

# ---- the two servers, each from its own source: the tag as it was released, and the tree (or commit) under test
git -C "$REPO" archive "$OLD" | tar -x -C "$OUT/old-src" || { echo "FAIL: no tag $OLD"; exit 1; }
docker build -q -f "$OUT/old-src/packaging/docker/Dockerfile" -t opendmt3-server:upgrade-old "$OUT/old-src" >/dev/null \
  || { echo "FAIL: the $OLD server image did not build"; exit 1; }
NEW_SRC=$REPO
if [ -n "$NEW" ]; then
  # A commit: its own clean tree, so files being edited meanwhile never reach the image.
  NEW_SRC=$OUT/new-src
  mkdir -p "$NEW_SRC"
  git -C "$REPO" archive "$NEW" | tar -x -C "$NEW_SRC" || { echo "FAIL: no commit $NEW"; exit 1; }
fi
docker build -q -f "$NEW_SRC/packaging/docker/Dockerfile" -t opendmt3-server:upgrade-new "$NEW_SRC" >/dev/null \
  || { echo "FAIL: the server image under test did not build"; exit 1; }
WANT=$(docker run --rm --network none --entrypoint python opendmt3-server:upgrade-new -c "from opendmt3.server import db; print(db.VERSION)")

# ---- the earlier release makes the data: an admin, a player and twelve plays
old() { docker run --rm --network none -v "$OUT/data:/data" "$@"; }
old opendmt3-server:upgrade-old --add-player BOSS --password pass1234 --dj BOSS --admin >/dev/null || fail "$OLD could not make BOSS"
old opendmt3-server:upgrade-old --add-player NOVA --password pass1234 --dj "DJ NOVA" >/dev/null || fail "$OLD could not make NOVA"
MADE=$(old --entrypoint python opendmt3-server:upgrade-old -c '
import time
try:
    from opendmt3.server import db
    from opendmt3.server.services import records
except ImportError:
    # A tree with the older layout keeps both at the package's top.
    from opendmt3 import db
    from opendmt3.services import records
c = db.connect("/data/openDMT3.sqlite")
plays = records.Records(c)
for i, who in enumerate(("BOSS", "NOVA") * 6):
    row = c.execute("SELECT id FROM accounts WHERE login_id = ?", (who,)).fetchone()
    plays.add(row["id"], "10.0.0.5:1", 0, {"song": 1 + i % 3, "pattern": 1 + i % 2, "score": 500000 + i * 1000,
              "counts": [0] * 7, "raw": bytes(47)}, at=time.time() - 3600 + i)
print(c.execute("PRAGMA user_version").fetchone()[0], c.execute("SELECT COUNT(*) FROM plays").fetchone()[0])
') || fail "$OLD could not store the plays"
read -r WAS PLAYS <<<"$MADE"
echo "  $OLD made database version $WAS with 2 accounts and $PLAYS plays"

# ---- the server under test opens it
PORT=$(python3 -c "import socket; s = socket.socket(); s.bind(('127.0.0.1', 0)); print(s.getsockname()[1])")
docker rm -f "$C" >/dev/null 2>&1
docker run -d --name "$C" -p "127.0.0.1:$PORT:4730" -v "$OUT/data:/data" opendmt3-server:upgrade-new >/dev/null \
  || fail "the server under test did not start"
for _ in $(seq 1 60); do curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && break; python3 -c "import time; time.sleep(0.5)"; done
curl -sf "http://127.0.0.1:$PORT/health" >/dev/null || fail "the server under test does not answer"
# The copy kept before the upgrade: there, and its owner's only (it holds card numbers and password hashes).
COPY=$(cd "$OUT/data" && ls openDMT3.sqlite.v"$WAS"-*.bak 2>/dev/null | head -1)
if [ "$WAS" = "$WANT" ]; then
  # A release that kept the database as it was: opened as it is, with no upgrade and so no copy.
  [ -z "$COPY" ] || fail "a version $WAS database was copied as if upgraded, though the server under test is version $WANT too"
  KEPT_FIRST="no upgrade needed"
else
  [ -n "$COPY" ] || fail "no copy of the version $WAS database was kept before the upgrade"
  [ "$(stat -c %a "$OUT/data/$COPY")" = "600" ] || fail "the copy $COPY is not its owner's only ($(stat -c %a "$OUT/data/$COPY"))"
  KEPT_FIRST="a 0600 copy kept first"
fi
NOW=$(docker exec "$C" python -c "
from opendmt3.server import db
c = db.connect('/data/openDMT3.sqlite')
print(c.execute('PRAGMA user_version').fetchone()[0], c.execute('SELECT COUNT(*) FROM plays').fetchone()[0])")
read -r IS KEPT <<<"$NOW"
[ "$IS" = "$WANT" ] || fail "the database is version $IS, not $WANT"
[ "$KEPT" = "$PLAYS" ] || fail "$KEPT plays after the upgrade, $PLAYS before"
# The same players sign in with the same passwords, and see what was there.
TOKEN=$(curl -s -X POST -H "Content-Type: application/json" -d '{"login_id":"BOSS","password":"pass1234"}' \
  "http://127.0.0.1:$PORT/api/v1/session" | python3 -c "import json, sys; print(json.load(sys.stdin).get('token', ''))")
[ -n "$TOKEN" ] || fail "BOSS cannot sign in after the upgrade"
WHO=$(curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:$PORT/api/v1/players" \
  | python3 -c "import json, sys; print(' '.join(sorted(p['login_id'] for p in json.load(sys.stdin)['players'])))")
[ "$WHO" = "BOSS NOVA" ] || fail "the players after the upgrade are: $WHO"
SEEN=$(curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:$PORT/api/v1/plays?everyone=1" \
  | python3 -c "import json, sys; print(len(json.load(sys.stdin)['plays']))")
[ "$SEEN" = "$PLAYS" ] || fail "the site shows $SEEN plays, the database had $PLAYS"
docker logs "$C" > "$OUT/server.log" 2>&1
docker rm -f "$C" >/dev/null
echo "PASS: a version $WAS database made by $OLD came up as version $IS ($KEPT_FIRST), with both accounts and all $PLAYS plays, and BOSS signs in with the same password"
