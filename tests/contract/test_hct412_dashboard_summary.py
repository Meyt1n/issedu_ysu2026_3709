"""HCT-412: privacy-preserving household dashboard summary contract."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

OWNER_HEADERS = {"X-Actor-Id": "owner"}


def _create_household_and_member(client: TestClient) -> tuple[str, str]:
    household = client.post(
        "/api/v1/households", headers=OWNER_HEADERS, json={"name": "HCT-412 household"}
    )
    assert household.status_code == 201, household.text
    member = client.post(
        f"/api/v1/households/{household.json()['id']}/members",
        headers=OWNER_HEADERS,
        json={"display_name": "Synthetic member", "role": "SELF"},
    )
    assert member.status_code == 201, member.text
    return household.json()["id"], member.json()["id"]


def test_dashboard_summary_returns_aggregate_counts_without_health_payload(
    client: TestClient,
) -> None:
    household_id, member_id = _create_household_and_member(client)
    event = client.post(
        f"/api/v1/households/{household_id}/events",
        headers=OWNER_HEADERS,
        json={
            "member_id": member_id,
            "event_type": "medication_added",
            "confirmation_status": "CONFIRMED",
            "payload": {"drug": "Synthetic medicine"},
            "occurred_at": datetime.now(UTC).isoformat(),
        },
    )
    assert event.status_code == 201, event.text

    response = client.get(
        f"/api/v1/households/{household_id}/dashboard-summary", headers=OWNER_HEADERS
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["member_count"] == 1
    assert body["events_today"] == 1
    assert body["events_total"] == 1
    assert sum(point["count"] for point in body["week_series"]) == 1
    assert "Synthetic medicine" not in response.text
    assert "payload" not in response.text


def test_dashboard_summary_is_not_an_aggregate_side_channel_for_caregivers(
    client: TestClient,
) -> None:
    household_id, member_id = _create_household_and_member(client)
    grant = client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers=OWNER_HEADERS,
        json={
            "member_id": member_id,
            "grantee_actor_id": "caregiver",
            "data_fields": ["health_events"],
            "actions": ["READ_EVENTS"],
            "purpose": "family-care",
            "valid_until": "2030-01-01T00:00:00Z",
        },
    )
    assert grant.status_code == 201, grant.text

    response = client.get(
        f"/api/v1/households/{household_id}/dashboard-summary",
        headers={"X-Actor-Id": "caregiver", "X-Access-Purpose": "family-care"},
    )

    assert response.status_code == 404
