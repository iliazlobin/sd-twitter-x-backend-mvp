import json
import uuid
from base64 import b64decode, b64encode
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from twitter_x.database import get_session
from twitter_x.models.follow import Follow
from twitter_x.models.hashtag import TweetHashtag
from twitter_x.models.tweet import Tweet
from twitter_x.models.user import User
from twitter_x.redis import get_redis
from twitter_x.schemas.common import FollowResponse
from twitter_x.schemas.timeline import TimelineItem, TimelineResponse
from twitter_x.schemas.tweet import HashtagItem, TweetAuthor
from twitter_x.schemas.user import UserCreate, UserResponse

router = APIRouter(prefix="/api/v1/users", tags=["users"])

PAGE_SIZE = 20
BACKFILL_LIMIT = 50


def _encode_cursor(created_at: datetime, tweet_id: uuid.UUID) -> str:
    payload = json.dumps(
        {"created_at": created_at.isoformat(), "tweet_id": str(tweet_id)},
        separators=(",", ":"),
    )
    return b64encode(payload.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        payload = json.loads(b64decode(cursor.encode()).decode())
        created_at = datetime.fromisoformat(payload["created_at"])
        tweet_id = uuid.UUID(payload["tweet_id"])
        return created_at, tweet_id
    except (ValueError, KeyError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Invalid cursor") from None


async def _backfill_timeline(
    redis: Redis,
    follower_id: uuid.UUID,
    followee_id: uuid.UUID,
    session: AsyncSession,
) -> None:
    """Pre-populate follower's Redis timeline with followee's recent tweets."""
    try:
        stmt = (
            select(Tweet.tweet_id, Tweet.created_at)
            .where(Tweet.author_id == followee_id)
            .order_by(Tweet.created_at.desc())
            .limit(BACKFILL_LIMIT)
        )
        result = await session.execute(stmt)
        rows = result.all()
        if rows:
            mapping = {str(row.tweet_id): row.created_at.timestamp() for row in rows}
            await redis.zadd(f"timeline:{follower_id}", mapping)
    except Exception:
        # Best-effort; timeline works via Postgres fallback
        pass


async def _cleanup_timeline(
    redis: Redis,
    follower_id: uuid.UUID,
    followee_id: uuid.UUID,
    session: AsyncSession,
) -> None:
    """Remove followee's tweets from follower's Redis timeline."""
    try:
        stmt = select(Tweet.tweet_id).where(Tweet.author_id == followee_id)
        result = await session.execute(stmt)
        tweet_ids = [str(row.tweet_id) for row in result.all()]
        if tweet_ids:
            await redis.zrem(f"timeline:{follower_id}", *tweet_ids)
    except Exception:
        # Best-effort; timeline works via Postgres fallback
        pass


@router.post("", status_code=201)
async def create_user(
    body: UserCreate,
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    existing = await session.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Username already taken")

    user = User(username=body.username, display_name=body.display_name)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return UserResponse.model_validate(user)


@router.get("/{user_id}")
async def get_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.model_validate(user)


@router.get("/{user_id}/tweets")
async def get_user_tweets(
    user_id: uuid.UUID,
    cursor: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> TimelineResponse:
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    stmt = (
        select(Tweet)
        .where(Tweet.author_id == user_id)
        .options(
            selectinload(Tweet.author),
            selectinload(Tweet.hashtags).selectinload(TweetHashtag.hashtag),
        )
        .order_by(Tweet.created_at.desc(), Tweet.tweet_id.desc())
        .limit(PAGE_SIZE + 1)
    )

    if cursor:
        cursor_created_at, cursor_tweet_id = _decode_cursor(cursor)
        stmt = stmt.where(
            (Tweet.created_at < cursor_created_at)
            | ((Tweet.created_at == cursor_created_at) & (Tweet.tweet_id < cursor_tweet_id))
        )

    result = await session.execute(stmt)
    tweets = result.scalars().all()

    has_more = len(tweets) > PAGE_SIZE
    if has_more:
        tweets = tweets[:PAGE_SIZE]

    items: list[TimelineItem] = []
    for t in tweets:
        items.append(
            TimelineItem(
                tweet_id=t.tweet_id,
                text=t.text,
                author=TweetAuthor(
                    user_id=t.author.user_id,
                    username=t.author.username,
                    display_name=t.author.display_name,
                ),
                hashtags=[
                    HashtagItem(hashtag_id=th.hashtag.hashtag_id, name=th.hashtag.name)
                    for th in t.hashtags
                ],
                created_at=t.created_at,
            )
        )

    next_cursor = None
    if has_more and tweets:
        last = tweets[-1]
        next_cursor = _encode_cursor(last.created_at, last.tweet_id)

    return TimelineResponse(tweets=items, next_cursor=next_cursor)


@router.post("/{followee_id}/follow")
async def follow_user(
    followee_id: uuid.UUID,
    follower_id: uuid.UUID = Query(...),
    session: AsyncSession = Depends(get_session),
    redis: Redis | None = Depends(get_redis),
) -> FollowResponse:
    if follower_id == followee_id:
        raise HTTPException(status_code=422, detail="Cannot follow yourself")

    follower = await session.get(User, follower_id)
    followee = await session.get(User, followee_id)
    if not follower or not followee:
        raise HTTPException(status_code=404, detail="User not found")

    existing = await session.execute(
        select(Follow).where(Follow.follower_id == follower_id, Follow.followee_id == followee_id)
    )
    if existing.scalar_one_or_none():
        return FollowResponse(status="following")

    session.add(Follow(follower_id=follower_id, followee_id=followee_id))
    follower.following_count += 1
    followee.follower_count += 1
    await session.commit()

    # Best-effort: backfill followee's recent tweets into follower's timeline
    if redis is not None:
        await _backfill_timeline(redis, follower_id, followee_id, session)

    return FollowResponse(status="following")


@router.delete("/{followee_id}/follow")
async def unfollow_user(
    followee_id: uuid.UUID,
    follower_id: uuid.UUID = Query(...),
    session: AsyncSession = Depends(get_session),
    redis: Redis | None = Depends(get_redis),
) -> FollowResponse:
    follower = await session.get(User, follower_id)
    followee = await session.get(User, followee_id)
    if not follower or not followee:
        raise HTTPException(status_code=404, detail="User not found")

    result = await session.execute(
        select(Follow).where(Follow.follower_id == follower_id, Follow.followee_id == followee_id)
    )
    follow = result.scalar_one_or_none()
    if not follow:
        return FollowResponse(status="unfollowed")

    await session.delete(follow)
    follower.following_count = max(0, follower.following_count - 1)
    followee.follower_count = max(0, followee.follower_count - 1)
    await session.commit()

    # Best-effort: remove followee's tweets from follower's timeline
    if redis is not None:
        await _cleanup_timeline(redis, follower_id, followee_id, session)

    return FollowResponse(status="unfollowed")
