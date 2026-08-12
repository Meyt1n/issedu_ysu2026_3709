"""
HCT-304 & HCT-308: Plan versions, safety time windows, care confirmation and escalation.

Plans are versioned via append-only events. Safety windows prevent dosing too
early or too late. Confirmations, deferrals and skips are idempotent operations.
Timeout triggers automatic care-level escalation.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
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
