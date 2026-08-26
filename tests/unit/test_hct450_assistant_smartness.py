"""HCT-450: 助手回复智能度与编排优化的回归测试。

覆盖五个增量：
1. synthesis 提示词点名本轮可引用的 chunk_id（降低「有卡却 EVIDENCE_REQUIRED」）；
2. 模型漏引用时的一次确定性补正重试；
3. GENERAL 教学问改为可选使用知识库（软通过，不新增失败墙）；
4. 追问建议按 query_type + 是否命中知识差异化；
5. 分流说明缩短为一句人话。

硬边界回归（HCT-448 空库友好、MEDICATION_SAFETY 无证据硬降级、伪造引用拒绝）
由 tests/unit/test_hct430_local_agents.py 与 test_hct403_tool_call.py 继续钉住，
本文件补充「有知识时」的行为。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.config import Settings
from app.local_agents import (
    _classifier_explanation,
    _synthesis_agent,
    run_local_multi_agent,
)
from app.tool_call import suggest_follow_up_questions

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
)

_KNOWLEDGE_FIXTURE = {
    "results": [
        {
            "document_id": "doc-cold-1",
            "chunk_id": "chunk-cold-1",
            "title": "感冒样症状居家照护教学卡",
            "version": "demo-v1",
            "locator": "section:FAQ",
            "text": "可以先了解缓解鼻塞流涕类与解热镇痛类非处方说明书资料的通用注意事项。",
        }
    ]
}


class _ScriptedStreamClient:
    """按脚本逐轮返回回答的假 Ollama 流式客户端。"""

    instances: list[_ScriptedStreamClient] = []

    def __init__(self, *_args, **_kwargs):
        type(self).instances.append(self)
        self.conversations: list[list[dict]] = []

    def chat_stream(self, **kwargs):
        self.conversations.append(list(kwargs["messages"]))
        yield json.dumps(self.script.pop(0), ensure_ascii=False)

    script: list[dict] = []


def _install_scripted_client(monkeypatch, script: list[dict]) -> type:
    client_cls = type(
        "_Client", (_ScriptedStreamClient,), {"script": list(script), "instances": []}
    )
    monkeypatch.setattr("app.local_agents.OllamaClient", client_cls)
    monkeypatch.setattr("app.local_agents.is_loopback_ollama_url", lambda _url: True)
    return client_cls


def _cited_answer() -> dict:
    return {
        "answer": "空调受凉引起的鼻塞可以先看缓解鼻塞流涕类资料，注意过敏史，症状加重要就医。",
        "sources": ["chunk-cold-1"],
        "confidence": "medium",
        "escalate": False,
    }


def _uncited_answer() -> dict:
    return {
        "answer": "空调受凉引起的鼻塞可以先看缓解鼻塞流涕类资料，注意休息补水。",
        "sources": [],
        "confidence": "medium",
        "escalate": False,
    }


# ── 1. 提示词点名可引用 chunk_id ─────────────────────────────────────


def test_synthesis_prompt_enumerates_retrieved_chunks_and_binds_citation(
    monkeypatch,
) -> None:
    client_cls = _install_scripted_client(monkeypatch, [_cited_answer()])

    result = _synthesis_agent(
        messages=[{"role": "user", "content": "夏天吹空调后有点鼻塞，看什么资料？"}],
        query_type="SYMPTOM_MEDICATION",
        database={},
        knowledge=_KNOWLEDGE_FIXTURE,
        external_sources=[],
        model="local-model",
        max_tokens=256,
        temperature=0.1,
        settings=Settings(agent_open_chat=False),
    )

    system_prompt = client_cls.instances[0].conversations[0][0]["content"]
    assert "本轮命中的本地知识片段" in system_prompt
    assert "chunk-cold-1" in system_prompt
    assert "感冒样症状居家照护教学卡" in system_prompt
    assert "原样填入" in system_prompt
    assert result["degraded"] is False
    assert result["citations"][0]["chunk_id"] == "chunk-cold-1"
    assert result["escalate"] is False


# ── 2. 漏引用的一次补正重试 ──────────────────────────────────────────


def test_synthesis_retries_once_when_model_forgets_citation(monkeypatch) -> None:
    client_cls = _install_scripted_client(
        monkeypatch, [_uncited_answer(), _cited_answer()]
    )

    result = _synthesis_agent(
        messages=[{"role": "user", "content": "夏天吹空调后有点鼻塞，看什么资料？"}],
        query_type="SYMPTOM_MEDICATION",
        database={},
        knowledge=_KNOWLEDGE_FIXTURE,
        external_sources=[],
        model="local-model",
        max_tokens=256,
        temperature=0.1,
        settings=Settings(agent_open_chat=False),
    )

    client = client_cls.instances[0]
    assert len(client.conversations) == 2, "one deterministic correction pass"
    correction = client.conversations[1][-1]
    assert correction["role"] == "system"
    assert "sources" in correction["content"]
    assert result["degraded"] is False
    assert result["citations"][0]["chunk_id"] == "chunk-cold-1"


def test_symptom_answer_still_walls_when_citation_missing_after_retry(
    monkeypatch,
) -> None:
    """补正重试失败后，症状用药问题旁边有真实证据却引用不上时，
    仍然如实降级为 EVIDENCE_REQUIRED，而不是放行无引用回答或谎报空库。"""
    client_cls = _install_scripted_client(
        monkeypatch, [_uncited_answer(), _uncited_answer()]
    )

    result = _synthesis_agent(
        messages=[{"role": "user", "content": "夏天吹空调后有点鼻塞，看什么资料？"}],
        query_type="SYMPTOM_MEDICATION",
        database={},
        knowledge=_KNOWLEDGE_FIXTURE,
        external_sources=[],
        model="local-model",
        max_tokens=256,
        temperature=0.1,
        settings=Settings(agent_open_chat=False),
    )

    assert len(client_cls.instances[0].conversations) == 2
    assert result["degraded"] is True
    assert result["degrade_reason"] == "EVIDENCE_REQUIRED"


# ── 3. GENERAL 教学问的可选知识使用 ──────────────────────────────────


def test_general_answer_keeps_uncited_reply_with_optional_knowledge(
    monkeypatch,
) -> None:
    """GENERAL 之前根本不检索知识；现在检索是增益，模型确实没用上片段时
    不能凭空多出一堵 EVIDENCE_REQUIRED 墙。伪造引用仍会被拒绝。"""
    _install_scripted_client(
        monkeypatch,
        [
            {
                "answer": "日常可以规律作息、注意通风，保持记录方便就医时说明。",
                "sources": [],
                "confidence": "medium",
                "escalate": False,
            }
        ]
        * 2,
    )

    result = _synthesis_agent(
        messages=[{"role": "user", "content": "帮我讲讲居家照护的基本习惯"}],
        query_type="GENERAL",
        database={},
        knowledge=_KNOWLEDGE_FIXTURE,
        external_sources=[],
        model="local-model",
        max_tokens=256,
        temperature=0.1,
        settings=Settings(agent_open_chat=False),
    )

    assert result["degraded"] is False
    assert result["citations"] == []
    assert result["sources"] == []


def test_general_answer_can_cite_optional_knowledge(monkeypatch) -> None:
    _install_scripted_client(
        monkeypatch,
        [
            {
                "answer": "可以先看这张教学卡的照护要点：补水休息、通风加湿、做好记录。",
                "sources": ["chunk-cold-1"],
                "confidence": "medium",
                "escalate": False,
            }
        ],
    )

    result = _synthesis_agent(
        messages=[{"role": "user", "content": "居家照护有哪些基本习惯？"}],
        query_type="GENERAL",
        database={},
        knowledge=_KNOWLEDGE_FIXTURE,
        external_sources=[],
        model="local-model",
        max_tokens=256,
        temperature=0.1,
        settings=Settings(agent_open_chat=False),
    )

    assert result["degraded"] is False
    assert result["citations"][0]["chunk_id"] == "chunk-cold-1"


# ── 4. 差异化追问 ────────────────────────────────────────────────────


def test_follow_ups_differ_by_query_type_and_knowledge_hit() -> None:
    messages = [{
        "role": "user",
        "content": "夏天吹空调后有点鼻塞，一般可以了解哪些用药资料？",
    }]

    with_hit = suggest_follow_up_questions(
        messages, query_type="SYMPTOM_MEDICATION", has_citations=True
    )
    without_hit = suggest_follow_up_questions(
        messages, query_type="SYMPTOM_MEDICATION", has_citations=False
    )

    assert with_hit != without_hit
    assert any("过敏史" in item for item in with_hit)
    assert any("就医" in item for item in with_hit)
    assert any("知识库" in item for item in without_hit)
    # 不诱导剂量/停换药决定。
    for item in [*with_hit, *without_hit]:
        assert "剂量" not in item and "停药" not in item

    # 未传 query_type 的旧调用方保持原有关键字梯子。
    legacy = suggest_follow_up_questions(messages)
    assert legacy, "legacy keyword ladder still answers"


# ── 5. 分流说明一句人话 ──────────────────────────────────────────────


def test_default_route_explanation_is_single_human_sentence() -> None:
    default = _classifier_explanation({
        "lexicon": "SYMPTOM_MEDICATION",
        "model": None,
        "merged": "SYMPTOM_MEDICATION",
        "override": None,
        "model_enabled": False,
    })
    assert default == "已按「症状用药资料解释」处理这个问题"
    assert "词表" not in default
    assert "默认" not in default

    override = _classifier_explanation({
        "lexicon": "GENERAL",
        "model": None,
        "merged": "MEDICATION_SAFETY",
        "override": "MEDICATION_SAFETY",
        "model_enabled": False,
    })
    assert "显式覆盖" in override


# ── 验收场景：感冒卡入库 + 引用回答，全链路 ─────────────────────────


class _CooperativeClient:
    """从系统提示中读出点名的 chunk_id 并如实引用的假模型。"""

    def __init__(self, *_args, **_kwargs):
        pass

    def chat_stream(self, **kwargs):
        system = kwargs["messages"][0]["content"]
        marker = system.find("本轮命中的本地知识片段")
        assert marker >= 0, "citation enumeration must be present"
        chunk_id = _UUID_RE.search(system[marker:])
        assert chunk_id is not None
        yield json.dumps(
            {
                "answer": (
                    "夏天空调房里受凉确实容易鼻塞。可以先了解缓解鼻塞流涕类和"
                    "解热镇痛类非处方说明书的通用注意事项；生活上避免冷风直吹、"
                    "多补水休息。查资料时记得结合家里的过敏史，症状加重或持续"
                    "不缓解就尽快就医。"
                ),
                "sources": [chunk_id.group(0)],
                "confidence": "medium",
                "escalate": False,
            },
            ensure_ascii=False,
        )


def test_summer_ac_stuffy_nose_with_cold_card_returns_cited_answer(
    monkeypatch, db_session
) -> None:
    """验收 1：感冒样症状卡入库后，鼻塞类问题命中检索、回答引用真实片段、
    不空洞、不升级。"""
    from app.knowledge import add_document

    card_path = (
        Path(__file__).resolve().parents[2]
        / "docs" / "demo" / "感冒样症状居家照护教学卡.md"
    )
    document = add_document(
        db_session,
        title="感冒样症状居家照护教学卡",
        content=card_path.read_text(encoding="utf-8"),
        source="internal-demo",
        created_by="demo-parent",
        version="demo-v1",
    )
    db_session.commit()

    monkeypatch.setattr("app.local_agents.OllamaClient", _CooperativeClient)
    monkeypatch.setattr("app.local_agents.is_loopback_ollama_url", lambda _url: True)

    result = run_local_multi_agent(
        db_session,
        messages=[{
            "role": "user",
            "content": "夏天吹空调后有点鼻塞，一般可以了解哪些用药资料？",
        }],
        actor_id="demo-parent",
    )

    assert result["query_type"] == "SYMPTOM_MEDICATION"
    assert result["degraded"] is False
    assert result["escalate"] is False
    assert result["citations"], "must bind a real retrieved citation"
    assert result["citations"][0]["document_id"] == document.id
    assert "感冒样症状居家照护教学卡" in result["citations"][0]["document_title"]
    # 非空洞模板：正文回应了处境并给出资料要点，末尾追加教学提醒。
    assert "鼻塞" in result["answer"]
    assert "教学提醒" in result["answer"]
    assert "缺少可核验的本地知识引用" not in result["answer"]
    # 差异化追问：命中知识后引导过敏史/就医边界。
    assert any("过敏史" in item for item in result["suggested_questions"])
    statuses = {trace["agent_id"]: trace["status"] for trace in result["agent_trace"]}
    assert statuses["knowledge"] == "completed"
    assert statuses["synthesis"] == "completed"
    # 分流说明是一句人话，不再暴露双通道术语。
    assert result["route_explanation"] == "已按「症状用药资料解释」处理这个问题"


def test_greeting_fast_path_untouched(monkeypatch) -> None:
    """问候仍走快路径：不因 GENERAL 检索开关而误触模型或数据库。"""
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("greeting must not call model or tools")

    monkeypatch.setattr("app.local_agents.OllamaClient", _forbidden)
    monkeypatch.setattr("app.local_agents.execute_whitelisted_tool", _forbidden)

    result = run_local_multi_agent(
        None,
        messages=[{"role": "user", "content": "你好"}],
        actor_id="actor",
    )

    assert result["degraded"] is False
    statuses = {trace["agent_id"]: trace["status"] for trace in result["agent_trace"]}
    assert statuses["knowledge"] == "skipped"
