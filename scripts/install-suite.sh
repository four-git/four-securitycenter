#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ ${1:-} == --dry-run && $# == 1 ]]; then
  printf '%s\n' 'Check Debian 13 ARM64, Docker Compose and UID/GID; preserve existing config; create state/signature directories; resolve Debian digest; build image and record versions. No mount creation, credentials, service changes or automatic scans.'
  exit 0
fi
[[ $# == 0 ]] || { echo 'Usage: install-suite.sh [--dry-run]' >&2; exit 2; }
[[ $EUID == 0 ]] || { echo 'Run as root on the Pi' >&2; exit 2; }
source /etc/os-release
[[ $ID == debian && $VERSION_ID == 13 && $(uname -m) == aarch64 ]] || { echo 'Debian 13 ARM64 required' >&2; exit 2; }
command -v docker >/dev/null || { echo 'Install Docker using the official Debian instructions in the Docker runbook; no remote installer is executed.' >&2; exit 2; }
docker compose version
# Do not take over existing service identities or directories silently.
getent passwd 997 | grep -q ':983:' || { echo 'Provision scanner UID 997 / GID 983 first (review existing IDs).' >&2; exit 2; }
install -d -m 0750 /etc/four-securitycenter
if [[ ! -e /etc/four-securitycenter/scanner.json ]]; then
  install -m 0644 config/scanner.json /etc/four-securitycenter/scanner.json
fi
for directory in /var/lib/four-securitycenter /var/lib/clamav; do
  if [[ ! -d $directory ]]; then install -d -o 997 -g 983 -m 0750 "$directory"; fi
  [[ $(stat -c %u:%g "$directory") == 997:983 ]] || { echo "Review ownership of $directory; existing data left intact" >&2; exit 2; }
done
if [[ ! -e .env ]]; then
  docker pull --platform linux/arm64 debian:13-slim
  digest=$(docker image inspect debian:13-slim --format '{{index .RepoDigests 0}}')
  [[ $digest == debian@sha256:* ]] || { echo 'No verified image digest' >&2; exit 2; }
  umask 077
  printf 'DEBIAN_IMAGE=%s\nSCAN_INTERVAL_SECONDS=0\nDISCOVER_INTERVAL_SECONDS=0\n' "$digest" > .env
fi
docker compose config --quiet
SUITE_IMAGE=four-securitycenter:local docker compose build scanner
image=$(docker image inspect four-securitycenter:local --format '{{.Id}}')
# Pin every service to this immutable locally retained image. Keep old images for rollback.
if grep -q '^SUITE_IMAGE=' .env; then
  sed -i.bak "s/^SUITE_IMAGE=.*/SUITE_IMAGE=$image/" .env
else
  printf 'SUITE_IMAGE=%s\n' "$image" >> .env
fi
docker run --rm --network none --entrypoint cat "$image" /usr/local/share/package-versions.txt > package-versions.txt
python3 - "$image" <<'PY'
import json, pathlib, sys
p = pathlib.Path('deployment-manifest.json')
data = json.loads(p.read_text())
data.update(image_id=sys.argv[1], package_versions=pathlib.Path('package-versions.txt').read_text(), build_status='built; acceptance pending')
p.write_text(json.dumps(data, indent=2) + '\n')
PY
chmod +x suite scripts/install-suite.sh
printf '%s\n' 'Installed without starting services. Credentials belong in root-only /etc/four-securitycenter/smb.credentials on the host. Follow the migration runbook before suite start.'
