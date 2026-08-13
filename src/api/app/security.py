import re
from datetime import UTC, datetime

from fastapi import Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AccessAudit, CareAuthorization, Household, Member

PURPOSE_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


def get_actor_id(x_actor_id: str | None = Header(default=None)) -> str:
    settings = get_settings()
    if settings.app_env == "production" or not settings.allow_dev_actor_header:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="REAL_AUTH_REQUIRED",
        )
    if not x_actor_id or len(x_actor_id) > 120:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="ACTOR_REQUIRED")
    return x_actor_id


def get_access_purpose(
    x_access_purpose: str | None = Header(default=None, alias="X-Access-Purpose"),
) -> str | None:
    if x_access_purpose is None:
        return None
    purpose = x_access_purpose.strip()
    return purpose if PURPOSE_CODE.fullmatch(purpose) else None


def require_household_owner(
    session: Session,
    household_id: str,
    actor_id: str,
    *,
    allow_deleted: bool = False,
) -> Household:
    household = session.get(Household, household_id)
    if household is None or household.created_by != actor_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RESOURCE_NOT_FOUND")
    if household.deleted_at is not None and not allow_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RESOURCE_NOT_FOUND")
    return household


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _record_access_decision(
    session: Session,
    *,
    household_id: str,
    authorization_id: str | None,
    actor_id: str,
    action: str,
    data_field: str,
    purpose: str | None,
    outcome: str,
    reason: str | None,
) -> None:
    session.add(
        AccessAudit(
            household_id=household_id,
            authorization_id=authorization_id,
            actor_id=actor_id,
            operation="ACCESS",
            action=action,
            data_field=data_field,
            purpose=purpose,
            outcome=outcome,
            reason=reason,
        )
    )
    # Access checks run before any business mutation. Persisting the decision here ensures
    # denied requests are not lost when the request session closes without a later commit.
    session.commit()


def has_authorized_action(
    session: Session,
    household: Household,
    member_id: str,
    actor_id: str,
    action: str,
    data_field: str,
    purpose: str | None = None,
) -> bool:
    # P0 管理边界：家庭 owner 是家庭管理员，可访问本家庭的成员目录和健康事实；
    # 非 owner 照护者必须同时满足成员、字段、动作和有效期授权。子女身份本身不等于 owner。
    if household.deleted_at is not None:
        return False
    member = session.get(Member, member_id)
    if member is None or member.household_id != household.id or member.deleted_at is not None:
        return False
    if household.created_by == actor_id:
        return True

    now = datetime.now(UTC)
    authorizations = session.scalars(
        select(CareAuthorization).where(
            CareAuthorization.household_id == household.id,
            CareAuthorization.member_id == member_id,
            CareAuthorization.grantee_actor_id == actor_id,
        )
    ).all()
    denied_reason = "AUTHORIZATION_NOT_FOUND"
    denied_authorization_id: str | None = None
    for authorization in authorizations:
        denied_authorization_id = authorization.id
        if authorization.revoked_at is not None:
            denied_reason = "CONSENT_REVOKED"
            continue
        if _as_utc(authorization.valid_from) > now:
            denied_reason = "AUTHORIZATION_NOT_ACTIVE"
            continue
        if _as_utc(authorization.valid_until) <= now:
            denied_reason = "AUTHORIZATION_EXPIRED"
            continue
        if action not in (authorization.actions or []):
            denied_reason = "ACTION_NOT_GRANTED"
            continue
        if data_field not in (authorization.data_fields or []):
            denied_reason = "FIELD_NOT_GRANTED"
            continue
        if purpose is None:
            denied_reason = "PURPOSE_REQUIRED"
            continue
        if authorization.purpose != purpose:
            denied_reason = "PURPOSE_MISMATCH"
            continue
        _record_access_decision(
            session,
            household_id=household.id,
            authorization_id=authorization.id,
            actor_id=actor_id,
            action=action,
            data_field=data_field,
            purpose=purpose,
            outcome="ALLOWED",
            reason=None,
        )
        return True
    _record_access_decision(
        session,
        household_id=household.id,
        authorization_id=denied_authorization_id,
        actor_id=actor_id,
        action=action,
        data_field=data_field,
        purpose=purpose,
        outcome="DENIED",
        reason=denied_reason,
    )
    return False
