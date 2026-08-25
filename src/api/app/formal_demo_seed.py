"""Apply formal demo health seeds inside the API process (synthetic only)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import register_account
from app.event_service import append_health_event_transaction
from app.formal_demo_plan import (
    CLASSROOM_SCENARIOS,
    FORMAL_CHILD_ACTOR_ID,
    FORMAL_CHILD_PASSWORD_DEFAULT,
    FORMAL_DEMO_HEALTH_EVENTS,
    FORMAL_DEMO_METRIC_EVENTS,
    FORMAL_DEMO_REMINDER_SPECS,
    FORMAL_GRANDMA_ACTOR_ID,
    FORMAL_GRANDPA_ACTOR_ID,
    FORMAL_HOUSEHOLD_NAME,
    FORMAL_OWNER_ACTOR_ID,
    expected_graph_labels,
)
from app.models import CareAuthorization, HealthEvent, Household, Member
from app.schemas import HealthEventCreate


def _ensure_member(
    session: Session,
    household: Household,
    *,
    display_name: str,
    actor_id: str,
    role: str = "DEPENDENT",
) -> Member:
    members = session.scalars(
        select(Member).where(Member.household_id == household.id)
    ).all()
    for member in members:
        if member.actor_id == actor_id or member.display_name == display_name:
            if not member.actor_id:
                member.actor_id = actor_id
                session.flush()
            return member
    member = Member(
        household_id=household.id,
        display_name=display_name,
        role=role,
        actor_id=actor_id,
    )
    session.add(member)
    session.flush()
    return member


def _append(
    session: Session,
    *,
    household: Household,
    member: Member,
    actor_id: str,
    event_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
) -> HealthEvent:
    return append_health_event_transaction(
        session,
        household=household,
        member=member,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        correlation_id=f"formal-demo-seed:{idempotency_key}",
        payload=HealthEventCreate(
            member_id=member.id,
            event_type=event_type,
            source="MANUAL",
            confirmation_status="CONFIRMED",
            payload=payload,
        ),
    )


def _event_by_idempotency(
    session: Session, household_id: str, key: str
) -> HealthEvent | None:
    return session.scalar(
        select(HealthEvent).where(
            HealthEvent.household_id == household_id,
            HealthEvent.idempotency_key == key,
        )
    )


def apply_formal_demo_seed(
    session: Session,
    *,
    actor_id: str,
    household: Household | None = None,
) -> dict[str, Any]:
    """Seed interconnected synthetic facts for the classroom household."""
    if household is None:
        household = session.scalar(
            select(Household).where(
                Household.name == FORMAL_HOUSEHOLD_NAME,
                Household.created_by == FORMAL_OWNER_ACTOR_ID,
            )
        )
        if household is None:
            household = session.scalar(
                select(Household).where(Household.name == FORMAL_HOUSEHOLD_NAME)
            )
        if household is None:
            household = Household(
                name=FORMAL_HOUSEHOLD_NAME,
                created_by=actor_id,
                time_zone="Asia/Shanghai",
            )
            session.add(household)
            session.flush()

    grandma = _ensure_member(
        session, household, display_name="奶奶", actor_id=FORMAL_GRANDMA_ACTOR_ID
    )
    grandpa = _ensure_member(
        session, household, display_name="爷爷", actor_id=FORMAL_GRANDPA_ACTOR_ID
    )
    members = {"grandma": grandma, "grandpa": grandpa}
    session.commit()

    created_ids: list[str] = []
    for spec in [*FORMAL_DEMO_HEALTH_EVENTS, *FORMAL_DEMO_METRIC_EVENTS]:
        event = _append(
            session,
            household=household,
            member=members[spec["member_key"]],
            actor_id=actor_id,
            event_type=spec["event_type"],
            payload=spec["payload"],
            idempotency_key=spec["idempotency_key"],
        )
        created_ids.append(event.id)

    for reminder in FORMAL_DEMO_REMINDER_SPECS:
        plan = _event_by_idempotency(
            session, household.id, reminder["plan_idempotency_key"]
        )
        if plan is None:
            continue
        member = members[reminder["member_key"]]
        for action in reminder["actions"]:
            payload = {
                "plan_event_id": plan.id,
                **(action.get("payload_extra") or {}),
            }
            event = _append(
                session,
                household=household,
                member=member,
                actor_id=actor_id,
                event_type=action["event_type"],
                payload=payload,
                idempotency_key=action["idempotency_key"],
            )
            created_ids.append(event.id)

    try:
        register_account(
            FORMAL_CHILD_ACTOR_ID, FORMAL_CHILD_PASSWORD_DEFAULT, session
        )
    except HTTPException as exc:
        if exc.status_code != 409:
            raise

    existing_auth = session.scalar(
        select(CareAuthorization).where(
            CareAuthorization.household_id == household.id,
            CareAuthorization.member_id == grandma.id,
            CareAuthorization.grantee_actor_id == FORMAL_CHILD_ACTOR_ID,
            CareAuthorization.revoked_at.is_(None),
        )
    )
    auth_id: str | None
    if existing_auth is None:
        now = datetime.now(UTC)
        auth = CareAuthorization(
            household_id=household.id,
            member_id=grandma.id,
            grantor_actor_id=actor_id,
            grantee_actor_id=FORMAL_CHILD_ACTOR_ID,
            data_fields=["health_events"],
            actions=["READ_EVENTS"],
            purpose="family-care",
            valid_from=now,
            valid_until=now + timedelta(days=30),
        )
        session.add(auth)
        session.commit()
        session.refresh(auth)
        auth_id = auth.id
    else:
        auth_id = existing_auth.id

    return {
        "ok": True,
        "household_id": household.id,
        "household_name": household.name,
        "members": {
            "grandma": {"id": grandma.id, "actor_id": grandma.actor_id},
            "grandpa": {"id": grandpa.id, "actor_id": grandpa.actor_id},
        },
        "events_touched": len(created_ids),
        "child_actor_id": FORMAL_CHILD_ACTOR_ID,
        "child_authorization_id": auth_id,
        "child_scope": {
            "member": "奶奶",
            "data_fields": ["health_events"],
            "actions": ["READ_EVENTS"],
            "note": "不包含爷爷；不含 risk_alerts，便于对照演示",
        },
        "scenarios": CLASSROOM_SCENARIOS,
        "expected_graph": {
            key: {kind: sorted(labels) for kind, labels in kinds.items()}
            for key, kinds in expected_graph_labels().items()
        },
        "disclaimer": "全部为虚构教学演示数据，禁止用于诊疗，不含真实健康信息。",
    }
