"""Validation helpers for household business-day time zones."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def validate_iana_time_zone(value: str) -> str:
    """Return a canonical input string only when the local tz database accepts it."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("TIME_ZONE_INVALID")
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("TIME_ZONE_INVALID") from exc
    return value
