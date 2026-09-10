# Fully offline RHEL 9.5 deployment

The target is RHEL 9.5 on AMD64. “Offline” means DNS and outbound network are
disabled during image build, Compose start, and rebuild.

## Pre-stage on a connected AlmaLinux 9 AMD64 host

The connected builder does not need to be RHEL. AlmaLinux 9.x on x86_64 is the
supported preparation path for this delivery; see `ALMALINUX_CONNECTED_BUILDER.md`
for the Mac-to-Alma source archive, architecture checks, clean wheel resolution,
and final transfer archive. Install an organization-approved Docker Engine with
Compose v2 and enough disk for OpenWebUI, ISIS, model caches, wheels, and
catalog data. Ollama and its existing model stores are external to this bundle.
Then run:

```bash
cd sacai-platform
chmod +x scripts/*.sh
./scripts/run_on_alma_builder.sh
```

The script pre-stages:

1. OCI images: Redis 7.4.2, Chroma 1.5.9, the pinned OpenWebUI Python/Node
   dependency bases, and the locally built SAC-ALRA service images.
2. Python wheels for FastAPI, Celery/Redis, Rasterio, NumPy, SciPy,
   scikit-image, Pillow, Matplotlib, Pydantic, LangChain, LangGraph,
   `langgraph-checkpoint-sqlite`, ChromaDB, HTTPX, pytest, and every resolved
   transitive dependency in `offline/wheelhouse/`. Resolution and proof occur
   in Linux/AMD64: clean no-index image installs, `pip check`, pytest, a resolved
   version lock, and wheel checksums must all pass.
3. Node packages in the connected dependency image and OpenWebUI's Pyodide,
   sentence-transformer/NLTK caches under `offline/models/openwebui-cache/`.
4. Debian `libexpat1`, extracted under `offline/apt-cache/rootfs/` for
   network-free service image builds.
5. For optional ISIS3, the prebuilt ISIS OCI image and complete mission-specific
   `ISISDATA` tree, including base data, kernels, calibration files, and test
   fixtures. See `ISIS3_OFFLINE.md`.
6. `offline/SHA256SUMS`, which covers archives, wheels, model manifests, and
   other staged regular files.

Exact container inputs are `node:22-alpine3.20`,
`python:3.11-slim-bookworm`, `redis:7.4.2-alpine`,
`chromadb/chroma:1.5.9`, the locally built
`sacai/openwebui-node-deps:v0.11.3-sacalra1-amd64`,
`sacai/openwebui-python-deps:v0.11.3-sacalra1-amd64`,
`sacai/openwebui:v0.11.3-sacalra1-amd64`,
`sacai/scientific-service:1.1.0-amd64`, and
`sacai/tests:1.1.0-amd64`. Optional ISIS additionally needs the operator-built
`sacai/isis-runtime:8.3.0-amd64` and `sacai/isis-worker:8.3.0-sacai1-amd64`.

The connected dependency images bake, rather than download offline, Alpine's
`python3` package and Debian's `git`, `build-essential`, `pandoc`, `gcc`,
`netcat-openbsd`, `curl`, `jq`, `ca-certificates`, `libmariadb-dev`,
`python3-dev`, `ffmpeg`, `libsm6`, `libxext6`, and `zstd`. The RHEL host itself
needs an already installed and approved Docker Engine/Compose v2 stack plus the
NVIDIA Container Toolkit/driver compatible with its dual H100s; stage those RPMs
through the organization's RHEL 9.5 repository before isolation. No container
build invokes `dnf`, `apt`, `apk`, npm, PyPI, or Hugging Face after
the connected dependency/archive step.

If an enterprise internal registry is approved, push the exact image digests
there and mirror wheels/models on an internal artifact server. Otherwise copy
the entire repository and `offline/` directory using encrypted USB media. Run
the checksum verifier after copying. A partial model manifest is not a model.

## Prepare the disconnected RHEL host

```bash
cd sacai-platform
cp .env.example .env
vi .env
./scripts/verify_offline_bundle.sh
./scripts/load_offline_images.sh
docker compose config
./scripts/prepare_output_host_paths.sh
./scripts/rebuild_offline.sh
```

In `.env`, replace `WEBUI_SECRET_KEY` and `SACAI_INTERNAL_TOKEN` with independent
random values; the latter must be at least 16 characters. Set
`OLLAMA_BASE_URL` to the existing Ollama API and point optional
`ISISDATA_HOST_PATH` at the transferred data. Do not expose Redis, Chroma, or
the SAC-ALRA API ports outside the Compose network.
Keep OpenWebUI's storage provider on the local shared `openwebui-data` volume;
S3/GCS providers require a separately designed offline object-store handoff and
are not silently treated as local worker paths.

If a vLLM instance (or any other OpenAI-compatible server) is already running
on this host, set `ENABLE_OPENAI_API=true` and `OPENAI_API_BASE_URLS` to its
`.../v1` URL alongside the existing `OLLAMA_BASE_URL`; both connections are
available in OpenWebUI at once. `OPENAI_API_KEYS` accepts vLLM's own `EMPTY`
placeholder when the server was started without `--api-key`. Leave
`ENABLE_OPENAI_API=false` on a host with no OpenAI-compatible server, since an
empty `OPENAI_API_BASE_URLS` otherwise falls back to the public OpenAI API,
which this offline host cannot reach.

`SACAI_OUTPUT_HOST_PATH`, `SACAI_AUDIT_HOST_PATH`, and
`SACAI_TOOL_VERSIONS_HOST_PATH` are plain host directories (default
`./offline/data/{outputs,audit,tool_versions}`), not Docker named volumes, so
an operator can inspect or back up scientific outputs, the audit trail, and
installed tool versions directly. `prepare_output_host_paths.sh` creates them
and confirms they are writable; `migrate_named_volumes_to_bind_mounts.sh`
copies over any data left in the old `sacai-outputs`/`sacai-audit`/
`sacai-tool-versions` named volumes from a release before this change.

`rebuild_offline.sh` sets BuildKit networking to `none`, uses `--pull=false`,
and starts with `--pull never`. If Docker reports a missing image/wheel/cache,
stop: return to the connected staging host and add the missing artifact. Do not
temporarily connect production to the internet.

Before rebuilding onto a new OpenWebUI version on a host that already has real
data (not a first-time install), run `./scripts/backup_openwebui_data.sh` —
the rebuild runs OpenWebUI's own database migrations against the existing
`openwebui-data` volume in one step, and that step is not reversible.

## Rebuild after a code-only change, still offline

```bash
cd sacai-platform
python3 -m compileall -q service openwebui_tools openwebui_functions branding isis
./scripts/rebuild_offline.sh
docker compose ps
docker compose logs --tail=100 sacai-api planetir-worker notebook-worker openwebui
```

Python dependencies are installed only from `/wheelhouse`; frontend dependencies
come only from the prebuilt Node image. A dependency, model, OS-package, or ISIS
data change is not a code-only rebuild and requires a new connected bundle.

## Change the project name after an image was built

The final project name does not need to be decided before preparing the offline
bundle. The current selected value is `SAC-ALRA`, and it can be replaced later.

The name is used in two places: runtime backend configuration and frontend assets
created during the image build. Changing `.env` and restarting containers updates
only the runtime value; page titles, splash content, PWA metadata, and the logo's
accessible title would still contain the name from the previous build. A complete
rename therefore requires rebuilding the OpenWebUI image.

On the offline host, edit the existing environment file:

```bash
cd sacai-platform
vi .env
```

Set the chosen name without changing the variable name:

```dotenv
PROJECT_NAME=YourChosenName
```

Save the file and run the normal disconnected rebuild:

```bash
./scripts/rebuild_offline.sh
```

This rebuild uses the already staged Node/Python dependency images and makes no
network calls. After it finishes, open the site in a private browser window and
check the pre-login title, splash screen, favicon, signed-in interface, and PWA
name. A container restart by itself is not sufficient for a complete rebrand.

## Acceptance gates

- Build and run the disconnected test image:
  `docker build --network=none -f docker/service-test.Dockerfile -t sacai/tests:1.1.0 ..`
  followed by `docker run --rm sacai/tests:1.1.0`.
- Upload the reference GeoTIFF, submit PlanetIR, poll to success, and confirm
  preview/report files appear in OpenWebUI Files and download successfully.
- Disconnect all egress, rebuild again, and repeat the smoke test.
- With `--profile isis`, process one reference product for every enabled mission
  and compare metadata/radiometry with the connected acceptance result.
- Record exact image digests, checksums, test output, and prompt/model versions
  as a new append-only `BUILD_LOG.md` entry.
