"""HCT-405: make vision review creation and transitions concurrency-safe.

Revision ID: 0010_hct405_review_wiring
Revises: 0009_merge_backend_heads
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_hct405_review_wiring"
down_revision: str = "0009_merge_backend_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_FUSION_STATUS = sa.Enum(
    "MATCHED",
    "CONFLICT",
    "UNKNOWN",
    "LOW_QUALITY",
    name="fusion_status",
)
NEW_FUSION_STATUS = sa.Enum(
    "MATCHED",
    "CONFLICT",
    "UNKNOWN",
    "REVIEW",
    "LOW_QUALITY",
    name="fusion_status",
)
VISION_TASK = sa.table(
    "vision_task",
    sa.column("household_id", sa.String()),
    sa.column("member_id", sa.String()),
    sa.column("status", sa.String()),
    sa.column("error_code", sa.String()),
    sa.column("error_message", sa.String()),
)
MEMBER = sa.table(
    "member",
    sa.column("id", sa.String()),
    sa.column("household_id", sa.String()),
)


def upgrade() -> None:
    bind = op.get_bind()
    valid_member = sa.exists(
        sa.select(1)
        .select_from(MEMBER)
        .where(MEMBER.c.id == VISION_TASK.c.member_id)
    )
    bind.execute(
        sa.update(VISION_TASK)
        .where(
            VISION_TASK.c.member_id.is_not(None),
            valid_member,
        )
        .values(
            household_id=sa.select(MEMBER.c.household_id)
            .where(MEMBER.c.id == VISION_TASK.c.member_id)
            .scalar_subquery()
        )
    )
    bind.execute(
        sa.update(VISION_TASK)
        .where(
            VISION_TASK.c.status.in_(("queued", "running")),
            sa.or_(
                VISION_TASK.c.member_id.is_(None),
                ~valid_member,
            ),
        )
        .values(
            status="cancelled",
            error_code="MEMBER_SCOPE_INVALID",
            error_message="Legacy task has no valid member scope",
        )
    )
    duplicate = bind.execute(
        sa.text(
            """
            SELECT vision_task_id
            FROM review_task
            GROUP BY vision_task_id
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError("DUPLICATE_REVIEW_TASKS_REQUIRE_RECONCILIATION")

    if bind.dialect.name == "mysql":
        op.alter_column(
            "review_task",
            "fusion_status",
            existing_type=OLD_FUSION_STATUS,
            type_=NEW_FUSION_STATUS,
            existing_nullable=True,
        )
    op.add_column(
        "review_task",
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column(
        "review_task",
        sa.Column("fusion_context", sa.JSON(), nullable=True),
    )
    op.add_column(
        "review_task",
        sa.Column("fusion_fingerprint", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "review_task",
        sa.Column("transition_fingerprint", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "uq_review_vision_task",
        "review_task",
        ["vision_task_id"],
        unique=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    audit_row = bind.execute(
        sa.text(
            """
            SELECT id
            FROM review_task
            WHERE fusion_context IS NOT NULL
               OR fusion_fingerprint IS NOT NULL
               OR transition_fingerprint IS NOT NULL
               OR version <> 1
            LIMIT 1
            """
        )
    ).first()
    if audit_row is not None:
        raise RuntimeError("REVIEW_AUDIT_DATA_REQUIRE_FORWARD_FIX")

    review_row = bind.execute(
        sa.text(
            "SELECT id FROM review_task WHERE fusion_status = 'REVIEW' LIMIT 1"
        )
    ).first()
    if review_row is not None:
        raise RuntimeError("REVIEW_STATUS_ROWS_REQUIRE_FORWARD_FIX")

    if bind.dialect.name == "mysql":
        op.alter_column(
            "review_task",
            "fusion_status",
            existing_type=NEW_FUSION_STATUS,
            type_=OLD_FUSION_STATUS,
            existing_nullable=True,
        )
    op.drop_index("uq_review_vision_task", table_name="review_task")
    with op.batch_alter_table("review_task") as batch_op:
        batch_op.drop_column("transition_fingerprint")
        batch_op.drop_column("fusion_fingerprint")
        batch_op.drop_column("fusion_context")
        batch_op.drop_column("version")
