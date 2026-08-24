"""The API must not advertise the in-memory demo auth as production-ready."""

import pytest

from app.config import Settings


def test_production_configuration_is_blocked_until_persistent_sessions_exist() -> None:
    with pytest.raises(ValueError, match="database-backed session persistence"):
        Settings(app_env="production")


def test_development_configuration_keeps_local_demo_defaults() -> None:
    settings = Settings(app_env="development")

    assert settings.allow_dev_actor_header is True
    assert settings.egress_default_deny is True
