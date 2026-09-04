"""Idempotent catch-up: sync the migration chain with merged ORM models.

Originally written when HCT-103/204/207/301/401 model changes had not
landed in the migration chain. The team chain (0005_hct103_event_recovery,
0006_hct207_review_task, 0007_hct204_vision_task, 0007_hct401_knowledge …)
later added the same columns and tables, so this revision now sits at the
end of the merged chain and only fills whatever is still missing: every
step checks for existence first (fresh databases built from the team chain
skip straight through; databases created by the original version of this
file keep their schema and merely record the new position).

Revision ID: 0012_sync_schema_with_models
Revises: 0011_hct405_erasure
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_sync_schema_with_models"
down_revision: str | None = "0011_hct405_erasure"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(connection: sa.Connection, table: str) -> set[str]:
    inspector = sa.inspect(connection)
    return {column["name"] for column in inspector.get_columns(table)}


def _index_names(connection: sa.Connection, table: str) -> set[str]:
    inspector = sa.inspect(connection)
    names = {index["name"] for index in inspector.get_indexes(table)}
    unique_constraints = {
        constraint["name"] for constraint in inspector.get_unique_constraints(table)
    }
    return names | unique_constraints


def _has_table(connection: sa.Connection, table: str) -> bool:
    return sa.inspect(connection).has_table(table)


def _backfill_health_event(connection: sa.Connection) -> None:
    connection.execute(
        sa.text("UPDATE health_event SET correlation_id = id WHERE correlation_id IS NULL")
    )
    connection.execute(
        sa.text("UPDATE health_event SET schema_version = 1 WHERE schema_version IS NULL")
    )
    connection.execute(
        sa.text("UPDATE health_event SET occurred_at = created_at WHERE occurred_at IS NULL")
    )

    # Portable per-member sequence backfill (MySQL cannot update a table it
    # selects from in a correlated subquery, so number the rows in Python).
    rows = connection.execute(
        sa.text(
            "SELECT id, household_id, member_id FROM health_event "
            "WHERE sequence_no IS NULL ORDER BY household_id, member_id, created_at, id"
        )
    ).all()
    counters: dict[tuple[str, str], int] = {}
    for event_id, household_id, member_id in rows:
        key = (household_id, member_id)
        counters[key] = counters.get(key, 0) + 1
        connection.execute(
            sa.text("UPDATE health_event SET sequence_no = :seq WHERE id = :id"),
            {"seq": counters[key], "id": event_id},
        )


def _sync_health_event(connection: sa.Connection) -> None:
    existing = _column_names(connection, "health_event")
    wanted = [
        sa.Column("sequence_no", sa.Integer(), nullable=True),
        sa.Column("request_fingerprint", sa.String(64), nullable=True),
        sa.Column("correlation_id", sa.String(120), nullable=True),
        sa.Column("causation_id", sa.String(36), nullable=True),
        sa.Column("supersedes_event_id", sa.String(36), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
    ]
    missing = [column for column in wanted if column.name not in existing]
    if missing:
        with op.batch_alter_table("health_event") as batch_op:
            for column in missing:
                batch_op.add_column(column)

        _backfill_health_event(connection)

        with op.batch_alter_table("health_event") as batch_op:
            batch_op.alter_column("sequence_no", existing_type=sa.Integer(), nullable=False)
            batch_op.alter_column(
                "correlation_id", existing_type=sa.String(120), nullable=False
            )
            batch_op.alter_column("schema_version", existing_type=sa.Integer(), nullable=False)
            batch_op.alter_column(
                "occurred_at", existing_type=sa.DateTime(timezone=True), nullable=False
            )

    indexes = _index_names(connection, "health_event")
    index_specs = [
        ("uq_event_household_member_sequence", ["household_id", "member_id", "sequence_no"], True),
        ("uq_event_household_idempotency", ["household_id", "idempotency_key"], True),
        ("uq_event_supersedes", ["supersedes_event_id"], True),
        ("ix_event_correlation", ["correlation_id"], False),
    ]
    to_create = [spec for spec in index_specs if spec[0] not in indexes]
    if to_create:
        with op.batch_alter_table("health_event") as batch_op:
            for name, columns, unique in to_create:
                batch_op.create_index(name, columns, unique=unique)


def _sync_projection(connection: sa.Connection) -> None:
    existing = _column_names(connection, "member_state_projection")
    wanted = [
        sa.Column("last_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state_hash", sa.String(64), nullable=True),
    ]
    missing = [column for column in wanted if column.name not in existing]
    if missing:
        with op.batch_alter_table("member_state_projection") as batch_op:
            for column in missing:
                batch_op.add_column(column)


def _sync_outbox(connection: sa.Connection) -> None:
    existing = _column_names(connection, "outbox_message")
    wanted = [
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ]
    missing = [column for column in wanted if column.name not in existing]
    if missing:
        with op.batch_alter_table("outbox_message") as batch_op:
            for column in missing:
                batch_op.add_column(column)

        connection.execute(
            sa.text(
                "UPDATE outbox_message SET available_at = created_at WHERE available_at IS NULL"
            )
        )
        connection.execute(
            sa.text("UPDATE outbox_message SET updated_at = created_at WHERE updated_at IS NULL")
        )
        connection.execute(
            sa.text(
                "UPDATE outbox_message SET status = 'DISPATCHED', dispatched_at = created_at "
                "WHERE dispatched = 1 AND status = 'PENDING'"
            )
        )
        with op.batch_alter_table("outbox_message") as batch_op:
            batch_op.alter_column(
                "available_at", existing_type=sa.DateTime(timezone=True), nullable=False
            )

    indexes = _index_names(connection, "outbox_message")
    index_specs = [
        ("uq_outbox_event", ["event_id"], True),
        ("ix_outbox_status_available", ["status", "available_at"], False),
    ]
    to_create = [spec for spec in index_specs if spec[0] not in indexes]
    if to_create:
        with op.batch_alter_table("outbox_message") as batch_op:
            for name, columns, unique in to_create:
                batch_op.create_index(name, columns, unique=unique)


def _create_projection_checkpoint(connection: sa.Connection) -> None:
    if _has_table(connection, "projection_checkpoint"):
        return
    op.create_table(
        "projection_checkpoint",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("member_id", sa.String(36), nullable=False),
        sa.Column("household_id", sa.String(36), nullable=False),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.Column("last_event_id", sa.String(36), nullable=True),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["member_id"], ["member.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "uq_checkpoint_member_sequence",
        "projection_checkpoint",
        ["member_id", "last_sequence"],
        unique=True,
    )


def _create_vision_task(connection: sa.Connection) -> None:
    if _has_table(connection, "vision_task"):
        return
    op.create_table(
        "vision_task",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("household_id", sa.String(36), nullable=False),
        sa.Column("member_id", sa.String(36), nullable=True),
        sa.Column("file_id", sa.String(120), nullable=False),
        sa.Column("task_type", sa.String(40), nullable=False, server_default="ocr"),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(512), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("input_digest", sa.String(64), nullable=True),
        sa.Column("preprocess_version", sa.String(64), nullable=True),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("model_threshold", sa.Float(), nullable=True),
        sa.Column("schema_version", sa.String(64), nullable=True),
        sa.Column("code_version", sa.String(64), nullable=True),
        sa.Column("data_version", sa.String(64), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_vision_task_household_id", "vision_task", ["household_id"])
    op.create_index("ix_vision_task_member_id", "vision_task", ["member_id"])
    op.create_index("ix_vision_task_file_id", "vision_task", ["file_id"])
    op.create_index("ix_vision_task_status", "vision_task", ["status"])
    op.create_index(
        "ix_vision_task_idempotency_key", "vision_task", ["idempotency_key"], unique=True
    )


def _create_review_task(connection: sa.Connection) -> None:
    if _has_table(connection, "review_task"):
        return
    op.create_table(
        "review_task",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("vision_task_id", sa.String(36), nullable=False),
        sa.Column("household_id", sa.String(36), nullable=False),
        sa.Column("member_id", sa.String(36), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING_REVIEW", "CONFIRMED", "CORRECTED", "SKIPPED", name="reviewstatus"
            ),
            nullable=False,
        ),
        sa.Column(
            "fusion_status",
            sa.Enum("MATCHED", "CONFLICT", "UNKNOWN", "LOW_QUALITY", name="fusionstatus"),
            nullable=True,
        ),
        sa.Column("candidates", sa.JSON(), nullable=False),
        sa.Column("selected_candidate", sa.JSON(), nullable=True),
        sa.Column("manual_payload", sa.JSON(), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("confirmed_by", sa.String(120), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("rule_version", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_review_task_vision_task_id", "review_task", ["vision_task_id"])
    op.create_index("ix_review_task_household_id", "review_task", ["household_id"])
    op.create_index("ix_review_task_member_id", "review_task", ["member_id"])
    op.create_index("ix_review_task_fusion_status", "review_task", ["fusion_status"])
    op.create_index(
        "ix_review_task_idempotency_key", "review_task", ["idempotency_key"], unique=True
    )


def _create_knowledge_tables(connection: sa.Connection) -> None:
    if not _has_table(connection, "knowledge_document"):
        op.create_table(
            "knowledge_document",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("source", sa.String(120), nullable=False),
            sa.Column("license", sa.String(60), nullable=False, server_default="internal"),
            sa.Column("version", sa.String(40), nullable=False, server_default="1.0"),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("permission_scope", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
            sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deleted_by", sa.String(120), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("full_text", sa.Text(), nullable=False),
            sa.Column("created_by", sa.String(120), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_knowledge_document_status", "knowledge_document", ["status"])

    if not _has_table(connection, "knowledge_chunk"):
        op.create_table(
            "knowledge_chunk",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("document_id", sa.String(36), nullable=False),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("locator", sa.String(200), nullable=True),
            sa.Column("term_vector", sa.JSON(), nullable=False),
        )
        op.create_index("ix_knowledge_chunk_document_id", "knowledge_chunk", ["document_id"])

    if not _has_table(connection, "knowledge_index"):
        op.create_table(
            "knowledge_index",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("version", sa.String(40), nullable=False, unique=True),
            sa.Column("document_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("checksum", sa.String(64), nullable=True),
            sa.Column("created_by", sa.String(120), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if not _has_table(connection, "retrieval_query"):
        op.create_table(
            "retrieval_query",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("query_text", sa.Text(), nullable=False),
            sa.Column("actor_id", sa.String(120), nullable=False),
            sa.Column("household_id", sa.String(36), nullable=True),
            sa.Column("member_id", sa.String(36), nullable=True),
            sa.Column("returned_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("top_chunk_ids", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )


def upgrade() -> None:
    connection = op.get_bind()
    _sync_health_event(connection)
    _sync_projection(connection)
    _sync_outbox(connection)
    _create_projection_checkpoint(connection)
    _create_vision_task(connection)
    _create_review_task(connection)
    _create_knowledge_tables(connection)


def downgrade() -> None:
    # Catch-up revision: schema pieces may pre-date this revision (created by
    # the team chain), so tearing them down here would destroy earlier
    # migrations' work. Downgrade is a recorded no-op.
    pass
