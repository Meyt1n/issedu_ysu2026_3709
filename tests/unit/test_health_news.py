"""Tests for proactive seasonal health-news cards."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.health_news import build_health_news


def test_health_news_summer_cards_are_actionable() -> None:
    payload = build_health_news(
        when=datetime(2026, 8, 25, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert payload.season == "summer"
    assert len(payload.items) >= 1
    assert all(item.chat_prompt for item in payload.items)
    assert "教学" in payload.disclaimer or "医生" in payload.disclaimer
    assert "病毒" not in payload.items[0].title or "不" in payload.items[0].summary


def test_health_news_winter_mentions_warmth() -> None:
    payload = build_health_news(
        when=datetime(2026, 1, 12, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert payload.season == "winter"
    joined = " ".join(item.summary for item in payload.items)
    assert "保暖" in joined or "冬季" in joined
