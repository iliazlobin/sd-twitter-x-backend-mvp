"""Fan-out worker — background asyncio task: BRPOP fanout_queue, ZADD to followers."""

import asyncio
import json
from collections.abc import Callable, Coroutine
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from twitter_x.models.follow import Follow

StopFn = Callable[[], Coroutine[Any, Any, None]]


async def fanout_worker_lifespan(
    redis: Redis | None,
    session_factory: async_sessionmaker[AsyncSession],
) -> StopFn:
    """Start the fan-out background task. Returns a stop callback.

    The worker polls the ``fanout_queue`` Redis list every 500ms.
    When a new tweet task arrives (JSON with author_id, tweet_id, created_at),
    it queries Postgres for the author's followers and ZADDs the tweet_id
    to each follower's ``timeline:{follower_id}`` sorted set.

    If Redis is unavailable, the worker sleeps and retries silently
    — the home timeline Postgres fallback handles the cold-cache case.
    """
    stop_event = asyncio.Event()

    async def _run() -> None:
        while not stop_event.is_set():
            try:
                if redis is None:
                    await asyncio.sleep(0.5)
                    continue

                # BRPOP with 500ms timeout
                task_data = await redis.brpop("fanout_queue", timeout=0.5)
                if task_data is None:
                    continue

                # Parse payload: (key, value) from BRPOP
                payload = json.loads(task_data[1])
                author_id = payload["author_id"]
                tweet_id = payload["tweet_id"]
                score = payload["created_at"]  # epoch float

                # Query followers
                async with session_factory() as session:
                    result = await session.execute(
                        select(Follow.follower_id).where(Follow.followee_id == author_id)
                    )
                    follower_ids = [row[0] for row in result.all()]

                if not follower_ids:
                    continue

                # Fan-out to all follower timelines (pipelined)
                pipe = redis.pipeline()
                for fid in follower_ids:
                    pipe.zadd(f"timeline:{fid}", {tweet_id: score})
                await pipe.execute()

            except asyncio.CancelledError:
                break
            except Exception:
                # Transient error (Redis down, DB flake) — retry after cooldown
                await asyncio.sleep(1.0)

    task = asyncio.create_task(_run())

    async def _stop() -> None:
        stop_event.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    return _stop
