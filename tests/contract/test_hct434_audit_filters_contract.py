"""HCT-434: owner audit pages support scope-bound action and outcome filters."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import AccessAudit

OWNER_HEADERS = {"X-Actor-Id": "owner"}


def _create_household(client: TestClient) -> str:
    response = client.post(
        "/api/v1/households", headers=OWNER_HEADERS, json={"name": "HCT-434 household"}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _seed_audits(db_session: Session, household_id: str) -> None:
    start = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)
    rows = [
        ("READ_EVENTS", "ALLOWED"),
        ("UPDATE_TIME_ZONE", "ALLOWED"),
        ("READ_EVENTS", "DENIED"),
        ("UPDATE_TIME_ZONE", "ALLOWED"),
    ]
    for index, (action, outcome) in enumerate(rows):
        db_session.add(
            AccessAudit(
                household_id=household_id,
                actor_id="owner",
                operation="READ" if action == "READ_EVENTS" else "UPDATE",
                action=action,
                data_field="health_events" if action == "READ_EVENTS" else "household.time_zone",
                purpose="test",
                outcome=outcome,
                reason=None,
                request_id=f"hct434-{index}",
                created_at=start + timedelta(seconds=index),
            )
        )
    db_session.commit()


def test_owner_can_filter_by_action_and_outcome_with_cursor_scope(
    client: TestClient, db_session: Session
) -> None:
    household_id = _create_household(client)
    _seed_audits(db_session, household_id)
    url = f"/api/v1/households/{household_id}/authorization-audits/page"

    first = client.get(
        url,
        headers=OWNER_HEADERS,
        params={"action": "UPDATE_TIME_ZONE", "outcome": "ALLOWED", "limit": 1},
    )
    assert first.status_code == 200, first.text
    first_payload = first.json()
    assert len(first_payload["items"]) == 1
    assert first_payload["items"][0]["action"] == "UPDATE_TIME_ZONE"
    assert first_payload["items"][0]["outcome"] == "ALLOWED"
    assert first_payload["has_more"] is True

    second = client.get(
        url,
        headers=OWNER_HEADERS,
        params={
            "action": "UPDATE_TIME_ZONE",
            "outcome": "ALLOWED",
            "limit": 1,
            "cursor": first_payload["next_cursor"],
        },
    )
    assert second.status_code == 200, second.text
    assert len(second.json()["items"]) == 1
    assert second.json()["has_more"] is False

    action_mismatch = client.get(
        url,
        headers=OWNER_HEADERS,
        params={
            "action": "READ_EVENTS",
            "outcome": "ALLOWED",
            "cursor": first_payload["next_cursor"],
        },
    )
    assert action_mismatch.status_code == 422
    assert action_mismatch.json()["detail"] == "AUDIT_CURSOR_INVALID"

    outcome_mismatch = client.get(
        url,
        headers=OWNER_HEADERS,
        params={
            "action": "UPDATE_TIME_ZONE",
            "outcome": "DENIED",
            "cursor": first_payload["next_cursor"],
        },
    )
    assert outcome_mismatch.status_code == 422
    assert outcome_mismatch.json()["detail"] == "AUDIT_CURSOR_INVALID"


def test_non_owner_cannot_use_audit_filters(client: TestClient) -> None:
    household_id = _create_household(client)
    response = client.get(
        f"/api/v1/households/{household_id}/authorization-audits/page",
        headers={"X-Actor-Id": "caregiver"},
        params={"action": "READ_EVENTS", "outcome": "DENIED"},
    )
    assert response.status_code == 404
