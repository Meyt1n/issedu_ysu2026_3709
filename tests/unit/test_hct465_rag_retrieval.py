"""Contract tests for the pluggable local-first RAG retrieval port."""

from __future__ import annotations

import math

import pytest
from ai.rag.retrieval import ChunkHit, LocalKnowledgeRetriever, RetrievalScope

from app.knowledge import add_document


def test_local_adapter_returns_citation_safe_chunk_hits(db_session) -> None:
    add_document(
        db_session,
        title="本地用药教学卡",
        content="阿莫西林胶囊的保存和用法说明。",
        source="synthetic-local",
        version="demo-v1",
        created_by="rag-owner",
    )
    db_session.commit()

    hits = LocalKnowledgeRetriever(db_session).retrieve(
        "阿莫西林 用法",
        RetrievalScope(actor_id="rag-owner"),
    )

    assert hits
    assert isinstance(hits[0], ChunkHit)
    payload = hits[0].as_dict()
    assert {"chunk_id", "document_id", "version", "text", "score"} <= payload.keys()
    assert payload["version"] == "demo-v1"
    assert isinstance(payload["matched_terms"], list)


def test_scope_is_forwarded_to_the_existing_permission_gate(db_session) -> None:
    add_document(
        db_session,
        title="私有教学卡",
        content="阿莫西林 用法",
        source="synthetic-private",
        created_by="owner-a",
        permission_scope={"created_by": "owner-a"},
    )
    db_session.commit()

    with pytest.raises(ValueError, match="NO_AUTHORISED_DOCUMENTS"):
        LocalKnowledgeRetriever(db_session).retrieve(
            "阿莫西林",
            RetrievalScope(actor_id="owner-b"),
        )


def test_port_validates_top_k_and_hit_shape() -> None:
    with pytest.raises(ValueError, match="TOP_K_INVALID"):
        LocalKnowledgeRetriever(object()).retrieve(
            "anything",
            RetrievalScope(actor_id="owner"),
            top_k=0,
        )

    with pytest.raises(ValueError, match="RAG_HIT_INVALID"):
        ChunkHit.from_mapping(
            {
                "chunk_id": "chunk-1",
                "document_id": "doc-1",
                "version": "v1",
                "text": "evidence",
                "score": math.nan,
            }
        )


def test_retrieval_scope_rejects_missing_actor() -> None:
    with pytest.raises(ValueError, match="ACTOR_REQUIRED"):
        RetrievalScope(actor_id=" ")
