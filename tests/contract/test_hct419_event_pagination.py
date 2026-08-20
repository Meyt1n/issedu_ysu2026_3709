"""HCT-419: authorization-safe health-event cursor pagination contract."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

OWNER_HEADERS = {"X-Actor-Id": "owner"}


def _create_household_and_members(client: TestClient) -> tuple[str, str, str]:
    household = client.post(
        "/api/v1/households", headers=OWNER_HEADERS, json={"name": "HCT-419 household"}
    )
    assert household.status_code == 201, household.text
    household_id = household.json()["id"]
    members = []
    for name in ("Member A", "Member B"):
        response = client.post(
            f"/api/v1/households/{household_id}/members",
            headers=OWNER_HEADERS,
            json={"display_name": name, "role": "DEPENDENT"},
        )
        assert response.status_code == 201, response.text
        members.append(response.json()["id"])
    return household_id, members[0], members[1]


def _append_event(client: TestClient, household_id: str, member_id: str, index: int) -> None:
    response = client.post(
        f"/api/v1/households/{household_id}/events",
        headers=OWNER_HEADERS,
        json={
            "member_id": member_id,
            "event_type": "NOTE",
            "confirmation_status": "CONFIRMED",
            "payload": {"index": index},
            "occurred_at": (datetime.now(UTC) + timedelta(seconds=index)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text


def test_event_pages_are_stable_and_do_not_repeat_items(client: TestClient) -> None:
    household_id, member_id, _ = _create_household_and_members(client)
    for index in range(3):
        _append_event(client, household_id, member_id, index)

    first = client.get(
        f"/api/v1/households/{household_id}/events/page",
        headers=OWNER_HEADERS,
        params={"member_id": member_id, "limit": 2},
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert len(first_body["items"]) == 2
    assert first_body["has_more"] is True
    assert first_body["next_cursor"]

    second = client.get(
        f"/api/v1/households/{household_id}/events/page",
        headers=OWNER_HEADERS,
        params={
            "member_id": member_id,
            "limit": 2,
            "cursor": first_body["next_cursor"],
        },
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert len(second_body["items"]) == 1
    assert second_body["has_more"] is False
    assert second_body["next_cursor"] is None
    assert {
        item["id"] for item in first_body["items"]
    }.isdisjoint(item["id"] for item in second_body["items"])


def test_event_page_cursor_is_bound_to_scope_and_authorization(client: TestClient) -> None:
    household_id, member_a, member_b = _create_household_and_members(client)
    _append_event(client, household_id, member_a, 1)
    _append_event(client, household_id, member_a, 2)
    _append_event(client, household_id, member_b, 3)

    first = client.get(
        f"/api/v1/households/{household_id}/events/page",
        headers=OWNER_HEADERS,
        params={"member_id": member_a, "limit": 1},
    )
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor
    wrong_scope = client.get(
        f"/api/v1/households/{household_id}/events/page",
        headers=OWNER_HEADERS,
        params={"member_id": member_b, "cursor": cursor},
    )
    assert wrong_scope.status_code == 422
    assert wrong_scope.json() == {"detail": "EVENT_CURSOR_INVALID"}

    # A malformed cursor is rejected without attempting a broad query.
    malformed = client.get(
        f"/api/v1/households/{household_id}/events/page",
        headers=OWNER_HEADERS,
        params={"member_id": member_a, "cursor": "tampered.cursor"},
    )
    assert malformed.status_code == 422
    assert malformed.json() == {"detail": "EVENT_CURSOR_INVALID"}


def test_event_page_rechecks_revoked_authorization(client: TestClient) -> None:
    household_id, member_id, _ = _create_household_and_members(client)
    _append_event(client, household_id, member_id, 1)
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
    caregiver_headers = {"X-Actor-Id": "caregiver", "X-Access-Purpose": "family-care"}
    visible = client.get(
        f"/api/v1/households/{household_id}/events/page",
        headers=caregiver_headers,
        params={"member_id": member_id, "limit": 1},
    )
    assert visible.status_code == 200, visible.text
    revoke = client.post(
        f"/api/v1/households/{household_id}/authorizations/{grant.json()['id']}/revoke",
        headers=OWNER_HEADERS,
        json={"expected_version": 1},
    )
    assert revoke.status_code == 200, revoke.text
    denied = client.get(
        f"/api/v1/households/{household_id}/events/page",
        headers=caregiver_headers,
        params={"member_id": member_id, "limit": 1},
    )
    assert denied.status_code == 404
