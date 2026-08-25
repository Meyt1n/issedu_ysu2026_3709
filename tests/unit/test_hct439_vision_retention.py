"""HCT-439: safe and repeatable temporary-video retention policy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import app.vision_tasks as vision_tasks
from app.models import VisionTask
from app.review import ReviewStatus, ReviewTask
from app.vision_tasks import VisionTaskStatus, cleanup_expired_video_files


def _task(
    session,
    *,
    household_id: str,
    file_id: str,
    status: VisionTaskStatus = VisionTaskStatus.SUCCEEDED,
    finished_at: datetime | None,
) -> VisionTask:
    task = VisionTask(
        household_id=household_id,
        created_by="owner",
        file_id=file_id,
        media_type="video",
        status=status,
        finished_at=finished_at,
        updated_at=finished_at or datetime.now(UTC),
    )
    session.add(task)
    session.flush()
    return task


def test_dry_run_and_execute_protect_review_shared_and_recent_files(
    db_session,
    monkeypatch,
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    household_id = str(uuid4())
    old = now - timedelta(days=2)
    recent = now - timedelta(minutes=5)
    eligible = _task(db_session, household_id=household_id, file_id="eligible.mp4", finished_at=old)
    _task(db_session, household_id=household_id, file_id="recent.mp4", finished_at=recent)
    _task(
        db_session,
        household_id=household_id,
        file_id="active.mp4",
        status=VisionTaskStatus.RUNNING,
        finished_at=None,
    )
    pending = _task(db_session, household_id=household_id, file_id="pending.mp4", finished_at=old)
    db_session.add(
        ReviewTask(
            id=str(uuid4()),
            vision_task_id=pending.id,
            household_id=household_id,
            member_id=str(uuid4()),
            status=ReviewStatus.PENDING_REVIEW,
            candidates=[],
        )
    )
    _task(db_session, household_id=household_id, file_id="shared.mp4", finished_at=old)
    _task(db_session, household_id=household_id, file_id="shared.mp4", finished_at=old)
    db_session.commit()

    deleted_keys: list[str] = []
    monkeypatch.setattr(
        vision_tasks,
        "delete_file_tree",
        lambda key: deleted_keys.append(key) or [key, f"thumbnails/{key}"],
    )

    preview = cleanup_expired_video_files(
        db_session,
        household_id,
        retention_seconds=86_400,
        limit=100,
        dry_run=True,
        now=now,
    )
    assert preview.scanned == 5
    assert preview.eligible == 1
    assert preview.skipped_recent == 1
    assert preview.skipped_pending_review == 1
    assert preview.skipped_shared_file == 2
    assert preview.deleted_artifacts == 0
    assert deleted_keys == []

    executed = cleanup_expired_video_files(
        db_session,
        household_id,
        retention_seconds=86_400,
        limit=100,
        dry_run=False,
        now=now,
    )
    assert executed.eligible == 1
    assert executed.deleted_artifacts == 2
    assert deleted_keys == ["eligible.mp4"]
    assert db_session.get(VisionTask, eligible.id) is not None


def test_cleanup_is_idempotent_when_file_was_already_removed(db_session, monkeypatch) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    household_id = str(uuid4())
    _task(
        db_session,
        household_id=household_id,
        file_id="gone.mp4",
        finished_at=now - timedelta(days=2),
    )
    db_session.commit()
    monkeypatch.setattr(vision_tasks, "delete_file_tree", lambda _key: [])

    report = cleanup_expired_video_files(
        db_session,
        household_id,
        retention_seconds=86_400,
        limit=10,
        dry_run=False,
        now=now,
    )
    assert report.eligible == 1
    assert report.missing_files == 1
    assert report.failed_files == 0
