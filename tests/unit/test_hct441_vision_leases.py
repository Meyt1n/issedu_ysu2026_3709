"""HCT-441: atomic vision-worker claims and stale lease recovery."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.models import VisionTask
from app.vision_tasks import (
    VisionTaskStatus,
    claim_vision_task,
    claim_vision_tasks,
    create_vision_task,
    recover_expired_vision_tasks,
    renew_vision_task_lease,
    transition_status,
)


def _make_task(session, *, actor_id: str = "worker-a", **overrides) -> VisionTask:
    values = {
        "household_id": str(uuid.uuid4()),
        "created_by": actor_id,
        "file_id": f"file-{uuid.uuid4().hex}",
    }
    attempt_count = overrides.pop("attempt_count", None)
    values.update(overrides)
    task = create_vision_task(session, **values)
    if attempt_count is not None:
        task.attempt_count = attempt_count
    return task


def test_claim_is_atomic_and_renewal_is_owner_bound(db_session) -> None:
    now = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)
    task = _make_task(db_session)
    db_session.commit()

    claimed = claim_vision_task(
        db_session,
        task,
        worker_id="worker-a",
        lease_seconds=300,
        now=now,
    )
    db_session.commit()
    assert claimed.status == VisionTaskStatus.RUNNING
    assert claimed.lease_owner == "worker-a"
    assert claimed.lease_expires_at.replace(tzinfo=UTC) == now + timedelta(seconds=300)
    assert claimed.attempt_count == 1

    with pytest.raises(HTTPException) as competing:
        claim_vision_task(
            db_session,
            claimed,
            worker_id="worker-b",
            lease_seconds=300,
            now=now + timedelta(seconds=30),
        )
    assert competing.value.detail == "VISION_TASK_LEASE_HELD"

    with pytest.raises(HTTPException) as foreign:
        renew_vision_task_lease(
            db_session,
            claimed,
            worker_id="worker-b",
            lease_seconds=300,
            now=now + timedelta(seconds=30),
        )
    assert foreign.value.detail == "VISION_TASK_LEASE_LOST"

    renewed = renew_vision_task_lease(
        db_session,
        claimed,
        worker_id="worker-a",
        lease_seconds=300,
        now=now + timedelta(seconds=30),
    )
    assert renewed.lease_expires_at.replace(tzinfo=UTC) == now + timedelta(seconds=330)

    transition_status(db_session, renewed, VisionTaskStatus.SUCCEEDED, result={"ok": True})
    db_session.commit()
    assert renewed.lease_owner is None
    assert renewed.lease_expires_at is None


def test_expired_lease_is_requeued_and_exhausted_task_times_out(db_session) -> None:
    now = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)
    requeue = _make_task(db_session, status=VisionTaskStatus.RUNNING, attempt_count=1)
    requeue.lease_owner = "dead-worker"
    requeue.lease_expires_at = now - timedelta(seconds=1)
    exhausted = _make_task(db_session, status=VisionTaskStatus.RUNNING, attempt_count=3)
    exhausted.lease_owner = "dead-worker"
    exhausted.lease_expires_at = now - timedelta(seconds=1)
    db_session.commit()

    assert recover_expired_vision_tasks(db_session, max_attempts=3, now=now) == 2
    db_session.commit()
    db_session.refresh(requeue)
    db_session.refresh(exhausted)
    assert requeue.status == VisionTaskStatus.QUEUED
    assert requeue.attempt_count == 1
    assert requeue.lease_owner is None
    assert exhausted.status == VisionTaskStatus.TIMEOUT
    assert exhausted.error_code == "WORKER_MAX_ATTEMPTS"
    assert exhausted.lease_owner is None


def test_batch_claim_is_scoped_to_actor_and_recovers_stale_work(db_session) -> None:
    now = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)
    mine = _make_task(db_session, actor_id="worker-a")
    _make_task(db_session, actor_id="worker-b")
    stale = _make_task(
        db_session, actor_id="worker-a", status=VisionTaskStatus.RUNNING, attempt_count=1
    )
    stale.lease_owner = "dead-worker"
    stale.lease_expires_at = now - timedelta(seconds=1)
    db_session.commit()

    claimed = claim_vision_tasks(
        db_session,
        actor_id="worker-a",
        limit=10,
        lease_seconds=300,
        now=now,
    )
    db_session.commit()
    assert {task.id for task in claimed} == {mine.id, stale.id}
    assert all(task.lease_owner == "worker-a" for task in claimed)
    assert all(task.attempt_count in {1, 2} for task in claimed)


def test_claim_endpoint_is_bounded_and_actor_scoped(client) -> None:
    response = client.post(
        "/api/v1/vision-tasks/claim",
        json={"limit": 100, "lease_seconds": 300},
        headers={"X-Actor-ID": "worker-a"},
    )
    assert response.status_code == 200
    assert response.json() == []

    invalid = client.post(
        "/api/v1/vision-tasks/claim",
        json={"limit": 0},
        headers={"X-Actor-ID": "worker-a"},
    )
    assert invalid.status_code == 422
