from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from twitter_x.database import get_session
from twitter_x.schemas.tweet import TweetCreate, TweetDetail, TweetResponse
from twitter_x.services.tweet_service import (
    create_tweet as create_tweet_svc,
)
from twitter_x.services.tweet_service import (
    get_tweet_detail as get_tweet_detail_svc,
)
from twitter_x.services.tweet_service import (
    get_tweet_hashtags,
)

tweets_router = APIRouter(prefix="/api/v1/tweets", tags=["tweets"])


@tweets_router.post("", status_code=201, response_model=TweetResponse)
async def create_tweet(
    body: TweetCreate,
    db: AsyncSession = Depends(get_session),
) -> TweetResponse:
    """Create a new tweet with optional hashtags."""
    try:
        tweet = await create_tweet_svc(db, body)
        await db.commit()
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise

    hashtags = await get_tweet_hashtags(db, tweet.tweet_id)
    return TweetResponse(
        tweet_id=tweet.tweet_id,
        author_id=tweet.author_id,
        text=tweet.text,
        hashtags=[{"hashtag_id": h.hashtag_id, "name": h.name} for h in hashtags],
        created_at=tweet.created_at,
    )


@tweets_router.get("/{tweet_id}", response_model=TweetDetail)
async def get_tweet(
    tweet_id: UUID,
    db: AsyncSession = Depends(get_session),
) -> TweetDetail:
    """Get a tweet by ID with author and hashtags."""
    detail = await get_tweet_detail_svc(db, tweet_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Tweet not found")
    return detail
