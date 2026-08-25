"""Fix face credential tombstone uniqueness on MySQL.

Revision ID: 0020_hct425_face_credential_mysql_index
Revises: 0019_hct404_release_evidence

Migration 0016 recreated ``uq_face_credential_active_account`` as a partial
unique index limited to ``status = 'ACTIVE'`` via ``sqlite_where`` /
``postgresql_where``.  MySQL has no partial indexes and silently created a
full unique index over (household_id, actor_id, status), so a second rebind
(two REVOKED rows) or erasure propagation (two DELETED rows) failed with an
IntegrityError on the Compose/MySQL deployment.  On MySQL the index becomes a
plain lookup index; single-ACTIVE-per-account stays enforced by the
application check in ``register_face_credential``.  SQLite/PostgreSQL keep the
partial unique index unchanged.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020_hct425_face_credential_mysql_index"
down_revision: str | None = "0019_hct404_release_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "uq_face_credential_active_account"
_TABLE = "face_credential"
_COLUMNS = ["household_id", "actor_id", "status"]


def upgrade() -> None:
    if op.get_bind().dialect.name != "mysql":
        return
    op.drop_index(_INDEX_NAME, table_name=_TABLE)
    op.create_index(_INDEX_NAME, _TABLE, _COLUMNS, unique=False)


def downgrade() -> None:
    if op.get_bind().dialect.name != "mysql":
        return
    op.drop_index(_INDEX_NAME, table_name=_TABLE)
    op.create_index(_INDEX_NAME, _TABLE, _COLUMNS, unique=True)
