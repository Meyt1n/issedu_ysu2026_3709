"""HCT-430: local agent graph, redaction and controlled web-search tests."""

from __future__ import annotations

from app.config import Settings
from app.egress_guard import is_web_search_egress_allowed
from app.local_agents import (
    _database_agent,
    _web_search_agent,
    get_agent_catalog,
    parse_search_results,
    redact_web_query,
)


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

    class FakeResponse:
        text = (
            '<a class="result__a" href="https://example.com/a">参考</a>'
            '<div class="result__snippet">摘要</div>'
        )

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, params):
            captured["url"] = url
            captured["params"] = params
            return FakeResponse()

    monkeypatch.setattr("app.local_agents.httpx.Client", FakeClient)
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
    assert captured["url"] == "https://example.com/search"


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
