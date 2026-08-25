"""HCT-403: Tests for Ollama tool calling — whitelist, schema, medical safety, degrade."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.knowledge import KnowledgeChunk, add_document
from app.models import CareAuthorization, HealthEvent, Household, Member
from app.tool_call import (
    HealthAssistantOutput,
    OllamaClient,
    ToolDefinition,
    _check_medical_boundary,
    _contains_external_links,
    _parse_loose_output,
    build_degrade_response,
    classify_question,
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

    def test_chat_does_not_retry_deterministic_client_error(self, monkeypatch):
        """A 404 (e.g. unknown model name) must fail fast, not retry."""
        import httpx

        calls = {"count": 0}

        def not_found(_self, url, **_kwargs):
            calls["count"] += 1
            request = httpx.Request("POST", url)
            return httpx.Response(404, request=request, json={"error": "model not found"})

        monkeypatch.setattr("app.tool_call.httpx.Client.post", not_found)
        monkeypatch.setattr("app.tool_call.time.sleep", lambda _seconds: None)
        client = OllamaClient()
        with pytest.raises(RuntimeError, match="OLLAMA_UNAVAILABLE: HTTP_404"):
            client.chat(
                model="no-such-model",
                messages=[{"role": "user", "content": "hello"}],
            )
        assert calls["count"] == 1

    def test_chat_still_retries_server_errors(self, monkeypatch):
        """5xx may be transient; the existing retry budget still applies."""
        import httpx

        from app.tool_call import MAX_RETRIES

        calls = {"count": 0}

        def server_error(_self, url, **_kwargs):
            calls["count"] += 1
            request = httpx.Request("POST", url)
            return httpx.Response(503, request=request, json={"error": "loading"})

        monkeypatch.setattr("app.tool_call.httpx.Client.post", server_error)
        monkeypatch.setattr("app.tool_call.time.sleep", lambda _seconds: None)
        client = OllamaClient()
        with pytest.raises(RuntimeError, match="OLLAMA_UNAVAILABLE: HTTP_503"):
            client.chat(
                model="llama3.2:3b",
                messages=[{"role": "user", "content": "hello"}],
            )
        assert calls["count"] == MAX_RETRIES + 1


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

    unbound_override = execute_whitelisted_tool(
        db_session,
        name="retrieve_knowledge",
        arguments={"query": "合成照护证据", "household_id": "house-a"},
        actor_id="owner-a",
        household_id=None,
        member_id=None,
    )
    assert unbound_override["error"] == "TOOL_SCOPE_DENIED"
    assert unbound_override["results"] == []

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
    assert len(result["citations"]) == 1
    citation = result["citations"][0]
    assert citation["document_id"] == document.id
    assert citation["version"] == "e2e-v1"
    assert citation["chunk_id"] == chunk.id
    assert citation["document_title"] == "Synthetic care evidence"
    assert citation["text"] == chunk.text
    assert citation["locator"] == chunk.locator
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


def _add_confirmed_medication_fixture(
    db_session: Session,
) -> tuple[Household, Member, list[HealthEvent]]:
    household = Household(name="Assistant household", created_by="assistant-owner")
    db_session.add(household)
    db_session.flush()
    member = Member(
        household_id=household.id,
        display_name="Synthetic member",
        role="SELF",
    )
    db_session.add(member)
    db_session.flush()
    events = [
        HealthEvent(
            household_id=household.id,
            member_id=member.id,
            sequence_no=index,
            event_type="medication_added",
            source="VISION_REVIEW",
            confirmation_status="CONFIRMED",
            payload={
                "drug": drug,
                "ingredient": ingredient,
                "candidate_id": (
                    "rec-amoxicillin-cn" if drug == "阿莫西林" else "rec-ibuprofen-en"
                ),
                "interaction_warnings": (
                    [
                        {
                            "with_record_id": "rec-ibuprofen-en",
                            "level": "INFO",
                            "message": (
                                "本地主数据要求核对当前医嘱和说明书；系统不判断是否可以同用。"
                            ),
                        }
                    ]
                    if drug == "阿莫西林"
                    else []
                ),
                "private": "must-not-leak",
            },
            evidence={"raw": "must-not-leak"},
            created_by="assistant-owner",
            confirmed_by="assistant-owner",
            correlation_id=f"assistant-{index}",
            schema_version=1,
        )
        for index, (drug, ingredient) in enumerate(
            (("阿莫西林", "阿莫西林"), ("布洛芬", "布洛芬")),
            start=1,
        )
    ]
    pending = HealthEvent(
        household_id=household.id,
        member_id=member.id,
        sequence_no=3,
        event_type="medication_added",
        source="VISION_REVIEW",
        confirmation_status="PENDING",
        payload={"drug": "未确认药品"},
        evidence={},
        created_by="assistant-owner",
        correlation_id="assistant-pending",
        schema_version=1,
    )
    db_session.add_all([*events, pending])
    db_session.commit()
    return household, member, events


def test_member_tools_return_confirmed_allowlisted_facts_and_rules(db_session: Session) -> None:
    household, member, events = _add_confirmed_medication_fixture(db_session)
    common = {
        "session": db_session,
        "actor_id": "assistant-owner",
        "household_id": household.id,
        "member_id": member.id,
    }

    event_result = execute_whitelisted_tool(
        name="get_health_events",
        arguments={},
        **common,
    )
    assert event_result["total"] == 2
    assert {item["event_id"] for item in event_result["events"]} == {event.id for event in events}
    assert all("private" not in item["fields"] for item in event_result["events"])

    state_result = execute_whitelisted_tool(
        name="get_member_state",
        arguments={},
        **common,
    )
    assert {item["name"] for item in state_result["state"]["drugs"]} == {"阿莫西林", "布洛芬"}
    assert set(state_result["sources"]) == {event.id for event in events}

    rules_result = execute_whitelisted_tool(
        name="get_applied_rules",
        arguments={},
        **common,
    )
    assert "interaction" in {item["rule_id"] for item in rules_result["rules"]}
    assert "interaction" in rules_result["sources"]

    risk_result = execute_whitelisted_tool(
        name="get_risk_alerts",
        arguments={},
        **common,
    )
    assert risk_result["alerts"]
    assert risk_result["ruleset_version"]


def test_member_tools_reject_cross_member_scope(db_session: Session) -> None:
    household, member, _events = _add_confirmed_medication_fixture(db_session)
    other = Member(household_id=household.id, display_name="Other member", role="DEPENDENT")
    db_session.add(other)
    db_session.commit()

    result = execute_whitelisted_tool(
        db_session,
        name="get_health_events",
        arguments={"member_id": other.id},
        actor_id="assistant-owner",
        household_id=household.id,
        member_id=member.id,
    )
    assert result["error"] == "TOOL_SCOPE_DENIED"
    assert result.get("events", []) == []


def test_member_tools_require_caregiver_purpose(db_session: Session) -> None:
    household, member, _events = _add_confirmed_medication_fixture(db_session)
    db_session.add(
        CareAuthorization(
            household_id=household.id,
            member_id=member.id,
            grantor_actor_id="assistant-owner",
            grantee_actor_id="assistant-caregiver",
            data_fields=["health_events"],
            actions=["READ_EVENTS"],
            purpose="family-care",
            valid_from=datetime.now(UTC) - timedelta(minutes=1),
            valid_until=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    db_session.commit()

    denied = execute_whitelisted_tool(
        db_session,
        name="get_member_state",
        arguments={},
        actor_id="assistant-caregiver",
        household_id=household.id,
        member_id=member.id,
    )
    assert denied["error"] == "TOOL_SCOPE_DENIED"

    allowed = execute_whitelisted_tool(
        db_session,
        name="get_member_state",
        arguments={},
        actor_id="assistant-caregiver",
        household_id=household.id,
        member_id=member.id,
        access_purpose="family-care",
    )
    assert len(allowed["state"]["drugs"]) == 2


def test_question_classifier_marks_medication_safety() -> None:
    assert classify_question("阿莫西林能不能和刚才扫描的布洛芬一起吃？") == "MEDICATION_SAFETY"


@pytest.mark.parametrize(
    "query",
    [
        "这个药的剂量是多少？",
        "阿莫西林应该怎么吃？",
        "我今天漏服了一次降压药，需要补服吗？",
        "老人误服了两粒药怎么办？",
        "吃过量了会怎么样？",
    ],
)
def test_question_classifier_marks_bare_dosage_terms_as_medication_safety(query) -> None:
    """Dosage / missed-dose / overdose questions must require reviewed knowledge.

    Without this route, a bare "剂量" question fell through to GENERAL and
    the citation requirement (EVIDENCE_REQUIRED without reviewed knowledge)
    did not apply.
    """
    assert classify_question(query) == "MEDICATION_SAFETY"


def test_medication_safety_requires_reviewed_knowledge_and_exposes_risk_notice(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    household, member, _events = _add_confirmed_medication_fixture(db_session)
    document = add_document(
        db_session,
        title="Synthetic medication interaction card",
        content="合成审核知识：阿莫西林与布洛芬的同服问题必须由医生或药师结合个体情况确认。",
        source="hct403-synthetic-approved",
        created_by="assistant-owner",
        version="approved-v1",
        permission_scope={"created_by": "assistant-owner"},
    )
    db_session.commit()
    chunk = db_session.query(KnowledgeChunk).filter_by(document_id=document.id).one()

    def scripted_chat(_self: OllamaClient, **kwargs: object) -> dict:
        messages = kwargs["messages"]  # type: ignore[index]
        tool_names = [
            message.get("name")
            for message in messages
            if isinstance(message, dict) and message.get("role") == "tool"
        ]
        if "get_member_state" not in tool_names:
            call = "get_member_state"
            arguments = {}
        elif "retrieve_knowledge" not in tool_names:
            call = "retrieve_knowledge"
            arguments = {"query": "阿莫西林 布洛芬 同服"}
        else:
            payload = json.loads(messages[-1]["content"])
            cited = payload["results"][0]["chunk_id"]
            return {
                "message": {
                    "content": json.dumps({
                        "answer": "本地已审核资料要求结合个人情况核对，不能仅凭助手决定是否同服。",
                        "sources": [cited],
                        "confidence": "medium",
                        "escalate": False,
                    }, ensure_ascii=False),
                },
            }
        return {
            "message": {
                "content": "",
                "tool_calls": [{"function": {"name": call, "arguments": arguments}}],
            },
        }

    monkeypatch.setattr(OllamaClient, "chat", scripted_chat)
    result = run_assistant(
        db_session,
        messages=[{
            "role": "user",
            "content": "阿莫西林能不能和刚才扫描的布洛芬一起吃？",
        }],
        actor_id="assistant-owner",
        household_id=household.id,
        member_id=member.id,
    )
    assert result["degraded"] is False
    assert result["query_type"] == "MEDICATION_SAFETY"
    assert result["risk_notice"] and "医生或药师" in result["risk_notice"]
    assert result["sources"] == [chunk.id]
    assert result["citations"][0]["version"] == "approved-v1"


def test_medication_safety_without_reviewed_knowledge_degrades(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    household, member, _events = _add_confirmed_medication_fixture(db_session)

    def scripted_chat(_self: OllamaClient, **kwargs: object) -> dict:
        messages = kwargs["messages"]  # type: ignore[index]
        tool_names = [
            message.get("name")
            for message in messages
            if isinstance(message, dict) and message.get("role") == "tool"
        ]
        if "get_member_state" not in tool_names:
            call = "get_member_state"
            arguments = {}
        elif "retrieve_knowledge" not in tool_names:
            call = "retrieve_knowledge"
            arguments = {"query": "阿莫西林 布洛芬 同服"}
        else:
            return {
                "message": {
                    "content": json.dumps({
                        "answer": "我无法判断这两种药品是否可以同服，请咨询医生或药师。",
                        "sources": [],
                        "confidence": "low",
                        "escalate": True,
                    }, ensure_ascii=False),
                },
            }
        return {
            "message": {
                "content": "",
                "tool_calls": [{"function": {"name": call, "arguments": arguments}}],
            },
        }

    monkeypatch.setattr(OllamaClient, "chat", scripted_chat)
    result = run_assistant(
        db_session,
        messages=[{"role": "user", "content": "阿莫西林和布洛芬能不能一起吃？"}],
        actor_id="assistant-owner",
        household_id=household.id,
        member_id=member.id,
    )
    assert result["degraded"] is True
    assert result["degrade_reason"] in {"NO_AUTHORISED_DOCUMENTS", "EVIDENCE_REQUIRED"}
    assert result["query_type"] == "MEDICATION_SAFETY"
    assert result["sources"] == []
