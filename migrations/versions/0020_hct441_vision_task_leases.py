"""HCT-441: persist worker claims and recovery leases for vision tasks.

Revision ID: 0020_hct441_vision_task_leases
Revises: 0019_hct404_release_evidence
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_hct441_vision_task_leases"
down_revision: str | None = "0019_hct404_release_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "vision_task",
        sa.Column("lease_owner", sa.String(120), nullable=True),
    )
    op.add_column(
        "vision_task",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "vision_task",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_vision_task_lease_expires_at", "vision_task", ["lease_expires_at"])


def downgrade() -> None:
    op.drop_index("ix_vision_task_lease_expires_at", table_name="vision_task")
    op.drop_column("vision_task", "attempt_count")
    op.drop_column("vision_task", "lease_expires_at")
    op.drop_column("vision_task", "lease_owner")
