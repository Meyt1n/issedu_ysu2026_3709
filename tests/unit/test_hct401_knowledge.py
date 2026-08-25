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

def _make_doc(
    db_session,
    *,
    title="Test Doc",
    content="阿莫西林 说明书 用法用量",
    kw_source="test",
    **kw,
):
    return add_document(
        db_session,
        title=title,
        content=content,
        source=kw_source,
        created_by="test-actor",
        **kw,
    )
# ── Document CRUD ──────────────────────────────────────────────────────
class TestDocumentCRUD:
    def test_add_document_creates_chunks(self, db_session):
        doc = _make_doc(
            db_session,
            content="阿莫西林 胶囊 用法：口服 剂量：0.5g 每日三次 注意事项 过敏禁用",
        )
        db_session.commit()

        assert doc.id is not None
        assert doc.content_hash == _content_hash(
            "阿莫西林 胶囊 用法：口服 剂量：0.5g 每日三次 注意事项 过敏禁用"
        )
        chunks = db_session.query(KnowledgeChunk).filter(
            KnowledgeChunk.document_id == doc.id
        ).all()
        assert len(chunks) == 1
        assert all(c.term_vector for c in chunks)

    def test_add_document_with_permission_scope(self, db_session):
        doc = _make_doc(
            db_session,
            permission_scope={"household_ids": ["h-1"], "member_ids": [], "created_by": "owner"},
        )
        db_session.commit()
        assert doc.permission_scope["household_ids"] == ["h-1"]

    def test_delete_document_soft_delete(self, db_session):
        doc = _make_doc(db_session)
        db_session.commit()

        ok = delete_document(db_session, doc.id, deleted_by="admin")
        db_session.commit()
        assert ok is True

        fetched = db_session.get(KnowledgeDocument, doc.id)
        assert fetched.status == "deleted"
        assert fetched.deleted_by == "admin"

    def test_delete_missing_returns_false(self, db_session):
        ok = delete_document(db_session, str(uuid.uuid4()), deleted_by="admin")
        assert ok is False

    def test_content_hash_deterministic(self, db_session):
        doc = _make_doc(db_session, content="青霉素 过敏 慎用")
        db_session.commit()
        assert doc.content_hash == _content_hash("青霉素 过敏 慎用")
# ── Permission filtering ───────────────────────────────────────────────
class TestPermissionFiltering:
    def test_empty_scope_is_public(self, db_session):
        assert _check_permission({}, "any-actor") is True

    def test_owner_can_read(self, db_session):
        scope = {"created_by": "alice"}
        assert _check_permission(scope, "alice") is True

    def test_non_owner_denied(self, db_session):
        scope = {"created_by": "alice"}
        assert _check_permission(scope, "bob") is False

    def test_household_filter_match(self, db_session):
        scope = {"household_ids": ["h-1", "h-2"]}
        assert _check_permission(scope, "any", household_id="h-1") is True
        assert _check_permission(scope, "any", household_id="h-3") is False

    def test_member_filter_match(self, db_session):
        scope = {"member_ids": ["m-1"]}
        assert _check_permission(scope, "any", member_id="m-1") is True
        assert _check_permission(scope, "any", member_id="m-2") is False

    def test_internal_flag_allows(self, db_session):
        scope = {"internal": True}
        assert _check_permission(scope, "any") is True
# ── TF-IDF Retrieval ───────────────────────────────────────────────────
class TestRetrieval:
    def test_basic_retrieval(self, db_session):
        _make_doc(
            db_session,
            content="阿莫西林 胶囊 用法用量 口服 0.5g 每日三次 过敏禁用 青霉素过敏者禁用",
        )
        db_session.commit()

        results = retrieve(db_session, query="阿莫西林 用法", actor_id="user-1")
        assert len(results) > 0
        assert results[0]["score"] > 0
        assert "阿莫西林" in results[0]["text"]

    def test_permission_filtered_retrieval(self, db_session):
        _make_doc(db_session, content="阿莫西林 说明书",
                  permission_scope={"household_ids": ["h-authorized"]})
        _make_doc(db_session, content="头孢拉定 说明书",
                  permission_scope={"household_ids": ["h-other"]})
        db_session.commit()

        # Authorised household can see first doc only
        results = retrieve(
            db_session, query="阿莫西林 用法", actor_id="u1", household_id="h-authorized"
        )
        assert all(r["title"] == "Test Doc" for r in results)

        # A permitted household with no matching evidence degrades explicitly.
        with pytest.raises(ValueError, match="NO_RELEVANT_RESULTS"):
            retrieve(db_session, query="阿莫西林", actor_id="u1", household_id="h-other")

    def test_empty_query_raises(self, db_session):
        with pytest.raises(ValueError):
            retrieve(db_session, query="   ", actor_id="u1")

    def test_no_authorised_docs_raises(self, db_session):
        _make_doc(db_session, permission_scope={"created_by": "someone-else"})
        db_session.commit()

        with pytest.raises(ValueError):  # NO_AUTHORISED_DOCUMENTS
            retrieve(db_session, query="药品", actor_id="user-1")

    def test_expired_document_excluded(self, db_session):
        past = datetime.now(UTC) - timedelta(days=30)
        future = datetime.now(UTC) + timedelta(days=30)
        _make_doc(
            db_session,
            title="过期文档",
            content="过期药品说明",
            effective_until=past,
        )
        _make_doc(
            db_session,
            title="生效文档",
            content="有效药品说明",
            effective_from=past,
            effective_until=future,
        )
        db_session.commit()

        results = retrieve(db_session, query="药品说明", actor_id="u1")
        assert all("过期" not in r["title"] for r in results)

    def test_results_include_source_metadata(self, db_session):
        _make_doc(db_session, content="知识库测试 内容", kw_source="auth_package_insert")
        db_session.commit()

        results = retrieve(db_session, query="知识库测试", actor_id="u1")
        assert results[0]["source"] == "auth_package_insert"
        assert results[0]["document_id"] is not None
        assert results[0]["chunk_id"] is not None
        assert results[0]["locator"] is not None

    def test_results_sorted_by_score(self, db_session):
        _make_doc(db_session, content="头孢拉定 服用方法 口服 0.25g")
        _make_doc(db_session, content="阿莫西林 服用方法 口服 0.5g")
        db_session.commit()

        results = retrieve(db_session, query="口服 服用方法", actor_id="u1", top_k=10)
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_unsegmented_chinese_query_matches_longer_sentence(self, db_session):
        _make_doc(
            db_session,
            content="合成照护证据要求先核对已确认事件并联系医务人员。",
        )
        db_session.commit()

        results = retrieve(db_session, query="合成照护证据", actor_id="u1")

        assert len(results) == 1
        assert results[0]["score"] > 0

    def test_no_relevant_result_is_explicit_degradation(self, db_session):
        _make_doc(db_session, content="阿莫西林 说明书 用法用量")
        db_session.commit()

        with pytest.raises(ValueError, match="NO_RELEVANT_RESULTS"):
            retrieve(db_session, query="天气温度", actor_id="u1")

    def test_common_term_across_all_chunks_is_still_retrievable(self, db_session):
        """Regression: a query term present in every chunk must stay findable.

        The previous scoring mixed document-level N with chunk-level document
        frequency, so a term appearing in more chunks than there are documents
        received a negative IDF and matching chunks were silently dropped as
        NO_RELEVANT_RESULTS.
        """
        section = (
            "家庭用药安全提醒：请核对药品名称、规格和有效期，"
            "妥善存放并在需要时联系药师复核。" * 8
        )
        content = "\n\n".join(section for _ in range(5))
        _make_doc(db_session, title="用药安全长文", content=content)
        db_session.commit()

        chunk_count = db_session.query(KnowledgeChunk).count()
        assert chunk_count >= 3, "fixture must span multiple chunks"

        results = retrieve(db_session, query="用药安全", actor_id="u1")
        assert results
        assert all(item["score"] > 0 for item in results)

    def test_chunk_matching_more_query_terms_ranks_first(self, db_session):
        """A chunk covering all query terms must outrank keyword stuffing."""
        _make_doc(
            db_session,
            title="覆盖全部术语",
            content="药品过期后的处理方式：先核对有效期，再按处置提示分类。",
        )
        _make_doc(
            db_session,
            title="重复单一术语",
            content="药品 药品 药品 药品 药品 药品 药品 药品 药品 药品",
        )
        db_session.commit()

        results = retrieve(db_session, query="过期 药品 处理", actor_id="u1", top_k=5)
        assert results[0]["title"] == "覆盖全部术语"

    def test_markdown_sections_become_chunks_with_section_locators(self, db_session):
        content = (
            "# 演示知识卡\n\n开头说明，仅用于测试。\n\n"
            "## 药品存放\n\n药品应存放在儿童接触不到的地方，避免高温和潮湿。\n\n"
            "## 过期处置\n\n定期检查有效期，过期药品需要妥善处置并记录。\n"
        )
        doc = _make_doc(db_session, title="章节演示", content=content)
        db_session.commit()

        chunks = (
            db_session.query(KnowledgeChunk)
            .filter(KnowledgeChunk.document_id == doc.id)
            .order_by(KnowledgeChunk.chunk_index)
            .all()
        )
        assert len(chunks) >= 3
        locators = [chunk.locator for chunk in chunks]
        assert any("药品存放" in locator for locator in locators)
        assert any("过期处置" in locator for locator in locators)

        results = retrieve(db_session, query="过期处置", actor_id="u1")
        assert "过期处置" in results[0]["locator"]
        assert "过期" in results[0]["text"]

# ── Index snapshot ─────────────────────────────────────────────────────
class TestIndexSnapshot:
    def test_create_snapshot(self, db_session):
        _make_doc(db_session, content="快照测试 文档 内容")
        db_session.commit()

        idx = create_index_snapshot(db_session, version="snap-v1", created_by="admin")
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
        # "的阿莫西林是胶囊" -> tokenize: \w matches ASCII, 一-鿿 matches
        # CJK. After .lower(), "的" and "是" are removed as stopwords.
        # This leaves "阿莫西林胶囊" as one token.
        vec = _tf("的阿莫西林是胶囊")
        assert "的" not in vec
        assert "是" not in vec
        assert len(vec) > 0

    def test_empty_tokenize(self):
        assert _tokenize("") == []
