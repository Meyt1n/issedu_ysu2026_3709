"""Opaque, signed cursors for authorization-scoped health event pages."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_CURSOR_VERSION = 1
_CURSOR_RESOURCE = "health-events"


@dataclass(frozen=True)
class EventCursor:
    household_id: str
    member_id: str | None
    created_at: datetime
    sequence_no: int
    event_id: str


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(encoded: str, secret: str) -> str:
    signature = hmac.new(
        secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
    ).digest()
    return _encode(signature)


def encode_event_cursor(
    *,
    household_id: str,
    member_id: str | None,
    created_at: datetime,
    sequence_no: int,
    event_id: str,
    secret: str,
) -> str:
    """Encode only the stable sort key and query scope; never include event payload."""
    timestamp = created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=UTC)
    payload = {
        "v": _CURSOR_VERSION,
        "resource": _CURSOR_RESOURCE,
        "household_id": household_id,
        "member_id": member_id,
        "created_at": timestamp.astimezone(UTC).isoformat(),
        "sequence_no": sequence_no,
        "event_id": event_id,
    }
    encoded = _encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    )
    return f"{encoded}.{_sign(encoded, secret)}"


def decode_event_cursor(cursor: str, *, secret: str) -> EventCursor:
    """Validate a cursor signature and shape, returning a normalized sort key."""
    try:
        encoded, supplied_signature = cursor.split(".", 1)
        if not encoded or not hmac.compare_digest(supplied_signature, _sign(encoded, secret)):
            raise ValueError
        payload: Any = json.loads(_decode(encoded).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError
        if payload.get("v") != _CURSOR_VERSION or payload.get("resource") != _CURSOR_RESOURCE:
            raise ValueError
        household_id = payload.get("household_id")
        member_id = payload.get("member_id")
        event_id = payload.get("event_id")
        created_at = payload.get("created_at")
        sequence_no = payload.get("sequence_no")
        if (
            not isinstance(household_id, str)
            or not household_id
            or (member_id is not None and not isinstance(member_id, str))
            or not isinstance(event_id, str)
            or not event_id
            or not isinstance(created_at, str)
            or isinstance(sequence_no, bool)
            or not isinstance(sequence_no, int)
            or sequence_no < 1
        ):
            raise ValueError
        timestamp = datetime.fromisoformat(created_at)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        return EventCursor(
            household_id=household_id,
            member_id=member_id,
            created_at=timestamp.astimezone(UTC),
            sequence_no=sequence_no,
            event_id=event_id,
        )
    except (
        ValueError,
        TypeError,
        KeyError,
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        raise ValueError("EVENT_CURSOR_INVALID") from None
