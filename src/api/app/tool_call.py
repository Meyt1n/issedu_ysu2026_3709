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
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from ai.safety.classifier import classify_question_dual, classify_question_lexicon
from ai.safety.lexicon import (
    DATA_EXFILTRATION_TERMS,
    FOLLOW_UP_RISK_TERMS,
    MEDICAL_BOUNDARY_TERMS,
    MEDICATION_SAFETY_ROUTE_TERMS,
    URGENT_ROUTE_TERMS,
    medical_boundary_hits,
)
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────

OLLAMA_DEFAULT_URL = "http://localhost:11434"
REQUEST_TIMEOUT = 30.0
MAX_RETRIES = 2
RETRY_BACKOFF = 2.0
MAX_TOOL_ROUNDS = 3

# Re-export shared lexicon names used by tests / callers that historically
# imported the private module-level lists from this file.
_MEDICAL_PROHIBITIONS: list[str] = list(MEDICAL_BOUNDARY_TERMS)
_DATA_EXFILTRATION_PROHIBITIONS: list[str] = list(DATA_EXFILTRATION_TERMS)
_FOLLOW_UP_RISK_TERMS = FOLLOW_UP_RISK_TERMS

# Default degrade template when model is unavailable
_DEGRADE_TEMPLATE = """当前助手服务暂时不可用。您可以：

1. 查阅已保存的健康事件记录
2. 查看规则引擎生成的提醒
3. 确认或修正已扫描的健康事件

如有紧急情况请及时联系医务人员。"""

# Output-contract system prompt pinned in front of every conversation.
# The fine-tuned v5 model answers evidence-first; this fixes the JSON shape
# the parser below expects regardless of caller-provided system context.
ASSISTANT_SYSTEM_PROMPT = (
    "/no_think\n"
    "你是「家健镜」家庭健康助手，运行在家庭本地设备上，服务于家庭照护的教学演示。"
    "首要任务是基于本轮已授权工具结果和已审核知识，直接、完整地回答用户问题。\n"
    "不要逐条复述或检查这些规则，不要展示分析草稿或内部推理；尽快只输出最终 JSON。\n"
    "回答要求：\n"
    "1. answer 必须是 1 至 6 句自然、完整的简体中文；绝不能只输出 hello、healthy、"
    "cannot_answer、unknown、DIRECT、REFUSE 等标签，也不要复述内部路由名称。\n"
    "2. 只依据系统消息中的本地事实、工具结果、规则结果与文档片段回答。资料不足时，"
    "明确说明缺少哪项资料和可以去哪个本地页面核对，不能猜测或补造事实。\n"
    "3. 用户问当前药品时，只列出已确认记录中明确出现的药名、规格等字段；如果只有"
    "medication_added 事件但没有药名，就回答「存在已确认的用药记录，但当前证据未提供"
    "药名和规格」。\n"
    "4. 用户问症状时，不诊断疾病；可复述用户描述、提示记录发生时间和伴随情况，并建议"
    "必要时联系医生。出现呼吸困难、意识异常、疑似中毒等紧急描述时 escalate=true。\n"
    "5. 用户问药品能否同服、停药、换药或剂量时，必须先调用成员状态/用药记录工具，"
    "再调用 retrieve_knowledge 查询已审核的本地药品文档；不自行判断，只解释已命中的确定性规则"
    "或授权文档。没有对应知识片段就明确无法判断，并建议咨询医生或药师。\n"
    "6. 普通问候要用简短中文正常回应；不得把问候误识别为健康结论。\n"
    "7. 需要更多事实时优先调用白名单工具。sources 只能填写本轮工具结果真实提供的"
    "事件 ID、规则编号或知识片段 ID；没有依据时使用空数组，禁止伪造引用。\n"
    "8. 绝不做诊断、开处方、决定用药剂量或建议停药换药；不提供购买链接、问诊导流或外部网址。\n"
    "9. 用温和、口语化的简体中文，先给依据再给解释，回答控制在 300 字以内。\n"
    "10. 输出必须是一个 JSON 对象，且只有 JSON，格式："
    '{"answer": "回答正文", "sources": ["引用的依据标识"], '
    '"confidence": "high|medium|low", "escalate": false}。'
    "紧急情况（如疑似中毒、呼吸困难）时 escalate 设为 true 并提醒联系医务人员。"
)

_PLACEHOLDER_ANSWER_LABELS = {
    "hello",
    "healthy",
    "cannot_answer",
    "cannot answer",
    "unknown",
    "direct",
    "evidence_required",
    "risk_only",
    "refuse",
    "urgent_escalate",
}


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

    def to_ollama_tool(self) -> dict[str, Any]:
        """Convert the internal whitelist entry to Ollama's tool schema.

        The registry intentionally keeps a small internal representation for
        argument validation. Ollama expects the OpenAI-compatible wire shape
        instead: ``type=function`` with a nested ``function`` object and a
        JSON-Schema ``parameters`` object. Sending the registry model dump
        directly makes Ollama reject the request with HTTP 500.
        """
        properties: dict[str, dict[str, Any]] = {}
        for name, schema in self.params.items():
            property_schema: dict[str, Any] = {
                "type": schema.type,
                "description": schema.description,
            }
            if schema.enum is not None:
                property_schema["enum"] = list(schema.enum)
            if schema.default is not None:
                property_schema["default"] = schema.default
            properties[name] = property_schema

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                },
            },
        }

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


ASSISTANT_OUTPUT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer", "sources", "confidence", "escalate"],
    "properties": {
        "answer": {"type": "string", "minLength": 1, "maxLength": 800},
        "sources": {
            "type": "array",
            "maxItems": 16,
            "items": {"type": "string", "minLength": 1, "maxLength": 200},
        },
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "escalate": {"type": "boolean"},
    },
}


class HealthAssistantOutput(BaseModel):
    """Structured output schema for the health assistant.

    Validation order for every model turn:
    1. JSON object parse (or degrade)
    2. Field-level Pydantic / JSON-schema checks below
    3. Shared medical / exfiltration / link blacklist as a final gate
    """

    answer: str = Field(min_length=1, max_length=800, description="Natural language response")
    sources: list[str] = Field(default_factory=list, max_length=16, description="Source IDs")
    confidence: Literal["high", "medium", "low"] = Field(default="low")
    escalate: bool = Field(default=False, description="Whether to escalate to a human")

    @field_validator("answer")
    @classmethod
    def _answer_must_be_substantive(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("ANSWER_EMPTY")
        if cleaned.casefold() in _PLACEHOLDER_ANSWER_LABELS:
            raise ValueError("ANSWER_PLACEHOLDER")
        return cleaned

    @field_validator("sources")
    @classmethod
    def _sources_must_be_tokens(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("SOURCE_NOT_STRING")
            token = item.strip()
            if not token:
                raise ValueError("SOURCE_EMPTY")
            if len(token) > 200:
                raise ValueError("SOURCE_TOO_LONG")
            normalized.append(token)
        return normalized[:16]


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
        "limit": {
            "type": "integer",
            "description": "Maximum confirmed events to return (1-20)",
            "default": 20,
        },
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
            # trust_env=False: local model calls must never go through a
            # system proxy (a misconfigured proxy turns localhost into 502).
            with httpx.Client(timeout=REQUEST_TIMEOUT, trust_env=False) as client:
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
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a chat completion request to Ollama."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            # Qwen3 thinking is disabled in the fine-tune; ask servers that
            # understand the flag to skip it too (others ignore the field).
            "think": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if tools:
            payload["tools"] = tools
        # Prefer schema-constrained JSON for the assistant contract.  Tool
        # rounds still include tools; Ollama ignores unknown fields and uses
        # format when emitting the final message content.
        if response_format is not None:
            payload["format"] = response_format

        last_error: str | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                with httpx.Client(timeout=timeout or REQUEST_TIMEOUT, trust_env=False) as client:
                    resp = client.post(f"{self.base_url}/api/chat", json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    self._available = True
                    return data
            except httpx.TimeoutException:
                last_error = "TIMEOUT"
                logger.warning("Ollama request timed out (attempt %d)", attempt + 1)
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                last_error = f"HTTP_{status_code}"
                logger.warning(
                    "Ollama HTTP error %s (attempt %d)",
                    status_code, attempt + 1,
                )
                # A 4xx (other than 408/429) is deterministic — for example
                # an unknown model name.  Retrying only delays the structured
                # degrade response the caller is waiting for.
                if 400 <= status_code < 500 and status_code not in (408, 429):
                    break
            except Exception as exc:
                last_error = str(exc)[:120]
                logger.warning("Ollama connection error (attempt %d): %s", attempt + 1, exc)

            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF ** attempt)

        logger.error("Ollama failed after %d attempts: %s", MAX_RETRIES + 1, last_error)
        raise RuntimeError(f"OLLAMA_UNAVAILABLE: {last_error}")

    def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
        max_tokens: int = 512,
        timeout: float | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ):
        """Stream chat completion chunks from Ollama.

        ``cancel_check`` is polled between chunks; when it returns True the
        HTTP stream is abandoned and a RuntimeError is raised so the
        orchestrator can stop without waiting for the full generation.
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "think": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if tools:
            payload["tools"] = tools

        with httpx.Client(timeout=timeout or REQUEST_TIMEOUT, trust_env=False) as client:
            with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if cancel_check is not None and cancel_check():
                        raise RuntimeError("OLLAMA_CANCELLED")
                    if not line:
                        continue
                    data = json.loads(line)
                    content = (data.get("message") or {}).get("content") or ""
                    if content:
                        yield content
                    if data.get("done"):
                        break
        self._available = True


# ── Medical safety check ───────────────────────────────────────────────


def _check_medical_boundary(output_text: str) -> list[str]:
    return medical_boundary_hits(output_text)


def _check_data_exfiltration(output_text: str) -> list[str]:
    return [
        keyword
        for keyword in DATA_EXFILTRATION_TERMS
        if keyword.casefold() in output_text.casefold()
    ]


def _contains_external_links(output_text: str) -> bool:
    """Detect external URLs that could be used for referral / advertising."""
    import re
    url_pattern = re.compile(r'https?://[^\s<"\']+', re.IGNORECASE)
    return bool(url_pattern.search(output_text))


# ── HCT-411: Controlled follow-up questions ──────────────────────────


_FOLLOW_UP_MAX_COUNT = 3
_FOLLOW_UP_MAX_LENGTH = 80
_FOLLOW_UP_MEDICATION_TERMS = (
    "药", "用药", "服用", "吃什么", "吃哪", "阿莫西林", "布洛芬", "处方",
)
_FOLLOW_UP_SYMPTOM_TERMS = (
    "症状", "感冒", "发烧", "发热", "咳嗽", "腹泻", "头晕", "乏力", "疼", "不舒服",
)
_FOLLOW_UP_EVIDENCE_TERMS = (
    "记录", "事件", "证据", "引用", "依据", "规则", "提醒", "成员", "药品清单",
)


def _latest_user_query(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


_QUESTION_TYPES = {
    "MEDICATION_SAFETY": "用药安全核对",
    "MEDICATION_RECORD": "用药记录查询",
    "FAMILY_RECORD": "家庭健康档案查询",
    "RULE_EVIDENCE": "规则与证据查询",
    "URGENT": "紧急情况分流",
    "GENERAL": "一般健康信息",
}


def classify_question(query: str) -> str:
    """Classify the latest question with lexicon + optional local model.

    This is a routing hint, not a medical conclusion.  High-risk medication
    questions are intentionally routed to both member facts and approved
    knowledge retrieval before Ollama is allowed to produce an answer.

    HCT-442: lexicon is always on. When ``AGENT_CLASSIFIER_ENABLED=true`` and
    Ollama is loopback, a short local classification pass merges by severity
    (prefer MEDICATION_SAFETY / URGENT). Model failure falls back to lexicon.
    """
    try:
        from app.config import get_settings

        settings = get_settings()
        return classify_question_dual(
            query,
            model_enabled=bool(settings.agent_classifier_enabled),
            is_loopback_url=is_loopback_ollama_url,
            ollama_base_url=settings.ollama_base_url,
            ollama_model=settings.ollama_model,
            ollama_timeout=float(settings.agent_classifier_timeout_seconds),
            chat_factory=lambda base_url: OllamaClient(base_url=base_url),
        )
    except Exception:  # noqa: BLE001 — routing must never fail open to crash
        logger.exception("dual classifier failed; falling back to lexicon")
        return classify_question_lexicon(query)


def question_type_label(query_type: str) -> str:
    return _QUESTION_TYPES.get(query_type, _QUESTION_TYPES["GENERAL"])


def risk_notice_for_question(query_type: str) -> str | None:
    if query_type == "MEDICATION_SAFETY":
        return "用药安全信息仅用于核对本地记录和已审核资料，请务必咨询医生或药师。"
    if query_type == "URGENT":
        return "如出现紧急症状，请及时联系医务人员；本助手不能替代紧急救治。"
    return None


def is_loopback_ollama_url(url: str) -> bool:
    """Return whether an Ollama endpoint is local to this machine."""
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.hostname in {
        "localhost", "127.0.0.1", "::1",
    }


def _sanitize_follow_up_questions(candidates: list[str]) -> list[str]:
    """Keep follow-ups short, local, non-commercial, and non-prescriptive."""
    sanitized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        question = re.sub(r"\s+", " ", candidate).strip()
        key = question.casefold()
        if (
            not question
            or len(question) > _FOLLOW_UP_MAX_LENGTH
            or key in seen
            or _contains_external_links(question)
            or _check_medical_boundary(question)
        ):
            continue
        seen.add(key)
        sanitized.append(question)
        if len(sanitized) >= _FOLLOW_UP_MAX_COUNT:
            break
    return sanitized


def suggest_follow_up_questions(
    messages: list[dict[str, Any]],
    *,
    degraded: bool = False,
    escalate: bool = False,
) -> list[str]:
    """Generate safe, deterministic follow-ups from the latest user query.

    Suggestions are interaction prompts, not model facts or medical advice.
    They intentionally do not inspect private facts, tool results, or the
    model's hidden reasoning, so an unknown query cannot disclose household
    data. Degraded responses return no suggestions because their evidence
    context is already incomplete.
    """
    if degraded:
        return []
    query = _latest_user_query(messages)
    if not query:
        return []
    normalized = query.casefold()

    if escalate or any(term in normalized for term in _FOLLOW_UP_RISK_TERMS):
        candidates = [
            "这条用药信息需要医生或药师确认哪些内容？",
            "当前药品记录的来源和确认状态是什么？",
            "如何查看这条信息对应的本地规则？",
        ]
    elif any(term in normalized for term in _FOLLOW_UP_MEDICATION_TERMS):
        candidates = [
            "这条回答依据了哪些已确认的药品记录？",
            "当前药品的规格、有效期或批号是否已核对？",
            "这条信息还缺少哪些证据需要人工确认？",
        ]
    elif any(term in normalized for term in _FOLLOW_UP_SYMPTOM_TERMS):
        candidates = [
            "我还需要补充哪些症状和发生时间？",
            "哪些情况需要尽快联系医生或药师？",
            "当前回答引用了哪些已确认记录或本地规则？",
        ]
    elif any(term in normalized for term in _FOLLOW_UP_EVIDENCE_TERMS):
        candidates = [
            "这条信息的来源和确认状态是什么？",
            "是否还有缺失字段需要人工补充？",
            "如何查看或更正这条本地记录？",
        ]
    elif normalized in {"你好", "您好", "hello", "hi", "在吗", "你能做什么"}:
        candidates = [
            "你能查看哪些已确认的健康记录？",
            "当前回答会引用哪些本地依据？",
            "如何确认或修正一条识别结果？",
        ]
    else:
        candidates = [
            "这条回答依据了哪些已确认记录？",
            "我还需要补充哪些信息才能继续核对？",
            "如何查看相关的本地规则或文档？",
        ]
    return _sanitize_follow_up_questions(candidates)


# ── Structured degrade ────────────────────────────────────────────────


@dataclass
class DegradedResponse:
    answer: str
    degraded: bool = True
    reason: str = "MODEL_UNAVAILABLE"
    sources: list[str] = field(default_factory=list)
    escalate: bool = False


def degrade_result(
    degrade: DegradedResponse,
    model: str | None = None,
    *,
    query_type: str | None = None,
) -> dict[str, Any]:
    """Map a DegradedResponse onto the assistant response contract."""
    payload = _degrade_payload(degrade)
    payload["model"] = model
    payload["query_type"] = query_type
    payload["risk_notice"] = risk_notice_for_question(query_type or "")
    return payload


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
    if reason == "DATA_EXFILTRATION_VIOLATION":
        return DegradedResponse(
            answer="当前请求包含未授权的敏感字段，已拒绝输出；请仅查看当前授权范围内的本地摘要。",
            degraded=True,
            reason=reason,
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


def _authorized_member_events(
    session: Session,
    *,
    actor_id: str,
    household_id: str | None,
    member_id: str | None,
    access_purpose: str | None,
    event_type: str | None = None,
    limit: int | None = None,
) -> tuple[list[Any] | None, str | None]:
    """Load only confirmed events after enforcing the API read boundary.

    The model may propose tool arguments, but it never chooses the scope.  The
    route-selected household/member pair is the authority, and the same
    member/field/action/purpose check used by the ordinary timeline endpoint
    is repeated immediately before tool data is read.
    """
    from app.models import Household, Member
    from app.security import has_authorized_action

    if not household_id or not member_id:
        return None, "TOOL_SCOPE_DENIED"
    household = session.get(Household, household_id)
    member = session.get(Member, member_id)
    if (
        household is None
        or member is None
        or household.deleted_at is not None
        or member.deleted_at is not None
        or member.household_id != household_id
    ):
        return None, "TOOL_SCOPE_DENIED"
    if not has_authorized_action(
        session,
        household,
        member_id,
        actor_id,
        "READ_EVENTS",
        "health_events",
        access_purpose,
    ):
        return None, "TOOL_SCOPE_DENIED"

    from app.projection import get_timeline

    events = get_timeline(session, member_id)
    if event_type:
        events = [event for event in events if event.event_type == event_type]
    if limit is not None:
        events = events[-max(1, min(limit, 20)):]
    return events, None


_SAFE_EVENT_PAYLOAD_KEYS = (
    "drug_name", "drug", "specification", "strength", "ingredient",
    "expiry_date", "stock", "allergy", "disease", "plan", "schedule",
    "symptom", "note", "status",
)


def _safe_event_fields(payload: dict[str, Any] | None) -> dict[str, str | int | float | bool]:
    """Expose an allowlisted fact subset, never the raw event payload/evidence."""
    if not isinstance(payload, dict):
        return {}
    fields: dict[str, str | int | float | bool] = {}
    for key in _SAFE_EVENT_PAYLOAD_KEYS:
        value = payload.get(key)
        if isinstance(value, (str, int, float, bool)) and (
            not isinstance(value, str) or value.strip()
        ):
            fields[key] = value.strip() if isinstance(value, str) else value
    return fields


def _public_health_event(event: Any) -> dict[str, Any]:
    fields = _safe_event_fields(event.payload)
    summary_parts = [f"{key}={value}" for key, value in fields.items()]
    return {
        "event_id": event.id,
        "event_type": event.event_type,
        "source": event.source,
        "confirmation_status": "CONFIRMED",
        "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "fields": fields,
        "summary": "；".join(summary_parts),
    }


def _state_with_sources(facts: dict[str, Any]) -> dict[str, Any]:
    """Serialize the projection with source event IDs and no raw payload."""
    sources: list[str] = []

    def source_id(item: dict[str, Any]) -> str | None:
        value = item.get("added_by")
        if isinstance(value, str) and value:
            sources.append(value)
            return value
        return None

    drugs = []
    for item in facts.get("drugs", []):
        item_source = source_id(item)
        drugs.append({
            "name": item.get("name"),
            "ingredient": item.get("ingredient"),
            "expiry_date": item.get("expiry_date"),
            "stock": item.get("stock"),
            "source_event_id": item_source,
        })
    allergies = []
    for item in facts.get("allergies", []):
        item_source = source_id(item)
        allergies.append({"name": item.get("name"), "source_event_id": item_source})
    diseases = []
    for item in facts.get("diseases", []):
        item_source = source_id(item)
        diseases.append({"name": item.get("name"), "source_event_id": item_source})
    plans = []
    for item in facts.get("plans", []):
        item_source = source_id(item)
        plans.append({
            "drug": item.get("drug"),
            "schedule": item.get("schedule"),
            "source_event_id": item_source,
        })
    return {
        "drugs": drugs,
        "allergies": allergies,
        "diseases": diseases,
        "plans": plans,
        "caregivers": [item for item in facts.get("caregivers", []) if isinstance(item, str)],
        "events_count": facts.get("events_count", 0),
        "last_event_id": facts.get("last_event_id"),
        "sources": list(dict.fromkeys(source for source in sources if source)),
    }


def _public_alert(alert: Any) -> dict[str, Any]:
    return {
        "rule_id": alert.rule_id,
        "level": alert.level,
        "message": alert.message,
        "source_event_ids": list(dict.fromkeys(alert.source_event_ids)),
    }


def _citation_from_chunk(chunk: dict[str, Any]) -> dict[str, str]:
    return {
        "document_id": str(chunk["document_id"]),
        "version": str(chunk.get("version") or ""),
        "chunk_id": str(chunk["chunk_id"]),
        "document_title": str(chunk.get("document_title") or chunk.get("title") or ""),
        "text": str(chunk.get("text") or ""),
        "locator": str(chunk.get("locator") or ""),
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


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_KNOWLEDGE_TOKEN_RE = re.compile(r"(chunk|document|doc[-_]|kb[-_])", re.IGNORECASE)


def _looks_like_knowledge_citation(token: str) -> bool:
    """True when a source token claims a knowledge chunk/document id."""
    text = token.strip()
    if not text:
        return False
    return bool(_UUID_RE.match(text) or _KNOWLEDGE_TOKEN_RE.search(text))


def _unmatched_source_tokens(
    claimed: list[str],
    matched: list[dict[str, str]],
) -> list[str]:
    indexed = _index_allowed_citations(matched)
    unmatched: list[str] = []
    for token in claimed:
        key = str(token).strip()
        if not key or key in indexed:
            continue
        unmatched.append(key)
    return unmatched


def _execute_get_health_events(
    session: Session,
    *,
    actor_id: str,
    household_id: str | None,
    member_id: str | None,
    access_purpose: str | None,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    event_type = str(arguments.get("event_type") or "").strip() or None
    try:
        limit = int(arguments.get("limit") or 20)
    except (TypeError, ValueError):
        limit = 20
    events, error = _authorized_member_events(
        session,
        actor_id=actor_id,
        household_id=household_id,
        member_id=member_id,
        access_purpose=access_purpose,
        event_type=event_type,
        limit=limit,
    )
    if error:
        return {"error": error, "events": [], "sources": [], "total": 0}
    public_events = [_public_health_event(event) for event in (events or [])]
    return {
        "events": public_events,
        "sources": [event["event_id"] for event in public_events],
        "total": len(public_events),
    }


def _execute_get_member_state(
    session: Session,
    *,
    actor_id: str,
    household_id: str | None,
    member_id: str | None,
    access_purpose: str | None,
) -> dict[str, Any]:
    events, error = _authorized_member_events(
        session,
        actor_id=actor_id,
        household_id=household_id,
        member_id=member_id,
        access_purpose=access_purpose,
    )
    if error:
        return {"error": error, "state": {}, "sources": []}
    from app.projection import build_relationship_graph

    state = _state_with_sources(build_relationship_graph(events or []))
    return {"state": state, "sources": state["sources"]}


def _execute_get_applied_rules(
    session: Session,
    *,
    actor_id: str,
    household_id: str | None,
    member_id: str | None,
    access_purpose: str | None,
) -> dict[str, Any]:
    events, error = _authorized_member_events(
        session,
        actor_id=actor_id,
        household_id=household_id,
        member_id=member_id,
        access_purpose=access_purpose,
    )
    if error:
        return {"error": error, "rules": [], "sources": []}
    from app.projection import build_relationship_graph
    from app.rules import dedup_alerts, run_rules

    alerts = dedup_alerts(run_rules(build_relationship_graph(events or [])))
    rules = [
        {
            "rule_id": alert.rule_id,
            "level": alert.level,
            "source_event_ids": list(dict.fromkeys(alert.source_event_ids)),
        }
        for alert in alerts
    ]
    sources = list(dict.fromkeys(
        [rule["rule_id"] for rule in rules]
        + [event_id for rule in rules for event_id in rule["source_event_ids"]]
    ))
    return {"rules": rules, "sources": sources, "total": len(rules)}


def _execute_get_risk_alerts(
    session: Session,
    *,
    actor_id: str,
    household_id: str | None,
    member_id: str | None,
    access_purpose: str | None,
) -> dict[str, Any]:
    events, error = _authorized_member_events(
        session,
        actor_id=actor_id,
        household_id=household_id,
        member_id=member_id,
        access_purpose=access_purpose,
    )
    if error:
        return {"error": error, "alerts": [], "sources": []}
    from app.config import get_settings
    from app.projection import build_relationship_graph
    from app.rules import apply_daily_budget, dedup_alerts, run_rules

    alerts = apply_daily_budget(dedup_alerts(run_rules(build_relationship_graph(events or []))))
    public_alerts = [_public_alert(alert) for alert in alerts]
    sources = list(dict.fromkeys(
        [alert["rule_id"] for alert in public_alerts]
        + [event_id for alert in public_alerts for event_id in alert["source_event_ids"]]
    ))
    return {
        "alerts": public_alerts,
        "sources": sources,
        "ruleset_version": get_settings().ruleset_version,
        "total": len(public_alerts),
    }


def _execute_retrieve_knowledge(
    session: Session,
    *,
    actor_id: str,
    household_id: str | None,
    member_id: str | None,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    from app.knowledge import log_query, retrieve

    # An unscoped route may still search actor-owned/global approved
    # documents, but the model must not invent a household/member filter to
    # make the server inspect another family's knowledge scope.
    if household_id is None and arguments.get("household_id") not in (None, ""):
        return {"error": "TOOL_SCOPE_DENIED", "results": [], "total": 0}
    if member_id is None and arguments.get("member_id") not in (None, ""):
        return {"error": "TOOL_SCOPE_DENIED", "results": [], "total": 0}
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
    from app.config import get_settings
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
        doc_created_by=document.created_by,
        knowledge_admin_ids=get_settings().knowledge_admin_actor_set,
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
    access_purpose: str | None = None,
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
    if name in {
        "get_health_events",
        "get_member_state",
        "get_applied_rules",
        "get_risk_alerts",
    }:
        if not household_id or not member_id:
            return {"error": "TOOL_SCOPE_DENIED"}
        _, household_error = _bound_scope_value(
            validated.get("household_id"), household_id,
        )
        _, member_error = _bound_scope_value(
            validated.get("member_id"), member_id,
        )
        if household_error or member_error:
            return {"error": "TOOL_SCOPE_DENIED"}
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
    if name == "get_health_events":
        return _execute_get_health_events(
            session,
            actor_id=actor_id,
            household_id=household_id,
            member_id=member_id,
            access_purpose=access_purpose,
            arguments=validated,
        )
    if name == "get_member_state":
        return _execute_get_member_state(
            session,
            actor_id=actor_id,
            household_id=household_id,
            member_id=member_id,
            access_purpose=access_purpose,
        )
    if name == "get_applied_rules":
        return _execute_get_applied_rules(
            session,
            actor_id=actor_id,
            household_id=household_id,
            member_id=member_id,
            access_purpose=access_purpose,
        )
    if name == "get_risk_alerts":
        return _execute_get_risk_alerts(
            session,
            actor_id=actor_id,
            household_id=household_id,
            member_id=member_id,
            access_purpose=access_purpose,
        )
    return {"error": "TOOL_NOT_BOUND"}


def _parse_assistant_output(raw_content: str) -> HealthAssistantOutput | None:
    if not raw_content or not str(raw_content).strip():
        return None
    try:
        parsed = parse_model_output(raw_content)
    except (ValidationError, json.JSONDecodeError, ValueError):
        return None
    answer = parsed.answer.strip()
    if not answer or answer.casefold() in _PLACEHOLDER_ANSWER_LABELS:
        return None
    return parsed


def run_assistant(
    db_session,
    *,
    messages: list[dict[str, Any]],
    actor_id: str,
    household_id: str | None = None,
    member_id: str | None = None,
    access_purpose: str | None = None,
    model: str | None = None,
    max_tokens: int = 512,
    temperature: float = 0.3,
) -> dict[str, Any]:
    """Run the health assistant with tool calling and citation checks.

    Returns a dict with:
        answer, sources, citations, confidence, escalate, degraded,
        degrade_reason, model, route, suggested_questions, query_type, risk_notice
    """
    from app.config import get_settings

    settings = get_settings()
    model = model or settings.ollama_model
    timeout = settings.ollama_timeout_seconds
    client = OllamaClient(settings.ollama_base_url)
    query_type = classify_question(_latest_user_query(messages))

    def degraded(reason: str) -> dict[str, Any]:
        return degrade_result(
            build_degrade_response(reason),
            model,
            query_type=query_type,
        )

    if not is_loopback_ollama_url(settings.ollama_base_url):
        logger.warning("Blocked non-loopback Ollama endpoint for local assistant")
        return degraded("LOCAL_MODEL_ENDPOINT_REQUIRED")

    # Pin the output contract as the leading system message; caller-provided
    # system context (e.g. injected member facts) is merged after it so
    # grounding never displaces the JSON contract or the medical boundary.
    routing_hint = (
        f"【本轮问题类型：{question_type_label(query_type)}】"
        "这是后端安全路由提示，不是需要复述给用户的内容。"
    )
    if query_type == "MEDICATION_SAFETY":
        routing_hint += (
            "必须先调用 get_member_state 或 get_health_events 获取已确认用药记录，"
            "再调用 retrieve_knowledge 检索已审核药品文档；没有知识片段不得回答"
            "能否同服、停药、换药或剂量。"
        )
    elif query_type in {"MEDICATION_RECORD", "FAMILY_RECORD"}:
        routing_hint += (
            "优先调用 get_member_state 或 get_health_events，并在 sources 中引用"
            "工具返回的事件 ID。"
        )
    elif query_type == "RULE_EVIDENCE":
        routing_hint += (
            "优先调用 get_applied_rules 或 get_risk_alerts，并在 sources 中引用"
            "工具返回的规则编号或事件 ID。"
        )
    system_parts = [ASSISTANT_SYSTEM_PROMPT, routing_hint] + [
        str(message.get("content", ""))
        for message in messages
        if message.get("role") == "system" and message.get("content")
    ]
    conversation = [
        {"role": "system", "content": "\n\n".join(system_parts)},
        *[message for message in messages if message.get("role") != "system"],
    ]

    approved_tools = [tool.to_ollama_tool() for tool in get_approved_tools()]
    request = HealthAssistantRequest(
        messages=conversation,
        tools=approved_tools,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    allowed_citations: list[dict[str, str]] = []
    allowed_fact_sources: set[str] = set()
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
                timeout=timeout,
                response_format=ASSISTANT_OUTPUT_JSON_SCHEMA,
            )
        except RuntimeError:
            return degraded("MODEL_UNAVAILABLE")

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
                    access_purpose=access_purpose,
                )
                if result.get("error"):
                    tool_errors.append(str(result["error"]))
                for chunk in result.get("results") or []:
                    allowed_citations.append(_citation_from_chunk(chunk))
                for source in result.get("sources") or []:
                    if isinstance(source, str) and source.strip():
                        allowed_fact_sources.add(source.strip())
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
            return degraded("SCHEMA_VALIDATION_FAILED")
        break
    else:
        return degraded("SCHEMA_VALIDATION_FAILED")

    assert parsed is not None
    violations = _check_medical_boundary(parsed.answer)
    if violations:
        logger.warning("Medical boundary violation: %s", violations)
        return degraded("MEDICAL_BOUNDARY_VIOLATION")
    if _contains_external_links(parsed.answer):
        logger.warning("External link detected in assistant output")
        return degraded("EXTERNAL_LINK_DETECTED")
    if _check_data_exfiltration(parsed.answer):
        logger.warning("Sensitive data exfiltration detected in assistant output")
        return degraded("DATA_EXFILTRATION_VIOLATION")

    # A model-proposed tool is never an authority boundary.  Unknown tools,
    # missing sessions and cross-scope arguments all degrade to the same
    # structured refusal instead of allowing the model to continue as if its
    # tool request had succeeded.
    if any(
        error in tool_errors
        for error in {"TOOL_SCOPE_DENIED", "TOOL_NOT_ALLOWED", "TOOL_SESSION_REQUIRED"}
    ):
        return degraded("TOOL_SCOPE_DENIED")
    if "NO_AUTHORISED_DOCUMENTS" in tool_errors and not allowed_citations:
        return degraded("NO_AUTHORISED_DOCUMENTS")

    matched_citations = filter_claimed_citations(parsed.sources, allowed_citations)
    unmatched = _unmatched_source_tokens(parsed.sources, matched_citations)
    unknown_sources = [token for token in unmatched if token not in allowed_fact_sources]
    if any(_looks_like_knowledge_citation(token) for token in unknown_sources):
        return degraded("CITATION_NOT_FOUND")
    if allowed_citations and not matched_citations:
        return degraded("EVIDENCE_REQUIRED")
    if query_type == "MEDICATION_SAFETY" and not matched_citations:
        return degraded("EVIDENCE_REQUIRED")
    if any(token not in allowed_fact_sources for token in unknown_sources):
        return degraded("CITATION_NOT_FOUND")

    fact_sources = [
        token for token in unmatched if token in allowed_fact_sources
    ]
    escalated = parsed.escalate or query_type == "URGENT"
    return {
        "answer": parsed.answer,
        "sources": [item["chunk_id"] for item in matched_citations] + fact_sources,
        "citations": matched_citations,
        "suggested_questions": suggest_follow_up_questions(
            messages,
            escalate=escalated,
        ),
        "confidence": parsed.confidence,
        "escalate": escalated,
        "degraded": False,
        "degrade_reason": None,
        "model": model,
        "route": "EVIDENCE_REQUIRED" if matched_citations else None,
        "query_type": query_type,
        "risk_notice": risk_notice_for_question(query_type),
    }


def strip_thinking(text: str) -> str:
    """Remove Qwen3 <think>...</think> blocks (and stray closers) from output."""
    import re

    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    cleaned = re.sub(r"^\s*</think>\s*", "", cleaned)
    return cleaned.strip()


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Parse the first JSON object out of generated text (fences tolerated)."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        import re

        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I | re.S).strip()
    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for start, character in enumerate(cleaned):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(cleaned[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _normalize_sources(raw_sources: Any) -> list[str]:
    """Accept both plain strings and the v5 {source_id, evidence} objects."""
    if not isinstance(raw_sources, list):
        return []
    normalized: list[str] = []
    for item in raw_sources:
        if isinstance(item, str) and item.strip():
            normalized.append(item.strip())
        elif isinstance(item, dict):
            label = item.get("source_id") or item.get("id") or item.get("evidence")
            if isinstance(label, str) and label.strip():
                normalized.append(label.strip())
    return normalized[:8]


def parse_model_output(raw_text: str) -> HealthAssistantOutput:
    """Normalize model output onto the assistant schema.

    Handles the fine-tuned v5 contract drift: ``response`` instead of
    ``answer``, source objects instead of strings, thinking-block leakage
    and malformed JSON (regex fallback).  Field-level schema validation
    runs inside ``HealthAssistantOutput``; medical blacklist is applied by
    ``run_assistant`` afterwards.
    """
    text = strip_thinking(raw_text)
    parsed = _extract_json_object(text)
    if parsed is not None:
        answer = parsed.get("answer") or parsed.get("response") or parsed.get("content")
        if isinstance(answer, str) and answer.strip():
            confidence = parsed.get("confidence")
            return HealthAssistantOutput.model_validate(
                {
                    "answer": answer.strip(),
                    "sources": _normalize_sources(parsed.get("sources")),
                    "confidence": (
                        confidence if confidence in ("high", "medium", "low") else "low"
                    ),
                    "escalate": bool(parsed.get("escalate", False)),
                }
            )
    return _parse_loose_output(text)


def _parse_loose_output(text: str) -> HealthAssistantOutput:
    """Best-effort parse of non-JSON model output."""
    # Try to extract answer field (escaped quotes tolerated)
    import re
    answer_match = re.search(r'"(?:answer|response)"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    confidence_match = re.search(r'"confidence"\s*:\s*"(\w+)"', text)
    sources_match = re.search(r'"sources"\s*:\s*\[([^\]]*)\]', text)
    escalate_match = re.search(r'"escalate"\s*:\s*(true|false)', text)

    if answer_match:
        try:
            answer = json.loads(f'"{answer_match.group(1)}"')
        except json.JSONDecodeError:
            answer = answer_match.group(1)
    else:
        answer = text[:500]
    confidence = confidence_match.group(1) if confidence_match else "low"
    sources = []
    if sources_match:
        raw_srcs = sources_match.group(1)
        sources = [s.strip().strip('"') for s in raw_srcs.split(",") if s.strip().strip('"')]
    escalate = bool(escalate_match and escalate_match.group(1).lower() == "true")

    return HealthAssistantOutput(
        answer=answer,
        sources=sources,
        confidence=confidence if confidence in ("high", "medium", "low") else "low",
        escalate=escalate,
    )

