"""HCT-403: Ollama tool calling — no new tables, just tool registry module."""

# revision identifiers, used by Alembic.
revision = "0008_hct403_tool_call"
down_revision = "0007_hct401_knowledge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No schema changes — tool calling is a software module, not a table.
    pass


def downgrade() -> None:
    pass
