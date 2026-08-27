"""HCT-457: the risk list must explain merging and the daily budget.

HCT-420 already pinned the aggregate budget summary. These tests pin the
per-alert audit metadata the mobile client renders, and the held-back alerts that
used to be reported only as a count.
"""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

OWNER_HEADERS = {"X-Actor-Id": "owner"}


def _household_with_member(client: TestClient, name: str) -> tuple[str, str]:
    household = client.post(
        "/api/v1/households", headers=OWNER_HEADERS, json={"name": name}
    )
    assert household.status_code == 201, household.text
    member = client.post(
        f"/api/v1/households/{household.json()['id']}/members",
        headers=OWNER_HEADERS,
        json={"display_name": "Synthetic member", "role": "SELF"},
    )
    assert member.status_code == 201, member.text
    return household.json()["id"], member.json()["id"]


def _add_low_stock_medicines(
    client: TestClient,
    household_id: str,
    member_id: str,
    count: int,
) -> None:
    for index in range(count):
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
                    "stock": 1,
                },
                "occurred_at": datetime.now(UTC).isoformat(),
            },
        )
        assert response.status_code == 201, response.text


def _risks(client: TestClient, household_id: str, member_id: str) -> dict:
    response = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/risks",
        headers=OWNER_HEADERS,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_every_returned_alert_carries_audit_metadata(client: TestClient) -> None:
    household_id, member_id = _household_with_member(client, "HCT-457 audit")
    _add_low_stock_medicines(client, household_id, member_id, 3)

    body = _risks(client, household_id, member_id)

    assert body["alerts"], "expected at least one alert from low stock"
    for alert in body["alerts"]:
        assert alert["deduplication_key"], alert
        assert alert["merged_count"] >= 1, alert
        assert alert["budget_status"] in {"VISIBLE", "SEVERE_EXEMPT"}, alert
        assert alert["budget_reason"], alert
        # Visible alerts have nothing to wait for.
        assert alert["next_visible_at"] is None, alert
        # Desensitized: a count, never event payload text.
        assert "证据事件" in alert["evidence_summary"], alert


def test_budget_held_back_alerts_are_returned_and_explained(client: TestClient) -> None:
    household_id, member_id = _household_with_member(client, "HCT-457 budget")
    _add_low_stock_medicines(client, household_id, member_id, 14)

    body = _risks(client, household_id, member_id)

    assert body["suppressed_count"] > 0
    held = body["suppressed_alerts"]
    # The count must match what is actually reported, not just be a number.
    assert len(held) == body["suppressed_count"]
    for alert in held:
        assert alert["budget_status"] == "SUPPRESSED", alert
        assert alert["budget_reason"], alert
        assert alert["next_visible_at"], "a held-back alert must say when it returns"
        assert alert["deduplication_key"], alert
    visible_keys = {alert["deduplication_key"] for alert in body["alerts"]}
    assert visible_keys.isdisjoint({alert["deduplication_key"] for alert in held})


def test_severe_alerts_are_marked_exempt_not_suppressed(client: TestClient) -> None:
    household_id, member_id = _household_with_member(client, "HCT-457 severe")
    # An allergy plus a matching medicine yields a SEVERE allergy_conflict.
    for payload, event_type in (
        ({"allergy": "aspirin"}, "allergy_added"),
        ({"drug": "Aspirin tablet", "ingredient": "aspirin", "stock": 30}, "medication_added"),
    ):
        response = client.post(
            f"/api/v1/households/{household_id}/events",
            headers=OWNER_HEADERS,
            json={
                "member_id": member_id,
                "event_type": event_type,
                "confirmation_status": "CONFIRMED",
                "payload": payload,
                "occurred_at": datetime.now(UTC).isoformat(),
            },
        )
        assert response.status_code == 201, response.text

    body = _risks(client, household_id, member_id)

    severe = [alert for alert in body["alerts"] if alert["level"] == "SEVERE"]
    assert severe, "expected a SEVERE allergy conflict"
    for alert in severe:
        assert alert["budget_status"] == "SEVERE_EXEMPT"
    assert all(alert["level"] != "SEVERE" for alert in body["suppressed_alerts"])


def test_no_alerts_means_empty_lists_not_missing_fields(client: TestClient) -> None:
    household_id, member_id = _household_with_member(client, "HCT-457 empty")

    body = _risks(client, household_id, member_id)

    assert body["alerts"] == []
    assert body["suppressed_alerts"] == []
    assert body["suppressed_count"] == 0
