"""Persist HCT-404 release and rollback evidence hashes.

Revision ID: 0019_hct404_release_evidence
Revises: 0018_hct428_auth_persistence
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_hct404_release_evidence"
down_revision: str | None = "0018_hct428_auth_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_version_binding",
        sa.Column("release_evidence_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "model_version_binding",
        sa.Column("rollback_evidence_hash", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_version_binding", "rollback_evidence_hash")
    op.drop_column("model_version_binding", "release_evidence_hash")
