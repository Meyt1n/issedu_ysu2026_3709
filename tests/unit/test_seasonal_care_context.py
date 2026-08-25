"""Unit tests for calendar seasonal care framing."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from ai.safety.seasonal_context import seasonal_care_context


def test_seasonal_care_context_spring_mentions_temperature_swing() -> None:
    note = seasonal_care_context(
        when=datetime(2026, 3, 20, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert "换季" in note
    assert "编造" in note


def test_seasonal_care_context_winter_mentions_warmth() -> None:
    note = seasonal_care_context(
        when=datetime(2026, 1, 10, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert "冬季" in note
    assert "保暖" in note


def test_symptom_routing_injects_seasonal_context() -> None:
    from app.tool_call import ASSISTANT_SYSTEM_PROMPT, classify_question

    assert classify_question("我感冒了应该吃什么药？") == "SYMPTOM_MEDICATION"
    assert "人情味" in ASSISTANT_SYSTEM_PROMPT or "共情" in ASSISTANT_SYSTEM_PROMPT
    assert "季节情境" in ASSISTANT_SYSTEM_PROMPT or "换季" in ASSISTANT_SYSTEM_PROMPT
