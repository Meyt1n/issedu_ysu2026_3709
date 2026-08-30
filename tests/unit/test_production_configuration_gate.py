"""The API must fail closed for production until remaining demo gaps are closed."""

import pytest

from app.config import Settings


def test_production_configuration_blocks_dev_shortcuts_and_process_local_face() -> None:
    with pytest.raises(ValueError, match="ALLOW_DEV_ACTOR_HEADER"):
        Settings(
            app_env="production",
            allow_dev_actor_header=True,
            cursor_signing_key="prod-cursor-key",
            vision_adapter_signing_key="prod-vision-key",
            biometric_encryption_key="prod-biometric-key",
        )


def test_production_configuration_accepts_durable_face_challenges() -> None:
    """Face challenges are DB-backed (migration 0023): no face blocker remains."""
    settings = Settings(
        app_env="production",
        allow_dev_actor_header=False,
        cursor_signing_key="prod-cursor-key",
        vision_adapter_signing_key="prod-vision-key",
        biometric_encryption_key="prod-biometric-key",
    )
    assert settings.app_env == "production"


def test_development_configuration_defaults_to_formal_authentication() -> None:
    settings = Settings(app_env="development", _env_file=None)

    assert settings.allow_dev_actor_header is False
    assert settings.egress_default_deny is True
