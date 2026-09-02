from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.models import AuthAccount
from app.password_policy import TEACHING_PASSWORD_DEFAULT, TEACHING_PASSWORD_LEGACY


def test_register_rejects_passwords_without_letter_and_digit(client: TestClient) -> None:
    for index, password in enumerate(("password", "12345678", "short1", "DemoOnly-ChangeMe!")):
        response = client.post(
            "/api/v1/auth/register",
            json={"actor_id": f"policy-reg-{index}", "password": password},
        )
        assert response.status_code == 422, password


def test_login_rejects_passwords_without_letter_and_digit(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"actor_id": "anyone", "password": "password"},
    )
    assert response.status_code == 422


def test_register_and_login_accept_mixed_english_and_digit_password(client: TestClient) -> None:
    password = "policy-ok-123"
    registered = client.post(
        "/api/v1/auth/register",
        json={"actor_id": "policy-owner", "password": password},
    )
    assert registered.status_code == 201
    logged_in = client.post(
        "/api/v1/auth/login",
        json={"actor_id": "policy-owner", "password": password},
    )
    assert logged_in.status_code == 200
    assert logged_in.json()["session_token"]


def test_legacy_teaching_password_upgrades_when_new_default_is_used(
    client: TestClient, db_session: Session
) -> None:
    db_session.add(
        AuthAccount(actor_id="demo-parent", password_hash=hash_password(TEACHING_PASSWORD_LEGACY))
    )
    db_session.commit()
    logged_in = client.post(
        "/api/v1/auth/login",
        json={"actor_id": "demo-parent", "password": TEACHING_PASSWORD_DEFAULT},
    )
    assert logged_in.status_code == 200
    old = client.post(
        "/api/v1/auth/login",
        json={"actor_id": "demo-parent", "password": TEACHING_PASSWORD_LEGACY},
    )
    assert old.status_code == 422
