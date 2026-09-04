"""HCT-207: review_task table for manual review workflow."""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0006_hct207_review_task"
down_revision = "0005_hct103_event_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_task",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("vision_task_id", sa.String(36), nullable=False, index=True),
        sa.Column("household_id", sa.String(36), nullable=False, index=True),
        sa.Column("member_id", sa.String(36), nullable=False, index=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING_REVIEW", "CONFIRMED", "CORRECTED", "SKIPPED", name="review_status"
            ),
            nullable=False,
            default="PENDING_REVIEW",
        ),
        sa.Column(
            "fusion_status",
            sa.Enum(
                "MATCHED", "CONFLICT", "UNKNOWN", "LOW_QUALITY", name="fusion_status"
            ),
            nullable=True,
            index=True,
        ),
        sa.Column("candidates", sa.JSON, nullable=False, default=list),
        sa.Column("selected_candidate", sa.JSON, nullable=True),
        sa.Column("manual_payload", sa.JSON, nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True, index=True, unique=True),
        sa.Column("confirmed_by", sa.String(120), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("rule_version", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    sa.Index(
        "ix_review_vision", "review_task", "vision_task_id"
    )
    sa.Index(
        "ix_review_household_member", "review_task", "household_id", "member_id"
    )


def downgrade() -> None:
    op.drop_table("review_task")
