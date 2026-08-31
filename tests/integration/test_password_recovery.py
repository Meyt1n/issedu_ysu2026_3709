"""Formal local password change and PIN-backed recovery."""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AccessAudit, AuthAccount

OLD_PASSWORD = "old-local-password-123"
NEW_PASSWORD = "new-local-password-456"


def _register_login_and_create_household(
    client: TestClient,
    actor_id: str,
) -> tuple[str, str]:
    assert client.post(
        "/api/v1/auth/register",
        json={"actor_id": actor_id, "password": OLD_PASSWORD},
    ).status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"actor_id": actor_id, "password": OLD_PASSWORD},
    )
    assert login.status_code == 200
    token = login.json()["session_token"]
    household = client.post(
        "/api/v1/households",
        json={"name": "Password recovery household"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert household.status_code == 201
    return token, household.json()["id"]


def test_authenticated_password_change_rotates_all_sessions(
    client: TestClient,
    db_session: Session,
) -> None:
    actor_id = f"password-change-{uuid4().hex[:10]}"
    old_token, _ = _register_login_and_create_household(client, actor_id)

    changed = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert changed.status_code == 200
    new_token = changed.json()["session_token"]
    assert new_token != old_token

    assert client.post(
        "/api/v1/auth/session",
        headers={"Authorization": f"Bearer {old_token}"},
    ).status_code == 401
    assert client.post(
        "/api/v1/auth/session",
        headers={"Authorization": f"Bearer {new_token}"},
    ).status_code == 200
    assert client.post(
        "/api/v1/auth/login",
        json={"actor_id": actor_id, "password": OLD_PASSWORD},
    ).status_code == 401
    assert client.post(
        "/api/v1/auth/login",
        json={"actor_id": actor_id, "password": NEW_PASSWORD},
    ).status_code == 200

    account = db_session.get(AuthAccount, actor_id)
    assert account is not None
    assert account.password_hash not in {OLD_PASSWORD, NEW_PASSWORD}
    audit = db_session.scalar(
        select(AccessAudit).where(
            AccessAudit.actor_id == actor_id,
            AccessAudit.action == "PASSWORD_CHANGE",
            AccessAudit.outcome == "SUCCESS",
        )
    )
    assert audit is not None
    assert audit.data_field == "account_password"
    assert OLD_PASSWORD not in (audit.reason or "")
    assert NEW_PASSWORD not in (audit.reason or "")


def test_password_change_rejects_wrong_or_reused_password(client: TestClient) -> None:
    actor_id = f"password-change-invalid-{uuid4().hex[:10]}"
    token, _ = _register_login_and_create_household(client, actor_id)

    wrong = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "wrong-password-123", "new_password": NEW_PASSWORD},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert wrong.status_code == 401
    assert wrong.json() == {"detail": "AUTH_FAILED"}

    reused = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": OLD_PASSWORD, "new_password": OLD_PASSWORD},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert reused.status_code == 422
    assert reused.json() == {"detail": "PASSWORD_REUSE"}


def test_forgotten_password_can_be_recovered_with_same_actor_household_pin(
    client: TestClient,
    db_session: Session,
) -> None:
    actor_id = f"password-recovery-{uuid4().hex[:10]}"
    old_token, household_id = _register_login_and_create_household(client, actor_id)
    assert client.post(
        "/api/v1/auth/pin",
        json={"household_id": household_id, "pin": "042006"},
        headers={"Authorization": f"Bearer {old_token}"},
    ).status_code == 200

    recovered = client.post(
        "/api/v1/auth/recover-password",
        json={
            "actor_id": actor_id,
            "household_id": household_id,
            "pin": "042006",
            "new_password": NEW_PASSWORD,
        },
    )
    assert recovered.status_code == 200
    assert recovered.json()["actor_id"] == actor_id
    assert recovered.json()["household_id"] == household_id
    recovered_token = recovered.json()["session_token"]

    assert client.post(
        "/api/v1/auth/session",
        headers={"Authorization": f"Bearer {old_token}"},
    ).status_code == 401
    assert client.post(
        "/api/v1/auth/session",
        headers={"Authorization": f"Bearer {recovered_token}"},
    ).status_code == 200
    assert client.post(
        "/api/v1/auth/login",
        json={"actor_id": actor_id, "password": OLD_PASSWORD},
    ).status_code == 401
    assert client.post(
        "/api/v1/auth/login",
        json={"actor_id": actor_id, "password": NEW_PASSWORD},
    ).status_code == 200

    audit = db_session.scalar(
        select(AccessAudit).where(
            AccessAudit.actor_id == actor_id,
            AccessAudit.action == "PASSWORD_RECOVERY",
            AccessAudit.outcome == "SUCCESS",
        )
    )
    assert audit is not None
    serialized_audit = " ".join(
        str(value)
        for value in (
            audit.operation,
            audit.action,
            audit.data_field,
            audit.purpose,
            audit.outcome,
            audit.reason,
        )
    )
    assert "042006" not in serialized_audit
    assert OLD_PASSWORD not in serialized_audit
    assert NEW_PASSWORD not in serialized_audit


def test_password_recovery_does_not_disclose_account_or_pin_state(client: TestClient) -> None:
    actor_id = f"password-recovery-invalid-{uuid4().hex[:10]}"
    _, household_id = _register_login_and_create_household(client, actor_id)

    wrong_pin = client.post(
        "/api/v1/auth/recover-password",
        json={
            "actor_id": actor_id,
            "household_id": household_id,
            "pin": "654321",
            "new_password": NEW_PASSWORD,
        },
    )
    unknown_actor = client.post(
        "/api/v1/auth/recover-password",
        json={
            "actor_id": f"missing-{uuid4().hex[:10]}",
            "household_id": household_id,
            "pin": "654321",
            "new_password": NEW_PASSWORD,
        },
    )
    assert wrong_pin.status_code == unknown_actor.status_code == 401
    assert wrong_pin.json() == unknown_actor.json() == {"detail": "AUTH_FAILED"}
