"""HCT-304/308: Care plan safety windows, confirmation, escalation tests."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.care_plan import (
    build_plan_workbench,
    check_escalation,
    confirm_plan,
    defer_plan,
    miss_plan,
    plan_automation_decisions,
    skip_plan,
    validate_plan_confirmation_window,
    validate_safety_window,
)
from app.models import HealthEvent


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

    def test_clock_window_uses_household_time_zone(self):
        proposed = datetime(2026, 8, 23, 16, 30, tzinfo=UTC)
        plan = HealthEvent(
            id="plan-time-zone",
            event_type="plan_created",
            occurred_at=proposed - timedelta(days=1),
            payload={
                "safety_window": {
                    "earliest_time": "00:00",
                    "latest_time": "01:00",
                }
            },
        )

        validate_plan_confirmation_window(
            [plan],
            plan.id,
            proposed,
            time_zone="Asia/Shanghai",
        )
        with pytest.raises(HTTPException) as exc:
            validate_plan_confirmation_window(
                [plan],
                plan.id,
                proposed,
                time_zone="UTC",
            )
        assert exc.value.detail == "TIME_WINDOW_VIOLATION"


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
        event = defer_plan("m1", "h1", "plan-1", 2, "actor1")
        assert event.idempotency_key == "defer:plan-1"
        assert event.payload["delay_hours"] == 2

    def test_skip_has_idempotency_key(self):
        event = skip_plan("m1", "h1", "plan-1", "doctor advised", "actor1")
        assert event.idempotency_key == "skip:plan-1"
        assert event.payload["reason"] == "doctor advised"

    def test_missed_is_distinct_from_skip(self):
        event = miss_plan("m1", "h1", "plan-1", "forgot", "actor1")
        assert event.event_type == "plan_missed"
        assert event.idempotency_key.startswith("miss:plan-1:")
        assert event.payload["reason"] == "forgot"

    def test_workbench_exposes_schedule_and_missed_history(self):
        plan = HealthEvent(
            id="plan-1",
            event_type="plan_created",
            occurred_at=datetime.now(UTC) - timedelta(hours=1),
            payload={
                "drug": "演示药",
                "schedule": "每日两次",
                "dose": "1 粒",
                "times": ["08:00", "20:00"],
                "start_date": "2026-08-20",
                "end_date": "2026-08-27",
            },
        )
        missed = HealthEvent(
            id="miss-1",
            event_type="plan_missed",
            occurred_at=datetime.now(UTC),
            payload={"plan_event_id": "plan-1", "reason": "忘记服用"},
        )

        item = build_plan_workbench([plan, missed])[0]

        assert item["dose"] == "1 粒"
        assert item["times"] == ["08:00", "20:00"]
        assert item["last_action"]["action"] == "MISS"
        assert item["last_action"]["reason"] == "忘记服用"
        assert item["action_history"][0]["action"] == "MISS"


class TestPlanAutomation:
    def test_unapproved_plan_is_never_automatically_written(self):
        now = datetime(2026, 8, 23, 12, tzinfo=UTC)
        plan = HealthEvent(
            id="plan-unapproved",
            event_type="plan_created",
            occurred_at=now - timedelta(hours=30),
            payload={"drug": "演示药", "schedule": "每日一次"},
        )

        assert plan_automation_decisions([plan], time_zone="Asia/Shanghai", now=now) == []

    def test_overdue_approved_plan_creates_missed_and_escalation_decisions(self):
        now = datetime(2026, 8, 23, 12, tzinfo=UTC)
        plan = HealthEvent(
            id="plan-approved",
            event_type="plan_created",
            occurred_at=now - timedelta(hours=30),
            payload={
                "drug": "演示药",
                "schedule": "每日一次",
                "automation": {"authorization": "AUTHORIZED"},
                "caregiver_notification": {"authorization": "AUTHORIZED"},
            },
        )

        decisions = plan_automation_decisions([plan], time_zone="Asia/Shanghai", now=now)

        assert [item["event_type"] for item in decisions] == ["plan_missed", "care_escalated"]
        assert decisions[-1]["notify_caregivers"] is True

    def test_course_end_uses_household_local_date(self):
        # UTC is still Aug 23, while the household local date is already Aug 24.
        now = datetime(2026, 8, 23, 16, 30, tzinfo=UTC)
        plan = HealthEvent(
            id="plan-course",
            event_type="plan_created",
            occurred_at=now - timedelta(days=2),
            payload={
                "drug": "演示药",
                "schedule": "每日一次",
                "end_date": "2026-08-23",
                "automation": {"authorization": "AUTHORIZED"},
            },
        )

        decisions = plan_automation_decisions([plan], time_zone="Asia/Shanghai", now=now)

        assert [item["event_type"] for item in decisions] == ["course_ended"]
