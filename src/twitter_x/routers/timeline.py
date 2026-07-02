import json
import uuid
from base64 import b64decode, b64encode
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from twitter_x.database import get_session
from twitter_x.models.follow import Follow
from twitter_x.models.hashtag import TweetHashtag
from twitter_x.models.tweet import Tweet
from twitter_x.models.user import User
from twitter_x.schemas.timeline import TimelineItem, TimelineResponse
from twitter_x.schemas.tweet import HashtagItem, TweetAuthor

router = APIRouter(prefix="/api/v1/timeline", tags=["timeline"])

PAGE_SIZE = 20


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
        raise HTTPException(status_code=400, detail="Invalid cursor")


@router.get("/home")
async def home_timeline(
    user_id: uuid.UUID = Query(...),
    cursor: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> TimelineResponse:
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Build query: tweets from followed users, cursor-paginated
    follow_stmt = select(Follow.followee_id).where(Follow.follower_id == user_id)
    follow_result = await session.execute(follow_stmt)
    followee_ids = [row[0] for row in follow_result.all()]

    if not followee_ids:
        return TimelineResponse(tweets=[], next_cursor=None)

    stmt = (
        select(Tweet)
        .where(Tweet.author_id.in_(followee_ids))
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

    items = [
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
        for t in tweets
    ]

    next_cursor = None
    if has_more and tweets:
        last = tweets[-1]
        next_cursor = _encode_cursor(last.created_at, last.tweet_id)

    return TimelineResponse(tweets=items, next_cursor=next_cursor)
