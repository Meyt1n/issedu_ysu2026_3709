"""
HCT-403: Ollama tool calling, structured output, and safe degradation.

Design
------
* Tool whitelist — only approved read-only endpoints are callable by the model.
* Parameter schema validation — every tool call is validated against a JSON Schema.
* Context authorisation — tool params must not cross household / member boundaries.
* Structured output — Ollama response is validated against a Pydantic schema.
* Medical boundary — output is checked for prohibited content (diagnosis,
  prescription, dosage decisions, purchasing / referral links).
* Timeout & retry — configurable per-request timeout with exponential backoff.
* Structured degrade — if Ollama is unreachable or output fails validation,
  fall back to rule-card / static evidence summary.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────

OLLAMA_DEFAULT_URL = "http://localhost:11434"
REQUEST_TIMEOUT = 30.0
MAX_RETRIES = 2
RETRY_BACKOFF = 2.0
MAX_TOOL_ROUNDS = 3

# Medical boundary keywords that must never appear in output
_MEDICAL_PROHIBITIONS: list[str] = [
    "诊断", "确诊", "处方", "给药", "建议停药", "建议换药",
    "诊断:", "Diagnosis:", "Prescription:", "你应当", "你必须",
    "buy", "purchase", "order", "点击购买", "咨询电话", "添加微信",
]

# Default degrade template when model is unavailable
_DEGRADE_TEMPLATE = """当前助手服务暂时不可用。您可以：

1. 查阅已保存的健康事件记录
2. 查看规则引擎生成的提醒
3. 确认或修正已扫描的健康事件

如有紧急情况请及时联系医务人员。"""


# ── Tool Schema ────────────────────────────────────────────────────────


class ToolParamSchema(BaseModel):
    """JSON Schema subset for a single tool parameter."""
    type: str
    description: str
    enum: list[str] | None = None
    default: Any = None


class ToolDefinition(BaseModel):
    """Definition of an approved, model-callable tool."""
    name: str
    description: str
    params: dict[str, ToolParamSchema] = Field(default_factory=dict)

    def validate_args(self, args: dict[str, Any]) -> dict[str, Any]:
        """Validate and coerce tool arguments."""
        validated: dict[str, Any] = {}
        for key, schema in self.params.items():
            value = args.get(key, schema.default)
            if value is None:
                if schema.type not in ("object", "array", "string"):
                    continue
            if schema.enum and value not in schema.enum:
                raise ValueError(f"Invalid enum value for {key}: {value}")
            validated[key] = value
        return validated


# ── Output Schemas ─────────────────────────────────────────────────────


class HealthAssistantOutput(BaseModel):
    """Structured output schema for the health assistant."""
    answer: str = Field(description="Natural language response to the user")
    sources: list[str] = Field(default_factory=list, description="Referenced source IDs")
    confidence: str = Field(default="low", description="high | medium | low")
    escalate: bool = Field(default=False, description="Whether to escalate to a human")


class ToolCallRequest(BaseModel):
    """Single tool call in an assistant message."""
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class HealthAssistantMessage(BaseModel):
    role: str
    content: str | None = None
    tool_calls: list[ToolCallRequest] | None = None


class HealthAssistantRequest(BaseModel):
    """Full request to the local assistant."""
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] = Field(default_factory=list)
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(default=512, ge=1, le=4096)


# ── Tool Registry ──────────────────────────────────────────────────────

_WHITELISTED_TOOLS: dict[str, ToolDefinition] = {}


def register_tool(name: str, description: str,
                  params: dict[str, dict[str, Any]] | None = None) -> None:
    """Register an approved tool. Call at module import time."""
    schema_params = {}
    if params:
        for key, val in params.items():
            schema_params[key] = ToolParamSchema(**val)
    _WHITELISTED_TOOLS[name] = ToolDefinition(
        name=name, description=description, params=schema_params,
    )


def get_approved_tools() -> list[ToolDefinition]:
    return list(_WHITELISTED_TOOLS.values())


def is_tool_allowed(name: str) -> bool:
    return name in _WHITELISTED_TOOLS


def get_tool(name: str) -> ToolDefinition:
    if name not in _WHITELISTED_TOOLS:
        raise ValueError(f"Tool '{name}' is not in the approved whitelist")
    return _WHITELISTED_TOOLS[name]


# ── Register read-only knowledge / rule tools ──────────────────────────

register_tool(
    name="retrieve_knowledge",
    description="Search approved local knowledge documents (drug inserts, care guidelines).",
    params={
        "query": {"type": "string", "description": "Search query in Chinese or English"},
        "household_id": {"type": "string", "description": "Optional household filter"},
        "member_id": {"type": "string", "description": "Optional member filter"},
        "top_k": {"type": "integer", "description": "Number of results (1-10)", "default": 5},
    },
)

register_tool(
    name="get_health_events",
    description="Retrieve health events for a household member (read-only).",
    params={
        "household_id": {"type": "string", "description": "Household UUID"},
        "member_id": {"type": "string", "description": "Member UUID"},
        "event_type": {"type": "string", "description": "Optional event type filter"},
    },
)

register_tool(
    name="get_member_state",
    description="Get the current state projection for a member (read-only).",
    params={
        "household_id": {"type": "string", "description": "Household UUID"},
        "member_id": {"type": "string", "description": "Member UUID"},
    },
)

register_tool(
    name="get_applied_rules",
    description="Get currently active rule IDs and their severity levels.",
    params={
        "household_id": {"type": "string", "description": "Household UUID"},
        "member_id": {"type": "string", "description": "Member UUID"},
    },
)

register_tool(
    name="get_risk_alerts",
    description="Get risk alerts for a household member (read-only).",
    params={
        "household_id": {"type": "string", "description": "Household UUID"},
        "member_id": {"type": "string", "description": "Member UUID"},
    },
)

register_tool(
    name="get_document_metadata",
    description="Get metadata for a specific knowledge document.",
    params={
        "document_id": {"type": "string", "description": "Knowledge document UUID"},
    },
)


# ── Ollama Client ──────────────────────────────────────────────────────


class OllamaClient:
    """Thin async wrapper around Ollama's HTTP API."""

    def __init__(self, base_url: str = OLLAMA_DEFAULT_URL):
        self.base_url = base_url.rstrip("/")
        self._available: bool | None = None  # cached health status

    def health_check(self) -> bool:
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                resp = client.get(f"{self.base_url}/api/tags")
                self._available = resp.status_code == 200
                return self._available
        except Exception:
            self._available = False
            return False

    def is_available(self) -> bool:
        if self._available is None:
            return self.health_check()
        return self._available

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
        max_tokens: int = 512,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Send a chat completion request to Ollama."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if tools:
            payload["tools"] = tools

        last_error: str | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                with httpx.Client(timeout=timeout or REQUEST_TIMEOUT) as client:
                    resp = client.post(f"{self.base_url}/api/chat", json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    self._available = True
                    return data
            except httpx.TimeoutException:
                last_error = "TIMEOUT"
                logger.warning("Ollama request timed out (attempt %d)", attempt + 1)
            except httpx.HTTPStatusError as exc:
                last_error = f"HTTP_{exc.response.status_code}"
                logger.warning(
                    "Ollama HTTP error %s (attempt %d)",
                    exc.response.status_code, attempt + 1,
                )
            except Exception as exc:
                last_error = str(exc)[:120]
                logger.warning("Ollama connection error (attempt %d): %s", attempt + 1, exc)

            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF ** attempt)

        logger.error("Ollama failed after %d attempts: %s", MAX_RETRIES + 1, last_error)
        raise RuntimeError(f"OLLAMA_UNAVAILABLE: {last_error}")


# ── Medical safety check ───────────────────────────────────────────────


def _check_medical_boundary(output_text: str) -> list[str]:
    violations = []
    for keyword in _MEDICAL_PROHIBITIONS:
        if keyword.lower() in output_text.lower():
            violations.append(keyword)
    return violations


def _contains_external_links(output_text: str) -> bool:
    """Detect external URLs that could be used for referral / advertising."""
    import re
    url_pattern = re.compile(r'https?://[^\s<"\']+', re.IGNORECASE)
    return bool(url_pattern.search(output_text))


# ── Structured degrade ────────────────────────────────────────────────


@dataclass
class DegradedResponse:
    answer: str
    degraded: bool = True
    reason: str = "MODEL_UNAVAILABLE"
    sources: list[str] = field(default_factory=list)
    escalate: bool = False


def build_degrade_response(
    reason: str = "MODEL_UNAVAILABLE",
    *,
    household_id: str | None = None,
) -> DegradedResponse:
    """Build a structured degrade response."""
    if reason == "MEDICAL_BOUNDARY_VIOLATION":
        return DegradedResponse(
            answer="抱歉，我无法提供具体医疗建议。如有紧急情况请及时联系医务人员。",
            degraded=True,
            reason=reason,
            escalate=True,
        )
    if reason == "SCHEMA_VALIDATION_FAILED":
        return DegradedResponse(
            answer="系统暂时无法处理您的请求，请稍后再试或联系照护者。",
            degraded=True,
            reason=reason,
        )
    if reason == "NO_AUTHORISED_DOCUMENTS":
        return DegradedResponse(
            answer="当前范围内没有可引用的授权知识证据，助手不能编造来源。",
            degraded=True,
            reason=reason,
        )
    if reason in {"CITATION_NOT_FOUND", "EVIDENCE_REQUIRED"}:
        return DegradedResponse(
            answer="当前回答缺少可核验的本地知识引用，请查阅已确认记录或联系照护者。",
            degraded=True,
            reason=reason,
        )
    if reason == "TOOL_SCOPE_DENIED":
        return DegradedResponse(
            answer="助手工具请求超出当前家庭或成员范围，已拒绝执行。",
            degraded=True,
            reason=reason,
        )
    return DegradedResponse(
        answer=_DEGRADE_TEMPLATE,
        degraded=True,
        reason=reason,
    )


_EVIDENCE_DEGRADE_REASONS = {
    "EVIDENCE_REQUIRED",
    "CITATION_NOT_FOUND",
    "NO_AUTHORISED_DOCUMENTS",
}


def _degrade_payload(response: DegradedResponse) -> dict[str, Any]:
    """Translate the internal degrade record to the public API contract."""
    return {
        "answer": response.answer,
        "sources": response.sources,
        "citations": [],
        "confidence": "low",
        "escalate": response.escalate,
        "degraded": response.degraded,
        "degrade_reason": response.reason,
        "route": (
            "EVIDENCE_REQUIRED"
            if response.reason in _EVIDENCE_DEGRADE_REASONS
            else "REFUSE"
        ),
    }


# ── Tool execution and citation binding ────────────────────────────────


def _parse_tool_arguments(raw_args: Any) -> dict[str, Any]:
    if raw_args is None:
        return {}
    if isinstance(raw_args, dict):
        return raw_args
    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def extract_tool_calls(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize Ollama/OpenAI-style tool calls to {name, arguments}."""
    message = raw.get("message") or {}
    calls = message.get("tool_calls") or []
    normalized: list[dict[str, Any]] = []
    for call in calls:
        function = call.get("function") if isinstance(call, dict) else None
        if isinstance(function, dict):
            name = function.get("name")
            arguments = _parse_tool_arguments(function.get("arguments"))
        elif isinstance(call, dict):
            name = call.get("name")
            arguments = _parse_tool_arguments(call.get("arguments"))
        else:
            continue
        if not name:
            continue
        normalized.append({"name": str(name), "arguments": arguments})
    return normalized


def _bound_scope_value(
    requested: Any,
    bound: str | None,
) -> tuple[str | None, str | None]:
    if requested in (None, ""):
        return bound, None
    requested_text = str(requested)
    if bound and requested_text != bound:
        return bound, "TOOL_SCOPE_DENIED"
    return requested_text, None


def _citation_from_chunk(chunk: dict[str, Any]) -> dict[str, str]:
    return {
        "document_id": str(chunk["document_id"]),
        "version": str(chunk.get("version") or ""),
        "chunk_id": str(chunk["chunk_id"]),
    }


def _index_allowed_citations(
    allowed: list[dict[str, str]],
) -> dict[str, dict[str, str]]:
    indexed: dict[str, dict[str, str]] = {}
    for citation in allowed:
        indexed[citation["chunk_id"]] = citation
        indexed[citation["document_id"]] = citation
        indexed[f"{citation['document_id']}:{citation['chunk_id']}"] = citation
    return indexed


def filter_claimed_citations(
    claimed_sources: list[str],
    allowed: list[dict[str, str]],
) -> list[dict[str, str]]:
    indexed = _index_allowed_citations(allowed)
    matched: list[dict[str, str]] = []
    seen: set[str] = set()
    for token in claimed_sources:
        citation = indexed.get(str(token).strip())
        if citation is None or citation["chunk_id"] in seen:
            continue
        seen.add(citation["chunk_id"])
        matched.append(citation)
    return matched


def _execute_retrieve_knowledge(
    session: Session,
    *,
    actor_id: str,
    household_id: str | None,
    member_id: str | None,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    from app.knowledge import log_query, retrieve

    bound_household, household_error = _bound_scope_value(
        arguments.get("household_id"), household_id
    )
    bound_member, member_error = _bound_scope_value(
        arguments.get("member_id"), member_id
    )
    if household_error or member_error:
        return {"error": "TOOL_SCOPE_DENIED", "results": [], "total": 0}

    query = str(arguments.get("query") or "").strip()
    try:
        top_k = int(arguments.get("top_k") or 5)
    except (TypeError, ValueError):
        top_k = 5
    top_k = max(1, min(top_k, 10))
    try:
        results = retrieve(
            session,
            query=query,
            actor_id=actor_id,
            household_id=bound_household,
            member_id=bound_member,
            top_k=top_k,
        )
        log_query(
            session,
            query_text=query,
            actor_id=actor_id,
            household_id=bound_household,
            member_id=bound_member,
            top_chunk_ids=[item["chunk_id"] for item in results],
            returned_count=len(results),
        )
        public_results = [
            {
                "chunk_id": item["chunk_id"],
                "document_id": item["document_id"],
                "title": item["title"],
                "version": item["version"],
                "locator": item.get("locator"),
                "text": item["text"],
                "score": item["score"],
            }
            for item in results
        ]
        return {"results": public_results, "total": len(public_results)}
    except ValueError as exc:
        return {
            "error": str(exc),
            "results": [],
            "total": 0,
            "degraded": True,
            "degrade_reason": str(exc),
        }


def _execute_get_document_metadata(
    session: Session,
    *,
    actor_id: str,
    household_id: str | None,
    member_id: str | None,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    from app.knowledge import KnowledgeDocument, _check_permission

    document_id = str(arguments.get("document_id") or "").strip()
    if not document_id:
        return {"error": "DOCUMENT_NOT_FOUND"}
    document = session.get(KnowledgeDocument, document_id)
    if document is None or document.status != "active":
        return {"error": "DOCUMENT_NOT_FOUND"}
    if not _check_permission(
        document.permission_scope or {},
        actor_id,
        household_id,
        member_id,
    ):
        return {"error": "DOCUMENT_NOT_FOUND"}
    return {
        "document_id": document.id,
        "title": document.title,
        "version": document.version,
        "source": document.source,
        "status": document.status,
    }


def execute_whitelisted_tool(
    session: Session | None,
    *,
    name: str,
    arguments: dict[str, Any],
    actor_id: str,
    household_id: str | None,
    member_id: str | None,
) -> dict[str, Any]:
    if not is_tool_allowed(name):
        return {"error": "TOOL_NOT_ALLOWED"}
    tool = get_tool(name)
    try:
        validated = tool.validate_args(arguments)
    except ValueError as exc:
        return {"error": str(exc)}
    if session is None:
        return {"error": "TOOL_SESSION_REQUIRED"}
    if name == "retrieve_knowledge":
        return _execute_retrieve_knowledge(
            session,
            actor_id=actor_id,
            household_id=household_id,
            member_id=member_id,
            arguments=validated,
        )
    if name == "get_document_metadata":
        return _execute_get_document_metadata(
            session,
            actor_id=actor_id,
            household_id=household_id,
            member_id=member_id,
            arguments=validated,
        )
    return {"error": "TOOL_NOT_BOUND"}


def _parse_assistant_output(raw_content: str) -> HealthAssistantOutput | None:
    if not raw_content or not str(raw_content).strip():
        return None
    try:
        return HealthAssistantOutput.model_validate_json(raw_content)
    except (ValidationError, json.JSONDecodeError):
        try:
            return _parse_loose_output(raw_content)
        except Exception:
            return None


def run_assistant(
    db_session,
    *,
    messages: list[dict[str, Any]],
    actor_id: str,
    household_id: str | None = None,
    member_id: str | None = None,
    model: str = "llama3.2:3b",
    max_tokens: int = 512,
    temperature: float = 0.3,
) -> dict[str, Any]:
    """Run the health assistant with tool calling and citation checks.

    Returns a dict with:
        answer, sources, citations, confidence, escalate, degraded,
        degrade_reason, route
    """
    client = OllamaClient()
    approved_tools = [tool.model_dump() for tool in get_approved_tools()]
    conversation = list(messages)
    request = HealthAssistantRequest(
        messages=conversation,
        tools=approved_tools,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    allowed_citations: list[dict[str, str]] = []
    tool_errors: list[str] = []

    parsed: HealthAssistantOutput | None = None
    for _round in range(MAX_TOOL_ROUNDS + 1):
        try:
            raw = client.chat(
                model=model,
                messages=conversation,
                tools=request.tools if request.tools else None,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            )
        except RuntimeError:
            return _degrade_payload(build_degrade_response("MODEL_UNAVAILABLE"))

        tool_calls = extract_tool_calls(raw)
        raw_content = (raw.get("message") or {}).get("content") or ""
        if tool_calls:
            conversation.append(
                {
                    "role": "assistant",
                    "content": raw_content or None,
                    "tool_calls": tool_calls,
                }
            )
            for call in tool_calls:
                result = execute_whitelisted_tool(
                    db_session,
                    name=call["name"],
                    arguments=call["arguments"],
                    actor_id=actor_id,
                    household_id=household_id,
                    member_id=member_id,
                )
                if result.get("error"):
                    tool_errors.append(str(result["error"]))
                for chunk in result.get("results") or []:
                    allowed_citations.append(_citation_from_chunk(chunk))
                conversation.append(
                    {
                        "role": "tool",
                        "name": call["name"],
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
            continue

        parsed = _parse_assistant_output(raw_content)
        if parsed is None:
            return _degrade_payload(build_degrade_response("SCHEMA_VALIDATION_FAILED"))
        break
    else:
        return _degrade_payload(build_degrade_response("SCHEMA_VALIDATION_FAILED"))

    assert parsed is not None
    violations = _check_medical_boundary(parsed.answer)
    if violations:
        logger.warning("Medical boundary violation: %s", violations)
        return _degrade_payload(build_degrade_response("MEDICAL_BOUNDARY_VIOLATION"))
    if _contains_external_links(parsed.answer):
        logger.warning("External link detected in assistant output")
        return _degrade_payload(build_degrade_response("EXTERNAL_LINK_DETECTED"))

    if "TOOL_SCOPE_DENIED" in tool_errors:
        return _degrade_payload(build_degrade_response("TOOL_SCOPE_DENIED"))
    if "NO_AUTHORISED_DOCUMENTS" in tool_errors and not allowed_citations:
        return _degrade_payload(build_degrade_response("NO_AUTHORISED_DOCUMENTS"))

    matched_citations = filter_claimed_citations(parsed.sources, allowed_citations)
    if parsed.sources and not matched_citations:
        return _degrade_payload(build_degrade_response("CITATION_NOT_FOUND"))
    if not matched_citations:
        return _degrade_payload(build_degrade_response("EVIDENCE_REQUIRED"))

    return {
        "answer": parsed.answer,
        "sources": [item["chunk_id"] for item in matched_citations],
        "citations": matched_citations,
        "confidence": parsed.confidence,
        "escalate": parsed.escalate,
        "degraded": False,
        "degrade_reason": None,
        "route": "EVIDENCE_REQUIRED",
    }


def _parse_loose_output(text: str) -> HealthAssistantOutput:
    """Best-effort parse of non-JSON model output."""
    # Try to extract answer field
    import re
    answer_match = re.search(r'"answer"\s*:\s*"([^"]*)"', text)
    confidence_match = re.search(r'"confidence"\s*:\s*"(\w+)"', text)
    sources_match = re.search(r'"sources"\s*:\s*\[([^\]]*)\]', text)
    escalate_match = re.search(r'"escalate"\s*:\s*(true|false)', text)

    answer = answer_match.group(1) if answer_match else text[:500]
    confidence = confidence_match.group(1) if confidence_match else "low"
    sources = []
    if sources_match:
        raw_srcs = sources_match.group(1)
        sources = [s.strip().strip('"') for s in raw_srcs.split(",") if s.strip()]
    escalate = bool(escalate_match and escalate_match.group(1).lower() == "true")

    return HealthAssistantOutput(
        answer=answer,
        sources=sources,
        confidence=confidence,
        escalate=escalate,
    )
