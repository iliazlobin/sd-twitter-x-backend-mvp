"""Trending service — velocity scorer, windowed count queries, Redis ZSET update."""

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession


class TrendingService:
    def __init__(self, session: AsyncSession, redis: Redis | None = None) -> None:
        self.session = session
        self.redis = redis

    async def compute_trends(self) -> None:
        """Compute trending scores for 1h and 24h windows. Stub until staff task."""
        pass

    async def get_trends(
        self,
        window: str = "1h",
        limit: int = 10,
    ) -> list[dict]:
        """Return top trending hashtags. Stub until staff task."""
        return []
