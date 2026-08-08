"""HCT-103: add idempotency_key and compensates_event_id to health_event.

Revision ID: 0004_hct103_event_idempotency
Revises: 0003_hct102_authorization_security
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_hct103_event_idempotency"
down_revision: str | None = "0003_hct102_authorization_security"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "health_event",
        sa.Column("idempotency_key", sa.String(128), nullable=True),
    )
    op.add_column(
        "health_event",
        sa.Column(
            "compensates_event_id",
            sa.String(36),
            sa.ForeignKey("health_event.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_unique_constraint(
        "uq_health_event_idempotency_key", "health_event", ["idempotency_key"]
    )
    op.create_index(
        "ix_health_event_idempotency_key", "health_event", ["idempotency_key"]
    )


def downgrade() -> None:
    op.drop_index("ix_health_event_idempotency_key", table_name="health_event")
    op.drop_constraint("uq_health_event_idempotency_key", table_name="health_event")
    op.drop_column("health_event", "compensates_event_id")
    op.drop_column("health_event", "idempotency_key")
