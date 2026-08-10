"""Add immutable event ordering, idempotency, outbox recovery, and checkpoints."""

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0004_hct103_event_recovery"
down_revision: str | None = "0003_hct102_auth_security"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_value(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return json.loads(value)
    return dict(value or {})


def _create_immutability_triggers() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(
            "CREATE TRIGGER trg_health_event_no_update "
            "BEFORE UPDATE ON health_event BEGIN "
            "SELECT RAISE(ABORT, 'HEALTH_EVENT_IMMUTABLE'); END"
        )
        op.execute(
            "CREATE TRIGGER trg_health_event_no_delete "
            "BEFORE DELETE ON health_event BEGIN "
            "SELECT RAISE(ABORT, 'HEALTH_EVENT_IMMUTABLE'); END"
        )
    elif dialect == "mysql":
        op.execute(
            "CREATE TRIGGER trg_health_event_no_update "
            "BEFORE UPDATE ON health_event FOR EACH ROW "
            "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'HEALTH_EVENT_IMMUTABLE'"
        )
        op.execute(
            "CREATE TRIGGER trg_health_event_no_delete "
            "BEFORE DELETE ON health_event FOR EACH ROW "
            "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'HEALTH_EVENT_IMMUTABLE'"
        )


def _drop_immutability_triggers() -> None:
    dialect = op.get_bind().dialect.name
    if dialect in {"sqlite", "mysql"}:
        op.execute("DROP TRIGGER IF EXISTS trg_health_event_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_health_event_no_delete")


def upgrade() -> None:
    op.add_column("health_event", sa.Column("sequence_no", sa.Integer(), nullable=True))
    op.add_column("health_event", sa.Column("idempotency_key", sa.String(length=128)))
    op.add_column("health_event", sa.Column("request_fingerprint", sa.String(length=64)))
    op.add_column("health_event", sa.Column("correlation_id", sa.String(length=120)))
    op.add_column("health_event", sa.Column("causation_id", sa.String(length=36)))
    op.add_column("health_event", sa.Column("supersedes_event_id", sa.String(length=36)))
    op.add_column(
        "health_event",
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("health_event", sa.Column("occurred_at", sa.DateTime(timezone=True)))

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, household_id, member_id, created_at FROM health_event "
            "ORDER BY household_id, member_id, created_at, id"
        )
    ).mappings()
    counters: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (row["household_id"], row["member_id"])
        counters[key] = counters.get(key, 0) + 1
        recorded_at = row["created_at"] or datetime.now(UTC)
        connection.execute(
            sa.text(
                "UPDATE health_event SET sequence_no = :sequence_no, "
                "correlation_id = :correlation_id, occurred_at = :occurred_at "
                "WHERE id = :event_id"
            ),
            {
                "sequence_no": counters[key],
                "correlation_id": row["id"],
                "occurred_at": recorded_at,
                "event_id": row["id"],
            },
        )

    with op.batch_alter_table("health_event") as batch_op:
        batch_op.alter_column("sequence_no", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column(
            "correlation_id", existing_type=sa.String(length=120), nullable=False
        )
        batch_op.alter_column(
            "occurred_at", existing_type=sa.DateTime(timezone=True), nullable=False
        )
        batch_op.alter_column(
            "schema_version",
            existing_type=sa.Integer(),
            existing_server_default="1",
            server_default=None,
        )
        batch_op.create_foreign_key(
            "fk_event_supersedes",
            "health_event",
            ["supersedes_event_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(
            "uq_event_household_member_sequence",
            ["household_id", "member_id", "sequence_no"],
            unique=True,
        )
        batch_op.create_index(
            "uq_event_household_idempotency",
            ["household_id", "idempotency_key"],
            unique=True,
        )
        batch_op.create_index("uq_event_supersedes", ["supersedes_event_id"], unique=True)
        batch_op.create_index("ix_event_correlation", ["correlation_id"])

    op.add_column(
        "outbox_message",
        sa.Column("status", sa.String(length=16), nullable=False, server_default="PENDING"),
    )
    op.add_column(
        "outbox_message",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("outbox_message", sa.Column("available_at", sa.DateTime(timezone=True)))
    op.add_column("outbox_message", sa.Column("locked_at", sa.DateTime(timezone=True)))
    op.add_column("outbox_message", sa.Column("dispatched_at", sa.DateTime(timezone=True)))
    op.add_column("outbox_message", sa.Column("last_error", sa.String(length=64)))
    op.add_column("outbox_message", sa.Column("updated_at", sa.DateTime(timezone=True)))
    connection.execute(
        sa.text(
            "UPDATE outbox_message SET available_at = COALESCE(created_at, CURRENT_TIMESTAMP), "
            "updated_at = COALESCE(created_at, CURRENT_TIMESTAMP), "
            "status = CASE WHEN dispatched = 1 THEN 'DISPATCHED' ELSE 'PENDING' END, "
            "dispatched_at = CASE WHEN dispatched = 1 THEN created_at ELSE NULL END"
        )
    )
    with op.batch_alter_table("outbox_message") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=16),
            existing_server_default="PENDING",
            server_default=None,
        )
        batch_op.alter_column(
            "attempts",
            existing_type=sa.Integer(),
            existing_server_default="0",
            server_default=None,
        )
        batch_op.alter_column(
            "available_at", existing_type=sa.DateTime(timezone=True), nullable=False
        )
        batch_op.alter_column(
            "updated_at", existing_type=sa.DateTime(timezone=True), nullable=False
        )
        batch_op.create_index("uq_outbox_event", ["event_id"], unique=True)
        batch_op.create_index(
            "ix_outbox_status_available", ["status", "available_at"], unique=False
        )

    op.add_column(
        "member_state_projection",
        sa.Column("last_sequence", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "member_state_projection",
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("member_state_projection", sa.Column("state_hash", sa.String(length=64)))
    projections = connection.execute(
        sa.text(
            "SELECT member_id, state, last_event_id FROM member_state_projection"
        )
    ).mappings()
    for projection in projections:
        sequence_no = 0
        if projection["last_event_id"] is not None:
            sequence_no = int(
                connection.execute(
                    sa.text("SELECT sequence_no FROM health_event WHERE id = :event_id"),
                    {"event_id": projection["last_event_id"]},
                ).scalar_one_or_none()
                or 0
            )
        state = _json_value(projection["state"])
        connection.execute(
            sa.text(
                "UPDATE member_state_projection SET last_sequence = :last_sequence, "
                "version = :version, state_hash = :state_hash WHERE member_id = :member_id"
            ),
            {
                "last_sequence": sequence_no,
                "version": int(state.get("events_count", 0)),
                "state_hash": _canonical_hash(state),
                "member_id": projection["member_id"],
            },
        )
    with op.batch_alter_table("member_state_projection") as batch_op:
        batch_op.alter_column(
            "last_sequence",
            existing_type=sa.Integer(),
            existing_server_default="0",
            server_default=None,
        )
        batch_op.alter_column(
            "version",
            existing_type=sa.Integer(),
            existing_server_default="0",
            server_default=None,
        )

    op.create_table(
        "projection_checkpoint",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("member_id", sa.String(length=36), nullable=False),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.Column("last_event_id", sa.String(length=36)),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["member_id"], ["member.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "uq_checkpoint_member_sequence",
        "projection_checkpoint",
        ["member_id", "last_sequence"],
        unique=True,
    )
    _create_immutability_triggers()


def downgrade() -> None:
    connection = op.get_bind()
    event_count = connection.execute(sa.text("SELECT COUNT(*) FROM health_event")).scalar_one()
    if event_count:
        raise RuntimeError(
            "Cannot downgrade HCT-103 while immutable health events must be retained; "
            "use a forward repair."
        )

    _drop_immutability_triggers()
    op.drop_index("uq_checkpoint_member_sequence", table_name="projection_checkpoint")
    op.drop_table("projection_checkpoint")
    with op.batch_alter_table("member_state_projection") as batch_op:
        batch_op.drop_column("state_hash")
        batch_op.drop_column("version")
        batch_op.drop_column("last_sequence")
    with op.batch_alter_table("outbox_message") as batch_op:
        batch_op.drop_index("ix_outbox_status_available")
        batch_op.drop_index("uq_outbox_event")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("last_error")
        batch_op.drop_column("dispatched_at")
        batch_op.drop_column("locked_at")
        batch_op.drop_column("available_at")
        batch_op.drop_column("attempts")
        batch_op.drop_column("status")
    with op.batch_alter_table("health_event") as batch_op:
        batch_op.drop_index("ix_event_correlation")
        batch_op.drop_index("uq_event_supersedes")
        batch_op.drop_index("uq_event_household_idempotency")
        batch_op.drop_index("uq_event_household_member_sequence")
        batch_op.drop_constraint("fk_event_supersedes", type_="foreignkey")
        batch_op.drop_column("occurred_at")
        batch_op.drop_column("schema_version")
        batch_op.drop_column("supersedes_event_id")
        batch_op.drop_column("causation_id")
        batch_op.drop_column("correlation_id")
        batch_op.drop_column("request_fingerprint")
        batch_op.drop_column("idempotency_key")
        batch_op.drop_column("sequence_no")
