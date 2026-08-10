from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PURPOSE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class CapabilityResponse(BaseModel):
    phase: str
    available: list[str]
    unavailable: list[str]


class HouseholdCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class HouseholdRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    created_by: str
    created_at: datetime


class MemberCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    role: Literal["SELF", "DEPENDENT", "CAREGIVER"] = "DEPENDENT"
    actor_id: str | None = Field(default=None, max_length=120)


class MemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    household_id: str
    display_name: str
    role: str
    actor_id: str | None
    created_at: datetime


class AuthorizationCreate(BaseModel):
    member_id: str
    grantee_actor_id: str = Field(min_length=1, max_length=120)
    data_fields: list[str] = Field(min_length=1)
    actions: list[Literal["READ_EVENTS", "WRITE_EVENTS"]] = Field(min_length=1)
    purpose: str = Field(pattern=PURPOSE_PATTERN)
    valid_until: datetime


class AuthorizationUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    data_fields: list[str] | None = Field(default=None, min_length=1)
    actions: list[Literal["READ_EVENTS", "WRITE_EVENTS"]] | None = Field(
        default=None,
        min_length=1,
    )
    purpose: str | None = Field(default=None, pattern=PURPOSE_PATTERN)
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def require_change(self) -> "AuthorizationUpdate":
        if all(
            value is None
            for value in (self.data_fields, self.actions, self.purpose, self.valid_until)
        ):
            raise ValueError("AUTHORIZATION_UPDATE_EMPTY")
        return self


class AuthorizationRevoke(BaseModel):
    expected_version: int = Field(ge=1)


class AuthorizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    household_id: str
    member_id: str
    grantor_actor_id: str
    grantee_actor_id: str
    data_fields: list[str]
    actions: list[str]
    purpose: str
    valid_from: datetime
    valid_until: datetime
    revoked_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class AccessAuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    household_id: str
    authorization_id: str | None
    actor_id: str
    operation: str
    action: str
    data_field: str
    purpose: str | None
    outcome: str
    reason: str | None
    before_version: int | None
    after_version: int | None
    created_at: datetime


class HealthEventCreate(BaseModel):
    member_id: str
    event_type: str = Field(min_length=1, max_length=80)
    source: Literal["MANUAL"] = "MANUAL"
    confirmation_status: Literal["CONFIRMED", "UNCONFIRMED"] = "UNCONFIRMED"
    payload: dict[str, Any] = Field(min_length=1)
    evidence: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=128)
    compensates_event_id: str | None = Field(default=None, max_length=36)
    occurred_at: datetime | None = None


class HealthEventCompensationCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=80)
    payload: dict[str, Any] = Field(min_length=1)
    evidence: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=240)
    occurred_at: datetime | None = None


class HealthEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    household_id: str
    member_id: str
    sequence_no: int
    event_type: str
    source: str
    confirmation_status: str
    payload: dict[str, Any]
    evidence: dict[str, Any]
    created_by: str
    confirmed_by: str | None
    idempotency_key: str | None
    compensates_event_id: str | None
    occurred_at: datetime
    recorded_at: datetime = Field(validation_alias="created_at")
    correlation_id: str
    causation_id: str | None
    supersedes_event_id: str | None
    schema_version: int
    created_at: datetime


class MemberStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    member_id: str
    household_id: str
    state: dict[str, Any]
    last_event_id: str | None
    last_sequence: int
    version: int
    state_hash: str | None
    updated_at: datetime


class ProjectionCheckpointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    member_id: str
    household_id: str
    last_sequence: int
    last_event_id: str | None
    state_hash: str
    created_by: str
    created_at: datetime


class ProjectionReplayRequest(BaseModel):
    checkpoint_id: str | None = None


class ProjectionReplayRead(BaseModel):
    member_id: str
    checkpoint_id: str | None
    events_replayed: int
    previous_state_hash: str | None
    rebuilt_state_hash: str
    consistent_with_online: bool
    last_sequence: int
    projection_version: int


class OutboxRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_id: str
    topic: str
    status: str
    attempts: int
    available_at: datetime
    locked_at: datetime | None
    dispatched_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class OutboxDispatchRequest(BaseModel):
    max_messages: int = Field(default=100, ge=1, le=500)
    stale_after_seconds: int = Field(default=300, ge=30, le=3600)


class OutboxDispatchRead(BaseModel):
    inspected: int
    dispatched: int
    failed: int
    out_of_order: int
    recovered_stale: int


# ── HCT-307: Risk evidence schemas ──────────────────────────────────


class RiskAlertRead(BaseModel):
    """Risk alert as returned by the rules engine. Evidence is desensitized."""

    rule_id: str
    level: str  # SEVERE | WARNING | INFO | TIP
    message: str
    source_event_ids: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


class RiskListResponse(BaseModel):
    """Risk list for a household member."""

    member_id: str
    alerts: list[RiskAlertRead]
    total: int
    severe_count: int
    warning_count: int


class RiskDetailResponse(BaseModel):
    """Single risk detail with linked source events."""

    alert: RiskAlertRead
    source_events: list[dict[str, Any]] = Field(default_factory=list)


# ── HCT-207: Manual review schemas ────────────────────────────────────


class CandidateItem(BaseModel):
    drug_name: str
    confidence: float | None = None
    evidence: list[str] = Field(default_factory=list)
    dosage: str | None = None
    frequency: str | None = None


class ReviewTaskConfirm(BaseModel):
    selected_index: int | None = None
    confirmation_note: str | None = None


class ReviewTaskCorrect(BaseModel):
    manual_payload: dict[str, Any] = Field(min_length=1)
    correction_note: str | None = None


class ReviewTaskSkip(BaseModel):
    reason: str = ""


class ReviewTaskRead(BaseModel):
    """Review task for API responses (Pydantic version)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    vision_task_id: str
    household_id: str
    member_id: str
    status: str
    fusion_status: str | None = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    selected_candidate: dict[str, Any] | None = None
    manual_payload: dict[str, Any] | None = None
    model_version: str | None = None
    rule_version: str | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
