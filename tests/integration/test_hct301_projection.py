"""HCT-301: Timeline and projection integration tests."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import HealthEvent
from app.projection import build_relationship_graph, get_timeline


class TestTimeline:
    def test_empty_timeline(self, db_session: Session):
        events = get_timeline(db_session, "nonexistent-member")
        assert events == []

    def test_timeline_ordered(self, db_session: Session, client: TestClient):
        hid = client.post("/api/v1/households", json={"name": "tl-house"},
                          headers={"X-Actor-ID": "tl-actor"}).json()["id"]
        mid = client.post(f"/api/v1/households/{hid}/members",
                          json={"display_name": "tl-member", "role": "DEPENDENT"},
                          headers={"X-Actor-ID": "tl-actor"}).json()["id"]
        for i in range(3):
            client.post(f"/api/v1/households/{hid}/events",
                        json={"member_id": mid, "event_type": "medication_added",
                              "payload": {"drug": f"drug-{i}"},
                              "confirmation_status": "CONFIRMED"},
                        headers={"X-Actor-ID": "tl-actor"})

        resp = client.get(f"/api/v1/households/{hid}/members/{mid}/timeline",
                          headers={"X-Actor-ID": "tl-actor"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3
        assert data[0]["event_type"] == "medication_added"


class TestRelationshipGraph:
    def test_build_graph_from_events(self):
        mock_events = [
            _mock_event("medication_added", {"drug": "aspirin", "ingredient": "asa"}),
            _mock_event("allergy_added", {"allergy": "penicillin"}),
            _mock_event("disease_added", {"disease": "hypertension"}),
        ]
        graph = build_relationship_graph(mock_events)
        assert len(graph["drugs"]) == 1
        assert graph["drugs"][0]["name"] == "aspirin"
        assert len(graph["allergies"]) == 1
        assert len(graph["diseases"]) == 1

    def test_compensation_removes_original(self):
        original = _mock_event("medication_added", {"drug": "wrong"})
        comp = _mock_event("COMPENSATION", {}, compensates_event_id=original.id)
        graph = build_relationship_graph([original, comp])
        assert len(graph["drugs"]) == 0

    def test_allergy_removed(self):
        add = _mock_event("allergy_added", {"allergy": "penicillin"})
        remove = _mock_event("allergy_removed", {"allergy": "penicillin"})
        graph = build_relationship_graph([add, remove])
        assert len(graph["allergies"]) == 0


def _mock_event(
    event_type: str,
    payload: dict,
    compensates_event_id: str | None = None,
) -> HealthEvent:
    e = HealthEvent(
        id=f"evt-{event_type}-{hash(frozenset(payload.items()))}",
        household_id="h",
        member_id="m",
        event_type=event_type,
        source="MANUAL",
        confirmation_status="CONFIRMED",
        payload=payload,
        created_by="a",
        compensates_event_id=compensates_event_id,
    )
    e.created_at = __import__("datetime").datetime(2026, 1, 1)
    return e
