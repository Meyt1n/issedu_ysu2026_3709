"""HCT-443: signed knowledge audit cursors are scope-bound."""

from datetime import UTC, datetime

import pytest

from app.knowledge_audit_pagination import (
    decode_knowledge_audit_cursor,
    encode_knowledge_audit_cursor,
)


def test_knowledge_cursor_round_trip_preserves_scope_and_sort_key() -> None:
    created_at = datetime(2026, 8, 25, 10, 30, tzinfo=UTC)
    cursor = encode_knowledge_audit_cursor(
        actor_id="owner",
        household_id="household-443",
        member_id="member-443",
        created_at=created_at,
        audit_id="audit-443",
        secret="test-secret",
    )

    decoded = decode_knowledge_audit_cursor(cursor, secret="test-secret")

    assert decoded.actor_id == "owner"
    assert decoded.household_id == "household-443"
    assert decoded.member_id == "member-443"
    assert decoded.created_at == created_at
    assert decoded.audit_id == "audit-443"


def test_knowledge_cursor_rejects_tampering_or_wrong_secret() -> None:
    cursor = encode_knowledge_audit_cursor(
        actor_id="owner",
        household_id=None,
        member_id=None,
        created_at=datetime.now(UTC),
        audit_id="audit-443",
        secret="test-secret",
    )
    encoded, signature = cursor.split(".", 1)
    replacement = "A" if signature[-1] != "A" else "B"
    tampered = f"{encoded}.{signature[:-1]}{replacement}"

    with pytest.raises(ValueError, match="KNOWLEDGE_AUDIT_CURSOR_INVALID"):
        decode_knowledge_audit_cursor(tampered, secret="test-secret")
    with pytest.raises(ValueError, match="KNOWLEDGE_AUDIT_CURSOR_INVALID"):
        decode_knowledge_audit_cursor(cursor, secret="different-secret")
