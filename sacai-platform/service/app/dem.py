"""Isolated ISIS-stereo-pair-to-DEM wrapper, running inside the ASP worker."""

import hashlib
import shlex
import subprocess
from pathlib import Path
from typing import Any

import rasterio

from .config import get_settings
from .schemas import Artifact
from .security import resolve_below


def _hash_artifact(path: Path, content_type: str) -> Artifact:
    """Return a validated manifest for one worker-created GeoTIFF."""

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return Artifact(
        path=str(path),
        name=path.name,
        content_type=content_type,
        size=path.stat().st_size,
        sha256=digest.hexdigest(),
    )


def generate_dem(
    job_id: str, user_id: str, input_path: str, secondary_input_path: str, options: dict[str, Any]
) -> dict[str, Any]:
    """Run the pinned, mission-agnostic ASP stereo/DEM wrapper and validate its output.

    The job/user IDs, Tool-resolved left/right stereo-pair paths, and Valve
    options are inputs. Both images must already be ISIS-calibrated with
    intact camera models (the ISIS "spice" stage output, not a map-projected
    GeoTIFF -- map projection removes the geometry ASP needs to triangulate).
    The output describes the generated DEM GeoTIFF.
    """

    settings = get_settings()
    left_path = resolve_below(input_path, settings.upload_root)
    right_path = resolve_below(secondary_input_path, settings.upload_root)
    for candidate in (left_path, right_path):
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        if candidate.stat().st_size > settings.max_input_bytes:
            raise ValueError("input exceeds configured SACAI_MAX_INPUT_BYTES")
    if not settings.asp_command:
        raise RuntimeError("SACAI_ASP_COMMAND is not configured; the DEM stage is disabled")

    output_dir = resolve_below(str(settings.output_root / user_id / job_id), settings.output_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / "dem.tif"
    arguments = [
        part.format(left=str(left_path), right=str(right_path), output=str(destination))
        for part in shlex.split(settings.asp_command)
    ]
    completed = subprocess.run(
        arguments,
        check=False,
        capture_output=True,
        text=True,
        timeout=settings.dem_time_limit_seconds,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"ASP wrapper failed: {completed.stderr[-4000:]}")
    if not destination.is_file():
        raise RuntimeError("ASP wrapper completed without producing the expected DEM GeoTIFF")

    with rasterio.open(destination) as dataset:
        if dataset.driver != "GTiff" or dataset.crs is None:
            raise ValueError("ASP output is not a map-projected GeoTIFF")
        metadata = {
            "driver": dataset.driver,
            "width": dataset.width,
            "height": dataset.height,
            "bands": dataset.count,
            "crs": dataset.crs.to_string(),
            "transform": list(dataset.transform)[:6],
        }
    artifact = _hash_artifact(destination, "image/tiff")
    return {
        "schema_version": "1.0",
        "job_id": job_id,
        "status": "succeeded",
        "metadata": metadata,
        "artifacts": [artifact.model_dump(mode="json")],
        "stdout_tail": completed.stdout[-4000:],
    }
