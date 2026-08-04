from datetime import UTC, datetime

from fastapi import Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import CareAuthorization, Household


def get_actor_id(x_actor_id: str | None = Header(default=None)) -> str:
    settings = get_settings()
    if settings.app_env == "production" or not settings.allow_dev_actor_header:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="REAL_AUTH_REQUIRED",
        )
    if not x_actor_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="ACTOR_REQUIRED")
    return x_actor_id


def require_household_owner(session: Session, household_id: str, actor_id: str) -> Household:
    household = session.get(Household, household_id)
    if household is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HOUSEHOLD_NOT_FOUND")
    if household.created_by != actor_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="OWNER_REQUIRED")
    return household


def has_authorized_action(
    session: Session,
    household: Household,
    member_id: str,
    actor_id: str,
    action: str,
    data_field: str,
) -> bool:
    if household.created_by == actor_id:
        return True

    now = datetime.now(UTC)
    authorizations = session.scalars(
        select(CareAuthorization).where(
            CareAuthorization.household_id == household.id,
            CareAuthorization.member_id == member_id,
            CareAuthorization.grantee_actor_id == actor_id,
            CareAuthorization.revoked_at.is_(None),
        )
    ).all()
    for authorization in authorizations:
        valid_from = authorization.valid_from
        valid_until = authorization.valid_until
        if valid_from.tzinfo is None:
            valid_from = valid_from.replace(tzinfo=UTC)
        if valid_until.tzinfo is None:
            valid_until = valid_until.replace(tzinfo=UTC)
        if (
            valid_from <= now < valid_until
            and action in authorization.actions
            and data_field in authorization.data_fields
        ):
            return True
    return False
