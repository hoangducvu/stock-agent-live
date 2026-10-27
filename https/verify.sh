#!/usr/bin/env bash
# Check both the direct origin and public Cloudflare route, without orders.
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
  echo 'Run with sudo to read the protected login file.' >&2
  exit 1
fi
systemctl is-active --quiet nexlara-edge.service
python3 - <<'PY'
from pathlib import Path
import json, subprocess

values = dict(line.split(': ', 1) for line in Path('/etc/nexlara-edge/login.txt').read_text().splitlines())
username, password = values['Username'], values['Password']
assert username == 'nexlara'
assert password and all(c.isalnum() or c in '_-' for c in password), 'Unexpected password format'

def request(path, authenticated, direct):
    cmd = ['curl', '--silent', '--show-error', '--connect-timeout', '5',
           '--max-time', '20', '--write-out', '\n%{http_code}', '--config', '-']
    if direct:
        cmd += ['--resolve', 'nexlara.eu:443:127.0.0.1']
    cmd += ['https://nexlara.eu'+path]
    # Credentials go over stdin, never into process arguments or output.
    config = f'user = "{username}:{password}"\n' if authenticated else ''
    result = subprocess.run(cmd, input=config, text=True, capture_output=True)
    if result.returncode:
        raise SystemExit('HTTPS certificate/connection check failed. Review gateway logs '
                         f'and domain/ingress routing. curl exit: {result.returncode}')
    body, code = result.stdout.rsplit('\n', 1)
    return int(code), body

for direct, name in ((True, 'Direct origin'), (False, 'Public domain')):
    for path in ('/', '/api/health', '/api/bot/status', '/api/bot/test-order'):
        code, _ = request(path, False, direct)
        assert code == 401, f'{name}: unauthenticated {path} returned {code}, expected 401'
    code, html = request('/tradingbot/', True, direct)
    assert code == 200 and 'id="root"' in html, f'{name}: website check failed'
    code, body = request('/api/health', True, direct)
    assert code == 200, f'{name}: health returned {code}'
    health = json.loads(body)
    assert health.get('status') == 'ok' and health.get('bot_running') is False, f'{name}: unhealthy or trading active'
    print(f'{name}: trusted TLS, password protection, website and API passed; trading inactive.')

result = subprocess.run(['curl', '--silent', '--show-error', '--max-time', '10',
                         '--output', '/dev/null', '--write-out', '%{http_code} %{redirect_url}',
                         '--resolve', 'nexlara.eu:80:127.0.0.1', 'http://nexlara.eu/'],
                        capture_output=True, text=True, check=True)
code, location = result.stdout.split(' ', 1)
assert code in ('301', '302', '307', '308') and location.startswith('https://nexlara.eu/'), 'HTTP redirect check failed'
print('Origin HTTP redirects to HTTPS. No orders were submitted.')
PY
