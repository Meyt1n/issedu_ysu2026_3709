"""HCT-511: household owner may set a member PIN used for member-portal login."""

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


def test_owner_sets_member_pin_and_member_can_pin_login(client: TestClient):
    owner_id = f"hct511-owner-{uuid4().hex[:8]}"
    member_actor = f"hct511-member-{uuid4().hex[:8]}"
    owner_token = _register_and_login(client, owner_id)
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    household = client.post(
        "/api/v1/households",
        json={"name": "HCT-511 PIN household"},
        headers=owner_headers,
    )
    assert household.status_code == 201
    household_id = household.json()["id"]

    member = client.post(
        f"/api/v1/households/{household_id}/members",
        json={"display_name": "奶奶", "role": "DEPENDENT", "actor_id": member_actor},
        headers=owner_headers,
    )
    assert member.status_code == 201

    configured = client.post(
        "/api/v1/auth/pin",
        json={"household_id": household_id, "pin": "135790", "actor_id": member_actor},
        headers=owner_headers,
    )
    assert configured.status_code == 200
    assert configured.json() == {"status": "pin_configured", "household_id": household_id}

    pin_login = client.post(
        "/api/v1/auth/pin-login",
        json={"household_id": household_id, "actor_id": member_actor, "pin": "135790"},
    )
    assert pin_login.status_code == 200
    assert pin_login.json()["actor_id"] == member_actor
    assert pin_login.json()["household_id"] == household_id

    status = client.get(
        f"/api/v1/households/{household_id}/pin-status",
        headers=owner_headers,
    )
    assert status.status_code == 200
    body = status.json()
    assert body["household_id"] == household_id
    assert member_actor in body["configured_actor_ids"]
    assert "pin" not in body
    assert "pin_hash" not in body


def test_non_owner_cannot_set_another_actor_pin(client: TestClient):
    owner_id = f"hct511-owner-{uuid4().hex[:8]}"
    other_id = f"hct511-other-{uuid4().hex[:8]}"
    owner_token = _register_and_login(client, owner_id)
    other_token = _register_and_login(client, other_id)
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    household_id = client.post(
        "/api/v1/households",
        json={"name": "HCT-511 forbidden PIN"},
        headers=owner_headers,
    ).json()["id"]
    assert client.post(
        f"/api/v1/households/{household_id}/members",
        json={"display_name": "家人", "role": "DEPENDENT", "actor_id": other_id},
        headers=owner_headers,
    ).status_code == 201

    forbidden = client.post(
        "/api/v1/auth/pin",
        json={"household_id": household_id, "pin": "246802", "actor_id": owner_id},
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "FORBIDDEN"

    status_forbidden = client.get(
        f"/api/v1/households/{household_id}/pin-status",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert status_forbidden.status_code == 403
    assert status_forbidden.json()["detail"] == "FORBIDDEN"
