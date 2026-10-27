#!/usr/bin/env bash
# Read-only checks. Does not start, stop, or restart services or trading bots.
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [ "$(id -un)" != opc ]; then
  echo 'Run as opc in a normal VM shell, without sudo.' >&2
  exit 1
fi
systemctl --user is-active --quiet nexlara-api.service nexlara-web.service
test -f /var/lib/systemd/linger/opc
for service in nexlara-api nexlara-web; do
  test -L "/run/user/$(id -u)/systemd/generator/default.target.wants/${service}.service"
  test "$(systemctl --user show "${service}.service" -p Restart --value)" = on-failure
done
test "$(podman port nexlara-web 80/tcp)" = '127.0.0.1:8080'
podman volume exists nexlara-data
podman volume exists nexlara-logs
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8080/api/health |
  python3 -c '
import json,sys
h=json.load(sys.stdin)
if h.get("status") != "ok":
    sys.exit("Deployment blocked: API health is not OK. Inspect the API service logs.")
if h.get("bot_running") is True:
    sys.exit("Deployment blocked: the trading engine is running. No changes were made. Inspect bot status and broker positions/orders before stopping it; stopping may close positions.")
if h.get("bot_running") is not False:
    sys.exit("Deployment blocked: API did not report a valid bot_running flag.")
print("API health OK; trading engine inactive.")
' 
podman exec -i nexlara-api python - <<'PY'
import json, urllib.request
def get(path):
    with urllib.request.urlopen('http://127.0.0.1:8000'+path, timeout=10) as response:
        return json.load(response)
assert len(get('/api/strategies')) == 4
assert get('/api/bot/status')['running'] is False, 'Trading is already active'
print('API responds; trading is inactive.')
PY
python3 - <<'PY'
from html.parser import HTMLParser
from urllib.request import urlopen
from urllib.parse import urljoin, urlsplit
base = 'http://127.0.0.1:8080'
class Assets(HTMLParser):
    def __init__(self):
        super().__init__(); self.urls = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        value = attrs.get('src') if tag == 'script' else attrs.get('href') if tag == 'link' else None
        if value: self.urls.append(value)
for route in ('/', '/tradingbot/', '/tradingbot/dashboard'):
    with urlopen(base+route, timeout=10) as response:
        html = response.read().decode()
    assert 'id="root"' in html, route
    parser = Assets(); parser.feed(html)
    for asset in parser.urls:
        url = urljoin(base+route, asset)
        if urlsplit(url).netloc != urlsplit(base).netloc: continue
        with urlopen(url, timeout=10) as response:
            content_type = response.headers.get('Content-Type', '')
            assert response.status == 200, url
            if urlsplit(url).path.endswith(('.js', '.css')):
                assert 'text/html' not in content_type, f'Asset returned HTML: {url}'
print('Website, client routes, scripts, and styles respond.')
PY
echo 'Private validation passed. Loopback binding and startup configuration checked.'
echo 'Reboot recovery, HTTPS, and trading recovery have NOT been tested.'
