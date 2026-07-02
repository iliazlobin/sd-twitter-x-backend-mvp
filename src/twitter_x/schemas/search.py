from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class SearchResultAuthor(BaseModel):
    user_id: UUID | str
    username: str


class SearchResult(BaseModel):
    type: str  # "tweet" or "hashtag"
    tweet_id: UUID | None = None
    text: str | None = None
    author_id: UUID | str | None = None
    username: str | None = None
    hashtag_id: UUID | str | None = None
    name: str | None = None
    score: float
    tweet_count: int | None = None
    created_at: datetime | None = None
    author: SearchResultAuthor | None = None
    hashtags: list[dict] | None = None


class SearchResponse(BaseModel):
    results: list[dict]  # flexible — items can have extra fields
    next_cursor: str | None
