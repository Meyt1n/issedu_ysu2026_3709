"""Expand Alembic's revision column before the first long revision identifier.

Revision ID: 0006_expand_alembic_version
Revises: 0005_hct208_hard_sample_consent
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_expand_alembic_version"
down_revision: str | None = "0005_hct208_hard_sample_consent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        op.alter_column(
            "alembic_version",
            "version_num",
            existing_type=sa.String(32),
            type_=sa.String(128),
            existing_nullable=False,
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        op.alter_column(
            "alembic_version",
            "version_num",
            existing_type=sa.String(128),
            type_=sa.String(32),
            existing_nullable=False,
        )
