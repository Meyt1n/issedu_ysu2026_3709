"""Unit tests for HCT-442 dual-channel question classification."""

from __future__ import annotations

import pytest
from ai.safety.classifier import (
    classify_question_dual,
    classify_question_lexicon,
    merge_query_types,
    parse_model_query_type,
)

from app.tool_call import classify_question


def test_lexicon_keeps_colloquial_medication_safety() -> None:
    assert classify_question_lexicon("好像吃错药了怎么办？") == "MEDICATION_SAFETY"
    assert classify_question_lexicon("药吃多了需要催吐吗？") == "MEDICATION_SAFETY"
    assert classify_question_lexicon("可能拿错药了") == "MEDICATION_SAFETY"


def test_merge_prefers_higher_severity() -> None:
    assert merge_query_types("GENERAL", "MEDICATION_SAFETY") == "MEDICATION_SAFETY"
    assert merge_query_types("MEDICATION_SAFETY", "URGENT") == "URGENT"
    assert merge_query_types(None, "invalid", "FAMILY_RECORD") == "FAMILY_RECORD"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('{"query_type":"MEDICATION_SAFETY"}', "MEDICATION_SAFETY"),
        ('这里是标签 MEDICATION_SAFETY 结束', "MEDICATION_SAFETY"),
        ('{"query_type":"not-a-type"}', None),
        ("", None),
    ],
)
def test_parse_model_query_type(raw: str, expected: str | None) -> None:
    assert parse_model_query_type(raw) == expected


def test_dual_channel_model_raises_medication_safety_over_general() -> None:
    def fake_chat(**_kwargs):
        return {"message": {"content": '{"query_type":"MEDICATION_SAFETY"}'}}

    class _Client:
        chat = staticmethod(fake_chat)

    result = classify_question_dual(
        "药片好像吞成双份了要不要紧",
        model_enabled=True,
        is_loopback_url=lambda _url: True,
        ollama_base_url="http://127.0.0.1:11434",
        ollama_model="demo-classifier",
        chat_factory=lambda _url: _Client(),
    )
    assert result == "MEDICATION_SAFETY"


def test_dual_channel_model_failure_falls_back_to_lexicon() -> None:
    def boom(**_kwargs):
        raise RuntimeError("OLLAMA_UNAVAILABLE")

    class _Client:
        chat = staticmethod(boom)

    result = classify_question_dual(
        "今天天气怎么样",
        model_enabled=True,
        is_loopback_url=lambda _url: True,
        ollama_base_url="http://127.0.0.1:11434",
        ollama_model="demo-classifier",
        chat_factory=lambda _url: _Client(),
    )
    assert result == "GENERAL"


def test_dual_channel_skips_non_loopback_model(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"n": 0}

    def fake_chat(**_kwargs):
        called["n"] += 1
        return {"message": {"content": '{"query_type":"URGENT"}'}}

    class _Client:
        chat = staticmethod(fake_chat)

    result = classify_question_dual(
        "今天天气怎么样",
        model_enabled=True,
        is_loopback_url=lambda _url: False,
        ollama_base_url="http://evil.example:11434",
        ollama_model="demo-classifier",
        chat_factory=lambda _url: _Client(),
    )
    assert result == "GENERAL"
    assert called["n"] == 0


def test_classify_question_default_is_lexicon_only(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Settings:
        agent_classifier_enabled = False
        ollama_base_url = "http://127.0.0.1:11434"
        ollama_model = "demo"
        agent_classifier_timeout_seconds = 3.0

    monkeypatch.setattr("app.config.get_settings", lambda: _Settings())
    assert classify_question("好像吃错药了怎么办？") == "MEDICATION_SAFETY"
    assert classify_question("你好") == "GENERAL"


def test_lexicon_ignores_negated_prescription_in_news_prompt() -> None:
    news_prompt = (
        "请阅读这篇公开网页后再回答：https://www.who.int/zh/news-room "
        "结合本地知识库，用教学语气说明一般性居家照护注意点；"
        "不要诊断、不开处方、不编造病例数或未证实的疫情结论。"
    )
    assert classify_question_lexicon(news_prompt) == "GENERAL"
    assert classify_question_lexicon("最近有什么新闻吗") == "GENERAL"
    assert classify_question_lexicon("请帮我开处方") == "MEDICATION_SAFETY"
