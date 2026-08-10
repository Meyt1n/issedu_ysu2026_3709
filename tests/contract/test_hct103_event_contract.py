from fastapi.testclient import TestClient


def test_hct103_openapi_exposes_recovery_contract(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    assert "post" in paths[
        "/api/v1/households/{household_id}/events/{event_id}/compensations"
    ]
    assert "post" in paths[
        "/api/v1/households/{household_id}/members/{member_id}/state/replay"
    ]
    assert "post" in paths[
        "/api/v1/households/{household_id}/members/{member_id}/state/checkpoints"
    ]
    assert "get" in paths["/api/v1/households/{household_id}/outbox"]
    assert "post" in paths["/api/v1/households/{household_id}/outbox/dispatch"]


def test_hct103_event_schema_contains_trace_and_replay_fields(client: TestClient) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    event_fields = schemas["HealthEventRead"]["properties"]
    assert {
        "sequence_no",
        "occurred_at",
        "recorded_at",
        "correlation_id",
        "causation_id",
        "supersedes_event_id",
        "schema_version",
    }.issubset(event_fields)
    projection_fields = schemas["MemberStateRead"]["properties"]
    assert {"last_sequence", "version", "state_hash"}.issubset(projection_fields)
