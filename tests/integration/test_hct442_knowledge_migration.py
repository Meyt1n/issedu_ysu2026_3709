"""HCT-442: historical retrieval text is redacted during migration."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.config import get_settings
from app.knowledge import query_audit_fingerprint

REPO_ROOT = Path(__file__).resolve().parents[2]
PREVIOUS_REVISION = "0021_hct425_face_credential_mysql_index"


def _config(database_url: str) -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_query_privacy_migration_redacts_history_and_downgrade_is_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'knowledge-privacy.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = _config(database_url)
    engine = create_engine(database_url)
    query = "成员最近的阿莫西林记录"
    expected_digest, expected_length = query_audit_fingerprint(query)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO retrieval_query "
                    "(id, query_text, actor_id, returned_count, top_chunk_ids) "
                    "VALUES ('legacy-query', :query, 'owner', 2, '[]')"
                ),
                {"query": query},
            )

        command.upgrade(config, "head")
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT query_text, query_digest, query_length "
                    "FROM retrieval_query WHERE id = 'legacy-query'"
                )
            ).one()
        assert row.query_text is None
        assert row.query_digest == expected_digest
        assert row.query_length == expected_length

        command.downgrade(config, PREVIOUS_REVISION)
        with engine.connect() as connection:
            downgraded = connection.execute(
                text("SELECT query_text FROM retrieval_query WHERE id = 'legacy-query'")
            ).scalar_one()
        assert downgraded == ""
    finally:
        engine.dispose()
        get_settings.cache_clear()
