"""HCT-405 household erasure unit coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.erasure import (
    assert_redacted_audit,
    request_household_erasure,
)
from app.knowledge import KnowledgeChunk, add_document
from app.models import HealthEvent, Household, Member, VisionTask


def test_redacted_audit_rejects_health_fields() -> None:
    with pytest.raises(ValueError, match="ERASURE_AUDIT_LEAK"):
        assert_redacted_audit({"payload": {"item": "hidden"}})
    assert_redacted_audit(
        {
            "deletion_id": "task-1",
            "member_ids": ["member-1"],
            "files_deleted": 1,
        }
    )


def test_household_erasure_hides_rows_and_writes_skip_marker(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "file_root", str(tmp_path))
    household = Household(name="Erasure household", created_by="owner")
    db_session.add(household)
    db_session.flush()
    member = Member(
        household_id=household.id,
        display_name="Synthetic member",
        role="SELF",
    )
    other = Household(name="Other household", created_by="other-owner")
    db_session.add_all([member, other])
    db_session.flush()
    other_member = Member(
        household_id=other.id,
        display_name="Other member",
        role="SELF",
    )
    db_session.add(other_member)
    db_session.flush()

    event = HealthEvent(
        household_id=household.id,
        member_id=member.id,
        sequence_no=1,
        event_type="care_note_added",
        source="MANUAL",
        confirmation_status="CONFIRMED",
        payload={"item": "synthetic-care-item"},
        evidence={},
        created_by="owner",
        confirmed_by="owner",
        correlation_id="erasure-unit",
        schema_version=1,
    )
    db_session.add(event)
    original_payload = dict(event.payload)

    storage_key = "synthetic-object.bin"
    (tmp_path / storage_key).write_bytes(b"synthetic-bytes")
    cache_file = tmp_path / "cache" / member.id / "entry.bin"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_bytes(b"cached")
    db_session.add(
        VisionTask(
            household_id=household.id,
            member_id=member.id,
            file_id=storage_key,
            task_type="ocr",
            status="queued",
            created_by="owner",
        )
    )

    scoped = add_document(
        db_session,
        title="Household evidence",
        content="合成家庭知识块，删除后不得再检索。",
        source="hct405-erasure",
        created_by="owner",
        permission_scope={"household_ids": [household.id]},
    )
    kept = add_document(
        db_session,
        title="Other household evidence",
        content="其他家庭的知识应保持可检索。",
        source="hct405-erasure",
        created_by="other-owner",
        permission_scope={"household_ids": [other.id]},
    )
    db_session.commit()

    task = request_household_erasure(db_session, household, actor_id="owner")
    db_session.commit()
    db_session.refresh(task)

    assert task.status == "completed"
    assert task.error_layers == []
    for layer in ("database", "files", "vectors", "cache", "hard_samples", "backups", "audit"):
        assert task.layers[layer]["status"] == "completed"
    assert_redacted_audit(task.scope)
    assert "payload" not in json.dumps(task.scope)
    assert member.display_name not in json.dumps(task.scope)

    db_session.refresh(household)
    db_session.refresh(member)
    db_session.refresh(event)
    db_session.refresh(scoped)
    db_session.refresh(kept)
    assert household.deleted_at is not None
    assert member.deleted_at is not None
    assert event.payload == original_payload
    assert event.confirmation_status == "CONFIRMED"
    assert not (tmp_path / storage_key).exists()
    assert not cache_file.exists()
    assert scoped.status == "deleted"
    assert db_session.scalar(
        select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.document_id == scoped.id)
    ) == 0
    assert kept.status == "active"
    assert db_session.scalar(
        select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.document_id == kept.id)
    ) >= 1

    marker_path = tmp_path / "backup-skip" / f"{task.id}.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["deletion_id"] == task.id
    assert marker["skip_on_restore"] is True
    assert marker["household_id"] == household.id
    assert_redacted_audit(marker)

    again = request_household_erasure(db_session, household, actor_id="owner")
    assert again.id == task.id
