"""Stable RAG retrieval port and the current local knowledge adapter.

The API and assistant should depend on this small contract rather than on the
SQLAlchemy-backed implementation in ``app.knowledge``.  A future vector
adapter can implement :class:`Retriever` without changing permission scope,
citation fields or the local-only default.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Any, Protocol


def _required_text(row: Mapping[str, Any], key: str) -> str:
    value = row[key]
    if value is None or not str(value).strip():
        raise ValueError(key)
    return str(value)


@dataclass(frozen=True, slots=True)
class RetrievalScope:
    """Authorization scope passed to every retrieval implementation."""

    actor_id: str
    household_id: str | None = None
    member_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.actor_id, str) or not self.actor_id.strip():
            raise ValueError("ACTOR_REQUIRED")


@dataclass(frozen=True, slots=True)
class ChunkHit:
    """Citation-safe result shared by local and future vector adapters."""

    chunk_id: str
    document_id: str
    title: str
    source: str
    version: str
    text: str
    locator: str | None
    score: float
    match_reason: str
    matched_terms: tuple[str, ...] = ()
    matched_synonyms: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("chunk_id", "document_id", "version"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError("RAG_HIT_INVALID")
        if not isfinite(self.score) or self.score < 0:
            raise ValueError("RAG_HIT_INVALID")

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> ChunkHit:
        """Validate and normalize a legacy adapter row at the boundary."""

        try:
            return cls(
                chunk_id=_required_text(row, "chunk_id"),
                document_id=_required_text(row, "document_id"),
                title=str(row.get("title") or ""),
                source=str(row.get("source") or ""),
                version=_required_text(row, "version"),
                text=_required_text(row, "text"),
                locator=(str(row["locator"]) if row.get("locator") is not None else None),
                score=float(row["score"]),
                match_reason=str(row.get("match_reason") or "term-overlap"),
                matched_terms=tuple(str(value) for value in row.get("matched_terms") or ()),
                matched_synonyms=tuple(
                    str(value) for value in row.get("matched_synonyms") or ()
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("RAG_HIT_INVALID") from exc

    def as_dict(self) -> dict[str, Any]:
        """Return the existing API/tool shape without leaking implementation state."""

        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "title": self.title,
            "source": self.source,
            "version": self.version,
            "text": self.text,
            "locator": self.locator,
            "score": self.score,
            "match_reason": self.match_reason,
            "matched_terms": list(self.matched_terms),
            "matched_synonyms": list(self.matched_synonyms),
        }


class Retriever(Protocol):
    """Port implemented by local TF-IDF and future vector adapters."""

    def retrieve(
        self,
        query: str,
        scope: RetrievalScope,
        *,
        top_k: int = 5,
    ) -> list[ChunkHit]: ...


class LocalKnowledgeRetriever:
    """Default adapter around the permission-filtered local knowledge store."""

    def __init__(self, session: Any) -> None:
        self._session = session

    def retrieve(
        self,
        query: str,
        scope: RetrievalScope,
        *,
        top_k: int = 5,
    ) -> list[ChunkHit]:
        if top_k < 1 or top_k > 20:
            raise ValueError("TOP_K_INVALID")
        # Lazy import keeps the port independent from the API package and
        # allows a vector adapter to replace this implementation cleanly.
        from app.knowledge import retrieve as retrieve_local

        rows = retrieve_local(
            self._session,
            query=query,
            actor_id=scope.actor_id,
            household_id=scope.household_id,
            member_id=scope.member_id,
            top_k=top_k,
        )
        return [ChunkHit.from_mapping(row) for row in rows]
