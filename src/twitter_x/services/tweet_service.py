from __future__ import annotations

import json
import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from twitter_x.models.hashtag import Hashtag, TweetHashtag
from twitter_x.models.tweet import Tweet
from twitter_x.models.user import User
from twitter_x.redis import get_redis
from twitter_x.schemas.tweet import HashtagItem, TweetCreate, TweetDetail, TweetResponse

_HASHTAG_RE = re.compile(r"#(\w+)", re.UNICODE)


async def _extract_hashtags_from_text(text: str) -> list[str]:
    """Extract hashtag names from tweet text (lowercased, without #)."""
    return [m.lower() for m in _HASHTAG_RE.findall(text)]


async def _upsert_hashtags(db: AsyncSession, names: list[str]) -> dict[str, Hashtag]:
    """Batch upsert hashtags, return {name: Hashtag} mapping."""
    result: dict[str, Hashtag] = {}
    seen = set()

    for name in names:
        if name in seen:
            continue
        seen.add(name)

        # Try to find existing
        stmt = select(Hashtag).where(Hashtag.name == name)
        row = await db.execute(stmt)
        hashtag = row.scalar_one_or_none()

        if hashtag is None:
            hashtag = Hashtag(name=name)
            db.add(hashtag)
            await db.flush()

        result[name] = hashtag

    return result


async def create_tweet(db: AsyncSession, data: TweetCreate) -> Tweet:
    """Create a tweet with hashtag extraction, upsert, and fan-out dispatch."""
    # Validate author exists
    author = await db.get(User, data.author_id)
    if author is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Author not found")

    # Extract hashtags from text + client-supplied
    text_hashtags = await _extract_hashtags_from_text(data.text)
    all_hashtags = list(dict.fromkeys(text_hashtags + (data.hashtags or [])))

    # Upsert hashtags
    hashtag_map = await _upsert_hashtags(db, all_hashtags)

    # Create tweet
    tweet = Tweet(author_id=data.author_id, text=data.text)
    db.add(tweet)
    await db.flush()

    # Create tweet_hashtag links
    for name in all_hashtags:
        ht = hashtag_map[name]
        link = TweetHashtag(tweet_id=tweet.tweet_id, hashtag_id=ht.hashtag_id)
        db.add(link)

    await db.flush()

    # Fire-and-forget fan-out dispatch to Redis queue
    redis = await get_redis()
    if redis is not None:
        payload = json.dumps(
            {
                "author_id": str(tweet.author_id),
                "tweet_id": str(tweet.tweet_id),
                "created_at": tweet.created_at.isoformat() if tweet.created_at else None,
            }
        )
        await redis.lpush("fanout_queue", payload)

    return tweet


async def get_tweet_detail(db: AsyncSession, tweet_id: UUID) -> TweetDetail | None:
    """Get tweet detail with author and hashtags."""
    stmt = (
        select(Tweet)
        .where(Tweet.tweet_id == tweet_id)
        .options(
            selectinload(Tweet.author),
        )
    )
    result = await db.execute(stmt)
    tweet = result.scalar_one_or_none()

    if tweet is None:
        return None

    # Load hashtags via join table
    hashtag_stmt = (
        select(Hashtag)
        .join(TweetHashtag, TweetHashtag.hashtag_id == Hashtag.hashtag_id)
        .where(TweetHashtag.tweet_id == tweet_id)
    )
    hashtag_result = await db.execute(hashtag_stmt)
    hashtags = hashtag_result.scalars().all()

    return TweetDetail(
        tweet_id=tweet.tweet_id,
        text=tweet.text,
        author={
            "user_id": tweet.author.user_id,
            "username": tweet.author.username,
        },
        hashtags=[HashtagItem(hashtag_id=h.hashtag_id, name=h.name) for h in hashtags],
        created_at=tweet.created_at,
    )


def _tweet_to_response(tweet: Tweet, hashtags: list[Hashtag]) -> TweetResponse:
    """Map a Tweet ORM model + hashtags to a TweetResponse."""
    return TweetResponse(
        tweet_id=tweet.tweet_id,
        author_id=tweet.author_id,
        text=tweet.text,
        hashtags=[HashtagItem(hashtag_id=h.hashtag_id, name=h.name) for h in hashtags],
        created_at=tweet.created_at,
    )


async def get_tweet_hashtags(db: AsyncSession, tweet_id: UUID) -> list[Hashtag]:
    """Get hashtags for a tweet."""
    stmt = (
        select(Hashtag)
        .join(TweetHashtag, TweetHashtag.hashtag_id == Hashtag.hashtag_id)
        .where(TweetHashtag.tweet_id == tweet_id)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
