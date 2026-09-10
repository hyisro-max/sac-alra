#!/usr/bin/env bash
set -euo pipefail

SACAI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

docker load -i "${SACAI_ROOT}/offline/images/runtime-images-amd64.tar"
docker image inspect sacai/openwebui:v0.11.3-sacalra1-amd64 >/dev/null
docker image inspect sacai/openwebui-python-deps:v0.11.3-sacalra1-amd64 >/dev/null
docker image inspect sacai/openwebui-node-deps:v0.11.3-sacalra1-amd64 >/dev/null
if [[ -f "${SACAI_ROOT}/offline/images/isis-runtime-amd64.tar" ]]; then
  docker load -i "${SACAI_ROOT}/offline/images/isis-runtime-amd64.tar"
fi
