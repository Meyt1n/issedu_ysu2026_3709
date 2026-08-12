from __future__ import annotations

import base64
import hashlib
import hmac

import pytest
from ai.vision import quality_receipt
from ai.vision.quality_receipt import issue_quality_receipt, verify_quality_receipt


def _signed_raw_payload(raw: bytes) -> str:
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    signature = base64.urlsafe_b64encode(
        hmac.new(quality_receipt._RECEIPT_SECRET, encoded.encode(), hashlib.sha256).digest()
    ).rstrip(b"=").decode("ascii")
    return f"{encoded}.{signature}"


def test_receipt_is_bound_to_actor_digest_and_config() -> None:
    receipt = issue_quality_receipt(
        actor_id="owner-a",
        input_digest="a" * 64,
        config_version="quality-v1",
        now=100,
    )

    payload = verify_quality_receipt(
        receipt,
        actor_id="owner-a",
        input_digest="a" * 64,
        config_version="quality-v1",
        now=101,
    )
    assert payload["decision"] == "PASS"

    with pytest.raises(ValueError, match="QUALITY_RECEIPT_MISMATCH"):
        verify_quality_receipt(
            receipt,
            actor_id="owner-b",
            input_digest="a" * 64,
            config_version="quality-v1",
            now=101,
        )


def test_receipt_expires_at_exact_boundary_and_tampering_is_rejected() -> None:
    receipt = issue_quality_receipt(
        actor_id="owner-a",
        input_digest="a" * 64,
        config_version="quality-v1",
        now=100,
        ttl_seconds=10,
    )

    with pytest.raises(ValueError, match="QUALITY_RECEIPT_EXPIRED"):
        verify_quality_receipt(
            receipt,
            actor_id="owner-a",
            input_digest="a" * 64,
            config_version="quality-v1",
            now=110,
        )
    with pytest.raises(ValueError, match="QUALITY_RECEIPT_INVALID"):
        tampered_receipt = receipt[:-1] + ("B" if receipt[-1] == "A" else "A")
        verify_quality_receipt(
            tampered_receipt,
            actor_id="owner-a",
            input_digest="a" * 64,
            config_version="quality-v1",
            now=101,
        )


@pytest.mark.parametrize(
    "raw_payload",
    [
        b"\xff\xfe",
        b"[]",
        b'"text"',
        b'{"actor_id":"owner-a"}',
        b'{"version":true,"actor_id":"owner-a","input_digest":"x",'
        b'"config_version":"v","decision":"PASS","issued_at":1,"expires_at":2}',
    ],
)
def test_signed_malformed_payloads_are_rejected(raw_payload: bytes) -> None:
    receipt = _signed_raw_payload(raw_payload)

    with pytest.raises(ValueError, match="QUALITY_RECEIPT_INVALID"):
        verify_quality_receipt(
            receipt,
            actor_id="owner-a",
            input_digest="a" * 64,
            config_version="quality-v1",
            now=101,
        )
