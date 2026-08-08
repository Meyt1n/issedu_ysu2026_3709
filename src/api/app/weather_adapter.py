"""
Weather adapter — the single whitelisted external integration.

Sends at most city/district codes to a weather API. Never transmits
member, health, report, image, vector, or conversation content.
Failure must never block local core flows.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings
from app.egress_guard import allowed_weather_payload, is_egress_allowed

logger = logging.getLogger(__name__)


class WeatherAdapterError(Exception):
    """Non-blocking weather adapter error."""


class WeatherEgressBlocked(WeatherAdapterError):
    """Raised when the weather API URL is not in the egress whitelist."""


class WeatherPayloadRejected(WeatherAdapterError):
    """Raised when the request body contains forbidden fields."""


async def fetch_weather(
    city_code: str | None = None,
    district_code: str | None = None,
) -> dict[str, Any]:
    """Fetch weather action cards for a location.

    Only city_code and district_code are sent — no health data.
    Returns an empty action card on any failure.
    """
    settings = get_settings()
    if settings.weather_adapter == "disabled":
        return {"status": "disabled", "action_cards": []}

    if not settings.weather_api_url:
        logger.info("weather_adapter: no weather_api_url configured, returning empty")
        return {"status": "unconfigured", "action_cards": []}

    body: dict[str, Any] = {}
    if city_code is not None:
        body["city_code"] = city_code
    if district_code is not None:
        body["district_code"] = district_code

    valid, reason = allowed_weather_payload(body)
    if not valid:
        logger.warning("weather_adapter: payload rejected reason=%s", reason)
        return {"status": "rejected", "action_cards": [], "reason": reason}

    if not is_egress_allowed(settings.weather_api_url):
        logger.warning("weather_adapter: egress blocked url=%s", settings.weather_api_url)
        return {"status": "egress_blocked", "action_cards": []}

    try:
        async with httpx.AsyncClient(timeout=settings.weather_api_timeout_seconds) as client:
            response = await client.get(
                settings.weather_api_url,
                params=body,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            # Ensure response does not accidentally echo back health data.
            # Only keep known-safe weather keys.
            safe: dict[str, Any] = {
                "status": "ok",
                "temperature": data.get("temperature"),
                "humidity": data.get("humidity"),
                "condition": data.get("condition"),
                "wind": data.get("wind"),
                "aqi": data.get("aqi"),
                "action_cards": data.get("action_cards", []),
            }
            return generate_action_cards(safe)
    except httpx.TimeoutException:
        logger.warning("weather_adapter: timeout after %.1fs", settings.weather_api_timeout_seconds)
        return {"status": "timeout", "action_cards": []}
    except httpx.HTTPStatusError as exc:
        logger.warning("weather_adapter: HTTP %d from weather API", exc.response.status_code)
        return {"status": "error", "action_cards": []}
    except Exception:
        logger.exception("weather_adapter: unexpected error")
        return {"status": "error", "action_cards": []}


def generate_action_cards(weather_data: dict[str, Any]) -> dict[str, Any]:
    """Generate environment action cards from weather data.

    Never includes health data — only environment-based recommendations.
    """
    cards: list[dict[str, str]] = []
    temp = weather_data.get("temperature")
    condition = str(weather_data.get("condition", "")).lower()
    humidity = weather_data.get("humidity")
    aqi = weather_data.get("aqi")

    if temp is not None:
        if temp > 35:
            cards.append({"level": "warning", "message": "高温预警：建议减少户外活动，注意防暑降温"})
        elif temp > 30:
            cards.append({"level": "info", "message": "天气较热：注意补充水分"})
        elif temp < 5:
            cards.append({"level": "warning", "message": "低温提醒：注意保暖，预防感冒"})

    if condition and condition in ("rain", "snow", "storm", "thunderstorm"):
        cards.append({"level": "info", "message": "雨雪天气：出行注意安全，携带雨具"})

    if isinstance(humidity, (int, float)) and humidity > 90:
        cards.append({"level": "info", "message": "高湿度提醒：注意防潮"})

    if isinstance(aqi, (int, float)) and aqi > 150:
        cards.append({"level": "warning", "message": "空气污染：建议减少开窗通风"})

    return {
        "status": "ok",
        "temperature": temp,
        "humidity": humidity,
        "condition": condition,
        "wind": weather_data.get("wind"),
        "aqi": aqi,
        "action_cards": cards,
    }
