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


def test_knowledge_agent_reports_empty_library_as_degraded_not_blocked(db_session) -> None:
    """No accessible reviewed documents is a retrieval gap, not a risk-control
    interception — the trace must not claim the step was "blocked"."""
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
    assert trace["status"] == "degraded"
    assert "暂无" in trace["summary"]


def test_knowledge_agent_reports_scope_denial_as_blocked(monkeypatch, db_session) -> None:
    """Real scope/tool failures keep the honest blocked status."""
    monkeypatch.setattr(
        "app.local_agents._tool_payload",
        lambda *args, **kwargs: {"error": "TOOL_SCOPE_DENIED", "results": [], "total": 0},
    )

    result, trace = _knowledge_agent(
        db_session,
        query="阿莫西林 用法",
        actor_id="u1",
        household_id=None,
        member_id=None,
        access_purpose=None,
    )

    assert result.get("error") == "TOOL_SCOPE_DENIED"
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
    assert trace["reason_code"] == "NOT_OPTED_IN"
    assert trace["network_used"] is False
    assert safe_query is None


def test_web_search_opt_in_with_disabled_deployment_is_blocked_with_reason() -> None:
    """Opting in without the deployment switch must say why it was blocked,
    not silently skip the node."""
    results, trace, safe_query = _web_search_agent(
        "最近有什么流行性感冒吗",
        sensitive_values=[],
        allow_network_search=True,
        settings=Settings(agent_web_search_enabled=False),
    )

    assert results == []
    assert trace["status"] == "blocked"
    assert trace["reason_code"] == "DEPLOYMENT_DISABLED"
    assert "未在当前部署启用" in trace["summary"]
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

    assert set(calls) == {
        "get_member_state",
        "get_health_events",
        "get_care_plan_status",
    }
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


def test_agent_catalog_explains_unavailable_reason_and_enable_hint() -> None:
    """The catalog must say why search is off and how to turn it on."""
    disabled = get_agent_catalog(Settings())
    assert disabled["web_search_unavailable_reason"] == "DEPLOYMENT_DISABLED"
    assert "AGENT_WEB_SEARCH_ENABLED" in disabled["web_search_enable_hint"]
    assert disabled["web_search_offline_fixture"] is False

    egress_blocked = get_agent_catalog(Settings(
        agent_web_search_enabled=True,
        agent_web_search_allowed_domains="other.example",
        agent_web_search_url="https://example.com/search",
    ))
    assert egress_blocked["web_search_unavailable_reason"] == "EGRESS_BLOCKED"
    assert "AGENT_WEB_SEARCH_ALLOWED_DOMAINS" in egress_blocked["web_search_enable_hint"]

    ready = get_agent_catalog(Settings(
        agent_web_search_enabled=True,
        agent_web_search_allowed_domains="example.com",
        agent_web_search_url="https://example.com/search",
    ))
    assert ready["web_search_ready"] is True
    assert ready["web_search_unavailable_reason"] == "OPT_IN_REQUIRED"

    fixture = get_agent_catalog(Settings(
        agent_web_search_enabled=True,
        agent_web_search_provider="fixture",
    ))
    assert fixture["web_search_ready"] is True
    assert fixture["web_search_offline_fixture"] is True
    assert fixture["web_search_unavailable_reason"] == "OPT_IN_REQUIRED"
    assert "教学夹具" in fixture["web_search_enable_hint"]


def test_chat_stream_wraps_connection_errors_for_structured_degrade(monkeypatch) -> None:
    """An unreachable Ollama must degrade, not crash the whole chat request."""
    import httpx
    import pytest as _pytest

    from app.tool_call import OllamaClient

    class _RefusingClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def stream(self, *_args, **_kwargs):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("app.tool_call.httpx.Client", _RefusingClient)
    stream = OllamaClient().chat_stream(
        model="local-model",
        messages=[{"role": "user", "content": "测试"}],
    )
    with _pytest.raises(RuntimeError, match="OLLAMA_UNAVAILABLE"):
        list(stream)


def test_web_search_agent_with_fixture_provider_stays_offline(monkeypatch) -> None:
    """Dual opt-in with the fixture provider works without any egress."""

    class _NoNetwork:
        def __init__(self, *args, **kwargs):
            raise AssertionError("fixture provider must never open an HTTP client")

    monkeypatch.setattr("app.search_providers.httpx.Client", _NoNetwork)
    from app.search_providers import clear_search_cache

    clear_search_cache()
    results, trace, safe_query = _web_search_agent(
        "药箱里的药过期了怎么处理",
        sensitive_values=[],
        allow_network_search=True,
        settings=Settings(
            agent_web_search_enabled=True,
            agent_web_search_provider="fixture",
            agent_web_search_cache_ttl_seconds=0,
        ),
    )

    assert results, "fixture provider should return teaching references"
    assert trace["status"] == "completed"
    assert trace["network_used"] is False
    assert "教学夹具" in trace["summary"]
    assert safe_query is not None
    assert all(item["source"] == "teaching_fixture" for item in results)
    assert all(item["domain"] == "fixture.invalid" for item in results)


def test_plan_routes_agents_by_question_type() -> None:
    # Without a selected member the database step never widens its scope.
    plan = plan_agent_execution("MEDICATION_SAFETY", household_id=None, member_id=None)
    assert plan["database"].run is False
    assert plan["rules"].run is False
    assert plan["knowledge"].run is True

    # Medication safety needs the approved knowledge chunks plus member facts.
    plan = plan_agent_execution("MEDICATION_SAFETY", household_id="h", member_id="m")
    assert plan["database"].run is True
    assert plan["rules"].run is True
    assert plan["knowledge"].run is True

    # Rule evidence is answered from the deterministic rule records.
    plan = plan_agent_execution("RULE_EVIDENCE", household_id="h", member_id="m")
    assert plan["database"].run is True
    assert plan["rules"].run is True
    assert plan["knowledge"].run is False
    # ...unless no member is selected, then generic knowledge still helps.
    plan = plan_agent_execution("RULE_EVIDENCE", household_id=None, member_id=None)
    assert plan["knowledge"].run is True

    # Urgent questions never wait for an external search, even when opted in.
    plan = plan_agent_execution(
        "URGENT", household_id="h", member_id="m", allow_network_search=True
    )
    assert plan["web_search"].run is False
    assert plan["web_search"].reason_code == "URGENT_LOCAL_FIRST"


def test_greeting_fast_path_never_touches_model_or_tools(monkeypatch) -> None:
    def _forbidden(*args, **kwargs):
        raise AssertionError("greeting must not call the model or database tools")

    monkeypatch.setattr("app.local_agents.OllamaClient", _forbidden)
    monkeypatch.setattr("app.local_agents.execute_whitelisted_tool", _forbidden)
    monkeypatch.setattr("app.local_agents.execute_web_search", _forbidden)

    phases: list[str] = []
    result = run_local_multi_agent(
        None,
        messages=[{"role": "user", "content": "你好"}],
        actor_id="actor",
        allow_network_search=True,
        on_status=phases.append,
    )

    assert result["degraded"] is False
    assert result["answer"]
    assert result["network_used"] is False
    assert phases[0] == "routing"
    assert "generating" in phases
    statuses = {trace["agent_id"]: trace["status"] for trace in result["agent_trace"]}
    assert statuses["database"] == "skipped"
    assert statuses["rules"] == "skipped"
    assert statuses["knowledge"] == "skipped"
    assert statuses["web_search"] == "skipped"
    assert statuses["synthesis"] == "completed"


def test_multi_agent_skips_knowledge_for_rule_evidence(monkeypatch) -> None:
    calls: list[str] = []

    def fake_database(session, **kwargs):
        calls.append("database")
        return {"get_member_state": {"sources": ["event-1"]}}, {
            "agent_id": "database", "role": "健康档案核对", "status": "completed",
            "local": True, "network_used": False, "duration_ms": 1,
            "summary": "", "source_count": 1,
        }

    def fake_knowledge(session, **kwargs):
        raise AssertionError("knowledge must be skipped for rule evidence")

    def fake_rules(session, **kwargs):
        calls.append("rules")
        return {"get_applied_rules": {"sources": ["RULE-1"]}}, {
            "agent_id": "rules", "role": "规则依据核对", "status": "completed",
            "local": True, "network_used": False, "duration_ms": 1,
            "summary": "", "source_count": 1,
        }

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
    monkeypatch.setattr("app.local_agents._rules_agent", fake_rules)
    monkeypatch.setattr("app.local_agents._synthesis_agent", fake_synthesis)

    result = run_local_multi_agent(
        None,
        messages=[{"role": "user", "content": "这个提醒的规则依据是什么？"}],
        actor_id="actor",
        household_id="household",
        member_id="member",
    )

    assert calls == ["database", "rules", "synthesis"]
    statuses = {trace["agent_id"]: trace["status"] for trace in result["agent_trace"]}
    assert statuses["rules"] == "completed"
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


def test_general_plan_runs_knowledge_and_honours_search_opt_in() -> None:
    """HCT-430/HCT-450: GENERAL teaching questions retrieve the reviewed local
    library; external search stays off until the user opts in (double gate
    still lives in the web-search agent)."""
    plan = plan_agent_execution("GENERAL", household_id="h", member_id="m")
    assert plan["knowledge"].run is True
    assert plan["database"].run is True
    assert plan["rules"].run is False
    # Not opted in: skipped with a machine-readable cause.
    assert plan["web_search"].run is False
    assert plan["web_search"].reason_code == "NOT_OPTED_IN"

    opted_in = plan_agent_execution(
        "GENERAL", household_id="h", member_id="m", allow_network_search=True
    )
    assert opted_in["web_search"].run is True
    # Opt-in also applies without a selected member (e.g.「你能联网搜索吗」).
    no_member = plan_agent_execution(
        "GENERAL", household_id=None, member_id=None, allow_network_search=True
    )
    assert no_member["web_search"].run is True
    assert no_member["knowledge"].run is True


def _completed_trace(agent_id: str, role: str, source_count: int = 0) -> dict:
    return {
        "agent_id": agent_id, "role": role, "status": "completed",
        "local": True, "network_used": False, "duration_ms": 1,
        "summary": "", "source_count": source_count,
    }


def test_general_opt_in_with_fixture_completes_web_search(monkeypatch) -> None:
    """Opt-in + fixture deployment: the web_search node must be completed with
    offline teaching references, and the synthesis prompt must state that the
    node ran instead of letting the model claim it cannot reach the network."""
    from app.search_providers import clear_search_cache

    clear_search_cache()
    fixture_settings = Settings(
        agent_web_search_enabled=True,
        agent_web_search_provider="fixture",
        agent_web_search_cache_ttl_seconds=0,
        agent_retrieval_cache_ttl_seconds=0,
    )
    monkeypatch.setattr("app.local_agents.get_settings", lambda: fixture_settings)

    def fake_knowledge(session, **kwargs):
        return {"results": []}, _completed_trace("knowledge", "本地资料检索")

    captured: dict[str, object] = {}

    def fake_synthesis(**kwargs):
        captured["network_status_note"] = kwargs.get("network_status_note")
        captured["external_sources"] = kwargs.get("external_sources")
        return {
            "answer": "ok", "sources": [], "citations": [],
            "suggested_questions": [], "confidence": "high", "escalate": False,
            "degraded": False, "degrade_reason": None, "route": None,
            "model": kwargs.get("model"), "query_type": kwargs.get("query_type"),
            "risk_notice": None,
            "_trace": _completed_trace("synthesis", "回答生成"),
        }

    monkeypatch.setattr("app.local_agents._knowledge_agent", fake_knowledge)
    monkeypatch.setattr("app.local_agents._synthesis_agent", fake_synthesis)

    result = run_local_multi_agent(
        None,
        messages=[{"role": "user", "content": "最近有什么流行性感冒吗"}],
        actor_id="actor",
        allow_network_search=True,
    )

    statuses = {trace["agent_id"]: trace["status"] for trace in result["agent_trace"]}
    assert statuses["web_search"] == "completed"
    assert statuses["knowledge"] == "completed"
    web = next(t for t in result["agent_trace"] if t["agent_id"] == "web_search")
    assert web["network_used"] is False
    assert "教学夹具" in web["summary"]
    assert result["network_used"] is False
    assert result["external_sources"], "fixture references must reach the response"
    assert all(item["source"] == "teaching_fixture" for item in result["external_sources"])
    note = str(captured["network_status_note"])
    assert "已执行" in note
    assert "教学夹具" in note


def test_general_opt_in_with_disabled_deployment_blocks_with_reason(monkeypatch) -> None:
    """Opt-in while the deployment switch is off: the node must be blocked with
    DEPLOYMENT_DISABLED, never silently skipped."""
    disabled_settings = Settings(
        agent_web_search_enabled=False,
        agent_retrieval_cache_ttl_seconds=0,
    )
    monkeypatch.setattr("app.local_agents.get_settings", lambda: disabled_settings)

    def fake_knowledge(session, **kwargs):
        return {"results": []}, _completed_trace("knowledge", "本地资料检索")

    captured: dict[str, object] = {}

    def fake_synthesis(**kwargs):
        captured["network_status_note"] = kwargs.get("network_status_note")
        return {
            "answer": "ok", "sources": [], "citations": [],
            "suggested_questions": [], "confidence": "high", "escalate": False,
            "degraded": False, "degrade_reason": None, "route": None,
            "model": kwargs.get("model"), "query_type": kwargs.get("query_type"),
            "risk_notice": None,
            "_trace": _completed_trace("synthesis", "回答生成"),
        }

    monkeypatch.setattr("app.local_agents._knowledge_agent", fake_knowledge)
    monkeypatch.setattr("app.local_agents._synthesis_agent", fake_synthesis)

    result = run_local_multi_agent(
        None,
        messages=[{"role": "user", "content": "你能够联网搜索吗"}],
        actor_id="actor",
        allow_network_search=True,
    )

    web = next(t for t in result["agent_trace"] if t["agent_id"] == "web_search")
    assert web["status"] == "blocked"
    assert web["reason_code"] == "DEPLOYMENT_DISABLED"
    assert result["network_used"] is False
    note = str(captured["network_status_note"])
    assert "部署" in note


def test_general_without_opt_in_keeps_web_search_skipped(monkeypatch) -> None:
    """No opt-in: the node stays skipped and the synthesis prompt explains the
    honest state (capability exists, this request did not enable it)."""
    settings = Settings(
        agent_web_search_enabled=True,
        agent_web_search_provider="fixture",
        agent_retrieval_cache_ttl_seconds=0,
    )
    monkeypatch.setattr("app.local_agents.get_settings", lambda: settings)

    def fake_knowledge(session, **kwargs):
        return {"results": []}, _completed_trace("knowledge", "本地资料检索")

    captured: dict[str, object] = {}

    def fake_synthesis(**kwargs):
        captured["network_status_note"] = kwargs.get("network_status_note")
        return {
            "answer": "ok", "sources": [], "citations": [],
            "suggested_questions": [], "confidence": "high", "escalate": False,
            "degraded": False, "degrade_reason": None, "route": None,
            "model": kwargs.get("model"), "query_type": kwargs.get("query_type"),
            "risk_notice": None,
            "_trace": _completed_trace("synthesis", "回答生成"),
        }

    monkeypatch.setattr("app.local_agents._knowledge_agent", fake_knowledge)
    monkeypatch.setattr("app.local_agents._synthesis_agent", fake_synthesis)

    result = run_local_multi_agent(
        None,
        messages=[{"role": "user", "content": "最近有什么流行性感冒吗"}],
        actor_id="actor",
        allow_network_search=False,
    )

    web = next(t for t in result["agent_trace"] if t["agent_id"] == "web_search")
    assert web["status"] == "skipped"
    assert web["reason_code"] == "NOT_OPTED_IN"
    note = str(captured["network_status_note"])
    assert "未勾选" in note
    assert "不要说自己完全不能联网" in note


def test_synthesis_degrade_mentions_retrieved_evidence(monkeypatch) -> None:
    """A schema failure must not hide references that were actually found."""
    from app.local_agents import _synthesis_agent

    class BrokenModel:
        def __init__(self, *args, **kwargs):
            pass

        def chat_stream(self, **kwargs):
            # Placeholder-label drafts fail _parse_assistant_output validation.
            yield '{"answer":"hello","sources":[],"confidence":"high","escalate":false}'

    monkeypatch.setattr("app.local_agents.OllamaClient", BrokenModel)
    monkeypatch.setattr("app.local_agents.is_loopback_ollama_url", lambda url: True)

    result = _synthesis_agent(
        messages=[{"role": "user", "content": "最近有什么流行性感冒吗"}],
        query_type="GENERAL",
        database={},
        knowledge={"results": []},
        external_sources=[{
            "title": "教学夹具：家庭照护公开科普检索导航",
            "url": "https://fixture.invalid/care-navigation",
            "snippet": "演示",
            "domain": "fixture.invalid",
            "source": "teaching_fixture",
        }],
        model="local-model",
        max_tokens=64,
        temperature=0.1,
        settings=Settings(agent_open_chat=False),
    )

    assert result["degraded"] is True
    assert result["degrade_reason"] == "SCHEMA_VALIDATION_FAILED"
    assert "1 条外部参考" in result["answer"]


def test_medication_safety_without_knowledge_still_answers(monkeypatch) -> None:
    """The EVIDENCE_REQUIRED short-circuit is gone and the answer stands alone.

    The draft already points at a clinician, so the server does not stack a
    second reminder or a low-evidence block on top of it."""
    class _AnsweringOllama:
        def __init__(self, *args, **kwargs):
            pass

        def chat_stream(self, **kwargs):
            yield (
                '{"answer":"两种药是否可以同服，本机资料未覆盖，无法替你判断，'
                '建议咨询医生或药师。","sources":[],"confidence":"low","escalate":false}'
            )

    monkeypatch.setattr("app.local_agents.OllamaClient", _AnsweringOllama)
    monkeypatch.setattr("app.local_agents.is_loopback_ollama_url", lambda url: True)

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

    assert result["query_type"] == "MEDICATION_SAFETY"
    assert result["degraded"] is False
    assert result["degrade_reason"] is None
    assert "风险说明" not in result["answer"]
    assert "咨询医生或药师" in result["answer"]
    assert result["risk_notice"]
    synthesis = next(trace for trace in result["agent_trace"] if trace["agent_id"] == "synthesis")
    assert synthesis["status"] == "completed"


def test_symptom_medication_model_down_keeps_friendly_fallback(monkeypatch) -> None:
    """When the model itself is unavailable and the library is empty, the
    symptom question still gets the deterministic friendly fallback rather
    than the generic MODEL_UNAVAILABLE wall."""
    class _DownOllama:
        def __init__(self, *args, **kwargs):
            pass

        def chat_stream(self, **kwargs):
            raise RuntimeError("OLLAMA_UNAVAILABLE: connection refused")
            yield  # pragma: no cover

    monkeypatch.setattr("app.local_agents.OllamaClient", _DownOllama)
    monkeypatch.setattr("app.local_agents.is_loopback_ollama_url", lambda url: True)

    def fake_database(session, **kwargs):
        return {"get_member_state": {"sources": []}}, {
            "agent_id": "database", "role": "健康档案核对", "status": "completed",
            "local": True, "network_used": False, "duration_ms": 1,
            "summary": "", "source_count": 0,
        }

    def fake_knowledge(session, **kwargs):
        return {"error": "NO_AUTHORISED_DOCUMENTS", "results": [], "total": 0}, {
            "agent_id": "knowledge", "role": "本地资料检索", "status": "degraded",
            "local": True, "network_used": False, "duration_ms": 1,
            "summary": "本机暂无当前可用的已审核知识卡", "source_count": 0,
        }

    monkeypatch.setattr("app.local_agents._database_agent", fake_database)
    monkeypatch.setattr("app.local_agents._knowledge_agent", fake_knowledge)

    result = run_local_multi_agent(
        None,
        messages=[{
            "role": "user",
            "content": "夏天吹空调后有点鼻塞，一般可以了解哪些用药资料？",
        }],
        actor_id="actor",
        household_id="household",
        member_id="member",
    )

    assert result["query_type"] == "SYMPTOM_MEDICATION"
    assert result["degraded"] is True
    assert result["degrade_reason"] == "KNOWLEDGE_UNAVAILABLE"
    assert result["escalate"] is False
    assert "医生或药师" in result["answer"]
    # The friendly fallback must not read like the harsh evidence wall.
    assert "缺少可核验的本地知识引用" not in result["answer"]
    assert result["suggested_questions"], "friendly fallback keeps follow-ups"
    statuses = {trace["agent_id"]: trace["status"] for trace in result["agent_trace"]}
    assert statuses["knowledge"] == "degraded"
    synthesis = next(trace for trace in result["agent_trace"] if trace["agent_id"] == "synthesis")
    assert "一般照护提示" in synthesis["summary"]


def test_dose_decision_fast_path_refuses_without_model(monkeypatch) -> None:
    """Decision 1A: 「一天几粒」refuses deterministically — no retrieval, no
    model call, escalate + fixed copy."""
    class _ForbiddenOllama:
        def __init__(self, *args, **kwargs):
            raise AssertionError("no model may be called for DOSE_DECISION")

    monkeypatch.setattr("app.local_agents.OllamaClient", _ForbiddenOllama)

    result = run_local_multi_agent(
        None,
        messages=[{"role": "user", "content": "布洛芬一天吃几粒？"}],
        actor_id="actor",
        household_id="household",
        member_id="member",
    )

    assert result["query_type"] == "DOSE_DECISION"
    assert result["degraded"] is True
    assert result["degrade_reason"] == "DOSE_DECISION_REFUSED"
    assert result["escalate"] is True
    assert "医生或药师" in result["answer"]
    statuses = {trace["agent_id"]: trace["status"] for trace in result["agent_trace"]}
    assert statuses["database"] == "skipped"
    assert statuses["knowledge"] == "skipped"
    assert statuses["web_search"] == "skipped"
    assert statuses["synthesis"] == "completed"


def test_context_binding_drops_cross_member_history() -> None:
    """One assistant session switching member must not keep the previous
    member's turns (context binding)."""
    from app.local_agents import bind_session_member_context, reset_session_member_bindings

    reset_session_member_bindings()
    history = [
        {"role": "system", "content": "server context"},
        {"role": "user", "content": "爷爷的用药记录"},
        {"role": "assistant", "content": "……"},
        {"role": "user", "content": "那他的过敏史呢"},
    ]
    bound, switched = bind_session_member_context(
        history,
        assistant_session_id="session-1",
        actor_id="actor",
        household_id="h1",
        member_id="grandpa",
    )
    assert not switched and bound == history

    bound, switched = bind_session_member_context(
        history,
        assistant_session_id="session-1",
        actor_id="actor",
        household_id="h1",
        member_id="child",
    )
    assert switched
    roles = [message["role"] for message in bound]
    assert roles == ["system", "user"]
    assert bound[-1]["content"] == "那他的过敏史呢"
    reset_session_member_bindings()


def test_anaphoric_follow_up_inherits_medication_safety_type() -> None:
    """「那饭后呢」after a co-administration question keeps the safety route."""
    from ai.safety.classifier import inherit_query_type_from_history

    query_type, inherited = inherit_query_type_from_history(
        [
            {"role": "user", "content": "布洛芬和阿莫西林能一起吃吗"},
            {"role": "assistant", "content": "……"},
            {"role": "user", "content": "那饭后呢"},
        ],
        current_type="GENERAL",
    )
    assert inherited is True
    assert query_type == "MEDICATION_SAFETY"


def test_compact_local_evidence_keeps_query_relevant_fields() -> None:
    from app.local_agents import _compact_local_evidence

    database = {
        "get_member_state": {
            "sources": ["state"],
            "state": {
                "drugs": [{"name": "布洛芬"}],
                "allergies": [],
                "plans": [],
                "notes": "x" * 5000,
            },
        },
        "get_health_events": {"sources": [], "events": []},
        "get_applied_rules": {"sources": ["RULE-1"], "rules": [{"id": "RULE-1"}]},
    }
    knowledge = {
        "results": [
            {
                "document_id": "d1",
                "chunk_id": "c1",
                "title": "说明书",
                "text": "很长的正文" * 200,
            }
        ]
    }

    med = _compact_local_evidence(database, knowledge, query_type="MEDICATION_SAFETY")
    assert "布洛芬" in med
    assert "notes" not in med
    assert "get_applied_rules" not in med

    rules = _compact_local_evidence(
        database,
        knowledge,
        query_type="RULE_EVIDENCE",
        rules={"get_applied_rules": database["get_applied_rules"]},
    )
    assert "RULE-1" in rules
    assert "get_member_state" in rules


def test_synthesis_streams_only_validated_answer(monkeypatch) -> None:
    from app.config import Settings
    from app.local_agents import _synthesis_agent

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def chat_stream(self, **kwargs):
            draft = '{"answer":"最终回答","sources":[],"confidence":"high","escalate":false}'
            yield draft[:20]
            yield draft[20:]

    monkeypatch.setattr("app.local_agents.OllamaClient", FakeClient)
    monkeypatch.setattr("app.local_agents.is_loopback_ollama_url", lambda url: True)

    tokens: list[str] = []
    statuses: list[str] = []
    result = _synthesis_agent(
        messages=[{"role": "user", "content": "今天天气怎样"}],
        query_type="GENERAL",
        database={},
        knowledge={},
        external_sources=[],
        model="local-model",
        max_tokens=128,
        temperature=0.1,
        settings=Settings(agent_open_chat=False),
        on_token=tokens.append,
        on_status=statuses.append,
    )

    assert result["answer"] == "最终回答"
    assert "".join(tokens) == "最终回答"
    assert "{" not in "".join(tokens)
    assert statuses == ["generating", "validating"]


def test_synthesis_emits_validating_status(monkeypatch) -> None:
    from app.config import Settings
    from app.local_agents import _synthesis_agent

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def chat_stream(self, **kwargs):
            yield '{"answer":"ok","sources":[],"confidence":"high","escalate":false}'

    monkeypatch.setattr("app.local_agents.OllamaClient", FakeClient)
    monkeypatch.setattr("app.local_agents.is_loopback_ollama_url", lambda url: True)

    phases: list[str] = []
    _synthesis_agent(
        messages=[{"role": "user", "content": "一般问题"}],
        query_type="GENERAL",
        database={},
        knowledge={},
        external_sources=[],
        model="local-model",
        max_tokens=64,
        temperature=0.1,
        settings=Settings(agent_open_chat=False),
        on_status=phases.append,
    )
    assert phases == ["generating", "validating"]
