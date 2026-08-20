import logging
import secrets
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
from fastapi.responses import FileResponse
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import (
    authenticate,
    generate_pin_challenge,
    logout,
    register_account,
    verify_pin,
)
from app.config import get_settings
from app.db import get_session
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
from app.file_upload import (
    compute_hash,
    delete_file_tree,
    validate_and_store,
    validate_extension,
    validate_filename,
    validate_magic,
    validate_size,
)
from app.knowledge import KnowledgeDocument
from app.models import (
    AccessAudit,
    CareAuthorization,
    HealthEvent,
    Household,
    Member,
    MemberStateProjection,
    OutboxMessage,
    RiskAcknowledgement,
    VisionTask,
)
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
    AccessAuditRead,
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
    KnowledgeDocumentCreate,
    KnowledgeDocumentRead,
    KnowledgeRetrieveRequest,
    KnowledgeRetrieveResponse,
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
    TrainingConsentCreate,
    TrainingConsentRead,
    TrainingConsentRevoke,
    VisionFusionRead,
    VisionQualityRead,
    VisionTaskCreate,
    VisionTaskRead,
)
from app.security import (
    get_access_purpose,
    get_actor_id,
    has_authorized_action,
    require_household_owner,
)
from app.tool_call import (
    get_approved_tools,
    run_assistant,
)
from app.vision_tasks import (
    VISION_MEDIA_TYPES,
    VisionTaskStatus,
    _file_digest,
    create_vision_task,
    get_vision_task,
    list_vision_tasks,
    retry_vision_task,
    transition_status,
)
from app.weather_adapter import WeatherActionCardsResponse, fetch_weather

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")
settings = get_settings()


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


@router.get("/health/db", response_model=HealthResponse)
def database_health(session: Session = Depends(get_session)) -> HealthResponse:
    session.execute(text("SELECT 1"))
    return HealthResponse(status="ok", service=f"{settings.app_name} database", version="0.1.0")


@router.get("/meta/capabilities", response_model=CapabilityResponse)
def capabilities() -> CapabilityResponse:
    return CapabilityResponse(
        phase="P0-foundation",
        available=[
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
        ],
        unavailable=["vision-inference", "llm-cloud", "external-web"],
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
        if "health_events" in (a.data_fields or [])
        and "READ_EVENTS" in (a.actions or [])
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
        a.household_id
        for a in _valid_authorizations(session, actor_id, purpose=access_purpose)
    }
    authorized = (
        list(session.scalars(
            select(Household).where(
                Household.id.in_(authorized_ids),
                Household.deleted_at.is_(None),
            )
        ).all())
        if authorized_ids
        else []
    )
    seen: set[str] = set()
    result: list[Household] = []
    for h in list(owned) + authorized:
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
    authorized_members = [
        m
        for m in members
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
    if not authorized_members:
        _raise_resource_not_found()
    return authorized_members


@router.post("/households", response_model=HouseholdRead, status_code=status.HTTP_201_CREATED)
def create_household(
    payload: HouseholdCreate,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> Household:
    household = Household(name=payload.name, created_by=actor_id)
    session.add(household)
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
    member = Member(
        household_id=household.id,
        display_name=payload.display_name,
        role=payload.role,
        actor_id=payload.actor_id,
    )
    session.add(member)
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
            "IDEMPOTENCY_KEY_CONFLICT"
            if idempotency_key is not None
            else "IDEMPOTENCY_CONFLICT"
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
    allowed_member_ids = _authorized_event_member_ids(
        session, household, actor_id, access_purpose
    )
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
    if member_id is not None:
        query = query.where(HealthEvent.member_id == member_id)
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
        if has_authorized_action(
            session,
            household,
            member.id,
            actor_id,
            "READ_EVENTS",
            "health_events",
            access_purpose,
        )
    }


@router.get(
    "/households/{household_id}/events/page",
    response_model=HealthEventPageRead,
)
def page_health_events(
    household_id: str,
    member_id: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> HealthEventPageRead:
    """Return an authorization-scoped page without exposing event payload in the cursor."""
    household = session.get(Household, household_id)
    if _is_erased(household):
        _raise_resource_not_found()
    allowed_member_ids = _authorized_event_member_ids(
        session, household, actor_id, access_purpose
    )
    if member_id is not None and member_id not in allowed_member_ids:
        _raise_resource_not_found()
    if not allowed_member_ids:
        if household.created_by == actor_id:
            return HealthEventPageRead(items=[])
        _raise_resource_not_found()

    try:
        decoded_cursor = (
            decode_event_cursor(cursor, secret=settings.cursor_signing_key)
            if cursor
            else None
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    if decoded_cursor is not None and (
        decoded_cursor.household_id != household.id or decoded_cursor.member_id != member_id
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
            or (
                member_id is not None
                and cursor_anchor.member_id != member_id
            )
            or (
                member_id is None
                and cursor_anchor.member_id not in allowed_member_ids
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="EVENT_CURSOR_INVALID",
            )

    query = select(HealthEvent).where(
        HealthEvent.household_id == household.id,
        HealthEvent.member_id.in_(allowed_member_ids),
    )
    if member_id is not None:
        query = query.where(HealthEvent.member_id == member_id)
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
    """Upload a file with validation, store with random key."""
    result = await validate_and_store(file)
    logger.info(
        "FILE_UPLOADED actor=%s key=%s size=%d",
        actor_id, result["storage_key"], result["size_bytes"],
    )
    return result


@router.get("/files/{storage_key}")
def download_file(
    storage_key: str,
    actor_id: str = Depends(get_actor_id),
) -> FileResponse:
    """Download a previously uploaded file by storage key."""
    settings = get_settings()
    root = Path(settings.file_root).resolve()
    target = (root / storage_key).resolve()

    if not str(target).startswith(str(root)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FILE_NOT_FOUND")
    if not target.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FILE_NOT_FOUND")

    logger.info("FILE_DOWNLOADED actor=%s key=%s", actor_id, storage_key)
    return FileResponse(str(target))


@router.delete("/files/{storage_key}")
def delete_file(
    storage_key: str,
    actor_id: str = Depends(get_actor_id),
) -> dict:
    """Delete a file and its thumbnails/cache/index entries."""
    deleted = delete_file_tree(storage_key)
    logger.info(
        "FILE_DELETED actor=%s key=%s deleted_paths=%d",
        actor_id, storage_key, len(deleted),
    )
    return {"storage_key": storage_key, "deleted_paths": len(deleted)}


# ── HCT-107: Local auth ────────────────────────────────────────────


@router.post("/auth/register", response_model=dict, status_code=status.HTTP_201_CREATED)
def auth_register(
    payload: AuthCredentials,
) -> dict:
    register_account(payload.actor_id, payload.password)
    return {"status": "registered", "actor_id": payload.actor_id}


@router.post("/auth/login", response_model=AuthSessionRead)
def auth_login(
    payload: AuthCredentials,
) -> dict:
    return {"actor_id": payload.actor_id, **authenticate(payload.actor_id, payload.password)}


@router.post("/auth/logout")
def auth_logout(payload: AuthSessionRequest) -> dict:
    logout(payload.session_token)
    return {"status": "logged_out"}


@router.post("/auth/pin-challenge")
def auth_pin_challenge(
    actor_id: str = Depends(get_actor_id),
) -> dict:
    session_token = secrets.token_hex(16)
    return generate_pin_challenge(actor_id, "confirm_high_risk", session_token)


@router.post("/auth/pin-verify")
def auth_pin_verify(
    pin: str,
    action: str = "confirm_high_risk",
    session_token: str = "",
) -> dict:
    ok = verify_pin(pin, action, session_token)
    if not ok:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="PIN_INVALID")
    return {"status": "confirmed"}


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
    if not has_authorized_action(
        session, household, member_id, actor_id, "READ_EVENTS", "health_events", access_purpose,
    ):
        _raise_resource_not_found()

    from app.projection import get_timeline

    since_dt = datetime.fromisoformat(since) if since else None
    until_dt = datetime.fromisoformat(until) if until else None
    events = get_timeline(session, member_id, since=since_dt, until=until_dt)
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
    if not has_authorized_action(
        session, household, member_id, actor_id, "READ_EVENTS", "health_events", access_purpose,
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
    if not has_authorized_action(
        session, household, member_id, actor_id, "READ_EVENTS", "health_events", access_purpose,
    ):
        _raise_resource_not_found()

    from app.care_plan import build_plan_workbench
    from app.projection import get_timeline

    return PlanWorkbenchRead(
        member_id=member_id,
        generated_at=datetime.now(UTC),
        plans=build_plan_workbench(get_timeline(session, member_id)),
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

    pending_reviews = session.scalar(
        select(func.count()).select_from(ReviewTask).where(
            ReviewTask.household_id == household_id,
            ReviewTask.status == "PENDING_REVIEW",
        )
    ) or 0
    pending_outbox = session.scalar(
        select(func.count())
        .select_from(OutboxMessage)
        .join(HealthEvent, OutboxMessage.event_id == HealthEvent.id)
        .where(
            HealthEvent.household_id == household_id,
            OutboxMessage.status.in_(("PENDING", "FAILED")),
        )
    ) or 0
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
    session: Session = Depends(get_session),
) -> list[dict]:
    household = session.get(Household, household_id)
    member = session.get(Member, member_id)
    if _is_erased(household, member):
        _raise_resource_not_found()
    from app.projection import build_relationship_graph, get_timeline
    from app.rules import run_rules

    events = get_timeline(session, member_id)
    facts = build_relationship_graph(events)
    alerts = run_rules(facts)
    logger.info("RULES_RUN member=%s alerts=%d", member_id, len(alerts))
    return [{"rule_id": a.rule_id, "level": a.level, "message": a.message,
             "source_event_ids": a.source_event_ids} for a in alerts]


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
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> HealthEventRead:
    household = session.get(Household, household_id)
    member = session.get(Member, member_id)
    if _is_erased(household, member):
        _raise_resource_not_found()
    if not has_authorized_action(
        session, household, member_id, actor_id, "WRITE_EVENTS", "health_events", access_purpose,
    ):
        _raise_resource_not_found()
    event = _append_care_plan_action(
        session,
        household=household,
        member=member,
        actor_id=actor_id,
        request=request,
        event_type="plan_confirmed",
        payload={"plan_event_id": plan_event_id, "confirmed_at": datetime.now(UTC).isoformat()},
        idempotency_key=f"confirm:{plan_event_id}",
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
        session, household, member_id, actor_id, "WRITE_EVENTS", "health_events", access_purpose,
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
        session, household, member_id, actor_id, "WRITE_EVENTS", "health_events", access_purpose,
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
    stmt = (
        select(KnowledgeDocument)
        .where(KnowledgeDocument.status == "active")
        .order_by(KnowledgeDocument.created_at.desc())
    )
    docs = session.scalars(stmt).all()
    return [
        d for d in docs
        if _check_permission(d.permission_scope, actor_id)
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
    if not _check_permission(doc.permission_scope, actor_id):
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


@router.post("/assistant/chat", response_model=AssistantResponse)
def assistant_chat(
    payload: AssistantRequest,
    actor_id: str = Depends(get_actor_id),
    household_id: str | None = None,
    member_id: str | None = None,
    session: Session = Depends(get_session),
) -> AssistantResponse:
    """Run the local health assistant with Ollama tool calling.

    Grounds the conversation in the selected member's confirmed facts, then
    falls back to a structured degrade response if the model is unavailable,
    output fails schema validation, or medical boundary checks are triggered.
    """
    messages = list(payload.messages)
    context = _build_assistant_context(session, actor_id, household_id, member_id)
    if context:
        messages = [{"role": "system", "content": context}, *messages]
    result = run_assistant(
        session,
        messages=messages,
        actor_id=actor_id,
        household_id=household_id,
        member_id=member_id,
        model=payload.model,
        max_tokens=payload.max_tokens,
        temperature=payload.temperature,
    )
    session.commit()
    return AssistantResponse(**result)


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
    if (
        member is None
        or household is None
        or _is_erased(household, member)
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
        household = (
            session.get(Household, member.household_id)
            if member is not None
            else None
        )
        if (
            member is None
            or household is None
            or _is_erased(household, member)
            or not has_authorized_action(
                session,
                household,
                member.id,
                actor_id,
                "WRITE_EVENTS",
                "health_events",
                access_purpose,
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
    specs_by_record = {
        record.record_id: record.specification for record in master_data.records
    }

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
                        record.name_aliases[0]
                        if record.name_aliases
                        else record.record_id
                    ),
                    "confidence": candidate.score,
                    "product_barcode": record.product_barcode,
                    "specification": record.specification,
                    "manufacturer": record.manufacturer,
                    "packaging_type": record.packaging_type,
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
            or not has_authorized_action(
                session,
                household,
                member.id,
                actor_id,
                "READ_EVENTS",
                "health_events",
                access_purpose,
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

    if task.status in (VisionTaskStatus.SUCCEEDED, VisionTaskStatus.FAILED,
                       VisionTaskStatus.TIMEOUT, VisionTaskStatus.CANCELLED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"VISION_TASK_ALREADY_{task.status.upper()}",
        )

    updated = transition_status(
        session, task, VisionTaskStatus.CANCELLED,
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
    if not has_authorized_action(
        session, household, member_id, actor_id, "READ_EVENTS", "health_events", access_purpose,
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
    if not has_authorized_action(
        session, household, member_id, actor_id, "READ_EVENTS", "health_events", access_purpose,
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
            sources.append({
                "id": evt.id,
                "event_type": evt.event_type,
                "confirmation_status": evt.confirmation_status,
                "created_at": evt.created_at.isoformat() if evt.created_at else None,
            })
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
        session, household_id,
        status=status, category=category, member_id=member_id,
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
            session, sample,
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
    manifests = _hs.list_export_manifests(
        session, household_id, status=status, group_key=group_key
    )
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
        _hs.invalidate_export_manifest(
            session, manifest, actor_id=actor_id, reason=payload.reason
        )
    except ValueError as exc:
        _hs_raise_val(str(exc))
    session.commit()
    session.refresh(manifest)
    return ExportManifestRead.model_validate(manifest)


# ── HCT-404: Model version binding, release and rollback ──────────────


from app import model_binding as _mb  # noqa: E402


def _mb_raise_val(err: str) -> NoReturn:
    mapping: dict[str, int] = {
        "BINDING_NOT_FOUND": 404,
        "BINDING_NOT_ACTIVE": 409,
        "BINDING_NOT_INACTIVE": 409,
        "BINDING_ALREADY_ACTIVE": 409,
        "BINDING_ALREADY_REVOKED": 409,
        "NO_ACTIVE_BINDING": 404,
        "COMPARISON_REPORT_REQUIRED": 422,
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
    session: Session = Depends(get_session),
) -> list[ModelVersionBindingRead]:
    bindings = _mb.list_bindings(session, model_id=model_id, release_status=release_status)
    return [ModelVersionBindingRead.model_validate(b) for b in bindings]


@router.get(
    "/model-version-bindings/{binding_id}",
    response_model=ModelVersionBindingRead,
)
def get_model_binding_endpoint(
    binding_id: str,
    session: Session = Depends(get_session),
) -> ModelVersionBindingRead:
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
    session: Session = Depends(get_session),
) -> ModelVersionBindingRead:
    binding = _mb.get_binding(session, binding_id)
    if binding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BINDING_NOT_FOUND")
    try:
        _mb.activate_binding(session, binding, approved_by=payload.approved_by)
    except ValueError as exc:
        _mb_raise_val(str(exc))
    session.commit()
    session.refresh(binding)
    return ModelVersionBindingRead.model_validate(binding)


@router.post(
    "/model-version-bindings/{binding_id}/rollback",
    response_model=ModelVersionBindingRead,
)
def rollback_model_binding_endpoint(
    binding_id: str,
    payload: ModelVersionBindingRollback,
    session: Session = Depends(get_session),
) -> ModelVersionBindingRead:
    binding = _mb.get_binding(session, binding_id)
    if binding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BINDING_NOT_FOUND")
    try:
        _mb.rollback_binding(session, binding, actor_id="admin", reason=payload.reason)
    except ValueError as exc:
        _mb_raise_val(str(exc))
    session.commit()
    session.refresh(binding)
    return ModelVersionBindingRead.model_validate(binding)


@router.get("/model-version-bindings/{binding_id}/comparison", response_model=dict)
def get_model_binding_comparison_endpoint(
    binding_id: str,
    session: Session = Depends(get_session),
) -> dict:
    binding = _mb.get_binding(session, binding_id)
    if binding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BINDING_NOT_FOUND")
    return {
        "binding_id": binding.id,
        "comparison_report_hash": binding.comparison_report_hash,
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
