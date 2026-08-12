"""Create the P0 foundation schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "household",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_household_created_by", "household", ["created_by"])

    op.create_table(
        "member",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="DEPENDENT"),
        sa.Column("actor_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_member_household_actor", "member", ["household_id", "actor_id"])
    op.create_index("ix_member_actor_id", "member", ["actor_id"])

    op.create_table(
        "care_authorization",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("member_id", sa.String(length=36), nullable=False),
        sa.Column("grantee_actor_id", sa.String(length=120), nullable=False),
        sa.Column("data_fields", sa.JSON(), nullable=False),
        sa.Column("actions", sa.JSON(), nullable=False),
        sa.Column("purpose", sa.String(length=200), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["member_id"], ["member.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_auth_household_member", "care_authorization", ["household_id", "member_id"])
    op.create_index("ix_auth_grantee_actor_id", "care_authorization", ["grantee_actor_id"])

    op.create_table(
        "health_event",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("member_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("confirmation_status", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("confirmed_by", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["member_id"], ["member.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_event_household_member_time",
        "health_event",
        ["household_id", "member_id", "created_at"],
    )

    op.create_table(
        "outbox_message",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("topic", sa.String(length=120), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("dispatched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["event_id"], ["health_event.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "member_state_projection",
        sa.Column("member_id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("last_event_id", sa.String(length=36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["member_id"], ["member.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("member_state_projection")
    op.drop_table("outbox_message")
    op.drop_index("ix_event_household_member_time", table_name="health_event")
    op.drop_table("health_event")
    op.drop_index("ix_auth_grantee_actor_id", table_name="care_authorization")
    op.drop_index("ix_auth_household_member", table_name="care_authorization")
    op.drop_table("care_authorization")
    op.drop_index("ix_member_actor_id", table_name="member")
    op.drop_index("ix_member_household_actor", table_name="member")
    op.drop_table("member")
    op.drop_index("ix_household_created_by", table_name="household")
    op.drop_table("household")
