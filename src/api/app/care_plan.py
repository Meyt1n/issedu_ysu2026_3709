"""
HCT-304 & HCT-308: Plan versions, safety time windows, care confirmation and escalation.

Plans are versioned via append-only events. Safety windows prevent dosing too
early or too late. Confirmations, deferrals and skips are idempotent operations.
Timeout triggers automatic care-level escalation.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from datetime import time as clock_time
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.event_service import append_health_event_transaction
from app.models import CareAuthorization, HealthEvent, Household, Member
from app.schemas import HealthEventCreate

logger = logging.getLogger(__name__)

# ── Safety windows ─────────────────────────────────────────────────

DEFAULT_MIN_INTERVAL_HOURS = 4  # minimum hours between doses
DEFAULT_MAX_INTERVAL_HOURS = 24  # max before reminder
GRACE_PERIOD_HOURS = 2  # grace period after due time before escalation


def validate_safety_window(
    last_dose_time: datetime | None,
    proposed_time: datetime,
    min_interval: int = DEFAULT_MIN_INTERVAL_HOURS,
) -> None:
    """Reject if proposed_time violates the minimum interval since last dose."""
    if last_dose_time is None:
        return
    min_next = last_dose_time + timedelta(hours=min_interval)
    if proposed_time < min_next:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="TIME_WINDOW_VIOLATION",
        )


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _policy_value(payload: dict[str, Any], key: str) -> Any:
    policy = payload.get("safety_window")
    if isinstance(policy, dict) and key in policy:
        return policy[key]
    return payload.get(key)


def _positive_int(value: Any, *, default: int | None = None) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def validate_plan_confirmation_window(
    events: list[HealthEvent],
    plan_event_id: str,
    proposed_time: datetime,
    *,
    time_zone: str = "UTC",
) -> None:
    """Validate a confirmation against the plan's server-side safety policy.

    The policy is optional for backwards-compatible plan events.  It can be
    supplied either under ``payload.safety_window`` or as the documented
    top-level payload keys.  The endpoint must call this function before it
    appends a confirmation; the helper deliberately delegates the minimum
    interval check to :func:`validate_safety_window`.
    """
    plan = next(
        (
            event
            for event in events
            if event.id == plan_event_id
            and event.event_type in {"plan_created", "plan_updated"}
        ),
        None,
    )
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PLAN_NOT_FOUND",
        )

    proposed = _as_utc(proposed_time)
    zone = ZoneInfo(time_zone)
    payload = plan.payload or {}
    minimum_hours = _positive_int(
        _policy_value(payload, "min_interval_hours"),
        default=DEFAULT_MIN_INTERVAL_HOURS,
    )
    confirmations = [
        event
        for event in events
        if event.event_type == "plan_confirmed"
        and str((event.payload or {}).get("plan_event_id") or "") == plan_event_id
    ]
    last_confirmation = max(
        (_as_utc(event.occurred_at) for event in confirmations),
        default=None,
    )
    validate_safety_window(last_confirmation, proposed, min_interval=minimum_hours or 0)

    maximum_daily = _positive_int(_policy_value(payload, "max_daily_doses"))
    if maximum_daily is not None:
        local_date = proposed.astimezone(zone).date()
        confirmations_today = sum(
            _as_utc(event.occurred_at).astimezone(zone).date() == local_date
            for event in confirmations
        )
        if confirmations_today >= maximum_daily:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="TIME_WINDOW_VIOLATION",
            )

    earliest_raw = _policy_value(payload, "earliest_time")
    latest_raw = _policy_value(payload, "latest_time")
    earliest_values = _parse_plan_times([earliest_raw]) if earliest_raw else []
    latest_values = _parse_plan_times([latest_raw]) if latest_raw else []
    earliest = earliest_values[0] if earliest_values else None
    latest = latest_values[0] if latest_values else None
    if earliest is not None or latest is not None:
        current = proposed.astimezone(zone).time().replace(second=0, microsecond=0)
        outside = False
        if earliest is not None and latest is not None:
            if earliest <= latest:
                outside = current < earliest or current > latest
            else:
                # A window such as 22:00–06:00 crosses midnight.
                outside = latest < current < earliest
        elif earliest is not None:
            outside = current < earliest
        else:
            outside = current > latest
        if outside:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="TIME_WINDOW_VIOLATION",
            )


# ── Plan event helpers ─────────────────────────────────────────────

def record_plan_event(
    member_id: str,
    household_id: str,
    event_type: str,
    payload: dict[str, Any],
    created_by: str,
    idempotency_key: str | None = None,
    compensates_event_id: str | None = None,
) -> HealthEvent:
    """Create a plan-related health event (returns unsaved)."""
    return HealthEvent(
        household_id=household_id,
        member_id=member_id,
        event_type=event_type,
        source="MANUAL",
        confirmation_status="CONFIRMED",
        payload=payload,
        created_by=created_by,
        confirmed_by=created_by,
        idempotency_key=idempotency_key,
        compensates_event_id=compensates_event_id,
    )


# ── Escalation ─────────────────────────────────────────────────────

def check_escalation(
    plan_created_at: datetime,
    last_confirmed_at: datetime | None,
    interval_hours: int = DEFAULT_MAX_INTERVAL_HOURS,
    grace_hours: int = GRACE_PERIOD_HOURS,
) -> str:
    """Return the care level: 'normal', 'reminder', or 'escalated'."""
    now = datetime.now(UTC)
    if last_confirmed_at is None:
        due = plan_created_at + timedelta(hours=interval_hours)
    else:
        due = last_confirmed_at + timedelta(hours=interval_hours)

    if now < due:
        return "normal"
    if now < due + timedelta(hours=grace_hours):
        return "reminder"
    return "escalated"


def _parse_plan_times(raw: Any) -> list[clock_time]:
    values = raw if isinstance(raw, list) else str(raw or "").replace("，", ",").split(",")
    result: list[clock_time] = []
    for value in values:
        text = str(value).strip()
        try:
            parsed = datetime.strptime(text, "%H:%M").time()
        except ValueError:
            continue
        if parsed not in result:
            result.append(parsed)
    return sorted(result)


def _parse_plan_date(raw: Any) -> date | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        return None


def _next_action_at(
    payload: dict[str, Any],
    *,
    reference_time: datetime,
    now: datetime,
    time_zone: str,
) -> datetime:
    """Use explicit local clock times when available, otherwise keep HCT-304's 24h fallback."""
    times = _parse_plan_times(payload.get("times"))
    if not times:
        return reference_time + timedelta(hours=DEFAULT_MAX_INTERVAL_HOURS)

    zone = ZoneInfo(time_zone)
    local_now = now.astimezone(zone)
    start_date = _parse_plan_date(payload.get("start_date"))
    end_date = _parse_plan_date(payload.get("end_date"))
    lower_bound = max(reference_time, now)
    for offset in range(0, 8):
        candidate_date = local_now.date() + timedelta(days=offset)
        if start_date is not None and candidate_date < start_date:
            continue
        if end_date is not None and candidate_date > end_date:
            continue
        for scheduled_time in times:
            candidate = datetime.combine(candidate_date, scheduled_time, tzinfo=local_now.tzinfo)
            candidate_utc = candidate.astimezone(UTC)
            if candidate_utc > lower_bound:
                return candidate_utc
    return reference_time + timedelta(hours=DEFAULT_MAX_INTERVAL_HOURS)


def build_plan_workbench(
    events: list[HealthEvent],
    *,
    time_zone: str = "UTC",
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Build a read-only, server-authoritative plan workbench from confirmed events."""
    compensated = {
        event.compensates_event_id
        for event in events
        if event.event_type == "COMPENSATION" and event.compensates_event_id
    }
    actions_by_plan: dict[str, list[HealthEvent]] = {}
    lifecycle_by_plan: dict[str, list[HealthEvent]] = {}
    plans: list[HealthEvent] = []

    for event in events:
        if event.id in compensated:
            continue
        if event.event_type in {"plan_created", "plan_updated"}:
            plans.append(event)
            continue
        if event.event_type not in {
            "plan_confirmed",
            "plan_deferred",
            "plan_skipped",
            "plan_missed",
        }:
            if event.event_type not in {
                "course_ended",
                "plan_completed",
                "care_escalated",
                "care_level_escalated",
            }:
                continue
            plan_event_id = str((event.payload or {}).get("plan_event_id") or "")
            if plan_event_id:
                lifecycle_by_plan.setdefault(plan_event_id, []).append(event)
            continue
        plan_event_id = str((event.payload or {}).get("plan_event_id") or "")
        if plan_event_id:
            actions_by_plan.setdefault(plan_event_id, []).append(event)

    def as_utc(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    current_time = _as_utc(now or datetime.now(UTC))
    local_today = current_time.astimezone(ZoneInfo(time_zone)).date()
    workbench: list[dict[str, Any]] = []
    for plan in plans:
        payload = plan.payload or {}
        action_history = sorted(actions_by_plan.get(plan.id, []), key=lambda item: item.occurred_at)
        lifecycle = sorted(lifecycle_by_plan.get(plan.id, []), key=lambda item: item.occurred_at)
        last_action = action_history[-1] if action_history else None
        reference_time = as_utc(plan.occurred_at)
        deferred_until: datetime | None = None
        if last_action is not None:
            action_payload = last_action.payload or {}
            if last_action.event_type == "plan_deferred":
                delay_hours = int(action_payload.get("delay_hours") or 0)
                deferred_until = as_utc(last_action.occurred_at) + timedelta(hours=delay_hours)
            else:
                reference_time = as_utc(last_action.occurred_at)

        due_at = deferred_until or _next_action_at(
            payload,
            reference_time=reference_time,
            now=current_time,
            time_zone=time_zone,
        )
        completed = next(
            (
                item
                for item in reversed(lifecycle)
                if item.event_type in {"course_ended", "plan_completed"}
            ),
            None,
        )
        escalated = next(
            (
                item
                for item in reversed(lifecycle)
                if item.event_type in {"care_escalated", "care_level_escalated"}
                and (
                    last_action is None
                    or _as_utc(item.occurred_at) >= _as_utc(last_action.occurred_at)
                )
            ),
            None,
        )
        configured_end = _parse_plan_date(payload.get("end_date"))
        if completed is not None or (configured_end is not None and configured_end < local_today):
            status_label = "COMPLETED"
        elif escalated is not None:
            status_label = "ESCALATED"
        elif current_time < due_at:
            status_label = "NORMAL"
        elif current_time < due_at + timedelta(hours=GRACE_PERIOD_HOURS):
            status_label = "REMINDER"
        else:
            status_label = "ESCALATED"

        workbench.append(
            {
                "plan_event_id": plan.id,
                "drug": str(payload.get("drug") or "未命名药品"),
                "schedule": str(payload.get("schedule") or "未填写安排"),
                "dose": str(payload.get("dose")) if payload.get("dose") else None,
                "times": [str(item) for item in payload.get("times", [])]
                if isinstance(payload.get("times"), list)
                else [],
                "start_date": payload.get("start_date"),
                "end_date": payload.get("end_date"),
                "status": status_label,
                "next_action_at": due_at,
                "last_action": None
                if last_action is None
                else {
                    "action": {
                        "plan_confirmed": "CONFIRM",
                        "plan_deferred": "DEFER",
                        "plan_skipped": "SKIP",
                        "plan_missed": "MISS",
                    }[last_action.event_type],
                    "recorded_at": last_action.occurred_at,
                    "reason": (last_action.payload or {}).get("reason"),
                    "delay_hours": (last_action.payload or {}).get("delay_hours"),
                },
                "action_history": [
                    {
                        "action": {
                            "plan_confirmed": "CONFIRM",
                            "plan_deferred": "DEFER",
                            "plan_skipped": "SKIP",
                            "plan_missed": "MISS",
                        }[event.event_type],
                        "recorded_at": event.occurred_at,
                        "reason": (event.payload or {}).get("reason"),
                        "delay_hours": (event.payload or {}).get("delay_hours"),
                    }
                    for event in action_history
                ],
                "allowed_actions": []
                if status_label == "COMPLETED"
                else ["CONFIRM", "DEFER", "SKIP", "MISS"],
            }
        )
    return workbench


def plan_automation_decisions(
    events: list[HealthEvent],
    *,
    time_zone: str,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return authorized lifecycle transitions without writing data.

    The caller persists these decisions transactionally. Plans without an
    explicit automation authorization are intentionally ignored.
    """
    current_time = _as_utc(now or datetime.now(UTC))
    plan_events = {
        event.id: event
        for event in events
        if event.event_type in {"plan_created", "plan_updated"}
    }
    existing_keys = {
        str((event.payload or {}).get("automation_key") or "")
        for event in events
        if (event.payload or {}).get("automation_key")
    }
    decisions: list[dict[str, Any]] = []
    for item in build_plan_workbench(events, time_zone=time_zone, now=current_time):
        plan = plan_events[item["plan_event_id"]]
        payload = plan.payload or {}
        automation = payload.get("automation")
        if not isinstance(automation, dict) or automation.get("authorization") != "AUTHORIZED":
            continue
        if item["status"] == "COMPLETED":
            key = f"course-end:{plan.id}:{payload.get('end_date') or 'unspecified'}"
            if key not in existing_keys:
                decisions.append(
                    {
                        "event_type": "course_ended",
                        "plan_event_id": plan.id,
                        "automation_key": key,
                        "occurred_at": current_time,
                        "reason": "COURSE_END_DATE_REACHED",
                    }
                )
            continue
        due_at = _as_utc(item["next_action_at"])
        if (
            item["status"] != "ESCALATED"
            or current_time < due_at + timedelta(hours=GRACE_PERIOD_HOURS)
        ):
            continue
        slot = due_at.strftime("%Y%m%dT%H%MZ")
        missed_key = f"missed:{plan.id}:{slot}"
        escalation_key = f"escalated:{plan.id}:{slot}"
        if missed_key not in existing_keys:
            decisions.append(
                {
                    "event_type": "plan_missed",
                    "plan_event_id": plan.id,
                    "automation_key": missed_key,
                    "occurred_at": current_time,
                    "reason": "OVERDUE_AFTER_GRACE_PERIOD",
                    "due_at": due_at,
                }
            )
        if escalation_key not in existing_keys:
            decisions.append(
                {
                    "event_type": "care_escalated",
                    "plan_event_id": plan.id,
                    "automation_key": escalation_key,
                    "occurred_at": current_time,
                    "reason": "MISSED_DOSE_ESCALATION",
                    "due_at": due_at,
                    "notify_caregivers": isinstance(payload.get("caregiver_notification"), dict)
                    and payload["caregiver_notification"].get("authorization") == "AUTHORIZED",
                }
            )
    return decisions


def execute_plan_automation(
    session: Session,
    *,
    household: Household,
    member: Member,
    actor_id: str,
    correlation_id: str,
    now: datetime | None = None,
) -> tuple[list[HealthEvent], list[str]]:
    """Persist one idempotent, explicitly authorized automation cycle."""
    from app.projection import get_timeline

    evaluated_at = _as_utc(now or datetime.now(UTC))
    decisions = plan_automation_decisions(
        get_timeline(session, member.id),
        time_zone=household.time_zone,
        now=evaluated_at,
    )
    created_events: list[HealthEvent] = []
    notified_actor_ids: list[str] = []

    def append_once(
        *,
        event_type: str,
        payload: dict[str, object],
        automation_key: str,
        occurred_at: datetime,
    ) -> HealthEvent | None:
        idempotency_key = f"hct308:{automation_key}"
        existing = session.scalar(
            select(HealthEvent).where(
                HealthEvent.household_id == household.id,
                HealthEvent.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return None
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
                payload={**payload, "automation_key": automation_key},
                occurred_at=occurred_at,
            ),
        )

    for decision in decisions:
        automation_key = str(decision["automation_key"])
        event_payload: dict[str, object] = {
            "plan_event_id": str(decision["plan_event_id"]),
            "reason": str(decision["reason"]),
            "evaluated_at": evaluated_at.isoformat(),
        }
        due_at = decision.get("due_at")
        if isinstance(due_at, datetime):
            event_payload["due_at"] = due_at.isoformat()
        created = append_once(
            event_type=str(decision["event_type"]),
            payload=event_payload,
            automation_key=automation_key,
            occurred_at=decision["occurred_at"],
        )
        if created is not None:
            created_events.append(created)

        if decision.get("notify_caregivers") is not True:
            continue
        authorizations = session.scalars(
            select(CareAuthorization).where(
                CareAuthorization.household_id == household.id,
                CareAuthorization.member_id == member.id,
                CareAuthorization.revoked_at.is_(None),
            )
        ).all()
        for authorization in authorizations:
            valid_from = _as_utc(authorization.valid_from)
            valid_until = _as_utc(authorization.valid_until)
            if not (valid_from <= evaluated_at <= valid_until):
                continue
            if "health_events" not in authorization.data_fields:
                continue
            if "READ_EVENTS" not in authorization.actions:
                continue
            notify_key = f"notified:{automation_key}:{authorization.id}"
            notification = append_once(
                event_type="caregiver_notified",
                payload={
                    "plan_event_id": str(decision["plan_event_id"]),
                    "escalation_automation_key": automation_key,
                    "recipient_actor_id": authorization.grantee_actor_id,
                    "authorization_id": authorization.id,
                    "channel": "LOCAL_EVENT_INBOX",
                    "delivery_status": "QUEUED",
                },
                automation_key=notify_key,
                occurred_at=evaluated_at,
            )
            if notification is not None:
                created_events.append(notification)
                notified_actor_ids.append(authorization.grantee_actor_id)

    return created_events, sorted(set(notified_actor_ids))


# ── Confirmation actions ───────────────────────────────────────────

def confirm_plan(
    member_id: str,
    household_id: str,
    plan_event_id: str,
    actor_id: str,
) -> HealthEvent:
    """Confirm a plan as taken on time."""
    return record_plan_event(
        member_id, household_id, "plan_confirmed",
        {"plan_event_id": plan_event_id, "confirmed_at": datetime.now(UTC).isoformat()},
        actor_id,
        idempotency_key=f"confirm:{plan_event_id}",
    )


def defer_plan(
    member_id: str,
    household_id: str,
    plan_event_id: str,
    delay_hours: int,
    actor_id: str,
) -> HealthEvent:
    """Defer a plan by *delay_hours* hours."""
    return record_plan_event(
        member_id, household_id, "plan_deferred",
        {"plan_event_id": plan_event_id, "delay_hours": delay_hours,
         "deferred_at": datetime.now(UTC).isoformat()},
        actor_id,
        idempotency_key=f"defer:{plan_event_id}",
    )


def skip_plan(
    member_id: str,
    household_id: str,
    plan_event_id: str,
    reason: str,
    actor_id: str,
) -> HealthEvent:
    """Skip a plan dose with a reason."""
    return record_plan_event(
        member_id, household_id, "plan_skipped",
        {"plan_event_id": plan_event_id, "reason": reason,
         "skipped_at": datetime.now(UTC).isoformat()},
        actor_id,
        idempotency_key=f"skip:{plan_event_id}",
    )


def miss_plan(
    member_id: str,
    household_id: str,
    plan_event_id: str,
    reason: str,
    actor_id: str,
) -> HealthEvent:
    """Record a missed dose separately from an intentional skip."""
    return record_plan_event(
        member_id, household_id, "plan_missed",
        {
            "plan_event_id": plan_event_id,
            "reason": reason,
            "missed_at": datetime.now(UTC).isoformat(),
        },
        actor_id,
        idempotency_key=f"miss:{plan_event_id}:{datetime.now(UTC).date().isoformat()}",
    )
