#!/usr/bin/env bash
set -euo pipefail
curl --fail --silent --show-error --retry 20 --retry-delay 2 --retry-connrefused --max-time 10 http://127.0.0.1:8080/api/health
echo
podman exec nexlara-api python -c 'import json, urllib.request; h=json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/health")); assert h["status"]=="ok" and h["bot_running"] is False, h; s=json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/strategies")); assert len(s)==4, s; print("API healthy; four strategies; no trading bot running")'
curl --fail --silent --show-error http://127.0.0.1:8080/tradingbot/ | grep -q 'id="root"'
echo 'Frontend HTML and API proxy responded successfully.'
echo 'App is available only through SSH forwarding; no public HTTP ports were opened.'
