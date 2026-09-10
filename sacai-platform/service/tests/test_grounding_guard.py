"""Regression tests for final-response numeric grounding behavior."""

import asyncio
import importlib.util
from pathlib import Path


def _load_filter():
    """Load the standalone OpenWebUI Filter file and return its class."""

    path = Path(__file__).parents[2] / "openwebui_functions/grounding_guard.py"
    spec = importlib.util.spec_from_file_location("grounding_guard", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module.Filter


def test_unmatched_number_appends_warning() -> None:
    """Flag assistant prose containing a value absent from tool output."""

    guard = _load_filter()()
    guard.valves.service_url = "http://127.0.0.1:1"
    body = {
        "id": "message",
        "messages": [
            {
                "role": "assistant",
                "content": "Mean is 5.0 but confidence is 99.",
                "output": [
                    {"type": "function_call_output", "output": [{"type": "output_text", "text": '{"mean": 5}'}]}
                ],
            }
        ],
    }
    result = asyncio.run(guard.outlet(body, {"id": "u"}, {"message_id": "message"}))
    assert "99" in result["messages"][-1]["content"]
    assert "Numeric grounding warning" in result["messages"][-1]["content"]


def test_equivalent_decimal_is_grounded() -> None:
    """Treat equivalent decimal spellings as the same deterministic value."""

    guard = _load_filter()()
    guard.valves.service_url = "http://127.0.0.1:1"
    body = {
        "id": "message",
        "messages": [
            {
                "role": "assistant",
                "content": "Mean is 5.0.",
                "output": [{"type": "function_call_output", "output": "{\"mean\": 5}"}],
            }
        ],
    }
    result = asyncio.run(guard.outlet(body, {"id": "u"}, {"message_id": "message"}))
    assert "warning" not in result["messages"][-1]["content"].lower()

