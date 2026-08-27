"""HCT-430 search provider abstraction tests."""

from __future__ import annotations

from app.config import Settings
from app.search_providers import (
    DuckDuckGoHtmlProvider,
    FixtureSearchProvider,
    SearchRedirected,
    SearXNGProvider,
    clear_search_cache,
    enrich_results_with_pages,
    execute_web_search,
    fetch_result_page_excerpt,
    filter_referral_results,
    get_search_provider,
    is_fixture_search_provider,
    parse_search_results,
    rank_search_results,
    strip_referral_sentences,
)


def test_searxng_provider_parses_json_results(monkeypatch) -> None:
    payload = {
        "results": [
            {"title": "标题一", "url": "https://example.com/a", "content": "摘要一"},
            {"title": "标题二", "url": "https://example.org/b", "snippet": "摘要二"},
        ],
    }

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return payload

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, params):
            assert params["format"] == "json"
            return FakeResponse()

    monkeypatch.setattr("app.search_providers.httpx.Client", FakeClient)
    settings = Settings(
        agent_web_search_url="https://search.example/search",
        agent_web_search_max_results=5,
    )
    results = SearXNGProvider().search("布洛芬注意事项", settings=settings)

    assert [item["url"] for item in results] == [
        "https://example.com/a",
        "https://example.org/b",
    ]


def test_get_search_provider_selects_backend() -> None:
    duck = Settings(agent_web_search_provider="duckduckgo_html")
    searx = Settings(agent_web_search_provider="searxng")
    fixture = Settings(agent_web_search_provider="fixture")
    assert isinstance(get_search_provider(duck), DuckDuckGoHtmlProvider)
    assert isinstance(get_search_provider(searx), SearXNGProvider)
    assert isinstance(get_search_provider(fixture), FixtureSearchProvider)
    assert is_fixture_search_provider(fixture) is True
    assert is_fixture_search_provider(duck) is False


def test_fixture_provider_serves_offline_teaching_results(monkeypatch) -> None:
    """Fixture search must not construct any HTTP client and must self-label."""

    class _NoNetwork:
        def __init__(self, *args, **kwargs):
            raise AssertionError("fixture provider must never open an HTTP client")

    monkeypatch.setattr("app.search_providers.httpx.Client", _NoNetwork)
    settings = Settings(
        agent_web_search_provider="fixture",
        agent_web_search_max_results=3,
    )
    results = FixtureSearchProvider().search("药箱 过期 存放", settings=settings)

    assert results
    assert len(results) <= 3
    assert results[0]["url"] == "https://fixture.invalid/med-storage"
    assert all(item["source"] == "teaching_fixture" for item in results)
    assert all("教学夹具" in f"{item['title']}{item['snippet']}" for item in results)


def test_fixture_provider_falls_back_to_generic_entries() -> None:
    settings = Settings(agent_web_search_provider="fixture")
    results = FixtureSearchProvider().search("zzz-no-overlap-zzz", settings=settings)
    assert results, "demo queries should always show the reference layout"


def test_fixture_execute_web_search_skips_rate_limit() -> None:
    clear_search_cache()
    settings = Settings(
        agent_web_search_provider="fixture",
        agent_web_search_cache_ttl_seconds=0,
        agent_web_search_min_interval_seconds=30,
    )
    first = execute_web_search("第一次夹具查询", settings=settings)
    second = execute_web_search("第二次夹具查询", settings=settings)
    assert first and second


def test_execute_web_search_delegates_to_provider(monkeypatch) -> None:
    class _StubProvider:
        def search(self, query: str, *, settings: Settings):
            return [{
                "title": "x",
                "url": "https://example.com",
                "snippet": "",
                "domain": "example.com",
                "source": "external_web_search",
            }]

    monkeypatch.setattr(
        "app.search_providers.get_search_provider",
        lambda settings: _StubProvider(),
    )
    clear_search_cache()
    results = execute_web_search("test", settings=Settings(agent_web_search_cache_ttl_seconds=0))
    assert results[0]["title"] == "x"


def test_rank_search_results_prefers_query_overlap_and_medical_domains() -> None:
    ranked = rank_search_results(
        "布洛芬 注意事项",
        [
            {
                "title": "无关新闻",
                "url": "https://news.example/a",
                "snippet": "体育比分",
                "domain": "news.example",
            },
            {
                "title": "布洛芬注意事项",
                "url": "https://www.nih.gov/ibuprofen",
                "snippet": "用药提示",
                "domain": "www.nih.gov",
            },
        ],
        max_results=2,
    )
    assert ranked[0]["domain"] == "www.nih.gov"


def test_execute_web_search_uses_ttl_cache(monkeypatch) -> None:
    calls = {"count": 0}

    class _StubProvider:
        def search(self, query: str, *, settings: Settings):
            calls["count"] += 1
            return [{
                "title": "布洛芬说明书",
                "url": "https://example.com/ibu",
                "snippet": "布洛芬注意事项",
                "domain": "example.com",
                "source": "external_web_search",
            }]

    monkeypatch.setattr(
        "app.search_providers.get_search_provider",
        lambda settings: _StubProvider(),
    )
    clear_search_cache()
    settings = Settings(
        agent_web_search_cache_ttl_seconds=300,
        agent_web_search_min_interval_seconds=0,
    )
    first = execute_web_search("布洛芬注意事项", settings=settings)
    second = execute_web_search("布洛芬注意事项", settings=settings)
    assert first == second
    assert calls["count"] == 1


def test_execute_web_search_enforces_min_interval(monkeypatch) -> None:
    from app.search_providers import SearchRateLimited

    class _StubProvider:
        def search(self, query: str, *, settings: Settings):
            return [{
                "title": "a",
                "url": "https://example.com/a",
                "snippet": "a",
                "domain": "example.com",
                "source": "external_web_search",
            }]

    monkeypatch.setattr(
        "app.search_providers.get_search_provider",
        lambda settings: _StubProvider(),
    )
    clear_search_cache()
    settings = Settings(
        agent_web_search_cache_ttl_seconds=0,
        agent_web_search_min_interval_seconds=30,
    )
    execute_web_search("第一次", settings=settings)
    try:
        execute_web_search("第二次", settings=settings)
        raised = False
    except SearchRateLimited:
        raised = True
    assert raised is True


# ── Audit-5 P0: DuckDuckGo snippet parsing ───────────────────────────────

_DDG_RESULT_PAGE = """
<div class="result results_links results_links_deep web-result">
  <h2 class="result__title">
    <a rel="nofollow" class="result__a"
       href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.example.org%2Fflu-care&amp;rut=a1">
      流感季家庭护理要点</a>
  </h2>
  <a class="result__snippet"
     href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.example.org%2Fflu-care&amp;rut=a1">
    <b>流感</b>季节注意休息补水，出现高热持续不退请及时就医。</a>
</div>
<div class="result">
  <h2 class="result__title">
    <a rel="nofollow" class="result__a"
       href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fhealth.example.net%2Fcold&amp;rut=b2">
      感冒居家观察指引</a>
  </h2>
  <a class="result__snippet"
     href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fhealth.example.net%2Fcold&amp;rut=b2">
    多数感冒可居家观察，注意补水与休息。</a>
</div>
"""


def test_duckduckgo_snippet_anchor_with_uddg_is_not_a_new_result() -> None:
    """P0 (audit-5): snippet anchors carry uddg= hrefs; they must be captured
    as snippets instead of starting a new (empty) result — the old behaviour
    lost 100% of abstracts."""
    results = parse_search_results(_DDG_RESULT_PAGE, 5)
    assert len(results) == 2
    assert results[0]["url"] == "https://www.example.org/flu-care"
    assert "休息补水" in results[0]["snippet"]
    assert "居家观察" in results[1]["snippet"]


def test_redirect_response_is_a_failure_not_an_empty_success(monkeypatch) -> None:
    """3xx ≠ empty success: the provider raises and metrics record a failure."""

    class RedirectResponse:
        status_code = 302
        headers = {"location": "https://elsewhere.example/"}
        text = ""

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, params):
            return RedirectResponse()

    monkeypatch.setattr("app.search_providers.httpx.Client", FakeClient)
    clear_search_cache()
    settings = Settings(
        agent_web_search_cache_ttl_seconds=0,
        agent_web_search_min_interval_seconds=0,
    )
    try:
        DuckDuckGoHtmlProvider().search("查询", settings=settings)
        raised = False
    except SearchRedirected:
        raised = True
    assert raised is True


def test_empty_results_use_short_cache_ttl(monkeypatch) -> None:
    """An empty result page must not suppress retries for the whole TTL."""
    calls = {"count": 0}

    class _EmptyProvider:
        def search(self, query: str, *, settings: Settings):
            calls["count"] += 1
            return []

    monkeypatch.setattr(
        "app.search_providers.get_search_provider",
        lambda settings: _EmptyProvider(),
    )
    clear_search_cache()
    settings = Settings(
        agent_web_search_cache_ttl_seconds=300,
        agent_web_search_empty_cache_ttl_seconds=0,
        agent_web_search_min_interval_seconds=0,
    )
    assert execute_web_search("空结果查询", settings=settings) == []
    assert execute_web_search("空结果查询", settings=settings) == []
    # empty TTL 0 → empty result not cached, provider called again.
    assert calls["count"] == 2


def test_referral_and_ad_results_are_filtered() -> None:
    results = [
        {
            "title": "布洛芬使用注意事项",
            "url": "https://www.nih.gov/ibu",
            "snippet": "公开科普内容",
            "domain": "www.nih.gov",
        },
        {
            "title": "立即购买特效药 限时优惠",
            "url": "https://shop.example.com/buy",
            "snippet": "加微信咨询，药房直送。",
            "domain": "shop.example.com",
        },
        {
            "title": "在线问诊一分钟开药",
            "url": "https://consult.example.com/x",
            "snippet": "在线问诊，快速购药。",
            "domain": "consult.example.com",
        },
    ]
    kept = filter_referral_results(results)
    assert [item["title"] for item in kept] == ["布洛芬使用注意事项"]


def test_strip_referral_sentences_keeps_normal_content() -> None:
    text = "这是正常科普内容。立即购买特效药！另一句正常说明。"
    cleaned = strip_referral_sentences(text)
    assert "立即购买" not in cleaned
    assert "正常科普内容" in cleaned
    assert "另一句正常说明" in cleaned


def test_open_mode_page_fetch_requires_public_https(monkeypatch) -> None:
    """SSRF guard: non-public hosts are never fetched in open mode."""
    monkeypatch.setattr(
        "app.egress_guard.is_public_https_url", lambda url: False
    )
    settings = Settings(agent_web_search_egress_mode="open")
    assert fetch_result_page_excerpt("https://internal.lan/x", settings=settings) is None


def test_enrich_results_with_pages_only_in_open_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.search_providers.fetch_result_page_excerpt",
        lambda url, settings: "页面正文摘录",
    )
    results = [{
        "title": "公开科普",
        "url": "https://www.example.org/a",
        "snippet": "摘要",
        "domain": "www.example.org",
        "source": "external_web_search",
    }]
    allowlist_settings = Settings(agent_web_search_egress_mode="allowlist")
    assert "page_excerpt" not in enrich_results_with_pages(
        [dict(results[0])], settings=allowlist_settings
    )[0]
    open_settings = Settings(
        agent_web_search_egress_mode="open",
        agent_web_search_fetch_page_count=2,
    )
    enriched = enrich_results_with_pages([dict(results[0])], settings=open_settings)
    assert enriched[0]["page_excerpt"] == "页面正文摘录"
