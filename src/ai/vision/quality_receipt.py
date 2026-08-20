"""Short-lived, process-local receipts proving that an input passed HCT-202."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

RECEIPT_VERSION = "vision-quality-receipt-v2"
LEGACY_RECEIPT_VERSION = "vision-quality-receipt-v1"
DEFAULT_TTL_SECONDS = 600
_RECEIPT_SECRET = secrets.token_bytes(32)
_MEDIA_TYPES = frozenset({"image", "video"})


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)


def issue_quality_receipt(
    *,
    actor_id: str,
    input_digest: str,
    config_version: str,
    media_type: str = "image",
    now: int | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> str:
    if media_type not in _MEDIA_TYPES:
        raise ValueError("MEDIA_TYPE_INVALID")
    issued_at = int(time.time()) if now is None else now
    payload = {
        "version": RECEIPT_VERSION,
        "actor_id": actor_id,
        "input_digest": input_digest,
        "config_version": config_version,
        "media_type": media_type,
        "decision": "PASS",
        "issued_at": issued_at,
        "expires_at": issued_at + ttl_seconds,
    }
    encoded = _encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = _encode(hmac.new(_RECEIPT_SECRET, encoded.encode(), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def verify_quality_receipt(
    receipt: str,
    *,
    actor_id: str,
    input_digest: str,
    config_version: str,
    media_type: str = "image",
    now: int | None = None,
) -> dict[str, Any]:
    if media_type not in _MEDIA_TYPES:
        raise ValueError("MEDIA_TYPE_INVALID")
    try:
        encoded, supplied_signature = receipt.split(".", 1)
        expected_signature = _encode(
            hmac.new(_RECEIPT_SECRET, encoded.encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise ValueError("QUALITY_RECEIPT_INVALID")
        payload = json.loads(_decode(encoded).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("QUALITY_RECEIPT_INVALID")
        required_types = {
            "version": str,
            "actor_id": str,
            "input_digest": str,
            "config_version": str,
            "decision": str,
            "issued_at": int,
            "expires_at": int,
        }
        if any(
            key not in payload
            or isinstance(payload[key], bool)
            or not isinstance(payload[key], expected_type)
            for key, expected_type in required_types.items()
        ):
            raise ValueError("QUALITY_RECEIPT_INVALID")
        receipt_version = payload["version"]
        if receipt_version not in {LEGACY_RECEIPT_VERSION, RECEIPT_VERSION}:
            raise ValueError("QUALITY_RECEIPT_INVALID")
        if receipt_version == RECEIPT_VERSION:
            if not isinstance(payload.get("media_type"), str):
                raise ValueError("QUALITY_RECEIPT_INVALID")
            if payload["media_type"] not in _MEDIA_TYPES:
                raise ValueError("QUALITY_RECEIPT_INVALID")
        elif "media_type" in payload and payload["media_type"] != "image":
            raise ValueError("QUALITY_RECEIPT_INVALID")
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("QUALITY_RECEIPT_INVALID") from exc

    current_time = int(time.time()) if now is None else now
    if payload["expires_at"] <= current_time:
        raise ValueError("QUALITY_RECEIPT_EXPIRED")
    expected = {
        "actor_id": actor_id,
        "input_digest": input_digest,
        "config_version": config_version,
        "decision": "PASS",
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ValueError("QUALITY_RECEIPT_MISMATCH")
    receipt_media_type = payload.get("media_type", "image")
    if receipt_media_type != media_type:
        raise ValueError("QUALITY_RECEIPT_MISMATCH")
    return payload
