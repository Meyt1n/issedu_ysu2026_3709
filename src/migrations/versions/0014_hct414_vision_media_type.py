"""HCT-414-D1: persist the image/video media type on vision tasks."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_hct414_vision_media_type"
down_revision: str | None = "0013_hct413_risk_acknowledgement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("vision_task") as batch_op:
        batch_op.add_column(
            sa.Column("media_type", sa.String(length=16), nullable=False, server_default="image")
        )
        batch_op.create_index("ix_vision_task_media_type", ["media_type"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("vision_task") as batch_op:
        batch_op.drop_index("ix_vision_task_media_type")
        batch_op.drop_column("media_type")
