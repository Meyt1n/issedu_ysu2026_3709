"""HCT-423: household-scoped six-digit PIN authentication."""

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


def test_pin_login_is_scoped_to_household_and_issues_bearer_session(client: TestClient):
    actor_id = f"pin-owner-{uuid4().hex[:10]}"
    password_token = _register_and_login(client, actor_id)
    household = client.post(
        "/api/v1/households",
        json={"name": "PIN household"},
        headers={"Authorization": f"Bearer {password_token}"},
    )
    assert household.status_code == 201
    household_id = household.json()["id"]

    configured = client.post(
        "/api/v1/auth/pin",
        json={"household_id": household_id, "pin": "042006"},
        headers={"Authorization": f"Bearer {password_token}"},
    )
    assert configured.status_code == 200
    assert configured.json() == {"status": "pin_configured", "household_id": household_id}

    pin_login = client.post(
        "/api/v1/auth/pin-login",
        json={"household_id": household_id, "actor_id": actor_id, "pin": "042006"},
    )
    assert pin_login.status_code == 200
    body = pin_login.json()
    assert body["actor_id"] == actor_id
    assert body["household_id"] == household_id
    assert len(body["session_token"]) >= 32

    listed = client.get(
        "/api/v1/households",
        headers={"Authorization": f"Bearer {body['session_token']}"},
    )
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == household_id

    wrong_household = client.post(
        "/api/v1/auth/pin-login",
        json={"household_id": "not-this-household", "actor_id": actor_id, "pin": "042006"},
    )
    assert wrong_household.status_code == 401
    assert wrong_household.json()["detail"] == "AUTH_FAILED"


def test_pin_login_rejects_wrong_pin_without_account_disclosure(client: TestClient):
    actor_id = f"pin-invalid-{uuid4().hex[:10]}"
    token = _register_and_login(client, actor_id)
    household_id = client.post(
        "/api/v1/households",
        json={"name": "PIN invalid household"},
        headers={"Authorization": f"Bearer {token}"},
    ).json()["id"]
    assert client.post(
        "/api/v1/auth/pin",
        json={"household_id": household_id, "pin": "123456"},
        headers={"Authorization": f"Bearer {token}"},
    ).status_code == 200

    wrong_pin = client.post(
        "/api/v1/auth/pin-login",
        json={"household_id": household_id, "actor_id": actor_id, "pin": "654321"},
    )
    unknown_actor = client.post(
        "/api/v1/auth/pin-login",
        json={
            "household_id": household_id,
            "actor_id": f"missing-{uuid4().hex[:10]}",
            "pin": "654321",
        },
    )
    assert wrong_pin.status_code == unknown_actor.status_code == 401
    assert wrong_pin.json() == unknown_actor.json() == {"detail": "AUTH_FAILED"}


def test_pin_login_is_rate_limited_after_repeated_failures(client: TestClient):
    actor_id = f"pin-brute-{uuid4().hex[:10]}"
    token = _register_and_login(client, actor_id)
    household_id = client.post(
        "/api/v1/households",
        json={"name": "PIN brute household"},
        headers={"Authorization": f"Bearer {token}"},
    ).json()["id"]
    assert client.post(
        "/api/v1/auth/pin",
        json={"household_id": household_id, "pin": "111111"},
        headers={"Authorization": f"Bearer {token}"},
    ).status_code == 200

    for _ in range(5):
        assert client.post(
            "/api/v1/auth/pin-login",
            json={"household_id": household_id, "actor_id": actor_id, "pin": "222222"},
        ).status_code == 401
    locked = client.post(
        "/api/v1/auth/pin-login",
        json={"household_id": household_id, "actor_id": actor_id, "pin": "222222"},
    )
    assert locked.status_code == 429
