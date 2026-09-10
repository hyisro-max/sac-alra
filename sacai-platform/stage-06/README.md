# Stage 6 — multi-user scheduling

Redis, the FastAPI job service, and capped Celery workers implement this stage.
Set queue/user caps and worker resources in `.env`, then rebuild.

From two accounts, submit more jobs than worker concurrency. Confirm two
PlanetIR jobs run while later jobs remain queued, ISIS stays on its own serial
queue, per-user/global excess receives HTTP 429, status is owner-only, and
cancel stops only the caller's job. Watch with `docker compose logs -f
planetir-worker notebook-worker redis`.
