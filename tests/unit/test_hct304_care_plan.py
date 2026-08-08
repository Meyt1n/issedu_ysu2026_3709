"""HCT-304/308: Care plan safety windows, confirmation, escalation tests."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.care_plan import (
    check_escalation,
    confirm_plan,
    defer_plan,
    skip_plan,
    validate_safety_window,
)


class TestSafetyWindow:
    def test_first_dose_always_allowed(self):
        validate_safety_window(None, datetime.now(UTC))

    def test_too_early_rejected(self):
        last = datetime.now(UTC)
        too_soon = last + timedelta(hours=2)
        with pytest.raises(HTTPException) as exc:
            validate_safety_window(last, too_soon, min_interval=4)
        assert "TIME_WINDOW" in str(exc.value.detail)

    def test_ok_after_interval(self):
        last = datetime.now(UTC)
        ok_time = last + timedelta(hours=5)
        validate_safety_window(last, ok_time, min_interval=4)


class TestEscalation:
    def test_normal_when_not_due(self):
        created = datetime.now(UTC) - timedelta(hours=1)
        level = check_escalation(created, None, interval_hours=24)
        assert level == "normal"

    def test_reminder_after_due(self):
        created = datetime.now(UTC) - timedelta(hours=25)
        level = check_escalation(created, None, interval_hours=24)
        assert level == "reminder"

    def test_escalated_past_grace(self):
        created = datetime.now(UTC) - timedelta(hours=27)
        level = check_escalation(created, None, interval_hours=24, grace_hours=2)
        assert level == "escalated"


class TestPlanActions:
    def test_confirm_has_idempotency_key(self):
        event = confirm_plan("m1", "h1", "plan-1", "actor1")
        assert event.idempotency_key == "confirm:plan-1"
        assert event.event_type == "plan_confirmed"

    def test_defer_has_idempotency_key(self):
        event = defer_plan("m1", "h1", "plan-1", 8, "actor1")
        assert event.idempotency_key == "defer:plan-1"
        assert event.payload["delay_hours"] == 8

    def test_skip_has_idempotency_key(self):
        event = skip_plan("m1", "h1", "plan-1", "doctor advised", "actor1")
        assert event.idempotency_key == "skip:plan-1"
        assert event.payload["reason"] == "doctor advised"
