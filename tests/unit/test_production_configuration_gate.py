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


def test_production_configuration_blocks_process_local_face_challenges() -> None:
    with pytest.raises(ValueError, match="face login challenges are process-local"):
        Settings(
            app_env="production",
            allow_dev_actor_header=False,
            cursor_signing_key="prod-cursor-key",
            vision_adapter_signing_key="prod-vision-key",
            biometric_encryption_key="prod-biometric-key",
            allow_process_local_face_challenges_in_production=False,
        )


def test_production_configuration_allows_single_node_face_drill_when_opted_in() -> None:
    settings = Settings(
        app_env="production",
        allow_dev_actor_header=False,
        cursor_signing_key="prod-cursor-key",
        vision_adapter_signing_key="prod-vision-key",
        biometric_encryption_key="prod-biometric-key",
        allow_process_local_face_challenges_in_production=True,
    )
    assert settings.app_env == "production"


def test_development_configuration_keeps_local_demo_defaults() -> None:
    settings = Settings(app_env="development")

    assert settings.allow_dev_actor_header is True
    assert settings.egress_default_deny is True
