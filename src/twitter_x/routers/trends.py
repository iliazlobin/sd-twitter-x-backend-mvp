import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from twitter_x.database import get_session
from twitter_x.models.hashtag import Hashtag
from twitter_x.redis import get_redis
from twitter_x.schemas.trends import TrendItem, TrendsResponse

router = APIRouter(prefix="/api/v1/trends", tags=["trends"])

VALID_WINDOWS = frozenset({"1h", "24h"})


@router.get("")
async def get_trends(
    window: str = Query("1h"),
    limit: int = Query(10, ge=1, le=50),
    redis: Redis | None = Depends(get_redis),
    session: AsyncSession = Depends(get_session),
) -> TrendsResponse:
    if window not in VALID_WINDOWS:
        raise HTTPException(status_code=422, detail="Invalid window parameter. Use '1h' or '24h'.")

    if redis is None:
        return TrendsResponse(trends=[], window=window)

    trend_key = f"trends:{window}"
    results = await redis.zrevrange(trend_key, 0, limit - 1, withscores=True)

    trends: list[TrendItem] = []
    for member, score in results:
        name = member if isinstance(member, str) else member.decode()

        # Look up hashtag_id from database
        stmt = select(Hashtag.hashtag_id).where(Hashtag.name == name)
        db_result = await session.execute(stmt)
        row = db_result.first()
        hashtag_id = row.hashtag_id if row else uuid.UUID(int=0)

        # Get tweet count from Redis (stored as a separate key by the worker)
        tweet_count = await redis.zscore(f"trends:{window}:counts", name)
        count = int(tweet_count) if tweet_count else 0

        trends.append(
            TrendItem(
                hashtag_id=hashtag_id,
                name=name,
                velocity_score=float(score),
                tweet_count=count,
            )
        )

    return TrendsResponse(trends=trends, window=window)
