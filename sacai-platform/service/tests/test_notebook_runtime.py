"""Safety and protocol tests for allowlisted remote notebook execution."""

import asyncio
import importlib.util
import json
from pathlib import Path


def _tool():
    """Load the standalone OpenWebUI Tool for adapter-level tests."""

    path = Path(__file__).parents[2] / "openwebui_tools/jupyter_runtime.py"
    spec = importlib.util.spec_from_file_location("jupyter_runtime_tool", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module.Tools()


def test_tool_submits_only_allowlisted_path_and_product(monkeypatch) -> None:
    """Map a friendly name to its Valve path without accepting Python source."""

    tool = _tool()
    tool.valves.allowed_notebooks = {"tmc_stats": "notebooks/tmc_stats.ipynb"}
    tool.valves.jupyter_server_url = "http://runtime.internal:8888"
    tool.valves.jupyter_server_token = "secret-token"
    captured = {}

    def request(method, path, payload=None):
        captured.update({"method": method, "path": path, "payload": payload})
        return {"job_id": "job-1", "status": "queued", "correlation_id": "message-1", "queue": "notebook_remote"}

    monkeypatch.setattr(tool, "_service_request", request)
    result = asyncio.run(
        tool.jupyter_runtime(
            action="submit",
            code_name="tmc_stats",
            product_id="TMC-001",
            __user__={"id": "scientist"},
            __metadata__={"message_id": "message-1"},
        )
    )

    assert result["status"] == "queued"
    assert captured["path"] == "/v1/notebook-jobs"
    assert captured["payload"]["notebook_path"] == "notebooks/tmc_stats.ipynb"
    assert captured["payload"]["product_id"] == "TMC-001"
    assert "source" not in captured["payload"]


def test_unknown_code_name_is_rejected_before_submission(monkeypatch) -> None:
    """Prevent a user from selecting an arbitrary remote notebook path."""

    import pytest

    tool = _tool()
    tool.valves.allowed_notebooks = {"approved": "notebooks/approved.ipynb"}
    monkeypatch.setattr(tool, "_service_request", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    with pytest.raises(ValueError, match="Unknown code_name"):
        asyncio.run(
            tool.jupyter_runtime(
                action="submit",
                code_name="../../other",
                product_id="TMC-001",
                __user__={"id": "scientist"},
            )
        )


def test_kernel_message_capture_is_parent_scoped() -> None:
    """Capture only output belonging to the submitted execute request."""

    from app.notebook_runtime import JupyterRuntimeClient
    from app.schemas import RemoteNotebookSubmit

    request = RemoteNotebookSubmit(
        user_id="scientist",
        correlation_id="message-1",
        server_url="http://runtime.internal:8888",
        code_name="approved",
        notebook_path="notebooks/approved.ipynb",
        product_id="TMC-001",
    )
    client = JupyterRuntimeClient(request)

    class Connection:
        """Provide deterministic kernel messages after observing the request ID."""

        def send(self, value):
            self.message_id = json.loads(value)["header"]["msg_id"]
            self.messages = iter(
                [
                    {
                        "parent_header": {"msg_id": "some-other-request"},
                        "header": {"msg_type": "stream"},
                        "content": {"name": "stdout", "text": "ignore"},
                    },
                    {
                        "parent_header": {"msg_id": self.message_id},
                        "header": {"msg_type": "stream"},
                        "content": {"name": "stdout", "text": "result=42"},
                    },
                    {
                        "parent_header": {"msg_id": self.message_id},
                        "header": {"msg_type": "status"},
                        "content": {"execution_state": "idle"},
                    },
                ]
            )

        def recv(self):
            return json.dumps(next(self.messages))

        def settimeout(self, timeout):
            self.timeout = timeout

    outputs = client._execute_code(Connection(), "session-1", "print('result=42')", 10**12)
    assert outputs == [{"output_type": "stream", "name": "stdout", "text": "result=42"}]
