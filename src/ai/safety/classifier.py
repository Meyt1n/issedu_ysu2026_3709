"""Dual-channel question classification for the local health assistant.

Channel A is a deterministic lexicon (always on). Channel B is an optional
loopback Ollama classifier for colloquial near-synonyms the lexicon misses.
Results are merged by severity so a medication-safety hit from either side
wins over GENERAL. Classification is a routing hint, never a diagnosis.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any

from ai.safety.lexicon import (
    MEDICATION_SAFETY_ROUTE_TERMS,
    SYMPTOM_CONTEXT_TERMS,
    SYMPTOM_MEDICATION_INTENT_TERMS,
    URGENT_ROUTE_TERMS,
)

logger = logging.getLogger(__name__)

QUERY_TYPES: tuple[str, ...] = (
    "URGENT",
    "MEDICATION_SAFETY",
    "SYMPTOM_MEDICATION",
    "MEDICATION_RECORD",
    "FAMILY_RECORD",
    "RULE_EVIDENCE",
    "GENERAL",
)

# Higher wins when merging lexicon + model channels.
_QUERY_TYPE_SEVERITY: dict[str, int] = {
    "URGENT": 100,
    "MEDICATION_SAFETY": 90,
    "SYMPTOM_MEDICATION": 80,
    "MEDICATION_RECORD": 50,
    "FAMILY_RECORD": 40,
    "RULE_EVIDENCE": 30,
    "GENERAL": 0,
}

_CLASSIFIER_SYSTEM = (
    "你是本地居家照护助手的问题路由分类器，不是医生。"
    "只输出一个 JSON 对象：{\"query_type\":\"<TYPE>\"}。"
    "允许的 TYPE：URGENT、MEDICATION_SAFETY、SYMPTOM_MEDICATION、MEDICATION_RECORD、"
    "FAMILY_RECORD、RULE_EVIDENCE、GENERAL。"
    "规则：危及生命的紧急描述→URGENT；剂量/停药/换药/误服/过量/同服/"
    "吃错药或近义口语→MEDICATION_SAFETY；症状问“吃什么药”类资料解释→SYMPTOM_MEDICATION；"
    "查用药清单→MEDICATION_RECORD；"
    "查家庭健康档案→FAMILY_RECORD；查规则/证据依据→RULE_EVIDENCE；其余→GENERAL。"
    "不要诊断，不要解释，不要输出其它字段。"
)


def classify_question_lexicon(query: str) -> str:
    """Deterministic lexicon route used as the hard safety fallback."""
    normalized = re.sub(r"\s+", "", query.casefold())
    if any(term in normalized for term in URGENT_ROUTE_TERMS):
        return "URGENT"
    if any(term in normalized for term in ("一起吃", "一同服用", "共同服用")) and any(
        term in normalized for term in ("药", "阿莫西林", "布洛芬", "处方")
    ):
        return "MEDICATION_SAFETY"
    if any(term in normalized for term in MEDICATION_SAFETY_ROUTE_TERMS):
        return "MEDICATION_SAFETY"
    medicine_intent = any(term in normalized for term in SYMPTOM_MEDICATION_INTENT_TERMS)
    symptom_context = any(term in normalized for term in SYMPTOM_CONTEXT_TERMS)
    if medicine_intent or (
        symptom_context and any(term in normalized for term in ("药", "用药", "吃药"))
    ):
        return "SYMPTOM_MEDICATION"
    if any(
        term in normalized
        for term in (
            "正在用药",
            "在用药",
            "用药记录",
            "药品记录",
            "药品清单",
            "扫描的药",
            "刚才扫描",
            "有哪些药",
            "药名",
            "用药",
            "吃药了吗",
            "今天吃药",
            "有没有吃药",
            "服药了吗",
            "确认服药",
            "今天药",
        )
    ):
        return "MEDICATION_RECORD"
    if any(
        term in normalized
        for term in (
            "家庭档案",
            "健康档案",
            "健康记录",
            "最近发生",
            "最近有哪些",
            "过敏史",
            "疾病记录",
            "成员信息",
            "健康变化",
            "健康事件",
        )
    ):
        return "FAMILY_RECORD"
    if any(
        term in normalized
        for term in (
            "规则",
            "提醒依据",
            "风险依据",
            "引用",
            "来源",
            "证据",
            "依据",
        )
    ):
        return "RULE_EVIDENCE"
    return "GENERAL"


def normalize_query_type(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip().upper().replace("-", "_").replace(" ", "_")
    return candidate if candidate in _QUERY_TYPE_SEVERITY else None


def merge_query_types(*types: str | None) -> str:
    """Return the highest-severity valid type; empty input → GENERAL."""
    best = "GENERAL"
    best_score = _QUERY_TYPE_SEVERITY[best]
    for item in types:
        normalized = normalize_query_type(item)
        if normalized is None:
            continue
        score = _QUERY_TYPE_SEVERITY[normalized]
        if score > best_score:
            best = normalized
            best_score = score
    return best


def parse_model_query_type(raw: str) -> str | None:
    """Extract a query_type from model JSON or bare label text."""
    text = (raw or "").strip()
    if not text:
        return None
    # Prefer JSON object when present.
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            return normalize_query_type(payload.get("query_type") or payload.get("type"))
    # Bare label fallback: first matching known type token.
    upper = text.upper()
    for label in QUERY_TYPES:
        if label in upper:
            return label
    return None


def classify_question_model(
    query: str,
    *,
    chat: Callable[..., dict[str, Any]],
    model: str,
    timeout: float = 3.0,
) -> str | None:
    """Ask a local model for a routing label. Failures return None."""
    trimmed = re.sub(r"\s+", " ", query).strip()
    if not trimmed or not model or model == "unavailable":
        return None
    try:
        response = chat(
            model=model,
            messages=[
                {"role": "system", "content": _CLASSIFIER_SYSTEM},
                {"role": "user", "content": trimmed[:500]},
            ],
            temperature=0.0,
            max_tokens=32,
            timeout=timeout,
            response_format={"type": "object", "properties": {"query_type": {"type": "string"}}},
        )
    except Exception as exc:  # noqa: BLE001 — classifier must never break chat
        logger.info("model classifier unavailable: %s", str(exc)[:120])
        return None

    message = response.get("message") if isinstance(response, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        return None
    return parse_model_query_type(content)


def classify_question_dual(
    query: str,
    *,
    model_enabled: bool = False,
    is_loopback_url: Callable[[str], bool] | None = None,
    ollama_base_url: str | None = None,
    ollama_model: str | None = None,
    ollama_timeout: float = 3.0,
    chat_factory: Callable[[str], Any] | None = None,
) -> str:
    """Lexicon always runs; optional loopback model merges by severity."""
    return classify_question_dual_detail(
        query,
        model_enabled=model_enabled,
        is_loopback_url=is_loopback_url,
        ollama_base_url=ollama_base_url,
        ollama_model=ollama_model,
        ollama_timeout=ollama_timeout,
        chat_factory=chat_factory,
    )["merged"]


def classify_question_dual_detail(
    query: str,
    *,
    model_enabled: bool = False,
    is_loopback_url: Callable[[str], bool] | None = None,
    ollama_base_url: str | None = None,
    ollama_model: str | None = None,
    ollama_timeout: float = 3.0,
    chat_factory: Callable[[str], Any] | None = None,
    override: str | None = None,
) -> dict[str, Any]:
    """Return lexicon / model / merged / override for agent_trace observability."""
    lexicon_type = classify_question_lexicon(query)
    model_type: str | None = None
    if model_enabled and ollama_base_url and ollama_model:
        if is_loopback_url is not None and not is_loopback_url(ollama_base_url):
            logger.warning("model classifier skipped: non-loopback Ollama URL")
        elif chat_factory is not None:
            client = chat_factory(ollama_base_url)
            chat_fn = client.chat if hasattr(client, "chat") else client
            model_type = classify_question_model(
                query,
                chat=chat_fn,
                model=ollama_model,
                timeout=ollama_timeout,
            )
    auto_merged = merge_query_types(lexicon_type, model_type)
    override_type = normalize_query_type(override)
    merged = override_type or auto_merged
    return {
        "lexicon": lexicon_type,
        "model": model_type,
        "merged": merged,
        "override": override_type,
        "model_enabled": bool(model_enabled),
    }
