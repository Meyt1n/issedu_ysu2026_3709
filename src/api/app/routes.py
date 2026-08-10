import logging
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NoReturn

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select, text, update
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
from app.file_upload import delete_file_tree, validate_and_store
from app.models import (
    AccessAudit,
    CareAuthorization,
    HealthEvent,
    Household,
    Member,
    MemberStateProjection,
    OutboxMessage,
    VisionTask,
)
from app.review import (
    ReviewTask,
    confirm_review,
    correct_review,
    get_review_task,
    list_pending_reviews,
    skip_review,
)
from app.schemas import (
    AccessAuditRead,
    AuthorizationCreate,
    AuthorizationRead,
    AuthorizationRevoke,
    AuthorizationUpdate,
    CapabilityResponse,
    HealthEventCompensationCreate,
    HealthEventCreate,
    HealthEventRead,
    HealthResponse,
    HouseholdCreate,
    HouseholdRead,
    KnowledgeChunkRead,
    KnowledgeDocumentCreate,
    KnowledgeDocumentRead,
    KnowledgeRetrieveRequest,
    KnowledgeRetrieveResponse,
    MemberCreate,
    MemberRead,
    MemberStateRead,
    OutboxDispatchRead,
    OutboxDispatchRequest,
    OutboxRead,
    ProjectionCheckpointRead,
    ProjectionReplayRead,
    ProjectionReplayRequest,
    ReviewTaskConfirm,
    ReviewTaskCorrect,
    ReviewTaskRead,
    ReviewTaskSkip,
    RiskAlertRead,
    RiskDetailResponse,
    RiskListResponse,
    VisionTaskCreate,
    VisionTaskRead,
)
from app.security import (
    get_access_purpose,
    get_actor_id,
    has_authorized_action,
    require_household_owner,
)
from app.vision_tasks import (
    VisionTaskStatus,
    _file_digest,
    create_vision_task,
    get_vision_task,
    list_vision_tasks,
    transition_status,
)
from app.weather_adapter import fetch_weather

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")
settings = get_settings()


def _raise_resource_not_found() -> NoReturn:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RESOURCE_NOT_FOUND")


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
        ],
        unavailable=["rag", "llm", "weather"],
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
        select(Household).where(Household.created_by == actor_id)
    ).all()
    authorized_ids = {
        a.household_id
        for a in _valid_authorizations(session, actor_id, purpose=access_purpose)
    }
    authorized = (
        list(session.scalars(
            select(Household).where(Household.id.in_(authorized_ids))
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
    if household is None:
        _raise_resource_not_found()
    if household.created_by == actor_id:
        query = select(Member).where(Member.household_id == household_id)
        return list(session.scalars(query).all())

    members = list(
        session.scalars(
            select(Member).where(Member.household_id == household_id)
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
    member = session.get(Member, payload.member_id)
    if member is None or member.household_id != household.id:
        _raise_resource_not_found()
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
    if household is None:
        _raise_resource_not_found()
    member = session.get(Member, payload.member_id)
    if member is None or member.household_id != household.id:
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
    if household is None:
        _raise_resource_not_found()
    members = session.scalars(select(Member).where(Member.household_id == household.id)).all()
    allowed_member_ids = {
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
    if member_id is not None and member_id not in allowed_member_ids:
        _raise_resource_not_found()
    if member_id is None and household.created_by != actor_id and not allowed_member_ids:
        _raise_resource_not_found()
    query = select(HealthEvent).where(HealthEvent.household_id == household.id)
    if household.created_by != actor_id:
        query = query.where(HealthEvent.member_id.in_(allowed_member_ids))
    elif member_id is not None:
        query = query.where(HealthEvent.member_id == member_id)
    return list(session.scalars(query.order_by(HealthEvent.sequence_no)).all())


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
    if household is None or member is None or member.household_id != household_id:
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
    if member is None or member.household_id != household_id:
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


@router.get("/weather/action-cards", response_model=dict)
async def weather_action_cards(
    city_code: str | None = None,
    district_code: str | None = None,
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


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
def auth_register(
    actor_id: str,
    password: str,
) -> dict:
    register_account(actor_id, password)
    return {"status": "registered", "actor_id": actor_id}


@router.post("/auth/login")
def auth_login(
    actor_id: str,
    password: str,
) -> dict:
    return authenticate(actor_id, password)


@router.post("/auth/logout")
def auth_logout(session_token: str) -> dict:
    logout(session_token)
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
    if household is None or member is None or member.household_id != household_id:
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


@router.post("/households/{household_id}/members/{member_id}/projection/rebuild")
def rebuild_member_projection(
    household_id: str,
    member_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> dict:
    household = session.get(Household, household_id)
    if household is None or household.created_by != actor_id:
        _raise_resource_not_found()
    from app.projection import rebuild_projection

    proj = rebuild_projection(session, member_id, household_id)
    return {"member_id": member_id, "state": proj.state, "last_event_id": proj.last_event_id}


# ── HCT-302: Rules engine ──────────────────────────────────────────


@router.post("/households/{household_id}/rules/run")
def run_rules_endpoint(
    household_id: str,
    member_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> list[dict]:
    household = session.get(Household, household_id)
    if household is None:
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


@router.post(
    "/households/{household_id}/members/{member_id}/plans/confirm",
    status_code=status.HTTP_201_CREATED,
)
def confirm_plan_endpoint(
    household_id: str,
    member_id: str,
    plan_event_id: str,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> HealthEventRead:
    household = session.get(Household, household_id)
    member = session.get(Member, member_id)
    if household is None or member is None or member.household_id != household_id:
        _raise_resource_not_found()
    if not has_authorized_action(
        session, household, member_id, actor_id, "WRITE_EVENTS", "health_events", access_purpose,
    ):
        _raise_resource_not_found()
    from app.care_plan import confirm_plan

    event = confirm_plan(member_id, household_id, plan_event_id, actor_id)
    session.add(event)
    session.commit()
    session.refresh(event)
    return HealthEventRead.model_validate(event)


@router.post(
    "/households/{household_id}/members/{member_id}/plans/defer",
    status_code=status.HTTP_201_CREATED,
)
def defer_plan_endpoint(
    household_id: str,
    member_id: str,
    plan_event_id: str,
    delay_hours: int = 4,
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> HealthEventRead:
    household = session.get(Household, household_id)
    member = session.get(Member, member_id)
    if household is None or member is None or member.household_id != household_id:
        _raise_resource_not_found()
    if not has_authorized_action(
        session, household, member_id, actor_id, "WRITE_EVENTS", "health_events", access_purpose,
    ):
        _raise_resource_not_found()
    from app.care_plan import defer_plan

    event = defer_plan(member_id, household_id, plan_event_id, delay_hours, actor_id)
    session.add(event)
    session.commit()
    session.refresh(event)
    return HealthEventRead.model_validate(event)


@router.post(
    "/households/{household_id}/members/{member_id}/plans/skip",
    status_code=status.HTTP_201_CREATED,
)
def skip_plan_endpoint(
    household_id: str,
    member_id: str,
    plan_event_id: str,
    reason: str = "",
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
    session: Session = Depends(get_session),
) -> HealthEventRead:
    household = session.get(Household, household_id)
    member = session.get(Member, member_id)
    if household is None or member is None or member.household_id != household_id:
        _raise_resource_not_found()
    if not has_authorized_action(
        session, household, member_id, actor_id, "WRITE_EVENTS", "health_events", access_purpose,
    ):
        _raise_resource_not_found()
    from app.care_plan import skip_plan

    event = skip_plan(member_id, household_id, plan_event_id, reason, actor_id)
    session.add(event)
    session.commit()
    session.refresh(event)
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
) -> KnowledgeDocument:
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
) -> list[KnowledgeDocument]:
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
) -> KnowledgeDocument:
    from app.knowledge import _check_permission
    doc = session.get(KnowledgeDocument, doc_id)
    if doc is None:
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
    from app.knowledge import retrieve, log_query

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
    if doc is None:
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


# ── HCT-204: Vision task API ─────────────────────────────────────────


@router.post(
    "/vision-tasks",
    response_model=VisionTaskRead,
    status_code=status.HTTP_201_CREATED,
)
def create_vision_task_endpoint(
    payload: VisionTaskCreate,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> VisionTask:
    """Create a new vision processing task.

    The *file_id* must already exist in the secure file store (uploaded via
    /files/upload).  The task is queued asynchronously and a worker picks it
    up later.  Use the idempotency key to avoid duplicate tasks on retry.
    """
    settings = get_settings()
    file_root = Path(settings.file_root).resolve()
    target = (file_root / payload.file_id).resolve()

    # Security: only allow files inside the upload root
    if not str(target).startswith(str(file_root)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="FILE_NOT_FOUND",
        )
    if not target.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="FILE_NOT_FOUND",
        )

    # Compute input digest for integrity tracking.
    try:
        input_digest = _file_digest(str(target))
    except Exception:
        input_digest = None

    task = create_vision_task(
        session,
        household_id="system",
        created_by=actor_id,
        file_id=payload.file_id,
        member_id=payload.member_id,
        task_type=payload.task_type,
        idempotency_key=payload.idempotency_key,
        model_threshold=payload.model_threshold,
        input_digest=input_digest,
        preprocess_version="opencv-quality-v1",
        schema_version="vision-result-v1",
        code_version="hct-204-v1",
        data_version="hct-201-dataset-v1",
    )
    session.commit()
    session.refresh(task)
    logger.info("VISION_TASK_ENQUEUED task=%s actor=%s", task.id, actor_id)
    return task


@router.get("/vision-tasks/{task_id}", response_model=VisionTaskRead)
def get_vision_task_endpoint(
    task_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> VisionTask:
    task = get_vision_task(session, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VISION_TASK_NOT_FOUND")
    return task


@router.get("/households/{household_id}/vision-tasks", response_model=list[VisionTaskRead])
def list_vision_tasks_endpoint(
    household_id: str,
    member_id: str | None = None,
    status: str | None = None,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> list[VisionTask]:
    # Verify actor has read access to the household
    household = session.get(Household, household_id)
    if household is None or household.created_by != actor_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HOUSEHOLD_NOT_FOUND")

    if status is not None and status not in {s.value for s in VisionTaskStatus}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"INVALID_STATUS: {status}",
        )

    return list_vision_tasks(session, household_id, member_id=member_id, status=status)


@router.post("/vision-tasks/{task_id}/cancel", response_model=VisionTaskRead)
def cancel_vision_task_endpoint(
    task_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> VisionTask:
    """Cancel a queued or running vision task."""
    task = get_vision_task(session, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VISION_TASK_NOT_FOUND")

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


# ── HCT-207: Manual review API ────────────────────────────────────────


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
    if household is None or member is None or member.household_id != household_id:
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
    return list_pending_reviews(session, household_id, member_id)


@router.get(
    "/households/{household_id}/review-tasks/{task_id}",
    response_model=ReviewTaskRead,
)
def get_review_task_endpoint(
    household_id: str,
    task_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> ReviewTask:
    task = get_review_task(session, task_id)
    if task is None or task.household_id != household_id:
        _raise_resource_not_found()
    if task.household_id != household_id:
        _raise_resource_not_found()
    # Verify actor has read access to this household
    household = session.get(Household, household_id)
    if household is None or household.created_by != actor_id:
        _raise_resource_not_found()
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
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
) -> ReviewTask:
    task = get_review_task(session, task_id)
    if task is None or task.household_id != household_id:
        _raise_resource_not_found()

    household = session.get(Household, household_id)
    if household is None or household.created_by != actor_id:
        _raise_resource_not_found()

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
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
) -> ReviewTask:
    task = get_review_task(session, task_id)
    if task is None or task.household_id != household_id:
        _raise_resource_not_found()

    household = session.get(Household, household_id)
    if household is None or household.created_by != actor_id:
        _raise_resource_not_found()

    updated_task, event_dict = correct_review(
        session,
        task,
        actor_id=actor_id,
        manual_payload=payload.manual_payload,
        correction_note=payload.correction_note,
        idempotency_key=idempotency_key,
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
    session: Session = Depends(get_session),
) -> ReviewTask:
    task = get_review_task(session, task_id)
    if task is None or task.household_id != household_id:
        _raise_resource_not_found()

    household = session.get(Household, household_id)
    if household is None or household.created_by != actor_id:
        _raise_resource_not_found()

    updated_task = skip_review(
        session,
        task,
        actor_id=actor_id,
        reason=payload.reason,
    )
    session.commit()
    session.refresh(updated_task)
    return updated_task


# ── HCT-307: Risk evidence API ─────────────────────────────────────


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
    if household is None or member is None or member.household_id != household_id:
        _raise_resource_not_found()
    if not has_authorized_action(
        session, household, member_id, actor_id, "READ_EVENTS", "health_events", access_purpose,
    ):
        _raise_resource_not_found()
    from app.projection import build_relationship_graph, get_timeline
    from app.rules import apply_daily_budget, dedup_alerts, run_rules

    events = get_timeline(session, member_id)
    facts = build_relationship_graph(events)
    raw = run_rules(facts)
    deduped = dedup_alerts(raw)
    budgeted = apply_daily_budget(deduped)

    alerts = [
        RiskAlertRead(
            rule_id=a.rule_id,
            level=a.level,
            message=a.message,
            source_event_ids=a.source_event_ids,
        )
        for a in budgeted
    ]
    return RiskListResponse(
        member_id=member_id,
        alerts=alerts,
        total=len(alerts),
        severe_count=sum(1 for a in alerts if a.level == "SEVERE"),
        warning_count=sum(1 for a in alerts if a.level == "WARNING"),
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
    if household is None or member is None or member.household_id != household_id:
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
        alert=RiskAlertRead(
            rule_id=alert.rule_id,
            level=alert.level,
            message=alert.message,
            source_event_ids=alert.source_event_ids,
        ),
        source_events=sources,
    )
