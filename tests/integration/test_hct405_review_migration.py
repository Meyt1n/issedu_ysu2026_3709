"""Migration coverage for HCT-405 vision-review wiring."""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.review import (
    FusionStatus,
    ReviewStatus,
    ReviewTask,
    confirm_review,
    create_review_task,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PREVIOUS_REVISION = "0009_merge_backend_heads"


def _config(database_url: str) -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _database_url(tmp_path: Path, name: str) -> str:
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def _insert_review(connection, *, task_id: str, vision_task_id: str) -> None:
    connection.execute(
        text(
            """
            INSERT INTO review_task (
                id,
                vision_task_id,
                household_id,
                member_id,
                status,
                fusion_status,
                candidates
            )
            VALUES (
                :id,
                :vision_task_id,
                'synthetic-household',
                'synthetic-member',
                'PENDING_REVIEW',
                'MATCHED',
                '[]'
            )
            """
        ),
        {"id": task_id, "vision_task_id": vision_task_id},
    )


def _insert_misaligned_vision_task(connection) -> None:
    connection.execute(
        text(
            """
            INSERT INTO household (id, name, created_by)
            VALUES
                ('actual-household', 'Actual household', 'owner'),
                ('legacy-system', 'Legacy system', 'owner')
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO `member` (id, household_id, display_name, role)
            VALUES ('actual-member', 'actual-household', 'Synthetic member', 'SELF')
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO vision_task (
                id,
                household_id,
                member_id,
                file_id,
                task_type,
                status,
                created_by
            )
            VALUES
                (
                    'legacy-vision',
                    'legacy-system',
                    'actual-member',
                    'synthetic-file',
                    'ocr',
                    'queued',
                    'owner'
                ),
                (
                    'unscoped-vision',
                    'legacy-system',
                    NULL,
                    'unscoped-file',
                    'ocr',
                    'running',
                    'owner'
                )
            """
        )
    )


def test_existing_review_receives_version_and_unique_vision_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _database_url(tmp_path, "existing-review.db")
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = _config(database_url)
    engine = create_engine(database_url)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        with engine.begin() as connection:
            _insert_misaligned_vision_task(connection)
            _insert_review(
                connection,
                task_id="existing-review",
                vision_task_id="existing-vision",
            )

        command.upgrade(config, "head")

        schema = inspect(engine)
        review_columns = {
            column["name"] for column in schema.get_columns("review_task")
        }
        assert {
            "version",
            "fusion_context",
            "fusion_fingerprint",
            "transition_fingerprint",
        }.issubset(review_columns)
        assert any(
            index["name"] == "uq_review_vision_task" and index["unique"]
            for index in schema.get_indexes("review_task")
        )
        with engine.connect() as connection:
            version = connection.execute(
                text("SELECT version FROM review_task WHERE id = 'existing-review'")
            ).scalar_one()
            repaired_household = connection.execute(
                text(
                    "SELECT household_id FROM vision_task WHERE id = 'legacy-vision'"
                )
            ).scalar_one()
            unscoped_status = connection.execute(
                text(
                    """
                    SELECT status, error_code
                    FROM vision_task
                    WHERE id = 'unscoped-vision'
                    """
                )
            ).one()
        assert version == 1
        assert repaired_household == "actual-household"
        assert unscoped_status == ("cancelled", "MEMBER_SCOPE_INVALID")
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_duplicate_reviews_block_upgrade_for_manual_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _database_url(tmp_path, "duplicate-review.db")
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = _config(database_url)
    engine = create_engine(database_url)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        with engine.begin() as connection:
            _insert_review(
                connection,
                task_id="duplicate-review-a",
                vision_task_id="duplicate-vision",
            )
            _insert_review(
                connection,
                task_id="duplicate-review-b",
                vision_task_id="duplicate-vision",
            )

        with pytest.raises(
            RuntimeError,
            match="DUPLICATE_REVIEW_TASKS_REQUIRE_RECONCILIATION",
        ):
            command.upgrade(config, "head")
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_review_audit_data_blocks_destructive_downgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _database_url(tmp_path, "review-audit-downgrade.db")
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = _config(database_url)
    engine = create_engine(database_url)
    try:
        command.upgrade(config, "head")
        with engine.begin() as connection:
            _insert_review(
                connection,
                task_id="audited-review",
                vision_task_id="audited-vision",
            )
            connection.execute(
                text(
                    """
                    UPDATE review_task
                    SET fusion_context = '{}',
                        fusion_fingerprint = :fingerprint
                    WHERE id = 'audited-review'
                    """
                ),
                {"fingerprint": "a" * 64},
            )

        with pytest.raises(
            RuntimeError,
            match="REVIEW_AUDIT_DATA_REQUIRE_FORWARD_FIX",
        ):
            command.downgrade(config, PREVIOUS_REVISION)
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_review_wiring_can_downgrade_when_no_review_status_rows_exist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _database_url(tmp_path, "review-downgrade.db")
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = _config(database_url)
    engine = create_engine(database_url)
    try:
        command.upgrade(config, "head")
        command.downgrade(config, PREVIOUS_REVISION)

        schema = inspect(engine)
        review_columns = {
            column["name"] for column in schema.get_columns("review_task")
        }
        assert {
            "version",
            "fusion_context",
            "fusion_fingerprint",
            "transition_fingerprint",
        }.isdisjoint(review_columns)
        assert all(
            index["name"] != "uq_review_vision_task"
            for index in schema.get_indexes("review_task")
        )
    finally:
        engine.dispose()
        get_settings.cache_clear()


@pytest.mark.skipif(
    not os.getenv("HCT405_MYSQL_TEST_URL"),
    reason="HCT405_MYSQL_TEST_URL is required for MySQL migration coverage",
)
def test_review_wiring_upgrade_and_downgrade_on_mysql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.environ["HCT405_MYSQL_TEST_URL"]
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = _config(database_url)
    engine = create_engine(database_url)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        with engine.begin() as connection:
            _insert_misaligned_vision_task(connection)
            _insert_review(
                connection,
                task_id="existing-review",
                vision_task_id="existing-vision",
            )

        command.upgrade(config, "head")

        schema = inspect(engine)
        review_columns = {
            column["name"] for column in schema.get_columns("review_task")
        }
        assert {
            "version",
            "fusion_context",
            "fusion_fingerprint",
            "transition_fingerprint",
        }.issubset(review_columns)
        fusion_type = next(
            column["type"]
            for column in schema.get_columns("review_task")
            if column["name"] == "fusion_status"
        )
        assert "REVIEW" in fusion_type.enums
        assert any(
            index["name"] == "uq_review_vision_task" and index["unique"]
            for index in schema.get_indexes("review_task")
        )

        session_factory = sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        )
        with session_factory() as setup_session:
            same_key_review = create_review_task(
                setup_session,
                vision_task_id="same-key-vision",
                household_id="actual-household",
                member_id="actual-member",
                candidates=[{"drug_name": "candidate"}],
                fusion_status=FusionStatus.MATCHED,
            )
            setup_session.commit()
            same_key_review_id = same_key_review.id
        with session_factory() as first_session, session_factory() as stale_session:
            first_task = first_session.get(ReviewTask, same_key_review_id)
            stale_task = stale_session.get(ReviewTask, same_key_review_id)
            assert first_task is not None
            assert stale_task is not None
            confirm_review(
                first_session,
                first_task,
                actor_id="mysql-reviewer",
                selected_candidate={"drug_name": "candidate"},
                idempotency_key="mysql-same-key",
                expected_version=1,
            )
            first_session.commit()

            retried, _ = confirm_review(
                stale_session,
                stale_task,
                actor_id="mysql-reviewer",
                selected_candidate={"drug_name": "candidate"},
                idempotency_key="mysql-same-key",
                expected_version=1,
            )
            assert retried.status == ReviewStatus.CONFIRMED
            assert retried.version == 2

        with pytest.raises(
            RuntimeError,
            match="REVIEW_AUDIT_DATA_REQUIRE_FORWARD_FIX",
        ):
            command.downgrade(config, PREVIOUS_REVISION)

        with engine.begin() as connection:
            assert connection.execute(
                text(
                    "SELECT household_id FROM vision_task WHERE id = 'legacy-vision'"
                )
            ).scalar_one() == "actual-household"
            assert connection.execute(
                text("SELECT status FROM vision_task WHERE id = 'unscoped-vision'")
            ).scalar_one() == "cancelled"
            connection.execute(
                text("DELETE FROM review_task WHERE id = :task_id"),
                {"task_id": same_key_review_id},
            )
            connection.execute(
                text(
                    """
                    UPDATE review_task
                    SET fusion_status = 'REVIEW'
                    WHERE id = 'existing-review'
                    """
                )
            )

        with pytest.raises(
            RuntimeError,
            match="REVIEW_STATUS_ROWS_REQUIRE_FORWARD_FIX",
        ):
            command.downgrade(config, PREVIOUS_REVISION)

        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE review_task
                    SET fusion_status = 'MATCHED'
                    WHERE id = 'existing-review'
                    """
                )
            )
        command.downgrade(config, PREVIOUS_REVISION)

        downgraded_type = next(
            column["type"]
            for column in inspect(engine).get_columns("review_task")
            if column["name"] == "fusion_status"
        )
        assert "REVIEW" not in downgraded_type.enums
        command.downgrade(config, "base")
    finally:
        engine.dispose()
        get_settings.cache_clear()
