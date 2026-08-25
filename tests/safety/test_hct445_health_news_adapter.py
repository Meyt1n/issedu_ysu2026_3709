"""HCT-445 safety tests for health-news egress and response hygiene."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import app.health_news_adapter as health_news_adapter
from app.config import get_settings
from app.health_news_adapter import reset_health_news_state


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_health_news_state()
    yield
    reset_health_news_state()


@pytest.mark.anyio
async def test_enabled_without_matching_source_does_not_egress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "health_news_adapter", "enabled")
    monkeypatch.setattr(settings, "health_news_allowed_domains", "news.example.com")
    monkeypatch.setattr(settings, "health_news_source_ids", "who_news_en")
    monkeypatch.setattr(settings, "health_news_extra_sources", "")

    def unexpected(**_kwargs: object) -> None:
        raise AssertionError("non-matching sources must not open HTTP")

    monkeypatch.setattr(health_news_adapter.httpx, "AsyncClient", unexpected)
    result = await health_news_adapter.fetch_health_news(
        when=datetime(2026, 8, 25, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert result["status"] == "unconfigured"
    assert result["items"]
    assert "member_id" not in result
    assert "household_id" not in result


@pytest.mark.anyio
async def test_response_never_embeds_forbidden_health_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "health_news_adapter", "local")
    result = await health_news_adapter.fetch_health_news()
    blob = str(result).casefold()
    for forbidden in ("member_id", "household_id", "allergy", "prescription"):
        assert forbidden not in blob
