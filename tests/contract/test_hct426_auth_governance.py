from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auth
from app.models import AccessAudit, FaceCredential, Household


def _password_login(client: TestClient, actor_id: str) -> str:
    assert client.post(
        "/api/v1/auth/register",
        json={"actor_id": actor_id, "password": "local-password-123"},
    ).status_code == 201
    response = client.post(
        "/api/v1/auth/login",
        json={"actor_id": actor_id, "password": "local-password-123"},
    )
    assert response.status_code == 200
    return response.json()["session_token"]


def _create_pin_household(client: TestClient, actor_id: str) -> tuple[str, str, str]:
    password_token = _password_login(client, actor_id)
    household = client.post(
        "/api/v1/households",
        json={"name": "HCT-426 governance household"},
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
    pin_login = client.post(
        "/api/v1/auth/pin-login",
        json={"household_id": household_id, "actor_id": actor_id, "pin": "042006"},
    )
    assert pin_login.status_code == 200
    return household_id, password_token, pin_login.json()["session_token"]


def test_pin_authentication_audit_contains_metadata_only(
    client: TestClient,
    db_session: Session,
) -> None:
    actor_id = f"hct426-audit-{uuid4().hex[:10]}"
    household_id, _, _ = _create_pin_household(client, actor_id)

    wrong = client.post(
        "/api/v1/auth/pin-login",
        json={"household_id": household_id, "actor_id": actor_id, "pin": "654321"},
    )
    assert wrong.status_code == 401

    audits = list(
        db_session.scalars(
            select(AccessAudit)
            .where(
                AccessAudit.household_id == household_id,
                AccessAudit.operation == "AUTHENTICATION",
            )
            .order_by(AccessAudit.created_at, AccessAudit.id)
        ).all()
    )
    assert [audit.outcome for audit in audits] == ["SUCCESS", "FAILED"]
    assert audits[-1].reason == "AUTH_FAILED"
    assert audits[-1].data_field == "pin"
    assert audits[-1].purpose == "authentication"
    assert {"pin", "password", "session_token", "template", "score"}.isdisjoint(
        AccessAudit.__table__.columns.keys()
    )

    configuration_audit = db_session.scalar(
        select(AccessAudit).where(
            AccessAudit.household_id == household_id,
            AccessAudit.operation == "PIN_CREDENTIAL",
        )
    )
    assert configuration_audit is not None
    assert configuration_audit.action == "SET"
    assert configuration_audit.data_field == "pin"
    assert configuration_audit.purpose == "authentication"
    assert configuration_audit.reason == "PIN_CONFIGURED"


def test_household_erasure_removes_pin_face_secret_and_bound_sessions(
    client: TestClient,
    db_session: Session,
) -> None:
    actor_id = f"hct426-delete-{uuid4().hex[:10]}"
    household_id, password_token, pin_token = _create_pin_household(client, actor_id)
    credential = FaceCredential(
        household_id=household_id,
        actor_id=actor_id,
        encrypted_template=b"encrypted-face-template",
        algorithm_version="test",
        feature_version="test",
        credential_version=1,
        consent_version="test",
        status="ACTIVE",
        created_by=actor_id,
        consented_at=datetime.now(UTC),
    )
    db_session.add(credential)
    db_session.commit()

    erased = client.delete(
        f"/api/v1/households/{household_id}",
        headers={"Authorization": f"Bearer {password_token}"},
    )
    assert erased.status_code == 200
    assert erased.json()["status"] == "completed"
    assert (household_id, actor_id) not in auth._pin_hashes
    assert client.post(
        "/api/v1/auth/session",
        headers={"Authorization": f"Bearer {pin_token}"},
    ).status_code == 401

    stored = db_session.scalar(select(FaceCredential).where(FaceCredential.id == credential.id))
    assert stored is not None
    assert stored.status == "DELETED"
    assert stored.encrypted_template == b""
    household = db_session.get(Household, household_id)
    assert household is not None and household.deleted_at is not None


def test_face_credential_can_be_deleted_after_a_previous_tombstone(
    client: TestClient,
    db_session: Session,
) -> None:
    actor_id = f"hct426-face-delete-{uuid4().hex[:10]}"
    household_id, password_token, _ = _create_pin_household(client, actor_id)
    now = datetime.now(UTC)
    previous = FaceCredential(
        household_id=household_id,
        actor_id=actor_id,
        encrypted_template=b"previous-template",
        algorithm_version="test",
        feature_version="test",
        credential_version=1,
        consent_version="test",
        status="DELETED",
        created_by=actor_id,
        consented_at=now,
        revoked_at=now,
    )
    current = FaceCredential(
        household_id=household_id,
        actor_id=actor_id,
        encrypted_template=b"current-template",
        algorithm_version="test",
        feature_version="test",
        credential_version=2,
        consent_version="test",
        status="ACTIVE",
        created_by=actor_id,
        consented_at=now,
    )
    db_session.add_all([previous, current])
    db_session.commit()

    deleted = client.delete(
        f"/api/v1/households/{household_id}/face-credentials/{current.id}",
        headers={"Authorization": f"Bearer {password_token}"},
    )

    assert deleted.status_code == 200
    assert deleted.json()["status"] == "DELETED"
    stored = db_session.scalar(select(FaceCredential).where(FaceCredential.id == current.id))
    assert stored is not None and stored.status == "DELETED"
    listed = client.get(
        f"/api/v1/households/{household_id}/face-credentials",
        headers={"Authorization": f"Bearer {password_token}"},
    )
    assert listed.status_code == 200
    assert all(item["status"] != "DELETED" for item in listed.json())
