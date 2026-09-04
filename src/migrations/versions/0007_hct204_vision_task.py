"""HCT-204: vision_task table for asynchronous OCR / barcode processing."""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0007_hct204_vision_task"
down_revision = "0006_hct207_review_task"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vision_task",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("household_id", sa.String(36), nullable=False, index=True),
        sa.Column("member_id", sa.String(36), nullable=True, index=True),
        sa.Column("file_id", sa.String(120), nullable=False, index=True),
        sa.Column("task_type", sa.String(40), nullable=False, default="ocr"),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            default="queued",
            index=True,
        ),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(512), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True, unique=True, index=True),
        sa.Column("input_digest", sa.String(64), nullable=True),
        sa.Column("preprocess_version", sa.String(64), nullable=True),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("model_threshold", sa.Float, nullable=True),
        sa.Column("schema_version", sa.String(64), nullable=True),
        sa.Column("code_version", sa.String(64), nullable=True),
        sa.Column("data_version", sa.String(64), nullable=True),
        sa.Column("result", sa.JSON, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    sa.Index("ix_vision_household", "vision_task", "household_id", "created_at")


def downgrade() -> None:
    op.drop_table("vision_task")
