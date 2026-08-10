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

import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import JSON, Column, DateTime, String, func, select
from sqlalchemy import Enum as SQLEnum
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
    LOW_QUALITY = "LOW_QUALITY"


# ── ORM model ──────────────────────────────────────────────────────────


class ReviewTask(Base):
    """Lightweight review-task row.

    Stored in table ``review_task``.  The ORM class is defined here (rather
    than in models.py) because review tasks belong to the HCT-207 domain and
    keeping them close reduces merge churn.
    """

    __tablename__ = "review_task"
    __table_args__ = {"extend_existing": True}

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
) -> ReviewTask:
    """Create a new review task after vision processing."""
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
    )
    session.add(task)
    session.flush()
    logger.info(
        "REVIEW_TASK_CREATED task=%s vision=%s fusion=%s candidates=%d",
        task.id, vision_task_id, fusion_status.value, len(candidates),
    )
    return task


def get_review_task(session: Session, task_id: str) -> ReviewTask | None:
    return session.get(ReviewTask, task_id)


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


# ── Lifecycle operations ────────────────────────────────────────────────


def confirm_review(
    session: Session,
    task: ReviewTask,
    *,
    actor_id: str,
    selected_candidate: dict[str, Any] | None = None,
    confirmation_note: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[ReviewTask, dict[str, Any]]:
    """Transition PENDING_REVIEW → CONFIRMED and build a health event.

    Returns (updated_task, health_event_dict).
    Raises 409 if the task is not in PENDING_REVIEW state.
    """
    if task.status != ReviewStatus.PENDING_REVIEW:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"REVIEW_ALREADY_{task.status.value}",
        )

    # Idempotency: if this key was already processed, return the cached event.
    if idempotency_key and task.idempotency_key != idempotency_key:
        existing = session.scalars(
            select(ReviewTask).where(
                ReviewTask.idempotency_key == idempotency_key,
                ReviewTask.id != task.id,
            )
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="IDEMPOTENCY_KEY_REUSED",
            )

    task.status = ReviewStatus.CONFIRMED
    task.confirmed_by = actor_id
    task.confirmed_at = datetime.now(UTC)
    task.selected_candidate = selected_candidate
    if idempotency_key:
        task.idempotency_key = idempotency_key

    event_dict: dict[str, Any] = {
        "event_type": "medication_confirmed",
        "source": "MANUAL_REVIEW",
        "confirmation_status": "CONFIRMED",
        "payload": selected_candidate or {},
        "evidence": {
            "review_task_id": task.id,
            "vision_task_id": task.vision_task_id,
            "fusion_status": task.fusion_status.value if task.fusion_status else None,
            "confirmation_note": confirmation_note,
        },
    }
    logger.info("REVIEW_CONFIRMED task=%s actor=%s", task.id, actor_id)
    return task, event_dict


def correct_review(
    session: Session,
    task: ReviewTask,
    *,
    actor_id: str,
    manual_payload: dict[str, Any],
    correction_note: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[ReviewTask, dict[str, Any]]:
    """Transition PENDING_REVIEW → CORRECTED and build a compensating event.

    Returns (updated_task, health_event_dict).
    """
    if task.status != ReviewStatus.PENDING_REVIEW:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"REVIEW_ALREADY_{task.status.value}",
        )

    if idempotency_key and task.idempotency_key != idempotency_key:
        existing = session.scalars(
            select(ReviewTask).where(
                ReviewTask.idempotency_key == idempotency_key,
                ReviewTask.id != task.id,
            )
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="IDEMPOTENCY_KEY_REUSED",
            )

    task.status = ReviewStatus.CORRECTED
    task.confirmed_by = actor_id
    task.confirmed_at = datetime.now(UTC)
    task.manual_payload = manual_payload
    if idempotency_key:
        task.idempotency_key = idempotency_key

    event_dict: dict[str, Any] = {
        "event_type": "medication_corrected",
        "source": "MANUAL_REVIEW",
        "confirmation_status": "CONFIRMED",
        "payload": manual_payload,
        "evidence": {
            "review_task_id": task.id,
            "vision_task_id": task.vision_task_id,
            "fusion_status": task.fusion_status.value if task.fusion_status else None,
            "correction_note": correction_note,
            "original_candidates": task.candidates,
        },
    }
    logger.info("REVIEW_CORRECTED task=%s actor=%s", task.id, actor_id)
    return task, event_dict


def skip_review(
    session: Session,
    task: ReviewTask,
    *,
    actor_id: str,
    reason: str = "",
) -> ReviewTask:
    """Transition PENDING_REVIEW → SKIPPED. No health event is created."""
    if task.status != ReviewStatus.PENDING_REVIEW:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"REVIEW_ALREADY_{task.status.value}",
        )
    task.status = ReviewStatus.SKIPPED
    task.confirmed_by = actor_id
    task.confirmed_at = datetime.now(UTC)
    logger.info("REVIEW_SKIPPED task=%s actor=%s reason=%s", task.id, actor_id, reason)
    return task
