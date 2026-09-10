# SAC-ALRA Architecture Decisions

Status: accepted for implementation  
Source baseline: OpenWebUI `v0.10.2`, commit `ecd48e2f718220a6400ecf49eafd4867a38feb10`

## 1. Source findings

This file was written before implementation code. The decisions below come from reading the checked-in OpenWebUI backend and frontend, not from assumptions about another release.

### Backend map

- `backend/open_webui/main.py` creates the FastAPI application, installs authentication, security, session-commit and audit middleware, and mounts the API routers. Chat preparation and completion processing live mainly in `backend/open_webui/utils/middleware.py`.
- Local Tools are Python source stored in the `tool` table. `utils/plugin.py` executes that source, instantiates its `Tools` class, and `utils/tools.py:get_tools()` exposes every public callable discovered on the instance. Reserved parameters beginning with `__` are removed from the model-visible schema and injected by OpenWebUI.
- Functions are Python source stored in the `function` table. They instantiate `Pipe`, `Filter`, `Action`, or `Event`. Filters run through `inlet`, `stream`, and `outlet` hooks in `utils/filter.py`; Pipes appear as models and implement their own chat request/response path.
- “Pipelines” in this release are not an internal job system. `routers/pipelines.py` proxies admin operations and inlet/outlet calls to a separately deployed OpenAI-compatible Pipelines server.
- Uploaded file bytes go through `routers/files.py:upload_file_handler()` to `Storage.upload_file()`. A `FileForm` row is then inserted into the `file` table. The local provider writes to `UPLOAD_DIR`, which is `DATA_DIR/uploads` (normally `/app/backend/data/uploads`), not an arbitrary `/mnt/uploads` directory.
- The chat frontend sends file descriptors shaped like `{type: "file"|"image", id, url: id, name, content_type, size, ...}`. Chat middleware places this list in `metadata.files`; `utils/tools.py` injects it as `__files__`. A Tool must resolve `entry.id` with `Files.get_file_by_id()` and then resolve the stored path with `Storage.get_file()` after checking ownership/access. A UUID-prefixed stored filename is an implementation detail and is never an LLM argument.
- Downloadability and the user Files browser require both storage bytes and a `file` table row. Merely writing below a mounted directory is insufficient. Downloads use `/api/v1/files/{id}/content` and enforce owner/admin/access-grant checks.
- Knowledge bases use the `knowledge`, `knowledge_file`, and file records plus the configured vector adapter. Chroma is already the default adapter and can use either a local persistent client or one HTTP Chroma instance. Knowledge is retrieved context and is not executable.
- Workspace model records store the version-specific system prompt in `model.params.system`; the frontend edits it at Workspace → Models → edit model → System Prompt. Model metadata also stores Tool, Filter, Knowledge and capability selections.
- Authentication resolves JWT cookies/bearer tokens and API keys to a `UserModel`. `get_verified_user` permits `user` and `admin`; `get_admin_user` permits only `admin`. Resource sharing uses `AccessGrants` and group membership. We reuse these identities and do not add a second role database.
- `tasks.py` only tracks live `asyncio.Task` objects, optionally mirroring IDs/cancellation commands in Redis. Results are not durable, jobs disappear with a process restart, and CPU/GPU work would still occupy the web process. It is unsuitable for heavy scientific jobs.
- `AuditLoggingMiddleware` can record authenticated request/response data to the configured audit log, but it does not create a linked scientific record spanning job input, raw result, final assistant text and cleanup events.

### Frontend map

- Runtime branding comes from backend `WEBUI_NAME`; however `env.py` appends ` (Open WebUI)` to custom names. Startup `<title>` is hardcoded in `src/app.html`, notification titles are hardcoded in `src/routes/+layout.svelte`, and channel titles and PWA/OpenSearch metadata contain additional literals. Favicons and splash artwork are under `static/`.
- Uploaded user images already render inline in `Messages/UserMessage.svelte` when either `type === "image"` or `content_type` begins with `image/`. The upload path sets `content_type`, and `InputMenu/Files.svelte` maps stored image MIME types back to `type: "image"`. Assistant output images render inline in `Messages/ResponseMessage.svelte` when the returned file descriptor has the same shape. Stage 8 therefore hardens and tests this existing behavior instead of replacing it.
- The file picker used from chat is `MessageInput/InputMenu/Files.svelte`; it calls `/api/v1/files/search` and therefore reads the `file` table. The Code Interpreter/terminal side panel is `ChatControls.svelte`; its Files tab is a separate Pyodide/terminal filesystem view. Scientific outputs will be registered in OpenWebUI Files and attached to the assistant message; they are not presented as unregistered paths in a browser-only Pyodide filesystem.

## 2. Placement decisions

The categories in the mandate are used explicitly below. A component can have a thin OpenWebUI adapter and a separate execution component; both placements are stated.

| Requirement | Placement | Decision and source-based reason |
|---|---|---|
| General STAC access | **Tool** | One model-visible `stac_catalog` method handles collection listing, item listing, schema inspection, and searches. These are bounded synchronous HTTP operations and fit native function calling. Its server URL, timeout, result limit and TLS behavior are Valves. It never duplicates STAC querying inside another Tool. |
| STAC natural-language interpretation | **Tool**, deterministic parser | The Tool accepts one loose query plus an optional operation. It maps known date/bbox/query terms locally, discovers collection/item fields from live STAC JSON, and returns an explicit unsupported-field list. It does not let the LLM invent a catalog field. |
| PlanetIR | **Tool adapter + separate backend service + new worker container** | The Tool exposes one `planetir` method with `submit`, `status`, and `cancel` actions. `submit` resolves `__files__`, sends an immutable job request, and returns a job ID immediately. Raster processing is CPU/RAM-heavy and must not execute in the synchronous chat request. Celery workers execute deterministic Rasterio/NumPy/SciPy/scikit-image code. |
| ISIS3 | **Tool adapter + separate backend service + optional new worker container** | One `isis3_preprocess` entry point submits/statuses/cancels raw-product jobs. ISIS3 is isolated from PlanetIR because it has a separate runtime, large ISISDATA/SPICE/calibration data, and can change radiometry. The orchestrator skips it for a catalog item or upload already identified as a calibrated, map-projected GeoTIFF. |
| Heavy-job queue | **Separate backend service + Redis container + Celery worker containers** | OpenWebUI’s `tasks.py` is process-local execution with optional Redis bookkeeping, not durable work dispatch. Celery provides durable queued state, acknowledgement/retry controls, separate queues, and worker concurrency caps. The FastAPI job API stays responsive and returns IDs immediately. |
| CPU/GPU/RAM budgets | **Worker/container configuration** | Default hard caps are two PlanetIR CPU jobs, one ISIS3 job, and one future GPU job. Celery queue routing prevents CPU work from entering the GPU worker. Compose resource limits, job input-size limits, per-job time limits and a single GPU worker prevent oversubscription. All limits are environment settings and Tool Valves where per-deployment tuning is appropriate. |
| Generated-output visibility | **Tool adapter using OpenWebUI file subsystem** | On `status` after success, the adapter registers each worker artifact through the same `upload_file_handler(..., process=False)` path used by uploads, producing storage bytes plus a user-owned `file` row. It returns `/api/v1/files/{id}/content` descriptors and emits a `files` event. Raw filesystem writes alone are never considered published. |
| Cleanup | **Admin-only Tool adapter + separate backend service** | A single model-visible `sacai_cleanup` method accepts `preview` or `execute` and a preview token. It requires injected `__user__.role == "admin"`, matching OpenWebUI’s role rather than maintaining parallel roles. The service is restricted to configured SACAI job/output/tool-version roots. Preview is mandatory; execute must present the matching unexpired token. Every deletion is appended to the linked audit store. A scheduled maintenance task may generate previews but never executes deletion automatically. |
| Grounding guard | **Function/Filter plus service audit endpoint** | A global or model-selected outlet `Filter` sees the final response and turn metadata. It extracts numeric tokens and compares normalized values with raw tool results captured for the turn, appending a warning for unmatched values. A Filter is the native response-middleware extension point; it is not a Tool the model can choose to skip. Scientific output Pydantic schemas reject malformed or out-of-range results before they reach the model. |
| Linked scientific audit trail | **Separate backend service + database volume** | Job/tool inputs, raw JSON outputs, published file IDs, final text, grounding results and cleanup events share a correlation ID in an append-only SQLite audit database (PostgreSQL is the documented scale-up option). OpenWebUI’s HTTP audit middleware remains enabled for authentication and route-level audit; the scientific store supplies the missing linked domain record. |
| Conditional end-to-end workflow | **One Tool adapter + LangGraph inside the separate backend service** | After the single STAC Tool identifies an item and its asset is attached, one `scientific_workflow` submit/status/cancel entry point queues optional ISIS3 → PlanetIR → grounding decision → report instead of relying on repeated model choices. LangGraph checkpoints graph state. A native interrupt occurs before destructive cleanup execution and after grounding failure. The standalone Tools remain independently usable and testable; STAC access is not duplicated in the workflow. |
| Knowledge/RAG | **Knowledge base + one Chroma container** | User documentation and scientific references may be retrieved through OpenWebUI Knowledge. Planning documents, pseudocode, internal callable names and “exposed functions” lists remain in `docs/` and are never attached. One Chroma HTTP service is shared by this platform; no second vector store is introduced. |
| Rebrand | **Docker build overlay and environment config** | All new files stay in `sacai-platform`. A reproducible build script copies a small branding overlay into a temporary OpenWebUI build context, sets `WEBUI_NAME=SAC-ALRA`, removes the suffix behavior, replaces startup/notification/channel/PWA/OpenSearch literals, and supplies project-owned favicon/splash assets. This is an explicit, reviewable patch against v0.10.2 and avoids scattering hand edits through the vendor checkout. |
| Inline images | **Existing frontend behavior plus overlay tests/fix only if needed** | v0.10.2 already renders user and assistant image records inline. We preserve this, ensure published output descriptors contain `type: image`, `content_type`, and an authenticated content URL, and add regression tests. No new backend service is required solely for rendering. |
| Model selection | **Evaluation harness and documentation; no automatic replacement** | Candidate models are pulled only on a connected staging machine, tested against the exact SACAI schemas, license-checked, exported, and re-tested offline. Production keeps the current Qwen models until a candidate wins the checked-in accuracy gate. Model weights are deployment assets, not Knowledge. |
| System prompts | **Versioned prompt files + OpenWebUI model config** | Git stores the canonical prompt. An admin copies it into Workspace → Models → System Prompt or uses the authenticated model update API. The database remains the runtime source because `ModelEditor.svelte` writes `params.system` and request middleware applies it. |
| Future DL models | **Tool adapter + routed worker queue** | Each future model has one orchestrating Tool method and an inference wrapper in the service. Weights live under a read-only model volume, never in Tool source or Knowledge. GPU queue/concurrency and resource Valves are reused. |
| Future agentic file editing | **Later-stage scoped Tool + sandbox service; not implemented now** | Stage 13 only designs this. A future service will resolve all paths below one configured project root, use separate read/write capabilities, require diffs and explicit approval for writes/deletes, and append every operation to the audit trail. It will not expose a general shell or unrestricted filesystem Tool. |

## 3. Queue and resource policy

Redis is the broker/result backend and Celery is the dispatch layer. Jobs have ownership (`user_id`), queue name, status, timestamps, input file IDs, resolved internal path, output manifest, resource estimate and correlation ID. The API checks ownership on every status/cancel/result request; admin cleanup uses the admin role forwarded by the trusted in-process Tool adapter.

Default queues and caps:

| Queue | Worker concurrency | Default budget per job | Time limit |
|---|---:|---:|---:|
| `planetir_cpu` | 2 | 8 CPU, 32 GiB RAM | 60 minutes |
| `isis_cpu` | 1 | 16 CPU, 64 GiB RAM | 120 minutes |
| `gpu` | 1 | 1 H100 allocation, 64 GiB host RAM | 60 minutes |
| `maintenance` | 1 | 2 CPU, 4 GiB RAM | 30 minutes |

These are conservative starting points, not hidden constants. Compose environment variables and service Valves configure accepted file size, queue name, timeouts and concurrency. Operators measure real imagery before raising them. Redis itself never executes scientific code. The API rejects new submissions when queued-job count or per-user outstanding-job limits are exceeded; accepted excess work waits instead of consuming more RAM.

## 4. File lifecycle and trust boundaries

1. A user uploads through OpenWebUI. The Tool receives `__files__`, selects a record by `id` or unambiguous filename, verifies owner/read access using OpenWebUI models, and resolves bytes through `Storage.get_file()`.
2. The Tool submits an internal job containing the user ID, correlation ID and a service-visible path under the shared uploads volume. The model never supplies that path.
3. A worker writes to `SACAI_OUTPUT_ROOT/<user-id>/<job-id>` only. The API returns a manifest; it never returns arbitrary directory traversal paths.
4. On a successful `status`, the Tool opens each manifest artifact and passes it through OpenWebUI’s upload handler as the same user. This creates the file row used by search/list/download UI. The Tool emits the registered file descriptors and stores their IDs in the audit record.
5. Cleanup previews only roots and records owned by this platform. Published OpenWebUI files are deleted through the OpenWebUI file API/model path so database, storage and vector associations stay consistent; unregistered worker temporaries are deleted by the maintenance worker.

## 5. ISIS3 compatibility decision

ISIS3 is an optional container, not installed into the OpenWebUI or PlanetIR images. Its image and all data are built and verified on an internet-connected EL9-compatible staging host, then transferred as an OCI archive. `ISISROOT`, `ISISDATA`, mission calibration data and required SPICE kernels are mounted read-only except for a dedicated ISIS preferences/cache directory. RHEL 9.5 is not claimed as an upstream-supported native host merely because an older RHEL release appears in upstream documentation; the acceptance gate is running the pinned ISIS container and reference products on the actual RHEL 9.5/AMD64 production kernel. Failure of that gate leaves ISIS disabled while calibrated GeoTIFF → PlanetIR remains usable.

## 6. Staging deviations

The proposed order is retained with two small implementation dependencies documented explicitly:

- Stage 1 output visibility supplies the publication adapter used by later Tools, while branding is delivered as an overlay because all new files must remain in one folder.
- Stage 6’s queue contract and minimal service skeleton are introduced alongside the first heavy Tool so Stage 4 can be independently usable without blocking the web process. Stage 6 then hardens quotas, cancellation and resource controls. This is a dependency split, not a change to the user-visible stage ordering.
- Stage 13 remains design-only. No agentic read/write or shell capability is implemented in this delivery.

## 7. Rejected alternatives

- Running raster/ISIS/DL code directly in a synchronous Tool was rejected because it blocks a chat request and shares memory with the web process.
- OpenWebUI `tasks.py` was rejected for scientific jobs because it creates local `asyncio.Task` objects and has no durable result or worker isolation.
- Treating a raw `/mnt/uploads` write as a published file was rejected because the frontend lists database file records and download routes enforce those records.
- Asking the model for a path was rejected because stored names are UUID-prefixed and the model receives file IDs.
- A Knowledge document describing callable functions was rejected because Knowledge is prompt context, not an executable registry, and can induce false tool calls.
- Multiple narrow STAC or PlanetIR helper methods were rejected because OpenWebUI exposes public methods as separate model-callable functions and this project has already experienced tool-call loops from that pattern.
- A second vector store was rejected because OpenWebUI already supports Chroma and the mandate permits only one platform-owned store.

## 8. Production frontend corrections

| Failure | Placement | Source-derived decision |
|---|---|---|
| Tool/Function Save crashes before its API request | **Docker build overlay plus defensive frontend utility patch** | The stack resolves to `src/lib/utils/index.ts:compareVersion()`, not a list sort or database row. Tool and Function create/edit pages pass the compile-time `WEBUI_VERSION`; direct invocation of `vite build` did not provide npm's `npm_package_version`, so `current.localeCompare()` received `undefined`. The Docker frontend build will explicitly export the checked package version, and the disposable overlay will make version comparison null-safe. This remains a build-time overlay because no Tool, Function, Pipeline, Knowledge base, or backend service participates in the editor's client-side Save promise. |
| SAC-ALRA logo returns no usable asset | **Docker branding overlay/static asset placement** | OpenWebUI startup clears `backend/open_webui/static` and repopulates it from `FRONTEND_BUILD_DIR/static`. The overlay previously installed the SVG at the frontend build root, while patched pages requested `/static/sacai-logo.svg`; startup therefore removed the only backend copy. The overlay will also install the logo at `static/static/sacai-logo.svg`, which SvelteKit emits as `build/static/sacai-logo.svg`. No core source-tree edit or new service is required. |

## 9. Connected-builder proxy reliability

The AlmaLinux machine is running Docker Desktop (`docker:desktop-linux`). Its
Docker Desktop/Containers proxy owns registry pulls, while explicit build
arguments and temporary container environment variables own `apk`, apt, npm,
pip, and model downloads. The bundle must not override Docker Desktop's internal
`http.docker.internal` DNS name with `host-gateway`; that can redirect the proxy
hostname to the wrong endpoint. A connected-container preflight will prove the
Alpine repository is reachable through the configured proxy before dependency
builds start. Downloads use bounded retries and longer handshakes, and apt-cache
output is returned to the invoking AlmaLinux user's UID/GID. These changes are
confined to connected bundle preparation and dependency images; production
runtime proxy variables remain explicitly empty.

## 10. STAC field-value queries

Requests such as “give me all sun-incidence values for these product IDs” stay
inside the single model-visible `stac_catalog` Tool. Product IDs map to the STAC
Search `ids` member, a bare year maps to an inclusive UTC interval, and a sensor
or mission term such as `TMC` is matched only against collection IDs/titles or
values actually observed in collection summaries and sampled items. Ambiguous
or unobserved terms are reported instead of being guessed.

Requested output fields are resolved against the observed schema and returned
per product, with missing properties identified explicitly. “All” means all
records fetched up to the configured user/server safety cap; pagination is
followed until that cap and the response states when additional pages remain.
This is deterministic catalog projection, not scientific computation, so it
does not add a worker, knowledge document, or another model-callable method.

## 11. Allowlisted remote Jupyter notebook execution

Remote notebook execution is placed as **one Tool adapter + a separate queued
worker using the existing backend service and Redis/Celery stack**. A notebook
may run much longer than an OpenWebUI Tool HTTP request, so the public
`jupyter_runtime` method exposes `list`, `check`, `submit`, `status`, and
`cancel` actions while the `notebook_remote` queue performs execution. This
adds one worker process from the existing scientific-service image, not a new
runtime image or vector store.

The runtime URL, API token, TLS policy, kernel name, and mapping from friendly
code names to existing `.ipynb` paths are admin Valves. The model and user can
choose only a configured code name and provide a bounded `product_id`; they
cannot send Python source, notebook paths, server addresses, or shell commands.
The worker uses the standard Jupyter Server Contents, Sessions, Kernels, and
kernel WebSocket APIs, injects `product_id`/`sacai_product_id` as data before
executing the fetched code cells, and always attempts to close its remote
session.

Executed notebooks, a bounded JSON result, and captured PNG outputs are written
under the existing user/job output root, hashed, audited, and published through
OpenWebUI Files. HTML output is recorded only as plain JSON metadata and is not
published inline. The Jupyter credential is sent over the trusted internal API
to the queued task but is excluded from job metadata, audit events, task
results, and error text. Production should use HTTPS for any route crossing an
untrusted network; this design cannot make a token sent to an HTTP server
confidential.
