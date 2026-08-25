"""Apply formal demo health seed plan through the API TestClient."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from formal_demo_health_plan import (  # noqa: E402
    FORMAL_DEMO_HEALTH_EVENTS,
    FORMAL_GRANDMA_ACTOR_ID,
    FORMAL_GRANDPA_ACTOR_ID,
    FORMAL_HOUSEHOLD_NAME,
    FORMAL_OWNER_ACTOR_ID,
    expected_graph_labels,
)

OWNER_HEADERS = {
    "X-Actor-Id": FORMAL_OWNER_ACTOR_ID,
    "X-Access-Purpose": "family-care",
}


def _ensure_household(client: TestClient) -> str:
    listed = client.get("/api/v1/households", headers=OWNER_HEADERS)
    assert listed.status_code == 200, listed.text
    for item in listed.json():
        if item.get("name") == FORMAL_HOUSEHOLD_NAME:
            return item["id"]
    created = client.post(
        "/api/v1/households",
        headers=OWNER_HEADERS,
        json={"name": FORMAL_HOUSEHOLD_NAME, "time_zone": "Asia/Shanghai"},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _ensure_members(client: TestClient, household_id: str) -> dict[str, str]:
    listed = client.get(
        f"/api/v1/households/{household_id}/members",
        headers=OWNER_HEADERS,
    )
    assert listed.status_code == 200, listed.text
    by_key: dict[str, str] = {}
    for member in listed.json():
        if member.get("actor_id") == FORMAL_GRANDMA_ACTOR_ID or member.get(
            "display_name"
        ) == "奶奶":
            by_key["grandma"] = member["id"]
        elif member.get("actor_id") == FORMAL_GRANDPA_ACTOR_ID or member.get(
            "display_name"
        ) == "爷爷":
            by_key["grandpa"] = member["id"]
    desired = {
        "grandma": {
            "display_name": "奶奶",
            "role": "DEPENDENT",
            "actor_id": FORMAL_GRANDMA_ACTOR_ID,
        },
        "grandpa": {
            "display_name": "爷爷",
            "role": "DEPENDENT",
            "actor_id": FORMAL_GRANDPA_ACTOR_ID,
        },
    }
    for key, body in desired.items():
        if key in by_key:
            continue
        created = client.post(
            f"/api/v1/households/{household_id}/members",
            headers=OWNER_HEADERS,
            json=body,
        )
        assert created.status_code == 201, created.text
        by_key[key] = created.json()["id"]
    return by_key


def test_formal_demo_seed_links_disease_allergy_meds_and_risks(
    client: TestClient,
) -> None:
    household_id = _ensure_household(client)
    members = _ensure_members(client, household_id)

    for spec in FORMAL_DEMO_HEALTH_EVENTS:
        response = client.post(
            f"/api/v1/households/{household_id}/events",
            headers=OWNER_HEADERS,
            json={
                "member_id": members[spec["member_key"]],
                "event_type": spec["event_type"],
                "source": "MANUAL",
                "confirmation_status": "CONFIRMED",
                "payload": spec["payload"],
                "idempotency_key": spec["idempotency_key"],
            },
        )
        assert response.status_code == 201, response.text

    # Idempotent replay returns the same facts without error.
    for spec in FORMAL_DEMO_HEALTH_EVENTS[:2]:
        again = client.post(
            f"/api/v1/households/{household_id}/events",
            headers=OWNER_HEADERS,
            json={
                "member_id": members[spec["member_key"]],
                "event_type": spec["event_type"],
                "source": "MANUAL",
                "confirmation_status": "CONFIRMED",
                "payload": spec["payload"],
                "idempotency_key": spec["idempotency_key"],
            },
        )
        assert again.status_code == 201, again.text

    expected = expected_graph_labels()
    for key, member_id in members.items():
        graph = client.get(
            f"/api/v1/households/{household_id}/members/{member_id}/relationship-graph",
            headers=OWNER_HEADERS,
        )
        assert graph.status_code == 200, graph.text
        body = graph.json()
        disease_labels = {
            node["label"]
            for node in body.get("nodes", [])
            if node.get("category") == "disease"
        }
        allergy_labels = {
            node["label"]
            for node in body.get("nodes", [])
            if node.get("category") == "allergy"
        }
        drug_labels = {
            node["label"]
            for node in body.get("nodes", [])
            if node.get("category") == "drug"
        }

        assert expected[key]["diseases"] <= disease_labels, (key, disease_labels, body)
        assert expected[key]["allergies"] <= allergy_labels, (key, allergy_labels, body)
        assert expected[key]["drugs"] <= drug_labels, (key, drug_labels, body)

        risks = client.get(
            f"/api/v1/households/{household_id}/members/{member_id}/risks",
            headers=OWNER_HEADERS,
        )
        assert risks.status_code == 200, risks.text
        alerts = risks.json()["alerts"]
        rules = {alert.get("rule_id") for alert in alerts}
        assert "allergy_conflict" in rules, (key, alerts)

    # Grandma: aspirin allergy vs aspirin tablet; Grandpa: penicillin vs penicillin V.
    grandma_risks = client.get(
        f"/api/v1/households/{household_id}/members/{members['grandma']}/risks",
        headers=OWNER_HEADERS,
    ).json()["alerts"]
    grandma_msgs = " ".join(str(a.get("message") or "") for a in grandma_risks)
    assert "阿司匹林" in grandma_msgs

    grandpa_risks = client.get(
        f"/api/v1/households/{household_id}/members/{members['grandpa']}/risks",
        headers=OWNER_HEADERS,
    ).json()["alerts"]
    grandpa_msgs = " ".join(str(a.get("message") or "") for a in grandpa_risks)
    assert "青霉素" in grandpa_msgs
