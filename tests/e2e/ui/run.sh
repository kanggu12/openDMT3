#!/bin/bash
# Screenshots and layout measurements of the launcher, in a container with a virtual screen and no network.
# Nothing opens on the developer's screen. Usage: tests/e2e/ui/run.sh OUT_DIR [lang ...] (default: en ko)
# Window sizes: the default 1180x760, the smallest allowed 960x640, and a large 1600x1000. At the first of them every
# page is also drawn at every window width from the narrowest to 1900 (shots.py --resize): a width at which the window
# never finishes drawing fails the run.
set -u
OUT=$(realpath -m "${1:?usage: run.sh OUT_DIR [lang ...]}")
shift
LANGS=${*:-en ko}
# OPENDMT3_REPO points the run at another copy (the layout checker is tested on a copy with a planted fault).
REPO=${OPENDMT3_REPO:-$(cd "$(dirname "$0")/../../.." && pwd)}
mkdir -p "$OUT"
# The image is small and built once (tests/e2e/ui/Dockerfile), and again whenever its recipe changes: the image carries
# the recipe's hash as a label, so one made from an older recipe (without 7-Zip, say) is never used for this tree.
RECIPE=$(sha256sum "$REPO/tests/e2e/ui/Dockerfile" | cut -c1-16)
if [ "$(docker image inspect -f '{{index .Config.Labels "opendmt3.recipe"}}' opendmt3-ui:local 2>/dev/null)" != "$RECIPE" ]; then
  docker build -q --label "opendmt3.recipe=$RECIPE" -t opendmt3-ui:local "$REPO/tests/e2e/ui" >/dev/null || exit 1
fi
# A name of its own (odt3-ui-*, or the one OPENDMT3_E2E_NAME gives, with this run's process number), so this run's
# container is told from any other and is gone when the run ends.
docker run --rm --name "${OPENDMT3_E2E_NAME:-odt3-ui}-$$" --network none -e PYTHONDONTWRITEBYTECODE=1 \
  -e OPENDMT3_SHOTS_ONLY -v "$REPO:/src:ro" -v "$OUT:/out" -w /src \
  opendmt3-ui:local bash -c "
    Xvfb :99 -screen 0 1920x1200x24 -nolisten tcp >/dev/null 2>&1 &
    sleep 1
    # The bundled fonts, known to fontconfig the way Windows loads them privately.
    mkdir -p /usr/local/share/fonts/opendmt3 && cp opendmt3/client/assets/fonts/*.ttf /usr/local/share/fonts/opendmt3/ && fc-cache -f >/dev/null
    status=0
    for lang in $LANGS; do
      for size in 1180x760 960x640 1600x1000; do
        # Every page at every window width too (shots.py's resize check), once a language: the widths are the same
        # at any height.
        resize=
        [ \$size = 1180x760 ] && resize=--resize
        # A screen that waits for an answer no step gives would hold the run for good: each size has 15 minutes.
        timeout 900 python tests/e2e/ui/shots.py --out /out --lang \$lang --size \$size \$resize || status=1
      done
    done
    exit \$status"
