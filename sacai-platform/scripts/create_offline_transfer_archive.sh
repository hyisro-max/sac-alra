#!/usr/bin/env bash
set -euo pipefail

SACAI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "${SACAI_ROOT}/.." && pwd)"
OUTPUT_DIRECTORY="${1:-}"

if [[ -z "${OUTPUT_DIRECTORY}" ]]; then
  echo "Usage: $0 /path/outside/the/repository" >&2
  exit 1
fi

mkdir -p "${OUTPUT_DIRECTORY}"
OUTPUT_DIRECTORY="$(cd "${OUTPUT_DIRECTORY}" && pwd)"
case "${OUTPUT_DIRECTORY}/" in
  "${REPO_ROOT}/"*)
    echo "Output directory must be outside ${REPO_ROOT} to prevent recursive archives." >&2
    exit 1
    ;;
esac

"${SACAI_ROOT}/scripts/verify_offline_bundle.sh"
if [[ -n "$(find "${REPO_ROOT}" -type d \( -name .git -o -name .github \) -print -quit)" ]]; then
  echo "Refusing to package Git/GitHub metadata." >&2
  exit 1
fi
if [[ -n "$(find "${REPO_ROOT}" -type f -name '.git*' -print -quit)" ]]; then
  echo "Refusing to package Git metadata files." >&2
  exit 1
fi

ARCHIVE="${OUTPUT_DIRECTORY}/sacai-rhel95-offline-amd64.tar"
tar -C "$(dirname "${REPO_ROOT}")" -cf "${ARCHIVE}" "$(basename "${REPO_ROOT}")"
(cd "${OUTPUT_DIRECTORY}" && sha256sum "$(basename "${ARCHIVE}")" > "$(basename "${ARCHIVE}").sha256")

echo "Created ${ARCHIVE}"
echo "Created ${ARCHIVE}.sha256"
