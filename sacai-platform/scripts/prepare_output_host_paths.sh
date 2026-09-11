#!/usr/bin/env bash
set -euo pipefail

# sacai-outputs, sacai-audit, and sacai-tool-versions are bind-mounted host
# directories, not Docker named volumes: unlike named volumes, Compose will
# happily auto-create a missing bind-mount path as an empty directory, which
# would silently start every service pointed at a *different* empty
# directory the first time paths are mistyped. Run this before the first
# `rebuild_offline.sh` on a host (and again if the *_HOST_PATH variables
# change) so the paths exist, are confirmed writable, and are shared for
# every service that mounts them.

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

for path in "${OUTPUT_PATH}" "${AUDIT_PATH}" "${TOOL_VERSIONS_PATH}"; do
  mkdir -p "${path}"
  if [[ ! -w "${path}" ]]; then
    echo "ERROR: ${path} exists but is not writable by $(id -un)." >&2
    exit 1
  fi
  echo "OK: ${path} -> $(cd "${path}" && pwd)"
done

echo
echo "All three host output paths exist and are writable. If an older"
echo "deployment on this host used the sacai-outputs / sacai-audit /"
echo "sacai-tool-versions named Docker volumes, run"
echo "scripts/migrate_named_volumes_to_bind_mounts.sh first so existing jobs,"
echo "audit records, and installed tool versions are not left behind."
