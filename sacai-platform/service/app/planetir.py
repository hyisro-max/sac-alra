"""Deterministic GeoTIFF EDA, anomaly detection, and restoration for PlanetIR."""

import hashlib
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from rasterio.enums import Resampling
from scipy import ndimage
from skimage import filters, restoration

from .config import get_settings
from .schemas import Artifact, BandStatistics, DegradationScore, PlanetIRResult, RasterMetadata
from .security import resolve_below


def _artifact(path: Path, content_type: str) -> Artifact:
    """Hash one completed output file and return its publication manifest.

    The path and MIME type are inputs. The returned validated Artifact is used
    by the job API and OpenWebUI publication adapter to verify exact bytes.
    """

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


def _sample_dataset(dataset: rasterio.io.DatasetReader, max_pixels: int) -> np.ma.MaskedArray:
    """Read every band into a bounded masked sample for deterministic analysis.

    The open dataset and pixel cap are inputs. The output retains every band
    while downsampling spatial dimensions, preventing large rasters from
    exhausting shared worker RAM.
    """

    scale = min(1.0, math.sqrt(max_pixels / max(dataset.width * dataset.height * dataset.count, 1)))
    height = max(1, round(dataset.height * scale))
    width = max(1, round(dataset.width * scale))
    return dataset.read(
        out_shape=(dataset.count, height, width),
        masked=True,
        resampling=Resampling.average,
    ).astype(np.float32)


def _metadata(dataset: rasterio.io.DatasetReader) -> RasterMetadata:
    """Extract exact header metadata from an open Rasterio dataset.

    The dataset is the input and the validated RasterMetadata output becomes
    the authoritative CRS/dimension record in every PlanetIR response.
    """

    return RasterMetadata(
        driver=dataset.driver,
        width=dataset.width,
        height=dataset.height,
        bands=dataset.count,
        dtypes=list(dataset.dtypes),
        crs=dataset.crs.to_string() if dataset.crs else None,
        transform=list(dataset.transform)[:6],
        bounds=list(dataset.bounds),
        resolution=[abs(dataset.res[0]), abs(dataset.res[1])],
        nodata=(
            float(dataset.nodata)
            if dataset.nodata is not None and math.isfinite(float(dataset.nodata))
            else None
        ),
        tags={str(key): str(value) for key, value in dataset.tags().items()},
    )


def _statistics(sample: np.ma.MaskedArray) -> list[BandStatistics]:
    """Calculate deterministic descriptive statistics for every sampled band.

    The masked band stack is the input. The validated list is included in the
    tool JSON and is independent of any language-model calculation.
    """

    results: list[BandStatistics] = []
    for index, band in enumerate(sample, start=1):
        values = band.compressed()
        values = values[np.isfinite(values)]
        if values.size == 0:
            results.append(BandStatistics(band=index, count=0))
            continue
        results.append(
            BandStatistics(
                band=index,
                count=int(values.size),
                minimum=float(np.min(values)),
                maximum=float(np.max(values)),
                mean=float(np.mean(values)),
                standard_deviation=float(np.std(values)),
                median=float(np.median(values)),
                percentile_2=float(np.percentile(values, 2)),
                percentile_98=float(np.percentile(values, 98)),
            )
        )
    return results


def _normalized_primary(sample: np.ma.MaskedArray) -> np.ndarray:
    """Robustly scale the first band to zero-through-one for diagnostics.

    The sampled masked stack is the input. The finite float array output feeds
    anomaly detectors and preview/restoration algorithms without changing the
    source raster's reported statistics.
    """

    band = sample[0].filled(np.nan).astype(np.float32)
    finite = band[np.isfinite(band)]
    if finite.size == 0:
        raise ValueError("the first band contains no finite pixels")
    low, high = np.percentile(finite, [2, 98])
    if high <= low:
        return np.zeros_like(np.nan_to_num(band), dtype=np.float32)
    return np.clip(np.nan_to_num((band - low) / (high - low)), 0, 1).astype(np.float32)


def _label(score: float, threshold: float) -> tuple[bool, str]:
    """Map a bounded anomaly score to a stable detection label.

    The score and deployment threshold are inputs. The boolean and label output
    make thresholds explicit in the deterministic report.
    """

    if score <= 0 or score < threshold:
        return False, "none"
    if score < min(1.0, threshold * 2):
        return True, "low"
    if score < min(1.0, threshold * 4):
        return True, "moderate"
    return True, "high"


def _detect_noise(image: np.ndarray, threshold: float) -> DegradationScore:
    """Estimate high-frequency noise with a wavelet-style MAD residual.

    The normalized image and configurable threshold are inputs. The bounded
    score and supporting measurements are deterministic PlanetIR output.
    """

    residual = image - ndimage.median_filter(image, size=3)
    sigma = float(np.median(np.abs(residual - np.median(residual))) / 0.67448975)
    signal_std = float(np.std(image))
    score = float(np.clip(sigma / max(signal_std, 1e-12), 0, 1))
    detected, label = _label(score, threshold)
    return DegradationScore(
        detected=detected,
        severity_0_to_1=score,
        label=label,
        measurements={
            "band": 1,
            "scope": "band_1_bounded_sample",
            "wavelet_mad_sigma": sigma,
            "normalized_signal_standard_deviation": signal_std,
            "threshold": threshold,
        },
    )


def _detect_blur(image: np.ndarray, threshold: float) -> DegradationScore:
    """Estimate blur from Laplacian and Sobel focus energy.

    The normalized image and configurable threshold are inputs. The method
    returns a bounded severity score where one indicates least high-frequency
    focus energy in the sampled raster.
    """

    laplacian_variance = float(np.var(ndimage.laplace(image)))
    sobel_energy = float(np.mean(filters.sobel(image) ** 2))
    focus = 1.0 - math.exp(-40.0 * (laplacian_variance + sobel_energy))
    score = float(np.clip(1.0 - focus, 0, 1))
    detected, label = _label(score, threshold)
    return DegradationScore(
        detected=detected,
        severity_0_to_1=score,
        label=label,
        measurements={
            "band": 1,
            "scope": "band_1_bounded_sample",
            "laplacian_variance": laplacian_variance,
            "sobel_energy": sobel_energy,
            "threshold": threshold,
        },
    )


def _detect_striping(image: np.ndarray, threshold: float) -> DegradationScore:
    """Estimate horizontal or vertical striping from line-offset variation.

    The normalized image and configurable threshold are inputs. The returned
    record names the strongest orientation and reports row/column evidence.
    """

    row_offsets = np.median(image, axis=1) - np.median(image)
    column_offsets = np.median(image, axis=0) - np.median(image)
    row_strength = float(np.std(row_offsets))
    column_strength = float(np.std(column_offsets))
    strength = max(row_strength, column_strength)
    image_std = float(np.std(image))
    score = float(np.clip(strength / max(image_std, 1e-12), 0, 1))
    orientation = "horizontal" if row_strength >= column_strength else "vertical"
    detected, label = _label(score, threshold)
    return DegradationScore(
        detected=detected,
        severity_0_to_1=score,
        label=label,
        measurements={
            "band": 1,
            "scope": "band_1_bounded_sample",
            "orientation": orientation,
            "row_offset_standard_deviation": row_strength,
            "column_offset_standard_deviation": column_strength,
            "threshold": threshold,
        },
    )


def _save_visuals(image: np.ndarray, output_dir: Path, bins: int) -> tuple[dict[str, list[float | int]], list[Artifact]]:
    """Write a preview and histogram while returning exact histogram arrays.

    The normalized image, job directory, and bin count are inputs. The returned
    histogram and artifact manifests support EDA and inline/download rendering.
    """

    preview_path = output_dir / "preview.png"
    histogram_path = output_dir / "histogram.png"
    plt.imsave(preview_path, image, cmap="gray", vmin=0, vmax=1)
    counts, edges = np.histogram(image, bins=bins, range=(0, 1))
    figure, axis = plt.subplots(figsize=(8, 4))
    axis.plot(edges[:-1], counts)
    axis.set(xlabel="Robustly normalized pixel value", ylabel="Sample count", title="Band 1 histogram")
    figure.tight_layout()
    figure.savefig(histogram_path, dpi=120)
    plt.close(figure)
    return (
        {"counts": [int(value) for value in counts], "bin_edges": [float(value) for value in edges]},
        [_artifact(preview_path, "image/png"), _artifact(histogram_path, "image/png")],
    )


def _restore_image(
    image: np.ndarray,
    noise: DegradationScore,
    blur: DegradationScore,
    striping: DegradationScore,
) -> np.ndarray:
    """Apply restoration only for anomalies detected by deterministic checks.

    The normalized image and three validated anomaly records are inputs. The
    returned array applies denoising, unsharp deblurring, and line correction
    in a fixed documented order without model-selected numeric parameters.
    """

    value = image.copy()
    if noise.detected:
        sigma = float(noise.measurements["wavelet_mad_sigma"] or 0)
        value = restoration.denoise_wavelet(
            value,
            sigma=max(sigma, 1e-6),
            mode="soft",
            rescale_sigma=True,
            channel_axis=None,
        ).astype(np.float32)
    if blur.detected:
        value = filters.unsharp_mask(value, radius=1.5, amount=1.0, preserve_range=True).astype(np.float32)
    if striping.detected:
        orientation = striping.measurements["orientation"]
        if orientation == "vertical":
            offsets = np.median(value, axis=0) - np.median(value)
            value = value - offsets[None, :]
        else:
            offsets = np.median(value, axis=1) - np.median(value)
            value = value - offsets[:, None]
    return np.clip(value, 0, 1).astype(np.float32)


def _write_restored_raster(source_path: Path, destination: Path, restored_sample: np.ndarray) -> None:
    """Write a georeferenced float32 restored raster using source metadata.

    The source path, destination, and normalized restored sample are inputs.
    The function returns nothing and creates a GeoTIFF that preserves CRS and
    bounds, resizing the sample to source dimensions when EDA was downsampled.
    """

    with rasterio.open(source_path) as source:
        profile = source.profile.copy()
        profile.update(dtype="float32", count=1, nodata=None, compress="deflate")
        if restored_sample.shape != (source.height, source.width):
            zoom = (source.height / restored_sample.shape[0], source.width / restored_sample.shape[1])
            restored_sample = ndimage.zoom(restored_sample, zoom, order=1)
            restored_sample = restored_sample[: source.height, : source.width]
        with rasterio.open(destination, "w", **profile) as target:
            target.write(restored_sample.astype(np.float32), 1)


def analyze(job_id: str, user_id: str, input_path: str, options: dict[str, Any]) -> dict[str, Any]:
    """Run the full PlanetIR pipeline and return schema-validated JSON.

    Worker-supplied job/user IDs, an already resolved upload path, and Tool
    Valve options are inputs. The output is the single deterministic result
    consumed by Celery, the audit trail, and the OpenWebUI adapter.
    """

    settings = get_settings()
    started = time.perf_counter()
    try:
        source_path = resolve_below(input_path, settings.upload_root)
    except ValueError:
        # LangGraph may pass the validated ISIS3 artifact from SACAI_OUTPUT_ROOT.
        # External job submission still accepts only UPLOAD_ROOT in api.py.
        source_path = resolve_below(input_path, settings.output_root)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if source_path.stat().st_size > settings.max_input_bytes:
        raise ValueError("input exceeds configured SACAI_MAX_INPUT_BYTES")
    mode = str(options.get("mode", "analyze")).lower()
    if mode not in {"analyze", "restore"}:
        raise ValueError("mode must be analyze or restore")

    output_dir = resolve_below(str(settings.output_root / user_id / job_id), settings.output_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    max_pixels = max(10_000, min(int(options.get("max_sample_pixels", settings.max_sample_pixels)), settings.max_sample_pixels))
    bins = int(options.get("histogram_bins", settings.histogram_bins))
    noise_threshold = float(options.get("noise_threshold", settings.noise_threshold))
    blur_threshold = float(options.get("blur_threshold", settings.blur_threshold))
    stripe_threshold = float(options.get("stripe_threshold", settings.stripe_threshold))
    if not 2 <= bins <= 4096:
        raise ValueError("histogram_bins must be between 2 and 4096")
    if not all(0 <= value <= 1 for value in (noise_threshold, blur_threshold, stripe_threshold)):
        raise ValueError("all detection thresholds must be between zero and one")

    with rasterio.open(source_path) as dataset:
        metadata = _metadata(dataset)
        sample = _sample_dataset(dataset, max_pixels)

    statistics = _statistics(sample)
    primary = _normalized_primary(sample)
    histogram, artifacts = _save_visuals(primary, output_dir, bins)
    noise = _detect_noise(primary, noise_threshold)
    blur = _detect_blur(primary, blur_threshold)
    striping = _detect_striping(primary, stripe_threshold)
    restoration_outputs: dict[str, str] = {}
    if mode == "restore":
        restored = _restore_image(primary, noise, blur, striping)
        restored_path = output_dir / "restored.tif"
        _write_restored_raster(source_path, restored_path, restored)
        artifacts.append(_artifact(restored_path, "image/tiff"))
        restoration_outputs["combined"] = restored_path.name
        restoration_outputs["scope"] = "band_1_robustly_normalized"
        restoration_outputs["noise"] = "wavelet_denoising" if noise.detected else "not_applied"
        restoration_outputs["blur"] = "unsharp_mask" if blur.detected else "not_applied"
        restoration_outputs["striping"] = "median_line_offset_correction" if striping.detected else "not_applied"

    result = PlanetIRResult(
        job_id=job_id,
        generated_at=datetime.now(timezone.utc),
        mode=mode,
        metadata=metadata,
        sampling={
            "source_pixels_all_bands": metadata.width * metadata.height * metadata.bands,
            "sampled_pixels_all_bands": int(sample.size),
            "sampled_width": int(sample.shape[2]),
            "sampled_height": int(sample.shape[1]),
            "method": (
                "full_resolution"
                if sample.shape[1:] == (metadata.height, metadata.width)
                else "average_resampling"
            ),
        },
        statistics=statistics,
        histogram=histogram,
        noise=noise,
        blur=blur,
        striping=striping,
        restoration=restoration_outputs,
        artifacts=artifacts,
        runtime_seconds=time.perf_counter() - started,
    )
    report_path = output_dir / "planetir_report.json"
    report_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    final = result.model_copy(update={"artifacts": [*artifacts, _artifact(report_path, "application/json")]})
    return PlanetIRResult.model_validate(final.model_dump()).model_dump(mode="json")
