"""HCT-204: Tests for vision task state machine, idempotency, file security."""

from __future__ import annotations

import uuid

import pytest
from fastapi import status

from app.models import VisionTask
from app.vision_tasks import (
    VisionTaskStatus,
    _VALID_TRANSITIONS,
    _can_transition,
    create_vision_task,
    get_vision_task,
    list_vision_tasks,
    transition_status,
)


# ── Helpers ────────────────────────────────────────────────────────────


def _make_task(session, **kwargs) -> VisionTask:
    defaults = dict(
        household_id=str(uuid.uuid4()),
        created_by="test-actor",
        file_id=f"file-{uuid.uuid4().hex[:12]}",
    )
    defaults.update(kwargs)
    return create_vision_task(session, **defaults)


# ── State machine tests ─────────────────────────────────────────────────


class TestStateMachine:
    """Valid transitions, illegal transitions, terminal states."""

    def test_queued_to_running(self, session):
        task = _make_task(session)
        session.commit()

        transition_status(session, task, VisionTaskStatus.RUNNING)
        session.commit()
        assert task.status == VisionTaskStatus.RUNNING
        assert task.started_at is not None

    def test_queued_to_cancelled(self, session):
        task = _make_task(session)
        session.commit()

        transition_status(session, task, VisionTaskStatus.CANCELLED,
                          error_code="CANCELLED_BY_USER")
        session.commit()
        assert task.status == VisionTaskStatus.CANCELLED

    def test_running_to_succeeded(self, session):
        task = _make_task(session, status=VisionTaskStatus.RUNNING)
        session.commit()

        transition_status(
            session, task, VisionTaskStatus.SUCCEEDED,
            result={"candidates": [{"drug_name": "阿莫西林", "confidence": 0.9}]},
            model_version="yolo11n-v1",
            preprocess_version="opencv-v1",
        )
        session.commit()
        assert task.status == VisionTaskStatus.SUCCEEDED
        assert task.result is not None
        assert task.model_version == "yolo11n-v1"
        assert task.finished_at is not None

    def test_running_to_failed(self, session):
        task = _make_task(session, status=VisionTaskStatus.RUNNING)
        session.commit()

        transition_status(session, task, VisionTaskStatus.FAILED,
                          error_code="MODEL_INFERENCE_ERROR",
                          error_message="OOM in inference")
        session.commit()
        assert task.status == VisionTaskStatus.FAILED
        assert task.error_code == "MODEL_INFERENCE_ERROR"

    def test_running_to_timeout(self, session):
        task = _make_task(session, status=VisionTaskStatus.RUNNING)
        session.commit()

        transition_status(session, task, VisionTaskStatus.TIMEOUT,
                          error_code="TIMEOUT")
        session.commit()
        assert task.status == VisionTaskStatus.TIMEOUT

    @pytest.mark.parametrize(
        "current,illegal",
        [
            ("succeeded", "running"),
            ("failed", "queued"),
            ("cancelled", "succeeded"),
            ("timeout", "running"),
            ("succeeded", "cancelled"),
            ("cancelled", "failed"),
        ],
    )
    def test_illegal_transition_raises(self, session, current: str, illegal: str):
        task = _make_task(session, status=VisionTaskStatus(current))
        session.commit()

        with pytest.raises(Exception):  # HTTPException 409
            transition_status(session, task, VisionTaskStatus(illegal))
        session.rollback()

    def test_terminal_states_reject_all(self, session):
        """succeeded / failed / timeout / cancelled accept zero transitions."""
        for terminal in (VisionTaskStatus.SUCCEEDED, VisionTaskStatus.FAILED,
                          VisionTaskStatus.TIMEOUT, VisionTaskStatus.CANCELLED):
            task = _make_task(session, status=terminal)
            session.commit()
            for next_ in VisionTaskStatus:
                with pytest.raises(Exception):
                    transition_status(session, task, next_)
            session.rollback()

    def test_all_valid_transitions(self, session):
        """Verify _VALID_TRANSITIONS dict covers every expected path."""
        assert VisionTaskStatus.RUNNING in _VALID_TRANSITIONS[VisionTaskStatus.QUEUED]
        assert VisionTaskStatus.CANCELLED in _VALID_TRANSITIONS[VisionTaskStatus.QUEUED]
        assert VisionTaskStatus.SUCCEEDED in _VALID_TRANSITIONS[VisionTaskStatus.RUNNING]
        assert VisionTaskStatus.FAILED in _VALID_TRANSITIONS[VisionTaskStatus.RUNNING]
        assert VisionTaskStatus.TIMEOUT in _VALID_TRANSITIONS[VisionTaskStatus.RUNNING]
        assert VisionTaskStatus.CANCELLED in _VALID_TRANSITIONS[VisionTaskStatus.RUNNING]
        for t in (VisionTaskStatus.SUCCEEDED, VisionTaskStatus.FAILED,
                   VisionTaskStatus.TIMEOUT, VisionTaskStatus.CANCELLED):
            assert _VALID_TRANSITIONS[t] == set()


# ── Idempotency tests ──────────────────────────────────────────────────


class TestIdempotency:
    def test_same_key_returns_existing_queued_task(self, session):
        key = f"idem-{uuid.uuid4().hex[:16]}"
        t1 = _make_task(session, idempotency_key=key)
        session.commit()

        t2 = create_vision_task(session, idempotency_key=key, household_id=str(uuid.uuid4()),
                                created_by="actor", file_id="f2")
        session.commit()
        assert t1.id == t2.id

    def test_different_key_creates_new_task(self, session):
        t1 = _make_task(session, idempotency_key="key-a")
        t2 = _make_task(session, idempotency_key="key-b")
        session.commit()
        assert t1.id != t2.id


# ── CRUD tests ─────────────────────────────────────────────────────────


class TestCRUD:
    def test_get_existing(self, session):
        task = _make_task(session)
        session.commit()
        fetched = get_vision_task(session, task.id)
        assert fetched is not None
        assert fetched.id == task.id

    def test_get_missing(self, session):
        fetched = get_vision_task(session, str(uuid.uuid4()))
        assert fetched is None

    def test_list_by_household(self, session):
        _make_task(session, household_id="h-1")
        _make_task(session, household_id="h-1")
        _make_task(session, household_id="h-2")
        session.commit()

        results = list_vision_tasks(session, "h-1")
        assert len(results) == 2

    def test_list_filter_by_member(self, session):
        _make_task(session, household_id="h-1", member_id="m-1")
        _make_task(session, household_id="h-1", member_id="m-2")
        session.commit()

        results = list_vision_tasks(session, "h-1", member_id="m-1")
        assert len(results) == 1
        assert results[0].member_id == "m-1"

    def test_list_filter_by_status(self, session):
        _make_task(session, status=VisionTaskStatus.SUCCEEDED)
        _make_task(session, status=VisionTaskStatus.FAILED)
        session.commit()

        results = list_vision_tasks(session, "system", status="succeeded")
        assert all(t.status == "succeeded" for t in results)


# ── Version tracking tests ─────────────────────────────────────────────


class TestVersionTracking:
    def test_versions_recorded_on_success(self, session):
        task = _make_task(session, status=VisionTaskStatus.RUNNING)
        session.commit()

        transition_status(
            session, task, VisionTaskStatus.SUCCEEDED,
            result={"ok": True},
            model_version="yolo11n-v2",
            preprocess_version="opencv-v2",
            schema_version="result-v2",
            code_version="hct-204-v2",
            data_version="dataset-v2",
        )
        session.commit()
        assert task.model_version == "yolo11n-v2"
        assert task.preprocess_version == "opencv-v2"
        assert task.schema_version == "result-v2"
        assert task.code_version == "hct-204-v2"
        assert task.data_version == "dataset-v2"

    def test_versions_recorded_on_failure(self, session):
        task = _make_task(session, status=VisionTaskStatus.RUNNING)
        session.commit()

        transition_status(
            session, task, VisionTaskStatus.FAILED,
            error_code="MODEL_NOT_FOUND",
            model_version="yolo11n-v1",
        )
        session.commit()
        assert task.model_version == "yolo11n-v1"
        assert task.error_code == "MODEL_NOT_FOUND"
