import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from twitter_x.database import get_session
from twitter_x.models.hashtag import Hashtag, TweetHashtag
from twitter_x.models.tweet import Tweet
from twitter_x.models.user import User
from twitter_x.schemas.tweet import HashtagItem, TweetCreate, TweetDetail, TweetResponse

router = APIRouter(prefix="/api/v1/tweets", tags=["tweets"])


def _extract_hashtags(text: str) -> set[str]:
    """Extract unique lowercased hashtag names from tweet text."""
    import re

    return {tag.lower() for tag in re.findall(r"#(\w+)", text)}


@router.post("", status_code=201)
async def create_tweet(
    body: TweetCreate,
    session: AsyncSession = Depends(get_session),
) -> TweetResponse:
    author = await session.get(User, body.author_id)
    if not author:
        raise HTTPException(status_code=404, detail="Author not found")

    # Extract hashtags from text and merge with client-supplied
    tag_names = _extract_hashtags(body.text)
    if body.hashtags:
        tag_names.update(h.lower() for h in body.hashtags)

    tweet = Tweet(author_id=body.author_id, text=body.text)
    session.add(tweet)
    await session.flush()

    hashtag_items: list[HashtagItem] = []
    for name in tag_names:
        stmt = select(Hashtag).where(Hashtag.name == name)
        result = await session.execute(stmt)
        hashtag = result.scalar_one_or_none()
        if not hashtag:
            hashtag = Hashtag(name=name)
            session.add(hashtag)
            await session.flush()

        session.add(TweetHashtag(tweet_id=tweet.tweet_id, hashtag_id=hashtag.hashtag_id))
        hashtag_items.append(HashtagItem(hashtag_id=hashtag.hashtag_id, name=hashtag.name))

    await session.commit()
    await session.refresh(tweet)

    return TweetResponse(
        tweet_id=tweet.tweet_id,
        author_id=tweet.author_id,
        text=tweet.text,
        hashtags=hashtag_items,
        created_at=tweet.created_at,
    )


@router.get("/{tweet_id}")
async def get_tweet(
    tweet_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> TweetDetail:
    stmt = (
        select(Tweet)
        .where(Tweet.tweet_id == tweet_id)
        .options(
            selectinload(Tweet.author),
            selectinload(Tweet.hashtags).selectinload(TweetHashtag.hashtag),
        )
    )
    result = await session.execute(stmt)
    tweet = result.scalar_one_or_none()
    if not tweet:
        raise HTTPException(status_code=404, detail="Tweet not found")

    return TweetDetail(
        tweet_id=tweet.tweet_id,
        text=tweet.text,
        author={
            "user_id": tweet.author.user_id,
            "username": tweet.author.username,
            "display_name": tweet.author.display_name,
        },
        hashtags=[
            HashtagItem(hashtag_id=th.hashtag.hashtag_id, name=th.hashtag.name)
            for th in tweet.hashtags
        ],
        created_at=tweet.created_at,
    )
