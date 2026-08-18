from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest

import app.weather_adapter as weather_adapter
from app.config import get_settings


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


def response(status_code: int, payload: Any) -> httpx.Response:
    request = httpx.Request("GET", "https://weather.example.com/current")
    return httpx.Response(status_code, request=request, json=payload)


@pytest.fixture(autouse=True)
def reset_weather_state() -> Iterator[None]:
    weather_adapter.reset_weather_state()
    yield
    weather_adapter.reset_weather_state()


@pytest.fixture()
def enabled_weather(monkeypatch: pytest.MonkeyPatch) -> object:
    settings = get_settings()
    monkeypatch.setattr(settings, "weather_adapter", "enabled")
    monkeypatch.setattr(settings, "weather_api_url", "https://weather.example.com/current")
    monkeypatch.setattr(settings, "egress_weather_whitelist", "weather.example.com")
    monkeypatch.setattr(settings, "weather_location_whitelist", "110000,110108")
    monkeypatch.setattr(settings, "weather_default_city_code", "110000")
    monkeypatch.setattr(settings, "weather_default_district_code", "")
    monkeypatch.setattr(settings, "weather_cache_ttl_seconds", 600.0)
    monkeypatch.setattr(settings, "weather_stale_ttl_seconds", 3600.0)
    monkeypatch.setattr(settings, "weather_min_request_interval_seconds", 0.0)
    monkeypatch.setattr(settings, "weather_retry_attempts", 2)
    monkeypatch.setattr(settings, "weather_retry_backoff_seconds", 0.0)
    monkeypatch.setattr(settings, "weather_ruleset_version", "weather-actions-v1")
    return settings


@pytest.mark.anyio
async def test_rejects_location_outside_configured_whitelist(
    enabled_weather: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_client(**_kwargs: Any) -> None:
        raise AssertionError("disallowed location must not create an HTTP client")

    monkeypatch.setattr(weather_adapter.httpx, "AsyncClient", unexpected_client)

    result = await weather_adapter.fetch_weather(city_code="310000")

    assert result["status"] == "location_not_allowed"
    assert result["action_cards"] == []
    assert "city_code" not in result


@pytest.mark.anyio
async def test_valid_response_has_version_source_scope_and_non_medical_notice(
    enabled_weather: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SequenceClient(
        [
            response(
                200,
                {
                    "temperature": 37,
                    "humidity": 62,
                    "condition": "sunny",
                    "wind": "2级",
                    "aqi": 80,
                    "observed_at": "2026-08-18T01:00:00Z",
                    "member_id": "must-not-be-forwarded",
                },
            )
        ]
    )
    monkeypatch.setattr(weather_adapter.httpx, "AsyncClient", lambda **_kwargs: client)

    result = await weather_adapter.fetch_weather(city_code="110000")

    assert result["status"] == "ok"
    assert result["cache_status"] == "miss"
    assert result["location_scope"] == "city"
    assert result["ruleset_version"] == "weather-actions-v1"
    assert result["source_observed_at"].startswith("2026-08-18T01:00:00")
    assert result["fetched_at"]
    assert "不构成诊断或用药建议" in result["disclaimer"]
    assert result["action_cards"][0]["rule_id"] == "heat-high"
    assert "member_id" not in result
    assert client.requests[0]["params"] == {"city_code": "110000"}


@pytest.mark.anyio
async def test_fresh_cache_prevents_duplicate_external_requests(
    enabled_weather: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SequenceClient([response(200, {"temperature": 22, "aqi": 40})])
    monkeypatch.setattr(weather_adapter.httpx, "AsyncClient", lambda **_kwargs: client)

    first = await weather_adapter.fetch_weather(city_code="110000")
    second = await weather_adapter.fetch_weather(city_code="110000")

    assert first["cache_status"] == "miss"
    assert second["status"] == "ok"
    assert second["cache_status"] == "fresh"
    assert client.calls == 1


@pytest.mark.anyio
async def test_timeout_falls_back_to_last_valid_cache(
    enabled_weather: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "weather_cache_ttl_seconds", 0.0)
    request = httpx.Request("GET", settings.weather_api_url)
    client = SequenceClient(
        [
            response(200, {"temperature": 9, "aqi": 30}),
            httpx.ReadTimeout("slow weather service", request=request),
            httpx.ReadTimeout("still slow", request=request),
        ]
    )
    monkeypatch.setattr(weather_adapter.httpx, "AsyncClient", lambda **_kwargs: client)

    await weather_adapter.fetch_weather(city_code="110000")
    degraded = await weather_adapter.fetch_weather(city_code="110000")

    assert degraded["status"] == "stale"
    assert degraded["cache_status"] == "stale"
    assert degraded["degraded_reason"] == "timeout"
    assert degraded["temperature"] == 9
    assert client.calls == 3


@pytest.mark.anyio
async def test_retries_5xx_then_succeeds(
    enabled_weather: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SequenceClient(
        [response(503, {"error": "busy"}), response(200, {"temperature": 18, "aqi": 42})]
    )
    monkeypatch.setattr(weather_adapter.httpx, "AsyncClient", lambda **_kwargs: client)

    result = await weather_adapter.fetch_weather(city_code="110000")

    assert result["status"] == "ok"
    assert client.calls == 2


@pytest.mark.anyio
async def test_429_is_not_retried(
    enabled_weather: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SequenceClient([response(429, {"error": "too many requests"})])
    monkeypatch.setattr(weather_adapter.httpx, "AsyncClient", lambda **_kwargs: client)

    result = await weather_adapter.fetch_weather(city_code="110000")

    assert result["status"] == "rate_limited"
    assert result["action_cards"] == []
    assert client.calls == 1


@pytest.mark.anyio
async def test_invalid_provider_payload_is_rejected_without_fake_data(
    enabled_weather: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SequenceClient([response(200, {"temperature": "very hot", "humidity": 140})])
    monkeypatch.setattr(weather_adapter.httpx, "AsyncClient", lambda **_kwargs: client)

    result = await weather_adapter.fetch_weather(city_code="110000")

    assert result["status"] == "invalid_response"
    assert result["action_cards"] == []
    assert "temperature" not in result


@pytest.mark.anyio
async def test_empty_provider_payload_is_not_reported_as_success(
    enabled_weather: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SequenceClient([response(200, {})])
    monkeypatch.setattr(weather_adapter.httpx, "AsyncClient", lambda **_kwargs: client)

    result = await weather_adapter.fetch_weather(city_code="110000")

    assert result["status"] == "invalid_response"
    assert result["action_cards"] == []


def test_weather_route_rejects_non_code_input(client: Any) -> None:
    result = client.get("/api/v1/weather/action-cards?city_code=../precise-address")

    assert result.status_code == 422


def test_weather_route_publishes_versioned_response_contract(client: Any) -> None:
    schema = client.get("/openapi.json").json()
    response_schema = schema["paths"]["/api/v1/weather/action-cards"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]

    assert response_schema["$ref"].endswith("/WeatherActionCardsResponse")
