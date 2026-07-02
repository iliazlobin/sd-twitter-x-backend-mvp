from collections.abc import AsyncGenerator

import redis.asyncio as aioredis

from twitter_x.config import settings

_redis: aioredis.Redis | None = None
_redis_initialized: bool = False


async def ensure_redis() -> aioredis.Redis | None:
    """Lazy-init Redis client. Returns None if Redis is unavailable."""
    global _redis, _redis_initialized  # noqa: PLW0603
    if not _redis_initialized:
        _redis_initialized = True
        if settings.redis_url and settings.redis_url.strip():
            try:
                client = aioredis.from_url(settings.redis_url, decode_responses=True)
                await client.ping()
                _redis = client
            except Exception:
                _redis = None
    return _redis


async def get_redis() -> AsyncGenerator[aioredis.Redis | None, None]:
    """Dependency for FastAPI endpoints."""
    redis_client = await ensure_redis()
    try:
        yield redis_client
    finally:
        pass


async def close_redis() -> None:
    global _redis  # noqa: PLW0603
    if _redis is not None:
        await _redis.aclose()
        _redis = None
