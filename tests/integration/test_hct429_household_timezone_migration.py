"""HCT-429: the household time zone migration preserves existing families."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.config import get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
PREVIOUS_REVISION = "0016_hct424_face_credential_status_index"
SCHEMA_BASE_REVISION = "0010_hct405_review_wiring"
CURRENT_REVISION = "0019_hct404_release_evidence"


def _config(database_url: str) -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_timezone_migration_backfills_existing_households_and_downgrades(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'household-timezone.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = _config(database_url)
    engine = create_engine(database_url)
    try:
        # Start from the merged schema branch so the legacy household table exists.
        command.upgrade(config, SCHEMA_BASE_REVISION)
        command.upgrade(config, PREVIOUS_REVISION)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO household (id, name, created_by) "
                    "VALUES ('legacy-household', 'Legacy', 'owner')"
                )
            )

        command.upgrade(config, "head")
        schema = inspect(engine)
        columns = {column["name"]: column for column in schema.get_columns("household")}
        assert columns["time_zone"]["nullable"] is False
        with engine.connect() as connection:
            timezone = connection.execute(
                text("SELECT time_zone FROM household WHERE id = 'legacy-household'")
            ).scalar_one()
        assert timezone == "UTC"

        command.downgrade(config, PREVIOUS_REVISION)
        assert "time_zone" not in {
            column["name"] for column in inspect(engine).get_columns("household")
        }
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_timezone_migration_is_the_single_head() -> None:
    from alembic.script import ScriptDirectory

    config = Config(str(REPO_ROOT / "alembic.ini"))
    assert ScriptDirectory.from_config(config).get_heads() == [CURRENT_REVISION]
