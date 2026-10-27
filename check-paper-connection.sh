#!/usr/bin/env bash
# Read-only status and broker readiness. Never prints API keys or order payloads.
set -euo pipefail
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8080/api/health
echo
curl --fail --silent --show-error --max-time 120 http://127.0.0.1:8080/api/workspace/readiness |
  python3 -c 'import json,sys; result=json.load(sys.stdin); print("Ready:", result.get("ready")); print("Account:", json.dumps(result.get("account", {}))); [print(("PASS" if c["ok"] else "FAIL")+" — "+c["label"]+": "+c["detail"]) for c in result.get("checks", [])]'
