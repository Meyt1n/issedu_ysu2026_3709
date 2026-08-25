"""
HCT-401: Knowledge store — versioned, authorisable, local-first retrieval.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import JSON, Column, DateTime, Integer, String, Text, func, select
from sqlalchemy.orm import Session

from app.knowledge_synonyms import expand_query_tokens, matched_synonym_labels
from app.models import Base, new_id

logger = logging.getLogger(__name__)

# Blend classic TF-IDF with a lightweight local cosine over bag-of-terms
# vectors.  No external embedding model is required; both signals stay on-box.
_VECTOR_SCORE_WEIGHT = 0.35


# ── ORM models (use shared Base) ─────────────────────────────────────


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_document"

    id = Column(String(36), primary_key=True, default=new_id)
    title = Column(String(200), nullable=False)
    source = Column(String(120), nullable=False)
    license = Column(String(60), nullable=False, default="internal")
    version = Column(String(40), nullable=False, default="1.0")
    content_hash = Column(String(64), nullable=False)
    permission_scope = Column(JSON, nullable=False, default=dict)
    status = Column(String(20), nullable=False, default="active", index=True)
    effective_from = Column(DateTime(timezone=True), nullable=True)
    effective_until = Column(DateTime(timezone=True), nullable=True)
    deleted_by = Column(String(120), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    full_text = Column(Text, nullable=False, default="")
    created_by = Column(String(120), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunk"

    id = Column(String(36), primary_key=True, default=new_id)
    document_id = Column(String(36), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    locator = Column(String(200), nullable=True)
    term_vector = Column(JSON, nullable=False, default=dict)


class KnowledgeIndex(Base):
    __tablename__ = "knowledge_index"

    id = Column(String(36), primary_key=True, default=new_id)
    version = Column(String(40), nullable=False, unique=True)
    document_count = Column(Integer, nullable=False, default=0)
    chunk_count = Column(Integer, nullable=False, default=0)
    checksum = Column(String(64), nullable=True)
    created_by = Column(String(120), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RetrievalQuery(Base):
    __tablename__ = "retrieval_query"

    id = Column(String(36), primary_key=True, default=new_id)
    query_text = Column(Text, nullable=False)
    actor_id = Column(String(120), nullable=False)
    household_id = Column(String(36), nullable=True)
    member_id = Column(String(36), nullable=True)
    returned_count = Column(Integer, nullable=False, default=0)
    top_chunk_ids = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── Helpers ───────────────────────────────────────────────────────────

_CHINESE_STOPWORDS = frozenset({
    "的", "了", "在", "是", "和", "也", "有", "就", "不", "都", "一", "到",
    "人", "大", "他", "中", "上", "为", "们", "个", "地", "与", "这", "那",
    "而", "及", "或", "但", "等", "如", "把", "被", "从", "向", "以", "要",
    "之", "去", "出", "会", "可", "着", "过", "来", "说", "给", "很", "还",
})
_TOKEN_PATTERN = re.compile(r"[a-z0-9_]+|[\u3400-\u9fff]+", re.IGNORECASE)


def _tokenize(text: str) -> list[str]:
    """Tokenize Latin words and unsegmented Chinese text for local retrieval.

    Chinese source documents rarely contain spaces between words.  Keeping a
    segment plus overlapping bigrams lets a short query match a longer
    sentence without requiring an external segmenter.
    """
    tokens: list[str] = []
    for raw_token in _TOKEN_PATTERN.findall(text.casefold()):
        if re.fullmatch(r"[\u3400-\u9fff]+", raw_token):
            if raw_token in _CHINESE_STOPWORDS or len(raw_token) <= 1:
                continue
            tokens.append(raw_token)
            if len(raw_token) > 2:
                tokens.extend(
                    raw_token[index : index + 2]
                    for index in range(len(raw_token) - 1)
                )
        elif len(raw_token) > 1:
            tokens.append(raw_token)
    return tokens


def _tf(text: str) -> dict[str, int]:
    return dict(Counter(_tokenize(text)))


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── Permission check ───────────────────────────────────────────────────

def _check_permission(
    doc_scope: dict,
    actor_id: str,
    household_id: str | None = None,
    member_id: str | None = None,
) -> bool:
    if not doc_scope:
        return True
    if doc_scope.get("created_by") == actor_id:
        return True
    hh_ids = doc_scope.get("household_ids", [])
    if hh_ids and household_id and household_id in hh_ids:
        return True
    m_ids = doc_scope.get("member_ids", [])
    if m_ids and member_id and member_id in m_ids:
        return True
    if doc_scope.get("internal", False):
        return True
    return False


# ── CRUD ──────────────────────────────────────────────────────────────

def add_document(
    session: Session,
    *,
    title: str,
    content: str,
    source: str,
    created_by: str,
    license: str = "internal",
    version: str = "1.0",
    permission_scope: dict | None = None,
    effective_from: datetime | None = None,
    effective_until: datetime | None = None,
) -> KnowledgeDocument:
    content_hash = _content_hash(content)
    doc = KnowledgeDocument(
        title=title,
        source=source,
        license=license,
        version=version,
        content_hash=content_hash,
        full_text=content,
        created_by=created_by,
        permission_scope=permission_scope or {},
        effective_from=effective_from,
        effective_until=effective_until,
    )
    session.add(doc)
    session.flush()
    _chunk_document(session, doc)
    session.flush()
    logger.info("KNOWLEDGE_DOC_ADDED doc=%s title=%s", doc.id, title)
    return doc


_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_CHUNK_SIZE = 500
_CHUNK_OVERLAP = 80
_LOCATOR_TITLE_MAX = 80


def _iter_sections(text: str) -> list[tuple[str, int, int]]:
    """Split text into (section_title, start, end) spans covering all of it.

    Markdown headings are the section boundaries so teaching cards retrieve
    per topic and citations can point at a named section (the AI/RAG spec
    requires keeping section labels through parsing).  Plain text without
    headings stays a single untitled section.
    """
    matches = list(_HEADING_PATTERN.finditer(text))
    if not matches:
        return [("", 0, len(text))]
    sections: list[tuple[str, int, int]] = []
    if matches[0].start() > 0:
        sections.append(("", 0, matches[0].start()))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append((match.group(2).strip(), match.start(), end))
    return sections


def _chunk_document(session: Session, doc: KnowledgeDocument) -> None:
    text = doc.full_text
    idx = 0
    for section_title, section_start, section_end in _iter_sections(text):
        start = section_start
        while start < section_end:
            end = min(start + _CHUNK_SIZE, section_end)
            chunk_text = text[start:end]
            if end < section_end:
                last_full_stop = max(chunk_text.rfind("。"), chunk_text.rfind("."))
                if last_full_stop > _CHUNK_SIZE // 2:
                    end = start + last_full_stop + 1
                    chunk_text = text[start:end]
            if chunk_text.strip():
                locator = f"chars:{start}-{end}"
                if section_title:
                    locator = f"section:{section_title[:_LOCATOR_TITLE_MAX]}|{locator}"
                chunk = KnowledgeChunk(
                    document_id=doc.id,
                    chunk_index=idx,
                    text=chunk_text,
                    locator=locator,
                    term_vector=_tf(chunk_text),
                )
                session.add(chunk)
                idx += 1
            if end >= section_end:
                break
            start = end - _CHUNK_OVERLAP


def delete_document(session: Session, doc_id: str, *, deleted_by: str) -> bool:
    doc = session.get(KnowledgeDocument, doc_id)
    if doc is None:
        return False
    doc.status = "deleted"
    doc.deleted_by = deleted_by
    doc.deleted_at = datetime.now(UTC)
    # Also delete chunks
    session.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == doc_id).delete()
    logger.info("KNOWLEDGE_DOC_DELETED doc=%s by=%s", doc_id, deleted_by)
    return True


# ── Retrieval ──────────────────────────────────────────────────────────

def retrieve(
    session: Session,
    *,
    query: str,
    actor_id: str,
    household_id: str | None = None,
    member_id: str | None = None,
    top_k: int = 5,
) -> list[dict]:
    normalized_query = re.sub(r"\s+", " ", str(query or "")).strip()
    if not normalized_query:
        raise ValueError("EMPTY_QUERY")
    q_tokens = _tokenize(normalized_query)
    if not q_tokens:
        # Stopword-only or single-character noise degrades exactly like an
        # empty query instead of scanning the index for nothing.
        raise ValueError("EMPTY_QUERY")
    original_q_tokens = list(dict.fromkeys(q_tokens))
    # Colloquial aliases ("expiry" / "回收") expand before scoring so teaching
    # cards remain findable without cloud embeddings.  Coverage is still
    # measured on the original query terms so expansions cannot dilute rank.
    q_tokens = expand_query_tokens(q_tokens)

    # 1. Permission pre-filter: load active docs, check scope
    now = datetime.now(UTC)
    stmt = (
        select(KnowledgeDocument)
        .where(KnowledgeDocument.status == "active")
        .where(
            (KnowledgeDocument.effective_from.is_(None)
             | (KnowledgeDocument.effective_from <= now)),
            (KnowledgeDocument.effective_until.is_(None)
             | (KnowledgeDocument.effective_until > now)),
        )
    )
    all_docs = session.scalars(stmt).all()

    accessible_ids: set = set()
    doc_meta: dict = {}
    for doc in all_docs:
        if _check_permission(doc.permission_scope, actor_id, household_id, member_id):
            accessible_ids.add(doc.id)
            doc_meta[doc.id] = {
                "title": doc.title,
                "source": doc.source,
                "version": doc.version,
            }

    if not accessible_ids:
        raise ValueError("NO_AUTHORISED_DOCUMENTS")

    # 2. Load chunks for accessible docs
    chunks = session.scalars(
        select(KnowledgeChunk).where(KnowledgeChunk.document_id.in_(accessible_ids))
    ).all()

    if not chunks:
        raise ValueError("EMPTY_INDEX")

    # 3. Scoring: smoothed chunk-level TF-IDF + lightweight local cosine.
    #    * IDF is computed against the chunk collection (df counts chunks), so
    #      a term present in every chunk keeps a small positive weight instead
    #      of turning negative and hiding matching chunks.
    #    * TF is sublinear (1 + ln tf) so a chunk repeating one keyword cannot
    #      drown out a chunk that actually covers the question.
    #    * Coverage weighting prefers chunks matching more distinct query
    #      terms, which keeps multi-document teaching content well ranked.
    #    * Cosine over bag-of-terms vectors is a local "light vector" signal
    #      (no external embedding download) blended at _VECTOR_SCORE_WEIGHT.
    n_chunks = len(chunks)
    df: Counter = Counter()
    for ch in chunks:
        df.update(ch.term_vector.keys())

    unique_q_tokens = set(q_tokens)
    original_unique = set(original_q_tokens)
    q_tf = Counter(q_tokens)
    scored = []
    for ch in chunks:
        score = 0.0
        matched_tokens = 0
        matched_original = 0
        for tok in unique_q_tokens:
            tf = ch.term_vector.get(tok, 0)
            if tf == 0:
                continue
            matched_tokens += 1
            if tok in original_unique:
                matched_original += 1
            idf = math.log((1 + n_chunks) / (1 + df[tok])) + 1.0
            score += (1.0 + math.log(tf)) * idf
        if matched_tokens:
            coverage = matched_original / len(original_unique)
            score *= 0.5 + 0.5 * coverage
            cosine = _cosine_bag_of_terms(q_tf, ch.term_vector or {})
            score = (1.0 - _VECTOR_SCORE_WEIGHT) * score + _VECTOR_SCORE_WEIGHT * (
                score * (0.5 + 0.5 * cosine)
            )
            doc_terms = set((ch.term_vector or {}).keys())
            direct_hits = sorted(
                token for token in original_unique if token in doc_terms
            )[:8]
            synonym_hits = matched_synonym_labels(original_q_tokens, doc_terms)[:6]
            reason_parts = []
            if direct_hits:
                reason_parts.append("关键词:" + ",".join(direct_hits))
            if synonym_hits:
                reason_parts.append("同义词:" + ";".join(synonym_hits))
            if coverage:
                reason_parts.append(f"覆盖度:{coverage:.2f}")
            if cosine:
                reason_parts.append(f"向量相似:{cosine:.2f}")
            meta = doc_meta.get(ch.document_id, {})
            scored.append({
                "chunk_id": ch.id,
                "document_id": ch.document_id,
                "title": meta.get("title", ""),
                "source": meta.get("source", ""),
                "version": meta.get("version", ""),
                "text": ch.text,
                "locator": ch.locator,
                "score": round(score, 4),
                "match_reason": " | ".join(reason_parts) or "term-overlap",
                "matched_terms": direct_hits,
                "matched_synonyms": synonym_hits,
            })

    scored.sort(key=lambda r: r["score"], reverse=True)
    if not scored:
        raise ValueError("NO_RELEVANT_RESULTS")
    return scored[:top_k]


def _cosine_bag_of_terms(query_tf: Counter, doc_tf: dict) -> float:
    """Cosine similarity between two bag-of-terms maps (local light vector)."""
    if not query_tf or not doc_tf:
        return 0.0
    dot = 0.0
    for term, q_weight in query_tf.items():
        d_weight = doc_tf.get(term)
        if d_weight:
            dot += float(q_weight) * float(d_weight)
    if dot <= 0.0:
        return 0.0
    q_norm = math.sqrt(sum(weight * weight for weight in query_tf.values()))
    d_norm = math.sqrt(sum(float(weight) * float(weight) for weight in doc_tf.values()))
    if q_norm <= 0.0 or d_norm <= 0.0:
        return 0.0
    return dot / (q_norm * d_norm)


# ── Audit logging ─────────────────────────────────────────────────────

def log_query(
    session: Session,
    *,
    query_text: str,
    actor_id: str,
    household_id: str | None = None,
    member_id: str | None = None,
    top_chunk_ids: list | None = None,
    returned_count: int = 0,
) -> RetrievalQuery:
    entry = RetrievalQuery(
        query_text=query_text[:1000],
        actor_id=actor_id,
        household_id=household_id,
        member_id=member_id,
        top_chunk_ids=top_chunk_ids or [],
        returned_count=returned_count,
    )
    session.add(entry)
    session.flush()
    return entry


# ── Index snapshot ────────────────────────────────────────────────────

def compute_index_checksum(session: Session) -> str:
    """Return a deterministic checksum for the active local index.

    Chunk UUIDs are intentionally excluded: rebuilding the same approved
    source creates new row IDs, but must still produce the same audit hash.
    The checksum covers document identity/version/permission metadata and
    the ordered content hash of every chunk.
    """
    active_docs = session.scalars(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.status == "active")
        .order_by(
            KnowledgeDocument.content_hash,
            KnowledgeDocument.version,
            KnowledgeDocument.source,
            KnowledgeDocument.title,
        )
    ).all()
    payload: list[dict] = []
    for doc in active_docs:
        chunks = session.scalars(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.document_id == doc.id)
            .order_by(KnowledgeChunk.chunk_index)
        ).all()
        payload.append(
            {
                "content_hash": doc.content_hash,
                "title": doc.title,
                "source": doc.source,
                "license": doc.license,
                "version": doc.version,
                "permission_scope": doc.permission_scope or {},
                "effective_from": doc.effective_from.isoformat()
                if doc.effective_from
                else None,
                "effective_until": doc.effective_until.isoformat()
                if doc.effective_until
                else None,
                "chunks": [
                    {
                        "chunk_index": chunk.chunk_index,
                        "text_hash": _content_hash(chunk.text),
                        "locator": chunk.locator,
                    }
                    for chunk in chunks
                ],
            }
        )
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_index_snapshot(
    session: Session,
    *,
    version: str,
    created_by: str,
) -> KnowledgeIndex:
    doc_count = int(
        session.scalar(
            select(func.count())
            .select_from(KnowledgeDocument)
            .where(KnowledgeDocument.status == "active")
        )
        or 0
    )
    chunk_count = int(
        session.scalar(select(func.count()).select_from(KnowledgeChunk)) or 0
    )
    checksum = compute_index_checksum(session)
    idx = KnowledgeIndex(
        version=version,
        document_count=doc_count,
        chunk_count=chunk_count,
        checksum=checksum,
        created_by=created_by,
    )
    session.add(idx)
    session.flush()
    logger.info("KNOWLEDGE_INDEX_CREATED version=%s docs=%d chunks=%d",
                version, doc_count, chunk_count)
    return idx
