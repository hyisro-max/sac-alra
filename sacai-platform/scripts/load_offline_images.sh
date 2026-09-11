#!/usr/bin/env bash
set -euo pipefail

SACAI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

docker load -i "${SACAI_ROOT}/offline/images/runtime-images-amd64.tar"
docker image inspect sacai/openwebui:v0.11.3-sacalra1-amd64 >/dev/null
docker image inspect sacai/openwebui-python-deps:v0.11.3-sacalra1-amd64 >/dev/null
docker image inspect sacai/openwebui-node-deps:v0.11.3-sacalra1-amd64 >/dev/null

# asp-runtime is mandatory, not optional like isis/ch2 below: asp-worker is
# a default-enabled Compose service (no profile), so a missing tar here must
# fail loudly now rather than let `docker compose up` fail later on a
# missing image with a less obvious error.
docker load -i "${SACAI_ROOT}/offline/images/asp-runtime-amd64.tar"
docker image inspect sacai/asp-runtime:3.5.0-amd64 >/dev/null
docker image inspect sacai/asp-worker:3.5.0-sacai1-amd64 >/dev/null

if [[ -f "${SACAI_ROOT}/offline/images/isis-runtime-amd64.tar" ]]; then
  docker load -i "${SACAI_ROOT}/offline/images/isis-runtime-amd64.tar"
fi
if [[ -f "${SACAI_ROOT}/offline/images/ch2-runtime-amd64.tar" ]]; then
  docker load -i "${SACAI_ROOT}/offline/images/ch2-runtime-amd64.tar"
fi
if [[ -f "${SACAI_ROOT}/offline/images/otb-runtime-amd64.tar" ]]; then
  docker load -i "${SACAI_ROOT}/offline/images/otb-runtime-amd64.tar"
fi
