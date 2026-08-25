"""HCT-442: retrieval audits retain correlation metadata, never query text."""

from __future__ import annotations

import hashlib

from app.knowledge import RetrievalQuery, log_query, query_audit_fingerprint


def test_query_audit_fingerprint_normalizes_without_retaining_text(db_session) -> None:
    first = log_query(
        db_session,
        query_text="  阿莫西林  的  已确认记录？ ",
        actor_id="audit-owner",
        household_id="household-a",
        member_id="member-a",
        top_chunk_ids=["chunk-a", "chunk-b"],
        returned_count=2,
    )
    second = log_query(
        db_session,
        query_text="阿莫西林 的 已确认记录？",
        actor_id="audit-owner",
        returned_count=0,
    )
    db_session.commit()

    expected_digest, expected_length = query_audit_fingerprint("阿莫西林 的 已确认记录？")
    assert first.query_text is None
    assert first.query_digest == expected_digest
    assert first.query_length == expected_length
    assert second.query_digest == expected_digest
    assert db_session.query(RetrievalQuery).count() == 2
    assert all(row.query_text is None for row in db_session.query(RetrievalQuery).all())


def test_query_audit_endpoint_is_actor_scoped_and_minimal(client, db_session) -> None:
    own = log_query(
        db_session,
        query_text="成员最近的风险提醒",
        actor_id="audit-owner",
        top_chunk_ids=["secret-chunk"],
        returned_count=1,
    )
    log_query(
        db_session,
        query_text="其他家庭的查询",
        actor_id="other-actor",
        returned_count=1,
    )
    db_session.commit()

    response = client.get(
        "/api/v1/knowledge/query-audit",
        headers={"X-Actor-ID": "audit-owner"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == own.id
    assert len(body[0]["query_digest"]) == 64
    assert body[0]["query_length"] > 0
    assert body[0]["top_chunk_count"] == 1
    assert "query_text" not in body[0]
    assert "secret-chunk" not in response.text

    # The digest is not a reversible encoding of the query.
    assert hashlib.sha256("成员最近的风险提醒".encode()).hexdigest() == body[0]["query_digest"]
