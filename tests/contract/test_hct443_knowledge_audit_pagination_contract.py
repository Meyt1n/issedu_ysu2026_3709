"""HCT-443: actor-scoped, privacy-safe knowledge audit pagination."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.knowledge import log_query

OWNER_HEADERS = {"X-Actor-Id": "owner-443"}


def _seed_audits(db_session: Session) -> tuple[str, str]:
    first = log_query(
        db_session,
        query_text="第一个家庭的用药记录",
        actor_id="owner-443",
        household_id="household-a",
        member_id="member-a",
        top_chunk_ids=["secret-a"],
        returned_count=1,
    )
    second = log_query(
        db_session,
        query_text="第二个家庭的风险提醒",
        actor_id="owner-443",
        household_id="household-b",
        member_id="member-b",
        returned_count=2,
    )
    third = log_query(
        db_session,
        query_text="其他操作者的查询",
        actor_id="other-443",
        household_id="household-a",
        member_id="member-a",
        returned_count=3,
    )
    base = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)
    first.created_at = base
    second.created_at = base + timedelta(seconds=1)
    third.created_at = base + timedelta(seconds=2)
    db_session.commit()
    return first.id, second.id


def test_owner_can_page_filtered_audits_without_leaking_text_or_other_actor(
    client: TestClient, db_session: Session
) -> None:
    first_id, second_id = _seed_audits(db_session)
    url = "/api/v1/knowledge/query-audit/page"

    first = client.get(url, headers=OWNER_HEADERS, params={"limit": 1})
    assert first.status_code == 200, first.text
    first_payload = first.json()
    assert len(first_payload["items"]) == 1
    assert first_payload["items"][0]["id"] == second_id
    assert first_payload["has_more"] is True
    assert "query_text" not in first.text
    assert "secret-a" not in first.text

    second = client.get(
        url,
        headers=OWNER_HEADERS,
        params={"limit": 1, "cursor": first_payload["next_cursor"]},
    )
    assert second.status_code == 200, second.text
    second_payload = second.json()
    assert [item["id"] for item in second_payload["items"]] == [first_id]
    assert second_payload["has_more"] is False

    filtered = client.get(
        url,
        headers=OWNER_HEADERS,
        params={"household_id": "household-a", "member_id": "member-a", "limit": 10},
    )
    assert filtered.status_code == 200, filtered.text
    assert [item["id"] for item in filtered.json()["items"]] == [first_id]


def test_knowledge_page_rejects_cursor_reuse_tampering_and_bad_limit(
    client: TestClient, db_session: Session
) -> None:
    _seed_audits(db_session)
    url = "/api/v1/knowledge/query-audit/page"
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
    assert tampered.json()["detail"] == "KNOWLEDGE_AUDIT_CURSOR_INVALID"

    reused = client.get(
        url,
        headers={"X-Actor-Id": "other-443"},
        params={"cursor": cursor},
    )
    assert reused.status_code == 422
    assert reused.json()["detail"] == "KNOWLEDGE_AUDIT_CURSOR_INVALID"

    changed_filter = client.get(
        url,
        headers=OWNER_HEADERS,
        params={"household_id": "household-a", "cursor": cursor},
    )
    assert changed_filter.status_code == 422
    assert changed_filter.json()["detail"] == "KNOWLEDGE_AUDIT_CURSOR_INVALID"

    bounded = client.get(url, headers=OWNER_HEADERS, params={"limit": 101})
    assert bounded.status_code == 422
