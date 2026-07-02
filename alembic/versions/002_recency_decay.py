"""recency_decay function

Revision ID: 002
Revises: 001
Create Date: 2026-07-02

Add a recency_decay(timestamp) SQL function that returns a score multiplier
between 0 and 1, decaying exponentially from 1.0 at now to near-zero after
30 days. Used by the full-text search query to boost recent tweets over
older ones.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION recency_decay(ts timestamptz)
        RETURNS float8
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        AS $$
            SELECT 1.0 / (1.0 + EXTRACT(EPOCH FROM (now() - ts)) / 86400.0)
        $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS recency_decay(timestamptz)")
