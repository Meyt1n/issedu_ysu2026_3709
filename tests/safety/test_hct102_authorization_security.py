from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AccessAudit, CareAuthorization

OWNER_HEADERS = {"X-Actor-Id": "owner"}
CARE_HEADERS = {
    "X-Actor-Id": "caregiver",
    "X-Access-Purpose": "family-care",
}
REPO_ROOT = Path(__file__).resolve().parents[2]


def create_household_member(
    client: TestClient,
    *,
    owner: str = "owner",
    name: str = "Household",
) -> tuple[str, str]:
    headers = {"X-Actor-Id": owner}
    household = client.post(
        "/api/v1/households",
        headers=headers,
        json={"name": name},
    )
    assert household.status_code == 201
    household_id = household.json()["id"]
    member = client.post(
        f"/api/v1/households/{household_id}/members",
        headers=headers,
        json={"display_name": "Member", "role": "SELF"},
    )
    assert member.status_code == 201
    return household_id, member.json()["id"]


def create_authorization(
    client: TestClient,
    household_id: str,
    member_id: str,
    *,
    owner: str = "owner",
    grantee: str = "caregiver",
    purpose: str = "family-care",
) -> dict:
    response = client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers={"X-Actor-Id": owner},
        json={
            "member_id": member_id,
            "grantee_actor_id": grantee,
            "data_fields": ["health_events"],
            "actions": ["READ_EVENTS"],
            "purpose": purpose,
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_authorization_endpoints_require_identity(client: TestClient) -> None:
    assert client.get("/api/v1/households/example/authorizations").status_code == 401


def test_cross_household_reads_writes_and_id_guessing_are_hidden(client: TestClient) -> None:
    household_id, member_id = create_household_member(client)
    authorization = create_authorization(client, household_id, member_id)
    other_household_id, _ = create_household_member(
        client,
        owner="other-owner",
        name="Other household",
    )
    other_headers = {"X-Actor-Id": "other-owner"}

    responses = [
        client.get(
            f"/api/v1/households/{household_id}/authorizations",
            headers=other_headers,
        ),
        client.get(
            f"/api/v1/households/{household_id}/authorization-audits",
            headers=other_headers,
        ),
        client.post(
            f"/api/v1/households/{household_id}/members",
            headers=other_headers,
            json={"display_name": "Guessed member"},
        ),
        client.patch(
            f"/api/v1/households/{household_id}/authorizations/{authorization['id']}",
            headers=other_headers,
            json={"expected_version": 1, "purpose": "family-care"},
        ),
        client.post(
            f"/api/v1/households/{household_id}/authorizations/{authorization['id']}/revoke",
            headers=other_headers,
            json={"expected_version": 1},
        ),
        client.post(
            f"/api/v1/households/{other_household_id}/events",
            headers=other_headers,
            json={"member_id": member_id, "event_type": "NOTE", "payload": {"text": "x"}},
        ),
    ]

    for response in responses:
        assert response.status_code == 404
        assert response.json() == {"detail": "RESOURCE_NOT_FOUND"}


def test_non_owner_access_requires_the_granted_purpose(client: TestClient) -> None:
    household_id, member_id = create_household_member(client)
    create_authorization(client, household_id, member_id)
    event = client.post(
        f"/api/v1/households/{household_id}/events",
        headers=OWNER_HEADERS,
        json={"member_id": member_id, "event_type": "NOTE", "payload": {"text": "private"}},
    )
    assert event.status_code == 201

    missing = client.get(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": "caregiver"},
    )
    mismatched = client.get(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": "caregiver", "X-Access-Purpose": "analytics"},
    )
    malformed = client.get(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": "caregiver", "X-Access-Purpose": "x" * 65},
    )
    allowed = client.get(
        f"/api/v1/households/{household_id}/events",
        headers=CARE_HEADERS,
    )

    assert missing.status_code == 404
    assert mismatched.status_code == 404
    assert malformed.status_code == 404
    assert allowed.status_code == 200
    assert [item["id"] for item in allowed.json()] == [event.json()["id"]]


def test_authorization_update_uses_compare_and_swap_versioning(client: TestClient) -> None:
    household_id, member_id = create_household_member(client)
    authorization = create_authorization(client, household_id, member_id)
    assert authorization["version"] == 1

    listed = client.get(
        f"/api/v1/households/{household_id}/authorizations",
        headers=OWNER_HEADERS,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [authorization["id"]]

    update_payload = {
        "expected_version": 1,
        "actions": ["READ_EVENTS", "WRITE_EVENTS"],
        "valid_until": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
    }
    updated = client.patch(
        f"/api/v1/households/{household_id}/authorizations/{authorization['id']}",
        headers=OWNER_HEADERS,
        json=update_payload,
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["actions"] == ["READ_EVENTS", "WRITE_EVENTS"]

    stale = client.patch(
        f"/api/v1/households/{household_id}/authorizations/{authorization['id']}",
        headers=OWNER_HEADERS,
        json={"expected_version": 1, "purpose": "family-care"},
    )
    assert stale.status_code == 409
    assert stale.json() == {"detail": "AUTHORIZATION_VERSION_CONFLICT"}


def test_authorization_lifecycle_and_denials_write_minimal_audit(
    client: TestClient,
    db_session: Session,
) -> None:
    household_id, member_id = create_household_member(client)
    authorization = create_authorization(client, household_id, member_id)

    updated = client.patch(
        f"/api/v1/households/{household_id}/authorizations/{authorization['id']}",
        headers=OWNER_HEADERS,
        json={"expected_version": 1, "purpose": "family-care"},
    )
    assert updated.status_code == 200
    revoked = client.post(
        f"/api/v1/households/{household_id}/authorizations/{authorization['id']}/revoke",
        headers=OWNER_HEADERS,
        json={"expected_version": 2},
    )
    assert revoked.status_code == 200
    assert revoked.json()["version"] == 3

    denied = client.get(
        f"/api/v1/households/{household_id}/events",
        headers=CARE_HEADERS,
    )
    assert denied.status_code == 404

    audits = list(
        db_session.scalars(
            select(AccessAudit).order_by(AccessAudit.created_at, AccessAudit.id)
        ).all()
    )
    operations = [audit.operation for audit in audits]
    assert {"CREATE", "UPDATE", "REVOKE", "ACCESS"}.issubset(operations)
    denied_audit = next(
        audit
        for audit in audits
        if audit.operation == "ACCESS" and audit.outcome == "DENIED"
    )
    assert denied_audit.reason == "CONSENT_REVOKED"
    assert {"payload", "evidence", "health_event"}.isdisjoint(AccessAudit.__table__.columns.keys())

    audit_response = client.get(
        f"/api/v1/households/{household_id}/authorization-audits",
        headers=OWNER_HEADERS,
    )
    assert audit_response.status_code == 200
    assert len(audit_response.json()) == len(audits)


def test_expired_authorization_is_denied_and_audited(
    client: TestClient,
    db_session: Session,
) -> None:
    household_id, member_id = create_household_member(client)
    authorization = create_authorization(client, household_id, member_id)
    grant = db_session.get(CareAuthorization, authorization["id"])
    assert grant is not None
    grant.valid_until = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    response = client.get(
        f"/api/v1/households/{household_id}/events",
        headers=CARE_HEADERS,
    )
    assert response.status_code == 404
    audit = db_session.scalars(
        select(AccessAudit).where(
            AccessAudit.authorization_id == authorization["id"],
            AccessAudit.operation == "ACCESS",
        )
    ).one()
    assert audit.outcome == "DENIED"
    assert audit.reason == "AUTHORIZATION_EXPIRED"


def test_hct102_openapi_contract_is_exposed(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    assert "get" in paths["/api/v1/households/{household_id}/authorizations"]
    assert "patch" in paths[
        "/api/v1/households/{household_id}/authorizations/{authorization_id}"
    ]
    assert "get" in paths["/api/v1/households/{household_id}/authorization-audits"]


def test_hct102_migration_upgrades_existing_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "hct102-upgrade.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(REPO_ROOT / "alembic.ini"))
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        command.upgrade(config, "0002_allow_pending_health_events")
        now = datetime.now(UTC)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO household (id, name, created_by) "
                    "VALUES ('household-1', 'Existing', 'original-owner')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO member (id, household_id, display_name, role) "
                    "VALUES ('member-1', 'household-1', 'Existing member', 'SELF')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO care_authorization ("
                    "id, household_id, member_id, grantee_actor_id, data_fields, actions, "
                    "purpose, valid_from, valid_until"
                    ") VALUES ("
                    "'authorization-1', 'household-1', 'member-1', 'caregiver', "
                    "'[\"health_events\"]', '[\"READ_EVENTS\"]', 'family-care', "
                    ":valid_from, :valid_until"
                    ")"
                ),
                {
                    "valid_from": now,
                    "valid_until": now + timedelta(days=1),
                },
            )

        command.upgrade(config, "head")
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT grantor_actor_id, version FROM care_authorization "
                    "WHERE id = 'authorization-1'"
                )
            ).one()
        assert row.grantor_actor_id == "original-owner"
        assert row.version == 1
        assert "access_audit" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
        get_settings.cache_clear()
