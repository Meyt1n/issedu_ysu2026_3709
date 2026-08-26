from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.retrieval_cache import (
    cache_put,
    clear_all,
    digest_query,
    make_entry_key,
    make_session_key,
)


def _entry(
    *,
    session_id: str,
    actor_id: str,
    household_id: str,
    member_id: str,
    agent: str,
    query: str,
) -> str:
    session_key = make_session_key(
        assistant_session_id=session_id,
        actor_id=actor_id,
        household_id=household_id,
        member_id=member_id,
    )
    return make_entry_key(
        session_key,
        agent=agent,
        query_digest=digest_query(query),
    )


def test_session_cache_ops_is_actor_scoped_and_redacted(client: TestClient) -> None:
    clear_all()
    cache_put(
        _entry(
            session_id="ops-session",
            actor_id="cache-owner",
            household_id="household-a",
            member_id="member-a",
            agent="database",
            query="health record",
        ),
        {"health_event": "must-not-leak"},
        ttl_seconds=120,
    )
    cache_put(
        _entry(
            session_id="ops-session",
            actor_id="cache-owner",
            household_id="household-a",
            member_id="member-a",
            agent="knowledge",
            query="care guidance",
        ),
        {"document_text": "must-not-leak"},
        ttl_seconds=120,
    )
    cache_put(
        _entry(
            session_id="ops-session",
            actor_id="cache-owner",
            household_id="household-a",
            member_id="member-a",
            agent="rules",
            query="expired",
        ),
        {"rule": "must-not-leak"},
        ttl_seconds=0.001,
    )
    cache_put(
        _entry(
            session_id="ops-session",
            actor_id="other-actor",
            household_id="household-a",
            member_id="member-a",
            agent="database",
            query="other actor",
        ),
        {"private": True},
        ttl_seconds=120,
    )
    time.sleep(0.01)

    response = client.get(
        "/api/v1/assistant/session-cache/ops",
        headers={"X-Actor-Id": "cache-owner"},
        params={"assistant_session_id": "ops-session"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["assistant_session_id"] == "ops-session"
    assert body["entries"] == 2
    assert body["alive_entries"] == 2
    assert body["scope_count"] == 1
    assert body["agent_entries"] == {"database": 1, "knowledge": 1}
    assert body["expired_entries_removed"] == 1
    assert body["min_remaining_ttl_seconds"] is not None
    assert body["max_remaining_ttl_seconds"] is not None
    serialized = str(body)
    assert "must-not-leak" not in serialized
    assert "household-a" not in serialized
    assert "member-a" not in serialized
    assert "cache-owner" not in serialized

    other_response = client.get(
        "/api/v1/assistant/session-cache/ops",
        headers={"X-Actor-Id": "other-actor"},
        params={"assistant_session_id": "ops-session"},
    )
    assert other_response.status_code == 200
    assert other_response.json()["entries"] == 1
    clear_all()


def test_session_cache_ops_requires_opaque_session_id(client: TestClient) -> None:
    response = client.get(
        "/api/v1/assistant/session-cache/ops",
        headers={"X-Actor-Id": "cache-owner"},
    )

    assert response.status_code == 422
    clear_all()
