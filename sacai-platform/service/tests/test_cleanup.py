"""Two-phase cleanup tests for project-root and approval-token safety."""

import os
from pathlib import Path

import pytest


def _settings(tmp_path: Path):
    """Point cleanup roots and audit/checkpoint databases at one temp folder."""

    from app.config import get_settings

    os.environ["SACAI_OUTPUT_ROOT"] = str(tmp_path / "outputs")
    os.environ["SACAI_TOOL_VERSIONS_ROOT"] = str(tmp_path / "tool-versions")
    os.environ["SACAI_AUDIT_DB_PATH"] = str(tmp_path / "audit.sqlite3")
    os.environ["SACAI_GRAPH_DB_PATH"] = str(tmp_path / "graphs.sqlite3")
    os.environ["SACAI_CLEANUP_MIN_AGE_HOURS"] = "1"
    get_settings.cache_clear()
    return get_settings()


def test_cleanup_requires_exact_preview_and_logs_deletion(tmp_path: Path) -> None:
    """Delete only previewed roots after exact admin-token execution."""

    settings = _settings(tmp_path)
    target = settings.output_root / "user" / "old-job"
    target.mkdir(parents=True)
    (target / "report.json").write_text("{}", encoding="utf-8")
    old = target.stat().st_mtime - 10 * 3600
    os.utime(target, (old, old))

    from app.audit import list_events
    from app.cleanup import run_cleanup
    from app.schemas import CleanupRequest

    preview = run_cleanup(
        CleanupRequest(
            action="preview",
            user_id="admin",
            user_role="admin",
            older_than_hours=1,
            openwebui_file_ids=["registered-file"],
        )
    )
    assert str(target.resolve()) in preview.targets
    assert preview.openwebui_file_ids == ["registered-file"]
    result = run_cleanup(
        CleanupRequest(
            action="execute",
            user_id="admin",
            user_role="admin",
            older_than_hours=1,
            preview_token=preview.preview_token,
        )
    )
    assert str(target.resolve()) in result.deleted
    assert not target.exists()
    assert any(event["event_type"] == "cleanup.deleted" for event in list_events(preview.preview_token))
    with pytest.raises(ValueError, match="already been executed"):
        run_cleanup(
            CleanupRequest(
                action="execute",
                user_id="admin",
                user_role="admin",
                older_than_hours=1,
                preview_token=preview.preview_token,
            )
        )


def test_cleanup_refuses_non_admin(tmp_path: Path) -> None:
    """Use OpenWebUI's supplied role and reject a normal user at the service."""

    _settings(tmp_path)
    from app.cleanup import run_cleanup
    from app.schemas import CleanupRequest

    with pytest.raises(PermissionError):
        run_cleanup(
            CleanupRequest(action="preview", user_id="user", user_role="user", older_than_hours=1)
        )
