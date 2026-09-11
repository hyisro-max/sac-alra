"""Isolated super-resolution wrapper (SR4RS-based), running inside the super-res worker."""

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


def enhance(job_id: str, user_id: str, input_path: str, options: dict[str, Any]) -> dict[str, Any]:
    """Run the pinned super-resolution wrapper and validate its GeoTIFF output.

    The job/user IDs, Tool-resolved image path, and Valve options are inputs.
    This is a standalone, on-demand capability -- not chained into ISIS/ASP/OTB
    DEM generation -- so it accepts any single image the model wants enhanced.
    """

    settings = get_settings()
    source_path = resolve_below(input_path, settings.upload_root)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if source_path.stat().st_size > settings.max_input_bytes:
        raise ValueError("input exceeds configured SACAI_MAX_INPUT_BYTES")
    if not settings.superres_command:
        raise RuntimeError("SACAI_SUPERRES_COMMAND is not configured; the super-resolution stage is disabled")

    output_dir = resolve_below(str(settings.output_root / user_id / job_id), settings.output_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / "superres.tif"
    arguments = [
        part.format(input=str(source_path), output=str(destination))
        for part in shlex.split(settings.superres_command)
    ]
    completed = subprocess.run(
        arguments,
        check=False,
        capture_output=True,
        text=True,
        timeout=settings.superres_time_limit_seconds,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"super-resolution wrapper failed: {completed.stderr[-4000:]}")
    if not destination.is_file():
        raise RuntimeError("super-resolution wrapper completed without producing the expected GeoTIFF")

    with rasterio.open(destination) as dataset:
        if dataset.driver != "GTiff":
            raise ValueError("super-resolution output is not a GeoTIFF")
        metadata = {
            "driver": dataset.driver,
            "width": dataset.width,
            "height": dataset.height,
            "bands": dataset.count,
            "crs": dataset.crs.to_string() if dataset.crs else None,
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
