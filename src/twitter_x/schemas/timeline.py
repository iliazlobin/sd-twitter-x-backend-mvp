import uuid
from datetime import datetime

from pydantic import BaseModel

from twitter_x.schemas.tweet import HashtagItem, TweetAuthor


class TimelineItem(BaseModel):
    tweet_id: uuid.UUID
    text: str
    author: TweetAuthor
    hashtags: list[HashtagItem]
    created_at: datetime


class TimelineResponse(BaseModel):
    tweets: list[TimelineItem]
    next_cursor: str | None
