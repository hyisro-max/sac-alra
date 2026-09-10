"""
title: SACAI Jupyter Runtime
description: Queue an allowlisted remote Jupyter notebook for one product ID.
author: SACAI
version: 1.0.0
"""

import asyncio
import hashlib
import json
import mimetypes
import ssl
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from fastapi import UploadFile
from pydantic import BaseModel, Field
from starlette.datastructures import Headers


class Tools:
    """Expose one safe remote-notebook orchestration method to the model."""

    class Valves(BaseModel):
        """Configure the private job API and one Jupyter runtime profile."""

        service_url: str = Field(default="http://sacai-api:8000", description="Internal SACAI job API URL.")
        service_token: str = Field(
            default="replace-with-at-least-16-characters",
            description="Shared SACAI internal API token.",
            json_schema_extra={"input": {"type": "password"}},
        )
        jupyter_server_url: str = Field(
            default="",
            description="Jupyter Server base URL reachable from SACAI containers.",
        )
        jupyter_server_token: str = Field(
            default="",
            description="Jupyter API token, if authentication is enabled.",
            json_schema_extra={"input": {"type": "password"}},
        )
        verify_tls: bool = Field(default=True, description="Verify an HTTPS Jupyter server certificate.")
        allowed_notebooks: dict[str, str] = Field(
            default_factory=dict,
            description='Allowlist mapping friendly code names to relative .ipynb paths, e.g. {"tmc_stats":"notebooks/tmc_stats.ipynb"}.',
        )
        kernel_name: str = Field(default="python3", description="Jupyter kernelspec used for submitted notebooks.")
        request_timeout_seconds: int = Field(default=30, ge=1, le=300)
        execution_timeout_seconds: int = Field(default=1800, ge=30, le=7200)
        max_output_chars: int = Field(default=100_000, ge=1000, le=1_000_000)
        max_notebook_bytes: int = Field(default=5_000_000, ge=10_000, le=50_000_000)
        max_code_cells: int = Field(default=200, ge=1, le=1000)
        artifact_root: str = Field(default="/data/outputs", description="Worker output root mounted read-only in OpenWebUI.")

    def __init__(self):
        """Initialize default Valves before OpenWebUI applies stored values."""

        self.valves = self.Valves()

    def _service_request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call the private SACAI job API and return one decoded response."""

        request = Request(
            f"{self.valves.service_url.rstrip('/')}{path}",
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
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

    def _check_jupyter(self) -> dict[str, Any]:
        """Check the configured Jupyter REST API without exposing its token."""

        parsed = urlsplit(self.valves.jupyter_server_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("jupyter_server_url must use http:// or https://")
        headers = {"Accept": "application/json"}
        if self.valves.jupyter_server_token:
            headers["Authorization"] = f"token {self.valves.jupyter_server_token}"
        context = None
        if parsed.scheme == "https" and not self.valves.verify_tls:
            context = ssl._create_unverified_context()
        request = Request(urljoin(self.valves.jupyter_server_url.rstrip("/") + "/", "api"), headers=headers)
        try:
            with urlopen(request, timeout=self.valves.request_timeout_seconds, context=context) as response:
                result = json.loads(response.read(100_000).decode("utf-8"))
                return {"status": "ok", "jupyter_version": result.get("version")}
        except HTTPError as error:
            raise RuntimeError(f"Jupyter connectivity check returned HTTP {error.code}") from error
        except URLError as error:
            raise RuntimeError(f"Jupyter server is unavailable: {error.reason}") from error

    @staticmethod
    def _notebook_path(code_name: str, allowed: dict[str, str]) -> str:
        """Resolve one exact friendly code name to a safe allowlisted path."""

        if code_name not in allowed:
            raise ValueError(f"Unknown code_name '{code_name}'. Allowed names: {sorted(allowed)}")
        path = str(allowed[code_name]).strip().lstrip("/")
        if not path.endswith(".ipynb") or any(part in {"", ".", ".."} for part in path.split("/")):
            raise ValueError(f"Valve path for '{code_name}' must be a relative .ipynb path without traversal")
        return path

    async def _publish(
        self,
        job: dict[str, Any],
        __request__: Any,
        __user__: dict[str, Any],
        __event_emitter__: Any,
    ) -> list[dict[str, Any]]:
        """Register successful notebook artifacts in OpenWebUI Files."""

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
                raise PermissionError("Notebook artifact is outside the publication root.") from error
            if not path.is_file() or self._sha256(path) != artifact.get("sha256"):
                raise ValueError(f"Notebook artifact integrity check failed: {path.name}")
            if path.stat().st_size != artifact.get("size"):
                raise ValueError(f"Notebook artifact size check failed: {path.name}")
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
            descriptors.append(
                {
                    "id": registered.id,
                    "type": "image" if content_type.startswith("image/") else "file",
                    "name": registered.filename,
                    "url": f"/api/v1/files/{registered.id}/content",
                    "content_type": content_type,
                    "size": registered.meta.get("size") if registered.meta else None,
                }
            )
        await asyncio.to_thread(
            self._service_request,
            "POST",
            f"/v1/jobs/{quote(job['job_id'])}/publication",
            {"user_id": __user__["id"], "files": descriptors},
        )
        if __event_emitter__ and descriptors:
            await __event_emitter__({"type": "files", "data": {"files": descriptors}})
        return descriptors

    @staticmethod
    def _sha256(path: Path) -> str:
        """Hash one worker artifact before publication."""

        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    async def jupyter_runtime(
        self,
        action: Literal["list", "check", "submit", "status", "cancel"] = "list",
        code_name: str = "",
        product_id: str = "",
        job_id: str = "",
        __user__: dict[str, Any] = {},
        __request__: Any = None,
        __event_emitter__: Any = None,
        __metadata__: dict[str, Any] = {},
    ) -> dict[str, Any]:
        """List, check, queue, inspect, or cancel an allowlisted notebook run.

        For submit, choose one name returned by ``list`` and provide the exact
        product ID. Python source and notebook paths are never accepted. Status
        publishes the executed notebook, result JSON, and captured PNG outputs.

        :param action: list, check, submit, status, or cancel.
        :param code_name: Friendly allowlisted notebook name required for submit.
        :param product_id: Exact product ID injected as product_id and sacai_product_id.
        :param job_id: Job ID returned by submit; required for status/cancel.
        :return: Allowed names, connectivity, queued job identity, status, results, and published files.
        """

        user_id = str((__user__ or {}).get("id") or "")
        if not user_id:
            raise PermissionError("Jupyter runtime requires an authenticated OpenWebUI user.")
        if action not in {"list", "check", "submit", "status", "cancel"}:
            raise ValueError("action must be list, check, submit, status, or cancel.")
        if action == "list":
            return {"status": "ok", "allowed_code_names": sorted(self.valves.allowed_notebooks)}
        if action == "check":
            return await asyncio.to_thread(self._check_jupyter)
        if action == "submit":
            if not product_id.strip():
                raise ValueError("product_id is required for submit.")
            notebook_path = self._notebook_path(code_name, self.valves.allowed_notebooks)
            payload = {
                "user_id": user_id,
                "correlation_id": str((__metadata__ or {}).get("message_id") or uuid4()),
                "server_url": self.valves.jupyter_server_url,
                "server_token": self.valves.jupyter_server_token,
                "code_name": code_name,
                "notebook_path": notebook_path,
                "kernel_name": self.valves.kernel_name,
                "product_id": product_id.strip(),
                "verify_tls": self.valves.verify_tls,
                "execution_timeout_seconds": self.valves.execution_timeout_seconds,
                "max_output_chars": self.valves.max_output_chars,
                "max_notebook_bytes": self.valves.max_notebook_bytes,
                "max_code_cells": self.valves.max_code_cells,
            }
            return await asyncio.to_thread(self._service_request, "POST", "/v1/notebook-jobs", payload)
        if not job_id:
            raise ValueError("job_id is required for status or cancel.")
        path = f"/v1/jobs/{quote(job_id)}?{urlencode({'user_id': user_id})}"
        job = await asyncio.to_thread(self._service_request, "GET" if action == "status" else "DELETE", path)
        if action == "status" and job.get("status") == "succeeded":
            job["files"] = await self._publish(job, __request__, __user__, __event_emitter__)
        return job
