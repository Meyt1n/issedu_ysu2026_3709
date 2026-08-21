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

from fastapi import HTTPException, status

from app.models import HealthEvent

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
        local_date = proposed.astimezone().date()
        confirmations_today = sum(
            _as_utc(event.occurred_at).astimezone().date() == local_date
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
        current = proposed.astimezone().time().replace(second=0, microsecond=0)
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
) -> datetime:
    """Use explicit local clock times when available, otherwise keep HCT-304's 24h fallback."""
    times = _parse_plan_times(payload.get("times"))
    if not times:
        return reference_time + timedelta(hours=DEFAULT_MAX_INTERVAL_HOURS)

    local_now = now.astimezone()
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


def build_plan_workbench(events: list[HealthEvent]) -> list[dict[str, Any]]:
    """Build a read-only, server-authoritative plan workbench from confirmed events."""
    compensated = {
        event.compensates_event_id
        for event in events
        if event.event_type == "COMPENSATION" and event.compensates_event_id
    }
    actions_by_plan: dict[str, list[HealthEvent]] = {}
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
            continue
        plan_event_id = str((event.payload or {}).get("plan_event_id") or "")
        if plan_event_id:
            actions_by_plan.setdefault(plan_event_id, []).append(event)

    def as_utc(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    now = datetime.now(UTC)
    workbench: list[dict[str, Any]] = []
    for plan in plans:
        payload = plan.payload or {}
        action_history = actions_by_plan.get(plan.id, [])
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

        due_at = deferred_until or _next_action_at(payload, reference_time=reference_time, now=now)
        if now < due_at:
            status_label = "NORMAL"
        elif now < due_at + timedelta(hours=GRACE_PERIOD_HOURS):
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
                "allowed_actions": ["CONFIRM", "DEFER", "SKIP", "MISS"],
            }
        )
    return workbench


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
