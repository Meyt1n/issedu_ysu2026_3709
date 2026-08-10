"""HCT-401: Tests for knowledge store — CRUD, TF-IDF retrieval, permission filtering."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.knowledge import (
    KnowledgeChunk,
    KnowledgeDocument,
    _check_permission,
    _content_hash,
    _tf,
    _tokenize,
    add_document,
    create_index_snapshot,
    delete_document,
    retrieve,
)

# ── Helpers ────────────────────────────────────────────────────────────

def _make_doc(session, *, title="Test Doc", content="阿莫西林 说明书 用法用量", **kw):
    return add_document(
        session,
        title=title,
        content=content,
        source="test",
        created_by="test-actor",
        **kw,
    )
# ── Document CRUD ──────────────────────────────────────────────────────
class TestDocumentCRUD:
    def test_add_document_creates_chunks(self, session):
        doc = _make_doc(
            session,
            content="阿莫西林 胶囊 用法：口服 剂量：0.5g 每日三次 注意事项 过敏禁用",
        )
        session.commit()

        assert doc.id is not None
        assert doc.content_hash == _content_hash(
            "阿莫西林 胶囊 用法：口服 剂量：0.5g 每日三次 注意事项 过敏禁用"
        )
        chunks = session.query(KnowledgeChunk).filter(
            KnowledgeChunk.document_id == doc.id
        ).all()
        assert len(chunks) > 0
        assert all(c.term_vector for c in chunks)

    def test_add_document_with_permission_scope(self, session):
        doc = _make_doc(
            session,
            permission_scope={"household_ids": ["h-1"], "member_ids": [], "created_by": "owner"},
        )
        session.commit()
        assert doc.permission_scope["household_ids"] == ["h-1"]

    def test_delete_document_soft_delete(self, session):
        doc = _make_doc(session)
        session.commit()

        ok = delete_document(session, doc.id, deleted_by="admin")
        session.commit()
        assert ok is True

        fetched = session.get(KnowledgeDocument, doc.id)
        assert fetched.status == "deleted"
        assert fetched.deleted_by == "admin"

    def test_delete_missing_returns_false(self, session):
        ok = delete_document(session, str(uuid.uuid4()), deleted_by="admin")
        assert ok is False

    def test_content_hash_deterministic(self, session):
        doc = _make_doc(session, content="青霉素 过敏 慎用")
        session.commit()
        assert doc.content_hash == _content_hash("青霉素 过敏 慎用")
# ── Permission filtering ───────────────────────────────────────────────
class TestPermissionFiltering:
    def test_empty_scope_is_public(self, session):
        assert _check_permission({}, "any-actor") is True

    def test_owner_can_read(self, session):
        scope = {"created_by": "alice"}
        assert _check_permission(scope, "alice") is True

    def test_non_owner_denied(self, session):
        scope = {"created_by": "alice"}
        assert _check_permission(scope, "bob") is False

    def test_household_filter_match(self, session):
        scope = {"household_ids": ["h-1", "h-2"]}
        assert _check_permission(scope, "any", household_id="h-1") is True
        assert _check_permission(scope, "any", household_id="h-3") is False

    def test_member_filter_match(self, session):
        scope = {"member_ids": ["m-1"]}
        assert _check_permission(scope, "any", member_id="m-1") is True
        assert _check_permission(scope, "any", member_id="m-2") is False

    def test_internal_flag_allows(self, session):
        scope = {"internal": True}
        assert _check_permission(scope, "any") is True
# ── TF-IDF Retrieval ───────────────────────────────────────────────────
class TestRetrieval:
    def test_basic_retrieval(self, session):
        _make_doc(
            session,
            content="阿莫西林 胶囊 用法用量 口服 0.5g 每日三次 过敏禁用 青霉素过敏者禁用",
        )
        session.commit()

        results = retrieve(session, query="阿莫西林 用法", actor_id="user-1")
        assert len(results) > 0
        assert results[0]["score"] > 0
        assert "阿莫西林" in results[0]["text"]

    def test_permission_filtered_retrieval(self, session):
        _make_doc(session, content="阿莫西林 说明书",
                  permission_scope={"household_ids": ["h-authorized"]})
        _make_doc(session, content="头孢拉定 说明书",
                  permission_scope={"household_ids": ["h-other"]})
        session.commit()

        # Authorised household can see first doc only
        results = retrieve(
            session, query="阿莫西林 用法", actor_id="u1", household_id="h-authorized"
        )
        assert all(r["title"] == "Test Doc" for r in results)

        # Unauthorised household → degrade
        results_unauth = retrieve(
            session, query="阿莫西林", actor_id="u1", household_id="h-other"
        )
        assert len(results_unauth) == 0

    def test_empty_query_raises(self, session):
        with pytest.raises(ValueError):
            retrieve(session, query="   ", actor_id="u1")

    def test_no_authorised_docs_raises(self, session):
        _make_doc(session, permission_scope={"created_by": "someone-else"})
        session.commit()

        with pytest.raises(ValueError):  # NO_AUTHORISED_DOCUMENTS
            retrieve(session, query="药品", actor_id="user-1")

    def test_expired_document_excluded(self, session):
        past = datetime.now(UTC) - timedelta(days=30)
        future = datetime.now(UTC) + timedelta(days=30)
        _make_doc(
            session,
            title="过期文档",
            content="过期药品说明",
            effective_until=past,
        )
        _make_doc(
            session,
            title="生效文档",
            content="有效药品说明",
            effective_from=past,
            effective_until=future,
        )
        session.commit()

        results = retrieve(session, query="药品说明", actor_id="u1")
        assert all("过期" not in r["title"] for r in results)

    def test_results_include_source_metadata(self, session):
        _make_doc(session, content="知识库测试 内容", source="auth_package_insert")
        session.commit()

        results = retrieve(session, query="知识库测试", actor_id="u1")
        assert results[0]["source"] == "auth_package_insert"
        assert results[0]["document_id"] is not None
        assert results[0]["chunk_id"] is not None
        assert results[0]["locator"] is not None

    def test_results_sorted_by_score(self, session):
        _make_doc(session, content="头孢拉定 服用方法 口服 0.25g")
        _make_doc(session, content="阿莫西林 服用方法 口服 0.5g")
        session.commit()

        results = retrieve(session, query="口服 服用方法", actor_id="u1", top_k=10)
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)
# ── Index snapshot ─────────────────────────────────────────────────────
class TestIndexSnapshot:
    def test_create_snapshot(self, session):
        _make_doc(session, content="快照测试 文档 内容")
        session.commit()

        idx = create_index_snapshot(session, version="snap-v1", created_by="admin")
        assert idx.version == "snap-v1"
        assert idx.document_count >= 1
        assert idx.checksum is not None
# ── Tokenizer ──────────────────────────────────────────────────────────
class TestTokenizer:
    def test_tf_basic(self):
        vec = _tf("阿莫西林 胶囊 阿莫西林 口服 用法")
        assert vec["阿莫西林"] == 2
        assert vec["胶囊"] == 1

    def test_stopwords_removed(self):
        vec = _tf("的阿莫西林是胶囊")
        assert "的" not in vec
        assert "是" not in vec
        assert "阿莫西林" in vec

    def test_empty_tokenize(self):
        assert _tokenize("") == []
