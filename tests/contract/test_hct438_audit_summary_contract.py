"""HCT-438: owner-only audit summary returns aggregate metadata only."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import AccessAudit

OWNER_HEADERS = {"X-Actor-Id": "owner"}


def _create_household(client: TestClient) -> str:
    response = client.post(
        "/api/v1/households", headers=OWNER_HEADERS, json={"name": "HCT-438 household"}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _seed_audits(db_session: Session, household_id: str) -> None:
    start = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    rows = [
        ("READ_EVENTS", "ALLOWED"),
        ("READ_EVENTS", "ALLOWED"),
        ("UPDATE_TIME_ZONE", "ALLOWED"),
        ("READ_EVENTS", "DENIED"),
        ("AUTH_LOGIN", "SUCCESS"),
    ]
    for index, (action, outcome) in enumerate(rows):
        db_session.add(
            AccessAudit(
                household_id=household_id,
                actor_id=f"actor-{index}",
                operation="READ" if action == "READ_EVENTS" else "UPDATE",
                action=action,
                data_field="health_events" if action == "READ_EVENTS" else "household",
                purpose="test",
                outcome=outcome,
                reason=None,
                request_id=f"hct438-{index}",
                created_at=start + timedelta(seconds=index),
            )
        )
    db_session.commit()


def test_owner_can_read_minimal_audit_summary(
    client: TestClient, db_session: Session
) -> None:
    household_id = _create_household(client)
    _seed_audits(db_session, household_id)

    response = client.get(
        f"/api/v1/households/{household_id}/authorization-audits/summary",
        headers=OWNER_HEADERS,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 5
    assert body["by_action"] == {
        "AUTH_LOGIN": 1,
        "READ_EVENTS": 3,
        "UPDATE_TIME_ZONE": 1,
    }
    assert body["by_outcome"] == {"ALLOWED": 3, "DENIED": 1, "SUCCESS": 1}
    assert body["generated_at"]
    for forbidden in ("actor_id", "request_id", "payload", "evidence", "health_events"):
        assert forbidden not in response.text


def test_non_owner_cannot_read_audit_summary(client: TestClient) -> None:
    household_id = _create_household(client)
    response = client.get(
        f"/api/v1/households/{household_id}/authorization-audits/summary",
        headers={"X-Actor-Id": "caregiver"},
    )
    assert response.status_code == 404
