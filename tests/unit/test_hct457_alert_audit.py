"""HCT-457: dedup and daily budget must be explainable, not silent.

HCT-303 merged duplicates by dropping them and enforced the budget by truncating
the list, so a client could only show a shorter list with no way to say why.
These tests pin the audit metadata that makes both decisions reviewable.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.rules import (
    BUDGET_STATUS_SEVERE_EXEMPT,
    BUDGET_STATUS_SUPPRESSED,
    BUDGET_STATUS_VISIBLE,
    Alert,
    apply_daily_budget,
    dedup_alerts,
    deduplication_key,
    suppressed_by_budget,
)


def _alert(rule_id: str, level: str = "WARNING", events: list[str] | None = None) -> Alert:
    return Alert(rule_id=rule_id, level=level, message="m", source_event_ids=events or [])


class TestDedupAudit:
    def test_merges_same_rule_and_evidence_and_counts_them(self):
        alerts = [
            _alert("expiry_check", events=["e1", "e2"]),
            _alert("expiry_check", events=["e2", "e1"]),  # same set, different order
            _alert("expiry_check", events=["e3"]),
        ]

        merged = dedup_alerts(alerts)

        assert len(merged) == 2
        assert merged[0].merged_count == 2
        assert merged[1].merged_count == 1
        assert merged[0].deduplication_key == deduplication_key(alerts[0])
        # Evidence order must not change the group key.
        assert deduplication_key(alerts[0]) == deduplication_key(alerts[1])

    def test_does_not_mutate_the_input_alerts(self):
        original = _alert("low_stock", events=["e1"])
        dedup_alerts([original, _alert("low_stock", events=["e1"])])
        assert original.merged_count is None
        assert original.deduplication_key is None

    def test_preserves_first_seen_order(self):
        alerts = [_alert("b", events=["e2"]), _alert("a", events=["e1"])]
        assert [a.rule_id for a in dedup_alerts(alerts)] == ["b", "a"]


class TestBudgetAudit:
    def test_severe_is_exempt_and_says_so(self):
        alerts = [_alert("allergy_conflict", level="SEVERE", events=["e1"])]
        kept = apply_daily_budget(alerts, budget=0)
        assert len(kept) == 1
        assert kept[0].budget_status == BUDGET_STATUS_SEVERE_EXEMPT
        assert kept[0].budget_reason

    def test_visible_non_severe_carries_the_budget_reason(self):
        kept = apply_daily_budget([_alert("low_stock", events=["e1"])], budget=5)
        assert kept[0].budget_status == BUDGET_STATUS_VISIBLE
        assert "5" in (kept[0].budget_reason or "")

    def test_budget_truncates_but_the_held_back_ones_are_explainable(self):
        alerts = [_alert(f"rule_{index}", events=[f"e{index}"]) for index in range(4)]

        kept = apply_daily_budget(alerts, budget=2)
        held = suppressed_by_budget(alerts, budget=2, now=datetime(2026, 8, 26, 10, 0, tzinfo=UTC))

        assert len(kept) == 2
        assert len(held) == 2
        assert {a.rule_id for a in kept}.isdisjoint({a.rule_id for a in held})
        for alert in held:
            assert alert.budget_status == BUDGET_STATUS_SUPPRESSED
            assert alert.budget_reason
            # The budget resets at the next UTC midnight.
            assert alert.next_visible_at == datetime(2026, 8, 27, 0, 0, tzinfo=UTC)
            assert alert.deduplication_key

    def test_severe_is_never_reported_as_suppressed(self):
        alerts = [_alert("allergy_conflict", level="SEVERE", events=["e1"])]
        assert suppressed_by_budget(alerts, budget=0) == []

    def test_nothing_held_back_when_inside_budget(self):
        assert suppressed_by_budget([_alert("low_stock", events=["e1"])], budget=10) == []

    def test_visible_alerts_have_no_next_visible_time(self):
        kept = apply_daily_budget([_alert("low_stock", events=["e1"])], budget=10)
        assert kept[0].next_visible_at is None


class TestSuppressedCountConsistency:
    """`suppressed_count` must equal the alerts actually reported as held back."""

    def test_count_matches_the_reported_suppressed_alerts(self):
        alerts = [_alert(f"rule_{index}", events=[f"e{index}"]) for index in range(5)]

        kept = apply_daily_budget(alerts, budget=2)
        held = suppressed_by_budget(alerts, budget=2)

        assert len(kept) + len(held) == len(alerts)
        assert len(held) == 3

    def test_severe_alerts_never_shrink_the_visible_list(self):
        alerts = [
            _alert("allergy_conflict", level="SEVERE", events=["e1"]),
            _alert("interaction", level="SEVERE", events=["e2"]),
            _alert("low_stock", events=["e3"]),
        ]

        kept = apply_daily_budget(alerts, budget=0)
        held = suppressed_by_budget(alerts, budget=0)

        assert len(kept) == 2  # both SEVERE survive a zero budget
        assert [a.rule_id for a in held] == ["low_stock"]
