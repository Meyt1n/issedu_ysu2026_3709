"""HCT-431: authorization audit records retain the request correlation ID."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AccessAudit

OWNER_HEADERS = {"X-Actor-Id": "owner"}


def _create_household_and_member(client: TestClient) -> tuple[str, str]:
    household = client.post(
        "/api/v1/households", headers=OWNER_HEADERS, json={"name": "HCT-431 household"}
    )
    assert household.status_code == 201, household.text
    household_id = household.json()["id"]
    member = client.post(
        f"/api/v1/households/{household_id}/members",
        headers=OWNER_HEADERS,
        json={"display_name": "Synthetic member", "role": "DEPENDENT"},
    )
    assert member.status_code == 201, member.text
    return household_id, member.json()["id"]


def _grant_read_access(client: TestClient, household_id: str, member_id: str) -> None:
    response = client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers=OWNER_HEADERS,
        json={
            "member_id": member_id,
            "grantee_actor_id": "caregiver",
            "data_fields": ["health_events"],
            "actions": ["READ_EVENTS"],
            "purpose": "family-care",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text


def test_allowed_audit_carries_custom_request_id(
    client: TestClient, db_session: Session
) -> None:
    household_id, member_id = _create_household_and_member(client)
    _grant_read_access(client, household_id, member_id)
    request_id = "audit-check-431"

    response = client.get(
        f"/api/v1/households/{household_id}/members",
        headers={
            "X-Actor-Id": "caregiver",
            "X-Access-Purpose": "family-care",
            "X-Request-ID": request_id,
        },
    )

    assert response.status_code == 200, response.text
    assert response.headers["X-Request-ID"] == request_id
    audit = db_session.scalar(
        select(AccessAudit)
        .where(AccessAudit.actor_id == "caregiver")
        .order_by(AccessAudit.created_at.desc(), AccessAudit.id.desc())
    )
    assert audit is not None
    assert audit.outcome == "ALLOWED"
    assert audit.request_id == request_id


def test_denied_audit_carries_generated_request_id(client: TestClient, db_session: Session) -> None:
    household_id, member_id = _create_household_and_member(client)

    response = client.get(
        f"/api/v1/households/{household_id}/members",
        headers={"X-Actor-Id": "unauthorized"},
    )

    assert response.status_code == 404
    generated_request_id = response.headers["X-Request-ID"]
    audit = db_session.scalar(
        select(AccessAudit)
        .where(
            AccessAudit.actor_id == "unauthorized",
            AccessAudit.household_id == household_id,
        )
        .order_by(AccessAudit.created_at.desc(), AccessAudit.id.desc())
    )
    assert audit is not None
    assert audit.outcome == "DENIED"
    assert audit.request_id == generated_request_id


def test_invalid_request_id_is_replaced_and_context_does_not_leak(
    client: TestClient, db_session: Session
) -> None:
    household_id, member_id = _create_household_and_member(client)
    _grant_read_access(client, household_id, member_id)
    invalid = "bad id with spaces"

    first = client.get(
        f"/api/v1/households/{household_id}/members",
        headers={
            "X-Actor-Id": "caregiver",
            "X-Access-Purpose": "family-care",
            "X-Request-ID": invalid,
        },
    )
    second = client.get(
        f"/api/v1/households/{household_id}/members",
        headers={
            "X-Actor-Id": "caregiver",
            "X-Access-Purpose": "family-care",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.headers["X-Request-ID"] != invalid
    assert second.headers["X-Request-ID"] != first.headers["X-Request-ID"]
    audits = list(
        db_session.scalars(
            select(AccessAudit)
            .where(AccessAudit.actor_id == "caregiver")
            .order_by(AccessAudit.created_at, AccessAudit.id)
        )
    )
    assert len(audits) >= 2
    assert audits[-2].request_id == first.headers["X-Request-ID"]
    assert audits[-1].request_id == second.headers["X-Request-ID"]
