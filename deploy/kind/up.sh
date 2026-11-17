#!/usr/bin/env bash
# The Helm chart on a local kind cluster, checked from this PC: the image built from this tree, the cluster
# (odt3-srv-kind, or OPENDMT3_E2E_NAME's -kind; cluster.yaml), the chart installed with the test's values, then
# /health and the site over the mapped port, the game's port taking a TCP connection, the first account from the
# chart's Secret signing in through the API, the Server tab's runner (the cluster's commands), and helm test. Each check prints PASS or FAIL; the exit code is the number that failed.
#
#   deploy/kind/up.sh          the cluster stays up afterwards (kubectl --context kind-odt3-srv-kind ...)
#   deploy/kind/up.sh --down   the cluster is deleted at the end, passed or not
#
# Ports 14725 and 14730 on 127.0.0.1 must be free (cluster.yaml maps them).
set -uo pipefail
cd "$(dirname "$0")/../.."
# The cluster's name (its node's container carries it): OPENDMT3_E2E_NAME's -kind, so two runs at once name their own.
CLUSTER=${OPENDMT3_E2E_NAME:-odt3-srv}-kind
CTX=kind-$CLUSTER
NS=opendmt3
IMAGE=opendmt3-server:kind
DOWN=no
[ "${1:-}" = "--down" ] && DOWN=yes
failed=0
# helm's own output, shown when it fails.
LOG=$(mktemp)
check() {
  # A check's line: its name, then whether the command after it held.
  local name=$1; shift
  if "$@"; then echo "PASS $name"; else echo "FAIL $name"; failed=$((failed + 1)); fi
}
finish() {
  # Deleted only when asked: a cluster kept up lets the owner look around in it.
  rm -f "$LOG"
  [ "$DOWN" = yes ] && kind delete cluster --name "$CLUSTER" >/dev/null 2>&1
  exit "$failed"
}
trap finish EXIT

# The ports first: a cluster cannot start onto a port another program holds, and nothing else is ever stopped for it.
for port in 14725 14730; do
  if ss -ltnH "sport = :$port" | grep -q .; then
    if ! kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
      echo "FAIL port $port on this PC is in use"; failed=1; exit
    fi
  fi
done

echo "== the image from this tree"
docker build -q -f packaging/docker/Dockerfile -t "$IMAGE" . >/dev/null || { echo "FAIL the image did not build"; failed=1; exit; }

echo "== the cluster"
kind get clusters 2>/dev/null | grep -qx "$CLUSTER" \
  || kind create cluster --config deploy/kind/cluster.yaml --name "$CLUSTER" --image kindest/node:v1.33.1 >/dev/null 2>&1 \
  || { echo "FAIL the cluster did not start"; failed=1; exit; }
# There is no registry: the image is copied onto the node.
kind load docker-image --name "$CLUSTER" "$IMAGE" >/dev/null || { echo "FAIL the image did not load"; failed=1; exit; }

echo "== the chart"
# helm's own lines only when it fails: the PASS and FAIL lines stay readable.
# --wait: until the pod is ready, its first account made before it (the init container).
quiet() { "$@" > "$LOG" 2>&1 || { cat "$LOG"; return 1; }; }
check "the chart installs and the server becomes ready" \
  quiet helm --kube-context "$CTX" upgrade --install dmt3 deploy/helm/opendmt3 -n "$NS" --create-namespace \
    -f deploy/kind/values.yaml --wait --timeout 5m

echo "== from this PC"
site=http://127.0.0.1:14730
# A NodePort answers a moment after the pod is ready (kube-proxy's rules): a few tries.
health() { for _ in $(seq 30); do curl -fsS -m 5 "$site/health" 2>/dev/null | grep -q '"ok": *true' && return 0; sleep 1; done; return 1; }
check "/health answers ok on the mapped port" health
check "the site's sign-in page answers" sh -c "curl -fsSL -m 10 '$site/' | grep -qi '<form'"
check "the game's port takes a TCP connection" python3 -c "import socket; socket.create_connection(('127.0.0.1', 14725), 5).close()"
# The account the chart's Secret made signs in through the API, and has the admin pages.
signin() {
  curl -fsS -m 10 -H 'Content-Type: application/json' -d '{"login_id": "BOSS", "password": "kindtest1"}' \
    "$site/api/v1/session" | python3 -c 'import json, sys; a = json.load(sys.stdin); sys.exit(0 if a["is_admin"] and a["token"] else 1)'
}
check "the first account from the Secret signs in, with the admin pages" signin
# The admin's Server tab knows the cluster runs the server: the cluster's commands with this release's names, and no
# button (GET /api/v1/server's runner, as the tab shows it).
runner() {
  token=$(curl -fsS -m 10 -H 'Content-Type: application/json' -d '{"login_id": "BOSS", "password": "kindtest1"}' \
    "$site/api/v1/session" | python3 -c 'import json, sys; print(json.load(sys.stdin)["token"])') \
    && curl -fsS -m 10 -H "Authorization: Bearer $token" "$site/api/v1/server" | python3 -c '
import json, sys
r = json.load(sys.stdin)["runner"]
print(r["kind"], r["can"], r["commands"]["restart"])
sys.exit(0 if r["kind"] == "kubernetes" and r["can"] == []
         and r["commands"]["restart"] == "kubectl -n opendmt3 rollout restart deployment/dmt3-opendmt3"
         and r["commands"]["remove_data"].endswith("delete pvc dmt3-opendmt3-data") else 1)'
}
check "the Server tab names the cluster's commands with this release's names, and no button" runner
# A new pod (an update) finds the account kept on the volume and makes none again.
again() {
  kubectl --context "$CTX" -n "$NS" rollout restart deploy/dmt3-opendmt3 >/dev/null \
    && kubectl --context "$CTX" -n "$NS" rollout status deploy/dmt3-opendmt3 --timeout 3m >/dev/null \
    && kubectl --context "$CTX" -n "$NS" logs deploy/dmt3-opendmt3 -c first-account | grep -q "accounts already" \
    && health && signin
}
check "after a restart the account is kept and none is made again" again

echo "== helm test"
check "helm test" quiet helm --kube-context "$CTX" test dmt3 -n "$NS" --timeout 2m
