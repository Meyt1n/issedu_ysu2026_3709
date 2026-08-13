"""Sync the migration chain with merged ORM models.

HCT-103/204/207/301/401 merged event replay metadata, projection
versioning, durable outbox fields and the projection_checkpoint /
vision_task / review_task / knowledge_* tables into the ORM and API, but
the columns and tables never landed in the migration chain. A clean
`alembic upgrade head` database therefore broke every event endpoint
(`no such column: health_event.sequence_no`) and the whole knowledge
store (`no such table: knowledge_document`). This revision backfills
existing rows and creates the missing tables so migrated databases match
the models used by tests (`Base.metadata.create_all`).

Revision ID: 0007_sync_schema_with_models
Revises: 0006_hct404_model_version_binding
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_sync_schema_with_models"
down_revision: str | None = "0006_hct404_model_version_binding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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


def upgrade() -> None:
    connection = op.get_bind()

    # ── health_event: replay & idempotency metadata (HCT-103) ─────────
    with op.batch_alter_table("health_event") as batch_op:
        batch_op.add_column(sa.Column("sequence_no", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("request_fingerprint", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("correlation_id", sa.String(120), nullable=True))
        batch_op.add_column(sa.Column("causation_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("supersedes_event_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("schema_version", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True))

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
        batch_op.create_index(
            "uq_event_household_member_sequence",
            ["household_id", "member_id", "sequence_no"],
            unique=True,
        )
        batch_op.create_index(
            "uq_event_household_idempotency",
            ["household_id", "idempotency_key"],
            unique=True,
        )
        batch_op.create_index("uq_event_supersedes", ["supersedes_event_id"], unique=True)
        batch_op.create_index("ix_event_correlation", ["correlation_id"])

    # ── member_state_projection: versioned projection (HCT-301) ───────
    with op.batch_alter_table("member_state_projection") as batch_op:
        batch_op.add_column(
            sa.Column("last_sequence", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("version", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("state_hash", sa.String(64), nullable=True))

    # ── outbox_message: durable dispatch state ─────────────────────────
    with op.batch_alter_table("outbox_message") as batch_op:
        batch_op.add_column(
            sa.Column("status", sa.String(16), nullable=False, server_default="PENDING")
        )
        batch_op.add_column(
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("available_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("last_error", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    connection.execute(
        sa.text("UPDATE outbox_message SET available_at = created_at WHERE available_at IS NULL")
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
        batch_op.create_index("uq_outbox_event", ["event_id"], unique=True)
        batch_op.create_index("ix_outbox_status_available", ["status", "available_at"])

    # ── projection_checkpoint (HCT-103 replay) ─────────────────────────
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

    # ── vision_task (HCT-204) ──────────────────────────────────────────
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

    # ── review_task (HCT-207) ──────────────────────────────────────────
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

    # ── knowledge store (HCT-401) ──────────────────────────────────────
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


def downgrade() -> None:
    op.drop_table("retrieval_query")
    op.drop_table("knowledge_index")
    op.drop_index("ix_knowledge_chunk_document_id", table_name="knowledge_chunk")
    op.drop_table("knowledge_chunk")
    op.drop_index("ix_knowledge_document_status", table_name="knowledge_document")
    op.drop_table("knowledge_document")

    op.drop_index("ix_review_task_idempotency_key", table_name="review_task")
    op.drop_index("ix_review_task_fusion_status", table_name="review_task")
    op.drop_index("ix_review_task_member_id", table_name="review_task")
    op.drop_index("ix_review_task_household_id", table_name="review_task")
    op.drop_index("ix_review_task_vision_task_id", table_name="review_task")
    op.drop_table("review_task")

    op.drop_index("ix_vision_task_idempotency_key", table_name="vision_task")
    op.drop_index("ix_vision_task_status", table_name="vision_task")
    op.drop_index("ix_vision_task_file_id", table_name="vision_task")
    op.drop_index("ix_vision_task_member_id", table_name="vision_task")
    op.drop_index("ix_vision_task_household_id", table_name="vision_task")
    op.drop_table("vision_task")

    op.drop_index("uq_checkpoint_member_sequence", table_name="projection_checkpoint")
    op.drop_table("projection_checkpoint")

    with op.batch_alter_table("outbox_message") as batch_op:
        batch_op.drop_index("ix_outbox_status_available")
        batch_op.drop_index("uq_outbox_event")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("last_error")
        batch_op.drop_column("dispatched_at")
        batch_op.drop_column("locked_at")
        batch_op.drop_column("available_at")
        batch_op.drop_column("attempts")
        batch_op.drop_column("status")

    with op.batch_alter_table("member_state_projection") as batch_op:
        batch_op.drop_column("state_hash")
        batch_op.drop_column("version")
        batch_op.drop_column("last_sequence")

    with op.batch_alter_table("health_event") as batch_op:
        batch_op.drop_index("ix_event_correlation")
        batch_op.drop_index("uq_event_supersedes")
        batch_op.drop_index("uq_event_household_idempotency")
        batch_op.drop_index("uq_event_household_member_sequence")
        batch_op.drop_column("occurred_at")
        batch_op.drop_column("schema_version")
        batch_op.drop_column("supersedes_event_id")
        batch_op.drop_column("causation_id")
        batch_op.drop_column("correlation_id")
        batch_op.drop_column("request_fingerprint")
        batch_op.drop_column("sequence_no")
