"""HCT-413: persist minimal risk acknowledgement receipts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_hct413_risk_acknowledgement"
down_revision: str | None = "0012_sync_schema_with_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("access_audit") as batch_op:
        batch_op.add_column(sa.Column("request_id", sa.String(120), nullable=True))
        batch_op.create_index("ix_audit_request_id", ["request_id"], unique=False)

    op.create_table(
        "risk_acknowledgement",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("household_id", sa.String(36), nullable=False),
        sa.Column("member_id", sa.String(36), nullable=False),
        sa.Column("rule_id", sa.String(80), nullable=False),
        sa.Column("rule_version", sa.String(64), nullable=False),
        sa.Column("risk_fingerprint", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(120), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["member_id"], ["member.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_risk_ack_household_idempotency",
        "risk_acknowledgement",
        ["household_id", "idempotency_key"],
        unique=True,
    )
    op.create_index(
        "uq_risk_ack_current_signal",
        "risk_acknowledgement",
        ["household_id", "member_id", "rule_id", "risk_fingerprint"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_risk_ack_current_signal", table_name="risk_acknowledgement")
    op.drop_index("uq_risk_ack_household_idempotency", table_name="risk_acknowledgement")
    op.drop_table("risk_acknowledgement")
    with op.batch_alter_table("access_audit") as batch_op:
        batch_op.drop_index("ix_audit_request_id")
        batch_op.drop_column("request_id")
