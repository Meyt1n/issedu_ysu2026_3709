"""Open-chat mode helpers (HCT-451, narrowed by ADR-0007 / decision 8C).

``AGENT_OPEN_CHAT`` is now an experience-only knob: it relaxes output
*parsing* (non-JSON drafts are coerced) and raises the generation token
floor.  It no longer swaps in a permissive system prompt and no longer
bypasses the medical boundary, dose refusal, sentence sanitisation or
citation verification — the same safety strategy applies in every
environment, including production.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from app.config import get_settings

# Deprecated (ADR-0007): the permissive open-chat prompt bypassed the safety
# strategy and is no longer used anywhere.  The unified prompt lives in
# ``app.tool_call.ASSISTANT_SYSTEM_PROMPT``.  Kept as an alias so older
# imports fail loudly in review rather than silently diverging.
OPEN_CHAT_SYSTEM_PROMPT_DEPRECATED = True


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
    # A JSON object that failed the strict assistant contract must not be
    # re-labelled as natural-language prose.  In particular, ``{"answer":
    # "route"}`` is an internal control response and belongs in the degraded
    # path, not in the user-visible answer field.
    if text.startswith(("{", "[")):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and any(
            key in parsed for key in ("answer", "response", "content", "route")
        ):
            return None
    return {
        "answer": text[:8000],
        "sources": [],
        "confidence": "medium",
        "escalate": False,
    }
