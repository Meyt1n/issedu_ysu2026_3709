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
    assert {item["agent_id"] for item in body["agents"]} >= {
        "router",
        "database",
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
