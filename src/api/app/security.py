import re
from datetime import UTC, datetime

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import validate_session
from app.config import get_settings
from app.db import get_session
from app.models import AccessAudit, CareAuthorization, Household, Member
from app.request_context import current_request_id

PURPOSE_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
# STRIDE S-01 mitigation: the development identity header must carry a
# well-formed actor id.  This blocks whitespace/control characters and other
# log-injection material and matches the ACTOR_ID_PATTERN already enforced
# when binding member accounts.
ACTOR_ID_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")


def get_actor_id(
    x_actor_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> str:
    if authorization is not None:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="AUTH_REQUIRED")
        return validate_session(token.strip(), session)

    settings = get_settings()
    if settings.app_env == "production" or not settings.allow_dev_actor_header:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="REAL_AUTH_REQUIRED",
        )
    if not x_actor_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="ACTOR_REQUIRED")
    if not ACTOR_ID_CODE.fullmatch(x_actor_id):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="ACTOR_ID_INVALID")
    return x_actor_id


def require_session_token(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> str:
    """Return the caller's live session token.

    HCT-427: step-up confirmation and session revalidation must be tied to a real
    server session, so the development ``X-Actor-Id`` path is deliberately not
    accepted here even when it is enabled for business endpoints.
    """
    if authorization is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="SESSION_REQUIRED",
        )
    scheme, _, raw_token = authorization.partition(" ")
    token = raw_token.strip()
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="AUTH_REQUIRED")
    validate_session(token, session)
    return token


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
            request_id=current_request_id(),
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


def is_self_member(
    session: Session,
    household: Household,
    member_id: str,
    actor_id: str,
) -> bool:
    """Return whether the caller is the household member represented by ``member_id``.

    A member account is allowed to see its own member context, but this must not
    silently become a general household authorization.  The portal uses this
    narrow identity check for self-service reads and for submitting a photo to
    the review queue; health-event writes remain owner/authorization scoped.
    """
    if household.deleted_at is not None:
        return False
    member = session.get(Member, member_id)
    return bool(
        member is not None
        and member.household_id == household.id
        and member.deleted_at is None
        and member.actor_id == actor_id
    )


def has_member_read_access(
    session: Session,
    household: Household,
    member_id: str,
    actor_id: str,
    purpose: str | None = None,
) -> bool:
    """Allow an account to read its own scope without granting family-wide access."""
    if household.created_by == actor_id:
        return True
    if is_self_member(session, household, member_id, actor_id):
        _record_access_decision(
            session,
            household_id=household.id,
            authorization_id=None,
            actor_id=actor_id,
            action="READ_EVENTS",
            data_field="health_events",
            purpose=purpose,
            outcome="ALLOWED",
            reason="SELF_MEMBER_SCOPE",
        )
        return True
    return has_authorized_action(
        session,
        household,
        member_id,
        actor_id,
        "READ_EVENTS",
        "health_events",
        purpose,
    )


def has_vision_capture_access(
    session: Session,
    household: Household,
    member_id: str,
    actor_id: str,
    purpose: str | None = None,
) -> bool:
    """Allow a member to submit evidence for their own review queue only."""
    if household.created_by == actor_id:
        return True
    if is_self_member(session, household, member_id, actor_id):
        _record_access_decision(
            session,
            household_id=household.id,
            authorization_id=None,
            actor_id=actor_id,
            action="WRITE_EVIDENCE",
            data_field="vision_evidence",
            purpose=purpose,
            outcome="ALLOWED",
            reason="SELF_MEMBER_CAPTURE",
        )
        return True
    return has_authorized_action(
        session,
        household,
        member_id,
        actor_id,
        "WRITE_EVENTS",
        "health_events",
        purpose,
    )
