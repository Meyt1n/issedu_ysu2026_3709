"""HCT-103: add idempotency_key and compensates_event_id to health_event.

Revision ID: 0004_hct103_event_idempotency
Revises: 0003_hct102_auth_security
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_hct103_event_idempotency"
down_revision: str | None = "0003_hct102_auth_security"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("health_event") as batch_op:
        batch_op.add_column(
            sa.Column("idempotency_key", sa.String(128), nullable=True),
        )
        batch_op.add_column(
            sa.Column(
                "compensates_event_id",
                sa.String(36),
                sa.ForeignKey("health_event.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        batch_op.create_index(
            "ix_health_event_idempotency_key", ["idempotency_key"]
        )


def downgrade() -> None:
    with op.batch_alter_table("health_event") as batch_op:
        batch_op.drop_index("ix_health_event_idempotency_key")
        batch_op.drop_column("compensates_event_id")
        batch_op.drop_column("idempotency_key")
