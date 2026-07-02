from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from twitter_x.database import get_session
from twitter_x.models.hashtag import Hashtag
from twitter_x.schemas.trends import TrendItem, TrendsResponse
from twitter_x.services.trending_service import get_trends

trends_router = APIRouter(prefix="/api/v1/trends", tags=["trends"])


@trends_router.get("", response_model=TrendsResponse)
async def trends(
    window: str = Query("1h", pattern=r"^(1h|24h)$"),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_session),
) -> TrendsResponse:
    """Get trending topics with velocity-based scoring."""
    raw_trends = await get_trends(window, limit)

    # Enrich with hashtag_id from Postgres
    trends_list = []
    for item in raw_trends:
        # Look up hashtag_id
        stmt = select(Hashtag).where(Hashtag.name == item["name"])
        result = await db.execute(stmt)
        ht = result.scalar_one_or_none()

        trends_list.append(
            TrendItem(
                hashtag_id=ht.hashtag_id if ht else None,
                name=item["name"],
                velocity_score=item["velocity_score"],
                tweet_count=item["tweet_count"],
            )
        )

    return TrendsResponse(window=window, trends=trends_list)
