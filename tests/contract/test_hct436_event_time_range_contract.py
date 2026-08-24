"""HCT-436: event pages bind occurred-at time ranges to their cursors."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

OWNER_HEADERS = {"X-Actor-Id": "owner"}


def _create_household_and_member(client: TestClient) -> tuple[str, str]:
    household = client.post(
        "/api/v1/households", headers=OWNER_HEADERS, json={"name": "HCT-436 household"}
    )
    assert household.status_code == 201, household.text
    household_id = household.json()["id"]
    member = client.post(
        f"/api/v1/households/{household_id}/members",
        headers=OWNER_HEADERS,
        json={"display_name": "HCT-436 member", "role": "DEPENDENT"},
    )
    assert member.status_code == 201, member.text
    return household_id, member.json()["id"]


def _append_event(
    client: TestClient,
    household_id: str,
    member_id: str,
    *,
    occurred_at: datetime,
    index: int,
) -> None:
    response = client.post(
        f"/api/v1/households/{household_id}/events",
        headers=OWNER_HEADERS,
        json={
            "member_id": member_id,
            "event_type": "NOTE",
            "confirmation_status": "CONFIRMED",
            "payload": {"index": index},
            "occurred_at": occurred_at.isoformat(),
        },
    )
    assert response.status_code == 201, response.text


def test_owner_can_page_events_in_an_occurred_at_window(client: TestClient) -> None:
    household_id, member_id = _create_household_and_member(client)
    _append_event(
        client,
        household_id,
        member_id,
        occurred_at=datetime(2026, 8, 19, 12, 0, tzinfo=UTC),
        index=1,
    )
    _append_event(
        client,
        household_id,
        member_id,
        occurred_at=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        index=2,
    )
    _append_event(
        client,
        household_id,
        member_id,
        occurred_at=datetime(2026, 8, 21, 12, 0, tzinfo=UTC),
        index=3,
    )
    _append_event(
        client,
        household_id,
        member_id,
        occurred_at=datetime(2026, 8, 22, 12, 0, tzinfo=UTC),
        index=4,
    )
    url = f"/api/v1/households/{household_id}/events/page"
    filters = {
        "member_id": member_id,
        "occurred_from": "2026-08-20T00:00:00Z",
        "occurred_until": "2026-08-21T23:59:59Z",
        "limit": 1,
    }

    first = client.get(url, headers=OWNER_HEADERS, params=filters)
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert len(first_body["items"]) == 1
    assert first_body["items"][0]["occurred_at"].startswith("2026-08-20")
    assert first_body["has_more"] is True

    second = client.get(
        url,
        headers=OWNER_HEADERS,
        params={**filters, "cursor": first_body["next_cursor"]},
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert len(second_body["items"]) == 1
    assert second_body["items"][0]["occurred_at"].startswith("2026-08-21")
    assert second_body["has_more"] is False
    assert first_body["items"][0]["id"] != second_body["items"][0]["id"]

    from_mismatch = client.get(
        url,
        headers=OWNER_HEADERS,
        params={
            **filters,
            "occurred_from": "2026-08-19T00:00:00Z",
            "cursor": first_body["next_cursor"],
        },
    )
    assert from_mismatch.status_code == 422
    assert from_mismatch.json()["detail"] == "EVENT_CURSOR_INVALID"

    until_mismatch = client.get(
        url,
        headers=OWNER_HEADERS,
        params={
            **filters,
            "occurred_until": "2026-08-22T23:59:59Z",
            "cursor": first_body["next_cursor"],
        },
    )
    assert until_mismatch.status_code == 422
    assert until_mismatch.json()["detail"] == "EVENT_CURSOR_INVALID"


def test_event_page_rejects_reversed_time_range(client: TestClient) -> None:
    household_id, member_id = _create_household_and_member(client)
    response = client.get(
        f"/api/v1/households/{household_id}/events/page",
        headers=OWNER_HEADERS,
        params={
            "member_id": member_id,
            "occurred_from": "2026-08-22T00:00:00Z",
            "occurred_until": "2026-08-21T00:00:00Z",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "EVENT_TIME_RANGE_INVALID"
