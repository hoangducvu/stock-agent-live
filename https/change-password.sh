#!/usr/bin/env bash
# Rotate the dashboard password; read the new value securely from the terminal.
set -euo pipefail
umask 077
if [ "$(id -u)" -ne 0 ]; then
  echo 'Run with sudo from the normal VM terminal.' >&2
  exit 1
fi
python3 - <<'PY'
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

root = Path('/etc/nexlara-edge')
config = root / 'Caddyfile'
login = root / 'login.txt'
image = (root / 'image.txt').read_text().strip()
subprocess.run(['systemctl', 'is-active', '--quiet', 'nexlara-edge.service'], check=True)
original = config.read_text()
pattern = r'(?m)^(\s*nexlara[ \t]+)\$2[aby]\$[^\s]+([ \t]*)$'
if len(re.findall(pattern, original)) != 1:
    raise SystemExit('Expected exactly one Nexlara login; configuration needs review.')
import getpass
password = getpass.getpass('New dashboard password: ')
if not password or not all(c.isalnum() or c in '_-' for c in password):
    raise SystemExit('Use a nonempty password containing letters, digits, underscores or hyphens.')
result = subprocess.run(
    ['podman', 'run', '--rm', '-i', '--network=none', image, 'caddy', 'hash-password'],
    input=password+'\n', capture_output=True, text=True, check=True,
)
hashed = result.stdout.strip()
if not re.fullmatch(r'\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}', hashed):
    raise SystemExit('Password hashing failed; nothing changed.')
updated = re.sub(pattern, lambda m: m[1]+hashed+m[2], original)
with tempfile.TemporaryDirectory(prefix='password-', dir=root) as temporary:
    stage = Path(temporary)
    candidate = stage / 'Caddyfile'
    candidate.write_text(updated)
    candidate.chmod(0o600)
    subprocess.run([
        'podman', 'run', '--rm', '--network=none',
        '-v', f'{candidate}:/etc/caddy/Caddyfile:ro,Z', image,
        'caddy', 'validate', '--config', '/etc/caddy/Caddyfile', '--adapter', 'caddyfile',
    ], check=True)
    shutil.copy2(config, stage / 'old-config')
    shutil.copy2(login, stage / 'old-login')
    try:
        # Keep the mounted file inode and its existing SELinux label.
        config.write_text(updated)
        login.write_text('Username: nexlara\nPassword: '+password+'\n')
        config.chmod(0o600)
        login.chmod(0o600)
        subprocess.run(['systemctl', 'restart', 'nexlara-edge.service'], check=True)
        for authenticated, expected in ((False, '401'), (True, '200')):
            result = subprocess.run([
                'curl', '--silent', '--show-error', '--fail-with-body',
                '--connect-timeout', '5', '--max-time', '20', '--retry', '3',
                '--retry-connrefused', '--output', '/dev/null', '--write-out', '%{http_code}',
                '--resolve', 'nexlara.eu:443:127.0.0.1', '--config', '-',
                'https://nexlara.eu/',
            ], input=f'user = "nexlara:{password}"\n' if authenticated else '',
               capture_output=True, text=True)
            if result.stdout != expected or result.returncode != (0 if authenticated else 22):
                raise RuntimeError('HTTPS login verification failed.')
    except BaseException:
        shutil.copyfile(stage / 'old-config', config)
        shutil.copyfile(stage / 'old-login', login)
        subprocess.run(['systemctl', 'restart', 'nexlara-edge.service'], check=True)
        raise
print('Password changed. HTTPS accepts the new login and blocks unauthenticated access.')
print('Website: https://nexlara.eu/  Username: nexlara')
PY
