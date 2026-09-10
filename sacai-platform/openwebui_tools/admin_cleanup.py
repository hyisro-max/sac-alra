"""
title: SACAI Admin Cleanup
description: Preview and explicitly approve deletion of stale SACAI job outputs.
author: SACAI
version: 1.0.0
"""

import asyncio
import json
import time
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field


class Tools:
    """Expose one two-phase cleanup entry point restricted to admins."""

    class Valves(BaseModel):
        """Configure cleanup API location, token, timeout, and minimum age."""

        service_url: str = Field(default="http://sacai-api:8000", description="Internal SACAI job API base URL.")
        service_token: str = Field(
            default="replace-with-at-least-16-characters",
            description="Shared internal API token.",
            json_schema_extra={"input": {"type": "password"}},
        )
        request_timeout_seconds: int = Field(default=30, ge=1, le=300)
        minimum_age_hours: int = Field(default=168, ge=1)

    def __init__(self):
        """Initialize default cleanup Valves before admin configuration."""

        self.valves = self.Valves()

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Post one cleanup request to the private API and decode its result."""

        request = Request(
            f"{self.valves.service_url.rstrip('/')}/v1/cleanup",
            data=json.dumps(payload).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "X-SACAI-Token": self.valves.service_token},
        )
        try:
            with urlopen(request, timeout=self.valves.request_timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise RuntimeError(f"SACAI cleanup returned HTTP {error.code}: {error.read().decode()}") from error
        except URLError as error:
            raise RuntimeError(f"SACAI service is unavailable: {error.reason}") from error

    def _audit_deletions(
        self,
        correlation_id: str,
        user_id: str,
        deleted_file_ids: list[str],
        failed_file_ids: list[str],
    ) -> None:
        """Record OpenWebUI file-row deletions in the linked append-only audit.

        The approved preview token, admin ID, deleted IDs, and failed IDs are
        inputs. The service event is written after all router attempts finish.
        """

        query = urlencode({"event_type": "cleanup.openwebui_files_deleted", "user_id": user_id})
        request = Request(
            f"{self.valves.service_url.rstrip('/')}/v1/audit/{quote(correlation_id)}?{query}",
            data=json.dumps({"deleted_file_ids": deleted_file_ids, "failed_file_ids": failed_file_ids}).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "X-SACAI-Token": self.valves.service_token},
        )
        with urlopen(request, timeout=self.valves.request_timeout_seconds):
            return

    async def sacai_cleanup(
        self,
        action: Literal["preview", "execute"] = "preview",
        older_than_hours: int = 168,
        preview_token: str = "",
        __user__: dict[str, Any] = {},
        __request__: Any = None,
    ) -> dict[str, Any]:
        """Preview or execute deletion of stale SACAI-owned output directories.

        Always call preview first and show its exact target list to the admin.
        Execute requires the unexpired token returned by that preview and can
        delete only those same targets. Every deletion is audited.

        :param action: preview to list targets or execute after explicit approval.
        :param older_than_hours: Only job outputs older than this age are eligible.
        :param preview_token: Exact token from the approved preview; required for execute.
        :return: Exact targets, token expiration, and actual deleted paths.
        """

        if __user__.get("role") != "admin":
            raise PermissionError("This Tool requires the OpenWebUI admin role.")
        if action not in {"preview", "execute"}:
            raise ValueError("action must be preview or execute.")
        age = max(older_than_hours, self.valves.minimum_age_hours)
        if action == "execute" and not preview_token:
            raise ValueError("preview_token is required; run preview and obtain explicit approval first.")
        from open_webui.models.files import Files

        openwebui_file_ids: list[str] = []
        if action == "preview":
            cutoff = int(time.time()) - age * 3600
            for record in await Files.get_files():
                metadata = record.meta or {}
                tool_metadata = metadata.get("data") if isinstance(metadata, dict) else {}
                if (
                    isinstance(tool_metadata, dict)
                    and tool_metadata.get("sacai_job_id")
                    and (record.created_at or 0) < cutoff
                ):
                    openwebui_file_ids.append(record.id)
        result = await asyncio.to_thread(
            self._request,
            {
                "action": action,
                "user_id": __user__["id"],
                "user_role": __user__["role"],
                "older_than_hours": age,
                "preview_token": preview_token or None,
                "openwebui_file_ids": openwebui_file_ids,
            },
        )
        if action == "execute" and result.get("openwebui_file_ids"):
            if __request__ is None:
                raise RuntimeError("OpenWebUI request context is required to delete registered files safely.")
            from open_webui.internal.db import get_async_db_context
            from open_webui.models.users import Users
            from open_webui.routers.files import delete_file_by_id

            user = await Users.get_user_by_id(__user__["id"])
            deleted_file_ids: list[str] = []
            failed_file_ids: list[str] = []
            async with get_async_db_context() as db:
                for file_id in result["openwebui_file_ids"]:
                    try:
                        await delete_file_by_id(__request__, file_id, user=user, db=db)
                        deleted_file_ids.append(file_id)
                    except Exception:
                        failed_file_ids.append(file_id)
            result["deleted_openwebui_file_ids"] = deleted_file_ids
            result["failed_openwebui_file_ids"] = failed_file_ids
            await asyncio.to_thread(
                self._audit_deletions,
                preview_token,
                __user__["id"],
                deleted_file_ids,
                failed_file_ids,
            )
        return result
