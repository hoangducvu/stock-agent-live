#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [ "$(id -u)" -eq 0 ]; then
  echo 'Run as opc, without sudo.' >&2
  exit 1
fi
command -v podman >/dev/null
command -v curl >/dev/null
systemctl --user show-environment >/dev/null
unit_dir="$HOME/.config/containers/systemd"
mkdir -p "$unit_dir"
for file in quadlet/*; do
  target="$unit_dir/$(basename "$file")"
  if [ -e "$target" ] && ! cmp -s "$file" "$target"; then
    echo "Existing configuration differs: $target. Preserve it before installing." >&2
    exit 1
  fi
done
podman build -t localhost/nexlara-api:oracle -f Containerfile.api .
podman build -t localhost/nexlara-web:oracle -f Containerfile.web .
for file in quadlet/*; do
  install -m 644 "$file" "$unit_dir/$(basename "$file")"
done
systemctl --user daemon-reload
systemctl --user restart nexlara-api.service
systemctl --user restart nexlara-web.service
bash ./check.sh
