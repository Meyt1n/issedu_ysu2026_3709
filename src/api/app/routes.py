import logging
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
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
from app.file_upload import delete_file_tree, validate_and_store
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
    HealthEventCreate,
    HealthEventRead,
    HealthResponse,
    HouseholdCreate,
    HouseholdRead,
    MemberCreate,
    MemberRead,
    MemberStateRead,
    RiskAlertRead,
    RiskDetailResponse,
    RiskListResponse,
)
from app.security import (
    get_access_purpose,
    get_actor_id,
    has_authorized_action,
    require_household_owner,
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
    actor_id: str = Depends(get_actor_id),
    access_purpose: str | None = Depends(get_access_purpose),
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

    # ── HCT-103: 幂等键去重 ──────────────────────────────────
    if payload.idempotency_key is not None:
        existing = session.scalars(
            select(HealthEvent).where(
                HealthEvent.idempotency_key == payload.idempotency_key
            )
        ).first()
        if existing is not None:
            if (
                existing.event_type != payload.event_type
                or existing.payload != payload.payload
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="IDEMPOTENCY_CONFLICT",
                )
            return existing

    # ── HCT-103: 补偿事件校验 ────────────────────────────────
    compensates_event = None
    if payload.compensates_event_id is not None:
        compensates_event = session.get(HealthEvent, payload.compensates_event_id)
        if compensates_event is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="COMPENSATES_EVENT_NOT_FOUND",
            )
        if compensates_event.household_id != household.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="COMPENSATES_EVENT_WRONG_HOUSEHOLD",
            )

    is_confirmed = payload.confirmation_status == "CONFIRMED"
    event = HealthEvent(
        household_id=household.id,
        member_id=member.id,
        event_type=payload.event_type,
        source=payload.source,
        confirmation_status=payload.confirmation_status,
        payload=payload.payload,
        evidence=payload.evidence,
        created_by=actor_id,
        confirmed_by=actor_id if is_confirmed else None,
        idempotency_key=payload.idempotency_key,
        compensates_event_id=payload.compensates_event_id,
    )
    session.add(event)
    session.flush()
    session.add(
        OutboxMessage(
            event_id=event.id,
            topic="health_event.created" if is_confirmed else "health_event.pending",
            payload={
                "event_id": event.id,
                "household_id": household.id,
                "member_id": member.id,
                "confirmation_status": event.confirmation_status,
            },
        )
    )
    if is_confirmed:
        projection = session.get(MemberStateProjection, member.id)
        if projection is None:
            projection = MemberStateProjection(
                member_id=member.id,
                household_id=household.id,
                state={},
            )
            session.add(projection)
        current_state = dict(projection.state or {})
        # HCT-103: 补偿事件覆写投影中对应字段，保留原始事件链
        if compensates_event is not None:
            current_state["compensated_event_id"] = compensates_event.id
            current_state["compensated_event_type"] = compensates_event.event_type
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
    return list(session.scalars(query.order_by(HealthEvent.created_at)).all())


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
