"""HCT-497: persist privacy-preserving visual quality provenance."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_hct497_vision_quality_records"
down_revision: str | None = "0024_hct462_risk_disposition"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vision_quality_record",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(120), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("media_type", sa.String(16), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("config_version", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("allow_downstream", sa.Boolean(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("thresholds", sa.JSON(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("retake_prompts", sa.JSON(), nullable=False),
        sa.Column("frames", sa.JSON(), nullable=False),
        sa.Column("receipt_digest", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vision_quality_record_actor_id", "vision_quality_record", ["actor_id"])
    op.create_index(
        "ix_vision_quality_record_input_digest", "vision_quality_record", ["input_digest"]
    )
    op.create_index(
        "ix_vision_quality_record_media_type", "vision_quality_record", ["media_type"]
    )
    op.create_index(
        "ix_vision_quality_record_decision", "vision_quality_record", ["decision"]
    )
    op.create_index(
        "ix_vision_quality_record_created_at", "vision_quality_record", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_vision_quality_record_created_at", table_name="vision_quality_record")
    op.drop_index("ix_vision_quality_record_decision", table_name="vision_quality_record")
    op.drop_index("ix_vision_quality_record_media_type", table_name="vision_quality_record")
    op.drop_index(
        "ix_vision_quality_record_input_digest", table_name="vision_quality_record"
    )
    op.drop_index("ix_vision_quality_record_actor_id", table_name="vision_quality_record")
    op.drop_table("vision_quality_record")
