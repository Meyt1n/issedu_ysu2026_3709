"""Add versioned authorizations and minimal access audit records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_hct102_auth_security"
down_revision: str | None = "0002_allow_pending_health_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "care_authorization",
        sa.Column("grantor_actor_id", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "care_authorization",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "care_authorization",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            "UPDATE care_authorization "
            "SET grantor_actor_id = ("
            "SELECT created_by FROM household "
            "WHERE household.id = care_authorization.household_id"
            ")"
        )
    )
    op.execute(
        sa.text(
            "UPDATE care_authorization "
            "SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP)"
        )
    )
    with op.batch_alter_table("care_authorization") as batch_op:
        batch_op.alter_column(
            "grantor_actor_id",
            existing_type=sa.String(length=120),
            nullable=False,
        )
        batch_op.alter_column(
            "version",
            existing_type=sa.Integer(),
            existing_server_default="1",
            server_default=None,
        )
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        )
        batch_op.create_index("ix_auth_grantor_actor_id", ["grantor_actor_id"])

    op.create_table(
        "access_audit",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("authorization_id", sa.String(length=36), nullable=True),
        sa.Column("actor_id", sa.String(length=120), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("data_field", sa.String(length=120), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column("before_version", sa.Integer(), nullable=True),
        sa.Column("after_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_household_time", "access_audit", ["household_id", "created_at"])
    op.create_index("ix_audit_authorization", "access_audit", ["authorization_id"])


def downgrade() -> None:
    connection = op.get_bind()
    audit_count = connection.execute(sa.text("SELECT COUNT(*) FROM access_audit")).scalar_one()
    if audit_count:
        raise RuntimeError("Cannot downgrade while authorization audit records must be retained.")

    op.drop_index("ix_audit_authorization", table_name="access_audit")
    op.drop_index("ix_audit_household_time", table_name="access_audit")
    op.drop_table("access_audit")
    with op.batch_alter_table("care_authorization") as batch_op:
        batch_op.drop_index("ix_auth_grantor_actor_id")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("version")
        batch_op.drop_column("grantor_actor_id")
