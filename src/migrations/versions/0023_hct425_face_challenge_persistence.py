"""HCT-425: persist face-login challenges so multi-worker/restart deployments work.

Revision ID: 0023_hct425_face_challenge_persistence
Revises: 0022_hct442_knowledge_query_privacy

Face challenges were process-local dictionaries, which blocked the production
configuration gate (a challenge issued by one worker could not be consumed by
another and every restart invalidated in-flight logins). This table stores
only opaque metadata: no biometric payload, no frames, no similarity scores.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_hct425_face_challenge_persistence"
down_revision: str | None = "0022_hct442_knowledge_query_privacy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_face_challenge",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("actor_id", sa.String(120), nullable=False),
        sa.Column("household_id", sa.String(120), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_auth_face_challenge_actor_id", "auth_face_challenge", ["actor_id"])
    op.create_index(
        "ix_auth_face_challenge_household_id", "auth_face_challenge", ["household_id"]
    )
    op.create_index("ix_auth_face_challenge_expires_at", "auth_face_challenge", ["expires_at"])


def downgrade() -> None:
    op.drop_table("auth_face_challenge")
