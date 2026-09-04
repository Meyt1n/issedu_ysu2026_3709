"""HCT-405 household erasure: propagate deletion across local stores.

Health events stay physically immutable. Business reads hide tombstoned
households/members. Audit and backup-skip records keep identifiers and
counts only — never payload, evidence, state, or display names.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, DateTime, String, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.orm.attributes import flag_modified

from app.auth import revoke_account_pin, revoke_household_sessions
from app.config import get_settings
from app.file_upload import delete_file_tree
from app.hard_sample import HardSample, delete_hard_sample
from app.knowledge import KnowledgeChunk, KnowledgeDocument, delete_document
from app.models import (
    AccessAudit,
    Base,
    CareAuthorization,
    DigitalTwinMemory,
    FaceCredential,
    HealthEvent,
    Household,
    Member,
    VisionTask,
    new_id,
)

logger = logging.getLogger(__name__)

LAYER_NAMES = (
    "database",
    "files",
    "vectors",
    "cache",
    "hard_samples",
    "backups",
    "audit",
)
FORBIDDEN_AUDIT_KEYS = frozenset(
    {
        "payload",
        "evidence",
        "state",
        "display_name",
        "full_text",
        "ocr_tokens",
        "candidates",
    }
)
ACTIVE_VISION_STATUSES = frozenset({"queued", "running"})


class ErasureTask(Base):
    __tablename__ = "erasure_task"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    member_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    requested_by: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    layers: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_layers: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _empty_layers() -> dict[str, dict[str, Any]]:
    return {name: {"status": "pending", "count": 0} for name in LAYER_NAMES}


def _mark_layer(
    layers: dict[str, dict[str, Any]],
    name: str,
    *,
    status: str,
    count: int = 0,
) -> None:
    layers[name] = {"status": status, "count": count}


def assert_redacted_audit(data: Any) -> None:
    """Raise if a deletion audit object contains forbidden health fields."""
    if isinstance(data, dict):
        leaked = FORBIDDEN_AUDIT_KEYS.intersection(data)
        if leaked:
            raise ValueError(f"ERASURE_AUDIT_LEAK:{sorted(leaked)}")
        for value in data.values():
            assert_redacted_audit(value)
        return
    if isinstance(data, list):
        for item in data:
            assert_redacted_audit(item)


def _target_members(
    session: Session,
    household: Household,
    member_id: str | None,
) -> list[Member]:
    stmt = select(Member).where(
        Member.household_id == household.id,
        Member.deleted_at.is_(None),
    )
    if member_id is not None:
        stmt = stmt.where(Member.id == member_id)
    return list(session.scalars(stmt).all())


def _knowledge_in_scope(
    doc: KnowledgeDocument,
    *,
    household_id: str,
    member_ids: set[str],
) -> bool:
    scope = doc.permission_scope or {}
    household_ids = set(scope.get("household_ids") or [])
    scoped_members = set(scope.get("member_ids") or [])
    return household_id in household_ids or bool(scoped_members & member_ids)


def _safe_remove_tree(root: Path, target: Path) -> int:
    resolved_root = root.resolve()
    resolved = target.resolve()
    if not resolved.exists() or not resolved.is_relative_to(resolved_root):
        return 0
    removed = 0
    if resolved.is_dir():
        removed = sum(1 for path in resolved.rglob("*") if path.is_file())
        shutil.rmtree(resolved)
        return removed
    resolved.unlink(missing_ok=True)
    return 1


def _write_backup_skip_marker(
    *,
    task_id: str,
    household_id: str,
    member_ids: list[str],
    file_ids: list[str],
    requested_by: str,
    requested_at: datetime,
) -> Path:
    settings = get_settings()
    root = Path(settings.file_root).resolve()
    skip_dir = root / "backup-skip"
    skip_dir.mkdir(parents=True, exist_ok=True)
    marker = {
        "deletion_id": task_id,
        "household_id": household_id,
        "member_ids": member_ids,
        "file_ids": file_ids,
        "requested_by": requested_by,
        "requested_at": requested_at.isoformat(),
        "skip_on_restore": True,
    }
    assert_redacted_audit(marker)
    path = skip_dir / f"{task_id}.json"
    path.write_text(json.dumps(marker, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


def find_erasure_task(session: Session, task_id: str) -> ErasureTask | None:
    return session.get(ErasureTask, task_id)


def find_completed_erasure(
    session: Session,
    *,
    household_id: str,
    member_id: str | None,
) -> ErasureTask | None:
    stmt = select(ErasureTask).where(
        ErasureTask.household_id == household_id,
        ErasureTask.status == "completed",
    )
    if member_id is None:
        stmt = stmt.where(ErasureTask.member_id.is_(None))
    else:
        stmt = stmt.where(ErasureTask.member_id == member_id)
    return session.scalar(stmt.order_by(ErasureTask.requested_at.desc()))


def request_household_erasure(
    session: Session,
    household: Household,
    *,
    actor_id: str,
    member_id: str | None = None,
) -> ErasureTask:
    """Soft-hide household/member data and propagate cleanup across local layers."""
    if member_id is not None:
        member = session.get(Member, member_id)
        if member is None or member.household_id != household.id:
            raise ValueError("RESOURCE_NOT_FOUND")

    existing = find_completed_erasure(
        session,
        household_id=household.id,
        member_id=member_id,
    )
    if existing is not None and (
        (member_id is None and household.deleted_at is not None)
        or (member_id is not None and (session.get(Member, member_id).deleted_at is not None))
    ):
        return existing

    now = _utc_now()
    members = _target_members(session, household, member_id)
    member_ids = [member.id for member in members]
    layers = _empty_layers()
    error_layers: list[str] = []
    task = ErasureTask(
        household_id=household.id,
        member_id=member_id,
        requested_by=actor_id,
        requested_at=now,
        status="pending",
        layers=layers,
        scope={},
        error_layers=error_layers,
    )
    session.add(task)
    session.flush()

    event_count = 0
    vision_tasks: list[VisionTask] = []
    if member_ids:
        event_count = (
            session.scalar(
                select(func.count())
                .select_from(HealthEvent)
                .where(
                    HealthEvent.household_id == household.id,
                    HealthEvent.member_id.in_(member_ids),
                )
            )
            or 0
        )
        vision_tasks = list(
            session.scalars(
                select(VisionTask).where(
                    VisionTask.household_id == household.id,
                    VisionTask.member_id.in_(member_ids),
                )
            ).all()
        )
    file_ids = sorted({task.file_id for task in vision_tasks if task.file_id})

    tables_affected = [
        "member",
        "face_credential",
        "pin_hash",
        "auth_session",
        "care_authorization",
        "vision_task",
        "knowledge_document",
        "knowledge_chunk",
        "hard_sample",
        "training_consent",
        "export_manifest",
        "digital_twin_memory",
    ]
    if member_id is None:
        tables_affected.insert(0, "household")

    revoked = 0
    pins_deleted = 0
    sessions_revoked = 0
    try:
        credential_stmt = select(FaceCredential).where(
            FaceCredential.household_id == household.id,
        )
        if member_id is not None:
            target_actor_ids = {member.actor_id for member in members if member.actor_id}
            if target_actor_ids:
                credential_stmt = credential_stmt.where(
                    FaceCredential.actor_id.in_(target_actor_ids)
                )
            else:
                credential_stmt = credential_stmt.where(False)
        credentials = list(session.scalars(credential_stmt).all())
        credentials_deleted = 0
        target_actor_ids = {member.actor_id for member in members if member.actor_id}
        pin_actor_ids = target_actor_ids | {credential.actor_id for credential in credentials}
        if member_id is None:
            pin_actor_ids.add(household.created_by)
        for target_actor_id in pin_actor_ids:
            revoke_account_pin(target_actor_id, household.id, session)
        pins_deleted = len(pin_actor_ids)
        for credential in credentials:
            if credential.status != "DELETED" or credential.encrypted_template:
                credential.status = "DELETED"
                credential.revoked_at = credential.revoked_at or now
                credential.encrypted_template = b""
                credentials_deleted += 1
        if member_id is None:
            sessions_revoked = revoke_household_sessions(household.id, session=session)
        else:
            sessions_revoked = revoke_household_sessions(household.id, target_actor_ids, session)

        if member_ids:
            authorizations = list(
                session.scalars(
                    select(CareAuthorization).where(
                        CareAuthorization.household_id == household.id,
                        CareAuthorization.member_id.in_(member_ids),
                        CareAuthorization.revoked_at.is_(None),
                    )
                ).all()
            )
        else:
            authorizations = []
        for authorization in authorizations:
            authorization.revoked_at = now
            authorization.version += 1
            revoked += 1

        cancelled_vision = 0
        for vision_task in vision_tasks:
            if vision_task.status in ACTIVE_VISION_STATUSES:
                vision_task.status = "cancelled"
                vision_task.error_code = "HOUSEHOLD_ERASED"
                vision_task.error_message = "Cancelled by household erasure"
                cancelled_vision += 1

        for member in members:
            member.deleted_at = now
        memory_stmt = session.query(DigitalTwinMemory).filter(
            DigitalTwinMemory.household_id == household.id,
        )
        if member_id is not None:
            memory_stmt = memory_stmt.filter(DigitalTwinMemory.member_id == member_id)
        memory_deleted = memory_stmt.delete(synchronize_session=False)
        erase_household = member_id is None
        if not erase_household:
            remaining = session.scalar(
                select(func.count())
                .select_from(Member)
                .where(Member.household_id == household.id, Member.deleted_at.is_(None))
            )
            erase_household = remaining == 0
        if erase_household:
            household.deleted_at = now

        session.flush()
        _mark_layer(
            layers,
            "database",
            status="completed",
            count=len(members) + revoked + cancelled_vision + credentials_deleted + memory_deleted,
        )
    except Exception:
        logger.exception("ERASURE_DATABASE_FAILED task=%s", task.id)
        _mark_layer(layers, "database", status="failed")
        error_layers.append("database")

    files_deleted = 0
    try:
        for storage_key in file_ids:
            files_deleted += len(delete_file_tree(storage_key))
        _mark_layer(layers, "files", status="completed", count=files_deleted)
    except Exception:
        logger.exception("ERASURE_FILES_FAILED task=%s", task.id)
        _mark_layer(layers, "files", status="failed", count=files_deleted)
        error_layers.append("files")

    vectors_deleted = 0
    try:
        documents = list(
            session.scalars(
                select(KnowledgeDocument).where(KnowledgeDocument.status == "active")
            ).all()
        )
        for document in documents:
            if not _knowledge_in_scope(
                document,
                household_id=household.id,
                member_ids=set(member_ids),
            ):
                continue
            chunk_count = (
                session.scalar(
                    select(func.count())
                    .select_from(KnowledgeChunk)
                    .where(KnowledgeChunk.document_id == document.id)
                )
                or 0
            )
            delete_document(session, document.id, deleted_by=actor_id)
            vectors_deleted += chunk_count
        _mark_layer(layers, "vectors", status="completed", count=vectors_deleted)
    except Exception:
        logger.exception("ERASURE_VECTORS_FAILED task=%s", task.id)
        _mark_layer(layers, "vectors", status="failed", count=vectors_deleted)
        error_layers.append("vectors")

    cache_deleted = 0
    try:
        root = Path(get_settings().file_root).resolve()
        cache_root = root / "cache"
        for cache_id in [*member_ids, household.id]:
            cache_deleted += _safe_remove_tree(root, cache_root / cache_id)
        _mark_layer(layers, "cache", status="completed", count=cache_deleted)
    except Exception:
        logger.exception("ERASURE_CACHE_FAILED task=%s", task.id)
        _mark_layer(layers, "cache", status="failed", count=cache_deleted)
        error_layers.append("cache")

    samples_deleted = 0
    try:
        if member_ids:
            samples = list(
                session.scalars(
                    select(HardSample).where(
                        HardSample.household_id == household.id,
                        HardSample.member_id.in_(member_ids),
                        HardSample.status != "deleted",
                    )
                ).all()
            )
        else:
            samples = []
        for sample in samples:
            delete_hard_sample(session, sample, actor_id=actor_id)
            samples_deleted += 1
        _mark_layer(layers, "hard_samples", status="completed", count=samples_deleted)
    except Exception:
        logger.exception("ERASURE_HARD_SAMPLES_FAILED task=%s", task.id)
        _mark_layer(layers, "hard_samples", status="failed", count=samples_deleted)
        error_layers.append("hard_samples")

    backup_markers = 0
    try:
        _write_backup_skip_marker(
            task_id=task.id,
            household_id=household.id,
            member_ids=member_ids,
            file_ids=file_ids,
            requested_by=actor_id,
            requested_at=now,
        )
        backup_markers = 1
        _mark_layer(layers, "backups", status="completed", count=backup_markers)
    except Exception:
        logger.exception("ERASURE_BACKUP_SKIP_FAILED task=%s", task.id)
        _mark_layer(layers, "backups", status="failed", count=backup_markers)
        error_layers.append("backups")

    scope = {
        "household_id": household.id,
        "member_ids": member_ids,
        "tables_affected": tables_affected,
        "files_deleted": files_deleted,
        "vectors_deleted": vectors_deleted,
        "cache_keys_deleted": cache_deleted,
        "hard_samples_deleted": samples_deleted,
        "event_rows_retained": int(event_count),
        "authorizations_revoked": revoked if "database" not in error_layers else 0,
        "pins_deleted": pins_deleted,
        "sessions_revoked": sessions_revoked,
    }
    try:
        assert_redacted_audit(scope)
        session.add(
            AccessAudit(
                household_id=household.id,
                authorization_id=None,
                actor_id=actor_id,
                operation="ERASURE",
                action="DELETE_HOUSEHOLD" if member_id is None else "DELETE_MEMBER",
                data_field="household" if member_id is None else "member",
                purpose="data-erasure",
                outcome="SUCCESS" if not error_layers else "FAILED",
                reason=None if not error_layers else ",".join(error_layers)[:64],
            )
        )
        _mark_layer(layers, "audit", status="completed", count=1)
    except Exception:
        logger.exception("ERASURE_AUDIT_FAILED task=%s", task.id)
        _mark_layer(layers, "audit", status="failed")
        error_layers.append("audit")

    task.layers = {name: dict(value) for name, value in layers.items()}
    task.scope = dict(scope)
    task.error_layers = list(error_layers)
    task.status = "completed" if not error_layers else "failed"
    task.completed_at = _utc_now()
    flag_modified(task, "layers")
    flag_modified(task, "scope")
    flag_modified(task, "error_layers")
    session.flush()
    logger.info(
        "ERASURE_%s task=%s household=%s members=%d layers_failed=%s",
        task.status.upper(),
        task.id,
        household.id,
        len(member_ids),
        error_layers or "none",
    )
    return task
