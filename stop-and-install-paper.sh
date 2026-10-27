#!/usr/bin/env bash
# User-authorized paper migration; preserve connection before stopping the engine.
set -euo pipefail
cd -- "$(dirname -- "$0")"
test "$(id -un)" = opc || { echo 'Run as opc, without sudo.' >&2; exit 1; }
# The user already validated this image with all 54 tests. No new source is
# executed by it except the explicit connection-import helper mounted below.
transfer_image=localhost/nexlara-api:paper-20261025T152334Z
podman image exists "$transfer_image"
health=$(curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8080/api/health)
printf '%s' "$health" | python3 -c 'import json,sys; h=json.load(sys.stdin); assert h.get("status")=="ok" and h.get("bot_running") is True, "Expected healthy running engine. For an already-stopped engine use deploy-paper-workspace.sh instead."'
snapshot="$PWD/deployment-review/backups/pre-paper-transfer-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -m 700 "$snapshot"
mountpoint=$(podman volume inspect nexlara-data --format '{{.Mountpoint}}')
podman unshare tar -C "$mountpoint" -czf "$snapshot/nexlara-data.tar.gz" .
# Keep broker secrets entirely in a pipe; never in shell variables, arguments,
# terminal output, or plaintext files. Read-only broker account verification.
podman exec -i nexlara-api python - < migration/export_running_paper.py |
  podman run --rm -i --network=none --security-opt label=disable \
    -v nexlara-data:/app/data \
    -v "$PWD/migration:/migration:ro" \
    "$transfer_image" python /migration/import_paper.py
# Only stop once encrypted connection transfer has succeeded.
# Stop is not retried: it can submit liquidation orders.
curl --fail --silent --show-error --connect-timeout 5 --max-time 90 \
  -X POST http://127.0.0.1:8080/api/bot/stop
echo
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8080/api/health |
  python3 -c 'import json,sys; h=json.load(sys.stdin); assert h.get("bot_running") is False, "Engine still running; installation aborted."'
bash deploy-paper-workspace.sh
echo 'Open https://nexlara.eu/ and run Readiness. Connection and larger paper position settings are saved.'
echo 'Shutdown attempted to close existing paper positions. During a closed session they may remain open or have pending exits; inspect Alpaca and Readiness before starting.'
