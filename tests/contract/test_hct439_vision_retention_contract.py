"""HCT-439: Owner-only preview/execute contract for video retention."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AccessAudit, VisionTask

OWNER_HEADERS = {"X-Actor-Id": "owner"}


def _create_household(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/households",
        headers=OWNER_HEADERS,
        json={"name": "HCT-439 household"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _add_old_video(session: Session, household_id: str, file_id: str) -> VisionTask:
    old = datetime.now(UTC) - timedelta(days=2)
    task = VisionTask(
        household_id=household_id,
        created_by="owner",
        file_id=file_id,
        media_type="video",
        status="succeeded",
        finished_at=old,
        updated_at=old,
    )
    session.add(task)
    session.commit()
    return task


def test_cleanup_defaults_to_dry_run_and_execute_removes_only_file_tree(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    household = _create_household(client)
    settings = get_settings()
    previous_root = settings.file_root
    settings.file_root = str(tmp_path)
    try:
        file_id = "capture.mp4"
        task = _add_old_video(db_session, household["id"], file_id)
        (tmp_path / file_id).write_bytes(b"video")
        for directory in ("thumbnails", "cache", "index"):
            target = tmp_path / directory / file_id
            target.parent.mkdir(parents=True)
            target.write_bytes(b"derived")

        preview = client.post(
            f"/api/v1/households/{household['id']}/vision-tasks/retention-cleanup",
            headers=OWNER_HEADERS,
            json={},
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["dry_run"] is True
        assert preview.json()["eligible"] == 1
        assert (tmp_path / file_id).exists()
        preview_audit = db_session.query(AccessAudit).one()
        assert preview_audit.action == "VISION_RETENTION_PREVIEW"
        assert preview_audit.data_field == "vision_task.video_files"
        assert preview_audit.reason == "DRY_RUN"

        executed = client.post(
            f"/api/v1/households/{household['id']}/vision-tasks/retention-cleanup",
            headers=OWNER_HEADERS,
            json={"dry_run": False},
        )
        assert executed.status_code == 200, executed.text
        assert executed.json()["deleted_artifacts"] == 4
        assert not (tmp_path / file_id).exists()
        assert db_session.get(VisionTask, task.id) is not None
        assert {
            audit.action for audit in db_session.query(AccessAudit).all()
        } == {"VISION_RETENTION_PREVIEW", "VISION_RETENTION_CLEANUP"}
    finally:
        settings.file_root = previous_root


def test_cleanup_is_owner_only_and_hides_household_boundary(client: TestClient) -> None:
    household = _create_household(client)
    path = f"/api/v1/households/{household['id']}/vision-tasks/retention-cleanup"

    denied = client.post(path, headers={"X-Actor-Id": "caregiver"}, json={})
    assert denied.status_code == 404

    missing = client.post(
        f"/api/v1/households/{uuid4()}/vision-tasks/retention-cleanup",
        headers=OWNER_HEADERS,
        json={},
    )
    assert missing.status_code == 404
