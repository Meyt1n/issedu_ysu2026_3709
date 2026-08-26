from datetime import datetime
from typing import Any, Literal

from ai.vision.candidate_fusion import CandidateFusionResult
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.time_zone import validate_iana_time_zone

PURPOSE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"
ACTOR_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$"


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class AuthCredentials(BaseModel):
    # The same actor-id charset used for member account binding: rejecting
    # whitespace/control characters at registration keeps log lines and audit
    # rows injection-free and every registered account bindable to a member.
    actor_id: str = Field(min_length=1, max_length=120, pattern=ACTOR_ID_PATTERN)
    password: str = Field(min_length=8, max_length=256)


class PinLoginCredentials(BaseModel):
    household_id: str = Field(min_length=1, max_length=120)
    actor_id: str = Field(min_length=1, max_length=120)
    pin: str = Field(pattern=r"^[0-9]{6}$")


class FaceChallengeRequest(BaseModel):
    household_id: str = Field(min_length=1, max_length=120)
    actor_id: str = Field(min_length=1, max_length=120, pattern=ACTOR_ID_PATTERN)


class FamilyFaceChallengeRequest(BaseModel):
    household_id: str = Field(min_length=1, max_length=120)


class FaceChallengeRead(BaseModel):
    challenge_id: str
    expires_at: float


class PinSetRequest(BaseModel):
    household_id: str = Field(min_length=1, max_length=120)
    pin: str = Field(pattern=r"^[0-9]{6}$")


class AuthSessionRequest(BaseModel):
    session_token: str = Field(min_length=32, max_length=256)


class AuthSessionRead(BaseModel):
    actor_id: str
    session_token: str
    expires_at: float
    household_id: str | None = None


class FaceCredentialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    household_id: str
    actor_id: str
    algorithm_version: str
    feature_version: str
    credential_version: int
    consent_version: str
    status: Literal["ACTIVE", "REVOKED", "DELETED"]
    created_by: str
    consented_at: datetime
    revoked_at: datetime | None
    created_at: datetime
    upgrade_recommended: bool = False
    template_count: int = 1


class FaceAuthFailureSummaryRead(BaseModel):
    """Desensitized FACE auth failure buckets; never includes scores or templates."""

    days: int
    totals: dict[str, int]
    by_day: dict[str, dict[str, int]]


# ── HCT-427: step-up confirmation and session revalidation ─────────

# Action codes stay ASCII and short so they can be logged and compared safely.
STEP_UP_ACTION_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"


class SessionIntrospectRead(BaseModel):
    """Live session behind the caller's Bearer token; no credential is returned."""

    actor_id: str
    household_id: str | None
    issued_at: float
    expires_at: float


class StepUpChallengeRequest(BaseModel):
    action: str = Field(pattern=STEP_UP_ACTION_PATTERN)
    # Optional: resolved server-side when the actor has a PIN in exactly one household.
    household_id: str | None = Field(default=None, min_length=1, max_length=120)
    method: Literal["pin"] = "pin"


class StepUpChallengeRead(BaseModel):
    """Deliberately carries no PIN: the caller re-enters its own household PIN."""

    challenge_id: str
    action: str
    household_id: str
    expires_at: float


class StepUpVerifyRequest(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=128)
    action: str = Field(pattern=STEP_UP_ACTION_PATTERN)
    code: str = Field(pattern=r"^[0-9]{6}$")
    method: Literal["pin"] = "pin"


class StepUpGrantRead(BaseModel):
    # `status` is kept so the already shipped mobile adapter (MOB-133) can assert
    # a confirmed grant without another release.
    status: Literal["confirmed"] = "confirmed"
    challenge_id: str
    action: str
    confirmed_at: float


class CapabilityResponse(BaseModel):
    phase: str
    available: list[str]
    unavailable: list[str]
    knowledge_admin_configured: bool = False
    model_release_admin_configured: bool = False
    model_release_dual_control: bool = True
    owner_requires_access_purpose: bool = False


class SecurityDashboardRead(BaseModel):
    """Teaching-oriented security counters for households owned by the caller."""

    household_count: int = 0
    access_allowed: int = 0
    access_denied: int = 0
    file_owner_cleanups: int = 0
    auth_failures: int = 0
    model_release_events: int = 0
    recent_denied: list[dict[str, Any]] = Field(default_factory=list)


class HouseholdCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    time_zone: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("time_zone")
    @classmethod
    def validate_time_zone(cls, value: str | None) -> str | None:
        return None if value is None else validate_iana_time_zone(value)


class HouseholdUpdate(BaseModel):
    time_zone: str = Field(min_length=1, max_length=64)

    @field_validator("time_zone")
    @classmethod
    def validate_time_zone(cls, value: str) -> str:
        return validate_iana_time_zone(value)


class HouseholdRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    created_by: str
    time_zone: str
    created_at: datetime


class MemberCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    role: Literal["SELF", "DEPENDENT", "CAREGIVER"] = "DEPENDENT"
    actor_id: str | None = Field(default=None, max_length=120, pattern=ACTOR_ID_PATTERN)


class MemberAccountBindingUpdate(BaseModel):
    """Bind a local family member to the actor used at login."""

    actor_id: str = Field(min_length=1, max_length=120, pattern=ACTOR_ID_PATTERN)


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
    actions: list[Literal["READ_EVENTS", "WRITE_EVENTS", "ACK_RISK"]] = Field(min_length=1)
    purpose: str = Field(pattern=PURPOSE_PATTERN)
    valid_until: datetime


class AuthorizationUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    data_fields: list[str] | None = Field(default=None, min_length=1)
    actions: list[Literal["READ_EVENTS", "WRITE_EVENTS", "ACK_RISK"]] | None = Field(
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
    request_id: str | None
    before_version: int | None
    after_version: int | None
    created_at: datetime


class AccessAuditPageRead(BaseModel):
    items: list[AccessAuditRead]
    next_cursor: str | None = None
    has_more: bool = False


class AccessAuditSummaryRead(BaseModel):
    total: int
    by_action: dict[str, int]
    by_outcome: dict[str, int]
    generated_at: datetime


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


class HealthEventPageRead(BaseModel):
    items: list[HealthEventRead]
    next_cursor: str | None = None
    has_more: bool = False


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


class PlanWorkbenchActionRead(BaseModel):
    action: Literal["CONFIRM", "DEFER", "SKIP", "MISS"]
    recorded_at: datetime
    reason: str | None = None
    delay_hours: int | None = None


class PlanWorkbenchItemRead(BaseModel):
    plan_event_id: str
    drug: str
    schedule: str
    dose: str | None = None
    times: list[str] = Field(default_factory=list)
    start_date: str | None = None
    end_date: str | None = None
    status: Literal["NORMAL", "REMINDER", "ESCALATED", "COMPLETED"]
    next_action_at: datetime
    last_action: PlanWorkbenchActionRead | None = None
    action_history: list[PlanWorkbenchActionRead] = Field(default_factory=list)
    allowed_actions: list[Literal["CONFIRM", "DEFER", "SKIP", "MISS"]]


class PlanWorkbenchRead(BaseModel):
    member_id: str
    generated_at: datetime
    plans: list[PlanWorkbenchItemRead]


class PlanAutomationRead(BaseModel):
    member_id: str
    evaluated_at: datetime
    created_events: list[HealthEventRead] = Field(default_factory=list)
    notified_caregiver_actor_ids: list[str] = Field(default_factory=list)


class DashboardDayCountRead(BaseModel):
    day: str
    count: int


class DashboardSummaryRead(BaseModel):
    generated_at: datetime
    member_count: int
    events_today: int
    events_total: int
    severe_count: int
    warning_count: int
    info_count: int
    pending_reviews: int
    pending_outbox: int
    week_series: list[DashboardDayCountRead]


class RelationshipGraphNodeRead(BaseModel):
    id: str
    category: Literal["drug", "allergy", "disease", "plan", "caregiver"]
    label: str
    source_event_id: str
    source_recorded_at: datetime
    source_created_by: str


class RelationshipGraphRead(BaseModel):
    member_id: str
    generated_at: datetime
    events_count: int
    last_event_id: str | None
    nodes: list[RelationshipGraphNodeRead]


# ── HCT-307: Risk evidence schemas ──────────────────────────────────


class RiskAcknowledgementCreate(BaseModel):
    rule_version: str = Field(min_length=1, max_length=64)
    risk_fingerprint: str = Field(min_length=64, max_length=64)


class RiskAcknowledgementRead(BaseModel):
    receipt_id: str
    household_id: str
    member_id: str
    rule_id: str
    rule_version: str
    risk_fingerprint: str
    actor_id: str
    acknowledged_at: datetime
    replayed: bool = False


class RiskAlertRead(BaseModel):
    """Risk alert as returned by the rules engine. Evidence is desensitized."""

    rule_id: str
    level: str  # SEVERE | WARNING | INFO | TIP
    message: str
    source_event_ids: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    rule_version: str
    risk_fingerprint: str
    acknowledgement: RiskAcknowledgementRead | None = None
    # HCT-458: server-authoritative merge/budget explanation.  These fields
    # contain only an opaque grouping key, counts, status and a redacted
    # evidence summary; no event payload is exposed.
    deduplication_key: str = Field(default="", max_length=64)
    merged_count: int = Field(default=1, ge=1)
    budget_status: Literal["VISIBLE", "DEFERRED"] = "VISIBLE"
    budget_reason: str = Field(default="", max_length=160)
    next_visible_at: datetime | None = None
    evidence_summary: str = Field(default="", max_length=200)


class RiskListResponse(BaseModel):
    """Risk list for a household member."""

    member_id: str
    alerts: list[RiskAlertRead]
    total: int
    severe_count: int
    warning_count: int
    ruleset_version: str
    non_severe_budget: int
    suppressed_count: int


class RiskDetailResponse(BaseModel):
    """Single risk detail with linked source events."""

    alert: RiskAlertRead
    source_events: list[dict[str, Any]] = Field(default_factory=list)


# ── HCT-207: Manual review schemas ────────────────────────────────────


class MedicationReviewPayload(BaseModel):
    """Whitelist for medication confirm / correct health-event payloads.

    Aligns with HCT-207 candidate cards and the fields HCT-103 / HCT-435
    projection reads from ``medication_confirmed`` / ``medication_corrected``
    events.  Unknown keys are rejected so a dirty dict cannot land in the
    immutable event log.
    """

    model_config = ConfigDict(extra="forbid")

    drug_name: str = Field(min_length=1, max_length=200)
    drug: str | None = Field(default=None, max_length=200)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    dosage: str | None = Field(default=None, max_length=120)
    frequency: str | None = Field(default=None, max_length=120)
    candidate_id: str | None = Field(default=None, max_length=128)
    rank: int | None = Field(default=None, ge=1)
    conflicts: list[str] = Field(default_factory=list)
    specification: str | None = Field(default=None, max_length=200)
    manufacturer: str | None = Field(default=None, max_length=200)
    active_ingredients: list[Any] = Field(default_factory=list)
    indications: list[Any] = Field(default_factory=list)
    cautions: list[Any] = Field(default_factory=list)
    contraindications: list[Any] = Field(default_factory=list)
    interaction_warnings: list[Any] = Field(default_factory=list)
    master_data_version: str | None = Field(default=None, max_length=128)
    expiry_date: str | None = Field(default=None, max_length=40)
    stock: Any = None
    ingredient: str | None = Field(default=None, max_length=200)


class CandidateItem(BaseModel):
    """Compact candidate card shown in review UI (subset of the whitelist)."""

    drug_name: str = Field(min_length=1, max_length=200)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    dosage: str | None = None
    frequency: str | None = None


class ReviewTaskConfirm(BaseModel):
    expected_version: int = Field(ge=1)
    selected_index: int | None = None
    confirmation_note: str | None = None


class ReviewTaskCorrect(BaseModel):
    expected_version: int = Field(ge=1)
    manual_payload: MedicationReviewPayload
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
    media_type: Literal["image", "video"] = Field(default="image")
    member_id: str | None = Field(default=None)
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
    media_type: Literal["image", "video"]
    task_type: str
    status: str
    error_code: str | None = None
    error_message: str | None = None
    error_detail: dict[str, Any] | None = None
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
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    attempt_count: int = Field(default=0, ge=0)
    created_by: str
    created_at: datetime

    @model_validator(mode="after")
    def derive_error_detail(self) -> "VisionTaskRead":
        if not self.error_code:
            self.error_detail = None
            return self
        actions = {
            "PREPROCESS_FAILED": "请检查图片格式、清晰度和文件是否完整后重新处理。",
            "MODEL_NOT_FOUND": "本地视觉模型不可用，请启动视觉 worker 或检查模型配置。",
            "MODEL_INFERENCE_ERROR": "视觉模型处理失败，请查看本地 worker 状态后重新处理。",
            "TIMEOUT": "任务超过本地处理时限，请确认 worker 正常运行后重新处理。",
            "UNKNOWN": "本地识别发生未知错误，请保留任务编号并重新处理。",
        }
        retryable = self.status in {"failed", "timeout"}
        self.error_detail = {
            "code": self.error_code,
            "message": self.error_message or "未提供错误详情。",
            "retryable": retryable,
            "next_action": actions.get(self.error_code, "请刷新任务状态并联系项目维护者。"),
        }
        return self


class VisionTaskClaimRequest(BaseModel):
    """Bounded worker claim request; the actor header identifies the worker."""

    limit: int = Field(default=10, ge=1, le=100)
    lease_seconds: int | None = Field(default=None, ge=30, le=86_400)


class VisionTaskLeaseRequest(BaseModel):
    """Optional lease extension for a long-running local inference."""

    lease_seconds: int | None = Field(default=None, ge=30, le=86_400)


class VisionTaskCleanupRequest(BaseModel):
    """Owner-controlled cleanup pass; preview is the safe default."""

    dry_run: bool = True
    limit: int = Field(default=100, ge=1, le=1_000)


class VisionTaskCleanupRead(BaseModel):
    cutoff_at: datetime
    retention_seconds: int
    dry_run: bool
    scanned: int
    eligible: int
    skipped_recent: int
    skipped_pending_review: int
    skipped_shared_file: int
    deleted_artifacts: int
    missing_files: int
    failed_files: int


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


class KnowledgeDocumentDetailRead(KnowledgeDocumentRead):
    """Read-only document detail: metadata plus full text and chunk previews."""

    content: str = ""
    chunk_count: int = 0
    chunks: list[KnowledgeChunkRead] = Field(default_factory=list)


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


class KnowledgeQueryAuditRead(BaseModel):
    """Minimal actor-scoped retrieval audit; never returns query text."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    query_digest: str = Field(min_length=64, max_length=64)
    query_length: int = Field(ge=0)
    household_id: str | None = None
    member_id: str | None = None
    returned_count: int = Field(ge=0)
    top_chunk_count: int = Field(ge=0)
    created_at: datetime


class KnowledgeQueryAuditPageRead(BaseModel):
    items: list[KnowledgeQueryAuditRead]
    next_cursor: str | None = None
    has_more: bool


# ── HCT-403: Ollama tool calling schemas ────────────────────────────


class AssistantMessage(BaseModel):
    role: str
    content: str | None = None


class AssistantCitation(BaseModel):
    document_id: str
    version: str
    chunk_id: str
    document_title: str | None = None
    text: str | None = None
    locator: str | None = None


AssistantQueryType = Literal[
    "URGENT",
    "MEDICATION_SAFETY",
    "SYMPTOM_MEDICATION",
    "MEDICATION_RECORD",
    "FAMILY_RECORD",
    "RULE_EVIDENCE",
    "GENERAL",
]


class AssistantRequest(BaseModel):
    messages: list[dict[str, Any]] = Field(min_length=1)
    model: str | None = Field(default=None, max_length=64)
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(default=512, ge=1, le=16384)
    # Keep existing API clients on HCT-403's single-agent contract.  The web
    # demo opts into multi-agent mode explicitly so this additive field cannot
    # change legacy tool-call tests or integrations unexpectedly.
    agent_mode: Literal["single", "multi_agent"] = "single"
    allow_network_search: bool = False
    query_type_override: AssistantQueryType | None = None
    assistant_session_id: str | None = Field(default=None, max_length=64)
    clear_session_cache: bool = False

    @field_validator("messages")
    @classmethod
    def reject_client_system_role(cls, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Clients may only send user/assistant turns; system prompt is server-owned."""
        for message in messages:
            if not isinstance(message, dict):
                raise ValueError("ASSISTANT_MESSAGE_INVALID")
            role = message.get("role")
            if role == "system":
                raise ValueError("ASSISTANT_SYSTEM_ROLE_FORBIDDEN")
            if role not in {"user", "assistant"}:
                raise ValueError("ASSISTANT_ROLE_INVALID")
        return messages


class AssistantSessionCacheClearRequest(BaseModel):
    assistant_session_id: str = Field(min_length=1, max_length=64)


class AssistantResponse(BaseModel):
    answer: str
    sources: list[str] = Field(default_factory=list)
    citations: list[AssistantCitation] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)
    confidence: str = "low"
    escalate: bool = False
    degraded: bool = False
    degrade_reason: str | None = None
    model: str | None = None
    route: str | None = None
    query_type: str | None = None
    risk_notice: str | None = None
    orchestration_mode: Literal["single", "multi_agent"] | None = None
    orchestration_id: str | None = None
    all_agents_local: bool = True
    network_used: bool = False
    network_query: str | None = None
    agent_trace: list[dict[str, Any]] = Field(default_factory=list)
    external_sources: list[dict[str, Any]] = Field(default_factory=list)
    route_explanation: str | None = None
    classifier: dict[str, Any] | None = None
    evidence_preview: dict[str, Any] | None = None
    retrieval_cache_hit: bool = False


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
    release_evidence_hash: str | None = Field(default=None, max_length=64)


class ModelVersionBindingActivate(BaseModel):
    approved_by: str = Field(min_length=1, max_length=120)


class ModelVersionBindingRollback(BaseModel):
    reason: str = Field(default="", max_length=240)
    evidence_hash: str | None = Field(default=None, max_length=64)


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
    release_evidence_hash: str | None
    rollback_evidence_hash: str | None
    approved_by: str | None
    approved_at: datetime | None
    revoked_by: str | None
    revoked_at: datetime | None
    created_by: str
    created_at: datetime
    updated_at: datetime


class ErasureTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    household_id: str
    member_id: str | None
    requested_by: str
    requested_at: datetime
    completed_at: datetime | None
    status: str
    layers: dict[str, Any]
    scope: dict[str, Any]
    error_layers: list[str]
