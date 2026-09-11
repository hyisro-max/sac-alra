#!/usr/bin/env bash
set -euo pipefail

# One-time migration for a host that already ran an earlier SAC-ALRA release
# where sacai-outputs, sacai-audit, and sacai-tool-versions were Docker named
# volumes (under /var/lib/docker/volumes/..., not a plain host directory).
# This copies their contents into the bind-mount paths this release uses
# instead, then leaves the old named volumes in place untouched -- nothing
# here deletes them. Safe to re-run; it only copies data that is not already
# present at the destination.
#
# Run this BEFORE the first `rebuild_offline.sh` after upgrading to a release
# with bind-mounted outputs. It does not start or stop any service itself.

SACAI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${SACAI_ROOT}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

OUTPUT_PATH="${SACAI_OUTPUT_HOST_PATH:-./offline/data/outputs}"
AUDIT_PATH="${SACAI_AUDIT_HOST_PATH:-./offline/data/audit}"
TOOL_VERSIONS_PATH="${SACAI_TOOL_VERSIONS_HOST_PATH:-./offline/data/tool_versions}"

# Reuse the scientific-service image already loaded offline by
# load_offline_images.sh (a plain `docker run alpine ...` would try to pull an
# image this host was never given) -- it is Debian-based with coreutils cp.
MIGRATION_IMAGE="$(docker compose --env-file .env -f docker-compose.yml config 2>/dev/null \
  | awk '/^  sacai-api:/{f=1} f && /^    image:/{print $2; exit}')"
if [[ -z "${MIGRATION_IMAGE}" ]]; then
  echo "ERROR: could not determine the sacai-api image tag from docker-compose.yml." >&2
  exit 1
fi
docker image inspect "${MIGRATION_IMAGE}" >/dev/null

migrate_one() {
  local volume_name="$1" dest_path="$2"
  if ! docker volume inspect "${volume_name}" >/dev/null 2>&1; then
    echo "SKIP: no existing '${volume_name}' named volume on this host."
    return
  fi
  mkdir -p "${dest_path}"
  local dest_abs
  dest_abs="$(cd "${dest_path}" && pwd)"
  echo "Copying ${volume_name} -> ${dest_abs} (existing files at the destination are kept, not overwritten) ..."
  docker run --rm \
    -v "${volume_name}:/from:ro" \
    -v "${dest_abs}:/to" \
    --entrypoint /bin/sh \
    "${MIGRATION_IMAGE}" -c 'cp -a -n /from/. /to/'
  echo "Done: ${volume_name}."
}

migrate_one sacai-outputs "${OUTPUT_PATH}"
migrate_one sacai-audit "${AUDIT_PATH}"
migrate_one sacai-tool-versions "${TOOL_VERSIONS_PATH}"

echo
echo "Migration copy complete. Verify the file counts/sizes look right, then"
echo "run rebuild_offline.sh. The old named volumes were left in place; once"
echo "you have confirmed the bind-mounted data is correct and the stack has"
echo "run successfully on it, you may remove them with:"
echo "  docker volume rm sacai-outputs sacai-audit sacai-tool-versions"
