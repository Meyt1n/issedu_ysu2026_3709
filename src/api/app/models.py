from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Household(Base):
    __tablename__ = "household"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    confirmation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    # 待确认事实可以先保存，但只有 CONFIRMED 事件才有确认人。
    confirmed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # HCT-103: 幂等键与补偿事件
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True, unique=True
    )
    compensates_event_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("health_event.id", ondelete="SET NULL"),
        nullable=True,
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


Index("ix_member_household_actor", Member.household_id, Member.actor_id)
Index(
    "ix_event_household_member_time",
    HealthEvent.household_id,
    HealthEvent.member_id,
    HealthEvent.created_at,
)
Index("ix_auth_household_member", CareAuthorization.household_id, CareAuthorization.member_id)
Index("ix_auth_grantor_actor_id", CareAuthorization.grantor_actor_id)
Index("ix_auth_grantee_actor_id", CareAuthorization.grantee_actor_id)
Index("ix_audit_household_time", AccessAudit.household_id, AccessAudit.created_at)
Index("ix_audit_authorization", AccessAudit.authorization_id)


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
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now()
    )

