"""Pluggable, local-first retrieval ports for HomeCare Twin."""

from ai.rag.retrieval import (
    ChunkHit,
    LocalKnowledgeRetriever,
    RetrievalScope,
    Retriever,
)

__all__ = ["ChunkHit", "LocalKnowledgeRetriever", "RetrievalScope", "Retriever"]
