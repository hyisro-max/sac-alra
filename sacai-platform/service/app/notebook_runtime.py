"""Execute allowlisted notebooks through a standard remote Jupyter Server."""

import base64
import hashlib
import json
import ssl
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from uuid import uuid4

import websocket
from redis import Redis

from .config import get_settings
from .schemas import RemoteNotebookSubmit


class JupyterRuntimeClient:
    """Run notebook cells through Jupyter REST and kernel-channel APIs.

    A validated remote-runtime request is the input at construction. The
    ``execute`` output contains bounded kernel results and worker-local
    artifacts suitable for audit and OpenWebUI publication.
    """

    def __init__(self, request: RemoteNotebookSubmit):
        """Store validated connection settings without logging the API token."""

        self.request = request
        self.job_id = ""
        self._next_cancel_check = 0.0
        self._ssl_context = None
        if request.server_url.startswith("https://") and not request.verify_tls:
            self._ssl_context = ssl._create_unverified_context()

    def _headers(self) -> dict[str, str]:
        """Return Jupyter token authentication headers for REST/WebSocket calls."""

        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.request.server_token:
            headers["Authorization"] = f"token {self.request.server_token}"
        return headers

    def _rest(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call one bounded Jupyter REST endpoint and decode its JSON mapping."""

        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.request.server_url}{path}",
            data=body,
            method=method,
            headers=self._headers(),
        )
        try:
            with urlopen(
                request,
                timeout=min(self.request.execution_timeout_seconds, 300),
                context=self._ssl_context,
            ) as response:
                raw = response.read(self.request.max_notebook_bytes + 1)
                if len(raw) > self.request.max_notebook_bytes:
                    raise ValueError("Jupyter response exceeds max_notebook_bytes")
                return json.loads(raw.decode("utf-8")) if raw else {}
        except HTTPError as error:
            detail = error.read(2000).decode("utf-8", errors="replace")
            raise RuntimeError(f"Jupyter returned HTTP {error.code}: {detail}") from error
        except URLError as error:
            raise RuntimeError(f"Jupyter server is unavailable: {error.reason}") from error

    def check(self) -> dict[str, Any]:
        """Return a credential-free Jupyter API/version connectivity result."""

        result = self._rest("GET", "/api")
        return {"status": "ok", "version": result.get("version")}

    def _websocket(self, kernel_id: str, session_id: str):
        """Open one authenticated kernel channels WebSocket for this execution."""

        parsed = urlsplit(self.request.server_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        path = f"{parsed.path.rstrip('/')}/api/kernels/{quote(kernel_id)}/channels"
        query = urlencode({"session_id": session_id})
        url = urlunsplit((scheme, parsed.netloc, path, query, ""))
        headers = []
        if self.request.server_token:
            headers.append(f"Authorization: token {self.request.server_token}")
        sslopt = {"cert_reqs": ssl.CERT_REQUIRED if self.request.verify_tls else ssl.CERT_NONE}
        return websocket.create_connection(url, header=headers, timeout=10, sslopt=sslopt)

    @staticmethod
    def _message(session_id: str, code: str) -> tuple[str, dict[str, Any]]:
        """Build one Jupyter execute_request message and return its message ID."""

        message_id = str(uuid4())
        header = {
            "msg_id": message_id,
            "username": "sacai",
            "session": session_id,
            "date": datetime.now(UTC).isoformat(),
            "msg_type": "execute_request",
            "version": "5.3",
        }
        return message_id, {
            "header": header,
            "parent_header": {},
            "metadata": {},
            "content": {
                "code": code,
                "silent": False,
                "store_history": False,
                "user_expressions": {},
                "allow_stdin": False,
                "stop_on_error": True,
            },
            "channel": "shell",
            "buffers": [],
        }

    def _execute_code(self, connection: Any, session_id: str, code: str, deadline: float) -> list[dict[str, Any]]:
        """Execute one code cell and return bounded, notebook-compatible outputs."""

        message_id, message = self._message(session_id, code)
        connection.send(json.dumps(message))
        outputs: list[dict[str, Any]] = []
        used_chars = 0
        error_text = ""
        while time.monotonic() < deadline:
            if self._cancel_requested():
                raise RuntimeError("Notebook job was cancelled")
            connection.settimeout(min(5.0, max(0.1, deadline - time.monotonic())))
            try:
                event = json.loads(connection.recv())
            except websocket.WebSocketTimeoutException:
                continue
            if (event.get("parent_header") or {}).get("msg_id") != message_id:
                continue
            message_type = (event.get("header") or {}).get("msg_type")
            content = event.get("content") or {}
            if message_type == "status" and content.get("execution_state") == "idle":
                if error_text:
                    raise RuntimeError(error_text)
                return outputs
            output: dict[str, Any] | None = None
            if message_type == "stream":
                text = str(content.get("text") or "")
                output = {"output_type": "stream", "name": content.get("name", "stdout"), "text": text}
            elif message_type in {"execute_result", "display_data"}:
                data = content.get("data") or {}
                safe_data = {
                    key: value
                    for key, value in data.items()
                    if key in {"text/plain", "application/json", "image/png"}
                }
                output = {
                    "output_type": message_type,
                    "data": safe_data,
                    "metadata": content.get("metadata") or {},
                }
                if message_type == "execute_result":
                    output["execution_count"] = content.get("execution_count")
            elif message_type == "error":
                error_text = f"{content.get('ename', 'NotebookError')}: {content.get('evalue', '')}".strip()
                output = {
                    "output_type": "error",
                    "ename": content.get("ename", "NotebookError"),
                    "evalue": content.get("evalue", ""),
                    "traceback": list(content.get("traceback") or [])[-20:],
                }
            if output is not None:
                budget_output = json.loads(json.dumps(output, default=str))
                if isinstance(budget_output.get("data"), dict) and "image/png" in budget_output["data"]:
                    image_value = str(budget_output["data"]["image/png"])
                    if len(image_value) > self.request.max_notebook_bytes * 2:
                        raise ValueError("A notebook PNG output exceeds max_notebook_bytes")
                    budget_output["data"]["image/png"] = "[captured PNG]"
                encoded = json.dumps(budget_output, default=str)
                remaining = self.request.max_output_chars - used_chars
                if remaining <= 0:
                    continue
                if len(encoded) > remaining:
                    if output.get("output_type") == "stream":
                        output["text"] = str(output.get("text") or "")[:remaining] + "\n[output truncated]"
                    elif isinstance(output.get("data"), dict):
                        if "text/plain" in output["data"]:
                            output["data"]["text/plain"] = str(output["data"]["text/plain"])[:remaining] + "\n[output truncated]"
                        if "application/json" in output["data"]:
                            output["data"]["application/json"] = {"sacai_truncated": True}
                    else:
                        output["traceback"] = ["[error traceback truncated]"]
                used_chars += min(len(encoded), remaining)
                outputs.append(output)
        raise TimeoutError("Notebook cell exceeded execution_timeout_seconds")

    def _cancel_requested(self) -> bool:
        """Read the API-owned cooperative cancellation flag for this job."""

        if not self.job_id:
            return False
        now = time.monotonic()
        if now < self._next_cancel_check:
            return False
        self._next_cancel_check = now + 1.0
        value = Redis.from_url(get_settings().redis_url, decode_responses=True).get(f"sacai:job:{self.job_id}")
        if not value:
            return False
        try:
            return json.loads(value).get("cancelled") is True
        except json.JSONDecodeError:
            return False

    @staticmethod
    def _artifact(path: Path, content_type: str) -> dict[str, Any]:
        """Return a hash/size manifest for one worker-created notebook artifact."""

        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return {
            "path": str(path),
            "name": path.name,
            "content_type": content_type,
            "size": path.stat().st_size,
            "sha256": digest,
        }

    def execute(self, job_id: str) -> dict[str, Any]:
        """Fetch, execute, save, and manifest one allowlisted remote notebook."""

        started = time.monotonic()
        self.job_id = job_id
        if self._cancel_requested():
            raise RuntimeError("Notebook job was cancelled")
        encoded_path = quote(self.request.notebook_path, safe="/")
        document = self._rest("GET", f"/api/contents/{encoded_path}")
        notebook = document.get("content")
        if document.get("type") != "notebook" or not isinstance(notebook, dict):
            raise ValueError("Configured Jupyter path is not a readable notebook")
        if len(json.dumps(notebook).encode("utf-8")) > self.request.max_notebook_bytes:
            raise ValueError("Notebook exceeds max_notebook_bytes")
        code_cells = [cell for cell in notebook.get("cells") or [] if isinstance(cell, dict) and cell.get("cell_type") == "code"]
        if len(code_cells) > self.request.max_code_cells:
            raise ValueError("Notebook exceeds max_code_cells")

        session_id = str(uuid4())
        session = self._rest(
            "POST",
            "/api/sessions",
            {
                "name": f"sacai-{job_id}",
                "path": self.request.notebook_path,
                "type": "notebook",
                "kernel": {"name": self.request.kernel_name},
            },
        )
        remote_session_id = str(session.get("id") or "")
        kernel_id = str((session.get("kernel") or {}).get("id") or "")
        if not remote_session_id or not kernel_id:
            raise RuntimeError("Jupyter did not return a session and kernel ID")

        output_dir = get_settings().output_root / self.request.user_id / job_id
        connection = None
        cell_summaries: list[dict[str, Any]] = []
        image_paths: list[Path] = []
        deadline = time.monotonic() + self.request.execution_timeout_seconds
        try:
            output_dir.mkdir(parents=True, exist_ok=False)
            connection = self._websocket(kernel_id, session_id)
            injected = f"product_id = {self.request.product_id!r}\nsacai_product_id = product_id"
            self._execute_code(connection, session_id, injected, deadline)
            executed_count = 0
            for index, cell in enumerate(notebook.get("cells") or []):
                if not isinstance(cell, dict) or cell.get("cell_type") != "code":
                    continue
                source = cell.get("source") or ""
                code = "".join(source) if isinstance(source, list) else str(source)
                outputs = self._execute_code(connection, session_id, code, deadline)
                executed_count += 1
                cell["outputs"] = outputs
                cell["execution_count"] = executed_count
                for output_index, output in enumerate(outputs):
                    data = output.get("data") or {}
                    if "image/png" in data:
                        image_path = output_dir / f"cell-{index + 1}-output-{output_index + 1}.png"
                        image_path.write_bytes(base64.b64decode(data["image/png"], validate=True))
                        image_paths.append(image_path)
                        data["image/png"] = f"published as {image_path.name}"
                cell_summaries.append({"cell": index + 1, "outputs": outputs})
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
            try:
                self._rest("DELETE", f"/api/sessions/{quote(remote_session_id)}")
            except Exception as error:
                raise RuntimeError("Jupyter session cleanup failed; an administrator must inspect the remote runtime") from error

        if len(json.dumps(notebook, default=str).encode("utf-8")) > self.request.max_notebook_bytes:
            raise ValueError("Executed notebook exceeds max_notebook_bytes after captured outputs")
        notebook_path = output_dir / f"{self.request.code_name}-{job_id}.executed.ipynb"
        notebook_path.write_text(json.dumps(notebook, indent=2), encoding="utf-8")
        result = {
            "schema_version": "1.0",
            "job_id": job_id,
            "code_name": self.request.code_name,
            "notebook_path": self.request.notebook_path,
            "product_id": self.request.product_id,
            "kernel_name": self.request.kernel_name,
            "cells_executed": len(cell_summaries),
            "cell_outputs": cell_summaries,
            "runtime_seconds": round(time.monotonic() - started, 3),
        }
        result_path = output_dir / f"{self.request.code_name}-{job_id}.result.json"
        result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        result["artifacts"] = [
            self._artifact(notebook_path, "application/x-ipynb+json"),
            self._artifact(result_path, "application/json"),
            *(self._artifact(path, "image/png") for path in image_paths),
        ]
        return result


def run_remote_notebook(job_id: str, request: RemoteNotebookSubmit) -> dict[str, Any]:
    """Execute one validated remote-notebook job for the Celery task layer."""

    return JupyterRuntimeClient(request).execute(job_id)
