#!/usr/bin/env bash
set -euo pipefail

SACAI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "This connected builder must be x86_64/AMD64; found $(uname -m)." >&2
  exit 1
fi

if [[ ! -r /etc/os-release ]]; then
  echo "Cannot identify the connected builder operating system." >&2
  exit 1
fi

# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "almalinux" || "${VERSION_ID%%.*}" != "9" ]]; then
  echo "Expected AlmaLinux 9.x; found ${PRETTY_NAME:-unknown}." >&2
  exit 1
fi

docker info >/dev/null
docker compose version >/dev/null

test -f "${SACAI_ROOT}/../source-code/open-webui/package-lock.json"
test -f "${SACAI_ROOT}/../source-code/pystac-client/pyproject.toml"

chmod +x "${SACAI_ROOT}"/scripts/*.sh
"${SACAI_ROOT}/scripts/prepare_connected_bundle.sh"
"${SACAI_ROOT}/scripts/verify_offline_bundle.sh"

echo "Connected AlmaLinux bundle preparation passed."
echo "Transfer the complete repository, including sacai-platform/offline, to RHEL 9.5."

