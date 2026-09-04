"""Allow pending health facts to exist without a confirmer."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_allow_pending_health_events"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("health_event") as batch_op:
        batch_op.alter_column(
            "confirmed_by",
            existing_type=sa.String(length=120),
            nullable=True,
        )


def downgrade() -> None:
    connection = op.get_bind()
    pending_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM health_event WHERE confirmed_by IS NULL")
    ).scalar_one()
    if pending_count:
        raise RuntimeError("不能安全回滚：请先处理 confirmed_by 为空的待确认事件。")
    with op.batch_alter_table("health_event") as batch_op:
        batch_op.alter_column(
            "confirmed_by",
            existing_type=sa.String(length=120),
            nullable=False,
        )
