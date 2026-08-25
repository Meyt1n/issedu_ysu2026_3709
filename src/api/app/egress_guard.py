"""
Egress guard — default-deny network egress with weather-service whitelist.

All outbound HTTP from the API layer MUST pass through this guard.
Any request to a non-whitelisted destination is blocked and audited.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from app.config import get_settings

logger = logging.getLogger(__name__)

# Fields that must never appear in an outbound request body.
# These patterns are matched case-insensitively against JSON keys.
FORBIDDEN_EGRESS_FIELDS: set[str] = {
    "member_id",
    "member_ids",
    "household_id",
    "display_name",
    "drug",
    "drugs",
    "disease",
    "diseases",
    "allergy",
    "allergies",
    "symptom",
    "symptoms",
    "diagnosis",
    "report",
    "reports",
    "image",
    "images",
    "video",
    "videos",
    "vector",
    "vectors",
    "embedding",
    "conversation",
    "conversations",
    "health_event",
    "health_events",
    "payload",
    "evidence",
    "ocr_text",
    "barcode_value",
    "prescription",
}


def _normalize_host(url: str) -> str:
    """Extract host:port (if present) from a URL, lowercased."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.port:
        return f"{host.lower()}:{parsed.port}"
    return host.lower()


def get_whitelist() -> set[str]:
    """Return the set of whitelisted hosts (with optional ports)."""
    settings = get_settings()
    raw = settings.egress_weather_whitelist
    if not raw:
        return set()
    return {
        _normalize_host(item.strip() if "://" in item else f"https://{item.strip()}")
        for item in raw.split(",")
        if item.strip()
    }


def is_egress_allowed(url: str) -> bool:
    """Check whether outbound traffic to *url* is permitted."""
    settings = get_settings()
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        logger.warning("EGRESS_BLOCKED: weather egress requires HTTPS")
        return False
    if not settings.egress_default_deny:
        return True

    target = _normalize_host(url)
    if not target:
        logger.warning("EGRESS_BLOCKED: could not parse host from url=%s", url)
        return False

    whitelist = get_whitelist()
    allowed = target in whitelist
    if not allowed:
        logger.warning(
            "EGRESS_BLOCKED: host=%s not in whitelist whitelist_size=%d",
            target,
            len(whitelist),
        )
    return allowed


def is_web_search_egress_allowed(url: str, settings=None) -> bool:
    """Allow only the configured HTTPS search host for HCT-430.

    This is deliberately separate from ``is_egress_allowed``: weather keeps
    its existing whitelist and audit semantics, while web search is a second,
    opt-in exception with its own allowlist.  Callers must still redact the
    query before making a request.
    """
    settings = settings or get_settings()
    if not settings.agent_web_search_enabled:
        logger.warning("EGRESS_BLOCKED: local agent web search is disabled")
        return False
    provider = (getattr(settings, "agent_web_search_provider", "") or "").strip().casefold()
    if provider == "fixture":
        # The teaching-fixture provider serves in-process synthetic results and
        # never opens a connection, so there is no egress to allowlist.
        return True
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        logger.warning("EGRESS_BLOCKED: agent web search requires HTTPS")
        return False
    target = _normalize_host(url)
    if not target:
        logger.warning("EGRESS_BLOCKED: agent web search URL has no host")
        return False
    allowed_hosts = settings.agent_web_search_allowed_domain_set
    if not allowed_hosts:
        configured_host = _normalize_host(settings.agent_web_search_url)
        allowed_hosts = {configured_host} if configured_host else set()
    allowed = target in allowed_hosts
    if not allowed:
        logger.warning(
            "EGRESS_BLOCKED: agent search host=%s not in allowlist size=%d",
            target,
            len(allowed_hosts),
        )
    return allowed


def is_health_news_egress_allowed(url: str, settings=None) -> bool:
    """Allow HTTPS hosts listed in HEALTH_NEWS_ALLOWED_DOMAINS (HCT-445).

    Separate from weather and agent web-search allowlists.  Health-news
    fetches are read-only GETs with no request body and must never carry
    household or health fields.
    """
    settings = settings or get_settings()
    mode = (settings.health_news_adapter or "local").strip().casefold()
    if mode != "enabled":
        logger.warning("EGRESS_BLOCKED: health news adapter is not enabled")
        return False
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        logger.warning("EGRESS_BLOCKED: health news egress requires HTTPS")
        return False
    target = _normalize_host(url)
    if not target:
        logger.warning("EGRESS_BLOCKED: health news URL has no host")
        return False
    allowed_hosts = settings.health_news_allowed_domain_set
    if not allowed_hosts:
        logger.warning("EGRESS_BLOCKED: health news allowlist is empty")
        return False
    host = (parsed.hostname or "").lower()
    bare = host.removeprefix("www.")
    allowed = (
        target in allowed_hosts
        or host in allowed_hosts
        or bare in allowed_hosts
        or f"www.{bare}" in allowed_hosts
    )
    if not allowed:
        logger.warning(
            "EGRESS_BLOCKED: health news host=%s not in allowlist size=%d",
            target,
            len(allowed_hosts),
        )
    return allowed


def validate_egress_payload(body: dict[str, Any] | None) -> tuple[bool, str | None]:
    """Reject outbound payloads that contain forbidden health fields.

    Returns (ok, reason).
    """
    if body is None:
        return True, None

    forbidden = _find_forbidden_keys(body)
    if forbidden:
        reason = f"EGRESS_CONTENT_REJECTED: forbidden fields {sorted(forbidden)}"
        logger.warning("%s field_count=%d", reason, len(forbidden))
        return False, reason
    return True, None


def _find_forbidden_keys(obj: Any, path: str = "") -> set[str]:
    """Recursively find forbidden keys in a JSON-like object."""
    found: set[str] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_lower = key.lower().strip()
            if key_lower in FORBIDDEN_EGRESS_FIELDS:
                found.add(key)
            found.update(_find_forbidden_keys(value, f"{path}.{key}" if path else key))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            found.update(_find_forbidden_keys(item, f"{path}[{idx}]"))
    return found


def allowed_weather_payload(body: dict[str, Any] | None) -> tuple[bool, str | None]:
    """Weather adapter payload must contain ONLY city/district codes."""
    if body is None:
        return True, None

    allowed_keys = {"city_code", "district_code"}
    for key in body:
        if key not in allowed_keys:
            reason = (
                f"EGRESS_WEATHER_PAYLOAD_REJECTED: "
                f"key '{key}' not in allowed set {sorted(allowed_keys)}"
            )
            logger.warning(reason)
            return False, reason

    valid, reason = validate_egress_payload(body)
    if not valid:
        return False, reason

    return True, None
