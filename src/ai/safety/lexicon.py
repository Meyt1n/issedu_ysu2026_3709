"""Shared safety / routing lexicon for the local health assistant.

Classification keywords, follow-up sanitizers, and medical-boundary
refusals used to live as three independent lists in ``tool_call.py``.
A missed synonym in one list (but not another) created uneven routing —
for example a colloquial「吃错药了」could fall through to ``GENERAL``
while the same intent expressed as「误服」was blocked.  Keep one source
of truth here; ``tool_call`` imports the shared tuples.
"""

from __future__ import annotations

# Emergency descriptions: route to URGENT and escalate.
URGENT_ROUTE_TERMS: tuple[str, ...] = (
    "呼吸困难",
    "意识异常",
    "疑似中毒",
    "昏迷",
    "抽搐",
    "严重过敏",
)

# High-risk medication questions must retrieve member facts + reviewed knowledge.
MEDICATION_SAFETY_ROUTE_TERMS: tuple[str, ...] = (
    "能不能一起吃",
    "能否一起吃",
    "可以一起吃",
    "能不能同服",
    "能否同服",
    "相互作用",
    "药物相互作用",
    "配伍",
    "停药",
    "换药",
    "调整剂量",
    "一次吃多少",
    "一天吃几",
    "怎么服用",
    "吃多少",
    "同服",
    "剂量",
    "怎么吃",
    "漏服",
    "补服",
    "过量",
    "误服",
    # Colloquial near-synonyms that previously leaked to GENERAL.
    "吃错药",
    "药吃多了",
    "吃多了药",
    "多吃了",
    "少吃了",
    "忘吃药",
    "忘记吃药",
    "拿错药",
    "多吞了",
    "吞多了",
    "吃了两倍",
    "别再吃",
    "可以停用",
    "先停药",
    "能不能停",
    "可以停药",
    "改吃什么",
    "换成别的药",
)

# Follow-up prompts must not invite dosage / stop / switch decisions.
FOLLOW_UP_RISK_TERMS: tuple[str, ...] = MEDICATION_SAFETY_ROUTE_TERMS + (
    "几粒",
    "几片",
    "应该吃",
    "补双倍",
    "一起吃",
    "诊断",
    "处方",
)

# Output must never contain diagnosis / prescription / commerce directives.
# Boundary checks run after structured schema validation as a second line.
# Prefer directive phrases over bare nouns so safe refusals such as
# 「停药请咨询医生」are not blocked while 「建议你停药」still is.
MEDICAL_BOUNDARY_TERMS: tuple[str, ...] = (
    "诊断",
    "确诊",
    "处方",
    "给药",
    "建议停药",
    "建议换药",
    "建议你停",
    "必须停药",
    "可以停用",
    "别再吃",
    "你应当",
    "你必须",
    "诊断:",
    "Diagnosis:",
    "Prescription:",
    "buy",
    "purchase",
    "order",
    "点击购买",
    "咨询电话",
    "添加微信",
)

DATA_EXFILTRATION_TERMS: tuple[str, ...] = (
    "身份证号",
    "身份证号码",
    "联系方式",
    "手机号码",
    "银行卡号",
)


def medical_boundary_hits(text: str) -> list[str]:
    """Return boundary terms that appear in ``text`` (case-insensitive for Latin)."""
    if not text:
        return []
    lowered = text.casefold()
    hits: list[str] = []
    for term in MEDICAL_BOUNDARY_TERMS:
        needle = term.casefold()
        if needle in lowered or term in text:
            hits.append(term)
    return hits
