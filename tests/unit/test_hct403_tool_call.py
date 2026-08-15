"""HCT-403: Tests for Ollama tool calling — whitelist, schema, medical safety, degrade."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.knowledge import KnowledgeChunk, add_document
from app.tool_call import (
    HealthAssistantOutput,
    OllamaClient,
    ToolDefinition,
    _check_medical_boundary,
    _contains_external_links,
    _parse_loose_output,
    build_degrade_response,
    execute_whitelisted_tool,
    extract_tool_calls,
    filter_claimed_citations,
    get_approved_tools,
    get_tool,
    is_tool_allowed,
    run_assistant,
)

# ── Tool whitelist ────────────────────────────────────────────────────


class TestToolWhitelist:
    def test_approved_tools_registered(self):
        tools = get_approved_tools()
        names = {t.name for t in tools}
        assert "retrieve_knowledge" in names
        assert "get_health_events" in names
        assert "get_member_state" in names
        assert "get_applied_rules" in names
        assert "get_risk_alerts" in names
        assert "get_document_metadata" in names

    def test_unknown_tool_rejected(self):
        assert is_tool_allowed("evil_tool") is False

    def test_get_unknown_tool_raises(self):
        with pytest.raises(ValueError, match="not in the approved whitelist"):
            get_tool("drop_table")

    def test_get_known_tool(self):
        tool = get_tool("retrieve_knowledge")
        assert isinstance(tool, ToolDefinition)
        assert tool.name == "retrieve_knowledge"

    def test_tool_has_description(self):
        for tool in get_approved_tools():
            assert tool.description, f"Tool {tool.name} missing description"

    def test_tool_params_have_types(self):
        for tool in get_approved_tools():
            for key, schema in tool.params.items():
                assert schema.type, f"{tool.name}.{key} missing type"

    def test_run_assistant_sends_ollama_function_tool_schema(self, monkeypatch):
        captured: dict[str, object] = {}

        def scripted_chat(_client: OllamaClient, **kwargs: object) -> dict:
            captured["tools"] = kwargs["tools"]
            return {
                "message": {
                    "content": json.dumps(
                        {
                            "answer": "演示问候。",
                            "sources": [],
                            "confidence": "low",
                            "escalate": False,
                        },
                        ensure_ascii=False,
                    )
                }
            }

        monkeypatch.setattr(OllamaClient, "chat", scripted_chat)
        result = run_assistant(
            None,
            messages=[{"role": "user", "content": "请问候我"}],
            actor_id="test-user",
        )

        assert result["degraded"] is False
        tools = captured["tools"]
        assert isinstance(tools, list)
        retrieve = next(tool for tool in tools if tool["function"]["name"] == "retrieve_knowledge")
        assert retrieve["type"] == "function"
        assert retrieve["function"]["description"]
        parameters = retrieve["function"]["parameters"]
        assert parameters["type"] == "object"
        assert parameters["properties"]["query"]["type"] == "string"
        assert parameters["properties"]["top_k"]["default"] == 5


# ── Parameter validation ──────────────────────────────────────────────


class TestParameterValidation:
    def test_valid_args(self):
        tool = get_tool("retrieve_knowledge")
        result = tool.validate_args({"query": "阿莫西林", "top_k": 3})
        assert result["query"] == "阿莫西林"
        assert result["top_k"] == 3

    def test_invalid_type_coerced_gracefully(self):
        """top_k accepts string integers without error (no enum constraint)."""
        tool = get_tool("retrieve_knowledge")
        result = tool.validate_args({"query": "test", "top_k": "3"})
        assert result["top_k"] == "3"

    def test_missing_optional_uses_default(self):
        tool = get_tool("retrieve_knowledge")
        result = tool.validate_args({"query": "test"})
        assert result.get("top_k") is not None


# ── Medical safety ────────────────────────────────────────────────────


class TestMedicalSafety:
    def test_diagnosis_keyword_blocked(self):
        violations = _check_medical_boundary("建议诊断结果为高血压")
        assert len(violations) > 0

    def test_prescription_keyword_blocked(self):
        violations = _check_medical_boundary("建议处方：阿莫西林 0.5g")
        assert len(violations) > 0

    def test_dosage_decision_blocked(self):
        violations = _check_medical_boundary("你应当停药并换药")
        assert len(violations) > 0

    def test_external_link_detected(self):
        assert _contains_external_links("请访问 https://example.com") is True

    def test_no_external_link_passes(self):
        assert _contains_external_links("这是本地文档内容") is False

    def test_clean_text_no_violations(self):
        violations = _check_medical_boundary("您可以查看已保存的健康记录")
        assert len(violations) == 0


# ── Structured output ─────────────────────────────────────────────────


class TestStructuredOutput:
    def test_valid_json_output(self):
        raw = json.dumps({
            "answer": "阿莫西林是一种青霉素类抗生素",
            "sources": ["doc-123"],
            "confidence": "high",
            "escalate": False,
        })
        parsed = HealthAssistantOutput.model_validate_json(raw)
        assert "青霉素" in parsed.answer
        assert parsed.confidence == "high"
        assert parsed.escalate is False

    def test_invalid_json_falls_back(self):
        raw = "This is not valid JSON output"
        with pytest.raises(ValidationError):
            HealthAssistantOutput.model_validate_json(raw)

    def test_loose_parse_extracts_answer(self):
        text = 'Some text before "answer": "这是回答内容" and after'
        result = _parse_loose_output(text)
        assert "这是回答内容" in result.answer

    def test_loose_parse_empty(self):
        result = _parse_loose_output("no json here at all")
        assert result.answer  # returns raw text as fallback


# ── Degrade response ──────────────────────────────────────────────────


class TestDegradeResponse:
    def test_model_unavailable(self):
        r = build_degrade_response("MODEL_UNAVAILABLE")
        assert r.degraded is True
        assert r.reason == "MODEL_UNAVAILABLE"
        assert "助手服务" in r.answer

    def test_medical_boundary_violation(self):
        r = build_degrade_response("MEDICAL_BOUNDARY_VIOLATION")
        assert r.degraded is True
        assert r.escalate is True
        assert "医疗建议" in r.answer or "医务人员" in r.answer

    def test_schema_validation_failed(self):
        r = build_degrade_response("SCHEMA_VALIDATION_FAILED")
        assert r.degraded is True
        assert "无法处理" in r.answer

    def test_external_link_detected(self):
        r = build_degrade_response("EXTERNAL_LINK_DETECTED")
        assert r.degraded is True
        assert r.reason == "EXTERNAL_LINK_DETECTED"


# ── Ollama client ─────────────────────────────────────────────────────


class TestOllamaClient:
    def test_is_available_default_false(self, monkeypatch):
        def unavailable(*_args, **_kwargs):
            raise OSError("synthetic connection refused")

        monkeypatch.setattr("app.tool_call.httpx.Client.get", unavailable)
        client = OllamaClient()
        assert client.is_available() is False

    def test_health_check_false_when_no_ollama(self, monkeypatch):
        def unavailable(*_args, **_kwargs):
            raise OSError("synthetic connection refused")

        monkeypatch.setattr("app.tool_call.httpx.Client.get", unavailable)
        client = OllamaClient("http://localhost:11434")
        assert client.health_check() is False

    def test_chat_raises_when_unavailable(self, monkeypatch):
        def unavailable(*_args, **_kwargs):
            raise OSError("synthetic connection refused")

        monkeypatch.setattr("app.tool_call.httpx.Client.post", unavailable)
        monkeypatch.setattr("app.tool_call.time.sleep", lambda _seconds: None)
        client = OllamaClient()
        with pytest.raises(RuntimeError, match="OLLAMA_UNAVAILABLE"):
            client.chat(
                model="llama3.2:3b",
                messages=[{"role": "user", "content": "hello"}],
            )


# ── run_assistant integration ────────────────────────────────────────


class TestRunAssistant:
    def test_degrade_when_ollama_unavailable(self, monkeypatch):
        def unavailable(*_args, **_kwargs):
            raise RuntimeError("OLLAMA_UNAVAILABLE: synthetic")

        monkeypatch.setattr(OllamaClient, "chat", unavailable)
        result = run_assistant(
            None,
            messages=[{"role": "user", "content": "test"}],
            actor_id="test-user",
        )
        assert result["degraded"] is True
        assert result["degrade_reason"] == "MODEL_UNAVAILABLE"
        assert result["answer"]  # non-empty degrade message

    @pytest.mark.parametrize("label", ["hello", "healthy", "cannot_answer", "REFUSE"])
    def test_degrade_when_model_returns_classification_label(self, monkeypatch, label):
        def label_only(*_args, **_kwargs):
            return {
                "message": {
                    "content": json.dumps(
                        {
                            "answer": label,
                            "sources": [],
                            "confidence": "low",
                            "escalate": False,
                        }
                    )
                }
            }

        monkeypatch.setattr(OllamaClient, "chat", label_only)
        result = run_assistant(
            None,
            messages=[{"role": "user", "content": "测试问题"}],
            actor_id="test-user",
        )

        assert result["degraded"] is True
        assert result["degrade_reason"] == "SCHEMA_VALIDATION_FAILED"
        assert label not in result["answer"]


def test_extract_tool_calls_normalizes_openai_and_ollama_shapes() -> None:
    calls = extract_tool_calls(
        {
            "message": {
                "tool_calls": [
                    {
                        "function": {
                            "name": "retrieve_knowledge",
                            "arguments": json.dumps({"query": "合成照护证据"}),
                        }
                    },
                    {"name": "get_document_metadata", "arguments": {"document_id": "doc-1"}},
                ]
            }
        }
    )
    assert calls == [
        {"name": "retrieve_knowledge", "arguments": {"query": "合成照护证据"}},
        {"name": "get_document_metadata", "arguments": {"document_id": "doc-1"}},
    ]


def test_filter_claimed_citations_keeps_only_retrieved_chunks() -> None:
    allowed = [
        {
            "document_id": "doc-a",
            "version": "e2e-v1",
            "chunk_id": "chunk-a",
        }
    ]
    matched = filter_claimed_citations(["chunk-a", "forged-source"], allowed)
    assert matched == allowed
    assert filter_claimed_citations(["forged-source"], allowed) == []


def test_retrieve_knowledge_tool_binds_request_scope_and_rejects_override(
    db_session: Session,
) -> None:
    document = add_document(
        db_session,
        title="Synthetic care evidence",
        content="合成照护证据要求先核对已确认事件，并联系有资质的医务人员。",
        source="hct405-synthetic",
        created_by="owner-a",
        version="e2e-v1",
        permission_scope={"created_by": "owner-a", "household_ids": ["house-a"]},
    )
    db_session.commit()

    denied = execute_whitelisted_tool(
        db_session,
        name="retrieve_knowledge",
        arguments={"query": "合成照护证据", "household_id": "house-b"},
        actor_id="owner-a",
        household_id="house-a",
        member_id=None,
    )
    assert denied["error"] == "TOOL_SCOPE_DENIED"
    assert denied["results"] == []

    retrieved = execute_whitelisted_tool(
        db_session,
        name="retrieve_knowledge",
        arguments={"query": "合成照护证据"},
        actor_id="owner-a",
        household_id="house-a",
        member_id=None,
    )
    assert retrieved["total"] == 1
    assert retrieved["results"][0]["document_id"] == document.id
    chunk = db_session.query(KnowledgeChunk).filter_by(document_id=document.id).one()
    assert retrieved["results"][0]["chunk_id"] == chunk.id


def test_unknown_tool_is_not_executed(db_session: Session) -> None:
    result = execute_whitelisted_tool(
        db_session,
        name="drop_table",
        arguments={},
        actor_id="owner-a",
        household_id=None,
        member_id=None,
    )
    assert result == {"error": "TOOL_NOT_ALLOWED"}


def test_run_assistant_requires_live_tool_citations(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = add_document(
        db_session,
        title="Synthetic care evidence",
        content="合成照护证据要求先核对已确认事件，并联系有资质的医务人员。",
        source="hct405-synthetic",
        created_by="owner-a",
        version="e2e-v1",
        permission_scope={"created_by": "owner-a"},
    )
    db_session.commit()
    chunk = db_session.query(KnowledgeChunk).filter_by(document_id=document.id).one()

    def scripted_chat(_self: OllamaClient, **kwargs: object) -> dict:
        messages = kwargs["messages"]  # type: ignore[index]
        has_tool_result = any(
            isinstance(message, dict) and message.get("role") == "tool"
            for message in messages
        )
        if not has_tool_result:
            return {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "retrieve_knowledge",
                                "arguments": {"query": "合成照护证据"},
                            }
                        }
                    ],
                }
            }
        payload = json.loads(messages[-1]["content"])
        cited = payload["results"][0]["chunk_id"]
        return {
            "message": {
                "content": json.dumps(
                    {
                        "answer": "合成照护证据要求先核对已确认事件。",
                        "sources": [cited],
                        "confidence": "medium",
                        "escalate": False,
                    },
                    ensure_ascii=False,
                )
            }
        }

    monkeypatch.setattr(OllamaClient, "chat", scripted_chat)
    result = run_assistant(
        db_session,
        messages=[{"role": "user", "content": "总结合成照护证据"}],
        actor_id="owner-a",
    )
    assert result["degraded"] is False
    assert result["sources"] == [chunk.id]
    assert result["citations"] == [
        {
            "document_id": document.id,
            "version": "e2e-v1",
            "chunk_id": chunk.id,
        }
    ]
    assert result["route"] == "EVIDENCE_REQUIRED"


def test_run_assistant_rejects_fabricated_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fabricated(_self: OllamaClient, **_kwargs: object) -> dict:
        return {
            "message": {
                "content": json.dumps(
                    {
                        "answer": "合成照护证据已经核对完成。",
                        "sources": ["forged-chunk"],
                        "confidence": "high",
                        "escalate": False,
                    },
                    ensure_ascii=False,
                )
            }
        }

    monkeypatch.setattr(OllamaClient, "chat", fabricated)
    result = run_assistant(
        None,
        messages=[{"role": "user", "content": "总结合成照护证据"}],
        actor_id="owner-a",
    )
    assert result["degraded"] is True
    assert result["degrade_reason"] == "CITATION_NOT_FOUND"
    assert result["citations"] == []
    assert result["route"] == "EVIDENCE_REQUIRED"
