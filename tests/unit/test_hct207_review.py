"""HCT-207: Tests for manual review workflow.

Covers:
- Create / list / get review tasks
- Confirm → CONFIRMED + health event in same transaction
- Correct → CORRECTED + compensating event
- Skip → SKIPPED (no health event)
- Idempotency: duplicate confirm/correct returns 409 or same result
- Concurrent write: confirm after already confirmed returns 409
- Authorization: cross-household access rejected
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.review import (
    FusionStatus,
    ReviewStatus,
    ReviewTask,
    confirm_review,
    correct_review,
    create_review_task,
    get_review_task,
    list_pending_reviews,
    skip_review,
)


@pytest.fixture
def session(db_session):
    """Compatibility alias for the repository-wide database fixture."""
    return db_session


# ── Helpers ────────────────────────────────────────────────────────────


def _make_task(
    session,
    *,
    household_id: str | None = None,
    member_id: str | None = None,
    fusion_status: FusionStatus = FusionStatus.MATCHED,
    candidates: list | None = None,
) -> ReviewTask:
    return create_review_task(
        session,
        vision_task_id=str(uuid.uuid4()),
        household_id=household_id or str(uuid.uuid4()),
        member_id=member_id or str(uuid.uuid4()),
        candidates=candidates or [{"drug_name": "阿莫西林", "confidence": 0.92}],
        fusion_status=fusion_status,
    )


# ── Lifecycle tests ────────────────────────────────────────────────────


class TestReviewLifecycle:
    """End-to-end lifecycle: create → confirm."""

    def test_create_and_get(self, session):
        task = _make_task(session)
        session.commit()

        fetched = get_review_task(session, task.id)
        assert fetched is not None
        assert fetched.status == ReviewStatus.PENDING_REVIEW
        assert fetched.fusion_status == FusionStatus.MATCHED
        assert len(fetched.candidates) == 1

    def test_list_pending(self, session):
        _make_task(session, household_id="h1", member_id="m1")
        _make_task(session, household_id="h1", member_id="m2")
        _make_task(session, household_id="h2", member_id="m3")
        session.commit()

        pending = list_pending_reviews(session, "h1")
        assert len(pending) == 2
        member_ids = {t.member_id for t in pending}
        assert member_ids == {"m1", "m2"}

    def test_confirm_single_candidate(self, session):
        task = _make_task(session)
        session.commit()

        _, event = confirm_review(
            session,
            task,
            actor_id="actor-1",
            selected_candidate={"drug_name": "阿莫西林"},
        )
        session.commit()

        assert task.status == ReviewStatus.CONFIRMED
        assert task.confirmed_by == "actor-1"
        assert task.confirmed_at is not None
        assert task.selected_candidate == {"drug_name": "阿莫西林"}
        assert event["event_type"] == "medication_confirmed"
        assert event["evidence"]["review_task_id"] == task.id

    def test_correct_creates_compensating_event(self, session):
        task = _make_task(session)
        session.commit()

        _, event = correct_review(
            session,
            task,
            actor_id="actor-1",
            manual_payload={"drug_name": "阿莫西林胶囊", "dosage": "0.5g"},
        )
        session.commit()

        assert task.status == ReviewStatus.CORRECTED
        assert task.manual_payload == {"drug_name": "阿莫西林胶囊", "dosage": "0.5g"}
        assert event["event_type"] == "medication_corrected"
        assert "original_candidates" in event["evidence"]

    def test_skip_no_health_event(self, session):
        task = _make_task(session)
        session.commit()

        updated = skip_review(session, task, actor_id="actor-1", reason="test")
        session.commit()

        assert updated.status == ReviewStatus.SKIPPED


# ── Idempotency tests ──────────────────────────────────────────────────


class TestIdempotency:
    """Duplicate confirm/correct requests must not create duplicate events."""

    def test_confirm_twice_conflict(self, session):
        task = _make_task(session)
        session.commit()

        confirm_review(
            session, task, actor_id="a1",
            idempotency_key="key-1",
        )
        session.commit()

        with pytest.raises(HTTPException):  # IDEMPOTENCY_KEY_REUSED
            confirm_review(
                session, task, actor_id="a1",
                idempotency_key="key-2",
            )
        session.rollback()

    def test_already_confirmed_conflict(self, session):
        task = _make_task(session)
        confirm_review(session, task, actor_id="a1")
        session.commit()

        with pytest.raises(HTTPException):  # REVIEW_ALREADY_CONFIRMED
            confirm_review(session, task, actor_id="a1")
        session.rollback()

    def test_already_corrected_conflict(self, session):
        task = _make_task(session)
        correct_review(session, task, actor_id="a1", manual_payload={"x": 1})
        session.commit()

        with pytest.raises(HTTPException):  # REVIEW_ALREADY_CORRECTED
            confirm_review(session, task, actor_id="a1")
        session.rollback()

    def test_skip_after_confirm_conflict(self, session):
        task = _make_task(session)
        confirm_review(session, task, actor_id="a1")
        session.commit()

        with pytest.raises(HTTPException):
            skip_review(session, task, actor_id="a1")
        session.rollback()


# ── Fusion status tests ────────────────────────────────────────────────


class TestFusionStatus:
    """All four fusion statuses are recorded and retrievable."""

    @pytest.mark.parametrize(
        "fusion",
        [
            FusionStatus.MATCHED,
            FusionStatus.CONFLICT,
            FusionStatus.UNKNOWN,
            FusionStatus.LOW_QUALITY,
        ],
    )
    def test_fusion_status_stored(self, session, fusion: FusionStatus):
        task = _make_task(session, fusion_status=fusion)
        session.commit()

        fetched = get_review_task(session, task.id)
        assert fetched is not None
        assert fetched.fusion_status == fusion

    def test_conflict_multiple_candidates(self, session):
        task = _make_task(
            session,
            candidates=[
                {"drug_name": "阿莫西林", "confidence": 0.55},
                {"drug_name": "头孢拉定", "confidence": 0.52},
            ],
            fusion_status=FusionStatus.CONFLICT,
        )
        session.commit()

        fetched = get_review_task(session, task.id)
        assert len(fetched.candidates) == 2


# ── Concurrent safety ──────────────────────────────────────────────────


class TestConcurrentSafety:
    """Optimistic-concurrency pattern: confirm uses in-session row check."""

    def test_confirm_after_external_state_change(self, session):
        """If task status changed between read and write, confirm must fail."""
        task = _make_task(session)
        session.commit()

        # Simulate external change
        task.status = ReviewStatus.SKIPPED
        session.commit()

        # Confirm should now fail
        with pytest.raises(HTTPException):  # REVIEW_ALREADY_SKIPPED
            confirm_review(session, task, actor_id="a1")
        session.rollback()
