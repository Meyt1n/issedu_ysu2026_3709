"""HCT-435: event-type and confirmation filters stay bound to event cursors."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

OWNER_HEADERS = {"X-Actor-Id": "owner"}


def _create_household_and_member(client: TestClient) -> tuple[str, str]:
    household = client.post(
        "/api/v1/households", headers=OWNER_HEADERS, json={"name": "HCT-435 household"}
    )
    assert household.status_code == 201, household.text
    household_id = household.json()["id"]
    member = client.post(
        f"/api/v1/households/{household_id}/members",
        headers=OWNER_HEADERS,
        json={"display_name": "HCT-435 member", "role": "DEPENDENT"},
    )
    assert member.status_code == 201, member.text
    return household_id, member.json()["id"]


def _append_event(
    client: TestClient,
    household_id: str,
    member_id: str,
    *,
    event_type: str,
    confirmation_status: str,
    index: int,
) -> None:
    response = client.post(
        f"/api/v1/households/{household_id}/events",
        headers=OWNER_HEADERS,
        json={
            "member_id": member_id,
            "event_type": event_type,
            "confirmation_status": confirmation_status,
            "payload": {"index": index},
            "occurred_at": (datetime.now(UTC) + timedelta(seconds=index)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text


def test_owner_can_filter_events_and_continue_with_matching_cursor(
    client: TestClient,
) -> None:
    household_id, member_id = _create_household_and_member(client)
    _append_event(
        client,
        household_id,
        member_id,
        event_type="MEDICATION",
        confirmation_status="CONFIRMED",
        index=1,
    )
    _append_event(
        client,
        household_id,
        member_id,
        event_type="VITAL_SIGN",
        confirmation_status="CONFIRMED",
        index=2,
    )
    _append_event(
        client,
        household_id,
        member_id,
        event_type="MEDICATION",
        confirmation_status="CONFIRMED",
        index=3,
    )
    _append_event(
        client,
        household_id,
        member_id,
        event_type="MEDICATION",
        confirmation_status="UNCONFIRMED",
        index=4,
    )
    url = f"/api/v1/households/{household_id}/events/page"
    filters = {
        "member_id": member_id,
        "event_type": "MEDICATION",
        "confirmation_status": "CONFIRMED",
        "limit": 1,
    }

    first = client.get(url, headers=OWNER_HEADERS, params=filters)
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert len(first_body["items"]) == 1
    assert first_body["items"][0]["event_type"] == "MEDICATION"
    assert first_body["items"][0]["confirmation_status"] == "CONFIRMED"
    assert first_body["has_more"] is True

    second = client.get(
        url,
        headers=OWNER_HEADERS,
        params={**filters, "cursor": first_body["next_cursor"]},
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert len(second_body["items"]) == 1
    assert second_body["items"][0]["event_type"] == "MEDICATION"
    assert second_body["items"][0]["confirmation_status"] == "CONFIRMED"
    assert second_body["has_more"] is False
    assert first_body["items"][0]["id"] != second_body["items"][0]["id"]

    action_mismatch = client.get(
        url,
        headers=OWNER_HEADERS,
        params={
            **filters,
            "event_type": "VITAL_SIGN",
            "cursor": first_body["next_cursor"],
        },
    )
    assert action_mismatch.status_code == 422
    assert action_mismatch.json()["detail"] == "EVENT_CURSOR_INVALID"

    status_mismatch = client.get(
        url,
        headers=OWNER_HEADERS,
        params={
            **filters,
            "confirmation_status": "UNCONFIRMED",
            "cursor": first_body["next_cursor"],
        },
    )
    assert status_mismatch.status_code == 422
    assert status_mismatch.json()["detail"] == "EVENT_CURSOR_INVALID"


def test_event_filter_does_not_bypass_member_authorization(client: TestClient) -> None:
    household_id, member_id = _create_household_and_member(client)
    _append_event(
        client,
        household_id,
        member_id,
        event_type="MEDICATION",
        confirmation_status="CONFIRMED",
        index=1,
    )

    response = client.get(
        f"/api/v1/households/{household_id}/events/page",
        headers={"X-Actor-Id": "caregiver"},
        params={
            "member_id": member_id,
            "event_type": "MEDICATION",
            "confirmation_status": "CONFIRMED",
        },
    )
    assert response.status_code == 404
