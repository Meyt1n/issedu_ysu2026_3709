"""HCT-411: deterministic, safe follow-up question suggestions."""

import json

from app.schemas import AssistantResponse
from app.tool_call import OllamaClient, run_assistant, suggest_follow_up_questions


def test_medication_question_gets_evidence_focused_follow_ups() -> None:
    suggestions = suggest_follow_up_questions([
        {"role": "user", "content": "阿莫西林的记录依据是什么？"},
    ])

    assert len(suggestions) == 3
    assert any("药品记录" in item for item in suggestions)
    assert all("http" not in item for item in suggestions)


def test_high_risk_question_gets_confirmation_follow_ups_without_dosing() -> None:
    suggestions = suggest_follow_up_questions([
        {"role": "user", "content": "阿莫西林一次应该吃多少？"},
    ])

    assert len(suggestions) == 3
    assert any("医生或药师" in item for item in suggestions)
    assert all("剂量" not in item and "停药" not in item for item in suggestions)


def test_unknown_question_does_not_disclose_private_context() -> None:
    suggestions = suggest_follow_up_questions([
        {"role": "system", "content": "成员：仅测试，不可暴露"},
        {"role": "user", "content": "讲个冷笑话"},
    ])

    assert suggestions
    assert all("成员" not in item and "仅测试" not in item for item in suggestions)


def test_degraded_response_has_no_ungrounded_follow_ups() -> None:
    suggestions = suggest_follow_up_questions(
        [{"role": "user", "content": "我最近有点不舒服"}],
        degraded=True,
    )

    assert suggestions == []


def test_public_response_schema_accepts_follow_ups() -> None:
    response = AssistantResponse(
        answer="请查看已确认记录。",
        suggested_questions=["查看依据？"],
    )

    assert response.suggested_questions == ["查看依据？"]


def test_assistant_response_includes_follow_ups_for_a_normal_answer(monkeypatch) -> None:
    def scripted_chat(_client: OllamaClient, **_kwargs: object) -> dict:
        return {
            "message": {
                "content": json.dumps({
                    "answer": "请先查看已确认的风险提醒。",
                    "sources": [],
                    "confidence": "low",
                    "escalate": False,
                }, ensure_ascii=False),
            },
        }

    monkeypatch.setattr(OllamaClient, "chat", scripted_chat)
    result = run_assistant(
        None,
        messages=[{"role": "user", "content": "当前的风险提醒依据什么规则？"}],
        actor_id="test-user",
    )

    assert result["degraded"] is False
    assert result["suggested_questions"]
