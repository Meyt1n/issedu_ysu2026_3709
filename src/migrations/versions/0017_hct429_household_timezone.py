"""HCT-429: store a validated household business-day time zone."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_hct429_household_timezone"
down_revision: str | None = "0016_hct424_face_credential_status_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("household") as batch_op:
        batch_op.add_column(sa.Column("time_zone", sa.String(length=64), nullable=True))
    op.execute(sa.text("UPDATE household SET time_zone = 'UTC' WHERE time_zone IS NULL"))
    with op.batch_alter_table("household") as batch_op:
        batch_op.alter_column(
            "time_zone",
            existing_type=sa.String(length=64),
            nullable=False,
            server_default="UTC",
        )


def downgrade() -> None:
    with op.batch_alter_table("household") as batch_op:
        batch_op.drop_column("time_zone")
