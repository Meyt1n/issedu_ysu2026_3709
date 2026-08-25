"""Session-scoped local retrieval cache for HCT-430 multi-agent.

Caches database/knowledge tool payloads in-process for a short TTL so
follow-up turns in the same assistant session avoid full re-fetch.
Never stores raw user questions — keys use digests only.
"""

from __future__ import annotations

import hashlib
import threading
import time
from copy import deepcopy
from typing import Any

_LOCK = threading.Lock()
# key -> (expires_at_monotonic, payload)
_CACHE: dict[str, tuple[float, Any]] = {}


def _digest(*parts: str) -> str:
    material = "|".join(parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def make_session_key(
    *,
    assistant_session_id: str,
    actor_id: str,
    household_id: str | None,
    member_id: str | None,
) -> str:
    """Build an actor-bound key with a separately clearable member scope."""
    actor_session = _digest(assistant_session_id.strip() or "anon", actor_id)
    scope = _digest(
        household_id or "",
        member_id or "",
    )
    return f"{actor_session}:{scope}"


def make_entry_key(session_key: str, *, agent: str, query_digest: str) -> str:
    return f"{session_key}:{agent}:{query_digest}"


def digest_query(query: str) -> str:
    normalized = " ".join(str(query or "").split()).casefold()
    return _digest(normalized)


def cache_get(entry_key: str) -> Any | None:
    now = time.monotonic()
    with _LOCK:
        item = _CACHE.get(entry_key)
        if item is None:
            return None
        expires_at, payload = item
        if expires_at <= now:
            _CACHE.pop(entry_key, None)
            return None
        return deepcopy(payload)


def cache_put(entry_key: str, payload: Any, *, ttl_seconds: float) -> None:
    if ttl_seconds <= 0:
        return
    expires_at = time.monotonic() + float(ttl_seconds)
    with _LOCK:
        _CACHE[entry_key] = (expires_at, deepcopy(payload))
        if len(_CACHE) > 512:
            oldest = sorted(_CACHE.items(), key=lambda item: item[1][0])[:128]
            for key, _ in oldest:
                _CACHE.pop(key, None)


def clear_session(session_key: str) -> int:
    """Drop all entries for one assistant session. Returns removed count."""
    prefix = f"{session_key}:"
    with _LOCK:
        keys = [key for key in _CACHE if key.startswith(prefix)]
        for key in keys:
            _CACHE.pop(key, None)
        return len(keys)


def clear_actor_session(*, assistant_session_id: str, actor_id: str) -> int:
    """Drop every household/member scope for one actor-owned assistant session."""
    prefix = f"{_digest(assistant_session_id.strip() or 'anon', actor_id)}:"
    with _LOCK:
        keys = [key for key in _CACHE if key.startswith(prefix)]
        for key in keys:
            _CACHE.pop(key, None)
        return len(keys)


def clear_all() -> None:
    with _LOCK:
        _CACHE.clear()


def stats() -> dict[str, int]:
    now = time.monotonic()
    with _LOCK:
        alive = sum(1 for expires_at, _ in _CACHE.values() if expires_at > now)
        return {"entries": len(_CACHE), "alive": alive}
