"""initial

Revision ID: 001
Revises:
Create Date: 2026-07-02

Create the initial schema: users, tweets, hashtags, tweet_hashtags, follows tables
plus GIN indexes for full-text search.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # users
    op.create_table(
        "users",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(15), unique=True, nullable=False, index=True),
        sa.Column("display_name", sa.String(50), nullable=True),
        sa.Column("follower_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("following_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # tweets
    op.create_table(
        "tweets",
        sa.Column("tweet_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "author_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("text", sa.String(280), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Add FTS tsvector column and GIN index to tweets
    op.execute(
        sa.text(
            "ALTER TABLE tweets ADD COLUMN fts_vector tsvector "
            "GENERATED ALWAYS AS (to_tsvector('english', text)) STORED"
        )
    )
    op.create_index("ix_tweets_fts_vector", "tweets", ["fts_vector"], postgresql_using="gin")

    # hashtags
    op.create_table(
        "hashtags",
        sa.Column("hashtag_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(50), unique=True, nullable=False, index=True),
    )

    # Add FTS tsvector column and GIN index to hashtags
    op.execute(
        sa.text(
            "ALTER TABLE hashtags ADD COLUMN fts_vector tsvector "
            "GENERATED ALWAYS AS (to_tsvector('english', name)) STORED"
        )
    )
    op.create_index("ix_hashtags_fts_vector", "hashtags", ["fts_vector"], postgresql_using="gin")

    # tweet_hashtags (join table)
    op.create_table(
        "tweet_hashtags",
        sa.Column(
            "tweet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tweets.tweet_id"),
            primary_key=True,
        ),
        sa.Column(
            "hashtag_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hashtags.hashtag_id"),
            primary_key=True,
        ),
        sa.UniqueConstraint("tweet_id", "hashtag_id"),
    )

    # follows
    op.create_table(
        "follows",
        sa.Column(
            "follower_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            primary_key=True,
        ),
        sa.Column(
            "followee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("follower_id", "followee_id"),
    )

    # Composite index for timeline queries: WHERE follower_id = X
    op.create_index("ix_follows_follower_id", "follows", ["follower_id"])


def downgrade() -> None:
    op.drop_table("follows")
    op.drop_table("tweet_hashtags")
    op.drop_table("hashtags")
    op.drop_table("tweets")
    op.drop_table("users")
