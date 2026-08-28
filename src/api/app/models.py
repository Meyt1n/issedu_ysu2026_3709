from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class AuthAccount(Base):
    """Persistent local account credential and lockout state (HCT-428)."""

    __tablename__ = "auth_account"

    actor_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )


class AuthPin(Base):
    """One bcrypt PIN per actor and household; plaintext is never persisted."""

    __tablename__ = "auth_pin"

    household_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    pin_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )


class AuthSession(Base):
    """Revocable server session; only a SHA-256 token digest is stored."""

    __tablename__ = "auth_session"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    actor_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    household_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    rotated_from_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthRateLimitAttempt(Base):
    """Durable failed-auth events shared by all workers."""

    __tablename__ = "auth_rate_limit_attempt"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    rate_key: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class AuthPinChallenge(Base):
    """Durable, single-use step-up challenge metadata (no PIN/code)."""

    __tablename__ = "auth_pin_challenge"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    household_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    session_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    grant_consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthFaceChallenge(Base):
    """Durable, single-use face-login challenge (HCT-425).

    Only opaque metadata is stored: challenge id, actor/household binding and
    expiry. No biometric payload ever reaches this table. Family 1:N
    challenges reuse the row with the family sentinel actor id.
    """

    __tablename__ = "auth_face_challenge"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    household_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Household(Base):
    __tablename__ = "household"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    time_zone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="UTC", server_default="UTC"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


class Member(Base):
    __tablename__ = "member"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("household.id", ondelete="CASCADE"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="DEPENDENT")
    actor_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


class FaceCredential(Base):
    """Encrypted face template bound to one household account.

    Raw registration frames never reach this table.  ``encrypted_template`` is
    an authenticated Fernet envelope produced by ``face_credentials.py``.
    """

    __tablename__ = "face_credential"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("household.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    encrypted_template: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    credential_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    consent_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE", index=True)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )


class CareAuthorization(Base):
    __tablename__ = "care_authorization"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("household.id", ondelete="CASCADE"), nullable=False
    )
    member_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("member.id", ondelete="CASCADE"), nullable=False
    )
    grantor_actor_id: Mapped[str] = mapped_column(String(120), nullable=False)
    grantee_actor_id: Mapped[str] = mapped_column(String(120), nullable=False)
    data_fields: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    actions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    purpose: Mapped[str] = mapped_column(String(200), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AccessAudit(Base):
    __tablename__ = "access_audit"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(String(36), nullable=False)
    authorization_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_id: Mapped[str] = mapped_column(String(120), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    data_field: Mapped[str] = mapped_column(String(120), nullable=False)
    purpose: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    before_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    after_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now()
    )


class HealthEvent(Base):
    __tablename__ = "health_event"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("household.id", ondelete="CASCADE"), nullable=False
    )
    member_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("member.id", ondelete="CASCADE"), nullable=False
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    confirmation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    # 待确认事实可以先保存，但只有 CONFIRMED 事件才有确认人。
    confirmed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # HCT-103: 幂等键、兼容补偿引用与可重放事件元数据。
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    causation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    compensates_event_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("health_event.id", ondelete="SET NULL"),
        nullable=True,
    )
    supersedes_event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_event.id", ondelete="RESTRICT"), nullable=True
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutboxMessage(Base):
    __tablename__ = "outbox_message"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_event.id", ondelete="CASCADE"), nullable=False
    )
    topic: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    dispatched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now()
    )


class MemberStateProjection(Base):
    __tablename__ = "member_state_projection"

    member_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("member.id", ondelete="CASCADE"), primary_key=True
    )
    household_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("household.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    last_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectionCheckpoint(Base):
    __tablename__ = "projection_checkpoint"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    member_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("member.id", ondelete="CASCADE"), nullable=False
    )
    household_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("household.id", ondelete="CASCADE"), nullable=False
    )
    last_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    last_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now()
    )


Index("ix_member_household_actor", Member.household_id, Member.actor_id)
Index(
    "uq_face_credential_active_account",
    FaceCredential.household_id,
    FaceCredential.actor_id,
    FaceCredential.status,
    unique=True,
    sqlite_where=FaceCredential.status == "ACTIVE",
    postgresql_where=FaceCredential.status == "ACTIVE",
)
Index(
    "ix_event_household_member_time",
    HealthEvent.household_id,
    HealthEvent.member_id,
    HealthEvent.created_at,
)
Index(
    "uq_event_household_member_sequence",
    HealthEvent.household_id,
    HealthEvent.member_id,
    HealthEvent.sequence_no,
    unique=True,
)
Index(
    "uq_event_household_idempotency",
    HealthEvent.household_id,
    HealthEvent.idempotency_key,
    unique=True,
)
Index("uq_event_supersedes", HealthEvent.supersedes_event_id, unique=True)
Index("ix_event_correlation", HealthEvent.correlation_id)
Index("uq_outbox_event", OutboxMessage.event_id, unique=True)
Index("ix_outbox_status_available", OutboxMessage.status, OutboxMessage.available_at)
Index(
    "uq_checkpoint_member_sequence",
    ProjectionCheckpoint.member_id,
    ProjectionCheckpoint.last_sequence,
    unique=True,
)
Index("ix_auth_household_member", CareAuthorization.household_id, CareAuthorization.member_id)
Index("ix_auth_grantor_actor_id", CareAuthorization.grantor_actor_id)
Index("ix_auth_grantee_actor_id", CareAuthorization.grantee_actor_id)
Index("ix_audit_household_time", AccessAudit.household_id, AccessAudit.created_at)
Index("ix_audit_authorization", AccessAudit.authorization_id)
Index("ix_audit_request_id", AccessAudit.request_id)


# ── HCT-204: Vision task ───────────────────────────────────────────────


class VisionTask(Base):
    """Tracks the lifecycle of an asynchronous vision (OCR / barcode) job.

    Status transitions
    ------------------
    queued  → running → succeeded | failed | timeout
    any     → cancelled
    """

    __tablename__ = "vision_task"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("household.id", ondelete="CASCADE"), nullable=False, index=True
    )
    member_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    file_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    media_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="image", server_default="image", index=True
    )
    task_type: Mapped[str] = mapped_column(String(40), nullable=False, default="ocr")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Idempotency: the client-provided key; unique to prevent duplicate jobs.
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128), nullable=True, unique=True, index=True
    )
    # Input integrity reference (sha256 hex or similar hash of the source file).
    input_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Versioning — all sub-systems contributing to this task.
    preprocess_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_threshold: Mapped[float | None] = mapped_column(nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    code_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    data_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Result blob — candidate detections / OCR text / barcode values.
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # HCT-441: workers claim a task with a short-lived lease.  The lease
    # owner is deliberately an actor id so the evidence endpoint can reject
    # stale or competing workers before they publish a result.
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )


class RiskAcknowledgement(Base):
    """Minimal receipt for acknowledging one current rule result."""

    __tablename__ = "risk_acknowledgement"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("household.id", ondelete="CASCADE"), nullable=False
    )
    member_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("member.id", ondelete="CASCADE"), nullable=False
    )
    rule_id: Mapped[str] = mapped_column(String(80), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    acknowledged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now()
    )


Index(
    "uq_risk_ack_household_idempotency",
    RiskAcknowledgement.household_id,
    RiskAcknowledgement.idempotency_key,
    unique=True,
)
Index(
    "uq_risk_ack_current_signal",
    RiskAcknowledgement.household_id,
    RiskAcknowledgement.member_id,
    RiskAcknowledgement.rule_id,
    RiskAcknowledgement.risk_fingerprint,
    unique=True,
)


class RiskDisposition(Base):
    """Auditable handling action for one computed risk signal (HCT-462).

    A disposition is deliberately separate from ``RiskAcknowledgement``: the
    existing acknowledgement endpoint remains compatible while a risk can
    accumulate a history of handoffs, snoozes and notes.  Only the rule
    version/fingerprint and minimal action metadata are stored; no risk or
    health-event payload is copied into this table.
    """

    __tablename__ = "risk_disposition"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("household.id", ondelete="CASCADE"), nullable=False
    )
    member_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("member.id", ondelete="CASCADE"), nullable=False
    )
    rule_id: Mapped[str] = mapped_column(String(80), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    target_actor_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    snooze_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actor_id: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now()
    )


Index(
    "uq_risk_disposition_household_idempotency",
    RiskDisposition.household_id,
    RiskDisposition.idempotency_key,
    unique=True,
)
Index(
    "ix_risk_disposition_signal_created",
    RiskDisposition.household_id,
    RiskDisposition.member_id,
    RiskDisposition.rule_id,
    RiskDisposition.created_at,
)
