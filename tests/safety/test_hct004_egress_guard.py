"""
Tests for HCT-004 egress guard — default-deny network egress.
"""

from app.egress_guard import (
    FORBIDDEN_EGRESS_FIELDS,
    allowed_weather_payload,
    is_egress_allowed,
    validate_egress_payload,
)


class TestEgressGuardWhitelist:
    def test_empty_whitelist_denies_all(self, monkeypatch):
        """Default-deny: empty whitelist blocks everything."""
        from app.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "egress_default_deny", True)
        monkeypatch.setattr(settings, "egress_weather_whitelist", "")

        assert is_egress_allowed("https://weather.example.com/api") is False
        assert is_egress_allowed("https://any-other-service.com") is False

    def test_whitelisted_host_allowed(self, monkeypatch):
        """Host in whitelist is allowed."""
        from app.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "egress_default_deny", True)
        monkeypatch.setattr(settings, "egress_weather_whitelist", "weather.example.com")

        assert is_egress_allowed("https://weather.example.com/api/v1") is True

    def test_plain_http_is_rejected_even_for_whitelisted_host(self, monkeypatch):
        """Weather egress requires TLS even when the host is allowlisted."""
        from app.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "egress_default_deny", True)
        monkeypatch.setattr(settings, "egress_weather_whitelist", "weather.example.com")

        assert is_egress_allowed("http://weather.example.com/api/v1") is False

    def test_non_whitelisted_host_blocked(self, monkeypatch):
        """Host NOT in whitelist is blocked."""
        from app.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "egress_default_deny", True)
        monkeypatch.setattr(settings, "egress_weather_whitelist", "weather.example.com")

        assert is_egress_allowed("https://evil.example.com") is False

    def test_whitelist_with_port(self, monkeypatch):
        """Whitelist entry with explicit port is matched exactly."""
        from app.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "egress_default_deny", True)
        monkeypatch.setattr(settings, "egress_weather_whitelist", "api.weather.com:8443")

        assert is_egress_allowed("https://api.weather.com:8443/data") is True
        assert is_egress_allowed("https://api.weather.com:443/data") is False

    def test_disabled_default_deny_allows_all(self, monkeypatch):
        """When egress_default_deny is False, all traffic is allowed."""
        from app.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "egress_default_deny", False)
        monkeypatch.setattr(settings, "egress_weather_whitelist", "")

        assert is_egress_allowed("https://anything.example.com") is True

    def test_multiple_whitelist_entries(self, monkeypatch):
        """Multiple comma-separated whitelist entries."""
        from app.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "egress_default_deny", True)
        monkeypatch.setattr(
            settings, "egress_weather_whitelist", "weather1.example.com,weather2.example.com:8080"
        )

        assert is_egress_allowed("https://weather1.example.com/api") is True
        assert is_egress_allowed("https://weather2.example.com:8080/api") is True
        assert is_egress_allowed("https://weather3.example.com/api") is False


class TestValidateEgressPayload:
    def test_empty_payload_allowed(self):
        ok, reason = validate_egress_payload(None)
        assert ok is True
        assert reason is None

    def test_safe_payload_allowed(self):
        ok, reason = validate_egress_payload({"city_code": "110000"})
        assert ok is True
        assert reason is None

    def test_member_id_blocked(self):
        ok, reason = validate_egress_payload({"city_code": "110000", "member_id": "abc-123"})
        assert ok is False
        assert "member_id" in reason

    def test_health_event_blocked(self):
        ok, reason = validate_egress_payload({"health_event": {"drug": "aspirin"}})
        assert ok is False

    def test_nested_forbidden_field_blocked(self):
        ok, reason = validate_egress_payload(
            {"request": {"params": {"diagnosis": "hypertension"}}}
        )
        assert ok is False
        assert "diagnosis" in reason

    def test_all_forbidden_fields_known(self):
        """Ensure FORBIDDEN_EGRESS_FIELDS covers the required categories."""
        required = {
            "member_id", "drug", "disease", "allergy", "report",
            "image", "video", "vector", "conversation", "payload", "evidence",
        }
        missing = required - FORBIDDEN_EGRESS_FIELDS
        assert not missing, f"Missing forbidden fields: {missing}"


class TestWeatherPayload:
    def test_only_coarse_location_codes_allowed(self):
        ok, reason = allowed_weather_payload({"city_code": "110000", "district_code": "110108"})
        assert ok is True

    def test_precise_coordinates_rejected(self):
        ok, reason = allowed_weather_payload({"city_code": "110000", "lat": 39.9, "lon": 116.4})
        assert ok is False
        assert "lat" in reason

    def test_health_field_in_weather_rejected(self):
        ok, reason = allowed_weather_payload({"city_code": "110000", "allergy": "penicillin"})
        assert ok is False

    def test_unknown_key_rejected(self):
        ok, reason = allowed_weather_payload({"city_code": "110000", "user_id": "xyz"})
        assert ok is False
        assert "user_id" in reason
