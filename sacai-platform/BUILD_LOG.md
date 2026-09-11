# SACAI build log

This file is append-only. Add a dated entry for every build, configuration, or
prompt change; never rewrite an older entry.

## 2026-07-22 — initial source-derived implementation

Purpose: map OpenWebUI v0.10.2 before implementation and create the SACAI overlay.

Commands run, in order (read-only probes are included so the investigation can
be reconstructed):

```text
rg --files source-code/open-webui
rg -n "class Tools|__files__|upload_file_handler|UPLOAD_DIR|WEBUI_NAME|Open WebUI" source-code/open-webui
sed -n '<selected ranges>' source-code/open-webui/backend/open_webui/{utils,routers,models}/*.py
sed -n '<selected ranges>' source-code/open-webui/src/**/*.svelte
find source-code -maxdepth 3 -type f
git -C source-code/open-webui rev-parse HEAD
python3 -m compileall -q sacai-platform
python3 -m pytest -q sacai-platform/service/tests
python3 - <<'PY'  # import availability probe for runtime/test dependencies
PY
```

Results:

- Source baseline recorded as `ecd48e2f718220a6400ecf49eafd4867a38feb10`.
- `compileall` passed.
- The host Python has none of the project dependencies and no `pytest`, so the
  test command stopped with `No module named pytest`. This is an environment
  limitation, not a passing test result; the offline wheel image and container
  test gate remain required before release.
- No command modified the vendor OpenWebUI checkout.

## 2026-07-22 — implementation hardening and static acceptance

Purpose: close publication, cleanup, branding, workflow, offline-transfer, and
scientific-output safety gaps found during review.

Commands run:

```text
chmod +x sacai-platform/scripts/*.sh
bash -n sacai-platform/scripts/*.sh
python3 -m compileall -q sacai-platform
python3 <inline AST check of every openwebui_tools/ Tools class>
PROJECT_NAME=SACAI WEBUI_SECRET_KEY=test-secret SACAI_INTERNAL_TOKEN=test-token-at-least-16 docker compose -f sacai-platform/docker-compose.yml config --quiet
SACAI_BRAND_TEST_DIR="$(mktemp -d)"; cp -R source-code/open-webui/src source-code/open-webui/static source-code/open-webui/backend "$SACAI_BRAND_TEST_DIR/open-webui/"; python3 sacai-platform/branding/apply_branding.py "$SACAI_BRAND_TEST_DIR/open-webui" --project-name TESTPROJECT --logo sacai-platform/branding/sacai-logo.svg
rg -n "Open WebUI|OpenWebUI|SACAI" "$SACAI_BRAND_TEST_DIR/open-webui/src" "$SACAI_BRAND_TEST_DIR/open-webui/static" "$SACAI_BRAND_TEST_DIR/open-webui/backend/open_webui/static"
find /Users/hiya_38/ISRO_SAC/sacai/sacai-platform -type d -name __pycache__ -prune -exec rm -rf '{}' +
```

Results:

- Shell syntax, Python byte compilation, exact one-public-method Tool surfaces,
  and Compose configuration passed.
- The first branding smoke test found an unhandled `.webmanifest` suffix. The
  overlay was fixed and the repeated disposable test found no upstream/project
  placeholder brand in frontend/static assets; runtime manifest icons point to
  the installed project SVG.
- Docker daemon access is unavailable in this workspace, and the host Python has
  no project dependencies. Full pytest/image-build/integration results therefore
  remain a connected-bundle and disconnected-host release gate; no passing
  claim is made for those tests here.

## 2026-07-22 — final dependency-free verification

Commands run:

```text
python3 <inline AST parse requiring syntax and docstrings for every project Python class/function, plus JSONL decode>
bash -n sacai-platform/scripts/*.sh
PROJECT_NAME=SACAI WEBUI_SECRET_KEY=test-secret SACAI_INTERNAL_TOKEN=test-token-at-least-16 docker compose -f sacai-platform/docker-compose.yml config --quiet
test -z "$(find sacai-platform -type d -name __pycache__ -print -quit)"
```

All four dependency-free checks passed. The dependency-bearing test/image gates
remain explicitly pending for the connected AMD64 bundle builder.

## 2026-07-22 — post-build project-name guidance

Documentation-only change: added exact offline steps to
`docs/OFFLINE_DEPLOYMENT.md` explaining that `PROJECT_NAME` can be chosen after
the initial build, but a full frontend rebrand requires
`./scripts/rebuild_offline.sh`; restarting containers alone is insufficient.

## 2026-07-22 — Mac-to-AlmaLinux source transfer and wheel proof

Added a macOS source packager, AlmaLinux 9 AMD64 builder entry point, final RHEL
transfer packager, and connected-builder guide. Source/final packagers reject
Git repositories, `.github` directories, Git metadata files, and cache files.
The Linux wheelhouse is cleared before resolution and is accepted only after
clean `--no-index` installs, `pip check`, pytest, a resolved-version lock, and
wheel/full-tree SHA-256 manifests.

Commands run:

```text
uname -m
du -sh source-code/open-webui source-code/pystac-client sacai-platform
find source-code -maxdepth 3 \( -name .git -o -name .github -o -name '.git*' \) -print
chmod +x sacai-platform/scripts/*.sh
bash -n sacai-platform/scripts/*.sh
./sacai-platform/scripts/create_alma_source_bundle_macos.sh
cd sacai-platform/dist && shasum -a 256 -c sacai-alma-builder-source.tar.gz.sha256
tar -tzf sacai-alma-builder-source.tar.gz
SACAI_VERIFY_DIR="$(mktemp -d)"; tar -xzf sacai-platform/dist/sacai-alma-builder-source.tar.gz -C "$SACAI_VERIFY_DIR"
cd "$SACAI_VERIFY_DIR/sacai-alma-builder"; shasum -a 256 -c SOURCE_MANIFEST.sha256
```

The first packaging attempt correctly failed because tracked `.gitkeep`
placeholders matched the no-Git-metadata gate. The packager was tightened to
exclude all `.git*` files while preserving empty directories, then rerun. The
final archive checksum, archive-content check, extracted source manifest, and
executable-script checks passed. Generated output:
`dist/sacai-alma-builder-source.tar.gz` (approximately 55 MiB) plus its SHA-256
file. Linux wheels and OCI/model artifacts are intentionally generated and
validated on the connected AlmaLinux AMD64 host, not on this ARM64 Mac.

## 2026-07-22 — ordered operator handoff

Documentation-only change: created the extensionless `next_step` file with one
ordered beginner-level checklist covering source transfer, AlmaLinux validation,
Linux/AMD64 wheel proof, final archive creation, offline RHEL extraction,
configuration, no-network rebuild, Tool/Filter/prompt installation, multi-user
acceptance testing, and deployment evidence.

## 2026-07-29 — SAC-ALRA dual-host and external-Ollama correction

Selected the frontend name `SAC-ALRA`. Added host templates for web endpoints
`10.61.247.253:2018` and `10.61.247.254:3000`, with each deployment using its
existing external Ollama API and model store. Removed the Compose Ollama service,
Ollama image/model staging, and stale Ollama bundle verification.

Added the connected-builder proxy path, no-script Node install, larger frontend
build heap, a complete Linux/AMD64 wheel pin for PyWavelets, and offline
`libexpat1` extraction/copy. Chroma now uses its `/data` persistence mount and
v2 heartbeat; OpenWebUI waits for Chroma health and has a startup grace period.
Added `scripts/diagnose_chroma.sh` and replaced `next_step` with the ordered
rebuild, transfer, two-host configuration, Chroma diagnosis, and acceptance
procedure. Runtime image and source transfer archives continue to exclude
Git/GitHub metadata.

Mac-side validation commands:

```text
bash -n sacai-platform/scripts/*.sh
docker compose --env-file sacai-platform/.env.server-253.example -f sacai-platform/docker-compose.yml config --quiet
docker compose --env-file sacai-platform/.env.server-254.example -f sacai-platform/docker-compose.yml config --quiet
./sacai-platform/scripts/create_alma_source_bundle_macos.sh
cd sacai-platform/dist && shasum -a 256 -c sacai-alma-builder-source.tar.gz.sha256
tar -xzf sacai-alma-builder-source.tar.gz -C <temporary-directory>
cd <temporary-directory>/sacai-alma-builder && shasum -a 256 -c SOURCE_MANIFEST.sha256
```

Shell syntax, both host-specific Compose configurations, the outer archive
checksum, and the extracted source manifest passed. Archive inspection found no
Git/GitHub metadata or Ollama model directory. The Linux wheel resolution,
image builds, Chroma runtime probe, and full pytest suite remain required on the
connected AlmaLinux builder and offline RHEL hosts; they were not claimed as
passing on this Mac.

## 2026-07-31 — remove builder proxy from OpenWebUI runtime

Production diagnosis found lowercase `http_proxy` and `https_proxy` inherited
from an older connected-builder dependency image. Chroma HTTP calls were routed
to the AlmaLinux-only proxy and failed on RHEL.

Proxy values are now build arguments only and are not stored as dependency-image
`ENV` metadata. The final OpenWebUI stage and Compose service explicitly clear
uppercase and lowercase HTTP/HTTPS/no-proxy variables. The permanent runtime
and dependency images use new `sacalra2` tags so an image loaded from the older
archive cannot satisfy the corrected tag accidentally. Connected preparation
and offline rebuilding now fail on any non-empty runtime proxy variable; the
offline rebuild also compares the running container image ID with the expected
new image ID and force-recreates the service. The Chroma diagnostic prints all
six values and performs both a proxy-disabled direct heartbeat and a Chroma
client heartbeat.

Mac-side checks run after the correction:

```text
bash -n sacai-platform/scripts/*.sh
docker compose --env-file sacai-platform/.env.server-253.example -f sacai-platform/docker-compose.yml config --quiet
docker compose --env-file sacai-platform/.env.server-254.example -f sacai-platform/docker-compose.yml config --quiet
./sacai-platform/scripts/create_alma_source_bundle_macos.sh
shasum -a 256 -c sacai-platform/dist/sacai-alma-builder-source.tar.gz.sha256
tar -xzf <archive> -C <temporary-directory>
shasum -a 256 -c <temporary-directory>/sacai-alma-builder/SOURCE_MANIFEST.sha256
```

Both Compose configurations, all shell syntax, the outer checksum, and the
extracted source manifest passed. The corrected Linux image itself must still
be built and pass the new proxy gate on the connected AlmaLinux AMD64 builder.

The operator guide was clarified after review: the
`http://http.docker.internal:3128` value is builder-only. Its presence in the
guide and connected preparation script is expected; any non-empty occurrence
inside the production OpenWebUI process is a deployment failure.

## 2026-08-04 — Tool Save version guard and logo asset correction

The Tool editor formatted code successfully but crashed before its create/update
request. Source tracing identified `src/lib/utils/index.ts:compareVersion`, where
the compile-time `WEBUI_VERSION` was undefined because the Dockerfile invoked
Vite directly without npm's `npm_package_version`; this was not a tool-list sort
or evidence of a null database row. The frontend build now exports and checks
OpenWebUI `0.10.2`, and the disposable overlay makes both the constant and
comparison null-safe.

The logo overlay previously placed the SVG at the frontend static root while
the application requested `/static/sacai-logo.svg`. OpenWebUI startup clears its
backend static directory and restores it from `build/static`, deleting the logo.
The overlay now emits the SVG into that exact build directory and verifies it
before Vite completes. A dedicated overlay verifier fails the build if either
version guard or either required logo source is missing. The corrected frontend
uses the new `sacalra3` tag so a previously transferred JavaScript bundle cannot
silently satisfy the image reference.

Mac-side checks run:

```text
python3 branding/apply_branding.py <temporary-openwebui-copy> --project-name SAC-ALRA --openwebui-version 0.10.2 --logo branding/sacai-logo.svg
python3 branding/verify_branding_overlay.py <temporary-openwebui-copy> --expected-version 0.10.2
python3 -m py_compile branding/apply_branding.py branding/verify_branding_overlay.py
bash -n scripts/*.sh
docker compose --env-file .env.server-253.example -f docker-compose.yml config --quiet
docker compose --env-file .env.server-254.example -f docker-compose.yml config --quiet
```

The disposable overlay, null-safe version guard, both logo paths, Python syntax,
shell syntax, and both host Compose configurations passed. Vite compilation and
the browser/API acceptance test remain gates for the connected AlmaLinux build
and offline RHEL deployment.

## 2026-08-06 — connected-builder proxy and retry correction

The connected Docker Desktop builder failed Alpine `apk`, Debian/ML downloads,
and finally Docker Hub with DNS, permission, and TLS handshake errors. The
project had overridden Docker Desktop's internal `http.docker.internal` name
with `host-gateway`, potentially sending proxy traffic to the wrong address;
that override was removed. Preparation now proves Alpine repository access from
a temporary proxied container before building dependencies, retries registry
pulls and bounded network downloads, increases TLS/download timeouts, and
returns apt-cache ownership to the invoking AlmaLinux UID/GID.

The operator guide now separates Docker Desktop/Containers proxy configuration
(required for `docker pull`) from build arguments (used by apk, apt, npm, pip,
and model-cache containers). It explicitly reverses an empty
`SACAI_BUILD_PROXY_URL` on this proxy-required network by instructing operators
to unset the variable.

Mac-side static checks run:

```text
bash -n sacai-platform/scripts/*.sh
python3 -m py_compile sacai-platform/branding/*.py
docker compose --env-file sacai-platform/.env.server-253.example -f sacai-platform/docker-compose.yml config --quiet
docker compose --env-file sacai-platform/.env.server-254.example -f sacai-platform/docker-compose.yml config --quiet
rg -- '--add-host=http.docker.internal:host-gateway' sacai-platform
```

Shell/Python syntax and both Compose configurations passed; the forbidden DNS
override search returned no matches. Live proxy, registry, apk, apt, pip, model,
and image-build checks must run on the connected AlmaLinux Docker Desktop host.

Final archive inspection found the local backup directory `dist_old` containing
an earlier archive. The source packager now excludes both `dist` and `dist_old`
trees, preventing recursive shipment while preserving the user's local backup.

## 2026-08-06 — schema-backed STAC field-value queries

The single `stac_catalog` Tool now supports exact product/item-ID lists, bare
year intervals, collection ID/title/acronym matching, and unique sensor/mission
values observed from live catalog summaries or sampled items. Requested fields
are projected per product without recomputation; sparse fields, unknown product
IDs, unsupported fields, and cap-limited results are reported explicitly.
STAC `next` links are followed up to the configured safety cap.

Regression cases cover sun-incidence values for named product IDs, a 2020 TMC
collection, TMC as an observed metadata value, a missing value, and multi-page
results. A capped response also keeps unfetched IDs separate from IDs proven
absent. Python compilation passed. The six focused tests passed through a
fixture-compatible direct runner because pytest is not installed in the Mac
base environment; the offline service-test image remains the authoritative
full pytest gate.

## 2026-08-06 — allowlisted remote Jupyter execution

Added one `jupyter_runtime` Tool with admin Valves for a standard Jupyter Server
URL/token, TLS policy, kernelspec, resource bounds, and friendly-name-to-notebook
allowlist. Submit accepts only a code name and product ID. A dedicated
`notebook_remote` Celery worker executes fetched code cells over Jupyter kernel
WebSockets, captures bounded text/JSON/PNG outputs, closes the remote session,
and publishes hashed result artifacts through OpenWebUI Files. Cooperative
cancellation avoids killing the worker before it can close the remote session.

The service dependency set now pins `websocket-client==1.9.0`; connected bundle
preparation will download it and all dependencies into the offline wheelhouse
before the no-index image build. Python compilation, both server Compose
configurations, Tool allowlist/submission mapping, parent-scoped kernel-message
capture, and the one-public-method surface check passed on the Mac using local
dependency stubs where the base environment lacks the staged Linux packages.
A real runtime URL/token was not supplied, so
the live REST, WebSocket, kernelspec, notebook, and cancellation acceptance
tests remain deployment gates rather than claimed results.

## 2026-09-10 — OpenWebUI v0.11.3 upgrade, vLLM connection, bind-mounted outputs

Purpose: production is running OpenWebUI v0.11.3 while this platform's audited
baseline was v0.10.2; add a vLLM (OpenAI-compatible) connection alongside the
existing external Ollama connection; move scientific outputs, the audit
trail, and installed tool versions from Docker named volumes to bind-mounted
host directories so an operator can inspect/back them up without Docker
tooling.

Source upgrade: `source-code/open-webui` replaced in full with the upstream
`v0.11.3` tag (commit `2a960a59fe1dbbd35282f0556b3666d81102e781`), shallow-cloned
from `https://github.com/open-webui/open-webui.git` and copied over the
checked-in `v0.10.2` tree (`ecd48e2f718220a6400ecf49eafd4867a38feb10`). Every
claim in `ARCHITECTURE_DECISIONS.md` §1 and §8 was re-verified against the new
source by direct `diff -u` (not re-derived from memory or assumed unchanged);
findings are recorded in a new §12 and as inline `[v0.11.3: ...]` notes.
Summary of what actually changed: the five separate request middlewares were
replaced by one consolidated `AppHTTPMiddleware`; Filters gained an optional
`request` hook additive to `inlet`/`stream`/`outlet`; file uploads gained two
optional behaviors on an unchanged publication path; `backend/requirements.txt`
drops `python-jose` for `joserfc` and renames `rapidocr-onnxruntime` to
`rapidocr`; the branding overlay's patch targets (`env.py` WEBUI_NAME/favicon,
`compareVersion()`, `main.py` logo reference, `site.webmanifest`) are all
byte-for-byte unchanged, so `branding/apply_branding.py` and
`branding/verify_branding_overlay.py` needed no code changes; and OpenWebUI
introduced an unrelated new "Open Terminal" feature
(`TERMINAL_SERVER_CONNECTIONS`, default empty) providing real server-side
command execution, which is explicitly left unconfigured and undocumented as
an integration point, for the same reason Stage 13 does not implement a shell
Tool — it is not the browser-side Pyodide Code Interpreter this platform
already relies on, which is unchanged. `grep` across `service/`,
`openwebui_tools/`, `openwebui_functions/`, `branding/`, and `docker/` found no
references to the removed/renamed Python packages or to the old middleware
class names. Ten new Alembic migrations exist between the two versions; a new
`scripts/backup_openwebui_data.sh` backs up the `openwebui-data` volume before
a rebuild runs them, and `next_step`/`OFFLINE_DEPLOYMENT.md` now call for that
backup on any host with real existing data. All `v0.10.2`/`sacalra3` version
and image-tag strings across `docker-compose.yml`, `docker/openwebui.Dockerfile`,
`scripts/*.sh`, `branding/apply_branding.py`, and `docs/*.md` were updated to
`v0.11.3`/`sacalra1` (a fresh overlay-revision counter on the new base); one
pre-existing drift in `docs/OFFLINE_DEPLOYMENT.md` (`sacalra2` for the
dependency-image tags, where every build script already used `sacalra3`) was
also corrected to `sacalra1` while there.

vLLM connection: OpenWebUI's existing `ENABLE_OPENAI_API` /
`OPENAI_API_BASE_URLS` / `OPENAI_API_KEYS` env vars (unchanged in v0.11.3,
confirmed in `config.py`) are wired into the `openwebui` Compose service
alongside the existing `OLLAMA_BASE_URL`/`OLLAMA_BASE_URLS`, following the
same "external service, not a Compose service" pattern Ollama already uses.
`ENABLE_OPENAI_API` defaults to `false` so a host with no OpenAI-compatible
server does not silently fall back to the public OpenAI API. `.env.example`
and `.env.server-253.example` document it commented-out;
`.env.server-254.example` sets it concretely to the vLLM instance at
`10.61.247.254:8004/v1` with the `EMPTY` placeholder key vLLM itself expects
when started without `--api-key`.

Bind-mounted outputs: `sacai-outputs`, `sacai-audit`, and
`sacai-tool-versions` named volumes are replaced with bind mounts to
`SACAI_OUTPUT_HOST_PATH` / `SACAI_AUDIT_HOST_PATH` /
`SACAI_TOOL_VERSIONS_HOST_PATH` (default `./offline/data/{outputs,audit,
tool_versions}`, already covered by the existing `sacai-platform/offline/`
`.gitignore` entry) across every service that mounts them (`openwebui`,
`sacai-api`, `planetir-worker`, `isis-worker`, `notebook-worker`). Container-side
paths (`/data/outputs`, `/data/audit`, `/data/tool_versions`) are unchanged, so
no service code needed changes. New `scripts/prepare_output_host_paths.sh`
creates and validates the host directories (called from `rebuild_offline.sh`
and documented in the deployment guides); new
`scripts/migrate_named_volumes_to_bind_mounts.sh` copies forward any data left
in the old named volumes from a prior release, using the already-loaded
`sacai-api` image rather than pulling an `alpine` image an offline host would
not have.

Checks run on this Mac-equivalent environment:

```text
python3 -m compileall -q sacai-platform/service sacai-platform/openwebui_tools \
  sacai-platform/openwebui_functions sacai-platform/branding sacai-platform/isis
python3 -m compileall -q source-code/open-webui/backend/open_webui
bash -n sacai-platform/scripts/*.sh
grep -rn "import jose\|rapidocr\|rosepine\|RedirectMiddleware\|SecurityHeadersMiddleware\|CommitSessionMiddleware\|AuthTokenMiddleware\|WebsocketUpgradeGuardMiddleware\|XTerminal\|AddTerminalServerModal" \
  sacai-platform/service sacai-platform/openwebui_tools sacai-platform/openwebui_functions \
  sacai-platform/branding sacai-platform/docker
docker compose --env-file sacai-platform/.env.example -f sacai-platform/docker-compose.yml config --quiet
docker compose --env-file sacai-platform/.env.server-253.example -f sacai-platform/docker-compose.yml config --quiet
docker compose --env-file sacai-platform/.env.server-254.example -f sacai-platform/docker-compose.yml config --quiet
```

All commands passed; the grep for removed/renamed dependencies and rejected
frontend components returned no matches in this overlay's own code, and all
three Compose configurations resolved the new OpenAI/vLLM variables and
bind-mounted output paths correctly. `run_on_alma_builder.sh`'s live wheel
resolution against the new `requirements.txt`, the disconnected rebuild gate,
and a real vLLM `/v1/models` reachability check from inside the OpenWebUI
container remain required on the actual connected AlmaLinux builder and
offline RHEL hosts; none of those were claimed as passing here.

## 2026-09-10 — Lunar DEM pipeline: ISIS -> ASP -> OTB, wired mission-agnostic

Purpose: the platform's stated main goal is autonomous lunar DEM generation.
`docker/asp-runtime.Dockerfile` and `docker/ch2-runtime.Dockerfile` already
existed in the repo (built and loaded on the operator's host, per
`docker images` output: `sacai/asp-runtime:3.5.0-amd64`,
`sacai/ch2-runtime:10.0.0rc2-amd64`) but were not referenced anywhere else --
no Compose service, no queue, no Tool, no ARCHITECTURE_DECISIONS entry. "OTV"
in the requested "ISIS ASP OTV" pipeline was clarified to mean Orfeo ToolBox
(OTB, CNES). The operator explicitly wants DEM generation "not specific to a
mission or sensor" -- the design below keeps the generic ISIS 8.3.0 path
(`isis-worker`) as the default for every mission, with the ISIS 10 RC2
Chandrayaan-2 TMC-2 variant (`ch2-worker`) opt-in per job via
`options.mission == "ch2_tmc2"`, never a default.

New generic, mission-agnostic stage wrappers, matching `isis/isis_preprocess.py`'s
existing contract exactly (operator-configured command templates, no
hardcoded tool flags or session type): `dem/asp_stereo.py` (optional bundle
adjustment -> stereo correlation -> `point2dem`, `{left}`/`{right}`/`{prefix}`/
`{output}` placeholders) and `dem/otb_postprocess.py` (one OTB stage,
`{input}`/`{dem}`/`{output}` placeholders).

Service layer, mirroring `isis.py`'s existing single-input pattern extended to
two inputs: `service/app/dem.py:generate_dem()` and
`service/app/otb.py:orthorectify()`. `schemas.py`'s `JobSubmit`/`JobStatus`
gained `lunar_dem`/`orthorectify` kinds and a validated
`secondary_input_file_id`/`secondary_input_path`/`secondary_original_name`
triple (the right stereo image, or the DEM to orthorectify against) -- a real
field rather than living inside the free-form `options` mapping, so `api.py`
applies the same `resolve_below()` boundary check to it that `input_path`
already gets. New `asp_cpu`/`otb_cpu`/`ch2_cpu` Celery queues in
`config.py`/`celery_app.py`; new `tasks.py:_run_paired_job()` (mirrors
`_run_job()`, requires `secondary_input_path`) backing `sacai.lunar_dem`/
`sacai.orthorectify`; `api.py`'s `submit_job()` validates and resolves the
secondary path the same way as the primary one before dispatch, and routes
`isis3` jobs to `ch2_cpu` only when `options.mission == "ch2_tmc2"`.

New Tool `openwebui_tools/lunar_dem.py` (`lunar_dem_pipeline`, actions
`submit_dem`/`submit_orthorectify`/`status`/`cancel`). Written to match
`openwebui_tools/isis3_preprocess.py` -- the async, `urllib`-based,
direct-`upload_file_handler`-publication pattern that
`service/tests/test_tool_surfaces.py` and `next_step` step 19 both actually
reference -- not `isis3_preprocess_tool.py`'s earlier `requests`-based draft,
which this session found is not referenced by anything and is flagged in
ARCHITECTURE_DECISIONS.md §13 as likely dead.

Docker: `docker/asp-worker.Dockerfile` and `docker/ch2-worker.Dockerfile`
layer the SACAI service/Celery code onto the already-built `asp-runtime`/
`ch2-runtime` images, exactly mirroring `isis-worker.Dockerfile`'s existing
pattern. `docker/otb-runtime.Dockerfile` (new, not yet built by the operator)
and `docker/otb-worker.Dockerfile` follow the same conda-based pattern as
`asp-runtime.Dockerfile`; unlike ASP/CH2, OTB's conda environment's Python
version has no existing proof of wheelhouse compatibility, flagged explicitly
in both the Dockerfile and ARCHITECTURE_DECISIONS.md §13.
`docker-compose.yml`: `asp-worker`/`otb-worker` default-enabled (core to the
stated goal, like `planetir-worker`); `ch2-worker` opt-in via
`profiles: ["ch2"]` (like `isis-worker`'s existing `profiles: ["isis"]`).
New `.env` variables for ASP/OTB/CH2 concurrency, resource limits, command
templates, and `ISISDATA_CH2_HOST_PATH`, added to `.env.example` and both
`.env.server-*.example` files identically (these are queue/resource defaults,
not host-specific).

Checks run, this time in an isolated venv against the real
`service/requirements.txt` and `service/test-requirements.txt` (a step up
from prior entries' "no pytest in the base environment" limitation -- a clean
`python3 -m venv` avoided the system Python's unrelated dependency
conflicts):

```text
python3 -m venv /tmp/sacai_venv && /tmp/sacai_venv/bin/pip install -r service/requirements.txt -r service/test-requirements.txt
python3 -m compileall -q service openwebui_tools dem isis branding
PYTHONPATH=service /tmp/sacai_venv/bin/python -m pytest -q service/tests
docker compose --env-file .env.example -f docker-compose.yml config --quiet
docker compose --env-file .env.example -f docker-compose.yml config --services
COMPOSE_PROFILES=isis,ch2 docker compose --env-file .env.example -f docker-compose.yml config --quiet
# repeated for .env.server-253.example and .env.server-254.example
```

All 25 tests passed (20 pre-existing plus 5 new `test_dem_pipeline.py` cases
covering the new schema fields, the paired-task secondary-input guard, and
queue isolation). All three `.env` files produced valid Compose configs, both
by default (`asp-worker`/`otb-worker` present, `ch2-worker`/`isis-worker`
absent) and with `COMPOSE_PROFILES=isis,ch2` (all six worker services
present, `ch2-worker` mounting a separate `ISISDATA_CH2_HOST_PATH`). Real
end-to-end DEM generation against actual ASP/OTB binaries, the `otb-runtime`
build itself, and tuning the empty `ASP_*`/`OTB_*`/`CH2_ISIS_*_COMMAND`
templates for a specific sensor remain deployment work on the connected
builder and production hosts; none of that was claimed as passing here.

## 2026-09-11 — openwebui-canary service; connected-builder image drift fixes

Purpose: the operator reported production 254 image state, which surfaced
real gaps between what this repo's scripts produce and what is actually
running.

Added `openwebui-canary`, a second OpenWebUI frontend (own port via
`SACAI_CANARY_WEB_PORT`, own `openwebui-canary-data` volume -- two instances
must never share one OpenWebUI database) sharing the existing
`sacai-api`/`redis`/`chroma` backend, gated behind `profiles: ["canary"]` so
neither a bare `docker compose up` nor a targeted `up -d --no-deps
openwebui-canary` ever touches the operator's existing production `openwebui`
container.

Fixed two real, pre-existing bugs found by comparing `docker image ls` on 254
against what this repo expects:

- `scripts/prepare_connected_bundle.sh` built and tagged
  `sacai/scientific-service`/`sacai/tests` as `1.0.0`, while
  `docker-compose.yml` and both deployment docs have always expected `1.1.0`.
  This explains the `1.0.0` image sitting unused on 254 (harmless in
  practice, since `sacai-api`/`planetir-worker`/`notebook-worker` all carry
  their own `build:` block and rebuild fresh under the correct tag
  regardless) but is still a real drift, now fixed to `1.1.0` throughout.
- `scripts/prepare_connected_bundle.sh` never learned about ASP or CH2 at
  all -- the operator had built `asp-runtime`/`ch2-runtime` and their worker
  images by hand, outside any tracked script. Added `SACAI_BUILD_ASP`
  (defaults to `1`: asp-worker is a default-enabled Compose service, unlike
  the truly-optional ISIS/CH2 containers, so it now builds by default rather
  than requiring an explicit opt-in) and `SACAI_BUILD_CH2` (defaults to `0`,
  mission-specific, mirrors `SACAI_BUILD_ISIS`) gated sections, each
  mirroring the existing ISIS section's build-then-conditionally-build-
  worker-then-save-to-its-own-tar pattern exactly. `load_offline_images.sh`
  now loads `asp-runtime-amd64.tar` unconditionally (asp-worker has no
  `build:` fallback path once its base image is missing, so a missing tar
  should fail loudly at load time, not with a confusing error later) and
  conditionally loads `ch2-runtime-amd64.tar`/`otb-runtime-amd64.tar`.

`otb-worker` was changed from default-enabled to `profiles: ["otb"]`: the
operator's existing `otb:otb` image's build method and therefore its
Python-ABI compatibility with the offline wheelhouse are still unconfirmed
(unlike `asp-runtime`/`ch2-runtime`, which both install ISIS 8.3.0 alongside
them and inherit `isis-runtime`'s already-proven compatibility). Left
un-added to `prepare_connected_bundle.sh` for the same reason -- adding a
`SACAI_BUILD_OTB` gate before confirming the real base image/build method
would template a build that might not match what actually runs.

Checks run:

```text
bash -n scripts/prepare_connected_bundle.sh scripts/load_offline_images.sh
python3 -c "import yaml; yaml.safe_load(open('docker-compose.yml'))"
docker compose --env-file .env.example -f docker-compose.yml config --services
COMPOSE_PROFILES=otb docker compose --env-file .env.example -f docker-compose.yml config --services
COMPOSE_PROFILES=canary docker compose --env-file .env.server-254.example -f docker-compose.yml config --quiet
COMPOSE_PROFILES=isis,ch2,canary docker compose --env-file .env.example -f docker-compose.yml config --quiet
# repeated for .env.server-253.example and .env.server-254.example
```

All passed. `otb-worker`'s absence from the default service list and
presence under `COMPOSE_PROFILES=otb` were confirmed directly, as was
`openwebui-canary` publishing port 3006 while the primary `openwebui`
service keeps its own configured port. Still unconfirmed here (needs the
operator's answer, then a real connected-builder run):
`otb:otb`'s actual build method; whether/how `sacai-super-res:latest` and
`ghcr.io/openwebui/pipelines:main` (both present on 254, neither referenced
anywhere in this repo) should be wired in.


