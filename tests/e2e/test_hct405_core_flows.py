"""HCT-405 core API end-to-end regression scenarios using synthetic data only."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

OWNER_HEADERS = {"X-Actor-Id": "owner"}


def create_household_and_member(client: TestClient, name: str = "E2E household") -> tuple[str, str]:
    household = client.post(
        "/api/v1/households",
        headers=OWNER_HEADERS,
        json={"name": name},
    )
    assert household.status_code == 201, household.text

    member = client.post(
        f"/api/v1/households/{household.json()['id']}/members",
        headers=OWNER_HEADERS,
        json={"display_name": "Synthetic member", "role": "SELF"},
    )
    assert member.status_code == 201, member.text
    return household.json()["id"], member.json()["id"]


def grant_caregiver(
    client: TestClient,
    household_id: str,
    member_id: str,
    *,
    actions: list[str],
    purpose: str = "family-care",
) -> dict:
    response = client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers=OWNER_HEADERS,
        json={
            "member_id": member_id,
            "grantee_actor_id": "caregiver",
            "data_fields": ["health_events"],
            "actions": actions,
            "purpose": purpose,
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def caregiver_headers(purpose: str = "family-care") -> dict[str, str]:
    return {"X-Actor-Id": "caregiver", "X-Access-Purpose": purpose}


def append_confirmed_event(
    client: TestClient,
    household_id: str,
    member_id: str,
    event_type: str,
    payload: dict[str, object],
) -> dict:
    response = client.post(
        f"/api/v1/households/{household_id}/events",
        headers=OWNER_HEADERS,
        json={
            "member_id": member_id,
            "event_type": event_type,
            "confirmation_status": "CONFIRMED",
            "payload": payload,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_authorized_caregiver_can_trace_confirmed_events_to_risk_evidence(
    client: TestClient,
) -> None:
    household_id, member_id = create_household_and_member(client)
    grant_caregiver(client, household_id, member_id, actions=["READ_EVENTS", "WRITE_EVENTS"])
    allergy = append_confirmed_event(
        client, household_id, member_id, "allergy_added", {"allergy": "aspirin"}
    )
    medication = append_confirmed_event(
        client, household_id, member_id, "medication_added", {"drug": "aspirin"}
    )

    timeline = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/timeline",
        headers=caregiver_headers(),
    )
    assert timeline.status_code == 200, timeline.text
    assert [event["id"] for event in timeline.json()] == [allergy["id"], medication["id"]]

    projection = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/state",
        headers=OWNER_HEADERS,
    )
    assert projection.status_code == 200, projection.text
    assert projection.json()["last_event_id"] == medication["id"]
    assert projection.json()["state"]["events_count"] == 2

    risks = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/risks",
        headers=caregiver_headers(),
    )
    assert risks.status_code == 200, risks.text
    conflict = next(
        alert for alert in risks.json()["alerts"] if alert["rule_id"] == "allergy_conflict"
    )
    assert conflict["level"] == "SEVERE"

    evidence = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/risks/allergy_conflict",
        headers=caregiver_headers(),
    )
    assert evidence.status_code == 200, evidence.text
    assert {source["id"] for source in evidence.json()["source_events"]} == {medication["id"]}
    assert all(
        "payload" not in source and "evidence" not in source
        for source in evidence.json()["source_events"]
    )


def test_unconfirmed_event_does_not_enter_timeline_or_projection(client: TestClient) -> None:
    household_id, member_id = create_household_and_member(client)
    response = client.post(
        f"/api/v1/households/{household_id}/events",
        headers=OWNER_HEADERS,
        json={
            "member_id": member_id,
            "event_type": "medication_added",
            "confirmation_status": "UNCONFIRMED",
            "payload": {"drug": "unverified"},
        },
    )
    assert response.status_code == 201, response.text

    timeline = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/timeline",
        headers=OWNER_HEADERS,
    )
    assert timeline.status_code == 200, timeline.text
    assert timeline.json() == []

    projection = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/state",
        headers=OWNER_HEADERS,
    )
    assert projection.status_code == 404


def test_caregiver_plan_actions_require_write_authorization(client: TestClient) -> None:
    household_id, member_id = create_household_and_member(client)
    grant_caregiver(
        client,
        household_id,
        member_id,
        actions=["WRITE_EVENTS"],
        purpose="plan-care",
    )
    headers = caregiver_headers("plan-care")

    actions = [
        ("confirm", {"plan_event_id": "plan-confirm"}, "plan_confirmed"),
        ("defer", {"plan_event_id": "plan-defer", "delay_hours": 6}, "plan_deferred"),
        ("skip", {"plan_event_id": "plan-skip", "reason": "not available"}, "plan_skipped"),
    ]
    for action, params, expected_type in actions:
        response = client.post(
            f"/api/v1/households/{household_id}/members/{member_id}/plans/{action}",
            headers=headers,
            params=params,
        )
        assert response.status_code == 201, response.text
        assert response.json()["event_type"] == expected_type
        assert response.json()["confirmation_status"] == "CONFIRMED"


def test_revocation_blocks_caregiver_immediately(client: TestClient) -> None:
    household_id, member_id = create_household_and_member(client)
    authorization = grant_caregiver(client, household_id, member_id, actions=["READ_EVENTS"])
    append_confirmed_event(client, household_id, member_id, "medication_added", {"drug": "aspirin"})

    before = client.get(
        f"/api/v1/households/{household_id}/events",
        headers=caregiver_headers(),
    )
    assert before.status_code == 200, before.text

    revoke = client.post(
        f"/api/v1/households/{household_id}/authorizations/{authorization['id']}/revoke",
        headers=OWNER_HEADERS,
        json={"expected_version": authorization["version"]},
    )
    assert revoke.status_code == 200, revoke.text

    after = client.get(
        f"/api/v1/households/{household_id}/events",
        headers=caregiver_headers(),
    )
    assert after.status_code == 404


def test_cross_household_timeline_is_not_visible_to_caregiver(client: TestClient) -> None:
    household_id, member_id = create_household_and_member(client, "Authorized household")
    other_household_id, other_member_id = create_household_and_member(client, "Other household")
    grant_caregiver(client, household_id, member_id, actions=["READ_EVENTS"])
    append_confirmed_event(
        client, other_household_id, other_member_id, "medication_added", {"drug": "aspirin"}
    )

    response = client.get(
        f"/api/v1/households/{other_household_id}/members/{other_member_id}/timeline",
        headers=caregiver_headers(),
    )
    assert response.status_code == 404


def test_capabilities_keep_unreleased_e2e_dependencies_explicit(client: TestClient) -> None:
    response = client.get("/api/v1/meta/capabilities")
    assert response.status_code == 200, response.text
    unavailable = set(response.json()["unavailable"])
    assert {"vision-inference", "llm-cloud", "external-web"}.issubset(unavailable)
