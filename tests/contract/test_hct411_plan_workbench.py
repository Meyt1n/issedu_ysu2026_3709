"""HCT-411: server-authoritative desktop care workbench contract."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

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


def _append_plan(client: TestClient, household_id: str, member_id: str) -> dict:
    response = client.post(
        f"/api/v1/households/{household_id}/events",
        headers=OWNER_HEADERS,
        json={
            "member_id": member_id,
            "event_type": "plan_created",
            "confirmation_status": "CONFIRMED",
            "payload": {"drug": "Synthetic medicine", "schedule": "每日一次"},
            "occurred_at": (datetime.now(UTC) - timedelta(hours=25)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


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
            "status": "REMINDER",
            "next_action_at": body["plans"][0]["next_action_at"],
            "last_action": None,
            "allowed_actions": ["CONFIRM", "DEFER", "SKIP"],
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
        params={"plan_event_id": plan["id"], "delay_hours": 6},
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
    assert timedelta(hours=5) < next_action_at - datetime.now(UTC) < timedelta(hours=7)
