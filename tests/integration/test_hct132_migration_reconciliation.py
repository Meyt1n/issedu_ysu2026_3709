"""Regression tests for the migration branches restored by HCT-132."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app.config import get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
CURRENT_HEAD = "0020_hct441_vision_task_leases"
RESTORED_TABLES = {
    "projection_checkpoint",
    "review_task",
    "vision_task",
    "knowledge_document",
    "knowledge_chunk",
    "knowledge_index",
    "retrieval_query",
}
CURRENT_BRANCH_TABLES = {
    "correction_diff",
    "hard_sample",
    "training_consent",
    "export_manifest",
    "model_version_binding",
    "erasure_task",
}


def _alembic_config(database_url: str) -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_migration_graph_has_one_merged_head() -> None:
    script = ScriptDirectory.from_config(Config(str(REPO_ROOT / "alembic.ini")))

    assert script.get_heads() == [CURRENT_HEAD]


@pytest.mark.parametrize(
    "starting_revision",
    [
        "0008_hct403_tool_call",
        "0006_hct404_model_version_binding",
    ],
)
def test_existing_schema_branch_can_upgrade_to_merged_head(
    starting_revision: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / f"{starting_revision}.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = _alembic_config(database_url)
    engine = create_engine(database_url)

    try:
        command.upgrade(config, starting_revision)
        command.upgrade(config, "head")

        schema = inspect(engine)
        tables = set(schema.get_table_names())
        assert RESTORED_TABLES <= tables
        assert CURRENT_BRANCH_TABLES <= tables
        assert {
            "sequence_no",
            "request_fingerprint",
            "correlation_id",
            "supersedes_event_id",
            "schema_version",
            "occurred_at",
        } <= {column["name"] for column in schema.get_columns("health_event")}
        assert {
            "status",
            "attempts",
            "available_at",
            "locked_at",
            "dispatched_at",
            "last_error",
            "updated_at",
        } <= {column["name"] for column in schema.get_columns("outbox_message")}
        assert {
            "version",
            "fusion_context",
            "fusion_fingerprint",
            "transition_fingerprint",
        } <= {column["name"] for column in schema.get_columns("review_task")}
        assert any(
            index["name"] == "uq_review_vision_task" and index["unique"]
            for index in schema.get_indexes("review_task")
        )
        assert {
            "release_evidence_hash",
            "rollback_evidence_hash",
        } <= {column["name"] for column in schema.get_columns("model_version_binding")}

        with engine.connect() as connection:
            current_revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert current_revision == CURRENT_HEAD
    finally:
        engine.dispose()
        get_settings.cache_clear()
