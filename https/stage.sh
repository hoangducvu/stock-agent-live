#!/usr/bin/env bash
# Stage and syntax-validate HTTPS only. Does not install/start a service,
# bind public ports, change firewall/DNS, or start trading.
set -euo pipefail
umask 077
cd -- "$(dirname -- "$0")"
if [ "$(id -u)" -ne 0 ]; then
  echo 'Run with sudo from the normal VM shell.' >&2
  exit 1
fi
test ! -e /etc/nexlara-edge || {
  echo '/etc/nexlara-edge already exists; refusing to overwrite it.' >&2
  exit 1
}
test ! -e /etc/containers/systemd/nexlara-edge.container || {
  echo 'An HTTPS Quadlet already exists; refusing to overwrite it.' >&2
  exit 1
}
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8080/api/health |
  python3 -c 'import json,sys; h=json.load(sys.stdin); assert h.get("status")=="ok" and h.get("bot_running") is False, "Private API unhealthy or trading active"'
podman pull docker.io/library/caddy:2-alpine
edge_image=$(podman image inspect docker.io/library/caddy:2-alpine --format '{{index .RepoDigests 0}}')
case "$edge_image" in
  *@sha256:*) ;;
  *) echo 'Failed to resolve immutable image digest.' >&2; exit 1 ;;
esac
stage_dir=$(mktemp -d /var/tmp/nexlara-edge.XXXXXXXX)
trap 'rm -rf -- "$stage_dir"' EXIT
python3 - "$edge_image" "$stage_dir" <<'PY'
from pathlib import Path
import secrets, subprocess, sys
image, stage = sys.argv[1], Path(sys.argv[2])
password = secrets.token_urlsafe(32)
result = subprocess.run(
    ['podman', 'run', '--rm', '-i', '--network=none', image,
     'caddy', 'hash-password'],
    input=password+'\n', capture_output=True, text=True, check=True,
)
hashed = result.stdout.strip()
assert hashed.startswith('$2') and len(hashed) == 60, 'Unexpected password hash'
config = Path('Caddyfile.template').read_text().replace('PASSWORD_HASH', hashed)
(stage/'Caddyfile').write_text(config)
(stage/'login.txt').write_text('Username: nexlara\nPassword: '+password+'\n')
unit = Path('nexlara-edge.container.template').read_text().replace('CADDY_IMAGE_DIGEST', image)
(stage/'nexlara-edge.container').write_text(unit)
(stage/'image.txt').write_text(image+'\n')
PY
podman run --rm --network=none \
  -v "$stage_dir/Caddyfile:/etc/caddy/Caddyfile:ro,Z" \
  "$edge_image" caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
install -d -m 700 /etc/nexlara-edge
install -m 600 "$stage_dir/Caddyfile" "$stage_dir/login.txt" \
  "$stage_dir/nexlara-edge.container" "$stage_dir/image.txt" /etc/nexlara-edge/
echo 'HTTPS configuration validated and staged at /etc/nexlara-edge.'
echo 'No service was installed or started. No firewall or DNS changes were made.'
echo 'Login credentials are in /etc/nexlara-edge/login.txt; do not paste them into chat.'
