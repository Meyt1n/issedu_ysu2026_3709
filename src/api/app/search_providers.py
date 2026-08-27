"""HCT-430 pluggable local web-search providers.

All providers run from the API process and must pass the HCT-430 egress
allowlist.  Results are supplemental references only.
"""

from __future__ import annotations

import html as html_lib
import logging
import re
import threading
import time
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

FIXTURE_PROVIDER = "fixture"


def is_fixture_search_provider(settings: Settings) -> bool:
    """True when the deployment uses the offline teaching-fixture provider."""
    return (settings.agent_web_search_provider or "").strip().casefold() == FIXTURE_PROVIDER


_MEDICAL_DOMAIN_HINTS = (
    "nih.gov",
    "who.int",
    "cdc.gov",
    "mayoclinic.org",
    "medlineplus.gov",
    "drugs.com",
    "webmd.com",
    "nmpa.gov.cn",
    "nhc.gov.cn",
    "cma.org.cn",
    "msdmanuals.com",
    "uptodate.com",
    "gov.cn",
    "edu.cn",
)

_CACHE_LOCK = threading.Lock()
_SEARCH_CACHE: dict[str, tuple[float, list[dict[str, str]]]] = {}
_LAST_SEARCH_AT = 0.0
_METRICS = {
    "cache_hits": 0,
    "cache_misses": 0,
    "rate_limited": 0,
    "searches": 0,
    "last_outcome": None,
    "last_error": None,
    "last_config": None,
}


class SearchRateLimited(RuntimeError):
    """Raised when searches are fired faster than the configured interval."""


class SearchRedirected(RuntimeError):
    """Raised when the provider answers with a 3xx instead of a result page.

    Audit-5: a redirect is a failed search, never a successful empty result —
    treating it as「0 条结果」cached the emptiness and hid the outage.
    """


def _enforce_min_interval(settings: Settings) -> None:
    global _LAST_SEARCH_AT
    interval = float(settings.agent_web_search_min_interval_seconds or 0)
    if interval <= 0:
        return
    with _CACHE_LOCK:
        now = time.monotonic()
        wait = interval - (now - _LAST_SEARCH_AT)
        if wait > 0:
            _METRICS["rate_limited"] += 1
            raise SearchRateLimited(f"search rate limited for {wait:.2f}s")
        _LAST_SEARCH_AT = now


class SearchProvider(Protocol):
    """Fetch external reference snippets for a redacted query."""

    def search(self, query: str, *, settings: Settings) -> list[dict[str, str]]:
        ...


class _DuckDuckGoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._capture: str | None = None
        self._buffer: list[str] = []
        self._pending_title_link = False

    @staticmethod
    def _classes(attrs: list[tuple[str, str | None]]) -> set[str]:
        raw = dict(attrs).get("class") or ""
        return {item.strip() for item in raw.split() if item.strip()}

    def _flush_buffer(self) -> None:
        if self._current is not None and self._capture:
            value = html_lib.unescape("".join(self._buffer)).strip()
            if value:
                self._current[self._capture] = re.sub(r"\s+", " ", value)
        self._buffer = []

    _RESULT_LINK_CLASSES = {"result__a", "result__title", "result-link"}
    _TITLE_WRAPPER_CLASSES = {"result__title", "result-title"}
    _SNIPPET_CLASSES = {"result__snippet", "result-snippet", "snippet"}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = self._classes(attrs)
        # Audit-5 P0: DuckDuckGo snippets are themselves anchors —
        # ``<a class="result__snippet" href="…uddg=…">摘要</a>``.  The old
        # ``uddg=`` heuristic treated every such anchor as a *new* title link,
        # so 100% of snippets were lost.  Snippet capture must win first.
        if self._current is not None and classes & self._SNIPPET_CLASSES:
            self._flush_buffer()
            self._capture = "snippet"
            self._buffer = []
            return
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if (
                classes & self._RESULT_LINK_CLASSES
                or self._pending_title_link
                or "uddg=" in href
            ):
                self._pending_title_link = False
                if self._current and self._current.get("title"):
                    self.results.append(self._current)
                self._current = {"title": "", "snippet": "", "url": href}
                self._capture = "title"
                self._buffer = []
                return
        elif classes & self._TITLE_WRAPPER_CLASSES:
            self._pending_title_link = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h1", "h2", "h3"}:
            self._pending_title_link = False
        if self._capture == "title" and tag == "a":
            self._flush_buffer()
            self._capture = None
        elif self._capture == "snippet" and tag in {"div", "a", "span"}:
            self._flush_buffer()
            self._capture = None

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)

    def close(self) -> None:
        self._flush_buffer()
        if self._current and self._current.get("title"):
            self.results.append(self._current)
        super().close()


def _result_url(raw_url: str) -> str | None:
    raw_url = html_lib.unescape(str(raw_url or "")).strip()
    if raw_url.startswith("//"):
        raw_url = "https:" + raw_url
    parsed = urlparse(raw_url)
    query = parse_qs(parsed.query)
    if query.get("uddg"):
        raw_url = unquote(query["uddg"][0])
        parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return raw_url


def _normalize_results(items: list[dict[str, str]], max_results: int) -> list[dict[str, str]]:
    parsed: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        url = _result_url(item.get("url", ""))
        title = item.get("title", "").strip()
        if not url or not title or url in seen:
            continue
        seen.add(url)
        parsed.append({
            "title": title[:180],
            "url": url,
            "snippet": (item.get("snippet") or "").strip()[:500],
            "domain": urlparse(url).hostname or "",
            "source": item.get("source") or "external_web_search",
        })
        if len(parsed) >= max_results:
            break
    return parsed


def parse_search_results(body: str, max_results: int = 5) -> list[dict[str, str]]:
    parser = _DuckDuckGoParser()
    try:
        parser.feed(str(body or ""))
        parser.close()
    except Exception:
        logger.warning("HCT-430 search result page could not be parsed")
    return _normalize_results(parser.results, max_results)


def _query_tokens(query: str) -> set[str]:
    tokens = re.findall(r"[\w\u4e00-\u9fff]{2,}", str(query or "").casefold())
    return set(tokens)


# ── Referral / advertising filter (decision 3B: rule filtering) ─────────
#
# Open retrieval may surface commercial drug-purchase or tele-consultation
# funnels.  Those results are dropped before ranking: the assistant must not
# relay "buy medicine here / chat with our doctor now" solicitations.
_REFERRAL_AD_RE = re.compile(
    "|".join((
        "立即购买", "马上购买", "立刻下单", "一键下单", "低价抢购", "限时优惠",
        "优惠券", "促销", "秒杀", "包邮", "免费领取", "加微信", "加v信",
        "扫码咨询", "扫码购买", "在线问诊", "在线购药", "网上药店", "药房直送",
        "买药上", "购药请", "预约挂号立减", "点击购买", "点击咨询",
    )),
    re.IGNORECASE,
)
_REFERRAL_DOMAIN_HINTS = (
    "taobao.com",
    "tmall.com",
    "jd.com",
    "pinduoduo.com",
    "yduoduo",
    "111.com.cn",
)


def is_referral_result(item: dict[str, str]) -> bool:
    """True when a search result reads like a purchase / consultation funnel."""
    domain = (item.get("domain") or urlparse(item.get("url") or "").hostname or "").casefold()
    if any(hint in domain for hint in _REFERRAL_DOMAIN_HINTS):
        return True
    haystack = f"{item.get('title', '')} {item.get('snippet', '')}"
    return bool(_REFERRAL_AD_RE.search(haystack))


def filter_referral_results(results: list[dict[str, str]]) -> list[dict[str, str]]:
    kept = [item for item in results if not is_referral_result(item)]
    dropped = len(results) - len(kept)
    if dropped:
        logger.info("HCT-430 dropped %d referral/ad search results", dropped)
    return kept


def strip_referral_sentences(text: str) -> str:
    """Remove purchase / consultation solicitation sentences from an excerpt."""
    parts = re.split(r"(?<=[。！？!?；;\n])", str(text or ""))
    kept = [part for part in parts if part.strip() and not _REFERRAL_AD_RE.search(part)]
    return "".join(kept).strip()


def rank_search_results(
    query: str,
    results: list[dict[str, str]],
    *,
    max_results: int,
) -> list[dict[str, str]]:
    """Prefer results that overlap the query terms or come from medical domains."""
    tokens = _query_tokens(query)
    scored: list[tuple[int, dict[str, str]]] = []
    for item in results:
        haystack = f"{item.get('title', '')} {item.get('snippet', '')}".casefold()
        domain = (item.get("domain") or "").casefold()
        score = sum(1 for token in tokens if token in haystack)
        if any(hint in domain for hint in _MEDICAL_DOMAIN_HINTS):
            score += 2
        scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1].get("title", "")))
    # Keep low-scoring items only when nothing better exists, so empty pages
    # still surface whatever the provider returned.
    preferred = [item for score, item in scored if score > 0]
    ordered = preferred or [item for _, item in scored]
    return ordered[:max_results]


def _cache_key(settings: Settings, query: str) -> str:
    return "|".join([
        (settings.agent_web_search_provider or "duckduckgo_html").strip().casefold(),
        settings.agent_web_search_url.strip(),
        query.strip().casefold(),
    ])


def _cache_get(key: str, ttl_seconds: float) -> list[dict[str, str]] | None:
    if ttl_seconds <= 0:
        return None
    now = time.monotonic()
    with _CACHE_LOCK:
        entry = _SEARCH_CACHE.get(key)
        if not entry:
            _METRICS["cache_misses"] += 1
            return None
        expires_at, payload = entry
        if expires_at < now:
            _SEARCH_CACHE.pop(key, None)
            _METRICS["cache_misses"] += 1
            return None
        _METRICS["cache_hits"] += 1
        return [dict(item) for item in payload]


def _cache_put(key: str, results: list[dict[str, str]], ttl_seconds: float) -> None:
    if ttl_seconds <= 0:
        return
    with _CACHE_LOCK:
        _SEARCH_CACHE[key] = (
            time.monotonic() + ttl_seconds,
            [dict(item) for item in results],
        )
        # Bound memory: drop oldest-ish entries when the map grows too large.
        if len(_SEARCH_CACHE) > 256:
            oldest = sorted(_SEARCH_CACHE.items(), key=lambda item: item[1][0])[:64]
            for stale_key, _ in oldest:
                _SEARCH_CACHE.pop(stale_key, None)


def clear_search_cache() -> None:
    global _LAST_SEARCH_AT
    with _CACHE_LOCK:
        _SEARCH_CACHE.clear()
        _LAST_SEARCH_AT = 0.0


def search_ops_snapshot(settings: Settings | None = None) -> dict[str, Any]:
    """Read-only ops metrics for admin surfaces (no query text)."""
    from app.egress_guard import is_web_search_egress_allowed

    cfg = settings
    if cfg is None:
        from app.config import get_settings

        cfg = get_settings()
    ready = False
    if cfg.agent_web_search_enabled:
        ready = is_web_search_egress_allowed(cfg.agent_web_search_url.strip(), cfg)
    with _CACHE_LOCK:
        hits = int(_METRICS["cache_hits"])
        misses = int(_METRICS["cache_misses"])
        rate_limited = int(_METRICS["rate_limited"])
        searches = int(_METRICS["searches"])
        last_outcome = _METRICS["last_outcome"]
        last_error = _METRICS["last_error"]
        last_config = _METRICS["last_config"]
        cache_entries = len(_SEARCH_CACHE)
    # Configuration/allowlist checks alone are not proof that the provider is
    # reachable.  Once a real request fails, expose that observed state to the
    # UI and capability catalog until a subsequent request succeeds.
    current_config = "|".join([
        (cfg.agent_web_search_provider or "").strip().casefold(),
        cfg.agent_web_search_url.strip(),
    ])
    if last_outcome == "failure" and last_config == current_config:
        ready = False
    total_lookups = hits + misses
    hit_rate = (hits / total_lookups) if total_lookups else 0.0
    return {
        "web_search_enabled": bool(cfg.agent_web_search_enabled),
        "web_search_ready": ready,
        "web_search_provider": cfg.agent_web_search_provider,
        "cache_ttl_seconds": float(cfg.agent_web_search_cache_ttl_seconds or 0),
        "min_interval_seconds": float(cfg.agent_web_search_min_interval_seconds or 0),
        "cache_entries": cache_entries,
        "cache_hits": hits,
        "cache_misses": misses,
        "cache_hit_rate": round(hit_rate, 4),
        "rate_limited_hits": rate_limited,
        "searches": searches,
        "last_search_status": last_outcome,
        "last_search_error": last_error,
    }


def reset_search_ops_metrics() -> None:
    with _CACHE_LOCK:
        for key in _METRICS:
            _METRICS[key] = None if key.startswith("last_") else 0


def _reject_redirect(response: httpx.Response) -> None:
    """A 3xx answer is a provider failure, never a successful empty page."""
    if 300 <= response.status_code < 400:
        raise SearchRedirected(f"HTTP_{response.status_code}")


class DuckDuckGoHtmlProvider:
    """Parse DuckDuckGo's HTML result page (default provider)."""

    def search(self, query: str, *, settings: Settings) -> list[dict[str, str]]:
        params = {"q": query, "kl": "cn-zh", "kp": "-2"}
        with httpx.Client(
            timeout=settings.agent_web_search_timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": "HomeCareTwin-local-agent/1.0"},
        ) as client:
            response = client.get(settings.agent_web_search_url.strip(), params=params)
            _reject_redirect(response)
            response.raise_for_status()
        return parse_search_results(response.text, settings.agent_web_search_max_results * 2)


class SearXNGProvider:
    """Query a self-hosted SearXNG instance via its JSON API."""

    def search(self, query: str, *, settings: Settings) -> list[dict[str, str]]:
        endpoint = settings.agent_web_search_url.strip()
        params = {
            "q": query,
            "format": "json",
            "language": "zh-CN",
        }
        with httpx.Client(
            timeout=settings.agent_web_search_timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": "HomeCareTwin-local-agent/1.0"},
        ) as client:
            response = client.get(endpoint, params=params)
            _reject_redirect(response)
            response.raise_for_status()
            payload = response.json()
        raw_items = payload.get("results") if isinstance(payload, dict) else []
        items: list[dict[str, str]] = []
        if isinstance(raw_items, list):
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                items.append({
                    "title": str(item.get("title") or ""),
                    "url": str(item.get("url") or ""),
                    "snippet": str(item.get("content") or item.get("snippet") or ""),
                })
        return _normalize_results(items, settings.agent_web_search_max_results * 2)


# ── Open-mode result-page fetch (decision 3B / ADR-0007) ────────────────
#
# In ``AGENT_WEB_SEARCH_EGRESS_MODE=open`` the top result pages may be fetched
# as reference excerpts.  Every fetch is bounded: HTTPS public hosts only
# (SSRF guard), page count capped, bytes capped, redirects never followed,
# and referral/solicitation sentences stripped from the extracted text.


class _PageTextParser(HTMLParser):
    """Extract readable text from an HTML page (scripts/styles skipped)."""

    _SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "head"}
    _BLOCK_TAGS = {"p", "div", "li", "section", "article", "br", "h1", "h2", "h3", "h4", "td"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._chunks.append(data)

    def text(self) -> str:
        joined = "".join(self._chunks)
        lines = [re.sub(r"\s+", " ", line).strip() for line in joined.splitlines()]
        return "\n".join(line for line in lines if line)


def extract_page_text(body: str) -> str:
    parser = _PageTextParser()
    try:
        parser.feed(str(body or ""))
        parser.close()
    except Exception:
        logger.warning("HCT-430 result page HTML could not be parsed")
    return parser.text()


_PAGE_EXCERPT_MAX_CHARS = 600
_FETCHABLE_CONTENT_TYPES = ("text/html", "text/plain", "application/xhtml")


def fetch_result_page_excerpt(url: str, *, settings: Settings) -> str | None:
    """Fetch one public HTTPS result page under strict limits.

    Returns a referral-free text excerpt, or ``None`` when the page is not a
    public HTTPS host, is not HTML/plain text, redirects, or fails to load.
    """
    from app.egress_guard import is_public_https_url

    if not is_public_https_url(url):
        logger.warning("HCT-430 open-mode page fetch blocked (not a public HTTPS host)")
        return None
    max_bytes = int(getattr(settings, "agent_web_search_fetch_page_max_bytes", 262_144))
    timeout = float(getattr(settings, "agent_web_search_fetch_page_timeout_seconds", 6.0))
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": "HomeCareTwin-local-agent/1.0"},
        ) as client:
            with client.stream("GET", url) as response:
                if response.status_code != 200:
                    return None
                content_type = (response.headers.get("content-type") or "").casefold()
                if content_type and not any(
                    accepted in content_type for accepted in _FETCHABLE_CONTENT_TYPES
                ):
                    return None
                collected = bytearray()
                for chunk in response.iter_bytes():
                    collected.extend(chunk)
                    if len(collected) >= max_bytes:
                        break
    except Exception as exc:  # noqa: BLE001 — page fetch is best-effort
        logger.warning("HCT-430 result page fetch failed: %s", str(exc)[:120])
        return None
    body = bytes(collected[:max_bytes]).decode("utf-8", errors="ignore")
    text = strip_referral_sentences(extract_page_text(body))
    text = re.sub(r"\n{2,}", "\n", text).strip()
    if not text:
        return None
    return text[:_PAGE_EXCERPT_MAX_CHARS]


def enrich_results_with_pages(
    results: list[dict[str, str]],
    *,
    settings: Settings,
) -> list[dict[str, str]]:
    """Attach bounded page excerpts to the top results in open egress mode."""
    mode = (getattr(settings, "agent_web_search_egress_mode", "allowlist") or "").casefold()
    page_count = int(getattr(settings, "agent_web_search_fetch_page_count", 0) or 0)
    if mode != "open" or page_count <= 0:
        return results
    for item in results[:page_count]:
        if item.get("source") == "teaching_fixture":
            continue
        excerpt = fetch_result_page_excerpt(str(item.get("url") or ""), settings=settings)
        if excerpt:
            item["page_excerpt"] = excerpt
    return results


# Synthetic offline references for classroom demos.  ``fixture.invalid`` is an
# RFC 2606 reserved domain that can never resolve, so nothing here can be
# mistaken for a real page and no request ever leaves the process.  The copy
# stays on generic care-operations topics and never states medical facts.
_FIXTURE_SNIPPET_SUFFIX = "（教学夹具，非真实网页；外部参考不属于本地审核证据，不构成医疗建议。）"
_FIXTURE_RESULTS: tuple[dict[str, str], ...] = (
    {
        "title": "教学夹具：家庭药箱存放与过期检查提示",
        "url": "https://fixture.invalid/med-storage",
        "snippet": "演示如何展示药箱存放、避光避潮与定期检查有效期的公开科普入口。"
        + _FIXTURE_SNIPPET_SUFFIX,
        "keywords": "药箱 存放 过期 有效期 保存 储存 medication storage expiry",
        "source": "teaching_fixture",
    },
    {
        "title": "教学夹具：过敏信息分享边界科普导航",
        "url": "https://fixture.invalid/allergy-share",
        "snippet": "演示过敏史沟通与授权边界类公开资料在搜索结果中的展示样式。"
        + _FIXTURE_SNIPPET_SUFFIX,
        "keywords": "过敏 授权 分享 allergy",
        "source": "teaching_fixture",
    },
    {
        "title": "教学夹具：用药提醒与照护升级公开指引入口",
        "url": "https://fixture.invalid/reminder-escalation",
        "snippet": "演示提醒确认、延期与照护者升级流程类公开指引的检索展示。"
        + _FIXTURE_SNIPPET_SUFFIX,
        "keywords": "提醒 升级 确认 延期 漏服 reminder escalation",
        "source": "teaching_fixture",
    },
    {
        "title": "教学夹具：药品包装复核与条码核对科普入口",
        "url": "https://fixture.invalid/packaging-check",
        "snippet": "演示包装信息、条码冲突与人工复核类公开科普的检索展示。"
        + _FIXTURE_SNIPPET_SUFFIX,
        "keywords": "包装 条码 复核 核对 说明书 barcode packaging",
        "source": "teaching_fixture",
    },
    {
        "title": "教学夹具：家庭照护公开科普检索导航",
        "url": "https://fixture.invalid/care-navigation",
        "snippet": "通用教学占位结果：演示受控联网参考的展示位置与「非本地审核证据」标注。"
        + _FIXTURE_SNIPPET_SUFFIX,
        "keywords": "照护 科普 家庭 健康",
        "source": "teaching_fixture",
    },
)


class FixtureSearchProvider:
    """Serve offline teaching fixtures; performs no network egress at all."""

    def search(self, query: str, *, settings: Settings) -> list[dict[str, str]]:
        tokens = _query_tokens(query)
        scored: list[tuple[int, dict[str, str]]] = []
        for item in _FIXTURE_RESULTS:
            haystack = (
                f"{item['title']} {item['snippet']} {item.get('keywords', '')}".casefold()
            )
            score = sum(1 for token in tokens if token in haystack)
            scored.append((score, item))
        scored.sort(key=lambda pair: -pair[0])
        matched = [item for score, item in scored if score > 0]
        # A demo query should always show the reference layout, so fall back to
        # the generic fixtures when nothing overlaps the redacted query.
        chosen = matched or [item for _, item in scored]
        return _normalize_results(
            [dict(item) for item in chosen], settings.agent_web_search_max_results
        )


def get_search_provider(settings: Settings) -> SearchProvider:
    provider = (settings.agent_web_search_provider or "duckduckgo_html").strip().casefold()
    if provider == FIXTURE_PROVIDER:
        return FixtureSearchProvider()
    if provider == "searxng":
        return SearXNGProvider()
    return DuckDuckGoHtmlProvider()


def execute_web_search(query: str, *, settings: Settings) -> list[dict[str, str]]:
    ttl = float(settings.agent_web_search_cache_ttl_seconds or 0)
    key = _cache_key(settings, query)
    cached = _cache_get(key, ttl)
    if cached is not None:
        return rank_search_results(
            query, cached, max_results=settings.agent_web_search_max_results
        )

    try:
        # The rate limiter protects external endpoints; fixtures never leave
        # the process, so classroom demos are not throttled.
        if not is_fixture_search_provider(settings):
            _enforce_min_interval(settings)
        with _CACHE_LOCK:
            _METRICS["searches"] += 1
        raw = get_search_provider(settings).search(query, settings=settings)
    except SearchRateLimited:
        with _CACHE_LOCK:
            _METRICS["last_outcome"] = "failure"
            _METRICS["last_error"] = "RATE_LIMITED"
            _METRICS["last_config"] = "|".join([
                (settings.agent_web_search_provider or "").strip().casefold(),
                settings.agent_web_search_url.strip(),
            ])
        raise
    except Exception as exc:
        with _CACHE_LOCK:
            _METRICS["last_outcome"] = "failure"
            _METRICS["last_error"] = type(exc).__name__[:80]
            _METRICS["last_config"] = "|".join([
                (settings.agent_web_search_provider or "").strip().casefold(),
                settings.agent_web_search_url.strip(),
            ])
        raise
    with _CACHE_LOCK:
        _METRICS["last_outcome"] = "success"
        _METRICS["last_error"] = None
        _METRICS["last_config"] = "|".join([
            (settings.agent_web_search_provider or "").strip().casefold(),
            settings.agent_web_search_url.strip(),
        ])
    ranked = rank_search_results(
        query,
        filter_referral_results(raw),
        max_results=settings.agent_web_search_max_results,
    )
    ranked = enrich_results_with_pages(ranked, settings=settings)
    if ranked:
        _cache_put(key, ranked, ttl)
    else:
        # Audit-5: an empty page is cached only briefly so a transient empty
        # response cannot suppress retries for the whole TTL.
        empty_ttl = float(
            getattr(settings, "agent_web_search_empty_cache_ttl_seconds", 0) or 0
        )
        _cache_put(key, ranked, min(ttl, empty_ttl) if ttl > 0 else empty_ttl)
    return ranked
