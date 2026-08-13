"""
HCT-207: Manual review task — persist a vision task outcome, manage the
PENDING_REVIEW → CONFIRMED / CORRECTED / SKIPPED lifecycle, and write
the resulting health event in the same transaction.

Design
------
* `review_tasks` table stores the multi-candidate review record.
* Confirm / correct / skip are idempotent via a per-task idempotency key.
* Concurrent writes are serialised by an optimistic `status` guard: if the
  task is no longer PENDING_REVIEW the request returns 409 CONFLICT.
* The health event and outbox message are written in the same DB session
  (caller controls the commit boundary).
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import JSON, Column, DateTime, Index, Integer, String, func, select, update
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Base

logger = logging.getLogger(__name__)


# ── Enums ──────────────────────────────────────────────────────────────


class ReviewStatus(StrEnum):
    PENDING_REVIEW = "PENDING_REVIEW"
    CONFIRMED = "CONFIRMED"
    CORRECTED = "CORRECTED"
    SKIPPED = "SKIPPED"


class FusionStatus(StrEnum):
    MATCHED = "MATCHED"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"
    REVIEW = "REVIEW"
    LOW_QUALITY = "LOW_QUALITY"


# ── ORM model ──────────────────────────────────────────────────────────


class ReviewTask(Base):
    """Lightweight review-task row.

    Stored in table ``review_task``.  The ORM class is defined here (rather
    than in models.py) because review tasks belong to the HCT-207 domain and
    keeping them close reduces merge churn.
    """

    __tablename__ = "review_task"
    __table_args__ = (
        Index("uq_review_vision_task", "vision_task_id", unique=True),
        {"extend_existing": True},
    )

    id = Column(String(36), primary_key=True)
    vision_task_id = Column(String(36), nullable=False, index=True)
    household_id = Column(String(36), nullable=False, index=True)
    member_id = Column(String(36), nullable=False, index=True)
    status = Column(SQLEnum(ReviewStatus), nullable=False, default=ReviewStatus.PENDING_REVIEW)
    fusion_status = Column(SQLEnum(FusionStatus), nullable=True, index=True)
    candidates = Column(JSON, nullable=False, default=list)
    selected_candidate = Column(JSON, nullable=True)
    manual_payload = Column(JSON, nullable=True)
    idempotency_key = Column(String(128), nullable=True, index=True, unique=True)
    version = Column(Integer, nullable=False, default=1, server_default="1")
    fusion_context = Column(JSON, nullable=True)
    fusion_fingerprint = Column(String(64), nullable=True)
    transition_fingerprint = Column(String(64), nullable=True)
    confirmed_by = Column(String(120), nullable=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    model_version = Column(String(64), nullable=True)
    rule_version = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ── Serialisation ───────────────────────────────────────────────────────
# ReviewTaskRead Pydantic model is defined in schemas.py and imported by
# the router; keep this file focused on state transitions and CRUD.


# ── CRUD helpers ───────────────────────────────────────────────────────


def _canonical_fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def create_review_task(
    session: Session,
    *,
    vision_task_id: str,
    household_id: str,
    member_id: str,
    candidates: list[dict[str, Any]],
    fusion_status: FusionStatus,
    model_version: str | None = None,
    rule_version: str | None = None,
    idempotency_key: str | None = None,
    fusion_context: dict[str, Any] | None = None,
) -> ReviewTask:
    """Create or return the single review task for a vision task."""
    normalized_fusion_context = fusion_context or {}
    fusion_fingerprint = _canonical_fingerprint(
        {
            "household_id": household_id,
            "member_id": member_id,
            "candidates": candidates,
            "fusion_status": fusion_status.value,
            "model_version": model_version,
            "rule_version": rule_version,
            "fusion_context": normalized_fusion_context,
        }
    )
    existing = get_review_task_by_vision_task(session, vision_task_id)
    if existing is not None:
        _assert_same_review_input(
            existing,
            household_id=household_id,
            member_id=member_id,
            candidates=candidates,
            fusion_status=fusion_status,
            model_version=model_version,
            rule_version=rule_version,
            fusion_context=normalized_fusion_context,
            fusion_fingerprint=fusion_fingerprint,
        )
        return existing

    task = ReviewTask(
        id=str(__import__("uuid").uuid4()),
        vision_task_id=vision_task_id,
        household_id=household_id,
        member_id=member_id,
        status=ReviewStatus.PENDING_REVIEW,
        fusion_status=fusion_status,
        candidates=candidates,
        model_version=model_version,
        rule_version=rule_version,
        idempotency_key=idempotency_key,
        fusion_context=normalized_fusion_context,
        fusion_fingerprint=fusion_fingerprint,
    )
    try:
        with session.begin_nested():
            session.add(task)
            session.flush()
    except IntegrityError:
        session.rollback()
        existing = get_review_task_by_vision_task(session, vision_task_id)
        if existing is None:
            raise
        _assert_same_review_input(
            existing,
            household_id=household_id,
            member_id=member_id,
            candidates=candidates,
            fusion_status=fusion_status,
            model_version=model_version,
            rule_version=rule_version,
            fusion_context=normalized_fusion_context,
            fusion_fingerprint=fusion_fingerprint,
        )
        return existing
    logger.info(
        "REVIEW_TASK_CREATED task=%s vision=%s fusion=%s candidates=%d",
        task.id, vision_task_id, fusion_status.value, len(candidates),
    )
    return task


def get_review_task(session: Session, task_id: str) -> ReviewTask | None:
    return session.get(ReviewTask, task_id)


def get_review_task_by_vision_task(
    session: Session,
    vision_task_id: str,
) -> ReviewTask | None:
    """Return the review task bound to a vision task (one per vision task)."""
    return session.scalars(
        select(ReviewTask).where(ReviewTask.vision_task_id == vision_task_id)
    ).first()


def list_pending_reviews(
    session: Session,
    household_id: str,
    member_id: str | None = None,
) -> list[ReviewTask]:
    stmt = (
        select(ReviewTask)
        .where(
            ReviewTask.household_id == household_id,
            ReviewTask.status == ReviewStatus.PENDING_REVIEW,
        )
        .order_by(ReviewTask.created_at.desc())
    )
    if member_id is not None:
        stmt = stmt.where(ReviewTask.member_id == member_id)
    return list(session.scalars(stmt).all())


def list_review_tasks(
    session: Session,
    household_id: str,
    member_id: str | None = None,
) -> list[ReviewTask]:
    """All review tasks (pending and settled) so the UI can show处理记录."""
    stmt = (
        select(ReviewTask)
        .where(ReviewTask.household_id == household_id)
        .order_by(ReviewTask.created_at.desc())
    )
    if member_id is not None:
        stmt = stmt.where(ReviewTask.member_id == member_id)
    return list(session.scalars(stmt).all())


# ── Lifecycle operations ────────────────────────────────────────────────


def _normalize_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 128:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="IDEMPOTENCY_KEY_INVALID",
        )
    return normalized


def _get_current_review_task(session: Session, task_id: str) -> ReviewTask | None:
    return session.scalar(
        select(ReviewTask)
        .where(ReviewTask.id == task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _claim_transition(
    session: Session,
    task: ReviewTask,
    *,
    next_status: ReviewStatus,
    actor_id: str,
    expected_version: int | None,
    idempotency_key: str | None,
    request_payload: dict[str, Any],
    values: dict[str, Any],
) -> tuple[ReviewTask, bool]:
    normalized_key = _normalize_idempotency_key(idempotency_key)
    request_fingerprint = _canonical_fingerprint(
        {
            "actor_id": actor_id,
            "expected_version": expected_version,
            "next_status": next_status.value,
            "payload": request_payload,
        }
    )
    if (
        normalized_key is not None
        and task.status == next_status
        and task.idempotency_key == normalized_key
    ):
        if task.transition_fingerprint != request_fingerprint:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="IDEMPOTENCY_KEY_CONFLICT",
            )
        return task, False
    if task.status != ReviewStatus.PENDING_REVIEW:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"REVIEW_ALREADY_{task.status.value}",
        )

    current_version = int(task.version or 1)
    requested_version = current_version if expected_version is None else expected_version
    if requested_version != current_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="REVIEW_VERSION_CONFLICT",
        )
    if normalized_key is not None:
        reused = session.scalar(
            select(ReviewTask.id).where(
                ReviewTask.idempotency_key == normalized_key,
                ReviewTask.id != task.id,
            )
        )
        if reused is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="IDEMPOTENCY_KEY_REUSED",
            )

    transition_values = {
        **values,
        "status": next_status,
        "confirmed_by": actor_id,
        "confirmed_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "version": ReviewTask.version + 1,
        "transition_fingerprint": request_fingerprint,
    }
    if normalized_key is not None:
        transition_values["idempotency_key"] = normalized_key

    try:
        result = session.execute(
            update(ReviewTask)
            .where(
                ReviewTask.id == task.id,
                ReviewTask.status == ReviewStatus.PENDING_REVIEW,
                ReviewTask.version == requested_version,
            )
            .values(**transition_values)
            .execution_options(synchronize_session=False)
        )
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="IDEMPOTENCY_KEY_REUSED",
        ) from exc

    if result.rowcount != 1:
        current = _get_current_review_task(session, task.id)
        if (
            current is not None
            and normalized_key is not None
            and current.status == next_status
            and current.idempotency_key == normalized_key
        ):
            if current.transition_fingerprint != request_fingerprint:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="IDEMPOTENCY_KEY_CONFLICT",
                )
            return current, False
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="REVIEW_VERSION_CONFLICT",
        )

    updated = _get_current_review_task(session, task.id)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="REVIEW_VERSION_CONFLICT",
        )
    return updated, True


def confirm_review(
    session: Session,
    task: ReviewTask,
    *,
    actor_id: str,
    selected_candidate: dict[str, Any] | None = None,
    confirmation_note: str | None = None,
    idempotency_key: str | None = None,
    expected_version: int | None = None,
) -> tuple[ReviewTask, dict[str, Any]]:
    """Transition PENDING_REVIEW → CONFIRMED and build a health event.

    Returns (updated_task, health_event_dict).
    Raises 409 if the task is not in PENDING_REVIEW state.
    """
    if selected_candidate is None and len(task.candidates or []) == 1:
        selected_candidate = task.candidates[0]
    updated, _ = _claim_transition(
        session,
        task,
        next_status=ReviewStatus.CONFIRMED,
        actor_id=actor_id,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_payload={
            "selected_candidate": selected_candidate,
            "confirmation_note": confirmation_note,
        },
        values={"selected_candidate": selected_candidate},
    )

    event_dict: dict[str, Any] = {
        "event_type": "medication_confirmed",
        "source": "MANUAL_REVIEW",
        "confirmation_status": "CONFIRMED",
        "payload": updated.selected_candidate or {},
        "evidence": {
            "review_task_id": updated.id,
            "vision_task_id": updated.vision_task_id,
            "fusion_status": updated.fusion_status.value if updated.fusion_status else None,
            "fusion_context": updated.fusion_context or {},
            "confirmation_note": confirmation_note,
        },
    }
    logger.info("REVIEW_CONFIRMED task=%s actor=%s", updated.id, actor_id)
    return updated, event_dict


def correct_review(
    session: Session,
    task: ReviewTask,
    *,
    actor_id: str,
    manual_payload: dict[str, Any],
    correction_note: str | None = None,
    idempotency_key: str | None = None,
    expected_version: int | None = None,
) -> tuple[ReviewTask, dict[str, Any]]:
    """Transition PENDING_REVIEW → CORRECTED and build a compensating event.

    Returns (updated_task, health_event_dict).
    """
    original_candidates = task.candidates
    updated, _ = _claim_transition(
        session,
        task,
        next_status=ReviewStatus.CORRECTED,
        actor_id=actor_id,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_payload={
            "manual_payload": manual_payload,
            "correction_note": correction_note,
        },
        values={"manual_payload": manual_payload},
    )

    event_dict: dict[str, Any] = {
        "event_type": "medication_corrected",
        "source": "MANUAL_REVIEW",
        "confirmation_status": "CONFIRMED",
        "payload": updated.manual_payload,
        "evidence": {
            "review_task_id": updated.id,
            "vision_task_id": updated.vision_task_id,
            "fusion_status": updated.fusion_status.value if updated.fusion_status else None,
            "fusion_context": updated.fusion_context or {},
            "correction_note": correction_note,
            "original_candidates": original_candidates,
        },
    }
    logger.info("REVIEW_CORRECTED task=%s actor=%s", updated.id, actor_id)
    return updated, event_dict


def skip_review(
    session: Session,
    task: ReviewTask,
    *,
    actor_id: str,
    reason: str = "",
    idempotency_key: str | None = None,
    expected_version: int | None = None,
) -> ReviewTask:
    """Transition PENDING_REVIEW → SKIPPED. No health event is created."""
    updated, _ = _claim_transition(
        session,
        task,
        next_status=ReviewStatus.SKIPPED,
        actor_id=actor_id,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_payload={"reason": reason},
        values={},
    )
    logger.info("REVIEW_SKIPPED task=%s actor=%s reason=%s", updated.id, actor_id, reason)
    return updated
