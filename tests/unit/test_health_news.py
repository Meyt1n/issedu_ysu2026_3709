"""Tests for seasonal health-news baseline and HCT-445 remote adapter."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

import app.health_news_adapter as health_news_adapter
from app.config import get_settings
from app.egress_guard import is_health_news_egress_allowed
from app.health_news import build_health_news
from app.health_news_adapter import (
    HealthNewsSourceProfile,
    draft_to_item,
    parse_html_list_payload,
    parse_rss_payload,
    reset_health_news_state,
)


def test_health_news_summer_cards_are_actionable() -> None:
    payload = build_health_news(
        when=datetime(2026, 8, 25, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert payload.season == "summer"
    assert len(payload.items) >= 1
    assert all(item.chat_prompt for item in payload.items)
    assert "教学" in payload.disclaimer or "医生" in payload.disclaimer
    assert payload.status == "local_only"


def test_health_news_winter_mentions_warmth() -> None:
    payload = build_health_news(
        when=datetime(2026, 1, 12, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert payload.season == "winter"
    joined = " ".join(item.summary for item in payload.items)
    assert "保暖" in joined or "冬季" in joined


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>WHO News</title>
    <item>
      <title>Heat and hydration guidance for families</title>
      <link>https://www.who.int/news/item/01-heat</link>
      <description>Stay cool and drink water during hot weather.</description>
      <pubDate>Mon, 25 Aug 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>在线问诊秒杀购药广告</title>
      <link>https://www.who.int/news/item/02-spam</link>
      <description>should be filtered</description>
    </item>
  </channel>
</rss>
"""

SAMPLE_HTML = """
<html><body>
<ul>
  <li><a href="/xcs/yqfkdt/202608/t20260825_1.shtml">秋季呼吸道健康提示</a></li>
  <li><a href="/other/skip.shtml">无关链接</a></li>
  <li><a href="https://evil.example/xcs/phish.shtml">钓鱼</a></li>
</ul>
</body></html>
"""


class SequenceClient:
    def __init__(self, outcomes: list[httpx.Response | Exception]) -> None:
        self.outcomes = outcomes
        self.calls = 0
        self.requests: list[dict[str, Any]] = []

    async def __aenter__(self) -> SequenceClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        self.requests.append({"url": url, **kwargs})
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _response(url: str, status_code: int, text: str) -> httpx.Response:
    request = httpx.Request("GET", url)
    return httpx.Response(
        status_code,
        request=request,
        text=text,
        headers={"content-type": "application/rss+xml"},
    )


def _redirected_response(
    *,
    source_url: str,
    final_url: str,
    text: str,
    history_urls: list[str] | None = None,
) -> httpx.Response:
    history = [
        httpx.Response(
            302,
            request=httpx.Request("GET", history_url),
            headers={"location": final_url},
        )
        for history_url in history_urls or [source_url]
    ]
    return httpx.Response(
        200,
        request=httpx.Request("GET", final_url),
        text=text,
        headers={"content-type": "application/rss+xml"},
        history=history,
    )


@pytest.fixture(autouse=True)
def _reset_state() -> Iterator[None]:
    reset_health_news_state()
    yield
    reset_health_news_state()


@pytest.fixture()
def enabled_news(monkeypatch: pytest.MonkeyPatch) -> object:
    settings = get_settings()
    monkeypatch.setattr(settings, "health_news_adapter", "enabled")
    monkeypatch.setattr(
        settings,
        "health_news_allowed_domains",
        "www.who.int,www.nhc.gov.cn",
    )
    monkeypatch.setattr(settings, "health_news_source_ids", "who_news_en")
    monkeypatch.setattr(settings, "health_news_extra_sources", "")
    monkeypatch.setattr(settings, "health_news_cache_ttl_seconds", 600.0)
    monkeypatch.setattr(settings, "health_news_stale_ttl_seconds", 3600.0)
    monkeypatch.setattr(settings, "health_news_min_request_interval_seconds", 0.0)
    monkeypatch.setattr(settings, "health_news_retry_attempts", 1)
    monkeypatch.setattr(settings, "health_news_retry_backoff_seconds", 0.0)
    monkeypatch.setattr(settings, "health_news_max_items", 6)
    monkeypatch.setattr(settings, "health_news_timeout_seconds", 2.0)
    return settings


def test_parse_rss_and_filter_commercial_titles() -> None:
    source = HealthNewsSourceProfile(
        id="who_news_en",
        name="世界卫生组织",
        list_url="https://www.who.int/rss-feeds/news-english.xml",
        kind="rss",
    )
    drafts = parse_rss_payload(SAMPLE_RSS, source=source)
    assert len(drafts) == 2
    fetched = datetime(2026, 8, 25, tzinfo=ZoneInfo("UTC"))
    items = [draft_to_item(draft, fetched_at=fetched) for draft in drafts]
    kept = [item for item in items if item is not None]
    assert len(kept) == 1
    assert kept[0].source_name == "世界卫生组织"
    assert kept[0].source_url and kept[0].source_url.startswith("https://")
    assert kept[0].fetched_at is not None


def test_parse_html_list_respects_path_hint() -> None:
    source = HealthNewsSourceProfile(
        id="nhc_xwzx",
        name="国家卫生健康委员会",
        list_url="https://www.nhc.gov.cn/xcs/yqfkdt/list_gzbd.shtml",
        kind="html_list",
        link_path_contains="/xcs/",
    )
    drafts = parse_html_list_payload(SAMPLE_HTML, source=source)
    assert len(drafts) == 2
    assert all("/xcs/" in d.source_url for d in drafts)


def test_egress_requires_enabled_and_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "health_news_adapter", "local")
    assert not is_health_news_egress_allowed("https://www.who.int/rss-feeds/news-english.xml")
    monkeypatch.setattr(settings, "health_news_adapter", "enabled")
    monkeypatch.setattr(settings, "health_news_allowed_domains", "")
    assert not is_health_news_egress_allowed("https://www.who.int/rss-feeds/news-english.xml")
    monkeypatch.setattr(settings, "health_news_allowed_domains", "www.who.int")
    assert is_health_news_egress_allowed("https://www.who.int/rss-feeds/news-english.xml")
    assert not is_health_news_egress_allowed("http://www.who.int/rss-feeds/news-english.xml")
    assert not is_health_news_egress_allowed("https://evil.example/news")


@pytest.mark.anyio
async def test_local_adapter_never_calls_http(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "health_news_adapter", "local")

    def unexpected(**_kwargs: Any) -> None:
        raise AssertionError("local mode must not create HTTP client")

    monkeypatch.setattr(health_news_adapter.httpx, "AsyncClient", unexpected)
    result = await health_news_adapter.fetch_health_news(
        when=datetime(2026, 8, 25, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert result["status"] == "local_only"
    assert result["items"]
    assert all(item["source"] == "seasonal_calendar" for item in result["items"])


@pytest.mark.anyio
async def test_unconfigured_allowlist_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "health_news_adapter", "enabled")
    monkeypatch.setattr(settings, "health_news_allowed_domains", "")

    def unexpected(**_kwargs: Any) -> None:
        raise AssertionError("empty allowlist must not create HTTP client")

    monkeypatch.setattr(health_news_adapter.httpx, "AsyncClient", unexpected)
    result = await health_news_adapter.fetch_health_news()
    assert result["status"] == "unconfigured"
    assert result["degraded_reason"]
    assert result["items"]


@pytest.mark.anyio
async def test_remote_ok_then_fresh_cache(
    enabled_news: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://www.who.int/rss-feeds/news-english.xml"
    client = SequenceClient([_response(url, 200, SAMPLE_RSS)])
    monkeypatch.setattr(
        health_news_adapter.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    first = await health_news_adapter.fetch_health_news(
        when=datetime(2026, 8, 25, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert first["status"] == "ok"
    remote = [item for item in first["items"] if item["source"] == "remote_whitelist"]
    assert len(remote) == 1
    assert remote[0]["source_name"] == "世界卫生组织"
    assert remote[0]["fetched_at"]
    assert "购药" not in remote[0]["title"]

    # Second call must hit fresh cache (no extra HTTP).
    second = await health_news_adapter.fetch_health_news(
        when=datetime(2026, 8, 25, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert second["cache_status"] == "fresh"
    assert client.calls == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("final_url", "history_urls"),
    [
        ("https://evil.example/news.xml", None),
        ("https://www.who.int/news.xml", ["https://evil.example/redirect"]),
    ],
)
async def test_redirect_chain_leaving_allowlist_is_blocked_without_caching(
    enabled_news: object,
    monkeypatch: pytest.MonkeyPatch,
    final_url: str,
    history_urls: list[str] | None,
) -> None:
    source_url = "https://www.who.int/rss-feeds/news-english.xml"
    client = SequenceClient(
        [
            _redirected_response(
                source_url=source_url,
                final_url=final_url,
                history_urls=history_urls,
                text=SAMPLE_RSS,
            )
        ]
    )
    monkeypatch.setattr(
        health_news_adapter.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )

    result = await health_news_adapter.fetch_health_news(
        when=datetime(2026, 8, 25, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert result["status"] == "egress_blocked"
    assert result["cache_status"] == "none"
    assert all(item["source"] == "seasonal_calendar" for item in result["items"])
    assert health_news_adapter._cache is None


@pytest.mark.anyio
async def test_allowlisted_redirect_is_parsed_and_cached(
    enabled_news: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_url = "https://www.who.int/rss-feeds/news-english.xml"
    final_url = "https://www.who.int/news.xml"
    client = SequenceClient(
        [
            _redirected_response(
                source_url=source_url,
                final_url=final_url,
                text=SAMPLE_RSS,
            )
        ]
    )
    monkeypatch.setattr(
        health_news_adapter.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )

    result = await health_news_adapter.fetch_health_news(
        when=datetime(2026, 8, 25, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert result["status"] == "ok"
    assert any(item["source"] == "remote_whitelist" for item in result["items"])
    assert health_news_adapter._cache is not None


@pytest.mark.anyio
async def test_provider_failure_uses_stale_cache(
    enabled_news: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://www.who.int/rss-feeds/news-english.xml"
    client = SequenceClient(
        [
            _response(url, 200, SAMPLE_RSS),
            httpx.TimeoutException("boom"),
        ]
    )
    monkeypatch.setattr(
        health_news_adapter.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    first = await health_news_adapter.fetch_health_news(
        when=datetime(2026, 8, 25, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert first["status"] == "ok"
    # Expire fresh TTL but keep entry within stale TTL.
    assert health_news_adapter._cache is not None
    monkeypatch.setattr(get_settings(), "health_news_cache_ttl_seconds", 1.0)
    monkeypatch.setattr(get_settings(), "health_news_stale_ttl_seconds", 3600.0)
    health_news_adapter._cache.stored_at -= 30

    second = await health_news_adapter.fetch_health_news(
        when=datetime(2026, 8, 25, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert second["status"] == "stale"
    assert second["cache_status"] == "stale"
    assert any(item["source"] == "remote_whitelist" for item in second["items"])


@pytest.mark.anyio
async def test_provider_failure_without_cache_keeps_seasonal(
    enabled_news: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SequenceClient([httpx.TimeoutException("offline")])
    monkeypatch.setattr(
        health_news_adapter.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    result = await health_news_adapter.fetch_health_news(
        when=datetime(2026, 8, 25, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert result["status"] == "timeout"
    assert result["items"]
    assert all(item["source"] == "seasonal_calendar" for item in result["items"])
    assert "编造" in result["disclaimer"] or "教学" in result["disclaimer"]
