"""HCT-442: replace plaintext knowledge queries with privacy-safe digests.

Revision ID: 0022_hct442_knowledge_query_privacy
Revises: 0021_hct425_face_credential_mysql_index
"""

import hashlib
import unicodedata
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_hct442_knowledge_query_privacy"
down_revision: str | None = "0021_hct425_face_credential_mysql_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fingerprint(value: str) -> tuple[str, int]:
    normalized = " ".join(unicodedata.normalize("NFKC", value).split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest(), len(normalized)


def upgrade() -> None:
    with op.batch_alter_table("retrieval_query") as batch:
        batch.add_column(sa.Column("query_digest", sa.String(64), nullable=True))
        batch.add_column(sa.Column("query_length", sa.Integer(), nullable=True))
        batch.alter_column("query_text", existing_type=sa.Text(), nullable=True)

    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, query_text FROM retrieval_query WHERE query_text IS NOT NULL")
    ).fetchall()
    for row in rows:
        digest, length = _fingerprint(str(row.query_text))
        connection.execute(
            sa.text(
                "UPDATE retrieval_query "
                "SET query_digest = :digest, query_length = :length, query_text = NULL "
                "WHERE id = :id"
            ),
            {"id": row.id, "digest": digest, "length": length},
        )

    # Existing audit rows are only useful when their minimum metadata is
    # complete.  Empty tables are common in local demos, so this remains
    # portable across SQLite and MySQL without a database-specific hash.
    connection.execute(
        sa.text(
            "UPDATE retrieval_query SET query_digest = :digest, query_length = 0 "
            "WHERE query_digest IS NULL"
        ),
        {"digest": hashlib.sha256(b"").hexdigest()},
    )

    with op.batch_alter_table("retrieval_query") as batch:
        batch.alter_column("query_digest", existing_type=sa.String(64), nullable=False)
        batch.alter_column("query_length", existing_type=sa.Integer(), nullable=False)

    op.create_index("ix_retrieval_query_query_digest", "retrieval_query", ["query_digest"])


def downgrade() -> None:
    # A downgrade cannot reconstruct query text.  It restores the legacy
    # non-null column shape with an empty placeholder, preserving the privacy
    # redaction rather than inventing the deleted question.
    op.drop_index("ix_retrieval_query_query_digest", table_name="retrieval_query")
    op.get_bind().execute(
        sa.text("UPDATE retrieval_query SET query_text = '' WHERE query_text IS NULL")
    )
    with op.batch_alter_table("retrieval_query") as batch:
        batch.drop_column("query_length")
        batch.drop_column("query_digest")
        batch.alter_column("query_text", existing_type=sa.Text(), nullable=False)
