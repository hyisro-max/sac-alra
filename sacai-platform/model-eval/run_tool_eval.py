"""Evaluate Ollama tool selection against SACAI's exact production schemas."""

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "stac_catalog",
            "description": "Inspect or search the configured STAC catalog.",
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "operation": {"enum": ["auto", "list_collections", "list_items", "search", "schema"]},
                    "collection_id": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "planetir",
            "description": "Submit, inspect, or cancel deterministic GeoTIFF analysis.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"enum": ["submit", "status", "cancel"]},
                    "job_id": {"type": "string"},
                    "file_id": {"type": "string"},
                    "mode": {"enum": ["analyze", "restore"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "isis3_preprocess",
            "description": "Submit, inspect, or cancel raw-product ISIS3 preprocessing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"enum": ["submit", "status", "cancel"]},
                    "job_id": {"type": "string"},
                    "file_id": {"type": "string"},
                    "already_calibrated": {"type": "boolean"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scientific_workflow",
            "description": "Run queued optional ISIS3 preprocessing followed by PlanetIR.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"enum": ["submit", "status", "cancel"]},
                    "job_id": {"type": "string"},
                    "file_id": {"type": "string"},
                    "already_calibrated": {"type": "boolean"},
                    "mode": {"enum": ["analyze", "restore"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sacai_cleanup",
            "description": "Preview or execute admin cleanup with an approved token.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"enum": ["preview", "execute"]},
                    "older_than_hours": {"type": "integer"},
                    "preview_token": {"type": "string"},
                },
            },
        },
    },
]


def _cases(path: Path) -> list[dict[str, Any]]:
    """Read JSON Lines cases from ``path`` and return decoded test mappings."""

    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _chat(base_url: str, model: str, prompt: str) -> dict[str, Any]:
    """Send one deterministic native Ollama chat and return its JSON response."""

    request = Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "tools": TOOL_SCHEMAS,
                "stream": False,
                "options": {"temperature": 0},
            }
        ).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def _score(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    """Compare one response's first tool call with exact expected safety fields."""

    calls = (response.get("message") or {}).get("tool_calls") or []
    function = (calls[0] if calls else {}).get("function") or {}
    name = function.get("name")
    arguments = function.get("arguments") or {}
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    expected_tool = case.get("expected_tool")
    tool_ok = name == expected_tool if expected_tool else not calls
    values_ok = all(arguments.get(key) == value for key, value in case.get("expected", {}).items())
    forbidden_ok = not any(key in arguments for key in case.get("forbidden_keys", []))
    return {
        "id": case["id"],
        "passed": tool_ok and values_ok and forbidden_ok,
        "tool_ok": tool_ok,
        "values_ok": values_ok,
        "forbidden_ok": forbidden_ok,
        "actual_tool": name,
        "actual_arguments": arguments,
    }


def main() -> None:
    """Parse CLI inputs, evaluate all cases, write evidence, and exit on failure."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="http://localhost:11434")
    args = parser.parse_args()
    results = [_score(case, _chat(args.base_url, args.model, case["prompt"])) for case in _cases(args.cases)]
    report = {
        "model": args.model,
        "passed": sum(result["passed"] for result in results),
        "total": len(results),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("model", "passed", "total")}))
    raise SystemExit(0 if report["passed"] == report["total"] else 1)


if __name__ == "__main__":
    main()
