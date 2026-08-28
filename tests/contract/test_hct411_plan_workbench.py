"""HCT-411: server-authoritative desktop care workbench contract."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.care_plan_worker import automation_cycle
from app.models import HealthEvent

OWNER_HEADERS = {"X-Actor-Id": "owner"}


def _create_household_and_member(client: TestClient) -> tuple[str, str]:
    household = client.post(
        "/api/v1/households", headers=OWNER_HEADERS, json={"name": "HCT-411 household"}
    )
    assert household.status_code == 201, household.text
    member = client.post(
        f"/api/v1/households/{household.json()['id']}/members",
        headers=OWNER_HEADERS,
        json={"display_name": "Synthetic member", "role": "SELF"},
    )
    assert member.status_code == 201, member.text
    return household.json()["id"], member.json()["id"]


def _append_plan(
    client: TestClient,
    household_id: str,
    member_id: str,
    *,
    payload: dict | None = None,
    occurred_at: datetime | None = None,
) -> dict:
    response = client.post(
        f"/api/v1/households/{household_id}/events",
        headers=OWNER_HEADERS,
        json={
            "member_id": member_id,
            "event_type": "plan_created",
            "confirmation_status": "CONFIRMED",
            "payload": payload or {"drug": "Synthetic medicine", "schedule": "每日一次"},
            "occurred_at": (occurred_at or datetime.now(UTC) - timedelta(hours=25)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_confirm_plan_enforces_minimum_interval_and_retries_idempotently(
    client: TestClient,
) -> None:
    household_id, member_id = _create_household_and_member(client)
    plan = _append_plan(
        client,
        household_id,
        member_id,
        payload={
            "drug": "Synthetic medicine",
            "schedule": "每日一次",
            "safety_window": {"min_interval_hours": 4},
        },
    )

    first = client.post(
        f"/api/v1/households/{household_id}/members/{member_id}/plans/confirm",
        headers={**OWNER_HEADERS, "Idempotency-Key": "confirm-hct304-1"},
        params={"plan_event_id": plan["id"]},
    )
    assert first.status_code == 201, first.text

    retry = client.post(
        f"/api/v1/households/{household_id}/members/{member_id}/plans/confirm",
        headers={**OWNER_HEADERS, "Idempotency-Key": "confirm-hct304-1"},
        params={"plan_event_id": plan["id"]},
    )
    assert retry.status_code == 201, retry.text
    assert retry.json()["id"] == first.json()["id"]

    too_soon = client.post(
        f"/api/v1/households/{household_id}/members/{member_id}/plans/confirm",
        headers={**OWNER_HEADERS, "Idempotency-Key": "confirm-hct304-2"},
        params={"plan_event_id": plan["id"]},
    )
    assert too_soon.status_code == 422, too_soon.text
    assert too_soon.json()["detail"] == "TIME_WINDOW_VIOLATION"


def test_confirm_plan_enforces_daily_limit_and_clock_window(client: TestClient) -> None:
    household_id, member_id = _create_household_and_member(client)
    plan = _append_plan(
        client,
        household_id,
        member_id,
        payload={
            "drug": "Synthetic medicine",
            "schedule": "每日一次",
            "safety_window": {
                "min_interval_hours": 1,
                "max_daily_doses": 1,
                "earliest_time": "00:00",
                "latest_time": "23:59",
            },
        },
    )
    first = client.post(
        f"/api/v1/households/{household_id}/members/{member_id}/plans/confirm",
        headers={**OWNER_HEADERS, "Idempotency-Key": "confirm-hct304-limit-1"},
        params={"plan_event_id": plan["id"]},
    )
    assert first.status_code == 201, first.text
    second = client.post(
        f"/api/v1/households/{household_id}/members/{member_id}/plans/confirm",
        headers={**OWNER_HEADERS, "Idempotency-Key": "confirm-hct304-limit-2"},
        params={"plan_event_id": plan["id"]},
    )
    assert second.status_code == 422, second.text
    assert second.json()["detail"] == "TIME_WINDOW_VIOLATION"


def test_plan_workbench_returns_server_authoritative_due_status(client: TestClient) -> None:
    household_id, member_id = _create_household_and_member(client)
    plan = _append_plan(client, household_id, member_id)

    response = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/plan-workbench",
        headers=OWNER_HEADERS,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["member_id"] == member_id
    assert body["generated_at"]
    assert body["plans"] == [
        {
            "plan_event_id": plan["id"],
            "drug": "Synthetic medicine",
            "schedule": "每日一次",
            "dose": None,
            "times": [],
            "start_date": None,
            "end_date": None,
            "status": "REMINDER",
            "next_action_at": body["plans"][0]["next_action_at"],
            "last_action": None,
            "action_history": [],
            "allowed_actions": ["CONFIRM", "DEFER", "SKIP", "MISS"],
        }
    ]


def test_plan_workbench_hides_member_after_revocation(client: TestClient) -> None:
    household_id, member_id = _create_household_and_member(client)
    _append_plan(client, household_id, member_id)
    grant = client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers=OWNER_HEADERS,
        json={
            "member_id": member_id,
            "grantee_actor_id": "caregiver",
            "data_fields": ["health_events"],
            "actions": ["READ_EVENTS"],
            "purpose": "plan-care",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    assert grant.status_code == 201, grant.text
    caregiver_headers = {"X-Actor-Id": "caregiver", "X-Access-Purpose": "plan-care"}

    visible = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/plan-workbench",
        headers=caregiver_headers,
    )
    assert visible.status_code == 200, visible.text

    revoked = client.post(
        f"/api/v1/households/{household_id}/authorizations/{grant.json()['id']}/revoke",
        headers=OWNER_HEADERS,
        json={"expected_version": grant.json()["version"]},
    )
    assert revoked.status_code == 200, revoked.text

    hidden = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/plan-workbench",
        headers=caregiver_headers,
    )
    assert hidden.status_code == 404


def test_plan_workbench_uses_latest_deferral_for_next_action(client: TestClient) -> None:
    household_id, member_id = _create_household_and_member(client)
    plan = _append_plan(client, household_id, member_id)
    deferred = client.post(
        f"/api/v1/households/{household_id}/members/{member_id}/plans/defer",
        headers=OWNER_HEADERS,
        params={"plan_event_id": plan["id"], "delay_hours": 2},
    )
    assert deferred.status_code == 201, deferred.text

    response = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/plan-workbench",
        headers=OWNER_HEADERS,
    )

    assert response.status_code == 200, response.text
    item = response.json()["plans"][0]
    assert item["status"] == "NORMAL"
    assert item["last_action"]["action"] == "DEFER"
    next_action_at = datetime.fromisoformat(item["next_action_at"])
    assert timedelta(hours=1) < next_action_at - datetime.now(UTC) < timedelta(hours=3)


def test_plan_defer_rejects_delay_outside_one_to_two_hours(client: TestClient) -> None:
    household_id, member_id = _create_household_and_member(client)
    plan = _append_plan(client, household_id, member_id)
    rejected = client.post(
        f"/api/v1/households/{household_id}/members/{member_id}/plans/defer",
        headers=OWNER_HEADERS,
        params={"plan_event_id": plan["id"], "delay_hours": 6},
    )
    assert rejected.status_code == 422, rejected.text


def test_plan_workbench_records_missed_dose_separately(client: TestClient) -> None:
    household_id, member_id = _create_household_and_member(client)
    plan = _append_plan(client, household_id, member_id)
    missed = client.post(
        f"/api/v1/households/{household_id}/members/{member_id}/plans/missed",
        headers=OWNER_HEADERS,
        params={"plan_event_id": plan["id"], "reason": "忘记服用"},
    )

    assert missed.status_code == 201, missed.text
    assert missed.json()["event_type"] == "plan_missed"
    response = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/plan-workbench",
        headers=OWNER_HEADERS,
    )

    assert response.status_code == 200, response.text
    item = response.json()["plans"][0]
    assert item["last_action"]["action"] == "MISS"
    assert item["last_action"]["reason"] == "忘记服用"
    assert item["action_history"][-1]["action"] == "MISS"


def test_authorized_overdue_plan_escalates_once_and_notifies_active_caregiver(
    client: TestClient,
) -> None:
    household_id, member_id = _create_household_and_member(client)
    plan = _append_plan(
        client,
        household_id,
        member_id,
        occurred_at=datetime.now(UTC) - timedelta(hours=30),
        payload={
            "drug": "Synthetic medicine",
            "schedule": "每日一次",
            "automation": {"authorization": "AUTHORIZED"},
            "caregiver_notification": {"authorization": "AUTHORIZED"},
        },
    )
    grant = client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers=OWNER_HEADERS,
        json={
            "member_id": member_id,
            "grantee_actor_id": "caregiver",
            "data_fields": ["health_events"],
            "actions": ["READ_EVENTS"],
            "purpose": "plan-care",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    assert grant.status_code == 201, grant.text

    denied = client.post(
        f"/api/v1/households/{household_id}/members/{member_id}/plans/evaluate",
        headers={"X-Actor-Id": "caregiver", "X-Access-Purpose": "plan-care"},
    )
    assert denied.status_code == 404

    first = client.post(
        f"/api/v1/households/{household_id}/members/{member_id}/plans/evaluate",
        headers=OWNER_HEADERS,
    )

    assert first.status_code == 200, first.text
    body = first.json()
    assert [item["event_type"] for item in body["created_events"]] == [
        "plan_missed",
        "care_escalated",
        "caregiver_notified",
    ]
    assert body["notified_caregiver_actor_ids"] == ["caregiver"]
    notification = body["created_events"][-1]
    assert notification["payload"]["plan_event_id"] == plan["id"]
    assert notification["payload"]["recipient_actor_id"] == "caregiver"
    assert notification["payload"]["channel"] == "LOCAL_EVENT_INBOX"

    retry = client.post(
        f"/api/v1/households/{household_id}/members/{member_id}/plans/evaluate",
        headers=OWNER_HEADERS,
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["created_events"] == []
    assert retry.json()["notified_caregiver_actor_ids"] == []


def test_plan_evaluation_is_fail_closed_and_records_course_end(client: TestClient) -> None:
    household_id, member_id = _create_household_and_member(client)
    unapproved = _append_plan(
        client,
        household_id,
        member_id,
        occurred_at=datetime.now(UTC) - timedelta(hours=30),
        payload={"drug": "No automation", "schedule": "每日一次"},
    )
    approved = _append_plan(
        client,
        household_id,
        member_id,
        payload={
            "drug": "Finished course",
            "schedule": "每日一次",
            "end_date": (datetime.now(UTC).date() - timedelta(days=1)).isoformat(),
            "automation": {"authorization": "AUTHORIZED"},
        },
    )

    response = client.post(
        f"/api/v1/households/{household_id}/members/{member_id}/plans/evaluate",
        headers=OWNER_HEADERS,
    )

    assert response.status_code == 200, response.text
    events = response.json()["created_events"]
    assert [item["event_type"] for item in events] == ["course_ended"]
    assert events[0]["payload"]["plan_event_id"] == approved["id"]
    assert all(item["payload"]["plan_event_id"] != unapproved["id"] for item in events)

    workbench = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/plan-workbench",
        headers=OWNER_HEADERS,
    )
    assert workbench.status_code == 200, workbench.text
    completed = next(
        item
        for item in workbench.json()["plans"]
        if item["plan_event_id"] == approved["id"]
    )
    assert completed["status"] == "COMPLETED"
    assert completed["allowed_actions"] == []


def test_care_plan_worker_retry_does_not_duplicate_lifecycle_events(
    client: TestClient,
    db_session: Session,
) -> None:
    household_id, member_id = _create_household_and_member(client)
    plan = _append_plan(
        client,
        household_id,
        member_id,
        payload={
            "drug": "Finished course",
            "schedule": "每日一次",
            "end_date": (datetime.now(UTC).date() - timedelta(days=1)).isoformat(),
            "automation": {"authorization": "AUTHORIZED"},
        },
    )
    first = automation_cycle(db_session)
    second = automation_cycle(db_session, now=datetime.now(UTC) + timedelta(minutes=1))

    assert first.created_events == 1
    assert second.created_events == 0
    lifecycle = db_session.scalars(
        select(HealthEvent).where(
            HealthEvent.member_id == member_id,
            HealthEvent.event_type == "course_ended",
        )
    ).all()
    assert len(lifecycle) == 1
    assert lifecycle[0].payload["plan_event_id"] == plan["id"]
