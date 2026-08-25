"""HCT-430: local agent graph, redaction and controlled web-search tests."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.egress_guard import is_web_search_egress_allowed
from app.local_agents import (
    _database_agent,
    _knowledge_agent,
    _web_search_agent,
    get_agent_catalog,
    plan_agent_execution,
    redact_web_query,
    run_local_multi_agent,
)
from app.search_providers import parse_search_results


def test_knowledge_agent_reports_no_hit_as_completed(db_session) -> None:
    """A no-hit retrieval is a normal outcome, not a blocked pipeline step."""
    from app.knowledge import add_document

    add_document(
        db_session,
        title="演示知识",
        content="阿莫西林 说明书 用法用量",
        source="synthetic-local",
        created_by="u1",
    )
    db_session.commit()

    result, trace = _knowledge_agent(
        db_session,
        query="天气温度",
        actor_id="u1",
        household_id=None,
        member_id=None,
        access_purpose=None,
    )

    assert result.get("error") == "NO_RELEVANT_RESULTS"
    assert trace["status"] == "completed"
    assert "暂无" in trace["summary"]


def test_knowledge_agent_reports_permission_denial_as_blocked(db_session) -> None:
    from app.knowledge import add_document

    add_document(
        db_session,
        title="他人私有知识",
        content="阿莫西林 说明书 用法用量",
        source="synthetic-local",
        created_by="someone-else",
        permission_scope={"created_by": "someone-else"},
    )
    db_session.commit()

    result, trace = _knowledge_agent(
        db_session,
        query="阿莫西林 用法",
        actor_id="u1",
        household_id=None,
        member_id=None,
        access_purpose=None,
    )

    assert result.get("error") == "NO_AUTHORISED_DOCUMENTS"
    assert trace["status"] == "blocked"


def test_web_query_redacts_identity_values_and_ids() -> None:
    query = "请查 member_id=member-secret，13812345678 的布洛芬能否同服？"
    redacted = redact_web_query(query, ["member-secret", "household-secret"])

    assert "member-secret" not in redacted
    assert "13812345678" not in redacted
    assert "布洛芬" in redacted
    assert "张三" not in redact_web_query("张三的用药记录", ["张三"])


def test_search_html_parser_returns_external_results() -> None:
    body = (
        '<a class="result__a" href="https://example.com/a">标题一</a>'
        '<div class="result__snippet">摘要一</div>'
        '<a class="result__a" href="https://example.org/b">标题二</a>'
        '<div class="result__snippet">摘要二</div>'
    )

    results = parse_search_results(body)

    assert [item["url"] for item in results] == [
        "https://example.com/a",
        "https://example.org/b",
    ]
    assert results[0]["source"] == "external_web_search"


def test_web_search_requires_request_opt_in() -> None:
    results, trace, safe_query = _web_search_agent(
        "布洛芬注意事项",
        sensitive_values=[],
        allow_network_search=False,
        settings=Settings(
            agent_web_search_enabled=True,
            agent_web_search_allowed_domains="example.com",
            agent_web_search_url="https://example.com/search",
        ),
    )

    assert results == []
    assert trace["status"] == "skipped"
    assert trace["network_used"] is False
    assert safe_query is None


def test_web_search_egress_requires_https_and_configured_host() -> None:
    settings = Settings(
        agent_web_search_enabled=True,
        agent_web_search_allowed_domains="example.com",
        agent_web_search_url="https://example.com/search",
    )

    assert is_web_search_egress_allowed("https://example.com/search", settings) is True
    assert is_web_search_egress_allowed("http://example.com/search", settings) is False
    assert is_web_search_egress_allowed("https://not-allowlisted.example/search", settings) is False


def test_web_search_uses_redacted_query_and_allowlist(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_execute(query: str, *, settings: Settings):
        captured["query"] = query
        captured["settings"] = settings
        return [{
            "title": "参考",
            "url": "https://example.com/a",
            "snippet": "摘要",
            "domain": "example.com",
            "source": "external_web_search",
        }]

    monkeypatch.setattr("app.local_agents.execute_web_search", fake_execute)
    results, trace, safe_query = _web_search_agent(
        "member_id=member-secret 布洛芬和 13812345678",
        sensitive_values=["member-secret"],
        allow_network_search=True,
        settings=Settings(
            agent_web_search_enabled=True,
            agent_web_search_allowed_domains="example.com",
            agent_web_search_url="https://example.com/search",
        ),
    )

    assert len(results) == 1
    assert trace["status"] == "completed"
    assert trace["local"] is True
    assert trace["network_used"] is True
    assert safe_query is not None
    assert "member-secret" not in safe_query
    assert "13812345678" not in safe_query
    assert captured["settings"].agent_web_search_url == "https://example.com/search"


def test_database_agent_only_uses_approved_read_tools(monkeypatch) -> None:
    calls: list[str] = []

    def fake_tool(session, *, name, **kwargs):
        calls.append(name)
        return {"sources": [name], "state": {}, "events": [], "rules": [], "alerts": []}

    monkeypatch.setattr("app.local_agents.execute_whitelisted_tool", fake_tool)
    facts, trace = _database_agent(
        object(),
        query="布洛芬和阿莫西林能否同服？",
        query_type="MEDICATION_SAFETY",
        actor_id="actor",
        household_id="household",
        member_id="member",
        access_purpose="assistant",
    )

    assert set(calls) == {"get_member_state", "get_health_events"}
    assert set(facts) == set(calls)
    assert trace["local"] is True
    assert trace["status"] == "completed"


def test_agent_catalog_declares_all_workers_local() -> None:
    catalog = get_agent_catalog(Settings())

    assert catalog["all_agents_local"] is True
    assert catalog["ollama_local_only"] is True
    assert all(item["local"] is True for item in catalog["agents"])


def test_agent_catalog_reports_web_search_readiness() -> None:
    disabled = get_agent_catalog(Settings())
    assert disabled["web_search_enabled"] is False
    assert disabled["web_search_ready"] is False

    ready = get_agent_catalog(Settings(
        agent_web_search_enabled=True,
        agent_web_search_allowed_domains="example.com",
        agent_web_search_url="https://example.com/search",
    ))
    assert ready["web_search_ready"] is True

    misconfigured = get_agent_catalog(Settings(
        agent_web_search_enabled=True,
        agent_web_search_allowed_domains="other.example",
        agent_web_search_url="https://example.com/search",
    ))
    assert misconfigured["web_search_ready"] is False


def test_plan_routes_agents_by_question_type() -> None:
    # Without a selected member the database step never widens its scope.
    plan = plan_agent_execution("MEDICATION_SAFETY", household_id=None, member_id=None)
    assert plan["database"].run is False
    assert plan["knowledge"].run is True

    # Medication safety needs the approved knowledge chunks plus member facts.
    plan = plan_agent_execution("MEDICATION_SAFETY", household_id="h", member_id="m")
    assert plan["database"].run is True
    assert plan["knowledge"].run is True

    # Rule evidence is answered from the deterministic rule records.
    plan = plan_agent_execution("RULE_EVIDENCE", household_id="h", member_id="m")
    assert plan["database"].run is True
    assert plan["knowledge"].run is False
    # ...unless no member is selected, then generic knowledge still helps.
    plan = plan_agent_execution("RULE_EVIDENCE", household_id=None, member_id=None)
    assert plan["knowledge"].run is True

    # Urgent questions never wait for an external search.
    plan = plan_agent_execution("URGENT", household_id="h", member_id="m")
    assert plan["web_search"].run is False


def test_greeting_fast_path_never_touches_model_or_tools(monkeypatch) -> None:
    def _forbidden(*args, **kwargs):
        raise AssertionError("greeting must not call the model or database tools")

    monkeypatch.setattr("app.local_agents.OllamaClient", _forbidden)
    monkeypatch.setattr("app.local_agents.execute_whitelisted_tool", _forbidden)
    monkeypatch.setattr("app.local_agents.execute_web_search", _forbidden)

    result = run_local_multi_agent(
        None,
        messages=[{"role": "user", "content": "你好"}],
        actor_id="actor",
        allow_network_search=True,
    )

    assert result["degraded"] is False
    assert result["answer"]
    assert result["network_used"] is False
    statuses = {trace["agent_id"]: trace["status"] for trace in result["agent_trace"]}
    assert statuses["database"] == "skipped"
    assert statuses["knowledge"] == "skipped"
    assert statuses["web_search"] == "skipped"
    assert statuses["synthesis"] == "completed"


def test_multi_agent_skips_knowledge_for_rule_evidence(monkeypatch) -> None:
    calls: list[str] = []

    def fake_database(session, **kwargs):
        calls.append("database")
        return {"get_applied_rules": {"sources": ["RULE-1"]}}, {
            "agent_id": "database", "role": "健康档案核对", "status": "completed",
            "local": True, "network_used": False, "duration_ms": 1,
            "summary": "", "source_count": 1,
        }

    def fake_knowledge(session, **kwargs):
        raise AssertionError("knowledge must be skipped for rule evidence")

    def fake_synthesis(**kwargs):
        calls.append("synthesis")
        return {
            "answer": "ok", "sources": [], "citations": [],
            "suggested_questions": [], "confidence": "high", "escalate": False,
            "degraded": False, "degrade_reason": None, "route": None,
            "model": kwargs.get("model"), "query_type": kwargs.get("query_type"),
            "risk_notice": None,
            "_trace": {
                "agent_id": "synthesis", "role": "回答生成", "status": "completed",
                "local": True, "network_used": False, "duration_ms": 1,
                "summary": "", "source_count": 0,
            },
        }

    monkeypatch.setattr("app.local_agents._database_agent", fake_database)
    monkeypatch.setattr("app.local_agents._knowledge_agent", fake_knowledge)
    monkeypatch.setattr("app.local_agents._synthesis_agent", fake_synthesis)

    result = run_local_multi_agent(
        None,
        messages=[{"role": "user", "content": "这个提醒的规则依据是什么？"}],
        actor_id="actor",
        household_id="household",
        member_id="member",
    )

    assert calls == ["database", "synthesis"]
    statuses = {trace["agent_id"]: trace["status"] for trace in result["agent_trace"]}
    assert statuses["knowledge"] == "skipped"
    assert statuses["web_search"] == "skipped"
    assert result["query_type"] == "RULE_EVIDENCE"


def test_search_parser_tolerates_markup_drift() -> None:
    # No result__a class at all: the redirect-link fallback still finds results.
    drifted = (
        '<div class="web-result">'
        '<a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa">标题一</a>'
        '<span class="snippet">摘要一</span>'
        "</div>"
        '<h2 class="result__title"><a href="https://example.org/b">标题二</a></h2>'
    )

    results = parse_search_results(drifted)

    assert [item["url"] for item in results] == [
        "https://example.com/a",
        "https://example.org/b",
    ]
    assert results[0]["snippet"] == "摘要一"


def test_search_parser_handles_empty_or_broken_body() -> None:
    assert parse_search_results("") == []
    assert parse_search_results("<html><body>没有结果标记</body></html>") == []


@pytest.mark.parametrize("body", ["", "<html><body><p>no results</p></body></html>"])
def test_web_search_no_results_keeps_trace_clear(monkeypatch, body: str) -> None:
    def fake_execute(query: str, *, settings: Settings):
        return []

    monkeypatch.setattr("app.local_agents.execute_web_search", fake_execute)
    results, trace, safe_query = _web_search_agent(
        "布洛芬注意事项",
        sensitive_values=[],
        allow_network_search=True,
        settings=Settings(
            agent_web_search_enabled=True,
            agent_web_search_allowed_domains="example.com",
            agent_web_search_url="https://example.com/search",
        ),
    )

    assert results == []
    assert trace["status"] == "completed"
    assert trace["source_count"] == 0
    assert trace["network_used"] is True
    assert "未找到" in trace["summary"]
    assert safe_query is not None


def test_general_plan_skips_knowledge_and_web_search() -> None:
    plan = plan_agent_execution("GENERAL", household_id="h", member_id="m")
    assert plan["knowledge"].run is False
    assert plan["web_search"].run is False
    assert plan["database"].run is True


def test_medication_safety_short_circuits_without_knowledge(monkeypatch) -> None:
    class _ForbiddenOllama:
        def __init__(self, *args, **kwargs):
            raise AssertionError("no model")

    monkeypatch.setattr("app.local_agents.OllamaClient", _ForbiddenOllama)

    def fake_database(session, **kwargs):
        return {"get_member_state": {"sources": []}}, {
            "agent_id": "database", "role": "健康档案核对", "status": "completed",
            "local": True, "network_used": False, "duration_ms": 1,
            "summary": "", "source_count": 0,
        }

    def fake_knowledge(session, **kwargs):
        return {"results": []}, {
            "agent_id": "knowledge", "role": "本地资料检索", "status": "completed",
            "local": True, "network_used": False, "duration_ms": 1,
            "summary": "", "source_count": 0,
        }

    monkeypatch.setattr("app.local_agents._database_agent", fake_database)
    monkeypatch.setattr("app.local_agents._knowledge_agent", fake_knowledge)

    result = run_local_multi_agent(
        None,
        messages=[{"role": "user", "content": "布洛芬和阿莫西林能否同服？"}],
        actor_id="actor",
        household_id="household",
        member_id="member",
    )

    assert result["degraded"] is True
    assert result["degrade_reason"] == "EVIDENCE_REQUIRED"
    synthesis = next(trace for trace in result["agent_trace"] if trace["agent_id"] == "synthesis")
    assert synthesis["status"] == "degraded"
    assert "跳过模型" in synthesis["summary"]
