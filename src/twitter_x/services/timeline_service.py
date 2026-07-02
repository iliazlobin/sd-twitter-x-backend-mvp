"""Timeline service — Redis ZSET read + Postgres fallback, cursor encode/decode."""

import json
import uuid
from base64 import b64decode, b64encode
from datetime import datetime

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from twitter_x.models.follow import Follow
from twitter_x.models.tweet import Tweet

PAGE_SIZE = 20


class TimelineService:
    def __init__(self, session: AsyncSession, redis: Redis | None = None) -> None:
        self.session = session
        self.redis = redis

    def encode_cursor(self, created_at: datetime, tweet_id: uuid.UUID) -> str:
        payload = json.dumps(
            {"created_at": created_at.isoformat(), "tweet_id": str(tweet_id)},
            separators=(",", ":"),
        )
        return b64encode(payload.encode()).decode()

    def decode_cursor(self, cursor: str) -> tuple[datetime, uuid.UUID]:
        from fastapi import HTTPException

        try:
            payload = json.loads(b64decode(cursor.encode()).decode())
            created_at = datetime.fromisoformat(payload["created_at"])
            tweet_id = uuid.UUID(payload["tweet_id"])
            return created_at, tweet_id
        except (ValueError, KeyError, json.JSONDecodeError):
            raise HTTPException(status_code=400, detail="Invalid cursor")

    async def get_home_timeline(
        self,
        user_id: uuid.UUID,
        cursor: str | None = None,
    ) -> tuple[list[Tweet], str | None]:
        follow_stmt = select(Follow.followee_id).where(Follow.follower_id == user_id)
        result = await self.session.execute(follow_stmt)
        followee_ids = [row[0] for row in result.all()]

        if not followee_ids:
            return [], None

        stmt = (
            select(Tweet)
            .where(Tweet.author_id.in_(followee_ids))
            .order_by(Tweet.created_at.desc(), Tweet.tweet_id.desc())
            .limit(PAGE_SIZE + 1)
        )

        if cursor:
            cursor_created_at, cursor_tweet_id = self.decode_cursor(cursor)
            stmt = stmt.where(
                (Tweet.created_at < cursor_created_at)
                | ((Tweet.created_at == cursor_created_at) & (Tweet.tweet_id < cursor_tweet_id))
            )

        rows = (await self.session.execute(stmt)).scalars().all()

        has_more = len(rows) > PAGE_SIZE
        if has_more:
            rows = rows[:PAGE_SIZE]

        next_cursor = None
        if has_more and rows:
            last = rows[-1]
            next_cursor = self.encode_cursor(last.created_at, last.tweet_id)

        return list(rows), next_cursor
