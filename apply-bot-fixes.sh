#!/usr/bin/env bash
# Install the validated candidate without starting bots or changing HTTPS.
set -euo pipefail
cd -- "$(dirname -- "$0")"
test "$(id -un)" = opc || { echo 'Run as opc, without sudo.' >&2; exit 1; }
bash validate-private.sh
podman image exists localhost/nexlara-api:reviewed
# Recheck the actual candidate rather than trusting an earlier tag/test result.
podman run --rm --network=none -e NEXLARA_REQUIRE_TEST_DEPS=1 \
  -v "$PWD/tests:/tests:ro,Z" localhost/nexlara-api:reviewed \
  python -B -m unittest discover -s /tests -q
release_stamp=$(date -u +%Y%m%dT%H%M%SZ)
snapshot="$PWD/deployment-review/backups/host-$release_stamp"
release_image="localhost/nexlara-api:release-$release_stamp"
podman tag localhost/nexlara-api:reviewed "$release_image"
mkdir -m 700 "$snapshot"
unit_dir="$HOME/.config/containers/systemd"
cp -a "$unit_dir/nexlara-api.container" "$snapshot/nexlara-api.container"
prior_image=$(podman inspect nexlara-api --format '{{.Image}}')
printf '%s\n' "$prior_image" > "$snapshot/api-image-id.txt"
# Add a retention tag so the previous image remains available for rollback.
podman tag "$prior_image" "localhost/nexlara-api:backup-$release_stamp"
for volume in nexlara-data nexlara-logs; do
  mountpoint=$(podman volume inspect "$volume" --format '{{.Mountpoint}}')
  podman unshare tar -C "$mountpoint" -czf "$snapshot/$volume.tar.gz" .
done
rollback() {
  cp -a "$snapshot/nexlara-api.container" "$unit_dir/nexlara-api.container"
  systemctl --user daemon-reload
  systemctl --user restart nexlara-api.service
  systemctl --user restart nexlara-web.service
  echo "Update failed; previous API configuration restored. Backups: $snapshot" >&2
}
trap rollback ERR
# Preserve all existing unit options, modifying only image and stop timeout.
python3 - "$unit_dir/nexlara-api.container" "$release_image" <<'PY'
from pathlib import Path
import re, sys
p = Path(sys.argv[1]); text = p.read_text()
assert len(re.findall(r'^Image=.*$', text, flags=re.M)) == 1
text = re.sub(r'^Image=.*$', 'Image='+sys.argv[2], text, flags=re.M)
if re.search(r'^TimeoutStopSec=', text, flags=re.M):
    text = re.sub(r'^TimeoutStopSec=.*$', 'TimeoutStopSec=90', text, flags=re.M)
else:
    text = text.replace('[Service]', '[Service]\nTimeoutStopSec=90', 1)
p.write_text(text)
PY
systemctl --user daemon-reload
systemctl --user restart nexlara-api.service
# Refresh nginx upstream DNS after the API container is replaced.
systemctl --user restart nexlara-web.service
curl --fail --silent --show-error --retry 15 --retry-delay 2 \
  --retry-connrefused --retry-all-errors --max-time 5 \
  http://127.0.0.1:8080/api/health
echo
bash validate-private.sh
trap - ERR
echo "API updated and private validation passed. Backups: $snapshot"
echo 'HTTPS/password protection unchanged. No bots or trades were started.'
echo 'Run sudo bash https/verify.sh to verify public access protection.'
