"""Validated API and scientific-result schemas shared by SACAI components."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class JobSubmit(BaseModel):
    """Describe one immutable queued job submitted by an OpenWebUI Tool.

    ``input_path`` is produced by the trusted Tool after resolving ``__files__``;
    it is never supplied by the model. The schema returns normalized job input
    to the API and then to a routed worker.
    """

    kind: Literal["planetir", "isis3", "workflow", "lunar_dem", "orthorectify", "superres"]
    user_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    input_file_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    input_path: str = Field(min_length=1)
    original_name: str = Field(min_length=1, max_length=512)
    correlation_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    options: dict[str, Any] = Field(default_factory=dict)
    # Required for "lunar_dem" (the right stereo-pair image) and
    # "orthorectify" (the DEM to orthorectify against); ignored otherwise.
    # A second trusted, Tool-resolved path -- never a model-supplied one --
    # validated the same way input_path is, so it needs its own field rather
    # than living inside the free-form options mapping.
    secondary_input_file_id: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"
    )
    secondary_input_path: str | None = Field(default=None, min_length=1)
    secondary_original_name: str | None = Field(default=None, min_length=1, max_length=512)


class Artifact(BaseModel):
    """Describe one worker-created file that is safe for later publication.

    A worker supplies the absolute path and MIME type; the API validates this
    record before a Tool can register the file in OpenWebUI.
    """

    path: str
    name: str = Field(min_length=1, max_length=512)
    content_type: str = Field(min_length=1, max_length=128)
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BandStatistics(BaseModel):
    """Hold deterministic per-band statistics emitted by PlanetIR.

    All values come from raster pixels. Nullable floating fields represent an
    empty/all-nodata band and prevent an LLM from filling missing values.
    """

    band: int = Field(ge=1)
    count: int = Field(ge=0)
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    standard_deviation: float | None = Field(default=None, ge=0)
    median: float | None = None
    percentile_2: float | None = None
    percentile_98: float | None = None


class DegradationScore(BaseModel):
    """Represent one bounded anomaly score and its deterministic evidence.

    The output is embedded in ``PlanetIRResult`` and prevents negative or
    greater-than-one severity values from reaching the model.
    """

    detected: bool
    severity_0_to_1: float = Field(ge=0, le=1)
    label: Literal["none", "low", "moderate", "high"]
    measurements: dict[str, float | int | str | None]


class RasterMetadata(BaseModel):
    """Hold exact geospatial metadata read from a raster dataset header.

    This object is part of every PlanetIR result and carries dimensions, data
    types, CRS, transform, bounds and nodata without model interpretation.
    """

    driver: str
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    bands: int = Field(ge=1)
    dtypes: list[str]
    crs: str | None
    transform: list[float] = Field(min_length=6, max_length=9)
    bounds: list[float] = Field(min_length=4, max_length=4)
    resolution: list[float] = Field(min_length=2, max_length=2)
    nodata: float | None
    tags: dict[str, str]


class SamplingInfo(BaseModel):
    """State exactly how bounded PlanetIR EDA pixels were selected.

    Source/sample dimensions and method are output fields. They prevent sampled
    statistics or histograms from being mistaken for full-resolution values.
    """

    source_pixels_all_bands: int = Field(ge=1)
    sampled_pixels_all_bands: int = Field(ge=1)
    sampled_width: int = Field(ge=1)
    sampled_height: int = Field(ge=1)
    method: Literal["full_resolution", "average_resampling"]
    statistics_scope: Literal["all_bands_bounded_sample"] = "all_bands_bounded_sample"
    histogram_scope: Literal["band_1_bounded_sample"] = "band_1_bounded_sample"


class PlanetIRResult(BaseModel):
    """Validate the complete deterministic PlanetIR output before exposure.

    Workers return this schema plus artifact files. It is the source of truth
    for scientific numbers later summarized by the chat model.
    """

    schema_version: Literal["1.0"] = "1.0"
    job_id: str
    generated_at: datetime
    mode: Literal["analyze", "restore"]
    metadata: RasterMetadata
    sampling: SamplingInfo
    statistics: list[BandStatistics]
    histogram: dict[str, list[float | int]]
    noise: DegradationScore
    blur: DegradationScore
    striping: DegradationScore
    restoration: dict[str, str]
    artifacts: list[Artifact]
    runtime_seconds: float = Field(ge=0)

    @field_validator("histogram")
    @classmethod
    def validate_histogram(cls, value: dict[str, list[float | int]]) -> dict[str, list[float | int]]:
        """Require matching histogram counts and bin-edge lengths.

        The validator receives the histogram mapping and returns it unchanged
        after checking the deterministic EDA contract.
        """

        counts = value.get("counts", [])
        edges = value.get("bin_edges", [])
        if not counts or len(edges) != len(counts) + 1:
            raise ValueError("histogram requires N counts and N+1 bin edges")
        return value


class JobAccepted(BaseModel):
    """Return the durable identifier and queue chosen for a new job."""

    job_id: str
    correlation_id: str
    status: Literal["queued"] = "queued"
    queue: str


class JobStatus(BaseModel):
    """Return ownership-safe Celery status and validated result data."""

    job_id: str
    correlation_id: str
    kind: Literal["planetir", "isis3", "workflow", "notebook", "lunar_dem", "orthorectify", "superres"]
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    result: dict[str, Any] | None = None
    error: str | None = None
    published_files: list[dict[str, Any]] = Field(default_factory=list)


class PublicationRecord(BaseModel):
    """Persist OpenWebUI file descriptors created for completed artifacts."""

    user_id: str = Field(min_length=1)
    files: list[dict[str, Any]]


class RemoteNotebookSubmit(BaseModel):
    """Validate one allowlisted remote Jupyter execution request.

    The Tool supplies the server/profile settings and selected notebook path;
    the model can supply only the friendly code name and product ID. The API
    passes this record to the isolated notebook queue without persisting or
    auditing ``server_token``.
    """

    user_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    correlation_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    server_url: str = Field(min_length=8, max_length=2048)
    server_token: str = Field(default="", repr=False)
    code_name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    notebook_path: str = Field(min_length=6, max_length=1024)
    kernel_name: str = Field(default="python3", min_length=1, max_length=128)
    product_id: str = Field(min_length=1, max_length=512)
    verify_tls: bool = True
    execution_timeout_seconds: int = Field(default=1800, ge=30, le=7200)
    max_output_chars: int = Field(default=100_000, ge=1000, le=1_000_000)
    max_notebook_bytes: int = Field(default=5_000_000, ge=10_000, le=50_000_000)
    max_code_cells: int = Field(default=200, ge=1, le=1000)

    @field_validator("server_url")
    @classmethod
    def validate_server_url(cls, value: str) -> str:
        """Accept only a plain HTTP(S) Jupyter base URL without credentials."""

        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("server_url must be an http:// or https:// URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("server_url cannot contain credentials, query parameters, or a fragment")
        return value.rstrip("/")

    @field_validator("notebook_path")
    @classmethod
    def validate_notebook_path(cls, value: str) -> str:
        """Require one relative allowlisted notebook path without traversal."""

        normalized = value.strip().lstrip("/")
        if not normalized.endswith(".ipynb") or any(part in {"", ".", ".."} for part in normalized.split("/")):
            raise ValueError("notebook_path must be a relative .ipynb path without traversal")
        return normalized


class RemoteNotebookResult(BaseModel):
    """Validate bounded notebook output before it reaches chat or audit."""

    schema_version: Literal["1.0"] = "1.0"
    job_id: str = Field(min_length=1, max_length=128)
    code_name: str = Field(min_length=1, max_length=128)
    notebook_path: str = Field(min_length=6, max_length=1024)
    product_id: str = Field(min_length=1, max_length=512)
    kernel_name: str = Field(min_length=1, max_length=128)
    cells_executed: int = Field(ge=0, le=1000)
    cell_outputs: list[dict[str, Any]]
    runtime_seconds: float = Field(ge=0)
    artifacts: list[Artifact]

    @field_validator("product_id")
    @classmethod
    def validate_product_id(cls, value: str) -> str:
        """Reject control characters while retaining real catalog ID punctuation."""

        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("product_id cannot contain control characters")
        normalized = value.strip()
        if not normalized:
            raise ValueError("product_id cannot be blank")
        return normalized


class CleanupRequest(BaseModel):
    """Request a safe cleanup preview or execute an approved preview."""

    action: Literal["preview", "execute"]
    user_id: str
    user_role: str
    older_than_hours: int = Field(ge=1)
    preview_token: str | None = None
    openwebui_file_ids: list[str] = Field(default_factory=list)


class CleanupResult(BaseModel):
    """Return exact cleanup targets, token, and execution outcome."""

    action: Literal["preview", "execute"]
    preview_token: str
    expires_at: datetime
    targets: list[str]
    deleted: list[str]
    openwebui_file_ids: list[str] = Field(default_factory=list)

class CatalogSearchHit(BaseModel):
    """Return one ISIS application matched by a catalog search query."""

    name: str
    brief: str | None
    category: list[str]


class CatalogEntry(BaseModel):
    """Return the full catalog record for one named ISIS application."""

    name: str
    brief: str | None
    category: list[str]
    parameters: list[dict[str, Any]]