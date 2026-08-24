"""
Weather adapter — the single whitelisted external integration.

Only allowlisted city/district codes leave the local trusted domain. Provider
responses are validated before they can produce versioned, non-medical action
cards. Fresh and stale caches keep this optional dependency off core flows.
"""

from __future__ import annotations

import asyncio
import logging
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Any, Literal

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.config import get_settings
from app.egress_guard import allowed_weather_payload, is_egress_allowed

logger = logging.getLogger(__name__)

LOCATION_CODE_PATTERN = re.compile(r"^\d{6}$")
DEFAULT_RULESET_VERSION = "weather-actions-v1"
WEATHER_DISCLAIMER = "环境行动建议仅供日常生活安排参考，不构成诊断或用药建议。"
UAPIS_PROVIDER = "uapis"


class WeatherAdapterError(Exception):
    """Base class for controlled, non-blocking weather adapter failures."""


class WeatherEgressBlocked(WeatherAdapterError):
    """Raised when the weather API URL is not in the egress whitelist."""


class WeatherPayloadRejected(WeatherAdapterError):
    """Raised when the request body contains forbidden fields."""


class WeatherProviderPayload(BaseModel):
    """Known-safe subset accepted from the external weather provider."""

    model_config = ConfigDict(extra="ignore", strict=True, allow_inf_nan=False)

    temperature: float | None = Field(default=None, ge=-90, le=70)
    humidity: float | None = Field(default=None, ge=0, le=100)
    condition: str | None = Field(default=None, max_length=40)
    wind: str | None = Field(default=None, max_length=80)
    aqi: float | None = Field(default=None, ge=0, le=1000)
    observed_at: datetime | None = None

    @field_validator("temperature", "humidity", "aqi", mode="before")
    @classmethod
    def accept_json_numbers_only(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("a JSON number is required")
        return float(value)

    @field_validator("observed_at", mode="before")
    @classmethod
    def parse_iso_observation_time(cls, value: object) -> object:
        if value is None or isinstance(value, datetime):
            return value
        if not isinstance(value, str):
            raise ValueError("an ISO timestamp is required")
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("an ISO timestamp is required") from exc

    @field_validator("condition", "wind")
    @classmethod
    def reject_control_characters(cls, value: str | None) -> str | None:
        if value is not None and any(ord(character) < 32 for character in value):
            raise ValueError("control characters are not allowed")
        return value

    @model_validator(mode="after")
    def require_environment_observation(self) -> WeatherProviderPayload:
        values = (self.temperature, self.humidity, self.condition, self.wind, self.aqi)
        if all(value is None for value in values):
            raise ValueError("at least one environment observation is required")
        return self


class WeatherActionCardResponse(BaseModel):
    rule_id: str
    level: Literal["info", "warning"]
    message: str


class WeatherActionCardsResponse(BaseModel):
    status: Literal[
        "ok",
        "stale",
        "disabled",
        "unconfigured",
        "location_required",
        "location_invalid",
        "location_not_allowed",
        "rejected",
        "egress_blocked",
        "rate_limited",
        "timeout",
        "provider_unavailable",
        "invalid_response",
        "error",
    ]
    cache_status: Literal["none", "miss", "fresh", "stale"]
    location_scope: Literal["city", "district"] | None = None
    ruleset_version: str
    source_observed_at: str | None = None
    fetched_at: str | None = None
    disclaimer: str
    degraded_reason: str | None = None
    temperature: float | None = None
    humidity: float | None = None
    condition: str | None = None
    wind: str | None = None
    aqi: float | None = None
    action_cards: list[WeatherActionCardResponse]


@dataclass(frozen=True)
class WeatherCacheEntry:
    payload: dict[str, Any]
    stored_at: float


_weather_cache: dict[tuple[str, str], WeatherCacheEntry] = {}
_last_request_at: dict[tuple[str, str], float] = {}
_weather_lock = asyncio.Lock()


def reset_weather_state() -> None:
    """Clear process-local weather state for tests and controlled reloads."""
    global _weather_lock
    _weather_cache.clear()
    _last_request_at.clear()
    _weather_lock = asyncio.Lock()


def _location_scope(district_code: str) -> str:
    return "district" if district_code else "city"


def _empty_response(
    status: str,
    *,
    location_scope: str | None = None,
    degraded_reason: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    result: dict[str, Any] = {
        "status": status,
        "cache_status": "none",
        "location_scope": location_scope,
        "ruleset_version": settings.weather_ruleset_version,
        "source_observed_at": None,
        "fetched_at": None,
        "disclaimer": WEATHER_DISCLAIMER,
        "action_cards": [],
    }
    if degraded_reason:
        result["degraded_reason"] = degraded_reason
    return result


def _resolve_location(
    city_code: str | None,
    district_code: str | None,
) -> tuple[dict[str, str] | None, dict[str, Any] | None]:
    settings = get_settings()
    city = (city_code or settings.weather_default_city_code).strip()
    district = (district_code or settings.weather_default_district_code).strip()
    scope = _location_scope(district)

    if not city:
        return None, _empty_response("location_required")
    if not LOCATION_CODE_PATTERN.fullmatch(city) or (
        district and not LOCATION_CODE_PATTERN.fullmatch(district)
    ):
        return None, _empty_response("location_invalid", location_scope=scope)

    whitelist = settings.weather_location_whitelist_set
    if not whitelist or city not in whitelist or (district and district not in whitelist):
        logger.warning("weather_adapter: location rejected scope=%s", scope)
        return None, _empty_response("location_not_allowed", location_scope=scope)

    body = {"city_code": city}
    if district:
        body["district_code"] = district
    return body, None


def _iso_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _normalize_uapis_condition(value: object) -> str | None:
    """Map provider-specific Chinese conditions to the rule vocabulary."""
    if not isinstance(value, str):
        return None
    condition = value.strip()
    if not condition:
        return None
    if "雷" in condition:
        return "thunderstorm"
    if "雨" in condition:
        return "storm" if "暴" in condition else "rain"
    if "雪" in condition:
        return "snow"
    if "晴" in condition:
        return "sunny"
    if "云" in condition or "阴" in condition:
        return "cloudy"
    return condition[:40]


def _normalize_uapis_observed_at(value: object) -> object:
    """Treat the provider's local China time as Asia/Shanghai, not UTC."""
    if not isinstance(value, str):
        return value
    observed_at = value.strip()
    if not observed_at:
        return None
    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?",
        observed_at,
    ):
        return None
    if observed_at.endswith("Z") or "+" in observed_at[10:]:
        return observed_at
    return f"{observed_at.replace(' ', 'T')}+08:00"


def _normalize_provider_payload(payload: object) -> object:
    """Convert an explicitly configured provider into the canonical schema."""
    settings = get_settings()
    if settings.weather_provider != UAPIS_PROVIDER:
        return payload
    if not isinstance(payload, dict):
        return payload

    wind_direction = payload.get("wind_direction")
    wind_power = payload.get("wind_power")
    wind_parts = [
        part.strip()
        for part in (wind_direction, wind_power)
        if isinstance(part, str) and part.strip()
    ]
    return {
        "temperature": payload.get("temperature"),
        "humidity": payload.get("humidity"),
        "condition": _normalize_uapis_condition(payload.get("weather")),
        "wind": " · ".join(wind_parts) or None,
        "aqi": payload.get("aqi"),
        "observed_at": _normalize_uapis_observed_at(payload.get("report_time")),
    }


def _provider_params(body: dict[str, str]) -> dict[str, str]:
    """Build provider params from the already validated coarse location body."""
    settings = get_settings()
    if settings.weather_provider == UAPIS_PROVIDER:
        return {"adcode": body.get("district_code") or body["city_code"]}
    return body


def generate_action_cards(
    weather_data: dict[str, Any],
    *,
    location_scope: str | None = None,
    ruleset_version: str = DEFAULT_RULESET_VERSION,
) -> dict[str, Any]:
    """Generate deterministic, versioned environment-only action cards."""
    cards: list[dict[str, str]] = []
    temp = weather_data.get("temperature")
    condition = str(weather_data.get("condition") or "").lower()
    humidity = weather_data.get("humidity")
    aqi = weather_data.get("aqi")

    if isinstance(temp, (int, float)):
        if temp > 35:
            cards.append(
                {
                    "rule_id": "heat-high",
                    "level": "warning",
                    "message": "高温提醒：建议减少长时间户外活动，及时补充饮水并留意室内通风。",
                }
            )
        elif temp > 30:
            cards.append(
                {
                    "rule_id": "heat-warm",
                    "level": "info",
                    "message": "天气较热：外出可携带饮水，优先安排在较凉爽时段活动。",
                }
            )
        elif temp < 5:
            cards.append(
                {
                    "rule_id": "cold-low",
                    "level": "warning",
                    "message": "低温提醒：外出注意保暖，并留意雨雪后的湿滑路面。",
                }
            )

    if condition in {"rain", "snow", "storm", "thunderstorm"}:
        cards.append(
            {
                "rule_id": "rain-travel",
                "level": "info",
                "message": "雨雪天气：外出携带雨具，合理预留通行时间并注意路面安全。",
            }
        )

    if isinstance(humidity, (int, float)) and humidity > 90:
        cards.append(
            {
                "rule_id": "humidity-high",
                "level": "info",
                "message": "空气湿度较高：可适时除湿并保持室内物品干燥。",
            }
        )

    if isinstance(aqi, (int, float)) and aqi > 150:
        cards.append(
            {
                "rule_id": "aqi-high",
                "level": "warning",
                "message": "空气污染水平较高：建议减少长时间户外活动，按需调整开窗时间。",
            }
        )

    return {
        "status": "ok",
        "cache_status": "miss",
        "location_scope": location_scope,
        "ruleset_version": ruleset_version,
        "source_observed_at": _iso_datetime(weather_data.get("observed_at")),
        "fetched_at": datetime.now(UTC).isoformat(),
        "disclaimer": WEATHER_DISCLAIMER,
        "temperature": temp,
        "humidity": humidity,
        "condition": condition or None,
        "wind": weather_data.get("wind"),
        "aqi": aqi,
        "action_cards": cards,
    }


def _cached_response(entry: WeatherCacheEntry, cache_status: str) -> dict[str, Any]:
    result = deepcopy(entry.payload)
    result["cache_status"] = cache_status
    return result


def _fallback_response(
    entry: WeatherCacheEntry | None,
    *,
    now: float,
    reason: str,
    location_scope: str,
) -> dict[str, Any]:
    settings = get_settings()
    stale_ttl = max(settings.weather_stale_ttl_seconds, 0.0)
    if entry is not None and now - entry.stored_at < stale_ttl:
        result = _cached_response(entry, "stale")
        result["status"] = "stale"
        result["degraded_reason"] = reason
        return result
    return _empty_response(reason, location_scope=location_scope, degraded_reason=reason)


async def _request_provider(
    body: dict[str, str],
) -> tuple[WeatherProviderPayload | None, str | None]:
    settings = get_settings()
    attempts = min(max(settings.weather_retry_attempts, 1), 3)
    last_reason = "error"

    async with httpx.AsyncClient(timeout=settings.weather_api_timeout_seconds) as client:
        for attempt in range(attempts):
            try:
                response = await client.get(
                    settings.weather_api_url,
                    params=_provider_params(body),
                    headers={"Accept": "application/json"},
                )
                if response.status_code == 429:
                    logger.warning("weather_adapter: provider rate limited request")
                    return None, "rate_limited"
                response.raise_for_status()
                try:
                    payload = WeatherProviderPayload.model_validate(
                        _normalize_provider_payload(response.json())
                    )
                except (ValidationError, ValueError, TypeError):
                    logger.warning("weather_adapter: provider response failed schema validation")
                    return None, "invalid_response"
                return payload, None
            except httpx.TimeoutException:
                last_reason = "timeout"
                logger.warning(
                    "weather_adapter: timeout attempt=%d/%d timeout=%.1fs",
                    attempt + 1,
                    attempts,
                    settings.weather_api_timeout_seconds,
                )
            except httpx.HTTPStatusError as exc:
                last_reason = "provider_unavailable" if exc.response.status_code >= 500 else "error"
                logger.warning(
                    "weather_adapter: provider HTTP status=%d attempt=%d/%d",
                    exc.response.status_code,
                    attempt + 1,
                    attempts,
                )
                if exc.response.status_code < 500:
                    return None, last_reason
            except httpx.RequestError:
                last_reason = "provider_unavailable"
                logger.warning(
                    "weather_adapter: provider request failed attempt=%d/%d",
                    attempt + 1,
                    attempts,
                )
            except Exception:
                logger.exception("weather_adapter: unexpected provider failure")
                return None, "error"

            if attempt + 1 < attempts and settings.weather_retry_backoff_seconds > 0:
                await asyncio.sleep(settings.weather_retry_backoff_seconds * (attempt + 1))

    return None, last_reason


async def fetch_weather(
    city_code: str | None = None,
    district_code: str | None = None,
) -> dict[str, Any]:
    """Fetch validated weather data without blocking local core flows."""
    settings = get_settings()
    if settings.weather_adapter == "disabled":
        return _empty_response("disabled")
    if not settings.weather_api_url:
        logger.info("weather_adapter: no provider configured")
        return _empty_response("unconfigured")

    body, location_error = _resolve_location(city_code, district_code)
    if location_error is not None:
        return location_error
    assert body is not None
    scope = _location_scope(body.get("district_code", ""))

    valid, reason = allowed_weather_payload(body)
    if not valid:
        logger.warning("weather_adapter: outbound payload rejected reason=%s", reason)
        return _empty_response("rejected", location_scope=scope)
    if not is_egress_allowed(settings.weather_api_url):
        logger.warning("weather_adapter: provider host blocked by egress policy")
        return _empty_response("egress_blocked", location_scope=scope)

    key = (body["city_code"], body.get("district_code", ""))
    now = monotonic()
    cached = _weather_cache.get(key)
    cache_ttl = max(settings.weather_cache_ttl_seconds, 0.0)
    if cached is not None and now - cached.stored_at < cache_ttl:
        return _cached_response(cached, "fresh")

    async with _weather_lock:
        now = monotonic()
        cached = _weather_cache.get(key)
        if cached is not None and now - cached.stored_at < cache_ttl:
            return _cached_response(cached, "fresh")

        minimum_interval = max(settings.weather_min_request_interval_seconds, 0.0)
        last_request = _last_request_at.get(key)
        if last_request is not None and now - last_request < minimum_interval:
            return _fallback_response(
                cached,
                now=now,
                reason="rate_limited",
                location_scope=scope,
            )

        _last_request_at[key] = now
        provider_payload, failure = await _request_provider(body)
        if provider_payload is None:
            return _fallback_response(
                cached,
                now=monotonic(),
                reason=failure or "error",
                location_scope=scope,
            )

        result = generate_action_cards(
            provider_payload.model_dump(),
            location_scope=scope,
            ruleset_version=settings.weather_ruleset_version,
        )
        _weather_cache[key] = WeatherCacheEntry(payload=deepcopy(result), stored_at=monotonic())
        return result
