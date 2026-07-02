from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class TimelineItemAuthor(BaseModel):
    user_id: UUID
    username: str


class TimelineItem(BaseModel):
    tweet_id: UUID
    author_id: UUID
    username: str
    text: str
    created_at: datetime
    author: TimelineItemAuthor | None = None


class TimelineResponse(BaseModel):
    tweets: list[dict]  # flexible — items can have extra fields
    next_cursor: str | None
