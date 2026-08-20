"""投影药品风险字段回归测试。

移动端联机联调（2026-08-13）发现：`medication_added` 事件的
`expiry_date` / `stock` / `ingredient` 字段在 `build_relationship_graph`
投影时被丢弃，导致 `expiry_check` / `low_stock` / `duplicate_ingredient`
三条规则（HCT-302，FR-05）对真实事件永远不会触发。

本文件从“事件 -> 投影 -> 规则”整条链路做回归，防止再次退化。
"""

from datetime import UTC, datetime, timedelta

from app.models import HealthEvent
from app.projection import build_relationship_graph
from app.rules import run_rules


def _medication_event(event_id: str, payload: dict) -> HealthEvent:
    return HealthEvent(id=event_id, event_type="medication_added", payload=payload)


def test_projection_keeps_drug_risk_fields():
    expired = (datetime.now(UTC) - timedelta(days=5)).date().isoformat()
    events = [
        _medication_event(
            "e1",
            {
                "drug": "阿司匹林肠溶片（测试）",
                "expiry_date": expired,
                "stock": 3,
                "ingredient": "阿司匹林",
            },
        ),
    ]

    facts = build_relationship_graph(events)

    assert len(facts["drugs"]) == 1
    drug = facts["drugs"][0]
    assert drug["name"] == "阿司匹林肠溶片（测试）"
    assert drug["added_by"] == "e1"
    assert drug["expiry_date"] == expired
    assert drug["stock"] == 3
    assert drug["ingredient"] == "阿司匹林"


def test_projection_tolerates_missing_optional_fields():
    events = [_medication_event("e1", {"drug": "仅有名称"})]

    facts = build_relationship_graph(events)

    drug = facts["drugs"][0]
    assert drug["name"] == "仅有名称"
    assert drug["expiry_date"] is None
    assert drug["stock"] is None
    assert drug["ingredient"] is None
    assert drug["active_ingredients"] == []
    assert drug["interaction_warnings"] == []


def test_projection_keeps_confirmed_master_metadata():
    events = [
        _medication_event(
            "e1",
            {
                "drug_name": "演示药",
                "candidate_id": "rec-demo",
                "active_ingredients": ["成分甲"],
                "indications": ["演示用途"],
                "cautions": ["演示注意"],
                "contraindications": ["演示禁忌"],
                "interaction_warnings": [
                    {"with_record_id": "rec-other", "level": "WARNING", "message": "核对"}
                ],
            },
        )
    ]
    facts = build_relationship_graph(
        [
            HealthEvent(
                id="e1",
                event_type="medication_confirmed",
                payload=events[0].payload,
            )
        ]
    )
    drug = facts["drugs"][0]
    assert drug["candidate_id"] == "rec-demo"
    assert drug["active_ingredients"] == ["成分甲"]
    assert drug["contraindications"] == ["演示禁忌"]
    assert drug["interaction_warnings"][0]["with_record_id"] == "rec-other"


def test_expiry_stock_duplicate_rules_fire_from_projected_events():
    expired = (datetime.now(UTC) - timedelta(days=10)).date().isoformat()
    fine = (datetime.now(UTC) + timedelta(days=365)).date().isoformat()
    events = [
        _medication_event(
            "e1",
            {
                "drug": "过期药（测试）",
                "expiry_date": expired,
                "stock": 2,
                "ingredient": "对乙酰氨基酚",
            },
        ),
        _medication_event(
            "e2",
            {
                "drug": "同成分药（测试）",
                "expiry_date": fine,
                "stock": 30,
                "ingredient": "对乙酰氨基酚",
            },
        ),
    ]

    facts = build_relationship_graph(events)
    alerts = run_rules(facts)
    rule_ids = {alert.rule_id for alert in alerts}

    assert "expiry_check" in rule_ids, "过期规则必须能从已确认事件触发"
    assert "low_stock" in rule_ids, "低库存规则必须能从已确认事件触发"
    assert "duplicate_ingredient" in rule_ids, "重复成分规则必须能从已确认事件触发"

    expiry_alert = next(a for a in alerts if a.rule_id == "expiry_check")
    assert expiry_alert.level == "SEVERE"
    assert expiry_alert.source_event_ids == ["e1"]
