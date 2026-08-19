"""HCT-413 API contract: risk acknowledgement is server-confirmed and idempotent."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AccessAudit, RiskAcknowledgement


def _create_scope(client: TestClient, *, owner: str = "owner") -> tuple[str, str]:
    headers = {"X-Actor-Id": owner}
    household = client.post("/api/v1/households", headers=headers, json={"name": "HCT-413"})
    assert household.status_code == 201, household.text
    household_id = household.json()["id"]
    member = client.post(
        f"/api/v1/households/{household_id}/members",
        headers=headers,
        json={"display_name": "成员", "role": "SELF"},
    )
    assert member.status_code == 201, member.text
    member_id = member.json()["id"]
    event = client.post(
        f"/api/v1/households/{household_id}/events",
        headers=headers,
        json={
            "member_id": member_id,
            "event_type": "medication_added",
            "source": "MANUAL",
            "confirmation_status": "CONFIRMED",
            "payload": {"drug": "测试药", "expiry_date": "2000-01-01"},
        },
    )
    assert event.status_code == 201, event.text
    return household_id, member_id


def _risk(client: TestClient, household_id: str, member_id: str) -> dict:
    response = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/risks",
        headers={"X-Actor-Id": "owner"},
    )
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["alerts"] if item["rule_id"] == "expiry_check")


def test_acknowledgement_returns_receipt_and_replays_without_duplicate(
    client: TestClient,
    db_session: Session,
) -> None:
    household_id, member_id = _create_scope(client)
    alert = _risk(client, household_id, member_id)
    path = (
        f"/api/v1/households/{household_id}/members/{member_id}"
        f"/risks/{alert['rule_id']}/acknowledge"
    )
    headers = {"X-Actor-Id": "owner", "Idempotency-Key": "ack-1"}
    payload = {
        "rule_version": alert["rule_version"],
        "risk_fingerprint": alert["risk_fingerprint"],
    }

    first = client.post(path, headers=headers, json=payload)
    assert first.status_code == 200, first.text
    receipt = first.json()
    assert receipt["actor_id"] == "owner"
    assert receipt["rule_version"] == "rules-v0"
    assert receipt["replayed"] is False
    assert first.headers.get("X-Request-ID")

    replay = client.post(path, headers=headers, json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["receipt_id"] == receipt["receipt_id"]
    assert replay.json()["replayed"] is True

    rows = list(db_session.scalars(select(RiskAcknowledgement)).all())
    assert len(rows) == 1
    audits = list(
        db_session.scalars(select(AccessAudit).where(AccessAudit.operation == "RISK_ACK")).all()
    )
    assert len(audits) == 1
    assert audits[0].request_id
    assert {"payload", "evidence", "message"}.isdisjoint(AccessAudit.__table__.columns.keys())


def test_acknowledgement_rejects_key_conflict_and_stale_signal(client: TestClient) -> None:
    household_id, member_id = _create_scope(client)
    alert = _risk(client, household_id, member_id)
    path = (
        f"/api/v1/households/{household_id}/members/{member_id}"
        f"/risks/{alert['rule_id']}/acknowledge"
    )
    headers = {"X-Actor-Id": "owner", "Idempotency-Key": "ack-conflict"}
    payload = {
        "rule_version": alert["rule_version"],
        "risk_fingerprint": alert["risk_fingerprint"],
    }
    assert client.post(path, headers=headers, json=payload).status_code == 200

    changed_key = {**headers, "Idempotency-Key": "ack-other"}
    stale = {**payload, "risk_fingerprint": "b" * 64}
    response = client.post(path, headers=changed_key, json=stale)
    assert response.status_code == 409
    assert response.json() == {"detail": "RISK_VERSION_CONFLICT"}

    same_key_changed = {**payload, "risk_fingerprint": "c" * 64}
    response = client.post(path, headers=headers, json=same_key_changed)
    assert response.status_code == 409
    assert response.json() == {"detail": "IDEMPOTENCY_KEY_CONFLICT"}


def test_acknowledgement_hides_revoked_caregiver_and_requires_current_risk(
    client: TestClient,
) -> None:
    household_id, member_id = _create_scope(client)
    grant = client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_id,
            "grantee_actor_id": "caregiver",
            "data_fields": ["risk_alerts"],
            "actions": ["ACK_RISK"],
            "purpose": "family-care",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    assert grant.status_code == 201, grant.text
    revoked = client.post(
        f"/api/v1/households/{household_id}/authorizations/{grant.json()['id']}/revoke",
        headers={"X-Actor-Id": "owner"},
        json={"expected_version": 1},
    )
    assert revoked.status_code == 200, revoked.text
    alert = _risk(client, household_id, member_id)
    path = (
        f"/api/v1/households/{household_id}/members/{member_id}"
        f"/risks/{alert['rule_id']}/acknowledge"
    )
    denied = client.post(
        path,
        headers={
            "X-Actor-Id": "caregiver",
            "X-Access-Purpose": "family-care",
            "Idempotency-Key": "revoked-1",
        },
        json={
            "rule_version": alert["rule_version"],
            "risk_fingerprint": alert["risk_fingerprint"],
        },
    )
    assert denied.status_code == 404
    assert denied.json() == {"detail": "RESOURCE_NOT_FOUND"}

    missing = client.post(
        f"/api/v1/households/{household_id}/members/{member_id}/risks/missing/acknowledge",
        headers={"X-Actor-Id": "owner", "Idempotency-Key": "missing-1"},
        json={"rule_version": "rules-v0", "risk_fingerprint": "d" * 64},
    )
    assert missing.status_code == 404
    assert missing.json() == {"detail": "RISK_NOT_FOUND"}
