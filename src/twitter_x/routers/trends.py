import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from redis.asyncio import Redis

from twitter_x.redis import get_redis
from twitter_x.schemas.trends import TrendItem, TrendsResponse

router = APIRouter(prefix="/api/v1/trends", tags=["trends"])


@router.get("")
async def get_trends(
    window: str = Query("1h", pattern=r"^(1h|24h)$"),
    limit: int = Query(10, ge=1, le=50),
    redis: Redis | None = Depends(get_redis),
) -> TrendsResponse:
    if window not in ("1h", "24h"):
        raise HTTPException(status_code=422, detail="Invalid window parameter. Use '1h' or '24h'.")

    if redis is None:
        return TrendsResponse(trends=[], window=window)

    trend_key = f"trends:{window}"
    results = await redis.zrevrange(trend_key, 0, limit - 1, withscores=True)

    trends = []
    for name_bytes, score in results:
        name = name_bytes if isinstance(name_bytes, str) else name_bytes.decode()
        trends.append(
            TrendItem(
                hashtag_id=uuid.UUID(int=0),
                name=name,
                velocity_score=float(score),
                tweet_count=0,
            )
        )

    return TrendsResponse(trends=trends, window=window)
