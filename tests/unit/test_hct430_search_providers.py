"""HCT-430 search provider abstraction tests."""

from __future__ import annotations

from app.config import Settings
from app.search_providers import (
    DuckDuckGoHtmlProvider,
    SearXNGProvider,
    execute_web_search,
    get_search_provider,
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
    results = execute_web_search("test", settings=Settings())
    assert results[0]["title"] == "x"
