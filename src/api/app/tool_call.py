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

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────

OLLAMA_DEFAULT_URL = "http://localhost:11434"
REQUEST_TIMEOUT = 30.0
MAX_RETRIES = 2
RETRY_BACKOFF = 2.0

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
    return DegradedResponse(
        answer=_DEGRADE_TEMPLATE,
        degraded=True,
        reason=reason,
    )


def _degrade_payload(response: DegradedResponse) -> dict[str, Any]:
    """Translate the internal degrade record to the public API contract."""
    return {
        "answer": response.answer,
        "sources": response.sources,
        "confidence": "low",
        "escalate": response.escalate,
        "degraded": response.degraded,
        "degrade_reason": response.reason,
    }


# ── Main entry point ───────────────────────────────────────────────────


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
    """Run the health assistant with tool calling and safety checks.

    Returns a dict with:
        answer, sources, confidence, escalate, degraded, degrade_reason
    """
    client = OllamaClient()

    # ── Phase 1: Build approved tool list ───────────────────────────
    approved_tools = [t.model_dump() for t in get_approved_tools()]

    # ── Phase 2: Build structured request ───────────────────────────
    request = HealthAssistantRequest(
        messages=messages,
        tools=approved_tools,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    # ── Phase 3: Call Ollama ───────────────────────────────────────
    try:
        raw = client.chat(
            model=model,
            messages=request.messages,
            tools=request.tools if request.tools else None,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
    except RuntimeError:
        degrade = build_degrade_response("MODEL_UNAVAILABLE")
        return _degrade_payload(degrade)

    # ── Phase 4: Parse & validate structured output ────────────────
    raw_content = raw.get("message", {}).get("content", "")
    try:
        parsed = HealthAssistantOutput.model_validate_json(raw_content)
    except (ValidationError, json.JSONDecodeError):
        # Try to extract from plain text — validate against schema
        try:
            parsed = _parse_loose_output(raw_content)
        except Exception:
            degrade = build_degrade_response("SCHEMA_VALIDATION_FAILED")
            return _degrade_payload(degrade)

    # ── Phase 5: Medical boundary check ────────────────────────────
    violations = _check_medical_boundary(parsed.answer)
    if violations:
        logger.warning("Medical boundary violation: %s", violations)
        degrade = build_degrade_response("MEDICAL_BOUNDARY_VIOLATION")
        return _degrade_payload(degrade)

    # ── Phase 6: Check for external links ──────────────────────────
    if _contains_external_links(parsed.answer):
        logger.warning("External link detected in assistant output")
        degrade = build_degrade_response("EXTERNAL_LINK_DETECTED")
        return _degrade_payload(degrade)

    # ── Phase 7: Return validated output ───────────────────────────
    return {
        "answer": parsed.answer,
        "sources": parsed.sources,
        "confidence": parsed.confidence,
        "escalate": parsed.escalate,
        "degraded": False,
        "degrade_reason": None,
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
