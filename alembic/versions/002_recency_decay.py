"""Add recency_decay function and GIN indexes for full-text search.

Revision ID: 002_recency_decay
Revises: 1093b16c00af
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers
revision: str = "002_recency_decay"
down_revision: Union[str, None] = "1093b16c00af"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # recency_decay: boost recent content, decay older content
    # score_multiplier = 1.0 / (1.0 + extract(epoch from (now() - created_at)) / 86400.0)
    # i.e. content 1 day old gets 0.5x, 2 days gets 0.33x, etc.
    op.execute("""
        CREATE OR REPLACE FUNCTION recency_decay(created_at timestamptz)
        RETURNS float
        LANGUAGE sql
        IMMUTABLE PARALLEL SAFE
        AS $$
            SELECT 1.0 / (1.0 + extract(epoch from (now() - created_at)) / 86400.0)
        $$;
    """)

    # GIN indexes for full-text search on tsvector columns
    op.execute("CREATE INDEX IF NOT EXISTS ix_tweets_fts ON tweets USING GIN (fts_vector);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_hashtags_fts ON hashtags USING GIN (fts_vector);")

    # Composite index for cursor pagination on tweets (created_at DESC, tweet_id DESC)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tweets_created_at_id "
        "ON tweets (created_at DESC, tweet_id DESC);"
    )

    # Composite index for cursor pagination on follows join
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_follows_follower_created "
        "ON follows (follower_id, created_at DESC);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_follows_follower_created;")
    op.execute("DROP INDEX IF EXISTS ix_tweets_created_at_id;")
    op.execute("DROP INDEX IF EXISTS ix_hashtags_fts;")
    op.execute("DROP INDEX IF EXISTS ix_tweets_fts;")
    op.execute("DROP FUNCTION IF EXISTS recency_decay(timestamptz);")
