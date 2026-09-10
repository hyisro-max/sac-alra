"""Schema-failure tests that keep malformed scientific output from the model."""

import pytest
from pydantic import ValidationError


def test_histogram_shape_is_rejected() -> None:
    """Reject a histogram whose edge count cannot describe its bins."""

    from app.schemas import PlanetIRResult

    with pytest.raises(ValidationError):
        PlanetIRResult.model_validate(
            {
                "job_id": "bad",
                "generated_at": "2026-01-01T00:00:00Z",
                "mode": "analyze",
                "metadata": {
                    "driver": "GTiff",
                    "width": 1,
                    "height": 1,
                    "bands": 1,
                    "dtypes": ["uint8"],
                    "crs": None,
                    "transform": [1, 0, 0, 0, -1, 0],
                    "bounds": [0, 0, 1, 1],
                    "resolution": [1, 1],
                    "nodata": None,
                    "tags": {},
                },
                "sampling": {
                    "source_pixels_all_bands": 1,
                    "sampled_pixels_all_bands": 1,
                    "sampled_width": 1,
                    "sampled_height": 1,
                    "method": "full_resolution",
                },
                "statistics": [],
                "histogram": {"counts": [1, 2], "bin_edges": [0, 1]},
                "noise": {"detected": False, "severity_0_to_1": 0, "label": "none", "measurements": {}},
                "blur": {"detected": False, "severity_0_to_1": 0, "label": "none", "measurements": {}},
                "striping": {"detected": False, "severity_0_to_1": 0, "label": "none", "measurements": {}},
                "restoration": {},
                "artifacts": [],
                "runtime_seconds": 0,
            }
        )


def test_out_of_range_severity_is_rejected() -> None:
    """Reject an anomaly severity above the physical schema range."""

    from app.schemas import DegradationScore

    with pytest.raises(ValidationError):
        DegradationScore(detected=True, severity_0_to_1=1.1, label="high", measurements={})


def test_job_identity_cannot_become_an_output_path() -> None:
    """Reject path separators in IDs used to partition worker output roots."""

    from app.schemas import JobSubmit

    with pytest.raises(ValidationError):
        JobSubmit(
            kind="planetir",
            user_id="../outside",
            input_file_id="file-id",
            input_path="/uploads/input.tif",
            original_name="input.tif",
            correlation_id="message-id",
        )


def test_remote_notebook_rejects_paths_and_url_credentials() -> None:
    """Reject traversal and credentials embedded in runtime URLs."""

    from app.schemas import RemoteNotebookSubmit

    common = {
        "user_id": "scientist",
        "correlation_id": "message-id",
        "code_name": "tmc_stats",
        "kernel_name": "python3",
        "product_id": "TMC-001",
    }
    with pytest.raises(ValidationError):
        RemoteNotebookSubmit(server_url="http://user:secret@runtime:8888", notebook_path="notebooks/run.ipynb", **common)
    with pytest.raises(ValidationError):
        RemoteNotebookSubmit(server_url="http://runtime:8888", notebook_path="../run.ipynb", **common)
