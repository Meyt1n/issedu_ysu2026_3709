"""HCT-430 local multi-agent orchestration.

The agents are application components, not remotely hosted workers:

* the router, database agent, knowledge agent and synthesis agent run in the
  API process;
* the synthesis model is required to be a loopback Ollama endpoint;
* the database agent can only call the existing read-only, authorised tool
  whitelist;
* web search is a separately gated local tool.  It is disabled by default and
  receives only a redacted user query, never member context or database data.

External search results are supplemental references.  They are never treated
as approved medical evidence and never enter the assistant's local citation
list.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event, Lock
from typing import Any

from ai.safety.classifier import inherit_query_type_from_history
from ai.safety.lexicon import sanitize_answer_sentences
from ai.safety.seasonal_context import is_seasonal_symptom_query, seasonal_care_context

from app.config import Settings, get_settings
from app.db import SessionLocal
from app.egress_guard import is_web_search_egress_allowed
from app.models import AccessAudit
from app.open_chat import (
    coerce_open_model_answer,
    effective_max_tokens,
    is_open_chat,
    local_clock_context,
)
from app.retrieval_cache import (
    cache_get,
    cache_put,
    clear_actor_session,
    digest_query,
    make_entry_key,
    make_session_key,
)
from app.search_providers import (
    SearchRateLimited,
    execute_web_search,
    is_fixture_search_provider,
    search_ops_snapshot,
)
from app.tool_call import (
    ASSISTANT_SYSTEM_PROMPT,
    HealthAssistantOutput,
    OllamaClient,
    _latest_user_query,
    _looks_like_knowledge_citation,
    _parse_assistant_output,
    _unmatched_source_tokens,
    append_risk_statement,
    build_degrade_response,
    classify_question_detail,
    degrade_result,
    dose_decision_result,
    execute_whitelisted_tool,
    filter_claimed_citations,
    is_loopback_ollama_url,
    question_type_label,
    risk_notice_for_question,
    suggest_follow_up_questions,
    symptom_knowledge_gap_result,
    validate_member_tool_scope,
)

logger = logging.getLogger(__name__)

_SENSITIVE_QUERY_PATTERNS = (
    re.compile(r"(?i)(?:actor|household|member)[-_ ]?id\s*[:=：]\s*[A-Za-z0-9_-]+"),
    re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I),
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
)
_QUERY_KEY_PATTERN = re.compile(
    r"(?i)(?:actor|household|member|家庭|成员|用户)(?:[-_ ]?id)?\s*[:=：]\s*[^\s,，;；]+"
)
_GREETING_QUERIES = {"你好", "您好", "hello", "hi", "在吗", "你能做什么"}


def _is_greeting(query: str) -> bool:
    return re.sub(r"\s+", "", str(query or "").casefold()) in _GREETING_QUERIES


# User-facing step names; the frontend renders these directly, so they use
# product wording rather than internal engineering terms.
_AGENT_ROLES = {
    "router": "问题识别",
    "database": "健康档案核对",
    "rules": "规则依据核对",
    "knowledge": "本地资料检索",
    "web_search": "联网参考",
    "synthesis": "回答生成",
}

_GREETING_ANSWER = (
    "你好，我是家庭健康助手。我可以帮你查看已确认的健康记录、"
    "解释提醒和风险的规则依据，也可以查找已审核的护理资料。"
    "请告诉我你想了解的内容。"
)


@dataclass(frozen=True)
class AgentDecision:
    """Routing decision for one agent in the current request."""

    run: bool
    skip_reason: str = ""
    reason_code: str = ""


def plan_agent_execution(
    query_type: str,
    *,
    household_id: str | None,
    member_id: str | None,
    allow_network_search: bool = False,
) -> dict[str, AgentDecision]:
    """Decide which agents this request actually needs.

    The router is a real gate: agents that cannot contribute evidence for the
    classified question type are skipped instead of being executed in order.

    Web search follows the user's per-request opt-in: once the user ticks
    「补充联网参考」, every non-urgent question type may run the search agent
    (which still enforces the deployment switch, redaction and the egress
    allowlist itself).  Routing must never silently drop an explicit opt-in —
    that was the HCT-430 "opted in but trace says skipped" defect.
    """
    member_selected = bool(household_id and member_id)

    database = (
        AgentDecision(run=True)
        if member_selected
        else AgentDecision(run=False, skip_reason="未选择家庭成员，本次未读取健康档案")
    )
    if not member_selected:
        rules = AgentDecision(run=False, skip_reason="未选择家庭成员，本次未核对规则依据")
    elif query_type in {"RULE_EVIDENCE", "URGENT", "MEDICATION_SAFETY"}:
        rules = AgentDecision(run=True)
    else:
        rules = AgentDecision(run=False, skip_reason="本类问题无需单独核对规则依据")

    if query_type == "RULE_EVIDENCE" and member_selected:
        # Rule explanations cite the deterministic rule records returned by
        # the database step; retrieving generic documents adds no evidence.
        knowledge = AgentDecision(
            run=False, skip_reason="规则依据直接来自本地规则记录，无需检索资料库"
        )
    else:
        # GENERAL / HCT-450 teaching questions also retrieve the reviewed local
        # library (cheap, on-box).  Skipping it left flu-type questions with
        # zero evidence; greetings never reach this plan (dedicated fast path).
        knowledge = AgentDecision(run=True)

    if query_type == "URGENT":
        web_search = AgentDecision(
            run=False,
            skip_reason="紧急问题优先本地处置，未发起外部搜索",
            reason_code="URGENT_LOCAL_FIRST",
        )
    elif not allow_network_search:
        web_search = AgentDecision(
            run=False,
            skip_reason="本次请求未开启联网搜索",
            reason_code="NOT_OPTED_IN",
        )
    else:
        web_search = AgentDecision(run=True)

    return {
        "database": database,
        "rules": rules,
        "knowledge": knowledge,
        "web_search": web_search,
    }


# NOTE: the former ``_medication_safety_short_circuit`` (EVIDENCE_REQUIRED
# wall when no local knowledge matched) was removed by decision 2B: the model
# may answer without local evidence and the server appends an explicit
# low-evidence risk statement instead of walling off the whole turn.


# ── Context binding: one assistant session must not mix members ─────────
_CONTEXT_BINDING_LOCK = Lock()
# actor-session digest -> "household|member" scope bound to that session.
_SESSION_MEMBER_BINDING: dict[str, str] = {}


def bind_session_member_context(
    messages: list[dict[str, Any]],
    *,
    assistant_session_id: str | None,
    actor_id: str,
    household_id: str | None,
    member_id: str | None,
) -> tuple[list[dict[str, Any]], bool]:
    """Discard chat history recorded for a different member (context binding).

    When the same assistant session switches to another member, earlier
    user/assistant turns (which may contain the previous member's facts) are
    dropped: only server system context and the latest user question remain,
    and the session's retrieval cache is cleared.  Returns
    ``(messages, member_switched)``.
    """
    session_id = str(assistant_session_id or "").strip()
    if not session_id:
        return messages, False
    key = hashlib.sha256(f"{session_id}|{actor_id}".encode()).hexdigest()[:32]
    scope = f"{household_id or ''}|{member_id or ''}"
    with _CONTEXT_BINDING_LOCK:
        previous = _SESSION_MEMBER_BINDING.get(key)
        _SESSION_MEMBER_BINDING[key] = scope
        while len(_SESSION_MEMBER_BINDING) > 512:
            _SESSION_MEMBER_BINDING.pop(next(iter(_SESSION_MEMBER_BINDING)))
    if previous is None or previous == scope:
        return messages, False
    trimmed = [
        message for message in messages
        if isinstance(message, dict) and message.get("role") == "system"
    ]
    last_user = next(
        (
            message for message in reversed(messages)
            if isinstance(message, dict) and message.get("role") == "user"
        ),
        None,
    )
    if last_user is not None:
        trimmed.append(last_user)
    clear_actor_session(assistant_session_id=session_id, actor_id=actor_id)
    logger.info("HCT-430 context binding dropped cross-member history for session")
    return trimmed, True


def reset_session_member_bindings() -> None:
    """Test helper: forget all session→member bindings."""
    with _CONTEXT_BINDING_LOCK:
        _SESSION_MEMBER_BINDING.clear()


def redact_web_query(query: str, sensitive_values: list[str | None] | None = None) -> str:
    """Return a short search query without identity or record identifiers."""
    redacted = str(query or "")
    for pattern in _SENSITIVE_QUERY_PATTERNS:
        redacted = pattern.sub(" ", redacted)
    redacted = _QUERY_KEY_PATTERN.sub(" ", redacted)
    for value in sensitive_values or []:
        value = str(value or "").strip()
        # Chinese display names are commonly two characters; do not leave a
        # selected member name in the external query just because it is short.
        if value and len(value) >= 2:
            redacted = re.sub(re.escape(value), " ", redacted, flags=re.I)
    redacted = re.sub(r"\s+", " ", redacted).strip()
    return redacted[:240]


# ── Decision 4B: tiered network-context opt-in ──────────────────────────
#
# ``query_only``（默认）: only the redacted question leaves the device.
# ``symptom``: adds symptom keywords found in this conversation's user turns.
# ``member``: additionally adds anonymised, whitelisted member facts —
#   allergy / chronic-disease / confirmed drug *names* only, never member or
#   household identifiers.  Every tier passes the same redaction; the final
#   network query is surfaced to the caller before the request is sent.
NETWORK_CONTEXT_LEVELS: tuple[str, ...] = ("query_only", "symptom", "member")

# Whitelisted member-state fields that may contribute anonymous context.
_MEMBER_CONTEXT_FIELDS = ("allergies", "diseases", "drugs")


def build_network_context_terms(
    level: str,
    *,
    messages: list[dict[str, Any]] | None = None,
    database: dict[str, Any] | None = None,
) -> list[str]:
    """Return deduplicated, anonymised context terms for the chosen tier."""
    normalized = (level or "query_only").strip().casefold()
    if normalized not in NETWORK_CONTEXT_LEVELS or normalized == "query_only":
        return []
    terms: list[str] = []
    from ai.safety.lexicon import SYMPTOM_CONTEXT_TERMS

    conversation_text = " ".join(
        str(message.get("content") or "")
        for message in messages or []
        if isinstance(message, dict) and message.get("role") == "user"
    )
    terms.extend(term for term in SYMPTOM_CONTEXT_TERMS if term in conversation_text)
    if normalized == "member":
        state = {}
        member_state = (database or {}).get("get_member_state")
        if isinstance(member_state, dict) and isinstance(member_state.get("state"), dict):
            state = member_state["state"]
        for field_name in _MEMBER_CONTEXT_FIELDS:
            for item in state.get(field_name) or []:
                name = str((item or {}).get("name") or (item or {}).get("drug") or "").strip()
                if name:
                    prefix = {"allergies": "过敏史", "diseases": "病史", "drugs": "在用"}[
                        field_name
                    ]
                    terms.append(f"{prefix}{name}")
    return list(dict.fromkeys(terms))[:8]


def _trace(
    agent_id: str,
    role: str,
    status: str,
    started: float,
    summary: str,
    *,
    network_used: bool = False,
    source_count: int = 0,
    cache_hit: bool = False,
    classifier: dict[str, Any] | None = None,
    reason_code: str = "",
) -> dict[str, Any]:
    result = {
        "agent_id": agent_id,
        "role": role,
        "status": status,
        "local": True,
        "network_used": network_used,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "summary": summary[:240],
        "source_count": source_count,
        "cache_hit": cache_hit,
    }
    if classifier is not None:
        result["classifier"] = dict(classifier)
    if reason_code:
        # Machine-readable cause for skipped/blocked/degraded steps so the UI
        # and audits can explain the outcome without parsing Chinese copy.
        result["reason_code"] = reason_code
    return result


def get_agent_catalog(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    search_ops = search_ops_snapshot(settings)
    web_search_ready = bool(search_ops["web_search_ready"])
    fixture_provider = is_fixture_search_provider(settings)
    # A machine-readable reason plus an operator hint let the UI say exactly
    # why search is not running and how to turn it on, instead of a silent
    # disabled checkbox.
    if not settings.agent_web_search_enabled:
        unavailable_reason = "DEPLOYMENT_DISABLED"
        enable_hint = (
            "在 .env 设置 AGENT_WEB_SEARCH_ENABLED=true 并重启 API；"
            "离线课堂演示可同时设置 AGENT_WEB_SEARCH_PROVIDER=fixture（不出网）。"
        )
    elif not is_web_search_egress_allowed(settings.agent_web_search_url.strip(), settings):
        unavailable_reason = "EGRESS_BLOCKED"
        enable_hint = (
            "AGENT_WEB_SEARCH_URL 必须是 HTTPS，且其域名需列入 "
            "AGENT_WEB_SEARCH_ALLOWED_DOMAINS（如 html.duckduckgo.com），修改后重启 API。"
        )
    elif search_ops.get("last_search_status") == "failure":
        unavailable_reason = "PROVIDER_UNAVAILABLE"
        enable_hint = (
            "最近一次搜索请求未能连接到配置的提供方；请检查出口网络，或切换到获批的 "
            "SearXNG 地址后重启 API。系统不会用缓存或夹具冒充真实结果。"
        )
    else:
        unavailable_reason = "OPT_IN_REQUIRED"
        enable_hint = (
            "教学夹具搜索已就绪（不出网）；在助手页勾选「补充联网参考」即可演示外部参考。"
            if fixture_provider
            else "部署已就绪；在助手页勾选「补充联网参考」后，本次请求才会发送脱敏查询。"
        )
    return {
        "mode": "multi_agent",
        "all_agents_local": True,
        "ollama_local_only": True,
        "web_search_enabled": settings.agent_web_search_enabled,
        # True only when the deployment switch and allowlist pass and the last
        # observed provider request did not fail.  A failed provider must not
        # remain advertised as a ready external capability.
        "web_search_ready": web_search_ready,
        "web_search_provider": settings.agent_web_search_provider,
        "web_search_offline_fixture": fixture_provider,
        "web_search_unavailable_reason": unavailable_reason,
        "web_search_enable_hint": enable_hint,
        "web_search_requires_request_opt_in": True,
        # Decision 3B: allowlist keeps the fixed-host posture; open allows
        # SSRF-guarded public HTTPS result-page follow-up with rule filtering.
        "web_search_egress_mode": getattr(
            settings, "agent_web_search_egress_mode", "allowlist"
        ),
        # Decision 4B: per-request opt-in tiers for outbound context.
        "network_context_levels": list(NETWORK_CONTEXT_LEVELS),
        "open_chat": is_open_chat(settings),
        "open_max_tokens": int(settings.agent_open_max_tokens)
        if is_open_chat(settings)
        else None,
        "agents": [
            {
                "agent_id": "router",
                "name": "问题识别",
                "role": "识别问题类型并规划需要执行的检索步骤",
                "local": True,
                "network": False,
            },
            {
                "agent_id": "database",
                "name": "健康档案核对",
                "role": "通过授权只读工具核对成员记录、状态与照护计划",
                "local": True,
                "network": False,
            },
            {
                "agent_id": "rules",
                "name": "规则依据核对",
                "role": "核对确定性规则命中与风险提醒，不由模型改写等级",
                "local": True,
                "network": False,
            },
            {
                "agent_id": "knowledge",
                "name": "本地资料检索",
                "role": "检索已审核的本地资料并绑定可核验出处",
                "local": True,
                "network": False,
            },
            {
                "agent_id": "web_search",
                "name": "联网参考",
                "role": "仅在部署与本次请求同时允许时发送脱敏查询",
                "local": True,
                "network": True,
            },
            {
                "agent_id": "synthesis",
                "name": "回答生成",
                "role": "使用本机模型汇总已授权证据并生成回答",
                "local": True,
                "network": False,
            },
        ],
    }


def _tool_payload(
    session: Any,
    *,
    name: str,
    arguments: dict[str, Any],
    actor_id: str,
    household_id: str | None,
    member_id: str | None,
    access_purpose: str | None,
) -> dict[str, Any]:
    """Only the existing server-side whitelist may touch the database."""
    return execute_whitelisted_tool(
        session,
        name=name,
        arguments=arguments,
        actor_id=actor_id,
        household_id=household_id,
        member_id=member_id,
        access_purpose=access_purpose,
    )


def _result_source_count(payload: dict[str, Any]) -> int:
    return sum(
        len(item.get("sources") or [])
        for item in payload.values()
        if isinstance(item, dict)
    )


def _member_cache_entry(
    retrieval_session_key: str | None,
    *,
    agent: str,
    query_material: str,
) -> str | None:
    if not retrieval_session_key:
        return None
    return make_entry_key(
        retrieval_session_key,
        agent=agent,
        query_digest=digest_query(query_material),
    )


def _member_cache_is_authorized(
    session: Any,
    *,
    actor_id: str,
    household_id: str | None,
    member_id: str | None,
    access_purpose: str | None,
) -> bool:
    if session is None:
        return False
    try:
        return validate_member_tool_scope(
            session,
            actor_id=actor_id,
            household_id=household_id,
            member_id=member_id,
            access_purpose=access_purpose,
        ) is None
    except Exception:
        logger.warning("cached member scope could not be revalidated", exc_info=True)
        return False


def _database_agent(
    session: Any,
    *,
    query: str,
    query_type: str,
    actor_id: str,
    household_id: str | None,
    member_id: str | None,
    access_purpose: str | None,
    retrieval_session_key: str | None = None,
    cache_ttl_seconds: float = 0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    if not household_id or not member_id:
        return {}, _trace(
            "database", _AGENT_ROLES["database"], "skipped", started,
            "未选择家庭成员，本次未读取健康档案",
        )

    entry_key = _member_cache_entry(
        retrieval_session_key,
        agent="database",
        query_material=query_type,
    )
    cached = cache_get(entry_key) if entry_key and cache_ttl_seconds > 0 else None
    if isinstance(cached, dict) and _member_cache_is_authorized(
        session,
        actor_id=actor_id,
        household_id=household_id,
        member_id=member_id,
        access_purpose=access_purpose,
    ):
        return cached, _trace(
            "database",
            _AGENT_ROLES["database"],
            "completed",
            started,
            "已复用本会话中仍获授权的健康档案核对结果",
            source_count=_result_source_count(cached),
            cache_hit=True,
        )

    names: list[str]
    if query_type in {
        "MEDICATION_SAFETY",
        "SYMPTOM_MEDICATION",
        "MEDICATION_RECORD",
        "FAMILY_RECORD",
        "URGENT",
    }:
        names = ["get_member_state", "get_health_events", "get_care_plan_status"]
    else:
        names = ["get_member_state"]

    facts: dict[str, Any] = {}
    errors: list[str] = []
    for name in names:
        args: dict[str, Any] = {
            "household_id": household_id,
            "member_id": member_id,
        }
        if name == "get_health_events":
            args["limit"] = 12
        result = _tool_payload(
            session,
            name=name,
            arguments=args,
            actor_id=actor_id,
            household_id=household_id,
            member_id=member_id,
            access_purpose=access_purpose,
        )
        facts[name] = result
        if result.get("error"):
            errors.append(str(result["error"]))

    if entry_key and not errors:
        cache_put(entry_key, facts, ttl_seconds=cache_ttl_seconds)
    return facts, _trace(
        "database", _AGENT_ROLES["database"],
        "blocked" if "TOOL_SCOPE_DENIED" in errors else "completed",
        started,
        "已核对该成员的健康记录与照护计划" if not errors else "部分健康档案暂时无法读取",
        source_count=_result_source_count(facts),
    )


def _rules_agent(
    session: Any,
    *,
    query_type: str,
    actor_id: str,
    household_id: str | None,
    member_id: str | None,
    access_purpose: str | None,
    retrieval_session_key: str | None = None,
    cache_ttl_seconds: float = 0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    if not household_id or not member_id:
        return {}, _trace(
            "rules",
            _AGENT_ROLES["rules"],
            "skipped",
            started,
            "未选择家庭成员，本次未核对规则依据",
        )

    entry_key = _member_cache_entry(
        retrieval_session_key,
        agent="rules",
        query_material=query_type,
    )
    cached = cache_get(entry_key) if entry_key and cache_ttl_seconds > 0 else None
    if isinstance(cached, dict) and _member_cache_is_authorized(
        session,
        actor_id=actor_id,
        household_id=household_id,
        member_id=member_id,
        access_purpose=access_purpose,
    ):
        return cached, _trace(
            "rules",
            _AGENT_ROLES["rules"],
            "completed",
            started,
            "已复用本会话中仍获授权的规则核对结果",
            source_count=_result_source_count(cached),
            cache_hit=True,
        )

    facts: dict[str, Any] = {}
    errors: list[str] = []
    for name in ("get_applied_rules", "get_risk_alerts"):
        result = _tool_payload(
            session,
            name=name,
            arguments={"household_id": household_id, "member_id": member_id},
            actor_id=actor_id,
            household_id=household_id,
            member_id=member_id,
            access_purpose=access_purpose,
        )
        facts[name] = result
        if result.get("error"):
            errors.append(str(result["error"]))

    if entry_key and not errors:
        cache_put(entry_key, facts, ttl_seconds=cache_ttl_seconds)
    return facts, _trace(
        "rules",
        _AGENT_ROLES["rules"],
        "blocked" if "TOOL_SCOPE_DENIED" in errors else "completed",
        started,
        "已核对确定性规则与风险提醒" if not errors else "规则依据暂时无法读取",
        source_count=_result_source_count(facts),
    )


def _knowledge_agent(
    session: Any,
    *,
    query: str,
    actor_id: str,
    household_id: str | None,
    member_id: str | None,
    access_purpose: str | None,
    retrieval_session_key: str | None = None,
    cache_ttl_seconds: float = 0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    entry_key = _member_cache_entry(
        retrieval_session_key,
        agent="knowledge",
        query_material=query,
    )
    cached = cache_get(entry_key) if entry_key and cache_ttl_seconds > 0 else None
    if isinstance(cached, dict):
        document_ids = {
            str(item.get("document_id") or "")
            for item in cached.get("results") or []
            if isinstance(item, dict) and item.get("document_id")
        }
        still_authorized = all(
            not _tool_payload(
                session,
                name="get_document_metadata",
                arguments={"document_id": document_id},
                actor_id=actor_id,
                household_id=household_id,
                member_id=member_id,
                access_purpose=access_purpose,
            ).get("error")
            for document_id in document_ids
        )
        if still_authorized:
            result_count = len(cached.get("results") or [])
            return cached, _trace(
                "knowledge",
                _AGENT_ROLES["knowledge"],
                "completed",
                started,
                "已复用本会话中仍获授权的本地资料检索结果",
                source_count=result_count,
                cache_hit=True,
            )

    result = _tool_payload(
        session,
        name="retrieve_knowledge",
        arguments={
            "query": query[:1000],
            "household_id": household_id,
            "member_id": member_id,
            "top_k": 5,
        },
        actor_id=actor_id,
        household_id=household_id,
        member_id=member_id,
        access_purpose=access_purpose,
    )
    result_count = len(result.get("results") or [])
    error = str(result.get("error") or "")
    # NO_RELEVANT_RESULTS means the search ran and simply found nothing.  An
    # empty / not-yet-seeded library (NO_AUTHORISED_DOCUMENTS, EMPTY_INDEX)
    # is a retrieval gap recorded as degraded — not a risk-control
    # interception.  "blocked" is reserved for scope/tool failures.
    if error == "NO_RELEVANT_RESULTS":
        status = "completed"
        summary = "本地资料库暂无与问题直接相关的内容"
    elif error in {"NO_AUTHORISED_DOCUMENTS", "EMPTY_INDEX"}:
        status = "degraded"
        summary = "本机暂无当前可用的已审核知识卡"
    elif error == "EMPTY_QUERY":
        status = "completed"
        summary = "问题内容过短，本地资料检索未能解析出检索词"
    elif error:
        status = "blocked"
        summary = "本地资料检索未完成"
    elif result_count:
        status = "completed"
        summary = "已找到相关的本地审核资料"
    else:
        status = "completed"
        summary = "本地资料库暂无直接相关的内容"
    if entry_key and not result.get("error"):
        cache_put(entry_key, result, ttl_seconds=cache_ttl_seconds)
    return result, _trace(
        "knowledge", _AGENT_ROLES["knowledge"],
        status,
        started,
        summary,
        source_count=result_count,
    )


def _web_search_agent(
    query: str,
    *,
    sensitive_values: list[str | None],
    allow_network_search: bool,
    settings: Settings,
    network_context_terms: list[str] | None = None,
    on_network_query: Callable[[str], None] | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any], str | None]:
    started = time.perf_counter()
    if not allow_network_search:
        return [], _trace(
            "web_search", _AGENT_ROLES["web_search"], "skipped", started,
            "本次请求未开启联网搜索",
            reason_code="NOT_OPTED_IN",
        ), None
    if not settings.agent_web_search_enabled:
        return [], _trace(
            "web_search", _AGENT_ROLES["web_search"], "blocked", started,
            "联网搜索未在当前部署启用（AGENT_WEB_SEARCH_ENABLED=false）",
            reason_code="DEPLOYMENT_DISABLED",
        ), None

    safe_query = redact_web_query(query, sensitive_values)
    if safe_query and network_context_terms:
        # 4B: opted-in context terms pass the same redaction as the query.
        combined = f"{safe_query} {' '.join(network_context_terms)}"
        safe_query = redact_web_query(combined, sensitive_values)
    if not safe_query:
        return [], _trace(
            "web_search", _AGENT_ROLES["web_search"], "blocked", started,
            "脱敏后没有可检索的内容",
            reason_code="EMPTY_QUERY_AFTER_REDACTION",
        ), None
    endpoint = settings.agent_web_search_url.strip()
    if not is_web_search_egress_allowed(endpoint, settings):
        return [], _trace(
            "web_search", _AGENT_ROLES["web_search"], "blocked", started,
            "搜索地址未通过出口白名单校验",
            reason_code="EGRESS_BLOCKED",
        ), safe_query

    fixture = is_fixture_search_provider(settings)
    # 4B: the exact outbound query is surfaced before the request is sent so
    # the UI can show users what leaves the device.
    if on_network_query is not None:
        on_network_query(safe_query)
    try:
        results = execute_web_search(safe_query, settings=settings)
        if fixture:
            summary = (
                f"已获取 {len(results)} 条教学夹具参考（未出网）"
                if results
                else "教学夹具搜索完成，未找到合适的参考"
            )
        else:
            summary = (
                f"已获取 {len(results)} 条外部参考"
                if results
                else "搜索完成，未找到合适的外部参考"
            )
        # An empty result set is a completed search, not a failure: the trace
        # must make clear that the call succeeded but found nothing.  The
        # fixture provider never leaves the process, so it must not claim
        # network usage.
        return results, _trace(
            "web_search", _AGENT_ROLES["web_search"], "completed", started,
            summary,
            network_used=not fixture,
            source_count=len(results),
        ), safe_query
    except SearchRateLimited:
        return [], _trace(
            "web_search", _AGENT_ROLES["web_search"], "degraded", started,
            "搜索请求过于频繁，已跳过本次联网参考",
            network_used=False,
            reason_code="RATE_LIMITED",
        ), safe_query
    except Exception as exc:
        logger.warning("HCT-430 web search failed: %s", str(exc)[:160])
        return [], _trace(
            "web_search", _AGENT_ROLES["web_search"], "degraded", started,
            "外部搜索暂时不可用，本地分析不受影响",
            network_used=not fixture,
            reason_code="SEARCH_FAILED",
        ), safe_query


def _compact_external_sources(results: list[dict[str, str]]) -> str:
    if not results:
        return (
            "无外部搜索结果；不要编造外部来源，也不要捏造「最近流行某某病毒」。"
            "仍可用【季节情境】做换季、着凉等生活化共情。"
        )
    lines = [
        "外部搜索结果仅供补充参考，不是已审核本地证据；不要在 sources 中引用它们，也不要输出网址。"
        "若摘要提到季节性呼吸道/流感样情况，可用口语转述为「最近外面常见的提醒」，并说明仅供参考。"
    ]
    for idx, item in enumerate(results[:3], 1):
        snippet = (item.get("snippet") or "无摘要")[:80]
        lines.append(f"[WEB-{idx}] {item['title']}：{snippet}")
        # Open egress mode (3B) may attach a rule-filtered page excerpt.
        excerpt = (item.get("page_excerpt") or "").strip()
        if excerpt:
            lines.append(f"[WEB-{idx} 页面摘录] {excerpt[:200]}")
    return "\n".join(lines)


def _network_status_note(
    web_trace: dict[str, Any] | None,
    *,
    external_count: int,
    fixture: bool,
) -> str:
    """Tell the synthesis model what the web-search node actually did.

    Without this the local model guesses about its own capabilities and
    answers「我不能访问外部网络」even when the user opted in and the search
    node ran — the answer must reflect the real trace state instead.
    """
    status = str((web_trace or {}).get("status") or "skipped")
    code = str((web_trace or {}).get("reason_code") or "")
    if status == "completed":
        if fixture:
            return (
                "【联网参考状态】本次联网参考节点已执行：教学夹具演示（不出网），"
                f"共 {external_count} 条外部参考。被问到能否联网时，如实说明"
                "「本次为教学夹具演示的外部参考，未真正出网」；"
                "不要声称自己没有联网参考功能。"
            )
        return (
            "【联网参考状态】本次已通过白名单出口执行受控联网搜索，"
            f"共 {external_count} 条外部参考。不要声称自己不能访问外部网络；"
            "外部参考只能作为补充说明，不是本地审核证据。"
        )
    if status == "skipped":
        if code == "URGENT_LOCAL_FIRST":
            return "【联网参考状态】紧急问题优先本地处置，本次未发起外部搜索。"
        return (
            "【联网参考状态】本次未执行联网参考（用户未勾选「补充联网参考」）。"
            "被问到能否联网时，如实说明：助手具备受控联网参考能力，"
            "但需要在提问时勾选「补充联网参考」；不要说自己完全不能联网。"
        )
    if code == "DEPLOYMENT_DISABLED":
        return (
            "【联网参考状态】当前部署未启用联网搜索，本次没有外部参考。"
            "被问到能否联网时，如实说明是部署开关未开启，需要部署负责人配置。"
        )
    if code == "EGRESS_BLOCKED":
        return (
            "【联网参考状态】联网参考被出口白名单拦截，本次没有外部参考；"
            "请如实说明外部搜索地址未通过安全校验，本地分析不受影响。"
        )
    return (
        "【联网参考状态】本次联网参考未成功（失败或限速），没有外部参考；"
        "如实说明外部搜索暂时不可用即可，不要编造外部结果，本地分析不受影响。"
    )


def _trim_knowledge_results(knowledge: dict[str, Any], *, limit: int = 3) -> dict[str, Any]:
    results = []
    for item in (knowledge.get("results") or [])[:limit]:
        if not isinstance(item, dict):
            continue
        results.append({
            "document_id": item.get("document_id"),
            "version": item.get("version"),
            "chunk_id": item.get("chunk_id"),
            "title": item.get("title"),
            "locator": item.get("locator"),
            "text": str(item.get("text") or "")[:400],
        })
    trimmed = {key: value for key, value in knowledge.items() if key != "results"}
    trimmed["results"] = results
    return trimmed


def _compact_local_evidence(
    database: dict[str, Any],
    knowledge: dict[str, Any],
    *,
    query_type: str,
    rules: dict[str, Any] | None = None,
) -> str:
    """Keep only the fields that matter for the classified question type."""
    if query_type == "RULE_EVIDENCE":
        selected = {
            key: database[key]
            for key in ("get_member_state",)
            if key in database
        }
    elif query_type in {"MEDICATION_SAFETY", "SYMPTOM_MEDICATION", "MEDICATION_RECORD", "URGENT"}:
        selected = {
            key: database[key]
            for key in ("get_member_state", "get_health_events", "get_care_plan_status")
            if key in database
        }
        # Prefer drug/allergy/plan slices when the member state payload is large.
        state = selected.get("get_member_state")
        if isinstance(state, dict) and isinstance(state.get("state"), dict):
            slim_state = dict(state)
            raw = state["state"]
            preferred = (
                ("allergies", "diseases", "drugs", "plans")
                if query_type == "SYMPTOM_MEDICATION"
                else ("drugs", "allergies", "plans", "diseases")
            )
            slim_state["state"] = {
                key: raw.get(key)
                for key in preferred
                if key in raw
            } or raw
            selected["get_member_state"] = slim_state
    elif query_type == "FAMILY_RECORD":
        selected = {
            key: database[key]
            for key in ("get_member_state", "get_health_events", "get_care_plan_status")
            if key in database
        }
    else:
        selected = {
            key: database[key]
            for key in ("get_member_state",)
            if key in database
        } or dict(database)

    payload = {
        "database_agent": selected,
        "rules_agent": dict(rules or {}),
        "knowledge_agent": _trim_knowledge_results(knowledge),
    }
    return json.dumps(payload, ensure_ascii=False, default=str)[:12_000]


def _build_evidence_preview(
    *,
    query_type: str,
    database: dict[str, Any],
    knowledge: dict[str, Any],
    rules: dict[str, Any],
    external_sources: list[dict[str, str]],
) -> dict[str, Any]:
    """Expose evidence shape only; never include member facts or source text."""
    knowledge_results = [
        item for item in knowledge.get("results") or [] if isinstance(item, dict)
    ]
    titles: list[str] = []
    for item in knowledge_results:
        title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip()[:120]
        if title and title not in titles:
            titles.append(title)
    return {
        "query_type": query_type,
        "database_tools": list(database),
        "knowledge_titles": titles,
        "knowledge_count": len(knowledge_results),
        "external_count": len(external_sources),
        "rule_tools": list(rules),
    }


def _emit_answer_tokens(answer: str, on_token: Callable[[str], None] | None) -> None:
    """Stream only the validated user-facing answer, never the raw model draft."""
    if on_token is None or not answer:
        return
    step = 12
    for index in range(0, len(answer), step):
        on_token(answer[index:index + step])


def _record_orchestration_audit(
    session: Any,
    *,
    actor_id: str,
    household_id: str | None,
    query_type: str,
    result: dict[str, Any],
) -> None:
    """Persist a redacted orchestration receipt; never store the user query."""
    if not household_id or session is None:
        return
    try:
        traces = result.get("agent_trace") or []
        steps = ",".join(
            f"{item.get('agent_id')}={item.get('status')}"
            for item in traces
            if isinstance(item, dict)
        )[:180]
        reason = (
            f"{query_type}|net={int(bool(result.get('network_used')))}"
            f"|deg={int(bool(result.get('degraded')))}|{steps}"
        )[:64]
        session.add(
            AccessAudit(
                household_id=household_id,
                authorization_id=None,
                actor_id=actor_id,
                operation="ASSISTANT",
                action="MULTI_AGENT_CHAT",
                data_field="orchestration",
                purpose="assistant",
                outcome="DENIED" if result.get("degraded") else "ALLOWED",
                reason=reason,
                request_id=result.get("orchestration_id"),
            )
        )
    except Exception:
        logger.warning("HCT-430 orchestration audit could not be written", exc_info=True)


class OrchestrationCancelled(RuntimeError):
    """Raised when the client disconnects or aborts the stream."""


def _synthesis_agent(
    *,
    messages: list[dict[str, Any]],
    query_type: str,
    database: dict[str, Any],
    knowledge: dict[str, Any],
    external_sources: list[dict[str, str]],
    model: str,
    max_tokens: int,
    temperature: float,
    settings: Settings,
    rules: dict[str, Any] | None = None,
    network_status_note: str | None = None,
    on_token: Callable[[str], None] | None = None,
    on_status: Callable[[str], None] | None = None,
    cancel_event: Event | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    rules = rules or {}
    open_chat = is_open_chat(settings)
    max_tokens = effective_max_tokens(max_tokens, settings)
    base = {
        "model": model,
        "query_type": query_type,
        # Unified server-side risk statement (2B/8C): the notice applies in
        # every mode, including open-chat.
        "risk_notice": risk_notice_for_question(query_type),
    }

    def cancelled() -> bool:
        return bool(cancel_event and cancel_event.is_set())

    def degraded(reason: str) -> dict[str, Any]:
        # A symptom-material question that cannot be answered because the
        # model itself is unavailable keeps the friendly deterministic
        # teaching fallback instead of the generic degrade wall.
        if (
            reason in {"SCHEMA_VALIDATION_FAILED", "MODEL_UNAVAILABLE"}
            and query_type == "SYMPTOM_MEDICATION"
            and not (knowledge.get("results") or [])
        ):
            payload = symptom_knowledge_gap_result(
                messages, model=model, query_type=query_type
            )
            payload["_trace"] = _trace(
                "synthesis", _AGENT_ROLES["synthesis"], "degraded", started,
                "模型暂不可用且本机无相关知识卡，已返回一般照护提示",
            )
            _emit_answer_tokens(str(payload.get("answer") or ""), on_token)
            return payload
        payload = degrade_result(build_degrade_response(reason), model, query_type=query_type)
        # A model/schema failure must not hide evidence that was actually
        # retrieved: point users at the references the earlier nodes found.
        if reason in {"SCHEMA_VALIDATION_FAILED", "MODEL_UNAVAILABLE"}:
            found: list[str] = []
            local_hits = len(knowledge.get("results") or [])
            if local_hits:
                found.append(f"{local_hits} 条本地审核资料")
            if external_sources:
                found.append(f"{len(external_sources)} 条外部参考")
            if found:
                payload["answer"] = (
                    f"{str(payload.get('answer') or '').rstrip()}\n\n"
                    f"本次检索已找到{ '和'.join(found) }，"
                    "可展开回答下方的「依据 / 外部参考」直接查看。"
                )
        payload["_trace"] = _trace(
            "synthesis", _AGENT_ROLES["synthesis"], "degraded", started,
            f"回答未通过本地校验（{reason}），已返回受控回复",
        )
        _emit_answer_tokens(str(payload.get("answer") or ""), on_token)
        return payload

    if cancelled():
        raise OrchestrationCancelled("cancelled before synthesis")

    if not is_loopback_ollama_url(settings.ollama_base_url):
        logger.warning("HCT-430 blocked non-loopback Ollama endpoint")
        return degraded("LOCAL_MODEL_ENDPOINT_REQUIRED")

    knowledge_results = knowledge.get("results") or []
    allowed_citations = [
        {
            "document_id": str(item.get("document_id") or ""),
            "version": str(item.get("version") or ""),
            "chunk_id": str(item.get("chunk_id") or ""),
            "document_title": str(item.get("title") or ""),
            "text": str(item.get("text") or ""),
            "locator": str(item.get("locator") or ""),
        }
        for item in knowledge_results
        if item.get("chunk_id") and item.get("document_id")
    ]
    allowed_fact_sources = {
        str(source).strip()
        for result in [*database.values(), *rules.values()]
        if isinstance(result, dict)
        for source in result.get("sources") or []
        if str(source).strip()
    }
    routing_hint = (
        f"【问题类型：{query_type}】只输出最终 JSON，不要复述内部智能体名称。"
        "sources 只能引用 database_agent 返回的 sources 或 knowledge_agent 返回的 chunk_id。"
    )
    if allowed_citations:
        listed_citations = "；".join(
            f"{item['chunk_id']}（{item['document_title'] or '未命名资料'}）"
            for item in allowed_citations[:5]
        )
        # 2B: citations are strongly preferred but no longer a hard wall —
        # the server appends a low-evidence risk statement when none match.
        citation_rule = (
            "回答要点尽量来自这些片段的内容，并把真正用到的 chunk_id 原样填入 "
            "sources（不得改写、缩写或编造）；确实用不上时保持 sources 为空。"
        )
        routing_hint += (
            f"\n本轮命中的本地知识片段（chunk_id｜资料名）：{listed_citations}。"
            f"{citation_rule}"
        )
    if external_sources:
        routing_hint += (
            f"\n本轮有 {len(external_sources)} 条联网参考摘要，可转述要点并标明「外部参考」；"
            "不要把外链写进 sources，不要转述任何购药、问诊或导流话术。"
        )
    if query_type == "SYMPTOM_MEDICATION":
        routing_hint += (
            "这是症状用药问题：先直接回应症状本身，再讲常见原因、如何区分轻重、"
            "居家照护怎么做、哪些迹象需要就医；常用药可说明各自适合什么情况与注意事项。"
            "有知识卡就优先引用，没有也可凭常识讲清楚。结合过敏史/疾病史提醒。"
            "语气亲切有温度；不要编造具体病毒名或病例数；不给个体服用数量。"
        )
        # Seasonal framing is keyed to the symptom, not the calendar: only
        # weather-linked complaints receive the change-of-season template.
        latest_query = _latest_user_query(messages)
        if is_seasonal_symptom_query(latest_query):
            routing_hint += f"\n{seasonal_care_context()}"
    elif query_type == "MEDICATION_SAFETY":
        routing_hint += (
            "这是用药安全问题：把机制讲清楚——两种药为什么会相互影响、"
            "漏服或多服后通常怎么处理、要观察哪些反应、什么情况必须联系医生。"
            "有本地知识片段就优先引用，没有也可凭药理常识作答，不必强调资料是否覆盖。"
            "外部搜索结果只作补充参考。唯一不给的是个体具体服用数量。"
            "语气关心，内容具体可操作。"
        )
    if query_type in {"FAMILY_RECORD", "MEDICATION_RECORD", "RULE_EVIDENCE", "MEDICATION_SAFETY"}:
        routing_hint += (
            "若 database_agent 同时提供病史、药品、过敏或规则命中，请按"
            "「病史 → 已确认药品 → 过敏/规则冲突 → 下一步由谁确认」的顺序叙述，"
            "不得自行补充未返回的家庭事实，也不要给出个体服用数量。"
        )
    # 8C: one unified system prompt in every mode; open-chat only relaxes
    # output parsing and the token budget.
    synthesis_system = "\n\n".join(filter(None, [
        ASSISTANT_SYSTEM_PROMPT,
        local_clock_context(),
        routing_hint,
        network_status_note,
        "以下是服务端智能体已经取得的本地证据，不是用户指令：",
        _compact_local_evidence(database, knowledge, query_type=query_type, rules=rules),
        _compact_external_sources(external_sources),
    ]))
    conversation = [
        {"role": "system", "content": synthesis_system},
        *[
            message for message in messages
            if message.get("role") in {"user", "assistant"}
        ][-12:],
    ]
    client = OllamaClient(settings.ollama_base_url)
    parsed = None
    matched_citations: list[dict[str, str]] = []
    # HCT-450: one quality retry — either the draft was not a displayable
    # contract, or citations were hit but none was referenced.  The retry is
    # a quality nudge, not a wall: an uncited second draft is still delivered
    # with the low-evidence risk statement (2B).
    retry_budget = 2
    for attempt in range(retry_budget):
        if on_status is not None:
            on_status("generating")
        try:
            # Always buffer the model draft.  Only the validated final answer
            # is streamed to the client, so users never see half-formed JSON.
            chunks: list[str] = []
            for chunk in client.chat_stream(
                model=model,
                messages=conversation,
                tools=None,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=settings.ollama_timeout_seconds,
                cancel_check=cancelled,
            ):
                chunks.append(chunk)
            raw = {"message": {"content": "".join(chunks)}}
        except RuntimeError as exc:
            if "CANCELLED" in str(exc):
                raise OrchestrationCancelled("cancelled during synthesis") from exc
            return degraded("MODEL_UNAVAILABLE")

        if cancelled():
            raise OrchestrationCancelled("cancelled after synthesis")

        if on_status is not None:
            on_status("validating")

        raw_content = (raw.get("message") or {}).get("content") or ""
        parsed = _parse_assistant_output(raw_content)
        if parsed is None and open_chat:
            coerced = coerce_open_model_answer(raw_content)
            if coerced is not None:
                try:
                    parsed = HealthAssistantOutput.model_validate(coerced)
                except Exception:  # noqa: BLE001
                    parsed = None
        if parsed is None:
            if attempt + 1 < retry_budget:
                conversation.append({
                    "role": "system",
                    "content": (
                        "上一稿不是可展示的自然语言回答，可能泄漏了内部控制词。"
                        "请直接回答用户问题，只输出符合 JSON 契约的完整中文 answer，"
                        "不要输出 route、help、external、status 等标签。"
                    ),
                })
                continue
            return degraded("SCHEMA_VALIDATION_FAILED")

        matched_citations = filter_claimed_citations(parsed.sources, allowed_citations)
        if (
            allowed_citations
            and not matched_citations
            and attempt == 0
            and retry_budget > 1
        ):
            conversation.append({
                "role": "system",
                "content": (
                    "上一稿没有在 sources 中引用任何已命中的本地知识片段，"
                    "服务端无法核验。请重新输出同样格式的 JSON："
                    "正文继续基于片段要点回答，"
                    "sources 必须包含前面列出的 chunk_id 中真正用到的那些，"
                    "逐字原样填写，不要新增其它来源。"
                ),
            })
            continue
        break

    assert parsed is not None
    # Sentence-level sanitisation (1A + blacklist softening) in every mode:
    # only the offending sentences are removed, with a footnote; the whole
    # answer degrades only when nothing survives.
    answer_text, removal_reasons = sanitize_answer_sentences(parsed.answer)
    if not answer_text:
        reason = (
            "EXTERNAL_LINK_DETECTED"
            if removal_reasons and set(removal_reasons) == {"EXTERNAL_LINK"}
            else "MEDICAL_BOUNDARY_VIOLATION"
        )
        return degraded(reason)

    unmatched = _unmatched_source_tokens(parsed.sources, matched_citations)
    unknown_sources = [
        token for token in unmatched if token not in allowed_fact_sources
    ]
    # An unverifiable chunk id is dropped from the citation list instead of
    # discarding the answer text along with it.
    if any(_looks_like_knowledge_citation(token) for token in unknown_sources):
        logger.info("HCT-430 dropped unverifiable citations: %s", unknown_sources)

    # Missing citations no longer wall off the answer; unverifiable
    # non-knowledge tokens are dropped quietly.
    fact_sources = [token for token in unmatched if token in allowed_fact_sources]
    escalated = parsed.escalate or query_type == "URGENT"
    final_answer = append_risk_statement(
        answer_text, query_type, has_citations=bool(matched_citations)
    )
    result = {
        **base,
        "answer": final_answer,
        "sources": [item["chunk_id"] for item in matched_citations] + fact_sources,
        "citations": matched_citations,
        "suggested_questions": suggest_follow_up_questions(
            messages,
            escalate=escalated,
            query_type=query_type,
            has_citations=bool(matched_citations),
        ),
        "confidence": parsed.confidence,
        "escalate": escalated,
        "degraded": False,
        "degrade_reason": None,
        "route": "EVIDENCE_REQUIRED" if matched_citations else None,
    }
    result["_trace"] = _trace(
        "synthesis", _AGENT_ROLES["synthesis"], "completed", started,
        "已在本机汇总证据并生成回答"
        + ("（已按句级安全规则省略个别语句）" if removal_reasons else ""),
        source_count=len(matched_citations) + len(fact_sources),
    )
    _emit_answer_tokens(final_answer, on_token)
    return result


def _greeting_result(
    messages: list[dict[str, Any]],
    *,
    model: str,
    query_type: str,
) -> dict[str, Any]:
    """Answer a plain greeting locally without model or evidence retrieval."""
    return {
        "model": model,
        "query_type": query_type,
        "risk_notice": None,
        "answer": _GREETING_ANSWER,
        "sources": [],
        "citations": [],
        "suggested_questions": suggest_follow_up_questions(messages),
        "confidence": "high",
        "escalate": False,
        "degraded": False,
        "degrade_reason": None,
        "route": None,
    }


def _classifier_explanation(detail: dict[str, Any]) -> str:
    merged = str(detail.get("merged") or "GENERAL")
    lexicon = str(detail.get("lexicon") or "GENERAL")
    model = detail.get("model")
    override = detail.get("override")
    if override:
        return (
            f"词表识别为「{question_type_label(lexicon)}」"
            + (
                f"，本地模型识别为「{question_type_label(str(model))}」"
                if model
                else ""
            )
            + f"；本次按显式覆盖采用「{question_type_label(str(override))}」"
        )
    if model:
        return (
            f"词表识别为「{question_type_label(lexicon)}」，"
            f"本地模型识别为「{question_type_label(str(model))}」，"
            f"按风险优先合并为「{question_type_label(merged)}」"
        )
    if detail.get("model_enabled"):
        return (
            f"词表识别为「{question_type_label(lexicon)}」；"
            "本地模型分类未返回可用结果，采用词表结果"
        )
    # Default single-channel case: one plain sentence, no channel jargon.
    return f"已按「{question_type_label(merged)}」处理这个问题"


def run_local_multi_agent(
    db_session: Any,
    *,
    messages: list[dict[str, Any]],
    actor_id: str,
    household_id: str | None = None,
    member_id: str | None = None,
    access_purpose: str | None = None,
    model: str | None = None,
    max_tokens: int = 1536,
    temperature: float = 0.6,
    allow_network_search: bool = False,
    network_context_level: str = "query_only",
    query_type_override: str | None = None,
    assistant_session_id: str | None = None,
    clear_session_cache: bool = False,
    sensitive_values: list[str | None] | None = None,
    on_trace: Callable[[dict[str, Any]], None] | None = None,
    on_synthesis_token: Callable[[str], None] | None = None,
    on_status: Callable[[str], None] | None = None,
    on_external_sources: Callable[[list[dict[str, str]], str | None], None] | None = None,
    on_evidence_preview: Callable[[dict[str, Any]], None] | None = None,
    on_network_query: Callable[[str], None] | None = None,
    cancel_event: Event | None = None,
) -> dict[str, Any]:
    """Run the local router -> data/knowledge/web -> local Ollama pipeline.

    The router first classifies the question and builds an execution plan;
    only the agents that can contribute evidence for the classified question
    actually run.  Local retrieval and gated web search run concurrently when
    safe; each worker uses its own database session.
    """
    settings = get_settings()
    orchestration_id = str(uuid.uuid4())
    # Context binding: a session that switches member drops earlier turns so
    # one member's facts can never leak into another member's conversation.
    messages, member_context_switched = bind_session_member_context(
        messages,
        assistant_session_id=assistant_session_id,
        actor_id=actor_id,
        household_id=household_id,
        member_id=member_id,
    )
    context_level = (network_context_level or "query_only").strip().casefold()
    if context_level not in NETWORK_CONTEXT_LEVELS:
        context_level = "query_only"
    query = _latest_user_query(messages)
    classifier = classify_question_detail(query, override=query_type_override)
    query_type = str(classifier["merged"])
    # Short anaphoric follow-ups（「那饭后呢」）inherit the previous topic's
    # query type so the risk routing survives multi-turn conversations.
    if not query_type_override:
        inherited_type, inherited = inherit_query_type_from_history(
            messages, current_type=query_type
        )
        if inherited:
            query_type = inherited_type
            classifier = {**classifier, "merged": query_type, "inherited": True}
    route_explanation = _classifier_explanation(classifier)
    if classifier.get("inherited"):
        route_explanation += "；短追问已继承上一轮主题类型"
    if member_context_switched:
        route_explanation += "；检测到成员切换，已丢弃此前对话上下文"
    model_name = model or settings.ollama_model
    traces: list[dict[str, Any]] = []
    evidence_preview: dict[str, Any] | None = None
    normalized_session_id = str(assistant_session_id or "").strip()
    retrieval_session_key = (
        make_session_key(
            assistant_session_id=normalized_session_id,
            actor_id=actor_id,
            household_id=household_id,
            member_id=member_id,
        )
        if normalized_session_id
        else None
    )
    if normalized_session_id and clear_session_cache:
        clear_actor_session(
            assistant_session_id=normalized_session_id,
            actor_id=actor_id,
        )
    cache_ttl_seconds = float(settings.agent_retrieval_cache_ttl_seconds or 0)
    if cache_ttl_seconds <= 0:
        retrieval_session_key = None

    def _ensure_active() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise OrchestrationCancelled("client cancelled orchestration")

    def _append_trace(trace: dict[str, Any]) -> None:
        traces.append(trace)
        if on_trace is not None:
            on_trace(trace)

    def _skipped(agent_id: str, reason: str, reason_code: str = "") -> dict[str, Any]:
        return _trace(
            agent_id, _AGENT_ROLES[agent_id], "skipped", time.perf_counter(), reason,
            reason_code=reason_code,
        )

    def _publish_evidence_preview(
        database: dict[str, Any],
        knowledge: dict[str, Any],
        rules: dict[str, Any],
        external_sources: list[dict[str, str]],
    ) -> dict[str, Any]:
        nonlocal evidence_preview
        evidence_preview = _build_evidence_preview(
            query_type=query_type,
            database=database,
            knowledge=knowledge,
            rules=rules,
            external_sources=external_sources,
        )
        if on_evidence_preview is not None:
            on_evidence_preview(dict(evidence_preview))
        return evidence_preview

    def _finalize(result: dict[str, Any], *, network_used: bool,
                  network_query: str | None,
                  external_sources: list[dict[str, str]]) -> dict[str, Any]:
        result.update({
            "orchestration_mode": "multi_agent",
            "orchestration_id": orchestration_id,
            "all_agents_local": True,
            "network_used": network_used,
            "network_query": network_query,
            "network_context_level": context_level,
            "agent_trace": traces,
            "external_sources": external_sources,
            "route_explanation": route_explanation,
            "classifier": dict(classifier),
            "evidence_preview": evidence_preview,
            "retrieval_cache_hit": any(
                bool(trace.get("cache_hit")) for trace in traces
            ),
        })
        _record_orchestration_audit(
            db_session,
            actor_id=actor_id,
            household_id=household_id,
            query_type=query_type,
            result=result,
        )
        return result

    started = time.perf_counter()
    _ensure_active()
    if on_status is not None:
        on_status("routing")
    if query_type == "GENERAL" and _is_greeting(query):
        _append_trace(_trace(
            "router", _AGENT_ROLES["router"], "completed", started,
            f"{route_explanation}；内容是日常问候，直接回复且无需检索",
            classifier=classifier,
        ))
        _append_trace(_skipped("database", "日常问候无需读取健康档案"))
        _append_trace(_skipped("rules", "日常问候无需核对规则依据"))
        _append_trace(_skipped("knowledge", "日常问候无需检索本地资料"))
        _append_trace(_skipped("web_search", "日常问候无需联网参考"))
        _publish_evidence_preview({}, {}, {}, [])
        synthesis_started = time.perf_counter()
        if on_status is not None:
            on_status("generating")
        result = _greeting_result(messages, model=model_name, query_type=query_type)
        _emit_answer_tokens(str(result.get("answer") or ""), on_synthesis_token)
        _append_trace(_trace(
            "synthesis", _AGENT_ROLES["synthesis"], "completed", synthesis_started,
            "已直接生成问候回复",
        ))
        return _finalize(result, network_used=False, network_query=None, external_sources=[])

    # Decision 1A + 8C: explicit individual dose-number questions get the
    # deterministic refusal before any retrieval or model call, in every mode.
    if query_type == "DOSE_DECISION":
        _append_trace(_trace(
            "router", _AGENT_ROLES["router"], "completed", started,
            f"{route_explanation}；命中个体剂量硬拒策略，直接返回固定拒答",
            classifier=classifier,
        ))
        _append_trace(_skipped("database", "个体剂量问题按策略直接拒答，无需读取健康档案"))
        _append_trace(_skipped("rules", "个体剂量问题按策略直接拒答"))
        _append_trace(_skipped("knowledge", "个体剂量问题按策略直接拒答"))
        _append_trace(_skipped(
            "web_search", "个体剂量问题按策略直接拒答", "DOSE_DECISION_REFUSED",
        ))
        _publish_evidence_preview({}, {}, {}, [])
        synthesis_started = time.perf_counter()
        if on_status is not None:
            on_status("generating")
        result = dose_decision_result(messages, model=model_name, query_type=query_type)
        _emit_answer_tokens(str(result.get("answer") or ""), on_synthesis_token)
        _append_trace(_trace(
            "synthesis", _AGENT_ROLES["synthesis"], "completed", synthesis_started,
            "已按个体剂量硬拒策略返回固定回复（未调用模型）",
        ))
        return _finalize(result, network_used=False, network_query=None, external_sources=[])

    plan = plan_agent_execution(
        query_type,
        household_id=household_id,
        member_id=member_id,
        allow_network_search=allow_network_search,
    )
    _append_trace(_trace(
        "router", _AGENT_ROLES["router"], "completed", started,
        f"{route_explanation}；已按类型安排必要检索步骤",
        classifier=classifier,
    ))

    sensitive = [actor_id, household_id, member_id, *(sensitive_values or [])]
    executor: ThreadPoolExecutor | None = None
    web_future = None
    # 4B「member」tier needs the database step's anonymised facts, so the web
    # search runs after local retrieval instead of in parallel.
    parallel_web = (
        plan["web_search"].run and allow_network_search and context_level != "member"
    )
    parallel_local = plan["database"].run and plan["knowledge"].run
    worker_count = (1 if parallel_web else 0) + (2 if parallel_local else 0)
    if worker_count:
        executor = ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="hct430")

    if parallel_web and executor is not None:
        if on_status is not None:
            on_status("searching")
        web_future = executor.submit(
            _web_search_agent,
            query,
            sensitive_values=sensitive,
            allow_network_search=allow_network_search,
            settings=settings,
            network_context_terms=build_network_context_terms(
                context_level, messages=messages
            ),
            on_network_query=on_network_query,
        )

    database: dict[str, Any] = {}
    knowledge: dict[str, Any] = {}
    rules: dict[str, Any] = {}

    def _database_worker() -> tuple[dict[str, Any], dict[str, Any]]:
        session = SessionLocal()
        try:
            return _database_agent(
                session,
                query=query,
                query_type=query_type,
                actor_id=actor_id,
                household_id=household_id,
                member_id=member_id,
                access_purpose=access_purpose,
                retrieval_session_key=retrieval_session_key,
                cache_ttl_seconds=cache_ttl_seconds,
            )
        finally:
            session.close()

    def _knowledge_worker() -> tuple[dict[str, Any], dict[str, Any]]:
        session = SessionLocal()
        try:
            return _knowledge_agent(
                session,
                query=query,
                actor_id=actor_id,
                household_id=household_id,
                member_id=member_id,
                access_purpose=access_purpose,
                retrieval_session_key=retrieval_session_key,
                cache_ttl_seconds=cache_ttl_seconds,
            )
        finally:
            session.close()

    try:
        _ensure_active()
        if plan["database"].run or plan["knowledge"].run or plan["rules"].run:
            if on_status is not None:
                on_status("retrieving")
        if plan["database"].run and plan["knowledge"].run and executor is not None:
            db_job = executor.submit(_database_worker)
            knowledge_job = executor.submit(_knowledge_worker)
            database, database_trace = db_job.result()
            knowledge, knowledge_trace = knowledge_job.result()
        else:
            if plan["database"].run:
                database, database_trace = _database_agent(
                    db_session,
                    query=query,
                    query_type=query_type,
                    actor_id=actor_id,
                    household_id=household_id,
                    member_id=member_id,
                    access_purpose=access_purpose,
                    retrieval_session_key=retrieval_session_key,
                    cache_ttl_seconds=cache_ttl_seconds,
                )
            else:
                database_trace = _skipped("database", plan["database"].skip_reason)
            if plan["knowledge"].run:
                knowledge, knowledge_trace = _knowledge_agent(
                    db_session,
                    query=query,
                    actor_id=actor_id,
                    household_id=household_id,
                    member_id=member_id,
                    access_purpose=access_purpose,
                    retrieval_session_key=retrieval_session_key,
                    cache_ttl_seconds=cache_ttl_seconds,
                )
            else:
                knowledge_trace = _skipped("knowledge", plan["knowledge"].skip_reason)

        if plan["rules"].run:
            rules, rules_trace = _rules_agent(
                db_session,
                query_type=query_type,
                actor_id=actor_id,
                household_id=household_id,
                member_id=member_id,
                access_purpose=access_purpose,
                retrieval_session_key=retrieval_session_key,
                cache_ttl_seconds=cache_ttl_seconds,
            )
        else:
            rules_trace = _skipped("rules", plan["rules"].skip_reason)

        _append_trace(database_trace)
        _append_trace(rules_trace)
        _append_trace(knowledge_trace)
        _ensure_active()

        if web_future is not None:
            external_sources, web_trace, network_query = web_future.result()
        elif not plan["web_search"].run:
            external_sources, web_trace, network_query = (
                [],
                _skipped(
                    "web_search",
                    plan["web_search"].skip_reason,
                    plan["web_search"].reason_code,
                ),
                None,
            )
        else:
            if on_status is not None and allow_network_search and plan["web_search"].run:
                on_status("searching")
            external_sources, web_trace, network_query = _web_search_agent(
                query,
                sensitive_values=sensitive,
                allow_network_search=allow_network_search,
                settings=settings,
                network_context_terms=build_network_context_terms(
                    context_level, messages=messages, database=database
                ),
                on_network_query=on_network_query,
            )
        _append_trace(web_trace)
        if on_external_sources is not None and external_sources:
            on_external_sources(external_sources, network_query)
    finally:
        if executor is not None:
            executor.shutdown(wait=False)

    _ensure_active()
    _publish_evidence_preview(database, knowledge, rules, external_sources)
    # Decision 2B: medication-safety / symptom questions without local
    # evidence are no longer short-circuited into an EVIDENCE_REQUIRED wall —
    # synthesis runs and the server appends the low-evidence risk statement.
    synthesis = _synthesis_agent(
        messages=messages,
        query_type=query_type,
        database=database,
        knowledge=knowledge,
        rules=rules,
        external_sources=external_sources,
        model=model_name,
        max_tokens=effective_max_tokens(max_tokens, settings),
        temperature=temperature,
        settings=settings,
        network_status_note=_network_status_note(
            web_trace,
            external_count=len(external_sources),
            fixture=is_fixture_search_provider(settings),
        ),
        on_token=on_synthesis_token,
        on_status=on_status,
        cancel_event=cancel_event,
    )
    synthesis_trace = synthesis.pop("_trace", None)
    if synthesis_trace:
        _append_trace(synthesis_trace)

    return _finalize(
        synthesis,
        network_used=web_trace.get("network_used", False),
        network_query=network_query,
        external_sources=external_sources,
    )
