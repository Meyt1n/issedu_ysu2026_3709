"""Open-chat demo mode helpers (HCT-451).

When ``AGENT_OPEN_CHAT`` is enabled (default for local demos), the assistant
behaves more like a normal local LLM chat: evidence/citation walls and short
template fallbacks are skipped so operators can evaluate the model's raw
reply quality.  Local clock context is always available so calendar questions
are answerable.  Production must set ``AGENT_OPEN_CHAT=false``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.config import get_settings

OPEN_CHAT_SYSTEM_PROMPT = (
    "/no_think\n"
    "你是「家健镜」家庭健康助手，运行在家庭本地设备上。"
    "当前为开放演示模式：请像普通智能助手一样直接、完整、有帮助地回答用户问题。\n"
    "要求：\n"
    "1. answer 用自然、完整的简体中文，先回应问题本身；可适当展开，不要只回标签或拒答套话。\n"
    "2. 可综合使用：系统给出的本机时间、本地健康档案工具结果、已审核知识片段、"
    "以及（若有）联网参考摘要。联网内容只作参考并注明「外部参考」，不要假装是本地审核证据。\n"
    "3. 用户问日期/时间时，以系统提供的本机时间为准直接回答。\n"
    "4. 用户问新闻/近况时，优先转述联网参考标题与要点；没有联网结果就如实说明。\n"
    "5. 健康相关问题可给出一般性居家照护与常见非处方资料介绍，语气像正常助手；"
    "仍建议严重情况就医，但不要用「超出系统边界」「缺少可核验引用」打断对话。\n"
    "6. sources 尽量填写本轮真实出现过的 chunk_id 或事实 ID；没有就用空数组，"
    "不要编造。联网链接不要强行塞进 sources。\n"
    "7. 输出必须是一个 JSON 对象且只有 JSON："
    '{"answer": "回答正文", "sources": [], "confidence": "high|medium|low", "escalate": false}。'
)


def is_open_chat(settings=None) -> bool:
    settings = settings or get_settings()
    return bool(getattr(settings, "agent_open_chat", True))


def local_clock_context(*, when: datetime | None = None) -> str:
    """Inject the device-local calendar so date questions are answerable."""
    moment = when or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    local = moment.astimezone()
    weekday = "一二三四五六日"[local.weekday()]
    return (
        f"【本机时间】{local.strftime('%Y年%m月%d日')}（星期{weekday}）"
        f" {local.strftime('%H:%M')}，时区 {local.tzinfo}。"
        "回答「今天几号/星期几」时请直接使用上述日期，不要说无法提供。"
    )


def effective_max_tokens(requested: int, settings=None) -> int:
    """Raise the generation budget in open-chat demo mode."""
    settings = settings or get_settings()
    value = max(1, int(requested or 512))
    if is_open_chat(settings):
        floor = int(getattr(settings, "agent_open_max_tokens", 4096) or 4096)
        return max(value, floor)
    return value


def coerce_open_model_answer(raw_content: str) -> dict[str, object] | None:
    """Best-effort accept non-JSON model drafts in open-chat mode."""
    text = (raw_content or "").strip()
    if not text:
        return None
    # Strip common fences
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return {
        "answer": text[:8000],
        "sources": [],
        "confidence": "medium",
        "escalate": False,
    }
