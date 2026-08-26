"""HCT-303: Alert dedup and daily budget tests."""

from app.rules import Alert, apply_daily_budget, dedup_alerts, deduplication_key


def test_dedup_same_rule():
    alerts = [
        Alert("low_stock", "WARNING", "msg", ["e1"]),
        Alert("low_stock", "WARNING", "msg", ["e1"]),
    ]
    result = dedup_alerts(alerts)
    assert len(result) == 1
    assert result[0].merged_count == 2
    assert len(deduplication_key(result[0])) == 32


def test_dedup_different_rule():
    alerts = [
        Alert("low_stock", "WARNING", "msg", ["e1"]),
        Alert("expiry_check", "WARNING", "msg", ["e1"]),
    ]
    result = dedup_alerts(alerts)
    assert len(result) == 2


def test_budget_severe_exempt():
    severe = [Alert("allergy_conflict", "SEVERE", "msg", ["e1"])]
    rest = [Alert("low_stock", "WARNING", f"msg-{i}", ["e1"]) for i in range(20)]
    result = apply_daily_budget(severe + rest, budget=5)
    severe_count = sum(1 for a in result if a.level == "SEVERE")
    assert severe_count == 1  # severe always passes
    assert len(result) <= 1 + 5


def test_budget_caps_non_severe():
    alerts = [Alert("low_stock", "WARNING", f"msg-{i}", ["e1"]) for i in range(20)]
    result = apply_daily_budget(alerts, budget=5)
    assert len(result) == 5
    assert all(alert.budget_status == "VISIBLE" for alert in result)
    assert [alert.budget_reason for alert in result] == [
        "当前处于每日普通提醒预算内"
    ] * 5


def test_budget_metadata_preserves_deferred_alerts_when_requested():
    alerts = [Alert("low_stock", "WARNING", f"msg-{i}", [f"e-{i}"]) for i in range(3)]

    result = apply_daily_budget(alerts, budget=1, include_suppressed=True)

    assert len(result) == 3
    assert [alert.budget_status for alert in result] == [
        "VISIBLE",
        "DEFERRED",
        "DEFERRED",
    ]
    assert result[0].next_visible_at is None
    assert result[1].next_visible_at is not None
    assert result[1].next_visible_at.tzinfo is not None
    assert all("msg-" not in (alert.budget_reason or "") for alert in result)
