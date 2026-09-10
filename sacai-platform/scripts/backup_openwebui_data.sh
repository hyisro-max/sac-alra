#!/usr/bin/env bash
set -euo pipefail

# Backs up the openwebui-data named volume (chats, users, settings, the
# OpenWebUI sqlite/Postgres-pointer database) to a plain host directory
# before a rebuild that will run OpenWebUI's own Alembic migrations against
# it, such as the v0.10.2 -> v0.11.3 upgrade. Run this before
# rebuild_offline.sh whenever the volume already holds real data; skip it on
# a genuinely first-time install with no prior deployment.

SACAI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${SACAI_ROOT}"

if ! docker volume inspect openwebui-data >/dev/null 2>&1; then
  echo "No existing 'openwebui-data' volume on this host; nothing to back up."
  exit 0
fi

BACKUP_DIR="${1:-offline/data/openwebui-data-backup-$(date +%Y%m%d-%H%M%S)}"
mkdir -p "${BACKUP_DIR}"
BACKUP_ABS="$(cd "${BACKUP_DIR}" && pwd)"

BACKUP_IMAGE="$(docker compose --env-file .env -f docker-compose.yml config 2>/dev/null \
  | awk '/^  sacai-api:/{f=1} f && /^    image:/{print $2; exit}')"
if [[ -z "${BACKUP_IMAGE}" ]]; then
  echo "ERROR: could not determine the sacai-api image tag from docker-compose.yml." >&2
  exit 1
fi
docker image inspect "${BACKUP_IMAGE}" >/dev/null

echo "Backing up openwebui-data -> ${BACKUP_ABS} ..."
docker run --rm \
  -v openwebui-data:/from:ro \
  -v "${BACKUP_ABS}:/to" \
  --entrypoint /bin/sh \
  "${BACKUP_IMAGE}" -c 'cp -a /from/. /to/'

echo "Done. Backup is at ${BACKUP_ABS}."
echo "Keep it until the upgraded stack has run successfully for a while."
