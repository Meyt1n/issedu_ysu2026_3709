"""HCT-462: auditable risk handling actions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_hct462_risk_disposition"
down_revision: str | None = "0023_hct425_face_challenge_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "risk_disposition",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("household_id", sa.String(36), nullable=False),
        sa.Column("member_id", sa.String(36), nullable=False),
        sa.Column("rule_id", sa.String(80), nullable=False),
        sa.Column("rule_version", sa.String(64), nullable=False),
        sa.Column("risk_fingerprint", sa.String(64), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("target_actor_id", sa.String(120), nullable=True),
        sa.Column("snooze_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_id", sa.String(120), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
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
        "uq_risk_disposition_household_idempotency",
        "risk_disposition",
        ["household_id", "idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_risk_disposition_signal_created",
        "risk_disposition",
        ["household_id", "member_id", "rule_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_risk_disposition_signal_created", table_name="risk_disposition")
    op.drop_index(
        "uq_risk_disposition_household_idempotency", table_name="risk_disposition"
    )
    op.drop_table("risk_disposition")
