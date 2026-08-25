"""Migration coverage for HCT-405 household erasure tombstones."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.config import get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
PREVIOUS_REVISION = "0010_hct405_review_wiring"
CURRENT_REVISION = "0020_hct425_face_credential_mysql_index"


def _config(database_url: str) -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _database_url(tmp_path: Path, name: str) -> str:
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def test_erasure_upgrade_adds_tombstones_and_task_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _database_url(tmp_path, "erasure-upgrade.db")
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = _config(database_url)
    engine = create_engine(database_url)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        schema = inspect(engine)
        assert "erasure_task" not in schema.get_table_names()
        assert "deleted_at" not in {column["name"] for column in schema.get_columns("household")}
        assert "deleted_at" not in {column["name"] for column in schema.get_columns("member")}

        command.upgrade(config, "head")
        schema = inspect(engine)
        assert "erasure_task" in schema.get_table_names()
        household_columns = {column["name"] for column in schema.get_columns("household")}
        member_columns = {column["name"] for column in schema.get_columns("member")}
        task_columns = {column["name"] for column in schema.get_columns("erasure_task")}
        assert "deleted_at" in household_columns
        assert "deleted_at" in member_columns
        assert {
            "id",
            "household_id",
            "member_id",
            "requested_by",
            "status",
            "layers",
            "scope",
            "error_layers",
        } <= task_columns
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert revision == CURRENT_REVISION
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_erasure_downgrade_refuses_to_discard_audit_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _database_url(tmp_path, "erasure-downgrade.db")
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = _config(database_url)
    engine = create_engine(database_url)
    try:
        command.upgrade(config, "head")
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO erasure_task (
                        id,
                        household_id,
                        requested_by,
                        status,
                        layers,
                        scope,
                        error_layers
                    )
                    VALUES (
                        'synthetic-erasure',
                        'synthetic-household',
                        'owner',
                        'completed',
                        '{}',
                        '{}',
                        '[]'
                    )
                    """
                )
            )

        with pytest.raises(RuntimeError, match="ERASURE_AUDIT_DATA_REQUIRE_FORWARD_FIX"):
            command.downgrade(config, PREVIOUS_REVISION)

        with engine.begin() as connection:
            connection.execute(text("DELETE FROM erasure_task WHERE id = 'synthetic-erasure'"))

        command.downgrade(config, PREVIOUS_REVISION)
        schema = inspect(engine)
        assert "erasure_task" not in schema.get_table_names()
        assert "deleted_at" not in {column["name"] for column in schema.get_columns("household")}
        assert "deleted_at" not in {column["name"] for column in schema.get_columns("member")}
    finally:
        engine.dispose()
        get_settings.cache_clear()
