from __future__ import annotations

import base64
import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from twitter_x.models.hashtag import Hashtag, TweetHashtag
from twitter_x.models.tweet import Tweet
from twitter_x.models.user import User
from twitter_x.redis import get_redis


async def get_home_timeline(
    db: AsyncSession,
    user_id: UUID,
    cursor: tuple | None = None,
    limit: int = 20,
) -> tuple[list[dict], str | None]:
    """Get home timeline — Redis ZSET first, Postgres fallback."""
    # Verify user exists
    user_result = await db.execute(select(User).where(User.user_id == user_id))
    if user_result.scalar_one_or_none() is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="User not found")

    redis = await get_redis()
    tweet_score_map: dict[UUID, float] = {}
    use_redis = redis is not None

    if use_redis:
        timeline_key = f"timeline:{user_id}"
        # Check if timeline has entries
        card = await redis.zcard(timeline_key)
        if card > 0:
            # Get tweet IDs from Redis ZSET (reverse score = reverse chronological)
            max_score = "+inf"
            min_score = "-inf"
            if cursor is not None:
                # cursor[0] is the created_at datetime
                max_score = f"({cursor[0].timestamp()}"  # exclusive upper bound

            # Get limit+1 to detect next page
            raw = await redis.zrevrangebyscore(
                timeline_key,
                max_score,
                min_score,
                start=0,
                num=limit + 1,
                withscores=True,
            )
            for tweet_id_str, score in raw:
                try:
                    tweet_id = UUID(tweet_id_str)
                    tweet_score_map[tweet_id] = score
                except ValueError:
                    continue

    # If Redis empty/unavailable, fallback to Postgres
    if not tweet_score_map:
        return await _postgres_timeline_fallback(db, user_id, cursor, limit)

    # Hydrate tweets from Postgres in score order
    return await _hydrate_tweets(db, tweet_score_map, limit)


async def _postgres_timeline_fallback(
    db: AsyncSession,
    user_id: UUID,
    cursor: tuple | None,
    limit: int,
) -> tuple[list[dict], str | None]:
    """Fallback: join follows + tweets directly in Postgres."""
    from twitter_x.models.follow import Follow

    # Get followee IDs
    follow_stmt = select(Follow.followee_id).where(Follow.follower_id == user_id)
    follow_result = await db.execute(follow_stmt)
    followee_ids = [row[0] for row in follow_result]

    if not followee_ids:
        return [], None

    # Build tweets query from followed users
    stmt = (
        select(Tweet)
        .where(Tweet.author_id.in_(followee_ids))
        .order_by(Tweet.created_at.desc(), Tweet.tweet_id.desc())
    )

    if cursor is not None:
        cursor_ts, cursor_id = cursor
        stmt = stmt.where(
            (Tweet.created_at < cursor_ts)
            | ((Tweet.created_at == cursor_ts) & (Tweet.tweet_id < cursor_id))
        )

    stmt = stmt.limit(limit + 1).options(selectinload(Tweet.author))
    result = await db.execute(stmt)
    tweets = result.scalars().all()

    # Build score map for ordering
    tweet_score_map = {}
    for tweet in tweets:
        tweet_score_map[tweet.tweet_id] = tweet.created_at.timestamp()

    return await _hydrate_tweets(db, tweet_score_map, limit)


async def _hydrate_tweets(
    db: AsyncSession,
    tweet_score_map: dict[UUID, float],
    limit: int,
) -> tuple[list[dict], str | None]:
    """Hydrate tweet objects from Postgres given tweet_id → score map."""
    # Get all requested tweet IDs
    tweet_ids = list(tweet_score_map.keys())
    if not tweet_ids:
        return [], None

    # Sort by score descending
    sorted_ids = sorted(tweet_ids, key=lambda tid: tweet_score_map[tid], reverse=True)

    # Fetch tweets from Postgres
    stmt = select(Tweet).where(Tweet.tweet_id.in_(sorted_ids)).options(selectinload(Tweet.author))
    result = await db.execute(stmt)
    tweet_map = {t.tweet_id: t for t in result.scalars().all()}

    # Build items in score order
    items = []
    for tid in sorted_ids:
        tweet = tweet_map.get(tid)
        if tweet is None:
            continue
        items.append(tweet)

    has_more = len(items) > limit
    items = items[:limit]

    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = _encode_cursor(last.created_at, last.tweet_id)

    # Build response items
    tweet_items = []
    for tweet in items:
        # Get hashtags
        ht_stmt = (
            select(Hashtag)
            .join(TweetHashtag, TweetHashtag.hashtag_id == Hashtag.hashtag_id)
            .where(TweetHashtag.tweet_id == tweet.tweet_id)
        )
        ht_result = await db.execute(ht_stmt)
        hashtags = ht_result.scalars().all()

        tweet_items.append(
            {
                "tweet_id": str(tweet.tweet_id),
                "author_id": str(tweet.author_id),
                "username": tweet.author.username,
                "text": tweet.text,
                "hashtags": [{"hashtag_id": str(h.hashtag_id), "name": h.name} for h in hashtags],
                "created_at": tweet.created_at.isoformat(),
                "author": {
                    "user_id": str(tweet.author.user_id),
                    "username": tweet.author.username,
                },
            }
        )

    return tweet_items, next_cursor


def _encode_cursor(created_at, tweet_id: UUID) -> str:
    payload = json.dumps(
        {"created_at": created_at.isoformat(), "tweet_id": str(tweet_id)}, separators=(",", ":")
    )
    return base64.b64encode(payload.encode()).decode()


def decode_cursor(cursor: str) -> tuple | None:
    try:
        data = json.loads(base64.b64decode(cursor.encode()).decode())
        ts = datetime.fromisoformat(data["created_at"])
        tid = UUID(data["tweet_id"])
        return (ts, tid)
    except Exception:
        return None
