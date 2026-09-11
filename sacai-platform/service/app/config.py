"""Environment-backed settings for the SACAI API and workers."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Load deployment settings and validate shared storage boundaries.

    Inputs come from ``SACAI_*`` environment variables. The resulting object
    configures the API, Celery, audit store, resource quotas, and safe roots
    used by every worker in the scientific pipeline.
    """

    model_config = SettingsConfigDict(env_prefix="SACAI_", extra="ignore")

    internal_token: str = Field(min_length=16)
    redis_url: str = "redis://redis:6379/0"
    result_backend_url: str = "redis://redis:6379/1"
    upload_root: Path = Path("/app/backend/data/uploads")
    output_root: Path = Path("/data/outputs")
    tool_versions_root: Path = Path("/data/tool_versions")
    audit_db_path: Path = Path("/data/audit/sacai-audit.sqlite3")
    graph_db_path: Path = Path("/data/audit/sacai-graphs.sqlite3")
    max_input_bytes: int = Field(default=10 * 1024**3, ge=1)
    max_sample_pixels: int = Field(default=4_000_000, ge=10_000)
    histogram_bins: int = Field(default=256, ge=16, le=4096)
    noise_threshold: float = Field(default=0.08, ge=0, le=1)
    blur_threshold: float = Field(default=0.55, ge=0, le=1)
    stripe_threshold: float = Field(default=0.08, ge=0, le=1)
    max_queued_jobs: int = Field(default=100, ge=1)
    max_user_jobs: int = Field(default=5, ge=1)
    planetir_queue: str = "planetir_cpu"
    isis_queue: str = "isis_cpu"
    maintenance_queue: str = "maintenance"
    notebook_queue: str = "notebook_remote"
    dem_queue: str = "asp_cpu"
    otb_queue: str = "otb_cpu"
    ch2_queue: str = "ch2_cpu"
    superres_queue: str = "superres_cpu"
    job_soft_time_limit_seconds: int = Field(default=3300, ge=60)
    job_time_limit_seconds: int = Field(default=3600, ge=60)
    isis_soft_time_limit_seconds: int = Field(default=6900, ge=60)
    isis_time_limit_seconds: int = Field(default=7200, ge=60)
    notebook_soft_time_limit_seconds: int = Field(default=3900, ge=60)
    notebook_time_limit_seconds: int = Field(default=4200, ge=60)
    dem_soft_time_limit_seconds: int = Field(default=10800, ge=60)
    dem_time_limit_seconds: int = Field(default=12000, ge=60)
    otb_soft_time_limit_seconds: int = Field(default=3300, ge=60)
    otb_time_limit_seconds: int = Field(default=3600, ge=60)
    superres_soft_time_limit_seconds: int = Field(default=3300, ge=60)
    superres_time_limit_seconds: int = Field(default=3600, ge=60)
    cleanup_preview_ttl_seconds: int = Field(default=900, ge=60)
    cleanup_min_age_hours: int = Field(default=168, ge=1)
    isis_command: str = ""
    asp_command: str = ""
    otb_command: str = ""
    superres_command: str = ""
    isis_catalog_path: Path = Path("/opt/sacai/isis_catalog.json")

    @field_validator("internal_token")
    @classmethod
    def reject_placeholder_token(cls, value: str) -> str:
        """Reject the documented placeholder before any private API starts.

        The configured token is the input. A non-placeholder token is returned;
        an unchanged example value stops startup rather than weakening auth.
        """

        if value.startswith("replace-with"):
            raise ValueError("SACAI_INTERNAL_TOKEN must be replaced with a deployment secret")
        return value

    def prepare_directories(self) -> None:
        """Create writable service directories before API or worker use.

        The method has no input and returns nothing. It sits at process startup
        so later job code can assume the configured output and audit parents
        exist without creating paths outside the approved roots.
        """

        self.output_root.mkdir(parents=True, exist_ok=True)
        self.tool_versions_root.mkdir(parents=True, exist_ok=True)
        self.audit_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.graph_db_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Return one validated settings instance for the current process.

    There are no inputs. The cached output is used by API routes, Celery tasks,
    and deterministic processors so all components share identical limits.
    """

    settings = Settings()
    settings.prepare_directories()
    return settings
