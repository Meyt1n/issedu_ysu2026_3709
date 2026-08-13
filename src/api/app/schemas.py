from datetime import datetime
from typing import Any, Literal

from ai.vision.candidate_fusion import CandidateFusionResult
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
    expected_version: int = Field(ge=1)
    selected_index: int | None = None
    confirmation_note: str | None = None


class ReviewTaskCorrect(BaseModel):
    expected_version: int = Field(ge=1)
    manual_payload: dict[str, Any] = Field(min_length=1)
    correction_note: str | None = None


class ReviewTaskSkip(BaseModel):
    expected_version: int = Field(ge=1)
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
    fusion_context: dict[str, Any] | None = None
    model_version: str | None = None
    rule_version: str | None = None
    version: int
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# ── HCT-204: Vision task schemas ──────────────────────────────────────


class VisionTaskCreate(BaseModel):
    file_id: str = Field(min_length=1, description="Reference to an uploaded file")
    member_id: str = Field(min_length=1)
    task_type: str = Field(default="ocr", min_length=1, max_length=40)
    idempotency_key: str | None = Field(default=None, max_length=128)
    model_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    quality_receipt: str | None = Field(default=None, min_length=32, max_length=2048)


class VisionTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    household_id: str
    member_id: str | None
    file_id: str
    task_type: str
    status: str
    error_code: str | None = None
    error_message: str | None = None
    result: dict[str, Any] | None = None
    preprocess_version: str | None = None
    model_version: str | None = None
    model_threshold: float | None = None
    schema_version: str | None = None
    code_version: str | None = None
    data_version: str | None = None
    input_digest: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_by: str
    created_at: datetime


class VisionFusionRead(CandidateFusionResult):
    review_task_id: str
    review_task_version: int = Field(ge=1)


class VisionQualityRead(BaseModel):
    schema_version: str
    config_version: str
    media_type: Literal["image", "video"]
    decision: Literal["PASS", "RETAKE"]
    allow_downstream: bool
    source: dict[str, Any]
    metrics: dict[str, Any]
    thresholds: dict[str, Any]
    reasons: list[str]
    retake_prompts: list[str]
    correction: dict[str, Any] | None = None
    frames: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    quality_receipt: str | None = None


# ── HCT-401: Knowledge / RAG schemas ──────────────────────────────────


class KnowledgeDocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    source: str = Field(min_length=1, max_length=120)
    license: str = Field(default="internal", max_length=60)
    version: str = Field(default="1.0", max_length=40)
    permission_scope: dict[str, Any] = Field(default_factory=dict)
    effective_from: datetime | None = None
    effective_until: datetime | None = None


class KnowledgeDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    source: str
    license: str
    version: str
    content_hash: str
    permission_scope: dict[str, Any]
    status: str
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    created_by: str
    created_at: datetime


class KnowledgeChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    chunk_index: int
    text: str
    locator: str | None = None


class KnowledgeRetrieveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    household_id: str | None = None
    member_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class KnowledgeRetrieveResponse(BaseModel):
    query: str
    results: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    query_id: str | None = None
    degraded: bool = False
    degrade_reason: str | None = None


# ── HCT-403: Ollama tool calling schemas ────────────────────────────


class AssistantMessage(BaseModel):
    role: str
    content: str | None = None


class AssistantRequest(BaseModel):
    messages: list[dict[str, Any]] = Field(min_length=1)
    model: str = Field(default="llama3.2:3b", max_length=64)
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(default=512, ge=1, le=4096)


class AssistantResponse(BaseModel):
    answer: str
    sources: list[str] = Field(default_factory=list)
    confidence: str = "low"
    escalate: bool = False
    degraded: bool = False
    degrade_reason: str | None = None


# ── HCT-208: Correction diff schemas ──────────────────────────────────


class CorrectionDiffCreate(BaseModel):
    source_event_id: str = Field(min_length=1, max_length=36)
    member_id: str = Field(min_length=1, max_length=36)
    field_path: str = Field(min_length=1, max_length=120)
    before_value: Any | None = None
    after_value: Any | None = None
    reason: str = Field(min_length=1, max_length=240)
    evidence: dict[str, Any] = Field(default_factory=dict)


class CorrectionDiffRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_event_id: str
    household_id: str
    member_id: str
    field_path: str
    before_value: Any | None = None
    after_value: Any | None = None
    reason: str
    evidence: dict[str, Any]
    operator_actor_id: str
    version: int
    created_at: datetime


# ── HCT-208: Hard sample schemas ──────────────────────────────────────


class HardSampleCreate(BaseModel):
    source_event_id: str = Field(min_length=1, max_length=36)
    member_id: str = Field(min_length=1, max_length=36)
    category: str = Field(min_length=1, max_length=20)
    note: str = Field(default="", max_length=500)


class HardSampleUpdate(BaseModel):
    status: str = Field(min_length=1, max_length=20)
    note: str | None = Field(default=None, max_length=500)


class HardSampleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_event_id: str
    household_id: str
    member_id: str
    category: str
    status: str
    note: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    deleted_by: str | None = None
    deleted_at: datetime | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime


# ── HCT-208: Training consent schemas ─────────────────────────────────


class TrainingConsentCreate(BaseModel):
    scope: dict[str, Any] = Field(default_factory=dict)
    license: str = Field(default="internal", max_length=60)


class TrainingConsentRevoke(BaseModel):
    reason: str = Field(default="", max_length=240)


class TrainingConsentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    hard_sample_id: str
    household_id: str
    member_id: str
    granted_by: str
    status: str
    scope: dict[str, Any]
    license: str
    revoked_by: str | None = None
    revoked_at: datetime | None = None
    version: int
    created_at: datetime


# ── HCT-208: Export manifest schemas ──────────────────────────────────


class ExportManifestCreate(BaseModel):
    version: str = Field(min_length=1, max_length=40)
    group_key: str = Field(min_length=1, max_length=120)
    license: str = Field(min_length=1, max_length=60)
    sample_ids: list[str] = Field(min_length=1)


class ExportManifestInvalidate(BaseModel):
    reason: str = Field(default="", max_length=240)


class ExportManifestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    version: str
    group_key: str
    license: str
    sample_ids: list[str]
    total_samples: int
    event_ids: list[str]
    content_hash: str
    created_by: str
    status: str
    invalidated_by: str | None = None
    invalidated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# ── HCT-404: Model version binding schemas ────────────────────────────


class ModelVersionBindingCreate(BaseModel):
    model_id: str = Field(min_length=1, max_length=128)
    dataset_version: str = Field(min_length=1, max_length=128)
    export_manifest_id: str | None = Field(default=None, max_length=36)
    fixed_set_hash: str = Field(min_length=1, max_length=64)
    safety_thresholds: dict[str, Any] = Field(default_factory=dict)
    comparison_report_hash: str | None = Field(default=None, max_length=64)


class ModelVersionBindingActivate(BaseModel):
    approved_by: str = Field(min_length=1, max_length=120)


class ModelVersionBindingRollback(BaseModel):
    reason: str = Field(default="", max_length=240)


class ModelVersionBindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    model_id: str
    dataset_version: str
    export_manifest_id: str | None
    fixed_set_hash: str
    release_status: str
    safety_thresholds: dict[str, Any]
    comparison_report_hash: str | None
    approved_by: str | None
    approved_at: datetime | None
    revoked_by: str | None
    revoked_at: datetime | None
    created_by: str
    created_at: datetime
    updated_at: datetime