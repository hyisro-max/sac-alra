"""
title: SACAI Scientific Workflow
description: Queue checkpointed optional-ISIS preprocessing followed by PlanetIR and report generation.
author: SACAI
version: 1.0.0
"""

import asyncio
import hashlib
import json
import mimetypes
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from fastapi import UploadFile
from pydantic import BaseModel, Field
from starlette.datastructures import Headers


class Tools:
    """Expose one queued LangGraph scientific workflow entry point."""

    class Valves(BaseModel):
        """Configure the job service, publication root, and safe analysis limits."""

        service_url: str = Field(default="http://sacai-api:8000", description="Internal SACAI API base URL.")
        service_token: str = Field(
            default="replace-with-at-least-16-characters",
            description="Shared internal API token.",
            json_schema_extra={"input": {"type": "password"}},
        )
        request_timeout_seconds: int = Field(default=30, ge=1, le=300)
        artifact_root: str = Field(default="/data/outputs", description="Read-only worker publication root.")
        max_sample_pixels: int = Field(default=4_000_000, ge=10_000)
        histogram_bins: int = Field(default=256, ge=16, le=4096)
        noise_threshold: float = Field(default=0.08, ge=0, le=1)
        blur_threshold: float = Field(default=0.55, ge=0, le=1)
        stripe_threshold: float = Field(default=0.08, ge=0, le=1)

    def __init__(self):
        """Initialize default workflow Valves before stored values are applied."""

        self.valves = self.Valves()

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call the private job API and return its decoded JSON mapping."""

        request = Request(
            f"{self.valves.service_url.rstrip('/')}{path}",
            data=json.dumps(payload).encode() if payload is not None else None,
            method=method,
            headers={"Content-Type": "application/json", "X-SACAI-Token": self.valves.service_token},
        )
        try:
            with urlopen(request, timeout=self.valves.request_timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise RuntimeError(f"SACAI service returned HTTP {error.code}: {error.read().decode()}") from error
        except URLError as error:
            raise RuntimeError(f"SACAI service is unavailable: {error.reason}") from error

    @staticmethod
    def _choose(__files__: list[dict[str, Any]], file_id: str) -> dict[str, Any]:
        """Select one attached product by ID or require an unambiguous upload."""

        files = [item for item in (__files__ or []) if isinstance(item, dict)]
        matches = [item for item in files if item.get("id") == file_id] if file_id else files
        if len(matches) != 1:
            raise ValueError("Attach exactly one raw product or ready GeoTIFF, or provide its attached file ID.")
        return matches[0]

    @staticmethod
    async def _resolve(descriptor: dict[str, Any], __user__: dict[str, Any]) -> tuple[Any, str]:
        """Authorize one attached file and resolve it through OpenWebUI Storage."""

        from open_webui.models.files import Files
        from open_webui.models.users import Users
        from open_webui.storage.provider import Storage
        from open_webui.utils.access_control.files import has_access_to_file

        record = await Files.get_file_by_id(descriptor.get("id"))
        if not record:
            raise FileNotFoundError("The attached OpenWebUI file record no longer exists.")
        if record.user_id != __user__.get("id") and __user__.get("role") != "admin":
            user = await Users.get_user_by_id(str(__user__.get("id") or ""))
            if not user or not await has_access_to_file(record.id, "read", user):
                raise PermissionError("The current user cannot read the attached file.")
        path = await asyncio.to_thread(Storage.get_file, record.path)
        return record, str(Path(path).resolve())

    async def _publish(
        self,
        job: dict[str, Any],
        __request__: Any,
        __user__: dict[str, Any],
        __event_emitter__: Any,
    ) -> list[dict[str, Any]]:
        """Register workflow artifacts as owner-visible OpenWebUI Files records."""

        if job.get("published_files"):
            return job["published_files"]
        from open_webui.models.users import Users
        from open_webui.routers.files import upload_file_handler

        user = await Users.get_user_by_id(__user__["id"])
        if not user:
            raise PermissionError("The OpenWebUI user no longer exists.")
        descriptors: list[dict[str, Any]] = []
        for artifact in (job.get("result") or {}).get("artifacts", []):
            path = Path(str(artifact.get("path") or "")).resolve()
            try:
                path.relative_to(Path(self.valves.artifact_root).resolve())
            except ValueError as error:
                raise PermissionError("Worker artifact is outside the configured publication root.") from error
            if not path.is_file():
                raise FileNotFoundError(f"Worker artifact is missing: {path.name}")
            digest = await asyncio.to_thread(self._sha256, path)
            if digest != artifact.get("sha256") or path.stat().st_size != artifact.get("size"):
                raise ValueError(f"Worker artifact integrity check failed: {path.name}")
            content_type = str(artifact.get("content_type") or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            with path.open("rb") as source:
                upload = UploadFile(
                    file=source,
                    filename=str(artifact.get("name") or path.name),
                    headers=Headers({"content-type": content_type}),
                )
                registered = await upload_file_handler(
                    __request__,
                    file=upload,
                    metadata={
                        "sacai_job_id": job["job_id"],
                        "sacai_correlation_id": job["correlation_id"],
                        "artifact_sha256": artifact.get("sha256"),
                    },
                    process=False,
                    process_in_background=False,
                    user=user,
                )
            is_inline = content_type.startswith("image/") and content_type != "image/tiff"
            descriptors.append(
                {
                    "id": registered.id,
                    "type": "image" if is_inline else "file",
                    "name": registered.filename,
                    "url": f"/api/v1/files/{registered.id}/content",
                    "content_type": content_type,
                    "size": registered.meta.get("size") if registered.meta else None,
                }
            )
        await asyncio.to_thread(
            self._request,
            "POST",
            f"/v1/jobs/{quote(job['job_id'])}/publication",
            {"user_id": __user__["id"], "files": descriptors},
        )
        if __event_emitter__ and descriptors:
            await __event_emitter__({"type": "files", "data": {"files": descriptors}})
        return descriptors

    @staticmethod
    def _sha256(path: Path) -> str:
        """Hash one workflow artifact before OpenWebUI copies it into storage."""

        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    async def scientific_workflow(
        self,
        action: Literal["submit", "status", "cancel"] = "submit",
        job_id: str = "",
        file_id: str = "",
        already_calibrated: bool = False,
        mode: Literal["analyze", "restore"] = "analyze",
        __files__: list[dict[str, Any]] = [],
        __user__: dict[str, Any] = {},
        __metadata__: dict[str, Any] = {},
        __request__: Any = None,
        __event_emitter__: Any = None,
    ) -> dict[str, Any]:
        """Queue or inspect optional ISIS3 → PlanetIR → report orchestration.

        Submit with one attached raw product or GeoTIFF; a TIFF automatically
        skips ISIS. The graph is checkpointed and heavy steps run on a capped
        worker queue. Status publishes completed artifacts through OpenWebUI.

        :param action: submit, status, or cancel.
        :param job_id: Workflow job ID returned by submit.
        :param file_id: Optional ID of one attached input file.
        :param already_calibrated: True only for a calibrated/projected non-TIFF input that should skip ISIS.
        :param mode: Analyze or also create PlanetIR restoration output.
        :return: Queued identity or checkpointed deterministic workflow result and registered files.
        """

        if not __user__.get("id"):
            raise PermissionError("The scientific workflow requires an authenticated OpenWebUI user.")
        if action not in {"submit", "status", "cancel"}:
            raise ValueError("action must be submit, status, or cancel.")
        if action == "submit":
            descriptor = self._choose(__files__, file_id)
            record, resolved_path = await self._resolve(descriptor, __user__)
            ready = already_calibrated or Path(record.filename).suffix.lower() in {".tif", ".tiff"}
            return await asyncio.to_thread(
                self._request,
                "POST",
                "/v1/jobs",
                {
                    "kind": "workflow",
                    "user_id": __user__["id"],
                    "input_file_id": record.id,
                    "input_path": resolved_path,
                    "original_name": record.filename,
                    "correlation_id": str(__metadata__.get("message_id") or uuid4()),
                    "options": {
                        "already_calibrated": ready,
                        "mode": mode,
                        "max_sample_pixels": self.valves.max_sample_pixels,
                        "histogram_bins": self.valves.histogram_bins,
                        "noise_threshold": self.valves.noise_threshold,
                        "blur_threshold": self.valves.blur_threshold,
                        "stripe_threshold": self.valves.stripe_threshold,
                    },
                },
            )
        if not job_id:
            raise ValueError("job_id is required for status or cancel.")
        path = f"/v1/jobs/{quote(job_id)}?{urlencode({'user_id': __user__['id']})}"
        job = await asyncio.to_thread(self._request, "GET" if action == "status" else "DELETE", path)
        if action == "status" and job.get("status") == "succeeded":
            job["files"] = await self._publish(job, __request__, __user__, __event_emitter__)
        return job
