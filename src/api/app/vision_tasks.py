"""
HCT-204: Vision task — asynchronous OCR / barcode processing pipeline.

Workflow
--------
queued  →  running  →  succeeded | failed | timeout
any      →  cancelled

The task result stores detected candidates (drug name, barcode value,
OCR text blocks).  Consumer (HCT-206 candidate fusion / HCT-207 review)
picks up the result and creates a review task.
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import VisionTask

logger = logging.getLogger(__name__)


# ── Status enums ────────────────────────────────────────────────────────


class VisionTaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


# Valid transitions: current_status → set of allowed next statuses
_VALID_TRANSITIONS: dict[str, set[str]] = {
    VisionTaskStatus.QUEUED: {VisionTaskStatus.RUNNING, VisionTaskStatus.CANCELLED},
    VisionTaskStatus.RUNNING: {
        VisionTaskStatus.SUCCEEDED,
        VisionTaskStatus.FAILED,
        VisionTaskStatus.TIMEOUT,
        VisionTaskStatus.CANCELLED,
    },
    VisionTaskStatus.SUCCEEDED: set(),  # terminal
    VisionTaskStatus.FAILED: set(),  # terminal
    VisionTaskStatus.TIMEOUT: set(),  # terminal
    VisionTaskStatus.CANCELLED: set(),  # terminal
}

# Error codes for terminal failure states
_ERROR_CODES: dict[str, str] = {
    "PREPROCESS_FAILED": "Image / video preprocessing failed",
    "MODEL_NOT_FOUND": "Vision model weights not available",
    "MODEL_INFERENCE_ERROR": "Model inference crashed",
    "TIMEOUT": "Processing exceeded time limit",
    "UNKNOWN": "Unknown processing error",
}

# ── Helpers ─────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(UTC)


def _can_transition(current: str, next_: str) -> bool:
    allowed = _VALID_TRANSITIONS.get(current, set())
    return next_ in allowed


def _file_digest(path: str) -> str:
    """SHA-256 of the first 8 KB of the file (fast integrity check)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ── State transitions ───────────────────────────────────────────────────


def transition_status(
    session: Session,
    task: "VisionTask",  # type: ignore[name-defined]
    next_status: str,
    *,
    result: dict[str, Any] | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    model_version: str | None = None,
    preprocess_version: str | None = None,
    schema_version: str | None = None,
    code_version: str | None = None,
    data_version: str | None = None,
) -> "VisionTask":  # noqa: F821
    """Apply a validated state transition.

    Returns the updated task.
    Raises 409 if the transition is illegal.
    """
    current = task.status
    if not _can_transition(current, next_status):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"INVALID_TRANSITION {current} → {next_status}",
        )

    values: dict[str, Any] = {"status": next_status, "updated_at": _now()}

    if next_status == VisionTaskStatus.RUNNING:
        values["started_at"] = _now()
    elif next_status in (
        VisionTaskStatus.SUCCEEDED,
        VisionTaskStatus.FAILED,
        VisionTaskStatus.TIMEOUT,
    ):
        values["finished_at"] = _now()
        if result is not None:
            values["result"] = result
        if error_code:
            values["error_code"] = error_code
            values["error_message"] = error_message or _ERROR_CODES.get(error_code, "")

    # Version tracking — recorded on terminal transitions
    if next_status in (VisionTaskStatus.SUCCEEDED, VisionTaskStatus.FAILED, VisionTaskStatus.TIMEOUT):
        if model_version is not None:
            values["model_version"] = model_version
        if preprocess_version is not None:
            values["preprocess_version"] = preprocess_version
        if schema_version is not None:
            values["schema_version"] = schema_version
        if code_version is not None:
            values["code_version"] = code_version
        if data_version is not None:
            values["data_version"] = data_version

    stmt = (
        update(VisionTask)
        .where(VisionTask.id == task.id)
        .values(**values)
    )
    session.execute(stmt)
    task.status = next_status
    task.result = values.get("result", task.result)
    task.error_code = values.get("error_code", task.error_code)
    task.error_message = values.get("error_message", task.error_message)
    if "started_at" in values:
        task.started_at = values["started_at"]
    if "finished_at" in values:
        task.finished_at = values["finished_at"]
    for field in ("model_version", "preprocess_version", "schema_version", "code_version", "data_version"):
        if field in values:
            setattr(task, field, values[field])

    logger.info(
        "VISION_TASK_TRANSITION task=%s %s → %s error=%s",
        task.id, current, next_status, error_code or "-",
    )
    return task


# ── CRUD ───────────────────────────────────────────────────────────────


def create_vision_task(
    session: Session,
    *,
    household_id: str,
    created_by: str,
    file_id: str,
    member_id: str | None = None,
    task_type: str = "ocr",
    idempotency_key: str | None = None,
    model_threshold: float | None = None,
    input_digest: str | None = None,
    preprocess_version: str | None = None,
    model_version: str | None = None,
    schema_version: str | None = None,
    code_version: str | None = None,
    data_version: str | None = None,
) -> "VisionTask":  # noqa: F821
    """Create a new vision task.  Idempotent — returns existing task if the
    idempotency key matches a queued or running task."""
    if idempotency_key is not None:
        existing = session.scalars(
            select(VisionTask).where(
                VisionTask.idempotency_key == idempotency_key,
                VisionTask.status.in_([VisionTaskStatus.QUEUED, VisionTaskStatus.RUNNING]),
            )
        ).first()
        if existing is not None:
            logger.info("VISION_TASK_DEDUP key=%s existing=%s", idempotency_key, existing.id)
            return existing

    task = VisionTask(
        household_id=household_id,
        member_id=member_id,
        file_id=file_id,
        task_type=task_type,
        status=VisionTaskStatus.QUEUED,
        idempotency_key=idempotency_key,
        input_digest=input_digest,
        preprocess_version=preprocess_version,
        model_version=model_version,
        model_threshold=model_threshold,
        schema_version=schema_version,
        code_version=code_version,
        data_version=data_version,
        created_by=created_by,
    )
    session.add(task)
    session.flush()
    logger.info("VISION_TASK_CREATED task=%s file=%s type=%s", task.id, file_id, task_type)
    return task


def get_vision_task(session: Session, task_id: str) -> "VisionTask | None":  # noqa: F821
    return session.get(VisionTask, task_id)


def list_vision_tasks(
    session: Session,
    household_id: str,
    member_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list["VisionTask"]:  # noqa: F821
    stmt = (
        select(VisionTask)
        .where(VisionTask.household_id == household_id)
        .order_by(VisionTask.created_at.desc())
        .limit(limit)
    )
    if member_id is not None:
        stmt = stmt.where(VisionTask.member_id == member_id)
    if status is not None:
        stmt = stmt.where(VisionTask.status == status)
    return list(session.scalars(stmt).all())
