"""Reference-raster tests for deterministic PlanetIR calculations."""

import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


def _write_raster(path: Path, values: np.ndarray) -> None:
    """Write one float32 reference GeoTIFF for a deterministic unit test.

    Destination path and 2-D values are inputs. The function returns nothing
    and creates a georeferenced single-band fixture with known ground truth.
    """

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(10, 20, 0.5, 0.5),
    ) as dataset:
        dataset.write(values.astype(np.float32), 1)


def _configure(tmp_path: Path):
    """Point cached service settings at temporary upload/output/audit roots.

    The pytest temp directory is the input. The returned settings object is
    ready for one isolated PlanetIR job without touching deployment data.
    """

    import os

    from app.config import get_settings

    os.environ["SACAI_UPLOAD_ROOT"] = str(tmp_path / "uploads")
    os.environ["SACAI_OUTPUT_ROOT"] = str(tmp_path / "outputs")
    os.environ["SACAI_TOOL_VERSIONS_ROOT"] = str(tmp_path / "tool-versions")
    os.environ["SACAI_AUDIT_DB_PATH"] = str(tmp_path / "audit.sqlite3")
    os.environ["SACAI_GRAPH_DB_PATH"] = str(tmp_path / "graphs.sqlite3")
    get_settings.cache_clear()
    settings = get_settings()
    settings.upload_root.mkdir(parents=True, exist_ok=True)
    return settings


def test_reference_ramp_statistics_and_metadata(tmp_path: Path) -> None:
    """Match PlanetIR output to precomputed ramp statistics and exact metadata."""

    settings = _configure(tmp_path)
    source = settings.upload_root / "reference-ramp.tif"
    _write_raster(source, np.arange(100, dtype=np.float32).reshape(10, 10))

    from app.planetir import analyze
    from app.schemas import PlanetIRResult

    result = PlanetIRResult.model_validate(
        analyze("reference-job", "scientist", str(source), {"mode": "analyze", "histogram_bins": 10})
    )
    expected = json.loads((Path(__file__).parent / "reference_ramp.json").read_text(encoding="utf-8"))
    actual = result.statistics[0].model_dump()
    for key, value in expected.items():
        assert np.isclose(actual[key], value, rtol=1e-6, atol=1e-6)
    assert result.metadata.width == 10
    assert result.metadata.height == 10
    assert result.metadata.crs == "EPSG:4326"
    assert result.sampling.method == "full_resolution"
    assert result.sampling.sampled_pixels_all_bands == 100
    assert len(result.histogram["counts"]) == 10
    assert len(result.histogram["bin_edges"]) == 11
    assert all(Path(artifact.path).is_file() for artifact in result.artifacts)
    preview = next(artifact for artifact in result.artifacts if artifact.name == "preview.png")
    assert preview.content_type == "image/png"


def test_anomaly_scores_are_bounded_and_restoration_is_georeferenced(tmp_path: Path) -> None:
    """Validate bounded anomaly outputs and the restored GeoTIFF contract."""

    settings = _configure(tmp_path)
    generator = np.random.default_rng(42)
    values = np.tile(np.linspace(0, 1, 64, dtype=np.float32), (64, 1))
    values[:, ::8] += 0.3
    values += generator.normal(0, 0.08, values.shape).astype(np.float32)
    source = settings.upload_root / "degraded.tif"
    _write_raster(source, values)

    from app.planetir import analyze
    from app.schemas import PlanetIRResult

    result = PlanetIRResult.model_validate(
        analyze(
            "restoration-job",
            "scientist",
            str(source),
            {
                "mode": "restore",
                "noise_threshold": 0.01,
                "blur_threshold": 0.01,
                "stripe_threshold": 0.01,
            },
        )
    )
    assert all(0 <= score.severity_0_to_1 <= 1 for score in (result.noise, result.blur, result.striping))
    restored = next(Path(item.path) for item in result.artifacts if item.name == "restored.tif")
    with rasterio.open(restored) as dataset:
        assert dataset.crs.to_string() == "EPSG:4326"
        assert (dataset.width, dataset.height) == (64, 64)
