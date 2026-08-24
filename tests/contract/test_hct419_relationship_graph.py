"""HCT-419: server-authoritative desktop relationship graph contract."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

OWNER_HEADERS = {"X-Actor-Id": "owner"}


def _create_household_and_member(client: TestClient) -> tuple[str, str]:
    household = client.post(
        "/api/v1/households", headers=OWNER_HEADERS, json={"name": "HCT-419 household"}
    )
    assert household.status_code == 201, household.text
    member = client.post(
        f"/api/v1/households/{household.json()['id']}/members",
        headers=OWNER_HEADERS,
        json={"display_name": "Synthetic member", "role": "SELF"},
    )
    assert member.status_code == 201, member.text
    return household.json()["id"], member.json()["id"]


def _append_event(
    client: TestClient,
    household_id: str,
    member_id: str,
    *,
    event_type: str,
    payload: dict,
    confirmation_status: str = "CONFIRMED",
    compensates_event_id: str | None = None,
) -> dict:
    response = client.post(
        f"/api/v1/households/{household_id}/events",
        headers=OWNER_HEADERS,
        json={
            "member_id": member_id,
            "event_type": event_type,
            "confirmation_status": confirmation_status,
            "payload": payload,
            "compensates_event_id": compensates_event_id,
            "occurred_at": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_relationship_graph_returns_minimal_confirmed_nodes_without_payload(
    client: TestClient,
) -> None:
    household_id, member_id = _create_household_and_member(client)
    active = _append_event(
        client,
        household_id,
        member_id,
        event_type="medication_added",
        payload={"drug": "Synthetic medicine"},
    )
    hidden = _append_event(
        client,
        household_id,
        member_id,
        event_type="allergy_added",
        payload={"allergy": "Synthetic allergy"},
    )
    _append_event(
        client,
        household_id,
        member_id,
        event_type="COMPENSATION",
        payload={"reason": "synthetic correction"},
        compensates_event_id=hidden["id"],
    )
    _append_event(
        client,
        household_id,
        member_id,
        event_type="disease_added",
        payload={"disease": "Unconfirmed diagnosis"},
        confirmation_status="UNCONFIRMED",
    )

    response = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/relationship-graph",
        headers=OWNER_HEADERS,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["member_id"] == member_id
    assert body["events_count"] == 3
    assert body["nodes"] == [
        {
            "id": f"drug:{active['id']}",
            "category": "drug",
            "label": "Synthetic medicine",
            "source_event_id": active["id"],
            "source_recorded_at": active["recorded_at"],
            "source_created_by": "owner",
        }
    ]
    assert "payload" not in response.text
    assert "Synthetic allergy" not in response.text
    assert "Unconfirmed diagnosis" not in response.text


def test_relationship_graph_hides_member_after_revocation(client: TestClient) -> None:
    household_id, member_id = _create_household_and_member(client)
    _append_event(
        client,
        household_id,
        member_id,
        event_type="medication_added",
        payload={"drug": "Synthetic medicine"},
    )
    grant = client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers=OWNER_HEADERS,
        json={
            "member_id": member_id,
            "grantee_actor_id": "caregiver",
            "data_fields": ["health_events"],
            "actions": ["READ_EVENTS"],
            "purpose": "graph-review",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    assert grant.status_code == 201, grant.text
    caregiver_headers = {"X-Actor-Id": "caregiver", "X-Access-Purpose": "graph-review"}
    path = f"/api/v1/households/{household_id}/members/{member_id}/relationship-graph"

    assert client.get(path, headers=caregiver_headers).status_code == 200
    revoked = client.post(
        f"/api/v1/households/{household_id}/authorizations/{grant.json()['id']}/revoke",
        headers=OWNER_HEADERS,
        json={"expected_version": grant.json()["version"]},
    )
    assert revoked.status_code == 200, revoked.text
    assert client.get(path, headers=caregiver_headers).status_code == 404
