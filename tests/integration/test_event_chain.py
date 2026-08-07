from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OutboxMessage


def create_household_and_member(client: TestClient) -> tuple[str, str]:
    household = client.post(
        "/api/v1/households",
        headers={"X-Actor-Id": "owner"},
        json={"name": "测试家庭"},
    )
    assert household.status_code == 201
    household_id = household.json()["id"]

    member = client.post(
        f"/api/v1/households/{household_id}/members",
        headers={"X-Actor-Id": "owner"},
        json={"display_name": "测试成员", "role": "SELF"},
    )
    assert member.status_code == 201
    return household_id, member.json()["id"]


def test_confirmed_event_is_append_only_and_projects_state(
    client: TestClient, db_session: Session
) -> None:
    household_id, member_id = create_household_and_member(client)
    event = client.post(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_id,
            "event_type": "MEDICINE_ADDED",
            "confirmation_status": "CONFIRMED",
            "payload": {"name": "示例药品", "confirmation": "manual"},
            "evidence": {"source": "manual-entry"},
        },
    )
    assert event.status_code == 201
    event_id = event.json()["id"]

    state = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/state",
        headers={"X-Actor-Id": "owner"},
    )
    assert state.status_code == 200
    assert state.json()["last_event_id"] == event_id
    assert state.json()["state"]["events_count"] == 1

    events = client.get(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": "owner"},
    )
    assert events.status_code == 200
    assert [item["id"] for item in events.json()] == [event_id]

    outbox = db_session.scalars(select(OutboxMessage)).all()
    assert len(outbox) == 1
    assert outbox[0].event_id == event_id
    assert outbox[0].topic == "health_event.created"
    assert outbox[0].dispatched is False


def test_unconfirmed_event_is_retained_but_does_not_project_state(
    client: TestClient, db_session: Session
) -> None:
    household_id, member_id = create_household_and_member(client)
    event = client.post(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_id,
            "event_type": "MEDICINE_ADDED",
            "confirmation_status": "UNCONFIRMED",
            "payload": {"name": "待复核药品"},
        },
    )
    assert event.status_code == 201
    event_body = event.json()
    assert event_body["confirmation_status"] == "UNCONFIRMED"
    assert event_body["confirmed_by"] is None

    # 待复核事实可查询，但没有正式状态投影。
    state = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/state",
        headers={"X-Actor-Id": "owner"},
    )
    assert state.status_code == 404

    outbox = db_session.scalars(select(OutboxMessage)).all()
    assert len(outbox) == 1
    assert outbox[0].event_id == event_body["id"]
    assert outbox[0].topic == "health_event.pending"
    assert outbox[0].payload["confirmation_status"] == "UNCONFIRMED"


def test_revoked_authorization_immediately_blocks_reading(client: TestClient) -> None:
    household_id, member_id = create_household_and_member(client)
    authorization = client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_id,
            "grantee_actor_id": "daughter",
            "data_fields": ["health_events"],
            "actions": ["READ_EVENTS"],
            "purpose": "照护任务摘要",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    assert authorization.status_code == 201
    authorization_id = authorization.json()["id"]

    event = client.post(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": "owner"},
        json={"member_id": member_id, "event_type": "NOTE", "payload": {"text": "可见"}},
    )
    assert event.status_code == 201

    allowed = client.get(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": "daughter"},
    )
    assert allowed.status_code == 200
    assert len(allowed.json()) == 1

    revoke = client.post(
        f"/api/v1/households/{household_id}/authorizations/{authorization_id}/revoke",
        headers={"X-Actor-Id": "owner"},
    )
    assert revoke.status_code == 200

    blocked = client.get(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": "daughter"},
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "EVENT_READ_NOT_AUTHORIZED"


def test_cross_household_member_write_is_rejected(client: TestClient) -> None:
    household_id, _ = create_household_and_member(client)
    response = client.post(
        f"/api/v1/households/{household_id}/members",
        headers={"X-Actor-Id": "other-family"},
        json={"display_name": "越权成员"},
    )
    assert response.status_code == 403
