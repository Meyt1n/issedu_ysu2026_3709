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

from app.models import Base, new_id

logger = logging.getLogger(__name__)


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


def _chunk_document(session: Session, doc: KnowledgeDocument) -> None:
    text = doc.full_text
    chunk_size = 500
    overlap = 80
    start = 0
    idx = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk_text = text[start:end]
        if end < len(text):
            last_full_stop = max(chunk_text.rfind("。"), chunk_text.rfind("."))
            if last_full_stop > chunk_size // 2:
                end = start + last_full_stop + 1
                chunk_text = text[start:end]
        term_vec = _tf(chunk_text)
        locator = f"chars:{start}-{end}"
        chunk = KnowledgeChunk(
            document_id=doc.id,
            chunk_index=idx,
            text=chunk_text,
            locator=locator,
            term_vector=term_vec,
        )
        session.add(chunk)
        idx += 1
        if end >= len(text):
            break
        start = end - overlap


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
    q_tokens = _tokenize(query)
    if not q_tokens:
        raise ValueError("EMPTY_QUERY")

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

    # 3. TF-IDF scoring
    n_docs = len(accessible_ids)
    df: Counter = Counter()
    for ch in chunks:
        df.update(ch.term_vector.keys())

    scored = []
    for ch in chunks:
        score = 0.0
        for tok in q_tokens:
            tf = ch.term_vector.get(tok, 0)
            if tf == 0:
                continue
            idf = math.log(n_docs / df.get(tok, 1)) + 1.0
            score += tf * idf
        if score > 0:
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
            })

    scored.sort(key=lambda r: r["score"], reverse=True)
    if not scored:
        raise ValueError("NO_RELEVANT_RESULTS")
    return scored[:top_k]


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
