#!/usr/bin/env bash
set -uo pipefail

SACAI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose --env-file "${SACAI_ROOT}/.env" -f "${SACAI_ROOT}/docker-compose.yml")

echo "Container state"
"${COMPOSE[@]}" ps

echo
echo "Recent Chroma and OpenWebUI logs"
"${COMPOSE[@]}" logs --tail=200 chroma openwebui

echo
echo "Proxy variables inside OpenWebUI (every value must be empty)"
"${COMPOSE[@]}" exec -T openwebui sh -c '
  for variable in HTTP_PROXY HTTPS_PROXY NO_PROXY http_proxy https_proxy no_proxy; do
    value="$(printenv "${variable}" 2>/dev/null || true)"
    printf "%s=<%s>\n" "${variable}" "${value}"
  done'

echo
echo "Chroma heartbeat from inside the Chroma container"
"${COMPOSE[@]}" exec -T chroma \
  curl --silent --show-error --fail http://localhost:8000/api/v2/heartbeat

echo
echo "Chroma client connection from inside OpenWebUI"
"${COMPOSE[@]}" exec -T openwebui python -c \
  'import urllib.request; opener=urllib.request.build_opener(urllib.request.ProxyHandler({})); print(opener.open("http://chroma:8000/api/v2/heartbeat", timeout=10).read().decode())'
"${COMPOSE[@]}" exec -T openwebui python -c \
  'import chromadb; print(chromadb.HttpClient(host="chroma", port=8000, tenant="default_tenant", database="default_database").heartbeat())'

echo
echo "Configured Ollama connection from inside OpenWebUI"
"${COMPOSE[@]}" exec -T openwebui python -c \
  'import os, urllib.request; url=os.environ["OLLAMA_BASE_URL"].rstrip("/") + "/api/tags"; print(url); print(urllib.request.urlopen(url, timeout=10).status)'
