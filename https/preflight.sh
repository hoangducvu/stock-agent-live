#!/usr/bin/env bash
# Read-only host and domain diagnostics. Run in a normal VM shell as opc.
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
bash validate-private.sh
echo '--- Domain addresses visible from this VM ---'
getent ahosts nexlara.eu || true
echo '--- VM IPv4 addresses ---'
ip -4 -brief address
echo '--- Existing HTTP/HTTPS listeners ---'
ss -lnt '( sport = :80 or sport = :443 )'
echo '--- Existing system proxy services ---'
systemctl is-active nginx.service httpd.service caddy.service || true
echo '--- Host firewall zones (requires sudo) ---'
sudo firewall-cmd --get-active-zones || true
sudo firewall-cmd --list-all || true
echo '--- Existing rootful containers ---'
sudo podman ps --format '{{.Names}} {{.Ports}}'
echo '--- Current HTTPS response (no credentials sent) ---'
curl --head --silent --show-error --connect-timeout 5 --max-time 15 https://nexlara.eu/ || true
echo 'No DNS, firewall, service, or trading settings were changed.'
