"""
title: ISIS3 Preprocess
description: Optionally queue raw planetary product calibration and map projection before PlanetIR.
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
    """Expose one optional ISIS3 preprocessing entry point to the model."""

    class Valves(BaseModel):
        """Configure the private job API used by the ISIS3 adapter."""

        service_url: str = Field(default="http://sacai-api:8000", description="Internal SACAI job API base URL.")
        service_token: str = Field(
            default="replace-with-at-least-16-characters",
            description="Shared internal API token.",
            json_schema_extra={"input": {"type": "password"}},
        )
        request_timeout_seconds: int = Field(default=30, ge=1, le=300)
        artifact_root: str = Field(
            default="/data/outputs",
            description="Read-only worker output root mounted in the OpenWebUI container.",
        )

    def __init__(self):
        """Initialize default ISIS3 Valves before stored values are applied."""

        self.valves = self.Valves()

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call the internal job API and return its decoded JSON mapping."""

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
        """Select one raw attached product descriptor and reject ambiguity.

        The reserved file list and optional ID are inputs. A descriptor is
        returned without ever asking the model for a stored path.
        """

        files = [item for item in (__files__ or []) if isinstance(item, dict)]
        matches = [item for item in files if item.get("id") == file_id] if file_id else files
        if len(matches) != 1:
            raise ValueError("Attach exactly one raw PDS/IMG/ISIS product or provide its attached file ID.")
        return matches[0]

    @staticmethod
    async def _resolve(descriptor: dict[str, Any], __user__: dict[str, Any]) -> tuple[Any, str]:
        """Resolve and authorize an attached raw file through OpenWebUI storage."""

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
        return record, str(Path(await asyncio.to_thread(Storage.get_file, record.path)).resolve())

    async def _publish(
        self,
        job: dict[str, Any],
        __request__: Any,
        __user__: dict[str, Any],
        __event_emitter__: Any,
    ) -> list[dict[str, Any]]:
        """Register a successful ISIS GeoTIFF through OpenWebUI file storage.

        Job data and injected request/user/event objects are inputs. The output
        file descriptor is database-backed, downloadable, and visible in Files.
        """

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
            content_type = str(artifact.get("content_type") or mimetypes.guess_type(path.name)[0] or "image/tiff")
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
            descriptors.append(
                {
                    "id": registered.id,
                    "type": "file",
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
        """Hash one ISIS artifact before OpenWebUI copies it into storage."""

        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    async def isis3_preprocess(
        self,
        action: Literal["submit", "status", "cancel"] = "submit",
        job_id: str = "",
        file_id: str = "",
        already_calibrated: bool = False,
        __files__: list[dict[str, Any]] = [],
        __user__: dict[str, Any] = {},
        __metadata__: dict[str, Any] = {},
        __request__: Any = None,
        __event_emitter__: Any = None,
    ) -> dict[str, Any]:
        """Queue or inspect optional ISIS3 preprocessing of one raw product.

        Use only for raw PDS/IMG/ISIS input. Set ``already_calibrated`` true for
        a ready GeoTIFF; the Tool will refuse to reprocess it. Submit returns a
        job ID immediately; status and cancel require that ID.

        :param action: submit, status, or cancel.
        :param job_id: Job ID returned by submit.
        :param file_id: Optional ID of one attached raw file.
        :param already_calibrated: True when the source is already calibrated/projected, which makes ISIS3 skip safely.
        :return: Queued job identity or current deterministic preprocessing status/result.
        """

        if not __user__.get("id"):
            raise PermissionError("ISIS3 preprocessing requires an authenticated OpenWebUI user.")
        if action not in {"submit", "status", "cancel"}:
            raise ValueError("action must be submit, status, or cancel.")
        if action == "submit":
            descriptor = self._choose(__files__, file_id)
            if already_calibrated or Path(str(descriptor.get("name") or "")).suffix.lower() in {".tif", ".tiff"}:
                return {"status": "skipped", "reason": "Input is already a GeoTIFF; run PlanetIR directly."}
            record, resolved_path = await self._resolve(descriptor, __user__)
            return await asyncio.to_thread(
                self._request,
                "POST",
                "/v1/jobs",
                {
                    "kind": "isis3",
                    "user_id": __user__["id"],
                    "input_file_id": record.id,
                    "input_path": resolved_path,
                    "original_name": record.filename,
                    "correlation_id": str(__metadata__.get("message_id") or uuid4()),
                    "options": {"already_calibrated": already_calibrated},
                },
            )
        if not job_id:
            raise ValueError("job_id is required for status or cancel.")
        path = f"/v1/jobs/{quote(job_id)}?{urlencode({'user_id': __user__['id']})}"
        job = await asyncio.to_thread(self._request, "GET" if action == "status" else "DELETE", path)
        if action == "status" and job.get("status") == "succeeded":
            job["files"] = await self._publish(job, __request__, __user__, __event_emitter__)
        return job
