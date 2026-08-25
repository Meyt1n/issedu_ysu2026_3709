"""Apply formal demo health seed plan through the API TestClient."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.formal_demo_plan import (
    FORMAL_CHILD_ACTOR_ID,
    FORMAL_GRANDMA_ACTOR_ID,
    FORMAL_GRANDPA_ACTOR_ID,
    FORMAL_HOUSEHOLD_NAME,
    FORMAL_OWNER_ACTOR_ID,
    expected_graph_labels,
)
from app.formal_demo_seed import apply_formal_demo_seed

OWNER_HEADERS = {
    "X-Actor-Id": FORMAL_OWNER_ACTOR_ID,
    "X-Access-Purpose": "family-care",
}


def test_formal_demo_seed_links_disease_allergy_meds_metrics_and_risks(
    client: TestClient,
    db_session,
) -> None:
    report = apply_formal_demo_seed(db_session, actor_id=FORMAL_OWNER_ACTOR_ID)
    assert report["ok"] is True
    assert report["child_actor_id"] == FORMAL_CHILD_ACTOR_ID
    household_id = report["household_id"]
    grandma_id = report["members"]["grandma"]["id"]
    grandpa_id = report["members"]["grandpa"]["id"]

    expected = expected_graph_labels()
    for key, member_id in {"grandma": grandma_id, "grandpa": grandpa_id}.items():
        graph = client.get(
            f"/api/v1/households/{household_id}/members/{member_id}/relationship-graph",
            headers=OWNER_HEADERS,
        )
        assert graph.status_code == 200, graph.text
        nodes = graph.json().get("nodes", [])
        disease_labels = {n["label"] for n in nodes if n.get("category") == "disease"}
        allergy_labels = {n["label"] for n in nodes if n.get("category") == "allergy"}
        drug_labels = {n["label"] for n in nodes if n.get("category") == "drug"}
        assert expected[key]["diseases"] <= disease_labels
        assert expected[key]["allergies"] <= allergy_labels
        assert expected[key]["drugs"] <= drug_labels

        risks = client.get(
            f"/api/v1/households/{household_id}/members/{member_id}/risks",
            headers=OWNER_HEADERS,
        )
        assert risks.status_code == 200, risks.text
        body = risks.json()
        assert body["severe_count"] >= 1
        rules = {alert["rule_id"] for alert in body["alerts"]}
        assert "allergy_conflict" in rules

    timeline = client.get(
        f"/api/v1/households/{household_id}/members/{grandma_id}/timeline",
        headers=OWNER_HEADERS,
    )
    assert timeline.status_code == 200, timeline.text
    types = {item["event_type"] for item in timeline.json()}
    assert "metric_recorded" in types
    assert "plan_confirmed" in types
    assert "plan_missed" in types
    assert "care_escalated" in types

    scenarios = client.get("/api/v1/demo/classroom-scenarios", headers=OWNER_HEADERS)
    assert scenarios.status_code == 200
    assert len(scenarios.json()["scenarios"]) >= 3

    seeded = client.post("/api/v1/demo/formal-health-seed", headers=OWNER_HEADERS)
    assert seeded.status_code == 200, seeded.text
    assert seeded.json()["household_name"] == FORMAL_HOUSEHOLD_NAME

    forbidden = client.post(
        "/api/v1/demo/formal-health-seed",
        headers={"X-Actor-Id": "random-user", "X-Access-Purpose": "family-care"},
    )
    assert forbidden.status_code == 403

    severe_total = 0
    for member_id in (grandma_id, grandpa_id):
        risks = client.get(
            f"/api/v1/households/{household_id}/members/{member_id}/risks",
            headers=OWNER_HEADERS,
        ).json()
        severe_total += int(risks["severe_count"])
    assert severe_total >= 2
    assert report["members"]["grandma"]["actor_id"] == FORMAL_GRANDMA_ACTOR_ID
    assert report["members"]["grandpa"]["actor_id"] == FORMAL_GRANDPA_ACTOR_ID
