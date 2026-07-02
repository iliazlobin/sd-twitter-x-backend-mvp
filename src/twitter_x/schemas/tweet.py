import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class HashtagItem(BaseModel):
    hashtag_id: uuid.UUID
    name: str


class TweetCreate(BaseModel):
    author_id: uuid.UUID
    text: str = Field(..., min_length=1, max_length=280)
    hashtags: list[str] | None = None


class TweetResponse(BaseModel):
    tweet_id: uuid.UUID
    author_id: uuid.UUID
    text: str
    hashtags: list[HashtagItem]
    created_at: datetime

    model_config = {"from_attributes": True}


class TweetAuthor(BaseModel):
    user_id: uuid.UUID
    username: str
    display_name: str | None


class TweetDetail(BaseModel):
    tweet_id: uuid.UUID
    text: str
    author: TweetAuthor
    hashtags: list[HashtagItem]
    created_at: datetime

    model_config = {"from_attributes": True}
