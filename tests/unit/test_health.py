from fastapi.testclient import TestClient


def test_health_and_capability_contract(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    capabilities = client.get("/api/v1/meta/capabilities")
    assert capabilities.status_code == 200
    assert "manual-health-event" in capabilities.json()["available"]
    assert "llm" in capabilities.json()["available"]


def test_actor_is_required_for_mutating_routes(client: TestClient) -> None:
    response = client.post("/api/v1/households", json={"name": "家庭"})
    assert response.status_code == 401
    assert response.json()["detail"] == "ACTOR_REQUIRED"
