"""HCT-451 open-chat demo and on-topic knowledge-gap answers."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.config import get_settings
from app.open_chat import effective_max_tokens, is_open_chat, local_clock_context
from app.tool_call import build_symptom_knowledge_gap_answer


def test_local_clock_context_answers_calendar_questions() -> None:
    text = local_clock_context(when=datetime(2026, 8, 26, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")))
    assert "2026年08月26日" in text
    assert "不要说无法提供" in text


def test_symptom_gap_answer_is_topic_aware_for_diarrhea() -> None:
    answer = build_symptom_knowledge_gap_answer(user_text="我有点腹泻，我应该注意什么，吃什么药")
    assert "腹泻" in answer
    assert "热伤风" not in answer
    assert "鼻塞" not in answer


def test_symptom_gap_answer_keeps_seasonal_for_generic_cold() -> None:
    answer = build_symptom_knowledge_gap_answer(user_text="我有点感冒")
    # This path runs only when the local model is unreachable, so the copy
    # gives real care advice and says the model is offline instead of blaming
    # an empty knowledge library.
    assert "模型" in answer
    assert any(token in answer for token in ("休息", "补水", "保暖"))


def test_open_chat_raises_token_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "agent_open_chat", True)
    monkeypatch.setattr(settings, "agent_open_max_tokens", 4096)
    assert is_open_chat(settings) is True
    assert effective_max_tokens(512, settings) == 4096
    assert effective_max_tokens(8000, settings) == 8000


def test_open_chat_off_keeps_requested_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "agent_open_chat", False)
    assert effective_max_tokens(512, settings) == 512


def test_open_chat_skips_symptom_short_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty knowledge must still call the model when open-chat is on."""
    from app import local_agents

    settings = get_settings()
    monkeypatch.setattr(settings, "agent_open_chat", True)
    monkeypatch.setattr(settings, "ollama_base_url", "http://127.0.0.1:11434")
    monkeypatch.setattr(settings, "ollama_model", "demo")

    calls: list[str] = []

    class FakeClient:
        def __init__(self, *_a, **_k) -> None:
            pass

        def chat_stream(self, **_kwargs):
            calls.append("stream")
            yield (
                '{"answer":"腹泻时先补水休息，外部参考仅供参考。",'
                '"sources":[],"confidence":"medium","escalate":false}'
            )

    monkeypatch.setattr(local_agents, "OllamaClient", FakeClient)
    monkeypatch.setattr(local_agents, "is_loopback_ollama_url", lambda _url: True)

    result = local_agents._synthesis_agent(
        messages=[{"role": "user", "content": "我有点腹泻，吃什么药"}],
        query_type="SYMPTOM_MEDICATION",
        database={},
        knowledge={"results": [], "error": "NO_AUTHORISED_DOCUMENTS"},
        external_sources=[{"title": "demo", "url": "https://example.com", "snippet": "x"}],
        model="demo",
        max_tokens=256,
        temperature=0.2,
        settings=settings,
    )
    assert calls == ["stream"]
    assert result["degraded"] is False
    assert "腹泻" in result["answer"]
    assert result.get("degrade_reason") is None


def test_open_chat_no_longer_bypasses_safety_sanitisation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Open-chat is experience-only: the dose limit applies there too.

    Stop / switch discussion now survives (it is teaching content), but a
    concrete per-serving quantity is still stripped in every mode."""
    from app import local_agents

    settings = get_settings()
    monkeypatch.setattr(settings, "agent_open_chat", True)

    class FakeClient:
        def __init__(self, *_a, **_k) -> None:
            pass

        def chat_stream(self, **_kwargs):
            yield (
                '{"answer":"布洛芬可以缓解不适。建议你停药并换新药。每次吃2片即可。'
                '有疑问请咨询医生或药师。","sources":[],"confidence":"low","escalate":false}'
            )

    monkeypatch.setattr(local_agents, "OllamaClient", FakeClient)
    monkeypatch.setattr(local_agents, "is_loopback_ollama_url", lambda _url: True)

    result = local_agents._synthesis_agent(
        messages=[{"role": "user", "content": "布洛芬吃着不舒服怎么办"}],
        query_type="MEDICATION_SAFETY",
        database={},
        knowledge={"results": []},
        external_sources=[],
        model="demo",
        max_tokens=256,
        temperature=0.2,
        settings=settings,
    )

    assert result["degraded"] is False
    assert "每次吃2片" not in result["answer"]
    assert "布洛芬可以缓解不适" in result["answer"]
    # Stop / switch wording is no longer censored out of the draft.
    assert "建议你停药" in result["answer"]
    assert "已略去" in result["answer"]  # dose-sanitiser footnote
    assert result["risk_notice"], "open-chat must expose the risk notice too"


def test_open_chat_rejects_router_control_label(monkeypatch: pytest.MonkeyPatch) -> None:
    """Internal ``route`` output must never be presented as a real answer."""
    from app import local_agents

    settings = get_settings()
    monkeypatch.setattr(settings, "agent_open_chat", True)

    class FakeClient:
        def __init__(self, *_a, **_k) -> None:
            pass

        def chat_stream(self, **_kwargs):
            yield '{"answer":"route","sources":[],"confidence":"low","escalate":false}'

    monkeypatch.setattr(local_agents, "OllamaClient", FakeClient)
    monkeypatch.setattr(local_agents, "is_loopback_ollama_url", lambda _url: True)

    result = local_agents._synthesis_agent(
        messages=[{"role": "user", "content": "普通问题"}],
        query_type="GENERAL",
        database={},
        knowledge={"results": []},
        external_sources=[],
        model="demo",
        max_tokens=64,
        temperature=0.2,
        settings=settings,
    )

    assert result["degraded"] is True
    assert result["degrade_reason"] == "SCHEMA_VALIDATION_FAILED"
    assert result["answer"] != "route"


def test_open_chat_rejects_orchestration_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.open_chat import coerce_open_model_answer

    leaked = (
        "问题类型是 MEDICATION_SAFETY。本地知识库 database_agent 报 TOOL_SCOPE_DENIED，"
        "上一稿没有在 sources 中引用任何 chunk_id。"
    )
    assert coerce_open_model_answer(leaked) is None
    assert coerce_open_model_answer("回答正文") is None
