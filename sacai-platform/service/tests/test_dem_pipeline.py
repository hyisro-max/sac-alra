"""Schema and routing tests for the lunar DEM (ASP) and OTB pipeline stages."""

import pytest
from pydantic import ValidationError


def test_lunar_dem_job_accepts_a_validated_secondary_input() -> None:
    """Accept a lunar_dem submission carrying the right stereo-pair fields."""

    from app.schemas import JobSubmit

    job = JobSubmit(
        kind="lunar_dem",
        user_id="scientist",
        input_file_id="left-file",
        input_path="/uploads/left.cub",
        original_name="left.cub",
        correlation_id="message-id",
        secondary_input_file_id="right-file",
        secondary_input_path="/uploads/right.cub",
        secondary_original_name="right.cub",
    )
    assert job.kind == "lunar_dem"
    assert job.secondary_input_path == "/uploads/right.cub"


def test_secondary_input_file_id_cannot_become_an_output_path() -> None:
    """Reject path separators in the secondary file ID, same as input_file_id."""

    from app.schemas import JobSubmit

    with pytest.raises(ValidationError):
        JobSubmit(
            kind="lunar_dem",
            user_id="scientist",
            input_file_id="left-file",
            input_path="/uploads/left.cub",
            original_name="left.cub",
            correlation_id="message-id",
            secondary_input_file_id="../outside",
            secondary_input_path="/uploads/right.cub",
            secondary_original_name="right.cub",
        )


def test_orthorectify_job_kind_is_accepted() -> None:
    """Accept the orthorectify job kind with its own secondary (DEM) input."""

    from app.schemas import JobSubmit

    job = JobSubmit(
        kind="orthorectify",
        user_id="scientist",
        input_file_id="image-file",
        input_path="/uploads/image.tif",
        original_name="image.tif",
        correlation_id="message-id",
        secondary_input_file_id="dem-file",
        secondary_input_path="/uploads/dem.tif",
        secondary_original_name="dem.tif",
    )
    assert job.kind == "orthorectify"


def test_paired_task_rejects_a_missing_secondary_input() -> None:
    """Reject a lunar_dem/orthorectify payload with no secondary_input_path.

    _run_paired_job is the shared guard behind both sacai.lunar_dem and
    sacai.orthorectify; a submission that somehow bypassed the API's own
    check must still fail loudly here rather than call the processor with
    an empty right-image/DEM path.
    """

    from app.tasks import _run_paired_job

    payload = {
        "kind": "lunar_dem",
        "user_id": "scientist",
        "input_file_id": "left-file",
        "input_path": "/uploads/left.cub",
        "original_name": "left.cub",
        "correlation_id": "message-id",
        "job_id": "job-1",
        "options": {},
    }
    with pytest.raises(ValueError, match="secondary_input_path"):
        _run_paired_job(payload, lambda *_args: {})


def test_dem_and_otb_queues_are_isolated_from_isis_and_planetir() -> None:
    """Confirm the new ASP/OTB/CH2 queues route independently of existing ones.

    Each heavy stage must run in its own resource-capped container: routing
    lunar_dem/orthorectify onto an existing queue would let stereo
    correlation or orthorectification starve PlanetIR/ISIS jobs sharing that
    worker, or run in a container that lacks the ASP/OTB binaries entirely.
    """

    from app.celery_app import celery_app

    routes = celery_app.conf.task_routes
    queues = {q.name for q in celery_app.conf.task_queues}
    assert routes["sacai.lunar_dem"]["queue"] == "asp_cpu"
    assert routes["sacai.orthorectify"]["queue"] == "otb_cpu"
    assert {"asp_cpu", "otb_cpu", "ch2_cpu"} <= queues
    assert routes["sacai.lunar_dem"]["queue"] not in {routes["sacai.isis3"]["queue"], routes["sacai.planetir"]["queue"]}
    assert routes["sacai.orthorectify"]["queue"] not in {routes["sacai.isis3"]["queue"], routes["sacai.planetir"]["queue"]}
