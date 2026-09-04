"""HCT-441: preserve full model provenance in review tasks."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027_hct441_review_model_version_length"
down_revision: str | None = "0026_hct441_model_version_length"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("review_task") as batch_op:
        batch_op.alter_column(
            "model_version",
            existing_type=sa.String(length=64),
            type_=sa.String(length=128),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("review_task") as batch_op:
        batch_op.alter_column(
            "model_version",
            existing_type=sa.String(length=128),
            type_=sa.String(length=64),
            existing_nullable=True,
        )
