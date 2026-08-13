"""HCT-208: correction diffs, hard sample pool, independent training consent,
and export manifest tables.

Revision ID: 0005_hct208_hard_sample_consent
Revises: 0004_hct103_event_idempotency
Create Date: 2026-08-12
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_hct208_hard_sample_consent"
down_revision: str | None = "0004_hct103_event_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    empty_json_default = (
        sa.text("(JSON_OBJECT())")
        if op.get_bind().dialect.name == "mysql"
        else sa.text("'{}'")
    )
    # ── 1. correction_diff ────────────────────────────────────────────
    op.create_table(
        "correction_diff",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_event_id",
            sa.String(36),
            sa.ForeignKey("health_event.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "household_id",
            sa.String(36),
            sa.ForeignKey("household.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "member_id",
            sa.String(36),
            sa.ForeignKey("member.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field_path", sa.String(120), nullable=False),
        sa.Column("before_value", sa.JSON(), nullable=True),
        sa.Column("after_value", sa.JSON(), nullable=True),
        sa.Column("reason", sa.String(240), nullable=False),
        sa.Column(
            "evidence",
            sa.JSON(),
            nullable=False,
            server_default=empty_json_default,
        ),
        sa.Column("operator_actor_id", sa.String(120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_correction_diff_source_event", "correction_diff", ["source_event_id"])
    op.create_index(
        "ix_correction_diff_household_member", "correction_diff", ["household_id", "member_id"]
    )
    op.create_index("ix_correction_diff_operator", "correction_diff", ["operator_actor_id"])

    # ── 2. hard_sample ───────────────────────────────────────────────
    op.create_table(
        "hard_sample",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_event_id",
            sa.String(36),
            sa.ForeignKey("health_event.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "household_id",
            sa.String(36),
            sa.ForeignKey("household.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "member_id",
            sa.String(36),
            sa.ForeignKey("member.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("reviewed_by", sa.String(120), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.String(120), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_hard_sample_source", "hard_sample", ["source_event_id"])
    op.create_index("ix_hard_sample_household_status", "hard_sample", ["household_id", "status"])
    op.create_index("ix_hard_sample_category", "hard_sample", ["household_id", "category"])

    # ── 3. training_consent ──────────────────────────────────────────
    op.create_table(
        "training_consent",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "hard_sample_id",
            sa.String(36),
            sa.ForeignKey("hard_sample.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "household_id",
            sa.String(36),
            sa.ForeignKey("household.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "member_id",
            sa.String(36),
            sa.ForeignKey("member.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("granted_by", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'active'")),
        sa.Column(
            "scope",
            sa.JSON(),
            nullable=False,
            server_default=empty_json_default,
        ),
        sa.Column("license", sa.String(60), nullable=False, server_default=sa.text("'internal'")),
        sa.Column("revoked_by", sa.String(120), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_training_consent_sample", "training_consent", ["hard_sample_id"])
    op.create_index(
        "ix_training_consent_status", "training_consent", ["household_id", "status"]
    )

    # ── 4. export_manifest ───────────────────────────────────────────
    op.create_table(
        "export_manifest",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version", sa.String(40), nullable=False, unique=True),
        sa.Column("group_key", sa.String(120), nullable=False),
        sa.Column("license", sa.String(60), nullable=False),
        sa.Column("sample_ids", sa.JSON(), nullable=False),
        sa.Column("total_samples", sa.Integer(), nullable=False),
        sa.Column("event_ids", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'active'")),
        sa.Column("invalidated_by", sa.String(120), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_export_manifest_group_key", "export_manifest", ["group_key"])
    op.create_index("ix_export_manifest_status", "export_manifest", ["status"])


def downgrade() -> None:
    # Reverse dependency order: export_manifest → training_consent → hard_sample → correction_diff
    op.drop_table("export_manifest")

    op.drop_table("training_consent")

    op.drop_table("hard_sample")

    op.drop_table("correction_diff")
