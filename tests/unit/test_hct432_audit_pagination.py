"""HCT-432: authorization audit cursors are signed and scope-bound."""

from datetime import UTC, datetime

import pytest

from app.audit_pagination import decode_audit_cursor, encode_audit_cursor


def test_audit_cursor_round_trip_preserves_scope_and_sort_key() -> None:
    created_at = datetime(2026, 8, 22, 9, 0, tzinfo=UTC)
    cursor = encode_audit_cursor(
        household_id="household-432",
        request_id="request-432",
        action="READ_EVENTS",
        outcome="ALLOWED",
        created_at=created_at,
        audit_id="audit-432",
        secret="test-secret",
    )

    decoded = decode_audit_cursor(cursor, secret="test-secret")

    assert decoded.household_id == "household-432"
    assert decoded.request_id == "request-432"
    assert decoded.action == "READ_EVENTS"
    assert decoded.outcome == "ALLOWED"
    assert decoded.created_at == created_at
    assert decoded.audit_id == "audit-432"


def test_audit_cursor_rejects_tampering_or_wrong_secret() -> None:
    cursor = encode_audit_cursor(
        household_id="household-432",
        request_id=None,
        action=None,
        outcome=None,
        created_at=datetime.now(UTC),
        audit_id="audit-432",
        secret="test-secret",
    )
    encoded, signature = cursor.split(".", 1)
    replacement = "A" if signature[-1] != "A" else "B"
    tampered = f"{encoded}.{signature[:-1]}{replacement}"

    with pytest.raises(ValueError, match="AUDIT_CURSOR_INVALID"):
        decode_audit_cursor(tampered, secret="test-secret")
    with pytest.raises(ValueError, match="AUDIT_CURSOR_INVALID"):
        decode_audit_cursor(cursor, secret="different-secret")
