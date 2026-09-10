#!/usr/bin/env bash
set -euo pipefail

SACAI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "${SACAI_ROOT}/.." && pwd)"
OUTPUT_ROOT="${SACAI_ROOT}/dist"
STAGING_ROOT="$(mktemp -d)"
STAGING_PROJECT="${STAGING_ROOT}/sacai-alma-builder"

cleanup() {
  "${SACAI_ROOT}/scripts/remove_staging_directory.sh" "${STAGING_ROOT}"
}
trap cleanup EXIT
export COPYFILE_DISABLE=1

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This source-packaging helper is intended to run on macOS." >&2
  exit 1
fi

mkdir -p "${OUTPUT_ROOT}" "${STAGING_PROJECT}/source-code"

copy_without_git_metadata() {
  local source_path="$1"
  local destination_parent="$2"
  tar \
    --exclude='.git' \
    --exclude='.git/**' \
    --exclude='.github' \
    --exclude='.github/**' \
    --exclude='.gitignore' \
    --exclude='.gitattributes' \
    --exclude='.gitmodules' \
    --exclude='.git-blame-ignore-revs' \
    --exclude='.git*' \
    --exclude='dist' \
    --exclude='dist/**' \
    --exclude='dist_old' \
    --exclude='dist_old/**' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.DS_Store' \
    -C "$(dirname "${source_path}")" \
    -cf - "$(basename "${source_path}")" \
    | tar -C "${destination_parent}" -xf -
}

copy_without_git_metadata "${REPO_ROOT}/source-code/open-webui" "${STAGING_PROJECT}/source-code"
copy_without_git_metadata "${REPO_ROOT}/source-code/pystac-client" "${STAGING_PROJECT}/source-code"
copy_without_git_metadata "${SACAI_ROOT}" "${STAGING_PROJECT}"

# The connected AlmaLinux host generates these large artifacts itself. Keep the
# directory placeholders so every build path already exists after extraction.
find "${STAGING_PROJECT}/sacai-platform/offline" -type f ! -name '.gitkeep' -delete
LEAKED_DIRECTORY="$(find "${STAGING_PROJECT}" -type d \( -name .git -o -name .github \) -print -quit)"
if [[ -n "${LEAKED_DIRECTORY}" ]]; then
  echo "Git/GitHub directory leaked into staging bundle: ${LEAKED_DIRECTORY}" >&2
  exit 1
fi
LEAKED_FILE="$(find "${STAGING_PROJECT}" -type f \( -name '.git*' -o -name '*.pyc' -o -name '.DS_Store' \) -print -quit)"
if [[ -n "${LEAKED_FILE}" ]]; then
  echo "Git/cache metadata leaked into staging bundle: ${LEAKED_FILE}" >&2
  exit 1
fi

(cd "${STAGING_PROJECT}" && find . -type f -print0 | xargs -0 shasum -a 256 | LC_ALL=C sort -k2) \
  > "${STAGING_ROOT}/SOURCE_MANIFEST.sha256"
mv "${STAGING_ROOT}/SOURCE_MANIFEST.sha256" "${STAGING_PROJECT}/SOURCE_MANIFEST.sha256"

ARCHIVE="${OUTPUT_ROOT}/sacai-alma-builder-source.tar.gz"
tar -C "${STAGING_ROOT}" -czf "${ARCHIVE}" sacai-alma-builder
(cd "${OUTPUT_ROOT}" && shasum -a 256 "$(basename "${ARCHIVE}")" > "$(basename "${ARCHIVE}").sha256")

echo "Created ${ARCHIVE}"
echo "Created ${ARCHIVE}.sha256"
