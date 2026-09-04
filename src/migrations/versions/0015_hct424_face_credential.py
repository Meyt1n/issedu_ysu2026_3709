"""HCT-424: encrypted household face credentials."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_hct424_face_credential"
down_revision: str | None = "0014_hct414_vision_media_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "face_credential",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("actor_id", sa.String(length=120), nullable=False),
        sa.Column("encrypted_template", sa.LargeBinary(), nullable=False),
        sa.Column("algorithm_version", sa.String(length=64), nullable=False),
        sa.Column("feature_version", sa.String(length=64), nullable=False),
        sa.Column("credential_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("consent_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ACTIVE"),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_face_credential_household_id", "face_credential", ["household_id"])
    op.create_index("ix_face_credential_actor_id", "face_credential", ["actor_id"])
    op.create_index("ix_face_credential_status", "face_credential", ["status"])
    op.create_index(
        "uq_face_credential_active_account",
        "face_credential",
        ["household_id", "actor_id", "status"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_face_credential_active_account", table_name="face_credential")
    op.drop_index("ix_face_credential_status", table_name="face_credential")
    op.drop_index("ix_face_credential_actor_id", table_name="face_credential")
    op.drop_index("ix_face_credential_household_id", table_name="face_credential")
    op.drop_table("face_credential")
