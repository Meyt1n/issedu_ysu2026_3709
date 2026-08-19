"""HCT-417: web-facing JSON auth and in-memory bearer session boundary."""

from uuid import uuid4

from fastapi.testclient import TestClient


def test_json_login_uses_bearer_identity_and_logout_revokes_session(client: TestClient):
    actor_id = f"web-session-{uuid4().hex[:10]}"
    password = "local-password-123"

    registered = client.post(
        "/api/v1/auth/register",
        json={"actor_id": actor_id, "password": password},
    )
    assert registered.status_code == 201

    login = client.post(
        "/api/v1/auth/login",
        json={"actor_id": actor_id, "password": password},
    )
    assert login.status_code == 200
    body = login.json()
    assert body["actor_id"] == actor_id
    token = body["session_token"]
    assert len(token) >= 32

    created = client.post(
        "/api/v1/households",
        json={"name": "Synthetic session household"},
        headers={"Authorization": f"Bearer {token}", "X-Actor-Id": "wrong-actor"},
    )
    assert created.status_code == 201
    assert created.json()["created_by"] == actor_id

    logged_out = client.post("/api/v1/auth/logout", json={"session_token": token})
    assert logged_out.status_code == 200

    denied = client.get(
        "/api/v1/households",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert denied.status_code == 401


def test_malformed_authorization_does_not_fall_back_to_dev_actor(client: TestClient):
    response = client.get(
        "/api/v1/households",
        headers={"Authorization": "Basic not-a-bearer", "X-Actor-Id": "dev-actor"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "AUTH_REQUIRED"
