"""HCT-430 search provider abstraction tests."""

from __future__ import annotations

from app.config import Settings
from app.search_providers import (
    DuckDuckGoHtmlProvider,
    SearXNGProvider,
    clear_search_cache,
    execute_web_search,
    get_search_provider,
    rank_search_results,
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
    assert isinstance(get_search_provider(duck), DuckDuckGoHtmlProvider)
    assert isinstance(get_search_provider(searx), SearXNGProvider)


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
    settings = Settings(agent_web_search_cache_ttl_seconds=300)
    first = execute_web_search("布洛芬注意事项", settings=settings)
    second = execute_web_search("布洛芬注意事项", settings=settings)
    assert first == second
    assert calls["count"] == 1
