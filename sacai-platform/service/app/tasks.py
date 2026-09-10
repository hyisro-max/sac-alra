"""Celery task entry points for routed scientific and maintenance jobs."""

from typing import Any

from celery.exceptions import SoftTimeLimitExceeded

from .audit import append_event
from .celery_app import celery_app
from .cleanup import run_cleanup
from .isis import preprocess
from .orchestrator import invoke_scientific
from .notebook_runtime import run_remote_notebook
from .planetir import analyze
from .schemas import CleanupRequest, JobSubmit, RemoteNotebookResult, RemoteNotebookSubmit


def _run_job(payload: dict[str, Any], processor) -> dict[str, Any]:
    """Run one validated job with linked start/success/failure audit events.

    The serialized submission and deterministic processor are inputs. The
    processor result is returned to Celery after raw JSON is durably audited.
    """

    job = JobSubmit.model_validate(payload)
    job_id = payload["job_id"]
    append_event(job.correlation_id, "job.started", job.user_id, {"job_id": job_id, "kind": job.kind})
    try:
        result = processor(job_id, job.user_id, job.input_path, job.options)
        append_event(job.correlation_id, "tool.raw_result", job.user_id, result)
        return result
    except SoftTimeLimitExceeded as error:
        message = "job exceeded the configured soft time limit"
        append_event(job.correlation_id, "job.failed", job.user_id, {"job_id": job_id, "error": message})
        raise RuntimeError(message) from error
    except Exception as error:
        append_event(
            job.correlation_id,
            "job.failed",
            job.user_id,
            {"job_id": job_id, "error": str(error)},
        )
        raise


@celery_app.task(name="sacai.planetir")
def planetir_task(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute one PlanetIR payload on the capped CPU queue."""

    return _run_job(payload, analyze)


@celery_app.task(name="sacai.isis3")
def isis_task(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute one raw-product ISIS3 payload on the isolated ISIS queue."""

    return _run_job(payload, preprocess)


@celery_app.task(name="sacai.cleanup")
def cleanup_task(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute an admin cleanup request on the serial maintenance queue."""

    return run_cleanup(CleanupRequest.model_validate(payload)).model_dump(mode="json")


@celery_app.task(name="sacai.workflow")
def workflow_task(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the checkpointed optional-ISIS PlanetIR graph on a capped queue.

    A validated serialized job is the input. The returned graph state includes
    deterministic results, publication artifacts, grounding, and report path.
    """

    job = JobSubmit.model_validate(payload)
    job_id = payload["job_id"]
    append_event(job.correlation_id, "job.started", job.user_id, {"job_id": job_id, "kind": job.kind})
    try:
        state = invoke_scientific(
            job_id,
            {
                "workflow_id": job_id,
                "user_id": job.user_id,
                "input_path": job.input_path,
                "options": job.options,
                "already_calibrated": bool(job.options.get("already_calibrated")),
                "final_text": "",
            },
        )
        result = {
            **state,
            "artifacts": [
                *(state.get("isis_result") or {}).get("artifacts", []),
                *(state.get("planetir_result") or {}).get("artifacts", []),
                *([state["report_artifact"]] if state.get("report_artifact") else []),
            ],
        }
        append_event(job.correlation_id, "tool.raw_result", job.user_id, result)
        return result
    except Exception as error:
        append_event(job.correlation_id, "job.failed", job.user_id, {"job_id": job_id, "error": str(error)})
        raise


@celery_app.task(name="sacai.notebook")
def notebook_task(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute one allowlisted notebook on the isolated remote-runtime queue.

    The serialized request includes a transient server credential. Audit events
    deliberately contain only safe job/code/product identifiers and results.
    """

    request = RemoteNotebookSubmit.model_validate(payload)
    job_id = str(payload["job_id"])
    safe = {"job_id": job_id, "kind": "notebook", "code_name": request.code_name, "product_id": request.product_id}
    append_event(request.correlation_id, "job.started", request.user_id, safe)
    try:
        result = RemoteNotebookResult.model_validate(run_remote_notebook(job_id, request)).model_dump(mode="json")
        append_event(request.correlation_id, "tool.raw_result", request.user_id, result)
        return result
    except SoftTimeLimitExceeded as error:
        message = "notebook job exceeded the configured soft time limit"
        append_event(request.correlation_id, "job.failed", request.user_id, {**safe, "error": message})
        raise RuntimeError(message) from error
    except Exception as error:
        message = str(error)
        if request.server_token:
            message = message.replace(request.server_token, "[redacted]")
        append_event(request.correlation_id, "job.failed", request.user_id, {**safe, "error": message})
        raise RuntimeError(message) from error
