# SACAI developer's manual

This guide assumes no previous OpenWebUI extension experience. All project code
belongs under `sacai-platform`; do not edit the vendor source directly.

## Install or update a Tool

1. Copy the chosen file from `openwebui_tools/` to your workstation clipboard.
2. Sign in as an OpenWebUI admin. Open **Workspace → Tools → + Create a Tool**.
3. Paste the complete source, save it, and open its gear/Valves panel. Set every
   deployment value, especially service URL/token or the STAC URL. Never commit
   a production token into Tool source.
4. Open **Workspace → Models**, edit the intended model, enable that Tool in its
   Tool selection, and save. Start with an admin-only test model; do not enable
   an untested Tool globally.
5. In a fresh chat, attach an input through the paperclip/Files interface. A
   raster Tool must receive `__files__`; never type or request a storage path.

OpenWebUI stores Tool source in its database, so `openwebui_tools/<name>.py` is
the versioned canonical copy. The naming convention is lowercase snake case.
Each `Tools` class has exactly one public method; helpers begin with `_`. Its
public method orchestrates the whole model-facing operation and has a full
docstring. Reserved injected arguments start with `__` and do not appear in the
model schema.

### Test a Tool before enabling it

```bash
cd sacai-platform
python3 -m compileall -q openwebui_tools
docker build --network=none -f docker/service-test.Dockerfile -t sacai/tests:1.1.0 ..
docker run --rm sacai/tests:1.1.0
```

Then create a private test model and run submit, status, failure, unauthorized
file, ambiguous attachment, cancel, and repeated-success-poll cases. Confirm a
successful artifact appears in Files and downloads. Test two users and ensure
one cannot inspect the other's job or attachment.

For `stac_catalog`, also test exact product-ID lists, a bare-year plus sensor or
mission query, requested metadata values, a missing property on one returned
item, an unknown ID, and a response spanning more than one STAC page. Exact
field names come from schema inspection or the Tool's `field_aliases` Valve;
never add a natural-language alias without mapping it to a catalog property.

## Add a Knowledge base safely

1. Open **Workspace → Knowledge → +** and create a narrowly named collection.
2. Upload only user-facing references that should become retrieved prompt
   context. Enable the collection on only the relevant model.
3. Ask source-specific questions and inspect citations before wider rollout.

Never upload architecture plans, source code, pseudocode, internal method names,
Tool schemas, or “exposed functions” lists. Knowledge is prose context, not an
executable registry; descriptions of imaginary callables can trigger false tool
calls. SACAI uses the one Compose Chroma service. Do not start a second project
vector store.

## Add a deterministic Tool or DL model

1. Put model weights below `offline/models/<model-name>/<version>/`. Mount that
   directory read-only into a dedicated worker; never put weights in Knowledge,
   Tool source, or the OpenWebUI database.
2. Add a small service wrapper under `service/app/`. It accepts a validated job
   record and returns a Pydantic-validated JSON result plus hashed artifact
   manifests. Document inputs, outputs, preprocessing, device/dtype, limits,
   and provenance in every class/function docstring.
3. Add a routed Celery queue and worker container. GPU inference defaults to one
   process per allocated GPU; overflow waits in Redis. Set hard CPU/RAM/GPU and
   time limits. Do not execute inference in OpenWebUI's request process.
4. Add one adapter under `openwebui_tools/`. Its sole public method resolves an
   attached file ID with OpenWebUI Files/Storage/access control, returns a job
   ID immediately, polls ownership-safe status, and registers output with
   `upload_file_handler`.
5. Add known-answer unit tests, an output schema test, two-user isolation tests,
   and cases in `model-eval/cases.jsonl`. Pre-stage every wheel and weight and
   repeat the disconnected rebuild gate.
6. Add the architectural placement and resource budget to
   `ARCHITECTURE_DECISIONS.md`, a stage README, and a new append-only build-log
   entry before enabling it.

## Add a remote Jupyter notebook safely

Use `jupyter_runtime`; do not create one Tool per notebook. An administrator
adds a friendly name and relative `.ipynb` path to its `allowed_notebooks`
Valve. Notebook code receives `product_id` and `sacai_product_id` as variables.
Users may choose the friendly name but never provide source code, a path,
server URL, token, or shell command. Test REST access, WebSocket access, output
bounds, cancellation, and remote-session cleanup before enabling a notebook.
Rebuild the scientific service/offline bundle after changing the executor or
its dependencies; changing only the stored allowlist Valve needs no restart.

## Add or change a Valve

Use `Valves` for admin/deployment configuration and `UserValves` only for a
bounded per-user preference. Add a typed Pydantic field with a useful description
and safe min/max. Read it through `self.valves`; do not shadow it with a literal.
Secrets use a password input hint. For a service setting, add the matching
`SACAI_*` Pydantic setting, `.env.example` entry, Compose environment mapping,
and offline documentation. Changing a stored Tool Valve does not require a
container restart; changing service environment does.

## Version and roll back Tools

1. Before updating the database, copy the old canonical source into
   `/data/tool_versions/<tool>/<version>/` or an operator-controlled release
   archive, record its checksum, current Valves (redacting secrets), and model
   assignments in `BUILD_LOG.md`.
2. Increment the source frontmatter version and test a private model.
3. Promote by pasting the reviewed source into the same Tool record; keep the
   previous copy until the retention window passes.
4. To roll back, disable the Tool on broad models, paste the exact prior source,
   restore its compatible Valve values, rerun smoke tests, and re-enable it.
5. Admin cleanup may preview superseded copies, but deletion requires the exact
   unexpired preview token and is audited.

## Update a model system prompt

The canonical prompt is `prompts/planetir_system_prompt.md` or
`prompts/coder_system_prompt.md`; runtime uses the OpenWebUI model database field
`model.params.system`.

1. Edit the prompt file and review the diff.
2. Add a `BUILD_LOG.md` entry with file checksum, reason, reviewer, and intended
   model ID.
3. Sign in as admin and open **Workspace → Models**. Edit the workspace model,
   replace **System Prompt** with the complete file contents, save, reopen the
   model, and verify the text persisted.
4. Start a new chat (old chats may retain context), run the relevant tool-call
   and numeric-grounding cases, and record results.

For scripted promotion, use OpenWebUI's authenticated model update API from an
approved admin workstation only after inspecting the v0.10.2 request shape in
the browser network panel/API docs. Send the full existing model record with
only `params.system` changed; never guess a partial-update contract and never
put an admin token in the repository.

## Pitfalls already encountered

- **Infinite tool-call loop:** public helper methods are all exposed as tools.
  SACAI exposes one public entry point per Tool and prefixes every helper `_`.
- **Guessed filepath:** stored files have internal names. SACAI selects from
  injected `__files__`, loads the DB record, checks access using `UserModel`, and
  resolves storage internally.
- **Invisible outputs:** writing under a mounted path does not create a Files row.
  Adapters publish through `upload_file_handler` and emit real descriptors.
- **Blocking chat:** OpenWebUI's asyncio task registry is not a scientific queue.
  Heavy work goes to Celery with job IDs, quotas, routed queues, and hard caps.
- **Shared-file authorization type:** `has_access_to_file` expects `UserModel`,
  not the injected dictionary. Resolve the user first.
- **Duplicate publication:** repeated status polling can duplicate output rows.
  The API stores published descriptors and adapters return them thereafter.
- **Partial offline cache:** an image manifest without all Ollama blobs, or a
  Python wheel without transitives, is not offline-ready. Checksum and rebuild
  with egress disabled.
- **ISIS reprocessing:** calibrated GeoTIFFs skip ISIS because another pass may
  alter radiometry/projection.
- **Ungrounded numbers:** prompts are insufficient by themselves. Deterministic
  schemas and the outlet Filter visibly flag final numbers absent from tool JSON.
- **Project-name split:** frontend literals are build-time assets while
  `WEBUI_NAME` is runtime state. Set the same `PROJECT_NAME` before rebuilding.
