"""HCT-432: owner-only, scope-bound pagination for authorization audits."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import AccessAudit

OWNER_HEADERS = {"X-Actor-Id": "owner"}


def _create_household(client: TestClient) -> str:
    response = client.post(
        "/api/v1/households", headers=OWNER_HEADERS, json={"name": "HCT-432 household"}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _seed_audits(db_session: Session, household_id: str) -> None:
    start = datetime(2026, 8, 22, 9, 0, tzinfo=UTC)
    for index in range(4):
        db_session.add(
            AccessAudit(
                household_id=household_id,
                actor_id="owner",
                operation="READ",
                action="READ_EVENTS",
                data_field="health_events",
                purpose="test",
                outcome="ALLOWED",
                reason=None,
                request_id="request-a" if index < 2 else "request-b",
                created_at=start + timedelta(seconds=index),
            )
        )
    db_session.commit()


def test_owner_can_page_and_filter_audits_without_duplicates(
    client: TestClient, db_session: Session
) -> None:
    household_id = _create_household(client)
    _seed_audits(db_session, household_id)
    url = f"/api/v1/households/{household_id}/authorization-audits/page"

    first = client.get(url, headers=OWNER_HEADERS, params={"limit": 2})
    assert first.status_code == 200, first.text
    first_payload = first.json()
    assert len(first_payload["items"]) == 2
    assert first_payload["has_more"] is True

    second = client.get(
        url,
        headers=OWNER_HEADERS,
        params={"limit": 2, "cursor": first_payload["next_cursor"]},
    )
    assert second.status_code == 200, second.text
    second_payload = second.json()
    assert len(second_payload["items"]) == 2
    assert second_payload["has_more"] is False
    ids = [item["id"] for item in first_payload["items"] + second_payload["items"]]
    assert len(ids) == len(set(ids)) == 4

    filtered = client.get(
        url,
        headers=OWNER_HEADERS,
        params={"request_id": "request-a", "limit": 1},
    )
    assert filtered.status_code == 200, filtered.text
    filtered_payload = filtered.json()
    assert len(filtered_payload["items"]) == 1
    assert filtered_payload["items"][0]["request_id"] == "request-a"
    assert filtered_payload["has_more"] is True

    filtered_next = client.get(
        url,
        headers=OWNER_HEADERS,
        params={
            "request_id": "request-a",
            "limit": 1,
            "cursor": filtered_payload["next_cursor"],
        },
    )
    assert filtered_next.status_code == 200, filtered_next.text
    assert [item["request_id"] for item in filtered_next.json()["items"]] == ["request-a"]

    reused_for_other_filter = client.get(
        url,
        headers=OWNER_HEADERS,
        params={
            "request_id": "request-b",
            "cursor": filtered_payload["next_cursor"],
        },
    )
    assert reused_for_other_filter.status_code == 422
    assert reused_for_other_filter.json()["detail"] == "AUDIT_CURSOR_INVALID"


def test_audit_page_rejects_tampered_cursor_and_non_owner(
    client: TestClient, db_session: Session
) -> None:
    household_id = _create_household(client)
    _seed_audits(db_session, household_id)
    url = f"/api/v1/households/{household_id}/authorization-audits/page"
    first = client.get(url, headers=OWNER_HEADERS, params={"limit": 1})
    cursor = first.json()["next_cursor"]
    encoded, signature = cursor.split(".", 1)
    replacement = "A" if signature[0] != "A" else "B"

    tampered = client.get(
        url,
        headers=OWNER_HEADERS,
        params={"cursor": f"{encoded}.{replacement}{signature[1:]}"},
    )
    assert tampered.status_code == 422
    assert tampered.json()["detail"] == "AUDIT_CURSOR_INVALID"

    non_owner = client.get(url, headers={"X-Actor-Id": "caregiver"})
    assert non_owner.status_code == 404


def test_audit_page_limits_are_bounded(client: TestClient) -> None:
    household_id = _create_household(client)
    response = client.get(
        f"/api/v1/households/{household_id}/authorization-audits/page",
        headers=OWNER_HEADERS,
        params={"limit": 101},
    )
    assert response.status_code == 422
