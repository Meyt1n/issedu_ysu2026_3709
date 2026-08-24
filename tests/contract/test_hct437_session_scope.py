"""HCT-437: session introspection exposes non-secret scope metadata."""

from fastapi.testclient import TestClient

ACTOR = "hct437-owner"
PASSWORD = "hct437-strong-pass"
PIN = "246810"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _sign_in(client: TestClient) -> str:
    registered = client.post(
        "/api/v1/auth/register",
        json={"actor_id": ACTOR, "password": PASSWORD},
    )
    assert registered.status_code == 201, registered.text
    response = client.post(
        "/api/v1/auth/login",
        json={"actor_id": ACTOR, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()["session_token"]


def test_pin_session_introspection_reports_household_scope_without_token(
    client: TestClient,
) -> None:
    password_token = _sign_in(client)
    household = client.post(
        "/api/v1/households",
        headers=_bearer(password_token),
        json={"name": "HCT-437 household"},
    )
    assert household.status_code == 201, household.text
    household_id = household.json()["id"]

    configured = client.post(
        "/api/v1/auth/pin",
        headers=_bearer(password_token),
        json={"household_id": household_id, "pin": PIN},
    )
    assert configured.status_code == 200, configured.text

    pin_login = client.post(
        "/api/v1/auth/pin-login",
        json={"household_id": household_id, "actor_id": ACTOR, "pin": PIN},
    )
    assert pin_login.status_code == 200, pin_login.text
    pin_token = pin_login.json()["session_token"]

    introspected = client.post(
        "/api/v1/auth/session",
        headers=_bearer(pin_token),
    )
    assert introspected.status_code == 200, introspected.text
    body = introspected.json()
    assert body["actor_id"] == ACTOR
    assert body["household_id"] == household_id
    assert body["issued_at"] > 0
    assert body["issued_at"] < body["expires_at"]
    assert "session_token" not in body
    assert "token_hash" not in introspected.text
