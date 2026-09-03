"""Health-event payload validation tests."""

import pytest
from pydantic import ValidationError

from app.schemas import HealthEventCreate


def test_medication_stock_must_be_a_non_negative_integer() -> None:
    for invalid_stock in (-1, 1.5, True, False):
        with pytest.raises(ValidationError, match="MEDICATION_STOCK_INVALID"):
            HealthEventCreate(
                member_id="member-1",
                event_type="medication_added",
                payload={"drug": "阿莫西林", "stock": invalid_stock},
            )

    event = HealthEventCreate(
        member_id="member-1",
        event_type="medication_added",
        payload={"drug": "阿莫西林", "stock": 0},
    )
    assert event.payload["stock"] == 0


def test_non_medication_payloads_are_not_blocked_by_inventory_rule() -> None:
    event = HealthEventCreate(
        member_id="member-1",
        event_type="note_added",
        payload={"text": "库存数字仅是备注", "stock": -1},
    )
    assert event.payload["stock"] == -1
