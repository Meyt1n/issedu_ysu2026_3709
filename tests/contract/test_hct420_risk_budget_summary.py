"""HCT-420: server-authoritative risk budget summary contract."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

OWNER_HEADERS = {"X-Actor-Id": "owner"}


def _create_household_and_member(client: TestClient) -> tuple[str, str]:
    household = client.post(
        "/api/v1/households", headers=OWNER_HEADERS, json={"name": "HCT-420 household"}
    )
    assert household.status_code == 201, household.text
    member = client.post(
        f"/api/v1/households/{household.json()['id']}/members",
        headers=OWNER_HEADERS,
        json={"display_name": "Synthetic member", "role": "SELF"},
    )
    assert member.status_code == 201, member.text
    return household.json()["id"], member.json()["id"]


def test_risk_list_reports_budget_and_suppressed_signal_count(client: TestClient) -> None:
    household_id, member_id = _create_household_and_member(client)
    for index in range(12):
        response = client.post(
            f"/api/v1/households/{household_id}/events",
            headers=OWNER_HEADERS,
            json={
                "member_id": member_id,
                "event_type": "medication_added",
                "confirmation_status": "CONFIRMED",
                "payload": {
                    "drug": f"Synthetic medicine {index}",
                    "ingredient": f"ingredient-{index}",
                },
                "occurred_at": datetime.now(UTC).isoformat(),
            },
        )
        assert response.status_code == 201, response.text

    response = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/risks",
        headers=OWNER_HEADERS,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ruleset_version"]
    assert body["non_severe_budget"] == 10
    assert body["suppressed_count"] > 0
    assert body["total"] == len(body["alerts"])
    assert body["suppressed_count"] + body["total"] >= 66
