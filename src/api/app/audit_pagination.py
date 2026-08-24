"""Opaque, signed cursors for authorization audit pages."""

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
_CURSOR_RESOURCE = "authorization-audits"


@dataclass(frozen=True)
class AuditCursor:
    household_id: str
    request_id: str | None
    action: str | None
    outcome: str | None
    created_at: datetime
    audit_id: str


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


def encode_audit_cursor(
    *,
    household_id: str,
    request_id: str | None,
    created_at: datetime,
    audit_id: str,
    secret: str,
    action: str | None = None,
    outcome: str | None = None,
) -> str:
    """Encode only the stable sort key and query scope, never audit contents."""
    timestamp = created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=UTC)
    payload = {
        "v": _CURSOR_VERSION,
        "resource": _CURSOR_RESOURCE,
        "household_id": household_id,
        "request_id": request_id,
        "action": action,
        "outcome": outcome,
        "created_at": timestamp.astimezone(UTC).isoformat(),
        "audit_id": audit_id,
    }
    encoded = _encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    )
    return f"{encoded}.{_sign(encoded, secret)}"


def decode_audit_cursor(cursor: str, *, secret: str) -> AuditCursor:
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
        request_id = payload.get("request_id")
        action = payload.get("action")
        outcome = payload.get("outcome")
        created_at = payload.get("created_at")
        audit_id = payload.get("audit_id")
        if (
            not isinstance(household_id, str)
            or not household_id
            or (request_id is not None and not isinstance(request_id, str))
            or (action is not None and not isinstance(action, str))
            or (outcome is not None and not isinstance(outcome, str))
            or not isinstance(created_at, str)
            or not isinstance(audit_id, str)
            or not audit_id
        ):
            raise ValueError
        timestamp = datetime.fromisoformat(created_at)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        return AuditCursor(
            household_id=household_id,
            request_id=request_id,
            action=action,
            outcome=outcome,
            created_at=timestamp.astimezone(UTC),
            audit_id=audit_id,
        )
    except (
        ValueError,
        TypeError,
        KeyError,
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        raise ValueError("AUDIT_CURSOR_INVALID") from None
