"""LangGraph orchestration for conditional scientific and cleanup workflows."""

import hashlib
import json
import re
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .cleanup import run_cleanup
from .config import get_settings
from .isis import preprocess
from .planetir import analyze
from .schemas import CleanupRequest
from .security import resolve_below


class ScientificState(TypedDict, total=False):
    """Carry validated state between conditional scientific graph nodes."""

    workflow_id: str
    user_id: str
    input_path: str
    options: dict[str, Any]
    already_calibrated: bool
    isis_result: dict[str, Any]
    planetir_result: dict[str, Any]
    final_text: str
    grounding: dict[str, Any]
    report_path: str
    report_artifact: dict[str, Any]


class CleanupState(TypedDict, total=False):
    """Carry preview and approval state through the cleanup graph."""

    user_id: str
    user_role: str
    older_than_hours: int
    preview: dict[str, Any]
    approval: dict[str, Any]
    result: dict[str, Any]


def _needs_isis(state: ScientificState) -> Literal["isis", "planetir"]:
    """Route raw products through ISIS3 and ready GeoTIFFs directly onward.

    Scientific state is the input. The output edge name is based on explicit
    calibration state and file type, not an LLM's preference.
    """

    suffix = Path(state["input_path"]).suffix.lower()
    return "planetir" if state.get("already_calibrated") or suffix in {".tif", ".tiff"} else "isis"


def _isis_node(state: ScientificState) -> ScientificState:
    """Calibrate and project one raw product inside the scientific graph.

    State is the input. The returned update contains the ISIS result and swaps
    downstream input to its validated GeoTIFF artifact.
    """

    result = preprocess(
        f"{state['workflow_id']}-isis",
        state["user_id"],
        state["input_path"],
        state.get("options", {}),
    )
    return {"isis_result": result, "input_path": result["artifacts"][0]["path"], "already_calibrated": True}


def _planetir_node(state: ScientificState) -> ScientificState:
    """Run deterministic PlanetIR after optional ISIS3 preprocessing.

    Scientific state is the input. The validated PlanetIR mapping is the output
    update consumed by grounding and report nodes.
    """

    result = analyze(
        f"{state['workflow_id']}-planetir",
        state["user_id"],
        state["input_path"],
        state.get("options", {}),
    )
    return {"planetir_result": result}


def _numbers(value: Any) -> set[str]:
    """Extract normalized numeric values from JSON-compatible data or text.

    Arbitrary graph data is the input. The canonical Decimal string set is the
    output used by the same mechanical grounding principle as the UI Filter.
    """

    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
    tokens = re.findall(r"(?<![A-Za-z0-9_])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![A-Za-z0-9_])", text)
    normalized: set[str] = set()
    for token in tokens:
        try:
            normalized.add(str(Decimal(token).normalize()))
        except InvalidOperation:
            continue
    return normalized


def _grounding_node(state: ScientificState) -> ScientificState:
    """Interrupt graph progress when final prose contains ungrounded numbers.

    Scientific state is the input. Passing output records matched values; on
    failure LangGraph pauses and requires an explicit corrected-text resume.
    """

    result_numbers = _numbers(state["planetir_result"])
    final_numbers = _numbers(state.get("final_text", ""))
    unmatched = sorted(final_numbers - result_numbers)
    if unmatched:
        correction = interrupt(
            {
                "reason": "numeric_grounding_failed",
                "unmatched_numbers": unmatched,
                "instruction": "Provide corrected final_text using only PlanetIR result numbers.",
            }
        )
        corrected_text = str((correction or {}).get("final_text") or "")
        corrected_unmatched = sorted(_numbers(corrected_text) - result_numbers)
        if corrected_unmatched:
            raise ValueError(f"resumed text is still ungrounded: {corrected_unmatched}")
        return {
            "final_text": corrected_text,
            "grounding": {"passed": True, "unmatched_numbers": []},
        }
    return {"grounding": {"passed": True, "unmatched_numbers": []}}


def _report_node(state: ScientificState) -> ScientificState:
    """Write a deterministic workflow report after grounding passes.

    Scientific state is the input. The returned update names a JSON report
    inside the same workflow-owned output root.
    """

    directory = resolve_below(
        str(get_settings().output_root / state["user_id"] / state["workflow_id"]),
        get_settings().output_root,
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "workflow_report.json"
    path.write_text(
        json.dumps(
            {
                "workflow_id": state["workflow_id"],
                "isis": state.get("isis_result"),
                "planetir": state["planetir_result"],
                "final_text": state.get("final_text", ""),
                "grounding": state["grounding"],
            },
            indent=2,
            sort_keys=True,
            default=str,
        ),
        encoding="utf-8",
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "report_path": str(path),
        "report_artifact": {
            "path": str(path),
            "name": path.name,
            "content_type": "application/json",
            "size": path.stat().st_size,
            "sha256": digest,
        },
    }


def build_scientific_graph(checkpointer: SqliteSaver):
    """Compile the STAC-adjacent optional-ISIS PlanetIR grounding graph.

    A SQLite checkpointer is the input. The compiled graph output supports
    conditional routing, durable state, and human correction interrupts.
    """

    graph = StateGraph(ScientificState)
    graph.add_node("isis", _isis_node)
    graph.add_node("planetir", _planetir_node)
    graph.add_node("grounding", _grounding_node)
    graph.add_node("report", _report_node)
    graph.add_conditional_edges(START, _needs_isis, {"isis": "isis", "planetir": "planetir"})
    graph.add_edge("isis", "planetir")
    graph.add_edge("planetir", "grounding")
    graph.add_edge("grounding", "report")
    graph.add_edge("report", END)
    return graph.compile(checkpointer=checkpointer)


def _cleanup_preview_node(state: CleanupState) -> CleanupState:
    """Generate the exact deletion preview at the start of cleanup orchestration."""

    preview = run_cleanup(
        CleanupRequest(
            action="preview",
            user_id=state["user_id"],
            user_role=state["user_role"],
            older_than_hours=state["older_than_hours"],
        )
    )
    return {"preview": preview.model_dump(mode="json")}


def _cleanup_approval_node(state: CleanupState) -> CleanupState:
    """Interrupt after preview and require an explicit matching approval token.

    Cleanup state is the input. The output stores approval only when the resume
    payload repeats the preview token, mechanically binding approval to targets.
    """

    approval = interrupt({"reason": "cleanup_preview", "preview": state["preview"]})
    if not approval or approval.get("preview_token") != state["preview"]["preview_token"]:
        raise ValueError("cleanup approval token does not match the preview")
    return {"approval": approval}


def _cleanup_execute_node(state: CleanupState) -> CleanupState:
    """Execute exactly the approved cleanup preview and return its audit result."""

    result = run_cleanup(
        CleanupRequest(
            action="execute",
            user_id=state["user_id"],
            user_role=state["user_role"],
            older_than_hours=state["older_than_hours"],
            preview_token=state["preview"]["preview_token"],
        )
    )
    return {"result": result.model_dump(mode="json")}


def build_cleanup_graph(checkpointer: SqliteSaver):
    """Compile the preview-interrupt-approval-execute cleanup graph."""

    graph = StateGraph(CleanupState)
    graph.add_node("preview", _cleanup_preview_node)
    graph.add_node("approval", _cleanup_approval_node)
    graph.add_node("execute", _cleanup_execute_node)
    graph.add_edge(START, "preview")
    graph.add_edge("preview", "approval")
    graph.add_edge("approval", "execute")
    graph.add_edge("execute", END)
    return graph.compile(checkpointer=checkpointer)


def invoke_scientific(workflow_id: str, state: ScientificState | None = None, resume: dict[str, Any] | None = None):
    """Start or resume one checkpointed scientific workflow.

    Workflow ID, initial state, or resume payload are inputs. The returned graph
    state includes interrupt data or the completed deterministic report path.
    """

    connection = sqlite3.connect(get_settings().graph_db_path, check_same_thread=False)
    graph = build_scientific_graph(SqliteSaver(connection))
    config = {"configurable": {"thread_id": workflow_id}}
    return graph.invoke(Command(resume=resume) if resume is not None else state, config=config)


def invoke_cleanup(workflow_id: str, state: CleanupState | None = None, resume: dict[str, Any] | None = None):
    """Start or resume one checkpointed cleanup approval workflow."""

    connection = sqlite3.connect(get_settings().graph_db_path, check_same_thread=False)
    graph = build_cleanup_graph(SqliteSaver(connection))
    config = {"configurable": {"thread_id": workflow_id}}
    return graph.invoke(Command(resume=resume) if resume is not None else state, config=config)
