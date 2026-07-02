from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from twitter_x.database import async_session_factory
from twitter_x.models.hashtag import Hashtag, TweetHashtag
from twitter_x.models.tweet import Tweet
from twitter_x.redis import get_redis

logger = logging.getLogger(__name__)

WINDOWS = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
}


class TrendingWorker:
    """Background asyncio task: 60s poll → velocity scores → Redis ZSET."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        await asyncio.sleep(5)  # Initial delay for DB/Redis readiness
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        """Main loop: compute velocity scores every 60s."""
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("TrendingWorker error — retrying in 10s")
                await asyncio.sleep(10)
                continue

            await asyncio.sleep(60)

    async def _tick(self) -> None:
        """Compute velocity scores for all windows."""
        now = datetime.now(timezone.utc)

        for window_name, window_delta in WINDOWS.items():
            scores = await self._compute_window(window_name, window_delta, now)
            if scores:
                redis = await get_redis()
                if redis is None:
                    return

                trends_key = f"trends:{window_name}"
                counts_key = f"trends:{window_name}:counts"

                pipeline = redis.pipeline()
                pipeline.delete(trends_key)
                pipeline.delete(counts_key)

                for name, velocity, count in scores:
                    pipeline.zadd(trends_key, {name: velocity})
                    pipeline.zadd(counts_key, {name: count})

                await pipeline.execute()

                logger.debug(
                    "TrendingWorker: %s — %d hashtags scored",
                    window_name,
                    len(scores),
                )

    async def _compute_window(
        self, window_name: str, window_delta: timedelta, now: datetime
    ) -> list[tuple[str, float, int]]:
        """Compute velocity scores for a time window."""
        recent_start = now - window_delta
        baseline_start = now - 2 * window_delta

        async with async_session_factory() as db:
            # Get recent tweet counts per hashtag
            recent_counts = await self._count_hashtags_in_range(db, recent_start, now)
            baseline_counts = await self._count_hashtags_in_range(db, baseline_start, recent_start)

        if not recent_counts:
            return []

        scores = []
        for name, recent in recent_counts.items():
            baseline = baseline_counts.get(name, 0)
            velocity = (recent / max(baseline, 1)) * math.log(1 + recent)
            scores.append((name, velocity, recent))

        # Sort by velocity descending
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores

    async def _count_hashtags_in_range(self, db, start: datetime, end: datetime) -> dict[str, int]:
        """Count hashtag occurrences in a time range."""
        stmt = (
            select(Hashtag.name, func.count(TweetHashtag.tweet_id).label("count"))
            .join(TweetHashtag, TweetHashtag.hashtag_id == Hashtag.hashtag_id)
            .join(
                Tweet,
                Tweet.tweet_id == TweetHashtag.tweet_id,
            )
            .where(
                Tweet.created_at >= start,
                Tweet.created_at < end,
            )
            .group_by(Hashtag.name)
        )
        result = await db.execute(stmt)
        return {row[0]: row[1] for row in result}
