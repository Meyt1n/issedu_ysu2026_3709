from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import (
    CareAuthorization,
    HealthEvent,
    Household,
    Member,
    MemberStateProjection,
    OutboxMessage,
)
from app.schemas import (
    AuthorizationCreate,
    AuthorizationRead,
    CapabilityResponse,
    HealthEventCreate,
    HealthEventRead,
    HealthResponse,
    HouseholdCreate,
    HouseholdRead,
    MemberCreate,
    MemberRead,
    MemberStateRead,
)
from app.security import get_actor_id, has_authorized_action, require_household_owner

router = APIRouter(prefix="/api/v1")
settings = get_settings()


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
        ],
        unavailable=["vision", "ocr", "barcode", "rag", "llm", "weather"],
    )


@router.get("/households", response_model=list[HouseholdRead])
def list_households(
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> list[Household]:
    owned = session.scalars(
        select(Household).where(Household.created_by == actor_id)
    ).all()
    authorized_ids = session.scalars(
        select(CareAuthorization.household_id)
        .where(
            CareAuthorization.grantee_actor_id == actor_id,
            CareAuthorization.revoked_at.is_(None),
            CareAuthorization.valid_until > datetime.now(UTC),
        )
        .distinct()
    ).all()
    authorized = session.scalars(
        select(Household).where(Household.id.in_(authorized_ids))
    ).all()
    seen: set[str] = set()
    result: list[Household] = []
    for h in list(owned) + list(authorized):
        if h.id not in seen:
            seen.add(h.id)
            result.append(h)
    return result


@router.get("/households/{household_id}/members", response_model=list[MemberRead])
def list_members(
    household_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> list[Member]:
    household = session.get(Household, household_id)
    if household is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HOUSEHOLD_NOT_FOUND")
    if household.created_by == actor_id:
        query = select(Member).where(Member.household_id == household_id)
        return list(session.scalars(query).all())
    authorized_member_ids = session.scalars(
        select(CareAuthorization.member_id)
        .where(
            CareAuthorization.household_id == household_id,
            CareAuthorization.grantee_actor_id == actor_id,
            CareAuthorization.revoked_at.is_(None),
            CareAuthorization.valid_until > datetime.now(UTC),
        )
        .distinct()
    ).all()
    if not authorized_member_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="MEMBER_LIST_NOT_AUTHORIZED"
        )
    return list(
        session.scalars(
            select(Member).where(
                Member.id.in_(authorized_member_ids),
                Member.household_id == household_id,
            )
        ).all()
    )


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MEMBER_NOT_FOUND")
    valid_until = payload.valid_until
    if valid_until.tzinfo is None:
        valid_until = valid_until.replace(tzinfo=UTC)
    if valid_until <= datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="AUTHORIZATION_EXPIRED",
        )
    authorization = CareAuthorization(
        household_id=household.id,
        member_id=member.id,
        grantee_actor_id=payload.grantee_actor_id,
        data_fields=payload.data_fields,
        actions=payload.actions,
        purpose=payload.purpose,
        valid_from=datetime.now(UTC),
        valid_until=valid_until,
    )
    session.add(authorization)
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
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> CareAuthorization:
    household = require_household_owner(session, household_id, actor_id)
    authorization = session.get(CareAuthorization, authorization_id)
    if authorization is None or authorization.household_id != household.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AUTHORIZATION_NOT_FOUND")
    authorization.revoked_at = datetime.now(UTC)
    session.commit()
    session.refresh(authorization)
    return authorization


@router.post(
    "/households/{household_id}/events",
    response_model=HealthEventRead,
    status_code=status.HTTP_201_CREATED,
)
def append_health_event(
    household_id: str,
    payload: HealthEventCreate,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> HealthEvent:
    household = session.get(Household, household_id)
    if household is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HOUSEHOLD_NOT_FOUND")
    member = session.get(Member, payload.member_id)
    if member is None or member.household_id != household.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MEMBER_NOT_FOUND")
    if not has_authorized_action(
        session, household, member.id, actor_id, "WRITE_EVENTS", "health_events"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="EVENT_WRITE_NOT_AUTHORIZED"
        )

    event = HealthEvent(
        household_id=household.id,
        member_id=member.id,
        event_type=payload.event_type,
        source=payload.source,
        confirmation_status=payload.confirmation_status,
        payload=payload.payload,
        evidence=payload.evidence,
        created_by=actor_id,
        confirmed_by=actor_id,
    )
    session.add(event)
    session.flush()
    session.add(
        OutboxMessage(
            event_id=event.id,
            topic="health_event.created",
            payload={"event_id": event.id, "household_id": household.id, "member_id": member.id},
        )
    )
    projection = session.get(MemberStateProjection, member.id)
    if projection is None:
        projection = MemberStateProjection(
            member_id=member.id,
            household_id=household.id,
            state={},
        )
        session.add(projection)
    current_state = dict(projection.state or {})
    current_state["last_event_type"] = event.event_type
    current_state["last_event_payload"] = event.payload
    current_state["events_count"] = int(current_state.get("events_count", 0)) + 1
    projection.state = current_state
    projection.last_event_id = event.id
    projection.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(event)
    return event


@router.get("/households/{household_id}/events", response_model=list[HealthEventRead])
def list_health_events(
    household_id: str,
    member_id: str | None = None,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> list[HealthEvent]:
    household = session.get(Household, household_id)
    if household is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HOUSEHOLD_NOT_FOUND")
    members = session.scalars(select(Member).where(Member.household_id == household.id)).all()
    allowed_member_ids = {
        member.id
        for member in members
        if has_authorized_action(
            session, household, member.id, actor_id, "READ_EVENTS", "health_events"
        )
    }
    if member_id is not None and member_id not in allowed_member_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="EVENT_READ_NOT_AUTHORIZED"
        )
    if member_id is None and household.created_by != actor_id and not allowed_member_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="EVENT_READ_NOT_AUTHORIZED"
        )
    query = select(HealthEvent).where(HealthEvent.household_id == household.id)
    if household.created_by != actor_id:
        query = query.where(HealthEvent.member_id.in_(allowed_member_ids))
    elif member_id is not None:
        query = query.where(HealthEvent.member_id == member_id)
    return list(session.scalars(query.order_by(HealthEvent.created_at)).all())


@router.get(
    "/households/{household_id}/members/{member_id}/state",
    response_model=MemberStateRead,
)
def read_member_state(
    household_id: str,
    member_id: str,
    actor_id: str = Depends(get_actor_id),
    session: Session = Depends(get_session),
) -> MemberStateProjection:
    household = session.get(Household, household_id)
    member = session.get(Member, member_id)
    if household is None or member is None or member.household_id != household_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MEMBER_NOT_FOUND")
    if not has_authorized_action(
        session, household, member_id, actor_id, "READ_EVENTS", "health_events"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="STATE_READ_NOT_AUTHORIZED"
        )
    projection = session.get(MemberStateProjection, member_id)
    if projection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="STATE_NOT_FOUND")
    return projection
