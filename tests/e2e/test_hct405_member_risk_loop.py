"""HCT-405 A2: confirmed facts → rule alerts → member portal read.

Maps to acceptance-gate scenario ``confirmed_event_to_rule_alert``.
Does not claim released-model or real OCR accuracy.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

OWNER = "risk-loop-owner"
MEMBER = "risk-loop-grandma"
OTHER = "risk-loop-grandpa"


def _setup(client: TestClient) -> tuple[str, str, str]:
    household = client.post(
        "/api/v1/households",
        headers={"X-Actor-Id": OWNER},
        json={"name": "规则提醒闭环家庭"},
    )
    assert household.status_code == 201, household.text
    household_id = household.json()["id"]
    grandma = client.post(
        f"/api/v1/households/{household_id}/members",
        headers={"X-Actor-Id": OWNER},
        json={"display_name": "奶奶", "role": "DEPENDENT", "actor_id": MEMBER},
    )
    assert grandma.status_code == 201, grandma.text
    grandpa = client.post(
        f"/api/v1/households/{household_id}/members",
        headers={"X-Actor-Id": OWNER},
        json={"display_name": "爷爷", "role": "DEPENDENT", "actor_id": OTHER},
    )
    assert grandpa.status_code == 201, grandpa.text
    return household_id, grandma.json()["id"], grandpa.json()["id"]


def _confirm(
    client: TestClient,
    household_id: str,
    member_id: str,
    event_type: str,
    payload: dict,
    key: str,
) -> dict:
    response = client.post(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": OWNER},
        json={
            "member_id": member_id,
            "event_type": event_type,
            "source": "MANUAL",
            "confirmation_status": "CONFIRMED",
            "payload": payload,
            "idempotency_key": key,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_confirmed_allergy_and_drug_surface_member_risk(client: TestClient) -> None:
    """管理员确认过敏+药品后，奶奶前台可读到 allergy_conflict 提醒。"""
    household_id, grandma_id, grandpa_id = _setup(client)

    # 未确认药品不得进入规则投影。
    unconfirmed = client.post(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": OWNER},
        json={
            "member_id": grandma_id,
            "event_type": "medication_added",
            "source": "MANUAL",
            "confirmation_status": "UNCONFIRMED",
            "payload": {"drug": "aspirin"},
            "idempotency_key": "risk-loop-unconfirmed",
        },
    )
    assert unconfirmed.status_code == 201
    empty_risks = client.get(
        f"/api/v1/households/{household_id}/members/{grandma_id}/risks",
        headers={"X-Actor-Id": MEMBER, "X-Access-Purpose": "family-care"},
    )
    assert empty_risks.status_code == 200
    assert empty_risks.json()["alerts"] == []

    _confirm(
        client,
        household_id,
        grandma_id,
        "allergy_added",
        {"allergy": "aspirin"},
        "risk-loop-allergy",
    )
    _confirm(
        client,
        household_id,
        grandma_id,
        "medication_added",
        {"drug": "aspirin"},
        "risk-loop-drug",
    )

    risks = client.get(
        f"/api/v1/households/{household_id}/members/{grandma_id}/risks",
        headers={"X-Actor-Id": MEMBER, "X-Access-Purpose": "family-care"},
    )
    assert risks.status_code == 200, risks.text
    body = risks.json()
    assert body["member_id"] == grandma_id
    conflict = next(alert for alert in body["alerts"] if alert["rule_id"] == "allergy_conflict")
    assert conflict["level"] == "SEVERE"
    assert "aspirin" in conflict["message"].lower()
    assert body["severe_count"] >= 1

    # 成员不能读取爷爷范围的风险。
    other = client.get(
        f"/api/v1/households/{household_id}/members/{grandpa_id}/risks",
        headers={"X-Actor-Id": MEMBER, "X-Access-Purpose": "family-care"},
    )
    assert other.status_code == 404

    # 重复成分：两剂带相同 ingredient 的已确认药品应触发 duplicate_ingredient。
    _confirm(
        client,
        household_id,
        grandma_id,
        "medication_added",
        {"drug": "阿司匹林肠溶片", "ingredient": "aspirin"},
        "risk-loop-dup-a",
    )
    _confirm(
        client,
        household_id,
        grandma_id,
        "medication_added",
        {"drug": "复方阿司匹林", "ingredient": "aspirin"},
        "risk-loop-dup-b",
    )
    risks_after = client.get(
        f"/api/v1/households/{household_id}/members/{grandma_id}/risks",
        headers={"X-Actor-Id": MEMBER, "X-Access-Purpose": "family-care"},
    )
    assert risks_after.status_code == 200
    rule_ids = {alert["rule_id"] for alert in risks_after.json()["alerts"]}
    assert "allergy_conflict" in rule_ids
    assert "duplicate_ingredient" in rule_ids


def test_member_cannot_acknowledge_risk_without_grant(client: TestClient) -> None:
    """成员前台只读风险摘要；确认回执仍需 ACK_RISK 授权或管理员。"""
    household_id, grandma_id, _ = _setup(client)
    _confirm(
        client,
        household_id,
        grandma_id,
        "allergy_added",
        {"allergy": "penicillin"},
        "ack-allergy",
    )
    _confirm(
        client,
        household_id,
        grandma_id,
        "medication_added",
        {"drug": "penicillin"},
        "ack-drug",
    )
    risks = client.get(
        f"/api/v1/households/{household_id}/members/{grandma_id}/risks",
        headers={"X-Actor-Id": MEMBER, "X-Access-Purpose": "family-care"},
    ).json()
    conflict = next(alert for alert in risks["alerts"] if alert["rule_id"] == "allergy_conflict")

    denied = client.post(
        f"/api/v1/households/{household_id}/members/{grandma_id}/risks/allergy_conflict/acknowledge",
        headers={
            "X-Actor-Id": MEMBER,
            "X-Access-Purpose": "family-care",
            "Idempotency-Key": "member-ack-denied",
        },
        json={
            "risk_fingerprint": conflict["risk_fingerprint"],
            "rule_version": risks["ruleset_version"],
        },
    )
    assert denied.status_code == 404
