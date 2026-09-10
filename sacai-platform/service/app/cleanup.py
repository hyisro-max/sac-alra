"""Two-phase, root-scoped cleanup for stale SACAI worker outputs."""

import hashlib
import hmac
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .audit import append_event
from .config import get_settings
from .schemas import CleanupRequest, CleanupResult
from .security import resolve_below


def _connection() -> sqlite3.Connection:
    """Open the audit database and ensure the cleanup-preview table exists.

    There are no inputs. The returned connection stores exact preview targets
    so execution can never silently expand beyond what the admin inspected.
    """

    connection = sqlite3.connect(get_settings().audit_db_path, timeout=30)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS cleanup_preview (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            targets_json TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            executed_at TEXT
        )
        """
    )
    return connection


def _stale_targets(older_than_hours: int) -> list[str]:
    """List stale job/version directories and root-level temporary files.

    The age threshold is the input. Exact canonical directory strings are the
    output; no file outside the configured output/tool-version roots can enter
    the preview.
    """

    roots = [get_settings().output_root.resolve(), get_settings().tool_versions_root.resolve()]
    cutoff = datetime.now(timezone.utc).timestamp() - older_than_hours * 3600
    targets: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for first_level in root.iterdir():
            if first_level.is_symlink():
                continue
            if first_level.is_file():
                if first_level.stat().st_mtime < cutoff:
                    targets.append(str(resolve_below(str(first_level), root)))
                continue
            if not first_level.is_dir():
                continue
            children = [item for item in first_level.iterdir() if item.is_dir() and not item.is_symlink()]
            candidates = children or [first_level]
            for candidate in candidates:
                if candidate.stat().st_mtime < cutoff:
                    targets.append(str(resolve_below(str(candidate), root)))
    return sorted(targets)


def _token(user_id: str, targets: list[str], expires_at: datetime) -> str:
    """Create an unguessable token bound to actor, targets and expiration.

    The admin ID, exact preview targets, and expiration are inputs. The output
    token keys the persisted preview and is required by execute mode.
    """

    payload = json.dumps([user_id, targets, expires_at.isoformat()], separators=(",", ":"))
    return hmac.new(get_settings().internal_token.encode(), payload.encode(), hashlib.sha256).hexdigest()


def run_cleanup(request: CleanupRequest) -> CleanupResult:
    """Create a deletion preview or execute exactly one approved preview.

    A validated admin request is the input. The output always lists preview
    targets and actual deletions; every real deletion is appended to audit.
    """

    if request.user_role != "admin":
        raise PermissionError("OpenWebUI admin role is required")
    now = datetime.now(timezone.utc)
    if request.action == "preview":
        targets = _stale_targets(max(request.older_than_hours, get_settings().cleanup_min_age_hours))
        file_ids = sorted(set(request.openwebui_file_ids))
        expires_at = now + timedelta(seconds=get_settings().cleanup_preview_ttl_seconds)
        token = _token(request.user_id, [*targets, *file_ids], expires_at)
        with _connection() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO cleanup_preview VALUES (?, ?, ?, ?, NULL)",
                (token, request.user_id, json.dumps({"paths": targets, "file_ids": file_ids}), expires_at.isoformat()),
            )
        append_event(
            token,
            "cleanup.preview",
            request.user_id,
            {"targets": targets, "openwebui_file_ids": file_ids, "expires_at": expires_at},
        )
        return CleanupResult(
            action="preview",
            preview_token=token,
            expires_at=expires_at,
            targets=targets,
            deleted=[],
            openwebui_file_ids=file_ids,
        )

    if not request.preview_token:
        raise ValueError("preview_token is required for execute")
    with _connection() as connection:
        row = connection.execute(
            "SELECT user_id, targets_json, expires_at, executed_at FROM cleanup_preview WHERE token = ?",
            (request.preview_token,),
        ).fetchone()
        if not row or row[0] != request.user_id:
            raise ValueError("preview token is invalid for this admin")
        expires_at = datetime.fromisoformat(row[2])
        if expires_at < now:
            raise ValueError("preview token has expired; request a new preview")
        if row[3]:
            raise ValueError("preview token has already been executed")
        preview = json.loads(row[1])
        targets = preview["paths"]
        file_ids = preview["file_ids"]
        deleted: list[str] = []
        for target_value in targets:
            try:
                target = resolve_below(target_value, get_settings().output_root)
            except ValueError:
                target = resolve_below(target_value, get_settings().tool_versions_root)
            if target.is_dir():
                shutil.rmtree(target)
                deleted.append(str(target))
                append_event(
                    request.preview_token,
                    "cleanup.deleted",
                    request.user_id,
                    {"path": str(target), "deleted_at": now.isoformat()},
                )
            elif target.is_file():
                target.unlink()
                deleted.append(str(target))
                append_event(
                    request.preview_token,
                    "cleanup.deleted",
                    request.user_id,
                    {"path": str(target), "deleted_at": now.isoformat()},
                )
        connection.execute(
            "UPDATE cleanup_preview SET executed_at = ? WHERE token = ?",
            (now.isoformat(), request.preview_token),
        )
    return CleanupResult(
        action="execute",
        preview_token=request.preview_token,
        expires_at=expires_at,
        targets=targets,
        deleted=deleted,
        openwebui_file_ids=file_ids,
    )
