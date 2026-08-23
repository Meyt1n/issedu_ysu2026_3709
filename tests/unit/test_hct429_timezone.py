"""HCT-429: household time zones accept only local IANA names."""

import pytest

from app.config import Settings
from app.time_zone import validate_iana_time_zone


@pytest.mark.parametrize("value", ["UTC", "Asia/Shanghai", "America/New_York"])
def test_validate_iana_time_zone_accepts_known_zones(value: str) -> None:
    assert validate_iana_time_zone(value) == value


@pytest.mark.parametrize("value", ["", " Mars/Olympus", "Mars/Olympus", "../UTC"])
def test_validate_iana_time_zone_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError, match="TIME_ZONE_INVALID"):
        validate_iana_time_zone(value)


def test_settings_reject_invalid_default_time_zone() -> None:
    with pytest.raises(ValueError, match="DEFAULT_HOUSEHOLD_TIME_ZONE_INVALID"):
        Settings(default_household_time_zone="Mars/Olympus")
