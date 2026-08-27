"""Decision 3B (ADR-0007): open web-search egress mode SSRF guard tests.

``allowlist`` keeps the fixed-host posture; ``open`` allows HTTPS egress to
public hosts only.  These tests never open a network connection: DNS
resolution is monkeypatched.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.egress_guard import is_public_https_url, is_web_search_egress_allowed


class TestPublicHttpsUrl:
    def test_http_rejected(self) -> None:
        assert is_public_https_url("http://example.org/", resolve_dns=False) is False

    def test_localhost_rejected(self) -> None:
        assert is_public_https_url("https://localhost/x", resolve_dns=False) is False

    def test_loopback_literal_rejected(self) -> None:
        assert is_public_https_url("https://127.0.0.1/", resolve_dns=False) is False

    def test_private_literal_rejected(self) -> None:
        assert is_public_https_url("https://192.168.1.10/", resolve_dns=False) is False
        assert is_public_https_url("https://10.0.0.8/", resolve_dns=False) is False

    def test_link_local_metadata_rejected(self) -> None:
        assert is_public_https_url("https://169.254.169.254/", resolve_dns=False) is False
        assert is_public_https_url(
            "https://metadata.google.internal/", resolve_dns=False
        ) is False

    def test_internal_suffixes_rejected(self) -> None:
        assert is_public_https_url("https://nas.lan/", resolve_dns=False) is False
        assert is_public_https_url("https://db.internal/", resolve_dns=False) is False
        assert is_public_https_url("https://printer.local/", resolve_dns=False) is False

    def test_public_ip_literal_allowed(self) -> None:
        assert is_public_https_url("https://93.184.216.34/", resolve_dns=False) is True

    def test_hostname_resolving_private_rejected(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "app.egress_guard._resolved_addresses", lambda host: ("192.168.0.5",)
        )
        assert is_public_https_url("https://sneaky.example.com/") is False

    def test_hostname_resolving_public_allowed(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "app.egress_guard._resolved_addresses", lambda host: ("93.184.216.34",)
        )
        assert is_public_https_url("https://www.example.org/") is True

    def test_unresolvable_hostname_rejected(self, monkeypatch) -> None:
        monkeypatch.setattr("app.egress_guard._resolved_addresses", lambda host: ())
        assert is_public_https_url("https://does-not-resolve.example/") is False


class TestOpenEgressMode:
    def _settings(self, mode: str) -> Settings:
        return Settings(
            agent_web_search_enabled=True,
            agent_web_search_egress_mode=mode,
            agent_web_search_url="https://html.duckduckgo.com/html/",
            agent_web_search_allowed_domains="html.duckduckgo.com",
        )

    def test_allowlist_mode_blocks_off_list_hosts(self) -> None:
        settings = self._settings("allowlist")
        assert is_web_search_egress_allowed(
            "https://html.duckduckgo.com/html/", settings
        ) is True
        assert is_web_search_egress_allowed("https://www.example.org/", settings) is False

    def test_open_mode_allows_public_https_only(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "app.egress_guard._resolved_addresses", lambda host: ("93.184.216.34",)
        )
        settings = self._settings("open")
        assert is_web_search_egress_allowed("https://www.example.org/", settings) is True
        assert is_web_search_egress_allowed("http://www.example.org/", settings) is False
        assert is_web_search_egress_allowed("https://192.168.1.4/", settings) is False

    def test_invalid_mode_rejected_by_config(self) -> None:
        with pytest.raises(ValueError):
            Settings(agent_web_search_egress_mode="wide-open")

    _PRODUCTION_BASE = {
        "app_env": "production",
        "allow_dev_actor_header": False,
        "cursor_signing_key": "prod-cursor-key",
        "vision_adapter_signing_key": "prod-vision-key",
        "biometric_encryption_key": "prod-biometric-key",
    }

    def test_open_mode_needs_no_domain_allowlist_in_production(self) -> None:
        settings = Settings(
            **self._PRODUCTION_BASE,
            agent_web_search_enabled=True,
            agent_web_search_egress_mode="open",
            agent_web_search_allowed_domains="",
        )
        assert settings.agent_web_search_egress_mode == "open"

    def test_allowlist_mode_still_requires_domains_in_production(self) -> None:
        with pytest.raises(ValueError, match="AGENT_WEB_SEARCH_ALLOWED_DOMAINS"):
            Settings(
                **self._PRODUCTION_BASE,
                agent_web_search_enabled=True,
                agent_web_search_egress_mode="allowlist",
                agent_web_search_allowed_domains="",
            )

    def test_open_chat_allowed_in_production_after_8c(self) -> None:
        """8C: AGENT_OPEN_CHAT no longer bypasses safety, so the production
        gate no longer blocks it."""
        settings = Settings(
            **self._PRODUCTION_BASE,
            agent_open_chat=True,
        )
        assert settings.agent_open_chat is True
