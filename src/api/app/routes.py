from datetime import UTC, datetime, timedelta
from typing import NoReturn

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

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
from app.models import (
    AccessAudit,
    CareAuthorization,
    HealthEvent,
    Household,
    Member,
    MemberStateProjection,
    OutboxMessage,
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
    MemberCreate,
    MemberRead,
    MemberStateRead,
    OutboxDispatchRead,
    OutboxDispatchRequest,
    OutboxRead,
    ProjectionCheckpointRead,
    ProjectionReplayRead,
    ProjectionReplayRequest,
)
from app.security import (
    get_access_purpose,
    get_actor_id,
    has_authorized_action,
    require_household_owner,
)

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
        ],
        unavailable=["vision", "ocr", "barcode", "rag", "llm", "weather"],
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

    try:
        return append_health_event_transaction(
            session,
            household=household,
            member=member,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            correlation_id=request.state.request_id,
            payload=payload,
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        if str(exc) == "IDEMPOTENCY_KEY_INVALID":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
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
            correlation_id=request.state.request_id,
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
