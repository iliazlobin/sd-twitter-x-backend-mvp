from __future__ import annotations

from twitter_x.redis import get_redis


async def get_trends(
    window: str = "1h",
    limit: int = 10,
) -> list[dict]:
    """Get trending topics from Redis ZSET."""
    redis = await get_redis()
    if redis is None:
        return []

    trends_key = f"trends:{window}"
    counts_key = f"trends:{window}:counts"

    # Get top hashtags by velocity score
    raw = await redis.zrevrange(trends_key, 0, limit - 1, withscores=True)

    if not raw:
        return []

    # Get tweet counts
    names = [name for name, _ in raw]
    counts = {}
    if names:
        pipeline = redis.pipeline()
        for name in names:
            pipeline.zscore(counts_key, name)
        count_results = await pipeline.execute()
        for i, name in enumerate(names):
            counts[name] = int(float(count_results[i])) if count_results[i] is not None else 0

    # Build response
    # We don't have hashtag_id in Redis — we'd need a Postgres lookup.
    # For the MVP, we'll include a placeholder. Actually, let's lookup from Postgres.
    trends = []
    for name, score in raw:
        trends.append(
            {
                "hashtag_id": None,  # Will be populated by router
                "name": name,
                "velocity_score": float(score),
                "tweet_count": counts.get(name, 0),
            }
        )

    return trends
