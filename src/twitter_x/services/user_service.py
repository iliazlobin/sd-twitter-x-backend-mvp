from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from twitter_x.models.follow import Follow
from twitter_x.models.hashtag import Hashtag, TweetHashtag
from twitter_x.models.tweet import Tweet
from twitter_x.models.user import User
from twitter_x.redis import get_redis
from twitter_x.schemas.common import FollowResponse
from twitter_x.schemas.user import UserCreate, UserResponse


async def create_user(db: AsyncSession, data: UserCreate) -> User:
    user = User(username=data.username, display_name=data.display_name)
    db.add(user)
    await db.flush()
    return user


async def get_user_by_id(db: AsyncSession, user_id: UUID) -> User | None:
    result = await db.execute(select(User).where(User.user_id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


def user_to_response(user: User) -> UserResponse:
    return UserResponse(
        user_id=user.user_id,
        username=user.username,
        display_name=user.display_name,
        follower_count=user.follower_count,
        following_count=user.following_count,
        created_at=user.created_at,
    )


async def follow_user(
    db: AsyncSession,
    followee_id: UUID,
    follower_id: UUID,
) -> FollowResponse:
    """Follow a user. Idempotent. Updates denormalized counters and backfills timeline."""
    if followee_id == follower_id:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="Cannot follow yourself")

    # Validate both users exist
    follower = await get_user_by_id(db, follower_id)
    followee = await get_user_by_id(db, followee_id)
    if follower is None or followee is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="User not found")

    # Check if already following
    existing = await db.execute(
        select(Follow).where(
            Follow.follower_id == follower_id,
            Follow.followee_id == followee_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return FollowResponse(status="following")

    # Create follow relationship
    follow = Follow(follower_id=follower_id, followee_id=followee_id)
    db.add(follow)

    # Update counters
    follower.following_count = (follower.following_count or 0) + 1
    followee.follower_count = (followee.follower_count or 0) + 1

    await db.flush()

    # Backfill followee's recent tweets into follower's Redis timeline
    redis = await get_redis()
    if redis is not None:
        # Get last 50 tweets from followee
        stmt = (
            select(Tweet.tweet_id, Tweet.created_at)
            .where(Tweet.author_id == followee_id)
            .order_by(Tweet.created_at.desc())
            .limit(50)
        )
        rows = await db.execute(stmt)
        timeline_key = f"timeline:{follower_id}"
        pipeline = redis.pipeline()
        for tweet_id, created_at in rows:
            score = created_at.timestamp()
            pipeline.zadd(timeline_key, {str(tweet_id): score})
        await pipeline.execute()

    return FollowResponse(status="following")


async def unfollow_user(
    db: AsyncSession,
    followee_id: UUID,
    follower_id: UUID,
) -> FollowResponse:
    """Unfollow a user. Idempotent. Updates denormalized counters and cleans up timeline."""
    # Validate both users exist
    follower = await get_user_by_id(db, follower_id)
    followee = await get_user_by_id(db, followee_id)
    if follower is None or followee is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="User not found")

    # Find and delete follow
    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == follower_id,
            Follow.followee_id == followee_id,
        )
    )
    follow = result.scalar_one_or_none()
    if follow is not None:
        await db.delete(follow)

        # Update counters
        follower.following_count = max(0, (follower.following_count or 0) - 1)
        followee.follower_count = max(0, (followee.follower_count or 0) - 1)

        # Remove followee's tweets from follower's Redis timeline
        redis = await get_redis()
        if redis is not None:
            stmt = select(Tweet.tweet_id).where(Tweet.author_id == followee_id)
            rows = await db.execute(stmt)
            tweet_ids = [str(row[0]) for row in rows]
            if tweet_ids:
                await redis.zrem(f"timeline:{follower_id}", *tweet_ids)

    return FollowResponse(status="unfollowed")


async def get_profile_tweets(
    db: AsyncSession,
    user_id: UUID,
    cursor: tuple | None = None,
    limit: int = 20,
) -> tuple[list[dict], str | None]:
    """Get a user's own tweets, cursor-paginated (reverse chronological)."""
    # Verify user exists
    user = await get_user_by_id(db, user_id)
    if user is None:
        return [], None

    # Build query
    stmt = (
        select(Tweet)
        .where(Tweet.author_id == user_id)
        .order_by(Tweet.created_at.desc(), Tweet.tweet_id.desc())
    )

    if cursor is not None:
        cursor_ts, cursor_id = cursor
        stmt = stmt.where(
            (Tweet.created_at < cursor_ts)
            | ((Tweet.created_at == cursor_ts) & (Tweet.tweet_id < cursor_id))
        )

    stmt = stmt.limit(limit + 1)  # +1 to detect if there's a next page
    result = await db.execute(stmt.options(selectinload(Tweet.author)))
    tweets = result.scalars().all()

    has_more = len(tweets) > limit
    items = tweets[:limit]

    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = _encode_cursor(last.created_at, last.tweet_id)

    # Build response items with hashtags
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
            }
        )

    return tweet_items, next_cursor


def _encode_cursor(created_at, tweet_id: UUID) -> str:
    import base64
    import json

    payload = json.dumps(
        {"created_at": created_at.isoformat(), "tweet_id": str(tweet_id)}, separators=(",", ":")
    )
    return base64.b64encode(payload.encode()).decode()


def _decode_cursor(cursor: str) -> tuple | None:
    import base64
    import json
    from datetime import datetime

    try:
        data = json.loads(base64.b64decode(cursor.encode()).decode())
        ts = datetime.fromisoformat(data["created_at"])
        tid = UUID(data["tweet_id"])
        return (ts, tid)
    except Exception:
        return None
