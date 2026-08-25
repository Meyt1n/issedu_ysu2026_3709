"""HCT-430 API contract tests."""

from fastapi.testclient import TestClient


def test_agent_catalog_exposes_local_only_graph(client: TestClient) -> None:
    response = client.get(
        "/api/v1/assistant/agents",
        headers={"X-Actor-Id": "hct430-contract-owner"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "multi_agent"
    assert body["all_agents_local"] is True
    assert body["ollama_local_only"] is True
    # The catalog must state whether search is actually usable; a disabled
    # deployment can never report a ready search agent.
    assert "web_search_ready" in body
    if not body["web_search_enabled"]:
        assert body["web_search_ready"] is False
    assert {item["agent_id"] for item in body["agents"]} >= {
        "router",
        "database",
        "rules",
        "knowledge",
        "web_search",
        "synthesis",
    }
    assert all(item["local"] is True for item in body["agents"])


def test_assistant_request_preserves_legacy_single_agent_default() -> None:
    from app.schemas import AssistantRequest

    payload = AssistantRequest(messages=[{"role": "user", "content": "你好"}])

    assert payload.agent_mode == "single"
    assert payload.allow_network_search is False
    assert payload.query_type_override is None
    assert payload.assistant_session_id is None
    assert payload.clear_session_cache is False


def test_agent_catalog_exposes_search_provider(client: TestClient) -> None:
    response = client.get(
        "/api/v1/assistant/agents",
        headers={"X-Actor-Id": "hct430-contract-owner"},
    )
    assert response.status_code == 200
    assert response.json()["web_search_provider"] == "duckduckgo_html"


def test_agent_catalog_explains_search_availability(client: TestClient) -> None:
    """Clients must be able to say why search is unavailable and how to enable it."""
    response = client.get(
        "/api/v1/assistant/agents",
        headers={"X-Actor-Id": "hct430-contract-owner"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["web_search_unavailable_reason"] in {
        "DEPLOYMENT_DISABLED",
        "EGRESS_BLOCKED",
        "OPT_IN_REQUIRED",
    }
    if not body["web_search_enabled"]:
        assert body["web_search_unavailable_reason"] == "DEPLOYMENT_DISABLED"
    assert isinstance(body["web_search_enable_hint"], str)
    assert body["web_search_enable_hint"]
    assert isinstance(body["web_search_offline_fixture"], bool)


def test_assistant_stream_requires_multi_agent(client: TestClient) -> None:
    response = client.post(
        "/api/v1/assistant/chat/stream",
        headers={"X-Actor-Id": "hct430-contract-owner"},
        json={"messages": [{"role": "user", "content": "你好"}], "agent_mode": "single"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "STREAM_REQUIRES_MULTI_AGENT"


def test_assistant_stream_greeting_emits_trace_token_done(client: TestClient) -> None:
    with client.stream(
        "POST",
        "/api/v1/assistant/chat/stream",
        headers={"X-Actor-Id": "hct430-stream-owner"},
        json={
            "messages": [{"role": "user", "content": "你好"}],
            "agent_mode": "multi_agent",
        },
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert "event: trace" in body
    assert "event: token" in body
    assert "event: done" in body
    assert "event: status" in body
    assert "event: evidence_preview" in body
    assert "家庭健康助手" in body
    # Validated answer text is streamed; the raw JSON draft must not appear.
    assert '{"answer"' not in body


def test_assistant_stream_emits_explicit_cancelled_event(
    client: TestClient,
    monkeypatch,
) -> None:
    from app.local_agents import OrchestrationCancelled

    def cancel(*_args, **_kwargs):
        raise OrchestrationCancelled("test cancellation")

    monkeypatch.setattr("app.routes.run_local_multi_agent", cancel)
    with client.stream(
        "POST",
        "/api/v1/assistant/chat/stream",
        headers={"X-Actor-Id": "hct430-stream-owner"},
        json={
            "messages": [{"role": "user", "content": "查看规则依据"}],
            "agent_mode": "multi_agent",
        },
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert "event: cancelled" in body
    assert '"code": "CANCELLED"' in body
