"""HCT-405 / HCT-423: formal PIN login establishes member portal context.

Maps to acceptance-gate scenario ``family_login_to_member_context``.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient


def _register_and_login(client: TestClient, actor_id: str) -> str:
    password = "local-password-123"
    assert client.post(
        "/api/v1/auth/register",
        json={"actor_id": actor_id, "password": password},
    ).status_code == 201
    response = client.post(
        "/api/v1/auth/login",
        json={"actor_id": actor_id, "password": password},
    )
    assert response.status_code == 200
    return response.json()["session_token"]


def _configure_pin(client: TestClient, token: str, household_id: str, pin: str) -> None:
    configured = client.post(
        "/api/v1/auth/pin",
        json={"household_id": household_id, "pin": pin},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert configured.status_code == 200, configured.text


def test_pin_login_establishes_member_context_and_blocks_admin_routes(client: TestClient):
    owner_id = f"portal-owner-{uuid4().hex[:8]}"
    member_id = f"portal-grandma-{uuid4().hex[:8]}"
    owner_token = _register_and_login(client, owner_id)

    household = client.post(
        "/api/v1/households",
        json={"name": "PIN 成员门户家庭"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert household.status_code == 201, household.text
    household_id = household.json()["id"]

    member = client.post(
        f"/api/v1/households/{household_id}/members",
        json={"display_name": "奶奶", "role": "DEPENDENT", "actor_id": member_id},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert member.status_code == 201, member.text
    member_row_id = member.json()["id"]

    _configure_pin(client, owner_token, household_id, "042006")
    member_token = _register_and_login(client, member_id)
    _configure_pin(client, member_token, household_id, "135790")

    pin_login = client.post(
        "/api/v1/auth/pin-login",
        json={"household_id": household_id, "actor_id": member_id, "pin": "135790"},
    )
    assert pin_login.status_code == 200, pin_login.text
    body = pin_login.json()
    assert body["actor_id"] == member_id
    assert body["household_id"] == household_id
    session_headers = {"Authorization": f"Bearer {body['session_token']}"}

    households = client.get("/api/v1/households", headers=session_headers)
    assert households.status_code == 200
    assert households.json()[0]["id"] == household_id
    assert households.json()[0]["created_by"] == owner_id

    members = client.get(
        f"/api/v1/households/{household_id}/members",
        headers=session_headers,
    )
    assert members.status_code == 200
    assert len(members.json()) == 1
    assert members.json()[0]["id"] == member_row_id
    assert members.json()[0]["display_name"] == "奶奶"

    own_timeline = client.get(
        f"/api/v1/households/{household_id}/members/{member_row_id}/timeline",
        headers=session_headers,
    )
    assert own_timeline.status_code == 200
    assert own_timeline.json() == []

    review_tasks = client.get(
        f"/api/v1/households/{household_id}/members/{member_row_id}/review-tasks",
        headers=session_headers,
    )
    assert review_tasks.status_code == 404


def test_owner_pin_login_retains_admin_scope(client: TestClient):
    owner_id = f"portal-admin-{uuid4().hex[:8]}"
    owner_token = _register_and_login(client, owner_id)
    household = client.post(
        "/api/v1/households",
        json={"name": "PIN 管理员家庭"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()
    household_id = household["id"]
    _configure_pin(client, owner_token, household_id, "246810")

    pin_login = client.post(
        "/api/v1/auth/pin-login",
        json={"household_id": household_id, "actor_id": owner_id, "pin": "246810"},
    )
    assert pin_login.status_code == 200
    session_headers = {"Authorization": f"Bearer {pin_login.json()['session_token']}"}

    members = client.get(
        f"/api/v1/households/{household_id}/members",
        headers=session_headers,
    )
    assert members.status_code == 200

    member = client.post(
        f"/api/v1/households/{household_id}/members",
        json={
            "display_name": "爷爷",
            "role": "DEPENDENT",
            "actor_id": f"grandpa-{uuid4().hex[:6]}",
        },
        headers=session_headers,
    ).json()

    review_tasks = client.get(
        f"/api/v1/households/{household_id}/members/{member['id']}/review-tasks",
        headers=session_headers,
    )
    assert review_tasks.status_code == 200
    assert review_tasks.json() == []
