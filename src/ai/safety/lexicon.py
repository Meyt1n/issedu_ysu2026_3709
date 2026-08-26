"""Shared safety / routing lexicon for the local health assistant.

Classification keywords, follow-up sanitizers, and medical-boundary
refusals used to live as three independent lists in ``tool_call.py``.
A missed synonym in one list (but not another) created uneven routing —
for example a colloquial「吃错药了」could fall through to ``GENERAL``
while the same intent expressed as「误服」was blocked.  Keep one source
of truth here; ``tool_call`` imports the shared tuples.
"""

from __future__ import annotations

import re

# Emergency descriptions: route to URGENT and escalate.
URGENT_ROUTE_TERMS: tuple[str, ...] = (
    "呼吸困难",
    "意识异常",
    "疑似中毒",
    "昏迷",
    "抽搐",
    "严重过敏",
)

# Symptom / “what medicine for …” guidance: explain approved knowledge +
# allergy/disease history.  Household formulary is optional enrichment.
SYMPTOM_MEDICATION_INTENT_TERMS: tuple[str, ...] = (
    "吃什么药",
    "用什么药",
    "吃点什么药",
    "该吃什么药",
    "应该吃什么药",
    "可以吃什么药",
    "吃啥药",
    "开什么药",
    "用啥药",
)

SYMPTOM_CONTEXT_TERMS: tuple[str, ...] = (
    "感冒",
    "发烧",
    "发热",
    "咳嗽",
    "头疼",
    "头痛",
    "腹泻",
    "喉咙痛",
    "咽痛",
    "流鼻涕",
    "鼻塞",
    "乏力",
    "不舒服",
    "过敏",
    "皮疹",
)

# High-risk individual medication decisions: stop/switch/dose/interaction.
# These still require reviewed knowledge and must not become prescriptions.
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
    "开个处方",
    "开处方",
    "帮我开药",
    "调整一下剂量",
)

# Follow-up prompts must not invite dosage / stop / switch decisions.
FOLLOW_UP_RISK_TERMS: tuple[str, ...] = MEDICATION_SAFETY_ROUTE_TERMS + (
    "几粒",
    "几片",
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

TEACHING_REMINDER = (
    "【教学提醒】以上内容仅供居家照护教学演示，不能替代医生或药师的诊断与个体用药指导。"
)

# A refusal or safety disclaimer is not itself a prohibited medical directive.
# Check the short phrase immediately before a matched noun so text such as
# “不诊断、不开处方” remains answerable while “建议开处方” is blocked.
_MEDICAL_NEGATION_PREFIXES: tuple[str, ...] = (
    "不",
    "不要",
    "无需",
    "不用",
    "禁止",
    "请勿",
    "不能",
    "无法",
    "不得",
    "避免",
    "不提供",
    "不建议",
    "不构成",
    "不开",
    "不要开",
    "不能开",
    "不得开",
)


def _is_negated_medical_term(text: str, start: int) -> bool:
    prefix = text[max(0, start - 24):start]
    return any(prefix.endswith(marker) for marker in _MEDICAL_NEGATION_PREFIXES) or any(
        marker in prefix for marker in ("不能替代", "不可作为", "不应作为", "不构成")
    )


def medical_boundary_hits(text: str) -> list[str]:
    """Return boundary terms that appear in ``text`` (case-insensitive for Latin)."""
    if not text:
        return []
    lowered = text.casefold()
    hits: list[str] = []
    for term in MEDICAL_BOUNDARY_TERMS:
        if term == "处方":
            # Teaching answers often mention OTC「非处方」资料; that must not
            # trip the prescription boundary.
            if any(
                not text[max(0, match.start() - 8):match.start()].endswith("非")
                and not _is_negated_medical_term(text, match.start())
                for match in re.finditer("处方", text)
            ):
                hits.append(term)
            continue
        needle = term.casefold()
        if needle not in lowered and term not in text:
            continue
        start = lowered.find(needle)
        if start >= 0 and _is_negated_medical_term(text, start):
            continue
        if term in text and _is_negated_medical_term(text, text.find(term)):
            continue
        if needle in lowered or term in text:
            hits.append(term)
    return hits
