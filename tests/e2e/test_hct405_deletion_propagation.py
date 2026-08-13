"""HCT-405 API E2E: full household deletion propagation across local stores."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.knowledge import KnowledgeChunk, KnowledgeDocument
from app.models import HealthEvent, Household, Member, VisionTask

OWNER = {"X-Actor-Id": "e2e-owner"}
CAREGIVER = {"X-Actor-Id": "e2e-caregiver", "X-Access-Purpose": "family-care"}
OTHER_OWNER = {"X-Actor-Id": "e2e-other-owner"}
STRANGER = {"X-Actor-Id": "e2e-stranger"}


def _create_household(client: TestClient, headers: dict[str, str], name: str) -> tuple[str, str]:
    household = client.post("/api/v1/households", headers=headers, json={"name": name})
    assert household.status_code == 201, household.text
    household_id = household.json()["id"]
    member = client.post(
        f"/api/v1/households/{household_id}/members",
        headers=headers,
        json={"display_name": "Synthetic member", "role": "SELF"},
    )
    assert member.status_code == 201, member.text
    return household_id, member.json()["id"]


def test_household_erasure_propagates_to_files_index_cache_and_backup_skip(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(get_settings(), "file_root", str(tmp_path))

    household_id, member_id = _create_household(client, OWNER, "Erasure household")
    other_id, other_member_id = _create_household(client, OTHER_OWNER, "Untouched household")

    grant = client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers=OWNER,
        json={
            "member_id": member_id,
            "grantee_actor_id": "e2e-caregiver",
            "data_fields": ["health_events"],
            "actions": ["READ_EVENTS", "WRITE_EVENTS"],
            "purpose": "family-care",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    assert grant.status_code == 201, grant.text

    event = client.post(
        f"/api/v1/households/{household_id}/events",
        headers=OWNER,
        json={
            "member_id": member_id,
            "event_type": "care_note_added",
            "confirmation_status": "CONFIRMED",
            "payload": {"item": "synthetic-care-item"},
        },
    )
    assert event.status_code == 201, event.text
    event_id = event.json()["id"]
    original_payload = event.json()["payload"]

    other_event = client.post(
        f"/api/v1/households/{other_id}/events",
        headers=OTHER_OWNER,
        json={
            "member_id": other_member_id,
            "event_type": "care_note_added",
            "confirmation_status": "CONFIRMED",
            "payload": {"item": "other-household-item"},
        },
    )
    assert other_event.status_code == 201, other_event.text

    sample = client.post(
        f"/api/v1/households/{household_id}/hard-samples",
        headers=OWNER,
        json={
            "source_event_id": event_id,
            "member_id": member_id,
            "category": "hard_font",
            "note": "HCT-405 synthetic household erasure",
        },
    )
    assert sample.status_code == 201, sample.text

    knowledge = client.post(
        "/api/v1/knowledge/documents",
        headers=OWNER,
        json={
            "title": "Household care evidence",
            "content": "合成家庭照护证据，删除传播后不得再检索。",
            "source": "hct405-erasure",
            "version": "e2e-v1",
            "permission_scope": {"household_ids": [household_id], "member_ids": [member_id]},
        },
    )
    assert knowledge.status_code == 201, knowledge.text
    document_id = knowledge.json()["id"]

    storage_key = "synthetic-object.bin"
    (tmp_path / storage_key).write_bytes(b"synthetic-object")
    cache_file = tmp_path / "cache" / member_id / "entry.bin"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_bytes(b"cached-entry")
    db_session.add(
        VisionTask(
            household_id=household_id,
            member_id=member_id,
            file_id=storage_key,
            task_type="ocr",
            status="queued",
            created_by="e2e-owner",
        )
    )
    db_session.commit()

    timeline = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/timeline",
        headers=CAREGIVER,
    )
    assert timeline.status_code == 200, timeline.text

    denied = client.delete(f"/api/v1/households/{household_id}", headers=CAREGIVER)
    assert denied.status_code == 404
    stranger = client.delete(f"/api/v1/households/{household_id}", headers=STRANGER)
    assert stranger.status_code == 404

    erased = client.delete(f"/api/v1/households/{household_id}", headers=OWNER)
    assert erased.status_code == 200, erased.text
    body = erased.json()
    task_id = body["id"]
    assert body["status"] == "completed"
    assert body["error_layers"] == []
    for layer in ("database", "files", "vectors", "cache", "hard_samples", "backups", "audit"):
        assert body["layers"][layer]["status"] == "completed"
    assert body["scope"]["event_rows_retained"] == 1
    assert body["scope"]["files_deleted"] >= 1
    serialized = json.dumps(body)
    assert "payload" not in serialized
    assert "display_name" not in serialized
    assert "synthetic-care-item" not in serialized

    stored_event = db_session.get(HealthEvent, event_id)
    assert stored_event is not None
    assert stored_event.payload == original_payload
    assert stored_event.confirmation_status == "CONFIRMED"

    listed = client.get("/api/v1/households", headers=OWNER)
    assert listed.status_code == 200
    assert listed.json() == []
    caregiver_list = client.get("/api/v1/households", headers=CAREGIVER)
    assert caregiver_list.status_code == 200
    assert caregiver_list.json() == []

    assert client.get(f"/api/v1/households/{household_id}/members", headers=OWNER).status_code == 404
    assert client.get(
        f"/api/v1/households/{household_id}/events",
        headers=OWNER,
    ).status_code == 404
    assert client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/timeline",
        headers=CAREGIVER,
    ).status_code == 404
    assert client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/state",
        headers=OWNER,
    ).status_code == 404
    assert client.get(f"/api/v1/files/{storage_key}", headers=OWNER).status_code == 404
    assert client.get(
        f"/api/v1/households/{household_id}/hard-samples",
        headers=OWNER,
    ).status_code == 404

    retrieve = client.post(
        "/api/v1/knowledge/retrieve",
        headers=OWNER,
        json={"query": "合成家庭照护证据", "household_id": household_id, "member_id": member_id},
    )
    assert retrieve.status_code == 200, retrieve.text
    assert retrieve.json()["results"] == []

    stored_doc = db_session.get(KnowledgeDocument, document_id)
    assert stored_doc is not None
    assert stored_doc.status == "deleted"
    chunk_count = db_session.scalar(
        select(func.count())
        .select_from(KnowledgeChunk)
        .where(KnowledgeChunk.document_id == document_id)
    )
    assert chunk_count == 0
    assert not (tmp_path / storage_key).exists()
    assert not cache_file.exists()

    marker_path = tmp_path / "backup-skip" / f"{task_id}.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["deletion_id"] == task_id
    assert marker["skip_on_restore"] is True
    assert marker["household_id"] == household_id
    assert member_id in marker["member_ids"]
    assert "payload" not in marker
    assert "display_name" not in json.dumps(marker)

    status = client.get(f"/api/v1/erasure-tasks/{task_id}", headers=OWNER)
    assert status.status_code == 200, status.text
    assert status.json()["layers"]["backups"]["status"] == "completed"
    assert client.get(f"/api/v1/erasure-tasks/{task_id}", headers=CAREGIVER).status_code == 404

    replay = client.delete(f"/api/v1/households/{household_id}", headers=OWNER)
    assert replay.status_code == 200
    assert replay.json()["id"] == task_id

    other_events = client.get(f"/api/v1/households/{other_id}/events", headers=OTHER_OWNER)
    assert other_events.status_code == 200, other_events.text
    assert [item["id"] for item in other_events.json()] == [other_event.json()["id"]]
    other_listed = client.get("/api/v1/households", headers=OTHER_OWNER)
    assert [item["id"] for item in other_listed.json()] == [other_id]

    db_session.expire_all()
    assert db_session.get(Household, household_id).deleted_at is not None
    assert db_session.get(Member, member_id).deleted_at is not None
    assert db_session.get(Household, other_id).deleted_at is None
    assert db_session.get(Member, other_member_id).deleted_at is None
