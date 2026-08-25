"""HCT-445 whitelist health-news fetch with cache and seasonal fallback.

Outbound GETs are HTTPS-only and must pass the health-news egress allowlist.
No household or health fields leave the device.  Remote cards are extractive
(title/summary from the source); the model never invents outbreak names or
case counts for the home screen.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from time import monotonic
from typing import Any, Literal
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.egress_guard import is_health_news_egress_allowed
from app.health_news import (
    DISCLAIMER,
    HealthNewsItem,
    build_seasonal_items,
    season_key_for,
)

logger = logging.getLogger(__name__)

StatusLiteral = Literal[
    "ok",
    "stale",
    "local_only",
    "disabled",
    "unconfigured",
    "egress_blocked",
    "rate_limited",
    "timeout",
    "provider_unavailable",
    "invalid_response",
    "error",
]
CacheLiteral = Literal["none", "miss", "fresh", "stale"]


class HealthNewsEgressBlockedError(ValueError):
    """Raised when a source response leaves the configured HTTPS allowlist."""

# Commercial / clinical funnel phrases never belong on teaching home cards.
_BLOCKED_TITLE_RE = re.compile(
    r"(购药|买药|开药|在线问诊|挂号|义诊广告|优惠券|秒杀|佣金)",
)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


class HealthNewsSourceProfile(BaseModel):
    """Built-in or operator-configured public list endpoint."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=80)
    list_url: str = Field(min_length=8, max_length=500)
    kind: Literal["rss", "html_list"] = "rss"
    # CSS-ish hints for html_list: we match <a href> whose path contains marker.
    link_path_contains: str = ""
    max_items: int = Field(default=4, ge=1, le=10)


# Curated public sources.  A source only runs when its host is in
# HEALTH_NEWS_ALLOWED_DOMAINS (and adapter=enabled).
BUILTIN_SOURCES: tuple[HealthNewsSourceProfile, ...] = (
    HealthNewsSourceProfile(
        id="who_news_en",
        name="世界卫生组织",
        list_url="https://www.who.int/rss-feeds/news-english.xml",
        kind="rss",
        max_items=4,
    ),
    HealthNewsSourceProfile(
        id="nhc_xwzx",
        name="国家卫生健康委员会",
        list_url="https://www.nhc.gov.cn/xcs/yqfkdt/list_gzbd.shtml",
        kind="html_list",
        link_path_contains="/xcs/",
        max_items=4,
    ),
    HealthNewsSourceProfile(
        id="chinacdc_zxxx",
        name="中国疾病预防控制中心",
        list_url="https://www.chinacdc.cn/jkzt/crb/",
        kind="html_list",
        link_path_contains="/jkzt/",
        max_items=4,
    ),
)


class RemoteNewsDraft(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=600)
    source_url: str = Field(min_length=8, max_length=500)
    source_name: str = Field(min_length=1, max_length=80)
    source_id: str = Field(min_length=1, max_length=64)
    published_at: datetime | None = None


class HealthNewsApiResponse(BaseModel):
    status: StatusLiteral
    cache_status: CacheLiteral
    season: str
    generated_at: datetime
    fetched_at: datetime | None = None
    disclaimer: str = DISCLAIMER
    degraded_reason: str | None = None
    sources_attempted: list[str] = Field(default_factory=list)
    items: list[HealthNewsItem]


@dataclass
class _CacheEntry:
    items: list[HealthNewsItem]
    fetched_at: datetime
    sources_attempted: list[str]
    stored_at: float


_cache: _CacheEntry | None = None
_last_request_at: float = 0.0
_lock = asyncio.Lock()


def reset_health_news_state() -> None:
    """Clear process-local cache for tests."""
    global _cache, _last_request_at, _lock
    _cache = None
    _last_request_at = 0.0
    _lock = asyncio.Lock()


def builtin_source_catalog() -> list[dict[str, Any]]:
    return [source.model_dump() for source in BUILTIN_SOURCES]


def _strip_html(text: str) -> str:
    cleaned = _TAG_RE.sub(" ", text or "")
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _parse_datetime(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    raw = value.strip()
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _host_allowed(url: str, allowed_hosts: set[str]) -> bool:
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if host in allowed_hosts:
        return True
    # Allow subdomain match when allowlist has parent (rare; keep exact + www strip).
    bare = host.removeprefix("www.")
    return bare in allowed_hosts or f"www.{bare}" in allowed_hosts


def _stable_id(source_id: str, url: str) -> str:
    digest = hashlib.sha256(f"{source_id}|{url}".encode()).hexdigest()[:16]
    return f"remote-{source_id}-{digest}"


def _chat_prompt_for(title: str) -> str:
    short = _truncate(title, 48)
    return (
        f"首页看到公开资讯「{short}」。"
        "请结合本地知识库，用教学语气说明一般性居家照护注意点；"
        "不要诊断、不开处方、不编造病例数或未证实的疫情结论。"
    )


def draft_to_item(draft: RemoteNewsDraft, *, fetched_at: datetime) -> HealthNewsItem | None:
    title = _strip_html(draft.title)
    if not title or _BLOCKED_TITLE_RE.search(title):
        return None
    summary = _strip_html(draft.summary)
    if not summary:
        summary = (
            f"来自{draft.source_name}的公开资讯摘要。"
            "首页仅作教学参考，不是诊断或疫情通报；可点进本地助手了解一般资料。"
        )
    try:
        return HealthNewsItem(
            id=_stable_id(draft.source_id, draft.source_url),
            kind="remote",
            title=_truncate(title, 120),
            summary=_truncate(summary, 400),
            tag="权威资讯",
            chat_prompt=_truncate(_chat_prompt_for(title), 240),
            source="remote_whitelist",
            source_name=draft.source_name,
            source_url=draft.source_url,
            published_at=draft.published_at,
            fetched_at=fetched_at,
        )
    except Exception:  # noqa: BLE001 — invalid draft must not break the panel
        logger.warning("health_news: dropped invalid remote draft source=%s", draft.source_id)
        return None


class _AnchorCollector(HTMLParser):
    def __init__(self, *, base_url: str, path_contains: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.path_contains = path_contains
        self._capture = False
        self._href: str | None = None
        self._chunks: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if not href:
            return
        absolute = urljoin(self.base_url, href.strip())
        path = urlparse(absolute).path or ""
        if self.path_contains and self.path_contains not in path:
            return
        if absolute.lower().endswith((".jpg", ".png", ".gif", ".css", ".js", ".pdf")):
            return
        self._capture = True
        self._href = absolute
        self._chunks = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._capture or not self._href:
            return
        title = _WHITESPACE_RE.sub(" ", "".join(self._chunks)).strip()
        if title:
            self.links.append((self._href, title))
        self._capture = False
        self._href = None
        self._chunks = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._chunks.append(data)


def parse_rss_payload(body: str, *, source: HealthNewsSourceProfile) -> list[RemoteNewsDraft]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise ValueError("invalid_rss") from exc

    items: list[RemoteNewsDraft] = []
    # RSS 2.0
    for node in root.findall(".//item"):
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        description = (node.findtext("description") or node.findtext("content:encoded") or "")
        pub = node.findtext("pubDate")
        if not title or not link:
            continue
        items.append(
            RemoteNewsDraft(
                title=title,
                summary=_truncate(_strip_html(description), 400),
                source_url=link,
                source_name=source.name,
                source_id=source.id,
                published_at=_parse_datetime(pub),
            )
        )
        if len(items) >= source.max_items:
            return items

    # Atom
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    atom_entries = root.findall(".//atom:entry", ns) or root.findall(
        ".//{http://www.w3.org/2005/Atom}entry"
    )
    for node in atom_entries:
        atom_title = node.findtext("atom:title", default="", namespaces=ns)
        plain_title = node.findtext("{http://www.w3.org/2005/Atom}title")
        title = (atom_title or plain_title or "").strip()
        link = ""
        atom_links = node.findall("atom:link", ns) or node.findall(
            "{http://www.w3.org/2005/Atom}link"
        )
        for link_node in atom_links:
            href = link_node.attrib.get("href", "")
            rel = link_node.attrib.get("rel", "alternate")
            if href and rel in {"alternate", ""}:
                link = href
                break
        summary = (
            node.findtext("atom:summary", default="", namespaces=ns)
            or node.findtext("{http://www.w3.org/2005/Atom}summary")
            or node.findtext("atom:content", default="", namespaces=ns)
            or ""
        )
        updated = (
            node.findtext("atom:updated", default="", namespaces=ns)
            or node.findtext("{http://www.w3.org/2005/Atom}updated")
            or node.findtext("atom:published", default="", namespaces=ns)
        )
        if not title or not link:
            continue
        items.append(
            RemoteNewsDraft(
                title=title,
                summary=_truncate(_strip_html(summary), 400),
                source_url=link,
                source_name=source.name,
                source_id=source.id,
                published_at=_parse_datetime(updated),
            )
        )
        if len(items) >= source.max_items:
            break
    return items


def parse_html_list_payload(body: str, *, source: HealthNewsSourceProfile) -> list[RemoteNewsDraft]:
    parser = _AnchorCollector(
        base_url=source.list_url,
        path_contains=source.link_path_contains,
    )
    parser.feed(body)
    drafts: list[RemoteNewsDraft] = []
    seen: set[str] = set()
    for href, title in parser.links:
        if href in seen:
            continue
        seen.add(href)
        drafts.append(
            RemoteNewsDraft(
                title=title,
                summary="",
                source_url=href,
                source_name=source.name,
                source_id=source.id,
                published_at=None,
            )
        )
        if len(drafts) >= source.max_items:
            break
    return drafts


def resolve_active_sources(settings=None) -> list[HealthNewsSourceProfile]:
    settings = settings or get_settings()
    allowed = settings.health_news_allowed_domain_set
    selected_ids = settings.health_news_source_id_set
    active: list[HealthNewsSourceProfile] = []
    for source in BUILTIN_SOURCES:
        if selected_ids and source.id not in selected_ids:
            continue
        if not _host_allowed(source.list_url, allowed):
            continue
        active.append(source)
    # Operator override URLs: id|name|url|kind
    for raw in settings.health_news_extra_sources_list:
        parts = [part.strip() for part in raw.split("|")]
        if len(parts) < 3:
            continue
        source_id, name, url = parts[0], parts[1], parts[2]
        kind = parts[3] if len(parts) > 3 else "rss"
        path_hint = parts[4] if len(parts) > 4 else ""
        if kind not in {"rss", "html_list"}:
            continue
        if not _host_allowed(url, allowed):
            continue
        active.append(
            HealthNewsSourceProfile(
                id=source_id[:64],
                name=name[:80],
                list_url=url[:500],
                kind=kind,  # type: ignore[arg-type]
                link_path_contains=path_hint[:120],
            )
        )
    return active


def _local_response(
    *,
    status: StatusLiteral,
    season: str,
    when: datetime,
    degraded_reason: str | None = None,
    cache_status: CacheLiteral = "none",
    fetched_at: datetime | None = None,
    sources_attempted: list[str] | None = None,
    remote_items: list[HealthNewsItem] | None = None,
    include_seasonal: bool = True,
) -> dict[str, Any]:
    settings = get_settings()
    items: list[HealthNewsItem] = list(remote_items or [])
    if include_seasonal:
        seasonal = build_seasonal_items(when=when)
        # Prefer remote cards; pad with seasonal up to max.
        existing_titles = {item.title for item in items}
        for card in seasonal:
            if len(items) >= settings.health_news_max_items:
                break
            if card.title in existing_titles:
                continue
            items.append(card)
    items = items[: settings.health_news_max_items]
    payload = HealthNewsApiResponse(
        status=status,
        cache_status=cache_status,
        season=season,
        generated_at=when,
        fetched_at=fetched_at,
        disclaimer=DISCLAIMER,
        degraded_reason=degraded_reason,
        sources_attempted=sources_attempted or [],
        items=items,
    )
    return payload.model_dump(mode="json")


async def _http_get(url: str, *, timeout: float) -> httpx.Response:
    settings = get_settings()
    attempts = max(1, settings.health_news_retry_attempts)
    backoff = settings.health_news_retry_backoff_seconds
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                headers={"User-Agent": "HomeCareTwin-HealthNews/1.0 (local-teaching-demo)"},
            ) as client:
                response = await client.get(url)
            if response.status_code == 429:
                raise httpx.HTTPStatusError(
                    "rate limited",
                    request=response.request,
                    response=response,
                )
            if response.status_code >= 500:
                raise httpx.HTTPStatusError(
                    "server error",
                    request=response.request,
                    response=response,
                )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt + 1 < attempts:
                await asyncio.sleep(backoff * (attempt + 1))
    assert last_error is not None
    raise last_error


def _validate_response_chain(
    response: httpx.Response,
    *,
    allowed_hosts: set[str],
) -> None:
    """Reject every URL observed while following a source redirect chain."""
    for hop in (*response.history, response):
        url = str(hop.url)
        if not _host_allowed(url, allowed_hosts) or not is_health_news_egress_allowed(url):
            logger.warning("health_news: redirect left allowlist url=%s", url)
            raise HealthNewsEgressBlockedError("health_news_redirect_blocked")


def _filter_drafts_by_egress(
    drafts: list[RemoteNewsDraft],
    *,
    allowed_hosts: set[str],
) -> list[RemoteNewsDraft]:
    kept: list[RemoteNewsDraft] = []
    for draft in drafts:
        # Article hosts must be on the same allowlist as list endpoints.
        if not _host_allowed(draft.source_url, allowed_hosts):
            continue
        kept.append(draft)
    return kept


async def _fetch_source(
    source: HealthNewsSourceProfile,
    *,
    allowed_hosts: set[str],
) -> list[RemoteNewsDraft]:
    settings = get_settings()
    if not is_health_news_egress_allowed(source.list_url):
        logger.warning("health_news: egress blocked for source=%s", source.id)
        return []
    response = await _http_get(
        source.list_url,
        timeout=settings.health_news_timeout_seconds,
    )
    _validate_response_chain(response, allowed_hosts=allowed_hosts)
    body = response.text
    content_type = (response.headers.get("content-type") or "").lower()
    if source.kind == "rss" or "xml" in content_type or body.lstrip().startswith("<?xml"):
        drafts = parse_rss_payload(body, source=source)
    else:
        drafts = parse_html_list_payload(body, source=source)
    return _filter_drafts_by_egress(drafts, allowed_hosts=allowed_hosts)


async def fetch_health_news(*, when: datetime | None = None) -> dict[str, Any]:
    """Return home-screen health news with remote whitelist + seasonal fallback."""
    settings = get_settings()
    moment = when or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    local = moment.astimezone()
    season = season_key_for(local.month)

    mode = (settings.health_news_adapter or "local").strip().casefold()
    if mode in {"disabled", "off", "false", "0"}:
        return _local_response(
            status="disabled",
            season=season,
            when=local,
            degraded_reason="health_news_adapter_disabled",
        )
    if mode in {"local", "seasonal", ""}:
        return _local_response(status="local_only", season=season, when=local)

    if mode != "enabled":
        return _local_response(
            status="error",
            season=season,
            when=local,
            degraded_reason="health_news_adapter_invalid",
        )

    allowed = settings.health_news_allowed_domain_set
    if not allowed:
        return _local_response(
            status="unconfigured",
            season=season,
            when=local,
            degraded_reason="health_news_allowlist_empty",
        )

    sources = resolve_active_sources(settings)
    if not sources:
        return _local_response(
            status="unconfigured",
            season=season,
            when=local,
            degraded_reason="health_news_no_active_sources",
        )

    global _cache, _last_request_at
    async with _lock:
        now_mono = monotonic()
        if _cache is not None:
            age = now_mono - _cache.stored_at
            if age <= settings.health_news_cache_ttl_seconds:
                return _local_response(
                    status="ok",
                    season=season,
                    when=local,
                    cache_status="fresh",
                    fetched_at=_cache.fetched_at,
                    sources_attempted=_cache.sources_attempted,
                    remote_items=_cache.items,
                )

        interval = settings.health_news_min_request_interval_seconds
        if interval > 0 and _last_request_at and (now_mono - _last_request_at) < interval:
            stale_ok = (
                _cache is not None
                and (now_mono - _cache.stored_at) <= settings.health_news_stale_ttl_seconds
            )
            if stale_ok:
                return _local_response(
                    status="stale",
                    season=season,
                    when=local,
                    cache_status="stale",
                    fetched_at=_cache.fetched_at,
                    sources_attempted=_cache.sources_attempted,
                    remote_items=_cache.items,
                    degraded_reason="rate_limited",
                )
            return _local_response(
                status="rate_limited",
                season=season,
                when=local,
                degraded_reason="rate_limited",
            )

        _last_request_at = now_mono
        fetched_at = datetime.now(UTC)
        remote_items: list[HealthNewsItem] = []
        attempted: list[str] = []
        errors: list[str] = []

        for source in sources:
            attempted.append(source.id)
            try:
                drafts = await _fetch_source(source, allowed_hosts=allowed)
                for draft in drafts:
                    item = draft_to_item(draft, fetched_at=fetched_at)
                    if item is not None:
                        remote_items.append(item)
            except httpx.TimeoutException:
                errors.append(f"{source.id}:timeout")
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code if exc.response is not None else 0
                if code == 429:
                    errors.append(f"{source.id}:rate_limited")
                else:
                    errors.append(f"{source.id}:http_{code}")
            except HealthNewsEgressBlockedError:
                errors.append(f"{source.id}:egress_blocked")
            except ValueError:
                errors.append(f"{source.id}:invalid_response")
            except Exception as exc:  # noqa: BLE001
                logger.warning("health_news source=%s failed: %s", source.id, str(exc)[:160])
                errors.append(f"{source.id}:error")

        # Dedupe by URL / title
        deduped: list[HealthNewsItem] = []
        seen_keys: set[str] = set()
        for item in remote_items:
            key = (item.source_url or item.title).casefold()
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(item)
        remote_items = deduped[: settings.health_news_max_items]

        if remote_items:
            _cache = _CacheEntry(
                items=list(remote_items),
                fetched_at=fetched_at,
                sources_attempted=attempted,
                stored_at=monotonic(),
            )
            return _local_response(
                status="ok",
                season=season,
                when=local,
                cache_status="miss",
                fetched_at=fetched_at,
                sources_attempted=attempted,
                remote_items=remote_items,
            )

        stale_age_ok = (
            _cache is not None
            and (monotonic() - _cache.stored_at) <= settings.health_news_stale_ttl_seconds
        )
        if stale_age_ok:
            reason = "provider_unavailable"
            if any("timeout" in err for err in errors):
                reason = "timeout"
            elif any("rate_limited" in err for err in errors):
                reason = "rate_limited"
            elif any("invalid_response" in err for err in errors):
                reason = "invalid_response"
            elif any("egress_blocked" in err for err in errors):
                reason = "egress_blocked"
            return _local_response(
                status="stale",
                season=season,
                when=local,
                cache_status="stale",
                fetched_at=_cache.fetched_at,
                sources_attempted=_cache.sources_attempted,
                remote_items=_cache.items,
                degraded_reason=reason,
            )

        status: StatusLiteral = "provider_unavailable"
        if any("timeout" in err for err in errors):
            status = "timeout"
        elif any("invalid_response" in err for err in errors):
            status = "invalid_response"
        elif any("egress_blocked" in err for err in errors):
            status = "egress_blocked"
        return _local_response(
            status=status,
            season=season,
            when=local,
            cache_status="none",
            sources_attempted=attempted,
            degraded_reason=";".join(errors) if errors else "no_remote_items",
            remote_items=[],
        )
