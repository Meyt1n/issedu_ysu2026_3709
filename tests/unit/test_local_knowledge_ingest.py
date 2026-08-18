"""Regression tests for the approved local knowledge ingestion command."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.knowledge import KnowledgeChunk, KnowledgeDocument, compute_index_checksum
from ingest_local_knowledge import IngestError, ingest_manifest


def _write_manifest(
    tmp_path: Path,
    *,
    content: str = "合成知识要求先核对已确认事实，并联系医生或药师。",
    status: str = "approved",
    relative_path: str = "knowledge.md",
    content_sha256: str | None = None,
) -> Path:
    source_root = tmp_path / "source"
    source_root.mkdir(parents=True, exist_ok=True)
    source_file = source_root / relative_path
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text(content, encoding="utf-8")
    manifest = {
        "manifest_version": "1",
        "status": status,
        "documents": [
            {
                "path": relative_path,
                "title": "合成照护知识",
                "source": "synthetic-local",
                "license": "internal-demo",
                "version": "demo-v1",
                "permission_scope": {},
                "content_sha256": content_sha256
                or hashlib.sha256(content.encode("utf-8")).hexdigest(),
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return manifest_path


def test_ingest_is_atomic_and_idempotent(db_session, tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path)

    first = ingest_manifest(
        db_session,
        manifest_path=manifest,
        source_root=tmp_path / "source",
        actor_id="local-admin",
        index_version="local-v1",
    )
    second = ingest_manifest(
        db_session,
        manifest_path=manifest,
        source_root=tmp_path / "source",
        actor_id="local-admin",
        index_version="local-v1",
    )

    assert first["created"][0]["title"] == "合成照护知识"
    assert second["created"] == []
    assert second["actions"][0]["action"] == "skip"
    assert first["index"]["checksum"] == second["index"]["checksum"]
    assert db_session.query(KnowledgeDocument).count() == 1


def test_ingest_rejects_unapproved_or_outside_files(db_session, tmp_path: Path) -> None:
    unapproved = _write_manifest(tmp_path / "unapproved", status="pending")
    with pytest.raises(IngestError, match="MANIFEST_NOT_APPROVED"):
        ingest_manifest(
            db_session,
            manifest_path=unapproved,
            source_root=unapproved.parent / "source",
            actor_id="local-admin",
            index_version="local-v1",
        )

    outside = _write_manifest(tmp_path / "outside", relative_path="../escape.md")
    with pytest.raises(IngestError, match="PATH_OUTSIDE_SOURCE_ROOT"):
        ingest_manifest(
            db_session,
            manifest_path=outside,
            source_root=outside.parent / "source",
            actor_id="local-admin",
            index_version="local-v2",
        )


def test_ingest_rejects_content_hash_mismatch(db_session, tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path, content_sha256="0" * 64)

    with pytest.raises(IngestError, match="CONTENT_HASH_MISMATCH"):
        ingest_manifest(
            db_session,
            manifest_path=manifest,
            source_root=tmp_path / "source",
            actor_id="local-admin",
            index_version="local-v1",
        )
    assert db_session.query(KnowledgeDocument).count() == 0


def test_index_checksum_ignores_generated_chunk_uuid(db_session) -> None:
    from app.knowledge import add_document

    document = add_document(
        db_session,
        title="Checksum source",
        content="固定内容用于重建校验。",
        source="synthetic-local",
        created_by="local-admin",
    )
    db_session.commit()
    before = compute_index_checksum(db_session)
    chunk = db_session.query(KnowledgeChunk).filter_by(document_id=document.id).one()
    chunk.id = "different-generated-id"
    db_session.commit()

    assert compute_index_checksum(db_session) == before
