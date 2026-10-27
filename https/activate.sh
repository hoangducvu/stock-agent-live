#!/usr/bin/env bash
# Run after confirming Cloudflare origin routing and OCI ingress.
# Opens host HTTP/HTTPS and starts the staged gateway. No DNS changes.
set -euo pipefail
umask 077
if [ "$(id -u)" -ne 0 ]; then
  echo 'Run with sudo from the normal VM shell.' >&2
  exit 1
fi
test -s /etc/nexlara-edge/Caddyfile
test -s /etc/nexlara-edge/nexlara-edge.container
test -s /etc/nexlara-edge/login.txt
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8080/api/health |
  python3 -c 'import json,sys; h=json.load(sys.stdin); assert h.get("status")=="ok" and h.get("bot_running") is False, "Private API unhealthy or trading active"'
target=/etc/containers/systemd/nexlara-edge.container
if [ -e "$target" ]; then
  cmp -s /etc/nexlara-edge/nexlara-edge.container "$target" || {
    echo 'Existing Quadlet differs; refusing to overwrite it.' >&2
    exit 1
  }
else
  if [ -n "$(ss -H -lnt '( sport = :80 or sport = :443 )')" ]; then
    echo 'HTTP/HTTPS ports are occupied; review listeners before installing.' >&2
    exit 1
  fi
fi
firewall-cmd --state
test "$(firewall-cmd --get-zone-of-interface=enp0s6)" = public || {
  echo 'The active interface zone changed; review firewall configuration.' >&2
  exit 1
}
for directory in /var/lib/nexlara-edge /var/lib/nexlara-edge/data /var/lib/nexlara-edge/config; do
  if [ ! -e "$directory" ]; then install -d -m 700 "$directory"; fi
done
install -d -m 755 /etc/containers/systemd
if [ ! -e "$target" ]; then
  install -m 644 /etc/nexlara-edge/nexlara-edge.container "$target"
fi
systemctl daemon-reload
systemctl start nexlara-edge.service
systemctl is-active --quiet nexlara-edge.service
# Add only web services; preserve SSH and existing rules without a reload.
for service in http https; do
  firewall-cmd --zone=public --add-service="$service"
  firewall-cmd --permanent --zone=public --add-service="$service"
done
test -L /run/systemd/generator/multi-user.target.wants/nexlara-edge.service
echo 'Gateway started; boot link exists; host HTTP/HTTPS ingress allowed.'
echo 'DNS and OCI ingress unchanged. Certificate issuance may still be pending.'
echo 'Next: sudo bash https/verify.sh'
