import json
import logging
import secrets
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from queue import Queue
from threading import Event, Thread
from typing import Any, NoReturn

from ai.vision.candidate_fusion import (
    FusionRequest,
    fuse_evidence,
)
from ai.vision.candidate_fusion import (
    FusionStatus as VisionFusionStatus,
)
from ai.vision.evidence_pipeline import (
    EvidencePipelineRequest,
    EvidencePipelineResult,
    LocalMasterData,
    process_evidence,
    verify_adapter_receipt,
)
from ai.vision.master_data import load_master_data_snapshot
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit_pagination import decode_audit_cursor, encode_audit_cursor
from app.auth import (
    authenticate,
    authenticate_with_pin,
    check_face_rate_limit,
    clear_face_failures,
    consume_face_challenge,
    consume_family_face_challenge,
    consume_pin_challenge,
    create_face_challenge,
    create_face_session,
    create_family_face_challenge,
    enforce_face_challenge_rate_limit,
    enforce_registration_rate_limit,
    family_face_rate_actor,
    generate_pin_challenge,
    introspect_session,
    logout,
    record_face_failure,
    register_account,
    revoke_household_sessions,
    set_account_pin,
    verify_pin_challenge,
)
from app.care_plan import validate_plan_confirmation_window
from app.config import get_settings
from app.db import SessionLocal, get_session
from app.erasure import (
    ErasureTask,
    find_erasure_task,
    request_household_erasure,
)
from app.event_pagination import decode_event_cursor, encode_event_cursor
from app.event_service import (
    CheckpointInvalidError,
    EventAlreadySupersededError,
    IdempotencyConflictError,
    append_compensation_transaction,
    append_health_event_transaction,
    create_projection_checkpoint,
    dispatch_outbox_batch,
    replay_member_projection,
)
from app.face_credentials import (
    FACE_CONSENT_VERSION,
    FACE_FEATURE_VERSION_MULTI,
    LEGACY_FACE_ALGORITHM_VERSION,
    V2_FACE_ALGORITHM_VERSION,
    aggregate_match_scores,
    check_face_liveness,
    decrypt_template,
    encrypt_template,
    extract_face_template,
    extract_legacy_face_template,
    extract_v2_face_template,
    face_models_ready,
    family_match_margin_for,
    is_legacy_face_algorithm,
    match_threshold_for,
    normalize_face_failure_reason,
    pack_face_templates,
    ranking_margin,
    score_probe_against_gallery,
    unpack_face_templates,
)
from app.file_upload import (
    compute_hash,
    delete_file_tree,
    file_owner,
    validate_and_store,
    validate_extension,
    validate_filename,
    validate_magic,
    validate_size,
)
from app.knowledge import KnowledgeDocument, RetrievalQuery
from app.knowledge_audit_pagination import (
    decode_knowledge_audit_cursor,
    encode_knowledge_audit_cursor,
)
from app.local_agents import OrchestrationCancelled, get_agent_catalog, run_local_multi_agent
from app.models import (
    AccessAudit,
    CareAuthorization,
    FaceCredential,
    HealthEvent,
    Household,
    Member,
    MemberStateProjection,
    OutboxMessage,
    RiskAcknowledgement,
    VisionTask,
)
from app.request_context import current_request_id
from app.review import (
    FusionStatus as ReviewFusionStatus,
)
from app.review import (
    ReviewTask,
    confirm_review,
    correct_review,
    create_review_task,
    get_review_task,
    get_review_task_by_vision_task,
    skip_review,
)
from app.review import (
    list_review_tasks as list_review_tasks_query,
)
from app.risk_acknowledgement import (
    acknowledgement_read,
    request_fingerprint,
    risk_fingerprint,
)
from app.schemas import (
    AccessAuditPageRead,
    AccessAuditRead,
    AccessAuditSummaryRead,
    AssistantRequest,
    AssistantResponse,
    AuthCredentials,
    AuthorizationCreate,
    AuthorizationRead,
    AuthorizationRevoke,
    AuthorizationUpdate,
    AuthSessionRead,
    AuthSessionRequest,
    CapabilityResponse,
    CorrectionDiffCreate,
    CorrectionDiffRead,
    DashboardSummaryRead,
    ErasureTaskRead,
    ExportManifestCreate,
    ExportManifestInvalidate,
    ExportManifestRead,
    FaceAuthFailureSummaryRead,
    FaceChallengeRead,
    FaceChallengeRequest,
    FaceCredentialRead,
    FamilyFaceChallengeRequest,
    HardSampleCreate,
    HardSampleRead,
    HardSampleUpdate,
    HealthEventCompensationCreate,
    HealthEventCreate,
    HealthEventPageRead,
    HealthEventRead,
    HealthResponse,
    HouseholdCreate,
    HouseholdRead,
    HouseholdUpdate,
    KnowledgeDocumentCreate,
    KnowledgeDocumentRead,
    KnowledgeQueryAuditPageRead,
    KnowledgeQueryAuditRead,
    KnowledgeRetrieveRequest,
    KnowledgeRetrieveResponse,
    MemberAccountBindingUpdate,
    MemberCreate,
    MemberRead,
    MemberStateRead,
    ModelVersionBindingActivate,
    ModelVersionBindingCreate,
    ModelVersionBindingRead,
    ModelVersionBindingRollback,
    OutboxDispatchRead,
    OutboxDispatchRequest,
    OutboxRead,
    PinLoginCredentials,
    PinSetRequest,
    PlanAutomationRead,
    PlanWorkbenchRead,
    ProjectionCheckpointRead,
    ProjectionReplayRead,
    ProjectionReplayRequest,
    RelationshipGraphRead,
    ReviewTaskConfirm,
    ReviewTaskCorrect,
    ReviewTaskRead,
    ReviewTaskSkip,
    RiskAcknowledgementCreate,
    RiskAcknowledgementRead,
    RiskAlertRead,
    RiskDetailResponse,
    RiskListResponse,
    SecurityDashboardRead,
    SessionIntrospectRead,
    StepUpChallengeRead,
    StepUpChallengeRequest,
    StepUpGrantRead,
    StepUpVerifyRequest,
    TrainingConsentCreate,
    TrainingConsentRead,
    TrainingConsentRevoke,
    VisionFusionRead,
    VisionQualityRead,
    VisionTaskClaimRequest,
    VisionTaskCleanupRead,
    VisionTaskCleanupRequest,
    VisionTaskCreate,
    VisionTaskLeaseRequest,
    VisionTaskRead,
)
from app.security import (
    get_access_purpose,
    get_actor_id,
    has_authorized_action,
    has_member_read_access,
    has_vision_capture_access,
    is_self_member,
    require_household_owner,
    require_session_token,
)
from app.tool_call import (
    get_approved_tools,
    run_assistant,
)
from app.vision_tasks import (
    VISION_MEDIA_TYPES,
    VisionTaskStatus,
    _file_digest,
    assert_vision_task_lease,
    claim_vision_tasks,
    cleanup_expired_video_files,
    create_vision_task,
    get_vision_task,
    list_vision_tasks,
    renew_vision_task_lease,
    retry_vision_task,
    transition_status,
)
from app.weather_adapter import WeatherActionCardsResponse, fetch_weather

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")
settings = get_settings()


def _face_extractor_for_algorithm(algorithm_version: str):
    """Resolve extractors via this module so contract tests can monkeypatch them."""
    if algorithm_version == LEGACY_FACE_ALGORITHM_VERSION:
        return extract_legacy_face_template
    if algorithm_version == V2_FACE_ALGORITHM_VERSION:
        return extract_v2_face_template
    return extract_face_template


def _raise_resource_not_found() -> NoReturn:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RESOURCE_NOT_FOUND")


def _is_erased(household: Household | None, member: Member | None = None) -> bool:
    if household is None or household.deleted_at is not None:
        return True
    if member is not None and (
        member.deleted_at is not None or member.household_id != household.id
    ):
        return True
    return False


def _actor_belongs_to_household(session: Session, household_id: str, actor_id: str) -> bool:
    household = session.get(Household, household_id)
    if _is_erased(household):
        return False
    if household.created_by == actor_id:
        return True
    return (
        session.scalar(
            select(Member.id).where(
                Member.household_id == household_id,
                Member.actor_id == actor_id,
                Member.deleted_at.is_(None),
            )
        )
        is not None
    )


def _record_authentication_audit(
    session: Session,
    *,
    household_id: str,
    actor_id: str,
    method: str,
    outcome: str,
    reason: str,
) -> None:
    """Persist only authentication metadata; never secrets, templates, or scores."""
    household = session.get(Household, household_id)
    if _is_erased(household):
        return
    session.add(
        AccessAudit(
            household_id=household_id,
            authorization_id=None,
            actor_id=actor_id,
            operation="AUTHENTICATION",
            action=f"{method}_LOGIN",
            data_field="pin" if method == "PIN" else "biometric_template",
            purpose="authentication",
            outcome=outcome,
            reason=reason[:64],
        )
    )
    session.commit()


def _future_time(value: datetime) -> datetime:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if normalized <= datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="AUTHORIZATION_EXPIRED",
        )
    return normalized


def _add_authorization_audit(
    session: Session,
    authorization: CareAuthorization,
    *,
    actor_id: str,
    operation: str,
    before_version: int | None,
    after_version: int,
) -> None:
    session.add(
        AccessAudit(
            household_id=authorization.household_id,
            authorization_id=authorization.id,
            actor_id=actor_id,
            operation=operation,
            action="MANAGE_AUTHORIZATION",
            data_field="care_authorization",
            purpose=authorization.purpose,
            outcome="SUCCESS",
            before_version=before_version,
            after_version=after_version,
        )
    )


def _add_household_setting_audit(
    session: Session,
    *,
    household_id: str,
    actor_id: str,
    action: str,
    data_field: str,
) -> None:
    """Record only the metadata needed to trace an allowed setting change."""
    session.add(
        AccessAudit(
            household_id=household_id,
            authorization_id=None,
            actor_id=actor_id,
            operation="UPDATE",
            action=action,
            data_field=data_field,
            purpose="household-settings",
            outcome="ALLOWED",
            reason=None,
            request_id=current_request_id(),
        )
    )


@router.get("/health/db", response_model=HealthResponse)
def database_health(session: Session = Depends(get_session)) -> HealthResponse:
    session.execute(text("SELECT 1"))
    return HealthResponse(status="ok", service=f"{settings.app_name} database", version="0.1.0")


@router.get("/meta/capabilities", response_model=CapabilityResponse)
def capabilities() -> CapabilityResponse:
    available = [
        "manual-health-event",
        "household-member",
        "field-authorization",
        "audit-outbox",
        "event-compensation-replay",
        "outbox-recovery-worker",
        "review-task",
        "vision-task",
        "knowledge-store",
        "local-assistant",
        "llm",
        "risk-acknowledgement",
    ]
    unavailable = ["vision-inference", "llm-cloud", "external-web"]
    # HCT-414-D2 (DEMO_ONLY until the HCT-201 fixed quality set is signed off):
    # the video task capability is declarative so mobile clients can hide the
    # video entry when the server does not provide it.
    if settings.vision_video_tasks_enabled:
        available.append("vision-task-video")
    else:
        unavailable.append("vision-task-video")
    if face_models_ready():
        available.append("face-recognition-local")
    else:
        unavailable.append("face-recognition-local")
    cfg = get_settings()
    return CapabilityResponse(
        phase="P0-foundation",
        available=available,
        unavailable=unavailable,
        knowledge_admin_configured=bool(cfg.knowledge_admin_actor_set),
        model_release_admin_configured=bool(cfg.model_release_admin_actor_set),
        model_release_dual_control=cfg.model_release_dual_control,
        owner_requires_access_purpose=cfg.owner_requires_access_purpose,
    )


@router.get("/meta/security-dashboard", response_model=SecurityDashboardRead)
def security_dashboard(
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> SecurityDashboardRead:
    """Aggregate access/auth audit counters for teaching demos (owner-scoped)."""
    owned = list(
        session.scalars(select(Household).where(Household.created_by == actor_id)).all()
    )
    household_ids = [h.id for h in owned if h.deleted_at is None]
    if not household_ids:
        return SecurityDashboardRead(household_count=0)

    audits = list(
        session.scalars(
            select(AccessAudit)
            .where(AccessAudit.household_id.in_(household_ids))
            .order_by(AccessAudit.created_at.desc())
            .limit(500)
        ).all()
    )
    allowed = sum(1 for a in audits if a.outcome == "ALLOWED")
    denied = sum(1 for a in audits if a.outcome == "DENIED")
    file_cleanups = sum(1 for a in audits if a.action == "DELETE_FILE")
    auth_failures = sum(
        1 for a in audits if a.operation == "AUTHENTICATION" and a.outcome == "FAILED"
    )
    recent_denied = [
        {
            "action": a.action,
            "reason": a.reason,
            "actor_id": a.actor_id,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in audits
        if a.outcome == "DENIED"
    ][:20]
    return SecurityDashboardRead(
        household_count=len(household_ids),
        access_allowed=allowed,
        access_denied=denied,
        file_owner_cleanups=file_cleanups,
        auth_failures=auth_failures,
        model_release_events=0,
        recent_denied=recent_denied,
    )


def _valid_authorizations(
    session: Session,
    actor_id: str,
    *,
    household_id: str | None = None,
    purpose: str | None = None,
) -> list[CareAuthorization]:
    """获取 actor 的未撤权、未过期、且有明确字段和动作的授权。

    统一在所有列表接口中复用，确保与 has_authorized_action 一致地校验
    data_fields 和 actions，不会仅凭"存在任意授权记录"就放行。
    """
    if purpose is None:
        return []
    now = datetime.now(UTC)
    stmt = select(CareAuthorization).where(
        CareAuthorization.grantee_actor_id == actor_id,
        CareAuthorization.revoked_at.is_(None),
        CareAuthorization.valid_from <= now,
        CareAuthorization.valid_until > now,
        CareAuthorization.purpose == purpose,
    )
    if household_id is not None:
        stmt = stmt.where(CareAuthorization.household_id == household_id)
    auths: list[CareAuthorization] = list(session.scalars(stmt).all())
    return [
        a
        for a in auths
        if "health_events" in (a.data_fields or []) and "READ_EVENTS" in (a.actions or [])
    ]


@router.get("/households", response_model=list[HouseholdRead])
def list_households(
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> list[Household]:
    owned = session.scalars(
        select(Household).where(
            Household.created_by == actor_id,
            Household.deleted_at.is_(None),
        )
    ).all()
    authorized_ids = {
        a.household_id for a in _valid_authorizations(session, actor_id, purpose=access_purpose)
    }
    authorized = (
        list(
            session.scalars(
                select(Household).where(
                    Household.id.in_(authorized_ids),
                    Household.deleted_at.is_(None),
                )
            ).all()
        )
        if authorized_ids
        else []
    )
    # A member account is a first-class local family identity.  It does not
    # need a separate CareAuthorization just to discover its own household.
    member_household_ids = set(
        session.scalars(
            select(Member.household_id).where(
                Member.actor_id == actor_id,
                Member.deleted_at.is_(None),
            )
        ).all()
    )
    member_households = (
        list(
            session.scalars(
                select(Household).where(
                    Household.id.in_(member_household_ids),
                    Household.deleted_at.is_(None),
                )
            ).all()
        )
        if member_household_ids
        else []
    )
    seen: set[str] = set()
    result: list[Household] = []
    for h in list(owned) + authorized + member_households:
        if h.id not in seen:
            seen.add(h.id)
            result.append(h)
    return result


@router.get("/households/{household_id}/members", response_model=list[MemberRead])
def list_members(
    household_id: str,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> list[Member]:
    household = session.get(Household, household_id)
    if _is_erased(household):
        _raise_resource_not_found()
    if household.created_by == actor_id:
        query = select(Member).where(
            Member.household_id == household_id,
            Member.deleted_at.is_(None),
        )
        return list(session.scalars(query).all())

    members = list(
        session.scalars(
            select(Member).where(
                Member.household_id == household_id,
                Member.deleted_at.is_(None),
            )
        ).all()
    )
    own_member = [m for m in members if m.actor_id == actor_id]
    authorized_members = [
        m
        for m in members
        if m.actor_id != actor_id
        if has_authorized_action(
            session,
            household,
            m.id,
            actor_id,
            "READ_EVENTS",
            "health_events",
            access_purpose,
        )
    ]
    visible_members = list(dict.fromkeys([*own_member, *authorized_members]))
    if not visible_members:
        _raise_resource_not_found()
    return visible_members


@router.post("/households", response_model=HouseholdRead, status_code=status.HTTP_201_CREATED)
def create_household(
    payload: HouseholdCreate,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> Household:
    household = Household(
        name=payload.name,
        created_by=actor_id,
        time_zone=payload.time_zone or settings.default_household_time_zone,
    )
    session.add(household)
    session.commit()
    session.refresh(household)
    return household


@router.patch("/households/{household_id}", response_model=HouseholdRead)
def update_household(
    household_id: str,
    payload: HouseholdUpdate,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> Household:
    household = require_household_owner(session, household_id, actor_id)
    if household.time_zone != payload.time_zone:
        household.time_zone = payload.time_zone
        _add_household_setting_audit(
            session,
            household_id=household.id,
            actor_id=actor_id,
            action="UPDATE_TIME_ZONE",
            data_field="household.time_zone",
        )
    session.commit()
    session.refresh(household)
    return household


@router.post(
    "/households/{household_id}/members",
    response_model=MemberRead,
    status_code=status.HTTP_201_CREATED,
)
def create_member(
    household_id: str,
    payload: MemberCreate,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> Member:
    household = require_household_owner(session, household_id, actor_id)
    target_actor_id = payload.actor_id.strip() if payload.actor_id else None
    if target_actor_id:
        duplicate = session.scalar(
            select(Member.id).where(
                Member.household_id == household.id,
                Member.actor_id == target_actor_id,
                Member.deleted_at.is_(None),
            )
        )
        if duplicate is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="ACCOUNT_ID_EXISTS")
        if target_actor_id == household.created_by and payload.role != "SELF":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="ACCOUNT_ID_EXISTS")
    member = Member(
        household_id=household.id,
        display_name=payload.display_name,
        role=payload.role,
        actor_id=target_actor_id,
    )
    session.add(member)
    session.commit()
    session.refresh(member)
    return member


@router.patch(
    "/households/{household_id}/members/{member_id}/account",
    response_model=MemberRead,
)
def bind_member_account(
    household_id: str,
    member_id: str,
    payload: MemberAccountBindingUpdate,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> Member:
    """Give an existing family member the actor id used for local login."""
    household = require_household_owner(session, household_id, actor_id)
    member = _require_household_member(session, household.id, member_id)
    target_actor_id = payload.actor_id.strip()
    duplicate = session.scalar(
        select(Member.id).where(
            Member.household_id == household.id,
            Member.id != member.id,
            Member.actor_id == target_actor_id,
            Member.deleted_at.is_(None),
        )
    )
    if duplicate is not None or (target_actor_id == household.created_by and member.role != "SELF"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="ACCOUNT_ID_EXISTS")

    previous_actor_id = member.actor_id
    if previous_actor_id != target_actor_id:
        now = datetime.now(UTC)
        active_credentials = (
            list(
                session.scalars(
                    select(FaceCredential).where(
                        FaceCredential.household_id == household.id,
                        FaceCredential.actor_id == previous_actor_id,
                        FaceCredential.status == "ACTIVE",
                    )
                ).all()
            )
            if previous_actor_id
            else []
        )
        for credential in active_credentials:
            credential.status = "REVOKED"
            credential.revoked_at = now
            credential.encrypted_template = b""
        if previous_actor_id:
            revoke_household_sessions(household.id, {previous_actor_id}, session)
        member.actor_id = target_actor_id
        session.add(
            AccessAudit(
                household_id=household.id,
                authorization_id=None,
                actor_id=actor_id,
                operation="MEMBER_ACCOUNT",
                action="BIND" if previous_actor_id is None else "REPLACE",
                data_field="member_actor_id",
                purpose="family-account-binding",
                outcome="SUCCESS",
                reason=None,
                before_version=None,
                after_version=None,
            )
        )
        session.commit()
        session.refresh(member)
    return member


@router.delete(
    "/households/{household_id}",
    response_model=ErasureTaskRead,
)
def erase_household(
    household_id: str,
    member_id: str | None = None,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> ErasureTask:
    household = require_household_owner(
        session,
        household_id,
        actor_id,
        allow_deleted=True,
    )
    try:
        task = request_household_erasure(
            session,
            household,
            actor_id=actor_id,
            member_id=member_id,
        )
    except ValueError as exc:
        if str(exc) == "RESOURCE_NOT_FOUND":
            _raise_resource_not_found()
        raise
    session.commit()
    session.refresh(task)
    return task


@router.get(
    "/erasure-tasks/{task_id}",
    response_model=ErasureTaskRead,
)
def read_erasure_task(
    task_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> ErasureTask:
    task = find_erasure_task(session, task_id)
    if task is None or task.requested_by != actor_id:
        _raise_resource_not_found()
    return task


@router.post(
    "/households/{household_id}/authorizations",
    response_model=AuthorizationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_authorization(
    household_id: str,
    payload: AuthorizationCreate,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> CareAuthorization:
    household = require_household_owner(session, household_id, actor_id)
    member = _require_household_member(session, household_id, payload.member_id)
    valid_until = _future_time(payload.valid_until)
    authorization = CareAuthorization(
        household_id=household.id,
        member_id=member.id,
        grantor_actor_id=actor_id,
        grantee_actor_id=payload.grantee_actor_id,
        data_fields=payload.data_fields,
        actions=payload.actions,
        purpose=payload.purpose,
        valid_from=datetime.now(UTC),
        valid_until=valid_until,
    )
    session.add(authorization)
    session.flush()
    _add_authorization_audit(
        session,
        authorization,
        actor_id=actor_id,
        operation="CREATE",
        before_version=None,
        after_version=1,
    )
    session.commit()
    session.refresh(authorization)
    return authorization


@router.get(
    "/households/{household_id}/authorizations",
    response_model=list[AuthorizationRead],
)
def list_authorizations(
    household_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> list[CareAuthorization]:
    household = require_household_owner(session, household_id, actor_id)
    return list(
        session.scalars(
            select(CareAuthorization)
            .where(CareAuthorization.household_id == household.id)
            .order_by(CareAuthorization.created_at, CareAuthorization.id)
        ).all()
    )


@router.patch(
    "/households/{household_id}/authorizations/{authorization_id}",
    response_model=AuthorizationRead,
)
def update_authorization(
    household_id: str,
    authorization_id: str,
    payload: AuthorizationUpdate,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> CareAuthorization:
    household = require_household_owner(session, household_id, actor_id)
    authorization = session.scalar(
        select(CareAuthorization).where(
            CareAuthorization.id == authorization_id,
            CareAuthorization.household_id == household.id,
        )
    )
    if authorization is None:
        _raise_resource_not_found()
    if authorization.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="AUTHORIZATION_REVOKED",
        )

    values: dict[str, object] = {
        "version": payload.expected_version + 1,
        "updated_at": datetime.now(UTC),
    }
    if payload.data_fields is not None:
        values["data_fields"] = payload.data_fields
    if payload.actions is not None:
        values["actions"] = payload.actions
    if payload.purpose is not None:
        values["purpose"] = payload.purpose
    if payload.valid_until is not None:
        values["valid_until"] = _future_time(payload.valid_until)

    result = session.execute(
        update(CareAuthorization)
        .where(
            CareAuthorization.id == authorization.id,
            CareAuthorization.household_id == household.id,
            CareAuthorization.version == payload.expected_version,
            CareAuthorization.revoked_at.is_(None),
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="AUTHORIZATION_VERSION_CONFLICT",
        )
    session.expire(authorization)
    session.refresh(authorization)
    _add_authorization_audit(
        session,
        authorization,
        actor_id=actor_id,
        operation="UPDATE",
        before_version=payload.expected_version,
        after_version=authorization.version,
    )
    session.commit()
    session.refresh(authorization)
    return authorization


@router.post(
    "/households/{household_id}/authorizations/{authorization_id}/revoke",
    response_model=AuthorizationRead,
)
def revoke_authorization(
    household_id: str,
    authorization_id: str,
    payload: AuthorizationRevoke,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> CareAuthorization:
    household = require_household_owner(session, household_id, actor_id)
    authorization = session.scalar(
        select(CareAuthorization).where(
            CareAuthorization.id == authorization_id,
            CareAuthorization.household_id == household.id,
        )
    )
    if authorization is None:
        _raise_resource_not_found()
    if authorization.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="AUTHORIZATION_REVOKED",
        )
    revoked_at = datetime.now(UTC)
    result = session.execute(
        update(CareAuthorization)
        .where(
            CareAuthorization.id == authorization.id,
            CareAuthorization.household_id == household.id,
            CareAuthorization.version == payload.expected_version,
            CareAuthorization.revoked_at.is_(None),
        )
        .values(
            revoked_at=revoked_at,
            updated_at=revoked_at,
            version=payload.expected_version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="AUTHORIZATION_VERSION_CONFLICT",
        )
    session.expire(authorization)
    session.refresh(authorization)
    _add_authorization_audit(
        session,
        authorization,
        actor_id=actor_id,
        operation="REVOKE",
        before_version=payload.expected_version,
        after_version=authorization.version,
    )
    session.commit()
    session.refresh(authorization)
    return authorization


@router.get(
    "/households/{household_id}/authorization-audits",
    response_model=list[AccessAuditRead],
)
def list_authorization_audits(
    household_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> list[AccessAudit]:
    household = require_household_owner(session, household_id, actor_id)
    return list(
        session.scalars(
            select(AccessAudit)
            .where(AccessAudit.household_id == household.id)
            .order_by(AccessAudit.created_at, AccessAudit.id)
        ).all()
    )


@router.get(
    "/households/{household_id}/authorization-audits/page",
    response_model=AccessAuditPageRead,
)
def page_authorization_audits(
    household_id: str,
    request_id: str | None = Query(default=None, min_length=1, max_length=120),
    action: str | None = Query(default=None, min_length=1, max_length=80),
    outcome: str | None = Query(default=None, min_length=1, max_length=32),
    cursor: str | None = Query(default=None, min_length=1),
    limit: int = Query(default=50, ge=1, le=100),
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> AccessAuditPageRead:
    household = require_household_owner(session, household_id, actor_id)
    decoded_cursor = None
    if cursor is not None:
        try:
            decoded_cursor = decode_audit_cursor(cursor, secret=settings.cursor_signing_key)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        if (
            decoded_cursor.household_id != household.id
            or decoded_cursor.request_id != request_id
            or decoded_cursor.action != action
            or decoded_cursor.outcome != outcome
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="AUDIT_CURSOR_INVALID",
            )

    query = select(AccessAudit).where(AccessAudit.household_id == household.id)
    if request_id is not None:
        query = query.where(AccessAudit.request_id == request_id)
    if action is not None:
        query = query.where(AccessAudit.action == action)
    if outcome is not None:
        query = query.where(AccessAudit.outcome == outcome)
    if decoded_cursor is not None:
        query = query.where(
            (AccessAudit.created_at > decoded_cursor.created_at)
            | (
                (AccessAudit.created_at == decoded_cursor.created_at)
                & (AccessAudit.id > decoded_cursor.audit_id)
            )
        )
    rows = list(
        session.scalars(
            query.order_by(AccessAudit.created_at, AccessAudit.id).limit(limit + 1)
        ).all()
    )
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_audit_cursor(
            household_id=household.id,
            request_id=request_id,
            action=action,
            outcome=outcome,
            created_at=last.created_at,
            audit_id=last.id,
            secret=settings.cursor_signing_key,
        )
    return AccessAuditPageRead(items=items, next_cursor=next_cursor, has_more=has_more)


@router.get(
    "/households/{household_id}/authorization-audits/summary",
    response_model=AccessAuditSummaryRead,
)
def summarize_authorization_audits(
    household_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> AccessAuditSummaryRead:
    household = require_household_owner(session, household_id, actor_id)
    grouped = session.execute(
        select(AccessAudit.action, AccessAudit.outcome, func.count(AccessAudit.id))
        .where(AccessAudit.household_id == household.id)
        .group_by(AccessAudit.action, AccessAudit.outcome)
    ).all()
    by_action: dict[str, int] = {}
    by_outcome: dict[str, int] = {}
    total = 0
    for action, outcome, count in grouped:
        normalized_count = int(count)
        by_action[action] = by_action.get(action, 0) + normalized_count
        by_outcome[outcome] = by_outcome.get(outcome, 0) + normalized_count
        total += normalized_count
    return AccessAuditSummaryRead(
        total=total,
        by_action=by_action,
        by_outcome=by_outcome,
        generated_at=datetime.now(UTC),
    )


@router.post(
    "/households/{household_id}/events",
    response_model=HealthEventRead,
    status_code=status.HTTP_201_CREATED,
)
def append_health_event(
    household_id: str,
    payload: HealthEventCreate,
    request: Request,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
) -> HealthEvent:
    household = session.get(Household, household_id)
    if _is_erased(household):
        _raise_resource_not_found()
    member = session.get(Member, payload.member_id)
    if _is_erased(household, member):
        _raise_resource_not_found()
    if not has_authorized_action(
        session,
        household,
        member.id,
        actor_id,
        "WRITE_EVENTS",
        "health_events",
        access_purpose,
    ):
        _raise_resource_not_found()

    if (
        idempotency_key is not None
        and payload.idempotency_key is not None
        and idempotency_key.strip() != payload.idempotency_key.strip()
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="IDEMPOTENCY_KEY_CONFLICT",
        )
    effective_key = idempotency_key or payload.idempotency_key
    correlation_id = getattr(request.state, "request_id", None) or request.headers.get(
        settings.request_id_header, ""
    )

    try:
        if payload.compensates_event_id is None:
            return append_health_event_transaction(
                session,
                household=household,
                member=member,
                actor_id=actor_id,
                idempotency_key=effective_key,
                correlation_id=correlation_id,
                payload=payload,
            )

        target = session.get(HealthEvent, payload.compensates_event_id)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="COMPENSATES_EVENT_NOT_FOUND",
            )
        if target.household_id != household.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="COMPENSATES_EVENT_WRONG_HOUSEHOLD",
            )
        return append_compensation_transaction(
            session,
            household=household,
            member=member,
            target=target,
            actor_id=actor_id,
            idempotency_key=effective_key,
            correlation_id=correlation_id,
            payload=HealthEventCompensationCreate(
                event_type=payload.event_type,
                payload=payload.payload,
                evidence=payload.evidence,
                reason="legacy compensation request",
                occurred_at=payload.occurred_at,
            ),
        )
    except IdempotencyConflictError as exc:
        detail = (
            "IDEMPOTENCY_KEY_CONFLICT" if idempotency_key is not None else "IDEMPOTENCY_CONFLICT"
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from exc
    except EventAlreadySupersededError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        code = str(exc)
        if code == "IDEMPOTENCY_KEY_INVALID":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=code,
            ) from exc
        if code == "UNCONFIRMED_EVENT_CANNOT_BE_COMPENSATED":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=code) from exc
        raise


@router.post(
    "/households/{household_id}/events/{event_id}/compensations",
    response_model=HealthEventRead,
    status_code=status.HTTP_201_CREATED,
)
def compensate_health_event(
    household_id: str,
    event_id: str,
    payload: HealthEventCompensationCreate,
    request: Request,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
) -> HealthEvent:
    household = session.get(Household, household_id)
    target = session.get(HealthEvent, event_id)
    if household is None or target is None or target.household_id != household.id:
        _raise_resource_not_found()
    member = session.get(Member, target.member_id)
    if member is None or not has_authorized_action(
        session,
        household,
        member.id,
        actor_id,
        "WRITE_EVENTS",
        "health_events",
        access_purpose,
    ):
        _raise_resource_not_found()
    try:
        return append_compensation_transaction(
            session,
            household=household,
            member=member,
            target=target,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            correlation_id=getattr(request.state, "request_id", ""),
            payload=payload,
        )
    except (IdempotencyConflictError, EventAlreadySupersededError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        code = str(exc)
        if code == "IDEMPOTENCY_KEY_INVALID":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=code,
            ) from exc
        if code == "UNCONFIRMED_EVENT_CANNOT_BE_COMPENSATED":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=code) from exc
        raise


@router.get("/households/{household_id}/events", response_model=list[HealthEventRead])
def list_health_events(
    household_id: str,
    member_id: str | None = None,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> list[HealthEvent]:
    household = session.get(Household, household_id)
    if _is_erased(household):
        _raise_resource_not_found()
    allowed_member_ids = _authorized_event_member_ids(session, household, actor_id, access_purpose)
    if member_id is not None and member_id not in allowed_member_ids:
        _raise_resource_not_found()
    if not allowed_member_ids:
        if household.created_by == actor_id:
            return []
        _raise_resource_not_found()
    query = select(HealthEvent).where(
        HealthEvent.household_id == household.id,
        HealthEvent.member_id.in_(allowed_member_ids),
    )
    # A member account may have a broad event-page query without explicitly
    # naming itself.  Keep the same confirmed-only boundary as the member
    # timeline endpoint; owners and authorized caregivers retain their
    # existing scoped visibility.
    if household.created_by != actor_id:
        self_member_ids = {
            member.id
            for member in session.scalars(
                select(Member).where(
                    Member.household_id == household.id,
                    Member.actor_id == actor_id,
                    Member.deleted_at.is_(None),
                )
            ).all()
        }
        if self_member_ids:
            query = query.where(
                (HealthEvent.member_id.not_in(self_member_ids))
                | (HealthEvent.confirmation_status == "CONFIRMED")
            )
    if member_id is not None:
        query = query.where(HealthEvent.member_id == member_id)
    if member_id is not None and is_self_member(session, household, member_id, actor_id):
        query = query.where(HealthEvent.confirmation_status == "CONFIRMED")
    return list(session.scalars(query.order_by(HealthEvent.sequence_no)).all())


def _authorized_event_member_ids(
    session: Session,
    household: Household,
    actor_id: str,
    access_purpose: str | None,
) -> set[str]:
    members = session.scalars(
        select(Member).where(
            Member.household_id == household.id,
            Member.deleted_at.is_(None),
        )
    ).all()
    return {
        member.id
        for member in members
        if has_member_read_access(
            session, household, member.id, actor_id, access_purpose
        )
    }


@router.get(
    "/households/{household_id}/events/page",
    response_model=HealthEventPageRead,
)
def page_health_events(
    household_id: str,
    member_id: str | None = None,
    event_type: str | None = Query(default=None, min_length=1, max_length=80),
    confirmation_status: str | None = Query(default=None, min_length=1, max_length=32),
    occurred_from: datetime | None = None,
    occurred_until: datetime | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> HealthEventPageRead:
    """Return an authorization-scoped page without exposing event payload in the cursor."""
    if occurred_from is not None and occurred_from.tzinfo is None:
        occurred_from = occurred_from.replace(tzinfo=UTC)
    if occurred_until is not None and occurred_until.tzinfo is None:
        occurred_until = occurred_until.replace(tzinfo=UTC)
    if occurred_from is not None:
        occurred_from = occurred_from.astimezone(UTC)
    if occurred_until is not None:
        occurred_until = occurred_until.astimezone(UTC)
    if (
        occurred_from is not None
        and occurred_until is not None
        and occurred_from > occurred_until
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="EVENT_TIME_RANGE_INVALID",
        )
    household = session.get(Household, household_id)
    if _is_erased(household):
        _raise_resource_not_found()
    allowed_member_ids = _authorized_event_member_ids(session, household, actor_id, access_purpose)
    if member_id is not None and member_id not in allowed_member_ids:
        _raise_resource_not_found()
    if not allowed_member_ids:
        if household.created_by == actor_id:
            return HealthEventPageRead(items=[])
        _raise_resource_not_found()

    try:
        decoded_cursor = (
            decode_event_cursor(cursor, secret=settings.cursor_signing_key) if cursor else None
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    if decoded_cursor is not None and (
        decoded_cursor.household_id != household.id
        or decoded_cursor.member_id != member_id
        or decoded_cursor.event_type != event_type
        or decoded_cursor.confirmation_status != confirmation_status
        or decoded_cursor.occurred_from != occurred_from
        or decoded_cursor.occurred_until != occurred_until
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="EVENT_CURSOR_INVALID",
        )

    cursor_anchor: HealthEvent | None = None
    if decoded_cursor is not None:
        cursor_anchor = session.get(HealthEvent, decoded_cursor.event_id)
        if (
            cursor_anchor is None
            or cursor_anchor.household_id != household.id
            or (member_id is not None and cursor_anchor.member_id != member_id)
            or (member_id is None and cursor_anchor.member_id not in allowed_member_ids)
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="EVENT_CURSOR_INVALID",
            )

    query = select(HealthEvent).where(
        HealthEvent.household_id == household.id,
        HealthEvent.member_id.in_(allowed_member_ids),
    )
    if household.created_by != actor_id:
        self_member_ids = {
            member.id
            for member in session.scalars(
                select(Member).where(
                    Member.household_id == household.id,
                    Member.actor_id == actor_id,
                    Member.deleted_at.is_(None),
                )
            ).all()
        }
        if self_member_ids:
            query = query.where(
                (HealthEvent.member_id.not_in(self_member_ids))
                | (HealthEvent.confirmation_status == "CONFIRMED")
            )
    if member_id is not None:
        query = query.where(HealthEvent.member_id == member_id)
    if event_type is not None:
        query = query.where(HealthEvent.event_type == event_type)
    if confirmation_status is not None:
        query = query.where(HealthEvent.confirmation_status == confirmation_status)
    if occurred_from is not None:
        query = query.where(HealthEvent.occurred_at >= occurred_from)
    if occurred_until is not None:
        query = query.where(HealthEvent.occurred_at <= occurred_until)
    if decoded_cursor is not None:
        query = query.where(
            (HealthEvent.sequence_no > decoded_cursor.sequence_no)
            | (
                (HealthEvent.sequence_no == decoded_cursor.sequence_no)
                & (HealthEvent.id > decoded_cursor.event_id)
            )
        )
    rows = list(
        session.scalars(
            query.order_by(HealthEvent.sequence_no, HealthEvent.id).limit(limit + 1)
        ).all()
    )
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_event_cursor(
            household_id=household.id,
            member_id=member_id,
            created_at=last.created_at,
            sequence_no=last.sequence_no,
            event_id=last.id,
            secret=settings.cursor_signing_key,
            event_type=event_type,
            confirmation_status=confirmation_status,
            occurred_from=occurred_from,
            occurred_until=occurred_until,
        )
    return HealthEventPageRead(items=items, next_cursor=next_cursor, has_more=has_more)


@router.get(
    "/households/{household_id}/members/{member_id}/state",
    response_model=MemberStateRead,
)
def read_member_state(
    household_id: str,
    member_id: str,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> MemberStateProjection:
    household = session.get(Household, household_id)
    member = session.get(Member, member_id)
    if _is_erased(household, member):
        _raise_resource_not_found()
    if not has_member_read_access(
        session,
        household,
        member_id,
        actor_id,
        access_purpose,
    ):
        _raise_resource_not_found()
    projection = session.get(MemberStateProjection, member_id)
    if projection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="STATE_NOT_FOUND")
    return projection


def _require_household_member(
    session: Session,
    household_id: str,
    member_id: str,
) -> Member:
    member = session.get(Member, member_id)
    if member is None or member.household_id != household_id or member.deleted_at is not None:
        _raise_resource_not_found()
    return member


@router.post(
    "/households/{household_id}/members/{member_id}/state/checkpoints",
    response_model=ProjectionCheckpointRead,
    status_code=status.HTTP_201_CREATED,
)
def checkpoint_member_state(
    household_id: str,
    member_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
):
    require_household_owner(session, household_id, actor_id)
    _require_household_member(session, household_id, member_id)
    projection = session.get(MemberStateProjection, member_id)
    if projection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="STATE_NOT_FOUND")
    try:
        return create_projection_checkpoint(session, projection=projection, actor_id=actor_id)
    except CheckpointInvalidError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/households/{household_id}/members/{member_id}/state/replay",
    response_model=ProjectionReplayRead,
)
def replay_member_state(
    household_id: str,
    member_id: str,
    payload: ProjectionReplayRequest,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
):
    require_household_owner(session, household_id, actor_id)
    _require_household_member(session, household_id, member_id)
    try:
        return replay_member_projection(
            session,
            household_id=household_id,
            member_id=member_id,
            checkpoint_id=payload.checkpoint_id,
        )
    except CheckpointInvalidError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get(
    "/households/{household_id}/outbox",
    response_model=list[OutboxRead],
)
def list_outbox_messages(
    household_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> list[OutboxMessage]:
    require_household_owner(session, household_id, actor_id)
    return list(
        session.scalars(
            select(OutboxMessage)
            .join(HealthEvent, HealthEvent.id == OutboxMessage.event_id)
            .where(HealthEvent.household_id == household_id)
            .order_by(HealthEvent.member_id, HealthEvent.sequence_no)
        ).all()
    )


@router.post(
    "/households/{household_id}/outbox/dispatch",
    response_model=OutboxDispatchRead,
)
def dispatch_household_outbox(
    household_id: str,
    payload: OutboxDispatchRequest,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
):
    require_household_owner(session, household_id, actor_id)
    return dispatch_outbox_batch(
        session,
        household_id=household_id,
        max_messages=payload.max_messages,
        stale_after=timedelta(seconds=payload.stale_after_seconds),
    )


@router.get("/weather/action-cards", response_model=WeatherActionCardsResponse)
async def weather_action_cards(
    city_code: str | None = Query(default=None, pattern=r"^\d{6}$"),
    district_code: str | None = Query(default=None, pattern=r"^\d{6}$"),
) -> dict:
    """Fetch weather action cards for the given coarse location.

    Only city_code and district_code are sent to the external weather API.
    No health data is included. This endpoint never blocks on weather failure.
    """
    return await fetch_weather(city_code=city_code, district_code=district_code)


# ── HCT-104: File upload & download ────────────────────────────────


@router.post("/files/upload", status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    actor_id: str = Depends(get_actor_id),
) -> dict:
    """Upload a file with validation, store with random key bound to the uploader."""
    result = await validate_and_store(file, owner=actor_id)
    logger.info(
        "FILE_UPLOADED actor=%s key=%s size=%d",
        actor_id,
        result["storage_key"],
        result["size_bytes"],
    )
    return result


def _actor_can_read_stored_file(
    session: Session,
    storage_key: str,
    actor_id: str,
    access_purpose: str | None,
) -> bool:
    """Allow non-uploaders to read a file only through an authorized vision task.

    Mirrors ``_require_vision_task_access``: the review flow legitimately lets
    a household owner (or an authorized caregiver) open evidence uploaded by a
    member, but only when a vision task links the file to their household.
    """
    tasks = session.scalars(
        select(VisionTask).where(VisionTask.file_id == storage_key)
    ).all()
    for task in tasks:
        if not task.member_id:
            if task.created_by == actor_id:
                return True
            continue
        member = session.get(Member, task.member_id)
        household = session.get(Household, task.household_id)
        if member is None or household is None or _is_erased(household, member):
            continue
        if has_member_read_access(session, household, member.id, actor_id, access_purpose):
            return True
    return False


def _actor_can_delete_stored_file(session: Session, storage_key: str, actor_id: str) -> bool:
    """Allow household owners to delete evidence linked to their household tasks."""
    tasks = session.scalars(
        select(VisionTask).where(VisionTask.file_id == storage_key)
    ).all()
    for task in tasks:
        household = session.get(Household, task.household_id)
        if household is None or _is_erased(household):
            continue
        if household.created_by == actor_id:
            return True
    return False


@router.get("/files/{storage_key}")
def download_file(
    storage_key: str,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> FileResponse:
    """Download a stored file: uploader always, others via an authorized vision task.

    Legacy objects without ownership metadata are fail-closed: they are readable
    only through the same vision-task authorization path (never by key alone).
    """
    settings = get_settings()
    root = Path(settings.file_root).resolve()
    target = (root / storage_key).resolve()

    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FILE_NOT_FOUND")

    owner = file_owner(storage_key)
    if owner is None or owner != actor_id:
        if not _actor_can_read_stored_file(session, storage_key, actor_id, access_purpose):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FILE_NOT_FOUND")

    logger.info("FILE_DOWNLOADED actor=%s key=%s", actor_id, storage_key)
    return FileResponse(
        str(target),
        filename=Path(storage_key).name,
        content_disposition_type="attachment",
    )


@router.delete("/files/{storage_key}")
def delete_file(
    storage_key: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> dict:
    """Delete a file and its thumbnails/cache/index entries.

    Uploaders may always delete their own objects. Household owners may delete
    evidence linked to a vision task in their household (audited). Legacy
    objects without ownership metadata follow the same rules (no open delete).
    Erasure tasks delete server-side and are not affected.
    """
    owner = file_owner(storage_key)
    as_uploader = owner == actor_id
    as_household_owner = _actor_can_delete_stored_file(session, storage_key, actor_id)
    if not as_uploader and not as_household_owner:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FILE_NOT_FOUND")

    audit_household_id: str | None = None
    if as_household_owner and not as_uploader:
        task = session.scalar(select(VisionTask).where(VisionTask.file_id == storage_key))
        if task is not None:
            audit_household_id = task.household_id

    deleted = delete_file_tree(storage_key)
    if audit_household_id is not None:
        session.add(
            AccessAudit(
                household_id=audit_household_id,
                authorization_id=None,
                actor_id=actor_id,
                operation="DELETE",
                action="DELETE_FILE",
                data_field="file",
                purpose=None,
                outcome="ALLOWED",
                reason="HOUSEHOLD_OWNER_EVIDENCE_CLEANUP",
                request_id=current_request_id(),
            )
        )
        session.commit()
    logger.info(
        "FILE_DELETED actor=%s key=%s deleted_paths=%d owner_cleanup=%s",
        actor_id,
        storage_key,
        len(deleted),
        audit_household_id is not None,
    )
    return {"storage_key": storage_key, "deleted_paths": len(deleted)}


# ── HCT-107: Local auth ────────────────────────────────────────────


@router.post("/auth/register", response_model=dict, status_code=status.HTTP_201_CREATED)
def auth_register(
    payload: AuthCredentials,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    client_host = request.client.host if request.client else None
    enforce_registration_rate_limit(
        session,
        actor_id=payload.actor_id,
        client_key=client_host,
    )
    register_account(payload.actor_id, payload.password, session)
    # Commit before the browser follows registration with a separate login
    # request; the dependency also commits successful requests at the boundary.
    session.commit()
    return {"status": "registered", "actor_id": payload.actor_id}


@router.post("/auth/login", response_model=AuthSessionRead)
def auth_login(
    payload: AuthCredentials,
    session: Session = Depends(get_session),
) -> dict:
    authentication = authenticate(payload.actor_id, payload.password, session)
    # Persist the session before the frontend immediately loads its household
    # scope in a new HTTP request; the dependency commits again at the boundary.
    session.commit()
    return {
        "actor_id": payload.actor_id,
        **authentication,
    }


@router.post("/auth/pin-login", response_model=AuthSessionRead)
def auth_pin_login(
    payload: PinLoginCredentials,
    session: Session = Depends(get_session),
) -> dict:
    # Keep household and identity selection server-side: a client cannot use a
    # valid PIN to enter a different household or impersonate another member.
    if not _actor_belongs_to_household(session, payload.household_id, payload.actor_id):
        _record_authentication_audit(
            session,
            household_id=payload.household_id,
            actor_id=payload.actor_id,
            method="PIN",
            outcome="FAILED",
            reason="AUTH_FAILED",
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="AUTH_FAILED")
    try:
        authentication = authenticate_with_pin(
            payload.actor_id,
            payload.household_id,
            payload.pin,
            session,
        )
    except HTTPException as exc:
        _record_authentication_audit(
            session,
            household_id=payload.household_id,
            actor_id=payload.actor_id,
            method="PIN",
            outcome="FAILED",
            reason=str(exc.detail).split(":", 1)[0],
        )
        raise
    _record_authentication_audit(
        session,
        household_id=payload.household_id,
        actor_id=payload.actor_id,
        method="PIN",
        outcome="SUCCESS",
        reason="AUTHENTICATED",
    )
    return {
        "actor_id": payload.actor_id,
        "household_id": payload.household_id,
        **authentication,
    }


@router.post("/auth/face-challenge", response_model=FaceChallengeRead)
def auth_face_challenge(
    payload: FaceChallengeRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Issue an opaque short-lived challenge; binding is checked at login."""
    client_host = request.client.host if request.client else None
    enforce_face_challenge_rate_limit(
        session,
        household_id=payload.household_id,
        client_key=client_host,
    )
    session.commit()
    return create_face_challenge(payload.actor_id, payload.household_id)


@router.post("/auth/family-face-challenge", response_model=FaceChallengeRead)
def auth_family_face_challenge(
    payload: FamilyFaceChallengeRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Issue a household-scoped challenge; actor identity is resolved later."""
    client_host = request.client.host if request.client else None
    enforce_face_challenge_rate_limit(
        session,
        household_id=payload.household_id,
        client_key=client_host,
    )
    session.commit()
    return create_family_face_challenge(payload.household_id)


@router.post("/auth/face-login", response_model=AuthSessionRead)
async def auth_face_login(
    household_id: str = Form(..., min_length=1, max_length=120),
    actor_id: str = Form(..., min_length=1, max_length=120),
    challenge_id: str = Form(..., min_length=16, max_length=128),
    frames: list[UploadFile] = File(...),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Match an in-memory motion sequence and issue the normal Bearer session."""
    try:
        rate_key = check_face_rate_limit(household_id, actor_id, session)
    except HTTPException:
        _record_authentication_audit(
            session,
            household_id=household_id,
            actor_id=actor_id,
            method="FACE",
            outcome="FAILED",
            reason="RATE_LIMITED",
        )
        raise

    def failed(reason: str = "FACE_AUTH_FAILED") -> NoReturn:
        record_face_failure(rate_key, session)
        _record_authentication_audit(
            session,
            household_id=household_id,
            actor_id=actor_id,
            method="FACE",
            outcome="FAILED",
            reason=normalize_face_failure_reason(reason),
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="FACE_AUTH_FAILED")

    try:
        consume_face_challenge(challenge_id, actor_id, household_id)
    except HTTPException:
        failed("CHALLENGE_INVALID")

    if not _actor_belongs_to_household(session, household_id, actor_id):
        failed("ACCOUNT_SCOPE_INVALID")
    credential = session.scalar(
        select(FaceCredential).where(
            FaceCredential.household_id == household_id,
            FaceCredential.actor_id == actor_id,
            FaceCredential.status == "ACTIVE",
        )
    )
    if credential is None or not credential.encrypted_template:
        failed("CREDENTIAL_UNAVAILABLE")

    frame_bytes: list[bytes] = []
    templates: list[bytes] = []
    yaws: list[float] = []
    try:
        if len(frames) < 2 or len(frames) > 3:
            failed("FRAME_COUNT_INVALID")
        for upload in frames:
            if upload.content_type not in {"image/jpeg", "image/png"}:
                failed("FRAME_TYPE_INVALID")
            data = await upload.read(2 * 1024 * 1024 + 1)
            if not data or len(data) > 2 * 1024 * 1024:
                failed("FRAME_SIZE_INVALID")
            if upload.content_type == "image/jpeg" and not data.startswith(b"\xff\xd8\xff"):
                failed("FRAME_MAGIC_INVALID")
            if upload.content_type == "image/png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
                failed("FRAME_MAGIC_INVALID")
            frame_bytes.append(data)
            from ai.vision.quality_gate import assess_image, decode_image

            quality = assess_image(
                decode_image(data),
                source_id="face-login",
                thresholds=settings.vision_quality_thresholds(),
            )
            if not quality["allow_downstream"]:
                failed("FRAME_QUALITY_INVALID")
            extractor = _face_extractor_for_algorithm(credential.algorithm_version)
            if credential.algorithm_version.startswith("opencv-yunet-sface"):
                template, frame_meta = extractor(data)
                yaws.append(float(frame_meta.get("yaw", 0.0)))
            else:
                template, _ = extractor(data)
            templates.append(template)
        try:
            pose_yaws = yaws if settings.face_require_pose_liveness and yaws else None
            check_face_liveness(templates, pose_yaws)
        except ValueError as exc:
            if str(exc) == "FACE_LIVENESS_FAILED":
                failed("LIVENESS_FAILED")
            failed("FACE_MATCH_FAILED")
        try:
            stored_template = decrypt_template(credential.encrypted_template)
            gallery = unpack_face_templates(stored_template)
        except HTTPException as exc:
            _record_authentication_audit(
                session,
                household_id=household_id,
                actor_id=actor_id,
                method="FACE",
                outcome="FAILED",
                reason="FACE_SERVICE_UNAVAILABLE",
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="FACE_AUTH_UNAVAILABLE",
            ) from exc
        except ValueError:
            failed("FACE_MATCH_FAILED")
        # Every frame must match the enrolled gallery (best angle per frame),
        # then take the minimum across frames so one stolen photo cannot pass.
        match_score = aggregate_match_scores(
            [score_probe_against_gallery(template, gallery) for template in templates]
        )
        if match_score < match_threshold_for(credential.algorithm_version):
            failed()
    except HTTPException:
        raise
    except ValueError:
        failed("FACE_MATCH_FAILED")
    except RuntimeError as exc:
        _record_authentication_audit(
            session,
            household_id=household_id,
            actor_id=actor_id,
            method="FACE",
            outcome="FAILED",
            reason="FACE_SERVICE_UNAVAILABLE",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FACE_AUTH_UNAVAILABLE",
        ) from exc
    finally:
        for index in range(len(frame_bytes)):
            frame_bytes[index] = b""
        templates.clear()

    clear_face_failures(rate_key, session)
    _record_authentication_audit(
        session,
        household_id=household_id,
        actor_id=actor_id,
        method="FACE",
        outcome="SUCCESS",
        reason="AUTHENTICATED",
    )
    return {
        "actor_id": actor_id,
        "household_id": household_id,
        **create_face_session(actor_id, household_id, session),
    }


@router.post("/auth/family-face-login", response_model=AuthSessionRead)
async def auth_family_face_login(
    household_id: str = Form(..., min_length=1, max_length=120),
    challenge_id: str = Form(..., min_length=16, max_length=128),
    frames: list[UploadFile] = File(...),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Identify one member inside the already bound household (1:N)."""
    rate_actor = family_face_rate_actor()
    try:
        rate_key = check_face_rate_limit(household_id, rate_actor, session)
    except HTTPException:
        _record_authentication_audit(
            session,
            household_id=household_id,
            actor_id=rate_actor,
            method="FACE",
            outcome="FAILED",
            reason="RATE_LIMITED",
        )
        raise

    def failed(reason: str = "FACE_AUTH_FAILED") -> NoReturn:
        record_face_failure(rate_key, session)
        _record_authentication_audit(
            session,
            household_id=household_id,
            actor_id=rate_actor,
            method="FACE",
            outcome="FAILED",
            reason=normalize_face_failure_reason(reason),
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="FACE_AUTH_FAILED")

    try:
        consume_family_face_challenge(challenge_id, household_id)
    except HTTPException:
        failed("CHALLENGE_INVALID")

    credentials = list(
        session.scalars(
            select(FaceCredential).where(
                FaceCredential.household_id == household_id,
                FaceCredential.status == "ACTIVE",
            )
        ).all()
    )
    credentials = [
        credential
        for credential in credentials
        if credential.encrypted_template
        and _actor_belongs_to_household(session, household_id, credential.actor_id)
    ]
    if not credentials:
        failed("CREDENTIAL_UNAVAILABLE")

    frame_bytes: list[bytes] = []
    templates_by_algorithm: dict[str, list[bytes]] = {}
    yaws_by_algorithm: dict[str, list[float]] = {}
    try:
        if len(frames) < 2 or len(frames) > 3:
            failed("FRAME_COUNT_INVALID")
        for upload in frames:
            if upload.content_type not in {"image/jpeg", "image/png"}:
                failed("FRAME_TYPE_INVALID")
            data = await upload.read(2 * 1024 * 1024 + 1)
            if not data or len(data) > 2 * 1024 * 1024:
                failed("FRAME_SIZE_INVALID")
            if upload.content_type == "image/jpeg" and not data.startswith(b"\xff\xd8\xff"):
                failed("FRAME_MAGIC_INVALID")
            if upload.content_type == "image/png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
                failed("FRAME_MAGIC_INVALID")
            frame_bytes.append(data)
            from ai.vision.quality_gate import assess_image, decode_image

            quality = assess_image(
                decode_image(data),
                source_id="family-face-login",
                thresholds=settings.vision_quality_thresholds(),
            )
            if not quality["allow_downstream"]:
                failed("FRAME_QUALITY_INVALID")

        # A household may contain legacy v1/v2 and current v3 credentials during
        # migration, so derive each feature representation only once per
        # algorithm version and keep all raw frames in memory only.
        for algorithm_version in {credential.algorithm_version for credential in credentials}:
            extractor = _face_extractor_for_algorithm(algorithm_version)
            extracted: list[bytes] = []
            yaws: list[float] = []
            for data in frame_bytes:
                template, frame_meta = extractor(data)
                extracted.append(template)
                if algorithm_version.startswith("opencv-yunet-sface"):
                    yaws.append(float(frame_meta.get("yaw", 0.0)))
            try:
                pose_yaws = yaws if settings.face_require_pose_liveness and yaws else None
                check_face_liveness(extracted, pose_yaws)
            except ValueError as exc:
                if str(exc) == "FACE_LIVENESS_FAILED":
                    failed("LIVENESS_FAILED")
                failed("FACE_MATCH_FAILED")
            templates_by_algorithm[algorithm_version] = extracted
            yaws_by_algorithm[algorithm_version] = yaws

        candidates: list[tuple[float, float, str, str]] = []
        decrypt_failures = 0
        for credential in credentials:
            try:
                stored_template = decrypt_template(credential.encrypted_template)
                gallery = unpack_face_templates(stored_template)
                templates = templates_by_algorithm[credential.algorithm_version]
                # Same rule as 1:1 login: all frames must match one member gallery.
                score = aggregate_match_scores(
                    [score_probe_against_gallery(template, gallery) for template in templates]
                )
            except (HTTPException, ValueError, KeyError):
                decrypt_failures += 1
                continue
            candidates.append(
                (
                    ranking_margin(score, credential.algorithm_version),
                    score,
                    credential.actor_id,
                    credential.algorithm_version,
                )
            )
        if not candidates:
            if decrypt_failures:
                raise RuntimeError("FACE_CREDENTIALS_UNAVAILABLE")
            failed("CREDENTIAL_UNAVAILABLE")

        candidates.sort(key=lambda item: item[0], reverse=True)
        best_margin, best_score, best_actor_id, best_algorithm = candidates[0]
        second_margin = candidates[1][0] if len(candidates) > 1 else None
        if best_margin < 0 or best_score < match_threshold_for(best_algorithm):
            failed("NO_MATCH")
        if (
            second_margin is not None
            and best_margin - second_margin < family_match_margin_for(best_algorithm)
        ):
            # A close race between two family members is not safe to resolve
            # automatically; the UI falls back to PIN/explicit account login.
            failed("AMBIGUOUS_MATCH")
    except HTTPException:
        raise
    except ValueError:
        failed("FACE_MATCH_FAILED")
    except RuntimeError as exc:
        _record_authentication_audit(
            session,
            household_id=household_id,
            actor_id=rate_actor,
            method="FACE",
            outcome="FAILED",
            reason="FACE_SERVICE_UNAVAILABLE",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FACE_AUTH_UNAVAILABLE",
        ) from exc
    finally:
        for index in range(len(frame_bytes)):
            frame_bytes[index] = b""
        for templates in templates_by_algorithm.values():
            templates.clear()
        templates_by_algorithm.clear()

    clear_face_failures(rate_key, session)
    _record_authentication_audit(
        session,
        household_id=household_id,
        actor_id=best_actor_id,
        method="FACE",
        outcome="SUCCESS",
        reason="FAMILY_MATCH_AUTHENTICATED",
    )
    return {
        "actor_id": best_actor_id,
        "household_id": household_id,
        **create_face_session(best_actor_id, household_id, session),
    }


@router.post("/auth/pin", response_model=dict)
def auth_set_pin(
    payload: PinSetRequest,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> dict:
    if not _actor_belongs_to_household(session, payload.household_id, actor_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RESOURCE_NOT_FOUND")
    set_account_pin(actor_id, payload.household_id, payload.pin, session)
    session.add(
        AccessAudit(
            household_id=payload.household_id,
            authorization_id=None,
            actor_id=actor_id,
            operation="PIN_CREDENTIAL",
            action="SET",
            data_field="pin",
            purpose="authentication",
            outcome="SUCCESS",
            reason="PIN_CONFIGURED",
        )
    )
    session.commit()
    return {"status": "pin_configured", "household_id": payload.household_id}


@router.post("/auth/logout")
def auth_logout(payload: AuthSessionRequest, session: Session = Depends(get_session)) -> dict:
    logout(payload.session_token, session)
    session.commit()
    return {"status": "logged_out"}


@router.post("/auth/session", response_model=SessionIntrospectRead)
def auth_session(
    session_token: str = Depends(require_session_token),
    session: Session = Depends(get_session),
) -> dict:
    """Revalidate the caller's session so a client can drop a stale one early."""
    return introspect_session(session_token, session)


@router.post("/auth/pin-challenge", response_model=StepUpChallengeRead)
def auth_pin_challenge(
    payload: StepUpChallengeRequest,
    actor_id: str = Depends(get_actor_id),
    session_token: str = Depends(require_session_token),
    session: Session = Depends(get_session),
) -> dict:
    # Household selection stays server-side: an explicit household_id is only
    # honoured when this actor really belongs to it.
    if payload.household_id is not None and not _actor_belongs_to_household(
        session, payload.household_id, actor_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RESOURCE_NOT_FOUND")
    return generate_pin_challenge(
        actor_id,
        payload.action,
        session_token,
        payload.household_id,
        session,
    )


@router.post("/auth/pin-verify", response_model=StepUpGrantRead)
def auth_pin_verify(
    payload: StepUpVerifyRequest,
    session_token: str = Depends(require_session_token),
    session: Session = Depends(get_session),
) -> dict:
    # The one-time code travels in the request body only; it must never reach a
    # query string, where reverse proxies and APM tools would log it.
    return verify_pin_challenge(
        payload.challenge_id,
        payload.action,
        session_token,
        payload.code,
        session,
    )


# HCT-424: face credential registration and binding.  Login matching and
# liveness remain deliberately outside this route (HCT-425).
FACE_REGISTER_ACTION = "register_face"


def _require_face_target(
    session: Session,
    household_id: str,
    target_actor_id: str,
) -> None:
    if not _actor_belongs_to_household(session, household_id, target_actor_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RESOURCE_NOT_FOUND")


def _confirm_face_registration(
    *,
    actor_id: str,
    household_id: str,
    session_token: str,
    confirmation_method: str,
    confirmation_code: str,
    confirmation_challenge_id: str | None,
    session: Session,
) -> None:
    if confirmation_challenge_id:
        consume_pin_challenge(
            confirmation_challenge_id,
            FACE_REGISTER_ACTION,
            session_token,
            household_id,
            session,
        )
        return
    from app.auth import verify_reauthentication

    verify_reauthentication(actor_id, household_id, confirmation_method, confirmation_code, session)


def _face_credential_read(credential: FaceCredential) -> FaceCredentialRead:
    template_count = 3 if "multi" in (credential.feature_version or "") else 1
    return FaceCredentialRead(
        id=credential.id,
        household_id=credential.household_id,
        actor_id=credential.actor_id,
        algorithm_version=credential.algorithm_version,
        feature_version=credential.feature_version,
        credential_version=credential.credential_version,
        consent_version=credential.consent_version,
        status=credential.status,  # type: ignore[arg-type]
        created_by=credential.created_by,
        consented_at=credential.consented_at,
        revoked_at=credential.revoked_at,
        created_at=credential.created_at,
        upgrade_recommended=is_legacy_face_algorithm(credential.algorithm_version),
        template_count=template_count,
    )


@router.get(
    "/households/{household_id}/face-credentials",
    response_model=list[FaceCredentialRead],
)
def list_face_credentials(
    household_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> list[FaceCredentialRead]:
    require_household_owner(session, household_id, actor_id)
    rows = list(
        session.scalars(
            select(FaceCredential)
            .where(
                FaceCredential.household_id == household_id,
                FaceCredential.status != "DELETED",
            )
            .order_by(FaceCredential.created_at.desc())
        ).all()
    )
    return [_face_credential_read(row) for row in rows]


@router.get(
    "/households/{household_id}/auth-audit/face-summary",
    response_model=FaceAuthFailureSummaryRead,
)
def face_auth_failure_summary(
    household_id: str,
    days: int = 7,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> FaceAuthFailureSummaryRead:
    """Owner-only desensitized FACE failure buckets (no scores/templates/images)."""
    require_household_owner(session, household_id, actor_id)
    window_days = max(1, min(int(days), 30))
    since = datetime.now(UTC) - timedelta(days=window_days)
    rows = session.scalars(
        select(AccessAudit).where(
            AccessAudit.household_id == household_id,
            AccessAudit.operation == "AUTHENTICATION",
            AccessAudit.action == "FACE_LOGIN",
            AccessAudit.outcome == "FAILED",
            AccessAudit.created_at >= since,
        )
    ).all()
    totals: dict[str, int] = {}
    by_day: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = normalize_face_failure_reason(row.reason or "FACE_AUTH_FAILED")
        totals[bucket] = totals.get(bucket, 0) + 1
        day_key = row.created_at.astimezone(UTC).date().isoformat()
        day_bucket = by_day.setdefault(day_key, {})
        day_bucket[bucket] = day_bucket.get(bucket, 0) + 1
    return FaceAuthFailureSummaryRead(days=window_days, totals=totals, by_day=by_day)


@router.post(
    "/households/{household_id}/face-credentials",
    response_model=FaceCredentialRead,
    status_code=status.HTTP_201_CREATED,
)
async def register_face_credential(
    household_id: str,
    frames: list[UploadFile] = File(default=[]),
    file: UploadFile | None = File(default=None),
    consent: bool = Form(default=False),
    target_actor_id: str | None = Form(default=None, max_length=120),
    replace_existing: bool = Form(default=False),
    confirmation_method: str = Form(default="pin"),
    confirmation_code: str = Form(default=""),
    confirmation_challenge_id: str | None = Form(default=None, max_length=128),
    actor_id: str = Depends(get_actor_id),
    session_token: str = Depends(require_session_token),
    session: Session = Depends(get_session),
) -> FaceCredential:
    if not consent:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="FACE_CONSENT_REQUIRED",
        )
    household = require_household_owner(session, household_id, actor_id)
    target = (target_actor_id or actor_id).strip()
    if not target:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="FACE_TARGET_REQUIRED",
        )
    _require_face_target(session, household.id, target)

    active = session.scalar(
        select(FaceCredential).where(
            FaceCredential.household_id == household.id,
            FaceCredential.actor_id == target,
            FaceCredential.status == "ACTIVE",
        )
    )
    if active is not None and not replace_existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="FACE_CREDENTIAL_EXISTS")

    # Verify the PIN/password/step-up confirmation before touching any
    # biometric pixels: without a valid second factor the endpoint must not
    # act as a face-quality/liveness oracle or burn CPU on frame processing.
    _confirm_face_registration(
        actor_id=actor_id,
        household_id=household.id,
        session_token=session_token,
        confirmation_method=confirmation_method,
        confirmation_code=confirmation_code,
        confirmation_challenge_id=confirmation_challenge_id,
        session=session,
    )

    # ``file`` remains accepted for one release so old local clients do not
    # break. The web UI always sends a 2–3 frame dynamic sequence.
    uploads = list(frames)
    if not uploads and file is not None:
        uploads = [file]
    if len(uploads) < 2 or len(uploads) > 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="FACE_LIVENESS_FAILED",
        )
    templates: list[bytes] = []
    yaws: list[float] = []
    metadata: dict[str, Any] | None = None
    packed_template = b""
    try:
        from ai.vision.quality_gate import assess_image, decode_image

        for upload in uploads:
            filename = validate_filename(upload.filename or "unknown")
            extension = validate_extension(filename)
            if extension not in {".jpg", ".jpeg", ".png"} or upload.content_type not in {
                "image/jpeg",
                "image/png",
            }:
                raise ValueError("FACE_IMAGE_INVALID")
            validate_magic(upload.file, extension)
            validate_size(upload.file)
            image_bytes = await upload.read(2 * 1024 * 1024 + 1)
            if not image_bytes or len(image_bytes) > 2 * 1024 * 1024:
                raise ValueError("FACE_FRAME_SIZE_INVALID")
            quality = assess_image(
                decode_image(image_bytes),
                source_id="face-registration",
                thresholds=settings.vision_quality_thresholds(),
            )
            if not quality["allow_downstream"]:
                raise ValueError("FACE_FRAME_LOW_QUALITY")
            # Geometry gates (face size/pose/blur) run inside extract_face_template.
            template, frame_metadata = extract_face_template(image_bytes, enforce_geometry=True)
            templates.append(template)
            yaws.append(float(frame_metadata.get("yaw", 0.0)))
            metadata = frame_metadata
            image_bytes = b""
        try:
            pose_yaws = yaws if settings.face_require_pose_liveness else None
            check_face_liveness(templates, pose_yaws)
        except ValueError as exc:
            raise ValueError("FACE_LIVENESS_FAILED") from exc
        # Keep every angle in an encrypted multi-template gallery so login can
        # tolerate mild head turns without lowering the match threshold.
        packed_template = pack_face_templates(templates)
        if metadata is not None and len(templates) > 1:
            metadata = {
                **metadata,
                "feature_version": FACE_FEATURE_VERSION_MULTI,
                "template_count": len(templates),
            }
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    finally:
        # Drop all decoded registration frames before touching the database.
        templates.clear()
        yaws.clear()

    if metadata is None or not packed_template:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="FACE_FRAME_INVALID",
        )

    now = datetime.now(UTC)
    previous_version = active.credential_version if active is not None else 0
    if active is not None:
        active.status = "REVOKED"
        active.revoked_at = now
        active.encrypted_template = b""
        # Rebinding replaces the trusted template, so household-scoped
        # sessions issued under the previous credential stop working now.
        revoke_household_sessions(household.id, {target}, session)
        session.flush()

    credential = FaceCredential(
        household_id=household.id,
        actor_id=target,
        encrypted_template=encrypt_template(packed_template),
        algorithm_version=metadata["algorithm_version"],
        feature_version=metadata["feature_version"],
        credential_version=previous_version + 1,
        consent_version=FACE_CONSENT_VERSION,
        status="ACTIVE",
        created_by=actor_id,
        consented_at=now,
    )
    session.add(credential)
    session.add(
        AccessAudit(
            household_id=household.id,
            authorization_id=None,
            actor_id=actor_id,
            operation="FACE_CREDENTIAL",
            action="REGISTER" if active is None else "REBIND",
            data_field="biometric_template",
            purpose="face-registration",
            outcome="SUCCESS",
            reason=None,
            before_version=previous_version or None,
            after_version=credential.credential_version,
        )
    )
    session.commit()
    session.refresh(credential)
    logger.info(
        "FACE_CREDENTIAL_%s actor=%s household=%s credential=%s version=%d",
        "REGISTERED" if active is None else "REBIND",
        actor_id,
        household.id,
        credential.id,
        credential.credential_version,
    )
    return _face_credential_read(credential)


@router.delete(
    "/households/{household_id}/face-credentials/{credential_id}",
    response_model=FaceCredentialRead,
)
def revoke_face_credential(
    household_id: str,
    credential_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> FaceCredentialRead:
    household = require_household_owner(session, household_id, actor_id)
    credential = session.scalar(
        select(FaceCredential).where(
            FaceCredential.id == credential_id,
            FaceCredential.household_id == household.id,
        )
    )
    if credential is None:
        _raise_resource_not_found()
    if credential.status == "ACTIVE":
        credential.status = "DELETED"
        credential.revoked_at = datetime.now(UTC)
        credential.encrypted_template = b""
        # HCT-426: revoking the credential must also cut live access that was
        # obtained with it, so the account's household-scoped sessions
        # (face/PIN issued) become invalid immediately.
        revoke_household_sessions(household.id, {credential.actor_id}, session)
        session.add(
            AccessAudit(
                household_id=household.id,
                authorization_id=None,
                actor_id=actor_id,
                operation="FACE_CREDENTIAL",
                action="DELETE",
                data_field="biometric_template",
                purpose="face-registration",
                outcome="SUCCESS",
                reason=None,
                before_version=credential.credential_version,
                after_version=credential.credential_version,
            )
        )
        session.commit()
        session.refresh(credential)
    return _face_credential_read(credential)


# ── HCT-301: Event timeline & projection ───────────────────────────


@router.get("/households/{household_id}/members/{member_id}/timeline")
def member_timeline(
    household_id: str,
    member_id: str,
    since: str | None = None,
    until: str | None = None,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> list[HealthEventRead]:
    household = session.get(Household, household_id)
    member = session.get(Member, member_id)
    if _is_erased(household, member):
        _raise_resource_not_found()
    if not has_member_read_access(
        session,
        household,
        member_id,
        actor_id,
        access_purpose,
    ):
        _raise_resource_not_found()

    from app.projection import get_timeline

    since_dt = datetime.fromisoformat(since) if since else None
    until_dt = datetime.fromisoformat(until) if until else None
    events = get_timeline(session, member_id, since=since_dt, until=until_dt)
    if is_self_member(session, household, member_id, actor_id):
        events = [event for event in events if event.confirmation_status == "CONFIRMED"]
    return [HealthEventRead.model_validate(e) for e in events]


@router.get(
    "/households/{household_id}/members/{member_id}/relationship-graph",
    response_model=RelationshipGraphRead,
)
def get_relationship_graph(
    household_id: str,
    member_id: str,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> RelationshipGraphRead:
    household = session.get(Household, household_id)
    member = session.get(Member, member_id)
    if _is_erased(household, member):
        _raise_resource_not_found()
    if not has_member_read_access(
        session,
        household,
        member_id,
        actor_id,
        access_purpose,
    ):
        _raise_resource_not_found()

    from app.projection import build_relationship_graph_view, get_timeline

    graph = build_relationship_graph_view(get_timeline(session, member_id))
    return RelationshipGraphRead(member_id=member_id, generated_at=datetime.now(UTC), **graph)


@router.post("/households/{household_id}/members/{member_id}/projection/rebuild")
def rebuild_member_projection(
    household_id: str,
    member_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> dict:
    household = session.get(Household, household_id)
    if _is_erased(household) or household.created_by != actor_id:
        _raise_resource_not_found()
    from app.projection import rebuild_projection

    proj = rebuild_projection(session, member_id, household_id)
    return {"member_id": member_id, "state": proj.state, "last_event_id": proj.last_event_id}


@router.get(
    "/households/{household_id}/members/{member_id}/plan-workbench",
    response_model=PlanWorkbenchRead,
)
def get_plan_workbench(
    household_id: str,
    member_id: str,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> PlanWorkbenchRead:
    household = session.get(Household, household_id)
    member = session.get(Member, member_id)
    if _is_erased(household, member):
        _raise_resource_not_found()
    if not has_member_read_access(
        session,
        household,
        member_id,
        actor_id,
        access_purpose,
    ):
        _raise_resource_not_found()

    from app.care_plan import build_plan_workbench
    from app.projection import get_timeline

    return PlanWorkbenchRead(
        member_id=member_id,
        generated_at=datetime.now(UTC),
        plans=build_plan_workbench(
            get_timeline(session, member_id),
            time_zone=household.time_zone,
        ),
    )


@router.get("/households/{household_id}/dashboard-summary", response_model=DashboardSummaryRead)
def get_dashboard_summary(
    household_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> DashboardSummaryRead:
    household = session.get(Household, household_id)
    if _is_erased(household) or household.created_by != actor_id:
        _raise_resource_not_found()

    members = list(
        session.scalars(
            select(Member).where(Member.household_id == household_id, Member.deleted_at.is_(None))
        ).all()
    )
    member_ids = [member.id for member in members]
    events = list(
        session.scalars(
            select(HealthEvent)
            .where(
                HealthEvent.household_id == household_id,
                HealthEvent.confirmation_status == "CONFIRMED",
            )
            .order_by(HealthEvent.created_at)
        ).all()
    )
    now = datetime.now(UTC)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    counts_by_day: dict[str, int] = {}
    for event in events:
        occurred_at = event.occurred_at
        normalized = occurred_at if occurred_at.tzinfo else occurred_at.replace(tzinfo=UTC)
        day = normalized.date().isoformat()
        counts_by_day[day] = counts_by_day.get(day, 0) + 1

    from app.projection import build_relationship_graph
    from app.rules import run_rules

    severe_count = 0
    warning_count = 0
    info_count = 0
    for member_id in member_ids:
        member_events = [event for event in events if event.member_id == member_id]
        for alert in run_rules(build_relationship_graph(member_events)):
            if alert.level == "SEVERE":
                severe_count += 1
            elif alert.level == "WARNING":
                warning_count += 1
            else:
                info_count += 1

    pending_reviews = (
        session.scalar(
            select(func.count())
            .select_from(ReviewTask)
            .where(
                ReviewTask.household_id == household_id,
                ReviewTask.status == "PENDING_REVIEW",
            )
        )
        or 0
    )
    pending_outbox = (
        session.scalar(
            select(func.count())
            .select_from(OutboxMessage)
            .join(HealthEvent, OutboxMessage.event_id == HealthEvent.id)
            .where(
                HealthEvent.household_id == household_id,
                OutboxMessage.status.in_(("PENDING", "FAILED")),
            )
        )
        or 0
    )
    week_series = []
    for offset in range(6, -1, -1):
        day = (today - timedelta(days=offset)).date().isoformat()
        week_series.append({"day": day, "count": counts_by_day.get(day, 0)})

    return DashboardSummaryRead(
        generated_at=now,
        member_count=len(members),
        events_today=counts_by_day.get(today.date().isoformat(), 0),
        events_total=len(events),
        severe_count=severe_count,
        warning_count=warning_count,
        info_count=info_count,
        pending_reviews=int(pending_reviews),
        pending_outbox=int(pending_outbox),
        week_series=week_series,
    )


# ── HCT-302: Rules engine ──────────────────────────────────────────


@router.post("/households/{household_id}/rules/run")
def run_rules_endpoint(
    household_id: str,
    member_id: str,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> list[dict]:
    household = session.get(Household, household_id)
    member = session.get(Member, member_id)
    if (
        _is_erased(household, member)
        or not has_member_read_access(
            session, household, member_id, actor_id, access_purpose
        )
    ):
        _raise_resource_not_found()
    from app.projection import build_relationship_graph, get_timeline
    from app.rules import run_rules

    events = get_timeline(session, member_id)
    facts = build_relationship_graph(events)
    alerts = run_rules(facts)
    logger.info("RULES_RUN member=%s alerts=%d", member_id, len(alerts))
    return [
        {
            "rule_id": a.rule_id,
            "level": a.level,
            "message": a.message,
            "source_event_ids": a.source_event_ids,
        }
        for a in alerts
    ]


# ── HCT-304/308: Care plans & escalation ───────────────────────────


def _append_care_plan_action(
    session: Session,
    *,
    household: Household,
    member: Member,
    actor_id: str,
    request: Request,
    event_type: str,
    payload: dict[str, object],
    idempotency_key: str,
    occurred_at: datetime | None = None,
) -> HealthEvent:
    correlation_id = getattr(request.state, "request_id", None) or request.headers.get(
        settings.request_id_header, ""
    )
    return append_health_event_transaction(
        session,
        household=household,
        member=member,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload=HealthEventCreate(
            member_id=member.id,
            event_type=event_type,
            confirmation_status="CONFIRMED",
            payload=payload,
            occurred_at=occurred_at,
        ),
    )


@router.post(
    "/households/{household_id}/members/{member_id}/plans/confirm",
    status_code=status.HTTP_201_CREATED,
)
def confirm_plan_endpoint(
    household_id: str,
    member_id: str,
    plan_event_id: str,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> HealthEventRead:
    household = session.get(Household, household_id)
    member = session.get(Member, member_id)
    if _is_erased(household, member):
        _raise_resource_not_found()
    if not has_authorized_action(
        session,
        household,
        member_id,
        actor_id,
        "WRITE_EVENTS",
        "health_events",
        access_purpose,
    ):
        _raise_resource_not_found()
    from app.projection import get_timeline

    now = datetime.now(UTC)
    effective_key = idempotency_key or f"confirm:{plan_event_id}:{now.strftime('%Y%m%d%H%M')}"
    existing = session.scalar(
        select(HealthEvent).where(
            HealthEvent.household_id == household.id,
            HealthEvent.idempotency_key == effective_key,
        )
    )
    if existing is not None:
        if (
            existing.member_id != member.id
            or str((existing.payload or {}).get("plan_event_id") or "") != plan_event_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="IDEMPOTENCY_KEY_CONFLICT",
            )
        return HealthEventRead.model_validate(existing)
    validate_plan_confirmation_window(
        get_timeline(session, member_id),
        plan_event_id,
        now,
        time_zone=household.time_zone,
    )
    event = _append_care_plan_action(
        session,
        household=household,
        member=member,
        actor_id=actor_id,
        request=request,
        event_type="plan_confirmed",
        payload={"plan_event_id": plan_event_id, "confirmed_at": now.isoformat()},
        idempotency_key=effective_key,
        occurred_at=now,
    )
    return HealthEventRead.model_validate(event)


@router.post(
    "/households/{household_id}/members/{member_id}/plans/defer",
    status_code=status.HTTP_201_CREATED,
)
def defer_plan_endpoint(
    household_id: str,
    member_id: str,
    plan_event_id: str,
    request: Request,
    delay_hours: int = 4,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> HealthEventRead:
    household = session.get(Household, household_id)
    member = session.get(Member, member_id)
    if _is_erased(household, member):
        _raise_resource_not_found()
    if not has_authorized_action(
        session,
        household,
        member_id,
        actor_id,
        "WRITE_EVENTS",
        "health_events",
        access_purpose,
    ):
        _raise_resource_not_found()
    event = _append_care_plan_action(
        session,
        household=household,
        member=member,
        actor_id=actor_id,
        request=request,
        event_type="plan_deferred",
        payload={
            "plan_event_id": plan_event_id,
            "delay_hours": delay_hours,
            "deferred_at": datetime.now(UTC).isoformat(),
        },
        idempotency_key=f"defer:{plan_event_id}",
    )
    return HealthEventRead.model_validate(event)


@router.post(
    "/households/{household_id}/members/{member_id}/plans/skip",
    status_code=status.HTTP_201_CREATED,
)
def skip_plan_endpoint(
    household_id: str,
    member_id: str,
    plan_event_id: str,
    request: Request,
    reason: str = "",
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> HealthEventRead:
    household = session.get(Household, household_id)
    member = session.get(Member, member_id)
    if _is_erased(household, member):
        _raise_resource_not_found()
    if not has_authorized_action(
        session,
        household,
        member_id,
        actor_id,
        "WRITE_EVENTS",
        "health_events",
        access_purpose,
    ):
        _raise_resource_not_found()
    event = _append_care_plan_action(
        session,
        household=household,
        member=member,
        actor_id=actor_id,
        request=request,
        event_type="plan_skipped",
        payload={
            "plan_event_id": plan_event_id,
            "reason": reason,
            "skipped_at": datetime.now(UTC).isoformat(),
        },
        idempotency_key=f"skip:{plan_event_id}",
    )
    return HealthEventRead.model_validate(event)


@router.post(
    "/households/{household_id}/members/{member_id}/plans/missed",
    status_code=status.HTTP_201_CREATED,
)
def miss_plan_endpoint(
    household_id: str,
    member_id: str,
    plan_event_id: str,
    request: Request,
    reason: str = Query(min_length=1, max_length=240),
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> HealthEventRead:
    household = session.get(Household, household_id)
    member = session.get(Member, member_id)
    if _is_erased(household, member):
        _raise_resource_not_found()
    if not has_authorized_action(
        session,
        household,
        member_id,
        actor_id,
        "WRITE_EVENTS",
        "health_events",
        access_purpose,
    ):
        _raise_resource_not_found()
    event = _append_care_plan_action(
        session,
        household=household,
        member=member,
        actor_id=actor_id,
        request=request,
        event_type="plan_missed",
        payload={
            "plan_event_id": plan_event_id,
            "reason": reason.strip(),
            "missed_at": datetime.now(UTC).isoformat(),
        },
        idempotency_key=f"miss:{plan_event_id}:{datetime.now(UTC).date().isoformat()}",
    )
    return HealthEventRead.model_validate(event)


@router.post(
    "/households/{household_id}/members/{member_id}/plans/evaluate",
    response_model=PlanAutomationRead,
)
def evaluate_plan_automation_endpoint(
    household_id: str,
    member_id: str,
    request: Request,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> PlanAutomationRead:
    """Evaluate explicitly authorized reminder automation for one member.

    This endpoint is owner-only because it can append health and notification
    events. Existing plans remain read-only unless their payload explicitly
    opts into automation.
    """
    household = require_household_owner(session, household_id, actor_id)
    member = _require_household_member(session, household_id, member_id)
    if _is_erased(household, member):
        _raise_resource_not_found()

    evaluated_at = datetime.now(UTC)
    correlation_id = getattr(request.state, "request_id", None) or request.headers.get(
        settings.request_id_header, ""
    )
    from app.care_plan import execute_plan_automation

    created_events, notified_actor_ids = execute_plan_automation(
        session,
        household=household,
        member=member,
        actor_id=actor_id,
        correlation_id=correlation_id,
        now=evaluated_at,
    )

    return PlanAutomationRead(
        member_id=member.id,
        evaluated_at=evaluated_at,
        created_events=[HealthEventRead.model_validate(item) for item in created_events],
        notified_caregiver_actor_ids=notified_actor_ids,
    )


# ── HCT-401: Knowledge store & RAG ──────────────────────────────────


@router.post(
    "/knowledge/documents",
    response_model=KnowledgeDocumentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge_document(
    payload: KnowledgeDocumentCreate,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> KnowledgeDocumentRead:
    """Register a new knowledge document with auto-chunking."""
    from app.knowledge import add_document

    doc = add_document(
        session,
        title=payload.title,
        content=payload.content,
        source=payload.source,
        created_by=actor_id,
        license=payload.license,
        version=payload.version,
        permission_scope=payload.permission_scope,
        effective_from=payload.effective_from,
        effective_until=payload.effective_until,
    )
    session.commit()
    session.refresh(doc)
    return KnowledgeDocumentRead.model_validate(doc)


@router.get("/knowledge/documents", response_model=list[KnowledgeDocumentRead])
def list_knowledge_documents(
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> list[KnowledgeDocumentRead]:
    """List active documents visible to the caller."""
    from app.knowledge import _check_permission

    knowledge_admins = get_settings().knowledge_admin_actor_set
    stmt = (
        select(KnowledgeDocument)
        .where(KnowledgeDocument.status == "active")
        .order_by(KnowledgeDocument.created_at.desc())
    )
    docs = session.scalars(stmt).all()
    return [
        d
        for d in docs
        if _check_permission(
            d.permission_scope or {},
            actor_id,
            doc_created_by=d.created_by,
            knowledge_admin_ids=knowledge_admins,
        )
    ]


@router.get("/knowledge/documents/{doc_id}", response_model=KnowledgeDocumentRead)
def get_knowledge_document(
    doc_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> KnowledgeDocumentRead:
    from app.knowledge import _check_permission

    doc = session.get(KnowledgeDocument, doc_id)
    if doc is None or doc.status != "active":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DOCUMENT_NOT_FOUND")
    if not _check_permission(
        doc.permission_scope or {},
        actor_id,
        doc_created_by=doc.created_by,
        knowledge_admin_ids=get_settings().knowledge_admin_actor_set,
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DOCUMENT_NOT_FOUND")
    return doc


@router.post(
    "/knowledge/retrieve",
    response_model=KnowledgeRetrieveResponse,
)
def retrieve_knowledge(
    payload: KnowledgeRetrieveRequest,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> KnowledgeRetrieveResponse:
    """TF-IDF retrieval with pre-filter permission gate.

    Returns a structured degrade response if no authorised documents exist
    or the index is empty — never exposes cross-family content.
    """
    from app.knowledge import log_query, retrieve

    try:
        results = retrieve(
            session,
            query=payload.query,
            actor_id=actor_id,
            household_id=payload.household_id,
            member_id=payload.member_id,
            top_k=payload.top_k,
        )
        log_entry = log_query(
            session,
            query_text=payload.query,
            actor_id=actor_id,
            household_id=payload.household_id,
            member_id=payload.member_id,
            top_chunk_ids=[r["chunk_id"] for r in results],
            returned_count=len(results),
        )
        session.commit()
        return KnowledgeRetrieveResponse(
            query=payload.query,
            results=results,
            total=len(results),
            query_id=log_entry.id,
        )
    except ValueError as exc:
        session.rollback()
        reason = str(exc)
        return KnowledgeRetrieveResponse(
            query=payload.query,
            results=[],
            total=0,
            degraded=True,
            degrade_reason=reason,
        )


@router.get("/knowledge/query-audit", response_model=list[KnowledgeQueryAuditRead])
def list_knowledge_query_audit(
    limit: int = Query(default=50, ge=1, le=100),
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> list[KnowledgeQueryAuditRead]:
    """Return only the caller's privacy-safe retrieval audit summaries."""
    entries = session.scalars(
        select(RetrievalQuery)
        .where(RetrievalQuery.actor_id == actor_id)
        .order_by(RetrievalQuery.created_at.desc())
        .limit(limit)
    ).all()
    return [
        KnowledgeQueryAuditRead(
            id=entry.id,
            query_digest=entry.query_digest,
            query_length=entry.query_length,
            household_id=entry.household_id,
            member_id=entry.member_id,
            returned_count=entry.returned_count,
            top_chunk_count=len(entry.top_chunk_ids or []),
            created_at=entry.created_at,
        )
        for entry in entries
    ]


@router.get("/knowledge/query-audit/page", response_model=KnowledgeQueryAuditPageRead)
def page_knowledge_query_audit(
    household_id: str | None = Query(default=None, min_length=1, max_length=36),
    member_id: str | None = Query(default=None, min_length=1, max_length=36),
    cursor: str | None = Query(default=None, min_length=1),
    limit: int = Query(default=50, ge=1, le=100),
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> KnowledgeQueryAuditPageRead:
    """Page privacy-safe query audits without exposing raw query contents."""
    decoded_cursor = None
    if cursor is not None:
        try:
            decoded_cursor = decode_knowledge_audit_cursor(
                cursor, secret=settings.cursor_signing_key
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        if (
            decoded_cursor.actor_id != actor_id
            or decoded_cursor.household_id != household_id
            or decoded_cursor.member_id != member_id
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="KNOWLEDGE_AUDIT_CURSOR_INVALID",
            )

    query = select(RetrievalQuery).where(RetrievalQuery.actor_id == actor_id)
    if household_id is not None:
        query = query.where(RetrievalQuery.household_id == household_id)
    if member_id is not None:
        query = query.where(RetrievalQuery.member_id == member_id)
    if decoded_cursor is not None:
        query = query.where(
            (RetrievalQuery.created_at < decoded_cursor.created_at)
            | (
                (RetrievalQuery.created_at == decoded_cursor.created_at)
                & (RetrievalQuery.id < decoded_cursor.audit_id)
            )
        )

    rows = list(
        session.scalars(
            query.order_by(RetrievalQuery.created_at.desc(), RetrievalQuery.id.desc()).limit(
                limit + 1
            )
        ).all()
    )
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_knowledge_audit_cursor(
            actor_id=actor_id,
            household_id=household_id,
            member_id=member_id,
            created_at=last.created_at,
            audit_id=last.id,
            secret=settings.cursor_signing_key,
        )
    return KnowledgeQueryAuditPageRead(
        items=[
            KnowledgeQueryAuditRead(
                id=entry.id,
                query_digest=entry.query_digest,
                query_length=entry.query_length,
                household_id=entry.household_id,
                member_id=entry.member_id,
                returned_count=entry.returned_count,
                top_chunk_count=len(entry.top_chunk_ids or []),
                created_at=entry.created_at,
            )
            for entry in items
        ],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.delete("/knowledge/documents/{doc_id}")
def delete_knowledge_document(
    doc_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> dict:
    from app.knowledge import delete_document

    doc = session.get(KnowledgeDocument, doc_id)
    if doc is None or doc.status != "active" or doc.created_by != actor_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DOCUMENT_NOT_FOUND")
    if not delete_document(session, doc_id, deleted_by=actor_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DOCUMENT_NOT_FOUND")
    session.commit()
    return {"status": "deleted", "document_id": doc_id}


@router.post("/knowledge/index/snapshot")
def create_knowledge_index_snapshot(
    version: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> dict:
    from app.knowledge import create_index_snapshot

    idx = create_index_snapshot(session, version=version, created_by=actor_id)
    session.commit()
    return {
        "index_id": idx.id,
        "version": idx.version,
        "document_count": idx.document_count,
        "chunk_count": idx.chunk_count,
        "checksum": idx.checksum,
    }


# ── HCT-403: Local assistant (Ollama tool calling) ───────────────────


@router.get("/assistant/tools")
def list_assistant_tools(
    actor_id: str = Depends(get_actor_id),
) -> dict:
    """List all approved tools the local assistant can call."""
    tools = [t.model_dump() for t in get_approved_tools()]
    return {"tools": tools, "count": len(tools)}


@router.get("/assistant/agents")
def list_assistant_agents(
    actor_id: str = Depends(get_actor_id),
) -> dict:
    """Describe the local agent graph and its explicit network-search gate."""
    del actor_id  # The catalog contains no household or member data.
    return get_agent_catalog(settings)


def _summarize_event_payload(payload: dict | None) -> str:
    if not payload:
        return ""
    for key in ("drug_name", "drug", "allergy", "disease", "plan", "note"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _build_assistant_context(
    session: Session,
    actor_id: str,
    household_id: str | None,
    member_id: str | None,
) -> str | None:
    """Ground the assistant in the member's confirmed local facts (RAG-lite).

    The v5 adapter is trained evidence-first: without grounds it refuses or
    hedges. Injecting the projection facts and active rule alerts gives it
    the "先依据后解释" context the product spec requires. Only the household
    owner gets the injection; anyone else keeps the ungrounded behaviour.
    """
    if not household_id or not member_id:
        return None
    household = session.get(Household, household_id)
    member = session.get(Member, member_id)
    if (
        household is None
        or member is None
        or member.household_id != household_id
        or household.created_by != actor_id
    ):
        return None

    from app.projection import build_relationship_graph, get_timeline
    from app.rules import run_rules

    events = get_timeline(session, member_id)
    facts = build_relationship_graph(events)
    alerts = run_rules(facts)

    def joined(items: list[dict], key: str = "name") -> str:
        values = [str(item.get(key)) for item in items if item.get(key)]
        return "、".join(dict.fromkeys(values)) if values else "无记录"

    lines = [
        f"【本地已确认事实 · 成员：{member.display_name}】",
        f"在用药品：{joined(facts['drugs'])}",
        f"过敏史：{joined(facts['allergies'])}",
        f"疾病记录：{joined(facts['diseases'])}",
    ]
    plan_texts = [
        f"{plan.get('drug')}（{plan.get('schedule') or '未定时间'}）"
        for plan in facts["plans"]
        if plan.get("drug")
    ]
    lines.append("用药计划：" + ("；".join(plan_texts) if plan_texts else "无记录"))
    if alerts:
        lines.append("活跃风险提醒：")
        lines.extend(
            f"- [{alert.level}] {alert.message}（规则 {alert.rule_id}）" for alert in alerts[:6]
        )
    else:
        lines.append("活跃风险提醒：当前无触发规则")
    recent = events[-5:]
    if recent:
        lines.append("最近已确认事件：")
        for event in recent:
            summary = _summarize_event_payload(event.payload)
            stamp = event.created_at.strftime("%m-%d") if event.created_at else ""
            lines.append(f"- {stamp} {event.event_type} {summary}".rstrip())
    lines.append(
        "以上为该成员当前授权范围内的本地事实，回答家庭照护问题时请以此为依据，"
        "在 sources 中引用相关的规则编号或事件类型；事实之外的内容请说明无法判断。"
    )
    return "\n".join(lines)


def _prepare_assistant_messages(
    session: Session,
    *,
    payload: AssistantRequest,
    actor_id: str,
    household_id: str | None,
    member_id: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    messages = list(payload.messages)
    context = _build_assistant_context(session, actor_id, household_id, member_id)
    if context:
        messages = [{"role": "system", "content": context}, *messages]
    member_display_name = None
    if context and member_id:
        member = session.get(Member, member_id)
        member_display_name = member.display_name if member else None
    return messages, member_display_name


@router.post("/assistant/chat", response_model=AssistantResponse)
def assistant_chat(
    payload: AssistantRequest,
    actor_id: str = Depends(get_actor_id),
    household_id: str | None = None,
    member_id: str | None = None,
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> AssistantResponse:
    """Run the local health assistant with Ollama tool calling.

    Grounds the conversation in the selected member's confirmed facts, then
    falls back to a structured degrade response if the model is unavailable,
    output fails schema validation, or medical boundary checks are triggered.
    """
    messages, member_display_name = _prepare_assistant_messages(
        session,
        payload=payload,
        actor_id=actor_id,
        household_id=household_id,
        member_id=member_id,
    )
    if payload.agent_mode == "multi_agent" and settings.agent_orchestration_enabled:
        result = run_local_multi_agent(
            session,
            messages=messages,
            actor_id=actor_id,
            household_id=household_id,
            member_id=member_id,
            access_purpose=access_purpose,
            model=payload.model,
            max_tokens=payload.max_tokens,
            temperature=payload.temperature,
            allow_network_search=payload.allow_network_search,
            sensitive_values=[member_display_name],
        )
    else:
        result = run_assistant(
            session,
            messages=messages,
            actor_id=actor_id,
            household_id=household_id,
            member_id=member_id,
            access_purpose=access_purpose,
            model=payload.model,
            max_tokens=payload.max_tokens,
            temperature=payload.temperature,
        )
        result.update(
            {
                "orchestration_mode": "single",
                "all_agents_local": True,
            }
        )
    session.commit()
    return AssistantResponse(**result)


@router.post("/assistant/chat/stream")
def assistant_chat_stream(
    payload: AssistantRequest,
    actor_id: str = Depends(get_actor_id),
    household_id: str | None = None,
    member_id: str | None = None,
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> StreamingResponse:
    """Stream multi-agent orchestration events over Server-Sent Events."""
    if payload.agent_mode != "multi_agent" or not settings.agent_orchestration_enabled:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="STREAM_REQUIRES_MULTI_AGENT",
        )

    messages, member_display_name = _prepare_assistant_messages(
        session,
        payload=payload,
        actor_id=actor_id,
        household_id=household_id,
        member_id=member_id,
    )
    event_queue: Queue[tuple[str, dict[str, Any]] | None] = Queue()
    cancel_event = Event()

    def worker() -> None:
        worker_session = SessionLocal()
        try:
            def on_trace(trace: dict[str, Any]) -> None:
                event_queue.put(("trace", {"trace": trace}))

            def on_token(token: str) -> None:
                event_queue.put(("token", {"token": token}))

            def on_status(phase: str) -> None:
                event_queue.put(("status", {"phase": phase}))

            def on_external_sources(
                sources: list[dict[str, str]],
                network_query: str | None,
            ) -> None:
                event_queue.put(("external_sources", {
                    "external_sources": sources,
                    "network_query": network_query,
                }))

            result = run_local_multi_agent(
                worker_session,
                messages=messages,
                actor_id=actor_id,
                household_id=household_id,
                member_id=member_id,
                access_purpose=access_purpose,
                model=payload.model,
                max_tokens=payload.max_tokens,
                temperature=payload.temperature,
                allow_network_search=payload.allow_network_search,
                sensitive_values=[member_display_name],
                on_trace=on_trace,
                on_synthesis_token=on_token,
                on_status=on_status,
                on_external_sources=on_external_sources,
                cancel_event=cancel_event,
            )
            if cancel_event.is_set():
                worker_session.rollback()
                event_queue.put(("error", {"message": "CANCELLED", "code": "CANCELLED"}))
            else:
                worker_session.commit()
                event_queue.put(("done", {"response": result}))
        except OrchestrationCancelled:
            worker_session.rollback()
            event_queue.put(("error", {"message": "CANCELLED", "code": "CANCELLED"}))
        except Exception as exc:
            worker_session.rollback()
            logger.exception("assistant chat stream failed")
            event_queue.put(("error", {"message": str(exc)[:240]}))
        finally:
            worker_session.close()
            event_queue.put(None)

    Thread(target=worker, daemon=True).start()

    def generate():
        try:
            while True:
                item = event_queue.get()
                if item is None:
                    break
                kind, data = item
                payload = json.dumps(data, ensure_ascii=False, default=str)
                yield f"event: {kind}\ndata: {payload}\n\n"
        finally:
            # Client disconnect or generator close: stop Ollama and workers.
            cancel_event.set()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── HCT-204: Vision task API ─────────────────────────────────────────


@router.post("/vision-quality/check", response_model=VisionQualityRead)
async def check_vision_quality(
    file: UploadFile = File(...),
    media_type: str = Form(default="image"),
    sample_interval_ms: int = Form(default=1000, ge=250, le=10_000),
    max_selected_frames: int = Form(default=30, ge=1, le=120),
    actor_id: str = Depends(get_actor_id),
) -> dict:
    """Check caller-supplied bytes locally; do not read another actor's stored file."""
    from ai.vision.quality_gate import assess_image, assess_video_file, decode_image
    from ai.vision.quality_receipt import issue_quality_receipt

    if media_type not in {"image", "video"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="MEDIA_TYPE_INVALID",
        )
    filename = validate_filename(file.filename or "unknown")
    extension = validate_extension(filename)
    allowed_for_media = {
        "image": {".jpg", ".jpeg", ".png"},
        "video": {".mp4", ".mov"},
    }
    if extension not in allowed_for_media[media_type]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="MEDIA_EXTENSION_MISMATCH",
        )
    allowed_content_types = {
        ".jpg": {"image/jpeg"},
        ".jpeg": {"image/jpeg"},
        ".png": {"image/png"},
        ".mp4": {"video/mp4"},
        ".mov": {"video/quicktime", "video/x-quicktime"},
    }
    if file.content_type not in allowed_content_types[extension]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="MEDIA_CONTENT_TYPE_MISMATCH",
        )
    validate_magic(file.file, extension)
    validate_size(file.file)
    input_digest = compute_hash(file.file)
    source_id = f"upload:{input_digest[:16]}"

    try:
        thresholds = settings.vision_quality_thresholds()
        if media_type == "video":
            temporary_path: Path | None = None
            try:
                file.file.seek(0)
                with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as temporary:
                    temporary.write(file.file.read())
                    temporary_path = Path(temporary.name)
                result = assess_video_file(
                    temporary_path,
                    source_id=source_id,
                    sample_interval_ms=sample_interval_ms,
                    max_selected_frames=max_selected_frames,
                    thresholds=thresholds,
                    max_duration_ms=settings.vision_video_max_duration_seconds * 1000,
                )
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
        else:
            file.file.seek(0)
            result = assess_image(
                decode_image(file.file.read()),
                source_id=source_id,
                thresholds=thresholds,
            )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    if not settings.vision_quality_enforce_retake:
        # Local demo mode: preserve all quality metrics and diagnostics, but
        # do not block a valid, decodable upload from reaching OCR.  This is
        # deliberately a policy switch in the API layer so the strict gate
        # remains available for regression tests and production deployment.
        result["decision"] = "PASS"
        result["allow_downstream"] = True
        result.setdefault("limitations", []).append(
            "quality enforcement disabled: metrics are advisory for local OCR demo"
        )

    result["source"]["sha256"] = input_digest
    result["source"]["digest_scope"] = "uploaded_file_bytes"
    result["quality_receipt"] = (
        issue_quality_receipt(
            actor_id=actor_id,
            input_digest=input_digest,
            config_version=result["config_version"],
            media_type=media_type,
        )
        if result["allow_downstream"]
        else None
    )

    logger.info(
        "VISION_QUALITY_CHECK actor=%s source=%s media=%s decision=%s reasons=%d",
        actor_id,
        source_id,
        media_type,
        result["decision"],
        len(result["reasons"]),
    )
    return result


def _require_vision_task_access(
    session: Session,
    task_id: str,
    *,
    actor_id: str,
    action: str,
    access_purpose: str | None,
) -> VisionTask:
    task = get_vision_task(session, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="VISION_TASK_NOT_FOUND",
        )
    if not task.member_id:
        if task.created_by != actor_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="VISION_TASK_NOT_FOUND",
            )
        return task
    member = session.get(Member, task.member_id)
    household = session.get(Household, task.household_id)
    allowed = False
    if member is not None and household is not None:
        allowed = has_member_read_access(
            session, household, member.id, actor_id, access_purpose
        ) if action == "READ_EVENTS" else has_vision_capture_access(
            session, household, member.id, actor_id, access_purpose
        )
    if (
        member is None
        or household is None
        or _is_erased(household, member)
        or not allowed
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="VISION_TASK_NOT_FOUND",
        )
    return task


@router.post(
    "/vision-tasks",
    response_model=VisionTaskRead,
    status_code=status.HTTP_201_CREATED,
)
def create_vision_task_endpoint(
    payload: VisionTaskCreate,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> VisionTask:
    """Create a new vision processing task.

    The *file_id* must already exist in the secure file store (uploaded via
    /files/upload).  The task is queued asynchronously and a worker picks it
    up later.  Use the idempotency key to avoid duplicate tasks on retry.
    """
    household_id = "system"
    if payload.member_id:
        member = session.get(Member, payload.member_id)
        household = session.get(Household, member.household_id) if member is not None else None
        if (
            member is None
            or household is None
            or _is_erased(household, member)
            or not has_vision_capture_access(
                session, household, member.id, actor_id, access_purpose
            )
        ):
            _raise_resource_not_found()
        household_id = household.id

    file_root = Path(settings.file_root).resolve()
    target = (file_root / payload.file_id).resolve()

    # Security: only allow files inside the upload root
    if not target.is_relative_to(file_root) or not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="FILE_NOT_FOUND",
        )

    extension = target.suffix.lower()
    media_type_by_extension = {
        ".jpg": "image",
        ".jpeg": "image",
        ".png": "image",
        ".mp4": "video",
        ".mov": "video",
    }
    actual_media_type = media_type_by_extension.get(extension)
    if actual_media_type not in VISION_MEDIA_TYPES or actual_media_type != payload.media_type:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="MEDIA_TYPE_MISMATCH",
        )

    # Compute input digest for integrity tracking.
    try:
        input_digest = _file_digest(str(target))
    except Exception:
        input_digest = None

    if input_digest is None or payload.quality_receipt is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="QUALITY_GATE_REQUIRED",
        )
    from ai.vision.quality_receipt import verify_quality_receipt

    try:
        verify_quality_receipt(
            payload.quality_receipt,
            actor_id=actor_id,
            input_digest=input_digest,
            config_version=settings.vision_quality_config_version,
            media_type=payload.media_type,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    task = create_vision_task(
        session,
        household_id=household_id,
        created_by=actor_id,
        file_id=payload.file_id,
        media_type=payload.media_type,
        member_id=payload.member_id,
        task_type=payload.task_type,
        idempotency_key=payload.idempotency_key,
        model_threshold=payload.model_threshold,
        input_digest=input_digest,
        preprocess_version=settings.vision_quality_config_version,
        schema_version="vision-result-v1",
        code_version="hct-204-v1",
        data_version="hct-201-dataset-v1",
    )
    session.commit()
    session.refresh(task)
    logger.info("VISION_TASK_ENQUEUED task=%s actor=%s", task.id, actor_id)
    return task


_FUSION_TO_REVIEW_STATUS: dict[VisionFusionStatus, ReviewFusionStatus] = {
    VisionFusionStatus.MATCHED: ReviewFusionStatus.MATCHED,
    VisionFusionStatus.CONFLICT: ReviewFusionStatus.CONFLICT,
    VisionFusionStatus.UNKNOWN: ReviewFusionStatus.UNKNOWN,
    VisionFusionStatus.REVIEW: ReviewFusionStatus.LOW_QUALITY,
}

_FUSION_CHANNEL_LABELS = {
    "ocr": "OCR 文本",
    "barcode": "条码",
    "packaging": "包装特征",
    "metadata": "规格/厂家",
}


def _review_candidate_metadata(
    master_data: LocalMasterData,
    record_id: str | None,
) -> dict[str, Any]:
    """Copy only approved, non-OCR medicine metadata into the review card."""
    if not record_id:
        return {}
    record = next((item for item in master_data.records if item.record_id == record_id), None)
    if record is None:
        return {}

    interaction_warnings: list[dict[str, str]] = []
    for interaction in master_data.interactions:
        if record_id not in interaction.record_ids:
            continue
        other_ids = [item for item in interaction.record_ids if item != record_id]
        if not other_ids:
            continue
        interaction_warnings.append(
            {
                "with_record_id": other_ids[0],
                "level": interaction.level,
                "message": interaction.message,
            }
        )

    return {
        "specification": record.specification,
        "manufacturer": record.manufacturer,
        "active_ingredients": list(record.active_ingredients),
        "indications": list(record.indications),
        "cautions": list(record.cautions),
        "contraindications": list(record.contraindications),
        "interaction_warnings": interaction_warnings,
        "master_data_version": master_data.version,
    }


def _ensure_review_task_for_vision(
    session: Session,
    *,
    task: VisionTask,
    result: EvidencePipelineResult,
    master_data: LocalMasterData,
) -> ReviewTask | None:
    """HCT-206 → HCT-207 bridge: turn fusion output into a review task.

    Every four-state outcome (including MATCHED) must pass human review
    before any health fact exists; without this bridge the vision loop
    stopped at fusion and nothing ever reached the review center.
    Idempotent: at most one review task per vision task.
    """
    if not task.member_id:
        return None
    member = session.get(Member, task.member_id)
    if member is None:
        return None
    existing = get_review_task_by_vision_task(session, task.id)
    if existing is not None:
        return existing

    fusion = fuse_evidence(result, master_data)
    names_by_record = {
        record.record_id: (record.name_aliases[0] if record.name_aliases else record.record_id)
        for record in master_data.records
    }
    specs_by_record = {record.record_id: record.specification for record in master_data.records}

    candidates: list[dict] = []
    for fused in fusion.candidates:
        evidence_notes: list[str] = []
        for channel, label in _FUSION_CHANNEL_LABELS.items():
            channel_evidence = fused.channel_evidence.get(channel)
            if channel_evidence is None or channel_evidence.missing:
                continue
            if channel_evidence.support:
                evidence_notes.append(f"{label}一致（{channel_evidence.score:.2f}）")
            if channel_evidence.conflict:
                evidence_notes.append(f"{label}冲突")
        candidates.append(
            {
                "drug_name": names_by_record.get(fused.candidate_id, fused.candidate_id),
                "confidence": fused.score,
                "evidence": evidence_notes,
                "dosage": specs_by_record.get(fused.candidate_id),
                "frequency": None,
                "candidate_id": fused.candidate_id,
                "rank": fused.rank,
                "conflicts": fused.conflicts,
                **_review_candidate_metadata(master_data, fused.candidate_id),
            }
        )

    if not candidates:
        # Master data had no match. Surface the raw OCR field extraction so
        # the reviewer still sees what the engines read and can correct or
        # skip with context instead of facing an empty task.
        spec_value = next(
            (
                field.normalized_value
                for field in result.fields
                if field.field_name == "specification"
            ),
            None,
        )
        for index, field in enumerate(
            field for field in result.fields if field.field_name == "drug_name"
        ):
            candidates.append(
                {
                    "drug_name": field.normalized_value,
                    "confidence": field.confidence,
                    "evidence": ["OCR 提取，主数据未收录，需人工核对"],
                    "dosage": spec_value,
                    "frequency": None,
                    "candidate_id": None,
                    "rank": index + 1,
                    "conflicts": [],
                    "active_ingredients": [],
                    "indications": [],
                    "cautions": [],
                    "contraindications": [],
                    "interaction_warnings": [],
                    "master_data_version": master_data.version,
                }
            )

    review = create_review_task(
        session,
        vision_task_id=task.id,
        household_id=member.household_id,
        member_id=member.id,
        candidates=candidates,
        fusion_status=_FUSION_TO_REVIEW_STATUS[fusion.status],
        model_version=result.versions.get("vision_model_version") or task.model_version,
        rule_version=fusion.versions.get("fusion_rule_version", "fusion-rules-v1"),
    )
    logger.info(
        "REVIEW_TASK_BRIDGED vision_task=%s review_task=%s status=%s candidates=%d",
        task.id,
        review.id,
        fusion.status,
        len(candidates),
    )
    return review


@router.post(
    "/vision-tasks/{task_id}/evidence",
    response_model=EvidencePipelineResult,
)
def submit_vision_evidence_endpoint(
    task_id: str,
    payload: EvidencePipelineRequest,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> EvidencePipelineResult:
    """Store OCR-first adapter evidence and produce a safe fusion input.

    This endpoint accepts outputs from local OCR/barcode/YOLO adapters.  It
    never confirms an identity or creates a health event; HCT-206 performs
    candidate fusion and HCT-207 performs human confirmation.
    """
    task = _require_vision_task_access(
        session,
        task_id,
        actor_id=actor_id,
        action="WRITE_EVENTS",
        access_purpose=access_purpose,
    )
    # HCT-441: once a worker has claimed the task, only that worker may
    # publish evidence while its lease is still live.  Unclaimed queued
    # tasks remain compatible with older local adapters.
    assert_vision_task_lease(task, actor_id)
    if task.status in {
        VisionTaskStatus.SUCCEEDED,
        VisionTaskStatus.FAILED,
        VisionTaskStatus.TIMEOUT,
        VisionTaskStatus.CANCELLED,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"VISION_TASK_ALREADY_{task.status.upper()}",
        )

    if payload.adapter_id not in settings.vision_adapter_allowlist_set:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ADAPTER_NOT_ALLOWED",
        )
    if payload.adapter_receipt is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ADAPTER_RECEIPT_REQUIRED",
        )
    if not verify_adapter_receipt(
        task.id,
        task.input_digest or "",
        payload,
        settings.vision_adapter_signing_key,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ADAPTER_RECEIPT_INVALID",
        )

    if task.status == VisionTaskStatus.QUEUED:
        transition_status(session, task, VisionTaskStatus.RUNNING)
    master_data = load_master_data_snapshot(
        payload.master_data_version,
        root=Path(settings.master_data_root),
        approved_versions=settings.master_data_approved_version_set,
    )
    result = process_evidence(
        payload,
        master_data=master_data,
        source_sha256=task.input_digest,
    )
    updated = transition_status(
        session,
        task,
        VisionTaskStatus.SUCCEEDED,
        result=result.model_dump(mode="json"),
        model_version=payload.vision_model_version,
        preprocess_version=task.preprocess_version,
        schema_version=result.schema_version,
        code_version=payload.code_version,
        data_version=payload.master_data_version,
    )
    _ensure_review_task_for_vision(
        session,
        task=updated,
        result=result,
        master_data=master_data,
    )
    session.commit()
    session.refresh(updated)
    logger.info(
        "VISION_EVIDENCE_STORED task=%s actor=%s readiness=%s findings=%d",
        task.id,
        actor_id,
        result.fusion_readiness,
        len(result.findings),
    )
    return result


@router.post(
    "/vision-tasks/{task_id}/fusion",
    response_model=VisionFusionRead,
)
def fuse_vision_task_endpoint(
    task_id: str,
    payload: FusionRequest,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> VisionFusionRead:
    """Rank local candidates and persist the single pending review task.

    Fusion consumes completed OCR-first evidence and an approved local
    master-data snapshot.  It never confirms or writes a health fact; only a
    human review task is created, idempotently, for the member-scoped task.
    """
    task = _require_vision_task_access(
        session,
        task_id,
        actor_id=actor_id,
        action="WRITE_EVENTS",
        access_purpose=access_purpose,
    )
    task = _require_vision_task_access(
        session,
        task_id,
        actor_id=actor_id,
        action="READ_EVENTS",
        access_purpose=access_purpose,
    )
    if task.status != VisionTaskStatus.SUCCEEDED or not task.result:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="VISION_EVIDENCE_REQUIRED")
    try:
        evidence = EvidencePipelineResult.model_validate(task.result)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="VISION_EVIDENCE_INVALID",
        ) from exc
    master_version = evidence.versions.get("master_data_version", "unavailable")
    master_data = load_master_data_snapshot(
        master_version,
        root=Path(settings.master_data_root),
        approved_versions=settings.master_data_approved_version_set,
    )
    result = fuse_evidence(evidence, master_data, thresholds=payload.thresholds())
    if task.member_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="VISION_MEMBER_REQUIRED",
        )
    records = {record.record_id: record for record in master_data.records}
    review_candidates: list[dict] = []
    for candidate in result.candidates:
        review_candidate = candidate.model_dump(mode="json")
        record = records.get(candidate.candidate_id)
        if record is not None:
            review_candidate.update(
                {
                    "drug_name": (
                        record.name_aliases[0] if record.name_aliases else record.record_id
                    ),
                    "confidence": candidate.score,
                    "product_barcode": record.product_barcode,
                    "specification": record.specification,
                    "manufacturer": record.manufacturer,
                    "packaging_type": record.packaging_type,
                    **_review_candidate_metadata(master_data, record.record_id),
                }
            )
        review_candidates.append(review_candidate)
    review_task = create_review_task(
        session,
        vision_task_id=task.id,
        household_id=task.household_id,
        member_id=task.member_id,
        candidates=review_candidates,
        fusion_status=ReviewFusionStatus(result.status.value),
        model_version=task.model_version,
        rule_version=result.versions.get("fusion_rule_version"),
        fusion_context={
            "thresholds": result.thresholds.model_dump(mode="json"),
            "weights": result.weights.model_dump(mode="json"),
            "versions": result.versions,
        },
    )
    session.commit()
    session.refresh(review_task)
    logger.info(
        "VISION_FUSION_REVIEW_READY task=%s review=%s actor=%s status=%s candidates=%d",
        task.id,
        review_task.id,
        actor_id,
        result.status,
        len(result.candidates),
    )
    return VisionFusionRead(
        **result.model_dump(mode="json"),
        review_task_id=review_task.id,
        review_task_version=review_task.version,
    )


@router.get("/vision-tasks", response_model=list[VisionTaskRead])
def list_my_vision_tasks_endpoint(
    task_status: str | None = None,
    limit: int = 20,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> list[VisionTask]:
    """List the caller's own vision tasks (adapter worker poll endpoint).

    Actor-scoped: only tasks created by the requesting identity are returned,
    so a family-trusted-domain worker can pick up its queued jobs without a
    household-owner lookup (web tasks are stored under the synthetic
    "system" household).
    """
    if task_status is not None and task_status not in {s.value for s in VisionTaskStatus}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"INVALID_STATUS: {task_status}",
        )
    stmt = (
        select(VisionTask)
        .where(VisionTask.created_by == actor_id)
        .order_by(VisionTask.created_at.asc())
        .limit(max(1, min(limit, 100)))
    )
    if task_status is not None:
        stmt = stmt.where(VisionTask.status == task_status)
    return list(session.scalars(stmt).all())


@router.post("/vision-tasks/claim", response_model=list[VisionTaskRead])
def claim_vision_tasks_endpoint(
    payload: VisionTaskClaimRequest,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> list[VisionTask]:
    """Atomically claim this worker's queued tasks with expiring leases.

    The actor header is both the task creator scope and the worker identity;
    no worker can claim another actor's jobs.  Expired leases are recovered
    before the next batch is selected, and exhausted jobs become ``timeout``.
    """
    tasks = claim_vision_tasks(
        session,
        actor_id=actor_id,
        limit=min(payload.limit, settings.vision_worker_claim_batch_size),
        lease_seconds=payload.lease_seconds or settings.vision_worker_lease_seconds,
        max_attempts=settings.vision_worker_max_attempts,
    )
    session.commit()
    return tasks


@router.get("/vision-tasks/{task_id}", response_model=VisionTaskRead)
def get_vision_task_endpoint(
    task_id: str,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> VisionTask:
    return _require_vision_task_access(
        session,
        task_id,
        actor_id=actor_id,
        action="READ_EVENTS",
        access_purpose=access_purpose,
    )


@router.post("/vision-tasks/{task_id}/lease", response_model=VisionTaskRead)
def renew_vision_task_lease_endpoint(
    task_id: str,
    payload: VisionTaskLeaseRequest,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> VisionTask:
    """Renew a live worker lease immediately before publishing evidence."""
    task = _require_vision_task_access(
        session,
        task_id,
        actor_id=actor_id,
        action="WRITE_EVENTS",
        access_purpose=access_purpose,
    )
    if task.created_by != actor_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VISION_TASK_NOT_FOUND")
    renewed = renew_vision_task_lease(
        session,
        task,
        worker_id=actor_id,
        lease_seconds=payload.lease_seconds or settings.vision_worker_lease_seconds,
    )
    session.commit()
    return renewed


@router.get("/households/{household_id}/vision-tasks", response_model=list[VisionTaskRead])
def list_vision_tasks_endpoint(
    household_id: str,
    member_id: str | None = None,
    task_status: str | None = Query(default=None, alias="status"),
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> list[VisionTask]:
    household = session.get(Household, household_id)
    if _is_erased(household):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HOUSEHOLD_NOT_FOUND")
    if member_id is None:
        if household.created_by != actor_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="HOUSEHOLD_NOT_FOUND",
            )
    else:
        member = session.get(Member, member_id)
        if (
            member is None
            or member.household_id != household.id
            or not has_member_read_access(
                session, household, member.id, actor_id, access_purpose
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="HOUSEHOLD_NOT_FOUND",
            )

    if task_status is not None and task_status not in {s.value for s in VisionTaskStatus}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"INVALID_STATUS: {task_status}",
        )

    return list_vision_tasks(
        session,
        household_id,
        member_id=member_id,
        status=task_status,
    )


@router.post(
    "/households/{household_id}/vision-tasks/retention-cleanup",
    response_model=VisionTaskCleanupRead,
)
def cleanup_vision_task_files_endpoint(
    household_id: str,
    payload: VisionTaskCleanupRequest,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> VisionTaskCleanupRead:
    """Preview or remove expired video files while retaining task metadata.

    This is an owner-only control-plane operation.  The default dry-run and
    server-side batch cap make it safe to wire to a periodic operator job.
    """
    require_household_owner(session, household_id, actor_id)
    report = cleanup_expired_video_files(
        session,
        household_id,
        retention_seconds=settings.vision_video_retention_seconds,
        limit=min(payload.limit, settings.vision_video_cleanup_batch_size),
        dry_run=payload.dry_run,
    )
    session.add(
        AccessAudit(
            household_id=household_id,
            actor_id=actor_id,
            operation="READ" if payload.dry_run else "DELETE",
            action="VISION_RETENTION_PREVIEW" if payload.dry_run else "VISION_RETENTION_CLEANUP",
            data_field="vision_task.video_files",
            purpose="retention",
            outcome="ALLOWED",
            reason="DRY_RUN" if payload.dry_run else "RETENTION_POLICY",
            request_id=current_request_id(),
        )
    )
    session.commit()
    return VisionTaskCleanupRead(**report.__dict__)


@router.post("/vision-tasks/{task_id}/cancel", response_model=VisionTaskRead)
def cancel_vision_task_endpoint(
    task_id: str,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> VisionTask:
    """Cancel a queued or running vision task."""
    task = _require_vision_task_access(
        session,
        task_id,
        actor_id=actor_id,
        action="WRITE_EVENTS",
        access_purpose=access_purpose,
    )

    if task.status in (
        VisionTaskStatus.SUCCEEDED,
        VisionTaskStatus.FAILED,
        VisionTaskStatus.TIMEOUT,
        VisionTaskStatus.CANCELLED,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"VISION_TASK_ALREADY_{task.status.upper()}",
        )

    updated = transition_status(
        session,
        task,
        VisionTaskStatus.CANCELLED,
        error_code="CANCELLED_BY_USER",
        error_message=f"Cancelled by {actor_id}",
    )
    session.commit()
    session.refresh(updated)
    return updated


@router.post("/vision-tasks/{task_id}/retry", response_model=VisionTaskRead)
def retry_vision_task_endpoint(
    task_id: str,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> VisionTask:
    """Requeue one failed/timeout task in place.

    The original file, member scope and task ID are retained.  This prevents
    a retry button from creating a second candidate or a second health fact.
    """
    task = _require_vision_task_access(
        session,
        task_id,
        actor_id=actor_id,
        action="WRITE_EVENTS",
        access_purpose=access_purpose,
    )
    updated = retry_vision_task(session, task)
    session.commit()
    session.refresh(updated)
    return updated


# ── HCT-207: Manual review API ────────────────────────────────────────


def _require_review_access(
    session: Session,
    task: ReviewTask,
    *,
    household_id: str,
    actor_id: str,
    action: str,
    access_purpose: str | None,
) -> Household:
    household = session.get(Household, household_id)
    member = session.get(Member, task.member_id)
    if (
        household is None
        or member is None
        or _is_erased(household, member)
        or task.household_id != household.id
        or not has_authorized_action(
            session,
            household,
            member.id,
            actor_id,
            action,
            "health_events",
            access_purpose,
        )
    ):
        _raise_resource_not_found()
    return household


def _commit_review_event(
    session: Session,
    *,
    household: Household,
    member_id: str,
    actor_id: str,
    idempotency_key: str | None,
    correlation_id: str,
    event_dict: dict,
) -> None:
    member = session.get(Member, member_id)
    if member is None or member.household_id != household.id:
        _raise_resource_not_found()
    try:
        append_health_event_transaction(
            session,
            household=household,
            member=member,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            payload=HealthEventCreate(
                member_id=member.id,
                event_type=event_dict["event_type"],
                source="MANUAL",
                confirmation_status="CONFIRMED",
                payload=event_dict["payload"],
                evidence={
                    **event_dict["evidence"],
                    "event_source": event_dict["source"],
                },
            ),
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="IDEMPOTENCY_KEY_CONFLICT",
        ) from exc


@router.get(
    "/households/{household_id}/members/{member_id}/review-tasks",
    response_model=list[ReviewTaskRead],
)
def list_review_tasks(
    household_id: str,
    member_id: str,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> list[ReviewTask]:
    household = session.get(Household, household_id)
    member = session.get(Member, member_id)
    if _is_erased(household, member):
        _raise_resource_not_found()
    if not has_authorized_action(
        session,
        household,
        member_id,
        actor_id,
        "READ_EVENTS",
        "health_events",
        access_purpose,
    ):
        _raise_resource_not_found()
    # 返回全部状态（待复核 + 已处理），前端负责分组展示处理记录。
    return list_review_tasks_query(session, household_id, member_id)


@router.get(
    "/households/{household_id}/review-tasks/{task_id}",
    response_model=ReviewTaskRead,
)
def get_review_task_endpoint(
    household_id: str,
    task_id: str,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> ReviewTask:
    task = get_review_task(session, task_id)
    if task is None or task.household_id != household_id:
        _raise_resource_not_found()
    _require_review_access(
        session,
        task,
        household_id=household_id,
        actor_id=actor_id,
        action="READ_EVENTS",
        access_purpose=access_purpose,
    )
    return task


@router.post(
    "/households/{household_id}/review-tasks/{task_id}/confirm",
    response_model=ReviewTaskRead,
    status_code=status.HTTP_200_OK,
)
def confirm_review_endpoint(
    household_id: str,
    task_id: str,
    payload: ReviewTaskConfirm,
    request: Request,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
) -> ReviewTask:
    task = get_review_task(session, task_id)
    if task is None or task.household_id != household_id:
        _raise_resource_not_found()

    household = _require_review_access(
        session,
        task,
        household_id=household_id,
        actor_id=actor_id,
        action="WRITE_EVENTS",
        access_purpose=access_purpose,
    )
    _require_review_access(
        session,
        task,
        household_id=household_id,
        actor_id=actor_id,
        action="READ_EVENTS",
        access_purpose=access_purpose,
    )

    candidates = task.candidates or []
    selected = candidates[0] if payload.selected_index is None and len(candidates) == 1 else None
    if payload.selected_index is not None:
        if payload.selected_index < 0 or payload.selected_index >= len(candidates):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="SELECTED_INDEX_OUT_OF_RANGE",
            )
        selected = candidates[payload.selected_index]
    if selected is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="REVIEW_CANDIDATE_REQUIRED",
        )

    updated_task, event_dict = confirm_review(
        session,
        task,
        actor_id=actor_id,
        selected_candidate=selected,
        confirmation_note=payload.confirmation_note,
        idempotency_key=idempotency_key,
        expected_version=payload.expected_version,
    )

    _commit_review_event(
        session,
        household=household,
        member_id=task.member_id,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        correlation_id=getattr(request.state, "request_id", None) or secrets.token_hex(16),
        event_dict=event_dict,
    )
    session.refresh(updated_task)
    return updated_task


@router.post(
    "/households/{household_id}/review-tasks/{task_id}/correct",
    response_model=ReviewTaskRead,
    status_code=status.HTTP_200_OK,
)
def correct_review_endpoint(
    household_id: str,
    task_id: str,
    payload: ReviewTaskCorrect,
    request: Request,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
) -> ReviewTask:
    task = get_review_task(session, task_id)
    if task is None or task.household_id != household_id:
        _raise_resource_not_found()

    household = _require_review_access(
        session,
        task,
        household_id=household_id,
        actor_id=actor_id,
        action="WRITE_EVENTS",
        access_purpose=access_purpose,
    )
    _require_review_access(
        session,
        task,
        household_id=household_id,
        actor_id=actor_id,
        action="READ_EVENTS",
        access_purpose=access_purpose,
    )

    updated_task, event_dict = correct_review(
        session,
        task,
        actor_id=actor_id,
        manual_payload=payload.manual_payload,
        correction_note=payload.correction_note,
        idempotency_key=idempotency_key,
        expected_version=payload.expected_version,
    )

    _commit_review_event(
        session,
        household=household,
        member_id=task.member_id,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        correlation_id=getattr(request.state, "request_id", None) or secrets.token_hex(16),
        event_dict=event_dict,
    )
    session.refresh(updated_task)
    return updated_task


@router.post(
    "/households/{household_id}/review-tasks/{task_id}/skip",
    response_model=ReviewTaskRead,
)
def skip_review_endpoint(
    household_id: str,
    task_id: str,
    payload: ReviewTaskSkip,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
) -> ReviewTask:
    task = get_review_task(session, task_id)
    if task is None or task.household_id != household_id:
        _raise_resource_not_found()

    _require_review_access(
        session,
        task,
        household_id=household_id,
        actor_id=actor_id,
        action="WRITE_EVENTS",
        access_purpose=access_purpose,
    )
    _require_review_access(
        session,
        task,
        household_id=household_id,
        actor_id=actor_id,
        action="READ_EVENTS",
        access_purpose=access_purpose,
    )

    updated_task = skip_review(
        session,
        task,
        actor_id=actor_id,
        reason=payload.reason,
        idempotency_key=idempotency_key,
        expected_version=payload.expected_version,
    )
    session.commit()
    session.refresh(updated_task)
    return updated_task


# ── HCT-307: Risk evidence API ─────────────────────────────────────


def _risk_alert_read(
    session: Session,
    *,
    household_id: str,
    member_id: str,
    alert: Any,
) -> RiskAlertRead:
    current_version = settings.ruleset_version
    fingerprint = risk_fingerprint(
        rule_id=alert.rule_id,
        level=alert.level,
        source_event_ids=alert.source_event_ids,
        rule_version=current_version,
    )
    acknowledgement = session.scalar(
        select(RiskAcknowledgement).where(
            RiskAcknowledgement.household_id == household_id,
            RiskAcknowledgement.member_id == member_id,
            RiskAcknowledgement.rule_id == alert.rule_id,
            RiskAcknowledgement.risk_fingerprint == fingerprint,
        )
    )
    return RiskAlertRead(
        rule_id=alert.rule_id,
        level=alert.level,
        message=alert.message,
        source_event_ids=alert.source_event_ids,
        rule_version=current_version,
        risk_fingerprint=fingerprint,
        acknowledgement=(acknowledgement_read(acknowledgement) if acknowledgement else None),
    )


def _current_risk_alert(session: Session, member_id: str, rule_id: str) -> Any | None:
    from app.projection import build_relationship_graph, get_timeline
    from app.rules import run_rules

    events = get_timeline(session, member_id)
    facts = build_relationship_graph(events)
    alerts = run_rules(facts, rule_ids=[rule_id])
    return alerts[0] if alerts else None


@router.get(
    "/households/{household_id}/members/{member_id}/risks",
    response_model=RiskListResponse,
)
def list_risks(
    household_id: str,
    member_id: str,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> dict:
    household = session.get(Household, household_id)
    member = session.get(Member, member_id)
    if _is_erased(household, member):
        _raise_resource_not_found()
    if not has_member_read_access(
        session,
        household,
        member_id,
        actor_id,
        access_purpose,
    ):
        _raise_resource_not_found()
    from app.projection import build_relationship_graph, get_timeline
    from app.rules import DEFAULT_DAILY_BUDGET, apply_daily_budget, dedup_alerts, run_rules

    events = get_timeline(session, member_id)
    facts = build_relationship_graph(events)
    raw = run_rules(facts)
    deduped = dedup_alerts(raw)
    budgeted = apply_daily_budget(deduped)

    alerts = [
        _risk_alert_read(
            session,
            household_id=household_id,
            member_id=member_id,
            alert=a,
        )
        for a in budgeted
    ]
    return RiskListResponse(
        member_id=member_id,
        alerts=alerts,
        total=len(alerts),
        severe_count=sum(1 for a in alerts if a.level == "SEVERE"),
        warning_count=sum(1 for a in alerts if a.level == "WARNING"),
        ruleset_version=settings.ruleset_version,
        non_severe_budget=DEFAULT_DAILY_BUDGET,
        suppressed_count=max(len(deduped) - len(budgeted), 0),
    )


@router.get(
    "/households/{household_id}/members/{member_id}/risks/{rule_id}",
    response_model=RiskDetailResponse,
)
def get_risk_detail(
    household_id: str,
    member_id: str,
    rule_id: str,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> dict:
    household = session.get(Household, household_id)
    member = session.get(Member, member_id)
    if _is_erased(household, member):
        _raise_resource_not_found()
    if not has_member_read_access(
        session,
        household,
        member_id,
        actor_id,
        access_purpose,
    ):
        _raise_resource_not_found()
    from app.projection import build_relationship_graph, get_timeline
    from app.rules import run_rules

    events = get_timeline(session, member_id)
    facts = build_relationship_graph(events)
    alerts = run_rules(facts, rule_ids=[rule_id])
    if not alerts:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RISK_NOT_FOUND")

    alert = alerts[0]
    sources: list[dict] = []
    for eid in alert.source_event_ids:
        evt = session.get(HealthEvent, eid)
        if evt is not None:
            sources.append(
                {
                    "id": evt.id,
                    "event_type": evt.event_type,
                    "confirmation_status": evt.confirmation_status,
                    "created_at": evt.created_at.isoformat() if evt.created_at else None,
                }
            )
    return RiskDetailResponse(
        alert=_risk_alert_read(
            session,
            household_id=household_id,
            member_id=member_id,
            alert=alert,
        ),
        source_events=sources,
    )


@router.post(
    "/households/{household_id}/members/{member_id}/risks/{rule_id}/acknowledge",
    response_model=RiskAcknowledgementRead,
)
def acknowledge_risk(
    household_id: str,
    member_id: str,
    rule_id: str,
    payload: RiskAcknowledgementCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> RiskAcknowledgementRead:
    """Write a minimal receipt only for the currently computed risk signal."""

    if not idempotency_key or len(idempotency_key) > 128:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="IDEMPOTENCY_KEY_REQUIRED",
        )

    household = session.get(Household, household_id)
    member = session.get(Member, member_id)
    if _is_erased(household, member):
        _raise_resource_not_found()
    if not has_authorized_action(
        session,
        household,
        member_id,
        actor_id,
        "ACK_RISK",
        "risk_alerts",
        access_purpose,
    ):
        _raise_resource_not_found()

    alert = _current_risk_alert(session, member_id, rule_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RISK_NOT_FOUND")

    current_version = settings.ruleset_version
    current_fingerprint = risk_fingerprint(
        rule_id=alert.rule_id,
        level=alert.level,
        source_event_ids=alert.source_event_ids,
        rule_version=current_version,
    )
    request_hash = request_fingerprint(
        household_id=household_id,
        member_id=member_id,
        rule_id=rule_id,
        rule_version=payload.rule_version,
        risk_fingerprint_value=payload.risk_fingerprint,
        actor_id=actor_id,
    )
    existing = session.scalar(
        select(RiskAcknowledgement).where(
            RiskAcknowledgement.household_id == household_id,
            RiskAcknowledgement.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_fingerprint != request_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="IDEMPOTENCY_KEY_CONFLICT",
            )
        return acknowledgement_read(existing, replayed=True)

    if payload.rule_version != current_version or payload.risk_fingerprint != current_fingerprint:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="RISK_VERSION_CONFLICT",
        )

    existing_signal = session.scalar(
        select(RiskAcknowledgement).where(
            RiskAcknowledgement.household_id == household_id,
            RiskAcknowledgement.member_id == member_id,
            RiskAcknowledgement.rule_id == rule_id,
            RiskAcknowledgement.risk_fingerprint == current_fingerprint,
        )
    )
    if existing_signal is not None:
        return acknowledgement_read(existing_signal, replayed=True)

    acknowledgement = RiskAcknowledgement(
        household_id=household_id,
        member_id=member_id,
        rule_id=rule_id,
        rule_version=current_version,
        risk_fingerprint=current_fingerprint,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        request_fingerprint=request_hash,
    )
    session.add(acknowledgement)
    session.add(
        AccessAudit(
            household_id=household_id,
            authorization_id=None,
            actor_id=actor_id,
            operation="RISK_ACK",
            action="ACK_RISK",
            data_field="risk_alerts",
            purpose=access_purpose,
            outcome="ALLOWED",
            reason=None,
            request_id=getattr(request.state, "request_id", None),
        )
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raced = session.scalar(
            select(RiskAcknowledgement).where(
                RiskAcknowledgement.household_id == household_id,
                RiskAcknowledgement.risk_fingerprint == current_fingerprint,
                RiskAcknowledgement.rule_id == rule_id,
                RiskAcknowledgement.member_id == member_id,
            )
        )
        if raced is not None:
            return acknowledgement_read(raced, replayed=True)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="IDEMPOTENCY_KEY_CONFLICT",
        ) from None
    session.refresh(acknowledgement)
    return acknowledgement_read(acknowledgement)


# ── HCT-208: Correction diff, hard sample, training consent & export ───


from app import hard_sample as _hs  # noqa: E402


def _hs_household(session: Session, household_id: str, actor_id: str) -> Household:
    return require_household_owner(session, household_id, actor_id)


def _hs_raise_val(err: str) -> NoReturn:
    mapping: dict[str, int] = {
        "SOURCE_EVENT_NOT_FOUND": 404,
        "SAMPLE_NOT_FOUND": 404,
        "NO_ACTIVE_CONSENT": 404,
        "SAMPLE_NOT_PENDING": 409,
        "SAMPLE_NOT_APPROVED": 422,
        "SAMPLE_DELETED": 422,
        "SAMPLE_ALREADY_DELETED": 409,
        "INVALID_STATUS_TRANSITION": 422,
        "VERSION_ALREADY_EXISTS": 409,
        "NO_SAMPLES_PROVIDED": 422,
        "MANIFEST_NOT_ACTIVE": 409,
        "INVALID_CATEGORY": 422,
        "TRAINING_CONSENT_REQUIRED": 422,
        "HARD_SAMPLE_NOT_FOUND": 404,
        "TRAINING_CONSENT_GRANT_REQUIRED": 422,
    }
    status_code_val = 422
    for prefix, code in mapping.items():
        if err.startswith(prefix):
            status_code_val = code
            break
    raise HTTPException(status_code=status_code_val, detail=err)


# ── Correction Diffs ─────────────────────────────────────────────────


@router.post(
    "/households/{household_id}/correction-diffs",
    response_model=CorrectionDiffRead,
    status_code=status.HTTP_201_CREATED,
)
def create_correction_diff_endpoint(
    household_id: str,
    payload: CorrectionDiffCreate,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> CorrectionDiffRead:
    household = _hs_household(session, household_id, actor_id)
    member = session.get(Member, payload.member_id)
    if member is None or member.household_id != household_id:
        _raise_resource_not_found()
    try:
        diff = _hs.create_correction_diff(
            session,
            household_id=household.id,
            member_id=member.id,
            source_event_id=payload.source_event_id,
            field_path=payload.field_path,
            before_value=payload.before_value,
            after_value=payload.after_value,
            reason=payload.reason,
            evidence=payload.evidence,
            operator_actor_id=actor_id,
        )
    except ValueError as exc:
        _hs_raise_val(str(exc))
    session.commit()
    session.refresh(diff)
    return CorrectionDiffRead.model_validate(diff)


@router.get(
    "/households/{household_id}/correction-diffs",
    response_model=list[CorrectionDiffRead],
)
def list_correction_diffs_endpoint(
    household_id: str,
    member_id: str | None = None,
    source_event_id: str | None = None,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> list[CorrectionDiffRead]:
    _hs_household(session, household_id, actor_id)
    diffs = _hs.list_correction_diffs(
        session, household_id, member_id=member_id, source_event_id=source_event_id
    )
    return [CorrectionDiffRead.model_validate(d) for d in diffs]


@router.get(
    "/households/{household_id}/correction-diffs/{diff_id}",
    response_model=CorrectionDiffRead,
)
def get_correction_diff_endpoint(
    household_id: str,
    diff_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> CorrectionDiffRead:
    _hs_household(session, household_id, actor_id)
    diff = _hs.get_correction_diff(session, diff_id)
    if diff is None or diff.household_id != household_id:
        _raise_resource_not_found()
    return CorrectionDiffRead.model_validate(diff)


# ── Hard Samples ──────────────────────────────────────────────────────


@router.post(
    "/households/{household_id}/hard-samples",
    response_model=HardSampleRead,
    status_code=status.HTTP_201_CREATED,
)
def create_hard_sample_endpoint(
    household_id: str,
    payload: HardSampleCreate,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> HardSampleRead:
    household = _hs_household(session, household_id, actor_id)
    member = session.get(Member, payload.member_id)
    if member is None or member.household_id != household_id:
        _raise_resource_not_found()
    try:
        sample = _hs.create_hard_sample(
            session,
            household_id=household.id,
            member_id=member.id,
            source_event_id=payload.source_event_id,
            category=payload.category,
            note=payload.note,
            created_by=actor_id,
        )
    except ValueError as exc:
        _hs_raise_val(str(exc))
    session.commit()
    session.refresh(sample)
    return HardSampleRead.model_validate(sample)


@router.get(
    "/households/{household_id}/hard-samples",
    response_model=list[HardSampleRead],
)
def list_hard_samples_endpoint(
    household_id: str,
    status: str | None = None,
    category: str | None = None,
    member_id: str | None = None,
    include_deleted: bool = False,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> list[HardSampleRead]:
    _hs_household(session, household_id, actor_id)
    samples = _hs.list_hard_samples(
        session,
        household_id,
        status=status,
        category=category,
        member_id=member_id,
        include_deleted=include_deleted,
    )
    return [HardSampleRead.model_validate(s) for s in samples]


@router.get(
    "/households/{household_id}/hard-samples/{sample_id}",
    response_model=HardSampleRead,
)
def get_hard_sample_endpoint(
    household_id: str,
    sample_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> HardSampleRead:
    _hs_household(session, household_id, actor_id)
    sample = _hs.get_hard_sample(session, sample_id)
    if sample is None or sample.household_id != household_id:
        _raise_resource_not_found()
    return HardSampleRead.model_validate(sample)


@router.patch(
    "/households/{household_id}/hard-samples/{sample_id}",
    response_model=HardSampleRead,
)
def update_hard_sample_endpoint(
    household_id: str,
    sample_id: str,
    payload: HardSampleUpdate,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> HardSampleRead:
    _hs_household(session, household_id, actor_id)
    sample = _hs.get_hard_sample(session, sample_id)
    if sample is None or sample.household_id != household_id:
        _raise_resource_not_found()
    try:
        _hs.update_hard_sample_status(
            session,
            sample,
            new_status=payload.status,
            actor_id=actor_id,
            note=payload.note,
        )
    except ValueError as exc:
        _hs_raise_val(str(exc))
    session.commit()
    session.refresh(sample)
    return HardSampleRead.model_validate(sample)


@router.delete("/households/{household_id}/hard-samples/{sample_id}")
def delete_hard_sample_endpoint(
    household_id: str,
    sample_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> dict:
    _hs_household(session, household_id, actor_id)
    sample = _hs.get_hard_sample(session, sample_id)
    if sample is None or sample.household_id != household_id:
        _raise_resource_not_found()
    try:
        _hs.delete_hard_sample(session, sample, actor_id=actor_id)
    except ValueError as exc:
        _hs_raise_val(str(exc))
    session.commit()
    return {"status": "deleted", "sample_id": sample_id}


# ── Training Consent ──────────────────────────────────────────────────


@router.post(
    "/households/{household_id}/hard-samples/{sample_id}/training-consent",
    response_model=TrainingConsentRead,
    status_code=status.HTTP_201_CREATED,
)
def grant_training_consent_endpoint(
    household_id: str,
    sample_id: str,
    payload: TrainingConsentCreate,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> TrainingConsentRead:
    _hs_household(session, household_id, actor_id)
    sample = _hs.get_hard_sample(session, sample_id)
    if sample is None or sample.household_id != household_id:
        _raise_resource_not_found()
    try:
        consent = _hs.grant_training_consent(
            session,
            hard_sample_id=sample_id,
            household_id=household_id,
            member_id=sample.member_id,
            granted_by=actor_id,
            scope=payload.scope,
            license=payload.license,
        )
    except ValueError as exc:
        _hs_raise_val(str(exc))
    session.commit()
    session.refresh(consent)
    return TrainingConsentRead.model_validate(consent)


@router.get(
    "/households/{household_id}/hard-samples/{sample_id}/training-consent",
    response_model=TrainingConsentRead | None,
)
def get_training_consent_endpoint(
    household_id: str,
    sample_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> TrainingConsentRead | None:
    _hs_household(session, household_id, actor_id)
    sample = _hs.get_hard_sample(session, sample_id)
    if sample is None or sample.household_id != household_id:
        _raise_resource_not_found()
    consent = _hs.get_training_consent(session, sample_id)
    if consent is None:
        return None
    return TrainingConsentRead.model_validate(consent)


@router.post(
    "/households/{household_id}/hard-samples/{sample_id}/training-consent/revoke",
    response_model=TrainingConsentRead,
)
def revoke_training_consent_endpoint(
    household_id: str,
    sample_id: str,
    payload: TrainingConsentRevoke,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> TrainingConsentRead:
    _hs_household(session, household_id, actor_id)
    sample = _hs.get_hard_sample(session, sample_id)
    if sample is None or sample.household_id != household_id:
        _raise_resource_not_found()
    try:
        consent = _hs.revoke_training_consent(
            session, sample_id, actor_id=actor_id, reason=payload.reason
        )
    except ValueError as exc:
        _hs_raise_val(str(exc))
    session.commit()
    session.refresh(consent)
    return TrainingConsentRead.model_validate(consent)


# ── Export Manifests ──────────────────────────────────────────────────


@router.post(
    "/households/{household_id}/export-manifests",
    response_model=ExportManifestRead,
    status_code=status.HTTP_201_CREATED,
)
def create_export_manifest_endpoint(
    household_id: str,
    payload: ExportManifestCreate,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> ExportManifestRead:
    _hs_household(session, household_id, actor_id)
    try:
        manifest = _hs.create_export_manifest(
            session,
            household_id=household_id,
            version=payload.version,
            group_key=payload.group_key,
            license=payload.license,
            sample_ids=payload.sample_ids,
            created_by=actor_id,
        )
    except ValueError as exc:
        _hs_raise_val(str(exc))
    session.commit()
    session.refresh(manifest)
    return ExportManifestRead.model_validate(manifest)


@router.get(
    "/households/{household_id}/export-manifests",
    response_model=list[ExportManifestRead],
)
def list_export_manifests_endpoint(
    household_id: str,
    status: str | None = None,
    group_key: str | None = None,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> list[ExportManifestRead]:
    _hs_household(session, household_id, actor_id)
    manifests = _hs.list_export_manifests(session, household_id, status=status, group_key=group_key)
    return [ExportManifestRead.model_validate(m) for m in manifests]


@router.get(
    "/households/{household_id}/export-manifests/{manifest_id}",
    response_model=ExportManifestRead,
)
def get_export_manifest_endpoint(
    household_id: str,
    manifest_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> ExportManifestRead:
    _hs_household(session, household_id, actor_id)
    manifest = _hs.get_export_manifest(session, manifest_id)
    if manifest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MANIFEST_NOT_FOUND")
    return ExportManifestRead.model_validate(manifest)


@router.post(
    "/households/{household_id}/export-manifests/{manifest_id}/invalidate",
    response_model=ExportManifestRead,
)
def invalidate_export_manifest_endpoint(
    household_id: str,
    manifest_id: str,
    payload: ExportManifestInvalidate,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> ExportManifestRead:
    _hs_household(session, household_id, actor_id)
    manifest = _hs.get_export_manifest(session, manifest_id)
    if manifest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MANIFEST_NOT_FOUND")
    try:
        _hs.invalidate_export_manifest(session, manifest, actor_id=actor_id, reason=payload.reason)
    except ValueError as exc:
        _hs_raise_val(str(exc))
    session.commit()
    session.refresh(manifest)
    return ExportManifestRead.model_validate(manifest)


# ── HCT-404: Model version binding, release and rollback ──────────────


from app import model_binding as _mb  # noqa: E402


def _can_govern_model_release(
    actor_id: str,
    binding: _mb.ModelVersionBinding,
    *,
    action: str = "rollback",
) -> bool:
    """Authorize model release governance.

    - Dual-control activate: activator must differ from creator; when
      ``MODEL_RELEASE_ADMIN_ACTORS`` is set the activator must be listed.
    - Rollback / non-dual: creator, or listed release admins.
    """
    settings = get_settings()
    admins = settings.model_release_admin_actor_set
    if action == "activate" and settings.model_release_dual_control:
        if actor_id == binding.created_by:
            return False
        if admins:
            return actor_id in admins
        return True
    if admins:
        return actor_id in admins
    return binding.created_by == actor_id


def _mb_raise_val(err: str) -> NoReturn:
    mapping: dict[str, int] = {
        "BINDING_NOT_FOUND": 404,
        "BINDING_NOT_ACTIVE": 409,
        "BINDING_NOT_INACTIVE": 409,
        "BINDING_ALREADY_ACTIVE": 409,
        "BINDING_ALREADY_REVOKED": 409,
        "NO_ACTIVE_BINDING": 404,
        "COMPARISON_REPORT_REQUIRED": 422,
        "HCT404_FORMAL_RELEASE_REQUIRED": 422,
        "HCT404_RELEASE_EVIDENCE_SCHEMA_REQUIRED": 422,
        "HCT404_RELEASE_EVIDENCE_HASH_REQUIRED": 422,
        "HCT404_RELEASE_EVIDENCE_HASH_MISMATCH": 422,
        "HCT404_FIXED_SET_HASH_MISMATCH": 422,
        "HCT404_COMPARISON_HASH_MISMATCH": 422,
        "HCT404_ROLLBACK_REASON_REQUIRED": 422,
        "HCT404_ROLLBACK_EVIDENCE_REQUIRED": 422,
        "RELEASE_DUAL_CONTROL_REQUIRED": 422,
        "RELEASE_ADMIN_REQUIRED": 403,
        "KNOWLEDGE_ADMIN_REQUIRED": 403,
    }
    status_code_val = 422
    for prefix, code in mapping.items():
        if err.startswith(prefix):
            status_code_val = code
            break
    raise HTTPException(status_code=status_code_val, detail=err)


def _resolve_active_model_version(session: Session) -> str | None:
    """Resolve active model version for vision task creation."""
    try:
        return _mb.resolve_active_model_version(session)
    except Exception:
        return None


@router.post(
    "/model-version-bindings",
    response_model=ModelVersionBindingRead,
    status_code=status.HTTP_201_CREATED,
)
def create_model_binding_endpoint(
    payload: ModelVersionBindingCreate,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> ModelVersionBindingRead:
    try:
        binding = _mb.create_binding(
            session,
            model_id=payload.model_id,
            dataset_version=payload.dataset_version,
            export_manifest_id=payload.export_manifest_id,
            fixed_set_hash=payload.fixed_set_hash,
            safety_thresholds=payload.safety_thresholds,
            comparison_report_hash=payload.comparison_report_hash,
            release_evidence_hash=payload.release_evidence_hash,
            created_by=actor_id,
        )
    except ValueError as exc:
        _mb_raise_val(str(exc))
    session.commit()
    session.refresh(binding)
    return ModelVersionBindingRead.model_validate(binding)


@router.get(
    "/model-version-bindings",
    response_model=list[ModelVersionBindingRead],
)
def list_model_bindings_endpoint(
    model_id: str | None = None,
    release_status: str | None = None,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> list[ModelVersionBindingRead]:
    del actor_id  # Release-ledger metadata is D1 internal: identity required.
    bindings = _mb.list_bindings(session, model_id=model_id, release_status=release_status)
    return [ModelVersionBindingRead.model_validate(b) for b in bindings]


@router.get(
    "/model-version-bindings/{binding_id}",
    response_model=ModelVersionBindingRead,
)
def get_model_binding_endpoint(
    binding_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> ModelVersionBindingRead:
    del actor_id
    binding = _mb.get_binding(session, binding_id)
    if binding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BINDING_NOT_FOUND")
    return ModelVersionBindingRead.model_validate(binding)


@router.post(
    "/model-version-bindings/{binding_id}/activate",
    response_model=ModelVersionBindingRead,
)
def activate_model_binding_endpoint(
    binding_id: str,
    payload: ModelVersionBindingActivate,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> ModelVersionBindingRead:
    """Activate a model release. Dual-control: activator must not be the creator."""
    binding = _mb.get_binding(session, binding_id)
    if binding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BINDING_NOT_FOUND")
    settings = get_settings()
    if settings.model_release_dual_control and actor_id == binding.created_by:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="RELEASE_DUAL_CONTROL_REQUIRED",
        )
    if not _can_govern_model_release(actor_id, binding, action="activate"):
        detail = (
            "RELEASE_ADMIN_REQUIRED"
            if settings.model_release_admin_actor_set
            else "BINDING_NOT_FOUND"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN
            if detail == "RELEASE_ADMIN_REQUIRED"
            else status.HTTP_404_NOT_FOUND,
            detail=detail,
        )
    if payload.approved_by != actor_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="APPROVED_BY_MUST_MATCH_ACTOR",
        )
    try:
        _mb.activate_binding(session, binding, approved_by=actor_id)
    except ValueError as exc:
        _mb_raise_val(str(exc))
    session.commit()
    session.refresh(binding)
    logger.info(
        "MODEL_BINDING_ACTIVATE_REQUESTED binding=%s actor=%s approved_by=%s",
        binding.id,
        actor_id,
        actor_id,
    )
    return ModelVersionBindingRead.model_validate(binding)


@router.post(
    "/model-version-bindings/{binding_id}/rollback",
    response_model=ModelVersionBindingRead,
)
def rollback_model_binding_endpoint(
    binding_id: str,
    payload: ModelVersionBindingRollback,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> ModelVersionBindingRead:
    """Roll back a model release, attributed to the authenticated caller."""
    binding = _mb.get_binding(session, binding_id)
    if binding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BINDING_NOT_FOUND")
    if not _can_govern_model_release(actor_id, binding, action="rollback"):
        detail = (
            "RELEASE_ADMIN_REQUIRED"
            if get_settings().model_release_admin_actor_set
            else "BINDING_NOT_FOUND"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN
            if detail == "RELEASE_ADMIN_REQUIRED"
            else status.HTTP_404_NOT_FOUND,
            detail=detail,
        )
    try:
        _mb.rollback_binding(
            session,
            binding,
            actor_id=actor_id,
            reason=payload.reason,
            evidence_hash=payload.evidence_hash,
        )
    except ValueError as exc:
        _mb_raise_val(str(exc))
    session.commit()
    session.refresh(binding)
    return ModelVersionBindingRead.model_validate(binding)


@router.get("/model-version-bindings/{binding_id}/comparison", response_model=dict)
def get_model_binding_comparison_endpoint(
    binding_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> dict:
    del actor_id
    binding = _mb.get_binding(session, binding_id)
    if binding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BINDING_NOT_FOUND")
    return {
        "binding_id": binding.id,
        "comparison_report_hash": binding.comparison_report_hash,
        "release_evidence_hash": binding.release_evidence_hash,
        "rollback_evidence_hash": binding.rollback_evidence_hash,
        "model_id": binding.model_id,
        "dataset_version": binding.dataset_version,
        "fixed_set_hash": binding.fixed_set_hash,
        "safety_thresholds": binding.safety_thresholds,
    }


@router.get("/meta/active-model-version", response_model=dict)
def active_model_version_endpoint(
    session: Session = Depends(get_session),
) -> dict:
    version = _resolve_active_model_version(session)
    settings = get_settings()
    return {
        "active_model_version": version or settings.vision_model_version,
        "source": "binding" if version else "config",
    }
