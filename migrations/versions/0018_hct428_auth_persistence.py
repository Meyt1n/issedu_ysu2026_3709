"""HCT-428: persist local credentials, sessions, rate limits and PIN challenges."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_hct428_auth_persistence"
down_revision: str | None = "0017_hct429_household_timezone"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_account",
        sa.Column("actor_id", sa.String(120), primary_key=True),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "auth_pin",
        sa.Column("household_id", sa.String(120), primary_key=True),
        sa.Column("actor_id", sa.String(120), primary_key=True),
        sa.Column("pin_hash", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "auth_session",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("actor_id", sa.String(120), nullable=False),
        sa.Column("household_id", sa.String(120), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_from_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_auth_session_token_hash", "auth_session", ["token_hash"], unique=True)
    op.create_index("ix_auth_session_actor_id", "auth_session", ["actor_id"])
    op.create_index("ix_auth_session_household_id", "auth_session", ["household_id"])
    op.create_index("ix_auth_session_expires_at", "auth_session", ["expires_at"])
    op.create_index("ix_auth_session_revoked_at", "auth_session", ["revoked_at"])
    op.create_table(
        "auth_rate_limit_attempt",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("rate_key", sa.String(240), nullable=False),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_rate_limit_attempt_rate_key", "auth_rate_limit_attempt", ["rate_key"])
    op.create_index(
        "ix_auth_rate_limit_attempt_failed_at", "auth_rate_limit_attempt", ["failed_at"]
    )
    op.create_table(
        "auth_pin_challenge",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("actor_id", sa.String(120), nullable=False),
        sa.Column("household_id", sa.String(120), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("session_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grant_consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_auth_pin_challenge_actor_id", "auth_pin_challenge", ["actor_id"])
    op.create_index("ix_auth_pin_challenge_household_id", "auth_pin_challenge", ["household_id"])
    op.create_index("ix_auth_pin_challenge_session_hash", "auth_pin_challenge", ["session_hash"])
    op.create_index("ix_auth_pin_challenge_expires_at", "auth_pin_challenge", ["expires_at"])


def downgrade() -> None:
    op.drop_table("auth_pin_challenge")
    op.drop_table("auth_rate_limit_attempt")
    op.drop_table("auth_session")
    op.drop_table("auth_pin")
    op.drop_table("auth_account")
