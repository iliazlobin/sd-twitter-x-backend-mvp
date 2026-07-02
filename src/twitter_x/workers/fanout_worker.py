from __future__ import annotations

import asyncio
import json
import logging

from twitter_x.database import async_session_factory
from twitter_x.models.follow import Follow
from twitter_x.redis import get_redis

logger = logging.getLogger(__name__)


class FanOutWorker:
    """Background asyncio task: BRPOP fanout_queue → ZADD to followers' timelines."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
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
        """Main loop: BRPOP fanout_queue, pipeline ZADD to followers."""
        while True:
            try:
                redis = await get_redis()
                if redis is None:
                    await asyncio.sleep(1)
                    continue

                # Block for up to 500ms waiting for a message
                result = await redis.brpop("fanout_queue", timeout=0.5)
                if result is None:
                    continue

                _, payload = result
                await self._process(payload)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("FanOutWorker error — retrying in 1s")
                await asyncio.sleep(1)

    async def _process(self, payload: str) -> None:
        """Process a single fan-out message."""
        try:
            data = json.loads(payload)
            author_id = data["author_id"]
            tweet_id = data["tweet_id"]
            created_at_str = data.get("created_at") or data.get("created_at")

            # Parse timestamp to get score
            from datetime import datetime

            try:
                score = datetime.fromisoformat(created_at_str).timestamp()
            except (ValueError, TypeError):
                score = 0.0

            # Get followers from Postgres
            from sqlalchemy import select

            async with async_session_factory() as db:
                stmt = select(Follow.follower_id).where(Follow.followee_id == author_id)
                result = await db.execute(stmt)
                follower_ids = [str(row[0]) for row in result]

            if not follower_ids:
                return

            # Pipeline ZADD to all follower timelines
            redis = await get_redis()
            if redis is None:
                return

            pipeline = redis.pipeline()
            for fid in follower_ids:
                pipeline.zadd(f"timeline:{fid}", {tweet_id: score})
            await pipeline.execute()

            logger.debug("FanOut: tweet %s → %d followers", tweet_id[:8], len(follower_ids))

        except Exception:
            logger.exception("FanOutWorker failed to process payload")
