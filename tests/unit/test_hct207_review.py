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
from sqlalchemy.orm import sessionmaker

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
    fusion_context: dict | None = None,
) -> ReviewTask:
    return create_review_task(
        session,
        vision_task_id=str(uuid.uuid4()),
        household_id=household_id or str(uuid.uuid4()),
        member_id=member_id or str(uuid.uuid4()),
        candidates=candidates or [{"drug_name": "阿莫西林", "confidence": 0.92}],
        fusion_status=fusion_status,
        fusion_context=fusion_context,
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
        fusion_context = {
            "thresholds": {"matched_score": 0.8},
            "versions": {"fusion_rule_version": "v1"},
        }
        task = _make_task(session, fusion_context=fusion_context)
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
        assert task.version == 2
        assert event["event_type"] == "medication_confirmed"
        assert event["evidence"]["review_task_id"] == task.id
        assert event["evidence"]["fusion_context"] == fusion_context

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

    def test_confirm_without_candidate_is_rejected(self, session):
        """No caller may write a confirmed event with an empty payload.

        An UNKNOWN result carries zero candidates; with multiple candidates
        the caller must choose one.  Both situations previously produced a
        ``medication_confirmed`` event with payload ``{}`` when this library
        function was called directly (the HTTP route had its own guard).
        """
        # ``_make_task`` swaps a falsy candidate list for its default, so an
        # UNKNOWN task with truly zero candidates is created directly.
        no_candidates = create_review_task(
            session,
            vision_task_id=str(uuid.uuid4()),
            household_id=str(uuid.uuid4()),
            member_id=str(uuid.uuid4()),
            candidates=[],
            fusion_status=FusionStatus.UNKNOWN,
        )
        several = _make_task(
            session,
            candidates=[
                {"drug_name": "阿莫西林", "confidence": 0.55},
                {"drug_name": "头孢拉定", "confidence": 0.52},
            ],
            fusion_status=FusionStatus.CONFLICT,
        )
        session.commit()

        for task in (no_candidates, several):
            with pytest.raises(HTTPException) as exc_info:
                confirm_review(session, task, actor_id="actor-1")
            assert exc_info.value.detail == "REVIEW_CANDIDATE_REQUIRED"
            session.rollback()
            assert get_review_task(session, task.id).status == ReviewStatus.PENDING_REVIEW


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

    def test_legacy_task_without_fusion_fingerprint_cannot_match_retry(self, session):
        task = _make_task(session)
        session.commit()
        task.fusion_context = None
        task.fusion_fingerprint = None
        session.commit()

        with pytest.raises(HTTPException) as exc_info:
            create_review_task(
                session,
                vision_task_id=task.vision_task_id,
                household_id=task.household_id,
                member_id=task.member_id,
                candidates=task.candidates,
                fusion_status=task.fusion_status,
            )
        assert exc_info.value.detail == "REVIEW_TASK_FUSION_CONFLICT"

    def test_confirm_retry_with_same_key_returns_same_transition(self, session):
        task = _make_task(session)
        session.commit()

        _, first_event = confirm_review(
            session,
            task,
            actor_id="a1",
            idempotency_key="key-1",
            expected_version=1,
        )
        session.commit()
        retried_task, retried_event = confirm_review(
            session,
            task,
            actor_id="a1",
            idempotency_key="key-1",
            expected_version=1,
        )

        assert retried_task.version == 2
        assert retried_event == first_event

    def test_confirm_retry_with_same_key_rejects_different_payload(self, session):
        task = _make_task(session)
        session.commit()

        confirm_review(
            session,
            task,
            actor_id="a1",
            selected_candidate={"drug_name": "first"},
            confirmation_note="first note",
            idempotency_key="confirm-payload-key",
            expected_version=1,
        )
        session.commit()

        with pytest.raises(HTTPException) as exc_info:
            confirm_review(
                session,
                task,
                actor_id="a1",
                selected_candidate={"drug_name": "different"},
                confirmation_note="first note",
                idempotency_key="confirm-payload-key",
                expected_version=1,
            )
        assert exc_info.value.detail == "IDEMPOTENCY_KEY_CONFLICT"

    def test_correct_retry_with_same_key_rejects_different_payload(self, session):
        task = _make_task(session)
        session.commit()

        correct_review(
            session,
            task,
            actor_id="a1",
            manual_payload={"drug_name": "first"},
            correction_note="first note",
            idempotency_key="correct-payload-key",
            expected_version=1,
        )
        session.commit()

        with pytest.raises(HTTPException) as exc_info:
            correct_review(
                session,
                task,
                actor_id="a1",
                manual_payload={"drug_name": "different"},
                correction_note="first note",
                idempotency_key="correct-payload-key",
                expected_version=1,
            )
        assert exc_info.value.detail == "IDEMPOTENCY_KEY_CONFLICT"

    def test_skip_retry_with_same_key_rejects_different_reason(self, session):
        task = _make_task(session)
        session.commit()

        skip_review(
            session,
            task,
            actor_id="a1",
            reason="first reason",
            idempotency_key="skip-payload-key",
            expected_version=1,
        )
        session.commit()

        with pytest.raises(HTTPException) as exc_info:
            skip_review(
                session,
                task,
                actor_id="a1",
                reason="different reason",
                idempotency_key="skip-payload-key",
                expected_version=1,
            )
        assert exc_info.value.detail == "IDEMPOTENCY_KEY_CONFLICT"

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
            FusionStatus.REVIEW,
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

    def test_stale_second_session_cannot_transition_same_version(self, session):
        task = _make_task(session)
        session.commit()
        session_factory = sessionmaker(
            bind=session.get_bind(),
            autoflush=False,
            expire_on_commit=False,
        )
        competing_session = session_factory()
        try:
            stale_task = get_review_task(competing_session, task.id)
            assert stale_task is not None

            confirm_review(
                session,
                task,
                actor_id="first",
                idempotency_key="first-transition",
                expected_version=1,
            )
            session.commit()

            with pytest.raises(HTTPException) as exc_info:
                correct_review(
                    competing_session,
                    stale_task,
                    actor_id="second",
                    manual_payload={"drug_name": "stale correction"},
                    idempotency_key="second-transition",
                    expected_version=1,
                )
            assert exc_info.value.detail == "REVIEW_VERSION_CONFLICT"
            competing_session.rollback()
        finally:
            competing_session.close()
