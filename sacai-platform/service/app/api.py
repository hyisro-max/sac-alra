"""FastAPI job-control surface used by trusted OpenWebUI Tool adapters."""

import json
from typing import Any
from uuid import uuid4

from celery.result import AsyncResult
from fastapi import Depends, FastAPI, HTTPException, Query, status
from redis import Redis
from .catalog import describe as catalog_describe, search as catalog_search
from .schemas import CatalogEntry, CatalogSearchHit


from .audit import append_event, list_events
from .celery_app import celery_app
from .cleanup import run_cleanup
from .config import get_settings
from .schemas import (
    CleanupRequest,
    CleanupResult,
    JobAccepted,
    JobStatus,
    JobSubmit,
    PublicationRecord,
    RemoteNotebookSubmit,
)
from .security import require_internal_token, resolve_below
from .tasks import isis_task, notebook_task, planetir_task, workflow_task


def _redis() -> Redis:
    """Return a decoded Redis client for durable job ownership metadata.

    There are no inputs. API handlers use the returned client for quotas and
    ownership checks while Celery stores execution state in its result backend.
    """

    return Redis.from_url(get_settings().redis_url, decode_responses=True)


def _job_key(job_id: str) -> str:
    """Return the namespaced Redis key for a job identifier."""

    return f"sacai:job:{job_id}"


def _metadata(job_id: str) -> dict[str, Any]:
    """Load one job's ownership metadata or raise a not-found response.

    The job ID is the input. The decoded mapping is the output used by status
    and cancellation routes to prevent cross-user job access.
    """

    value = _redis().get(_job_key(job_id))
    if not value:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return json.loads(value)


def _check_quota(user_id: str) -> None:
    """Enforce global and per-user outstanding-job limits before dispatch.

    The requesting user ID is the input. The function returns nothing or a
    429 response, keeping excess work out of worker RAM and broker growth.
    """

    outstanding = []
    for key in _redis().scan_iter("sacai:job:*"):
        value = _redis().get(key)
        if not value:
            continue
        record = json.loads(value)
        result = AsyncResult(record["job_id"], app=celery_app)
        if not result.ready():
            outstanding.append(record)
    settings = get_settings()
    if len(outstanding) >= settings.max_queued_jobs:
        raise HTTPException(status_code=429, detail="global queued-job limit reached")
    if sum(record["user_id"] == user_id for record in outstanding) >= settings.max_user_jobs:
        raise HTTPException(status_code=429, detail="per-user outstanding-job limit reached")


app = FastAPI(title="SACAI Scientific Job Service", version="1.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    """Return a dependency-light liveness response for Compose health checks."""

    return {"status": "ok"}


@app.post("/v1/jobs", response_model=JobAccepted, dependencies=[Depends(require_internal_token)])
def submit_job(request: JobSubmit) -> JobAccepted:
    """Validate, quota-check, persist, and route one scientific job.

    A Tool-created JobSubmit is the input. The returned JobAccepted contains a
    durable ID immediately; no scientific processing occurs in the API process.
    """

    source = resolve_below(request.input_path, get_settings().upload_root)
    if not source.is_file():
        raise HTTPException(status_code=400, detail="input file does not exist")
    if source.stat().st_size > get_settings().max_input_bytes:
        raise HTTPException(status_code=413, detail="input exceeds configured SACAI_MAX_INPUT_BYTES")
    _check_quota(request.user_id)
    job_id = str(uuid4())
    if request.kind == "planetir":
        queue = get_settings().planetir_queue
        task = planetir_task
    elif request.kind == "isis3":
        queue = get_settings().isis_queue
        task = isis_task
    else:
        ready = bool(request.options.get("already_calibrated")) or source.suffix.lower() in {".tif", ".tiff"}
        queue = get_settings().planetir_queue if ready else get_settings().isis_queue
        task = workflow_task
    payload = {**request.model_dump(mode="json"), "input_path": str(source), "job_id": job_id}
    metadata = {
        "job_id": job_id,
        "correlation_id": request.correlation_id,
        "kind": request.kind,
        "user_id": request.user_id,
    }
    _redis().set(_job_key(job_id), json.dumps(metadata), ex=7 * 24 * 3600)
    task.apply_async(args=[payload], task_id=job_id, queue=queue)
    append_event(request.correlation_id, "job.submitted", request.user_id, metadata)
    return JobAccepted(job_id=job_id, correlation_id=request.correlation_id, queue=queue)


@app.post("/v1/notebook-jobs", response_model=JobAccepted, dependencies=[Depends(require_internal_token)])
def submit_notebook_job(request: RemoteNotebookSubmit) -> JobAccepted:
    """Queue one allowlisted remote notebook without persisting its credential.

    The trusted Tool request is quota-checked and dispatched immediately. Only
    safe ownership and selection metadata enters Redis or the audit trail.
    """

    _check_quota(request.user_id)
    settings = get_settings()
    job_id = str(uuid4())
    metadata = {
        "job_id": job_id,
        "correlation_id": request.correlation_id,
        "kind": "notebook",
        "user_id": request.user_id,
    }
    _redis().set(_job_key(job_id), json.dumps(metadata), ex=7 * 24 * 3600)
    payload = {**request.model_dump(mode="json"), "job_id": job_id}
    notebook_task.apply_async(args=[payload], task_id=job_id, queue=settings.notebook_queue)
    append_event(
        request.correlation_id,
        "job.submitted",
        request.user_id,
        {**metadata, "code_name": request.code_name, "product_id": request.product_id},
    )
    return JobAccepted(job_id=job_id, correlation_id=request.correlation_id, queue=settings.notebook_queue)


@app.get("/v1/jobs/{job_id}", response_model=JobStatus, dependencies=[Depends(require_internal_token)])
def job_status(job_id: str, user_id: str = Query(min_length=1)) -> JobStatus:
    """Return Celery state and result only to the job owner.

    The path job ID and querying user ID are inputs. The normalized JobStatus
    output is safe for the OpenWebUI Tool to show or publish.
    """

    metadata = _metadata(job_id)
    if metadata["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="job not found")
    if metadata.get("cancelled") is True:
        response_metadata = {key: value for key, value in metadata.items() if key not in {"published_files", "cancelled"}}
        return JobStatus(**response_metadata, status="cancelled", published_files=metadata.get("published_files", []))
    result = AsyncResult(job_id, app=celery_app)
    state_map = {
        "PENDING": "queued",
        "RECEIVED": "queued",
        "STARTED": "running",
        "SUCCESS": "succeeded",
        "FAILURE": "failed",
        "REVOKED": "cancelled",
    }
    normalized = state_map.get(result.state, "queued")
    response_metadata = {key: value for key, value in metadata.items() if key != "published_files"}
    return JobStatus(
        **response_metadata,
        status=normalized,
        result=result.result if normalized == "succeeded" else None,
        error=str(result.result) if normalized == "failed" else None,
        published_files=metadata.get("published_files", []),
    )


@app.delete("/v1/jobs/{job_id}", response_model=JobStatus, dependencies=[Depends(require_internal_token)])
def cancel_job(job_id: str, user_id: str = Query(min_length=1)) -> JobStatus:
    """Revoke a queued/running job after enforcing owner identity.

    The job and user IDs are inputs. The returned cancelled JobStatus is also
    appended to the linked audit trail for later review.
    """

    metadata = _metadata(job_id)
    if metadata["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="job not found")
    if metadata["kind"] == "notebook":
        metadata["cancelled"] = True
        _redis().set(_job_key(job_id), json.dumps(metadata), ex=7 * 24 * 3600)
        celery_app.control.revoke(job_id, terminate=False)
    else:
        celery_app.control.revoke(job_id, terminate=True, signal="SIGTERM")
    append_event(metadata["correlation_id"], "job.cancelled", user_id, {"job_id": job_id})
    response_metadata = {key: value for key, value in metadata.items() if key != "cancelled"}
    return JobStatus(**response_metadata, status="cancelled")


@app.post("/v1/jobs/{job_id}/publication", response_model=JobStatus, dependencies=[Depends(require_internal_token)])
def record_publication(job_id: str, publication: PublicationRecord) -> JobStatus:
    """Store file descriptors after OpenWebUI registers completed artifacts.

    The job ID and owner-bound publication record are inputs. The returned
    status prevents repeated polling from creating duplicate file-table rows.
    """

    metadata = _metadata(job_id)
    if metadata["user_id"] != publication.user_id:
        raise HTTPException(status_code=404, detail="job not found")
    metadata["published_files"] = publication.files
    _redis().set(_job_key(job_id), json.dumps(metadata), ex=7 * 24 * 3600)
    append_event(
        metadata["correlation_id"],
        "files.published",
        publication.user_id,
        {"job_id": job_id, "files": publication.files},
    )
    result = AsyncResult(job_id, app=celery_app)
    response_metadata = {key: value for key, value in metadata.items() if key != "published_files"}
    return JobStatus(
        **response_metadata,
        status="succeeded",
        result=result.result if result.successful() else None,
        published_files=publication.files,
    )


@app.post("/v1/cleanup", response_model=CleanupResult, dependencies=[Depends(require_internal_token)])
def cleanup(request: CleanupRequest) -> CleanupResult:
    """Preview or execute root-scoped cleanup using the OpenWebUI admin role.

    The validated cleanup request is the input. The exact targets/deletions are
    returned synchronously because only small metadata and filesystem removals
    occur; actual deletion remains two-phase and auditable.
    """

    try:
        return run_cleanup(request)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/v1/audit/{correlation_id}", dependencies=[Depends(require_internal_token)])
def record_audit_event(
    correlation_id: str,
    event_type: str,
    user_id: str,
    payload: dict[str, Any],
) -> dict[str, str]:
    """Append a Tool/filter publication or final-response audit event.

    Correlation, event, actor and JSON payload inputs produce one immutable
    event ID used to link OpenWebUI-side activity to worker computations.
    """

    return {"event_id": append_event(correlation_id, event_type, user_id, payload)}


@app.get("/v1/audit/{correlation_id}", dependencies=[Depends(require_internal_token)])
def get_audit_events(correlation_id: str) -> list[dict[str, Any]]:
    """Return the ordered scientific audit lineage for one correlation ID."""

    return list_events(correlation_id)

@app.get("/v1/isis/search", response_model=list[CatalogSearchHit], dependencies=[Depends(require_internal_token)])
def isis_search(query: str = Query(min_length=1)) -> list[CatalogSearchHit]:
    """Return ISIS applications matching a free-text query."""
    return catalog_search(query)


@app.get("/v1/isis/describe/{name}", response_model=CatalogEntry, dependencies=[Depends(require_internal_token)])
def isis_describe(name: str) -> CatalogEntry:
    """Return the full parameter schema for one named ISIS application."""
    try:
        return catalog_describe(name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown ISIS application: {name}")