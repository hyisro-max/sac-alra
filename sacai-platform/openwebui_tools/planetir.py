"""
title: PlanetIR
description: Queue deterministic GeoTIFF EDA, anomaly detection, and restoration without blocking chat.
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
    """Expose one PlanetIR orchestration entry point to the chat model."""

    class Valves(BaseModel):
        """Configure deployment-specific PlanetIR service and analysis limits."""

        service_url: str = Field(
            default="http://sacai-api:8000",
            description="Internal SACAI job API base URL.",
        )
        service_token: str = Field(
            default="replace-with-at-least-16-characters",
            description="Shared internal API token; set this before enabling the Tool.",
            json_schema_extra={"input": {"type": "password"}},
        )
        request_timeout_seconds: int = Field(default=30, ge=1, le=300)
        artifact_root: str = Field(
            default="/data/outputs",
            description="Read-only worker output root mounted in the OpenWebUI container.",
        )
        max_sample_pixels: int = Field(default=4_000_000, ge=10_000)
        histogram_bins: int = Field(default=256, ge=16, le=4096)
        noise_threshold: float = Field(default=0.08, ge=0, le=1)
        blur_threshold: float = Field(default=0.55, ge=0, le=1)
        stripe_threshold: float = Field(default=0.08, ge=0, le=1)

    class UserValves(BaseModel):
        """Allow a scientist to choose safe analysis versus restoration mode."""

        default_mode: Literal["analyze", "restore"] = "analyze"

    def __init__(self):
        """Initialize default Valves before OpenWebUI applies stored values."""

        self.valves = self.Valves()

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call the private job API and decode one JSON response.

        HTTP method/path and optional JSON body are inputs. The decoded mapping
        is returned to the public Tool method after service-side validation.
        """

        body = json.dumps(payload).encode() if payload is not None else None
        request = Request(
            f"{self.valves.service_url.rstrip('/')}{path}",
            data=body,
            method=method,
            headers={"Content-Type": "application/json", "X-SACAI-Token": self.valves.service_token},
        )
        try:
            with urlopen(request, timeout=self.valves.request_timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"SACAI service returned HTTP {error.code}: {detail}") from error
        except URLError as error:
            raise RuntimeError(f"SACAI service is unavailable: {error.reason}") from error

    @staticmethod
    def _choose_descriptor(__files__: list[dict[str, Any]], file_id: str) -> dict[str, Any]:
        """Choose one uploaded raster descriptor without accepting a path.

        Reserved OpenWebUI ``__files__`` and an optional record ID are inputs.
        The returned descriptor is either the exact ID match or the only TIFF;
        ambiguity is reported instead of guessed.
        """

        files = [item for item in (__files__ or []) if isinstance(item, dict)]
        if file_id:
            matches = [item for item in files if item.get("id") == file_id]
            if len(matches) == 1:
                return matches[0]
            raise ValueError("The requested file ID is not attached to this chat turn.")
        candidates = [
            item
            for item in files
            if Path(str(item.get("name") or "")).suffix.lower() in {".tif", ".tiff"}
            or str(item.get("content_type") or "").lower() in {"image/tiff", "image/geotiff"}
        ]
        if len(candidates) != 1:
            names = [str(item.get("name") or item.get("id")) for item in candidates]
            raise ValueError(f"Attach exactly one GeoTIFF for PlanetIR. Eligible files: {names}")
        return candidates[0]

    @staticmethod
    async def _resolve_file(descriptor: dict[str, Any], __user__: dict[str, Any]) -> tuple[Any, str]:
        """Resolve an OpenWebUI file ID through its model and Storage provider.

        The chosen descriptor and injected user are inputs. The returned file
        model and local storage path are obtained after OpenWebUI access checks.
        """

        from open_webui.models.files import Files
        from open_webui.models.users import Users
        from open_webui.storage.provider import Storage
        from open_webui.utils.access_control.files import has_access_to_file

        file_id = descriptor.get("id")
        if not file_id:
            raise ValueError("The attached upload has no OpenWebUI file ID.")
        record = await Files.get_file_by_id(file_id)
        if not record:
            raise FileNotFoundError("The attached OpenWebUI file record no longer exists.")
        user_id = str((__user__ or {}).get("id") or "")
        role = str((__user__ or {}).get("role") or "")
        if record.user_id != user_id and role != "admin":
            user = await Users.get_user_by_id(user_id)
            if not user or not await has_access_to_file(file_id, "read", user):
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
        """Register completed artifacts through OpenWebUI's upload handler.

        The successful job, injected request/user and event emitter are inputs.
        Returned file descriptors have database records and authenticated URLs,
        making them visible in Files and downloadable from the assistant message.
        """

        if job.get("published_files"):
            return job["published_files"]
        from open_webui.models.users import Users
        from open_webui.routers.files import upload_file_handler

        user = await Users.get_user_by_id(__user__["id"])
        if not user:
            raise PermissionError("The OpenWebUI user no longer exists.")
        descriptors: list[dict[str, Any]] = []
        artifacts = (job.get("result") or {}).get("artifacts", [])
        for artifact in artifacts:
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
            is_image = content_type.startswith("image/") and content_type != "image/tiff"
            descriptors.append(
                {
                    "id": registered.id,
                    "type": "image" if is_image else "file",
                    "name": registered.filename,
                    "url": f"/api/v1/files/{registered.id}/content",
                    "content_type": content_type,
                    "size": registered.meta.get("size") if registered.meta else None,
                }
            )
        path = f"/v1/jobs/{quote(job['job_id'])}/publication"
        await asyncio.to_thread(
            self._request,
            "POST",
            path,
            {"user_id": __user__["id"], "files": descriptors},
        )
        if __event_emitter__ and descriptors:
            await __event_emitter__({"type": "files", "data": {"files": descriptors}})
        return descriptors

    @staticmethod
    def _sha256(path: Path) -> str:
        """Hash one worker artifact before OpenWebUI copies it into storage."""

        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    async def planetir(
        self,
        action: Literal["submit", "status", "cancel"] = "submit",
        job_id: str = "",
        file_id: str = "",
        mode: Literal["analyze", "restore"] | None = None,
        __files__: list[dict[str, Any]] = [],
        __user__: dict[str, Any] = {},
        __request__: Any = None,
        __event_emitter__: Any = None,
        __metadata__: dict[str, Any] = {},
    ) -> dict[str, Any]:
        """Queue or inspect one deterministic PlanetIR GeoTIFF analysis.

        Use ``submit`` with one attached GeoTIFF; no filepath is accepted. The
        method returns a job ID immediately. Use ``status`` with that ID until
        it succeeds, at which point reports/images are registered in OpenWebUI
        Files and attached to the response. Use ``cancel`` to stop owned work.

        :param action: submit, status, or cancel.
        :param job_id: Job ID previously returned by submit; required for status/cancel.
        :param file_id: Optional attached OpenWebUI file ID; omit when exactly one GeoTIFF is attached.
        :param mode: analyze for non-destructive EDA/detection or restore to also create a restored GeoTIFF.
        :return: Queued job identity, current status, deterministic result JSON, and registered output files.
        """

        if not (__user__ or {}).get("id"):
            raise PermissionError("PlanetIR requires an authenticated OpenWebUI user.")
        if action not in {"submit", "status", "cancel"}:
            raise ValueError("action must be submit, status, or cancel.")
        if action == "submit":
            descriptor = self._choose_descriptor(__files__, file_id)
            record, resolved_path = await self._resolve_file(descriptor, __user__)
            correlation_id = str((__metadata__ or {}).get("message_id") or uuid4())
            user_mode = getattr((__user__ or {}).get("valves"), "default_mode", "analyze")
            selected_mode = mode or user_mode or "analyze"
            payload = {
                "kind": "planetir",
                "user_id": __user__["id"],
                "input_file_id": record.id,
                "input_path": resolved_path,
                "original_name": record.filename,
                "correlation_id": correlation_id,
                "options": {
                    "mode": selected_mode,
                    "max_sample_pixels": self.valves.max_sample_pixels,
                    "histogram_bins": self.valves.histogram_bins,
                    "noise_threshold": self.valves.noise_threshold,
                    "blur_threshold": self.valves.blur_threshold,
                    "stripe_threshold": self.valves.stripe_threshold,
                },
            }
            return await asyncio.to_thread(self._request, "POST", "/v1/jobs", payload)
        if not job_id:
            raise ValueError("job_id is required for status or cancel.")
        path = f"/v1/jobs/{quote(job_id)}?{urlencode({'user_id': __user__['id']})}"
        job = await asyncio.to_thread(self._request, "GET" if action == "status" else "DELETE", path)
        if action == "status" and job.get("status") == "succeeded":
            job["files"] = await self._publish(job, __request__, __user__, __event_emitter__)
        return job
