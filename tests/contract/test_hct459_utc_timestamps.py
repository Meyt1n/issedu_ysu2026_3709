"""HCT-459: outward-facing timestamps must carry an explicit timezone.

A date-time string without a designator is read as *local* time by
`Date.parse`, so a naive payload made the mobile 7-day trend land on the wrong
business day, by an amount that depended on the viewer's device. These tests
walk real responses and fail if any timestamp regresses to a naive string.
"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

OWNER_HEADERS = {"X-Actor-Id": "owner"}

# Matches a date-time string; the designator is deliberately not part of it so a
# naive value still matches and can be reported as a failure.
DATE_TIME_PREFIX = 10  # len("YYYY-MM-DD")


def _looks_like_date_time(value: str) -> bool:
    if len(value) < 19 or value[DATE_TIME_PREFIX] != "T":
        return False
    head = value[:DATE_TIME_PREFIX]
    return head.count("-") == 2 and head.replace("-", "").isdigit()


def _is_qualified(value: str) -> bool:
    if value.endswith(("Z", "z")):
        return True
    tail = value[-6:]
    return len(value) >= 6 and tail[0] in "+-" and tail[3] == ":"


def _timestamps(payload: object, path: str = "$") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            found.extend(_timestamps(value, f"{path}.{key}"))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            found.extend(_timestamps(value, f"{path}[{index}]"))
    elif isinstance(payload, str) and _looks_like_date_time(payload):
        found.append((path, payload))
    return found


def _assert_all_qualified(payload: object, label: str) -> int:
    stamps = _timestamps(payload)
    naive = [(path, value) for path, value in stamps if not _is_qualified(value)]
    assert not naive, f"{label} returned naive timestamps: {naive}"
    return len(stamps)


@pytest.fixture()
def seeded(client: TestClient) -> tuple[str, str]:
    household = client.post(
        "/api/v1/households", headers=OWNER_HEADERS, json={"name": "HCT-456 household"}
    )
    assert household.status_code == 201, household.text
    household_id = household.json()["id"]
    member = client.post(
        f"/api/v1/households/{household_id}/members",
        headers=OWNER_HEADERS,
        json={"display_name": "Synthetic member", "role": "SELF"},
    )
    assert member.status_code == 201, member.text
    member_id = member.json()["id"]
    event = client.post(
        f"/api/v1/households/{household_id}/events",
        headers=OWNER_HEADERS,
        json={
            "member_id": member_id,
            "event_type": "medication_added",
            "confirmation_status": "CONFIRMED",
            "payload": {"drug": "Synthetic medicine", "ingredient": "synthetic", "stock": 1},
            "occurred_at": datetime.now(UTC).isoformat(),
        },
    )
    assert event.status_code == 201, event.text
    return household_id, member_id


def test_household_and_member_timestamps_are_qualified(
    client: TestClient, seeded: tuple[str, str]
) -> None:
    household_id, _ = seeded

    households = client.get("/api/v1/households", headers=OWNER_HEADERS)
    members = client.get(
        f"/api/v1/households/{household_id}/members", headers=OWNER_HEADERS
    )

    assert _assert_all_qualified(households.json(), "GET /households") > 0
    assert _assert_all_qualified(members.json(), "GET /members") > 0


def test_event_timeline_timestamps_are_qualified(
    client: TestClient, seeded: tuple[str, str]
) -> None:
    household_id, member_id = seeded

    timeline = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/timeline",
        headers=OWNER_HEADERS,
    )

    body = timeline.json()
    assert body, "expected the seeded event in the timeline"
    # occurred_at / created_at / recorded_at are exactly what the trend buckets on.
    assert _assert_all_qualified(body, "GET /timeline") >= 3


def test_created_event_response_is_qualified(client: TestClient, seeded: tuple[str, str]) -> None:
    household_id, member_id = seeded

    response = client.post(
        f"/api/v1/households/{household_id}/events",
        headers=OWNER_HEADERS,
        json={
            "member_id": member_id,
            "event_type": "allergy_added",
            "confirmation_status": "CONFIRMED",
            "payload": {"allergy": "synthetic-allergen"},
            "occurred_at": datetime.now(UTC).isoformat(),
        },
    )

    assert response.status_code == 201, response.text
    assert _assert_all_qualified(response.json(), "POST /events") > 0


def test_risk_list_timestamps_are_qualified(client: TestClient, seeded: tuple[str, str]) -> None:
    household_id, member_id = seeded

    risks = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/risks",
        headers=OWNER_HEADERS,
    )

    assert risks.status_code == 200, risks.text
    _assert_all_qualified(risks.json(), "GET /risks")


def test_a_naive_string_would_be_caught(client: TestClient) -> None:
    """Guard the guard: the walker must actually reject a naive timestamp."""
    assert _looks_like_date_time("2026-08-26T01:56:09.853583")
    assert not _is_qualified("2026-08-26T01:56:09.853583")
    assert _is_qualified("2026-08-26T01:56:09.853583Z")
    assert _is_qualified("2026-08-26T09:56:09+08:00")
    with pytest.raises(AssertionError):
        _assert_all_qualified({"created_at": "2026-08-26T01:56:09"}, "synthetic")
