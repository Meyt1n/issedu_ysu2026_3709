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
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.file_upload import delete_file_tree
from app.models import VisionTask
from app.review import ReviewStatus, ReviewTask

logger = logging.getLogger(__name__)


# ── Status enums ────────────────────────────────────────────────────────


class VisionTaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


VISION_MEDIA_TYPES = frozenset({"image", "video"})

_TERMINAL_STATUSES = frozenset(
    {
        VisionTaskStatus.SUCCEEDED,
        VisionTaskStatus.FAILED,
        VisionTaskStatus.TIMEOUT,
        VisionTaskStatus.CANCELLED,
    }
)


@dataclass(frozen=True)
class VisionTaskCleanupReport:
    """Safe, repeatable result of one temporary-video cleanup pass.

    The task rows and their OCR/fusion results are deliberately retained as
    audit metadata.  Only the uploaded file tree is removed.
    """

    cutoff_at: datetime
    retention_seconds: int
    dry_run: bool
    scanned: int = 0
    eligible: int = 0
    skipped_recent: int = 0
    skipped_pending_review: int = 0
    skipped_shared_file: int = 0
    deleted_artifacts: int = 0
    missing_files: int = 0
    failed_files: int = 0


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


def _as_utc(value: datetime | None, *, fallback: datetime) -> datetime:
    if value is None:
        return fallback
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _lease_deadline(now: datetime, lease_seconds: int) -> datetime:
    if lease_seconds < 30:
        raise ValueError("VISION_LEASE_SECONDS_INVALID")
    return now + timedelta(seconds=lease_seconds)


def assert_vision_task_lease(
    task: VisionTask,  # type: ignore[name-defined]
    worker_id: str,
    *,
    now: datetime | None = None,
) -> None:
    """Reject evidence from a worker whose claim was lost or expired.

    Legacy callers that transition a queued task directly still work because
    an unclaimed task has no owner.  Once a worker claims a task, however,
    every terminal write must come from that worker while its lease is live.
    """

    if task.lease_owner is None:
        return
    current = _as_utc(now, fallback=_now())
    expires_at = _as_utc(task.lease_expires_at, fallback=current)
    if task.lease_owner != worker_id or expires_at <= current:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="VISION_TASK_LEASE_LOST",
        )


def recover_expired_vision_tasks(
    session: Session,
    *,
    actor_id: str | None = None,
    limit: int = 100,
    max_attempts: int = 3,
    now: datetime | None = None,
) -> int:
    """Requeue expired leases and timeout tasks that exhausted their budget.

    Each update includes the observed status and expiry, so two workers can
    run recovery concurrently without reviving a task that another worker
    has already reclaimed.
    """

    if limit <= 0 or max_attempts <= 0:
        raise ValueError("VISION_RECOVERY_LIMIT_INVALID")
    current = _as_utc(now, fallback=_now())
    stmt = (
        select(VisionTask)
        .where(
            VisionTask.status == VisionTaskStatus.RUNNING,
            VisionTask.lease_expires_at.is_not(None),
            VisionTask.lease_expires_at <= current,
        )
        .order_by(VisionTask.lease_expires_at.asc())
        .limit(min(limit, 1_000))
    )
    if actor_id is not None:
        stmt = stmt.where(VisionTask.created_by == actor_id)

    recovered = 0
    for task in session.scalars(stmt).all():
        if (task.attempt_count or 0) >= max_attempts:
            values = {
                "status": VisionTaskStatus.TIMEOUT,
                "error_code": "WORKER_MAX_ATTEMPTS",
                "error_message": "Worker lease expired too many times; manual retry required.",
                "finished_at": current,
                "lease_owner": None,
                "lease_expires_at": None,
                "updated_at": current,
            }
        else:
            values = {
                "status": VisionTaskStatus.QUEUED,
                "lease_owner": None,
                "lease_expires_at": None,
                "updated_at": current,
            }
        updated = session.execute(
            update(VisionTask)
            .where(
                VisionTask.id == task.id,
                VisionTask.status == VisionTaskStatus.RUNNING,
                VisionTask.lease_expires_at <= current,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        recovered += int(updated.rowcount == 1)
    return recovered


def claim_vision_task(
    session: Session,
    task: VisionTask,  # type: ignore[name-defined]
    *,
    worker_id: str,
    lease_seconds: int,
    max_attempts: int = 3,
    now: datetime | None = None,
) -> VisionTask:
    """Atomically claim one queued task or reclaim an expired lease."""

    if not worker_id.strip():
        raise ValueError("VISION_WORKER_ID_REQUIRED")
    if max_attempts <= 0:
        raise ValueError("VISION_MAX_ATTEMPTS_INVALID")
    current = _as_utc(now, fallback=_now())
    deadline = _lease_deadline(current, lease_seconds)
    if task.status in _TERMINAL_STATUSES:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"VISION_TASK_NOT_CLAIMABLE_{task.status.upper()}",
        )

    attempt_count = task.attempt_count or 0
    if attempt_count >= max_attempts and task.status == VisionTaskStatus.RUNNING:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="VISION_TASK_MAX_ATTEMPTS",
        )

    claimable = or_(
        VisionTask.status == VisionTaskStatus.QUEUED,
        and_(
            VisionTask.status == VisionTaskStatus.RUNNING,
            VisionTask.lease_expires_at.is_not(None),
            VisionTask.lease_expires_at <= current,
        ),
    )
    updated = session.execute(
        update(VisionTask)
        .where(VisionTask.id == task.id, claimable)
        .values(
            status=VisionTaskStatus.RUNNING,
            lease_owner=worker_id,
            lease_expires_at=deadline,
            started_at=task.started_at or current,
            attempt_count=VisionTask.attempt_count + 1,
            error_code=None,
            error_message=None,
            updated_at=current,
        )
        .execution_options(synchronize_session=False)
    )
    if updated.rowcount != 1:
        session.refresh(task)
        if task.status == VisionTaskStatus.RUNNING and task.lease_owner:
            detail = "VISION_TASK_LEASE_HELD"
        else:
            detail = "VISION_TASK_CLAIM_CONFLICT"
        raise HTTPException(status_code=http_status.HTTP_409_CONFLICT, detail=detail)
    session.refresh(task)
    logger.info(
        "VISION_TASK_CLAIMED task=%s worker=%s attempt=%d lease_until=%s",
        task.id,
        worker_id,
        task.attempt_count,
        task.lease_expires_at,
    )
    return task


def claim_vision_tasks(
    session: Session,
    *,
    actor_id: str,
    limit: int = 10,
    lease_seconds: int = 900,
    max_attempts: int = 3,
    now: datetime | None = None,
) -> list[VisionTask]:
    """Recover this worker's stale jobs, then atomically claim a batch."""

    if limit <= 0:
        raise ValueError("VISION_CLAIM_LIMIT_INVALID")
    current = _as_utc(now, fallback=_now())
    recover_expired_vision_tasks(
        session,
        actor_id=actor_id,
        limit=min(limit * 2, 1_000),
        max_attempts=max_attempts,
        now=current,
    )
    candidates = list(
        session.scalars(
            select(VisionTask)
            .where(
                VisionTask.created_by == actor_id,
                VisionTask.status == VisionTaskStatus.QUEUED,
            )
            .order_by(VisionTask.created_at.asc())
            .limit(min(limit, 100))
        ).all()
    )
    claimed: list[VisionTask] = []
    for task in candidates:
        try:
            claimed.append(
                claim_vision_task(
                    session,
                    task,
                    worker_id=actor_id,
                    lease_seconds=lease_seconds,
                    max_attempts=max_attempts,
                    now=current,
                )
            )
        except HTTPException:
            # Another worker won the conditional update; keep claiming the
            # remaining batch rather than failing the whole poll request.
            continue
    return claimed


def renew_vision_task_lease(
    session: Session,
    task: VisionTask,  # type: ignore[name-defined]
    *,
    worker_id: str,
    lease_seconds: int,
    now: datetime | None = None,
) -> VisionTask:
    """Extend a live lease; an expired or foreign lease cannot be renewed."""

    current = _as_utc(now, fallback=_now())
    deadline = _lease_deadline(current, lease_seconds)
    updated = session.execute(
        update(VisionTask)
        .where(
            VisionTask.id == task.id,
            VisionTask.status == VisionTaskStatus.RUNNING,
            VisionTask.lease_owner == worker_id,
            VisionTask.lease_expires_at > current,
        )
        .values(lease_expires_at=deadline, updated_at=current)
        .execution_options(synchronize_session=False)
    )
    if updated.rowcount != 1:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="VISION_TASK_LEASE_LOST",
        )
    session.refresh(task)
    return task


def cleanup_expired_video_files(
    session: Session,
    household_id: str,
    *,
    retention_seconds: int,
    limit: int,
    dry_run: bool = True,
    now: datetime | None = None,
) -> VisionTaskCleanupReport:
    """Preview or remove expired video upload trees for one household.

    Only terminal video tasks are considered.  A task with a pending manual
    review or a file referenced by another vision task is protected.  The
    operation does not delete task rows, so a retry, audit lookup and erasure
    propagation can still see the original task metadata.  Re-running after a
    successful deletion is safe because missing files are reported, not raised.
    """

    if retention_seconds <= 0:
        raise ValueError("VISION_RETENTION_SECONDS_INVALID")
    if limit <= 0:
        raise ValueError("VISION_CLEANUP_LIMIT_INVALID")

    current = _as_utc(now, fallback=_now())
    cutoff = current - timedelta(seconds=retention_seconds)
    terminal_values = [status.value for status in _TERMINAL_STATUSES]
    timestamp_expr = func.coalesce(
        VisionTask.finished_at,
        VisionTask.updated_at,
        VisionTask.created_at,
    )
    tasks = list(
        session.scalars(
            select(VisionTask)
            .where(
                VisionTask.household_id == household_id,
                VisionTask.media_type == "video",
                VisionTask.status.in_(terminal_values),
            )
            .order_by(timestamp_expr.asc())
            .limit(limit)
        ).all()
    )

    task_ids = [task.id for task in tasks]
    pending_review_ids = {
        task_id
        for task_id in session.scalars(
            select(ReviewTask.vision_task_id).where(
                ReviewTask.vision_task_id.in_(task_ids),
                ReviewTask.status == ReviewStatus.PENDING_REVIEW,
            )
        ).all()
    } if task_ids else set()
    file_ids = {task.file_id for task in tasks if task.file_id}
    file_reference_counts = {
        file_id: int(count)
        for file_id, count in session.execute(
            select(VisionTask.file_id, func.count(VisionTask.id))
            .where(VisionTask.file_id.in_(file_ids))
            .group_by(VisionTask.file_id)
        ).all()
    } if file_ids else {}

    report = VisionTaskCleanupReport(
        cutoff_at=cutoff,
        retention_seconds=retention_seconds,
        dry_run=dry_run,
        scanned=len(tasks),
    )
    for task in tasks:
        terminal_at = _as_utc(
            task.finished_at or task.updated_at or task.created_at,
            fallback=current,
        )
        if terminal_at > cutoff:
            report = _replace_cleanup_report(report, skipped_recent=report.skipped_recent + 1)
            continue
        if task.id in pending_review_ids:
            report = _replace_cleanup_report(
                report,
                skipped_pending_review=report.skipped_pending_review + 1,
            )
            continue
        if file_reference_counts.get(task.file_id, 0) > 1:
            report = _replace_cleanup_report(
                report,
                skipped_shared_file=report.skipped_shared_file + 1,
            )
            continue

        report = _replace_cleanup_report(report, eligible=report.eligible + 1)
        if dry_run:
            continue
        try:
            deleted = delete_file_tree(task.file_id)
        except OSError:
            logger.warning("VISION_RETENTION_DELETE_FAILED household=%s", household_id)
            report = _replace_cleanup_report(report, failed_files=report.failed_files + 1)
            continue
        if deleted:
            report = _replace_cleanup_report(
                report,
                deleted_artifacts=report.deleted_artifacts + len(deleted),
            )
        else:
            report = _replace_cleanup_report(report, missing_files=report.missing_files + 1)

    logger.info(
        "VISION_RETENTION_CLEANUP household=%s dry_run=%s scanned=%d eligible=%d "
        "deleted=%d missing=%d failed=%d",
        household_id,
        dry_run,
        report.scanned,
        report.eligible,
        report.deleted_artifacts,
        report.missing_files,
        report.failed_files,
    )
    return report


def _replace_cleanup_report(
    report: VisionTaskCleanupReport,
    **changes: int,
) -> VisionTaskCleanupReport:
    """Keep the public report immutable while accumulating one cleanup pass."""
    return replace(report, **changes)


def _can_transition(current: str, next_: str) -> bool:
    allowed = _VALID_TRANSITIONS.get(current, set())
    return next_ in allowed


def _file_digest(path: str) -> str:
    """SHA-256 of the whole file (integrity check + receipt binding).

    HCT-414-D2: previously only the first 8 KiB were hashed, which silently
    disagreed with the quality-check receipt (full-file sha256) for any media
    larger than 8 KiB and made task creation reject valid uploads with
    QUALITY_RECEIPT_MISMATCH before this fix.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ── State transitions ───────────────────────────────────────────────────


def transition_status(
    session: Session,
    task: VisionTask,  # type: ignore[name-defined]
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
) -> VisionTask:  # noqa: F821
    """Apply a validated state transition.

    Returns the updated task.
    Raises 409 if the transition is illegal.
    """
    current = task.status
    if not _can_transition(current, next_status):
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"INVALID_TRANSITION {current} → {next_status}",
        )

    values: dict[str, Any] = {"status": next_status, "updated_at": _now()}

    if next_status == VisionTaskStatus.RUNNING:
        values["started_at"] = _now()
    elif next_status in _TERMINAL_STATUSES:
        values["finished_at"] = _now()
        if result is not None:
            values["result"] = result
        if error_code:
            values["error_code"] = error_code
            values["error_message"] = error_message or _ERROR_CODES.get(error_code, "")
        values["lease_owner"] = None
        values["lease_expires_at"] = None

    # Version tracking — recorded on terminal transitions
    if next_status in (
        VisionTaskStatus.SUCCEEDED,
        VisionTaskStatus.FAILED,
        VisionTaskStatus.TIMEOUT,
    ):
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
    if "lease_owner" in values:
        task.lease_owner = values["lease_owner"]
    if "lease_expires_at" in values:
        task.lease_expires_at = values["lease_expires_at"]
    for field in (
        "model_version",
        "preprocess_version",
        "schema_version",
        "code_version",
        "data_version",
    ):
        if field in values:
            setattr(task, field, values[field])

    logger.info(
        "VISION_TASK_TRANSITION task=%s %s → %s error=%s",
        task.id, current, next_status, error_code or "-",
    )
    return task


def retry_vision_task(session: Session, task: VisionTask) -> VisionTask:  # noqa: F821
    """Requeue one terminal failure without creating a second task record.

    A retry is deliberately limited to failed/timeout tasks.  Keeping the
    same task ID preserves the original file/member scope and makes repeated
    UI clicks safe: after the first update the conditional update no longer
    matches and the caller receives a conflict instead of another job.
    """
    if task.status not in {VisionTaskStatus.FAILED, VisionTaskStatus.TIMEOUT}:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"VISION_TASK_NOT_RETRYABLE_{task.status.upper()}",
        )

    now = _now()
    stmt = (
        update(VisionTask)
        .where(
            VisionTask.id == task.id,
            VisionTask.status.in_([VisionTaskStatus.FAILED, VisionTaskStatus.TIMEOUT]),
        )
        .values(
            status=VisionTaskStatus.QUEUED,
            error_code=None,
            error_message=None,
            result=None,
            started_at=None,
            finished_at=None,
            lease_owner=None,
            lease_expires_at=None,
            attempt_count=0,
            updated_at=now,
        )
    )
    updated = session.execute(stmt)
    if updated.rowcount != 1:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="VISION_TASK_RETRY_CONFLICT",
        )
    session.refresh(task)
    logger.info("VISION_TASK_REQUEUED task=%s", task.id)
    return task


# ── CRUD ───────────────────────────────────────────────────────────────


def _assert_matching_create_request(
    task: VisionTask,
    *,
    household_id: str,
    member_id: str | None,
    created_by: str,
    file_id: str,
    media_type: str,
    task_type: str,
    input_digest: str | None,
    model_threshold: float | None,
    preprocess_version: str | None,
    model_version: str | None,
    schema_version: str | None,
    code_version: str | None,
    data_version: str | None,
) -> None:
    if (
        task.household_id != household_id
        or task.member_id != member_id
        or task.created_by != created_by
        or task.file_id != file_id
        or task.media_type != media_type
        or task.task_type != task_type
        or task.input_digest != input_digest
        or task.model_threshold != model_threshold
        or task.preprocess_version != preprocess_version
        or task.model_version != model_version
        or task.schema_version != schema_version
        or task.code_version != code_version
        or task.data_version != data_version
    ):
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="IDEMPOTENCY_KEY_CONFLICT",
        )


def _get_task_by_idempotency_key(
    session: Session,
    idempotency_key: str,
    *,
    current_read: bool = False,
) -> VisionTask | None:
    stmt = select(VisionTask).where(VisionTask.idempotency_key == idempotency_key)
    if current_read:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return session.scalars(stmt).first()


def create_vision_task(
    session: Session,
    *,
    household_id: str,
    created_by: str,
    file_id: str,
    media_type: str = "image",
    member_id: str | None = None,
    task_type: str = "ocr",
    status: str = VisionTaskStatus.QUEUED,
    idempotency_key: str | None = None,
    model_threshold: float | None = None,
    input_digest: str | None = None,
    preprocess_version: str | None = None,
    model_version: str | None = None,
    schema_version: str | None = None,
    code_version: str | None = None,
    data_version: str | None = None,
) -> VisionTask:  # noqa: F821
    """Create a vision task, or return the matching task for an idempotent retry."""
    if media_type not in VISION_MEDIA_TYPES:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="MEDIA_TYPE_INVALID",
        )
    if idempotency_key is not None:
        existing = _get_task_by_idempotency_key(session, idempotency_key)
        if existing is not None:
            _assert_matching_create_request(
                existing,
                household_id=household_id,
                member_id=member_id,
                created_by=created_by,
                file_id=file_id,
                media_type=media_type,
                task_type=task_type,
                input_digest=input_digest,
                model_threshold=model_threshold,
                preprocess_version=preprocess_version,
                model_version=model_version,
                schema_version=schema_version,
                code_version=code_version,
                data_version=data_version,
            )
            logger.info("VISION_TASK_DEDUP key=%s existing=%s", idempotency_key, existing.id)
            return existing

    task = VisionTask(
        household_id=household_id,
        member_id=member_id,
        file_id=file_id,
        media_type=media_type,
        task_type=task_type,
        status=status,
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
    if idempotency_key is None:
        session.add(task)
        session.flush()
    else:
        try:
            with session.begin_nested():
                session.add(task)
                session.flush()
        except IntegrityError as exc:
            existing = _get_task_by_idempotency_key(
                session,
                idempotency_key,
                current_read=True,
            )
            if existing is None:
                raise exc
            _assert_matching_create_request(
                existing,
                household_id=household_id,
                member_id=member_id,
                created_by=created_by,
                file_id=file_id,
                media_type=media_type,
                task_type=task_type,
                input_digest=input_digest,
                model_threshold=model_threshold,
                preprocess_version=preprocess_version,
                model_version=model_version,
                schema_version=schema_version,
                code_version=code_version,
                data_version=data_version,
            )
            logger.info(
                "VISION_TASK_DEDUP_RACE key=%s existing=%s",
                idempotency_key,
                existing.id,
            )
            return existing
    logger.info("VISION_TASK_CREATED task=%s file=%s type=%s", task.id, file_id, task_type)
    return task


def get_vision_task(session: Session, task_id: str) -> VisionTask | None:  # noqa: F821
    return session.get(VisionTask, task_id)


def list_vision_tasks(
    session: Session,
    household_id: str,
    member_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[VisionTask]:  # noqa: F821
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
