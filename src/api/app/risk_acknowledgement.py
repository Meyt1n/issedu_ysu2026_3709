"""HCT-413 risk acknowledgement fingerprints and receipt helpers."""

from __future__ import annotations

import hashlib
import json

from app.models import RiskAcknowledgement
from app.schemas import RiskAcknowledgementRead


def risk_fingerprint(
    *,
    rule_id: str,
    level: str,
    source_event_ids: list[str],
    rule_version: str,
) -> str:
    """Bind an acknowledgement to the exact server-side rule result."""

    canonical = json.dumps(
        {
            "level": level,
            "rule_id": rule_id,
            "rule_version": rule_version,
            "source_event_ids": sorted(source_event_ids),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def request_fingerprint(
    *,
    household_id: str,
    member_id: str,
    rule_id: str,
    rule_version: str,
    risk_fingerprint_value: str,
    actor_id: str,
) -> str:
    canonical = json.dumps(
        {
            "actor_id": actor_id,
            "household_id": household_id,
            "member_id": member_id,
            "risk_fingerprint": risk_fingerprint_value,
            "rule_id": rule_id,
            "rule_version": rule_version,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def acknowledgement_read(
    acknowledgement: RiskAcknowledgement,
    *,
    replayed: bool = False,
) -> RiskAcknowledgementRead:
    return RiskAcknowledgementRead(
        receipt_id=acknowledgement.id,
        household_id=acknowledgement.household_id,
        member_id=acknowledgement.member_id,
        rule_id=acknowledgement.rule_id,
        rule_version=acknowledgement.rule_version,
        risk_fingerprint=acknowledgement.risk_fingerprint,
        actor_id=acknowledgement.actor_id,
        acknowledged_at=acknowledgement.acknowledged_at,
        replayed=replayed,
    )
