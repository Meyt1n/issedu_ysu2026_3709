"""HCT-303: Alert dedup and daily budget tests."""

from app.rules import Alert, apply_daily_budget, dedup_alerts


def test_dedup_same_rule():
    alerts = [
        Alert("low_stock", "WARNING", "msg", ["e1"]),
        Alert("low_stock", "WARNING", "msg", ["e1"]),
    ]
    result = dedup_alerts(alerts)
    assert len(result) == 1


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
