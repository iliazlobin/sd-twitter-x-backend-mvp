from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class HashtagItem(BaseModel):
    hashtag_id: UUID
    name: str


class TweetCreate(BaseModel):
    author_id: UUID
    text: str = Field(..., min_length=1, max_length=280)
    hashtags: list[str] | None = None


class TweetResponse(BaseModel):
    tweet_id: UUID
    author_id: UUID
    text: str
    hashtags: list[HashtagItem]
    created_at: datetime


class TweetAuthor(BaseModel):
    user_id: UUID
    username: str


class TweetDetail(BaseModel):
    tweet_id: UUID
    text: str
    author: TweetAuthor
    hashtags: list[HashtagItem]
    created_at: datetime
