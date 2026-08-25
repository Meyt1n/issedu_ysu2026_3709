"""Formal demo health seed plan — synthetic, labelled teaching facts only.

All strings are fiction for classroom demos. They must never be treated as
real clinical records. Links between disease → medicine → allergy → plan are
intentional so relationship-graph and rule demos stay coherent.
"""
from __future__ import annotations

from typing import Any

# Shared labels used by prepare-family-demo.ps1 / continuous demo runbook.
FORMAL_HOUSEHOLD_NAME = "爷爷奶奶家（本地演示）"
FORMAL_OWNER_ACTOR_ID = "demo-parent"
FORMAL_GRANDPA_ACTOR_ID = "grandpa-demo"
FORMAL_GRANDMA_ACTOR_ID = "grandma-demo"
FORMAL_OWNER_PASSWORD_DEFAULT = "DemoOnly-ChangeMe!"
FORMAL_CHILD_ACTOR_ID = "demo-child"
FORMAL_CHILD_PASSWORD_DEFAULT = "DemoOnly-ChangeMe!"

# Idempotent keys — re-running the seeder skips duplicates via API.
SEED_PREFIX = "formal-demo-health"


def _event(
    *,
    member_key: str,
    event_type: str,
    payload: dict[str, Any],
    key: str,
    note: str,
) -> dict[str, Any]:
    return {
        "member_key": member_key,
        "event_type": event_type,
        "payload": payload,
        "idempotency_key": f"{SEED_PREFIX}-{key}",
        "teaching_note": note,
    }


FORMAL_DEMO_HEALTH_EVENTS: list[dict[str, Any]] = [
    # ── 奶奶：高血压 + 糖尿病病史，阿司匹林过敏，却误录含阿司匹林药品 ──
    _event(
        member_key="grandma",
        event_type="disease_added",
        payload={"disease": "高血压（演示）", "note": "教学病史，非诊断结论"},
        key="grandma-disease-htn",
        note="病史驱动后续降压药与计划",
    ),
    _event(
        member_key="grandma",
        event_type="disease_added",
        payload={"disease": "2型糖尿病（演示）", "note": "教学病史，非诊断结论"},
        key="grandma-disease-dm2",
        note="病史驱动后续二甲双胍计划",
    ),
    _event(
        member_key="grandma",
        event_type="allergy_added",
        payload={"allergy": "阿司匹林", "note": "登记过敏，供规则冲突演示"},
        key="grandma-allergy-asa",
        note="与下方阿司匹林肠溶片成分对齐，触发 allergy_conflict",
    ),
    _event(
        member_key="grandma",
        event_type="medication_added",
        payload={
            "drug": "阿司匹林肠溶片（演示）",
            "spec": "100mg×30片",
            "schedule": "按医嘱核对后服用（演示，不给剂量建议）",
            "expiry_date": "2026-01-15",
            "stock": 8,
            "ingredient": "阿司匹林",
            "note": "故意与过敏史对齐，仅用于冲突规则演示",
        },
        key="grandma-med-asa",
        note="过敏冲突 + 过期/临期规则素材",
    ),
    _event(
        member_key="grandma",
        event_type="medication_added",
        payload={
            "drug": "苯磺酸氨氯地平片（演示）",
            "spec": "5mg×28片",
            "schedule": "每日早餐后（演示计划）",
            "expiry_date": "2027-06-01",
            "stock": 3,
            "ingredient": "氨氯地平",
            "related_disease": "高血压（演示）",
            "note": "对应高血压病史的常用教学药名",
        },
        key="grandma-med-amlodipine",
        note="关联高血压病史；低库存提示素材",
    ),
    _event(
        member_key="grandma",
        event_type="medication_added",
        payload={
            "drug": "二甲双胍缓释片（演示）",
            "spec": "0.5g×30片",
            "schedule": "晚餐后（演示计划）",
            "expiry_date": "2027-09-01",
            "stock": 20,
            "ingredient": "二甲双胍",
            "related_disease": "2型糖尿病（演示）",
            "note": "对应糖尿病病史的常用教学药名",
        },
        key="grandma-med-metformin",
        note="关联糖尿病病史",
    ),
    _event(
        member_key="grandma",
        event_type="plan_created",
        payload={
            "drug": "苯磺酸氨氯地平片（演示）",
            "schedule": "每日早餐后核对服用（演示）",
            "due_time": "08:00",
            "level": "GENERAL",
            "related_disease": "高血压（演示）",
        },
        key="grandma-plan-amlodipine",
        note="计划药品名与已确认药品一致",
    ),
    _event(
        member_key="grandma",
        event_type="plan_created",
        payload={
            "drug": "二甲双胍缓释片（演示）",
            "schedule": "晚餐后核对服用（演示）",
            "due_time": "19:00",
            "level": "HIGH",
            "related_disease": "2型糖尿病（演示）",
        },
        key="grandma-plan-metformin",
        note="计划药品名与已确认药品一致",
    ),
    # ── 爷爷：高脂血症 + 冠心病病史，青霉素过敏，误录含青霉素药品 ──
    _event(
        member_key="grandpa",
        event_type="disease_added",
        payload={"disease": "高脂血症（演示）", "note": "教学病史，非诊断结论"},
        key="grandpa-disease-lipid",
        note="病史驱动他汀类教学药品",
    ),
    _event(
        member_key="grandpa",
        event_type="disease_added",
        payload={"disease": "冠心病（演示）", "note": "教学病史，非诊断结论"},
        key="grandpa-disease-chd",
        note="与高脂血症共同构成心血管教学背景",
    ),
    _event(
        member_key="grandpa",
        event_type="allergy_added",
        payload={"allergy": "青霉素", "note": "登记过敏，供规则冲突演示"},
        key="grandpa-allergy-penicillin",
        note="与下方青霉素V钾片成分对齐",
    ),
    _event(
        member_key="grandpa",
        event_type="medication_added",
        payload={
            "drug": "阿托伐他汀钙片（演示）",
            "spec": "20mg×28片",
            "schedule": "每晚睡前（演示计划）",
            "expiry_date": "2027-11-01",
            "stock": 16,
            "ingredient": "阿托伐他汀",
            "related_disease": "高脂血症（演示）",
            "note": "对应血脂病史",
        },
        key="grandpa-med-statin",
        note="关联高脂血症病史",
    ),
    _event(
        member_key="grandpa",
        event_type="medication_added",
        payload={
            "drug": "青霉素V钾片（演示）",
            "spec": "250mg×24片",
            "schedule": "待人工与医嘱核对（演示，不给用法）",
            "expiry_date": "2026-03-01",
            "stock": 10,
            "ingredient": "青霉素",
            "note": "故意与青霉素过敏对齐，仅用于冲突规则演示",
        },
        key="grandpa-med-penicillin",
        note="过敏冲突 + 过期/临期素材",
    ),
    _event(
        member_key="grandpa",
        event_type="medication_added",
        payload={
            "drug": "阿司匹林肠溶片（演示·爷爷）",
            "spec": "100mg×30片",
            "schedule": "按医嘱核对（演示）",
            "expiry_date": "2027-08-01",
            "stock": 25,
            "ingredient": "阿司匹林",
            "related_disease": "冠心病（演示）",
            "note": "心血管教学背景常用药名；爷爷无阿司匹林过敏，不触发其过敏冲突",
        },
        key="grandpa-med-asa",
        note="与奶奶的阿司匹林过敏形成对照教学",
    ),
    _event(
        member_key="grandpa",
        event_type="plan_created",
        payload={
            "drug": "阿托伐他汀钙片（演示）",
            "schedule": "每晚睡前核对服用（演示）",
            "due_time": "21:00",
            "level": "GENERAL",
            "related_disease": "高脂血症（演示）",
        },
        key="grandpa-plan-statin",
        note="计划药品名与已确认药品一致",
    ),
]



# Extra metric / observation events (not part of relationship-graph nodes).
FORMAL_DEMO_METRIC_EVENTS: list[dict[str, Any]] = [
    _event(
        member_key="grandma",
        event_type="metric_recorded",
        payload={
            "metric": "blood_pressure",
            "systolic": 128,
            "diastolic": 78,
            "unit": "mmHg",
            "measured_at": "2026-08-24T08:10:00+08:00",
            "context": "早餐前（演示数值，非诊断）",
            "related_disease": "高血压（演示）",
            "note": "教学观察值，不做高低解读",
        },
        key="grandma-metric-bp-1",
        note="关联高血压病史的观察记录",
    ),
    _event(
        member_key="grandma",
        event_type="metric_recorded",
        payload={
            "metric": "blood_pressure",
            "systolic": 132,
            "diastolic": 80,
            "unit": "mmHg",
            "measured_at": "2026-08-25T08:05:00+08:00",
            "context": "早餐前（演示数值，非诊断）",
            "related_disease": "高血压（演示）",
        },
        key="grandma-metric-bp-2",
        note="连续观察，供趋势展示",
    ),
    _event(
        member_key="grandma",
        event_type="metric_recorded",
        payload={
            "metric": "blood_glucose",
            "value": 6.2,
            "unit": "mmol/L",
            "meal_context": "空腹",
            "measured_at": "2026-08-25T07:50:00+08:00",
            "related_disease": "2型糖尿病（演示）",
            "note": "教学观察值，不做诊断阈值解读",
        },
        key="grandma-metric-glu-1",
        note="关联糖尿病病史的观察记录",
    ),
    _event(
        member_key="grandpa",
        event_type="metric_recorded",
        payload={
            "metric": "blood_pressure",
            "systolic": 118,
            "diastolic": 72,
            "unit": "mmHg",
            "measured_at": "2026-08-25T07:40:00+08:00",
            "context": "晨起（演示数值）",
            "related_disease": "冠心病（演示）",
        },
        key="grandpa-metric-bp-1",
        note="爷爷心血管背景的观察记录",
    ),
]

# Plan keys that drive reminder closed-loop samples after plans exist.
FORMAL_DEMO_REMINDER_SPECS: list[dict[str, Any]] = [
    {
        "member_key": "grandma",
        "plan_idempotency_key": f"{SEED_PREFIX}-grandma-plan-amlodipine",
        "actions": [
            {
                "event_type": "plan_confirmed",
                "idempotency_key": f"{SEED_PREFIX}-grandma-confirm-amlodipine",
                "payload_extra": {
                    "confirmed_at": "2026-08-25T08:05:00+08:00",
                    "note": "演示：已在安全时间窗内确认",
                },
            }
        ],
    },
    {
        "member_key": "grandma",
        "plan_idempotency_key": f"{SEED_PREFIX}-grandma-plan-metformin",
        "actions": [
            {
                "event_type": "plan_missed",
                "idempotency_key": f"{SEED_PREFIX}-grandma-miss-metformin",
                "payload_extra": {
                    "missed_at": "2026-08-25T20:30:00+08:00",
                    "reason": "演示：连续未确认后的漏服记录",
                    "note": "非真实依从性数据",
                },
            },
            {
                "event_type": "care_escalated",
                "idempotency_key": f"{SEED_PREFIX}-grandma-escalate-metformin",
                "payload_extra": {
                    "reason": "MISSED_DOSE_ESCALATION",
                    "note": "演示升级到照护者关注",
                },
            },
            {
                "event_type": "caregiver_notified",
                "idempotency_key": f"{SEED_PREFIX}-grandma-notify-child",
                "payload_extra": {
                    "recipient_actor_id": "demo-child",
                    "channel": "LOCAL_EVENT_INBOX",
                    "delivery_status": "QUEUED",
                    "note": "演示本地收件箱通知，非推送",
                },
            },
        ],
    },
]

CLASSROOM_SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "allergy-conflict",
        "title": "过敏冲突",
        "member_key": "grandma",
        "summary": "奶奶有阿司匹林过敏，却登记了含阿司匹林药品；打开风险页查看 SEVERE。",
        "focus": ["allergy_conflict", "relationship-graph"],
    },
    {
        "id": "expired-med",
        "title": "过期/临期药品",
        "member_key": "grandpa",
        "summary": "爷爷的青霉素V钾片已过期或临期；风险页展示 expiry_check，并对照过敏冲突。",
        "focus": ["expiry_check", "allergy_conflict"],
    },
    {
        "id": "missed-escalation",
        "title": "未确认升级",
        "member_key": "grandma",
        "summary": "二甲双胍计划漏服后产生 care_escalated 与 caregiver_notified；对照已确认的氨氯地平。",
        "focus": ["plan_missed", "care_escalated", "authorization"],
    },
]

def expected_graph_labels() -> dict[str, dict[str, set[str]]]:
    """Labels the relationship graph should contain after seeding."""
    return {
        "grandma": {
            "diseases": {"高血压（演示）", "2型糖尿病（演示）"},
            "allergies": {"阿司匹林"},
            "drugs": {
                "阿司匹林肠溶片（演示）",
                "苯磺酸氨氯地平片（演示）",
                "二甲双胍缓释片（演示）",
            },
        },
        "grandpa": {
            "diseases": {"高脂血症（演示）", "冠心病（演示）"},
            "allergies": {"青霉素"},
            "drugs": {
                "阿托伐他汀钙片（演示）",
                "青霉素V钾片（演示）",
                "阿司匹林肠溶片（演示·爷爷）",
            },
        },
    }
