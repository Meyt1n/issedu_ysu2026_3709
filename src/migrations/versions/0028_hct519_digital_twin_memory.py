"""HCT-519: durable model-extracted memory for the family digital twin."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028_hct519_digital_twin_memory"
down_revision: str | None = "0027_hct441_review_model_version_length"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "digital_twin_memory",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("member_id", sa.String(length=36), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("value", sa.String(length=500), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("source_kind", sa.String(length=24), nullable=False),
        sa.Column("source_session_id", sa.String(length=64), nullable=True),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column("evidence_excerpt", sa.String(length=600), nullable=False),
        sa.Column("term_vector", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("confirmed_by", sa.String(length=120), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["member_id"], ["member.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_digital_twin_memory_household_id",
        "digital_twin_memory",
        ["household_id"],
    )
    op.create_index(
        "ix_digital_twin_memory_member_id",
        "digital_twin_memory",
        ["member_id"],
    )
    op.create_index(
        "ix_digital_twin_memory_category",
        "digital_twin_memory",
        ["category"],
    )
    op.create_index(
        "ix_digital_twin_memory_source_session_id",
        "digital_twin_memory",
        ["source_session_id"],
    )
    op.create_index(
        "ix_digital_twin_memory_source_digest",
        "digital_twin_memory",
        ["source_digest"],
    )
    op.create_index(
        "ix_digital_twin_memory_status",
        "digital_twin_memory",
        ["status"],
    )
    op.create_index(
        "uq_digital_twin_memory_fact",
        "digital_twin_memory",
        ["household_id", "member_id", "category", "value"],
        unique=True,
    )
    op.create_index(
        "ix_digital_twin_memory_scope_status",
        "digital_twin_memory",
        ["household_id", "member_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_digital_twin_memory_scope_status", table_name="digital_twin_memory")
    op.drop_index("uq_digital_twin_memory_fact", table_name="digital_twin_memory")
    op.drop_index("ix_digital_twin_memory_status", table_name="digital_twin_memory")
    op.drop_index("ix_digital_twin_memory_source_digest", table_name="digital_twin_memory")
    op.drop_index("ix_digital_twin_memory_source_session_id", table_name="digital_twin_memory")
    op.drop_index("ix_digital_twin_memory_category", table_name="digital_twin_memory")
    op.drop_index("ix_digital_twin_memory_member_id", table_name="digital_twin_memory")
    op.drop_index("ix_digital_twin_memory_household_id", table_name="digital_twin_memory")
    op.drop_table("digital_twin_memory")
