#!/usr/bin/env bash
# Run in a normal opc server shell. Builds/tests first; never starts trading.
set -euo pipefail
cd -- "$(dirname -- "$0")"
test "$(id -un)" = opc || { echo 'Run as opc, without sudo.' >&2; exit 1; }
case "${1:-}" in
  --stage-only) stage_only=true ;;
  '') stage_only=false ;;
  *) echo 'Usage: bash deploy-paper-workspace.sh [--stage-only]' >&2; exit 2 ;;
esac
if [ "$stage_only" = false ]; then
  bash validate-private.sh
else
  echo 'Staging candidate images only. Running services, trading and production volumes will remain unchanged.'
fi
node --check dist/workspace.js
node tests/test_workspace_form.mjs
node tests/test_ai_settings_form.mjs
node tests/test_research_diagnostics_ui.mjs
node --check dist/equity-chart.js
node tests/test_account_dashboard_ui.mjs
stamp=$(date -u +%Y%m%dT%H%M%SZ)
api_image="localhost/nexlara-api:paper-$stamp"
web_image="localhost/nexlara-web:paper-$stamp"
podman build -t "$api_image" -f Containerfile.api .
podman run --rm --network=none -e NEXLARA_REQUIRE_TEST_DEPS=1 \
  -v "$PWD/tests:/tests:ro,Z" "$api_image" python -B -m unittest discover -s /tests -v
podman run --rm --network=none "$api_image" python -m pip check
podman build -t "$web_image" -f Containerfile.web .
podman run --rm --network=none --add-host=nexlara-api:127.0.0.1 "$web_image" nginx -t
if [ "$stage_only" = true ]; then
  echo "Candidate API validated: $api_image"
  echo "Candidate web validated: $web_image"
  echo 'Staging complete. No running services, production volumes, orders, or trading settings were changed.'
  exit 0
fi
# Check again immediately before update: do not interrupt an active engine.
bash validate-private.sh
snapshot="$PWD/deployment-review/backups/paper-$stamp"
mkdir -m 700 "$snapshot"
unit_dir="$HOME/.config/containers/systemd"
for service in nexlara-api nexlara-web; do
  cp -a "$unit_dir/$service.container" "$snapshot/$service.container"
  prior_image=$(podman inspect "$service" --format '{{.Image}}')
  podman tag "$prior_image" "localhost/$service:backup-$stamp"
done
for volume in nexlara-data nexlara-logs; do
  mountpoint=$(podman volume inspect "$volume" --format '{{.Mountpoint}}')
  podman unshare tar -C "$mountpoint" -czf "$snapshot/$volume.tar.gz" .
done
rollback() {
  trap - ERR
  cp -a "$snapshot/nexlara-api.container" "$unit_dir/nexlara-api.container"
  cp -a "$snapshot/nexlara-web.container" "$unit_dir/nexlara-web.container"
  systemctl --user daemon-reload
  systemctl --user restart nexlara-api.service || true
  systemctl --user restart nexlara-web.service || true
  echo "Update failed. Previous service configuration restored. Backups: $snapshot" >&2
}
trap rollback ERR
python3 - "$unit_dir" "$api_image" "$web_image" <<'PY'
from pathlib import Path
import re,sys
for service,image in zip(('nexlara-api','nexlara-web'),sys.argv[2:]):
    path=Path(sys.argv[1],service+'.container')
    text=path.read_text()
    assert len(re.findall(r'^Image=.*$',text,re.M)) == 1
    text=re.sub(r'^Image=.*$','Image='+image,text,flags=re.M)
    if service=='nexlara-api':
        env_file=Path.home()/'.config/nexlara/research.env'
        if env_file.is_file():
            option='EnvironmentFile='+str(env_file)
            text=re.sub(r'^EnvironmentFile=.*research\.env.*\n','',text,flags=re.M)
            text=text.replace('[Container]','[Container]\n'+option,1)
    path.write_text(text)
PY
systemctl --user daemon-reload
systemctl --user restart nexlara-api.service
systemctl --user restart nexlara-web.service
curl --fail --silent --show-error --retry 15 --retry-delay 2 \
  --retry-connrefused --retry-all-errors --max-time 5 \
  http://127.0.0.1:8080/api/health
echo
bash validate-private.sh
python3 - <<'PY'
import json
from urllib.request import urlopen, Request
base='http://127.0.0.1:8080'
def get(path):
    with urlopen(base+path,timeout=10) as response:
        return response.read().decode()
settings=json.loads(get('/api/workspace/settings'))
assert settings['paper'] is True
assert 'api_key' not in settings and 'secret_key' not in settings
assert json.loads(get('/api/workspace/status'))['running'] is False
assert 'Your account. Your guardrails.' in get('/')
assert 'landing-archive.js' in get('/tradingbot/archive/first-landing/')
print('Paper dashboard, archived landing page, secret redaction and inactive engine verified.')
PY
trap - ERR
echo "Paper workspace installed. Backups: $snapshot"
echo 'Run: sudo bash https/verify.sh'
echo 'Open https://nexlara.eu/ → Settings; review your saved PAPER connection, run Readiness, then Start.'
echo 'Trading remains stopped. Configure optional Slack and AI in Settings; email/Google registration remains deferred.'
