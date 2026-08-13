"""Merge the restored backend schema branch with HCT-208/HCT-404.

Revision ID: 0009_merge_backend_heads
Revises: 0008_hct403_tool_call, 0006_hct404_model_version_binding
Create Date: 2026-08-13
"""

from collections.abc import Sequence

revision: str = "0009_merge_backend_heads"
down_revision: tuple[str, str] = (
    "0008_hct403_tool_call",
    "0006_hct404_model_version_binding",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Join both already-applied schema branches without changing data."""


def downgrade() -> None:
    """Split the migration graph back into its two parent heads."""
