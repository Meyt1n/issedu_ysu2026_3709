"""HCT-405: household/member erasure tasks and tombstones.

Revision ID: 0011_hct405_erasure
Revises: 0010_hct405_review_wiring
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_hct405_erasure"
down_revision: str = "0010_hct405_review_wiring"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "household",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "member",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_household_deleted_at", "household", ["deleted_at"])
    op.create_index("ix_member_deleted_at", "member", ["deleted_at"])
    op.create_table(
        "erasure_task",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("member_id", sa.String(length=36), nullable=True),
        sa.Column("requested_by", sa.String(length=120), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("layers", sa.JSON(), nullable=False),
        sa.Column("scope", sa.JSON(), nullable=False),
        sa.Column("error_layers", sa.JSON(), nullable=False),
    )
    op.create_index("ix_erasure_task_household_id", "erasure_task", ["household_id"])
    op.create_index("ix_erasure_task_member_id", "erasure_task", ["member_id"])
    op.create_index("ix_erasure_task_requested_by", "erasure_task", ["requested_by"])


def downgrade() -> None:
    bind = op.get_bind()
    audit_row = bind.execute(sa.text("SELECT id FROM erasure_task LIMIT 1")).first()
    if audit_row is not None:
        raise RuntimeError("ERASURE_AUDIT_DATA_REQUIRE_FORWARD_FIX")

    op.drop_index("ix_erasure_task_requested_by", table_name="erasure_task")
    op.drop_index("ix_erasure_task_member_id", table_name="erasure_task")
    op.drop_index("ix_erasure_task_household_id", table_name="erasure_task")
    op.drop_table("erasure_task")
    op.drop_index("ix_member_deleted_at", table_name="member")
    op.drop_index("ix_household_deleted_at", table_name="household")
    op.drop_column("member", "deleted_at")
    op.drop_column("household", "deleted_at")
