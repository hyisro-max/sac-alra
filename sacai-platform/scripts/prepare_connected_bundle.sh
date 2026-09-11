#!/usr/bin/env bash
set -euo pipefail

SACAI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "${SACAI_ROOT}/.." && pwd)"

mkdir -p \
  "${SACAI_ROOT}/offline/wheelhouse" \
  "${SACAI_ROOT}/offline/images" \
  "${SACAI_ROOT}/offline/models/openwebui-cache" \
  "${SACAI_ROOT}/offline/apt-cache/rootfs/lib/x86_64-linux-gnu"

# Docker Desktop connected-builder proxy.
# IMPORTANT:
# - Do NOT add --add-host=http.docker.internal:host-gateway.
# - Docker Desktop provides http.docker.internal itself.
BUILD_PROXY_URL="${SACAI_BUILD_PROXY_URL:-http://http.docker.internal:3128}"
NO_PROXY_VALUE="${SACAI_BUILD_NO_PROXY:-localhost,127.0.0.1,chroma,redis,sacai-api,hubproxy.docker.internal}"

PROXY_ARGS=()
PROXY_ENV=()
PROXY_HOST_ARGS=()

if [[ -n "${BUILD_PROXY_URL}" ]]; then
  PROXY_ARGS=(
    --build-arg "HTTP_PROXY=${BUILD_PROXY_URL}"
    --build-arg "HTTPS_PROXY=${BUILD_PROXY_URL}"
    --build-arg "NO_PROXY=${NO_PROXY_VALUE}"
    --build-arg "http_proxy=${BUILD_PROXY_URL}"
    --build-arg "https_proxy=${BUILD_PROXY_URL}"
    --build-arg "no_proxy=${NO_PROXY_VALUE}"
  )

  PROXY_ENV=(
    --env "HTTP_PROXY=${BUILD_PROXY_URL}"
    --env "HTTPS_PROXY=${BUILD_PROXY_URL}"
    --env "NO_PROXY=${NO_PROXY_VALUE}"
    --env "http_proxy=${BUILD_PROXY_URL}"
    --env "https_proxy=${BUILD_PROXY_URL}"
    --env "no_proxy=${NO_PROXY_VALUE}"
  )
fi

# A stale wheel can hide a missing/new dependency or introduce another ABI.
# Preserve the directory but rebuild the wheel set from zero.
find "${SACAI_ROOT}/offline/wheelhouse" \
  -maxdepth 1 -type f -name '*.whl' -delete

find "${SACAI_ROOT}/offline/apt-cache/rootfs" \
  -mindepth 1 -delete

mkdir -p \
  "${SACAI_ROOT}/offline/apt-cache/rootfs/lib/x86_64-linux-gnu"

# ---------------------------------------------------------------------------
# Pull base images
# ---------------------------------------------------------------------------

docker pull --platform=linux/amd64 node:22-alpine3.20
docker pull --platform=linux/amd64 python:3.11-slim-bookworm
docker pull --platform=linux/amd64 redis:7.4.2-alpine
docker pull --platform=linux/amd64 chromadb/chroma:1.5.9

# ---------------------------------------------------------------------------
# Build OpenWebUI dependency images
# ---------------------------------------------------------------------------

docker build --platform=linux/amd64 \
  "${PROXY_ARGS[@]}" \
  -f "${SACAI_ROOT}/docker/openwebui-node-deps.Dockerfile" \
  -t sacai/openwebui-node-deps:v0.11.3-sacalra1-amd64 \
  "${REPO_ROOT}"

docker build --platform=linux/amd64 \
  "${PROXY_ARGS[@]}" \
  -f "${SACAI_ROOT}/docker/openwebui-python-deps.Dockerfile" \
  -t sacai/openwebui-python-deps:v0.11.3-sacalra1-amd64 \
  "${REPO_ROOT}"

# ---------------------------------------------------------------------------
# Optional ISIS runtime base image
#
# Set SACAI_BUILD_ISIS=1 to build the ISIS base image in this run. Skipped
# by default so ordinary connected-bundle runs stay fast, matching
# ISIS3_OFFLINE.md's framing of ISIS as an optional container.
#
# This must run BEFORE the wheelhouse download below: the wheelhouse step
# wipes and rebuilds offline/wheelhouse/*.whl from zero, and one of those
# packages (bcrypt, a chromadb dependency) needs a second, isis-runtime-
# specific download pass to get a wheel that image's older glibc can use.
# That pass is gated on sacai/isis-runtime already existing, so the image
# build has to happen first.
# ---------------------------------------------------------------------------

if [[ "${SACAI_BUILD_ISIS:-0}" == "1" ]]; then

  # isis-runtime needs real internet egress (conda channels), so unlike the
  # --network=none builds later in this script, it goes through the same
  # Docker Desktop connected-builder proxy as the node/python deps images.
  docker build --platform=linux/amd64 \
    "${PROXY_ARGS[@]}" \
    -f "${SACAI_ROOT}/docker/isis-runtime.Dockerfile" \
    -t sacai/isis-runtime:8.3.0-amd64 \
    "${REPO_ROOT}"

fi

# ---------------------------------------------------------------------------
# ASP (Ames Stereo Pipeline) runtime base image
#
# Unlike SACAI_BUILD_ISIS/SACAI_BUILD_CH2 (both truly optional missions/
# containers), asp-worker is a default-enabled Compose service -- lunar DEM
# generation is this platform's stated main goal, the same way
# planetir-worker is always on. So this builds by default; set
# SACAI_BUILD_ASP=0 to skip it in a run that only needs the other images
# (e.g. iterating on OpenWebUI/service changes without re-touching ASP).
# Needs real internet egress through the connected-builder proxy, same as
# the ISIS build above.
# ---------------------------------------------------------------------------

if [[ "${SACAI_BUILD_ASP:-1}" == "1" ]]; then

  docker build --platform=linux/amd64 \
    "${PROXY_ARGS[@]}" \
    -f "${SACAI_ROOT}/docker/asp-runtime.Dockerfile" \
    -t sacai/asp-runtime:3.5.0-amd64 \
    "${REPO_ROOT}"

fi

# ---------------------------------------------------------------------------
# Optional CH2 (Chandrayaan-2 TMC-2, ISIS 10 RC2) runtime base image
#
# Set SACAI_BUILD_CH2=1 to build it in this run. Mission-specific and
# skipped by default, same as SACAI_BUILD_ISIS/SACAI_BUILD_ASP above.
# ---------------------------------------------------------------------------

if [[ "${SACAI_BUILD_CH2:-0}" == "1" ]]; then

  docker build --platform=linux/amd64 \
    "${PROXY_ARGS[@]}" \
    -f "${SACAI_ROOT}/docker/ch2-runtime.Dockerfile" \
    -t sacai/ch2-runtime:10.0.0rc2-amd64 \
    "${REPO_ROOT}"

fi

# ---------------------------------------------------------------------------
# Download scientific-service Python wheelhouse
# ---------------------------------------------------------------------------

docker run --rm --platform=linux/amd64 \
  "${PROXY_HOST_ARGS[@]}" \
  "${PROXY_ENV[@]}" \
  -v "${SACAI_ROOT}/service:/source:ro" \
  -v "${SACAI_ROOT}/offline/wheelhouse:/wheelhouse" \
  python:3.11-slim-bookworm \
  sh -c '
    python -m pip download \
      --only-binary=:all: \
      --dest /wheelhouse \
      -r /source/requirements.txt \
      -r /source/test-requirements.txt
  '

# ---------------------------------------------------------------------------
# ISIS-target-compatible bcrypt wheel
#
# The main wheelhouse download above uses python:3.11-slim-bookworm (glibc
# 2.36) as its reference environment, so pip resolves the newest compatible
# bcrypt wheel: manylinux_2_34. sacai/isis-runtime is built on an older base
# (glibc 2.31) and cannot use that wheel ("no matching distribution found"
# even though a bcrypt file is present). Fetch a second bcrypt wheel using
# isis-runtime's own Python as the resolution environment so pip picks a tag
# (manylinux_2_28 as of bcrypt 5.0.0) that image can actually install. Only
# runs when the ISIS image exists. Both wheels are kept in the wheelhouse;
# pip selects the compatible one automatically at install time.
# ---------------------------------------------------------------------------

if docker image inspect sacai/isis-runtime:8.3.0-amd64 >/dev/null 2>&1; then
  docker run --rm --platform=linux/amd64 \
    --entrypoint /opt/conda/envs/isis/bin/python \
    "${PROXY_ENV[@]}" \
    -v "${SACAI_ROOT}/offline/wheelhouse:/wheelhouse" \
    sacai/isis-runtime:8.3.0-amd64 \
    -m pip download --only-binary=:all: --dest /wheelhouse "bcrypt>=4.0.1"
fi

# ---------------------------------------------------------------------------
# Stage libexpat from the same Debian release as the service base image
# ---------------------------------------------------------------------------

docker run --rm --platform=linux/amd64 \
  "${PROXY_HOST_ARGS[@]}" \
  "${PROXY_ENV[@]}" \
  -v "${SACAI_ROOT}/offline/apt-cache:/apt-cache" \
  python:3.11-slim-bookworm \
  sh -c '
    set -eu

    apt_proxy="${HTTP_PROXY:-false}"

    apt-get \
      -o Acquire::http::Proxy="${apt_proxy}" \
      -o Acquire::https::Proxy="${apt_proxy}" \
      update

    mkdir -p /tmp/apt-download /tmp/apt-rootfs
    cd /tmp/apt-download

    apt-get \
      -o Acquire::http::Proxy="${apt_proxy}" \
      -o Acquire::https::Proxy="${apt_proxy}" \
      -o APT::Sandbox::User=root \
      download libexpat1

    deb_file="$(find . -maxdepth 1 -name "libexpat1_*.deb" -print -quit)"
    test -n "${deb_file}"

    dpkg-deb -x "${deb_file}" /tmp/apt-rootfs
    dpkg-deb -f "${deb_file}" Package Version Architecture \
      > /tmp/PACKAGES.txt

    cp -a --no-preserve=ownership \
      /tmp/apt-rootfs/. \
      /apt-cache/rootfs/

    cp --no-preserve=ownership \
      /tmp/PACKAGES.txt \
      /apt-cache/PACKAGES.txt
  '

test -e \
  "${SACAI_ROOT}/offline/apt-cache/rootfs/lib/x86_64-linux-gnu/libexpat.so.1"

# ---------------------------------------------------------------------------
# Populate OpenWebUI offline model/cache bundle
# ---------------------------------------------------------------------------

docker run --rm --platform=linux/amd64 \
  "${PROXY_HOST_ARGS[@]}" \
  "${PROXY_ENV[@]}" \
  -e HF_HOME=/cache/embedding/models \
  -e SENTENCE_TRANSFORMERS_HOME=/cache/embedding/models \
  -e WHISPER_MODEL_DIR=/cache/whisper/models \
  -e TIKTOKEN_CACHE_DIR=/cache/tiktoken \
  -v "${SACAI_ROOT}/offline/models/openwebui-cache:/cache" \
  sacai/openwebui-python-deps:v0.11.3-sacalra1-amd64 \
  sh -c '
    python -c "
from sentence_transformers import SentenceTransformer

SentenceTransformer(\"sentence-transformers/all-MiniLM-L6-v2\")
SentenceTransformer(\"TaylorAI/bge-micro-v2\")

from faster_whisper import WhisperModel
WhisperModel(
    \"base\",
    device=\"cpu\",
    compute_type=\"int8\",
    download_root=\"/cache/whisper/models\"
)

import tiktoken
tiktoken.get_encoding(\"cl100k_base\")

import nltk
nltk.download(\"punkt_tab\", download_dir=\"/cache/nltk_data\")
"
  '

# ---------------------------------------------------------------------------
# Build final OpenWebUI runtime image fully offline
# ---------------------------------------------------------------------------

docker build --platform=linux/amd64 --network=none \
  --build-arg NODE_DEPS_IMAGE=sacai/openwebui-node-deps:v0.11.3-sacalra1-amd64 \
  --build-arg PYTHON_DEPS_IMAGE=sacai/openwebui-python-deps:v0.11.3-sacalra1-amd64 \
  -f "${SACAI_ROOT}/docker/openwebui.Dockerfile" \
  -t sacai/openwebui:v0.11.3-sacalra1-amd64 \
  "${REPO_ROOT}"

# Refuse to package an OpenWebUI runtime image containing any non-empty proxy
# variable. This catches both uppercase and lowercase inherited image metadata.
docker run --rm --platform=linux/amd64 \
  --entrypoint sh \
  sacai/openwebui:v0.11.3-sacalra1-amd64 \
  -c '
    for variable in HTTP_PROXY HTTPS_PROXY NO_PROXY http_proxy https_proxy no_proxy; do
      value="$(printenv "${variable}" 2>/dev/null || true)"
      if [ -n "${value}" ]; then
        echo "Runtime proxy leak: ${variable}=${value}" >&2
        exit 1
      fi
    done
  '

# ---------------------------------------------------------------------------
# Build scientific service and tests fully offline
# ---------------------------------------------------------------------------

docker build --platform=linux/amd64 --network=none \
  -f "${SACAI_ROOT}/docker/service.Dockerfile" \
  -t sacai/scientific-service:1.1.0-amd64 \
  "${REPO_ROOT}"

docker build --platform=linux/amd64 --network=none \
  -f "${SACAI_ROOT}/docker/service-test.Dockerfile" \
  -t sacai/tests:1.1.0-amd64 \
  "${REPO_ROOT}"

docker run --rm --platform=linux/amd64 \
  sacai/tests:1.1.0-amd64

docker run --rm --platform=linux/amd64 \
  sacai/tests:1.1.0-amd64 \
  sh -c 'python -m pip check && python -m pip freeze --all' \
  > "${SACAI_ROOT}/offline/requirements-linux-amd64.lock.txt"

(
  cd "${SACAI_ROOT}/offline"
  sha256sum wheelhouse/*.whl > WHEELHOUSE_SHA256SUMS
)

# ---------------------------------------------------------------------------
# Optional ISIS worker image (built on top of the base image staged above)
# ---------------------------------------------------------------------------

if docker image inspect sacai/isis-runtime:8.3.0-amd64 >/dev/null 2>&1; then
  docker build --platform=linux/amd64 --network=none \
    -f "${SACAI_ROOT}/docker/isis-worker.Dockerfile" \
    -t sacai/isis-worker:8.3.0-sacai1-amd64 \
    "${REPO_ROOT}"

  docker save \
    -o "${SACAI_ROOT}/offline/images/isis-runtime-amd64.tar" \
    sacai/isis-runtime:8.3.0-amd64 \
    sacai/isis-worker:8.3.0-sacai1-amd64
fi

# ---------------------------------------------------------------------------
# Optional ASP worker image (built on top of the base image staged above)
# ---------------------------------------------------------------------------

if docker image inspect sacai/asp-runtime:3.5.0-amd64 >/dev/null 2>&1; then
  docker build --platform=linux/amd64 --network=none \
    -f "${SACAI_ROOT}/docker/asp-worker.Dockerfile" \
    -t sacai/asp-worker:3.5.0-sacai1-amd64 \
    "${REPO_ROOT}"

  docker save \
    -o "${SACAI_ROOT}/offline/images/asp-runtime-amd64.tar" \
    sacai/asp-runtime:3.5.0-amd64 \
    sacai/asp-worker:3.5.0-sacai1-amd64
fi

# ---------------------------------------------------------------------------
# Optional CH2 worker image (built on top of the base image staged above)
# ---------------------------------------------------------------------------

if docker image inspect sacai/ch2-runtime:10.0.0rc2-amd64 >/dev/null 2>&1; then
  docker build --platform=linux/amd64 --network=none \
    -f "${SACAI_ROOT}/docker/ch2-worker.Dockerfile" \
    -t sacai/ch2-worker:10.0.0rc2-sacai1-amd64 \
    "${REPO_ROOT}"

  docker save \
    -o "${SACAI_ROOT}/offline/images/ch2-runtime-amd64.tar" \
    sacai/ch2-runtime:10.0.0rc2-amd64 \
    sacai/ch2-worker:10.0.0rc2-sacai1-amd64
fi

# ---------------------------------------------------------------------------
# Save all runtime images
# ---------------------------------------------------------------------------

docker save \
  -o "${SACAI_ROOT}/offline/images/runtime-images-amd64.tar" \
  node:22-alpine3.20 \
  python:3.11-slim-bookworm \
  redis:7.4.2-alpine \
  chromadb/chroma:1.5.9 \
  sacai/openwebui-node-deps:v0.11.3-sacalra1-amd64 \
  sacai/openwebui-python-deps:v0.11.3-sacalra1-amd64 \
  sacai/openwebui:v0.11.3-sacalra1-amd64 \
  sacai/scientific-service:1.1.0-amd64 \
  sacai/tests:1.1.0-amd64

# ---------------------------------------------------------------------------
# Generate final bundle checksums
# ---------------------------------------------------------------------------

(
  cd "${SACAI_ROOT}/offline"
  find . -type f ! -name SHA256SUMS -print0 \
    | sort -z \
    | xargs -0 sha256sum \
    > SHA256SUMS
)

echo
echo "Connected bundle preparation completed successfully."
echo "OpenWebUI tag: sacai/openwebui:v0.11.3-sacalra1-amd64"



# #!/usr/bin/env bash
# set -euo pipefail

# SACAI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# REPO_ROOT="$(cd "${SACAI_ROOT}/.." && pwd)"

# mkdir -p \
#   "${SACAI_ROOT}/offline/wheelhouse" \
#   "${SACAI_ROOT}/offline/images" \
#   "${SACAI_ROOT}/offline/models/openwebui-cache" \
#   "${SACAI_ROOT}/offline/apt-cache/rootfs/lib/x86_64-linux-gnu"

# # Docker Desktop connected-builder proxy.
# # IMPORTANT:
# # - Do NOT add --add-host=http.docker.internal:host-gateway.
# # - Docker Desktop provides http.docker.internal itself.
# BUILD_PROXY_URL="${SACAI_BUILD_PROXY_URL:-http://http.docker.internal:3128}"
# NO_PROXY_VALUE="${SACAI_BUILD_NO_PROXY:-localhost,127.0.0.1,chroma,redis,sacai-api,hubproxy.docker.internal}"

# PROXY_ARGS=()
# PROXY_ENV=()
# PROXY_HOST_ARGS=()

# if [[ -n "${BUILD_PROXY_URL}" ]]; then
#   PROXY_ARGS=(
#     --build-arg "HTTP_PROXY=${BUILD_PROXY_URL}"
#     --build-arg "HTTPS_PROXY=${BUILD_PROXY_URL}"
#     --build-arg "NO_PROXY=${NO_PROXY_VALUE}"
#     --build-arg "http_proxy=${BUILD_PROXY_URL}"
#     --build-arg "https_proxy=${BUILD_PROXY_URL}"
#     --build-arg "no_proxy=${NO_PROXY_VALUE}"
#   )

#   PROXY_ENV=(
#     --env "HTTP_PROXY=${BUILD_PROXY_URL}"
#     --env "HTTPS_PROXY=${BUILD_PROXY_URL}"
#     --env "NO_PROXY=${NO_PROXY_VALUE}"
#     --env "http_proxy=${BUILD_PROXY_URL}"
#     --env "https_proxy=${BUILD_PROXY_URL}"
#     --env "no_proxy=${NO_PROXY_VALUE}"
#   )
# fi

# # A stale wheel can hide a missing/new dependency or introduce another ABI.
# # Preserve the directory but rebuild the wheel set from zero.
# find "${SACAI_ROOT}/offline/wheelhouse" \
#   -maxdepth 1 -type f -name '*.whl' -delete

# find "${SACAI_ROOT}/offline/apt-cache/rootfs" \
#   -mindepth 1 -delete

# mkdir -p \
#   "${SACAI_ROOT}/offline/apt-cache/rootfs/lib/x86_64-linux-gnu"

# # ---------------------------------------------------------------------------
# # Pull base images
# # ---------------------------------------------------------------------------

# docker pull --platform=linux/amd64 node:22-alpine3.20
# docker pull --platform=linux/amd64 python:3.11-slim-bookworm
# docker pull --platform=linux/amd64 redis:7.4.2-alpine
# docker pull --platform=linux/amd64 chromadb/chroma:1.5.9

# # ---------------------------------------------------------------------------
# # Build OpenWebUI dependency images
# # ---------------------------------------------------------------------------

# docker build --platform=linux/amd64 \
#   "${PROXY_ARGS[@]}" \
#   -f "${SACAI_ROOT}/docker/openwebui-node-deps.Dockerfile" \
#   -t sacai/openwebui-node-deps:v0.11.3-sacalra1-amd64 \
#   "${REPO_ROOT}"

# docker build --platform=linux/amd64 \
#   "${PROXY_ARGS[@]}" \
#   -f "${SACAI_ROOT}/docker/openwebui-python-deps.Dockerfile" \
#   -t sacai/openwebui-python-deps:v0.11.3-sacalra1-amd64 \
#   "${REPO_ROOT}"

# # ---------------------------------------------------------------------------
# # Download scientific-service Python wheelhouse
# # ---------------------------------------------------------------------------

# docker run --rm --platform=linux/amd64 \
#   "${PROXY_HOST_ARGS[@]}" \
#   "${PROXY_ENV[@]}" \
#   -v "${SACAI_ROOT}/service:/source:ro" \
#   -v "${SACAI_ROOT}/offline/wheelhouse:/wheelhouse" \
#   python:3.11-slim-bookworm \
#   sh -c '
#     python -m pip download \
#       --only-binary=:all: \
#       --dest /wheelhouse \
#       -r /source/requirements.txt \
#       -r /source/test-requirements.txt
#   '

# # ---------------------------------------------------------------------------
# # Stage libexpat from the same Debian release as the service base image
# # ---------------------------------------------------------------------------

# docker run --rm --platform=linux/amd64 \
#   "${PROXY_HOST_ARGS[@]}" \
#   "${PROXY_ENV[@]}" \
#   -v "${SACAI_ROOT}/offline/apt-cache:/apt-cache" \
#   python:3.11-slim-bookworm \
#   sh -c '
#     set -eu

#     apt_proxy="${HTTP_PROXY:-false}"

#     apt-get \
#       -o Acquire::http::Proxy="${apt_proxy}" \
#       -o Acquire::https::Proxy="${apt_proxy}" \
#       update

#     mkdir -p /tmp/apt-download /tmp/apt-rootfs
#     cd /tmp/apt-download

#     apt-get \
#       -o Acquire::http::Proxy="${apt_proxy}" \
#       -o Acquire::https::Proxy="${apt_proxy}" \
#       -o APT::Sandbox::User=root \
#       download libexpat1

#     deb_file="$(find . -maxdepth 1 -name "libexpat1_*.deb" -print -quit)"
#     test -n "${deb_file}"

#     dpkg-deb -x "${deb_file}" /tmp/apt-rootfs
#     dpkg-deb -f "${deb_file}" Package Version Architecture \
#       > /tmp/PACKAGES.txt

#     cp -a --no-preserve=ownership \
#       /tmp/apt-rootfs/. \
#       /apt-cache/rootfs/

#     cp --no-preserve=ownership \
#       /tmp/PACKAGES.txt \
#       /apt-cache/PACKAGES.txt
#   '

# test -e \
#   "${SACAI_ROOT}/offline/apt-cache/rootfs/lib/x86_64-linux-gnu/libexpat.so.1"

# # ---------------------------------------------------------------------------
# # Populate OpenWebUI offline model/cache bundle
# # ---------------------------------------------------------------------------

# docker run --rm --platform=linux/amd64 \
#   "${PROXY_HOST_ARGS[@]}" \
#   "${PROXY_ENV[@]}" \
#   -e HF_HOME=/cache/embedding/models \
#   -e SENTENCE_TRANSFORMERS_HOME=/cache/embedding/models \
#   -e WHISPER_MODEL_DIR=/cache/whisper/models \
#   -e TIKTOKEN_CACHE_DIR=/cache/tiktoken \
#   -v "${SACAI_ROOT}/offline/models/openwebui-cache:/cache" \
#   sacai/openwebui-python-deps:v0.11.3-sacalra1-amd64 \
#   sh -c '
#     python -c "
# from sentence_transformers import SentenceTransformer

# SentenceTransformer(\"sentence-transformers/all-MiniLM-L6-v2\")
# SentenceTransformer(\"TaylorAI/bge-micro-v2\")

# from faster_whisper import WhisperModel
# WhisperModel(
#     \"base\",
#     device=\"cpu\",
#     compute_type=\"int8\",
#     download_root=\"/cache/whisper/models\"
# )

# import tiktoken
# tiktoken.get_encoding(\"cl100k_base\")

# import nltk
# nltk.download(\"punkt_tab\", download_dir=\"/cache/nltk_data\")
# "
#   '

# # ---------------------------------------------------------------------------
# # Build final OpenWebUI runtime image fully offline
# # ---------------------------------------------------------------------------

# docker build --platform=linux/amd64 --network=none \
#   --build-arg NODE_DEPS_IMAGE=sacai/openwebui-node-deps:v0.11.3-sacalra1-amd64 \
#   --build-arg PYTHON_DEPS_IMAGE=sacai/openwebui-python-deps:v0.11.3-sacalra1-amd64 \
#   -f "${SACAI_ROOT}/docker/openwebui.Dockerfile" \
#   -t sacai/openwebui:v0.11.3-sacalra1-amd64 \
#   "${REPO_ROOT}"

# # Refuse to package an OpenWebUI runtime image containing any non-empty proxy
# # variable. This catches both uppercase and lowercase inherited image metadata.
# docker run --rm --platform=linux/amd64 \
#   --entrypoint sh \
#   sacai/openwebui:v0.11.3-sacalra1-amd64 \
#   -c '
#     for variable in HTTP_PROXY HTTPS_PROXY NO_PROXY http_proxy https_proxy no_proxy; do
#       value="$(printenv "${variable}" 2>/dev/null || true)"
#       if [ -n "${value}" ]; then
#         echo "Runtime proxy leak: ${variable}=${value}" >&2
#         exit 1
#       fi
#     done
#   '

# # ---------------------------------------------------------------------------
# # Build scientific service and tests fully offline
# # ---------------------------------------------------------------------------

# docker build --platform=linux/amd64 --network=none \
#   -f "${SACAI_ROOT}/docker/service.Dockerfile" \
#   -t sacai/scientific-service:1.1.0-amd64 \
#   "${REPO_ROOT}"

# docker build --platform=linux/amd64 --network=none \
#   -f "${SACAI_ROOT}/docker/service-test.Dockerfile" \
#   -t sacai/tests:1.1.0-amd64 \
#   "${REPO_ROOT}"

# docker run --rm --platform=linux/amd64 \
#   sacai/tests:1.1.0-amd64

# docker run --rm --platform=linux/amd64 \
#   sacai/tests:1.1.0-amd64 \
#   sh -c 'python -m pip check && python -m pip freeze --all' \
#   > "${SACAI_ROOT}/offline/requirements-linux-amd64.lock.txt"

# (
#   cd "${SACAI_ROOT}/offline"
#   sha256sum wheelhouse/*.whl > WHEELHOUSE_SHA256SUMS
# )


# # ---------------------------------------------------------------------------
# # Optional ISIS runtime
# #
# # Set SACAI_BUILD_ISIS=1 to build the ISIS base + worker images in this run.
# # Skipped by default so ordinary connected-bundle runs stay fast, matching
# # ISIS3_OFFLINE.md's framing of ISIS as an optional container.
# # ---------------------------------------------------------------------------

# if [[ "${SACAI_BUILD_ISIS:-0}" == "1" ]]; then

#   # isis-runtime needs real internet egress (conda channels), so unlike the
#   # --network=none builds above, it goes through the same Docker Desktop
#   # connected-builder proxy as the node/python deps images.
#   docker build --platform=linux/amd64 \
#     "${PROXY_ARGS[@]}" \
#     -f "${SACAI_ROOT}/docker/isis-runtime.Dockerfile" \
#     -t sacai/isis-runtime:8.3.0-amd64 \
#     "${REPO_ROOT}"

# fi

# if docker image inspect sacai/isis-runtime:8.3.0-amd64 >/dev/null 2>&1; then
#   docker build --platform=linux/amd64 --network=none \
#     -f "${SACAI_ROOT}/docker/isis-worker.Dockerfile" \
#     -t sacai/isis-worker:8.3.0-sacai1-amd64 \
#     "${REPO_ROOT}"

#   docker save \
#     -o "${SACAI_ROOT}/offline/images/isis-runtime-amd64.tar" \
#     sacai/isis-runtime:8.3.0-amd64 \
#     sacai/isis-worker:8.3.0-sacai1-amd64
# fi
# # ---------------------------------------------------------------------------
# # Save all runtime images
# # ---------------------------------------------------------------------------

# docker save \
#   -o "${SACAI_ROOT}/offline/images/runtime-images-amd64.tar" \
#   node:22-alpine3.20 \
#   python:3.11-slim-bookworm \
#   redis:7.4.2-alpine \
#   chromadb/chroma:1.5.9 \
#   sacai/openwebui-node-deps:v0.11.3-sacalra1-amd64 \
#   sacai/openwebui-python-deps:v0.11.3-sacalra1-amd64 \
#   sacai/openwebui:v0.11.3-sacalra1-amd64 \
#   sacai/scientific-service:1.1.0-amd64 \
#   sacai/tests:1.1.0-amd64

# # ---------------------------------------------------------------------------
# # Generate final bundle checksums
# # ---------------------------------------------------------------------------

# (
#   cd "${SACAI_ROOT}/offline"
#   find . -type f ! -name SHA256SUMS -print0 \
#     | sort -z \
#     | xargs -0 sha256sum \
#     > SHA256SUMS
# )

# echo
# echo "Connected bundle preparation completed successfully."
# echo "OpenWebUI tag: sacai/openwebui:v0.11.3-sacalra1-amd64"