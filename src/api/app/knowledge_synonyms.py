"""Local synonym / alias expansion for HCT-401 knowledge retrieval.

Synonym groups are loaded from src/runtime/knowledge/synonyms/本地RAG同义词表.json so operators can
edit aliases without code changes.  Expansion never overrides permission
filtering or citation validation.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_GROUPS: tuple[tuple[str, ...], ...] = (
    ("过期", "过期药", "过期药品", "expired", "expiry", "临期"),
    ("拒答", "拒绝", "refuse", "导流", "处方", "开处方", "买药"),
    ("剂量", "几片", "吃多少"),
)

_REPO_SYNONYM_PATH = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "runtime"
    / "knowledge"
    / "synonyms"
    / "本地RAG同义词表.json"
)


def _load_groups() -> tuple[tuple[str, ...], ...]:
    path = _REPO_SYNONYM_PATH
    if not path.is_file():
        logger.warning("knowledge synonym file missing: %s", path)
        return _DEFAULT_GROUPS
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("knowledge synonym file unreadable: %s", exc)
        return _DEFAULT_GROUPS
    groups = payload.get("groups")
    if not isinstance(groups, list) or not groups:
        return _DEFAULT_GROUPS
    parsed: list[tuple[str, ...]] = []
    for group in groups:
        if not isinstance(group, list):
            continue
        terms = tuple(str(term).strip() for term in group if str(term).strip())
        if len(terms) >= 2:
            parsed.append(terms)
    return tuple(parsed) or _DEFAULT_GROUPS


@lru_cache(maxsize=1)
def _lookup() -> dict[str, frozenset[str]]:
    lookup: dict[str, frozenset[str]] = {}
    for group in _load_groups():
        normalized = tuple(term.casefold() for term in group)
        members = frozenset(normalized)
        for term in normalized:
            lookup[term] = members
    return lookup


def reload_synonyms() -> None:
    """Clear cached synonym table (tests / after file edits)."""
    _lookup.cache_clear()


def expand_query_tokens(tokens: list[str]) -> list[str]:
    """Return tokens plus synonym/alias expansions, preserving order."""
    expanded: list[str] = []
    seen: set[str] = set()
    table = _lookup()
    for token in tokens:
        key = token.casefold()
        for candidate in (key, *table.get(key, ())):
            if candidate not in seen:
                seen.add(candidate)
                expanded.append(candidate)
    return expanded


def matched_synonym_labels(
    query_tokens: list[str], doc_terms: set[str]
) -> list[str]:
    """Return human-readable synonym hits used for match explanation."""
    labels: list[str] = []
    table = _lookup()
    seen: set[str] = set()
    for token in query_tokens:
        key = token.casefold()
        group = table.get(key)
        if not group:
            continue
        hits = sorted(term for term in group if term in doc_terms and term != key)
        if not hits:
            continue
        label = f"{key}→{','.join(hits[:3])}"
        if label not in seen:
            seen.add(label)
            labels.append(label)
    return labels
