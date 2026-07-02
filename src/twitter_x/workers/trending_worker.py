"""Trending worker — background asyncio task: compute velocity scores every 60s."""

import asyncio
import math
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from twitter_x.models.hashtag import Hashtag, TweetHashtag
from twitter_x.models.tweet import Tweet

StopFn = Callable[[], Coroutine[Any, Any, None]]

WINDOWS = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
}


async def trending_worker_lifespan(
    redis: Redis | None,
    session_factory: async_sessionmaker[AsyncSession],
) -> StopFn:
    """Start the trending computation background task. Returns a stop callback.

    Every 60s, counts hashtag occurrences in two sliding windows
    (recent and baseline) and computes velocity scores:
      score = count_recent / max(count_baseline, 1) * log(1 + count_recent)

    Results are written to Redis sorted sets ``trends:1h`` and ``trends:24h``.
    If Redis is unavailable, computation is skipped but the worker keeps polling.
    """
    stop_event = asyncio.Event()

    async def _compute_window(
        session: AsyncSession,
        window_key: str,
        window_delta: timedelta,
    ) -> None:
        if redis is None:
            return

        now = datetime.now(datetime.UTC)
        recent_start = now - window_delta
        baseline_start = now - 2 * window_delta
        baseline_end = now - window_delta

        async def _count_hashtags(since: datetime, until: datetime) -> dict[str, int]:
            stmt = (
                select(Hashtag.name, func.count(Hashtag.name).label("cnt"))
                .select_from(TweetHashtag)
                .join(Tweet, TweetHashtag.tweet_id == Tweet.tweet_id)
                .join(Hashtag, TweetHashtag.hashtag_id == Hashtag.hashtag_id)
                .where(Tweet.created_at >= since, Tweet.created_at < until)
                .group_by(Hashtag.name)
            )
            result = await session.execute(stmt)
            return {row.name: row.cnt for row in result.all()}

        recent = await _count_hashtags(recent_start, now)
        baseline = await _count_hashtags(baseline_start, baseline_end)

        pipe = redis.pipeline()
        # Delete old scores and counts before repopulating
        pipe.delete(f"trends:{window_key}")
        pipe.delete(f"trends:{window_key}:counts")

        all_names = set(recent.keys()) | set(baseline.keys())
        for name in all_names:
            r = recent.get(name, 0)
            b = baseline.get(name, 0)
            score = (r / max(b, 1)) * math.log(1 + r)
            if score > 0:
                pipe.zadd(f"trends:{window_key}", {name: score})
                pipe.zadd(f"trends:{window_key}:counts", {name: r})

        await pipe.execute()

    async def _run() -> None:
        # Sleep a bit on startup to let DB/Redis settle
        await asyncio.sleep(5)

        while not stop_event.is_set():
            try:
                async with session_factory() as session:
                    for window_key, window_delta in WINDOWS.items():
                        await _compute_window(session, window_key, window_delta)
            except asyncio.CancelledError:
                break
            except Exception:
                pass

            # Sleep 60s between computations
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=60)
            except TimeoutError:
                pass

    task = asyncio.create_task(_run())

    async def _stop() -> None:
        stop_event.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    return _stop
