"""HCT-404: model version binding table for release management and rollback.

Revision ID: 0006_hct404_model_version_binding
Revises: 0005_hct208_hard_sample_consent
Create Date: 2026-08-12
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_hct404_model_version_binding"
down_revision: str | None = "0005_hct208_hard_sample_consent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_version_binding",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("dataset_version", sa.String(128), nullable=False),
        sa.Column(
            "export_manifest_id",
            sa.String(36),
            sa.ForeignKey("export_manifest.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("fixed_set_hash", sa.String(64), nullable=False),
        sa.Column(
            "release_status",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'inactive'"),
        ),
        sa.Column("safety_thresholds", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("comparison_report_hash", sa.String(64), nullable=True),
        sa.Column("approved_by", sa.String(120), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.String(120), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_model_binding_model_id", "model_version_binding", ["model_id"])
    op.create_index(
        "ix_model_binding_release_status", "model_version_binding", ["release_status"]
    )


def downgrade() -> None:
    op.drop_index("ix_model_binding_release_status", table_name="model_version_binding")
    op.drop_index("ix_model_binding_model_id", table_name="model_version_binding")
    op.drop_table("model_version_binding")
