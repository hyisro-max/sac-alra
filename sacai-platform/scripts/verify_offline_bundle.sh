#!/usr/bin/env bash
set -euo pipefail

SACAI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

(cd "${SACAI_ROOT}/offline" && sha256sum --check SHA256SUMS)
(cd "${SACAI_ROOT}/offline" && sha256sum --check WHEELHOUSE_SHA256SUMS)
test -f "${SACAI_ROOT}/offline/images/runtime-images-amd64.tar"
test -n "$(find "${SACAI_ROOT}/offline/wheelhouse" -maxdepth 1 -name '*.whl' -print -quit)"
test -e "${SACAI_ROOT}/offline/apt-cache/rootfs/lib/x86_64-linux-gnu/libexpat.so.1"
test -s "${SACAI_ROOT}/offline/apt-cache/PACKAGES.txt"
test -s "${SACAI_ROOT}/offline/requirements-linux-amd64.lock.txt"
