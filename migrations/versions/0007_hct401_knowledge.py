"""HCT-401: Knowledge store — documents, chunks, index snapshots, retrieval audit."""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0007_hct401_knowledge"
down_revision = "0006_hct204_vision_task"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_document",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column("license", sa.String(60), nullable=False, default="internal"),
        sa.Column("version", sa.String(40), nullable=False, default="1.0"),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("permission_scope", sa.JSON, nullable=False, default=dict),
        sa.Column("status", sa.String(20), nullable=False, default="active", index=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.String(120), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("full_text", sa.Text, nullable=False, default=""),
        sa.Column("created_by", sa.String(120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "knowledge_chunk",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), nullable=False, index=True),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("locator", sa.String(200), nullable=True),
        sa.Column("term_vector", sa.JSON, nullable=False, default=dict),
    )
    op.create_table(
        "knowledge_index",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version", sa.String(40), nullable=False, unique=True),
        sa.Column("document_count", sa.Integer, nullable=False, default=0),
        sa.Column("chunk_count", sa.Integer, nullable=False, default=0),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column("created_by", sa.String(120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "retrieval_query",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("query_text", sa.Text, nullable=False),
        sa.Column("actor_id", sa.String(120), nullable=False),
        sa.Column("household_id", sa.String(36), nullable=True),
        sa.Column("member_id", sa.String(36), nullable=True),
        sa.Column("returned_count", sa.Integer, nullable=False, default=0),
        sa.Column("top_chunk_ids", sa.JSON, default=list),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_knowledge_doc_status", "knowledge_document", ["status"])
    op.create_index("ix_knowledge_chunk_doc", "knowledge_chunk", ["document_id", "chunk_index"])


def downgrade() -> None:
    op.drop_table("retrieval_query")
    op.drop_table("knowledge_index")
    op.drop_table("knowledge_chunk")
    op.drop_table("knowledge_document")
