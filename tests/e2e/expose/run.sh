#!/bin/bash
# ./dmt3 expose as an owner runs it, on a copy of this tree with ports of its own, under a Compose project of its own
# (odt3-srv-expose: its containers, network and volumes carry the name), so nothing of a server on this PC is touched:
#   1. Caddy's local authority (a closed network): ./dmt3 setup, expose NAME --local-ca, up; ./dmt3 check answers
#      through Caddy; the root saved with --root-cert verifies the site's certificate; plain HTTP is sent to HTTPS; an
#      admin signs in through the API over HTTPS; the site's own port is not published.
#   2. An ACME authority: Pebble (Let's Encrypt's test authority, every challenge taken as passed) on the project's
#      network, named with --ca and --ca-root; Caddy gets a certificate it signed.
#   3. expose --off: Caddy goes, the site is on its own port again.
# Each step says PASS or FAIL; the exit code is the number that failed. Everything made is removed at the end.
#
#   tests/e2e/expose/run.sh OUT_DIR [IMAGE]
#
# IMAGE is the server image to run (default: built from this tree as odt3-srv-expose:test). Ports (each checked free
# first): EXPOSE_PORTS="GAME SITE HTTP HTTPS", by default 14725 14730 14780 14743.
set -u
OUT=$(realpath -m "${1:?usage: tests/e2e/expose/run.sh OUT_DIR [IMAGE]}")
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
IMAGE=${2:-odt3-srv-expose:test}
read -r GAME SITE HTTP HTTPS <<< "${EXPOSE_PORTS:-14725 14730 14780 14743}"
export COMPOSE_PROJECT_NAME=odt3-srv-expose
PEBBLE=odt3-srv-pebble
NAME=dmt3.test
failed=0
step() { if [ "$2" = 0 ]; then echo "PASS $1"; else echo "FAIL $1"; failed=$((failed + 1)); fi; }
for port in $GAME $SITE $HTTP $HTTPS; do
  # A port another program listens on is never taken over.
  if ss -ltnH "sport = :$port" | grep -q .; then echo "port $port is in use: EXPOSE_PORTS names others"; exit 1; fi
done
rm -rf "$OUT" && mkdir -p "$OUT/tree"
# The tree as git has it (and new files not ignored), without the working folder; a tree that is no git checkout of its
# own (an export of a commit, perhaps inside another repository's folder) as it is, but its working folder.
if [ "$(git -C "$REPO" rev-parse --show-toplevel 2>/dev/null)" = "$REPO" ]; then
  (cd "$REPO" && git ls-files -z --cached --others --exclude-standard | tar --null -T - -cf -) | tar -xf - -C "$OUT/tree"
else
  (cd "$REPO" && tar --exclude=./_work -cf - .) | tar -xf - -C "$OUT/tree"
fi
cd "$OUT/tree"
# The copy's own ports, kept in its .env by its own ./dmt3 ports, as an owner whose 80 and 443 are taken does it.
./dmt3 ports --game "$GAME" --web "$SITE" --http "$HTTP" --https "$HTTPS" > "$OUT/ports.txt" 2>&1 \
  || { cat "$OUT/ports.txt"; exit 1; }
cleanup() {
  docker rm -f "$PEBBLE" >/dev/null 2>&1
  (cd "$OUT/tree" && docker compose -f compose.yaml -f packaging/docker/edge.yaml down -v --remove-orphans >/dev/null 2>&1)
}
trap cleanup EXIT
cleanup
if [ "$IMAGE" = odt3-srv-expose:test ]; then
  docker build -q -f "$REPO/packaging/docker/Dockerfile" -t "$IMAGE" "$REPO" >/dev/null || { echo "FAIL the image"; exit 1; }
fi
# The image the copy's ./dmt3 runs: given by name, as an owner's own build is (.env would keep it the same way).
export OPENDMT3_IMAGE=$IMAGE
# https://NAME/PATH on this PC's HTTPS port, the name sent in the handshake; extra curl options after the path.
https() { local path=$1; shift; curl -s --max-time 10 --resolve "$NAME:$HTTPS:127.0.0.1" "$@" "https://$NAME:$HTTPS$path"; }

# ---- 1. Caddy's local authority
./dmt3 setup --admin BOSS --password pass1234 --no-start > "$OUT/setup.txt" 2>&1
r=$?; step "./dmt3 setup (the image given, the first account)" $r
./dmt3 expose "$NAME" --local-ca > "$OUT/expose-local.txt" 2>&1 && grep -q "https://$NAME/" .env
r=$?; step "./dmt3 expose $NAME --local-ca keeps the name and the players' address" $r
./dmt3 up --no-build > "$OUT/up.txt" 2>&1
r=$?; step "./dmt3 up: the server with Caddy beside it" $r
for _ in $(seq 60); do ./dmt3 check > "$OUT/check-local.txt" 2>&1 && break; sleep 1; done
grep -q "through Caddy" "$OUT/check-local.txt"
r=$?; step "./dmt3 check: $(grep -m1 "Caddy" "$OUT/check-local.txt" | sed 's/^ *//')" $r
./dmt3 expose --root-cert "$OUT/local-root.crt" > /dev/null 2>&1
https /health --cacert "$OUT/local-root.crt" -o "$OUT/health-local.json" -w '%{http_code}' > "$OUT/code.txt"
grep -q 200 "$OUT/code.txt" && grep -q '"ok":true' "$OUT/health-local.json"
r=$?; step "the root saved with --root-cert verifies https://$NAME/ (curl --cacert)" $r
code=$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' --resolve "$NAME:$HTTP:127.0.0.1" "http://$NAME:$HTTP/health")
[[ "$code" == 30[178]" https://$NAME"* ]]
r=$?; step "plain HTTP is sent to HTTPS ($code)" $r
token=$(https /api/v1/session --cacert "$OUT/local-root.crt" -H 'Content-Type: application/json' \
  -d '{"login_id": "BOSS", "password": "pass1234"}' | python3 -c "import json, sys; print(json.load(sys.stdin)['token'])")
https /api/v1/server/invite --cacert "$OUT/local-root.crt" -H "Authorization: Bearer $token" > "$OUT/invite.json"
grep -q "\"address\":\"https://$NAME/\"" "$OUT/invite.json"
r=$?; step "an admin signs in over HTTPS, and the invite carries https://$NAME/" $r
! curl -s --max-time 3 "http://127.0.0.1:$SITE/health" > /dev/null
r=$?; step "the site's own port is not published while it is exposed" $r

# ---- 2. An ACME authority: Pebble on the project's network, every challenge taken as passed
docker run -d --name "$PEBBLE" --network "${COMPOSE_PROJECT_NAME}_default" --network-alias pebble \
  -e PEBBLE_VA_ALWAYS_VALID=1 -e PEBBLE_VA_NOSLEEP=1 ghcr.io/letsencrypt/pebble:2.8.0 > /dev/null
# Pebble's own HTTPS (its directory) is signed by the test root it brings.
docker cp "$PEBBLE:/test/certs/pebble.minica.pem" "$OUT/pebble-root.pem" 2>/dev/null \
  || docker exec "$PEBBLE" cat /test/certs/pebble.minica.pem > "$OUT/pebble-root.pem"
./dmt3 expose "$NAME" --ca https://pebble:14000/dir --ca-root "$OUT/pebble-root.pem" --email owner@example.org \
  > "$OUT/expose-acme.txt" 2>&1
r=$?; step "./dmt3 expose $NAME --ca (Pebble) --ca-root: Caddy started again with it" $r
issuer=
for _ in $(seq 60); do
  issuer=$(echo | openssl s_client -connect "127.0.0.1:$HTTPS" -servername "$NAME" 2>/dev/null \
    | openssl x509 -noout -issuer 2>/dev/null)
  [[ "$issuer" == *Pebble* ]] && break
  sleep 2
done
[[ "$issuer" == *Pebble* ]] && ./dmt3 check > "$OUT/check-acme.txt" 2>&1
r=$?; step "Caddy got a certificate from the ACME authority ($issuer)" $r

# ---- 3. Back to the site on its own port
./dmt3 expose --off > "$OUT/off.txt" 2>&1
for _ in $(seq 30); do curl -sf "http://127.0.0.1:$SITE/health" > /dev/null && break; sleep 1; done
curl -sf "http://127.0.0.1:$SITE/health" > /dev/null && ! grep -q EDGE_NAME .env \
  && [ -z "$(docker ps -aq --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" \
            --filter label=com.docker.compose.service=edge)" ]
r=$?; step "./dmt3 expose --off: Caddy gone, the site on its own port again" $r
# The ports ./dmt3 ports moved, honoured everywhere: the site tells launchers the game's port they reach, the game's
# port takes a connection there, and the banner in the server's log says both.
curl -s "http://127.0.0.1:$SITE/api/v1/status" > "$OUT/status.json"
grep -q "\"game_port\":$GAME" "$OUT/status.json" && python3 -c "import socket; socket.create_connection(('127.0.0.1', $GAME), 5)"
r=$?; step "the site tells launchers the moved game port ($GAME), which takes a connection" $r
docker compose logs --no-color > "$OUT/compose.log" 2>&1
grep -q "| Game      TCP $GAME" "$OUT/compose.log" && grep -q "This PC   http://127.0.0.1:$SITE/" "$OUT/compose.log"
r=$?; step "the server's log starts with its banner, the ports in its box" $r
echo "failed: $failed"
exit $failed
