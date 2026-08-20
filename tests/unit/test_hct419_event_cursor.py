"""HCT-419: signed, opaque health-event cursor helpers."""

from datetime import UTC, datetime

import pytest

from app.event_pagination import decode_event_cursor, encode_event_cursor


def test_cursor_round_trip_contains_only_sort_key() -> None:
    cursor = encode_event_cursor(
        household_id="household-1",
        member_id="member-1",
        created_at=datetime(2026, 8, 20, 12, 30, tzinfo=UTC),
        sequence_no=4,
        event_id="event-1",
        secret="test-secret",
    )

    decoded = decode_event_cursor(cursor, secret="test-secret")

    assert decoded.household_id == "household-1"
    assert decoded.member_id == "member-1"
    assert decoded.created_at == datetime(2026, 8, 20, 12, 30, tzinfo=UTC)
    assert decoded.sequence_no == 4
    assert decoded.event_id == "event-1"
    assert "payload" not in cursor
    assert "health detail" not in cursor


def test_cursor_rejects_tampering_and_wrong_secret() -> None:
    cursor = encode_event_cursor(
        household_id="household-1",
        member_id=None,
        created_at=datetime.now(UTC),
        sequence_no=1,
        event_id="event-1",
        secret="test-secret",
    )
    encoded, signature = cursor.split(".", 1)

    with pytest.raises(ValueError, match="EVENT_CURSOR_INVALID"):
        decode_event_cursor(f"{encoded}.{signature[:-1]}x", secret="test-secret")
    with pytest.raises(ValueError, match="EVENT_CURSOR_INVALID"):
        decode_event_cursor(cursor, secret="other-secret")


@pytest.mark.parametrize("cursor", ["", "not-a-cursor", "a.b.c", "%%%%.%%%%"])
def test_cursor_rejects_malformed_values(cursor: str) -> None:
    with pytest.raises(ValueError, match="EVENT_CURSOR_INVALID"):
        decode_event_cursor(cursor, secret="test-secret")
