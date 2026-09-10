"""Isolated ISIS3 raw-product preprocessing wrapper."""

import hashlib
import shlex
import subprocess
from pathlib import Path
from typing import Any

import rasterio

from .config import get_settings
from .schemas import Artifact
from .security import resolve_below


def _hash_artifact(path: Path) -> Artifact:
    """Return a validated manifest for one ISIS3-created GeoTIFF.

    The completed file path is the input. The Artifact output supplies its
    SHA-256, size and TIFF MIME type to the job API and publication adapter.
    """

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return Artifact(
        path=str(path),
        name=path.name,
        content_type="image/tiff",
        size=path.stat().st_size,
        sha256=digest.hexdigest(),
    )


def preprocess(job_id: str, user_id: str, input_path: str, options: dict[str, Any]) -> dict[str, Any]:
    """Run a pinned mission-aware ISIS3 wrapper and validate its GeoTIFF.

    The job/user IDs, Tool-resolved raw upload path and Valve options are inputs.
    The output describes the calibrated map-projected raster and never runs for
    a source already declared ready for PlanetIR.
    """

    settings = get_settings()
    source_path = resolve_below(input_path, settings.upload_root)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if source_path.stat().st_size > settings.max_input_bytes:
        raise ValueError("input exceeds configured SACAI_MAX_INPUT_BYTES")
    if source_path.suffix.lower() in {".tif", ".tiff"} or bool(options.get("already_calibrated")):
        raise ValueError("ISIS3 must be skipped for an already calibrated GeoTIFF")
    if not settings.isis_command:
        raise RuntimeError("SACAI_ISIS_COMMAND is not configured; the optional ISIS3 stage is disabled")

    output_dir = resolve_below(str(settings.output_root / user_id / job_id), settings.output_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / "calibrated_projected.tif"
    arguments = [
        part.format(input=str(source_path), output=str(destination))
        for part in shlex.split(settings.isis_command)
    ]
    completed = subprocess.run(
        arguments,
        check=False,
        capture_output=True,
        text=True,
        timeout=settings.job_time_limit_seconds,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"ISIS3 wrapper failed: {completed.stderr[-4000:]}")
    if not destination.is_file():
        raise RuntimeError("ISIS3 wrapper completed without producing the expected GeoTIFF")

    with rasterio.open(destination) as dataset:
        if dataset.driver != "GTiff" or dataset.crs is None:
            raise ValueError("ISIS3 output is not a map-projected GeoTIFF")
        metadata = {
            "driver": dataset.driver,
            "width": dataset.width,
            "height": dataset.height,
            "bands": dataset.count,
            "crs": dataset.crs.to_string(),
            "transform": list(dataset.transform)[:6],
        }
    artifact = _hash_artifact(destination)
    return {
        "schema_version": "1.0",
        "job_id": job_id,
        "status": "succeeded",
        "metadata": metadata,
        "artifacts": [artifact.model_dump(mode="json")],
        "stdout_tail": completed.stdout[-4000:],
    }
