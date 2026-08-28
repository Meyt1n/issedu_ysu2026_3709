"""HCT-462 risk handling actions and desensitized receipts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from app.models import RiskDisposition
from app.schemas import RiskDispositionRead

MAX_SNOOZE_SECONDS = 7 * 24 * 60 * 60


def as_utc(value: datetime) -> datetime:
    """Normalize SQLite-naive and offset-aware values to an UTC instant."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def disposition_request_fingerprint(
    *,
    household_id: str,
    member_id: str,
    rule_id: str,
    rule_version: str,
    risk_fingerprint_value: str,
    action: str,
    note: str | None,
    target_actor_id: str | None,
    snooze_until: datetime | None,
    actor_id: str,
) -> str:
    canonical = json.dumps(
        {
            "action": action,
            "actor_id": actor_id,
            "household_id": household_id,
            "member_id": member_id,
            "note": note,
            "risk_fingerprint": risk_fingerprint_value,
            "rule_id": rule_id,
            "rule_version": rule_version,
            "snooze_until": as_utc(snooze_until).isoformat() if snooze_until else None,
            "target_actor_id": target_actor_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def disposition_read(
    disposition: RiskDisposition,
    *,
    replayed: bool = False,
) -> RiskDispositionRead:
    return RiskDispositionRead(
        disposition_id=disposition.id,
        household_id=disposition.household_id,
        member_id=disposition.member_id,
        rule_id=disposition.rule_id,
        rule_version=disposition.rule_version,
        risk_fingerprint=disposition.risk_fingerprint,
        action=disposition.action,
        note=disposition.note,
        target_actor_id=disposition.target_actor_id,
        snooze_until=disposition.snooze_until,
        actor_id=disposition.actor_id,
        created_at=disposition.created_at,
        replayed=replayed,
    )
