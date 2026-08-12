"""HCT-208: Correction diffs, hard sample pool, independent training consent,
and export manifest management.

Training consent is INDEPENDENT from business authorization (CareAuthorization).
It must be explicitly granted and can be revoked at any time.
"""

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models import Base, HealthEvent, new_id

logger = logging.getLogger(__name__)

# ── Enums ────────────────────────────────────────────────────────────────

HardSampleCategoryStr = str  # one of: hard_font, layout, condition, similar, foreign
VALID_CATEGORIES = frozenset({
    "hard_font", "hard_layout", "hard_condition", "hard_similar", "hard_foreign",
})


# ── Models ───────────────────────────────────────────────────────────────


class CorrectionDiff(Base):
    """Field-level correction record. Never modifies the original HealthEvent."""

    __tablename__ = "correction_diff"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_event.id", ondelete="RESTRICT"), nullable=False
    )
    household_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("household.id", ondelete="CASCADE"), nullable=False
    )
    member_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("member.id", ondelete="CASCADE"), nullable=False
    )
    field_path: Mapped[str] = mapped_column(String(120), nullable=False)
    before_value: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    after_value: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str] = mapped_column(String(240), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    operator_actor_id: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_correction_diff_source_event", "source_event_id"),
        Index("ix_correction_diff_household_member", "household_id", "member_id"),
        Index("ix_correction_diff_operator", "operator_actor_id"),
    )


class HardSample(Base):
    """Hard sample pool entry — references source event, with review lifecycle."""

    __tablename__ = "hard_sample"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_event.id", ondelete="RESTRICT"), nullable=False
    )
    household_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("household.id", ondelete="CASCADE"), nullable=False
    )
    member_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("member.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_hard_sample_source", "source_event_id"),
        Index("ix_hard_sample_household_status", "household_id", "status"),
        Index("ix_hard_sample_category", "household_id", "category"),
    )


class TrainingConsent(Base):
    """Independent, revocable training consent per sample.

    NOT derived from CareAuthorization — must be explicitly granted.
    One active consent per sample enforced at application level (SQLite-compatible).
    """

    __tablename__ = "training_consent"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    hard_sample_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("hard_sample.id", ondelete="RESTRICT"), nullable=False
    )
    household_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("household.id", ondelete="CASCADE"), nullable=False
    )
    member_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("member.id", ondelete="CASCADE"), nullable=False
    )
    granted_by: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    license: Mapped[str] = mapped_column(String(60), nullable=False, default="internal")
    revoked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_training_consent_sample", "hard_sample_id"),
        Index("ix_training_consent_status", "household_id", "status"),
    )


class ExportManifest(Base):
    """Immutable training data export record. Frozen on creation."""

    __tablename__ = "export_manifest"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    version: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    group_key: Mapped[str] = mapped_column(String(120), nullable=False)
    license: Mapped[str] = mapped_column(String(60), nullable=False)
    sample_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    total_samples: Mapped[int] = mapped_column(Integer, nullable=False)
    event_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    invalidated_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_export_manifest_group_key", "group_key"),
        Index("ix_export_manifest_status", "status"),
    )


# ── Utility ──────────────────────────────────────────────────────────────


def _canonical_hash(*, sample_ids: list[str], event_ids: list[str], version: str) -> str:
    """Deterministic SHA-256 hash of sorted sample_ids, event_ids, and version."""
    payload = json.dumps(
        {"sample_ids": sorted(sample_ids), "event_ids": sorted(event_ids), "version": version},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_category(category: str) -> None:
    if category not in VALID_CATEGORIES:
        raise ValueError(f"INVALID_CATEGORY: {category}")


# ── Correction Diff ──────────────────────────────────────────────────────


def create_correction_diff(
    session: Session,
    *,
    household_id: str,
    member_id: str,
    source_event_id: str,
    field_path: str,
    before_value: Any,
    after_value: Any,
    reason: str,
    evidence: dict[str, Any],
    operator_actor_id: str,
) -> CorrectionDiff:
    """Record a field-level correction without modifying the original event."""
    event = session.get(HealthEvent, source_event_id)
    if event is None or event.household_id != household_id:
        raise ValueError("SOURCE_EVENT_NOT_FOUND")

    # Determine version for this field path + source_event
    existing = (
        session.execute(
            select(CorrectionDiff.version)
            .where(
                CorrectionDiff.source_event_id == source_event_id,
                CorrectionDiff.field_path == field_path,
            )
            .order_by(CorrectionDiff.version.desc())
        )
        .scalars()
        .first()
    )
    next_version = (existing or 0) + 1

    diff = CorrectionDiff(
        source_event_id=source_event_id,
        household_id=household_id,
        member_id=member_id,
        field_path=field_path,
        before_value=before_value,
        after_value=after_value,
        reason=reason,
        evidence=evidence,
        operator_actor_id=operator_actor_id,
        version=next_version,
    )
    session.add(diff)
    session.flush()
    logger.info(
        "CORRECTION_DIFF_CREATED diff=%s event=%s field=%s version=%d actor=%s",
        diff.id, source_event_id, field_path, next_version, operator_actor_id,
    )
    return diff


def list_correction_diffs(
    session: Session,
    household_id: str,
    *,
    member_id: str | None = None,
    source_event_id: str | None = None,
) -> list[CorrectionDiff]:
    stmt = select(CorrectionDiff).where(CorrectionDiff.household_id == household_id)
    if member_id is not None:
        stmt = stmt.where(CorrectionDiff.member_id == member_id)
    if source_event_id is not None:
        stmt = stmt.where(CorrectionDiff.source_event_id == source_event_id)
    return list(session.scalars(stmt.order_by(CorrectionDiff.created_at.desc())).all())


def get_correction_diff(session: Session, diff_id: str) -> CorrectionDiff | None:
    return session.get(CorrectionDiff, diff_id)


# ── Hard Sample ──────────────────────────────────────────────────────────


def create_hard_sample(
    session: Session,
    *,
    household_id: str,
    member_id: str,
    source_event_id: str,
    category: str,
    note: str = "",
    created_by: str,
) -> HardSample:
    _validate_category(category)
    event = session.get(HealthEvent, source_event_id)
    if event is None or event.household_id != household_id:
        raise ValueError("SOURCE_EVENT_NOT_FOUND")

    sample = HardSample(
        source_event_id=source_event_id,
        household_id=household_id,
        member_id=member_id,
        category=category,
        status="pending",
        note=note or None,
        created_by=created_by,
    )
    session.add(sample)
    session.flush()
    logger.info("HARD_SAMPLE_CREATED sample=%s category=%s actor=%s", sample.id, category, created_by)
    return sample


def list_hard_samples(
    session: Session,
    household_id: str,
    *,
    status: str | None = None,
    category: str | None = None,
    member_id: str | None = None,
    include_deleted: bool = False,
) -> list[HardSample]:
    stmt = select(HardSample).where(HardSample.household_id == household_id)
    if not include_deleted:
        stmt = stmt.where(HardSample.status != "deleted")
    if status is not None:
        stmt = stmt.where(HardSample.status == status)
    if category is not None:
        stmt = stmt.where(HardSample.category == category)
    if member_id is not None:
        stmt = stmt.where(HardSample.member_id == member_id)
    return list(session.scalars(stmt.order_by(HardSample.created_at.desc())).all())


def get_hard_sample(session: Session, sample_id: str) -> HardSample | None:
    return session.get(HardSample, sample_id)


def update_hard_sample_status(
    session: Session,
    sample: HardSample,
    *,
    new_status: str,
    actor_id: str,
    note: str | None = None,
) -> HardSample:
    if sample.status != "pending":
        raise ValueError("SAMPLE_NOT_PENDING")
    if new_status not in ("approved", "rejected"):
        raise ValueError("INVALID_STATUS_TRANSITION")

    sample.status = new_status
    sample.reviewed_by = actor_id
    sample.reviewed_at = datetime.now(UTC)
    if note is not None:
        sample.note = note
    session.flush()
    logger.info("HARD_SAMPLE_%s sample=%s actor=%s", new_status.upper(), sample.id, actor_id)
    return sample


def delete_hard_sample(
    session: Session,
    sample: HardSample,
    *,
    actor_id: str,
) -> HardSample:
    """Soft-delete with cascade: revoke consent, invalidate manifests."""
    if sample.status == "deleted":
        raise ValueError("SAMPLE_ALREADY_DELETED")

    now = datetime.now(UTC)
    sample.status = "deleted"
    sample.deleted_by = actor_id
    sample.deleted_at = now

    # Cascade: revoke active training consent
    _revoke_active_consent_for_sample(
        session, sample.id, actor_id=actor_id, reason="sample_deleted",
    )

    # Cascade: invalidate manifests referencing this sample
    _invalidate_manifests_referencing_sample(
        session, sample.id, actor_id=actor_id, reason="sample_deleted",
    )

    session.flush()
    logger.info("HARD_SAMPLE_DELETED sample=%s actor=%s", sample.id, actor_id)
    return sample


# ── Training Consent ─────────────────────────────────────────────────────


def _get_active_consent(session: Session, hard_sample_id: str) -> TrainingConsent | None:
    return session.scalar(
        select(TrainingConsent).where(
            TrainingConsent.hard_sample_id == hard_sample_id,
            TrainingConsent.status == "active",
        )
    )


def _revoke_active_consent_for_sample(
    session: Session,
    hard_sample_id: str,
    *,
    actor_id: str,
    reason: str = "",
) -> TrainingConsent | None:
    """Revoke the active consent for a sample (internal, no permission check)."""
    consent = _get_active_consent(session, hard_sample_id)
    if consent is None:
        return None
    now = datetime.now(UTC)
    consent.status = "revoked"
    consent.revoked_by = actor_id
    consent.revoked_at = now
    consent.version += 1
    session.flush()
    logger.info(
        "TRAINING_CONSENT_REVOKED consent=%s sample=%s reason=%s actor=%s",
        consent.id, hard_sample_id, reason, actor_id,
    )
    return consent


def grant_training_consent(
    session: Session,
    *,
    hard_sample_id: str,
    household_id: str,
    member_id: str,
    granted_by: str,
    scope: dict[str, Any] | None = None,
    license: str = "internal",
) -> TrainingConsent:
    """Grant or replace training consent. Requires sample be approved and not deleted."""
    sample = session.get(HardSample, hard_sample_id)
    if sample is None or sample.household_id != household_id:
        raise ValueError("SAMPLE_NOT_FOUND")
    if sample.status == "deleted":
        raise ValueError("SAMPLE_DELETED")
    if sample.status != "approved":
        raise ValueError("SAMPLE_NOT_APPROVED")

    # Revoke existing active consent first
    _revoke_active_consent_for_sample(
        session, hard_sample_id, actor_id=granted_by, reason="replaced_by_new_grant",
    )

    consent = TrainingConsent(
        hard_sample_id=hard_sample_id,
        household_id=household_id,
        member_id=member_id,
        granted_by=granted_by,
        status="active",
        scope=scope or {},
        license=license,
    )
    session.add(consent)
    session.flush()
    logger.info(
        "TRAINING_CONSENT_GRANTED consent=%s sample=%s actor=%s",
        consent.id, hard_sample_id, granted_by,
    )
    return consent


def revoke_training_consent(
    session: Session,
    hard_sample_id: str,
    *,
    actor_id: str,
    reason: str = "",
) -> TrainingConsent:
    """Revoke training consent and cascade-invalidate manifests."""
    consent = _get_active_consent(session, hard_sample_id)
    if consent is None:
        raise ValueError("NO_ACTIVE_CONSENT")

    _revoke_active_consent_for_sample(
        session, hard_sample_id, actor_id=actor_id, reason=reason,
    )

    # Cascade: invalidate manifests referencing this sample
    _invalidate_manifests_referencing_sample(
        session, hard_sample_id, actor_id=actor_id, reason="consent_revoked",
    )

    return consent


def get_training_consent(session: Session, hard_sample_id: str) -> TrainingConsent | None:
    return _get_active_consent(session, hard_sample_id)


# ── Export Manifest ──────────────────────────────────────────────────────


def _invalidate_manifests_referencing_sample(
    session: Session,
    sample_id: str,
    *,
    actor_id: str,
    reason: str,
) -> int:
    """Invalidate all active export manifests that contain the given sample_id."""
    manifests = session.scalars(
        select(ExportManifest).where(ExportManifest.status == "active")
    ).all()

    count = 0
    now = datetime.now(UTC)
    for m in manifests:
        sample_ids: list[str] = m.sample_ids or []
        if sample_id in sample_ids:
            m.status = "invalidated"
            m.invalidated_by = actor_id
            m.invalidated_at = now
            count += 1
            logger.info(
                "EXPORT_MANIFEST_INVALIDATED manifest=%s reason=%s actor=%s",
                m.id, reason, actor_id,
            )
    if count > 0:
        session.flush()
    return count


def create_export_manifest(
    session: Session,
    *,
    household_id: str,
    version: str,
    group_key: str,
    license: str,
    sample_ids: list[str],
    created_by: str,
) -> ExportManifest:
    """Create an immutable export manifest.

    Preconditions per sample:
    - Sample exists, is approved, not deleted
    - Sample has active training consent
    - Sample belongs to this household
    """
    if not sample_ids:
        raise ValueError("NO_SAMPLES_PROVIDED")

    # Check version uniqueness
    existing = session.scalar(select(ExportManifest).where(ExportManifest.version == version))
    if existing is not None:
        raise ValueError("VERSION_ALREADY_EXISTS")

    event_ids: list[str] = []
    for sid in sample_ids:
        sample = session.get(HardSample, sid)
        if sample is None or sample.household_id != household_id:
            raise ValueError(f"SAMPLE_NOT_FOUND: {sid}")
        if sample.status == "deleted":
            raise ValueError(f"SAMPLE_DELETED: {sid}")
        if sample.status != "approved":
            raise ValueError(f"SAMPLE_NOT_APPROVED: {sid}")

        consent = _get_active_consent(session, sid)
        if consent is None:
            raise ValueError(f"TRAINING_CONSENT_REQUIRED: {sid}")

        event = session.get(HealthEvent, sample.source_event_id)
        if event is not None:
            event_ids.append(event.id)

    content_hash = _canonical_hash(
        sample_ids=sample_ids,
        event_ids=event_ids,
        version=version,
    )

    manifest = ExportManifest(
        version=version,
        group_key=group_key,
        license=license,
        sample_ids=sample_ids,
        total_samples=len(sample_ids),
        event_ids=sorted(set(event_ids)),
        content_hash=content_hash,
        created_by=created_by,
        status="active",
    )
    session.add(manifest)
    session.flush()
    logger.info(
        "EXPORT_MANIFEST_CREATED manifest=%s version=%s samples=%d hash=%s",
        manifest.id, version, len(sample_ids), content_hash,
    )
    return manifest


def invalidate_export_manifest(
    session: Session,
    manifest: ExportManifest,
    *,
    actor_id: str,
    reason: str = "",
) -> ExportManifest:
    if manifest.status != "active":
        raise ValueError("MANIFEST_NOT_ACTIVE")

    manifest.status = "invalidated"
    manifest.invalidated_by = actor_id
    manifest.invalidated_at = datetime.now(UTC)
    session.flush()
    logger.info(
        "EXPORT_MANIFEST_INVALIDATED manifest=%s reason=%s actor=%s",
        manifest.id, reason, actor_id,
    )
    return manifest


def list_export_manifests(
    session: Session,
    household_id: str | None = None,
    *,
    status: str | None = None,
    group_key: str | None = None,
) -> list[ExportManifest]:
    stmt = select(ExportManifest)
    if status is not None:
        stmt = stmt.where(ExportManifest.status == status)
    if group_key is not None:
        stmt = stmt.where(ExportManifest.group_key == group_key)
    return list(session.scalars(stmt.order_by(ExportManifest.created_at.desc())).all())


def get_export_manifest(session: Session, manifest_id: str) -> ExportManifest | None:
    return session.get(ExportManifest, manifest_id)
