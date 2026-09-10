"""Append-only linked audit storage for jobs, grounding, and cleanup."""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .config import get_settings


def _connect() -> sqlite3.Connection:
    """Open a short-lived SQLite connection and ensure the audit schema.

    There are no inputs. The returned WAL-enabled connection is used for one
    small transaction, avoiding a process-global connection across workers.
    """

    connection = sqlite3.connect(get_settings().audit_db_path, timeout=30)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_event (
            id TEXT PRIMARY KEY,
            correlation_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            user_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS audit_event_correlation_idx ON audit_event(correlation_id, created_at)"
    )
    return connection


def append_event(correlation_id: str, event_type: str, user_id: str, payload: dict[str, Any]) -> str:
    """Append one immutable structured event and return its UUID.

    Inputs identify the linked scientific turn, event kind, actor, and payload.
    Workers, grounding filters, publication adapters, and cleanup all call this
    function so a scientist can reconstruct the complete claim lineage.
    """

    event_id = str(uuid4())
    with _connect() as connection:
        connection.execute(
            "INSERT INTO audit_event VALUES (?, ?, ?, ?, ?, ?)",
            (
                event_id,
                correlation_id,
                event_type,
                user_id,
                json.dumps(payload, sort_keys=True, default=str),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    return event_id


def list_events(correlation_id: str) -> list[dict[str, Any]]:
    """Return all audit events for one correlation ID in creation order.

    The correlation ID is the input. The JSON-compatible list is used by the
    audit API and grounding verification without changing stored records.
    """

    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, event_type, user_id, payload_json, created_at "
            "FROM audit_event WHERE correlation_id = ? ORDER BY created_at",
            (correlation_id,),
        ).fetchall()
    return [
        {
            "id": row[0],
            "event_type": row[1],
            "user_id": row[2],
            "payload": json.loads(row[3]),
            "created_at": row[4],
        }
        for row in rows
    ]

