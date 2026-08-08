"""
HCT-103: Idempotency key and compensation event tests.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def household_id(client: TestClient) -> str:
    resp = client.post(
        "/api/v1/households",
        json={"name": "test-household-hct103"},
        headers={"X-Actor-ID": "actor-test-103"},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


@pytest.fixture
def member_id(client: TestClient, household_id: str) -> str:
    resp = client.post(
        f"/api/v1/households/{household_id}/members",
        json={"display_name": "test-member", "role": "DEPENDENT"},
        headers={"X-Actor-ID": "actor-test-103"},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


class TestIdempotency:
    def test_duplicate_idempotency_key_returns_existing(self, client, household_id, member_id):
        """Same idempotency_key + same payload → 200 with existing event."""
        payload = {
            "member_id": member_id,
            "event_type": "medication_added",
            "source": "MANUAL",
            "confirmation_status": "CONFIRMED",
            "payload": {"drug": "aspirin"},
            "idempotency_key": "idem-001",
        }
        resp1 = client.post(
            f"/api/v1/households/{household_id}/events",
            json=payload,
            headers={"X-Actor-ID": "actor-test-103"},
        )
        assert resp1.status_code == 201

        resp2 = client.post(
            f"/api/v1/households/{household_id}/events",
            json=payload,
            headers={"X-Actor-ID": "actor-test-103"},
        )
        assert resp2.status_code == 201
        assert resp2.json()["id"] == resp1.json()["id"]

    def test_idempotency_key_conflict_rejected(self, client, household_id, member_id):
        """Same idempotency_key + different payload → 409."""
        payload1 = {
            "member_id": member_id,
            "event_type": "medication_added",
            "source": "MANUAL",
            "confirmation_status": "CONFIRMED",
            "payload": {"drug": "aspirin"},
            "idempotency_key": "idem-002",
        }
        resp1 = client.post(
            f"/api/v1/households/{household_id}/events",
            json=payload1,
            headers={"X-Actor-ID": "actor-test-103"},
        )
        assert resp1.status_code == 201

        payload2 = {
            "member_id": member_id,
            "event_type": "medication_added",
            "source": "MANUAL",
            "confirmation_status": "CONFIRMED",
            "payload": {"drug": "ibuprofen"},
            "idempotency_key": "idem-002",
        }
        resp2 = client.post(
            f"/api/v1/households/{household_id}/events",
            json=payload2,
            headers={"X-Actor-ID": "actor-test-103"},
        )
        assert resp2.status_code == 409
        assert resp2.json()["detail"] == "IDEMPOTENCY_CONFLICT"

    def test_no_idempotency_key_allows_duplicates(self, client, household_id, member_id):
        """Without idempotency_key, duplicate submissions create separate events."""
        payload = {
            "member_id": member_id,
            "event_type": "medication_added",
            "source": "MANUAL",
            "confirmation_status": "CONFIRMED",
            "payload": {"drug": "aspirin"},
        }
        resp1 = client.post(
            f"/api/v1/households/{household_id}/events",
            json=payload,
            headers={"X-Actor-ID": "actor-test-103"},
        )
        assert resp1.status_code == 201

        resp2 = client.post(
            f"/api/v1/households/{household_id}/events",
            json=payload,
            headers={"X-Actor-ID": "actor-test-103"},
        )
        assert resp2.status_code == 201
        assert resp2.json()["id"] != resp1.json()["id"]


class TestCompensation:
    def test_compensation_event_references_original(self, client, household_id, member_id):
        """Compensation event links to the original event."""
        resp1 = client.post(
            f"/api/v1/households/{household_id}/events",
            json={
                "member_id": member_id,
                "event_type": "medication_added",
                "source": "MANUAL",
                "confirmation_status": "CONFIRMED",
                "payload": {"drug": "wrong_drug"},
            },
            headers={"X-Actor-ID": "actor-test-103"},
        )
        assert resp1.status_code == 201
        original_id = resp1.json()["id"]

        resp2 = client.post(
            f"/api/v1/households/{household_id}/events",
            json={
                "member_id": member_id,
                "event_type": "medication_corrected",
                "source": "MANUAL",
                "confirmation_status": "CONFIRMED",
                "payload": {"drug": "correct_drug"},
                "compensates_event_id": original_id,
            },
            headers={"X-Actor-ID": "actor-test-103"},
        )
        assert resp2.status_code == 201
        assert resp2.json()["compensates_event_id"] == original_id

    def test_compensation_event_not_found(self, client, household_id, member_id):
        """Compensating a non-existent event → 404."""
        resp = client.post(
            f"/api/v1/households/{household_id}/events",
            json={
                "member_id": member_id,
                "event_type": "medication_corrected",
                "source": "MANUAL",
                "confirmation_status": "CONFIRMED",
                "payload": {"drug": "correct_drug"},
                "compensates_event_id": "00000000-0000-0000-0000-000000000000",
            },
            headers={"X-Actor-ID": "actor-test-103"},
        )
        assert resp.status_code == 404
        assert "COMPENSATES_EVENT_NOT_FOUND" in resp.json()["detail"]


