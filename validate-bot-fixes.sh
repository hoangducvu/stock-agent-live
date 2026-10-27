#!/usr/bin/env bash
# Builds/tests a candidate image. Leaves running services and volumes unchanged.
set -euo pipefail
cd -- "$(dirname -- "$0")"
test "$(id -un)" = opc || { echo 'Run as opc, without sudo.' >&2; exit 1; }
bash validate-private.sh
podman build -t localhost/nexlara-api:reviewed -f Containerfile.api .
podman run --rm --network=none \
  -e NEXLARA_REQUIRE_TEST_DEPS=1 \
  -v "$PWD/tests:/tests:ro,Z" \
  localhost/nexlara-api:reviewed \
  python -B -m unittest discover -s /tests -v
podman run --rm --network=none localhost/nexlara-api:reviewed python -m pip check
echo 'Candidate image validation passed. No running service was replaced.'
echo 'Next: bash apply-bot-fixes.sh'
