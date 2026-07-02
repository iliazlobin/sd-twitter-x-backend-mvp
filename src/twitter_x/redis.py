from __future__ import annotations

import logging
from typing import NoReturn

from redis.asyncio import Redis as AsyncRedis  # noqa: N812

from twitter_x.config import settings

logger = logging.getLogger(__name__)

_redis_client: AsyncRedis | None = None


async def init_redis() -> AsyncRedis | None:
    global _redis_client  # noqa: PLW0603
    try:
        client = AsyncRedis.from_url(settings.redis_url, decode_responses=True)
        await client.ping()
        _redis_client = client
        logger.info("Redis connected: %s", settings.redis_url)
        return _redis_client
    except Exception as exc:
        logger.warning("Redis unavailable — running in degraded mode: %s", exc)
        _redis_client = None
        return None


async def close_redis() -> None:
    global _redis_client  # noqa: PLW0603
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


async def get_redis() -> AsyncRedis | None:
    return _redis_client


def require_redis() -> AsyncRedis:
    if _redis_client is None:
        raise RuntimeError("Redis is not available")
    return _redis_client


def _raise_no_redis() -> NoReturn:
    raise RuntimeError("Redis is not available")
