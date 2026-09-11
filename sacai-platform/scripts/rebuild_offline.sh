#!/usr/bin/env bash
set -euo pipefail

SACAI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENWEBUI_IMAGE="sacai/openwebui:v0.11.3-sacalra1-amd64"
COMPOSE=(docker compose --env-file "${SACAI_ROOT}/.env" -f "${SACAI_ROOT}/docker-compose.yml")

"${SACAI_ROOT}/scripts/prepare_output_host_paths.sh"

export DOCKER_BUILDKIT=1
"${COMPOSE[@]}" build --pull=false --no-cache

# Check the newly tagged image before replacing the running container. An old
# archive uses a different tag, so it cannot silently satisfy this lookup.
EXPECTED_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "${OPENWEBUI_IMAGE}")"
docker run --rm --network none --entrypoint sh "${OPENWEBUI_IMAGE}" -c '
  for variable in HTTP_PROXY HTTPS_PROXY NO_PROXY http_proxy https_proxy no_proxy; do
    value="$(printenv "${variable}" 2>/dev/null || true)"
    if [ -n "${value}" ]; then
      echo "Runtime proxy leak: ${variable}=${value}" >&2
      exit 1
    fi
  done'

"${COMPOSE[@]}" up -d --pull never --force-recreate --remove-orphans

CONTAINER_ID="$("${COMPOSE[@]}" ps -q openwebui)"
ACTUAL_IMAGE_ID="$(docker inspect --format '{{.Image}}' "${CONTAINER_ID}")"
if [[ "${ACTUAL_IMAGE_ID}" != "${EXPECTED_IMAGE_ID}" ]]; then
  echo "OpenWebUI container uses ${ACTUAL_IMAGE_ID}; expected ${EXPECTED_IMAGE_ID}." >&2
  exit 1
fi

"${COMPOSE[@]}" exec -T openwebui sh -c '
  for variable in HTTP_PROXY HTTPS_PROXY NO_PROXY http_proxy https_proxy no_proxy; do
    value="$(printenv "${variable}" 2>/dev/null || true)"
    if [ -n "${value}" ]; then
      echo "Container proxy leak: ${variable}=${value}" >&2
      exit 1
    fi
  done'

echo "OpenWebUI image ID: ${EXPECTED_IMAGE_ID}"
echo "All runtime proxy variables are empty."
