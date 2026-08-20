"""HCT-204: Tests for vision task state machine, idempotency, file security."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

import app.vision_tasks as vision_tasks
from app.models import VisionTask
from app.vision_tasks import (
    _VALID_TRANSITIONS,
    VisionTaskStatus,
    create_vision_task,
    get_vision_task,
    list_vision_tasks,
    retry_vision_task,
    transition_status,
)


@pytest.fixture
def session(db_session):
    """Compatibility alias for the repository-wide database fixture."""
    return db_session


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

    @pytest.mark.parametrize("terminal", [VisionTaskStatus.FAILED, VisionTaskStatus.TIMEOUT])
    def test_retry_requeues_same_task_without_duplicate(self, session, terminal):
        task = _make_task(session, status=VisionTaskStatus.RUNNING)
        task.result = {"partial": True}
        session.commit()
        error_code = "TIMEOUT" if terminal == VisionTaskStatus.TIMEOUT else "MODEL_INFERENCE_ERROR"
        transition_status(session, task, terminal, error_code=error_code)
        session.commit()
        task_id = task.id

        retried = retry_vision_task(session, task)
        session.commit()

        assert retried.id == task_id
        assert retried.status == VisionTaskStatus.QUEUED
        assert retried.result is None
        assert retried.error_code is None
        assert retried.error_message is None
        assert session.query(VisionTask).count() == 1

    def test_retry_rejects_success_and_second_click(self, session):
        task = _make_task(session, status=VisionTaskStatus.RUNNING)
        session.commit()
        transition_status(session, task, VisionTaskStatus.SUCCEEDED, result={"ok": True})
        session.commit()

        with pytest.raises(HTTPException) as success_exc:
            retry_vision_task(session, task)
        assert success_exc.value.detail == "VISION_TASK_NOT_RETRYABLE_SUCCEEDED"

        failed = _make_task(session, status=VisionTaskStatus.RUNNING)
        session.commit()
        transition_status(session, failed, VisionTaskStatus.FAILED, error_code="UNKNOWN")
        session.commit()
        retry_vision_task(session, failed)
        session.commit()
        with pytest.raises(HTTPException) as second_exc:
            retry_vision_task(session, failed)
        assert second_exc.value.detail == "VISION_TASK_NOT_RETRYABLE_QUEUED"

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

        with pytest.raises(HTTPException):
            transition_status(session, task, VisionTaskStatus(illegal))
        session.rollback()

    def test_terminal_states_reject_all(self, session):
        """succeeded / failed / timeout / cancelled accept zero transitions."""
        for terminal in (VisionTaskStatus.SUCCEEDED, VisionTaskStatus.FAILED,
                          VisionTaskStatus.TIMEOUT, VisionTaskStatus.CANCELLED):
            task = _make_task(session, status=terminal)
            session.commit()
            for next_ in VisionTaskStatus:
                with pytest.raises(HTTPException):
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
    def test_same_key_and_same_request_returns_existing_queued_task(self, session):
        key = f"idem-{uuid.uuid4().hex[:16]}"
        household_id = str(uuid.uuid4())
        t1 = _make_task(
            session,
            idempotency_key=key,
            household_id=household_id,
            created_by="actor",
            file_id="same-file",
        )
        session.commit()

        t2 = create_vision_task(
            session,
            idempotency_key=key,
            household_id=household_id,
            created_by="actor",
            file_id="same-file",
        )
        session.commit()
        assert t1.id == t2.id

    def test_unique_race_reloads_matching_task(
        self,
        session,
        monkeypatch: pytest.MonkeyPatch,
    ):
        key = f"idem-{uuid.uuid4().hex[:16]}"
        request = {
            "idempotency_key": key,
            "household_id": str(uuid.uuid4()),
            "member_id": str(uuid.uuid4()),
            "created_by": "actor",
            "file_id": "raced-file",
            "model_version": "model-v1",
            "schema_version": "schema-v1",
            "code_version": "code-v1",
            "data_version": "data-v1",
        }
        existing = create_vision_task(session, **request)
        session.commit()

        original_lookup = vision_tasks._get_task_by_idempotency_key

        def miss_initial_lookup(
            lookup_session,
            idempotency_key,
            *,
            current_read=False,
        ):
            if not current_read:
                return None
            return original_lookup(
                lookup_session,
                idempotency_key,
                current_read=True,
            )

        monkeypatch.setattr(
            vision_tasks,
            "_get_task_by_idempotency_key",
            miss_initial_lookup,
        )
        retried = create_vision_task(session, **request)

        assert retried.id == existing.id

    def test_same_key_with_different_request_is_conflict(self, session):
        key = f"idem-{uuid.uuid4().hex[:16]}"
        _make_task(session, idempotency_key=key)
        session.commit()

        with pytest.raises(HTTPException) as exc_info:
            create_vision_task(
                session,
                idempotency_key=key,
                household_id=str(uuid.uuid4()),
                created_by="actor",
                file_id="different-file",
            )
        assert exc_info.value.detail == "IDEMPOTENCY_KEY_CONFLICT"

    @pytest.mark.parametrize(
        ("field", "changed_value"),
        [
            ("media_type", "video"),
            ("model_version", "model-v2"),
            ("schema_version", "schema-v2"),
            ("code_version", "code-v2"),
            ("data_version", "data-v2"),
        ],
    )
    def test_same_key_rejects_changed_version_metadata(
        self,
        session,
        field: str,
        changed_value: str,
    ):
        key = f"idem-{uuid.uuid4().hex[:16]}"
        request = {
            "idempotency_key": key,
            "household_id": str(uuid.uuid4()),
            "member_id": str(uuid.uuid4()),
            "created_by": "actor",
            "file_id": "versioned-file",
            "model_version": "model-v1",
            "schema_version": "schema-v1",
            "code_version": "code-v1",
            "data_version": "data-v1",
        }
        create_vision_task(session, **request)
        session.commit()

        with pytest.raises(HTTPException) as exc_info:
            create_vision_task(
                session,
                **{**request, field: changed_value},
            )
        assert exc_info.value.detail == "IDEMPOTENCY_KEY_CONFLICT"

    def test_invalid_media_type_is_rejected(self, session):
        with pytest.raises(HTTPException) as exc_info:
            _make_task(session, media_type="document")
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == "MEDIA_TYPE_INVALID"

    def test_same_key_returns_matching_terminal_task(self, session):
        key = f"idem-{uuid.uuid4().hex[:16]}"
        household_id = str(uuid.uuid4())
        task = _make_task(
            session,
            idempotency_key=key,
            household_id=household_id,
            created_by="actor",
            file_id="terminal-file",
        )
        transition_status(session, task, VisionTaskStatus.RUNNING)
        transition_status(session, task, VisionTaskStatus.SUCCEEDED, result={"ok": True})
        session.commit()

        retried = create_vision_task(
            session,
            idempotency_key=key,
            household_id=household_id,
            created_by="actor",
            file_id="terminal-file",
        )
        assert retried.id == task.id
        assert retried.status == VisionTaskStatus.SUCCEEDED

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
