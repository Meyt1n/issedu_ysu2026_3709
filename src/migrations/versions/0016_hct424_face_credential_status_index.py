"""Allow historical face credential tombstones per account."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_hct424_face_credential_status_index"
down_revision: str | None = "0015_hct424_face_credential"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_face_credential_active_account", table_name="face_credential")
    op.create_index(
        "uq_face_credential_active_account",
        "face_credential",
        ["household_id", "actor_id", "status"],
        unique=True,
        sqlite_where=sa.text("status = 'ACTIVE'"),
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )


def downgrade() -> None:
    op.drop_index("uq_face_credential_active_account", table_name="face_credential")
    op.create_index(
        "uq_face_credential_active_account",
        "face_credential",
        ["household_id", "actor_id", "status"],
        unique=True,
    )
