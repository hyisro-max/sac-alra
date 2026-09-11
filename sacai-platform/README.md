# SAC-ALRA platform overlay

This folder is the complete upgrade-safe SAC-ALRA delivery for the checked-in
OpenWebUI v0.11.3 source. It does not modify `source-code/open-webui`.

## What is here

- `openwebui_tools/`: one-entry-point STAC, PlanetIR, ISIS3, allowlisted Jupyter, queued workflow,
  and admin-cleanup Tools.
- `openwebui_functions/`: the post-response numeric grounding Filter.
- `service/`: deterministic raster code, job API, Celery workers, audit storage,
  schemas, and LangGraph workflows.
- `branding/` and `docker/`: the build-time rebrand overlay and offline images.
- `docs/`: operator, ISIS3, model-evaluation, and developer manuals.
- `stage-00` through `stage-14`: independently testable stage handoffs.

## First deployment

For a single command-by-command handoff, start with [`next_step`](next_step).

1. On this Mac, create the clean AlmaLinux source package as described in
   `docs/ALMALINUX_CONNECTED_BUILDER.md`.
2. On an internet-connected AlmaLinux 9 AMD64 machine, verify/extract it and run
   `cd sacai-platform && ./scripts/run_on_alma_builder.sh`.
3. Transfer the generated full offline archive to the
   RHEL 9.5 host using encrypted removable media or an approved internal share.
4. On each offline host, copy its `.env.server-*.example` to `.env`, replace
   both secret placeholders, and confirm its external Ollama API URL.
5. Run `./scripts/load_offline_images.sh`, then `./scripts/rebuild_offline.sh`.
6. Open `http://10.61.247.253:2018` or `http://10.61.247.254:3000`, create the
   first admin, and install the Tool/Filter sources described in
   [the developer manual](docs/DEVELOPER_MANUAL.md).

The exact pre-stage list and verification commands are in
[OFFLINE_DEPLOYMENT.md](docs/OFFLINE_DEPLOYMENT.md). Do not call the bundle
offline-ready until every checksum and the disconnected rebuild gate passes.
