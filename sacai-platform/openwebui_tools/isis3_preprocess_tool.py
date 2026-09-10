"""
title: SACAI ISIS3 Preprocessing
description: Search the ISIS3 application catalog and submit/track/cancel ISIS3 raw-product preprocessing jobs.
"""

import time
from typing import Any

import requests
from pydantic import BaseModel, Field


class Tools:
    """One model-visible entry point for ISIS3 catalog discovery and jobs.

    A single public method with an `action` dispatcher, per this project's
    architecture: exposing separate methods per action (search/describe/
    submit/status/cancel) previously caused tool-call loops. __user__ and
    __files__ are OpenWebUI-reserved parameters, stripped from the model-
    visible schema and injected by OpenWebUI itself.
    """

    class Valves(BaseModel):
        api_base_url: str = Field(
            default="http://sacai-api:8000",
            description="Base URL of the SACAI scientific service (private Docker network).",
        )
        internal_token: str = Field(
            default="",
            description="Shared X-Sacai-Token value; must match SACAI_INTERNAL_TOKEN on the service.",
        )
        request_timeout_seconds: int = Field(default=30, description="HTTP timeout for non-submit calls.")
        search_result_limit: int = Field(default=15, description="Max results returned by a search action.")

    def __init__(self):
        self.valves = self.Valves()

    def _headers(self) -> dict[str, str]:
        return {"X-Sacai-Token": self.valves.internal_token}

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = requests.get(
            f"{self.valves.api_base_url}{path}",
            headers=self._headers(),
            params=params or {},
            timeout=self.valves.request_timeout_seconds,
        )
        if response.status_code == 404:
            return {"error": response.json().get("detail", "not found")}
        response.raise_for_status()
        return response.json()

    def _resolve_input_path(self, filename: str, __files__: list[dict[str, Any]] | None) -> str:
        """Resolve a model-supplied filename to the trusted stored path.

        __files__ is the OpenWebUI-injected descriptor list for this chat
        turn (never model-visible as an argument). This never lets the model
        supply a filesystem path directly, matching this project's rejected-
        alternatives decision on that point.

        NOTE: needs verification inside a real OpenWebUI instance. Per
        ARCHITECTURE_DECISIONS.md this should resolve the matched entry's id
        via Files.get_file_by_id() and the stored path via Storage.get_file()
        after an ownership/access check -- those OpenWebUI-internal calls are
        written here following the documented pattern, but were not directly
        inspected against the real open-webui checkout in this session.
        """

        if not __files__:
            raise ValueError("no files attached to this chat turn")

        matches = [f for f in __files__ if f.get("name") == filename]
        if not matches:
            available = [f.get("name") for f in __files__]
            raise ValueError(f"'{filename}' not found among attached files: {available}")
        if len(matches) > 1:
            raise ValueError(f"'{filename}' matches multiple attached files; ambiguous")

        file_id = matches[0]["id"]

        # --- OpenWebUI-internal resolution: verify against real checkout ---
        from open_webui.models.files import Files
        from open_webui.storage.provider import Storage

        file_record = Files.get_file_by_id(file_id)
        if file_record is None:
            raise ValueError(f"file id {file_id} not found or not accessible")
        return Storage.get_file(file_record.path)
        # ---------------------------------------------------------------

    def isis3_preprocess(
        self,
        action: str,
        query: str = "",
        operation_name: str = "",
        filename: str = "",
        job_id: str = "",
        options: dict[str, Any] | None = None,
        __user__: dict[str, Any] | None = None,
        __files__: list[dict[str, Any]] | None = None,
    ) -> str:
        """Search, describe, submit, check, or cancel ISIS3 preprocessing work.

        :param action: One of "search", "describe", "submit", "status", "cancel".
        :param query: Free-text description of what you want to do. Required for "search".
            Example: "clean up noise in this image" -> returns candidate ISIS tools.
        :param operation_name: Exact ISIS application name. Required for "describe".
        :param filename: Name of an attached file to preprocess. Required for "submit".
        :param job_id: Job identifier. Required for "status" and "cancel".
        :param options: Extra job options passed through to the ISIS3 wrapper. Optional for "submit".
        :return: A human-readable summary of the result. Always tell the user which
            ISIS tool you are about to run and why before calling with action="submit",
            unless they already named the exact tool themselves.
        """

        if __user__ is None or "id" not in __user__:
            return "Error: no authenticated user context available for this request."
        user_id = __user__["id"]

        if action == "search":
            if not query:
                return "Error: 'query' is required for action='search'."
            hits = self._get("/v1/isis/search", {"query": query, "limit": self.valves.search_result_limit})
            if not hits:
                return f"No ISIS tools matched '{query}'. Try a different description."
            lines = [f"- {h['name']} ({', '.join(h['category'])}): {h['brief']}" for h in hits]
            return f"Found {len(hits)} ISIS tool(s) matching '{query}':\n" + "\n".join(lines)

        if action == "describe":
            if not operation_name:
                return "Error: 'operation_name' is required for action='describe'."
            result = self._get(f"/v1/isis/describe/{operation_name}")
            if "error" in result:
                return f"Error: {result['error']}"
            required = [p["name"] for p in result["parameters"] if p.get("required")]
            optional = [p["name"] for p in result["parameters"] if not p.get("required")]
            return (
                f"{result['name']} ({', '.join(result['category'])}): {result['brief']}\n"
                f"Required parameters: {', '.join(required) or 'none'}\n"
                f"Optional parameters: {', '.join(optional) or 'none'}"
            )

        if action == "submit":
            if not filename:
                return "Error: 'filename' is required for action='submit'."
            try:
                input_path = self._resolve_input_path(filename, __files__)
            except ValueError as error:
                return f"Error: {error}"

            response = requests.post(
                f"{self.valves.api_base_url}/v1/jobs",
                headers=self._headers(),
                json={
                    "kind": "isis3",
                    "user_id": user_id,
                    "input_file_id": next(f["id"] for f in __files__ if f["name"] == filename),
                    "input_path": input_path,
                    "original_name": filename,
                    "correlation_id": f"{user_id}-{int(time.time())}",
                    "options": options or {},
                },
                timeout=self.valves.request_timeout_seconds,
            )
            response.raise_for_status()
            accepted = response.json()
            return (
                f"Job submitted: {accepted['job_id']} (queue: {accepted['queue']}). "
                f"Use action='status' with this job_id to check progress."
            )

        if action == "status":
            if not job_id:
                return "Error: 'job_id' is required for action='status'."
            result = self._get(f"/v1/jobs/{job_id}", {"user_id": user_id})
            if "error" in result:
                return f"Error: {result['error']}"
            status = result["status"]
            if status == "failed":
                return f"Job {job_id}: failed. Error: {result.get('error')}"
            if status == "succeeded":
                files = result.get("published_files", [])
                return f"Job {job_id}: succeeded. {len(files)} file(s) published."
            return f"Job {job_id}: {status}."

        if action == "cancel":
            if not job_id:
                return "Error: 'job_id' is required for action='cancel'."
            response = requests.delete(
                f"{self.valves.api_base_url}/v1/jobs/{job_id}",
                headers=self._headers(),
                params={"user_id": user_id},
                timeout=self.valves.request_timeout_seconds,
            )
            if response.status_code == 404:
                return f"Error: job {job_id} not found."
            response.raise_for_status()
            return f"Job {job_id}: cancelled."

        return f"Error: unknown action '{action}'. Use search, describe, submit, status, or cancel."
