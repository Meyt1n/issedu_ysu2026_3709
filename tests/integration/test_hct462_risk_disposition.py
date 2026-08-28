"""HCT-462: auditable risk handling actions and bounded history."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AccessAudit, RiskDisposition


def _create_scope(client: TestClient, *, owner: str = "owner") -> tuple[str, str]:
    headers = {"X-Actor-Id": owner}
    household = client.post("/api/v1/households", headers=headers, json={"name": "HCT-462"})
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


def _path(household_id: str, member_id: str, rule_id: str) -> str:
    return (
        f"/api/v1/households/{household_id}/members/{member_id}"
        f"/risks/{rule_id}/dispositions"
    )


def _payload(alert: dict, **changes: object) -> dict:
    value = {
        "rule_version": alert["rule_version"],
        "risk_fingerprint": alert["risk_fingerprint"],
        "action": "NOTE",
        "note": "已联系照护者核对提醒",
    }
    value.update(changes)
    return value


def _grant_caregiver(client: TestClient, household_id: str, member_id: str) -> str:
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
    return grant.json()["id"]


def test_owner_can_record_actions_and_read_bounded_history(
    client: TestClient,
    db_session: Session,
) -> None:
    household_id, member_id = _create_scope(client)
    alert = _risk(client, household_id, member_id)
    path = _path(household_id, member_id, alert["rule_id"])

    note = client.post(
        path,
        headers={"X-Actor-Id": "owner", "Idempotency-Key": "disposition-note-1"},
        json=_payload(alert),
    )
    assert note.status_code == 201, note.text
    receipt = note.json()
    assert receipt["action"] == "NOTE"
    assert receipt["actor_id"] == "owner"
    assert receipt["replayed"] is False
    assert note.headers.get("X-Request-ID")

    snooze = client.post(
        path,
        headers={"X-Actor-Id": "owner", "Idempotency-Key": "disposition-snooze-1"},
        json=_payload(
            alert,
            action="SNOOZE",
            note="明天早上再次查看",
            snooze_until=(datetime.now(UTC) + timedelta(hours=2)).isoformat(),
        ),
    )
    assert snooze.status_code == 201, snooze.text
    assert snooze.json()["snooze_until"].endswith("Z")

    replay = client.post(
        path,
        headers={"X-Actor-Id": "owner", "Idempotency-Key": "disposition-note-1"},
        json=_payload(alert),
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["disposition_id"] == receipt["disposition_id"]
    assert replay.json()["replayed"] is True

    history = client.get(path, headers={"X-Actor-Id": "owner"})
    assert history.status_code == 200, history.text
    assert history.json()["total"] == 2
    assert {item["action"] for item in history.json()["items"]} == {"NOTE", "SNOOZE"}

    filtered = client.get(
        path,
        headers={"X-Actor-Id": "owner"},
        params={"risk_fingerprint": alert["risk_fingerprint"], "limit": 1},
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] == 1
    assert len(list(db_session.scalars(select(RiskDisposition)).all())) == 2
    audits = list(
        db_session.scalars(
            select(AccessAudit).where(AccessAudit.operation == "RISK_DISPOSITION")
        ).all()
    )
    assert len(audits) == 2
    assert all(audit.request_id for audit in audits)
    assert {"payload", "evidence", "message"}.isdisjoint(RiskDisposition.__table__.columns.keys())


def test_handoff_requires_authorized_target_and_snooze_has_time_bounds(
    client: TestClient,
) -> None:
    household_id, member_id = _create_scope(client)
    alert = _risk(client, household_id, member_id)
    path = _path(household_id, member_id, alert["rule_id"])

    self_handoff = client.post(
        path,
        headers={"X-Actor-Id": "owner", "Idempotency-Key": "handoff-self"},
        json=_payload(alert, action="HANDOFF", target_actor_id="owner"),
    )
    assert self_handoff.status_code == 422
    assert self_handoff.json() == {"detail": "HANDOFF_TARGET_SELF"}

    unknown_target = client.post(
        path,
        headers={"X-Actor-Id": "owner", "Idempotency-Key": "handoff-unknown"},
        json=_payload(alert, action="HANDOFF", target_actor_id="someone-else"),
    )
    assert unknown_target.status_code == 422
    assert unknown_target.json() == {"detail": "HANDOFF_TARGET_NOT_AUTHORIZED"}

    grant_id = _grant_caregiver(client, household_id, member_id)
    handoff = client.post(
        path,
        headers={"X-Actor-Id": "owner", "Idempotency-Key": "handoff-caregiver"},
        json=_payload(
            alert,
            action="HANDOFF",
            note="交由授权照护者跟进",
            target_actor_id="caregiver",
        ),
    )
    assert handoff.status_code == 201, handoff.text
    assert handoff.json()["target_actor_id"] == "caregiver"

    past = client.post(
        path,
        headers={"X-Actor-Id": "owner", "Idempotency-Key": "snooze-past"},
        json=_payload(
            alert,
            action="SNOOZE",
            note="时间无效",
            snooze_until=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        ),
    )
    assert past.status_code == 422
    assert past.json() == {"detail": "SNOOZE_UNTIL_PAST"}

    too_far = client.post(
        path,
        headers={"X-Actor-Id": "owner", "Idempotency-Key": "snooze-far"},
        json=_payload(
            alert,
            action="SNOOZE",
            note="时间过远",
            snooze_until=(datetime.now(UTC) + timedelta(days=8)).isoformat(),
        ),
    )
    assert too_far.status_code == 422
    assert too_far.json() == {"detail": "SNOOZE_UNTIL_TOO_FAR"}

    revoked = client.post(
        f"/api/v1/households/{household_id}/authorizations/{grant_id}/revoke",
        headers={"X-Actor-Id": "owner"},
        json={"expected_version": 1},
    )
    assert revoked.status_code == 200, revoked.text
    denied = client.post(
        path,
        headers={
            "X-Actor-Id": "caregiver",
            "X-Access-Purpose": "family-care",
            "Idempotency-Key": "handoff-revoked",
        },
        json=_payload(alert, action="NOTE", note="撤权后不应写入"),
    )
    assert denied.status_code == 404
    assert denied.json() == {"detail": "RESOURCE_NOT_FOUND"}


def test_disposition_rejects_stale_signal_and_idempotency_conflict(client: TestClient) -> None:
    household_id, member_id = _create_scope(client)
    alert = _risk(client, household_id, member_id)
    path = _path(household_id, member_id, alert["rule_id"])
    headers = {"X-Actor-Id": "owner", "Idempotency-Key": "disposition-conflict"}
    first = client.post(path, headers=headers, json=_payload(alert))
    assert first.status_code == 201, first.text

    changed = client.post(
        path,
        headers=headers,
        json=_payload(alert, note="同一幂等键不能改载荷"),
    )
    assert changed.status_code == 409
    assert changed.json() == {"detail": "IDEMPOTENCY_KEY_CONFLICT"}

    stale = client.post(
        path,
        headers={"X-Actor-Id": "owner", "Idempotency-Key": "disposition-stale"},
        json=_payload(alert, risk_fingerprint="f" * 64),
    )
    assert stale.status_code == 409
    assert stale.json() == {"detail": "RISK_VERSION_CONFLICT"}

    no_access = client.post(
        path,
        headers={"X-Actor-Id": "outsider", "Idempotency-Key": "disposition-outside"},
        json=_payload(alert),
    )
    assert no_access.status_code == 404
    assert no_access.json() == {"detail": "RESOURCE_NOT_FOUND"}


def test_disposition_schema_requires_action_specific_fields(client: TestClient) -> None:
    household_id, member_id = _create_scope(client)
    alert = _risk(client, household_id, member_id)
    path = _path(household_id, member_id, alert["rule_id"])
    headers = {"X-Actor-Id": "owner", "Idempotency-Key": "schema-invalid"}

    for payload in (
        _payload(alert, action="HANDOFF"),
        _payload(alert, action="SNOOZE"),
        _payload(alert, action="NOTE", note="  "),
    ):
        response = client.post(path, headers=headers, json=payload)
        assert response.status_code == 422, response.text
