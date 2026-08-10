"""HCT-403: Tests for Ollama tool calling — whitelist, schema, medical safety, degrade."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.tool_call import (
    HealthAssistantOutput,
    OllamaClient,
    ToolDefinition,
    _check_medical_boundary,
    _contains_external_links,
    _parse_loose_output,
    build_degrade_response,
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


# ── Parameter validation ──────────────────────────────────────────────


class TestParameterValidation:
    def test_valid_args(self):
        tool = get_tool("retrieve_knowledge")
        result = tool.validate_args({"query": "阿莫西林", "top_k": 3})
        assert result["query"] == "阿莫西林"
        assert result["top_k"] == 3

    def test_invalid_enum_value(self):
        tool = get_tool("retrieve_knowledge")
        with pytest.raises(ValueError, match="Invalid enum"):
            tool.validate_args({"query": "test", "top_k": 999})

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
        assert "assistant service temporarily unavailable" in r.answer.lower()

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
    def test_is_available_default_false(self):
        client = OllamaClient()
        # In test environment without Ollama, should return False
        assert client.is_available() is False

    def test_health_check_false_when_no_ollama(self):
        client = OllamaClient("http://localhost:11434")
        assert client.health_check() is False

    def test_chat_raises_when_unavailable(self):
        client = OllamaClient()
        with pytest.raises(RuntimeError, match="OLLAMA_UNAVAILABLE"):
            client.chat(
                model="llama3.2:3b",
                messages=[{"role": "user", "content": "hello"}],
            )


# ── run_assistant integration ────────────────────────────────────────


class TestRunAssistant:
    def test_degrade_when_ollama_unavailable(self):
        result = run_assistant(
            None,
            messages=[{"role": "user", "content": "test"}],
            actor_id="test-user",
        )
        assert result["degraded"] is True
        assert result["degrade_reason"] == "MODEL_UNAVAILABLE"
        assert result["answer"]  # non-empty degrade message
